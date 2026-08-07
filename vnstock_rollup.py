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
import json
import os
import random
import shutil
import socket
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from vnstock_parquet_io import (
    CorruptWarehouseFile, read_year_frames, write_table_atomic,
)

# ═════════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════════

LIVE_DIR = Path("data_warehouse/_live")
ARCHIVE_DIR = LIVE_DIR / "archive"
PRICES_DIR = Path("data_warehouse/prices")
META_DIR = Path("data_warehouse/_meta")
PIPELINE_STATUS_PATH = META_DIR / "pipeline_status.json"

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
# Multi-machine coordination helpers
# ═════════════════════════════════════════════════════════════════════════════

def get_hostname() -> str:
    """Tên máy hiện tại."""
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def get_today_vn() -> date:
    """Ngày hôm nay theo Asia/Ho_Chi_Minh."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    except Exception:
        return date.today()


def read_pipeline_status() -> dict:
    """Đọc pipeline_status.json. Trả dict rỗng nếu missing/corrupt."""
    if not PIPELINE_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(PIPELINE_STATUS_PATH.read_text())
    except Exception:
        return {}


def write_pipeline_status(job: str, update: dict):
    """Merge update vào pipeline_status.json[job], atomic write."""
    PIPELINE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status = read_pipeline_status()
    status[job] = {**status.get(job, {}), **update}

    tmp = PIPELINE_STATUS_PATH.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False))
        os.replace(str(tmp), str(PIPELINE_STATUS_PATH))
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        print(f"[rollup] ⚠ write pipeline_status: {e}")


def is_already_done_today(job: str) -> tuple[bool, dict]:
    """Check nếu job đã chạy thành công hôm nay (VN time)."""
    status = read_pipeline_status().get(job, {})
    last_date_str = status.get("last_success_date", "")
    today_str = get_today_vn().isoformat()
    done = (last_date_str == today_str
            and status.get("last_result") == "success")
    return done, status


# ═════════════════════════════════════════════════════════════════════════════
# Warehouse helpers (tái sử dụng pattern từ vnstock_updater)
# ═════════════════════════════════════════════════════════════════════════════



def _read_year(ticker_dir: Path, year: int, *, strict: bool = True) -> pd.DataFrame:
    """Đọc data một năm — gộp MỌI file parquet trong year-dir (Dropbox có thể
    đẻ "conflicted copy" cạnh file chính; đọc một file là mất data mới nếu nó
    nằm ở file kia). File mới nhất (mtime) thắng khi trùng ngày.

    `strict=True` (mặc định): canonical hỏng → raise `CorruptWarehouseFile`.
    Rollup CHỈ có bar hôm nay nên ghi tiếp là tạo file 1 dòng, xoá sổ cả năm
    lịch sử — thà bỏ qua ticker-year (xem vnstock_parquet_io)."""
    frames = read_year_frames(ticker_dir / f"year={year}", strict=strict)
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["time"], keep="last")
    return merged.sort_values("time").reset_index(drop=True)


def _write_year(ticker_dir: Path, year: int, df: pd.DataFrame):
    year_dir = ticker_dir / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)

    # Luôn ghi về file canonical — trước đây "existing[0]" khiến updater ghi
    # vào bản conflicted copy của Dropbox (xếp trước theo alphabet) trong khi
    # loader đọc file khác → kho "tươi mà vẫn cũ" (07/07/2026).
    out_path = year_dir / "prices.parquet"

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df["open"] = df["open"].astype("float32")
    df["high"] = df["high"].astype("float32")
    df["low"] = df["low"].astype("float32")
    df["close"] = df["close"].astype("float32")
    df["volume"] = df["volume"].astype("int64")

    table = pa.Table.from_pandas(df, schema=PRICE_SCHEMA, safe=False)
    # Ghi NGUYÊN TỬ — xem vnstock_parquet_io (audit 06/08: ghi thẳng + chết
    # giữa chừng = file cụt = mất cả năm lịch sử ở lần chạy sau).
    write_table_atomic(table, out_path)

    # Consolidate: mọi file khác prices.parquet (Dropbox conflicted copy…) đã
    # được _read_year gộp vào df — xoá đi để year-dir luôn về đúng 1 file.
    for pf in year_dir.glob("*.parquet"):
        if pf.name != "prices.parquet":
            try:
                pf.unlink()
            except Exception:
                pass


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


_UNIT_RATIO_MIN = 100.0     # trần biên độ 1 phiên là ±15%, nên ≥100× chắc chắn
#                             là lệch ĐƠN VỊ chứ không phải giá chạy
_UNIT_SCALE = 1000.0        # kho lưu NGHÌN VND, WSS trả VND thô


def _normalize_units(new_rows: pd.DataFrame, existing: pd.DataFrame,
                     ticker: str) -> pd.DataFrame:
    """Quy đổi giá bar WSS (VND thô) về đơn vị kho (NGHÌN VND).

    Vì sao không dựa vào `vnstock_fix_units`: nó chỉ chạm bar có
    `close > 1000` (RAW_VND_THRESHOLD). Mã penny — 300-900 VND, rất nhiều
    trên UPCOM — ghi thẳng số thô vào kho thì bị đọc thành 300-900 NGHÌN VND,
    sai 1000× mà KHÔNG có lưới nào bắt (audit 06/08).

    Cách chắc ăn hơn ngưỡng toàn cục: so với chính LỊCH SỬ của mã đó. Giá một
    phiên không thể nhảy ≥100× (biên độ sàn ±15%), nên tỉ lệ cỡ đó chỉ có thể
    là lệch đơn vị. Mã chưa có lịch sử (niêm yết mới) → giữ nguyên, để
    `fix_units` lo phần > 1000 như cũ.
    """
    if new_rows.empty or existing.empty or "close" not in existing.columns:
        return new_rows
    ref = pd.to_numeric(existing["close"], errors="coerce").dropna()
    ref = ref[ref > 0]
    new_close = pd.to_numeric(new_rows["close"], errors="coerce").dropna()
    new_close = new_close[new_close > 0]
    if ref.empty or new_close.empty:
        return new_rows

    ratio = float(new_close.median()) / float(ref.median())
    if ratio < _UNIT_RATIO_MIN:
        return new_rows

    out = new_rows.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") / _UNIT_SCALE
    print(f"[rollup] {ticker}: giá bar lệch {ratio:,.0f}× so với kho → quy đổi "
          f"VND → nghìn VND ({len(out)} dòng)")
    return out


def rollup_bars_file(bars_path: Path, dry_run: bool = False) -> dict:
    """
    Rollup 1 file bars_{date}.parquet → warehouse daily.

    Returns: dict với {tickers_updated, rows_merged, skipped, errors,
                        skipped_tickers, already_archived}
    """
    stats = {"tickers_updated": 0, "rows_merged": 0, "skipped": 0,
             "errors": 0, "skipped_tickers": [], "already_archived": False}

    if not bars_path.exists():
        # Check xem có phải đã archive bởi máy khác không
        archive_path = ARCHIVE_DIR / bars_path.name
        if archive_path.exists():
            print(f"[rollup] {bars_path.name} đã archive sẵn (máy khác đã chạy)")
            stats["already_archived"] = True
            return stats
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

            try:
                existing = _read_year(ticker_dir, year)
            except CorruptWarehouseFile as e:
                # Canonical hỏng: ghi tiếp = ghi đè cả năm bằng bar hôm nay.
                # Bỏ qua ticker-year; updater (chạy TRƯỚC trong run.py sync)
                # sẽ cách ly file + tải lại nguyên năm từ API.
                print(f"[rollup] ⛔ Bỏ qua {ticker} year={year}: {e}")
                stats["errors"] += 1
                continue
            new_rows = _normalize_units(new_rows, existing, str(ticker))

            if not existing.empty:
                # Existing data (from updater API) is authoritative — rollup only
                # fills gaps. Rollup-aggregated volume is less reliable than the
                # daily API, especially for intraday-bar based sources where
                # accumulated volume may have been summed (see vnstock_wss.py
                # accum→delta conversion).
                combined = pd.concat([existing, new_rows], ignore_index=True)
                combined = (
                    combined.drop_duplicates(subset=["time"], keep="first")
                            .sort_values("time")
                            .reset_index(drop=True)
                )
            else:
                combined = new_rows.sort_values("time").reset_index(drop=True)

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
    parser.add_argument("--skip-if-done", action="store_true",
                        help="Skip nếu job đã chạy hôm nay (multi-machine coordination)")
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"✗ Invalid date format: {args.date}")
            return 1
    else:
        target_date = get_today_vn()

    hostname = get_hostname()
    bars_path = LIVE_DIR / f"bars_{target_date.isoformat()}.parquet"

    print("=" * 60)
    print(f"Rollup Job — {target_date.isoformat()}")
    print(f"Machine: {hostname}")
    print(f"Source:  {bars_path}")
    print(f"Dry run: {args.dry_run}")
    if args.skip_if_done:
        print(f"Mode:    skip-if-done (multi-machine)")
    print("=" * 60)

    # ── Multi-machine coordination: skip if another machine already did it
    if args.skip_if_done and not args.dry_run:
        # Jitter 0-30s để giảm xác suất 2 máy start cùng lúc
        jitter = random.uniform(0, 30)
        print(f"[rollup] Jitter {jitter:.1f}s trước khi check status...")
        time.sleep(jitter)

        done, existing_status = is_already_done_today("rollup")
        if done:
            other_machine = existing_status.get("last_machine", "?")
            other_time = existing_status.get("last_run_at", "?")
            tickers = existing_status.get("tickers_updated", "?")
            print(f"\n[rollup] ✓ Đã chạy hôm nay bởi máy {other_machine}")
            print(f"  Thời điểm:       {other_time}")
            print(f"  Tickers updated: {tickers}")
            print(f"  → Skip trên máy này ({hostname})")
            return 0

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

    # 4. Write pipeline status (success)
    if (not args.dry_run
            and stats["errors"] == 0
            and (stats["tickers_updated"] > 0 or stats["already_archived"])):
        write_pipeline_status("rollup", {
            "last_success_date": target_date.isoformat(),
            "last_run_at": datetime.now().isoformat(timespec="seconds"),
            "last_machine": hostname,
            "last_result": "success",
            "tickers_updated": stats["tickers_updated"],
            "already_archived": stats["already_archived"],
        })
        print(f"[rollup] pipeline_status.json updated")

    print("\n[rollup] ✓ Done")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
