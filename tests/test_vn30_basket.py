"""
Lưới cho ``vnstock_vn30`` (rổ VN30 hiện hành) + tầng nóng của động cơ live.

Vết 20/08/2026: HOSE đổi rổ VN30 (đổi 2 lần/năm), nhưng danh sách 30 mã được
CHÉP CỨNG ở ba module độc lập và không chỗ nào tự làm mới — heatmap live vẽ rổ
cũ suốt và KHÔNG có gì báo. Hai họ bug phải canh ở đây:

1. **Rổ teo âm thầm** — API trả dở dang (12 mã) mà vẫn được nhận thì heatmap
   mất mã, tệ hơn hẳn rổ cũ vì không ai biết vì sao.
2. **Vòng quét rỗng** — tách tầng nóng/lạnh mà chọn nhầm thì có vòng không
   quét mã nào, feed đứng hình trong khi status vẫn "connected".
"""
from __future__ import annotations

from datetime import datetime, timedelta

import vnstock_vn30 as v30
from vnstock_wss import split_hot_cold

_REAL30 = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB",
           "HPG", "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB",
           "SSI", "STB", "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC",
           "VNM", "VPB", "VRE"]


class TestValidate:
    def test_normalises_case_and_whitespace(self):
        assert v30.validate([" vcb ", "fpt"] + _REAL30[:28])[:2] == ["ACB", "BCM"]

    def test_rejects_a_truncated_basket(self):
        # Ca nguy hiểm nhất: API trả dở dang → rổ teo mà không ai biết
        assert v30.validate(_REAL30[:12]) is None

    def test_rejects_an_absurdly_large_basket(self):
        assert v30.validate([f"T{i:03d}" for i in range(200)]) is None

    def test_rejects_junk_symbols(self):
        assert v30.validate(_REAL30[:29] + ["THIS-IS-NOT-A-TICKER"]) is None

    def test_rejects_empty_and_none(self):
        assert v30.validate([]) is None
        assert v30.validate(None) is None

    def test_dedups(self):
        assert len(v30.validate(_REAL30 + _REAL30)) == 30


class TestResolveOrder:
    def test_live_wins_over_cache_and_fallback(self):
        live = sorted(set(_REAL30) - {"POW"} | {"VIX"})
        out = v30.resolve(fetch=lambda: live,
                          cache={"members": _REAL30, "updated_at": "2026-08-01T00:00:00"},
                          fallback=_REAL30)
        assert out["source"] == "live"
        assert "VIX" in out["members"] and "POW" not in out["members"]

    def test_falls_back_to_cache_when_fetch_raises(self):
        def _boom():
            raise RuntimeError("mạng hỏng")
        out = v30.resolve(fetch=_boom,
                          cache={"members": _REAL30,
                                 "updated_at": datetime.now().isoformat()},
                          fallback=_REAL30)
        assert out["source"] == "cache" and out["stale"] is False

    def test_falls_back_to_constant_when_everything_fails(self):
        out = v30.resolve(fetch=lambda: None, cache=None, fallback=_REAL30)
        assert out["source"] == "fallback"
        assert out["members"] == sorted(_REAL30)
        assert out["stale"] is True

    def test_a_truncated_live_answer_does_not_replace_a_good_cache(self):
        out = v30.resolve(fetch=lambda: ["VCB", "FPT"],
                          cache={"members": _REAL30,
                                 "updated_at": datetime.now().isoformat()},
                          fallback=_REAL30)
        assert out["source"] == "cache"
        assert len(out["members"]) == 30

    def test_a_corrupt_cache_does_not_shrink_the_basket(self):
        out = v30.resolve(fetch=None, cache={"members": ["VCB"]}, fallback=_REAL30)
        assert out["source"] == "fallback" and len(out["members"]) == 30

    def test_old_cache_is_used_but_marked_stale(self):
        old = (datetime.now() - timedelta(days=30)).isoformat()
        out = v30.resolve(fetch=None, cache={"members": _REAL30, "updated_at": old},
                          fallback=_REAL30)
        assert out["source"] == "cache" and out["stale"] is True

    def test_cache_without_timestamp_is_stale_not_rejected(self):
        out = v30.resolve(fetch=None, cache={"members": _REAL30}, fallback=_REAL30)
        assert out["source"] == "cache" and out["stale"] is True


class TestDiffVsFallback:
    def test_names_both_directions(self):
        cur = sorted(set(_REAL30) - {"POW", "SAB"} | {"VIX", "DGC"})
        added, removed = v30.diff_vs_fallback(cur, fallback=_REAL30)
        assert added == ["DGC", "VIX"]
        assert removed == ["POW", "SAB"]

    def test_identical_basket_reports_nothing(self):
        assert v30.diff_vs_fallback(_REAL30, fallback=_REAL30) == ([], [])

    def test_hardcoded_constant_is_a_valid_basket(self):
        # Hằng số chép cứng phải tự nó qua được kiểm tỉnh táo, nếu không thì
        # lưới cuối cũng hỏng
        assert v30.validate(v30.fallback_members()) is not None


class TestCacheAge:
    def test_unparseable_timestamp_is_none_not_zero(self):
        assert v30.cache_age_days("hôm qua") is None
        assert v30.cache_age_days(None) is None

    def test_age_in_days(self):
        now = datetime(2026, 8, 20, 12, 0, 0)
        then = (now - timedelta(days=3)).isoformat()
        assert abs(v30.cache_age_days(then, now=now) - 3.0) < 1e-6


class TestHotTierSplit:
    HOT = frozenset({"VCB", "FPT", "VNINDEX"})
    SYMS = ["VCB", "FPT", "VNINDEX", "AAA", "BBB", "CCC", "DDD"]

    def test_hot_only_on_ordinary_cycles(self):
        assert split_hot_cold(self.SYMS, self.HOT, 1, every_n=5) == \
            ["VCB", "FPT", "VNINDEX"]

    def test_full_sweep_every_nth_cycle(self):
        assert split_hot_cold(self.SYMS, self.HOT, 0, every_n=5) == self.SYMS
        assert split_hot_cold(self.SYMS, self.HOT, 5, every_n=5) == self.SYMS

    def test_never_returns_an_empty_round_for_a_nonempty_input(self):
        # Không mã nóng nào → quét TẤT CẢ, tuyệt đối không quét rỗng
        for cycle in range(10):
            got = split_hot_cold(["AAA", "BBB"], self.HOT, cycle, every_n=5)
            assert got == ["AAA", "BBB"]

    def test_small_subscription_is_untouched(self):
        # `subscribe_all()` (38 mã, mọi mã đều nóng) phải giữ NGUYÊN hành vi
        allhot = ["VCB", "FPT", "VNINDEX"]
        for cycle in range(10):
            assert split_hot_cold(allhot, self.HOT, cycle, every_n=5) == allhot

    def test_kill_switch_restores_flat_sweep(self):
        for cycle in range(10):
            assert split_hot_cold(self.SYMS, self.HOT, cycle, every_n=5,
                                  tiering=False) == self.SYMS

    def test_every_n_of_one_is_a_flat_sweep(self):
        assert split_hot_cold(self.SYMS, self.HOT, 3, every_n=1) == self.SYMS

    def test_empty_input_stays_empty(self):
        assert split_hot_cold([], self.HOT, 1) == []

    def test_every_cold_symbol_is_reached_within_one_period(self):
        seen = set()
        for cycle in range(5):
            seen.update(split_hot_cold(self.SYMS, self.HOT, cycle, every_n=5))
        assert seen == set(self.SYMS)
