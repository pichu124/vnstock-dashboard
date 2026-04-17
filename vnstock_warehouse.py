"""
vnstock_warehouse.py — Local Parquet Data Warehouse
====================================================
High-performance local data warehouse for Vietnamese stock market data.
Works alongside vnstock_platform_v2.py (shares the same dual-source logic).

Directory structure:
  data_warehouse/
  └── prices/
      ├── ticker=VCB/
      │   ├── year=2024/part-0.parquet
      │   └── year=2025/part-0.parquet
      ├── ticker=FPT/
      │   └── year=2025/part-0.parquet
      └── _meta/
          └── last_sync.json   ← tracks last date per ticker

Install deps:
  pip install pyarrow pandas vnstock rich tqdm python-dotenv

Setup API key (one-time):
  Create a .env file in the same folder:
    VNSTOCK_API_KEY=vnstock_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Run:
  python vnstock_warehouse.py --load        # Initial bulk load (all exchanges)
  python vnstock_warehouse.py --sync        # Daily incremental sync
  python vnstock_warehouse.py --query FPT   # Query example
  python vnstock_warehouse.py --load --exchange HOSE   # One exchange only
"""

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn, TimeRemainingColumn)
from rich.table import Table
from rich import box

from vnstock_auth import ensure_api_key, get_api_key

warnings.filterwarnings("ignore")

console = Console()

# ── Apply API key from .env ───────────────────────────────────────────────────
_API_KEY = get_api_key()
if _API_KEY:
    ensure_api_key()
    console.log(f"[green]🔑 API key loaded from .env[/green]")
else:
    console.log("[yellow]⚠ No VNSTOCK_API_KEY in .env — using Community tier[/yellow]")

# ── Tier config — request limits & safe delays ────────────────────────────────
# Community: 60/min  → delay 1.1s
# Bronze:   180/min  → delay 0.38s  (dùng 0.40s để có buffer)
# Silver:   300/min  → delay 0.22s
# Golden:   600/min  → delay 0.12s
TIER_CONFIG = {
    "community": {"req_per_min": 60,  "delay": 1.10, "label": "Community"},
    "bronze":    {"req_per_min": 180, "delay": 0.40, "label": "Bronze"},
    "silver":    {"req_per_min": 300, "delay": 0.22, "label": "Silver"},
    "golden":    {"req_per_min": 600, "delay": 0.12, "label": "Golden"},
}

def _detect_tier() -> str:
    """
    Detect tier from vnstock check_status() after API key is applied.
    """
    if not _API_KEY:
        return "community"
    try:
        ensure_api_key()  # Re-apply key in case vnstock_data import reset it
        from vnstock.core.utils.auth import check_status
        status = str(check_status()).lower()
        for t in ("golden", "silver", "bronze"):
            if t in status:
                console.log(f"[cyan]📊 Detected tier: {t.capitalize()}[/cyan]")
                return t
        # Has a key but tier not detected → assume bronze (registered user)
        if _API_KEY.startswith("vnstock_") and len(_API_KEY) > 20:
            console.log("[cyan]📊 Registered key detected → using Bronze config[/cyan]")
            return "bronze"
        return "community"
    except Exception:
        if _API_KEY.startswith("vnstock_") and len(_API_KEY) > 20:
            return "bronze"
        return "community"

# ── Dual-source: vnstock_data → vnstock (free) ────────────────────────────────
try:
    from vnstock_data import Market, Reference
    USE_UNIFIED = True
except ImportError:
    USE_UNIFIED = False
    try:
        from vnstock import Vnstock, Listing
    except ImportError:
        console.print("[red]❌ Install vnstock: pip install vnstock[/red]")
        sys.exit(1)

# Re-apply Golden key AFTER vnstock imports (they can auto-register free keys)
ensure_api_key()

# ─────────────────────────────────────────────────────────────────────────────
# PyArrow schema — enforces consistent dtypes across all parquet files
# ─────────────────────────────────────────────────────────────────────────────
OHLCV_SCHEMA = pa.schema([
    pa.field("time",   pa.date32()),
    pa.field("open",   pa.float32()),
    pa.field("high",   pa.float32()),
    pa.field("low",    pa.float32()),
    pa.field("close",  pa.float32()),
    pa.field("volume", pa.int64()),
    pa.field("ticker", pa.string()),
    pa.field("year",   pa.int16()),   # partition column
])

import re as _re

VALID_EXCHANGES = {"HOSE", "HNX", "UPCOM"}
DEFAULT_START   = "2000-01-01"

# Patterns for non-stock symbols to skip
# CW: SSI2405, HDB125025 (ticker + 6 digits)
# Futures: VN30F2503, VNXF2503
_CW_PATTERN      = _re.compile(r"^[A-Z]{2,4}\d{5,6}$")
_FUTURES_PATTERN = _re.compile(r"^[A-Z]{2,6}F\d{4}$")

def _is_stock(symbol: str) -> bool:
    """Return False for covered warrants and futures symbols."""
    s = symbol.upper().strip()
    if _CW_PATTERN.match(s):
        return False
    if _FUTURES_PATTERN.match(s):
        return False
    return True     # listing date fallback


# ═════════════════════════════════════════════════════════════════════════════
# VnStockWarehouse
# ═════════════════════════════════════════════════════════════════════════════

class VnStockWarehouse:
    """
    Local Parquet data warehouse for Vietnam stock OHLCV data.

    Storage layout:
      <root>/prices/ticker=XXX/year=YYYY/part-0.parquet

    Partition strategy:
      - ticker  : filter one stock without scanning others
      - year    : filter a date range without loading full history

    Usage:
        wh = VnStockWarehouse("data_warehouse")
        wh.initial_bulk_load(exchanges=["HOSE"])
        wh.daily_sync()
        df = wh.query("FPT", start="2020-01-01")
    """

    def __init__(
        self,
        root: str = "data_warehouse",
        tier: str = "auto",
        batch_size: int = 50,
    ):
        """
        Args:
            root       : Root directory for all parquet files
            tier       : "auto" (detect from API key) | "community" | "bronze" |
                         "silver" | "golden"
            batch_size : Symbols per checkpoint save
        """
        self.root       = Path(root)
        self.prices_dir = self.root / "prices"
        self.meta_dir   = self.root / "_meta"
        self.meta_file  = self.meta_dir / "last_sync.json"
        self.batch_size = batch_size

        # Detect tier & set delay
        self.tier = _detect_tier() if tier == "auto" else tier.lower()
        cfg = TIER_CONFIG.get(self.tier, TIER_CONFIG["community"])
        self.request_delay  = cfg["delay"]
        self.req_per_min    = cfg["req_per_min"]
        self._tier_label    = cfg["label"]

        # Create directories
        self.prices_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

        # Load metadata
        self._meta: dict = self._load_meta()

        # Token bucket for precise rate limiting
        self._bucket_tokens  = float(self.req_per_min)
        self._bucket_last_ts = time.monotonic()

        console.log(
            f"[green]📦 Warehouse:[/green] {self.root.resolve()}\n"
            f"   Tier: [cyan]{self._tier_label}[/cyan]  |  "
            f"Rate limit: [cyan]{self.req_per_min} req/min[/cyan]  |  "
            f"Delay: [cyan]{self.request_delay}s[/cyan]  |  "
            f"Tracked: [cyan]{len(self._meta)}[/cyan] tickers"
        )

    # ── Token bucket rate limiter ─────────────────────────────────────────────

    def _throttle(self):
        """
        Token bucket algorithm — smoother than fixed sleep.
        Refills at req_per_min rate; consumes 1 token per request.
        Blocks only when bucket is empty.
        """
        now = time.monotonic()
        elapsed = now - self._bucket_last_ts
        self._bucket_last_ts = now

        # Refill tokens based on elapsed time
        refill = elapsed * (self.req_per_min / 60.0)
        self._bucket_tokens = min(
            float(self.req_per_min),
            self._bucket_tokens + refill
        )

        if self._bucket_tokens < 1.0:
            # Not enough tokens — wait until we have 1
            wait = (1.0 - self._bucket_tokens) / (self.req_per_min / 60.0)
            time.sleep(wait)
            self._bucket_tokens = 0.0
        else:
            self._bucket_tokens -= 1.0
            # Minimum polite delay regardless of tokens
            time.sleep(self.request_delay)

    # ── Metadata helpers ──────────────────────────────────────────────────────

    def _load_meta(self) -> dict:
        if self.meta_file.exists():
            with open(self.meta_file, "r") as f:
                return json.load(f)
        return {}

    def _save_meta(self):
        with open(self.meta_file, "w") as f:
            json.dump(self._meta, f, indent=2)

    def _get_last_date(self, ticker: str) -> Optional[str]:
        """Return the last stored date for a ticker, or None."""
        return self._meta.get(ticker, {}).get("last_date")

    def _set_last_date(self, ticker: str, date_str: str, rows: int = 0):
        if ticker not in self._meta:
            self._meta[ticker] = {}
        self._meta[ticker]["last_date"] = date_str
        self._meta[ticker]["total_rows"] = (
            self._meta[ticker].get("total_rows", 0) + rows
        )
        self._meta[ticker]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Symbol universe ───────────────────────────────────────────────────────

    def get_all_symbols(self, exchanges: list[str] = None) -> pd.DataFrame:
        """
        Fetch all listed symbols from HOSE, HNX, UPCOM (or a subset).
        Returns DataFrame with columns: symbol, organ_name, exchange
        """
        exchanges = [e.upper() for e in (exchanges or list(VALID_EXCHANGES))]
        console.log(f"  📋 Fetching symbol list for: {exchanges}")

        try:
            if USE_UNIFIED:
                ref = Reference()
                df  = ref.equity.list_by_exchange(exchanges[0]) if len(exchanges) == 1 \
                      else ref.equity.list()
                # Normalise column name
                if "exchange" not in df.columns:
                    df["exchange"] = "UNKNOWN"
            else:
                listing = Listing(source="VCI")
                frames  = []
                for ex in exchanges:
                    try:
                        tmp = listing.symbols_by_exchange(exchange=ex)
                        if tmp is not None and not tmp.empty:
                            tmp["exchange"] = ex
                            frames.append(tmp)
                    except Exception:
                        pass
                df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

            if df is None or df.empty:
                console.print("[red]❌ No symbols returned[/red]")
                return pd.DataFrame()

            # Standardise column names
            df.columns = [c.lower() for c in df.columns]
            for alias in ("ticker", "stock_code", "code"):
                if alias in df.columns and "symbol" not in df.columns:
                    df = df.rename(columns={alias: "symbol"})

            # Filter requested exchanges
            if "exchange" in df.columns:
                df = df[df["exchange"].str.upper().isin(exchanges)]

            df = df.drop_duplicates(subset=["symbol"]).reset_index(drop=True)

            # Filter out CW and Futures — only keep plain stocks
            before = len(df)
            df = df[df["symbol"].apply(_is_stock)].reset_index(drop=True)
            skipped = before - len(df)
            if skipped:
                console.log(f"  ⏭ Skipped {skipped} CW/Futures symbols")

            console.log(f"  ✅ {len(df)} stock symbols found")
            return df

        except Exception as e:
            console.print(f"[red]❌ get_all_symbols error: {e}[/red]")
            return pd.DataFrame()

    # ── Fetch price ───────────────────────────────────────────────────────────

    def _fetch_price(
        self,
        ticker: str,
        start: str,
        end: str,
        max_retries: int = 5,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV with token-bucket throttling + smart rate-limit recovery.

        Key optimisation: uses Quote() directly instead of Vnstock().stock()
        → avoids Finance/Company initialisation (saves 2 extra API calls/ticker)
        → avoids ICB4 NoneType crash on unclassified symbols
        """
        for attempt in range(max_retries):
            self._throttle()
            try:
                if USE_UNIFIED:
                    df = Market().equity(ticker).ohlcv(start=start, end=end)
                else:
                    from vnstock import Quote
                    q  = Quote(source="VCI", symbol=ticker)
                    df = q.history(start=start, end=end, interval="1D")

                if df is None or df.empty:
                    return pd.DataFrame()

                df = df.copy()
                df.columns = [c.lower() for c in df.columns]

                if "time" in df.columns:
                    df["time"] = pd.to_datetime(df["time"]).dt.date
                elif "date" in df.columns:
                    df["time"] = pd.to_datetime(df["date"]).dt.date
                    df.drop(columns=["date"], inplace=True)

                for col in ("open", "high", "low", "close", "volume"):
                    if col not in df.columns:
                        df[col] = None

                df["ticker"] = ticker
                df["year"]   = pd.to_datetime(df["time"]).dt.year.astype("int16")
                df["volume"] = (
                    pd.to_numeric(df["volume"], errors="coerce")
                    .fillna(0).astype("int64")
                )
                for col in ("open", "high", "low", "close"):
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
                df = df.dropna(subset=["close"])

                # ── Data quality gate ────────────────────────────────────────
                # Reject rows that cannot be valid OHLCV bars. Logs are surfaced
                # at DEBUG level only to avoid flooding bulk-load output.
                before = len(df)
                # 1) price must be strictly positive
                df = df[df["close"] > 0]
                # 2) volume must be non-negative (NaN already coerced to 0)
                df = df[df["volume"] >= 0]
                # 3) OHLC sanity: high >= max(open, close) and low <= min(open, close)
                #    Only enforce when all four values are present.
                mask_ohlc = (
                    df[["open", "high", "low", "close"]].notna().all(axis=1)
                )
                if mask_ohlc.any():
                    valid_ohlc = (
                        (df["high"] >= df[["open", "close", "low"]].max(axis=1))
                        & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
                    )
                    df = df[~mask_ohlc | valid_ohlc]
                dropped = before - len(df)
                if dropped:
                    console.log(
                        f"  [dim yellow]⚠ {ticker}: dropped {dropped} "
                        f"invalid bar(s) (price<=0 / volume<0 / bad OHLC)[/dim yellow]"
                    )

                return df[["time","open","high","low","close","volume","ticker","year"]]

            # ✅ Bắt BaseException để catch cả SystemExit (vnstock gọi sys.exit())
            except BaseException as e:
                err     = str(e)
                err_low = err.lower()

                # SystemExit từ vnstock rate limit handler
                is_system_exit = isinstance(e, SystemExit)

                # ── Skip ngay: không phải stock ──────────────────────────────
                is_not_stock = (
                    "not a stock" in err_low
                    or "company and finance" in err_low
                    or "nonetype" in err_low
                    or "icbname" in err_low
                    or "is not subscriptable" in err_low
                    or ("retryerror" in err_low and "valueerror" in err_low)
                )
                if is_not_stock:
                    console.log(f"  [dim]⏭ {ticker}: skipped ({err[:50]})[/dim]")
                    return pd.DataFrame()

                # ── IntCastingNaN: skip, no retry ────────────────────────────
                if "intcastingna" in err_low or "castingna" in err_low:
                    console.log(f"  [dim]⏭ {ticker}: data quality — skipped[/dim]")
                    return pd.DataFrame()

                # ── Rate limit (kể cả SystemExit từ vnstock) ─────────────────
                is_rate_limit = is_system_exit or any(k in err_low for k in (
                    "rate limit", "giới hạn", "429", "too many",
                    "requests/phút", "request limit", "đã đạt",
                    "process terminated",
                ))
                if is_rate_limit:
                    wait_match = _re.search(
                        r"(?:chờ|wait)[^\d]*(\d+)", err_low
                    )
                    # Đọc số giây từ message, nếu không có dùng 45s
                    wait_sec = int(wait_match.group(1)) + 3 if wait_match else 45
                    console.log(
                        f"  [yellow]⏳ Rate limit [{ticker}] — "
                        f"sleeping {wait_sec}s "
                        f"(attempt {attempt+1}/{max_retries})[/yellow]"
                    )
                    self._bucket_tokens = 0.0
                    time.sleep(wait_sec)
                    continue

                # ── Lỗi khác: exponential backoff ────────────────────────────
                if attempt < max_retries - 1:
                    backoff = min(2 ** attempt, 30)
                    console.log(
                        f"  [dim]⚠ {ticker} (attempt {attempt+1}): "
                        f"{err[:70]} — retry in {backoff}s[/dim]"
                    )
                    time.sleep(backoff)
                elif isinstance(e, (KeyboardInterrupt, SystemExit)) and not is_rate_limit:
                    raise  # Re-raise Ctrl+C và SystemExit thật sự

        return pd.DataFrame()

    # ── Write / append parquet ────────────────────────────────────────────────

    def _write_parquet(self, df: pd.DataFrame, ticker: str):
        """
        Write DataFrame to partitioned parquet.
        Merges with existing data → deduplicates → rewrites.
        Partitioned by ticker= / year=.
        """
        if df.empty:
            return

        # Cast to schema types
        df["open"]   = df["open"].astype("float32")
        df["high"]   = df["high"].astype("float32")
        df["low"]    = df["low"].astype("float32")
        df["close"]  = df["close"].astype("float32")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
        df["year"]   = df["year"].astype("int16")

        # Contract check: reject invalid rows before they ever hit parquet
        try:
            from vnstock_contracts import validate_ohlcv
            df, report = validate_ohlcv(df, strict=False, drop_invalid=True)
            if report["dropped"] > 0:
                console.log(
                    f"  [yellow]⚠ {ticker}: contract dropped "
                    f"{report['dropped']}/{report['rows_in']} row(s)[/yellow]"
                )
            if df.empty:
                return
        except Exception as e:
            console.log(f"  [red]contract check failed for {ticker}: {e}[/red]")

        # Merge with existing data for this ticker (deduplication)
        existing = self._read_ticker(ticker)
        if not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
        else:
            combined = df.copy()

        # Deduplicate on (ticker, time)
        combined["time"] = pd.to_datetime(combined["time"]).dt.date
        combined = (
            combined
            .drop_duplicates(subset=["ticker", "time"], keep="last")
            .sort_values("time")
            .reset_index(drop=True)
        )
        combined["year"] = pd.to_datetime(combined["time"]).dt.year.astype("int16")

        # Write partitioned by year
        table = pa.Table.from_pandas(combined, schema=OHLCV_SCHEMA, safe=False)
        pq.write_to_dataset(
            table,
            root_path=str(self.prices_dir),
            partition_cols=["ticker", "year"],
            existing_data_behavior="delete_matching",
            compression="snappy",
        )

    def _read_ticker(self, ticker: str) -> pd.DataFrame:
        """Read all stored data for a ticker. Returns empty DataFrame if none."""
        ticker_dir = self.prices_dir / f"ticker={ticker}"
        if not ticker_dir.exists():
            return pd.DataFrame()
        try:
            dataset = ds.dataset(str(ticker_dir), format="parquet", partitioning="hive")
            df = dataset.to_table().to_pandas()
            df["ticker"] = ticker   # restore partition column dropped by pyarrow
            return df
        except Exception:
            return pd.DataFrame()

    # ── PUBLIC API ────────────────────────────────────────────────────────────

    def initial_bulk_load(
        self,
        exchanges: list[str] = None,
        skip_existing: bool = True,
        start_override: str = None,
    ):
        """
        Download full history for every listed stock.

        Args:
            exchanges      : ["HOSE","HNX","UPCOM"] or subset
            skip_existing  : Skip tickers already in warehouse
            start_override : Force a specific start date (e.g. "2020-01-01")
        """
        console.rule("[bold cyan]📥 Initial Bulk Load[/bold cyan]")
        symbols_df = self.get_all_symbols(exchanges)
        if symbols_df.empty:
            return

        symbols = symbols_df["symbol"].tolist()
        if skip_existing:
            before = len(symbols)
            symbols = [s for s in symbols if self._get_last_date(s) is None]
            console.log(f"  ⏭ Skipping {before - len(symbols)} already-loaded tickers")

        if not symbols:
            console.print("[green]✅ All tickers already loaded.[/green]")
            return

        today = datetime.now().strftime("%Y-%m-%d")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading...", total=len(symbols))

            for i, ticker in enumerate(symbols):
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

                start = start_override or DEFAULT_START
                df    = self._fetch_price(ticker, start, today)

                if not df.empty:
                    self._write_parquet(df, ticker)
                    last = str(df["time"].max())
                    self._set_last_date(ticker, last, rows=len(df))

                # Checkpoint save every batch_size tickers
                if (i + 1) % self.batch_size == 0:
                    self._save_meta()

        self._save_meta()
        self._print_stats()

    def daily_sync(self, exchanges: list[str] = None):
        """
        Incremental update: only fetch new bars since the last stored date.
        Safe to run multiple times — deduplication handles overlaps.
        """
        console.rule("[bold green]🔄 Daily Sync[/bold green]")

        # Sync known tickers first; optionally add new listings
        symbols_df = self.get_all_symbols(exchanges)
        all_tickers = symbols_df["symbol"].tolist() if not symbols_df.empty else []

        # Tickers in warehouse
        known = list(self._meta.keys())
        # New listings not yet in warehouse
        new_listings = [t for t in all_tickers if t not in known]

        to_sync = known + new_listings
        if not to_sync:
            console.print("[yellow]⚠ No tickers to sync.[/yellow]")
            return

        today    = datetime.now().strftime("%Y-%m-%d")
        updated  = 0
        no_new   = 0
        errors   = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing...", total=len(to_sync))

            for i, ticker in enumerate(to_sync):
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

                last_date = self._get_last_date(ticker)

                # Start 1 day after last stored date to avoid redundant fetch
                if last_date:
                    fetch_start = (
                        datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
                    ).strftime("%Y-%m-%d")
                else:
                    fetch_start = DEFAULT_START

                # Skip if already up-to-date
                if fetch_start > today:
                    no_new += 1
                    time.sleep(0.05)
                    continue

                df = self._fetch_price(ticker, fetch_start, today)
                if not df.empty:
                    self._write_parquet(df, ticker)
                    last = str(df["time"].max())
                    self._set_last_date(ticker, last, rows=len(df))
                    updated += 1
                else:
                    errors += 1

                if (i + 1) % self.batch_size == 0:
                    self._save_meta()

        self._save_meta()
        console.print(
            f"\n[green]✅ Sync complete:[/green]  "
            f"Updated: [cyan]{updated}[/cyan]  |  "
            f"Already current: [dim]{no_new}[/dim]  |  "
            f"Errors: [red]{errors}[/red]"
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(
        self,
        ticker: str,
        start: str = None,
        end: str   = None,
        columns: list[str] = None,
    ) -> pd.DataFrame:
        """
        Load stored OHLCV for a single ticker. Ultra-fast via partition pruning.

        Args:
            ticker  : e.g. "FPT"
            start   : "YYYY-MM-DD" (optional)
            end     : "YYYY-MM-DD" (optional)
            columns : subset of columns to load (default: all)

        Returns:
            DataFrame sorted by time

        Example (5 years of FPT in <1 second):
            df = wh.query("FPT", start="2020-01-01")
        """
        ticker_dir = self.prices_dir / f"ticker={ticker.upper()}"
        if not ticker_dir.exists():
            console.print(f"[yellow]⚠ No data for {ticker}[/yellow]")
            return pd.DataFrame()

        # Build year filter for partition pruning
        filters = []
        if start:
            y_start = int(start[:4])
            filters.append(("year", ">=", y_start))
        if end:
            y_end = int(end[:4])
            filters.append(("year", "<=", y_end))

        dataset = ds.dataset(
            str(ticker_dir),
            format="parquet",
            partitioning="hive",
        )

        # Apply partition filter + optional column projection
        scan_args = {}
        if filters:
            pa_filter = None
            for col, op, val in filters:
                expr = ds.field(col) >= val if op == ">=" else ds.field(col) <= val
                pa_filter = expr if pa_filter is None else pa_filter & expr
            scan_args["filter"] = pa_filter
        if columns:
            scan_args["columns"] = columns

        df = dataset.to_table(**scan_args).to_pandas()
        df["ticker"] = ticker.upper()

        # Fine-grained date filter (partition only pruned by year)
        df["time"] = pd.to_datetime(df["time"])
        if start:
            df = df[df["time"] >= pd.Timestamp(start)]
        if end:
            df = df[df["time"] <= pd.Timestamp(end)]

        return df.sort_values("time").reset_index(drop=True)

    def query_multi(
        self,
        tickers: list[str],
        start: str = None,
        end: str   = None,
    ) -> pd.DataFrame:
        """Load and concatenate data for multiple tickers."""
        frames = [self.query(t, start, end) for t in tickers]
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit(
        self,
        fix: bool = False,
        sample: int = 0,
    ) -> pd.DataFrame:
        """
        Kiểm tra chất lượng toàn bộ dữ liệu trong warehouse.

        Checks:
          1. File tồn tại nhưng rỗng (0 rows)
          2. Thiếu cột OHLCV
          3. Giá trị NaN trong close/volume
          4. Logic OHLCV sai (high < low, close < 0)
          5. Dữ liệu trùng lặp (duplicate dates)
          6. Khoảng trống lớn bất thường (gap > 10 ngày làm việc)
          7. So sánh last_date trong meta vs thực tế trong file

        Args:
            fix    : Tự động xóa meta của tickers lỗi để re-download
            sample : Nếu > 0, chỉ kiểm tra N tickers ngẫu nhiên (test nhanh)

        Returns:
            DataFrame báo cáo, 1 dòng/ticker
        """
        console.rule("[bold yellow]🔍 Warehouse Audit[/bold yellow]")

        tickers = list(self._meta.keys())
        if sample > 0:
            import random
            tickers = random.sample(tickers, min(sample, len(tickers)))
            console.log(f"  [dim]Sample mode: checking {len(tickers)} tickers[/dim]")

        report   = []
        to_refix = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Auditing...", total=len(tickers))

            for ticker in tickers:
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

                row = {
                    "ticker":      ticker,
                    "status":      "✅ OK",
                    "issues":      [],
                    "rows":        0,
                    "date_min":    None,
                    "date_max":    None,
                    "meta_last":   self._meta.get(ticker, {}).get("last_date"),
                    "nulls":       0,
                    "duplicates":  0,
                    "ohlc_errors": 0,
                    "max_gap_days":0,
                }

                try:
                    df = self._read_ticker(ticker)

                    # 1. File rỗng
                    if df.empty:
                        row["issues"].append("EMPTY_FILE")
                        row["status"] = "❌ Error"
                        to_refix.append(ticker)
                        report.append(row)
                        continue

                    df["time"] = pd.to_datetime(df["time"])
                    df = df.sort_values("time").reset_index(drop=True)

                    row["rows"]     = len(df)
                    row["date_min"] = str(df["time"].min().date())
                    row["date_max"] = str(df["time"].max().date())

                    # 2. Thiếu cột
                    missing_cols = [c for c in ("open","high","low","close","volume")
                                    if c not in df.columns]
                    if missing_cols:
                        row["issues"].append(f"MISSING_COLS:{missing_cols}")

                    # 3. NaN trong close
                    null_count = df["close"].isna().sum()
                    if null_count > 0:
                        row["nulls"] = int(null_count)
                        row["issues"].append(f"NULL_CLOSE:{null_count}")

                    # 4. Logic OHLCV sai
                    if {"high","low","close"}.issubset(df.columns):
                        bad = (
                            (df["high"] < df["low"]) |
                            (df["close"] < 0)
                        ).sum()
                        if bad > 0:
                            row["ohlc_errors"] = int(bad)
                            row["issues"].append(f"OHLC_LOGIC:{bad}")

                    # 5. Duplicate dates
                    dups = df["time"].duplicated().sum()
                    if dups > 0:
                        row["duplicates"] = int(dups)
                        row["issues"].append(f"DUPLICATES:{dups}")

                    # 6. Gap lớn (> 10 ngày calendar, bỏ qua cuối tuần)
                    if len(df) > 1:
                        gaps = df["time"].diff().dt.days.dropna()
                        max_gap = int(gaps.max())
                        row["max_gap_days"] = max_gap
                        if max_gap > 10:
                            row["issues"].append(f"GAP:{max_gap}d")

                    # 7. Meta vs thực tế
                    actual_last = str(df["time"].max().date())
                    if row["meta_last"] and row["meta_last"] != actual_last:
                        row["issues"].append(
                            f"META_MISMATCH(meta={row['meta_last']},file={actual_last})"
                        )
                        # Fix meta
                        self._meta[ticker]["last_date"] = actual_last

                    if row["issues"]:
                        row["status"] = "⚠️ Warning" if len(row["issues"]) <= 2 else "❌ Error"
                        if any(k in str(row["issues"]) for k in
                               ("EMPTY","MISSING_COLS","NULL_CLOSE","OHLC_LOGIC")):
                            to_refix.append(ticker)

                except Exception as e:
                    row["issues"].append(f"READ_ERROR:{str(e)[:60]}")
                    row["status"] = "❌ Error"
                    to_refix.append(ticker)

                row["issues"] = "; ".join(row["issues"]) if row["issues"] else ""
                report.append(row)

        self._save_meta()  # lưu meta fixes

        df_report = pd.DataFrame(report)

        # ── Summary ──────────────────────────────────────────────────────────
        ok      = (df_report["status"] == "✅ OK").sum()
        warn    = (df_report["status"] == "⚠️ Warning").sum()
        err     = (df_report["status"] == "❌ Error").sum()
        total_r = df_report["rows"].sum()

        t = Table(title="📊 Audit Summary", box=box.SIMPLE_HEAVY)
        t.add_column("Metric", style="bold")
        t.add_column("Value",  justify="right")
        t.add_row("Tickers checked",  f"{len(df_report):,}")
        t.add_row("✅ OK",             f"[green]{ok:,}[/green]")
        t.add_row("⚠️  Warning",       f"[yellow]{warn:,}[/yellow]")
        t.add_row("❌ Error",          f"[red]{err:,}[/red]")
        t.add_row("Total rows stored", f"{total_r:,}")
        t.add_row("Tickers to re-download", f"[red]{len(set(to_refix)):,}[/red]")
        console.print(t)

        # ── Top issues ────────────────────────────────────────────────────────
        issues_df = df_report[df_report["issues"] != ""].head(20)
        if not issues_df.empty:
            it = Table(title="⚠️  Issues Detail (top 20)", box=box.SIMPLE_HEAVY)
            it.add_column("Ticker", style="cyan", width=10)
            it.add_column("Status", width=12)
            it.add_column("Rows",   justify="right", width=8)
            it.add_column("Date Range", width=24)
            it.add_column("Issues")
            for _, r in issues_df.iterrows():
                it.add_row(
                    r["ticker"], r["status"],
                    str(r["rows"]),
                    f"{r['date_min']} → {r['date_max']}",
                    r["issues"],
                )
            console.print(it)

        # ── Fix: xóa meta để re-download ────────────────────────────────────
        if fix and to_refix:
            unique_refix = list(set(to_refix))
            console.log(
                f"[yellow]🔧 Removing meta for {len(unique_refix)} "
                f"tickers → will re-download on next --load[/yellow]"
            )
            for t in unique_refix:
                self._meta.pop(t, None)
            self._save_meta()
            console.log("[green]✅ Meta cleared. Run --load to re-download.[/green]")

        # Save report CSV
        report_path = self.meta_dir / f"audit_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        df_report.to_csv(report_path, index=False, encoding="utf-8-sig")
        console.log(f"[dim]📄 Full report saved → {report_path}[/dim]")

        return df_report

    def _print_stats(self):
        """Print warehouse summary table."""
        total_rows  = sum(v.get("total_rows", 0) for v in self._meta.values())
        total_files = sum(1 for _ in self.prices_dir.rglob("*.parquet"))
        total_size  = sum(f.stat().st_size for f in self.prices_dir.rglob("*.parquet"))
        size_mb     = total_size / 1024 / 1024

        t = Table(title="📦 Warehouse Stats", box=box.SIMPLE_HEAVY)
        t.add_column("Metric", style="bold")
        t.add_column("Value",  justify="right")
        t.add_row("Tickers tracked", f"{len(self._meta):,}")
        t.add_row("Total rows",      f"{total_rows:,}")
        t.add_row("Parquet files",   f"{total_files:,}")
        t.add_row("Storage size",    f"{size_mb:.1f} MB")
        console.print(t)

    def stats(self):
        """Public stats method."""
        self._print_stats()


# ═════════════════════════════════════════════════════════════════════════════
# Query Example — load 5 years of FPT in < 1 second
# ═════════════════════════════════════════════════════════════════════════════

def demo_query(wh: VnStockWarehouse):
    """
    Demonstrate fast querying from local Parquet.
    Expected: < 1 second even for 5 years of daily data.
    """
    import time as _time
    console.rule("[bold]⚡ Query Demo[/bold]")

    ticker = "FPT"
    t0 = _time.perf_counter()
    df = wh.query(ticker, start="2020-01-01")
    elapsed = _time.perf_counter() - t0

    if df.empty:
        console.print(f"[yellow]No data for {ticker} — run initial_bulk_load first.[/yellow]")
        return

    console.print(f"[green]✅ {len(df):,} rows loaded in {elapsed*1000:.0f} ms[/green]")
    console.print(df[["time","open","high","low","close","volume"]].tail(10).to_string(index=False))

    # Simple MA crossover on loaded data
    df = df.sort_values("time").copy()
    df["ma20"]  = df["close"].rolling(20).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    latest = df.iloc[-1]
    trend = "📈 Uptrend" if latest["ma20"] > latest["ma200"] else "📉 Downtrend"
    console.print(
        f"\n  Last close: [cyan]{latest['close']:.1f}[/cyan]"
        f"  MA20: {latest['ma20']:.1f}"
        f"  MA200: {latest['ma200']:.1f}"
        f"  → {trend}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Parquet Warehouse")
    parser.add_argument("--load",       action="store_true", help="Initial bulk load")
    parser.add_argument("--sync",       action="store_true", help="Daily incremental sync")
    parser.add_argument("--query",      metavar="TICKER",    help="Query demo for a ticker")
    parser.add_argument("--stats",      action="store_true", help="Print warehouse stats")
    parser.add_argument("--exchange",   nargs="+", default=["HOSE","HNX","UPCOM"],
                        help="Exchanges to load (default: all)")
    parser.add_argument("--start",      default=None,        help="Start date YYYY-MM-DD")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--tier", default="auto",
                        choices=["auto","community","bronze","silver","golden"])
    parser.add_argument("--root", default="data_warehouse")
    args = parser.parse_args()

    wh = VnStockWarehouse(root=args.root, tier=args.tier)

    if args.audit:
        wh.audit(fix=args.fix, sample=args.sample)

    if args.load:
        wh.initial_bulk_load(
            exchanges=args.exchange,
            start_override=args.start,
        )

    if args.sync:
        wh.daily_sync(exchanges=args.exchange)

    if args.query:
        # Load a single ticker and print stats
        import time as _t
        t0 = _t.perf_counter()
        df = wh.query(args.query.upper(), start=args.start)
        el = _t.perf_counter() - t0
        if not df.empty:
            console.print(f"[green]✅ {len(df):,} rows in {el*1000:.0f} ms[/green]")
            console.print(df.tail(10).to_string(index=False))
        else:
            console.print("[yellow]No data found.[/yellow]")

    if args.stats:
        wh.stats()

    # Default: show help if no args
    if not any([args.load, args.sync, args.query, args.stats]):
        demo_query(wh)
