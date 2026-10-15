"""P1b-6 (#24) — từ vựng & nhãn 3 khung (§3.1, §3.12, mẫu §4 D) sau công tắc
VNSTOCK_HORIZONS: một hàm nhãn cho regime + quant; label_old của chạy bóng KHÔNG
đổi; guard từ vựng (Risk-on/off cấp thị trường ⇒ "điểm kỹ thuật ngày …", "đảo
chiều xu hướng thị trường" khi trung hạn không đổi ⇒ chỉ ĐẾM); gạch 🔭 trong TLDR
brief sáng; badge tab Thị trường.
"""
from __future__ import annotations

import pandas as pd
import pytest

import vnstock_horizons as hz


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")      # nền khung cũ (mặc định BẬT từ 14/10)


def _view(medium=hz.GIAM, prev_medium=hz.GIAM, short=hz.CHINH, stale=False) -> dict:
    if stale:
        return {"stale": True, "as_of": "2026-10-09", "reason": "cũ"}
    rule = hz.stance_rule(short, medium, 1)
    snap = {"as_of": "2026-10-13", "short": short, "short_since": "2026-09-24", "score": -7,
            "n": 7, "medium": medium, "medium_since": "2026-10-02", "pending": 0,
            "levels": [], "alert": {"tier": 1, "anchor": 1853.08, "since": "2026-10-01"},
            "stance": {"forced": rule.forced, "allowed": list(rule.allowed)}}
    prev = {**snap, "as_of": "2026-10-12", "medium": prev_medium}
    return {"stale": False, "snap": snap, "prev": prev, "short_sessions": 14,
            "medium_weeks": 2, "breadth_pct": 9.0, "breadth_pct_4w": 11.0, "known_levels": []}


# ── Một hàm nhãn, có điều kiện theo công tắc ─────────────────────────────────

@pytest.mark.parametrize("regime,old,new", [
    ("bull", "🔥 Bull — Risk-on", "🟢 Kỹ thuật ngày: rất tích cực"),
    ("bullish", "📈 Tích cực", "🟢 Kỹ thuật ngày: tích cực"),
    ("sideways", "⚖️ Sideways / Phân hoá", "⚖️ Kỹ thuật ngày: trung tính / phân hoá"),
    ("bearish", "📉 Tiêu cực", "🔴 Kỹ thuật ngày: tiêu cực"),
    ("bear", "❄️ Bear — Risk-off", "🔴 Kỹ thuật ngày: rất tiêu cực"),
])
def test_regime_label_follows_the_switch(monkeypatch, regime, old, new):
    import vnstock_regime as rg
    assert rg.vocab_label(old) == old
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    assert rg.vocab_label(old) == new


def test_classify_regime_keeps_label_old_for_the_shadow_run(monkeypatch):
    import vnstock_regime as rg
    tech = {"close": 1700.0, "ma20": 1800.0, "ma50": 1810.0, "ma200": 1750.0, "rsi14": 28.0,
            "day_change_pct": -2.0}
    off = rg.classify_regime(tech, {"above_ma200_pct": 9, "advances": 50, "declines": 300},
                             -2000.0)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    on = rg.classify_regime(tech, {"above_ma200_pct": 9, "advances": 50, "declines": 300},
                            -2000.0)
    assert on["label_old"] == off["label_old"] == off["label"] == "❄️ Bear — Risk-off"
    assert on["label"] == "🔴 Kỹ thuật ngày: rất tiêu cực"


def test_shadow_inputs_store_the_old_label_even_with_the_switch_on(monkeypatch):
    from datetime import date, timedelta
    import vnstock_horizons_state as hs
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    d0 = date(2025, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(260)]
    closes = [1800.0 - i * 0.5 for i in range(260)]
    out = hs.score_inputs(dates, closes, [dates[-1]], {}, {})
    assert "Kỹ thuật ngày" not in out[dates[-1]]["label_old"]


@pytest.mark.parametrize("old,new", [
    ("🔥 Risk-on", "🟢 Dòng tiền ngành nghiêng mạnh tích cực"),
    ("❄️ Risk-off", "🔴 Dòng tiền ngành nghiêng mạnh tiêu cực"),
    ("📈 Slight bullish bias", "📈 Dòng tiền ngành nghiêng tích cực"),
    ("📉 Slight bearish bias", "📉 Dòng tiền ngành nghiêng tiêu cực"),
    ("⚖️ Neutral / Phân hoá", "⚖️ Dòng tiền ngành trung tính / phân hoá"),
])
def test_quant_label_goes_through_the_same_function(monkeypatch, old, new):
    import vnstock_regime as rg
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    assert rg.vocab_label(old) == new


def test_market_regime_uses_the_label_function(monkeypatch):
    from vnstock_market_analyzer import market_regime
    scores = pd.DataFrame({"composite": [-1.5, -1.2, -0.8, -0.9, -0.6]})
    assert market_regime(scores)["regime"] == "❄️ Risk-off"
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    assert market_regime(scores)["regime"] == "🔴 Dòng tiền ngành nghiêng mạnh tiêu cực"


def test_prompt_header_follows_the_switch():
    from vnstock_brief import _quant_regime_prompt_lines
    q = {"quant_regime": {"regime": "x", "conviction": 0.1, "detail": "d"}}
    assert "## Quant Market Regime" in _quant_regime_prompt_lines(q)[0]
    on = _quant_regime_prompt_lines({**q, "horizons": _view()})[0]
    assert "## Độ nghiêng điểm quant các ngành (khung ngày)" in on
    assert "Quant Market Regime" not in on and "## Dòng tiền ngành" not in on   # trùng block NN


# ── Guard từ vựng ───────────────────────────────────────────────────────────

_BRIEF = """## 🎯 TLDR
**Kết quả phiên:** VNINDEX giảm, thị trường Risk-off rõ.
**Stance ngày mai:** GIẢM — x

## 🔭 Góc nhìn theo khung thời gian
- Ngắn hạn (vài phiên): nhịp chỉnh. → Tâm lý risk-off.

## 📊 Tổng kết phiên
Regime ❄️ Bear — Risk-off kéo dài; HPG đảo chiều tăng; mẫu hình đảo chiều ở FPT.
"""


def test_vocab_guard_rewrites_market_level_risk_on_off_only_outside_the_section():
    from vnstock_brief import enforce_horizon_vocab
    ctx = {"brief_type": "afternoon", "horizons": _view()}
    out = enforce_horizon_vocab(_BRIEF, ctx)
    assert "thị trường điểm kỹ thuật ngày -7/7 rõ" in out          # số từ ctx, không đoán chiều
    assert "Regime điểm kỹ thuật ngày -7/7 kéo dài" in out
    assert "→ Tâm lý risk-off." in out                          # dòng 🔭 không đụng
    assert "HPG đảo chiều tăng; mẫu hình đảo chiều ở FPT." in out
    assert enforce_horizon_vocab(out, ctx) == out
    assert enforce_horizon_vocab(_BRIEF, {"brief_type": "afternoon"}) == _BRIEF


@pytest.mark.parametrize("text,medium,prev,n", [
    ("Thị trường đảo chiều xu hướng sang tăng.", hz.GIAM, hz.GIAM, 1),
    ("VNINDEX có dấu hiệu đảo chiều xu hướng.", hz.GIAM, hz.GIAM, 1),
    ("Thị trường đảo chiều xu hướng sang giảm.", hz.GIAM, hz.DI_NGANG, 0),   # trung hạn đổi thật
    ("HPG đảo chiều xu hướng tăng.", hz.GIAM, hz.GIAM, 0),                  # mã
    ("HPG đảo chiều xu hướng, vượt trội thị trường.", hz.GIAM, hz.GIAM, 0), # mã, có chữ thị trường
    ("VNINDEX đóng 1,737.71, đảo chiều xu hướng.", hz.GIAM, hz.GIAM, 1),     # số thập phân
    ("Thị trường hình thành mẫu hình đảo chiều.", hz.GIAM, hz.GIAM, 0),     # mẫu hình
])
def test_trend_reversal_claims_are_only_counted(text, medium, prev, n):
    from vnstock_brief_watch import scan_trend_reversal
    ctx = {"horizons": _view(medium=medium, prev_medium=prev)}
    events = scan_trend_reversal(f"## 📊 Tổng kết phiên\n{text}\n", ctx)
    assert len(events) == n
    if n:
        assert events[0]["kind"] == "trend_reversal_claim"


def test_trend_reversal_ignores_the_horizon_section_and_switch_off():
    from vnstock_brief_watch import scan_trend_reversal
    text = ("## 🔭 Góc nhìn theo khung thời gian\n- Trung hạn: → thị trường đảo chiều xu hướng.\n")
    assert scan_trend_reversal(text, {"horizons": _view()}) == []
    assert scan_trend_reversal("Thị trường đảo chiều xu hướng.", {}) == []


# ── Brief sáng: 1 gạch 🔭 trong TLDR (mẫu §4 D) ─────────────────────────────

def _morning_ctx(view=None, **extra) -> dict:
    return {"brief_type": "morning", "horizons": view or _view(),
            "allocation": {"band": "B4", "allocation": {"Cổ phiếu": 15}},
            "defensive": {"on": True, "level": "cứng", "reasons": ["nhịp chỉnh"]}, **extra}


def test_morning_line_matches_sample_d():
    from vnstock_brief import _horizon_morning_line
    assert _horizon_morning_line(_morning_ctx()) == (
        "- 🔭 Trung hạn GIẢM (2 lần đóng tuần) · ngắn hạn: nhịp chỉnh (phiên 14) · 💼 15% — "
        "Bias GIẢM; không BUY vô điều kiện")
    flat = _view(medium=hz.DI_NGANG, prev_medium=hz.DI_NGANG, short=hz.CHUA_RO)
    assert _horizon_morning_line(_morning_ctx(flat, defensive={"on": False, "level": None})) \
        == ("- 🔭 Trung hạn ĐI NGANG (2 lần đóng tuần) · ngắn hạn: chưa rõ (phiên 14) · 💼 15% — "
            "Bias chỉ TRUNG TÍNH/GIẢM")
    assert _horizon_morning_line(_morning_ctx(_view(stale=True))) == \
        "- 🔭 chưa cập nhật (as_of 09/10)."


def test_morning_guard_puts_the_line_in_the_tldr():
    from vnstock_brief import _horizon_morning_line, enforce_horizon_view
    text = ("## 🎯 TLDR\n**Bias:** GIẢM — x\n**Hành động ưu tiên:** WAIT — y\n\n"
            "## 📊 Tổng quan phiên sáng\nz\n")
    ctx = _morning_ctx()
    out = enforce_horizon_view(text, ctx)
    lines = out.split("\n")
    assert lines[3] == _horizon_morning_line(ctx) and "## 🔭" not in out
    assert enforce_horizon_view(out, ctx) == out


def test_switch_off_morning_is_untouched():
    from vnstock_brief import enforce_horizon_view
    text = "## 🎯 TLDR\n**Bias:** GIẢM — x\n"
    assert enforce_horizon_view(text, {"brief_type": "morning"}) == text


# ── Tab Thị trường: badge trung hạn + ngắn hạn ──────────────────────────────

def test_market_tab_badges(monkeypatch):
    import vnstock_horizons_state as hs
    from dashboard import market_tab
    assert market_tab._horizon_badges() == []                     # công tắc tắt
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    monkeypatch.setattr(hs, "latest_published", lambda *a, **k: "LP")
    monkeypatch.setattr(hs, "brief_view", lambda lp: _view())
    badges = market_tab._horizon_badges()
    assert badges == ["🔭 Trung hạn: GIẢM (từ 02/10, 2 lần đóng tuần)",
                      "Ngắn hạn: nhịp chỉnh (phiên 14) · điểm -7/7",
                      "🚨 Rủi ro ngắn hạn: mức 1"]
    monkeypatch.setattr(hs, "brief_view", lambda lp: _view(stale=True))
    assert market_tab._horizon_badges() == ["🔭 3 khung: chưa cập nhật (as_of 09/10)"]


def test_morning_line_survives_the_whole_guard_chain():
    from vnstock_brief import _horizon_morning_line, apply_brief_guards
    text = ("## 🎯 TLDR\n**Bias:** GIẢM — x\n**Hành động ưu tiên:** BUY — ngân hàng\n\n"
            "## 📊 Tổng quan phiên sáng\nz\n")
    ctx = _morning_ctx()
    once = apply_brief_guards(text, ctx)
    assert _horizon_morning_line(ctx) in once.split("\n")
    assert apply_brief_guards(once, dict(ctx)) == once



@pytest.mark.parametrize("line", [
    "📰 Asian stocks slide as Risk-off mood deepens — Reuters",
    "Tâm lý risk-off toàn cầu lan sang châu Á.",
    "Dòng tiền risk-on vào nhóm chứng khoán.",
    "Thị trường Mỹ risk-off sau số CPI.",
])
def test_vocab_guard_leaves_non_market_or_foreign_text(line):
    from vnstock_brief import enforce_horizon_vocab
    ctx = {"brief_type": "afternoon", "horizons": _view()}
    text = f"## 📊 Tổng kết phiên\n{line}\n"
    assert enforce_horizon_vocab(text, ctx) == text


def test_vocab_guard_skips_code_written_news_section():
    from vnstock_brief import enforce_horizon_vocab
    ctx = {"brief_type": "afternoon", "horizons": _view()}
    text = "## 📰 Tin tức ảnh hưởng\n- Thị trường châu Á Risk-off (Reuters)\n"
    assert enforce_horizon_vocab(text, ctx) == text
    assert enforce_horizon_vocab("Thị trường Risk-on.", {"horizons": _view(stale=True)}) == \
        "Thị trường Risk-on."


def test_morning_guard_removes_agent_copies_of_the_horizon_line():
    from vnstock_brief import _horizon_morning_line, enforce_horizon_view
    text = ("## 🎯 TLDR\n**Bias:** GIẢM — x\n🔭 Trung hạn TĂNG mạnh\n- **🔭 tự viết**\n"
            "**Trung hạn:** TĂNG\n\n## 🔭 Góc nhìn theo khung thời gian\n- Trung hạn: TĂNG mạnh\n\n"
            "## 📊 Tổng quan phiên sáng\nz\n")
    ctx = _morning_ctx()
    out = enforce_horizon_view(text, ctx)
    assert "TĂNG mạnh" not in out and "tự viết" not in out and "**Trung hạn:**" not in out
    assert out.count("🔭") == 1 and _horizon_morning_line(ctx) in out
    assert enforce_horizon_view(out, ctx) == out


def test_detect_stance_ignores_the_morning_horizon_line():
    from vnstock_brief import _detect_stance
    line = "- 🔭 Trung hạn ĐI NGANG (2 lần đóng tuần) · ngắn hạn: chưa rõ (phiên 14) — Bias chỉ TRUNG TÍNH/GIẢM"
    assert _detect_stance(f"**Bias:** x\n{line}") == "unknown"
