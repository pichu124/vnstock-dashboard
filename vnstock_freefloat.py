"""
vnstock_freefloat.py — Freefloat thực (vnstock thế hệ 6, nguồn chọn ở vnstock_auth)
====================================================================
freefloat_pct = free-float nguồn công bố (`Reference().company(t).listing()`);
nguồn không có ⇒ 100% - Σ `rate` cổ đông lớn (`Reference().company(t).shareholders()`).
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
from vnstock_auth import keep_schema_warnings

keep_schema_warnings()

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


def _num(row, col) -> float | None:
    v = pd.to_numeric(row.get(col), errors="coerce")
    return None if pd.isna(v) else float(v)


def _listing_freefloat_pct(ticker: str) -> float | None:
    """Free-float nguồn công bố, `Reference().company(t).listing()`.

    Ưu tiên `free_float_shares / outstanding_shares` (không phụ thuộc đơn vị), rồi
    `free_float_percent` (đơn vị `percent` = điểm phần trăm 0–100). Nguồn không có route
    này (`UnsupportedError`) hoặc thiếu số ⇒ None (chỗ gọi dùng cách tính dự phòng). Lỗi
    nguồn khác (mạng, hạn mức, khoá…) NÉM lên: đừng thay số công bố bằng số ước tính.
    """
    from vnstock import Reference
    from vnstock.errors import UnsupportedError
    try:
        li = Reference().company(ticker).listing()
    except UnsupportedError:
        return None
    if li is None or li.empty:
        return None
    row = li.iloc[0]
    ff_sh, out_sh = _num(row, "free_float_shares"), _num(row, "outstanding_shares")
    if ff_sh is not None and out_sh:
        return 100.0 * ff_sh / out_sh
    return _num(row, "free_float_percent")


def fetch_freefloat_for_ticker(ticker: str) -> dict | None:
    """
    Free-float của một mã: số của nguồn ở `company(t).listing()`; nguồn không có thì
    100% − Σ `rate` cổ đông lớn ở `company(t).shareholders()` (cách tính cũ).
    `shareholders_count` = số cổ đông lớn công bố. Trả None nếu lỗi / không có data.
    """
    from vnstock import Reference
    from vnstock.errors import VnstockError
    from vnstock_auth import ensure_api_key

    ensure_api_key()
    try:
        # cột v5: symbol, name, shareholder_type, total_shares, rate, date
        sh = Reference().company(ticker).shareholders()
    except VnstockError:
        return None
    if sh is None or sh.empty:
        return None

    try:
        pct = _listing_freefloat_pct(ticker)
    except VnstockError:
        return None              # lượt này lỗi ⇒ không ghi số (giữ số cũ trong kho)
    if pct is None:
        if "rate" not in sh.columns:
            return None
        # Hồ sơ v5: `rate` là PHÂN SỐ (hợp đồng: ownership_percent × 0.01) ⇒ Σ×100 ra điểm %.
        pct = 100.0 - 100.0 * float(pd.to_numeric(sh["rate"], errors="coerce").fillna(0).sum())
    return {
        "ticker": ticker,
        "freefloat_pct": round(max(0.0, min(100.0, pct)), 2),
        "shareholders_count": int(len(sh)),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


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
            f"({'force-refresh' if force else 'new only'})"
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
