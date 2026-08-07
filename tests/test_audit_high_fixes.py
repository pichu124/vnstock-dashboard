"""Tests cho 6 lỗi mức HIGH của đợt audit 06/08/2026.

Mỗi lỗi một nhóm; tất cả đều tái hiện được đường hỏng trước khi vá.
Hermetic: không mạng, không ghi ngoài tmp_path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


# ═══ 1. WSS: baseline accum bị ghi đè = 0 khi tick thiếu cột volume ═══════
# `_pick(...) or 0` gộp "chưa khớp lệnh nào" với "bảng giá thiếu cột volume".
# Ca sau làm baseline = 0 → tick KẾ TIẾP tính delta = accum CẢ PHIÊN → volume
# bar phồng (cùng họ bug 78× trên AAA).

def test_accum_to_delta_baseline_semantics():
    from vnstock_wss import accum_to_delta
    d = "2026-08-06"
    assert accum_to_delta(None, None, 5_000_000, d) == 0.0     # tick đầu
    assert accum_to_delta(1_000, d, 1_500, d) == 500.0          # bình thường
    assert accum_to_delta(1_000, "2026-08-05", 1_500, d) == 0.0  # ngày mới
    assert accum_to_delta(5_000, d, 100, d) == 0.0              # accum lùi
    # ĐÂY là cú phồng nếu baseline lỡ bị ghi 0:
    assert accum_to_delta(0, d, 5_000_000, d) == 5_000_000.0


def test_missing_volume_column_must_not_reset_baseline():
    """Guard nguồn: nhánh xử lý phải phân biệt None với 0 và KHÔNG cập nhật
    baseline khi thiếu số liệu."""
    import inspect

    import vnstock_wss as w
    src = inspect.getsource(w)
    assert "accum_raw" in src, "vẫn dùng `or 0`, không phân biệt thiếu-số-liệu"
    assert "if accum_raw is None" in src


# ═══ 2. WSS: tick không khai delta thì KHÔNG được cộng volume ═════════════
# 3 nguồn tick khác price_board (fallback intraday, index, futures) đặt số
# TÍCH LUỸ vào `volume`; vòng poll ~1s cộng lại mỗi lần → bar phồng.

class _FakeAgg:
    def __init__(self):
        self.calls = []

    def add_tick(self, ticker, t, price, volume):
        self.calls.append((ticker, price, volume))


def _svc_with_fake_agg(tmp_path, monkeypatch):
    import vnstock_wss as w
    monkeypatch.setattr(w, "LIVE_DIR", tmp_path)
    svc = w.VnStockWSS.__new__(w.VnStockWSS)
    svc.aggregator = _FakeAgg()
    svc.last_error = ""
    svc._file_locks = {}
    import threading
    svc._locks_guard = threading.Lock()
    monkeypatch.setattr(w.VnStockWSS, "_get_file_lock",
                        lambda self, t: threading.Lock())
    monkeypatch.setattr(w.VnStockWSS, "_atomic_write_json",
                        lambda self, p, d: None)
    return svc


def test_tick_without_delta_contributes_zero_volume(tmp_path, monkeypatch):
    svc = _svc_with_fake_agg(tmp_path, monkeypatch)

    svc._handle_tick({"ticker": "VNINDEX", "time": "2026-08-06T10:00:00",
                      "price": 1700.0, "volume": 850_000_000})   # accum cả phiên

    assert svc.aggregator.calls[-1][2] == 0.0, \
        "tick không khai `_delta_volume` vẫn bơm volume tích luỹ vào bar"


def test_tick_with_delta_still_counts(tmp_path, monkeypatch):
    svc = _svc_with_fake_agg(tmp_path, monkeypatch)

    svc._handle_tick({"ticker": "FPT", "time": "2026-08-06T10:00:00",
                      "price": 120.0, "volume": 5_000_000,
                      "_delta_volume": 1_200.0})

    assert svc.aggregator.calls[-1][2] == 1_200.0


# ═══ 3. Rollup: mã penny lệch đơn vị 1000× ═══════════════════════════════
# `fix_units` chỉ chạm close > 1000 nên giá thô 300-900 VND (đầy trên UPCOM)
# lọt lưới, vào kho thành 300-900 NGHÌN VND.

def _bars(close: float, n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.date_range("2026-08-06", periods=n, freq="D"),
        "open": [close] * n, "high": [close * 1.01] * n,
        "low": [close * 0.99] * n, "close": [close] * n,
        "volume": [1000] * n,
    })


def test_penny_ticker_units_normalised_against_own_history():
    """Mã penny: kho có 0.85 (nghìn VND), bar WSS trả 850 (VND thô)."""
    from vnstock_rollup import _normalize_units

    out = _normalize_units(_bars(850.0), _bars(0.85), "PENNY")

    assert out["close"].iloc[0] == pytest.approx(0.85)
    assert out["high"].iloc[0] == pytest.approx(0.8585, rel=1e-3)


def test_normal_ticker_units_untouched():
    """Giá đã đúng đơn vị → không được đụng (guard không tự tạo lỗi)."""
    from vnstock_rollup import _normalize_units

    out = _normalize_units(_bars(120.0), _bars(119.0), "FPT")

    assert out["close"].iloc[0] == pytest.approx(120.0)


def test_units_untouched_when_no_history():
    """Mã mới niêm yết chưa có lịch sử → giữ nguyên, để fix_units lo."""
    from vnstock_rollup import _normalize_units

    out = _normalize_units(_bars(850.0), pd.DataFrame(), "NEW")

    assert out["close"].iloc[0] == pytest.approx(850.0)


def test_daily_limit_move_not_mistaken_for_unit_error():
    """Trần biên độ VN là ±15% — phải chắc chắn ngưỡng 100× không bắt nhầm."""
    from vnstock_rollup import _normalize_units

    out = _normalize_units(_bars(11.5), _bars(10.0), "ABC")

    assert out["close"].iloc[0] == pytest.approx(11.5)


# ═══ 4. Guard enforce_vnindex_change đọc cửa sổ từ chuỗi SAI ═════════════
# Nhánh 2 khớp trên `out` (đã bị nhánh 1 đổi độ dài) nhưng đọc ngữ cảnh từ
# `text` gốc → lệch vị trí → bỏ sót, hoặc tệ hơn là đè nhầm số GTGD.

def test_vnindex_guard_reads_context_from_shifted_string():
    import vnstock_brief as vb
    ctx = {"vnindex_tech": {"day_change_pct": 0.31}}
    # nhánh 1 rút "giảm 111,222.333%" → "tăng 0.31%" (lệch 7 ký tự)
    text = ("VNINDEX giảm 111,222.333% so với phiên trước, và chỉ số này "
            "giảm 2.50% so với đầu tuần.")

    out = vb.enforce_vnindex_change(text, ctx)

    assert "tăng 0.31% so với phiên trước" in out          # nhánh 1
    assert "2.50%" not in out, "nhánh 2 bỏ sót vì đọc cửa sổ từ chuỗi cũ"
    assert vb.enforce_vnindex_change(out, ctx) == out       # idempotent


def test_vnindex_guard_still_skips_turnover_clause():
    """Không được đè số GTGD — chống guard tự tạo lỗi (bài 14/07)."""
    import vnstock_brief as vb
    ctx = {"vnindex_tech": {"day_change_pct": 0.31}}
    text = ("VNINDEX giảm 111,222.333% so với phiên trước, GTGD toàn thị "
            "trường giảm 12.00% so với đầu tuần.")

    out = vb.enforce_vnindex_change(text, ctx)

    assert "GTGD toàn thị trường giảm 12.00%" in out


# ═══ 5. Sentiment: tin chưa chấm được không được đóng băng "neutral" ═════

def test_unscored_news_not_cached(monkeypatch, tmp_path):
    """Ladder chết → `score_one` trả ("neutral", None). Ghi vào cache là
    đóng băng VĨNH VIỄN: lần sau hash đã có nên không bao giờ chấm lại."""
    import vnstock_sentiment as snt
    written: list = []

    monkeypatch.setattr(snt, "_get_conn", lambda: _FakeConn(written))
    monkeypatch.setattr(snt, "score_one",
                        lambda item: (snt._item_hash(item), "neutral", None))

    news = [{"ticker": "AAA", "news_title": f"tin {i}", "_date_sort": "2026-08-06"}
            for i in range(4)]
    out = snt.score_news_batch(news, max_workers=1)

    assert written == [], "tin chưa chấm được vẫn bị ghi vào cache"
    assert all(v == "neutral" for v in out.values())      # phiên này vẫn hiển thị


def test_scored_news_still_cached(monkeypatch):
    import vnstock_sentiment as snt
    written: list = []

    monkeypatch.setattr(snt, "_get_conn", lambda: _FakeConn(written))
    monkeypatch.setattr(snt, "score_one",
                        lambda item: (snt._item_hash(item), "positive", "Gemini"))

    snt.score_news_batch(
        [{"ticker": "AAA", "news_title": "tin tốt", "_date_sort": "2026-08-06"}],
        max_workers=1)

    assert len(written) == 1 and written[0][0][3] == "positive"


class _FakeConn:
    """SQLite giả: SELECT trả rỗng, ghi lại mọi executemany."""

    def __init__(self, sink):
        self._sink = sink

    def execute(self, *a, **kw):
        return self

    def fetchall(self):
        return []

    def executemany(self, sql, rows):
        self._sink.append(list(rows))

    def commit(self):
        pass

    def close(self):
        pass


# ═══ 6. Exit code: updater + test đỏ phải chặn được pipeline ═════════════

def test_updater_exit_code_reflects_result():
    """Trước: script LUÔN exit 0 nên cổng `if updater != 0` chỉ bắt crash —
    'chạy sạch' và '500 mã lỗi' ra cùng một mã thoát."""
    import inspect
    import pathlib
    src = pathlib.Path(
        inspect.getfile(__import__("vnstock_rollup"))).parent / "vnstock_updater.py"
    body = src.read_text(encoding="utf-8")
    assert "raise SystemExit(2)" in body     # không mã nào update được
    assert "raise SystemExit(1)" in body     # có mã lỗi → cảnh báo


def test_cmd_sync_treats_updater_warning_as_warning(monkeypatch):
    """Đổi exit code của updater mà quên chỗ này thì 1 mã lỗi = fail cứng cả
    pipeline — hỏng nặng hơn bug ban đầu."""
    import run as runpy
    monkeypatch.setattr(runpy, "_run", lambda cmd: 1)

    rc = runpy.cmd_sync(SimpleNamespace(warehouse="data_warehouse",
                                        no_fix_units=True, no_auto_heal=True))

    assert rc == 1


def test_cmd_sync_hard_fails_on_updater_fatal(monkeypatch):
    import run as runpy
    monkeypatch.setattr(runpy, "_run", lambda cmd: 2)

    rc = runpy.cmd_sync(SimpleNamespace(warehouse="data_warehouse",
                                        no_fix_units=True, no_auto_heal=True))

    assert rc == 2


def test_red_tests_hard_fail_the_pipeline():
    """pytest dùng exit 1 cho 'có test fail', mà trong run.py all số 1 nghĩa
    là 'cảnh báo, chạy tiếp' → pipeline vẫn train + ĐẨY BRIEF bằng code đỏ.
    Trái quy ước repo ('badge đỏ = không merge/deploy')."""
    import inspect

    import run as runpy
    src = inspect.getsource(runpy.cmd_test)
    assert "return 2" in src and "proc.returncode != 0" in src


def test_cmd_all_rejects_unknown_exit_codes(monkeypatch):
    """`rc == 2` cũ để lọt pytest 3/4/5, mã âm khi tiến trình bị signal giết,
    hay bug trả 255 — tất cả thành 'thành công im lặng'."""
    import run as runpy
    for bad in (3, 5, 255, -9):
        monkeypatch.setattr(runpy, "_all_steps",
                            lambda a, _b=bad: [("buoc-loi", lambda args: _b)])
        assert runpy.cmd_all(SimpleNamespace(llm=False)) == 2, f"rc={bad} lọt"

    monkeypatch.setattr(runpy, "_all_steps",
                        lambda a: [("ok", lambda args: 0),
                                   ("canh-bao", lambda args: 1)])
    assert runpy.cmd_all(SimpleNamespace(llm=False)) == 0


# ═══ Lưới chống nhiễm chéo giữa các test module ══════════════════════════

def test_no_repo_module_is_replaced_by_a_mock():
    """`tests/test_dashboard.py` từng đặt `sys.modules["vnstock_wss"] =
    MagicMock()` ở CẤP MODULE — có hiệu lực ngay lúc pytest THU THẬP nên
    nhiễm sang mọi file khác, bất kể thứ tự. Hậu quả: 4 test ở file này đỏ
    khi chạy CẢ SUITE nhưng xanh khi chạy RIÊNG — kiểu lỗi tốn nhiều thời
    gian nhất để lần ra. Lưới này bắt ngay lần sau."""
    import sys
    from unittest.mock import Mock
    mocked = [name for name, mod in list(sys.modules.items())
              if name.startswith("vnstock_") and isinstance(mod, Mock)]
    assert not mocked, f"module thật của repo bị thay bằng mock: {mocked}"
