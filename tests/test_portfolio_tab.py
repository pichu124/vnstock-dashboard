"""Smoke tests for dashboard.portfolio_tab — the Streamlit UI is tested
manually; this file only covers the non-UI helpers and the import path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_module_imports_without_streamlit():
    """The tab module must be importable even when Streamlit is not
    available — Streamlit is only imported inside render_portfolio_tab."""
    import importlib
    mod = importlib.import_module("dashboard.portfolio_tab")
    assert hasattr(mod, "render_portfolio_tab")
    assert callable(mod.render_portfolio_tab)


def test_load_portfolio_returns_empty_when_file_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio
    assert _load_portfolio(tmp_path) == []


def test_load_portfolio_returns_empty_on_corrupt_file(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "portfolio.json").write_text("{not valid json")
    assert _load_portfolio(tmp_path) == []


def test_save_load_round_trip(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    positions = [
        {"ticker": "VCB", "quantity": 100, "buy_price": 90000,
         "buy_date": "2026-01-15"},
        {"ticker": "FPT", "quantity": 50, "buy_price": 120000,
         "buy_date": "2026-02-01"},
    ]
    _save_portfolio(tmp_path, positions)
    assert _load_portfolio(tmp_path) == positions


def test_save_is_atomic_no_partial_file_on_failure(tmp_path: Path, monkeypatch):
    from dashboard.portfolio_tab import _save_portfolio, _portfolio_path
    # Force os.replace to fail AFTER tmp is written
    import os as _os

    def _fail(_a, _b):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", _fail)
    _save_portfolio(tmp_path, [{"ticker": "VCB"}])

    # Final file must not exist; tmp must be cleaned up
    assert not _portfolio_path(tmp_path).exists()
    assert not any(p.name.startswith("portfolio") and p.suffix.endswith(".tmp")
                   for p in (tmp_path / "_meta").glob("*"))


def test_live_quote_returns_none_when_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    assert _live_quote("XYZ", tmp_path) is None


def test_live_quote_parses_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text(json.dumps({
        "ticker": "VCB", "price": 91000, "ts": "2026-04-22T10:00:00",
    }))
    q = _live_quote("VCB", tmp_path)
    assert q is not None
    assert q["price"] == 91000


def test_live_quote_handles_corrupt_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text("not-json")
    assert _live_quote("VCB", tmp_path) is None


def test_warehouse_last_close_returns_zero_when_no_data(tmp_path: Path):
    from dashboard.portfolio_tab import _warehouse_last_close
    assert _warehouse_last_close("VCB", tmp_path) == 0.0


def test_warehouse_last_close_picks_newest_close(tmp_path: Path):
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from dashboard.portfolio_tab import _warehouse_last_close

    year_dir = tmp_path / "prices" / "ticker=VCB" / "year=2026"
    year_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-02", periods=3, freq="B").date,
        "close": [90.0, 91.5, 92.7],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")
    assert _warehouse_last_close("VCB", tmp_path) == pytest.approx(92.7)
