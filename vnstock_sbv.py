"""
vnstock_sbv.py — Bản tin tuần SBV: LNH + OMO + tỷ giá trung tâm
===============================================================
Nguồn CHÍNH THỨC thứ 2 cho lãi suất liên ngân hàng (bổ sung VBMA), + 2 thứ
VBMA/HNX KHÔNG có: **OMO ròng** (bơm/hút thành SỐ — trước chỉ suy từ từ
khoá tin) và **tỷ giá trung tâm** (neo cross-check bên cạnh er-api↔VCB).

Khảo sát repo Thanhtran-165/baocaolaisuatvatiente (2026-07-16, no LICENSE
→ mượn Ý TƯỞNG + URL/pattern parse, KHÔNG copy code). Tự viết theo mẫu
vnstock_vbma: fetch bài tuần SBV → PDF nhúng → `pdf_to_text` (dùng lại của
vnstock_vbma) → parse regex → cache `_meta/sbv_weekly.json`.

⚠️ VERIFY-GATED: sandbox chặn sbv.gov.vn → `--diag` chạy trên máy có mạng;
slug bài + URL PDF (cần uuid) là ứng viên CHƯA verify — SBV hay đổi/ghi
nhầm slug. Tắt: `VNSTOCK_SBV=0`. Parse THUẦN (testable với fixture text).

CLI:  python vnstock_sbv.py --refresh | --show | --diag | --set-omo <tỷ VND>
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_CACHE = "sbv_weekly.json"

# Chênh LNH ON SBV vs VBMA > ngưỡng này (%) → cờ divergence (mirror _fx_crosscheck)
_INTERBANK_DIVERGENCE_PCT = 15.0


def _cache_path() -> Path:
    return _META / _CACHE


# ── Parse (thuần, testable) ─────────────────────────────────────────────────

@dataclass
class SBVWeekly:
    overnight: Optional[float] = None       # LNH qua đêm (%/năm)
    one_week: Optional[float] = None
    two_week: Optional[float] = None
    one_month: Optional[float] = None
    fx_central: Optional[float] = None      # tỷ giá trung tâm (VND/USD)
    omo_net: Optional[float] = None         # + = hút ròng, − = bơm ròng (tỷ VND)
    week_end: Optional[str] = None          # thứ 6 TUẦN DATA của bản tin (ISO)
                                            # — ngày DATA thật, không phải ngày fetch


def _num(s: str) -> Optional[float]:
    """'1,20' / '1.20' → 1.20 (lãi suất — dấu phẩy = thập phân)."""
    try:
        return float((s or "").strip().replace(",", "."))
    except ValueError:
        return None


def _thousands(s: str) -> Optional[float]:
    """'25.140' → 25140 (VND — dấu chấm = ngăn nghìn)."""
    try:
        return float((s or "").strip().replace(".", "").replace(",", ""))
    except ValueError:
        return None


def _parse_interbank_table(text: str) -> "tuple | None":
    """Bảng lãi suất bình quân LNH cuối bản tin — dòng 'VND <ON> <1T> <2T>
    <1 tháng> …' (cột theo header Qua đêm|1 tuần|2 tuần|1 tháng|3 tháng…).
    Trả (ON, 1W, 2W, 1M) hoặc None. Đây là NGUỒN CHÍNH (câu tường thuật
    'giảm 0,03%/năm' là mức THAY ĐỔI / là USD — KHÔNG lấy).

    GATE HEADER (fix 17/07 sau vụ cache nhiễm 4.26/7.34/7.76): dòng VND chỉ
    được nhận khi ~250 ký tự TRƯỚC nó có header bảng LNH 'Qua đêm' — bản tin
    SBV KHÁC (huy động/cho vay) cũng có dòng 'VND <số> <số>…' nhưng cột là
    kỳ hạn tiền gửi, không phải LNH → không được lọt."""
    # "VND" theo sau NGAY bởi ≥4 token lãi suất (a,bc) hoặc "-" — phân biệt với
    # văn xuôi "bằng VND đạt 4.428.576 tỷ" (sau VND là chữ, không phải token số).
    for m in re.finditer(r"\bVND\b[ \t]+((?:(?:\d{1,2},\d{1,2}|-)[ \t]*){4,})", text):
        if "qua đêm" not in text[max(0, m.start() - 250):m.start()].lower():
            continue                        # dòng VND không thuộc bảng LNH
        toks = re.findall(r"\d{1,2},\d{1,2}|-", m.group(1))
        vals = [None if t == "-" else float(t.replace(",", ".")) for t in toks]
        if len(vals) < 4:
            continue
        on, w1, w2, m1 = vals[0], vals[1], vals[2], vals[3]

        def _ok(v):
            return v is None or (0.1 <= v <= 20)
        if all(_ok(v) for v in (on, w1, w2, m1)):
            return on, w1, w2, m1
    return None


def parse_sbv_text(text: str) -> SBVWeekly:
    """Text PDF bản tin tuần SBV → SBVWeekly. Mỗi trường best-effort (thiếu →
    None). Bản tin 'Diễn biến TT ngoại tệ & LNH' có BẢNG lãi suất bình quân
    (ON/1T/2T/1 tháng…); tỷ giá trung tâm & OMO thường ở bản tin SBV KHÁC →
    thiếu ở đây là bình thường."""
    r = SBVWeekly()
    if not text:
        return r
    t = text

    # 1) Lãi suất LNH — CHỈ lấy từ BẢNG (dòng "VND <ON> <1T>…"). KHÔNG parse
    #    câu tường thuật: mọi kỳ hạn chung 1 mệnh đề "…xuống các mức A, B, C"
    #    nên regex per-tenor gán SAI (lấy nhầm số đầu cho mọi kỳ hạn) — thà
    #    None (VBMA vẫn cover LNH). Số 'giảm 0,03%/năm' trong câu = mức THAY
    #    ĐỔI / là USD, tuyệt đối không lấy.
    tbl = _parse_interbank_table(t)
    if tbl:
        r.overnight, r.one_week, r.two_week, r.one_month = tbl

    # 2) Tỷ giá trung tâm — 'tỷ giá trung tâm ... 25.140' (bản tin FX/LNH này
    #    thường KHÔNG có → None; nằm ở bản tin điều hành khác).
    m = re.search(r"tỷ giá trung tâm[^0-9]{0,40}(\d{2}[.,]\d{3})", t, re.I)
    if m:
        r.fx_central = _thousands(m.group(1))

    # 3) OMO ròng — 'hút/bơm (ròng) ... X tỷ' (hút=+/bơm=−). Cụm xuất hiện TRƯỚC.
    #    Yêu cầu 'ròng' hoặc 'OMO'/'thị trường mở' gần đó để không bắt số doanh
    #    số giao dịch. Bản tin này thường KHÔNG có OMO → None.
    def _omo(kw: str) -> "tuple | None":
        for m in re.finditer(rf"{kw}[^0-9\n]{{0,40}}?(\d{{1,3}}(?:[.,]\d{{3}})+)\s*tỷ",
                             t, re.I):
            ctx = t[max(0, m.start() - 60):m.end() + 20].lower()
            if "ròng" in ctx or "omo" in ctx or "thị trường mở" in ctx:
                return m.start(), _thousands(m.group(1))
        return None
    oh, ob = _omo("hút"), _omo("bơm")
    if oh and (not ob or oh[0] <= ob[0]):
        r.omo_net = oh[1]
    elif ob:
        r.omo_net = -ob[1] if ob[1] is not None else None
    return r


# ── Cross-source resolution SBV ↔ VBMA (mirror _fx_crosscheck) ──────────────

def resolve_interbank_on(sbv: Optional[float], vbma: Optional[float],
                         sbv_as_of: Optional[str] = None,
                         vbma_as_of: Optional[str] = None,
                         ) -> "tuple[Optional[float], str, bool]":
    """LNH ON từ 2 nguồn → (giá trị, nguồn, cờ_lệch). **User chốt 17/07:
    luôn dùng số CẬP NHẬT NHẤT** — so ngày DATA (as_of ISO): nguồn có tuần
    data MỚI hơn thắng, bất kể nguồn nào. Cùng tuần / thiếu as_of → ưu tiên
    VBMA (ĐIỂM cuối tuần, sát hiện tại hơn TRUNG BÌNH cả tuần của SBV).
    Thiếu 1 nguồn → dùng nguồn kia. Cờ lệch > ngưỡng khi có cả 2 (bất kể
    nguồn nào thắng) — SBV vẫn giữ vai trò cross-check chính thức."""
    if sbv is None and vbma is None:
        return None, "none", False
    if sbv is None:
        return vbma, "vbma", False
    if vbma is None:
        return sbv, "sbv", False
    avg = (sbv + vbma) / 2
    diverged = avg > 0 and abs(sbv - vbma) / avg * 100 > _INTERBANK_DIVERGENCE_PCT
    if sbv_as_of and vbma_as_of and sbv_as_of > vbma_as_of:   # ISO so sánh chuỗi
        return sbv, "sbv", bool(diverged)
    return vbma, "vbma", bool(diverged)


# ── Fetch (best-effort, verify-gated) ───────────────────────────────────────

_SBV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://www.sbv.gov.vn/vi/web/sbv_portal/"
               "thong-tin-ve-hoat-dong-ngan-hang-trong-tuan",
}
# Trang LISTING render bài qua JS (verify 16/07: HTML tĩnh chỉ có 1 link
# /vi/trang-chu) → KHÔNG scrape được. Thay bằng DỰNG URL bài TỪ NGÀY tuần
# (mirror repo gốc): slug = "<tiêu-đề>-<DD>-<DD>.<M>.<YYYY>" (ngày zero-pad,
# THÁNG không pad).
# ⚠️ CHỈ 1 slug — bài FX/LNH đã verify thật 16/07. Slug fallback cũ
# "thông-tin-hoạt-động-ngân-hàng-trong-tuần-từ" ĐÃ GỠ (17/07): đó là BẢN TIN
# KHÁC (hoạt động NH — lãi suất huy động/cho vay) cũng có dòng 'VND <số>…'
# → khi bài FX/LNH fail tạm (WAF) fetch rơi xuống bài này và parse ra số SAI
# (cache nhiễm 4.26/7.34/7.76 ngày 16/07). SBV đổi tiêu đề bài FX/LNH → toàn
# 404: mở 1 bài tuần thật trên trình duyệt, copy URL, cập nhật slug ở đây.
_SBV_TITLE_SLUGS = (
    "diễn-biến-thị-trường-ngoại-tệ-và-thị-trường-liên-ngân-hàng-tuần-từ",
)
# Giãn cách giữa các request tới SBV (repo gốc dùng sleep 3s "WAF avoidance" —
# nghi là nguyên nhân các lần fetch fail tạm khi gọi dồn dập cùng ngày).
_REQUEST_GAP_S = 2.0
# PDF nhúng trong BÀI (server-render): /documents/.../<file>.pdf/<uuid>?...
_SBV_PDF_RE = re.compile(r'(?:src|href)="(/documents/\d+/[^"]+\.pdf/[^"]*)"', re.I)


def _week_date_slug(monday, friday) -> str:
    """'01-05.6.2026' — ngày T2/T6 zero-pad, THÁNG không pad, năm đầy đủ."""
    return f"{monday.day:02d}-{friday.day:02d}.{monday.month}.{monday.year}"


def _candidate_article_urls(monday, friday) -> list:
    from urllib.parse import quote
    ds = _week_date_slug(monday, friday)
    return ["https://www.sbv.gov.vn/vi/web/sbv_portal/w/"
            + quote(f"{title}-{ds}") for title in _SBV_TITLE_SLUGS]


def _fetch_pdf_text(verbose: bool = False, weeks_back: int = 5
                    ) -> "tuple[str, str] | None":
    """DỰNG URL bài tuần từ ngày (listing là JS) → tải PDF → (text THÔ, thứ 6
    TUẦN DATA dạng ISO). Bài tuần N publish tuần N+1 → bắt đầu TUẦN TRƯỚC,
    lùi dần; 404 = nghỉ/chưa có → thử tuần trước nữa. None khi không ra bài."""
    if os.environ.get("VNSTOCK_SBV", "1") == "0":
        return None
    try:
        import requests
        from vnstock_vbma import pdf_to_text
    except Exception:
        return None
    import time
    from datetime import timedelta
    today = datetime.now().date()
    this_monday = today - timedelta(days=today.weekday())
    attempts = 0
    for back in range(1, max(2, weeks_back) + 1):
        monday = this_monday - timedelta(weeks=back)
        friday = monday + timedelta(days=4)
        for url in _candidate_article_urls(monday, friday):
            if attempts and _REQUEST_GAP_S > 0:      # giãn cách né WAF SBV
                time.sleep(_REQUEST_GAP_S)
            attempts += 1
            try:
                resp = requests.get(url, headers=_SBV_HEADERS, timeout=30)
            except Exception as e:
                if verbose:
                    print(f"    → LỖI {type(e).__name__}: {url[:90]}")
                continue
            if resp.status_code != 200:
                if verbose:
                    print(f"    → {resp.status_code}: {url}")
                continue
            pm = _SBV_PDF_RE.search(resp.text)
            if not pm:
                if verbose:
                    print(f"    → 200 nhưng KHÔNG thấy PDF nhúng: {url}")
                continue
            pdf_url = "https://www.sbv.gov.vn" + pm.group(1).replace("&amp;", "&")
            if verbose:
                print(f"    ✅ bài: {url}\n       PDF: {pdf_url[:110]}")
            try:
                data = requests.get(pdf_url, headers=_SBV_HEADERS, timeout=45).content
            except Exception:
                continue
            text = pdf_to_text(data)
            if text:
                return text, friday.isoformat()
            if verbose:
                print("    → tải PDF OK nhưng pdf_to_text rỗng (thiếu pypdf/pdftotext?)")
    if verbose:
        print(f"    → thử {weeks_back} tuần gần nhất × {len(_SBV_TITLE_SLUGS)} tiêu "
              "đề đều không ra. Nếu SBV đổi tiêu đề bài: mở 1 bài tuần thật trên "
              "trình duyệt, COPY URL rồi gửi tôi → tôi cập nhật _SBV_TITLE_SLUGS.")
    return None


def fetch_weekly(verbose: bool = False, weeks_back: int = 5) -> "SBVWeekly | None":
    """Bài tuần SBV mới nhất → PDF → text → parse (`parse_sbv_text`).
    `week_end` = thứ 6 tuần DATA (ngày data thật — không phải ngày fetch)."""
    got = _fetch_pdf_text(verbose=verbose, weeks_back=weeks_back)
    if not got:
        return None
    text, week_end = got
    r = parse_sbv_text(text)
    r.week_end = week_end
    return r


def probe_url(url: str) -> int:
    """Thăm dò 1 trang SBV (diag-only, máy có mạng): status/size, trang tĩnh
    hay JS, số bảng, text đầu, link con liên quan lãi suất — để quyết định có
    làm được fetcher LNH THEO NGÀY từ trang 'Lãi suất' portal SBV không."""
    try:
        import requests
    except Exception:
        print("  ❌ thiếu requests")
        return 1
    try:
        resp = requests.get(url, headers=_SBV_HEADERS, timeout=30)
    except Exception as e:
        print(f"  ❌ fetch lỗi: {type(e).__name__}: {e}")
        return 1
    html = resp.text or ""
    print(f"  HTTP {resp.status_code} — {len(html):,} ký tự HTML")
    if resp.status_code != 200 or not html:
        return 1
    n_tables = len(re.findall(r"<table", html, re.I))
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    print(f"  <table>: {n_tables} — text nhìn thấy: {len(text):,} ký tự")
    kws = [k for k in ("qua đêm", "liên ngân hàng", "bình quân", "tái cấp vốn",
                       "%/năm") if k.lower() in text.lower()]
    print(f"  từ khoá lãi suất có mặt: {kws or 'KHÔNG — nghi trang render JS'}")
    print(f"\n  ── TEXT ĐẦU (1.500 ký tự) ──\n  {text[:1500]}\n")
    hrefs = sorted({h for h in re.findall(r'href="([^"#]+)"', html)
                    if re.search(r"l%C3%A3i|lãi|lai-suat|interbank", h, re.I)})
    print("  ── LINK CON liên quan lãi suất ──")
    for h in hrefs[:20] or ["  (không có)"]:
        print(f"    {h}")
    # XHR/API endpoint lộ trong HTML (trang JS hay gọi API nội bộ lấy bảng)
    apis = sorted({a for a in re.findall(
        r'["\'](/[^"\']*(?:api|Module|getdata|Service)[^"\']*)["\']', html, re.I)})
    if apis:
        print("  ── ENDPOINT nội bộ lộ trong HTML (ứng viên API bảng) ──")
        for a in apis[:15]:
            print(f"    {a}")
    return 0


# ── Cache + refresh + loaders ───────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    _META.mkdir(parents=True, exist_ok=True)
    p = _cache_path()
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def refresh(as_of: Optional[str] = None, verbose: bool = False) -> "dict | None":
    """Fetch bản tin tuần → ghi cache (chỉ các trường parse ĐƯỢC; None giữ
    giá trị cũ — merge-safe). Best-effort → None khi fetch lỗi.
    `as_of` = ngày DATA (thứ 6 tuần bản tin) — KHÔNG phải ngày fetch (mirror
    nguyên tắc data_date ≠ generated_at của market_overview)."""
    parsed = fetch_weekly(verbose=verbose)
    if parsed is None:
        return None
    cache = _load_cache()
    new = {k: v for k, v in asdict(parsed).items() if v is not None}
    if not new:
        return None
    cache.update(new)
    cache["as_of"] = as_of or parsed.week_end or datetime.now().date().isoformat()
    _save_cache(cache)
    return cache


def set_omo(value: float, as_of: Optional[str] = None) -> dict:
    """Nhập tay OMO ròng (tỷ VND, + = hút / − = bơm) khi fetch chưa chạy."""
    cache = _load_cache()
    cache["omo_net"] = float(value)
    cache["as_of"] = as_of or datetime.now().date().isoformat()
    _save_cache(cache)
    return cache


def load_weekly() -> dict:
    """Cache SBV hiện tại (dict; {} khi chưa có). Zero fetch."""
    return _load_cache()


def load_interbank_on() -> Optional[float]:
    return _load_cache().get("overnight")


def load_omo_net() -> Optional[float]:
    return _load_cache().get("omo_net")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bản tin tuần SBV: LNH + OMO + tỷ giá trung tâm")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--diag", action="store_true", help="thử fetch verbose (máy có mạng)")
    ap.add_argument("--dump-text", action="store_true",
                    help="in TEXT THÔ của PDF bài tuần (gửi lại để chỉnh regex parse)")
    ap.add_argument("--set-omo", type=float, metavar="TỶ_VND",
                    help="nhập tay OMO ròng (+ hút / − bơm)")
    ap.add_argument("--probe", metavar="URL",
                    help="thăm dò 1 trang SBV (tĩnh/JS? có bảng LNH ngày?) — máy có mạng")
    args = ap.parse_args(argv)

    if args.probe:
        print(f"[sbv] probe {args.probe}")
        return probe_url(args.probe)

    if args.dump_text:
        print("[sbv] tải PDF bài tuần & in text thô…")
        got = _fetch_pdf_text(verbose=True)
        if not got:
            print("  ❌ không lấy được PDF")
            return 1
        txt, week_end = got
        print(f"\n===== PDF TEXT ({len(txt):,} ký tự, tuần data kết {week_end}) — "
              "gửi lại phần lãi suất/OMO/tỷ giá cho tôi =====\n")
        print(txt[:6000])
        return 0
    if args.diag:
        print("[sbv] dựng URL bài tuần từ ngày (listing SBV là JS, không scrape)")
        r = fetch_weekly(verbose=True)
        print("  ✅ " + str(asdict(r)) if r else "  ❌ không lấy được")
        return 0 if r else 1
    if args.set_omo is not None:
        set_omo(args.set_omo)
        print(f"✅ OMO ròng = {args.set_omo:,.0f} tỷ VND")
    if args.refresh:
        c = refresh()
        print("✅ SBV refresh: " + str({k: v for k, v in (c or {}).items()})
              if c else "⚠️ SBV refresh không có data (giữ cache).")
    if args.show or not (args.refresh or args.diag or args.set_omo is not None):
        c = _load_cache()
        if not c:
            print("Chưa có cache SBV (chạy --refresh trên máy có mạng).")
            return 1
        print(f"🏦 Bản tin tuần SBV — as_of {c.get('as_of', '?')}")
        for k, lb in (("overnight", "LNH qua đêm"), ("one_week", "LNH 1 tuần"),
                      ("two_week", "LNH 2 tuần"), ("one_month", "LNH 1 tháng"),
                      ("fx_central", "Tỷ giá trung tâm"), ("omo_net", "OMO ròng (tỷ)")):
            if c.get(k) is not None:
                print(f"  {lb:>18}: {c[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
