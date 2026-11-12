"""Tests for vnstock_warehouse — symbol classification + lệnh gọi vnstock thế hệ 6."""
import re
import pytest

from tests.conftest import needs_vnstock


# _is_stock logic extracted directly to avoid importing vnstock_warehouse
# (which requires vnstock installed and does sys.exit on import failure)
_CW_PATTERN = re.compile(r"^[A-Z]{2,4}\d{5,6}$")
_FUTURES_PATTERN = re.compile(r"^[A-Z]{2,6}F\d{4}$")


def _is_stock(symbol: str) -> bool:
    """Replica of vnstock_warehouse._is_stock for testing."""
    s = symbol.upper().strip()
    if _CW_PATTERN.match(s):
        return False
    if _FUTURES_PATTERN.match(s):
        return False
    return True


class TestIsStock:

    def test_normal_stocks(self):
        for ticker in ("VCB", "FPT", "HPG", "SSI", "MBB", "ACB"):
            assert _is_stock(ticker) is True, f"{ticker} should be a stock"

    def test_three_letter_stocks(self):
        for ticker in ("VNM", "GAS", "SAB", "VIC"):
            assert _is_stock(ticker) is True

    def test_covered_warrants_rejected(self):
        for cw in ("SSI24050", "VCB23060", "HPG250612", "FPT24055"):
            assert _is_stock(cw) is False, f"{cw} should be rejected (covered warrant)"

    def test_futures_rejected(self):
        # Note: _is_stock pattern ^[A-Z]{2,6}F\d{4}$ only catches
        # pure-alpha prefix futures like VNXF2503, not VN30F2503
        # (which has digits in the prefix). This is a known limitation.
        for fut in ("VNXF2503", "VNCBF2504"):
            assert _is_stock(fut) is False, f"{fut} should be rejected (futures)"

    def test_case_insensitive(self):
        assert _is_stock("fpt") is True
        assert _is_stock("vcb") is True

    def test_whitespace_trimmed(self):
        assert _is_stock("  VCB  ") is True


# ── vnstock thế hệ 6: lệnh gọi Market/Reference + lỗi có kiểu ──────────────
# Mock lớp thế hệ 6 ngay trong module — không gọi mạng, không cần khoá nguồn.

class _Node:
    def __init__(self, outcomes, calls):
        self._outcomes, self._calls = list(outcomes), calls

    def ohlcv(self, **kwargs):
        self._calls.append(kwargs)
        out = self._outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


def _warehouse(tmp_path, monkeypatch, outcomes):
    import vnstock_warehouse as wh_mod     # sys.exit khi thiếu vnstock ⇒ test gắn @needs_vnstock
    calls, sleeps = [], []
    node = _Node(outcomes, calls)

    class _Market:
        def equity(self, symbol):
            return node

    monkeypatch.setattr(wh_mod, "Market", _Market)
    monkeypatch.setattr(wh_mod.time, "sleep", sleeps.append)
    wh = wh_mod.VnStockWarehouse(root=str(tmp_path), tier="golden")
    monkeypatch.setattr(wh, "_throttle", lambda: None)
    return wh, calls, sleeps


def _gen6_bars():
    import pandas as pd
    return pd.DataFrame({
        "time": pd.to_datetime(["2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z"]),
        "open": [119.5, 121.0], "high": [121.0, 122.5], "low": [119.0, 120.5],
        "close": [120.0, 121.5], "volume": [1_000_000, 1_200_000],
    })


@needs_vnstock
def test_fetch_price_keeps_warehouse_schema_on_gen6_bars(tmp_path, monkeypatch):
    from datetime import date

    wh, calls, _ = _warehouse(tmp_path, monkeypatch, [_gen6_bars()])
    df = wh._fetch_price("FPT", "2026-07-16", "2026-07-17")

    assert list(df.columns) == ["time", "open", "high", "low", "close",
                                "volume", "ticker", "year"]
    assert list(df["time"]) == [date(2026, 7, 16), date(2026, 7, 17)]   # ngày lịch VN
    assert [str(t) for t in df.dtypes[["open", "close", "volume"]]] == [
        "float32", "float32", "int64"]
    assert list(df["close"]) == [120.0, 121.5]                          # đơn vị nguồn giữ nguyên
    assert calls == [{"start": "2026-07-16", "end": "2026-07-17", "interval": "1D"}]


@needs_vnstock
def test_fetch_price_waits_retry_after_on_rate_limit(tmp_path, monkeypatch):
    from vnstock.errors import RateLimitError

    limited = RateLimitError("Nguồn báo vượt giới hạn tần suất (429)",
                             code="VNSTOCK_SOURCE_RATE_LIMITED", retry_after=12)
    wh, calls, sleeps = _warehouse(tmp_path, monkeypatch, [limited, _gen6_bars()])
    df = wh._fetch_price("FPT", "2026-07-16", "2026-07-17")

    assert len(df) == 2 and len(calls) == 2
    assert sleeps == [15]                                               # retry_after + 3s đệm


@needs_vnstock
def test_fetch_price_skips_non_retryable_error_without_retry(tmp_path, monkeypatch):
    from vnstock.errors import InputError

    wh, calls, sleeps = _warehouse(tmp_path, monkeypatch, [
        InputError("Chưa chọn nguồn", code="VNSTOCK_INPUT_SOURCE")])
    assert wh._fetch_price("FPT", "2026-07-16", "2026-07-17").empty
    assert len(calls) == 1 and sleeps == []


@needs_vnstock
def test_fetch_price_backs_off_on_network_error_then_gives_up(tmp_path, monkeypatch):
    from vnstock.errors import NetworkError

    wh, calls, sleeps = _warehouse(tmp_path, monkeypatch,
                                   [NetworkError("Hết thời gian chờ")] * 3)
    assert wh._fetch_price("FPT", "2026-07-16", "2026-07-17", max_retries=3).empty
    assert len(calls) == 3 and sleeps == [1, 2]                         # 2**attempt


@needs_vnstock
def test_get_all_symbols_lists_each_exchange_and_drops_warrants(tmp_path, monkeypatch):
    import pandas as pd

    wh, _, _ = _warehouse(tmp_path, monkeypatch, [])
    asked = []

    class _Equity:
        def list(self, exchange=None):
            asked.append(exchange)
            rows = {"HOSE": ["FPT", "HPG12501"], "HNX": ["SHS"]}[exchange]
            return pd.DataFrame({"symbol": rows, "exchange": ["?"] * len(rows),
                                 "organ_name": ["x"] * len(rows)})

    class _Reference:
        equity = _Equity()

    import vnstock_warehouse as wh_mod
    monkeypatch.setattr(wh_mod, "Reference", _Reference)
    df = wh.get_all_symbols(["HOSE", "HNX"])

    assert asked == ["HOSE", "HNX"]
    assert sorted(df["symbol"]) == ["FPT", "SHS"]
    assert dict(zip(df["symbol"], df["exchange"])) == {"FPT": "HOSE", "SHS": "HNX"}
