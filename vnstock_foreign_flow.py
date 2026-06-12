#!/usr/bin/env python3
"""Full-market foreign net flow (NN ròng) — daily, ALL symbols, CLI/pipeline-safe.

Why this module exists
----------------------
The dashboard's ``_fetch_foreign_net_flow`` fetches only the TOP-100 foreign
buy/sell symbols (``limit=100``) via ``vnstock_data.TopStock``, and that cache is
the ONLY source ``vnstock_regime._load_nn_net_1d`` reads for the brief's
"NN ròng 1D" sentiment signal. Two consequences (observed 12/06):

* the top-100 sum OVERSTATES net selling — it misses the long tail of small-cap
  net buyers and drops the buy offset for symbols that appear only on the sell
  side (e.g. it reported -665 tỷ vs the real market -491 tỷ); and
* that cache is refreshed ONLY when the Streamlit Money-Flow tab is opened, and
  ``_load_nn_net_1d`` read it ignoring age → the brief showed a FROZEN value
  labelled "phiên hôm nay" (the same -665 appeared for both 11/06 and 12/06).

This module fetches the FULL universe (a high ``limit``) for each trading day,
sums the market-total net, caches it PER DATE, and exposes a freshness-aware
loader so the brief uses the right session's value — or omits it, never a stale
one.

Accuracy note: this is matched-order foreign value from TopStock summed over
EVERY symbol the API returns (no top-N truncation). It still depends on the API
returning the whole board for a large ``limit``. Verify on a machine with
network access:

    python vnstock_foreign_flow.py --diag 2026-06-12

which prints the net + how many symbols came back (a full HOSE/HNX/UPCOM day is
several hundred, not 100). Refresh the per-date cache for the pipeline with:

    python vnstock_foreign_flow.py --refresh --days 5
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date, timedelta as _td
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "foreign_net_daily.json"
# High enough to return the entire HOSE/HNX/UPCOM board in one call.
_FULL_LIMIT = 3000

# Value-named columns checked first (names drift across vnstock/vnstock_data
# versions); mirrors the dashboard's extraction so per-symbol values match.
_VALUE_KEYS = ("net_value", "buy_value", "sell_value", "value", "total_value",
               "netvalue", "buyvalue", "sellvalue")


def _largest_value(row: dict) -> float:
    """Largest |numeric| in the row (excluding symbol/date columns)."""
    best = 0.0
    for k in _VALUE_KEYS:
        v = row.get(k)
        if v is not None:
            try:
                fv = abs(float(v))
                if fv > best:
                    best = fv
            except (TypeError, ValueError):
                pass
    if best == 0.0:
        for k, v in row.items():
            if k == "symbol" or "date" in str(k).lower():
                continue
            try:
                fv = abs(float(v))
                if fv > best:
                    best = fv
            except (TypeError, ValueError):
                pass
    return best


def fetch_market_net(date_str: str, limit: int = _FULL_LIMIT) -> dict | None:
    """Fetch FULL-market foreign buy/sell for one trading day.

    Returns ``{date, net, buy, sell, n_symbols}`` in tỷ VND, or None when the
    API is unavailable / returns nothing. ``net = Σ(buy_value − sell_value)``
    over EVERY symbol returned (not just the top-N).
    """
    try:
        from vnstock_data import TopStock
    except ImportError:
        return None
    ts = TopStock()
    rows: dict[str, dict] = {}
    got = False
    for side, fn in (("buy", ts.foreign_buy), ("sell", ts.foreign_sell)):
        try:
            df = fn(date=date_str, limit=limit)
        except Exception:
            continue
        if df is None or getattr(df, "empty", True):
            continue
        got = True
        for _, r in df.iterrows():
            row = dict(r)
            sym = str(row.get("symbol", "") or "").strip()
            if not sym:
                continue
            val = _largest_value(row)
            ent = rows.setdefault(sym, {"buy": 0.0, "sell": 0.0})
            ent[side] = max(ent[side], val)
    if not got or not rows:
        return None
    buy = sum(e["buy"] for e in rows.values())
    sell = sum(e["sell"] for e in rows.values())
    return {
        "date": date_str,
        "net": round((buy - sell) / 1e9, 1),
        "buy": round(buy / 1e9, 1),
        "sell": round(sell / 1e9, 1),
        "n_symbols": len(rows),
    }


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8")) if _CACHE.exists() else {}
    except (OSError, ValueError):
        return {}


def _save_cache(d: dict) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(d, ensure_ascii=False, sort_keys=True, indent=0),
                          encoding="utf-8")
    except OSError:
        pass


def refresh(days: int = 5, limit: int = _FULL_LIMIT) -> dict:
    """Fetch the last ``days`` trading days (skipping weekends) and merge into
    the per-date cache. Returns the updated cache (possibly unchanged when the
    API is unavailable)."""
    cache = _load_cache()
    today = _date.today()
    fetched, cal = 0, 0
    while fetched < days and cal < days * 2 + 4:
        dt = today - _td(days=cal)
        cal += 1
        if dt.weekday() >= 5:        # skip Sat/Sun
            continue
        rec = fetch_market_net(dt.isoformat(), limit=limit)
        fetched += 1
        if rec:
            cache[rec["date"]] = {k: rec[k] for k in ("net", "buy", "sell", "n_symbols")}
    _save_cache(cache)
    return cache


def load_market_net_1d(effective_date: str | None = None) -> float | None:
    """Return the market-total NN ròng (tỷ) for ``effective_date`` (ISO) from the
    per-date cache, or the latest cached day when no date is given.

    Returns None when the date isn't cached — callers MUST treat None as
    "no fresh data" and never fall back to a stale figure labelled "today".
    """
    cache = _load_cache()
    if not cache:
        return None
    rec = cache.get(effective_date) if effective_date else cache.get(max(cache))
    if rec and rec.get("net") is not None:
        try:
            return float(rec["net"])
        except (TypeError, ValueError):
            return None
    return None


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Full-market foreign net flow (NN ròng).")
    ap.add_argument("--refresh", action="store_true",
                    help="Fetch last --days trading days → per-date cache")
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--limit", type=int, default=_FULL_LIMIT,
                    help=f"Symbols per side (default {_FULL_LIMIT} = full board)")
    ap.add_argument("--diag", metavar="YYYY-MM-DD",
                    help="Fetch ONE day live and print the full breakdown (verify vs official)")
    a = ap.parse_args(argv)

    if a.diag:
        rec = fetch_market_net(a.diag, limit=a.limit)
        if not rec:
            print(f"[foreign-flow] no data for {a.diag} (API unavailable or empty)")
            return 1
        print(f"[foreign-flow] {rec['date']}: NN ròng = {rec['net']:+,.1f} tỷ "
              f"(mua {rec['buy']:,.1f} / bán {rec['sell']:,.1f}) trên "
              f"{rec['n_symbols']} mã (limit={a.limit}).")
        print("  → so khớp với NN ròng chính thức của phiên; nếu chỉ ~100 mã thì "
              "API đang cap limit, cần tăng --limit hoặc đổi nguồn.")
        return 0

    if a.refresh:
        c = refresh(days=a.days, limit=a.limit)
        if not c:
            print("[foreign-flow] refresh got no data (API unavailable)")
            return 1
        latest = max(c)
        print(f"[foreign-flow] cache updated ({len(c)} ngày). Mới nhất {latest}: "
              f"{c[latest]['net']:+,.1f} tỷ trên {c[latest].get('n_symbols', '?')} mã.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
