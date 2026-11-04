"""Tập mã cho độ rộng thị trường "% mã trên MA200" (PTKT §16) — hàm THUẦN dùng chung.

Mẫu số của runner (mọi mã ≥5 bar trong 400 ngày; mã <200 bar hay đứng giá bị tính "dưới")
kéo độ rộng xuống ~11% trên kho thật. TẬP MÃ ĐẦU TƯ ĐƯỢC tại phiên ``d``:
  • ≥ ``MIN_BARS`` (200) bar trong ``LOOKBACK_DAYS`` (400) ngày lùi từ ``d`` (như runner);
  • GTGD TB20 ≥ ``MIN_GTGD_BN`` (1 tỷ VND) theo LỊCH PHIÊN (``session_gtgd20``);
  • bar cuối ≤ ``d`` không trễ quá ``stale_limit()`` phiên (``VNSTOCK_SCREENER_STALE_SESSIONS``,
    đọc như screener; ≤ 0 = tắt lọc).
Đây đúng mẫu số (c) + fresh của ``scripts/compare_indicator_formulas.py --breadth-diag``.

Công tắc ``VNSTOCK_BREADTH_UNIVERSE`` = ``all`` (mặc định, số y nguyên) | ``investable``.
``vnstock_runner.build_market_overview`` và ``vnstock_horizons_state.breadth_history`` cùng
gọi ``investable_mask`` + ``breadth_fields`` ⇒ cùng phiên ra cùng số. Luôn ghi CẢ HAI số
(``above_ma200_pct_all`` / ``_investable`` + mẫu số) để so; ``above_ma200_pct`` = tập đang bật.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

UNIVERSE_ENV = "VNSTOCK_BREADTH_UNIVERSE"
ALL, INVESTABLE = "all", "investable"
MIN_BARS = 200                  # MA200 cần 200 bar trong cửa sổ
LOOKBACK_DAYS = 400             # vnstock_runner: cutoff = phiên − 400 ngày
MIN_GTGD_BN = 1.0               # tỷ VND
GTGD_N = 20


def breadth_universe() -> str:
    """Tập đang bật theo env; giá trị lạ ⇒ ``all`` (không đổi số khi gõ nhầm)."""
    raw = (os.environ.get(UNIVERSE_ENV) or "").strip().lower()
    return INVESTABLE if raw == INVESTABLE else ALL


def _days(x) -> np.ndarray:
    return pd.DatetimeIndex(pd.to_datetime(x)).to_numpy().astype("datetime64[D]")


def _session_values(t: np.ndarray, close, volume, s: np.ndarray) -> np.ndarray:
    """GTGD (tỷ) từng phiên của lịch ``s``: tổng bar trùng phiên, 0 phiên không bar, NaN trước
    bar đầu nằm trong lịch. ``t``, ``s`` = datetime64[D] đã sắp tăng."""
    out = np.zeros(len(s))
    if not len(s):
        return out
    val = np.nan_to_num(np.asarray(close, dtype=float) * np.asarray(volume, dtype=float) / 1e6)
    pos = np.searchsorted(s, t)
    hit = (pos < len(s)) & (s[np.minimum(pos, len(s) - 1)] == t)
    np.add.at(out, pos[hit], val[hit])
    out[:pos[hit].min() if hit.any() else len(s)] = np.nan
    return out


def session_gtgd20(time, close, volume, sessions) -> pd.Series:
    """GTGD TB20 (tỷ VND, ``close`` nghìn VND × KL / 1e6 như runner) theo LỊCH PHIÊN: phiên không
    có bar tính 0 (mã không khớp lệnh thì thanh khoản 0, không phải "thiếu"). Trước bar đầu và
    20 phiên đầu = NaN. Index = ``sessions``."""
    idx = pd.DatetimeIndex(sessions)
    v = _session_values(_days(time), close, volume, _days(idx))
    return pd.Series(v, index=idx).rolling(GTGD_N, min_periods=GTGD_N).mean()


def session_lag(time, sessions, days) -> np.ndarray:
    """Mỗi phiên ``days``: số phiên lịch SAU bar cuối ≤ phiên đó (như
    ``vnstock_screener.stale_sessions``); NaN khi chưa có bar."""
    t, s, d = _days(time), _days(sessions), _days(days)
    k = np.searchsorted(t, d, side="right") - 1
    last = t[np.clip(k, 0, None)] if len(t) else d
    lag = np.searchsorted(s, d, side="right") - np.searchsorted(s, last, side="right")
    return np.where(k >= 0, lag, np.nan).astype(float)


def investable_mask(time, close, volume, sessions, days, *, min_bars: int = MIN_BARS,
                    lookback_days: int = LOOKBACK_DAYS, min_gtgd: float = MIN_GTGD_BN,
                    max_lag: int | None = None) -> np.ndarray:
    """Mã (một chuỗi đã sắp tăng, ``close`` nghìn VND) có thuộc tập đầu tư được tại từng phiên
    ``days`` không — mảng bool cùng độ dài ``days``. ``sessions`` = lịch phiên (VNINDEX, sắp
    tăng), rỗng ⇒ toàn False (không tính được GTGD); phiên ``days`` ngoài lịch ⇒ False (như
    ``session_gtgd20(...).reindex(days)``). ``max_lag`` None ⇒ ``vnstock_screener.stale_limit()``."""
    dv, s = _days(days), _days(sessions)
    if not len(s) or not len(dv):
        return np.zeros(len(dv), bool)
    if max_lag is None:
        from vnstock_screener import stale_limit
        max_lag = stale_limit()
    tv = _days(time)
    hi = np.searchsorted(tv, dv, side="right") - 1
    lo = np.searchsorted(tv, dv - np.timedelta64(lookback_days, "D"), side="left")
    ok = (hi >= 0) & (hi - lo + 1 >= min_bars)
    # GTGD TB20 tại phiên j = (C[j+1] − C[j+1−20]) / 20 trên tổng tích luỹ — đúng rolling của
    # `session_gtgd20` (NaN ⇔ cửa sổ chạm phần trước bar đầu).
    vals = _session_values(tv, close, volume, s)
    known = np.flatnonzero(~np.isnan(vals))
    first = known[0] if len(known) else len(s)
    cum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(vals))])
    j = np.searchsorted(s, dv, side="right") - 1
    jc = np.clip(j, 0, None)
    has_g = (j >= 0) & (s[jc] == dv) & (j - GTGD_N + 1 >= first)
    g = (cum[jc + 1] - cum[np.clip(jc + 1 - GTGD_N, 0, None)]) / GTGD_N
    ok &= has_g & (g >= min_gtgd)
    if max_lag > 0:
        ok &= np.nan_to_num(session_lag(tv, s, dv), nan=np.inf) <= max_lag
    return ok


def _pct(above: int, n: int) -> float:
    return round(above / n * 100, 1)


def breadth_fields(n_all: int, above_all: int, n_inv: int | None, above_inv: int | None,
                   universe: str | None = None) -> dict:
    """Các trường độ rộng MA200 của một phiên. ``n_inv`` None/0 (không có lịch phiên, kho
    thiếu volume) ⇒ số investable None và tập thực dùng rơi về ``all`` — ``breadth_universe``
    luôn ghi tập THỰC DÙNG, không phải tập được yêu cầu."""
    want = universe or breadth_universe()
    has_inv = bool(n_inv)
    use = INVESTABLE if want == INVESTABLE and has_inv else ALL
    n, above = (n_inv, above_inv) if use == INVESTABLE else (n_all, above_all)
    return {
        "above_ma200": int(above),
        "above_ma200_pct": _pct(above, n),
        "breadth_universe": use,
        "breadth_n": int(n),
        "above_ma200_all": int(above_all),
        "ma200_n_all": int(n_all),
        "above_ma200_pct_all": _pct(above_all, n_all),
        "above_ma200_investable": int(above_inv) if has_inv else None,
        "ma200_n_investable": int(n_inv) if has_inv else None,
        "above_ma200_pct_investable": _pct(above_inv, n_inv) if has_inv else None,
    }


def with_universe(rec: dict, universe: str) -> dict:
    """Bản SAO của một bản ghi đã qua ``breadth_fields``, chọn lại tập ``universe`` từ chính
    các số đếm đã lưu (cùng đường ``breadth_fields``) — replay dựng breadth MỘT lần cho cả
    hai tập."""
    return {**rec, **breadth_fields(rec["ma200_n_all"], rec["above_ma200_all"],
                                    rec.get("ma200_n_investable"),
                                    rec.get("above_ma200_investable"), universe)}


def label_suffix(breadth: dict | None) -> str:
    """Hậu tố nhãn khi độ rộng đo trên tập đầu tư được: `` (269 mã thanh khoản)``; tập ``all``
    hay thiếu dữ liệu ⇒ chuỗi rỗng (chữ brief y nguyên)."""
    b = breadth or {}
    if b.get("breadth_universe") != INVESTABLE or not b.get("breadth_n"):
        return ""
    return f" ({int(b['breadth_n']):,} mã thanh khoản)"
