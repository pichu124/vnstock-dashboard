"""Lịch sử fundamentals theo thời điểm — user chốt bật 13/08.

Vì sao tồn tại: backtest "chọn cổ phiếu theo cơ bản" cần số liệu NHƯ ĐÃ BIẾT
tại từng thời điểm. `fundamentals.parquet` bị ghi đè mỗi lần update nên quá
khứ mất sạch — dùng số hôm nay cho ngày hôm qua là look-ahead, backtest đẹp
giả. Ảnh chụp mất rồi thì KHÔNG tái tạo được (API chỉ trả hiện tại), nên mỗi
tháng lưu một bản `_meta/fundamentals_history/fundamentals-YYYY-MM.parquet`.

Hợp đồng: một bản/tháng · bản ĐẦU của tháng thắng (không ghi đè) · hỏng
archive không được làm hỏng update chính · ghi nguyên tử (đã vào lưới
`_MUST_BE_ATOMIC`).
"""
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import vnstock_fundamental_updater as fu


@pytest.fixture
def hist_dir(tmp_path, monkeypatch):
    d = tmp_path / "fundamentals_history"
    monkeypatch.setattr(fu, "FUND_HISTORY_DIR", d)
    return d


def _table(roe=15.0):
    return pa.table({"ticker": ["VCB"], "roe": [roe]})


def test_first_run_of_the_month_writes_a_snapshot(hist_dir):
    dest = fu._archive_monthly_snapshot(_table(), now=datetime(2026, 8, 13))
    assert dest is not None
    assert dest.name == "fundamentals-2026-08.parquet"
    assert pq.read_table(dest).column("ticker").to_pylist() == ["VCB"]


def test_second_run_same_month_is_a_noop(hist_dir):
    """Bản ĐẦU của tháng thắng: ảnh chụp càng gần đầu tháng càng gần "như đã
    biết lúc đó". Chạy lại trong tháng không được ghi đè."""
    fu._archive_monthly_snapshot(_table(roe=15.0), now=datetime(2026, 8, 1))
    out = fu._archive_monthly_snapshot(_table(roe=99.0), now=datetime(2026, 8, 28))
    assert out is None
    kept = pq.read_table(hist_dir / "fundamentals-2026-08.parquet")
    assert kept.column("roe").to_pylist() == [15.0]


def test_new_month_gets_its_own_file(hist_dir):
    fu._archive_monthly_snapshot(_table(), now=datetime(2026, 8, 13))
    fu._archive_monthly_snapshot(_table(), now=datetime(2026, 9, 2))
    names = sorted(p.name for p in hist_dir.iterdir())
    assert names == ["fundamentals-2026-08.parquet", "fundamentals-2026-09.parquet"]


def test_archive_failure_never_breaks_the_main_update(hist_dir, monkeypatch):
    """Best-effort thật sự: lỗi ghi archive (đĩa đầy, quyền) chỉ in cảnh báo,
    KHÔNG ném — update chính (file fundamentals đang dùng) phải sống."""
    import vnstock_parquet_io as pio

    def _die(*a, **k):
        raise OSError("đĩa đầy")

    monkeypatch.setattr(pio, "write_table_atomic", _die)
    assert fu._archive_monthly_snapshot(_table(), now=datetime(2026, 8, 13)) is None


def test_no_tmp_left_behind(hist_dir):
    fu._archive_monthly_snapshot(_table(), now=datetime(2026, 8, 13))
    assert not [p for p in hist_dir.iterdir() if p.name.endswith(".tmp")]


def test_save_writes_both_current_and_snapshot(tmp_path, monkeypatch):
    """`_save` (đường update thật) phải vừa ghi file hiện hành vừa gọi archive."""
    import pandas as pd
    monkeypatch.setattr(fu, "FUND_PATH", tmp_path / "fundamentals.parquet")
    monkeypatch.setattr(fu, "FUND_HISTORY_DIR", tmp_path / "hist")
    fu._save(pd.DataFrame({"ticker": ["VCB"], "roe": [15.0]}))
    assert (tmp_path / "fundamentals.parquet").exists()
    assert len(list((tmp_path / "hist").iterdir())) == 1
