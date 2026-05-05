"""
vnstock_session_stats.py — Session stats helpers (no Streamlit dependency).
Can be safely imported from vnstock_runner.py or any non-Streamlit context.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logging.getLogger("vnstock.common.data").setLevel(logging.WARNING)

import pandas as pd

SESSION_STATS_PATH = Path("data_warehouse/_meta/market_session_stats.json")

SESSION_WINDOWS = {
    "9h-10h":   ("09:00", "10:00"),
    "9h-11h30": ("09:00", "11:30"),
    "9h-14h":   ("09:00", "14:00"),
    "9h-15h":   ("09:00", "15:00"),
}

SESSION_INDICES = ["VNINDEX", "VN30", "HNX", "UPCOM"]

_INDEX_SYMBOL_MAP = {
    "VNINDEX": "VNINDEX",
    "VN30":    "VN30",
    "HNX":     "HNXINDEX",
    "UPCOM":   "UPCOM",
}

# vnstock's quote.history() for INDEX symbols returns only OHLCV — no
# trading-value field. The "close" is the index level (e.g. VNINDEX≈1300,
# HNX≈250), NOT a price-per-share. So `close × volume` does NOT compute
# GTGD. We approximate GTGD = volume_shares × avg_price_per_share, with
# per-index avg-price constants calibrated against typical 2025-2026
# Vietnamese market figures:
#   HOSE/VNINDEX:  ~700M shares/day × ~28k VND ≈ 20 nghìn tỷ
#   VN30:          ~200M  × ~32k    ≈ 6.4 nghìn tỷ
#   HNX:           ~75M   × ~22k    ≈ 1.6 nghìn tỷ
#   UPCOM:         ~50M   × ~13k    ≈ 0.65 nghìn tỷ
# Real avg price drifts ±20% day-to-day; these constants are an
# approximation, not exact. If vnstock later exposes a `value`/`gtgd`
# column, prefer that and fall back to this heuristic.
_AVG_PRICE_VND = {
    "VNINDEX": 28000,
    "VN30":    32000,
    "HNX":     22000,
    "UPCOM":   13000,
}

# Bump when the on-disk schema or formula changes — load_session_stats_history
# treats older versions as empty so backfill regenerates clean data.
SESSION_STATS_FORMAT_VERSION = 2


def _fetch_index_intraday(
    index_symbol: str, *, days: int = 5, interval: str = "1m"
) -> pd.DataFrame:
    """Fetch intraday OHLCV for an index over the last `days` calendar days.

    Default (1m / 5d) is suited for live "today" stats. For 30-day backfill,
    callers pass `days=35, interval="5m"` since vnstock's 1m endpoint only
    serves ~5 days of history; 5m bars still align with all session window
    boundaries (10:00, 11:30, 14:00, 15:00).
    """
    from vnstock_auth import get_vnstock
    today = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    symbols_to_try = [index_symbol]
    if index_symbol == "UPCOM":
        symbols_to_try = ["UPCOM", "UPCOM-INDEX", "UPINDEX", "HNX30"]
    elif index_symbol == "HNXINDEX":
        symbols_to_try = ["HNXINDEX", "HNX-INDEX", "HNX"]

    for sym in symbols_to_try:
        try:
            stock = get_vnstock(sym)
            df = stock.quote.history(start=start, end=today, interval=interval)
            if df is not None and not df.empty:
                df = df.copy()
                df["time"] = pd.to_datetime(df["time"])
                # Keep ALL columns — if vnstock ever adds a `value` / `gtgd`
                # field for indexes, _compute_window_stats will pick it up.
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _compute_window_stats(
    day_df: pd.DataFrame, end_time: str, index_name: str = "VNINDEX"
) -> dict:
    """Aggregate volume + estimated GTGD for one session window.

    GTGD is approximated as volume_shares × avg_price (per-index constant,
    see _AVG_PRICE_VND) because vnstock's index OHLCV doesn't carry a
    trading-value field. If a future vnstock version supplies one, prefer
    that column instead.
    """
    if day_df.empty:
        return {"vol": 0, "gtgd": 0, "gtgd_per_vol": 0}
    mask = day_df["time"].dt.strftime("%H:%M") <= end_time
    window_df = day_df[mask]
    if window_df.empty:
        return {"vol": 0, "gtgd": 0, "gtgd_per_vol": 0}
    vol = float(window_df["volume"].sum())

    # Prefer an actual value column from vnstock if present (forward-compat).
    value_col = next(
        (c for c in window_df.columns
         if c.lower() in ("value", "trading_value", "gtgd", "totalvalue", "total_value")),
        None,
    )
    if value_col is not None:
        gtgd = float(window_df[value_col].astype(float).sum()) / 1e9  # tỷ VND
    else:
        avg_price = _AVG_PRICE_VND.get(index_name, 25000)
        gtgd = vol * avg_price / 1e9  # tỷ VND

    return {
        "vol": int(vol),
        "gtgd": round(gtgd, 1),
        "gtgd_per_vol": round(gtgd * 1e9 / vol if vol > 0 else 0, 0),
    }


def compute_session_stats(target_date: date | None = None) -> dict:
    """Compute session stats for target_date (default: today).
    Returns {window_name: {index_name: {vol, gtgd, gtgd_per_vol}}}."""
    target = target_date or date.today()
    result: dict = {}

    index_data: dict = {}
    for display_name, symbol in _INDEX_SYMBOL_MAP.items():
        df = _fetch_index_intraday(symbol)
        if not df.empty:
            day_df = df[df["time"].dt.date == target].copy()
            if not day_df.empty:
                index_data[display_name] = day_df.sort_values("time")

    for window_name, (_, end_time) in SESSION_WINDOWS.items():
        window_stats: dict = {}
        for idx in SESSION_INDICES:
            window_stats[idx] = _compute_window_stats(
                index_data.get(idx, pd.DataFrame()), end_time, idx
            )
        result[window_name] = window_stats

    return result


def backfill_session_stats(*, days: int = 35, interval: str = "5m") -> int:
    """Fill gaps in history using a wider API window (default 35d / 5m bars).

    Only fills missing dates — existing entries are kept as-is. Returns the
    number of dates filled.
    """
    all_data = load_session_stats_history()

    index_data: dict = {}
    for display_name, symbol in _INDEX_SYMBOL_MAP.items():
        df = _fetch_index_intraday(symbol, days=days, interval=interval)
        if not df.empty:
            index_data[display_name] = df

    if not index_data:
        return 0

    all_dates: set = set()
    for df in index_data.values():
        all_dates |= set(df["time"].dt.date.unique())

    filled = 0
    for d in sorted(all_dates):
        d_str = d.isoformat()
        if d_str in all_data or d.weekday() >= 5:
            continue

        day_slices = {
            name: df[df["time"].dt.date == d].copy()
            for name, df in index_data.items()
        }
        result: dict = {}
        for window_name, (_, end_time) in SESSION_WINDOWS.items():
            result[window_name] = {
                idx: _compute_window_stats(day_slices.get(idx, pd.DataFrame()), end_time, idx)
                for idx in SESSION_INDICES
            }
        all_data[d_str] = result
        filled += 1

    if filled > 0:
        _write_history(all_data)

    return filled


def save_session_stats(stats: dict):
    """Save today's session stats to JSON. Keeps 90 days history."""
    all_data = load_session_stats_history()
    all_data[date.today().isoformat()] = stats
    _write_history(all_data)


def load_session_stats_history() -> dict:
    """Load full session stats history from disk.

    Returns empty if the on-disk format version is older than the current
    code expects — backfill_session_stats() will then regenerate from
    the live API with the corrected GTGD formula.
    """
    if not SESSION_STATS_PATH.exists():
        return {}
    try:
        raw = json.loads(SESSION_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    on_disk_version = raw.get("_format_version", 1)
    if on_disk_version != SESSION_STATS_FORMAT_VERSION:
        # Stale schema (e.g. data computed with the old buggy
        # close × volume formula). Treat as empty so backfill rebuilds.
        return {}
    # Strip metadata keys (anything starting with '_') before returning.
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _write_history(all_data: dict):
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    pruned = {
        k: v for k, v in all_data.items()
        if not k.startswith("_") and k >= cutoff
    }
    pruned["_format_version"] = SESSION_STATS_FORMAT_VERSION
    SESSION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATS_PATH.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
