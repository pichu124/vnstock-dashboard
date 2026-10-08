"""Ghi nguyên tử — dọn nợ MEDIUM đợt audit 06/08 (làm 12/08).

Audit đã vá đường updater/rollup bằng `vnstock_parquet_io`. Quét lại 12/08
tìm ra hai lỗ CÒN LẠI, và lỗ đầu NẶNG HƠN cả ca đã vá:

* `VnstockWarehouse._write_parquet` dùng `pq.write_to_dataset(...,
  existing_data_behavior="delete_matching")` — XOÁ partition cũ RỒI mới ghi.
  Chết giữa hai bước = partition BIẾN MẤT (không phải hỏng — mất hẳn), và
  `_read_ticker` đọc thư mục rỗng trả DataFrame rỗng → im lặng.
* `_save_meta` dùng `open(w)` — cắt file về 0 trước khi ghi. Chết giữa chừng
  = meta cụt → `_get_last_date` trả None cho MỌI mã → updater tưởng kho
  trống, refetch toàn bộ (hoặc tệ hơn: merge đè lịch sử).

Kèm lưới chặn tái phát cho các file "state của user/kho" — chỗ mất là đau,
khác cache (dựng lại được).
"""

import json

import pandas as pd
import pyarrow as pa
import pytest

import vnstock_parquet_io as pio


# ── write_json_atomic ────────────────────────────────────────────────────────

def test_write_json_atomic_roundtrip(tmp_path):
    p = tmp_path / "sub" / "state.json"
    pio.write_json_atomic({"a": 1, "ticker": "VCB"}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["ticker"] == "VCB"


def test_write_json_atomic_keeps_old_file_when_serialize_fails(tmp_path):
    """Nửa vời là thứ DUY NHẤT không được phép: payload hỏng → file CŨ còn
    nguyên, không bị cắt cụt.

    Dùng tham chiếu VÒNG để ép serialize vỡ — `default=str` (cố ý, cho date)
    nuốt được gần như mọi object lạ nên object thường không làm vỡ được."""
    p = tmp_path / "state.json"
    pio.write_json_atomic({"ok": True}, p)

    loop: dict = {}
    loop["self"] = loop

    with pytest.raises(ValueError):
        pio.write_json_atomic(loop, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": True}
    assert not list(p.parent.glob("*.tmp"))          # dọn rác tạm


def test_write_json_atomic_serializes_dates(tmp_path):
    """`default=str` là CHỦ ĐÍCH: _meta đầy datetime/date/Path."""
    from datetime import date
    p = tmp_path / "d.json"
    pio.write_json_atomic({"day": date(2026, 8, 12)}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["day"] == "2026-08-12"


def test_write_json_atomic_leaves_no_tmp_on_success(tmp_path):
    p = tmp_path / "state.json"
    pio.write_json_atomic({"x": 1}, p)
    assert [f.name for f in p.parent.iterdir()] == ["state.json"]


def test_write_json_atomic_unicode_not_escaped(tmp_path):
    """Output tiếng Việt trong _meta phải đọc được bằng mắt."""
    p = tmp_path / "vn.json"
    pio.write_json_atomic({"nganh": "Ngân hàng"}, p)
    assert "Ngân hàng" in p.read_text(encoding="utf-8")


# ── Warehouse: partition không được biến mất ────────────────────────────────

def _wh(tmp_path):
    from vnstock_warehouse import VnStockWarehouse
    return VnStockWarehouse(str(tmp_path), tier="community")


def _bars(dates, close=10.0):
    """`_write_parquet` nhận df ĐÃ có cột `year` (caller upstream tự thêm)."""
    ts = pd.to_datetime(dates)
    return pd.DataFrame({
        "ticker": ["VCB"] * len(dates),
        "time": ts,
        "open": [close] * len(dates), "high": [close] * len(dates),
        "low": [close] * len(dates), "close": [close] * len(dates),
        "volume": [1000] * len(dates),
        "year": ts.year.astype("int16"),
    })


def test_warehouse_write_merges_history(tmp_path):
    wh = _wh(tmp_path)
    wh._write_parquet(_bars(["2025-03-03", "2025-03-04"]), "VCB")
    wh._write_parquet(_bars(["2025-03-05"], close=11.0), "VCB")
    got = wh._read_ticker("VCB")
    assert len(got) == 3                       # gộp, không đè
    assert set(pd.to_datetime(got["time"]).dt.day) == {3, 4, 5}


def test_warehouse_write_is_atomic_no_delete_then_write(tmp_path, monkeypatch):
    """Lỗi CỐT LÕI: nếu còn xoá-rồi-ghi thì chết giữa 2 bước = mất partition.
    Giả lập chết ĐÚNG lúc ghi → dữ liệu CŨ phải còn nguyên vẹn."""
    wh = _wh(tmp_path)
    wh._write_parquet(_bars(["2025-03-03", "2025-03-04"]), "VCB")
    before = len(wh._read_ticker("VCB"))

    real = pio.write_table_atomic

    def _die(table, out_path, **k):
        raise RuntimeError("máy tắt giữa lúc ghi")

    monkeypatch.setattr(pio, "write_table_atomic", _die)
    with pytest.raises(Exception):
        wh._write_parquet(_bars(["2025-03-05"]), "VCB")
    monkeypatch.setattr(pio, "write_table_atomic", real)

    assert len(wh._read_ticker("VCB")) == before   # KHÔNG mất gì


def test_warehouse_write_spans_years(tmp_path):
    wh = _wh(tmp_path)
    wh._write_parquet(_bars(["2024-12-30", "2025-01-02"]), "VCB")
    got = wh._read_ticker("VCB")
    assert len(got) == 2
    assert {p.name for p in (tmp_path / "prices" / "ticker=VCB").iterdir()} == \
        {"year=2024", "year=2025"}


def test_warehouse_meta_written_atomically(tmp_path):
    wh = _wh(tmp_path)
    wh._meta["VCB"] = {"last_date": "2025-03-04"}
    wh._save_meta()
    assert json.loads(wh.meta_file.read_text(encoding="utf-8"))["VCB"]["last_date"] \
        == "2025-03-04"
    assert not list(wh.meta_file.parent.glob("*.tmp"))


# ── Lưới chặn tái phát ──────────────────────────────────────────────────────

# File giữ STATE của user/kho — mất là đau, khác cache (dựng lại được).
# Thêm điểm ghi state mới → thêm vào đây; lưới chỉ soi thứ ĐƯỢC KHAI BÁO.
_MUST_BE_ATOMIC = [
    ("vnstock_warehouse.py", "kho giá + meta last_date"),
    ("vnstock_brief.py", "brief_agents.json — lựa chọn agent của user"),
    ("vnstock_classifier.py", "kho phân loại 1.652 mã + company profiles"),
    ("vnstock_model_watch.py", "model_status.json + lịch sử probe/danh mục"),
    ("vnstock_rollup.py", "vết quy đổi đơn vị giá"),
    ("dashboard/watchlist_io.py", "watchlist user tự tay dựng"),
    ("vnstock_fundamental_updater.py",
     "fundamentals + snapshot lịch sử point-in-time (mất là không tái tạo được)"),
    ("vnstock_fund_periods.py",
     "sổ kỳ BCTC + sổ đã báo — mất là mất 'kỳ trước' (nguồn chỉ trả kỳ hiện tại)"),
    ("vnstock_mcp_enrich.py",
     "bản chạy bóng connector MCP (U79) — đọc cụt là mất một phiên đối chiếu"),
    # Mở rộng 19/08 sau khi pipeline bị kill lần thứ hai. Chọn theo HẬU QUẢ
    # của một bản cụt, không theo "file nào cũng nên nguyên tử":
    ("vnstock_fix_units.py", "ghi ĐÈ prices.parquet canonical, chạy MỖI ĐÊM "
                             "trong sync — cụt là mất nguyên năm giá"),
    ("vnstock_remediate.py", "ghi đè year-file sau khi bỏ bar hỏng"),
    ("vnstock_wss_backfill.py", "_live/bars_*.parquet — WSS KHÔNG phát lại "
                                "được, cụt là mất vi cấu trúc phiên vĩnh viễn"),
    ("vnstock_freefloat.py", "bản đồ freefloat screener lọc thanh khoản theo"),
    ("vnstock_events.py", "upcoming_events.parquet — guard GDKHQ đọc thẳng "
                          "file này; cụt là brief mất cảnh báo chốt quyền"),
    ("vnstock_runner.py", "screener_results.json (dashboard POLL rồi json.load "
                          "TRẦN) + market_overview.json (brief dựng độ rộng / "
                          "movers / dòng tiền / regime từ đây)"),
    ("vnstock_session_stats.py", "market_session_stats.json — mốc so GTGD"),
    ("run.py", "test_status.json — badge sidebar chặn merge/deploy"),
    ("vnstock_doctor.py", "doctor_status.json — badge sidebar"),
]


@pytest.mark.parametrize("fname,why", _MUST_BE_ATOMIC)
def test_state_writers_stay_atomic(fname, why):
    """Ghi thẳng = cắt file về 0 trước khi chép nội dung mới; chết giữa chừng
    là mất/cụt. Mọi điểm ghi trong các file này phải qua helper nguyên tử
    (write_table_atomic / write_json_atomic) hoặc tự tmp+os.replace."""
    from pathlib import Path
    src = Path(fname).read_text(encoding="utf-8")
    lines = src.split("\n")
    bad = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("#") or "st.write(" in ln:
            continue
        if not any(w in ln for w in ("pq.write_table(", "write_to_dataset(",
                                     "to_parquet(", ".write_text(",
                                     "json.dump(")):
            continue
        ctx = "\n".join(lines[max(0, i - 8):i + 10])
        if any(safe in ctx for safe in ("os.replace", "write_table_atomic",
                                        "write_json_atomic")):
            continue
        bad.append(f"{fname}:{i + 1}: {stripped[:70]}")
    assert not bad, (
        f"Ghi KHÔNG nguyên tử trong file giữ state ({why}):\n  "
        + "\n  ".join(bad))
