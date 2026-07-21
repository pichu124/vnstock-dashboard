"""Vá 2 bug từ review close brief 23:18 20/07 (user chốt "sửa cả 2").

Bug 1 — câu GTGD trộn khung dạng NHÃN-TRƯỚC-%-SAU lọt cả chuỗi guard:
  "Phiên chiều chiếm 60% GTGD (22,821.4 tỷ), cao hơn TB sáng 5 phiên (+42%)
   nhưng cao hơn TB cả ngày (+53%)."
  _MORNING_CMP_RE đòi mở đầu verb+% hoặc %+so/vs → trượt;
  enforce_gtgd_baseline_pct Form 2 cố ý bỏ baseline "sáng" → trượt nốt.
  (+42% vs TB sáng và +53% vs TB cả ngày còn vô lý nội tại: TB sáng >
  TB cả ngày là bất khả — sáng là tập con của cả ngày.)

Bug 2 — "thủng S1=1,733.25 → mục tiêu S2=1,457.31" (cách close ~16% =
  low_52w): _select_sr_levels không có TRẦN khoảng cách nên đáy 52w nghiễm
  nhiên đóng vai S2 khi thị trường thủng đáy 60 phiên; canon hợp lệ →
  enforce_sr_direction tầng 3 nhường. Fix: trần _SR_MAX_MOVE_PCT (7%) ngay
  từ nguồn → canon vai 2 rỗng → tầng 3 kéo mục tiêu về mức known kế tiếp
  trong tầm / cắt vế.
"""

import vnstock_brief as vb

F = 22821.4
CTX_GTGD = {
    "full_day_gtgd": F,
    # avg5 = F/1.5 → +50%; avg20 = F/1.25 → +25%
    "full_day_gtgd_cmp": {"avg5": F / 1.5, "avg20": F / 1.25, "prev": 23000.0},
}

TEXT_2007 = (
    "## 📊 Tổng kết phiên\n"
    "Phiên chiều chiếm 60% GTGD (22,821.4 tỷ), cao hơn TB sáng 5 phiên (+42%) "
    "nhưng cao hơn TB cả ngày (+53%). Độ rộng tiêu cực: A/D ratio 0.39, "
    "chỉ 10% mã trên MA200.\n"
)


# ── Bug 1: enforce_gtgd_compare_frame dạng nhãn-trước-%-sau ────────────────

def test_gtgd_label_first_morning_chain_replaced():
    out = vb.enforce_gtgd_compare_frame(TEXT_2007, CTX_GTGD)
    assert "TB sáng" not in out
    assert "TB cả ngày" not in out
    assert "cao hơn TB5 phiên (+50%) và TB20 phiên (+25%)" in out
    # phần không liên quan giữ nguyên
    assert "Phiên chiều chiếm 60% GTGD (22,821.4 tỷ)" in out
    assert "A/D ratio 0.39" in out


def test_gtgd_label_first_idempotent():
    out1 = vb.enforce_gtgd_compare_frame(TEXT_2007, CTX_GTGD)
    out2 = vb.enforce_gtgd_compare_frame(out1, CTX_GTGD)
    assert out2 == out1


def test_gtgd_label_first_through_full_guard_chain():
    out = vb.apply_brief_guards(TEXT_2007, CTX_GTGD)
    assert "TB sáng" not in out
    assert "TB5 phiên (+50%)" in out


def test_gtgd_morning_subject_left_alone():
    """Chủ ngữ là GTGD SÁNG → so sáng-với-sáng HỢP LỆ, không đụng."""
    text = (
        "## 📊 Tổng kết phiên\n"
        "GTGD phiên sáng 8,397.0 tỷ, cao hơn TB sáng 5 phiên (+12%).\n"
    )
    assert vb.enforce_gtgd_compare_frame(text, CTX_GTGD) == text


def test_gtgd_chain_other_subject_left_alone():
    """Chủ ngữ câu là KHỐI NGOẠI (không phải GTGD/thanh khoản) — cùng dạng
    "cao hơn TB sáng … (+N%)" nhưng KHÔNG được viết lại bằng số GTGD
    (review 21/07: regex thiếu anchor chủ ngữ)."""
    text = ("## 📊 Tổng kết phiên\n"
            "Khối ngoại bán ròng 500 tỷ, cao hơn TB sáng 5 phiên (+42%).\n")
    assert vb.enforce_gtgd_compare_frame(text, CTX_GTGD) == text


def test_gtgd_chain_subject_scoped_per_sentence():
    """GTGD ở CÂU TRƯỚC trên cùng dòng không cấp phép viết lại câu sau
    về khối ngoại — soi chủ ngữ trong phạm vi CÂU chứa chuỗi."""
    text = ("## 📊 Tổng kết phiên\n"
            "GTGD cả ngày 22,821.4 tỷ. Khối ngoại bán ròng 500 tỷ, "
            "cao hơn TB sáng 5 phiên (+42%).\n")
    assert vb.enforce_gtgd_compare_frame(text, CTX_GTGD) == text


def test_gtgd_label_first_reverse_order_chain():
    """Vế 'sáng' đứng SAU trong chuỗi vẫn bị thay trọn chuỗi."""
    text = (
        "## 📊 Tổng kết phiên\n"
        "GTGD cả ngày 22,821.4 tỷ, cao hơn TB cả ngày (+53%) và "
        "cao hơn TB sáng 5 phiên (+42%).\n"
    )
    out = vb.enforce_gtgd_compare_frame(text, CTX_GTGD)
    assert "TB sáng" not in out
    assert "TB5 phiên (+50%)" in out


def test_gtgd_morning_only_section_gate():
    """Ngoài mục 'Tổng kết phiên' → không đụng (guard close-only)."""
    text = (
        "## 🎯 TLDR\n"
        "GTGD 22,821.4 tỷ, cao hơn TB sáng 5 phiên (+42%).\n"
    )
    assert vb.enforce_gtgd_compare_frame(text, CTX_GTGD) == text


# ── Bug 2: trần khoảng cách vai S/R + kéo mục tiêu về mức gần ─────────────

CLOSE = 1743.51


def test_select_sr_levels_caps_distance():
    # đáy 52w cách ~16% KHÔNG được đóng vai S2 (kịch bản thật 20/07)
    assert vb._select_sr_levels([1733.25, 1457.31], CLOSE) == [1733.25]
    # mức trong tầm 7% vẫn được nhận làm vai 2
    assert vb._select_sr_levels([1733.25, 1690.0, 1457.31], CLOSE) == \
        [1733.25, 1690.0]
    # kháng cự đối xứng: mức xa +14% bị loại
    assert vb._select_sr_levels([1800.80, 1822.95, 1990.0], CLOSE) == \
        [1800.80, 1822.95]
    assert vb._select_sr_levels([1800.80, 1990.0], CLOSE) == [1800.80]


def _vt(**over):
    vt = dict(close=CLOSE, ma20=1836.58, ma50=1846.85, ma200=1771.99,
              support_1=1733.25, support_2=None,
              resistance_1=1800.80, resistance_2=1822.95,
              week_high=1830.0, week_low=1733.25,
              month_high=1860.0, month_low=1690.0,
              high_52w=1990.0, low_52w=1457.31)
    vt.update(over)
    return vt


SR_TEXT = ("**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=1,733.25 "
           "→ mục tiêu S2=1,457.31; hủy nếu vượt lại R1=1,800.80.")


def test_sr_far_target_pulled_to_near_known_level():
    """Canon vai 2 rỗng (đã lọc ở nguồn) → tầng 3 kéo mục tiêu về mức known
    kế tiếp trong tầm 7% (đáy tháng 1,690)."""
    out = vb.enforce_sr_direction(SR_TEXT, {"vnindex_tech": _vt()})
    assert "1,457.31" not in out
    assert "S2=1,690.00" in out
    assert "S1=1,733.25" in out and "R1=1,800.80" in out
    # idempotent
    assert vb.enforce_sr_direction(out, {"vnindex_tech": _vt()}) == out


def test_sr_far_target_cut_when_nothing_in_reach():
    """Không còn mức known nào dưới S1 trong tầm 7% → CẮT vế mục tiêu."""
    vt = _vt(month_low=1733.25)  # đáy tháng = S1 → dưới S1 chỉ còn low_52w
    out = vb.enforce_sr_direction(SR_TEXT, {"vnindex_tech": vt})
    assert "1,457.31" not in out
    assert "mục tiêu" not in out
    assert "thủng S1=1,733.25; hủy nếu vượt lại R1=1,800.80" in out


def test_sr_canon_within_reach_untouched():
    """Canon vai 2 hợp lệ trong tầm → guard nhường enforce_pivot_labels,
    không đụng (hành vi cũ giữ nguyên)."""
    vt = _vt(support_2=1690.0)
    text = ("canh giảm nếu thủng S1=1,733.25 → mục tiêu S2=1,690.00; "
            "hủy nếu vượt lại R1=1,800.80.")
    assert vb.enforce_sr_direction(text, {"vnindex_tech": vt}) == text
