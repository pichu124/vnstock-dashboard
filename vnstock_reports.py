#!/usr/bin/env python3
"""vnstock_reports.py — Ingest báo cáo vĩ mô (Phase 2 của thiết kế Phân bổ tài sản).

Tại sao có module này
---------------------
Thiết kế "Báo cáo vĩ mô upload + Phân bổ tài sản" (user duyệt 2026-07-13):
user upload báo cáo hay của CTCK/chuyên gia (PDF, cả Việt lẫn Anh) hoặc dán
URL/text → thư viện báo cáo có metadata, để P3 digest bằng LLM rồi tilt ±1
band phân bổ. Phase 2 = ĐÚNG tầng ingest: nhận file/URL/text, trích text,
dedup, quản metadata — **KHÔNG LLM, KHÔNG số nào vào registry vĩ mô**.

Nguyên tắc (từ thiết kế đã duyệt):
* **Dedup sha256** — id = sha256 của nội dung canonical (PDF: bytes; URL:
  chuỗi URL chuẩn hoá; text: text chuẩn hoá). Upload lại cùng file (Streamlit
  rerun) → CÙNG id, chỉ merge metadata mới, không nhân bản.
* **Metadata BẮT BUỘC để vào phân tích**: ``report_date`` (YYYY-MM-DD) +
  ``source`` (tên CTCK/chuyên gia). Thiếu → báo cáo CHỈ nằm thư viện
  (``in_analysis=False``), bổ sung sau bằng ``--set-meta``.
* **PDF scan không lớp text** → flag ``no_text_layer`` (giữ trong thư viện,
  không vào phân tích — không có gì để digest).
* Ghi ATOMIC (tmp + os.replace) vì Streamlit upload đụng pipeline recompute.

Trích text:
* PDF → tái dùng ``vnstock_vbma.pdf_to_text`` (pdftotext -layout → pypdf).
* URL → Jina Reader (``https://r.jina.ai/<URL>`` — free, không cần key; cùng
  đường news_feeds đang dùng) nhưng KHÔNG cắt 1.800 ký tự như tin — báo cáo
  giữ tới ``_REPORT_MAX_CHARS``; fail/chặn mạng → không lưu gì (best-effort).
  Sandbox/web session: r.jina.ai bị allowlist chặn → --add-url luôn fail ở
  đây, KHÔNG phải bug.

Lưu trữ:
* Index ``data_warehouse/_meta/reports_index.json`` — metadata mọi báo cáo.
* Text đã trích ``data_warehouse/_meta/reports/<id>.txt``; PDF gốc giữ kèm
  ``<id>.pdf`` (để P3 ``--redigest`` khi extractor/prompt đổi).

CLI::

    python vnstock_reports.py --add bao_cao.pdf --source "VNDirect" \
        --report-date 2026-07-10 [--title "..."]
    python vnstock_reports.py --add-url https://... --source ... --report-date ...
    python vnstock_reports.py --add-text "..." / --add-text - (đọc stdin)
    python vnstock_reports.py --list
    python vnstock_reports.py --show <id>
    python vnstock_reports.py --set-meta <id> --source ... --report-date ...
    python vnstock_reports.py --remove <id>
    python vnstock_reports.py --diag   # thử Jina Reader (cần mạng)

Tiêu thụ (P3): ``load_for_analysis()`` — báo cáo đủ metadata + có text +
tuổi ≤ ``_MAX_AGE_DAYS`` (90 — weight decay chi tiết là việc của digest P3).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"
_INDEX = _META / "reports_index.json"
_STORE = _META / "reports"

# Text ngắn hơn ngưỡng này sau khi trích PDF = coi như KHÔNG có lớp text
# (PDF scan) — vẫn nằm thư viện nhưng không vào phân tích.
_NO_TEXT_LAYER_CHARS = 200

# Báo cáo giữ dài hơn tin nhiều (news_feeds cắt 1.800 cho prompt tin); cap này
# chỉ chống file bất thường — P3 tự cắt theo budget token khi digest.
_REPORT_MAX_CHARS = 200_000

# Quá tuổi này thì load_for_analysis bỏ qua (thiết kế: weight=0 ở 90 ngày;
# decay mượt từ 30 ngày là việc của digest P3).
_MAX_AGE_DAYS = 90

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_JINA_BASE = "https://r.jina.ai/"
_URL_TIMEOUT = 30

_MD_NOISE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")   # ảnh markdown
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")   # [text](url) → text


# ── id / chuẩn hoá ───────────────────────────────────────────────────────────


def _sha_id(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _valid_date(s: "str | None") -> "str | None":
    """report_date hợp lệ (YYYY-MM-DD, không ở tương lai xa) hoặc None."""
    if not s:
        return None
    try:
        d = date.fromisoformat(str(s).strip())
    except ValueError:
        print(f"[reports] ⚠ report_date '{s}' không phải YYYY-MM-DD — bỏ qua, "
              f"bổ sung sau bằng --set-meta")
        return None
    if d > date.today():
        print(f"[reports] ⚠ report_date '{s}' ở tương lai — bỏ qua")
        return None
    return d.isoformat()


# ── Index I/O (atomic) ───────────────────────────────────────────────────────


def _load_index() -> dict:
    try:
        if _INDEX.exists():
            return json.loads(_INDEX.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _write_index(idx: dict) -> None:
    _INDEX.parent.mkdir(parents=True, exist_ok=True)
    idx["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = _INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _INDEX)


def _text_path(rid: str) -> Path:
    return _STORE / f"{rid}.txt"


def _pdf_path(rid: str) -> Path:
    return _STORE / f"{rid}.pdf"


def _docx_path(rid: str) -> Path:
    return _STORE / f"{rid}.docx"


# ── Trích text ───────────────────────────────────────────────────────────────


def fetch_url_text(url: str, timeout: int = _URL_TIMEOUT) -> str:
    """Toàn văn một URL báo cáo qua Jina Reader — '' khi fail (best-effort).

    Khác ``vnstock_news_feeds.fetch_fulltext``: GIỮ xuống dòng (cấu trúc mục
    của báo cáo có ích cho digest) và cap ``_REPORT_MAX_CHARS`` thay vì 1.800.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        import requests as _req
        headers = {"User-Agent": _UA, "Accept": "text/plain",
                   "X-Return-Format": "markdown"}
        jina_key = (os.environ.get("JINA_API_KEY") or "").strip()
        if jina_key:
            headers["Authorization"] = f"Bearer {jina_key}"
        resp = _req.get(f"{_JINA_BASE}{url}", headers=headers, timeout=timeout)
        resp.raise_for_status()
        text = resp.text or ""
    except Exception:
        return ""
    _, sep, body = text.partition("Markdown Content:")
    if sep:
        text = body
    text = _MD_NOISE_RE.sub(" ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:_REPORT_MAX_CHARS]


def docx_to_text(data: bytes) -> str:
    """DOCX → text bằng STDLIB (zipfile + xml.etree) — KHÔNG thêm dependency
    (mirror parser RSS stdlib của news_feeds). DOCX là zip; part chính chuẩn
    là ``word/document.xml`` nhưng một số tool ghi ``document2.xml``/tên khác
    → quét mọi ``word/*.xml`` có node ``<w:t>``. ``root.iter`` bắt cả text
    trong bảng/textbox (đều là ``<w:p>`` lồng sâu). '' khi file hỏng/không
    phải docx — dùng ``docx_failure_hint`` để biết VÌ SAO."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return ""
    names = sorted(z.namelist())
    main = [n for n in names if re.fullmatch(r"word/document\d*\.xml", n)]
    rest = [n for n in names
            if n.startswith("word/") and n.endswith(".xml") and n not in main]
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for name in main + rest:
        try:
            root = ET.fromstring(z.read(name))
        except Exception:
            continue
        paras = []
        for para in root.iter(f"{ns}p"):
            text = "".join(t.text or "" for t in para.iter(f"{ns}t"))
            if text.strip():
                paras.append(text.strip())
        if paras:
            return "\n".join(paras)
    return ""


def docx_failure_hint(data: bytes) -> str:
    """Chẩn đoán 1 dòng khi docx_to_text ra rỗng — phân biệt theo chữ ký bytes
    (bắt được khi verify 14/07: Q3.docx ra 0 ký tự không rõ vì sao)."""
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ("đây là .DOC định dạng CŨ (OLE) đổi đuôi — mở bằng Word rồi "
                "Save As → .docx thật")
    if data[:2] != b"PK":
        return ("nội dung không phải docx (file placeholder Dropbox "
                "online-only? — chuột phải file → 'Make available offline' "
                "rồi thử lại)")
    return ("docx là zip hợp lệ nhưng không tìm thấy text — file chỉ có "
            "ảnh/scan? Thử mở Word xem có bôi đen copy được chữ không")


# ── Ingest core ──────────────────────────────────────────────────────────────


def _upsert(rid: str, kind: str, text: "str | None", *,
            report_date: "str | None" = None, source: "str | None" = None,
            title: "str | None" = None, url: "str | None" = None,
            orig_name: "str | None" = None,
            pdf_bytes: "bytes | None" = None) -> dict:
    """Tạo/merge record + ghi file text (và PDF gốc nếu có). Idempotent:
    id đã có → chỉ merge metadata MỚI (arg không rỗng thắng), không nhân bản."""
    idx = _load_index()
    reports = idx.setdefault("reports", {})
    rec = reports.get(rid) or {
        "id": rid, "kind": kind,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    duplicate = rid in reports

    text = (text or "").strip()[:_REPORT_MAX_CHARS]
    if text:
        _STORE.mkdir(parents=True, exist_ok=True)
        _text_path(rid).write_text(text, encoding="utf-8")
    if pdf_bytes:
        _STORE.mkdir(parents=True, exist_ok=True)
        orig = _docx_path(rid) if kind == "docx" else _pdf_path(rid)
        orig.write_bytes(pdf_bytes)

    rec["chars"] = len(text)
    rec["no_text_layer"] = (kind in ("pdf", "docx")
                            and len(text) < _NO_TEXT_LAYER_CHARS)
    for key, val in (("report_date", _valid_date(report_date)),
                     ("source", (source or "").strip() or None),
                     ("title", (title or "").strip() or None),
                     ("url", url), ("orig_name", orig_name)):
        if val:
            rec[key] = val

    reports[rid] = rec
    _write_index(idx)

    if duplicate:
        print(f"[reports] id {rid} đã có (dedup sha256) — merge metadata, "
              f"không nhân bản")
    if not in_analysis(rec):
        print(f"[reports] ⚠ {rid}: {_why_library_only(rec)} — báo cáo chỉ nằm "
              f"thư viện, chưa vào phân tích")
    return rec


def in_analysis(rec: dict) -> bool:
    """Đủ điều kiện vào phân tích (P3 digest): có report_date + source + text."""
    return bool(rec.get("report_date") and rec.get("source")
                and rec.get("chars", 0) >= _NO_TEXT_LAYER_CHARS
                and not rec.get("no_text_layer"))


def _why_library_only(rec: dict) -> str:
    miss = []
    if not rec.get("report_date"):
        miss.append("thiếu report_date")
    if not rec.get("source"):
        miss.append("thiếu source")
    if rec.get("no_text_layer"):
        miss.append("PDF không có lớp text (scan?)")
    elif rec.get("chars", 0) < _NO_TEXT_LAYER_CHARS:
        miss.append("text quá ngắn")
    return ", ".join(miss) or "?"


def add_pdf(path: "str | Path", *, report_date: "str | None" = None,
            source: "str | None" = None,
            title: "str | None" = None) -> "dict | None":
    """Ingest 1 file báo cáo — PDF (vnstock_vbma.pdf_to_text) hoặc DOCX
    (docx_to_text stdlib). sha256(bytes) làm id; giữ file gốc cho
    --redigest (P3). Tên hàm giữ 'add_pdf' vì UI/tests đã gọi."""
    p = Path(path)
    if p.is_dir():
        # Windows trả 'Permission denied' khi read_bytes() một THƯ MỤC — thông
        # báo gây hiểu nhầm (user dán đường dẫn folder Dropbox, verify 14/07).
        files = sorted(list(p.glob("*.pdf")) + list(p.glob("*.docx")))
        hint = (f" (trong đó có {len(files)} PDF/DOCX, vd: {files[0].name})"
                if files else "")
        print(f"[reports] ❌ {p} là THƯ MỤC — --add nhận 1 FILE PDF/DOCX{hint}")
        return None
    try:
        data = p.read_bytes()
    except OSError as e:
        print(f"[reports] ❌ không đọc được {p}: {e}")
        return None
    if not data:
        print(f"[reports] ❌ {p} rỗng")
        return None
    kind = "docx" if p.suffix.lower() == ".docx" else "pdf"
    try:
        if kind == "docx":
            text = docx_to_text(data)
        else:
            from vnstock_vbma import pdf_to_text
            text = pdf_to_text(data) or ""
    except Exception as e:
        print(f"[reports] ⚠ trích text lỗi ({type(e).__name__}: {e}) — lưu "
              f"file gốc, đánh dấu no_text_layer")
        text = ""
    if not text.strip():
        reason = (docx_failure_hint(data) if kind == "docx"
                  else "PDF scan? thiếu pdftotext/pypdf?")
        print(f"[reports] ⚠ {p.name}: không trích được text — {reason}")
    return _upsert(_sha_id(data), kind, text, report_date=report_date,
                   source=source, title=title or p.stem, orig_name=p.name,
                   pdf_bytes=data)


def add_url(url: str, *, report_date: "str | None" = None,
            source: "str | None" = None,
            title: "str | None" = None) -> "dict | None":
    """Ingest 1 URL báo cáo qua Jina Reader. Fetch fail → KHÔNG lưu gì
    (không có nội dung thì không có gì để dedup/digest)."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        print(f"[reports] ❌ URL không hợp lệ: {url!r}")
        return None
    text = fetch_url_text(url)
    if not text:
        print("[reports] ❌ không lấy được nội dung qua Jina Reader "
              "(mạng bị chặn / URL hỏng?) — không lưu. Sandbox/web session "
              "chặn r.jina.ai là bình thường; thử trên máy có mạng.")
        return None
    return _upsert(_sha_id(url.encode("utf-8")), "url", text,
                   report_date=report_date, source=source, title=title,
                   url=url)


def add_text(text: str, *, report_date: "str | None" = None,
             source: "str | None" = None,
             title: "str | None" = None) -> "dict | None":
    """Ingest text dán trực tiếp. id = sha256(text chuẩn hoá whitespace) —
    dán lại cùng nội dung (kể cả khác xuống dòng) → cùng id."""
    if not (text or "").strip():
        print("[reports] ❌ text rỗng")
        return None
    return _upsert(_sha_id(_norm_text(text).encode("utf-8")), "text", text,
                   report_date=report_date, source=source, title=title)


def set_meta(rid: str, *, report_date: "str | None" = None,
             source: "str | None" = None,
             title: "str | None" = None) -> "dict | None":
    """Bổ sung metadata cho báo cáo đã ingest (đường hoàn thiện 'thư viện →
    phân tích')."""
    idx = _load_index()
    rec = (idx.get("reports") or {}).get(rid)
    if rec is None:
        print(f"[reports] ❌ không có id {rid} — xem --list")
        return None
    for key, val in (("report_date", _valid_date(report_date)),
                     ("source", (source or "").strip() or None),
                     ("title", (title or "").strip() or None)):
        if val:
            rec[key] = val
    _write_index(idx)
    status = "✅ vào phân tích" if in_analysis(rec) else \
        f"⚠ vẫn chỉ nằm thư viện ({_why_library_only(rec)})"
    print(f"[reports] {rid}: {status}")
    return rec


def set_digest(rid: str, digest: dict) -> "dict | None":
    """Ghi digest (P3 — vnstock_report_digest) vào record. Digest sống trong
    index cùng metadata: một nguồn sự thật, xóa báo cáo là digest đi theo."""
    idx = _load_index()
    rec = (idx.get("reports") or {}).get(rid)
    if rec is None:
        print(f"[reports] ❌ không có id {rid} để gắn digest")
        return None
    rec["digest"] = digest
    _write_index(idx)
    return rec


def remove(rid: str) -> bool:
    idx = _load_index()
    reports = idx.get("reports") or {}
    if rid not in reports:
        print(f"[reports] ❌ không có id {rid}")
        return False
    reports.pop(rid)
    _write_index(idx)
    for p in (_text_path(rid), _pdf_path(rid), _docx_path(rid)):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    print(f"[reports] đã xóa {rid}")
    return True


# ── Loaders (cho P3 digest / P5 UI) ─────────────────────────────────────────


def list_reports() -> list[dict]:
    """Mọi báo cáo, mới nhất trước (report_date rồi added_at)."""
    reports = list((_load_index().get("reports") or {}).values())
    reports.sort(key=lambda r: (r.get("report_date") or "",
                                r.get("added_at") or ""), reverse=True)
    return reports


def load_report_text(rid: str) -> str:
    try:
        p = _text_path(rid)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        return ""


def load_for_analysis(as_of: "str | None" = None,
                      max_age_days: int = _MAX_AGE_DAYS) -> list[dict]:
    """Báo cáo đủ điều kiện digest: metadata đầy đủ + có text + tuổi ≤
    ``max_age_days`` so với ``as_of`` (mặc định hôm nay). Mỗi record kèm
    ``age_days`` để P3 tính decay (giảm từ 30 ngày, weight=0 ở 90)."""
    anchor = date.fromisoformat(as_of) if as_of else date.today()
    out: list[dict] = []
    for rec in list_reports():
        if not in_analysis(rec):
            continue
        age = (anchor - date.fromisoformat(rec["report_date"])).days
        if age < 0 or age > max_age_days:
            continue
        out.append({**rec, "age_days": age})
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────


def _fmt_row(rec: dict) -> str:
    flag = "✅" if in_analysis(rec) else \
        ("🖼" if rec.get("no_text_layer") else "📥")
    return (f"  {flag} {rec['id']}  [{rec['kind']:<4}] "
            f"{rec.get('report_date') or '????-??-??'}  "
            f"{(rec.get('source') or '—'):<18.18} "
            f"{(rec.get('title') or rec.get('url') or ''):<40.40} "
            f"({rec.get('chars', 0):,} ký tự)")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Thư viện báo cáo vĩ mô (ingest PDF/URL/text — Phase 2)")
    ap.add_argument("--add", metavar="FILE", help="ingest 1 file PDF/DOCX")
    ap.add_argument("--add-url", metavar="URL",
                    help="ingest 1 URL qua Jina Reader (cần mạng)")
    ap.add_argument("--add-text", metavar="TEXT",
                    help="ingest text dán trực tiếp ('-' = đọc stdin)")
    ap.add_argument("--report-date", default=None, metavar="YYYY-MM-DD",
                    help="ngày báo cáo (BẮT BUỘC để vào phân tích)")
    ap.add_argument("--source", default=None,
                    help="nguồn CTCK/chuyên gia (BẮT BUỘC để vào phân tích)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--list", action="store_true", help="liệt kê thư viện")
    ap.add_argument("--show", metavar="ID", help="in metadata + đầu text 1 báo cáo")
    ap.add_argument("--set-meta", metavar="ID",
                    help="bổ sung report-date/source/title cho id đã có")
    ap.add_argument("--remove", metavar="ID")
    ap.add_argument("--diag", action="store_true",
                    help="thử Jina Reader 1 lần (chạy trên máy có mạng)")
    args = ap.parse_args(argv)

    meta = {"report_date": args.report_date, "source": args.source,
            "title": args.title}
    if args.add:
        return 0 if add_pdf(args.add, **meta) else 1
    if args.add_url:
        return 0 if add_url(args.add_url, **meta) else 1
    if args.add_text is not None:
        text = sys.stdin.read() if args.add_text == "-" else args.add_text
        return 0 if add_text(text, **meta) else 1
    if args.set_meta:
        return 0 if set_meta(args.set_meta, **meta) else 1
    if args.remove:
        return 0 if remove(args.remove) else 1
    if args.show:
        rec = (_load_index().get("reports") or {}).get(args.show)
        if rec is None:
            print(f"[reports] ❌ không có id {args.show}")
            return 1
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        body = load_report_text(args.show)
        if body:
            print("─" * 60)
            print(body[:1500])
        return 0
    if args.diag:
        body = fetch_url_text("https://vneconomy.vn/")
        print(f"Jina Reader: {'OK, ' + f'{len(body):,}' + ' ký tự' if body else 'FAIL — mạng chặn r.jina.ai / cần verify trên máy có mạng'}")
        return 0 if body else 1

    # mặc định: --list
    reports = list_reports()
    if not reports:
        print("[reports] thư viện trống — thêm bằng --add / --add-url / --add-text")
        return 0
    ready = sum(1 for r in reports if in_analysis(r))
    print(f"📚 Thư viện báo cáo: {len(reports)} bản, {ready} đủ điều kiện "
          f"phân tích (✅) — 📥 thiếu metadata, 🖼 PDF không lớp text")
    for rec in reports:
        print(_fmt_row(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
