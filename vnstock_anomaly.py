"""
Anomaly Agent — flag "phi logic" data points for manual review.

Scope
-----
The contracts layer (vnstock_contracts) rejects structurally impossible rows
(price<=0, high<low, bad ticker format). This module goes one step further
and flags statistically or regulatorially suspicious rows:

* **Price band breach** — daily % change exceeding the exchange's fluctuation
  limit. HOSE allows ±7% on a regular session (±20% on first-day IPO, ±10%
  after halts); HNX allows ±10%; UPCOM allows ±15%. We tolerate a small
  overshoot (`BAND_TOLERANCE_PCT`) because the vnstock data sometimes rounds.
* **OHLC outside band** — high or low exceeds the band; catches print errors.
* **Calendar gap** — >10 consecutive trading days missing between two bars.
  Often a halt, delisting, or a data hole we should backfill.
* **Volume spike** — volume > mean20 * `VOL_SPIKE_FACTOR` (default 5x) AND
  > mean20 + `VOL_SIGMA_GATE` * std20 (default 4σ). The dual-gate avoids
  false positives on illiquid tickers where std is dominated by zero-volume
  days, and tolerates the fat-tailed nature of VN trading volume.
* **Zero-volume price move** — volume == 0 but |chg| > 0. Usually a bad
  corporate-action ex-date that vnstock didn't clean.

Exchanges are looked up from the classifier's cache
(`_meta/industry_classification.parquet`). If that cache is missing, all
tickers are scanned with the most lenient (UPCOM 15%) band.

Usage
-----
    # Scan the whole warehouse for the last 60 trading days
    python vnstock_anomaly.py --lookback 60

    # One ticker, full history
    python vnstock_anomaly.py --ticker VCB --full

    # As a library
    from vnstock_anomaly import scan_ticker, scan_warehouse
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
PRICES_SUBDIR = "prices"
META_SUBDIR = "_meta"

# Regulatory price bands by exchange (% of previous close)
BAND_PCT = {
    "HOSE": 7.0,
    "HNX": 10.0,
    "UPCOM": 15.0,
    # Unknown → use the loosest band so we don't spam false positives.
    "_UNKNOWN": 15.0,
}
BAND_TOLERANCE_PCT = 0.3          # allow 0.3pp overshoot for rounding
MAX_GAP_DAYS = 10                 # > N trading days missing → flag
VOL_SPIKE_FACTOR = 5.0            # volume > mean20 * 5
VOL_SIGMA_GATE = 4.0              # and volume > mean20 + 4*std20 (fat-tailed)


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Anomaly:
    ticker: str
    trading_date: str
    kind: str                     # "band", "ohlc", "gap", "vol_spike", "zero_vol_move"
    severity: str                 # "warn" | "fail"
    detail: str
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnomalyReport:
    run_at: str
    tickers_scanned: int
    anomalies: list[Anomaly]

    def to_dict(self) -> dict:
        return {
            "run_at": self.run_at,
            "tickers_scanned": self.tickers_scanned,
            "total": len(self.anomalies),
            "by_kind": _count_by(self.anomalies, "kind"),
            "by_severity": _count_by(self.anomalies, "severity"),
            "anomalies": [a.to_dict() for a in self.anomalies],
        }


def _count_by(items: list[Anomaly], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        k = getattr(it, attr)
        out[k] = out.get(k, 0) + 1
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Exchange lookup
# ─────────────────────────────────────────────────────────────────────────────


def _load_exchange_map(warehouse: Path) -> dict[str, str]:
    """Return {ticker: exchange} from the classifier cache. Empty on miss."""
    path = warehouse / META_SUBDIR / "industry_classification.parquet"
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if "ticker" not in df.columns or "exchange" not in df.columns:
        return {}
    mp: dict[str, str] = {}
    for _, row in df[["ticker", "exchange"]].dropna().iterrows():
        ex = str(row["exchange"]).strip().upper()
        if ex in BAND_PCT:
            mp[str(row["ticker"]).upper()] = ex
        elif "HO" in ex or "HSX" in ex:
            mp[str(row["ticker"]).upper()] = "HOSE"
        elif "HN" in ex:
            mp[str(row["ticker"]).upper()] = "HNX"
        elif "UP" in ex:
            mp[str(row["ticker"]).upper()] = "UPCOM"
    return mp


def band_for(ticker: str, exchange_map: dict[str, str]) -> tuple[str, float]:
    ex = exchange_map.get(ticker.upper(), "_UNKNOWN")
    return ex, BAND_PCT[ex]


# ─────────────────────────────────────────────────────────────────────────────
# Core scan — per ticker
# ─────────────────────────────────────────────────────────────────────────────


def scan_ticker(
    df: pd.DataFrame,
    ticker: str,
    *,
    exchange: str = "_UNKNOWN",
    lookback: int | None = None,
) -> list[Anomaly]:
    """
    Run all anomaly checks on a single ticker's daily OHLCV.

    ``df`` must have: time, open, high, low, close, volume. Sorted by time.
    ``lookback`` restricts to the last N rows (after sort).
    """
    if df is None or df.empty:
        return []
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    out: list[Anomaly] = []
    band = BAND_PCT.get(exchange, BAND_PCT["_UNKNOWN"]) + BAND_TOLERANCE_PCT

    # Compute derived columns once
    df["prev_close"] = df["close"].shift(1)
    df["chg_pct"] = (df["close"] - df["prev_close"]) / df["prev_close"] * 100
    df["hi_pct"] = (df["high"] - df["prev_close"]) / df["prev_close"] * 100
    df["lo_pct"] = (df["low"] - df["prev_close"]) / df["prev_close"] * 100
    df["vol_mean20"] = df["volume"].rolling(20, min_periods=5).mean()
    df["vol_std20"] = df["volume"].rolling(20, min_periods=5).std()
    df["gap_days"] = df["time"].diff().dt.days

    # Optionally restrict scanning window
    scan = df.tail(lookback) if lookback else df

    for _, row in scan.iterrows():
        prev_c = row.get("prev_close")
        chg = row.get("chg_pct")
        ts = str(row["time"].date())

        # 1) close breaches the band
        if pd.notna(prev_c) and pd.notna(chg) and abs(chg) > band:
            sev = "fail" if abs(chg) > band * 1.5 else "warn"
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="band", severity=sev,
                detail=f"close chg {chg:+.2f}% exceeds {exchange} band ±{band:.2f}%",
                metrics={"chg_pct": round(float(chg), 3),
                         "exchange": exchange,
                         "prev_close": float(prev_c)},
            ))

        # 2) high/low outside the band (print errors)
        hi = row.get("hi_pct"); lo = row.get("lo_pct")
        if pd.notna(hi) and hi > band * 1.05:
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="ohlc", severity="warn",
                detail=f"high {hi:+.2f}% > band +{band:.2f}%",
                metrics={"hi_pct": round(float(hi), 3)},
            ))
        if pd.notna(lo) and lo < -band * 1.05:
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="ohlc", severity="warn",
                detail=f"low {lo:+.2f}% < band -{band:.2f}%",
                metrics={"lo_pct": round(float(lo), 3)},
            ))

        # 3) calendar gap
        gap = row.get("gap_days")
        if pd.notna(gap) and gap > MAX_GAP_DAYS:
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="gap", severity="warn",
                detail=f"{int(gap)}-day gap since previous bar",
                metrics={"gap_days": int(gap)},
            ))

        # 4) volume spike
        vm = row.get("vol_mean20"); vs = row.get("vol_std20")
        v = row.get("volume")
        if (pd.notna(vm) and pd.notna(vs) and vm > 0
                and v > vm * VOL_SPIKE_FACTOR
                and v > vm + VOL_SIGMA_GATE * vs):
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="vol_spike", severity="warn",
                detail=f"volume {int(v):,} vs mean20 {int(vm):,} "
                       f"(factor {v/vm:.1f}x)",
                metrics={"volume": int(v),
                         "mean20": float(vm),
                         "factor": round(float(v / vm), 2)},
            ))

        # 5) zero volume but price changed
        if pd.notna(v) and v == 0 and pd.notna(chg) and abs(chg) > 0.5:
            out.append(Anomaly(
                ticker=ticker, trading_date=ts, kind="zero_vol_move",
                severity="fail",
                detail=f"volume=0 but close moved {chg:+.2f}%",
                metrics={"chg_pct": round(float(chg), 3)},
            ))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Warehouse scan
# ─────────────────────────────────────────────────────────────────────────────


def _iter_warehouse_tickers(warehouse: Path) -> Iterable[tuple[str, pd.DataFrame]]:
    prices_dir = warehouse / PRICES_SUBDIR
    if not prices_dir.exists():
        return
    for ticker_dir in sorted(prices_dir.glob("ticker=*")):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name.removeprefix("ticker=")
        frames: list[pd.DataFrame] = []
        for pq_file in sorted(ticker_dir.glob("year=*/*.parquet")):
            try:
                frames.append(pd.read_parquet(pq_file))
            except Exception:
                continue
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        yield ticker, df


def scan_warehouse(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    lookback: int | None = 60,
    tickers: list[str] | None = None,
) -> AnomalyReport:
    exchange_map = _load_exchange_map(warehouse)
    anomalies: list[Anomaly] = []
    scanned = 0

    for ticker, df in _iter_warehouse_tickers(warehouse):
        if tickers and ticker not in tickers:
            continue
        scanned += 1
        ex, _band = band_for(ticker, exchange_map)
        try:
            anomalies.extend(
                scan_ticker(df, ticker, exchange=ex, lookback=lookback)
            )
        except Exception as e:
            print(f"[anomaly] {ticker}: {e}", file=sys.stderr)

    return AnomalyReport(
        run_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        tickers_scanned=scanned,
        anomalies=sorted(
            anomalies,
            key=lambda a: (a.severity != "fail", a.trading_date, a.ticker),
        ),
    )


def write_report(report: AnomalyReport, warehouse: Path = DEFAULT_WAREHOUSE) -> Path:
    meta_dir = warehouse / META_SUBDIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    out = meta_dir / "anomalies.json"
    out.write_text(json.dumps(report.to_dict(), indent=2, default=str))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    ap.add_argument("--lookback", type=int, default=60,
                    help="Trailing rows to scan per ticker (0 = full history).")
    ap.add_argument("--ticker", action="append",
                    help="Limit scan to these ticker(s). Default: all.")
    ap.add_argument("--full", action="store_true",
                    help="Shortcut for --lookback 0 (scan entire history).")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    lookback = None if args.full or args.lookback == 0 else args.lookback
    report = scan_warehouse(
        warehouse=Path(args.warehouse),
        lookback=lookback,
        tickers=args.ticker,
    )
    summary = report.to_dict()
    print(f"[anomaly] scanned {summary['tickers_scanned']} tickers — "
          f"{summary['total']} anomalies "
          f"(by_kind={summary['by_kind']}, by_severity={summary['by_severity']})")
    for a in report.anomalies[:20]:
        print(f"  [{a.severity:4}] {a.kind:13} {a.ticker} {a.trading_date}: {a.detail}")

    if not args.no_write:
        out = write_report(report, Path(args.warehouse))
        print(f"[anomaly] wrote {out}")


if __name__ == "__main__":
    main()


__all__ = [
    "BAND_PCT", "BAND_TOLERANCE_PCT", "MAX_GAP_DAYS",
    "VOL_SPIKE_FACTOR", "VOL_SIGMA_GATE",
    "Anomaly", "AnomalyReport",
    "band_for", "scan_ticker", "scan_warehouse", "write_report",
]
