"""Lưới cho việc kho ĐỒNG BỘ QUA DROPBOX có thể tạm có 2 file trong một year-dir.

Sự thật hạ tầng (user xác nhận 19/08): `C:\\vnstock` đồng bộ Dropbox giữa
desktop `PICHU` và laptop `CFA-BINHLD-LT`. Hai máy ghi cùng file ⇒ Dropbox đẻ
`prices (X's conflicted copy YYYY-MM-DD).parquet` NGAY trong year-dir, và nó
cũng kết thúc bằng `.parquet` nên mọi glob đều nhặt.

Repo ĐÃ xử tốt ở đường ghi: `vnstock_parquet_io.read_year_frames` gộp mọi file
(không mất data nằm ở bản kia), `vnstock_updater._read_year` khử trùng ngày giữ
bản mtime mới nhất, `_write_year` dồn lại còn đúng 1 file, và `vnstock_health`
báo year-dir nào có >1 file.

Chỗ CHƯA xử là đường ĐỌC PHÂN TÍCH: `_load_history_from_parquet` (loader của
backtest) nối thẳng mọi file, không khử trùng ⇒ bar nằm ở cả hai file bị đếm
HAI LẦN. n_trades và Sharpe sai mà không có dấu hiệu gì — đúng loại lỗi im
lặng đã ngốn cả ngày 19/08.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from vnstock_strategy import _load_history_from_parquet

_COLS = ["time", "open", "high", "low", "close", "volume"]


def _bars(days, close):
    return pd.DataFrame({"time": days, "open": close, "high": close,
                         "low": close, "close": close,
                         "volume": [1e6] * len(days)})[_COLS]


@pytest.fixture()
def year_dir(tmp_path):
    d = tmp_path / "ticker=AAA" / "year=2026"
    d.mkdir(parents=True)
    return tmp_path, d


def _days(n=10):
    return list(pd.bdate_range(end="2026-08-17", periods=n).date)


def test_single_file_reads_every_bar_once(year_dir):
    root, d = year_dir
    days = _days()
    _bars(days, [100.0 + i for i in range(len(days))]).to_parquet(
        d / "prices.parquet", index=False)
    out = _load_history_from_parquet("AAA", days=0, prices_dir=root)
    assert len(out) == len(days)


def test_conflicted_copy_does_not_double_count_bars(year_dir):
    """Bar nằm ở CẢ HAI file phải tính MỘT lần — nếu không, backtest thấy gấp
    đôi số phiên và mọi thống kê per-trade lệch theo."""
    root, d = year_dir
    days = _days()
    px = [100.0 + i for i in range(len(days))]
    _bars(days, px).to_parquet(d / "prices.parquet", index=False)
    _bars(days, px).to_parquet(
        d / "prices (PICHU's conflicted copy 2026-08-19).parquet", index=False)
    out = _load_history_from_parquet("AAA", days=0, prices_dir=root)
    assert len(out) == len(days), "bar bị đếm hai lần"
    assert out["time"].is_unique


def test_the_newer_file_wins_on_a_clashing_day(year_dir):
    """Cùng ngữ nghĩa `_read_year`: file mtime MỚI hơn thắng."""
    import os
    import time as _t

    root, d = year_dir
    days = _days()
    old = d / "prices.parquet"
    _bars(days, [100.0] * len(days)).to_parquet(old, index=False)
    _t.sleep(0.01)
    new = d / "prices (conflicted copy).parquet"
    _bars(days, [55.0] * len(days)).to_parquet(new, index=False)
    os.utime(old, (0, 1_000_000))          # ép old thành CŨ hơn hẳn
    os.utime(new, (0, 2_000_000))
    out = _load_history_from_parquet("AAA", days=0, prices_dir=root)
    assert out["close"].iloc[0] == pytest.approx(55.0)


def test_bars_only_in_the_conflicted_copy_are_not_lost(year_dir):
    """Bản kia có thể mang phiên MỚI hơn — bỏ nó là mất data thật."""
    root, d = year_dir
    days = _days()
    _bars(days[:-2], [100.0] * (len(days) - 2)).to_parquet(
        d / "prices.parquet", index=False)
    _bars(days[-2:], [200.0, 201.0]).to_parquet(
        d / "prices (conflicted copy).parquet", index=False)
    out = _load_history_from_parquet("AAA", days=0, prices_dir=root)
    assert len(out) == len(days)
