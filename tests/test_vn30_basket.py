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


class TestExtractSymbolsAcceptsWhatTheApiActuallyReturns:
    """
    Vết 20/08: `Listing.symbols_by_group("VN30")` của VCI trả **pd.Series**
    (`return df["symbol"]`), nhưng cả `vnstock_vn30._fetch_live` lẫn
    `vnstock_brief.get_vn30_live` đều dò `.columns` ⇒ AttributeError mỗi lần
    ⇒ im lặng rơi về hằng số. Đường "lấy rổ động" là **code chết trông y như
    code sống**, chỉ lòi ra khi doctor --net in "API không trả rổ dùng được".
    """

    def test_pandas_series_is_the_real_shape(self):
        import pandas as pd
        got = v30.extract_symbols(pd.Series(_REAL30, name="symbol"))
        assert got == _REAL30

    def test_dataframe_with_named_column_still_works(self):
        import pandas as pd
        assert v30.extract_symbols(pd.DataFrame({"ticker": _REAL30})) == _REAL30

    def test_single_column_frame_with_an_odd_name_is_accepted(self):
        import pandas as pd
        assert v30.extract_symbols(pd.DataFrame({"mã": _REAL30})) == _REAL30

    def test_multi_column_frame_without_a_symbol_column_is_refused(self):
        import pandas as pd
        df = pd.DataFrame({"a": _REAL30, "b": _REAL30})
        assert v30.extract_symbols(df) is None

    def test_plain_list_and_set(self):
        assert v30.extract_symbols(["VCB", " FPT "]) == ["VCB", "FPT"]
        assert sorted(v30.extract_symbols({"VCB", "FPT"})) == ["FPT", "VCB"]

    def test_empty_and_none_give_none_not_an_empty_basket(self):
        import pandas as pd
        assert v30.extract_symbols(None) is None
        assert v30.extract_symbols([]) is None
        assert v30.extract_symbols(pd.Series([], dtype=object)) is None

    def test_drops_nulls_without_stringifying_them(self):
        got = v30.extract_symbols(["VCB", None, "", "  ", "FPT"])
        assert got == ["VCB", "FPT"]

    def test_a_live_series_flows_all_the_way_through_resolve(self):
        import pandas as pd
        live = pd.Series(sorted(set(_REAL30) - {"POW"} | {"VIX"}), name="symbol")
        out = v30.resolve(fetch=lambda: v30.extract_symbols(live),
                          cache=None, fallback=_REAL30)
        assert out["source"] == "live" and "VIX" in out["members"]


class TestBriefUsesTheSameResolver:
    def test_get_vn30_live_delegates_to_the_resolver(self, monkeypatch):
        import vnstock_brief
        monkeypatch.setattr(v30, "get_members", lambda: ["VCB", "VIX"])
        assert vnstock_brief.get_vn30_live() == {"VCB", "VIX"}

    def test_get_vn30_live_falls_back_when_the_resolver_explodes(self, monkeypatch):
        import vnstock_brief
        from vnstock_brief_canon import VN30_TICKERS

        def _boom():
            raise RuntimeError("nổ")
        monkeypatch.setattr(v30, "get_members", _boom)
        assert vnstock_brief.get_vn30_live() == set(VN30_TICKERS)


class TestTheThreeHardcodedCopiesNeverDrift:
    """
    Rổ VN30 chép cứng ở BA module. Trước 20/08 không lưới nào canh chúng KHỚP
    NHAU — sửa một chỗ quên hai chỗ kia thì brief, tin và heatmap nói ba rổ
    khác nhau, im lặng. Lưới này rẻ và chặn đúng cái đó.
    """

    def _copies(self):
        from vnstock_brief_canon import VN30_TICKERS
        from vnstock_news import _VN30_FALLBACK
        from vnstock_wss import VN30_SYMBOLS
        return {
            "vnstock_brief_canon.VN30_TICKERS": set(VN30_TICKERS),
            "vnstock_news._VN30_FALLBACK": set(_VN30_FALLBACK),
            "vnstock_wss.VN30_SYMBOLS": set(VN30_SYMBOLS),
        }

    def test_all_three_copies_are_identical(self):
        copies = self._copies()
        ref_name, ref = next(iter(copies.items()))
        for name, got in copies.items():
            assert got == ref, (
                f"{name} lệch {ref_name}: thừa {sorted(got - ref)} · "
                f"thiếu {sorted(ref - got)}")

    def test_each_copy_holds_exactly_thirty_unique_tickers(self):
        from vnstock_news import _VN30_FALLBACK
        from vnstock_wss import VN30_SYMBOLS
        for name, got in self._copies().items():
            assert len(got) == 30, f"{name} có {len(got)} mã"
        # list thì còn phải không trùng lặp (set che mất trùng)
        assert len(_VN30_FALLBACK) == len(set(_VN30_FALLBACK))
        assert len(VN30_SYMBOLS) == len(set(VN30_SYMBOLS))

    def test_the_copies_pass_the_resolver_sanity_check(self):
        for name, got in self._copies().items():
            assert v30.validate(sorted(got)) is not None, name


class TestDiagPersistsWhatItFetched:
    """
    Vết 20/08: `--diag` in ✅ cả ba dòng nhưng vẫn để `(chưa có cache)` — nó
    gọi thẳng API rồi vứt kết quả đi. Lượt sau lại gọi mạng, và máy kia không
    được hưởng gì qua Dropbox, đúng lúc thiết kế nói "fetch 1 lần phục vụ cả
    2 máy".
    """

    def test_diag_writes_the_cache_after_a_good_fetch(self, monkeypatch, tmp_path, capsys):
        import pandas as pd
        cache = tmp_path / "vn30_members.json"
        monkeypatch.setattr(v30, "CACHE_PATH", cache)
        monkeypatch.setattr(v30, "load_cache", lambda: None)

        class _Listing:
            @staticmethod
            def symbols_by_group(_g):
                return pd.Series(_REAL30, name="symbol")

        monkeypatch.setitem(
            __import__("sys").modules, "vnstock_auth",
            type("M", (), {"get_vnstock": staticmethod(
                lambda *a, **k: type("C", (), {"listing": _Listing})())}))

        assert v30._diag() == 0
        assert cache.exists(), "diag phải ghi lại rổ vừa lấy được"
        import json
        assert set(json.loads(cache.read_text(encoding="utf-8"))["members"]) \
            == set(_REAL30)

    def test_diag_does_not_write_a_rejected_basket(self, monkeypatch, tmp_path):
        import pandas as pd
        cache = tmp_path / "vn30_members.json"
        monkeypatch.setattr(v30, "CACHE_PATH", cache)
        monkeypatch.setattr(v30, "load_cache", lambda: None)

        class _Listing:
            @staticmethod
            def symbols_by_group(_g):
                return pd.Series(["VCB", "FPT"], name="symbol")   # rổ teo

        monkeypatch.setitem(
            __import__("sys").modules, "vnstock_auth",
            type("M", (), {"get_vnstock": staticmethod(
                lambda *a, **k: type("C", (), {"listing": _Listing})())}))

        assert v30._diag() == 2
        assert not cache.exists(), "rổ không qua validate thì TUYỆT ĐỐI không ghi đè cache"


class TestFinancialsInTheBasketAreClassifiedAsFinancial:
    """
    `_FINANCIAL_TICKERS` là thứ giữ cho ngân hàng/chứng khoán/bảo hiểm KHÔNG
    bị xếp hạng rủi ro cơ bản chung với doanh nghiệp thường (D/E ngân hàng
    9-17 là BÌNH THƯỜNG, Op.CF âm chục nghìn tỷ cũng vậy). Mỗi kỳ đổi rổ mà
    quên bổ sung định chế tài chính MỚI là brief bắt đầu gọi tên nó như một
    rủi ro — sai mà nghe rất thuyết phục.

    TCX (Techcom Securities, vào rổ 08/2026) là ca đầu tiên chạm lưới này.
    """

    def test_every_financial_in_the_sector_map_is_in_the_financial_set(self):
        from vnstock_brief_canon import _FINANCIAL_TICKERS
        from vnstock_train import _VN30_SECTOR_MAP
        financial_kinds = {"bank", "securities", "insurance"}
        missing = sorted(
            tk for tk, kind in _VN30_SECTOR_MAP.items()
            if kind in financial_kinds and tk not in _FINANCIAL_TICKERS)
        assert not missing, (
            f"định chế tài chính thiếu trong _FINANCIAL_TICKERS: {missing} — "
            f"brief sẽ chấm chúng là rủi ro cơ bản vì đòn bẩy")

    def test_tcx_is_securities_in_both_files(self):
        from vnstock_brief_canon import _FINANCIAL_TICKERS
        from vnstock_train import _VN30_SECTOR_MAP
        assert _VN30_SECTOR_MAP.get("TCX") == "securities"
        assert "TCX" in _FINANCIAL_TICKERS

    def test_every_basket_member_has_a_sector(self):
        from vnstock_brief_canon import VN30_TICKERS
        from vnstock_train import _VN30_SECTOR_MAP
        missing = sorted(set(VN30_TICKERS) - set(_VN30_SECTOR_MAP))
        assert not missing, f"mã trong rổ chưa có ngành: {missing}"
