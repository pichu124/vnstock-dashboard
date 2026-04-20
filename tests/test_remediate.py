"""Tests for vnstock_remediate — whitelist, archive, bulk, logging."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_remediate import (
    accept,
    add_to_whitelist,
    apply_bulk,
    archive,
    attach_note,
    load_whitelist,
)


# ── whitelist ──────────────────────────────────────────────────────────────

def test_load_whitelist_empty(tmp_path):
    assert load_whitelist(tmp_path) == set()


def test_add_to_whitelist_writes_json(tmp_path):
    path = add_to_whitelist("VCB", "2026-04-15", kind="band",
                             warehouse=tmp_path, note="halt resumed")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["ticker"] == "VCB"
    assert entry["kind"] == "band"
    assert entry["note"] == "halt resumed"


def test_add_to_whitelist_dedupes(tmp_path):
    add_to_whitelist("VCB", "2026-04-15", kind="band", warehouse=tmp_path)
    add_to_whitelist("VCB", "2026-04-15", kind="band", warehouse=tmp_path,
                      note="updated")
    wl = load_whitelist(tmp_path)
    assert len(wl) == 1  # same tuple, overwrites


def test_add_to_whitelist_different_kinds_coexist(tmp_path):
    add_to_whitelist("VCB", "2026-04-15", kind="band", warehouse=tmp_path)
    add_to_whitelist("VCB", "2026-04-15", kind="ohlc", warehouse=tmp_path)
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl
    assert ("VCB", "2026-04-15", "ohlc") in wl


def test_load_whitelist_normalises_format(tmp_path):
    add_to_whitelist("vcb", "2026-04-15T00:00:00", kind="band",
                      warehouse=tmp_path)
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl


# ── accept (combines quarantine mark + whitelist) ─────────────────────────

def test_accept_writes_both_whitelist_and_quarantine_note(tmp_path):
    from vnstock_quarantine import quarantine_row
    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)

    res = accept("VCB", "2026-04-15", warehouse=tmp_path, kind="band",
                 note="legitimate halt")
    assert res["status"] == "ok"

    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl

    q_file = tmp_path / "_meta/quarantine/VCB/2026-04-15.json"
    q_data = json.loads(q_file.read_text())
    assert q_data["accepted"] is True
    assert q_data["note"] == "legitimate halt"


# ── archive ────────────────────────────────────────────────────────────────

def _seed_warehouse_row(warehouse: Path, ticker: str, d: str, close: float):
    year = int(d[:4])
    year_dir = warehouse / "prices" / f"ticker={ticker}" / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp(d)],
        "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [1000],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "prices.parquet")


def test_archive_removes_target_row(tmp_path):
    _seed_warehouse_row(tmp_path, "VCB", "2026-04-15", 100.0)
    res = archive("VCB", "2026-04-15", warehouse=tmp_path)
    assert res["status"] == "ok"
    assert res["removed"] == 1
    # File should be gone (was the only row)
    assert not (tmp_path / "prices/ticker=VCB/year=2026/prices.parquet").exists()


def test_archive_missing_partition(tmp_path):
    res = archive("NOPE", "2026-04-15", warehouse=tmp_path)
    assert res["status"] == "fail"


def test_archive_missing_row_in_partition(tmp_path):
    _seed_warehouse_row(tmp_path, "VCB", "2026-04-14", 100.0)
    res = archive("VCB", "2026-04-15", warehouse=tmp_path)
    assert res["status"] == "fail"


# ── bulk ───────────────────────────────────────────────────────────────────

def test_apply_bulk_missing_anomalies_file(tmp_path):
    res = apply_bulk("accept", warehouse=tmp_path)
    assert res["status"] == "fail"


def _seed_anomalies(warehouse: Path, items):
    meta = warehouse / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "anomalies.json").write_text(json.dumps({
        "run_at": "2026-04-20T00:00:00Z",
        "tickers_scanned": 3,
        "total": len(items),
        "by_kind": {},
        "by_severity": {},
        "anomalies": items,
    }))


def test_apply_bulk_dry_run_no_side_effect(tmp_path):
    _seed_anomalies(tmp_path, [
        {"ticker": "VCB", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path, dry_run=True)
    assert res["ok"] == 1
    assert res["dry_run"] is True
    # No whitelist written
    wl = load_whitelist(tmp_path)
    assert len(wl) == 0


def test_apply_bulk_accept_creates_whitelist(tmp_path):
    _seed_anomalies(tmp_path, [
        {"ticker": "VCB", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"},
        {"ticker": "FPT", "trading_date": "2026-04-16",
         "kind": "ohlc", "severity": "warn"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path)
    assert res["ok"] == 2
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl
    assert ("FPT", "2026-04-16", "ohlc") in wl


def test_apply_bulk_filters_by_kind(tmp_path):
    _seed_anomalies(tmp_path, [
        {"ticker": "VCB", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"},
        {"ticker": "FPT", "trading_date": "2026-04-16",
         "kind": "ohlc", "severity": "warn"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path, kind="band")
    assert res["ok"] == 1
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl
    assert ("FPT", "2026-04-16", "ohlc") not in wl


def test_apply_bulk_filters_by_severity(tmp_path):
    _seed_anomalies(tmp_path, [
        {"ticker": "A", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"},
        {"ticker": "B", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path, severity="fail")
    assert res["ok"] == 1
    wl = load_whitelist(tmp_path)
    assert ("B", "2026-04-15", "band") in wl


def test_apply_bulk_limit(tmp_path):
    _seed_anomalies(tmp_path, [
        {"ticker": f"T{i}", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"}
        for i in range(5)
    ])
    res = apply_bulk("accept", warehouse=tmp_path, limit=2)
    assert res["ok"] == 2


# ── remediation log ──────────────────────────────────────────────────────

def test_action_writes_log_line(tmp_path):
    attach_note("VCB", "2026-04-15", "test note", warehouse=tmp_path)
    # note on a nonexistent entry fails, but the log should still capture
    # the successful path when entry exists:
    from vnstock_quarantine import quarantine_row
    quarantine_row("FPT", "2026-04-15", "x", {}, warehouse=tmp_path)
    attach_note("FPT", "2026-04-15", "fpt note", warehouse=tmp_path)

    log = tmp_path / "_meta/remediation_log.jsonl"
    assert log.exists()
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    entries = [json.loads(l) for l in lines]
    assert any(e["ticker"] == "FPT" and e["result"] == "ok" for e in entries)
