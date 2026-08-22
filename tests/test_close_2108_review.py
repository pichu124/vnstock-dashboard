"""
Soi brief close 21/08/2026 — hai lỗi lọt ra bản gửi Telegram.

① `📊 Tổng kết phiên` mở đầu bằng **"VNINDEX đóng cửa tăng mạnh +51% so với
   phiên trước"**. 51 là % đổi GTGD bị dán sang chỉ số; chỉ số thật +1.95%,
   và chính brief đó viết +1.95% ở cả TLDR lẫn mục kỹ thuật ⇒ TỰ MÂU THUẪN.
   `enforce_vnindex_change` ĐÃ có mặt để chặn đúng ca này (vết 16/06, 15/07)
   nhưng regex `(?:tăng|giảm)\\s*\\d` không khớp khi có TRẠNG TỪ chen giữa —
   guard là NO-OP với đúng cách viết model hay dùng nhất.

② Khối `📰 Tin kinh tế/chính trị` vỡ dòng:
       — tác động: An ninh tại Horm      (cắt giữa từ, không dấu …)
       — tác động: `
       *                                  (rác markdown + XUỐNG DÒNG)
   Khối tin dựng theo TỪNG DÒNG nên một ký tự `\\n` trong `_impact` đẩy phần
   còn lại thành dòng lạc — nhìn hệt như câu bị cụt.
"""
from __future__ import annotations

import vnstock_brief_guards_numbers as gn
from vnstock_brief_canon import _market_news_body_lines, sanitize_impact

_CTX = {"vnindex_tech": {"day_change_pct": 1.95}}

_REAL_LINE = (
    "VNINDEX đóng cửa tăng mạnh +51% so với phiên trước, đạt 1,768.12 điểm "
    "với GTGD cả ngày đạt 20,420.9 tỷ (tăng 51% so với phiên trước và tăng "
    "19% so với trung bình 20 phiên)."
)


class TestAdverbNoLongerHidesTheIndexNumber:
    def test_the_real_close_2108_line_is_repaired(self):
        out = gn.enforce_vnindex_change(_REAL_LINE, _CTX)
        assert "tăng 1.95% so với phiên trước" in out
        assert "+51% so với phiên trước" not in out

    def test_the_gtgd_clause_in_the_same_sentence_is_left_alone(self):
        # Mệnh đề GTGD trong ngoặc vẫn PHẢI giữ 51 — đè nó là guard tự tạo lỗi
        out = gn.enforce_vnindex_change(_REAL_LINE, _CTX)
        assert "(tăng 51% so với phiên trước" in out

    def test_every_intensifier_is_covered(self):
        for adv in ("mạnh", "mạnh mẽ", "nhẹ", "vọt", "nhanh", "đáng kể",
                    "ấn tượng", "khá", "tốt", "đột biến"):
            src = f"VNINDEX đóng cửa tăng {adv} 9.99% so với phiên trước."
            assert "tăng 1.95%" in gn.enforce_vnindex_change(src, _CTX), adv

    def test_adverb_does_not_defeat_the_gtgd_skip(self):
        src = "GTGD giảm mạnh 12.50% so với phiên trước."
        assert gn.enforce_vnindex_change(src, _CTX) == src

    def test_negative_day_still_reads_giam(self):
        src = "VNINDEX đóng cửa tăng mạnh +51% so với phiên trước."
        out = gn.enforce_vnindex_change(src, {"vnindex_tech": {"day_change_pct": -0.8}})
        assert "giảm 0.80%" in out and "tăng" not in out.split("cửa")[1]

    def test_guard_is_idempotent(self):
        once = gn.enforce_vnindex_change(_REAL_LINE, _CTX)
        assert gn.enforce_vnindex_change(once, _CTX) == once

    def test_no_day_change_is_a_noop(self):
        assert gn.enforce_vnindex_change(_REAL_LINE, {}) == _REAL_LINE


class TestImpactTextCannotBreakTheNewsBlock:
    def test_newline_inside_impact_is_flattened(self):
        assert "\n" not in sanitize_impact("Ảnh hưởng\nlan toả\nnhóm dầu khí")

    def test_markdown_debris_is_stripped(self):
        assert sanitize_impact("`\n*Ít tác động") == "Ít tác động"

    def test_a_bullet_stays_exactly_one_line(self):
        lines = _market_news_body_lines([{
            "_sentiment": "neutral", "_date_sort": "2026-08-21",
            "title": "Nga nói\nnội bộ Ukraine chia rẽ",
            "source_feed": "VnExpress", "_impact": "`\n*Ít tác động tới TTCK",
        }], directive=False)
        assert len(lines) == 1
        assert "\n" not in lines[0]
        assert lines[0].endswith("— tác động: Ít tác động tới TTCK")

    def test_long_impact_cuts_at_a_word_boundary_with_an_ellipsis(self):
        src = "An ninh tại Hormuz căng thẳng làm giá dầu " + "biến động " * 40
        out = sanitize_impact(src)
        assert out.endswith("…")
        assert len(out) <= 161
        assert not out.rstrip("…").endswith(" ")
        # KHÔNG được cắt giữa từ (vết "An ninh tại Horm")
        assert out.rstrip("…").split()[-1] in src.split()

    def test_short_impact_is_untouched(self):
        assert sanitize_impact("Ít tác động tới TTCK") == "Ít tác động tới TTCK"

    def test_empty_and_none_give_empty_string(self):
        assert sanitize_impact("") == ""
        assert sanitize_impact(None) == ""
        assert sanitize_impact("   \n  ") == ""

    def test_an_impact_that_is_only_debris_disappears_instead_of_showing_junk(self):
        lines = _market_news_body_lines([{
            "_sentiment": "neutral", "_date_sort": "2026-08-21",
            "title": "Tin gì đó", "source_feed": "X", "_impact": "`\n*",
        }], directive=False)
        assert "tác động" not in lines[0]

    def test_hyphens_and_percentages_survive(self):
        s = "Giá dầu -3.5% gây áp lực lên nhóm dầu khí"
        assert sanitize_impact(s) == s
