"""Lưới cho lỗ hổng ĐỘ TƯƠI: `market_overview` chốt GIỮA phiên.

Luật cũ chỉ so NGÀY: `overview_date < data_date` ⇒ stale. Nên "độ rộng chốt
lúc 11:00" và "độ rộng chốt phiên" có cùng `data_date` và cùng được coi là
TƯƠI — trong khi brief chiều mô tả cả phiên còn khối độ rộng / VN30 movers /
dòng tiền ngành mới thấy nửa buổi sáng. Đó là thứ phải kiểm bằng TAY suốt
(mục "Bước 2" trong sổ việc).

Mốc "phiên đã đóng" = **15:05** (user chốt 19/08, khớp mốc screener đang dùng).

Lưới canh cả hai chiều, vì nới quá tay thì sáng nào cũng kêu oan:
  * chốt TRƯỚC mốc, ĐÚNG ngày phiên  → stale · reason=intraday
  * chốt SAU mốc, hoặc ghi ở ngày SAU (chạy bù từ data EOD) → KHÔNG kêu
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vnstock_brief import (
    SESSION_CLOSE_CUTOFF,
    _market_overview_generated_at,
    market_data_freshness,
)

_D = "2026-08-19"


@pytest.fixture()
def overview(tmp_path):
    def _mk(data_date=_D, generated_at=f"{_D} 18:30:00"):
        p = tmp_path / "market_overview.json"
        payload = {"data_date": data_date}
        if generated_at is not None:
            payload["generated_at"] = generated_at
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p
    return _mk


# ── Ca thật ─────────────────────────────────────────────────────────────────

def test_overview_computed_mid_session_is_flagged_stale(overview):
    fr = market_data_freshness(_D, overview(generated_at=f"{_D} 11:00:00"))
    assert fr["stale"] is True
    assert fr["reason"] == "intraday"
    assert fr["overview_time"] == "11:00"
    assert "độ rộng" in fr["stale_blocks"]


def test_overview_computed_after_the_close_is_fresh(overview):
    fr = market_data_freshness(_D, overview(generated_at=f"{_D} 18:30:00"))
    assert fr["stale"] is False and fr["reason"] == ""


def test_previous_session_still_uses_the_old_reason(overview):
    fr = market_data_freshness(_D, overview(data_date="2026-08-18",
                                            generated_at="2026-08-18 18:30:00"))
    assert fr["stale"] is True and fr["reason"] == "prev_session"


def test_backfilled_next_morning_is_not_intraday(overview):
    """Chạy bù sáng hôm sau từ data EOD thì nó ĐÃ thấy trọn phiên — kêu ở đây
    là báo động giả."""
    fr = market_data_freshness(_D, overview(generated_at="2026-08-20 08:00:00"))
    assert fr["stale"] is False


@pytest.mark.parametrize("hhmm,stale", [
    ("15:04:59", True),      # trước mốc một giây
    ("15:05:00", False),     # ĐÚNG mốc = đã đóng
    ("15:06:00", False),
])
def test_cutoff_boundary(overview, hhmm, stale):
    fr = market_data_freshness(_D, overview(generated_at=f"{_D} {hhmm}"))
    assert fr["stale"] is stale


def test_cutoff_constant_is_1505():
    assert (SESSION_CLOSE_CUTOFF.hour, SESSION_CLOSE_CUTOFF.minute) == (15, 5)


# ── Không được kêu oan / không được nổ ──────────────────────────────────────

def test_missing_generated_at_falls_back_to_the_date_rule(overview):
    """Vết cũ không có `generated_at` — không được biến thành "luôn stale"."""
    fr = market_data_freshness(_D, overview(generated_at=None))
    assert fr["stale"] is False and fr["overview_time"] is None


def test_unparseable_generated_at_is_ignored(overview):
    fr = market_data_freshness(_D, overview(generated_at="hôm nọ"))
    assert fr["stale"] is False and fr["overview_time"] is None


def test_missing_file_is_not_stale(tmp_path):
    fr = market_data_freshness(_D, tmp_path / "khong-co.json")
    assert fr["stale"] is False and fr["overview_date"] is None


def test_corrupt_file_does_not_raise(tmp_path):
    p = tmp_path / "market_overview.json"
    p.write_text("{ hong", encoding="utf-8")
    assert market_data_freshness(_D, p)["stale"] is False


# ── Bộ đọc giờ ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    (f"{_D} 11:00:00", "11:00"),
    (f"{_D} 11:00", "11:00"),
    (f"{_D}T11:00:00", "11:00"),
    (f"{_D}T11:00:00.123456", "11:00"),
])
def test_generated_at_accepts_the_formats_in_the_wild(overview, raw, expect):
    got = _market_overview_generated_at(overview(generated_at=raw))
    assert got is not None and got.strftime("%H:%M") == expect


# ── Câu cảnh báo trong prompt ───────────────────────────────────────────────

def test_prompt_says_mid_session_not_previous_session():
    """Mượn câu "PHIÊN TRƯỚC" cho ca giữa phiên là nói SAI sự thật, và người
    đọc sẽ học cách bỏ qua cảnh báo."""
    from vnstock_brief import build_prompt

    def _ctx(reason, ov_date, ov_time):
        return {"date": _D, "time": "18:30",
                "freshness": {"data_date": _D, "overview_date": ov_date,
                              "stale": True, "reason": reason,
                              "overview_time": ov_time,
                              "stale_blocks": ["độ rộng"]}}

    mid = build_prompt(_ctx("intraday", _D, "11:00"))
    assert "GIỮA PHIÊN" in mid and "11:00" in mid
    assert "PHIÊN TRƯỚC" not in mid

    prev = build_prompt(_ctx("prev_session", "2026-08-18", "18:30"))
    assert "PHIÊN TRƯỚC" in prev and "GIỮA PHIÊN" not in prev
