"""Smoke tests for dashboard.screener_tab.

The UI and dashboard-level helpers (df_from_preset, render_table etc.)
are covered by their own tests in test_screener.py and test_dashboard.py.
This file only validates the tab module's import contract and signature.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest


def test_module_imports_without_streamlit():
    """Module must be importable with just stdlib — Streamlit + dashboard
    helpers are lazy-imported inside render_screener_tab."""
    import importlib
    mod = importlib.import_module("dashboard.screener_tab")
    assert hasattr(mod, "render_screener_tab")
    assert callable(mod.render_screener_tab)


def test_render_signature_keyword_only():
    """All state parameters are keyword-only so callers can't pass
    positionally by accident — the dispatch block in vnstock_dashboard.py
    relies on this contract."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    for name, param in sig.parameters.items():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, \
            f"parameter {name!r} must be keyword-only"


def test_render_accepts_expected_params():
    """The wrapper in vnstock_dashboard.py passes exactly these names —
    this test locks the contract so a rename breaks loudly here."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    expected = {
        "presets_data", "industry_summary", "gen_time",
        "total_tickers", "classified", "total_hits", "top_preset", "stale_excluded",
    }
    assert set(sig.parameters.keys()) == expected


# ── Watchlist: file hỏng không bị ghi đè (state user, Dropbox đẩy sang máy kia) ──

def _watchlist_sidebar(path, click: str, typed: str = "VCB", snapshot=None):
    """`snapshot` = thứ `load_watchlist()` (cache 10 phút của dashboard) trả về; None ⇒
    đọc thẳng file như khi cache vừa hết hạn."""
    from unittest.mock import MagicMock

    from dashboard.screener_tab import _render_watchlist_sidebar
    from dashboard.watchlist_io import load_watchlist, save_watchlist
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.text_input = lambda *a, **k: typed
    st.button = lambda label, key=None, **k: key == click and not k.get("disabled")
    st.rerun = MagicMock()
    load = (lambda: list(snapshot)) if snapshot is not None else (lambda: load_watchlist(path))
    out = _render_watchlist_sidebar(st, load, lambda t: save_watchlist(path, t), path)
    return st, out


def test_corrupt_watchlist_blocks_add_and_delete(tmp_path):
    path = tmp_path / "watchlist.json"
    truncated = b'{"tickers": ["FPT", "HPG", "SS'
    path.write_bytes(truncated)
    for click in ("wl_add_btn", "wl_del_btn"):
        st, (tickers, _) = _watchlist_sidebar(path, click)
        assert path.read_bytes() == truncated                 # không ghi đè bằng [] + VCB
        assert [p.name for p in tmp_path.iterdir()] == ["watchlist.json"]
        assert str(path) in st.error.call_args.args[0]
        assert tickers == [] and not st.rerun.called



@pytest.mark.parametrize("payload", [b"null", b'["FPT", "HPG"]', b'{"tickers": "FPT"}'])
def test_wrong_shape_watchlist_blocks_add_and_delete(tmp_path, payload):
    """JSON hợp lệ nhưng sai dạng: từng sập tab (AttributeError lọt qua
    `except (OSError, ValueError)`) hoặc ghép chuỗi "FPT" với mã mới."""
    path = tmp_path / "watchlist.json"
    path.write_bytes(payload)
    for click in ("wl_add_btn", "wl_del_btn"):
        st, (tickers, _) = _watchlist_sidebar(path, click)
        assert path.read_bytes() == payload
        assert str(path) in st.error.call_args.args[0]
        assert tickers == [] and not st.rerun.called

def test_missing_watchlist_is_empty_and_add_writes(tmp_path):
    path = tmp_path / "watchlist.json"
    st, (tickers, _) = _watchlist_sidebar(path, "wl_add_btn")
    assert tickers == [] and not st.error.called
    assert json.loads(path.read_text(encoding="utf-8"))["tickers"] == ["VCB"]
    assert st.rerun.called


def test_watchlist_save_failure_is_reported(tmp_path, monkeypatch):
    import os

    import vnstock_parquet_io as pio
    path = tmp_path / "watchlist.json"
    path.write_text('{"tickers": ["FPT"]}', encoding="utf-8")

    def _fail(_a, _b):
        raise OSError("file đang bị khoá")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(os, "replace", _fail)
    st, _ = _watchlist_sidebar(path, "wl_add_btn")
    monkeypatch.undo()
    msg = st.error.call_args.args[0]
    assert str(path) in msg and "file đang bị khoá" in msg and not st.rerun.called
    assert json.loads(path.read_text(encoding="utf-8"))["tickers"] == ["FPT"]


@pytest.mark.parametrize("click, typed, expected", [("wl_add_btn", "CCC", ["AAA", "BBB", "CCC"]),
                                                    ("wl_del_btn", "AAA", ["BBB"])])
def test_watchlist_buttons_reread_file_not_cached_snapshot(tmp_path, click, typed, expected):
    """Cache 10 phút còn [AAA] trong khi máy kia (Dropbox) đã ghi [AAA, BBB]: Thêm/Xoá
    phải đọc LẠI file, không ghi từ bản chụp rồi đè mất BBB."""
    from dashboard.watchlist_io import load_watchlist, save_watchlist
    path = tmp_path / "watchlist.json"
    save_watchlist(path, ["AAA", "BBB"])

    st, _ = _watchlist_sidebar(path, click, typed=typed, snapshot=["AAA"])

    assert load_watchlist(path) == expected
    assert st.rerun.called and not st.error.called


@pytest.mark.parametrize("click", ["wl_add_btn", "wl_del_btn"])
def test_watchlist_reread_failure_writes_nothing(tmp_path, click):
    """Bản chụp còn tốt nhưng lúc bấm file trên đĩa đã hỏng (Dropbox đang ghi dở) ⇒ báo lỗi
    kèm đường dẫn, không ghi đè file."""
    path = tmp_path / "watchlist.json"
    truncated = b'{"tickers": ["AAA", "BB'
    path.write_bytes(truncated)

    st, _ = _watchlist_sidebar(path, click, typed="AAA", snapshot=["AAA"])

    assert path.read_bytes() == truncated
    assert str(path) in st.error.call_args.args[0] and not st.rerun.called


# ── Thống kê phiên: fragment chạy mỗi 30s ở tab mặc định ⇒ không tải lại EOD / ghi lại file ──

def _count_eod_fetches(monkeypatch, frames):
    """Thay vnstock Trading bằng bản giả đếm lượt gọi price_history (lượt mạng thật)."""
    import types

    import pandas as pd

    import vnstock_session_stats as ss
    calls = []

    class _Trading:
        def __init__(self, symbol, source):
            self.symbol = symbol

        def price_history(self, **kw):
            calls.append(self.symbol)
            return frames(self.symbol)

    monkeypatch.setitem(sys.modules, "vnstock.api.trading", types.SimpleNamespace(Trading=_Trading))
    for sponsor in ("vnstock_data", "vnii"):                 # nhánh dự phòng cũng không ra mạng
        monkeypatch.setitem(sys.modules, sponsor, None)
    bars = pd.DataFrame({"time": pd.to_datetime([f"{date.today()} 09:15"]), "volume": [1_000_000]})
    monkeypatch.setattr(ss, "_fetch_intraday_volume", lambda *a, **k: bars)
    monkeypatch.setattr(ss, "_PRICE_HISTORY_CACHE", {}, raising=False)
    return ss, calls


def _eod_frame(_symbol):
    import pandas as pd
    return pd.DataFrame({"trading_date": [date.today().isoformat()],
                         "total_value": [2.0e13], "total_volume": [8.0e8]})


def test_compute_session_stats_fetches_eod_history_once_per_day(monkeypatch):
    ss, calls = _count_eod_fetches(monkeypatch, _eod_frame)
    first = ss.compute_session_stats()
    second = ss.compute_session_stats()
    assert second == first                                    # kết quả số không đổi
    assert first["9h-10h"]["VNINDEX"] == {"vol": 1_000_000, "gtgd": 25.0, "gtgd_per_vol": 25_000,
                                          "status": "estimate"}   # calibration từ EOD giả
    assert sorted(calls) == sorted(ss._PRICE_HISTORY_SYMBOL.values())   # 4 lượt, không phải 8

    class _Tomorrow(date):
        @classmethod
        def today(cls):
            return cls.fromordinal(date.today().toordinal() + 1)

    monkeypatch.setattr(ss, "date", _Tomorrow)
    ss.compute_session_stats()
    assert len(calls) == 8                                    # sang ngày mới thì tải lại
    monkeypatch.setattr(ss, "_PRICE_HISTORY_TTL_S", 0)
    ss.compute_session_stats()
    assert len(calls) == 12                                   # hết TTL (EOD đăng giữa ngày) ⇒ tải lại


def test_eod_history_failure_is_not_cached(monkeypatch):
    import pandas as pd
    ss, calls = _count_eod_fetches(monkeypatch, lambda s: pd.DataFrame())
    ss.compute_session_stats()
    n = len(calls)
    ss.compute_session_stats()
    assert n > 0 and len(calls) == 2 * n                      # lỗi mạng ⇒ lượt sau thử lại


def test_save_session_stats_skips_identical_content(tmp_path, monkeypatch):
    import vnstock_parquet_io as pio
    import vnstock_session_stats as ss
    monkeypatch.setattr(ss, "SESSION_STATS_PATH", tmp_path / "market_session_stats.json")
    writes = []
    real = pio.write_json_atomic
    monkeypatch.setattr(pio, "write_json_atomic",
                        lambda payload, path, **k: writes.append(path) or real(payload, path, **k))
    stats = {"9h-10h": {"VNINDEX": {"vol": 123, "gtgd": 3.7, "gtgd_per_vol": 30000.0,
                                    "status": "estimate"}}}
    ss.save_session_stats(stats)
    ss.save_session_stats(json.loads(json.dumps(stats)))      # cùng nội dung ⇒ không ghi lại
    assert len(writes) == 1
    changed = {"9h-10h": {"VNINDEX": {**stats["9h-10h"]["VNINDEX"], "vol": 456}}}
    ss.save_session_stats(changed)
    assert len(writes) == 2
    assert ss.load_session_stats_history()[date.today().isoformat()] == changed


# ── Live Scan: nối bar hôm nay, đơn vị giá, chỉ báo khớp EOD, ghi nhớ kết quả ──

TODAY = date(2026, 10, 16)
T0, S = 10**18, 10**9          # mtime_ns cố định; bước 1s (NTFS 100ns, st_mtime float)


def _bars(n=120, end="2026-10-15", start=20.0):
    """Chuỗi tăng LUỸ THỪA (close cuối ~65) ⇒ MACD hist dương ở bar cuối, dựng được ca SELL."""
    close = start * 1.01 ** np.arange(n)
    return pd.DataFrame({"time": pd.bdate_range(end=end, periods=n), "open": close * 0.995,
                         "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": 1_000_000.0 + 1_000 * np.arange(n)})


def _at(local: str) -> float:
    """Giờ local naive → epoch giây (như `st_mtime`) — không phụ thuộc đồng hồ thật."""
    return datetime.fromisoformat(local).timestamp()


def _put_hist(prices_dir, ticker, df, written=None):
    """`written` (epoch giây) = lúc kho ghi file parquet (mtime)."""
    for year, part in df.groupby(df["time"].dt.year):
        d = prices_dir / f"ticker={ticker}" / f"year={year}"
        d.mkdir(parents=True, exist_ok=True)
        part.to_parquet(d / "prices.parquet", index=False)
        if written is not None:
            os.utime(d / "prices.parquet", (written, written))


def _put_quote(quote_dir, ticker, price, time="2026-10-16T14:20:52", volume=2_000_000.0,
               high=None, low=None, mtime_ns=None):
    quote_dir.mkdir(parents=True, exist_ok=True)
    path = quote_dir / f"quote_{ticker}.json"
    q = {"ticker": ticker, "time": time, "price": price, "volume": volume, "type": "stock"}
    if high is not None:
        q.update(high=high, low=low)
    path.write_text(json.dumps(q), encoding="utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _scan_all(tmp_path, monkeypatch, state=None, today=TODAY, budget_s=float("inf")):
    """Quét qua preset `_all` (lọt mọi row) ⇒ (scanned, mã → row, pending, lỗi): thấy row từng
    mã mà không soi ruột cache. Ngân sách mặc định vô hạn ⇒ test khác không phụ thuộc tốc độ máy."""
    import vnstock_screener
    from dashboard.screener_tab import _scan_live_quotes
    monkeypatch.setitem(vnstock_screener.PRESETS, "_all", {"filter": lambda r: True})
    state = {} if state is None else state
    scanned, hits, pending, errors = _scan_live_quotes(
        tmp_path / "_live", tmp_path / "prices", state, today, lambda t: True, budget_s=budget_s)
    return scanned, {r["ticker"]: r for r in hits["_all"]}, pending, errors


def _scan(tmp_path, monkeypatch, state=None, today=TODAY):
    return _scan_all(tmp_path, monkeypatch, state, today)[:2]


def _today_bar(hist, close, high, low, volume=2e6):
    return pd.DataFrame([{"time": pd.Timestamp("2026-10-16"), "open": hist["close"].iloc[-1],
                          "high": high, "low": low, "close": close, "volume": volume}])


def test_live_frame_appends_today_and_keeps_yesterday_bar():
    """Lỗi 1: kho tới D-1 mà code cũ GHI ĐÈ close bar D-1 ⇒ chg_20d trên 21 phiên."""
    from dashboard.screener_tab import _live_frame
    hist = _bars()
    before = hist.copy()
    frame = _live_frame(hist, {"time": "2026-10-16T14:20:52", "price": 61_000.0,
                               "volume": 2e6, "high": 62_000.0, "low": 60_000.0}, TODAY, None)
    assert len(frame) == len(hist) + 1
    assert frame.iloc[:-1].equals(hist)                       # bar D-1 nguyên vẹn
    assert hist.equals(before)                                # không sửa bản đang nằm trong cache
    assert frame.iloc[-1].to_dict() == _today_bar(hist, 61.0, 62.0, 60.0).iloc[0].to_dict()


def test_live_frame_same_day_replaces_last_bar_only_if_quote_is_newer():
    """Bar ngày D của kho có thể là EOD (18:00) hoặc dở dang (chạy bù sáng) — chỉ đè khi quote
    chụp SAU lúc ghi kho; không biết lúc ghi ⇒ không chứng minh được ⇒ bỏ."""
    from dashboard.screener_tab import _live_frame
    hist = _bars(end="2026-10-16")
    bar = hist.iloc[-1]
    quote = {"time": "2026-10-16T14:20:52", "price": 66_000.0,
             "volume": 0.0, "high": 66_500.0, "low": 50_000.0}
    for written_at in (_at("2026-10-16T18:30"), _at("2026-10-16T14:20:52"), None):
        assert _live_frame(hist, quote, TODAY, written_at) is None
    frame = _live_frame(hist, quote, TODAY, _at("2026-10-16T10:20"))
    last = frame.iloc[-1]
    assert len(frame) == len(hist) and frame.iloc[:-1].equals(hist.iloc[:-1])
    assert (last["time"], last["open"], last["close"]) == (bar["time"], bar["open"], 66.0)
    assert (last["high"], last["low"]) == (max(bar["high"], 66.5), 50.0)
    assert last["volume"] == bar["volume"]                    # live vol 0 ⇒ giữ vol của kho


def test_live_frame_drops_stale_or_broken_quote():
    """Quote tồn từ phiên trước (file 08/2026 vẫn nằm trong _live) ⇒ bỏ mã."""
    from dashboard.screener_tab import _live_frame
    hist = _bars()
    assert _live_frame(hist, {"time": "2026-08-18T14:20:52", "price": 68_700.0}, TODAY, None) is None
    assert _live_frame(hist, {"time": "hỏng", "price": 68_700.0}, TODAY, None) is None
    assert _live_frame(hist, {"price": 68_700.0}, TODAY, None) is None
    assert _live_frame(hist, {"time": "2026-10-16T10:00:00", "price": 0}, TODAY, None) is None


def test_live_frame_converts_tz_aware_quote_to_vietnam_day():
    from dashboard.screener_tab import _live_frame
    hist = _bars()
    frame = _live_frame(hist, {"time": "2026-10-15T17:30:00+00:00", "price": 61_000.0}, TODAY,
                        None)
    assert frame["time"].iloc[-1] == pd.Timestamp("2026-10-16")      # 00:30 giờ VN


def test_scan_chg_20d_counts_from_today(tmp_path, monkeypatch):
    hist = _bars()
    for t in ("AAA", "OLD"):
        _put_hist(tmp_path / "prices", t, hist)
    _put_quote(tmp_path / "_live", "AAA", 61_000.0)
    _put_quote(tmp_path / "_live", "OLD", 68_700.0, time="2026-08-18T14:20:52")
    scanned, rows = _scan(tmp_path, monkeypatch)
    assert rows["AAA"]["chg_20d_pct"] == round((61.0 / hist["close"].iloc[-20] - 1) * 100, 2)
    assert scanned == 1 and "OLD" not in rows


@pytest.mark.parametrize("hist_close, quote_price, expected", [
    (0.3, 300.0, 0.3),          # mã 300 đ: ngưỡng cứng >500 cũ giữ 300 (= 300 nghìn)
    (77.7, 77_700.0, 77.7),
    (77.7, 77.8, 77.8),
])
def test_live_price_unit_follows_warehouse(hist_close, quote_price, expected):
    """Lỗi 2: đơn vị giá live suy từ close cuối của kho, không từ ngưỡng 500."""
    from dashboard.screener_tab import _live_frame
    hist = _bars().assign(open=hist_close, high=hist_close, low=hist_close, close=hist_close)
    frame = _live_frame(hist, {"time": "2026-10-16T10:00:00", "price": quote_price,
                               "high": quote_price, "low": quote_price}, TODAY, None)
    last = frame.iloc[-1]
    assert (last["close"], last["high"], last["low"]) == pytest.approx((expected,) * 3)


def test_scan_row_matches_eod_indicators(tmp_path, monkeypatch):
    """Lỗi 3: row live = `_calc_indicators` của khung đã nối (crsi, ha_streak… có mặt)."""
    from vnstock_screener import _calc_indicators
    hist = _bars()
    _put_hist(tmp_path / "prices", "AAA", hist)
    _put_quote(tmp_path / "_live", "AAA", 61_000.0, high=62_000.0, low=60_000.0)
    _, rows = _scan(tmp_path, monkeypatch)
    expected = _calc_indicators(pd.concat([hist, _today_bar(hist, 61.0, 62.0, 60.0)],
                                          ignore_index=True))
    assert rows["AAA"] == {**expected, "ticker": "AAA"}
    assert {"crsi", "ha_streak", "macd_cross", "bb_pct"} <= rows["AAA"].keys()


def test_scan_reports_macd_sell(tmp_path, monkeypatch):
    """Code cũ chỉ có BUY/BULL/BEAR ⇒ live không bao giờ thấy SELL."""
    hist = _bars()
    _put_hist(tmp_path / "prices", "AAA", hist)
    _put_quote(tmp_path / "_live", "AAA", hist["close"].iloc[-1] * 0.85 * 1000)
    _, rows = _scan(tmp_path, monkeypatch)
    assert rows["AAA"]["macd_cross"] == "SELL"


def _count_calc(monkeypatch):
    import vnstock_screener
    real, calls = vnstock_screener._calc_indicators, []
    monkeypatch.setattr(vnstock_screener, "_calc_indicators",
                        lambda df: calls.append(len(df)) or real(df))
    return calls


def test_scan_memoizes_unchanged_quotes(tmp_path, monkeypatch):
    """Lỗi 4: mỗi 10s tính lại ~1.100 mã dù giá không đổi."""
    for t in ("AAA", "BBB"):
        _put_hist(tmp_path / "prices", t, _bars())
        _put_quote(tmp_path / "_live", t, 61_000.0, mtime_ns=T0)
    calls, state = _count_calc(monkeypatch), {}
    _, first = _scan(tmp_path, monkeypatch, state)
    assert len(calls) == 2

    _, again = _scan(tmp_path, monkeypatch, state)
    assert len(calls) == 2 and again == first                 # không đổi gì ⇒ 0 lần

    aaa = tmp_path / "_live" / "quote_AAA.json"
    aaa.write_text("{hỏng", encoding="utf-8")                 # mtime như cũ ⇒ không mở file
    os.utime(aaa, ns=(T0, T0))
    _, again = _scan(tmp_path, monkeypatch, state)
    assert len(calls) == 2 and again == first

    _put_quote(tmp_path / "_live", "AAA", 61_000.0, time="2026-10-16T14:25:00",
               mtime_ns=T0 + S)                               # tầng lạnh ghi lại, giá như cũ
    _, again = _scan(tmp_path, monkeypatch, state)
    assert len(calls) == 2 and again == first

    _put_quote(tmp_path / "_live", "BBB", 59_000.0, mtime_ns=T0 + 2 * S)
    _, again = _scan(tmp_path, monkeypatch, state)
    assert len(calls) == 3 and again["BBB"]["last_close"] == 59.0
    assert again["AAA"] == first["AAA"]


def test_scan_budget_defers_rest_and_resumes_from_first_deferred(tmp_path, monkeypatch):
    """Giờ cao điểm vài trăm mã đổi KL mỗi lượt ⇒ 3-5s CPU/10s, lượt đầu chặn phiên ~1 phút.
    Ngân sách cắt lượt; mã hoãn giữ row cũ; lượt sau bắt đầu từ mã hoãn đầu tiên — không thì
    lượt nào cũng hết giờ ở cùng chỗ và mã cuối danh sách không bao giờ được tính."""
    import types

    import dashboard.screener_tab as tab
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    for t in tickers:
        _put_hist(tmp_path / "prices", t, _bars())
        _put_quote(tmp_path / "_live", t, 61_000.0, mtime_ns=T0)
    calls, state = _count_calc(monkeypatch), {}
    # đồng hồ giả: 1 "giây" = 1 lần tính chỉ báo ⇒ ngân sách 2 = đúng 2 mã mỗi lượt
    monkeypatch.setattr(tab, "time", types.SimpleNamespace(monotonic=lambda: len(calls)))

    def scan():
        return _scan_all(tmp_path, monkeypatch, state, budget_s=2)

    scanned, rows, pending, _ = scan()
    assert (scanned, sorted(rows), pending, len(calls)) == (2, ["AAA", "BBB"], 3, 2)

    for t in tickers:                                         # mọi mã đổi giá trước lượt 2
        _put_quote(tmp_path / "_live", t, 62_000.0, mtime_ns=T0 + S)
    scanned, rows, pending, _ = scan()
    assert (scanned, sorted(rows), pending, len(calls)) == (4, ["AAA", "BBB", "CCC", "DDD"], 3, 4)
    assert rows["CCC"]["last_close"] == rows["DDD"]["last_close"] == 62.0   # tiếp từ CCC
    assert rows["AAA"]["last_close"] == rows["BBB"]["last_close"] == 61.0   # hoãn: row cũ vẫn hit

    scanned, rows, pending, _ = scan()                        # EEE, AAA; BBB hoãn lần nữa
    assert (scanned, pending, len(calls), rows["BBB"]["last_close"]) == (5, 1, 6, 61.0)
    scanned, rows, pending, _ = scan()
    assert (scanned, pending, len(calls)) == (5, 0, 7)
    assert {t: r["last_close"] for t, r in rows.items()} == dict.fromkeys(tickers, 62.0)


@pytest.mark.parametrize("exc", [KeyError, TypeError])
def test_scan_reports_one_ticker_error_and_keeps_round(tmp_path, monkeypatch, exc):
    """Một mã làm `_calc_indicators` ném lỗi ngoài (OSError, ValueError) ⇒ code cũ sập cả vòng.
    Nay bỏ riêng mã đó, trả số lỗi + mẫu để fragment báo, không ghi memo ⇒ lượt sau thử lại."""
    import vnstock_screener
    real, calls = vnstock_screener._calc_indicators, []

    def calc(df):
        calls.append(df["close"].iloc[-1])
        if df["close"].iloc[-1] == 55.0:
            raise exc("rsi_14")
        return real(df)

    monkeypatch.setattr(vnstock_screener, "_calc_indicators", calc)
    for t, price in (("AAA", 61_000.0), ("BAD", 55_000.0), ("CCC", 62_000.0)):
        _put_hist(tmp_path / "prices", t, _bars())
        _put_quote(tmp_path / "_live", t, price, mtime_ns=T0)
    state = {}
    scanned, rows, _, errors = _scan_all(tmp_path, monkeypatch, state)
    assert scanned == 2 and sorted(rows) == ["AAA", "CCC"]
    assert errors == [f"BAD: {exc.__name__}: {exc('rsi_14')}"]
    _, rows, _, errors = _scan_all(tmp_path, monkeypatch, state)
    assert len(calls) == 4 and len(errors) == 1 and sorted(rows) == ["AAA", "CCC"]


def test_scan_skips_broken_quote_without_failing_round(tmp_path, monkeypatch):
    for t in ("AAA", "BBB", "CCC"):
        _put_hist(tmp_path / "prices", t, _bars())
    _put_quote(tmp_path / "_live", "AAA", 61_000.0)
    (tmp_path / "_live" / "quote_BBB.json").write_text("{hỏng", encoding="utf-8")
    (tmp_path / "_live" / "quote_CCC.json").write_text("null", encoding="utf-8")
    scanned, rows = _scan(tmp_path, monkeypatch)
    assert scanned == 1 and set(rows) == {"AAA"}


def test_scan_ignores_quote_from_past_session_even_on_last_bar_day(tmp_path, monkeypatch):
    """File quote chụp 11:00 phiên D-1 (dashboard tắt giữa phiên; hôm nay WSS chưa ghi mã này)
    trùng ngày bar EOD D-1 ⇒ code cũ đè bar EOD bằng giá 11:00: chg_1d −4%, vol 0,28×, MACD SELL
    giả. Live Scan chỉ dùng quote của HÔM NAY; hôm nay = D-1 và bar D-1 ghi TRƯỚC quote (dở dang,
    pipeline chạy bù 10:20) thì vẫn thay bar."""
    hist = _bars()                                            # kho tới 2026-10-15
    price = round(hist["close"].iloc[-1] * 0.95, 2)
    _put_hist(tmp_path / "prices", "AAA", hist, written=_at("2026-10-15T10:20"))
    _put_quote(tmp_path / "_live", "AAA", price * 1000, time="2026-10-15T11:00:00",
               volume=3e5, high=hist["close"].iloc[-1] * 1000, low=price * 1000)
    assert _scan(tmp_path, monkeypatch, today=TODAY) == (0, {})

    scanned, rows = _scan(tmp_path, monkeypatch, today=date(2026, 10, 15))
    assert scanned == 1 and rows["AAA"]["last_close"] == price
    assert rows["AAA"]["chg_1d_pct"] == round((price / hist["close"].iloc[-2] - 1) * 100, 2)


@pytest.mark.parametrize("written, replaced", [
    ("2026-10-16T18:30", False),    # bar EOD (pipeline 18:00) mới hơn quote 11:00 ⇒ không đè
    ("2026-10-16T10:20", True),     # bar dở dang (pipeline chạy bù sáng) cũ hơn quote ⇒ thay
])
def test_scan_same_day_quote_replaces_bar_only_if_taken_after_write(tmp_path, monkeypatch,
                                                                    written, replaced):
    """Dashboard tắt 11:00, tối mở lại (today = D) khi kho đã có bar EOD D: code cũ đè EOD bằng
    giá 11:00 ⇒ chg_1d −4%, vol 0,28×, MACD SELL giả. Ngày không phân biệt được EOD với bar dở
    dang ⇒ so THỜI ĐIỂM quote với lúc ghi file parquet."""
    hist = _bars(end="2026-10-16")
    price = round(hist["close"].iloc[-1] * 0.95, 2)
    _put_hist(tmp_path / "prices", "AAA", hist, written=_at(written))
    _put_quote(tmp_path / "_live", "AAA", price * 1000, time="2026-10-16T11:00:00", volume=3e5)
    scanned, rows = _scan(tmp_path, monkeypatch)
    assert scanned == int(replaced)
    assert {t: r["last_close"] for t, r in rows.items()} == ({"AAA": price} if replaced else {})


def test_scan_rechecks_quote_taken_before_write_once_file_changes(tmp_path, monkeypatch):
    """Quote 10:15 cũ hơn bar dở dang 10:20 ⇒ bỏ. WSS ghi lại lúc 11:00 với giá/KL y nguyên (mã ít
    khớp, KL 0) ⇒ khoá (ngày, giá, KL, cao, thấp) như cũ nhưng giờ quote đã mới hơn kho ⇒ phải
    thay bar, không được dính memo "bỏ"."""
    _put_hist(tmp_path / "prices", "AAA", _bars(end="2026-10-16"), written=_at("2026-10-16T10:20"))
    _put_quote(tmp_path / "_live", "AAA", 66_000.0, time="2026-10-16T10:15:00", volume=0.0,
               mtime_ns=T0)
    state = {}
    assert _scan(tmp_path, monkeypatch, state) == (0, {})
    _put_quote(tmp_path / "_live", "AAA", 66_000.0, time="2026-10-16T11:00:00", volume=0.0,
               mtime_ns=T0 + S)
    scanned, rows = _scan(tmp_path, monkeypatch, state)
    assert scanned == 1 and rows["AAA"]["last_close"] == 66.0


def test_scan_before_open_reads_no_parquet(tmp_path, monkeypatch):
    """Trước 9:00 cả ~1.100 quote là của hôm qua: code cũ đọc parquet từng mã rồi mới bỏ (~33 lượt
    ngân sách vô ích). Mở quote trước ⇒ 0 lần đọc parquet, không mã nào phải chờ lượt sau."""
    import types

    import dashboard.screener_tab as tab
    real, reads = tab._read_recent_history, []
    monkeypatch.setattr(tab, "_read_recent_history", lambda d: reads.append(d.name) or real(d))
    # đồng hồ giả: 1 "giây" = 1 lần đọc parquet ⇒ ngân sách 1 = đúng 1 lần đọc mỗi lượt
    monkeypatch.setattr(tab, "time", types.SimpleNamespace(monotonic=lambda: len(reads)))
    for t in ("AAA", "BBB", "CCC"):
        _put_hist(tmp_path / "prices", t, _bars())
        _put_quote(tmp_path / "_live", t, 61_000.0, time="2026-10-15T14:45:00", mtime_ns=T0)
    assert _scan_all(tmp_path, monkeypatch, budget_s=1) == (0, {}, 0, [])
    assert reads == []


def test_scan_remembers_non_dict_quote_without_reopening(tmp_path, monkeypatch):
    """JSON hợp lệ nhưng không phải dict (`null`) từng không ghi memo ⇒ mỗi lượt mở lại file và
    tiêu ngân sách. Lượt 2 ngân sách 0, mtime như cũ ⇒ không còn mã nào phải hoãn."""
    for t in ("AAA", "CCC"):
        _put_hist(tmp_path / "prices", t, _bars())
    _put_quote(tmp_path / "_live", "AAA", 61_000.0, mtime_ns=T0)
    null = tmp_path / "_live" / "quote_CCC.json"
    null.write_text("null", encoding="utf-8")
    os.utime(null, ns=(T0, T0))
    state = {}
    scanned, _, pending, _ = _scan_all(tmp_path, monkeypatch, state)
    assert (scanned, pending) == (1, 0)
    scanned, rows, pending, errors = _scan_all(tmp_path, monkeypatch, state, budget_s=0)
    assert (scanned, sorted(rows), pending, errors) == (1, ["AAA"], 0, [])


def test_scan_skips_short_or_missing_history(tmp_path, monkeypatch):
    _put_hist(tmp_path / "prices", "NEW", _bars(n=59))        # < 60 bar như min_rows của EOD
    _put_quote(tmp_path / "_live", "NEW", 61_000.0)
    _put_quote(tmp_path / "_live", "NOHIST", 61_000.0)
    assert _scan(tmp_path, monkeypatch) == (0, {})


def test_scan_caches_history_for_the_day_only(tmp_path, monkeypatch):
    """Không đọc lại parquet mỗi 10s, nhưng sang ngày mới thì đọc lại (pipeline 18:00 ghi bar mới)."""
    hist = _bars()
    _put_hist(tmp_path / "prices", "AAA", hist)
    _put_quote(tmp_path / "_live", "AAA", 61_000.0, mtime_ns=T0)
    state = {}
    _scan(tmp_path, monkeypatch, state)
    rebased = hist.assign(close=hist["close"] * 0.9)
    _put_hist(tmp_path / "prices", "AAA", rebased)
    _put_quote(tmp_path / "_live", "AAA", 62_000.0, mtime_ns=T0 + S)
    _, same_day = _scan(tmp_path, monkeypatch, state)
    assert same_day["AAA"]["chg_20d_pct"] == round((62.0 / hist["close"].iloc[-20] - 1) * 100, 2)
    _put_quote(tmp_path / "_live", "AAA", 62_000.0, time="2026-10-17T10:00:00")   # quote hôm nay
    _, next_day = _scan(tmp_path, monkeypatch, state, today=date(2026, 10, 17))
    assert next_day["AAA"]["chg_20d_pct"] == round((62.0 / rebased["close"].iloc[-20] - 1) * 100, 2)


@pytest.mark.parametrize("env, expected", [(None, ["AAA"]), ("0", ["AAA", "OLD"])])
def test_scan_skips_ticker_whose_warehouse_is_stale(tmp_path, monkeypatch, env, expected):
    """Kho đứng im nhiều phiên (cách ly basis drift, ngừng GD): nối bar live ngay sau khoảng
    trống ⇒ chỉ báo nhảy vọt ⇒ hit giả. Lịch phiên = bar VNINDEX của kho; env 0 = tắt lọc."""
    monkeypatch.delenv("VNSTOCK_SCREENER_STALE_SESSIONS", raising=False)
    if env is not None:
        monkeypatch.setenv("VNSTOCK_SCREENER_STALE_SESSIONS", env)
    prices = tmp_path / "prices"
    _put_hist(prices, "VNINDEX", _bars(n=150, end="2026-10-15"))
    _put_hist(prices, "AAA", _bars(end="2026-10-14"))          # trễ 1 phiên: vẫn xét
    _put_hist(prices, "OLD", _bars(end="2026-10-01"))          # trễ 10 phiên
    for t in ("AAA", "OLD"):
        _put_quote(tmp_path / "_live", t, 61_000.0)
    state = {}
    scanned, rows = _scan(tmp_path, monkeypatch, state)
    assert (scanned, sorted(rows)) == (len(expected), expected)
    assert state["stale"] == ({"OLD"} if env is None else set())


def test_read_recent_history_only_latest_two_years(tmp_path):
    from dashboard.screener_tab import _read_recent_history
    _put_hist(tmp_path, "AAA", _bars(n=100, end="2022-12-30").assign(close=999.0))   # "độc"
    _put_hist(tmp_path, "AAA", _bars(n=250, end="2024-06-28"))
    assert {p.name for p in (tmp_path / "ticker=AAA").iterdir()} == {
        "year=2022", "year=2023", "year=2024"}
    df, _ = _read_recent_history(tmp_path / "ticker=AAA")
    assert len(df) == 250 and df["time"].dt.year.min() == 2023 and (df["close"] != 999.0).all()


def test_read_recent_history_dedups_conflicted_copy_by_mtime(tmp_path):
    """Dropbox đẻ "(conflicted copy).parquet" cạnh file gốc ⇒ giữ bản mtime MỚI, không trùng ngày."""
    from dashboard.screener_tab import _read_recent_history
    year = tmp_path / "ticker=AAA" / "year=2026"
    year.mkdir(parents=True)
    base = _bars(n=80, end="2026-10-15")
    newer = base.tail(5).assign(close=base["close"].tail(5) + 1.0)
    base.to_parquet(year / "z_old.parquet", index=False)      # tên xếp SAU nhưng mtime CŨ hơn
    newer.to_parquet(year / "a_new (conflicted copy).parquet", index=False)
    os.utime(year / "z_old.parquet", ns=(T0, T0))
    os.utime(year / "a_new (conflicted copy).parquet", ns=(T0 + S, T0 + S))
    df, written_at = _read_recent_history(tmp_path / "ticker=AAA")
    assert len(df) == 80 and df["time"].is_unique and df["time"].is_monotonic_increasing
    assert written_at == (T0 + S) / 10**9                     # lúc ghi = mtime MỚI nhất đã đọc
    assert df["close"].tail(5).tolist() == newer["close"].tolist()
    assert df["close"].iloc[0] == base["close"].iloc[0]


def test_read_recent_history_normalizes_vnd_cells(tmp_path):
    from dashboard.screener_tab import _read_recent_history
    df = _bars(n=80)
    df.loc[df.index[-1], "close"] = df["close"].iloc[-1] * 1000   # một ô ở đơn vị VND
    _put_hist(tmp_path, "AAA", df)
    out, _ = _read_recent_history(tmp_path / "ticker=AAA")
    assert out["close"].iloc[-1] == pytest.approx(df["close"].iloc[-1] / 1000)


def test_top_hits_tolerates_missing_rsi_and_volume():
    """rsi_14 None (loss = 0) làm `sorted` ném TypeError và f"{None:.0f}" sập fragment."""
    from dashboard.screener_tab import _top_hits
    hits = [{"ticker": "AAA", "rsi_14": None, "vol_spike": None},
            {"ticker": "BBB", "rsi_14": 28.4, "vol_spike": 1.56}]
    assert _top_hits(hits) == [("BBB", "RSI 28 Vol 1.6x"), ("AAA", "RSI — Vol —")]
