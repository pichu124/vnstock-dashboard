"""Tests for vnstock_contracts — the Pandera data-contract layer."""

from __future__ import annotations

import pandas as pd
import pytest

from vnstock_contracts import (
    ContractViolation,
    validate_ohlcv,
    validate_fundamental,
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


def test_accept_clean_fundamental():
    df = pd.DataFrame([{
        "ticker": "VCB", "as_of": "2026-04-17",
        "pe": 12.3, "pb": 1.5, "roe": 18.4, "roa": 2.1, "eps": 4500.0,
    }])
    clean, report = validate_fundamental(df)
    assert report["rows_out"] == 1


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
    schema_present = validate_ohlcv(pd.DataFrame([_mkbar()]))[1]["pandera_available"]
    if not schema_present:
        pytest.skip("pandera not installed")
    with pytest.raises(ContractViolation):
        validate_ohlcv(df, strict=True)


# ── empty / edge cases ──────────────────────────────────────────────────────

def test_empty_df_passes_through():
    df = pd.DataFrame()
    clean, report = validate_ohlcv(df)
    assert clean.empty
    assert report["rows_in"] == 0


def test_fundamental_allows_null_metrics():
    df = pd.DataFrame([{
        "ticker": "VCB", "as_of": "2026-04-17",
        "pe": None, "pb": None, "roe": None, "roa": None, "eps": None,
    }])
    clean, report = validate_fundamental(df)
    assert report["rows_out"] == 1
