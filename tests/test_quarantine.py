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
