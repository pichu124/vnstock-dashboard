"""
vnstock_indicators.py — chỉ báo bổ sung thuần numpy (khảo sát StockSharp 15/07)
================================================================================
Hai chỉ báo mượn Ý TƯỞNG từ StockSharp Algo.Indicators (LGPL — không copy
code), deterministic thuần, zero LLM/fetch:

- ``choppiness_index`` (CHOP 14): đo trend-vs-range thuần giá —
  100·log10(ΣTR/(maxH−minL))/log10(n). > 61.8 = đi ngang/choppy,
  < 38.2 = có xu hướng. LEVEL-gauge hiển thị/ngữ cảnh (mirror triết lý
  liquidity_spread), KHÔNG vào composite regime score.

- ``connors_rsi`` (CRSI): trung bình RSI(3) + RSI-streak(2) + percent-rank
  ROC(1) trên 100 phiên — mean-reversion kinh điển (bản CỔ ĐIỂN percent-rank,
  KHÔNG phải biến thể RSI-của-ROC trong StockSharp). < 10 = quá bán ngắn hạn.

Input nhận list/np.ndarray/pandas.Series; trả float hoặc None khi thiếu
data / suy biến (không nổ, không độn 0).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

_CHOP_LEN_DEFAULT = 14
CHOP_CHOPPY = 61.8    # trên ngưỡng → đi ngang/choppy (mốc Fibonacci chuẩn)
CHOP_TRENDING = 38.2  # dưới ngưỡng → có xu hướng rõ


def _arr(x) -> Optional[np.ndarray]:
    try:
        a = np.asarray(x, dtype=float)
    except Exception:
        return None
    if a.ndim != 1:
        return None
    return a


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
