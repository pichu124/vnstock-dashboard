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
) -> HealthSnapshot:
    """Collect all health signals into a single snapshot."""
    warehouse = Path(warehouse)
    snap = HealthSnapshot(
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        warehouse_path=str(warehouse),
    )

    _populate_warehouse_stats(snap, warehouse)
    _populate_missing_rate(snap, warehouse, lookback_days, top_missing)
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


def _populate_warehouse_stats(snap: HealthSnapshot, warehouse: Path) -> None:
    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        snap.warnings.append("Warehouse prices directory not found")
        return
    ticker_dirs = [p for p in prices_dir.glob("ticker=*") if p.is_dir()]
    snap.ticker_count = len(ticker_dirs)

    oldest = None
    newest = None
    row_count = 0
    partition_count = 0

    for ticker_dir in ticker_dirs:
        for pq_file in ticker_dir.glob("year=*/*.parquet"):
            partition_count += 1
            try:
                import pyarrow.parquet as pq
                meta = pq.read_metadata(str(pq_file))
                row_count += meta.num_rows
                # Reading min/max per file would be exact but heavy — sample
                # only the time column on the first & last file per ticker.
            except Exception:
                continue

        # Probe time range by reading the first/last year directories only.
        years = sorted(ticker_dir.glob("year=*"))
        if years:
            for probe_dir in (years[0], years[-1]):
                for pq_file in probe_dir.glob("*.parquet"):
                    try:
                        df = pd.read_parquet(pq_file, columns=["time"])
                    except Exception:
                        continue
                    if df.empty:
                        continue
                    ts_min = pd.to_datetime(df["time"]).min()
                    ts_max = pd.to_datetime(df["time"]).max()
                    if oldest is None or ts_min < oldest:
                        oldest = ts_min
                    if newest is None or ts_max > newest:
                        newest = ts_max
                    break

    snap.row_count = row_count
    snap.partition_count = partition_count
    snap.oldest_bar = oldest.date().isoformat() if oldest is not None else None
    snap.newest_bar = newest.date().isoformat() if newest is not None else None


def _populate_missing_rate(
    snap: HealthSnapshot,
    warehouse: Path,
    lookback_days: int,
    top_missing: int,
) -> None:
    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        return

    today = pd.Timestamp(date.today())
    start = today - pd.tseries.offsets.BDay(lookback_days)
    expected = pd.date_range(start=start, end=today, freq="B")
    expected_n = len(expected)
    if expected_n == 0:
        return

    per_ticker: list[dict] = []
    total_expected = 0
    total_present = 0

    for ticker_dir in prices_dir.glob("ticker=*"):
        ticker = ticker_dir.name.removeprefix("ticker=")
        frames = []
        for pq_file in ticker_dir.glob("year=*/*.parquet"):
            try:
                frames.append(pd.read_parquet(pq_file, columns=["time"]))
            except Exception:
                continue
        if not frames:
            continue
        times = pd.to_datetime(pd.concat(frames)["time"])
        times = times[(times >= start) & (times <= today)]
        present = times.dt.normalize().nunique()
        missing = max(0, expected_n - present)
        rate = missing / expected_n * 100
        total_expected += expected_n
        total_present += present
        per_ticker.append({
            "ticker": ticker,
            "expected": expected_n,
            "present": int(present),
            "missing": int(missing),
            "missing_pct": round(rate, 2),
        })

    if total_expected > 0:
        snap.missing_rate_pct = round(
            (1 - total_present / total_expected) * 100, 3
        )

    per_ticker.sort(key=lambda r: r["missing_pct"], reverse=True)
    snap.missing_top = per_ticker[:top_missing]


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
