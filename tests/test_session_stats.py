"""Tests cho vnstock_session_stats — lệnh gọi vnstock thế hệ 6 (không mạng).

GTGD chỉ số "exact" đến từ `Market().index(s).trade_history(start, end)`: cột
`trading_date` (thế hệ 6 có múi giờ) phải ra ngày lịch VN, các cột tổng giữ tên
dòng cũ mà code phía sau đọc. Lỗi nguồn ⇒ bảng rỗng (caller rơi về ước lượng),
log một lần — fragment gọi mỗi 30s.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest

from tests.conftest import needs_vnstock

pytestmark = needs_vnstock


@pytest.fixture
def vss(monkeypatch, tmp_path):
    import vnstock_session_stats as mod

    monkeypatch.setattr(mod, "SESSION_STATS_PATH", tmp_path / "market_session_stats.json")
    monkeypatch.setattr(mod, "_PRICE_HISTORY_CACHE", {})
    monkeypatch.setattr(mod, "_LOGGED", set())
    return mod


def _fake_index_market(monkeypatch, frame=None, exc=None, asked=None):
    import vnstock

    class _Node:
        def __init__(self, symbol):
            self.symbol = symbol

        def trade_history(self, **kwargs):
            if asked is not None:
                asked.append((self.symbol, kwargs))
            if exc is not None:
                raise exc
            return frame.copy()

    class _Market:
        def index(self, symbol):
            return _Node(symbol)

        def equity(self, symbol):
            raise AssertionError("GTGD chỉ số không được đi nhánh cổ phiếu")

    monkeypatch.setattr(vnstock, "Market", _Market)


def _trade_history_frame(day: date, total_value: float) -> pd.DataFrame:
    return pd.DataFrame({
        "trading_date": [pd.Timestamp(day).tz_localize("Asia/Ho_Chi_Minh")
                         .tz_convert("UTC")],                     # 17:00 UTC hôm trước
        "close": [1700.0], "matched_volume": [700e6], "matched_value": [21_000e9],
        "deal_volume": [50e6], "deal_value": [1_500e9],
        "total_volume": [750e6], "total_value": [total_value],
    })


def test_trade_history_maps_to_local_trading_dates(vss, monkeypatch):
    asked = []
    _fake_index_market(monkeypatch, frame=_trade_history_frame(date(2026, 10, 16), 22_500e9),
                       asked=asked)

    df = vss._fetch_price_history_uncached("UPCOM")

    assert list(df["trading_date"]) == [date(2026, 10, 16)]      # không lùi 1 ngày vì UTC
    assert float(df["total_value"].iloc[0]) == 22_500e9
    assert asked[0][0] == "UPCOMINDEX"
    assert set(asked[0][1]) == {"start", "end"}


def test_source_error_returns_empty_and_logs_once(vss, monkeypatch, caplog):
    from vnstock.errors import UnsupportedError

    _fake_index_market(monkeypatch, exc=UnsupportedError(
        "Nguồn không đọc route này", code="VNSTOCK_ROUTE_UNSUPPORTED"))
    with caplog.at_level(logging.WARNING, logger="vnstock_session_stats"):
        assert vss._fetch_price_history_uncached("VNINDEX").empty
        assert vss._fetch_price_history_uncached("VNINDEX").empty
    hits = [r for r in caplog.records if "VNSTOCK_ROUTE_UNSUPPORTED" in r.getMessage()]
    assert len(hits) == 1


def test_backfill_writes_exact_gtgd_from_trade_history(vss, monkeypatch):
    day = date.today()
    while day.weekday() >= 5:
        day = date.fromordinal(day.toordinal() - 1)
    _fake_index_market(monkeypatch, frame=_trade_history_frame(day, 22_500e9))
    monkeypatch.setattr(vss, "_fetch_intraday_volume", lambda *a, **k: pd.DataFrame())

    assert vss.backfill_session_stats(days=10) == 1
    cell = vss.load_session_stats_history()[day.isoformat()]["9h-15h"]["VNINDEX"]
    assert cell["status"] == "exact"
    assert cell["gtgd"] == pytest.approx(22_500.0)                # tỷ đồng
    assert cell["gtgd_matched"] == pytest.approx(21_000.0)
    assert cell["gtgd_deal"] == pytest.approx(1_500.0)
    assert cell["vol"] == 750_000_000


def test_intraday_volume_only_asks_index_symbols(vss, monkeypatch):
    import types

    import vnstock_auth
    from vnstock.errors import NetworkError

    asked = []

    def _get(sym):
        asked.append(sym)

        def _history(**kwargs):
            raise NetworkError("Hết thời gian chờ")
        return types.SimpleNamespace(quote=types.SimpleNamespace(history=_history))

    monkeypatch.setattr(vnstock_auth, "get_vnstock", _get)
    assert vss._fetch_intraday_volume("HNX", date(2026, 10, 16)).empty
    assert vss._fetch_intraday_volume("UPCOM", date(2026, 10, 16)).empty
    assert asked == ["HNXINDEX", "UPCOMINDEX", "UPCOM"]
    assert all(vnstock_auth.is_index_symbol(s) for s in asked)
