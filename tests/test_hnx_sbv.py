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


# ─── SBV parse + cross-source ───────────────────────────────────────────────

_SBV_TEXT = ("Bản tin hoạt động ngân hàng trong tuần. Lãi suất bình quân liên "
             "ngân hàng: Qua đêm 4,28%; 1 tuần 4,92%; 2 tuần 5,10%; 1 tháng "
             "5,45%. Tỷ giá trung tâm tham chiếu: 25.140 VND/USD. NHNN hút ròng "
             "12.500 tỷ đồng qua kênh OMO trong tuần.")


def test_sbv_parse():
    r = sbv.parse_sbv_text(_SBV_TEXT)
    assert r.overnight == 4.28 and r.one_week == 4.92 and r.one_month == 5.45
    assert r.fx_central == 25140.0 and r.omo_net == 12500.0        # hút = +


def test_sbv_parse_bom_is_negative():
    r = sbv.parse_sbv_text("NHNN bơm ròng 8.000 tỷ đồng qua OMO.")
    assert r.omo_net == -8000.0


def test_sbv_parse_empty():
    r = sbv.parse_sbv_text("")
    assert r.overnight is None and r.omo_net is None


def test_sbv_resolve_interbank():
    assert sbv.resolve_interbank_on(4.28, 4.30) == (4.28, "sbv", False)
    v, s, d = sbv.resolve_interbank_on(4.28, 6.00)
    assert v == 4.28 and s == "sbv" and d is True                  # lệch → cờ
    assert sbv.resolve_interbank_on(None, 4.30) == (4.30, "vbma", False)
    assert sbv.resolve_interbank_on(4.28, None) == (4.28, "sbv", False)
    assert sbv.resolve_interbank_on(None, None)[1] == "none"


@pytest.fixture()
def _sbv_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(sbv, "_META", tmp_path)
    return tmp_path


def test_sbv_refresh_merge_safe(_sbv_meta, monkeypatch):
    monkeypatch.setattr(sbv, "fetch_weekly", lambda **k: sbv.parse_sbv_text(_SBV_TEXT))
    c = sbv.refresh()
    assert c["overnight"] == 4.28 and c["omo_net"] == 12500.0
    # fetch sau chỉ có ON (thiếu OMO) → OMO cũ GIỮ (merge-safe)
    monkeypatch.setattr(sbv, "fetch_weekly",
                        lambda **k: sbv.SBVWeekly(overnight=4.10))
    c2 = sbv.refresh()
    assert c2["overnight"] == 4.10 and c2["omo_net"] == 12500.0
    assert sbv.load_interbank_on() == 4.10 and sbv.load_omo_net() == 12500.0


def test_sbv_set_omo_manual(_sbv_meta):
    sbv.set_omo(-5000.0)
    assert sbv.load_omo_net() == -5000.0


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


def test_push_rates_weekly_empty_cache_guarded(monkeypatch):
    import vnstock_telegram as tg
    monkeypatch.setattr("vnstock_rates_report.build_report_data",
                        lambda *a, **k: {"rates": [], "curve": None})
    res = tg.push_rates_weekly()
    assert res["ok"] is False and "rỗng" in res["error"]


# ─── SBV link-finder (nới sau khi --diag thật trượt regex cũ 16/07) ─────────

def test_sbv_find_article_link_multiple_shapes():
    html = ('<a href="/vi/web/sbv_portal/thong-tin-ve-hoat-dong-ngan-hang-trong-tuan">L</a>'
            '<a href="/vi/web/sbv_portal/w/thong-tin-hoat-dong-ngan-hang-tuan-07-11072026">B</a>')
    assert sbv._find_article_link(html) == \
        "/vi/web/sbv_portal/w/thong-tin-hoat-dong-ngan-hang-tuan-07-11072026"
    # chỉ có link listing → None (không tự trỏ về chính nó)
    only = '<a href="/vi/web/sbv_portal/thong-tin-ve-hoat-dong-ngan-hang-trong-tuan">x</a>'
    assert sbv._find_article_link(only) is None
    # dạng .htm
    htm = '<a href="/vi/web/ban-tin-kinh-te-tuan-4-thang-7-2026.htm">x</a>'
    assert sbv._find_article_link(htm) == "/vi/web/ban-tin-kinh-te-tuan-4-thang-7-2026.htm"


def test_sbv_candidate_links_for_diag():
    html = ('<a href="/vi/web/sbv_portal/w/bai-tuan-1">a</a>'
            '<a href="/vi/web/khac/gioi-thieu">b</a>'
            '<a href="/vi/web/sbv_portal/ban-tin-tuan-2.htm">c</a>')
    cands = sbv._candidate_links(html)
    assert "/vi/web/sbv_portal/w/bai-tuan-1" in cands
    assert "/vi/web/sbv_portal/ban-tin-tuan-2.htm" in cands
    assert "/vi/web/khac/gioi-thieu" not in cands        # không có từ khoá bài
    assert sbv._candidate_links("<p>JS app, no links</p>") == []
