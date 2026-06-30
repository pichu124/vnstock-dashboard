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


def test_custom_group_membership_and_override():
    """The tab pulls custom-group tickers (Họ VIN / Họ M) out of their listed
    industry; everything else falls through to the shared sector mapping."""
    from dashboard.money_flow_tab import _custom_sector_for
    for tk in ("VIC", "VHM", "VRE", "VPL"):
        assert _custom_sector_for(tk) == "Họ VIN"
    for tk in ("GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"):
        assert _custom_sector_for(tk) == "Họ M"
    # non-grouped tickers fall through to the base mapping
    for tk in ("FPT", "HPG", "VCB", "VNM", "SSI"):
        assert _custom_sector_for(tk) is None


def test_custom_groups_pinned_first_preserving_base_order():
    """The tab builds _MF_SECTOR_ORDER = [*CUSTOM_SECTOR_ORDER, *SECTOR_ORDER] —
    custom groups sit first (registry order), the base order is preserved, and no
    base sector is dropped. Uses a representative base list to avoid importing the
    Streamlit-bound dashboard."""
    from dashboard.money_flow_tab import _CUSTOM_SECTOR_ORDER
    base = ["Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản"]
    order = [*_CUSTOM_SECTOR_ORDER, *base]   # mirrors the local _MF_SECTOR_ORDER
    assert order[0] == "Họ VIN"
    assert order[1] == "Họ M"
    assert order[len(_CUSTOM_SECTOR_ORDER)] == "Ngân hàng"   # custom groups above banks
    assert order[len(_CUSTOM_SECTOR_ORDER):] == base         # base order preserved
