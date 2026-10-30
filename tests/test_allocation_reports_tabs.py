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


def _allocation_env(monkeypatch, diag: bool):
    import sys
    import types
    from unittest.mock import MagicMock
    from tests.test_tab_render_smoke import _Ctx, _fake_streamlit

    st = _fake_streamlit()
    st.expander = MagicMock(return_value=_Ctx())
    st.session_state = {"diag_mode": diag}
    monkeypatch.setitem(sys.modules, "streamlit", st)
    state = {"band": "B2", "band_label": "Cân bằng", "score": 0.1,
             "allocation": {"Cổ phiếu": 60, "Tiền": 40},
             "inputs": [{"label": "Regime", "value": "yếu", "score": -0.2, "weight": 0.3,
                         "source": "vnstock_regime", "as_of": "2026-10-16"}],
             "history": [{"date": "2026-10-15", "band": "B1"},
                         {"date": "2026-10-16", "band": "B2"}],
             "as_of": "2026-10-16", "updated_at": "2026-10-16 18:30"}
    stubs = {
        "vnstock_allocation": dict(load_state=lambda: state),
        "vnstock_gold": dict(load_gold=lambda: None),
        "vnstock_assets_view": dict(card=lambda key: None),
        "vnstock_scorecard": dict(load_scorecard=lambda: {
            "periods": [], "sources": [{"id": "r1", "source": "SSI", "has_mismatch": False}]}),
        "vnstock_brief": dict(generate_brief=lambda *a, **k: {}),
        "vnstock_memory": dict(recent_briefs=lambda *a, **k: []),
    }
    for name, attrs in stubs.items():
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
    return st


@pytest.mark.parametrize("diag", [False, True])
def test_allocation_page_headers_and_raw_source_log_only_in_diag(monkeypatch, diag):
    """Phân bổ thành trang riêng (P2) ⇒ có tiêu đề trang; tiêu đề mục qua `ui.section`
    (hết `#####` kèm emoji). Log nguồn báo cáo là dict thô (`id`, `has_mismatch`…) ⇒
    chỉ hiện ở chế độ chẩn đoán; bảng tín hiệu không lộ tên trường `as_of`."""
    from dashboard.allocation_tab import render_allocation_subtab
    st = _allocation_env(monkeypatch, diag)

    render_allocation_subtab()

    texts = [str(c.args[0]) for c in st.markdown.call_args_list if c.args]
    assert [t for t in texts if t.lstrip().startswith("#")] == []
    for title in ("Phân bổ", "Vì sao ở band này", "Lịch sử band", "Scorecard hồi tố",
                  "Brief phân bổ"):
        assert any(f">{title}</div>" in t for t in texts), title
    reasons = next(c.args[0] for c in st.dataframe.call_args_list
                   if "Tín hiệu" in c.args[0].columns)
    assert list(reasons.columns) == ["Tín hiệu", "Giá trị", "Điểm", "Trọng số", "Nguồn",
                                     "Ngày dữ liệu"]
    expanders = [str(c.args[0]) for c in st.expander.call_args_list]
    assert any("Log nguồn báo cáo" in e for e in expanders) is diag


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


def _markdown(st):
    return [str(c.args[0]) for c in st.markdown.call_args_list if c.args]


def test_reports_page_has_page_title_and_section_headings(monkeypatch):
    """Trang Báo cáo (P2 tách khỏi Tin tức): tiêu đề trang + tiêu đề mục chuẩn, không "##### 📥 …"."""
    st, _, _ = _reports_env(monkeypatch)
    _render_reports()

    md = _markdown(st)
    assert any(">Báo cáo<" in s for s in md), md
    for title in ("Thêm báo cáo", "Thư viện", "Digest &amp; consensus"):
        assert any(f">{title}<" in s for s in md), (title, md)
    assert not [s for s in md if s.lstrip().startswith("#")], md


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


# ─── Nút không đảo ngược được phải có bước xác nhận ──────────────────────────

@pytest.mark.parametrize("sure,calls", [(False, 0), (True, 1)])
def test_reports_remove_needs_confirmation(monkeypatch, sure, calls):
    """`rp.remove` xoá index + text + file gốc; selectbox mặc định là báo cáo mới nhất."""
    st, rp, _ = _reports_env(monkeypatch, pressed={"_rp_remove"})
    st.checkbox = lambda label, *a, key=None, **k: sure and key.startswith("_rp_remove_sure")

    assert _render_reports() is bool(calls)

    assert rp.remove.call_count == calls
    if calls:
        rp.remove.assert_called_once_with("r1")


def _rates_env(monkeypatch, sure, pressed=True):
    import sys
    import types
    from unittest.mock import MagicMock
    from tests.test_tab_render_smoke import _fake_streamlit

    st = _fake_streamlit()
    st.button = lambda label, *a, key=None, disabled=False, **k: pressed and not disabled
    st.checkbox = lambda label, *a, key=None, **k: sure
    monkeypatch.setitem(sys.modules, "streamlit", st)
    rr = types.SimpleNamespace(
        build_report_data=lambda: {"rates": [1], "curve": [], "as_of": "2026-10-16"},
        render_html=lambda data: "<html></html>")
    tg = types.SimpleNamespace(push_rates_weekly=MagicMock(return_value={"ok": True}))
    monkeypatch.setitem(sys.modules, "vnstock_rates_report", rr)
    monkeypatch.setitem(sys.modules, "vnstock_telegram", tg)
    return st, tg


def test_rates_page_has_page_title(monkeypatch):
    from dashboard.rates_report_tab import render_rates_report_subtab
    st, _ = _rates_env(monkeypatch, sure=False, pressed=False)

    render_rates_report_subtab()

    md = _markdown(st)
    assert any(">Báo cáo tuần<" in s and "Lãi suất" in s for s in md), md
    assert not [s for s in md if s.lstrip().startswith("#")], md


def test_rates_report_failure_is_one_sentence_details_in_diag(monkeypatch):
    """Dựng báo cáo lỗi ⇒ một câu tiếng Việt; chi tiết ngoại lệ chỉ ở chế độ chẩn đoán."""
    import sys
    from dashboard.rates_report_tab import render_rates_report_subtab
    st, _ = _rates_env(monkeypatch, sure=False, pressed=False)

    def _boom():
        raise KeyError("rates_table")
    sys.modules["vnstock_rates_report"].build_report_data = _boom

    render_rates_report_subtab()

    assert _said(st.error) == ["Không dựng được báo cáo tuần."]
    assert not st.exception.called
    st.session_state["diag_mode"] = True
    render_rates_report_subtab()
    st.exception.assert_called_once()


@pytest.mark.parametrize("sure,calls", [(False, 0), (True, 1)])
def test_rates_telegram_push_needs_confirmation(monkeypatch, sure, calls):
    from dashboard.rates_report_tab import render_rates_report_subtab
    st, tg = _rates_env(monkeypatch, sure)

    render_rates_report_subtab()

    assert tg.push_rates_weekly.call_count == calls


def test_rates_telegram_confirmation_is_spent_after_one_push(monkeypatch):
    """Tick một lần rồi bấm hai lần ⇒ gửi một lần (ô đã tick không được giữ nút bật)."""
    from dashboard.rates_report_tab import render_rates_report_subtab
    st, tg = _rates_env(monkeypatch, sure=None)
    ticked = []                    # ô user tick giữ trạng thái; ô key mới bắt đầu trống

    def _checkbox(label, *a, key=None, **k):
        ticked[:] = ticked or [key]
        return key == ticked[0]
    st.checkbox = _checkbox

    render_rates_report_subtab()
    render_rates_report_subtab()

    assert tg.push_rates_weekly.call_count == 1
