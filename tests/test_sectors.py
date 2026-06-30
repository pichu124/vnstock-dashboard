"""Tests for vnstock_sectors — the canonical custom sector groupings shared by
the dashboard money-flow tab and the brief/screener pipeline."""
from __future__ import annotations

import pytest


def test_vin_family_is_exactly_the_four_vingroup_tickers():
    import vnstock_sectors as vs
    assert vs.VIN_FAMILY == {"VIC", "VHM", "VRE", "VPL"}
    assert vs.VIN_SECTOR == "Họ VIN"


def test_vin_sector_for_maps_only_the_family():
    import vnstock_sectors as vs
    for tk in ("VIC", "VHM", "VRE", "VPL"):
        assert vs.vin_sector_for(tk) == "Họ VIN"
    # other tickers — including unrelated 'V' codes — fall through to None
    for tk in ("FPT", "HPG", "VND", "VCB", "VNM", "VGC"):
        assert vs.vin_sector_for(tk) is None


def test_runner_grouping_pattern_collapses_vin_into_one_sector():
    """Mirror compute_market_overview's relabel: grouping by a relabeled industry
    column collapses VIC/VHM/VRE/VPL into 'Họ VIN' (out of their old industries)
    while non-VIN rows keep their industry."""
    pd = pytest.importorskip("pandas")
    import vnstock_sectors as vs
    merged = pd.DataFrame({
        "ticker":   ["VIC", "VHM", "VRE", "VPL", "HPG", "VCB"],
        "industry": ["Bất động sản", "Bất động sản", "Bán lẻ",
                     "Du lịch & Giải trí", "Thép", "Ngân hàng"],
    })
    merged["_sector_group"] = merged["industry"]
    merged.loc[merged["ticker"].isin(vs.VIN_FAMILY), "_sector_group"] = vs.VIN_SECTOR
    by = merged.groupby("_sector_group")["ticker"].apply(set).to_dict()
    assert by["Họ VIN"] == {"VIC", "VHM", "VRE", "VPL"}
    assert "Bất động sản" not in by   # its only members were VIN → folded away
    assert by["Thép"] == {"HPG"}       # non-VIN rows untouched
    assert by["Ngân hàng"] == {"VCB"}
