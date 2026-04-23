"""
vnstock_wss_backfill.py — Repair _live rolled bars from API when WSS capture
was partial.

Why
---
When the WSS realtime feed misses a large fraction of a session's trades
(< 50 % of API volume), the aggregated rolled_close is a random intraday
tick rather than the closing print. The reconciler labels the row
``wss_partial_miss`` — visible but not a fail. That keeps the audit
clean, but the underlying minute bars in ``_live/bars_{date}.parquet``
are still wrong, which leaks into any dashboard or downstream job that
reads them.

This module overwrites those ticker-day bars with one synthetic bar
whose OHLCV equals the authoritative API daily row. After aggregation
the rolled daily matches the API exactly, so subsequent reconciles see
``ok`` rows and realtime views stop showing stale intraday ticks.

Not a root-cause fix for the WSS capture gap — that's tầng 3 (persistent
state, catch-up on restart). This is the defense-in-depth belt that
guarantees data consistency regardless of WSS health.

Public API
----------
* ``extract_partial_miss(report)`` — pull (ticker, date) pairs from a
  ReconciliationReport
* ``backfill_rolled_bars(warehouse, pairs)`` — rewrite _live parquet,
  returns {"fixed": n, "skipped": n, "no_api_row": n}
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as _date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


LIVE_SUBDIR = "_live"
PRICES_SUBDIR = "prices"

# Synthetic bar is written at 14:45 ICT — the Vietnam ATC close print time.
# Any minute the aggregator groups into the daily slot works; 14:45 makes
# the resulting file inspectable / plausibly-ordered.
_SYNTH_BAR_TIME = pd.Timedelta(hours=14, minutes=45)


def extract_partial_miss(report) -> list[tuple[str, _date]]:
    """Return [(ticker, date), ...] for every wss_partial_miss discrepancy."""
    out: list[tuple[str, _date]] = []
    for d in report.discrepancies:
        if not getattr(d, "reason", "") or "wss_partial_miss" not in d.reason:
            continue
        try:
            target = pd.to_datetime(d.trading_date).date()
        except Exception:
            continue
        out.append((d.ticker, target))
    return out


def _load_api_full_row(
    warehouse: Path, ticker: str, d: _date
) -> dict | None:
    """Read the authoritative OHLCV row for (ticker, date) from prices/."""
    year_dir = warehouse / PRICES_SUBDIR / f"ticker={ticker}" / f"year={d.year}"
    if not year_dir.exists():
        return None
    for pq_file in year_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(pq_file)
        except Exception:
            continue
        if df.empty or "time" not in df.columns:
            continue
        df["time"] = pd.to_datetime(df["time"]).dt.date
        row = df[df["time"] == d]
        if row.empty:
            continue
        r = row.iloc[0]
        close_val = float(r["close"])
        return {
            "open": float(r.get("open", close_val)),
            "high": float(r.get("high", close_val)),
            "low": float(r.get("low", close_val)),
            "close": close_val,
            "volume": int(r.get("volume", 0)),
        }
    return None


def backfill_rolled_bars(
    warehouse: Path,
    partial_miss: list[tuple[str, _date]],
) -> dict:
    """Rewrite ``_live/bars_{date}.parquet`` for each partial-miss pair.

    Drops any existing bars for the target ticker on the target date,
    then appends one synthetic bar with API-authoritative OHLCV. Tickers
    with no API row yet (e.g. if EOD sync hasn't run) are skipped.
    """
    by_date: dict[_date, list[str]] = defaultdict(list)
    for ticker, d in partial_miss:
        by_date[d].append(ticker)

    fixed = skipped = no_api = 0

    for d, tickers in by_date.items():
        live_path = warehouse / LIVE_SUBDIR / f"bars_{d.isoformat()}.parquet"
        if live_path.exists():
            try:
                df = pd.read_parquet(live_path)
            except Exception:
                df = pd.DataFrame()
        else:
            live_path.parent.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame()

        if not df.empty and "ticker" in df.columns:
            df = df[~df["ticker"].isin(tickers)].reset_index(drop=True)

        synth_rows: list[dict] = []
        for ticker in tickers:
            api_row = _load_api_full_row(warehouse, ticker, d)
            if api_row is None:
                no_api += 1
                continue
            synth_rows.append({
                "time": pd.Timestamp(d) + _SYNTH_BAR_TIME,
                "ticker": ticker,
                **api_row,
            })

        if not synth_rows:
            skipped += len(tickers) - no_api
            continue

        synth_df = pd.DataFrame(synth_rows)
        merged = (
            pd.concat([df, synth_df], ignore_index=True)
            if not df.empty else synth_df
        )
        table = pa.Table.from_pandas(merged, preserve_index=False)
        pq.write_table(table, live_path, compression="snappy")
        fixed += len(synth_rows)

    return {"fixed": fixed, "skipped": skipped, "no_api_row": no_api}
