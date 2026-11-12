"""scripts/gen6_check.py — hàm thuần so giá kho/nguồn (phần gọi mạng chạy trên máy thật)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.gen6_check import ratio_summary


def _df(days, closes):
    return pd.DataFrame({"time": [date(2026, 11, d) for d in days], "close": closes})


def test_same_unit_same_basis_ratio_is_one():
    out = ratio_summary(_df([3, 4, 5], [100.0, 101.0, 102.0]), _df([4, 5, 6], [101.0, 102.0, 103.0]))
    assert out["n"] == 2 and out["ratio_median"] == 1.0 and out["max_dev_pct"] == 0.0
    assert (out["wh_last"], out["src_last"]) == ("2026-11-05", "2026-11-06")


def test_unit_mismatch_shows_as_thousand():
    out = ratio_summary(_df([3, 4], [100.0, 101.0]), _df([3, 4], [0.1, 0.101]))
    assert out["ratio_median"] == 1000.0


def test_no_overlap_reports_zero():
    assert ratio_summary(_df([3], [1.0]), _df([], []).astype({"close": float}))["n"] == 0
