"""Tests for vnstock_memory — recommendation lifecycle helpers."""

from __future__ import annotations

import pytest

import vnstock_memory as mem


@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    """Point the memory store at a throwaway SQLite file."""
    monkeypatch.setattr(mem, "DB_PATH", tmp_path / "mem.db")
    mem.init_db()
    yield


def test_stale_close_records_null_pnl_and_drops_from_open(_isolated_db):
    rec_id = mem.save_recommendation(
        ticker="CFPT2528", action="buy", entry=1.0, tp=1.2, sl=0.9,
        horizon_days=5,
    )
    # Open before closing.
    assert any(r["ticker"] == "CFPT2528" for r in mem.open_recommendations())

    # Stale close: no fetchable price → exit_price None, pnl stays NULL so it
    # doesn't pollute win-rate stats, and it leaves the open list.
    mem.close_recommendation(
        rec_id, exit_price=None, hit_target="stale", notes="no price history",
    )
    assert not any(r["ticker"] == "CFPT2528" for r in mem.open_recommendations())

    closed = mem.recent_closed_recommendations(limit=10)
    row = next(r for r in closed if r["ticker"] == "CFPT2528")
    assert row["hit_target"] == "stale"
    assert row["exit_price"] is None
    assert row["pnl_pct"] is None


def test_priced_close_still_computes_pnl(_isolated_db):
    rec_id = mem.save_recommendation(
        ticker="FPT", action="buy", entry=100.0, tp=110.0, sl=95.0,
        horizon_days=5,
    )
    mem.close_recommendation(rec_id, exit_price=110.0, hit_target="tp")
    row = next(
        r for r in mem.recent_closed_recommendations(limit=10)
        if r["ticker"] == "FPT"
    )
    assert row["pnl_pct"] == pytest.approx(10.0)
