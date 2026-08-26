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


# ── Index benchmark helpers ───────────────────────────────────────────────
def compute_index_returns(idx_df: pd.DataFrame,
                           index_col: str = "VNINDEX") -> dict:
    """Compute 1T/1M/3M returns for a benchmark index from load_index_overview()
    output. Returns dict with keys '1T', '1M', '3M' (in %).

    idx_df is expected to be sorted desc by time (newest first), with a close
    column named like "VNINDEX".
    """
    empty = {"1T": 0.0, "1M": 0.0, "3M": 0.0}
    if idx_df is None or idx_df.empty or index_col not in idx_df.columns:
        return empty
    closes = pd.to_numeric(idx_df[index_col], errors="coerce").dropna()
    if len(closes) < 2:
        return empty
    # idx_df is sorted newest-first — row 0 is latest
    latest = float(closes.iloc[0])
    if latest <= 0:
        return empty

    def _ret(n):
        if n >= len(closes):
            return 0.0
        past = float(closes.iloc[n])
        return round((latest / past - 1) * 100, 2) if past > 0 else 0.0

    return {
        "1T": _ret(5),    # 1 week = 5 business days
        "1M": _ret(20),
        "3M": _ret(60),
    }


# ── Technical overlay helpers (from screener presets) ────────────────────
def build_preset_sets(screener_results: dict | None) -> dict:
    """Turn screener_results.json into sets of tickers per preset.

    Returns dict with keys matching preset names (each a set of ticker strings).
    Handles the structure:
      {"presets": {"oversold": {"results": [{"ticker": ..., ...}, ...]}, ...}}
    """
    if not screener_results:
        return {}
    presets = (screener_results or {}).get("presets", {})
    out: dict = {}
    # Also keep per-ticker full records for richer flags (RSI value, 52w_pct)
    per_ticker: dict = {}
    for name, data in presets.items():
        rows = data.get("results", []) if isinstance(data, dict) else []
        tickers = set()
        for r in rows:
            tk = r.get("ticker") if isinstance(r, dict) else None
            if tk:
                tickers.add(tk)
                # Collapse: first-seen record is fine (fields are computed once per ticker)
                if tk not in per_ticker:
                    per_ticker[tk] = r
        out[name] = tickers
    out["_per_ticker"] = per_ticker
    return out


def _ticker_flags(ticker: str, presets: dict,
                   composite: float) -> tuple[list[str], list[str]]:
    """Derive red flags & catalysts for a ticker from screener preset membership."""
    if not presets or not ticker:
        return [], []

    oversold    = presets.get("oversold", set())
    overbought  = presets.get("overbought", set())
    golden      = presets.get("golden_cross", set())
    breakout    = presets.get("breakout", set())
    volsurge    = presets.get("volume_surge", set())
    reversal    = presets.get("reversal", set())
    strong_up   = presets.get("strong_uptrend", set())
    pt          = presets.get("_per_ticker", {}).get(ticker, {})
    rsi         = pt.get("rsi_14") if isinstance(pt, dict) else None
    w52_pct     = pt.get("52w_pct") if isinstance(pt, dict) else None
    above_ma200 = pt.get("above_ma200") if isinstance(pt, dict) else None

    rf, ct = [], []

    # ─ Red flags ─
    if ticker in overbought and composite > 0:
        rf.append(f"🥵 Overbought: RSI `{rsi:.1f}` >70 — cẩn trọng chasing"
                  if rsi is not None else "🥵 Overbought (RSI>70) — cẩn trọng chasing")
    if ticker in oversold and composite < 0:
        rf.append(f"🔪 Falling knife: RSI `{rsi:.1f}` <30, đà giảm chưa dừng"
                  if rsi is not None else "🔪 Falling knife: RSI<30, đà giảm chưa dừng")
    if above_ma200 is False and composite > 0:
        rf.append("📉 Dưới MA200 — trong downtrend dài hạn, bull trap risk")

    # ─ Catalysts ─
    if ticker in golden:
        ct.append("🌟 Golden cross: EMA9>21 + EMA50>200 + trên MA200")
    if ticker in strong_up:
        ct.append("💪 Strong uptrend: +5% 20d, MACD bull, trên MA200")
    if ticker in breakout:
        ct.append(f"🚀 Breakout: gần 52w high (`{w52_pct:.0f}%` range) + vol spike"
                  if w52_pct is not None else "🚀 Breakout: gần 52w high + vol spike")
    if ticker in volsurge:
        ct.append("⚡ Volume surge: >3× MA20 vol")
    if ticker in reversal:
        ct.append(f"🎯 Reversal setup: 52w low (`{w52_pct:.0f}%` range) + RSI<40"
                  if w52_pct is not None else "🎯 Reversal setup: 52w low + RSI<40")
    if above_ma200 is True and composite > 0.3 and ticker not in overbought:
        ct.append("✅ Trên MA200 (confirmed uptrend)")

    return rf, ct


def _sector_technical_summary(sector_df: pd.DataFrame, presets: dict) -> str:
    """Aggregate: what % of sector's tickers are oversold/overbought/etc."""
    if not presets or sector_df is None or sector_df.empty or "Mã" not in sector_df.columns:
        return ""
    tickers = set(sector_df["Mã"].dropna().astype(str).tolist())
    if not tickers:
        return ""
    n = len(tickers)
    ov = len(tickers & presets.get("oversold", set()))
    ob = len(tickers & presets.get("overbought", set()))
    gc = len(tickers & presets.get("golden_cross", set()))
    bo = len(tickers & presets.get("breakout", set()))
    parts = []
    if ob > 0:
        parts.append(f"{ob}/{n} overbought ({ob*100//n}%)")
    if ov > 0:
        parts.append(f"{ov}/{n} oversold ({ov*100//n}%)")
    if gc > 0:
        parts.append(f"{gc}/{n} golden cross")
    if bo > 0:
        parts.append(f"{bo}/{n} breakout")
    return " · ".join(parts)


# ── Quarantine & dividend helpers ────────────────────────────────────────
def load_quarantine_tickers() -> set[str]:
    """Return set of tickers with unresolved data-quality issues.
    These should be excluded from top-pick rankings to avoid acting on bad data.
    """
    try:
        from vnstock_quarantine import list_quarantine
        q_df = list_quarantine()
        if q_df.empty:
            return set()
        accepted_col = q_df.get("accepted") if "accepted" in q_df.columns else None
        if accepted_col is not None:
            q_df = q_df[~q_df["accepted"].fillna(False).astype(bool)]
        return set(q_df["ticker"].dropna().str.upper().unique()) if "ticker" in q_df.columns else set()
    except Exception:
        return set()


def _exdiv_from_registry(cutoff, today, warehouse=None) -> dict:
    """Sự kiện CỔ TỨC TIỀN MẶT trong khoảng, lấy từ SỔ ĐĂNG KÝ sự kiện.

    Sổ `_meta/corp_actions_registry.parquet` được nhiều nguồn nạp (vietstock,
    capital_history, manual…) và có sẵn cột `cash_amount`. Đây là đường CHÍNH
    từ 26/08 — xem `_exdiv_from_cafef_cache` để biết vì sao.
    """
    from pathlib import Path

    import pandas as pd

    wh = Path(warehouse or "data_warehouse")
    path = wh / "_meta" / "corp_actions_registry.parquet"
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if df is None or df.empty or "ex_date" not in df.columns:
        return {}

    out: dict = {}
    for _, row in df.iterrows():
        if str(row.get("type", "")).lower() != "cash":
            continue
        try:
            ex_date = pd.to_datetime(row["ex_date"]).date()
        except Exception:
            continue
        if not (cutoff <= ex_date <= today):
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        amount = row.get("cash_amount")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        if amount != amount:                     # NaN — sổ có sự kiện, thiếu số
            amount = 0.0
        prev = out.get(ticker)
        if prev is None or ex_date.isoformat() > prev["ex_date"]:
            out[ticker] = {"ex_date": ex_date.isoformat(), "amount": amount}
    return out


def exdiv_source_status(days_back: int = 7) -> dict:
    """Sổ đăng ký có trả sự kiện cổ tức không, và tổng sổ dày bao nhiêu.

    `recent` một mình KHÔNG đọc được: 7 ngày không mã nào chia cổ tức là
    chuyện BÌNH THƯỜNG. Phải kèm `total_cash` — tổng sự kiện `cash` ở MỌI kỳ —
    mới phân biệt được "tuần này im" với "sổ rỗng, không có nguồn".
    """
    from datetime import date, timedelta

    today = date.today()
    recent = _exdiv_from_registry(today - timedelta(days=days_back), today)
    ever = _exdiv_from_registry(date(1990, 1, 1), today)
    return {
        "recent": len(recent),
        "total_cash": len(ever),
        "source": "registry" if recent else "none",
        "days_back": days_back,
    }


def load_recent_exdiv(days_back: int = 7) -> dict:
    """Return tickers whose ex-dividend date falls within the last ``days_back`` days.

    Used to suppress false "sell" red-flags when a price drop is simply the
    stock going ex-dividend, not a distribution signal.

    Returns {ticker_upper: {"ex_date": str, "amount": float}} for each match.

    Nguồn DUY NHẤT là sổ `_meta/corp_actions_registry.parquet`. Kho JSON cũ
    `_meta/cash_dividends/` **đã bỏ 26/08**: nó chỉ do `run.py cash-dividends`
    ghi, lệnh đó cào CafeF và **404 từ 19/08**, lại không nằm trong `cmd_all`.
    Cửa sổ ở MỌI chỗ gọi là 7 ngày ⇒ kho ấy chỉ có thể chứa sự kiện từ 19/08
    trở đi, mà từ 19/08 không gì được ghi. **Chứng minh được là rỗng vĩnh
    viễn**, nên giữ lại chỉ là nuôi thêm một đoạn code chết trông như sống.
    """
    from datetime import date, timedelta

    today = date.today()
    return _exdiv_from_registry(today - timedelta(days=days_back), today)

def compute_scores(df: pd.DataFrame,
                    presets: dict | None = None,
                    index_returns: dict | None = None,
                    exdiv_map: dict | None = None) -> pd.DataFrame:
    """Compute per-row composite scores. Works for both sector-level (mkt_df)
    and ticker-level (tick_data) DataFrames.

    Args:
      df: DataFrame with sector/ticker metrics (see module constants for cols).
      presets: optional dict from build_preset_sets(); adds technical overlays
               (RSI / MA200 / golden cross / breakout) to per-ticker flags.
      index_returns: optional dict {"1T": x, "1M": y, "3M": z} from
               compute_index_returns(idx_df). If provided, momentum uses
               ALPHA (excess return vs index) instead of raw returns.
      exdiv_map: optional dict {ticker: {"ex_date": str, "amount": float}}
               from load_recent_exdiv(). Suppresses false distribution flags
               for stocks that just went ex-dividend.

    Returns DataFrame indexed same as input with columns:
      momentum, volume, flow, composite, verdict, red_flags, catalysts,
      alpha_1T, alpha_1M, alpha_3M (if index_returns provided),
      rotation (alpha_1M - alpha_3M, warming-up signal),
      nn_trend (NN daily pace 1M vs 3M, accumulation trend),
      _vol_regime ("high" | "normal")
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = pd.DataFrame(index=df.index)

    # ── Volatility regime filter ───────────────────────────────────────────
    # When market daily amplitude is high (avg Biên 1T > 2.5%), short-term
    # signals become noisy — flatten the recency weights to reduce false signals.
    amp1_regime = _safe(df, "Biên 1T (%)")
    _mkt_vol = float(amp1_regime.mean()) if amp1_regime.notna().sum() >= 2 else 0.0
    _high_vol = _mkt_vol > 2.5
    out["_vol_regime"] = "high" if _high_vol else "normal"
    # Momentum weights: under high vol flatten recency bias (less 1T, more 1M/3M)
    _w_m1, _w_m2, _w_m3 = (0.3, 0.4, 0.3) if _high_vol else (0.5, 0.3, 0.2)

    # ── Momentum (price action or alpha vs benchmark) ──────────────────────
    raw_1t = _safe(df, "Giá 1T %")
    raw_1m = _safe(df, "Giá 1M %")
    raw_3m = _safe(df, "Giá 3M %")

    if index_returns:
        # Use ALPHA (excess return) instead of raw — this is the quant-pure way
        i1 = float(index_returns.get("1T", 0) or 0)
        i2 = float(index_returns.get("1M", 0) or 0)
        i3 = float(index_returns.get("3M", 0) or 0)
        alpha_1t = raw_1t - i1
        alpha_1m = raw_1m - i2
        alpha_3m = raw_3m - i3
        out["alpha_1T"] = alpha_1t
        out["alpha_1M"] = alpha_1m
        out["alpha_3M"] = alpha_3m
        m1 = _zscore(alpha_1t)
        m2 = _zscore(alpha_1m)
        m3 = _zscore(alpha_3m)
        # Sector rotation: alpha_1M - alpha_3M > 0 = money rotating in recently
        out["rotation"] = alpha_1m - alpha_3m
    else:
        m1 = _zscore(raw_1t)
        m2 = _zscore(raw_1m)
        m3 = _zscore(raw_3m)
    out["momentum"] = _w_m1 * m1 + _w_m2 * m2 + _w_m3 * m3

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
    # Foreign flow: point-in-time levels
    cap = _safe(df, _COL_MKTCAP).replace(0, np.nan)
    nn1m_val = _safe(df, "NN 1M (tỷ)")
    nn3m_val = _safe(df, "NN 3M (tỷ)")
    nn1 = nn1m_val / cap
    nn3 = nn3m_val / cap
    fx1 = _zscore(nn1)
    fx3 = _zscore(nn3)
    # Foreign flow TREND: daily run-rate 1M vs 3M
    # nn_rate_1m = avg daily NN buy (% cap) over last month
    # nn_rate_3m = avg daily NN buy (% cap) over last 3 months
    # positive nn_trend → NN accelerating accumulation recently
    nn_rate_1m = nn1m_val / (20 * cap)
    nn_rate_3m = nn3m_val / (60 * cap)
    nn_trend = nn_rate_1m - nn_rate_3m
    out["nn_trend"] = nn_trend
    fx_trend = _zscore(nn_trend)
    # Composite flow: 25% Net BS 1M, 15% Net BS 3M, 25% NN level 1M, 15% NN level 3M, 20% NN trend
    out["flow"] = 0.25 * f1 + 0.15 * f2 + 0.25 * fx1 + 0.15 * fx3 + 0.20 * fx_trend

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
    # Vol regime flag: high-vol market → note it in per-row detail
    _vol_high_note = "⚡ high-vol regime" if _high_vol else ""
    # Volatility signal threshold: stricter blow-off under high vol
    _g1_blowoff_thr = 2.5 if _high_vol else 3.0

    _ticker_col = "Mã" if "Mã" in df.columns else None
    _exdiv_map = exdiv_map or {}

    for idx in df.index:
        rf, ct = [], []

        # Resolve ticker string (for ex-div and quarantine checks)
        _tk_str: str | None = None
        if _ticker_col and _ticker_col in df.columns:
            _tk_str = str(df.at[idx, _ticker_col]) if df.at[idx, _ticker_col] else None

        # ── Ex-dividend guard ──────────────────────────────────────────────
        # If ticker went ex-div in the last 7 days, price drop is expected —
        # suppress divergence/distribution flags, add information note instead.
        _is_exdiv = _tk_str and _tk_str.upper() in _exdiv_map
        if _is_exdiv:
            _ed = _exdiv_map[_tk_str.upper()]
            ct.append(f"📅 Ex-div `{_ed['ex_date']}` "
                      + (f"(VND `{_ed['amount']:,.0f}`) " if _ed.get("amount") else "")
                      + "— giá giảm do tách quyền, không phải bán tháo")

        # Distribution divergence: giá 1M tăng nhưng Net BS 1M < -5% volume baseline
        if (not _is_exdiv and _notna(g1m.at[idx]) and g1m.at[idx] > 0
                and _notna(nbs1_ratio.at[idx]) and nbs1_ratio.at[idx] < -0.05):
            rf.append(f"⚠️ Divergence: giá 1M `{g1m.at[idx]:+.1f}%` nhưng "
                      f"Net BS 1M = `{nbs1_ratio.at[idx]*100:+.1f}%` volume → dòng tiền thoát")

        # Blow-off top: giá 1T bùng, rel vol cao, biên độ top quintile
        if (_notna(g1.at[idx]) and g1.at[idx] > _g1_blowoff_thr and
            _notna(rel_v.at[idx]) and rel_v.at[idx] > 150 and
            _notna(amp1.at[idx]) and _notna(amp1_q80) and amp1.at[idx] >= amp1_q80):
            rf.append("🌋 Blow-off: giá bứt mạnh + vol nổ + biên độ cao → rủi ro đảo chiều"
                      + (f" (trong {_vol_high_note})" if _vol_high_note else ""))

        # Exhaustion: đã chạy dài 3M nhưng volume short-term quay đầu
        if _notna(g3m.at[idx]) and g3m.at[idx] > 15 and _notna(av51.at[idx]) and av51.at[idx] < -15:
            rf.append("💤 Exhaustion: sau đợt tăng 3M, volume 5d đã chậm lại >15%")

        # Foreign flow: point-in-time level
        if not _is_exdiv and _notna(nn1.at[idx]) and nn1.at[idx] < -0.01:
            rf.append(f"🚪 NN bán ròng `{nn1.at[idx]*100:+.1f}%` cap trong 1M")

        # ── NN trend: ACCUMULATING vs DUMPING ─────────────────────────────
        # Compare daily run-rate of NN over 1M vs 3M to detect direction change
        if "nn_trend" in out.columns:
            _nnt = out["nn_trend"].at[idx]
            if _notna(_nnt):
                _nnt_pct = _nnt * 100 * 20  # express as % cap per month
                if _nnt_pct > 0.5:  # NN pace accelerating by >0.5% cap/month
                    ct.append(f"🌍 NN ACCUMULATING: pace 1M nhanh hơn avg 3M "
                               f"(`{_nnt_pct:+.2f}%` cap/tháng vượt trội)")
                elif _nnt_pct < -0.5:
                    rf.append(f"🚪 NN DUMPING: pace bán 1M nhanh hơn 3M avg "
                               f"(`{_nnt_pct:+.2f}%` cap/tháng — NN đang tăng tốc thoát hàng)")

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

        # Foreign leading (level signal)
        if _notna(nn1.at[idx]) and nn1.at[idx] > 0.005 and _notna(fx1.at[idx]) and fx1.at[idx] > 1:
            ct.append(f"🌍 NN dẫn dắt: mua ròng `{nn1.at[idx]*100:+.1f}%` cap 1M, top quintile")

        # Alpha vs benchmark (if index_returns provided)
        if index_returns and "alpha_1M" in out.columns:
            _a1m = out["alpha_1M"].at[idx]
            _a3m = out["alpha_3M"].at[idx] if "alpha_3M" in out.columns else np.nan
            if _notna(_a1m) and _a1m > 5:
                ct.append(f"📊 Alpha 1M `+{_a1m:.1f}%` vượt VNINDEX rõ rệt")
            if _notna(_a3m) and _a3m > 10:
                ct.append(f"📊 Alpha 3M `+{_a3m:.1f}%` outperform benchmark")
            if _notna(_a1m) and _a1m < -5:
                rf.append(f"📉 Alpha 1M `{_a1m:+.1f}%` underperform VNINDEX rõ rệt")
            if _notna(_a3m) and _a3m < -10:
                rf.append(f"📉 Alpha 3M `{_a3m:+.1f}%` laggard 3 tháng")

        # ── Sector rotation signal ─────────────────────────────────────────
        # alpha_1M - alpha_3M > 0 → tiền mới đổ vào ngành gần đây (warming up)
        # alpha_1M - alpha_3M < 0 → đà giảm dần (cooling off)
        if "rotation" in out.columns:
            _rot = out["rotation"].at[idx]
            if _notna(_rot):
                if _rot > 5:
                    _a1m_v = out["alpha_1M"].at[idx] if "alpha_1M" in out.columns else np.nan
                    _a3m_v = out["alpha_3M"].at[idx] if "alpha_3M" in out.columns else np.nan
                    ct.append(f"🔄 Rotation IN: alpha 1M `{_a1m_v:+.1f}%` > alpha 3M `{_a3m_v:+.1f}%` "
                               f"({_rot:+.1f}pp) → tiền mới vào, momentum đang tăng tốc")
                elif _rot < -5:
                    _a1m_v = out["alpha_1M"].at[idx] if "alpha_1M" in out.columns else np.nan
                    _a3m_v = out["alpha_3M"].at[idx] if "alpha_3M" in out.columns else np.nan
                    rf.append(f"🔄 Momentum fading: alpha 1M `{_a1m_v:+.1f}%` < alpha 3M `{_a3m_v:+.1f}%` "
                               f"({_rot:+.1f}pp) → đà tăng đang hạ nhiệt, cân nhắc chốt lời")

        # Technical overlay — only meaningful at ticker level (df must have "Mã")
        if presets and _ticker_col:
            if _tk_str:
                _rf2, _ct2 = _ticker_flags(_tk_str, presets,
                                           composite=float(out["composite"].at[idx]))
                rf.extend(_rf2)
                ct.extend(_ct2)

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

    # Volatility regime from scores
    if "_vol_regime" in scores.columns:
        _vr_mode = scores["_vol_regime"].mode()
        if not _vr_mode.empty and _vr_mode.iloc[0] == "high":
            detail += " · ⚡ Biên độ cao — short-term signals giảm weight tự động"

    return {
        "regime": regime,
        # `or 0.0` khử ZERO ÂM: avg_comp ~ -0.001 → round ra -0.0 → format
        # "+.2f" hiện "conviction -0.00" trên dashboard/brief (lộ 17/07)
        "conviction": round(avg_comp, 2) or 0.0,
        "bullish": bullish, "bearish": bearish,
        "strong": strong, "weak": weak,
        "detail": detail,
    }


# ── Session timing (institutional vs retail bias) ──────────────────────────
def session_timing_signal(session_stats_today: dict | None,
                           history: dict | None = None,
                           index_name: str = "VNINDEX") -> dict:
    """Detect institutional vs retail bias from today's intraday session profile.

    Logic:
      - Morning share = GTGD(9h-11h30) / GTGD(9h-15h)
        * > 55% → institutional morning push (positive for follow-through)
        * 40-55% → balanced
        * < 40% → late-day dominant → often retail chasing, weaker quality

    Args:
      session_stats_today: dict shaped like {window: {index: {vol, gtgd, ...}}}
      history: optional full history for computing today vs 20-day norm
      index_name: which index to use as market proxy (default VNINDEX)

    Returns:
      dict with keys: signal, morning_share, detail, flag (+1/-1/0)
    """
    if not session_stats_today:
        return {"signal": "N/A", "morning_share": None, "detail": "Chưa có session stats hôm nay", "flag": 0}

    morn = session_stats_today.get("9h-11h30", {}).get(index_name, {}).get("gtgd", 0) or 0
    full = session_stats_today.get("9h-15h",  {}).get(index_name, {}).get("gtgd", 0) or 0
    if full <= 0:
        return {"signal": "N/A", "morning_share": None, "detail": "Thiếu dữ liệu phiên cả ngày", "flag": 0}

    morning_share = morn / full

    # Baseline: 9h-11h30 window là 2.5h / 5h trading = 50% nếu volume rải đều
    # So any deviation is meaningful
    if morning_share > 0.58:
        signal = "🌅 Institutional morning"
        flag = 1
        detail = (f"Sáng chiếm `{morning_share*100:.0f}%` GTGD cả ngày (baseline 50%) → "
                  f"tổ chức mua/bán sớm, chất lượng phiên cao")
    elif morning_share > 0.52:
        signal = "📈 Sáng thiên mạnh"
        flag = 1
        detail = f"Sáng chiếm `{morning_share*100:.0f}%` GTGD (khá cân, thiên sáng)"
    elif morning_share >= 0.45:
        signal = "⚖️ Cân bằng"
        flag = 0
        detail = f"Phân bổ đều 2 phiên (sáng `{morning_share*100:.0f}%`)"
    elif morning_share >= 0.38:
        signal = "🌆 Chiều chủ đạo"
        flag = -1
        detail = f"Chiều chiếm `{(1-morning_share)*100:.0f}%` GTGD → retail/short-term bias"
    else:
        signal = "🎢 Retail chasing"
        flag = -1
        detail = (f"Chiều nổ mạnh `{(1-morning_share)*100:.0f}%` GTGD → "
                  f"có thể retail đuổi giá cuối phiên, cẩn trọng follow-through")

    # Compare to history if available
    extra = ""
    if history:
        try:
            from datetime import date, timedelta
            hist_shares = []
            for k, v in history.items():
                try:
                    _d = date.fromisoformat(k)
                    if (date.today() - _d).days <= 20 and _d != date.today():
                        _m = v.get("9h-11h30", {}).get(index_name, {}).get("gtgd", 0) or 0
                        _f = v.get("9h-15h",  {}).get(index_name, {}).get("gtgd", 0) or 0
                        if _f > 0:
                            hist_shares.append(_m / _f)
                except Exception:
                    continue
            if hist_shares:
                avg = sum(hist_shares) / len(hist_shares)
                delta = morning_share - avg
                if abs(delta) >= 0.05:
                    arrow = "↑" if delta > 0 else "↓"
                    extra = f" · 20d avg `{avg*100:.0f}%` ({arrow}`{abs(delta)*100:.0f}pp`)"
        except Exception:
            pass

    return {
        "signal": signal,
        "morning_share": round(morning_share, 3),
        "detail": detail + extra,
        "flag": flag,
    }


# ── Ranking ───────────────────────────────────────────────────────────────
def rank(df: pd.DataFrame, scores: pd.DataFrame,
         n_top: int = 5, n_bot: int = 5, name_col: str = "Ngành",
         quarantined: set | None = None) -> dict:
    """Return dict with 'top' (best composite) and 'avoid' (worst composite) lists.

    Args:
      quarantined: optional set of ticker strings (uppercase) from
                   load_quarantine_tickers(). These are excluded from 'top'
                   and 'stealth' lists to avoid acting on bad data.
    """
    if scores is None or scores.empty:
        return {"top": [], "avoid": [], "stealth": [], "distribution": []}

    merged = df.copy()
    for c in ("momentum", "volume", "flow", "composite", "verdict", "red_flags", "catalysts"):
        merged[c] = scores[c].values
    # Carry extra columns if present
    for c in ("alpha_1T", "alpha_1M", "alpha_3M", "rotation", "nn_trend"):
        if c in scores.columns:
            merged[c] = scores[c].values

    # Quarantine filter: exclude bad-data tickers from actionable picks
    _quar = {str(t).upper() for t in quarantined} if quarantined else set()
    def _not_quarantined(row_name_val) -> bool:
        return str(row_name_val).upper() not in _quar if _quar else True

    if _quar and name_col in merged.columns:
        _clean_mask = merged[name_col].apply(_not_quarantined)
        _clean = merged[_clean_mask]
    else:
        _clean = merged

    top = _clean.sort_values("composite", ascending=False).head(n_top)
    avoid = merged.sort_values("composite", ascending=True).head(n_bot)  # avoid: quarantine OK to show

    # Stealth watch: neutral composite but has stealth/breakout catalyst
    stealth_mask = _clean["catalysts"].apply(
        lambda xs: any("Stealth" in x or "breakout" in x for x in xs)
    ) & (_clean["composite"].abs() < 0.8)
    stealth = _clean[stealth_mask].sort_values("composite", ascending=False).head(3)

    # Distribution watch: composite positive but has divergence red flag
    dist_mask = merged["red_flags"].apply(lambda xs: any("Divergence" in x for x in xs))
    distribution = merged[dist_mask & (merged["composite"] > 0)].sort_values("composite", ascending=False).head(3)

    # Rotation picks: warming-up sectors/tickers (alpha_1M > alpha_3M by 5pp+)
    rotation_picks: list[dict] = []
    if "rotation" in _clean.columns:
        rot_mask = _clean["rotation"] > 5
        rotation_picks = _clean[rot_mask].sort_values("rotation", ascending=False).head(3).to_dict("records")

    return {
        "top": top.to_dict("records"),
        "avoid": avoid.to_dict("records"),
        "stealth": stealth.to_dict("records"),
        "distribution": distribution.to_dict("records"),
        "rotation": rotation_picks,
    }


# ── Formatted narrative ───────────────────────────────────────────────────
def format_row(row: dict, name_col: str = "Ngành",
               show_detail: bool = True) -> list[str]:
    """Return markdown lines describing a single row (sector or ticker).

    Args:
      show_detail: if False, omit red_flags and catalysts lines (brief mode).
    """
    name = row.get(name_col) or row.get("Mã") or row.get("ticker") or "?"
    comp = row.get("composite", 0)
    verdict = row.get("verdict", "")
    lines = [f"**{name}** · Composite `{comp:+.2f}` · {verdict}"]

    # Key evidence (momentum, flow, volume)
    ev = []
    if _notna(row.get("Giá 1M %")):
        _a1m = row.get("alpha_1M")
        if _notna(_a1m):
            ev.append(f"Giá 1M `{row['Giá 1M %']:+.1f}%` (α `{_a1m:+.1f}%`)")
        else:
            ev.append(f"Giá 1M `{row['Giá 1M %']:+.1f}%`")
    if _notna(row.get("Giá 3M %")):
        _a3m = row.get("alpha_3M")
        if _notna(_a3m):
            ev.append(f"3M `{row['Giá 3M %']:+.1f}%` (α `{_a3m:+.1f}%`)")
        else:
            ev.append(f"3M `{row['Giá 3M %']:+.1f}%`")
    if _notna(row.get("Net BS 1M")):
        ev.append(f"Net BS 1M `{row['Net BS 1M']:+,.1f}M`")
    if _notna(row.get("AVG 5-10 %")):
        ev.append(f"AVG 5-10 `{row['AVG 5-10 %']:+.1f}%`")
    if _notna(row.get("Vol 5/Free %")):
        ev.append(f"Vol/Free 5d `{row['Vol 5/Free %']:.1f}%`")
    if _notna(row.get("NN 1M (tỷ)")):
        ev.append(f"NN 1M `{row['NN 1M (tỷ)']:+,.0f}` tỷ")
    if _notna(row.get("rotation")):
        rot = row["rotation"]
        if rot > 3:
            ev.append(f"🔄 Rotation `+{rot:.1f}pp`")
        elif rot < -3:
            ev.append(f"🔄 Fading `{rot:+.1f}pp`")
    if ev:
        lines.append("  · " + " · ".join(ev))

    # Red flags & catalysts (only when detail mode)
    if show_detail:
        for rf in row.get("red_flags", []) or []:
            lines.append(f"  {rf}")
        for ct in row.get("catalysts", []) or []:
            lines.append(f"  {ct}")

    return lines


# ── Quant export helpers ────────────────────────────────────────────────────
def scores_to_export_df(df: pd.DataFrame, scores: pd.DataFrame,
                         name_col: str = "Mã") -> pd.DataFrame:
    """Build a clean DataFrame suitable for CSV/Markdown export.

    Merges the original name column with all numeric score columns and
    stringifies red_flags / catalysts as pipe-separated text.
    """
    out = pd.DataFrame()
    if name_col in df.columns:
        out[name_col] = df[name_col].values

    numeric_cols = ["composite", "momentum", "volume", "flow",
                    "alpha_1T", "alpha_1M", "alpha_3M", "rotation"]
    for c in numeric_cols:
        if c in scores.columns:
            out[c] = scores[c].round(3).values

    if "verdict" in scores.columns:
        out["verdict"] = scores["verdict"].values

    if "red_flags" in scores.columns:
        out["red_flags"] = scores["red_flags"].apply(
            lambda xs: " | ".join(xs) if xs else "")
    if "catalysts" in scores.columns:
        out["catalysts"] = scores["catalysts"].apply(
            lambda xs: " | ".join(xs) if xs else "")

    return out


def scores_to_markdown(df: pd.DataFrame, scores: pd.DataFrame,
                        name_col: str = "Mã",
                        title: str = "Quant Analysis") -> str:
    """Return full markdown report string for download."""
    from datetime import date
    lines = [f"# {title}", f"_Generated {date.today().isoformat()}_", ""]

    merged = df.copy()
    for c in ("composite", "momentum", "volume", "flow", "verdict",
              "red_flags", "catalysts", "alpha_1T", "alpha_1M", "alpha_3M",
              "rotation", "nn_trend"):
        if c in scores.columns:
            merged[c] = scores[c].values

    for _, row in merged.sort_values("composite", ascending=False).iterrows():
        row_d = row.to_dict()
        for ln in format_row(row_d, name_col=name_col, show_detail=True):
            lines.append(ln)
        lines.append("")

    return "\n".join(lines)
