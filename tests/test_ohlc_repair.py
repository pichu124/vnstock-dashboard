"""Lưới cho `vnstock_ohlc_repair` — nới low/high cho bar TỰ MÂU THUẪN.

Vì sao tồn tại (số đo 19/08): ~34.000 mục trong `remediation_log.jsonl` bị cách
ly với lý do gốc `low > min(open, close, high)` / `high < max(open, close, low)`.
Bar mâu thuẫn NỘI TẠI ⇒ `refetch` gọi lại cùng nguồn ⇒ nhận cùng bar ⇒ trượt
hợp đồng lần nữa. Đo được: 3.844 mục quét, **35 lành = 0,9%**, tốn 35,9 phút
mỗi đêm = 83% bước sync.

Hai bất biến lưới này giữ, và chúng kéo ngược nhau nên phải canh cả hai:
  1. Bar dở (nới nhỏ) PHẢI được sửa — nếu không thì vòng lãng phí quay lại.
  2. Bar HỎNG (nới lớn) TUYỆT ĐỐI KHÔNG sửa — vẽ ra râu nến không có thật còn
     tệ hơn thiếu một bar.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

import vnstock_ohlc_repair as ohlc


def _df(rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def _bar(day, o, h, l, c):
    return [pd.Timestamp(day), o, h, l, c]


# ── Hàm thuần: sửa gì, không sửa gì ─────────────────────────────────────────

def test_valid_bar_is_returned_untouched():
    df = _df([_bar("2026-08-11", 62.5, 63.3, 61.8, 62.0)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert reps == []
    assert out is df, "không có gì để sửa thì đừng copy"


def test_low_above_open_is_widened_down_to_a_traded_price():
    """`low` nói 62.1 trong khi có lệnh khớp ở 61.8 (close) ⇒ mâu thuẫn nằm ở
    con số low. Giá mới KHÔNG bịa: nó chính là close."""
    df = _df([_bar("2026-08-12", 61.9, 62.5, 62.1, 61.8)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert out["low"].iloc[0] == pytest.approx(61.8)
    assert reps[0]["low"] == [pytest.approx(62.1), pytest.approx(61.8)]
    assert reps[0]["ticker"] == "VNM" and reps[0]["time"] == "2026-08-12"


def test_high_below_close_is_widened_up():
    df = _df([_bar("2026-08-12", 61.0, 61.5, 60.5, 62.0)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert out["high"].iloc[0] == pytest.approx(62.0)
    assert reps[0]["high"] == [pytest.approx(61.5), pytest.approx(62.0)]


def test_both_ends_can_be_widened_in_one_bar():
    df = _df([_bar("2026-08-12", 61.9, 61.0, 62.1, 61.8)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert out["low"].iloc[0] == pytest.approx(61.8)
    assert out["high"].iloc[0] == pytest.approx(61.9)
    assert "low" in reps[0] and "high" in reps[0]


def test_broken_bar_beyond_the_cap_is_left_for_the_contract():
    """Biên độ phiên VN tối đa ±15% (UPCoM). Cần nới 190% thì đây là feed hỏng
    / lẫn đơn vị — sửa là vẽ ra một cây nến râu dài không có thật."""
    df = _df([_bar("2026-08-13", 10.0, 11.0, 30.0, 10.5)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert reps == []
    assert out["low"].iloc[0] == pytest.approx(30.0)   # nguyên vẹn để bị cách ly


def test_cap_boundary_is_inclusive():
    close = 100.0
    low = close * (1 + ohlc.MAX_WIDEN_PCT)             # nới đúng bằng trần
    df = _df([_bar("2026-08-13", close, low, low, close)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert len(reps) == 1


def test_only_the_offending_rows_change():
    df = _df([_bar("2026-08-11", 62.5, 63.3, 61.8, 62.0),
              _bar("2026-08-12", 61.9, 62.5, 62.1, 61.8),
              _bar("2026-08-13", 61.8, 63.0, 61.5, 61.6)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert len(reps) == 1
    assert out.iloc[0].tolist() == df.iloc[0].tolist()
    assert out.iloc[2].tolist() == df.iloc[2].tolist()


def test_rows_with_missing_or_zero_values_are_skipped():
    """Thiếu giá trị thì KHÔNG đoán; giá 0 là bar rác, để hợp đồng xử."""
    df = _df([_bar("2026-08-11", 61.9, None, 62.1, 61.8),
              _bar("2026-08-12", 0.0, 0.0, 5.0, 0.0)])
    out, reps = ohlc.repair_ohlc(df, "VNM")
    assert reps == []


def test_repair_is_idempotent():
    df = _df([_bar("2026-08-12", 61.9, 61.0, 62.1, 61.8)])
    once, _ = ohlc.repair_ohlc(df, "VNM")
    twice, reps2 = ohlc.repair_ohlc(once, "VNM")
    assert reps2 == []
    assert twice is once


def test_empty_or_shapeless_input_is_a_noop():
    assert ohlc.repair_ohlc(None, "X") == (None, [])
    empty = pd.DataFrame()
    assert ohlc.repair_ohlc(empty, "X")[1] == []
    no_cols = pd.DataFrame({"time": [pd.Timestamp("2026-08-11")], "close": [1.0]})
    assert ohlc.repair_ohlc(no_cols, "X")[1] == []


# ── Kill-switch + vết ───────────────────────────────────────────────────────

def test_kill_switch(monkeypatch):
    monkeypatch.delenv("VNSTOCK_OHLC_REPAIR", raising=False)
    assert ohlc.enabled()
    monkeypatch.setenv("VNSTOCK_OHLC_REPAIR", "0")
    assert not ohlc.enabled()


def test_repairs_are_traceable(tmp_path):
    ohlc.record_repairs(tmp_path, [{"ticker": "VNM", "time": "2026-08-12",
                                    "widen_pct": 0.5, "low": [62.1, 61.8]}])
    data = ohlc.load_repairs(tmp_path)
    assert data["total"] == 1
    assert data["events"][0]["ticker"] == "VNM" and "at" in data["events"][0]
    assert not list((tmp_path / "_meta").glob("*.tmp"))


def test_trace_is_capped_but_total_keeps_counting(tmp_path, monkeypatch):
    monkeypatch.setattr(ohlc, "_LOG_MAX", 3)
    for i in range(5):
        ohlc.record_repairs(tmp_path, [{"ticker": f"T{i}", "widen_pct": 0.1}])
    data = ohlc.load_repairs(tmp_path)
    assert len(data["events"]) == 3 and data["total"] == 5
    assert data["events"][-1]["ticker"] == "T4"


def test_recording_never_raises_on_a_bad_path(tmp_path):
    blocked = tmp_path / "khong_phai_thu_muc"
    blocked.write_text("x", encoding="utf-8")
    ohlc.record_repairs(blocked, [{"ticker": "VNM"}])       # không được ném


def test_corrupt_trace_reads_as_empty(tmp_path):
    p = ohlc.log_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("{ hong", encoding="utf-8")
    assert ohlc.load_repairs(tmp_path) == {}


# ── Badge doctor ────────────────────────────────────────────────────────────

def test_doctor_badge_green_when_nothing_repaired(tmp_path, monkeypatch):
    import vnstock_doctor as d
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    assert d.check_ohlc_repairs()["status"] == "ok"


def test_doctor_badge_warns_on_recent_repairs(tmp_path, monkeypatch):
    import vnstock_doctor as d
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    ohlc.record_repairs(tmp_path, [{"ticker": "VNM", "widen_pct": 1.94}])
    out = d.check_ohlc_repairs()
    assert out["status"] == "warn"
    assert "VNM" in out["message"] and "1.94%" in out["message"]


def test_doctor_badge_goes_quiet_once_the_repairs_are_old(tmp_path, monkeypatch):
    """Cảnh báo vĩnh viễn = alarm fatigue; vết cũ chỉ còn là con số tổng."""
    import vnstock_doctor as d
    monkeypatch.setattr(d, "_META", tmp_path / "_meta")
    old = datetime.now() - timedelta(days=60)
    ohlc.record_repairs(tmp_path, [{"ticker": "VNM", "widen_pct": 1.0}], now=old)
    out = d.check_ohlc_repairs()
    assert out["status"] == "ok" and "tổng" in out["message"]


# ── Đường ghi thật ──────────────────────────────────────────────────────────

def test_write_path_repairs_before_the_contract_can_quarantine(tmp_path,
                                                               monkeypatch):
    """Bất biến CỐT LÕI: bar dở phải QUA được hợp đồng, không rơi vào hàng đợi."""
    import vnstock_updater as up

    tdir = tmp_path / "prices" / "ticker=VNM"
    (tdir / "year=2026").mkdir(parents=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp("2026-08-12")],
        "open": [61.9], "high": [61.0], "low": [62.1], "close": [61.8],
        "volume": [1_000_000],
    })
    quarantined = []
    monkeypatch.setattr("vnstock_quarantine.quarantine_dropped",
                        lambda *a, **k: quarantined.append(a))
    up._write_year(tdir, 2026, df)

    out = pd.read_parquet(tdir / "year=2026")
    assert len(out) == 1, "bar bị hợp đồng loại thay vì được nới"
    assert out["low"].iloc[0] == pytest.approx(61.8, abs=1e-4)
    assert out["high"].iloc[0] == pytest.approx(61.9, abs=1e-4)
    assert not quarantined
    assert ohlc.load_repairs(tmp_path)["total"] == 1


def test_write_path_still_quarantines_a_truly_broken_bar(tmp_path, monkeypatch):
    import vnstock_updater as up

    tdir = tmp_path / "prices" / "ticker=VNM"
    (tdir / "year=2026").mkdir(parents=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp("2026-08-13")],
        "open": [10.0], "high": [11.0], "low": [30.0], "close": [10.5],
        "volume": [1_000_000],
    })
    quarantined = []
    monkeypatch.setattr("vnstock_quarantine.quarantine_dropped",
                        lambda *a, **k: quarantined.append(a))
    up._write_year(tdir, 2026, df)
    assert quarantined, "bar hỏng phải vẫn bị cách ly"


def test_kill_switch_restores_the_old_quarantine_behaviour(tmp_path, monkeypatch):
    import vnstock_updater as up

    monkeypatch.setenv("VNSTOCK_OHLC_REPAIR", "0")
    tdir = tmp_path / "prices" / "ticker=VNM"
    (tdir / "year=2026").mkdir(parents=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp("2026-08-12")],
        "open": [61.9], "high": [61.0], "low": [62.1], "close": [61.8],
        "volume": [1_000_000],
    })
    quarantined = []
    monkeypatch.setattr("vnstock_quarantine.quarantine_dropped",
                        lambda *a, **k: quarantined.append(a))
    up._write_year(tdir, 2026, df)
    assert quarantined, "tắt guard thì bar dở phải quay lại đường cách ly"
