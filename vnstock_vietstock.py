"""
Vietstock corporate action scraper.

Fetches corp action events from finance.vietstock.vn/data/eventstypedata
and converts them to registry-compatible dicts for register_bulk().

Flow
----
1. GET lich-su-kien.htm?code=<TICKER> → session cookies + CSRF token
2. POST /data/eventstypedata with eventTypeID=1 (corp actions)
3. Parse /Date(ms)/ timestamps, map ChannelID → registry type,
   extract ratio/amount from Note free-text via regex
4. Return list[dict] ready for register_bulk()

ChannelID mapping (from observed Vietstock responses)
------------------------------------------------------
13  Trả cổ tức bằng tiền mặt  → cash
14  Thưởng cổ phiếu            → bonus
15  Trả cổ tức bằng cổ phiếu   → bonus
16  Phát hành thêm             → rights

CLI
---
    python vnstock_vietstock.py --ticker CDC
    python vnstock_vietstock.py --ticker CDC --register --warehouse data_warehouse
    python vnstock_vietstock.py --bulk --register --warehouse data_warehouse
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://finance.vietstock.vn"
_EVENTS_ENDPOINT = f"{BASE_URL}/data/eventstypedata"
_CSRF_PAGE = f"{BASE_URL}/lich-su-kien.htm"

_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL + "/",
    "Origin": BASE_URL,
}

_CHANNEL_TYPE: dict[int, str] = {
    13: "cash",
    14: "bonus",
    15: "bonus",
    16: "rights",
}

DEFAULT_WAREHOUSE = Path("data_warehouse")


# ── Session & CSRF ─────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_SESSION_HEADERS)
    return s


def _get_csrf_token(
    session: requests.Session,
    ticker: str,
    verbose: bool = False,
) -> str | None:
    """GET the event-history page and extract ASP.NET CSRF token.

    Visits the site root first to establish cookies, then fetches the
    event-history page. ASP.NET anti-forgery tokens are tied to the session
    cookie — a cold requests.Session() won't have one until it visits the site.
    """
    # 1. Warm up cookies by visiting the base URL
    try:
        session.get(BASE_URL, timeout=10)
    except requests.RequestException:
        pass

    # 2. Fetch the event-history page
    url = f"{_CSRF_PAGE}?page=1&tab=1&code={ticker.upper()}"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        if verbose:
            print(f"[vietstock] GET {url} failed: {exc}")
        return None

    if verbose:
        print(f"[vietstock] GET {url} → {resp.status_code}, {len(resp.text)} chars")
        snippet = resp.text[:500].replace("\n", " ")
        print(f"[vietstock] HTML snippet: {snippet}")

    # Match both quoted and unquoted HTML5 attribute values, either ordering
    for pattern in (
        # name=... value=... (quoted or unquoted)
        r'name=["\']?__RequestVerificationToken["\']?[^>]*?value=["\']?([^"\'>\s]+)',
        # value=... name=... (reversed order)
        r'value=["\']?([^"\'>\s]+)["\']?[^>]*?name=["\']?__RequestVerificationToken',
    ):
        m = re.search(pattern, resp.text)
        if m:
            return m.group(1)

    if verbose:
        # Search for any RequestVerificationToken in the HTML
        idx = resp.text.find("RequestVerificationToken")
        if idx >= 0:
            print(f"[vietstock] Token context: {resp.text[max(0,idx-50):idx+200]}")
        else:
            print("[vietstock] RequestVerificationToken not found in HTML")
    return None


# ── Date & Note parsers ────────────────────────────────────────────────────────

def _parse_ms_date(val: str | None) -> str | None:
    """'/Date(1776358800000)/' → 'YYYY-MM-DD' in Vietnam local time (UTC+7)."""
    if not val:
        return None
    m = re.search(r"/Date\((\d+)\)/", str(val))
    if not m:
        return None
    try:
        from zoneinfo import ZoneInfo
        vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        vn_tz = timezone(datetime.utcoffset(datetime.now()) or __import__("datetime").timedelta(hours=7))  # fallback
    ts = int(m.group(1)) / 1000
    return datetime.fromtimestamp(ts, tz=vn_tz).strftime("%Y-%m-%d")


def _parse_note(note: str, channel_id: int) -> dict:
    """Extract cash_amount (thousand VND) and/or ratio from Note text."""
    result: dict = {}
    if channel_id == 13:
        # "... X,XXX đồng/CP"  — cash in VND, store as thousand VND
        m = re.search(r"([\d,.]+)\s*đồng/CP", note, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            try:
                result["cash_amount"] = int(raw) / 1000
            except ValueError:
                pass
    elif channel_id in (14, 15):
        # "tỷ lệ 100:20"  → ratio = received / base
        m = re.search(r"tỷ lệ\s+(\d+)\s*:\s*(\d+)", note, re.IGNORECASE)
        if m:
            base, received = int(m.group(1)), int(m.group(2))
            if base:
                result["ratio"] = round(received / base, 6)
    elif channel_id == 16:
        # "tỷ lệ 1:1, giá 10,000 đồng/CP"
        m_ratio = re.search(r"tỷ lệ\s+(\d+)\s*:\s*(\d+)", note, re.IGNORECASE)
        m_price = re.search(r"giá\s+([\d,]+)\s*đồng/CP", note, re.IGNORECASE)
        if m_ratio:
            owns, buys = int(m_ratio.group(1)), int(m_ratio.group(2))
            if owns:
                result["ratio"] = round(buys / owns, 6)
        if m_price:
            raw = m_price.group(1).replace(",", "")
            try:
                result["cash_amount"] = int(raw) / 1000
            except ValueError:
                pass
    return result


# ── Core fetch ─────────────────────────────────────────────────────────────────

def fetch_corp_events(
    ticker: str,
    *,
    fdate: str = "",
    tdate: str = "",
    page_size: int = 50,
    max_pages: int = 10,
    session: requests.Session | None = None,
    _csrf_token: str | None = None,
    verbose: bool = False,
) -> list[dict]:
    """
    Fetch all corp action events for ticker from Vietstock.

    Returns list of dicts with keys:
      ticker, ex_date, type_, cash_amount, ratio, source, note
    ready for vnstock_corp_registry.register_bulk().
    """
    sess = session or _make_session()
    token = _csrf_token or _get_csrf_token(sess, ticker, verbose=verbose)
    if not token:
        raise RuntimeError(
            f"[vietstock] Could not obtain CSRF token for {ticker}. "
            "Vietstock may be blocking the request. "
            "Try running with --verbose to see the HTML response."
        )

    events: list[dict] = []
    for page in range(1, max_pages + 1):
        payload = {
            "eventTypeID": "1",
            "channelID": "0",
            "code": ticker.upper(),
            "catID": "",
            "fDate": fdate,
            "tDate": tdate,
            "page": str(page),
            "pageSize": str(page_size),
            "orderBy": "Date1",
            "orderDir": "DESC",
            "__RequestVerificationToken": token,
        }
        try:
            resp = sess.post(_EVENTS_ENDPOINT, data=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"[vietstock] fetch failed for {ticker}: {exc}") from exc

        # Non-JSON body = ticker not in Vietstock (empty body, HTML error page, etc.)
        body = resp.text.strip() if resp.text else ""
        if not body or body[0] != "[":
            break

        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"[vietstock] fetch failed for {ticker}: {exc}") from exc

        rows = data[0] if data and isinstance(data[0], list) else []
        total = data[2][0] if len(data) >= 3 and isinstance(data[2], list) and data[2] else 0

        for row in rows:
            channel_id = row.get("ChannelID", 0)
            event_type = _CHANNEL_TYPE.get(channel_id)
            if not event_type:
                continue

            ex_date = _parse_ms_date(row.get("GDKHQDate"))
            if not ex_date:
                continue

            note_text = row.get("Note", "") or ""
            parsed = _parse_note(note_text, channel_id)

            events.append({
                "ticker": ticker.upper(),
                "ex_date": ex_date,
                "type_": event_type,
                "cash_amount": parsed.get("cash_amount"),
                "ratio": parsed.get("ratio"),
                "source": "vietstock",
                "note": note_text[:200],
            })

        fetched_so_far = (page - 1) * page_size + len(rows)
        if len(rows) < page_size or (total and fetched_so_far >= total):
            break
        time.sleep(0.4)

    return events


def fetch_and_register(
    ticker: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    fdate: str = "",
    tdate: str = "",
    session: requests.Session | None = None,
) -> dict:
    """Fetch Vietstock events and register them. Returns {fetched, added, skipped, total}."""
    from vnstock_corp_registry import register_bulk
    events = fetch_corp_events(ticker, fdate=fdate, tdate=tdate, session=session)
    if not events:
        return {"fetched": 0, "added": 0, "skipped": 0, "total": 0}
    result = register_bulk(events, warehouse=warehouse)
    result["fetched"] = len(events)
    return result


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Vietstock corp action scraper")
    p.add_argument("--ticker", help="Single ticker (e.g. CDC)")
    p.add_argument("--bulk", action="store_true", help="Process all warehouse tickers")
    p.add_argument("--limit", type=int, default=0, help="Limit for --bulk")
    p.add_argument("--register", action="store_true",
                   help="Register fetched events into corp_actions_registry")
    p.add_argument("--warehouse", default="data_warehouse",
                   help="Path to data warehouse root")
    p.add_argument("--fdate", default="", help="From date YYYY-MM-DD")
    p.add_argument("--tdate", default="", help="To date YYYY-MM-DD")
    p.add_argument("--verbose", action="store_true", help="Print HTTP debug info")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    warehouse = Path(args.warehouse)

    if args.ticker and not args.bulk:
        if args.register:
            res = fetch_and_register(args.ticker, warehouse=warehouse,
                                     fdate=args.fdate, tdate=args.tdate)
            print(json.dumps(res, indent=2))
        else:
            events = fetch_corp_events(args.ticker, fdate=args.fdate, tdate=args.tdate,
                                       verbose=getattr(args, "verbose", False))
            for e in events:
                print(f"  {e['ex_date']}  {e['type_']:8s}  {e['note'][:80]}")
            print(f"\nTotal: {len(events)} events")
        return

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
        print(f"[vietstock] processing {len(tickers)} tickers...")
        ok = empty = fail = 0
        sess = _make_session()
        for i, t in enumerate(tickers, 1):
            try:
                if args.register:
                    res = fetch_and_register(t, warehouse=warehouse,
                                             fdate=args.fdate, tdate=args.tdate,
                                             session=sess)
                    if res["fetched"] > 0:
                        ok += 1
                    else:
                        empty += 1
                else:
                    evts = fetch_corp_events(t, fdate=args.fdate, tdate=args.tdate,
                                             session=sess)
                    (ok if evts else empty).__class__  # dummy
                    ok += bool(evts)
                    empty += not bool(evts)
            except Exception as exc:
                fail += 1
                print(f"  [{i}/{len(tickers)}] {t}: {exc}", file=__import__("sys").stderr)
            if i % 50 == 0:
                print(f"  progress: {i}/{len(tickers)} ok={ok} empty={empty} fail={fail}")
            time.sleep(0.3)
        print(f"[vietstock] done: ok={ok} empty={empty} fail={fail}")
        return

    print("Specify --ticker or --bulk", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
