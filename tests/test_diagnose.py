"""Tests for vnstock_diagnose — per-row investigation tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_diagnose import DiagnoseResult, _decide_verdict, diagnose, render


def _seed_warehouse(path: Path, ticker: str, rows: list[tuple[str, float, int]]):
    """rows: list of (date_str, close, volume)."""
    if not rows:
        return
    year = int(rows[0][0][:4])
    year_dir = path / "prices" / f"ticker={ticker.upper()}" / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp(d) for d, _, _ in rows],
        "open": [c for _, c, _ in rows],
        "high": [c for _, c, _ in rows],
        "low": [c for _, c, _ in rows],
        "close": [c for _, c, _ in rows],
        "volume": [v for _, _, v in rows],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")


def _seed_capital_event(path: Path, ticker: str, ex_date: str, type_: str,
                         ratio: float | None = None, cash_amount: float | None = None):
    cdir = path / "_meta" / "corp_actions"
    cdir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{
        "ticker": ticker.upper(),
        "ex_date": pd.Timestamp(ex_date),
        "type": type_,
        "cash_amount": cash_amount,
        "ratio": ratio,
        "raw": "",
    }])
    df.to_parquet(cdir / f"{ticker.upper()}.parquet", index=False)


def _seed_reconciler(path: Path, entries: list[dict]):
    meta = path / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "reconciliation_report.json").write_text(json.dumps({
        "discrepancies": entries,
    }))


def _seed_anomalies(path: Path, entries: list[dict]):
    meta = path / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "anomalies.json").write_text(json.dumps({"anomalies": entries}))


# ── verdict heuristic ─────────────────────────────────────────────────────

def test_verdict_registered_corp_action_wins(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 70.0, 800_000),    # large drop
        ("2026-04-16", 71.0, 900_000),
    ])
    _seed_capital_event(tmp_path, "VCB", "2026-04-15", "split", ratio=1.5)
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert r.verdict == "registered corp action"
    assert r.confidence >= 0.9
    assert r.suggested_action == "accept"


def test_verdict_wss_miss(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 100.5, 800_000),
    ])
    _seed_reconciler(tmp_path, [{
        "ticker": "VCB", "trading_date": "2026-04-15",
        "api_close": 100.5, "rolled_close": 100.0,
        "api_volume": 800_000, "rolled_volume": 0,
        "severity": "warn", "reason": "rolled missing",
    }])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert r.verdict == "WSS missed session"
    assert "rolled_volume=0" in " ".join(r.rationale)


def test_verdict_likely_cash_dividend(tmp_path):
    """Large day-over-day drop with NO registered event → likely cash div."""
    _seed_warehouse(tmp_path, "CDC", [
        ("2026-04-14", 26.30, 100_000),
        ("2026-04-15", 17.93, 100_000),    # -31.8% drop
        ("2026-04-16", 18.00, 100_000),
    ])
    r = diagnose("CDC", date(2026, 4, 15), warehouse=tmp_path)
    assert r.verdict == "likely cash dividend (unregistered)"
    assert r.confidence >= 0.7
    assert "register" in r.suggested_action.lower()


def test_verdict_moderate_drop(tmp_path):
    """6% drop is in the maybe-dividend range."""
    _seed_warehouse(tmp_path, "SBT", [
        ("2026-04-14", 21.90, 200_000),
        ("2026-04-15", 20.66, 200_000),    # -5.66% drop
        ("2026-04-16", 20.70, 200_000),
    ])
    r = diagnose("SBT", date(2026, 4, 15), warehouse=tmp_path)
    assert "moderate drop" in r.verdict
    assert r.suggested_action == "investigate (check news / dividend records)"


def test_verdict_wss_partial_miss(tmp_path):
    _seed_warehouse(tmp_path, "BFC", [
        ("2026-04-19", 64.0, 1_000_000),
        ("2026-04-20", 64.5, 1_000_000),
    ])
    _seed_reconciler(tmp_path, [{
        "ticker": "BFC", "trading_date": "2026-04-20",
        "api_close": 64.5, "rolled_close": 67.7,
        "api_volume": 1_000_000, "rolled_volume": 50_000,    # 5% only
        "severity": "fail", "reason": "close drift",
    }])
    r = diagnose("BFC", date(2026, 4, 20), warehouse=tmp_path)
    assert r.verdict == "WSS partial miss (volume incomplete)"


def test_verdict_no_clear_cause_no_warehouse_data(tmp_path):
    r = diagnose("XYZ", date(2026, 4, 15), warehouse=tmp_path)
    assert r.verdict == "no clear cause"
    assert any("no warehouse data" in r2 for r2 in r.rationale)


def test_verdict_no_change_no_anomaly(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 100.5, 1_000_000),    # +0.5% — boring
    ])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert r.verdict == "no clear cause"


def test_verdict_warehouse_only_anomaly(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 100.5, 1_000_000),
    ])
    _seed_anomalies(tmp_path, [{
        "ticker": "VCB", "trading_date": "2026-04-15",
        "kind": "ohlc", "severity": "warn",
        "detail": "high < low",
    }])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert "warehouse-only anomaly" in r.verdict
    assert "ohlc" in r.verdict


# ── data loading ──────────────────────────────────────────────────────────

def test_warehouse_window_padding(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-10", 99.0, 1_000_000),
        ("2026-04-11", 99.5, 1_000_000),
        ("2026-04-15", 100.0, 1_000_000),
        ("2026-04-18", 100.5, 1_000_000),
        ("2026-04-22", 101.0, 1_000_000),
    ])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path, pad_days=5)
    times = [row["time"] for row in r.warehouse_window]
    assert date(2026, 4, 10) in times
    assert date(2026, 4, 18) in times
    # 04-22 is +7 days, outside pad_days=5
    assert date(2026, 4, 22) not in times


def test_day_over_day_change_computed(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 95.0, 1_000_000),    # -5% exactly
    ])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert r.day_over_day_change_pct == pytest.approx(-5.0, abs=0.01)
    assert r.prev_close == 100.0


def test_capital_events_loaded(tmp_path):
    _seed_capital_event(tmp_path, "VCB", "2026-04-15", "bonus", ratio=1.2)
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert len(r.capital_events) == 1
    assert r.capital_events[0]["type"] == "bonus"


def test_capital_events_loaded_from_registry(tmp_path):
    """Registry (manual/vietstock entries) must appear in diagnose capital_events."""
    from vnstock_corp_registry import register_event
    register_event("VCB", "2026-04-15", "rights", ratio=1.0, cash_amount=10.0,
                   source="manual", warehouse=tmp_path)
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    assert len(r.capital_events) == 1
    assert r.capital_events[0]["type"] == "rights"
    assert r.capital_events[0]["source"] == "manual"


def test_render_does_not_crash(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 95.0, 1_000_000),
    ])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    text = render(r)
    assert "VCB" in text
    assert "VERDICT" in text


def test_to_dict_json_serialisable(tmp_path):
    _seed_warehouse(tmp_path, "VCB", [
        ("2026-04-14", 100.0, 1_000_000),
        ("2026-04-15", 95.0, 1_000_000),
    ])
    r = diagnose("VCB", date(2026, 4, 15), warehouse=tmp_path)
    json.dumps(r.to_dict(), default=str)
