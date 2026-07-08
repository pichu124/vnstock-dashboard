"""Tests for vnstock_vbma — VBMA weekly PDF parser + vnstock_macro wiring.

Fixture text mô phỏng layout `pdftotext -layout` của bản tin tuần VBMA
(song ngữ, số thập phân dấu phẩy). Khi có PDF thật, chạy
`python vnstock_vbma.py --diag --dump` trên máy có mạng và cập nhật fixture
nếu layout lệch.
"""
from __future__ import annotations

import pytest

import vnstock_macro as mac
import vnstock_vbma as vbma


_FIXTURE = """\
BẢN TIN THỊ TRƯỜNG TRÁI PHIẾU HÀNG TUẦN / WEEKLY BOND MARKET REPORT

I. LÃI SUẤT BÌNH QUÂN LIÊN NGÂN HÀNG (INTERBANK AVERAGE RATES)
   Kỳ hạn / Term            Lãi suất / Rate (%/năm)
   Qua đêm / ON                    4,52
   1 tuần / 1W                     4,75
   2 tuần / 2W                     4,90
   1 tháng / 1M                    5,10

II. LỢI SUẤT TRÁI PHIẾU CHÍNH PHỦ (GOVERNMENT BOND YIELDS)
   Kỳ hạn / Tenor            Lợi suất / Yield (%)
   5 năm / 5Y                      2,45
   10 năm / 10Y                    3,12
   15 năm / 15Y                    3,35

Giao dịch trên thị trường thứ cấp đạt 5.200 tỷ đồng, tăng 12% so với tuần trước.
Trading on the secondary market reached VND 5,200 billion this week.
"""


# ── extract_rates ────────────────────────────────────────────────────────────

def test_extract_rates_parses_all_three_indicators():
    out = vbma.extract_rates(_FIXTURE)
    assert out["interbank_on"] == pytest.approx(4.52)
    assert out["interbank_1w"] == pytest.approx(4.75)
    assert out["govt_bond_yield_10y"] == pytest.approx(3.12)


def test_extract_rates_english_on_outside_section_not_matched():
    # "Trading on the secondary market ... 5,200" — chữ "on" tiếng Anh + số
    # nằm NGOÀI section liên-ngân-hàng không được nhận nhầm làm lãi suất ON.
    text = """
Some intro text here.
Trading on the secondary market reached 5,20 percent growth.
More prose lines without any rates table.
"""
    assert vbma.extract_rates(text) == {}


def test_extract_rates_rejects_out_of_range_and_empty():
    bad = """
LÃI SUẤT LIÊN NGÂN HÀNG
   Qua đêm / ON                    45,2
"""
    assert vbma.extract_rates(bad) == {}      # 45.2%/năm ngoài sanity range
    assert vbma.extract_rates("") == {}


# ── find_latest_pdf ──────────────────────────────────────────────────────────

def test_find_latest_pdf_picks_max_end_date_and_quotes_url():
    html = """
    <a href="/data/Ban tin TT TP 23062026-27062026.pdf">tuần 23-27/06</a>
    <a href="/data/Ban tin TT TP 30062026-04072026.pdf">tuần 30/06-04/07</a>
    <a href="/data/huong-dan.pdf">không phải báo cáo tuần</a>
    """
    hit = vbma.find_latest_pdf(html)
    assert hit is not None
    url, as_of = hit
    assert as_of == "2026-07-04"                       # ngày CUỐI của tuần mới nhất
    assert url.startswith("https://vbma.org.vn/")
    assert " " not in url and "%20" in url             # dấu cách đã được quote


def test_find_latest_pdf_none_when_no_dated_pdf():
    assert vbma.find_latest_pdf('<a href="/x/abc.pdf">x</a>') is None
    assert vbma.find_latest_pdf("") is None


# ── vnstock_macro wiring ─────────────────────────────────────────────────────

def _use_tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro_indicators.json")


def test_refresh_records_vbma_readings_with_report_as_of(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: {
        "interbank_on": 4.52, "interbank_1w": 4.75,
        "govt_bond_yield_10y": 3.12, "as_of": "2026-07-04",
    })
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["interbank_on"]["value"] == pytest.approx(4.52)
    assert rows["interbank_1w"]["value"] == pytest.approx(4.75)
    assert rows["govt_bond_yield_10y"]["value"] == pytest.approx(3.12)
    assert rows["interbank_on"]["as_of"] == "2026-07-04"   # ngày báo cáo, không phải hôm nay


def test_refresh_vbma_failure_keeps_manual_value(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    mac.set_value("interbank_on", 9.9, as_of="2026-07-01")
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)   # fetch hỏng
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["interbank_on"]["value"] == pytest.approx(9.9)   # --set không bị đè


def test_refresh_vbma_kill_switch(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setenv("VNSTOCK_MACRO_VBMA", "0")
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    calls = {"n": 0}
    monkeypatch.setattr(mac, "_fetch_vbma",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    mac.refresh()
    assert calls["n"] == 0
