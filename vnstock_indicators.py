"""
vnstock_indicators.py — chỉ báo bổ sung thuần numpy
====================================================
Các chỉ báo mượn Ý TƯỞNG từ khảo sát repo ngoài (không copy code),
deterministic thuần, zero LLM/fetch:

Từ StockSharp Algo.Indicators (LGPL, khảo sát 15/07):
- ``choppiness_index`` (CHOP 14): đo trend-vs-range thuần giá —
  100·log10(ΣTR/(maxH−minL))/log10(n). > 61.8 = đi ngang/choppy,
  < 38.2 = có xu hướng. LEVEL-gauge hiển thị/ngữ cảnh (mirror triết lý
  liquidity_spread), KHÔNG vào composite regime score.
- ``connors_rsi`` (CRSI): trung bình RSI(3) + RSI-streak(2) + percent-rank
  ROC(1) trên 100 phiên — mean-reversion kinh điển (bản CỔ ĐIỂN percent-rank,
  KHÔNG phải biến thể RSI-của-ROC trong StockSharp). < 10 = quá bán ngắn hạn.

Từ je-suis-tm/quant-trading (Apache 2.0, khảo sát 15/07):
- ``parabolic_sar``: PSAR Wilder chuẩn — trailing stop THÍCH ỨNG (AF tăng
  tốc theo trend; equity dùng AF 0.01 theo ghi chú của repo gốc).
- ``double_bottom_w``: nhận diện 2 đáy hình W neo Bollinger — pattern
  recognition SỐ HỌC trên cấu trúc giá nhiều tuần (bổ sung mẫu nến 1-5
  phiên). Ngưỡng TƯƠNG ĐỐI theo % giá (repo gốc dùng alpha tuyệt đối
  0.0001 cho giá FX ~1.0 — scale-dependent, bẫy đã ghi khi khảo sát).
- ``heikin_ashi`` + ``ha_trend_streak``: biến đổi Heikin-Ashi lọc nhiễu
  trend; streak nến HA cùng màu không râu ngược = trend sạch.

Input nhận list/np.ndarray/pandas.Series; trả float/None khi thiếu data /
suy biến (không nổ, không độn 0). Mọi hàm nhìn chuỗi giá dài đều có guard
unit-break ×200 (bẫy per-bar normalization mã penny — mirror
`_stitch_units`/vnstock_candle_patterns).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

_CHOP_LEN_DEFAULT = 14
CHOP_CHOPPY = 61.8    # trên ngưỡng → đi ngang/choppy (mốc Fibonacci chuẩn)
CHOP_TRENDING = 38.2  # dưới ngưỡng → có xu hướng rõ

_UNIT_BREAK_RATIO = 200.0   # bước nhảy ×≥200 giữa 2 bar = trộn đơn vị giá


def _arr(x) -> Optional[np.ndarray]:
    try:
        a = np.asarray(x, dtype=float)
    except Exception:
        return None
    if a.ndim != 1:
        return None
    return a


def _has_unit_break(a: np.ndarray) -> bool:
    prev = None
    for v in a:
        if np.isfinite(v) and v > 0:
            if prev is not None and (v / prev >= _UNIT_BREAK_RATIO
                                     or prev / v >= _UNIT_BREAK_RATIO):
                return True
            prev = v
    return False


def choppiness_index(high, low, close, length: int = _CHOP_LEN_DEFAULT) -> Optional[float]:
    """CHOP trên ``length`` bar cuối. Cần ``length + 1`` bar (TR dùng close
    trước đó). Range 0 (mọi bar 1 giá — trần/sàn liên tục) → None."""
    h, l, c = _arr(high), _arr(low), _arr(close)
    if h is None or l is None or c is None or length < 2:
        return None
    n = min(len(h), len(l), len(c))
    if n < length + 1:
        return None
    h, l, c = h[-n:], l[-n:], c[-n:]

    hh, ll, cc = h[-length:], l[-length:], c[-length:]
    prev_close = c[-length - 1:-1]
    tr = np.maximum(hh - ll,
                    np.maximum(np.abs(hh - prev_close), np.abs(ll - prev_close)))
    if np.isnan(tr).any():
        return None
    rng = float(np.max(hh) - np.min(ll))
    tr_sum = float(np.sum(tr))
    if rng <= 0 or tr_sum <= 0:
        return None
    return float(100.0 * math.log10(tr_sum / rng) / math.log10(length))


def chop_label(value: Optional[float]) -> Optional[str]:
    """Nhãn tiếng Việt cho giá trị CHOP (None → None)."""
    if value is None:
        return None
    if value > CHOP_CHOPPY:
        return "đi ngang/choppy"
    if value < CHOP_TRENDING:
        return "có xu hướng rõ"
    return "trung gian"


def _wilder_rsi(values: np.ndarray, period: int) -> Optional[float]:
    """RSI Wilder (EWM alpha=1/period) — cùng họ công thức RSI(14) của brief."""
    if len(values) < period + 1:
        return None
    delta = np.diff(values)
    up = np.clip(delta, 0, None)
    dn = np.clip(-delta, 0, None)
    alpha = 1.0 / period
    avg_up, avg_dn = up[0], dn[0]
    for i in range(1, len(delta)):
        avg_up = avg_up + alpha * (up[i] - avg_up)
        avg_dn = avg_dn + alpha * (dn[i] - avg_dn)
    if avg_dn == 0:
        return 100.0 if avg_up > 0 else 50.0
    rs = avg_up / avg_dn
    return float(100.0 - 100.0 / (1.0 + rs))


def _streak_series(closes: np.ndarray) -> np.ndarray:
    """Chuỗi streak Connors: +k sau k phiên tăng liên tiếp, -k giảm, 0 đứng giá."""
    out = np.zeros(len(closes))
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + 1 if out[i - 1] > 0 else 1
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - 1 if out[i - 1] < 0 else -1
        else:
            out[i] = 0
    return out


def connors_rsi(close, rsi_period: int = 3, streak_period: int = 2,
                rank_period: int = 100) -> Optional[float]:
    """CRSI cổ điển = mean(RSI(3), RSI(streak, 2), PercentRank(ROC(1), 100)).

    Cần ``rank_period + 2`` bar. Trả None khi thiếu data / giá rác."""
    c = _arr(close)
    if c is None or len(c) < rank_period + 2:
        return None
    if np.isnan(c[-rank_period - 2:]).any() or (c[-rank_period - 2:] <= 0).any():
        return None

    rsi = _wilder_rsi(c[-(rsi_period * 30 + 1):], rsi_period)
    streak = _streak_series(c[-(rank_period + 2):])
    streak_rsi = _wilder_rsi(streak, streak_period)

    roc = c[1:] / c[:-1] - 1.0
    window = roc[-(rank_period + 1):]      # 100 giá trị trước + hôm nay
    today, history = window[-1], window[:-1]
    if len(history) < rank_period:
        return None
    pct_rank = float(np.sum(history < today) / len(history) * 100.0)

    parts = [p for p in (rsi, streak_rsi, pct_rank) if p is not None]
    if len(parts) != 3:
        return None
    return float(sum(parts) / 3.0)


# ── Parabolic SAR (je-suis-tm/quant-trading, Wilder chuẩn) ───────────────────

def parabolic_sar(high, low, close=None, af_init: float = 0.01,
                  af_step: float = 0.01, af_max: float = 0.2
                  ) -> Optional[tuple]:
    """PSAR Wilder → (sar_cuối, trend_cuối) với trend +1 = uptrend (SAR dưới
    giá) / −1 = downtrend. AF mặc định 0.01 cho equity (repo gốc dùng 0.02
    cho FX/commodity). Cần ≥ 5 bar; data rác/trộn đơn vị → None."""
    h, l = _arr(high), _arr(low)
    if h is None or l is None:
        return None
    n = min(len(h), len(l))
    if n < 5:
        return None
    h, l = h[-n:], l[-n:]
    if (np.isnan(h).any() or np.isnan(l).any() or (h <= 0).any()
            or (l <= 0).any() or (h < l).any()):
        return None
    c = _arr(close)
    if c is not None and len(c) >= n:
        c = c[-n:]
    if _has_unit_break(l):
        return None

    if c is not None and not np.isnan(c[:2]).any():
        trend = 1 if c[1] > c[0] else -1
    else:
        trend = 1 if (h[1] + l[1]) > (h[0] + l[0]) else -1
    sar = l[0] if trend == 1 else h[0]
    ep = h[1] if trend == 1 else l[1]
    af = af_init

    for i in range(2, n):
        sar = sar + af * (ep - sar)
        if trend == 1:
            sar = min(sar, l[i - 1], l[i - 2])   # SAR không được vượt đáy 2 bar trước
            if l[i] < sar:                        # giá thủng SAR → đảo chiều
                trend, sar, ep, af = -1, ep, l[i], af_init
            elif h[i] > ep:
                ep, af = h[i], min(af_max, af + af_step)
        else:
            sar = max(sar, h[i - 1], h[i - 2])
            if h[i] > sar:
                trend, sar, ep, af = 1, ep, h[i], af_init
            elif l[i] < ep:
                ep, af = l[i], min(af_max, af + af_step)

    return float(sar), int(trend)


# ── Double bottom W neo Bollinger (je-suis-tm/quant-trading) ─────────────────

_DB_WINDOW = 75          # cửa sổ tìm mẫu (repo gốc theo Investopedia ~3 tháng)
_DB_TOL_PCT = 3.0        # 2 đáy lệch nhau ≤ 3% (ngưỡng TƯƠNG ĐỐI — bẫy alpha)
_DB_MIN_BOUNCE_PCT = 3.0 # đỉnh giữa (neckline) phải cao hơn đáy ≥ 3%
_DB_MIN_GAP = 5          # 2 đáy cách nhau ≥ 5 bar
_DB_BREAK_RECENT = 3     # breakout neckline phải xảy ra trong ≤ 3 bar cuối


def _local_minima(a: np.ndarray, q: int = 2) -> list:
    """Chỉ số các cực tiểu cục bộ (thấp nhất trong ±q bar)."""
    out = []
    for i in range(q, len(a) - q):
        seg = a[i - q:i + q + 1]
        if a[i] == seg.min() and a[i] < seg.max():
            out.append(i)
    return out


def double_bottom_w(close, low=None, window: int = _DB_WINDOW) -> Optional[dict]:
    """Mẫu 2 đáy hình W neo Bollinger(20,2), KẾT THÚC bằng breakout gần đây.

    Điều kiện (bản viết lại bằng cực trị cục bộ, thay loop O(n·75) gốc):
      1. 2 đáy cuối trong ``window`` bar: cách nhau ≥ 5 bar, giá lệch ≤ 3%.
      2. Đáy 1 chạm/thủng lower band; đáy 2 GIỮ TRÊN lower band (đà giảm
         yếu đi — luật W-bottom Bollinger kinh điển).
      3. Neckline (đỉnh giữa 2 đáy) cao hơn đáy ≥ 3%.
      4. Close vượt neckline trong ≤ 3 bar cuối và bar cuối vẫn trên đó.

    Trả {"neckline", "bottom", "bars_since_bottom"} hoặc None."""
    c = _arr(close)
    if c is None or len(c) < 40:
        return None
    lo = _arr(low)
    if lo is None or len(lo) != len(c):
        lo = c
    tail = min(len(c), window + 20)
    c, lo = c[-tail:], lo[-tail:]
    if np.isnan(c).any() or (c <= 0).any() or _has_unit_break(c):
        return None

    mid = np.full(len(c), np.nan)
    std = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        seg = c[i - 19:i + 1]
        mid[i] = seg.mean()
        std[i] = seg.std(ddof=1)
    lower = mid - 2 * std

    start = max(19, len(c) - window)
    minima = [i for i in _local_minima(lo, q=2) if i >= start]
    if len(minima) < 2:
        return None
    m1, m2 = minima[-2], minima[-1]
    if m2 - m1 < _DB_MIN_GAP:
        return None

    b1, b2 = lo[m1], lo[m2]
    ref = (b1 + b2) / 2
    if abs(b1 - b2) > ref * _DB_TOL_PCT / 100.0:
        return None                       # 2 đáy không cùng vùng giá
    if not (np.isfinite(lower[m1]) and np.isfinite(lower[m2])):
        return None
    if b1 > lower[m1] * 1.005:
        return None                       # đáy 1 phải chạm/thủng lower band
    if b2 <= lower[m2]:
        return None                       # đáy 2 phải GIỮ TRÊN band (đà yếu đi)

    neckline = float(c[m1:m2 + 1].max())
    if neckline < ref * (1 + _DB_MIN_BOUNCE_PCT / 100.0):
        return None                       # bụng W quá nông

    if c[-1] <= neckline:
        return None
    crossed = any(c[k] > neckline and c[k - 1] <= neckline
                  for k in range(len(c) - _DB_BREAK_RECENT, len(c)))
    if not crossed:
        return None                       # breakout cũ rồi — không phải tín hiệu mới

    return {"neckline": round(neckline, 2), "bottom": round(float(ref), 2),
            "bars_since_bottom": int(len(c) - 1 - m2)}


# ── Heikin-Ashi (je-suis-tm/quant-trading) ───────────────────────────────────

_HA_SHADOW_TOL_PCT = 0.15   # râu ngược ≤ 0.15% giá coi như "không râu"


def heikin_ashi(open_, high, low, close) -> Optional[tuple]:
    """Biến đổi Heikin-Ashi → (ha_open, ha_high, ha_low, ha_close) numpy
    arrays. HAc=(O+H+L+C)/4; HAo=(HAo₋₁+HAc₋₁)/2 (đệ quy, khởi tạo O đầu)."""
    o, h, l, c = _arr(open_), _arr(high), _arr(low), _arr(close)
    if any(x is None for x in (o, h, l, c)):
        return None
    n = min(len(o), len(h), len(l), len(c))
    if n < 2:
        return None
    o, h, l, c = o[-n:], h[-n:], l[-n:], c[-n:]
    if np.isnan(np.concatenate([o, h, l, c])).any() or (l <= 0).any():
        return None
    if _has_unit_break(c):
        return None

    ha_close = (o + h + l + c) / 4.0
    ha_open = np.empty(n)
    ha_open[0] = o[0]
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    ha_high = np.maximum.reduce([h, ha_open, ha_close])
    ha_low = np.minimum.reduce([l, ha_open, ha_close])
    return ha_open, ha_high, ha_low, ha_close


def ha_trend_streak(open_, high, low, close,
                    shadow_tol_pct: float = _HA_SHADOW_TOL_PCT) -> int:
    """Số nến Heikin-Ashi CÙNG MÀU liên tiếp tính từ bar cuối, mỗi nến
    KHÔNG có râu ngược đáng kể (nến xanh không râu dưới / nến đỏ không râu
    trên = trend sạch theo luật HA). Trả +N (trend tăng) / −N (giảm) / 0."""
    ha = heikin_ashi(open_, high, low, close)
    if ha is None:
        return 0
    ha_open, ha_high, ha_low, ha_close = ha

    def _clean_bull(i):
        tol = ha_close[i] * shadow_tol_pct / 100.0
        return ha_close[i] > ha_open[i] and ha_low[i] >= ha_open[i] - tol

    def _clean_bear(i):
        tol = ha_close[i] * shadow_tol_pct / 100.0
        return ha_close[i] < ha_open[i] and ha_high[i] <= ha_open[i] + tol

    last = len(ha_close) - 1
    if _clean_bull(last):
        streak = 1
        for i in range(last - 1, 0, -1):
            if _clean_bull(i):
                streak += 1
            else:
                break
        return streak
    if _clean_bear(last):
        streak = 1
        for i in range(last - 1, 0, -1):
            if _clean_bear(i):
                streak += 1
            else:
                break
        return -streak
    return 0


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    n = 130
    trend = np.cumsum(rng.normal(0.4, 0.5, n)) + 100
    chop_series = 100 + np.sin(np.arange(n)) * 2 + rng.normal(0, 0.3, n)
    for name, cl in (("trend", trend), ("sideway", chop_series)):
        h, l = cl + 0.5, cl - 0.5
        print(f"{name:8s} CHOP={choppiness_index(h, l, cl):6.1f} "
              f"({chop_label(choppiness_index(h, l, cl))}) "
              f"CRSI={connors_rsi(cl):.1f}")
