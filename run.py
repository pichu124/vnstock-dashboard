"""
Unified orchestrator for the vnstock-dashboard pipeline.

Replaces the PowerShell-specific Scheduled Task setup with a single, portable
Python entry point that can be driven from cron, Windows Task Scheduler,
GitHub Actions, or manually.

Subcommands
-----------
    python run.py scan       — collect a HealthSnapshot and print it
    python run.py sync       — incremental daily update (updater + rollup)
    python run.py validate   — re-run pandera contracts on the warehouse
    python run.py audit      — reconciler + anomaly scan, optionally + LLM
    python run.py test       — pytest
    python run.py dashboard  — launch streamlit dashboard
    python run.py all        — sync → validate → test → audit (in order,
                                stopping on first failure)

Exit codes
----------
0 = success, 1 = non-fatal warning (e.g. some anomalies flagged),
2 = hard failure (a step returned non-zero).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


DEFAULT_WAREHOUSE = Path("data_warehouse")
REPO_ROOT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand implementations
# ─────────────────────────────────────────────────────────────────────────────


def cmd_scan(args) -> int:
    from vnstock_health import collect

    snap = collect(
        Path(args.warehouse),
        fast=getattr(args, "fast", False),
        verbose=getattr(args, "verbose", False),
    )
    print(json.dumps(snap.to_dict(), indent=2, default=str, ensure_ascii=False))
    return 1 if snap.warnings else 0


def cmd_sync(args) -> int:
    """Run incremental daily updater, then roll up any intraday bars."""
    updater = _run([sys.executable, "vnstock_updater.py", "--skip-if-done"])
    if updater != 0:
        return 2
    rollup = _run([sys.executable, "vnstock_rollup.py", "--skip-if-done"])
    return 0 if rollup == 0 else 2


def cmd_validate(args) -> int:
    """Walk the warehouse and run the OHLCV contract on every ticker.

    This is heavier than the inline write-time check because it validates
    the full history, not just newly-ingested rows. Useful after a schema
    change to pandera or after a bulk load.
    """
    from vnstock_contracts import validate_ohlcv
    import pandas as pd

    prices_dir = Path(args.warehouse) / "prices"
    if not prices_dir.exists():
        print(f"[validate] warehouse not found at {prices_dir}")
        return 2

    total_in = total_out = total_dropped = 0
    failing_tickers: list[tuple[str, int]] = []
    for ticker_dir in sorted(prices_dir.glob("ticker=*")):
        ticker = ticker_dir.name.removeprefix("ticker=")
        frames = []
        for pq_file in ticker_dir.glob("year=*/*.parquet"):
            try:
                frames.append(pd.read_parquet(pq_file))
            except Exception:
                continue
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        # Contract requires ticker/year columns
        year = pd.to_datetime(df["time"]).dt.year.astype("int16") if "year" not in df.columns else df["year"]
        df = df.assign(ticker=ticker, year=year)
        _, report = validate_ohlcv(df, drop_invalid=True)
        total_in += report["rows_in"]
        total_out += report["rows_out"]
        total_dropped += report["dropped"]
        if report["dropped"] > 0:
            failing_tickers.append((ticker, report["dropped"]))

    print(f"[validate] {total_in:,} rows → {total_out:,} valid "
          f"({total_dropped:,} invalid)")
    if failing_tickers:
        print(f"[validate] {len(failing_tickers)} ticker(s) with invalid rows:")
        for t, n in sorted(failing_tickers, key=lambda x: -x[1])[:20]:
            print(f"  {t}: {n}")
        return 1
    return 0


def cmd_audit(args) -> int:
    """Run reconciler + anomaly scan. If ``--llm`` is passed, also ask the
    Auditor agent for a second opinion on the combined summary."""
    from vnstock_anomaly import scan_warehouse, write_report as write_anomaly
    from vnstock_reconciler import reconcile, write_report as write_recon

    warehouse = Path(args.warehouse)
    recon = reconcile(
        warehouse=warehouse,
        lookback=args.lookback,
        check_volume=getattr(args, "check_volume", False),
    )
    write_recon(recon, warehouse)
    print(f"[audit] reconciler: ok={recon.ok} warn={recon.warn} fail={recon.fail}")

    anom = scan_warehouse(
        warehouse=warehouse,
        lookback=args.lookback,
        stocks_only=not getattr(args, "include_non_stocks", False),
    )
    write_anomaly(anom, warehouse)
    total = len(anom.anomalies)
    print(f"[audit] anomalies: {total} flagged across {anom.tickers_scanned} tickers")

    summary = {
        "reconciler": {"ok": recon.ok, "warn": recon.warn, "fail": recon.fail,
                       "missing_in_api": recon.missing_in_api,
                       "missing_in_rolled": recon.missing_in_rolled},
        "anomalies": {
            "total": total,
            "by_kind": {}, "by_severity": {},
        },
    }
    for a in anom.anomalies:
        summary["anomalies"]["by_kind"][a.kind] = \
            summary["anomalies"]["by_kind"].get(a.kind, 0) + 1
        summary["anomalies"]["by_severity"][a.severity] = \
            summary["anomalies"]["by_severity"].get(a.severity, 0) + 1

    if args.llm:
        from vnstock_auditor import make_auditor
        agent = make_auditor(prefer=args.auditor)
        verdict = agent.audit(
            summary,
            context=f"Daily audit for {date.today().isoformat()}.",
        )
        print(f"[audit] auditor={verdict.backend} "
              f"approved={verdict.approved} conf={verdict.confidence:.2f}")
        for i in verdict.issues:
            print(f"  issue: {i}")
        for s in verdict.suggestions:
            print(f"  suggestion: {s}")
        if not verdict.approved:
            return 1

    return 1 if (recon.fail + sum(1 for a in anom.anomalies if a.severity == "fail")) > 0 else 0


def cmd_refresh_metadata(args) -> int:
    """Build/refresh the cheap metadata caches used by the audit pipeline.

    * exchange_map.json  → listing-based HOSE/HNX/UPCOM map (one API call
      per exchange, very fast).
    * corp_actions/{TICKER}.parquet → per-ticker dividend + split events
      for bulk-refresh when ``--events`` is passed. This makes the anomaly
      scanner skip ex-dates and the adjusted-price layer work.
    """
    from vnstock_exchange_map import build_exchange_map

    warehouse = Path(args.warehouse)
    m = build_exchange_map(warehouse, verbose=True)
    print(f"[refresh] exchange_map: {len(m)} tickers")
    if m:
        # Show per-exchange breakdown
        from collections import Counter
        c = Counter(m.values())
        print(f"[refresh]   HOSE={c.get('HOSE', 0)} "
              f"HNX={c.get('HNX', 0)} UPCOM={c.get('UPCOM', 0)}")

    if args.events:
        from vnstock_adjust import refresh_events
        from vnstock_anomaly import _is_stock
        # Only refresh for real stocks
        prices_dir = warehouse / "prices"
        tickers = sorted(
            p.name.removeprefix("ticker=")
            for p in prices_dir.glob("ticker=*")
            if p.is_dir() and _is_stock(p.name.removeprefix("ticker="))
        )
        if args.limit:
            tickers = tickers[: args.limit]
        print(f"[refresh] fetching corp-action events for {len(tickers)} tickers...")
        success = skip = fail = 0
        for i, t in enumerate(tickers, 1):
            try:
                ev = refresh_events(t, warehouse, verbose=args.verbose)
                if ev.empty:
                    skip += 1
                else:
                    success += 1
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(tickers)}] {t}: {e}", file=sys.stderr)
            if i % 50 == 0:
                print(f"  progress: {i}/{len(tickers)} "
                      f"(ok={success} skip={skip} fail={fail})")
        print(f"[refresh] events: ok={success} skip={skip} fail={fail}")
    return 0


def cmd_remediate(args) -> int:
    """Dispatch to vnstock_remediate with the parsed args."""
    from vnstock_remediate import (
        accept, apply_bulk, archive, attach_note, refetch,
    )

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
        print("[remediate] single-target mode requires --ticker and --date, "
              "or use --all", file=sys.stderr)
        return 2

    if args.action == "refetch":
        res = refetch(args.ticker, args.date, warehouse=warehouse)
    elif args.action == "accept":
        res = accept(args.ticker, args.date, warehouse=warehouse,
                     kind=args.kind or "*", note=args.note)
    elif args.action == "archive":
        res = archive(args.ticker, args.date, warehouse=warehouse)
    elif args.action == "note":
        if not args.note:
            print("[remediate] --action note requires --note TEXT", file=sys.stderr)
            return 2
        res = attach_note(args.ticker, args.date, args.note, warehouse=warehouse)
    else:
        print(f"[remediate] unknown action {args.action}", file=sys.stderr)
        return 2

    print(json.dumps(res, indent=2))
    return 0 if res.get("status") == "ok" else 1


def cmd_top_offenders(args) -> int:
    """Rank tickers by anomaly count. Answers: is the noise concentrated?"""
    from vnstock_top_offenders import (
        analyze, bulk_suggestions, concentration, render_table,
    )

    stats = analyze(
        warehouse=Path(args.warehouse),
        severity_filter=args.severity,
        kind_filter=args.by_kind,
    )
    if args.json:
        out = {
            "concentration": concentration(stats, top_n=args.limit),
            "top": [s.to_dict() for s in stats[: args.limit]],
            "suggestions": bulk_suggestions(stats, limit=min(10, args.limit)),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        return 0 if not stats else 1

    print(f"\n=== Top {args.limit} offenders ===\n")
    print(render_table(stats, limit=args.limit))
    conc = concentration(stats, top_n=args.limit)
    print(f"\nConcentration: {conc['total_anomalies']} anomalies / "
          f"{conc['total_tickers']} tickers — "
          f"top {conc['top_n']} hold {conc['top_n_share']:.1%} "
          f"({conc['pattern'].upper()})")
    if conc["pattern"] == "concentrated":
        print("  → Refetch/accept the top offenders to clear most noise.")
    elif conc["pattern"] == "diffuse":
        print("  → Noise spread evenly — threshold tuning, not per-ticker fix.")
    for s in bulk_suggestions(stats, limit=min(10, args.limit)):
        print(f"  • {s['ticker']:6} ({s['total']:3} anomalies) → {s['cli']}")
    return 0


def cmd_diagnose(args) -> int:
    """Investigate a single (ticker, date) — what flagged it and why."""
    from datetime import date as _date
    from vnstock_diagnose import diagnose, render

    target = _date.fromisoformat(args.date)
    result = diagnose(
        args.ticker, target,
        warehouse=Path(args.warehouse),
        pad_days=args.pad_days,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2,
                          ensure_ascii=False, default=str))
    else:
        print(render(result))
    return 0


def cmd_registry(args) -> int:
    """Manage the corp_actions_registry.parquet."""
    from vnstock_corp_registry import (
        VALID_TYPES, clear_source, get_events_for_ticker,
        import_from_capital_history, register_event, summary,
    )
    warehouse = Path(args.warehouse)

    if args.subcmd == "show":
        if args.ticker:
            df = get_events_for_ticker(args.ticker, warehouse=warehouse)
            print(df.to_string(index=False) if not df.empty else "(empty)")
        else:
            print(json.dumps(summary(warehouse), indent=2,
                              ensure_ascii=False, default=str))
    elif args.subcmd == "add":
        if not args.type or args.type not in VALID_TYPES:
            print(f"--type must be one of {sorted(VALID_TYPES)}",
                  file=sys.stderr)
            return 2
        n = register_event(
            args.ticker, args.date, args.type,
            cash_amount=args.cash, ratio=args.ratio,
            source=args.source, note=args.note, warehouse=warehouse,
        )
        print(f"[registry] registered; total rows = {n}")
    elif args.subcmd == "import-capital-history":
        result = import_from_capital_history(warehouse, verbose=True)
        print(json.dumps(result, indent=2))
    elif args.subcmd == "remove":
        from vnstock_corp_registry import remove_event
        if not (args.ticker and args.date and args.type):
            print("--ticker, --date, and --type are required for remove",
                  file=sys.stderr)
            return 2
        n = remove_event(args.ticker, args.date, args.type, warehouse=warehouse)
        print(f"[registry] removed {n} row(s) for {args.ticker} {args.date} type={args.type}")
    elif args.subcmd == "clear-source":
        n = clear_source(args.source_to_clear, warehouse=warehouse)
        print(f"[registry] removed {n} row(s) from source={args.source_to_clear}")
    return 0


def cmd_vietstock(args) -> int:
    """Scrape Vietstock for corp actions; optionally register."""
    from vnstock_vietstock import fetch_and_register, fetch_corp_events, _make_session
    warehouse = Path(args.warehouse)

    if args.ticker and not args.bulk:
        if args.register:
            res = fetch_and_register(args.ticker, warehouse=warehouse,
                                     fdate=args.fdate, tdate=args.tdate)
            print(json.dumps(res, indent=2))
        else:
            events = fetch_corp_events(args.ticker, fdate=args.fdate, tdate=args.tdate)
            for e in events:
                print(f"  {e['ex_date']}  {e['type_']:8s}  {e['note'][:80]}")
            print(f"\nTotal: {len(events)} events")
        return 0

    if args.bulk:
        from vnstock_anomaly import _is_stock
        import time
        prices = warehouse / "prices"
        tickers = sorted(
            p.name.removeprefix("ticker=")
            for p in prices.glob("ticker=*")
            if p.is_dir() and _is_stock(p.name.removeprefix("ticker="))
        )
        if args.limit:
            tickers = tickers[: args.limit]
        print(f"[vietstock] processing {len(tickers)} tickers...")
        ok = empty = fail = 0
        sess = _make_session()
        for i, t in enumerate(tickers, 1):
            try:
                if args.register:
                    res = fetch_and_register(t, warehouse=warehouse,
                                             fdate=args.fdate, tdate=args.tdate,
                                             session=sess)
                    if res["fetched"] > 0:
                        ok += 1
                    else:
                        empty += 1
                else:
                    evts = fetch_corp_events(t, fdate=args.fdate, tdate=args.tdate,
                                             session=sess)
                    ok += bool(evts)
                    empty += not bool(evts)
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(tickers)}] {t}: {e}", file=sys.stderr)
            if i % 50 == 0:
                print(f"  progress: {i}/{len(tickers)} ok={ok} empty={empty} fail={fail}")
            time.sleep(0.3)
        print(f"[vietstock] done: ok={ok} empty={empty} fail={fail}")
        return 0

    print("[vietstock] specify --ticker or --bulk", file=sys.stderr)
    return 2


def cmd_cash_dividends(args) -> int:
    """Scrape CafeF for cash dividends; optionally register."""
    from vnstock_cash_dividends import (
        fetch_and_register, fetch_cash_dividends,
    )
    warehouse = Path(args.warehouse)

    if args.ticker and not args.bulk:
        if args.register:
            res = fetch_and_register(args.ticker, warehouse=warehouse,
                                      use_cache=not args.no_cache)
            print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        else:
            events = fetch_cash_dividends(args.ticker, warehouse=warehouse,
                                            use_cache=not args.no_cache)
            for e in events:
                print(f"  {e.ex_date}  {e.cash_amount_vnd:>10,.0f} VND  "
                      f"({e.note[:80]})")
            print(f"\nTotal: {len(events)} cash dividends")
        return 0

    if args.bulk:
        from vnstock_anomaly import _is_stock
        prices = warehouse / "prices"
        tickers = sorted(
            p.name.removeprefix("ticker=")
            for p in prices.glob("ticker=*")
            if p.is_dir() and _is_stock(p.name.removeprefix("ticker="))
        )
        if args.limit:
            tickers = tickers[: args.limit]
        print(f"[cash_div] processing {len(tickers)} tickers...")
        success = empty = fail = 0
        for i, t in enumerate(tickers, 1):
            try:
                if args.register:
                    res = fetch_and_register(
                        t, warehouse=warehouse,
                        use_cache=not args.no_cache,
                    )
                    if res["fetched"] > 0:
                        success += 1
                    else:
                        empty += 1
                else:
                    events = fetch_cash_dividends(
                        t, warehouse=warehouse,
                        use_cache=not args.no_cache,
                    )
                    if events:
                        success += 1
                    else:
                        empty += 1
            except Exception as e:
                fail += 1
                print(f"  [{i}/{len(tickers)}] {t}: {e}", file=sys.stderr)
            if i % 50 == 0:
                print(f"  progress: {i}/{len(tickers)} "
                      f"(ok={success} empty={empty} fail={fail})")
        print(f"[cash_div] done: ok={success} empty={empty} fail={fail}")
        return 0

    print("[cash_div] specify --ticker or --bulk", file=sys.stderr)
    return 2


def cmd_test(args) -> int:
    return _run([sys.executable, "-m", "pytest", "tests/", "-v"])


def cmd_dashboard(args) -> int:
    return _run([sys.executable, "-m", "streamlit", "run", "vnstock_dashboard.py"])


def cmd_all(args) -> int:
    """sync → validate → test → audit. Stops on first hard failure."""
    for name, fn in (
        ("sync", cmd_sync),
        ("validate", cmd_validate),
        ("test", cmd_test),
        ("audit", cmd_audit),
    ):
        print(f"\n=== run.py all :: {name} ===")
        rc = fn(args)
        if rc == 2:
            print(f"[run.py] {name} returned hard failure → stopping")
            return 2
        if rc == 1:
            print(f"[run.py] {name} returned warnings → continuing")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run(cmd: list[str]) -> int:
    """Run a subprocess in the repo root, streaming its output."""
    print(f"[run.py] $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return proc.returncode


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE))
    sub = p.add_subparsers(dest="subcommand", required=True)

    scan = sub.add_parser("scan", help="Collect and print a HealthSnapshot")
    scan.add_argument("--fast", action="store_true",
                      help="Skip per-file row counting and missing-rate (sub-second)")
    scan.add_argument("--verbose", action="store_true",
                      help="Show tqdm progress bar during warehouse scan")
    sub.add_parser("sync", help="Incremental daily updater + rollup")
    sub.add_parser("validate", help="Re-run pandera contracts over full warehouse")

    audit = sub.add_parser("audit", help="Reconciler + anomaly scan")
    audit.add_argument("--lookback", type=int, default=60)
    audit.add_argument("--llm", action="store_true",
                       help="Also ask the Auditor agent for a second opinion")
    audit.add_argument("--auditor", choices=["auto", "claude", "gpt", "null"],
                       default="auto")
    audit.add_argument("--include-non-stocks", action="store_true",
                       help="Include CW / bonds / futures / indices in anomaly scan")
    audit.add_argument("--check-volume", action="store_true",
                       help="Include WSS rolled-volume drift in reconciler severity "
                            "(off by default — WSS volumes are unreliable)")

    refresh = sub.add_parser("refresh-metadata",
                             help="Rebuild exchange_map.json (and optionally corp-action events)")
    refresh.add_argument("--events", action="store_true",
                         help="Also fetch corp-action events per ticker (slow, uses API)")
    refresh.add_argument("--limit", type=int, default=0,
                         help="With --events, process at most N tickers (for testing)")
    refresh.add_argument("--verbose", action="store_true",
                         help="Log source attempts for each ticker")

    rem = sub.add_parser("remediate",
                         help="Refetch / accept / archive specific bars or bulk by kind")
    rem.add_argument("--ticker", help="Single ticker target")
    rem.add_argument("--date", help="Single date target (YYYY-MM-DD)")
    rem.add_argument("--kind", help="Anomaly kind filter (for --all)")
    rem.add_argument("--severity", choices=["fail", "warn"])
    rem.add_argument("--action", choices=["refetch", "accept", "archive", "note"],
                     required=True)
    rem.add_argument("--note", default=None)
    rem.add_argument("--all", action="store_true",
                     help="Apply action to every anomaly in anomalies.json "
                          "matching the kind/severity filters")
    rem.add_argument("--limit", type=int, default=0)
    rem.add_argument("--dry-run", action="store_true")

    top = sub.add_parser("top-offenders",
                          help="Rank tickers by anomaly count")
    top.add_argument("--severity", choices=["fail", "warn"])
    top.add_argument("--by-kind",
                     choices=["band", "ohlc", "gap", "vol_spike",
                              "zero_vol_move"])
    top.add_argument("--limit", type=int, default=20)
    top.add_argument("--json", action="store_true")

    diag = sub.add_parser("diagnose",
                           help="Investigate why a single (ticker, date) was flagged")
    diag.add_argument("--ticker", required=True)
    diag.add_argument("--date", required=True,
                      help="YYYY-MM-DD")
    diag.add_argument("--pad-days", type=int, default=5,
                      help="Show this many days around the target")
    diag.add_argument("--json", action="store_true")

    reg = sub.add_parser("registry",
                          help="Manage the corp_actions_registry.parquet")
    reg.add_argument("subcmd",
                      choices=["show", "add", "remove",
                               "import-capital-history", "clear-source"])
    reg.add_argument("--ticker")
    reg.add_argument("--date", help="YYYY-MM-DD")
    reg.add_argument("--type", help="cash|split|bonus|rights|unknown")
    reg.add_argument("--cash", type=float)
    reg.add_argument("--ratio", type=float)
    reg.add_argument("--source", default="manual")
    reg.add_argument("--source-to-clear")
    reg.add_argument("--note", default=None)

    cash = sub.add_parser("cash-dividends",
                           help="Scrape CafeF for cash dividends")
    cash.add_argument("--ticker")
    cash.add_argument("--bulk", action="store_true")
    cash.add_argument("--limit", type=int, default=0)
    cash.add_argument("--no-cache", action="store_true")
    cash.add_argument("--register", action="store_true",
                      help="Push fetched events into corp_actions_registry")

    vs = sub.add_parser("vietstock", help="Scrape Vietstock for corp actions")
    vs.add_argument("--ticker", help="Single ticker")
    vs.add_argument("--bulk", action="store_true", help="All warehouse tickers")
    vs.add_argument("--limit", type=int, default=0)
    vs.add_argument("--register", action="store_true",
                    help="Push fetched events into corp_actions_registry")
    vs.add_argument("--fdate", default="", help="From date YYYY-MM-DD")
    vs.add_argument("--tdate", default="", help="To date YYYY-MM-DD")

    sub.add_parser("test", help="Run pytest")
    sub.add_parser("dashboard", help="Launch the Streamlit dashboard")

    all_ = sub.add_parser("all", help="sync → validate → test → audit")
    all_.add_argument("--lookback", type=int, default=60)
    all_.add_argument("--llm", action="store_true")
    all_.add_argument("--auditor", choices=["auto", "claude", "gpt", "null"],
                      default="auto")

    return p


_DISPATCH = {
    "scan": cmd_scan,
    "sync": cmd_sync,
    "validate": cmd_validate,
    "audit": cmd_audit,
    "refresh-metadata": cmd_refresh_metadata,
    "remediate": cmd_remediate,
    "top-offenders": cmd_top_offenders,
    "diagnose": cmd_diagnose,
    "registry": cmd_registry,
    "cash-dividends": cmd_cash_dividends,
    "vietstock": cmd_vietstock,
    "test": cmd_test,
    "dashboard": cmd_dashboard,
    "all": cmd_all,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _DISPATCH[args.subcommand]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
