"""P1b-7 (#25) — header Telegram 3 khung (mẫu §4 A) + `run.py horizons --legend`
+ tách tin đúng ranh giới mục. Sau công tắc VNSTOCK_HORIZONS (tắt ⇒ header cũ).
"""
from __future__ import annotations

import pytest

import vnstock_horizons as hz


@pytest.fixture(autouse=True)
def _no_vnstock_env(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_"):
            monkeypatch.delenv(k, raising=False)


def _view(as_of, medium, since, weeks, short, tier, levels, anchor=1853.08) -> dict:
    snap = {"as_of": as_of, "short": short, "short_since": "2026-09-24", "score": -6, "n": 7,
            "medium": medium, "medium_since": since, "pending": 0, "levels": levels,
            "alert": {"tier": tier, "anchor": anchor if tier else None,
                      "since": "2026-10-01" if tier else None},
            "stance": {"forced": "GIẢM", "allowed": ["GIẢM"]}}
    return {"stale": False, "snap": snap, "prev": None, "short_sessions": 7,
            "medium_weeks": weeks, "breadth_pct": 9.0, "breadth_pct_4w": 11.0,
            "known_levels": []}


_ALLOC = {"band": "B4", "allocation": {"Cổ phiếu": 15}}


def test_header_on_02_10_has_no_alert_line_once_the_trend_is_down():
    from vnstock_telegram import _horizon_header_lines
    view = _view("2026-10-02", hz.GIAM, "2026-10-02", 1, hz.CHINH, 1,
                 [{"kind": "leave_giam", "price": 1802.4, "reachable": True}])
    vt = {"close": 1737.71, "day_change_pct": -0.66, "data_date": "2026-10-02"}
    assert _horizon_header_lines(view, _ALLOC, vt) == [
        "📊 VNINDEX <b>1,737.71</b> (-0.66%) · phiên 02/10",
        "🔭 <b>Trung hạn: GIẢM</b> (tuần 1, từ 02/10) · 💼 Cổ phiếu 15% · "
        "Nên: giữ tỷ trọng thấp; không bắt đáy",
    ]


def test_header_on_01_10_shows_the_alert_while_the_trend_is_still_flat():
    from vnstock_telegram import _horizon_header_lines
    view = _view("2026-10-01", hz.DI_NGANG, "2026-07-24", 10, hz.CHINH, 1,
                 [{"kind": "to_giam", "price": 1766.2, "reachable": True},
                  {"kind": "to_tang", "price": 2020.0, "reachable": False}])
    vt = {"close": 1749.30, "day_change_pct": -1.09, "data_date": "2026-10-01"}
    lines = _horizon_header_lines(view, _ALLOC, vt)
    assert lines[1] == ("🔭 <b>Trung hạn: ĐI NGANG</b> (tuần 10, từ 24/07) · 💼 Cổ phiếu 15% · "
                        "Nên: không bán tháo; trung hạn chuyển GIẢM nếu đóng tuần < ~1,766")
    assert lines[2] == ("🚨 <b>Rủi ro ngắn hạn: BẬT mức 1</b> — thấp hơn đỉnh neo ~1,853 "
                        "5.6%; không đổi xu hướng")


def test_stale_state_header_says_not_updated():
    from vnstock_telegram import _horizon_header_lines
    lines = _horizon_header_lines({"stale": True, "as_of": "2026-10-09"}, {},
                                  {"close": 1737.71, "day_change_pct": -0.66,
                                   "data_date": "2026-10-13"})
    assert lines == ["📊 VNINDEX <b>1,737.71</b> (-0.66%) · phiên 13/10",
                     "🔭 3 khung: chưa cập nhật (as_of 09/10)"]


def test_market_header_lines_switch(monkeypatch):
    import vnstock_telegram as tg
    monkeypatch.setattr(tg, "_vnindex_line", lambda: "OLD1")
    monkeypatch.setattr(tg, "_regime_block", lambda: "OLD2")
    monkeypatch.setattr(tg, "_market_sentiment_line", lambda: "OLD3")
    assert tg._market_header_lines() == ["OLD1", "OLD2", "OLD3"]          # tắt ⇒ header cũ
    monkeypatch.setenv("VNSTOCK_HORIZONS", "1")
    monkeypatch.setattr(tg, "_horizon_header_inputs", lambda: ({"stale": True, "as_of": None},
                                                               {}, {"close": None}))
    assert tg._market_header_lines()[1] == "🔭 3 khung: chưa cập nhật (chưa đọc được state)"
    monkeypatch.setattr(tg, "_horizon_header_inputs", lambda: 1 / 0)
    assert tg._market_header_lines() == ["OLD1", "OLD2", "OLD3"]          # lỗi ⇒ header cũ


# ── --legend: đúng 1 tin, không ghi kho/marker ───────────────────────────────

def test_legend_sends_exactly_one_message_and_writes_nothing(monkeypatch, tmp_path):
    import vnstock_horizons_state as hs
    import vnstock_telegram as tg
    sent = []
    monkeypatch.setattr(tg, "send_message", lambda text, **k: sent.append(text) or {"ok": True})
    monkeypatch.setattr(hs, "_WAREHOUSE", tmp_path)
    monkeypatch.setattr(hs, "_REPO", tmp_path)          # .env máy thật không lọt vào test
    assert hs.main(["--legend"]) == 0
    assert len(sent) == 1 and len(sent[0]) < tg._MAX_MSG_LEN
    assert tg._split_for_telegram(tg._sanitize_html(sent[0])) == [tg._sanitize_html(sent[0])]
    for word in ("Ngắn hạn", "Trung hạn", "Dài hạn", "🚨", "Lớp bảo vệ", "💼", "Stance"):
        assert word in sent[0]
    assert list(tmp_path.rglob("*")) == []


def test_legend_dry_run_prints_without_sending(monkeypatch, capsys, tmp_path):
    import vnstock_horizons_state as hs
    import vnstock_telegram as tg
    monkeypatch.setattr(hs, "_REPO", tmp_path)
    monkeypatch.setattr(tg, "send_message", lambda *a, **k: pytest.fail("không được gửi"))
    assert hs.main(["--legend", "--dry-run"]) == 0
    assert "Trung hạn" in capsys.readouterr().out


# ── Tách tin đúng ranh giới mục ─────────────────────────────────────────────

def test_split_keeps_every_section_whole():
    from vnstock_telegram import _split_for_telegram
    sections = [f"{emo} Mục {k}\n" + "\n".join(f"dòng {k}.{i} " + "x" * 60 for i in range(20))
                for k, emo in enumerate(("🎯", "🔭", "📊", "📈", "📋", "⚠️"))]
    text = "📉 <b>VNStock Close Brief</b>\n" + "\n".join(sections)
    parts = _split_for_telegram(text, 4000)
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)
    assert "\n".join(parts) == text
    for sec in sections:                          # mỗi mục nằm trọn trong 1 tin
        assert any(sec in p for p in parts)


def test_split_falls_back_to_lines_for_a_section_longer_than_a_message():
    from vnstock_telegram import _split_for_telegram
    big = "🔭 Mục lớn\n" + "\n".join("y" * 90 for _ in range(60))
    parts = _split_for_telegram("🎯 TLDR\nngắn\n" + big, 4000)
    assert all(len(p) <= 4000 for p in parts) and "\n".join(parts) == "🎯 TLDR\nngắn\n" + big
