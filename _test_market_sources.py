"""Test v4 — focus on VCI/VND source (KBS default fails on most methods).

v3 revealed:
  • Trading/Quote default to source='KBS' — NotImplementedError on most methods
  • Quote.history() with VCI for VNINDEX works but only OHLCV (no value col)
  • Trading.foreign_trade() works (22 cols) but only foreign trading
  • IndexGroup is just a string enum
  • Listing.all_indices() works (21 indices listed)
  • TopStock.value() signature looks promising

v4 tries:
  A. Trading methods with source='VCI' AND source='VND'
  B. TopStock.value() and .deal() — top stocks by GTGD
  C. Listing(source='VCI').symbols_by_exchange — get HOSE/HNX/UPCOM lists
  D. Trading.price_board for STOCK list with proper column handling
  E. Trading.history with VCI for VNINDEX
"""
from __future__ import annotations

import inspect
import time
import traceback
from datetime import date, timedelta


def _section(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


def _kv(k, v):
    print(f"  {k:.<32} {v}")


def _safe(label, fn, *args, **kwargs):
    print(f"\n  → {label}")
    if kwargs:
        print(f"    kwargs: {kwargs}")
    t0 = time.time()
    try:
        r = fn(*args, **kwargs)
        dt = (time.time() - t0) * 1000
        _kv("Latency", f"{dt:.0f} ms")
        if r is None:
            _kv("Result", "None")
            return None
        if hasattr(r, "shape"):
            _kv("Shape", r.shape)
            cols = [str(c) for c in r.columns]
            _kv("Columns", cols[:30])
            value_cols = [c for c in cols if any(
                kw in c.lower() for kw in
                ("value", "gtgd", "accumulated", "match_value", "totalvalmt",
                 "totalvalue", "total_value"))]
            if value_cols:
                print(f"    *** VALUE-LIKE: {value_cols} ***")
            try:
                head = r.head(3)
                print("    First rows:")
                for line in str(head).split("\n")[:8]:
                    print(f"      {line}")
            except Exception:
                pass
            return r
        else:
            _kv("Result", str(r)[:300])
            return r
    except Exception as e:
        dt = (time.time() - t0) * 1000
        _kv("Latency", f"{dt:.0f} ms")
        _kv("ERROR", f"{type(e).__name__}: {str(e)[:200]}")
        return None


def main():
    print(f"v4 test · {time.strftime('%H:%M:%S')}")
    try:
        import vnstock_data as vd
    except ImportError:
        print("vnstock_data not installed")
        return

    today = date.today().isoformat()
    start = (date.today() - timedelta(days=2)).isoformat()

    # ─── A. Trading methods with VCI source ───────────────────────────────
    _section("A — Trading(source='VCI') methods")
    for source in ("VCI", "VND"):
        print(f"\n  ━━━━━━ source='{source}' ━━━━━━")
        try:
            t = vd.Trading(symbol="VNINDEX", source=source)
        except Exception as e:
            print(f"  Init failed: {e}")
            continue

        for method_name in ("trading_stats", "order_stats", "side_stats",
                           "matched_by_price", "history", "price_board",
                           "price_history", "put_through", "prop_trade"):
            m = getattr(t, method_name, None)
            if m is None:
                continue
            # Try empty call first
            _safe(f"{source}.{method_name}()", m)
            # Try with symbols param if first failed
            _safe(f"{source}.{method_name}(symbols=['VNINDEX'])", m,
                  symbols=["VNINDEX"])

    # ─── B. TopStock — top stocks by VALUE ────────────────────────────────
    _section("B — TopStock.value (top stocks by GTGD)")
    try:
        # TopStock default source = 'vnd'
        ts = vd.TopStock(source="vnd")
        for method in ("value", "volume", "deal", "gainer"):
            m = getattr(ts, method, None)
            if m:
                # value(index='VNINDEX', limit=10)
                _safe(f"TopStock.{method}(index='VNINDEX', limit=20)",
                      m, index="VNINDEX", limit=20)
                _safe(f"TopStock.{method}(index='VN30', limit=20)",
                      m, index="VN30", limit=20)
                _safe(f"TopStock.{method}(index='HNXINDEX', limit=20)",
                      m, index="HNXINDEX", limit=20)
                _safe(f"TopStock.{method}(index='UPCOM', limit=20)",
                      m, index="UPCOM", limit=20)
    except Exception as e:
        print(f"  Error: {e}")
        traceback.print_exc()

    # ─── C. Listing with source ───────────────────────────────────────────
    _section("C — Listing(source='vci') symbols by exchange")
    for source in ("vci", "vnd"):
        try:
            ls = vd.Listing(source=source)
            print(f"\n  ━━ {source} ━━")
            _safe(f"Listing({source}).all_symbols()", ls.all_symbols)
            _safe(f"Listing({source}).symbols_by_exchange()",
                  ls.symbols_by_exchange)
            _safe(f"Listing({source}).symbols_by_group(group='VN30')",
                  ls.symbols_by_group, group="VN30")
        except Exception as e:
            print(f"  Listing({source}) failed: {e}")

    # ─── D. price_board for stocks (proper column handling) ───────────────
    _section("D — price_board for VN30 stocks (vnstock free)")
    try:
        from vnstock import Vnstock
        VN30 = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
                "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
                "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]
        st = Vnstock().stock(symbol="VCB", source="VCI")
        t0 = time.time()
        df = st.trading.price_board(VN30)
        dt = (time.time() - t0) * 1000
        _kv("Latency 30 stocks", f"{dt:.0f} ms")
        _kv("Shape", df.shape)
        # Flatten MultiIndex columns
        if hasattr(df.columns, "levels"):
            df.columns = ["_".join(str(c) for c in col).strip("_")
                          for col in df.columns]
        cols = list(df.columns)
        _kv("Flat columns", cols)
        # Find price + accumulated_volume cols
        price_col = next((c for c in cols if "match_price" in c), None)
        vol_col = next((c for c in cols if "accumulated_volume" in c), None)
        sym_col = next((c for c in cols if c.endswith("symbol")), None)
        _kv("price_col", price_col)
        _kv("vol_col", vol_col)
        _kv("sym_col", sym_col)
        if price_col and vol_col:
            df["est_gtgd"] = df[price_col].astype(float) * df[vol_col].astype(float)
            total = df["est_gtgd"].sum() / 1e9
            _kv("Sum est GTGD VN30", f"{total:,.1f} tỷ VND")
            print("\n    Top 5:")
            for _, r in df.sort_values("est_gtgd", ascending=False).head(5).iterrows():
                _print_sym = r[sym_col] if sym_col else "?"
                print(f"      {_print_sym:<6} price={r[price_col]:<10} "
                      f"accVol={r[vol_col]:<14,.0f} GTGD={r['est_gtgd']/1e9:>6.1f} tỷ")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ─── E. Trading.history with explicit start/end/interval ──────────────
    _section("E — Trading.history(VNINDEX, VCI) with various params")
    try:
        t_vci = vd.Trading(symbol="VNINDEX", source="VCI")
        for kw in [
            {"start": start, "end": today, "interval": "1m"},
            {"start": start, "end": today, "interval": "5m"},
            {"symbol": "VNINDEX", "start": start, "end": today},
            {"symbol": "VN30", "start": start, "end": today, "interval": "1m"},
        ]:
            _safe(f"Trading.history(**{kw})", t_vci.history, **kw)
    except Exception as e:
        print(f"  Error: {e}")

    _section("DONE")


if __name__ == "__main__":
    main()
