"""Tests for vnstock_nso — CPI/IIP tháng từ NSO + vnstock_macro wiring.

Fixture = câu chữ CÔNG THỨC của NSO với số liệu THẬT tháng 6/2026 (đối chiếu
qua nhiều báo dẫn lại NSO: CPI −0,39% MoM / +4,69% YoY; IIP +3,5% MoM /
+12,7% YoY), giữ các bẫy đã lường trước:
  * "tăng 3,61% so với tháng 12/2025" (mốc YTD — KHÔNG phải MoM)
  * "Bình quân 6 tháng ... CPI tăng 4,38% so với cùng kỳ" (bình quân — KHÔNG
    phải YoY của tháng; đứng NGAY SAU câu tháng)
  * ngành con "chế biến, chế tạo tăng 12,6% so với cùng kỳ" sau câu IIP headline
  * NSO dùng dấu PHẨY thập phân ("0,39%")
"""
from __future__ import annotations

import pytest

import vnstock_macro as mac
import vnstock_nso as nso


_REAL = (
    "Chỉ số giá tiêu dùng (CPI) tháng 6/2026 giảm 0,39% so với tháng trước, "
    "tăng 3,61% so với tháng 12/2025 và tăng 4,69% so với cùng kỳ năm trước. "
    "Bình quân quý II/2026, CPI tăng 5,25% so với quý II/2025. Bình quân 6 "
    "tháng đầu năm 2026, CPI tăng 4,38% so với cùng kỳ năm trước; lạm phát cơ "
    "bản tăng 4,12%. "
    "Chỉ số sản xuất toàn ngành công nghiệp (IIP) tháng Sáu ước tính tăng "
    "3,5% so với tháng trước và tăng 12,7% so với cùng kỳ năm trước. Trong "
    "đó, ngành chế biến, chế tạo tăng 12,6% so với cùng kỳ năm trước; sản "
    "xuất và phân phối điện tăng 8,7%."
)


def test_extract_indicators_real_sentences_exact_values():
    out = nso.extract_indicators(_REAL)
    assert out == {
        "cpi_mom": pytest.approx(-0.39),   # "giảm" → dấu âm
        "cpi_yoy": pytest.approx(4.69),    # KHÔNG phải 3,61 (tháng 12) / 4,38 (bình quân)
        "iip_mom": pytest.approx(3.5),
        "iip_yoy": pytest.approx(12.7),    # KHÔNG phải 12,6 của ngành con
    }


def test_extract_skips_average_only_mention_and_uses_month_sentence():
    # Anchor đầu là câu BÌNH QUÂN (không có "so với tháng trước/cùng kỳ" trước
    # điểm cắt) → cửa sổ sau (câu tháng) mới thắng.
    text = (
        "Chỉ số giá tiêu dùng bình quân 6 tháng đầu năm 2026 tăng 4,38% so với "
        "cùng kỳ năm trước. "
        "Chỉ số giá tiêu dùng (CPI) tháng 6/2026 giảm 0,39% so với tháng trước "
        "và tăng 4,69% so với cùng kỳ năm trước."
    )
    out = nso.extract_indicators(text)
    assert out["cpi_mom"] == pytest.approx(-0.39)
    assert out["cpi_yoy"] == pytest.approx(4.69)


def test_extract_rejects_out_of_range_and_empty():
    assert nso.extract_indicators(
        "Chỉ số giá tiêu dùng (CPI) tháng 6 tăng 45,00% so với cùng kỳ") == {}
    assert nso.extract_indicators("") == {}
    assert nso.extract_indicators("Không có số liệu nào ở đây.") == {}


# ── find_latest_report ───────────────────────────────────────────────────────

def test_find_latest_report_picks_max_publish_month_and_data_month_end():
    html = """
    <a href="/bai-top/2026/06/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-nam-va-5-thang-dau-nam-2025-2/">T5</a>
    <a href="/bai-top/2026/07/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-sau-va-6-thang-dau-nam-2026/">T6</a>
    <a href="/bai-top/2026/07/thong-cao-khac.pdf">khác</a>
    """
    hit = nso.find_latest_report(html)
    assert hit is not None
    url, as_of = hit
    assert url.startswith("https://www.nso.gov.vn/bai-top/2026/07/")
    assert as_of == "2026-06-30"            # publish 07 → data tháng 6, cuối tháng


def test_find_latest_report_quarter_month_uses_quarterly_report():
    # Tháng cuối quý KHÔNG có "báo cáo tháng" — chỉ có "báo cáo quý x và N
    # tháng" (URL thật Q2/2026, publish 07). Diag 08/07 từng vớ nhầm bài T5.
    html = """
    <a href="/bai-top/2026/06/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-nam-va-5-thang-dau-nam-2025-2/">T5</a>
    <a href="/bai-top/2026/07/bao-cao-tinh-hinh-kinh-te-xa-hoi-quy-ii-va-sau-thang-dau-nam-2026/">Q2</a>
    """
    hit = nso.find_latest_report(html)
    assert hit is not None
    assert "quy-ii" in hit[0] and hit[1] == "2026-06-30"


def test_find_latest_report_january_rolls_back_to_december():
    html = '<a href="/bai-top/2026/01/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-muoi-hai-2025/">x</a>'
    hit = nso.find_latest_report(html)
    assert hit is not None
    assert hit[1] == "2025-12-31"


def test_find_latest_report_none_when_no_match():
    assert nso.find_latest_report('<a href="/bai-top/2026/07/tin-khac/">x</a>') is None
    assert nso.find_latest_report("") is None


def test_strip_html_flattens_tags_and_entities():
    text = nso._strip_html(
        "<html><script>var x=1;</script><p>CPI th&aacute;ng 6/2026\n"
        "gi&#7843;m  0,39%</p></html>")
    assert "var x" not in text
    assert "CPI tháng 6/2026 giảm 0,39%" in text


# ── vnstock_macro wiring ─────────────────────────────────────────────────────

def _use_tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro_indicators.json")
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: None)


def test_refresh_records_nso_readings_with_data_month_as_of(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "_fetch_nso", lambda: {
        "cpi_yoy": 4.69, "cpi_mom": -0.39, "iip_yoy": 12.7,
        "as_of": "2026-06-30",
    })
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["cpi_yoy"]["value"] == pytest.approx(4.69)
    assert rows["iip_yoy"]["value"] == pytest.approx(12.7)
    assert rows["cpi_yoy"]["as_of"] == "2026-06-30"    # cuối tháng data
    assert "cpi_mom" not in rows                       # chỉ ghi key trong _DEFS


def test_refresh_nso_failure_keeps_manual_value(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    mac.set_value("cpi_yoy", 3.3, as_of="2026-05-31")
    monkeypatch.setattr(mac, "_fetch_nso", lambda: None)
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["cpi_yoy"]["value"] == pytest.approx(3.3)


def test_refresh_nso_kill_switch(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setenv("VNSTOCK_MACRO_NSO", "0")
    calls = {"n": 0}
    monkeypatch.setattr(mac, "_fetch_nso",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    mac.refresh()
    assert calls["n"] == 0


# ── TLS ladder (.gov.vn thiếu intermediate — diag thật 08/07/2026) ───────────


class _FakeResp:
    status_code = 200
    text = "<html>ok</html>"


def test_http_get_falls_back_to_insecure_when_both_stores_fail(monkeypatch):
    import requests as rq

    calls = []

    def fake_get(url, **kw):
        calls.append(kw.get("verify", True))
        if kw.get("verify", True) is not False:
            raise rq.exceptions.SSLError("missing intermediate")
        return _FakeResp()

    monkeypatch.setattr(nso.requests, "get", fake_get)

    class _S:
        def get(self, url, **kw):
            raise rq.exceptions.SSLError("os store also fails")

    monkeypatch.setattr(nso, "_os_trust_session", lambda: _S())
    r = nso._http_get("https://www.nso.gov.vn/x")
    assert r is not None and r.status_code == 200
    assert calls[-1] is False                     # nấc cuối mới hạ verify


def test_http_get_strict_env_forbids_insecure_fallback(monkeypatch):
    import requests as rq
    monkeypatch.setenv("VNSTOCK_NSO_TLS_STRICT", "1")

    def fake_get(url, **kw):
        raise rq.exceptions.SSLError("missing intermediate")

    monkeypatch.setattr(nso.requests, "get", fake_get)

    class _S:
        def get(self, url, **kw):
            raise rq.exceptions.SSLError("os store also fails")

    monkeypatch.setattr(nso, "_os_trust_session", lambda: _S())
    assert nso._http_get("https://www.nso.gov.vn/x") is None


def test_http_get_prefers_verified_when_it_works(monkeypatch):
    def fake_get(url, **kw):
        assert kw.get("verify", True) is not False
        return _FakeResp()

    monkeypatch.setattr(nso.requests, "get", fake_get)
    r = nso._http_get("https://www.nso.gov.vn/x")
    assert r is not None and r.status_code == 200


def test_iip_window_never_bleeds_into_consumption_index():
    # Bug diag 08/07 (bài quý II): anchor IIP KHÔNG mang số ("tăng ở 34 địa
    # phương") đứng ngay trước câu "Chỉ số TIÊU THỤ … 1,8% … 9,0%" → cửa sổ
    # tràn sang, IIP bị gán số tiêu thụ. Cửa sổ phải cắt tại "Chỉ số" kế tiếp.
    bleed = (
        "Chỉ số sản xuất toàn ngành công nghiệp tăng ở 34 địa phương trên cả "
        "nước. Chỉ số tiêu thụ toàn ngành công nghiệp chế biến, chế tạo tháng "
        "6/2026 tăng 1,8% so với tháng trước và tăng 9,0% so với cùng kỳ năm "
        "trước."
    )
    assert nso.extract_indicators(bleed) == {}       # KHÔNG nhận 1,8/9,0

    # đủ cả câu quý (bỏ), câu tháng (lấy), câu tiêu thụ (bỏ) — như bài quý thật
    full = (
        "Chỉ số sản xuất toàn ngành công nghiệp (IIP) quý II/2026 ước tính "
        "tăng 11,2% so với cùng kỳ năm trước. "
        "Chỉ số sản xuất toàn ngành công nghiệp (IIP) tháng 6/2026 ước tính "
        "tăng 3,5% so với tháng trước và tăng 12,7% so với cùng kỳ năm trước. "
        "Chỉ số tiêu thụ toàn ngành công nghiệp chế biến, chế tạo tháng 6/2026 "
        "tăng 1,8% so với tháng trước và tăng 9,0% so với cùng kỳ năm trước."
    )
    out = nso.extract_indicators(full)
    assert out["iip_mom"] == pytest.approx(3.5)
    assert out["iip_yoy"] == pytest.approx(12.7)
