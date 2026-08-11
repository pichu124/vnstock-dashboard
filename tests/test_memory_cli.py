"""CLI đọc bộ nhớ brief — sinh từ phát hiện 11/08: pipeline KHÔNG ghi log.

Task Scheduler chạy `python run.py all` thẳng (stdout bị vứt), run_daily.bat
không redirect — `run_daily.log` chưa bao giờ tồn tại. Lỗi agent brief vì thế
chỉ còn dấu vết trong SQLite memory (`save_brief(..., error=err)`), mà chưa
có vòi đọc từ terminal: bằng chứng nằm đó nhưng không móc ra được (python -c
inline đã bị PowerShell nuốt nháy 2 lần). CLI này là cái vòi.
"""

import pytest

import vnstock_memory as vm


@pytest.fixture()
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "DB_PATH", tmp_path / "brief_memory.db")
    vm.init_db()
    return tmp_path


def _save(agent: str, error: "str | None" = None) -> int:
    return vm.save_brief(
        brief_date="2026-08-11", brief_type="afternoon", agent_name=agent,
        agent_type="groq", model="qwen/qwen3.6-27b", prompt="p",
        output="" if error else "brief text", error=error, context={},
        auto_score=5.0)


def test_recent_shows_error_rows_loudly(_tmp_db, capsys):
    _save("Gemini 3.5 Flash")
    _save("Groq Qwen3.6-27B",
          error="Groq API 400: max_tokens reached, finish_reason=length")
    assert vm.main(["--recent", "5"]) == 0
    out = capsys.readouterr().out
    assert "❌" in out and "finish_reason=length" in out   # lỗi hiện NGUYÊN VĂN
    assert "✅" in out and "Gemini 3.5 Flash" in out


def test_recent_empty_db_says_so(_tmp_db, capsys):
    assert vm.main(["--recent", "5"]) == 1
    assert "chưa có brief" in capsys.readouterr().out


def test_recent_filters_by_type(_tmp_db, capsys):
    """--type phải khớp giá trị THẬT trong DB (morning/afternoon/allocation)
    — bản đầu ghi "close" theo tên gọi miệng, filter không bao giờ khớp."""
    vm.save_brief(brief_date="2026-08-11", brief_type="morning",
                  agent_name="Sang-Agent", agent_type="gemini", model="m",
                  prompt="p", output="x", error=None, context={}, auto_score=1.0)
    _save("Chieu-Agent")
    vm.main(["--recent", "5", "--type", "afternoon"])
    out = capsys.readouterr().out
    assert "Chieu-Agent" in out and "Sang-Agent" not in out
