"""Tests for the partial-intraday-bar self-heal in vnstock_updater.update_ticker.

Bug (2026-06-11): an updater run DURING the session stores VCI's in-progress
daily bar (partial volume). The old `fetch_from = last_date + 1` then returned
"up_to_date" for the rest of the day and only fetched LATER dates on subsequent
days — freezing the partial bar forever. Observed: 379 tickers carried partial
10/06 bars summing to 6,157 tỷ ≈ 57% of the real day (the morning share).

Fix: refetch from `last_date` INCLUSIVE; the year-merge dedups keep="last" so
the refetched final bar replaces the stale partial one.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# vnstock_updater hard-requires the vnstock package at import time; skip the
# module cleanly on environments without it (CI/sandbox) — it runs in full on
# the dev machine where vnstock is installed.
vu = pytest.importorskip("vnstock_updater")


def _seed(prices_dir: Path, ticker: str, rows: list[dict]) -> Path:
    tdir = prices_dir / f"ticker={ticker}"
    for year in {pd.to_datetime(r["time"]).year for r in rows}:
        ydf = pd.DataFrame([r for r in rows
                            if pd.to_datetime(r["time"]).year == year])
        ydir = tdir / f"year={year}"
        ydir.mkdir(parents=True, exist_ok=True)
        ydf.to_parquet(ydir / "prices.parquet", index=False)
    return tdir


def _bar(d: str, close: float, vol: float) -> dict:
    return {"time": pd.Timestamp(d), "open": close, "high": close,
            "low": close, "close": close, "volume": vol}


def test_partial_today_bar_is_refetched_and_replaced(tmp_path, monkeypatch):
    today = date(2026, 6, 10)
    prices = tmp_path / "prices"
    _seed(prices, "AAA", [_bar("2026-06-09", 10.0, 500_000),
                          _bar("2026-06-10", 10.2, 300_000)])  # partial intraday bar

    fetched = {}

    def fake_fetch(ticker, start, end):
        fetched["start"] = start
        return pd.DataFrame([{"time": date(2026, 6, 10), "open": 10.2,
                              "high": 10.4, "low": 10.1, "close": 10.3,
                              "volume": 900_000.0}])           # final EOD bar

    monkeypatch.setattr(vu, "_fetch_prices", fake_fetch)
    res = vu.update_ticker("AAA", prices, today)
    # Old behavior: "up_to_date" (fetch_from = 11/06 > today) → frozen partial.
    assert res["status"] == "updated"
    assert fetched["start"] == "2026-06-10"       # inclusive refetch of last bar

    out = pd.read_parquet(prices / "ticker=AAA/year=2026/prices.parquet")
    out["time"] = pd.to_datetime(out["time"]).dt.date
    row = out[out["time"] == date(2026, 6, 10)]
    assert len(row) == 1                          # dedup: one bar per day
    assert float(row["volume"].iloc[0]) == 900_000.0   # partial replaced by final


def test_next_day_run_heals_yesterdays_partial(tmp_path, monkeypatch):
    # Run on 11/06 with a partial 10/06 bar: must fetch FROM 10/06 (inclusive),
    # not 11/06, so yesterday's frozen partial gets replaced too.
    today = date(2026, 6, 11)
    prices = tmp_path / "prices"
    _seed(prices, "BBB", [_bar("2026-06-10", 20.0, 100_000)])  # stale partial

    def fake_fetch(ticker, start, end):
        assert start == "2026-06-10"              # heals the last stored day
        return pd.DataFrame([
            {"time": date(2026, 6, 10), "open": 20, "high": 21, "low": 19.8,
             "close": 20.5, "volume": 800_000.0},
            {"time": date(2026, 6, 11), "open": 20.5, "high": 20.8, "low": 20.2,
             "close": 20.6, "volume": 600_000.0},
        ])

    monkeypatch.setattr(vu, "_fetch_prices", fake_fetch)
    res = vu.update_ticker("BBB", prices, today)
    assert res["status"] == "updated"
    assert res["new_days"] == 1                   # only 11/06 is genuinely new

    out = pd.read_parquet(prices / "ticker=BBB/year=2026/prices.parquet")
    out["time"] = pd.to_datetime(out["time"]).dt.date
    assert float(out[out["time"] == date(2026, 6, 10)]["volume"].iloc[0]) == 800_000.0
    assert len(out) == 2


def test_future_dated_bar_still_short_circuits(tmp_path, monkeypatch):
    # Clock-skew/garbage future bar → "up_to_date", no fetch (guard retained).
    today = date(2026, 6, 10)
    prices = tmp_path / "prices"
    _seed(prices, "CCC", [_bar("2026-06-12", 5.0, 1_000)])

    def boom(*a, **k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(vu, "_fetch_prices", boom)
    assert vu.update_ticker("CCC", prices, today)["status"] == "up_to_date"
