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


# ── Thế hệ 6: bảng giá / HĐTL / chỉ số / danh sách mã (mock, không mạng) ──────

def _svc_capturing_ticks(monkeypatch):
    """VnStockWSS không chạy luồng; `_handle_tick` chỉ GOM tick để soi."""
    import vnstock_wss as w
    svc = w.VnStockWSS.__new__(w.VnStockWSS)
    svc.last_error = None
    svc._last_accum_vol, svc._last_accum_date = {}, {}
    ticks: list = []
    monkeypatch.setattr(w.VnStockWSS, "_handle_tick", lambda self, t: ticks.append(t))
    return svc, ticks


def _board_row(symbol, close, ref, total_volume, **extra):
    """Một dòng `Market().equity.quote` hồ sơ v5 (giá ĐỒNG), đủ cột dễ nhầm với volume."""
    return {
        "symbol": symbol, "exchange": "HOSE", "reference_price": ref,
        "ceiling_price": ref * 1.07, "floor_price": ref * 0.93, "open_price": ref,
        "high_price": close + 200, "low_price": close - 300, "close_price": close,
        "bid_price_1": close - 100, "bid_vol_1": 1500, "bid_price_2": close - 200,
        "bid_vol_2": 800, "bid_price_3": None, "bid_vol_3": None,
        "ask_price_1": close + 100, "ask_vol_1": 700, "ask_price_2": None,
        "ask_vol_2": None, "ask_price_3": None, "ask_vol_3": None,
        "foreign_buy_volume": 999_999, "foreign_sell_volume": 888_888,
        "time": "2026-11-11 10:15:00", "total_volume": total_volume,
        "total_value": 1e12, "last_volume": 77_000, **extra,
    }


class _FakeNode:
    def __init__(self, df=None, exc=None):
        self.df, self.exc, self.calls = df, exc, []

    def _ret(self, name, *a, **k):
        self.calls.append((name, a, k))
        if self.exc is not None:
            raise self.exc
        return self.df

    def quote(self, *a, **k):
        return self._ret("quote", *a, **k)


class _FakeMarket:
    """`Market()` giả: `.equity.quote(symbols)` · `.futures(s).quote()` · `.index(s).quote()`."""
    board = futures = index = None

    def __init__(self, *a, **k):
        cls = type(self)
        self.equity = cls.board
        self.futures = lambda s: cls.futures
        self.index = lambda s: cls.index


def _patch_market(monkeypatch, **nodes):
    import vnstock
    fake = type("_M", (_FakeMarket,), nodes)
    monkeypatch.setattr(vnstock, "Market", fake)
    return fake


def test_price_board_reads_gen6_quote_columns(monkeypatch):
    """Bảng giá thế hệ 6: giá = close_price, KL phiên = total_volume — KHÔNG phải
    `foreign_buy_volume`/`last_volume` (dò chuỗi con "volume"/"last" cũ trúng chúng)."""
    pytest.importorskip("vnstock")
    board = _FakeNode(pd.DataFrame([_board_row("FPT", 77_700, 76_000, 1_234_500)]))
    _patch_market(monkeypatch, board=board)
    svc, ticks = _svc_capturing_ticks(monkeypatch)

    assert svc._fetch_batch_price_board(["FPT"]) is True
    assert board.calls == [("quote", (["FPT"],), {})]
    (t,) = ticks
    assert t["ticker"] == "FPT" and t["type"] == "stock"
    assert t["price"] == 77_700 and t["volume"] == 1_234_500
    assert t["high"] == 77_900 and t["low"] == 77_400
    assert t["chg_pct"] == round((77_700 - 76_000) / 76_000 * 100, 2)
    assert t["bids"] == [{"price": 77_600, "volume": 1500}, {"price": 77_500, "volume": 800}]
    assert t["asks"] == [{"price": 77_800, "volume": 700}]
    assert t["bid"] == 77_600 and t["ask"] == 77_800


def test_price_board_vnstock_error_is_recorded_not_raised(monkeypatch):
    """Chưa chọn nguồn (InputError VNSTOCK_INPUT_SOURCE) ⇒ False + last_error, không ném."""
    pytest.importorskip("vnstock")
    from vnstock.errors import InputError
    _patch_market(monkeypatch, board=_FakeNode(exc=InputError("Chưa chọn nguồn")))
    svc, ticks = _svc_capturing_ticks(monkeypatch)
    assert svc._fetch_batch_price_board(["FPT"]) is False
    assert ticks == [] and "Chưa chọn nguồn" in svc.last_error


def test_futures_quote_keeps_friendly_name_and_depth(monkeypatch):
    """HĐTL: `Market().futures(s).quote()`; nguồn trả mã nội bộ 41I… nhưng file quote
    phải mang tên đã đăng ký (VN30F1M) để dashboard tìm thấy."""
    pytest.importorskip("vnstock")
    row = _board_row("41I1G4000", 1_850.5, 1_840.0, 210_000)
    _patch_market(monkeypatch, futures=_FakeNode(pd.DataFrame([row])))
    svc, ticks = _svc_capturing_ticks(monkeypatch)

    assert svc._fetch_futures_quote("VN30F1M") is True
    (t,) = ticks
    assert t["ticker"] == "VN30F1M" and t["type"] == "futures"
    assert t["price"] == 1_850.5 and t["volume"] == 210_000
    assert t["bids"][0] == {"price": 1_750.5, "volume": 1500}


def test_index_quote_reads_gen6_columns(monkeypatch):
    pytest.importorskip("vnstock")
    df = pd.DataFrame([{
        "symbol": "VNINDEX", "reference_price": 1_250.0, "high_price": 1_270.0,
        "low_price": 1_245.0, "close_price": 1_262.5, "total_volume": 650_000_000,
        "time": "2026-11-11 10:15:00", "price_change": 12.5, "percent_change": 0.01,
        "advances": 200, "declines": 150, "accumulated_volume": 1, "put_through_volume": 2,
    }])
    _patch_market(monkeypatch, index=_FakeNode(df))
    svc, ticks = _svc_capturing_ticks(monkeypatch)

    svc._fetch_index_quote("VNINDEX")
    (t,) = ticks
    assert t["ticker"] == "VNINDEX" and t["type"] == "index"
    assert t["price"] == 1_262.5 and t["volume"] == 650_000_000
    assert t["high"] == 1_270.0 and t["low"] == 1_245.0
    assert t["chg_pct"] == pytest.approx(1.0)        # từ reference_price, không đoán đơn vị %


def test_listed_symbols_from_reference_equity_list(monkeypatch):
    pytest.importorskip("vnstock")
    import vnstock

    import vnstock_wss as w
    asked = []

    class _Eq:
        def list(self, exchange=None):
            asked.append(exchange)
            return pd.DataFrame({"symbol": {"HOSE": ["fpt", "VCB"], "HNX": ["SHS"],
                                            "UPCOM": ["BSR", "VN30F2412"]}[exchange],
                                 "exchange": exchange})

    monkeypatch.setattr(vnstock, "Reference", lambda *a, **k: type("_R", (), {"equity": _Eq()})())
    monkeypatch.setattr(w, "_ALL_LISTED_CACHE", [])
    monkeypatch.setattr(w, "_ALL_LISTED_DATE", "")
    assert w.get_all_listed_symbols() == ["BSR", "FPT", "SHS", "VCB"]
    assert asked == ["HOSE", "HNX", "UPCOM"]


def test_index_quote_last_row_takes_latest_time_and_session_volume():
    """Thế hệ 6: `index(s).quote()` trả CẢ chuỗi trong ngày (đo 🖥️ 12/11: 4.144 dòng). Lấy dòng MỚI NHẤT
    theo `time` dù nguồn xếp ngược; khối lượng = `accumulated_volume`; cột *_volume khác không lọt."""
    import pandas as pd

    import vnstock_wss as w
    df = pd.DataFrame({
        "symbol": ["VNINDEX"] * 3,
        "time": ["2026-11-12 14:45:00", "2026-11-12 09:15:00", "2026-11-12 11:30:00"],
        "reference_price": [1740.0] * 3,
        "close_price": [1734.75, 1745.0, 1738.0], "high_price": [1750.0, 1745.0, 1748.0],
        "low_price": [1730.0, 1744.0, 1736.0], "total_volume": [1.0e6, 2.0e5, 5.0e5],
        "put_through_volume": [9.9e9] * 3, "advance_volume": [8.8e9] * 3,
        "accumulated_volume": [6.5e8, 2.0e7, 3.1e8],
    })
    row = w._index_quote_last_row(df)
    assert row["close"] == 1734.75 and row["volume"] == 6.5e8 and row["reference_price"] == 1740.0
    assert set(row.index) == {"close", "high", "low", "volume", "reference_price"}
    no_acc = w._index_quote_last_row(df.drop(columns=["accumulated_volume"]))
    assert no_acc["volume"] == 1.0e6                       # không có luỹ kế ⇒ total_volume
