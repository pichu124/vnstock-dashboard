"""Tests for vnstock_health — system health collector."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_health import collect, HealthSnapshot


@pytest.fixture
def mini_warehouse(tmp_path: Path) -> Path:
    """Build a tiny fake warehouse with 2 tickers × 2 years."""
    prices = tmp_path / "prices"
    for ticker, closes in [("VCB", [100.0] * 10), ("FPT", [120.0] * 10)]:
        for year in (2024, 2025):
            year_dir = prices / f"ticker={ticker}" / f"year={year}"
            year_dir.mkdir(parents=True, exist_ok=True)
            dates = pd.date_range(f"{year}-01-02", periods=len(closes), freq="B")
            df = pd.DataFrame({
                "time": dates.date,
                "open": closes, "high": closes, "low": closes, "close": closes,
                "volume": [1_000_000] * len(closes),
            })
            table = pa.Table.from_pandas(df)
            pq.write_table(table, year_dir / "p.parquet", compression="snappy")
    return tmp_path


def test_collect_on_empty_warehouse(tmp_path):
    snap = collect(tmp_path)
    assert isinstance(snap, HealthSnapshot)
    assert snap.ticker_count == 0
    assert any("empty" in w.lower() or "not found" in w.lower() for w in snap.warnings)


def test_collect_reports_tickers_and_rows(mini_warehouse):
    snap = collect(mini_warehouse)
    assert snap.ticker_count == 2
    assert snap.row_count == 2 * 2 * 10   # 2 tickers * 2 years * 10 bars
    assert snap.partition_count == 4


def test_collect_reports_date_range(mini_warehouse):
    snap = collect(mini_warehouse)
    assert snap.oldest_bar is not None
    assert snap.newest_bar is not None
    assert snap.oldest_bar <= snap.newest_bar


def test_collect_ingests_metadata_reports(mini_warehouse):
    meta = mini_warehouse / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "last_sync.json").write_text(json.dumps({"VCB": "2025-04-17"}))
    (meta / "pipeline_status.json").write_text(json.dumps({
        "updater": {"last_success_date": "2025-04-17", "machine": "vm-1"}
    }))
    (meta / "reconciliation_report.json").write_text(json.dumps({
        "ok": 10, "warn": 2, "fail": 0,
        "missing_in_api": 0, "missing_in_rolled": 1,
        "discrepancies": [],
    }))
    (meta / "anomalies.json").write_text(json.dumps({
        "total": 3,
        "by_kind": {"band": 2, "vol_spike": 1},
        "by_severity": {"warn": 3},
        "anomalies": [],
    }))

    snap = collect(mini_warehouse)
    assert snap.last_sync == {"VCB": "2025-04-17"}
    assert "updater" in snap.pipeline_status
    assert snap.reconciler["ok"] == 10
    assert snap.anomalies["total"] == 3


def test_collect_handles_corrupt_metadata(mini_warehouse):
    meta = mini_warehouse / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "last_sync.json").write_text("{not json")
    snap = collect(mini_warehouse)
    assert any("corrupt" in w for w in snap.warnings)


def test_snapshot_roundtrips_to_dict(mini_warehouse):
    snap = collect(mini_warehouse)
    d = snap.to_dict()
    assert d["ticker_count"] == snap.ticker_count
    assert d["warehouse_path"] == str(mini_warehouse)
    # json-serialisable
    json.dumps(d, default=str)
