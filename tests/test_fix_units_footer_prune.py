"""
Lưới cho phép lọc bằng THỐNG KÊ FOOTER của `fix-units`.

Bước này quét TOÀN KHO mỗi đêm và đang tăng: **98s (18/08) → 302s (24/08) →
316s (25/08)**. Nó soi ~3.125 thư mục mã (KHÔNG lọc `_is_stock` như updater)
và giải nén CẢ 6 cột trong khi chỉ dùng `time` + `close`.

`_detect_in_ticker` chỉ có thể sinh fix khi tồn tại bar `close >
RAW_VND_THRESHOLD`. Parquet ghi sẵn max mỗi cột trong footer, và
`pq.read_metadata` đọc footer mà KHÔNG giải nén data page. Nên bỏ qua mã có
max(close) ≤ ngưỡng là phép lọc **tương đương chứng minh được**.

Bất biến sống chết: **nghi ngờ thì ĐỌC**. Bỏ sót một bar sai đơn vị là ghi số
sai vào kho giá — đắt hơn nhiều so với đọc thừa vài mã.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import vnstock_fix_units as fu


def _mk(root, ticker, closes, year=2026, columns=True):
    d = root / "prices" / f"ticker={ticker}" / f"year={year}"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=len(closes)),
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1] * len(closes),
    })
    if not columns:
        df = df.drop(columns=["close"])
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   d / "prices.parquet")
    return d / "prices.parquet"


@pytest.fixture()
def wh(tmp_path):
    return tmp_path


class TestEquivalence:
    def test_a_clean_ticker_is_skipped_without_being_read(self, wh):
        _mk(wh, "SACH", [10.0] * 40)
        rep = fu.scan(wh)
        assert rep.scanned_tickers == 1
        assert rep.skipped_by_footer == 1
        assert rep.fixes == []
        assert rep.scanned_bars == 0        # không giải nén bar nào

    def test_a_dirty_ticker_is_still_read_and_fixed(self, wh):
        _mk(wh, "BAN", [10.0] * 20 + [12345.0] + [10.0] * 19)
        rep = fu.scan(wh)
        assert rep.skipped_by_footer == 0
        assert [(f.ticker, f.close_before, f.close_after) for f in rep.fixes] == \
            [("BAN", 12345.0, 12.345)]

    def test_the_prune_never_changes_the_fix_list(self, wh):
        """So thẳng với đường CŨ (đọc mọi mã, mọi cột) trên cùng một kho."""
        _mk(wh, "SACH", [10.0] * 40)
        _mk(wh, "BAN", [10.0] * 20 + [12345.0] + [10.0] * 19)
        _mk(wh, "NUA", [25.0] * 30)
        new = {(f.ticker, f.time, f.close_after) for f in fu.scan(wh).fixes}

        from vnstock_anomaly import _iter_warehouse_tickers
        old = set()
        for tk, df in _iter_warehouse_tickers(wh):
            for f in fu._detect_in_ticker(tk, df):
                old.add((f.ticker, f.time, f.close_after))
        assert new == old

    def test_exactly_at_the_threshold_is_not_a_candidate(self, wh):
        # Quy tắc là `close > RAW_VND_THRESHOLD` — BẰNG ngưỡng thì không phải
        _mk(wh, "MEP", [10.0] * 30 + [fu.RAW_VND_THRESHOLD] + [10.0] * 9)
        assert fu.scan(wh).skipped_by_footer == 1

    def test_just_above_the_threshold_is_read(self, wh):
        _mk(wh, "MEP", [10.0] * 30 + [fu.RAW_VND_THRESHOLD + 0.5] + [10.0] * 9)
        assert fu.scan(wh).skipped_by_footer == 0


class TestWhenInDoubtRead:
    def test_a_file_without_a_close_column_is_read(self, wh):
        _mk(wh, "LA", [10.0] * 30, columns=False)
        assert fu._needs_read(wh / "prices" / "ticker=LA") is True

    def test_unreadable_footer_is_read(self, wh):
        d = wh / "prices" / "ticker=HONG" / "year=2026"
        d.mkdir(parents=True, exist_ok=True)
        (d / "prices.parquet").write_bytes(b"not a parquet file")
        assert fu._needs_read(wh / "prices" / "ticker=HONG") is True

    def test_missing_statistics_is_read(self, wh, monkeypatch):
        _mk(wh, "SACH", [10.0] * 40)
        monkeypatch.setattr(fu, "_max_close_from_footer", lambda p: None)
        assert fu._needs_read(wh / "prices" / "ticker=SACH") is True

    def test_a_ticker_with_no_parquet_at_all_is_not_read(self, wh):
        (wh / "prices" / "ticker=RONG").mkdir(parents=True)
        assert fu._needs_read(wh / "prices" / "ticker=RONG") is False

    def test_one_dirty_year_out_of_many_forces_the_read(self, wh):
        _mk(wh, "MIX", [10.0] * 30, year=2024)
        _mk(wh, "MIX", [10.0] * 30, year=2025)
        _mk(wh, "MIX", [10.0] * 20 + [9999.0] + [10.0] * 9, year=2026)
        assert fu._needs_read(wh / "prices" / "ticker=MIX") is True
        assert fu.scan(wh).fixes


class TestReportCarriesTheMeasurement:
    def test_skip_count_is_reported(self, wh):
        _mk(wh, "A", [10.0] * 30)
        _mk(wh, "B", [10.0] * 30)
        _mk(wh, "C", [10.0] * 20 + [5000.0] + [10.0] * 9)
        rep = fu.scan(wh)
        assert rep.skipped_by_footer == 2 and rep.scanned_tickers == 3

    def test_skip_count_is_in_the_json_payload(self, wh):
        _mk(wh, "A", [10.0] * 30)
        assert fu.scan(wh).to_dict()["skipped_by_footer"] == 1

    def test_ticker_filter_still_works(self, wh):
        _mk(wh, "A", [10.0] * 20 + [9999.0] + [10.0] * 9)
        _mk(wh, "B", [10.0] * 20 + [9999.0] + [10.0] * 9)
        rep = fu.scan(wh, tickers=["A"])
        assert rep.scanned_tickers == 1 and {f.ticker for f in rep.fixes} == {"A"}
