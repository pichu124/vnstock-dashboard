"""Tests cho vnstock_market_analyzer — hiện mới có regression zero-âm
(conviction "-0.00" trên dashboard/brief, lộ 17/07)."""
from __future__ import annotations

import pandas as pd
import pytest

from vnstock_market_analyzer import market_regime


def test_market_regime_conviction_no_negative_zero():
    # composite trung bình -0.001 → round(…, 2) = -0.0 → format "+.2f" từng
    # hiện "conviction -0.00"; nay khử về 0.0 dương sạch
    r = market_regime(pd.DataFrame({"composite": [0.199, -0.201]}))
    assert f"{r['conviction']:+.2f}" == "+0.00"
    # giá trị khác 0 giữ nguyên
    r2 = market_regime(pd.DataFrame({"composite": [0.5, 0.9]}))
    assert r2["conviction"] == 0.7
    # âm thật vẫn âm
    r3 = market_regime(pd.DataFrame({"composite": [-0.5, -0.9]}))
    assert r3["conviction"] == -0.7


def test_market_regime_empty_scores():
    r = market_regime(pd.DataFrame())
    assert r["conviction"] == 0 and "Không đủ dữ liệu" in r["regime"]


# ── NN 3M: feed TopStock chỉ ~20 phiên ⇒ cửa sổ 90 ngày phủ đúng dữ liệu 30 ngày ──
# Cột "NN 3M" từng bằng hệt "NN 1M", analyzer đọc thành xu hướng (fx3, nn_trend) và
# in "🌍 NN ACCUMULATING: pace 1M nhanh hơn avg 3M" khi không có dữ liệu 3M nào.

def mini_warehouse(root, tickers=("AAA", "BBB"), n_bars=70):
    """Kho giả tối thiểu cho `vnstock_runner`: prices/ticker=*/year=*/ + bảng ngành."""
    from pathlib import Path

    root = Path(root)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_bars)
    for i, tk in enumerate(tickers):
        px = [20.0 + i + 0.1 * k for k in range(n_bars)]
        bars = pd.DataFrame({"time": days, "open": px, "high": [p * 1.01 for p in px],
                             "low": [p * 0.99 for p in px], "close": px,
                             "volume": [1e6 * (i + 1)] * n_bars})
        for year, grp in bars.groupby(bars["time"].dt.year):
            yd = root / "prices" / f"ticker={tk}" / f"year={year}"
            yd.mkdir(parents=True)
            grp.to_parquet(yd / "prices.parquet", index=False)
    (root / "_meta").mkdir(parents=True)
    pd.DataFrame({"ticker": list(tickers), "primary_industry": ["Ngân hàng"] * len(tickers)}
                 ).to_parquet(root / "_meta" / "industry_classification.parquet", index=False)
    return root


def fake_gen6_market(net_per_day: float, calls: "dict | None" = None):
    """`vnstock.Market` giả (thế hệ 6): `.equity.screener(date=)` trả AAA mua ròng `net_per_day`
    đồng MỖI phiên được hỏi + BBB không có NN; `.equity(t).trade_history()` rỗng (Net BS rỗng)."""
    calls = calls if calls is not None else {}

    class _Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def trade_history(self, start=None, end=None):
            calls.setdefault("trade_history", []).append((self.symbol, start))
            return pd.DataFrame()

    class _Equity:
        def __call__(self, symbol):
            return _Ticker(symbol)

        def screener(self, date=None, **_):
            calls.setdefault("screener", []).append(date)
            return pd.DataFrame({"symbol": ["AAA", "BBB"], "close": [20.0, 21.0],
                                 "foreign_net_value": [net_per_day, 0.0],
                                 "foreign_net_volume": [1_000, 0]})

    class _Market:
        def __init__(self, *_a, **_k):
            self.equity = _Equity()
    return _Market


def test_runner_leaves_nn_3m_missing_when_feed_has_only_20_sessions(tmp_path, monkeypatch):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    import vnstock

    import vnstock_runner as vr

    calls: dict = {}
    monkeypatch.setattr(vnstock, "Market", fake_gen6_market(1e9, calls))
    out = vr.compute_market_overview(str(mini_warehouse(tmp_path)))

    assert len(calls["screener"]) == 20          # một lượt cả thị trường mỗi phiên
    assert {s for s, _ in calls["trade_history"]} == {"AAA", "BBB"}
    sector = out["sectors"][0]
    assert sector["NN 1M (tỷ)"] == 20.0          # 20 phiên × 1 tỷ
    assert pd.isna(sector["NN 3M (tỷ)"])         # không phải 20.0 chép từ 1M
    aaa = next(t for t in out["tickers"] if t["Mã"] == "AAA")
    assert aaa["NN 1M (tỷ)"] == 20.0 and pd.isna(aaa["NN 3M (tỷ)"])


def test_runner_nn_keeps_top_buyers_and_sellers_per_session(monkeypatch):
    """Mỗi phiên: top `_NN_TOP_N` mua ròng + top `_NN_TOP_N` bán ròng (tập TopStock cũ),
    mã NN = 0/NaN bỏ; phiên nguồn lỗi bỏ qua, không làm hỏng cả lượt."""
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    import vnstock
    from vnstock.errors import NetworkError

    import vnstock_foreign_flow as ff
    import vnstock_runner as vr

    board = pd.DataFrame({"symbol": ["B1", "B2", "B3", "S1", "S2", "Z0", "NA"],
                          "foreign_net_value": [5e9, 3e9, 1e9, -4e9, -2e9, 0.0, None],
                          "foreign_net_volume": [1, 1, 1, -1, -1, 0, None]})
    seen = []

    def _board(day):
        seen.append(day)
        if len(seen) == 1:
            raise NetworkError("timeout")
        return board
    monkeypatch.setattr(ff, "foreign_net_for_date", _board)
    monkeypatch.setattr(vr, "_NN_TOP_N", 2)
    captured = {}
    monkeypatch.setattr(vr, "build_market_overview",
                        lambda wh, fetch_nn, fetch_net_bs: captured.setdefault("nn", fetch_nn()))
    vr.compute_market_overview("unused")
    nn = captured["nn"]
    assert len(seen) == 20 and nn["date"].nunique() == 19
    one = nn[nn["date"] == nn["date"].max()]
    assert dict(zip(one["symbol"], one["net_value"])) == {"B1": 5e9, "B2": 3e9,
                                                           "S1": -4e9, "S2": -2e9}


def test_net_bs_reads_trade_history_columns(tmp_path, monkeypatch):
    """Net BS = Σ(total_buy_trade_volume − total_sell_trade_volume) của 5/20/60/120 phiên,
    triệu cp — tên cột hồ sơ v5 của `trade_history` (= `order_stats` cũ)."""
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    import vnstock

    import vnstock_runner as vr

    days = pd.bdate_range(end="2026-10-16", periods=130)
    hist = pd.DataFrame({"trading_date": days[::-1],              # nguồn trả mới nhất trước
                         "total_buy_trade_volume": [3e6] * 130,
                         "total_sell_trade_volume": [1e6] * 130})

    class _Ticker:
        def trade_history(self, start=None, end=None):
            return hist

    class _Equity:
        def __call__(self, symbol):
            return _Ticker()

        def screener(self, date=None, **_):
            return pd.DataFrame()

    class _Market:
        def __init__(self, *_a, **_k):
            self.equity = _Equity()
    monkeypatch.setattr(vnstock, "Market", _Market)
    captured = {}
    monkeypatch.setattr(vr, "build_market_overview",
                        lambda wh, fetch_nn, fetch_net_bs: captured.setdefault(
                            "nb", fetch_net_bs(["AAA"])))
    (tmp_path / "_meta").mkdir()
    vr.compute_market_overview(str(tmp_path))
    assert captured["nb"] == {"AAA": {"1w": 10.0, "1m": 40.0, "3m": 120.0, "6m": 240.0}}


def test_nn_windows_fill_3m_once_feed_covers_60_sessions():
    import vnstock_runner as vr

    days = pd.bdate_range(end="2026-10-16", periods=65)
    nn = pd.DataFrame({"symbol": "AAA", "date": days, "net_value": 1e9})
    nn_w, nn_m, nn_3m, anchor = vr._nn_windows(nn)
    assert anchor == "2026-10-16"
    assert nn_m["AAA"] < nn_3m["AAA"] <= 65.0
    assert vr._nn_windows(nn.tail(59))[2] == {}


def test_price_change_of_high_priced_stock_crossing_500(tmp_path):
    """Mã giá > 500 nghìn (HLB, VNZ): `_normalize_prices` chia 1000 từng bar > 500 ⇒ Giá 1M %
    so 0.6 với 450 = −99,9%."""
    import vnstock_runner as vr

    root = mini_warehouse(tmp_path, tickers=("AAA", "HHH"))
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=70)
    px = [450.0] * 60 + [600.0] * 10
    bars = pd.DataFrame({"time": days, "open": px, "high": px, "low": px, "close": px,
                         "volume": [1e6] * 70})
    for year, grp in bars.groupby(days.year):
        grp.to_parquet(root / "prices" / "ticker=HHH" / f"year={year}" / "prices.parquet",
                       index=False)

    out = vr.build_market_overview(str(root))
    hhh = next(t for t in out["tickers"] if t["Mã"] == "HHH")
    assert hhh["Giá 1M %"] == 33.3                              # 600 / 450 − 1
    assert hhh["Giá 1T %"] == 0.0


def test_nn_1t_1m_sum_exactly_5_and_20_latest_sessions(tmp_path):
    """NN 1T/1M = 5/20 PHIÊN có trong data (như `Giá 1T %` = 5 phiên). Cắt `≥ mốc − 7
    ngày lịch` từng lấy cả mốc ⇒ 6 phiên khi mốc là ngày thường."""
    import vnstock_runner as vr

    days = pd.bdate_range(end="2026-10-16", periods=25)          # phiên k mua ròng k tỷ
    nn = pd.DataFrame({"symbol": "AAA", "date": days,
                       "net_value": [k * 1e9 for k in range(1, 26)]})
    out = vr.build_market_overview(str(mini_warehouse(tmp_path)), fetch_nn=lambda: nn)

    aaa = next(t for t in out["tickers"] if t["Mã"] == "AAA")
    assert aaa["NN 1T (tỷ)"] == 21 + 22 + 23 + 24 + 25           # 115, không phải 135
    assert aaa["NN 1M (tỷ)"] == sum(range(6, 26))                # 310
    assert pd.isna(aaa["NN 3M (tỷ)"])                            # 25 < 60 phiên
    assert out["sectors"][0]["NN 1T (tỷ)"] == 115.0


def test_conflicted_copy_counts_each_session_once_and_newest_file_wins(tmp_path):
    """Year-dir có "(… conflicted copy …).parquet" của Dropbox trùng ngày với file chính:
    mỗi phiên tính MỘT lần (GTGD/số mã không nhân đôi), bản mtime MỚI thắng."""
    import os

    import vnstock_runner as vr

    root = mini_warehouse(tmp_path)
    yd = next((root / "prices" / "ticker=AAA").glob("year=*"))
    main = pd.read_parquet(yd / "prices.parquet")
    copy = main.tail(10).assign(close=lambda d: d["close"] + 1.0)
    copy_pf = yd / "prices (PICHU's conflicted copy 2026-10-16).parquet"
    copy.to_parquet(copy_pf, index=False)
    t = os.stat(yd / "prices.parquet").st_mtime
    os.utime(copy_pf, (t + 60, t + 60))      # tên xếp TRƯỚC file chính, mtime SAU

    out = vr.build_market_overview(str(root))

    assert {v["count"] for v in out["gtgd_by_date"].values()} == {2}   # 2 mã, không phải 3
    aaa = next(x for x in out["tickers"] if x["Mã"] == "AAA")
    assert aaa["last"] == round(float(copy["close"].iloc[-1]), 2)


def test_young_warehouse_under_61_bars_builds_with_empty_price_3m(tmp_path):
    """Kho mới (mọi mã < 61 bar): chg60 toàn None ⇒ cột object, `.round` từng ném
    TypeError làm nổ cả market_overview."""
    import vnstock_runner as vr

    out = vr.build_market_overview(str(mini_warehouse(tmp_path, n_bars=30)))

    aaa = next(t for t in out["tickers"] if t["Mã"] == "AAA")
    assert pd.isna(aaa["Giá 3M %"])
    assert aaa["Giá 1T %"] == round((22.9 / 22.4 - 1) * 100, 1)   # cột còn lại vẫn có số
    assert pd.isna(out["sectors"][0]["Giá 3M %"])


def test_missing_nn_3m_drops_trend_flag_and_keeps_flow_finite():
    """NN 3M thiếu ⇒ không cờ ACCUMULATING/DUMPING; flow tính từ thành phần còn lại
    (thành phần thiếu z = 0, cùng mẫu `_zscore` dùng cho mọi cột thiếu)."""
    import numpy as np

    from vnstock_market_analyzer import compute_scores

    df = pd.DataFrame({"Ngành": ["A", "B", "C"], "Vốn hoá (tỷ)": [1000.0, 2000.0, 1500.0],
                       "Vol Avg 20": [1.0, 2.0, 1.5], "Net BS 1M": [0.5, -0.2, 0.1],
                       "Net BS 3M": [1.0, -0.5, 0.3], "NN 1M (tỷ)": [50.0, -30.0, 10.0],
                       "NN 3M (tỷ)": [None, None, None]})
    s = compute_scores(df)
    assert np.isfinite(s["flow"]).all() and s["flow"].abs().sum() > 0
    flags = [x for xs in list(s["catalysts"]) + list(s["red_flags"]) for x in xs]
    assert not [x for x in flags if "ACCUMULATING" in x or "DUMPING" in x]
