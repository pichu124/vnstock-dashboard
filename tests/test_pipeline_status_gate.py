"""Lưới cho cửa `--skip-if-done` — nó quyết định đêm nay có sync hay không.

Cửa này đứng trên MỘT giả định về hạ tầng, và giả định đó không đọc được từ
code: kho có dùng CHUNG giữa hai máy hay không.

* Kho DÙNG CHUNG (Dropbox — cấu hình thật của user, xác nhận 19/08): "máy khác
  đã sync hôm nay" ĐÚNG là "kho đã mới" ⇒ bỏ qua là mong muốn. Mặc định.
* Kho RIÊNG từng máy: câu trên thành sai, mà `pipeline_status.json` lại nằm
  TRONG kho ⇒ chép/đồng bộ kho sang máy kia là máy nhận tự bỏ qua cả sync lẫn
  rollup, in "✓ đã chạy hôm nay bởi máy X" rồi đi tiếp — kho đứng yên nguyên
  đêm mà pipeline vẫn XANH. Bật `VNSTOCK_INDEPENDENT_WAREHOUSE=1`.

Lưới canh CẢ HAI chế độ, vì chọn nhầm chế độ là hỏng im lặng ở cả hai chiều.
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
    monkeypatch.delenv("VNSTOCK_INDEPENDENT_WAREHOUSE", raising=False)

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


def test_shared_warehouse_default_skips_when_the_other_machine_did_it(
        status_file):
    """Mặc định = kho dùng chung: máy khác sync xong nghĩa là kho đã mới."""
    status_file("updater", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    done, status = rl.is_already_done_today("updater")
    assert done is True
    assert status["last_machine"] == "CFA-BINHLD-LT"   # vẫn trả về để in ra


def test_independent_warehouse_flag_demands_the_same_machine(
        status_file, monkeypatch):
    """Kho riêng từng máy: 'máy khác xong' KHÔNG còn nghĩa là 'kho này đã mới'.
    Không có cờ này thì đồng bộ kho = máy nhận bỏ qua sync, im lặng."""
    status_file("updater", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    monkeypatch.setenv("VNSTOCK_INDEPENDENT_WAREHOUSE", "1")
    assert rl.is_already_done_today("updater")[0] is False


def test_rollup_job_uses_the_same_gate(status_file, monkeypatch):
    monkeypatch.setenv("VNSTOCK_INDEPENDENT_WAREHOUSE", "1")
    status_file("rollup", last_success_date=_today(),
                last_result="success", last_machine="CFA-BINHLD-LT")
    assert rl.is_already_done_today("rollup")[0] is False


def test_missing_machine_field_keeps_the_old_behaviour(status_file, monkeypatch):
    """Vết cũ chưa có trường máy — không được biến thành 'luôn chạy lại'."""
    monkeypatch.setenv("VNSTOCK_INDEPENDENT_WAREHOUSE", "1")
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
