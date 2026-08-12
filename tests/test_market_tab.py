"""Smoke tests for dashboard.market_tab (+ panel brief đã tách ra 12/08)."""

from __future__ import annotations

import inspect


def test_module_imports_without_streamlit():
    import importlib
    mod = importlib.import_module("dashboard.market_tab")
    assert hasattr(mod, "render_market_tab")
    assert callable(mod.render_market_tab)


import pytest

# Panel tách ra từ `market_tab` (12/08) — mỗi file một panel, tất cả phải giữ
# ĐÚNG tính chất của module gốc. Thêm panel mới → thêm vào đây; lưới chỉ soi
# thứ ĐƯỢC KHAI BÁO.
_PANELS = {
    "market_brief_panel": "render_brief_panel",
    "brief_agent_settings": "render_agent_settings",
    "brief_run_panel": "render_brief_runner",
    "brief_accuracy_panel": "render_accuracy_widget",
    "brief_history_panel": "render_brief_history",
    "brief_strategy_panel": "render_strategy_panel",
}


@pytest.mark.parametrize("mod,fname", sorted(_PANELS.items()))
def test_panel_modules_import_without_streamlit_runtime(mod, fname):
    import importlib
    assert callable(getattr(importlib.import_module(f"dashboard.{mod}"), fname))


@pytest.mark.parametrize("mod", sorted(_PANELS))
def test_panels_lazy_import_streamlit_inside_the_function(mod):
    """Import Streamlit ở CẤP MODULE là kéo cả runtime vào lúc pytest thu
    thập — đúng thứ khiến cả tab trước đây không test được."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "dashboard" / f"{mod}.py").read_text(encoding="utf-8")
    top_level = {a.name for n in ast.parse(src).body
                 if isinstance(n, ast.Import) for a in n.names}
    top_level |= {n.module for n in ast.parse(src).body
                  if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(str(m).startswith("streamlit") for m in top_level)


@pytest.mark.parametrize("mod,fname", sorted(_PANELS.items()))
def test_panels_are_nullary(mod, fname):
    """Panel lấy state qua `st.session_state`, không nhận tham số — đổi chữ ký
    là phải sửa cả chỗ gọi trong `market_brief_panel`."""
    import importlib
    fn = getattr(importlib.import_module(f"dashboard.{mod}"), fname)
    assert not [p for p in inspect.signature(fn).parameters.values()
                if p.default is inspect.Parameter.empty]


def test_orchestrator_calls_every_panel():
    """Panel viết ra mà quên gọi = code chết trông y như code sống."""
    import inspect as _i

    from dashboard.market_brief_panel import render_brief_panel
    src = _i.getsource(render_brief_panel)
    missing = [f for m, f in _PANELS.items()
               if m != "market_brief_panel" and f"{f}()" not in src]
    assert not missing, f"Panel không được gọi: {missing}"


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
