"""
vnstock_vbma.py — Lãi suất liên ngân hàng + lợi suất TPCP từ báo cáo tuần VBMA.

VBMA (Hiệp hội Thị trường Trái phiếu Việt Nam) công bố "Bản tin thị trường
trái phiếu hàng tuần" dạng PDF, tải tự do không cần đăng nhập — nguồn free
hiếm hoi có lãi suất liên ngân hàng (Vietstock VNIBOR tường phí bản Basic,
xác minh 2026-06-14) và lợi suất TPCP. Cadence TUẦN — hợp brief hằng ngày
hơn mọi nguồn monthly. (Nguồn phát hiện qua khảo sát skill vimovietnam.)

Pipeline (best-effort từng bước — lỗi bước nào trả None bước đó, KHÔNG bịa):
  1. Scrape trang listing báo cáo tuần → link .pdf mới nhất (tên file mang
     2 ngày DDMMYYYY nối liền hoặc có gạch, vd "2906202603072026_BAO_CAO..."
     → as_of = ngày CUỐI tuần báo cáo).
  2. Tải PDF (URL có thể chứa dấu cách → quote).
  3. PDF → text: ưu tiên ``pdftotext -layout`` (poppler) nếu có trên PATH,
     fallback thư viện ``pypdf`` nếu import được. Cả hai thiếu → None.
  4. Parse theo CẤU TRÚC BẢNG (chỉnh trên PDF thật tuần 29/06-03/07/2026):
     bảng LNH lấy cột NGÀY BÁO CÁO (không phải "TB 5 ngày"), lợi suất TPCP
     lấy từ ma trận tenor "10N"; văn xuôi chỉ làm fallback cấu trúc chặt
     ("qua đêm ON ... mức X%") + sanity range. KHÔNG dùng LLM — mọi con số
     vào registry vĩ mô phải deterministic.

Parse verify OK trên PDF thật (03/07/2026): ON 5.67 / 1W 6.17 / 10Y 4.40 —
khớp phần bình luận của chính báo cáo. Fetch (listing/download) CHƯA verify
được — sandbox dev chặn egress; chạy trên máy có mạng:
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

# Sanity range (%/năm; VND cho fx) — số ngoài khoảng coi như parse trúng ô khác, bỏ.
_RANGES = {
    "interbank_on": (0.0, 20.0),
    "interbank_1w": (0.0, 20.0),
    "govt_bond_yield_10y": (1.0, 10.0),
    "usdvnd_vcb_mid": (15000.0, 40000.0),
}

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
# Tên file thật nối liền 2 ngày KHÔNG dấu gạch: "2906202603072026_BAO_CAO_TUAN..."
_DATE_RANGE = re.compile(r"(\d{8})\s*-?\s*(\d{8})")


def find_latest_pdf(html: str) -> "tuple[str, str] | None":
    """(url, as_of_iso) của báo cáo tuần mới nhất.

    Chọn theo NGÀY CUỐI trong tên file (DDMMYYYY liền hoặc có gạch nối) thay
    vì thứ tự trên trang — bền hơn khi listing sắp xếp lại. Không dựng URL từ
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
    except BaseException as e:                     # pyo3 PanicException (cryptography
        if isinstance(e, (KeyboardInterrupt, SystemExit)):  # vỡ) kế thừa BaseException
            raise
        return None



# ── Parse theo CẤU TRÚC BẢNG THẬT (chỉnh theo PDF tuần 29/06-03/07/2026) ─────
#
# Bảng LNH (sau tiêu đề "LÃI SUẤT LIÊN NGÂN HÀNG"):
#   Đvị : %   TB 5 ngày   3/7/2026   26/6/2026   +/- so tuần trước (đcb)  ...
#      ON        6.89        5.67       2.91        276                   19
#      1W        6.94        6.17       7.35       -118                    3
# → giá trị ĐÚNG = cột ngày báo cáo (index 1 trong các số thập phân; cột đcb
#   là số nguyên nên regex thập phân tự loại). Header có "TB 5" thì tin idx 1.
#
# Lợi suất TPCP là MA TRẬN tenor (sau "BIẾN ĐỘNG LỢI SUẤT PHÒNG GIAO DỊCH"):
#      1N     2N     3N     5N     7N     10N    15N    20N    30N
#   3/7/2026  3.40%  3.50%  3.57%  4.20%  4.26%  4.40%  4.57%  ...
# → dòng header đếm vị trí "10N", dòng ngày đầu tiên bên dưới lấy % thứ đó.
#
# Văn xuôi ("...lên mức 9.26%... qua đêm và 1W...") KHÔNG được đụng tới —
# chỉ dùng làm FALLBACK có cấu trúc chặt ("qua đêm ON ... mức X%") khi bảng
# không parse được (layout đổi).

_DEC = re.compile(r"-?\d{1,2}[.,]\d{1,3}\b")       # số thập phân (loại cột đcb nguyên)
_PCT = re.compile(r"(\d{1,2}[.,]\d{1,3})\s*%")
_TENOR = re.compile(r"\b(\d{1,2})N\b")
_DATE_ROW = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\b")
_IB_TITLE = re.compile(r"LÃI\s*SUẤT\s*LIÊN\s*NGÂN\s*HÀNG|INTERBANK\s*RATES?", re.I)


def _in_range(key: str, v: float) -> bool:
    lo, hi = _RANGES[key]
    return lo <= v <= hi


def _parse_interbank(lines: "list[str]") -> dict:
    out: dict = {}
    for i, line in enumerate(lines):
        if not _IB_TITLE.search(line):
            continue
        block = lines[i:i + 20]
        # Anchor có thể khớp cả đoạn VĂN XUÔI "Lãi suất liên ngân hàng: ..."
        # đứng trước bảng → tìm header "TB 5 ngày" trong TOÀN block, không chỉ
        # vài dòng đầu (PDF thật 03/07/2026: văn xuôi ở dòng i, bảng ở i+11).
        header_has_tb5 = any("TB 5" in b for b in block)
        for row_label, key in (("ON", "interbank_on"), ("1W", "interbank_1w")):
            for b in block:
                toks = b.split()
                if not toks or toks[0] != row_label:
                    continue
                decs = [_to_float(m) for m in _DEC.findall(b)]
                decs = [d for d in decs if _in_range(key, d)]
                if decs:
                    v = decs[1] if (header_has_tb5 and len(decs) >= 2) else decs[0]
                    out[key] = v
                break
        if out:
            return out

    # Fallback: câu văn có cấu trúc chặt trong phần bình luận LNH
    text = "\n".join(lines)
    m = re.search(r"qua\s*đêm\s*\(?ON\)?[^%]{0,80}?mức\s*(\d{1,2}[.,]\d{1,3})\s*%",
                  text, re.I | re.S)
    if m and _in_range("interbank_on", _to_float(m.group(1))):
        out["interbank_on"] = _to_float(m.group(1))
    m = re.search(r"kỳ\s*hạn\s*\(?1W\)?[^%]{0,80}?mức\s*(\d{1,2}[.,]\d{1,3})\s*%",
                  text, re.I | re.S)
    if m and _in_range("interbank_1w", _to_float(m.group(1))):
        out["interbank_1w"] = _to_float(m.group(1))
    return out


# Thứ tự tenor CỐ ĐỊNH của ma trận lợi suất VBMA (dùng cho đường 2 bên dưới)
_CANON_TENORS = ("1", "2", "3", "5", "7", "10", "15", "20", "30")


def _parse_bond_10y(lines: "list[str]") -> "float | None":
    # Đường 1 — layout giữ cột (pdftotext -layout): header tenor nguyên vẹn
    # rồi dòng ngày ĐẦU TIÊN ngay bên dưới là tuần mới nhất.
    for i, line in enumerate(lines):
        tenors = _TENOR.findall(line)
        if "10" not in tenors or len(tenors) < 4:      # header ma trận tenor
            continue
        idx = tenors.index("10")
        for row in lines[i + 1:i + 6]:
            if not _DATE_ROW.match(row):
                continue
            pcts = [_to_float(x) for x in _PCT.findall(row)]
            if len(pcts) > idx and _in_range("govt_bond_yield_10y", pcts[idx]):
                return pcts[idx]
            break                                       # header khác (legend chart) → thử tiếp

    # Đường 2 — pypdf XÁO layout (header vỡ mảnh, hàng 2025 in trước 2026,
    # giá trị cuối rớt dòng): mọi dòng "d/m/yyyy" mang ≥6 giá trị % vẫn giữ
    # THỨ TỰ TENOR CHUẨN 1N..30N → lấy vị trí 10N, chọn dòng NGÀY MỚI NHẤT.
    # (Đã kiểm trên PDF thật 03/07/2026: cả 2 chế độ extract, dòng-ngày-nhiều-%
    # duy nhất chính là ma trận lợi suất.)
    idx10 = _CANON_TENORS.index("10")
    best: "tuple | None" = None
    for line in lines:
        if not _DATE_ROW.match(line):
            continue
        pcts = [_to_float(x) for x in _PCT.findall(line)]
        if len(pcts) <= idx10:
            continue
        try:
            d = datetime.strptime(line.split()[0], "%d/%m/%Y").date()
        except ValueError:
            continue
        v = pcts[idx10]
        if _in_range("govt_bond_yield_10y", v) and (best is None or d > best[0]):
            best = (d, v)
    return best[1] if best else None


# Tỷ giá VCB từ văn xuôi "THỊ TRƯỜNG NGOẠI HỐI": "...xuống 26,103 VND/USD ở
# chiều mua và tăng 9 VND/USD lên 26,463 VND/USD ở chiều bán". Neo số NGAY TRƯỚC
# "VND/USD ở chiều mua/bán" nên số delta ("tăng 9 VND/USD lên") không lọt.
# \s* giữa mọi token vì pdftotext ngắt dòng giữa câu còn pypdf DÍNH chữ
# ("ởchiều bán" — đã thấy trên PDF thật 03/07/2026).
_FX_NUM = r"(\d{2}[.,]\d{3})"
_FX_BUY = re.compile(_FX_NUM + r"\s*VND/USD\s*ở\s*chiều\s*mua", re.I)
_FX_SELL = re.compile(_FX_NUM + r"\s*VND/USD\s*ở\s*chiều\s*bán", re.I)


def _fx_to_vnd(s: str) -> float:
    return float(re.sub(r"[.,]", "", s))       # "26,103" → 26103 (sep = nghìn)


def _parse_fx(text: str) -> "float | None":
    """Trung bình mua/bán niêm yết Vietcombank (VND/USD) — dùng để cross-check
    nguồn FX chính (er-api) trong vnstock_macro, không ghi thành chỉ số."""
    mb, ms = _FX_BUY.search(text), _FX_SELL.search(text)
    if not (mb and ms):
        return None
    buy, sell = _fx_to_vnd(mb.group(1)), _fx_to_vnd(ms.group(1))
    mid = round((buy + sell) / 2.0, 1)
    if buy <= sell and _in_range("usdvnd_vcb_mid", mid):
        return mid
    return None


def extract_rates(text: str) -> dict:
    """{key: value} cho các chỉ số parse được từ text PDF (deterministic)."""
    if not text:
        return {}
    lines = text.splitlines()
    out = _parse_interbank(lines)
    y10 = _parse_bond_10y(lines)
    if y10 is not None:
        out["govt_bond_yield_10y"] = y10
    fx = _parse_fx(text)
    if fx is not None:
        out["usdvnd_vcb_mid"] = fx
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
