"""P1b-1 (#19) — một nguồn "thị trường phòng thủ" (floor cũ) cho brief, guard,
Telegram; prompt không đổi một byte (golden chụp TRƯỚC khi tách khối)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

_GOLDEN = Path(__file__).parent / "golden" / "brief_prompt_p1b1.json"

# Luật floor cũ (docstring `_bias_floor_dir`): GIẢM khi momentum ≤ −50 HOẶC regime
# ≤ −3; TĂNG khi momentum ≥ 50 HOẶC regime ≥ 3; hai chiều cùng bật ⇒ không ép.
_FLOOR_TABLE = [
    ((-67, -5), "GIẢM"),
    ((-50, None), "GIẢM"),
    ((None, -3), "GIẢM"),
    ((-49, -2), None),
    ((55, None), "TĂNG"),
    ((None, 3), "TĂNG"),
    ((49, 2), None),
    ((-60, 4), None),     # mâu thuẫn
    ((60, -4), None),     # mâu thuẫn
    ((None, None), None),
]


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")      # nền khung cũ (mặc định BẬT từ 14/10)


# ── Seam 1: prompt sáng + chiều giống từng byte (golden chụp 13/10 trước khi tách) ──

def _golden_cases():
    floors = {"none": None,
              "giam": {"dir": "GIẢM", "momentum": -67, "regime_score": -5},
              "tang": {"dir": "TĂNG", "momentum": 55, "regime_score": None}}
    quant = {"no_quant": {},
             "quant": {"quant_regime": {"regime": "❄️ Risk-off", "conviction": -0.42,
                                        "detail": "breadth 9%"},
                       "vol_regime": "high"}}
    for fk, fl in floors.items():
        for qk, q in quant.items():
            for bt, tm in (("morning", "11:30"), ("afternoon", "15:30")):
                ctx = {"date": "2026-10-02", "time": tm, **q}
                if fl:
                    ctx["bias_floor"] = fl
                yield f"{fk}|{qk}|{bt}", ctx, bt


def _segment(t: str) -> str:
    i = t.find("\n## 🧭 RÀNG BUỘC BIAS")
    if i < 0:
        i = t.find("\n## Quant Market Regime")
    q = t.find("\n## Quant Market Regime")
    j = t.find("\n## ", q + 5)
    return t[i:j if j > 0 else len(t)]


@pytest.mark.parametrize("key,ctx,bt", list(_golden_cases()), ids=lambda v: v if isinstance(v, str) else "")
def test_prompt_is_byte_identical_to_pre_refactor_golden(key, ctx, bt):
    from vnstock_brief import build_prompt
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))[key]
    p = build_prompt(ctx, brief_type=bt)
    assert _segment(p) == golden["segment"]          # khối bias + quant: diff đọc được
    assert hashlib.sha256(p.encode()).hexdigest() == golden["sha256"], (
        "khối bias/quant giữ nguyên nhưng phần KHÁC của prompt đã đổi")


# ── Seam 2: floor_dir / is_defensive ───────────────────────────────────────

@pytest.mark.parametrize("sig,expect", _FLOOR_TABLE)
def test_bias_floor_dir_follows_the_documented_rule(sig, expect):
    from vnstock_brief import _bias_floor_dir
    assert _bias_floor_dir(*sig) == expect


@pytest.mark.parametrize("ctx,expect", [
    (None, None),
    ({}, None),
    ({"bias_floor": None}, None),
    ({"bias_floor": {}}, None),
    ({"bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -5}}, "GIẢM"),
    ({"bias_floor": {"dir": "TĂNG"}}, "TĂNG"),
])
def test_floor_dir_and_is_defensive_read_ctx_safely(ctx, expect):
    from vnstock_brief import floor_dir, is_defensive
    assert floor_dir(ctx) == expect
    assert is_defensive(ctx) is (expect == "GIẢM")


@pytest.mark.parametrize("guard", ["enforce_watchlist_hygiene", "enforce_buy_vs_bias_caveat",
                                   "enforce_allocation_table"])
def test_guards_do_not_crash_when_bias_floor_is_none(guard):
    import vnstock_brief
    text = ("## 🎯 TLDR\n**Stance ngày mai:** TRUNG TÍNH\n\n## 📋 Watchlist sáng mai\n"
            "1. HPG — MUA vùng 25.5–26.0, SL 24.8\n")
    out = getattr(vnstock_brief, guard)(text, {"bias_floor": None})
    assert isinstance(out, str)


def test_market_floor_builds_the_ctx_record_from_momentum_and_regime(monkeypatch):
    import vnstock_regime
    import vnstock_brief
    monkeypatch.setattr(vnstock_regime, "load_regime", lambda: {"score": -4})
    assert vnstock_brief._market_floor(-10) == {"dir": "GIẢM", "momentum": -10, "regime_score": -4}
    monkeypatch.setattr(vnstock_regime, "load_regime", lambda: {"score": 1})
    assert vnstock_brief._market_floor(-10) is None
    errs = []
    monkeypatch.setattr(vnstock_regime, "load_regime", lambda: 1 / 0)
    assert vnstock_brief._market_floor(-55, on_error=errs.append) == {
        "dir": "GIẢM", "momentum": -55, "regime_score": None}
    assert len(errs) == 1 and isinstance(errs[0], ZeroDivisionError)


# ── Seam 3: Telegram ra cùng quyết định với brief ────────────────────────────

@pytest.mark.parametrize("sig,expect", _FLOOR_TABLE)
def test_telegram_market_is_bearish_matches_the_floor_rule(monkeypatch, sig, expect):
    import vnstock_market_sentiment
    import vnstock_regime
    import vnstock_telegram
    mom, reg = sig
    monkeypatch.setattr(vnstock_market_sentiment, "load_market_sentiment",
                        lambda: {"momentum": mom} if mom is not None else {})
    monkeypatch.setattr(vnstock_regime, "load_regime",
                        lambda: {"score": reg} if reg is not None else {})
    assert vnstock_telegram._market_is_bearish() is (expect == "GIẢM")


def test_telegram_bearish_is_false_when_loaders_fail(monkeypatch):
    import vnstock_market_sentiment
    import vnstock_regime
    import vnstock_telegram
    monkeypatch.setattr(vnstock_market_sentiment, "load_market_sentiment", lambda: 1 / 0)
    monkeypatch.setattr(vnstock_regime, "load_regime", lambda: 1 / 0)
    assert vnstock_telegram._market_is_bearish() is False


# ── Header Telegram: 3 dòng thị trường giống từng byte (hàm cũ, chụp 13/10) ──

def test_telegram_market_header_lines_are_byte_identical(monkeypatch):
    import vnstock_market_sentiment
    import vnstock_regime
    import vnstock_telegram
    monkeypatch.setattr(vnstock_regime, "_load_vnindex_tech",
                        lambda: {"close": 1737.71, "rsi14": 31.4})
    monkeypatch.setattr(vnstock_regime, "load_regime", lambda: {
        "label": "❄️ Bear — Risk-off", "score": -5, "n_signals": 7, "confidence": 0.71,
        "signals": [{"name": "MA200", "value": "dưới", "direction": -1},
                    {"name": "RSI", "value": "31", "direction": -1},
                    {"name": "NN", "value": "-3,297 tỷ", "direction": -2},
                    {"name": "A/D", "value": "0.6", "direction": 0}]})
    monkeypatch.setattr(vnstock_market_sentiment, "load_market_sentiment", lambda: {
        "mood": "😨 Sợ hãi", "momentum": -67, "n_signals": 5})
    got = "\n".join(b for b in vnstock_telegram._market_header_lines() if b is not None)
    assert got == (
        "🌏 VNINDEX: <b>1,737.7</b> | RSI 31\n"
        "⚖️ <b>Regime:</b> ❄️ Bear — Risk-off  (score -5/7, conviction 71%)\n"
        "   🔴 NN: -3,297 tỷ | 🔴 MA200: dưới | 🔴 RSI: 31\n"
        "🧭 <b>Tâm lý:</b> 😨 Sợ hãi (momentum -67/100, 5 tín hiệu)")
