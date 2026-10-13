"""P1b-4 (#22) — Stance theo bảng 3 khung (§3.4) sau công tắc VNSTOCK_HORIZONS.

Chỉ ÉP ở 2 ô: ngắn hạn nhịp chỉnh ⇒ GIẢM; nhịp hồi × trung hạn TĂNG × 🚨 tắt ⇒
TĂNG. Ô khác: tập cho phép, nhãn agent ngoài tập ⇒ TRUNG TÍNH (setup giữ nguyên).
Momentum ±50 rời luật ép (floor cũ chỉ còn trong lớp bảo vệ). State cũ/hỏng ⇒
floor cũ y như trước.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

import vnstock_horizons as hz

SHORTS = (hz.HOI, hz.CHUA_RO, hz.CHINH)
MEDIUMS = (hz.TANG, hz.DI_NGANG, hz.GIAM)
LABELS = ("TĂNG", "TRUNG TÍNH", "GIẢM")


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)


def _view(short=hz.CHINH, medium=hz.GIAM, tier=1, **snap_over) -> dict:
    rule = hz.stance_rule(short, medium, tier)
    snap = {"as_of": "2026-10-13", "short": short, "short_since": "2026-09-24",
            "score": -7, "n": 7, "medium": medium, "medium_since": "2026-10-02",
            "pending": 0, "levels": [], "alert": {"tier": tier, "anchor": 1853.08,
                                                  "since": "2026-10-01"},
            "stance": {"forced": rule.forced, "allowed": list(rule.allowed)}}
    snap.update(snap_over)
    return {"stale": False, "snap": snap, "prev": None, "short_sessions": 14,
            "medium_weeks": 2, "breadth_pct": 9.0, "breadth_pct_4w": 11.0,
            "known_levels": []}


def _close(label: str) -> str:
    return (f"## 🎯 TLDR\n**Kết quả phiên:** VNINDEX giảm.\n"
            f"**Stance ngày mai:** {label} — canh giảm nếu thủng S1 → mục tiêu S2; "
            f"hủy nếu vượt lại R1.\n\n## 📊 Tổng kết phiên\nx\n")


def _stance_of(text: str) -> str:
    line = next(ln for ln in text.splitlines() if "Stance ngày mai:" in ln or "Bias:" in ln)
    tail = line.split(":", 1)[1].replace("*", "").strip()
    return next(lb for lb in LABELS if tail.startswith(lb))


# ── Bảng 9 ô × 🚨 qua guard ─────────────────────────────────────────────────

@pytest.mark.parametrize("tier", [0, 1, 2])
@pytest.mark.parametrize("medium", MEDIUMS)
@pytest.mark.parametrize("short", SHORTS)
@pytest.mark.parametrize("agent", LABELS)
def test_stance_table_goes_through_the_guard(short, medium, tier, agent):
    from vnstock_brief import enforce_stance_horizon
    rule = hz.stance_rule(short, medium, tier)
    ctx = {"brief_type": "afternoon", "horizons": _view(short, medium, tier)}
    out = enforce_stance_horizon(_close(agent), ctx)
    if agent == "GIẢM":
        expect = "GIẢM"                 # GIẢM không bao giờ bị loại — kể cả ô ép TĂNG (§3.1)
    else:
        expect = rule.forced or (agent if agent in rule.allowed else "TRUNG TÍNH")
    assert _stance_of(out) == expect
    assert "canh giảm nếu thủng S1 → mục tiêu S2; hủy nếu vượt lại R1." in out   # setup giữ
    assert enforce_stance_horizon(out, ctx) == out
    assert ("stance_pinned" in ctx) is (expect != agent)


def test_guard_handles_bold_label_and_the_morning_bias_line():
    from vnstock_brief import enforce_stance_horizon
    ctx = {"brief_type": "morning", "horizons": _view(hz.CHUA_RO, hz.DI_NGANG, 0)}
    morning = "## 🎯 TLDR\n**Bias:** **TĂNG** — VNINDEX giữ MA20.\n**Hành động ưu tiên:** WAIT\n"
    out = enforce_stance_horizon(morning, ctx)
    assert "**Bias:** **TRUNG TÍNH** — VNINDEX giữ MA20." in out


def test_unrecognised_label_gets_the_default_prefixed():
    from vnstock_brief import enforce_stance_horizon
    ctx = {"brief_type": "afternoon", "horizons": _view(hz.CHUA_RO, hz.GIAM, 0)}
    out = enforce_stance_horizon(_close("THẬN TRỌNG"), ctx)
    assert "**Stance ngày mai:** TRUNG TÍNH — THẬN TRỌNG — canh giảm" in out


@pytest.mark.parametrize("ctx", [
    {"brief_type": "afternoon"},                                         # công tắc tắt
    {"brief_type": "afternoon", "horizons": {"stale": True, "as_of": "2026-10-09"}},
])
def test_guard_is_a_noop_without_a_usable_state(ctx):
    from vnstock_brief import enforce_stance_horizon
    assert enforce_stance_horizon(_close("TĂNG"), ctx) == _close("TĂNG")


# ── Hợp đồng ctx: bias_floor chỉ ở 2 ô ép; floor cũ ⇒ bias_floor_old ─────────

def test_forced_cell_writes_the_new_floor_with_its_source():
    from vnstock_brief import _apply_horizon_stance
    ctx = {"horizons": _view(hz.CHINH, hz.DI_NGANG, 0),
           "bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -5}}
    _apply_horizon_stance(ctx)
    assert ctx["bias_floor"] == {"dir": "GIẢM", "source": "nhip", "short": hz.CHINH,
                                 "since": "2026-09-24", "n": 14, "score": -7, "n_signals": 7}
    assert ctx["bias_floor_old"] == {"dir": "GIẢM", "momentum": -67, "regime_score": -5}
    assert "stance_allowed" not in ctx["horizons"]


def test_momentum_alone_no_longer_forces_but_still_protects():
    from vnstock_brief import _apply_horizon_stance, floor_dir, is_defensive
    ctx = {"horizons": _view(hz.CHUA_RO, hz.DI_NGANG, 0),
           "bias_floor": {"dir": "GIẢM", "momentum": -55, "regime_score": None}}
    _apply_horizon_stance(ctx)
    assert "bias_floor" not in ctx and floor_dir(ctx) is None
    assert ctx["horizons"]["stance_allowed"] == ["TRUNG TÍNH", "GIẢM"]
    assert is_defensive(ctx) is True              # floor cũ vẫn bật lớp bảo vệ


def test_stale_state_keeps_the_old_floor_untouched():
    from vnstock_brief import _apply_horizon_stance
    old = {"dir": "GIẢM", "momentum": -67, "regime_score": -5}
    ctx = {"horizons": {"stale": True, "as_of": "2026-10-09"}, "bias_floor": dict(old)}
    _apply_horizon_stance(ctx)
    assert ctx["bias_floor"] == old and "bias_floor_old" not in ctx


# ── Prompt ──────────────────────────────────────────────────────────────────

def test_prompt_names_the_short_term_reason_for_a_forced_cell():
    from vnstock_brief import _apply_horizon_stance, build_prompt
    ctx = {"date": "2026-10-13", "time": "15:30", "horizons": _view(hz.CHINH, hz.GIAM, 1)}
    _apply_horizon_stance(ctx)
    p = build_prompt(ctx, brief_type="afternoon")
    assert "Ngắn hạn: nhịp chỉnh phiên 14 (điểm -7/7)" in p
    assert "momentum" not in p.split("## 🧭 RÀNG BUỘC BIAS")[1].split("\n## ")[0]


@pytest.mark.parametrize("bt,word", [("afternoon", "Stance ngày mai"), ("morning", "Bias")])
def test_prompt_lists_the_allowed_labels(bt, word):
    from vnstock_brief import _apply_horizon_stance, build_prompt
    ctx = {"date": "2026-10-13", "time": "15:30" if bt == "afternoon" else "11:30",
           "horizons": _view(hz.HOI, hz.GIAM, 0)}
    _apply_horizon_stance(ctx)
    p = build_prompt(ctx, brief_type=bt)
    assert f"{word} CHỈ được chọn trong: TRUNG TÍNH / GIẢM" in p
    assert "## 🧭 RÀNG BUỘC BIAS" not in p


# ── Sổ độ chính xác: stance_source từ ctx đã lưu ────────────────────────────

def test_stance_source_is_rebuilt_from_the_saved_context(monkeypatch):
    import vnstock_stance_track as stk
    monkeypatch.setattr(stk, "_vnindex_closes", lambda days=200: [
        ("2026-10-08", 1750.0), ("2026-10-09", 1740.0), ("2026-10-12", 1700.0),
        ("2026-10-13", 1720.0)])
    rows = [
        {"brief_date": "2026-10-12", "agent_name": "Claude", "output": _close("GIẢM"),  # sai: +1.2%
         "error": None, "context_json": json.dumps({"date": "2026-10-12"})},
        {"brief_date": "2026-10-09", "agent_name": "Claude", "output": _close("GIẢM"),
         "error": None, "context_json": json.dumps(
             {"bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -5}})},
        {"brief_date": "2026-10-08", "agent_name": "Claude", "output": _close("GIẢM"),
         "error": None, "context_json": "{hỏng"},
    ]
    mod = types.ModuleType("vnstock_memory")
    mod.init_db = lambda: None
    mod.recent_briefs = lambda brief_type=None, limit=20: rows
    monkeypatch.setitem(sys.modules, "vnstock_memory", mod)
    recs = {r["date"]: r for r in stk.stance_records()}
    assert recs["2026-10-12"]["stance_source"] == "agent"
    assert recs["2026-10-09"]["stance_source"] == "code"
    assert recs["2026-10-08"]["stance_source"] == "agent"
    s = stk.stance_summary()
    assert s["agent_only"]["n_graded"] == 2 and s["agent_only"]["n_correct"] == 1


# ── Regime: khối ngoại 1 phiên theo NGÀY HIỆU LỰC (chuyển từ #19) ────────────

def test_load_regime_reads_foreign_flow_of_the_price_bar_session(monkeypatch):
    import vnstock_foreign_flow as ff
    import vnstock_regime as rg
    monkeypatch.setattr(rg, "_load_vnindex_tech", lambda: {"data_date": "2026-10-10",
                                                           "close": 1737.71})
    monkeypatch.setattr(rg, "_load_breadth", lambda: {})
    monkeypatch.setattr(ff, "_load_cache", lambda: {"2026-10-10": {"net": -1200.0},
                                                    "2026-10-13": {"net": 800.0}})
    seen = []
    monkeypatch.setattr(rg, "classify_regime", lambda t, b, nn: seen.append(nn) or {})
    rg.load_regime()
    rg.load_regime("2026-10-13")
    assert seen == [-1200.0, 800.0]          # cache có ngày MỚI hơn bar ⇒ không lấy nhầm


# ── Sau review #22: biến thể dòng nhãn, dòng mồi, setup ngược chiều ô ép ─────

_FLAT = {"brief_type": "afternoon"}       # ô {TRUNG TÍNH, GIẢM}: hồi × GIẢM


@pytest.mark.parametrize("line,expect", [
    ("**Stance ngày mai:** **TĂNG** — x", "**Stance ngày mai:** **TRUNG TÍNH** — x"),
    ("**Stance ngày mai: TĂNG**", "**Stance ngày mai: TRUNG TÍNH**"),
    ("- **Stance ngày mai**: TĂNG — x", "- **Stance ngày mai**: TRUNG TÍNH — x"),
    ("🧭 **Stance ngày mai:** TĂNG — x", "🧭 **Stance ngày mai:** TRUNG TÍNH — x"),
    ("1. Stance ngày mai (16/10): TĂNG — x", "1. Stance ngày mai (16/10): TRUNG TÍNH — x"),
    ("**Stance ngày mai:** `TĂNG` — x", "**Stance ngày mai:** `TRUNG TÍNH` — x"),
    ("**Stance ngày mai:** Tăng/Trung tính — x", "**Stance ngày mai:** TRUNG TÍNH — x"),
    ("**Stance ngày mai:** TRUNG TÍNH nghiêng tăng — x", "**Stance ngày mai:** TRUNG TÍNH — x"),
    ("**Stance ngày mai:** Nghiêng GIẢM — x", None),          # GIẢM có chữ phía trước: giữ
    ("**Stance ngày mai:** 📉 GIẢM — x", None),
    ("**Stance ngày mai:** [GIẢM] — x", None),
    ("**Stance ngày mai:**", "**Stance ngày mai:** TRUNG TÍNH"),
])
def test_label_variants_are_pinned_without_corrupting_the_line(line, expect):
    from vnstock_brief import _detect_stance, enforce_stance_horizon
    ctx = {**_FLAT, "horizons": _view(hz.HOI, hz.GIAM, 0)}
    text = f"## 🎯 TLDR\n{line}\n\n## 📊 Tổng kết phiên\nx\n"
    out = enforce_stance_horizon(text, ctx)
    assert out == (text if expect is None else text.replace(line, expect))
    assert enforce_stance_horizon(out, dict(ctx)) == out
    if expect is None:
        assert _detect_stance(out.split("## 📊")[0]) == "bearish"


def test_a_decoy_bias_line_outside_the_tldr_is_ignored():
    from vnstock_brief import enforce_stance_horizon
    ctx = {**_FLAT, "horizons": _view(hz.HOI, hz.GIAM, 0)}
    text = ("## 🎯 TLDR\n**Stance ngày mai:** TĂNG — x\n\n## 📊 Tổng kết phiên\n"
            "Bias: TRUNG TÍNH theo khối ngoại.\n")
    out = enforce_stance_horizon(text, ctx)
    assert "**Stance ngày mai:** TRUNG TÍNH — x" in out
    assert "Bias: TRUNG TÍNH theo khối ngoại." in out


def test_forced_cell_rebuilds_an_opposite_setup_from_real_levels():
    from vnstock_brief import enforce_stance_horizon
    vt = {"close": 1737.71, "support_1": 1720.5, "support_2": 1700.1,
          "resistance_1": 1760.2, "resistance_2": 1790.12}
    ctx = {**_FLAT, "horizons": _view(hz.CHINH, hz.DI_NGANG, 0), "vnindex_tech": vt}
    text = ("## 🎯 TLDR\n**Stance ngày mai:** TĂNG — canh mua nếu vượt R1=1,760.20 → mục "
            "tiêu R2=1,790.12; hủy nếu thủng S1=1,720.50.\n")
    out = enforce_stance_horizon(text, ctx)
    assert ("**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,720.50 → mục tiêu "
            "S2=1,700.10; hủy nếu vượt lại R1=1,760.20.") in out
    assert ctx["stance_pinned"] == {"agent": "TĂNG", "code": "GIẢM"}


def test_missing_stance_rule_in_a_usable_snapshot_keeps_the_old_floor():
    from vnstock_brief import _apply_horizon_stance
    view = _view(hz.CHINH, hz.GIAM, 1)
    view["snap"]["stance"] = None
    old = {"dir": "GIẢM", "momentum": -67, "regime_score": -5}
    ctx = {"horizons": view, "bias_floor": dict(old)}
    _apply_horizon_stance(ctx)
    assert ctx["bias_floor"] == old and "stance_allowed" not in view


def test_prompt_survives_a_null_score_and_names_the_protection_reason():
    from vnstock_brief import _apply_horizon_defensive, _apply_horizon_stance, build_prompt
    view = _view(hz.CHINH, hz.GIAM, 1, score=None)
    ctx = {"date": "2026-10-13", "time": "15:30", "horizons": view,
           "bias_floor": {"dir": "GIẢM", "momentum": -55, "regime_score": None}}
    _apply_horizon_stance(ctx)
    _apply_horizon_defensive(ctx)
    p = build_prompt(ctx, brief_type="afternoon")
    assert "Ngắn hạn: nhịp chỉnh phiên 14 (điểm 0/7)" in p          # score None: không TypeError
    assert "bias GIẢM" in p                       # ô ép GIẢM: lời cũ vẫn đúng chiều
    ctx2 = {"date": "2026-10-13", "time": "15:30", "horizons": _view(hz.HOI, hz.TANG, 1),
            "bias_floor": {"dir": "GIẢM", "momentum": -55, "regime_score": None}}
    _apply_horizon_stance(ctx2)
    _apply_horizon_defensive(ctx2)
    p2 = build_prompt(ctx2, brief_type="afternoon")
    assert "(lớp bảo vệ bật: tín hiệu ngày một chiều giảm · 🚨 mức 1)" in p2
    assert "(bias GIẢM)" not in p2


def test_apply_horizons_wires_morning_and_afternoon_only(monkeypatch):
    import vnstock_brief as vb
    calls = []
    monkeypatch.setattr(vb, "_load_horizons", lambda c: c.__setitem__(
        "horizons", _view(hz.HOI, hz.GIAM, 0)))
    for bt in ("morning", "afternoon", "allocation"):
        ctx = {"bias_floor": {"dir": "GIẢM", "momentum": -60, "regime_score": None}}
        vb._apply_horizons(ctx, bt)
        calls.append((bt, "horizons" in ctx, ctx.get("defensive", {}).get("level")))
    assert calls == [("morning", True, "cứng"), ("afternoon", True, "cứng"),
                     ("allocation", False, None)]


def test_stance_source_marks_days_the_guard_rewrote(monkeypatch):
    import vnstock_stance_track as stk
    monkeypatch.setattr(stk, "_vnindex_closes", lambda days=200: [
        ("2026-10-12", 1700.0), ("2026-10-13", 1720.0)])
    rows = [{"brief_date": "2026-10-12", "agent_name": "Claude", "output": _close("TRUNG TÍNH"),
             "error": None, "context_json": json.dumps(
                 {"stance_pinned": {"agent": "TĂNG", "code": "TRUNG TÍNH"}})},
            {"brief_date": "2026-10-12", "agent_name": "Groq", "output": _close("TRUNG TÍNH"),
             "error": None, "context_json": json.dumps(
                 {"bias_floor": {"dir": "GIẢM", "momentum": -67}})},     # agent cãi floor
            {"brief_date": "2026-10-12", "agent_name": "Gemini", "output": _close("GIẢM"),
             "error": None, "context_json": "[]"}]
    mod = types.ModuleType("vnstock_memory")
    mod.init_db = lambda: None
    mod.recent_briefs = lambda brief_type=None, limit=20: rows
    monkeypatch.setitem(sys.modules, "vnstock_memory", mod)
    src = {r["agent"]: r["stance_source"] for r in stk.stance_records()}
    assert src == {"Claude": "code", "Groq": "agent", "Gemini": "agent"}
    assert "Claude" not in stk.stance_summary()["by_agent"]      # view theo agent bỏ ngày code
