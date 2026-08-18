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


# ── Badge phải nói ĐÚNG những gì nó biết (sửa 18/08) ─────────────────────────
#
# Ba lỗi "nói quá" khiến user đi soi 5 chart oan hôm 18/08: badge in ratio như
# thể đó là độ tin cậy của phép quy đổi, in 5 mã cuối theo VẦN như thể đó là 5
# ca nặng nhất, và in số đếm đã chạm trần log như thể đó là số thật.

def test_badge_does_not_print_ratio_as_if_it_were_a_verdict(_tmp_meta):
    """ratio = giá / TRUNG VỊ YTD của chính mã (rollup:291) — nó nói mã đang ở
    đâu so với trung vị năm, KHÔNG nói phép quy đổi đúng hay sai. In kèm mã là
    mời người đọc kết luận sai: "764× lệch xa 1000 nên chắc là quy đổi oan"."""
    vr._record_unit_normalization("YEG", 764.1, 1)
    msg = vd.check_unit_normalizations()["message"]
    assert "YEG" in msg
    assert "764" not in msg and "×" not in msg


def test_badge_counts_distinct_tickers_and_flags_alphabetical_tail(_tmp_meta):
    """6 mã → badge chỉ in được 5; phải nói rõ tổng số mã VÀ rằng 5 cái tên đó
    là đuôi bảng chữ cái (rollup duyệt `groupby("ticker")` = alphabet)."""
    for tk in ("AAA", "BBB", "CCC", "WSS", "XPH", "YEG"):
        vr._record_unit_normalization(tk, 1000.0, 1)
    msg = vd.check_unit_normalizations()["message"]
    assert "6 mã" in msg
    assert "cuối theo vần" in msg
    assert "AAA" not in msg                 # đúng là đuôi vần, không phải tất cả


def test_badge_says_at_least_when_the_trace_log_is_full(_tmp_meta):
    """Log giữ tối đa `_UNIT_LOG_MAX` vết — đầy rồi thì số đếm là SÀN. In "50"
    trần trụi khiến người đọc tưởng đã đếm đủ (ca thật 17/08: đúng 50)."""
    for i in range(vr._UNIT_LOG_MAX + 10):
        vr._record_unit_normalization(f"T{i:03d}", 1000.0, 1)
    msg = vd.check_unit_normalizations()["message"]
    assert f"≥{vr._UNIT_LOG_MAX}" in msg
    assert "log đầy" in msg


def test_badge_omits_the_hedges_when_they_do_not_apply(_tmp_meta):
    """Ít mã + log chưa đầy → KHÔNG chú thích thừa. Cảnh báo nào cũng kèm
    ngoặc đơn thì người đọc thôi đọc ngoặc đơn."""
    vr._record_unit_normalization("WSS", 937.5, 1)
    msg = vd.check_unit_normalizations()["message"]
    assert "cuối theo vần" not in msg and "log đầy" not in msg and "≥" not in msg


def test_badge_fix_hint_points_at_the_tool_not_at_eyeballs(_tmp_meta):
    """Việc "soi chart bằng mắt rồi báo Claude" nay có công cụ chạy được —
    gợi ý sửa phải trỏ vào đó, nếu không tool viết ra chẳng ai biết."""
    vr._record_unit_normalization("WSS", 937.5, 1)
    assert "check_unit_continuity" in vd.check_unit_normalizations()["fix"]


def test_badge_reads_log_cap_from_rollup_not_a_local_copy():
    """Hai bản sao hằng số là thứ trôi lúc nào không hay — đọc từ nguồn."""
    assert vd._rollup_log_cap() == vr._UNIT_LOG_MAX


def test_unit_norm_check_is_registered():
    """Lưới chỉ soi thứ ĐƯỢC KHAI BÁO — viết check mà quên đăng ký vào
    OFFLINE_CHECKS là badge không bao giờ thấy nó."""
    assert vd.check_unit_normalizations in vd.OFFLINE_CHECKS
