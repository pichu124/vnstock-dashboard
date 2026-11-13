"""`rebase_ticker_history.rewrite_frame` — viết lại một file năm khi rebase (hàm thuần).

🖥️ 13/11/2026: SCL (khối lượng × 1.17) và VBB (giá lưu int64 ÷ hệ số) ném
`TypeError: Invalid value … for dtype 'int64'` ⇒ rebase bỏ 2 mã, sổ cách ly còn nguyên.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebase_ticker_history.py"
_spec = importlib.util.spec_from_file_location("rebase_ticker_history_rf", _SCRIPT)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _wh(days, close, vol):
    return pd.DataFrame({"time": pd.to_datetime(days), "open": close, "high": close,
                         "low": close, "close": close, "volume": vol})


def test_int64_volume_scaled_by_fractional_factor_rounds_back_to_int():
    # SCL: khối lượng int64 nhân 1.17 (bar có trong nguồn) ⇒ phải ra số nguyên, không ném.
    wh = _wh(["2026-06-01", "2026-06-02"], [117, 118], pd.array([80_098, 1_000], dtype="int64"))
    src = _wh(["2026-06-01", "2026-06-02"], [100.0, 100.85], [80_098.0, 1_000.0])
    src_idx = src.set_index(src["time"].dt.normalize())
    out, n_src, n_scaled = R.rewrite_frame(wh, src_idx, cut=date(2026, 6, 3), brk=date(2026, 6, 3),
                                           factor=1.17, scale_vol=1.17, vol_factor=1.0)
    assert (n_src, n_scaled) == (2, 0)
    assert out["volume"].dtype == "int64" and out["volume"].tolist() == [93_715, 1_170]
    assert out["close"].tolist() == [100.0, 100.85]


def test_int_price_column_divided_by_factor_becomes_float():
    # VBB: giá lưu int64 (37) ở bar NGOÀI tầm nguồn ⇒ chia 1.0890 ra 33.976…, không ném.
    wh = _wh(["2011-01-04"], pd.array([37], dtype="int64"), pd.array([500], dtype="int64"))
    src = _wh(["2026-06-01"], [10.0], [1.0])
    src_idx = src.set_index(src["time"].dt.normalize())
    out, n_src, n_scaled = R.rewrite_frame(wh, src_idx, cut=date(2026, 6, 3), brk=date(2026, 6, 3),
                                           factor=1.089, scale_vol=1.0, vol_factor=1.0)
    assert (n_src, n_scaled) == (0, 1)
    assert abs(out["close"].iloc[0] - 37 / 1.089) < 1e-9
    assert out["volume"].tolist() == [500] and out["volume"].dtype == "int64"


def test_nothing_before_cut_returns_none():
    wh = _wh(["2026-11-10"], [10.0], [1.0])
    src_idx = wh.set_index(wh["time"].dt.normalize())
    assert R.rewrite_frame(wh, src_idx, cut=date(2026, 11, 1), brk=date(2026, 11, 1),
                           factor=1.1, scale_vol=1.0, vol_factor=1.0) == (None, 0, 0)
