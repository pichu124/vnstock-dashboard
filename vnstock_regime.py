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
    """Read VNINDEX price history from warehouse and compute technicals."""
    try:
        import pyarrow.parquet as pq
        import numpy as np

        vnindex_dir = _REPO / "data_warehouse" / "prices" / "ticker=VNINDEX"
        if not vnindex_dir.exists():
            return {}

        tables = []
        for part in sorted(vnindex_dir.glob("year=*/*.parquet")):
            tables.append(pq.read_table(part).to_pandas())
        if not tables:
            return {}

        import pandas as pd
        df = pd.concat(tables, ignore_index=True)
        df = df.sort_values("trading_date").reset_index(drop=True)
        if df.empty:
            return {}

        close = df["close"].astype(float)
        # Price-unit normalisation (some sources store in integer points)
        if close.iloc[-1] > 5000:
            close = close / 1000

        n = len(close)
        def _ma(w):
            return float(close.rolling(w).mean().iloc[-1]) if n >= w else None

        def _rsi(period=14):
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
            rs = gain / loss.replace(0, float("nan"))
            return float(100 - 100 / (1 + rs.iloc[-1]))

        c = float(close.iloc[-1])
        ma20  = _ma(20)
        ma50  = _ma(50)
        ma200 = _ma(200)

        return {
            "close":  c,
            "ma20":   ma20,
            "ma50":   ma50,
            "ma200":  ma200,
            "rsi14":  _rsi(14),
            "vs_ma20":  round((c / ma20 - 1) * 100, 2)  if ma20  else None,
            "vs_ma50":  round((c / ma50 - 1) * 100, 2)  if ma50  else None,
            "vs_ma200": round((c / ma200 - 1) * 100, 2) if ma200 else None,
        }
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


def _load_nn_net_1d() -> float:
    """Return total NN ròng (tỷ VND) for most recent trading day from disk cache."""
    try:
        p = _REPO / "data_warehouse" / "_meta" / "nn_flow_cache.json"
        if not p.exists():
            return 0.0
        import pandas as pd
        data = json.loads(p.read_text(encoding="utf-8"))
        df = pd.DataFrame(data.get("rows", []))
        if df.empty or "date" not in df.columns:
            return 0.0
        df["date"] = pd.to_datetime(df["date"])
        latest = df["date"].max()
        day_df = df[df["date"] >= latest]
        net = day_df["net_value"].sum() if "net_value" in day_df.columns else 0.0
        return round(float(net) / 1e9, 1)
    except Exception:
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
        nn_net_1d = _load_nn_net_1d()

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

    # Signal 1 — VNINDEX vs MA20
    if c and ma20:
        d = (c / ma20 - 1) * 100
        _sig("VNINDEX / MA20", f"{d:+.1f}%",
             1 if d > 0 else -1,
             f"{'Trên' if d > 0 else 'Dưới'} MA20 ({ma20:,.0f})")

    # Signal 2 — VNINDEX vs MA50
    if c and ma50:
        d = (c / ma50 - 1) * 100
        _sig("VNINDEX / MA50", f"{d:+.1f}%",
             1 if d > 0 else -1,
             f"{'Trên' if d > 0 else 'Dưới'} MA50 ({ma50:,.0f})")

    # Signal 3 — VNINDEX vs MA200
    if c and ma200:
        d = (c / ma200 - 1) * 100
        _sig("VNINDEX / MA200", f"{d:+.1f}%",
             1 if d > 0 else -1,
             f"{'Trên' if d > 0 else 'Dưới'} MA200 ({ma200:,.0f})")

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

    # Signal 6 — Advance/Decline ratio
    advances = breadth.get("advances", 0)
    declines = breadth.get("declines", 1)
    ad_ratio = advances / max(declines, 1)
    if advances or declines:
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


def load_regime() -> dict[str, Any]:
    """Load all inputs and classify. Safe to call at render time."""
    tech    = _load_vnindex_tech()
    breadth = _load_breadth()
    nn_1d   = _load_nn_net_1d()
    return classify_regime(tech, breadth, nn_1d)
