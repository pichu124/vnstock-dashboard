"""Smoke tests cho 2 sub-tab P5 (📚 Báo cáo + 🧭 Phân bổ) — import contract
(mirror test_money_flow_tab): streamlit lazy-import trong render nên module
phải import được không cần streamlit; entry point nullary.
"""
from __future__ import annotations

import importlib
import inspect

import pytest


@pytest.mark.parametrize("mod_name,fn_name", [
    ("dashboard.reports_tab", "render_reports_subtab"),
    ("dashboard.allocation_tab", "render_allocation_subtab"),
    ("dashboard.rates_report_tab", "render_rates_report_subtab"),
])
def test_module_imports_without_streamlit_and_nullary(mod_name, fn_name):
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    assert callable(fn)
    required = [
        name for name, p in inspect.signature(fn).parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD)
    ]
    assert required == []


def test_news_tab_wires_subtabs():
    src = (__import__("pathlib").Path(__file__).resolve().parent.parent
           / "dashboard" / "news_tab.py").read_text(encoding="utf-8")
    assert "📚 Báo cáo" in src and "🧭 Phân bổ" in src and "📄 Báo cáo tuần" in src
    assert "render_reports_subtab" in src and "render_allocation_subtab" in src
    assert "render_rates_report_subtab" in src
