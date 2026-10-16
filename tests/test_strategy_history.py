"""Tests for vnstock_strategy._load_history — CLI-safe warehouse reads.

Regression: the dashboard loader is @st.cache_data-decorated and fails outside a
Streamlit session, so reconcile/backtest run from the CLI/brief pipeline used to
get an empty frame and leave graded recs stuck open as zombies.
"""

from __future__ import annotations

import sys
import types

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import vnstock_strategy as vs


def _write_ticker(prices_dir, ticker: str, rows: list[dict]):
    d = prices_dir / f"ticker={ticker.upper()}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False),
                   str(d / "p.parquet"))


def test_load_history_from_parquet_reads_and_normalises(tmp_path):
    # Stored in raw VND (e.g. 25,000) → must come back in thousands (25.0).
    _write_ticker(tmp_path, "ACB", [
        {"time": pd.Timestamp("2026-06-04"), "open": 25000.0, "high": 25500.0,
         "low": 24800.0, "close": 25000.0, "volume": 1_000_000},
        {"time": pd.Timestamp("2026-06-05"), "open": 25000.0, "high": 26000.0,
         "low": 24900.0, "close": 25800.0, "volume": 1_200_000},
    ])
    df = vs._load_history_from_parquet("ACB", days=0, prices_dir=tmp_path)
    assert not df.empty and len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(25.8)   # 25,800 → 25.8
    assert df["time"].is_monotonic_increasing


def test_load_history_from_parquet_missing_ticker(tmp_path):
    assert vs._load_history_from_parquet("NOPE", days=0, prices_dir=tmp_path).empty


def _pin_streamlit_session(monkeypatch):
    """Loader dashboard chỉ dùng TRONG phiên Streamlit. Không ghim thì kết quả
    tuỳ thứ tự chạy: `tests/test_dashboard.py` gắn MagicMock vào
    `sys.modules["streamlit"]` ở cấp module ⇒ `runtime.exists()` truthy cho cả
    phiên pytest, còn chạy riêng file này thì False."""
    monkeypatch.setattr(vs, "_in_streamlit_session", lambda: True)


def test_load_history_falls_back_when_dashboard_loader_empty(monkeypatch):
    _pin_streamlit_session(monkeypatch)
    fake = types.ModuleType("vnstock_dashboard")
    fake.load_price_history = lambda ticker, days=0: pd.DataFrame()  # empty / fails
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", fake)
    sentinel = pd.DataFrame({"time": [pd.Timestamp("2026-06-05")], "close": [25.0]})
    monkeypatch.setattr(vs, "_load_history_from_parquet", lambda t, d: sentinel)
    assert vs._load_history("ACB", 15) is sentinel


def test_load_history_uses_dashboard_loader_when_available(monkeypatch):
    _pin_streamlit_session(monkeypatch)
    df = pd.DataFrame({"time": [pd.Timestamp("2026-06-05")], "close": [25.0]})
    fake = types.ModuleType("vnstock_dashboard")
    fake.load_price_history = lambda ticker, days=0: df
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", fake)

    def _boom(t, d):
        raise AssertionError("should not fall back when loader returns data")
    monkeypatch.setattr(vs, "_load_history_from_parquet", _boom)
    assert vs._load_history("ACB", 15) is df
