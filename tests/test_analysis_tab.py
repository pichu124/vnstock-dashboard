"""Smoke tests for dashboard.analysis_tab."""

from __future__ import annotations

import ast
import inspect
import types
from pathlib import Path


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


# ── Entry / TP / SL: giá kho là NGHÌN đồng ───────────────────────────────────

_TAB_SRC = (Path(__file__).resolve().parent.parent
            / "dashboard" / "analysis_tab.py").read_text(encoding="utf-8")
_TAB_TREE = ast.parse(_TAB_SRC)


def _render_levels(rec: dict) -> dict:
    """Chạy ĐÚNG khối metric Entry/TP/SL (trích từ source) với st giả."""
    block = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.If)
                 and "📍 Entry" in ast.unparse(n) and "_act in" in ast.unparse(n.test))
    shown: dict = {}

    class _Col:
        def metric(self, label, value, delta=None, **kw):
            shown[label] = (value, delta)

    st = types.SimpleNamespace(columns=lambda n: [_Col() for _ in range(n)])
    exec(compile(ast.Module([block], []), "analysis_tab.py", "exec"),
         {"st": st, "_act": "buy", "_r": rec})
    return shown


def test_entry_tp_sl_keep_two_decimals():
    """22.35 nghìn đồng in `{:,.0f}` thành "22" — mất cả bước giá."""
    shown = _render_levels({"entry": 22.35, "tp": 24.5, "sl": 21.05})
    assert shown["📍 Entry"] == ("22.35", None)
    assert shown["🎯 Take Profit"] == ("24.50", "+9.6%")
    assert shown["🛑 Cut Loss"][0] == "21.05"


def test_missing_levels_show_dash():
    shown = _render_levels({"entry": 22.35, "tp": None, "sl": None})
    assert shown["🎯 Take Profit"] == ("—", None)
    assert shown["🛑 Cut Loss"] == ("—", None)


# ── Nút timeframe: không xoá cache của CẢ process ───────────────────────────

def test_timeframe_switch_does_not_clear_every_cache():
    """`st.cache_data.clear()` xoá cache MỌI tab (screener, NN, BCTC…) chỉ để
    đổi khung nến — trong khi `load_intraday` đã khoá cache theo `interval`."""
    loop = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.For)
                and "tf_options" in ast.unparse(n.iter))
    cleared: list = []

    class _Rerun(Exception):
        pass

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _rerun():
        raise _Rerun

    st = types.SimpleNamespace(
        session_state={"tf": "1D"},
        button=lambda label, **kw: label == "5m",
        cache_data=types.SimpleNamespace(clear=lambda: cleared.append(1)),
        rerun=_rerun,
    )
    ns = {"st": st, "tf_options": ["1m", "5m", "1D"], "tf_cols": [_Ctx()] * 3}
    try:
        exec(compile(ast.Module([loop], []), "analysis_tab.py", "exec"), ns)
    except _Rerun:
        pass
    assert st.session_state["tf"] == "5m"
    assert cleared == []


def test_load_intraday_cache_key_includes_interval():
    """Điều kiện để bỏ clear(): cache key của load_intraday phải gồm interval."""
    src = (Path(__file__).resolve().parent.parent / "vnstock_dashboard.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "load_intraday")
    assert [a.arg for a in fn.args.args] == ["ticker", "interval"]
    assert "cache_data" in ast.unparse(fn.decorator_list[0])
