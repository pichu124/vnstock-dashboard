"""
Lưới cho bộ nhớ chỉ báo của `MarketScreener`.

Đo trên máy thật 25/08: bước `screener` **1.318s = 22 phút**, nặng nhất cả
phát — hơn CẢ `sync`. Gốc rễ có cấu trúc: `run_all_presets` lặp preset ở
NGOÀI, `scan()` lặp mã ở TRONG, và filter của preset chỉ được áp SAU khi đã
đọc parquet + tính trọn bộ chỉ báo. **14 preset ⇒ 14 lượt quét kho y hệt
nhau** cho cùng ~1.600 mã, không nhớ gì giữa các lượt.

Bất biến phải giữ:
1. Cùng một mã ⇒ đọc đĩa + tính chỉ báo **đúng một lần**, dù quét bao nhiêu
   preset.
2. Kết quả **không đổi một chữ** so với đường cũ — cache không được làm lệch
   kết quả sàng lọc.
3. Cache trả **bản sao**: chỗ gọi gắn thêm `ticker`/`industry` vào dict, sửa
   thẳng vào cache là preset sau nhận rác của preset trước.
4. `min_rows` đổi theo preset nên KHÔNG được nướng vào cache.
"""
from __future__ import annotations

import pandas as pd
import pytest

import vnstock_screener as sc


@pytest.fixture()
def screener(monkeypatch):
    """MarketScreener rỗng ruột — không đụng kho, đếm số lần đọc/tính."""
    obj = sc.MarketScreener.__new__(sc.MarketScreener)
    obj.tickers = ["AAA", "BBB"]
    obj.industry_map = {}
    obj.fundamentals = None
    obj.industry_medians = {}
    obj._ind_cache = {}

    calls = {"load": 0, "calc": 0}

    def _load(ticker):
        calls["load"] += 1
        return pd.DataFrame({"close": [10.0] * 60, "volume": [1] * 60})

    def _calc(df):
        calls["calc"] += 1
        return {"rsi": 42.0, "close": 10.0}

    monkeypatch.setattr(obj, "_load_ticker", _load, raising=False)
    monkeypatch.setattr(sc, "_calc_indicators", _calc)
    return obj, calls


class TestIndicatorCache:
    def test_one_read_and_one_compute_per_ticker_across_presets(self, screener):
        obj, calls = screener
        for _ in range(14):                      # đúng số preset thật
            for tk in obj.tickers:
                obj._indicators_for(tk, min_rows=30)
        assert calls["load"] == 2 and calls["calc"] == 2

    def test_the_cached_value_is_a_copy(self, screener):
        obj, _ = screener
        first = obj._indicators_for("AAA", min_rows=30)
        first["ticker"] = "AAA"
        first["rsi"] = -999
        second = obj._indicators_for("AAA", min_rows=30)
        assert "ticker" not in second and second["rsi"] == 42.0

    def test_min_rows_is_re_evaluated_per_preset_not_baked_in(self, screener):
        obj, calls = screener
        assert obj._indicators_for("AAA", min_rows=30) is not None
        assert obj._indicators_for("AAA", min_rows=200) is None   # 60 bar < 200
        assert obj._indicators_for("AAA", min_rows=30) is not None
        assert calls["load"] == 1                # vẫn chỉ đọc một lần

    def test_an_empty_ticker_is_remembered_as_a_miss(self, screener, monkeypatch):
        obj, calls = screener
        monkeypatch.setattr(obj, "_load_ticker",
                            lambda t: pd.DataFrame(), raising=False)
        for _ in range(5):
            assert obj._indicators_for("CCC", min_rows=30) is None
        assert calls["calc"] == 0                # không tính trên df rỗng

    def test_indicators_returning_nothing_is_remembered_too(self, screener, monkeypatch):
        obj, calls = screener
        monkeypatch.setattr(sc, "_calc_indicators", lambda df: {})
        for _ in range(5):
            assert obj._indicators_for("AAA", min_rows=30) is None
        assert calls["load"] == 1


class TestScanStillProducesTheSameResult:
    def test_scan_result_is_identical_with_and_without_the_cache(self, monkeypatch):
        """Cache KHÔNG được làm lệch kết quả sàng lọc — chỉ được làm nhanh hơn."""
        frames = {
            "AAA": pd.DataFrame({"close": [10.0] * 60, "volume": [1] * 60}),
            "BBB": pd.DataFrame({"close": [20.0] * 60, "volume": [2] * 60}),
        }
        inds = {"AAA": {"rsi": 25.0, "close": 10.0},
                "BBB": {"rsi": 75.0, "close": 20.0}}

        def _mk():
            o = sc.MarketScreener.__new__(sc.MarketScreener)
            o.tickers = ["AAA", "BBB"]
            o.industry_map = {}
            o.fundamentals = None
            o.industry_medians = {}
            o._ind_cache = {}
            o._load_ticker = lambda t: frames[t]                 # noqa: E731
            return o

        monkeypatch.setattr(sc, "_calc_indicators",
                            lambda df: dict(inds["AAA" if df["close"].iloc[0] == 10.0
                                                 else "BBB"]))
        obj = _mk()
        got = list(obj.scan(custom_filter=lambda i: i["rsi"] < 30,
                            min_rows=30)["ticker"])
        assert got == ["AAA"]
        # Lượt thứ hai đi HOÀN TOÀN qua cache — vẫn phải ra y hệt
        again = list(obj.scan(custom_filter=lambda i: i["rsi"] < 30,
                              min_rows=30)["ticker"])
        assert again == got

    def test_a_second_preset_sees_clean_dicts(self, monkeypatch):
        """Preset trước gắn `ticker`/`industry` vào dict — preset sau không
        được nhận lại thứ đó qua cache."""
        obj = sc.MarketScreener.__new__(sc.MarketScreener)
        obj.tickers = ["AAA"]
        obj.industry_map = {"AAA": {"primary": "Thép", "secondary": ["Vật liệu"]}}
        obj.fundamentals = None
        obj.industry_medians = {}
        obj._ind_cache = {}
        obj._load_ticker = lambda t: pd.DataFrame(  # noqa: E731
            {"close": [10.0] * 60, "volume": [1] * 60})
        monkeypatch.setattr(sc, "_calc_indicators", lambda df: {"rsi": 20.0})

        obj.scan(custom_filter=lambda i: True, min_rows=30)
        cached = obj._ind_cache["AAA"][1]
        assert "ticker" not in cached and "industry" not in cached


class TestWiring:
    def test_scan_goes_through_the_cache(self):
        """Ai gỡ cache khỏi scan() là đỏ — 14 lượt quét kho quay lại ngay."""
        import inspect
        src = inspect.getsource(sc.MarketScreener.scan)
        assert "_indicators_for" in src
        assert "_calc_indicators(df)" not in src

    def test_there_really_are_fourteen_presets(self):
        # CLAUDE.md từng ghi "9 preset" — con số đó SAI, và nó là hệ số nhân
        # của toàn bộ chi phí bước screener.
        assert len(sc.PRESETS) == 14
