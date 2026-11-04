"""Các cách tìm hỗ trợ / kháng cự (PTKT P2b) — HÀM THUẦN, không I/O, chưa nối vào brief.

Bối cảnh `docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §15: S/R pivot 60 phiên đang chạy KHÔNG hơn mức
giả cùng khoảng cách ⇒ đo thử cách khác bằng `scripts/eval_sr_methods.py` rồi mới chọn.

Mỗi phương pháp: `fn(bars, close, atr_t=None) -> {"support": [...], "resistance": [...]}` —
tối đa 2 mức mỗi phía, GẦN NHẤT TRƯỚC. `bars` = DataFrame OHLC(V) sắp tăng theo ngày, bar cuối
là phiên t, `close` = đóng cửa phiên t, `atr_t` = ATR(14) tại t nếu đã tính sẵn. Chỉ đọc `bars`
(không nhìn trước — `levels_at` / `window_at` cắt đúng bar ≤ t).

Luật lọc CHUNG cho mọi phương pháp (so công bằng) = luật của đường đang chạy
(`vnstock_brief._select_sr_levels`): cách giá ≥ `_SR_MIN_DIST_PCT`, ≤ `_SR_MAX_MOVE_PCT`, hai
mức cùng phía cách nhau ≥ `_SR_MIN_GAP_PCT`. Không có ứng viên nào qua lọc ⇒ danh sách rỗng.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

from vnstock_brief import _SR_MIN_DIST_PCT, _SR_MIN_GAP_PCT, _select_sr_levels
from vnstock_brief_canon import _SR_MAX_MOVE_PCT
from vnstock_indicators import atr

ATR_N = 14
LOOKBACK = 120            # touch_cluster / volume_node: số phiên gần nhất
SWING_W = 2               # đỉnh/đáy swing = cực trị của 2 bar mỗi bên (2 bar cuối chưa thành)
CLUSTER_K = 0.5           # touch_cluster: vùng rộng tối đa k·ATR
MIN_TOUCHES = 2
VP_BIN_ATR = 0.5          # volume_node: bề rộng bin = 0,5·ATR
VP_MAX_BINS = 400
ROUND_TARGET_PCT = 2.0    # round_number: bước tròn 1-2-5 ≥ 2% giá
ATR_BAND = (1.5, 3.0)     # atr_band: mức 1 / mức 2 = close ∓ 1,5·ATR / 3·ATR
WINDOW = 260              # levels_at: số bar đưa vào (đủ 252 cho đáy/đỉnh 52 tuần)

Levels = dict[str, list[float]]
EMPTY: Levels = {"support": [], "resistance": []}


def _nearest(cands, close: float) -> Levels:
    """Ứng viên → 2 mức mỗi phía qua luật lọc chung, gần nhất trước."""
    vals = [float(v) for v in cands if v == v and v and v > 0]
    below = sorted({round(v, 2) for v in vals if v < close}, reverse=True)
    above = sorted({round(v, 2) for v in vals if v > close})
    return {"support": _select_sr_levels(below, close),
            "resistance": _select_sr_levels(above, close)}


def _atr_last(bars: pd.DataFrame, atr_t: float | None = None) -> float | None:
    """ATR(14) Wilder tại bar cuối; `atr_t` = đã tính sẵn trên cả chuỗi (script đo, tránh
    tính lại mỗi ngày — Wilder nhân quả nên vẫn chỉ dùng bar ≤ t)."""
    if atr_t is None:
        if len(bars) < ATR_N:
            return None
        atr_t = atr(bars["high"], bars["low"], bars["close"], ATR_N).iloc[-1]
    return float(atr_t) if atr_t == atr_t and atr_t > 0 else None


def _valid_close(close) -> float | None:
    try:
        c = float(close)
    except (TypeError, ValueError):
        return None
    return c if c == c and c > 0 else None


# ── Phương pháp ──────────────────────────────────────────────────────────

def pivot60(bars: pd.DataFrame, close: float, atr_t: float | None = None,
            with_extremes: bool = False) -> Levels:
    """Đường đang chạy: high/low 60 bar bỏ 2 bar cuối (`vnstock_brief.ticker_sr_levels`).
    `with_extremes` = thêm đỉnh/đáy 20 phiên + 52 tuần như `_vnindex_technicals` (VN-Index)."""
    c = _valid_close(close)
    if c is None:
        return EMPTY
    high, low = (bars[col].to_numpy(dtype=float) for col in ("high", "low"))
    hs, ls = high[np.isfinite(high) & (high != 0)], low[np.isfinite(low) & (low != 0)]
    if len(hs) < 12 or len(ls) < 12:
        return EMPTY
    # Kháng cự CHỈ từ high, hỗ trợ CHỈ từ low — như đường đang chạy.
    above, below = list(hs[-62:-2][hs[-62:-2] > c]), list(ls[-62:-2][ls[-62:-2] < c])
    if with_extremes:
        above += [v for v in (np.nanmax(high[-20:]), np.nanmax(high[-252:])) if v > c]
        below += [v for v in (np.nanmin(low[-20:]), np.nanmin(low[-252:])) if v < c]
    return {"support": _nearest(below, c)["support"],
            "resistance": _nearest(above, c)["resistance"]}


def _swing_points(bars: pd.DataFrame, w: int = SWING_W) -> np.ndarray:
    """Giá các đỉnh (high) và đáy (low) swing; chuỗi bằng nhau liền nhau tính 1 lần."""
    out = []
    for col, agg in (("high", np.max), ("low", np.min)):
        x = bars[col].to_numpy(dtype=float)
        if len(x) < 2 * w + 1:
            continue
        ext = agg(np.lib.stride_tricks.sliding_window_view(x, 2 * w + 1), axis=1)
        hit = np.zeros(len(x), dtype=bool)
        hit[w:len(x) - w] = x[w:len(x) - w] == ext      # cần đủ w bar SAU ⇒ w bar cuối chưa thành
        first = hit & ~np.concatenate([[False], hit[:-1]])
        out.append(x[first])
    return np.concatenate(out) if out else np.array([])


def touch_cluster(bars: pd.DataFrame, close: float, atr_t: float | None = None,
                  k: float = CLUSTER_K, lookback: int = LOOKBACK,
                  min_touches: int = MIN_TOUCHES) -> Levels:
    """Gom đỉnh/đáy swing `lookback` phiên thành vùng rộng ≤ k·ATR(14); vùng ≥ `min_touches`
    lần chạm là ứng viên, mức = trung bình vùng. Mỗi phía chọn 2 vùng NHIỀU lần chạm nhất (hoà
    ⇒ gần hơn) qua luật lọc chung, rồi in gần nhất trước."""
    c, a = _valid_close(close), _atr_last(bars, atr_t)
    if c is None or a is None:
        return EMPTY
    pts = np.sort(_swing_points(bars.tail(lookback)))
    tol = k * a
    zones: list[list[float]] = []
    for p in pts:
        if zones and p - zones[-1][0] <= tol:
            zones[-1].append(float(p))
        else:
            zones.append([float(p)])
    cands = [(round(float(np.mean(z)), 2), len(z)) for z in zones if len(z) >= min_touches]
    return {"support": _by_touches([x for x in cands if x[0] < c], c),
            "resistance": _by_touches([x for x in cands if x[0] > c], c)}


def _by_touches(cands: list[tuple[float, int]], close: float) -> list[float]:
    """Luật lọc chung (như `_select_sr_levels`) nhưng ưu tiên số lần chạm."""
    out: list[float] = []
    for v, _ in sorted(cands, key=lambda x: (-x[1], abs(x[0] / close - 1))):
        d = abs(v / close - 1)
        if d < _SR_MIN_DIST_PCT or d > _SR_MAX_MOVE_PCT:
            continue
        if any(abs(v / o - 1) < _SR_MIN_GAP_PCT for o in out):
            continue
        out.append(v)
        if len(out) == 2:
            break
    return sorted(out, key=lambda v: abs(v - close))


def volume_profile(bars: pd.DataFrame, bin_width: float) -> tuple[np.ndarray, np.ndarray]:
    """(tâm bin, khối lượng) — KL mỗi phiên rải ĐỀU trên đoạn [low, high] của phiên đó."""
    lo, hi, v = (bars[c].to_numpy(dtype=float) for c in ("low", "high", "volume"))
    ok = np.isfinite(lo) & np.isfinite(hi) & np.isfinite(v) & (v > 0) & (hi >= lo)
    lo, hi, v = lo[ok], hi[ok], v[ok]
    if not len(v) or bin_width <= 0:
        return np.array([]), np.array([])
    bin_width = max(bin_width, (hi.max() - lo.min()) / (VP_MAX_BINS - 1))  # ATR tí hon: nới bin
    nb = int(math.ceil((hi.max() - lo.min()) / bin_width)) + 1
    edges = lo.min() + bin_width * np.arange(nb + 1)
    span = hi - lo
    ov = np.clip(np.minimum(hi[:, None], edges[None, 1:])
                 - np.maximum(lo[:, None], edges[None, :-1]), 0, None)
    share = np.where(span[:, None] > 0, ov / np.where(span > 0, span, 1)[:, None], 0.0)
    flat = span <= 0                               # phiên đứng giá: dồn cả vào bin chứa giá
    if flat.any():
        idx = np.clip(((lo[flat] - edges[0]) / bin_width).astype(int), 0, nb - 1)
        share[np.flatnonzero(flat), idx] = 1.0
    return (edges[:-1] + edges[1:]) / 2, (share * v[:, None]).sum(axis=0)


def volume_node(bars: pd.DataFrame, close: float, atr_t: float | None = None,
                lookback: int = LOOKBACK, bin_atr: float = VP_BIN_ATR) -> Levels:
    """Đỉnh cục bộ của phân bổ khối lượng theo giá `lookback` phiên (bin = bin_atr·ATR(14)),
    chỉ giữ đỉnh ≥ KL trung bình mỗi bin; mức = tâm bin. Không có cột volume ⇒ rỗng."""
    c, a = _valid_close(close), _atr_last(bars, atr_t)
    if c is None or a is None or "volume" not in bars.columns:
        return EMPTY
    centers, prof = volume_profile(bars.tail(lookback), bin_atr * a)
    if len(prof) < 3 or prof.sum() <= 0:
        return EMPTY
    p = np.concatenate([[0.0], prof, [0.0]])
    peak = (p[1:-1] > p[:-2]) & (p[1:-1] >= p[2:]) & (prof >= prof.mean())
    return _nearest(centers[peak], c)


def _nice_step(x: float) -> float:
    e = 10.0 ** math.floor(math.log10(x))
    return next(m * e for m in (1, 2, 5, 10) if m * e >= x - 1e-12)


def round_number(bars: pd.DataFrame, close: float, atr_t: float | None = None) -> Levels:
    """Mốc ngây thơ: bội số của bước tròn 1-2-5 gần nhất ≥ 2% giá (23,4 → 0,5; 1.250 → 50)."""
    c = _valid_close(close)
    if c is None:
        return EMPTY
    step = _nice_step(c * ROUND_TARGET_PCT / 100)
    m = math.floor(c / step)
    cands = [round((m + j) * step, 6) for j in range(-6, 8)]
    return _nearest(cands, c)


def atr_band(bars: pd.DataFrame, close: float, atr_t: float | None = None,
             mults: tuple[float, float] = ATR_BAND) -> Levels:
    """Mốc ngây thơ: close ∓ 1,5·ATR(14) (mức 1) và ∓ 3·ATR (mức 2, cho trigger)."""
    c, a = _valid_close(close), _atr_last(bars, atr_t)
    if c is None or a is None:
        return EMPTY
    return _nearest([c + s * m * a for m in mults for s in (-1, 1)], c)


METHODS: dict[str, Callable[..., Levels]] = {
    "pivot60": pivot60,
    "touch_cluster": touch_cluster,
    "volume_node": volume_node,
    "round_number": round_number,
    "atr_band": atr_band,
}


def window_at(bars: pd.DataFrame, t: int, window: int = WINDOW) -> pd.DataFrame:
    """`window` bar kết thúc ĐÚNG ở phiên vị trí t — mọi phương pháp chỉ thấy chừng này."""
    return bars.iloc[max(0, t + 1 - window):t + 1]


def levels_at(bars: pd.DataFrame, t: int, method: Callable[..., Levels],
              window: int = WINDOW, **kw) -> Levels:
    """Mức của `method` tại phiên vị trí `t` (chỉ bar ≤ t)."""
    if t < 0 or t >= len(bars):
        return EMPTY
    w = window_at(bars, t, window)
    return method(w, float(w["close"].iloc[-1]), **kw)
