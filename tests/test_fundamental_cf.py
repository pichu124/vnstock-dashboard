"""Tests for vnstock_fundamental_updater._annual_operating_cf.

Regression: VCI returns QUARTERLY cash-flow rows even for period='year', so the
single latest row is one quarter (e.g. FPT Q1 working-capital outflow → -2,847.8
tỷ) instead of the full-year / TTM figure.
"""

from __future__ import annotations

import pandas as pd
import pytest

from vnstock_fundamental_updater import _annual_operating_cf

_OCF = "Net cash inflows/(outflows) from operating activities"


def test_quarterly_sums_to_ttm_not_single_negative_quarter():
    # Latest quarter is negative (FPT-like), but the trailing 4 quarters are
    # strongly positive — must return the TTM sum, not the single quarter.
    df = pd.DataFrame({
        "report_period": ["2026-Q1", "2025-Q4", "2025-Q3", "2025-Q2", "2025-Q1"],
        _OCF: [-2847.8e9, 4000e9, 1500e9, 1000e9, -500e9],
    })
    val = _annual_operating_cf(df)
    # head(4) after sorting desc: 2026Q1 + 2025Q4 + Q3 + Q2
    assert val == pytest.approx((-2847.8 + 4000 + 1500 + 1000) * 1e9)
    assert val > 0


def test_annual_uses_latest_complete_year():
    df = pd.DataFrame({
        "report_period": ["2025", "2024", "2023"],
        _OCF: [5000e9, 4000e9, 3000e9],
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx(5000e9)   # latest year, not a sum


def test_quarterly_detected_by_rowcount_when_period_has_no_year():
    # report_period is an integer period-id (no parseable year) — FPT's real
    # case. >12 rows ⇒ sub-annual ⇒ TTM = sum of the 4 most recent rows.
    n = 41
    df = pd.DataFrame({
        "report_period": list(range(n, 0, -1)),  # 41, 40, … 1 (already desc)
        _OCF: [-2847.8e9, 4000e9, 1500e9, 1000e9] + [100e9] * (n - 4),
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx((-2847.8 + 4000 + 1500 + 1000) * 1e9)
    assert val > 0


def test_empty_returns_none():
    assert _annual_operating_cf(pd.DataFrame()) is None
