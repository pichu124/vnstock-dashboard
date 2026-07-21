"""
Per-row diagnostic: investigate why a (ticker, date) was flagged.

When the reconciler reports a fail or the anomaly scanner flags an OHLC
breach, the operator's first question is "what actually happened on that
day?". This module aggregates everything we know about a single
(ticker, date) into one report:

* Warehouse OHLCV around the date (5 days before/after)
* Day-over-day % change pattern → signals corp action
* Cached corp-action events (vnstock_data.capital_history → bonus/split)
* Reconciler discrepancy detail (api_close vs rolled_close, volumes)
* Anomaly entries (kind, severity, detail)
* Quarantine entries (if any)
* Final verdict heuristic with confidence:
    - "likely corp action (cash dividend)" — large sudden price drop, no event registered
    - "likely corp action (split/bonus)" — registered in capital_history
    - "likely WSS miss" — rolled volume = 0
    - "likely data bug" — no obvious cause
    - "real market event" — both sources agree, just a big move

CLI
---
    python vnstock_diagnose.py --ticker CDC --date 2026-04-15
    python vnstock_diagnose.py --ticker SBT --date 2026-04-15 --out diag.json

Returns a verdict that helps decide: refetch, accept, register corp action,
or investigate further.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"
PRICES_SUBDIR = "prices"

# Heuristic thresholds
SUSPECTED_CORP_ACTION_DROP_PCT = 5.0   # day-over-day API close drop > 5%
LARGE_DROP_PCT = 15.0                   # > 15% → almost certainly corp action


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DiagnoseResult:
    ticker: str
    target_date: str

    warehouse_window: list[dict] = field(default_factory=list)
    day_over_day_change_pct: float | None = None
    prev_close: float | None = None
    next_close: float | None = None

    capital_events: list[dict] = field(default_factory=list)
    reconciler_entry: dict | None = None
    anomaly_entries: list[dict] = field(default_factory=list)
    quarantine_entry: dict | None = None

    verdict: str = "unknown"
    confidence: float = 0.0
    rationale: list[str] = field(default_factory=list)
    suggested_action: str = "review"

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────


def _load_warehouse_window(
    warehouse: Path, ticker: str, target: date, *, pad_days: int = 5,
) -> pd.DataFrame:
    """Read OHLCV from warehouse within ±pad_days of target."""
    ticker_dir = warehouse / PRICES_SUBDIR / f"ticker={ticker.upper()}"
    if not ticker_dir.exists():
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for pq_file in ticker_dir.glob("year=*/*.parquet"):
        try:
            frames.append(pd.read_parquet(pq_file))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"]).dt.date
    start = target - pd.Timedelta(days=pad_days).to_pytimedelta()
    end = target + pd.Timedelta(days=pad_days).to_pytimedelta()
    df = df[(df["time"] >= start) & (df["time"] <= end)]
    return df.sort_values("time").reset_index(drop=True)


def _load_capital_events(warehouse: Path, ticker: str, target: date) -> list[dict]:
    """Read corp-action events for ticker, filtered to ±30 days of target.

    Checks the corp_actions_registry first (all sources including manual),
    then falls back to the old capital_history cache for backwards compat.
    """
    window_start = target - pd.Timedelta(days=30).to_pytimedelta()
    window_end = target + pd.Timedelta(days=30).to_pytimedelta()

    # Primary: corp_actions_registry (includes manual, vietstock, cafef, etc.)
    try:
        from vnstock_corp_registry import get_events_for_ticker
        df_reg = get_events_for_ticker(ticker, warehouse=warehouse)
        if not df_reg.empty and "ex_date" in df_reg.columns:
            df_reg["ex_date"] = pd.to_datetime(df_reg["ex_date"]).dt.date
            df_reg = df_reg[
                (df_reg["ex_date"] >= window_start)
                & (df_reg["ex_date"] <= window_end)
            ]
            if not df_reg.empty:
                return df_reg.to_dict(orient="records")
    except Exception:
        pass

    # Fallback: old capital_history cache (_meta/corp_actions/{ticker}.parquet)
    path = warehouse / META_SUBDIR / "corp_actions" / f"{ticker.upper()}.parquet"
    if not path.exists():
        return []
    try:
        df = pd.read_parquet(path)
    except Exception:
        return []
    if df.empty or "ex_date" not in df.columns:
        return []
    df["ex_date"] = pd.to_datetime(df["ex_date"]).dt.date
    df = df[(df["ex_date"] >= window_start) & (df["ex_date"] <= window_end)]
    return df.to_dict(orient="records")


def _load_reconciler_entry(
    warehouse: Path, ticker: str, target: date,
) -> dict | None:
    path = warehouse / META_SUBDIR / "reconciliation_report.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    target_str = target.isoformat()
    for d in data.get("discrepancies", []):
        if (str(d.get("ticker", "")).upper() == ticker.upper()
                and str(d.get("trading_date", "")).startswith(target_str)):
            return d
    return None


def _load_anomaly_entries(
    warehouse: Path, ticker: str, target: date,
) -> list[dict]:
    path = warehouse / META_SUBDIR / "anomalies.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    target_str = target.isoformat()
    return [
        a for a in data.get("anomalies", [])
        if (str(a.get("ticker", "")).upper() == ticker.upper()
            and str(a.get("trading_date", "")).startswith(target_str))
    ]


def _load_quarantine_entry(
    warehouse: Path, ticker: str, target: date,
) -> dict | None:
    path = (warehouse / META_SUBDIR / "quarantine"
            / ticker.upper() / f"{target.isoformat()}.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Verdict heuristic
# ─────────────────────────────────────────────────────────────────────────────


def _decide_verdict(result: DiagnoseResult) -> None:
    """Populate result.verdict + confidence + rationale + suggested_action."""

    chg = result.day_over_day_change_pct
    has_capital_event = bool(result.capital_events)
    recon = result.reconciler_entry or {}
    rolled_vol = recon.get("rolled_volume")
    api_vol = recon.get("api_volume")

    rationale: list[str] = []

    # 1) Registered corp action — split / bonus / rights → high confidence
    if has_capital_event:
        types = sorted({str(e.get("type", "?")) for e in result.capital_events})
        result.verdict = "registered corp action"
        result.confidence = 0.95
        result.suggested_action = "accept"
        rationale.append(
            f"capital_history has event(s) on / around target: {types}"
        )
        result.rationale = rationale
        return

    # 2) WSS miss — rolled didn't capture the session
    if recon and rolled_vol == 0 and api_vol and api_vol > 0:
        result.verdict = "WSS missed session"
        result.confidence = 0.9
        result.suggested_action = "accept (WSS infra)"
        rationale.append(
            f"reconciler shows rolled_volume=0 vs api_volume={api_vol:,}"
        )
        result.rationale = rationale
        return

    # 3) Suspected unregistered corp action — large API price drop with no
    #    rolled equivalent. Likely cash dividend not in our event registry.
    if chg is not None and chg <= -LARGE_DROP_PCT:
        result.verdict = "likely cash dividend (unregistered)"
        result.confidence = 0.75
        result.suggested_action = "register manually + accept"
        rationale.append(
            f"API close dropped {chg:.2f}% day-over-day with no capital_history event"
        )
        if recon:
            rolled_close = recon.get("rolled_close")
            api_close = recon.get("api_close")
            if rolled_close and api_close:
                implied = rolled_close - api_close
                rationale.append(
                    f"implied dividend per share ≈ {implied:.3f} (thousand VND)"
                )
        result.rationale = rationale
        return

    # 4) Moderate drop — could be cash div or real move
    if chg is not None and chg <= -SUSPECTED_CORP_ACTION_DROP_PCT:
        result.verdict = "moderate drop — possible cash dividend or real event"
        result.confidence = 0.55
        result.suggested_action = "investigate (check news / dividend records)"
        rationale.append(
            f"API close dropped {chg:.2f}% — within plausible cash-dividend range"
        )
        result.rationale = rationale
        return

    # 5) WSS partial-miss — rolled has volume but much lower than api
    if (recon and rolled_vol and api_vol and api_vol > 0
            and rolled_vol < api_vol * 0.5):
        ratio = rolled_vol / api_vol
        result.verdict = "WSS partial miss (volume incomplete)"
        result.confidence = 0.7
        result.suggested_action = "accept (WSS infra)"
        rationale.append(
            f"rolled captured only {ratio:.1%} of API volume "
            f"({rolled_vol:,} / {api_vol:,})"
        )
        result.rationale = rationale
        return

    # 6) Anomaly without reconciler entry — pure warehouse data issue
    if result.anomaly_entries and not recon:
        kinds = sorted({a.get("kind", "?") for a in result.anomaly_entries})
        result.verdict = f"warehouse-only anomaly ({', '.join(kinds)})"
        result.confidence = 0.6
        result.suggested_action = "review anomaly detail; refetch if data bug"
        rationale.append(
            f"flagged by anomaly scanner ({len(result.anomaly_entries)} entries) "
            f"but reconciler agreement is fine"
        )
        result.rationale = rationale
        return

    # 7) Default
    result.verdict = "no clear cause"
    result.confidence = 0.3
    result.suggested_action = "review manually"
    if not result.warehouse_window:
        rationale.append("no warehouse data for this (ticker, date)")
    elif chg is None:
        rationale.append("no prior bar to compute day-over-day change")
    else:
        rationale.append(
            f"day-over-day change is {chg:+.2f}% (not a corp-action signal)"
        )
    result.rationale = rationale


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def diagnose(
    ticker: str,
    target_date: date | str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    pad_days: int = 5,
) -> DiagnoseResult:
    """Build a full diagnostic for one (ticker, date)."""
    target = (
        target_date if isinstance(target_date, date)
        else pd.to_datetime(target_date).date()
    )
    warehouse = Path(warehouse)
    result = DiagnoseResult(
        ticker=ticker.upper(), target_date=target.isoformat(),
    )

    df = _load_warehouse_window(warehouse, ticker, target, pad_days=pad_days)
    if not df.empty:
        result.warehouse_window = df.to_dict(orient="records")
        target_idx = df.index[df["time"] == target].tolist()
        if target_idx:
            i = target_idx[0]
            target_close = float(df.iloc[i]["close"])
            if i > 0:
                prev = float(df.iloc[i - 1]["close"])
                result.prev_close = prev
                if prev > 0:
                    result.day_over_day_change_pct = round(
                        (target_close / prev - 1) * 100, 3
                    )
            if i < len(df) - 1:
                result.next_close = float(df.iloc[i + 1]["close"])

    result.capital_events = _load_capital_events(warehouse, ticker, target)
    result.reconciler_entry = _load_reconciler_entry(warehouse, ticker, target)
    result.anomaly_entries = _load_anomaly_entries(warehouse, ticker, target)
    result.quarantine_entry = _load_quarantine_entry(warehouse, ticker, target)

    _decide_verdict(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pretty printer
# ─────────────────────────────────────────────────────────────────────────────


def render(result: DiagnoseResult) -> str:
    lines: list[str] = []
    lines.append(f"\n=== Diagnose {result.ticker} {result.target_date} ===\n")

    # Verdict
    lines.append(f"VERDICT: {result.verdict}")
    lines.append(f"Confidence: {result.confidence:.2f}")
    lines.append(f"Suggested action: {result.suggested_action}")
    lines.append("Rationale:")
    for r in result.rationale:
        lines.append(f"  • {r}")

    # Warehouse window
    lines.append("\nWarehouse window (±5 days):")
    if not result.warehouse_window:
        lines.append("  (no warehouse data)")
    else:
        df = pd.DataFrame(result.warehouse_window)
        cols = [c for c in ("time", "open", "high", "low", "close", "volume")
                if c in df.columns]
        lines.append(df[cols].to_string(index=False))
        if result.day_over_day_change_pct is not None:
            lines.append(
                f"\n  prev_close → close: "
                f"{result.prev_close} → "
                f"{df[df['time'] == pd.to_datetime(result.target_date).date()]['close'].iloc[0] if len(df[df['time'] == pd.to_datetime(result.target_date).date()]) else 'n/a'} "
                f"({result.day_over_day_change_pct:+.2f}%)"
            )

    # Reconciler
    lines.append("\nReconciler entry:")
    if result.reconciler_entry:
        for k, v in result.reconciler_entry.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  (no reconciler discrepancy for this row)")

    # Anomaly
    lines.append("\nAnomaly entries:")
    if result.anomaly_entries:
        for a in result.anomaly_entries:
            lines.append(
                f"  [{a.get('severity', '?'):4}] {a.get('kind', '?')}: "
                f"{a.get('detail', '')}"
            )
    else:
        lines.append("  (none)")

    # Capital events
    lines.append("\nRegistered capital events (±30d):")
    if result.capital_events:
        for e in result.capital_events:
            lines.append(
                f"  {e.get('ex_date', '?')} {e.get('type', '?')} "
                f"ratio={e.get('ratio', '-')} cash={e.get('cash_amount', '-')}"
            )
    else:
        lines.append("  (none)")

    # Quarantine
    if result.quarantine_entry:
        lines.append("\nQuarantine entry:")
        for k, v in result.quarantine_entry.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# GTGD baseline audit (review 21/07 — "+28% vs TB20" lúc 01:22 nhưng "+0%"
# lúc 16:18: map gtgd_by_date cộng dồn 22 bar cuối CỦA TỪNG MÃ nên tổng
# per-date phụ thuộc trạng thái sync kho lúc chạy screener)
# ─────────────────────────────────────────────────────────────────────────────


def audit_gtgd(warehouse: Path | str = DEFAULT_WAREHOUSE) -> int:
    """In bảng gtgd_by_date (total/count per ngày) + baseline TB5/TB20 TRƯỚC
    và SAU gate coverage của `vnstock_brief._gtgd_baselines` — chạy trên máy
    thật để thấy ngay ngày nào under-covered kéo lệch baseline.
    Exit 0 = có data; 1 = thiếu map."""
    ov = Path(warehouse) / "_meta" / "market_overview.json"
    if not ov.exists():
        print(f"❌ Không thấy {ov} — chạy `python run.py screener` trước.")
        return 1
    data = json.loads(ov.read_text(encoding="utf-8"))
    byd = data.get("gtgd_by_date") or {}
    if not byd:
        print("❌ market_overview.json không có gtgd_by_date (runner cũ?).")
        return 1

    import statistics as _st
    from vnstock_brief import _gtgd_baselines, _GTGD_COVERAGE_MIN_RATIO

    dates = sorted(byd, reverse=True)
    counts = [int((byd[d] or {}).get("count") or 0) for d in dates]
    med = _st.median([c for c in counts if c > 0]) if any(counts) else 0
    floor = _GTGD_COVERAGE_MIN_RATIO * med
    print(f"📊 gtgd_by_date — {len(dates)} phiên · gtgd_date="
          f"{data.get('gtgd_date')} · generated_at={data.get('generated_at')}")
    print(f"   median(count)={med:.0f} → gate ≥ {floor:.0f} "
          f"(ratio {_GTGD_COVERAGE_MIN_RATIO})")
    for d in dates:
        e = byd[d] or {}
        t = float(e.get("total") or 0)
        c = int(e.get("count") or 0)
        mark = "  " if (not med or c >= floor) else "⚠️ "
        print(f"   {mark}{d}  total={t:>12,.1f} tỷ  count={c}")

    latest = dates[0]
    ungated = [float((byd[d] or {}).get("total") or 0)
               for d in dates if d < latest and (byd[d] or {}).get("total")]
    if ungated:
        a5 = sum(ungated[:5]) / len(ungated[:5])
        line = f"   TRƯỚC gate: prev={ungated[0]:,.1f} · avg5={a5:,.1f}"
        if len(ungated) >= 15:
            line += f" · avg20={sum(ungated[:20]) / len(ungated[:20]):,.1f}"
        print(line)
    cmp = _gtgd_baselines(byd, latest)
    if cmp:
        line = f"   SAU gate : prev={cmp['prev']:,.1f} · avg5={cmp['avg5']:,.1f}"
        if "avg20" in cmp:
            line += f" · avg20={cmp['avg20']:,.1f}"
        print(line)
        f_latest = float((byd[latest] or {}).get("total") or 0)
        if f_latest > 0 and cmp.get("avg20"):
            print(f"   → GTGD {latest} = {f_latest:,.1f} tỷ: "
                  f"{(f_latest / cmp['avg20'] - 1) * 100:+.0f}% vs TB20 (gated)")
    else:
        print("   ⚠️ Không còn phiên nào qua gate — soi coverage kho.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Chẩn đoán data warehouse")
    ap.add_argument("--gtgd", action="store_true",
                    help="audit map gtgd_by_date + baseline TB5/TB20 "
                         "(trước/sau gate coverage)")
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    args = ap.parse_args(argv)
    if args.gtgd:
        return audit_gtgd(args.warehouse)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
