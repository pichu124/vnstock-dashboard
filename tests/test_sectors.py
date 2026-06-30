"""Tests for vnstock_sectors — the canonical custom sector groupings shared by
the dashboard money-flow tab and the brief/screener pipeline."""
from __future__ import annotations

import pytest


def test_custom_groups_membership():
    import vnstock_sectors as vs
    assert vs.VIN_FAMILY == {"VIC", "VHM", "VRE", "VPL"}
    assert vs.VIN_SECTOR == "Họ VIN"
    assert vs.M_FAMILY == {"GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"}
    assert vs.M_SECTOR == "Họ M"


def test_custom_sector_for_maps_each_family_else_none():
    import vnstock_sectors as vs
    for tk in ("VIC", "VHM", "VRE", "VPL"):
        assert vs.custom_sector_for(tk) == "Họ VIN"
    for tk in ("GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"):
        assert vs.custom_sector_for(tk) == "Họ M"
    # unrelated tickers fall through to None
    for tk in ("FPT", "HPG", "VCB", "VNM", "SSI", "MWG"):
        assert vs.custom_sector_for(tk) is None


def test_custom_sector_order_is_registry_order():
    import vnstock_sectors as vs
    assert vs.CUSTOM_SECTOR_ORDER == ["Họ VIN", "Họ M"]
    # CUSTOM_FAMILY is the union of all grouped tickers
    assert vs.CUSTOM_FAMILY == vs.VIN_FAMILY | vs.M_FAMILY


def test_groups_are_disjoint():
    """No ticker may live in two custom groups (the builder enforces this)."""
    import vnstock_sectors as vs
    assert not (vs.VIN_FAMILY & vs.M_FAMILY)
    # a duplicated ticker across groups raises at build time
    with pytest.raises(ValueError):
        vs._build_lookup([("A", frozenset({"X"})), ("B", frozenset({"X"}))])


def test_vin_sector_for_backcompat_is_vin_only():
    import vnstock_sectors as vs
    assert vs.vin_sector_for("VIC") == "Họ VIN"
    # a Họ-M ticker is NOT matched by the VIN-only back-compat helper
    assert vs.vin_sector_for("GEX") is None
    assert vs.vin_sector_for("FPT") is None


def test_runner_grouping_pattern_collapses_families_into_sectors():
    """Mirror compute_market_overview's relabel (map → fillna): grouping by the
    relabeled column collapses each family into its own sector while non-grouped
    rows keep their industry."""
    pd = pytest.importorskip("pandas")
    import vnstock_sectors as vs
    merged = pd.DataFrame({
        "ticker":   ["VIC", "VHM", "GEX", "EIB", "VGC", "HPG", "VCB"],
        "industry": ["Bất động sản", "Bất động sản", "Thiết bị điện",
                     "Ngân hàng", "Vật liệu xây dựng", "Thép", "Ngân hàng"],
    })
    merged["_sector_group"] = (
        merged["ticker"].map(vs.custom_sector_for).fillna(merged["industry"]))
    by = merged.groupby("_sector_group")["ticker"].apply(set).to_dict()
    assert by["Họ VIN"] == {"VIC", "VHM"}
    assert by["Họ M"] == {"GEX", "EIB", "VGC"}
    assert by["Thép"] == {"HPG"}        # non-grouped untouched
    assert by["Ngân hàng"] == {"VCB"}   # EIB (a bank) moved to Họ M, VCB stays
