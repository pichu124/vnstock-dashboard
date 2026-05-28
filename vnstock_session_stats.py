"""
vnstock_session_stats.py — Session stats helpers (no Streamlit dependency).

Realtime architecture (Option A — calibrated estimate):
  • Backfill (past days): Trading.price_history(VNINDEX/VN30/HNXINDEX/UPCOM,
    source='VCI') gives EOD-accurate `total_value` per trading day. EOD
    batch posts ~24h after market close.
  • Today (during trading): Quote.history(INDEX, interval='1m') provides
    the cumulative market volume from 9:00; multiply by per-index
    calibrated avg_price/share computed from last N days of price_history.
    Accuracy ~95-98% during the day; auto-corrected to the exact value
    when the EOD batch posts the next morning.
  • Each row carries a `status` field: "exact" (from price_history) or
    "estimate" (from calibrated formula). UI uses this to show 🟢/🟡.

NOTE: vnstock_data does NOT expose realtime total_value for indices.
We exhaustively tested SSI iboard, cafef, and vnstock library endpoints —
see _test_market_sources.py history. The only realtime-accurate paths
require either reverse-engineering iboard.ssi.com.vn DevTools (URL
discovery) or aggregating per-stock price_board (slow, requires testing
batch latency). Both are deferred to a future improvement; tracked in
CLAUDE.md "Future improvements" section.
"""
from __future__ import annotations

import json
import logging
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

logging.getLogger("vnstock.common.data").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=UserWarning, module=r"vnstock")

import pandas as pd

SESSION_STATS_PATH = Path("data_warehouse/_meta/market_session_stats.json")

SESSION_WINDOWS = {
    "9h-10h":   ("09:00", "10:00"),
    "9h-11h30": ("09:00", "11:30"),
    "9h-14h":   ("09:00", "14:00"),
    "9h-15h":   ("09:00", "15:00"),
}

SESSION_INDICES = ["VNINDEX", "VN30", "HNX", "UPCOM"]

# Symbol used by vnstock_data Trading.price_history for each display name.
# These DIFFER from the vnstock free Quote.history symbols — verified
# empirically that "UPCOM" is rejected by price_history with
# "Invalid symbol" error; confirmed alias is "UPCOMINDEX" (2026-05-18).
_PRICE_HISTORY_SYMBOL = {
    "VNINDEX":  "VNINDEX",
    "VN30":     "VN30",
    "HNX":      "HNXINDEX",
    "UPCOM":    "UPCOMINDEX",  # confirmed working 2026-05-18
}

# Symbols for vnstock free Quote.history (used for intraday volume polling).
_QUOTE_INTRADAY_SYMBOL = {
    "VNINDEX":  "VNINDEX",
    "VN30":     "VN30",
    "HNX":      "HNXINDEX",
    "UPCOM":    "UPCOM",
}

# Fallback price/share if calibration data unavailable (initial run, all
# price_history calls failing). Calibrated against typical 2025-2026
# market figures; replaced as soon as price_history returns ≥1 row.
_FALLBACK_AVG_PRICE_VND = {
    "VNINDEX": 30000,
    "VN30":    44000,
    "HNX":     19000,
    "UPCOM":   13000,
}

# Bump when on-disk schema changes — load_session_stats_history()
# treats older versions as empty so backfill regenerates from scratch.
# v4: rebuild after switching backfill to interval='5m' (v3 used '1m' which
#     silently returned bogus/duplicated data for dates >5 days back, leaving
#     inflated values in the cache that the 0/0 retry logic couldn't catch).
SESSION_STATS_FORMAT_VERSION = 4

# Days of history used to compute calibration average price.
CALIBRATION_LOOKBACK_DAYS = 10


# ─── EOD-accurate history (Trading.price_history) ─────────────────────────

def _fetch_price_history(display_name: str) -> pd.DataFrame:
    """Fetch EOD-accurate daily totals for one index.

    Uses vnstock_data.Trading(symbol, source='VCI').price_history() which
    returns ~100 rows with `trading_date`, `total_value`, `total_volume`.
    Returns empty DataFrame on any error.
    """
    # Need a module that exposes Trading class.
    # vnii is the newer package name but may not expose Trading at top level;
    # vnstock_data always has it. Check both in order.
    # Need a module that exposes Trading class.
    # Suppress stdout/stderr during import to silence vnstock_data's
    # update-check print statements (📦 Vnstock X.Y.Z is available…).
    import contextlib, io as _io
    vd = None
    for _mod in ("vnstock_data", "vnii"):
        try:
            with contextlib.redirect_stdout(_io.StringIO()), \
                 contextlib.redirect_stderr(_io.StringIO()):
                _m = __import__(_mod)
            if hasattr(_m, "Trading"):
                vd = _m
                break
        except ImportError:
            continue
        except Exception:
            break
    if vd is None:
        return pd.DataFrame()

    symbol = _PRICE_HISTORY_SYMBOL[display_name]
    # Always pass explicit date range so the API doesn't return a stale
    # default window. 120 days covers the full calibration + backfill period.
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")

    for sym in [symbol]:
        try:
            t = vd.Trading(symbol=sym, source="VCI")
        except Exception:
            continue
        # Try explicit date range first; fall back to no-args if params rejected.
        for kwargs in (
            {"start": start_date, "end": end_date},
            {"start_date": start_date, "end_date": end_date},
            {},
        ):
            try:
                df = t.price_history(**kwargs)
                if df is not None and not df.empty:
                    df = df.copy()
                    df["trading_date"] = pd.to_datetime(df["trading_date"]).dt.date
                    return df
            except Exception:
                continue
    return pd.DataFrame()


def _compute_calibration(history_dfs: dict) -> dict:
    """Compute avg price/share per index from recent EOD totals.

    avg_price = mean(total_value / total_volume) over last N days where
    both fields are positive. Falls back to constants if data missing.
    """
    cal: dict = {}
    cutoff = date.today() - timedelta(days=CALIBRATION_LOOKBACK_DAYS * 2)
    for idx, df in history_dfs.items():
        if df is None or df.empty:
            cal[idx] = _FALLBACK_AVG_PRICE_VND[idx]
            continue
        recent = df[df["trading_date"] >= cutoff].copy()
        recent = recent[(recent["total_value"] > 0) & (recent["total_volume"] > 0)]
        recent = recent.head(CALIBRATION_LOOKBACK_DAYS)
        if recent.empty:
            cal[idx] = _FALLBACK_AVG_PRICE_VND[idx]
            continue
        ratios = recent["total_value"].astype(float) / recent["total_volume"].astype(float)
        cal[idx] = float(ratios.mean())
    return cal


# ─── Realtime intraday (Quote.history 1m) ─────────────────────────────────

def _fetch_intraday_volume(
    display_name: str, target_date: date, interval: str = "1m"
) -> pd.DataFrame:
    """Fetch intraday OHLCV bars for one index on a specific date.

    Uses vnstock free Quote.history. Returns columns
    [time, open, high, low, close, volume]. Empty on error.

    interval='1m' serves only ~5 days of history and is suited for live
    "today" stats. For backfill of older dates use interval='5m' which
    serves 30+ days; 5m bars still align with all session boundaries
    (10:00, 11:30, 14:00, 15:00).
    """
    from vnstock_auth import get_vnstock
    end = target_date.strftime("%Y-%m-%d")
    # Wider start window for 5m (more lenient lookup) so the API doesn't
    # narrow-window-reject older dates.
    days_back = 5 if interval == "5m" else 2
    start = (target_date - timedelta(days=days_back)).strftime("%Y-%m-%d")

    symbols = [_QUOTE_INTRADAY_SYMBOL[display_name]]
    if display_name == "UPCOM":
        symbols = ["UPCOMINDEX", "UPCOM", "UPCOM-INDEX", "UPINDEX"]
    elif display_name == "HNX":
        symbols = ["HNXINDEX", "HNX-INDEX", "HNX"]

    for sym in symbols:
        try:
            stock = get_vnstock(sym)
            df = stock.quote.history(start=start, end=end, interval=interval)
            if df is not None and not df.empty:
                df = df.copy()
                df["time"] = pd.to_datetime(df["time"])
                # Defense: vnstock occasionally returns duplicate bars at
                # the same timestamp (especially for older dates near the
                # API window edge). Without dedup, sum(volume) double-counts.
                df = df.drop_duplicates(subset=["time"], keep="first")
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _compute_window_stats_estimate(
    day_df: pd.DataFrame, end_time: str, avg_price_vnd: float
) -> dict:
    """Compute estimated GTGD for a session window from intraday volume.

    GTGD ≈ cumulative_volume × avg_price/share. Marked status='estimate'.
    Mask clamped to 09:00 ≤ time ≤ end_time so any spurious bars before
    market open (e.g. ATO pre-open auction at 08:45) don't inflate totals.
    """
    if day_df.empty:
        return {"vol": 0, "gtgd": 0.0, "gtgd_per_vol": 0, "status": "estimate"}
    times = day_df["time"].dt.strftime("%H:%M")
    mask = (times >= "09:00") & (times <= end_time)
    win = day_df[mask]
    if win.empty:
        return {"vol": 0, "gtgd": 0.0, "gtgd_per_vol": 0, "status": "estimate"}
    vol = float(win["volume"].sum())
    gtgd = vol * avg_price_vnd / 1e9  # tỷ VND
    return {
        "vol": int(vol),
        "gtgd": round(gtgd, 1),
        "gtgd_per_vol": round(avg_price_vnd, 0),
        "status": "estimate",
    }


# ─── Public API ───────────────────────────────────────────────────────────

def compute_session_stats(target_date: date | None = None) -> dict:
    """Compute session stats for target_date (default: today).

    Returns {window_name: {index_name: {vol, gtgd, gtgd_per_vol, status}}}.
    Uses calibrated estimate from intraday volume — status='estimate'.
    The 9h-15h slot is replaced with EOD-exact value via
    reconcile_with_price_history() once the price_history batch posts.
    """
    target = target_date or date.today()
    result: dict = {}

    # Get calibration from recent price_history
    history_dfs: dict = {idx: _fetch_price_history(idx) for idx in SESSION_INDICES}
    calibration = _compute_calibration(history_dfs)

    # Fetch intraday for each index
    intraday: dict = {}
    for idx in SESSION_INDICES:
        df = _fetch_intraday_volume(idx, target)
        if not df.empty:
            day_df = df[df["time"].dt.date == target].copy()
            if not day_df.empty:
                intraday[idx] = day_df.sort_values("time")

    # Compute per window per index
    for window_name, (_, end_time) in SESSION_WINDOWS.items():
        window_stats: dict = {}
        for idx in SESSION_INDICES:
            window_stats[idx] = _compute_window_stats_estimate(
                intraday.get(idx, pd.DataFrame()),
                end_time,
                calibration.get(idx, _FALLBACK_AVG_PRICE_VND[idx]),
            )
        result[window_name] = window_stats

    return result


def backfill_session_stats(*, days: int = 60) -> int:
    """Backfill historical session stats from price_history (EOD-accurate).

    For each past trading day in the last `days`:
      • 9h-15h slot: EXACT total_value from Trading.price_history (status='exact').
        If price_history is unavailable for an index (e.g. UPCOM symbol
        not yet identified), fall back to intraday volume × calibrated
        avg_price (status='estimate') so the cell shows a value instead
        of 0.
      • 9h-10h, 9h-11h30, 9h-14h slots: ESTIMATE from intraday volume
        × calibrated avg_price (since price_history is daily-only,
        no per-window breakdown is available).

    Only fills missing dates; existing entries are kept. Returns count of
    dates filled.
    """
    all_data = load_session_stats_history()

    # Get full price_history per index
    history_dfs: dict = {idx: _fetch_price_history(idx) for idx in SESSION_INDICES}
    if not any(not df.empty for df in history_dfs.values()):
        return 0

    calibration = _compute_calibration(history_dfs)

    # Find candidate dates (any trading_date in any index's history)
    all_dates: set = set()
    cutoff = date.today() - timedelta(days=days)
    for df in history_dfs.values():
        if df.empty:
            continue
        for d in df["trading_date"]:
            if isinstance(d, date) and d >= cutoff and d.weekday() < 5:
                all_dates.add(d)

    filled = 0
    for d in sorted(all_dates, reverse=True):
        d_str = d.isoformat()
        existing = all_data.get(d_str, {})
        existing_full = existing.get("9h-15h", {})

        # Determine which indexes need 9h-15h work this run:
        # • Need work if cell is missing OR vol == 0 (initial broken / stale)
        # • Also refetch if 'exact' cell is missing the matched/deal split
        #   (gtgd_matched / gtgd_deal — added in commit 2ca28e2; cells
        #   populated before that lack these diagnostic fields).
        def _needs_work_full(idx: str) -> bool:
            cell = existing_full.get(idx)
            if not cell:
                return True
            if cell.get("vol", 0) == 0 and cell.get("gtgd", 0) == 0:
                return True
            if cell.get("status") == "exact" and "gtgd_matched" not in cell:
                return True
            return False

        # Per partial-window, list indexes that need re-fetch (missing window
        # OR cell is 0/0 — earlier backfill with interval=1m failed for old
        # dates because the 1m API only serves ~5 days back).
        def _partial_indexes_needing_work(wn: str) -> list[str]:
            if wn not in existing:
                return list(SESSION_INDICES)
            w = existing[wn]
            return [
                idx for idx in SESSION_INDICES
                if w.get(idx, {}).get("vol", 0) == 0
                and w.get(idx, {}).get("gtgd", 0) == 0
            ]

        indexes_to_update_full = [idx for idx in SESSION_INDICES if _needs_work_full(idx)]
        partial_holes: dict = {
            wn: _partial_indexes_needing_work(wn)
            for wn in ("9h-10h", "9h-11h30", "9h-14h")
        }
        any_partial_holes = any(partial_holes.values())

        if not indexes_to_update_full and not any_partial_holes:
            continue

        # Determine which indexes need ANY intraday fetch (for 9h-15h
        # fallback or for any partial-window hole). Fetch each ONCE per day.
        indexes_needing_intraday: set = set()
        for idx in indexes_to_update_full:
            df = history_dfs.get(idx, pd.DataFrame())
            row = df[df["trading_date"] == d] if not df.empty else None
            if row is None or row.empty:
                indexes_needing_intraday.add(idx)  # 9h-15h fallback needs intraday
        for wn, idxs in partial_holes.items():
            indexes_needing_intraday.update(idxs)

        # Use 5m interval — serves 30+ days reliably; 1m only ~5 days.
        intraday_per_idx: dict = {}
        for idx in indexes_needing_intraday:
            idf = _fetch_intraday_volume(idx, d, interval="5m")
            if not idf.empty:
                intraday_per_idx[idx] = idf[idf["time"].dt.date == d].sort_values("time")
            else:
                intraday_per_idx[idx] = pd.DataFrame()

        # Build 9h-15h: prefer price_history exact; fallback to intraday est.
        full_session = dict(existing_full)
        for idx in indexes_to_update_full:
            df = history_dfs.get(idx, pd.DataFrame())
            row = df[df["trading_date"] == d] if not df.empty else None
            if row is not None and not row.empty:
                r0 = row.iloc[0]
                tv = float(r0["total_value"])
                tvol = float(r0["total_volume"])
                # Capture matched + deal breakdown for diagnostics. On days
                # with large block deals, total_value can spike (e.g. 9/3,
                # 10/3 in Mar 2026 looked anomalously high). matched_value
                # filters those out — useful when the user wants pure
                # session GTGD comparable across days.
                mv = float(r0.get("matched_value", 0)) if "matched_value" in r0.index else 0.0
                mvol = float(r0.get("matched_volume", 0)) if "matched_volume" in r0.index else 0.0
                dv = float(r0.get("deal_value", 0)) if "deal_value" in r0.index else 0.0
                full_session[idx] = {
                    "vol": int(tvol),
                    "gtgd": round(tv / 1e9, 1),
                    "gtgd_per_vol": round(tv / tvol, 0) if tvol > 0 else 0,
                    "status": "exact",
                    # Diagnostic fields (not displayed; available for future
                    # UI toggle "GTGD khớp lệnh" vs "GTGD tổng").
                    "vol_matched": int(mvol),
                    "gtgd_matched": round(mv / 1e9, 1),
                    "gtgd_deal": round(dv / 1e9, 1),
                }
            else:
                full_session[idx] = _compute_window_stats_estimate(
                    intraday_per_idx.get(idx, pd.DataFrame()),
                    "15:00",
                    calibration.get(idx, _FALLBACK_AVG_PRICE_VND[idx]),
                )

        # Partial windows: only refresh cells that were missing or 0/0.
        # Preserve already-good cells from prior runs (avoid unnecessary
        # writes that could shift values due to calibration drift).
        partial_windows: dict = {
            wn: dict(existing.get(wn, {})) for wn in ("9h-10h", "9h-11h30", "9h-14h")
        }
        for wn, idxs_to_refresh in partial_holes.items():
            if not idxs_to_refresh:
                continue
            end_t = SESSION_WINDOWS[wn][1]
            for idx in idxs_to_refresh:
                partial_windows[wn][idx] = _compute_window_stats_estimate(
                    intraday_per_idx.get(idx, pd.DataFrame()),
                    end_t,
                    calibration.get(idx, _FALLBACK_AVG_PRICE_VND[idx]),
                )

        all_data[d_str] = {**partial_windows, "9h-15h": full_session}
        filled += 1

    if filled > 0:
        _write_history(all_data, calibration=calibration)

    return filled


def reconcile_with_price_history() -> int:
    """Replace estimated 9h-15h slots with exact values from price_history.

    Run on each dashboard load (or daily). When the EOD batch posts a date
    we previously had as 'estimate', overwrite with the exact value.
    Returns count of slots upgraded.
    """
    all_data = load_session_stats_history()
    history_dfs: dict = {idx: _fetch_price_history(idx) for idx in SESSION_INDICES}
    if not any(not df.empty for df in history_dfs.values()):
        return 0

    upgraded = 0
    for d_str, day in list(all_data.items()):
        full = day.get("9h-15h", {})
        # Already exact? Skip.
        if all(full.get(idx, {}).get("status") == "exact" for idx in SESSION_INDICES):
            continue
        try:
            d = datetime.fromisoformat(d_str).date()
        except Exception:
            continue
        new_full = dict(full)
        any_upgrade = False
        for idx, df in history_dfs.items():
            if df.empty:
                continue
            row = df[df["trading_date"] == d]
            if row.empty:
                continue
            tv = float(row.iloc[0]["total_value"])
            tvol = float(row.iloc[0]["total_volume"])
            new_full[idx] = {
                "vol": int(tvol),
                "gtgd": round(tv / 1e9, 1),
                "gtgd_per_vol": round(tv / tvol, 0) if tvol > 0 else 0,
                "status": "exact",
            }
            any_upgrade = True
        if any_upgrade:
            day["9h-15h"] = new_full
            all_data[d_str] = day
            upgraded += 1

    if upgraded > 0:
        _write_history(all_data)
    return upgraded


def save_session_stats(stats: dict):
    """Save today's session stats to JSON. Keeps 90 days history."""
    all_data = load_session_stats_history()
    all_data[date.today().isoformat()] = stats
    _write_history(all_data)


def load_session_stats_history() -> dict:
    """Load session stats history from disk. Empty if schema mismatch."""
    if not SESSION_STATS_PATH.exists():
        return {}
    try:
        raw = json.loads(SESSION_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if raw.get("_format_version") != SESSION_STATS_FORMAT_VERSION:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_calibration() -> dict | None:
    """Read the most recent calibration block written by _write_history."""
    if not SESSION_STATS_PATH.exists():
        return None
    try:
        raw = json.loads(SESSION_STATS_PATH.read_text(encoding="utf-8"))
        return raw.get("_calibration")
    except Exception:
        return None


def _write_history(all_data: dict, calibration: dict | None = None):
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    pruned = {
        k: v for k, v in all_data.items()
        if not k.startswith("_") and k >= cutoff
    }
    pruned["_format_version"] = SESSION_STATS_FORMAT_VERSION
    if calibration is not None:
        pruned["_calibration"] = {
            **calibration,
            "_last_updated": date.today().isoformat(),
            "_lookback_days": CALIBRATION_LOOKBACK_DAYS,
        }
    else:
        # Preserve any existing calibration block.
        try:
            existing = json.loads(SESSION_STATS_PATH.read_text(encoding="utf-8"))
            if "_calibration" in existing:
                pruned["_calibration"] = existing["_calibration"]
        except Exception:
            pass
    SESSION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATS_PATH.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
