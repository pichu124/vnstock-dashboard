"""
vnstock_rollup.py — Daily Rollup Job
====================================
Sau phiên giao dịch (>= 15:05 VN), merge 1-minute bars từ vnstock_wss
(data_warehouse/_live/bars_{date}.parquet) vào warehouse daily
(data_warehouse/prices/ticker={X}/year={Y}/prices.parquet).

Pipeline:
  1. Đọc bars_{date}.parquet — schema: ticker,time(datetime),OHLCV
  2. Aggregate theo ticker → daily OHLCV (open=first, high=max,
     low=min, close=last, volume=sum)
  3. Với từng ticker: merge vào warehouse (dedup by date, keep last)
  4. Archive bars file vào _live/archive/
  5. Cleanup archive cũ > N ngày

Usage:
  python vnstock_rollup.py                 # Rollup today's bars
  python vnstock_rollup.py --date 2026-04-10
  python vnstock_rollup.py --cleanup-days 30
  python vnstock_rollup.py --dry-run       # Preview, không ghi
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ═════════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════════

LIVE_DIR = Path("data_warehouse/_live")
ARCHIVE_DIR = LIVE_DIR / "archive"
PRICES_DIR = Path("data_warehouse/prices")
META_DIR = Path("data_warehouse/_meta")

# Schema giống vnstock_updater.py
PRICE_SCHEMA = pa.schema([
    pa.field("time",   pa.date32()),
    pa.field("open",   pa.float32()),
    pa.field("high",   pa.float32()),
    pa.field("low",    pa.float32()),
    pa.field("close",  pa.float32()),
    pa.field("volume", pa.int64()),
])


# ═════════════════════════════════════════════════════════════════════════════
# Warehouse helpers (tái sử dụng pattern từ vnstock_updater)
# ═════════════════════════════════════════════════════════════════════════════

def _get_year_file(ticker_dir: Path, year: int) -> Optional[Path]:
    year_dir = ticker_dir / f"year={year}"
    if not year_dir.exists():
        return None
    files = list(year_dir.glob("*.parquet"))
    return files[0] if files else None


def _read_year(ticker_dir: Path, year: int) -> pd.DataFrame:
    pf = _get_year_file(ticker_dir, year)
    if pf is None:
        return pd.DataFrame()
    try:
        df = pq.read_table(str(pf)).to_pandas()
        df["time"] = pd.to_datetime(df["time"]).dt.date
        return df
    except Exception:
        return pd.DataFrame()


def _write_year(ticker_dir: Path, year: int, df: pd.DataFrame):
    year_dir = ticker_dir / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)

    existing = list(year_dir.glob("*.parquet"))
    fname = existing[0].name if existing else "prices.parquet"
    out_path = year_dir / fname

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df["open"] = df["open"].astype("float32")
    df["high"] = df["high"].astype("float32")
    df["low"] = df["low"].astype("float32")
    df["close"] = df["close"].astype("float32")
    df["volume"] = df["volume"].astype("int64")

    table = pa.Table.from_pandas(df, schema=PRICE_SCHEMA, safe=False)
    pq.write_table(table, str(out_path), compression="snappy")


# ═════════════════════════════════════════════════════════════════════════════
# Ticker filter — chỉ rollup mã cổ phiếu vào warehouse, skip futures/index
# ═════════════════════════════════════════════════════════════════════════════

import re as _re

_INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOM"}
_FUT_PREFIX = ("VN30F", "41I")


def _should_rollup_to_warehouse(ticker: str) -> bool:
    """
    Chỉ rollup mã cổ phiếu (VCB, FPT, ...) vào warehouse.
    Indices và futures có schema riêng, không merge chung.
    """
    t = ticker.upper()
    if t in _INDEX_SYMBOLS:
        return False
    if any(t.startswith(p) for p in _FUT_PREFIX):
        return False
    # Basic stock pattern: 3 chữ cái
    if len(t) != 3 or not t.isalpha():
        return False
    return True


# ═════════════════════════════════════════════════════════════════════════════
# Rollup logic
# ═════════════════════════════════════════════════════════════════════════════

def _aggregate_bars_to_daily(bars_df: pd.DataFrame) -> pd.DataFrame:
    """
    Group 1m bars theo (ticker, trading_date) → 1 daily OHLCV row.

    Input: columns = ticker, time(datetime), open, high, low, close, volume
    Output: columns = ticker, trading_date(date), open, high, low, close, volume
    """
    if bars_df.empty:
        return pd.DataFrame(columns=["ticker", "trading_date", "open", "high",
                                      "low", "close", "volume"])

    df = bars_df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df["trading_date"] = df["time"].dt.date

    # Sort để first/last đúng chiều thời gian
    df = df.sort_values(["ticker", "time"])

    agg = (
        df.groupby(["ticker", "trading_date"], as_index=False)
          .agg(
              open=("open", "first"),
              high=("high", "max"),
              low=("low", "min"),
              close=("close", "last"),
              volume=("volume", "sum"),
          )
    )
    return agg


def rollup_bars_file(bars_path: Path, dry_run: bool = False) -> dict:
    """
    Rollup 1 file bars_{date}.parquet → warehouse daily.

    Returns: dict với {tickers_updated, rows_merged, skipped, errors}
    """
    stats = {"tickers_updated": 0, "rows_merged": 0, "skipped": 0,
             "errors": 0, "skipped_tickers": []}

    if not bars_path.exists():
        print(f"[rollup] ✗ {bars_path.name} không tồn tại")
        return stats

    print(f"[rollup] Reading {bars_path.name}...")
    try:
        bars_df = pq.read_table(str(bars_path)).to_pandas()
    except Exception as e:
        print(f"[rollup] ✗ Read error: {e}")
        stats["errors"] += 1
        return stats

    if bars_df.empty:
        print("[rollup] ✗ Empty bars file")
        return stats

    print(f"[rollup] {len(bars_df):,} bars from {bars_df['ticker'].nunique()} symbols")

    daily = _aggregate_bars_to_daily(bars_df)
    print(f"[rollup] Aggregated → {len(daily)} daily rows")

    PRICES_DIR.mkdir(parents=True, exist_ok=True)

    for ticker, group in daily.groupby("ticker"):
        if not _should_rollup_to_warehouse(ticker):
            stats["skipped"] += 1
            stats["skipped_tickers"].append(ticker)
            continue

        ticker_dir = PRICES_DIR / f"ticker={ticker}"

        # Mỗi group thường có 1 date (per trading day). Split by year.
        for year, year_group in group.groupby(group["trading_date"].apply(lambda d: d.year)):
            year = int(year)
            new_rows = year_group[["trading_date", "open", "high", "low",
                                   "close", "volume"]].rename(
                columns={"trading_date": "time"}
            )

            existing = _read_year(ticker_dir, year)
            if not existing.empty:
                combined = pd.concat([existing, new_rows], ignore_index=True)
            else:
                combined = new_rows

            # Dedup: keep last (rollup data wins cho cùng date)
            combined = (
                combined.drop_duplicates(subset=["time"], keep="last")
                        .sort_values("time")
                        .reset_index(drop=True)
            )

            if dry_run:
                print(f"[dry-run] {ticker} year={year}: "
                      f"{len(new_rows)} new → {len(combined)} total")
            else:
                try:
                    _write_year(ticker_dir, year, combined)
                    stats["tickers_updated"] += 1
                    stats["rows_merged"] += len(new_rows)
                except Exception as e:
                    print(f"[rollup] ✗ Write {ticker} year={year}: {e}")
                    stats["errors"] += 1

    return stats


# ═════════════════════════════════════════════════════════════════════════════
# Archive management
# ═════════════════════════════════════════════════════════════════════════════

def archive_bars_file(bars_path: Path, dry_run: bool = False) -> bool:
    """Move bars_{date}.parquet → _live/archive/."""
    if not bars_path.exists():
        return False
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / bars_path.name
    if dry_run:
        print(f"[dry-run] archive: {bars_path.name} → archive/")
        return True
    try:
        shutil.move(str(bars_path), str(target))
        print(f"[rollup] Archived {bars_path.name}")
        return True
    except Exception as e:
        print(f"[rollup] ✗ Archive failed: {e}")
        return False


def cleanup_archive(days: int = 30, dry_run: bool = False) -> int:
    """Xoá file archive cũ hơn N ngày. Trả về số file xoá."""
    if not ARCHIVE_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_date = cutoff.date()

    deleted = 0
    for f in sorted(ARCHIVE_DIR.glob("bars_*.parquet")):
        # Parse date từ filename: bars_2026-04-10.parquet
        try:
            date_str = f.stem.replace("bars_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if file_date < cutoff_date:
            if dry_run:
                print(f"[dry-run] cleanup: {f.name} (age {(cutoff_date - file_date).days}d)")
            else:
                try:
                    f.unlink()
                    print(f"[rollup] Deleted old archive: {f.name}")
                    deleted += 1
                except Exception as e:
                    print(f"[rollup] ✗ Delete {f.name}: {e}")

    return deleted


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Daily rollup: 1m bars → warehouse daily OHLCV"
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD",
                        help="Rollup specific date (default: today)")
    parser.add_argument("--cleanup-days", type=int, default=30,
                        help="Delete archive files older than N days (default: 30)")
    parser.add_argument("--no-archive", action="store_true",
                        help="Không archive file sau khi rollup")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Không cleanup archive cũ")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview, không ghi file")
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"✗ Invalid date format: {args.date}")
            return 1
    else:
        target_date = date.today()

    bars_path = LIVE_DIR / f"bars_{target_date.isoformat()}.parquet"

    print("=" * 60)
    print(f"Rollup Job — {target_date.isoformat()}")
    print(f"Source: {bars_path}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # 1. Rollup
    stats = rollup_bars_file(bars_path, dry_run=args.dry_run)

    print(f"\n[rollup] Summary:")
    print(f"  Tickers updated: {stats['tickers_updated']}")
    print(f"  Rows merged:     {stats['rows_merged']}")
    print(f"  Skipped (index/futures/invalid): {stats['skipped']}")
    if stats["skipped_tickers"]:
        print(f"    → {', '.join(sorted(set(stats['skipped_tickers'])))}")
    print(f"  Errors:          {stats['errors']}")

    # 2. Archive bars file
    if not args.no_archive and stats["tickers_updated"] > 0:
        archive_bars_file(bars_path, dry_run=args.dry_run)

    # 3. Cleanup old archives
    if not args.no_cleanup:
        deleted = cleanup_archive(days=args.cleanup_days, dry_run=args.dry_run)
        if deleted:
            print(f"[rollup] Deleted {deleted} old archive files")

    print("\n[rollup] ✓ Done")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
