"""Tests for vnstock_reconciler cross-reference logic."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from vnstock_reconciler import _classify, _normalise_units, _pct_diff, reconcile


def test_pct_diff_symmetric():
    assert _pct_diff(100.0, 101.0) == 1.0
    assert _pct_diff(100.0, 99.0) == 1.0


def test_pct_diff_nan_and_zero():
    assert _pct_diff(None, 10) is None
    assert _pct_diff(10, None) is None
    assert _pct_diff(0.0, 5.0) is None


def test_classify_ok_within_tolerance():
    sev, _ = _classify(close_diff=0.1, volume_diff=1.0)
    assert sev == "ok"


def test_classify_warn_on_volume_only_when_enabled():
    # Default: volume ignored
    sev, reason = _classify(close_diff=0.1, volume_diff=10.0)
    assert sev == "ok"
    assert "volume drift" not in reason

    # Enabled: volume pushes to warn
    sev, reason = _classify(close_diff=0.1, volume_diff=10.0, check_volume=True)
    assert sev == "warn"
    assert "volume drift" in reason


def test_classify_volume_fail_only_when_enabled():
    # Default: 200% volume drift is ignored
    sev, _ = _classify(close_diff=0.1, volume_diff=200.0)
    assert sev == "ok"

    # Enabled: 200% volume drift → fail
    sev, _ = _classify(close_diff=0.1, volume_diff=200.0, check_volume=True)
    assert sev == "fail"


def test_classify_fail_on_close():
    sev, reason = _classify(close_diff=5.0, volume_diff=None)
    assert sev == "fail"
    assert "close drift" in reason


def test_classify_close_fail_always_wins():
    # Even with volume checking enabled, close fail takes priority
    sev, _ = _classify(close_diff=5.0, volume_diff=10.0, check_volume=True)
    assert sev == "fail"


# ── unit normalisation (per-row, close > 500 → /1000) ─────────────────────

def test_normalise_rescales_rolled_row_by_row():
    """Rolled stores raw VND (7120). Every row > 500 is divided by 1000."""
    api = pd.DataFrame({
        "ticker": ["AAA", "FPT", "VCB"],
        "close": [7.12, 120.0, 77.7],
    })
    rolled = pd.DataFrame({
        "ticker": ["AAA", "FPT", "VCB"],
        "close": [7120.0, 120000.0, 77700.0],
    })
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(rolled_out["close"]) == [7.12, 120.0, 77.7]
    # API values were all below threshold → untouched
    assert list(api_out["close"]) == [7.12, 120.0, 77.7]


def test_normalise_handles_mixed_units_in_same_frame():
    """Warehouse has mixed units on different tickers — each row treated
    on its own merits."""
    api = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "close": [7.12, 5600.0, 14.5],   # second row is raw VND
    })
    rolled = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "close": [7120.0, 5600.0, 14500.0],   # first + third raw VND
    })
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(api_out["close"]) == [7.12, 5.6, 14.5]
    assert list(rolled_out["close"]) == [7.12, 5.6, 14.5]


def test_normalise_noop_when_all_rows_under_threshold():
    api = pd.DataFrame({"ticker": ["AAA"], "close": [7.12]})
    rolled = pd.DataFrame({"ticker": ["AAA"], "close": [7.15]})
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is False
    assert list(rolled_out["close"]) == [7.15]


def test_normalise_handles_empty_frames():
    empty = pd.DataFrame(columns=["ticker", "close"])
    one = pd.DataFrame({"ticker": ["X"], "close": [7.12]})
    api_out, rolled_out, rescaled = _normalise_units(empty, one)
    assert rescaled is False
    api_out, rolled_out, rescaled = _normalise_units(one, empty)
    assert rescaled is False


def test_normalise_handles_only_api_in_raw_vnd():
    """If only one side has raw VND, only that side gets rescaled."""
    api = pd.DataFrame({"ticker": ["X"], "close": [7120.0]})
    rolled = pd.DataFrame({"ticker": ["X"], "close": [7.12]})
    api_out, rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    assert list(api_out["close"]) == [7.12]
    assert list(rolled_out["close"]) == [7.12]


# ── Smart WSS-miss detection (Option E) ────────────────────────────────────

def _seed_warehouse(path: Path, ticker: str, d: date, close: float, volume: int):
    year_dir = path / "prices" / f"ticker={ticker}" / f"year={d.year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp(d)],
        "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [volume],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")


def _seed_rolled(path: Path, d: date, rows: list[dict]):
    live_dir = path / "_live"
    live_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    df = pd.DataFrame(rows)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   live_dir / f"bars_{d.isoformat()}.parquet")


def test_wss_miss_counted_as_missing_not_fail(tmp_path):
    """When rolled_volume=0 AND api_volume>0, treat as missing_in_rolled
    not fail. This is the Option E fix: WSS didn't capture the session,
    so the close comparison is meaningless."""
    d = date(2026, 4, 20)

    # API has real data
    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=1_000_000)

    # Rolled has a degenerate row: volume=0, stale close
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 75.0,                # stale, differs from API
        "volume": 0,                  # ← the signal
        "open": 75.0, "high": 75.0, "low": 75.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, f"WSS-miss should not be a fail, got {report.fail}"
    assert report.missing_in_rolled >= 1, \
        f"WSS-miss should increment missing_in_rolled, got {report.missing_in_rolled}"


def test_real_drift_still_flagged_when_both_sides_have_volume(tmp_path):
    """A genuine close drift (both sides have volume > 0) still trips fail."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=1_000_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 85.0,                # +9.4% close drift
        "volume": 500_000,            # non-zero rolled volume
        "open": 85.0, "high": 85.0, "low": 85.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail >= 1 or report.warn >= 1, \
        "A real 9.4% close drift must still surface"


def test_both_zero_volume_not_counted_as_wss_miss(tmp_path):
    """If api_volume is ALSO 0 (holiday / halted ticker), don't reclassify
    as WSS-miss — nothing to miss. Goes through normal classification."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=0)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 77.7,
        "volume": 0,
        "open": 77.7, "high": 77.7, "low": 77.7,
    }])

    report = reconcile(tmp_path, dates=[d])
    # No fail expected — close matches — but also not a missing_in_rolled
    # because the premise "api_volume > 0" doesn't hold.
    assert report.fail == 0
    assert report.ok >= 1
