"""vnstock_claude_cli — backend Claude Code headless dùng chung (30/09, U62).

Hermetic: subprocess.run monkeypatch, .env không được đọc (`_ENV_LOADED`
ghim True) để `.env` thật trên máy user không lật kết quả test."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import vnstock_claude_cli as vcc

_REPO = Path(__file__).resolve().parent.parent
_ALL_ENVS = ("VNSTOCK_LLM_ENGINE", *vcc.STEP_ENGINE_ENV.values(),
             "VNSTOCK_CLAUDE_CLI_EXE", "VNSTOCK_BRIEF_CLI_EXE",
             "VNSTOCK_CLAUDE_CLI_MODEL", "VNSTOCK_BRIEF_CLI_MODEL",
             "VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL", "VNSTOCK_CLAUDE_CLI_TIMEOUT_S",
             "VNSTOCK_BRIEF_CLI_TIMEOUT_S", "VNSTOCK_CLAUDE_CLI_API_KEY",
             "VNSTOCK_BRIEF_CLI_API_KEY", "VNSTOCK_CLAUDE_CLI_REPO_CONTEXT")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setattr(vcc, "_ENV_LOADED", True)      # không đọc .env thật
    for k in _ALL_ENVS:
        monkeypatch.delenv(k, raising=False)


def _ledger_spy(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(vcc, "_ledger_record",
                        lambda provider, model, ok, usage=None, error=None:
                        rows.append((provider, model, ok, usage, error)))
    return rows


# ─── engine / nút vặn ─────────────────────────────────────────────────────────

def test_engine_for_precedence_step_over_global_over_ladder(monkeypatch):
    assert vcc.engine_for("brief") == "ladder"
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    assert vcc.engine_for("brief") == "claude" and vcc.engine_for("news") == "claude"
    monkeypatch.setenv("VNSTOCK_NEWS_ENGINE", "ladder")
    assert vcc.engine_for("news") == "ladder" and vcc.engine_for("audit") == "claude"
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "gpt")          # chữ lạ = ladder
    assert vcc.engine_for("audit") == "ladder"
    assert vcc.engine_for("bước-lạ") == "ladder"


def test_model_fallback_timeout_env(monkeypatch):
    assert vcc.cli_model() == "claude-opus-5-5"
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_MODEL", "claude-sonnet-5-5")
    assert vcc.cli_model() == "claude-sonnet-5-5"
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_MODEL", "claude-opus-5-5")
    assert vcc.cli_model("VNSTOCK_BRIEF_CLI_MODEL") == "claude-opus-5-5"   # đè riêng bước

    assert vcc.cli_fallback_model() == "claude-sonnet-5-5"
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL", "off")
    assert vcc.cli_fallback_model() is None
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL", "claude-haiku-4-5")
    assert vcc.cli_fallback_model() == "claude-haiku-4-5"

    assert vcc.cli_timeout_s() == 600
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_TIMEOUT_S", "5")
    assert vcc.cli_timeout_s() == 30
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_TIMEOUT_S", "abc")
    assert vcc.cli_timeout_s("VNSTOCK_BRIEF_CLI_TIMEOUT_S") == 600


def test_cli_env_hides_api_key_and_disables_autoupdate(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = vcc.cli_env()
    assert "ANTHROPIC_API_KEY" not in env and env["DISABLE_AUTOUPDATER"] == "1"
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_API_KEY", "1")
    assert vcc.cli_env()["ANTHROPIC_API_KEY"] == "sk-secret"


def test_cli_executable_env_then_path(monkeypatch, tmp_path):
    exe = tmp_path / "claude"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_EXE", str(exe))
    assert vcc.cli_executable() == str(exe)
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_EXE", str(tmp_path / "missing"))
    assert vcc.cli_executable() is None                      # ghim sai thì KHÔNG rơi về PATH
    monkeypatch.delenv("VNSTOCK_CLAUDE_CLI_EXE")
    monkeypatch.setattr(vcc.shutil, "which", lambda name: "/usr/bin/claude")
    assert vcc.cli_executable() == "/usr/bin/claude"


# ─── dòng lệnh ───────────────────────────────────────────────────────────────

def test_cli_command_strips_repo_context_and_carries_system_prompt():
    cmd = vcc.cli_command("/x/claude", "claude-opus-5-5", system="SYS",
                          fallback_model="claude-sonnet-5-5")
    assert cmd[:3] == ["/x/claude", "-p", vcc.TASK_LINE]
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--disable-slash-commands" in cmd and "--strict-mcp-config" in cmd
    assert "--no-session-persistence" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert cmd[cmd.index("--fallback-model") + 1] == "claude-sonnet-5-5"
    assert "--max-turns" not in cmd and "--json-schema" not in cmd


def test_cli_command_repo_context_json_schema_effort(monkeypatch):
    schema = {"type": "object", "properties": {"score": {"type": "number"}},
              "required": ["score"]}
    cmd = vcc.cli_command("/x/claude", "m", json_schema=schema, effort="high",
                          repo_context=True)
    assert "--setting-sources" not in cmd and "--disable-slash-commands" not in cmd
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == schema
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert "--system-prompt" not in cmd and "--fallback-model" not in cmd
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_REPO_CONTEXT", "1")
    assert "--setting-sources" not in vcc.cli_command("/x/claude", "m")


def test_cli_command_tools_stay_confined_to_cwd(monkeypatch):
    """04/10 đọc ảnh báo cáo: `tools="Read"` bật ĐÚNG Read, KHÔNG `--allowedTools`
    (cho phép trần ⇒ đọc được file ngoài cwd, đã thử 2.1.289) và luôn tước
    settings người dùng, kể cả khi bật repo context; mặc định vẫn 0 công cụ."""
    monkeypatch.setenv("VNSTOCK_CLAUDE_CLI_REPO_CONTEXT", "1")
    for cmd in (vcc.cli_command("/x/claude", "m", tools="Read"),
                vcc.cli_command("/x/claude", "m", tools="Read", repo_context=True)):
        assert cmd[cmd.index("--tools") + 1] == "Read"
        assert cmd[cmd.index("--permission-prompts") + 1] == "none"
        assert not any(c.startswith("--allowedTools") or c.startswith("--allowed-tools")
                       for c in cmd)
        assert cmd[cmd.index("--setting-sources") + 1] == ""
    plain = vcc.cli_command("/x/claude", "m")
    assert plain[plain.index("--tools") + 1] == "" and "--setting-sources" not in plain


def test_complete_passes_tools_and_cwd(monkeypatch, tmp_path):
    _ledger_spy(monkeypatch)
    got: dict = {}

    def _run(cmd, **kw):
        got["cmd"], got["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_body()), stderr="")
    monkeypatch.setattr(subprocess, "run", _run)
    text, err, _ = vcc.complete("U", model="m", exe="/fake/claude", tools="Read",
                                cwd=str(tmp_path))
    assert err is None and got["kw"]["cwd"] == str(tmp_path)
    assert got["cmd"][got["cmd"].index("--tools") + 1] == "Read"


# ─── parse stdout ────────────────────────────────────────────────────────────

def _body(**kw) -> dict:
    base = {"type": "result", "subtype": "success", "is_error": False,
            "result": "BRIEF", "total_cost_usd": 0.1234, "duration_ms": 9000,
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 11_000,
                      "cache_creation_input_tokens": 500, "output_tokens": 2_000},
            "modelUsage": {"claude-opus-5-5": {"outputTokens": 2_000}}}
    base.update(kw)
    return base


def test_parse_success_sums_cache_and_reads_real_model():
    text, err, info = vcc.parse_cli_output(json.dumps(_body()))
    assert (text, err) == ("BRIEF", None)
    assert info["usage"] == {"prompt_tokens": 11_600, "completion_tokens": 2_000}
    assert info["cost_usd"] == pytest.approx(0.1234) and info["duration_ms"] == 9000
    assert info["model"] == "claude-opus-5-5"


def test_parse_real_model_is_the_one_that_answered():
    body = _body(modelUsage={"claude-opus-5-5": {"outputTokens": 0},
                             "claude-sonnet-5-5": {"outputTokens": 1_900}})
    _, _, info = vcc.parse_cli_output(json.dumps(body))
    assert info["model"] == "claude-sonnet-5-5"


def test_parse_non_json_stdout_is_an_error_never_text():
    text, err, _ = vcc.parse_cli_output("Claude Code v2.2 is available — update now\nBRIEF")
    assert text == "" and "không phải JSON" in err
    text, err, _ = vcc.parse_cli_output("")
    assert text == "" and err
    text, err, _ = vcc.parse_cli_output("[1, 2]")
    assert text == "" and "object" in err


def test_parse_error_and_empty_and_structured():
    text, err, _ = vcc.parse_cli_output(json.dumps(_body(is_error=True, result="Not logged in")))
    assert text == "" and "Not logged in" in err
    text, err, _ = vcc.parse_cli_output(json.dumps(_body(result="  ")))
    assert text == "" and "rỗng" in err
    body = _body(result="", structured_output={"score": 0.7, "label": "positive"})
    text, err, info = vcc.parse_cli_output(json.dumps(body))
    assert err is None and info["structured"] == {"score": 0.7, "label": "positive"}
    assert json.loads(text) == {"score": 0.7, "label": "positive"}


# ─── complete(): stdin, env, sổ, timeout, fallback ──────────────────────────

def test_complete_pipes_user_via_stdin_and_records_ok(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    got: dict = {}

    def _run(cmd, **kw):
        got["cmd"], got["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_body()), stderr="")
    monkeypatch.setattr(subprocess, "run", _run)

    text, err, info = vcc.complete("USER-TEXT", system="SYS", model="claude-opus-5-5",
                                   timeout_s=123, exe="/fake/claude", tag="t")
    assert (text, err) == ("BRIEF", None)
    assert got["kw"]["input"] == "USER-TEXT"                # prompt qua stdin, nguyên văn
    assert not any("USER-TEXT" in c for c in got["cmd"])
    assert got["cmd"][got["cmd"].index("--system-prompt") + 1] == "SYS"
    assert got["cmd"][got["cmd"].index("--fallback-model") + 1] == "claude-sonnet-5-5"
    assert got["kw"]["timeout"] == 123 and got["kw"]["encoding"] == "utf-8"
    assert got["kw"]["cwd"] == str(_REPO)
    assert "ANTHROPIC_API_KEY" not in got["kw"]["env"]
    assert info["model"] == "claude-opus-5-5" and info["fallback"] is False
    assert info["tag"] == "t" and info["cost_usd"] == pytest.approx(0.1234)
    assert rows == [("ClaudeCode", "claude-opus-5-5", True,
                     {"prompt_tokens": 11_600, "completion_tokens": 2_000}, None)]


def test_complete_marks_fallback_and_ledgers_real_model(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    body = _body(modelUsage={"claude-sonnet-5-5": {"outputTokens": 1_900}})
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps(body), stderr=""))
    text, err, info = vcc.complete("U", model="claude-opus-5-5", exe="/fake/claude")
    assert err is None and info["fallback"] is True and info["model"] == "claude-sonnet-5-5"
    assert rows[-1][1] == "claude-sonnet-5-5" and rows[-1][2] is True
    line = vcc.outcome_line("brief", info, text, err)
    assert "↘ fallback claude-sonnet-5-5" in line and line.startswith("[brief] ⏱ claude-cli:")


def test_complete_fallback_off_drops_flag(monkeypatch):
    _ledger_spy(monkeypatch)
    got: dict = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: got.update(cmd=cmd) or
                        subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_body()), stderr=""))
    vcc.complete("U", exe="/fake/claude", fallback_model="")
    assert "--fallback-model" not in got["cmd"]


def test_complete_missing_exe_records_ledger_and_never_spawns(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn khi không có CLI")))
    text, err, info = vcc.complete("U")
    assert text == "" and "claude" in err
    assert rows == [("ClaudeCode", "claude-opus-5-5", False, None, err)]


def test_complete_timeout_and_nonzero_rc(monkeypatch):
    rows = _ledger_spy(monkeypatch)

    def _timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(subprocess, "run", _timeout)
    text, err, info = vcc.complete("U", exe="/fake/claude", timeout_s=60)
    assert text == "" and "60s" in err and rows[-1][2] is False and "60s" in rows[-1][4]
    vcc.reset_dead_memo()                      # timeout đã ghi memo "CLI chết"

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout="", stderr="Error: not logged in\n"))
    text, err, _ = vcc.complete("U", exe="/fake/claude")
    assert text == "" and "rc=1" in err and "not logged in" in err and rows[-1][2] is False


def test_outcome_line_shapes():
    ok = vcc.outcome_line("brief", {"elapsed_s": 41.2, "cost_usd": 0.31}, "x" * 2500, None)
    assert ok.startswith("[brief] ⏱ claude-cli: 41s · ✅ 2,500 ký tự · $0.31")
    bad = vcc.outcome_line("news", {"elapsed_s": 600}, "", "claude CLI quá 600s — bỏ")
    assert bad.startswith("[news] ⏱ claude-cli: 600s · ❌ claude CLI quá")


# ─── cli_check ───────────────────────────────────────────────────────────────

def test_cli_check_reports_exe_version_auth_and_probe(monkeypatch):
    _ledger_spy(monkeypatch)
    monkeypatch.setattr(vcc, "cli_executable", lambda: "/fake/claude")

    def _run(cmd, **kw):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="2.1.285 (Claude Code)\n", stderr="")
        if cmd[1:] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
                {"loggedIn": True, "authMethod": "oauth_token"}), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_body(result="OK")), stderr="")
    monkeypatch.setattr(subprocess, "run", _run)

    res = vcc.cli_check()
    assert res["ok"] is True and res["exe_source"] == "path"
    assert res["version"].startswith("2.1.285") and res["auth"]["loggedIn"] is True
    assert res["probe"]["ok"] and res["probe"]["text"] == "OK"
    assert res["probe"]["model"] == "claude-opus-5-5"
    assert res["engine"]["brief"] == "ladder"

    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    res = vcc.cli_check()
    assert res["ok"] is False and "claude" in res["error"]
    assert vcc.main(["--check"]) == 1


# ─── memo "CLI chết trong tiến trình" (thẩm định 30/09) ──────────────────────

def test_dead_memo_short_circuits_after_timeout_until_reset(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    spawned: list = []

    def _run(cmd, **kw):
        spawned.append(1)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(subprocess, "run", _run)
    _, err, _ = vcc.complete("U", exe="/fake/claude", timeout_s=60)
    assert "60s" in err and len(spawned) == 1
    _, err2, info = vcc.complete("U2", exe="/fake/claude", timeout_s=60)
    assert len(spawned) == 1 and "đã chết" in err2 and info["memo"] is True   # không đợi lần 2
    assert rows[-1][2] is False
    vcc.reset_dead_memo()
    vcc.complete("U3", exe="/fake/claude", timeout_s=60)
    assert len(spawned) == 2


def test_api_error_does_not_trip_memo_but_rc_and_missing_exe_do(monkeypatch):
    _ledger_spy(monkeypatch)
    spawned: list = []
    body = json.dumps(_body(is_error=True, result="overloaded"))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: spawned.append(1) or
                        subprocess.CompletedProcess(cmd, 0, stdout=body, stderr=""))
    vcc.complete("U", exe="/fake/claude"); vcc.complete("U", exe="/fake/claude")
    assert len(spawned) == 2 and vcc._DEAD_REASON is None       # lỗi API: thử lại được
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: spawned.append(1) or
                        subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in"))
    vcc.complete("U", exe="/fake/claude")
    assert vcc._DEAD_REASON and "rc=1" in vcc._DEAD_REASON
    vcc.reset_dead_memo()
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    vcc.complete("U")
    assert vcc._DEAD_REASON and "claude" in vcc._DEAD_REASON


def test_is_shim_and_native_exe_preferred(monkeypatch, tmp_path):
    assert vcc.is_shim("C:\\npm\\claude.cmd") and vcc.is_shim("claude.BAT")
    assert not vcc.is_shim("/usr/bin/claude") and not vcc.is_shim(None)
    monkeypatch.setattr(vcc.shutil, "which", lambda name: "C:\\npm\\claude.cmd")
    monkeypatch.setattr(vcc.Path, "home", lambda: tmp_path)
    assert vcc.cli_executable() == "C:\\npm\\claude.cmd"          # chưa có bản native
    native = tmp_path / ".local" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.write_text("", encoding="utf-8")
    assert vcc.cli_executable() == str(native)                     # né shim


def test_cli_check_probe_uses_special_chars_and_flags_shim(monkeypatch):
    _ledger_spy(monkeypatch)
    monkeypatch.setattr(vcc, "cli_executable", lambda: "C:\\npm\\claude.cmd")
    seen: dict = {}

    def _run(cmd, **kw):
        if "--system-prompt" in cmd:
            seen["system"] = cmd[cmd.index("--system-prompt") + 1]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_body(result="OK")), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="2.1.285\n", stderr="")
    monkeypatch.setattr(subprocess, "run", _run)
    res = vcc.cli_check()
    assert res["shim"] is True and "claude.exe" in res["warning"] and res["ok"] is True
    assert seen["system"] == vcc.PROBE_SYSTEM
    assert all(ch in vcc.PROBE_SYSTEM for ch in ('|', '<', '>', '%', '"', '\n'))


# ─── connector MCP (08/10, U78/U79) ───────────────────────────────────────────
TCBS_OV = "mcp__claude_ai_TCBS_MCP__tcinvest-getTickerOverview"


def _use(tid, name, **inp):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def _res(tid, text, is_error=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid,
         "content": [{"type": "text", "text": text}], "is_error": is_error}]}}


def _final(**kw):
    return {"type": "result", "subtype": "success", "is_error": False, "result": "XONG",
            "total_cost_usd": 0.07, "duration_ms": 9000,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 900, "output_tokens": 40},
            "modelUsage": {"claude-sonnet-5-5": {"outputTokens": 40}}, **kw}


def test_mcp_server_prefix_matches_desktop_naming():
    assert vcc.mcp_server_prefix("claude.ai TCBS MCP") + "x" == "mcp__claude_ai_TCBS_MCP__x"


def test_mcp_command_lean_flags_and_allowed_tools_last():
    cmd = vcc.mcp_command("claude", "m", system="s", allowed_tools=[TCBS_OV, "b"], max_turns=5)
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch"
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" not in cmd and "--disable-slash-commands" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json" and "--verbose" in cmd
    assert cmd[-3:] == ["--allowedTools", TCBS_OV, "b"]
    assert cmd[cmd.index("--max-turns") + 1] == "5"
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"


def test_plain_complete_still_blocks_mcp():
    # Bước brief/news vẫn đi complete() — phải giữ --strict-mcp-config (U78 đo 0 tool).
    cmd = vcc.cli_command("claude", "m")
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--tools") + 1] == ""


def test_tool_exchanges_pairs_use_and_result_in_order():
    evs = [_use("a", TCBS_OV, ticker="SHB"), _use("b", TCBS_OV, ticker="GMD"),
           _res("b", '{"ticker":"GMD"}'), _res("a", "lỗi", is_error=True), _res("zz", "lạc")]
    ex = vcc.tool_exchanges(evs)
    assert [(e["input"]["ticker"], e["text"], e["is_error"]) for e in ex] == [
        ("SHB", "lỗi", True), ("GMD", '{"ticker":"GMD"}', False)]


def test_complete_mcp_reads_tool_results_and_records_ledger(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    seen: dict = {}

    def _fake(cmd, stdin_text, timeout_s, *, stop_at_init=False, cwd=None):
        seen.update(cmd=cmd, stdin=stdin_text, cwd=cwd)
        return ([_use("s", "ToolSearch"), _use("a", TCBS_OV, ticker="SHB"),
                 _res("a", '{"ticker":"SHB"}'), _use("x", "Bash"), _final()], None, 9.0)
    monkeypatch.setattr(vcc, "run_stream_json", _fake)
    ex, err, info = vcc.complete_mcp("mã: SHB", system="s", allowed_tools=[TCBS_OV],
                                     exe="claude", tag="t")
    assert err is None and [e["text"] for e in ex] == ['{"ticker":"SHB"}']
    assert info["helpers"] == 1 and info["strangers"] == ["Bash"]
    assert info["cost_usd"] == 0.07 and info["usage"]["prompt_tokens"] == 910
    assert seen["stdin"] == "mã: SHB" and "vnstock_mcp_" in seen["cwd"]
    assert rows[-1][0] == "ClaudeCode" and rows[-1][2] is True


def test_complete_mcp_no_tool_result_is_error(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(vcc, "run_stream_json",
                        lambda *a, **k: ([_final(permission_denials=[{"tool_name": TCBS_OV}])], None, 1.0))
    ex, err, info = vcc.complete_mcp("x", system="s", allowed_tools=[TCBS_OV], exe="claude")
    assert ex == [] and err and info["denials"] == [TCBS_OV]
    assert rows[-1][2] is False


def test_complete_mcp_without_exe(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    ex, err, info = vcc.complete_mcp("x", system="s", allowed_tools=[TCBS_OV])
    assert ex == [] and "không tìm thấy" in err and info["no_exe"] and rows[-1][2] is False
