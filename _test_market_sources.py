"""Test v2 — focus on what's promising after v1 results.

v1 conclusions:
  • SSI iboard URLs all 404 → guessed paths wrong, need real ones
  • cafef URLs all 404 → same
  • vnstock Trading.price_board() works but no accumulated_value for INDEX
  • User has vnstock_data sponsor package installed → may have extras

v2 tests:
  A. vnstock_data: list its modules + try market-summary methods
  B. price_board for STOCK symbols (VN30 list) → verify approximate GTGD
     via match_price × accumulated_volume + measure speed for 30+ symbols
  C. More SSI endpoints (GraphQL, securities-stats, real iboard paths)
  D. More cafef endpoints (msh-appdata real paths)

Run from repo root: python _test_market_sources.py
Paste output back to Claude after running.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("Cần cài requests: pip install requests")
    sys.exit(1)


def _print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _print_kv(k: str, v: Any) -> None:
    print(f"  {k:.<30} {v}")


def _safe_get(url: str, headers: dict | None = None,
              params: dict | None = None, timeout: int = 8) -> tuple[int, str, str, float]:
    """Returns (status, content_type, body_truncated, latency_ms)."""
    t0 = time.time()
    try:
        r = requests.get(url, headers=headers or {}, params=params, timeout=timeout)
        dt = (time.time() - t0) * 1000
        ct = r.headers.get("content-type", "")
        body = r.text[:300]
        return (r.status_code, ct, body, dt)
    except Exception as e:
        dt = (time.time() - t0) * 1000
        return (-1, "", f"{type(e).__name__}: {e}", dt)


def _safe_post(url: str, headers: dict | None = None,
               json_body: dict | None = None, timeout: int = 10) -> tuple[int, str, str, float]:
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers or {},
                          json=json_body, timeout=timeout)
        dt = (time.time() - t0) * 1000
        ct = r.headers.get("content-type", "")
        body = r.text[:400]
        return (r.status_code, ct, body, dt)
    except Exception as e:
        dt = (time.time() - t0) * 1000
        return (-1, "", f"{type(e).__name__}: {e}", dt)


# ─── A. vnstock_data sponsor package ──────────────────────────────────────
def test_vnstock_data() -> None:
    _print_section("A — vnstock_data sponsor package")
    try:
        import vnstock_data
        _print_kv("Imported", "OK")
        _print_kv("Version", getattr(vnstock_data, "__version__", "?"))
        # List public attrs
        attrs = [a for a in dir(vnstock_data) if not a.startswith("_")]
        _print_kv("Public attrs", attrs[:40])
    except ImportError as e:
        _print_kv("ImportError", e)
        return
    except Exception as e:
        _print_kv("Error", f"{type(e).__name__}: {e}")
        return

    # Try common entry points
    candidates = [
        ("Vnstock", "Vnstock"),
        ("Trading", "Trading"),
        ("Quote", "Quote"),
        ("Market", "Market"),
        ("Listing", "Listing"),
    ]
    for label, name in candidates:
        try:
            obj = getattr(vnstock_data, name, None)
            if obj is not None:
                methods = [m for m in dir(obj) if not m.startswith("_")]
                _print_kv(f"{label} methods", methods[:25])
        except Exception as e:
            _print_kv(f"{label}", f"err: {e}")

    # Specifically try a market-summary-like call
    print("\n  → Try vnstock_data.Vnstock().stock(symbol='VNINDEX').trading.price_board")
    try:
        from vnstock_data import Vnstock as VD
        t0 = time.time()
        st = VD().stock(symbol="VNINDEX", source="VCI")
        df = st.trading.price_board(["VNINDEX", "VN30", "HNXINDEX", "UPCOM"])
        dt = (time.time() - t0) * 1000
        _print_kv("Latency", f"{dt:.0f} ms")
        if df is not None and not df.empty:
            cols = [str(c) for c in df.columns]
            _print_kv("Columns", cols)
            # Look for accumulated_value or similar
            value_cols = [c for c in cols if any(
                kw in c.lower() for kw in ("value", "gtgd", "accumulated"))]
            _print_kv("Value-like cols", value_cols)
    except Exception as e:
        _print_kv("Error", f"{type(e).__name__}: {e}")


# ─── B. price_board for actual stocks (VN30) ──────────────────────────────
VN30 = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
        "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
        "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]


def _flatten_cols(df) -> dict:
    """Convert MultiIndex columns to flat dict per row, return first row."""
    if df is None or df.empty:
        return {}
    row0 = df.iloc[0]
    out = {}
    for c, v in row0.items():
        key = c if isinstance(c, str) else "_".join(str(x) for x in c)
        out[key] = v
    return out


def test_price_board_stocks() -> None:
    _print_section("B — Trading.price_board() for STOCKS (VN30)")
    try:
        from vnstock import Vnstock
    except ImportError:
        _print_kv("ImportError", "vnstock not installed")
        return

    try:
        t0 = time.time()
        st = Vnstock().stock(symbol="VCB", source="VCI")
        df = st.trading.price_board(VN30)
        dt = (time.time() - t0) * 1000
        _print_kv("Latency (30 stocks)", f"{dt:.0f} ms")
        _print_kv("Shape", df.shape if df is not None else "None")
        if df is not None and not df.empty:
            cols = [str(c) for c in df.columns]
            _print_kv("Columns", cols)
            print("\n    First row (VN30[0]):")
            for k, v in _flatten_cols(df).items():
                print(f"      {k:.<40} {v}")
            # Compute approximate GTGD = match_price × accumulated_volume
            try:
                # Find the right columns by tuple
                price_col = next(c for c in df.columns
                                 if isinstance(c, tuple) and c[1] == "match_price")
                vol_col = next(c for c in df.columns
                               if isinstance(c, tuple) and c[1] == "accumulated_volume")
                df_calc = df.copy()
                df_calc["est_gtgd"] = df_calc[price_col] * df_calc[vol_col]
                total = df_calc["est_gtgd"].sum() / 1e9  # tỷ VND
                _print_kv("Sum(price × accVol) for 30", f"{total:,.1f} tỷ VND")
                # Print top 5 biggest contributors
                df_calc = df_calc.sort_values("est_gtgd", ascending=False).head(5)
                sym_col = next(c for c in df.columns
                               if isinstance(c, tuple) and c[1] == "symbol")
                print("\n    Top 5 GTGD trong VN30:")
                for _, r in df_calc.iterrows():
                    print(f"      {r[sym_col]:<5} = {r['est_gtgd']/1e9:>8.1f} tỷ "
                          f"(price={r[price_col]}, accVol={r[vol_col]:,.0f})")
            except Exception as e:
                _print_kv("Calc error", f"{type(e).__name__}: {e}")
    except Exception as e:
        _print_kv("Error", f"{type(e).__name__}: {e}")

    # Test scaling: how does it scale with 100 stocks?
    print("\n  → Scaling test: price_board with ~100 stocks")
    try:
        # Make ~100 symbols by repeating VN30 with some variations
        # Actually use real diverse list — top liquid HOSE stocks
        big_list = VN30 + [
            "HCM", "VND", "DGC", "PNJ", "REE", "KBC", "DXG", "NLG", "VCG", "CII",
            "BCG", "HSG", "NKG", "DPM", "DCM", "PDR", "VPI", "DIG", "HHV", "LPB",
            "OCB", "EIB", "MSB", "VIX", "HUT", "C4G", "PAN", "DBC", "ANV", "VHC",
            "ITA", "LDG", "QCG", "DRH", "FLC", "ROS", "AMD", "HQC", "TCH", "NVL",
            "KDH", "DXS", "KBC", "SCR", "TDC", "IJC", "NTL", "SZC", "BCM", "VPI",
            "GMD", "VTP", "SAS", "ACV", "AST", "VOS", "PVS", "PVD", "PVT", "BSR",
            "MSN", "HBC", "CTD", "VCS", "TLG", "BMP", "TNG", "TTF", "VHC", "FRT",
        ][:80]
        seen = set()
        big_list = [s for s in big_list if s not in seen and not seen.add(s)]
        big_list = big_list[:100]
        t0 = time.time()
        df = st.trading.price_board(big_list)
        dt = (time.time() - t0) * 1000
        _print_kv("Latency (100 stocks)", f"{dt:.0f} ms")
        _print_kv("Shape", df.shape if df is not None else "None")
        if df is not None and not df.empty:
            try:
                price_col = next(c for c in df.columns
                                 if isinstance(c, tuple) and c[1] == "match_price")
                vol_col = next(c for c in df.columns
                               if isinstance(c, tuple) and c[1] == "accumulated_volume")
                est = (df[price_col] * df[vol_col]).sum() / 1e9
                _print_kv("Sum GTGD est (100 stocks)", f"{est:,.1f} tỷ VND")
            except Exception as e:
                _print_kv("Calc err", e)
    except Exception as e:
        _print_kv("Error", f"{type(e).__name__}: {e}")


# ─── C. More SSI endpoints (real ones from iboard) ────────────────────────
def test_ssi_v2() -> None:
    _print_section("C — SSI iboard real endpoints (v2)")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://iboard.ssi.com.vn",
        "Referer": "https://iboard.ssi.com.vn/",
        "Accept": "application/json",
    }
    endpoints = [
        # Real paths used by iboard.ssi.com.vn web
        "https://iboard-api.ssi.com.vn/v2/stock/group?group=HOSE",
        "https://iboard-api.ssi.com.vn/v2/stock/group?group=HNX",
        "https://iboard-api.ssi.com.vn/v2/stock/group?group=UPCOM",
        "https://iboard-query.ssi.com.vn/v2/stock/group?group=HOSE",
        "https://iboard-query.ssi.com.vn/v2/stock/group?group=VN30",
        "https://iboard-api.ssi.com.vn/v2/stock/securities/all",
        "https://iboard-api.ssi.com.vn/v2/stock/securities-stats-batch?stockCode=VNINDEX",
        # FC-data (real one)
        "https://fc-data.ssi.com.vn/api/v2/Market/Securities?market=HOSE&pageIndex=1&pageSize=10",
        # Stock info (snapshot)
        "https://iboard-query.ssi.com.vn/v2/stock/securities/exchange/HOSE",
    ]
    for url in endpoints:
        print(f"\n  → {url}")
        status, ct, body, dt = _safe_get(url, headers=headers)
        _print_kv("Status", status)
        _print_kv("Latency", f"{dt:.0f} ms")
        _print_kv("Content-Type", ct)
        if status == 200 and "json" in ct:
            try:
                data = json.loads(body if len(body) >= 200 else body)
                _print_kv("Body sample", json.dumps(data, ensure_ascii=False)[:300])
            except Exception:
                _print_kv("Body sample", body[:300])
        else:
            _print_kv("Body", body[:200])

    # Also try GraphQL endpoint
    print("\n  → GraphQL: wgateway-iboard")
    gql_url = "https://wgateway-iboard.ssi.com.vn/graphql"
    gql_query = {
        "query": """{ exchangeIndex { exchange indexValue prevIndexValue
            allValue allVolume change percent } }"""
    }
    status, ct, body, dt = _safe_post(gql_url, headers=headers, json_body=gql_query)
    _print_kv("Status", status)
    _print_kv("Latency", f"{dt:.0f} ms")
    _print_kv("Content-Type", ct)
    _print_kv("Body", body[:400])


# ─── D. More cafef endpoints ──────────────────────────────────────────────
def test_cafef_v2() -> None:
    _print_section("D — cafef real endpoints (v2)")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://cafef.vn",
        "Referer": "https://s.cafef.vn/",
    }
    endpoints = [
        # msh-appdata real paths
        "https://msh-appdata.cafef.vn/rest-api/api/v1/Index/GetIndex?Index=VNINDEX",
        "https://msh-appdata.cafef.vn/rest-api/api/v1/Market/GetIndex?Index=VNINDEX",
        "https://msh-appdata.cafef.vn/rest-api/api/v1/MarketStatistic/GetTopIndex",
        "https://msh-appdata.cafef.vn/rest-api/api/v1/MarketStatistic",
        # Liveboard
        "https://liveboard.cafef.vn/rest-api/api/v1/IndexValue?indexCode=VNINDEX",
        "https://liveboard.cafef.vn/rest-api/api/v1/Index/GetTopIndex",
        # Old Ajax endpoints
        "https://s.cafef.vn/Ajax/PageNew/IndexInfo.ashx?Index=VNINDEX",
        "https://s.cafef.vn/Ajax/PageNew/HOSEIndex/IndexValue.ashx",
        # Some sources reference these
        "https://cafef.vn/api/Index/GetIndexInfo?index=VNINDEX",
    ]
    for url in endpoints:
        print(f"\n  → {url}")
        status, ct, body, dt = _safe_get(url, headers=headers)
        _print_kv("Status", status)
        _print_kv("Latency", f"{dt:.0f} ms")
        _print_kv("Content-Type", ct)
        _print_kv("Body", body[:250])


def main() -> None:
    print("Test v2 — focus on what's promising after v1 results")
    print(f"Running at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    test_vnstock_data()
    test_price_board_stocks()
    test_ssi_v2()
    test_cafef_v2()
    _print_section("DONE — paste output cho Claude")


if __name__ == "__main__":
    main()
