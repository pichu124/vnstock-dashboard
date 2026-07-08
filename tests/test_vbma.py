"""Tests for vnstock_vbma — VBMA weekly PDF parser + vnstock_macro wiring.

Fixture = TRÍCH ĐOẠN THẬT từ bản tin tuần 29/06–03/07/2026 (user cung cấp,
extract bằng `pdftotext -layout`), giữ nguyên các bẫy đã gặp khi chỉnh parser:
  * đoạn văn xuôi "lên mức 9.26% ... qua đêm và 1W" (từng làm ON=1W=9.26)
  * nhãn trục chart " 5.0%" (từng làm 10Y=5.0)
  * dòng legend chart "3/7/2026  26/6/2026  3/7/2025" (dates không có %)
  * cột "TB 5 ngày" đứng TRƯỚC cột ngày báo cáo (từng làm ON=6.89)
Giá trị đúng đối chiếu văn xuôi của chính báo cáo: ON 5.67 / 1W 6.17 / 10Y 4.40.
"""
from __future__ import annotations

import pytest

import vnstock_macro as mac
import vnstock_vbma as vbma


@pytest.fixture(autouse=True)
def _no_external_macro_fetch(monkeypatch):
    """refresh() nay còn gọi NSO (mạng) + PMI-from-news (đọc cache repo) —
    chặn mặc định để test wiring hermetic."""
    monkeypatch.setattr(mac, "_fetch_nso", lambda: None)
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: None)


_REAL = """\
 Lãi suất liên ngân hàng: Kết tuần, trong khi lãi suất qua đêm ON tăng 276 đcb lên mức 5.67%, lãi suất kỳ hạn 1W giảm 118 đcb xuống
 mức 6.17%. Ngoài ra, lãi suất kỳ hạn 6 tháng tăng 40 đcb lên mức 9.00% và lãi suất kỳ hạn 9 tháng tăng 120 đcb lên mức 9.26%. Chênh
 lệch lãi suất USD và VND kỳ hạn qua đêm và 1W trung bình nới rộng khoảng 264 đcb.

 Khối lượng giao dịch: Tổng giá trị giao dịch trên thị trường liên ngân hàng trong kỳ báo cáo tăng 4.2% so với kỳ trước, lên mức 4.59
 triệu tỷ đồng. Trong đó, kỳ hạn qua đêm (ON) và 1 tuần (1W) có khối lượng giao dịch lớn nhất.

LÃI SUẤT LIÊN NGÂN HÀNG
 Đvị : %       TB 5 ngày      3/7/2026      26/6/2026     +/- so tuần trước (đcb)    +/- so tháng trước (đcb)
        ON        6.89           5.67          2.91           276                        19
        1W        6.94           6.17          7.35          -118                          3
        2W        7.14           6.12          7.72          -160                        -10
        1M        7.84           7.38          7.57           -19                         24

Lợi suất trái phiếu Chính phủ (theo VBMA): Lợi suất trung bình TPCP đi ngang ở hầu hết các kỳ hạn.
              DIỄN BIẾN LỢI SUẤT TRÁI PHIẾU CHÍNH PHỦ - VBMA
 5.0%
 4.5%
 1.0%
        1N       2N       3N       5N       7N       10N       15N       20N       30N
              3/7/2026            26/6/2026           3/7/2025

BIẾN ĐỘNG LỢI SUẤT PHÒNG GIAO DỊCH VBMA
        1N       2N       3N       5N       7N       10N       15N       20N       30N
3/7/2026      3.40%    3.50%    3.57%    4.20%    4.26%    4.40%    4.57%    4.64%    4.71%
26/6/2026     3.38%    3.48%    3.56%    4.19%    4.25%    4.40%    4.57%    4.62%    4.69%
WoW (đcb)       1.68     2.32     1.36     1.22     0.98     0.14     0.28     1.60     1.64
Nguồn: VBMA
"""


# ── extract_rates trên trích đoạn thật ───────────────────────────────────────

def test_extract_rates_real_excerpt_exact_values():
    out = vbma.extract_rates(_REAL)
    assert out == {
        "interbank_on": pytest.approx(5.67),      # cột 3/7/2026, KHÔNG phải TB 5 ngày 6.89
        "interbank_1w": pytest.approx(6.17),      # và KHÔNG phải 9.26 từ văn xuôi
        "govt_bond_yield_10y": pytest.approx(4.40),  # ma trận 10N, KHÔNG phải trục chart 5.0%
    }


def test_extract_rates_narrative_fallback_when_table_missing():
    # Layout đổi mất bảng → fallback câu văn cấu trúc chặt "... mức X%"
    narrative_only = (
        "Lãi suất liên ngân hàng: Kết tuần, trong khi lãi suất qua đêm ON tăng "
        "276 đcb lên mức 5.67%, lãi suất kỳ hạn 1W giảm 118 đcb xuống mức 6.17%."
    )
    out = vbma.extract_rates(narrative_only)
    assert out["interbank_on"] == pytest.approx(5.67)
    assert out["interbank_1w"] == pytest.approx(6.17)


def test_extract_rates_english_on_prose_not_matched():
    # Chữ "on" tiếng Anh + số ngoài mọi bảng/anchor không được nhận nhầm
    text = "Trading on the secondary market reached 5.20 percent growth this week."
    assert vbma.extract_rates(text) == {}


def test_extract_rates_rejects_out_of_range_and_empty():
    bad = """\
LÃI SUẤT LIÊN NGÂN HÀNG
 Đvị : %    TB 5 ngày   3/7/2026
        ON     46.89       45.67
"""
    assert vbma.extract_rates(bad) == {}          # ngoài sanity range 0-20%/năm
    assert vbma.extract_rates("") == {}


# ── _parse_fx: tỷ giá VCB từ văn xuôi "THỊ TRƯỜNG NGOẠI HỐI" ────────────────

# Trích đoạn thật (pdftotext) — câu bị NGẮT DÒNG giữa chừng; số delta
# "giảm 11 VND/USD xuống" / "tăng 9 VND/USD lên" đứng cạnh số cần lấy.
_REAL_FX = """\
 Kết tuần, tỷ giá trung tâm tăng 8 VND/USD so với tuần trước, lên mức
 25,203 VND/USD. Ngoài ra, tỷ giá niêm yết tại Vietcombank giảm 11
 VND/USD xuống 26,103 VND/USD ở chiều mua và tăng 9 VND/USD lên
 26,463 VND/USD ở chiều bán.
"""

# Cùng đoạn khi extract bằng PYPDF — chữ DÍNH nhau qua chỗ xuống dòng
# ("tỷ giániêm yết", "ởchiều bán") — thấy trên PDF thật 03/07/2026.
_REAL_FX_PYPDF = (
    "Tỷ giá USD/VND: Kết tuần, tỷ giá trung tâm tăng 8 VND/USD so với tuần "
    "trước, lên mức 25,203 VND/USD. Ngoài ra, tỷ giániêm yết tại Vietcombank "
    "giảm 11 VND/USD xuống 26,103 VND/USD ở chiều mua và tăng 9 VND/USD lên "
    "26,463 VND/USD ởchiều bán."
)


def test_parse_fx_vcb_mid_both_extraction_modes():
    # mid = (26,103 + 26,463) / 2 — KHÔNG dính 25,203 (trung tâm) hay delta 9/11
    assert vbma._parse_fx(_REAL_FX) == pytest.approx(26283.0)
    assert vbma._parse_fx(_REAL_FX_PYPDF) == pytest.approx(26283.0)
    out = vbma.extract_rates(_REAL_FX)
    assert out["usdvnd_vcb_mid"] == pytest.approx(26283.0)


def test_parse_fx_rejects_inverted_or_missing_sides():
    swapped = ("xuống 26,463 VND/USD ở chiều mua và lên "
               "26,103 VND/USD ở chiều bán")           # mua > bán → vô lý, bỏ
    assert vbma._parse_fx(swapped) is None
    assert vbma._parse_fx("chỉ có 26,103 VND/USD ở chiều mua") is None
    assert vbma._parse_fx("") is None


def test_refresh_fx_crosscheck_flags_divergence_and_clears(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: {
        "as_of": "2026-07-03", "usdvnd_vcb_mid": 26283.0,
    })
    # er-api lệch +2.7% so với VCB → cắm cờ cảnh báo trong cache
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: 27000.0)
    mac.refresh()
    xc = mac._load_cache().get("fx_crosscheck")
    assert xc and xc["diff_pct"] == pytest.approx(2.73, abs=0.01)
    # về lại trong ngưỡng → cờ được XÓA (không cảnh báo dai dẳng)
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: 26300.0)
    mac.refresh()
    assert "fx_crosscheck" not in mac._load_cache()
    # usdvnd_vcb_mid KHÔNG bị ghi thành chỉ số riêng
    assert "usdvnd_vcb_mid" not in {x["key"] for x in mac.load_macro()}


# ── find_latest_pdf ──────────────────────────────────────────────────────────

def test_find_latest_pdf_real_concatenated_filename():
    # Tên file thật: 2 ngày DDMMYYYY nối LIỀN không có dấu gạch
    html = '<a href="/data/2906202603072026_BAO_CAO_TUAN_TTTP1.pdf">tuần</a>'
    hit = vbma.find_latest_pdf(html)
    assert hit == (
        "https://vbma.org.vn/data/2906202603072026_BAO_CAO_TUAN_TTTP1.pdf",
        "2026-07-03",
    )


def test_find_latest_pdf_picks_max_end_date_and_quotes_spaces():
    html = """
    <a href="/data/Ban tin 2306202627062026.pdf">tuần cũ</a>
    <a href="/data/Ban tin 3006202604072026.pdf">tuần mới</a>
    <a href="/data/huong-dan.pdf">không phải báo cáo</a>
    """
    hit = vbma.find_latest_pdf(html)
    assert hit is not None
    url, as_of = hit
    assert as_of == "2026-07-04"
    assert " " not in url and "%20" in url


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
        "interbank_on": 5.67, "interbank_1w": 6.17,
        "govt_bond_yield_10y": 4.40, "as_of": "2026-07-03",
    })
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["interbank_on"]["value"] == pytest.approx(5.67)
    assert rows["interbank_1w"]["value"] == pytest.approx(6.17)
    assert rows["govt_bond_yield_10y"]["value"] == pytest.approx(4.40)
    assert rows["interbank_on"]["as_of"] == "2026-07-03"   # ngày báo cáo, không phải hôm nay


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


# Trích đoạn thật khi extract bằng PYPDF (máy Windows không có pdftotext):
# layout ma trận bị XÁO — header tenor vỡ mảnh, hàng 2025 in TRƯỚC hàng 2026,
# giá trị cuối rớt dòng. Đường 2 của _parse_bond_10y phải vẫn ra 4.40 (10N,
# dòng có ngày MỚI NHẤT).
_REAL_PYPDF_BOND = """\
BIẾN ĐỘNG LỢI SUẤT PHÒNG GIAO DỊCH VBMA
* Chú thích: Dữ liệu VBMA tổng hợp tính đến ngày 3/7/2026
1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20
3/7/2025 2.18% 2.23% 2.30% 2.67% 3.00% 3.22% 3.34% 3.40%
4.62%
3/7/2026 3.40% 3.50% 3.57% 4.20% 4.26% 4.40% 4.57% 4.64%
20N
7N 10N 15N
26/6/2026 3.38%
1N 2N 3N 5N
WoW (đcb)
3.48% 3.56% 4.19% 4.25% 4.40% 4.57%
"""


def test_extract_rates_pypdf_scrambled_matrix_latest_date_wins():
    out = vbma.extract_rates(_REAL_PYPDF_BOND)
    # 4.40 từ hàng 3/7/2026 (mới nhất) — KHÔNG phải 3.22 của hàng 3/7/2025
    # đứng trước, và hàng 26/6/2026 cụt (1 giá trị) bị bỏ qua.
    assert out.get("govt_bond_yield_10y") == pytest.approx(4.40)
