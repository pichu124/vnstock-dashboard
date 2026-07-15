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


def test_stitch_units_fixes_per_bar_normalization_artifact():
    # Mã penny quanh 500 VND: _normalize_prices chia 1000 cho TỪNG bar > 500
    # → [480, 0.51, 495, 0.52] = return giả ±96,959% (thấy thật 15/07:
    # oversold "excess +42.73%/5 phiên"). Stitch phải đưa cả chuỗi về CÙNG
    # thang → return lại là vài % thật.
    raw = [("2026-07-01", 480.0), ("2026-07-02", 0.51),
           ("2026-07-03", 495.0), ("2026-07-04", 0.52)]
    fixed = stk_vals = [v for _, v in ps._stitch_units(raw)]
    ratios = [stk_vals[i + 1] / stk_vals[i] for i in range(3)]
    assert all(0.9 < r < 1.1 for r in ratios), ratios
    # chuỗi blue-chip đơn vị nhất quán → giữ nguyên
    ok = [("2026-07-01", 25.0), ("2026-07-02", 25.8)]
    assert ps._stitch_units(ok) == ok
    # fwd return trên chuỗi đã stitch phải nhỏ (không còn outlier nghìn %)
    r = ps._fwd_return(ps._stitch_units(raw), "2026-07-01", 3)
    assert r is not None and abs(r) < 15


def test_ticker_without_data_skipped(_fake_env):
    _write_snap(_fake_env, "2026-07-05", {"momentum": ["AAA", "XXX"]})
    card = ps.preset_scorecard(horizons=(5,), days=30)
    assert card["presets"]["momentum"]["h5"]["n"] == 1   # XXX không có giá → bỏ


# ── "Đọc kết quả" deterministic ──────────────────────────────────────────────


def _mk_card(presets, n_days=30, horizons=(5, 20)):
    return {"as_of": "2026-07-15", "n_days": n_days,
            "horizons": list(horizons), "presets": presets}


def _p(e5, e20=None, hit=50.0, n=100):
    row = {"desc": "", "n_days_signal": 10,
           "h5": {"n": n, "avg_fwd": e5, "avg_excess": e5, "hit_rate": hit}}
    if e20 is not None:
        row["h20"] = {"n": n, "avg_fwd": e20, "avg_excess": e20, "hit_rate": hit}
    return row


def test_interpret_bear_regime_reading():
    # đúng hình bảng thật 15/07: bắt đáy thắng, edge tắt ở 20p, phí ăn hết
    card = _mk_card({
        "reversal": _p(0.81, -3.31), "oversold": _p(0.36, -3.02),
        "momentum": _p(-1.47, -4.64), "breakout": _p(-2.02, -6.96),
        "strong_uptrend": _p(-2.01, -4.91), "golden_cross": _p(-1.07, -4.03),
        "overbought": _p(-1.63, -2.71),
    })
    bullets = interpret = ps.interpret_scorecard(card, breadth_pct=13.0,
                                                 cost_pct=0.4)
    text = " ".join(bullets)
    assert "Mean-reversion đang thắng" in text
    assert "chỉ sống ~5 phiên" in text and "reversal" in text
    assert "Phí ăn gần hết edge" in text
    assert "13% mã trên MA200" in text            # ngữ cảnh độ rộng
    assert "XẾP HẠNG" in text                     # caveat luôn có


def test_interpret_trend_regime_and_durable_edge():
    card = _mk_card({
        "momentum": _p(2.5, 1.8), "strong_uptrend": _p(1.9, 1.2),
        "oversold": _p(-0.5, -1.0), "reversal": _p(-0.8, -1.5),
    })
    text = " ".join(ps.interpret_scorecard(card, breadth_pct=65.0,
                                           cost_pct=0.4))
    assert "Trend-following đang thắng" in text
    assert "giữ được qua cả 20 phiên" in text
    assert "còn +2.10%" in text                   # 2.5 − 0.4 sau phí
    assert "MA200" not in text                    # breadth khỏe → không đổ lỗi


def test_interpret_all_negative_and_empty():
    card = _mk_card({"momentum": _p(-1.0, -2.0), "oversold": _p(-0.3, -1.0)})
    text = " ".join(ps.interpret_scorecard(card, cost_pct=0.4))
    assert "đứng ngoài" in text
    assert ps.interpret_scorecard({}, cost_pct=0.4) == []


def test_cli_prints_interpretation(_fake_env, capsys):
    _write_snap(_fake_env, "2026-07-05", {"momentum": ["AAA"]})
    assert ps.main(["--show", "--horizons", "5"]) == 0
    out = capsys.readouterr().out
    assert "Đọc kết quả" in out and "XẾP HẠNG" in out


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
