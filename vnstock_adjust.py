"""
Adjusted price layer.

vnstock's Quote API returns **un-adjusted** OHLCV. For back-testing, factor
exposure, and signal research we need prices that are continuous across
corporate actions (dividends, splits, bonus issues). This module derives a
back-adjusted close column (`close_adj`) without mutating the raw warehouse
columns.

Approach
--------
1. Corp-action events are fetched per ticker from vnstock
   (`Company().dividends()` / `Company().events()`) and cached to
   `data_warehouse/_meta/corp_actions/{TICKER}.parquet`. If the fetch fails
   or vnstock lacks the endpoint, the ticker is silently skipped — the
   adjusted column simply equals the raw column.
2. For each event (cash dividend D on ex-date T), an **adjustment factor**
   is computed:

       factor = (close_before_ex - D) / close_before_ex

   where `close_before_ex` is the close of the last trading session before T.
   Stock splits (ratio r) give `factor = 1 / r`.
3. The **cumulative product of factors for all events at or after t** is
   applied to the close at time t. Result: `close_adj(t) = close(t) *
   cum_factor(t)`. This preserves the most recent close as authoritative and
   rescales history backwards — the standard Yahoo / Bloomberg convention.

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
    apply_adjustments(ohlcv_df, events_df) -> DataFrame
        Adds / overwrites `close_adj`, `open_adj`, `high_adj`, `low_adj`.

    load_events(ticker, meta_dir) -> DataFrame
        Read cached corp-action events (empty DF if cache miss).

    refresh_events(ticker) -> DataFrame
        Fetch from vnstock and write cache. Best-effort only.

This module is **read-only** with respect to the raw OHLCV warehouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

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
        rows.extend(dividends)
        rows.extend(events)
        if rows:
            if verbose:
                print(f"  [{ticker}] {source_name}: "
                      f"{len(dividends)} div, {len(events)} event")
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
        from vnstock import Vnstock
        return Vnstock().stock(symbol=ticker, source="VCI").company

    def via_vnstock_kbs(ticker: str):
        from vnstock import Vnstock
        return Vnstock().stock(symbol=ticker, source="KBS").company

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

        # Probe likely candidates + sample columns/shape
        for candidate in (_DIVIDEND_METHOD_NAMES + _EVENT_METHOD_NAMES):
            try:
                attr = getattr(company, candidate)
            except AttributeError:
                continue
            try:
                val = attr() if callable(attr) else attr
            except Exception as e:
                info["samples"][candidate] = f"<error: {type(e).__name__}>"
                continue
            if val is None:
                info["samples"][candidate] = "<None>"
            elif hasattr(val, "empty") and val.empty:
                info["samples"][candidate] = "<empty DataFrame>"
            elif hasattr(val, "columns"):
                info["samples"][candidate] = {
                    "shape": list(val.shape),
                    "columns": list(val.columns),
                    "head": val.head(2).to_dict(orient="records"),
                }
            else:
                info["samples"][candidate] = f"<{type(val).__name__}>"
        out["sources"][source_name] = info
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Core adjustment
# ─────────────────────────────────────────────────────────────────────────────


def _per_event_factor(event: dict, close_before_ex: float) -> float:
    """Compute the adjustment factor for one corporate event."""
    etype = str(event.get("type", "")).lower()
    if etype == "cash":
        cash = float(event.get("cash_amount") or 0)
        if close_before_ex <= 0 or cash <= 0:
            return 1.0
        return max(0.0, (close_before_ex - cash) / close_before_ex)
    if etype == "split":
        ratio = float(event.get("ratio") or 0)
        if ratio <= 0:
            return 1.0
        return 1.0 / ratio
    if etype == "bonus":
        ratio = float(event.get("ratio") or 0)
        # Vietnamese bonus issues: ratio is often expressed as "10:1" meaning
        # 1 new share per 10 held. We model that as price scaling by 10/(10+1).
        if ratio <= 0:
            return 1.0
        return ratio / (ratio + 1.0)
    return 1.0


def apply_adjustments(
    ohlcv: pd.DataFrame,
    events: pd.DataFrame | None,
    *,
    price_cols: Iterable[str] = ("open", "high", "low", "close"),
) -> pd.DataFrame:
    """
    Add back-adjusted columns (e.g. ``close_adj``) to an OHLCV DataFrame.

    Parameters
    ----------
    ohlcv : DataFrame with 'time' (date) and the listed price columns.
    events : DataFrame from ``load_events`` or None.

    Returns
    -------
    DataFrame with added ``*_adj`` columns. Raw columns are untouched.
    When ``events`` is empty/None the adjusted columns equal the raw columns.
    """
    if ohlcv is None or ohlcv.empty:
        return ohlcv

    result = ohlcv.copy()
    result["time"] = pd.to_datetime(result["time"])
    result = result.sort_values("time").reset_index(drop=True)

    # Initialise adj columns as copies — the no-op default.
    for col in price_cols:
        if col in result.columns:
            result[f"{col}_adj"] = result[col].astype(float)

    if events is None or events.empty:
        return result

    events = events.copy()
    events["ex_date"] = pd.to_datetime(events["ex_date"])
    events = events.sort_values("ex_date")
    # Keep only events within the series range (±1 day slack)
    events = events[
        (events["ex_date"] >= result["time"].min())
        & (events["ex_date"] <= result["time"].max())
    ]
    if events.empty:
        return result

    # cum_factor[i] = product of per-event factors for all events strictly
    # after time[i]. close_adj[i] = close[i] * cum_factor[i].
    cum_factor = pd.Series(1.0, index=result.index)

    for _, ev in events.iterrows():
        ex_date = ev["ex_date"]
        # Last trading session strictly before ex_date
        before_mask = result["time"] < ex_date
        if not before_mask.any():
            continue
        close_before = float(result.loc[before_mask, "close"].iloc[-1])
        if close_before <= 0:
            continue
        f = _per_event_factor(ev.to_dict(), close_before)
        if f == 1.0:
            continue
        # apply to every row strictly before ex_date (back-adjust history)
        cum_factor.loc[before_mask] *= f

    for col in price_cols:
        adj_col = f"{col}_adj"
        if adj_col in result.columns:
            result[adj_col] = (result[col].astype(float) * cum_factor).astype("float32")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────────────────


def with_adjusted_prices(
    ohlcv: pd.DataFrame,
    ticker: str,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> pd.DataFrame:
    """Shortcut: load events for ``ticker`` from cache and apply adjustments."""
    events = load_events(ticker, warehouse)
    return apply_adjustments(ohlcv, events)


__all__ = [
    "EVENT_SCHEMA_COLS",
    "apply_adjustments",
    "load_events",
    "probe_company",
    "refresh_events",
    "with_adjusted_prices",
]


def _main():
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description="Corporate-action probe/refresh")
    ap.add_argument("--probe", metavar="TICKER",
                    help="Introspect what corp-action methods a ticker exposes")
    ap.add_argument("--refresh", metavar="TICKER",
                    help="Fetch and cache corp-action events for a ticker")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.probe:
        info = probe_company(args.probe)
        print(_json.dumps(info, indent=2, default=str, ensure_ascii=False))
    elif args.refresh:
        ev = refresh_events(args.refresh, verbose=args.verbose)
        print(f"[refresh] {args.refresh}: {len(ev)} event(s)")
        if not ev.empty:
            print(ev.head(10).to_string(index=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
