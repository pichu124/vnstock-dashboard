"""`vnstock_reachability` — đo tầm với của TP theo horizon (13/08).

Test chạy trên dữ liệu TỔNG HỢP có gieo hạt (container không có kho giá; số
thật user đo trên máy thật). Điều đáng canh không phải con số cụ thể mà là
các BẤT BIẾN của phép đo — sai một cái là toàn bộ kết luận cấu hình sai theo:

* MFE không giảm khi horizon dài ra (max của tập lớn hơn ≥ max của tập con);
* MAE ≤ 0 ≤ MFE (max(high) ≥ close vào, min(low) ≤ close vào của phiên sau
  gần kề — với dữ liệu hợp lệ high ≥ close ≥ low);
* tỷ lệ với-tới GIẢM khi mốc ATR tăng (đặt TP xa hơn không thể dễ tới hơn);
* không có mẫu → {} (không đo được phải nói không đo được, không trả bảng 0).
"""
import numpy as np
import pandas as pd
import pytest

from vnstock_reachability import (
    DEFAULT_HORIZONS,
    measure_ticker,
    merge_measures,
    summarize,
)


def _bars(n=400, seed=7, drift=0.0005):
    rng = np.random.default_rng(seed)
    close = 50 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    spread = np.abs(rng.normal(0.008, 0.003, n))
    return pd.DataFrame({
        "time": pd.bdate_range(end="2026-08-13", periods=n),
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": rng.integers(100_000, 5_000_000, n),
    })


@pytest.fixture(scope="module")
def summary():
    measures = [measure_ticker(_bars(seed=s)) for s in (1, 2, 3)]
    return summarize(merge_measures(measures))


def test_all_default_horizons_present(summary):
    assert set(summary) == {str(h) for h in DEFAULT_HORIZONS}
    assert all(s["n_samples"] > 50 for s in summary.values())


def test_mfe_grows_with_horizon(summary):
    """Cửa sổ dài hơn chứa cửa sổ ngắn → max chỉ có thể bằng hoặc lớn hơn.
    Vi phạm = lỗi cửa sổ trượt, mọi kết luận horizon sai theo."""
    p60 = [summary[str(h)]["mfe_pct"]["p60"] for h in DEFAULT_HORIZONS]
    assert all(b >= a for a, b in zip(p60, p60[1:])), p60


def test_mae_negative_mfe_positive(summary):
    for s in summary.values():
        assert s["mae_pct_p50"] <= 0
        assert s["mfe_pct"]["p50"] >= 0


def test_reach_share_decreases_as_tp_moves_further(summary):
    """TP đặt xa hơn không thể DỄ với tới hơn — chiều này gãy là phép chia
    ATR sai."""
    for s in summary.values():
        shares = [s["tp_reach_share"][k] for k in ("1.5", "2.5", "4.0")]
        assert all(0.0 <= x <= 1.0 for x in shares)
        assert shares[0] >= shares[1] >= shares[2]


def test_longer_horizon_reaches_the_same_tp_more_often(summary):
    """Chính giả thuyết 0/49: cùng mốc 2.5×ATR, horizon dài hơn phải với tới
    THƯỜNG XUYÊN hơn horizon 5 phiên."""
    share_5 = summary["5"]["tp_reach_share"]["2.5"]
    share_40 = summary["40"]["tp_reach_share"]["2.5"]
    assert share_40 >= share_5


def test_short_series_returns_empty_not_garbage():
    out = measure_ticker(_bars(n=30))
    assert all(not cols["mfe_pct"] for cols in out.values())
    assert summarize(merge_measures([out])) == {}


def test_summarize_empty_is_empty():
    assert summarize({}) == {}


def test_percentiles_are_ordered(summary):
    for s in summary.values():
        m = s["mfe_pct"]
        assert m["p50"] <= m["p60"] <= m["p75"] <= m["p90"]
