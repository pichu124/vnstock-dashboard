"""Tests for the adjusted-price layer."""

from __future__ import annotations

import pandas as pd
import pytest

from vnstock_adjust import apply_adjustments, _per_event_factor


def _mk_ohlcv(dates, closes):
    df = pd.DataFrame({
        "time": pd.to_datetime(dates),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low":  [c * 0.99 for c in closes],
        "close": closes,
    })
    return df


def test_no_events_adjusted_equals_raw():
    df = _mk_ohlcv(["2026-04-15", "2026-04-16", "2026-04-17"], [100.0, 101.0, 102.0])
    out = apply_adjustments(df, events=None)
    assert "close_adj" in out.columns
    assert (out["close_adj"] == out["close"]).all()


def test_cash_dividend_back_adjusts_history():
    # Stock trades at 100 on 04-15 and 04-16. On 04-17 it pays a 5.0 cash div.
    # Post-ex close is 95. Back-adjusted 04-15/04-16 closes become 95.
    df = _mk_ohlcv(
        ["2026-04-15", "2026-04-16", "2026-04-17"],
        [100.0, 100.0, 95.0],
    )
    events = pd.DataFrame([{
        "ticker": "X", "ex_date": "2026-04-17", "type": "cash",
        "cash_amount": 5.0, "ratio": None, "raw": "",
    }])
    out = apply_adjustments(df, events)

    # 04-17 (post-ex) stays at 95
    assert out.loc[out["time"] == pd.Timestamp("2026-04-17"), "close_adj"].iloc[0] == pytest.approx(95.0, abs=1e-3)
    # 04-15 / 04-16 shifted down to 95 (factor = 95/100 = 0.95)
    for d in ["2026-04-15", "2026-04-16"]:
        val = out.loc[out["time"] == pd.Timestamp(d), "close_adj"].iloc[0]
        assert val == pytest.approx(95.0, abs=1e-2)


def test_split_factor_halves_history():
    # 2-for-1 split: all pre-ex prices should halve.
    df = _mk_ohlcv(
        ["2026-04-15", "2026-04-16", "2026-04-17"],
        [200.0, 200.0, 100.0],
    )
    events = pd.DataFrame([{
        "ticker": "X", "ex_date": "2026-04-17", "type": "split",
        "cash_amount": None, "ratio": 2.0, "raw": "",
    }])
    out = apply_adjustments(df, events)
    assert out.loc[out["time"] == pd.Timestamp("2026-04-15"), "close_adj"].iloc[0] == pytest.approx(100.0)
    assert out.loc[out["time"] == pd.Timestamp("2026-04-17"), "close_adj"].iloc[0] == pytest.approx(100.0)


def test_per_event_factor_cash_guards_zero_price():
    assert _per_event_factor({"type": "cash", "cash_amount": 5.0}, 0.0) == 1.0
    assert _per_event_factor({"type": "cash", "cash_amount": 0.0}, 100.0) == 1.0


def test_per_event_factor_split_guards_bad_ratio():
    assert _per_event_factor({"type": "split", "ratio": 0}, 100.0) == 1.0
    assert _per_event_factor({"type": "split", "ratio": -1}, 100.0) == 1.0


def test_events_outside_range_are_ignored():
    df = _mk_ohlcv(["2026-04-15", "2026-04-16"], [100.0, 101.0])
    events = pd.DataFrame([{
        "ticker": "X", "ex_date": "2020-01-01", "type": "cash",
        "cash_amount": 10.0, "ratio": None, "raw": "",
    }])
    out = apply_adjustments(df, events)
    # Out-of-range event: adj == raw
    assert (out["close_adj"] == out["close"]).all()
