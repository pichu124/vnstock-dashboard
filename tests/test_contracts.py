"""Tests for vnstock_contracts — the OHLCV data-contract layer."""

from __future__ import annotations

import pandas as pd
import pytest

from vnstock_contracts import (
    ContractViolation,
    validate_ohlcv,
)


def _mkbar(time="2026-04-17", open_=10.0, high=11.0, low=9.8, close=10.5,
           volume=1_000_000, ticker="VCB", year=2026):
    return {
        "time": time, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "ticker": ticker, "year": year,
    }


# ── positive cases ──────────────────────────────────────────────────────────

def test_accept_clean_ohlcv():
    df = pd.DataFrame([_mkbar(), _mkbar(time="2026-04-18", close=10.7)])
    clean, report = validate_ohlcv(df)
    assert report["rows_in"] == 2
    assert report["rows_out"] == 2
    assert report["dropped"] == 0


def test_accept_partial_bar_with_nan_ohlc():
    bar = _mkbar()
    bar["open"] = None
    df = pd.DataFrame([bar])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 1   # NaN open allowed; cross-field rules exempt


# ── negative cases — must drop or raise ─────────────────────────────────────

def test_reject_zero_close():
    df = pd.DataFrame([_mkbar(), _mkbar(time="2026-04-18", close=0.0)])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 1
    assert report["dropped"] == 1


def test_reject_negative_close():
    df = pd.DataFrame([_mkbar(close=-5.0)])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 0


def test_reject_negative_volume():
    df = pd.DataFrame([_mkbar(volume=-100)])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 0


def test_reject_high_below_low():
    df = pd.DataFrame([_mkbar(high=5.0, low=10.0)])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 0


def test_reject_bad_ticker_format():
    df = pd.DataFrame([_mkbar(ticker="lowercase")])
    clean, report = validate_ohlcv(df, drop_invalid=True)
    assert report["rows_out"] == 0


def test_strict_mode_raises():
    df = pd.DataFrame([_mkbar(close=-1.0)])
    with pytest.raises(ContractViolation):
        validate_ohlcv(df, strict=True)


def test_return_dropped_carries_rows_and_reasons():
    df = pd.DataFrame([_mkbar(), _mkbar(time="2026-04-18", close=-1.0)])
    clean, report = validate_ohlcv(df, drop_invalid=True, return_dropped=True)
    assert len(report["dropped_rows"]) == 1
    assert report["dropped_reasons"] == ["close out of bounds"]
    assert report["failures"]


def test_drop_invalid_false_returns_unchanged():
    df = pd.DataFrame([_mkbar(close=-1.0)])
    clean, report = validate_ohlcv(df, drop_invalid=False)
    assert len(clean) == 1
    assert report["failures"]


# ── empty / edge cases ──────────────────────────────────────────────────────

def test_empty_df_passes_through():
    df = pd.DataFrame()
    clean, report = validate_ohlcv(df)
    assert clean.empty
    assert report["rows_in"] == 0
