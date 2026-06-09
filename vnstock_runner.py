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
from datetime import datetime
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# Import từ screener (cùng thư mục)
import sys
sys.path.insert(0, str(Path(__file__).parent))
from vnstock_screener import MarketScreener, PRESETS

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

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

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


def compute_market_overview(warehouse: str = "data_warehouse") -> dict:
    """
    Compute sector metrics + breadth indicators from warehouse parquet.
    Returns dict ready to JSON-serialize → market_overview.json.
    Dashboard reads this file for instant load.
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
                for pf in yd.glob("*.parquet"):
                    frames.append(pq.read_table(str(pf),
                        columns=["time", "close", "volume", "high", "low"]).to_pandas())
            if not frames:
                continue
            df = pd.concat(frames).sort_values("time")
            df["time"] = pd.to_datetime(df["time"])
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

    # Fetch foreign net flow (TopStock API) for NN ròng columns
    nn_w, nn_m, nn_3m = {}, {}, {}
    try:
        from vnstock_data import TopStock
        from datetime import timedelta as _td
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

        if all_nn_rows:
            nn_df_all = pd.DataFrame(all_nn_rows)
            today_ts = pd.Timestamp(today_d)
            for days, result_map in ((7, nn_w), (30, nn_m), (90, nn_3m)):
                cutoff = today_ts - pd.Timedelta(days=days)
                filtered = nn_df_all[pd.to_datetime(nn_df_all["date"]) >= cutoff]
                agg_val = filtered.groupby("symbol")["net_value"].sum()
                for sym, val in agg_val.items():
                    result_map[sym] = round(val / 1e9, 1)  # → tỷ VND
            console.log(f"  NN data: {len(all_nn_rows)} records across 20 days")
    except ImportError:
        console.log("  [dim]vnstock_data not installed — NN data skipped[/dim]")
    except Exception as e:
        console.log(f"  [yellow]⚠ NN data fetch error: {e}[/yellow]")

    # Fetch aggressive order flow (Net Buy-Sell) per ticker via order_stats()
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
            _top_tickers = [r["ticker"] for r in sorted(rows, key=lambda r: -r.get("mktcap", 0))]

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(), MofNCompleteColumn(),
                TaskProgressColumn(), TimeElapsedColumn(),
                console=console,
            ) as _nb_progress:
                _nb_task = _nb_progress.add_task("Net BS...", total=len(_top_tickers))
                for tk in _top_tickers:
                    _nb_progress.update(_nb_task, description=f"[cyan]{tk:6s}[/cyan]", advance=1)
                    try:
                        os_df = Trading(symbol=tk).order_stats()
                        if os_df is not None and not os_df.empty:
                            os_df = os_df.sort_values("trading_date")
                            bv = pd.to_numeric(os_df["total_buy_trade_volume"], errors="coerce").fillna(0)
                            sv = pd.to_numeric(os_df["total_sell_trade_volume"], errors="coerce").fillna(0)
                            net = bv - sv
                            nb_data[tk] = {
                                "1w": round(float(net.tail(5).sum())   / 1e6, 1),
                                "1m": round(float(net.tail(20).sum())  / 1e6, 1),
                                "3m": round(float(net.tail(60).sum())  / 1e6, 1),
                                "6m": round(float(net.tail(120).sum()) / 1e6, 1),
                            }
                    except Exception:
                        pass
                    _nb_time.sleep(0.15)

            # Save cache
            try:
                _NB_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                _NB_CACHE_PATH.write_text(
                    json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "data": nb_data},
                               ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception:
                pass
            console.log(
                f"  Net Buy-Sell: {len(nb_data)}/{len(_top_tickers)} tickers "
                f"({_nb_time.time() - _t0_nb:.0f}s) → cached"
            )
    except ImportError:
        console.log("  [dim]vnstock_data not installed — Net BS data skipped[/dim]")
    except Exception as e:
        console.log(f"  [yellow]⚠ Net BS fetch error: {e}[/yellow]")

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
    tick_display["Giá 1T %"] = tick_display["chg5"].round(1)
    tick_display["Giá 1M %"] = tick_display["chg20"].round(1)
    tick_display["Giá 3M %"] = tick_display["chg60"].round(1)
    tick_display = tick_display.rename(columns={"ticker": "Mã", "industry": "Ngành"})

    result = merged.groupby("industry").apply(agg).reset_index()
    result = result.rename(columns={"industry": "Ngành"})
    result = result.sort_values("Vốn hoá (tỷ)", ascending=False).reset_index(drop=True)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # Actual trading date of the stock bars used (NOT wall-clock) — lets the
        # brief detect when breadth/movers/regime trail an intraday VNINDEX.
        "data_date": _max_data_date.date().isoformat() if _max_data_date is not None else None,
        "sectors": result.to_dict(orient="records"),
        "breadth": breadth,
        "tickers": tick_display.to_dict(orient="records"),
    }


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
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2, default=_json_safe)
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
