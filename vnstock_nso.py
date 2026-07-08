#!/usr/bin/env python3
"""vnstock_nso.py — CPI & IIP hàng tháng từ NSO (Cục Thống kê, nso.gov.vn).

Lấp 2 chỉ số vĩ mô "nóng" còn thiếu trong ``vnstock_macro`` (CLAUDE.md ghi
"CPI/Fed/GDP vẫn chưa có"): **CPI YoY** (market-mover số 1 với kỳ vọng lãi
suất) và **IIP YoY** (nhịp tăng trưởng sản xuất). Nguồn = báo cáo "Tình hình
kinh tế – xã hội" NSO công bố ~mùng 3 hàng tháng (HTML tĩnh, free, phát hiện
khi khảo sát skill vimovietnam).

Pipeline (mirror ``vnstock_vbma``): listing → bài báo cáo THÁNG mới nhất
(``/bai-top/{YYYY}/{MM}/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-…``) → strip
HTML → regex câu CÔNG THỨC của NSO:

    "Chỉ số giá tiêu dùng (CPI) tháng 6/2026 giảm 0,39% so với tháng trước;
     … tăng 4,69% so với cùng kỳ năm trước."
    "Chỉ số sản xuất toàn ngành công nghiệp (IIP) tháng Sáu ước tính tăng
     3,5% so với tháng trước và tăng 12,7% so với cùng kỳ năm trước."

(Câu chữ đối chiếu số liệu THẬT tháng 6/2026 qua báo chí dẫn lại NSO —
sandbox bị chặn egress nên **CẦN VERIFY trên máy có mạng**::

    python vnstock_nso.py --diag          # in URL bài + số parse được
    python vnstock_nso.py --diag --dump   # kèm text đã strip để chỉnh regex

Best-effort by design: mọi lỗi mạng/parse → None → ``vnstock_macro`` giữ cache
cũ; ``--set cpi_yoy/iip_yoy`` tay luôn là đường sống. NSO dùng dấu PHẨY thập
phân ("0,39%") — parser nhận cả hai kiểu.
"""
from __future__ import annotations

import calendar
import html as _html
import re
from datetime import date

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# Header browser đầy đủ — server .gov.vn hay từ chối request "trần" (chỉ UA).
_HEADERS = {
    "User-Agent": _UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "vi,vi-VN;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}
_LISTING_URLS = (
    "https://www.nso.gov.vn/bao-cao-tinh-hinh-kinh-te-xa-hoi-hang-thang/",
    "https://nso.gov.vn/bao-cao-tinh-hinh-kinh-te-xa-hoi-hang-thang/",
    # tên miền cũ (Tổng cục Thống kê trước khi đổi NSO) — thường redirect
    "https://www.gso.gov.vn/bao-cao-tinh-hinh-kinh-te-xa-hoi-hang-thang/",
)
_TIMEOUT = 20

# Sanity range (% — YoY/MoM đều là %); ngoài khoảng coi như trúng số khác, bỏ.
_RANGES = {
    "cpi_mom": (-5.0, 5.0),
    "cpi_yoy": (-10.0, 30.0),
    "iip_mom": (-30.0, 30.0),
    "iip_yoy": (-30.0, 50.0),
}


# ── Bước 1: listing → bài báo cáo tháng mới nhất ────────────────────────────

# Slug NSO không nhất quán (có bài còn ghi nhầm năm trong slug — thấy 06/2026
# slug "…-2025-2") → KHÔNG dựng URL từ pattern; chỉ scrape href và chọn theo
# /bai-top/{YYYY}/{MM}/ (tháng PUBLISH) lớn nhất.
_REPORT_HREF = re.compile(
    r'href="([^"]*/bai-top/(\d{4})/(\d{2})/[^"]*'
    r'bao-cao-tinh-hinh-kinh-te-xa-hoi-thang[^"]*)"', re.I)


def fetch_listing_html(verbose: bool = False) -> "str | None":
    """HTML trang index báo cáo tháng. ``verbose`` (--diag) in chi tiết từng
    URL (HTTP status / exception) để pinpoint lỗi thay vì FAIL câm."""
    for url in _LISTING_URLS:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            if verbose:
                print(f"  • GET {url}\n    → HTTP {r.status_code}, "
                      f"{len(r.text or '')} ký tự")
            if r.status_code == 200 and r.text:
                return r.text
        except requests.RequestException as e:
            if verbose:
                print(f"  • GET {url}\n    → LỖI {type(e).__name__}: {str(e)[:200]}")
            continue
    return None


def find_latest_report(html: str) -> "tuple[str, str] | None":
    """(url, as_of_iso) của báo cáo tháng mới nhất.

    ``as_of`` = NGÀY CUỐI của THÁNG DỮ LIỆU (= tháng publish − 1: báo cáo
    tháng M đăng mùng ~3 tháng M+1) — khớp semantics "tính đến" của
    vnstock_macro."""
    best: "tuple[str, int, int] | None" = None
    for url, yyyy, mm in _REPORT_HREF.findall(html or ""):
        y, m = int(yyyy), int(mm)
        if not (1 <= m <= 12):
            continue
        if best is None or (y, m) > (best[1], best[2]):
            best = (url, y, m)
    if best is None:
        return None
    url, y, m = best
    if url.startswith("/"):
        url = "https://www.nso.gov.vn" + url
    y, m = (y, m - 1) if m > 1 else (y - 1, 12)      # tháng data = publish − 1
    return url, date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def download_report_text(url: str) -> "str | None":
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200 and r.text:
            return _strip_html(r.text)
    except requests.RequestException:
        pass
    return None


def _strip_html(page: str) -> str:
    """HTML → text phẳng (1 dòng, whitespace gộp) đủ cho regex câu."""
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", _html.unescape(page)).strip()


# ── Bước 2: text → chỉ số ────────────────────────────────────────────────────

# Mệnh đề chuẩn: "tăng|giảm X% so với tháng trước / so với cùng kỳ". Bắt buộc
# chữ "trước" nên "so với tháng 12/2025" (mốc YTD) không lọt vào MoM.
_MOVE = re.compile(
    r"(tăng|giảm)\s*(\d{1,2}[.,]\d{1,2})\s*%\s*so\s*với\s*"
    r"(tháng\s*trước|cùng\s*kỳ)", re.I)
_CPI_ANCHOR = re.compile(r"chỉ\s*số\s*giá\s*tiêu\s*dùng[^.;]{0,40}?tháng", re.I)
_IIP_ANCHOR = re.compile(
    r"chỉ\s*số\s*sản\s*xuất\s*(?:toàn\s*ngành\s*)?công\s*nghiệp", re.I)
# Cắt cửa sổ tại số liệu BÌNH QUÂN (quý / N tháng) để không lấy nhầm YoY
# bình quân (vd "bình quân 6 tháng CPI tăng 4,38%") thay cho YoY của THÁNG.
_WINDOW_STOP = re.compile(r"bình\s*quân|quý\s*[IV1-4]", re.I)
_WINDOW_CHARS = 350


def _windows(text: str, anchor: re.Pattern, limit: int = 6):
    """Cửa sổ câu quanh từng lần khớp anchor (bài dài có thể nhắc chỉ số
    nhiều lần — TOC/bình quân trước, câu tháng sau → thử lần lượt)."""
    for n, m in enumerate(anchor.finditer(text)):
        if n >= limit:
            break
        win = text[m.start(): m.start() + _WINDOW_CHARS]
        stop = _WINDOW_STOP.search(win)
        yield win[: stop.start()] if stop else win


def _moves(window: str, prefix: str) -> dict:
    out: dict = {}
    for verb, num, base in _MOVE.findall(window):
        v = float(num.replace(",", "."))
        if verb.lower() == "giảm":
            v = -v
        key = f"{prefix}_{'mom' if 'tháng' in base.lower() else 'yoy'}"
        lo, hi = _RANGES[key]
        if key not in out and lo <= v <= hi:
            out[key] = v
    return out


def extract_indicators(text: str) -> dict:
    """{cpi_mom, cpi_yoy, iip_mom, iip_yoy} (dấu theo tăng/giảm) — chỉ key
    parse được. Deterministic, không LLM."""
    if not text:
        return {}
    flat = re.sub(r"\s+", " ", text)
    out: dict = {}
    for anchor, prefix in ((_CPI_ANCHOR, "cpi"), (_IIP_ANCHOR, "iip")):
        for win in _windows(flat, anchor):
            d = _moves(win, prefix)
            if d:                        # cửa sổ đầu tiên có số "so với" thắng
                out.update(d)
                break
    return out


# ── End-to-end ───────────────────────────────────────────────────────────────

def fetch_monthly() -> "dict | None":
    """Fetch + parse báo cáo tháng mới nhất.

    Trả ``{"as_of": ISO cuối tháng data, "source_url": …, <key>: value…}``
    hoặc None khi bất kỳ bước nào hỏng (caller giữ cache cũ)."""
    html = fetch_listing_html()
    if not html:
        return None
    hit = find_latest_report(html)
    if hit is None:
        return None
    url, as_of = hit
    text = download_report_text(url)
    if not text:
        return None
    inds = extract_indicators(text)
    if not inds:
        return None
    inds["as_of"] = as_of
    inds["source_url"] = url
    return inds


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="NSO CPI/IIP hàng tháng — diag")
    ap.add_argument("--diag", action="store_true",
                    help="Fetch thử 1 lần, in URL bài + số parse được")
    ap.add_argument("--dump", action="store_true",
                    help="Kèm --diag: in text đã strip (chỉnh regex khi lệch)")
    args = ap.parse_args(argv)

    if not args.diag:
        ap.print_help()
        return 0

    html = fetch_listing_html(verbose=True)
    print(f"listing: {'OK' if html else 'FAIL — gửi tôi các dòng GET ở trên để chỉnh (server chặn? đổi URL?)'}")
    if not html:
        return 1
    hit = find_latest_report(html)
    print(f"bài mới nhất: {hit if hit else 'KHÔNG tìm thấy href bao-cao-…-thang'}")
    if not hit:
        return 1
    text = download_report_text(hit[0])
    print(f"tải bài: {'OK, ' + str(len(text)) + ' ký tự' if text else 'FAIL'}")
    if not text:
        return 1
    if args.dump:
        print("─" * 60)
        print(text[:8000])
        print("─" * 60)
    inds = extract_indicators(text)
    print(f"parse: {inds if inds else 'KHÔNG bắt được số — chạy lại --dump gửi text để chỉnh regex'}")
    return 0 if inds else 1


if __name__ == "__main__":
    raise SystemExit(main())
