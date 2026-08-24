"""
Soi brief close 24/08/2026 — cảnh báo GDKHQ cho một sự kiện KHÔNG đổi giá.

```
1. **PNJ** (Giá 42,650) — MUA vùng 42,650 … · ⚠️ GDKHQ 2026-08-24
   (PNJ - Tổ chức ĐHĐCĐ bất thường 2026) — giá tham chiếu tự điều chỉnh,
   mốc trên CHƯA quy đổi
```

**Tổ chức ĐHĐCĐ là chốt danh sách DỰ HỌP** — không có gì chia ra khỏi doanh
nghiệp, HOSE KHÔNG điều chỉnh giá tham chiếu. Câu cảnh báo nói về một cú giảm
**không bao giờ xảy ra**.

Sai kiểu này **tệ hơn im lặng**: nó dạy người đọc rằng ⚠️ GDKHQ hay báo hão,
nên lần có cú điều chỉnh THẬT (MSB thưởng 20% ngày 28/08) họ sẽ lướt qua. Cùng
họ với "alarm fatigue" mà `vnstock_doctor` đã đặt tên.
"""
from __future__ import annotations

from datetime import date

import vnstock_brief_guards_sections as gs
from vnstock_corp_ratio import adjusts_price

_DHDCD = "PNJ - Tổ chức ĐHĐCĐ bất thường 2026"
_BONUS = "Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 20.0%"
_CTX = {"today": date(2026, 8, 24), "upcoming_events": [
    {"ticker": "PNJ", "ex_date": "2026-08-24", "title": _DHDCD},
    {"ticker": "MSB", "ex_date": "2026-08-28", "title": _BONUS},
]}


class TestAdjustsPrice:
    def test_a_shareholder_meeting_does_not_adjust_the_price(self):
        assert adjusts_price(_DHDCD) is False

    def test_written_ballot_does_not_adjust_the_price(self):
        assert adjusts_price("Lấy ý kiến cổ đông bằng văn bản") is False

    def test_bonus_shares_do_adjust(self):
        assert adjusts_price(_BONUS) is True

    def test_cash_dividend_adjusts(self):
        assert adjusts_price("Trả cổ tức bằng tiền mặt, 500 đồng/CP") is True

    def test_rights_issue_adjusts(self):
        assert adjusts_price("Thực hiện quyền mua trái phiếu chuyển đổi") is True

    def test_a_meeting_that_also_distributes_still_adjusts(self):
        # Phân phối THẮNG chữ "đại hội" — thà cảnh báo thừa
        assert adjusts_price("ĐHĐCĐ thường niên thông qua trả cổ tức bằng tiền") is True

    def test_an_unknown_event_defaults_to_adjusting(self):
        # Không nhận ra ⇒ CẢNH BÁO. Bỏ sót cú điều chỉnh thật tệ hơn nhiều.
        assert adjusts_price("Sự kiện doanh nghiệp chưa từng gặp") is True

    def test_empty_title_defaults_to_adjusting(self):
        assert adjusts_price("") is True and adjusts_price(None) is True


class TestTheGuardStopsWarningAboutMeetings:
    def test_pnj_no_longer_gets_an_exdate_mark(self):
        src = ("## 📋 Watchlist sáng mai\n"
               "1. **PNJ** (Giá 42,650) — MUA vùng 42,650 · chốt lời 43,950 "
               "· cắt lỗ 41,350\n\n## ⚠️ Rủi ro\n")
        assert gs.enforce_exdate_levels(src, _CTX) == src

    def test_a_real_corporate_action_still_gets_the_mark(self):
        # Vùng watchlist chỉ soi _EXDATE_WL_DAYS ngày tới (=3), nên dựng sự
        # kiện chia thưởng trong tầm đó
        ctx = {"today": date(2026, 8, 24), "upcoming_events": [
            {"ticker": "PNJ", "ex_date": "2026-08-24", "title": _DHDCD},
            {"ticker": "MSB", "ex_date": "2026-08-26", "title": _BONUS},
        ]}
        src = ("## 📋 Watchlist sáng mai\n"
               "1. **MSB** (Giá 20,000) — MUA vùng 20,000\n\n## ⚠️ Rủi ro\n")
        out = gs.enforce_exdate_levels(src, ctx)
        assert "⚠️ GDKHQ 2026-08-26" in out

    def test_the_map_drops_meeting_only_tickers(self):
        assert set(gs._exdate_map(_CTX, 14)) == {"MSB"}

    def test_a_ticker_with_both_kinds_keeps_only_the_adjusting_one(self):
        ctx = {"today": date(2026, 8, 24), "upcoming_events": [
            {"ticker": "AAA", "ex_date": "2026-08-26", "title": _DHDCD},
            {"ticker": "AAA", "ex_date": "2026-08-26", "title": _BONUS},
        ]}
        _, titles = gs._exdate_map(ctx, 14)["AAA"]
        assert titles == [_BONUS]


class TestTheEventsFooterOnlyClaimsWhatIsTrue:
    def _sec(self):
        return "## 📅 Sự kiện sắp tới\nGì đó model tự viết\n\n## 🌐 Vĩ mô\n"

    def test_footer_appears_when_a_listed_event_adjusts_price(self):
        out = gs.enforce_upcoming_events(self._sec(), _CTX)
        assert "Giá tự điều chỉnh trong ngày GDKHQ" in out

    def test_footer_is_dropped_when_every_listed_event_is_a_meeting(self):
        ctx = {"upcoming_events": [
            {"ticker": "PNJ", "ex_date": "2026-08-24", "title": _DHDCD},
            {"ticker": "XYZ", "ex_date": "2026-08-25",
             "title": "Lấy ý kiến cổ đông bằng văn bản"},
        ]}
        out = gs.enforce_upcoming_events(self._sec(), ctx)
        assert "Giá tự điều chỉnh" not in out
        assert "PNJ" in out            # sự kiện vẫn được LIỆT KÊ, chỉ bỏ ghi chú sai

    def test_events_are_still_listed_verbatim(self):
        out = gs.enforce_upcoming_events(self._sec(), _CTX)
        assert "PNJ - Tổ chức ĐHĐCĐ bất thường 2026" in out
        assert "ngày 2026-08-28" in out
