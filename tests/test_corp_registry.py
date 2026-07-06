"""Tests for vnstock_corp_registry — central corp action store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_corp_registry import (
    DEFAULT_CONFIDENCE,
    VALID_TYPES,
    clear_source,
    get_events_for_date,
    get_events_for_ticker,
    import_from_capital_history,
    register_bulk,
    register_event,
    remove_event,
    summary,
)


# ── register_event ────────────────────────────────────────────────────────

def test_register_event_writes_parquet(tmp_path):
    n = register_event("VCB", "2026-04-15", "cash",
                        cash_amount=2.0, source="manual",
                        warehouse=tmp_path)
    assert n == 1
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["type"] == "cash"
    assert df.iloc[0]["cash_amount"] == 2.0


def test_register_event_normalises_ticker_case(tmp_path):
    register_event("vcb", "2026-04-15", "cash", cash_amount=2.0,
                    warehouse=tmp_path)
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 1


def test_register_event_uses_default_confidence(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    source="manual", warehouse=tmp_path)
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert df.iloc[0]["confidence"] == DEFAULT_CONFIDENCE["manual"]


def test_register_event_invalid_type_falls_back_to_unknown(tmp_path):
    register_event("VCB", "2026-04-15", "BADTYPE", warehouse=tmp_path)
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert df.iloc[0]["type"] == "unknown"


# ── deduplication ─────────────────────────────────────────────────────────

def test_dedupe_keeps_higher_confidence(tmp_path):
    # Lower confidence first
    register_event("VCB", "2026-04-15", "cash", cash_amount=1.0,
                    source="cafef", warehouse=tmp_path)
    # Higher confidence second
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    source="manual", warehouse=tmp_path)
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["source"] == "manual"
    assert df.iloc[0]["cash_amount"] == 2.0


def test_dedupe_preserves_different_types(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    warehouse=tmp_path)
    register_event("VCB", "2026-04-15", "bonus", ratio=1.2,
                    warehouse=tmp_path)
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 2


# ── register_bulk ─────────────────────────────────────────────────────────

def test_register_bulk(tmp_path):
    events = [
        {"ticker": "VCB", "ex_date": "2026-04-15", "type_": "cash",
         "cash_amount": 2.0, "source": "manual"},
        {"ticker": "FPT", "ex_date": "2026-04-16", "type_": "split",
         "ratio": 2.0, "source": "capital_history"},
    ]
    result = register_bulk(events, warehouse=tmp_path)
    assert result["added"] == 2
    assert result["total"] == 2


def test_register_bulk_empty(tmp_path):
    result = register_bulk([], warehouse=tmp_path)
    assert result["added"] == 0


# ── get_events_for_date ───────────────────────────────────────────────────

def test_get_events_for_date(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    warehouse=tmp_path)
    register_event("FPT", "2026-04-15", "bonus", ratio=1.2,
                    warehouse=tmp_path)
    register_event("VCB", "2026-04-16", "cash", cash_amount=1.0,
                    warehouse=tmp_path)
    df = get_events_for_date(date(2026, 4, 15), warehouse=tmp_path)
    assert len(df) == 2
    assert set(df["ticker"]) == {"VCB", "FPT"}


def test_get_events_for_date_empty(tmp_path):
    assert get_events_for_date(date(2026, 4, 15), warehouse=tmp_path).empty









# ── remove_event ──────────────────────────────────────────────────────────

def test_remove_event_deletes_matching_row(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    warehouse=tmp_path)
    register_event("VCB", "2026-04-15", "bonus", ratio=0.2,
                    warehouse=tmp_path)
    n = remove_event("VCB", "2026-04-15", "cash", warehouse=tmp_path)
    assert n == 1
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["type"] == "bonus"


def test_remove_event_no_match_returns_zero(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    warehouse=tmp_path)
    n = remove_event("VCB", "2026-04-15", "bonus", warehouse=tmp_path)
    assert n == 0
    assert len(get_events_for_ticker("VCB", warehouse=tmp_path)) == 1


def test_remove_event_empty_registry_returns_zero(tmp_path):
    assert remove_event("VCB", "2026-04-15", "cash", warehouse=tmp_path) == 0


# ── clear_source ──────────────────────────────────────────────────────────

def test_clear_source(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    source="cafef", warehouse=tmp_path)
    register_event("FPT", "2026-04-16", "bonus", ratio=1.2,
                    source="capital_history", warehouse=tmp_path)
    n = clear_source("cafef", warehouse=tmp_path)
    assert n == 1
    df = get_events_for_ticker("FPT", warehouse=tmp_path)
    assert len(df) == 1   # FPT survived


# ── import_from_capital_history ──────────────────────────────────────────

def test_import_from_capital_history(tmp_path):
    cdir = tmp_path / "_meta" / "corp_actions"
    cdir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{
        "ticker": "VCB", "ex_date": pd.Timestamp("2026-01-15"),
        "type": "bonus", "cash_amount": None, "ratio": 1.5, "raw": "",
    }, {
        "ticker": "VCB", "ex_date": pd.Timestamp("2025-09-27"),
        "type": "bonus", "cash_amount": None, "ratio": 1.2, "raw": "",
    }])
    df.to_parquet(cdir / "VCB.parquet", index=False)

    result = import_from_capital_history(tmp_path)
    assert result["added"] == 2
    df_reg = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df_reg) == 2
    assert all(df_reg["source"] == "capital_history")


def test_import_from_capital_history_no_dir(tmp_path):
    result = import_from_capital_history(tmp_path)
    assert "error" in result


# ── summary ────────────────────────────────────────────────────────────────

def test_summary_empty(tmp_path):
    s = summary(tmp_path)
    assert s["total"] == 0


def test_summary_counts(tmp_path):
    register_event("VCB", "2026-04-15", "cash", cash_amount=2.0,
                    source="manual", warehouse=tmp_path)
    register_event("FPT", "2026-04-16", "bonus", ratio=1.2,
                    source="capital_history", warehouse=tmp_path)
    s = summary(tmp_path)
    assert s["total"] == 2
    assert s["by_type"]["cash"] == 1
    assert s["by_type"]["bonus"] == 1
    assert s["by_source"]["manual"] == 1
    assert s["tickers_covered"] == 2


# ── integration: anomaly skip via registry ───────────────────────────────

def test_registry_event_suppresses_anomaly_band(tmp_path):
    """Registering a corp action makes scan_warehouse skip band/ohlc on
    that ex-date."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from vnstock_anomaly import scan_warehouse

    today = pd.Timestamp(date.today())
    prev_day = today - pd.Timedelta(days=1)
    year = today.year

    # Seed warehouse with a +20% breach on `today`
    year_dir = tmp_path / "prices" / "ticker=VCB" / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": [prev_day, today],
        "open": [100.0, 120.0], "high": [100.0, 120.0],
        "low": [100.0, 120.0], "close": [100.0, 120.0],
        "volume": [1_000_000, 1_000_000],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")

    # Seed exchange map → HOSE 7%
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "exchange_map.json").write_text('{"VCB": "HOSE"}')

    # Without registry: the +20% breach should fire
    r1 = scan_warehouse(tmp_path, lookback=30)
    assert any(a.ticker == "VCB" and a.kind == "band" for a in r1.anomalies)

    # Register a split on `today` → next scan suppresses band
    register_event("VCB", today.date(), "split", ratio=1.5,
                    source="manual", warehouse=tmp_path)
    r2 = scan_warehouse(tmp_path, lookback=30)
    assert not any(a.ticker == "VCB" and a.kind == "band"
                   for a in r2.anomalies), \
        "registered split must suppress band breach on its ex-date"
