"""Tests cho vnstock_market_analyzer — hiện mới có regression zero-âm
(conviction "-0.00" trên dashboard/brief, lộ 17/07)."""
from __future__ import annotations

import pandas as pd

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


def fake_vnstock_data(net_per_day: float):
    """TopStock trả AAA mua ròng `net_per_day` VND MỖI ngày được hỏi; Net BS rỗng."""
    import types

    class _TopStock:
        def foreign_buy(self, date, limit):
            return pd.DataFrame({"symbol": ["AAA"], "net_value": [net_per_day]})

        def foreign_sell(self, date, limit):
            return pd.DataFrame()

    class _Trading:
        def __init__(self, symbol):
            pass

        def order_stats(self):
            return pd.DataFrame()

    return types.SimpleNamespace(TopStock=_TopStock, Trading=_Trading)


def test_runner_leaves_nn_3m_missing_when_feed_has_only_20_sessions(tmp_path, monkeypatch):
    import sys

    import vnstock_runner as vr

    monkeypatch.setitem(sys.modules, "vnstock_data", fake_vnstock_data(1e9))
    out = vr.compute_market_overview(str(mini_warehouse(tmp_path)))

    sector = out["sectors"][0]
    assert sector["NN 1M (tỷ)"] == 20.0          # 20 phiên × 1 tỷ
    assert pd.isna(sector["NN 3M (tỷ)"])         # không phải 20.0 chép từ 1M
    aaa = next(t for t in out["tickers"] if t["Mã"] == "AAA")
    assert aaa["NN 1M (tỷ)"] == 20.0 and pd.isna(aaa["NN 3M (tỷ)"])


def test_nn_windows_fill_3m_once_feed_covers_60_sessions():
    import vnstock_runner as vr

    days = pd.bdate_range(end="2026-10-16", periods=65)
    nn = pd.DataFrame({"symbol": "AAA", "date": days, "net_value": 1e9})
    nn_w, nn_m, nn_3m, anchor = vr._nn_windows(nn)
    assert anchor == "2026-10-16"
    assert nn_m["AAA"] < nn_3m["AAA"] <= 65.0
    assert vr._nn_windows(nn.tail(59))[2] == {}


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
