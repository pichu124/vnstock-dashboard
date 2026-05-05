"""Test v3 — focus on vnstock_data sponsor package.

v2 revealed vnstock_data 3.0.0 has these promising methods:
  Trading: trading_stats, order_stats, side_stats, history, foreign_trade,
           price_board, price_history, ...
  IndexGroup (dedicated class for index groups!)
  Listing: symbols_by_exchange, symbols_by_group, all_indices, ...

But init pattern is different from vnstock free. v3 introspects signatures
so we know exactly how to call them, then tries each promising method
with VNINDEX/VN30/HNX/UPCOM.
"""
from __future__ import annotations

import inspect
import sys
import time
import traceback


def _print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _sig(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except Exception as e:
        return f"<no sig: {e}>"


def _safe_call(label, fn, *args, **kwargs):
    """Call fn, print latency + result preview, swallow exceptions."""
    print(f"\n  → {label}")
    print(f"    args={args} kwargs={kwargs}")
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        dt = (time.time() - t0) * 1000
        print(f"    Latency: {dt:.0f} ms")
        if result is None:
            print(f"    Result: None")
            return None
        # DataFrame?
        if hasattr(result, "shape"):
            print(f"    Shape: {result.shape}")
            cols = [str(c) for c in getattr(result, "columns", [])]
            print(f"    Columns ({len(cols)}): {cols[:25]}")
            # Look for value-like columns
            value_cols = [c for c in cols if any(kw in c.lower() for kw in
                          ("value", "gtgd", "accumulated", "total", "mtchval"))]
            if value_cols:
                print(f"    *** VALUE-LIKE: {value_cols} ***")
            # Print first 3 rows
            try:
                print("    First rows:")
                for line in str(result.head(3)).split("\n")[:10]:
                    print(f"      {line}")
            except Exception:
                pass
        else:
            preview = str(result)[:400]
            print(f"    Result: {preview}")
        return result
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"    Latency: {dt:.0f} ms")
        print(f"    ERROR: {type(e).__name__}: {e}")
        # Short traceback
        tb = traceback.format_exc().split("\n")
        for line in tb[-5:]:
            print(f"      {line}")
        return None


def main():
    print(f"v3 test — vnstock_data introspection · {time.strftime('%H:%M:%S')}")

    try:
        import vnstock_data as vd
    except ImportError:
        print("vnstock_data không cài được")
        return

    _print_section("1. Class signatures")
    for name in ("Trading", "Quote", "Listing", "IndexGroup", "TopStock"):
        cls = getattr(vd, name, None)
        if cls is None:
            print(f"\n  {name}: not found")
            continue
        print(f"\n  {name}:")
        print(f"    __init__{_sig(cls.__init__)}")
        # List methods (non-underscore, callable)
        methods = [m for m in dir(cls) if not m.startswith("_")
                   and callable(getattr(cls, m, None))]
        for m in methods:
            mfn = getattr(cls, m, None)
            print(f"    .{m}{_sig(mfn)}")

    # ─── Try Trading.trading_stats ────────────────────────────────────────
    _print_section("2. Trading.trading_stats — most promising")
    try:
        Trading = vd.Trading
        # Try multiple init patterns to see which works
        init_candidates = [
            ("symbol+source", lambda: Trading(symbol="VNINDEX", source="VCI")),
            ("symbol only",   lambda: Trading(symbol="VNINDEX")),
            ("source only",   lambda: Trading(source="VCI")),
            ("no args",       lambda: Trading()),
        ]
        t = None
        for label, fn in init_candidates:
            try:
                t = fn()
                print(f"  ✓ Init OK with: {label}")
                break
            except Exception as e:
                print(f"  ✗ Init failed ({label}): {type(e).__name__}: {e}")

        if t is not None:
            method = getattr(t, "trading_stats", None)
            if method:
                print(f"\n  trading_stats signature: {_sig(method)}")
                # Try calling with no args
                _safe_call("trading_stats() no args", method)
                # Try with symbol parameter
                _safe_call("trading_stats(symbol='VNINDEX')", method, symbol="VNINDEX")
                _safe_call("trading_stats(symbols=['VNINDEX','VN30','HNXINDEX','UPCOM'])",
                          method, symbols=["VNINDEX","VN30","HNXINDEX","UPCOM"])
    except Exception as e:
        print(f"  Error: {e}")

    # ─── Try Trading.history for index ─────────────────────────────────────
    _print_section("3. Trading.history for index")
    try:
        if t is not None:
            method = getattr(t, "history", None)
            if method:
                print(f"\n  history signature: {_sig(method)}")
                # Try with reasonable params
                from datetime import date, timedelta
                today = date.today().isoformat()
                start = (date.today() - timedelta(days=2)).isoformat()
                _safe_call("history(start, end)", method, start=start, end=today)
                _safe_call("history(symbol='VNINDEX', start, end)", method,
                          symbol="VNINDEX", start=start, end=today)
    except Exception as e:
        print(f"  Error: {e}")

    # ─── Try Trading.order_stats / side_stats ─────────────────────────────
    _print_section("4. Trading.order_stats and side_stats")
    if t is not None:
        for mname in ("order_stats", "side_stats", "foreign_trade", "price_board"):
            m = getattr(t, mname, None)
            if m:
                print(f"\n  --- {mname}{_sig(m)} ---")
                _safe_call(f"{mname}() no args", m)
                _safe_call(f"{mname}(symbols=['VNINDEX'])", m, symbols=["VNINDEX"])
                _safe_call(f"{mname}(symbol='VNINDEX')", m, symbol="VNINDEX")

    # ─── Try IndexGroup ────────────────────────────────────────────────────
    _print_section("5. IndexGroup class")
    try:
        IG = vd.IndexGroup
        print(f"  __init__{_sig(IG.__init__)}")
        methods = [m for m in dir(IG) if not m.startswith("_")
                   and callable(getattr(IG, m, None))]
        for m in methods:
            print(f"  .{m}{_sig(getattr(IG, m))}")
        # Try init
        for label, fn in [
            ("()", lambda: IG()),
            ("symbol=VNINDEX", lambda: IG(symbol="VNINDEX")),
            ("group=VN30", lambda: IG(group="VN30")),
        ]:
            try:
                ig = fn()
                print(f"  ✓ IndexGroup init OK: {label}")
                # Try each method
                for m in methods:
                    if m in ("__init__",):
                        continue
                    fn_m = getattr(ig, m, None)
                    if fn_m and callable(fn_m):
                        _safe_call(f"IndexGroup.{m}()", fn_m)
                break
            except Exception as e:
                print(f"  ✗ IndexGroup init failed ({label}): {e}")
    except Exception as e:
        print(f"  Error: {e}")

    # ─── Try Quote.history with index ──────────────────────────────────────
    _print_section("6. Quote.history for VNINDEX (vnstock_data)")
    try:
        Quote = vd.Quote
        print(f"  __init__{_sig(Quote.__init__)}")
        for label, fn in [
            ("symbol+source", lambda: Quote(symbol="VNINDEX", source="VCI")),
            ("symbol only",   lambda: Quote(symbol="VNINDEX")),
        ]:
            try:
                q = fn()
                print(f"  ✓ Init OK: {label}")
                from datetime import date, timedelta
                today = date.today().isoformat()
                start = (date.today() - timedelta(days=2)).isoformat()
                _safe_call("Quote.history(start, end, interval='1m')",
                          q.history, start=start, end=today, interval="1m")
                _safe_call("Quote.intraday(page_size=10)",
                          q.intraday, page_size=10)
                break
            except Exception as e:
                print(f"  ✗ {label}: {e}")
    except Exception as e:
        print(f"  Error: {e}")

    # ─── Listing.all_indices and symbols_by_exchange ──────────────────────
    _print_section("7. Listing — discover symbols")
    try:
        Listing = vd.Listing
        for label, fn in [
            ("()", lambda: Listing()),
            ("symbol=VNM", lambda: Listing(symbol="VNM")),
        ]:
            try:
                ls = fn()
                print(f"  ✓ Init OK: {label}")
                _safe_call("all_indices()", getattr(ls, "all_indices"))
                _safe_call("symbols_by_exchange()",
                          getattr(ls, "symbols_by_exchange"))
                _safe_call("symbols_by_group(group='VN30')",
                          getattr(ls, "symbols_by_group"), group="VN30")
                break
            except Exception as e:
                print(f"  ✗ {label}: {e}")
    except Exception as e:
        print(f"  Error: {e}")

    _print_section("DONE — copy output gửi cho Claude")


if __name__ == "__main__":
    main()
