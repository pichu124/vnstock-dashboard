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

import numpy as np
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


# ── Kho đứng im: mã trễ > N phiên không xét preset ──────────────────────────
# Đo 17/10 trên kho thật: 517/1.723 mã có bar cuối trễ > 5 phiên so với VNINDEX
# (cách ly basis drift, ngừng giao dịch, huỷ niêm yết) — chỉ báo của chúng là
# của một ngày cũ, ra preset hôm nay là tín hiệu giả.

STALE_ENV = "VNSTOCK_SCREENER_STALE_SESSIONS"
# Tuần lễ 30/4: nghỉ T2 27/4 (Giỗ Tổ bù), T5 30/4, T6 1/5.
_HOLIDAY_SESSIONS = ["2026-04-24", "2026-04-28", "2026-04-29", "2026-05-04", "2026-05-05"]


@pytest.mark.parametrize("last_bar, expected", [
    ("2026-05-05", 0),            # bar cuối = phiên mới nhất
    ("2026-05-06", 0),            # bar mới hơn lịch (VNINDEX chậm một phiên) ⇒ không trễ
    ("2026-05-04", 1),
    ("2026-04-29 14:45", 2),      # giờ trong ngày không đổi phép đếm
    ("2026-04-24", 4),            # qua cuối tuần + 3 ngày lễ: 4 phiên, không phải 7 ngày làm việc
    ("2026-04-25", 4),            # bar ngày không phải phiên ⇒ đếm phiên SAU nó
    ("2026-01-02", 5),            # cũ hơn cả lịch ⇒ mọi phiên của lịch
])
def test_stale_sessions_counts_market_sessions_not_calendar_days(last_bar, expected):
    assert sc.stale_sessions(pd.Timestamp(last_bar), _HOLIDAY_SESSIONS) == expected


def test_stale_sessions_without_calendar_is_zero():
    assert sc.stale_sessions(pd.Timestamp("2026-01-02"), []) == 0


@pytest.mark.parametrize("raw, expected", [(None, 5), ("0", 0), ("8", 8), ("hỏng", 5)])
def test_stale_limit_reads_env(monkeypatch, raw, expected):
    monkeypatch.delenv(STALE_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(STALE_ENV, raw)
    assert sc.stale_limit() == expected


def _write_prices(root, ticker, times, close):
    df = pd.DataFrame({"time": times, "open": close, "high": close * 1.01,
                       "low": close * 0.99, "close": close, "volume": 1e6})
    for year, part in df.groupby(df["time"].dt.year):
        d = root / "prices" / f"ticker={ticker}" / f"year={year}"
        d.mkdir(parents=True, exist_ok=True)
        part.to_parquet(d / "prices.parquet", index=False)


@pytest.fixture()
def stale_warehouse(tmp_path, monkeypatch):
    """Kho thu nhỏ: VNINDEX (đang tăng) = lịch phiên; FRESH trễ 1 phiên, STALE trễ 10 phiên —
    cả hai rơi đều 1%/phiên (RSI 0 ⇒ lọt `oversold`). Ngày neo theo hôm nay vì `_load_ticker`
    chỉ đọc từ năm ngoái trở đi."""
    monkeypatch.delenv(STALE_ENV, raising=False)
    sessions = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=150)
    _write_prices(tmp_path, "VNINDEX", sessions, 1000.0 + np.arange(150))
    _write_prices(tmp_path, "FRESH", sessions[:-1], 50 * 0.99 ** np.arange(149))
    _write_prices(tmp_path, "STALE", sessions[:-10], 50 * 0.99 ** np.arange(140))
    return tmp_path


def _oversold(warehouse):
    from vnstock_runner import run_all_presets
    out = run_all_presets(str(warehouse), presets=["oversold"])
    return {r["ticker"] for r in out["presets"]["oversold"]["results"]}, out["stale_excluded"]


def test_eod_preset_skips_ticker_stale_10_sessions_keeps_1(stale_warehouse):
    got, stale = _oversold(stale_warehouse)
    assert got == {"FRESH"}
    assert stale == {"limit": 5, "count": 1, "tickers": {"STALE": 10}}


def test_eod_stale_filter_off_with_env_zero(stale_warehouse, monkeypatch):
    monkeypatch.setenv(STALE_ENV, "0")
    got, stale = _oversold(stale_warehouse)
    assert got == {"FRESH", "STALE"}
    assert stale == {"limit": 0, "count": 0, "tickers": {}}
