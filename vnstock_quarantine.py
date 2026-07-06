"""
Quarantine system for rows rejected by the data contract.

Problem
-------
The Pandera contract (``vnstock_contracts.validate_ohlcv``) drops rows that
fail structural checks (price <= 0, high < low, volume < 0, …). Previously
those rows were silently discarded — the warehouse was clean, but the rows
were lost forever. If a one-off API glitch caused a bad print, the bar was
gone until someone noticed the gap and refetched by hand.

Solution
--------
Instead of silently dropping, offending rows are written to
``_meta/quarantine/{TICKER}/{DATE}.json`` with:
* the raw values that failed the check
* the reason(s) the row was rejected
* a fetch timestamp and a retry counter

Operators can then:
* Run ``retry_quarantined()`` to re-fetch and try to heal entries whose
  retry counter is below ``max_retries``. Successfully healed rows are
  written back to the warehouse and the quarantine file removed.
* Inspect remaining entries via ``list_quarantine()`` to triage manually.
* ``accept_quarantine()`` to whitelist a bar (e.g. a delisted stock with
  a legitimate zero close) so it doesn't keep flapping.

The quarantine is a file-based store on purpose: easy to inspect with
``ls`` / VS Code, trivial to clear by deleting the directory, no DB needed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd


DEFAULT_WAREHOUSE = Path("data_warehouse")
QUARANTINE_SUBDIR = "_meta/quarantine"
WHITELIST_FILE = "_meta/quarantine_whitelist.json"

MAX_RETRIES_DEFAULT = 3


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class QuarantineEntry:
    ticker: str
    bar_date: str                 # YYYY-MM-DD
    reason: str
    raw_values: dict              # original row as a plain dict
    fetched_at: str               # ISO timestamp
    retry_count: int = 0
    last_retry_at: str | None = None
    accepted: bool = False
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)



# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────────────────────────────────────


def _quarantine_dir(warehouse: Path) -> Path:
    return Path(warehouse) / QUARANTINE_SUBDIR


def _entry_path(warehouse: Path, ticker: str, bar_date: str) -> Path:
    ticker = str(ticker).upper()
    return _quarantine_dir(warehouse) / ticker / f"{bar_date}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic write with retry — Dropbox / AV on Windows can hold a transient
    lock on the destination and break os.replace; short backoff absorbs it."""
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
            time.sleep(0.1 * (2 ** attempt))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    if last_err is not None:
        raise last_err


def _normalise_date(d) -> str:
    """Coerce various date shapes to YYYY-MM-DD."""
    if isinstance(d, str):
        return d.split("T")[0][:10]
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return pd.to_datetime(d).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# Public CRUD
# ─────────────────────────────────────────────────────────────────────────────


def quarantine_row(
    ticker: str,
    bar_date,
    reason: str,
    raw_values: dict,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> Path:
    """Add / refresh an entry in the quarantine."""
    d = _normalise_date(bar_date)
    path = _entry_path(Path(warehouse), ticker, d)

    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    entry = QuarantineEntry(
        ticker=str(ticker).upper(),
        bar_date=d,
        reason=reason,
        raw_values={k: _jsonable(v) for k, v in (raw_values or {}).items()},
        fetched_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        retry_count=int(existing.get("retry_count", 0)),
        last_retry_at=existing.get("last_retry_at"),
        accepted=bool(existing.get("accepted", False)),
        note=existing.get("note"),
    )
    _atomic_write(path, entry.to_dict())
    return path


def list_quarantine(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    ticker: str | None = None,
) -> pd.DataFrame:
    """Return all quarantined rows as a DataFrame."""
    qdir = _quarantine_dir(Path(warehouse))
    if not qdir.exists():
        return pd.DataFrame(columns=list(QuarantineEntry.__dataclass_fields__))

    rows: list[dict] = []
    pattern = f"{ticker.upper()}/*.json" if ticker else "*/*.json"
    for f in qdir.glob(pattern):
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=list(QuarantineEntry.__dataclass_fields__))
    df = pd.DataFrame(rows)
    return df.sort_values(["accepted", "retry_count", "ticker", "bar_date"],
                          ascending=[True, False, True, True])


def accept_quarantine(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
    note: str | None = None,
) -> bool:
    """Mark an entry as accepted — won't be retried automatically."""
    path = _entry_path(Path(warehouse), ticker, _normalise_date(bar_date))
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    data["accepted"] = True
    if note is not None:
        data["note"] = note
    _atomic_write(path, data)
    return True


def clear_quarantine(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> bool:
    """Remove an entry entirely (e.g. after a successful re-fetch)."""
    path = _entry_path(Path(warehouse), ticker, _normalise_date(bar_date))
    if not path.exists():
        return False
    try:
        path.unlink()
    except Exception:
        return False
    # Try to remove parent dir if empty — keeps the tree tidy
    try:
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        pass
    return True


def bump_retry(
    ticker: str,
    bar_date,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> int:
    """Increment retry_count + update last_retry_at. Returns the new count."""
    path = _entry_path(Path(warehouse), ticker, _normalise_date(bar_date))
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    data["retry_count"] = int(data.get("retry_count", 0)) + 1
    data["last_retry_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _atomic_write(path, data)
    return int(data["retry_count"])


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────


def auto_heal(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    max_retries: int = MAX_RETRIES_DEFAULT,
    archive_exhausted: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Walk every pending quarantine entry and try to heal it automatically.

    Behaviour per entry:
      1. ``accepted`` entries are skipped (user explicitly okayed them).
      2. ``retry_count < max_retries`` → call ``refetch()``. If success,
         the refetch helper clears the entry. If failure, bump the counter.
      3. ``retry_count >= max_retries`` AND ``archive_exhausted`` → wipe
         the quarantine file (the row in warehouse was never written, so
         no extra archive step needed). A one-line entry is appended to
         the remediation log so the decision is traceable.

    Returns a stats dict ``{"scanned": n, "refetched_ok": n,
    "refetched_fail": n, "archived": n, "skipped_accepted": n}``.
    ``dry_run=True`` returns the same shape without mutating anything;
    pending entries are counted under ``refetched_ok`` to show the
    planned action (outcome is unknowable without calling the API).
    """
    import time

    # Lazy imports — we can't ``from vnstock_remediate import refetch`` at
    # module level because vnstock_remediate already imports from here
    # (circular init). The function bodies resolve fine at call time.
    try:
        from vnstock_remediate import refetch
    except Exception as exc:
        return {
            "scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
            "archived": 0, "skipped_accepted": 0,
            "error": f"cannot import refetch: {exc}",
        }

    stats = {
        "scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
        "archived": 0, "skipped_accepted": 0,
    }

    df = list_quarantine(warehouse)
    if df.empty:
        return stats

    warehouse = Path(warehouse)
    for _, row in df.iterrows():
        stats["scanned"] += 1
        ticker = str(row.get("ticker", "")).strip()
        bar_date = str(row.get("bar_date", "")).strip()
        accepted = bool(row.get("accepted", False))
        retry_count = int(row.get("retry_count", 0) or 0)
        if not ticker or not bar_date:
            continue

        if accepted:
            stats["skipped_accepted"] += 1
            continue

        if retry_count >= max_retries:
            if archive_exhausted and not dry_run:
                _log_exhausted(warehouse, ticker, bar_date, retry_count,
                                row.get("reason", ""))
                clear_quarantine(ticker, bar_date, warehouse=warehouse)
            stats["archived"] += 1
            if verbose:
                print(f"[quarantine.auto_heal] archived {ticker} {bar_date} "
                      f"(retries={retry_count} >= {max_retries})")
            continue

        if dry_run:
            # Count as a planned refetch so the user can see the
            # pre-action shape of the pass. The actual outcome (ok vs
            # fail) is unknowable without calling the API.
            stats["refetched_ok"] += 1
            if verbose:
                print(f"[quarantine.auto_heal] would refetch {ticker} "
                      f"{bar_date} (retries={retry_count})")
            continue

        try:
            result = refetch(ticker, bar_date, warehouse=warehouse)
        except Exception as exc:
            bump_retry(ticker, bar_date, warehouse=warehouse)
            stats["refetched_fail"] += 1
            if verbose:
                print(f"[quarantine.auto_heal] refetch {ticker} {bar_date} "
                      f"raised: {exc}")
            continue

        status = (result or {}).get("status") if isinstance(result, dict) else None
        if status == "ok":
            stats["refetched_ok"] += 1
            if verbose:
                print(f"[quarantine.auto_heal] healed {ticker} {bar_date}")
        else:
            bump_retry(ticker, bar_date, warehouse=warehouse)
            stats["refetched_fail"] += 1
            if verbose:
                print(f"[quarantine.auto_heal] refetch {ticker} {bar_date} "
                      f"→ {status}")
        # Tiny pause so batch runs don't hammer the API
        time.sleep(0.05)

    return stats


def _log_exhausted(warehouse: Path, ticker: str, bar_date: str,
                    retry_count: int, reason: str) -> None:
    """Record an auto-archive in _meta/remediation_log.jsonl for traceability."""
    log_path = warehouse / "_meta" / "remediation_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "action": "auto_archive",
        "ticker": ticker,
        "date": bar_date,
        "result": "ok",
        "detail": (f"retries={retry_count} exhausted; "
                   f"original reason: {reason}"),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")



def summary(warehouse: Path = DEFAULT_WAREHOUSE) -> dict:
    """Concise stats for the health dashboard."""
    df = list_quarantine(warehouse)
    if df.empty:
        return {"total": 0, "accepted": 0, "pending": 0,
                "max_retries_hit": 0, "by_reason": {}}
    accepted = int(df["accepted"].sum()) if "accepted" in df.columns else 0
    pending = int(len(df) - accepted)
    max_hit = (
        int(((df["retry_count"] >= MAX_RETRIES_DEFAULT) & (~df["accepted"])).sum())
        if "retry_count" in df.columns and "accepted" in df.columns
        else 0
    )
    reason_counts: dict[str, int] = {}
    if "reason" in df.columns:
        reason_counts = df["reason"].value_counts().to_dict()
    return {
        "total": int(len(df)),
        "accepted": accepted,
        "pending": pending,
        "max_retries_hit": max_hit,
        "by_reason": {str(k): int(v) for k, v in reason_counts.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bulk quarantine from a DataFrame of dropped rows
# ─────────────────────────────────────────────────────────────────────────────


def quarantine_dropped(
    dropped: pd.DataFrame,
    reasons: list[str] | str,
    *,
    warehouse: Path = DEFAULT_WAREHOUSE,
) -> int:
    """
    Quarantine a DataFrame of dropped rows at once.

    ``reasons`` is either a single string (applied to all rows) or a list of
    per-row reason strings the same length as ``dropped``.
    """
    if dropped is None or dropped.empty:
        return 0
    if "ticker" not in dropped.columns or "time" not in dropped.columns:
        return 0
    if isinstance(reasons, str):
        reasons_list = [reasons] * len(dropped)
    else:
        reasons_list = list(reasons)
        if len(reasons_list) != len(dropped):
            reasons_list += [reasons_list[-1] if reasons_list else "unknown"] * (
                len(dropped) - len(reasons_list)
            )

    n = 0
    for (_, row), reason in zip(dropped.iterrows(), reasons_list):
        quarantine_row(
            ticker=str(row["ticker"]),
            bar_date=row["time"],
            reason=reason,
            raw_values={k: row[k] for k in row.index if k != "year"},
            warehouse=warehouse,
        )
        n += 1
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _jsonable(v):
    if pd.isna(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


__all__ = [
    "MAX_RETRIES_DEFAULT",
    "QuarantineEntry",
    "accept_quarantine",
    "auto_heal",
    "bump_retry",
    "clear_quarantine",
    "list_quarantine",
    "quarantine_dropped",
    "quarantine_row",
    "summary",
]
