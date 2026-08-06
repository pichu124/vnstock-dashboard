"""Tests cho vnstock_parquet_io — ghi nguyên tử + lưới bắt file parquet hỏng.

Bối cảnh (audit 06/08/2026, lỗi CRITICAL): updater/rollup ghi thẳng
`pq.write_table` vào prices.parquet → process chết giữa chừng để lại file
cụt → lần sau `except: continue` hiểu thành "chưa có data" → ghi đè cả năm
lịch sử bằng vài dòng hôm nay, im lặng và không bao giờ refetch.

Test ở đây khoá CẢ HAI lớp chống: (1) ghi tmp-rồi-tráo nên file cũ không
bao giờ bị hỏng dở, (2) đọc gặp file hỏng thì cách ly/dừng chứ không im
lặng coi như rỗng. Hermetic hoàn toàn (tmp_path, không mạng).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_parquet_io import (
    CANONICAL_NAME,
    CorruptWarehouseFile,
    read_year_frames,
    write_table_atomic,
)


def _table(days: int = 3) -> "pa.Table":
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-02", periods=days, freq="D"),
        "close": [10.0 + i for i in range(days)],
    })
    return pa.Table.from_pandas(df, preserve_index=False)


def _write_canonical(year_dir: Path, days: int = 3) -> Path:
    year_dir.mkdir(parents=True, exist_ok=True)
    out = year_dir / CANONICAL_NAME
    pq.write_table(_table(days), str(out))
    return out


# ── Ghi nguyên tử ──────────────────────────────────────────────────────────

def test_write_atomic_creates_file_and_leaves_no_tmp(tmp_path):
    out = tmp_path / "year=2026" / CANONICAL_NAME

    write_table_atomic(_table(3), out)

    assert len(pq.read_table(str(out)).to_pandas()) == 3
    assert list(out.parent.glob("*.tmp")) == []          # dọn sạch dấu vết


def test_write_atomic_keeps_old_file_intact_when_write_fails(tmp_path, monkeypatch):
    """Tính chất SỐNG CÒN: ghi hỏng giữa chừng thì file CŨ phải nguyên vẹn.
    Với pq.write_table ghi thẳng, file cũ đã bị cắt về 0 byte từ trước khi
    lỗi xảy ra — đó chính là đường mất data."""
    year_dir = tmp_path / "year=2026"
    out = _write_canonical(year_dir, days=250)           # "cả năm lịch sử"

    def _boom(table, where, **kw):                       # mô phỏng bị kill
        Path(where).write_bytes(b"PAR1-cut-off")         # tmp dở dang
        raise RuntimeError("process killed mid-write")

    monkeypatch.setattr(pq, "write_table", _boom)
    with pytest.raises(RuntimeError):
        write_table_atomic(_table(1), out)

    assert len(pq.read_table(str(out)).to_pandas()) == 250   # còn nguyên
    assert list(year_dir.glob("*.tmp")) == []                # tmp đã dọn


def test_write_atomic_tmp_name_never_matches_parquet_glob(tmp_path, monkeypatch):
    """Tên tạm không được kết thúc .parquet — nếu không, tmp còn sót lại sẽ bị
    read_year_frames nhặt nhầm thành dữ liệu."""
    seen = {}

    def _spy(table, where, **kw):
        seen["path"] = Path(where)
        pq_orig(table, where, **kw)

    pq_orig = pq.write_table
    monkeypatch.setattr(pq, "write_table", _spy)
    write_table_atomic(_table(1), tmp_path / CANONICAL_NAME)

    assert seen["path"].suffix == ".tmp"
    assert not seen["path"].name.endswith(".parquet")


# ── Đọc: file hỏng không còn bị nuốt im lặng ───────────────────────────────

def test_read_frames_normal_merges_all_files(tmp_path):
    year_dir = tmp_path / "year=2026"
    _write_canonical(year_dir, days=3)
    pq.write_table(_table(2), str(year_dir / "prices (conflicted copy).parquet"))

    frames = read_year_frames(year_dir, strict=False)

    assert len(frames) == 2                              # gộp cả bản Dropbox
    assert all("time" in f.columns for f in frames)


def test_read_frames_non_strict_quarantines_corrupt_canonical(tmp_path):
    """Updater: cách ly + đi tiếp (nó tự refetch nguyên năm từ API)."""
    year_dir = tmp_path / "year=2026"
    out = _write_canonical(year_dir)
    out.write_bytes(b"not a parquet file at all")

    frames = read_year_frames(year_dir, strict=False)    # KHÔNG raise

    assert frames == []
    assert not out.exists()                              # đã bị đổi tên
    assert len(list(year_dir.glob("*.corrupt-*"))) == 1


def test_read_frames_strict_raises_and_keeps_tripwire(tmp_path):
    """Rollup: raise + GIỮ NGUYÊN file hỏng làm dây bẫy. Đổi tên ở đây sẽ
    khiến lần rollup kế tiếp thấy thư mục rỗng rồi ghi đè file 1 dòng —
    đúng thứ đang muốn tránh."""
    year_dir = tmp_path / "year=2026"
    out = _write_canonical(year_dir)
    out.write_bytes(b"corrupted")

    with pytest.raises(CorruptWarehouseFile):
        read_year_frames(year_dir, strict=True)

    assert out.exists()                                  # bẫy vẫn nằm đó
    assert list(year_dir.glob("*.corrupt-*")) == []


def test_read_frames_strict_still_quarantines_non_canonical(tmp_path):
    """Bản conflicted copy hỏng không phải nguồn chân lý → cách ly, không raise."""
    year_dir = tmp_path / "year=2026"
    _write_canonical(year_dir, days=4)
    dup = year_dir / "prices (conflicted copy).parquet"
    dup.write_bytes(b"corrupted")

    frames = read_year_frames(year_dir, strict=True)

    assert len(frames) == 1 and len(frames[0]) == 4      # canonical vẫn dùng
    assert not dup.exists()
    assert len(list(year_dir.glob("*.corrupt-*"))) == 1


def test_read_frames_missing_dir_is_empty(tmp_path):
    assert read_year_frames(tmp_path / "year=1999", strict=True) == []


# ── Tích hợp: tái hiện ĐÚNG đường mất data qua rollup thật ─────────────────

def test_rollup_refuses_to_overwrite_corrupt_year(tmp_path, monkeypatch, capsys):
    """Kịch bản CRITICAL của audit, end-to-end qua `rollup_bars_file`:
    prices.parquet của FPT hỏng (bị kill giữa lúc ghi đêm trước), rollup chỉ
    có bar HÔM NAY. Trước fix: đọc lỗi → nuốt → tưởng 'chưa có data' → ghi đè
    canonical bằng đúng 1 dòng → cả năm lịch sử bốc hơi, và vì file mới mang
    ngày hôm nay nên updater không bao giờ refetch. Sau fix: rollup BỎ QUA
    ticker-year đó, file hỏng giữ nguyên làm dây bẫy."""
    import vnstock_rollup as rl

    prices_dir = tmp_path / "prices"
    year_dir = prices_dir / "ticker=FPT" / "year=2026"
    canonical = _write_canonical(year_dir, days=250)      # cả năm lịch sử
    corrupt_bytes = b"PAR1-truncated-mid-write"
    canonical.write_bytes(corrupt_bytes)                  # ← bị kill đêm trước
    monkeypatch.setattr(rl, "PRICES_DIR", prices_dir)

    bars = pd.DataFrame({
        "ticker": ["FPT"] * 2,
        "time": pd.to_datetime(["2026-08-06 09:15", "2026-08-06 14:30"]),
        "open": [100.0, 101.0], "high": [102.0, 103.0],
        "low": [99.0, 100.0], "close": [101.0, 102.5],
        "volume": [1000, 2000],
    })
    bars_path = tmp_path / "bars_2026-08-06.parquet"
    bars.to_parquet(bars_path, index=False)

    stats = rl.rollup_bars_file(bars_path)

    # File hỏng KHÔNG bị ghi đè (trước fix: thành file hợp lệ 1 dòng)
    assert canonical.read_bytes() == corrupt_bytes
    assert stats["errors"] == 1 and stats["tickers_updated"] == 0
    assert "Bỏ qua FPT" in capsys.readouterr().out       # có dấu vết chẩn đoán


def test_rollup_still_merges_healthy_year(tmp_path, monkeypatch):
    """Đường bình thường không bị lưới mới chặn nhầm."""
    import vnstock_rollup as rl

    prices_dir = tmp_path / "prices"
    year_dir = prices_dir / "ticker=FPT" / "year=2026"
    year_dir.mkdir(parents=True)
    pd.DataFrame({
        "time": pd.to_datetime(["2026-08-05"]),
        "open": [99.0], "high": [100.0], "low": [98.0], "close": [99.5],
        "volume": [5000],
    }).to_parquet(year_dir / CANONICAL_NAME, index=False)
    monkeypatch.setattr(rl, "PRICES_DIR", prices_dir)

    bars = pd.DataFrame({
        "ticker": ["FPT"], "time": pd.to_datetime(["2026-08-06 09:15"]),
        "open": [100.0], "high": [102.0], "low": [99.0], "close": [101.0],
        "volume": [1000],
    })
    bars_path = tmp_path / "bars_2026-08-06.parquet"
    bars.to_parquet(bars_path, index=False)

    stats = rl.rollup_bars_file(bars_path)

    out = pd.read_parquet(year_dir / CANONICAL_NAME)
    assert stats["errors"] == 0 and stats["tickers_updated"] == 1
    assert [str(d) for d in pd.to_datetime(out["time"]).dt.date] == \
        ["2026-08-05", "2026-08-06"]                     # lịch sử + bar mới
