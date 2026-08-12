"""Tests for vnstock_wss — import ĐỒ THẬT (bỏ replica 12/08).

Lịch sử: file này từng chép tay `is_futures` + một `BarAggregator` rút gọn
với chú thích "avoid importing vnstock_wss (heavy init at import)". Lý do đó
ĐÃ HẾT HẠN — commit 6cb23d9 (07/08) gỡ mkdir-lúc-import khỏi vnstock_wss;
đo lại 12/08: `import vnstock_wss` mất 0.4s, không tác dụng phụ.

Replica là test tự khen mình: bản thật đổi/hỏng thì test vẫn xanh. Bản
replica BarAggregator đã trôi thật — thiếu `diagnostics()`, thiếu 2 khoá
chẩn đoán trong suspect_samples, và chép cứng ngưỡng 500_000 thay vì dùng
`MAX_SINGLE_TICK_VOLUME`.
"""
import pandas as pd
import pytest

from vnstock_wss import (FUTURES_SYMBOLS, MAX_SINGLE_TICK_VOLUME,
                         BarAggregator, accum_to_delta, is_futures)


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

    # Dùng accum_to_delta THẬT (bỏ replica 12/08) — chú thích cũ "avoid
    # pulling in the heavy wss module" đã hết hạn từ 07/08.
    fn = staticmethod(accum_to_delta)

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


class TestBarAggregatorSanityCheck:
    """
    Defensive checks added to BarAggregator to stop the AAA 78× volume
    bug from polluting the warehouse: if a single tick contributes more
    than MAX_SINGLE_TICK_VOLUME (500K shares), the aggregator drops the
    volume contribution and counts the suspect.

    Dùng BarAggregator THẬT (bỏ replica 12/08) + hằng số THẬT
    MAX_SINGLE_TICK_VOLUME thay vì chép cứng 500_000.
    """

    @staticmethod
    def make_aggregator():
        return BarAggregator()

    def test_normal_volume_accepted(self):
        agg = self.make_aggregator()
        agg.add_tick("VCB", pd.Timestamp("2026-04-20 10:00:00"), 77.7,
                      volume=10_000)
        bar = list(agg._bars.values())[0]
        assert bar["volume"] == 10_000
        assert agg.suspect_count == 0

    def test_huge_volume_rejected(self):
        """The AAA-78× scenario: a single tick claiming 5M shares."""
        agg = self.make_aggregator()
        agg.add_tick("AAA", pd.Timestamp("2026-04-20 10:00:00"), 7.12,
                      volume=5_000_000)
        bar = list(agg._bars.values())[0]
        assert bar["volume"] == 0   # rejected
        assert agg.suspect_count == 1
        assert len(agg._suspect_samples) == 1

    def test_negative_volume_rejected(self):
        agg = self.make_aggregator()
        agg.add_tick("VCB", pd.Timestamp("2026-04-20 10:00:00"), 77.7,
                      volume=-100)
        assert agg.suspect_count == 1

    def test_price_still_updated_on_suspect_tick(self):
        """Price-side fields update even when volume is rejected."""
        agg = self.make_aggregator()
        agg.add_tick("VCB", pd.Timestamp("2026-04-20 10:00:00"), 77.7, 10_000)
        agg.add_tick("VCB", pd.Timestamp("2026-04-20 10:00:30"), 80.0,
                      volume=99_999_999)   # absurd
        bar = list(agg._bars.values())[0]
        assert bar["high"] == 80.0
        assert bar["close"] == 80.0
        assert bar["volume"] == 10_000   # only the first tick contributed
        assert agg.suspect_count == 1

    def test_threshold_boundary(self):
        """Exactly at MAX should be accepted, just over should be rejected."""
        agg = self.make_aggregator()
        agg.add_tick("X", pd.Timestamp("2026-04-20 10:00:00"), 100.0,
                      volume=MAX_SINGLE_TICK_VOLUME)   # at threshold
        assert agg.suspect_count == 0
        agg.add_tick("X", pd.Timestamp("2026-04-20 10:01:00"), 100.0,
                      volume=MAX_SINGLE_TICK_VOLUME + 1)   # over
        assert agg.suspect_count == 1
