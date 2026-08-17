"""Cờ `live_mode` phải SỐNG QUA chuyển tab — bug user bắt 17/08.

Chuyện đã xảy ra: nav dùng `st.pills` nên mỗi lượt chạy CHỈ tab đang mở được
render. Toggle "Real-time WSS" nằm trong sidebar tab Phân tích và từng bind
thẳng `key="live_mode"` — mà Streamlit XOÁ session_state của widget không
được render trong lượt. Hệ quả: bấm sang tab Thị trường là cờ bị xoá,
`market_tab` đọc `st.session_state.get("live_mode")` ra None → khối live
(khung chỉ số + heatmap VN30) bị bỏ qua IM LẶNG, không cả dòng
"⏳ Chờ WSS data...". Khối này vì thế CHƯA BAO GIỜ hiện được qua đường
điều hướng thật — lộ đúng ở bước soi mắt mục 1 (heatmap là khối duy nhất
máy không phủ được, phải chờ user nhìn trong phiên).

Fix: tách key — widget giữ `key="live_mode_toggle"`, cờ cho tab khác đọc
gán tay `st.session_state["live_mode"] = live_on` (key thường, Streamlit
không dọn). Hai test structural ở đây canh cả HAI PHÍA của hợp đồng đó;
test render canh phía tiêu thụ thật sự vẽ heatmap khi cờ sống.
"""
import re
import sys
import types
from pathlib import Path

import pytest

from tests.test_tab_render_smoke import (
    _fake_analyzer, _fake_memory, _fake_streamlit, _load, _stub_dashboard,
)

ROOT = Path(__file__).resolve().parent.parent
_ANALYSIS_SRC = (ROOT / "dashboard" / "analysis_tab.py").read_text(encoding="utf-8")
_MARKET_SRC = (ROOT / "dashboard" / "market_tab.py").read_text(encoding="utf-8")


# ── Structural: hợp đồng key giữa hai tab ────────────────────────────────────

def test_toggle_widget_must_not_bind_the_crosstab_flag_key():
    """Widget bind `key="live_mode"` là tái phát bug: Streamlit sẽ xoá cờ
    ngay khi rời tab Phân tích. Key widget phải là key KHÁC."""
    assert not re.search(r'key\s*=\s*["\']live_mode["\']', _ANALYSIS_SRC), (
        "Toggle đang bind thẳng key='live_mode' — cờ sẽ chết khi chuyển tab "
        "(widget-state bị Streamlit dọn khi widget không render). "
        "Dùng key widget riêng + gán tay st.session_state['live_mode']."
    )


def test_analysis_tab_assigns_plain_flag_for_other_tabs():
    """Cờ phải được GÁN TAY thành key thường thì mới sống qua chuyển tab."""
    assert re.search(r'st\.session_state\[["\']live_mode["\']\]\s*=\s*\w', _ANALYSIS_SRC), (
        "analysis_tab không còn gán st.session_state['live_mode'] — "
        "market_tab sẽ không bao giờ thấy cờ bật."
    )


def test_market_tab_still_reads_the_same_flag_key():
    """Đổi tên cờ một phía là lưới đứt mà không ai hay — canh cả phía đọc."""
    assert re.search(r'session_state\.get\(\s*["\']live_mode["\']', _MARKET_SRC), (
        "market_tab không còn đọc cờ 'live_mode' — nếu đổi tên cờ thì phải "
        "đổi CẢ HAI phía và cập nhật test này."
    )


# ── Render: phía tiêu thụ thật sự vẽ heatmap khi cờ sống ─────────────────────

def _live_quote(sym):
    return {"ticker": sym, "price": 100.0, "chg_pct": 1.25, "volume": 264700}


@pytest.fixture
def render_env(monkeypatch):
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setitem(sys.modules, "streamlit.components",
                        types.ModuleType("streamlit.components"))
    _v1 = types.ModuleType("streamlit.components.v1")
    _v1.html = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "streamlit.components.v1", _v1)
    monkeypatch.setitem(sys.modules, "vnstock_market_analyzer", _fake_analyzer())
    monkeypatch.setitem(sys.modules, "vnstock_memory", _fake_memory())
    sess = types.ModuleType("vnstock_session_stats")
    sess.load_session_stats_history = lambda *a, **k: {}
    sess.load_session_stats = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "vnstock_session_stats", sess)
    return st


def _markdown_dump(st):
    return " | ".join(str(c.args[0]) if c.args else ""
                      for c in st.markdown.call_args_list)


def test_market_tab_renders_heatmap_when_flag_alive(render_env, monkeypatch):
    """Cờ sống (key thường) + WSS có quote → heatmap VN30 phải xuất hiện."""
    stub = _stub_dashboard()
    stub.WSS_AVAILABLE = True
    stub.load_live_quote = _live_quote
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", stub)

    st = render_env
    st.session_state["live_mode"] = True
    _load("dashboard.market_tab").render_market_tab()

    assert "VN30 Heatmap" in _markdown_dump(st), (
        "Cờ live_mode=True mà tab Thị trường không vẽ heatmap — "
        "đường render khối live gãy."
    )


def test_market_tab_skips_live_block_without_flag_but_says_so(render_env, monkeypatch):
    """Không bật live thì khối live vắng CÓ CHỦ Ý — nhưng phải để lại MỘT dòng
    chỉ đường. Bài học 17/08: khối vắng âm thầm thì user không phân biệt được
    "chưa bật" với "cờ chết" với "máy chạy code cũ" — dòng caption này là
    chứng chỉ code-mới-đang-chạy, đừng để ai dọn mất."""
    stub = _stub_dashboard()
    stub.WSS_AVAILABLE = True
    stub.load_live_quote = _live_quote
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", stub)

    _load("dashboard.market_tab").render_market_tab()

    assert "VN30 Heatmap" not in _markdown_dump(render_env)
    caps = " | ".join(str(c.args[0]) if c.args else ""
                      for c in render_env.caption.call_args_list)
    assert "Live Mode tắt" in caps, (
        "Cờ tắt mà không có dòng chỉ đường — khối live lại vắng mặt âm thầm."
    )
