"""P1b-8 (#26) — chuẩn bị bật brief 3 khung: few-shot chỉ mẫu sau P1b (lọc
trong truy vấn), công tắc nguy hiểm trong doctor, script bản mẫu + vòng tròn
trên ctx đã lưu. KHÔNG đổi mặc định VNSTOCK_HORIZONS (chờ user duyệt mẫu).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import vnstock_horizons as hz

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)


def test_default_is_still_off():
    assert hz.horizons_enabled() is False          # bật sau khi user duyệt bản mẫu


# ── Few-shot: lọc NGAY TRONG truy vấn ─────────────────────────────────────────

@pytest.fixture()
def mem(tmp_path, monkeypatch):
    import vnstock_memory as m
    monkeypatch.setattr(m, "DB_PATH", tmp_path / "brief_memory.db")
    return m


def _save(m, day: str, output: str, rating: int) -> None:
    bid = m.save_brief(brief_date=day, brief_type="afternoon", agent_name="Claude",
                       agent_type="claude", model="x", prompt="p", output=output,
                       error=None, context={})
    with m._conn() as c:
        c.execute("UPDATE briefs SET user_rating=? WHERE id=?", (rating, bid))


def test_few_shot_uses_only_post_p1b_examples_when_switched_on(mem, monkeypatch):
    from vnstock_brief import _HORIZON_TITLE, _few_shot_block
    old = "## 🎯 TLDR (2 dòng)\n**Stance ngày mai:** TĂNG — Risk-on\n" + "x" * 200
    for k in range(5):                            # 5 mẫu cũ điểm cao hơn ⇒ "lấy N rồi lọc" ra rỗng
        _save(mem, f"2026-10-0{k + 1}", old, 5)
    assert "Risk-on" in _few_shot_block("afternoon")              # tắt: như cũ
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    assert _few_shot_block("afternoon") == ""                     # chưa có mẫu mới
    new = f"## 🎯 TLDR\n**Trung hạn:** GIẢM\n\n{_HORIZON_TITLE}\n- Ngắn hạn …\n" + "y" * 200
    _save(mem, "2026-10-15", new, 4)
    shot = _few_shot_block("afternoon")
    assert _HORIZON_TITLE in shot and "Risk-on" not in shot


# ── Doctor: công tắc 3 khung là công tắc nguy hiểm ───────────────────────────

@pytest.mark.parametrize("key", ["VNSTOCK_HORIZONS", "VNSTOCK_HORIZONS_STEP",
                                 "VNSTOCK_HORIZON_MACRO", "VNSTOCK_ALLOC_HORIZON_CAP",
                                 "VNSTOCK_ALLOC_ONE_STEP"])
def test_doctor_lists_the_three_frame_switches(monkeypatch, key):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_env_file_values", lambda: {})
    monkeypatch.setenv(key, "0")
    r = doc.check_kill_switches()
    assert r["status"] == "warn" and key in r["message"]


# ── Script bản mẫu + vòng tròn trên ctx đã lưu ──────────────────────────────

def _script():
    spec = importlib.util.spec_from_file_location(
        "sample_horizons_brief", _REPO / "scripts" / "sample_horizons_brief.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _snap(as_of: str, medium: int) -> dict:
    rule = hz.stance_rule(hz.CHINH, medium, 1)
    return {"as_of": as_of, "short": hz.CHINH, "short_since": "2026-09-24", "score": -7,
            "n": 7, "medium": medium, "medium_since": "2026-10-02", "pending": 0,
            "week_closed": False, "levels": [{"kind": "leave_giam", "price": 1802.4,
                                              "reachable": True}],
            "alert": {"tier": 1, "anchor": 1853.08, "since": "2026-10-01"},
            "protect": "cứng", "stance": {"forced": rule.forced, "allowed": list(rule.allowed)},
            "ma_w": {"short": 1781.99, "long": 1801.32}}


_STATE = {"inputs": {d: {"close": 1740.0, "breadth_pct": 9.0}
                     for d in ("2026-10-09", "2026-10-12", "2026-10-13")},
          "published": [_snap("2026-10-09", hz.DI_NGANG), _snap("2026-10-12", hz.GIAM),
                        _snap("2026-10-13", hz.GIAM)]}

_SAVED = {"date": "2026-10-12", "market_sentiment": {"mood": "❄️ Sợ hãi", "momentum": -35},
          "vnindex_tech": {"close": 1737.71, "support_1": 1720.5, "resistance_1": 1760.2},
          "bias_floor": {"dir": "GIẢM", "momentum": -55, "regime_score": -3},
          "allocation": {"band": "B4", "allocation": {"Cổ phiếu": 15}}}

_TEXT = ("## 🎯 TLDR\n**Kết quả phiên:** VNINDEX giảm, thị trường Risk-off.\n"
         "**Stance ngày mai:** TĂNG — canh mua nếu vượt R1=1,760.20; hủy nếu thủng "
         "S1=1,720.50.\n\n## 📊 Tổng kết phiên\nx\n")


def test_view_for_picks_the_session_and_its_own_previous_entry():
    s = _script()
    v = s.view_for(_STATE, "2026-10-12")
    assert v["snap"]["as_of"] == "2026-10-12" and v["prev"]["as_of"] == "2026-10-09"
    assert s.view_for(_STATE, "2026-10-01") is None


def test_round_trip_on_a_saved_ctx_passes_and_pins_the_stance():
    s = _script()
    ctx = s.rebuild_ctx(_SAVED, s.view_for(_STATE, "2026-10-12"))
    assert ctx["bias_floor"]["source"] == "nhip" and ctx["defensive"]["level"] == "cứng"
    out, errs = s.round_trip(_TEXT, ctx)
    assert errs == []
    assert "**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,720.50" in out
    assert "🔁 Thay đổi: trung hạn ĐI NGANG → GIẢM" in out
    assert "Risk-off" not in out


def test_telegram_preview_builds_without_sending(monkeypatch):
    import vnstock_telegram as tg
    s = _script()
    monkeypatch.setattr(tg, "send_message", lambda *a, **k: pytest.fail("không được gửi"))
    ctx = s.rebuild_ctx(_SAVED, s.view_for(_STATE, "2026-10-12"))
    out, _ = s.round_trip(_TEXT, ctx)
    prev = s.telegram_preview(out, ctx)
    assert prev.startswith("──── tin 1/1") and "🔭 <b>Trung hạn: GIẢM</b>" in prev


def test_round_trip_flags_a_broken_section(monkeypatch):
    import vnstock_brief as vb
    s = _script()
    ctx = s.rebuild_ctx(_SAVED, s.view_for(_STATE, "2026-10-12"))
    monkeypatch.setattr(vb, "apply_brief_guards", lambda t, c: t.replace("## 🔭", "## x"))
    _, errs = s.round_trip(_TEXT, ctx)
    assert "không có khối 🔭" in errs
