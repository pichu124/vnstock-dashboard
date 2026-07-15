"""Tests cho vnstock_indicators (Choppiness Index + ConnorsRSI) và
vnstock_strategy.profit_and_recovery — cả 3 từ khảo sát StockSharp 15/07.
Hermetic, data tự chế."""

from __future__ import annotations

import numpy as np

from vnstock_indicators import (
    choppiness_index, chop_label, connors_rsi,
    CHOP_CHOPPY, CHOP_TRENDING,
)


def _bars(closes, spread=0.3):
    c = np.asarray(closes, dtype=float)
    return c + spread, c - spread, c


# ─── Choppiness Index ────────────────────────────────────────────────────────

def test_chop_low_on_clean_trend():
    closes = 100 + np.arange(30) * 1.0     # tăng đều 1 điểm/phiên
    h, l, c = _bars(closes)
    v = choppiness_index(h, l, c)
    assert v is not None and v < CHOP_TRENDING


def test_chop_high_on_tight_range():
    closes = 100 + np.tile([0.0, 0.8], 15)  # dập dềnh trong biên hẹp
    h, l, c = _bars(closes, spread=0.5)
    v = choppiness_index(h, l, c)
    assert v is not None and v > CHOP_CHOPPY


def test_chop_none_when_insufficient_or_degenerate():
    h, l, c = _bars(100 + np.arange(10))
    assert choppiness_index(h, l, c) is None          # < 15 bar
    flat = np.full(30, 100.0)
    assert choppiness_index(flat, flat, flat) is None  # range 0 (1 giá suốt)
    assert choppiness_index(None, None, None) is None


def test_chop_label_bands():
    assert chop_label(70.0) == "đi ngang/choppy"
    assert chop_label(30.0) == "có xu hướng rõ"
    assert chop_label(50.0) == "trung gian"
    assert chop_label(None) is None


# ─── ConnorsRSI ──────────────────────────────────────────────────────────────

def test_crsi_high_when_rising_low_when_falling():
    n = 130
    rising = 100 * (1.004 ** np.arange(n))
    falling = 100 * (0.996 ** np.arange(n))
    up, dn = connors_rsi(rising), connors_rsi(falling)
    assert up is not None and dn is not None
    assert up > 60 and dn < 40
    assert dn < up


def test_crsi_very_low_after_sharp_drop_in_downtrend():
    closes = list(100 * (0.998 ** np.arange(128))) + [70.0, 66.0]  # rơi mạnh cuối
    v = connors_rsi(closes)
    assert v is not None and v < 15


def test_crsi_none_when_insufficient_or_bad_data():
    assert connors_rsi(np.arange(1, 50, dtype=float)) is None   # < 102 bar
    bad = np.full(130, 100.0)
    bad[125] = -5.0                                             # giá rác
    assert connors_rsi(bad) is None
    assert connors_rsi(None) is None


# ─── profit_factor + recovery_factor ─────────────────────────────────────────

def test_profit_and_recovery_basic():
    from vnstock_strategy import profit_and_recovery
    pf, rf = profit_and_recovery(np.array([1.0, 2.0, -1.0]))
    assert pf == 3.0                     # Σlãi 3 / |Σlỗ| 1
    assert rf == 2.0                     # net 2 / maxDD 1 (cum 1→3→2)


def test_profit_and_recovery_degenerate_returns_none():
    from vnstock_strategy import profit_and_recovery
    pf, rf = profit_and_recovery(np.array([1.0, 2.0, 0.5]))  # không có lệnh lỗ
    assert pf is None and rf is None      # equity không drawdown → rf None
    pf, rf = profit_and_recovery(np.array([]))
    assert pf is None and rf is None


def test_profit_and_recovery_all_losses():
    from vnstock_strategy import profit_and_recovery
    pf, rf = profit_and_recovery(np.array([-1.0, -2.0]))
    assert pf == 0.0                      # Σlãi 0 / |Σlỗ| 3
    assert rf == -1.0                     # net -3 / maxDD 3


def test_backtest_empty_metrics_carry_new_keys():
    # dict rỗng (0 lệnh) phải mang đủ key mới để downstream không KeyError
    import inspect
    import vnstock_strategy as vs
    src = inspect.getsource(vs.backtest)
    assert '"profit_factor"' in src and '"recovery_factor"' in src
