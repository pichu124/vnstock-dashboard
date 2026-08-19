"""Badge doctor phải THÔI kêu thứ đã được đối chiếu và ra sạch.

Vết 19/08: badge "Quy đổi đơn vị giá" kêu vàng suốt 7 ngày vì guard rollup có
kích hoạt, trong khi `check_unit_continuity` đã soi cả 50 mã và ra **0 mã cần
soi tay**. Bắt người ta kiểm lại thứ vừa kiểm là cách nhanh nhất để họ quen với
màu vàng rồi bỏ qua cả cảnh báo thật — đúng lý lẽ đã dùng khi hạ vách ngoài
lookback xuống ℹ.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import vnstock_doctor as doc


@pytest.fixture
def meta(tmp_path, monkeypatch):
    m = tmp_path / "_meta"
    m.mkdir(parents=True)
    monkeypatch.setattr(doc, "_META", m)
    return m


def _events(m, when: datetime, n: int = 3):
    m.joinpath("unit_normalizations.json").write_text(json.dumps({"events": [
        {"at": when.isoformat(), "ticker": f"T{i}"} for i in range(n)]}),
        encoding="utf-8")


def _stamp(m, when: datetime, suspect=(), scope="trace", scanned=50):
    m.joinpath("unit_continuity_check.json").write_text(json.dumps({
        "checked_at": when.isoformat(timespec="seconds"), "scope": scope,
        "scanned": scanned, "suspect": list(suspect)}), encoding="utf-8")


def test_warns_when_nobody_has_checked(meta):
    _events(meta, datetime.now() - timedelta(hours=2))
    assert doc.check_unit_normalizations()["status"] == "warn"


def test_goes_quiet_after_a_clean_check(meta):
    ev = datetime.now() - timedelta(hours=5)
    _events(meta, ev)
    _stamp(meta, ev + timedelta(hours=1))
    r = doc.check_unit_normalizations()
    assert r["status"] == "ok"
    assert "ĐÃ đối chiếu" in r["message"] and "không mã nào cần soi tay" in r["message"]


def test_a_check_done_BEFORE_the_newest_event_does_not_count(meta):
    """Soi trước sự kiện mới nhất thì nó chưa nhìn thấy thứ vừa xảy ra."""
    ev = datetime.now() - timedelta(hours=1)
    _events(meta, ev)
    _stamp(meta, ev - timedelta(hours=6))
    assert doc.check_unit_normalizations()["status"] == "warn"


def test_check_that_found_something_still_warns(meta):
    ev = datetime.now() - timedelta(hours=3)
    _events(meta, ev)
    _stamp(meta, ev + timedelta(minutes=30), suspect=["VVS"])
    assert doc.check_unit_normalizations()["status"] == "warn"


def test_single_ticker_check_cannot_clear_the_whole_list(meta):
    """Soi vài mã lẻ KHÔNG chứng minh gì về cả danh sách — ghi vào là nói dối
    badge, nên scope 'ticker' phải bị bỏ qua."""
    ev = datetime.now() - timedelta(hours=3)
    _events(meta, ev)
    _stamp(meta, ev + timedelta(minutes=30), scope="ticker", scanned=1)
    assert doc.check_unit_normalizations()["status"] == "warn"


def test_corrupt_stamp_falls_back_to_warning(meta):
    _events(meta, datetime.now() - timedelta(hours=2))
    meta.joinpath("unit_continuity_check.json").write_text("{khong-phai-json",
                                                           encoding="utf-8")
    assert doc.check_unit_normalizations()["status"] == "warn"


def test_tool_writes_the_stamp_for_a_full_sweep(tmp_path, monkeypatch):
    """Đầu kia của hợp đồng: công cụ phải THỰC SỰ ghi vết, nếu không badge
    không bao giờ im (guard quên nối = code chết trông y như code sống)."""
    import sys
    sys.path.insert(0, "scripts")
    import check_unit_continuity as cuc
    res = [{"ticker": "AAA", "status": "clean"},
           {"ticker": "BBB", "status": "suspect"}]
    cuc._write_check_stamp(tmp_path, res, "trace")
    data = json.loads((tmp_path / "_meta" / "unit_continuity_check.json")
                      .read_text(encoding="utf-8"))
    assert data["suspect"] == ["BBB"] and data["scanned"] == 2
    assert data["scope"] == "trace"


def test_tool_refuses_to_stamp_a_single_ticker_run(tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import check_unit_continuity as cuc
    cuc._write_check_stamp(tmp_path, [{"ticker": "AAA", "status": "clean"}],
                           "ticker")
    assert not (tmp_path / "_meta" / "unit_continuity_check.json").exists()
