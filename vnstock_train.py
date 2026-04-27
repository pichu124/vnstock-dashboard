"""
vnstock_train.py — Training/improvement orchestration for AI brief agents.

Two improvement loops:

  brief_loop()    — pull recent rated briefs, identify high-rated outputs,
                    save them as "golden examples", update prompt versions.
                    Also extracts data-gap suggestions from agent reasoning.

  strategy_loop() — for each enabled agent, run develop_and_backtest()
                    to evolve a trading strategy. Best validated ones become
                    candidates for emit_recommendations() in next brief.

CLI
---
  python vnstock_train.py --once          # run both loops once
  python vnstock_train.py --briefs-only   # only refresh few-shot pool
  python vnstock_train.py --strategy-only # only run strategy evolution
  python vnstock_train.py --schedule      # daemonize with internal scheduler

For real cron, prefer system cron + --once:
  0 16 * * 1-5 cd /path && python vnstock_train.py --once
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import vnstock_memory as mem


# ── Auto-scoring (specificity heuristic) ───────────────────────────────────
_NUM_PATTERN = re.compile(r"[+-]?\d+(?:[.,]\d+)?\s*(?:%|pp|tỷ|triệu|VND|nghìn)?")
_TICKER_PATTERN = re.compile(r"\b[A-Z]{3}\b")


def auto_score_brief(text: str) -> float:
    """Score 0..1 based on density of concrete numbers/tickers vs filler.

    Used as a tie-breaker when no human rating exists.
    """
    if not text or len(text) < 50:
        return 0.0
    n_chars = len(text)
    n_nums = len(_NUM_PATTERN.findall(text))
    n_tickers = len(_TICKER_PATTERN.findall(text))
    # density per 100 chars
    num_density = n_nums / (n_chars / 100)
    tk_density  = n_tickers / (n_chars / 100)

    # filler phrases that signal vagueness
    fillers = (
        "diễn biến tích cực", "diễn biến tiêu cực", "thị trường khả quan",
        "tâm lý chung", "có thể", "có khả năng", "nhìn chung",
        "cần theo dõi thêm", "chưa rõ ràng", "biến động đáng kể",
    )
    n_fillers = sum(text.lower().count(f) for f in fillers)

    score = (
        min(num_density / 3.0, 1.0) * 0.5
        + min(tk_density / 1.5, 1.0) * 0.3
        + max(0, 1 - n_fillers / 5) * 0.2
    )
    return round(score, 3)


# ── Brief loop: refresh few-shot pool + extract data gaps ──────────────────
def brief_loop(verbose: bool = True) -> dict:
    """Compute auto-scores for unscored briefs, refresh prompt stats."""
    mem.init_db()
    summary = {"scored": 0, "skipped": 0}

    recents = mem.recent_briefs(limit=200)
    for b in recents:
        if b.get("auto_score") is not None:
            summary["skipped"] += 1
            continue
        out = b.get("output") or ""
        if not out:
            summary["skipped"] += 1
            continue
        s = auto_score_brief(out)
        with mem._conn() as c:
            c.execute("UPDATE briefs SET auto_score=? WHERE id=?", (s, b["id"]))
        summary["scored"] += 1

    mem.refresh_prompt_stats()
    if verbose:
        print(f"[brief_loop] scored={summary['scored']} skipped={summary['skipped']}")
    return summary


# ── Strategy loop: evolve strategies per agent ─────────────────────────────
def _get_universe(top_n: int = 30) -> list[str]:
    """Pick a universe to backtest on. Default: VN30."""
    try:
        from vnstock_brief import VN30_TICKERS
        return sorted(VN30_TICKERS)[:top_n]
    except Exception:
        return ["VCB", "FPT", "HPG", "VHM", "VIC", "MSN", "MWG", "VNM",
                "TCB", "VPB", "MBB", "ACB", "CTG", "BID", "GAS"]


def _build_context_summary() -> str:
    """One-shot snapshot to seed strategy generation prompt."""
    try:
        from vnstock_brief import collect_context
        ctx = collect_context("morning")
        regime = ctx.get("quant_regime", {}).get("regime", "unknown")
        breadth = ctx.get("breadth", {})
        return (
            f"Regime: {regime} | "
            f"Trên MA200: {breadth.get('above_ma200_pct', 0):.0f}% | "
            f"A/D: {breadth.get('ad_ratio', 0):.2f}"
        )
    except Exception:
        return "VN large-cap, daily timeframe"


def strategy_loop(
    n_iterations: int = 2,
    universe_size: int = 15,
    verbose: bool = True,
    lite: bool = False,
) -> dict:
    """For each enabled agent: develop + backtest + persist a strategy.

    Args:
        lite: If True, use a smaller backtest config (5 tickers, fewer
              windows) — completes in ~30-60s instead of ~8 min on Windows.
              Use for UI-triggered runs and smoke tests.
    """
    from vnstock_brief import build_agents
    from vnstock_strategy import develop_and_backtest, lite_config

    agents = build_agents()
    if not agents:
        if verbose:
            print("[strategy_loop] No agents enabled — skipping")
        return {"agents_run": 0, "validated": 0}

    universe = _get_universe(universe_size)
    context_summary = _build_context_summary()
    cfg = lite_config(universe) if lite else None

    summary = {"agents_run": 0, "validated": 0, "errors": []}

    for ag in agents:
        if not ag.is_available:
            if verbose:
                print(f"[strategy_loop] {ag.name}: API key missing, skip")
            continue
        if verbose:
            print(f"[strategy_loop] {ag.name}: developing strategy "
                  f"({'lite' if lite else 'full'})...")
        try:
            sid, metrics = develop_and_backtest(
                ag, universe=universe,
                context_summary=context_summary,
                n_iterations=n_iterations,
                cfg=cfg,
            )
            summary["agents_run"] += 1
            if sid is None:
                if verbose:
                    print(f"  → failed: {metrics.get('error')}")
                continue
            s = mem.get_strategy(sid)
            if s and s.get("status") == "validated":
                summary["validated"] += 1
            if verbose:
                print(
                    f"  → strategy_id={sid} status={s.get('status') if s else 'n/a'} "
                    f"trades={metrics.get('n_trades')} "
                    f"expectancy={metrics.get('expectancy')}"
                )
        except Exception as e:
            err = f"{ag.name}: {type(e).__name__}: {e}"
            summary["errors"].append(err)
            if verbose:
                print(f"  → error: {err}")
                traceback.print_exc()
    return summary


# ── Outcome reconciliation: close recs whose horizon expired ───────────────
def reconcile_recommendations(verbose: bool = True) -> dict:
    """For each open rec older than horizon_days, fetch latest close and grade."""
    from vnstock_strategy import _load_history

    open_recs = mem.open_recommendations()
    summary = {"closed": 0, "still_open": 0}

    for r in open_recs:
        try:
            created = datetime.fromisoformat(r["created_at"])
        except Exception:
            continue
        age_days = (datetime.now() - created).days
        horizon = int(r.get("horizon_days") or 5)
        if age_days < horizon:
            summary["still_open"] += 1
            continue
        hist = _load_history(r["ticker"], days=horizon + 10)
        if hist.empty:
            summary["still_open"] += 1
            continue
        # Find bar after creation, walk forward up to horizon bars
        try:
            tcol = hist["time"].dt.date.astype(str)
        except Exception:
            continue
        post = hist[tcol > created.date().isoformat()].head(horizon)
        if post.empty:
            summary["still_open"] += 1
            continue

        entry = float(r["entry_price"] or 0)
        tp    = float(r["take_profit"] or 0)
        sl    = float(r["cut_loss"] or 0)
        exit_price = float(post["close"].iloc[-1])
        hit = "expire"
        if entry > 0:
            for _, bar in post.iterrows():
                hi, lo = float(bar["high"]), float(bar["low"])
                if sl > 0 and lo <= sl:
                    exit_price, hit = sl, "sl"
                    break
                if tp > 0 and hi >= tp:
                    exit_price, hit = tp, "tp"
                    break
        mem.close_recommendation(r["id"], exit_price=exit_price, hit_target=hit)
        summary["closed"] += 1

    if verbose:
        print(f"[reconcile] closed={summary['closed']} still_open={summary['still_open']}")
    return summary


# ── Run-once orchestrator ──────────────────────────────────────────────────
def run_once(briefs: bool = True, strategy: bool = True,
             reconcile: bool = True, verbose: bool = True,
             lite: bool = False) -> dict:
    out: dict = {"started_at": datetime.now().isoformat(timespec="seconds")}
    if briefs:
        out["brief_loop"] = brief_loop(verbose=verbose)
    if reconcile:
        out["reconcile"] = reconcile_recommendations(verbose=verbose)
    if strategy:
        out["strategy_loop"] = strategy_loop(verbose=verbose, lite=lite)
    out["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return out


# ── Lightweight in-process scheduler (alternative to system cron) ──────────
def schedule_loop(interval_hours: float = 24, verbose: bool = True) -> None:
    """Run once, then sleep, then repeat. Stop with Ctrl+C."""
    while True:
        try:
            run_once(verbose=verbose)
        except KeyboardInterrupt:
            print("[schedule_loop] stopped by user")
            return
        except Exception as e:
            print(f"[schedule_loop] error: {e}")
            traceback.print_exc()
        sleep_s = max(60, int(interval_hours * 3600))
        if verbose:
            print(f"[schedule_loop] sleeping {sleep_s}s before next run...")
        try:
            time.sleep(sleep_s)
        except KeyboardInterrupt:
            print("[schedule_loop] stopped by user")
            return


# ── CLI ────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI brief training/improvement orchestrator"
    )
    parser.add_argument("--once", action="store_true",
                        help="Run all loops once and exit (default).")
    parser.add_argument("--briefs-only", action="store_true",
                        help="Only refresh few-shot pool / auto-scores.")
    parser.add_argument("--strategy-only", action="store_true",
                        help="Only run strategy evolution loop.")
    parser.add_argument("--reconcile-only", action="store_true",
                        help="Only close expired recommendations.")
    parser.add_argument("--schedule", action="store_true",
                        help="Run in a loop with --interval-hours sleep.")
    parser.add_argument("--interval-hours", type=float, default=24,
                        help="Sleep between iterations when --schedule (default 24).")
    parser.add_argument("--quiet", action="store_true", help="Suppress logs.")
    parser.add_argument("--lite", action="store_true",
                        help="Use a smaller backtest window (5 tickers, ~30s) "
                             "instead of full (15 tickers, ~8 min on Windows).")
    args = parser.parse_args(argv)

    verbose = not args.quiet

    # Auto-load .env so API keys are available outside Streamlit
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env", override=False)
    except ImportError:
        pass

    if args.schedule:
        schedule_loop(interval_hours=args.interval_hours, verbose=verbose)
        return 0

    if args.briefs_only:
        brief_loop(verbose=verbose)
    elif args.strategy_only:
        strategy_loop(verbose=verbose, lite=args.lite)
    elif args.reconcile_only:
        reconcile_recommendations(verbose=verbose)
    else:
        run_once(verbose=verbose, lite=args.lite)
    return 0


if __name__ == "__main__":
    sys.exit(main())
