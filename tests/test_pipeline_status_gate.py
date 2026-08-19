"""Lưới cho cửa `--skip-if-done` — nó quyết định đêm nay có sync hay không.

Vết 19/08: kho laptop được chép lên desktop lúc 17:39, 21 phút trước phát
18:00. `pipeline_status.json` nằm TRONG kho nên đi theo bản chép; cửa cũ chỉ
so ngày + kết quả, KHÔNG so máy, nên desktop sẽ bỏ qua cả sync lẫn rollup, in
"✓ đã chạy hôm nay bởi máy CFA-BINHLD-LT" rồi đi tiếp — kho đứng yên nguyên
đêm mà pipeline vẫn xanh.

Giả định đã chết đứng sau cửa đó: nó sinh ra thời kho nằm trên Dropbox dùng
chung, khi ấy "máy khác đã sync" ĐÚNG là "kho đã mới".
"""
from __future__ import annotations

import json

import pytest

import vnstock_rollup as rl


@pytest.fixture()
def status_file(tmp_path, monkeypatch):
    p = tmp_path / "pipeline_status.json"
    monkeypatch.setattr(rl, "PIPELINE_STATUS_PATH", p)
    monkeypatch.setattr(rl, "get_hostname", lambda: "PICHU")
    monkeypatch.delenv("VNSTOCK_SHARED_WAREHOUSE", raising=False)

    def _write(job: str, **fields):
        p.write_text(json.dumps({job: fields}), encoding="utf-8")

    return _write


def _today() -> str:
    return rl.get_today_vn().isoformat()


def test_same_machine_success_today_is_skipped(status_file):
    status_file("updater", last_success_date=_today(),
                last_result="success", last_machine="PICHU")
    done, _ = rl.is_already_done_today("updater")
    assert done is True


def test_another_machines_success_does_not_skip_this_machine(status_file):
    """Hai kho độc lập từ khi bỏ Dropbox — 'máy khác xong' KHÔNG còn nghĩa là
    'kho máy này đã mới'."""
    status_file("updater", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    done, status = rl.is_already_done_today("updater")
    assert done is False
    assert status["last_machine"] == "CFA-BINHLD-LT"   # vẫn trả về để in ra


def test_rollup_job_uses_the_same_gate(status_file):
    status_file("rollup", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    assert rl.is_already_done_today("rollup")[0] is False


def test_shared_warehouse_flag_restores_the_old_cross_machine_behaviour(
        status_file, monkeypatch):
    """Kho THẬT SỰ dùng chung (mount mạng) thì hành vi cũ mới đúng."""
    status_file("updater", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    monkeypatch.setenv("VNSTOCK_SHARED_WAREHOUSE", "1")
    assert rl.is_already_done_today("updater")[0] is True


def test_missing_machine_field_keeps_the_old_behaviour(status_file):
    """Vết cũ chưa có trường máy — không được biến thành 'luôn chạy lại'."""
    status_file("updater", last_success_date=_today(), last_result="success")
    assert rl.is_already_done_today("updater")[0] is True


def test_stale_date_or_failed_result_never_skips(status_file):
    status_file("updater", last_success_date="2020-01-01",
                last_result="success", last_machine="PICHU")
    assert rl.is_already_done_today("updater")[0] is False
    status_file("updater", last_success_date=_today(),
                last_result="failed", last_machine="PICHU")
    assert rl.is_already_done_today("updater")[0] is False


def test_missing_or_corrupt_status_file_never_skips(tmp_path, monkeypatch):
    p = tmp_path / "khong_ton_tai.json"
    monkeypatch.setattr(rl, "PIPELINE_STATUS_PATH", p)
    assert rl.is_already_done_today("updater")[0] is False
    p.write_text("{ hong", encoding="utf-8")
    assert rl.is_already_done_today("updater")[0] is False
