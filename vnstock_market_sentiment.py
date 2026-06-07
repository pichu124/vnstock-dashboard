"""vnstock_market_sentiment.py — Composite market-mood ("tâm lý thị trường").

Synthesises signals that already live in the warehouse into ONE short-term
sentiment reading the AI brief can reason about, instead of leaving them as
scattered raw numbers:

  • Market breadth   — % cổ phiếu trên MA200, A/D ratio
  • Foreign flow     — NN ròng 1D (tỷ VND)
  • VNINDEX momentum — RSI(14), vị trí giá vs MA20/50/200, % thay đổi phiên
  • News sentiment   — % tin tích cực/tiêu cực toàn thị trường 7 ngày
                       (đọc cache đã chấm điểm; KHÔNG tự chấm để khỏi tốn token)

Output: a "mood" label + a momentum score in -100..+100 + the per-signal
breakdown. Pure-function core (`compute_market_sentiment`) is unit-tested;
`load_market_sentiment` gathers the inputs from caches for the brief.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).parent


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _dir(score: float) -> int:
    """Coarse direction of a normalised [-1,1] signal for display."""
    return 1 if score > 0.15 else (-1 if score < -0.15 else 0)


# Mood thresholds on the -100..+100 momentum scale.
_MOODS = (
    (50,   "🔥 Hưng phấn"),
    (20,   "📈 Tích cực"),
    (-20,  "⚖️ Thận trọng"),
    (-50,  "📉 Tiêu cực"),
    (-101, "❄️ Sợ hãi"),
)


def _mood_label(momentum: float) -> str:
    for thr, label in _MOODS:
        if momentum >= thr:
            return label
    return "❄️ Sợ hãi"


def compute_market_sentiment(
    breadth: dict | None = None,
    nn_net: float | None = None,
    vnindex_tech: dict | None = None,
    news_sentiment: dict | None = None,
) -> dict:
    """Combine breadth + foreign flow + index momentum + news into one mood.

    Each input is optional; only the signals with data are weighted (weights
    renormalise over what's available). Returns:
      {mood, momentum (-100..+100), signals[], news, n_signals}
    or {} when no signal at all is available.
    """
    breadth = breadth or {}
    vnindex_tech = vnindex_tech or {}
    signals: list[dict] = []
    weighted = 0.0
    wsum = 0.0

    def add(name: str, value: str, score: float, weight: float):
        nonlocal weighted, wsum
        score = _clamp(score)
        signals.append({"name": name, "value": value, "dir": _dir(score),
                        "score": round(score, 2)})
        weighted += score * weight
        wsum += weight

    # 1. Breadth — % cổ phiếu trên MA200 (55% bull / 35% bear)
    ma200 = breadth.get("above_ma200_pct")
    if ma200 is not None:
        try:
            ma200 = float(ma200)
            add("Breadth (% trên MA200)", f"{ma200:.0f}%",
                (ma200 - 45) / 10.0, 0.20)
        except (TypeError, ValueError):
            pass

    # 2. A/D ratio (1.5 bull / 0.7 bear, centred ~1.1)
    ad = breadth.get("ad_ratio")
    if ad is not None:
        try:
            ad = float(ad)
            add("A/D ratio", f"{ad:.2f}", (ad - 1.1) / 0.4, 0.15)
        except (TypeError, ValueError):
            pass

    # 3. Foreign net flow 1D (±100 tỷ saturates)
    if nn_net is not None:
        try:
            nn = float(nn_net)
            sign = "+" if nn >= 0 else ""
            add("NN ròng 1D", f"{sign}{nn:,.0f} tỷ", nn / 100.0, 0.20)
        except (TypeError, ValueError):
            pass

    # 4. VNINDEX RSI(14) (70 bull / 30 bear)
    rsi = vnindex_tech.get("rsi14")
    if rsi is not None:
        try:
            rsi = float(rsi)
            add("RSI VNINDEX", f"{rsi:.0f}", (rsi - 50) / 20.0, 0.10)
        except (TypeError, ValueError):
            pass

    # 5. Price vs MA20/50/200 (how many the index trades above)
    close = vnindex_tech.get("close")
    if close:
        above = 0
        have = 0
        for k in ("ma20", "ma50", "ma200"):
            v = vnindex_tech.get(k)
            if v:
                have += 1
                if close >= v:
                    above += 1
        if have:
            add("Giá vs MA", f"trên {above}/{have}",
                (above / have - 0.5) * 2, 0.15)

    # 6. Intraday move (% thay đổi phiên, ±1% saturates)
    dchg = vnindex_tech.get("day_change_pct")
    if dchg is not None:
        try:
            dchg = float(dchg)
            add("Thay đổi phiên", f"{dchg:+.1f}%", dchg / 1.0, 0.05)
        except (TypeError, ValueError):
            pass

    # 7. News sentiment 7D (net % tích cực, ±50% saturates).
    # VN corporate-disclosure feeds are dominated by procedural filings that
    # are genuinely neutral, so show raw counts + flag when neutral dominates
    # rather than tiny pos/neg percentages that look like noise.
    ns = news_sentiment or {}
    if ns.get("total"):
        net_pct = ns.get("net_pct", 0.0)
        tot = ns.get("total", 0)
        neu = ns.get("neutral", 0)
        neu_pct = round(neu / tot * 100) if tot else 0
        val = (f"{ns.get('positive', 0)} tích cực / {ns.get('negative', 0)} tiêu cực "
               f"/ {tot} tin")
        if neu_pct >= 80:
            val += f" — đa số trung lập ({neu_pct}%, tin công bố thông tin)"
        add("Tin tức 7N", val, net_pct / 50.0, 0.15)

    if wsum == 0:
        return {}

    momentum = round(weighted / wsum * 100)
    return {
        "mood":      _mood_label(momentum),
        "momentum":  momentum,
        "signals":   signals,
        "news":      ns,
        "n_signals": len(signals),
    }


def _load_news_sentiment(days: int = 7) -> dict:
    """Best-effort market-wide news sentiment from the scored cache.

    Reads only — never triggers LLM scoring. Empty dict if the news cache or
    sentiment cache is missing/unscored.
    """
    try:
        from vnstock_news import load_news_cache
        from vnstock_sentiment import attach_sentiments, market_news_sentiment
        news = load_news_cache()
        if not news:
            return {}
        attach_sentiments(news)
        return market_news_sentiment(news, days=days)
    except Exception:
        return {}


def _load_breadth() -> dict:
    try:
        import json
        p = _REPO / "data_warehouse" / "_meta" / "market_overview.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("breadth", {}) or {}
    except Exception:
        return {}


def _load_nn_net_1d() -> float | None:
    try:
        from vnstock_regime import _load_nn_net_1d as _nn
        return _nn()
    except Exception:
        return None


def load_market_sentiment(
    vnindex_tech: dict | None = None,
    breadth: dict | None = None,
    news_days: int = 7,
) -> dict:
    """Gather inputs from caches and compute the composite mood.

    The brief passes its already-fetched ``vnindex_tech`` / ``breadth`` to
    avoid recomputation; both fall back to cache loads when omitted.
    """
    if breadth is None:
        breadth = _load_breadth()
    return compute_market_sentiment(
        breadth=breadth,
        nn_net=_load_nn_net_1d(),
        vnindex_tech=vnindex_tech or {},
        news_sentiment=_load_news_sentiment(days=news_days),
    )
