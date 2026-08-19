"""`horizon_days` là số PHIÊN — mọi chỗ so với tuổi tính bằng NGÀY LỊCH phải
quy đổi trước (vết 19/08).

Vì sao có file này: `reconcile_recommendations` lấy `hist.head(horizon)` rồi
chấm điểm ngay, nhưng `head()` trả về ÍT hơn horizon bar khi chưa đủ phiên —
và `_grade_rec` vẫn dán "expire" tại close của bar CUỐI CÙNG CÓ SẴN. Lệnh
20 phiên bị chốt ở ~bar 14 (−30%), lệnh 5 phiên ở ~bar 3-4. Đóng lệnh là
VĨNH VIỄN (không có đường mở lại), nên sai ở đây là hỏng vĩnh viễn số liệu
dùng để chấm chiến lược — chính con số mục theo dõi #32 đang dựa vào.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from vnstock_strategy import calendar_days_for_sessions


class TestCalendarConversion:

    def test_five_sessions_is_a_full_week(self):
        assert calendar_days_for_sessions(5) == 7

    def test_twenty_sessions_is_four_weeks(self):
        """Đúng ca đau: tầng vị thế 20 phiên = 28 ngày lịch, không phải 20."""
        assert calendar_days_for_sessions(20) == 28

    def test_never_shorter_than_the_session_count(self):
        for n in range(0, 40):
            assert calendar_days_for_sessions(n) >= n

    def test_monotonic_and_junk_input_is_zero_not_a_crash(self):
        vals = [calendar_days_for_sessions(n) for n in range(0, 25)]
        assert vals == sorted(vals)
        assert calendar_days_for_sessions("xx") == 0


def _hist(n_bars: int, start: str = "2026-07-16", close=100.0):
    """n bar sau ngày tạo rec, giá đi ngang (không chạm TP/SL)."""
    days = pd.bdate_range(start=start, periods=n_bars)
    return pd.DataFrame({
        "time": days, "open": close, "high": close + 0.5,
        "low": close - 0.5, "close": close, "volume": 1_000,
    })


class TestReconcileWaitsForAFullWindow:

    def _run(self, monkeypatch, *, horizon, bars, age_days, sl_break_at=None):
        import vnstock_train as vt
        created = datetime.now() - timedelta(days=age_days)
        rec = {"id": 1, "ticker": "AAA", "created_at": created.isoformat(),
               "entry_price": 100.0, "take_profit": 120.0, "cut_loss": 80.0,
               "horizon_days": horizon}
        closed: list = []

        class _Mem:
            @staticmethod
            def open_recommendations():
                return [rec]

            @staticmethod
            def close_recommendation(rid, exit_price=None, hit_target=None, notes=None):
                closed.append({"id": rid, "hit": hit_target})

        import vnstock_strategy as vs
        monkeypatch.setattr(vt, "mem", _Mem, raising=False)
        _h = _hist(bars, start=(created + timedelta(days=1)).date().isoformat())
        if sl_break_at is not None:
            _h.loc[sl_break_at, "low"] = 70.0        # thủng SL=80
        monkeypatch.setattr(vs, "_load_history", lambda t, days=0: _h)
        monkeypatch.setattr(vs, "check_strategy_decay", lambda: None, raising=False)
        summary = vt.reconcile_recommendations(verbose=False)
        return summary, closed

    def test_expire_is_refused_while_the_window_is_short(self, monkeypatch):
        """20 phiên, mới có 14 bar → KHÔNG được đóng. Đây là ca thật đang bóp
        méo verdict của tầng vị thế."""
        summary, closed = self._run(monkeypatch, horizon=20, bars=14, age_days=30)
        assert closed == [], "đóng lệnh khi cửa sổ mới đi được 14/20 phiên"
        assert summary["closed"] == 0 and summary["still_open"] == 1

    def test_expire_closes_once_the_window_is_complete(self, monkeypatch):
        summary, closed = self._run(monkeypatch, horizon=20, bars=20, age_days=30)
        assert [c["hit"] for c in closed] == ["expire"]
        assert summary["closed"] == 1

    def test_short_tier_also_protected(self, monkeypatch):
        """Tầng ngắn (5 phiên) đông rec hơn — 5 ngày lịch ≈ 3-4 phiên."""
        summary, _ = self._run(monkeypatch, horizon=5, bars=3, age_days=7)
        assert summary["closed"] == 0 and summary["still_open"] == 1

    def test_bar_count_decides_not_age(self, monkeypatch):
        """Tuổi theo ngày KHÔNG còn là căn cứ: đủ 20 bar thì đóng, bất kể lịch.
        Ngược lại thiếu bar thì không đóng dù đã lâu ngày (test ở trên)."""
        summary, closed = self._run(monkeypatch, horizon=20, bars=20, age_days=21)
        assert [c["hit"] for c in closed] == ["expire"] and summary["closed"] == 1

    def test_stop_loss_seen_immediately_not_after_the_horizon(self, monkeypatch):
        """Cổng cũ `age_days < horizon` giấu lệnh thủng SL tới tận ngày 20.
        Nay soi mỗi lượt nên nhận ra ngay — khớp ngữ nghĩa backtest."""
        summary, closed = self._run(monkeypatch, horizon=20, bars=2,
                                    age_days=3, sl_break_at=1)
        assert [c["hit"] for c in closed] == ["sl"]


class TestDisplayPathsUseTheSameRule:

    def test_brief_helper_matches_strategy_helper(self):
        from vnstock_brief import _horizon_calendar_days
        for n in (1, 5, 20, 33):
            assert _horizon_calendar_days(n) == calendar_days_for_sessions(n)

    def test_brief_keeps_a_position_rec_past_day_twenty(self):
        """Lệnh 20 phiên tuổi 24 ngày vẫn CÒN MỞ trong sổ → không được biến
        mất khỏi brief (trước bản vá thì mất từ ngày 21)."""
        from vnstock_brief import _horizon_calendar_days
        assert 24 <= _horizon_calendar_days(20)

    def test_telegram_overdue_label_uses_calendar_equivalent(self):
        import inspect
        import vnstock_telegram as tg
        src = inspect.getsource(tg._open_recs_block)
        assert "_horizon_calendar_days" in src
        assert "age > horizon " not in src
