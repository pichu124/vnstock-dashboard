"""NN ròng NGÀNH tính thiếu phiên (vnstock thế hệ 6, 11/11): lượt tải NN có ngày lỗi (nguồn báo
lỗi / chạm hạn mức) ⇒ `market_overview["nn_coverage"]` mang số phiên thiếu THEO KHUNG
(`missing_1t` trong 5 phiên gần nhất, `missing_1m` trong 20). Brief gắn nhãn
"(NN 1 tháng thiếu 8/20 phiên)" cạnh số NN ngành CỦA KHUNG THIẾU — prompt dặn, guard chốt.

Review 11/11: NN 1T = 5 phiên MỚI NHẤT có dữ liệu ⇒ phiên lỗi CŨ (ca thường gặp) không làm 1T
thiếu; gắn nhãn lên số tuần là bảo người đọc trừ hao một con số đầy đủ.
"""
from __future__ import annotations

import pandas as pd

import vnstock_brief as vb
from vnstock_brief import (build_prompt, enforce_nn_coverage_note, nn_coverage_label,
                           nn_coverage_labels)
from vnstock_runner import nn_window_gaps

_SECTORS = [
    {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1032.4, "NN 1M (tỷ)": -2536.0, "GTGD TB (tỷ)": 4000.0},
    {"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": 120.0, "NN 1M (tỷ)": 300.0, "GTGD TB (tỷ)": 900.0},
]
_OLD_GAPS = {"sessions": 12, "asked": 20, "source": "pipeline", "missing_1t": 0, "missing_1m": 8}
_RECENT_GAP = {"sessions": 19, "asked": 20, "source": "pipeline", "missing_1t": 1, "missing_1m": 1}
_CTX = {"nn_coverage": _OLD_GAPS, "sectors": _SECTORS}


# ── nn_window_gaps (runner): phiên thiếu theo khung ─────────────────────────────

def _nn(days):
    return pd.DataFrame({"symbol": "AAA", "date": pd.to_datetime(days), "net_value": 1e9})


def test_old_failed_sessions_do_not_short_the_week():
    have = pd.bdate_range(end="2026-11-10", periods=12)
    failed = [d.date().isoformat() for d in pd.bdate_range(end=have[0] - pd.Timedelta(days=1), periods=8)]
    cov = nn_window_gaps(_nn(have), {"sessions": 12, "asked": 20, "failed_dates": failed})
    assert (cov["missing_1t"], cov["missing_1m"]) == (0, 8)


def test_recent_failed_session_shorts_both_windows():
    days = pd.bdate_range(end="2026-11-10", periods=20)
    cov = nn_window_gaps(_nn(days[:-1]), {"sessions": 19, "asked": 20,
                                          "failed_dates": [days[-1].date().isoformat()]})
    assert (cov["missing_1t"], cov["missing_1m"]) == (1, 1)


def test_truncated_dashboard_load_counts_unasked_older_sessions():
    cov = nn_window_gaps(_nn(pd.bdate_range(end="2026-11-10", periods=2)),
                         {"sessions": 2, "asked": 20, "truncated": True, "failed_dates": []})
    assert (cov["missing_1t"], cov["missing_1m"]) == (3, 18)
    assert nn_window_gaps(_nn(["2026-11-10"]), None) is None


# ── nhãn + guard ────────────────────────────────────────────────────────────────

def test_labels_per_window():
    assert nn_coverage_labels(_CTX) == {"1T": None, "1M": "NN 1 tháng thiếu 8/20 phiên"}
    assert nn_coverage_label(_CTX) == "NN 1 tháng thiếu 8/20 phiên"
    assert nn_coverage_label({"nn_coverage": _RECENT_GAP}) == "NN 1 tuần thiếu 1/5 phiên gần nhất; NN 1 tháng thiếu 1/20 phiên"
    for cov in (None, {"missing_1t": 0, "missing_1m": 0}, {"missing_1m": "rác"}, {}):
        assert nn_coverage_label({"nn_coverage": cov}) is None


def test_week_figure_is_not_labelled_when_only_old_sessions_failed():
    t = "NN mua ròng mạnh nhất (1 tuần): Ngân hàng -1,032 tỷ."
    assert enforce_nn_coverage_note(t, _CTX) == t
    t2 = "Ngân hàng: NN bán ròng 2,536 tỷ trong tháng (1M)."
    assert "2,536 tỷ (NN 1 tháng thiếu 8/20 phiên) trong tháng" in enforce_nn_coverage_note(t2, _CTX)


def test_recent_gap_labels_week_figure_once_and_merges_frame_label():
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    t = ("Khối ngoại bán ròng 159 tỷ, NN ròng ngành Ngân hàng -1,032 tỷ (1 tuần).\n"
         "Thép & Kim loại mua ròng 120 tỷ.")
    f = enforce_nn_coverage_note(t, ctx)
    assert "Ngân hàng -1,032 tỷ (1 tuần; NN 1 tuần thiếu 1/5 phiên gần nhất)." in f
    assert f.count("NN 1 tuần thiếu") == 1 and "bán ròng 159 tỷ," in f
    assert enforce_nn_coverage_note(f, ctx) == f                       # idempotent
    t2 = "Ngân hàng bị NN bán ròng mạnh nhất (-1,032 tỷ, 1 tuần), bias GIẢM"
    assert "(-1,032 tỷ, 1 tuần; NN 1 tuần thiếu 1/5 phiên gần nhất), bias" in enforce_nn_coverage_note(t2, ctx)


def test_guard_needs_sector_name_next_to_the_figure():
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    for t in ("Khối ngoại bán ròng 1,040 tỷ, tập trung ở ngân hàng.",
              "Khối ngoại bán ròng 1,040 tỷ ở Ngân hàng hôm nay.",        # 'ở' trần = NN toàn thị trường
              "NN ròng ngành Ngân hàng -500 tỷ.", "Ngân hàng GTGD 4,000 tỷ."):
        assert enforce_nn_coverage_note(t, ctx) == t
    k = {**ctx, "sectors": [{"Ngành": "Khác", "NN 1T (tỷ)": 45.0}]}
    t = "Khối ngoại mua ròng 45 tỷ hôm nay, khác hẳn tuần trước."
    assert enforce_nn_coverage_note(t, k) == t
    t3 = "NN mua ròng 120 tỷ trong ngành Thép & Kim loại."
    assert "120 tỷ (NN 1 tuần thiếu 1/5 phiên gần nhất) trong ngành Thép" in enforce_nn_coverage_note(t3, ctx)
    # chữ số không kèm "tỷ" (2%, VN30) chen giữa tên và số không cắt cửa sổ
    t4 = "Ngân hàng giảm 2%, NN bán ròng 1,032 tỷ (1T) trong tuần."
    assert "1,032 tỷ (1T; NN 1 tuần thiếu 1/5 phiên gần nhất)" in enforce_nn_coverage_note(t4, ctx)


def test_guard_is_wired_into_shared_guard_chain():
    """Điểm parity duy nhất của brief sáng/chiều + engine Claude: `apply_brief_guards`."""
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    out = vb.apply_brief_guards("NN ròng ngành Ngân hàng -1,032 tỷ (1 tuần), bị bán mạnh.", ctx)
    assert "NN 1 tuần thiếu 1/5 phiên gần nhất" in out


def test_prompt_warns_only_for_short_windows():
    ctx = {"date": "2026-11-10", "time": "15:00", "sectors": _SECTORS,
           "vnindex_tech": {"close": 1777.73, "intraday": False}}
    assert "tính THIẾU phiên" not in build_prompt(ctx, brief_type="afternoon")
    p = build_prompt({**ctx, "nn_coverage": _OLD_GAPS}, brief_type="afternoon")
    assert "NN ròng NGÀNH tính THIẾU phiên (NN 1 tháng thiếu 8/20 phiên;" in p and "NN 1 tuần thiếu" not in p


def test_second_figure_of_same_sector_gets_its_window_label():
    """Review 11/11: "Ngân hàng bán ròng 1,032 tỷ (1T) và 2,536 tỷ (1M)" — số 1M cùng ngành với số
    đứng ngay trước (giữa chỉ có nhãn khung + từ nối) ⇒ vẫn nhận nhãn của khung 1M."""
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    t = "Ngân hàng bán ròng 1,032 tỷ (1T) và 2,536 tỷ (1M)."
    out = enforce_nn_coverage_note(t, ctx)
    assert "1,032 tỷ (1T; NN 1 tuần thiếu 1/5 phiên gần nhất)" in out
    assert "2,536 tỷ (1M; NN 1 tháng thiếu 1/20 phiên)" in out
    assert enforce_nn_coverage_note(out, ctx) == out                   # idempotent
    # có chữ khác chen giữa (ngành khác / NN toàn thị trường) ⇒ KHÔNG nối tiếp
    t2 = "Ngân hàng bán ròng 1,032 tỷ (1T), cả thị trường bán ròng 2,536 tỷ trong tháng."
    assert "2,536 tỷ (NN 1M" not in enforce_nn_coverage_note(t2, ctx)



def test_same_sector_pair_survives_the_full_guard_chain():
    """Review 11/11: qua `apply_brief_guards` thật, `enforce_nn_frame_labels` từng chèn "(1 tuần)"
    trước "(1T)" có sẵn (khung in hai lần) làm số 1M mất nhãn."""
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    out = vb.apply_brief_guards("Ngân hàng bán ròng 1,032 tỷ (1T) và 2,536 tỷ (1M).", ctx)
    first = out.splitlines()[0]                # dòng 2 là dòng chuẩn two_sides guard thêm
    assert "(1 tuần" not in first                                     # không in khung hai lần
    assert "1,032 tỷ (1T; NN 1 tuần thiếu 1/5 phiên gần nhất)" in first
    assert "2,536 tỷ (1M; NN 1 tháng thiếu 1/20 phiên)" in first
    assert vb.apply_brief_guards(out, ctx) == out          # `--from-file` chạy chuỗi lần 2


def test_full_chain_is_idempotent_and_keeps_week_trace_on_month_label():
    """Review 11/11: (a) nhãn gộp "(1T; NN 1 tuần thiếu …)" không được làm lượt 2 chèn lại "(1 tuần)";
    (b) số TUẦN đứng trước "(1M)" (enforce_sector_nn_figures ghim) vẫn mang dấu "(1 tuần)" như cũ."""
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    for t in ("Ngân hàng bán ròng 1,032 tỷ (1T).", "Ngân hàng bán ròng 1,032 tỷ đồng (1T).",
              "Ngân hàng bán ròng 1,032 tỷ (1T) và 2,536 tỷ (1M)."):
        once = vb.apply_brief_guards(t, ctx)
        assert vb.apply_brief_guards(once, ctx) == once, once
        assert "(1 tuần) (1T" not in once and "(1 tuần; NN 1 tuần thiếu 1/5 phiên gần nhất) (1T" not in once
    # số 1 THÁNG đúng có nhãn tháng: giữ nguyên (guard số NN ngành nhận khung tháng — 11/11)
    out = vb.apply_brief_guards("Ngân hàng bán ròng 2,536 tỷ (1M).", {**_CTX, "nn_coverage": None})
    assert "2,536 tỷ (1M)" in out.splitlines()[0] and "(1 tuần)" not in out.splitlines()[0]
    lab = vb.apply_brief_guards("Ngân hàng bán ròng 2,536 tỷ (1M).", _CTX).splitlines()[0]
    assert "2,536 tỷ (1M; NN 1 tháng thiếu 8/20 phiên)" in lab           # ngày thiếu 1M: đúng nhãn


def test_label_survives_jargon_rewrite_on_money_flow_lines():
    """Review 11/11: trên dòng "Dòng tiền", `enforce_no_composite_jargon` đổi "1M" → "1 tháng" — nhãn
    viết tắt bị đổi khiến lượt chạy lại gắn nhãn lần 2. Nhãn chữ đầy đủ ⇒ chuỗi guard idempotent."""
    for ctx in (_CTX, {**_CTX, "nn_coverage": _RECENT_GAP}):
        for t in ("- Dòng tiền ngoại: Ngân hàng bán ròng 2,536 tỷ trong tháng.",
                  "**Dòng tiền ngành:** Ngân hàng bán ròng 2,536 tỷ (1M), Thép & Kim loại mua ròng 120 tỷ.",
                  "- Dòng tiền ngoại: Thép & Kim loại mua ròng 300 tỷ (1M)."):
            once = vb.apply_brief_guards(t, ctx)
            assert vb.apply_brief_guards(once, ctx) == once, once
            assert once.count("thiếu") <= 2, once


def test_carry_only_to_a_self_contained_figure_of_another_window():
    ctx = {**_CTX, "nn_coverage": _RECENT_GAP}
    for t in ("Ngân hàng bán ròng 1,032 tỷ (1T), 2,536 tỷ toàn thị trường trong tháng.",
              "Ngân hàng bán ròng 1,032 tỷ (1T) và 1,040 tỷ (1T)."):          # cùng khung ⇒ không nối
        assert "NN 1 tháng thiếu" not in enforce_nn_coverage_note(t, ctx)
    t = "Ngân hàng bán ròng 1,032 tỷ, 2,500 tỷ cả thị trường."
    assert "NN 1 tháng thiếu" not in enforce_nn_coverage_note(t, {**_CTX, "nn_coverage": _OLD_GAPS})
