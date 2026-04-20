"""Tests for vnstock_reconciler cross-reference logic."""

from __future__ import annotations

import pandas as pd

from vnstock_reconciler import _classify, _normalise_units, _pct_diff


def test_pct_diff_symmetric():
    assert _pct_diff(100.0, 101.0) == 1.0
    assert _pct_diff(100.0, 99.0) == 1.0


def test_pct_diff_nan_and_zero():
    assert _pct_diff(None, 10) is None
    assert _pct_diff(10, None) is None
    assert _pct_diff(0.0, 5.0) is None


def test_classify_ok_within_tolerance():
    sev, _ = _classify(close_diff=0.1, volume_diff=1.0)
    assert sev == "ok"


def test_classify_warn_on_volume():
    sev, reason = _classify(close_diff=0.1, volume_diff=10.0)
    assert sev == "warn"
    assert "volume drift" in reason


def test_classify_fail_on_close():
    sev, reason = _classify(close_diff=5.0, volume_diff=None)
    assert sev == "fail"
    assert "close drift" in reason


def test_classify_fail_dominates_warn():
    sev, _ = _classify(close_diff=5.0, volume_diff=10.0)
    assert sev == "fail"


# ── unit normalisation (per-row, close > 500 → /1000) ─────────────────────

def test_normalise_rescales_rolled_row_by_row():
    """Rolled stores raw VND (7120). Every row > 500 is divided by 1000."""
    api = pd.DataFrame({
        "ticker": ["AAA", "FPT", "VCB"],
        "close": [7.12, 120.0, 77.7],
    })
    rolled = pd.DataFrame({
        "ticker": ["AAA", "FPT", "VCB"],
        "close": [7120.0, 120000.0, 77700.0],
    })
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(rolled_out["close"]) == [7.12, 120.0, 77.7]
    # API values were all below threshold → untouched
    assert list(api_out["close"]) == [7.12, 120.0, 77.7]


def test_normalise_handles_mixed_units_in_same_frame():
    """Warehouse has mixed units on different tickers — each row treated
    on its own merits."""
    api = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "close": [7.12, 5600.0, 14.5],   # second row is raw VND
    })
    rolled = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "close": [7120.0, 5600.0, 14500.0],   # first + third raw VND
    })
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(api_out["close"]) == [7.12, 5.6, 14.5]
    assert list(rolled_out["close"]) == [7.12, 5.6, 14.5]


def test_normalise_noop_when_all_rows_under_threshold():
    api = pd.DataFrame({"ticker": ["AAA"], "close": [7.12]})
    rolled = pd.DataFrame({"ticker": ["AAA"], "close": [7.15]})
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is False
    assert list(rolled_out["close"]) == [7.15]


def test_normalise_handles_empty_frames():
    empty = pd.DataFrame(columns=["ticker", "close"])
    one = pd.DataFrame({"ticker": ["X"], "close": [7.12]})
    api_out, rolled_out, rescaled = _normalise_units(empty, one)
    assert rescaled is False
    api_out, rolled_out, rescaled = _normalise_units(one, empty)
    assert rescaled is False


def test_normalise_handles_only_api_in_raw_vnd():
    """If only one side has raw VND, only that side gets rescaled."""
    api = pd.DataFrame({"ticker": ["X"], "close": [7120.0]})
    rolled = pd.DataFrame({"ticker": ["X"], "close": [7.12]})
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(api_out["close"]) == [7.12]
    assert list(rolled_out["close"]) == [7.12]
