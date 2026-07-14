"""Tests for vnstock_reports — Phase 2: ingest báo cáo vĩ mô (PDF/URL/text).

Hermetic: index + store trỏ vào tmp_path; PDF→text và Jina fetch đều
monkeypatch — không mạng, không cần pdftotext/pypdf, không LLM.
"""
import json
import sys
import types
from datetime import date, timedelta

import pytest

import vnstock_reports as rp


_TEXT = ("Báo cáo chiến lược vĩ mô tháng 7: lãi suất điều hành giữ 4.5%, "
         "tỷ giá chịu áp lực, ưu tiên nhóm phòng thủ. " * 10)   # > 200 ký tự


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_INDEX", tmp_path / "reports_index.json")
    monkeypatch.setattr(rp, "_STORE", tmp_path / "reports")


def _fake_vbma(monkeypatch, text=_TEXT):
    monkeypatch.setitem(sys.modules, "vnstock_vbma", types.ModuleType("vnstock_vbma"))
    sys.modules["vnstock_vbma"].pdf_to_text = lambda data: text


def _today():
    return date.today().isoformat()


# ── add_text: dedup + metadata gate ─────────────────────────────────────────


def test_add_text_full_metadata_goes_into_analysis():
    rec = rp.add_text(_TEXT, report_date=_today(), source="VNDirect",
                      title="Chiến lược T7")
    assert rec and rp.in_analysis(rec)
    assert rec["kind"] == "text" and rec["chars"] == len(_TEXT.strip())
    assert rp.load_report_text(rec["id"]).startswith("Báo cáo chiến lược")
    assert len(rp.list_reports()) == 1


def test_add_text_dedup_same_content_merges_metadata():
    r1 = rp.add_text(_TEXT)                          # thiếu metadata
    assert not rp.in_analysis(r1)
    # dán lại CÙNG nội dung (khác whitespace) kèm metadata → cùng id, merge
    r2 = rp.add_text("  " + _TEXT.replace(" ", "  ") + "\n",
                     report_date=_today(), source="SSI")
    assert r2["id"] == r1["id"]
    assert len(rp.list_reports()) == 1               # không nhân bản
    assert rp.in_analysis(r2)


def test_add_text_rejects_empty():
    assert rp.add_text("   ") is None
    assert rp.list_reports() == []


def test_invalid_or_future_report_date_kept_library_only(capsys):
    r1 = rp.add_text(_TEXT, report_date="10/07/2026", source="SSI")
    assert not rp.in_analysis(r1) and "report_date" not in r1
    future = (date.today() + timedelta(days=30)).isoformat()
    r2 = rp.add_text(_TEXT + "x", report_date=future, source="SSI")
    assert not rp.in_analysis(r2)
    out = capsys.readouterr().out
    assert "thư viện" in out


def test_set_meta_completes_record_into_analysis():
    rec = rp.add_text(_TEXT)
    assert not rp.in_analysis(rec)
    upd = rp.set_meta(rec["id"], report_date=_today(), source="HSC")
    assert rp.in_analysis(upd)
    on_disk = rp.list_reports()[0]
    assert on_disk["source"] == "HSC" and on_disk["report_date"] == _today()
    assert rp.set_meta("khong_co_id", source="X") is None


# ── add_pdf: sha256 bytes + no_text_layer ────────────────────────────────────


def test_add_pdf_extracts_text_and_keeps_original(tmp_path, monkeypatch):
    _fake_vbma(monkeypatch)
    pdf = tmp_path / "chien_luoc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake body")
    rec = rp.add_pdf(pdf, report_date=_today(), source="VCBS")
    assert rec and rp.in_analysis(rec)
    assert rec["kind"] == "pdf" and rec["orig_name"] == "chien_luoc.pdf"
    assert rec["title"] == "chien_luoc"              # mặc định = tên file
    assert rp._pdf_path(rec["id"]).exists()          # giữ PDF gốc cho --redigest
    # upload lại cùng file (Streamlit rerun) → cùng id, không nhân bản
    rec2 = rp.add_pdf(pdf, source="VCBS")
    assert rec2["id"] == rec["id"] and len(rp.list_reports()) == 1


def test_add_pdf_scan_without_text_layer_flagged(tmp_path, monkeypatch):
    _fake_vbma(monkeypatch, text="")                 # PDF scan → không có text
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 scanned")
    rec = rp.add_pdf(pdf, report_date=_today(), source="SSI")
    assert rec["no_text_layer"] is True
    assert not rp.in_analysis(rec)                   # có metadata vẫn không vào
    assert rec in rp.list_reports()                  # nhưng vẫn nằm thư viện


def test_add_pdf_missing_file_returns_none(tmp_path):
    assert rp.add_pdf(tmp_path / "khong_ton_tai.pdf") is None


# ── add_url: Jina best-effort ────────────────────────────────────────────────


def test_add_url_stores_fetched_text(monkeypatch):
    monkeypatch.setattr(rp, "fetch_url_text", lambda u, timeout=30: _TEXT)
    rec = rp.add_url("https://ctck.vn/bao-cao-t7", report_date=_today(),
                     source="Mirae", title="Báo cáo T7")
    assert rec and rp.in_analysis(rec)
    assert rec["url"] == "https://ctck.vn/bao-cao-t7"
    # cùng URL → cùng id (dedup theo URL, không theo nội dung fetch)
    rec2 = rp.add_url("https://ctck.vn/bao-cao-t7")
    assert rec2["id"] == rec["id"] and len(rp.list_reports()) == 1


def test_add_url_fetch_fail_stores_nothing(monkeypatch, capsys):
    monkeypatch.setattr(rp, "fetch_url_text", lambda u, timeout=30: "")
    assert rp.add_url("https://ctck.vn/bi-chan") is None
    assert rp.list_reports() == []
    assert "không lấy được" in capsys.readouterr().out
    assert rp.add_url("khong-phai-url") is None


def test_fetch_url_text_strips_jina_preamble_and_markdown(monkeypatch):
    raw = ("Title: Báo cáo\nURL Source: https://x\nMarkdown Content:\n"
           "# Vĩ mô\n\n\n\n![logo](http://x/l.png) Xem [chi tiết](http://x/a) "
           "lãi suất giữ nguyên.")

    class _Resp:
        text = raw
        def raise_for_status(self):
            pass

    fake_req = types.ModuleType("requests")
    fake_req.get = lambda *a, **k: _Resp()
    monkeypatch.setitem(sys.modules, "requests", fake_req)
    out = rp.fetch_url_text("https://ctck.vn/bao-cao")
    assert "Markdown Content" not in out and "![" not in out
    assert "chi tiết lãi suất giữ nguyên." in out
    assert "\n\n\n" not in out                       # gộp dòng trống thừa


# ── remove / list / load_for_analysis ────────────────────────────────────────


def test_remove_deletes_record_and_files():
    rec = rp.add_text(_TEXT, report_date=_today(), source="SSI")
    assert rp._text_path(rec["id"]).exists()
    assert rp.remove(rec["id"]) is True
    assert rp.list_reports() == []
    assert not rp._text_path(rec["id"]).exists()
    assert rp.remove(rec["id"]) is False             # xóa lần 2 → báo không có


def test_list_reports_sorted_newest_first():
    rp.add_text(_TEXT + "a", report_date="2026-06-01", source="A")
    rp.add_text(_TEXT + "b", report_date="2026-07-01", source="B")
    rp.add_text(_TEXT + "c")                         # không ngày → xếp cuối
    dates = [r.get("report_date") for r in rp.list_reports()]
    assert dates == ["2026-07-01", "2026-06-01", None]


def test_load_for_analysis_filters_completeness_and_age():
    rp.add_text(_TEXT + "fresh", report_date="2026-07-10", source="SSI")
    rp.add_text(_TEXT + "old", report_date="2026-03-01", source="SSI")   # > 90d
    rp.add_text(_TEXT + "nometa")                                        # thiếu meta
    out = rp.load_for_analysis(as_of="2026-07-13")
    assert [r["report_date"] for r in out] == ["2026-07-10"]
    assert out[0]["age_days"] == 3                   # cho decay P3
    # nới max_age → báo cáo cũ vào lại
    out2 = rp.load_for_analysis(as_of="2026-07-13", max_age_days=365)
    assert len(out2) == 2


def test_report_date_in_future_of_as_of_excluded():
    rp.add_text(_TEXT, report_date=_today(), source="SSI")
    assert rp.load_for_analysis(as_of="2020-01-01") == []   # age âm → loại


# ── CLI smoke ────────────────────────────────────────────────────────────────


def test_cli_add_text_list_show_setmeta_remove(capsys):
    assert rp.main(["--add-text", _TEXT, "--source", "SSI"]) == 0
    rid = rp.list_reports()[0]["id"]
    assert rp.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert rid in out and "📥" in out                # thiếu ngày → chưa ✅
    assert rp.main(["--set-meta", rid, "--report-date", _today()]) == 0
    assert rp.main(["--show", rid]) == 0
    shown = capsys.readouterr().out
    assert '"report_date"' in shown and "Báo cáo chiến lược" in shown
    assert rp.main(["--remove", rid]) == 0
    assert rp.main(["--show", rid]) == 1


def test_cli_add_text_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(_TEXT))
    assert rp.main(["--add-text", "-", "--source", "HSC",
                    "--report-date", _today()]) == 0
    assert rp.list_reports()[0]["chars"] > 200


def test_cli_empty_library_message(capsys):
    assert rp.main([]) == 0
    assert "thư viện trống" in capsys.readouterr().out


def test_index_written_atomically(tmp_path):
    rp.add_text(_TEXT, report_date=_today(), source="SSI")
    raw = json.loads(rp._INDEX.read_text(encoding="utf-8"))
    assert raw["updated_at"] and len(raw["reports"]) == 1
    assert not rp._INDEX.with_suffix(".json.tmp").exists()   # tmp đã replace


def test_add_pdf_directory_gives_clear_error(tmp_path, capsys):
    # Đường dẫn THƯ MỤC (dán nhầm folder Dropbox — verify 14/07): Windows trả
    # 'Permission denied' gây hiểu nhầm → phải nói thẳng là thư mục + gợi ý PDF.
    d = tmp_path / "bao_cao_vi_mo"
    d.mkdir()
    (d / "t7.pdf").write_bytes(b"%PDF")
    assert rp.add_pdf(d) is None
    out = capsys.readouterr().out
    assert "THƯ MỤC" in out and "t7.pdf" in out
    assert rp.list_reports() == []


def _mk_docx(path, paragraphs):
    """Dựng DOCX tối thiểu thật (zip + word/document.xml) — không cần Word."""
    import zipfile
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = (f'<?xml version="1.0"?><w:document xmlns:w="{ns}">'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_add_docx_extracts_text_and_goes_into_analysis(tmp_path):
    # Thư viện báo cáo thật của user là .docx (verify 14/07) — đọc bằng stdlib.
    docx = tmp_path / "Q3.docx"
    _mk_docx(docx, ["Báo cáo vĩ mô quý 3.", _TEXT])
    rec = rp.add_pdf(docx, report_date=_today(), source="HedgeAcademy")
    assert rec and rec["kind"] == "docx"
    assert rp.in_analysis(rec)
    body = rp.load_report_text(rec["id"])
    assert body.startswith("Báo cáo vĩ mô quý 3.")
    assert "lãi suất điều hành" in body
    assert rp._docx_path(rec["id"]).exists()          # giữ file gốc cho --redigest
    # xóa dọn cả file gốc .docx
    rp.remove(rec["id"])
    assert not rp._docx_path(rec["id"]).exists()


def test_add_docx_corrupt_flagged_no_text_layer(tmp_path):
    bad = tmp_path / "hong.docx"
    bad.write_bytes(b"khong phai zip")
    rec = rp.add_pdf(bad, report_date=_today(), source="X")
    assert rec["kind"] == "docx" and rec["no_text_layer"] is True
    assert not rp.in_analysis(rec)


def test_docx_to_text_handles_garbage():
    assert rp.docx_to_text(b"") == ""
    assert rp.docx_to_text(b"rac") == ""
