"""
vnstock_train.py — Training/improvement orchestration for AI brief agents.

Two improvement loops:

  brief_loop()    — compute auto-scores (specificity heuristic) for recent
                    unscored briefs, feeding the few-shot/rating pool.

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
from datetime import datetime
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

    if verbose:
        print(f"[brief_loop] scored={summary['scored']} skipped={summary['skipped']}")
    return summary


# ── Strategy loop: evolve strategies per agent ─────────────────────────────

# ── Training universe — dynamic stratified selection ───────────────────────
#
# Hardcoded lists below are FALLBACKS only — used when the vnstock API is
# unreachable or the local price warehouse is empty.
# At runtime, _training_universe() fetches the live VN30/VNMID composition
# and re-ranks candidates by recent average volume, so the universe
# automatically adapts to quarterly index reviews and liquidity shifts.

# Sector map for current VN30 — used for sector-stratified Lite selection.
# Supplemented (or overridden) by industry_classification.parquet when available.
_VN30_SECTOR_MAP: dict[str, str] = {
    # Ngân hàng
    "ACB": "bank", "BID": "bank", "CTG": "bank", "HDB": "bank",
    "MBB": "bank", "SHB": "bank", "SSB": "bank", "STB": "bank",
    "TCB": "bank", "TPB": "bank", "VCB": "bank", "VIB": "bank", "VPB": "bank",
    # Bảo hiểm
    "BVH": "insurance",
    # Chứng khoán
    "SSI": "securities",
    # Bất động sản
    "BCM": "realestate", "VHM": "realestate", "VRE": "realestate",
    # Công nghệ
    "FPT": "tech",
    # Năng lượng / dầu khí
    "GAS": "energy", "PLX": "energy", "POW": "energy",
    # Vật liệu / thép / cao su
    "HPG": "materials", "GVR": "materials",
    # Tiêu dùng
    "MSN": "consumer", "MWG": "consumer", "SAB": "consumer", "VNM": "consumer",
    # Tập đoàn / đa ngành
    "VIC": "conglomerate",
    # Vận tải / dịch vụ hàng không
    "VJC": "transport",
}

# Fallback VNMID list — 20 mã đa ngành, dùng khi API lỗi.
# Tự động bỏ mã đã vào VN30 khi build universe.
_VNMID_FALLBACK: list[str] = [
    "GMD", "HAH", "TCH",        # Logistics / cảng
    "PNJ", "KDC",               # Bán lẻ / tiêu dùng
    "VHC", "ANV",               # Thực phẩm / thủy sản
    "NLG", "DXG", "KDH",        # Bất động sản mid
    "HSG", "NKG",               # Thép mid
    "DGC", "DPM", "GEX",        # Hóa chất / công nghiệp
    "VIX",                      # Chứng khoán
    "BWE", "REE",               # Hạ tầng / tiện ích
    "PHR",                      # Cao su
    "VGC",                      # Vật liệu xây dựng
]
_VNMID_LITE_FALLBACK: list[str] = ["GMD", "PNJ", "NLG", "HSG", "VHC", "DGC", "VIX"]


# ── Universe helper functions ──────────────────────────────────────────────

def _fetch_group_live(group: str) -> list[str]:
    """Fetch current index group composition from vnstock API.

    Returns empty list on any error (caller should use fallback).
    """
    try:
        from vnstock_auth import get_vnstock
        df = get_vnstock("VCB", "VCI").listing.symbols_by_group(group)
        if df is not None and not df.empty:
            col = next((c for c in ("ticker", "symbol", "code") if c in df.columns), None)
            if col:
                tickers = [str(v).strip().upper() for v in df[col] if v]
                if len(tickers) >= 10:
                    return tickers
    except Exception:
        pass
    return []


def _avg_volume_30d(ticker: str) -> float:
    """Return 30-day average daily volume from local parquet warehouse.

    Reads only the 'volume' column from the most recent parquet file(s),
    so it's fast (column projection). Returns 0.0 if data is unavailable.
    """
    try:
        import pyarrow.parquet as pq
        import pandas as pd
        td = Path("data_warehouse/prices") / f"ticker={ticker.upper()}"
        parquets = sorted(td.glob("**/*.parquet"))
        if not parquets:
            return 0.0
        frames = []
        # Last 2 year-files is enough to cover 30 trading days
        for p in parquets[-2:]:
            try:
                frames.append(pq.read_table(str(p), columns=["volume"]).to_pandas())
            except Exception:
                pass
        if not frames:
            return 0.0
        return float(pd.concat(frames)["volume"].tail(30).mean())
    except Exception:
        return 0.0


def _rank_by_volume(tickers: list[str], n: int) -> list[str]:
    """Return top-n tickers sorted by descending 30-day avg volume."""
    if not tickers:
        return []
    scored = sorted(tickers, key=_avg_volume_30d, reverse=True)
    return scored[:n]


def _load_sector_map(tickers: list[str]) -> dict[str, str]:
    """Merge hardcoded VN30 sector map with industry_classification.parquet (if exists)."""
    sector_map: dict[str, str] = dict(_VN30_SECTOR_MAP)
    try:
        import pyarrow.parquet as pq
        p = Path("data_warehouse/_meta/industry_classification.parquet")
        if p.exists():
            df = pq.read_table(str(p)).to_pandas()
            # Accept common column name variants
            tcol = next((c for c in ("ticker", "symbol", "code") if c in df.columns), None)
            scol = next((c for c in ("sector", "industry", "icb_name2") if c in df.columns), None)
            if tcol and scol:
                for _, row in df.iterrows():
                    t = str(row[tcol]).strip().upper()
                    s = str(row[scol]).strip().lower()
                    if t:
                        sector_map[t] = s
    except Exception:
        pass
    return sector_map


def _sector_stratified(tickers: list[str], n: int) -> list[str]:
    """Pick n tickers ensuring sector diversity.

    Algorithm:
      1. Group tickers by sector (via _load_sector_map).
      2. Within each sector, prefer higher 30-day avg volume.
      3. Banks are capped at max(1, n//3) slots to avoid cluster dominance.
      4. Every other sector gets 1 slot minimum.
      5. Remaining slots go to the highest-volume tickers not yet selected.

    Works even with zero volume data — sector diversity is preserved by
    the 1-per-sector rule, which is volume-independent.
    """
    if not tickers:
        return []
    if n >= len(tickers):
        return list(tickers)

    sector_map = _load_sector_map(tickers)

    # Group and rank within sector by volume
    by_sector: dict[str, list[str]] = {}
    for t in tickers:
        s = sector_map.get(t, "other")
        by_sector.setdefault(s, []).append(t)
    ranked_by_sector: dict[str, list[str]] = {
        s: _rank_by_volume(ts, len(ts)) for s, ts in by_sector.items()
    }

    selected: list[str] = []
    bank_cap = max(1, n // 3)  # e.g. n=10 → 3 bank slots, n=30 → 10

    # Pass 1: allocate per-sector slots
    for sector, ranked in ranked_by_sector.items():
        cap = bank_cap if sector == "bank" else 1
        for t in ranked[:cap]:
            if t not in selected:
                selected.append(t)
        if len(selected) >= n:
            return selected[:n]

    # Pass 2: fill remaining with highest-volume across all tickers
    all_ranked = _rank_by_volume(tickers, len(tickers))
    for t in all_ranked:
        if t not in selected:
            selected.append(t)
        if len(selected) >= n:
            break

    return selected[:n]


def _training_universe(lite: bool = False) -> list[str]:
    """Build a dynamic stratified training universe.

    Sources (evaluated at call time, not at import time):
      1. Live vnstock API → symbols_by_group('VN30' / 'VNMID')
      2. Hardcoded fallbacks (_VNMID_FALLBACK, vnstock_brief.VN30_TICKERS)

    Selection logic:
      • VN30 Lite  : sector-stratified top-10 by volume (max 3 banks,
                     1 slot per other sector) → diverse even without vol data
      • VNMID Lite : top-7 by 30-day avg volume from live VNMID roster
      • VN30 Full  : all available VN30 tickers (sorted)
      • VNMID Full : top-20 by 30-day avg volume from live VNMID roster

    Tickers in VNMID that got promoted to VN30 are automatically removed.
    Tickers not yet in the local price warehouse are filtered out (unless
    the warehouse is empty, in which case the full live/fallback list is used).

    lite=False  →  VN30 all + VNMID top-20  ≈ 50 mã  (~15-25 phút)
    lite=True   →  VN30 top-10 (sector) + VNMID top-7  = ~17 mã  (~60-90s)
    """
    # ── 1. Fetch current index compositions ────────────────────────────────
    vn30_live = _fetch_group_live("VN30")
    try:
        from vnstock_brief import VN30_TICKERS as _vn30_fb
        vn30_fallback = sorted(_vn30_fb)
    except Exception:
        vn30_fallback = sorted(_VN30_SECTOR_MAP.keys())
    vn30 = vn30_live if vn30_live else vn30_fallback
    vn30_set = set(vn30)

    vnmid_live = _fetch_group_live("VNMID")
    vnmid_candidates = [
        t for t in (vnmid_live if vnmid_live else _VNMID_FALLBACK)
        if t not in vn30_set
    ]

    # ── 2. Filter to tickers available in warehouse ────────────────────────
    warehouse = set(_scan_universe())
    # When warehouse is empty, skip filtering (use full live/fallback list)
    if warehouse:
        vn30_avail  = [t for t in vn30            if t in warehouse]
        vnmid_avail = [t for t in vnmid_candidates if t in warehouse]
    else:
        vn30_avail  = []   # triggers fallback to full live list below
        vnmid_avail = []

    # ── 3. Select subset ───────────────────────────────────────────────────
    if lite:
        # VN30: sector-stratified top-10 (adapts to volume changes + index changes)
        vn30_pool = vn30_avail if vn30_avail else vn30
        vn30_sel  = _sector_stratified(vn30_pool, n=10)

        # VNMID: top-7 by volume; fallback to hardcoded if no warehouse data
        vnmid_sel = (_rank_by_volume(vnmid_avail, n=7)
                     if vnmid_avail else list(_VNMID_LITE_FALLBACK))

        selected = vn30_sel + [t for t in vnmid_sel if t not in set(vn30_sel)]

    else:
        # Full VN30
        vn30_sel = vn30_avail if vn30_avail else vn30

        # VNMID top-20 by volume; fallback to hardcoded
        vnmid_sel = (_rank_by_volume(vnmid_avail, n=20)
                     if vnmid_avail else [t for t in _VNMID_FALLBACK if t not in vn30_set])

        selected = list(vn30_sel) + [t for t in vnmid_sel if t not in vn30_set]

    return selected


def _scan_universe() -> list[str]:
    """All tickers present in the price data warehouse.

    Used by emit_recommendations() to scan the broadest possible set of stocks.
    Tickers with insufficient history (<60 bars) are silently skipped by the caller.
    Returns [] when the warehouse is empty (no circular fallback to _training_universe).
    """
    prices_dir = Path("data_warehouse/prices")
    if not prices_dir.exists():
        return []
    tickers = sorted(
        d.name.split("=", 1)[-1].upper()
        for d in prices_dir.glob("ticker=*")
        if "=" in d.name and d.is_dir()
    )
    return tickers




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
    verbose: bool = True,
    lite: bool = False,
    mode: str = "auto",
    tier: str = "short",
) -> dict:
    """Adaptive strategy training shared across all enabled agents.

    Modes:
      auto    — choose tune (daily) vs revise (weekly) based on stability
      tune    — daily tune of params (every agent contributes, best wins)
      revise  — weekly rewrite of core code by lead agent
      fresh   — cold-start a brand new strategy family

    All enabled agents share one strategy family (cross-agent knowledge).
    Lead agent for revise/cold-start = first available agent (typically
    Claude > OpenAI > Groq > Mistral order from config).

    Args:
        lite: use 10 diverse tickers + smaller backtest window (~30-60s)
              False: full VN30 (~30 tickers, 5-15 min)
        mode: see above. "auto" delegates to develop_and_backtest's logic.
    """
    from vnstock_brief import build_agents
    from vnstock_strategy import develop_and_backtest, lite_config

    agents = build_agents()
    available = [a for a in agents if a.is_available]
    if not available:
        if verbose:
            print("[strategy_loop] No agents with valid API key — skipping")
        return {"agents_run": 0, "validated": 0}

    universe = _training_universe(lite=lite)
    context_summary = _build_context_summary()
    cfg = lite_config(universe) if lite else None

    lead = available[0]   # for revise / cold start
    pool = available[1:]  # extra agents for tune competition

    if verbose:
        names = ", ".join(a.name for a in available)
        print(f"[strategy_loop] mode={mode} lite={lite} | agents: {names} "
              f"| lead={lead.name}")

    summary: dict = {"agents_run": len(available), "validated": 0,
                     "mode": mode, "errors": []}
    try:
        sid, metrics = develop_and_backtest(
            lead,
            universe=universe,
            context_summary=context_summary,
            n_iterations=n_iterations,
            cfg=cfg,
            mode=mode,
            extra_agents=pool,
            tier=tier,
        )
        if sid is None:
            if verbose:
                print(f"  → failed: {metrics.get('error')}")
            summary["errors"].append(metrics.get("error", "unknown"))
        else:
            s = mem.get_strategy(sid)
            if s and s.get("status") in ("validated", "active"):
                summary["validated"] += 1
            if verbose:
                print(
                    f"  → strategy_id={sid} status={s.get('status') if s else 'n/a'} "
                    f"trades={metrics.get('n_trades')} "
                    f"expectancy={metrics.get('expectancy')}"
                )
                # "active" chỉ là ghế làm việc, KHÔNG phải phán quyết — phán
                # quyết là kiểm định, và nó quyết brief có nhận rec hay không
                # (13/08: user chạy cold-start xong không biết đạt hay trượt
                # vì dòng trên không nói).
                _mix = metrics.get("exit_mix") or {}
                if _mix:
                    print(f"     exit mix: TP {_mix.get('tp', 0):.0%} · "
                          f"SL {_mix.get('sl', 0):.0%} · "
                          f"hết hạn {_mix.get('expire', 0):.0%}")
                _v = metrics.get("validation")
                if _v is None:
                    print("     kiểm định: ⏳ chưa đủ lệnh để chấm")
                elif _v.get("passed"):
                    _p = _v.get("p_value_adj", _v.get("p_value_sharpe"))
                    print(f"     kiểm định: ✅ ĐẠT (p={_p:.3f})"
                          if isinstance(_p, float) else "     kiểm định: ✅ ĐẠT")
                    print("     → khuyến nghị của chiến lược này SẼ vào brief")
                else:
                    print("     kiểm định: 🎲 CHƯA ĐẠT — "
                          + "; ".join(_v.get("reasons") or ["?"]))
                    print("     → brief sẽ KHÔNG nhận khuyến nghị từ chiến lược "
                          "này (vẫn ghi sổ + đối soát để nó tự chứng minh)")
    except Exception as e:
        err = f"{lead.name}: {type(e).__name__}: {e}"
        summary["errors"].append(err)
        if verbose:
            print(f"  → error: {err}")
            traceback.print_exc()
    return summary


# ── Outcome reconciliation: close recs whose horizon expired ───────────────
# A rec this far past its horizon with no fetchable price history is treated as
# a zombie (delisted ticker, covered warrant, symbol the warehouse can't serve)
# and force-closed as "stale" so it stops lingering as an open recommendation.
STALE_GRACE_DAYS = 10


def _grade_rec(post, entry: float, tp: float, sl: float) -> tuple[float, str]:
    """Walk-forward các bar sau ngày tạo rec (lệnh MUA) → (exit_price, hit).

    Bar chứa CẢ TP lẫn SL → thứ tự theo `_bar_high_first` (heuristic
    nautilus: cực trị gần open chạm trước); không quyết được → SL thắng
    (pessimistic). PnL rec thật vẫn GROSS (convention DB không đổi —
    backtest thì đã trừ phí, xem _cost_roundtrip_pct)."""
    from vnstock_strategy import _bar_high_first

    exit_price = float(post["close"].iloc[-1])
    hit = "expire"
    if entry <= 0:
        return exit_price, hit
    for _, bar in post.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        sl_hit = sl > 0 and lo <= sl
        tp_hit = tp > 0 and hi >= tp
        if sl_hit and tp_hit:
            if _bar_high_first(bar):        # high (TP) chạm trước
                return tp, "tp"
            return sl, "sl"
        if sl_hit:
            return sl, "sl"
        if tp_hit:
            return tp, "tp"
    return exit_price, hit


def reconcile_recommendations(verbose: bool = True) -> dict:
    """For each open rec older than horizon_days, fetch latest close and grade.

    Recs whose price history can't be fetched and that are well past horizon
    (horizon + STALE_GRACE_DAYS) are force-closed as "stale" — otherwise they
    accumulate as zombies (e.g. covered warrants showing "ngày 34/5" forever).
    """
    from vnstock_strategy import _load_history

    open_recs = mem.open_recommendations()
    summary = {"closed": 0, "still_open": 0, "stale": 0}

    def _maybe_stale(rec: dict, age: int, horizon: int) -> bool:
        """Force-close an un-fetchable, well-overdue rec. Returns True if closed."""
        if age >= horizon + STALE_GRACE_DAYS:
            mem.close_recommendation(
                rec["id"], exit_price=None, hit_target="stale",
                notes=f"no price history after {age}d (horizon {horizon}d)",
            )
            summary["stale"] += 1
            return True
        return False

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
            if not _maybe_stale(r, age_days, horizon):
                summary["still_open"] += 1
            continue
        # Find bar after creation, walk forward up to horizon bars
        try:
            tcol = hist["time"].dt.date.astype(str)
        except Exception:
            continue
        post = hist[tcol > created.date().isoformat()].head(horizon)
        if post.empty:
            if not _maybe_stale(r, age_days, horizon):
                summary["still_open"] += 1
            continue

        entry = float(r["entry_price"] or 0)
        tp    = float(r["take_profit"] or 0)
        sl    = float(r["cut_loss"] or 0)
        exit_price, hit = _grade_rec(post, entry, tp, sl)
        mem.close_recommendation(r["id"], exit_price=exit_price, hit_target=hit)
        summary["closed"] += 1

    if verbose:
        print(
            f"[reconcile] closed={summary['closed']} "
            f"stale={summary['stale']} still_open={summary['still_open']}"
        )

    # Vòng đời decay: outcome thật vừa cập nhật là lúc đánh giá lại sức khỏe
    # chiến lược active (zero LLM). Best-effort — lỗi không chặn reconcile.
    try:
        from vnstock_strategy import check_strategy_decay
        decay = check_strategy_decay()
        if decay:
            summary["strategy_health"] = decay["state"]
            if decay.get("applied") and verbose:
                print(f"[reconcile] strategy #{decay['strategy_id']} DECAYED → "
                      f"demoted: {'; '.join(decay['reasons'])}")
    except Exception as e:
        if verbose:
            print(f"[reconcile] decay check skipped: {type(e).__name__}: {e}")
    return summary


# ── Run-once orchestrator ──────────────────────────────────────────────────
def run_once(briefs: bool = True, strategy: bool = True,
             reconcile: bool = True, emit: bool = True,
             verbose: bool = True,
             lite: bool = False, mode: str = "auto") -> dict:
    out: dict = {"started_at": datetime.now().isoformat(timespec="seconds")}
    if briefs:
        out["brief_loop"] = brief_loop(verbose=verbose)
    if reconcile:
        out["reconcile"] = reconcile_recommendations(verbose=verbose)
    if strategy:
        out["strategy_loop"] = strategy_loop(verbose=verbose, lite=lite, mode=mode)
    if emit:
        from vnstock_strategy import emit_recommendations as _emit
        scan_u = _scan_universe()
        all_out = _emit(scan_u, max_recs=5, min_avg_volume=100_000)
        recs = [r for r in all_out if not r.get("_stats")]
        diag = next((r for r in all_out if r.get("_stats")), {})
        out["recommendations"] = len(recs)
        if verbose:
            print(f"[run_once] emit_recommendations → {len(recs)} new recs "
                  f"(scanned {len(scan_u)} tickers, vol ≥ 100K filter)")
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
    parser.add_argument("--tier", choices=("short", "position", "both"),
                        default="short",
                        help="Tầng chiến lược: short=5 phiên (mặc định), "
                             "position=20 phiên (chốt từ số đo 13/08), both=cả hai.")
    parser.add_argument("--lite", action="store_true",
                        help="Train on 10 curated diverse tickers with a smaller "
                             "backtest window (~30-60s). Default: full VN30 "
                             "(~30 tickers, 5-15 min). Recommendations always "
                             "scan all tickers in the price warehouse.")
    parser.add_argument("--mode", choices=("auto", "tune", "revise", "fresh"),
                        default="auto",
                        help="Strategy training mode. auto=tune daily / revise "
                             "weekly. tune=force params-only. revise=force "
                             "rewrite core. fresh=cold start a new family.")
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
        for _t in (("short", "position") if args.tier == "both" else (args.tier,)):
            strategy_loop(verbose=verbose, lite=args.lite, mode=args.mode, tier=_t)
    elif args.reconcile_only:
        reconcile_recommendations(verbose=verbose)
    else:
        run_once(verbose=verbose, lite=args.lite, mode=args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
