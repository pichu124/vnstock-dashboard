"""
vnstock_hnx.py — Lợi suất TPCP từ HNX (đường cong 8 kỳ hạn, theo NGÀY)
======================================================================
Nguồn TPCP CHÍNH THỨC granularity NGÀY từ Sở GDCK Hà Nội (HNX = sàn niêm
yết trái phiếu). Thay/bổ sung `vnstock_vbma._parse_bond_yields` (PDF tuần,
mong manh, chỉ 2Y/10Y): HNX cho **1Y/2Y/3Y/5Y/7Y/10Y/15Y/20Y mỗi ngày**.

Khảo sát repo Thanhtran-165/baocaolaisuatvatiente (2026-07-16, no LICENSE
→ mượn Ý TƯỞNG + endpoint/tenor-map, KHÔNG copy code). Mô-đun này tự viết
theo mẫu vnstock_vbma/nso/fred: fetch best-effort → parse HTML → cache
`_meta/hnx_yields.json` (history theo ngày) → loaders public cho vnstock_macro.

Endpoint POST `pDate=dd/mm/YYYY` → bảng HTML (tbody > tr > td: cột 0 = kỳ
hạn "N năm", cột lợi suất par). SSL: HNX thiếu chứng chỉ TRUNG GIAN (giống
NSO/GSO) → TLS ladder 3 nấc (certifi → OS trust → verify=False chỉ nguồn
này; `VNSTOCK_HNX_TLS_STRICT=1` cấm nấc cuối). Tắt cả module: `VNSTOCK_HNX=0`.

⚠️ VERIFY-GATED: sandbox chặn hnx.vn → `--diag` phải chạy trên máy có mạng;
endpoint + selector bảng là ứng viên CHƯA verify (đổi thì sửa tại đây).

CLI:  python vnstock_hnx.py --refresh | --show | --diag [YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import ssl
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"      # tests monkeypatch chỗ này
_CACHE = "hnx_yields.json"
_RETAIN_DATES = 260                              # ~1 năm phiên (đủ percentile)
_TIMEOUT = 30

_HNX_YIELD_URL = ("https://hnx.vn/ModuleReportBonds/Bond_YieldCurve/"
                  "SearchAndNextPageYieldCurveData")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Kỳ hạn VN → nhãn chuẩn (khớp key registry macro govt_bond_yield_2y/10y).
# Match CHÍNH XÁC chuỗi ("15 năm" KHÔNG được match "5 năm").
_TENORS = {
    "1 năm": "1Y", "2 năm": "2Y", "3 năm": "3Y", "5 năm": "5Y",
    "7 năm": "7Y", "10 năm": "10Y", "15 năm": "15Y", "20 năm": "20Y",
}
_YIELD_MIN, _YIELD_MAX = 0.1, 15.0               # sanity range lợi suất (%)


def _cache_path() -> Path:
    return _META / _CACHE


# ── TLS ladder cho POST (mirror vnstock_nso._http_get, dạng POST) ───────────

def _os_trust_session():
    import requests
    from requests.adapters import HTTPAdapter

    class _OSTrustAdapter(HTTPAdapter):
        def init_poolmanager(self, *a, **k):
            k["ssl_context"] = ssl.create_default_context()
            return super().init_poolmanager(*a, **k)

    s = requests.Session()
    s.mount("https://", _OSTrustAdapter())
    return s


def _http_post(url: str, data: dict, verbose: bool = False):
    """POST trả requests.Response (hoặc None). 3 nấc TLS như NSO."""
    import requests
    try:
        return requests.post(url, data=data, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.exceptions.SSLError:
        if verbose:
            print("    → certifi FAIL (thiếu intermediate) — thử OS trust store")
    except requests.RequestException as e:
        if verbose:
            print(f"    → LỖI {type(e).__name__}: {str(e)[:200]}")
        return None
    try:
        return _os_trust_session().post(url, data=data, headers=_HEADERS,
                                        timeout=_TIMEOUT)
    except requests.exceptions.SSLError:
        if verbose:
            print("    → OS trust FAIL — fallback verify=False (chỉ nguồn này)")
    except requests.RequestException:
        return None
    if os.environ.get("VNSTOCK_HNX_TLS_STRICT") == "1":
        return None
    import urllib3
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        try:
            return requests.post(url, data=data, headers=_HEADERS,
                                 timeout=_TIMEOUT, verify=False)
        except requests.RequestException:
            return None


# ── Parse (thuần, testable với fixture HTML) ────────────────────────────────

def _vn_float(s: str) -> Optional[float]:
    """'4,40' → 4.40 · '4.40' → 4.40 · '-'/'' → None."""
    s = (s or "").strip().rstrip("%").strip()
    if s in ("", "-", "N/A", "NA"):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_yield_curve_html(html: str) -> dict:
    """Bảng HTML HNX → {nhãn kỳ hạn chuẩn: lợi suất par (%)}.

    Mỗi <tr> trong <tbody>: cột 0 = kỳ hạn ("N năm"), lấy giá trị par ở cột
    có lợi suất trong ngưỡng hợp lý (thử cột 2 trước — theo layout HNX — rồi
    cột 1). Match kỳ hạn CHÍNH XÁC; giá trị ngoài [0.1,15] bị loại."""
    if not html or "<tbody" not in html.lower():
        return {}
    tb = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, re.S | re.I)
    if not tb:
        return {}
    out: dict[str, float] = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 2:
            continue
        cells = [_html.unescape(re.sub(r"<[^>]+>", "", td)).strip() for td in tds]
        label = _TENORS.get(cells[0])
        if not label or label in out:
            continue
        val = None
        for idx in (2, 1, 3):                    # ưu tiên cột par (layout HNX)
            if idx < len(cells):
                v = _vn_float(cells[idx])
                if v is not None and _YIELD_MIN < v < _YIELD_MAX:
                    val = v
                    break
        if val is not None:
            out[label] = round(val, 3)
    return out


def fetch_yield_curve(target: date, verbose: bool = False) -> dict:
    """Lợi suất đường cong 1 ngày. {} khi không có data / lỗi mạng."""
    resp = _http_post(_HNX_YIELD_URL, {"pDate": target.strftime("%d/%m/%Y")},
                      verbose=verbose)
    if resp is None:
        return {}
    try:
        text = resp.text
    except Exception:
        return {}
    if "không tìm thấy" in text.lower() or len(text) < 400:
        return {}
    return parse_yield_curve_html(text)


def fetch_latest(as_of: Optional[date] = None, max_back: int = 7,
                 verbose: bool = False) -> "tuple[date, dict] | None":
    """Lùi từ ``as_of`` (mặc định hôm nay), bỏ T7/CN, trả (ngày, yields) của
    phiên gần nhất có data. None nếu ``max_back`` ngày đều trống."""
    cur = as_of or datetime.now().date()
    for _ in range(max_back + 1):
        if cur.weekday() < 5:                    # HNX không công bố T7/CN
            ys = fetch_yield_curve(cur, verbose=verbose)
            if ys:
                return cur, ys
        cur -= timedelta(days=1)
    return None


# ── Cache + refresh ─────────────────────────────────────────────────────────

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
    """Fetch phiên gần nhất → ghi vào history cache. Best-effort: lỗi/rỗng →
    GIỮ cache cũ, trả None. Trả dict yields khi thành công."""
    if os.environ.get("VNSTOCK_HNX", "1") == "0":
        return None
    ref = date.fromisoformat(as_of) if as_of else None
    got = fetch_latest(ref, verbose=verbose)
    if not got:
        return None
    day, yields = got
    cache = _load_cache()
    hist = cache.get("history")
    if not isinstance(hist, dict):
        hist = {}
    hist[day.isoformat()] = yields                # same-date replace
    for old in sorted(hist)[:-_RETAIN_DATES]:     # prune ngày cũ
        hist.pop(old, None)
    cache["history"] = hist
    cache["as_of"] = day.isoformat()
    cache["latest"] = yields
    _save_cache(cache)
    return yields


# ── Loaders public (cho vnstock_macro / dashboard) ──────────────────────────

def load_yields(as_of: Optional[str] = None) -> "tuple[str, dict] | None":
    """(ngày, {tenor: yield}) của phiên gần nhất ≤ ``as_of`` trong cache.
    None khi cache trống. Zero fetch."""
    cache = _load_cache()
    hist = cache.get("history") or {}
    if not hist:
        return None
    days = sorted(hist)
    if as_of:
        days = [d for d in days if d <= as_of]
    if not days:
        return None
    d = days[-1]
    return d, hist[d]


def yield_on(tenor: str, as_of: Optional[str] = None) -> Optional[float]:
    """Lợi suất 1 kỳ hạn ("2Y"/"10Y"…) của phiên gần nhất ≤ as_of."""
    got = load_yields(as_of)
    if not got:
        return None
    return got[1].get(tenor)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lợi suất TPCP từ HNX (8 kỳ hạn/ngày)")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--diag", nargs="?", const="", metavar="YYYY-MM-DD",
                    help="thử fetch 1 lần (verbose) — chạy trên máy có mạng")
    args = ap.parse_args(argv)

    if args.diag is not None:
        ref = date.fromisoformat(args.diag) if args.diag else None
        print(f"[hnx] POST {_HNX_YIELD_URL}")
        got = fetch_latest(ref, verbose=True)
        if got:
            d, ys = got
            print(f"  ✅ {d}: " + ", ".join(f"{k} {v}" for k, v in ys.items()))
        else:
            print("  ❌ không lấy được data (mạng chặn / endpoint đổi / ngày trống)")
        return 0 if got else 1

    if args.refresh:
        ys = refresh()
        if ys:
            print("✅ HNX refresh: " + ", ".join(f"{k} {v}" for k, v in ys.items()))
        else:
            print("⚠️ HNX refresh không có data mới (giữ cache cũ).")

    if args.show or not (args.refresh or args.diag is not None):
        got = load_yields()
        if not got:
            print("Chưa có cache HNX (chạy --refresh trên máy có mạng).")
            return 1
        d, ys = got
        print(f"📈 Đường cong TPCP HNX — phiên {d}")
        for k in ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y"):
            if k in ys:
                print(f"  {k:>4}: {ys[k]:.3f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
