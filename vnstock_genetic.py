"""
vnstock_genetic.py — GA tune params DETERMINISTIC (khảo sát StockSharp 15/07)
==============================================================================
Bản "tune deterministic" từng để dành (Lean Optimizer → StockSharp
GeneticOptimizer, user chốt làm 2026-07-15): thay vì LLM đề xuất params
(`_do_tune`), chạy GENETIC ALGORITHM thuần numpy trên không gian params của
chiến lược ACTIVE — zero LLM/fetch, seed cố định nên cùng data ra cùng kết
quả. 3 ý mirror StockSharp (mượn Ý TƯỞNG, không copy code — LGPL):

  - Population / GenerationsMax  → ``pop`` / ``gens``
  - GenerationsStagnation        → ``stagnation`` (best không cải thiện N
    thế hệ liên tiếp → dừng sớm)
  - Fitness formula user-defined → ``fitness`` = tên metric backtest
    (expectancy | sharpe | profit_factor | recovery_factor — bản rút gọn,
    không compile biểu thức)

Kỷ luật chống-ăn-may GIỮ NGUYÊN như vòng tune LLM:
  - Backtest NET sau phí (0.4% round-trip) — cùng cost-basis với benchmark.
  - Winner-of-N bị `apply_selection_penalty` với **n_trials = số bộ params
    UNIQUE đã chấm** (GA chấm nhiều ứng viên hơn hẳn tune LLM 3-4 agent →
    penalty nặng hơn tương ứng, ĐÚNG như phải thế).
  - Adopt cần: fitness thắng benchmark active (re-backtest cùng config —
    tránh bẫy benchmark đóng băng 15/07) VÀ `_validation_ok` sau penalty.

Vận hành: công cụ GỌI TAY (mirror vnstock_preset_score — KHÔNG vào
run.py all; backtest full ~8 phút/lần × 40-60 lần đánh giá là bất khả thi
cho pipeline tối). Mặc định chạy trên `lite_config` (~10-30s/backtest →
GA trọn gói ~10-30 phút) và DRY-RUN (không ghi DB); `--apply` mới cập nhật
params + lưu row backtest.

  python vnstock_genetic.py --run                 # dry-run, lite config
  python vnstock_genetic.py --run --medium        # ~90 cửa sổ (chiến lược thưa lệnh)
  python vnstock_genetic.py --run --apply         # ghi DB nếu ứng viên đạt
  python vnstock_genetic.py --run --full          # config đầy đủ (RẤT lâu)
  python vnstock_genetic.py --space               # xem không gian params suy ra

LƯU Ý cỡ mẫu (verify thật 15/07): chiến lược THƯA LỆNH (family hiện tại ra
0-1 lệnh trên ~20 cửa sổ lite) làm GA mù trên lite — nhìn "median n_trades"
trong báo cáo: quá thấp → chạy --medium/--full. GA hữu ích nhất trên core
CÓ lệnh đều; core vừa bị rule 2b revise thì tune sau khi có core mới.
"""

from __future__ import annotations

import argparse
import json
from typing import Optional

import numpy as np

import vnstock_memory as mem
import vnstock_strategy as vs

# GA defaults — pop×gens nhỏ có chủ đích (mỗi đánh giá = 1 backtest thật)
_POP_DEFAULT = 8
_GENS_DEFAULT = 5
_STAGNATION_DEFAULT = 2      # mirror GenerationsStagnation (họ default 5 —
                             # mình 2 vì mỗi thế hệ đắt hơn họ nhiều)
_ELITE = 2                   # số cá thể tốt nhất giữ nguyên qua thế hệ
_TOURNAMENT_K = 3
_MUTATE_P = 0.35             # xác suất đột biến mỗi gene
_MUTATE_SIGMA = 0.15         # sigma gaussian = 15% bề rộng khoảng
_SEED_DEFAULT = 20260715     # deterministic — cùng data ra cùng kết quả

_SPAN_LO, _SPAN_HI = 0.4, 2.5   # khoảng tìm kiếm quanh giá trị hiện tại

_FITNESS_KEYS = ("expectancy", "sharpe", "profit_factor", "recovery_factor")
_MIN_TRADES_DEFAULT = 8      # dưới ngưỡng → fitness -inf (mẫu quá mỏng)
_MIN_TRADES_LITE = 4         # lite/medium tự nhiên ít lệnh hơn nhiều — 8
                             # chặn sạch mọi ứng viên (thấy thật 15/07:
                             # benchmark có số mà GA toàn "—")

_CONFIGS = ("lite", "medium", "full")

_AGENT_NAME = "GeneticOptimizer"


# ── Không gian tham số — suy tự động từ params hiện tại ─────────────────────

def _param_space(params: dict, span: tuple = (_SPAN_LO, _SPAN_HI)) -> dict:
    """{key: (lo, hi, is_int)} cho mọi param SỐ (bool/str/0 giữ cố định —
    giá trị 0 không có thang để suy khoảng). Khoảng = [0.4×, 2.5×] giá trị
    hiện tại (âm thì đảo đầu); int giữ int, sàn 1."""
    space = {}
    for k, v in (params or {}).items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if v == 0 or not np.isfinite(v):
            continue
        lo, hi = sorted((v * span[0], v * span[1]))
        if isinstance(v, int):
            lo, hi = int(np.floor(lo)), int(np.ceil(hi))
            lo = max(1, lo)
            hi = max(lo + 1, hi)
        space[k] = (float(lo), float(hi), isinstance(v, int))
    return space


def _clip_gene(value: float, lo: float, hi: float, is_int: bool):
    v = min(max(float(value), lo), hi)
    return int(round(v)) if is_int else float(v)


def _random_individual(rng, space: dict, base: dict) -> dict:
    ind = dict(base)
    for k, (lo, hi, is_int) in space.items():
        ind[k] = _clip_gene(rng.uniform(lo, hi), lo, hi, is_int)
    return ind


def _crossover(rng, a: dict, b: dict, space: dict, base: dict) -> dict:
    """Per-gene: 50% lấy thẳng từ 1 cha, 50% blend tuyến tính (BLX đơn giản)."""
    child = dict(base)
    for k, (lo, hi, is_int) in space.items():
        va, vb = a.get(k), b.get(k)
        if rng.random() < 0.5:
            v = va if rng.random() < 0.5 else vb
        else:
            t = rng.random()
            v = va + t * (vb - va)
        child[k] = _clip_gene(v, lo, hi, is_int)
    return child


def _mutate(rng, ind: dict, space: dict, p: float = _MUTATE_P) -> dict:
    out = dict(ind)
    for k, (lo, hi, is_int) in space.items():
        if rng.random() < p:
            sigma = (hi - lo) * _MUTATE_SIGMA
            out[k] = _clip_gene(out[k] + rng.normal(0.0, sigma), lo, hi, is_int)
    return out


def _key_of(params: dict, space: dict) -> tuple:
    """Khóa dedup — chỉ các gene đang tối ưu, float làm tròn 6 lẻ."""
    return tuple((k, round(float(params[k]), 6)) for k in sorted(space))


def _fitness_of(metrics: dict, fitness_key: str, min_trades: int) -> float:
    """Metric → fitness; thiếu metric / quá ít lệnh → -inf (bị loại tự
    nhiên qua selection, không nổ). profit_factor None (không lệnh lỗ) cũng
    -inf — chọn fitness đó là chấp nhận đặc tính này."""
    if (metrics.get("n_trades") or 0) < min_trades:
        return float("-inf")
    v = metrics.get(fitness_key)
    return float(v) if isinstance(v, (int, float)) and np.isfinite(v) else float("-inf")


# ── GA core ──────────────────────────────────────────────────────────────────

def genetic_tune(code: str, base_params: dict, cfg,
                 pop: int = _POP_DEFAULT, gens: int = _GENS_DEFAULT,
                 stagnation: int = _STAGNATION_DEFAULT,
                 fitness: str = "expectancy",
                 min_trades: int = _MIN_TRADES_DEFAULT,
                 seed: int = _SEED_DEFAULT) -> dict:
    """Chạy GA trên không gian params quanh ``base_params``.

    Trả {best_params, best_metrics (đã apply_selection_penalty), best_fitness,
    n_trials (số bộ params UNIQUE đã backtest), generations_run, history,
    space}. ``best_metrics`` có thể là None fitness khi mọi ứng viên -inf.
    Không ghi DB — caller quyết định adopt."""
    if fitness not in _FITNESS_KEYS:
        raise ValueError(f"fitness phải thuộc {_FITNESS_KEYS}")
    space = _param_space(base_params)
    if not space:
        return {"error": "params không có giá trị số nào để tối ưu",
                "space": {}}

    rng = np.random.default_rng(seed)
    cache: dict[tuple, tuple[float, dict]] = {}

    def _evaluate(params: dict) -> tuple[float, dict]:
        key = _key_of(params, space)
        if key not in cache:
            metrics, _, _ = vs._do_backtest(code, params, cfg)
            cache[key] = (_fitness_of(metrics, fitness, min_trades), metrics)
        return cache[key]

    # Thế hệ 0: params hiện tại (elite seed) + cá thể ngẫu nhiên trong khoảng
    population = [dict(base_params)]
    population += [_random_individual(rng, space, base_params)
                   for _ in range(max(pop - 1, 1))]

    history: list[float] = []
    best_params, best_fit, best_metrics = None, float("-inf"), {}
    stale = 0
    generations_run = 0

    for _gen in range(max(gens, 1)):
        generations_run += 1
        scored = [( *_evaluate(ind), ind) for ind in population]
        scored.sort(key=lambda t: t[0], reverse=True)

        gen_fit, gen_metrics, gen_best = scored[0]
        if gen_fit > best_fit + 1e-9:
            best_fit, best_metrics, best_params = gen_fit, gen_metrics, dict(gen_best)
            stale = 0
        else:
            stale += 1
        history.append(gen_fit if np.isfinite(gen_fit) else None)

        if stale >= max(stagnation, 1):
            break                      # GenerationsStagnation early-stop

        # Thế hệ kế: elitism + tournament → crossover → mutation
        elites = [dict(t[2]) for t in scored[:_ELITE]]
        nxt = list(elites)
        while len(nxt) < len(population):
            def _pick():
                idx = rng.integers(0, len(scored), size=min(_TOURNAMENT_K, len(scored)))
                return max((scored[i] for i in idx), key=lambda t: t[0])[2]
            child = _mutate(rng, _crossover(rng, _pick(), _pick(), space, base_params), space)
            nxt.append(child)
        population = nxt

    n_trials = len(cache)
    if best_metrics:
        best_metrics = vs.apply_selection_penalty(best_metrics, n_trials)

    # Chẩn đoán: bao nhiêu ứng viên bị gate min_trades chặn + best THÔ
    # (bỏ gate) + median n_trades — để báo cáo giải thích được vì sao toàn
    # "—" và cho thấy cỡ mẫu thật của config đang dùng
    evals = list(cache.values())
    n_below = sum(1 for f, m in evals
                  if not np.isfinite(f) and (m.get("n_trades") or 0) < min_trades)
    trades_counts = sorted((m.get("n_trades") or 0) for _, m in evals)
    median_n_trades = (trades_counts[len(trades_counts) // 2]
                       if trades_counts else None)
    best_raw_fitness = best_raw_n = None
    if evals:
        _, raw_m = max(evals, key=lambda t: _fitness_of(t[1], fitness, 0))
        rf = _fitness_of(raw_m, fitness, 0)
        if np.isfinite(rf):
            best_raw_fitness, best_raw_n = rf, raw_m.get("n_trades")

    return {
        "best_params": best_params,
        "best_metrics": best_metrics,
        "best_fitness": best_fit if np.isfinite(best_fit) else None,
        "fitness_key": fitness,
        "min_trades": min_trades,
        "n_trials": n_trials,
        "n_below_min_trades": n_below,
        "median_n_trades": median_n_trades,
        "best_raw_fitness": best_raw_fitness,
        "best_raw_n_trades": best_raw_n,
        "generations_run": generations_run,
        "history": history,
        "space": {k: (lo, hi) for k, (lo, hi, _) in space.items()},
    }


# ── Vòng ngoài: tune chiến lược ACTIVE, mirror kỷ luật _do_tune ──────────────

def _active_or_none() -> Optional[dict]:
    """get_active_family best-effort — DB chưa init (chưa từng train) trả
    None thay vì nổ sqlite3.OperationalError."""
    try:
        return mem.get_active_family()
    except Exception:
        return None


def medium_config(universe: list) -> "vs.BacktestConfig":
    """Nấc giữa lite và full (thêm sau verify 15/07: active thưa lệnh ra
    0-1 lệnh trên ~20 cửa sổ lite → GA mù; full ~1,800 cửa sổ × 30-40 đánh
    giá = nhiều giờ). ~90 cửa sổ (10 mã × ~9 cửa sổ, lookback 300, step 15)
    → mỗi backtest ~1-2 phút, GA trọn gói ~30-60 phút."""
    return vs.BacktestConfig(universe=universe[:10], lookback_days=300,
                             horizon_days=vs.DEFAULT_HORIZON_DAYS,
                             window_size=60, step_days=15)


def genetic_tune_active(apply: bool = False, config: str = "lite",
                        universe: Optional[list] = None,
                        pop: int = _POP_DEFAULT, gens: int = _GENS_DEFAULT,
                        stagnation: int = _STAGNATION_DEFAULT,
                        fitness: str = "expectancy",
                        min_trades: Optional[int] = None,
                        seed: int = _SEED_DEFAULT) -> dict:
    """GA-tune chiến lược active. DRY-RUN mặc định (zero side-effect);
    ``apply=True`` mới ghi DB — và CHỈ khi ứng viên thắng benchmark active
    (re-backtest cùng config, net-vs-net) VÀ qua gate validation sau penalty
    chọn-lọc (mirror `_do_tune`). ``config``: lite | medium | full."""
    if config not in _CONFIGS:
        return {"error": f"config phải thuộc {_CONFIGS}"}
    active = _active_or_none()
    if not active:
        return {"error": "không có chiến lược active — chạy train/cold-start trước"}
    try:
        cur_params = json.loads(active.get("params_json") or "{}")
    except Exception:
        cur_params = {}
    if not _param_space(cur_params):
        return {"error": "chiến lược active không có params số để tối ưu"}

    if universe is None:
        from vnstock_train import _training_universe
        universe = _training_universe(lite=(config != "full"))
    if not universe:
        return {"error": "không dựng được universe (warehouse trống?)"}
    cfg = (vs.lite_config(universe) if config == "lite"
           else medium_config(universe) if config == "medium"
           else vs.BacktestConfig(universe=universe))
    if min_trades is None:
        min_trades = _MIN_TRADES_DEFAULT if config == "full" else _MIN_TRADES_LITE

    code = active["code"]
    # Benchmark CÙNG cost-basis + CÙNG config với ứng viên (bẫy benchmark
    # đóng băng 15/07: đọc row DB cũ là so net-vs-gross / khác config)
    cur_metrics, _ps, _pe = vs._do_backtest(code, cur_params, cfg)
    cur_fit = _fitness_of(cur_metrics, fitness, min_trades=0)

    result = genetic_tune(code, cur_params, cfg, pop=pop, gens=gens,
                          stagnation=stagnation, fitness=fitness,
                          min_trades=min_trades, seed=seed)
    if result.get("error"):
        return result

    best_metrics = result.get("best_metrics") or {}
    best_fit = result.get("best_fitness")
    # Sàn n_trades: dùng sàn CỦA CHÍNH RUN (config-aware — lite hạ sàn có chủ
    # đích cho smoke test, xem _MIN_TRADES_LITE), không phải sàn cứng 10 —
    # nhưng vẫn phải hiện diện NGAY TRONG cổng adopt (lộ 13/08: cổng tune bên
    # vnstock_strategy thiếu sàn, ứng viên co mẫu thắng bằng expectancy ảo).
    adopted = (best_fit is not None and cur_fit is not None
               and best_fit > cur_fit
               and (best_metrics.get("n_trades") or 0) >= min_trades
               and vs._validation_ok(best_metrics))

    applied = False
    if apply and adopted:
        mem.save_backtest(active["id"], _ps, _pe,
                          ",".join(cfg.universe[:10]), cur_metrics)
        mem.update_strategy_params(active["id"], result["best_params"], _AGENT_NAME)
        mem.save_backtest(active["id"], _ps, _pe,
                          ",".join(cfg.universe[:10]), best_metrics)
        applied = True

    return {
        **result,
        "strategy_id": active["id"],
        "baseline_fitness": cur_fit if np.isfinite(cur_fit) else None,
        "baseline_metrics": {k: cur_metrics.get(k) for k in
                             ("n_trades", "win_rate", "expectancy", "sharpe",
                              "profit_factor", "recovery_factor")},
        "adopted": adopted,
        "applied": applied,
        "config": config,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.4f}" if isinstance(v, float) else str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GA tune params chiến lược active (deterministic, zero LLM)")
    ap.add_argument("--run", action="store_true", help="chạy GA (mặc định dry-run)")
    ap.add_argument("--apply", action="store_true", help="ghi DB nếu ứng viên đạt gate")
    ap.add_argument("--medium", action="store_true",
                    help="config trung gian ~90 cửa sổ (~1-2 phút/đánh giá, trọn gói "
                         "~30-60 phút) — dùng khi chiến lược thưa lệnh làm lite mù")
    ap.add_argument("--full", action="store_true",
                    help="config backtest đầy đủ (RẤT lâu: ~8 phút/đánh giá)")
    ap.add_argument("--space", action="store_true", help="chỉ in không gian params suy ra")
    ap.add_argument("--pop", type=int, default=_POP_DEFAULT)
    ap.add_argument("--gens", type=int, default=_GENS_DEFAULT)
    ap.add_argument("--stagnation", type=int, default=_STAGNATION_DEFAULT)
    ap.add_argument("--fitness", choices=list(_FITNESS_KEYS), default="expectancy")
    ap.add_argument("--min-trades", type=int, default=None,
                    help=f"số lệnh tối thiểu để ứng viên được chấm "
                         f"(mặc định: {_MIN_TRADES_LITE} lite / {_MIN_TRADES_DEFAULT} full)")
    ap.add_argument("--seed", type=int, default=_SEED_DEFAULT)
    args = ap.parse_args(argv)

    if args.space:
        active = _active_or_none()
        if not active:
            print("Không có chiến lược active.")
            return 1
        params = json.loads(active.get("params_json") or "{}")
        space = _param_space(params)
        print(f"Chiến lược #{active['id']} — {len(space)} gene tối ưu được:")
        for k, (lo, hi, is_int) in space.items():
            cur = params.get(k)
            print(f"  {k:24s} hiện tại={cur}  khoảng=[{lo:g}, {hi:g}]"
                  f"{' (int)' if is_int else ''}")
        fixed = [k for k in params if k not in space]
        if fixed:
            print(f"  Giữ cố định (không phải số/=0): {', '.join(fixed)}")
        return 0

    if not args.run:
        ap.print_help()
        return 0

    if args.medium and args.full:
        print("❌ --medium và --full loại trừ nhau.")
        return 1
    config = "full" if args.full else "medium" if args.medium else "lite"
    r = genetic_tune_active(apply=args.apply, config=config,
                            pop=args.pop, gens=args.gens,
                            stagnation=args.stagnation,
                            fitness=args.fitness, min_trades=args.min_trades,
                            seed=args.seed)
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1

    v = (r.get("best_metrics") or {}).get("validation") or {}
    base_n = (r.get("baseline_metrics") or {}).get("n_trades")
    print(f"🧬 GA tune chiến lược #{r['strategy_id']} — fitness={r['fitness_key']}"
          f" ({r['config']} config, seed {args.seed},"
          f" min_trades={r.get('min_trades')})")
    print(f"  Thế hệ chạy: {r['generations_run']} (best theo thế hệ: "
          f"{', '.join(_fmt(h) for h in r['history'])})")
    print(f"  Ứng viên UNIQUE đã backtest: {r['n_trials']}"
          f" (median n_trades={r.get('median_n_trades') if r.get('median_n_trades') is not None else '—'})"
          f" → penalty chọn-lọc p_adj={_fmt(v.get('p_value_adj'))}")
    print(f"  Benchmark active : {_fmt(r.get('baseline_fitness'))}"
          f"  (n_trades={base_n if base_n is not None else '—'})")
    print(f"  Best GA          : {_fmt(r.get('best_fitness'))}"
          f"  (validation {'ĐẠT' if v.get('passed') else 'TRƯỢT/thiếu'})")
    if (n_below := r.get("n_below_min_trades")) and r.get("best_fitness") is None:
        print(f"  ⚠️ {n_below}/{r['n_trials']} ứng viên bị loại vì n_trades <"
              f" {r.get('min_trades')} — best THÔ (bỏ gate):"
              f" {_fmt(r.get('best_raw_fitness'))}"
              f" ({r.get('best_raw_n_trades')} lệnh)."
              f" Thử --min-trades thấp hơn hoặc --medium/--full (nhiều cửa sổ hơn).")
    if r.get("best_params"):
        print(f"  Params best      : {json.dumps(r['best_params'], ensure_ascii=False)}")
    if r["adopted"]:
        print("  ✅ Ứng viên THẮNG benchmark + qua gate validation"
              + (" — ĐÃ GHI DB." if r["applied"] else " — dry-run, thêm --apply để ghi."))
    else:
        print("  ⛔ Không adopt (thua benchmark hoặc trượt gate) — giữ params hiện tại.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
