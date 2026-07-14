"""Tests for vnstock_reflection — bài học từ quyết định đã biết outcome.

Hermetic: log trỏ tmp_path, LLM call monkeypatch, nguồn outcome (memory/
scorecard) fake qua sys.modules — không mạng, không DB thật.
"""
import json
import sys
import types

import pytest

import vnstock_reflection as rf


_LESSON = ("Gọi đúng hướng, lệnh chốt lời +8.2%. Luận điểm vượt kháng cự đứng "
           "vững nhờ thanh khoản xác nhận. Bài học: chỉ vào lệnh breakout khi "
           "GTGD phiên xác nhận vượt trung bình.")


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "_LOG", tmp_path / "reflection_log.json")


def _closed_rec(rec_id=1, hit="tp", pnl=8.2):
    return {"id": rec_id, "created_at": "2026-07-01T09:00:00",
            "ticker": "HPG", "action": "BUY", "entry_price": 27.5,
            "take_profit": 30.0, "cut_loss": 26.0, "horizon_days": 10,
            "rationale": "vượt kháng cự kèm thanh khoản",
            "closed_at": "2026-07-10T15:00:00", "exit_price": 29.8,
            "pnl_pct": pnl, "hit_target": hit, "notes": ""}


def _fake_memory(monkeypatch, recs):
    mod = types.ModuleType("vnstock_memory")
    mod.recent_closed_recommendations = lambda limit=30: recs
    monkeypatch.setitem(sys.modules, "vnstock_memory", mod)


def _fake_scorecard(monkeypatch, periods):
    mod = types.ModuleType("vnstock_scorecard")
    mod.load_scorecard = lambda: {"periods": periods}
    monkeypatch.setitem(sys.modules, "vnstock_scorecard", mod)


# ── reflect từng loại ────────────────────────────────────────────────────────


def test_reflect_rec_prompt_carries_outcome(monkeypatch):
    seen = {}
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: seen.update(s=s, u=u) or _LESSON)
    lesson = rf.reflect_rec(_closed_rec())
    assert lesson == _LESSON
    assert "BUY HPG" in seen["u"] and "+8.20%" in seen["u"]
    assert "vượt kháng cự kèm thanh khoản" in seen["u"]   # rationale vào prompt
    assert "chạm chốt lời" in seen["u"]
    assert "2-4 câu" in seen["s"]


def test_reflect_allocation_period(monkeypatch):
    seen = {}
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: seen.update(u=u) or _LESSON)
    period = {"period_start": "2026-07-01", "period_end": "2026-08-01",
              "band": "B4", "band_data": "B4", "tilt": 1,
              "port_ret_pct": 1.2, "baseline_b2_ret_pct": -0.5,
              "delta_vs_b2": 1.7, "coverage_pct": 100,
              "class_returns": {"Cổ phiếu": -3.0, "Vàng": 2.0}}
    assert rf.reflect_allocation_period(period) == _LESSON
    assert "band B4" in seen["u"] and "+1.70" in seen["u"]
    assert "Cổ phiếu -3.0%" in seen["u"]


def test_lesson_cleaned_one_line_capped(monkeypatch):
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: "## Bài\nhọc 🎯 达到 " + "x" * 900)
    lesson = rf.reflect_rec(_closed_rec())
    assert "\n" not in lesson and "#" not in lesson and "达" not in lesson
    assert len(lesson) <= rf._LESSON_MAX_CHARS


# ── refresh: quét outcome mới + cap chi phí ─────────────────────────────────


def test_refresh_reflects_new_recs_and_skips_admin_closes(monkeypatch):
    _fake_memory(monkeypatch, [
        _closed_rec(1, hit="tp"),
        _closed_rec(2, hit="superseded"),          # đóng hành chính → bỏ
        _closed_rec(3, hit="stale", pnl=None),     # không pnl → bỏ
        _closed_rec(4, hit="sl", pnl=-4.1),
    ])
    _fake_scorecard(monkeypatch, [])
    calls = []
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: calls.append(1) or _LESSON)
    new = rf.refresh()
    assert [e["id"] for e in new] == ["rec-1", "rec-4"]
    assert len(calls) == 2
    on_disk = json.loads(rf._LOG.read_text(encoding="utf-8"))
    assert len(on_disk["entries"]) == 2
    # chạy lại: đã reflect rồi → 0 call mới (idempotent theo id)
    assert rf.refresh() == [] and len(calls) == 2


def test_refresh_caps_llm_calls(monkeypatch):
    _fake_memory(monkeypatch, [_closed_rec(i) for i in range(1, 8)])
    _fake_scorecard(monkeypatch, [])
    calls = []
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: calls.append(1) or _LESSON)
    new = rf.refresh(max_calls=2)
    assert len(new) == 2 and len(calls) == 2       # trần chi phí giữ đúng
    # lượt sau tiếp tục phần còn lại
    assert len(rf.refresh(max_calls=10)) == 5


def test_refresh_includes_scorecard_periods(monkeypatch):
    _fake_memory(monkeypatch, [])
    _fake_scorecard(monkeypatch, [
        {"period_start": "2026-07-01", "period_end": "2026-08-01",
         "band": "B4", "band_data": "B4", "tilt": 0, "port_ret_pct": 1.2,
         "baseline_b2_ret_pct": -0.5, "delta_vs_b2": 1.7,
         "coverage_pct": 100, "class_returns": {}},
        {"period_start": "2026-08-01", "period_end": "2026-09-01",
         "band": "B2", "port_ret_pct": None},      # thiếu return → bỏ
    ])
    monkeypatch.setattr(rf, "_reflect_call", lambda s, u: _LESSON)
    new = rf.refresh()
    assert [e["id"] for e in new] == ["alloc-2026-07-01"]
    assert new[0]["kind"] == "allocation"


def test_refresh_llm_dead_leaves_entry_for_next_run(monkeypatch):
    _fake_memory(monkeypatch, [_closed_rec(1)])
    _fake_scorecard(monkeypatch, [])
    monkeypatch.setattr(rf, "_reflect_call", lambda s, u: None)
    assert rf.refresh() == []
    assert not rf._LOG.exists()                    # không ghi entry rỗng
    # LLM sống lại → rec đó được reflect (không bị đánh dấu nhầm là đã xong)
    monkeypatch.setattr(rf, "_reflect_call", lambda s, u: _LESSON)
    assert len(rf.refresh()) == 1


def test_refresh_env_kill_switch(monkeypatch):
    monkeypatch.setenv("VNSTOCK_REFLECTION", "0")
    _fake_memory(monkeypatch, [_closed_rec(1)])
    calls = []
    monkeypatch.setattr(rf, "_reflect_call",
                        lambda s, u: calls.append(1) or _LESSON)
    assert rf.refresh() == [] and calls == []


# ── load_lessons + CLI ───────────────────────────────────────────────────────


def test_load_lessons_newest_first_and_capped(monkeypatch):
    log = {"entries": [
        {"id": f"rec-{i}", "kind": "rec", "date": f"2026-07-{i:02d}",
         "label": f"L{i}", "lesson": f"bài học {i}"} for i in range(1, 6)]}
    rf._write_log(log)
    out = rf.load_lessons(limit=3)
    assert [e["id"] for e in out] == ["rec-5", "rec-4", "rec-3"]
    assert rf.load_lessons(limit=10)[0]["id"] == "rec-5"


def test_log_capped(monkeypatch):
    monkeypatch.setattr(rf, "_MAX_ENTRIES", 3)
    rf._write_log({"entries": [{"id": f"rec-{i}", "lesson": "x"}
                               for i in range(6)]})
    on_disk = json.loads(rf._LOG.read_text(encoding="utf-8"))
    assert [e["id"] for e in on_disk["entries"]] == ["rec-3", "rec-4", "rec-5"]


def test_cli_show_and_refresh(monkeypatch, capsys):
    assert rf.main(["--show"]) == 1                # chưa có gì
    _fake_memory(monkeypatch, [_closed_rec(1)])
    _fake_scorecard(monkeypatch, [])
    monkeypatch.setattr(rf, "_reflect_call", lambda s, u: _LESSON)
    assert rf.main(["--refresh"]) == 0
    assert "1 bài học mới" in capsys.readouterr().out
    assert rf.main(["--show"]) == 0
    out = capsys.readouterr().out
    assert "BUY HPG" in out and "Bài học" in out
