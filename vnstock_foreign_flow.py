#!/usr/bin/env python3
"""Full-market foreign net flow (NN ròng) — daily, ALL symbols, CLI/pipeline-safe.

Why this module exists
----------------------
The dashboard once fetched only the TOP-100 foreign buy/sell symbols, and that
cache was the ONLY source ``vnstock_regime._load_nn_net_1d`` read for the
brief's "NN ròng 1D" sentiment signal. Two consequences (observed 12/06):

* the top-100 sum OVERSTATES net selling — it misses the long tail of small-cap
  net buyers and drops the buy offset for symbols that appear only on the sell
  side (e.g. it reported -665 tỷ vs the real market -491 tỷ); and
* that cache is refreshed ONLY when the Streamlit Money-Flow tab is opened, and
  ``_load_nn_net_1d`` read it ignoring age → the brief showed a FROZEN value
  labelled "phiên hôm nay" (the same -665 appeared for both 11/06 and 12/06).

This module reads the FULL board for each trading day, sums the market-total
net, caches it PER DATE, and exposes a freshness-aware loader so the brief uses
the right session's value — or omits it, never a stale one.

Nguồn (vnstock thế hệ 6): ``foreign_net_for_date(day)`` = MỘT lượt
``Market().equity.screener(date=day)`` — bảng cả thị trường, mỗi mã một dòng
``foreign_net_value`` (đồng) / ``foreign_net_volume``. Hàm này DÙNG CHUNG cho
runner (NN ròng theo ngành) và dashboard (tab Dòng tiền). Kiểm trên máy có khoá
nguồn:

    python vnstock_foreign_flow.py --diag 2026-06-12

in net + số mã có giao dịch NN (cả sàn là vài trăm mã, không phải 100). Refresh
cache theo ngày cho pipeline:

    python vnstock_foreign_flow.py --refresh --days 5
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date, timedelta as _td
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "foreign_net_daily.json"

FOREIGN_NET_COLS = ["symbol", "foreign_net_value", "foreign_net_volume"]


def foreign_net_for_date(day: str) -> pd.DataFrame:
    """NN ròng TỪNG MÃ của phiên ``day`` (ISO) trên cả thị trường.

    Cột ``symbol`` (in hoa), ``foreign_net_value`` (đồng), ``foreign_net_volume`` (cp);
    bảng rỗng khi nguồn không có phiên đó. Lỗi của vnstock (chưa khai nguồn, hạn mức,
    mạng…) ném NGUYÊN VẸN — chỗ gọi quyết định giữ cache cũ.
    """
    from vnstock import Market
    from vnstock_auth import ensure_api_key

    ensure_api_key()
    df = Market().equity.screener(date=day)
    if df is None or df.empty or "symbol" not in df.columns:
        return pd.DataFrame(columns=FOREIGN_NET_COLS)
    out = df.reindex(columns=FOREIGN_NET_COLS).copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    for c in ("foreign_net_value", "foreign_net_volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[out["symbol"] != ""].reset_index(drop=True)


def fetch_market_net(date_str: str) -> dict | None:
    """FULL-market foreign net for one trading day.

    Returns ``{date, net, buy, sell, n_symbols}`` in tỷ VND, or None when the
    source is unavailable / returns nothing. ``buy`` = Σ NN ròng của mã mua ròng,
    ``sell`` = Σ |NN ròng| của mã bán ròng, ``net = buy − sell``; ``n_symbols`` =
    số mã có NN ròng khác 0.
    """
    from vnstock.errors import VnstockError

    try:
        df = foreign_net_for_date(date_str)
    except VnstockError as e:
        print(f"[foreign-flow] {date_str}: {type(e).__name__} {getattr(e, 'code', '')} — {e}",
              file=sys.stderr)
        return None
    net = df["foreign_net_value"].dropna()
    net = net[net != 0]
    if net.empty:
        return None
    buy = float(net[net > 0].sum())
    sell = float(-net[net < 0].sum())
    return {
        "date": date_str,
        "net": round((buy - sell) / 1e9, 1),
        "buy": round(buy / 1e9, 1),
        "sell": round(sell / 1e9, 1),
        "n_symbols": int(len(net)),
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


def refresh(days: int = 5) -> dict:
    """Fetch the last ``days`` trading days (skipping weekends) and merge into
    the per-date cache. Returns the updated cache (possibly unchanged when the
    source is unavailable — a failed day keeps its cached value)."""
    cache = _load_cache()
    today = _date.today()
    fetched, cal = 0, 0
    while fetched < days and cal < days * 2 + 4:
        dt = today - _td(days=cal)
        cal += 1
        if dt.weekday() >= 5:        # skip Sat/Sun
            continue
        rec = fetch_market_net(dt.isoformat())
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
    ap.add_argument("--diag", metavar="YYYY-MM-DD",
                    help="Fetch ONE day live and print the full breakdown (verify vs official)")
    a = ap.parse_args(argv)

    if a.diag:
        rec = fetch_market_net(a.diag)
        if not rec:
            print(f"[foreign-flow] no data for {a.diag} (nguồn lỗi hoặc rỗng)")
            return 1
        print(f"[foreign-flow] {rec['date']}: NN ròng = {rec['net']:+,.1f} tỷ "
              f"(mua ròng {rec['buy']:,.1f} / bán ròng {rec['sell']:,.1f}) trên "
              f"{rec['n_symbols']} mã.")
        print("  → so khớp với NN ròng chính thức của phiên; chỉ ~100 mã ⇒ nguồn trả "
              "thiếu bảng, kiểm VNSTOCK_SOURCE_ROUTES cho market.equity.screener.")
        return 0

    if a.refresh:
        c = refresh(days=a.days)
        if not c:
            print("[foreign-flow] refresh got no data (nguồn lỗi)")
            return 1
        latest = max(c)
        print(f"[foreign-flow] cache updated ({len(c)} ngày). Mới nhất {latest}: "
              f"{c[latest]['net']:+,.1f} tỷ trên {c[latest].get('n_symbols', '?')} mã.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
