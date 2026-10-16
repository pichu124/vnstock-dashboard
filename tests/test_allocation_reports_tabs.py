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


# ─── reports_tab: thông báo sống qua st.rerun, spinner, kiểm ngày ─────────────

class _Rerun(Exception):
    """st.rerun thật ném ngoại lệ — mọi thứ vẽ trước nó biến mất."""


def _reports_env(monkeypatch, pressed=(), texts=None):
    import sys
    import types
    from unittest.mock import MagicMock
    from tests.test_tab_render_smoke import _fake_streamlit

    st = _fake_streamlit()
    st.columns = lambda spec=2, **k: [st] * (spec if isinstance(spec, int) else len(spec))
    st.button = lambda label, *a, key=None, disabled=False, **k: (
        key in pressed and not disabled)
    st.text_input = lambda label, *a, key=None, **k: (texts or {}).get(key, "")

    def _rerun():
        raise _Rerun()
    st.rerun = _rerun
    monkeypatch.setitem(sys.modules, "streamlit", st)

    rec = {"id": "r1", "source": "SSI", "report_date": "2026-10-01", "chars": 10}
    rp = types.SimpleNamespace(
        list_reports=lambda: [rec], in_analysis=lambda r: True,
        original_path=lambda rid: None, load_for_analysis=lambda: [rec],
        set_meta=MagicMock(return_value=rec), remove=MagicMock())
    dg = types.SimpleNamespace(refresh=MagicMock(return_value=["r1"]),
                               consensus=lambda: None)
    monkeypatch.setitem(sys.modules, "vnstock_reports", rp)
    monkeypatch.setitem(sys.modules, "vnstock_report_digest", dg)
    return st, rp, dg


def _render_reports():
    from dashboard.reports_tab import render_reports_subtab
    try:
        render_reports_subtab()
    except _Rerun:
        return True
    return False


def _said(mock):
    return [str(c.args[0]) for c in mock.call_args_list if c.args]


def test_reports_digest_result_survives_rerun_and_runs_under_spinner(monkeypatch):
    st, _, dg = _reports_env(monkeypatch, pressed={"_rp_digest"})
    spinning = []
    import contextlib

    @contextlib.contextmanager
    def _spinner(*a, **k):
        spinning.append(True)
        yield
        spinning.pop()
    st.spinner = _spinner
    dg.refresh.side_effect = lambda *a, **k: (["r1"] if spinning else
                                              pytest.fail("dg.refresh chạy ngoài spinner"))

    assert _render_reports()                 # bấm → digest → rerun
    st.success.reset_mock()
    st.button = lambda *a, **k: False        # lượt sau: không bấm gì
    _render_reports()

    assert any("Đã digest 1 báo cáo" in s for s in _said(st.success)), _said(st.success)


def test_reports_save_meta_result_survives_rerun(monkeypatch):
    st, rp, _ = _reports_env(monkeypatch, pressed={"_rp_save_meta"},
                             texts={"_rp_fix_date": "2026-10-01"})
    assert _render_reports()
    rp.set_meta.assert_called_once()
    st.success.reset_mock()
    st.button = lambda *a, **k: False
    _render_reports()

    assert any("r1" in s for s in _said(st.success)), _said(st.success)


@pytest.mark.parametrize("key,pressed", [
    ("_rp_date", set()),
    ("_rp_fix_date", {"_rp_save_meta"}),
])
def test_reports_bad_date_is_reported_on_ui(monkeypatch, key, pressed):
    """"16/10/2026" từng chỉ được print ra console rồi lặng lẽ bỏ qua."""
    st, rp, _ = _reports_env(monkeypatch, pressed=pressed,
                             texts={key: "16/10/2026"})
    _render_reports()

    assert any("YYYY-MM-DD" in s for s in _said(st.error)), _said(st.error)
    rp.set_meta.assert_not_called()
