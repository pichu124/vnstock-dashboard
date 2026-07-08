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
import os
import re
import ssl
import warnings
from datetime import date

import requests
from requests.adapters import HTTPAdapter

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
# /bai-top/{YYYY}/{MM}/ (tháng PUBLISH) lớn nhất. THÁNG CUỐI QUÝ (3/6/9/12)
# không có "báo cáo tháng" riêng — NSO gộp vào "báo cáo QUÝ x và N tháng"
# (diag thật 08/07: chỉ bắt "-thang" nên vớ nhầm bài tháng 5) → nhận cả 2 slug:
#   bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-…  (tháng thường)
#   bao-cao-tinh-hinh-kinh-te-xa-hoi-quy-…    (tháng cuối quý, vẫn chứa câu
#                                              CPI/IIP THÁNG bên trong)
_REPORT_HREF = re.compile(
    r'href="([^"]*/bai-top/(\d{4})/(\d{2})/[^"]*'
    r'bao-cao-tinh-hinh-kinh-te-xa-hoi-(?:thang|quy)[^"]*)"', re.I)


# ── TLS ladder cho server .gov.vn ────────────────────────────────────────────
# Diag thật 08/07/2026: cả 3 host nso/gso FAIL `SSLCertVerificationError` —
# server KHÔNG gửi chứng chỉ trung gian (browser tự tải bù qua AIA nên vẫn mở
# được; certifi của Python thì không). Thang 3 nấc:
#   1. certifi (mặc định)  →  2. kho chứng chỉ HỆ ĐIỀU HÀNH (Windows thường đã
#   cache intermediate)  →  3. verify=False CHỈ CHO NGUỒN NÀY (data thống kê
#   công khai, chỉ đọc; số đi qua sanity range + as_of hiển thị; đặt
#   VNSTOCK_NSO_TLS_STRICT=1 để CẤM nấc này).


class _OSTrustAdapter(HTTPAdapter):
    """HTTPS adapter dùng SSLContext mặc định của OS (Windows cert store) thay
    vì certifi — intermediate mà Windows đã cache sẽ được dùng để vá chuỗi."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)


def _os_trust_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _OSTrustAdapter())
    return s


def _http_get(url: str, verbose: bool = False) -> "requests.Response | None":
    try:
        return requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.exceptions.SSLError:
        if verbose:
            print("    → certifi FAIL (thiếu intermediate) — thử OS trust store")
    except requests.RequestException as e:
        if verbose:
            print(f"    → LỖI {type(e).__name__}: {str(e)[:200]}")
        return None
    try:
        return _os_trust_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.exceptions.SSLError:
        if verbose:
            print("    → OS trust store FAIL — fallback verify=False (chỉ nguồn này)")
    except requests.RequestException:
        return None
    if os.environ.get("VNSTOCK_NSO_TLS_STRICT") == "1":
        return None
    import urllib3
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        try:
            return requests.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                                verify=False)
        except requests.RequestException:
            return None


def fetch_listing_html(verbose: bool = False) -> "str | None":
    """HTML trang index báo cáo tháng. ``verbose`` (--diag) in chi tiết từng
    URL (HTTP status / exception / nấc TLS) để pinpoint lỗi thay vì FAIL câm."""
    for url in _LISTING_URLS:
        if verbose:
            print(f"  • GET {url}")
        r = _http_get(url, verbose=verbose)
        if r is None:
            continue
        if verbose:
            print(f"    → HTTP {r.status_code}, {len(r.text or '')} ký tự")
        if r.status_code == 200 and r.text:
            return r.text
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
    r = _http_get(url)
    if r is not None and r.status_code == 200 and r.text:
        return _strip_html(r.text)
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
    nhiều lần — TOC/bình quân trước, câu tháng sau → thử lần lượt).

    Cửa sổ CẮT tại "chỉ số" kế tiếp — mỗi cửa sổ chỉ chứa đúng 1 chỉ số.
    Diag thật 08/07 (bài quý II): anchor IIP không mang số đứng ngay trước câu
    "Chỉ số TIÊU THỤ … tăng 1,8% … 9,0%" → cửa sổ tràn sang, IIP bị gán nhầm
    số tiêu thụ."""
    for n, m in enumerate(anchor.finditer(text)):
        if n >= limit:
            break
        win = text[m.start(): m.start() + _WINDOW_CHARS]
        nxt = win.lower().find("chỉ số", 6)          # bỏ qua chính anchor
        if nxt != -1:
            win = win[:nxt]
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


def _extract(text: str) -> "tuple[dict, dict]":
    """(chỉ số, {prefix: cửa sổ nguồn}) — cửa sổ giữ lại cho --diag soi câu."""
    if not text:
        return {}, {}
    flat = re.sub(r"\s+", " ", text)
    out: dict = {}
    wins: dict = {}
    for anchor, prefix in ((_CPI_ANCHOR, "cpi"), (_IIP_ANCHOR, "iip")):
        for win in _windows(flat, anchor):
            d = _moves(win, prefix)
            if d:                        # cửa sổ đầu tiên có số "so với" thắng
                out.update(d)
                wins[prefix] = win.strip()
                break
    return out, wins


def extract_indicators(text: str) -> dict:
    """{cpi_mom, cpi_yoy, iip_mom, iip_yoy} (dấu theo tăng/giảm) — chỉ key
    parse được. Deterministic, không LLM."""
    return _extract(text)[0]


# ── Fallback IIP: bài "Chỉ số sản xuất công nghiệp tháng X" riêng ────────────
# Bài QUÝ (tháng cuối quý 3/6/9/12) chỉ nói IIP theo quý/6 tháng — KHÔNG có câu
# IIP THÁNG (diag thật 08/07: bài Q2 ra mỗi CPI). NSO luôn có bài IIP riêng
# hàng tháng (vd /du-lieu-va-so-lieu-thong-ke/2026/07/chi-so-san-xuat-cong-
# nghiep-thang-sau-nam-2026/) → lấy IIP từ đó khi bài chính thiếu.

_IIP_LISTING_URLS = ("https://www.nso.gov.vn/iip/",)
_IIP_HREF = re.compile(
    r'href="([^"]*/(\d{4})/(\d{2})/chi-so-san-xuat-cong-nghiep-thang[^"]*)"', re.I)
# Slug tháng tiếng Việt của NSO ("tháng Sáu" → thang-sau) — dùng khi trang
# listing /iip/ không có/không lấy được, ĐOÁN đúng 1 URL rồi thôi (best-effort).
_VN_MONTH_SLUGS = {1: "mot", 2: "hai", 3: "ba", 4: "tu", 5: "nam", 6: "sau",
                   7: "bay", 8: "tam", 9: "chin", 10: "muoi",
                   11: "muoi-mot", 12: "muoi-hai"}


def _iip_guess_url(pub_y: int, pub_m: int) -> str:
    dy, dm = (pub_y, pub_m - 1) if pub_m > 1 else (pub_y - 1, 12)
    return (f"https://www.nso.gov.vn/du-lieu-va-so-lieu-thong-ke/{pub_y}/"
            f"{pub_m:02d}/chi-so-san-xuat-cong-nghiep-thang-"
            f"{_VN_MONTH_SLUGS[dm]}-nam-{dy}/")


def _fetch_iip_fallback(pub_y: int, pub_m: int, verbose: bool = False) -> dict:
    """{iip_mom, iip_yoy} từ bài IIP tháng riêng, CÙNG tháng publish với báo
    cáo chính (không trộn kỳ); {} khi không tìm/parse được."""
    urls: list[str] = []
    for lst in _IIP_LISTING_URLS:                      # 1) scrape listing
        r = _http_get(lst)
        if r is None or r.status_code != 200 or not r.text:
            continue
        best: "tuple[str, tuple] | None" = None
        for u, yy, mm in _IIP_HREF.findall(r.text):
            k = (int(yy), int(mm))
            if best is None or k > best[1]:
                best = (u, k)
        if best and best[1] == (pub_y, pub_m):
            u = best[0]
            urls.append("https://www.nso.gov.vn" + u if u.startswith("/") else u)
    urls.append(_iip_guess_url(pub_y, pub_m))          # 2) đoán URL theo slug
    for u in urls:
        text = download_report_text(u)
        if not text:
            continue
        out = {k: v for k, v in extract_indicators(text).items()
               if k.startswith("iip")}
        if out:
            if verbose:
                print(f"  IIP từ bài riêng: {u}")
            return out
    return {}


# ── End-to-end ───────────────────────────────────────────────────────────────

def fetch_monthly(verbose: bool = False) -> "dict | None":
    """Fetch + parse báo cáo tháng mới nhất (+ bài IIP riêng khi bài chính là
    báo cáo quý không có câu IIP tháng).

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
    if inds and "iip_yoy" not in inds:
        dy, dm = int(as_of[:4]), int(as_of[5:7])       # tháng data → tháng publish
        pub_y, pub_m = (dy + 1, 1) if dm == 12 else (dy, dm + 1)
        inds.update(_fetch_iip_fallback(pub_y, pub_m, verbose=verbose))
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
    inds, wins = _extract(text)
    if inds and "iip_yoy" not in inds:
        dy, dm = int(hit[1][:4]), int(hit[1][5:7])
        pub_y, pub_m = (dy + 1, 1) if dm == 12 else (dy, dm + 1)
        print("  IIP không có trong bài chính (bài quý) → thử bài IIP tháng riêng…")
        inds.update(_fetch_iip_fallback(pub_y, pub_m, verbose=True))
    print(f"parse: {inds if inds else 'KHÔNG bắt được số — chạy lại --dump gửi text để chỉnh regex'}")
    for prefix, win in wins.items():
        print(f"  câu nguồn [{prefix}]: {win[:220]}")
    return 0 if inds else 1


if __name__ == "__main__":
    raise SystemExit(main())
