"""Thanh trạng thái chung (giao diện P2): phiên giao dịch, gộp badge, đổi chỉ số."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from dashboard.status_strip import (fmt_signed, index_change, session_phase,
                                    system_items, worst_level)

FRI = datetime(2026, 10, 30)


@pytest.mark.parametrize("hm,key", [
    ((8, 59), "pre"), ((9, 0), "open"), ((11, 29), "open"), ((11, 30), "lunch"),
    ((13, 0), "open"), ((14, 29), "open"), ((14, 30), "atc"), ((14, 45), "pt"),
    ((15, 0), "closed"), ((21, 0), "closed"),
])
def test_session_phase_follows_hose_hours(hm, key):
    assert session_phase(FRI.replace(hour=hm[0], minute=hm[1]))[0] == key


def test_weekend_is_closed_all_day():
    assert session_phase(datetime(2026, 10, 31, 10, 0))[0] == "weekend"
    assert session_phase(datetime(2026, 11, 1, 10, 0))[0] == "weekend"


@pytest.mark.parametrize("levels,want", [
    (["ok", "ok", "ok"], "ok"), (["ok", "warn", "off"], "warn"),
    (["warn", "error", "ok"], "error"), ([], "off"), (["lạ"], "off"), (["off", "ok"], "ok"),
])
def test_worst_level(levels, want):
    assert worst_level(levels) == want


def _write(meta, name, obj):
    meta.mkdir(parents=True, exist_ok=True)
    (meta / name).write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def test_missing_files_are_off_not_ok(tmp_path):
    items = system_items(tmp_path, FRI)
    assert [i["level"] for i in items] == ["off", "off", "off"]
    assert worst_level(i["level"] for i in items) == "off"


def test_failed_tests_make_the_dot_red(tmp_path):
    """Badge tests đỏ = KHÔNG merge/deploy — gộp 3 badge không được làm mất màu đỏ."""
    _write(tmp_path, "test_status.json", {"passed": 10, "failed": 1, "errors": 0, "mode": "fast",
                                          "ran_at": "2026-10-30T08:00:00", "elapsed_s": 50})
    _write(tmp_path, "doctor_status.json", {"worst": "ok", "counts": {"ok": 20}})
    _write(tmp_path, "model_status.json", {"level": "green", "probe": {"ok": 5}})
    items = system_items(tmp_path, FRI.replace(hour=12))
    assert items[0]["level"] == "error" and "1 fail" in items[0]["text"]
    assert worst_level(i["level"] for i in items) == "error"


def test_corrupt_file_says_so_and_warns(tmp_path):
    """Badge biến mất khi file hỏng = user tưởng ổn (vết test_unreadable_sidebar_badge_says_so)."""
    _write(tmp_path, "doctor_status.json", "{hỏng")
    items = system_items(tmp_path, FRI)
    doc = next(i for i in items if i["name"] == "Nguồn dữ liệu")
    assert doc["level"] == "warn" and "không đọc được doctor_status.json" in doc["text"]


def test_model_levels_map(tmp_path):
    _write(tmp_path, "model_status.json", {"level": "red", "probe": {"ok": 3, "fail": 2},
                                           "catalog": {"gone_in_use": ["x"]}})
    m = system_items(tmp_path, FRI)[2]
    assert m["level"] == "error" and "2 lỗi" in m["text"] and "1 đang dùng bị gỡ" in m["text"]


def test_index_change():
    close, chg, pct = index_change([1755.61, 1741.62])
    assert close == 1741.62 and chg == pytest.approx(-13.99) and pct == pytest.approx(-0.797, abs=1e-3)
    assert index_change([1.0]) is None
    assert index_change([0.0, 1.0]) is None
    assert index_change([float("nan"), 1.0, 2.0])[0] == 2.0


def test_fmt_signed_uses_en_format():
    assert fmt_signed(-13.987) == "-13.99"
    assert fmt_signed(1234.5) == "+1,234.50"
