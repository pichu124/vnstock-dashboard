"""
Unified orchestrator for the vnstock-dashboard pipeline.

Replaces the PowerShell-specific Scheduled Task setup with a single, portable
Python entry point that can be driven from cron, Windows Task Scheduler,
GitHub Actions, or manually.

Subcommands
-----------
    python run.py scan       — collect a HealthSnapshot and print it
    python run.py doctor     — health-check EVERY data source feeding the brief
                               (cache ages + config; --net adds live probes)
    python run.py sync       — incremental daily update (updater + rollup)
    python run.py validate   — re-run data contracts on the warehouse
    python run.py audit      — reconciler + anomaly scan, optionally + LLM
    python run.py test       — pytest
    python run.py dashboard  — launch streamlit dashboard
    python run.py all        — sync → validate → screener → news → test → audit
                               → doctor (in order, stopping on first hard
                               failure) --no-news to skip the sentiment step

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
from datetime import date, datetime as _datetime
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


def cmd_doctor(args) -> int:
    """Unified data-source health check (vnstock_doctor).

    Offline by default (cache ages + .env keys, <1s); ``--net`` also probes the
    external sources (RSS feeds, FX API, VBMA PDF, NSO page, foreign-flow API,
    Jina Reader) — run that on a networked machine. Writes
    data_warehouse/_meta/doctor_status.json for the sidebar badge.
    """
    from vnstock_doctor import main as doctor_main

    argv = []
    if getattr(args, "net", False):
        argv.append("--net")
    if getattr(args, "json", False):
        argv.append("--json")
    return doctor_main(argv)


def cmd_sync(args) -> int:
    """Run incremental daily updater, then roll up any intraday bars.

    After the two sub-pipelines succeed, run three automatic self-heal
    passes in order so the warehouse lands clean without any manual
    intervention:

    1. **fix-units** — rescale any raw-VND bars (close > 1000 on a
       normally thousand-VND-range ticker) by /1000 in place.
       Disable with ``--no-fix-units``.
    2. **quarantine auto-heal** — refetch contract-rejected bars;
       archive after ``MAX_RETRIES_DEFAULT`` failures.
       Disable with ``--no-auto-heal``.
    """
    updater = _run([sys.executable, "vnstock_updater.py", "--skip-if-done"])
    if updater != 0:
        return 2
    rollup = _run([sys.executable, "vnstock_rollup.py", "--skip-if-done"])
    if rollup != 0:
        return 2

    if not getattr(args, "no_fix_units", False):
        try:
            from vnstock_fix_units import run as fix_units_run
            report = fix_units_run(Path(args.warehouse), dry_run=False)
            if report.fixes:
                print(f"[sync] fix-units: rescaled {len(report.fixes)} bar(s) "
                      f"across {report.ticker_count} ticker(s)")
        except Exception as exc:
            print(f"[sync] fix-units skipped: {exc}", file=sys.stderr)

    if not getattr(args, "no_auto_heal", False):
        try:
            from vnstock_quarantine import auto_heal
            stats = auto_heal(Path(args.warehouse), verbose=False)
            if stats.get("scanned", 0):
                print(f"[sync] auto-heal: scanned={stats['scanned']} "
                      f"healed={stats['refetched_ok']} "
                      f"retry_bumped={stats['refetched_fail']} "
                      f"archived={stats['archived']} "
                      f"skipped_accepted={stats['skipped_accepted']}")
        except Exception as exc:
            print(f"[sync] auto-heal skipped: {exc}", file=sys.stderr)
    return 0


def cmd_heal(args) -> int:
    """Explicit quarantine auto-heal — refetch retries + archive exhausted."""
    from vnstock_quarantine import auto_heal
    stats = auto_heal(
        Path(args.warehouse),
        max_retries=args.max_retries,
        archive_exhausted=not args.no_archive,
        dry_run=args.dry_run,
        verbose=True,
    )
    print(json.dumps(stats, indent=2))
    return 0 if "error" not in stats else 2


def cmd_validate(args) -> int:
    """Walk the warehouse and run the OHLCV contract on every ticker.

    This is heavier than the inline write-time check because it validates
    the full history, not just newly-ingested rows. Useful after a schema
    change to the contracts or after a bulk load.
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

    # Belt-and-suspenders: replace incomplete WSS minute bars with synthetic
    # bars carrying API-authoritative OHLCV. Keeps _live/ consistent with
    # prices/ so dashboards don't show stale intraday ticks on WSS-fail days.
    if not getattr(args, "no_backfill", False):
        from vnstock_wss_backfill import (
            backfill_rolled_bars, extract_partial_miss,
        )
        partial = extract_partial_miss(recon)
        if partial:
            result = backfill_rolled_bars(warehouse, partial)
            if result["fixed"] > 0:
                print(f"[audit] wss_backfill: {result['fixed']} row(s) "
                      f"synthesised from API (skipped={result['skipped']}, "
                      f"no_api_row={result['no_api_row']})")
                recon = reconcile(
                    warehouse=warehouse,
                    lookback=args.lookback,
                    check_volume=getattr(args, "check_volume", False),
                )
                write_recon(recon, warehouse)
                print(f"[audit] reconciler post-backfill: "
                      f"ok={recon.ok} warn={recon.warn} fail={recon.fail}")

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
            ticker=getattr(args, "ticker", None) or None,
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
            events = fetch_corp_events(args.ticker, fdate=args.fdate, tdate=args.tdate,
                                       verbose=getattr(args, "verbose", False))
            for e in events:
                print(f"  {e['ex_date']}  {e['type_']:8s}  {e['note'][:80]}")
            print(f"\nTotal: {len(events)} events")
        return 0

    if args.bulk:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from vnstock_anomaly import _is_stock
        from vnstock_vietstock import _bulk_worker

        prices = warehouse / "prices"
        tickers = sorted(
            p.name.removeprefix("ticker=")
            for p in prices.glob("ticker=*")
            if p.is_dir() and _is_stock(p.name.removeprefix("ticker="))
        )
        if args.limit:
            tickers = tickers[: args.limit]

        n_workers = max(1, min(getattr(args, "workers", 4), 8))
        print(f"[vietstock] processing {len(tickers)} tickers with {n_workers} workers...")

        chunks: list[list[str]] = [[] for _ in range(n_workers)]
        for i, t in enumerate(tickers):
            chunks[i % n_workers].append(t)

        ok = empty = fail = 0
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    _bulk_worker, chunk,
                    warehouse=warehouse,
                    fdate=args.fdate,
                    tdate=args.tdate,
                    do_register=args.register,
                ): idx
                for idx, chunk in enumerate(chunks)
            }
            for fut in as_completed(futures):
                w_ok, w_empty, w_fail = fut.result()
                ok += w_ok
                empty += w_empty
                fail += w_fail
                done += w_ok + w_empty + w_fail
                print(f"  progress: {done}/{len(tickers)} ok={ok} empty={empty} fail={fail}")

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


def cmd_fix_units(args) -> int:
    """Rescale unit-mismatch OHLC bars (volume=0 with raw-VND prices)."""
    from vnstock_fix_units import run as fix_run

    warehouse = Path(args.warehouse)
    tickers = [args.ticker] if args.ticker else None
    report = fix_run(warehouse, tickers=tickers, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"[fix-units] scanned {report.scanned_tickers} tickers, "
          f"{report.scanned_bars:,} bars")
    print(f"[fix-units] detected {len(report.fixes)} unit-mismatch bar(s) "
          f"across {report.ticker_count} ticker(s)")
    if args.dry_run:
        print("[fix-units] DRY-RUN — no files modified")
    else:
        print(f"[fix-units] rewrote {len(report.fixes)} bar(s) in place")

    if report.fixes:
        preview = report.fixes[: args.limit] if args.limit else report.fixes[:20]
        print(f"\n=== Preview ({len(preview)}/{len(report.fixes)}) ===")
        print(f"{'Ticker':<8} {'Date':<12} {'Before':>12} {'After':>10} "
              f"{'Median':>10}")
        print("─" * 58)
        for f in preview:
            print(f"{f.ticker:<8} {f.time:<12} {f.close_before:>12.2f} "
                  f"{f.close_after:>10.3f} {f.neighbor_median:>10.3f}")
    if report.errors:
        print(f"\n[fix-units] {len(report.errors)} error(s):")
        for t, msg in report.errors[:10]:
            print(f"  {t}: {msg}")
    return 0


def cmd_test(args) -> int:
    """Run pytest. Writes a status summary to data_warehouse/_meta/test_status.json
    so the dashboard can display test health.

    Modes:
      (default) — full tests/ directory
      --fast    — only the 7 test files added in F1-F7 + tune-ups (103 tests, ~0.5s)
      --new     — alias for --fast
    """
    import json as _json
    import subprocess as _sp
    import time as _time

    fast = getattr(args, "fast", False) or getattr(args, "new", False)
    if fast:
        test_paths = [
            "tests/test_regime.py",
            "tests/test_brief.py",
            "tests/test_sentiment.py",
            "tests/test_news_dedup.py",
            "tests/test_freshness.py",
            "tests/test_vn30_weights.py",
            "tests/test_telegram.py",
            "tests/test_events.py",
            "tests/test_macro.py",
            "tests/test_news_feeds.py",
            "tests/test_updater_partial_bar.py",
            "tests/test_doctor.py",
            "tests/test_fred.py",
            "tests/test_ratelimit.py",
            "tests/test_allocation.py",
            "tests/test_reports.py",
            "tests/test_report_digest.py",
            "tests/test_gold.py",
            "tests/test_scorecard.py",
            "tests/test_allocation_reports_tabs.py",
            "tests/test_reflection.py",
            "tests/test_debate.py",
            "tests/test_strategy_validation.py",
        ]
    else:
        test_paths = ["tests/"]

    started = _time.time()
    cmd = [sys.executable, "-m", "pytest", *test_paths, "-v", "--tb=short"]
    proc = _sp.run(cmd, capture_output=True, text=True)
    elapsed = _time.time() - started

    # Echo output verbatim so user still sees the regular pytest run
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)

    # Parse the last "==== N passed, M failed in Xs ====" summary line
    summary_line = ""
    n_passed = n_failed = n_skipped = n_error = 0
    for line in reversed(proc.stdout.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary_line = line.strip()
            break
    import re as _re
    if (m := _re.search(r"(\d+)\s+passed", summary_line)):
        n_passed = int(m.group(1))
    if (m := _re.search(r"(\d+)\s+failed", summary_line)):
        n_failed = int(m.group(1))
    if (m := _re.search(r"(\d+)\s+skipped", summary_line)):
        n_skipped = int(m.group(1))
    if (m := _re.search(r"(\d+)\s+error", summary_line)):
        n_error = int(m.group(1))

    status = {
        "ran_at":   _datetime.now().isoformat(),
        "mode":     "fast" if fast else "full",
        "passed":   n_passed,
        "failed":   n_failed,
        "skipped":  n_skipped,
        "errors":   n_error,
        "elapsed_s": round(elapsed, 1),
        "exit_code": proc.returncode,
        "summary":  summary_line,
    }
    out_path = REPO_ROOT / "data_warehouse" / "_meta" / "test_status.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            _json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[test] status written → {out_path}")
    except OSError as e:
        print(f"[test] could not write status: {e}")

    return proc.returncode


def cmd_dashboard(args) -> int:
    return _run([sys.executable, "-m", "streamlit", "run", "vnstock_dashboard.py"])


def cmd_freefloat(args) -> int:
    """Fetch shareholders() per ticker → compute real freefloat_pct."""
    from vnstock_freefloat import FreefloatUpdater
    updater = FreefloatUpdater(args.warehouse)
    df = updater.run(
        limit=getattr(args, "limit", 0),
        force=getattr(args, "force", False),
        delay=getattr(args, "delay", 0.15),
    )
    return 0 if not df.empty else 1


def cmd_screener(args) -> int:
    """Run vnstock_runner.py to refresh screener signals."""
    return _run([sys.executable, str(REPO_ROOT / "vnstock_runner.py")])


def cmd_foreign_flow(args) -> int:
    """Refresh the FULL-market foreign net-flow per-date cache (NN ròng 1D).

    The brief reads this (vnstock_foreign_flow.load_market_net_1d) instead of the
    Streamlit-only top-100 cache. Best-effort: a network/API miss is a warning,
    not a hard failure.
    """
    days = str(getattr(args, "days", 5) or 5)
    rc = _run([sys.executable, str(REPO_ROOT / "vnstock_foreign_flow.py"),
               "--refresh", "--days", days])
    return 1 if rc != 0 else 0


def cmd_macro(args) -> int:
    """Refresh the macro cache (lãi suất & tỷ giá) — seed/scaffold + auto-fetch FX.

    The brief reads this (vnstock_macro.load_macro) for its "🌐 Vĩ mô" block and
    the macro-pressure sentiment signal. Best-effort: a blocked/failed FX fetch is
    a warning, not a hard failure (the prior cache stays intact). Rates are
    maintained manually via `python vnstock_macro.py --set <key> <value>`.
    """
    rc = _run([sys.executable, str(REPO_ROOT / "vnstock_macro.py"), "--refresh"])
    return 1 if rc != 0 else 0


def cmd_gold(args) -> int:
    """Refresh the international gold-spot cache (display-only, not in the
    macro registry). Best-effort: a blocked fetch keeps the prior cache —
    the scorecard's Vàng proxy just skips missing dates."""
    rc = _run([sys.executable, str(REPO_ROOT / "vnstock_gold.py"), "--refresh"])
    return 1 if rc != 0 else 0


def cmd_allocation(args) -> int:
    """Refresh the asset-allocation band (B0-B4) from existing caches, then
    the retrospective scorecard (both zero LLM).

    vnstock_allocation reads regime/sentiment/breadth/macro caches, applies
    hysteresis + report tilt, persists state + per-day history; the scorecard
    re-marks completed monthly periods + the report-source log. Best-effort:
    missing inputs keep the previous state intact.
    """
    rc = _run([sys.executable, str(REPO_ROOT / "vnstock_allocation.py"),
               "--refresh"])
    _run([sys.executable, str(REPO_ROOT / "vnstock_scorecard.py"), "--refresh"])
    return 1 if rc != 0 else 0


def cmd_reflection(args) -> int:
    """Rút bài học từ rec vừa đóng / kỳ band vừa khép (vnstock_reflection).

    1 call LLM ngắn mỗi outcome mới (trần 3/lượt) → bài học 2-4 câu được bơm
    vào prompt brief sau. Best-effort: không key/không outcome mới = no-op.
    Chạy SAU audit vì reconciler vừa đóng rec xong là lúc có outcome mới.
    """
    rc = _run([sys.executable, str(REPO_ROOT / "vnstock_reflection.py"),
               "--refresh"])
    return 1 if rc != 0 else 0


def cmd_telegram(args) -> int:
    """Push Telegram notifications (test / morning / close / screener)."""
    try:
        import vnstock_telegram as _tg
    except ImportError as e:
        print(f"[telegram] cannot import vnstock_telegram: {e}")
        return 1

    action = args.action
    try:
        if action == "test":
            resp = _tg.push_test()
            print(f"[telegram] test sent — message_id={resp.get('result',{}).get('message_id')}")
        elif action == "morning":
            resp = _tg.push_morning_brief()
            print(f"[telegram] morning brief sent — message_id={resp.get('result',{}).get('message_id')}")
        elif action == "close":
            resp = _tg.push_close_brief()
            print(f"[telegram] close brief sent — message_id={resp.get('result',{}).get('message_id')}")
        elif action == "screener":
            resp = _tg.push_screener_alerts()
            print(f"[telegram] screener sent — message_id={resp.get('result',{}).get('message_id')}")
        else:
            print(f"[telegram] unknown action: {action}")
            return 1
        return 0
    except RuntimeError as e:
        print(f"[telegram] ❌ {e}")
        return 1
    except Exception as e:
        print(f"[telegram] ❌ {type(e).__name__}: {e}")
        return 1


def cmd_news(args) -> int:
    """Refresh news cache + score sentiment.

    Populates the news-sentiment cache the brief's "Tâm lý thị trường" block
    reads (the 7th signal). Safe to schedule daily before the close brief.
    Also called internally by cmd_all; uses getattr so extra args are optional.
    """
    try:
        import vnstock_news as _news
        import vnstock_sentiment as _snt
    except ImportError as e:
        print(f"[news] cannot import: {e}")
        return 1

    # Load .env so provider keys (GROQ/CEREBRAS/OPENROUTER) are available.
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env", override=False)
    except Exception:
        pass

    # 1. Refresh (or load) news
    if getattr(args, "no_refresh", False):
        news = _news.load_news_cache()
        print(f"[news] loaded {len(news)} cached articles")
    else:
        print("[news] refreshing news cache…")
        news = _news.refresh_news()
        print(f"[news] fetched {len(news)} articles")

    if not news:
        print("[news] no articles — nothing to score")
        return 0

    # 2. Score sentiment
    if getattr(args, "no_score", False):
        print("[news] skip scoring (--no-score)")
        return 0

    provider = _snt.available_provider()
    if not provider:
        print("[news] ⚠ chưa có provider key (GROQ/CEREBRAS/OPENROUTER) — bỏ qua chấm điểm")
        return 0

    before = _snt.scored_count(news)
    print(f"[news] scoring sentiment via {provider}… ({before}/{len(news)} đã có)")
    _snt.score_news_batch(news)
    after = _snt.scored_count(news)
    print(f"[news] scored {after - before} mới (tổng {after}/{len(news)})")

    # 3. Market-wide aggregate (what the brief will show)
    _snt.attach_sentiments(news)
    agg = _snt.market_news_sentiment(news, days=7)
    if agg:
        print(f"[news] tâm lý 7N: {agg['pos_pct']:.0f}% tích cực / "
              f"{agg['neg_pct']:.0f}% tiêu cực "
              f"(net {agg['net_pct']:+.0f}, {agg['total']} tin)")

    # 4. Broad economic/political news via RSS (market-moving macro/geopolitics) —
    #    separate from the per-ticker news above. Best-effort; the brief's
    #    "📰 Tin kinh tế/chính trị" block + LLM impact read this cache.
    if not getattr(args, "no_refresh", False):
        try:
            import vnstock_news_feeds as _nf
            items = _nf.refresh(analyze=not getattr(args, "no_score", False))
            n_an = sum(1 for it in items if it.get("_impact"))
            print(f"[news] market feeds (RSS): {len(items)} tin liên quan, "
                  f"{n_an} đã phân tích tác động")
        except Exception as e:
            print(f"[news] market feeds skipped: {type(e).__name__}: {e}")
    return 0


def cmd_all(args) -> int:
    """sync → validate → screener → news → foreign-flow → macro → allocation
    → test → audit → doctor. Stops on first hard failure. The trailing doctor
    pass is offline-only and just refreshes doctor_status.json so the sidebar
    badge stays current."""
    steps: list[tuple[str, object]] = [
        ("sync",         cmd_sync),
        ("validate",     cmd_validate),
        ("screener",     cmd_screener),
        ("foreign-flow", cmd_foreign_flow),
        ("macro",        cmd_macro),
        ("gold",         cmd_gold),
        ("allocation",   cmd_allocation),
        ("test",         cmd_test),
        ("audit",        cmd_audit),
        ("reflection",   cmd_reflection),
        ("doctor",       cmd_doctor),
    ]
    # Insert news after screener unless the caller opts out
    if not getattr(args, "no_news", False):
        steps.insert(3, ("news", cmd_news))

    for name, fn in steps:
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

    doctor = sub.add_parser(
        "doctor",
        help="Khám sức khỏe MỌI nguồn dữ liệu của brief (tuổi cache + key; "
             "--net probe mạng)")
    doctor.add_argument("--net", action="store_true",
                        help="Thêm probe mạng: RSS/FX/VBMA/NSO/foreign-flow/Jina")
    doctor.add_argument("--json", action="store_true",
                        help="In JSON thay vì báo cáo text")

    sync = sub.add_parser("sync", help="Incremental daily updater + rollup")
    sync.add_argument("--no-fix-units", action="store_true",
                       help="Skip the post-sync fix-units pass "
                            "(raw-VND rescale)")
    sync.add_argument("--no-auto-heal", action="store_true",
                       help="Skip the post-sync quarantine auto-heal pass")
    sub.add_parser("validate", help="Re-run data contracts over full warehouse")

    heal = sub.add_parser("heal",
                           help="Auto-heal quarantine: refetch retries, "
                                "archive after MAX_RETRIES failures")
    heal.add_argument("--max-retries", type=int, default=3,
                      help="Archive after this many failed refetches (default: 3)")
    heal.add_argument("--no-archive", action="store_true",
                      help="Never archive — only bump retry counters")
    heal.add_argument("--dry-run", action="store_true",
                      help="Report what would happen without mutating state")

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
    audit.add_argument("--no-backfill", action="store_true",
                       help="Skip the WSS partial-miss auto-backfill step "
                            "(default: backfill enabled)")

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
    vs.add_argument("--workers", type=int, default=4,
                    help="Parallel workers for --bulk (default: 4, max: 8)")
    vs.add_argument("--verbose", action="store_true", help="Print HTTP debug info")

    fix = sub.add_parser("fix-units",
                         help="Rescale unit-mismatch OHLC bars (volume=0 + raw-VND price)")
    fix.add_argument("--ticker", help="Restrict to a single ticker")
    fix.add_argument("--dry-run", action="store_true",
                     help="Report what would be fixed without writing files")
    fix.add_argument("--json", action="store_true",
                     help="Machine-readable JSON output")
    fix.add_argument("--limit", type=int, default=0,
                     help="Cap preview rows (default: 20)")

    ff = sub.add_parser("freefloat",
                        help="Fetch shareholders() per ticker → store real freefloat_pct")
    ff.add_argument("--limit", type=int, default=0,
                    help="Process at most N tickers (0 = all)")
    ff.add_argument("--force", action="store_true",
                    help="Re-fetch tickers that already have data")
    ff.add_argument("--delay", type=float, default=0.15,
                    help="Delay between API calls in seconds (default 0.15)")

    test = sub.add_parser("test", help="Run pytest + write status to test_status.json")
    test.add_argument("--fast", action="store_true",
                      help="Only run the 7 test files for new modules (~103 tests, 0.5s)")
    test.add_argument("--new", action="store_true",
                      help="Alias for --fast")
    sub.add_parser("screener", help="Refresh screener signals (vnstock_runner.py)")
    ff_nn = sub.add_parser("foreign-flow",
                           help="Refresh full-market foreign net-flow cache (NN ròng 1D)")
    ff_nn.add_argument("--days", type=int, default=5)
    sub.add_parser("macro",
                   help="Refresh macro cache (lãi suất & tỷ giá) — seed + auto-fetch FX")
    sub.add_parser("allocation",
                   help="Refresh asset-allocation band B0-B4 + scorecard")
    sub.add_parser("gold",
                   help="Refresh gold-spot cache (display-only, vnstock_gold.py)")
    sub.add_parser("reflection",
                   help="Rút bài học từ rec/kỳ band đã đóng (vnstock_reflection.py)")
    sub.add_parser("dashboard", help="Launch the Streamlit dashboard")

    tg = sub.add_parser("telegram", help="Push Telegram notifications")
    tg.add_argument(
        "action",
        choices=["test", "morning", "close", "screener"],
        help="test=verify connection, morning=morning brief, close=close brief, screener=alerts only",
    )

    news_p = sub.add_parser(
        "news", help="Refresh tin + chấm sentiment (cho tín hiệu tâm lý tin tức trong brief)")
    news_p.add_argument("--no-refresh", action="store_true",
                        help="Bỏ qua fetch tin, chỉ chấm điểm cache hiện có")
    news_p.add_argument("--no-score", action="store_true",
                        help="Chỉ refresh tin, không chấm sentiment")

    all_ = sub.add_parser(
        "all", help="sync → validate → screener → news → test → audit → doctor")
    all_.add_argument("--lookback", type=int, default=60)
    all_.add_argument("--llm", action="store_true")
    all_.add_argument("--auditor", choices=["auto", "claude", "gpt", "null"],
                      default="auto")
    all_.add_argument("--no-news", action="store_true",
                      help="Skip the news sentiment refresh step")

    return p


_DISPATCH = {
    "scan": cmd_scan,
    "doctor": cmd_doctor,
    "sync": cmd_sync,
    "heal": cmd_heal,
    "validate": cmd_validate,
    "audit": cmd_audit,
    "refresh-metadata": cmd_refresh_metadata,
    "remediate": cmd_remediate,
    "top-offenders": cmd_top_offenders,
    "diagnose": cmd_diagnose,
    "registry": cmd_registry,
    "cash-dividends": cmd_cash_dividends,
    "vietstock": cmd_vietstock,
    "fix-units": cmd_fix_units,
    "freefloat": cmd_freefloat,
    "screener": cmd_screener,
    "foreign-flow": cmd_foreign_flow,
    "macro": cmd_macro,
    "gold": cmd_gold,
    "allocation": cmd_allocation,
    "reflection": cmd_reflection,
    "telegram": cmd_telegram,
    "news": cmd_news,
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
