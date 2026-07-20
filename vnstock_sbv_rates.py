"""
vnstock_sbv_rates.py — Lãi suất LNH bình quân THEO NGÀY từ portal SBV
=====================================================================
Nguồn LNH granularity NGÀY chính thức (nâng cấp từ 2 nguồn TUẦN: bản tin
SBV `vnstock_sbv` + VBMA PDF). Tìm ra 17/07/2026 khi user hỏi "muốn số liệu
luôn cập nhật nhất": trang `sbv.gov.vn/vi/lãi-suất-thị-trường-liên-ngân-hàng`
đổ bảng bằng **Liferay headless-delivery API** (lộ trong HTML unescape):

    /o/headless-delivery/v1.0/content-structures/3450260/structured-contents

JSON công khai, không cần key, totalCount ~3.100 bài = ~13 NĂM lịch sử ngày.
Mỗi item: `ngayApDung` (⚠️ midnight VN serialize thành `T17:00:00Z` hôm
TRƯỚC — phải +7h rồi lấy date, không thì lệch 1 ngày) + field lặp
`laiSuatThiTruongNganHangs` {thoihan, laiSuatBQLienNganHang (phẩy thập
phân), doanhSo (tỷ), footNode}. Kỳ hạn có footNode "(*)" = số THAM CHIẾU
ngày cũ độn vào (không có giao dịch) → LOẠI khỏi rates (không vào registry).

Trang "Lãi suất NHNN quy định" cùng cơ chế, structure id 3450482
(`_STRUCT_POLICY` — schema chưa soi, wire sbv_policy_rate là việc sau).

Mirror vnstock_hnx: fetch best-effort → cache `_meta/sbv_daily_rates.json`
(history theo ngày, giữ ~400 ngày — đủ mẫu percentile "trụ 4" VnBondLab) →
loaders public cho vnstock_macro (source "sbv_daily", recency tự thắng 2
nguồn tuần). Tắt: `VNSTOCK_SBV_DAILY=0`.

⚠️ VERIFY-GATED: sandbox chặn sbv.gov.vn → `--diag` chạy trên máy có mạng.

CLI:  python vnstock_sbv_rates.py --refresh | --show | --diag | --backfill N
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_CACHE = "sbv_daily_rates.json"
_RETAIN_DATES = 400
_TIMEOUT = 30
_REQUEST_GAP_S = 2.0                             # né WAF SBV (như vnstock_sbv)

_STRUCT_INTERBANK = 3450260                      # bảng LNH ngày (verify 17/07)
_STRUCT_POLICY = 3450482                         # lãi suất điều hành (chưa wire)
_API = ("https://www.sbv.gov.vn/o/headless-delivery/v1.0/content-structures/"
        "{sid}/structured-contents?pageSize={size}&page={page}"
        "&sort=datePublished:desc")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json",
}

# thoihan (chuẩn hoá lower) → key kỳ hạn. Registry macro chỉ dùng on/1w
# nhưng cache giữ đủ 7 kỳ hạn (curve LNH — để dành percentile/gauge sau).
_TENORS = {
    "qua đêm": "on", "1 tuần": "1w", "2 tuần": "2w", "1 tháng": "1m",
    "3 tháng": "3m", "6 tháng": "6m", "9 tháng": "9m",
}
_RATE_MIN, _RATE_MAX = 0.05, 25.0                # sanity %/năm


def _cache_path() -> Path:
    return _META / _CACHE


# ── Parse (thuần, testable với fixture JSON) ────────────────────────────────

def _vn_date(iso: str) -> Optional[str]:
    """'2026-07-14T17:00:00Z' → '2026-07-15' (midnight VN = 17:00Z hôm trước;
    KHÔNG +7h là lệch 1 ngày — bẫy thấy ngay trên data thật 17/07)."""
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt + timedelta(hours=7)).date().isoformat()


def _num(s) -> Optional[float]:
    """'4,16' → 4.16 (phẩy thập phân SBV) · '887615' → 887615.0."""
    try:
        return float(str(s).strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def parse_items(data: dict) -> list:
    """JSON headless-delivery → [{date, rates {key: %}, volumes {key: tỷ}}]
    (mới → cũ). Kỳ hạn footNode khác rỗng bị LOẠI khỏi rates (số tham chiếu
    ngày cũ độn vào); giá trị ngoài sanity range bị loại."""
    out = []
    for it in (data or {}).get("items") or []:
        day = None
        rates: dict[str, float] = {}
        vols: dict[str, float] = {}
        for cf in it.get("contentFields") or []:
            name = cf.get("name")
            if name == "ngayApDung":
                day = _vn_date((cf.get("contentFieldValue") or {}).get("data"))
            elif name == "laiSuatThiTruongNganHangs":
                row = {nf.get("name"): (nf.get("contentFieldValue") or {}).get("data")
                       for nf in cf.get("nestedContentFields") or []}
                key = _TENORS.get(str(row.get("thoihan") or "").strip().lower())
                if not key:
                    continue
                if str(row.get("footNode") or "").strip():
                    continue                     # số tham chiếu cũ — loại
                v = _num(row.get("laiSuatBQLienNganHang"))
                if v is not None and _RATE_MIN <= v <= _RATE_MAX:
                    rates[key] = round(v, 3)
                    vol = _num(row.get("doanhSo"))
                    if vol is not None:
                        vols[key] = vol
        if day and rates:
            out.append({"date": day, "rates": rates, "volumes": vols})
    return out


# ── Fetch (best-effort) ─────────────────────────────────────────────────────

def fetch_page(page: int = 1, size: int = 15, sid: int = _STRUCT_INTERBANK,
               verbose: bool = False) -> "dict | None":
    """1 trang JSON từ headless-delivery. None khi lỗi mạng/HTTP/JSON."""
    if os.environ.get("VNSTOCK_SBV_DAILY", "1") == "0":
        return None
    try:
        import requests
    except Exception:
        return None
    url = _API.format(sid=sid, size=size, page=page)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    except Exception as e:
        if verbose:
            print(f"    → LỖI {type(e).__name__}: {str(e)[:150]}")
        return None
    if resp.status_code != 200:
        if verbose:
            print(f"    → HTTP {resp.status_code}")
        return None
    try:
        return resp.json()
    except ValueError:
        if verbose:
            print("    → body không phải JSON")
        return None


def fetch_daily(verbose: bool = False) -> list:
    """Trang mới nhất (15 item ≈ 3 tuần) → list parse_items. [] khi lỗi."""
    data = fetch_page(verbose=verbose)
    return parse_items(data) if data else []


# ── Lãi suất điều hành (structure 3450482 — probe-api thật 17/07) ───────────
# totalCount=1: SBV chỉ giữ ĐÚNG 1 item = quyết định hiện hành (thay tại chỗ).
# ⚠️ BẪY DATA THẬT: field `ngayApDung` ghi SAI THÁNG (2023-03-18T17:00Z =
# 19/03 VN) trong khi title "19-06-2023" + QĐ "1123/QĐ-NHNN ngày 16/06/2023"
# → ngày hiệu lực đúng là 19/06/2023. Parser ưu tiên NGÀY TRONG TITLE
# (dd-MM-yyyy), fallback ngayApDung.

_POLICY_KINDS = {
    "tái cấp vốn": "refinancing",            # → registry sbv_policy_rate
    "tái chiết khấu": "discount",            # display-only (ngoài registry 13)
}


def _title_date(title: str) -> Optional[str]:
    """'19-06-2023' (title item điều hành) → '2023-06-19'."""
    m = None
    for m in re.finditer(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", title or ""):
        pass                                  # lấy match CUỐI nếu có nhiều
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).date().isoformat()
    except ValueError:
        return None


def parse_policy_items(data: dict) -> "dict | None":
    """JSON structure 3450482 → {as_of, refinancing, discount, decision}.
    None khi không parse được. Giá trị '4,500%' = 4.5 (phẩy thập phân)."""
    for it in (data or {}).get("items") or []:
        as_of = _title_date(it.get("title") or "")
        out: dict = {}
        for cf in it.get("contentFields") or []:
            name = cf.get("name")
            if name == "ngayApDung" and not as_of:
                as_of = _vn_date((cf.get("contentFieldValue") or {}).get("data"))
            elif name == "banglaiSuats":
                row = {nf.get("name"): (nf.get("contentFieldValue") or {}).get("data")
                       for nf in cf.get("nestedContentFields") or []}
                loai = str(row.get("loaiLaiSuat") or "").lower()
                key = next((v for k, v in _POLICY_KINDS.items() if k in loai), None)
                if not key:
                    continue
                v = _num(str(row.get("giaTri") or "").rstrip("%").strip())
                if v is not None and 0.1 <= v <= 20:
                    out[key] = round(v, 3)
                    if row.get("vanBanQuyetDinh"):
                        out.setdefault("decision", str(row["vanBanQuyetDinh"]))
        if as_of and out.get("refinancing") is not None:
            out["as_of"] = as_of
            return out
    return None


def refresh_policy(verbose: bool = False) -> "dict | None":
    """Fetch + parse lãi suất điều hành → ghi vào cache dưới key 'policy'.
    Best-effort: lỗi → GIỮ cache cũ, trả None."""
    data = fetch_page(size=5, sid=_STRUCT_POLICY, verbose=verbose)
    parsed = parse_policy_items(data) if data else None
    if not parsed:
        return None
    cache = _load_cache()
    cache["policy"] = parsed
    _save_cache(cache)
    return parsed


def load_policy() -> "dict | None":
    """{as_of, refinancing, discount, decision} từ cache. Zero fetch."""
    return _load_cache().get("policy") or None


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


def _merge(entries: list) -> "dict | None":
    """Gộp entries vào history cache (same-date replace, prune). None khi rỗng."""
    if not entries:
        return None
    cache = _load_cache()
    hist = cache.get("history")
    if not isinstance(hist, dict):
        hist = {}
    vols = cache.get("volumes")
    if not isinstance(vols, dict):
        vols = {}
    for e in entries:
        hist[e["date"]] = e["rates"]
        if e.get("volumes"):
            vols[e["date"]] = e["volumes"]
    for old in sorted(hist)[:-_RETAIN_DATES]:
        hist.pop(old, None)
        vols.pop(old, None)
    cache["history"], cache["volumes"] = hist, vols
    cache["as_of"] = max(hist)
    _save_cache(cache)
    return cache


def refresh(verbose: bool = False) -> "dict | None":
    """Fetch trang mới nhất → merge cache. Best-effort: lỗi → GIỮ cache cũ,
    trả None. `as_of` = ngày DATA mới nhất (ngayApDung, không phải ngày fetch)."""
    return _merge(fetch_daily(verbose=verbose))


def backfill(pages: int, verbose: bool = False) -> int:
    """Kéo lịch sử: N trang × 100 item (~5 tháng/trang). Trả số ngày merge.
    Giãn cách giữa các trang để né WAF. Chạy 1 lần trên máy có mạng khi muốn
    đủ mẫu percentile (~1 năm = 3 trang)."""
    total = 0
    for pg in range(1, max(1, pages) + 1):
        if pg > 1 and _REQUEST_GAP_S > 0:
            time.sleep(_REQUEST_GAP_S)
        data = fetch_page(page=pg, size=100, verbose=verbose)
        entries = parse_items(data) if data else []
        if verbose:
            print(f"  trang {pg}: {len(entries)} ngày")
        if entries:
            _merge(entries)
            total += len(entries)
    return total


def load_rates(as_of: Optional[str] = None) -> "tuple[str, dict] | None":
    """(ngày, {key kỳ hạn: %}) của ngày gần nhất ≤ ``as_of``. Zero fetch."""
    hist = _load_cache().get("history") or {}
    if not hist:
        return None
    days = sorted(hist)
    if as_of:
        days = [d for d in days if d <= as_of]
    if not days:
        return None
    d = days[-1]
    return d, hist[d]


def rate_on(tenor: str = "on", as_of: Optional[str] = None) -> Optional[float]:
    got = load_rates(as_of)
    return got[1].get(tenor) if got else None


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="LNH bình quân THEO NGÀY từ portal SBV (headless-delivery)")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--diag", action="store_true",
                    help="thử fetch 1 lần (verbose) — chạy trên máy có mạng")
    ap.add_argument("--backfill", type=int, metavar="N_TRANG",
                    help="kéo lịch sử N trang × 100 ngày (1 năm ≈ 3 trang)")
    ap.add_argument("--policy", action="store_true",
                    help="fetch lãi suất điều hành (structure 3450482) → cache")
    args = ap.parse_args(argv)

    if args.policy:
        p = refresh_policy(verbose=True)
        if p:
            print(f"✅ Điều hành (hiệu lực {p['as_of']}, {p.get('decision', '?')}): "
                  f"tái cấp vốn {p.get('refinancing')}%"
                  + (f", tái chiết khấu {p.get('discount')}%"
                     if p.get("discount") is not None else ""))
        else:
            print("⚠️ không fetch/parse được lãi suất điều hành.")
        return 0 if p else 1

    if args.diag:
        print(f"[sbv-daily] GET {_API.format(sid=_STRUCT_INTERBANK, size=3, page=1)}")
        entries = fetch_daily(verbose=True)
        if entries:
            for e in entries[:3]:
                print(f"  ✅ {e['date']}: " +
                      ", ".join(f"{k} {v}" for k, v in sorted(e["rates"].items())))
        else:
            print("  ❌ không lấy được (mạng chặn / endpoint đổi / schema đổi)")
        return 0 if entries else 1

    if args.backfill:
        n = backfill(args.backfill, verbose=True)
        print(f"✅ backfill {n} ngày vào cache." if n else "⚠️ backfill không có data.")

    if args.refresh:
        c = refresh()
        if c:
            d = c["as_of"]
            print(f"✅ SBV daily refresh — mới nhất {d}: " +
                  ", ".join(f"{k} {v}" for k, v in sorted(c["history"][d].items())))
        else:
            print("⚠️ SBV daily refresh không có data (giữ cache cũ).")

    if args.show or not (args.refresh or args.diag or args.backfill):
        got = load_rates()
        if not got:
            print("Chưa có cache (chạy --refresh trên máy có mạng).")
            return 1
        d, rates = got
        hist = _load_cache().get("history") or {}
        print(f"🏦 LNH bình quân theo ngày (SBV) — {len(hist)} ngày, mới nhất {d}")
        for k in ("on", "1w", "2w", "1m", "3m", "6m", "9m"):
            if k in rates:
                print(f"  {k:>3}: {rates[k]}%/năm")
        pol = load_policy()
        if pol:
            print(f"  Điều hành (hiệu lực {pol['as_of']}): tái cấp vốn "
                  f"{pol.get('refinancing')}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
