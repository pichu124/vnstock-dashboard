"""Smoke tests for dashboard.analysis_tab."""

from __future__ import annotations

import ast
import inspect
import types
from pathlib import Path

import pandas as pd
import pytest


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


# ── Nút "✅ Tạo alert": cũng ghi theo FILE, không theo bản chụp ─────────────

def _create_alert_block():
    return next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.If)
                and "alert_create" in ast.unparse(n.test))


def test_create_alert_rereads_disk(tmp_path):
    """Bản chụp sidebar có A chưa bắn; `_alert_checker` vừa bắn + lưu A. Nối B vào bản
    chụp rồi ghi là trả A về "chưa bắn" ⇒ Telegram bắn lại."""
    import json
    path = tmp_path / "price_alerts.json"
    a = {"ticker": "VCB", "condition": "above", "target": 100.0, "fired": False}
    path.write_text(json.dumps([{**a, "fired": True}]), encoding="utf-8")
    st = types.SimpleNamespace(button=lambda label, key=None, **kw: key == "alert_create",
                               rerun=_raise_rerun, error=lambda msg: None)
    ns = {"st": st, "ALERTS_PATH": path, "_alerts": [dict(a)], "_alerts_broken": False,
          "_al_ticker": "FPT", "_al_cond": "below", "_al_target": 90.0,
          "load_alerts": lambda: json.loads(path.read_text(encoding="utf-8")),
          "save_alerts": lambda al: path.write_text(json.dumps(al), encoding="utf-8")}
    with pytest.raises(_Rerun):
        exec(compile(ast.Module([_create_alert_block()], []), "analysis_tab.py", "exec"), ns)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk[0] == {**a, "fired": True}
    assert {k: v for k, v in on_disk[1].items() if k != "created_at"} == {
        "ticker": "FPT", "condition": "below", "target": 90.0, "fired": False}
    assert len(on_disk) == 2


def test_create_alert_does_not_write_when_file_unreadable(tmp_path):
    """Đọc lại hỏng (Dropbox đang ghi dở) ⇒ báo lỗi, KHÔNG ghi gì."""
    saved, errors = [], []

    def _broken():
        raise ValueError("Expecting value: line 1")

    st = types.SimpleNamespace(button=lambda label, key=None, **kw: key == "alert_create",
                               rerun=_raise_rerun, error=errors.append)
    ns = {"st": st, "ALERTS_PATH": tmp_path / "price_alerts.json", "_alerts": [],
          "_alerts_broken": False, "_al_ticker": "FPT", "_al_cond": "below",
          "_al_target": 90.0, "load_alerts": _broken, "save_alerts": saved.append}
    exec(compile(ast.Module([_create_alert_block()], []), "analysis_tab.py", "exec"), ns)
    assert saved == []
    assert "price_alerts.json" in errors[0]


def _clear_fired_block():
    return next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.If)
                and ast.unparse(n.test) == "_fired_alerts" and "alert_clear" in ast.unparse(n))


@pytest.mark.parametrize("clicked, block", [("alert_create", _create_alert_block),
                                            ("alert_clear", _clear_fired_block)])
def test_alert_button_reports_failed_save_instead_of_rerun(tmp_path, clicked, block):
    """`save_alerts` hết lượt thử (Dropbox giữ file) trả False: rerun ngay thì trang vẽ
    lại như chưa bấm, user không biết alert chưa được tạo / chưa xoá."""
    errors: list = []
    st = types.SimpleNamespace(button=lambda label, key=None, **kw: key == clicked,
                               rerun=_raise_rerun, error=errors.append)
    ns = {"st": st, "ALERTS_PATH": tmp_path / "price_alerts.json", "_alerts": [],
          "_alerts_broken": False, "_al_ticker": "FPT", "_al_cond": "below",
          "_al_target": 90.0, "_fired_alerts": [{"ticker": "HPG", "fired": True}],
          "load_alerts": lambda: [{"ticker": "HPG", "fired": True}],
          "save_alerts": lambda al: False}
    exec(compile(ast.Module([block()], []), "analysis_tab.py", "exec"), ns)
    assert len(errors) == 1 and "price_alerts.json" in errors[0]


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


# ── 1W/1M: nhãn kỳ của pandas là ngày CUỐI kỳ (tương lai) ──────────────────

_FN_BODY = next(n for n in _TAB_TREE.body if isinstance(n, ast.FunctionDef)).body


def _dashboard_fn(name: str, **globs):
    """Hàm THẬT của vnstock_dashboard (module đó dựng UI khi import ⇒ lấy từ source)."""
    src = (Path(__file__).resolve().parent.parent / "vnstock_dashboard.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == name)
    ns: dict = {"pd": pd, **globs}
    exec(compile(ast.Module([fn], []), "vnstock_dashboard.py", "exec"), ns)
    return ns[name]


@pytest.mark.parametrize("tf, n_bars", [("1D", 8), ("1W", 2), ("1M", 1)])
def test_data_caption_shows_real_session_dates(tf, n_bars):
    """Caption "📅 Data: … → …" từng in 18/10 (CN cuối tuần) / 31/10 (cuối
    tháng) khi phiên cuối có data mới là T4 14/10."""
    chain = next(n for n in _FN_BODY if isinstance(n, ast.If)
                 and "resample_ohlcv" in ast.unparse(n))
    caption = next(n for n in _FN_BODY if isinstance(n, ast.If) and "📅 Data" in ast.unparse(n))
    days = pd.bdate_range("2026-10-05", "2026-10-14")                  # T2 05/10 → T4 14/10
    df = pd.DataFrame({"time": days, "open": 10.0, "high": 11.0, "low": 9.0,
                       "close": 10.5, "volume": 1e5})
    shown: list = []
    ns = {"st": types.SimpleNamespace(caption=shown.append), "tf": tf, "df": df,
          "_merge_today_bar": lambda d: d, "resample_ohlcv": _dashboard_fn("resample_ohlcv")}
    exec(compile(ast.Module([chain, caption], []), "analysis_tab.py", "exec"), ns)
    assert len(ns["chart_df"]) == n_bars
    assert shown == [f"📅 Data: 05/10/2026 → 14/10/2026 ({n_bars} bars)"]


@pytest.mark.parametrize("live", [True, False])
@pytest.mark.parametrize("tf, writes_bar", [("1D", True), ("All", True),
                                            ("1W", False), ("1M", False)])
def test_today_bar_writer_only_for_daily_views(tf, writes_bar, live):
    """1W/1M: bar hôm nay mang time=hôm nay < nhãn kỳ cuối ⇒ JS chart luôn bỏ
    (`b.time < lastT`). Bộ ghi khi đó là code chết mà vẫn gọi VCI mỗi phút,
    cả ngoài giờ."""
    import dashboard.analysis_tab as tab
    from tests.test_tab_render_smoke import _fake_streamlit
    block = next(n for n in _FN_BODY if isinstance(n, ast.If)
                 and ast.unparse(n.test) == "_live_daily")
    vci: list = []
    live_urls: list = []
    ns = {**vars(tab), "st": _fake_streamlit(), "tf": tf, "ticker": "VCB",
          "chart_df": pd.DataFrame(),
          "_live_daily": live, "_live_intraday": False,
          "load_intraday": lambda t, interval: vci.append(interval) or pd.DataFrame(),
          "load_live_quote": lambda t: None,
          "render_chart": lambda df, t, **kw: live_urls.append(kw.get("live_url"))}
    exec(compile(ast.Module([block], []), "analysis_tab.py", "exec"), ns)
    assert bool(vci) is writes_bar
    assert len(live_urls) == 1
    assert (live_urls[0] == "/app/static/today_bars/VCB.json") is writes_bar
    if not writes_bar:
        assert live_urls[0] is None


# ── Bảng Định giá & Sinh lời: số kiểu EN có phân cách nghìn ─────────────────

def test_fundamental_ratios_use_thousands_separator():
    """EPS 4523.12 đ / Book Value 25123.46 đ thiếu dấu phẩy nghìn (quy ước `{:,.2f}`)."""
    import dashboard.analysis_tab as tab
    loop = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.For)
                and ast.unparse(n.iter) == "ratios")
    html: list = []
    st = types.SimpleNamespace(markdown=lambda s, **kw: html.append(s))
    ratios = [("EPS", 4523.123, "đ"), ("Book Value", 25123.456, "đ"), ("P/E", 12.5, "lần")]
    exec(compile(ast.Module([loop], []), "analysis_tab.py", "exec"),
         {**vars(tab), "st": st, "ratios": ratios})
    assert "4,523.12 đ" in html[0]
    assert "25,123.46 đ" in html[1]
    assert "12.50 lần" in html[2]


# ── Khuyến nghị tổng hợp: trọng số theo phần THỰC có điểm ───────────────────

def test_composite_tech_only_uses_full_tech_weight():
    """Không có điểm cơ bản mà vẫn nhân tech × 0.5 ⇒ tech +1.00 chỉ ra +0.50, không
    bao giờ tới STRONG (> 0.6)."""
    from dashboard.analysis_tab import composite_score
    assert composite_score(0.8, None) == (0.8, "(chỉ technical)")
    assert composite_score(-1.0, None) == (-1.0, "(chỉ technical)")


def test_composite_tech_and_fund_is_40_60():
    from dashboard.analysis_tab import composite_score
    assert composite_score(0.5, 1.0) == (0.8, "(40% tech + 60% fund)")
    assert composite_score(1.0, -1.0) == (-0.2, "(40% tech + 60% fund)")


def test_composite_card_when_fund_api_fails_says_tech_only():
    """Bật toggle cơ bản nhưng API lỗi (không có fund_score): thẻ từng ghi "(40% tech +
    60% fund)" và nhân tech × 0.4. Chạy ĐÚNG khối Consensus trong globals của module."""
    import dashboard.analysis_tab as tab
    col_fund = next(n for n in ast.walk(_TAB_TREE) if isinstance(n, ast.With)
                    and ast.unparse(n.items[0].context_expr) == "col_fund")
    body = col_fund.body
    start = next(i for i, n in enumerate(body) if "tech_score" in ast.unparse(n))
    end = next(i for i, n in enumerate(body) if "Khuyến nghị tổng hợp" in ast.unparse(n))
    html: list = []
    ns = {**vars(tab), "st": types.SimpleNamespace(markdown=lambda s, **kw: html.append(s)),
          "tech": {"tech_score": 0.8}, "load_fund": True, "fund": {"error": "HTTP 403"},
          "fund_score": None}
    exec(compile(ast.Module(body[start:end + 1], []), "analysis_tab.py", "exec"), ns)
    assert "(chỉ technical)" in html[-1] and "60% fund" not in html[-1]
    assert "STRONG BUY" in html[-1] and "+0.80" in html[-1]


# ── P3 giao diện: tiêu đề trang + màu giá theo bảng điện ────────────────────

def test_page_title_shows_exchange_and_industry():
    from dashboard.analysis_tab import page_title
    assert page_title("VCB", "Vietcombank", "HOSE", "Ngân hàng") == (
        "VCB — Vietcombank", "HOSE · Ngân hàng")
    assert page_title("FPT", "FPT Corp", "", "Công nghệ") == ("FPT — FPT Corp", "Công nghệ")


def test_page_title_without_company_name_or_meta():
    """Hợp đồng tương lai / chỉ số không có trong bảng ngành: tên rơi về chính mã ⇒
    không in "VN30F1M — VN30F1M", không dòng phụ rỗng."""
    from dashboard.analysis_tab import page_title
    assert page_title("VN30F1M", "VN30F1M", "", "") == ("VN30F1M", None)


def _metric_row_items(closes: list) -> list:
    """Chạy ĐÚNG đoạn `price = …` → `render_metric_row([...])` với giá kho `closes`."""
    import dashboard.analysis_tab as tab
    i0 = next(i for i, n in enumerate(_FN_BODY) if isinstance(n, ast.Assign)
              and ast.unparse(n.targets[0]) == "price")
    i1 = next(i for i, n in enumerate(_FN_BODY) if isinstance(n, ast.Expr)
              and ast.unparse(n).startswith("render_metric_row("))
    df = pd.DataFrame({"time": pd.bdate_range("2026-10-26", periods=len(closes)),
                       "close": closes})
    chg1d = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) > 1 else None
    got: list = []
    ns = {**vars(tab), "df": df, "render_metric_row": got.extend,
          "fmt_pct": _dashboard_fn("fmt_pct"),
          "tech": {"price": closes[-1], "chg1d": chg1d, "pct52": 50.0,
                   "lo52": min(closes), "hi52": max(closes)}}
    exec(compile(ast.Module(_FN_BODY[i0:i1 + 1], []), "analysis_tab.py", "exec"), ns)
    return got


@pytest.mark.parametrize("closes, token", [
    ([50.0, 51.0], "up"), ([50.0, 49.0], "down"),
    ([50.0, 50.0], "ref"),          # đứng giá = vàng tham chiếu (bản cũ: trắng / "0.0%")
    ([50.0], "text_faint"),         # không có phiên trước ⇒ không đoán chiều
])
def test_price_and_1d_change_use_board_colors(closes, token):
    """Giá + "1 ngày" tô theo tham chiếu (= đóng cửa phiên trước) như bảng điện VN;
    5/20 ngày vẫn tô theo dấu (không ép màu)."""
    from dashboard.theme import TOKENS
    items = _metric_row_items(closes)
    assert items[0][:2] == ("Giá hiện tại", f"{closes[-1]:,.1f}")
    assert items[0][3] == TOKENS[token]
    assert items[1][0] == "1 ngày" and items[1][3] == TOKENS[token]
    assert all(len(it) == 3 for it in items[2:])


def test_metric_row_color_override_wins_over_sign():
    """Phần tử thứ 4 là màu ép; thiếu thì vẫn tô theo dấu `+`/`-` như cũ."""
    from dashboard.theme import TOKENS
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    row = _dashboard_fn("render_metric_row", st=st, _T=TOKENS)
    row([("Giá", "51.0", "nghìn đồng", TOKENS["ref"]), ("5 ngày", "+1.2%", ""),
         ("20 ngày", "-3.0%", ""), ("Khác", "12", "")])
    html = [c.args[0] for c in st.markdown.call_args_list]
    assert f"color:{TOKENS['ref']}\">51.0<" in html[0]
    assert f"color:{TOKENS['up']}\">+1.2%<" in html[1]
    assert f"color:{TOKENS['down']}\">-3.0%<" in html[2]
    assert f"color:{TOKENS['text_strong']}\">12<" in html[3]


def _live_daily_strip(quote: dict) -> str:
    """HTML dải giá live của khung ngày (khối `if _live_daily:` thật, st giả)."""
    import dashboard.analysis_tab as tab
    from tests.test_tab_render_smoke import _fake_streamlit
    block = next(n for n in _FN_BODY if isinstance(n, ast.If)
                 and ast.unparse(n.test) == "_live_daily")
    st = _fake_streamlit()
    ns = {**vars(tab), "st": st, "tf": "1W", "ticker": "VCB", "chart_df": pd.DataFrame(),
          "_live_daily": True, "_live_intraday": False,
          "load_live_quote": lambda t: quote, "is_futures": lambda t: False,
          "fetch_volume_profile_direct": lambda t: [],
          "render_chart": lambda *a, **k: None}
    exec(compile(ast.Module([block], []), "analysis_tab.py", "exec"), ns)
    return next(c.args[0] for c in st.markdown.call_args_list if "BID/ASK" in c.args[0])


@pytest.mark.parametrize("chg, token", [(1.2, "up"), (-0.8, "down"), (0.0, "ref")])
def test_live_strip_price_and_change_colored_vs_reference(chg, token):
    """Bảng điện: giá + %D cùng màu theo tham chiếu; 0% là vàng (bản cũ: `>= 0` ⇒ xanh)."""
    import re
    from dashboard.theme import TOKENS
    html = _live_daily_strip({"price": 25.5, "chg_pct": chg, "volume": 1e6, "bid": 25.4,
                              "ask": 25.5, "time": "2026-10-30T10:15:00"})
    price = re.search(r"<span style='color:([^;']+);[^']*'>25\.50</span>", html)
    pct = re.search(r"<span style='color:([^;']+);[^']*'>[+-]?\d+\.\d\d%</span>", html)
    assert price and price.group(1) == TOKENS[token]
    assert pct and pct.group(1) == TOKENS[token]
