"""Tests for vnstock_wss — futures detection."""
import pytest


# Extract is_futures logic to avoid importing vnstock_wss
# (which requires dotenv, pandas, and does heavy init at import)
FUTURES_SYMBOLS = ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"]


def is_futures(ticker: str) -> bool:
    """Replica of vnstock_wss.is_futures for testing."""
    t = str(ticker).upper()
    if t in FUTURES_SYMBOLS:
        return True
    if t.startswith("VN30F") and len(t) >= 6:
        return True
    if t.startswith("41I") and len(t) >= 6:
        return True
    return False


class TestIsFutures:

    def test_friendly_names(self):
        for sym in ("VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"):
            assert is_futures(sym) is True

    def test_expiry_codes(self):
        for sym in ("VN30F2410", "VN30F2504", "VN30F2601"):
            assert is_futures(sym) is True

    def test_hnx_internal_codes(self):
        for sym in ("41I1G4000", "41I1G5000", "41IABCDE"):
            assert is_futures(sym) is True

    def test_stocks_not_futures(self):
        for sym in ("VCB", "FPT", "HPG", "SSI", "ACB"):
            assert is_futures(sym) is False

    def test_index_not_futures(self):
        for sym in ("VNINDEX", "VN30", "HNXINDEX"):
            assert is_futures(sym) is False

    def test_case_insensitive(self):
        assert is_futures("vn30f1m") is True
        assert is_futures("Vn30F2M") is True


class TestAccumToDelta:
    """
    Regression tests for the accumulated-volume → delta conversion that feeds
    BarAggregator. The bug (EIB 2026-04-16 showing 183M on one minute) was
    caused by feeding session-accumulated volume straight into the aggregator,
    which then summed it bar-by-bar.
    """

    # Replica of vnstock_wss.accum_to_delta — kept in sync manually to avoid
    # pulling in the heavy wss module (dotenv, vnstock, pandas). If the real
    # helper changes, update this too.
    @staticmethod
    def fn(last_accum, last_date, accum, today):
        if last_date != today or last_accum is None or accum < last_accum:
            return 0.0
        return max(0.0, float(accum) - float(last_accum))

    def test_first_tick_no_prior_state_returns_zero(self):
        # Runner restart mid-session: last_accum=None. Must NOT emit the full
        # session total as one bogus bar — use 0 as baseline.
        assert self.fn(None, None, 50_000_000, "2026-04-17") == 0.0

    def test_new_day_resets_baseline(self):
        # Same ticker seen yesterday at accum=80M; today's first tick accum=1M.
        assert self.fn(80_000_000, "2026-04-16", 1_000_000, "2026-04-17") == 0.0

    def test_accum_backwards_resets(self):
        # API glitch / session reset: accum dropped. Treat as new baseline.
        assert self.fn(5_000_000, "2026-04-17", 1_000_000, "2026-04-17") == 0.0

    def test_normal_delta(self):
        # Two ticks same day: emit the difference.
        assert self.fn(1_000_000, "2026-04-17", 1_250_000, "2026-04-17") == 250_000

    def test_same_accum_emits_zero(self):
        # No trades between ticks.
        assert self.fn(1_000_000, "2026-04-17", 1_000_000, "2026-04-17") == 0.0

    def test_does_not_inflate_like_pre_fix(self):
        # Simulate 30 ticks over a minute with realistic accum growth.
        # Pre-fix behaviour summed all accum values = huge bar.
        # With delta conversion, total bar volume equals accum_end - accum_start.
        last_accum, last_date = None, None
        today = "2026-04-17"
        bar_total = 0.0
        accums = [100_000 * i for i in range(1, 31)]  # 100k → 3M
        for accum in accums:
            bar_total += self.fn(last_accum, last_date, accum, today)
            last_accum, last_date = accum, today
        # Expected: accum grew 100k → 3M, first tick baseline=0, so delta total
        # = 3,000,000 - 100,000 = 2,900,000. Definitely not sum of accums (46.5M).
        assert bar_total == 2_900_000
        assert bar_total < sum(accums) / 10
