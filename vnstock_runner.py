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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Screener Runner")
    parser.add_argument("--warehouse", default="data_warehouse")
    parser.add_argument("--presets",   nargs="+", help="Chỉ chạy preset cụ thể")
    args = parser.parse_args()

    console.rule("[bold cyan]🚀 VnStock Screener Runner[/bold cyan]")
    output = run_all_presets(warehouse=args.warehouse, presets=args.presets)
    path   = save_results(output, warehouse=args.warehouse)

    # Summary
    total_hits = sum(v["count"] for v in output["presets"].values())
    console.print(
        f"\n  [dim]Presets: {len(output['presets'])} | "
        f"Total hits: {total_hits} | "
        f"Generated: {output['generated_at']}[/dim]"
    )
