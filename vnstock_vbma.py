"""
vnstock_vbma.py — Lãi suất liên ngân hàng + lợi suất TPCP từ báo cáo tuần VBMA.

VBMA (Hiệp hội Thị trường Trái phiếu Việt Nam) công bố "Bản tin thị trường
trái phiếu hàng tuần" dạng PDF, tải tự do không cần đăng nhập — nguồn free
hiếm hoi có lãi suất liên ngân hàng (Vietstock VNIBOR tường phí bản Basic,
xác minh 2026-06-14) và lợi suất TPCP. Cadence TUẦN — hợp brief hằng ngày
hơn mọi nguồn monthly. (Nguồn phát hiện qua khảo sát skill vimovietnam.)

Pipeline (best-effort từng bước — lỗi bước nào trả None bước đó, KHÔNG bịa):
  1. Scrape trang listing báo cáo tuần → link .pdf mới nhất (tên file mang
     khoảng ngày DDMMYYYY-DDMMYYYY → as_of = ngày CUỐI tuần báo cáo).
  2. Tải PDF (URL có thể chứa dấu cách → quote).
  3. PDF → text: ưu tiên ``pdftotext -layout`` (poppler) nếu có trên PATH,
     fallback thư viện ``pypdf`` nếu import được. Cả hai thiếu → None.
  4. Regex số theo NHÃN DÒNG trong đúng SECTION ("liên ngân hàng" cho ON/1W,
     "lợi suất/trái phiếu" cho 10Y) + sanity range. KHÔNG dùng LLM — mọi con
     số vào registry vĩ mô phải deterministic.

⚠️ Sandbox dev bị chặn egress — verify trên máy có mạng:
    python vnstock_vbma.py --diag          # in URL PDF chọn + số parse được
    python vnstock_vbma.py --diag --dump   # in thêm raw text để chỉnh regex
Nếu ``vbma.org.vn`` chưa có trong allowlist mạng thì cần thêm.

Tiêu thụ: ``vnstock_macro.refresh()`` gọi ``fetch_weekly()`` và ghi vào
registry (interbank_on / interbank_1w / govt_bond_yield_10y, source="vbma").
``--set`` tay vẫn luôn là đường sống — fetch lỗi không bao giờ đè cache cũ.
Tắt hẳn: env ``VNSTOCK_MACRO_VBMA=0``.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_LISTING_URLS = (
    "https://vbma.org.vn/vi/reports/weekly",
    "https://vbma.org.vn/reports/weekly",
)

_TIMEOUT_HTML = 15
_TIMEOUT_PDF = 30

# Sanity range (%/năm) — số ngoài khoảng coi như parse trúng ô khác, bỏ.
_RANGES = {
    "interbank_on": (0.0, 20.0),
    "interbank_1w": (0.0, 20.0),
    "govt_bond_yield_10y": (1.0, 10.0),
}

# Anchor mở section trong text PDF (± _SECTION_SPAN dòng quanh anchor).
_SECTIONS = {
    "interbank": re.compile(r"liên\s*ngân\s*hàng|interbank", re.I),
    "bond": re.compile(r"lợi\s*suất|trái\s*phiếu\s*chính\s*phủ|government\s*bond|yield", re.I),
}
_SECTION_SPAN = 25

# Nhãn dòng theo section. "ON"/"1W" chỉ tin trong section liên-ngân-hàng
# (chữ "on" tiếng Anh quá phổ biến để tìm toàn văn).
_LABELS = {
    "interbank_on": ("interbank", re.compile(r"qua\s*đêm|overnight|\bON\b", re.I)),
    "interbank_1w": ("interbank", re.compile(r"1\s*tuần|1\s*week|\b1W\b", re.I)),
    "govt_bond_yield_10y": ("bond", re.compile(r"10\s*năm|\b10Y\b|10\s*year", re.I)),
}

_NUM = re.compile(r"(\d{1,2}[.,]\d{1,3})\s*%?")


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


# ── Bước 1: listing → PDF mới nhất ───────────────────────────────────────────

def fetch_listing_html() -> "str | None":
    for url in _LISTING_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT_HTML)
            if r.status_code == 200 and r.text:
                return r.text
        except requests.RequestException:
            continue
    return None


_PDF_HREF = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
_DATE_RANGE = re.compile(r"(\d{8})\s*-\s*(\d{8})")


def find_latest_pdf(html: str) -> "tuple[str, str] | None":
    """(url, as_of_iso) của báo cáo tuần mới nhất.

    Chọn theo NGÀY CUỐI trong tên file (pattern DDMMYYYY-DDMMYYYY) thay vì
    thứ tự trên trang — bền hơn khi listing sắp xếp lại. Không dựng URL từ
    pattern (suffix tên file của VBMA không nhất quán) — chỉ scrape href.
    """
    best: "tuple[str, object] | None" = None
    for href in _PDF_HREF.findall(html or ""):
        m = _DATE_RANGE.search(href)
        if not m:
            continue
        try:
            end = datetime.strptime(m.group(2), "%d%m%Y").date()
        except ValueError:
            continue
        if best is None or end > best[1]:
            best = (href, end)
    if best is None:
        return None
    url, end = best
    if url.startswith("/"):
        url = "https://vbma.org.vn" + url
    url = quote(url, safe=":/%?&=")          # tên file VBMA hay chứa dấu cách
    return url, end.isoformat()


def download_pdf(url: str) -> "bytes | None":
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT_PDF)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except requests.RequestException:
        pass
    return None


# ── Bước 3: PDF → text ───────────────────────────────────────────────────────

def pdf_to_text(data: bytes) -> "str | None":
    """pdftotext -layout (giữ cột bảng) → fallback pypdf → None."""
    exe = shutil.which("pdftotext")
    if exe:
        try:
            with tempfile.TemporaryDirectory() as td:
                pin = Path(td) / "r.pdf"
                pout = Path(td) / "r.txt"
                pin.write_bytes(data)
                subprocess.run([exe, "-layout", str(pin), str(pout)],
                               timeout=60, check=True, capture_output=True)
                return pout.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None


# ── Bước 4: text → số ────────────────────────────────────────────────────────

def _section_lines(lines: "list[str]", anchor: re.Pattern) -> "list[str]":
    """Các dòng trong ± _SECTION_SPAN quanh MỌI anchor khớp (gộp, giữ thứ tự)."""
    idx: set[int] = set()
    for i, line in enumerate(lines):
        if anchor.search(line):
            idx.update(range(max(0, i - 2), min(len(lines), i + _SECTION_SPAN)))
    return [lines[i] for i in sorted(idx)]


def extract_rates(text: str) -> dict:
    """{key: value} cho các chỉ số parse được (chỉ nhận giá trị trong range)."""
    out: dict = {}
    if not text:
        return out
    lines = text.splitlines()
    scoped = {name: _section_lines(lines, pat) for name, pat in _SECTIONS.items()}
    for key, (section, label) in _LABELS.items():
        for line in scoped.get(section, []):
            if not label.search(line):
                continue
            m = _NUM.search(line)
            if not m:
                continue
            v = _to_float(m.group(1))
            lo, hi = _RANGES[key]
            if lo <= v <= hi:
                out[key] = v
                break
    return out


# ── End-to-end ───────────────────────────────────────────────────────────────

def fetch_weekly() -> "dict | None":
    """Fetch + parse báo cáo tuần mới nhất.

    Trả ``{"as_of": ISO, "source_url": ..., <key>: value...}`` hoặc None khi
    bất kỳ bước nào hỏng / không parse được số nào (caller giữ cache cũ).
    """
    html = fetch_listing_html()
    if not html:
        return None
    hit = find_latest_pdf(html)
    if hit is None:
        return None
    url, as_of = hit
    data = download_pdf(url)
    if data is None:
        return None
    rates = extract_rates(pdf_to_text(data) or "")
    if not rates:
        return None
    rates["as_of"] = as_of
    rates["source_url"] = url
    return rates


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="VBMA weekly PDF — diag")
    ap.add_argument("--diag", action="store_true",
                    help="Fetch thử 1 lần, in URL + số parse được")
    ap.add_argument("--dump", action="store_true",
                    help="Kèm --diag: in raw text (chỉnh regex khi lệch layout)")
    args = ap.parse_args(argv)

    if not args.diag:
        ap.print_help()
        return 0

    html = fetch_listing_html()
    print(f"listing: {'OK' if html else 'FAIL (mạng/allowlist? cần vbma.org.vn)'}")
    if not html:
        return 1
    hit = find_latest_pdf(html)
    print(f"pdf mới nhất: {hit if hit else 'KHÔNG tìm thấy href .pdf có khoảng ngày'}")
    if not hit:
        return 1
    data = download_pdf(hit[0])
    print(f"download: {len(data):,} bytes" if data else "download: FAIL")
    if not data:
        return 1
    text = pdf_to_text(data)
    print(f"pdf→text: {'OK, ' + str(len(text)) + ' ký tự' if text else 'FAIL (cần pdftotext hoặc pip install pypdf)'}")
    if not text:
        return 1
    if args.dump:
        print("─" * 60)
        print(text)
        print("─" * 60)
    rates = extract_rates(text)
    print(f"parse: {rates if rates else 'KHÔNG bắt được số nào — chạy lại với --dump gửi text để chỉnh regex'}")
    return 0 if rates else 1


if __name__ == "__main__":
    raise SystemExit(main())
