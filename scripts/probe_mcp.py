#!/usr/bin/env python3
"""
scripts/probe_mcp.py — Claude Code chạy NGẦM có thấy & gọi được 3 connector
MCP chứng khoán (SSI · TCBS · Finhay) không (08/10)
============================================================================
Vì sao: pipeline Python KHÔNG gọi thẳng được MCP — connector gắn với TÀI KHOẢN
Claude, không phải API có key (`scripts/export_bank_balance_sheets.py:23`).
Đường duy nhất cho bước tự động là `claude -p` qua `vnstock_claude_cli` — mà
wrapper đó CỐ Ý tắt MCP (`--strict-mcp-config`, `--tools ""`). Trước khi nối
connector vào mục ⚠️ Rủi ro (cổ phiếu chờ niêm yết, tin công bố HOSE…) phải đo
trên MÁY THẬT, dưới đúng tài khoản chạy task:

  1. `claude mcp list` — CLI thấy những server nào (không tốn token).
  2. Khám phá: 5 bộ cờ, đọc sự kiện `init` của `--output-format stream-json`
     (danh sách server + tool MCP) rồi DỪNG tiến trình ngay (gần 0 token):
       pipeline    = đúng cờ wrapper hiện nay (kỳ vọng: KHÔNG thấy connector)
       lean_ts     = tước settings/slash, BỎ --strict-mcp-config, công cụ có
                     sẵn chỉ còn ToolSearch (nạp schema tool MCP bị hoãn)
       lean_tools0 = như trên nhưng --tools "" (không cả ToolSearch)
       lean        = tước settings/slash, giữ công cụ có sẵn
       full        = không tước gì (nạp cả skill/rules của máy — đắt)
     Connector claude.ai nối chậm: lúc init hay còn `pending` ⇒ ◐, tên tool
     SUY từ tên server (đo 08/10: `claude.ai SSI MCP` ⇒ `mcp__claude_ai_SSI_MCP__…`).
  3. Gọi thử MỘT tool chỉ-đọc mỗi nguồn (`--allowedTools` đúng tên tool đó,
     thư mục làm việc rỗng), từ bộ cờ rẻ nhất, dừng ở bộ đầu tiên gọi được;
     xác nhận bằng sự kiện tool_use/tool_result THẬT trong stream — không tin
     lời model kể.

🖥️ DESKTOP, dưới tài khoản chạy task Daily:

    python scripts/probe_mcp.py              # đủ 3 bước (3 lượt model ngắn)
    python scripts/probe_mcp.py --no-call    # chỉ bước 1–2
    python scripts/probe_mcp.py --json       # in thêm kết quả thô
    python scripts/probe_mcp.py --with-full  # cho thử cả bộ cờ full (đắt, ~$0,3/lượt)

Dán TOÀN BỘ output cho Claude. CHỈ ĐỌC: không ghi kho, không ghi sổ LLM, không
đụng .env. Tool tài khoản Finhay (danh mục, sổ lệnh) KHÔNG BAO GIỜ được mở —
chỉ đúng 3 tool thị trường trong PROBE_TOOLS.
Exit: 0 = cả 3 nguồn gọi được · 1 = được một phần · 2 = không nguồn nào / CLI hỏng.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import vnstock_claude_cli as cc  # noqa: E402

# (nhãn, khoá dò trong TÊN SERVER, tên tool (phần sau `mcp__<server>__`),
#  khoá tham số mã). Tool nhỏ, chỉ đọc, thị trường — không tool tài khoản.
PROBE_TOOLS: tuple[tuple[str, str, str, str], ...] = (
    ("SSI", "ssi", "marketdata_list_share_holder_summary", "symbol"),
    ("TCBS", "tcbs", "tcinvest-getPriceVolatility", "ticker"),
    ("Finhay", "finhay", "get_stock_quote", "symbol"),
)

_LEAN = ["--setting-sources", "", "--disable-slash-commands"]
VARIANTS: dict[str, list[str]] = {
    "pipeline": ["--tools", "", *_LEAN, "--strict-mcp-config"],
    "lean_ts": ["--tools", "ToolSearch", *_LEAN],
    "lean_tools0": ["--tools", "", *_LEAN],
    "lean": list(_LEAN),
    "full": [],
}
# Bước 3 thử lần lượt, DỪNG ở biến thể đầu tiên gọi được. `full` nạp cả skill/
# rules/agent của máy (08/10 🖥️ desktop: $0,25–0,29/lượt Sonnet cho MỘT tool)
# ⇒ chỉ thử khi --with-full.
CALL_ORDER = ("lean_ts", "lean_tools0", "lean", "full")
# Connector claude.ai nối CHẬM: lúc `init` thường còn `pending` (08/10: cả 3
# pending ở lean, chỉ full kịp connected SSI/TCBS) — pending KHÔNG phải không có.
DEAD_STATUS = ("failed", "needs-auth")
# Nhiều tool MCP ⇒ CLI hoãn schema, model phải ToolSearch nạp trước — hợp lệ.
HELPER_TOOLS = ("ToolSearch",)
# Biến thể còn công cụ có sẵn: cấm hẳn nhóm ghi/chạy lệnh/mạng.
_DENY_BUILTINS = "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch"

CALL_SYSTEM = ("Bạn là bộ thử kết nối. Gọi tool được nêu trong tin nhắn đúng một lần "
               "với đúng tham số đã cho, được phép dùng ToolSearch để nạp tool đó trước, "
               "không gọi tool nào khác, rồi trả lời một dòng ngắn: OK hoặc LOI kèm lý do.")
DISCOVER_TIMEOUT_S = 90
CALL_TIMEOUT_S = 180
EXCERPT_CHARS = 300


# ── Hàm thuần (có test) ──────────────────────────────────────────────────────
def split_tool(name: str) -> "tuple[str, str] | None":
    """`mcp__<server>__<tool>` → (server, tool); tool có thể chứa `__`."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return None
    parts = name[5:].split("__", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def pick_tool(tools: list, key: str, suffix: str) -> "str | None":
    """Tên đầy đủ của tool `suffix` trên server có tên chứa `key` (không phân
    biệt hoa thường). Tên server tuỳ CLI (`SSI_MCP`, `claude_ai_SSI_MCP`…) nên
    dò theo khoá, không ghim cứng."""
    for t in tools or []:
        sp = split_tool(t)
        if sp and key.lower() in sp[0].lower() and sp[1] == suffix:
            return t
    return None


def server_prefix(server_name: str) -> str:
    """Tên server trong `mcp_servers` → tiền tố tool. Đo 08/10: server
    `claude.ai SSI MCP` ⇒ tool `mcp__claude_ai_SSI_MCP__…` (ký tự ngoài
    chữ/số/_/- thành `_`)."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", str(server_name)) + "__"


def find_init(events: list) -> "dict | None":
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "system" and ev.get("subtype") == "init":
            return ev
    return None


def discover_summary(init: "dict | None") -> dict:
    """Từ sự kiện init: server khớp từng nguồn (tên + trạng thái), số tool MCP
    của nguồn, và tool thử có mặt không."""
    out: dict = {"init": init is not None, "providers": {}, "mcp_tools": 0}
    # Server còn `pending` lúc init: tool chưa có trong danh sách ⇒ SUY tên tool
    # từ tên server (inferred) để bước 3 vẫn gọi thử.
    if init is None:
        return out
    tools = [t for t in (init.get("tools") or []) if isinstance(t, str)]
    servers = [s for s in (init.get("mcp_servers") or []) if isinstance(s, dict)]
    out["mcp_tools"] = sum(1 for t in tools if split_tool(t))
    for label, key, suffix, _ in PROBE_TOOLS:
        srv = [{"name": s.get("name"), "status": s.get("status")} for s in servers
               if key in str(s.get("name") or "").lower()]
        n = sum(1 for t in tools if (sp := split_tool(t)) and key in sp[0].lower())
        tool = pick_tool(tools, key, suffix)
        live = [x for x in srv if str(x.get("status") or "").lower() not in DEAD_STATUS]
        inferred = not tool and bool(live)
        if inferred:
            tool = server_prefix(live[0]["name"]) + suffix
        out["providers"][label] = {"servers": srv, "tools": n, "probe_tool": tool,
                                   "inferred": inferred}
    return out


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def call_summary(events: list, tool: str) -> dict:
    """Bằng chứng từ stream: tool `tool` có THẬT được gọi không, kết quả lỗi hay
    không, có gọi tool nào khác không, quyền bị từ chối, chi phí."""
    out: dict = {"called": 0, "is_error": None, "excerpt": "", "other_tools": [],
                 "helpers": 0, "denials": [], "result": None, "cost_usd": None,
                 "duration_ms": None, "subtype": None}
    ids: set = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
        if ev.get("type") == "assistant":
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    if b.get("name") == tool:
                        out["called"] += 1
                        ids.add(b.get("id"))
                    elif b.get("name") in HELPER_TOOLS:
                        out["helpers"] += 1
                    else:
                        out["other_tools"].append(str(b.get("name")))
        elif ev.get("type") == "user":
            for b in blocks:
                if (isinstance(b, dict) and b.get("type") == "tool_result"
                        and b.get("tool_use_id") in ids and not out["excerpt"]):
                    out["is_error"] = bool(b.get("is_error"))
                    out["excerpt"] = _result_text(b.get("content"))[:EXCERPT_CHARS]
        elif ev.get("type") == "result":
            out["result"] = str(ev.get("result") or "")[:200]
            out["cost_usd"] = ev.get("total_cost_usd")
            out["duration_ms"] = ev.get("duration_ms")
            out["subtype"] = ev.get("subtype")
            den = ev.get("permission_denials")
            if isinstance(den, list):
                out["denials"] = [str((d or {}).get("tool_name") or d) for d in den]
    out["ok"] = bool(out["called"]) and out["is_error"] is False
    return out


def base_cmd(exe: str, model: str) -> list[str]:
    return [exe, "-p", cc.TASK_LINE, "--output-format", "stream-json", "--verbose",
            "--model", model, "--no-session-persistence", "--permission-prompts", "none"]


def discovery_cmd(exe: str, model: str, variant: str) -> list[str]:
    return base_cmd(exe, model) + VARIANTS[variant]


def call_cmd(exe: str, model: str, variant: str, tool: str) -> list[str]:
    cmd = base_cmd(exe, model) + VARIANTS[variant]
    cmd += ["--system-prompt", CALL_SYSTEM, "--allowedTools", tool, "--max-turns", "3"]
    if "--tools" not in VARIANTS[variant]:
        cmd += ["--disallowedTools", _DENY_BUILTINS]
    return cmd


def call_variants(found: dict, label: str, with_full: bool = False) -> list[str]:
    """Các biến thể sẽ thử gọi cho nguồn `label`, theo CALL_ORDER (ít quyền/rẻ
    trước); `pipeline` không bao giờ — đó là cờ wrapper, phải KHÔNG thấy MCP."""
    order = CALL_ORDER if with_full else tuple(v for v in CALL_ORDER if v != "full")
    return [v for v in order
            if ((found.get(v) or {}).get("providers") or {}).get(label, {}).get("probe_tool")]


def exit_code(calls: dict) -> int:
    ok = sum(1 for c in calls.values() if c.get("ok"))
    if ok == len(PROBE_TOOLS):
        return 0
    return 1 if ok else 2


# ── Chạy tiến trình ──────────────────────────────────────────────────────────
def run_stream(cmd: list, stdin_text: str, timeout_s: int, *, stop_at_init: bool,
               cwd: str) -> "tuple[list, str | None, float]":
    """Chạy `claude -p … stream-json`, gom sự kiện JSON theo dòng. stop_at_init:
    thấy `init` là giết tiến trình (chưa kịp tốn token cho câu trả lời)."""
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", cwd=cwd, env=cc.cli_env())
    except OSError as e:
        return [], f"không chạy được: {type(e).__name__}: {str(e)[:120]}", 0.0
    lines: queue.Queue = queue.Queue()
    err_buf: list = []

    def _pump_out() -> None:
        for ln in proc.stdout:
            lines.put(ln)

    threading.Thread(target=_pump_out, daemon=True).start()
    threading.Thread(target=lambda: err_buf.append(proc.stderr.read()), daemon=True).start()
    try:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    except OSError:
        pass
    events: list = []
    err = None
    deadline = t0 + timeout_s
    while True:
        try:
            ln = lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and lines.empty():
                break
            if time.time() > deadline:
                err = f"quá {timeout_s}s"
                break
            continue
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        events.append(ev)
        if stop_at_init and find_init([ev]):
            break
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    if not events and err is None:
        tail = "".join(err_buf).strip().splitlines()
        err = f"rc={proc.returncode}: {(tail[-1] if tail else 'không in gì')[:200]}"
    return events, err, time.time() - t0


def mcp_list(exe: str) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120,
                           cwd=str(_REPO), env=cc.cli_env())
        raw = ((p.stdout or "") + (p.stderr or "")).strip()
        return {"rc": p.returncode, "elapsed_s": time.time() - t0, "lines": raw.splitlines()}
    except Exception as e:
        return {"rc": None, "elapsed_s": time.time() - t0,
                "lines": [f"{type(e).__name__}: {str(e)[:160]}"]}


# ── In kết quả ───────────────────────────────────────────────────────────────
def _fmt_discover(name: str, d: dict, err: "str | None", el: float) -> str:
    if not d.get("init"):
        return f"    {name:<12} ❌ không có sự kiện init ({err or 'CLI cũ?'}) · {el:,.0f}s"
    parts = []
    for label, info in d["providers"].items():
        if not info["servers"] and not info["tools"]:
            parts.append(f"{label} ✗")
            continue
        srv = ", ".join(f"{s['name']}:{s['status']}" for s in info["servers"]) or "?"
        mark = ("✓" if info["probe_tool"] and not info.get("inferred")
                else "◐" if info["probe_tool"] else "⛔")
        parts.append(f"{label} {mark} ({srv}; {info['tools']} tool)")
    return f"    {name:<12} {d['mcp_tools']} tool MCP · " + " · ".join(parts)


def _fmt_call(label: str, c: dict) -> str:
    if c.get("skipped"):
        return f"    {label:<7} ⏭ {c['skipped']}"
    head = "✅" if c.get("ok") else "❌"
    cost = c.get("cost_usd")
    cost_s = f" · ${cost:,.3f}" if isinstance(cost, (int, float)) else ""
    bits = [f"{head} [{c['variant']}] {c['tool']}", f"{float(c.get('elapsed_s') or 0):,.0f}s{cost_s}"]
    if not c.get("called"):
        bits.append("model KHÔNG gọi tool")
    if c.get("denials"):
        bits.append("bị từ chối quyền: " + ", ".join(c["denials"]))
    if c.get("helpers"):
        bits.append(f"ToolSearch ×{c['helpers']}")
    if c.get("other_tools"):
        bits.append("gọi thêm tool lạ: " + ", ".join(c["other_tools"]))
    if c.get("error"):
        bits.append(c["error"])
    line = f"    {label:<7} " + " · ".join(bits)
    if c.get("excerpt"):
        line += "\n            ↳ " + c["excerpt"].replace("\n", " ")[:EXCERPT_CHARS]
    return line


def conclusions(found: dict, calls: dict) -> list[str]:
    out = []
    pipe = (found.get("pipeline") or {}).get("providers") or {}
    if any(v.get("tools") for v in pipe.values()):
        out.append("⚠️ Cờ wrapper hiện nay VẪN thấy tool MCP — --strict-mcp-config không "
                   "chặn connector; báo Claude (brief/news đang chạy với MCP trong tầm).")
    else:
        out.append("✅ Cờ wrapper hiện nay không thấy connector (đúng thiết kế).")
    ok = [k for k, c in calls.items() if c.get("ok")]
    if calls:
        out.append(f"Gọi được: {', '.join(ok) or 'không nguồn nào'} / {len(PROBE_TOOLS)}.")
        for k in ok:
            c = calls[k]
            cost = c.get("cost_usd")
            cost_s = f" · ${cost:,.3f}/lượt" if isinstance(cost, (int, float)) else ""
            out.append(f"  {k}: biến thể {c['variant']}{cost_s}")
        if ok and all(calls[k]["variant"] != "full" for k in ok):
            out.append("✅ Bộ cờ gọn (không nạp skill/rules của máy) gọi được — dùng cho bước tự động.")
        elif ok:
            out.append("⚠️ Chỉ bộ cờ `full` gọi được — đắt, chưa nên chạy hằng đêm.")
    return out


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Claude Code headless có gọi được MCP SSI/TCBS/Finhay?")
    ap.add_argument("--symbol", default="SHB", help="mã dùng để gọi thử (mặc định SHB)")
    ap.add_argument("--model", default=None,
                    help=f"model cho lượt gọi thử (mặc định {cc.DEFAULT_FALLBACK_MODEL} — rẻ)")
    ap.add_argument("--no-call", action="store_true", help="chỉ bước 1–2, không gọi tool")
    ap.add_argument("--with-full", action="store_true",
                    help="cho phép thử cả biến thể full (nạp skill/rules của máy — đắt)")
    ap.add_argument("--json", action="store_true", help="in thêm kết quả thô dạng JSON")
    a = ap.parse_args(argv)

    cc._ensure_env_loaded()
    exe = cc.cli_executable()
    model = a.model or cc.DEFAULT_FALLBACK_MODEL
    print(f"[probe-mcp] máy {socket.gethostname()} · exe {exe or '—'} · model {model}")
    if not exe:
        print("    ❌ không thấy `claude` — chạy `python vnstock_claude_cli.py --check` trước")
        return 2

    ml = mcp_list(exe)
    keep = [ln for ln in ml["lines"] if any(k in ln.lower() for _, k, _, _ in PROBE_TOOLS)]
    print(f"[1] claude mcp list · rc={ml['rc']} · {ml['elapsed_s']:,.0f}s · "
          f"{len(ml['lines'])} dòng, {len(keep)} dòng khớp ssi/tcbs/finhay")
    for ln in (keep or ml["lines"][:15]):
        print(f"    {ln[:160]}")

    print("[2] Khám phá (sự kiện init của stream-json, dừng ngay sau init):")
    found: dict = {}
    raw: dict = {"mcp_list": ml, "discover": {}, "calls": {}}
    for name in VARIANTS:
        events, err, el = run_stream(discovery_cmd(exe, model, name), "Trả lời đúng một chữ: OK",
                                     DISCOVER_TIMEOUT_S, stop_at_init=True, cwd=str(_REPO))
        found[name] = discover_summary(find_init(events))
        raw["discover"][name] = {"error": err, "elapsed_s": el, **found[name]}
        print(_fmt_discover(name, found[name], err, el))

    calls: dict = {}
    if not a.no_call:
        print(f"[3] Gọi thử 1 tool chỉ-đọc mỗi nguồn (mã {a.symbol}, thư mục làm việc rỗng):")
        for label, key, suffix, arg in PROBE_TOOLS:
            variants = call_variants(found, label, with_full=a.with_full)
            if not variants:
                calls[label] = {"skipped": f"không biến thể nào thấy server/tool {suffix}"}
                print(_fmt_call(label, calls[label]))
                continue
            raw["calls"][label] = []
            for variant in variants:          # dừng ở biến thể đầu tiên gọi được
                tool = found[variant]["providers"][label]["probe_tool"]
                msg = (f"Tool: {tool}\nTham số JSON: {json.dumps({arg: a.symbol})}\n"
                       f"Nếu tool chưa có sẵn: gọi ToolSearch với query select:{tool} để nạp.")
                with tempfile.TemporaryDirectory(prefix="probe_mcp_") as tmp:
                    events, err, el = run_stream(call_cmd(exe, model, variant, tool), msg,
                                                 CALL_TIMEOUT_S, stop_at_init=False, cwd=tmp)
                c = call_summary(events, tool)
                c.update({"variant": variant, "tool": tool, "error": err, "elapsed_s": el})
                calls[label] = c
                raw["calls"][label].append(c)
                print(_fmt_call(label, c))
                if c["ok"]:
                    break

    print("[Kết luận]")
    for ln in conclusions(found, calls):
        print(f"    {ln}")
    if a.json:
        print(json.dumps(raw, ensure_ascii=False, indent=2, default=str))
    if calls:
        return exit_code(calls)
    seen = any(v.get("probe_tool") for d in found.values() for v in d["providers"].values())
    return 0 if seen else 2


if __name__ == "__main__":
    raise SystemExit(main())
