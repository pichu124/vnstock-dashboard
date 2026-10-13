"""vnstock_regime.py — Market regime classifier for VNStock Dashboard.

Synthesises VNINDEX technicals + market breadth + NN foreign flow into
a single regime label and suggests matching screener presets.

Regimes (5 states):
  🔥 Bull       — strong bull, risk-on
  📈 Tích cực   — bullish bias
  ⚖️ Sideways   — ranging, no clear trend
  📉 Tiêu cực   — bearish bias
  ❄️ Bear       — strong bear, risk-off
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_REPO = Path(__file__).parent

# ── Preset suggestions per regime ─────────────────────────────────────────

PRESET_SUGGESTIONS: dict[str, list[str]] = {
    "bull":     ["momentum", "breakout", "strong_uptrend", "volume_surge"],
    "bullish":  ["momentum", "golden_cross", "volume_surge"],
    "sideways": ["golden_cross", "volume_surge", "reversal"],
    "bearish":  ["oversold", "reversal"],
    "bear":     ["oversold", "reversal"],
}

REGIME_META: dict[str, dict] = {
    "bull":     {"label": "🔥 Bull — Risk-on",      "color": "#22c55e", "bg": "#14532d"},
    "bullish":  {"label": "📈 Tích cực",             "color": "#86efac", "bg": "#166534"},
    "sideways": {"label": "⚖️ Sideways / Phân hoá",  "color": "#fbbf24", "bg": "#78350f"},
    "bearish":  {"label": "📉 Tiêu cực",             "color": "#fca5a5", "bg": "#7f1d1d"},
    "bear":     {"label": "❄️ Bear — Risk-off",       "color": "#ef4444", "bg": "#450a0a"},
}

# Preset display names
PRESET_DISPLAY: dict[str, str] = {
    "momentum":       "⚡ Momentum",
    "breakout":       "🚀 Breakout",
    "strong_uptrend": "📈 Strong uptrend",
    "volume_surge":   "💥 Volume surge",
    "golden_cross":   "✨ Golden cross",
    "oversold":       "🟢 Oversold",
    "reversal":       "↩️ Reversal",
    "overbought":     "🔴 Overbought",
}


# ── Data loaders ──────────────────────────────────────────────────────────

def _load_vnindex_tech() -> dict:
    """Load VNINDEX technicals — reuses battle-tested _vnindex_technicals()
    from vnstock_brief, which already handles warehouse path, price-unit
    normalisation and all edge cases."""
    try:
        from vnstock_brief import _vnindex_technicals
        return _vnindex_technicals()
    except Exception:
        return {}


def _load_breadth() -> dict:
    """Load market breadth from market_overview.json."""
    try:
        p = _REPO / "data_warehouse" / "_meta" / "market_overview.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("breadth", data)
    except Exception:
        return {}


def _load_nn_net_1d(effective_date: "str | None" = None) -> float:
    """Total NN ròng (tỷ VND) for the effective trading day.

    Prefers the FULL-market per-date source (vnstock_foreign_flow). The legacy
    top-100 cache (nn_flow_cache.json) overstated net selling AND was refreshed
    only by the Streamlit dashboard, so the brief showed a frozen value as
    "phiên hôm nay" (observed 12/06: -665 for two different sessions). Returns
    0.0 (→ the sentiment signal is omitted) when no fresh full-market figure
    exists for the date, rather than presenting a stale/biased number.
    """
    try:
        from vnstock_foreign_flow import load_market_net_1d
        v = load_market_net_1d(effective_date)
        if v is not None:
            return round(float(v), 1)
    except Exception:
        pass
    return 0.0


# ── Core classifier ───────────────────────────────────────────────────────

def classify_regime(
    vnindex_tech: dict | None = None,
    breadth: dict | None = None,
    nn_net_1d: float | None = None,
) -> dict[str, Any]:
    """
    Score 7 signals → determine regime + suggest presets.

    Returns dict with:
      regime, label, color, bg, score, confidence, signals, suggested_presets
    """
    if vnindex_tech is None:
        vnindex_tech = _load_vnindex_tech()
    if breadth is None:
        breadth = _load_breadth()
    if nn_net_1d is None:
        nn_net_1d = _load_nn_net_1d(_nn_session(vnindex_tech))

    signals: list[dict] = []
    score = 0

    def _sig(name: str, value: str, direction: int, detail: str = "") -> None:
        signals.append({
            "name": name, "value": value,
            "direction": direction,   # +1 bull, -1 bear, 0 neutral
            "detail": detail,
        })
        nonlocal score
        score += direction

    c     = vnindex_tech.get("close")
    ma20  = vnindex_tech.get("ma20")
    ma50  = vnindex_tech.get("ma50")
    ma200 = vnindex_tech.get("ma200")
    rsi   = vnindex_tech.get("rsi14")

    def _ma_dir(d: float) -> int:
        # Treat ±0.1% band as neutral so a flat market doesn't score bearish.
        if d > 0.1:
            return 1
        if d < -0.1:
            return -1
        return 0

    # Signal 1 — VNINDEX vs MA20
    if c and ma20:
        d = (c / ma20 - 1) * 100
        _sig("VNINDEX / MA20", f"{d:+.1f}%", _ma_dir(d),
             f"{'Trên' if d > 0 else 'Dưới' if d < 0 else 'Ngang'} MA20 ({ma20:,.0f})")

    # Signal 2 — VNINDEX vs MA50
    if c and ma50:
        d = (c / ma50 - 1) * 100
        _sig("VNINDEX / MA50", f"{d:+.1f}%", _ma_dir(d),
             f"{'Trên' if d > 0 else 'Dưới' if d < 0 else 'Ngang'} MA50 ({ma50:,.0f})")

    # Signal 3 — VNINDEX vs MA200
    if c and ma200:
        d = (c / ma200 - 1) * 100
        _sig("VNINDEX / MA200", f"{d:+.1f}%", _ma_dir(d),
             f"{'Trên' if d > 0 else 'Dưới' if d < 0 else 'Ngang'} MA200 ({ma200:,.0f})")

    # Signal 4 — RSI14
    if rsi is not None:
        if rsi > 60:
            _sig("RSI14", f"{rsi:.0f}", 1, "Momentum tích cực")
        elif rsi < 40:
            _sig("RSI14", f"{rsi:.0f}", -1, "Momentum yếu")
        else:
            _sig("RSI14", f"{rsi:.0f}", 0, "Trung tính")

    # Signal 5 — Breadth: % trên MA200
    pct_ma200 = breadth.get("above_ma200_pct")
    if pct_ma200 is not None:
        if pct_ma200 > 55:
            _sig("Breadth MA200", f"{pct_ma200:.0f}%", 1, "Đa số mã trên MA200")
        elif pct_ma200 < 35:
            _sig("Breadth MA200", f"{pct_ma200:.0f}%", -1, "Đa số mã dưới MA200")
        else:
            _sig("Breadth MA200", f"{pct_ma200:.0f}%", 0, "Phân hoá")

    # Signal 6 — Advance/Decline ratio (only if real data present)
    advances = breadth.get("advances")
    declines = breadth.get("declines")
    if advances is not None and declines is not None:
        ad_ratio = advances / max(int(declines), 1)
        if ad_ratio > 1.5:
            _sig("A/D ratio", f"{ad_ratio:.1f}", 1, f"{advances} tăng / {declines} giảm")
        elif ad_ratio < 0.7:
            _sig("A/D ratio", f"{ad_ratio:.1f}", -1, f"{advances} tăng / {declines} giảm")
        else:
            _sig("A/D ratio", f"{ad_ratio:.1f}", 0, f"{advances} tăng / {declines} giảm")

    # Signal 7 — NN flow 1D
    if nn_net_1d != 0:
        if nn_net_1d > 100:
            _sig("NN ròng 1D", f"+{nn_net_1d:.0f} tỷ", 1, "Khối ngoại đang mua ròng")
        elif nn_net_1d < -100:
            _sig("NN ròng 1D", f"{nn_net_1d:.0f} tỷ", -1, "Khối ngoại đang bán ròng")
        else:
            _sig("NN ròng 1D", f"{nn_net_1d:+.0f} tỷ", 0, "NN ròng nhỏ")

    # ── Map score → regime ────────────────────────────────────────────────
    n_signals = len(signals)
    confidence = abs(score) / max(n_signals, 1)

    if score >= 4:
        regime = "bull"
    elif score >= 1:
        regime = "bullish"
    elif score <= -4:
        regime = "bear"
    elif score <= -1:
        regime = "bearish"
    else:
        regime = "sideways"

    # Special overrides
    if rsi is not None and rsi > 72 and score >= 2:
        regime = "sideways"   # overbought → caution even if score positive

    meta = REGIME_META[regime]
    return {
        "regime":            regime,
        "label":             meta["label"],
        "color":             meta["color"],
        "bg":                meta["bg"],
        "score":             score,
        "n_signals":         n_signals,
        "confidence":        confidence,
        "signals":           signals,
        "suggested_presets": PRESET_SUGGESTIONS.get(regime, []),
        "vnindex_close":     c,
        "rsi14":             rsi,
    }


def load_regime(effective_date: "str | None" = None) -> dict[str, Any]:
    """Load all inputs and classify. Safe to call at render time.

    Khối ngoại 1 phiên lấy ĐÚNG phiên hiệu lực — mặc định phiên của bar VNINDEX
    (`data_date`) — chứ không lấy ngày MỚI NHẤT trong cache: cache khối ngoại có
    ngày mới hơn bar giá thì regime trộn NN phiên sau với giá phiên trước (#22)."""
    tech    = _load_vnindex_tech()
    breadth = _load_breadth()
    nn_1d   = _load_nn_net_1d(effective_date or _nn_session(tech))
    return classify_regime(tech, breadth, nn_1d)


def _nn_session(tech: "dict | None") -> "str | None":
    """Phiên lấy khối ngoại 1 phiên = phiên của bar VNINDEX (``data_date``). Hệ
    quả cố ý: buổi sáng có bar live hôm nay mà cache khối ngoại (pipeline tối)
    chưa có hôm nay ⇒ phiếu NN vắng mặt thay vì mượn số phiên trước. Trả lại
    hành vi cũ (ngày mới nhất trong cache): VNSTOCK_REGIME_NN_SAME_SESSION=0."""
    if os.environ.get("VNSTOCK_REGIME_NN_SAME_SESSION", "1").strip().lower() in (
            "0", "false", "off", "no"):
        return None
    return (tech or {}).get("data_date")
