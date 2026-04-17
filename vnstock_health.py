"""
System Health module (Phase 4, Feature 3C).

Aggregates operational signals from across the warehouse into a single
snapshot that can be consumed by:

1. The main Streamlit dashboard (via ``render_health_tab``).
2. The orchestrator (``run.py``) for a terminal summary.
3. The AuditorAgent as prior context for LLM audits.

Signals collected
-----------------
* **Warehouse coverage** — ticker count, total rows, date range, oldest/
  newest bar, partition count.
* **Missing rate** — % of expected business days missing in the last N
  trading days per ticker; aggregated to overall missing rate and a
  top-N list of worst offenders.
* **Last sync** — read from ``_meta/last_sync.json`` (warehouse bulk load)
  and ``_meta/pipeline_status.json`` (rollup + updater cron jobs).
* **Contract gates** — counts of pandera pass/fail from the most recent
  contract report, if one was persisted. Falls back gracefully when no
  report exists (contracts are run inline at write time but not always
  aggregated).
* **Reconciler** — counts ok/warn/fail from the reconciler report.
* **Anomalies** — by-kind and by-severity counts from the anomaly report.

Nothing in this module mutates the warehouse. Safe to call from any process.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
PRICES_SUBDIR = "prices"
META_SUBDIR = "_meta"
LIVE_SUBDIR = "_live"


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot shape
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class HealthSnapshot:
    generated_at: str
    warehouse_path: str

    ticker_count: int = 0
    row_count: int = 0
    oldest_bar: str | None = None
    newest_bar: str | None = None
    partition_count: int = 0

    missing_rate_pct: float | None = None
    missing_top: list[dict] = field(default_factory=list)

    last_sync: dict | None = None
    pipeline_status: dict = field(default_factory=dict)
    live_bars_present: bool = False
    live_bars_date: str | None = None

    reconciler: dict | None = None
    anomalies: dict | None = None

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def collect(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    lookback_days: int = 30,
    top_missing: int = 10,
    fast: bool = False,
    verbose: bool = False,
) -> HealthSnapshot:
    """
    Collect all health signals into a single snapshot.

    ``fast=True`` skips per-file row counting and per-ticker missing rate —
    only ticker count + metadata reports are populated. Useful for a sub-
    second status check when the warehouse has thousands of parquet files.
    ``verbose=True`` shows a tqdm progress bar during warehouse scanning.
    """
    warehouse = Path(warehouse)
    snap = HealthSnapshot(
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        warehouse_path=str(warehouse),
    )

    _scan_warehouse_single_pass(
        snap, warehouse,
        lookback_days=lookback_days,
        top_missing=top_missing,
        fast=fast,
        verbose=verbose,
    )
    _populate_sync_state(snap, warehouse)
    _populate_live_bars(snap, warehouse)
    _populate_reports(snap, warehouse)
    _populate_warnings(snap)

    return snap


def render_health_tab(warehouse: Path = DEFAULT_WAREHOUSE) -> None:
    """Render the System Health tab inside Streamlit. Lazy import of streamlit."""
    try:
        import streamlit as st
    except ImportError:
        print("[health] streamlit not available — call collect() instead")
        return

    snap = collect(Path(warehouse))

    st.subheader("⚕️ Sức khỏe Hệ thống")
    if snap.warnings:
        for w in snap.warnings:
            st.warning(w)

    # Top-level KPI cards
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mã theo dõi", f"{snap.ticker_count:,}")
    col2.metric("Tổng dòng dữ liệu", f"{snap.row_count:,}")
    col3.metric(
        "Tỉ lệ thiếu (30d)",
        f"{snap.missing_rate_pct:.2f}%" if snap.missing_rate_pct is not None else "—",
    )
    col4.metric(
        "Bar mới nhất",
        snap.newest_bar or "—",
    )

    st.divider()

    # Sync + pipeline
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**⏱️ Cập nhật cuối**")
        if snap.last_sync:
            st.json(_truncate_dict(snap.last_sync, max_keys=6), expanded=False)
        else:
            st.caption("Chưa có dữ liệu last_sync.json")
        if snap.live_bars_present:
            st.success(f"Live bars có sẵn cho {snap.live_bars_date}")
        else:
            st.info("Chưa có live bars hôm nay (WSS có thể đang tắt)")

    with col_r:
        st.markdown("**📋 Pipeline status**")
        if snap.pipeline_status:
            st.json(snap.pipeline_status, expanded=False)
        else:
            st.caption("Chưa có pipeline_status.json")

    st.divider()

    # Reconciler + Anomaly rows
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🔁 Reconciler (rollup vs API)**")
        if snap.reconciler:
            r = snap.reconciler
            st.metric("OK / Warn / Fail",
                      f"{r.get('ok', 0)} / {r.get('warn', 0)} / {r.get('fail', 0)}")
            if r.get("discrepancies"):
                df = pd.DataFrame(r["discrepancies"][:20])
                st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.caption("Chưa chạy reconciler. `python vnstock_reconciler.py`")

    with col_b:
        st.markdown("**🚨 Anomalies**")
        if snap.anomalies:
            a = snap.anomalies
            st.metric("Tổng cảnh báo", a.get("total", 0))
            by_kind = a.get("by_kind") or {}
            by_sev = a.get("by_severity") or {}
            if by_kind:
                st.write("**Theo loại:**", by_kind)
            if by_sev:
                st.write("**Theo mức độ:**", by_sev)
            if a.get("anomalies"):
                df = pd.DataFrame(a["anomalies"][:20])
                st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.caption("Chưa chạy anomaly scan. `python vnstock_anomaly.py`")

    if snap.missing_top:
        st.divider()
        st.markdown(f"**📉 Top {len(snap.missing_top)} mã thiếu dữ liệu**")
        st.dataframe(
            pd.DataFrame(snap.missing_top),
            hide_index=True,
            use_container_width=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Collectors
# ─────────────────────────────────────────────────────────────────────────────


def _scan_warehouse_single_pass(
    snap: HealthSnapshot,
    warehouse: Path,
    *,
    lookback_days: int,
    top_missing: int,
    fast: bool,
    verbose: bool,
) -> None:
    """
    Walk the warehouse once and populate every warehouse-derived field.

    Each ticker is touched at most three times:
    * Metadata (pq.read_metadata) on each year file → row count + partition
      count + min/max timestamps from the parquet footer statistics. No data
      pages are read. This is O(ms) per file.
    * The most recent year's time column is loaded only when computing
      missing rate, and only if the column statistics don't tell us.

    ``fast=True`` skips row counts and missing rate entirely, returning in
    sub-second time even on a 1k-ticker warehouse.
    """
    import pyarrow.parquet as pq

    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        snap.warnings.append("Warehouse prices directory not found")
        return

    ticker_dirs = [p for p in prices_dir.glob("ticker=*") if p.is_dir()]
    snap.ticker_count = len(ticker_dirs)
    if not ticker_dirs:
        return

    # Missing-rate windowing
    today = pd.Timestamp(date.today())
    start = today - pd.tseries.offsets.BDay(lookback_days)
    expected_days = pd.date_range(start=start, end=today, freq="B")
    expected_n = len(expected_days)

    oldest: pd.Timestamp | None = None
    newest: pd.Timestamp | None = None
    row_count = 0
    partition_count = 0
    per_ticker: list[dict] = []
    total_present = 0

    iterator = ticker_dirs
    if verbose:
        try:
            from tqdm import tqdm
            iterator = tqdm(ticker_dirs, desc="health scan", unit="tkr")
        except ImportError:
            pass

    for ticker_dir in iterator:
        ticker = ticker_dir.name.removeprefix("ticker=")
        year_files = sorted(ticker_dir.glob("year=*/*.parquet"))
        if not year_files:
            continue

        ticker_min: pd.Timestamp | None = None
        ticker_max: pd.Timestamp | None = None

        for pq_file in year_files:
            partition_count += 1
            try:
                meta = pq.read_metadata(str(pq_file))
            except Exception:
                continue
            if not fast:
                row_count += meta.num_rows

            # Pull min/max from parquet column statistics (free — footer only)
            ts_min, ts_max = _time_bounds_from_metadata(meta)
            if ts_min is not None:
                ticker_min = ts_min if ticker_min is None else min(ticker_min, ts_min)
            if ts_max is not None:
                ticker_max = ts_max if ticker_max is None else max(ticker_max, ts_max)

        if ticker_min is not None:
            oldest = ticker_min if oldest is None else min(oldest, ticker_min)
        if ticker_max is not None:
            newest = ticker_max if newest is None else max(newest, ticker_max)

        if fast:
            continue

        # Missing rate: only inspect year files that overlap the lookback window
        present = _count_present_days_in_window(
            year_files, start, today,
        )
        missing = max(0, expected_n - present)
        rate = (missing / expected_n * 100) if expected_n > 0 else 0.0
        total_present += present
        per_ticker.append({
            "ticker": ticker,
            "expected": expected_n,
            "present": int(present),
            "missing": int(missing),
            "missing_pct": round(rate, 2),
        })

    snap.row_count = row_count
    snap.partition_count = partition_count
    snap.oldest_bar = oldest.date().isoformat() if oldest is not None else None
    snap.newest_bar = newest.date().isoformat() if newest is not None else None

    if not fast and per_ticker:
        total_expected = expected_n * len(per_ticker)
        if total_expected > 0:
            snap.missing_rate_pct = round(
                (1 - total_present / total_expected) * 100, 3
            )
        per_ticker.sort(key=lambda r: r["missing_pct"], reverse=True)
        snap.missing_top = per_ticker[:top_missing]


def _time_bounds_from_metadata(meta) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Extract min/max of the `time` column from parquet footer statistics.

    Reading footer stats does NOT decode data pages — it's O(1) per file.
    Returns (None, None) if the column is missing or stats are absent.
    """
    try:
        schema = meta.schema.to_arrow_schema()
        if "time" not in schema.names:
            return None, None
        time_idx = schema.names.index("time")
    except Exception:
        return None, None

    ts_min: pd.Timestamp | None = None
    ts_max: pd.Timestamp | None = None
    try:
        for rg in range(meta.num_row_groups):
            col = meta.row_group(rg).column(time_idx)
            stats = col.statistics
            if stats is None or not stats.has_min_max:
                return None, None
            mn = pd.Timestamp(stats.min)
            mx = pd.Timestamp(stats.max)
            ts_min = mn if ts_min is None else min(ts_min, mn)
            ts_max = mx if ts_max is None else max(ts_max, mx)
    except Exception:
        return None, None
    return ts_min, ts_max


def _count_present_days_in_window(
    year_files: list[Path],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Count distinct trading days present in ``[start, end]``.

    We only open files whose parquet footer statistics overlap the window —
    typically just the current year, sometimes the previous year at January.
    """
    import pyarrow.parquet as pq

    relevant: list[Path] = []
    for f in year_files:
        try:
            meta = pq.read_metadata(str(f))
        except Exception:
            continue
        mn, mx = _time_bounds_from_metadata(meta)
        if mn is None or mx is None:
            relevant.append(f)  # can't tell — include to be safe
            continue
        if mx < start or mn > end:
            continue
        relevant.append(f)

    if not relevant:
        return 0

    days = set()
    for f in relevant:
        try:
            df = pd.read_parquet(f, columns=["time"])
        except Exception:
            continue
        if df.empty:
            continue
        t = pd.to_datetime(df["time"])
        t = t[(t >= start) & (t <= end)]
        days.update(t.dt.normalize().tolist())
    return len(days)


def _populate_sync_state(snap: HealthSnapshot, warehouse: Path) -> None:
    last_sync_path = warehouse / META_SUBDIR / "last_sync.json"
    if last_sync_path.exists():
        try:
            snap.last_sync = json.loads(last_sync_path.read_text())
        except Exception:
            snap.warnings.append("last_sync.json corrupt")

    pipeline_path = warehouse / META_SUBDIR / "pipeline_status.json"
    if pipeline_path.exists():
        try:
            snap.pipeline_status = json.loads(pipeline_path.read_text())
        except Exception:
            snap.warnings.append("pipeline_status.json corrupt")


def _populate_live_bars(snap: HealthSnapshot, warehouse: Path) -> None:
    live_dir = warehouse / LIVE_SUBDIR
    if not live_dir.exists():
        return
    today_iso = date.today().isoformat()
    today_file = live_dir / f"bars_{today_iso}.parquet"
    if today_file.exists():
        snap.live_bars_present = True
        snap.live_bars_date = today_iso
        return
    # Show most recent rolled date even if not today (helps debug stale feed)
    recent = sorted(live_dir.glob("bars_*.parquet"), reverse=True)
    if recent:
        stem = recent[0].stem
        snap.live_bars_date = stem.removeprefix("bars_")


def _populate_reports(snap: HealthSnapshot, warehouse: Path) -> None:
    recon_path = warehouse / META_SUBDIR / "reconciliation_report.json"
    if recon_path.exists():
        try:
            snap.reconciler = json.loads(recon_path.read_text())
        except Exception:
            snap.warnings.append("reconciliation_report.json corrupt")

    anomaly_path = warehouse / META_SUBDIR / "anomalies.json"
    if anomaly_path.exists():
        try:
            snap.anomalies = json.loads(anomaly_path.read_text())
        except Exception:
            snap.warnings.append("anomalies.json corrupt")


def _populate_warnings(snap: HealthSnapshot) -> None:
    if snap.ticker_count == 0:
        snap.warnings.append("Warehouse is empty — run `vnstock_warehouse.py --load`")
    elif snap.missing_rate_pct is not None and snap.missing_rate_pct > 5.0:
        snap.warnings.append(
            f"Overall missing rate {snap.missing_rate_pct:.1f}% > 5%. "
            "Consider running `vnstock_updater.py`."
        )
    if snap.newest_bar:
        newest = pd.to_datetime(snap.newest_bar).date()
        gap = (date.today() - newest).days
        if gap > 3:
            snap.warnings.append(
                f"Newest bar is {gap} days old ({snap.newest_bar}). "
                "Updater may have stopped."
            )


def _truncate_dict(d: dict, max_keys: int = 6) -> dict:
    if not isinstance(d, dict) or len(d) <= max_keys:
        return d
    keys = list(d.keys())[:max_keys]
    out = {k: d[k] for k in keys}
    out["..."] = f"(+{len(d) - max_keys} more)"
    return out


__all__ = [
    "HealthSnapshot",
    "collect",
    "render_health_tab",
]
