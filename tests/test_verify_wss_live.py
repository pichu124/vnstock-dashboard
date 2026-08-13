"""
Lưới cho ``grade()`` của scripts/verify_wss_live.py — logic chấm 3 bất biến WSS.

Script verify chỉ chạy được trong giờ giao dịch; phần chấm điểm là hàm thuần
nên test được quanh năm. Ca nguy hiểm nhất thuộc họ bug quen của repo:
"không đo được" bị đọc nhầm thành "đạt" — snapshot rỗng phải ra ⚠️ (exit 1),
KHÔNG BAO GIỜ ra ✅ (exit 0).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_wss_live.py"
_spec = importlib.util.spec_from_file_location("verify_wss_live", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
grade = _mod.grade

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
