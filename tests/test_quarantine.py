"""Tests for vnstock_quarantine — storage + retrieval + summary."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from vnstock_quarantine import (
    accept_quarantine,
    bump_retry,
    clear_quarantine,
    list_quarantine,
    quarantine_dropped,
    quarantine_row,
    summary,
)


# ── quarantine_row ─────────────────────────────────────────────────────────

def test_quarantine_row_writes_file(tmp_path):
    path = quarantine_row(
        "VCB", "2026-04-15", "close<=0",
        {"close": 0, "volume": 1000},
        warehouse=tmp_path,
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["ticker"] == "VCB"
    assert data["bar_date"] == "2026-04-15"
    assert data["reason"] == "close<=0"
    assert data["raw_values"]["close"] == 0


def test_quarantine_row_normalises_ticker_case(tmp_path):
    quarantine_row("vcb", "2026-04-15", "x", {}, warehouse=tmp_path)
    path = tmp_path / "_meta/quarantine/VCB/2026-04-15.json"
    assert path.exists()


def test_quarantine_row_normalises_date(tmp_path):
    quarantine_row("VCB", pd.Timestamp("2026-04-15"), "x", {}, warehouse=tmp_path)
    assert (tmp_path / "_meta/quarantine/VCB/2026-04-15.json").exists()


def test_quarantine_row_preserves_retry_count_on_overwrite(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    bump_retry("VCB", "2026-04-15", warehouse=tmp_path)
    bump_retry("VCB", "2026-04-15", warehouse=tmp_path)
    # Re-quarantining the same bar should keep retry_count
    quarantine_row("VCB", "2026-04-15", "b", {}, warehouse=tmp_path)
    data = json.loads((tmp_path / "_meta/quarantine/VCB/2026-04-15.json").read_text())
    assert data["retry_count"] == 2
    assert data["reason"] == "b"


# ── list_quarantine ────────────────────────────────────────────────────────

def test_list_quarantine_empty(tmp_path):
    df = list_quarantine(tmp_path)
    assert df.empty


def test_list_quarantine_returns_all(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    quarantine_row("VCB", "2026-04-16", "b", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "c", {}, warehouse=tmp_path)
    df = list_quarantine(tmp_path)
    assert len(df) == 3
    assert set(df["ticker"]) == {"VCB", "FPT"}


def test_list_quarantine_filter_by_ticker(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "b", {}, warehouse=tmp_path)
    df = list_quarantine(tmp_path, ticker="FPT")
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "FPT"


# ── accept / clear / bump ─────────────────────────────────────────────────

def test_accept_marks_entry(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path, note="ok")
    data = json.loads((tmp_path / "_meta/quarantine/VCB/2026-04-15.json").read_text())
    assert data["accepted"] is True
    assert data["note"] == "ok"


def test_accept_missing_returns_false(tmp_path):
    assert accept_quarantine("XXX", "2026-04-15", warehouse=tmp_path) is False


def test_clear_removes_file(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert clear_quarantine("VCB", "2026-04-15", warehouse=tmp_path)
    assert not (tmp_path / "_meta/quarantine/VCB/2026-04-15.json").exists()


def test_bump_retry_increments(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert bump_retry("VCB", "2026-04-15", warehouse=tmp_path) == 1
    assert bump_retry("VCB", "2026-04-15", warehouse=tmp_path) == 2


# ── summary ────────────────────────────────────────────────────────────────

def test_summary_empty(tmp_path):
    s = summary(tmp_path)
    assert s["total"] == 0
    assert s["pending"] == 0


def test_summary_counts_and_breakdown(tmp_path):
    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    quarantine_row("VCB", "2026-04-16", "high<low", {}, warehouse=tmp_path)
    accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path)
    s = summary(tmp_path)
    assert s["total"] == 3
    assert s["accepted"] == 1
    assert s["pending"] == 2
    assert s["by_reason"]["close<=0"] == 2
    assert s["by_reason"]["high<low"] == 1


# ── quarantine_dropped (bulk from contract output) ────────────────────────

def test_quarantine_dropped_bulk(tmp_path):
    dropped = pd.DataFrame({
        "ticker": ["VCB", "FPT", "MBB"],
        "time": ["2026-04-15", "2026-04-15", "2026-04-16"],
        "close": [0, -1, 100],
        "volume": [1000, 1000, -5],
    })
    n = quarantine_dropped(
        dropped,
        reasons=["close<=0", "close<=0", "volume<0"],
        warehouse=tmp_path,
    )
    assert n == 3
    df = list_quarantine(tmp_path)
    assert len(df) == 3


def test_quarantine_dropped_empty_df(tmp_path):
    assert quarantine_dropped(pd.DataFrame(), "x", warehouse=tmp_path) == 0


def test_quarantine_dropped_single_reason_broadcasts(tmp_path):
    dropped = pd.DataFrame({
        "ticker": ["VCB", "FPT"],
        "time": ["2026-04-15", "2026-04-15"],
        "close": [0, -1],
    })
    n = quarantine_dropped(dropped, reasons="bad data", warehouse=tmp_path)
    assert n == 2
    for t in ("VCB", "FPT"):
        data = json.loads((tmp_path / f"_meta/quarantine/{t}/2026-04-15.json").read_text())
        assert data["reason"] == "bad data"


# ── auto_heal ────────────────────────────────────────────────────────────


def test_auto_heal_empty_warehouse(tmp_path):
    """No quarantine → zero stats, no errors."""
    from vnstock_quarantine import auto_heal
    stats = auto_heal(tmp_path)
    assert stats == {
        "scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
        "archived": 0, "skipped_accepted": 0,
    }


def test_auto_heal_skips_accepted_entries(tmp_path, monkeypatch):
    """User-accepted entries are left alone — we never retry them."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path)

    called = {"n": 0}

    def _fake_refetch(*_a, **_kw):
        called["n"] += 1
        return {"status": "ok"}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert called["n"] == 0
    assert stats["skipped_accepted"] == 1
    assert stats["refetched_ok"] == 0


def test_auto_heal_refetches_and_clears_on_success(tmp_path, monkeypatch):
    """Happy path — refetch returns ok, entry is cleared by refetch()."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)

    def _fake_refetch(ticker, bar_date, *, warehouse, **_kw):
        # Simulate successful refetch: clear the entry the way the real
        # vnstock_remediate.refetch does.
        clear_quarantine(ticker, bar_date, warehouse=warehouse)
        return {"status": "ok", "rows_written": 1}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats == {
        "scanned": 1, "refetched_ok": 1, "refetched_fail": 0,
        "archived": 0, "skipped_accepted": 0,
    }
    assert list_quarantine(tmp_path).empty


def test_auto_heal_bumps_retry_on_failure(tmp_path, monkeypatch):
    """Failed refetch → retry_count goes up, entry stays in quarantine."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        return {"status": "fail", "reason": "API down"}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats["refetched_fail"] == 1
    df = list_quarantine(tmp_path)
    assert len(df) == 1
    assert int(df.iloc[0]["retry_count"]) == 1


def test_auto_heal_archives_after_max_retries(tmp_path, monkeypatch):
    """retry_count >= max_retries → entry is removed + log line appended."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    # Pre-bump to 3 (MAX_RETRIES_DEFAULT)
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("refetch must not be called when retries exhausted")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats["archived"] == 1
    assert stats["refetched_ok"] == 0
    assert list_quarantine(tmp_path).empty

    log = tmp_path / "_meta" / "remediation_log.jsonl"
    assert log.exists()
    line = json.loads(log.read_text().strip().splitlines()[-1])
    assert line["action"] == "auto_archive"
    assert line["ticker"] == "VCB"
    assert line["date"] == "2026-04-15"
    assert "retries=3" in line["detail"]


def test_auto_heal_dry_run_never_mutates(tmp_path, monkeypatch):
    """dry_run=True: scans and reports but touches nothing."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    # Push past max_retries so an archive WOULD happen
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("should not be called during dry_run")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path, dry_run=True)
    assert stats["archived"] == 1   # counted but not executed
    # Entry still on disk; log not written
    df = list_quarantine(tmp_path)
    assert len(df) == 1
    log = tmp_path / "_meta" / "remediation_log.jsonl"
    assert not log.exists()


def test_auto_heal_dry_run_counts_pending_refetches(tmp_path, monkeypatch):
    """dry-run on fresh entries must surface the planned refetch count so
    the operator sees WHAT would happen, not a silent all-zero report."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "x", {}, warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("should not be called during dry_run")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path, dry_run=True)
    assert stats["refetched_ok"] == 2, \
        "dry-run should report the planned refetch count, not 0"
    assert stats["archived"] == 0
    # Nothing mutated — retry_count stays at 0 and entries survive
    df = list_quarantine(tmp_path)
    assert len(df) == 2
    assert all(int(r["retry_count"]) == 0 for _, r in df.iterrows())


def test_auto_heal_no_archive_option_leaves_exhausted_entries(tmp_path, monkeypatch):
    """archive_exhausted=False: count archives but keep on disk."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    monkeypatch.setattr("vnstock_remediate.refetch",
                         lambda *a, **k: {"status": "ok"})
    stats = auto_heal(tmp_path, archive_exhausted=False)
    assert stats["archived"] == 1
    # Entry survives
    assert not list_quarantine(tmp_path).empty
