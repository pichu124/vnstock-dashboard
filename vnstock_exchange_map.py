"""
Build / read a lightweight ticker → exchange map.

Why a separate module?
----------------------
vnstock_classifier.py produces `industry_classification.parquet` which
includes `exchange`, but running the full classifier requires AI API calls
per ticker (expensive). For the anomaly scanner we only need to know which
exchange a ticker trades on (HOSE / HNX / UPCOM) to apply the correct
price-band rule. That's cheap: one ``Reference().equity.list(exchange=…)``
call per exchange returns the entire listing.

This module:
* ``build_exchange_map(warehouse)`` — fetches the 3 listings from vnstock
  and writes `_meta/exchange_map.json` as a simple `{ticker: exchange}`.
* ``load_exchange_map(warehouse)`` — reads both sources (classifier parquet
  + exchange_map.json) and returns the merged dict.

Safe to run many times — each call overwrites atomically.

CLI
---
    python vnstock_exchange_map.py --build
    python vnstock_exchange_map.py --show VCB FPT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"
MAP_FILE = "exchange_map.json"
EXCHANGES = ("HOSE", "HNX", "UPCOM")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def load_exchange_map(warehouse: Path = DEFAULT_WAREHOUSE) -> dict[str, str]:
    """Merge exchange_map.json with the classifier's parquet, latter wins."""
    out: dict[str, str] = {}

    # 1) Cheap JSON map first
    path = Path(warehouse) / META_SUBDIR / MAP_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            if isinstance(raw, dict):
                for k, v in raw.items():
                    ex = _normalise_exchange(v)
                    if ex:
                        out[str(k).upper()] = ex
        except Exception:
            pass

    # 2) Classifier parquet — more authoritative when present
    cls_path = Path(warehouse) / META_SUBDIR / "industry_classification.parquet"
    if cls_path.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(cls_path)
            if "ticker" in df.columns and "exchange" in df.columns:
                for _, row in df[["ticker", "exchange"]].dropna().iterrows():
                    ex = _normalise_exchange(row["exchange"])
                    if ex:
                        out[str(row["ticker"]).upper()] = ex
        except Exception:
            pass

    return out


def build_exchange_map(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    verbose: bool = False,
) -> dict[str, str]:
    """Fetch ticker → exchange from vnstock listing API and persist.

    Uses ``vnstock_data.Reference`` when available (Golden-tier), otherwise
    the free ``vnstock.Listing`` endpoint. On failure, returns whatever has
    been collected so far and leaves any existing map untouched.
    """
    mapping: dict[str, str] = {}

    reference = _get_reference()
    if reference is None:
        if verbose:
            print("[exchange_map] neither vnstock_data.Reference nor "
                  "vnstock.Listing available")
    else:
        for ex in EXCHANGES:
            try:
                df = reference(ex)
            except Exception as e:
                if verbose:
                    print(f"[exchange_map] {ex}: fetch failed — {e}")
                continue
            if df is None or len(df) == 0:
                continue
            col = _pick_ticker_column(df.columns)
            if col is None:
                continue
            for sym in df[col].dropna().astype(str).str.upper():
                mapping[sym] = ex
            if verbose:
                print(f"[exchange_map] {ex}: {len(df)} tickers")

    if not mapping:
        if verbose:
            print("[exchange_map] empty mapping — keeping existing file")
        return mapping

    _atomic_write(Path(warehouse) / META_SUBDIR / MAP_FILE, mapping)
    if verbose:
        print(f"[exchange_map] wrote {len(mapping)} tickers → "
              f"{Path(warehouse) / META_SUBDIR / MAP_FILE}")
    return mapping


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _get_reference():
    """Return a callable (exchange: str) -> DataFrame, or None."""
    # Prefer vnstock_data (sponsor tier, richer data).
    try:
        from vnstock_data import Reference
        try:
            from vnstock_auth import ensure_api_key
            ensure_api_key()
        except Exception:
            pass
        ref = Reference()
        return lambda ex: ref.equity.list(exchange=ex)
    except ImportError:
        pass

    # Fallback: free vnstock Listing
    try:
        from vnstock import Listing
        listing = Listing()
        return lambda ex: listing.symbols_by_exchange().pipe(
            lambda df: df[df["exchange"].str.upper() == ex]
            if "exchange" in df.columns else df
        )
    except Exception:
        return None


def _pick_ticker_column(columns) -> str | None:
    for c in columns:
        if str(c).lower() in ("ticker", "symbol", "code",
                              "stocksymbol", "stock_symbol"):
            return c
    # Last-resort: use the first column
    return columns[0] if len(columns) > 0 else None


def _normalise_exchange(value) -> str:
    if value is None:
        return ""
    v = str(value).strip().upper()
    if v in ("HOSE", "HSX") or "HO" in v or "HSX" in v:
        return "HOSE"
    if v in ("HNX",) or "HN" in v:
        return "HNX"
    if v in ("UPCOM", "UPCOM-INDEX", "UPINDEX") or "UP" in v:
        return "UPCOM"
    return ""


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True,
                                   ensure_ascii=False))
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    ap.add_argument("--build", action="store_true",
                    help="Fetch listings and write _meta/exchange_map.json")
    ap.add_argument("--show", nargs="*", metavar="TICKER",
                    help="Print the exchange for given tickers")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.build:
        m = build_exchange_map(Path(args.warehouse), verbose=args.verbose)
        print(f"[exchange_map] wrote {len(m)} tickers")
    if args.show:
        mp = load_exchange_map(Path(args.warehouse))
        for t in args.show:
            print(f"{t}: {mp.get(t.upper(), '_UNKNOWN')}")
    if not args.build and not args.show:
        ap.print_help()


if __name__ == "__main__":
    main()


__all__ = ["build_exchange_map", "load_exchange_map", "EXCHANGES"]
