"""vnstock_brief_pack — gói brief cho engine ngoài (Claude Code), 30/09.

Hermetic: không kho, không mạng, không CLI thật — subprocess.run và mọi
điểm chạm ctx/memory đều monkeypatch."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import vnstock_brief as vb
import vnstock_brief_pack as bp

_REPO = Path(__file__).resolve().parent.parent


def _pack(session: str = "2026-09-30") -> dict:
    return {"version": bp.PACK_VERSION, "brief_type": "afternoon",
            "session": session, "created_at": f"{session}T20:30:00",
            "machine": "PICHU", "prompt": "PROMPT-XYZ",
            "ctx": {"date": session, "tickers": [1, 2, 3], "breadth": {}}}


# ─── engine / nút vặn ─────────────────────────────────────────────────────────

def test_engine_from_env_defaults_to_ladder_and_ignores_junk(monkeypatch):
    monkeypatch.delenv(bp.ENGINE_ENV, raising=False)
    assert bp.engine_from_env() == "ladder"
    monkeypatch.setenv(bp.ENGINE_ENV, " CLAUDE ")
    assert bp.engine_from_env() == "claude"
    monkeypatch.setenv(bp.ENGINE_ENV, "gpt")
    assert bp.engine_from_env() == "ladder"


def test_cli_model_and_label(monkeypatch):
    monkeypatch.delenv("VNSTOCK_BRIEF_CLI_MODEL", raising=False)
    assert bp.cli_model() == "claude-opus-5-5"
    assert bp.engine_label("claude-opus-5-5") == "Claude Code · opus-5-5"
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_MODEL", "claude-sonnet-5-5")
    assert bp.cli_model() == "claude-sonnet-5-5"


def test_cli_env_hides_api_key_unless_opted_in(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("VNSTOCK_BRIEF_CLI_API_KEY", raising=False)
    assert "ANTHROPIC_API_KEY" not in bp.cli_env()
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_API_KEY", "1")
    assert bp.cli_env()["ANTHROPIC_API_KEY"] == "sk-secret"


def test_cli_command_shape():
    cmd = bp.cli_command("/x/claude", "claude-opus-5-5")
    assert cmd[0] == "/x/claude" and "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""          # tắt mọi công cụ: 1 lượt chữ
    assert "--no-session-persistence" in cmd
    assert "--max-turns" not in cmd                      # không có trong --help 2.1.285


def test_cli_timeout_floor_and_default(monkeypatch):
    monkeypatch.delenv("VNSTOCK_BRIEF_CLI_TIMEOUT_S", raising=False)
    assert bp.cli_timeout_s() == bp.DEFAULT_CLI_TIMEOUT_S
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_TIMEOUT_S", "5")
    assert bp.cli_timeout_s() == 30
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_TIMEOUT_S", "abc")
    assert bp.cli_timeout_s() == bp.DEFAULT_CLI_TIMEOUT_S


# ─── build / write / read pack ───────────────────────────────────────────────

def test_build_pack_walks_the_same_path_as_generate_brief(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(vb, "_ensure_env_loaded", lambda: calls.append("env"))
    monkeypatch.setattr(vb, "_maybe_reconcile_overdue", lambda: calls.append("overdue"))
    monkeypatch.setattr(vb, "_maybe_refresh_events", lambda: calls.append("events"))
    monkeypatch.setattr(vb, "_maybe_refresh_macro", lambda: calls.append("macro"))
    monkeypatch.setattr(vb, "_maybe_refresh_market_news", lambda: calls.append("news"))
    monkeypatch.setattr(vb, "collect_context",
                        lambda bt, auto_refresh=False: {"date": "2026-09-30",
                                                        "brief_type": bt,
                                                        "tickers": [1],
                                                        "auto": auto_refresh})
    monkeypatch.setattr(vb, "_few_shot_block", lambda bt: "FEW")
    monkeypatch.setattr(vb, "_recommendation_block", lambda ctx: "REC")
    monkeypatch.setattr(vb, "_news_block", lambda: "NEWS")
    monkeypatch.setattr(vb, "build_prompt",
                        lambda ctx, bt, few_shot="", rec_block="", news_block="":
                        f"P|{bt}|{few_shot}|{rec_block}|{news_block}")
    monkeypatch.setattr(bp, "_hostname", lambda: "PICHU")

    pack = bp.build_pack("afternoon")
    assert calls == ["env", "overdue", "events", "macro", "news"]
    assert pack["version"] == bp.PACK_VERSION
    assert pack["session"] == "2026-09-30"
    assert pack["prompt"] == "P|afternoon|FEW|REC|NEWS"
    assert pack["ctx"]["auto"] is True          # auto_refresh=True như generate_brief
    assert pack["machine"] == "PICHU"
    json.dumps(pack, default=str)               # gói phải ghi được ra JSON


def test_write_and_read_pack_roundtrip(tmp_path):
    path = bp.write_pack(_pack(), tmp_path / "_meta" / "brief_pack.json")
    assert path.exists() and not list(path.parent.glob("*.tmp"))
    got = bp.read_pack(path)
    assert got["prompt"] == "PROMPT-XYZ" and got["ctx"]["tickers"] == [1, 2, 3]


def test_read_pack_rejects_missing_prompt_and_wrong_version(tmp_path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps({"version": bp.PACK_VERSION, "prompt": ""}), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt"):
        bp.read_pack(p)
    p.write_text(json.dumps({"version": 99, "prompt": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        bp.read_pack(p)


def test_pack_paths_live_in_meta():
    assert bp.pack_path("W") == Path("W") / "_meta" / "brief_pack.json"
    assert bp.brief_out_path("W") == Path("W") / "_meta" / "brief_claude.md"


# ─── finalize: guards → validate → memory ───────────────────────────────────

def test_clean_text_strips_code_fence_and_whitespace():
    assert bp._clean_text("```markdown\nBODY\nX\n```\n") == "BODY\nX"
    assert bp._clean_text("  BODY  ") == "BODY"
    assert bp._clean_text("```") == ""


def test_finalize_brief_runs_the_ladder_post_chain(monkeypatch):
    import vnstock_brief_watch as _watch
    import vnstock_memory as _mem
    import vnstock_train as _vt

    seen: dict = {}
    monkeypatch.setattr(vb, "apply_brief_guards",
                        lambda t, ctx: seen.setdefault("guard_ctx", ctx) and t + "|G")
    monkeypatch.setattr(vb, "validate_brief_factuality", lambda t, ctx: ["cảnh báo 1"])
    monkeypatch.setattr(_vt, "auto_score_brief", lambda t: 0.75)
    monkeypatch.setattr(_mem, "save_brief", lambda **kw: seen.update(kw) or 42)
    monkeypatch.setattr(_watch, "observe_brief",
                        lambda *a, **k: seen.setdefault("watched", True))

    pack = _pack()
    fin = bp.finalize_brief("```\nBODY\n```", pack,
                            agent_name="Claude Code · opus-5-5",
                            model="claude-opus-5-5")
    assert fin == {"text": "BODY|G", "warnings": ["cảnh báo 1"],
                   "brief_id": 42, "auto_score": 0.75}
    assert seen["guard_ctx"] is pack["ctx"]           # guard thấy ctx đầy đủ
    assert seen["agent_type"] == "claude"
    assert seen["agent_name"] == "Claude Code · opus-5-5"
    assert seen["model"] == "claude-opus-5-5"
    assert seen["brief_date"] == "2026-09-30" and seen["brief_type"] == "afternoon"
    assert seen["prompt"] == "PROMPT-XYZ" and seen["output"] == "BODY|G"
    assert seen["error"] is None and seen["auto_score"] == 0.75
    assert "tickers" not in seen["context"]           # memory bỏ tickers như ladder
    assert seen["watched"] is True


def test_finalize_brief_empty_text_touches_nothing(monkeypatch):
    import vnstock_memory as _mem
    monkeypatch.setattr(_mem, "save_brief",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("ghi memory bản rỗng")))
    monkeypatch.setattr(vb, "apply_brief_guards",
                        lambda t, ctx: (_ for _ in ()).throw(AssertionError("guard bản rỗng")))
    fin = bp.finalize_brief("```\n```", _pack(), agent_name="x", model="m")
    assert fin["text"] == "" and fin["brief_id"] is None


def test_finalize_brief_survives_memory_and_validator_failures(monkeypatch):
    import vnstock_memory as _mem
    monkeypatch.setattr(vb, "apply_brief_guards", lambda t, ctx: t)
    monkeypatch.setattr(vb, "validate_brief_factuality",
                        lambda t, ctx: (_ for _ in ()).throw(RuntimeError("validator hỏng")))
    monkeypatch.setattr(_mem, "save_brief",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("sqlite khoá")))
    fin = bp.finalize_brief("BODY", _pack(), agent_name="x", model="m")
    assert fin["text"] == "BODY" and fin["warnings"] == [] and fin["brief_id"] is None


# ─── parse stdout của `claude -p --output-format json` ──────────────────────

def test_parse_cli_output_success_sums_cache_tokens_into_prompt():
    body = {"type": "result", "subtype": "success", "is_error": False,
            "result": "BRIEF", "total_cost_usd": 0.1234, "duration_ms": 9000,
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 11_000,
                      "cache_creation_input_tokens": 500, "output_tokens": 2_000}}
    text, err, info = bp.parse_cli_output(json.dumps(body))
    assert (text, err) == ("BRIEF", None)
    assert info["usage"] == {"prompt_tokens": 11_600, "completion_tokens": 2_000}
    assert info["cost_usd"] == pytest.approx(0.1234) and info["duration_ms"] == 9000


def test_parse_cli_output_error_and_empty_variants():
    text, err, _ = bp.parse_cli_output(json.dumps(
        {"is_error": True, "result": "Not logged in", "subtype": "error"}))
    assert text == "" and "Not logged in" in err
    text, err, _ = bp.parse_cli_output(json.dumps({"is_error": False, "result": "  "}))
    assert text == "" and "rỗng" in err
    text, err, _ = bp.parse_cli_output("")
    assert text == "" and err
    # CLI cũ in text thường → cả stdout là chữ
    text, err, _ = bp.parse_cli_output("## Tổng quan\nDòng")
    assert text.startswith("## Tổng quan") and err is None


# ─── run_claude_cli: stdin, env, sổ, timeout ────────────────────────────────

def _ledger_spy(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(vb, "_ledger_record",
                        lambda provider, model, ok, usage=None, error=None:
                        rows.append((provider, model, ok, usage, error)))
    return rows


def test_run_claude_cli_pipes_prompt_via_stdin_and_records_ok(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: "/fake/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("VNSTOCK_BRIEF_CLI_API_KEY", raising=False)
    got: dict = {}

    def _run(cmd, **kw):
        got["cmd"], got["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
            {"is_error": False, "result": "BRIEF", "total_cost_usd": 0.2,
             "usage": {"input_tokens": 10, "output_tokens": 5}}), stderr="")
    monkeypatch.setattr(subprocess, "run", _run)

    text, err, info = bp.run_claude_cli("PROMPT-XYZ", model="claude-opus-5-5",
                                        timeout_s=123)
    assert (text, err) == ("BRIEF", None)
    assert got["cmd"][0] == "/fake/claude" and "--model" in got["cmd"]
    assert got["kw"]["input"].startswith(bp.CLI_PREFACE)
    assert got["kw"]["input"].endswith("PROMPT-XYZ")   # prompt qua stdin, không qua argv
    assert not any("PROMPT-XYZ" in c for c in got["cmd"])
    assert got["kw"]["timeout"] == 123 and got["kw"]["encoding"] == "utf-8"
    assert got["kw"]["cwd"] == str(_REPO)
    assert "ANTHROPIC_API_KEY" not in got["kw"]["env"]
    assert info["model"] == "claude-opus-5-5" and info["cost_usd"] == 0.2
    assert rows == [("ClaudeCode", "claude-opus-5-5", True,
                     {"prompt_tokens": 10, "completion_tokens": 5}, None)]


def test_run_claude_cli_missing_exe_never_spawns(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: None)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn khi không có CLI")))
    text, err, _ = bp.run_claude_cli("P")
    assert text == "" and "claude" in err and rows == []


def test_run_claude_cli_timeout_records_fail(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: "/fake/claude")

    def _run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(subprocess, "run", _run)
    text, err, info = bp.run_claude_cli("P", timeout_s=60)
    assert text == "" and "60s" in err
    assert rows and rows[0][2] is False and "60s" in rows[0][4]


def test_run_claude_cli_error_body_and_nonzero_rc(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: "/fake/claude")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout="", stderr="Error: not logged in\n"))
    text, err, _ = bp.run_claude_cli("P")
    assert text == "" and "rc=1" in err and "not logged in" in err
    assert rows[-1][2] is False

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps({"is_error": True, "result": "quota"}), stderr=""))
    text, err, _ = bp.run_claude_cli("P")
    assert text == "" and "quota" in err and rows[-1][2] is False


def test_outcome_line_matches_agent_log_shape():
    ok = bp.outcome_line({"elapsed_s": 41.2, "cost_usd": 0.31}, "x" * 2500, None)
    assert ok.startswith("[brief] ⏱ claude-cli: 41s · ✅ 2,500 ký tự · $0.31")
    bad = bp.outcome_line({"elapsed_s": 900}, "", "claude CLI quá 900s — bỏ")
    assert bad.startswith("[brief] ⏱ claude-cli: 900s · ❌ claude CLI quá")


# ─── skill tay phải nói đúng hợp đồng gói ───────────────────────────────────

def test_skill_brief_close_matches_pack_contract():
    skill = _REPO / ".claude" / "skills" / "brief-close" / "SKILL.md"
    src = skill.read_text(encoding="utf-8")
    assert src.startswith("---\nname: brief-close\n")
    for needle in (bp.PACK_NAME, bp.OUT_NAME, "run.py brief --from-file",
                   "run.py brief --export-pack", "VNSTOCK_BRIEF_ENGINE=claude"):
        assert needle in src, needle
