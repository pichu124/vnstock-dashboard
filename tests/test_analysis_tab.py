"""Smoke tests for dashboard.analysis_tab."""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    import importlib
    mod = importlib.import_module("dashboard.analysis_tab")
    assert hasattr(mod, "render_analysis_tab")
    assert callable(mod.render_analysis_tab)


def test_render_takes_no_positional_args():
    """Nullary entry point — all state comes via lazy import."""
    from dashboard.analysis_tab import render_analysis_tab
    sig = inspect.signature(render_analysis_tab)
    required = [
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD)
    ]
    assert required == []
