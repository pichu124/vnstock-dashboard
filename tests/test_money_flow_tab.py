"""Smoke tests for dashboard.money_flow_tab.

Covers the import contract and signature only — the UI is exercised
manually, and the data-loading helpers (``_fetch_foreign_net_flow``,
``_fetch_order_stats_batch`` etc.) still live in ``vnstock_dashboard.py``
with their own tests in ``test_dashboard.py``.
"""

from __future__ import annotations

import inspect

from tests.conftest import needs


def test_module_imports_without_streamlit():
    """Module must be importable even when Streamlit is not available —
    Streamlit is lazy-imported inside render_money_flow_tab."""
    import importlib
    mod = importlib.import_module("dashboard.money_flow_tab")
    assert hasattr(mod, "render_money_flow_tab")
    assert callable(mod.render_money_flow_tab)


def test_render_takes_no_positional_args():
    """render_money_flow_tab() is a nullary entry point — all state is
    pulled via lazy import from vnstock_dashboard. Locks the contract."""
    from dashboard.money_flow_tab import render_money_flow_tab
    sig = inspect.signature(render_money_flow_tab)
    # No required parameters
    required = [
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD)
    ]
    assert required == []


def test_custom_group_membership_and_override():
    """The tab pulls custom-group tickers (Họ VIN / Họ M) out of their listed
    industry; everything else falls through to the shared sector mapping."""
    from dashboard.money_flow_tab import _custom_sector_for
    for tk in ("VIC", "VHM", "VRE", "VPL"):
        assert _custom_sector_for(tk) == "Họ VIN"
    for tk in ("GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"):
        assert _custom_sector_for(tk) == "Họ M"
    # non-grouped tickers fall through to the base mapping
    for tk in ("FPT", "HPG", "VCB", "VNM", "SSI"):
        assert _custom_sector_for(tk) is None


def test_custom_groups_pinned_first_preserving_base_order():
    """The tab builds _MF_SECTOR_ORDER = [*CUSTOM_SECTOR_ORDER, *SECTOR_ORDER] —
    custom groups sit first (registry order), the base order is preserved, and no
    base sector is dropped. Uses a representative base list to avoid importing the
    Streamlit-bound dashboard."""
    from dashboard.money_flow_tab import _CUSTOM_SECTOR_ORDER
    base = ["Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản"]
    order = [*_CUSTOM_SECTOR_ORDER, *base]   # mirrors the local _MF_SECTOR_ORDER
    assert order[0] == "Họ VIN"
    assert order[1] == "Họ M"
    assert order[len(_CUSTOM_SECTOR_ORDER)] == "Ngân hàng"   # custom groups above banks
    assert order[len(_CUSTOM_SECTOR_ORDER):] == base         # base order preserved


# ── Live Money Flow: Buy/Sell ngành phải lấy từ bid/ask khi không có volume_profile ──

def _stub_mf_dashboard(prices_dir):
    """`vnstock_dashboard` thật dựng UI khi import → stub đủ tên tab dùng."""
    import types

    import pandas as pd

    from dashboard.money_flow_score import score_bar_html, score_label
    from vnstock_sectors import SECTOR_ICONS, SECTOR_ORDER, get_sector

    m = types.ModuleType("vnstock_dashboard")
    m.PRICES_DIR = prices_dir
    m.SECTOR_ICONS, m.SECTOR_ORDER, m.WSS_AVAILABLE = SECTOR_ICONS, SECTOR_ORDER, True
    m._NN_CACHE_PATH = m._ORDER_CACHE_PATH = prices_dir / "none.json"
    m._NN_DIAG = {}
    m._NN_WINDOW_SESSIONS = {0: 1, 7: 5, 30: 20, 90: 60}
    m._aggregate_nn_by_window = lambda raw, days: {}
    m._aggregate_nn_buy_sell_by_window = lambda raw, days: {}
    m._batch_load_live_quotes = lambda tickers: {}
    m._load_last_closes = lambda: {}
    m._compute_gtgd_by_window = lambda n: {}
    m._compute_money_flow_score = lambda *a, **k: 0.0
    m._fetch_foreign_net_flow = lambda **k: pd.DataFrame()
    m._fetch_order_stats_batch = lambda tickers: {}
    m._get_sector, m._is_stock = get_sector, (lambda tk: True)
    m._load_industry_map = lambda: {"VCB": "Ngân hàng"}
    m._score_bar_html, m._score_label = score_bar_html, score_label
    return m


def test_live_sector_buy_sell_comes_from_bid_ask_depth(monkeypatch, tmp_path):
    """Bug: fragment tính buy_r theo bid/ask rồi BỎ, gộp ngành chỉ cộng
    `volume_profile` (cổ phiếu không có) ⇒ mọi ngành 50/50, Áp lực = 0.
    Quote chỉ có bid 300 / ask 100 ⇒ ngành phải ra 75/25."""
    import json
    import sys

    from tests.test_tab_render_smoke import _fake_streamlit, _load

    st = _fake_streamlit()
    st.session_state.update(live_mode=True, live_scan=True)
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _stub_mf_dashboard(tmp_path / "prices"))
    live = tmp_path / "data_warehouse" / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text(json.dumps({
        "ticker": "VCB", "price": 90_000, "volume": 1_000_000,
        "bids": [{"price": 89.9, "volume": 200}, {"price": 89.8, "volume": 100}],
        "asks": [{"price": 90.0, "volume": 100}],
    }), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _load("dashboard.money_flow_tab").render_money_flow_tab()

    live_tbl = [str(c.args[0]) for c in st.markdown.call_args_list
                if c.args and "Áp lực" in str(c.args[0])]
    assert live_tbl, "Không thấy bảng Live Money Flow"
    assert "75/25" in live_tbl[0]


def test_live_sector_buy_ratio_is_weighted_by_gtgd():
    """Ngành = Σ buy_r×GTGD / Σ GTGD (như bảng tĩnh), không phải TB cộng:
    AAA 75% mua @ 90 tỷ + BBB 25% mua @ 30 tỷ ⇒ 62.5%."""
    import pytest

    from dashboard.money_flow_tab import aggregate_live_sectors

    def q(price, vol, bid, ask):
        return {"price": price, "volume": vol,
                "bids": [{"volume": bid}], "asks": [{"volume": ask}]}

    out = aggregate_live_sectors(
        {"AAA": q(90_000, 1_000_000, 300, 100), "BBB": q(30.0, 1_000_000, 100, 300),
         "CCC": q(0, 5, 1, 0)},                           # giá 0 = chưa có quote → bỏ
        lambda tk: "Ngân hàng")
    s = out["Ngân hàng"]
    assert s["count"] == 2
    assert s["gtgd"] == pytest.approx(120.0)
    assert s["buy_ratio"] == pytest.approx(0.625)


def test_live_sectors_skip_only_the_broken_quote():
    """File quote đọc được JSON nhưng là `null`/list, hoặc `volume` là chuỗi
    "1,234" ⇒ bỏ ĐÚNG mã đó; bảng Live Money Flow vẫn có ngành của mã tốt."""
    import pytest

    from dashboard.money_flow_tab import aggregate_live_sectors

    good = {"price": 30.0, "volume": 1_000_000,
            "bids": [{"volume": 300}], "asks": [{"volume": 100}]}
    sectors = {"AAA": "Ngân hàng", "BBB": "Ngân hàng",
               "NUL": "Xấu", "LST": "Xấu", "STR": "Xấu"}
    out = aggregate_live_sectors(
        {"AAA": good, "NUL": None, "LST": [1, 2], "BBB": dict(good, price=60_000),
         "STR": dict(good, volume="1,234")},
        sectors.__getitem__)

    assert set(out) == {"Ngân hàng"}
    s = out["Ngân hàng"]
    assert s["count"] == 2
    assert s["gtgd"] == pytest.approx(90.0)
    assert s["buy_ratio"] == pytest.approx(0.75)


def test_live_sector_price_unit_follows_warehouse_close():
    """Ngưỡng cứng `price > 500 ⇒ /1000`: quote nghìn của mã > 500 nghìn (HLB 660) bị chia
    còn 0.66, mã 300 đ quote VND 300 bị hiểu 300 nghìn ⇒ GTGD ngành lệch 1000×.
    Mốc đơn vị phải là close kho."""
    import pytest

    from dashboard.money_flow_tab import aggregate_live_sectors

    def q(price):
        return {"price": price, "volume": 1_000_000, "bids": [], "asks": []}

    out = aggregate_live_sectors(
        {"HLB": q(660.0), "AVF": q(300.0), "VCB": q(90_000), "NEW": q(25_000)},
        lambda tk: "X", ref_close={"HLB": 650.0, "AVF": 0.3, "VCB": 89.0})
    assert out["X"]["gtgd"] == pytest.approx(660 + 0.3 + 90 + 25)   # NEW: chưa có kho ⇒ ngưỡng


# ── P3 (docs/THIET-KE-GIAO-DIEN.md §6): tiêu đề chuẩn + màu chỉ đi qua token ──

_HEX = r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?(?![0-9a-zA-Z])"


def _render_full_page(monkeypatch, tmp_path):
    """Trang đủ dữ liệu: 3 ngành ròng +/0/−, VCB có Lệnh lớn (kéo VÀO), Live Scan bật.
    Trả (st giả, các lần gọi ui.page_header/ui.section)."""
    import json
    import sys
    import types

    import pandas as pd

    from dashboard import ui
    from dashboard.money_flow_score import compute_money_flow_score
    from tests.test_tab_render_smoke import _fake_streamlit, _load

    st = _fake_streamlit()
    st.session_state.update(live_mode=True, live_scan=True)
    monkeypatch.setitem(sys.modules, "streamlit", st)

    prices = tmp_path / "prices"
    for tk in ("VCB", "HPG", "FPT"):
        (prices / f"ticker={tk}").mkdir(parents=True)
    m = _stub_mf_dashboard(prices)
    m._load_industry_map = lambda: {"VCB": "Ngân hàng", "HPG": "Thép & Kim loại",
                                    "FPT": "Công nghệ"}
    m._fetch_foreign_net_flow = lambda **k: pd.DataFrame({"symbol": ["VCB"]})
    m._aggregate_nn_by_window = lambda raw, days: {"VCB": 50.0, "HPG": 0.0, "FPT": -20.0}
    m._aggregate_nn_buy_sell_by_window = lambda raw, days: {
        "VCB": {"buy": 80.0, "sell": 30.0}, "HPG": {"buy": 10.0, "sell": 10.0},
        "FPT": {"buy": 5.0, "sell": 25.0}}
    m._compute_gtgd_by_window = lambda n: {"VCB": 500.0, "HPG": 200.0, "FPT": 300.0}
    m._batch_load_live_quotes = lambda tickers: {"FPT": {"price": 100.0, "volume": 1e6,
                                                         "buy_ratio": 0.3}}
    m._fetch_order_stats_batch = lambda tickers: {
        "VCB": {"buy_sell_ratio": 0.7, "big_order_score": 40}}
    m._compute_money_flow_score = compute_money_flow_score
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", m)

    # badge độ tươi là module ngoài trang (màu riêng, có test riêng) — tắt để chỉ soi trang
    fresh = types.ModuleType("vnstock_freshness")
    fresh.render_freshness_row = lambda items: None
    monkeypatch.setitem(sys.modules, "vnstock_freshness", fresh)

    calls: list = []
    real_page, real_section = ui.page_header, ui.section
    monkeypatch.setattr(ui, "page_header",
                        lambda *a, **k: (calls.append(("page", a)), real_page(*a, **k)))
    monkeypatch.setattr(ui, "section",
                        lambda *a, **k: (calls.append(("section", a)), real_section(*a, **k)))

    live = tmp_path / "data_warehouse" / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text(json.dumps({
        "price": 90.0, "volume": 1_000_000,
        "bids": [{"volume": 300}], "asks": [{"volume": 100}]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _load("dashboard.money_flow_tab").render_money_flow_tab()
    return st, calls


def _markdowns(st):
    return [str(c.args[0]) for c in st.markdown.call_args_list if c.args]


def test_page_uses_page_header_and_sections(monkeypatch, tmp_path):
    """Đầu trang = `ui.page_header("Dòng tiền", …khung đang chọn…)`, các mục = `ui.section`,
    không còn `###`/`####` kèm emoji; sidebar = nhãn mục gọn như mục Live."""
    st, calls = _render_full_page(monkeypatch, tmp_path)

    assert calls and calls[0][0] == "page"
    title, subtitle = calls[0][1]
    assert title == "Dòng tiền"
    assert "1D" in subtitle                      # st.radio giả chọn khung đầu tiên
    sections = [a[0] for kind, a in calls if kind == "section"]
    assert "Khối ngoại chi tiết" in sections
    assert "Dòng tiền trong phiên (live)" in sections

    mds = _markdowns(st)
    assert not [m for m in mds if m.lstrip().startswith("#")], "còn tiêu đề markdown thô"
    assert any('class="vn-side-label"' in m and "Dòng tiền" in m for m in mds)
    assert not any("💰" in m for m in mds)


def test_rendered_colors_are_theme_tokens(monkeypatch, tmp_path):
    """Mọi màu HTML của trang (thẻ KPI, bảng ngành, chi tiết mã, live, thanh điểm) đều là
    token — không còn #d1d5db/#4b5563/#0d1117/#6ee7b7…"""
    import re

    from dashboard.theme import TOKENS as T

    st, _ = _render_full_page(monkeypatch, tmp_path)
    html = "\n".join(_markdowns(st))

    # trang đã vẽ đủ các khối (không thì "0 hex lạ" là xanh suông)
    assert "Ngành có tiền VÀO" in html and "Áp lực" in html and "Vai trò" in html
    assert re.search(r"color:(#\w{6})[^>]*>★ Kéo VÀO", html).group(1) == T["up"]
    stray = set(re.findall(_HEX, html)) - set(T.values())
    assert not stray, f"hex ngoài token: {sorted(stray)}"


@needs("plotly")  # chart NN ròng theo ngành chỉ vẽ khi có plotly (thiếu thì rơi về bảng)
def test_sector_flow_chart_colors_are_theme_tokens(monkeypatch, tmp_path):
    """Chart Plotly NN ròng theo ngành: cột tăng/giảm, nền, chữ, lưới đều là token."""
    from dashboard.theme import PLOTLY_BG, TOKENS as T

    st, _ = _render_full_page(monkeypatch, tmp_path)
    fig = st.plotly_chart.call_args.args[0]
    # Ngân hàng +50 · Thép 0 · Công nghệ −20 (xếp giảm dần)
    assert list(fig.data[0].marker.color) == [T["up"], T["up"], T["down"]]
    assert fig.layout.paper_bgcolor == PLOTLY_BG["paper_bgcolor"]
    assert fig.layout.plot_bgcolor == PLOTLY_BG["plot_bgcolor"]
    assert {fig.layout.font.color, fig.layout.yaxis.gridcolor,
            fig.layout.yaxis.zerolinecolor} <= set(T.values())


def test_score_bar_uses_only_tokens_and_soft_shades():
    """Thanh điểm: nền rãnh, vạch giữa, nhãn — 5 mức đều là token."""
    import re

    from dashboard.money_flow_score import score_bar_html
    from dashboard.theme import TOKENS as T

    for score, shade in ((60, "up"), (20, "up_soft"), (0, "text_muted"),
                         (-20, "down_soft"), (-60, "down")):
        html = score_bar_html(score)
        assert set(re.findall(_HEX, html)) <= set(T.values()), score
        assert f'color:{T[shade]};' in html, score
