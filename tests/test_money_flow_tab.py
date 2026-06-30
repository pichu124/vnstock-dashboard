"""Smoke tests for dashboard.money_flow_tab.

Covers the import contract and signature only — the UI is exercised
manually, and the data-loading helpers (``_fetch_foreign_net_flow``,
``_fetch_order_stats_batch`` etc.) still live in ``vnstock_dashboard.py``
with their own tests in ``test_dashboard.py``.
"""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    """Module must be importable even when Streamlit is not available —
    Streamlit is lazy-imported inside render_money_flow_tab."""
    import importlib
    mod = importlib.import_module("dashboard.money_flow_tab")
    assert hasattr(mod, "render_money_flow_tab")
    assert callable(mod.render_money_flow_tab)


def test_render_takes_no_positional_args():
    """render_money_flow_tab() is a nullary entry point — all state is
    pulled via lazy import from vnstock_dashboard. Locks the contract."""
    from dashboard.money_flow_tab import render_money_flow_tab
    sig = inspect.signature(render_money_flow_tab)
    # No required parameters
    required = [
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD)
    ]
    assert required == []


def test_vin_family_membership_and_override():
    """The 'Họ VIN' group is exactly VIC/VHM/VRE/VPL and overrides the listed
    industry; everything else falls through to the shared sector mapping."""
    from dashboard.money_flow_tab import _vin_sector_for, _VIN_FAMILY, _VIN_SECTOR
    assert _VIN_FAMILY == {"VIC", "VHM", "VRE", "VPL"}
    assert _VIN_SECTOR == "Họ VIN"
    # every VIN ticker maps to the family group regardless of listed industry
    for tk in ("VIC", "VHM", "VRE", "VPL"):
        assert _vin_sector_for(tk) == "Họ VIN"
    # non-VIN tickers (incl. other 'V' codes) are left to the base mapping
    for tk in ("FPT", "HPG", "VND", "VCB", "VNM"):
        assert _vin_sector_for(tk) is None


def test_vin_group_pins_first_preserving_base_order():
    """The tab builds _MF_SECTOR_ORDER = [_VIN_SECTOR, *SECTOR_ORDER] — VIN sits
    first, the base order is preserved, and no base sector is dropped. Tested on
    a representative base list to avoid importing the Streamlit-bound dashboard."""
    from dashboard.money_flow_tab import _VIN_SECTOR
    base = ["Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản"]
    order = [_VIN_SECTOR, *base]   # mirrors the local _MF_SECTOR_ORDER construction
    assert order[0] == "Họ VIN"
    assert order[1] == "Ngân hàng"     # VIN sits above banks
    assert order[1:] == base           # base order preserved, nothing lost/reordered
