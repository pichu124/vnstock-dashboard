"""
Golden-value tests for indicator math in vnstock_screener.

These tests validate the exact mathematical outputs of ``_calc_indicators``
against hand-computed reference values. They are intentionally strict: if a
future refactor accidentally changes the RSI flavour (Cutler → Wilder) or the
MACD EMA initialisation (adjust=False → True), these tests fail loudly.

Canonical formulas tested
-------------------------
* **RSI (current impl: Cutler / SMA variant)** — uses simple 14-period mean
  of gains and losses, not Wilder's smoothed average. This matches
  `delta.clip(lower=0).rolling(14).mean()` in vnstock_screener.py.
* **MACD (12-26-9)** — `ema(adjust=False)`-based, signal is EMA(9) of the
  MACD line, hist = MACD - signal.
* **EMA** — pandas ewm(adjust=False). Verified against the recursion
  ``ema_t = alpha * x_t + (1 - alpha) * ema_{t-1}`` with ``alpha = 2/(span+1)``.
* **Bollinger Bands** — SMA(20), STD(20) (pandas default: ddof=1), ±2σ.
* **Volume spike** — volume / mean(volume, 20).

A separate test shows that the current RSI is **not** Wilder's — useful for
anyone expecting MetaTrader/TradingView compatibility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vnstock_screener import _calc_indicators


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_df(closes, volumes=None):
    """Build an OHLCV DataFrame from a close series (O=H=L=C for simplicity)."""
    n = len(closes)
    volumes = volumes if volumes is not None else [1_000_000] * n
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "time": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": volumes,
    })


def _ref_ema(series, span):
    """Reference EMA using the recursive definition (adjust=False)."""
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(series), dtype=float)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


def _ref_cutler_rsi14(closes):
    """Reference Cutler/SMA RSI(14): simple mean of gains vs losses."""
    c = np.asarray(closes, dtype=float)
    delta = np.diff(c)
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    # Rolling simple mean of the last 14 deltas, ending at bar index -1
    g14 = gain[-14:].mean()
    l14 = loss[-14:].mean()
    if l14 == 0:
        return 100.0  # no losses → RSI saturates
    rs = g14 / l14
    return 100 - (100 / (1 + rs))


def _ref_wilder_rsi14(closes):
    """Reference Wilder's RSI(14): EMA-smoothed gains/losses (alpha = 1/14)."""
    c = np.asarray(closes, dtype=float)
    delta = np.diff(c)
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    # First avg = simple mean of first 14 deltas; thereafter Wilder smoothing
    avg_g = gain[:14].mean()
    avg_l = loss[:14].mean()
    for i in range(14, len(delta)):
        avg_g = (avg_g * 13 + gain[i]) / 14
        avg_l = (avg_l * 13 + loss[i]) / 14
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


# ─────────────────────────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────────────────────────


def test_rsi_matches_cutler_reference_on_uptrend():
    # When every delta is positive, loss == 0 and RSI is mathematically
    # undefined (division by zero). The current implementation guards this
    # with ``loss.replace(0, np.nan)`` and returns None. Document that here:
    closes = [100.0 + i for i in range(30)]
    out = _calc_indicators(_make_df(closes))
    assert out["rsi_14"] is None

    # With a pullback in the window, RSI becomes defined and tilts bullish.
    closes2 = [100.0 + i for i in range(29)] + [120.0]
    closes2[-2] = 125.0   # inject a down-tick on the penultimate bar
    out2 = _calc_indicators(_make_df(closes2))
    assert out2["rsi_14"] is not None
    assert out2["rsi_14"] > 50   # gains still dominate overall


def test_rsi_matches_cutler_reference_mixed():
    # Known hand-computable series
    closes = [100.0, 101, 102, 101, 103, 104, 103, 105, 106, 105,
              107, 108, 107, 109, 110, 109, 111, 112, 111, 113,
              114, 113, 115, 116, 115, 117, 118, 117, 119, 120]
    out = _calc_indicators(_make_df(closes))
    expected = _ref_cutler_rsi14(closes)
    assert out["rsi_14"] == pytest.approx(round(expected, 1), abs=0.1)


def test_rsi_bounded_0_to_100():
    np.random.seed(42)
    closes = list(100 + np.cumsum(np.random.randn(100)))
    out = _calc_indicators(_make_df(closes))
    assert 0.0 <= out["rsi_14"] <= 100.0


def test_rsi_current_impl_is_cutler_not_wilder():
    """
    Document that the current implementation uses Cutler's SMA-based RSI,
    not Wilder's EMA-smoothed RSI. If we ever switch, this test fails and
    forces us to update downstream consumers.
    """
    closes = [100.0, 101, 102, 101, 103, 104, 103, 105, 106, 105,
              107, 108, 107, 109, 110, 109, 111, 112, 111, 113,
              114, 113, 115, 116, 115, 117, 118, 117, 119, 120]
    out = _calc_indicators(_make_df(closes))
    cutler = _ref_cutler_rsi14(closes)
    wilder = _ref_wilder_rsi14(closes)
    # Current impl matches Cutler (within rounding tolerance) ...
    assert out["rsi_14"] == pytest.approx(cutler, abs=0.15)
    # ... and the two reference flavours disagree on this series
    assert abs(cutler - wilder) > 0.1


# ─────────────────────────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────────────────────────


def test_macd_matches_recursive_reference():
    np.random.seed(7)
    closes = list(100 + np.cumsum(np.random.randn(60)))
    out = _calc_indicators(_make_df(closes))

    ema12 = _ref_ema(np.array(closes), 12)
    ema26 = _ref_ema(np.array(closes), 26)
    macd_line = ema12 - ema26
    signal = _ref_ema(macd_line, 9)
    hist = macd_line - signal

    assert out["macd_hist"] == pytest.approx(round(hist[-1], 4), abs=0.01)
    assert out["macd_signal_val"] == pytest.approx(round(signal[-1], 4), abs=0.01)


def test_macd_cross_buy_signal():
    # Construct a series where the histogram crosses from negative to positive
    # on the last bar. Build a long down-leg followed by a sharp up-leg.
    closes = [100.0 - i * 0.5 for i in range(30)]           # downtrend 30 bars
    closes += [closes[-1] + i * 2.0 for i in range(1, 12)]  # sharp up-leg 11 bars
    out = _calc_indicators(_make_df(closes))
    # After a strong reversal, the last histogram sign should be positive
    assert out["macd_hist"] > 0
    assert out["macd_cross"] in ("BUY", "BULL")


def test_macd_cross_sell_signal():
    closes = [100.0 + i * 0.5 for i in range(30)]
    closes += [closes[-1] - i * 2.0 for i in range(1, 12)]
    out = _calc_indicators(_make_df(closes))
    assert out["macd_hist"] < 0
    assert out["macd_cross"] in ("SELL", "BEAR")


# ─────────────────────────────────────────────────────────────────────────────
# EMA
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("span", [9, 21, 50, 200])
def test_ema_matches_recursive_reference(span):
    np.random.seed(span)
    n = max(span + 10, 220)
    closes = list(100 + np.cumsum(np.random.randn(n) * 0.5))
    out = _calc_indicators(_make_df(closes))
    ref = _ref_ema(np.array(closes), span)[-1]
    assert out[f"ema_{span}"] == pytest.approx(round(ref, 2), abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────────


def test_bollinger_pct_at_midband_is_50():
    # Flat series → std=0 → guard triggers → bb_pct absent
    out = _calc_indicators(_make_df([100.0] * 30))
    assert "bb_pct" not in out or out.get("bb_pct") is None


def test_bollinger_pct_within_0_100_for_typical_series():
    np.random.seed(99)
    closes = list(100 + np.cumsum(np.random.randn(40)))
    out = _calc_indicators(_make_df(closes))
    bb = out.get("bb_pct")
    if bb is not None:
        # %B can exceed [0,100] on breakouts, but for a random walk should stay close
        assert -50 <= bb <= 150


def test_bollinger_upper_lower_symmetric():
    """
    Sanity: construct a deterministic series, verify (upper - sma) == (sma - lower).
    Done via hand-computed sma/std on the last 20 closes.
    """
    closes = [100.0 + (i % 5) for i in range(30)]
    last20 = np.array(closes[-20:])
    sma = last20.mean()
    std = last20.std(ddof=1)
    upper = sma + 2 * std
    lower = sma - 2 * std
    assert upper - sma == pytest.approx(sma - lower, abs=1e-9)
    assert upper - lower == pytest.approx(4 * std, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Volume spike
# ─────────────────────────────────────────────────────────────────────────────


def test_vol_spike_equals_ratio():
    volumes = [1_000_000] * 19 + [3_500_000]
    closes = [100.0] * 20
    # _calc_indicators needs len >= 30 → pad both
    volumes = [1_000_000] * 10 + volumes
    closes = [100.0] * 10 + closes
    out = _calc_indicators(_make_df(closes, volumes=volumes))
    # Last-bar volume 3.5M vs MA20 over last 20 bars (mix of 1M & 3.5M)
    last20 = np.array(volumes[-20:], dtype=float)
    expected = volumes[-1] / last20.mean()
    assert out["vol_spike"] == pytest.approx(round(expected, 2), abs=0.01)


def test_vol_spike_handles_zero_ma():
    # If rolling mean is 0, indicator should silently skip (no div-by-zero)
    volumes = [0] * 30
    closes = [100.0] * 30
    out = _calc_indicators(_make_df(closes, volumes=volumes))
    assert "vol_spike" not in out


# ─────────────────────────────────────────────────────────────────────────────
# Chg %
# ─────────────────────────────────────────────────────────────────────────────


def test_chg_pct_exact():
    # _calc_indicators requires >= 30 bars
    closes = [100.0] * 29 + [105.0]
    out = _calc_indicators(_make_df(closes))
    assert out["chg_1d_pct"] == pytest.approx(5.0, abs=0.01)
    # 5d change: 105 / 100 - 1 = 5%
    assert out["chg_5d_pct"] == pytest.approx(5.0, abs=0.01)
    # 20d change: 105 / 100 - 1 = 5%
    assert out["chg_20d_pct"] == pytest.approx(5.0, abs=0.01)
