#!/usr/bin/env python3
"""vnstock_gold.py — Giá vàng spot quốc tế (P6, display-only + proxy return).

Vị trí trong thiết kế (user duyệt 2026-07-13): lớp tài sản "Vàng" có trong
bảng phân bổ từ v1, tin vàng/PNJ xuất hiện thường xuyên mà brief chỉ có TIN
không có SỐ (mục để-dành 1c). Module này lấp đúng chỗ đó:

* **Display-only + proxy return** — KHÔNG vào registry 13 chỉ số vĩ mô
  (cap đã chốt; tầng SỐ ĐO của macro ≠ ngữ cảnh hiển thị). Nơi dùng:
  sub-tab Phân bổ (P5) + proxy return lớp Vàng cho scorecard (P6).
* **Nhãn bắt buộc**: đây là SPOT QUỐC TẾ (USD/oz) — giá SJC trong nước
  thường cao hơn ~15-20% (premium), TUYỆT ĐỐI không trình bày như giá vàng
  trong nước.
* Fetch best-effort mirror FX ladder của vnstock_macro: thử lần lượt các
  endpoint free-không-key, sanity range, fail → GIỮ cache cũ, KHÔNG bịa.
  Sandbox/web session bị allowlist chặn → --diag luôn FAIL ở đây, verify
  trên máy có mạng. (Ghi chú khảo sát 1c nêu "Goldprice.dev"; API cụ thể
  chưa xác minh được nên ladder dùng 2 endpoint đã biết shape:
  goldprice.org dbXRates + gold-api.com — chỉnh ở ``_ENDPOINTS`` nếu chết.)

Cache: ``data_warehouse/_meta/gold_price.json`` — {history: {date: usd_oz}}.
CLI: ``--refresh`` / ``--show`` / ``--diag``. Tắt trong pipeline:
``VNSTOCK_GOLD=0``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "gold_price.json"

_MAX_HISTORY = 400
_RANGE = (500.0, 20000.0)          # USD/oz sanity
_SJC_PREMIUM_NOTE = "spot quốc tế, CHƯA gồm premium SJC (~15-20%)"

# (url, parser) — parser nhận dict JSON, trả USD/oz hoặc None. Thử theo thứ tự.
_ENDPOINTS = (
    ("https://data-asg.goldprice.org/dbXRates/USD",
     lambda d: (d.get("items") or [{}])[0].get("xauPrice")),
    ("https://api.gold-api.com/price/XAU",
     lambda d: d.get("price")),
)


def _enabled() -> bool:
    return os.environ.get("VNSTOCK_GOLD", "1") != "0"


def fetch_gold_usd(timeout: int = 15) -> "float | None":
    """USD/oz spot qua ladder endpoint — None khi mọi nguồn fail/ngoài range."""
    try:
        import requests
    except ImportError:
        return None
    for url, parse in _ENDPOINTS:
        try:
            resp = requests.get(url, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            v = parse(resp.json())
            v = float(v)
            if _RANGE[0] <= v <= _RANGE[1]:
                return round(v, 2)
        except Exception:
            continue
    return None


# ── Cache I/O ────────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    try:
        if _CACHE.exists():
            return json.loads(_CACHE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _write_cache(cache: dict) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _CACHE)


def refresh() -> "float | None":
    """Fetch + ghi reading hôm nay vào history. Fail → giữ cache cũ nguyên
    vẹn, trả None (mirror triết lý FX của vnstock_macro)."""
    if not _enabled():
        return None
    v = fetch_gold_usd()
    if v is None:
        print("[gold] ⚠ không fetch được giá vàng — giữ cache cũ "
              "(sandbox chặn mạng là bình thường)")
        return None
    cache = _load_cache()
    hist = cache.setdefault("history", {})
    hist[date.today().isoformat()] = v
    if len(hist) > _MAX_HISTORY:
        for k in sorted(hist)[:len(hist) - _MAX_HISTORY]:
            hist.pop(k)
    _write_cache(cache)
    print(f"[gold] ✅ {v:,.2f} USD/oz ({_SJC_PREMIUM_NOTE})")
    return v


def load_gold() -> "dict | None":
    """Reading gần nhất + change so với reading trước:
    ``{value, as_of, note, change: {delta, pct, dir} | None}``; None khi trống."""
    hist = _load_cache().get("history") or {}
    if not hist:
        return None
    dates = sorted(hist)
    as_of = dates[-1]
    value = float(hist[as_of])
    out = {"value": value, "as_of": as_of, "note": _SJC_PREMIUM_NOTE,
           "change": None}
    if len(dates) >= 2:
        prev = float(hist[dates[-2]])
        if prev:
            delta = round(value - prev, 2)
            pct = round(delta / prev * 100, 2)
            out["change"] = {"delta": delta, "pct": pct,
                             "dir": 1 if delta > 0 else (-1 if delta < 0 else 0),
                             "prev_as_of": dates[-2]}
    return out


def price_on(date_iso: str) -> "float | None":
    """Reading gần nhất TRƯỚC HOẶC BẰNG ``date_iso`` — cho proxy return của
    scorecard (kỳ tháng, không cần đúng từng ngày)."""
    hist = _load_cache().get("history") or {}
    ok = [d for d in hist if d <= date_iso]
    return float(hist[max(ok)]) if ok else None


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Giá vàng spot quốc tế (display-only)")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--diag", action="store_true",
                    help="thử fetch 1 lần (chạy trên máy có mạng)")
    args = ap.parse_args(argv)
    if args.refresh:
        return 0 if refresh() is not None else 1
    if args.diag:
        v = fetch_gold_usd()
        print(f"gold fetch: {f'{v:,.2f} USD/oz' if v else 'FAIL — mạng chặn / endpoint đổi (sửa _ENDPOINTS)'}")
        return 0 if v else 1
    g = load_gold()
    if not g:
        print("[gold] cache trống — chạy --refresh trên máy có mạng")
        return 1
    ch = g.get("change")
    extra = (f" ({'▲' if ch['dir'] > 0 else '▼'} {ch['pct']:+.2f}% so với "
             f"{ch['prev_as_of']})" if ch and ch["dir"] else "")
    print(f"🥇 Vàng {g['value']:,.2f} USD/oz — as_of {g['as_of']}{extra}")
    print(f"   ({g['note']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
