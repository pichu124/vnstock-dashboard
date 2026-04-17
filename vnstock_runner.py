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

    from datetime import date, timedelta
    cutoff = pd.Timestamp(date.today() - timedelta(days=400))

    rows = []
    b_total = b_ma200 = b_rsi_ov = b_rsi_ob = 0
    b_adv = b_dec = b_unch = b_hi = b_lo = 0

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

            vol5 = float(v90.tail(5).mean())
            vol10 = float(v90.tail(10).mean())
            vol20 = float(v90.tail(20).mean())

            h90 = recent["high"].astype(float)
            l90 = recent["low"].astype(float)
            amp = (h90 - l90) / c90 * 100
            amp5 = float(amp.tail(5).mean())
            amp20 = float(amp.tail(20).mean())
            amp60 = float(amp.tail(60).mean()) if len(amp) >= 60 else amp5

            chg5 = float((c90.iloc[-1] / c90.iloc[-6] - 1) * 100) if len(c90) > 5 else None
            chg20 = float((c90.iloc[-1] / c90.iloc[-21] - 1) * 100) if len(c90) > 20 else None
            chg60 = float((c90.iloc[-1] / c90.iloc[-61] - 1) * 100) if len(c90) > 60 else None

            if chg5 is not None and abs(chg5) > 50: chg5 = None
            if chg20 is not None and abs(chg20) > 80: chg20 = None
            if chg60 is not None and abs(chg60) > 150: chg60 = None

            issue_share = shares_map.get(ticker, 0)
            mktcap = last * 1000 * issue_share / 1e9 if issue_share > 0 else 0.0
            mktcap_proxy = last * 1000 * vol20 / 1e9

            rows.append({
                "ticker": ticker, "last": round(last, 2),
                "vol5": vol5, "vol10": vol10, "vol20": vol20,
                "mktcap": round(mktcap, 1), "mktcap_proxy": round(mktcap_proxy, 1),
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

    # Aggregate by industry
    def agg(grp):
        n = len(grp)
        v20 = grp["vol20"].sum()
        v5 = grp["vol5"].sum()
        v10 = grp["vol10"].sum()
        total_mktcap = grp["mktcap"].sum()
        gtgd_tb = grp["mktcap_proxy"].sum()
        vol5_20 = round(v5 / v20 * 100, 0) if v20 > 0 else None

        # Foreign flow (tỷ VND)
        tickers_in = grp["ticker"].tolist()
        net_w = sum(nn_w.get(t, 0) for t in tickers_in)
        net_m = sum(nn_m.get(t, 0) for t in tickers_in)
        net_3m_v = sum(nn_3m.get(t, 0) for t in tickers_in)

        return pd.Series({
            "Số mã": n,
            "Vốn hoá (tỷ)": round(total_mktcap, 0),
            "GTGD TB (tỷ)": round(gtgd_tb, 0),
            "Vol Avg 5": round(v5 / 1e6, 1),
            "Vol Avg 10": round(v10 / 1e6, 1),
            "Vol Avg 20": round(v20 / 1e6, 1),
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
        })

    # Ticker display data
    import numpy as np
    tick_display = merged.copy()
    tick_display["Vốn hoá (tỷ)"] = tick_display["mktcap"].round(0)
    tick_display["GTGD TB (tỷ)"] = tick_display["mktcap_proxy"].round(1)
    tick_display["Vol Avg 5"] = (tick_display["vol5"] / 1e6).round(1)
    tick_display["Vol Avg 10"] = (tick_display["vol10"] / 1e6).round(1)
    tick_display["Vol Avg 20"] = (tick_display["vol20"] / 1e6).round(1)
    tick_display["Vol 5/20 %"] = np.where(
        tick_display["vol20"] > 0,
        (tick_display["vol5"] / tick_display["vol20"] * 100).round(0), None)
    tick_display = tick_display.rename(columns={"ticker": "Mã", "industry": "Ngành"})

    result = merged.groupby("industry").apply(agg).reset_index()
    result = result.rename(columns={"industry": "Ngành"})
    result = result.sort_values("Vốn hoá (tỷ)", ascending=False).reset_index(drop=True)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
