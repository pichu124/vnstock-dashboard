"""Tests for vnstock_screener — indicator calculations & preset filters."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vnstock_screener import _calc_indicators, PRESETS


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 300, base: float = 50.0, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-04-10", periods=n)
    closes = base + np.cumsum(rng.normal(0, 0.5, n))
    closes = np.maximum(closes, 1.0)  # no negative prices
    return pd.DataFrame({
        "time": dates,
        "open": closes + rng.normal(0, 0.2, n),
        "high": closes + abs(rng.normal(0.5, 0.3, n)),
        "low":  closes - abs(rng.normal(0.5, 0.3, n)),
        "close": closes,
        "volume": rng.integers(100_000, 5_000_000, n),
    })


# ── _calc_indicators ────────────────────────────────────────────────────────

class TestCalcIndicators:

    def test_returns_dict_with_expected_keys(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        assert isinstance(result, dict)
        for key in ("rsi_14", "ema_9", "ema_21", "ema_50", "ema_200",
                     "macd_hist", "macd_cross", "bb_pct", "vol_spike",
                     "ema_trend", "long_trend", "above_ma200",
                     "last_close", "last_volume",
                     "chg_1d_pct", "chg_5d_pct", "chg_20d_pct",
                     "52w_high", "52w_low", "52w_pct"):
            assert key in result, f"Missing key: {key}"

    def test_rsi_range(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        rsi = result["rsi_14"]
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_ema_order(self):
        """EMA9 should be closer to current price than EMA200."""
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        assert result["ema_9"] is not None
        assert result["ema_200"] is not None

    def test_macd_cross_values(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        assert result["macd_cross"] in ("BUY", "SELL", "BULL", "BEAR")

    def test_52w_pct_range(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        pct = result["52w_pct"]
        assert 0 <= pct <= 100

    def test_short_data_returns_empty(self):
        df = _make_ohlcv(10)
        result = _calc_indicators(df)
        assert result == {}

    def test_none_input_returns_empty(self):
        result = _calc_indicators(None)
        assert result == {}

    def test_volume_spike_positive(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        assert result["vol_spike"] > 0

    def test_trend_signals(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        assert result["ema_trend"] in ("UP", "DOWN")
        assert result["long_trend"] in ("BULL", "BEAR")
        assert isinstance(result["above_ma200"], bool)

    def test_price_changes(self):
        df = _make_ohlcv(300)
        result = _calc_indicators(df)
        for key in ("chg_1d_pct", "chg_5d_pct", "chg_20d_pct"):
            assert isinstance(result[key], float)


# ── Preset Filters ───────────────────────────────────────────────────────────

class TestPresetFilters:

    def test_oversold_filter(self):
        f = PRESETS["oversold"]["filter"]
        assert f({"rsi_14": 25}) is True
        assert f({"rsi_14": 35}) is False
        assert f({}) is False  # default 999

    def test_overbought_filter(self):
        f = PRESETS["overbought"]["filter"]
        assert f({"rsi_14": 75}) is True
        assert f({"rsi_14": 65}) is False

    def test_momentum_filter(self):
        f = PRESETS["momentum"]["filter"]
        assert f({"macd_cross": "BUY", "ema_trend": "UP"}) is True
        assert f({"macd_cross": "BULL", "ema_trend": "UP"}) is True
        assert f({"macd_cross": "SELL", "ema_trend": "UP"}) is False
        assert f({"macd_cross": "BUY", "ema_trend": "DOWN"}) is False

    def test_breakout_filter(self):
        f = PRESETS["breakout"]["filter"]
        assert f({"52w_pct": 90, "vol_spike": 2.0}) is True
        assert f({"52w_pct": 80, "vol_spike": 2.0}) is False
        assert f({"52w_pct": 90, "vol_spike": 1.0}) is False

    def test_reversal_filter(self):
        f = PRESETS["reversal"]["filter"]
        assert f({"52w_pct": 10, "rsi_14": 30}) is True
        assert f({"52w_pct": 20, "rsi_14": 30}) is False
        assert f({"52w_pct": 10, "rsi_14": 50}) is False

    def test_golden_cross_filter(self):
        f = PRESETS["golden_cross"]["filter"]
        assert f({"ema_trend": "UP", "long_trend": "BULL", "above_ma200": True}) is True
        assert f({"ema_trend": "DOWN", "long_trend": "BULL", "above_ma200": True}) is False

    def test_volume_surge_filter(self):
        f = PRESETS["volume_surge"]["filter"]
        assert f({"vol_spike": 4.0}) is True
        assert f({"vol_spike": 2.5}) is False

    def test_strong_uptrend_filter(self):
        f = PRESETS["strong_uptrend"]["filter"]
        assert f({"chg_20d_pct": 8, "macd_cross": "BUY", "above_ma200": True}) is True
        assert f({"chg_20d_pct": 3, "macd_cross": "BUY", "above_ma200": True}) is False
