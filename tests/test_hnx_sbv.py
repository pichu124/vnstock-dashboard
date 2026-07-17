"""Tests cho vnstock_hnx (yield curve HNX) + vnstock_sbv (bản tin tuần SBV)
+ wiring vào vnstock_macro. Khảo sát baocaolaisuatvatiente 2026-07-16.
Hermetic — fetch mạng đều fake, cache ghi tmp_path."""

from __future__ import annotations

import json
from datetime import date

import pytest

import vnstock_hnx as hnx
import vnstock_sbv as sbv


_HNX_HTML = """<html><body><table id="_tableDatas"><tbody>
<tr><td>1 năm</td><td>3,20</td><td>3,25</td></tr>
<tr><td>2 năm</td><td>3,45</td><td>3,50</td></tr>
<tr><td>5 năm</td><td>4,10</td><td>4,15</td></tr>
<tr><td>10 năm</td><td>4,38</td><td>4,40</td></tr>
<tr><td>15 năm</td><td>4,60</td><td>4,65</td></tr>
<tr><td>20 năm</td><td>4,80</td><td>4,85</td></tr>
</tbody></table></body></html>"""


# ─── HNX parse ───────────────────────────────────────────────────────────────

def test_hnx_parse_yield_curve():
    r = hnx.parse_yield_curve_html(_HNX_HTML)
    assert r["2Y"] == 3.5 and r["10Y"] == 4.4
    assert r["15Y"] == 4.65 and "5Y" in r and r["5Y"] == 4.15   # 15 không nhầm 5
    assert set(r) == {"1Y", "2Y", "5Y", "10Y", "15Y", "20Y"}


def test_hnx_parse_guards():
    assert hnx.parse_yield_curve_html("") == {}
    assert hnx.parse_yield_curve_html("<p>không có bảng</p>") == {}
    # giá trị ngoài [0.1,15] bị loại
    bad = _HNX_HTML.replace("4,38</td><td>4,40", "99,0</td><td>99,9")
    assert "10Y" not in hnx.parse_yield_curve_html(bad)
    assert hnx._vn_float("4,40") == 4.4 and hnx._vn_float("-") is None


# ─── HNX refresh + cache + loaders (fetch fake) ─────────────────────────────

@pytest.fixture()
def _hnx_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(hnx, "_META", tmp_path)
    return tmp_path


def test_hnx_refresh_and_load(_hnx_meta, monkeypatch):
    monkeypatch.setattr(hnx, "fetch_latest",
                        lambda *a, **k: (date(2026, 7, 15),
                                         hnx.parse_yield_curve_html(_HNX_HTML)))
    got = hnx.refresh()
    assert got["2Y"] == 3.5
    loaded = hnx.load_yields()
    assert loaded[0] == "2026-07-15" and loaded[1]["10Y"] == 4.4
    assert hnx.yield_on("2Y") == 3.5
    assert hnx.yield_on("10Y", as_of="2026-07-15") == 4.4
    # as_of trước phiên → None
    assert hnx.load_yields(as_of="2026-07-01") is None


def test_hnx_refresh_none_keeps_cache(_hnx_meta, monkeypatch):
    monkeypatch.setattr(hnx, "fetch_latest",
                        lambda *a, **k: (date(2026, 7, 15), {"2Y": 3.5}))
    hnx.refresh()
    monkeypatch.setattr(hnx, "fetch_latest", lambda *a, **k: None)   # fetch fail
    assert hnx.refresh() is None
    assert hnx.load_yields()[1]["2Y"] == 3.5        # cache cũ còn nguyên


def test_hnx_kill_switch(_hnx_meta, monkeypatch):
    monkeypatch.setenv("VNSTOCK_HNX", "0")
    monkeypatch.setattr(hnx, "fetch_latest", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("không được fetch khi tắt")))
    assert hnx.refresh() is None


def test_hnx_prune_keeps_recent(_hnx_meta, monkeypatch):
    monkeypatch.setattr(hnx, "_RETAIN_DATES", 2)
    for i, d in enumerate(("2026-07-10", "2026-07-11", "2026-07-14")):
        monkeypatch.setattr(hnx, "fetch_latest",
                            lambda *a, _d=d, _i=i, **k: (date.fromisoformat(_d),
                                                         {"2Y": 3.0 + _i}))
        hnx.refresh()
    hist = json.loads((_hnx_meta / "hnx_yields.json").read_text())["history"]
    assert set(hist) == {"2026-07-11", "2026-07-14"}     # giữ 2 gần nhất


# ─── SBV parse + cross-source (fixture = TEXT THẬT bản tin 06-10.7.2026) ────

# Trích text PDF thật (dump 16/07): bảng lãi suất bình quân + câu tường thuật
# BẪY ("giảm 0,03%/năm" = mức thay đổi USD) + số doanh số (không phải OMO).
_SBV_REAL = (
    "DIỄN BIẾN THỊ TRƯỜNG NGOẠI TỆ VÀ THỊ TRƯỜNG LIÊN NGÂN HÀNG (Tuần từ 06-10.7.2026)\n"
    "doanh số giao dịch trên thị trường liên ngân hàng trong tuần bằng VND đạt "
    "xấp xỉ 4.428.576 tỷ đồng, bình quân 885.715 tỷ đồng/ngày.\n"
    "- Đối với các giao dịch bằng VND: ... kỳ hạn qua đêm, 01 tuần và 01 tháng "
    "giảm lần lượt 2,02%/năm, 1,24%/năm và 0,46%/năm xuống các mức 5,21%/năm, "
    "5,57%/năm và 7,32%/năm.\n"
    "- Đối với các giao dịch bằng USD: ... kỳ hạn qua đêm giảm 0,03%/năm xuống "
    "mức 3,62%/năm ...\n"
    " Qua đêm 1 tuần 2 tuần 1 tháng 3 tháng 6 tháng 9 tháng\n"
    "VND 5,21 5,57 6,13 7,32 7,76 8,64 -\n"
    "USD 3,62 3,66 3,70 3,84 3,86 - -\n")


def test_sbv_parse_real_table():
    r = sbv.parse_sbv_text(_SBV_REAL)
    # lấy ĐÚNG từ bảng VND, KHÔNG nhầm 0,03 (USD change) hay doanh số
    assert r.overnight == 5.21 and r.one_week == 5.57
    assert r.two_week == 6.13 and r.one_month == 7.32
    assert r.overnight != 0.03                             # không bắt USD change
    # bản tin FX/LNH này KHÔNG có tỷ giá trung tâm / OMO → None (đúng)
    assert r.fx_central is None and r.omo_net is None


def test_sbv_omo_requires_net_context():
    # 'hút ròng'/'bơm ròng ... OMO' → bắt; doanh số 'VND đạt 4.428.576 tỷ' → bỏ
    assert sbv.parse_sbv_text("NHNN hút ròng 12.500 tỷ đồng qua kênh OMO.").omo_net == 12500.0
    assert sbv.parse_sbv_text("NHNN bơm ròng 8.000 tỷ đồng qua OMO.").omo_net == -8000.0
    assert sbv.parse_sbv_text("doanh số bằng VND đạt 4.428.576 tỷ đồng.").omo_net is None


def test_sbv_parse_empty():
    r = sbv.parse_sbv_text("")
    assert r.overnight is None and r.omo_net is None


def test_sbv_table_ignores_transaction_volume_line():
    # dòng doanh số 'bằng VND đạt 4.428.576 tỷ' KHÔNG được đọc thành bảng lãi suất
    assert sbv._parse_interbank_table(
        "doanh số bằng VND đạt 4.428.576 tỷ đồng, bình quân 885.715 tỷ") is None


def test_sbv_table_requires_interbank_header():
    # REGRESSION cache nhiễm 16/07: bản tin SBV KHÁC (huy động/cho vay) cũng có
    # dòng 'VND <số>…' nhưng header là kỳ hạn TIỀN GỬI, không có 'Qua đêm'
    # → phải bị loại (trước đây parse ra 4,26/7,34/7,76 đè cache).
    deposit_style = ("Lãi suất huy động bình quân\n"
                     " Không kỳ hạn 1 tháng 3 tháng 6 tháng 12 tháng\n"
                     "VND 4,26 7,34 7,76 7,32 8,10\n")
    assert sbv._parse_interbank_table(deposit_style) is None
    assert sbv.parse_sbv_text(deposit_style).overnight is None
    # bảng LNH thật (có header 'Qua đêm') vẫn parse bình thường
    assert sbv._parse_interbank_table(_SBV_REAL) == (5.21, 5.57, 6.13, 7.32)


def test_sbv_single_slug_fx_interbank_only():
    # slug bản tin 'thông tin hoạt động ngân hàng' đã GỠ (nguồn nhiễm cache)
    assert len(sbv._SBV_TITLE_SLUGS) == 1
    assert "liên-ngân-hàng" in sbv._SBV_TITLE_SLUGS[0]


def test_sbv_resolve_interbank():
    # User chốt 17/07 "luôn cập nhật nhất": cùng tuần / thiếu as_of → VBMA
    # (điểm cuối tuần sát hơn TB tuần); tuần data MỚI hơn thắng bất kể nguồn.
    assert sbv.resolve_interbank_on(4.28, 4.30) == (4.30, "vbma", False)
    v, s, d = sbv.resolve_interbank_on(5.21, 4.28)
    assert v == 4.28 and s == "vbma" and d is True                 # lệch → cờ vẫn bật
    # SBV có tuần data MỚI hơn → SBV thắng (cờ lệch giữ nguyên)
    v, s, d = sbv.resolve_interbank_on(5.21, 4.28,
                                       sbv_as_of="2026-07-17", vbma_as_of="2026-07-10")
    assert v == 5.21 and s == "sbv" and d is True
    # VBMA mới hơn / cùng ngày → VBMA
    assert sbv.resolve_interbank_on(5.21, 4.28, sbv_as_of="2026-07-10",
                                    vbma_as_of="2026-07-17")[1] == "vbma"
    assert sbv.resolve_interbank_on(5.21, 4.28, sbv_as_of="2026-07-10",
                                    vbma_as_of="2026-07-10")[1] == "vbma"
    # thiếu 1 nguồn → dùng nguồn kia (như cũ)
    assert sbv.resolve_interbank_on(None, 4.30) == (4.30, "vbma", False)
    assert sbv.resolve_interbank_on(4.28, None) == (4.28, "sbv", False)
    assert sbv.resolve_interbank_on(None, None)[1] == "none"


@pytest.fixture()
def _sbv_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(sbv, "_META", tmp_path)
    return tmp_path


def test_sbv_refresh_merge_safe(_sbv_meta, monkeypatch):
    # lần 1: có ON (5.21) + OMO (set tay giả lập)
    monkeypatch.setattr(sbv, "fetch_weekly",
                        lambda **k: sbv.SBVWeekly(overnight=5.21, omo_net=12500.0))
    c = sbv.refresh()
    assert c["overnight"] == 5.21 and c["omo_net"] == 12500.0
    # fetch sau chỉ có ON (thiếu OMO) → OMO cũ GIỮ (merge-safe)
    monkeypatch.setattr(sbv, "fetch_weekly",
                        lambda **k: sbv.SBVWeekly(overnight=4.10))
    c2 = sbv.refresh()
    assert c2["overnight"] == 4.10 and c2["omo_net"] == 12500.0
    assert sbv.load_interbank_on() == 4.10 and sbv.load_omo_net() == 12500.0


def test_sbv_set_omo_manual(_sbv_meta):
    sbv.set_omo(-5000.0)
    assert sbv.load_omo_net() == -5000.0


def test_sbv_refresh_as_of_is_data_week_not_fetch_date(_sbv_meta, monkeypatch):
    # as_of cache = thứ 6 TUẦN DATA của bản tin (data_date), KHÔNG phải hôm nay
    monkeypatch.setattr(sbv, "fetch_weekly",
                        lambda **k: sbv.SBVWeekly(overnight=5.21,
                                                  week_end="2026-07-10"))
    c = sbv.refresh()
    assert c["as_of"] == "2026-07-10" and c["week_end"] == "2026-07-10"
    # fetch_weekly không mang week_end (test/fake cũ) → fallback hôm nay
    monkeypatch.setattr(sbv, "fetch_weekly",
                        lambda **k: sbv.SBVWeekly(overnight=5.30))
    from datetime import datetime as _dt
    assert sbv.refresh()["as_of"] == _dt.now().date().isoformat()


def test_sbv_fetch_weekly_carries_week_end(monkeypatch):
    import requests

    class _R:
        def __init__(self, status=200, text="", content=b""):
            self.status_code, self.text, self.content = status, text, content

    def fake_get(url, **k):
        if "/documents/" in url:
            return _R(200, content=b"%PDF-fake")
        if "/w/" in url:
            return _R(200, text='<a href="/documents/20117/0/sbv.pdf/u-1">PDF</a>')
        return _R(404)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("vnstock_vbma.pdf_to_text", lambda d: _SBV_REAL)
    monkeypatch.setattr(sbv, "_REQUEST_GAP_S", 0)
    r = sbv.fetch_weekly()
    # tuần đầu thử = tuần TRƯỚC tuần hiện tại → week_end là 1 ngày thứ 6 ISO
    assert r.week_end and len(r.week_end) == 10
    from datetime import date
    assert date.fromisoformat(r.week_end).weekday() == 4


# ─── Wiring vào vnstock_macro ────────────────────────────────────────────────

def test_macro_prefers_hnx_over_vbma_for_yields(monkeypatch):
    import vnstock_macro as mac
    monkeypatch.setattr(mac, "_fetch_hnx",
                        lambda: {"govt_bond_yield_2y": 3.5,
                                 "govt_bond_yield_10y": 4.4, "as_of": "2026-07-15"})
    cache = {}
    # giả lập VBMA đã ghi 2Y=3.9 rồi HNX ghi đè 3.5
    mac._record(cache, "govt_bond_yield_2y", 3.9, "2026-07-10", "vbma")
    hx = mac._fetch_hnx()
    for key in ("govt_bond_yield_2y", "govt_bond_yield_10y"):
        if hx.get(key) is not None:
            mac._record(cache, key, float(hx[key]), hx["as_of"], "hnx")
    ind = cache["indicators"]["govt_bond_yield_2y"]
    assert ind["history"]["2026-07-15"] == 3.5      # HNX ghi đè giá trị mới
    assert ind["source"] == "hnx"


def test_macro_fetch_hnx_best_effort(monkeypatch):
    import vnstock_macro as mac
    import sys
    monkeypatch.setitem(sys.modules, "vnstock_hnx", None)     # import lỗi
    assert mac._fetch_hnx() is None
    assert mac._fetch_sbv() is None


# ─── SBV daily (headless-delivery — LNH theo ngày, verify thật 17/07) ────────

import vnstock_sbv_rates as sbvd


def _cf(name, data, nested=None):
    return {"name": name, "contentFieldValue": {"data": data},
            "nestedContentFields": nested or []}


def _tenor_row(thoihan, rate, vol, foot=""):
    return _cf("laiSuatThiTruongNganHangs", None, [
        _cf("thoihan", thoihan), _cf("laiSuatBQLienNganHang", rate),
        _cf("doanhSo", vol), _cf("footNode", foot),
        _cf("noiDungFootNode", "Tham chiếu ngày 01/7" if foot else ""),
    ])


# Fixture dựng từ JSON THẬT probe-api 17/07 (structure 3450260)
_SBVD_JSON = {"totalCount": 3112, "items": [
    {"title": "Lãi suất...", "datePublished": "2026-07-15T21:37:00Z",
     "contentFields": [
         _cf("ngayApDung", "2026-07-14T17:00:00Z"), _cf("ghiChu", ""),
         _tenor_row("Qua đêm", "4,16", "887615"),
         _tenor_row("1 Tuần", "4,74", "10545"),
         _tenor_row("9 Tháng", "9,26", "230", foot="(*)"),   # số tham chiếu cũ
     ]},
    {"title": "Lãi suất...", "datePublished": "2026-07-14T21:53:00Z",
     "contentFields": [
         _cf("ngayApDung", "2026-07-13T17:00:00Z"), _cf("ghiChu", ""),
         _tenor_row("Qua đêm", "4,18", "890315"),
         _tenor_row("1 Tuần", "4,78", "14055"),
     ]},
]}


def test_sbv_daily_vn_date():
    # midnight VN serialize thành 17:00Z hôm TRƯỚC → phải +7h (bẫy data thật)
    assert sbvd._vn_date("2026-07-14T17:00:00Z") == "2026-07-15"
    assert sbvd._vn_date("rác") is None and sbvd._vn_date("") is None


def test_sbv_daily_parse_items():
    entries = sbvd.parse_items(_SBVD_JSON)
    assert [e["date"] for e in entries] == ["2026-07-15", "2026-07-14"]
    assert entries[0]["rates"] == {"on": 4.16, "1w": 4.74}   # 9m stale bị LOẠI
    assert "9m" not in entries[0]["rates"]
    assert entries[0]["volumes"]["on"] == 887615.0
    assert entries[1]["rates"]["on"] == 4.18
    assert sbvd.parse_items({}) == [] and sbvd.parse_items({"items": []}) == []


@pytest.fixture()
def _sbvd_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(sbvd, "_META", tmp_path)
    return tmp_path


def test_sbv_daily_refresh_merge_prune_loaders(_sbvd_meta, monkeypatch):
    monkeypatch.setattr(sbvd, "fetch_daily",
                        lambda **k: sbvd.parse_items(_SBVD_JSON))
    c = sbvd.refresh()
    assert c["as_of"] == "2026-07-15" and len(c["history"]) == 2
    # same-date replace + prune
    monkeypatch.setattr(sbvd, "_RETAIN_DATES", 2)
    monkeypatch.setattr(sbvd, "fetch_daily", lambda **k: [
        {"date": "2026-07-16", "rates": {"on": 4.10}, "volumes": {}}])
    c2 = sbvd.refresh()
    assert c2["as_of"] == "2026-07-16" and len(c2["history"]) == 2
    assert "2026-07-13" not in c2["history"]                 # ngày cũ nhất bị prune
    # loaders: as_of filter + rate_on
    assert sbvd.load_rates()[0] == "2026-07-16"
    assert sbvd.load_rates(as_of="2026-07-15") == ("2026-07-15",
                                                   {"on": 4.16, "1w": 4.74})
    assert sbvd.rate_on("on") == 4.10
    # fetch lỗi → giữ cache cũ, trả None
    monkeypatch.setattr(sbvd, "fetch_daily", lambda **k: [])
    assert sbvd.refresh() is None
    assert sbvd.load_rates()[0] == "2026-07-16"


def test_sbv_daily_kill_switch(monkeypatch):
    monkeypatch.setenv("VNSTOCK_SBV_DAILY", "0")
    assert sbvd.fetch_page() is None


def _policy_row(loai, gia_tri, qd="1123/QĐ-NHNN ngày 16/06/2023"):
    return _cf("banglaiSuats", None, [
        _cf("loaiLaiSuat", loai), _cf("giaTri", gia_tri),
        _cf("vanBanQuyetDinh", qd),
    ])


# Fixture từ JSON THẬT probe-api 3450482 (17/07) — ngayApDung SAI THÁNG
# (2023-03-18T17:00Z = 19/03 VN) trong khi title "19-06-2023" mới đúng.
_SBVD_POLICY_JSON = {"totalCount": 1, "items": [{
    "title": "19-06-2023", "datePublished": "2025-10-26T18:37:00Z",
    "contentFields": [
        _cf("ngayApDung", "2023-03-18T17:00:00Z"),
        _policy_row("Lãi suất tái chiết khấu", "3,000%"),
        _policy_row("Lãi suất tái cấp vốn", "4,500%"),
    ]}]}


def test_sbv_policy_parse_title_wins_over_wrong_ngayapdung():
    p = sbvd.parse_policy_items(_SBVD_POLICY_JSON)
    assert p["as_of"] == "2023-06-19"            # title thắng field sai tháng
    assert p["refinancing"] == 4.5 and p["discount"] == 3.0   # '4,500%' = 4.5
    assert "1123/QĐ-NHNN" in p["decision"]


def test_sbv_policy_fallback_ngayapdung_when_title_unparseable():
    bad = json.loads(json.dumps(_SBVD_POLICY_JSON))
    bad["items"][0]["title"] = "Lãi suất NHNN quy định"
    p = sbvd.parse_policy_items(bad)
    assert p["as_of"] == "2023-03-19"            # fallback +7h từ ngayApDung
    # thiếu tái cấp vốn → None (refinancing là trường bắt buộc cho registry)
    bad["items"][0]["contentFields"] = [
        _cf("ngayApDung", "2023-03-18T17:00:00Z"),
        _policy_row("Lãi suất tái chiết khấu", "3,000%"),
    ]
    assert sbvd.parse_policy_items(bad) is None


def test_sbv_policy_refresh_and_loader(_sbvd_meta, monkeypatch):
    monkeypatch.setattr(sbvd, "fetch_page",
                        lambda **k: _SBVD_POLICY_JSON)
    p = sbvd.refresh_policy()
    assert p["refinancing"] == 4.5
    assert sbvd.load_policy()["as_of"] == "2023-06-19"
    # fetch lỗi → giữ cache cũ, trả None
    monkeypatch.setattr(sbvd, "fetch_page", lambda **k: None)
    assert sbvd.refresh_policy() is None
    assert sbvd.load_policy()["refinancing"] == 4.5


def test_macro_fetch_sbv_policy(monkeypatch):
    import sys
    import types
    import vnstock_macro as mac
    fake = types.SimpleNamespace(refresh_policy=lambda **k: {
        "as_of": "2023-06-19", "refinancing": 4.5, "discount": 3.0})
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", fake)
    assert mac._fetch_sbv_policy()["refinancing"] == 4.5
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", None)
    assert mac._fetch_sbv_policy() is None


def test_macro_fetch_sbv_daily(monkeypatch):
    import sys
    import types
    import vnstock_macro as mac
    fake = types.SimpleNamespace(refresh=lambda **k: {
        "as_of": "2026-07-15",
        "history": {"2026-07-15": {"on": 4.16, "1w": 4.74}}})
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", fake)
    got = mac._fetch_sbv_daily()
    assert got == {"interbank_on": 4.16, "interbank_1w": 4.74,
                   "as_of": "2026-07-15"}
    # import lỗi / refresh None → best-effort None
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", None)
    assert mac._fetch_sbv_daily() is None


def test_macro_drop_reading(tmp_path, monkeypatch):
    # cache surgery: xóa entry sai ngày (tàn dư vụ SBV 16-17/07) → registry
    # đọc lại entry đúng còn lại; key lạ → KeyError; ngày không có → False
    import vnstock_macro as mac
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro_indicators.json")
    cache = {}
    mac._record(cache, "interbank_on", 4.28, "2026-07-10", "vbma")
    mac._record(cache, "interbank_on", 5.21, "2026-07-17", "sbv")   # sai ngày
    mac._save_cache(cache)
    assert mac.drop_reading("interbank_on", "2026-07-17") is True
    hist = (mac._load_cache()["indicators"]["interbank_on"]["history"])
    assert list(hist) == ["2026-07-10"] and hist["2026-07-10"] == 4.28
    assert mac.drop_reading("interbank_on", "2026-07-17") is False  # đã sạch
    import pytest as _pt
    with _pt.raises(KeyError):
        mac.drop_reading("khong_ton_tai", "2026-07-10")


# ─── Báo cáo tuần lãi suất (vnstock_rates_report) — hướng A + B ─────────────

import vnstock_rates_report as rr

_RPT_DATA = {
    "as_of": "2026-07-15", "week_label": "Tuần 29/2026",
    "rates": [
        {"key": "interbank_on", "label": "LNH qua đêm", "value": "4.28%/năm",
         "as_of": "2026-07-10", "source": "sbv", "change": "▼ -1.39 điểm %", "dir": -1},
        {"key": "govt_bond_yield_10y", "label": "TPCP 10 năm", "value": "4.40%/năm",
         "as_of": "2026-07-15", "source": "hnx", "change": "", "dir": 0}],
    "gauges": [{"name": "Thanh khoản hệ thống", "spread": -0.22,
                "label": "bình thường", "dir": 0}],
    "curve": {"as_of": "2026-07-15",
              "points": [("1Y", 3.25), ("2Y", 3.50), ("5Y", 4.15),
                         ("10Y", 4.40), ("15Y", 4.65), ("20Y", 4.85)]},
    "omo_net": 12500.0, "fx_central": 25140.0,
    "narrative": ["Thanh khoản hệ thống: bình thường (-0.22 điểm %).",
                  "NHNN hút ròng 12,500 tỷ đồng qua kênh OMO trong tuần."],
}


def test_render_html_self_contained_with_svg():
    h = rr.render_html(_RPT_DATA)
    assert h.strip().lower().startswith("<!doctype html>")
    assert "http://" not in h and "https://" not in h        # zero external dep
    assert "<svg" in h and "polyline" in h                    # đường cong TPCP
    assert "LNH qua đêm" in h and "4.28%/năm" in h
    assert "hút ròng 12,500" in h
    # background TƯỜNG MINH — nhúng iframe dashboard nền tối, transparent là
    # chữ tối tàng hình (bug thật 17/07)
    assert "background:#ffffff" in h


def test_macro_dense_history(monkeypatch):
    # chart LNH/TPCP phải đọc cache nguồn THEO NGÀY (registry chỉ vài mốc);
    # helper nằm ở vnstock_macro (zero streamlit) — macro_tab chỉ gọi lại
    import sys
    import types
    import vnstock_macro as mac
    fake_sbvd = types.SimpleNamespace(_load_cache=lambda: {"history": {
        "2026-07-14": {"on": 4.18, "1w": 4.78},
        "2026-07-15": {"on": 4.16},                      # thiếu 1w → bỏ qua key đó
    }})
    fake_hnx = types.SimpleNamespace(_load_cache=lambda: {"history": {
        "2026-07-17": {"2Y": 3.94, "10Y": 4.34}}})
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", fake_sbvd)
    monkeypatch.setitem(sys.modules, "vnstock_hnx", fake_hnx)
    assert mac.dense_history("interbank_on") == {"2026-07-14": 4.18,
                                                 "2026-07-15": 4.16}
    assert mac.dense_history("interbank_1w") == {"2026-07-14": 4.78}
    assert mac.dense_history("govt_bond_yield_10y") == {"2026-07-17": 4.34}
    assert mac.dense_history("usdvnd") == {}             # chỉ số khác → registry
    monkeypatch.setitem(sys.modules, "vnstock_sbv_rates", None)   # import lỗi
    assert mac.dense_history("interbank_on") == {}       # best-effort
    # macro_tab phải dùng đúng helper này (đọc source — không import streamlit)
    src = (__import__("pathlib").Path(__file__).resolve().parent.parent
           / "dashboard" / "macro_tab.py").read_text(encoding="utf-8")
    assert "dense_history" in src


def test_render_telegram_compact():
    t = rr.render_telegram(_RPT_DATA)
    assert "Báo cáo tuần lãi suất" in t and "Tuần 29/2026" in t
    assert "LNH qua đêm" in t and "4.28%/năm" in t
    assert "2Y 3.50" in t and "10Y 4.40" in t                 # curve segment
    assert "hút ròng 12,500 tỷ" in t


def test_svg_empty_when_insufficient_points():
    assert rr._svg_yield_curve({"points": [("2Y", 3.5)]}) == ""
    assert rr._svg_yield_curve({"points": []}) == ""


def test_build_report_data_from_fake_caches(monkeypatch):
    import vnstock_macro as mac
    fake_macro = [
        {"key": "interbank_on", "label": "LNH ON", "unit": "%/năm", "kind": "rate",
         "value": 4.28, "as_of": "2026-07-10", "source": "sbv",
         "change": {"delta": -1.39, "pct": None, "dir": -1}},
        {"key": "govt_bond_yield_10y", "label": "TPCP 10Y", "unit": "%/năm",
         "kind": "rate", "value": 4.40, "as_of": "2026-07-15", "source": "hnx",
         "change": None},
    ]
    monkeypatch.setattr(mac, "load_macro", lambda *a, **k: fake_macro)
    monkeypatch.setattr(mac, "liquidity_spread",
                        lambda m: {"spread": -0.22, "label": "bình thường", "dir": 0})
    monkeypatch.setattr(mac, "term_spread", lambda m: None)
    monkeypatch.setattr(mac, "intl_spread", lambda m: None)
    import vnstock_hnx
    monkeypatch.setattr(vnstock_hnx, "load_yields",
                        lambda *a, **k: ("2026-07-15", {"2Y": 3.5, "10Y": 4.4}))
    import vnstock_sbv
    monkeypatch.setattr(vnstock_sbv, "load_weekly",
                        lambda: {"omo_net": 12500.0, "fx_central": 25140.0})
    d = rr.build_report_data("2026-07-15")
    assert d["week_label"] == "Tuần 29/2026"
    assert any(r["source"] == "hnx" for r in d["rates"])
    assert d["curve"]["points"][0] == ("2Y", 3.5)
    assert d["omo_net"] == 12500.0
    # narrative suy từ số: gauge + OMO + đổi LNH ON (|−1.39| ≥ 0.10)
    joined = " ".join(d["narrative"])
    assert "Thanh khoản" in joined and "hút ròng" in joined and "qua đêm" in joined
    # REGRESSION 17/07: không truyền as_of → "dữ liệu đến" = as_of MỚI NHẤT,
    # LOẠI sbv_policy_rate (as_of = ngày QUYẾT ĐỊNH 2023 kéo cả báo cáo về
    # "Tuần 25/2023" vì policy đứng đầu _RATE_KEYS)
    fake_macro.insert(0, {"key": "sbv_policy_rate", "label": "Tái cấp vốn",
                          "unit": "%/năm", "kind": "rate", "value": 4.5,
                          "as_of": "2023-06-19", "source": "sbv_portal",
                          "change": None})
    d2 = rr.build_report_data()
    assert d2["as_of"] == "2026-07-15" and d2["week_label"] == "Tuần 29/2026"


def test_push_rates_weekly_empty_cache_guarded(monkeypatch):
    import vnstock_telegram as tg
    monkeypatch.setattr("vnstock_rates_report.build_report_data",
                        lambda *a, **k: {"rates": [], "curve": None})
    res = tg.push_rates_weekly()
    assert res["ok"] is False and "rỗng" in res["error"]


# ─── SBV fetch dựng URL từ ngày (listing là JS — verify thật 16/07) ─────────

def test_sbv_week_date_slug():
    from datetime import date
    # ngày zero-pad, THÁNG không pad, năm đầy đủ
    assert sbv._week_date_slug(date(2026, 6, 1), date(2026, 6, 5)) == "01-05.6.2026"
    assert sbv._week_date_slug(date(2026, 12, 28), date(2027, 1, 1)) == "28-01.12.2026"


def test_sbv_candidate_article_urls():
    from datetime import date
    urls = sbv._candidate_article_urls(date(2026, 6, 1), date(2026, 6, 5))
    assert len(urls) == len(sbv._SBV_TITLE_SLUGS)
    assert all(u.startswith("https://www.sbv.gov.vn/vi/web/sbv_portal/w/") for u in urls)
    # ngày slug đã URL-encode nằm trong URL (01-05.6.2026)
    assert all("01-05.6.2026" in __import__("urllib.parse").parse.unquote(u) for u in urls)


def test_sbv_fetch_weekly_date_constructed(monkeypatch):
    import requests

    class _R:
        def __init__(self, status=200, text="", content=b""):
            self.status_code, self.text, self.content = status, text, content

    tried = []

    def fake_get(url, **k):
        tried.append(url)
        if "/documents/" in url:
            return _R(200, content=b"%PDF-fake")
        if "/w/" in url:                                  # bài tuần → có PDF nhúng
            return _R(200, text='<a href="/documents/20117/0/sbv.pdf/uuid-9?t=1">PDF</a>')
        return _R(404)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("vnstock_vbma.pdf_to_text", lambda d: _SBV_REAL)
    monkeypatch.setattr(sbv, "_REQUEST_GAP_S", 0)     # test không ngủ né WAF
    r = sbv.fetch_weekly()
    assert r is not None and r.overnight == 5.21 and r.one_month == 7.32
    assert any("/w/" in u for u in tried) and any("/documents/" in u for u in tried)


def test_sbv_fetch_weekly_all_404_returns_none(monkeypatch):
    import requests

    class _R:
        status_code, text, content = 404, "", b""

    monkeypatch.setattr(requests, "get", lambda url, **k: _R())
    monkeypatch.setattr(sbv, "_REQUEST_GAP_S", 0)
    assert sbv.fetch_weekly(weeks_back=2) is None       # không bài nào → None sạch
