"""
vnstock_runner.py — Chạy tất cả screener presets và xuất kết quả ra JSON
=========================================================================
Thiết kế để chạy tự động sau khi updater cập nhật giá (lúc ~15:35).
Kết quả lưu vào data_warehouse/_meta/screener_results.json
Dashboard Streamlit đọc file này để hiển thị.

Run:
  python vnstock_runner.py                    # Chạy tất cả presets
  python vnstock_runner.py --presets oversold momentum  # Chỉ chạy 1 số preset
  python vnstock_runner.py --warehouse data_warehouse   # Custom warehouse path

Task Scheduler: chạy lúc 15:35 (sau updater 15:30)
"""

import argparse
import json
import warnings
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# Import từ screener (cùng thư mục)
import sys
sys.path.insert(0, str(Path(__file__).parent))
from vnstock_screener import MarketScreener, PRESETS, stale_limit

from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress,
    SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
console = Console(force_terminal=True)

OUTPUT_FILE = "screener_results.json"


def run_all_presets(
    warehouse: str = "data_warehouse",
    presets: list = None,
) -> dict:
    """Chạy tất cả presets và gom kết quả vào dict."""

    screener = MarketScreener(warehouse_root=warehouse)
    preset_list = presets or list(PRESETS.keys())

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_tickers": len(screener.tickers),
        "classified_tickers": len(screener.industry_map),
        "presets": {},
        "industry_summary": {},
    }

    # ── Chạy từng preset ──────────────────────────────────────────────────────
    for preset_name in preset_list:
        if preset_name not in PRESETS:
            console.print(f"[yellow]⚠ Preset '{preset_name}' không tồn tại, bỏ qua[/yellow]")
            continue

        console.log(f"  ▶ Running preset: [cyan]{preset_name}[/cyan]")
        try:
            df = screener.scan(preset=preset_name)
            if df.empty:
                output["presets"][preset_name] = {
                    "desc": PRESETS[preset_name]["desc"],
                    "count": 0,
                    "results": [],
                }
                continue

            # Thêm thông tin ngành vào kết quả
            if screener.industry_map:
                df["industry"] = df["ticker"].map(
                    lambda t: screener.industry_map.get(t, {}).get("primary", "")
                )

            # Convert sang list of dicts, xử lý NaN
            records = []
            for _, row in df.iterrows():
                rec = {}
                for col, val in row.items():
                    if pd.isna(val) if not isinstance(val, str) else False:
                        rec[col] = None
                    elif isinstance(val, (int, float)):
                        rec[col] = round(float(val), 2)
                    else:
                        rec[col] = str(val) if val is not None else None
                records.append(rec)

            output["presets"][preset_name] = {
                "desc": PRESETS[preset_name]["desc"],
                "count": len(records),
                "results": records,
            }
            console.log(f"    ✅ {len(records)} mã")

        except Exception as e:
            console.log(f"    [red]❌ Error: {e}[/red]")
            output["presets"][preset_name] = {
                "desc": PRESETS[preset_name].get("desc", ""),
                "count": 0,
                "results": [],
                "error": str(e),
            }

    # Mã kho đứng im bị bỏ khỏi MỌI preset (`stale_lag`) — để dashboard/doctor đọc được.
    limit = stale_limit()
    output["stale_excluded"] = {"limit": limit, "count": len(screener.stale),
                                "tickers": screener.stale}
    if screener.stale:
        console.log(f"  ⏸ Bỏ {len(screener.stale):,} mã kho cũ khỏi mọi preset "
                    f"(bar cuối trễ > {limit} phiên VNINDEX)")

    # ── Thống kê ngành ────────────────────────────────────────────────────────
    if screener.industry_map:
        from collections import Counter
        counts = Counter(v["primary"] for v in screener.industry_map.values())
        output["industry_summary"] = dict(
            sorted(counts.items(), key=lambda x: -x[1])
        )

    return output


def save_results(output: dict, warehouse: str = "data_warehouse"):
    """Lưu kết quả vào _meta/screener_results.json + history snapshot."""
    meta_dir = Path(warehouse) / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    out_path = meta_dir / OUTPUT_FILE

    # Nguyên tử. `open(..., "w")` CẮT file về 0 rồi mới stream — mà dashboard
    # chủ động poll mtime file này (`_get_data_mtime` → `st.rerun()`) rồi
    # `json.load` TRẦN, không try/except. Đọc trúng cửa sổ ghi là sập trang,
    # và đó là kịch bản được lập trình để xảy ra chứ không phải xui.
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(output, out_path)

    # Save daily snapshot for alerts comparison
    history_dir = meta_dir / "screener_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    dated_path = history_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
    import shutil
    shutil.copy2(out_path, dated_path)

    # Cleanup: keep only last 30 days
    history_files = sorted(history_dir.glob("*.json"))
    for old_file in history_files[:-30]:
        old_file.unlink(missing_ok=True)

    console.print(f"[green]✅ Saved → {out_path}[/green]")
    console.print(f"[dim]📋 History → {dated_path}[/dim]")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# Market Overview — pre-compute sector metrics + breadth
# ══════════════════════════════════════════════════════════════════════════════

MARKET_OVERVIEW_FILE = "market_overview.json"


def _normalize_prices(df):
    """Normalize mixed VND/nghìn VND price units."""
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            vals = df[col].astype(float)
            mask = vals > 500
            if mask.any():
                df.loc[mask, col] = vals[mask] / 1000
    return df


# ── Nhịp gọi API dùng chung cho pool worker ──────────────────────────────
# Hạn mức Sponsor: 600 req/phút = 10 req/s (xem `vnstock_updater` khi in
# "600 req/min"). Đặt dưới mức đó để chừa biên — và vì các bước khác của phát
# có thể còn gọi mạng.
_NB_RATE_PER_SEC = 8.0
_NB_WORKERS_DEFAULT = 8
_NB_WORKERS_ENV = "VNSTOCK_NETBS_WORKERS"


def _nb_pool_size() -> int:
    """Số luồng gọi Net BS. `VNSTOCK_NETBS_WORKERS=1` là quay về tuần tự."""
    import os as _os
    try:
        n = int(_os.environ.get(_NB_WORKERS_ENV, "") or _NB_WORKERS_DEFAULT)
    except ValueError:
        n = _NB_WORKERS_DEFAULT
    return max(1, min(n, 32))


class _RatePacer:
    """Chặn TỔNG tốc độ gọi ở `per_sec`, bất kể bao nhiêu worker.

    Khoá chỉ giữ lúc tính mốc "lượt kế tiếp"; `sleep` nằm NGOÀI khoá nên các
    worker không chặn nhau — chúng chỉ xếp hàng theo thời điểm. Đây là chỗ
    khác biệt so với `sleep(0.15)` cũ: nhịp cũ áp cho MỖI lượt nối tiếp nhau
    (0,15s + round-trip, cộng dồn), nhịp mới áp cho TOÀN BỘ (round-trip chồng
    lên nhau).
    """

    def __init__(self, per_sec: float):
        import threading as _th
        self._gap = 1.0 / max(per_sec, 0.001)
        self._lock = _th.Lock()
        self._next = 0.0

    def wait(self) -> None:
        import time as _t
        with self._lock:
            now = _t.monotonic()
            slot = max(now, self._next)
            self._next = slot + self._gap
        delay = slot - now
        if delay > 0:
            _t.sleep(delay)


# #18 (30/09): mã LỚN thiếu bar phiên mới nhất (cách ly cơ sở, sync lỗi) làm
# Σ giá×KLGD hụt HỆ THỐNG mà cổng đếm SỐ MÃ (`_gtgd_baselines`, 70% trung vị
# count) không thấy: 45 mã cách ly 16–29/09 gồm FPT · VPB · GAS · TCX · PVS,
# mỗi mã vài trăm tỷ/phiên = 2,6% số mã nhưng cả nghìn tỷ GTGD. Brief in
# "+27% so với phiên trước" (17/09) rồi "thấp hơn TB" suốt hai tuần một phần
# vì thiếu data. Runner biết TỪNG mã có bar ngày nào → (a) kê mã lớn thiếu
# bar ở phiên mới nhất, (b) tổng baseline từng ngày ĐÃ LOẠI các mã đó để brief
# so cùng tập mã (`excl_missing`).
_HEAVY_GTGD_TY = 50.0          # TB giá×KLGD 22 bar ≥ 50 tỷ/phiên → mã lớn
_HEAVY_MISSING_MAX_DAYS = 45   # thiếu lâu hơn = hủy niêm yết/ngừng GD, không phải lỗ coverage


def heavy_missing(gtgd_by_ticker: dict, latest, *, min_avg: float = _HEAVY_GTGD_TY,
                  max_gap_days: int = _HEAVY_MISSING_MAX_DAYS) -> list:
    """Mã lớn (TB giá×KLGD ≥ `min_avg` tỷ/phiên trên các bar có) KHÔNG có bar
    ở ngày `latest` nhưng còn bar trong `max_gap_days` ngày trước đó. Hàm thuần:
    `gtgd_by_ticker` = {ticker: {date: giá×KLGD tỷ}}. Trả [{ticker, last_date,
    avg_gtgd}] sắp theo avg giảm dần; [] khi không có `latest`."""
    out = []
    if latest is None:
        return out
    for tk, tv in gtgd_by_ticker.items():
        if not tv:
            continue
        last = max(tv)
        if last >= latest or (latest - last).days > max_gap_days:
            continue
        avg = float(sum(tv.values()) / len(tv))
        if avg < min_avg:
            continue
        out.append({"ticker": tk, "last_date": last.isoformat(),
                    "avg_gtgd": round(avg, 1)})
    out.sort(key=lambda r: -r["avg_gtgd"])
    return out


def excl_missing_totals(totals: dict, gtgd_by_ticker: dict, missing: list) -> dict:
    """{date: total − Σ giá trị NGÀY ĐÓ của các mã đang thiếu}. Chỉ trừ khi mã
    có bar ngày đó (mã đứng từ 16/09 thì ngày 17/09 không có gì để trừ) — cùng
    tập mã với phiên mới nhất, so được % mà không lệch coverage."""
    names = [m["ticker"] for m in missing]
    return {d: float(t) - float(sum(gtgd_by_ticker.get(tk, {}).get(d, 0.0) for tk in names))
            for d, t in totals.items()}


# 3M = 60 phiên (như Net BS "3m" = tail(60)). Feed TopStock chỉ kéo ~20 phiên nên
# cửa sổ 90 ngày phủ ĐÚNG dữ liệu của 30 ngày: "NN 3M" từng bằng hệt "NN 1M" và
# analyzer đọc thành xu hướng (cờ "NN ACCUMULATING: pace 1M nhanh hơn avg 3M").
_NN_3M_MIN_SESSIONS = 60


def _nn_windows(nn_df: pd.DataFrame) -> tuple:
    """(nn_w, nn_m, nn_3m, nn_data_date): {mã: tỷ VND} của 5/20/60 phiên gần nhất.

    Phiên = ngày phân biệt CÓ trong dữ liệu NN (như `vnstock_dashboard._nn_window`),
    không đếm ngày lịch: `≥ mốc − 7 ngày` lấy cả mốc ⇒ "NN 1T" thành 6 phiên. Neo ở
    ngày mới nhất có dữ liệu, không phải đồng hồ: feed trễ như batch EOD (BĐS NN
    ~-5,277 ngày 09/06 hai phiên sau vẫn -5,275).
    Dưới `_NN_3M_MIN_SESSIONS` phiên thì nn_3m rỗng ⇒ cột NN 3M = None."""
    nn_w, nn_m, nn_3m = {}, {}, {}
    if nn_df is None or nn_df.empty:
        return nn_w, nn_m, nn_3m, None
    dates = pd.to_datetime(nn_df["date"]).dt.normalize()
    sessions = dates.drop_duplicates().nlargest(_NN_3M_MIN_SESSIONS)
    windows = [(5, nn_w), (20, nn_m)]
    if len(sessions) >= _NN_3M_MIN_SESSIONS:
        windows.append((_NN_3M_MIN_SESSIONS, nn_3m))
    for n, result_map in windows:
        filtered = nn_df[dates.isin(sessions.head(n))]
        for sym, val in filtered.groupby("symbol")["net_value"].sum().items():
            result_map[sym] = round(val / 1e9, 1)  # → tỷ VND
    return nn_w, nn_m, nn_3m, sessions.iloc[0].date().isoformat()


def build_market_overview(warehouse: str = "data_warehouse", *, fetch_nn=None,
                          fetch_net_bs=None) -> dict:
    """Sector metrics + breadth + GTGD từ kho parquet → dict của market_overview.json.

    KHÔNG gọi mạng, KHÔNG ghi file — dashboard (Tầng 2) gọi thẳng khi file runner
    ghi đã cũ. Dữ liệu ngoài kho do bên gọi đưa vào, thiếu thì cột tương ứng None:
      fetch_nn()             → DataFrame [symbol, date, net_value (VND)]
      fetch_net_bs(tickers)  → {mã: {"1w", "1m", "3m", "6m"}} (triệu cp)
    """
    import numpy as np
    import pyarrow.parquet as pq

    prices_dir = Path(warehouse) / "prices"
    industry_path = Path(warehouse) / "_meta" / "industry_classification.parquet"

    if not prices_dir.exists() or not industry_path.exists():
        console.print("[red]❌ Prices dir hoặc industry classification không tồn tại[/red]")
        return {}

    console.log("  Loading industry map...")
    ind_df = pq.read_table(
        str(industry_path), columns=["ticker", "primary_industry"]
    ).to_pandas().rename(columns={"primary_industry": "industry"})
    ind_df["industry"] = ind_df["industry"].fillna("Khác")
    valid_tickers = set(ind_df["ticker"].tolist())

    # Shares outstanding
    companies_dir = Path(warehouse) / "companies"
    shares_map = {}
    if companies_dir.exists():
        for comp_dir in companies_dir.glob("ticker=*"):
            tk = comp_dir.name.split("=")[1]
            ov_file = comp_dir / "overview.parquet"
            if ov_file.exists():
                try:
                    ov = pq.ParquetFile(str(ov_file)).read(columns=["issue_share"]).to_pandas()
                    if len(ov) > 0 and pd.notna(ov["issue_share"].iloc[0]):
                        shares_map[tk] = float(ov["issue_share"].iloc[0])
                except Exception:
                    pass

    # Freefloat lookup (optional — falls back to 30% proxy if file absent)
    freefloat_map: dict = {}
    try:
        from vnstock_freefloat import FreefloatUpdater
        freefloat_map = FreefloatUpdater(warehouse).load_map()
        console.log(f"  Freefloat map: {len(freefloat_map)} tickers loaded")
    except Exception as _ff_err:
        console.log(f"  [dim]freefloat_map not loaded: {_ff_err}[/dim]")

    from datetime import date, timedelta
    cutoff = pd.Timestamp(date.today() - timedelta(days=400))

    rows = []
    b_total = b_ma200 = b_rsi_ov = b_rsi_ob = 0
    b_adv = b_dec = b_unch = b_hi = b_lo = 0
    _gtgd_day_rows: list[tuple] = []  # (bar_date, giá×KLGD tỷ) → tổng GTGD phiên mới nhất
    _gtgd_by_ticker: dict = {}        # ticker → {date: giá×KLGD tỷ} 22 bar cuối (#18)
    _max_data_date = None  # latest stock bar date actually used (breadth data date)

    ticker_dirs = sorted(prices_dir.glob("ticker=*"))
    console.log(f"  Scanning {len(ticker_dirs)} tickers...")

    for td in ticker_dirs:
        ticker = td.name.split("=")[1]
        if len(ticker) > 5 or not ticker.isalpha():
            continue
        try:
            frames = []
            for yd in sorted(td.glob("year=*"))[-3:]:
                # mtime CŨ→MỚI + khử trùng giữ bản MỚI: Dropbox có thể đẻ "(… conflicted
                # copy …).parquet" cạnh file chính — cùng ngữ nghĩa
                # `vnstock_strategy._read_ticker_dir`, không thì KLGD/GTGD đếm 2 lần.
                for pf in sorted(yd.glob("*.parquet"), key=lambda f: f.stat().st_mtime):
                    frames.append(pq.read_table(str(pf),
                        columns=["time", "close", "volume", "high", "low"]).to_pandas())
            if not frames:
                continue
            df = pd.concat(frames, ignore_index=True)
            df["time"] = pd.to_datetime(df["time"])
            df = df.drop_duplicates("time", keep="last").sort_values("time")
            df = df[df["time"] >= cutoff]
            if len(df) < 5:
                continue
            _bar_date = df["time"].iloc[-1]
            if _max_data_date is None or _bar_date > _max_data_date:
                _max_data_date = _bar_date

            df = _normalize_prices(df)
            c = df["close"].astype(float)
            v = df["volume"].astype(float)
            last = float(c.iloc[-1])

            # Real full-day GTGD (matching value) ≈ giá × KLGD, gom THEO TỪNG
            # NGÀY cho ~22 bar gần nhất của mỗi mã (không chỉ bar cuối). `close`
            # ở thang nghìn VND, volume ở cổ phiếu → tỷ VND = close*vol/1e6.
            # Lý do theo-ngày: chạy updater GIỮA phiên kéo bar dở của HÔM NAY
            # về → "ngày mới nhất" thành phiên đang dở; brief cho ngày T vẫn
            # cần tổng của ĐÚNG ngày T (đã chốt). 22 bar → đủ ~20 phiên cho
            # baseline TB5/TB20 thật (model từng bịa "TB 20 phiên -15%" khi
            # chỉ có 5 phiên). EOD-derived → không cần WSS.
            _tv: dict = {}
            for _t, _c, _v in zip(df["time"].tail(22), c.tail(22), v.tail(22)):
                if _c > 0 and _v > 0:
                    _val = float(_c * _v / 1e6)
                    _gtgd_day_rows.append((pd.Timestamp(_t), _val))
                    _tv[pd.Timestamp(_t).date()] = _val
            if _tv:
                _gtgd_by_ticker[ticker] = _tv

            # Breadth
            b_total += 1
            if len(c) >= 200:
                ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
                if last > ema200:
                    b_ma200 += 1

            delta = c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
            if not np.isnan(rsi_val):
                if rsi_val < 30: b_rsi_ov += 1
                elif rsi_val > 70: b_rsi_ob += 1

            if len(c) >= 2:
                chg1d = c.iloc[-1] - c.iloc[-2]
                if chg1d > 0: b_adv += 1
                elif chg1d < 0: b_dec += 1
                else: b_unch += 1

            if len(df) >= 50:
                year_df = df.tail(252)
                h52 = year_df["high"].astype(float).max()
                l52 = year_df["low"].astype(float).min()
                if last >= h52 * 0.98: b_hi += 1
                if last <= l52 * 1.02: b_lo += 1

            # Sector metrics (only classified tickers)
            if ticker not in valid_tickers:
                continue
            recent = df.tail(90)
            if len(recent) < 5:
                continue
            c90 = recent["close"].astype(float)
            v90 = recent["volume"].astype(float)

            vol5  = float(v90.tail(5).mean())
            vol10 = float(v90.tail(10).mean())
            vol20 = float(v90.tail(20).mean())
            vol5_sum  = float(v90.tail(5).sum())
            vol10_sum = float(v90.tail(10).sum())
            vol20_sum = float(v90.tail(20).sum())

            h90 = recent["high"].astype(float)
            l90 = recent["low"].astype(float)
            # Guard against close == 0 / NaN to avoid Inf/NaN leaking into screener JSON
            c90_safe = c90.where(c90 > 0)
            amp = ((h90 - l90) / c90_safe * 100).replace([np.inf, -np.inf], np.nan)
            amp5 = float(amp.tail(5).mean(skipna=True))
            amp20 = float(amp.tail(20).mean(skipna=True))
            amp60 = float(amp.tail(60).mean(skipna=True)) if len(amp) >= 60 else amp5
            # NaN still possible if every bar in window had close<=0; coerce to 0 for JSON
            amp5 = 0.0 if not np.isfinite(amp5) else amp5
            amp20 = 0.0 if not np.isfinite(amp20) else amp20
            amp60 = 0.0 if not np.isfinite(amp60) else amp60

            def _pct_change(series, lookback):
                if len(series) <= lookback:
                    return None
                base = series.iloc[-lookback - 1]
                last_px = series.iloc[-1]
                if not (np.isfinite(base) and np.isfinite(last_px)) or base <= 0:
                    return None
                return float((last_px / base - 1) * 100)

            chg5 = _pct_change(c90, 5)
            chg20 = _pct_change(c90, 20)
            chg60 = _pct_change(c90, 60)

            if chg5 is not None and abs(chg5) > 50: chg5 = None
            if chg20 is not None and abs(chg20) > 80: chg20 = None
            if chg60 is not None and abs(chg60) > 150: chg60 = None

            issue_share = shares_map.get(ticker, 0)
            mktcap = last * 1000 * issue_share / 1e9 if issue_share > 0 else 0.0
            mktcap_proxy = last * 1000 * vol20 / 1e9
            freefloat_pct = freefloat_map.get(ticker, 30.0)
            freefloat_val = round(mktcap * freefloat_pct / 100, 1)
            freefloat_shares = issue_share * freefloat_pct / 100

            rows.append({
                "ticker": ticker, "last": round(last, 2),
                "vol5": vol5, "vol10": vol10, "vol20": vol20,
                "vol5_sum": vol5_sum, "vol10_sum": vol10_sum, "vol20_sum": vol20_sum,
                "mktcap": round(mktcap, 1), "mktcap_proxy": round(mktcap_proxy, 1),
                "freefloat_val": freefloat_val, "freefloat_shares": freefloat_shares,
                "amp5": round(amp5, 1), "amp20": round(amp20, 1), "amp60": round(amp60, 1),
                "chg5": round(chg5, 1) if chg5 is not None else None,
                "chg20": round(chg20, 1) if chg20 is not None else None,
                "chg60": round(chg60, 1) if chg60 is not None else None,
            })
        except Exception:
            continue

    # Breadth
    breadth = {}
    if b_total > 0:
        breadth = {
            "total": b_total,
            "above_ma200": b_ma200,
            "above_ma200_pct": round(b_ma200 / b_total * 100, 1),
            "rsi_oversold": b_rsi_ov,
            "rsi_oversold_pct": round(b_rsi_ov / b_total * 100, 1),
            "rsi_overbought": b_rsi_ob,
            "rsi_overbought_pct": round(b_rsi_ob / b_total * 100, 1),
            "advances": b_adv, "declines": b_dec, "unchanged": b_unch,
            "ad_ratio": round(b_adv / max(b_dec, 1), 2),
            "new_highs": b_hi, "new_lows": b_lo,
            "net_new_highs": b_hi - b_lo,
        }

    if not rows:
        return {"sectors": [], "breadth": breadth, "tickers": []}

    tick_df = pd.DataFrame(rows)
    merged = tick_df.merge(ind_df, on="ticker", how="left")
    merged["industry"] = merged["industry"].fillna("Khác")

    # NN ròng + Net BS là nguồn NGOÀI kho: bên gọi đưa vào, thiếu ⇒ cột None.
    nn_w, nn_m, nn_3m, nn_data_date = {}, {}, {}, None
    if fetch_nn is not None:
        try:
            nn_df = fetch_nn()
            nn_w, nn_m, nn_3m, nn_data_date = _nn_windows(nn_df)
            if nn_data_date:
                console.log(f"  NN data: {len(nn_df)} records, đến ngày {nn_data_date}")
        except Exception as e:
            console.log(f"  [yellow]⚠ NN data fetch error: {e}[/yellow]")

    nb_data: dict = {}
    if fetch_net_bs is not None:
        nb_data = fetch_net_bs(
            [r["ticker"] for r in sorted(rows, key=lambda r: -r.get("mktcap", 0))])

    # Aggregate by industry
    def agg(grp):
        n = len(grp)
        v20 = grp["vol20"].sum()
        v5 = grp["vol5"].sum()
        v10 = grp["vol10"].sum()
        total_mktcap = grp["mktcap"].sum()
        gtgd_tb = grp["mktcap_proxy"].sum()
        vs   = grp["vol5_sum"].sum()
        vs10 = grp["vol10_sum"].sum()
        vs20 = grp["vol20_sum"].sum()
        ff_sh = grp["freefloat_shares"].sum()
        vol5_20  = round(vs / vs20 * 100, 0) if vs20 > 0 else None
        avg5_10  = round((v5 / v10 - 1) * 100, 1) if v10 > 0 else None
        avg10_20 = round((v10 / v20 - 1) * 100, 1) if v20 > 0 else None
        vol5_free  = round(vs  / ff_sh * 100, 2) if ff_sh > 0 else None
        vol10_free = round(vs10 / ff_sh * 100, 2) if ff_sh > 0 else None
        vol20_free = round(vs20 / ff_sh * 100, 2) if ff_sh > 0 else None

        # Foreign flow (tỷ VND)
        tickers_in = grp["ticker"].tolist()
        net_w = sum(nn_w.get(t, 0) for t in tickers_in)
        net_m = sum(nn_m.get(t, 0) for t in tickers_in)
        net_3m_v = sum(nn_3m.get(t, 0) for t in tickers_in)

        # Aggressive order flow (triệu cổ phiếu)
        net_bs_1w = sum(nb_data.get(t, {}).get("1w", 0) for t in tickers_in)
        net_bs_1m = sum(nb_data.get(t, {}).get("1m", 0) for t in tickers_in)
        net_bs_3m = sum(nb_data.get(t, {}).get("3m", 0) for t in tickers_in)
        net_bs_6m = sum(nb_data.get(t, {}).get("6m", 0) for t in tickers_in)

        total_freefloat = grp["freefloat_val"].sum()
        return pd.Series({
            "Số mã": n,
            "Vốn hoá (tỷ)": round(total_mktcap, 0),
            "Freefloat (tỷ)": round(total_freefloat, 0),
            "GTGD TB (tỷ)": round(gtgd_tb, 0),
            "Vol Avg 5": round(v5 / 1e6, 1),
            "Vol Avg 10": round(v10 / 1e6, 1),
            "Vol Avg 20": round(v20 / 1e6, 1),
            "AVG 5-10 %": avg5_10,
            "AVG 10-20 %": avg10_20,
            "Vol 5/Free %": vol5_free,
            "Vol 10/Free %": vol10_free,
            "Vol 20/Free %": vol20_free,
            "Vol 5/20 %": vol5_20,
            "Biên 1T (%)": round(grp["amp5"].mean(), 1),
            "Biên 1M (%)": round(grp["amp20"].mean(), 1),
            "Biên 3M (%)": round(grp["amp60"].mean(), 1),
            "Giá 1T %": round(grp["chg5"].dropna().mean(), 1) if grp["chg5"].notna().any() else None,
            "Giá 1M %": round(grp["chg20"].dropna().mean(), 1) if grp["chg20"].notna().any() else None,
            "Giá 3M %": round(grp["chg60"].dropna().mean(), 1) if grp["chg60"].notna().any() else None,
            "NN 1T (tỷ)": round(net_w, 1) if net_w != 0 else None,
            "NN 1M (tỷ)": round(net_m, 1) if net_m != 0 else None,
            "NN 3M (tỷ)": round(net_3m_v, 1) if net_3m_v != 0 else None,
            "Net BS 1T": round(net_bs_1w, 1) if net_bs_1w != 0 else None,
            "Net BS 1M": round(net_bs_1m, 1) if net_bs_1m != 0 else None,
            "Net BS 3M": round(net_bs_3m, 1) if net_bs_3m != 0 else None,
            "Net BS 6M": round(net_bs_6m, 1) if net_bs_6m != 0 else None,
        })

    # Ticker display data
    import numpy as np
    tick_display = merged.copy()
    tick_display["Vốn hoá (tỷ)"] = tick_display["mktcap"].round(0)
    tick_display["Freefloat (tỷ)"] = tick_display["freefloat_val"].round(0)
    tick_display["GTGD TB (tỷ)"] = tick_display["mktcap_proxy"].round(1)
    tick_display["Vol Avg 5"] = (tick_display["vol5"] / 1e6).round(1)
    tick_display["Vol Avg 10"] = (tick_display["vol10"] / 1e6).round(1)
    tick_display["Vol Avg 20"] = (tick_display["vol20"] / 1e6).round(1)
    tick_display["AVG 5-10 %"] = np.where(
        tick_display["vol10"] > 0,
        ((tick_display["vol5"] / tick_display["vol10"] - 1) * 100).round(1), None)
    tick_display["AVG 10-20 %"] = np.where(
        tick_display["vol20"] > 0,
        ((tick_display["vol10"] / tick_display["vol20"] - 1) * 100).round(1), None)
    tick_display["Vol 5/Free %"] = np.where(
        tick_display["freefloat_shares"] > 0,
        (tick_display["vol5_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
    tick_display["Vol 10/Free %"] = np.where(
        tick_display["freefloat_shares"] > 0,
        (tick_display["vol10_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
    tick_display["Vol 20/Free %"] = np.where(
        tick_display["freefloat_shares"] > 0,
        (tick_display["vol20_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
    tick_display["Vol 5/20 %"] = np.where(
        tick_display["vol20_sum"] > 0,
        (tick_display["vol5_sum"] / tick_display["vol20_sum"] * 100).round(0), None)
    tick_display["Net BS 1T"] = tick_display["ticker"].map(lambda t: nb_data.get(t, {}).get("1w"))
    tick_display["Net BS 1M"] = tick_display["ticker"].map(lambda t: nb_data.get(t, {}).get("1m"))
    tick_display["Net BS 3M"] = tick_display["ticker"].map(lambda t: nb_data.get(t, {}).get("3m"))
    tick_display["Net BS 6M"] = tick_display["ticker"].map(lambda t: nb_data.get(t, {}).get("6m"))
    tick_display["NN 1T (tỷ)"] = tick_display["ticker"].map(nn_w)
    tick_display["NN 1M (tỷ)"] = tick_display["ticker"].map(nn_m)
    tick_display["NN 3M (tỷ)"] = tick_display["ticker"].map(nn_3m)
    # Kho mới (mọi mã < 61 bar) ⇒ chg60 toàn None = cột object, `.round` ném TypeError
    tick_display["Giá 1T %"] = pd.to_numeric(tick_display["chg5"], errors="coerce").round(1)
    tick_display["Giá 1M %"] = pd.to_numeric(tick_display["chg20"], errors="coerce").round(1)
    tick_display["Giá 3M %"] = pd.to_numeric(tick_display["chg60"], errors="coerce").round(1)
    tick_display = tick_display.rename(columns={"ticker": "Mã", "industry": "Ngành"})

    # Custom sector groups ("Họ VIN", "Họ M", …): group these ticker families as
    # their own SECTOR for the per-sector aggregation (feeds the brief's "Dòng
    # tiền ngành" block + lead/lag sector). The per-ticker "Ngành" (tick_display
    # above) is left as the raw industry, so the brief's realestate/financial
    # detection and movers stay unaffected.
    from vnstock_sectors import custom_sector_for
    merged["_sector_group"] = (
        merged["ticker"].map(custom_sector_for).fillna(merged["industry"]))

    result = merged.groupby("_sector_group").apply(agg).reset_index()
    result = result.rename(columns={"_sector_group": "Ngành"})
    result = result.sort_values("Vốn hoá (tỷ)", ascending=False).reset_index(drop=True)

    # Per-date GTGD map over the last ~20 sessions: {iso_date: {total, count}}.
    # total_gtgd_day/gtgd_ticker_count expose the latest COMPLETE session via
    # _pick_gtgd_session (an in-progress day with few names yet is skipped);
    # the brief instead looks up gtgd_by_date for ITS effective trading date.
    gtgd_by_date: dict = {}
    _missing: list = []
    _missing_est = 0.0
    if _gtgd_day_rows:
        _acc: dict = {}
        for d, val in _gtgd_day_rows:
            k = d.date()
            t, n = _acc.get(k, (0.0, 0))
            _acc[k] = (t + val, n + 1)
        _lastn = sorted(_acc.keys(), reverse=True)[:20]   # ~20 phiên cho TB5/TB20
        # #18: mã lớn thiếu bar phiên mới nhất + tổng từng ngày đã loại chúng
        _latest_d = _max_data_date.date() if _max_data_date is not None else None
        _missing = heavy_missing(_gtgd_by_ticker, _latest_d)
        _missing_est = round(float(sum(m["avg_gtgd"] for m in _missing)), 1)
        _excl = (excl_missing_totals({k: _acc[k][0] for k in _lastn},
                                     _gtgd_by_ticker, _missing) if _missing else {})
        gtgd_by_date = {
            k.isoformat(): {"total": round(_acc[k][0], 1), "count": _acc[k][1],
                            **({"excl_missing": round(_excl[k], 1)} if _missing else {})}
            for k in _lastn
        }
    _gd, total_gtgd_day, gtgd_ticker_count = _pick_gtgd_session(gtgd_by_date)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # Actual trading date of the stock bars used (NOT wall-clock) — lets the
        # brief detect when breadth/movers/regime trail an intraday VNINDEX.
        "data_date": _max_data_date.date().isoformat() if _max_data_date is not None else None,
        "total_gtgd_day": total_gtgd_day,
        "gtgd_ticker_count": gtgd_ticker_count,
        "gtgd_date": _gd,
        "gtgd_by_date": gtgd_by_date,
        # #18: mã lớn thiếu bar phiên data_date (+ tổng TB/phiên của chúng) —
        # brief nói rõ "ước tính thấp", doctor có badge; baseline dùng excl_missing.
        "gtgd_missing_heavy": _missing,
        "gtgd_missing_est": _missing_est,
        "gtgd_heavy_min": _HEAVY_GTGD_TY,
        "nn_data_date": nn_data_date,   # latest date the foreign-flow feed covers
        "sectors": result.to_dict(orient="records"),
        "breadth": breadth,
        "tickers": tick_display.to_dict(orient="records"),
    }


def compute_market_overview(warehouse: str = "data_warehouse") -> dict:
    """Bản của bước screener: `build_market_overview` + NN ròng (TopStock) + Net
    Buy-Sell (order_stats, cache `_meta/net_bs_cache.json`). Trả dict, chưa ghi
    market_overview.json — việc đó của `save_market_overview`."""

    def _fetch_nn() -> pd.DataFrame:
        """NN ròng ~20 phiên gần nhất: TopStock foreign_buy + foreign_sell."""
        try:
            from vnstock_data import TopStock
        except ImportError:
            console.log("  [dim]vnstock_data not installed — NN data skipped[/dim]")
            return pd.DataFrame()
        from datetime import date, timedelta as _td
        ts = TopStock()
        all_nn_rows = []
        today_d = date.today()
        days_fetched = 0
        calendar_day = 0
        while days_fetched < 20 and calendar_day < 40:
            dt = today_d - _td(days=calendar_day)
            calendar_day += 1
            if dt.weekday() >= 5:
                continue
            dt_str = dt.strftime("%Y-%m-%d")
            for fetch_fn in (ts.foreign_buy, ts.foreign_sell):
                try:
                    nn_df_day = fetch_fn(date=dt_str, limit=100)
                    if nn_df_day is not None and not nn_df_day.empty:
                        for _, r in nn_df_day.iterrows():
                            all_nn_rows.append({
                                "symbol": str(r.get("symbol", "")),
                                "date": dt,
                                "net_value": float(r.get("net_value", 0)),
                            })
                except Exception:
                    continue
            days_fetched += 1
        return pd.DataFrame(all_nn_rows)

    def _fetch_net_bs(_top_tickers: list) -> dict:
        """Net Buy-Sell theo mã qua order_stats(): song song có nhịp, cache 12h."""
        nb_data: dict = {}
        _NB_CACHE_PATH = Path(warehouse) / "_meta" / "net_bs_cache.json"
        _NB_CACHE_TTL_H = 12  # reuse cache if younger than 12 hours
        try:
            from vnstock_data import Trading
            import time as _nb_time

            # Check cache first
            _nb_cache_hit = False
            if _NB_CACHE_PATH.exists():
                try:
                    _nb_cached = json.loads(_NB_CACHE_PATH.read_text(encoding="utf-8"))
                    _nb_age_h = (_nb_time.time() - _NB_CACHE_PATH.stat().st_mtime) / 3600
                    if _nb_age_h < _NB_CACHE_TTL_H:
                        nb_data = _nb_cached.get("data", {})
                        console.log(
                            f"  Net BS: loaded from cache ({_nb_age_h:.1f}h old, "
                            f"{len(nb_data)} tickers)"
                        )
                        _nb_cache_hit = True
                except Exception:
                    pass

            if not _nb_cache_hit:
                _t0_nb = _nb_time.time()

                # ── Gọi SONG SONG có nhịp, thay vì tuần tự có sleep ───────────
                # Bản cũ: `for tk in ...: order_stats(tk); sleep(0.15)`. Với
                # ~1.000 mã đó là **sàn 150 giây chỉ để NGỦ**, cộng round-trip
                # mạng cũng nối tiếp nhau ⇒ vài trăm giây nữa. Trong khi hạn mức
                # Sponsor là 600 req/phút = 10 req/s: đường tuần tự dùng chưa tới
                # 1/10 quota mà vẫn chậm.
                #
                # Nay: pool worker + MỘT bộ nhịp dùng chung. Tổng tốc độ bị chặn ở
                # `_NB_RATE_PER_SEC` bất kể bao nhiêu worker (bộ nhịp giữ mốc
                # "lượt kế tiếp" dưới khoá, còn `sleep` thì nằm NGOÀI khoá nên
                # worker không chặn nhau). Sàn thời gian nay là HẠN MỨC, không
                # phải độ trễ nối tiếp.
                #
                # ⚠️ CỐ Ý KHÔNG đụng TTL 12h của cache: phát chạy mỗi ~24h nên
                # cache LUÔN nguội ở đường đêm — nhưng đó là ĐÚNG. `Net BS 1T` là
                # tổng 5 phiên; xài lại cache hôm qua là thiếu mất phiên hôm nay,
                # một lỗi số liệu IM LẶNG. Cache chỉ để cứu lượt chạy lại trong
                # cùng buổi tối, và nó làm đúng việc đó.
                _nb_workers = _nb_pool_size()
                _nb_pacer = _RatePacer(_NB_RATE_PER_SEC)
                _nb_fail = 0

                def _nb_fetch_one(tk: str) -> "tuple[str, dict | None, bool]":
                    """(mã, số liệu | None, có LỖI không). Chạy trong worker."""
                    from vnstock_ratelimit import call_with_rate_limit_retry
                    _nb_pacer.wait()
                    try:
                        os_df = call_with_rate_limit_retry(
                            lambda: Trading(symbol=tk).order_stats(), retries=2)
                    except Exception:
                        # Nuốt im lặng như bản cũ là MẤT DATA không dấu vết: mã bị
                        # hạn mức chặn biến mất khỏi nb_data mà không ai biết.
                        return tk, None, True
                    if os_df is None or os_df.empty:
                        return tk, None, False        # thật sự không có data
                    try:
                        os_df = os_df.sort_values("trading_date")
                        bv = pd.to_numeric(os_df["total_buy_trade_volume"],
                                           errors="coerce").fillna(0)
                        sv = pd.to_numeric(os_df["total_sell_trade_volume"],
                                           errors="coerce").fillna(0)
                        net = bv - sv
                        return tk, {
                            "1w": round(float(net.tail(5).sum())   / 1e6, 1),
                            "1m": round(float(net.tail(20).sum())  / 1e6, 1),
                            "3m": round(float(net.tail(60).sum())  / 1e6, 1),
                            "6m": round(float(net.tail(120).sum()) / 1e6, 1),
                        }, False
                    except Exception:
                        return tk, None, True

                from concurrent.futures import ThreadPoolExecutor, as_completed
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(), MofNCompleteColumn(),
                    TaskProgressColumn(), TimeElapsedColumn(),
                    console=console,
                ) as _nb_progress:
                    _nb_task = _nb_progress.add_task(
                        f"Net BS ({_nb_workers} luồng)...", total=len(_top_tickers))
                    with ThreadPoolExecutor(max_workers=_nb_workers) as _nb_pool:
                        _futs = [_nb_pool.submit(_nb_fetch_one, tk) for tk in _top_tickers]
                        for _fut in as_completed(_futs):
                            try:
                                tk, val, failed = _fut.result()
                            except Exception:
                                _nb_fail += 1
                                _nb_progress.update(_nb_task, advance=1)
                                continue
                            if val is not None:
                                nb_data[tk] = val
                            if failed:
                                _nb_fail += 1
                            _nb_progress.update(_nb_task, description=f"[cyan]{tk:6s}[/cyan]",
                                                advance=1)

                # Save cache
                try:
                    # Cache thuần (TTL 12h) nên mất không sao — nhưng file này ở
                    # trong file đã vào lưới `_MUST_BE_ATOMIC`, và lưới soi theo
                    # FILE chứ không theo điểm ghi. Nguyên tử luôn cho khỏi phải
                    # cấy ngoại lệ vào lưới (ngoại lệ là chỗ lỗi thật hay trốn).
                    from vnstock_parquet_io import write_json_atomic
                    write_json_atomic(
                        {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "data": nb_data},
                        _NB_CACHE_PATH)
                except Exception:
                    pass
                _nb_secs = _nb_time.time() - _t0_nb
                _nb_rate = len(_top_tickers) / _nb_secs if _nb_secs > 0 else 0
                console.log(
                    f"  Net Buy-Sell: {len(nb_data)}/{len(_top_tickers)} tickers "
                    f"({_nb_secs:.0f}s · {_nb_rate:.1f} req/s · {_nb_workers} luồng"
                    + (f" · {_nb_fail} LỖI" if _nb_fail else "") + ") → cached"
                )
        except ImportError:
            console.log("  [dim]vnstock_data not installed — Net BS data skipped[/dim]")
        except Exception as e:
            console.log(f"  [yellow]⚠ Net BS fetch error: {e}[/yellow]")
        return nb_data

    return build_market_overview(warehouse, fetch_nn=_fetch_nn, fetch_net_bs=_fetch_net_bs)


def _pick_gtgd_session(gtgd_by_date: dict, now=None) -> tuple:
    """Pick the latest COMPLETE session from {iso_date: {total, count}}.

    Count can't tell a mid-day partial apart — by noon ~80% of names have
    already printed a trade (observed 706/869) while turnover sits at ~37%.
    So: (a) if the latest date IS today and the session hasn't closed yet
    (< 15:05), it's in-progress by definition → step back one day; (b) else
    compare its TOTAL with the median of the other days — below 55% of the
    median means a partial fetched mid-session (a genuinely quiet day doesn't
    halve the 5-day median). Returns (iso_date, total, count) / (None, 0.0, 0).
    """
    if not gtgd_by_date:
        return None, 0.0, 0
    dates = sorted(gtgd_by_date.keys(), reverse=True)
    latest = dates[0]
    drop_latest = False
    now = now or datetime.now()
    if latest == now.date().isoformat() and now.time() < dt_time(15, 5):
        drop_latest = True                      # session still open → partial
    elif len(dates) > 1:
        import statistics as _st
        med = _st.median(gtgd_by_date[d]["total"] for d in dates[1:])
        if med > 0 and gtgd_by_date[latest]["total"] < 0.55 * med:
            drop_latest = True                  # stale mid-session fetch
    pick = dates[1] if (drop_latest and len(dates) > 1) else latest
    e = gtgd_by_date[pick]
    return pick, e["total"], e["count"]


def _json_safe(obj):
    """Convert numpy/pandas types to Python native for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if np.isnan(obj):
            return None
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _clean_nan(obj):
    """Recursively replace NaN floats with None for clean JSON output."""
    import math
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


def save_market_overview(data: dict, warehouse: str = "data_warehouse"):
    """Save market overview to JSON."""
    meta_dir = Path(warehouse) / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    out_path = meta_dir / MARKET_OVERVIEW_FILE
    cleaned = _clean_nan(data)
    # Nguyên tử: brief dựng độ rộng / VN30 movers / dòng tiền ngành / regime từ
    # file này. Bản cụt = brief im lặng mất mấy khối đó.
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(cleaned, out_path)
    console.print(f"[green]✅ Market overview → {out_path}[/green]")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Screener Runner")
    parser.add_argument("--warehouse", default="data_warehouse")
    parser.add_argument("--presets",   nargs="+", help="Chỉ chạy preset cụ thể")
    parser.add_argument("--skip-market", action="store_true",
                        help="Bỏ qua bước tính market overview")
    args = parser.parse_args()

    console.rule("[bold cyan]🚀 VnStock Screener Runner[/bold cyan]")

    # Step 1: Screener presets
    console.log("[bold]Step 1/2: Screener presets[/bold]")
    output = run_all_presets(warehouse=args.warehouse, presets=args.presets)
    path   = save_results(output, warehouse=args.warehouse)

    total_hits = sum(v["count"] for v in output["presets"].values())
    console.print(
        f"\n  [dim]Presets: {len(output['presets'])} | "
        f"Total hits: {total_hits} | "
        f"Generated: {output['generated_at']}[/dim]\n"
    )

    # Step 2: Market overview (sector metrics + breadth)
    if not args.skip_market:
        console.log("[bold]Step 2/2: Market overview[/bold]")
        mkt_data = compute_market_overview(warehouse=args.warehouse)
        if mkt_data and mkt_data.get("sectors"):
            save_market_overview(mkt_data, warehouse=args.warehouse)
            console.print(
                f"  [dim]Sectors: {len(mkt_data['sectors'])} | "
                f"Breadth: {mkt_data['breadth'].get('total', 0)} mã | "
                f"Tickers: {len(mkt_data['tickers'])}[/dim]"
            )
        else:
            console.print("  [yellow]⚠ Market overview: không có dữ liệu[/yellow]")
    else:
        console.print("[dim]  ⏭ Bỏ qua market overview (--skip-market)[/dim]")

    # Step 3: Session stats (intraday) — auto-save today's data
    console.log("[bold]Step 3/3: Session stats[/bold]")
    try:
        from vnstock_session_stats import compute_session_stats, save_session_stats, backfill_session_stats
        _filled = backfill_session_stats()
        if _filled:
            console.print(f"  [dim]Session stats: backfilled {_filled} missing date(s)[/dim]")
        _ss = compute_session_stats()
        if _ss:
            save_session_stats(_ss)
            console.print(f"  [dim]Session stats: {len(_ss)} windows → saved[/dim]")
        else:
            console.print("  [yellow]⚠ Session stats: không có dữ liệu intraday[/yellow]")
    except Exception as _ss_err:
        console.print(f"  [yellow]⚠ Session stats skipped: {_ss_err}[/yellow]")
