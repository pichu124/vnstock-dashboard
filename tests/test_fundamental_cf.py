"""Tests for vnstock_fundamental_updater._annual_operating_cf.

VCI's cash_flow spans many fiscal years; the naive "latest row" picked the
in-progress current year (FPT 2026 Q1 working-capital outflow → -2,847.8 tỷ),
and naive quarterly-summing added several years (→ +9,795 tỷ). The correct value
is the operating cash flow of the most recent COMPLETE fiscal year.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from vnstock_fundamental_updater import _annual_operating_cf

_OCF = "Net cash inflows/(outflows) from operating activities"
_CUR = date.today().year


def test_annual_uses_last_complete_year():
    df = pd.DataFrame({
        "report_period": [str(_CUR - 1), str(_CUR - 2), str(_CUR - 3)],
        _OCF: [5000e9, 4000e9, 3000e9],
    })
    assert _annual_operating_cf(df) == pytest.approx(5000e9)   # last year, not a sum


def test_excludes_in_progress_current_year():
    # Current year is a partial, negative row (FPT-like) → must be excluded;
    # return the last COMPLETE year, which is positive.
    df = pd.DataFrame({
        "report_period": [str(_CUR), str(_CUR - 1), str(_CUR - 2)],
        _OCF: [-2847.8e9, 5000e9, 4500e9],
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx(5000e9)
    assert val > 0


def test_quarterly_sums_last_complete_year_only():
    # Quarterly rows: 4 quarters of last complete year + 1 partial current-year
    # quarter. Sum only the complete year's 4 quarters; exclude the partial one.
    df = pd.DataFrame({
        "report_period": [f"{_CUR}-Q1",
                          f"{_CUR-1}-Q4", f"{_CUR-1}-Q3", f"{_CUR-1}-Q2", f"{_CUR-1}-Q1"],
        _OCF: [-2847.8e9, 4000e9, 1500e9, 1000e9, -500e9],
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx((4000 + 1500 + 1000 - 500) * 1e9)   # = 6000e9
    assert val > 0


def test_no_parseable_year_falls_back_to_latest_row():
    # Integer period-ids (no year) → can't determine the year → latest row.
    df = pd.DataFrame({
        "report_period": [3, 2, 1],
        _OCF: [7000e9, 4000e9, 3000e9],
    })
    assert _annual_operating_cf(df) == pytest.approx(7000e9)


def test_empty_returns_none():
    assert _annual_operating_cf(pd.DataFrame()) is None
