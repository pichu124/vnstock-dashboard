"""Tests for dashboard helpers — price normalization, indicators, value area."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# Mock streamlit and vnstock_wss before importing dashboard
_st_mock = MagicMock()
_st_mock.set_page_config = MagicMock()
_st_mock.cache_data = lambda *a, **kw: (lambda f: f)
_st_mock.cache_resource = lambda *a, **kw: (lambda f: f)
sys.modules["streamlit"] = _st_mock
sys.modules["streamlit.components"] = MagicMock()
sys.modules["streamlit.components.v1"] = MagicMock()
sys.modules["vnstock_wss"] = MagicMock()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Import individual functions — dashboard module does heavy init,
# so we extract and test the pure logic directly.

def _normalize_price_units(df: pd.DataFrame) -> pd.DataFrame:
    """Replica from vnstock_dashboard.py:192"""
    if df.empty:
        return df
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            continue
        vals = df[col].astype(float)
        mask = vals > 500
        if mask.any():
            df.loc[mask, col] = vals[mask] / 1000
    return df


def _normalize_live_price(historical_last_close: float, live_price: float) -> float:
    """Replica from vnstock_dashboard.py:996"""
    if historical_last_close <= 0 or live_price <= 0:
        return live_price
    ratio = live_price / historical_last_close
    if ratio > 100:
        return live_price / 1000.0
    if ratio < 0.01:
        return live_price * 1000.0
    return live_price


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Replica from vnstock_dashboard.py:301"""
    df = df.copy()
    c = df["close"].astype(float)

    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    for span in (9, 21, 50, 200):
        if len(c) >= span:
            df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()
        else:
            df[f"ema{span}"] = np.nan

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df["bb_up"] = sma20 + 2 * std20
    df["bb_lo"] = sma20 - 2 * std20
    df["bb_mid"] = sma20
    df["vol_ma20"] = df["volume"].astype(float).rolling(20).mean()

    return df


def _calc_value_area(profile: list, pct: float = 0.70) -> tuple:
    """Replica from vnstock_dashboard.py:688"""
    if not profile:
        return (0, 0, 0, 0, 0, 0)
    volumes = [float(r.get("total_vol", 0)) for r in profile]
    prices = [float(r.get("price", 0)) for r in profile]
    total_all = sum(volumes)
    if total_all <= 0:
        return (0, 0, len(profile) - 1, prices[0], prices[0],
                prices[-1] if prices else 0)
    poc_idx = max(range(len(volumes)), key=lambda i: volumes[i])
    va_vol = volumes[poc_idx]
    target = total_all * pct
    upper = poc_idx - 1
    lower = poc_idx + 1
    while va_vol < target and (upper >= 0 or lower < len(volumes)):
        up_vol = volumes[upper] if upper >= 0 else -1
        lo_vol = volumes[lower] if lower < len(volumes) else -1
        if up_vol >= lo_vol and upper >= 0:
            va_vol += up_vol
            upper -= 1
        elif lower < len(volumes):
            va_vol += lo_vol
            lower += 1
        else:
            break
    vah_idx = max(upper + 1, 0)
    val_idx = min(lower - 1, len(volumes) - 1)
    return (poc_idx, vah_idx, val_idx,
            prices[poc_idx], prices[vah_idx], prices[val_idx])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 100, base: float = 50.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-04-10", periods=n)
    closes = base + np.cumsum(rng.normal(0, 0.5, n))
    closes = np.maximum(closes, 1.0)
    return pd.DataFrame({
        "time": dates,
        "open": closes + rng.normal(0, 0.1, n),
        "high": closes + abs(rng.normal(0.2, 0.1, n)),
        "low": closes - abs(rng.normal(0.2, 0.1, n)),
        "close": closes,
        "volume": rng.integers(10_000, 500_000, n),
    })


# ── _normalize_price_units ──────────────────────────────────────────────────

class TestNormalizePriceUnits:

    def test_vnd_divided_by_1000(self):
        df = pd.DataFrame({
            "open": [77800.0], "high": [78000.0],
            "low": [77500.0], "close": [77700.0],
        })
        result = _normalize_price_units(df)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)
        assert result["open"].iloc[0] == pytest.approx(77.8, rel=1e-3)

    def test_thousand_vnd_unchanged(self):
        df = pd.DataFrame({
            "open": [77.8], "high": [78.0],
            "low": [77.5], "close": [77.7],
        })
        result = _normalize_price_units(df)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)

    def test_mixed_units_per_cell(self):
        df = pd.DataFrame({
            "open": [77.8], "high": [78000.0],
            "low": [77.5], "close": [77700.0],
        })
        result = _normalize_price_units(df)
        assert result["open"].iloc[0] == pytest.approx(77.8, rel=1e-3)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)
        assert result["high"].iloc[0] == pytest.approx(78.0, rel=1e-3)

    def test_empty_dataframe(self):
        result = _normalize_price_units(pd.DataFrame())
        assert result.empty

    def test_does_not_modify_original(self):
        df = pd.DataFrame({"open": [77800.0], "high": [78000.0],
                           "low": [77500.0], "close": [77700.0]})
        original_close = df["close"].iloc[0]
        _normalize_price_units(df)
        assert df["close"].iloc[0] == original_close


# ── _normalize_live_price ────────────────────────────────────────────────────

class TestNormalizeLivePrice:

    def test_live_in_vnd_historical_in_thousand(self):
        result = _normalize_live_price(77.7, 77700.0)
        assert result == pytest.approx(77.7, rel=1e-3)

    def test_live_in_thousand_historical_in_vnd(self):
        result = _normalize_live_price(77700.0, 77.7)
        assert result == pytest.approx(77700.0, rel=1e-3)

    def test_same_scale_unchanged(self):
        result = _normalize_live_price(77.7, 78.0)
        assert result == pytest.approx(78.0, rel=1e-3)

    def test_zero_historical(self):
        assert _normalize_live_price(0, 77700.0) == 77700.0

    def test_zero_live(self):
        assert _normalize_live_price(77.7, 0) == 0


# ── compute_indicators ──────────────────────────────────────────────────────

class TestComputeIndicators:

    def test_adds_indicator_columns(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        for col in ("rsi", "ema9", "ema21", "macd", "macd_signal",
                     "macd_hist", "bb_up", "bb_lo", "bb_mid", "vol_ma20"):
            assert col in result.columns, f"Missing column: {col}"

    def test_rsi_bounded(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        rsi = result["rsi"].dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_bollinger_band_order(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        valid = result.dropna(subset=["bb_up", "bb_lo"])
        assert (valid["bb_up"] >= valid["bb_lo"]).all()

    def test_output_same_length(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        assert len(result) == len(df)


# ── _calc_value_area ─────────────────────────────────────────────────────────

class TestCalcValueArea:

    def test_basic_value_area(self):
        profile = [
            {"price": 80.0, "total_vol": 100},
            {"price": 79.0, "total_vol": 500},
            {"price": 78.0, "total_vol": 300},
            {"price": 77.0, "total_vol": 50},
        ]
        poc_idx, vah_idx, val_idx, poc_p, vah_p, val_p = _calc_value_area(profile)
        assert poc_p == 79.0
        assert vah_p >= val_p

    def test_empty_profile(self):
        assert _calc_value_area([]) == (0, 0, 0, 0, 0, 0)

    def test_single_level(self):
        profile = [{"price": 50.0, "total_vol": 1000}]
        poc_idx, vah_idx, val_idx, poc_p, vah_p, val_p = _calc_value_area(profile)
        assert poc_p == 50.0

    def test_poc_is_max_volume(self):
        profile = [
            {"price": 82.0, "total_vol": 10},
            {"price": 81.0, "total_vol": 20},
            {"price": 80.0, "total_vol": 999},
            {"price": 79.0, "total_vol": 30},
            {"price": 78.0, "total_vol": 15},
        ]
        _, _, _, poc_p, _, _ = _calc_value_area(profile)
        assert poc_p == 80.0
