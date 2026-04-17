"""Tests for vnstock_reconciler cross-reference logic."""

from __future__ import annotations

import pandas as pd

from vnstock_reconciler import _classify, _pct_diff


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
