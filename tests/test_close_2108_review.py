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


class TestReferenceBandIsNotCalledSupportOrResistance:
    """
    Đây KHÔNG phải model bịa mốc — CHÍNH repo bịa hộ nó, đều đặn mọi phiên.

    `_vn30_line` (vnstock_brief.py) gắn vào mỗi mã ⭐ một nhãn tính bằng
    `giá × 0,97` và `giá × 1,03` rồi GỌI CHÚNG LÀ "hỗ trợ ~X / kháng cự ~Y",
    và template còn ra lệnh "MỐC GIÁ SETUP MỖI MÃ LẤY TỪ …". Model chép lại
    trung thực ⇒ brief close 21/08: "giữ vững trên hỗ trợ 81,000 và hướng tới
    kháng cự 86,000" cho GAS — nghe như mốc kỹ thuật đo được, thực chất là
    83.500 ±3%. R:R chẵn 1,00 là hệ quả TẤT YẾU của cấu tạo đó, không phải
    trùng hợp.

    Đổi nhãn ở prompt là điều kiện CẦN. Guard này là điều kiện ĐỦ (doctrine
    repo: model phớt chỉ thị).
    """

    CTX = {"vn30_gainers": [{"Mã": "GAS", "last": 83.5}],
           "vn30_losers": [{"Mã": "PNJ", "last": 39.9}]}

    def _wl(self, body: str) -> str:
        return f"## 📋 Watchlist sáng mai\n{body}\n\n## ⚠️ Rủi ro cần lưu ý\nKháng cự 86,000 ở mục khác.\n"

    def test_the_real_gas_line_stops_claiming_support_and_resistance(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — MUA vùng 83,500 · chốt lời "
                       "86,000 · cắt lỗ 81,000 — Canh mua nếu giá giữ vững trên "
                       "hỗ trợ 81,000 và hướng tới kháng cự 86,000.")
        out = enforce_reference_band_wording(src, self.CTX)
        assert "hỗ trợ 81,000" not in out and "kháng cự 86,000" not in out.split("## ⚠️")[0]
        assert "mốc tham chiếu 81,000" in out and "mốc tham chiếu 86,000" in out

    def test_a_genuinely_measured_level_is_left_alone(self):
        # Mốc KHÔNG trùng dải ±3% ⇒ có thể là mốc thật ⇒ guard KHÔNG được đụng.
        # Nếu sau này nối pivot thật vào, guard vẫn im lặng đúng chỗ đó.
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — MUA vùng 83,500 — giữ trên hỗ trợ 79,200.")
        assert "hỗ trợ 79,200" in enforce_reference_band_wording(src, self.CTX)

    def test_other_sections_are_untouched(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — giữ trên hỗ trợ 81,000.")
        assert "Kháng cự 86,000 ở mục khác." in enforce_reference_band_wording(src, self.CTX)

    def test_exdate_suffix_numbers_are_not_mistaken_for_levels(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — giữ trên hỗ trợ 81,000 · "
                       "⚠️ GDKHQ 2026-08-26 (Cổ tức) — giá tham chiếu ≈ 81,000, "
                       "mốc trên CHƯA quy đổi")
        out = enforce_reference_band_wording(src, self.CTX)
        assert "mốc tham chiếu 81,000 ·" in out
        assert "giá tham chiếu ≈ 81,000" in out      # phần GDKHQ giữ nguyên

    def test_idempotent(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — giữ trên hỗ trợ 81,000.")
        once = enforce_reference_band_wording(src, self.CTX)
        assert enforce_reference_band_wording(once, self.CTX) == once

    def test_noop_without_ctx(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        src = self._wl("1. **GAS** (Giá 83,500) — giữ trên hỗ trợ 81,000.")
        assert enforce_reference_band_wording(src, {}) == src

    def test_bands_match_what_the_prompt_actually_prints(self):
        # Guard và prompt PHẢI dựng cùng một bộ số — lệch một bên là guard mù
        from vnstock_brief import build_prompt
        from vnstock_brief_guards_sections import _reference_bands
        ctx = {"date": "2026-08-21", "time": "15:00",
               "vn30_gainers": [{"Mã": "GAS", "Giá 1T %": 2.0, "Ngành": "NL",
                                 "last": 83.5, "GTGD TB (tỷ)": 300.0}]}
        p = build_prompt(ctx, brief_type="afternoon")
        assert "dải ±3% quanh giá: 81,000 – 86,000" in p
        assert _reference_bands(ctx)["GAS"] == {81000, 86000}

    def test_prompt_forbids_the_support_resistance_wording(self):
        from vnstock_brief import build_prompt
        p = build_prompt({"date": "2026-08-21", "time": "15:00",
                          "vn30_gainers": [{"Mã": "GAS", "Giá 1T %": 2.0,
                                            "Ngành": "NL", "last": 83.5,
                                            "GTGD TB (tỷ)": 300.0}]},
                         brief_type="afternoon")
        assert "KHÔNG gọi chúng là" in p

    def test_guard_is_wired_into_the_chain(self):
        # Guard quên nối = code chết trông y như code sống (doctrine repo)
        import inspect

        from vnstock_brief_guards import apply_brief_guards
        assert "enforce_reference_band_wording" in inspect.getsource(apply_brief_guards)
