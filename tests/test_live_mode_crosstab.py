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
_MAIN_SRC = (ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8")
_MARKET_SRC = (ROOT / "dashboard" / "market_tab.py").read_text(encoding="utf-8")
_TAB_SRCS = {p.name: p.read_text(encoding="utf-8")
             for p in (ROOT / "dashboard").glob("*.py")}


# ── Structural: hợp đồng key + vị trí toggle ─────────────────────────────────

def test_no_widget_anywhere_binds_the_crosstab_flag_key():
    """Widget bind `key="live_mode"` là tái phát bug: Streamlit sẽ xoá cờ
    ngay khi widget rời cây render. Key widget phải là key KHÁC."""
    offenders = [name for name, src in {**_TAB_SRCS,
                                        "vnstock_dashboard.py": _MAIN_SRC}.items()
                 if re.search(r'key\s*=\s*["\']live_mode["\']', src)]
    assert not offenders, (
        f"{offenders} đang bind widget thẳng key='live_mode' — cờ sẽ chết khi "
        "widget không render (Streamlit dọn widget-state). "
        "Dùng key widget riêng + gán tay st.session_state['live_mode']."
    )


def test_toggle_lives_in_always_rendered_sidebar_and_assigns_plain_flag():
    """Bổ sung 17/08 (lần 2): toggle CHUYỂN LÊN sidebar chung của main script
    — render mọi lượt, mọi tab, hết cả lớp bug dọn-state lẫn cảnh user tìm
    không ra công tắc giữa 3 toggle 'Live...'. Ai dời nó về một tab
    (dashboard/*.py) là mở lại lớp bug đó → đỏ."""
    assert re.search(r'key\s*=\s*["\']live_mode_toggle["\']', _MAIN_SRC), (
        "vnstock_dashboard.py không còn toggle Live Mode ở sidebar chung."
    )
    assert re.search(r'st\.session_state\[["\']live_mode["\']\]\s*=\s*\w', _MAIN_SRC), (
        "Sidebar chung không còn gán st.session_state['live_mode'] — "
        "các tab sẽ không bao giờ thấy cờ bật."
    )
    offenders = [name for name, src in _TAB_SRCS.items()
                 if re.search(r'key\s*=\s*["\']live_mode_toggle["\']', src)]
    assert not offenders, (
        f"{offenders} render toggle Live Mode TRONG TAB — widget sẽ bị dọn "
        "state khi user rời tab. Toggle phải ở sidebar chung (main script)."
    )


def test_market_tab_still_reads_the_same_flag_key():
    """Đổi tên cờ một phía là lưới đứt mà không ai hay — canh cả phía đọc."""
    assert re.search(r'session_state\.get\(\s*["\']live_mode["\']', _MARKET_SRC), (
        "market_tab không còn đọc cờ 'live_mode' — nếu đổi tên cờ thì phải "
        "đổi CẢ HAI phía và cập nhật test này."
    )


def test_live_scan_consumers_are_gated_on_the_engine():
    """Hướng (a) user chốt 17/08: hai toggle Live Scan là CONSUMER của động
    cơ WSS — động cơ tắt thì phải KHOÁ (disabled) + kéo về OFF + caption chỉ
    đường, thay vì bật chay được rồi chỉ thấy "Chưa có quote data" (chính
    cảnh làm user tưởng Live Scan là Live Mode)."""
    for fname, widget_key in (("screener_tab.py", "live_scan_on"),
                              ("money_flow_tab.py", "mf_live")):
        src = _TAB_SRCS[fname]
        assert re.search(r'session_state\.get\(\s*["\']live_mode["\']', src), (
            f"{fname}: toggle Live Scan không còn nhìn cờ động cơ live_mode."
        )
        assert re.search(r'disabled\s*=\s*not\s+_wss_engine_on', src), (
            f"{fname}: toggle Live Scan không còn bị khoá khi động cơ tắt."
        )
        assert re.search(
            rf'st\.session_state\[["\']{widget_key}["\']\]\s*=\s*False', src), (
            f"{fname}: không còn kéo '{widget_key}' về OFF khi động cơ tắt — "
            "toggle sẽ đứng ON-nhưng-xám, trạng thái nói dối."
        )
        assert "Cần bật" in src, (
            f"{fname}: mất caption chỉ đường về 🔴 Live Mode."
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


_CELL_RE = r"flex:0 1 ([0-9.]+)%'><div style='[^']*'>([A-Z0-9]+)</div>"


def _heatmap_env(monkeypatch, render_env, tickers, caps=None, live_basket=None):
    import pandas as pd
    stub = _stub_dashboard()
    stub.WSS_AVAILABLE = True
    stub.VN30_SYMBOLS = list(tickers)
    if live_basket is not None:
        stub.get_vn30_symbols = lambda: list(live_basket)
    stub.load_live_quote = _live_quote
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", stub)
    render_env.session_state["live_mode"] = True
    if caps:
        render_env.session_state["_mkt_ticker_data"] = pd.DataFrame(
            {"Mã": list(caps), "Vốn hoá (tỷ)": [float(v) for v in caps.values()]})
    _load("dashboard.market_tab").render_market_tab()
    return _markdown_dump(render_env)


def test_heatmap_cell_width_scales_with_market_cap(render_env, monkeypatch):
    """User chốt 18/08: rộng ô ≈ vốn hoá TƯƠNG ĐỐI, nén sqrt — VCB cap gấp
    16× SSB thì bề rộng gấp ~4×. Bề rộng đi bằng flex-BASIS %: dùng
    flex-grow thì min-width nuốt hết chênh lệch (đo trên trình duyệt thật
    18/08: 28/30 ô dính đúng 80px). Tổng % của mọi ô = _HEATMAP_WIDTH_SPAN
    nên số hàng ổn định dù cap thay đổi."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB"],
                        {"VCB": 400_000, "SSB": 25_000})
    w = {tk: float(p) for p, tk in re.findall(_CELL_RE, dump)}
    assert set(w) == {"VCB", "SSB"}, f"không parse được cell: {w}"
    ratio = w["VCB"] / w["SSB"]
    assert 3.5 < ratio < 4.5, f"cap 16× phải ra rộng ~4× (sqrt), đang {ratio:.2f}×"
    from dashboard.market_tab import _HEATMAP_WIDTH_SPAN
    assert abs(sum(w.values()) - _HEATMAP_WIDTH_SPAN) < 0.5
    assert "rộng ô ≈ vốn hoá" in dump
    assert "vốn hoá ~400,000 tỷ" in dump          # tooltip format EN


def test_heatmap_cell_does_not_stretch_to_fill_last_row(render_env, monkeypatch):
    """grow phải là 0: bản grow=1 đo được TCB phình 575px ở hàng cuối —
    bề rộng lúc đó NÓI DỐI vốn hoá. Lề phải so le là cái giá chấp nhận."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB"],
                        {"VCB": 400_000, "SSB": 25_000})
    assert "flex:0 1 " in dump and "flex:1 1 " not in dump


def test_heatmap_ticker_without_cap_takes_median_weight(render_env, monkeypatch):
    """Mã thiếu cap (mã mới / bảng screener chưa có) không được teo bằng 0
    cũng không được phình — đi trọng số TRUNG VỊ, và không có tooltip."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB", "XYZ"],
                        {"VCB": 400_000, "SSB": 25_000})
    w = {tk: float(p) for p, tk in re.findall(_CELL_RE, dump)}
    assert set(w) == {"VCB", "SSB", "XYZ"}
    assert w["SSB"] <= w["XYZ"] <= w["VCB"], f"XYZ phải nằm giữa: {w}"
    assert "XYZ: vốn hoá" not in dump


def test_heatmap_without_cap_data_falls_back_to_equal_widths(render_env, monkeypatch):
    """Lượt render đầu (`_mkt_ticker_data` chưa có vì fragment đứng trước
    thân tab): mọi ô rộng bằng nhau, KHÔNG nổ, và không ghi chú vốn hoá
    (ghi mà không scale là nhãn nói dối)."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB"])
    assert not re.findall(_CELL_RE, dump), "thiếu cap mà vẫn scale theo %"
    assert dump.count("flex:1 1 0") == 2, "mọi ô phải rộng bằng nhau"
    assert "rộng ô ≈ vốn hoá" not in dump


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


def test_heatmap_follows_the_live_basket_not_the_constant(render_env, monkeypatch):
    """HOSE đổi rổ VN30 2 lần/năm. Heatmap phải vẽ rổ SỐNG, không phải hằng số
    chép cứng — vết 20/08/2026: user nhìn heatmap trong phiên mới phát hiện nó
    còn vẽ rổ cũ, vì `VN30_SYMBOLS` không chỗ nào tự làm mới."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "POW"],
                        live_basket=["VCB", "VIX"])
    assert ">VIX<" in dump, "mã MỚI vào rổ phải xuất hiện"
    assert ">POW<" not in dump, "mã ĐÃ rời rổ không được vẽ nữa"


def test_heatmap_falls_back_to_the_constant_when_resolver_is_missing(
        render_env, monkeypatch):
    """Không phân giải được rổ sống thì vẫn phải vẽ — hằng số là lưới cuối,
    không phải màn hình trắng."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB"])
    assert ">VCB<" in dump and ">SSB<" in dump


def test_heatmap_ignores_an_empty_live_basket(render_env, monkeypatch):
    """Resolver trả rỗng (API dở dang) không được làm heatmap trắng bảng."""
    dump = _heatmap_env(monkeypatch, render_env, ["VCB", "SSB"], live_basket=[])
    assert ">VCB<" in dump and ">SSB<" in dump
