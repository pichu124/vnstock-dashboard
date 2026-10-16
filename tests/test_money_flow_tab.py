"""Smoke tests for dashboard.money_flow_tab.

Covers the import contract and signature only — the UI is exercised
manually, and the data-loading helpers (``_fetch_foreign_net_flow``,
``_fetch_order_stats_batch`` etc.) still live in ``vnstock_dashboard.py``
with their own tests in ``test_dashboard.py``.
"""

from __future__ import annotations

import inspect


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
