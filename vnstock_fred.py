#!/usr/bin/env python3
"""vnstock_fred.py — US10Y + lãi suất Fed từ FRED (Fed St. Louis).

Nguồn phát hiện qua khảo sát public-apis (2026-07-11). Lấp 2 gap đã ghi trong
CLAUDE.md từ khảo sát VnBondLab:
  * ``us10y``     (series DGS10, daily) → gauge chênh lệch VN10Y − US10Y
    ("trụ cột 3" của Macro Alert System — áp lực dòng vốn ngoại).
  * ``fed_funds`` (series DFF, daily)   → brief hết phải CẤM BỊA Fed
    (directive trong ``_macro_body_lines`` tự nới khi có reading).

Cần ``FRED_API_KEY`` trong .env — key FREE, đăng ký ~2 phút:
https://fred.stlouisfed.org/docs/api/api_key.html (120 req/phút, quá đủ —
mình gọi 2 request/ngày). KHÔNG có key → ``fetch_daily()`` trả None, macro
refresh bỏ qua nguồn này (best-effort như VBMA/NSO — không bao giờ bịa).
Tắt hẳn: env ``VNSTOCK_MACRO_FRED=0`` (đọc ở ``vnstock_macro.refresh``).

Verify trên máy có mạng (sandbox dev chặn egress → luôn FAIL ở đây):

    python vnstock_fred.py --diag

Tiêu thụ: ``vnstock_macro._fetch_fred()`` → ghi registry (source="fred").
``--set us10y <số>`` tay vẫn là đường sống như mọi chỉ số khác.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 15

# key registry → series FRED. Thêm series mới = thêm 1 entry ở đây + _RANGES
# + _DEFS bên vnstock_macro (cùng pattern _YIELD_TENORS của vnstock_vbma).
_SERIES = {
    "us10y": "DGS10",        # Market Yield on U.S. Treasury 10-Year (daily)
    "fed_funds": "DFF",      # Effective Federal Funds Rate (daily)
}

# Sanity range (%/năm) — ngoài khoảng coi như payload lạ, bỏ.
_RANGES = {
    "us10y": (0.1, 20.0),
    "fed_funds": (0.0, 20.0),
}


def _api_key() -> str:
    return (os.environ.get("FRED_API_KEY") or "").strip()


def _in_range(key: str, v: float) -> bool:
    lo, hi = _RANGES[key]
    return lo <= v <= hi


def fetch_series(series_id: str, api_key: str) -> "tuple[float, str] | None":
    """(giá trị, ngày ISO) của observation hợp lệ MỚI NHẤT — None khi fail.

    FRED đánh dấu ngày thiếu data (cuối tuần/lễ với DGS10) bằng value "." →
    lấy observation số đầu tiên theo thứ tự ngày giảm dần.
    """
    try:
        import requests as _req
        resp = _req.get(_BASE, params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 10,                    # đủ nhảy qua chuỗi ngày "." liên tiếp
        }, timeout=_TIMEOUT)
        resp.raise_for_status()
        obs = (resp.json() or {}).get("observations") or []
    except Exception:
        return None
    for o in obs:
        raw = str(o.get("value", ".")).strip()
        if raw in (".", ""):
            continue
        try:
            return float(raw), str(o.get("date", ""))[:10]
        except ValueError:
            continue
    return None


def fetch_daily() -> "dict | None":
    """{key: (value, as_of_iso)} cho các series fetch được — None khi không có
    FRED_API_KEY hoặc không series nào về (caller giữ cache cũ)."""
    key = _api_key()
    if not key:
        return None
    out: dict = {}
    for name, sid in _SERIES.items():
        got = fetch_series(sid, key)
        if got and _in_range(name, got[0]):
            out[name] = got
    return out or None


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: "list[str] | None" = None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="FRED US10Y + Fed funds — diag")
    ap.add_argument("--diag", action="store_true",
                    help="Fetch thử 1 lần, in kết quả (xác minh trên máy có mạng)")
    a = ap.parse_args(argv)
    if not a.diag:
        ap.print_help()
        return 0

    if not _api_key():
        print("FRED_API_KEY: CHƯA CÓ trong .env — đăng ký free (~2 phút):")
        print("  https://fred.stlouisfed.org/docs/api/api_key.html")
        print("  rồi thêm dòng FRED_API_KEY=<key> vào .env")
        return 1
    print("FRED_API_KEY: có")
    got = fetch_daily()
    if not got:
        print("fetch: FAIL — kiểm tra mạng/allowlist (api.stlouisfed.org) hoặc key")
        return 1
    for name, (val, as_of) in got.items():
        print(f"  {name} ({_SERIES[name]}): {val} (%/năm, ngày {as_of})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
