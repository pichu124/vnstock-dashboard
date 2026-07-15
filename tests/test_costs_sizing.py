"""Tests cho 3 món mượn từ khảo sát nautilus_trader (2026-07-14):
1. Chi phí giao dịch round-trip trừ vào pnl backtest (_cost_roundtrip_pct).
2. Thứ tự chạm TP/SL trong bar theo cực-trị-gần-open (_bar_high_first),
   áp cả _simulate_trade (backtest) lẫn _grade_rec (reconcile rec thật).
3. Khối lượng gợi ý fixed-risk (suggest_position_size) — display-only.

Hermetic: config trỏ tmp_path, env monkeypatch — không DB, không mạng.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import vnstock_strategy as vs
import vnstock_train as vt


@pytest.fixture(autouse=True)
def _fixed_cost(monkeypatch):
    # chốt phí 0.4 để test không phụ thuộc env máy chạy
    monkeypatch.setenv("VNSTOCK_COST_ROUNDTRIP_PCT", "0.4")


def _bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


def _future(*bars):
    return pd.DataFrame([_bar(*b) for b in bars])


def _sig(action="buy", entry=100.0, tp=110.0, sl=95.0):
    return {"action": action, "entry": entry, "tp": tp, "sl": sl,
            "confidence": 0.5}


# ── Món 1: chi phí giao dịch ─────────────────────────────────────────────────


def test_cost_subtracted_on_tp():
    fut = _future((101, 111, 100, 110))          # chạm TP 110, không chạm SL
    pnl, reason = vs._simulate_trade(fut, _sig())
    assert reason == "tp"
    assert pnl == pytest.approx(10.0 - 0.4)      # gross +10% → net +9.6%


def test_cost_subtracted_on_sl_and_expire():
    pnl, reason = vs._simulate_trade(_future((100, 102, 94, 96)), _sig())
    assert reason == "sl" and pnl == pytest.approx(-5.0 - 0.4)
    pnl, reason = vs._simulate_trade(_future((100, 103, 99, 102)), _sig())
    assert reason == "expire" and pnl == pytest.approx(2.0 - 0.4)


def test_cost_env_override_and_hold_free(monkeypatch):
    monkeypatch.setenv("VNSTOCK_COST_ROUNDTRIP_PCT", "0")
    pnl, reason = vs._simulate_trade(_future((101, 111, 100, 110)), _sig())
    assert pnl == pytest.approx(10.0)            # 0 → về gross
    monkeypatch.setenv("VNSTOCK_COST_ROUNDTRIP_PCT", "rác")
    assert vs._cost_roundtrip_pct() == 0.4       # rác → default
    # hold/no_data không có lệnh → không trừ phí
    assert vs._simulate_trade(_future((100, 101, 99, 100)),
                              _sig(action="hold")) == (0.0, "hold")


# ── Món 2: _bar_high_first + thứ tự trong bar ────────────────────────────────


def test_bar_high_first_heuristic():
    assert vs._bar_high_first(_bar(109, 111, 94, 95)) is True    # open sát high
    assert vs._bar_high_first(_bar(95, 111, 94, 110)) is False   # open sát low
    assert vs._bar_high_first({"high": 111, "low": 94}) is None  # thiếu open
    assert vs._bar_high_first(_bar(float("nan"), 111, 94, 95)) is None


def test_buy_bar_hits_both_open_decides():
    # bar chứa CẢ TP(110) lẫn SL(95): open 109 sát high → TP chạm trước
    pnl, reason = vs._simulate_trade(_future((109, 111, 94, 95)), _sig())
    assert reason == "tp" and pnl == pytest.approx(10.0 - 0.4)
    # open 96 sát low → SL chạm trước
    pnl, reason = vs._simulate_trade(_future((96, 111, 94, 110)), _sig())
    assert reason == "sl" and pnl == pytest.approx(-5.0 - 0.4)


def test_buy_bar_hits_both_missing_open_pessimistic():
    fut = pd.DataFrame([{"high": 111.0, "low": 94.0, "close": 95.0}])
    pnl, reason = vs._simulate_trade(fut, _sig())
    assert reason == "sl"                        # không quyết được → SL thắng


def test_sell_bar_hits_both_symmetric():
    # sell: SL phía TRÊN (105), TP phía DƯỚI (90)
    sig = _sig(action="sell", entry=100.0, tp=90.0, sl=105.0)
    # open sát low → low (TP) chạm trước
    pnl, reason = vs._simulate_trade(_future((91, 106, 89, 105)), sig)
    assert reason == "tp" and pnl == pytest.approx((100 / 90 - 1) * 100 - 0.4)
    # open sát high → high (SL) chạm trước
    pnl, reason = vs._simulate_trade(_future((104, 106, 89, 90)), sig)
    assert reason == "sl"


def test_grade_rec_adaptive_and_pessimistic():
    # reconcile rec thật dùng CÙNG heuristic nhưng pnl GROSS (exit=giá đích)
    post = _future((109, 111, 94, 95))
    assert vt._grade_rec(post, 100.0, 110.0, 95.0) == (110.0, "tp")
    post = _future((96, 111, 94, 110))
    assert vt._grade_rec(post, 100.0, 110.0, 95.0) == (95.0, "sl")
    post = pd.DataFrame([{"high": 111.0, "low": 94.0, "close": 95.0}])
    assert vt._grade_rec(post, 100.0, 110.0, 95.0) == (95.0, "sl")
    # không chạm gì → expire tại close cuối; entry 0 → expire luôn
    post = _future((100, 103, 99, 102))
    assert vt._grade_rec(post, 100.0, 110.0, 95.0) == (102.0, "expire")
    assert vt._grade_rec(post, 0.0, 110.0, 95.0) == (102.0, "expire")


# ── Món 3: suggest_position_size ─────────────────────────────────────────────


@pytest.fixture
def _tmp_sizing(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "_SIZING_CONFIG", tmp_path / "sizing_config.json")


def test_sizing_basic_math(_tmp_sizing):
    vs.save_sizing_config(nav_million=500, risk_pct=1.0)
    # risk money 5tr; rủi ro/cp (25−24)×1000=1000đ + phí 25000×0.4%=100đ
    # → 5tr/1100 = 4545 → lô 100 → 4500 cp; giá trị 112.5tr < cap 125tr
    s = vs.suggest_position_size(25.0, 24.0)
    assert s["qty"] == 4500 and s["capped"] is False
    assert s["value_million"] == pytest.approx(112.5)
    assert s["risk_pct"] == 1.0 and s["nav_million"] == 500


def test_sizing_caps_position_value(_tmp_sizing):
    vs.save_sizing_config(nav_million=500, risk_pct=1.0)
    # SL sát entry → qty khổng lồ → cap 25% NAV = 125tr → 125tr/25.000đ = 5000
    s = vs.suggest_position_size(25.0, 24.9)
    assert s["capped"] is True and s["qty"] == 5000
    assert s["value_million"] <= 0.25 * 500 + 1e-6


def test_sizing_silent_without_nav_or_bad_inputs(_tmp_sizing):
    assert vs.suggest_position_size(25.0, 24.0) is None      # chưa cấu hình
    vs.save_sizing_config(nav_million=500)
    assert vs.suggest_position_size(0, 24.0) is None
    assert vs.suggest_position_size(25.0, 0) is None
    assert vs.suggest_position_size(25.0, 26.0) is None      # SL trên entry
    assert vs.suggest_position_size("x", 24.0) is None
    # NAV quá nhỏ → dưới 1 lô → None (không gợi ý 0 cp)
    vs.save_sizing_config(nav_million=1, risk_pct=0.5)
    assert vs.suggest_position_size(500.0, 400.0) is None


def test_sizing_config_roundtrip_and_off_switch(_tmp_sizing):
    cfg = vs.save_sizing_config(nav_million=300, risk_pct=2.0,
                                max_position_pct=20)
    assert cfg == vs.load_sizing_config()
    on_disk = json.loads(vs._SIZING_CONFIG.read_text(encoding="utf-8"))
    assert on_disk["nav_million"] == 300
    # NAV = 0 → tắt (None), field khác giữ nguyên
    cfg = vs.save_sizing_config(nav_million=0)
    assert cfg["nav_million"] is None and cfg["risk_pct"] == 2.0
    assert vs.suggest_position_size(25.0, 24.0) is None
    # file hỏng → defaults, không nổ
    vs._SIZING_CONFIG.write_text("{rác", encoding="utf-8")
    assert vs.load_sizing_config()["nav_million"] is None


def test_sizing_explicit_args_override_config(_tmp_sizing):
    # không có file config nhưng truyền thẳng NAV/risk vẫn tính được
    s = vs.suggest_position_size(25.0, 24.0, nav_million=500, risk_pct=1.0)
    assert s and s["qty"] == 4500


# ── Cap thanh khoản (zipline VolumeShareSlippage, khảo sát 15/07) ────────────


def test_sizing_liquidity_cap(_tmp_sizing):
    vs.save_sizing_config(nav_million=500, risk_pct=1.0)
    # không cap: 4500 cp; ADV 20.000 cp → cap 10% = 2.000 cp
    s = vs.suggest_position_size(25.0, 24.0, adv_shares=20_000)
    assert s["qty"] == 2000 and s["capped_adv"] is True
    # ADV dồi dào → không đụng
    s = vs.suggest_position_size(25.0, 24.0, adv_shares=1_000_000)
    assert s["qty"] == 4500 and s["capped_adv"] is False
    # ADV rác/None/0 → bỏ qua cap, không nổ
    for adv in (None, 0, "rác", float("nan")):
        s = vs.suggest_position_size(25.0, 24.0, adv_shares=adv)
        assert s and s["qty"] == 4500 and s["capped_adv"] is False
    # mã quá mỏng → cap dưới 1 lô → None (không gợi ý 0 cp)
    assert vs.suggest_position_size(25.0, 24.0, adv_shares=500) is None


def test_sizing_max_adv_pct_configurable(_tmp_sizing):
    vs.save_sizing_config(nav_million=500, risk_pct=1.0, max_adv_pct=25)
    s = vs.suggest_position_size(25.0, 24.0, adv_shares=10_000)
    assert s["qty"] == 2500 and s["capped_adv"] is True
    assert vs.load_sizing_config()["max_adv_pct"] == 25.0


# ── SL trailing gợi ý (Lean TrailingStopRiskManagementModel, 15/07) ──────────


def test_trailing_stop_hint_rises_with_peak():
    # entry 25, SL 24; giá chạy lên đỉnh 27 → trail = 27×0.95 = 25.65 > SL gốc
    assert vs.trailing_stop_hint(24.0, [25.0, 26.0, 27.0, 26.5]) == \
        pytest.approx(25.65)
    # đỉnh quyết định, không phải close cuối
    assert vs.trailing_stop_hint(24.0, [27.0, 25.0]) == pytest.approx(25.65)


def test_trailing_stop_hint_silent_when_not_meaningful():
    # trail dưới/ngang SL gốc (+0.5% biên) → None, khỏi gợi ý hạ SL
    assert vs.trailing_stop_hint(24.0, [25.0, 25.2]) is None   # 25.2×0.95=23.94
    assert vs.trailing_stop_hint(24.0, [25.3]) is None         # 24.035 ≤ 24×1.005
    # rỗng / giá rác / SL rác → None, không nổ
    assert vs.trailing_stop_hint(24.0, []) is None
    assert vs.trailing_stop_hint(24.0, [0, None]) is None
    assert vs.trailing_stop_hint("x", [25.0]) is None


def test_trailing_stop_hint_custom_pct():
    # trail_pct 3% bám sát hơn: 27×0.97 = 26.19
    assert vs.trailing_stop_hint(24.0, [27.0], trail_pct=3.0) == \
        pytest.approx(26.19)
