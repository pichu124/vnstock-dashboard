"""Tests for vnstock_anomaly — regulatory + statistical anomaly detection."""

from __future__ import annotations

import pandas as pd
import pytest

from vnstock_anomaly import (
    BAND_PCT,
    _is_stock,
    band_for,
    scan_ticker,
)


# ── non-stock filter ───────────────────────────────────────────────────────

def test_is_stock_accepts_regular_tickers():
    for t in ["VCB", "FPT", "HPG", "VIC", "BID"]:
        assert _is_stock(t) is True


def test_is_stock_rejects_covered_warrants():
    for t in ["CVRE2410", "CVNM2101", "CFPT2409"]:
        assert _is_stock(t) is False


def test_is_stock_rejects_old_bonds():
    for t in ["HDB124001", "VBA121033", "VCB12001"]:
        assert _is_stock(t) is False


def test_is_stock_rejects_futures():
    for t in ["VN30F2404", "VN30F2502", "BVBF2404"]:
        assert _is_stock(t) is False


def test_is_stock_rejects_indices():
    for t in ["VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOM"]:
        assert _is_stock(t) is False


def test_is_stock_rejects_hnx_internal_derivatives():
    # HNX internal codes for index-derived futures start with digits.
    # The vnstock API surfaces these as "ticker" folders but they are not
    # actual equities and have no company info.
    for t in ["41I1F7000", "41I1G2000", "41I1FB000", "41I1G4000"]:
        assert _is_stock(t) is False


def test_is_stock_handles_whitespace_and_case():
    assert _is_stock("  vcb  ") is True
    assert _is_stock("  vn30f2404  ") is False


def _make_series(dates, closes, volumes=None, highs=None, lows=None, opens=None):
    n = len(dates)
    volumes = volumes if volumes is not None else [1_000_000] * n
    highs = highs if highs is not None else [c * 1.005 for c in closes]
    lows = lows if lows is not None else [c * 0.995 for c in closes]
    opens = opens if opens is not None else closes
    return pd.DataFrame({
        "time": pd.to_datetime(dates),
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes,
    })


# ── band lookup ─────────────────────────────────────────────────────────────

def test_band_for_known_exchange():
    ex, pct = band_for("VCB", {"VCB": "HOSE"})
    assert ex == "HOSE"
    assert pct == BAND_PCT["HOSE"]


def test_band_for_unknown_defaults_to_loosest():
    ex, pct = band_for("XYZ", {})
    assert ex == "_UNKNOWN"
    assert pct == BAND_PCT["UPCOM"]


# ── price band breach ──────────────────────────────────────────────────────

def test_hose_close_breach_flagged():
    # previous close 100, next close 108 → +8% breaches HOSE ±7%
    df = _make_series(["2026-04-15", "2026-04-16"], [100.0, 108.0])
    out = scan_ticker(df, "VCB", exchange="HOSE")
    band = [a for a in out if a.kind == "band"]
    assert len(band) == 1
    assert band[0].severity in ("warn", "fail")
    assert band[0].metrics["exchange"] == "HOSE"


def test_hose_close_within_band_not_flagged():
    # +6.5% < band+tolerance (7.3%) → OK
    df = _make_series(["2026-04-15", "2026-04-16"], [100.0, 106.5])
    out = scan_ticker(df, "VCB", exchange="HOSE")
    assert not any(a.kind == "band" for a in out)


def test_upcom_band_wider():
    # +11% would breach HOSE but is within UPCOM 15% band
    df = _make_series(["2026-04-15", "2026-04-16"], [100.0, 111.0])
    assert any(a.kind == "band" for a in scan_ticker(df, "X", exchange="HOSE"))
    assert not any(a.kind == "band" for a in scan_ticker(df, "X", exchange="UPCOM"))


def test_band_severity_scales_with_breach_magnitude():
    # +15% on HOSE is ~2x the band → should be "fail"
    df = _make_series(["2026-04-15", "2026-04-16"], [100.0, 115.0])
    out = [a for a in scan_ticker(df, "X", exchange="HOSE") if a.kind == "band"]
    assert out[0].severity == "fail"


# ── OHLC outside band (print errors) ───────────────────────────────────────

def test_high_outside_band_flagged():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 100.0],
        highs=[101.0, 120.0],     # +20% high on HOSE → flag
    )
    out = [a for a in scan_ticker(df, "X", exchange="HOSE") if a.kind == "ohlc"]
    assert any("high" in a.detail for a in out)


# ── calendar gap ───────────────────────────────────────────────────────────

def test_gap_over_threshold_flagged():
    df = _make_series(
        ["2026-01-15", "2026-02-01"],   # 17-day gap
        [100.0, 101.0],
    )
    out = scan_ticker(df, "X", exchange="HOSE")
    gaps = [a for a in out if a.kind == "gap"]
    assert len(gaps) == 1
    assert gaps[0].metrics["gap_days"] == 17


def test_normal_weekend_gap_not_flagged():
    # Friday -> Monday (3 days) is below threshold
    df = _make_series(
        ["2026-04-17", "2026-04-20"],
        [100.0, 101.0],
    )
    out = scan_ticker(df, "X", exchange="HOSE")
    assert not any(a.kind == "gap" for a in out)


# ── volume spike ───────────────────────────────────────────────────────────

def test_volume_spike_requires_dual_gate():
    # 25 boring days at 1M, then one day at 20M → factor 20x
    dates = pd.bdate_range("2026-03-01", periods=26)
    volumes = [1_000_000] * 25 + [20_000_000]
    closes = [100.0] * 26
    df = _make_series(list(dates), closes, volumes=volumes)
    out = scan_ticker(df, "X", exchange="HOSE")
    spikes = [a for a in out if a.kind == "vol_spike"]
    assert len(spikes) == 1
    assert spikes[0].metrics["factor"] >= 5.0


def test_small_volume_variation_not_flagged():
    dates = pd.bdate_range("2026-03-01", periods=26)
    volumes = [1_000_000 + 50_000 * (i % 3) for i in range(26)]
    closes = [100.0] * 26
    df = _make_series(list(dates), closes, volumes=volumes)
    out = scan_ticker(df, "X", exchange="HOSE")
    assert not any(a.kind == "vol_spike" for a in out)


# ── zero-volume price move ─────────────────────────────────────────────────

def test_zero_volume_with_price_move_flagged():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 103.0],
        volumes=[1_000_000, 0],
    )
    out = [a for a in scan_ticker(df, "X", exchange="HOSE") if a.kind == "zero_vol_move"]
    assert len(out) == 1
    assert out[0].severity == "fail"


def test_zero_volume_flat_price_not_flagged():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 100.0],
        volumes=[1_000_000, 0],
    )
    assert not any(a.kind == "zero_vol_move" for a in scan_ticker(df, "X", exchange="HOSE"))


# ── edge cases ─────────────────────────────────────────────────────────────

def test_empty_df_returns_empty():
    assert scan_ticker(pd.DataFrame(), "X") == []


# ── corp-action-aware skipping ─────────────────────────────────────────────

def _make_events(rows):
    return pd.DataFrame(rows, columns=["ticker", "ex_date", "type",
                                         "cash_amount", "ratio", "raw"])


def test_zero_vol_move_skipped_on_cash_ex_date():
    # prev close 100, today close 95 (=-5% after 5.0 cash div), volume=0
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 95.0],
        volumes=[1_000_000, 0],
    )
    events = _make_events([
        {"ticker": "X", "ex_date": "2026-04-16", "type": "cash",
         "cash_amount": 5.0, "ratio": None, "raw": ""},
    ])
    out = scan_ticker(df, "X", exchange="HOSE", events=events)
    assert not any(a.kind == "zero_vol_move" for a in out)


def test_zero_vol_move_still_flagged_without_event():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 95.0],
        volumes=[1_000_000, 0],
    )
    out = scan_ticker(df, "X", exchange="HOSE")
    assert any(a.kind == "zero_vol_move" for a in out)


def test_band_skipped_on_split_ex_date():
    # 2-for-1 split: close goes 200 → 100 (-50%). Without events this trips
    # band + ohlc; with split event on that date, both should be suppressed.
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[200.0, 100.0],
    )
    events = _make_events([
        {"ticker": "X", "ex_date": "2026-04-16", "type": "split",
         "cash_amount": None, "ratio": 2.0, "raw": ""},
    ])
    out = scan_ticker(df, "X", exchange="HOSE", events=events)
    assert not any(a.kind == "band" for a in out)
    assert not any(a.kind == "ohlc" for a in out)


def test_band_still_flagged_without_split_event():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[200.0, 100.0],
    )
    out = scan_ticker(df, "X", exchange="HOSE")
    assert any(a.kind == "band" for a in out)


def test_empty_events_df_behaves_like_no_events():
    df = _make_series(
        ["2026-04-15", "2026-04-16"],
        closes=[100.0, 95.0],
        volumes=[1_000_000, 0],
    )
    out = scan_ticker(df, "X", exchange="HOSE",
                      events=pd.DataFrame(columns=["ticker", "ex_date", "type"]))
    assert any(a.kind == "zero_vol_move" for a in out)


def test_lookback_limits_scan():
    dates = pd.bdate_range("2026-01-01", periods=50)
    closes = [100.0] * 49 + [120.0]   # breach on last bar only
    df = _make_series(list(dates), closes)
    # Lookback=5 still catches the last-bar breach
    out = [a for a in scan_ticker(df, "X", exchange="HOSE", lookback=5) if a.kind == "band"]
    assert len(out) == 1
    # Lookback=1 sees only the last bar; still catches it (but if we asked for
    # just the oldest row by tailing, no breach). Sanity check the tail logic:
    out2 = [a for a in scan_ticker(df, "X", exchange="HOSE", lookback=1) if a.kind == "band"]
    assert len(out2) == 1
