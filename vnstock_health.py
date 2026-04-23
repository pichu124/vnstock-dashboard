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

    ticker_count: int = 0           # all folders in warehouse (incl. non-stocks)
    stock_count: int = 0            # real equities only
    non_stock_count: int = 0        # CW / bonds / futures / HNX internal codes
    active_count: int = 0           # stocks with ≥1 bar in the lookback window
    inactive_count: int = 0         # stocks with 0 bars in lookback → zombie
    row_count: int = 0
    oldest_bar: str | None = None
    newest_bar: str | None = None
    partition_count: int = 0

    missing_rate_pct: float | None = None      # across ALL stocks
    missing_rate_active_pct: float | None = None  # across active only — more meaningful
    missing_top: list[dict] = field(default_factory=list)

    last_sync: dict | None = None
    pipeline_status: dict = field(default_factory=dict)
    live_bars_present: bool = False
    live_bars_date: str | None = None

    reconciler: dict | None = None
    anomalies: dict | None = None
    quarantine: dict | None = None
    wss_coverage: dict | None = None   # partial-miss stats from reconciler

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
    col1.metric(
        "Mã cổ phiếu",
        f"{snap.stock_count:,}",
        delta=(f"{snap.active_count:,} active · {snap.inactive_count:,} zombie"
               if snap.active_count or snap.inactive_count
               else (f"+{snap.non_stock_count:,} CW/derivatives"
                     if snap.non_stock_count else None)),
        delta_color="off",
    )
    col2.metric("Tổng dòng dữ liệu", f"{snap.row_count:,}")
    # Prefer the active-universe figure; fall back to the overall one.
    active_rate = snap.missing_rate_active_pct
    col3.metric(
        "Tỉ lệ thiếu (30d, active)",
        f"{active_rate:.2f}%" if active_rate is not None else "—",
        delta=(f"{snap.missing_rate_pct:.1f}% bao gồm zombie"
               if snap.missing_rate_pct is not None
               and snap.missing_rate_active_pct is not None
               and abs(snap.missing_rate_pct - snap.missing_rate_active_pct) > 1
               else None),
        delta_color="off",
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

    if snap.quarantine and snap.quarantine.get("total", 0) > 0:
        st.divider()
        q = snap.quarantine
        st.markdown("**🛂 Quarantine** (dữ liệu bẩn chờ xử lý)")
        cq1, cq2, cq3 = st.columns(3)
        cq1.metric("Tổng", q.get("total", 0))
        cq2.metric("Chờ retry", q.get("pending", 0))
        cq3.metric(
            "Đã hit max retry",
            q.get("max_retries_hit", 0),
            delta=None if q.get("max_retries_hit", 0) == 0 else "cần review",
            delta_color="inverse",
        )
        if q.get("by_reason"):
            st.write("**Theo lý do:**", q["by_reason"])
        st.caption(
            "Xử lý: `python vnstock_remediate.py --ticker X --date Y "
            "--action refetch|accept|archive`"
        )

    # Top-offenders: show only if the anomaly report is present
    if snap.anomalies and snap.anomalies.get("anomalies"):
        try:
            from vnstock_top_offenders import (
                analyze, concentration, bulk_suggestions,
            )
            stats = analyze(warehouse=Path(warehouse))
            if stats:
                st.divider()
                st.markdown("**🎯 Top offenders (mã bị flag nhiều nhất)**")
                conc = concentration(stats, top_n=10)
                st.caption(
                    f"Pattern: **{conc['pattern'].upper()}** — "
                    f"top 10 mã hold {conc['top_n_share']:.1%} "
                    f"của {conc['total_anomalies']:,} anomaly."
                )
                df_top = pd.DataFrame([s.to_dict() for s in stats[:15]])
                if not df_top.empty:
                    # Collapse by_kind dict to a readable string
                    df_top["by_kind"] = df_top["by_kind"].apply(
                        lambda d: ", ".join(
                            f"{k}:{v}" for k, v in sorted(
                                d.items(), key=lambda kv: -kv[1]
                            )
                        ) if isinstance(d, dict) else str(d)
                    )
                    st.dataframe(
                        df_top[["ticker", "total", "fail", "warn",
                                "by_kind", "latest_date", "suggested_action"]],
                        hide_index=True,
                        use_container_width=True,
                    )
                suggestions = bulk_suggestions(stats, limit=5)
                if suggestions:
                    st.caption("Lệnh đề xuất:")
                    for s in suggestions:
                        st.code(s["cli"], language="bash")
        except Exception:
            pass

    if snap.missing_top:
        st.divider()
        st.markdown(f"**📉 Top {len(snap.missing_top)} mã thiếu dữ liệu**")
        st.dataframe(
            pd.DataFrame(snap.missing_top),
            hide_index=True,
            use_container_width=True,
        )

    # ── 🛠 Hành động nhanh — Phase 5C click-to-fix UI ────────────────────────
    st.divider()
    st.markdown("### 🛠 Hành động nhanh")
    st.caption(
        "Thao tác trực tiếp trên anomaly / quarantine không cần mở PowerShell. "
        "Xem `_meta/remediation_log.jsonl` để audit trail."
    )

    _render_remediate_panels(snap, Path(warehouse))


def _render_remediate_panels(snap: HealthSnapshot, warehouse: Path) -> None:
    """Render the bulk + single-row remediation UI. Split out of render_health_tab
    to keep the main function readable."""
    try:
        import streamlit as st
    except ImportError:
        return

    has_anomalies = bool(snap.anomalies and snap.anomalies.get("anomalies"))
    has_quarantine = bool(snap.quarantine and snap.quarantine.get("total", 0) > 0)

    tab_bulk, tab_single, tab_re_audit = st.tabs(
        ["🎯 Bulk (theo kind)", "🔧 Một bar cụ thể", "🔄 Chạy audit lại"]
    )

    # ── Tab: Bulk ───────────────────────────────────────────────────────────
    with tab_bulk:
        if not has_anomalies:
            st.info("Chưa có anomaly — chạy `audit` trước.")
        else:
            with st.form("bulk_remediate_form"):
                st.write("Apply 1 action cho **tất cả** anomaly match filter.")
                c1, c2, c3 = st.columns(3)
                kind = c1.selectbox(
                    "Kind",
                    ["(tất cả)", "band", "ohlc", "vol_spike", "gap", "zero_vol_move"],
                    key="bulk_kind",
                )
                severity = c2.selectbox(
                    "Severity", ["(tất cả)", "fail", "warn"], key="bulk_sev"
                )
                action = c3.selectbox(
                    "Action", ["accept", "refetch", "archive", "note"],
                    key="bulk_action",
                )
                dry_run = st.checkbox("Dry-run (không làm gì, chỉ đếm)",
                                       value=True, key="bulk_dry")
                limit = st.number_input(
                    "Limit (0 = không giới hạn)", min_value=0, value=0,
                    key="bulk_limit",
                )
                submitted = st.form_submit_button(
                    f"▶ Execute {action} {'(dry-run)' if dry_run else ''}"
                )
            if submitted:
                from vnstock_remediate import apply_bulk
                with st.spinner(f"Applying {action}..."):
                    try:
                        result = apply_bulk(
                            action,
                            warehouse=warehouse,
                            kind=kind if kind != "(tất cả)" else None,
                            severity=severity if severity != "(tất cả)" else None,
                            limit=int(limit) or 0,
                            dry_run=dry_run,
                        )
                    except Exception as e:
                        st.error(f"Error: {e}")
                        return
                st.success(
                    f"✓ total={result.get('total')} "
                    f"ok={result.get('ok')} fail={result.get('fail')} "
                    f"error={result.get('error')}"
                )
                if not dry_run:
                    st.info("Chạy `Chạy audit lại` tab để refresh dashboard.")

    # ── Tab: Single bar ─────────────────────────────────────────────────────
    with tab_single:
        with st.form("single_remediate_form"):
            st.write("Action trên 1 (ticker, date) cụ thể.")
            c1, c2 = st.columns(2)
            ticker_default = ""
            date_default = ""
            if has_anomalies:
                first = snap.anomalies["anomalies"][0]
                ticker_default = first.get("ticker", "")
                date_default = first.get("trading_date", "")
            ticker = c1.text_input("Ticker", value=ticker_default,
                                    key="single_ticker")
            bar_date = c2.text_input(
                "Date (YYYY-MM-DD)", value=date_default,
                key="single_date",
            )
            action = st.selectbox(
                "Action", ["refetch", "accept", "archive", "note"],
                key="single_action",
            )
            kind_hint = st.selectbox(
                "Kind (optional — cho `accept` với whitelist)",
                ["*", "band", "ohlc", "vol_spike", "gap", "zero_vol_move"],
                key="single_kind",
            )
            note = st.text_input("Note (optional)", value="", key="single_note")
            submitted = st.form_submit_button(f"▶ Execute {action}")
        if submitted:
            if not ticker or not bar_date:
                st.error("Cần cả ticker và date.")
                return
            from vnstock_remediate import (
                accept, archive, attach_note, refetch,
            )
            try:
                if action == "refetch":
                    res = refetch(ticker, bar_date, warehouse=warehouse)
                elif action == "accept":
                    res = accept(ticker, bar_date, warehouse=warehouse,
                                 kind=kind_hint, note=note or None)
                elif action == "archive":
                    res = archive(ticker, bar_date, warehouse=warehouse)
                else:  # note
                    if not note:
                        st.error("Action `note` cần --note text.")
                        return
                    res = attach_note(ticker, bar_date, note, warehouse=warehouse)
            except Exception as e:
                st.error(f"Error: {e}")
                return
            if res.get("status") == "ok":
                st.success(f"✓ {action} {ticker} {bar_date}: {res}")
            else:
                st.warning(f"⚠ {res}")

    # ── Tab: Re-audit ───────────────────────────────────────────────────────
    with tab_re_audit:
        st.write(
            "Sau khi remediate, chạy audit lại để refresh "
            "`_meta/anomalies.json` và `_meta/reconciliation_report.json`."
        )
        lookback = st.number_input(
            "Lookback (ngày)", min_value=1, value=60, key="reaudit_lookback",
        )
        include_ns = st.checkbox(
            "Bao gồm non-stocks", value=False, key="reaudit_ns",
        )
        if st.button("🔄 Chạy audit ngay", key="reaudit_btn"):
            import subprocess, sys as _sys
            cmd = [
                _sys.executable, "run.py",
                "--warehouse", str(warehouse),
                "audit", "--lookback", str(int(lookback)),
            ]
            if include_ns:
                cmd.append("--include-non-stocks")
            with st.spinner("Audit đang chạy..."):
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True,
                                           timeout=600)
                except Exception as e:
                    st.error(f"Không chạy được: {e}")
                    return
            if proc.returncode == 0:
                st.success("✓ Audit xong. Reload dashboard để xem số mới.")
            else:
                st.warning(f"Audit trả exit code {proc.returncode}")
            if proc.stdout:
                st.code(proc.stdout[-2000:], language="text")
            if proc.stderr:
                with st.expander("stderr"):
                    st.code(proc.stderr[-2000:], language="text")


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

    # Separate real equities from CW / bonds / futures / HNX internal
    # derivatives. Health metrics (missing rate, date range) are computed
    # only on real stocks, otherwise zombie derivative codes push the
    # missing-rate figure to absurd levels and mask the real picture.
    try:
        from vnstock_anomaly import _is_stock
    except Exception:
        _is_stock = lambda s: True  # fallback — don't filter

    all_ticker_dirs = [p for p in prices_dir.glob("ticker=*") if p.is_dir()]
    stock_dirs = [p for p in all_ticker_dirs
                  if _is_stock(p.name.removeprefix("ticker="))]
    non_stock_count = len(all_ticker_dirs) - len(stock_dirs)

    snap.ticker_count = len(all_ticker_dirs)
    snap.stock_count = len(stock_dirs)
    snap.non_stock_count = non_stock_count
    ticker_dirs = stock_dirs  # only scan stocks from here on
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
            "active": present > 0,
        })

    snap.row_count = row_count
    snap.partition_count = partition_count
    snap.oldest_bar = oldest.date().isoformat() if oldest is not None else None
    snap.newest_bar = newest.date().isoformat() if newest is not None else None

    if not fast and per_ticker:
        # Active = has at least one bar in the lookback window.
        # Zombies (delisted / long-halted) inflate the raw missing_rate so
        # we report BOTH numbers: one across all stocks (raw) and one
        # restricted to active tickers (the meaningful signal).
        active_rows = [r for r in per_ticker if r["active"]]
        snap.active_count = len(active_rows)
        snap.inactive_count = len(per_ticker) - len(active_rows)

        total_expected = expected_n * len(per_ticker)
        if total_expected > 0:
            snap.missing_rate_pct = round(
                (1 - total_present / total_expected) * 100, 3
            )
        if active_rows:
            active_present = sum(r["present"] for r in active_rows)
            active_expected = expected_n * len(active_rows)
            snap.missing_rate_active_pct = round(
                (1 - active_present / active_expected) * 100, 3
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
            snap.wss_coverage = _summarise_wss_coverage(snap.reconciler)
        except Exception:
            snap.warnings.append("reconciliation_report.json corrupt")

    anomaly_path = warehouse / META_SUBDIR / "anomalies.json"
    if anomaly_path.exists():
        try:
            snap.anomalies = json.loads(anomaly_path.read_text())
        except Exception:
            snap.warnings.append("anomalies.json corrupt")

    # Quarantine summary (lightweight — doesn't load every file)
    try:
        from vnstock_quarantine import summary as q_summary
        snap.quarantine = q_summary(warehouse)
    except Exception:
        snap.quarantine = None


_WSS_CAPTURED_PCT_RE = __import__("re").compile(
    r"wss_partial_miss\s*\(([-\d.]+)%"
)


def _summarise_wss_coverage(recon_dict: dict) -> dict:
    """Extract WSS partial-miss stats from a reconciliation_report dict.

    The reason string has the form ``wss_partial_miss (X% vol captured)`` —
    we parse X so the Health tab can show an average capture rate.
    """
    discs = recon_dict.get("discrepancies", [])
    pct_values: list[float] = []
    tickers: list[str] = []
    by_date: dict[str, int] = {}
    for d in discs:
        reason = d.get("reason", "")
        if "wss_partial_miss" not in reason:
            continue
        tickers.append(d.get("ticker", "?"))
        date_str = str(d.get("trading_date", ""))
        by_date[date_str] = by_date.get(date_str, 0) + 1
        m = _WSS_CAPTURED_PCT_RE.search(reason)
        if m:
            try:
                pct_values.append(float(m.group(1)))
            except ValueError:
                pass

    if not tickers:
        return {
            "partial_miss_count": 0,
            "partial_miss_tickers": [],
            "avg_captured_pct": None,
            "by_date": {},
        }

    avg = round(sum(pct_values) / len(pct_values), 1) if pct_values else None
    return {
        "partial_miss_count": len(tickers),
        "partial_miss_tickers": sorted(set(tickers))[:10],
        "avg_captured_pct": avg,
        "by_date": by_date,
    }


def _populate_warnings(snap: HealthSnapshot) -> None:
    if snap.ticker_count == 0:
        snap.warnings.append("Warehouse is empty — run `vnstock_warehouse.py --load`")
    else:
        # Alert on the active figure — the raw figure is dominated by zombies
        rate = snap.missing_rate_active_pct
        if rate is None:
            rate = snap.missing_rate_pct
        if rate is not None and rate > 5.0:
            snap.warnings.append(
                f"Active-ticker missing rate {rate:.1f}% > 5%. "
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

    if snap.quarantine:
        pending = snap.quarantine.get("pending", 0)
        max_hit = snap.quarantine.get("max_retries_hit", 0)
        if max_hit > 0:
            snap.warnings.append(
                f"{max_hit} quarantine entry(ies) hit max retries — "
                "run `python run.py remediate` to review."
            )
        elif pending > 20:
            snap.warnings.append(
                f"{pending} quarantine entries pending. "
                "Try `python vnstock_remediate.py --all --action refetch`."
            )

    if snap.wss_coverage and snap.wss_coverage.get("partial_miss_count", 0) >= 10:
        cov = snap.wss_coverage
        avg = cov.get("avg_captured_pct")
        avg_str = f", avg capture {avg:.0f}%" if avg is not None else ""
        snap.warnings.append(
            f"WSS partial-miss on {cov['partial_miss_count']} ticker-day(s)"
            f"{avg_str}. The audit pipeline auto-backfills from API, but "
            "check `vnstock_wss.py` if this persists session after session."
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
