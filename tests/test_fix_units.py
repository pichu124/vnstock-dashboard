"""Tests for vnstock_fix_units — warehouse unit-mismatch repair."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_fix_units import (
    NEIGHBOR_CAP,
    OHLC_COLS,
    RATIO_THRESHOLD,
    RAW_VND_THRESHOLD,
    UnitFix,
    _detect_in_ticker,
    apply_fixes,
    run,
    scan,
)


def _make_bars(dates, closes, volumes):
    assert len(dates) == len(closes) == len(volumes)
    return pd.DataFrame({
        "time": pd.to_datetime(dates).date,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": volumes,
    })


# ── detection ──────────────────────────────────────────────────────────────


def test_detect_flags_vol_zero_bar_with_raw_vnd_price():
    df = _make_bars(
        ["2026-04-10", "2026-04-11", "2026-04-14", "2026-04-15", "2026-04-16"],
        [4.8, 5.0, 4200.0, 4.9, 5.1],
        [1000, 500, 0, 2000, 1500],
    )
    fixes = _detect_in_ticker("UPH", df)
    assert len(fixes) == 1
    f = fixes[0]
    assert f.ticker == "UPH"
    assert f.time == "2026-04-14"
    assert f.close_before == 4200.0
    assert f.close_after == pytest.approx(4.2)
    assert f.neighbor_median == pytest.approx(4.95, rel=0.05)


def test_detect_flags_traded_bar_with_raw_vnd_price():
    # API can return raw VND even on bars with volume > 0 (VGT 2026-04-15)
    df = _make_bars(
        ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"],
        [12.4, 12.4, 12300.0, 12.2, 12.3],
        [929700, 0, 454000, 0, 489800],   # candidate has volume > 0
    )
    fixes = _detect_in_ticker("VGT", df)
    assert len(fixes) == 1
    assert fixes[0].time == "2026-04-15"
    assert fixes[0].close_after == pytest.approx(12.3)


def test_detect_skips_when_close_below_raw_vnd_threshold():
    df = _make_bars(
        ["2026-04-10", "2026-04-14"],
        [4.8, 999.0],
        [1000, 0],
    )
    assert _detect_in_ticker("AAA", df) == []


def test_detect_skips_when_neighbors_also_high_priced():
    # Looks like a legitimate high-priced instrument (e.g. index mirror)
    df = _make_bars(
        ["2026-04-10", "2026-04-11", "2026-04-14", "2026-04-15"],
        [1400.0, 1410.0, 1500.0, 1420.0],
        [0, 100, 0, 200],
    )
    assert _detect_in_ticker("XXX", df) == []


def test_detect_skips_when_ratio_below_threshold():
    # close=4000, neighbors=500 → ratio=8, under the 10× rule
    df = _make_bars(
        ["2026-04-10", "2026-04-11", "2026-04-14", "2026-04-15"],
        [450.0, 500.0, 4000.0, 520.0],
        [1000, 500, 0, 1000],
    )
    # Even though neighbors < NEIGHBOR_CAP (500) is borderline, the ratio guard
    # should still reject this one. Adjust to clearly under-ratio:
    fixes = _detect_in_ticker("AAA", df)
    # 4000 vs median ~500 → ratio = 8 < 10 → expect no fix
    assert fixes == []


def test_detect_uses_only_sensible_neighbors_for_median():
    # Two raw-VND spikes near each other — each candidate should be excluded
    # from the other's median so we don't get a poisoned baseline.
    df = _make_bars(
        ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16"],
        [4.8, 4200.0, 4.9, 4500.0, 5.1],
        [1000, 0, 800, 0, 1500],
    )
    fixes = _detect_in_ticker("UPH", df)
    assert len(fixes) == 2
    for f in fixes:
        assert f.neighbor_median < 10   # computed from the legit ~5 prices


def test_detect_handles_long_closure_with_only_fixed_neighbors():
    # BBC scenario: after the 1st pass fixed Apr 14-20, Apr 21 must still be
    # detectable on a 2nd pass even though every vol>0 trading day is
    # outside the ±10-day window (data cutoff in mid-holiday).
    df = _make_bars(
        ["2026-04-16", "2026-04-17", "2026-04-20", "2026-04-21"],
        [90.9, 90.9, 90.9, 90900.0],   # first 3 already fixed, last still raw
        [0, 0, 0, 0],                   # entire holiday, no trades
    )
    fixes = _detect_in_ticker("BBC", df)
    assert len(fixes) == 1
    assert fixes[0].time == "2026-04-21"
    assert fixes[0].close_after == pytest.approx(90.9)


def test_detect_handles_empty_and_missing_columns():
    assert _detect_in_ticker("X", pd.DataFrame()) == []
    assert _detect_in_ticker("X", pd.DataFrame({"foo": [1]})) == []


# ── apply_fixes (file-level rewrite) ───────────────────────────────────────


def _write_ticker_parquet(root: Path, ticker: str, year: int, df: pd.DataFrame):
    out = root / "prices" / f"ticker={ticker}" / f"year={year}"
    out.mkdir(parents=True, exist_ok=True)
    # Match warehouse: OHLC as float32, volume int64, no ticker/year columns
    arrow = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(arrow, out / "part-0.parquet", compression="snappy")


def test_apply_fixes_rewrites_parquet_in_place(tmp_path: Path):
    df = _make_bars(
        ["2026-04-10", "2026-04-14", "2026-04-15"],
        [4.8, 4200.0, 5.0],
        [1000, 0, 1000],
    ).astype({"open": "float32", "high": "float32", "low": "float32",
              "close": "float32", "volume": "int64"})
    _write_ticker_parquet(tmp_path, "UPH", 2026, df)

    fix = UnitFix(
        ticker="UPH", year=2026, time="2026-04-14",
        close_before=4200.0, close_after=4.2, neighbor_median=4.9,
    )
    updated = apply_fixes(tmp_path, [fix])
    assert updated == 1

    # Reload and confirm the bar was rescaled across all OHLC columns
    out_file = tmp_path / "prices" / "ticker=UPH" / "year=2026" / "part-0.parquet"
    back = pd.read_parquet(out_file)
    row = back[pd.to_datetime(back["time"]).dt.date.astype(str) == "2026-04-14"].iloc[0]
    for col in OHLC_COLS:
        assert row[col] == pytest.approx(4.2, rel=1e-3)


def test_apply_fixes_is_noop_on_empty_input(tmp_path: Path):
    assert apply_fixes(tmp_path, []) == 0


# ── end-to-end run() ───────────────────────────────────────────────────────


def test_run_dry_run_does_not_modify_files(tmp_path: Path):
    df = _make_bars(
        ["2026-04-10", "2026-04-14", "2026-04-15"],
        [4.8, 4200.0, 5.0],
        [1000, 0, 1000],
    ).astype({"open": "float32", "high": "float32", "low": "float32",
              "close": "float32", "volume": "int64"})
    _write_ticker_parquet(tmp_path, "UPH", 2026, df)

    report = run(tmp_path, dry_run=True)
    assert len(report.fixes) == 1

    back = pd.read_parquet(
        tmp_path / "prices" / "ticker=UPH" / "year=2026" / "part-0.parquet"
    )
    bad_row = back[pd.to_datetime(back["time"]).dt.date.astype(str) == "2026-04-14"].iloc[0]
    # Still the original raw-VND value since dry_run=True
    assert bad_row["close"] == pytest.approx(4200.0, rel=1e-3)


def test_run_applies_and_returns_report(tmp_path: Path):
    df = _make_bars(
        ["2026-04-10", "2026-04-14", "2026-04-15"],
        [4.8, 4200.0, 5.0],
        [1000, 0, 1000],
    ).astype({"open": "float32", "high": "float32", "low": "float32",
              "close": "float32", "volume": "int64"})
    _write_ticker_parquet(tmp_path, "UPH", 2026, df)

    report = run(tmp_path, dry_run=False)
    assert len(report.fixes) == 1
    assert report.ticker_count == 1

    back = pd.read_parquet(
        tmp_path / "prices" / "ticker=UPH" / "year=2026" / "part-0.parquet"
    )
    fixed_row = back[pd.to_datetime(back["time"]).dt.date.astype(str) == "2026-04-14"].iloc[0]
    assert fixed_row["close"] == pytest.approx(4.2, rel=1e-3)


def test_run_ticker_filter_isolates_scan(tmp_path: Path):
    # Two tickers, both have a bad bar; filter should restrict to one.
    for t in ("UPH", "UPS"):
        df = _make_bars(
            ["2026-04-10", "2026-04-14", "2026-04-15"],
            [4.8, 4200.0, 5.0],
            [1000, 0, 1000],
        ).astype({"open": "float32", "high": "float32", "low": "float32",
                  "close": "float32", "volume": "int64"})
        _write_ticker_parquet(tmp_path, t, 2026, df)

    report = scan(tmp_path, tickers=["UPH"])
    assert report.ticker_count == 1
    assert report.fixes[0].ticker == "UPH"
