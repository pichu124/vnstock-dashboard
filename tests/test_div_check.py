"""
Lưới cho vnstock_div_check (mục 4d) — checker điều chỉnh cổ tức kho giá.

Toàn bộ phần chấm là hàm thuần trên chuỗi giá tổng hợp — test được quanh
năm không cần kho. Các ca canh kỹ nhất:
  * chuỗi THÔ (gap = −cổ tức tại ex-date) phải bị bắt — đây là lý do module
    tồn tại: backtest giữ lệnh 20-40 phiên ăn lỗ giả;
  * chuỗi ĐÃ điều chỉnh (không gap) phải được xác nhận sạch;
  * họ bug quen "không đo được ≠ đạt": cổ tức nhỏ chìm nhiễu / thiếu bar /
    sập sàn trùng ex-date / toàn inconclusive → không bao giờ ra ✅/exit 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vnstock_div_check import (VERDICT_ADJUSTED, VERDICT_RAW, VERDICT_UNSURE,
                               classify_event, expected_drop_pct, grade_report)

EX = pd.Timestamp("2026-06-10")


def _series(gap_pct: float = 0.0, noise_pct: float = 0.4, n: int = 120,
            base: float = 60.0, seed: int = 7) -> pd.DataFrame:
    """Chuỗi ngày quanh EX: nhiễu đều `noise_pct`, chèn `gap_pct` (âm = sụt)
    vào open+close của bar đầu tiên ≥ EX — mô phỏng chuỗi thô qua ex-date."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-08-12", periods=n)
    rets = rng.normal(0.0, noise_pct / 100.0, size=n)
    close = base * np.cumprod(1 + rets)
    close = pd.Series(close, index=dates)
    ex_pos = int((dates >= EX).argmax())
    if gap_pct:
        close.iloc[ex_pos:] *= (1 + gap_pct / 100.0)
    open_ = close.shift(1).fillna(close.iloc[0])   # open ≈ close hôm trước
    if gap_pct:                                     # gap hiện NGAY từ open
        open_.iloc[ex_pos] = close.iloc[ex_pos - 1] * (1 + gap_pct / 100.0)
    return pd.DataFrame({"time": dates, "open": open_.values,
                         "high": close.values * 1.01,
                         "low": close.values * 0.99,
                         "close": close.values})


class TestExpectedDrop:
    def test_cash_dividend_converts_vnd_to_price_units(self):
        # 1,500đ/cp trên giá 60 (nghìn đồng) = 2.5%
        pct, why = expected_drop_pct(
            {"type": "cash", "cash_amount": 1500.0}, close_prev=60.0)
        assert why == "" and pct == pytest.approx(2.5)

    def test_split_ratio_over_one_is_divisor(self):
        pct, _ = expected_drop_pct({"type": "split", "ratio": 2.0}, 60.0)
        assert pct == pytest.approx(50.0)

    def test_bonus_fraction_ratio(self):
        pct, _ = expected_drop_pct({"type": "bonus", "ratio": 0.1}, 60.0)
        assert pct == pytest.approx(100 * 0.1 / 1.1)

    @pytest.mark.parametrize("event", [
        {"type": "cash", "cash_amount": None},
        {"type": "cash", "cash_amount": "rác"},
        {"type": "stock", "ratio": None},
        {"type": "stock", "ratio": 0},
    ])
    def test_missing_params_return_none_with_reason(self, event):
        pct, why = expected_drop_pct(event, 60.0)
        assert pct is None and why


class TestClassifyEvent:
    def test_adjusted_series_confirmed_clean(self):
        res = classify_event(_series(gap_pct=0.0), EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_ADJUSTED

    def test_raw_gap_caught(self):
        # Chuỗi thô: sụt đúng 2.5% tại ex-date — lý do module tồn tại
        res = classify_event(_series(gap_pct=-2.5), EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_RAW
        assert res["observed_pct"] == pytest.approx(-2.5, abs=0.3)

    def test_small_dividend_drowned_in_noise_is_inconclusive(self):
        res = classify_event(_series(noise_pct=1.2), EX, expected_pct=0.6)
        assert res["verdict"] == VERDICT_UNSURE
        assert "chìm trong nhiễu" in res["reason"]

    def test_crash_day_on_ex_date_not_blamed_on_dividend(self):
        # Sập 12% trong khi cổ tức chỉ 2% — nhiễu trội, không dám kết luận
        res = classify_event(_series(gap_pct=-12.0), EX, expected_pct=2.0)
        assert res["verdict"] == VERDICT_UNSURE
        assert "nhiễu thị trường trội" in res["reason"]

    def test_absurd_yield_flags_unit_suspicion(self):
        res = classify_event(_series(), EX, expected_pct=55.0)
        assert res["verdict"] == VERDICT_UNSURE
        assert "đơn vị" in res["reason"]

    def test_missing_bars_around_ex_date(self):
        df = _series()
        df = df[(df["time"] < EX - pd.Timedelta(days=30))]   # cắt cụt trước EX
        res = classify_event(df, EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_UNSURE

    def test_calendar_hole_around_ex_date(self):
        df = _series()
        keep = (df["time"] < EX - pd.Timedelta(days=10)) | (df["time"] >= EX + pd.Timedelta(days=5))
        res = classify_event(df[keep], EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_UNSURE
        assert "đứt chuỗi" in res["reason"]

    def test_short_series_is_inconclusive(self):
        res = classify_event(_series(n=20), EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_UNSURE

    def test_nan_open_falls_back_to_close(self):
        df = _series(gap_pct=-2.5)
        ex_pos = int((df["time"] >= EX).argmax())
        df.loc[df.index[ex_pos], "open"] = np.nan
        res = classify_event(df, EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_RAW      # close cũng mang gap

    def test_positive_gap_reads_as_adjusted_not_raw(self):
        # Giá TĂNG tại ex-date (tin tốt trùng ngày) — không thể là gap thô
        res = classify_event(_series(gap_pct=+2.5), EX, expected_pct=2.5)
        assert res["verdict"] != VERDICT_RAW

    def test_unsorted_input_still_classified(self):
        df = _series(gap_pct=-2.5).sample(frac=1.0, random_state=3)
        res = classify_event(df, EX, expected_pct=2.5)
        assert res["verdict"] == VERDICT_RAW


def _t(ticker: str, events: list[dict]) -> dict:
    return {"ticker": ticker, "events": events, "has_cache": bool(events),
            "has_prices": True}


def _ev(verdict: str) -> dict:
    return {"ticker": "X", "ex_date": "2026-06-10", "type": "cash",
            "verdict": verdict, "observed_pct": -2.0, "expected_pct": 2.0,
            "reason": ""}


class TestGradeReport:
    def test_any_raw_gap_is_hard_fail(self):
        rep = grade_report([_t("VCB", [_ev(VERDICT_ADJUSTED)]),
                            _t("HPG", [_ev(VERDICT_RAW)])])
        assert rep["exit_code"] == 2 and len(rep["flagged"]) == 1

    def test_clean_evidence_passes(self):
        rep = grade_report([_t("VCB", [_ev(VERDICT_ADJUSTED),
                                       _ev(VERDICT_UNSURE)])])
        assert rep["exit_code"] == 0

    def test_all_inconclusive_never_passes(self):
        # "Không đo được ≠ đạt" — không có sự kiện nào chấm được thì exit 1
        rep = grade_report([_t("VCB", [_ev(VERDICT_UNSURE)]),
                            _t("HPG", [])])
        assert rep["exit_code"] == 1
        assert rep["tickers_no_events"] == ["HPG"]

    def test_no_events_anywhere_is_unsure_not_pass(self):
        rep = grade_report([_t("VCB", []), _t("HPG", [])])
        assert rep["exit_code"] == 1


class TestVerbosePrint:
    def test_verbose_shows_inconclusive_reason(self, capsys):
        from vnstock_div_check import _print_report
        rep = grade_report([_t("VIC", [{**_ev(VERDICT_UNSURE),
                                        "reason": "chìm trong nhiễu"}])])
        rep["days"] = 750
        rep["per_ticker"] = [_t("VIC", [{**_ev(VERDICT_UNSURE),
                                         "reason": "chìm trong nhiễu"}])]
        _print_report(rep, verbose=True)
        out = capsys.readouterr().out
        assert "chìm trong nhiễu" in out          # lý do phải nhìn thấy được

    def test_default_hides_inconclusive_detail(self, capsys):
        from vnstock_div_check import _print_report
        rep = grade_report([_t("VIC", [{**_ev(VERDICT_UNSURE),
                                        "reason": "chìm trong nhiễu"}])])
        rep["days"] = 750
        rep["per_ticker"] = [_t("VIC", [{**_ev(VERDICT_UNSURE),
                                         "reason": "chìm trong nhiễu"}])]
        _print_report(rep, verbose=False)
        assert "chìm trong nhiễu" not in capsys.readouterr().out
