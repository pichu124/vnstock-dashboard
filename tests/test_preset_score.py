"""Tests cho vnstock_preset_score (chấm alpha preset screener) +
apply_selection_penalty (hiệu chỉnh đa-thử-nghiệm gate 🧪) — 2 món từ
khảo sát ML4T 3rd edition 2026-07-15.

Hermetic: history + kho giá fake qua tmp_path/monkeypatch.
"""
from __future__ import annotations

import json

import pytest

import vnstock_preset_score as ps
import vnstock_strategy as vs


# ── Kho giá fake: VNINDEX đi ngang +1%/5phiên, AAA +5%, BBB -3% ─────────────

_DATES = [f"2026-07-{d:02d}" for d in range(1, 29)]


def _mk_closes(start: float, step_pct: float) -> list[tuple[str, float]]:
    out, px = [], start
    for d in _DATES:
        out.append((d, round(px, 3)))
        px *= 1 + step_pct / 100
    return out


_PRICES = {
    "VNINDEX": _mk_closes(1800.0, 0.2),   # ~+1.0%/5 phiên
    "AAA": _mk_closes(20.0, 1.0),         # ~+5.1%/5 phiên → excess dương
    "BBB": _mk_closes(30.0, -0.6),        # ~-3.0%/5 phiên → excess âm
}


@pytest.fixture(autouse=True)
def _fake_env(tmp_path, monkeypatch):
    hist_dir = tmp_path / "screener_history"
    hist_dir.mkdir(parents=True)
    monkeypatch.setattr(ps, "_HISTORY_DIR", hist_dir)
    monkeypatch.setattr(ps, "_CACHE", tmp_path / "preset_scorecard.json")
    monkeypatch.setattr(ps, "_close_series",
                        lambda tk, cache: _PRICES.get(tk, []))
    yield hist_dir


def _write_snap(hist_dir, date, presets):
    body = {"presets": {
        name: {"desc": f"desc {name}", "count": len(tks),
               "results": [{"ticker": t, "close": 1.0} for t in tks]}
        for name, tks in presets.items()}}
    (hist_dir / f"{date}.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")


# ── Món 1: forward return + scorecard ────────────────────────────────────────


def test_fwd_return_math_and_edges():
    closes = _PRICES["AAA"]
    r = ps._fwd_return(closes, "2026-07-05", 5)
    assert r == pytest.approx(5.1, abs=0.1)          # 1.01^5
    # ngày nghỉ → dùng bar cuối TRƯỚC đó làm gốc
    assert ps._fwd_return(closes, "2026-07-05", 5) == \
           ps._fwd_return(closes, "2026-07-05", 5)
    # chưa đủ H phiên tương lai → None (tín hiệu mới không được chấm non)
    assert ps._fwd_return(closes, _DATES[-3], 5) is None
    # trước bar đầu tiên → None
    assert ps._fwd_return(closes, "2026-06-01", 5) is None


def test_scorecard_ranks_presets_by_excess(_fake_env):
    _write_snap(_fake_env, "2026-07-05", {"momentum": ["AAA"],
                                          "oversold": ["BBB"]})
    _write_snap(_fake_env, "2026-07-10", {"momentum": ["AAA", "BBB"]})
    card = ps.preset_scorecard(horizons=(5,), days=30)
    mom = card["presets"]["momentum"]["h5"]
    ovs = card["presets"]["oversold"]["h5"]
    assert mom["n"] == 3 and ovs["n"] == 1
    assert card["presets"]["momentum"]["n_days_signal"] == 2
    # AAA thắng index, BBB thua index
    assert ovs["avg_excess"] < 0 < mom["avg_fwd"]
    assert ovs["hit_rate"] == 0.0
    assert mom["hit_rate"] == pytest.approx(66.7, abs=0.1)  # 2×AAA thắng, 1×BBB thua


def test_scorecard_empty_and_cache_roundtrip(_fake_env, capsys):
    assert ps.preset_scorecard() is None             # chưa có history
    assert ps.main(["--show"]) == 1
    _write_snap(_fake_env, "2026-07-05", {"momentum": ["AAA"]})
    assert ps.main(["--refresh", "--horizons", "5"]) == 0
    out = capsys.readouterr().out
    assert "momentum" in out and "excess" in out
    card = ps.load_scorecard()
    assert card and "momentum" in card["presets"]


def test_ticker_without_data_skipped(_fake_env):
    _write_snap(_fake_env, "2026-07-05", {"momentum": ["AAA", "XXX"]})
    card = ps.preset_scorecard(horizons=(5,), days=30)
    assert card["presets"]["momentum"]["h5"]["n"] == 1   # XXX không có giá → bỏ


# ── Món 2: apply_selection_penalty ───────────────────────────────────────────


def test_selection_penalty_flips_borderline_pass():
    m = {"validation": {"passed": True, "p_value_sharpe": 0.04,
                        "reasons": []}}
    vs.apply_selection_penalty(m, 3)
    v = m["validation"]
    assert v["p_value_adj"] == pytest.approx(0.12)
    assert v["passed"] is False                       # 0.04×3 ≥ 0.10 → siết
    assert any("chọn-lọc" in r for r in v["reasons"])
    assert v["n_trials"] == 3


def test_selection_penalty_keeps_strong_pass_and_never_loosens():
    strong = {"validation": {"passed": True, "p_value_sharpe": 0.01,
                             "reasons": []}}
    vs.apply_selection_penalty(strong, 3)
    assert strong["validation"]["passed"] is True     # 0.03 < 0.10 → giữ
    assert strong["validation"]["p_value_adj"] == pytest.approx(0.03)
    # đã trượt (walk-forward) thì p_adj nhỏ cũng KHÔNG lật thành đạt
    failed = {"validation": {"passed": False, "p_value_sharpe": 0.01,
                             "reasons": ["fold dồn cục"]}}
    vs.apply_selection_penalty(failed, 2)
    assert failed["validation"]["passed"] is False


def test_selection_penalty_noop_cases():
    m1 = {"validation": {"passed": True, "p_value_sharpe": 0.04, "reasons": []}}
    vs.apply_selection_penalty(m1, 1)                 # 1 ứng viên → no-op
    assert "p_value_adj" not in m1["validation"]
    m2 = {"validation": None}
    assert vs.apply_selection_penalty(m2, 5) is m2    # thiếu validation
    m3 = {"validation": {"passed": True, "p_value_sharpe": None, "reasons": []}}
    vs.apply_selection_penalty(m3, 5)                 # thiếu p → no-op
    assert "p_value_adj" not in m3["validation"]
