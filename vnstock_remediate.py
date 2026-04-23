"""
Remediation actions — the "fix" side of detect-and-fix.

Given a ticker + date (and optionally a kind of anomaly), choose an action:

* ``refetch``  — re-download that date's bar from the vnstock API. If the new
                  value passes the contract, it replaces the warehouse row
                  and the quarantine entry (if any) is cleared.
* ``accept``   — mark the row as "known bad but leave it". For quarantine
                  entries this sets ``accepted=True``. For anomalies it writes
                  an entry to ``_meta/anomaly_whitelist.json`` so the scanner
                  skips the (ticker, date, kind) tuple on future runs.
* ``archive``  — delete the bar from the warehouse. Use sparingly — only when
                  you're sure the row is bogus and can't be recovered.
* ``note``     — attach a free-text note to a quarantine entry.

Bulk operations
---------------
The CLI supports ``--all-kind KIND`` to apply a single action to every
anomaly of a given kind in the most recent ``anomalies.json``. Useful for
e.g. ``--all-kind ohlc --action refetch`` after a known bad API day.

Nothing here mutates the warehouse without logging. A JSON line is appended
to ``_meta/remediation_log.jsonl`` for every action.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"
PRICES_SUBDIR = "prices"
WHITELIST_FILE = "anomaly_whitelist.json"
LOG_FILE = "remediation_log.jsonl"

ACTIONS = ("refetch", "accept", "archive", "note")


# ─────────────────────────────────────────────────────────────────────────────
# Whitelist
# ─────────────────────────────────────────────────────────────────────────────


def _whitelist_path(warehouse: Path) -> Path:
    return Path(warehouse) / META_SUBDIR / WHITELIST_FILE


def load_whitelist(warehouse: Path = DEFAULT_WAREHOUSE) -> set[tuple[str, str, str]]:
    """Return the set of (ticker, date, kind) tuples that are whitelisted."""
    path = _whitelist_path(Path(warehouse))
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out: set[tuple[str, str, str]] = set()
    for entry in data.get("entries", []):
        t = str(entry.get("ticker", "")).upper()
        d = str(entry.get("date", ""))[:10]
        k = str(entry.get("kind", "*"))
        if t and d:
            out.add((t, d, k))
    return out


def add_to_whitelist(
    ticker: str,
    bar_date,
    kind: str = "*",
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    note: str | None = None,
) -> Path:
    """Append an entry to the anomaly whitelist."""
    path = _whitelist_path(Path(warehouse))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"entries": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {"entries": []}
        except Exception:
            data = {"entries": []}

    d = _normalise_date(bar_date)
    entry = {
        "ticker": ticker.upper(),
        "date": d,
        "kind": kind,
        "accepted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "note": note or "",
    }
    # Dedupe by (ticker, date, kind)
    key = (entry["ticker"], entry["date"], entry["kind"])
    data["entries"] = [
        e for e in data["entries"]
        if (e.get("ticker", "").upper(), str(e.get("date", ""))[:10],
            e.get("kind", "*")) != key
    ]
    data["entries"].append(entry)
    _atomic_write_json(path, data)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Actions
# ─────────────────────────────────────────────────────────────────────────────


def refetch(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    pad_days: int = 2,
) -> dict:
    """
    Re-fetch the single bar for ``ticker`` on ``bar_date`` from the vnstock
    API and write it through the contract → warehouse. Clears the quarantine
    entry on success.

    ``pad_days`` widens the fetch range (the API sometimes declines single-
    day requests). The resulting DataFrame is then filtered to the target
    date.
    """
    target = _normalise_date(bar_date)
    try:
        start = (pd.Timestamp(target) - pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")
        end = (pd.Timestamp(target) + pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")
    except Exception:
        return {"status": "error", "reason": f"invalid date {target}"}

    try:
        from vnstock_warehouse import VnstockWarehouse
    except Exception as e:
        return {"status": "error", "reason": f"cannot import warehouse: {e}"}

    try:
        wh = VnstockWarehouse(root=str(warehouse), verbose=False)
        df = wh._fetch_price(ticker, start=start, end=end)
    except Exception as e:
        return {"status": "error", "reason": f"fetch failed: {e}"}

    if df is None or df.empty:
        _log_action(warehouse, "refetch", ticker, target,
                    result="fail", detail="API returned empty")
        return {"status": "fail", "reason": "API returned empty"}

    # Keep only the target date
    df["time"] = pd.to_datetime(df["time"]).dt.date
    target_d = pd.to_datetime(target).date()
    df = df[df["time"] == target_d]
    if df.empty:
        _log_action(warehouse, "refetch", ticker, target,
                    result="fail", detail="no row for target date in response")
        return {"status": "fail", "reason": "no row for target date"}

    # Write through the contract (quarantine for rejection is automatic)
    try:
        wh._write_parquet(df, ticker)
    except Exception as e:
        return {"status": "error", "reason": f"write failed: {e}"}

    # On success, clear any quarantine entry for this (ticker, date)
    try:
        from vnstock_quarantine import clear_quarantine
        clear_quarantine(ticker, target, warehouse=warehouse)
    except Exception:
        pass

    _log_action(warehouse, "refetch", ticker, target, result="ok")
    return {"status": "ok", "rows_written": len(df)}


def accept(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    kind: str = "*",
    note: str | None = None,
) -> dict:
    """Accept a (ticker, date[, kind]) — both quarantine and whitelist paths."""
    d = _normalise_date(bar_date)
    # Quarantine
    try:
        from vnstock_quarantine import accept_quarantine
        accept_quarantine(ticker, d, warehouse=warehouse, note=note)
    except Exception:
        pass
    # Whitelist (for anomalies)
    path = add_to_whitelist(ticker, d, kind=kind,
                             warehouse=warehouse, note=note)
    _log_action(warehouse, "accept", ticker, d,
                result="ok", detail=f"kind={kind}; whitelist={path.name}")
    return {"status": "ok", "whitelist_file": str(path)}


def archive(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> dict:
    """
    Delete the bar for ``ticker`` on ``bar_date`` from the warehouse.

    This is a destructive action — used when refetch fails and the row is
    definitively bogus (e.g. a stale API error that never resolves).
    """
    target = _normalise_date(bar_date)
    target_d = pd.to_datetime(target).date()
    year = target_d.year

    prices_dir = Path(warehouse) / PRICES_SUBDIR / f"ticker={ticker.upper()}" / f"year={year}"
    if not prices_dir.exists():
        _log_action(warehouse, "archive", ticker, target,
                    result="fail", detail="no warehouse partition")
        return {"status": "fail", "reason": "partition not found"}

    import pyarrow.parquet as pq

    removed_total = 0
    for pq_file in prices_dir.glob("*.parquet"):
        try:
            df = pq.read_table(str(pq_file)).to_pandas()
        except Exception:
            continue
        if df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"]).dt.date
        mask = df["time"] == target_d
        if not mask.any():
            continue
        kept = df[~mask]
        removed_total += int(mask.sum())
        # Rewrite file without the archived row
        if kept.empty:
            try:
                pq_file.unlink()
            except Exception:
                pass
        else:
            import pyarrow as pa
            kept["time"] = pd.to_datetime(kept["time"])
            table = pa.Table.from_pandas(kept, preserve_index=False)
            pq.write_table(table, str(pq_file), compression="snappy")

    if removed_total == 0:
        _log_action(warehouse, "archive", ticker, target,
                    result="fail", detail="no matching row")
        return {"status": "fail", "reason": "no matching row"}

    _log_action(warehouse, "archive", ticker, target,
                result="ok", detail=f"removed {removed_total} row(s)")
    return {"status": "ok", "removed": removed_total}


def attach_note(
    ticker: str,
    bar_date,
    note: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> dict:
    """Attach/update a free-text note on a quarantine entry."""
    try:
        from vnstock_quarantine import accept_quarantine
        ok = accept_quarantine(ticker, bar_date, warehouse=warehouse, note=note)
        if not ok:
            return {"status": "fail", "reason": "no quarantine entry"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    _log_action(warehouse, "note", ticker, _normalise_date(bar_date),
                result="ok", detail=note[:100])
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Bulk actions driven by the most recent anomalies.json
# ─────────────────────────────────────────────────────────────────────────────


def apply_bulk(
    action: str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    ticker: str | None = None,
    kind: str | None = None,
    severity: str | None = None,
    limit: int = 0,
    dry_run: bool = False,
) -> dict:
    """Apply ``action`` to every anomaly matching the filters."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; allowed: {ACTIONS}")

    anomalies_path = Path(warehouse) / META_SUBDIR / "anomalies.json"
    if not anomalies_path.exists():
        return {"status": "fail", "reason": "no anomalies.json — run audit first"}

    try:
        data = json.loads(anomalies_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "reason": f"bad anomalies.json: {e}"}

    items = data.get("anomalies", [])
    if ticker:
        items = [a for a in items if str(a.get("ticker", "")).upper() == ticker.upper()]
    if kind:
        items = [a for a in items if a.get("kind") == kind]
    if severity:
        items = [a for a in items if a.get("severity") == severity]
    if limit:
        items = items[:limit]

    summary = {"total": len(items), "ok": 0, "fail": 0, "error": 0,
               "dry_run": dry_run}
    for a in items:
        ticker = a.get("ticker")
        d = a.get("trading_date")
        if not ticker or not d:
            continue
        if dry_run:
            summary["ok"] += 1
            continue
        try:
            if action == "refetch":
                res = refetch(ticker, d, warehouse=warehouse)
            elif action == "accept":
                res = accept(ticker, d, warehouse=warehouse,
                             kind=a.get("kind", "*"),
                             note=f"bulk-accepted via {action}")
            elif action == "archive":
                res = archive(ticker, d, warehouse=warehouse)
            else:  # note
                res = attach_note(ticker, d, f"flagged as {a.get('kind')}",
                                   warehouse=warehouse)
        except Exception as e:
            summary["error"] += 1
            print(f"  [bulk] {ticker} {d}: {e}", file=sys.stderr)
            continue
        if res.get("status") == "ok":
            summary["ok"] += 1
        else:
            summary["fail"] += 1
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _normalise_date(d) -> str:
    if isinstance(d, str):
        return d.split("T")[0][:10]
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return pd.to_datetime(d).strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic write with retry — Dropbox / antivirus on Windows occasionally
    holds a transient lock on the destination path and os.replace fails with
    PermissionError. A short retry loop absorbs those spikes."""
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(path))
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.1 * (2 ** attempt))  # 0.1, 0.2, 0.4, 0.8, 1.6s
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    if last_err is not None:
        raise last_err


def _log_action(
    warehouse: Path,
    action: str,
    ticker: str,
    bar_date: str,
    *,
    result: str,
    detail: str = "",
) -> None:
    path = Path(warehouse) / META_SUBDIR / LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "action": action,
        "ticker": str(ticker).upper(),
        "date": str(bar_date),
        "result": result,
        "detail": detail,
    }, ensure_ascii=False)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Remediate anomalies / quarantine items")
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    ap.add_argument("--ticker", help="Single ticker target")
    ap.add_argument("--date", help="Single date target (YYYY-MM-DD)")
    ap.add_argument("--kind", help="Anomaly kind filter (for --all)")
    ap.add_argument("--severity", choices=["fail", "warn"])
    ap.add_argument("--action", choices=list(ACTIONS), required=True)
    ap.add_argument("--note", default=None, help="Note attached to accept/note")
    ap.add_argument("--all", action="store_true",
                    help="Apply action to every matching anomaly in anomalies.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    warehouse = Path(args.warehouse)

    if args.all:
        result = apply_bulk(
            args.action,
            warehouse=warehouse,
            kind=args.kind,
            severity=args.severity,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") != "error" else 2

    if not args.ticker or not args.date:
        ap.error("single-target mode requires --ticker and --date (or use --all)")

    if args.action == "refetch":
        res = refetch(args.ticker, args.date, warehouse=warehouse)
    elif args.action == "accept":
        res = accept(args.ticker, args.date, warehouse=warehouse,
                     kind=args.kind or "*", note=args.note)
    elif args.action == "archive":
        res = archive(args.ticker, args.date, warehouse=warehouse)
    elif args.action == "note":
        if not args.note:
            ap.error("--action note requires --note TEXT")
        res = attach_note(args.ticker, args.date, args.note, warehouse=warehouse)
    else:
        ap.error(f"unknown action {args.action}")

    print(json.dumps(res, indent=2))
    return 0 if res.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ACTIONS",
    "accept",
    "add_to_whitelist",
    "apply_bulk",
    "archive",
    "attach_note",
    "load_whitelist",
    "refetch",
]
