"""P2 tab "💱 Hàng hoá & Tiền tệ" (U83): số thuần `vnstock_assets_view` + render thử
`dashboard/assets_tab.py` bằng Streamlit giả trên kho tạm (conftest `_assets_hermetic_anywhere`).

Render thử chỉ trả lời "code có chạy hết không" (như `test_tab_render_smoke`) — mỗi mục Vàng/Dầu/USD
tự bắt lỗi rồi in `st.warning`, nên test soi đúng chỗ đó: không mục nào được rơi vào nhánh lỗi."""
from __future__ import annotations

import importlib
import sys
from datetime import date

import pandas as pd
import pytest

import vnstock_assets as va
import vnstock_assets_view as av

from tests.conftest import needs

TODAY = date(2026, 10, 10)            # thứ Bảy — vàng nội có giá, dầu/USD dừng ở thứ Sáu
T = "2026-10-10T09:00:00"


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


def _w(key, rows):
    va.write(key, rows, today=TODAY, fetched_at=T)


def _seed():
    days = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02",
            "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    _w("XAU", [va._row("2025-12-31", 4000.0, "finhay")]
       + [va._row(d, 4100.0 + 8 * i, "finhay", open=4090.0 + 8 * i, high=4120.0 + 8 * i,
                  low=4080.0 + 8 * i) for i, d in enumerate(days)])
    _w("USDVND", [va._row(d, 25800.0 + 8 * i, "yahoo") for i, d in enumerate(days)])
    sjc_days = ["2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-09", "2026-10-10"]
    _w("GOLD_SJC_BAR", [va._row(d, 144_000_000 + 100_000 * i, "finhay", bid=141_000_000 + 100_000 * i,
                                ask=144_000_000 + 100_000 * i) for i, d in enumerate(sjc_days)])
    for dealer in va.DEALERS:
        for kind, off in (("BAR", 0), ("RING", -500_000)):
            if (dealer, kind) == ("SJC", "BAR"):
                continue
            _w(f"GOLD_{dealer}_{kind}", [va._row("2026-10-10", 144_500_000 + off, "finhay",
                                                 bid=141_500_000 + off, ask=144_500_000 + off)])
    _w("BRENT", [va._row(d, 100.0 + 0.5 * i, "yahoo") for i, d in enumerate(days)])
    _w("WTI", [va._row(d, 90.0 + 0.2 * i, "yahoo") for i, d in enumerate(days)])
    for key, root, base_px in (("CURVE_BRENT", "BZ", 104.0), ("CURVE_WTI", "CL", 91.0)):
        rows = []
        for d, bump in (("2026-10-01", -1.0), ("2026-10-09", 0.0)):
            for j, m in enumerate(("Z26", "F27", "G27", "H27", "J27", "K27")):
                rows.append(va._row(d, base_px + bump - 1.5 * j, "yahoo", contract=f"{root}{m}"))
        _w(key, rows)
    _w("WTI_SPOT", [va._row("2026-10-06", 96.24, "fred")])
    _w("BRENT_SPOT", [va._row("2026-10-06", 125.44, "fred")])
    _w("DXY", [va._row(d, 102.0 + 0.05 * i, "yahoo") for i, d in enumerate(days)])
    _w("USD_BROAD", [va._row("2026-10-02", 121.38, "fred")])
    _w("USD_BROAD_EST", [va._row("2026-10-09", 121.23, "est")])
    _w("USD_CENTRAL", [va._row(d, 25620.0 + i, "mbk") for i, d in enumerate(days)])
    _w("USDVND_VCB", [va._row(d, 26050.0 + i, "vcb", bid=25690.0, ask=26050.0 + i) for i, d in enumerate(days)])
    _w("USD_SBV_REF", [va._row(d, 26850.0 + i, "ssi", bid=24390.0 + i, ask=26850.0 + i)
                       for i, d in enumerate(days)])
    va.update_status("python", {"run_at": "2026-10-10T09:00:00", "status": "ok"})
    va.update_status("mcp", {"run_at": "2026-10-10T09:05:00", "status": "ok"})
    va.update_status("estimates", {
        "USD_BROAD_EST": {"value": 121.23, "date": "2026-10-09", "anchor": 121.38,
                          "anchor_date": "2026-10-02", "h": 5, "band_pct": 0.3},
        "WTI_SPOT_EST": {"hidden": "ẩn: 4 phiên kể từ số EIA 2026-10-06 (> 3)"}})


# ── số thuần ────────────────────────────────────────────────────────────────
def test_changes_calendar_windows_and_missing_history():
    s = pd.Series([100.0, 110.0, 120.0, 121.0],
                  index=pd.to_datetime(["2025-12-31", "2026-09-30", "2026-10-02", "2026-10-09"]))
    c = av.changes(s)
    assert c["1 phiên"] == pytest.approx(0.83, abs=0.01)
    assert c["1 tuần"] == pytest.approx(0.83, abs=0.01)           # ≤ 02/10
    assert c["1 tháng"] == pytest.approx(21.0)                    # ≤ 09/09 ⇒ điểm 31/12
    assert c["YTD"] == pytest.approx(21.0)
    short = av.changes(pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-10-08", "2026-10-09"])))
    assert short["1 phiên"] == 100.0 and short["1 tuần"] is None and short["YTD"] is None
    assert set(av.changes(pd.Series(dtype=float)).values()) == {None}


def test_card_staleness_follows_market_calendar():
    _seed()
    gold = av.card("GOLD_SJC_BAR", today=TODAY)
    oil = av.card("BRENT", today=TODAY)
    assert gold["date"] == "2026-10-10" and not gold["stale"] and gold["ask"] == 144_500_000
    assert oil["age"] == 1 and not oil["stale"]                    # thứ Sáu, hôm nay thứ Bảy
    assert av.card("BRENT", today=date(2026, 10, 14))["stale"]     # 5 ngày > 3
    assert av.card("GOLD_SJC_BAR", today=date(2026, 10, 12))["stale"]   # vàng nội: > 1 ngày
    assert av.card("XAU", today=TODAY)["unit"] == "USD/oz" and av.card("GOLD_SJC_RING", today=TODAY)


def test_premium_uses_friday_world_price_on_weekend_and_drops_stale_join():
    _seed()
    p = av.premium_frame()
    world_fri = 4180.0 * 25880.0 * va.LUONG_OZ
    assert p.loc["2026-10-10", "world"] == pytest.approx(world_fri)        # T7 dùng số thứ Sáu
    assert p.loc["2026-10-10", "pct"] == pytest.approx((144_500_000 / world_fri - 1) * 100)
    _w("GOLD_SJC_BAR", [va._row("2026-10-20", 150_000_000, "finhay", ask=150_000_000)])
    assert "2026-10-20" not in p.index and pd.Timestamp("2026-10-20") not in av.premium_frame().index


def test_dealer_table_columns():
    _seed()
    t = av.dealer_table(today=TODAY)
    assert len(t) == 10
    pnj = t[(t["Đại lý"] == "PNJ") & (t["Loại"] == "nhẫn")].iloc[0]
    assert pnj["Bán"] == 144_000_000 and pnj["Bán − SJC miếng"] == -500_000
    assert pnj["Chênh mua–bán %"] == pytest.approx(3_000_000 / 144_000_000 * 100, abs=0.01)
    assert pnj["Chênh vs TG %"] == pytest.approx((144_000_000 / (4180 * 25880 * va.LUONG_OZ) - 1) * 100, abs=0.01)


def test_curve_snapshots_latest_and_week_ago():
    _seed()
    s = av.curve_snapshots("CURVE_BRENT", today=TODAY)
    d, pts = s["latest"]
    assert d == "2026-10-09" and [p[0] for p in pts][:2] == ["BZZ26", "BZF27"] and pts[0][2] == 104.0
    assert s["prior"][0] == "2026-10-01" and s["prior"][1][0][2] == 103.0
    assert av.curve_snapshots("CURVE_WTI", back_days=30, today=TODAY)["prior"] is None


def test_usd_band_and_spread():
    _seed()
    b = av.usd_band_frame()
    last = b.iloc[-1]
    assert last["ceiling"] == pytest.approx(last["central"] * 1.05) and last["sbv_sell"] == 26860.0
    sp = av.spread_series()
    assert sp.iloc[-1] == pytest.approx(105.0 - 92.0)


def test_fmt_value():
    assert av.fmt_value(144_800_000.0, "VND/lượng") == "144,800,000"
    assert av.fmt_value(4182.09, "USD/oz") == "4,182.09" and av.fmt_value(None, "VND") == "—"


# ── render thử bằng Streamlit giả ───────────────────────────────────────────
@pytest.fixture
def fake_st(monkeypatch):
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    sys.modules.pop("dashboard.assets_tab", None)
    mod = importlib.import_module("dashboard.assets_tab")
    monkeypatch.setattr(mod, "date", _FixedDate)
    monkeypatch.setattr(av, "date", _FixedDate)
    return st, mod


@needs("plotly")
def test_assets_tab_renders_every_section(fake_st):
    st, mod = fake_st
    _seed()
    mod.render_assets_tab()
    warned = [c.args for c in st.warning.call_args_list] + [c.args for c in st.error.call_args_list]
    assert warned == []                                            # không mục nào rơi vào nhánh lỗi
    assert st.plotly_chart.call_count >= 9                         # 3 vàng + đường cong + 2 dầu + 3 USD
    labels = [c.args[0] for c in st.metric.call_args_list]
    assert "SJC miếng đắt hơn vàng TG" in labels and "VCB bán còn cách trần" in labels
    captions = " ".join(str(c.args[0]) for c in st.caption.call_args_list)
    assert "ẩn: 4 phiên kể từ số EIA" in captions                  # lý do ẩn WTI giao ngay hiện ra
    assert "neo Fed 121.38" in captions


@needs("plotly")
def test_assets_tab_rerun_does_not_reread_store(monkeypatch):
    """Đổi radio/rerun không được đọc lại parquet (~47 lần `va.load`/lượt); kho có file mới ⇒ đọc
    lại. Streamlit giả biến `cache_data` thành hàm đồng nhất ⇒ ở đây thay bằng cache THẬT khoá theo
    tham số (trả bản sao như Streamlit) để soi đúng khoá làm tươi của tab."""
    import copy

    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()

    def _cache_data(*a, **k):
        def deco(f):
            memo = {}

            def wrapper(*args, **kw):
                key = repr((args, sorted(kw.items())))
                if key not in memo:
                    memo[key] = f(*args, **kw)
                return copy.deepcopy(memo[key])
            return wrapper
        return deco
    st.cache_data = _cache_data
    monkeypatch.setitem(sys.modules, "streamlit", st)
    sys.modules.pop("dashboard.assets_tab", None)
    mod = importlib.import_module("dashboard.assets_tab")
    monkeypatch.setattr(mod, "date", _FixedDate)
    monkeypatch.setattr(av, "date", _FixedDate)
    _seed()
    loads = []
    real_load = va.load
    monkeypatch.setattr(va, "load", lambda key, **kw: loads.append(key) or real_load(key, **kw))

    def render():
        st.metric.reset_mock()
        mod.render_assets_tab()
        assert not st.warning.called and not st.error.called
        return [(c.args, c.kwargs) for c in st.metric.call_args_list]

    first = render()
    n = len(loads)
    assert n > 0 and render() == first and len(loads) == n        # rerun: 0 lần đọc kho, số y hệt
    _w("DXY", [va._row("2026-10-09", 110.0, "yahoo")])
    loads.clear()
    third = render()
    assert loads and third != first                                 # kho đổi ⇒ đọc lại, số mới
    assert "110.00" in str(third)


def test_assets_tab_empty_store_tells_how_to_fill(fake_st):
    st, mod = fake_st
    mod.render_assets_tab()
    assert "Kho tài sản trống" in st.info.call_args.args[0]
    assert st.plotly_chart.call_count == 0


def test_tab_is_wired_into_navigation():
    src = open("vnstock_dashboard.py", encoding="utf-8").read()
    assert '"💱 Hàng hoá & Tiền tệ"' in src.split("_TAB_OPTIONS = ")[1].split("]")[0]
    assert 'if _active_tab == "💱 Hàng hoá & Tiền tệ":' in src and "render_assets_tab()" in src
    assert "🪙" not in src.split("_TAB_OPTIONS = ")[1].split("]")[0]     # ô vuông trên Windows 10 (10/10)


def test_no_dollar_sign_in_tab_text():
    """Streamlit đọc `$…$` trong markdown/caption thành công thức toán (10/10: chú thích đường cong
    "+1.50$ (+1.46%) · … +7.50$" vỡ thành khối mã) ⇒ tab ghi "USD", không dùng ký hiệu $."""
    src = open("dashboard/assets_tab.py", encoding="utf-8").read()
    assert "$" not in src


def test_agreement_table_dashes_when_no_common_day(monkeypatch):
    """Cặp chưa có ngày chung in "—", không in 0 (đọc nhầm thành "khớp tuyệt đối") hay None (10/10)."""
    monkeypatch.setattr(va, "agreement_all", lambda **kw: {
        "XAU": {"finhay~gold-api": {"n": 0, "window": 0, "bad": 0, "tol_pct": 0.8, "max_abs_pct": 0.0,
                                    "last": None, "status": "chưa đủ"}},
        "BRENT": {"finhay~yahoo": {"n": 5, "window": 5, "bad": 0, "tol_pct": 1.0, "max_abs_pct": 0.288,
                                   "last": {"date": "2026-10-09", "dev_pct": -0.288}, "status": "đạt"}}})
    df = av.agreement_table(today=date(2026, 10, 10))
    empty, ok = df.iloc[0], df.iloc[1]
    assert (empty["Lệch lớn nhất %"], empty["Lệch ngày cuối %"], empty["Ngưỡng %"]) == ("—", "—", "0.8")
    assert (ok["Lệch lớn nhất %"], ok["Lệch ngày cuối %"], ok["Lệch > ngưỡng / 5 phiên"]) == ("0.288", "-0.288", "0/5")
    assert "None" not in df.astype(str).to_string()


@pytest.mark.parametrize("stateful,expect", [
    (True, ["Dầu"]),                                  # streamlit có `on_change`: chỉ tab mở
    (False, ["Vàng", "Dầu", "USD", "Liên kết"]),      # bản cũ: chạy hết như trước
])
def test_assets_subtabs_run_only_open_tab_when_supported(fake_st, monkeypatch, stateful, expect):
    from tests.test_tab_render_smoke import _stateful_tabs
    st, mod = fake_st
    _seed()
    ran = []
    for fn, tag in (("_render_gold", "Vàng"), ("_render_oil", "Dầu"),
                    ("_render_usd", "USD"), ("_render_links", "Liên kết")):
        monkeypatch.setattr(mod, fn, lambda va_, av_, start, tag=tag: ran.append(tag))
    if stateful:
        st.tabs = _stateful_tabs(open_idx=1)

    mod.render_assets_tab()

    assert ran == expect
