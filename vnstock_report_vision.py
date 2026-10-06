#!/usr/bin/env python3
"""vnstock_report_vision.py — Claude Code ĐỌC ẢNH báo cáo không có lớp text (04/10).

Tại sao
-------
PDF scan và DOCX toàn ảnh (Q4.docx của user, 04/10) ingest ra 0 ký tự ⇒ cờ
``no_text_layer`` ⇒ không bao giờ vào digest. Claude Code xem được ảnh qua công
cụ Read (đã thử 2.1.289: PNG trong cwd + PDF scan với ``pages``), nên đường này
chép ảnh thành text rồi ``vnstock_reports.set_text`` — từ đó báo cáo đi tiếp
đường digest bình thường (đủ ngày + nguồn là vào phân tích).

Cách làm
--------
* DOCX: ảnh lấy từ ``word/media`` theo ĐÚNG thứ tự xuất hiện trong
  ``document.xml`` (r:embed/r:id → rels). Ảnh header/footer (logo) không nằm
  trong document.xml nên tự rơi; ảnh quá nhỏ (icon) bỏ. EMF/WMF (biểu đồ dán
  từ Excel) chỉ Pillow trên Windows mới vẽ được — không vẽ được thì bỏ + đếm.
  Ảnh ghi ra thư mục tạm ``img_001.png…``, mỗi lượt CLI đọc ``IMAGES_PER_CALL``.
* PDF: chép ``report.pdf`` vào thư mục tạm, mỗi lượt đọc ``PDF_PAGES_PER_CALL``
  trang qua Read ``pages=``.
* CLI: ``vnstock_claude_cli.complete(tools="Read", cwd=<thư mục tạm>)`` — chỉ
  bật Read, cwd chỉ chứa ảnh của báo cáo. Model = ``VNSTOCK_REPORT_VISION_CLI_MODEL``
  > ``VNSTOCK_CLAUDE_CLI_MODEL`` > mặc định CLI (chép số liệu cần độ chính xác).
* Được ăn cả: một lượt hỏng ⇒ KHÔNG ghi gì (text nửa vời digest ra kết luận sai).

Không tự chạy trong pipeline — gọi CÓ CHỦ ĐÍCH (nút 👁 tab Báo cáo hoặc CLI)::

    python vnstock_report_vision.py <id>          # đọc 1 báo cáo
    python vnstock_report_vision.py --all         # mọi báo cáo 🖼 có file gốc
    python vnstock_report_vision.py <id> --dry-run   # chỉ đếm ảnh/trang, không gọi Claude
"""
from __future__ import annotations

import argparse
import io
import os
import posixpath
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import vnstock_claude_cli as vcc
import vnstock_reports as rp

VIA = "claude-vision"
TAG = "report_vision"
ENV_MODEL = "VNSTOCK_REPORT_VISION_CLI_MODEL"
ENV_TIMEOUT = "VNSTOCK_REPORT_VISION_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 900          # 8 ảnh dày bảng số có thể mất vài phút

IMAGES_PER_CALL = 8
PDF_PAGES_PER_CALL = 10          # Read nhận tối đa 20 trang/lượt — 10 cho chắc
MAX_SIDE = 2000                  # ảnh to hơn thu nhỏ (Claude tự hạ ~1.5K cạnh dài)
MIN_AREA = 40_000                # < 200×200 ⇒ icon/logo
MIN_SIDE = 60                    # vạch kẻ, banner mỏng
VECTOR_EXT = {".emf", ".wmf"}    # Pillow chỉ vẽ được trên Windows
SKIP_EXT = {".svg", ".svgz"}
PASS_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

VISION_SYSTEM = """Bạn chép báo cáo phân tích (vĩ mô/thị trường) từ ẢNH sang TEXT để một bước sau tóm tắt.
Quy tắc:
1. Chép NGUYÊN VĂN chữ trong ảnh, đúng ngôn ngữ gốc (Việt/Anh), đúng dấu như in — không dịch, không tóm tắt, không bình luận, không thêm/bớt dấu.
2. Giữ tiêu đề, gạch đầu dòng, MỌI con số kèm đơn vị và kỳ (Q3/2026, YoY, %, tỷ đồng…).
3. Bảng: mỗi hàng một dòng, các ô nối bằng " | ", giữ hàng tiêu đề.
4. Biểu đồ: dòng "Biểu đồ: <tiêu đề>", rồi các số IN trên hình (nhãn, trục, chú thích) kèm kỳ, rồi MỘT câu xu hướng nhìn thấy. KHÔNG ước lượng số không in trên hình.
5. Chữ mờ hoặc không chắc: ghi "[không đọc được]" — không đoán.
6. Ảnh trang trí (logo, ảnh bìa không chữ, icon): ghi "(trang trí)" rồi bỏ qua.
7. Mở đầu mỗi ảnh/trang bằng đúng nhãn hướng dẫn cho ("[Ảnh N]" hoặc "[Trang N]").
8. Chỉ trả về bản chép — không lời dẫn, không code block."""


# ── DOCX: lấy ảnh theo thứ tự ────────────────────────────────────────────────


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    """Id → đường dẫn trong zip, cho relationships của một part (bỏ External)."""
    base = posixpath.dirname(part)
    rels_name = posixpath.join(base, "_rels", posixpath.basename(part) + ".rels")
    try:
        root = ET.fromstring(z.read(rels_name))
    except Exception:
        return {}
    out = {}
    for rel in root.iter(f"{{{_PKG_REL_NS}}}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        rid, target = rel.get("Id"), rel.get("Target") or ""
        if rid and target:
            path = (target.lstrip("/") if target.startswith("/")
                    else posixpath.normpath(posixpath.join(base, target)))
            out[rid] = path
    return out


def docx_images(data: bytes) -> list[tuple[str, bytes]]:
    """Ảnh của DOCX theo thứ tự xuất hiện trong thân văn bản. Thân không trỏ
    ảnh nào (file lạ) ⇒ lấy mọi ``word/media/*`` theo tên. Zip hỏng ⇒ []."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return []
    names = set(z.namelist())
    media = sorted(n for n in names if n.startswith("word/media/"))
    order: list[str] = []
    for part in sorted(n for n in names if re.fullmatch(r"word/document\d*\.xml", n)):
        rels = _rels(z, part)
        try:
            root = ET.fromstring(z.read(part))
        except Exception:
            continue
        for el in root.iter():
            for key, val in el.attrib.items():
                if not key.startswith(f"{{{_REL_NS}}}"):
                    continue
                path = rels.get(val)
                if path in names and path.startswith("word/media/") and path not in order:
                    order.append(path)
    return [(n, z.read(n)) for n in (order or media)]


def prepare_image(name: str, data: bytes) -> "tuple[str, bytes] | None":
    """(đuôi, bytes) sẵn cho Claude, hoặc None = bỏ (vector không vẽ được,
    icon, file hỏng). Không có Pillow ⇒ chỉ cho qua ảnh raster sẵn."""
    ext = Path(name).suffix.lower()
    if ext in SKIP_EXT:
        return None
    try:
        from PIL import Image
    except ImportError:
        return (ext, data) if ext in PASS_EXT else None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()                         # EMF/WMF ngoài Windows ném ở đây
    except Exception:
        return None
    w, h = im.size
    if w * h < MIN_AREA or min(w, h) < MIN_SIDE:
        return None
    if ext in PASS_EXT and max(w, h) <= MAX_SIDE:
        return ext, data
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return ".png", buf.getvalue()


# ── Lập lượt đọc ─────────────────────────────────────────────────────────────


def pdf_page_count(data: bytes) -> "int | None":
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None


def chunks(n: int, size: int) -> list[tuple[int, int]]:
    """[(đầu, cuối)] 1-based, bao hai đầu."""
    return [(i, min(i + size - 1, n)) for i in range(1, n + 1, size)]


def plan(rec: dict, data: bytes) -> dict:
    """Kế hoạch đọc một báo cáo — thuần, không gọi Claude.
    {kind, files: {tên: bytes}, jobs: [user prompt], skipped, n_units}"""
    head = _report_head(rec)
    if rec.get("kind") == "docx":
        files, skipped = {}, 0
        for src, raw in docx_images(data):
            got = prepare_image(src, raw)
            if got is None:
                skipped += 1
                continue
            files[f"img_{len(files) + 1:03d}{got[0]}"] = got[1]
        names = list(files)
        spans = chunks(len(names), IMAGES_PER_CALL)
        jobs = [_image_prompt(head, names[a - 1:b], a, k + 1, len(spans))
                for k, (a, b) in enumerate(spans)]
        return {"kind": "docx", "files": files, "jobs": jobs,
                "skipped": skipped, "n_units": len(names)}
    n = pdf_page_count(data)
    spans = chunks(n, PDF_PAGES_PER_CALL) if n else [(0, 0)]
    jobs = [_pdf_prompt(head, a, b, k + 1, len(spans))
            for k, (a, b) in enumerate(spans)]
    return {"kind": "pdf", "files": {"report.pdf": data}, "jobs": jobs,
            "skipped": 0, "n_units": n or 0}


def _report_head(rec: dict) -> str:
    bits = [rec.get("source"), rec.get("report_date")]
    meta = ", ".join(b for b in bits if b)
    title = rec.get("title") or rec.get("orig_name") or rec.get("id")
    return f"Báo cáo: {title}" + (f" ({meta})" if meta else "")


def _image_prompt(head: str, names: list[str], first: int, k: int, n: int) -> str:
    lines = "\n".join(f"- {nm}  → nhãn [Ảnh {first + i}]" for i, nm in enumerate(names))
    return (f"{head} — phần {k}/{n}.\n"
            "Dùng công cụ Read đọc LẦN LƯỢT các file ảnh sau trong thư mục hiện tại, "
            f"đúng thứ tự, rồi chép từng ảnh theo quy tắc:\n{lines}")


def _pdf_prompt(head: str, a: int, b: int, k: int, n: int) -> str:
    if not a:
        rng = "toàn bộ file (nếu Read đòi pages thì đọc từng 10 trang)"
    else:
        rng = f'pages="{a}-{b}"' if b > a else f'pages="{a}"'
    return (f"{head} — phần {k}/{n}.\n"
            f"Dùng công cụ Read đọc file report.pdf trong thư mục hiện tại với {rng}, "
            "rồi chép từng trang theo quy tắc, mở đầu mỗi trang bằng nhãn "
            "[Trang N] (N = số trang trong file).")


# ── Chạy ─────────────────────────────────────────────────────────────────────


def _timeout_s() -> int:
    raw = (os.environ.get(ENV_TIMEOUT) or "").strip()
    try:
        return max(60, int(raw)) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S


def read_report(rid: str, *, dry_run: bool = False, log=print) -> dict:
    """Đọc ảnh một báo cáo bằng Claude Code. Trả {ok, error, chars, cost_usd,
    n_units, n_jobs, skipped}; ok=True ⇒ đã ``set_text``. KHÔNG bao giờ ném."""
    out = {"ok": False, "error": None, "chars": 0, "cost_usd": 0.0,
           "n_units": 0, "n_jobs": 0, "skipped": 0}
    rec = next((r for r in rp.list_reports() if r["id"] == rid), None)
    if rec is None:
        out["error"] = f"không có báo cáo id {rid}"
        return out
    src = rp.original_path(rid)
    if src is None:
        out["error"] = "không còn file gốc PDF/DOCX (báo cáo URL/text không có ảnh để đọc)"
        return out
    try:
        p = plan(rec, src.read_bytes())
    except Exception as e:
        out["error"] = f"không mở được file gốc: {type(e).__name__}: {e}"
        return out
    out.update(n_units=p["n_units"], n_jobs=len(p["jobs"]), skipped=p["skipped"])
    unit = "ảnh" if p["kind"] == "docx" else "trang"
    log(f"[vision] {rid}: {p['n_units']} {unit} → {len(p['jobs'])} lượt Claude"
        + (f" · bỏ {p['skipped']} ảnh (icon/vector không vẽ được)" if p["skipped"] else ""))
    if not p["jobs"]:
        out["error"] = (f"không có ảnh nào đọc được (bỏ {p['skipped']}: icon / EMF-WMF "
                        "ngoài Windows / SVG)")
        return out
    if dry_run:
        out["ok"] = True
        return out
    parts = []
    with tempfile.TemporaryDirectory(prefix="vnstock_vision_") as td:
        for name, raw in p["files"].items():
            Path(td, name).write_bytes(raw)
        for k, job in enumerate(p["jobs"], 1):
            text, err, info = vcc.complete(
                job, system=VISION_SYSTEM, model=vcc.cli_model(ENV_MODEL),
                timeout_s=_timeout_s(), tag=TAG, tools="Read", cwd=td)
            log(vcc.outcome_line(f"vision {k}/{len(p['jobs'])}", info, text, err))
            if isinstance(info.get("cost_usd"), (int, float)):
                out["cost_usd"] += info["cost_usd"]
            if err or not text.strip():
                out["error"] = f"lượt {k}/{len(p['jobs'])} hỏng: {err or 'trả rỗng'}"
                return out
            parts.append(text.strip())
    text = "\n\n".join(parts)
    if len(text) < rp._NO_TEXT_LAYER_CHARS:
        out["error"] = (f"Claude chỉ chép được {len(text)} ký tự — không ghi"
                        f" (bản chép: {text[:150]!r})")
        return out
    rp.set_text(rid, text, VIA)
    out.update(ok=True, chars=len(text))
    return out


def pending() -> list[dict]:
    """Báo cáo 🖼 không trích được chữ mà còn file gốc."""
    return [r for r in rp.list_reports()
            if r.get("no_text_layer") and rp.original_path(r["id"]) is not None]


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Claude Code đọc ảnh báo cáo không có lớp text")
    ap.add_argument("id", nargs="?", help="id báo cáo (xem `vnstock_reports.py --list`)")
    ap.add_argument("--all", action="store_true", help="mọi báo cáo 🖼 còn file gốc")
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm ảnh/trang, không gọi Claude")
    a = ap.parse_args(argv)
    ids = [r["id"] for r in pending()] if a.all else ([a.id] if a.id else [])
    if not ids:
        print("[vision] không có gì để đọc — truyền <id> hoặc --all "
              "(--all chỉ lấy báo cáo 🖼 còn file gốc)")
        return 0 if a.all else 2
    rc = 0
    for rid in ids:
        res = read_report(rid, dry_run=a.dry_run)
        if res["ok"] and not a.dry_run:
            rec = next((r for r in rp.list_reports() if r["id"] == rid), {})
            tail = ("✅ vào phân tích — chạy 🧠 Digest" if rp.in_analysis(rec)
                    else "⚠ còn thiếu ngày/nguồn — `vnstock_reports.py --set-meta`")
            print(f"[vision] {rid}: ✅ {res['chars']:,} ký tự · ${res['cost_usd']:,.2f} · {tail}")
        elif not res["ok"]:
            print(f"[vision] {rid}: ❌ {res['error']}")
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
