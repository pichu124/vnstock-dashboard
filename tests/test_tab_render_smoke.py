"""Render thử tab Thị trường + 5 panel brief bằng Streamlit GIẢ.

Vì sao cần: đợt tách 12/08 kéo ~2.400 dòng UI ra khỏi hai hàm khổng lồ. Suite
cũ chỉ soi được phần THUẦN (định dạng, nhận định, sparkline) — phần render thì
không test nào chạm tới, nên lỗi kiểu "cắt khối ra mà quên truyền một biến"
chỉ lộ khi mở dashboard bằng mắt.

Test này chạy THẲNG `render_market_tab()` / `render_brief_panel()` với một
Streamlit giả. Nó KHÔNG kiểm giao diện đẹp hay số đúng — chỉ trả lời đúng một
câu: **code có chạy hết không, hay nổ giữa chừng**. Đó lại chính là rủi ro của
một đợt refactor.

Giới hạn (nói rõ để không tưởng bở):
* Streamlit giả luôn trả về "không bấm" cho mọi nút → nhánh sau khi bấm không
  chạy (train, scan, sinh brief — những thứ tốn tiền/thời gian thật).
* `vnstock_dashboard` bị thay bằng stub, vì module thật dựng UI ngay khi
  import nên không import nổi trong pytest.
* Chạy được KHÔNG có nghĩa là hiển thị đúng — vẫn cần liếc mắt một lần sau
  khi merge.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
_SECTORS = ["Ngân hàng", "Thép & Kim loại", "Công nghệ"]


class _Ctx(MagicMock):
    """Widget vừa là giá trị vừa là context manager (`with st.expander(...)`)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_streamlit():
    st = MagicMock()
    st.columns = lambda spec=2, **k: [
        _Ctx() for _ in (range(spec) if isinstance(spec, int) else spec)]
    st.tabs = lambda labels, **k: [_Ctx() for _ in labels]
    for name in ("expander", "container", "form", "spinner", "status", "empty", "popover"):
        setattr(st, name, lambda *a, **k: _Ctx())
    st.sidebar = _Ctx()
    st.session_state = {}
    st.cache_data = lambda *a, **k: (lambda f: f)
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.fragment = lambda *a, **k: (lambda f: f)
    # Không bấm gì cả — nhánh "sau khi bấm" là việc thật (train/scan/gọi LLM).
    st.button = lambda *a, **k: False
    st.checkbox = lambda *a, **k: False
    st.toggle = lambda *a, **k: False
    st.radio = lambda label, options=(), **k: (list(options)[0] if len(options) else None)
    st.selectbox = lambda label, options=(), **k: (list(options)[0] if len(options) else None)
    st.multiselect = lambda *a, **k: []
    st.text_input = lambda *a, **k: ""
    st.slider = lambda label, *a, **k: (a[0] if a else 0)
    st.number_input = lambda *a, **k: 0
    return st


def _sector_df():
    n = len(_SECTORS)
    cols = {"Ngành": _SECTORS, "Số mã": [10, 5, 3]}
    for c, base in (("Vốn hoá (tỷ)", 1e6), ("Freefloat (tỷ)", 3e5), ("GTGD TB (tỷ)", 500),
                    ("Vol Avg 5", 10.0), ("Vol Avg 10", 9.0), ("Vol Avg 20", 8.0),
                    ("AVG 5-10 %", 5.0), ("AVG 10-20 %", 2.0),
                    ("Vol 5/Free %", 0.5), ("Vol 10/Free %", 0.4), ("Vol 20/Free %", 0.6),
                    ("Vol 5/20 %", 120.0),
                    ("Net BS 1T", 10.0), ("Net BS 1M", 20.0),
                    ("Net BS 3M", 30.0), ("Net BS 6M", 40.0),
                    ("NN 1T (tỷ)", 100.0), ("NN 1M (tỷ)", 200.0), ("NN 3M (tỷ)", 300.0),
                    ("Biên 1T (%)", 2.0), ("Biên 1M (%)", 3.0), ("Biên 3M (%)", 4.0),
                    ("Giá 1T %", 1.5), ("Giá 1M %", 3.0), ("Giá 3M %", 5.0)):
        # dấu xen kẽ để chạm cả nhánh xanh lẫn đỏ của bảng màu
        cols[c] = [base * s for s in (1, -0.5, 0.2)][:n]
    return pd.DataFrame(cols)


def _ticker_df():
    df = _sector_df().rename(columns={"Ngành": "_x"})
    df.insert(0, "Mã", ["VCB", "HPG", "FPT"])
    df.insert(1, "Ngành", _SECTORS)
    return df.drop(columns=["_x", "Số mã"])


def _index_df():
    return pd.DataFrame({
        "time": pd.bdate_range(end="2026-08-12", periods=90),
        "VNINDEX": np.linspace(1200, 1300, 90),
        "VNINDEX_chg": np.linspace(-1, 1, 90),
    })


def _stub_dashboard(sector_df=None, index_df=None):
    """`vnstock_dashboard` thật dựng UI ngay khi import → phải stub."""
    m = types.ModuleType("vnstock_dashboard")
    m.INDEX_SYMBOLS = ["VNINDEX"]
    m.VN30_SYMBOLS = ["VCB"]
    m.WSS_AVAILABLE = False
    m.load_market_overview = lambda *a, **k: (
        sector_df if sector_df is not None else pd.DataFrame())
    m.load_index_overview = lambda days=90: (
        index_df if index_df is not None else pd.DataFrame())
    m.load_live_quote = lambda *a, **k: {}
    m.load_price_history = lambda *a, **k: pd.DataFrame()
    m.load_screener_results = lambda *a, **k: None
    m.PRICES_DIR = ROOT / "data_warehouse" / "prices"
    return m


@pytest.fixture
def render_env(monkeypatch):
    """Cài Streamlit giả + stub dashboard, rồi nạp lại module tab."""
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setitem(sys.modules, "streamlit.components", MagicMock())
    monkeypatch.setitem(sys.modules, "streamlit.components.v1", MagicMock())
    return st


def _load(name):
    import importlib
    mod = importlib.import_module(name)
    return importlib.reload(mod)


def test_market_tab_renders_with_no_data(render_env, monkeypatch):
    """Kho trống / loader chết — đường đi hay gặp nhất khi máy vừa dựng lại."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_dashboard())
    _load("dashboard.market_tab").render_market_tab()


def test_market_tab_renders_with_data(render_env, monkeypatch):
    """Có data thì bảng ngành, thang màu, sparkline, treemap, nhận định đều
    chạy — đúng những chỗ vừa bị kéo ra module khác."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(_sector_df(), _index_df()))
    render_env.session_state["_mkt_ticker_data"] = _ticker_df()
    _load("dashboard.market_tab").render_market_tab()


def test_market_tab_renders_when_drilldown_sector_selected(render_env, monkeypatch):
    """Drill-down dùng THANG MÀU RIÊNG (`_dd_amp_color`) — chính chỗ trước đây
    là bản chép của thang bảng tổng."""
    monkeypatch.setitem(sys.modules, "vnstock_dashboard",
                        _stub_dashboard(_sector_df(), _index_df()))
    st = render_env
    st.session_state["_mkt_ticker_data"] = _ticker_df()
    st.selectbox = lambda label, options=(), **k: (
        "Ngân hàng" if "ngành" in str(label).lower() and "Ngân hàng" in list(options)
        else (list(options)[0] if len(options) else None))
    _load("dashboard.market_tab").render_market_tab()


def test_brief_panel_renders(render_env):
    """5 panel con vừa tách — nổ ở đây nghĩa là cắt khối mà rơi mất biến."""
    _load("dashboard.market_brief_panel").render_brief_panel()


@pytest.mark.parametrize("mod,fn", [
    ("dashboard.brief_agent_settings", "render_agent_settings"),
    ("dashboard.brief_run_panel", "render_brief_runner"),
    ("dashboard.brief_accuracy_panel", "render_accuracy_widget"),
    ("dashboard.brief_history_panel", "render_brief_history"),
    ("dashboard.brief_strategy_panel", "render_strategy_panel"),
])
def test_each_brief_subpanel_renders_on_its_own(render_env, mod, fn):
    """Gọi lẻ từng panel: panel phải tự đứng được, không dựa vào biến mà panel
    trước tình cờ để lại."""
    getattr(_load(mod), fn)()
