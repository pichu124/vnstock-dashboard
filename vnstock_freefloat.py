"""
vnstock_freefloat.py — Tính freefloat thực từ cổ đông lớn (KBS API)
====================================================================
freefloat_pct = 100% - sum(ownership_percentage của cổ đông lớn đã công bố)
Lưu vào data_warehouse/_meta/freefloat.parquet

Run:
  python vnstock_freefloat.py                # Fetch tất cả tickers mới
  python vnstock_freefloat.py --force        # Fetch lại toàn bộ
  python vnstock_freefloat.py --limit 20     # Test 20 tickers
"""

import argparse
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress,
    SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn,
)

console = Console()

FREEFLOAT_SCHEMA = pa.schema([
    pa.field("ticker",             pa.string()),
    pa.field("freefloat_pct",      pa.float64()),   # 0–100 (%)
    pa.field("shareholders_count", pa.int32()),
    pa.field("fetched_at",         pa.string()),
])


def _is_stock(ticker: str) -> bool:
    return ticker.isalpha() and len(ticker) <= 5


def fetch_freefloat_for_ticker(ticker: str) -> dict | None:
    """
    Gọi company.shareholders() từ KBS, tính freefloat.
    Trả về dict hoặc None nếu lỗi / không có data.
    """
    try:
        from vnstock_auth import get_vnstock
        vn = get_vnstock(ticker, source="KBS")
        sh = vn.company.shareholders()
        if sh is None or sh.empty:
            return None

        # KBS columns: name, update_date, shares_owned, ownership_percentage
        pct_col = None
        for col in sh.columns:
            cl = col.lower()
            if "ownership_percentage" == col or "percentage" in cl or "ratio" in cl:
                pct_col = col
                break
        if pct_col is None:
            return None

        total_pct = float(
            pd.to_numeric(sh[pct_col], errors="coerce").fillna(0).sum()
        )
        freefloat_pct = round(max(0.0, min(100.0, 100.0 - total_pct)), 2)
        return {
            "ticker": ticker,
            "freefloat_pct": freefloat_pct,
            "shareholders_count": int(len(sh)),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception:
        return None


class FreefloatUpdater:
    """Batch fetch + lưu freefloat cho toàn bộ warehouse."""

    def __init__(self, warehouse: str = "data_warehouse"):
        self.meta_dir   = Path(warehouse) / "_meta"
        self.prices_dir = Path(warehouse) / "prices"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.meta_dir / "freefloat.parquet"

    # ── I/O ───────────────────────────────────────────────────────────────────

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=[f.name for f in FREEFLOAT_SCHEMA])
        return pq.read_table(str(self.path)).to_pandas()

    def save(self, df: pd.DataFrame):
        table = pa.Table.from_pandas(df, schema=FREEFLOAT_SCHEMA, safe=False)
        from vnstock_parquet_io import write_table_atomic
        write_table_atomic(table, self.path)

    def load_map(self) -> dict[str, float]:
        """Return {ticker: freefloat_pct} dict — instant lookup."""
        df = self.load()
        if df.empty:
            return {}
        return dict(zip(df["ticker"], df["freefloat_pct"]))

    # ── Tickers ───────────────────────────────────────────────────────────────

    def get_tickers(self) -> list[str]:
        if not self.prices_dir.exists():
            return []
        return sorted([
            p.name.replace("ticker=", "")
            for p in self.prices_dir.iterdir()
            if p.is_dir()
            and p.name.startswith("ticker=")
            and _is_stock(p.name.replace("ticker=", ""))
        ])

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(
        self,
        limit: int = 0,
        force: bool = False,
        delay: float = 0.15,
    ) -> pd.DataFrame:
        tickers = self.get_tickers()
        existing = self.load()
        existing_map: dict = (
            {r["ticker"]: r for r in existing.to_dict("records")}
            if not existing.empty else {}
        )

        if not force:
            tickers = [t for t in tickers if t not in existing_map]

        if limit > 0:
            tickers = tickers[:limit]

        console.log(
            f"  Freefloat: {len(tickers)} tickers to fetch "
            f"({'force-refresh' if force else 'new only'}, KBS source)"
        )

        if not tickers:
            console.log("  Freefloat: nothing to do")
            return existing

        rows = dict(existing_map)  # upsert into existing
        ok = errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
            TaskProgressColumn(), TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching freefloat...", total=len(tickers))
            for ticker in tickers:
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)
                result = fetch_freefloat_for_ticker(ticker)
                if result:
                    rows[ticker] = result
                    ok += 1
                else:
                    errors += 1
                time.sleep(delay)

        df_out = pd.DataFrame(list(rows.values()))
        if not df_out.empty:
            df_out = df_out.sort_values("ticker").reset_index(drop=True)
            self.save(df_out)

        console.print(
            f"[green]✅ Freefloat: {ok} updated[/green] | "
            f"[red]{errors} failed[/red] | "
            f"Total: {len(df_out)} tickers → {self.path}"
        )
        return df_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch real freefloat from shareholders API")
    parser.add_argument("--warehouse", default="data_warehouse")
    parser.add_argument("--limit",  type=int,   default=0,    help="Max tickers (0=all)")
    parser.add_argument("--force",  action="store_true",       help="Re-fetch existing")
    parser.add_argument("--delay",  type=float, default=0.15,  help="Delay between calls (s)")
    parser.add_argument("--show",   action="store_true",       help="Print result table")
    args = parser.parse_args()

    updater = FreefloatUpdater(args.warehouse)
    df = updater.run(limit=args.limit, force=args.force, delay=args.delay)

    if args.show and not df.empty:
        console.print("\n[bold]Kết quả freefloat (sắp xếp thấp → cao):[/bold]")
        show = df.sort_values("freefloat_pct")[["ticker", "freefloat_pct", "shareholders_count", "fetched_at"]]
        console.print(show.head(30).to_string(index=False))
