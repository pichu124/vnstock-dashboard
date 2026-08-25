"""
Lưới cho sổ HIỆU SUẤT auto-heal.

Đo trên máy thật hai đêm liền (24-25/08): **0 bar lành / 3.076 lượt refetch**,
mỗi đêm tiêu trọn ~620s ngân sách. Trước đó 19/08 đo 35/3.844 = 0,9%.

Bài học quy trình đứng sau lưới này: con số đó lẽ ra phải TỰ nổi lên qua badge
doctor, không phải chờ user dán log về rồi Claude ngồi trừ tay. Và ca nguy
hiểm quen thuộc vẫn là **kêu khi chưa đủ mẫu** — một đêm 40 lượt không lành
KHÔNG phải bằng chứng.
"""
from __future__ import annotations

import vnstock_quarantine as q


def _fill(tmp_path, runs):
    for i, (scanned, healed) in enumerate(runs):
        q.record_heal_run(tmp_path,
                          {"scanned": scanned, "refetched_ok": healed,
                           "refetched_fail": scanned - healed, "archived": 0},
                          today=f"2026-08-{i + 1:02d}")


class TestLedger:
    def test_the_two_real_nights_land_at_zero_percent(self, tmp_path):
        _fill(tmp_path, [(1956, 0), (1120, 0)])
        st = q.heal_stats(tmp_path)
        assert st["attempts"] == 3076 and st["healed"] == 0
        assert st["rate"] == 0.0 and st["enough"] is True

    def test_last_run_is_kept_for_the_badge(self, tmp_path):
        _fill(tmp_path, [(1956, 0), (1120, 0)])
        assert q.heal_stats(tmp_path)["last"]["scanned"] == 1120

    def test_empty_ledger_is_safe(self, tmp_path):
        st = q.heal_stats(tmp_path)
        assert st["runs"] == 0 and st["rate"] is None and st["enough"] is False

    def test_corrupt_ledger_is_safe(self, tmp_path):
        p = q.heal_log_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{nope", encoding="utf-8")
        assert q.heal_stats(tmp_path)["runs"] == 0

    def test_log_is_capped(self, tmp_path):
        _fill(tmp_path, [(10, 0)] * (q.HEAL_LOG_MAX + 15))
        assert q.heal_stats(tmp_path)["runs"] == q.HEAL_LOG_MAX

    def test_record_never_raises_when_the_write_fails(self, tmp_path, monkeypatch):
        import vnstock_parquet_io as pio
        monkeypatch.setattr(pio, "write_json_atomic",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        assert q.record_heal_run(tmp_path, {"scanned": 5}) is False

    def test_auto_heal_records_its_own_run(self, tmp_path, monkeypatch):
        # Guard "quên nối": sổ không được ghi thì badge vĩnh viễn im lặng
        import inspect
        assert "record_heal_run" in inspect.getsource(q.auto_heal)


class TestBadgeNeverCriesTooEarly:
    def _doctor(self, tmp_path, monkeypatch):
        import vnstock_doctor as d
        monkeypatch.setattr(d, "_META", tmp_path / "_meta")
        return d

    def test_below_the_sample_floor_stays_ok(self, tmp_path, monkeypatch):
        _fill(tmp_path, [(40, 0)])
        r = self._doctor(tmp_path, monkeypatch).check_autoheal_yield()
        assert r["status"] == "ok" and "chưa đủ mẫu" in r["message"]

    def test_zero_yield_with_enough_samples_warns(self, tmp_path, monkeypatch):
        _fill(tmp_path, [(1956, 0), (1120, 0)])
        r = self._doctor(tmp_path, monkeypatch).check_autoheal_yield()
        assert r["status"] == "warn"
        assert "VNSTOCK_AUTOHEAL_BUDGET_S" in r["fix"]

    def test_some_healing_is_not_a_warning(self, tmp_path, monkeypatch):
        _fill(tmp_path, [(1956, 35), (1120, 10)])
        assert self._doctor(tmp_path, monkeypatch).check_autoheal_yield()["status"] == "ok"

    def test_empty_ledger_is_ok(self, tmp_path, monkeypatch):
        assert self._doctor(tmp_path, monkeypatch).check_autoheal_yield()["status"] == "ok"
