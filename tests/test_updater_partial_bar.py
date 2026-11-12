"""Tests for the partial-intraday-bar self-heal in vnstock_updater.update_ticker.

Bug (2026-06-11): an updater run DURING the session stores VCI's in-progress
daily bar (partial volume). The old `fetch_from = last_date + 1` then returned
"up_to_date" for the rest of the day and only fetched LATER dates on subsequent
days — freezing the partial bar forever. Observed: 379 tickers carried partial
10/06 bars summing to 6,157 tỷ ≈ 57% of the real day (the morning share).

Fix: refetch from `last_date` INCLUSIVE; the year-merge dedups keep="last" so
the refetched final bar replaces the stale partial one.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# vnstock_updater hard-requires the vnstock package at import time; skip the
# module cleanly on environments without it (CI/sandbox) — it runs in full on
# the dev machine where vnstock is installed.
vu = pytest.importorskip("vnstock_updater")


def _seed(prices_dir: Path, ticker: str, rows: list[dict]) -> Path:
    tdir = prices_dir / f"ticker={ticker}"
    for year in {pd.to_datetime(r["time"]).year for r in rows}:
        ydf = pd.DataFrame([r for r in rows
                            if pd.to_datetime(r["time"]).year == year])
        ydir = tdir / f"year={year}"
        ydir.mkdir(parents=True, exist_ok=True)
        ydf.to_parquet(ydir / "prices.parquet", index=False)
    return tdir


def _bar(d: str, close: float, vol: float) -> dict:
    return {"time": pd.Timestamp(d), "open": close, "high": close,
            "low": close, "close": close, "volume": vol}


def test_partial_today_bar_is_refetched_and_replaced(tmp_path, monkeypatch):
    today = date(2026, 6, 10)
    prices = tmp_path / "prices"
    _seed(prices, "AAA", [_bar("2026-06-09", 10.0, 500_000),
                          _bar("2026-06-10", 10.2, 300_000)])  # partial intraday bar

    fetched = {}

    def fake_fetch(ticker, start, end):
        fetched["start"] = start
        return pd.DataFrame([{"time": date(2026, 6, 10), "open": 10.2,
                              "high": 10.4, "low": 10.1, "close": 10.3,
                              "volume": 900_000.0}])           # final EOD bar

    monkeypatch.setattr(vu, "_fetch_prices", fake_fetch)
    res = vu.update_ticker("AAA", prices, today)
    # Old behavior: "up_to_date" (fetch_from = 11/06 > today) → frozen partial.
    assert res["status"] == "updated"
    # Bất biến là "fetch BAO GỒM bar cuối" chứ không phải "start đúng bằng bar
    # cuối": từ 19/08 basis guard nới cửa sổ lùi thêm để có vùng chồng lấn mà
    # đối chiếu cơ sở (superset — bar dở vẫn được lành). Canh literal là canh
    # chi tiết cài đặt, không phải canh bất biến.
    assert fetched["start"] <= "2026-06-10"       # inclusive refetch of last bar

    out = pd.read_parquet(prices / "ticker=AAA/year=2026/prices.parquet")
    out["time"] = pd.to_datetime(out["time"]).dt.date
    row = out[out["time"] == date(2026, 6, 10)]
    assert len(row) == 1                          # dedup: one bar per day
    assert float(row["volume"].iloc[0]) == 900_000.0   # partial replaced by final


def test_next_day_run_heals_yesterdays_partial(tmp_path, monkeypatch):
    # Run on 11/06 with a partial 10/06 bar: must fetch FROM 10/06 (inclusive),
    # not 11/06, so yesterday's frozen partial gets replaced too.
    today = date(2026, 6, 11)
    prices = tmp_path / "prices"
    _seed(prices, "BBB", [_bar("2026-06-10", 20.0, 100_000)])  # stale partial

    def fake_fetch(ticker, start, end):
        assert start <= "2026-06-10"              # heals the last stored day
        return pd.DataFrame([
            {"time": date(2026, 6, 10), "open": 20, "high": 21, "low": 19.8,
             "close": 20.5, "volume": 800_000.0},
            {"time": date(2026, 6, 11), "open": 20.5, "high": 20.8, "low": 20.2,
             "close": 20.6, "volume": 600_000.0},
        ])

    monkeypatch.setattr(vu, "_fetch_prices", fake_fetch)
    res = vu.update_ticker("BBB", prices, today)
    assert res["status"] == "updated"
    assert res["new_days"] == 1                   # only 11/06 is genuinely new

    out = pd.read_parquet(prices / "ticker=BBB/year=2026/prices.parquet")
    out["time"] = pd.to_datetime(out["time"]).dt.date
    assert float(out[out["time"] == date(2026, 6, 10)]["volume"].iloc[0]) == 800_000.0
    assert len(out) == 2


def test_future_dated_bar_still_short_circuits(tmp_path, monkeypatch):
    # Clock-skew/garbage future bar → "up_to_date", no fetch (guard retained).
    today = date(2026, 6, 10)
    prices = tmp_path / "prices"
    _seed(prices, "CCC", [_bar("2026-06-12", 5.0, 1_000)])

    def boom(*a, **k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(vu, "_fetch_prices", boom)
    assert vu.update_ticker("CCC", prices, today)["status"] == "up_to_date"


def test_skip_stale_days_skips_dead_ticker_without_fetching(tmp_path, monkeypatch):
    # A long-dead/delisted ticker (last bar years ago) was re-fetching years of
    # data every run for 0 new days — the main time sink. skip_stale_days short-
    # circuits it BEFORE any API call.
    today = date(2026, 6, 16)
    prices = tmp_path / "prices"
    _seed(prices, "DEADX", [_bar("2019-05-01", 10.0, 1_000)])

    def boom(*a, **k):
        raise AssertionError("must not fetch a stale ticker")

    monkeypatch.setattr(vu, "_fetch_prices", boom)
    assert vu.update_ticker("DEADX", prices, today,
                            skip_stale_days=90)["status"] == "stale_skip"

    # default (0) → feature off → NOT stale-skipped (fetch attempted, stubbed empty).
    monkeypatch.setattr(vu, "_fetch_prices", lambda *a, **k: pd.DataFrame())
    assert vu.update_ticker("DEADX", prices, today,
                            skip_stale_days=0)["status"] != "stale_skip"


# ── vnstock thế hệ 6: lệnh gọi đi qua Market (mặt tiền), lỗi có kiểu ────────

class _FakeNode:
    def __init__(self, frame=None, exc=None, calls=None):
        self._frame, self._exc, self._calls = frame, exc, calls

    def ohlcv(self, **kwargs):
        if self._calls is not None:
            self._calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._frame


def _fake_market(monkeypatch, frame=None, exc=None, calls=None):
    import vnstock

    node = _FakeNode(frame, exc, calls)

    class _Market:
        def equity(self, symbol):
            return node

        def index(self, symbol):
            raise AssertionError("cổ phiếu không được đi nhánh chỉ số")

    monkeypatch.setattr(vnstock, "Market", _Market)


def test_gen6_fetch_maps_tz_aware_bars_to_warehouse_dates(monkeypatch):
    # Thế hệ 6 trả `time` CÓ múi giờ (bar ngày lúc 07:00 giờ VN = 00:00 UTC).
    # Kho lưu ngày lịch VN: phải ra đúng ngày, giá giữ nguyên đơn vị nguồn.
    calls = []
    frame = pd.DataFrame({
        "time": pd.to_datetime(["2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z"]),
        "open": [119.5, 121.0], "high": [121.0, 122.5], "low": [119.0, 120.5],
        "close": [120.0, 121.5], "volume": [1_000_000, 1_200_000],
    })
    _fake_market(monkeypatch, frame=frame, calls=calls)

    out = vu._fetch_prices("FPT", "2026-07-16", "2026-07-17")

    assert list(out.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert list(out["time"]) == [date(2026, 7, 16), date(2026, 7, 17)]
    assert list(out["close"]) == [120.0, 121.5]
    # nguồn chọn ở luật VNSTOCK_SOURCE — lệnh gọi không mang tên nguồn
    assert calls == [{"start": "2026-07-16", "end": "2026-07-17", "interval": "1D"}]


def test_gen6_typed_network_error_is_raised_not_swallowed(monkeypatch):
    # Bài 17/07: nuốt lỗi → df rỗng → "no_new_data" giả. Lỗi thế hệ 6 phải bay ra.
    from vnstock.errors import NetworkError

    _fake_market(monkeypatch, exc=NetworkError("Hết thời gian chờ",
                                               code="VNSTOCK_SOURCE_NETWORK"))
    with pytest.raises(NetworkError):
        vu._fetch_prices("FPT", "2026-07-10", "2026-07-17")

    # Nguồn trả rỗng THẬT (mã hủy niêm yết) → df rỗng, không raise
    _fake_market(monkeypatch, frame=pd.DataFrame())
    assert vu._fetch_prices("XXX", "2026-07-10", "2026-07-17").empty


def test_gen6_source_error_marks_one_ticker_and_leaves_warehouse(tmp_path, monkeypatch):
    from vnstock.errors import SourceError

    prices = tmp_path / "prices"
    tdir = _seed(prices, "FPT", [_bar("2026-07-15", 119.5, 1e6),
                                 _bar("2026-07-16", 120.0, 1e6)])
    before = (tdir / "year=2026" / "prices.parquet").read_bytes()
    _fake_market(monkeypatch, exc=SourceError("Nguồn lỗi",
                                              code="VNSTOCK_SOURCE_UNAVAILABLE"))

    res = vu.update_ticker("FPT", prices, date(2026, 7, 17))

    assert res["status"] == "error" and "Nguồn lỗi" in res["error"]
    assert (tdir / "year=2026" / "prices.parquet").read_bytes() == before


def test_gen6_source_in_raw_dong_is_quarantined_by_basis_guard(tmp_path, monkeypatch):
    # Kho lưu giá NGHÌN đồng. Nguồn trả ĐỒNG (×1000) — chưa đối chiếu được khi
    # không có khoá nguồn — thì cửa V1 phải chặn, không nối chuỗi lệch đơn vị.
    import vnstock_basis_guard as bg

    prices = tmp_path / "prices"
    days = list(pd.bdate_range(end="2026-07-16", periods=12).date)
    tdir = _seed(prices, "VTP", [_bar(str(d), 100.0 + i, 1e6)
                                 for i, d in enumerate(days)])
    before = (tdir / "year=2026" / "prices.parquet").read_bytes()
    src_days = days + [date(2026, 7, 17)]
    px = [(100.0 + i) * 1000 for i in range(len(src_days))]
    _fake_market(monkeypatch, frame=pd.DataFrame({
        "time": pd.to_datetime(src_days), "open": px, "high": px, "low": px,
        "close": px, "volume": [1_000_000] * len(src_days)}))

    res = vu.update_ticker("VTP", prices, date(2026, 7, 17))

    assert res["status"] == "basis_drift"
    assert res["ratio"] == pytest.approx(0.001)            # kho / nguồn
    assert (tdir / "year=2026" / "prices.parquet").read_bytes() == before
    assert "VTP" in bg.load_pending(tmp_path)
