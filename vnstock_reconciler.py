"""
Cross-reference reconciler: rolled-up intraday bars vs daily API warehouse.

Goal
----
Detect drift between the two independent sources of daily OHLCV:

1. **API-sourced daily** — written by `vnstock_updater.py`. Authoritative.
2. **Rolled-up daily** — produced by `vnstock_rollup.py` aggregating 1-minute
   bars streamed via WSS. Subject to accum→delta conversion, missing ticks,
   market halts.

The reconciler flags tickers whose rolled volume or close deviates from the
API value beyond configured tolerances. Findings are written to
`data_warehouse/_meta/reconciliation_report.json` for the System Health
dashboard to display.

Usage
-----
    # One-day reconcile
    python vnstock_reconciler.py --date 2026-04-17

    # Reconcile the 5 most recent trading days
    python vnstock_reconciler.py --lookback 5

Design decisions
----------------
* We never mutate the warehouse here. Reconciliation is read-only observation.
* Volume tolerance defaults to 5 % because rolled bars legitimately miss
  pre-open and ATC auction prints on some datafeed tiers.
* Close tolerance defaults to 0.5 % (one tick on the cheapest VN stock is
  roughly 0.4 % at 2,500 VND).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq


DEFAULT_WAREHOUSE = Path("data_warehouse")
PRICES_SUBDIR = "prices"
LIVE_SUBDIR = "_live"
META_SUBDIR = "_meta"

VOLUME_TOLERANCE_PCT = 5.0
CLOSE_TOLERANCE_PCT = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Discrepancy:
    ticker: str
    trading_date: str
    api_close: float | None
    rolled_close: float | None
    close_pct_diff: float | None
    api_volume: int | None
    rolled_volume: int | None
    volume_pct_diff: float | None
    severity: str  # "ok", "warn", "fail"
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReconciliationReport:
    run_at: str
    dates_checked: list[str]
    tickers_checked: int
    ok: int
    warn: int
    fail: int
    missing_in_api: int
    missing_in_rolled: int
    discrepancies: list[Discrepancy]

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "discrepancies"},
            "discrepancies": [d.to_dict() for d in self.discrepancies],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────


def _load_api_daily(
    warehouse: Path, tickers: list[str] | None, dates: list[date]
) -> pd.DataFrame:
    """Read API-sourced daily OHLCV from the partitioned parquet warehouse."""
    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    year_set = {d.year for d in dates}
    date_set = {pd.Timestamp(d).date() for d in dates}

    if tickers is None:
        ticker_dirs = [p for p in prices_dir.glob("ticker=*") if p.is_dir()]
    else:
        ticker_dirs = [prices_dir / f"ticker={t}" for t in tickers]

    for ticker_dir in ticker_dirs:
        if not ticker_dir.exists():
            continue
        ticker = ticker_dir.name.removeprefix("ticker=")
        for year in year_set:
            year_dir = ticker_dir / f"year={year}"
            if not year_dir.exists():
                continue
            for pq_file in year_dir.glob("*.parquet"):
                try:
                    df = pq.read_table(str(pq_file)).to_pandas()
                except Exception:
                    continue
                if df.empty:
                    continue
                df["time"] = pd.to_datetime(df["time"]).dt.date
                df = df[df["time"].isin(date_set)]
                if df.empty:
                    continue
                df["ticker"] = ticker
                frames.append(df[["ticker", "time", "close", "volume"]])

    if not frames:
        return pd.DataFrame(columns=["ticker", "time", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def _load_rolled_daily(warehouse: Path, dates: list[date]) -> pd.DataFrame:
    """
    Aggregate the live 1-minute bars into daily OHLCV in-memory (no write).

    Re-uses the aggregator from vnstock_rollup so drift in aggregation logic
    can't split the two sources.
    """
    try:
        from vnstock_rollup import _aggregate_bars_to_daily  # type: ignore
    except Exception as e:
        print(f"[reconciler] cannot import vnstock_rollup: {e}", file=sys.stderr)
        return pd.DataFrame()

    live_dir = warehouse / LIVE_SUBDIR
    if not live_dir.exists():
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for d in dates:
        path = live_dir / f"bars_{d.isoformat()}.parquet"
        if not path.exists():
            continue
        try:
            bars = pq.read_table(str(path)).to_pandas()
        except Exception:
            continue
        if bars.empty:
            continue
        try:
            daily = _aggregate_bars_to_daily(bars)
        except Exception as e:
            print(f"[reconciler] aggregate failed for {d}: {e}", file=sys.stderr)
            continue
        if daily.empty:
            continue
        daily = daily.rename(columns={"trading_date": "time"})
        frames.append(daily[["ticker", "time", "close", "volume"]])

    if not frames:
        return pd.DataFrame(columns=["ticker", "time", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def _normalise_units(api_df: pd.DataFrame, rolled_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """
    Bring the two price sources onto a common unit (thousand VND).

    The warehouse (via _fetch_price) stores prices in thousand VND
    (e.g. 77.7 for a 77,700 VND stock), while WSS-rolled bars often
    carry raw VND (77,700). Blindly comparing the two produces drift
    figures like 99,900% which drown out real discrepancies.

    Heuristic: if the rolled median close is >= 500× the API median close
    (or vice versa), divide the larger side by 1000. We log whether a
    rescaling was applied so operators know the reconciler did it.
    """
    rescaled = False
    if api_df is None or rolled_df is None or api_df.empty or rolled_df.empty:
        return api_df, rolled_df, rescaled
    if "close" not in api_df.columns or "close" not in rolled_df.columns:
        return api_df, rolled_df, rescaled

    try:
        med_api = float(pd.to_numeric(api_df["close"], errors="coerce").median())
        med_rolled = float(pd.to_numeric(rolled_df["close"], errors="coerce").median())
    except Exception:
        return api_df, rolled_df, rescaled
    if not (med_api > 0 and med_rolled > 0):
        return api_df, rolled_df, rescaled

    ratio = med_rolled / med_api
    # Rolled is ~1000× the API → rolled is in VND, divide by 1000
    if ratio >= 500 and ratio <= 2000:
        rolled_df = rolled_df.copy()
        rolled_df["close"] = pd.to_numeric(rolled_df["close"], errors="coerce") / 1000.0
        rescaled = True
    # Rare inverse case
    elif ratio <= 1 / 500 and ratio >= 1 / 2000:
        api_df = api_df.copy()
        api_df["close"] = pd.to_numeric(api_df["close"], errors="coerce") / 1000.0
        rescaled = True
    return api_df, rolled_df, rescaled


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation logic
# ─────────────────────────────────────────────────────────────────────────────


def _pct_diff(a: float, b: float) -> float | None:
    if a is None or b is None:
        return None
    if not (pd.notna(a) and pd.notna(b)):
        return None
    if a == 0:
        return None
    return float(abs(b - a) / abs(a) * 100)


def _classify(
    close_diff: float | None,
    volume_diff: float | None,
) -> tuple[str, str]:
    """Map numeric diffs to (severity, reason)."""
    reasons = []
    severity = "ok"
    if close_diff is not None and close_diff > CLOSE_TOLERANCE_PCT:
        reasons.append(f"close drift {close_diff:.2f}%")
        severity = "fail" if close_diff > CLOSE_TOLERANCE_PCT * 4 else "warn"
    if volume_diff is not None and volume_diff > VOLUME_TOLERANCE_PCT:
        reasons.append(f"volume drift {volume_diff:.1f}%")
        if severity != "fail":
            severity = "fail" if volume_diff > VOLUME_TOLERANCE_PCT * 5 else "warn"
    return severity, ", ".join(reasons) or "within tolerance"


def reconcile(
    warehouse: Path = DEFAULT_WAREHOUSE,
    dates: list[date] | None = None,
    lookback: int = 1,
    tickers: list[str] | None = None,
) -> ReconciliationReport:
    """
    Compare API daily vs rolled-up daily for the given dates.

    If ``dates`` is None, the most recent ``lookback`` trading days for which
    a rolled-bars file exists are used.
    """
    warehouse = Path(warehouse)
    live_dir = warehouse / LIVE_SUBDIR

    if dates is None:
        dates = _discover_recent_rolled_dates(live_dir, lookback)

    if not dates:
        return ReconciliationReport(
            run_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            dates_checked=[],
            tickers_checked=0,
            ok=0, warn=0, fail=0,
            missing_in_api=0, missing_in_rolled=0,
            discrepancies=[],
        )

    api_df = _load_api_daily(warehouse, tickers, dates)
    rolled_df = _load_rolled_daily(warehouse, dates)

    # Bring prices onto a common unit before comparing. Without this, the
    # reconciler reports 99900% drift on every row because rolled bars are
    # in VND and API bars are in thousand VND.
    api_df, rolled_df, rescaled = _normalise_units(api_df, rolled_df)
    if rescaled:
        print("[reconciler] normalised price units (rolled /= 1000) "
              "before comparison")

    if api_df.empty and rolled_df.empty:
        return ReconciliationReport(
            run_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            dates_checked=[d.isoformat() for d in dates],
            tickers_checked=0,
            ok=0, warn=0, fail=0,
            missing_in_api=0, missing_in_rolled=0,
            discrepancies=[],
        )

    merged = api_df.merge(
        rolled_df,
        on=["ticker", "time"],
        how="outer",
        suffixes=("_api", "_rolled"),
        indicator=True,
    )

    discrepancies: list[Discrepancy] = []
    ok = warn = fail = 0
    missing_api = missing_rolled = 0

    for _, row in merged.iterrows():
        api_close = row.get("close_api")
        api_vol = row.get("volume_api")
        rolled_close = row.get("close_rolled")
        rolled_vol = row.get("volume_rolled")

        if row["_merge"] == "left_only":
            missing_rolled += 1
            continue  # rolled didn't see this trading day — normal if WSS was off
        if row["_merge"] == "right_only":
            missing_api += 1
            discrepancies.append(Discrepancy(
                ticker=row["ticker"],
                trading_date=str(row["time"]),
                api_close=None,
                rolled_close=_finite(rolled_close),
                close_pct_diff=None,
                api_volume=None,
                rolled_volume=_int_or_none(rolled_vol),
                volume_pct_diff=None,
                severity="warn",
                reason="missing in API warehouse",
            ))
            warn += 1
            continue

        close_diff = _pct_diff(api_close, rolled_close)
        vol_diff = _pct_diff(api_vol, rolled_vol)
        severity, reason = _classify(close_diff, vol_diff)

        if severity == "ok":
            ok += 1
            continue
        if severity == "warn":
            warn += 1
        else:
            fail += 1

        discrepancies.append(Discrepancy(
            ticker=row["ticker"],
            trading_date=str(row["time"]),
            api_close=_finite(api_close),
            rolled_close=_finite(rolled_close),
            close_pct_diff=_round(close_diff, 3),
            api_volume=_int_or_none(api_vol),
            rolled_volume=_int_or_none(rolled_vol),
            volume_pct_diff=_round(vol_diff, 2),
            severity=severity,
            reason=reason,
        ))

    return ReconciliationReport(
        run_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        dates_checked=[d.isoformat() for d in dates],
        tickers_checked=int(merged["ticker"].nunique()),
        ok=ok, warn=warn, fail=fail,
        missing_in_api=missing_api,
        missing_in_rolled=missing_rolled,
        discrepancies=sorted(
            discrepancies,
            key=lambda d: (d.severity == "warn", d.ticker),  # fail first
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# IO helpers
# ─────────────────────────────────────────────────────────────────────────────


def _discover_recent_rolled_dates(live_dir: Path, n: int) -> list[date]:
    if not live_dir.exists():
        return []
    candidates: list[date] = []
    for path in sorted(live_dir.glob("bars_*.parquet"), reverse=True):
        stem = path.stem  # "bars_2026-04-17"
        try:
            d = date.fromisoformat(stem.removeprefix("bars_"))
        except ValueError:
            continue
        candidates.append(d)
        if len(candidates) >= n:
            break
    return sorted(candidates)


def write_report(report: ReconciliationReport, warehouse: Path = DEFAULT_WAREHOUSE) -> Path:
    meta_dir = warehouse / META_SUBDIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    out = meta_dir / "reconciliation_report.json"
    out.write_text(json.dumps(report.to_dict(), indent=2, default=str))
    return out


def _finite(x) -> float | None:
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _int_or_none(x) -> int | None:
    try:
        if x is None or pd.isna(x):
            return None
        return int(x)
    except (TypeError, ValueError):
        return None


def _round(x: float | None, n: int) -> float | None:
    if x is None:
        return None
    return round(x, n)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    ap.add_argument("--date", type=_parse_date, action="append",
                    help="Specific date(s) to reconcile. Repeatable.")
    ap.add_argument("--lookback", type=int, default=1,
                    help="If --date omitted, reconcile this many recent rolled days.")
    ap.add_argument("--ticker", action="append",
                    help="Restrict to specific ticker(s). Default: all.")
    ap.add_argument("--no-write", action="store_true",
                    help="Print summary but don't persist report JSON.")
    args = ap.parse_args()

    report = reconcile(
        warehouse=Path(args.warehouse),
        dates=args.date,
        lookback=args.lookback,
        tickers=args.ticker,
    )

    print(f"[reconciler] {len(report.dates_checked)} date(s), "
          f"{report.tickers_checked} ticker(s): "
          f"ok={report.ok} warn={report.warn} fail={report.fail} "
          f"missing_api={report.missing_in_api} "
          f"missing_rolled={report.missing_in_rolled}")

    for d in report.discrepancies[:20]:
        print(f"  [{d.severity:4}] {d.ticker} {d.trading_date}: {d.reason}")

    if not args.no_write:
        out = write_report(report, Path(args.warehouse))
        print(f"[reconciler] wrote {out}")


if __name__ == "__main__":
    main()
