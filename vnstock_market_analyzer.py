"""
vnstock_market_analyzer.py — Quant-style sector/ticker scoring.

Philosophy:
  - Z-score every raw signal across the universe to put them on the same scale.
  - Composite score = weighted blend of Momentum, Volume, Flow sub-scores.
  - Overlay rule-based red flags (divergence / blow-off / exhaustion)
    and bullish catalysts (stealth accumulation / volume breakout).
  - Output is a ranked list plus per-sector evidence bullets — no judgement
    call, just evidence surfaced so the user can act on it.

Module has NO Streamlit dependency; safe to unit-test or reuse from CLI.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# ── Column constants (match dashboard display names) ──────────────────────
_COL_MKTCAP  = "Vốn hoá (tỷ)"
_COL_FF_VAL  = "Freefloat (tỷ)"
_COL_GTGD    = "GTGD TB (tỷ)"

_PRICE_COLS  = ("Giá 1T %", "Giá 1M %", "Giá 3M %")
_VOL_COLS    = ("AVG 5-10 %", "AVG 10-20 %")
_TURNOVER    = ("Vol 5/Free %", "Vol 10/Free %", "Vol 20/Free %")
_REL_VOL     = "Vol 5/20 %"
_NET_BS_COLS = ("Net BS 1T", "Net BS 1M", "Net BS 3M", "Net BS 6M")
_NN_COLS     = ("NN 1T (tỷ)", "NN 1M (tỷ)", "NN 3M (tỷ)")
_AMP_COLS    = ("Biên 1T (%)", "Biên 1M (%)", "Biên 3M (%)")


# ── Helpers ────────────────────────────────────────────────────────────────
def _zscore(series: pd.Series) -> pd.Series:
    """Robust-ish z-score: uses standard mean/std, NaN-safe, clipped to ±3σ."""
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean()
    sd = s.std()
    if sd is None or not np.isfinite(sd) or sd < 1e-9:
        return pd.Series(np.zeros(len(s)), index=s.index)
    z = (s - mu) / sd
    return z.clip(-3, 3).fillna(0)


def _safe(df: pd.DataFrame, col: str) -> pd.Series:
    """Return numeric Series for col or zeros if missing."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series([np.nan] * len(df), index=df.index)


# ── Core scoring ──────────────────────────────────────────────────────────
def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-row composite scores. Works for both sector-level (mkt_df)
    and ticker-level (tick_data) DataFrames.

    Returns DataFrame indexed same as input with columns:
      momentum, volume, flow, composite, verdict, red_flags, catalysts
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = pd.DataFrame(index=df.index)

    # ── Momentum (price action) ────────────────────────────────────────────
    # Weight to recency: 1T=0.5, 1M=0.3, 3M=0.2
    m1 = _zscore(_safe(df, "Giá 1T %"))
    m2 = _zscore(_safe(df, "Giá 1M %"))
    m3 = _zscore(_safe(df, "Giá 3M %"))
    out["momentum"] = 0.5 * m1 + 0.3 * m2 + 0.2 * m3

    # ── Volume (participation / conviction) ────────────────────────────────
    v1 = _zscore(_safe(df, "AVG 5-10 %"))      # vol accel short
    v2 = _zscore(_safe(df, "AVG 10-20 %"))     # vol accel medium
    v3 = _zscore(_safe(df, "Vol 5/Free %"))    # turnover intensity
    v4 = _zscore(_safe(df, "Vol 5/20 %") - 100)  # relative vol vs baseline
    out["volume"] = 0.30 * v1 + 0.20 * v2 + 0.30 * v3 + 0.20 * v4

    # ── Flow (smart money) ────────────────────────────────────────────────
    # Net BS & Vol Avg cùng đơn vị "triệu cổ phiếu" → tỷ lệ = "days of volume"
    # Giá trị thường trong [-1, +1] vì |Net| ≤ tổng volume
    vol20 = _safe(df, "Vol Avg 20").replace(0, np.nan)
    nbs1_ratio = _safe(df, "Net BS 1M") / (vol20 * 20)   # 1M = 20 phiên
    nbs3_ratio = _safe(df, "Net BS 3M") / (vol20 * 60)   # 3M = 60 phiên
    f1 = _zscore(nbs1_ratio)
    f2 = _zscore(nbs3_ratio)
    # Foreign flow normalized by cap (cả hai đều tỷ)
    cap = _safe(df, _COL_MKTCAP).replace(0, np.nan)
    nn1 = _safe(df, "NN 1M (tỷ)") / cap
    nn3 = _safe(df, "NN 3M (tỷ)") / cap
    fx1 = _zscore(nn1)
    fx3 = _zscore(nn3)
    out["flow"] = 0.35 * f1 + 0.25 * f2 + 0.25 * fx1 + 0.15 * fx3

    # Keep the ratios for red-flag detection below
    out["_nbs1_ratio"] = nbs1_ratio
    out["_nn1_ratio"]  = nn1

    # ── Composite ──────────────────────────────────────────────────────────
    out["composite"] = 0.35 * out["momentum"] + 0.30 * out["volume"] + 0.35 * out["flow"]

    # ── Verdict ────────────────────────────────────────────────────────────
    def _verdict(r):
        c = r["composite"]
        subs = [r["momentum"], r["volume"], r["flow"]]
        pos = sum(1 for s in subs if s > 0)
        neg = sum(1 for s in subs if s < 0)
        if c > 1.0 and pos >= 3:
            return "🔥 Strong Buy"
        if c > 0.3 and pos >= 2:
            return "📈 Accumulate"
        if c < -1.0 and neg >= 3:
            return "❄️ Avoid"
        if c < -0.3 and neg >= 2:
            return "📉 Distribute"
        return "⚖️ Neutral"
    out["verdict"] = out.apply(_verdict, axis=1)

    # ── Red flags & catalysts ──────────────────────────────────────────────
    red_flags: list[list[str]] = []
    catalysts: list[list[str]] = []

    g1 = _safe(df, "Giá 1T %")
    g1m = _safe(df, "Giá 1M %")
    g3m = _safe(df, "Giá 3M %")
    av51 = _safe(df, "AVG 5-10 %")
    rel_v = _safe(df, "Vol 5/20 %")
    amp1 = _safe(df, "Biên 1T (%)")
    amp1_q80 = amp1.quantile(0.8) if amp1.notna().any() else np.nan
    vf5 = _safe(df, "Vol 5/Free %")
    vf5_median = vf5.median() if vf5.notna().any() else np.nan

    for idx in df.index:
        rf, ct = [], []

        # Distribution divergence: giá 1M tăng nhưng Net BS 1M < -5% volume baseline
        if (_notna(g1m.at[idx]) and g1m.at[idx] > 0
                and _notna(nbs1_ratio.at[idx]) and nbs1_ratio.at[idx] < -0.05):
            rf.append(f"⚠️ Divergence: giá 1M `{g1m.at[idx]:+.1f}%` nhưng "
                      f"Net BS 1M = `{nbs1_ratio.at[idx]*100:+.1f}%` volume → dòng tiền thoát")

        # Blow-off top: giá 1T bùng, rel vol cao, biên độ top quintile
        if (_notna(g1.at[idx]) and g1.at[idx] > 3 and
            _notna(rel_v.at[idx]) and rel_v.at[idx] > 150 and
            _notna(amp1.at[idx]) and _notna(amp1_q80) and amp1.at[idx] >= amp1_q80):
            rf.append("🌋 Blow-off: giá bứt mạnh + vol nổ + biên độ cao → rủi ro đảo chiều")

        # Exhaustion: đã chạy dài 3M nhưng volume short-term quay đầu
        if _notna(g3m.at[idx]) and g3m.at[idx] > 15 and _notna(av51.at[idx]) and av51.at[idx] < -15:
            rf.append("💤 Exhaustion: sau đợt tăng 3M, volume 5d đã chậm lại >15%")

        # Foreign dumping
        if _notna(nn1.at[idx]) and nn1.at[idx] < -0.01:
            rf.append(f"🚪 NN bán ròng `{nn1.at[idx]*100:+.1f}%` cap trong 1M")

        # Stealth accumulation: coiling + dòng tiền vào (Net BS 1M > 3% volume baseline)
        if (_notna(g1.at[idx]) and abs(g1.at[idx]) < 1.5 and
            _notna(nbs1_ratio.at[idx]) and nbs1_ratio.at[idx] > 0.03 and
            _notna(vf5.at[idx]) and _notna(vf5_median) and vf5.at[idx] >= vf5_median):
            ct.append(f"🕵️ Stealth: giá đi ngang, Net BS 1M `{nbs1_ratio.at[idx]*100:+.1f}%` "
                      f"volume + turnover trên trung vị")

        # Volume breakout early
        if (_notna(av51.at[idx]) and av51.at[idx] > 30 and
            _notna(rel_v.at[idx]) and rel_v.at[idx] > 120 and
            _notna(g1.at[idx]) and g1.at[idx] > 0):
            ct.append("🚀 Volume breakout: AVG 5-10 >+30% + rel vol >120% + giá xanh")

        # Foreign leading
        if _notna(nn1.at[idx]) and nn1.at[idx] > 0.005 and _notna(fx1.at[idx]) and fx1.at[idx] > 1:
            ct.append(f"🌍 NN dẫn dắt: mua ròng `{nn1.at[idx]*100:+.1f}%` cap 1M, top quintile")

        red_flags.append(rf)
        catalysts.append(ct)

    out["red_flags"] = red_flags
    out["catalysts"] = catalysts

    return out


def _notna(v) -> bool:
    try:
        return v is not None and not (isinstance(v, float) and np.isnan(v))
    except Exception:
        return False


# ── Market regime aggregation ─────────────────────────────────────────────
def market_regime(scores: pd.DataFrame,
                   breadth: Optional[dict] = None) -> dict:
    """Summarize overall market from sector-level scores + optional breadth."""
    if scores is None or scores.empty:
        return {"regime": "Không đủ dữ liệu", "conviction": 0, "detail": ""}

    bullish = int((scores["composite"] > 0.3).sum())
    bearish = int((scores["composite"] < -0.3).sum())
    strong  = int((scores["composite"] > 1.0).sum())
    weak    = int((scores["composite"] < -1.0).sum())
    total   = len(scores)

    diff_ratio = (bullish - bearish) / max(total, 1)
    avg_comp = float(scores["composite"].mean())

    if diff_ratio > 0.3 and avg_comp > 0.2:
        regime = "🔥 Risk-on"
    elif diff_ratio > 0.1:
        regime = "📈 Slight bullish bias"
    elif diff_ratio < -0.3 and avg_comp < -0.2:
        regime = "❄️ Risk-off"
    elif diff_ratio < -0.1:
        regime = "📉 Slight bearish bias"
    else:
        regime = "⚖️ Neutral / Phân hoá"

    detail = (f"{bullish}/{total} ngành tích cực ({strong} mạnh) · "
              f"{bearish}/{total} ngành tiêu cực ({weak} yếu)")

    # Breadth corroboration
    if breadth:
        pct200 = breadth.get("above_ma200_pct", None)
        ad = breadth.get("ad_ratio", None)
        parts = []
        if pct200 is not None:
            parts.append(f"{pct200:.0f}% > MA200")
        if ad is not None:
            parts.append(f"A/D {ad:.2f}")
        if parts:
            detail += " · " + " · ".join(parts)

    return {
        "regime": regime,
        "conviction": round(avg_comp, 2),
        "bullish": bullish, "bearish": bearish,
        "strong": strong, "weak": weak,
        "detail": detail,
    }


# ── Ranking ───────────────────────────────────────────────────────────────
def rank(df: pd.DataFrame, scores: pd.DataFrame,
         n_top: int = 5, n_bot: int = 5, name_col: str = "Ngành") -> dict:
    """Return dict with 'top' (best composite) and 'avoid' (worst composite) lists."""
    if scores is None or scores.empty:
        return {"top": [], "avoid": [], "stealth": [], "distribution": []}

    merged = df.copy()
    for c in ("momentum", "volume", "flow", "composite", "verdict", "red_flags", "catalysts"):
        merged[c] = scores[c].values

    top = merged.sort_values("composite", ascending=False).head(n_top)
    avoid = merged.sort_values("composite", ascending=True).head(n_bot)

    # Stealth watch: neutral composite but has stealth/breakout catalyst
    stealth_mask = merged["catalysts"].apply(
        lambda xs: any("Stealth" in x or "breakout" in x for x in xs)
    ) & (merged["composite"].abs() < 0.8)
    stealth = merged[stealth_mask].sort_values("composite", ascending=False).head(3)

    # Distribution watch: composite positive but has red flag
    dist_mask = merged["red_flags"].apply(lambda xs: any("Divergence" in x for x in xs))
    distribution = merged[dist_mask & (merged["composite"] > 0)].sort_values("composite", ascending=False).head(3)

    return {
        "top": top.to_dict("records"),
        "avoid": avoid.to_dict("records"),
        "stealth": stealth.to_dict("records"),
        "distribution": distribution.to_dict("records"),
    }


# ── Formatted narrative ───────────────────────────────────────────────────
def format_row(row: dict, name_col: str = "Ngành") -> list[str]:
    """Return markdown lines describing a single row (sector or ticker)."""
    name = row.get(name_col) or row.get("Mã") or row.get("ticker") or "?"
    comp = row.get("composite", 0)
    verdict = row.get("verdict", "")
    lines = [f"**{name}** · Composite `{comp:+.2f}` · {verdict}"]

    # Key evidence (momentum, flow, volume)
    ev = []
    if _notna(row.get("Giá 1M %")):
        ev.append(f"Giá 1M `{row['Giá 1M %']:+.1f}%`")
    if _notna(row.get("Giá 3M %")):
        ev.append(f"3M `{row['Giá 3M %']:+.1f}%`")
    if _notna(row.get("Net BS 1M")):
        ev.append(f"Net BS 1M `{row['Net BS 1M']:+,.1f}M`")
    if _notna(row.get("AVG 5-10 %")):
        ev.append(f"AVG 5-10 `{row['AVG 5-10 %']:+.1f}%`")
    if _notna(row.get("Vol 5/Free %")):
        ev.append(f"Vol/Free 5d `{row['Vol 5/Free %']:.1f}%`")
    if _notna(row.get("NN 1M (tỷ)")):
        ev.append(f"NN 1M `{row['NN 1M (tỷ)']:+,.0f}` tỷ")
    if ev:
        lines.append("  · " + " · ".join(ev))

    # Red flags & catalysts
    for rf in row.get("red_flags", []) or []:
        lines.append(f"  {rf}")
    for ct in row.get("catalysts", []) or []:
        lines.append(f"  {ct}")

    return lines
