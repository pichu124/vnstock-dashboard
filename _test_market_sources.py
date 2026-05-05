"""Test script — verify which data source can give us realtime market GTGD.

Run from repo root:
    python _test_market_sources.py

Tests 3 sources for VNINDEX/VN30/HNX/UPCOM realtime trading value (GTGD):
  1. SSI iboard public API
  2. cafef.vn live data API
  3. vnstock library — Trading.price_board() and Quote variants

For each source: prints HTTP status, latency, raw response sample, and
whether a GTGD/totalValue field is present.

After running, paste the output back so we can pick the most reliable source.
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
    print(f"  {k:.<28} {v}")


def _find_value_keys(obj: Any, path: str = "") -> list[str]:
    """Recursively find keys that look like trading value (gtgd/totalValue/...)."""
    hits: list[str] = []
    keywords = ("totalvalue", "total_value", "totalvalmt", "totalmatchval",
                "tradingvalue", "value", "gtgd", "totalnmval", "matchval",
                "totalvolume", "total_volume", "vol", "matchvolume")
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            full = f"{path}.{k}" if path else k
            if any(kw in kl for kw in keywords) and not isinstance(v, (dict, list)):
                hits.append(f"{full} = {v!r}")
            if isinstance(v, (dict, list)):
                hits.extend(_find_value_keys(v, full))
    elif isinstance(obj, list) and obj:
        # only inspect first element of lists to avoid noise
        hits.extend(_find_value_keys(obj[0], path + "[0]"))
    return hits


# ─── Source 1: SSI iboard ─────────────────────────────────────────────────
def test_ssi() -> None:
    _print_section("SOURCE 1 — SSI iboard public API")
    endpoints = [
        # Most commonly used patterns from open-source projects
        ("exchangeIndex hose",
         "https://iboard-api.ssi.com.vn/v2/stock/exchangeIndex?exchange=hose"),
        ("exchangeIndex hnx",
         "https://iboard-api.ssi.com.vn/v2/stock/exchangeIndex?exchange=hnx"),
        ("exchangeIndex upcom",
         "https://iboard-api.ssi.com.vn/v2/stock/exchangeIndex?exchange=upcom"),
        ("group VN30",
         "https://iboard-api.ssi.com.vn/v2/stock/group?group=VN30"),
        # Alternative endpoint sometimes seen
        ("indices",
         "https://iboard-query.ssi.com.vn/v2/stock/indices"),
        # Total trading statistic (may exist)
        ("total-trading-statistic",
         "https://iboard-api.ssi.com.vn/v2/stock/total-trading-statistic"),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://iboard.ssi.com.vn",
        "Referer": "https://iboard.ssi.com.vn/",
    }
    for label, url in endpoints:
        print(f"\n  → {label}")
        _print_kv("URL", url)
        t0 = time.time()
        try:
            r = requests.get(url, headers=headers, timeout=8)
            dt = (time.time() - t0) * 1000
            _print_kv("Status", r.status_code)
            _print_kv("Latency", f"{dt:.0f} ms")
            ct = r.headers.get("content-type", "")
            _print_kv("Content-Type", ct)
            if r.status_code == 200 and "json" in ct:
                data = r.json()
                hits = _find_value_keys(data)
                _print_kv("Value-like keys", f"{len(hits)} found")
                for h in hits[:8]:
                    print(f"      • {h}")
                # First 400 chars of raw JSON
                sample = json.dumps(data, ensure_ascii=False)[:400]
                _print_kv("Sample", sample + ("…" if len(sample) >= 400 else ""))
            else:
                _print_kv("Body", r.text[:200])
        except Exception as e:
            _print_kv("ERROR", f"{type(e).__name__}: {e}")


# ─── Source 2: cafef live ─────────────────────────────────────────────────
def test_cafef() -> None:
    _print_section("SOURCE 2 — cafef.vn live API")
    endpoints = [
        ("livedata index VNINDEX",
         "https://s.cafef.vn/Ajax/PageNew/HsxIndex/IndexValue.ashx?index=VNINDEX"),
        ("livedata index HNX",
         "https://s.cafef.vn/Ajax/PageNew/HnxIndex/IndexValue.ashx?index=HNXIndex"),
        # msh-appdata is the new endpoint (2024+)
        ("msh-appdata index list",
         "https://msh-appdata.cafef.vn/rest-api/api/v1/IndexValue"),
        ("msh-appdata vnindex",
         "https://msh-appdata.cafef.vn/rest-api/api/v1/IndexValue?indexCode=VNINDEX"),
        # Generic livedata page
        ("livedata getindexlist",
         "https://msh-appdata.cafef.vn/rest-api/api/v1/IndexList"),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://cafef.vn",
        "Referer": "https://cafef.vn/",
    }
    for label, url in endpoints:
        print(f"\n  → {label}")
        _print_kv("URL", url)
        t0 = time.time()
        try:
            r = requests.get(url, headers=headers, timeout=8)
            dt = (time.time() - t0) * 1000
            _print_kv("Status", r.status_code)
            _print_kv("Latency", f"{dt:.0f} ms")
            ct = r.headers.get("content-type", "")
            _print_kv("Content-Type", ct)
            if r.status_code == 200:
                if "json" in ct:
                    data = r.json()
                    hits = _find_value_keys(data)
                    _print_kv("Value-like keys", f"{len(hits)} found")
                    for h in hits[:8]:
                        print(f"      • {h}")
                    sample = json.dumps(data, ensure_ascii=False)[:400]
                    _print_kv("Sample", sample + ("…" if len(sample) >= 400 else ""))
                else:
                    _print_kv("Body (first 300)", r.text[:300])
            else:
                _print_kv("Body", r.text[:200])
        except Exception as e:
            _print_kv("ERROR", f"{type(e).__name__}: {e}")


# ─── Source 3: vnstock library ────────────────────────────────────────────
def test_vnstock() -> None:
    _print_section("SOURCE 3 — vnstock library")
    try:
        from vnstock import Vnstock
    except ImportError as e:
        _print_kv("ERROR", f"vnstock không cài được: {e}")
        return

    # 3a. Trading.price_board for index symbols
    print("\n  → Trading.price_board(['VNINDEX','VN30','HNXINDEX','UPCOM'])")
    for source in ("VCI", "TCBS"):
        print(f"\n  ━━ source={source} ━━")
        try:
            t0 = time.time()
            stock = Vnstock().stock(symbol="VNINDEX", source=source)
            tr = stock.trading
            df = tr.price_board(["VNINDEX", "VN30", "HNXINDEX", "UPCOM"])
            dt = (time.time() - t0) * 1000
            _print_kv("Latency", f"{dt:.0f} ms")
            if df is None or df.empty:
                _print_kv("Result", "empty DataFrame")
            else:
                _print_kv("Shape", df.shape)
                _print_kv("Columns", list(df.columns))
                # Look for value-like columns
                value_cols = [c for c in df.columns
                              if any(kw in c.lower() for kw in
                                     ("value", "gtgd", "matchval", "total"))]
                _print_kv("Value-like cols", value_cols)
                print("    First row:")
                if len(df) > 0:
                    print(df.iloc[0].to_dict())
        except Exception as e:
            _print_kv("ERROR", f"{type(e).__name__}: {e}")

    # 3b. quote.intraday for index — does it return tick data with value?
    print("\n  → quote.intraday(symbol='VNINDEX')  [VCI]")
    try:
        t0 = time.time()
        stock = Vnstock().stock(symbol="VNINDEX", source="VCI")
        df = stock.quote.intraday(symbol="VNINDEX", page_size=10)
        dt = (time.time() - t0) * 1000
        _print_kv("Latency", f"{dt:.0f} ms")
        if df is None or (hasattr(df, "empty") and df.empty):
            _print_kv("Result", "empty")
        else:
            _print_kv("Shape", df.shape)
            _print_kv("Columns", list(df.columns))
            print("    First 3 rows:")
            print(df.head(3).to_string())
    except Exception as e:
        _print_kv("ERROR", f"{type(e).__name__}: {e}")


def main() -> None:
    print("Testing 3 sources for realtime VN market GTGD...")
    print(f"Running at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Trading hours (VN): Mon-Fri 09:00-15:00 (ICT). Tests work 24/7,")
    print(f"but value fields may be 0/last-known outside trading hours.")

    test_ssi()
    test_cafef()
    test_vnstock()

    _print_section("DONE — copy toàn bộ output ở trên gửi cho Claude")


if __name__ == "__main__":
    main()
