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


# ── Nút "🗑 Xoá alerts đã triggered": ghi theo FILE, không theo bản chụp ────

class _Rerun(Exception):
    """st.rerun thật dừng script bằng exception — giả lập đúng như vậy."""


def _raise_rerun():
    raise _Rerun


def test_clear_fired_alerts_rereads_disk(tmp_path):
    """`_alert_checker` (fragment 10s) có thể bắn + lưu alert SAU bản chụp của
    sidebar. Ghi lại `_active_alerts` cũ là trả A về "chưa bắn" ⇒ Telegram bắn
    lại, và nuốt luôn B vừa thêm (máy kia qua Dropbox)."""
    import json
    block = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.If)
                 and ast.unparse(n.test) == "_fired_alerts" and "alert_clear" in ast.unparse(n))
    path = tmp_path / "price_alerts.json"
    a_new = {"ticker": "VCB", "condition": "above", "target": 100.0, "fired": False}
    b_new = {"ticker": "FPT", "condition": "below", "target": 90.0, "fired": False}
    c_fired = {"ticker": "HPG", "condition": "above", "target": 30.0, "fired": True}
    path.write_text(json.dumps([{**a_new, "fired": True}, b_new, c_fired]), encoding="utf-8")
    st = types.SimpleNamespace(button=lambda label, key=None, **kw: key == "alert_clear",
                               rerun=_raise_rerun, error=lambda msg: None)
    ns = {"st": st, "ALERTS_PATH": path,
          "_active_alerts": [a_new], "_fired_alerts": [c_fired],      # bản chụp lúc vẽ sidebar
          "load_alerts": lambda: json.loads(path.read_text(encoding="utf-8")),
          "save_alerts": lambda al: path.write_text(json.dumps(al), encoding="utf-8")}
    try:
        exec(compile(ast.Module([block], []), "analysis_tab.py", "exec"), ns)
    except _Rerun:
        pass
    assert json.loads(path.read_text(encoding="utf-8")) == [b_new]


def test_clear_fired_alerts_does_not_write_when_file_unreadable(tmp_path):
    """Đọc lại hỏng (Dropbox đang ghi dở) ⇒ báo lỗi, KHÔNG ghi gì."""
    block = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.If)
                 and ast.unparse(n.test) == "_fired_alerts" and "alert_clear" in ast.unparse(n))
    saved, errors = [], []

    def _broken():
        raise ValueError("Expecting value: line 1")

    st = types.SimpleNamespace(button=lambda label, key=None, **kw: key == "alert_clear",
                               rerun=_raise_rerun, error=errors.append)
    ns = {"st": st, "ALERTS_PATH": tmp_path / "price_alerts.json",
          "_active_alerts": [], "_fired_alerts": [{"ticker": "HPG", "fired": True}],
          "load_alerts": _broken, "save_alerts": saved.append}
    exec(compile(ast.Module([block], []), "analysis_tab.py", "exec"), ns)
    assert saved == []
    assert "price_alerts.json" in errors[0]


# ── Chọn mã: lựa chọn MỚI NHẤT của user thắng (selectbox hay nút futures) ────

def _ticker_pick_code():
    """Khối chọn mã thật: selectbox → nút futures (trong `with st.sidebar`) →
    dòng `ticker = …` ngay sau sidebar."""
    fn = next(n for n in _TAB_TREE.body if isinstance(n, ast.FunctionDef))
    sidebar = next(n for n in fn.body if isinstance(n, ast.With))
    start = next(i for i, n in enumerate(sidebar.body) if "ticker_sidebar" in ast.unparse(n))
    end = next(i for i, n in enumerate(sidebar.body) if "futures_picker" in ast.unparse(n))
    pick = next(n for n in fn.body if isinstance(n, ast.Assign)
                and ast.unparse(n.targets[0]) == "ticker")
    return compile(ast.Module(sidebar.body[start:end + 1] + [pick], []), "analysis_tab.py", "exec")


class _PickSt:
    """Đủ ngữ nghĩa Streamlit cho khối chọn mã: widget đọc state theo key;
    callback của nút chạy ĐẦU lượt kế (trước script) và nút trả True đúng lượt đó."""

    def __init__(self):
        self.session_state: dict = {}
        self._callbacks: dict = {}
        self._clicked = None

    def selectbox(self, label, options, key=None, **kw):
        return self.session_state.setdefault(key, list(options)[0])

    def button(self, label, key=None, on_click=None, args=(), kwargs=None, **kw):
        self._callbacks[key] = (on_click, args, kwargs or {})
        return key == self._clicked

    def run(self, code, click=None) -> str:
        if click:
            cb, args, kwargs = self._callbacks[click]
            if cb:
                cb(*args, **kwargs)
        self._clicked = click
        ns = {"st": self, "WSS_AVAILABLE": True, "list_live_futures": lambda: ["VN30F1M"],
              "_ticker_options": ["", "VCB", "FPT", "VN30F1M"], "_ticker_labels": {}}
        exec(code, ns)
        return ns["ticker"]


def test_futures_button_wins_over_previous_selectbox_pick():
    """Đã chọn VCB ở selectbox thì `ticker_input or …` để VCB thắng ⇒ bấm
    "Phân tích VN30F1M →" không đổi mã."""
    code, st = _ticker_pick_code(), _PickSt()
    st.session_state["ticker_sidebar"] = "VCB"
    assert st.run(code) == "VCB"
    st.session_state["futures_picker"] = "VN30F1M"
    assert st.run(code) == "VCB"                        # mới chọn trong picker, chưa bấm
    assert st.run(code, click="anal_fut_go") == "VN30F1M"
    assert st.run(code) == "VN30F1M"                    # lượt sau (đổi khung nến…) vẫn giữ
    st.session_state["ticker_sidebar"] = "FPT"
    assert st.run(code) == "FPT"                        # chọn mã mới ⇒ mã mới thắng
