"""Doctor phải nói ngay khi có cờ môi trường đang TẮT một phần pipeline.

Vết 19/08: cả buổi truy "vì sao brief không gửi", mà `VNSTOCK_PIPELINE_BRIEF=0`
là một trong bốn nghi phạm — và doctor, thứ sinh ra để trả lời đúng loại câu
hỏi này, lại mù hoàn toàn với nhóm cờ đó (chỉ soi 6 cờ tắt của nguồn vĩ mô).
Đường lây đã vấp: một dòng trong `.env` là đủ, vì các bước chạy in-process
(`cmd_news`, `cmd_doctor`) đều load_dotenv vào os.environ trước bước brief.
"""
from __future__ import annotations

import pytest

import vnstock_doctor as doc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for k in doc._DANGEROUS_SWITCHES:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(doc, "_REPO", tmp_path)     # .env giả, không đụng thật
    return tmp_path


def test_quiet_when_nothing_is_switched_off():
    r = doc.check_kill_switches()
    assert r["status"] == "ok"


def test_env_var_switching_brief_off_is_reported(monkeypatch):
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "0")
    r = doc.check_kill_switches()
    assert r["status"] == "warn"
    assert "VNSTOCK_PIPELINE_BRIEF" in r["message"]
    assert "brief" in r["message"].lower()


def test_dotenv_line_is_caught_too(_clean_env):
    """Đường lây thật: cờ nằm trong .env chứ không phải shell."""
    (_clean_env / ".env").write_text(
        "ANTHROPIC_API_KEY=x\nVNSTOCK_PIPELINE_BRIEF=0\n", encoding="utf-8")
    r = doc.check_kill_switches()
    assert r["status"] == "warn" and "VNSTOCK_PIPELINE_BRIEF" in r["message"]


def test_values_that_mean_on_are_not_flagged(monkeypatch):
    """Đặt về "1" là mặc định — báo động ở đây là báo động oan mỗi ngày."""
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "1")
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_REFRESH", "true")
    assert doc.check_kill_switches()["status"] == "ok"


def test_off_spellings_all_recognised(monkeypatch):
    for val in ("0", "false", "off", "no", "OFF", "False"):
        monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_RECONCILE", val)
        assert doc.check_kill_switches()["status"] == "warn", val


def test_several_switches_are_all_named(monkeypatch):
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "0")
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    d = doc.check_kill_switches()["message"]
    assert "VNSTOCK_PIPELINE_BRIEF" in d and "VNSTOCK_NEWS_FULLTEXT" in d


def test_broken_dotenv_does_not_crash_the_check(_clean_env):
    (_clean_env / ".env").write_bytes(b"\xff\xfe not utf8 \x00\nVNSTOCK_PIPELINE_BRIEF=0\n")
    assert doc.check_kill_switches()["status"] in ("ok", "warn")


def test_check_is_wired_into_the_offline_run():
    """Guard quên nối = code chết trông y như code sống (nếp của repo)."""
    assert doc.check_kill_switches in doc.OFFLINE_CHECKS


# ── Badge test không được XANH khi code đã đổi sau lần chạy (vá 19/08) ──────


@pytest.fixture
def meta(tmp_path, monkeypatch):
    m = tmp_path / "_meta"
    m.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(doc, "_META", m)
    return m


class TestStaleTestBadge:
    """Ca thật 19/08: user merge code mới rồi chạy `pytest` thẳng (không qua
    `run.py test` nên badge không được ghi) — badge vẫn khoe "2148 passed" của
    hôm trước trong khi thực tế đã 2196. Badge XANH mà code đã đổi sau đó là
    lời trấn an sai, đúng loại hỏng vừa vá ở badge quy đổi đơn vị."""

    def _status(self, meta, ran_at, passed=2148, failed=0):
        import json
        meta.joinpath("test_status.json").write_text(json.dumps({
            "passed": passed, "failed": failed, "errors": 0,
            "mode": "full", "ran_at": ran_at.isoformat()}), encoding="utf-8")

    def test_warns_when_a_py_file_is_newer_than_the_run(self, meta, tmp_path,
                                                        monkeypatch):
        import os
        from datetime import datetime, timedelta
        monkeypatch.setattr(doc, "_REPO", tmp_path)
        ran = datetime.now() - timedelta(hours=3)
        self._status(meta, ran)
        f = tmp_path / "vnstock_brief.py"
        f.write_text("x = 1", encoding="utf-8")
        newer = (ran + timedelta(hours=1)).timestamp()
        os.utime(f, (newer, newer))
        r = doc.check_tests()
        assert r["status"] == "warn"
        assert "CODE đã đổi sau đó" in r["message"] and "vnstock_brief.py" in r["message"]

    def test_stays_green_when_nothing_changed_since(self, meta, tmp_path,
                                                    monkeypatch):
        import os
        from datetime import datetime, timedelta
        monkeypatch.setattr(doc, "_REPO", tmp_path)
        ran = datetime.now() - timedelta(hours=1)
        self._status(meta, ran)
        f = tmp_path / "vnstock_brief.py"
        f.write_text("x = 1", encoding="utf-8")
        older = (ran - timedelta(hours=5)).timestamp()
        os.utime(f, (older, older))
        assert doc.check_tests()["status"] == "ok"

    def test_a_real_failure_still_beats_the_staleness_warning(self, meta,
                                                              tmp_path,
                                                              monkeypatch):
        """Test ĐỎ phải thắng: đừng hạ một lỗi thật xuống thành cảnh báo cũ."""
        import os
        from datetime import datetime, timedelta
        monkeypatch.setattr(doc, "_REPO", tmp_path)
        ran = datetime.now() - timedelta(hours=3)
        self._status(meta, ran, passed=2100, failed=3)
        f = tmp_path / "vnstock_brief.py"
        f.write_text("x = 1", encoding="utf-8")
        newer = (ran + timedelta(hours=1)).timestamp()
        os.utime(f, (newer, newer))
        assert doc.check_tests()["status"] == "error"
