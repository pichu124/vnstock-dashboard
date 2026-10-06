"""vnstock_report_vision — Claude Code đọc ảnh báo cáo không có lớp text (04/10).

Hermetic: index/store trỏ tmp_path, `vcc.complete` giả (không spawn CLI), DOCX
dựng bằng zipfile trong bộ nhớ, ảnh bằng Pillow."""
from __future__ import annotations

import io
import zipfile

import pytest

import vnstock_claude_cli as vcc
import vnstock_report_vision as rv
import vnstock_reports as rp

PIL = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_INDEX", tmp_path / "reports_index.json")
    monkeypatch.setattr(rp, "_STORE", tmp_path / "reports")


def _png(w=800, h=600, color="white") -> bytes:
    buf = io.BytesIO()
    PIL.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def _docx(order: list[str], media: dict, *, text: str = "", hyperlink: bool = False) -> bytes:
    """DOCX tối giản: thân trỏ ảnh theo `order` (tên file media)."""
    rels = [f'<Relationship Id="rId{i}" Type="image" Target="media/{n}"/>'
            for i, n in enumerate(media, 1)]
    rid = {n: f"rId{i}" for i, n in enumerate(media, 1)}
    if hyperlink:
        rels.append('<Relationship Id="rLink" Type="hyperlink" '
                    'Target="https://x.com" TargetMode="External"/>')
    body = "".join(f'<w:p><w:r><w:drawing><a:blip r:embed="{rid[n]}"/></w:drawing></w:r></w:p>'
                   for n in order)
    if hyperlink:
        body += '<w:p><w:hyperlink r:id="rLink"><w:r><w:t>link</w:t></w:r></w:hyperlink></w:p>'
    if text:
        body += f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:a="{_A}">'
                   f"<w:body>{body}</w:body></w:document>")
        z.writestr("word/_rels/document.xml.rels",
                   f'<Relationships xmlns="{_PR}">{"".join(rels)}</Relationships>')
        for n, data in media.items():
            z.writestr(f"word/media/{n}", data)
    return buf.getvalue()


# ── DOCX: thứ tự + lọc ảnh ───────────────────────────────────────────────────


def test_docx_images_follow_body_order_not_file_names():
    media = {"image1.png": _png(color="red"), "image2.png": _png(color="blue"),
             "image3.png": _png(color="green"), "logo.png": _png()}   # logo: header, thân không trỏ
    got = rv.docx_images(_docx(["image3.png", "image1.png", "image3.png", "image2.png"],
                               media, hyperlink=True))
    assert [n for n, _ in got] == ["word/media/image3.png", "word/media/image1.png",
                                   "word/media/image2.png"]          # trùng chỉ 1 lần, bỏ logo + link


def test_docx_images_falls_back_to_all_media_and_survives_garbage():
    got = rv.docx_images(_docx([], {"b.png": _png(), "a.png": _png()}))
    assert [n for n, _ in got] == ["word/media/a.png", "word/media/b.png"]
    assert rv.docx_images(b"not a zip") == []


def test_prepare_image_drops_icons_vectors_and_shrinks_big():
    assert rv.prepare_image("i.png", _png(150, 150)) is None          # icon
    assert rv.prepare_image("i.png", _png(1600, 40)) is None          # vạch kẻ
    assert rv.prepare_image("c.svg", b"<svg/>") is None
    assert rv.prepare_image("c.emf", b"\x01\x00\x00\x00junk") is None  # không vẽ được ⇒ bỏ
    raw = _png(900, 600)
    assert rv.prepare_image("p.png", raw) == (".png", raw)            # vừa cỡ: giữ nguyên bytes
    ext, data = rv.prepare_image("big.png", _png(4000, 3000))
    assert ext == ".png" and max(PIL.open(io.BytesIO(data)).size) == rv.MAX_SIDE
    buf = io.BytesIO()
    PIL.new("RGB", (800, 600)).save(buf, format="BMP")
    assert rv.prepare_image("x.bmp", buf.getvalue())[0] == ".png"     # BMP ⇒ PNG


def test_chunks():
    assert rv.chunks(0, 8) == []
    assert rv.chunks(17, 8) == [(1, 8), (9, 16), (17, 17)]


def test_plan_docx_batches_and_numbers_images(monkeypatch):
    monkeypatch.setattr(rv, "IMAGES_PER_CALL", 2)
    media = {f"image{i}.png": _png(color=(i * 40, 0, 0)) for i in range(1, 6)}
    media["icon.png"] = _png(50, 50)
    p = rv.plan({"kind": "docx", "id": "x", "title": "Q4", "source": "HA"},
                _docx(list(media), media))
    assert p["n_units"] == 5 and p["skipped"] == 1 and len(p["jobs"]) == 3
    assert list(p["files"]) == [f"img_00{i}.png" for i in range(1, 6)]
    assert "img_003.png  → nhãn [Ảnh 3]" in p["jobs"][1] and "phần 2/3" in p["jobs"][1]
    assert "Báo cáo: Q4 (HA)" in p["jobs"][0]


def test_plan_pdf_page_ranges(monkeypatch):
    monkeypatch.setattr(rv, "pdf_page_count", lambda data: 23)
    p = rv.plan({"kind": "pdf", "id": "x"}, b"%PDF")
    assert p["files"] == {"report.pdf": b"%PDF"} and p["n_units"] == 23
    assert ['pages="1-10"' in p["jobs"][0], 'pages="11-20"' in p["jobs"][1],
            'pages="21-23"' in p["jobs"][2]] == [True] * 3
    monkeypatch.setattr(rv, "pdf_page_count", lambda data: None)      # pypdf không mở được
    assert len(rv.plan({"kind": "pdf", "id": "x"}, b"%PDF")["jobs"]) == 1


# ── read_report: Claude giả ──────────────────────────────────────────────────


def _add_scan_docx(n_images=3, **meta):
    media = {f"image{i}.png": _png(color=(i * 50, 10, 10)) for i in range(1, n_images + 1)}
    from pathlib import Path
    p = Path(rp._STORE).parent / "Q4.docx"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_docx(list(media), media))
    rec = rp.add_pdf(p, **meta)
    assert rec["no_text_layer"] and rec["chars"] == 0
    return rec


def _fake_complete(monkeypatch, replies):
    calls = []

    def fake(user, **kw):
        from pathlib import Path
        calls.append({"user": user, "files": sorted(p.name for p in Path(kw["cwd"]).iterdir()),
                      **kw})
        r = replies[len(calls) - 1]
        if isinstance(r, Exception):
            return "", str(r), {"elapsed_s": 1}
        return r, None, {"elapsed_s": 1, "cost_usd": 0.05, "model": "m"}
    monkeypatch.setattr(vcc, "complete", fake)
    return calls


LONG = "GDP quý 3/2026 tăng 7,4% so với cùng kỳ; CPI bình quân 9 tháng 3,1%. " * 4


def test_read_report_sets_text_and_enters_analysis(monkeypatch):
    monkeypatch.setattr(rv, "IMAGES_PER_CALL", 2)
    rec = _add_scan_docx(3, source="HedgeAcademy", report_date="2026-10-01")
    assert not rp.in_analysis(rec)
    calls = _fake_complete(monkeypatch, [f"[Ảnh 1]\n{LONG}", f"[Ảnh 3]\n{LONG}"])
    res = rv.read_report(rec["id"], log=lambda s: None)
    assert res["ok"] and res["n_jobs"] == 2 and res["cost_usd"] == pytest.approx(0.10)
    assert all(c["tools"] == "Read" and c["system"] == rv.VISION_SYSTEM for c in calls)
    assert calls[0]["files"] == ["img_001.png", "img_002.png", "img_003.png"]
    assert "img_003.png" in calls[1]["user"] and "img_001.png" not in calls[1]["user"]
    new = next(r for r in rp.list_reports() if r["id"] == rec["id"])
    assert rp.in_analysis(new) and new["text_via"] == rv.VIA and not new["no_text_layer"]
    assert rp.load_report_text(rec["id"]).startswith("[Ảnh 1]")
    assert rv.pending() == []


def test_read_report_all_or_nothing(monkeypatch):
    monkeypatch.setattr(rv, "IMAGES_PER_CALL", 1)
    rec = _add_scan_docx(3)
    _fake_complete(monkeypatch, [LONG, RuntimeError("claude CLI quá 900s — bỏ"), LONG])
    res = rv.read_report(rec["id"], log=lambda s: None)
    assert not res["ok"] and "lượt 2/3" in res["error"] and "900s" in res["error"]
    after = next(r for r in rp.list_reports() if r["id"] == rec["id"])
    assert after["no_text_layer"] and after["chars"] == 0 and "text_via" not in after
    assert [r["id"] for r in rv.pending()] == [rec["id"]]


def test_read_report_rejects_too_little_text(monkeypatch):
    rec = _add_scan_docx(1)
    _fake_complete(monkeypatch, ["[Ảnh 1] (trang trí)"])
    res = rv.read_report(rec["id"], log=lambda s: None)
    assert not res["ok"] and "ký tự" in res["error"]


def test_read_report_dry_run_never_calls_claude(monkeypatch):
    rec = _add_scan_docx(2)
    monkeypatch.setattr(vcc, "complete", lambda *a, **k: pytest.fail("dry-run gọi Claude"))
    res = rv.read_report(rec["id"], dry_run=True, log=lambda s: None)
    assert res["ok"] and res["n_units"] == 2 and res["n_jobs"] == 1


def test_read_report_without_original_or_images():
    rec = rp.add_text("x" * 300)
    assert "file gốc" in rv.read_report(rec["id"], log=lambda s: None)["error"]
    assert "không có báo cáo" in rv.read_report("nope", log=lambda s: None)["error"]


def test_reupload_keeps_vision_text(monkeypatch):
    rec = _add_scan_docx(1, source="HA", report_date="2026-10-01")
    _fake_complete(monkeypatch, [LONG])
    assert rv.read_report(rec["id"], log=lambda s: None)["ok"]
    from pathlib import Path
    again = rp.add_pdf(Path(rp._STORE).parent / "Q4.docx")         # Streamlit rerun
    assert again["chars"] == len(LONG.strip()) and rp.in_analysis(again)


def test_main_exit_codes(monkeypatch, capsys):
    assert rv.main([]) == 2
    assert rv.main(["--all"]) == 0
    rec = _add_scan_docx(1)
    _fake_complete(monkeypatch, [LONG])
    assert rv.main([rec["id"]]) == 0
    assert "còn thiếu ngày/nguồn" in capsys.readouterr().out
