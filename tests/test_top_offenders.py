"""Tests for vnstock_top_offenders — anomaly distribution analyzer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vnstock_top_offenders import (
    TickerStats,
    analyze,
    bulk_suggestions,
    concentration,
    render_table,
)


def _seed_anomalies(warehouse: Path, items: list[dict]) -> None:
    meta = warehouse / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "anomalies.json").write_text(json.dumps({
        "run_at": "2026-04-20T00:00:00Z",
        "tickers_scanned": len({a["ticker"] for a in items}),
        "total": len(items),
        "anomalies": items,
    }))


def _anomaly(ticker, date, kind, severity="warn"):
    return {
        "ticker": ticker,
        "trading_date": date,
        "kind": kind,
        "severity": severity,
        "detail": f"{kind} breach",
    }


# ── analyze ───────────────────────────────────────────────────────────────

def test_analyze_missing_file(tmp_path):
    assert analyze(tmp_path) == []


def test_analyze_empty_list(tmp_path):
    _seed_anomalies(tmp_path, [])
    assert analyze(tmp_path) == []


def test_analyze_ranks_by_total(tmp_path):
    _seed_anomalies(tmp_path, [
        _anomaly("ABC", "2026-04-15", "band", "fail"),
        _anomaly("ABC", "2026-04-16", "ohlc", "warn"),
        _anomaly("XYZ", "2026-04-15", "band", "fail"),
    ])
    stats = analyze(tmp_path)
    assert len(stats) == 2
    assert stats[0].ticker == "ABC"   # 2 anomalies, first
    assert stats[0].total == 2
    assert stats[0].fail == 1
    assert stats[0].warn == 1
    assert stats[0].by_kind == {"band": 1, "ohlc": 1}
    assert stats[1].ticker == "XYZ"


def test_analyze_severity_filter(tmp_path):
    _seed_anomalies(tmp_path, [
        _anomaly("ABC", "2026-04-15", "band", "fail"),
        _anomaly("ABC", "2026-04-16", "ohlc", "warn"),
        _anomaly("XYZ", "2026-04-15", "band", "fail"),
    ])
    stats = analyze(tmp_path, severity_filter="fail")
    assert all(s.warn == 0 for s in stats)
    assert sum(s.fail for s in stats) == 2


def test_analyze_kind_filter(tmp_path):
    _seed_anomalies(tmp_path, [
        _anomaly("ABC", "2026-04-15", "band"),
        _anomaly("ABC", "2026-04-16", "ohlc"),
        _anomaly("XYZ", "2026-04-15", "band"),
    ])
    stats = analyze(tmp_path, kind_filter="band")
    total_band = sum(s.by_kind.get("band", 0) for s in stats)
    assert total_band == 2
    assert all("ohlc" not in s.by_kind for s in stats)


def test_analyze_tracks_date_range(tmp_path):
    _seed_anomalies(tmp_path, [
        _anomaly("ABC", "2026-04-10", "band"),
        _anomaly("ABC", "2026-04-18", "band"),
        _anomaly("ABC", "2026-04-14", "ohlc"),
    ])
    s = analyze(tmp_path)[0]
    assert s.earliest_date == "2026-04-10"
    assert s.latest_date == "2026-04-18"


# ── concentration ─────────────────────────────────────────────────────────

def test_concentration_empty():
    c = concentration([])
    assert c["pattern"] == "empty"
    assert c["total_anomalies"] == 0


def test_concentration_concentrated():
    """10 tickers, first 2 hold 80% → 'concentrated'."""
    stats = [TickerStats(ticker=f"T{i}", total=(80 if i < 2 else 5))
             for i in range(10)]
    c = concentration(stats, top_n=2)
    assert c["pattern"] == "concentrated"
    assert c["top_n_share"] == pytest.approx(160 / (160 + 40), abs=0.01)


def test_concentration_diffuse():
    """20 tickers each with 5 anomalies → top 5 only have 25% → 'moderate'
    (25% borders moderate). Lower top_n to get diffuse."""
    stats = [TickerStats(ticker=f"T{i}", total=5) for i in range(20)]
    c = concentration(stats, top_n=3)
    # top 3 = 15/100 = 15% → diffuse
    assert c["pattern"] == "diffuse"


# ── suggested_action ──────────────────────────────────────────────────────

def test_suggested_action_ohlc_refetch():
    s = TickerStats(ticker="X", total=10, by_kind={"ohlc": 8, "band": 2})
    assert s.suggested_action == "refetch"


def test_suggested_action_gap_accept():
    s = TickerStats(ticker="X", total=5, by_kind={"gap": 5})
    assert s.suggested_action == "accept"


def test_suggested_action_band_review():
    s = TickerStats(ticker="X", total=5, by_kind={"band": 5})
    assert s.suggested_action == "review"


def test_suggested_action_empty():
    s = TickerStats(ticker="X", total=0, by_kind={})
    assert s.suggested_action == "review"


# ── bulk_suggestions ──────────────────────────────────────────────────────

def test_bulk_suggestions_includes_cli(tmp_path):
    stats = [TickerStats(ticker="X", total=10, by_kind={"ohlc": 10})]
    sug = bulk_suggestions(stats, limit=5)
    assert len(sug) == 1
    assert sug[0]["action"] == "refetch"
    assert "python run.py remediate" in sug[0]["cli"]
    assert "--ticker X" in sug[0]["cli"]
    assert "--action refetch" in sug[0]["cli"]


def test_bulk_suggestions_review_uses_grep():
    stats = [TickerStats(ticker="X", total=10, by_kind={"band": 10})]
    sug = bulk_suggestions(stats, limit=5)
    assert sug[0]["action"] == "review"
    assert "grep" in sug[0]["cli"]


# ── render_table ──────────────────────────────────────────────────────────

def test_render_table_non_empty():
    stats = [TickerStats(ticker="ABC", total=5, fail=3, warn=2,
                          by_kind={"band": 5}, latest_date="2026-04-15")]
    out = render_table(stats, limit=10)
    assert "ABC" in out
    assert "Rank" in out   # header
    assert "band:5" in out


def test_render_table_empty():
    assert "no anomalies" in render_table([])


# ── roundtrip ─────────────────────────────────────────────────────────────

def test_ticker_stats_to_dict_includes_suggested_action():
    s = TickerStats(ticker="X", total=5, by_kind={"ohlc": 5})
    d = s.to_dict()
    assert d["suggested_action"] == "refetch"
    assert d["ticker"] == "X"
