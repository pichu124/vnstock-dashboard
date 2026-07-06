"""
Top-offender analysis for the anomaly report.

Purpose
-------
The audit output says "2,947 anomalies flagged", but leaves operators
guessing about distribution. This module answers the real question:

    "Is the noise concentrated in 5-10 bad tickers (refetch them and
     80% of the problem goes away), or is it spread uniformly across
     the whole universe (accept or tune thresholds)?"

It groups `_meta/anomalies.json` by ticker, ranks the worst offenders,
breaks down their kinds, and suggests bulk remediation commands.

CLI
---
    python vnstock_top_offenders.py --warehouse data_warehouse
    python vnstock_top_offenders.py --severity fail --limit 20
    python vnstock_top_offenders.py --by-kind band

Returns exit code 0 if there are no offenders, 1 otherwise — useful
for cron pipelines that want to fail loudly when concentration spikes.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


DEFAULT_WAREHOUSE = Path("data_warehouse")
META_SUBDIR = "_meta"


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TickerStats:
    ticker: str
    total: int = 0
    fail: int = 0
    warn: int = 0
    by_kind: dict = field(default_factory=dict)
    latest_date: str | None = None
    earliest_date: str | None = None

    @property
    def suggested_action(self) -> str:
        """Recommend a remediation action based on the dominant kind."""
        if not self.by_kind:
            return "review"
        dominant = max(self.by_kind.items(), key=lambda kv: kv[1])[0]
        if dominant == "ohlc":
            return "refetch"   # print errors almost always refetch away
        if dominant == "band":
            return "review"    # could be real event (halt/IPO)
        if dominant == "gap":
            return "accept"    # halt/delisting
        if dominant == "vol_spike":
            return "review"    # could be real (big news)
        return "review"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["suggested_action"] = self.suggested_action
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Analyzer
# ─────────────────────────────────────────────────────────────────────────────


def analyze(
    warehouse: Path = DEFAULT_WAREHOUSE,
    *,
    severity_filter: str | None = None,
    kind_filter: str | None = None,
) -> list[TickerStats]:
    """
    Return a list of TickerStats sorted by total count (desc).

    Parameters
    ----------
    severity_filter : "fail" | "warn" | None — keep only matching entries.
    kind_filter : restrict to a single kind (e.g. "band").
    """
    path = Path(warehouse) / META_SUBDIR / "anomalies.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    items = data.get("anomalies", []) or []
    if severity_filter:
        items = [a for a in items if a.get("severity") == severity_filter]
    if kind_filter:
        items = [a for a in items if a.get("kind") == kind_filter]

    by_ticker: dict[str, TickerStats] = {}
    for a in items:
        ticker = a.get("ticker")
        if not ticker:
            continue
        stats = by_ticker.setdefault(ticker, TickerStats(ticker=ticker))
        stats.total += 1
        if a.get("severity") == "fail":
            stats.fail += 1
        else:
            stats.warn += 1
        kind = a.get("kind", "?")
        stats.by_kind[kind] = stats.by_kind.get(kind, 0) + 1
        d = a.get("trading_date")
        if d:
            if stats.latest_date is None or d > stats.latest_date:
                stats.latest_date = d
            if stats.earliest_date is None or d < stats.earliest_date:
                stats.earliest_date = d

    return sorted(by_ticker.values(), key=lambda s: s.total, reverse=True)


def concentration(stats: list[TickerStats], top_n: int = 10) -> dict:
    """How much of the total noise sits in the top N tickers?"""
    if not stats:
        return {"total_anomalies": 0, "total_tickers": 0,
                "top_n": top_n, "top_n_share": 0.0, "pattern": "empty"}
    total = sum(s.total for s in stats)
    top_total = sum(s.total for s in stats[:top_n])
    share = top_total / total if total else 0.0
    pattern = (
        "concentrated" if share >= 0.5 else
        "moderate" if share >= 0.2 else
        "diffuse"
    )
    return {
        "total_anomalies": total,
        "total_tickers": len(stats),
        "top_n": top_n,
        "top_n_total": top_total,
        "top_n_share": round(share, 3),
        "pattern": pattern,
    }


def bulk_suggestions(stats: list[TickerStats], *, limit: int = 10) -> list[dict]:
    """Turn the top N offenders into concrete CLI suggestions."""
    suggestions: list[dict] = []
    for s in stats[:limit]:
        action = s.suggested_action
        suggestions.append({
            "ticker": s.ticker,
            "total": s.total,
            "action": action,
            "cli": (
                f"python run.py remediate --ticker {s.ticker} --all "
                f"--action {action}"
                if action in ("refetch", "accept", "archive")
                else (
                    f"# review manually: "
                    f"grep -r '{s.ticker}' data_warehouse/_meta/anomalies.json"
                )
            ),
        })
    return suggestions


# ─────────────────────────────────────────────────────────────────────────────
# Pretty printer
# ─────────────────────────────────────────────────────────────────────────────


def render_table(stats: list[TickerStats], *, limit: int = 20) -> str:
    if not stats:
        return "(no anomalies)"
    rows = stats[:limit]
    widths = {"rank": 4, "ticker": 8, "total": 6, "fail": 5, "warn": 5,
              "kinds": 30, "latest": 12, "action": 10}
    header = (
        f"{'Rank':<{widths['rank']}} "
        f"{'Ticker':<{widths['ticker']}} "
        f"{'Total':>{widths['total']}} "
        f"{'Fail':>{widths['fail']}} "
        f"{'Warn':>{widths['warn']}} "
        f"{'Kinds':<{widths['kinds']}} "
        f"{'Latest':<{widths['latest']}} "
        f"{'Action':<{widths['action']}}"
    )
    sep = "─" * len(header)
    lines = [header, sep]
    for i, s in enumerate(rows, 1):
        kinds_s = ", ".join(f"{k}:{v}" for k, v in sorted(
            s.by_kind.items(), key=lambda kv: -kv[1]
        ))[:widths["kinds"]]
        latest = (s.latest_date or "")[:widths["latest"]]
        lines.append(
            f"{i:<{widths['rank']}} "
            f"{s.ticker:<{widths['ticker']}} "
            f"{s.total:>{widths['total']}} "
            f"{s.fail:>{widths['fail']}} "
            f"{s.warn:>{widths['warn']}} "
            f"{kinds_s:<{widths['kinds']}} "
            f"{latest:<{widths['latest']}} "
            f"{s.suggested_action:<{widths['action']}}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
