"""
vnstock_fundamental_updater.py — Tải P/E, ROE toàn thị trường → Warehouse
===========================================================================
Gọi vnstock API để lấy ratio fundamentals cho tất cả cổ phiếu,
lưu vào data_warehouse/_meta/fundamentals.parquet

Run:
  python vnstock_fundamental_updater.py              # Cập nhật tất cả
  python vnstock_fundamental_updater.py --force      # Bỏ qua skip existing
  python vnstock_fundamental_updater.py --tickers VCB FPT HPG  # Cụ thể
  python vnstock_fundamental_updater.py --check      # Xem trạng thái
  python vnstock_fundamental_updater.py --report     # Báo cáo thống kê

Schedule: Chạy 1 lần/tuần (Task Scheduler hoặc cron)
"""

import argparse
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table
from rich import box

warnings.filterwarnings("ignore")
console = Console()

WAREHOUSE     = Path("data_warehouse")
PRICES_DIR    = WAREHOUSE / "prices"
META_DIR      = WAREHOUSE / "_meta"
FUND_PATH     = META_DIR / "fundamentals.parquet"
INDUSTRY_PATH = META_DIR / "industry_classification.parquet"

META_DIR.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _get_stock_tickers() -> list[str]:
    """Lấy danh sách ticker từ warehouse, lọc CW/futures."""
    import re
    _CW  = re.compile(r"^C[A-Z]{2,4}\d{4}$")
    _OLD = re.compile(r"^[A-Z]{2,4}\d{5,6}$")
    _FUT = re.compile(r"^[A-Z]{2,6}F\d{4}$")

    def ok(s: str) -> bool:
        s = s.upper()
        return bool(s) and not s[0].isdigit() and \
               not (_CW.match(s) or _OLD.match(s) or _FUT.match(s))

    return sorted([
        p.name.replace("ticker=", "")
        for p in PRICES_DIR.iterdir()
        if p.is_dir() and p.name.startswith("ticker=")
        and ok(p.name.replace("ticker=", ""))
    ])


def _load_existing() -> pd.DataFrame:
    """Load bảng fundamentals hiện có."""
    if FUND_PATH.exists():
        try:
            return pq.read_table(str(FUND_PATH)).to_pandas()
        except Exception:
            pass
    return pd.DataFrame()


def _save(df: pd.DataFrame):
    """Lưu bảng fundamentals ra Parquet."""
    schema = pa.schema([
        pa.field("ticker",          pa.string()),
        pa.field("pe",              pa.float64()),
        pa.field("pb",              pa.float64()),
        pa.field("roe",             pa.float64()),
        pa.field("roa",             pa.float64()),
        pa.field("eps",             pa.float64()),
        pa.field("net_margin",      pa.float64()),
        pa.field("gross_margin",    pa.float64()),
        pa.field("debt_ratio",      pa.float64()),
        pa.field("debt_to_equity",  pa.float64()),   # Nợ/Vốn chủ sở hữu (D/E)
        pa.field("operating_cf",    pa.float64()),   # LCT thuần từ HĐKD (tỷ VND)
        pa.field("updated_at",      pa.string()),
    ])
    for col in [f.name for f in schema]:
        if col not in df.columns:
            df[col] = None

    table = pa.Table.from_pandas(df[schema.names], schema=schema,
                                  preserve_index=False)
    pq.write_table(table, str(FUND_PATH), compression="snappy")


# Sponsor / free Finance classes accept different keyword combos across
# versions — try them in order and take the first non-empty frame, mirroring
# the proven retry loop in vnstock_dashboard.py.
_RATIO_PARAMS = [
    {"period": "year", "lang": "vi"},
    {"period": "year", "lang": "en"},
    {"period": "year"},
    {"period": "annual"},
    {},
]
_CF_PARAMS = [
    {"period": "year", "lang": "vi"},
    {"period": "year", "lang": "en"},
    {"period": "year"},
    {"period": "annual"},
    {},
]


def _try_statement(method, param_combos):
    """Call a finance-statement method trying several param combos.

    Returns the first non-empty DataFrame, or None if every combo fails or
    returns empty. Swallows TypeError (wrong kwargs) and other call errors so
    one bad signature never aborts the whole fetch.
    """
    for kw in param_combos:
        try:
            df = method(**kw)
        except TypeError:
            continue
        except Exception:
            continue
        if df is not None and hasattr(df, "empty") and not df.empty:
            return df
    return None


def _fetch_ratios(ticker: str) -> dict:
    """
    Gọi vnstock VCI để lấy ratio cho 1 ticker.
    Trả về dict với pe, pb, roe, roa, eps, net_margin, gross_margin, debt_ratio.
    """
    try:
        from vnstock_auth import get_vnstock
        fin = get_vnstock(ticker).finance
    except Exception as e:
        raise RuntimeError(f"API error: {e}")

    ratios = _try_statement(fin.ratio, _RATIO_PARAMS)
    if ratios is None or ratios.empty:
        return {}

    # iloc[0] can be a TTM/interim row where valuation ratios (P/E, ROE,
    # Debt/Equity) are NaN even though they exist in the annual row (seen on
    # VHM). Pick the most recent row that actually carries those values.
    ratio_row = _best_ratio_row(ratios)
    if ratio_row is None:
        return {}

    def get_val(df, *keys):
        """Tìm cột theo substring — hỗ trợ MultiIndex tuple."""
        for key in keys:
            key_lo = key.lower()
            for col in df.columns:
                col_str = (
                    " ".join(str(c) for c in col).lower()
                    if isinstance(col, tuple)
                    else str(col).lower()
                )
                if key_lo in col_str:
                    try:
                        v = ratio_row[col]
                        if v is None or (isinstance(v, float) and np.isnan(v)):
                            continue
                        return float(v)
                    except Exception:
                        continue
        return None

    def pct(v):
        """Convert thập phân → % nếu cần (ROE=0.167 → 16.7)."""
        if v is not None and abs(v) <= 2:
            return round(v * 100, 2)
        return round(v, 2) if v is not None else None

    # The VCI sponsor ratio table is labelled in ENGLISH (P/E, ROE (%),
    # Debt/Equity, Financial Leverage, Gross Margin (%), After-tax Profit
    # Margin (%) …) regardless of lang=. Match English first, keep Vietnamese
    # labels as a fallback for other sources.
    result = {
        "pe":           get_val(ratios, "p/e"),
        "pb":           get_val(ratios, "p/b"),
        "roe":          pct(get_val(ratios, "roe (%)", "roe")),
        "roa":          pct(get_val(ratios, "roa (%)", "roa")),
        "eps":          get_val(ratios, "eps (vnd)", "eps basic", "eps"),
        "net_margin":   pct(get_val(ratios, "after-tax profit margin",
                                    "net profit margin", "biên lợi nhuận ròng")),
        "gross_margin": pct(get_val(ratios, "gross margin", "biên lợi nhuận gộp")),
        "debt_ratio":   get_val(ratios, "financial leverage", "đòn bẩy tài chính"),
        # D/E = Nợ phải trả / Vốn chủ sở hữu. The VCI ratio table exposes it
        # directly under a few possible labels; fall back to None if absent
        # (the brief then derives nothing rather than guessing).
        "debt_to_equity": get_val(
            ratios, "nợ/vcsh", "nợ trên vốn chủ", "nợ/vốn chủ",
            "debt/equity", "debt to equity", "d/e",
        ),
    }
    return result


def _latest_row(df: "pd.DataFrame") -> "pd.Series | None":
    """Return the most recent fiscal-year row from a financial statement df.

    vnstock orders rows inconsistently across sources, so sort by any
    year-like column descending when present; otherwise assume row 0 is latest.
    """
    if df is None or df.empty:
        return None
    # VCI statements carry the fiscal period in "report_period"; other sources
    # use "year"/"năm"/"kỳ". Sort that column descending to get the latest row.
    for col in df.columns:
        col_str = (" ".join(str(c) for c in col) if isinstance(col, tuple) else str(col)).lower()
        if any(k in col_str for k in ("report_period", "period", "year", "năm", "kỳ")):
            try:
                return df.sort_values(col, ascending=False).iloc[0]
            except Exception:
                break
    return df.iloc[0]


def _best_ratio_row(df: "pd.DataFrame") -> "pd.Series | None":
    """Pick the most recent ratio row that actually carries valuation metrics.

    The VCI ratio table mixes annual and TTM/interim rows; iloc[0] can be an
    interim row where P/E, ROE and Debt/Equity are NaN (observed on VHM). Sort
    by report_period descending and return the first row that has a non-null
    value in any of P/E / ROE / Debt-to-Equity; fall back to row 0.
    """
    if df is None or df.empty:
        return None

    # Sort newest-first by the period column when present.
    sdf = df
    for col in df.columns:
        col_str = (" ".join(str(c) for c in col) if isinstance(col, tuple) else str(col)).lower()
        if "report_period" in col_str or "year id" in col_str or col_str == "period":
            try:
                sdf = df.sort_values(col, ascending=False)
                break
            except Exception:
                pass

    # Columns that signal a "real" ratio row.
    key_cols = []
    for col in df.columns:
        cs = (" ".join(str(c) for c in col).lower() if isinstance(col, tuple) else str(col).lower())
        if cs in ("p/e", "p/b") or "roe (%)" in cs or "debt to equity" in cs or "debt/equity" in cs:
            key_cols.append(col)

    if key_cols:
        for _, row in sdf.iterrows():
            for kc in key_cols:
                try:
                    v = row[kc]
                except Exception:
                    continue
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    return row
    return sdf.iloc[0]


def _operating_cf_from_row(row) -> float | None:
    """Find net operating cash flow (raw VND) in a cash-flow statement row.

    Banks label it "Net cash from operating activities"; non-banks use
    variants like "Net cash flows from operating activities". Match any column
    containing net + cash + operating while excluding section subtotals and
    the "before CIT / changes in working capital" intermediate lines.
    """
    # 1. Specific labels first (covers Vietnamese sources + exact bank label)
    for key in (
        "lưu chuyển tiền thuần từ hoạt động kinh doanh",
        "lưu chuyển tiền thuần từ hđ kinh doanh",
        "net cash from operating",
        "operating cash flow",
        "lct thuần từ hđkd",
    ):
        for col in row.index:
            cs = (" ".join(str(c) for c in col).lower()
                  if isinstance(col, tuple) else str(col).lower())
            if key in cs:
                try:
                    v = row[col]
                    if v is not None and not (isinstance(v, float) and np.isnan(v)):
                        return float(v)
                except Exception:
                    continue

    # 2. Robust fallback: net + cash + operating, minus subtotal/intermediate lines
    _exclude = ("before", "investing", "financing", "changes", "working")
    for col in row.index:
        cs = (" ".join(str(c) for c in col).lower()
              if isinstance(col, tuple) else str(col).lower())
        if all(w in cs for w in ("net", "cash", "operating")) and \
           not any(x in cs for x in _exclude):
            try:
                v = row[col]
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    return float(v)
            except Exception:
                continue
    return None


def _annual_operating_cf(df: "pd.DataFrame") -> float | None:
    """Latest annual / trailing-twelve-month operating cash flow (raw VND).

    VCI returns QUARTERLY cash-flow rows even when 'year' is requested, so the
    single latest row is just one quarter — e.g. FPT's Q1 working-capital
    outflow shows -2,847.8 tỷ while the full year is strongly positive. Detect
    quarterly data (a fiscal year appearing in >1 row) and sum the 4 most recent
    periods (TTM). For genuinely annual data, use the latest row unchanged.
    """
    if df is None or df.empty:
        return None
    import re as _re

    period_col = None
    for col in df.columns:
        cs = (" ".join(str(c) for c in col) if isinstance(col, tuple) else str(col)).lower()
        if any(k in cs for k in ("report_period", "period", "year", "năm", "kỳ")):
            period_col = col
            break

    sdf = df
    if period_col is not None:
        try:
            sdf = df.sort_values(period_col, ascending=False)
        except Exception:
            sdf = df

    # Detect quarterly: a fiscal year repeated across rows. If report_period
    # carries no parseable year (e.g. integer period-ids), fall back to row count
    # — a financial statement with >12 rows is far too long to be annual for a
    # VN-listed company, so it must be sub-annual.
    quarterly = False
    years = []
    if period_col is not None:
        years = [m.group() for v in sdf[period_col]
                 if (m := _re.search(r"(?:19|20)\d{2}", str(v)))]
    if years:
        from collections import Counter
        quarterly = max(Counter(years).values()) >= 2
    elif len(sdf) > 12:
        quarterly = True

    if quarterly:
        vals = [v for _, row in sdf.head(4).iterrows()
                if (v := _operating_cf_from_row(row)) is not None]
        return sum(vals) if vals else None

    row = _latest_row(df)
    return _operating_cf_from_row(row) if row is not None else None


def _fetch_cash_flow(ticker: str) -> dict:
    """Fetch latest annual / TTM net operating cash flow (tỷ VND) for one ticker.

    Returns {"operating_cf": <tỷ VND>} or {} on any failure — best-effort so a
    single missing statement never aborts the whole update run.
    """
    try:
        from vnstock_auth import get_vnstock
        cf = _try_statement(get_vnstock(ticker).finance.cash_flow, _CF_PARAMS)
    except Exception:
        return {}

    val = _annual_operating_cf(cf)
    if val is None:
        return {}
    return {"operating_cf": round(val / 1e9, 1)}  # raw VND → tỷ VND


def _row_find_all(row, *words) -> float | None:
    """Return the value of the row cell whose column name contains ALL given
    words (case-insensitive). Robust to punctuation/apostrophes, e.g.
    ("owner", "equity") matches "OWNER'S EQUITY"."""
    wanted = [w.lower() for w in words]
    for col in row.index:
        col_str = (
            " ".join(str(c) for c in col).lower()
            if isinstance(col, tuple) else str(col).lower()
        )
        if all(w in col_str for w in wanted):
            try:
                v = row[col]
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                return float(v)
            except Exception:
                continue
    return None


def _fetch_debt_to_equity(ticker: str) -> float | None:
    """Compute D/E = Tổng nợ phải trả / Vốn chủ sở hữu from the balance sheet.

    More reliable than the ratio table's Debt/Equity, which VCI leaves at 0
    for banks. Returns None on any failure. Units cancel (both raw VND).
    """
    try:
        from vnstock_auth import get_vnstock
        bs = _try_statement(get_vnstock(ticker).finance.balance_sheet, _CF_PARAMS)
    except Exception:
        return None
    row = _latest_row(bs)
    if row is None:
        return None
    liab = _row_find_all(row, "total", "liabilities")
    eq   = _row_find_all(row, "owner", "equity")
    if eq is None:  # some sources label it just "Equity"
        eq = _row_find_all(row, "vốn chủ sở hữu")
    if liab is not None and eq:
        try:
            return round(liab / eq, 2)
        except Exception:
            return None
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Main updater
# ═════════════════════════════════════════════════════════════════════════════

def update(
    tickers: list[str] | None = None,
    force: bool = False,
    delay: float = 0.5,
    batch_save: int = 50,
):
    """
    Tải P/E, ROE cho từng ticker, lưu vào warehouse.

    Args:
        tickers   : Danh sách cụ thể (None = tất cả từ warehouse)
        force     : True = update kể cả đã có dữ liệu
        delay     : Thời gian chờ giữa các API call (giây)
        batch_save: Lưu file sau mỗi N ticker
    """
    all_tickers = tickers or _get_stock_tickers()
    existing    = _load_existing()

    # Index các ticker đã có. After a schema upgrade (new debt_to_equity /
    # operating_cf columns) the old rows lack those fields, so refetch once to
    # backfill them — otherwise skipped tickers would never get cash-flow data.
    done_set = set()
    if not existing.empty and not force:
        _has_new_cols = {"debt_to_equity", "operating_cf"} <= set(existing.columns)
        if _has_new_cols:
            done_set = set(existing["ticker"].tolist())
        else:
            console.print(
                "[yellow]⚠ Schema cũ thiếu debt_to_equity/operating_cf "
                "→ refetch để bổ sung cash flow + D/E.[/yellow]"
            )

    to_fetch = [t for t in all_tickers if t not in done_set]

    console.rule("[bold cyan]📥 Fundamental Updater[/bold cyan]")
    console.print(
        f"  Total tickers: [cyan]{len(all_tickers):,}[/cyan]  |  "
        f"Already done: [green]{len(done_set):,}[/green]  |  "
        f"To fetch: [yellow]{len(to_fetch):,}[/yellow]\n"
    )

    if not to_fetch:
        console.print("[green]✅ Tất cả đã cập nhật. Dùng --force để cập nhật lại.[/green]")
        return

    rows   = existing.to_dict("records") if not existing.empty else []
    errors = 0
    ok_cnt = 0
    kept   = 0  # empty fetch but existing good data preserved

    # Tickers that already hold a usable ratio (pe or roe) — used to avoid
    # overwriting good data with a NaN placeholder when a refetch comes back
    # empty (e.g. transient API hiccup).
    have_data = set()
    if not existing.empty:
        for _col in ("pe", "roe"):
            if _col in existing.columns:
                have_data |= set(existing.loc[existing[_col].notna(), "ticker"])

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("Fetching...", total=len(to_fetch))

        for i, ticker in enumerate(to_fetch):
            prog.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

            try:
                data = _fetch_ratios(ticker)
                # "Usable" = at least one non-None ratio value (a dict of all
                # None means the statement was empty / unparseable).
                if data and any(v is not None for v in data.values()):
                    # Cash flow is a second (slower) statement call — merge it in.
                    # Failure here is non-fatal: the ratio data still gets saved.
                    try:
                        data.update(_fetch_cash_flow(ticker))
                    except Exception:
                        pass
                    # Ratio table leaves Debt/Equity at 0 for banks → derive a
                    # reliable D/E from the balance sheet when it's missing/0.
                    if not data.get("debt_to_equity"):
                        try:
                            _de = _fetch_debt_to_equity(ticker)
                            if _de is not None:
                                data["debt_to_equity"] = _de
                        except Exception:
                            pass
                    data["ticker"]     = ticker
                    data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
                    rows.append(data)
                    ok_cnt += 1
                elif ticker in have_data:
                    # Refetch came back empty but we already have good data —
                    # keep the existing row instead of wiping it with NaN.
                    kept += 1
                else:
                    # Never had data → write NaN placeholder so --check counts it
                    rows.append({
                        "ticker":     ticker,
                        "updated_at": datetime.now().strftime("%Y-%m-%d"),
                    })
            except Exception as e:
                errors += 1
                prog.console.print(f"  [dim red]✗ {ticker}: {e}[/dim red]")

            # Batch save
            if (i + 1) % batch_save == 0:
                df = pd.DataFrame(rows).drop_duplicates("ticker", keep="last")
                _save(df)
                prog.console.print(
                    f"  [dim]💾 Saved batch {i+1}/{len(to_fetch)} "
                    f"({ok_cnt} OK, {errors} errors)[/dim]"
                )

            time.sleep(delay)

    # Final save
    df = pd.DataFrame(rows).drop_duplicates("ticker", keep="last")
    _save(df)

    console.print(f"\n[green]✅ Done![/green]")
    console.print(
        f"  OK: [green]{ok_cnt}[/green]  |  Errors: [red]{errors}[/red]"
        f"  |  Giữ data cũ: [yellow]{kept}[/yellow]"
    )
    if ok_cnt == 0 and errors == 0:
        console.print(
            "[yellow]⚠ Không lấy được ratio nào (statement rỗng). "
            "Chạy thử: [bold]python vnstock_fundamental_updater.py --diag VCB[/bold] "
            "để xem API trả gì.[/yellow]"
        )
    console.print(f"  Saved → [cyan]{FUND_PATH}[/cyan]")

    return df


def check():
    """Xem trạng thái hiện tại của fundamentals warehouse."""
    all_tickers = _get_stock_tickers()
    existing    = _load_existing()

    console.rule("[bold]📊 Fundamental Warehouse Status[/bold]")
    if existing.empty:
        console.print("[yellow]⚠ Chưa có dữ liệu. Chạy updater để tải về.[/yellow]")
        return

    total   = len(existing)

    def _cov(col: str) -> str:
        if col not in existing.columns:
            return "—  (cột chưa có)"
        n = existing[col].notna().sum()
        return f"{n:,}  ({n/total*100:.0f}%)"

    t = Table(box=box.SIMPLE_HEAVY)
    t.add_column("Metric", style="bold")
    t.add_column("Value",  justify="right", style="cyan")
    t.add_row("Tickers trong warehouse",  f"{len(all_tickers):,}")
    t.add_row("Tickers đã có fundamental", f"{total:,}")
    t.add_row("Có P/E",            _cov("pe"))
    t.add_row("Có ROE",            _cov("roe"))
    t.add_row("Có D/E (Nợ/VCSH)",  _cov("debt_to_equity"))
    t.add_row("Có Cash Flow (HĐKD)", _cov("operating_cf"))

    if "updated_at" in existing.columns:
        latest = existing["updated_at"].max()
        t.add_row("Cập nhật lần cuối", str(latest))

    console.print(t)

    # Preview
    preview = existing[existing["pe"].notna()].head(5)
    if not preview.empty:
        console.print("\n[dim]Preview (top 5 có P/E):[/dim]")
        console.print(preview[["ticker","pe","pb","roe","roa"]].to_string(index=False))


def diag(ticker: str):
    """In ra những gì API tài chính thực sự trả về cho 1 mã.

    Dùng khi update báo OK: 0 — xem statement có rỗng không, tên cột là gì,
    để biết cần dò nhãn nào cho ratio / cash flow / D/E.
    """
    console.rule(f"[bold]🔬 Finance API diagnostic — {ticker}[/bold]")
    try:
        from vnstock_auth import get_vnstock
        fin = get_vnstock(ticker).finance
    except Exception as e:
        console.print(f"[red]✗ Không tạo được Finance object: {e}[/red]")
        return

    for name, method, params in (
        ("ratio",            getattr(fin, "ratio", None),            _RATIO_PARAMS),
        ("cash_flow",        getattr(fin, "cash_flow", None),        _CF_PARAMS),
        ("balance_sheet",    getattr(fin, "balance_sheet", None),    _CF_PARAMS),
        ("income_statement", getattr(fin, "income_statement", None), _CF_PARAMS),
    ):
        console.print(f"\n[bold cyan]── {name}() ──[/bold cyan]")
        if method is None:
            console.print("  [red]method không tồn tại trên Finance[/red]")
            continue
        df = _try_statement(method, params)
        if df is None:
            console.print("  [yellow]→ rỗng / lỗi với mọi bộ tham số[/yellow]")
            continue
        console.print(f"  shape = {df.shape}")
        cols = [
            " | ".join(str(c) for c in col) if isinstance(col, tuple) else str(col)
            for col in df.columns
        ]
        console.print(f"  columns ({len(cols)}):")
        for c in cols[:60]:
            console.print(f"    • {c}")
        if len(cols) > 60:
            console.print(f"    … (+{len(cols)-60} cột nữa)")

    # Show what the updater would actually extract — confirms label matching,
    # latest-row selection, and units (e.g. operating_cf magnitude).
    console.print("\n[bold green]── Giá trị updater parse được ──[/bold green]")
    try:
        ratios = _fetch_ratios(ticker)
    except Exception as e:
        ratios = {"error": str(e)}
    cf = _fetch_cash_flow(ticker)
    de_bs = _fetch_debt_to_equity(ticker)
    console.print(f"  ratios: {ratios}")
    console.print(f"  cash_flow: {cf}")
    console.print(f"  D/E (từ balance sheet): {de_bs}")
    console.print(
        "  [dim](operating_cf đơn vị tỷ VND; D/E ngân hàng ~8-15 là bình thường)[/dim]"
    )

    # List every "operating" cash-flow line + its latest value so we can verify
    # the matcher picked the right column (raw VND).
    try:
        from vnstock_auth import get_vnstock
        _cf_df = _try_statement(get_vnstock(ticker).finance.cash_flow, _CF_PARAMS)
        _row = _latest_row(_cf_df)
        if _row is not None:
            console.print("\n  [dim]Các cột cash flow chứa 'operating':[/dim]")
            for col in _row.index:
                cs = (" ".join(str(c) for c in col) if isinstance(col, tuple) else str(col))
                if "operating" in cs.lower():
                    try:
                        rv = _row[col]
                        rv_ty = f"{float(rv)/1e9:,.1f} tỷ" if rv is not None and not (isinstance(rv, float) and np.isnan(rv)) else "—"
                    except Exception:
                        rv_ty = "—"
                    console.print(f"    • {cs}  =  {rv_ty}")

        # Show report_period values + the annual/TTM decision so we can see the
        # granularity (year vs quarter) the matcher is working with.
        pc = next((c for c in _cf_df.columns
                   if "report_period" in str(c).lower()), None)
        if pc is not None:
            console.print(f"\n  [dim]report_period (head 8): "
                          f"{list(_cf_df[pc].head(8))}[/dim]")
            console.print(f"  [dim]_annual_operating_cf (TTM/năm) = "
                          f"{_annual_operating_cf(_cf_df)} VND[/dim]")
    except Exception:
        pass


def report():
    """Báo cáo median P/E, ROE theo ngành."""
    existing = _load_existing()
    if existing.empty:
        console.print("[yellow]⚠ Chưa có dữ liệu fundamentals.[/yellow]")
        return

    # Load industry map
    if not INDUSTRY_PATH.exists():
        console.print("[yellow]⚠ Chưa có industry_classification.parquet.[/yellow]")
        return

    industry_df = pq.read_table(
        str(INDUSTRY_PATH), columns=["ticker","primary_industry"]
    ).to_pandas()
    industry_df = industry_df.rename(columns={"primary_industry": "industry"})

    merged = existing.merge(industry_df, on="ticker", how="left")
    merged["industry"] = merged["industry"].fillna("Khác")

    grouped = merged.groupby("industry").agg(
        count=("ticker", "count"),
        median_pe=("pe",  lambda x: round(x.dropna().median(), 1)),
        median_pb=("pb",  lambda x: round(x.dropna().median(), 1)),
        median_roe=("roe", lambda x: round(x.dropna().median(), 1)),
        median_roa=("roa", lambda x: round(x.dropna().median(), 1)),
    ).reset_index().sort_values("count", ascending=False)

    t = Table(title="📐 Median Fundamentals by Industry", box=box.SIMPLE_HEAVY)
    t.add_column("Ngành",      style="cyan", min_width=25)
    t.add_column("Số mã",      justify="right")
    t.add_column("P/E",        justify="right")
    t.add_column("P/B",        justify="right")
    t.add_column("ROE%",       justify="right")
    t.add_column("ROA%",       justify="right")

    for _, row in grouped.iterrows():
        t.add_row(
            str(row["industry"])[:30],
            str(int(row["count"])),
            f"{row['median_pe']:.1f}" if not pd.isna(row["median_pe"]) else "—",
            f"{row['median_pb']:.1f}" if not pd.isna(row["median_pb"]) else "—",
            f"{row['median_roe']:.1f}" if not pd.isna(row["median_roe"]) else "—",
            f"{row['median_roa']:.1f}" if not pd.isna(row["median_roa"]) else "—",
        )
    console.print(t)


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Tải P/E, ROE toàn thị trường vào warehouse"
    )
    parser.add_argument("--tickers", nargs="+", help="Chỉ cập nhật các mã này")
    parser.add_argument("--force",   action="store_true", help="Cập nhật lại kể cả đã có")
    parser.add_argument("--delay",   type=float, default=0.5, help="Delay giữa API calls (giây)")
    parser.add_argument("--check",   action="store_true", help="Xem trạng thái warehouse")
    parser.add_argument("--report",  action="store_true", help="Báo cáo median theo ngành")
    parser.add_argument("--diag",    metavar="TICKER", help="In raw output API tài chính cho 1 mã")
    args = parser.parse_args()

    if args.diag:
        diag(args.diag.upper())
    elif args.check:
        check()
    elif args.report:
        report()
    else:
        update(
            tickers=args.tickers,
            force=args.force,
            delay=args.delay,
        )
