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


def parse_sbv_text(text: str) -> SBVWeekly:
    """Text PDF bản tin tuần SBV → SBVWeekly. Mỗi trường best-effort (thiếu →
    None). Lãi suất LNH: '<kỳ hạn> ... <số>%'; tỷ giá trung tâm; OMO hút/bơm."""
    r = SBVWeekly()
    if not text:
        return r
    t = text

    # Lãi suất LNH theo kỳ hạn — 'Qua đêm/Overnight/O/N', '1 tuần', '2 tuần', '1 tháng'
    def _rate(*labels) -> Optional[float]:
        for lb in labels:
            m = re.search(rf"{lb}[^0-9%]{{0,25}}(\d{{1,2}}[.,]\d{{1,4}})\s*%?",
                          t, re.I)
            if m:
                return _num(m.group(1))
        return None

    r.overnight = _rate("qua đêm", "overnight", r"\bO/N\b")
    r.one_week = _rate("1 tuần", r"\b1W\b")
    r.two_week = _rate("2 tuần", r"\b2W\b")
    r.one_month = _rate("1 tháng", r"\b1M\b")

    # Tỷ giá trung tâm — 'tỷ giá trung tâm ... 25.140'
    m = re.search(r"tỷ giá trung tâm[^0-9]{0,40}(\d{1,2}[.,]\d{3})", t, re.I)
    if m:
        r.fx_central = _thousands(m.group(1))

    # OMO ròng — 'hút (ròng) ... X tỷ' (+) hoặc 'bơm (ròng) ... X tỷ' (−).
    # Chọn cụm XUẤT HIỆN TRƯỚC (thường là kết luận ròng của tuần).
    mh = re.search(r"hút[^0-9]{0,30}?(\d{1,3}(?:[.,]\d{3})*)\s*tỷ", t, re.I)
    mb = re.search(r"bơm[^0-9]{0,30}?(\d{1,3}(?:[.,]\d{3})*)\s*tỷ", t, re.I)
    if mh and (not mb or mh.start() <= mb.start()):
        r.omo_net = _thousands(mh.group(1))
    elif mb:
        v = _thousands(mb.group(1))
        r.omo_net = -v if v is not None else None
    return r


# ── Cross-source resolution SBV ↔ VBMA (mirror _fx_crosscheck) ──────────────

def resolve_interbank_on(sbv: Optional[float], vbma: Optional[float]
                         ) -> "tuple[Optional[float], str, bool]":
    """LNH ON từ 2 nguồn → (giá trị, nguồn, cờ_lệch). Có cả 2 → ưu tiên SBV
    (chính thức) nhưng cờ lệch khi chênh > ngưỡng. Thiếu 1 → dùng nguồn kia."""
    if sbv is None and vbma is None:
        return None, "none", False
    if sbv is None:
        return vbma, "vbma", False
    if vbma is None:
        return sbv, "sbv", False
    avg = (sbv + vbma) / 2
    diverged = avg > 0 and abs(sbv - vbma) / avg * 100 > _INTERBANK_DIVERGENCE_PCT
    return sbv, "sbv", bool(diverged)


# ── Fetch (best-effort, verify-gated) ───────────────────────────────────────

_SBV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://www.sbv.gov.vn/vi/web/sbv_portal/"
               "thong-tin-ve-hoat-dong-ngan-hang-trong-tuan",
}
_SBV_LISTING = ("https://www.sbv.gov.vn/vi/web/sbv_portal/"
                "thong-tin-ve-hoat-dong-ngan-hang-trong-tuan")

# Ứng viên link bài tuần — thử nhiều dạng (SBV đổi cấu trúc theo thời gian).
# Từ khoá "trong-tuan"/"hoat-dong-ngan-hang" nhận diện bài; loại chính trang
# listing. Thứ tự = ưu tiên (bài /w/ slug trước, rồi .htm/aspx).
_ARTICLE_PATTERNS = (
    r'href="(/vi/web/sbv_portal/w/[^"?#]*(?:tuan|hoat-dong-ngan-hang)[^"?#]*)"',
    r'href="(https?://[^"]*sbv\.gov\.vn/[^"?#]*hoat-dong-ngan-hang[^"?#]*(?:tuan)[^"?#]*)"',
    r'href="(/[^"?#]*hoat-dong-ngan-hang[^"?#]*tuan[^"?#]*\.(?:htm|html|aspx)[^"]*)"',
    r'href="(/[^"?#]*(?:ban-tin|thong-tin)[^"?#]*tuan[^"?#]*)"',
)


def _find_article_link(html: str) -> Optional[str]:
    """Link bài tuần mới nhất trong listing — thử nhiều pattern. Bỏ chính
    URL trang listing (nó cũng chứa 'trong-tuan')."""
    listing_tail = _SBV_LISTING.split("/")[-1]
    for pat in _ARTICLE_PATTERNS:
        for m in re.finditer(pat, html, re.I):
            href = m.group(1)
            if listing_tail and href.rstrip("/").endswith(listing_tail):
                continue                     # đây là link về chính trang listing
            return href
    return None


def _candidate_links(html: str) -> list:
    """Mọi href nội bộ 'có vẻ là bài' — để --diag in ra cho user gửi lại khi
    regex trượt (không đoán được cấu trúc từ sandbox)."""
    out, seen = [], set()
    for m in re.finditer(r'href="(/[^"?#]+|https?://[^"?#]*sbv\.gov\.vn/[^"?#]+)"',
                         html, re.I):
        h = m.group(1)
        low = h.lower()
        if any(k in low for k in ("tuan", "ngan-hang", "ban-tin", "sbv_portal/w/")) \
                and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def fetch_weekly(verbose: bool = False) -> "SBVWeekly | None":
    """Bài tuần SBV mới nhất → PDF → text → parse. None khi lỗi/không tìm thấy.

    Đi qua trang listing → link bài mới nhất → PDF nhúng (URL cần uuid). Dùng
    lại `pdf_to_text` của vnstock_vbma. VERIFY trên máy có mạng (--diag)."""
    if os.environ.get("VNSTOCK_SBV", "1") == "0":
        return None
    try:
        import requests
        from vnstock_vbma import pdf_to_text
    except Exception:
        return None
    try:
        html = requests.get(_SBV_LISTING, headers=_SBV_HEADERS, timeout=30).text
    except Exception as e:
        if verbose:
            print(f"    → listing FAIL: {type(e).__name__}: {str(e)[:150]}")
        return None
    if verbose:
        print(f"    → listing tải OK ({len(html):,} ký tự)")
    art_path = _find_article_link(html)
    if not art_path:
        if verbose:
            print("    → không tìm thấy link bài tuần trong listing")
            cands = _candidate_links(html)
            if cands:
                print(f"    → {len(cands)} link ứng viên trên trang (gửi lại để chỉnh regex):")
                for h in cands[:20]:
                    print(f"        {h}")
            else:
                print("    → trang KHÔNG có href nội bộ nào (có thể load qua JS "
                      "→ cần API/endpoint khác, xem Network tab DevTools)")
        return None
    art_url = art_path if art_path.startswith("http") \
        else "https://www.sbv.gov.vn" + art_path
    try:
        art = requests.get(art_url, headers=_SBV_HEADERS, timeout=30).text
    except Exception:
        return None
    pm = re.search(r'href="(/documents/\d+/[^"]+\.pdf[^"]*)"', art, re.I)
    if not pm:
        if verbose:
            print("    → không tìm thấy PDF nhúng trong bài")
        return None
    pdf_url = "https://www.sbv.gov.vn" + pm.group(1).replace("&amp;", "&")
    try:
        data = requests.get(pdf_url, headers=_SBV_HEADERS, timeout=45).content
    except Exception:
        return None
    text = pdf_to_text(data)
    if not text:
        return None
    return parse_sbv_text(text)


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
    giá trị cũ — merge-safe). Best-effort → None khi fetch lỗi."""
    parsed = fetch_weekly(verbose=verbose)
    if parsed is None:
        return None
    cache = _load_cache()
    new = {k: v for k, v in asdict(parsed).items() if v is not None}
    if not new:
        return None
    cache.update(new)
    cache["as_of"] = as_of or datetime.now().date().isoformat()
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
    ap.add_argument("--set-omo", type=float, metavar="TỶ_VND",
                    help="nhập tay OMO ròng (+ hút / − bơm)")
    args = ap.parse_args(argv)

    if args.diag:
        print(f"[sbv] listing {_SBV_LISTING}")
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
