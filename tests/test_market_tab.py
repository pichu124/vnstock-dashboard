"""Smoke tests for dashboard.market_tab (+ panel brief đã tách ra 12/08)."""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    import importlib
    mod = importlib.import_module("dashboard.market_tab")
    assert hasattr(mod, "render_market_tab")
    assert callable(mod.render_market_tab)


def test_brief_panel_module_imports_without_streamlit():
    """Panel tách ra phải giữ ĐÚNG tính chất của module gốc: import lười
    Streamlit trong thân hàm, nên pytest import được mà không cần runtime."""
    import importlib
    mod = importlib.import_module("dashboard.market_brief_panel")
    assert callable(mod.render_brief_panel)


def test_brief_panel_lazy_imports_streamlit_inside_the_function():
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "dashboard" / "market_brief_panel.py").read_text(encoding="utf-8")
    top_level = {a.name for n in ast.parse(src).body
                 if isinstance(n, ast.Import) for a in n.names}
    assert "streamlit" not in top_level


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
