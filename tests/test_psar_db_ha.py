"""Tests cho 3 món khảo sát je-suis-tm/quant-trading (2026-07-15):
Parabolic SAR (SL trailing thích ứng) + double bottom W neo Bollinger +
Heikin-Ashi streak. Hermetic — data tự chế, zero I/O."""

from __future__ import annotations

import numpy as np
import pandas as pd

from vnstock_indicators import (
    parabolic_sar, double_bottom_w, heikin_ashi, ha_trend_streak,
)


# ─── Parabolic SAR ───────────────────────────────────────────────────────────

def _trend_bars(n=30, start=100.0, step=1.0):
    c = start + np.arange(n) * step
    return c + 0.4, c - 0.4, c          # high, low, close


def test_psar_uptrend_sar_below_price():
    h, l, c = _trend_bars(step=1.0)
    sar, trend = parabolic_sar(h, l, c)
    assert trend == 1
    assert sar < c[-1]
    assert sar <= min(l[-1], l[-2])      # SAR bị clamp bởi đáy 2 bar trước


def test_psar_downtrend_sar_above_price():
    h, l, c = _trend_bars(step=-1.0)
    sar, trend = parabolic_sar(h, l, c)
    assert trend == -1 and sar > c[-1]


def test_psar_ratchets_up_with_trend():
    # AF tăng tốc → SAR của trend dài phải CAO hơn (bám sát hơn) SAR lúc
    # trend mới bắt đầu, tính theo khoảng cách tới giá
    h, l, c = _trend_bars(n=40, step=1.0)
    sar_early, _ = parabolic_sar(h[:12], l[:12], c[:12])
    sar_late, _ = parabolic_sar(h, l, c)
    gap_early = c[11] - sar_early
    gap_late = c[-1] - sar_late
    assert gap_late < gap_early * 1.5    # không doãng ra theo trend


def test_psar_reversal_flips_trend():
    down = np.linspace(100, 80, 20)
    up = np.linspace(80.5, 105, 20)
    c = np.concatenate([down, up])
    sar, trend = parabolic_sar(c + 0.4, c - 0.4, c)
    assert trend == 1 and sar < c[-1]


def test_psar_guards():
    assert parabolic_sar([1, 2], [0.5, 1]) is None                # < 5 bar
    h, l, c = _trend_bars()
    l2 = l.copy()
    l2[10] = h[10] + 5                                            # high < low
    assert parabolic_sar(h, l2, c) is None
    c3 = c.copy()
    c3[15] = c3[14] * 500                                         # unit break
    assert parabolic_sar(c3 + 0.4, c3 - 0.4, c3) is None
    assert parabolic_sar(None, None) is None


def test_psar_stop_hint_rules():
    from vnstock_strategy import psar_stop_hint
    h, l, c = _trend_bars(n=40, step=1.0)
    hint = psar_stop_hint(50.0, h, l, c)      # SL gốc thấp xa → PSAR thắng
    assert hint is not None and hint > 50.0
    assert psar_stop_hint(c[-1] + 10, h, l, c) is None   # SL gốc cao hơn SAR
    hd, ld, cd = _trend_bars(step=-1.0)
    assert psar_stop_hint(50.0, hd, ld, cd) is None      # downtrend → không gợi ý


# ─── Double bottom W ─────────────────────────────────────────────────────────

def _w_series():
    xs = list(100 + 0.15 * np.sin(np.arange(25)))        # nền phẳng
    xs += list(np.linspace(99.5, 88.0, 9))               # rơi mạnh → đáy 1 (thủng band)
    xs += list(np.linspace(88.8, 96.5, 8))               # hồi về neckline
    xs += list(np.linspace(96.0, 89.0, 9))               # đáy 2 nông hơn (trên band)
    xs += list(np.linspace(89.6, 96.0, 7))               # hồi lần 2
    xs += [95.9, 97.2]                                   # breakout > neckline
    return np.array(xs)


def test_double_bottom_detected_on_breakout():
    c = _w_series()
    res = double_bottom_w(c, low=c - 0.25)
    assert res is not None
    assert res["neckline"] > res["bottom"] * 1.03
    assert res["bars_since_bottom"] < 15


def test_double_bottom_rejects_unequal_bottoms():
    c = _w_series()
    c[34:36] -= 6.0                       # đáy 1 sâu hơn hẳn (>3% lệch)
    assert double_bottom_w(c, low=c - 0.25) is None


def test_double_bottom_requires_recent_breakout():
    c = _w_series()[:-2]                  # bỏ 2 bar breakout — vẫn dưới neckline
    assert double_bottom_w(c, low=c - 0.25) is None
    stale = np.concatenate([_w_series(), np.full(6, 97.0)])
    assert double_bottom_w(stale, low=stale - 0.25) is None   # breakout đã cũ


def test_double_bottom_guards():
    assert double_bottom_w(np.arange(1, 30, dtype=float)) is None   # < 40 bar
    c = _w_series()
    c[40] = c[39] * 500                                             # unit break
    assert double_bottom_w(c, low=c - 0.25) is None
    assert double_bottom_w(None) is None


# ─── Heikin-Ashi ─────────────────────────────────────────────────────────────

def _smooth_trend_ohlc(n=12, start=100.0, step=1.0):
    """Mỗi bar mở tại close bar trước, đóng cao/thấp hơn step — trend sạch."""
    o = start + np.arange(n) * step
    c = o + step
    if step > 0:
        h, l = c + 0.1, o - 0.02          # râu dưới ~0
    else:
        h, l = o + 0.02, c - 0.1          # râu trên ~0
    return o, h, l, c


def test_heikin_ashi_math():
    o = np.array([100.0, 102.0]); c = np.array([102.0, 104.0])
    h, l = c + 1, o - 1
    ha = heikin_ashi(o, h, l, c)
    assert ha is not None
    ha_open, ha_high, ha_low, ha_close = ha
    assert ha_close[0] == (o[0] + h[0] + l[0] + c[0]) / 4
    assert ha_open[0] == o[0]
    assert ha_open[1] == (ha_open[0] + ha_close[0]) / 2
    assert ha_high[1] >= max(ha_open[1], ha_close[1])


def test_ha_streak_up_down_choppy():
    o, h, l, c = _smooth_trend_ohlc(step=1.0)
    assert ha_trend_streak(o, h, l, c) >= 3
    o, h, l, c = _smooth_trend_ohlc(step=-1.0)
    assert ha_trend_streak(o, h, l, c) <= -3
    # răng cưa — HA smooth nhưng râu 2 phía → không có streak sạch dài
    zig = 100 + np.tile([0.0, 1.5], 10)
    assert abs(ha_trend_streak(zig, zig + 2.0, zig - 2.0,
                               100 + np.tile([1.5, 0.0], 10))) <= 2


def test_ha_guards():
    assert ha_trend_streak([100], [101], [99], [100]) == 0      # < 2 bar
    o, h, l, c = _smooth_trend_ohlc()
    c2 = c.copy(); c2[5] = c2[4] * 500                          # unit break
    assert ha_trend_streak(o, h, l, c2) == 0


# ─── Wiring screener + preset groups ─────────────────────────────────────────

def test_calc_indicators_emits_double_bottom_and_ha():
    from vnstock_screener import _calc_indicators
    c = _w_series()
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=len(c), freq="D"),
        "open": c + 0.1, "high": c + 0.4, "low": c - 0.25, "close": c,
        "volume": 100_000,
    })
    r = _calc_indicators(df)
    assert r.get("double_bottom") is True
    assert r.get("db_neckline") and r["db_neckline"] > 90


def test_new_presets_filters():
    from vnstock_screener import PRESETS
    assert PRESETS["double_bottom"]["filter"]({"double_bottom": True})
    assert not PRESETS["double_bottom"]["filter"]({})
    assert PRESETS["ha_trend"]["filter"]({"ha_streak": 4})
    assert not PRESETS["ha_trend"]["filter"]({"ha_streak": 2})
    assert not PRESETS["ha_trend"]["filter"]({"ha_streak": -5})


def test_preset_score_groups_updated():
    from vnstock_preset_score import _MEANREV_PRESETS, _TREND_PRESETS
    assert "double_bottom" in _MEANREV_PRESETS
    assert "ha_trend" in _TREND_PRESETS
