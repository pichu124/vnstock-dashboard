"""Tests cho vnstock_genetic — GA tune params deterministic (StockSharp
GeneticOptimizer port). Hermetic: backtest + memory đều fake qua monkeypatch,
zero DB/LLM/data."""

from __future__ import annotations

import json

import pytest

import vnstock_genetic as vg
import vnstock_strategy as vs


def _fake_backtest(calls=None, p_value=0.01, n_trades=30):
    """Backtest giả: expectancy là hàm trơn của params — đỉnh tại
    rsi_period=24, stop_loss_pct=3.0 → GA phải leo về phía đó."""
    def fake(code, params, cfg):
        if calls is not None:
            calls.append(dict(params))
        rsi = float(params.get("rsi_period", 10))
        sl = float(params.get("stop_loss_pct", 1.0))
        exp = 2.0 - abs(rsi - 24.0) * 0.05 - abs(sl - 3.0) * 0.2
        metrics = {"n_trades": n_trades, "expectancy": exp, "sharpe": exp / 2,
                   "win_rate": 0.5, "profit_factor": 1.2, "recovery_factor": 1.0,
                   "validation": {"passed": True, "p_value_sharpe": p_value}}
        return metrics, "2026-01-01", "2026-07-01"
    return fake


_BASE = {"rsi_period": 10, "stop_loss_pct": 1.0}
_CFG = vs.BacktestConfig(universe=["AAA"])


# ─── _param_space ────────────────────────────────────────────────────────────

def test_param_space_numeric_only_and_int_flag():
    space = vg._param_space({"rsi_period": 20, "stop_loss_pct": 2.5,
                             "use_volume": True, "mode": "ema", "zero": 0})
    assert set(space) == {"rsi_period", "stop_loss_pct"}
    lo, hi, is_int = space["rsi_period"]
    assert is_int and lo >= 1 and lo < 20 < hi
    _, _, is_int_f = space["stop_loss_pct"]
    assert not is_int_f


def test_param_space_negative_value_bounds_ordered():
    (lo, hi, _), = vg._param_space({"threshold": -5.0}).values()
    assert lo < hi and lo == -12.5 and hi == -2.0


# ─── genetic_tune core ───────────────────────────────────────────────────────

def test_ga_improves_over_base_params(monkeypatch):
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest())
    r = vg.genetic_tune("code", dict(_BASE), _CFG)
    base_exp = 2.0 - abs(10 - 24) * 0.05 - abs(1.0 - 3.0) * 0.2   # = 0.9
    assert r["best_fitness"] is not None and r["best_fitness"] > base_exp + 0.2
    assert r["best_params"]["rsi_period"] > _BASE["rsi_period"]   # leo về 24
    assert isinstance(r["best_params"]["rsi_period"], int)        # int giữ int


def test_ga_is_deterministic(monkeypatch):
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest())
    r1 = vg.genetic_tune("code", dict(_BASE), _CFG, seed=123)
    r2 = vg.genetic_tune("code", dict(_BASE), _CFG, seed=123)
    assert r1["best_params"] == r2["best_params"]
    assert r1["history"] == r2["history"] and r1["n_trials"] == r2["n_trials"]


def test_cache_dedup_counts_unique_trials(monkeypatch):
    calls = []
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(calls=calls))
    r = vg.genetic_tune("code", dict(_BASE), _CFG, pop=6, gens=4)
    # mỗi call backtest = 1 cache miss → n_trials đúng bằng số bộ UNIQUE
    assert len(calls) == r["n_trials"]
    assert r["n_trials"] <= 6 * 4


def test_stagnation_early_stop(monkeypatch):
    def flat(code, params, cfg):   # fitness hằng số → không bao giờ cải thiện
        return ({"n_trades": 30, "expectancy": 1.0,
                 "validation": {"passed": True, "p_value_sharpe": 0.01}},
                "2026-01-01", "2026-07-01")
    monkeypatch.setattr(vs, "_do_backtest", flat)
    r = vg.genetic_tune("code", dict(_BASE), _CFG, gens=10, stagnation=2)
    assert r["generations_run"] <= 3      # gen1 set best, +2 thế hệ stale → dừng


def test_selection_penalty_applied_with_ga_trial_count(monkeypatch):
    # p=0.02 nhưng GA chấm hàng chục ứng viên → p_adj = 0.02×n ≥ 0.10 → TRƯỢT
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(p_value=0.02))
    r = vg.genetic_tune("code", dict(_BASE), _CFG)
    v = r["best_metrics"]["validation"]
    assert v["n_trials"] == r["n_trials"] and r["n_trials"] >= 5
    assert v["p_value_adj"] >= 0.10 and v["passed"] is False


def test_min_trades_gate_all_unfit(monkeypatch):
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(n_trades=2))
    r = vg.genetic_tune("code", dict(_BASE), _CFG, gens=3)
    assert r["best_fitness"] is None and r["best_params"] is None


def test_bad_fitness_key_raises():
    with pytest.raises(ValueError):
        vg.genetic_tune("code", dict(_BASE), _CFG, fitness="pnl_total")


def test_no_numeric_params_returns_error():
    r = vg.genetic_tune("code", {"mode": "ema"}, _CFG)
    assert "error" in r


# ─── genetic_tune_active — vòng ngoài, adopt discipline ──────────────────────

def _fake_active(params=None):
    return {"id": 7, "code": "def signal(...): ...",
            "params_json": json.dumps(params or _BASE)}


def test_active_missing_returns_error(monkeypatch):
    monkeypatch.setattr(vg.mem, "get_active_family", lambda: None)
    assert "error" in vg.genetic_tune_active(universe=["AAA"])


def test_dry_run_never_writes_db(monkeypatch):
    monkeypatch.setattr(vg.mem, "get_active_family", lambda: _fake_active())
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(p_value=0.00001))
    writes = []
    monkeypatch.setattr(vg.mem, "update_strategy_params",
                        lambda *a, **k: writes.append(("params", a)))
    monkeypatch.setattr(vg.mem, "save_backtest",
                        lambda *a, **k: writes.append(("bt", a)))
    r = vg.genetic_tune_active(universe=["AAA"])
    assert r["adopted"] is True and r["applied"] is False
    assert writes == []                        # dry-run: zero side-effect


def test_apply_writes_params_when_adopted(monkeypatch):
    monkeypatch.setattr(vg.mem, "get_active_family", lambda: _fake_active())
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(p_value=0.00001))
    params_writes, bt_writes = [], []
    monkeypatch.setattr(vg.mem, "update_strategy_params",
                        lambda sid, p, name: params_writes.append((sid, p, name)))
    monkeypatch.setattr(vg.mem, "save_backtest",
                        lambda *a, **k: bt_writes.append(a))
    r = vg.genetic_tune_active(universe=["AAA"], apply=True)
    assert r["adopted"] and r["applied"]
    sid, p, name = params_writes[0]
    assert sid == 7 and name == "GeneticOptimizer"
    assert p == r["best_params"]
    assert len(bt_writes) == 2                 # benchmark row + best row


def test_apply_skipped_when_validation_fails_after_penalty(monkeypatch):
    # p=0.02 × hàng chục trials → trượt gate → KHÔNG adopt dù fitness thắng
    monkeypatch.setattr(vg.mem, "get_active_family", lambda: _fake_active())
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(p_value=0.02))
    writes = []
    monkeypatch.setattr(vg.mem, "update_strategy_params",
                        lambda *a, **k: writes.append(a))
    monkeypatch.setattr(vg.mem, "save_backtest", lambda *a, **k: None)
    r = vg.genetic_tune_active(universe=["AAA"], apply=True)
    assert r["best_fitness"] > r["baseline_fitness"]   # thắng benchmark...
    assert r["adopted"] is False and r["applied"] is False
    assert writes == []                                # ...nhưng gate chặn


def test_diagnostics_when_min_trades_gates_everything(monkeypatch):
    # Tình huống thật 15/07: benchmark có số nhưng GA toàn "—" — báo cáo
    # phải nói rõ bao nhiêu ứng viên bị gate + best THÔ là bao nhiêu
    monkeypatch.setattr(vs, "_do_backtest", _fake_backtest(n_trades=5))
    r = vg.genetic_tune("code", dict(_BASE), _CFG, min_trades=8)
    assert r["best_fitness"] is None
    assert r["n_below_min_trades"] == r["n_trials"] > 0
    assert r["best_raw_fitness"] is not None and r["best_raw_n_trades"] == 5
    assert r["min_trades"] == 8


def test_active_lite_defaults_min_trades_lower(monkeypatch):
    # lite config tự hạ min_trades xuống _MIN_TRADES_LITE → ứng viên 5 lệnh
    # vẫn được chấm (trước fix: 8 chặn sạch trên lite)
    monkeypatch.setattr(vg.mem, "get_active_family", lambda: _fake_active())
    monkeypatch.setattr(vs, "_do_backtest",
                        _fake_backtest(p_value=0.00001, n_trades=5))
    r = vg.genetic_tune_active(universe=["AAA"], lite=True)
    assert r["min_trades"] == vg._MIN_TRADES_LITE
    assert r["best_fitness"] is not None and r["adopted"] is True
    r_full = vg.genetic_tune_active(universe=["AAA"], lite=False)
    assert r_full["min_trades"] == vg._MIN_TRADES_DEFAULT
    assert r_full["best_fitness"] is None          # 5 lệnh < 8 → gate chặn


def test_load_history_skips_dashboard_import_outside_streamlit(monkeypatch):
    # Ngoài phiên Streamlit, _load_history phải đi THẲNG parquet — import
    # vnstock_dashboard trong bare mode sẽ thực thi nguyên app (spam
    # ScriptRunContext + chậm, thấy thật khi chạy vnstock_genetic 15/07)
    import sys
    import pandas as pd

    class _Poison:
        def __getattr__(self, name):
            raise AssertionError("vnstock_dashboard bị import ngoài Streamlit!")

    monkeypatch.setitem(sys.modules, "vnstock_dashboard", _Poison())
    sentinel = pd.DataFrame({"close": [1.0]})
    monkeypatch.setattr(vs, "_load_history_from_parquet",
                        lambda ticker, days, **k: sentinel)
    assert vs._in_streamlit_session() is False
    out = vs._load_history("AAA", days=30)
    assert out is sentinel
