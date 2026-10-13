"""P1b-5 (#23) — lớp bảo vệ 2 mức cho mọi chỗ dùng (§3.4, §8 mục 2), sau công
tắc VNSTOCK_HORIZONS. Bật khi BẤT KỲ: floor cũ của brief thật GIẢM / nhịp chỉnh
/ trung hạn GIẢM / 🚨. Cứng (floor cũ GIẢM hoặc ≥2 tín hiệu) làm đủ; mềm (đúng 1
tín hiệu, không phải floor cũ) chỉ nhắc "không mua đuổi". Floor cũ GIẢM ⇒ luôn
cứng (tập cha của hôm nay).
"""
from __future__ import annotations

import itertools

import pytest

import vnstock_horizons as hz


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)


def _view(short, medium, tier, protect=None) -> dict:
    rule = hz.stance_rule(short, medium, tier)
    snap = {"as_of": "2026-10-13", "short": short, "short_since": "2026-09-24", "score": -2,
            "n": 7, "medium": medium, "medium_since": "2026-10-02", "pending": 0,
            "levels": [], "alert": {"tier": tier, "anchor": 1853.08 if tier else None,
                                    "since": "2026-10-01" if tier else None},
            "protect": protect,
            "stance": {"forced": rule.forced, "allowed": list(rule.allowed)}}
    return {"stale": False, "snap": snap, "prev": None, "short_sessions": 5,
            "medium_weeks": 2, "breadth_pct": 30.0, "breadth_pct_4w": 31.0, "known_levels": []}


def _ctx(floor_old, short, medium, tier, protect=None, **extra) -> dict:
    from vnstock_brief import _apply_horizon_defensive, _apply_horizon_stance
    ctx = {"brief_type": "afternoon", "horizons": _view(short, medium, tier, protect), **extra}
    if floor_old:
        ctx["bias_floor"] = {"dir": floor_old, "momentum": -60 if floor_old == "GIẢM" else 60,
                             "regime_score": None}
    _apply_horizon_stance(ctx)
    _apply_horizon_defensive(ctx)
    return ctx


_WATCH = ("## 📋 Watchlist sáng mai\n1. **HPG** (Giá 26,000) — MUA vùng 25,800 · chốt lời 27,500 "
          "· cắt lỗ 25,000\n\n## 💡 Đề xuất giao dịch\n- MUA FPT (Strategy) — entry 98,000\n")


# ── Property: floor cũ GIẢM ⇒ cứng, cả 3 consumer cùng hành động ──────────────

_COMBOS = list(itertools.product(("GIẢM", "TĂNG", None), (hz.HOI, hz.CHUA_RO, hz.CHINH),
                                 (hz.TANG, hz.DI_NGANG, hz.GIAM), (0, 1),
                                 (None, "mềm", "cứng")))


@pytest.mark.parametrize("floor_old,short,medium,tier,protect", _COMBOS)
def test_protection_is_a_superset_of_today(floor_old, short, medium, tier, protect):
    from vnstock_brief import defensive_level, is_defensive
    ctx = _ctx(floor_old, short, medium, tier, protect)
    sigs = sum((floor_old == "GIẢM", short == hz.CHINH, medium == hz.GIAM, tier > 0))
    level = defensive_level(ctx)
    if floor_old == "GIẢM" or sigs >= 2 or protect == "cứng":
        assert level == "cứng" and is_defensive(ctx)
    elif sigs == 1 or protect == "mềm":
        assert level == "mềm" and not is_defensive(ctx)
    else:
        assert level is None and ctx["defensive"]["on"] is False


def test_hard_level_drives_all_three_consumers(monkeypatch):
    import vnstock_brief
    import vnstock_market_sentiment
    import vnstock_telegram
    from vnstock_brief import _BUY_DEFENSIVE_CAVEAT, apply_brief_guards
    ctx = _ctx("GIẢM", hz.CHUA_RO, hz.DI_NGANG, 0)
    out = apply_brief_guards(_WATCH, ctx)
    assert "canh MUA NẾU vượt" in out and "MUA vùng" not in out           # watchlist
    assert _BUY_DEFENSIVE_CAVEAT in out          # cảnh báo MUA (lời "lớp bảo vệ", không "GIẢM")
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")                             # Telegram
    monkeypatch.setattr(vnstock_market_sentiment, "load_market_sentiment",
                        lambda: {"momentum": -60})
    monkeypatch.setattr(vnstock_brief, "_market_floor",
                        lambda m, on_error=None: {"dir": "GIẢM", "momentum": m,
                                                  "regime_score": None})
    monkeypatch.setattr(vnstock_brief, "_load_horizons",
                        lambda c: c.__setitem__("horizons", _view(hz.CHUA_RO, hz.DI_NGANG, 0)))
    assert vnstock_telegram._market_is_bearish() is True


def test_soft_level_only_reminds_and_keeps_the_watchlist(monkeypatch):
    from vnstock_brief import (_BUY_BIAS_CAVEAT, _BUY_DEFENSIVE_CAVEAT, _SOFT_DEFENSIVE_MARK,
                               apply_brief_guards)
    ctx = _ctx(None, hz.CHINH, hz.DI_NGANG, 0)                 # đúng 1 tín hiệu: nhịp chỉnh
    out = apply_brief_guards(_WATCH, ctx)
    assert "MUA vùng 25,800" in out and "canh MUA NẾU vượt" not in out
    assert _BUY_BIAS_CAVEAT not in out and _BUY_DEFENSIVE_CAVEAT not in out
    assert out.count(_SOFT_DEFENSIVE_MARK) == 1 and "nhịp chỉnh" in out
    assert apply_brief_guards(out, ctx) == out


def test_telegram_follows_the_soft_level_too(monkeypatch):
    import vnstock_brief
    import vnstock_market_sentiment
    import vnstock_telegram
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    monkeypatch.setattr(vnstock_market_sentiment, "load_market_sentiment", lambda: {"momentum": 5})
    monkeypatch.setattr(vnstock_brief, "_market_floor", lambda m, on_error=None: None)
    monkeypatch.setattr(vnstock_brief, "_load_horizons",
                        lambda c: c.__setitem__("horizons", _view(hz.CHINH, hz.DI_NGANG, 0)))
    assert vnstock_telegram._market_is_bearish() is False      # mềm ⇒ không cảnh báo cứng


# ── Công tắc tắt ⇒ giống hệt hôm nay ─────────────────────────────────────────

@pytest.mark.parametrize("floor,expect", [("GIẢM", True), ("TĂNG", False), (None, False)])
def test_switch_off_reads_the_old_floor_only(floor, expect):
    from vnstock_brief import defensive_level, is_defensive
    ctx = {"bias_floor": {"dir": floor}} if floor else {}
    assert is_defensive(ctx) is expect
    assert defensive_level(ctx) == ("cứng" if expect else None)


def test_switch_off_portfolio_line_and_prompt_are_unchanged():
    from vnstock_brief import _portfolio_block, _portfolio_fact_line
    p = {"ticker": "HPG", "qty": 1000, "buy_price": 25.0, "last_close": 26.0, "pnl_pct": 4.0}
    assert _portfolio_fact_line(p) == "- HPG: 1,000 cp | vốn 25.00 | hiện 26.00 | lãi +4.0%"
    assert "MA50" not in _portfolio_block([p])


# ── Danh mục: trạng thái MA50 do code tính + prompt khi phòng thủ ─────────────

def test_portfolio_line_carries_the_ma50_state_when_known():
    from vnstock_brief import _portfolio_fact_line
    p = {"ticker": "HPG", "qty": 1000, "buy_price": 25.0, "last_close": 24.0, "pnl_pct": -4.0}
    assert _portfolio_fact_line({**p, "above_ma50": False}).endswith("| lỗ -4.0% | dưới MA50")
    assert _portfolio_fact_line({**p, "above_ma50": True}).endswith("| trên MA50")


def test_portfolio_prompt_under_protection_trims_below_ma50_first():
    from vnstock_brief import _portfolio_block
    p = {"ticker": "HPG", "qty": 1000, "buy_price": 25.0, "last_close": 24.0, "pnl_pct": -4.0,
         "above_ma50": False}
    block = _portfolio_block([p], defensive={"on": True, "level": "cứng",
                                             "reasons": ["trung hạn GIẢM", "🚨 mức 1"]})
    assert "KHÔNG GIA TĂNG vô điều kiện" in block and "DƯỚI MA50" in block
    assert "trung hạn GIẢM · 🚨 mức 1" in block


def test_attach_ma50_uses_the_last_50_closes(monkeypatch):
    import pandas as pd
    import vnstock_strategy
    from vnstock_brief import _attach_portfolio_ma50
    closes = [10.0] * 49 + [20.0] * 11          # MA50 của 50 phiên cuối = (39·10 + 11·20)/50
    h = pd.DataFrame({"time": pd.date_range("2026-07-01", periods=60, freq="B"), "close": closes})
    monkeypatch.setattr(vnstock_strategy, "_load_history_from_parquet", lambda t, days=0: h)
    pos = [{"ticker": "HPG"}]
    _attach_portfolio_ma50(pos)
    assert pos[0]["above_ma50"] is True


# ── Brief sáng: Hành động ưu tiên không BUY vô điều kiện ─────────────────────

@pytest.mark.parametrize("line,expect", [
    ("**Hành động ưu tiên:** BUY — ngân hàng dẫn dắt",
     "**Hành động ưu tiên:** WAIT — ngân hàng dẫn dắt (thị trường phòng thủ: chỉ mua khi giá "
     "xác nhận vượt kháng cự)"),
    ("**Hành động ưu tiên:** BUY có điều kiện — nếu vượt 1,760", None),
    ("**Hành động ưu tiên:** DEFENSIVE — hạ tỷ trọng", None),
])
def test_morning_priority_action_is_never_an_unconditional_buy(line, expect):
    from vnstock_brief import enforce_morning_action_defensive
    ctx = {**_ctx("GIẢM", hz.CHUA_RO, hz.GIAM, 0), "brief_type": "morning"}
    text = f"## 🎯 TLDR\n**Bias:** GIẢM — x\n{line}\n"
    out = enforce_morning_action_defensive(text, ctx)
    assert out == (text if expect is None else text.replace(line, expect))
    assert enforce_morning_action_defensive(out, ctx) == out
    assert enforce_morning_action_defensive(text, {"brief_type": "morning",
                                                   "bias_floor": {"dir": "GIẢM"}}) == text


# ── Caveat band phân bổ: lời mới + điều kiện lệch mới ────────────────────────

def _alloc_text(band: str, stance: str) -> str:
    return (f"## 🎯 TLDR\n**Stance ngày mai:** {stance} — x\n\n## 📚 Báo cáo vĩ mô & phân bổ\n"
            f"- 🧭 Band phân bổ tháng: {band} (x) — điểm +0.10, phiên 2026-10-13\n")


@pytest.mark.parametrize("band,stance,floor_old,short,medium,clash", [
    ("B1", "TRUNG TÍNH", None, hz.CHINH, hz.DI_NGANG, True),   # B0/B1 + bảo vệ (mềm vẫn tính)
    ("B1", "TRUNG TÍNH", None, hz.CHUA_RO, hz.DI_NGANG, False),
    ("B4", "TĂNG", None, hz.HOI, hz.TANG, True),                # B3/B4 + Stance TĂNG
    ("B4", "GIẢM", None, hz.CHINH, hz.GIAM, False),
])
def test_allocation_caveat_new_wording_and_conditions(band, stance, floor_old, short, medium,
                                                      clash):
    from vnstock_brief import _ALLOC_HORIZON_CAVEAT_3K, enforce_allocation_table
    ctx = _ctx(floor_old, short, medium, 0, allocation={"band": band, "allocation": {}})
    out = enforce_allocation_table(_alloc_text(band, stance), ctx)
    assert (_ALLOC_HORIZON_CAVEAT_3K in out) is clash
    assert "tỷ trọng theo band và xu hướng trung hạn; nhịp ngày chỉ chọn thời điểm" in \
        _ALLOC_HORIZON_CAVEAT_3K
