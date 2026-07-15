"""Tests cho vnstock_stance_track — chấm "Stance ngày mai" vs chiều VNINDEX
phiên kế tiếp (ý tưởng AI-Trader, khảo sát 2026-07-15) + helper MTM.

Hermetic: brief_memory + kho giá đều fake qua monkeypatch — không DB thật,
không parquet, không mạng.
"""
from __future__ import annotations

import sys
import types

import pytest

import vnstock_stance_track as stk


def _brief(date, stance_txt, agent="Agent A", error=None, output=None):
    body = output if output is not None else (
        f"## 🎯 TLDR\n**Kết quả phiên:** VNINDEX abc.\n"
        f"**Stance ngày mai:** **{stance_txt}** — chi tiết.\n## 📊 Tổng kết\nx\n")
    return {"brief_date": date, "agent_name": agent,
            "output": body, "error": error}


# VNINDEX: 10→11/07 +1.0% · 11→14/07 -0.5% · 14→15/07 +0.05% (phẳng)
_CLOSES = [("2026-07-10", 1800.0), ("2026-07-11", 1818.0),
           ("2026-07-14", 1808.9), ("2026-07-15", 1809.8)]


@pytest.fixture(autouse=True)
def _fake_sources(monkeypatch):
    monkeypatch.setattr(stk, "_vnindex_closes", lambda days=200: _CLOSES)
    mod = types.ModuleType("vnstock_memory")
    mod.init_db = lambda: None
    mod.recent_briefs = lambda brief_type=None, limit=20: []
    monkeypatch.setitem(sys.modules, "vnstock_memory", mod)
    yield mod


def _set_briefs(fake_mem, briefs):
    fake_mem.recent_briefs = lambda brief_type=None, limit=20: briefs


def test_grades_bullish_bearish_neutral(_fake_sources):
    _set_briefs(_fake_sources, [
        _brief("2026-07-10", "TĂNG"),              # phiên kế +1.0% → đúng
        _brief("2026-07-11", "TĂNG"),              # phiên kế -0.5% → sai
        _brief("2026-07-11", "GIẢM", agent="B"),   # phiên kế -0.5% → đúng
        _brief("2026-07-10", "TRUNG TÍNH", agent="B"),  # +1.0% > band → sai
    ])
    recs = stk.stance_records()
    marks = {(r["date"], r["agent"]): r["correct"] for r in recs}
    assert marks[("2026-07-10", "Agent A")] is True
    assert marks[("2026-07-11", "Agent A")] is False
    assert marks[("2026-07-11", "B")] is True
    assert marks[("2026-07-10", "B")] is False
    s = stk.stance_summary()
    assert s["n_graded"] == 4 and s["n_correct"] == 2 and s["pct"] == 50.0
    assert s["by_agent"]["Agent A"] == {"n": 2, "correct": 1}


def test_flat_session_directional_not_graded(_fake_sources):
    # 14→15/07 chỉ +0.05% (≤ _FLAT_BAND) → TĂNG/GIẢM không chấm,
    # TRUNG TÍNH thì ĐÚNG (|đổi| ≤ _NEUTRAL_BAND)
    _set_briefs(_fake_sources, [
        _brief("2026-07-14", "GIẢM"),
        _brief("2026-07-14", "TRUNG TÍNH", agent="B"),
    ])
    recs = stk.stance_records()
    assert {r["agent"]: r["correct"] for r in recs} == {"Agent A": None, "B": True}
    s = stk.stance_summary()
    assert s["n_graded"] == 1 and s["skipped"] == 1


def test_dedupes_regenerated_briefs_same_date_agent(_fake_sources):
    # 14/07 user regenerate 4 bản cùng agent → chỉ bản MỚI NHẤT (đầu list,
    # recent_briefs sort DESC) được chấm; agent khác cùng ngày vẫn được chấm.
    _set_briefs(_fake_sources, [
        _brief("2026-07-10", "TĂNG"),               # bản mới nhất → dùng
        _brief("2026-07-10", "GIẢM"),               # bản cũ hơn cùng agent → bỏ
        _brief("2026-07-10", "GIẢM"),
        _brief("2026-07-10", "GIẢM", agent="B"),    # agent khác → vẫn chấm
    ])
    recs = stk.stance_records()
    assert len(recs) == 2
    marks = {r["agent"]: (r["stance"], r["correct"]) for r in recs}
    assert marks["Agent A"] == ("bullish", True)     # +1.0% → TĂNG đúng
    assert marks["B"] == ("bearish", False)


def test_skips_latest_error_and_unknown(_fake_sources):
    _set_briefs(_fake_sources, [
        _brief("2026-07-15", "GIẢM"),                       # chưa có phiên kế → bỏ
        _brief("2026-07-11", "GIẢM", error="boom"),         # brief lỗi → bỏ
        _brief("2026-07-11", "", output="## 🎯 TLDR\nkhông nói gì.\n"),  # unknown
        _brief("2026-07-10", "TĂNG"),
    ])
    recs = stk.stance_records()
    assert len(recs) == 1 and recs[0]["date"] == "2026-07-10"


def test_summary_line_and_empty(_fake_sources):
    assert stk.stance_summary() is None                # chưa có brief nào
    assert stk.summary_line() is None
    _set_briefs(_fake_sources, [_brief("2026-07-10", "TĂNG")])
    line = stk.summary_line()
    assert "đúng 1/1" in line and "100%" in line


def test_next_session_change_edges():
    closes = _CLOSES
    assert stk._next_session_change("2026-07-10", closes) == (
        "2026-07-11", pytest.approx(1.0))
    assert stk._next_session_change("2026-07-15", closes) is None   # chưa có kế
    assert stk._next_session_change("2026-07-01", closes) is None   # thiếu bar gốc
    # brief ngày nghỉ (12/07) → so với bar cuối TRƯỚC đó (11/07)
    d, chg = stk._next_session_change("2026-07-12", closes)
    assert d == "2026-07-14" and chg == pytest.approx(-0.5, abs=0.01)


def test_cli_show(_fake_sources, capsys):
    assert stk.main(["--show"]) == 1                   # trống → exit 1
    _set_briefs(_fake_sources, [_brief("2026-07-10", "TĂNG")])
    assert stk.main(["--show"]) == 0
    out = capsys.readouterr().out
    assert "đúng 1/1" in out and "✅" in out


# ── Món 2: MTM helper ────────────────────────────────────────────────────────


def test_unrealized_pnl_pct():
    import vnstock_strategy as vs
    assert vs.unrealized_pnl_pct(25.0, 26.0) == pytest.approx(4.0)
    assert vs.unrealized_pnl_pct(25.0, 24.0) == pytest.approx(-4.0)
    assert vs.unrealized_pnl_pct(25.0, 24.0, action="sell") == pytest.approx(4.0)
    assert vs.unrealized_pnl_pct(0, 24.0) is None
    assert vs.unrealized_pnl_pct("x", 24.0) is None
