"""
vnstock_fix_units.py — One-shot repair for unit-mismatch OHLC bars.

Problem
-------
Some API responses return prices in raw VND (e.g. 4200) instead of the
warehouse's expected thousand-VND unit (e.g. 4.2) for bars where no trade
happened (volume=0 — reference price only). These bars cause spurious
``band/fail`` anomalies like "close dropped -99.89%" when in fact the
stock barely moved.

Detection rule (all three must hold — avoids false positives)
-------------------------------------------------------------
  1. close > RAW_VND_THRESHOLD        — no VN equity trades > 500 thousand VND,
                                        so any close > 1000 is raw VND
  2. close > RATIO_THRESHOLD × median — the bar stands out vs ±N-day neighbors
  3. neighbor_median < NEIGHBOR_CAP   — the ticker's normal range is thousand-VND
                                        (excludes legitimate high-priced
                                        instruments like indices)

Neighbors are restricted to ``0 < close < NEIGHBOR_CAP`` — that way already-
fixed bars from a prior pass still count as valid references, which matters
during extended market closures (Tet, 30/4) when every bar in a ±N window
can be a unit-mismatch candidate on the first pass.

Volume is NOT a detection signal. The API can return raw-VND prices on
bars with volume > 0 too; restricting to volume == 0 misses those.

Fix: divide ``open/high/low/close`` by 1000 and write the parquet back in
place. Volume and time are untouched.

CLI
---
    python run.py fix-units --dry-run              # preview all fixes
    python run.py fix-units                        # apply to whole warehouse
    python run.py fix-units --ticker UPH           # single ticker
    python run.py fix-units --dry-run --json       # machine-readable preview
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


RAW_VND_THRESHOLD = 1000.0   # close > 1000 is certainly raw VND for a VN equity
RATIO_THRESHOLD   = 10.0     # close must exceed N× the neighbor median
NEIGHBOR_WINDOW   = 10       # ±N trading days — covers week-long Tet/30-4 closures
NEIGHBOR_CAP      = 500.0    # if neighbors are also > this, ticker is legit high-priced

OHLC_COLS = ("open", "high", "low", "close")


@dataclass
class UnitFix:
    ticker: str
    year: int
    time: str           # YYYY-MM-DD
    close_before: float
    close_after: float
    neighbor_median: float


@dataclass
class FixReport:
    scanned_tickers: int = 0
    scanned_bars: int = 0
    fixes: list[UnitFix] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ticker_count(self) -> int:
        return len({f.ticker for f in self.fixes})

    def to_dict(self) -> dict:
        return {
            "scanned_tickers": self.scanned_tickers,
            "scanned_bars": self.scanned_bars,
            "fix_count": len(self.fixes),
            "ticker_count": self.ticker_count,
            "fixes": [f.__dict__ for f in self.fixes],
            "errors": [{"ticker": t, "message": m} for t, m in self.errors],
        }


def _detect_in_ticker(ticker: str, df: pd.DataFrame) -> list[UnitFix]:
    """Return all unit-mismatch bars detected in a single ticker's history."""
    if df.empty or "close" not in df.columns:
        return []

    work = df.sort_values("time").reset_index(drop=True)
    close = pd.to_numeric(work["close"], errors="coerce")

    candidates = close > RAW_VND_THRESHOLD
    if not candidates.any():
        return []

    # Neighbors: bars whose close is in the plausible thousand-VND range.
    # This filter naturally excludes other unit-mismatch candidates AND
    # includes already-fixed low-value bars, so the detector is robust
    # during long closures and on re-runs.
    sensible = close.where((close > 0) & (close < NEIGHBOR_CAP))

    out: list[UnitFix] = []
    for idx in work.index[candidates]:
        start = max(0, idx - NEIGHBOR_WINDOW)
        end = min(len(work), idx + NEIGHBOR_WINDOW + 1)
        neighbors = sensible.iloc[start:end].drop(index=idx).dropna()
        if len(neighbors) == 0:
            continue
        med = float(neighbors.median())
        if med >= NEIGHBOR_CAP:
            continue
        bar_close = float(close.iloc[idx])
        if bar_close <= RATIO_THRESHOLD * med:
            continue
        t = pd.to_datetime(work.iloc[idx]["time"]).date()
        out.append(UnitFix(
            ticker=ticker,
            year=t.year,
            time=t.isoformat(),
            close_before=bar_close,
            close_after=bar_close / 1000.0,
            neighbor_median=med,
        ))
    return out


def scan(warehouse: Path, *, tickers: list[str] | None = None) -> FixReport:
    """Walk warehouse and collect all unit-mismatch bars (read-only)."""
    from vnstock_anomaly import _iter_warehouse_tickers

    report = FixReport()
    target = {t.upper() for t in tickers} if tickers else None

    for ticker, df in _iter_warehouse_tickers(warehouse):
        if target is not None and ticker.upper() not in target:
            continue
        report.scanned_tickers += 1
        report.scanned_bars += len(df)
        try:
            report.fixes.extend(_detect_in_ticker(ticker, df))
        except Exception as exc:
            report.errors.append((ticker, str(exc)))
    return report


def apply_fixes(warehouse: Path, fixes: list[UnitFix]) -> int:
    """Rewrite parquet files in place for every fix. Returns bars updated.

    Groups by (ticker, year) so each year-file is opened at most once. The
    partition columns (``ticker``, ``year``) are NOT part of the on-disk
    schema — they live in the hive path — so we only rewrite the OHLCV
    columns found in each file.
    """
    if not fixes:
        return 0

    import pyarrow as pa
    import pyarrow.parquet as pq

    by_year: dict[tuple[str, int], set[str]] = {}
    for f in fixes:
        by_year.setdefault((f.ticker, f.year), set()).add(f.time)

    updated = 0
    for (ticker, year), dates in by_year.items():
        year_dir = warehouse / "prices" / f"ticker={ticker}" / f"year={year}"
        pq_files = sorted(year_dir.glob("*.parquet"))
        if not pq_files:
            continue
        for pq_file in pq_files:
            df = pd.read_parquet(pq_file)
            if df.empty or "time" not in df.columns:
                continue
            row_dates = pd.to_datetime(df["time"]).dt.date.astype(str)
            mask = row_dates.isin(dates)
            n = int(mask.sum())
            if n == 0:
                continue
            for col in OHLC_COLS:
                if col in df.columns:
                    df.loc[mask, col] = (df.loc[mask, col] / 1000.0).astype(df[col].dtype)
            table = pa.Table.from_pandas(df, preserve_index=False)
            # Ghi NGUYÊN TỬ: `pq.write_table` thẳng vào file đích cắt nó về 0
            # rồi mới stream nội dung — chết giữa chừng là mất/cụt nguyên năm
            # dữ liệu (audit 06/08). Bước này chạy MỖI ĐÊM trong `sync`, và
            # pipeline đã bị kill 2 lần.
            from vnstock_parquet_io import write_table_atomic
            write_table_atomic(table, pq_file)
            updated += n
    return updated


def run(
    warehouse: Path,
    *,
    tickers: list[str] | None = None,
    dry_run: bool = False,
) -> FixReport:
    """End-to-end: scan warehouse, optionally apply, return the report."""
    report = scan(warehouse, tickers=tickers)
    if not dry_run and report.fixes:
        apply_fixes(warehouse, report.fixes)
    return report
