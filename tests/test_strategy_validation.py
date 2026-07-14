"""Tests for vnstock_strategy — kiểm định chống-ăn-may (Món 1) + vòng đời
decay chiến lược (Món 2), từ khảo sát HKUDS/Vibe-Trading 2026-07-14.

Hermetic: numpy thuần cho các kiểm định; mem/agents monkeypatch — không DB
thật, không LLM, không mạng.
"""
from __future__ import annotations

import numpy as np
import pytest

import vnstock_strategy as vs


# ── Món 1: monte_carlo_pvalue (sign-flip permutation) ───────────────────────


def test_mc_pvalue_strong_edge_is_small():
    # 30 lệnh toàn dương có phương sai → edge rõ, p rất nhỏ
    pnls = np.array([2.0, 3.0, 1.5, 2.5] * 8)
    p = vs.monte_carlo_pvalue(pnls)
    assert p is not None and p < 0.01


def test_mc_pvalue_symmetric_noise_is_large():
    # pnl đối xứng quanh 0 = đúng H0 → p không thể nhỏ
    pnls = np.array([1.0, -1.0, 2.0, -2.0, 0.5, -0.5] * 5)
    p = vs.monte_carlo_pvalue(pnls)
    assert p is not None and p > 0.3


def test_mc_pvalue_guards_and_determinism():
    assert vs.monte_carlo_pvalue(np.array([1.0, 2.0])) is None      # < 3 lệnh
    assert vs.monte_carlo_pvalue(np.array([2.0, 2.0, 2.0])) is None  # σ = 0
    pnls = np.array([1.0, -0.5, 2.0, 0.3, -1.1, 0.8, 1.4, -0.2])
    assert vs.monte_carlo_pvalue(pnls) == vs.monte_carlo_pvalue(pnls)


# ── Món 1: bootstrap_sharpe_ci ───────────────────────────────────────────────


def test_bootstrap_ci_ordered_and_positive_for_edge():
    pnls = np.array([2.0, 3.0, 1.5, 2.5, 1.8, 2.2] * 5)
    ci = vs.bootstrap_sharpe_ci(pnls)
    assert ci is not None and ci[0] < ci[1]
    assert ci[0] > 0            # edge mạnh → cả biên dưới CI dương


def test_bootstrap_ci_too_few_trades():
    assert vs.bootstrap_sharpe_ci(np.array([1.0, 2.0])) is None


# ── Món 1: walk_forward_consistency ─────────────────────────────────────────


def _trades(pnls, start=0):
    return [{"pnl": p, "start_idx": start + i * 5} for i, p in enumerate(pnls)]


def test_walk_forward_even_performance():
    wf = vs.walk_forward_consistency(_trades([1.0] * 16), n_folds=4)
    assert wf["n_folds"] == 4 and wf["positive_frac"] == 1.0
    assert all(f > 0 for f in wf["fold_pnls"])


def test_walk_forward_concentrated_performance():
    # lãi dồn hết vào đoạn ĐẦU, 3 đoạn sau âm → chỉ 25% cửa sổ dương
    wf = vs.walk_forward_consistency(
        _trades([10.0] * 4 + [-0.5] * 12), n_folds=4)
    assert wf["positive_frac"] == 0.25


def test_walk_forward_sorts_by_time_and_guards():
    # đưa vào KHÔNG theo thứ tự thời gian → phải sort theo start_idx
    trades = [{"pnl": -1.0, "start_idx": 100}, {"pnl": 5.0, "start_idx": 0},
              {"pnl": 5.0, "start_idx": 5}, {"pnl": -1.0, "start_idx": 105}]
    wf = vs.walk_forward_consistency(trades, n_folds=2)
    assert wf["fold_pnls"] == [10.0, -2.0]
    assert vs.walk_forward_consistency(_trades([1.0]), n_folds=4) is None


# ── Món 1: validate_backtest_quality + gate helper ──────────────────────────


def test_validate_quality_passes_real_edge():
    v = vs.validate_backtest_quality(_trades([2.0, 3.0, 1.5, 2.5] * 8))
    assert v["passed"] is True and v["reasons"] == []
    assert v["p_value_sharpe"] < 0.01
    assert v["sharpe_ci"][0] > 0
    assert v["walk_forward"]["positive_frac"] == 1.0


def test_validate_quality_fails_luck():
    # đối xứng quanh 0 → p lớn → có reason, passed False
    v = vs.validate_backtest_quality(_trades([1.0, -1.0, 2.0, -2.0] * 6))
    assert v["passed"] is False
    assert any("ăn-may" in r for r in v["reasons"])


def test_validate_quality_fails_concentrated():
    v = vs.validate_backtest_quality(_trades([30.0] * 4 + [-0.1] * 12))
    assert v["passed"] is False
    assert any("dồn cục" in r for r in v["reasons"])


def test_validate_quality_too_few_trades():
    assert vs.validate_backtest_quality(_trades([1.0, 2.0])) is None
    assert vs.validate_backtest_quality([]) is None


def test_validation_ok_gate_helper():
    assert vs._validation_ok({}) is True                     # backtest cũ
    assert vs._validation_ok({"validation": None}) is True   # quá ít lệnh
    assert vs._validation_ok({"validation": {"passed": True}}) is True
    assert vs._validation_ok({"validation": {"passed": False}}) is False


# ── Món 1: backtest() gắn validation vào metrics ────────────────────────────


def test_backtest_metrics_include_validation(monkeypatch):
    import pandas as pd

    n = 60
    closes = 20.0 + np.arange(n) * 0.2          # uptrend đều
    hist = pd.DataFrame({
        "time": pd.date_range("2026-01-05", periods=n, freq="B"),
        "open": closes, "high": closes * 1.03, "low": closes * 0.99,
        "close": closes, "volume": [1_000_000] * n,
    })
    monkeypatch.setattr(vs, "_load_history", lambda t, days=0: hist)

    calls = {"n": 0}

    def fake_run(code, window, params):
        calls["n"] += 1
        entry = float(window["close"].iloc[-1])
        tp_mult = 1.02 if calls["n"] % 2 else 1.025   # pnl có phương sai
        return {"action": "buy", "entry": entry,
                "tp": entry * tp_mult, "sl": entry * 0.9, "confidence": 0.6}

    monkeypatch.setattr(vs.EXECUTOR, "run", fake_run)
    cfg = vs.BacktestConfig(universe=["AAA"], lookback_days=80,
                            horizon_days=5, window_size=20, step_days=5)
    m = vs.backtest("code", cfg)
    assert m["n_trades"] >= 5
    assert m["validation"] is not None
    assert m["validation"]["passed"] is True      # uptrend + toàn TP → edge thật


# ── Món 1: gate ở _do_revise / _do_tune ──────────────────────────────────────


class _FakeAgent:
    name = "TestAgent"
    is_available = True


def _patch_revise(monkeypatch, metrics, recorder):
    monkeypatch.setattr(vs.mem, "latest_backtest",
                        lambda sid: {"expectancy": 0.1, "n_trades": 20})
    monkeypatch.setattr(vs.mem, "save_strategy", lambda **kw: 5)
    monkeypatch.setattr(vs.mem, "save_backtest", lambda *a, **kw: 1)
    monkeypatch.setattr(vs.mem, "promote_strategy",
                        lambda sid, retire_others=True: recorder.append(("promote", sid)))
    monkeypatch.setattr(vs.mem, "update_strategy_status",
                        lambda sid, st: recorder.append(("status", sid, st)))
    monkeypatch.setattr(vs.mem, "mark_core_stable", lambda *a, **kw: None)
    monkeypatch.setattr(vs, "revise_strategy",
                        lambda *a, **kw: ("def signal(df,p): pass", {"x": 1}, None))
    monkeypatch.setattr(vs, "_do_backtest",
                        lambda c, p, cfg: (metrics, "2026-01-01", "2026-07-01"))
    monkeypatch.setattr(vs, "_check_stability", lambda fam: False)


def test_do_revise_blocks_failed_validation(monkeypatch):
    rec: list = []
    metrics = {"expectancy": 0.9, "n_trades": 25,
               "validation": {"passed": False, "reasons": ["p-value cao"]}}
    _patch_revise(monkeypatch, metrics, rec)
    active = {"id": 1, "code": "c", "family_id": "fam", "is_core_stable": 0}
    cfg = vs.BacktestConfig(universe=["AAA"])
    sid, out = vs._do_revise(_FakeAgent(), active, cfg)
    # expectancy tốt hơn NHƯNG kiểm định trượt → retired, KHÔNG promote
    assert ("status", 5, "retired") in rec
    assert not any(r[0] == "promote" for r in rec)


def test_do_revise_promotes_when_validation_passes(monkeypatch):
    rec: list = []
    metrics = {"expectancy": 0.9, "n_trades": 25,
               "validation": {"passed": True, "reasons": []}}
    _patch_revise(monkeypatch, metrics, rec)
    active = {"id": 1, "code": "c", "family_id": "fam", "is_core_stable": 0}
    sid, out = vs._do_revise(_FakeAgent(), active,
                             vs.BacktestConfig(universe=["AAA"]))
    assert ("promote", 5) in rec


def test_do_tune_blocks_failed_validation(monkeypatch):
    rec: list = []
    monkeypatch.setattr(vs.mem, "latest_backtest",
                        lambda sid: {"expectancy": 0.1})
    monkeypatch.setattr(vs.mem, "update_strategy_params",
                        lambda *a, **kw: rec.append("adopted"))
    monkeypatch.setattr(vs.mem, "save_backtest", lambda *a, **kw: 1)
    monkeypatch.setattr(vs, "tune_params", lambda *a, **kw: ({"x": 2}, None))
    monkeypatch.setattr(
        vs, "_do_backtest",
        lambda c, p, cfg: ({"expectancy": 0.9, "n_trades": 25,
                            "validation": {"passed": False, "reasons": ["x"]}},
                           "a", "b"))
    active = {"id": 1, "code": "c", "params_json": '{"x": 1}'}
    sid, out = vs._do_tune([_FakeAgent()], active,
                           vs.BacktestConfig(universe=["AAA"]))
    assert rec == [] and "error" in out


# ── Món 2: strategy_health ───────────────────────────────────────────────────


def _patch_health(monkeypatch, live, bt_wr):
    monkeypatch.setattr(vs.mem, "recommendation_performance", lambda sid: live)
    monkeypatch.setattr(vs.mem, "latest_backtest",
                        lambda sid: {"win_rate": bt_wr} if bt_wr is not None else None)


def test_health_insufficient_sample(monkeypatch):
    _patch_health(monkeypatch, {"n": 3, "win_rate": 0.0, "avg_pnl": -2.0}, 0.6)
    assert vs.strategy_health(1)["state"] == "insufficient"
    _patch_health(monkeypatch, {"n": 20, "win_rate": 0.5, "avg_pnl": 1.0}, None)
    assert vs.strategy_health(1)["state"] == "insufficient"   # chưa có backtest


def test_health_healthy(monkeypatch):
    _patch_health(monkeypatch, {"n": 10, "win_rate": 0.55, "avg_pnl": 0.8}, 0.60)
    h = vs.strategy_health(1)
    assert h["state"] == "healthy" and h["gap"] == pytest.approx(0.05)


def test_health_monitoring(monkeypatch):
    _patch_health(monkeypatch, {"n": 10, "win_rate": 0.45, "avg_pnl": 0.2}, 0.60)
    h = vs.strategy_health(1)
    assert h["state"] == "monitoring"
    assert any("theo dõi" in r for r in h["reasons"])


def test_health_decayed_by_gap(monkeypatch):
    _patch_health(monkeypatch, {"n": 12, "win_rate": 0.30, "avg_pnl": 0.1}, 0.60)
    h = vs.strategy_health(1)
    assert h["state"] == "decayed"
    assert any("tụt" in r for r in h["reasons"])


def test_health_decayed_by_floor(monkeypatch):
    # gap 0.20 < ngưỡng 0.25 nhưng wr ≤ 30% + PnL âm → vẫn decayed
    _patch_health(monkeypatch, {"n": 12, "win_rate": 0.25, "avg_pnl": -1.5}, 0.45)
    h = vs.strategy_health(1)
    assert h["state"] == "decayed"
    assert any("âm" in r for r in h["reasons"])


# ── Món 2: check_strategy_decay ──────────────────────────────────────────────


def test_check_decay_demotes_active(monkeypatch):
    rec: list = []
    monkeypatch.setattr(vs.mem, "get_active_family",
                        lambda: {"id": 7, "name": "family-x v1"})
    _patch_health(monkeypatch, {"n": 12, "win_rate": 0.20, "avg_pnl": -2.0}, 0.60)
    monkeypatch.setattr(vs.mem, "update_strategy_status",
                        lambda sid, st: rec.append((sid, st)))
    r = vs.check_strategy_decay()
    assert r["state"] == "decayed" and r["applied"] is True
    assert rec == [(7, "decayed")]


def test_check_decay_monitoring_no_demote(monkeypatch):
    rec: list = []
    monkeypatch.setattr(vs.mem, "get_active_family", lambda: {"id": 7, "name": "x"})
    _patch_health(monkeypatch, {"n": 12, "win_rate": 0.45, "avg_pnl": 0.1}, 0.60)
    monkeypatch.setattr(vs.mem, "update_strategy_status",
                        lambda sid, st: rec.append((sid, st)))
    r = vs.check_strategy_decay()
    assert r["state"] == "monitoring" and r["applied"] is False and rec == []


def test_check_decay_apply_false_reports_only(monkeypatch):
    rec: list = []
    monkeypatch.setattr(vs.mem, "get_active_family", lambda: {"id": 7, "name": "x"})
    _patch_health(monkeypatch, {"n": 12, "win_rate": 0.20, "avg_pnl": -2.0}, 0.60)
    monkeypatch.setattr(vs.mem, "update_strategy_status",
                        lambda sid, st: rec.append((sid, st)))
    r = vs.check_strategy_decay(apply=False)
    assert r["state"] == "decayed" and r["applied"] is False and rec == []


def test_check_decay_guards(monkeypatch):
    monkeypatch.setattr(vs.mem, "get_active_family", lambda: None)
    assert vs.check_strategy_decay() is None            # không có active
    monkeypatch.setattr(vs.mem, "get_active_family", lambda: {"id": 7})
    monkeypatch.setenv("VNSTOCK_STRATEGY_DECAY", "0")   # kill switch
    assert vs.check_strategy_decay() is None
