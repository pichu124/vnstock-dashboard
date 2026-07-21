"""Smoke tests for dashboard.portfolio_tab — the Streamlit UI is tested
manually; this file only covers the non-UI helpers and the import path."""

from __future__ import annotations

import json
from pathlib import Path


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


# ── tripwire ⚠ sai đơn vị giá (review 21/07: tách hàm thuần + nới ngưỡng) ──

def test_unit_suspect_same_day_thousandfold_loss():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", -99.7) is True


def test_unit_suspect_same_day_thousandfold_gain():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", 99_900.0) is True


def test_unit_suspect_legit_bands_not_flagged():
    """HOSE ±7% · HNX ±10% · UPCoM ±15% · chào sàn ±40% · mua đáy −N% đóng
    trần +N% — tất cả là %L/L cùng-ngày HỢP LỆ, không được dán nhãn 'gần như
    chắc chắn sai' như ngưỡng ±7.5% cũ."""
    from dashboard.portfolio_tab import _unit_suspect
    for pct in (6.9, -9.8, 14.9, -15.0, 39.9, -40.0, 42.0, 133.0):
        assert _unit_suspect("2026-07-21", "2026-07-21", pct) is False, pct


def test_unit_suspect_only_fires_on_buy_day():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-18", "2026-07-21", -99.7) is False
    assert _unit_suspect("", "2026-07-21", -99.7) is False
    assert _unit_suspect("2026-07-21", "", -99.7) is False


# ── trục X chart NAV (review 21/07: tách hàm thuần cho nhánh dtick) ────────

def test_nav_xaxis_short_series_forces_daily_dtick():
    from dashboard.portfolio_tab import _nav_xaxis
    x = _nav_xaxis(5)
    assert x["dtick"] == 86_400_000
    assert x["tickformat"] == "%d/%m"
    assert x["rangebreaks"] == [{"bounds": ["sat", "mon"]}]


def test_nav_xaxis_long_series_keeps_auto_ticks():
    from dashboard.portfolio_tab import _nav_xaxis
    assert "dtick" not in _nav_xaxis(11)
    assert _nav_xaxis(11)["tickformat"] == "%d/%m"
