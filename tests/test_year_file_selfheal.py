"""Self-heal against Dropbox conflicted copies in warehouse year dirs.

2026-07-07 incident: Dropbox spawned "conflicted copy" parquet files next to
prices.parquet during the 2-machine migration. The updater then wrote new bars
into the conflicted file (glob order) while loaders read the other → warehouse
looked permanently stale despite successful syncs.

The fix (mirrored in vnstock_updater + vnstock_rollup):
  * _read_year merges EVERY parquet in the year dir (newest mtime wins on
    duplicate dates)
  * _write_year always writes the canonical prices.parquet and deletes the
    other files afterwards — each sync cycle converges the dir back to 1 file.

Tested through vnstock_rollup (importable without the vnstock package; the
updater carries an identical copy of both helpers).
"""
from __future__ import annotations

import os
import time as _time
from pathlib import Path

import pandas as pd
import pytest

from vnstock_rollup import _read_year, _write_year


def _mk(ydir: Path, name: str, dates: list[str], closes: list[float],
        mtime_offset: float = 0.0) -> Path:
    ydir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": pd.to_datetime(dates),
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes,
        "volume": [1_000_000] * len(dates),
    })
    path = ydir / name
    df.to_parquet(path, index=False)
    ts = _time.time() + mtime_offset
    os.utime(path, (ts, ts))
    return path


def test_read_year_merges_all_files_newest_mtime_wins(tmp_path):
    tdir = tmp_path / "ticker=FPT"
    ydir = tdir / "year=2026"
    # stale canonical file: through 07-03 (older mtime)
    _mk(ydir, "prices.parquet",
        ["2026-07-02", "2026-07-03"], [72.5, 72.3], mtime_offset=-100)
    # conflicted copy holding the fresh bars, 07-03 refetched with a new value
    _mk(ydir, "x (conflicted copy 2026-07-06).parquet",
        ["2026-07-03", "2026-07-06", "2026-07-07"], [72.4, 73.0, 73.2])

    df = _read_year(tdir, 2026)
    assert [str(d) for d in df["time"]] == \
        ["2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"]
    # duplicate 07-03: the newer file's value wins
    assert float(df.loc[df["time"].astype(str) == "2026-07-03", "close"].iloc[0]) \
        == pytest.approx(72.4)


def test_write_year_consolidates_to_single_canonical_file(tmp_path):
    tdir = tmp_path / "ticker=FPT"
    ydir = tdir / "year=2026"
    _mk(ydir, "prices.parquet", ["2026-07-02"], [72.5], mtime_offset=-100)
    _mk(ydir, "x (conflicted copy 2026-07-06).parquet", ["2026-07-07"], [73.2])

    merged = _read_year(tdir, 2026)
    _write_year(tdir, 2026, merged)

    files = sorted(p.name for p in ydir.glob("*.parquet"))
    assert files == ["prices.parquet"]          # conflicted copy deleted
    out = pd.read_parquet(ydir / "prices.parquet")
    assert [str(d) for d in pd.to_datetime(out["time"]).dt.date] == \
        ["2026-07-02", "2026-07-07"]            # union survived the rewrite


def test_read_year_single_file_and_missing_dir(tmp_path):
    tdir = tmp_path / "ticker=FPT"
    _mk(tdir / "year=2026", "prices.parquet", ["2026-07-03"], [72.3])
    assert len(_read_year(tdir, 2026)) == 1
    assert _read_year(tdir, 2025).empty
