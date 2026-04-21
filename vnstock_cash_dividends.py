"""
Cash dividend source — scrape CafeF for cash dividend ex-dates.

Background
----------
vnstock and vnstock_data don't expose VN cash-dividend history through
their Company API (verified via probe — only `capital_history` is
available, which covers bonus/split but not cash). To register cash
dividends in the corp action registry, we scrape a public source.

CafeF (`s.cafef.vn`) publishes per-ticker dividend history at:

    https://s.cafef.vn/Lich-su-su-kien/<TICKER>--<TICKER_TYPE>.chn

The page contains an HTML table with columns roughly:
  Ngày GDKHQ (ex-rights date) | Loại sự kiện | Tỷ lệ / Giá trị | Ghi chú

This module:
* Fetches the page (rate-limited)
* Parses cash-dividend rows (skips bonuses/splits — those come via
  capital_history with higher fidelity)
* Returns a normalised list of events ready for register_bulk()
* Writes a per-ticker cache to _meta/cash_dividends/{TICKER}.json

Best-effort design — when CafeF changes their HTML or blocks the IP,
the parser logs and returns []. The registry's confidence threshold
(cafef = 0.80) means manual overrides still win.

CLI
---
    python vnstock_cash_dividends.py --ticker CDC
    python vnstock_cash_dividends.py --ticker CDC --register
    python vnstock_cash_dividends.py --bulk --limit 50 --register
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"
CACHE_SUBDIR = "_meta/cash_dividends"
RATE_LIMIT_S = 1.5  # be polite — 1 request every 1.5s

CAFEF_URL_TEMPLATE = "https://s.cafef.vn/Lich-su-su-kien/{ticker}.chn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CashDividend:
    ticker: str
    ex_date: date
    cash_amount_vnd: float    # raw VND per share
    note: str = ""

    def to_registry_event(self) -> dict:
        """Shape for vnstock_corp_registry.register_bulk()."""
        return {
            "ticker": self.ticker,
            "ex_date": self.ex_date,
            "type_": "cash",
            "cash_amount": self.cash_amount_vnd / 1000.0,  # store in thousand VND
            "source": "cafef",
            "note": self.note,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────


_DATE_PATTERNS = [
    re.compile(r"(\d{2})/(\d{2})/(\d{4})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
]


def _parse_date_safe(s: str) -> date | None:
    if not s:
        return None
    s = s.strip()
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            try:
                if pat.pattern.startswith(r"(\d{2})"):
                    d, mo, y = m.groups()
                    return date(int(y), int(mo), int(d))
                else:
                    y, mo, d = m.groups()
                    return date(int(y), int(mo), int(d))
            except (ValueError, TypeError):
                continue
    return None


def _extract_cash_amount(text: str) -> float | None:
    """Pull a VND amount from cells like '1,200 đ/cp' or 'Tiền 8% / 1500 VND'."""
    if not text:
        return None
    text = text.replace(".", "").replace(",", "").strip()
    m = re.search(r"(\d{2,7})\s*(?:đ|d|VND|vnd)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    # Fallback — just first integer
    m = re.search(r"(\d{2,7})", text)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _is_cash_dividend_row(event_text: str) -> bool:
    """Check if a CafeF event row is a cash dividend."""
    if not event_text:
        return False
    t = event_text.lower()
    cash_markers = [
        "trả cổ tức bằng tiền", "cổ tức tiền mặt",
        "trả cổ tức tiền", "cổ tức bằng tiền",
        "cash dividend",
    ]
    skip_markers = [
        "cổ phiếu thưởng", "phát hành thêm", "chia tách",
        "bằng cổ phiếu", "stock split", "bonus", "rights",
    ]
    if any(s in t for s in skip_markers):
        return False
    return any(m in t for m in cash_markers)


_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    """Remove HTML tags + collapse whitespace, preserving Unicode."""
    if not s:
        return ""
    text = _TAG_RE.sub(" ", s)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS_RE.sub(" ", text).strip()


def parse_cafef_html(html: str, ticker: str) -> list[CashDividend]:
    """Extract cash-dividend rows from a CafeF HTML page.

    Pure-regex parser — no lxml/bs4 dependency. CafeF's table HTML is
    well-formed enough that this works reliably. Defensive: returns []
    on any parse error rather than raising.
    """
    if not html:
        return []

    events: list[CashDividend] = []
    try:
        for table_html in _TABLE_RE.findall(html):
            rows = _ROW_RE.findall(table_html)
            if not rows:
                continue
            # First row (header) heuristic — find which column is the
            # event description so we know where to look on data rows.
            header_cells = [_strip_html(c).lower()
                             for c in _CELL_RE.findall(rows[0])]
            if not header_cells:
                continue
            date_idx = next(
                (i for i, c in enumerate(header_cells)
                 if "ngày" in c or "date" in c or "gdkhq" in c),
                0,
            )
            event_idx = next(
                (i for i, c in enumerate(header_cells)
                 if "sự kiện" in c or "event" in c or "loại" in c),
                1 if len(header_cells) > 1 else 0,
            )
            value_idx = next(
                (i for i, c in enumerate(header_cells)
                 if "tỷ lệ" in c or "giá trị" in c
                    or "rate" in c or "value" in c),
                len(header_cells) - 1,
            )

            for row_html in rows[1:]:
                cells = [_strip_html(c) for c in _CELL_RE.findall(row_html)]
                if not cells or len(cells) <= max(date_idx, event_idx, value_idx):
                    continue
                event_text = cells[event_idx]
                if not _is_cash_dividend_row(event_text):
                    continue
                ex_date = _parse_date_safe(cells[date_idx])
                cash = _extract_cash_amount(cells[value_idx])
                if ex_date is None or cash is None:
                    continue
                events.append(CashDividend(
                    ticker=ticker.upper(),
                    ex_date=ex_date,
                    cash_amount_vnd=cash,
                    note=event_text[:120],
                ))
    except Exception:
        # Defensive — never let a parser bug bring down the audit pipeline
        return events
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Fetching (network + cache)
# ─────────────────────────────────────────────────────────────────────────────


_last_fetch_ts: float = 0.0


def _throttle() -> None:
    global _last_fetch_ts
    now = time.time()
    elapsed = now - _last_fetch_ts
    if elapsed < RATE_LIMIT_S:
        time.sleep(RATE_LIMIT_S - elapsed)
    _last_fetch_ts = time.time()


def _cache_path(warehouse: Path, ticker: str) -> Path:
    return Path(warehouse) / CACHE_SUBDIR / f"{ticker.upper()}.json"


def _load_cache(warehouse: Path, ticker: str) -> list[CashDividend] | None:
    path = _cache_path(warehouse, ticker)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    out: list[CashDividend] = []
    for d in data.get("events", []):
        try:
            out.append(CashDividend(
                ticker=ticker.upper(),
                ex_date=date.fromisoformat(d["ex_date"]),
                cash_amount_vnd=float(d["cash_amount_vnd"]),
                note=d.get("note", ""),
            ))
        except Exception:
            continue
    return out


def _save_cache(
    warehouse: Path, ticker: str, events: list[CashDividend],
) -> None:
    path = _cache_path(warehouse, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker.upper(),
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "events": [
            {
                "ex_date": e.ex_date.isoformat(),
                "cash_amount_vnd": e.cash_amount_vnd,
                "note": e.note,
            }
            for e in events
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def fetch_cash_dividends(
    ticker: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    use_cache: bool = True,
    timeout: int = 10,
) -> list[CashDividend]:
    """
    Fetch cash dividend history for one ticker.

    Order of attempts:
      1. Local cache (if use_cache=True)
      2. Network fetch CafeF HTML
      3. On failure, return []
    """
    if use_cache:
        cached = _load_cache(warehouse, ticker)
        if cached is not None:
            return cached

    try:
        import requests
    except ImportError:
        print("[cash_div] requests not installed", file=sys.stderr)
        return []

    _throttle()
    url = CAFEF_URL_TEMPLATE.format(ticker=ticker.upper())
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi"},
            timeout=timeout,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[cash_div] {ticker}: fetch failed — {e}", file=sys.stderr)
        return []

    events = parse_cafef_html(html, ticker)
    _save_cache(warehouse, ticker, events)
    return events


def fetch_and_register(
    ticker: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    use_cache: bool = True,
) -> dict:
    """Fetch + push into corp_actions_registry. Returns add/skip counts."""
    events = fetch_cash_dividends(
        ticker, warehouse=warehouse, use_cache=use_cache,
    )
    if not events:
        return {"ticker": ticker.upper(), "fetched": 0,
                "registered_added": 0, "registered_skipped": 0}

    try:
        from vnstock_corp_registry import register_bulk
    except ImportError:
        return {"ticker": ticker.upper(), "fetched": len(events),
                "error": "vnstock_corp_registry not available"}

    payload = [e.to_registry_event() for e in events]
    result = register_bulk(payload, warehouse=warehouse)
    return {
        "ticker": ticker.upper(),
        "fetched": len(events),
        "registered_added": result["added"],
        "registered_skipped": result["skipped"],
        "registry_total": result["total"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    ap.add_argument("--ticker", help="Single ticker")
    ap.add_argument("--bulk", action="store_true",
                    help="Fetch all stocks in warehouse")
    ap.add_argument("--limit", type=int, default=0,
                    help="With --bulk, process at most N tickers")
    ap.add_argument("--no-cache", action="store_true",
                    help="Force network fetch")
    ap.add_argument("--register", action="store_true",
                    help="Push fetched events into the corp action registry")
    args = ap.parse_args()

    warehouse = Path(args.warehouse)

    if args.ticker and not args.bulk:
        if args.register:
            result = fetch_and_register(
                args.ticker, warehouse=warehouse,
                use_cache=not args.no_cache,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            events = fetch_cash_dividends(
                args.ticker, warehouse=warehouse,
                use_cache=not args.no_cache,
            )
            for e in events:
                print(f"  {e.ex_date}  {e.cash_amount_vnd:>10,.0f} VND  "
                      f"({e.note[:80]})")
            print(f"\nTotal: {len(events)} cash dividends")
        return 0

    if args.bulk:
        from vnstock_anomaly import _is_stock
        prices = warehouse / "prices"
        tickers = sorted(
            p.name.removeprefix("ticker=")
            for p in prices.glob("ticker=*")
            if p.is_dir() and _is_stock(p.name.removeprefix("ticker="))
        )
        if args.limit:
            tickers = tickers[: args.limit]
        print(f"[cash_div] processing {len(tickers)} tickers...")
        success = empty = fail = 0
        for i, t in enumerate(tickers, 1):
            try:
                if args.register:
                    res = fetch_and_register(
                        t, warehouse=warehouse, use_cache=not args.no_cache,
                    )
                    if res["fetched"] > 0:
                        success += 1
                    else:
                        empty += 1
                else:
                    events = fetch_cash_dividends(
                        t, warehouse=warehouse, use_cache=not args.no_cache,
                    )
                    if events:
                        success += 1
                    else:
                        empty += 1
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(tickers)}] {t}: {e}", file=sys.stderr)
            if i % 50 == 0:
                print(f"  progress: {i}/{len(tickers)} "
                      f"(ok={success} empty={empty} fail={fail})")
        print(f"[cash_div] done: ok={success} empty={empty} fail={fail}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(_main())


__all__ = [
    "CashDividend",
    "fetch_and_register",
    "fetch_cash_dividends",
    "parse_cafef_html",
]
