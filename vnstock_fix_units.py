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
    # Mã bị LOẠI bằng thống kê footer (max(close) ≤ ngưỡng ⇒ không thể có bar
    # sai đơn vị). Con số này là phép ĐO: trước đây không có gì ghi lại việc
    # quét toàn kho mỗi đêm tốn công vào đâu.
    skipped_by_footer: int = 0
    fixes: list[UnitFix] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ticker_count(self) -> int:
        return len({f.ticker for f in self.fixes})

    def to_dict(self) -> dict:
        return {
            "scanned_tickers": self.scanned_tickers,
            "scanned_bars": self.scanned_bars,
            "skipped_by_footer": self.skipped_by_footer,
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


# ── Lọc bằng THỐNG KÊ FOOTER, không giải nén data page ───────────────────
# `_detect_in_ticker` chỉ có thể sinh fix khi tồn tại bar `close >
# RAW_VND_THRESHOLD` (dòng `candidates = close > RAW_VND_THRESHOLD`; không có
# bar nào vượt thì nó trả [] ngay). Nên nếu **max(close) của cả lịch sử một
# mã ≤ ngưỡng**, đọc mã đó là chắc chắn phí công.
#
# Parquet ghi sẵn min/max mỗi cột trong footer. `pq.read_metadata` đọc đúng
# footer, KHÔNG giải nén data page — nên biết được max(close) gần như miễn
# phí. Đây là phép lọc **tương đương chứng minh được**, không phải phỏng
# đoán: bỏ qua đúng những mã mà đường cũ cũng sẽ không sinh fix nào.
#
# Vì sao đáng: đo 25/08 bước này 316s và ĐANG TĂNG (98s → 302s → 316s), nó
# quét ~3.125 thư mục mã (KHÔNG lọc `_is_stock` như updater) và đọc CẢ 6 cột
# trong khi chỉ dùng `time` + `close`.
#
# Không đọc được thống kê (thiếu cột, thiếu statistics, file lạ, ném lỗi) ⇒
# **ĐỌC** mã đó như cũ. Nghi ngờ thì đọc — bỏ sót một bar sai đơn vị là ghi
# số sai vào kho giá.
def _max_close_from_footer(pq_file: Path) -> "float | None":
    """max(close) đọc từ footer. None = KHÔNG kết luận được ⇒ phải đọc thật."""
    import pyarrow.parquet as _pq

    try:
        md = _pq.read_metadata(str(pq_file))
        idx = md.schema.names.index("close")
    except Exception:
        return None
    best: "float | None" = None
    for rg in range(md.num_row_groups):
        try:
            st = md.row_group(rg).column(idx).statistics
        except Exception:
            return None
        if st is None or not st.has_min_max:
            return None
        try:
            v = float(st.max)
        except (TypeError, ValueError):
            return None
        best = v if best is None else max(best, v)
    return best


def _needs_read(ticker_dir: Path) -> bool:
    """Mã này có thể chứa bar sai đơn vị không? Sai lệch về phía ĐỌC."""
    files = sorted(ticker_dir.glob("year=*/*.parquet"))
    if not files:
        return False
    for pq_file in files:
        m = _max_close_from_footer(pq_file)
        if m is None or m > RAW_VND_THRESHOLD:
            return True
    return False


def _iter_candidate_tickers(warehouse: Path):
    """Như `vnstock_anomaly._iter_warehouse_tickers` nhưng (a) bỏ qua mã mà
    footer đã chứng minh là không thể có bar sai đơn vị, (b) chỉ giải nén
    `time` + `close`.

    Trả `(ticker, df | None)` — `None` = đã LOẠI bằng footer, chỗ gọi vẫn đếm
    được là đã soi mà không phải đọc.
    """
    from vnstock_anomaly import PRICES_SUBDIR

    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        return
    for ticker_dir in sorted(prices_dir.glob("ticker=*")):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name.removeprefix("ticker=")
        if not _needs_read(ticker_dir):
            yield ticker, None
            continue
        frames: list[pd.DataFrame] = []
        for pq_file in sorted(ticker_dir.glob("year=*/*.parquet")):
            try:
                frames.append(pd.read_parquet(pq_file, columns=["time", "close"]))
            except Exception:
                try:                      # cột lạ/thiếu ⇒ đọc trọn như cũ
                    frames.append(pd.read_parquet(pq_file))
                except Exception:
                    continue
        if not frames:
            continue
        yield ticker, pd.concat(frames, ignore_index=True)


def scan(warehouse: Path, *, tickers: list[str] | None = None) -> FixReport:
    """Walk warehouse and collect all unit-mismatch bars (read-only)."""
    report = FixReport()
    target = {t.upper() for t in tickers} if tickers else None

    for ticker, df in _iter_candidate_tickers(warehouse):
        if target is not None and ticker.upper() not in target:
            continue
        report.scanned_tickers += 1
        if df is None:                    # footer đã loại — không có bar nào cần sửa
            report.skipped_by_footer += 1
            continue
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
