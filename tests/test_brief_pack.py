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
import vnstock_claude_cli as vcc

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Không đọc .env thật (máy user có thể đặt VNSTOCK_LLM_ENGINE=claude)."""
    monkeypatch.setattr(vcc, "_ENV_LOADED", True)
    for k in ("VNSTOCK_LLM_ENGINE", "VNSTOCK_BRIEF_ENGINE", "VNSTOCK_CLAUDE_CLI_MODEL",
              "VNSTOCK_BRIEF_CLI_MODEL", "VNSTOCK_CLAUDE_CLI_TIMEOUT_S",
              "VNSTOCK_BRIEF_CLI_TIMEOUT_S", "VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL",
              "VNSTOCK_CLAUDE_CLI_API_KEY", "VNSTOCK_BRIEF_CLI_API_KEY",
              "VNSTOCK_CLAUDE_CLI_REPO_CONTEXT"):
        monkeypatch.delenv(k, raising=False)


def _pack(session: str = "2026-09-30") -> dict:
    return {"version": bp.PACK_VERSION, "brief_type": "afternoon",
            "session": session, "created_at": f"{session}T20:30:00",
            "machine": "PICHU", "prompt": "PROMPT-XYZ",
            "ctx": {"date": session, "tickers": [1, 2, 3], "breadth": {},
                    "financial_tickers": {"VCB", "ACB"},
                    "realestate_tickers": frozenset({"VHM"}),
                    "mover_universe": set()}}


# ─── engine / nút vặn ─────────────────────────────────────────────────────────

def test_engine_from_env_defaults_to_ladder_and_ignores_junk(monkeypatch):
    assert bp.engine_from_env() == "ladder"
    monkeypatch.setenv(bp.ENGINE_ENV, " CLAUDE ")
    assert bp.engine_from_env() == "claude"
    monkeypatch.setenv(bp.ENGINE_ENV, "gpt")
    assert bp.engine_from_env() == "ladder"
    monkeypatch.delenv(bp.ENGINE_ENV)
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")     # công tắc chung
    assert bp.engine_from_env() == "claude"
    monkeypatch.setenv(bp.ENGINE_ENV, "ladder")            # riêng bước đè chung
    assert bp.engine_from_env() == "ladder"


def test_engine_from_env_loads_dotenv_first(monkeypatch):
    """`run.py brief` chạy một mình phải thấy cờ trong .env (giám khảo 30/09)."""
    calls: list = []
    monkeypatch.setattr(vcc, "_ENV_LOADED", False)
    monkeypatch.setattr(vcc, "_ensure_env_loaded",
                        lambda: calls.append(1) or setattr(vcc, "_ENV_LOADED", True))
    # engine_for gọi thẳng hàm module → patch qua module hoạt động
    monkeypatch.setattr(vcc, "engine_for",
                        lambda step: (vcc._ensure_env_loaded(), "ladder")[1])
    assert bp.engine_from_env() == "ladder" and calls == [1]


def test_cli_model_and_label(monkeypatch):
    assert bp.cli_model() == "claude-opus-5-5"
    assert bp.engine_label("claude-opus-5-5") == "Claude Code · opus-5-5"
    monkeypatch.setenv("VNSTOCK_BRIEF_CLI_MODEL", "claude-sonnet-5-5")
    assert bp.cli_model() == "claude-sonnet-5-5"


def test_cli_env_hides_api_key_unless_opted_in(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
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
    # tước context repo (20K → ~1,6K token system) + preface làm system prompt
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--disable-slash-commands" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == bp.CLI_PREFACE
    assert cmd[cmd.index("--fallback-model") + 1] == "claude-sonnet-5-5"


def test_cli_timeout_floor_and_default(monkeypatch):
    assert bp.cli_timeout_s() == bp.DEFAULT_CLI_TIMEOUT_S == 600
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


def test_write_and_read_pack_roundtrip_restores_sets_and_keeps_tickers(tmp_path):
    pack = _pack()
    path = bp.write_pack(pack, tmp_path / "_meta" / "brief_pack.json")
    assert path.exists() and not list(path.parent.glob("*.tmp"))
    # ctx trong bộ nhớ KHÔNG bị đụng (đường đêm đưa thẳng vào guard)
    assert isinstance(pack["ctx"]["financial_tickers"], set)
    assert isinstance(pack["ctx"]["realestate_tickers"], frozenset)
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["ctx"]["financial_tickers"] == ["ACB", "VCB"]      # list sort, không repr
    assert disk["ctx_set_keys"] == ["financial_tickers", "mover_universe", "realestate_tickers"]
    got = bp.read_pack(path)
    assert got["prompt"] == "PROMPT-XYZ" and got["ctx"]["tickers"] == [1, 2, 3]
    assert got["ctx"]["financial_tickers"] == {"VCB", "ACB"}         # set trở lại cho guard
    assert got["ctx"]["realestate_tickers"] == {"VHM"} and got["ctx"]["mover_universe"] == set()
    # prompt nhiều dòng ghi cạnh gói cho skill /brief-close
    assert (path.parent / bp.PROMPT_NAME).read_text(encoding="utf-8") == "PROMPT-XYZ"


def test_read_pack_rejects_missing_prompt_and_old_version(tmp_path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps({"version": bp.PACK_VERSION, "prompt": ""}), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt"):
        bp.read_pack(p)
    p.write_text(json.dumps({"version": 1, "prompt": "x", "ctx": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="version 1"):
        bp.read_pack(p)


def test_write_raw_and_final_are_atomic_text_files(tmp_path):
    assert bp.write_raw("RAW", tmp_path) == tmp_path / "_meta" / bp.RAW_NAME
    assert bp.write_final("FIN", tmp_path) == tmp_path / "_meta" / bp.OUT_NAME
    assert bp.raw_path(tmp_path).read_text(encoding="utf-8") == "RAW"
    assert bp.brief_out_path(tmp_path).read_text(encoding="utf-8") == "FIN"
    assert not list((tmp_path / "_meta").glob("*.tmp"))


def test_pack_paths_live_in_meta():
    assert bp.pack_path("W") == Path("W") / "_meta" / "brief_pack.json"
    assert bp.prompt_path("W") == Path("W") / "_meta" / "brief_prompt.md"
    assert bp.raw_path("W") == Path("W") / "_meta" / "brief_claude_raw.md"
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
                   "brief_id": 42, "auto_score": 0.75, "guard_delta": 2}
    assert seen["guard_ctx"] is pack["ctx"]           # guard thấy ctx đầy đủ (set là set)
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
    # stdout không phải JSON là LỖI — banner/cảnh báo không bao giờ thành brief
    text, err, _ = bp.parse_cli_output("## Tổng quan\nDòng")
    assert text == "" and "không phải JSON" in err


# ─── run_claude_cli: stdin, env, sổ, timeout ────────────────────────────────

def _ledger_spy(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(vcc, "_ledger_record",
                        lambda provider, model, ok, usage=None, error=None:
                        rows.append((provider, model, ok, usage, error)))
    return rows


def test_run_claude_cli_pipes_prompt_via_stdin_and_records_ok(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: "/fake/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    got: dict = {}

    def _run(cmd, **kw):
        got["cmd"], got["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
            {"is_error": False, "result": "BRIEF", "total_cost_usd": 0.2,
             "usage": {"input_tokens": 10, "output_tokens": 5},
             "modelUsage": {"claude-opus-5-5": {"outputTokens": 5}}}), stderr="")
    monkeypatch.setattr(subprocess, "run", _run)

    text, err, info = bp.run_claude_cli("PROMPT-XYZ", model="claude-opus-5-5",
                                        timeout_s=123)
    assert (text, err) == ("BRIEF", None)
    assert got["cmd"][0] == "/fake/claude" and "--model" in got["cmd"]
    assert got["kw"]["input"] == "PROMPT-XYZ"          # prompt nguyên văn qua stdin
    assert got["cmd"][got["cmd"].index("--system-prompt") + 1] == bp.CLI_PREFACE
    assert not any("PROMPT-XYZ" in c for c in got["cmd"])
    assert got["kw"]["timeout"] == 123 and got["kw"]["encoding"] == "utf-8"
    assert got["kw"]["cwd"] == str(_REPO)
    assert "ANTHROPIC_API_KEY" not in got["kw"]["env"]
    assert info["model"] == "claude-opus-5-5" and info["cost_usd"] == 0.2
    assert info["fallback"] is False and info["tag"] == "brief"
    assert rows == [("ClaudeCode", "claude-opus-5-5", True,
                     {"prompt_tokens": 10, "completion_tokens": 5}, None)]


def test_run_claude_cli_missing_exe_records_fail_and_never_spawns(monkeypatch):
    rows = _ledger_spy(monkeypatch)
    monkeypatch.setattr(bp, "cli_executable", lambda: None)
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn khi không có CLI")))
    text, err, _ = bp.run_claude_cli("P")
    assert text == "" and "claude" in err
    assert rows and rows[0][2] is False and rows[0][0] == "ClaudeCode"   # sổ thấy đêm rơi ladder


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
    vcc.reset_dead_memo()                      # rc≠0 đã ghi memo "CLI chết"

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps({"is_error": True, "result": "quota"}), stderr=""))
    text, err, _ = bp.run_claude_cli("P")
    assert text == "" and "quota" in err and rows[-1][2] is False


def test_outcome_line_matches_agent_log_shape():
    ok = bp.outcome_line({"elapsed_s": 41.2, "cost_usd": 0.31}, "x" * 2500, None)
    assert ok.startswith("[brief] ⏱ claude-cli: 41s · ✅ 2,500 ký tự · $0.31")
    bad = bp.outcome_line({"elapsed_s": 600}, "", "claude CLI quá 600s — bỏ")
    assert bad.startswith("[brief] ⏱ claude-cli: 600s · ❌ claude CLI quá")


# ─── soi lại sáng hôm sau ────────────────────────────────────────────────────

def test_review_report_reads_marker_ledger_memory_and_guard_diff(tmp_path, monkeypatch):
    import vnstock_llm_ledger as _lg
    import vnstock_memory as _mem
    meta = tmp_path / "_meta"; meta.mkdir()
    (meta / "brief_push.json").write_text(json.dumps(
        {"close": "2026-09-30", "engine": "ladder", "agent": "Gemini 3.5 Flash",
         "machine": "PICHU", "claude_error": "claude CLI quá 600s — bỏ"}), encoding="utf-8")
    monkeypatch.setattr(_lg, "summary", lambda day=None: {
        "day": "2026-09-30", "providers": {"ClaudeCode:claude-opus-5-5": {
            "calls": 1, "ok": 0, "fail": 1, "last_error": "quá 600s"}}})
    monkeypatch.setattr(_mem, "recent_briefs", lambda bt=None, limit=20: [
        {"id": 7, "brief_date": "2026-09-30", "agent_name": "Gemini 3.5 Flash",
         "output": "x" * 1200, "auto_score": 0.4, "user_rating": None}])
    bp.write_raw("a\nb\nc", tmp_path); bp.write_final("a\nB", tmp_path)
    rep = bp.review_report(tmp_path)
    assert "engine=ladder" in rep and "Claude rơi về ladder: claude CLI quá 600s" in rep
    assert "ClaudeCode:claude-opus-5-5 · 1 call · 0 OK · 1 lỗi" in rep
    assert "memory #7" in rep and "1,200 ký tự" in rep and "sao —" in rep
    assert "raw 3 dòng → final 2 dòng · 2 dòng khác" in rep


def test_rate_brief_and_main_dispatch(monkeypatch, capsys):
    import vnstock_memory as _mem
    seen: dict = {}
    monkeypatch.setattr(_mem, "update_rating",
                        lambda bid, rating, feedback="": seen.update(bid=bid, r=rating, fb=feedback))
    assert bp.main(["--rate", "7", "5", "rất", "tốt"]) == 0
    assert seen == {"bid": 7, "r": 5, "fb": "rất tốt"}
    assert bp.main(["--rate", "7"]) == 2
    monkeypatch.setattr(bp, "review_report", lambda wh="data_warehouse": "REPORT")
    assert bp.main(["--review"]) == 0 and "REPORT" in capsys.readouterr().out
    monkeypatch.setattr(vcc, "cli_check", lambda: {"ok": False, "error": "x"})
    assert bp.main(["--check"]) == 1


# ─── skill tay phải nói đúng hợp đồng gói ───────────────────────────────────

def test_skill_brief_close_matches_pack_contract():
    skill = _REPO / ".claude" / "skills" / "brief-close" / "SKILL.md"
    src = skill.read_text(encoding="utf-8")
    assert src.startswith("---\nname: brief-close\n")
    for needle in (bp.PACK_NAME, bp.PROMPT_NAME, bp.OUT_NAME, "run.py brief --from-file",
                   "run.py brief --export-pack", "VNSTOCK_BRIEF_ENGINE=claude",
                   "vnstock_brief_pack.py --check"):
        assert needle in src, needle


def test_skill_brief_review_matches_cli_contract():
    skill = _REPO / ".claude" / "skills" / "brief-review" / "SKILL.md"
    src = skill.read_text(encoding="utf-8")
    assert src.startswith("---\nname: brief-review\n")
    for needle in ("vnstock_brief_pack.py --review", "vnstock_brief_pack.py --rate",
                   bp.RAW_NAME, bp.OUT_NAME, "brief_push.json"):
        assert needle in src, needle
