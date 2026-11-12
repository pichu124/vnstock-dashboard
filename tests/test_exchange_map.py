"""Tests for vnstock_exchange_map."""

from __future__ import annotations

import importlib.util
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


# ── build_exchange_map (thế hệ 6: một lệnh Reference().equity.list()) ──────

class _FakeEquity:
    def __init__(self, df=None, exc=None):
        self.df, self.exc, self.calls = df, exc, []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.df


def _patch_reference(monkeypatch, equity):
    import vnstock

    class _Ref:
        def __init__(self, *a, **k):
            self.equity = equity

    monkeypatch.setattr(vnstock, "Reference", _Ref)


_needs_vnstock = pytest.mark.skipif(importlib.util.find_spec("vnstock") is None,
                                    reason="cần vnstock thế hệ 6 (CI cài tối thiểu, không có vnstock)")


@_needs_vnstock
def test_build_exchange_map_reads_exchange_column_of_equity_list(tmp_path, monkeypatch):
    from vnstock_exchange_map import build_exchange_map
    eq = _FakeEquity(pd.DataFrame({
        "symbol": ["VCB", "shb", "OIL", "XYZ"],
        "exchange": ["HOSE", "HNX", "UPCOM", None],
        "organ_name": ["a", "b", "c", "d"],
    }))
    _patch_reference(monkeypatch, eq)

    m = build_exchange_map(tmp_path)

    assert m == {"VCB": "HOSE", "SHB": "HNX", "OIL": "UPCOM"}
    assert eq.calls == [{}]          # một lệnh, không lọc sàn, không tên nguồn
    on_disk = json.loads((tmp_path / "_meta" / "exchange_map.json").read_text())
    assert on_disk == m


@_needs_vnstock
def test_build_exchange_map_vnstock_error_keeps_existing_file(tmp_path, monkeypatch):
    from vnstock.errors import InputError
    from vnstock_exchange_map import build_exchange_map
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "exchange_map.json").write_text(json.dumps({"VCB": "HOSE"}))
    _patch_reference(monkeypatch, _FakeEquity(
        exc=InputError("Chưa chọn nguồn", code="VNSTOCK_INPUT_SOURCE")))

    assert build_exchange_map(tmp_path) == {}
    assert json.loads((meta / "exchange_map.json").read_text()) == {"VCB": "HOSE"}


@_needs_vnstock
def test_build_exchange_map_empty_listing_writes_nothing(tmp_path, monkeypatch):
    from vnstock_exchange_map import build_exchange_map
    _patch_reference(monkeypatch, _FakeEquity(pd.DataFrame()))

    assert build_exchange_map(tmp_path) == {}
    assert not (tmp_path / "_meta" / "exchange_map.json").exists()
