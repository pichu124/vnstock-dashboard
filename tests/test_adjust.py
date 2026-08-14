"""Tests for the corp-action events layer (vnstock_adjust)."""

from __future__ import annotations

import pandas as pd
import pytest


def test_capital_history_emits_bonus_events():
    """Simulates vnstock_data's capital_history() shape."""
    from vnstock_adjust import _extract_capital_history_as_events

    class FakeCompany:
        def capital_history(self):
            return pd.DataFrame({
                "date": ["2023-01-15", "2024-06-10", "2025-01-23"],
                "charter_capital": [37_000_000_000_000,
                                    55_890_000_000_000,
                                    83_556_000_000_000],
                "currency": ["VND", "VND", "VND"],
            })

    evts = _extract_capital_history_as_events(FakeCompany(), "VCB")
    assert len(evts) == 2                               # 2 increases
    assert all(e["type"] == "bonus" for e in evts)
    # First ratio: 55.89T / 37T ≈ 1.51
    assert evts[0]["ratio"] == pytest.approx(1.51, abs=0.05)
    # Second ratio: 83.56T / 55.89T ≈ 1.495
    assert evts[1]["ratio"] == pytest.approx(1.495, abs=0.05)


def test_capital_history_skips_tiny_changes():
    """ESOP / micro issuances under 2% should not generate events."""
    from vnstock_adjust import _extract_capital_history_as_events

    class FakeCompany:
        def capital_history(self):
            return pd.DataFrame({
                "date": ["2023-01-15", "2023-06-01"],
                "charter_capital": [100_000_000_000, 101_000_000_000],  # +1%
                "currency": ["VND", "VND"],
            })

    assert _extract_capital_history_as_events(FakeCompany(), "X") == []


def test_capital_history_handles_missing_method():
    """Returns [] when the company object doesn't expose capital_history."""
    from vnstock_adjust import _extract_capital_history_as_events

    class EmptyCompany:
        pass

    assert _extract_capital_history_as_events(EmptyCompany(), "X") == []




# ── Gộp nguồn thay vì first-wins (14/08 — vá vùng mù 12 mã của div_check) ──


def _div_company(rows):
    """Company giả chỉ có dividends() — đủ cho đường _extract_dividends."""
    class _C:
        def dividends(self):
            return pd.DataFrame(rows)
    return _C()


def _sources(monkeypatch, *companies):
    """Thay chuỗi nguồn bằng danh sách company giả (giữ nguyên thứ tự)."""
    import vnstock_adjust as va
    pairs = [(f"fake{i}", (lambda c: (lambda _t: c))(c))
             for i, c in enumerate(companies)]
    monkeypatch.setattr(va, "_company_sources", lambda: iter(pairs))


class TestMergedSources:
    def test_all_sources_consulted_not_first_wins(self, monkeypatch):
        """Nguồn 1 chỉ có sự kiện CŨ — sự kiện MỚI của nguồn 2 vẫn phải vào.
        (Trước 14/08: nguồn 1 có gì đó là break — đúng hình vùng mù VNM/SAB.)"""
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2018-05-10",
                                "cash_dividend": 1000.0}]),
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 2
        assert str(max(df["ex_date"])) == "2026-04-15"

    def test_exact_duplicate_prefers_earlier_source(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]),
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1400.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        assert df.loc[0, "cash_amount"] == 1500.0

    def test_near_duplicate_two_dates_same_event_collapsed(self, monkeypatch):
        """Nguồn B ghi record-date lệch 2 ngày → vẫn là MỘT sự kiện, giữ bản
        nguồn ưu tiên — không được đẻ ra 'sự kiện ma' cho div_check chấm."""
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-04-15",
                                "cash_dividend": 1500.0}]),
                 _div_company([{"exercise_date": "2026-04-17",
                                "cash_dividend": 1500.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 1
        assert str(df.loc[0, "ex_date"]) == "2026-04-15"

    def test_distinct_events_far_apart_both_kept(self, monkeypatch):
        from vnstock_adjust import _fetch_events
        _sources(monkeypatch,
                 _div_company([{"exercise_date": "2026-01-10",
                                "cash_dividend": 800.0},
                               {"exercise_date": "2026-06-10",
                                "cash_dividend": 700.0}]))
        df = _fetch_events("VNM")
        assert len(df) == 2

    def test_broken_first_source_falls_through(self, monkeypatch):
        import vnstock_adjust as va
        from vnstock_adjust import _fetch_events

        def _boom(_t):
            raise RuntimeError("nguồn chết")
        ok = _div_company([{"exercise_date": "2026-04-15",
                            "cash_dividend": 1500.0}])
        monkeypatch.setattr(va, "_company_sources",
                            lambda: iter([("dead", _boom),
                                          ("ok", lambda _t: ok)]))
        df = _fetch_events("VNM")
        assert len(df) == 1
