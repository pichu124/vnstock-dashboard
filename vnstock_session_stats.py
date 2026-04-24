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


def _fetch_index_intraday(index_symbol: str) -> pd.DataFrame:
    """Fetch 1m intraday data for an index. Returns last 5 calendar days."""
    from vnstock_auth import get_vnstock
    today = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")

    symbols_to_try = [index_symbol]
    if index_symbol == "UPCOM":
        symbols_to_try = ["UPCOM", "UPCOM-INDEX", "UPINDEX", "HNX30"]
    elif index_symbol == "HNXINDEX":
        symbols_to_try = ["HNXINDEX", "HNX-INDEX", "HNX"]

    for sym in symbols_to_try:
        try:
            stock = get_vnstock(sym)
            df = stock.quote.history(start=start, end=today, interval="1m")
            if df is not None and not df.empty:
                df["time"] = pd.to_datetime(df["time"])
                return df[["time", "open", "high", "low", "close", "volume"]].copy()
        except Exception:
            continue
    return pd.DataFrame()


def _compute_window_stats(day_df: pd.DataFrame, end_time: str) -> dict:
    if day_df.empty:
        return {"vol": 0, "gtgd": 0, "gtgd_per_vol": 0}
    mask = day_df["time"].dt.strftime("%H:%M") <= end_time
    window_df = day_df[mask]
    if window_df.empty:
        return {"vol": 0, "gtgd": 0, "gtgd_per_vol": 0}
    vol = float(window_df["volume"].sum())
    closes = window_df["close"].astype(float)
    volumes = window_df["volume"].astype(float)
    gtgd = float((closes * volumes).sum()) / (1e6 if closes.max() < 500 else 1e9)
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
                index_data.get(idx, pd.DataFrame()), end_time
            )
        result[window_name] = window_stats

    return result


def backfill_session_stats() -> int:
    """Fill gaps using the 5-day API window. Only fills missing dates.
    Returns number of dates filled."""
    all_data = load_session_stats_history()

    index_data: dict = {}
    for display_name, symbol in _INDEX_SYMBOL_MAP.items():
        df = _fetch_index_intraday(symbol)
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
                idx: _compute_window_stats(day_slices.get(idx, pd.DataFrame()), end_time)
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
    """Load full session stats history from disk."""
    if not SESSION_STATS_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_history(all_data: dict):
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    all_data = {k: v for k, v in all_data.items() if k >= cutoff}
    SESSION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATS_PATH.write_text(
        json.dumps(all_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
