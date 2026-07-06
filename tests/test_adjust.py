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


