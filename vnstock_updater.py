"""
vnstock_updater.py — Tự động cập nhật giá hàng ngày vào warehouse
==================================================================
Chỉ fetch dữ liệu MỚI kể từ ngày cuối trong warehouse — không tải lại toàn bộ.
Ghi đè file parquet của năm hiện tại với dữ liệu mới nhất.

Cấu trúc warehouse (giữ nguyên):
  data_warehouse/prices/ticker=VCB/year=2026/xxx.parquet

Run:
  python vnstock_updater.py                    # Update tất cả tickers
  python vnstock_updater.py --tickers VCB FPT  # Update mã chỉ định
  python vnstock_updater.py --dry-run          # Xem sẽ update gì, không ghi
  python vnstock_updater.py --check            # Kiểm tra ngày cuối mỗi mã

Tự động hóa (chạy sau 18:00 mỗi ngày làm việc):
  Windows Task Scheduler:
    Program: python
    Arguments: E:\\path\\to\\vnstock_updater.py
    Trigger: Daily 18:30, chỉ Mon-Fri
"""

import argparse
import re as _re
import time
import warnings
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rich import box
from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

# ── vnstock import ────────────────────────────────────────────────────────────
try:
    from vnstock_data import Reference
    USE_UNIFIED = True
    console.log("[green]✅ Using vnstock_data[/green]")
except ImportError:
    USE_UNIFIED = False
    try:
        from vnstock import Vnstock
        console.log("[yellow]⚠ Using vnstock (free)[/yellow]")
    except ImportError:
        console.print("[red]❌ Install vnstock: pip install vnstock[/red]")
        raise

# ── Schema Parquet (giống warehouse hiện tại) ─────────────────────────────────
PRICE_SCHEMA = pa.schema([
    pa.field("time",   pa.date32()),
    pa.field("open",   pa.float32()),
    pa.field("high",   pa.float32()),
    pa.field("low",    pa.float32()),
    pa.field("close",  pa.float32()),
    pa.field("volume", pa.int64()),
])

# ── Filter mã hợp lệ (tái sử dụng từ classifier) ─────────────────────────────
_CW_VN  = _re.compile(r"^C[A-Z]{2,4}\d{4}$")
_CW_OLD = _re.compile(r"^[A-Z]{2,4}\d{5,6}$")
_FUT    = _re.compile(r"^[A-Z]{2,6}F\d{4}$")
_FUT2   = _re.compile(r"^[A-Z]{2}\d{2}F\d{4}$")

def _is_stock(s: str) -> bool:
    s = s.upper().strip()
    if not s or s[0].isdigit():
        return False
    return not (_CW_VN.match(s) or _CW_OLD.match(s) or _FUT.match(s) or _FUT2.match(s))


# ═════════════════════════════════════════════════════════════════════════════
# Warehouse helpers
# ═════════════════════════════════════════════════════════════════════════════

def _get_last_date(ticker_dir: Path) -> date | None:
    """Ngày giao dịch cuối cùng có trong warehouse cho một ticker."""
    last = None
    for year_dir in sorted(ticker_dir.glob("year=*"), reverse=True):
        for pf in year_dir.glob("*.parquet"):
            try:
                tbl = pq.read_table(str(pf), columns=["time"])
                df  = tbl.to_pandas()
                if not df.empty:
                    t = pd.to_datetime(df["time"]).max().date()
                    if last is None or t > last:
                        last = t
                    return last  # Năm mới nhất đã đủ
            except Exception:
                continue
    return last


def _get_year_file(ticker_dir: Path, year: int) -> Path | None:
    """Trả về path file parquet của năm đó (nếu có)."""
    year_dir = ticker_dir / f"year={year}"
    if not year_dir.exists():
        return None
    files = list(year_dir.glob("*.parquet"))
    return files[0] if files else None


def _read_year(ticker_dir: Path, year: int) -> pd.DataFrame:
    """Đọc toàn bộ dữ liệu của năm đó."""
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
    """Ghi dữ liệu năm vào parquet, ghi đè file cũ."""
    year_dir = ticker_dir / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)

    # Giữ tên file cũ nếu có, tạo tên mới nếu chưa có
    existing = list(year_dir.glob("*.parquet"))
    fname = existing[0].name if existing else "prices.parquet"
    out_path = year_dir / fname

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])

    # Cast về đúng schema
    df["open"]   = df["open"].astype("float32")
    df["high"]   = df["high"].astype("float32")
    df["low"]    = df["low"].astype("float32")
    df["close"]  = df["close"].astype("float32")
    df["volume"] = df["volume"].astype("int64")

    table = pa.Table.from_pandas(df, schema=PRICE_SCHEMA, safe=False)
    pq.write_table(table, str(out_path), compression="snappy")


# ═════════════════════════════════════════════════════════════════════════════
# Fetch từ API
# ═════════════════════════════════════════════════════════════════════════════

def _fetch_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch OHLCV từ vnstock API.
    start/end: 'YYYY-MM-DD'
    Trả về DataFrame với cột: time(date), open, high, low, close, volume
    """
    try:
        if USE_UNIFIED:
            from vnstock_data import Equity
            df = Equity().stock(ticker).quote.history(
                start=start, end=end, interval="1D"
            )
        else:
            df = Vnstock().stock(symbol=ticker, source="VCI") \
                         .quote.history(start=start, end=end, interval="1D")

        if df is None or df.empty:
            return pd.DataFrame()

        # Normalize columns
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ("time", "date", "tradingdate"):
                col_map[c] = "time"
            elif cl == "open":
                col_map[c] = "open"
            elif cl == "high":
                col_map[c] = "high"
            elif cl == "low":
                col_map[c] = "low"
            elif cl in ("close", "adjclose"):
                col_map[c] = "close"
            elif cl in ("volume", "vol"):
                col_map[c] = "volume"
        df = df.rename(columns=col_map)

        needed = ["time", "open", "high", "low", "close", "volume"]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            return pd.DataFrame()

        df = df[needed].copy()
        df["time"] = pd.to_datetime(df["time"]).dt.date
        df = df.dropna(subset=["time", "close"])
        df = df.sort_values("time").reset_index(drop=True)
        return df

    except Exception as e:
        raise RuntimeError(str(e))


# ═════════════════════════════════════════════════════════════════════════════
# Core update logic
# ═════════════════════════════════════════════════════════════════════════════

def update_ticker(
    ticker: str,
    prices_dir: Path,
    today: date,
    dry_run: bool = False,
) -> dict:
    """
    Update giá cho một ticker.
    Trả về dict với status và số ngày mới.
    """
    ticker_dir = prices_dir / f"ticker={ticker}"
    result = {"ticker": ticker, "status": "skip", "new_days": 0, "error": ""}

    if not ticker_dir.exists():
        result["status"] = "no_data"
        result["error"] = "Không có trong warehouse"
        return result

    # Lấy ngày cuối trong warehouse
    last_date = _get_last_date(ticker_dir)
    if last_date is None:
        result["status"] = "error"
        result["error"] = "Không đọc được ngày cuối"
        return result

    # Tính ngày cần fetch
    fetch_from = last_date + timedelta(days=1)

    # Không cần update nếu đã có đến hôm nay hoặc hôm qua (T+0 chưa có)
    if fetch_from > today:
        result["status"] = "up_to_date"
        return result

    if dry_run:
        result["status"] = "would_update"
        result["new_days"] = (today - last_date).days
        return result

    # Fetch dữ liệu mới
    try:
        new_df = _fetch_prices(
            ticker,
            start=fetch_from.strftime("%Y-%m-%d"),
            end=today.strftime("%Y-%m-%d"),
        )
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:80]
        return result

    if new_df.empty:
        result["status"] = "no_new_data"
        return result

    # Merge vào warehouse theo năm
    years_affected = sorted(new_df["time"].apply(lambda d: d.year).unique())
    for year in years_affected:
        year_new = new_df[new_df["time"].apply(lambda d: d.year) == year].copy()

        # Đọc data cũ của năm đó (nếu có)
        year_old = _read_year(ticker_dir, year)

        if not year_old.empty:
            # Merge: giữ data cũ, thêm ngày mới, dedup
            merged = pd.concat([year_old, year_new], ignore_index=True)
            merged["time"] = pd.to_datetime(merged["time"]).dt.date
            merged = merged.drop_duplicates(subset=["time"], keep="last")
            merged = merged.sort_values("time").reset_index(drop=True)
        else:
            merged = year_new

        _write_year(ticker_dir, year, merged)

    result["status"] = "updated"
    result["new_days"] = len(new_df)
    result["last_date"] = str(new_df["time"].max())
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Main runner
# ═════════════════════════════════════════════════════════════════════════════

def run_update(
    warehouse: str = "data_warehouse",
    tickers: list = None,
    dry_run: bool = False,
    delay: float = 0.3,
    skip_weekends: bool = True,
):
    prices_dir = Path(warehouse) / "prices"
    if not prices_dir.exists():
        console.print(f"[red]❌ Warehouse không tồn tại: {prices_dir}[/red]")
        return

    today = date.today()

    # Bỏ qua cuối tuần nếu không có --force
    if skip_weekends and today.weekday() >= 5:
        day_name = "Thứ Bảy" if today.weekday() == 5 else "Chủ Nhật"
        console.print(
            f"[yellow]⏸ Hôm nay là {day_name} ({today}) — "
            f"thị trường đóng cửa.[/yellow]\n"
            f"  Chạy với [cyan]--force[/cyan] để update bất kể ngày."
        )
        return

    # Lấy danh sách tickers
    if tickers:
        scan_list = [t.upper() for t in tickers]
    else:
        scan_list = sorted([
            p.name.replace("ticker=", "")
            for p in prices_dir.iterdir()
            if p.is_dir() and p.name.startswith("ticker=")
            and _is_stock(p.name.replace("ticker=", ""))
        ])

    console.rule(
        f"[bold cyan]📈 Daily Price Update — {today}[/bold cyan]"
        + (" [DRY RUN]" if dry_run else "")
    )
    console.log(f"  Tickers: {len(scan_list)} | Delay: {delay}s")

    stats = {"updated": 0, "up_to_date": 0, "error": 0, "skip": 0}
    errors = []
    updated_list = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Updating...", total=len(scan_list))

        for ticker in scan_list:
            progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

            result = update_ticker(ticker, prices_dir, today, dry_run=dry_run)
            status = result["status"]

            if status == "updated":
                stats["updated"] += 1
                updated_list.append(result)
            elif status in ("up_to_date", "no_new_data", "would_update"):
                stats["up_to_date"] += 1
                if status == "would_update":
                    updated_list.append(result)
            elif status == "error":
                stats["error"] += 1
                errors.append(result)
            else:
                stats["skip"] += 1

            if status not in ("up_to_date", "no_new_data"):
                time.sleep(delay)

    # ── Summary ────────────────────────────────────────────────────────────────
    console.print()
    action = "Would update" if dry_run else "Updated"
    console.print(
        f"[green]✅ {action}: {stats['updated']}[/green] | "
        f"[dim]Up-to-date: {stats['up_to_date']}[/dim] | "
        f"[red]Errors: {stats['error']}[/red] | "
        f"[dim]Skipped: {stats['skip']}[/dim]"
    )

    # Hiển thị các mã vừa được update
    if updated_list:
        t = Table(
            title=f"{'📋 Sẽ update' if dry_run else '✅ Đã update'} {len(updated_list)} mã",
            box=box.SIMPLE_HEAVY
        )
        t.add_column("Ticker",      style="cyan", width=8)
        t.add_column("Ngày mới nhất", width=14)
        t.add_column("Số ngày mới", justify="right", width=12)
        for r in updated_list[:30]:
            t.add_row(
                r["ticker"],
                r.get("last_date", "—"),
                str(r.get("new_days", "—")),
            )
        if len(updated_list) > 30:
            t.add_row("...", f"...và {len(updated_list)-30} mã khác", "")
        console.print(t)

    # Hiển thị lỗi
    if errors:
        console.print(f"\n[red]❌ {len(errors)} lỗi:[/red]")
        for e in errors[:10]:
            console.print(f"  [dim]{e['ticker']}: {e['error']}[/dim]")


def run_check(warehouse: str = "data_warehouse", tickers: list = None):
    """Kiểm tra ngày cuối của từng ticker trong warehouse."""
    prices_dir = Path(warehouse) / "prices"
    today = date.today()

    scan_list = tickers or sorted([
        p.name.replace("ticker=", "")
        for p in prices_dir.iterdir()
        if p.is_dir() and p.name.startswith("ticker=")
        and _is_stock(p.name.replace("ticker=", ""))
    ])

    console.rule("[bold]🔍 Warehouse Status Check[/bold]")

    results = []
    for ticker in scan_list[:50]:  # Giới hạn 50 để nhanh
        ticker_dir = prices_dir / f"ticker={ticker}"
        last = _get_last_date(ticker_dir)
        if last:
            lag = (today - last).days
            results.append({"ticker": ticker, "last_date": last, "lag_days": lag})

    results.sort(key=lambda x: x["lag_days"], reverse=True)

    t = Table(title=f"Ngày cuối trong warehouse (top 20 lâu nhất)", box=box.SIMPLE_HEAVY)
    t.add_column("Ticker",    style="cyan", width=8)
    t.add_column("Ngày cuối", width=12)
    t.add_column("Lag",       justify="right", style="yellow", width=8)

    for r in results[:20]:
        lag = r["lag_days"]
        color = "red" if lag > 5 else "yellow" if lag > 2 else "green"
        t.add_row(
            r["ticker"],
            str(r["last_date"]),
            f"[{color}]{lag}d[/{color}]",
        )
    console.print(t)

    up_to_date = sum(1 for r in results if r["lag_days"] <= 1)
    stale      = sum(1 for r in results if r["lag_days"] > 3)
    console.print(
        f"  [dim]Checked {len(results)} tickers | "
        f"Up-to-date (≤1d): {up_to_date} | "
        f"Stale (>3d): {stale}[/dim]"
    )


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Daily Price Updater")
    parser.add_argument("--tickers",   nargs="+", metavar="TICKER",
                        help="Chỉ update mã cụ thể (mặc định: tất cả)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Xem sẽ update gì mà không ghi vào disk")
    parser.add_argument("--check",     action="store_true",
                        help="Kiểm tra ngày cuối của từng mã")
    parser.add_argument("--force",     action="store_true",
                        help="Chạy kể cả cuối tuần")
    parser.add_argument("--delay",     type=float, default=0.3,
                        help="Delay giữa API calls (giây, mặc định 0.3)")
    parser.add_argument("--warehouse", default="data_warehouse",
                        help="Đường dẫn warehouse")
    args = parser.parse_args()

    if args.check:
        run_check(warehouse=args.warehouse, tickers=args.tickers)
    else:
        run_update(
            warehouse=args.warehouse,
            tickers=args.tickers,
            dry_run=args.dry_run,
            delay=args.delay,
            skip_weekends=not args.force,
        )
