"""Tests cho khung GTGD cả ngày thống nhất (fix 21/07).

Close 16:18 in "GTGD 20,453.9 tỷ (+0% vs TB20)": SỐ là capture WSS còn %
bị guard pin theo khung EOD (14,878.9 / TB20 14,869.6) — hai khung lệch hệ
thống ~20-40% nên % cross-frame vô nghĩa ("+28%" bản 01:22 cùng họ lỗi).
Fix: _gtgd_close_frame chọn MỘT khung cho cả số lẫn % (WSS-với-WSS ưu tiên,
baseline mới _full_wss_baselines từ lịch sử cửa sổ 9h-15h — mirror TB sáng),
dùng chung bởi build_prompt + enforce_gtgd_total/compare_frame/baseline_pct.
"""

import vnstock_brief as vb


# Kịch bản thật 21/07: WSS 20,453.9 vs EOD 14,878.9 (lệch 37%)
WSS = {"today": 20_453.9, "prev": 19_800.0, "avg5": 20_100.0, "avg20": 19_900.0}
EOD_F = 14_878.9
EOD_CMP = {"prev": 19_069.2, "avg5": 15_559.7, "avg20": 14_869.6}


# ── _gtgd_close_frame (resolver) ───────────────────────────────────────────

def test_wss_frame_wins_when_baselines_exist():
    F, cmp, frame = vb._gtgd_close_frame(
        {"full_wss_gtgd": WSS, "full_day_gtgd": EOD_F,
         "full_day_gtgd_cmp": EOD_CMP})
    assert (F, frame) == (20_453.9, "wss")
    assert cmp == {"prev": 19_800.0, "avg5": 20_100.0, "avg20": 19_900.0}


def test_wss_without_history_uses_whole_eod_frame():
    """WSS có số nhưng không có lịch sử cùng khung, EOD đủ bộ → TRỌN khung
    EOD (số + %), không được lấy số WSS gắn % EOD."""
    F, cmp, frame = vb._gtgd_close_frame(
        {"full_wss_gtgd": {"today": 20_453.9},
         "full_day_gtgd": EOD_F, "full_day_gtgd_cmp": EOD_CMP})
    assert (F, frame) == (EOD_F, "eod")
    assert cmp == EOD_CMP


def test_wss_bare_when_no_eod_cmp():
    F, cmp, frame = vb._gtgd_close_frame({"full_wss_gtgd": {"today": 15_000.0}})
    assert (F, cmp, frame) == (15_000.0, {}, "wss")


def test_eod_only_and_empty():
    F, _cmp, frame = vb._gtgd_close_frame(
        {"full_day_gtgd": EOD_F, "full_day_gtgd_cmp": EOD_CMP})
    assert (F, frame) == (EOD_F, "eod")
    assert vb._gtgd_close_frame({}) == (None, {}, "")


def test_resolver_derives_today_from_session_stats():
    ss = {"9h-15h": {"VNINDEX": {"gtgd": 15_000.0}},
          "9h-11h30": {"VNINDEX": {"gtgd": 7_000.0}}}
    F, _cmp, frame = vb._gtgd_close_frame({"session_stats": ss})
    assert (F, frame) == (15_000.0, "wss")


def test_resolver_rejects_half_day_capture():
    """Capture chết giữa phiên (full ≈ sáng) không được đóng vai cả ngày —
    fallback EOD (hành vi mới, trước đây enforce_gtgd_total pin bừa số dở)."""
    ss = {"9h-15h": {"VNINDEX": {"gtgd": 7_165.4}},
          "9h-11h30": {"VNINDEX": {"gtgd": 7_165.4}}}
    F, _cmp, frame = vb._gtgd_close_frame(
        {"session_stats": ss, "full_day_gtgd": 14_000.0,
         "full_day_gtgd_cmp": {"prev": 13_500.0, "avg5": 13_800.0}})
    assert (F, frame) == (14_000.0, "eod")


# ── _full_wss_baselines ────────────────────────────────────────────────────

def _hist_day(full, morn=None):
    d = {"9h-15h": {"VNINDEX": {"gtgd": full}}}
    if morn is not None:
        d["9h-11h30"] = {"VNINDEX": {"gtgd": morn}}
    return d


def test_full_wss_baselines_mirror_morning_design():
    hist = {f"2026-07-{d:02d}": _hist_day(20_000.0, 8_000.0)
            for d in range(1, 21)}
    hist["2026-07-21"] = _hist_day(20_453.9, 8_400.0)
    out = vb._full_wss_baselines(hist, "2026-07-21")
    assert out == {"today": 20_453.9, "prev": 20_000.0,
                   "avg5": 20_000.0, "avg20": 20_000.0}


def test_full_wss_baselines_skips_dead_captures():
    """Ngày capture chết giữa phiên (full == sáng) bị loại khỏi baseline."""
    hist = {"2026-07-18": _hist_day(20_000.0, 8_000.0),
            "2026-07-19": _hist_day(7_000.0, 7_000.0),     # chết giữa phiên
            "2026-07-20": _hist_day(21_000.0, 8_000.0),
            "2026-07-21": _hist_day(20_453.9, 8_400.0)}
    out = vb._full_wss_baselines(hist, "2026-07-21")
    assert out["prev"] == 21_000.0
    assert out["avg5"] == round((20_000.0 + 21_000.0) / 2, 1)


def test_full_wss_baselines_none_when_today_invalid():
    hist = {"2026-07-21": _hist_day(7_165.4, 7_165.4)}     # today chết giữa phiên
    assert vb._full_wss_baselines(hist, "2026-07-21") is None
    assert vb._full_wss_baselines({}, "2026-07-21") is None


# ── build_prompt: số và % cùng khung ───────────────────────────────────────

def _close_ctx(**over):
    ctx = {"date": "2026-07-21", "time": "16:18",
           "session_timing": {"signal": "sig", "detail": "det"},
           "session_stats": {
               "9h-11h30": {"VNINDEX": {"gtgd": 8_400.0}},
               "9h-15h": {"VNINDEX": {"gtgd": 20_453.9}}},
           "full_wss_gtgd": dict(WSS),
           "full_day_gtgd": EOD_F,
           "full_day_gtgd_cmp": dict(EOD_CMP)}
    ctx.update(over)
    return ctx


def test_build_prompt_close_uses_wss_frame_end_to_end():
    p = vb.build_prompt(_close_ctx(), brief_type="afternoon")
    assert "GTGD cả ngày: 20,453.9 tỷ" in p
    assert "cùng khung đo" in p
    # % tính trên baseline WSS: 20,453.9/20,100 − 1 = +1.76% → "+2%"
    assert "TB5 phiên 20,100.0 tỷ (+2%)" in p
    # khung EOD không được lẻn vào khối GTGD
    assert "14,878.9" not in p and "14,869.6" not in p
    assert "ước tính từ EOD" not in p


def test_build_prompt_close_falls_back_to_whole_eod_frame():
    p = vb.build_prompt(_close_ctx(full_wss_gtgd=None,
                                   session_stats={
                                       "9h-11h30": {"VNINDEX": {"gtgd": 8_400.0}},
                                       "9h-15h": {"VNINDEX": {"gtgd": 20_453.9}}}),
                        brief_type="afternoon")
    # WSS không lịch sử + EOD đủ bộ → hiển thị TRỌN khung EOD, có nhãn nguồn
    assert "GTGD cả ngày: 14,878.9 tỷ" in p
    assert "ước tính từ EOD" in p
    assert "TB20 phiên 14,869.6 tỷ (+0%)" in p
    assert "20,453.9" not in p


# ── guards cùng khung ──────────────────────────────────────────────────────

def test_enforce_gtgd_total_pins_to_wss_frame_number():
    ctx = _close_ctx()
    ctx["vnindex_tech"] = {"intraday": False}
    t = ("🎯 TLDR\n**Kết quả phiên:** VNINDEX -0.74% với GTGD 14,878.9 tỷ.\n")
    out = vb.enforce_gtgd_total(t, ctx)
    assert "GTGD 20,453.9 tỷ" in out and "14,878.9" not in out


def test_enforce_gtgd_compare_frame_canonical_from_wss():
    """Guard thay chuỗi trộn khung bằng canonical tính trên CÙNG khung WSS."""
    ctx = _close_ctx()
    text = ("## 📊 Tổng kết phiên\n"
            "GTGD 20,453.9 tỷ, cao hơn TB sáng 5 phiên (+42%).\n")
    out = vb.enforce_gtgd_compare_frame(text, ctx)
    assert "TB sáng" not in out
    # p5 = +1.76% → +2%; p20 = 20,453.9/19,900 − 1 = +2.78% → +3%
    assert "TB5 phiên (+2%)" in out and "TB20 phiên (+3%)" in out


def test_guards_keep_eod_frame_when_no_wss():
    """Ctx chỉ có EOD (test cũ / máy không chạy WSS) → hành vi y như trước."""
    ctx = {"full_day_gtgd": 22_821.4,
           "full_day_gtgd_cmp": {"avg5": 22_821.4 / 1.5, "avg20": 22_821.4 / 1.25}}
    text = ("## 📊 Tổng kết phiên\n"
            "GTGD 22,821.4 tỷ, cao hơn TB sáng 5 phiên (+42%).\n")
    out = vb.enforce_gtgd_compare_frame(text, ctx)
    assert "cao hơn TB5 phiên (+50%) và TB20 phiên (+25%)" in out
