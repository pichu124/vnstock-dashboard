"""Smoke tests for dashboard.screener_tab.

The UI and dashboard-level helpers (df_from_preset, render_table etc.)
are covered by their own tests in test_screener.py and test_dashboard.py.
This file only validates the tab module's import contract and signature.
"""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    """Module must be importable with just stdlib — Streamlit + dashboard
    helpers are lazy-imported inside render_screener_tab."""
    import importlib
    mod = importlib.import_module("dashboard.screener_tab")
    assert hasattr(mod, "render_screener_tab")
    assert callable(mod.render_screener_tab)


def test_render_signature_keyword_only():
    """All state parameters are keyword-only so callers can't pass
    positionally by accident — the dispatch block in vnstock_dashboard.py
    relies on this contract."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    for name, param in sig.parameters.items():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, \
            f"parameter {name!r} must be keyword-only"


def test_render_accepts_expected_params():
    """The wrapper in vnstock_dashboard.py passes exactly these names —
    this test locks the contract so a rename breaks loudly here."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    expected = {
        "presets_data", "industry_summary", "gen_time",
        "total_tickers", "classified", "total_hits", "top_preset",
    }
    assert set(sig.parameters.keys()) == expected
