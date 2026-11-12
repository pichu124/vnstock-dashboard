"""Tests for vnstock_foreign_flow — full-market NN ròng cache + freshness loader.

Nguồn thế hệ 6 (`Market().equity.screener(date=…)`) được giả bằng `fake_screener_market`
— không test nào ra mạng.
"""
import importlib
import json

import pandas as pd
import pytest

import vnstock_foreign_flow as ff


def _use_tmp_cache(tmp_path, monkeypatch):
    p = tmp_path / "foreign_net_daily.json"
    monkeypatch.setattr(ff, "_CACHE", p)
    return p


def fake_screener_market(frames: dict, calls: list | None = None):
    """`Market` giả: `.equity.screener(date=d)` trả `frames[d]` (thiếu ⇒ bảng rỗng)."""
    class _Equity:
        def screener(self, date=None, **_):
            if calls is not None:
                calls.append(date)
            got = frames.get(date)
            if isinstance(got, Exception):
                raise got
            return got if got is not None else pd.DataFrame()

    class _Market:
        def __init__(self, *_a, **_k):
            self.equity = _Equity()
    return _Market


_BOARD = pd.DataFrame({
    "symbol": ["vcb", "FPT", "HPG", "AAA", "BBB"],
    "name": ["Vietcombank", "FPT", "Hòa Phát", "An Phát", "B"],
    "close": [60.0, 100.0, 25.0, 8.0, 5.0],
    "foreign_net_value": [12e9, -3.5e9, -0.5e9, 0.0, None],
    "foreign_net_volume": [200_000, -35_000, -20_000, 0, None],
    "foreign_room": [1.0, 2.0, 3.0, 4.0, 5.0],
})


def test_foreign_net_for_date_maps_screener_columns(monkeypatch):
    import vnstock
    calls = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-06-12": _BOARD}, calls))
    df = ff.foreign_net_for_date("2026-06-12")
    assert calls == ["2026-06-12"]                       # MỘT lượt cả thị trường, đúng phiên
    assert list(df.columns) == ["symbol", "foreign_net_value", "foreign_net_volume"]
    assert list(df["symbol"]) == ["VCB", "FPT", "HPG", "AAA", "BBB"]
    assert df.loc[0, "foreign_net_value"] == 12e9        # đồng, không đổi đơn vị
    assert df.loc[1, "foreign_net_volume"] == -35_000


def test_foreign_net_for_date_raises_vnstock_error_untouched(monkeypatch):
    import vnstock
    from vnstock.errors import InputError
    err = InputError("Chưa chọn nguồn")
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-06-12": err}))
    with pytest.raises(InputError):
        ff.foreign_net_for_date("2026-06-12")


def test_fetch_market_net_sums_full_board_in_ty(monkeypatch):
    import vnstock
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-06-12": _BOARD}))
    rec = ff.fetch_market_net("2026-06-12")
    assert rec == {"date": "2026-06-12", "net": 8.0, "buy": 12.0, "sell": 4.0,
                   "n_symbols": 3}                       # 0 và NaN không tính là có NN


def test_fetch_market_net_none_on_source_error_or_empty(monkeypatch):
    import vnstock
    from vnstock.errors import NetworkError
    monkeypatch.setattr(vnstock, "Market", fake_screener_market(
        {"2026-06-12": NetworkError("timeout")}))
    assert ff.fetch_market_net("2026-06-12") is None
    assert ff.fetch_market_net("2026-06-13") is None     # nguồn không có phiên


def test_refresh_keeps_cached_day_when_source_fails(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({"2026-06-11": {"net": -504.0, "n_symbols": 420}}),
                 encoding="utf-8")
    monkeypatch.setattr(ff, "fetch_market_net", lambda d: None)
    assert ff.refresh(days=3) == {"2026-06-11": {"net": -504.0, "n_symbols": 420}}


def test_load_market_net_1d_is_date_aware_and_omits_missing(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({
        "2026-06-11": {"net": -504.0, "buy": 3000.0, "sell": 3504.0, "n_symbols": 420},
        "2026-06-12": {"net": -491.0, "buy": 3100.0, "sell": 3591.0, "n_symbols": 418},
    }), encoding="utf-8")
    # exact date → that day's full-market net (not a frozen value)
    assert ff.load_market_net_1d("2026-06-12") == -491.0
    assert ff.load_market_net_1d("2026-06-11") == -504.0
    # a date NOT in cache → None (caller omits the signal, never shows stale)
    assert ff.load_market_net_1d("2026-06-13") is None
    # no date → latest cached day
    assert ff.load_market_net_1d() == -491.0
    # empty cache → None
    p.write_text("{}", encoding="utf-8")
    assert ff.load_market_net_1d("2026-06-12") is None


def test_regime_loader_uses_full_market_source_date_aware(tmp_path, monkeypatch):
    # vnstock_regime._load_nn_net_1d must read the full-market per-date cache and
    # return the right day's value (or 0.0 → omit) — NOT the legacy top-100 cache.
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({"2026-06-12": {"net": -491.0, "n_symbols": 418}}),
                 encoding="utf-8")
    import vnstock_regime
    importlib.reload(vnstock_regime)
    assert vnstock_regime._load_nn_net_1d("2026-06-12") == -491.0
    # unknown date → 0.0 (sentiment omits the NN signal rather than showing stale)
    assert vnstock_regime._load_nn_net_1d("2099-01-01") == 0.0


def test_sentiment_loader_maps_zero_to_none(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({"2026-06-12": {"net": -491.0}}), encoding="utf-8")
    import vnstock_regime
    importlib.reload(vnstock_regime)
    import vnstock_market_sentiment
    importlib.reload(vnstock_market_sentiment)
    assert vnstock_market_sentiment._load_nn_net_1d("2026-06-12") == -491.0
    # no fresh figure → None so compute_market_sentiment skips the NN signal
    assert vnstock_market_sentiment._load_nn_net_1d("2099-01-01") is None



# ── Đệm bảng NN ròng theo ngày (12/11: một lượt screener ≈ 50 giây) ─────────────

def _cache_on(monkeypatch, tmp_path, now_hhmm=(18, 0), today="2026-11-12"):
    import datetime as _dt
    monkeypatch.setenv("VNSTOCK_NN_SCREENER_CACHE", "1")
    monkeypatch.setattr(ff, "_DAY_CACHE_DIR", tmp_path / "nn_screener")
    y, m, d = map(int, today.split("-"))
    fixed = _dt.datetime(y, m, d, *now_hhmm, tzinfo=_dt.timezone(_dt.timedelta(hours=7)))
    monkeypatch.setattr(ff, "_vn_now", lambda: fixed)


def test_closed_session_is_fetched_once_then_read_from_disk(tmp_path, monkeypatch):
    pytest.importorskip("vnstock")
    import vnstock
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-11": _big_board()}, calls))
    _cache_on(monkeypatch, tmp_path)
    first = ff.foreign_net_for_date("2026-11-11")
    second = ff.foreign_net_for_date("2026-11-11")
    assert len(calls) == 1                                   # lần 2 đọc đệm, không gọi nguồn
    pd.testing.assert_frame_equal(second, first, check_dtype=False)   # kiểu chuỗi khác bản pandas
    assert (tmp_path / "nn_screener" / "2026-11-11.parquet").exists()


def test_today_before_close_is_not_cached(tmp_path, monkeypatch):
    pytest.importorskip("vnstock")
    import vnstock
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-12": _big_board()}, calls))
    _cache_on(monkeypatch, tmp_path, now_hhmm=(10, 30))
    ff.foreign_net_for_date("2026-11-12")
    ff.foreign_net_for_date("2026-11-12")
    assert len(calls) == 2 and not (tmp_path / "nn_screener" / "2026-11-12.parquet").exists()
    _cache_on(monkeypatch, tmp_path, now_hhmm=(18, 0))      # sau 15:30 ⇒ phiên đã chốt, đệm được
    ff.foreign_net_for_date("2026-11-12")
    assert (tmp_path / "nn_screener" / "2026-11-12.parquet").exists()


def test_source_error_is_not_cached_and_kill_switch(tmp_path, monkeypatch):
    pytest.importorskip("vnstock")
    import vnstock
    from vnstock.errors import NetworkError
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-10": NetworkError("timeout")}))
    _cache_on(monkeypatch, tmp_path)
    with pytest.raises(NetworkError):
        ff.foreign_net_for_date("2026-11-10")
    assert not (tmp_path / "nn_screener" / "2026-11-10.parquet").exists()
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-11": _BOARD}, calls))
    monkeypatch.setenv("VNSTOCK_NN_SCREENER_CACHE", "0")
    ff.foreign_net_for_date("2026-11-11")
    ff.foreign_net_for_date("2026-11-11")
    assert len(calls) == 2 and not (tmp_path / "nn_screener").exists()


def test_empty_or_thin_board_is_never_cached(tmp_path, monkeypatch):
    """Review 12/11: nguồn trả RỖNG / CỤT (chưa có bảng hôm nay lúc 15:31, lỗi im lặng) không được thành đệm
    vĩnh viễn (kho đi qua Dropbox) — lượt sau phải tải lại."""
    pytest.importorskip("vnstock")
    import vnstock
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-12": pd.DataFrame()}, calls))
    _cache_on(monkeypatch, tmp_path, now_hhmm=(15, 31))
    ff.foreign_net_for_date("2026-11-12")
    ff.foreign_net_for_date("2026-11-12")
    assert len(calls) == 2 and not (tmp_path / "nn_screener" / "2026-11-12.parquet").exists()
    calls2: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-11": _BOARD}, calls2))
    ff.foreign_net_for_date("2026-11-11")                  # _BOARD chỉ vài mã ⇒ "cụt" so với sàn
    assert not (tmp_path / "nn_screener" / "2026-11-11.parquet").exists()


def test_use_cache_false_always_hits_source(tmp_path, monkeypatch):
    """Doctor kiểm API mạng ⇒ không được đọc đệm của phiên trước."""
    pytest.importorskip("vnstock")
    import vnstock
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-11": _big_board()}, calls))
    _cache_on(monkeypatch, tmp_path)
    ff.foreign_net_for_date("2026-11-11")
    ff.foreign_net_for_date("2026-11-11", use_cache=False)
    assert len(calls) == 2


def _big_board(n: int = 300) -> pd.DataFrame:
    return pd.DataFrame({"symbol": [f"M{i:03d}" for i in range(n)],
                         "foreign_net_value": [1e8 * (1 if i % 2 else -1) for i in range(n)],
                         "foreign_net_volume": [1000] * n})



def test_thin_cache_file_is_refetched(tmp_path, monkeypatch):
    pytest.importorskip("vnstock")
    import vnstock
    _cache_on(monkeypatch, tmp_path)
    (tmp_path / "nn_screener").mkdir(parents=True)
    _BOARD.to_parquet(tmp_path / "nn_screener" / "2026-11-11.parquet", index=False)   # bản cụt cũ
    calls: list = []
    monkeypatch.setattr(vnstock, "Market", fake_screener_market({"2026-11-11": _big_board()}, calls))
    assert len(ff.foreign_net_for_date("2026-11-11")) == 300 and len(calls) == 1
