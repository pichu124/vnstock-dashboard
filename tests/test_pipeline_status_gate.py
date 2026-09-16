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
    # Ghim đồng hồ cho CẢ FILE (16/09): cửa nay so PHIÊN PHỦ nên "hôm nay" của
    # marker và `now` mặc định của cửa phải cùng một thứ 3 SAU 15:05 — không
    # thì test đỏ mỗi sáng ngày làm việc và cả cuối tuần (review 16/09 bắt).
    from datetime import datetime as _pdt
    monkeypatch.setattr(rl, "get_today_vn", lambda: rl.date(2026, 9, 15))
    monkeypatch.setattr(rl, "get_now_vn", lambda: _pdt(2026, 9, 15, 19, 0))

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


# ── #12 (14/09): marker updater đêm fallback KBS không được câm ─────────────
def _updater_mod():
    import vnstock_updater as vu
    return vu


def test_partial_run_is_recorded_but_never_counts_as_done(status_file):
    """Đêm 14/09: VCI timeout, 1.524 mã vẫn vào kho qua KBS + 181 lỗi, marker
    đứng ở 11/09 vì bản cũ chỉ ghi khi lỗi = 0 ⇒ doctor đọc thành "updater
    không chạy". Nay ghi `partial` kèm số — nhưng KHÔNG đụng last_success_date
    nên cửa --skip-if-done vẫn không coi lượt hụt là xong."""
    vu = _updater_mod()
    status_file("updater", last_success_date="2026-09-11", last_result="success",
                last_machine="PICHU", tickers_updated=1613)
    upd = vu.updater_status_update(
        {"error": 181, "updated": 1524, "up_to_date": 15, "fallback": 1245},
        today=_today(), now="2026-09-14T21:55:00", machine="PICHU")
    assert upd["last_result"] == "partial"
    assert "last_success_date" not in upd and upd["last_partial_date"] == _today()
    assert (upd["errors"], upd["fallback"], upd["tickers_updated"]) == (181, 1245, 1524)
    rl.write_pipeline_status("updater", upd)
    st = rl.read_pipeline_status()["updater"]
    assert st["last_success_date"] == "2026-09-11"      # giữ nguyên
    assert st["last_result"] == "partial" and st["errors"] == 181
    done, _ = rl.is_already_done_today("updater")
    assert done is False


def test_clean_run_marks_success_with_today_and_zero_errors(status_file):
    vu = _updater_mod()
    upd = vu.updater_status_update(
        {"error": 0, "updated": 1613, "up_to_date": 89, "fallback": 0},
        today=_today(), now=f"{_today()}T20:19:00", machine="PICHU")
    assert upd["last_result"] == "success" and upd["last_success_date"] == _today()
    assert upd["errors"] == 0 and "last_partial_date" not in upd
    status_file("updater", last_success_date="2026-09-14", last_result="partial",
                errors=181)
    rl.write_pipeline_status("updater", upd)
    from datetime import datetime as _dt2, time as _time2
    done, st = rl.is_already_done_today(
        "updater", now=_dt2.combine(rl.get_today_vn(), _time2(21, 0)))
    assert done is True and st["errors"] == 0


# ── 16/09: cửa so PHIÊN PHỦ, không so ngày lịch ─────────────────────────────
# Hai lỗ hổng đường chạy bù (StartWhenAvailable): (1) máy tắt 18:00 T2, bật
# 08:20 T3 ⇒ sync bù lấy bar tới T2 nhưng đóng dấu NGÀY T3 ⇒ task 18:00 T3
# "✓ đã chạy hôm nay" bỏ qua sync, bar T3 chờ tới T4, brief chiều T3 dựng trên
# bar T2. (2) chạy bù T7 ⇒ updater bỏ qua cuối tuần (không --force) mà brief
# T6 vẫn đẩy (luật 15/08) trên bar T5. Lưới: marker ghi `covered_session`,
# cửa so nó với phiên mà lượt hiện tại sẽ phủ; run.py sync thêm --force T7/CN.
from datetime import datetime as _dt, time as _time


def test_session_covered_at_cutoff_and_weekend():
    assert rl.session_covered_at(_dt(2026, 9, 15, 15, 4)) == rl.date(2026, 9, 14)   # T3 trước chốt
    assert rl.session_covered_at(_dt(2026, 9, 15, 15, 5)) == rl.date(2026, 9, 15)   # đúng giờ chốt
    assert rl.session_covered_at(_dt(2026, 9, 15, 19, 5)) == rl.date(2026, 9, 15)
    assert rl.session_covered_at(_dt(2026, 9, 14, 8, 20)) == rl.date(2026, 9, 11)   # T2 sáng → T6
    assert rl.session_covered_at(_dt(2026, 9, 19, 10, 0)) == rl.date(2026, 9, 18)   # T7 → T6
    assert rl.session_covered_at(_dt(2026, 9, 20, 23, 0)) == rl.date(2026, 9, 18)   # CN → T6


def test_session_close_cutoff_matches_brief_constant():
    import vnstock_brief as vb
    assert rl._SESSION_CLOSE_CUTOFF == vb.SESSION_CLOSE_CUTOFF == _time(15, 5)


def _now_today(hh, mm=0):
    return _dt.combine(rl.get_today_vn(), _time(hh, mm))


def test_morning_catchup_does_not_block_the_evening_sync(status_file):
    """Timeline (1): marker của lượt chạy bù 08:20 hôm nay phủ phiên TRƯỚC ⇒
    lượt 18:00 hôm nay KHÔNG được bỏ qua; lượt bù thứ hai lúc 09:00 thì có."""
    vu = _updater_mod()
    today = rl.get_today_vn()                      # thứ 3 15/09 (ghim ở fixture)
    upd = vu.updater_status_update(
        {"error": 0, "updated": 1613, "up_to_date": 89, "fallback": 0},
        today=today.isoformat(), now=f"{today.isoformat()}T08:20:00", machine="PICHU")
    assert upd["covered_session"] == rl.session_covered_at(_now_today(8, 20)).isoformat()
    assert upd["covered_session"] != today.isoformat()
    rl.write_pipeline_status("updater", upd)
    assert rl.is_already_done_today("updater", now=_now_today(18, 0))[0] is False
    assert rl.is_already_done_today("updater", now=_now_today(9, 0))[0] is True


@pytest.mark.parametrize("day", [rl.date(2026, 9, 15), rl.date(2026, 9, 19)])   # T3 và T7
def test_evening_marker_still_skips_a_second_run_the_same_evening(status_file, day):
    """Lượt 19:05 rồi lượt 21:00 cùng ngày phủ cùng phiên (T7: cả hai là T6)
    ⇒ lượt sau bỏ qua — ngày nào cũng vậy."""
    vu = _updater_mod()
    upd = vu.updater_status_update(
        {"error": 0, "updated": 10, "up_to_date": 0, "fallback": 0},
        today=day.isoformat(), now=f"{day.isoformat()}T19:05:12", machine="PICHU")
    rl.write_pipeline_status("updater", upd)
    assert rl.is_already_done_today("updater", now=_dt.combine(day, _time(21, 0)))[0] is True


def test_legacy_marker_without_covered_session_is_read_by_run_time(status_file):
    """Marker trước 16/09 chỉ có ngày lịch — suy phiên phủ từ last_run_at."""
    today = rl.get_today_vn()
    status_file("updater", last_success_date=today.isoformat(),
                last_run_at=f"{today.isoformat()}T08:20:00",
                last_result="success", last_machine="PICHU")
    assert rl.is_already_done_today("updater", now=_now_today(18, 0))[0] is False
    assert rl.is_already_done_today("updater", now=_now_today(9, 0))[0] is True
    # không có cả last_run_at ⇒ giữ hành vi cũ (ngày lịch)
    status_file("updater", last_success_date=today.isoformat(),
                last_result="success", last_machine="PICHU")
    assert rl.is_already_done_today("updater", now=_now_today(18, 0))[0] is True


def test_weekend_catchup_covers_friday_and_sunday_skips(status_file):
    """Timeline (2): chạy bù T7 10:00 (với --force) phủ T6 ⇒ CN bỏ qua, T2
    18:00 chạy lại (phủ T2)."""
    vu = _updater_mod()
    upd = vu.updater_status_update(
        {"error": 0, "updated": 1613, "up_to_date": 89, "fallback": 0},
        today="2026-09-19", now="2026-09-19T10:00:00", machine="PICHU")
    assert upd["covered_session"] == "2026-09-18"
    rl.write_pipeline_status("updater", upd)
    assert rl.is_already_done_today("updater", now=_dt(2026, 9, 20, 10, 0))[0] is True
    assert rl.is_already_done_today("updater", now=_dt(2026, 9, 21, 8, 0))[0] is True
    assert rl.is_already_done_today("updater", now=_dt(2026, 9, 21, 18, 0))[0] is False


def test_rollup_manual_date_marker_does_not_hide_tonights_rollup(status_file):
    """Marker rollup ghi last_success_date = NGÀY MỤC TIÊU (đã là phiên phủ);
    `--date` tay 10/09 chạy tối 15/09 không được làm rollup tối 15/09 bỏ qua."""
    status_file("rollup", last_success_date="2026-09-10",
                last_run_at="2026-09-15T20:00:00", last_result="success",
                last_machine="PICHU")
    assert rl.is_already_done_today("rollup", now=_dt(2026, 9, 15, 20, 30))[0] is False
    status_file("rollup", last_success_date="2026-09-15", covered_session="2026-09-15",
                last_run_at="2026-09-15T20:00:00", last_result="success",
                last_machine="PICHU")
    assert rl.is_already_done_today("rollup", now=_dt(2026, 9, 15, 20, 30))[0] is True


def test_covered_session_uses_the_start_time_and_survives_bad_input(capsys):
    """Lượt vắt qua 15:05 (bắt đầu 13:30, xong 15:10) đã fetch bar dở dang của
    phiên hôm nay ở những mã đầu ⇒ phiên phủ tính theo giờ BẮT ĐẦU. `now` rác
    ⇒ về ngày lịch nhưng phải NÓI ra (run_daily.log), không câm."""
    vu = _updater_mod()
    st = {"error": 0, "updated": 1, "up_to_date": 0, "fallback": 0}
    upd = vu.updater_status_update(st, today="2026-09-15", now="2026-09-15T15:10:00",
                                   machine="PICHU", started="2026-09-15T13:30:00")
    assert upd["covered_session"] == "2026-09-14" and upd["last_run_at"] == "2026-09-15T15:10:00"
    upd = vu.updater_status_update(st, today="2026-09-15", now="2026-09-15T15:10:00",
                                   machine="PICHU")
    assert upd["covered_session"] == "2026-09-15"          # không có started ⇒ now
    upd = vu.updater_status_update(st, today="2026-09-15", now="rác", machine="PICHU")
    assert upd["covered_session"] == "2026-09-15"
    assert "covered_session: về ngày lịch" in capsys.readouterr().out


def test_session_covered_at_accepts_tz_aware_and_now_vn_is_naive():
    from datetime import timezone
    assert rl.session_covered_at(_dt(2026, 9, 15, 8, 4, tzinfo=timezone.utc)) == rl.date(2026, 9, 14)
    assert rl.session_covered_at(_dt(2026, 9, 15, 8, 5, tzinfo=timezone.utc)) == rl.date(2026, 9, 15)
    assert rl.get_now_vn().tzinfo is None


def test_rollup_main_targets_the_covered_session_and_stamps_it(tmp_path, monkeypatch):
    """Chạy bù 08:20 thứ 3 phải cuộn `bars_<thứ 2>` (trước đây nhắm bars_<hôm
    nay> không tồn tại ⇒ bar 1m hôm qua KHÔNG BAO GIỜ được cuộn) và marker ghi
    covered_session = phiên đó."""
    import sys
    calls = {}
    monkeypatch.setattr(rl, "PIPELINE_STATUS_PATH", tmp_path / "pipeline_status.json")
    monkeypatch.setattr(rl, "LIVE_DIR", tmp_path / "_live")
    monkeypatch.setattr(rl, "get_now_vn", lambda: _dt(2026, 9, 15, 8, 20))
    monkeypatch.setattr(rl, "get_hostname", lambda: "PICHU")
    monkeypatch.setattr(rl.time, "sleep", lambda s: None)           # jitter 0–30s
    monkeypatch.setattr(rl, "rollup_bars_file", lambda path, dry_run=False: (
        calls.setdefault("bars", path),
        {"tickers_updated": 3, "rows_merged": 3, "skipped": 0, "skipped_tickers": [],
         "errors": 0, "already_archived": False})[1])
    monkeypatch.setattr(rl, "archive_bars_file", lambda path, dry_run=False: True)
    monkeypatch.setattr(rl, "cleanup_archive", lambda days=30, dry_run=False: 0)
    monkeypatch.setattr(sys, "argv", ["vnstock_rollup.py", "--skip-if-done"])
    assert rl.main() == 0
    assert calls["bars"].name == "bars_2026-09-14.parquet"
    st = rl.read_pipeline_status()["rollup"]
    assert st["covered_session"] == "2026-09-14" == st["last_success_date"]
    # lượt 18:00 cùng ngày (phủ thứ 3) KHÔNG bị marker này chặn
    assert rl.is_already_done_today("rollup", now=_dt(2026, 9, 15, 18, 0))[0] is False
    assert rl.is_already_done_today("rollup", now=_dt(2026, 9, 15, 9, 0))[0] is True
