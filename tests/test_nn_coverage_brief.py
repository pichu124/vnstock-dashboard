"""NN ròng NGÀNH tính thiếu phiên (vnstock thế hệ 6, 11/11): lượt tải NN của runner có ngày lỗi
(nguồn báo lỗi / chạm hạn mức) ⇒ `market_overview["nn_coverage"]` {sessions, asked, …}. Brief phải
gắn nhãn "(NN chỉ có X/20 phiên)" cạnh số NN ngành — prompt dặn, guard chốt (model hay bỏ).
"""
from __future__ import annotations

import vnstock_brief as vb
from vnstock_brief import build_prompt, enforce_nn_coverage_note, nn_coverage_label

_COV = {"sessions": 12, "asked": 20, "failed_days": 8, "source": "pipeline"}
_SECTORS = [
    {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1032.4, "NN 1M (tỷ)": -2536.0, "GTGD TB (tỷ)": 4000.0},
    {"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": 120.0, "NN 1M (tỷ)": 300.0, "GTGD TB (tỷ)": 900.0},
]
_CTX = {"nn_coverage": _COV, "sectors": _SECTORS}


def test_label_only_when_sessions_are_missing():
    assert nn_coverage_label(_CTX) == "NN chỉ có 12/20 phiên"
    assert nn_coverage_label({"nn_coverage": None}) is None
    assert nn_coverage_label({"nn_coverage": {"sessions": 20, "asked": 20}}) is None
    assert nn_coverage_label({"nn_coverage": {"sessions": "rác", "asked": 20}}) is None
    assert nn_coverage_label({}) is None


def test_guard_labels_first_sector_nn_figure_once_and_merges_frame_label():
    t = ("Khối ngoại bán ròng 159 tỷ, NN ròng ngành Ngân hàng -1,032 tỷ (1 tuần).\n"
         "Thép & Kim loại mua ròng 120 tỷ.")
    f = enforce_nn_coverage_note(t, _CTX)
    assert "Ngân hàng -1,032 tỷ (1 tuần; NN chỉ có 12/20 phiên)." in f
    assert f.count("NN chỉ có") == 1                           # đúng một lần, không rải mọi số
    assert "bán ròng 159 tỷ," in f                             # NN toàn thị trường 1D: không đụng
    assert enforce_nn_coverage_note(f, _CTX) == f              # idempotent


def test_guard_inside_parentheses_and_1m_figure():
    t = "Ngân hàng bị NN bán ròng mạnh nhất (-2,536 tỷ, 1 tuần), bias GIẢM"
    assert ("(-2,536 tỷ, 1 tuần; NN chỉ có 12/20 phiên), bias" in enforce_nn_coverage_note(t, _CTX))
    t2 = "Thép & Kim loại: NN mua ròng 300 tỷ trong tháng."
    assert "300 tỷ (NN chỉ có 12/20 phiên) trong tháng" in enforce_nn_coverage_note(t2, _CTX)


def test_guard_no_op_when_full_or_not_a_sector_figure():
    t = "NN ròng ngành Ngân hàng -1,032 tỷ (1 tuần)."
    assert enforce_nn_coverage_note(t, {**_CTX, "nn_coverage": None}) == t
    assert enforce_nn_coverage_note(t, {**_CTX, "sectors": []}) == t
    # số không khớp NN của ngành được nêu / dòng không nói "ròng" / chỉ NN toàn thị trường
    for other in ("NN ròng ngành Ngân hàng -500 tỷ.", "Ngân hàng GTGD 4,000 tỷ.",
                  "Khối ngoại bán ròng 159 tỷ."):
        assert enforce_nn_coverage_note(other, _CTX) == other


def test_guard_is_wired_into_shared_guard_chain():
    """Điểm parity duy nhất của brief sáng/chiều + engine Claude: `apply_brief_guards`."""
    out = vb.apply_brief_guards("NN ròng ngành Ngân hàng -1,032 tỷ (1 tuần), bị bán mạnh.", _CTX)
    assert "NN chỉ có 12/20 phiên" in out


def test_prompt_warns_when_sector_nn_is_short():
    ctx = {"date": "2026-11-10", "time": "15:00", "sectors": _SECTORS,
           "vnindex_tech": {"close": 1777.73, "intraday": False}}
    assert "tính THIẾU phiên" not in build_prompt(ctx, brief_type="afternoon")
    p = build_prompt({**ctx, "nn_coverage": _COV}, brief_type="afternoon")
    assert "NN ròng NGÀNH (1T/1M) tính THIẾU phiên: NN chỉ có 12/20 phiên" in p


def test_guard_needs_sector_name_next_to_the_figure():
    """Review 11/11: số NN 1D toàn thị trường trùng tình cờ NN tuần của ngành nêu xa trong câu ⇒ KHÔNG gắn;
    tên ngành là từ thường ("Khác") không được khớp chữ "khác" trong câu."""
    t = "Khối ngoại bán ròng 1,040 tỷ, tập trung ở ngân hàng."
    assert enforce_nn_coverage_note(t, _CTX) == t
    ctx = {**_CTX, "sectors": [{"Ngành": "Khác", "NN 1T (tỷ)": 45.0}]}
    t2 = "Khối ngoại mua ròng 45 tỷ hôm nay, khác hẳn tuần trước."
    assert enforce_nn_coverage_note(t2, ctx) == t2
    # số-trước-tên qua từ nối vẫn gắn
    t3 = "NN mua ròng 120 tỷ trong ngành Thép & Kim loại."
    assert "120 tỷ (NN chỉ có 12/20 phiên) trong ngành Thép" in enforce_nn_coverage_note(t3, _CTX)


def test_guard_marker_is_the_label_not_any_phrase_and_more_frame_labels():
    t = "NN chỉ có 2 ngành mua ròng; Ngân hàng -1,032 tỷ (1T) bị bán mạnh."
    out = enforce_nn_coverage_note(t, _CTX)
    assert "-1,032 tỷ (1T; NN chỉ có 12/20 phiên)" in out
    t2 = "Ngân hàng bán ròng -2,536 tỷ, 1 tuần qua."
    assert "-2,536 tỷ (NN chỉ có 12/20 phiên), 1 tuần qua" in enforce_nn_coverage_note(t2, _CTX)
