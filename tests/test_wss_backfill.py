"""Tests for vnstock_wss_backfill — _live bar repair from API."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from vnstock_wss_backfill import (
    backfill_rolled_bars,
    extract_partial_miss,
)


class _FakeDiscrepancy:
    def __init__(self, ticker, trading_date, reason):
        self.ticker = ticker
        self.trading_date = trading_date
        self.reason = reason


class _FakeReport:
    def __init__(self, discrepancies):
        self.discrepancies = discrepancies


def _write_api_row(warehouse: Path, ticker: str, d: date, **fields):
    year_dir = warehouse / "prices" / f"ticker={ticker}" / f"year={d.year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    defaults = {"open": 10.0, "high": 11.0, "low": 9.5,
                "close": 10.5, "volume": 100_000}
    defaults.update(fields)
    df = pd.DataFrame([{"time": pd.Timestamp(d), **defaults}])
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")


def _write_live_bars(warehouse: Path, d: date, rows: list[dict]):
    live_dir = warehouse / "_live"
    live_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   live_dir / f"bars_{d.isoformat()}.parquet")


def _read_live_bars(warehouse: Path, d: date) -> pd.DataFrame:
    return pd.read_parquet(warehouse / "_live" / f"bars_{d.isoformat()}.parquet")


# ── extract_partial_miss ───────────────────────────────────────────────────


def test_extract_partial_miss_picks_matching_reason():
    r = _FakeReport([
        _FakeDiscrepancy("PNJ", "2026-04-20", "wss_partial_miss (4% vol captured)"),
        _FakeDiscrepancy("VCB", "2026-04-20", "close drift 5.00%"),  # ignored
        _FakeDiscrepancy("BMP", "2026-04-20", "wss_partial_miss (2% vol captured)"),
    ])
    pairs = extract_partial_miss(r)
    assert pairs == [("PNJ", date(2026, 4, 20)), ("BMP", date(2026, 4, 20))]


def test_extract_partial_miss_ignores_bad_date():
    r = _FakeReport([
        _FakeDiscrepancy("X", "not-a-date", "wss_partial_miss (1%)"),
    ])
    assert extract_partial_miss(r) == []


# ── backfill_rolled_bars ──────────────────────────────────────────────────


def test_backfill_replaces_partial_miss_ticker_bars(tmp_path: Path):
    d = date(2026, 4, 20)
    _write_api_row(tmp_path, "PNJ", d, close=76.67, volume=1_870_506,
                   open=75.0, high=78.0, low=74.5)

    # WSS captured only a few early-morning ticks for PNJ + a full day for VCB
    _write_live_bars(tmp_path, d, [
        {"time": pd.Timestamp("2026-04-20 09:15"), "ticker": "PNJ",
         "open": 112.5, "high": 112.5, "low": 112.5, "close": 112.5, "volume": 83_284},
        {"time": pd.Timestamp("2026-04-20 10:30"), "ticker": "VCB",
         "open": 77.0, "high": 77.5, "low": 76.8, "close": 77.2, "volume": 500_000},
    ])

    result = backfill_rolled_bars(tmp_path, [("PNJ", d)])
    assert result == {"fixed": 1, "skipped": 0, "no_api_row": 0}

    bars = _read_live_bars(tmp_path, d)
    pnj = bars[bars["ticker"] == "PNJ"]
    assert len(pnj) == 1, "partial-miss ticker should have exactly 1 synthetic bar"
    assert float(pnj.iloc[0]["close"]) == 76.67
    assert int(pnj.iloc[0]["volume"]) == 1_870_506
    # Unrelated ticker untouched
    vcb = bars[bars["ticker"] == "VCB"]
    assert len(vcb) == 1
    assert float(vcb.iloc[0]["close"]) == 77.2


def test_backfill_creates_live_file_when_none_exists(tmp_path: Path):
    d = date(2026, 4, 20)
    _write_api_row(tmp_path, "PNJ", d, close=76.67, volume=1_870_506)

    # No _live/bars_*.parquet yet — backfill should create it
    result = backfill_rolled_bars(tmp_path, [("PNJ", d)])
    assert result["fixed"] == 1

    bars = _read_live_bars(tmp_path, d)
    assert len(bars) == 1
    assert bars.iloc[0]["ticker"] == "PNJ"


def test_backfill_skips_when_no_api_row(tmp_path: Path):
    d = date(2026, 4, 20)
    # No api row written for MISSING
    result = backfill_rolled_bars(tmp_path, [("MISSING", d)])
    assert result == {"fixed": 0, "skipped": 0, "no_api_row": 1}


def test_backfill_is_idempotent(tmp_path: Path):
    d = date(2026, 4, 20)
    _write_api_row(tmp_path, "PNJ", d, close=76.67, volume=1_870_506)

    backfill_rolled_bars(tmp_path, [("PNJ", d)])
    backfill_rolled_bars(tmp_path, [("PNJ", d)])

    bars = _read_live_bars(tmp_path, d)
    pnj = bars[bars["ticker"] == "PNJ"]
    assert len(pnj) == 1, "repeat backfill must not duplicate the synthetic bar"


def test_backfill_aggregates_to_api_close_via_rollup(tmp_path: Path):
    """End-to-end: after backfill, _aggregate_bars_to_daily on the _live
    file must produce the exact API OHLCV for the partial-miss ticker."""
    from vnstock_rollup import _aggregate_bars_to_daily

    d = date(2026, 4, 20)
    _write_api_row(tmp_path, "PNJ", d, open=75.0, high=78.0, low=74.5,
                   close=76.67, volume=1_870_506)
    _write_live_bars(tmp_path, d, [
        {"time": pd.Timestamp("2026-04-20 09:15"), "ticker": "PNJ",
         "open": 112.5, "high": 112.5, "low": 112.5, "close": 112.5, "volume": 83_284},
    ])

    backfill_rolled_bars(tmp_path, [("PNJ", d)])

    bars = _read_live_bars(tmp_path, d)
    daily = _aggregate_bars_to_daily(bars)
    pnj = daily[daily["ticker"] == "PNJ"].iloc[0]
    assert float(pnj["close"]) == 76.67
    assert int(pnj["volume"]) == 1_870_506
    assert float(pnj["open"]) == 75.0
    assert float(pnj["high"]) == 78.0
    assert float(pnj["low"]) == 74.5
