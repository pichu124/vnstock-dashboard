"""
Corp-action events layer — fetch & cache per-ticker corporate actions.

Events (cash dividends, splits, bonus issues) are fetched per ticker from
vnstock (`Company().dividends()` / `Company().events()`) and cached to
`data_warehouse/_meta/corp_actions/{TICKER}.parquet`. If the fetch fails
or vnstock lacks the endpoint, the ticker is silently skipped.

Consumers: vnstock_events (upcoming-events brief block), vnstock_anomaly
(corp-action-aware anomaly suppression), vnstock_corp_registry.

Data contract
-------------
The cached events parquet has the schema:

    ticker: str
    ex_date: date
    type: "cash" | "stock" | "split" | "bonus"
    cash_amount: float (VND, nullable)
    ratio: float (nullable)  # e.g. 10:1 split → ratio=10
    raw: str (original description, for debugging)

Public API
----------
    load_events(ticker, meta_dir) -> DataFrame
        Read cached corp-action events (empty DF if cache miss).

    refresh_events(ticker) -> DataFrame
        Fetch from vnstock and write cache. Best-effort only.

(A back-adjusted-price layer — apply_adjustments()/close_adj — used to live
here but was never wired into production; see git history if needed.)

This module is **read-only** with respect to the raw OHLCV warehouse.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
CORP_ACTIONS_SUBDIR = "_meta/corp_actions"

EVENT_SCHEMA_COLS = ["ticker", "ex_date", "type", "cash_amount", "ratio", "raw"]


# ─────────────────────────────────────────────────────────────────────────────
# Loading / caching
# ─────────────────────────────────────────────────────────────────────────────


def _events_path(ticker: str, warehouse: Path) -> Path:
    return warehouse / CORP_ACTIONS_SUBDIR / f"{ticker}.parquet"


def load_events(ticker: str, warehouse: Path = DEFAULT_WAREHOUSE) -> pd.DataFrame:
    """Read cached corp-action events. Returns an empty DF on miss."""
    path = _events_path(ticker, warehouse)
    if not path.exists():
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    if df.empty:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)
    df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
    return df


def refresh_events(
    ticker: str,
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    verbose: bool = False,
) -> pd.DataFrame:
    """Best-effort fetch of corp-action events from vnstock and cache to parquet."""
    events = _fetch_events(ticker, verbose=verbose)
    if events.empty:
        return events
    path = _events_path(ticker, warehouse)
    path.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(path, index=False)
    return events


def _fetch_events(ticker: str, *, verbose: bool = False) -> pd.DataFrame:
    """Query vnstock for corp actions. Returns empty DF on any failure.

    Tries sources in order until one yields data:
      1. vnstock_data.Company (Golden tier — richest history)
      2. vnstock Vnstock(source="TCBS").stock.company
      3. vnstock Vnstock(source="VCI").stock.company
    """
    rows: list[dict] = []

    for source_name, resolve in _company_sources():
        try:
            company = resolve(ticker)
        except Exception as e:
            if verbose:
                print(f"  [{ticker}] {source_name}: resolve failed — {e}")
            continue
        if company is None:
            continue
        dividends = _extract_dividends(company, ticker)
        events = _extract_events(company, ticker)
        capital = _extract_capital_history_as_events(company, ticker)
        rows.extend(dividends)
        rows.extend(events)
        rows.extend(capital)
        if rows:
            if verbose:
                print(f"  [{ticker}] {source_name}: "
                      f"{len(dividends)} div, {len(events)} event, "
                      f"{len(capital)} capital-change")
            break
        elif verbose:
            print(f"  [{ticker}] {source_name}: no data")

    if not rows:
        return pd.DataFrame(columns=EVENT_SCHEMA_COLS)

    df = pd.DataFrame(rows)
    for col in EVENT_SCHEMA_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[EVENT_SCHEMA_COLS]
    df["ex_date"] = pd.to_datetime(df["ex_date"], errors="coerce").dt.date
    df = df.dropna(subset=["ex_date", "ticker"])
    df = df.drop_duplicates(subset=["ticker", "ex_date", "type"], keep="last")
    return df.sort_values("ex_date").reset_index(drop=True)


def _company_sources():
    """Yield (name, resolver) pairs. Resolver: str -> company-like object.

    Modern vnstock (>=3.5) dropped TCBS support; supported sources are
    VCI, KBS, MSN, FMP. We try those plus vnstock_data's native ``Company``.
    """

    def via_vnstock_data(ticker: str):
        from vnstock_data import Company
        try:
            from vnstock_auth import ensure_api_key
            ensure_api_key()
        except Exception:
            pass
        return Company(symbol=ticker)

    def via_vnstock_vci(ticker: str):
        from vnstock_auth import get_vnstock
        return get_vnstock(ticker, "VCI").company

    def via_vnstock_kbs(ticker: str):
        from vnstock_auth import get_vnstock
        return get_vnstock(ticker, "KBS").company

    yield "vnstock_data.Company", via_vnstock_data
    yield "vnstock:VCI", via_vnstock_vci
    yield "vnstock:KBS", via_vnstock_kbs


_DIVIDEND_METHOD_NAMES = (
    "dividends",
    "dividend",
    "dividend_history",
    "cash_dividend",
    "cash_dividend_history",
    "corporate_action_dividends",
)


def _call_first_working(obj, method_names):
    """Call the first attribute/method on ``obj`` that returns a non-empty DataFrame."""
    for name in method_names:
        try:
            attr = getattr(obj, name)
        except AttributeError:
            continue
        try:
            val = attr() if callable(attr) else attr
        except Exception:
            continue
        if val is None:
            continue
        try:
            if hasattr(val, "empty") and val.empty:
                continue
        except Exception:
            pass
        return name, val
    return None, None


def _extract_dividends(company, ticker: str) -> list[dict]:
    name, div = _call_first_working(company, _DIVIDEND_METHOD_NAMES)
    if div is None:
        return []
    div = div.copy()
    div.columns = [c.lower() for c in div.columns]
    out: list[dict] = []
    for _, r in div.iterrows():
        ex = (r.get("exercise_date") or r.get("ex_date")
              or r.get("ex_rights_date") or r.get("record_date"))
        cash = (r.get("cash_dividend") or r.get("cash_value")
                or r.get("value") or r.get("amount")
                or r.get("dividend_value"))
        try:
            cash_val = float(cash) if cash not in (None, "") else None
        except (TypeError, ValueError):
            cash_val = None
        if ex is None or cash_val is None:
            continue
        out.append({
            "ticker": ticker,
            "ex_date": ex,
            "type": "cash",
            "cash_amount": cash_val,
            "ratio": None,
            "raw": str(r.to_dict()),
        })
    return out


_EVENT_METHOD_NAMES = (
    "events",
    "event_history",
    "corporate_events",
    "corp_events",
    "company_events",
    "events_schedule",
    "capital_history",          # vnstock_data.Company exposes this — likely
                                # contains splits/bonuses/capital increases.
)


def _extract_events(company, ticker: str) -> list[dict]:
    name, evt = _call_first_working(company, _EVENT_METHOD_NAMES)
    if evt is None:
        return []
    evt = evt.copy()
    evt.columns = [c.lower() for c in evt.columns]
    out: list[dict] = []
    for _, r in evt.iterrows():
        ex = r.get("ex_date") or r.get("exercise_date") or r.get("ex_rights_date")
        label = str(r.get("event_name") or r.get("title")
                    or r.get("event") or "").lower()
        if "split" in label or "chia tách" in label or "tách cổ phiếu" in label:
            ratio = (r.get("ratio") or r.get("split_ratio")
                     or r.get("exercise_ratio"))
            try:
                ratio_val = float(ratio) if ratio else None
            except (TypeError, ValueError):
                ratio_val = None
            if ex is None or ratio_val is None:
                continue
            out.append({
                "ticker": ticker, "ex_date": ex, "type": "split",
                "cash_amount": None, "ratio": ratio_val,
                "raw": str(r.to_dict()),
            })
        elif "bonus" in label or "thưởng" in label or "stock dividend" in label:
            ratio = r.get("ratio") or r.get("exercise_ratio")
            try:
                ratio_val = float(ratio) if ratio else None
            except (TypeError, ValueError):
                ratio_val = None
            if ex is None or ratio_val is None:
                continue
            out.append({
                "ticker": ticker, "ex_date": ex, "type": "bonus",
                "cash_amount": None, "ratio": ratio_val,
                "raw": str(r.to_dict()),
            })
    return out


def _extract_capital_history_as_events(company, ticker: str) -> list[dict]:
    """Derive bonus-like events from ``company.capital_history()``.

    Charter-capital changes don't tell us the exact event type (bonus
    issue vs rights offer vs private placement), but EVERY such change
    is a legitimate reason for the market price to move on / around the
    event date. That's enough for the anomaly scanner to suppress false
    positives on band / ohlc breaches.

    We do NOT emit cash events — capital_history doesn't capture cash
    dividends (those come out of retained earnings, not capital).

    Returns event rows with ``type="bonus"`` so they go through the
    existing skip-band-and-ohlc path in scan_ticker.
    """
    try:
        df = company.capital_history()
    except Exception:
        return []
    if df is None:
        return []
    try:
        if df.empty:
            return []
    except Exception:
        return []

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "date" not in df.columns or "charter_capital" not in df.columns:
        return []

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["charter_capital"] = pd.to_numeric(df["charter_capital"], errors="coerce")
    df = df.dropna(subset=["date", "charter_capital"]).sort_values("date")

    out: list[dict] = []
    prev_cap: float | None = None
    for _, r in df.iterrows():
        cap = float(r["charter_capital"])
        if cap <= 0:
            continue
        if prev_cap is not None and prev_cap > 0:
            ratio = cap / prev_cap
            # Only emit if capital grew by >2% — filters floating-point noise
            # and tiny ESOP issuances that don't meaningfully move the price.
            if ratio > 1.02:
                out.append({
                    "ticker": ticker,
                    "ex_date": r["date"],
                    "type": "bonus",
                    "cash_amount": None,
                    "ratio": round(ratio, 4),
                    "raw": str(r.to_dict()),
                })
        prev_cap = cap
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic probe — for debugging API changes
# ─────────────────────────────────────────────────────────────────────────────


def probe_company(ticker: str) -> dict:
    """Introspect what each data source exposes for ``ticker``.

    Returns a dict with source name → method/attr lists + sample data.
    Useful when the vnstock API changes and _extract_* stop matching.

    CLI: ``python vnstock_adjust.py --probe VCB``
    """
    out: dict = {"ticker": ticker, "sources": {}}
    for source_name, resolve in _company_sources():
        info: dict = {"resolved": False, "error": None,
                      "methods": [], "attrs": [], "samples": {}}
        try:
            company = resolve(ticker)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            out["sources"][source_name] = info
            continue
        if company is None:
            info["error"] = "resolver returned None"
            out["sources"][source_name] = info
            continue

        info["resolved"] = True
        for attr_name in sorted(dir(company)):
            if attr_name.startswith("_"):
                continue
            try:
                val = getattr(company, attr_name)
            except Exception:
                continue
            if callable(val):
                info["methods"].append(attr_name)
            else:
                info["attrs"].append(attr_name)

        # Probe every public method — not just our guesses. For each, try
        # calling with no args, then with common (start, end) date range args.
        # This catches methods that require parameters (like KBS dividends).
        for candidate in info["methods"]:
            sample_key = candidate
            attempts = [
                ("()", lambda a=getattr(company, candidate): a()),
                ("(start, end)",
                 lambda a=getattr(company, candidate):
                 a(start="2020-01-01", end="2026-12-31")),
            ]
            for label, call in attempts:
                try:
                    val = call()
                except Exception as e:
                    info["samples"][f"{sample_key}{label}"] = \
                        f"<error: {type(e).__name__}: {str(e)[:60]}>"
                    continue
                if val is None:
                    info["samples"][f"{sample_key}{label}"] = "<None>"
                elif hasattr(val, "empty") and val.empty:
                    info["samples"][f"{sample_key}{label}"] = "<empty DataFrame>"
                elif hasattr(val, "columns"):
                    info["samples"][f"{sample_key}{label}"] = {
                        "shape": list(val.shape),
                        "columns": list(val.columns),
                        "head": val.head(2).to_dict(orient="records"),
                    }
                    break  # stop trying variants once we got data
                else:
                    info["samples"][f"{sample_key}{label}"] = \
                        f"<{type(val).__name__}>"
                    break
        out["sources"][source_name] = info
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Core adjustment
# ─────────────────────────────────────────────────────────────────────────────






# ─────────────────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────────────────




__all__ = [
    "EVENT_SCHEMA_COLS",
    "load_events",
    "probe_company",
    "refresh_events",
]


def _main():
    import argparse
    import json as _json
    import sys as _sys

    # Force UTF-8 on stdout (Windows console defaults to cp1252 which can't
    # encode Vietnamese characters in probe output)
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Corporate-action probe/refresh")
    ap.add_argument("--probe", metavar="TICKER",
                    help="Introspect what corp-action methods a ticker exposes")
    ap.add_argument("--refresh", metavar="TICKER",
                    help="Fetch and cache corp-action events for a ticker")
    ap.add_argument("--out", metavar="PATH",
                    help="Write probe output to this file (UTF-8) instead of stdout")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.probe:
        info = probe_company(args.probe)
        text = _json.dumps(info, indent=2, default=str, ensure_ascii=False)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"[probe] wrote {args.out} ({len(text):,} chars)")
        else:
            print(text)
    elif args.refresh:
        ev = refresh_events(args.refresh, verbose=args.verbose)
        print(f"[refresh] {args.refresh}: {len(ev)} event(s)")
        if not ev.empty:
            print(ev.head(10).to_string(index=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
