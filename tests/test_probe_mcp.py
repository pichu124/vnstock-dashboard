"""scripts/probe_mcp.py — Claude Code headless có thấy/gọi được MCP SSI·TCBS·Finhay (08/10).

Hermetic: không gọi `claude` thật. Tiến trình giả là `python -c` in dòng JSON
giống `--output-format stream-json` để thử máy đọc stream + dừng ở init."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probe_mcp", _REPO / "scripts" / "probe_mcp.py")
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)

SSI_TOOL = "mcp__claude_ai_SSI_MCP__marketdata_list_share_holder_summary"
TCBS_TOOL = "mcp__TCBS_MCP__tcinvest-getPriceVolatility"
FIN_TOOL = "mcp__Finhay__get_stock_quote"


def _init(tools, servers):
    return {"type": "system", "subtype": "init", "tools": tools, "mcp_servers": servers}


# ── tên tool ────────────────────────────────────────────────────────────────
def test_split_tool_handles_double_underscore_in_tool_part():
    assert pm.split_tool("mcp__SSI_MCP__a__b") == ("SSI_MCP", "a__b")
    assert pm.split_tool(FIN_TOOL) == ("Finhay", "get_stock_quote")


def test_split_tool_rejects_builtin_and_malformed():
    for bad in ("Bash", "mcp__", "mcp__X", "mcp____tool", None, 3):
        assert pm.split_tool(bad) is None


def test_pick_tool_matches_server_by_key_any_prefix_and_case():
    tools = ["Bash", SSI_TOOL, TCBS_TOOL, FIN_TOOL]
    assert pm.pick_tool(tools, "ssi", "marketdata_list_share_holder_summary") == SSI_TOOL
    assert pm.pick_tool(tools, "tcbs", "tcinvest-getPriceVolatility") == TCBS_TOOL


def test_pick_tool_needs_exact_tool_name_and_right_server():
    tools = ["mcp__OtherBroker__get_stock_quote", "mcp__Finhay__get_stock_quote_history"]
    assert pm.pick_tool(tools, "finhay", "get_stock_quote") is None


def test_probe_tools_never_include_account_tools():
    account = {"get_portfolio_positions", "get_order_history", "get_order_detail",
               "get_account_summary", "get_asset_summary", "get_pnl_today",
               "get_my_profile", "get_user_rights"}
    assert not {suffix for _, _, suffix, _ in pm.PROBE_TOOLS} & account


# ── khám phá ────────────────────────────────────────────────────────────────
def test_discover_summary_without_init():
    d = pm.discover_summary(None)
    assert d["init"] is False and d["providers"] == {}


def test_discover_summary_counts_tools_and_servers_per_provider():
    init = _init(["Bash", SSI_TOOL, "mcp__claude_ai_SSI_MCP__x", FIN_TOOL],
                 [{"name": "claude_ai_SSI_MCP", "status": "connected"},
                  {"name": "Finhay", "status": "needs-auth"}])
    d = pm.discover_summary(init)
    assert d["init"] and d["mcp_tools"] == 3
    assert d["providers"]["SSI"] == {"servers": [{"name": "claude_ai_SSI_MCP", "status": "connected"}],
                                     "tools": 2, "probe_tool": SSI_TOOL, "inferred": False}
    assert d["providers"]["Finhay"]["probe_tool"] == FIN_TOOL
    assert d["providers"]["TCBS"] == {"servers": [], "tools": 0, "probe_tool": None,
                                      "inferred": False}


def test_server_prefix_matches_desktop_naming_0810():
    # 🖥️ 08/10: server `claude.ai SSI MCP` ⇒ tool `mcp__claude_ai_SSI_MCP__…`
    assert pm.server_prefix("claude.ai SSI MCP") + "x" == "mcp__claude_ai_SSI_MCP__x"
    assert pm.server_prefix("claude.ai TCBS MCP") == "mcp__claude_ai_TCBS_MCP__"
    assert pm.server_prefix("claude.ai Finhay") == "mcp__claude_ai_Finhay__"


def test_pending_server_gets_inferred_tool_name():
    # Vết 08/10: lean thấy 3 server `pending`, 0 tool ⇒ bản đầu bỏ qua oan Finhay.
    init = _init(["Bash"], [{"name": "claude.ai Finhay", "status": "pending"},
                            {"name": "claude.ai SSI MCP", "status": "pending"}])
    d = pm.discover_summary(init)
    assert d["providers"]["Finhay"]["probe_tool"] == "mcp__claude_ai_Finhay__get_stock_quote"
    assert d["providers"]["Finhay"]["inferred"] is True
    assert d["providers"]["SSI"]["probe_tool"] == SSI_TOOL


def test_dead_server_is_not_probed():
    init = _init([], [{"name": "claude.ai Finhay", "status": "needs-auth"},
                      {"name": "claude.ai TCBS MCP", "status": "failed"}])
    d = pm.discover_summary(init)
    assert d["providers"]["Finhay"]["probe_tool"] is None
    assert d["providers"]["TCBS"]["probe_tool"] is None


def test_find_init_skips_other_system_events():
    evs = [{"type": "active_goal"}, {"type": "system", "subtype": "x"}, _init([], [])]
    assert pm.find_init(evs)["subtype"] == "init"
    assert pm.find_init([{"type": "result"}]) is None


def test_call_variants_cheapest_first_full_only_on_request():
    have = {"providers": {"SSI": {"probe_tool": SSI_TOOL}}}
    none = {"providers": {"SSI": {"probe_tool": None}}}
    found = {"lean": have, "lean_ts": have, "lean_tools0": none, "full": have}
    assert pm.call_variants(found, "SSI") == ["lean_ts", "lean"]
    assert pm.call_variants(found, "SSI", with_full=True) == ["lean_ts", "lean", "full"]
    # pipeline KHÔNG bao giờ là biến thể gọi thử (đó là cờ wrapper hiện nay)
    assert pm.call_variants({"pipeline": have}, "SSI", with_full=True) == []


# ── dòng lệnh ───────────────────────────────────────────────────────────────
def test_pipeline_variant_mirrors_wrapper_flags():
    cmd = pm.discovery_cmd("claude", "m", "pipeline")
    i = cmd.index("--tools")
    assert cmd[i + 1] == "" and "--strict-mcp-config" in cmd
    assert "--setting-sources" in cmd and "--disable-slash-commands" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json" and "--verbose" in cmd


def test_lean_ts_keeps_only_toolsearch_builtin():
    cmd = pm.call_cmd("claude", "m", "lean_ts", SSI_TOOL)
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch"
    assert "--strict-mcp-config" not in cmd and "--disallowedTools" not in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""


def test_call_cmd_allows_only_the_probe_tool():
    cmd = pm.call_cmd("claude", "m", "lean_tools0", SSI_TOOL)
    assert cmd[cmd.index("--allowedTools") + 1] == SSI_TOOL
    assert "--strict-mcp-config" not in cmd and "--disallowedTools" not in cmd
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"


def test_call_cmd_denies_builtins_when_variant_keeps_them():
    for v in ("lean", "full"):
        cmd = pm.call_cmd("claude", "m", v, FIN_TOOL)
        deny = cmd[cmd.index("--disallowedTools") + 1]
        assert {"Bash", "Write", "Edit", "WebFetch"} <= set(deny.split(","))


def test_call_system_prompt_is_shim_safe():
    # claude.cmd (npm shim) đọc lại argv qua cmd.exe — xem vnstock_claude_cli.is_shim
    assert not set("|<>%\n\"") & set(pm.CALL_SYSTEM)


# ── bằng chứng gọi tool ─────────────────────────────────────────────────────
def _use(tid, name):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def _res(tid, content, is_error=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": is_error}]}}


def _final(**kw):
    return {"type": "result", "subtype": "success", "result": "OK",
            "total_cost_usd": 0.012, "duration_ms": 4200, **kw}


def test_call_summary_ok_with_excerpt():
    evs = [_use("t1", SSI_TOOL), _res("t1", [{"type": "text", "text": '{"status":"ok"}'}]), _final()]
    c = pm.call_summary(evs, SSI_TOOL)
    assert c["ok"] and c["called"] == 1 and c["excerpt"] == '{"status":"ok"}'
    assert c["cost_usd"] == 0.012 and c["other_tools"] == [] and c["denials"] == []


def test_call_summary_error_result_is_not_ok():
    evs = [_use("t1", FIN_TOOL), _res("t1", "401 needs auth", is_error=True), _final()]
    c = pm.call_summary(evs, FIN_TOOL)
    assert c["called"] == 1 and c["is_error"] is True and not c["ok"]
    assert c["excerpt"] == "401 needs auth"


def test_call_summary_model_claiming_ok_without_tool_use_is_not_ok():
    c = pm.call_summary([_final(result="OK đã gọi")], SSI_TOOL)
    assert c["called"] == 0 and not c["ok"]


def test_call_summary_toolsearch_is_helper_not_stranger():
    # Vết 08/10: full gọi ToolSearch trước tool MCP (schema bị hoãn) — hợp lệ.
    evs = [_use("s1", "ToolSearch"), _use("t1", SSI_TOOL), _res("t1", "{}"), _final()]
    c = pm.call_summary(evs, SSI_TOOL)
    assert c["ok"] and c["helpers"] == 1 and c["other_tools"] == []


def test_call_summary_reports_denials_and_other_tools():
    evs = [_use("t9", "Bash"), _final(permission_denials=[{"tool_name": SSI_TOOL}])]
    c = pm.call_summary(evs, SSI_TOOL)
    assert c["other_tools"] == ["Bash"] and c["denials"] == [SSI_TOOL] and not c["ok"]


def test_call_summary_ignores_results_of_other_tool_ids():
    evs = [_use("t1", SSI_TOOL), _res("zz", "khác"), _res("t1", "đúng"), _final()]
    assert pm.call_summary(evs, SSI_TOOL)["excerpt"] == "đúng"


def test_exit_code():
    ok, bad = {"ok": True}, {"ok": False}
    assert pm.exit_code({"SSI": ok, "TCBS": ok, "Finhay": ok}) == 0
    assert pm.exit_code({"SSI": ok, "TCBS": bad, "Finhay": bad}) == 1
    assert pm.exit_code({"SSI": bad, "TCBS": bad, "Finhay": {"skipped": "x"}}) == 2


def test_conclusions_name_variant_and_warn_when_only_full():
    clean = {"pipeline": {"providers": {"SSI": {"tools": 0}}}}
    lean = {"SSI": {"ok": True, "variant": "lean_ts", "cost_usd": 0.03}}
    out = pm.conclusions(clean, lean)
    assert any("lean_ts" in ln and "$0.030" in ln for ln in out)
    assert any(ln.startswith("✅ Bộ cờ gọn") for ln in out)
    full = {"SSI": {"ok": True, "variant": "full", "cost_usd": 0.29}}
    assert any(ln.startswith("⚠️ Chỉ bộ cờ `full`") for ln in pm.conclusions(clean, full))


def test_conclusions_flag_wrapper_leak():
    leak = {"pipeline": {"providers": {"SSI": {"tools": 5}}}}
    assert pm.conclusions(leak, {})[0].startswith("⚠️")
    clean = {"pipeline": {"providers": {"SSI": {"tools": 0}}}}
    assert pm.conclusions(clean, {})[0].startswith("✅")


# ── máy đọc stream (tiến trình giả) ─────────────────────────────────────────
def _fake(lines, sleep_s=0.0, rc=0, stderr=""):
    body = "".join(f"print({json.dumps(ln)}, flush=True)\n" for ln in lines)
    body += f"import sys,time\nsys.stderr.write({stderr!r})\ntime.sleep({sleep_s})\nsys.exit({rc})\n"
    return [sys.executable, "-c", body]


def test_run_stream_stops_right_after_init(tmp_path):
    lines = ['{"type":"active_goal"}', json.dumps(_init([SSI_TOOL], []))]
    t0 = time.time()
    evs, err, _ = pm.run_stream(_fake(lines, sleep_s=30), "OK", 20, stop_at_init=True, cwd=str(tmp_path))
    assert err is None and pm.find_init(evs) and time.time() - t0 < 15


def test_run_stream_reads_to_end_and_skips_non_json(tmp_path):
    lines = ["banner không phải JSON", json.dumps(_final())]
    evs, err, _ = pm.run_stream(_fake(lines), "x", 20, stop_at_init=False, cwd=str(tmp_path))
    assert err is None and [e["type"] for e in evs] == ["result"]


def test_run_stream_no_output_reports_rc_and_stderr(tmp_path):
    evs, err, _ = pm.run_stream(_fake([], rc=3, stderr="chưa đăng nhập"), "x", 20,
                                stop_at_init=False, cwd=str(tmp_path))
    assert evs == [] and "rc=3" in err and "chưa đăng nhập" in err


def test_run_stream_timeout(tmp_path):
    evs, err, _ = pm.run_stream(_fake(['{"type":"active_goal"}'], sleep_s=30), "x", 1,
                                stop_at_init=True, cwd=str(tmp_path))
    assert err == "quá 1s"


def test_main_without_cli_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(pm.cc, "cli_executable", lambda: None)
    assert pm.main(["--no-call"]) == 2
    assert "không thấy `claude`" in capsys.readouterr().out
