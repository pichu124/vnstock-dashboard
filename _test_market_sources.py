"""Test v5 — VERIFY put_through aggregation matches real exchange GTGD.

v4 found:
  • Trading.price_history(source='VCI') has total_value column (EOD daily)
  • Trading.put_through(source='VCI') returns 1221 trades w/ accumulated_value
    + timestamps (14:59:39 ICT - real-time during session)
  • Listing(source='vnd').all_symbols() returns 1982 rows w/ exchange column

This test does the REAL aggregation:
  1. Get all stocks → exchange map (HOSE/HNX/UPCOM)
  2. Get put_through() → group by symbol → max(accumulated_value) per symbol
  3. Sum by exchange → check if matches realistic VN market figures
     (HOSE ~15-25k tỷ, HNX ~1-3k tỷ, UPCOM ~0.3-1k tỷ for a typical day)

If the numbers match, this is our realtime data source.
"""
from __future__ import annotations

import time
import traceback
from datetime import date


def _section(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


def main():
    print(f"v5 verify · {time.strftime('%H:%M:%S')}")
    try:
        import vnstock_data as vd
        import pandas as pd
    except ImportError as e:
        print(f"Missing: {e}")
        return

    # ─── 1. Build exchange map ────────────────────────────────────────────
    _section("1. Exchange map from Listing(source='vnd').all_symbols()")
    try:
        ls = vd.Listing(source="vnd")
        sym_df = ls.all_symbols()
        # Filter listed stocks only
        listed = sym_df[
            (sym_df["status"] == "listed") &
            (sym_df["type"] == "STOCK")
        ].copy() if "type" in sym_df.columns else sym_df[sym_df["status"] == "listed"]
        print(f"  Listed rows: {len(listed)}")
        print(f"  Type values:", sym_df["type"].value_counts().to_dict() if "type" in sym_df.columns else "N/A")
        # Try to identify stock type — exclude IFC (fund), CW, BOND
        if "type" in sym_df.columns:
            stocks = sym_df[
                (sym_df["status"] == "listed") &
                (sym_df["type"].isin(["STOCK", "stock", "ST"]))
            ]
        else:
            stocks = listed
        print(f"  Stocks only: {len(stocks)}")

        # Exchange distribution
        if "exchange" in stocks.columns:
            print(f"  Exchange dist:", stocks["exchange"].value_counts().to_dict())

        # Build symbol → exchange dict
        sym_to_ex = dict(zip(stocks["symbol"].astype(str).str.upper(),
                              stocks["exchange"].astype(str).str.upper()))
        print(f"  Map size: {len(sym_to_ex)}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    # ─── 2. Get put_through and aggregate ──────────────────────────────────
    _section("2. Trading.put_through() — aggregate by exchange")
    try:
        t = vd.Trading(symbol="VNINDEX", source="VCI")
        t0 = time.time()
        pt = t.put_through()
        dt = (time.time() - t0) * 1000
        print(f"  Latency: {dt:.0f} ms")
        print(f"  Shape: {pt.shape}")
        print(f"  Columns: {list(pt.columns)}")
        print(f"  Time range: {pt['time'].min()} → {pt['time'].max()}")

        # Group by symbol, take latest accumulated_value (highest = latest cumulative)
        latest = pt.sort_values("time").groupby("symbol").last().reset_index()
        print(f"\n  Unique symbols in put_through: {len(latest)}")
        # Top 10 by accumulated_value
        latest_top = latest.nlargest(10, "accumulated_value")[
            ["symbol", "accumulated_volume", "accumulated_value", "time"]
        ]
        print("\n  Top 10 by accumulated_value:")
        for _, r in latest_top.iterrows():
            sym = str(r["symbol"]).upper()
            ex = sym_to_ex.get(sym, "?")
            print(f"    {sym:<6} ({ex:>6}) "
                  f"vol={r['accumulated_volume']:>12,.0f} "
                  f"val={r['accumulated_value']/1e9:>8.1f} tỷ "
                  f"@ {r['time']}")

        # Aggregate by exchange
        latest["symbol_upper"] = latest["symbol"].astype(str).str.upper()
        latest["exchange"] = latest["symbol_upper"].map(sym_to_ex).fillna("UNKNOWN")
        agg = latest.groupby("exchange").agg(
            total_value_VND=("accumulated_value", "sum"),
            total_volume=("accumulated_volume", "sum"),
            stock_count=("symbol", "count"),
        ).reset_index()
        agg["total_value_billion_VND"] = agg["total_value_VND"] / 1e9
        agg["total_volume_million"] = agg["total_volume"] / 1e6

        print("\n  Aggregated by exchange:")
        print(f"  {'Exchange':<10}{'Stocks':<10}{'Volume (M)':<15}{'GTGD (tỷ VND)':<20}")
        for _, r in agg.iterrows():
            print(f"  {r['exchange']:<10}{r['stock_count']:<10}"
                  f"{r['total_volume_million']:<15,.1f}"
                  f"{r['total_value_billion_VND']:<20,.1f}")

        # Expected ranges (from typical VN market data)
        print("\n  Expected typical ranges:")
        print(f"  {'HOSE (VNINDEX)':<20} GTGD: 15,000 - 25,000 tỷ VND")
        print(f"  {'HNX':<20} GTGD: 1,000 - 3,000 tỷ VND")
        print(f"  {'UPCOM':<20} GTGD: 300 - 1,000 tỷ VND")

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    # ─── 3. Cross-check with price_history ─────────────────────────────────
    _section("3. Cross-check: Trading.price_history for each index")
    for idx in ("VNINDEX", "VN30", "HNXINDEX", "UPCOM"):
        try:
            ti = vd.Trading(symbol=idx, source="VCI")
            t0 = time.time()
            ph = ti.price_history()
            dt = (time.time() - t0) * 1000
            # Get most recent rows
            ph = ph.sort_values("trading_date", ascending=False).head(5)
            print(f"\n  {idx} (latency {dt:.0f}ms):")
            for _, r in ph.iterrows():
                td = r.get("trading_date", "?")
                tv = r.get("total_value", 0)
                tvol = r.get("total_volume", 0)
                print(f"    {td}  GTGD={tv/1e9:>10,.1f} tỷ  VOL={tvol/1e6:>8,.1f}M")
        except Exception as e:
            print(f"  {idx} ERROR: {type(e).__name__}: {e}")

    _section("DONE")
    print("""
Phân tích output:
  • Section 2 sum HOSE: nếu khớp range 15-25k tỷ → put_through aggregation OK
  • Section 3 trading_date latest: nếu là yesterday/today → realtime
    Nếu là > 1 day ago → EOD batch only
    Compare số HOSE ở section 2 với số VNINDEX ở section 3 cùng ngày →
    confirm aggregation matches index total

Copy output gửi cho Claude.
""")


if __name__ == "__main__":
    main()
