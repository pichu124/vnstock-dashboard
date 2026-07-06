"""
Corp Action Registry — single source of truth for VN equity events.

Why a separate module?
----------------------
Corp action data lives in ≥ 3 different places today:
  * vnstock_data.Company.capital_history → bonus / split / capital increase
  * (future) CafeF or Vietstock scraper → cash dividends
  * (manual) operator overrides → CSV import

Each consumer (anomaly scanner, reconciler, dashboard) used to call a
separate loader, so adding a new source meant editing every consumer.
This module centralises that:

  Sources (heterogeneous) → register_event() → corp_actions_registry.parquet
                                              ↓
                              get_events_for_*() consulted by every consumer

Schema (data_warehouse/_meta/corp_actions_registry.parquet)
-----------------------------------------------------------
  ticker:         str, uppercased
  ex_date:        date (the day price adjusts)
  type:           "cash" | "split" | "bonus" | "rights" | "unknown"
  cash_amount:    float or NaN  — VND per share for cash events
  ratio:          float or NaN  — multiplier for split/bonus
  source:         str  — provenance: "capital_history", "cafef", "manual", ...
  confidence:     float in [0, 1]
  registered_at:  datetime
  note:           str, optional

The registry deduplicates on (ticker, ex_date, type). On conflict, the
higher-confidence row wins; ties are resolved by `registered_at` (last
write wins).

Public API
----------
* register_event(ticker, ex_date, type, ...) → dedupe + persist
* register_bulk(events) → many at once
* get_events_for_ticker(ticker) → DataFrame
* import_from_capital_history(warehouse) → bootstrap from cached events
* clear_source(source) → remove all rows from one source (e.g. for re-import)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"
REGISTRY_FILE = "corp_actions_registry.parquet"

VALID_TYPES = {"cash", "split", "bonus", "rights", "unknown"}
DEFAULT_CONFIDENCE = {
    "manual": 1.00,           # operator-curated wins everything
    "capital_history": 0.85,  # vnstock_data, reliable for splits/bonuses
    "cafef": 0.80,            # scraper, occasionally stale
    "vietstock": 0.80,
    "inferred": 0.50,         # heuristic from price gap, weak
    "unknown": 0.30,
}

REGISTRY_COLS = [
    "ticker", "ex_date", "type", "cash_amount", "ratio",
    "source", "confidence", "registered_at", "note",
]


# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────────────────────────────────────


def _registry_path(warehouse: Path) -> Path:
    return Path(warehouse) / META_SUBDIR / REGISTRY_FILE


def _atomic_write_parquet(path: Path, df: pd.DataFrame) -> None:
    """Atomic write with retry for Dropbox/AV transient locks on Windows."""
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            df.to_parquet(tmp, index=False)
            os.replace(str(tmp), str(path))
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.1 * (2 ** attempt))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    if last_err is not None:
        raise last_err


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=REGISTRY_COLS).astype({
        "ticker": str, "type": str, "cash_amount": float, "ratio": float,
        "source": str, "confidence": float, "note": str,
    })


def _load(warehouse: Path) -> pd.DataFrame:
    path = _registry_path(Path(warehouse))
    if not path.exists():
        return _empty_frame()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return _empty_frame()
    if df.empty:
        return _empty_frame()
    df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
    return df


def _normalise_event(
    ticker: str,
    ex_date,
    type_: str,
    cash_amount: float | None = None,
    ratio: float | None = None,
    source: str = "unknown",
    confidence: float | None = None,
    note: str | None = None,
) -> dict:
    """Build a registry row, applying defaults and validation."""
    type_ = (type_ or "unknown").lower()
    if type_ not in VALID_TYPES:
        type_ = "unknown"
    if confidence is None:
        confidence = DEFAULT_CONFIDENCE.get(source.lower(), 0.5)
    confidence = max(0.0, min(1.0, float(confidence)))
    return {
        "ticker": str(ticker).upper(),
        "ex_date": pd.to_datetime(ex_date).date(),
        "type": type_,
        "cash_amount": (
            float(cash_amount) if cash_amount is not None else float("nan")
        ),
        "ratio": float(ratio) if ratio is not None else float("nan"),
        "source": str(source),
        "confidence": confidence,
        "registered_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "note": str(note) if note else "",
    }


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the highest-confidence row per (ticker, ex_date, type).
    Ties resolved by registered_at (last write wins)."""
    if df.empty:
        return df
    df = df.sort_values(
        by=["confidence", "registered_at"],
        ascending=[False, False],
    )
    return df.drop_duplicates(
        subset=["ticker", "ex_date", "type"], keep="first"
    ).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Public CRUD
# ─────────────────────────────────────────────────────────────────────────────


def register_event(
    ticker: str,
    ex_date,
    type_: str,
    *,
    cash_amount: float | None = None,
    ratio: float | None = None,
    source: str = "manual",
    confidence: float | None = None,
    note: str | None = None,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> int:
    """Register one event. Returns total rows in registry after the write."""
    df = _load(warehouse)
    new_row = _normalise_event(
        ticker, ex_date, type_,
        cash_amount=cash_amount, ratio=ratio,
        source=source, confidence=confidence, note=note,
    )
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = _dedupe(df)
    _atomic_write_parquet(_registry_path(Path(warehouse)), df)
    return len(df)


def register_bulk(
    events: list[dict],
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> dict:
    """Register many events at once. Returns {added, skipped (dupes), total}."""
    if not events:
        return {"added": 0, "skipped": 0, "total": 0}
    df = _load(warehouse)
    before = len(df)
    new_rows = [_normalise_event(**e) for e in events]
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df = _dedupe(df)
    after = len(df)
    _atomic_write_parquet(_registry_path(Path(warehouse)), df)
    return {
        "added": after - before,
        "skipped": len(events) - (after - before),
        "total": after,
    }


def get_events_for_ticker(
    ticker: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    type_filter: str | None = None,
) -> pd.DataFrame:
    df = _load(warehouse)
    if df.empty:
        return df
    df = df[df["ticker"] == str(ticker).upper()]
    if type_filter:
        df = df[df["type"] == type_filter]
    return df.sort_values("ex_date").reset_index(drop=True)






def remove_event(
    ticker: str,
    ex_date,
    type_: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> int:
    """Remove a specific (ticker, ex_date, type) entry. Returns rows removed."""
    df = _load(warehouse)
    if df.empty:
        return 0
    target_d = pd.to_datetime(ex_date).date()
    mask = (
        (df["ticker"] == str(ticker).upper())
        & (df["ex_date"] == target_d)
        & (df["type"] == str(type_))
    )
    before = len(df)
    df = df[~mask]
    after = len(df)
    _atomic_write_parquet(_registry_path(Path(warehouse)), df)
    return before - after


def clear_source(
    source: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> int:
    """Remove every row from a given source. Returns rows removed."""
    df = _load(warehouse)
    if df.empty:
        return 0
    before = len(df)
    df = df[df["source"] != source]
    after = len(df)
    _atomic_write_parquet(_registry_path(Path(warehouse)), df)
    return before - after


def summary(warehouse: Path = DEFAULT_WAREHOUSE) -> dict:
    """Concise stats for the health dashboard."""
    df = _load(warehouse)
    if df.empty:
        return {"total": 0, "by_type": {}, "by_source": {}}
    return {
        "total": int(len(df)),
        "by_type": df["type"].value_counts().to_dict(),
        "by_source": df["source"].value_counts().to_dict(),
        "tickers_covered": int(df["ticker"].nunique()),
        "date_range": (
            f"{df['ex_date'].min()} → {df['ex_date'].max()}"
            if not df.empty else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap from existing sources
# ─────────────────────────────────────────────────────────────────────────────


def import_from_capital_history(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    verbose: bool = False,
) -> dict:
    """Sweep _meta/corp_actions/*.parquet (the cache from
    vnstock_adjust.refresh_events) and load every event into the registry
    under source='capital_history'."""
    cdir = Path(warehouse) / META_SUBDIR / "corp_actions"
    if not cdir.exists():
        return {"added": 0, "skipped": 0, "total": 0,
                "error": "no corp_actions cache found"}

    events: list[dict] = []
    for f in cdir.glob("*.parquet"):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if df.empty or "ex_date" not in df.columns:
            continue
        df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
        for _, r in df.iterrows():
            t = str(r.get("type", "unknown")).lower()
            cash = r.get("cash_amount")
            ratio = r.get("ratio")
            events.append({
                "ticker": r.get("ticker", f.stem),
                "ex_date": r["ex_date"],
                "type_": t,
                "cash_amount": (float(cash) if pd.notna(cash) else None),
                "ratio": (float(ratio) if pd.notna(ratio) else None),
                "source": "capital_history",
                "note": "imported from vnstock_adjust cache",
            })
        if verbose:
            print(f"[registry] {f.stem}: {len(df)} events")

    return register_bulk(events, warehouse=warehouse)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
