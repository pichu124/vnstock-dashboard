"""Lưới cho `enforce_exdate_levels` — mốc giá vs ngày GDKHQ.

Ca thật, brief chiều 19/08: cùng MỘT brief chứa hai khối đá nhau — Watchlist
nêu `VIX (Giá 13,100) — TRÁNH nếu thủng 12,700`, còn mục Sự kiện nói `VIX: Trả
Cổ tức bằng Cổ phiếu tỉ lệ 5.0% — ngày 2026-08-20`. 13.100 × 100/105 = 12.476
⇒ mốc "thủng 12.700" kích hoạt CƠ HỌC ngay lúc mở cửa hôm sau, không phải do
ai bán; mốc hủy 13.500 thành bất khả.

Lớp lỗi MỚI: 46 guard cũ canh "nói đúng chuyện" TRONG từng mục, chưa cái nào
canh NHẤT QUÁN GIỮA HAI MỤC.
"""
from __future__ import annotations

import pytest

from vnstock_brief_guards_sections import (
    _EXDATE_MARK,
    _exdate_map,
    enforce_exdate_levels,
)

_WL = """📋 Watchlist sáng mai
1. **VIC** (Giá 200,000) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 194,000
2. **VIX** (Giá 13,100) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 12,700 · mục tiêu 12,000

💡 Đề xuất giao dịch
- SBT BUY entry=24 TP=25 SL=23
- VIX BUY entry=13 TP=15 SL=12
"""


def _ctx(ex_date="2026-08-20", ticker="VIX", today="2026-08-19",
         title="Trả Cổ tức bằng Cổ phiếu tỉ lệ 5.0%"):
    return {"today": today,
            "upcoming_events": [{"ticker": ticker, "ex_date": ex_date,
                                 "title": title}]}


def _line(text: str, needle: str) -> str:
    return next(l for l in text.splitlines() if needle in l)


# ── Ca thật ─────────────────────────────────────────────────────────────────

def test_watchlist_item_for_a_ticker_going_ex_tomorrow_is_flagged():
    out = enforce_exdate_levels(_WL, _ctx())
    vix = _line(out, "**VIX**")
    assert _EXDATE_MARK in vix
    assert "2026-08-20" in vix
    assert "CHƯA quy đổi" in vix
    assert "Cổ phiếu tỉ lệ 5.0%" in vix          # nêu chính sự kiện, không nói suông


def test_other_tickers_in_the_same_section_are_left_alone():
    out = enforce_exdate_levels(_WL, _ctx())
    assert _EXDATE_MARK not in _line(out, "**VIC**")
    assert _line(out, "**VIC**") == _line(_WL, "**VIC**")


def test_trade_suggestions_are_flagged_too():
    """Đề xuất có horizon 5-20 phiên nên GDKHQ trong 14 ngày cũng chạm."""
    out = enforce_exdate_levels(_WL, _ctx())
    assert _EXDATE_MARK in _line(out, "VIX BUY")
    assert _EXDATE_MARK not in _line(out, "SBT BUY")


# ── Không được kêu oan ──────────────────────────────────────────────────────

def test_no_events_is_a_noop():
    assert enforce_exdate_levels(_WL, {}) == _WL
    assert enforce_exdate_levels(_WL, {"upcoming_events": []}) == _WL


def test_empty_text_is_a_noop():
    assert enforce_exdate_levels("", _ctx()) == ""


def test_far_off_exdate_does_not_touch_the_next_session_watchlist():
    """Watchlist là kịch bản cho PHIÊN KẾ TIẾP — quyền 10 ngày nữa không làm
    sai mốc ngày mai. Kêu ở đây là alarm fatigue."""
    out = enforce_exdate_levels(_WL, _ctx(ex_date="2026-08-29"))
    assert _EXDATE_MARK not in _line(out, "**VIX**")
    # nhưng đề xuất 5-20 phiên thì VẪN chạm
    assert _EXDATE_MARK in _line(out, "VIX BUY")


def test_past_exdate_is_ignored():
    out = enforce_exdate_levels(_WL, _ctx(ex_date="2026-08-18"))
    assert _EXDATE_MARK not in out


def test_prose_lines_are_never_tagged():
    """Chỉ gắn vào DÒNG SETUP (có đánh số / gạch đầu dòng), không gắn vào văn."""
    txt = ("📋 Watchlist sáng mai\n"
           "VIX đang chịu áp lực bán mạnh theo nhóm chứng khoán.\n"
           "1. **VIX** (Giá 13,100) — TRÁNH nếu thủng 12,700\n")
    out = enforce_exdate_levels(txt, _ctx())
    assert _EXDATE_MARK not in _line(out, "đang chịu áp lực")
    assert _EXDATE_MARK in _line(out, "1. **VIX**")


def test_ticker_must_match_as_a_whole_word():
    """'VIX' không được khớp bên trong 'VIXY' hay 'AVIX'."""
    txt = "📋 Watchlist sáng mai\n1. **AVIX** (Giá 13,100) — TRÁNH nếu thủng 12,700\n"
    assert enforce_exdate_levels(txt, _ctx()) == txt


def test_sections_without_price_setups_are_untouched():
    txt = ("📰 Tin kinh tế/chính trị nổi bật\n"
           "- [2026-08-19] VIX công bố phương án chia cổ tức\n")
    assert enforce_exdate_levels(txt, _ctx()) == txt


# ── Bất biến kỹ thuật ───────────────────────────────────────────────────────

def test_guard_is_idempotent():
    once = enforce_exdate_levels(_WL, _ctx())
    assert enforce_exdate_levels(once, _ctx()) == once


def test_broken_event_rows_do_not_crash_the_guard():
    ctx = {"today": "2026-08-19", "upcoming_events": [
        {"ticker": "VIX", "ex_date": "khong-phai-ngay", "title": "x"},
        {"ticker": "", "ex_date": "2026-08-20", "title": "y"},
        {"ex_date": None, "title": None},
    ]}
    assert enforce_exdate_levels(_WL, ctx) == _WL


def test_nearest_event_wins_when_a_ticker_has_several():
    ctx = {"today": "2026-08-19", "upcoming_events": [
        {"ticker": "VIX", "ex_date": "2026-08-28", "title": "xa"},
        {"ticker": "VIX", "ex_date": "2026-08-20", "title": "gan"},
    ]}
    assert "2026-08-20" in _line(enforce_exdate_levels(_WL, ctx), "**VIX**")


def test_exdate_map_windows_are_inclusive_of_today():
    m = _exdate_map(_ctx(ex_date="2026-08-19"), 3)
    assert "VIX" in m


def test_guard_is_wired_into_the_chain():
    """Họ lỗi lặp lại nhiều nhất repo này: guard viết ra rồi bỏ quên."""
    import inspect

    import vnstock_brief_guards as g
    assert "enforce_exdate_levels(" in inspect.getsource(g.apply_brief_guards)


def test_guard_does_not_invent_an_adjusted_price():
    """Cố ý KHÔNG tự quy đổi: tỉ lệ chỉ nằm trong CHỮ, mà cổ tức TIỀN MẶT điều
    chỉnh theo MỆNH GIÁ chứ không theo % giá — đoán sai còn hại hơn không đoán."""
    out = _line(enforce_exdate_levels(_WL, _ctx()), "**VIX**")
    assert "12,476" not in out and "12.476" not in out
