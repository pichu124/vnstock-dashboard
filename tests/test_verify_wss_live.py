"""
Lưới cho ``grade()`` của scripts/verify_wss_live.py — logic chấm 3 bất biến WSS.

Script verify chỉ chạy được trong giờ giao dịch; phần chấm điểm là hàm thuần
nên test được quanh năm. Ca nguy hiểm nhất thuộc họ bug quen của repo:
"không đo được" bị đọc nhầm thành "đạt" — snapshot rỗng phải ra ⚠️ (exit 1),
KHÔNG BAO GIỜ ra ✅ (exit 0).
"""
from __future__ import annotations

import importlib.util
from datetime import time as dtime
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_wss_live.py"
_spec = importlib.util.spec_from_file_location("verify_wss_live", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
grade = _mod.grade
quiet_phases = _mod.quiet_phases
has_continuous_matching = _mod.has_continuous_matching

INDEX = {"VNINDEX", "VN30", "HNXINDEX"}
FUTURES = {"VN30F1M", "VN30F2M"}


def _snap(rows: list[tuple[str, float]]) -> pd.DataFrame:
    """Dựng snapshot bars tối thiểu: (ticker, volume) → DataFrame đủ cột."""
    return pd.DataFrame([
        {"ticker": t, "time": pd.Timestamp("2026-08-13 09:30"),
         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": v}
        for t, v in rows
    ])


class TestGradeAllGood:
    def test_stocks_traded_index_silent_no_suspects_passes(self):
        snap = _snap([("VCB", 120_000), ("HPG", 250_000), ("FPT", 90_000),
                      ("VNINDEX", 0), ("VN30F1M", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 0
        assert sum(ln.startswith("✅") for ln in lines) == 3

    def test_pass_line_names_top_traded_tickers(self):
        snap = _snap([("VCB", 5), ("HPG", 999), ("VNINDEX", 0)])
        lines, _ = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert "HPG" in lines[0]


class TestGradeFailures:
    def test_index_volume_leak_fails_hard(self):
        snap = _snap([("VCB", 120_000), ("VNINDEX", 88_000)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 2
        assert any(ln.startswith("❌ [2]") and "VNINDEX" in ln for ln in lines)

    def test_futures_volume_leak_fails_hard(self):
        snap = _snap([("VCB", 120_000), ("VNINDEX", 0), ("VN30F1M", 3_000)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 2
        assert any("VN30F1M" in ln for ln in lines if ln.startswith("❌"))

    def test_all_stock_volume_zero_fails_hard(self):
        snap = _snap([("VCB", 0), ("HPG", 0), ("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 2
        assert any(ln.startswith("❌ [1]") for ln in lines)

    def test_suspect_ticks_fail_hard(self):
        snap = _snap([("VCB", 120_000), ("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 7, "suspect_samples": []},
                            INDEX, FUTURES)
        assert code == 2
        assert any(ln.startswith("❌ [3]") and "7" in ln for ln in lines)


class TestGradeUnsure:
    """Họ bug quen: không đo được PHẢI ra ⚠️/1, không được ra ✅/0."""

    def test_empty_snapshot_is_unsure_never_pass(self):
        empty = pd.DataFrame(
            columns=["ticker", "time", "open", "high", "low", "close", "volume"])
        lines, code = grade(empty, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 1
        assert not any(ln.startswith("✅") for ln in lines)

    def test_no_index_bars_at_all_is_unsure(self):
        snap = _snap([("VCB", 120_000), ("HPG", 90_000)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 1
        assert any(ln.startswith("⚠️ [2]") for ln in lines)

    def test_minority_traded_is_unsure_not_fail(self):
        rows = [("VCB", 100)] + [(f"T{i:02d}", 0) for i in range(9)]
        snap = _snap(rows + [("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 1
        assert any(ln.startswith("⚠️ [1]") for ln in lines)

    def test_missing_suspect_count_is_unsure(self):
        snap = _snap([("VCB", 120_000), ("VNINDEX", 0)])
        lines, code = grade(snap, {}, INDEX, FUTURES)
        assert code == 1
        assert any(ln.startswith("⚠️ [3]") for ln in lines)


class TestGradeSeverityOrdering:
    def test_fail_beats_unsure_in_exit_code(self):
        # [2] leak (❌) + [3] thiếu suspect_count (⚠️) → exit phải là 2
        snap = _snap([("VCB", 120_000), ("VNINDEX", 5_000)])
        _, code = grade(snap, {}, INDEX, FUTURES)
        assert code == 2


class TestSessionPhaseHelpers:
    """
    ``_is_market_open()`` của vnstock_wss chỉ biết 9:00-15:00 — nó KHÔNG biết
    nghỉ trưa. Hai hàm thuần dưới đây bù đúng khoảng mù đó.
    """

    def test_midday_break_is_named(self):
        assert quiet_phases(dtime(11, 40), dtime(11, 42)) == "NGHỈ TRƯA"

    def test_continuous_window_has_no_quiet_phase(self):
        assert quiet_phases(dtime(10, 0), dtime(10, 2)) is None
        assert quiet_phases(dtime(13, 30), dtime(14, 0)) is None

    def test_ato_and_atc_are_named(self):
        assert quiet_phases(dtime(9, 2), dtime(9, 10)) == "ATO"
        assert quiet_phases(dtime(14, 35), dtime(14, 40)) == "ATC"

    def test_window_straddling_two_phases_names_both(self):
        note = quiet_phases(dtime(14, 40), dtime(14, 50))
        assert "ATC" in note and "thoả thuận" in note

    def test_window_touching_continuous_is_flagged_continuous(self):
        # 11:29-11:31 dính nghỉ trưa NHƯNG vẫn có 1 phút khớp lệnh liên tục
        assert quiet_phases(dtime(11, 29), dtime(11, 31)) == "NGHỈ TRƯA"
        assert has_continuous_matching(dtime(11, 29), dtime(11, 31)) is True

    def test_window_fully_inside_break_has_no_continuous(self):
        assert has_continuous_matching(dtime(11, 40), dtime(12, 30)) is False

    def test_boundaries_are_half_open_not_overlapping(self):
        # Đúng 11:30 là mốc ĐÓNG của khung liên tục — chạm nó không tính
        assert has_continuous_matching(dtime(11, 30), dtime(11, 45)) is False
        assert has_continuous_matching(dtime(13, 0), dtime(13, 5)) is True


class TestGradeKnowsTheTradingCalendar:
    """
    Ca báo động giả 20/08: một lượt đo rơi vào khung KHÔNG khớp lệnh liên tục
    thì volume 0 là ĐÚNG. Chấm ❌ ở đó là đổ lỗi cho feed vì lỗi của lịch.
    """

    def test_all_zero_during_break_is_unsure_not_fail(self):
        snap = _snap([("VCB", 0), ("HPG", 0), ("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES,
                            window=(dtime(11, 40), dtime(11, 42)))
        assert code == 1
        assert any("NGHỈ TRƯA" in ln for ln in lines)

    def test_all_zero_during_continuous_still_fails_hard(self):
        snap = _snap([("VCB", 0), ("HPG", 0), ("VNINDEX", 0)])
        _, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES,
                        window=(dtime(10, 0), dtime(10, 2)))
        assert code == 2

    def test_no_window_keeps_the_old_hard_fail(self):
        # Gọi không truyền window (đường cũ) phải giữ nguyên hành vi
        snap = _snap([("VCB", 0), ("HPG", 0), ("VNINDEX", 0)])
        _, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES)
        assert code == 2

    def test_minority_traded_names_the_phase_when_window_is_quiet(self):
        rows = [("VCB", 100)] + [(f"T{i:02d}", 0) for i in range(9)]
        snap = _snap(rows + [("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES,
                            window=(dtime(11, 29), dtime(11, 31)))
        assert code == 1
        assert any("NGHỈ TRƯA" in ln for ln in lines)

    def test_minority_traded_in_continuous_window_says_run_longer(self):
        rows = [("VCB", 100)] + [(f"T{i:02d}", 0) for i in range(9)]
        snap = _snap(rows + [("VNINDEX", 0)])
        lines, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES,
                            window=(dtime(10, 0), dtime(10, 5)))
        assert code == 1
        assert any("chạy lại lâu hơn" in ln for ln in lines)

    def test_quiet_window_never_upgrades_a_real_leak_to_pass(self):
        # [2] rò volume index là ❌ CỨNG — lịch phiên không được che nó
        snap = _snap([("VCB", 0), ("VNINDEX", 5_000)])
        _, code = grade(snap, {"suspect_count": 0}, INDEX, FUTURES,
                        window=(dtime(11, 40), dtime(11, 42)))
        assert code == 2
