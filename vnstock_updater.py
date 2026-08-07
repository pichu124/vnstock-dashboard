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
from vnstock_auth import ensure_api_key, get_vnstock, has_sponsor_package
from vnstock_parquet_io import read_year_frames, write_table_atomic

try:
    from vnstock_data import Reference
    USE_UNIFIED = True
    ensure_api_key()
    console.log("[green]✅ Using vnstock_data (Sponsor)[/green]")
except ImportError:
    USE_UNIFIED = False
    try:
        # Verify vnstock is importable (new Quote API used via get_vnstock shim)
        try:
            from vnstock.api.quote import Quote  # type: ignore  # noqa: F401
        except ImportError:
            from vnstock import Quote  # type: ignore  # noqa: F401
        ensure_api_key()
        # Rate limit depends on the API KEY tier, not which Python package
        # we're calling. vnstock_auth.has_sponsor_package() reflects whether
        # a Sponsor package is installed (vnii / vnstock_data) — even if
        # vnstock_data is broken, vnii being present means the device is
        # registered as Sponsor and the key won't be downgraded.
        if has_sponsor_package():
            console.log(
                "[green]✅ Using vnstock + Sponsor API key "
                "(600 req/min)[/green]"
            )
        else:
            console.log(
                "[yellow]⚠ Using vnstock free tier "
                "(60 req/min — install vnii for Sponsor)[/yellow]"
            )
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
    """Ngày giao dịch cuối cùng có trong warehouse cho một ticker.

    Quét MỌI file parquet của năm mới nhất (không chỉ file đầu tiên) — year-dir
    có thể chứa Dropbox conflicted copy mang data mới hơn file chính."""
    for year_dir in sorted(ticker_dir.glob("year=*"), reverse=True):
        best: date | None = None
        for pf in year_dir.glob("*.parquet"):
            try:
                df = pq.read_table(str(pf), columns=["time"]).to_pandas()
                if not df.empty:
                    t = pd.to_datetime(df["time"]).max().date()
                    if best is None or t > best:
                        best = t
            except Exception:
                continue
        if best is not None:
            return best
    return None




def _read_year(ticker_dir: Path, year: int) -> pd.DataFrame:
    """Đọc data một năm — gộp MỌI file parquet trong year-dir (Dropbox có thể
    đẻ "conflicted copy" cạnh file chính; đọc một file là mất data mới nếu nó
    nằm ở file kia). File mới nhất (mtime) thắng khi trùng ngày.

    `strict=False`: file hỏng được CÁCH LY + cảnh báo rồi đi tiếp — updater
    tự lành được vì `_get_last_date` bỏ qua file không đọc được → rơi về năm
    trước → refetch nguyên năm từ API (xem vnstock_parquet_io)."""
    frames = read_year_frames(ticker_dir / f"year={year}", strict=False)
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["time"], keep="last")
    return merged.sort_values("time").reset_index(drop=True)


def _write_year(ticker_dir: Path, year: int, df: pd.DataFrame):
    """Ghi dữ liệu năm vào parquet, ghi đè file cũ."""
    year_dir = ticker_dir / f"year={year}"
    year_dir.mkdir(parents=True, exist_ok=True)

    # Giữ tên file cũ nếu có, tạo tên mới nếu chưa có
    # Luôn ghi về file canonical — trước đây "existing[0]" khiến updater ghi
    # vào bản conflicted copy của Dropbox (xếp trước theo alphabet) trong khi
    # loader đọc file khác → kho "tươi mà vẫn cũ" (07/07/2026).
    out_path = year_dir / "prices.parquet"

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])

    # Cast về đúng schema
    df["open"]   = df["open"].astype("float32")
    df["high"]   = df["high"].astype("float32")
    df["low"]    = df["low"].astype("float32")
    df["close"]  = df["close"].astype("float32")
    df["volume"] = df["volume"].astype("int64")

    # Contract check (ticker/year are partition cols — add for validation only).
    # Dropped rows → quarantine instead of silent discard.
    try:
        from vnstock_contracts import validate_ohlcv
        ticker = ticker_dir.name.removeprefix("ticker=")
        check_df = df.assign(ticker=ticker, year=int(year))
        check_df, report = validate_ohlcv(
            check_df, strict=False, drop_invalid=True, return_dropped=True,
        )
        if report["dropped"] > 0:
            print(f"  [contract] {ticker} y{year}: dropped "
                  f"{report['dropped']}/{report['rows_in']} row(s) → quarantine")
            try:
                from vnstock_quarantine import quarantine_dropped
                warehouse_root = ticker_dir.parent.parent  # .../prices/ticker=X → root
                quarantine_dropped(
                    report.get("dropped_rows"),
                    report.get("dropped_reasons", "contract failure"),
                    warehouse=warehouse_root,
                )
            except Exception as qe:
                print(f"  [quarantine] {ticker}: write failed — {qe}")
        df = check_df.drop(columns=["ticker", "year"], errors="ignore")
        if df.empty:
            return
    except Exception as e:
        print(f"  [contract] warning for {ticker_dir.name} y{year}: {e}")

    table = pa.Table.from_pandas(df, schema=PRICE_SCHEMA, safe=False)
    # Ghi NGUYÊN TỬ (tmp + os.replace): ghi thẳng thì process chết giữa chừng
    # để lại file cụt → lần sau bị hiểu thành "chưa có data" → mất cả năm
    # lịch sử (audit 06/08, xem vnstock_parquet_io).
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
# Fetch từ API
# ═════════════════════════════════════════════════════════════════════════════

def _normalize_price_df(df) -> pd.DataFrame:
    """Chuẩn hoá df thô từ API (mọi nguồn) → cột time/open/high/low/close/
    volume + quality gate. Dùng chung cho VCI lẫn nguồn fallback."""
    if df is None or df.empty:
        return pd.DataFrame()

    try:

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
        # Data quality gate: reject non-positive price and negative volume.
        # The Pandera contract (vnstock_contracts.OHLCVSchema) is the
        # authoritative check at write time; this filter is defense-in-depth.
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        df = df[(df["close"] > 0) & (df["volume"] >= 0)]
        df = df.sort_values("time").reset_index(drop=True)
        return df

    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}")


def _fetch_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch OHLCV từ vnstock API (nguồn CHÍNH — VCI qua sponsor shim).
    start/end: 'YYYY-MM-DD'
    Trả về DataFrame với cột: time(date), open, high, low, close, volume

    LỖI PHẢI LỘ RA NGOÀI (fix 22:55 17/07 — user bắt tại trận): bản cũ
    `except: pass` NUỐT timeout → trả df RỖNG → update_ticker tưởng
    "no_new_data" → breaker được báo OK → fallback KHÔNG BAO GIỜ kích dù
    VCI chết cả tối. Nay: cả 2 nấc đều lỗi VÀ không có data → raise lỗi
    cuối cùng (breaker đếm được, fallback KBS kích được); API trả rỗng
    THẬT không kèm lỗi (mã hủy niêm yết…) vẫn ra df rỗng như cũ.
    """
    df, last_exc = None, None
    try:
        ensure_api_key()
        df = get_vnstock(ticker).quote.history(start=start, end=end, interval="1D")
    except Exception as e:
        last_exc = e

    # Fallback: try Quote directly (works on some vnstock versions)
    if df is None or (hasattr(df, 'empty') and df.empty):
        try:
            try:
                from vnstock.api.quote import Quote  # type: ignore
            except ImportError:
                from vnstock import Quote  # type: ignore
            q = Quote(source="VCI", symbol=ticker)
            df = q.history(start=start, end=end, interval="1D")
        except Exception as e:
            last_exc = e

    if (df is None or (hasattr(df, "empty") and df.empty)) and last_exc is not None:
        raise RuntimeError(f"{type(last_exc).__name__}: {last_exc}")

    return _normalize_price_df(df)


def _fetch_prices_fallback(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch qua nguồn FALLBACK (KBS — bảng xếp hạng vnstock_source_probe
    17/07). Exception propagate cho caller phân loại; data qua CÙNG normalize
    + sẽ bị `reconcile_fallback_df` đối chiếu với warehouse trước khi ghi."""
    import vnstock_price_fallback as _fb
    try:
        from vnstock.api.quote import Quote  # type: ignore
    except ImportError:
        from vnstock import Quote  # type: ignore
    q = Quote(source=_fb.FALLBACK_SOURCE, symbol=ticker)
    return _normalize_price_df(q.history(start=start, end=end, interval="1D"))


def _get_close_on(ticker_dir: Path, d: date):
    """Close trong warehouse tại đúng ngày d (đối chiếu fallback). None khi
    không đọc được — reconcile sẽ từ chối data fallback (an toàn)."""
    try:
        y = _read_year(ticker_dir, d.year)
        if y.empty:
            return None
        y = y.copy()
        y["time"] = pd.to_datetime(y["time"]).dt.date
        row = y[y["time"] == d]
        return float(row["close"].iloc[0]) if not row.empty else None
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Core update logic
# ═════════════════════════════════════════════════════════════════════════════

def update_ticker(
    ticker: str,
    prices_dir: Path,
    today: date,
    dry_run: bool = False,
    skip_stale_days: int = 0,
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

    # Bỏ qua mã "chết" (hủy niêm yết/ngừng giao dịch lâu): nếu bar cuối quá cũ thì
    # mỗi lần chạy lại fetch+validate NHIỀU NĂM cho 0 ngày mới (BKH/SPA/SSU… last
    # 2018-2021) — đây là phần phí công lớn nhất sau khi đã song song hoá. 0 = tắt.
    if skip_stale_days and (today - last_date).days > skip_stale_days:
        result["status"] = "stale_skip"
        result["last_date"] = str(last_date)
        return result

    # Tính ngày cần fetch — refetch CẢ ngày cuối (inclusive), không phải
    # last_date + 1. Lý do (bug 2026-06-11): bar cuối có thể là bar DỞ DANG nếu
    # updater từng chạy TRONG phiên — VCI trả daily bar partial giữa phiên
    # (volume mới tính đến lúc fetch). Với fetch_from = last_date + 1 cũ, chạy
    # lại buổi tối bị "up_to_date" (fetch_from > today) → bar dở bị ĐÓNG BĂNG
    # VĨNH VIỄN (các ngày sau chỉ fetch từ hôm sau, không bao giờ refetch lại).
    # Quan sát 10/06: 379 mã mang bar 10/06 partial, Σ giá×KLGD = 6.157 tỷ
    # ≈ 57% ngày = đúng tỷ trọng phiên sáng. Merge bên dưới dedup keep="last"
    # → bar refetch đè bar dở → idempotent + tự lành các bar partial lịch sử.
    fetch_from = last_date

    # Chỉ "up_to_date" khi bar cuối ở TƯƠNG LAI (lệch đồng hồ/bar lỗi) —
    # last_date == today vẫn refetch để thay bar dở dang bằng bar chốt phiên.
    if fetch_from > today:
        result["status"] = "up_to_date"
        return result

    if dry_run:
        result["status"] = "would_update"
        result["new_days"] = (today - last_date).days
        return result

    # Fetch dữ liệu mới. Bọc qua call_with_rate_limit_retry: vnai chạm trần
    # 500 req/phút thì sys.exit (SystemExit — KHÔNG phải Exception) → từng
    # giết cả run ở 558/1724 mã (13/07). Helper ngủ theo "Chờ X giây" của
    # vnai rồi thử lại; hết lượt → RuntimeError để except dưới degrade thành
    # 1 mã lỗi thay vì sập tiến trình.
    #
    # LƯỚI ĐỠ NGUỒN (17/07, user "làm fallback đi" sau VCI outage 21h):
    # breaker mở sau N mã lỗi MẠNG liên tiếp → đi thẳng KBS (hết cày 60-90s/mã);
    # đang mở vẫn probe VCI định kỳ để tự quay về khi hồi. Data KBS phải qua
    # `reconcile_fallback_df` (đối chiếu close bar overlap với warehouse —
    # bắt lệch đơn vị ×1000 + khác adjustment basis) mới được ghi.
    # Tắt: VNSTOCK_PRICE_FALLBACK=0 → hành vi y như cũ.
    from vnstock_ratelimit import call_with_rate_limit_retry
    import vnstock_price_fallback as fb

    _kwargs = {"start": fetch_from.strftime("%Y-%m-%d"),
               "end": today.strftime("%Y-%m-%d")}
    _on_wait = lambda w, i: console.print(                       # noqa: E731
        f"  [dim yellow]⏳ {ticker}: rate-limit, chờ {w}s (lần {i})[/dim yellow]")
    use_fb = fb.enabled()
    new_df, primary_exc = None, None

    if not use_fb or fb.BREAKER.allow_primary():
        try:
            new_df = call_with_rate_limit_retry(
                _fetch_prices, ticker, on_wait=_on_wait, **_kwargs)
            if use_fb and fb.BREAKER.record_ok():
                console.print("  [green]⚡ VCI hồi phục — đóng mạch, quay về "
                              "nguồn chính[/green]")
        except Exception as e:
            primary_exc = e
            if not use_fb:
                result["status"] = "error"
                result["error"] = str(e)[:80]
                return result
            if fb.is_outage_error(str(e)):
                if fb.BREAKER.record_fail():
                    console.print(
                        f"  [yellow]⚡ VCI: {fb.BREAKER.open_after} mã lỗi mạng "
                        f"liên tiếp → MỞ MẠCH, chuyển {fb.FALLBACK_SOURCE} cho "
                        f"phần còn lại (probe lại VCI mỗi "
                        f"{fb.BREAKER.probe_every} mã)[/yellow]")
            else:
                result["status"] = "error"          # lỗi riêng của mã — không fallback
                result["error"] = str(e)[:80]
                return result

    if use_fb and new_df is None:                    # mạch mở / VCI vừa lỗi mạng
        try:
            fb_df = call_with_rate_limit_retry(
                _fetch_prices_fallback, ticker, on_wait=_on_wait, **_kwargs)
            fb_df, note = fb.reconcile_fallback_df(
                fb_df, _get_close_on(ticker_dir, last_date), last_date)
            if fb_df is None:
                result["status"] = "error"
                result["error"] = f"{fb.FALLBACK_SOURCE} fallback: {note}"[:80]
                return result
            new_df = fb_df
            result["source"] = fb.FALLBACK_SOURCE.lower()
            if note:
                result["fb_note"] = note
        except Exception as e:
            result["status"] = "error"
            result["error"] = (f"VCI: {str(primary_exc)[:36]} | "
                               f"{fb.FALLBACK_SOURCE}: {str(e)[:36]}"
                               if primary_exc else str(e)[:80])
            return result

    if new_df is None or new_df.empty:
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
    # Đếm ngày MỚI thật sự (sau last_date) — ngày refetch overlap không tính.
    result["new_days"] = int((new_df["time"] > last_date).sum())
    result["last_date"] = str(new_df["time"].max())
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Main runner
# ═════════════════════════════════════════════════════════════════════════════

def run_update(
    warehouse: str = "data_warehouse",
    tickers: list = None,
    dry_run: bool = False,
    delay: float = 0.1,
    skip_weekends: bool = True,
    workers: int = 8,
    skip_stale_days: int = 0,
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
    workers = max(1, int(workers or 1))
    console.log(f"  Tickers: {len(scan_list)} | Workers: {workers}"
                + (f" | Delay: {delay}s" if workers == 1 else "")
                + (f" | Skip stale > {skip_stale_days}d" if skip_stale_days else ""))

    # Lưới đỡ nguồn giá: breaker là singleton dùng chung giữa worker — reset
    # đầu mỗi run để outage run trước không di chứng sang run sau.
    try:
        import vnstock_price_fallback as _fb
        _fb.BREAKER.reset()
    except Exception:
        pass

    stats = {"updated": 0, "up_to_date": 0, "error": 0, "skip": 0, "fallback": 0}
    errors = []
    updated_list = []

    def _tally(result: dict) -> None:
        status = result["status"]
        if result.get("source") and status == "updated":
            stats["fallback"] += 1
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

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Updating...", total=len(scan_list))

        if workers > 1:
            # I/O-bound (each ticker = one API round-trip) → thread-parallel for a
            # near-linear speedup. Each ticker writes its own ticker=/year= dir, so
            # there's no write contention; update_ticker swallows its own errors.
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(update_ticker, t, prices_dir, today,
                                dry_run=dry_run, skip_stale_days=skip_stale_days): t
                    for t in scan_list
                }
                for fut in as_completed(futures):
                    try:
                        result = fut.result()
                    except Exception as exc:
                        result = {"ticker": futures[fut], "status": "error",
                                  "new_days": 0, "error": str(exc)[:80]}
                    _tally(result)
                    progress.update(task, advance=1,
                                    description=f"[cyan]{result['ticker']:6s}[/cyan]")
        else:
            for ticker in scan_list:
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)
                result = update_ticker(ticker, prices_dir, today, dry_run=dry_run,
                                       skip_stale_days=skip_stale_days)
                _tally(result)
                if result["status"] not in ("up_to_date", "no_new_data", "stale_skip"):
                    time.sleep(delay)

    # ── Summary ────────────────────────────────────────────────────────────────
    console.print()
    action = "Would update" if dry_run else "Updated"
    if stats.get("fallback"):
        console.print(
            f"[yellow]⚡ Fallback KBS: {stats['fallback']} mã (VCI lỗi mạng — "
            "mỗi mã đã đối chiếu close với warehouse trước khi ghi)[/yellow]")
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

    return stats


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
    parser.add_argument("--delay",     type=float, default=0.1,
                        help="Delay giữa API calls khi chạy 1 luồng (--workers 1)")
    parser.add_argument("--workers",   type=int, default=8,
                        help="Số luồng fetch song song (mặc định 8; 1 = tuần tự. "
                             "Giảm nếu API rate-limit)")
    parser.add_argument("--skip-stale-days", type=int, default=0, metavar="N",
                        help="Bỏ qua mã có bar cuối cũ hơn N ngày (mã hủy niêm yết). "
                             "0 = không bỏ. Vd 90 để bỏ mã chết, chạy nhanh hơn nhiều")
    parser.add_argument("--warehouse", default="data_warehouse",
                        help="Đường dẫn warehouse")
    parser.add_argument("--skip-if-done", action="store_true",
                        help="Skip nếu job đã chạy hôm nay (multi-machine)")
    args = parser.parse_args()

    if args.check:
        run_check(warehouse=args.warehouse, tickers=args.tickers)
    else:
        # ── Multi-machine coordination (import từ rollup để share helpers)
        if args.skip_if_done and not args.dry_run:
            try:
                import random as _rnd
                import time as _t
                from vnstock_rollup import (
                    get_hostname, get_today_vn, is_already_done_today,
                    write_pipeline_status,
                )

                hostname = get_hostname()
                jitter = _rnd.uniform(0, 30)
                console.log(f"[dim]Jitter {jitter:.1f}s trước khi check status...[/dim]")
                _t.sleep(jitter)

                done, existing = is_already_done_today("updater")
                if done:
                    other = existing.get("last_machine", "?")
                    other_time = existing.get("last_run_at", "?")
                    tickers_cnt = existing.get("tickers_updated", "?")
                    console.print(
                        f"[green]✓ Updater đã chạy hôm nay bởi máy {other}[/green]\n"
                        f"  Thời điểm: {other_time}\n"
                        f"  Tickers updated: {tickers_cnt}\n"
                        f"  → Skip trên máy này ({hostname})"
                    )
                    import sys; sys.exit(0)
            except ImportError:
                console.print("[yellow]⚠ vnstock_rollup không có — bỏ qua --skip-if-done[/yellow]")

        stats = run_update(
            warehouse=args.warehouse,
            tickers=args.tickers,
            dry_run=args.dry_run,
            delay=args.delay,
            skip_weekends=not args.force,
            workers=args.workers,
            skip_stale_days=args.skip_stale_days,
        )

        # Write pipeline status sau khi update thành công
        if (args.skip_if_done and not args.dry_run and stats is not None
                and stats.get("error", 0) == 0):
            try:
                from vnstock_rollup import (
                    get_hostname, get_today_vn, write_pipeline_status,
                )
                write_pipeline_status("updater", {
                    "last_success_date": get_today_vn().isoformat(),
                    "last_run_at": datetime.now().isoformat(timespec="seconds"),
                    "last_machine": get_hostname(),
                    "last_result": "success",
                    "tickers_updated": stats.get("updated", 0),
                    "tickers_up_to_date": stats.get("up_to_date", 0),
                })
                console.log("[dim]pipeline_status.json updated[/dim]")
            except Exception as e:
                console.log(f"[yellow]⚠ write pipeline_status: {e}[/yellow]")

        # Exit code phản ánh KẾT QUẢ (audit 06/08): trước đây script luôn
        # exit 0 nên cổng `if updater != 0: return 2` của run.py sync chỉ bắt
        # được CRASH — "500/1700 mã fetch lỗi" và "chạy sạch" ra cùng một mã
        # thoát, pipeline đêm đi tiếp như không có gì. Nay:
        #   2 = fail cứng (KHÔNG mã nào update nổi → nguồn data hỏng/mất mạng)
        #   1 = cảnh báo (có mã lỗi nhưng phần lớn xong — pipeline chạy tiếp)
        #   0 = sạch
        # Ngưỡng theo TỈ LỆ chứ không theo số tuyệt đối: vài mã hủy niêm yết
        # lỗi là chuyện thường ngày, không đáng chặn cả pipeline.
        if stats is not None:
            n_err = int(stats.get("error", 0))
            n_ok = int(stats.get("updated", 0)) + int(stats.get("up_to_date", 0))
            if n_err and n_ok == 0:
                console.print(f"[red]✗ {n_err} mã lỗi, KHÔNG mã nào update "
                              f"được → fail cứng[/red]")
                raise SystemExit(2)
            if n_err:
                console.print(f"[yellow]⚠ {n_err} mã lỗi "
                              f"({n_err / max(n_err + n_ok, 1) * 100:.1f}%) — "
                              f"cảnh báo, pipeline đi tiếp[/yellow]")
                raise SystemExit(1)
