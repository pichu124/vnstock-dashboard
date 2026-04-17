"""Tests for vnstock_exchange_map."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from vnstock_exchange_map import (
    _normalise_exchange,
    _pick_ticker_column,
    load_exchange_map,
)


# ── normalisation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("HOSE", "HOSE"),
    ("HSX", "HOSE"),
    ("hose", "HOSE"),
    ("hsx-listed", "HOSE"),
    ("HNX", "HNX"),
    ("hnx", "HNX"),
    ("UPCOM", "UPCOM"),
    ("upcom-index", "UPCOM"),
    ("", ""),
    (None, ""),
    ("UNKNOWN", ""),
])
def test_normalise_exchange(raw, expected):
    assert _normalise_exchange(raw) == expected


# ── ticker column picker ──────────────────────────────────────────────────

def test_pick_ticker_column_finds_standard_names():
    for col in ["ticker", "Ticker", "symbol", "stock_symbol", "code"]:
        df = pd.DataFrame({col: ["VCB"], "other": ["x"]})
        assert _pick_ticker_column(df.columns) == col


def test_pick_ticker_column_falls_back_to_first():
    df = pd.DataFrame({"mystery": ["VCB"]})
    assert _pick_ticker_column(df.columns) == "mystery"


# ── load_exchange_map ─────────────────────────────────────────────────────

def test_load_exchange_map_empty(tmp_path):
    assert load_exchange_map(tmp_path) == {}


def test_load_exchange_map_reads_json(tmp_path):
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "exchange_map.json").write_text(json.dumps({
        "VCB": "HOSE", "SHB": "HNX", "OIL": "UPCOM", "BAD": "unknown"
    }))
    m = load_exchange_map(tmp_path)
    assert m["VCB"] == "HOSE"
    assert m["SHB"] == "HNX"
    assert m["OIL"] == "UPCOM"
    assert "BAD" not in m   # dropped because exchange couldn't be normalised


def test_load_exchange_map_classifier_overrides_json(tmp_path):
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    # JSON says HOSE
    (meta / "exchange_map.json").write_text(json.dumps({"VCB": "HOSE"}))
    # Classifier parquet says HNX — should win (more authoritative)
    pd.DataFrame({
        "ticker": ["VCB", "SHB"],
        "exchange": ["HNX", "HNX"],
    }).to_parquet(meta / "industry_classification.parquet", index=False)
    m = load_exchange_map(tmp_path)
    assert m["VCB"] == "HNX"
    assert m["SHB"] == "HNX"


def test_load_exchange_map_corrupt_json_survives(tmp_path):
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "exchange_map.json").write_text("{not json")
    # Should not raise — just return empty
    assert load_exchange_map(tmp_path) == {}
