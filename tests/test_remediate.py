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


# ── Phase 5C checklist coverage (replaces manual UI tests where possible) ──

def test_apply_bulk_filters_by_ticker(tmp_path):
    """Covers checklist D1 + the UPS regression fix: --all --ticker UPS
    must only touch anomalies for that ticker."""
    _seed_anomalies(tmp_path, [
        {"ticker": "UPS", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
        {"ticker": "HVA", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
        {"ticker": "FPT", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path, ticker="UPS")
    assert res["ok"] == 1
    wl = load_whitelist(tmp_path)
    assert ("UPS", "2026-04-15", "band") in wl
    assert ("HVA", "2026-04-15", "band") not in wl
    assert ("FPT", "2026-04-15", "band") not in wl


def test_apply_bulk_ticker_case_insensitive(tmp_path):
    """Covers checklist E2: `vcb` typed in the UI must match stored `VCB`."""
    _seed_anomalies(tmp_path, [
        {"ticker": "VCB", "trading_date": "2026-04-15",
         "kind": "band", "severity": "warn"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path, ticker="vcb")
    assert res["ok"] == 1
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl


def test_apply_bulk_ticker_combined_with_kind_and_severity(tmp_path):
    """All three filters compose — only rows matching every filter are hit."""
    _seed_anomalies(tmp_path, [
        {"ticker": "VCB", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
        {"ticker": "VCB", "trading_date": "2026-04-16",
         "kind": "band", "severity": "warn"},
        {"ticker": "VCB", "trading_date": "2026-04-17",
         "kind": "ohlc", "severity": "fail"},
        {"ticker": "FPT", "trading_date": "2026-04-15",
         "kind": "band", "severity": "fail"},
    ])
    res = apply_bulk("accept", warehouse=tmp_path,
                      ticker="VCB", kind="band", severity="fail")
    assert res["ok"] == 1
    wl = load_whitelist(tmp_path)
    assert ("VCB", "2026-04-15", "band") in wl
    assert ("VCB", "2026-04-16", "band") not in wl   # wrong severity
    assert ("VCB", "2026-04-17", "ohlc") not in wl   # wrong kind
    assert ("FPT", "2026-04-15", "band") not in wl   # wrong ticker


def test_atomic_write_retries_on_permission_error(tmp_path, monkeypatch):
    """Covers checklist E3: Dropbox/antivirus file locks on Windows should
    be absorbed by the retry loop, not bubbled up."""
    from vnstock_remediate import _atomic_write_json
    import os as _os

    call_count = {"n": 0}
    real_replace = _os.replace

    def flaky_replace(src, dst):
        call_count["n"] += 1
        if call_count["n"] <= 2:   # fail twice, succeed on the 3rd
            raise PermissionError("Windows lock")
        return real_replace(src, dst)

    monkeypatch.setattr(_os, "replace", flaky_replace)
    target = tmp_path / "flaky.json"
    _atomic_write_json(target, {"entries": [{"ticker": "VCB"}]})

    assert target.exists()
    assert call_count["n"] == 3   # retried twice, succeeded on third
    assert json.loads(target.read_text())["entries"][0]["ticker"] == "VCB"


def test_atomic_write_reraises_after_max_retries(tmp_path, monkeypatch):
    """If all 5 retries fail, the error surfaces so the caller can react."""
    from vnstock_remediate import _atomic_write_json
    import os as _os

    def always_fail(_src, _dst):
        raise PermissionError("stuck")

    monkeypatch.setattr(_os, "replace", always_fail)
    with pytest.raises(PermissionError):
        _atomic_write_json(tmp_path / "blocked.json", {"entries": []})


def test_accept_then_scan_warehouse_filters_whitelisted(tmp_path):
    """End-to-end (checklist D1): bulk accept writes whitelist, then
    scan_warehouse reads it and excludes those entries from the next
    anomaly scan. Replaces the "re-audit after bulk" manual step."""
    # Seed a warehouse bar that trips the band detector hard
    import pyarrow as pa
    import pyarrow.parquet as pq

    year_dir = tmp_path / "prices" / "ticker=VCB" / "year=2026"
    year_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "time": pd.to_datetime([
            "2026-04-14", "2026-04-15", "2026-04-16"
        ]).date,
        "open": [90.0, 90.0, 90.0],
        "high": [90.0, 110.0, 90.0],   # 22% jump triggers band fail
        "low":  [90.0, 90.0, 90.0],
        "close":[90.0, 110.0, 90.0],
        "volume":[1000, 1000, 1000],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")

    from vnstock_anomaly import scan_warehouse
    # lookback=None → scan ALL history. (Was lookback=10, but the fixture's fixed
    # April-2026 dates age out of a "last-10-calendar-days-from-today" window as
    # real time passes, so the scan saw 0 bars and the assert tripped — a
    # time-dependent test bug unrelated to the detector.)
    pre = scan_warehouse(warehouse=tmp_path, lookback=None)
    vcb_hits_pre = [a for a in pre.anomalies if a.ticker == "VCB"]
    assert vcb_hits_pre, "fixture should trip at least one anomaly"

    # Accept via apply_bulk — mirrors the dashboard button exactly
    from vnstock_anomaly import write_report
    write_report(pre, tmp_path)
    res = apply_bulk("accept", warehouse=tmp_path, ticker="VCB")
    assert res["ok"] >= 1

    # Re-scan: whitelisted entries are filtered out
    post = scan_warehouse(warehouse=tmp_path, lookback=None)
    assert not [a for a in post.anomalies if a.ticker == "VCB"], \
        "whitelisted anomalies must be filtered out on rescan"


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
