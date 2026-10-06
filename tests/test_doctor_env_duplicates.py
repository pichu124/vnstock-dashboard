"""Badge doctor "Khoá trùng trong .env" + đọc `.env` đúng như python-dotenv.

Vết 05/10 (desktop): `.env` có HAI dòng `TELEGRAM_CHAT_ID` — group Brief ở trên,
chat riêng cũ ở dưới (user giữ dòng cũ mà quên `#`). python-dotenv lấy dòng
SAU ⇒ brief tối đó sẽ âm thầm về chat cũ; không badge nào thấy. Cùng lúc phát
hiện doctor tự đọc `.env` theo kiểu dòng ĐẦU thắng ⇒ báo khác thứ pipeline chạy.
"""
from __future__ import annotations

import pytest

import vnstock_doctor as doc

SECRET = "123456789:AAtokenTHATmustNEVERprint"


@pytest.fixture(autouse=True)
def _repo(monkeypatch, tmp_path):
    monkeypatch.setattr(doc, "_REPO", tmp_path)          # .env giả, không đụng thật
    monkeypatch.setenv("COMPUTERNAME", "PICHU")
    for k in (*doc._ENGINE_ENVS, *doc._DANGEROUS_SWITCHES):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _env(tmp_path, text, bom=False):
    (tmp_path / ".env").write_text(("﻿" if bom else "") + text, encoding="utf-8")


def test_no_env_file_is_off():
    r = doc.check_env_duplicates()
    assert r["status"] == "off" and "PICHU" in r["message"]


def test_clean_file_is_ok_ignoring_comments_blank_and_export(_repo):
    _env(_repo, "# TELEGRAM_CHAT_ID=old\n\nTELEGRAM_CHAT_ID=-5561219238\n"
                "export FRED_API_KEY=x\nnot a line\n", bom=True)
    r = doc.check_env_duplicates()
    assert r["status"] == "ok" and "2 khoá" in r["message"]


def test_conflicting_duplicate_warns_with_lines_and_never_values(_repo):
    _env(_repo, f"TELEGRAM_CHAT_ID=-5561219238\nTELEGRAM_NEWS_BOT_TOKEN={SECRET}\n"
                f"TELEGRAM_CHAT_ID=828087238\nTELEGRAM_NEWS_BOT_TOKEN={SECRET}\n")
    r = doc.check_env_duplicates()
    assert r["status"] == "warn" and "2 khoá lặp (PICHU)" in r["message"]
    assert "TELEGRAM_CHAT_ID (dòng 1, 3: KHÁC giá trị — dòng 3 đang thắng)" in r["message"]
    assert "TELEGRAM_NEWS_BOT_TOKEN (dòng 2, 4: cùng giá trị" in r["message"]
    blob = r["message"] + r["fix"]
    assert SECRET not in blob and "828087238" not in blob and "-5561219238" not in blob


def test_env_values_follow_dotenv_last_wins(_repo):
    _env(_repo, "TELEGRAM_CHAT_ID=-5561219238\nTELEGRAM_CHAT_ID=828087238\n")
    assert doc._env_file_values()["TELEGRAM_CHAT_ID"] == "828087238"
    try:                                                   # đối chiếu thư viện thật
        from dotenv import dotenv_values
        assert dotenv_values(_repo / ".env")["TELEGRAM_CHAT_ID"] == "828087238"
    except ImportError:
        pass


def test_engine_setting_reads_last_duplicate(_repo):
    _env(_repo, "VNSTOCK_LLM_ENGINE=ladder\nVNSTOCK_LLM_ENGINE=claude\n")
    assert doc._engine_setting() == "claude"


@pytest.mark.parametrize("text,status", [
    ("VNSTOCK_PIPELINE_BRIEF=0\nVNSTOCK_PIPELINE_BRIEF=1\n", "ok"),     # dòng sau BẬT lại
    ("VNSTOCK_PIPELINE_BRIEF=1\nVNSTOCK_PIPELINE_BRIEF=0\n", "warn"),
])
def test_kill_switch_reads_last_duplicate(_repo, text, status):
    _env(_repo, text)
    assert doc.check_kill_switches()["status"] == status


def test_badge_is_wired_into_offline_checks():
    assert doc.check_env_duplicates in doc.OFFLINE_CHECKS
