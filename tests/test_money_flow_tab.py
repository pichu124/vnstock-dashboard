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
