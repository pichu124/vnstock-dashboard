"""Smoke tests for dashboard.market_tab."""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    import importlib
    mod = importlib.import_module("dashboard.market_tab")
    assert hasattr(mod, "render_market_tab")
    assert callable(mod.render_market_tab)


def test_render_takes_no_positional_args():
    """Nullary entry point — dashboard pulls all state via lazy import."""
    from dashboard.market_tab import render_market_tab
    sig = inspect.signature(render_market_tab)
    required = [
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD)
    ]
    assert required == []
