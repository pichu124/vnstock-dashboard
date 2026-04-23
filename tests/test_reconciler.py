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


def test_wss_partial_miss_downgraded_from_fail_to_warn(tmp_path):
    """Rolled captured < 50% of API volume → rolled_close is a random
    intraday tick, not the session close. Don't flag as fail even if
    close drift is huge. This is the PNJ 2026-04-20 case: rolled
    captured 4.5% of volume, showing 46% close drift — which is infra
    noise, not a data bug."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "PNJ", d, close=76.67, volume=1_870_506)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "PNJ",
        "close": 112.5,                # huge apparent drift
        "volume": 83_284,              # only 4.5% of API volume
        "open": 112.5, "high": 112.5, "low": 112.5,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, "wss_partial_miss must not escalate to fail"
    assert report.warn >= 1, "significant close drift should still surface as warn"
    disc = [d for d in report.discrepancies if d.ticker == "PNJ"]
    assert disc, "PNJ row must be reported"
    assert "wss_partial_miss" in disc[0].reason
    assert disc[0].severity == "warn"


def test_wss_partial_miss_stays_ok_when_close_within_tolerance(tmp_path):
    """If WSS captured little volume but happened to land on a tick near
    the real close, the row is silently OK — no noise."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VIC", d, close=191.0, volume=5_425_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VIC",
        "close": 190.9,                # within tolerance
        "volume": 902_582,             # 16.6% of API — under floor
        "open": 190.9, "high": 190.9, "low": 190.9,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0
    # No discrepancy recorded for ok rows
    assert not any(d.ticker == "VIC" for d in report.discrepancies)


def test_wss_atc_miss_detected_at_75pct_capture(tmp_path):
    """Realistic ATC (auction-at-close) miss: WSS caught most of the
    session but dropped the closing auction, leaving rolled_close as
    the pre-ATC tick. HPT 2026-04-20 had ~75% coverage and 3.70% drift —
    must be classified as wss_partial_miss, not a real fail."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "HPT", d, close=27.0, volume=4000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "HPT",
        "close": 28.0,                 # pre-ATC tick
        "volume": 3000,                # 75% captured — above the old 50% floor
        "open": 28.0, "high": 28.0, "low": 28.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, "ATC miss must not escalate to fail"
    disc = [d for d in report.discrepancies if d.ticker == "HPT"]
    assert disc and "wss_partial_miss" in disc[0].reason


def test_reconciler_respects_anomaly_whitelist(tmp_path):
    """User accepting a (ticker, date) via `remediate --action accept`
    should stop BOTH the anomaly scan AND the reconciler from re-flagging
    it. Otherwise the operator has to accept twice for one event."""
    from vnstock_remediate import add_to_whitelist

    d = date(2026, 4, 15)

    # Real genuine drift — without the whitelist, this should fail.
    _seed_warehouse(tmp_path, "SBT", d, close=20.66, volume=500_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d), "ticker": "SBT",
        "close": 21.9, "volume": 500_000,     # both have vol → real drift
        "open": 21.9, "high": 21.9, "low": 21.9,
    }])

    # 1) Without whitelist entry — expect fail (close drift 6%)
    r = reconcile(tmp_path, dates=[d])
    assert r.fail >= 1, "genuine drift must fire before whitelist"

    # 2) Whitelist the entry and re-run — must NOT fail anymore
    add_to_whitelist("SBT", d, kind="band", warehouse=tmp_path,
                      note="WSS corrupted rolled")
    r2 = reconcile(tmp_path, dates=[d])
    assert r2.fail == 0, "whitelisted entry must be skipped by reconciler"
    assert r2.ok >= 1


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
