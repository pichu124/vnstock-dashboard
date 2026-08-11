"""Vết quy đổi đơn vị giá → doctor check → badge sidebar (11/08).

Trước đây mục "canh chừng đơn vị giá penny" là NGƯỜI phải nhớ quét
run_daily.log tìm dòng "[rollup] … quy đổi VND". Nay tự động hoá trọn vòng:
`_normalize_units` bắn → ghi vết máy-đọc-được vào
`_meta/unit_normalizations.json` → doctor (pipeline 18:00 chạy sẵn) đọc vết
→ badge sidebar tự warn. Doctrine repo: mọi lớp best-effort TỰ SỬA cần một
doctor check tương ứng — tự sửa xong vẫn cần người liếc chart (ca oan lý
thuyết: chia tách tỉ lệ cực lớn).
"""

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

import vnstock_doctor as vd
import vnstock_rollup as vr


@pytest.fixture()
def _tmp_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "META_DIR", tmp_path)
    monkeypatch.setattr(vd, "_META", tmp_path)
    return tmp_path


def _bars(close: float) -> pd.DataFrame:
    return pd.DataFrame({"open": [close], "high": [close], "low": [close],
                         "close": [close], "volume": [100]})


# ── Phía rollup: ghi vết ─────────────────────────────────────────────────────

def test_normalize_units_writes_machine_readable_trace(_tmp_meta):
    out = vr._normalize_units(_bars(450.0), _bars(0.45), "PENNY")
    assert out["close"].iloc[0] == pytest.approx(0.45)      # vẫn quy đổi như cũ
    data = json.loads((_tmp_meta / "unit_normalizations.json")
                      .read_text(encoding="utf-8"))
    ev = data["events"][-1]
    assert ev["ticker"] == "PENNY"
    assert ev["ratio"] >= 100
    assert "at" in ev and "rows" in ev


def test_no_trace_when_units_are_fine(_tmp_meta):
    vr._normalize_units(_bars(0.46), _bars(0.45), "OK1")
    assert not (_tmp_meta / "unit_normalizations.json").exists()


def test_trace_failure_does_not_kill_rollup(tmp_path, monkeypatch):
    """Ghi vết là best-effort — _meta hỏng (vd là FILE, bài `_live` 06/08)
    thì rollup VẪN phải quy đổi và chạy tiếp, không được chết."""
    blocker = tmp_path / "blocked"
    blocker.write_text("x")                 # FILE chắn chỗ, mkdir sẽ nổ
    monkeypatch.setattr(vr, "META_DIR", blocker)
    out = vr._normalize_units(_bars(450.0), _bars(0.45), "PENNY")
    assert out["close"].iloc[0] == pytest.approx(0.45)


def test_trace_is_bounded(_tmp_meta):
    for i in range(vr._UNIT_LOG_MAX + 7):
        vr._record_unit_normalization(f"T{i}", 1000.0, 1)
    data = json.loads((_tmp_meta / "unit_normalizations.json")
                      .read_text(encoding="utf-8"))
    assert len(data["events"]) == vr._UNIT_LOG_MAX


# ── Phía doctor: đọc vết → badge ─────────────────────────────────────────────

def test_doctor_ok_when_never_fired(_tmp_meta):
    r = vd.check_unit_normalizations()
    assert r["status"] == "ok"


def test_doctor_warns_on_fresh_event(_tmp_meta):
    vr._record_unit_normalization("PENNY", 1000.0, 5)
    r = vd.check_unit_normalizations()
    assert r["status"] == "warn"
    assert "PENNY" in r["message"]          # biết soi chart MÃ NÀO


def test_doctor_ok_when_events_stale(_tmp_meta):
    """Vết cũ hơn 7 ngày coi như đã xem — treo warn vĩnh viễn là alarm
    fatigue, badge kêu mãi thì người ta bỏ qua thật."""
    old = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    (_tmp_meta / "unit_normalizations.json").write_text(
        json.dumps({"events": [{"at": old, "ticker": "OLDPX", "ratio": 1000.0}]}),
        encoding="utf-8")
    r = vd.check_unit_normalizations()
    assert r["status"] == "ok"
    assert "OLDPX" in r["message"]          # vẫn nhắc lần cuối để tra cứu


def test_doctor_broken_timestamp_counts_as_fresh(_tmp_meta):
    """Timestamp hỏng → coi là MỚI (thà soi thừa còn hơn nuốt im lặng)."""
    (_tmp_meta / "unit_normalizations.json").write_text(
        json.dumps({"events": [{"at": "rác", "ticker": "XPX", "ratio": 999.0}]}),
        encoding="utf-8")
    assert vd.check_unit_normalizations()["status"] == "warn"


def test_unit_norm_check_is_registered():
    """Lưới chỉ soi thứ ĐƯỢC KHAI BÁO — viết check mà quên đăng ký vào
    OFFLINE_CHECKS là badge không bao giờ thấy nó."""
    assert vd.check_unit_normalizations in vd.OFFLINE_CHECKS
