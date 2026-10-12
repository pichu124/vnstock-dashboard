"""vnstock_claude_cli — Claude Code headless (`claude -p`) làm backend LLM DÙNG CHUNG.

Một lượt gọi = một tiến trình `claude -p` chạy ngầm dưới tài khoản đã đăng
nhập thuê bao (không key API): prompt vào STDIN, kết quả ra JSON. Dùng cho
brief chiều (`vnstock_brief_pack`) và các nấc `claude-cli` ở digest/
reflection/auditor/sentiment (30/09, U62). Mọi điểm gọi đi qua `complete()`
để cờ CLI, sổ LLM, giấu key, timeout chỉ có MỘT bản.

Đã đo trên CLI 2.1.285 (30/09): không tước context thì mỗi call kéo ~20K
token system prompt của Claude Code (CLAUDE.md, skill, MCP); với
`--system-prompt` + `--setting-sources ""` + `--disable-slash-commands` +
`--strict-mcp-config` còn ~1,1–1,6K. `--tools ""` = không công cụ ⇒ một lượt
chữ; `--json-schema` trả thêm `structured_output` (dict) bên cạnh `result`.

Nút vặn (đọc từ `.env` của MÁY chạy — không đồng bộ Dropbox):
  VNSTOCK_LLM_ENGINE            claude | ladder — công tắc CHUNG cho mọi bước
  VNSTOCK_<BƯỚC>_ENGINE         đè riêng từng bước (BRIEF/NEWS/AUDIT/TRAIN/
                                REFLECTION/DIGEST); trống = theo công tắc chung
  VNSTOCK_CLAUDE_CLI_EXE        đường dẫn `claude` (Task Scheduler dùng PATH
                                registry — nên ghim); alias VNSTOCK_BRIEF_CLI_EXE
  VNSTOCK_CLAUDE_CLI_MODEL      mặc định claude-opus-5-5
  VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL  mặc định claude-sonnet-5-5; "off" = tắt
  VNSTOCK_CLAUDE_CLI_TIMEOUT_S  mặc định 600
  VNSTOCK_CLAUDE_CLI_API_KEY    =1 mới cho CLI thấy ANTHROPIC_API_KEY (tính
                                tiền API thay vì thuê bao); alias …BRIEF_CLI_API_KEY
  VNSTOCK_CLAUDE_CLI_REPO_CONTEXT =1 tải lại CLAUDE.md/skill/MCP vào call
  VNSTOCK_MCP_CLI_MODEL         model cho lượt gọi connector MCP (`complete_mcp`,
                                mặc định claude-sonnet-5-5 — chỉ gọi tool, không viết)
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent

LEDGER_PROVIDER = "ClaudeCode"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_FALLBACK_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT_S = 600

ENGINE_LADDER = "ladder"
ENGINE_CLAUDE = "claude"
ENGINES = (ENGINE_LADDER, ENGINE_CLAUDE)
GLOBAL_ENGINE_ENV = "VNSTOCK_LLM_ENGINE"
STEP_ENGINE_ENV = {
    "brief": "VNSTOCK_BRIEF_ENGINE",
    "news": "VNSTOCK_NEWS_ENGINE",
    "audit": "VNSTOCK_AUDIT_ENGINE",
    "train": "VNSTOCK_TRAIN_ENGINE",
    "reflection": "VNSTOCK_REFLECTION_ENGINE",
    "digest": "VNSTOCK_DIGEST_ENGINE",
    "news_alert": "VNSTOCK_NEWS_ALERT_ENGINE",   # cảnh báo tin mỗi giờ (02/10, #31)
}

TASK_LINE = "Làm theo hướng dẫn hệ thống với nội dung nhận vào từ stdin."
_OFF = ("0", "false", "off", "no", "none")
_ENV_LOADED = False

# Memo "CLI chết" TRONG TIẾN TRÌNH (thẩm định 30/09): không có exe, không chạy
# được, treo quá trần, rc≠0 (chưa đăng nhập) ⇒ mọi lượt gọi sau trong cùng
# tiến trình trả lỗi NGAY thay vì mỗi điểm gọi lại đợi hết timeout (news
# ⌈N/50⌉×300s + audit + reflection ≤3×300s… ⇒ đêm CLI treo ăn hết trần 240′).
# Lỗi API (is_error, quá tải) KHÔNG memo — lượt sau có thể qua. Tiến trình
# con (train/reflection) có memo riêng — vẫn chặn được 30×300s trong bước đó.
_DEAD_REASON: "str | None" = None


def reset_dead_memo() -> None:
    global _DEAD_REASON
    _DEAD_REASON = None


def _mark_dead(reason: str) -> None:
    global _DEAD_REASON
    if _DEAD_REASON is None:
        _DEAD_REASON = reason
        print(f"[claude-cli] ⛔ ghi nhớ trong tiến trình: {reason[:120]} — các lượt "
              "gọi sau trả lỗi ngay, không đợi timeout")


def _ensure_env_loaded() -> None:
    """`.env` vào os.environ đúng một lần, không đè biến shell — engine phải
    đọc ĐƯỢC cờ trong .env dù `run.py brief` chạy một mình (lỗi giám khảo
    30/09: chọn engine trước khi ai load .env ⇒ âm thầm ladder)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass
    _ENV_LOADED = True


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return default


def engine_for(step: str) -> str:
    """Engine của một bước: env riêng bước > VNSTOCK_LLM_ENGINE > ladder.
    Chữ lạ = ladder (không bao giờ ném)."""
    _ensure_env_loaded()
    raw = _env(STEP_ENGINE_ENV.get(step, ""), GLOBAL_ENGINE_ENV).lower()
    return raw if raw in ENGINES else ENGINE_LADDER


def cli_model(*override_envs: str) -> str:
    return _env(*override_envs, "VNSTOCK_CLAUDE_CLI_MODEL", default=DEFAULT_MODEL)


def cli_fallback_model() -> "str | None":
    raw = os.environ.get("VNSTOCK_CLAUDE_CLI_FALLBACK_MODEL")
    if raw is None:
        return DEFAULT_FALLBACK_MODEL
    raw = raw.strip()
    return None if raw.lower() in ("", *_OFF) else raw


def cli_timeout_s(*override_envs: str) -> int:
    raw = _env(*override_envs, "VNSTOCK_CLAUDE_CLI_TIMEOUT_S")
    try:
        return max(30, int(raw)) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S


_SHIM_SUFFIXES = (".cmd", ".bat")


def is_shim(exe: "str | None") -> bool:
    """`claude.cmd`/`.bat` (npm) = cmd.exe đọc lại argv ⇒ `|`, `<`, `>`, `%`,
    xuống dòng trong `--system-prompt`/`--json-schema` bị hiểu là pipe/
    redirect/hết dòng. Bản cài native là `claude.exe` — không có chuyện đó."""
    return bool(exe) and str(exe).lower().endswith(_SHIM_SUFFIXES)


def cli_executable() -> "str | None":
    exe = _env("VNSTOCK_CLAUDE_CLI_EXE", "VNSTOCK_BRIEF_CLI_EXE")
    if exe:
        return exe if Path(exe).exists() else None
    found = shutil.which("claude")
    if is_shim(found):
        # Ưu tiên claude.exe của bộ cài native (cùng máy) trước shim npm.
        native = Path.home() / ".local" / "bin" / "claude.exe"
        if native.exists():
            return str(native)
    return found


def cli_env() -> dict:
    """Môi trường cho tiến trình CLI: GIẤU ANTHROPIC_API_KEY (có key là CLI
    lặng lẽ chuyển sang tính tiền API), tắt tự cập nhật (task đêm không được
    đổi binary giữa chừng)."""
    env = dict(os.environ)
    keep = _env("VNSTOCK_CLAUDE_CLI_API_KEY", "VNSTOCK_BRIEF_CLI_API_KEY").lower()
    if keep in ("", *_OFF):
        env.pop("ANTHROPIC_API_KEY", None)
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    return env


def repo_context_wanted() -> bool:
    return _env("VNSTOCK_CLAUDE_CLI_REPO_CONTEXT").lower() not in ("", *_OFF)


# Ký tự cmd.exe đọc lại khi `claude` là shim `.cmd` của npm: xuống dòng CẮT argv (12/10
# 🖥️: hướng dẫn chấm tin chỉ còn "… Với TỪNG bài, chấm:" — Claude tự chế tiêu chí, trả
# chữ thay JSON); `|<>&^%` là pipe/redirect/biến. Có ký tự nào ⇒ system qua FILE.
_SHIM_UNSAFE = ("\n", "\r", "|", "<", ">", "&", "^", "%")


def system_needs_file(exe: "str | None", system: "str | None") -> bool:
    return bool(system) and is_shim(exe) and any(ch in system for ch in _SHIM_UNSAFE)


def cli_command(exe: str, model: str, *, system: "str | None" = None,
                system_file: "str | None" = None,
                fallback_model: "str | None" = None,
                json_schema: "dict | None" = None,
                effort: "str | None" = None,
                repo_context: "bool | None" = None,
                tools: str = "") -> list[str]:
    """Dòng lệnh `claude -p` — mọi cờ đã kiểm trên 2.1.285 `--help` + chạy thử.
    `tools` (vd "Read" — đọc ảnh báo cáo, 04/10) bật ĐÚNG các công cụ đó;
    mặc định "" = không công cụ nào. CỐ Ý không `--allowedTools`: thử 2.1.289,
    `--tools Read --permission-prompts none` đọc được file TRONG cwd còn file
    ngoài cwd bị từ chối; thêm `--allowedTools Read` thì đọc được CẢ file ngoài
    (chữ trong ảnh báo cáo bảo "đọc .env" là lộ). Cùng lý do: có công cụ thì
    luôn tước settings người dùng — rule allow ở đó không được nới quyền."""
    cmd = [exe, "-p", TASK_LINE, "--output-format", "json", "--model", model,
           "--tools", tools, "--no-session-persistence",
           "--permission-prompts", "none"]
    if tools:
        repo_context = False
    if repo_context is None:
        repo_context = repo_context_wanted()
    if not repo_context:
        cmd += ["--setting-sources", "", "--disable-slash-commands",
                "--strict-mcp-config"]
    if system_file:                       # shim npm: argv không chở được prompt nhiều dòng
        cmd += ["--system-prompt-file", system_file]
    elif system:
        cmd += ["--system-prompt", system]
    if fallback_model:
        cmd += ["--fallback-model", fallback_model]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def _real_model(body: dict) -> "str | None":
    """Model THẬT đã trả lời (khác `--model` khi CLI tự fallback): khoá trong
    `modelUsage` có output lớn nhất."""
    mu = body.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return None
    best, best_out = None, -1
    for k, v in mu.items():
        out = int((v or {}).get("outputTokens") or 0) if isinstance(v, dict) else 0
        if out > best_out:
            best, best_out = k, out
    return best


def parse_cli_output(stdout: str) -> "tuple[str, str | None, dict]":
    """(chữ, lỗi, info) từ stdout của `claude -p --output-format json`.
    stdout KHÔNG phải JSON là LỖI (giám khảo 30/09: đây là đường duy nhất chữ
    SAI — banner, cảnh báo — có thể lên Telegram nếu nhận làm brief).
    info: usage kiểu OpenAI (cache token cộng vào prompt), cost_usd,
    duration_ms, model (thật), structured (dict khi --json-schema)."""
    raw = (stdout or "").strip()
    if not raw:
        return "", "CLI không in gì (stdout rỗng)", {}
    try:
        body = json.loads(raw)
    except ValueError:
        return "", f"CLI in không phải JSON (đã yêu cầu --output-format json): {raw[:120]}", {}
    if not isinstance(body, dict):
        return "", "CLI in JSON không phải object", {}
    info: dict = {}
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    if usage:
        p_in = int(usage.get("input_tokens") or 0)
        p_in += int(usage.get("cache_read_input_tokens") or 0)
        p_in += int(usage.get("cache_creation_input_tokens") or 0)
        info["usage"] = {"prompt_tokens": p_in,
                         "completion_tokens": int(usage.get("output_tokens") or 0)}
    if body.get("total_cost_usd") is not None:
        try:
            info["cost_usd"] = float(body["total_cost_usd"])
        except (TypeError, ValueError):
            pass
    if body.get("duration_ms") is not None:
        info["duration_ms"] = body.get("duration_ms")
    if (m := _real_model(body)):
        info["model"] = m
    if isinstance(body.get("structured_output"), dict):
        info["structured"] = body["structured_output"]
    text = body.get("result")
    text = text if isinstance(text, str) else ""
    if body.get("is_error"):
        return "", f"CLI báo lỗi: {(text or body.get('subtype') or '?')[:200]}", info
    if not text.strip() and not info.get("structured"):
        return "", f"CLI trả kết quả rỗng (subtype={body.get('subtype')})", info
    if not text.strip() and info.get("structured"):
        text = json.dumps(info["structured"], ensure_ascii=False)
    return text, None, info


def _ledger_record(provider: str, model: str, ok: bool,
                   usage: "dict | None" = None, error: "str | None" = None) -> None:
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


def complete(user: str, *, system: "str | None" = None,
             model: "str | None" = None,
             fallback_model: "str | None" = None,
             timeout_s: "int | None" = None,
             json_schema: "dict | None" = None,
             effort: "str | None" = None,
             exe: "str | None" = None,
             tag: str = "",
             tools: str = "",
             cwd: "str | None" = None) -> "tuple[str, str | None, dict]":
    """Một lượt Claude Code headless. Trả (chữ, lỗi, info); KHÔNG bao giờ ném.
    Sổ LLM ghi MỌI kết cục (kể cả không có exe) dưới provider `ClaudeCode`;
    OK chỉ khi có chữ thật. `fallback_model=None` = theo env; `""` = tắt.
    `tools`/`cwd`: bật công cụ (vd "Read") và thư mục làm việc — file công cụ
    được đọc nằm trong `cwd` (mặc định repo)."""
    _ensure_env_loaded()
    model = model or cli_model()
    if fallback_model is None:
        fallback_model = cli_fallback_model()
    timeout_s = timeout_s or cli_timeout_s()
    exe = exe or cli_executable()
    info: dict = {"requested_model": model, "tag": tag}
    if _DEAD_REASON:
        err = f"claude CLI đã chết trong tiến trình này: {_DEAD_REASON}"
        info["memo"] = True
        _ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
        return "", err, info
    if not exe:
        err = ("không tìm thấy lệnh `claude` (Claude Code CLI) trên PATH — cài CLI "
               "+ đăng nhập, hoặc đặt VNSTOCK_CLAUDE_CLI_EXE")
        _mark_dead(err)
        _ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
        return "", err, info
    sys_file = None
    if system_needs_file(exe, system):
        fd, sys_file = tempfile.mkstemp(prefix="vnstock_sys_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(system)
    cmd = cli_command(exe, model, system=system, system_file=sys_file,
                      fallback_model=fallback_model or None,
                      json_schema=json_schema, effort=effort, tools=tools)
    t0 = time.time()
    try:
        try:
            proc = subprocess.run(
                cmd, input=user, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout_s,
                cwd=str(cwd or _REPO), env=cli_env(),
            )
        except subprocess.TimeoutExpired:
            err = f"claude CLI quá {timeout_s}s — bỏ"
            info["elapsed_s"] = time.time() - t0
            _mark_dead(err)
            _ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
            return "", err, info
        except OSError as e:
            err = f"không chạy được claude CLI: {type(e).__name__}: {str(e)[:120]}"
            info["elapsed_s"] = time.time() - t0
            _mark_dead(err)
            _ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
            return "", err, info
    finally:
        if sys_file:                      # file tạm chở system prompt (shim) — dọn ngay
            try:
                os.unlink(sys_file)
            except OSError:
                pass
    text, err, parsed = parse_cli_output(proc.stdout)
    info.update(parsed)
    info["elapsed_s"] = time.time() - t0
    info.setdefault("model", model)
    info["fallback"] = info["model"] != model
    if proc.returncode != 0 and not text:
        tail = (proc.stderr or "").strip().splitlines()
        err = f"claude CLI rc={proc.returncode}: {(tail[-1] if tail else err or '?')[:200]}"
        _mark_dead(err)                 # chưa đăng nhập / binary hỏng: cả đêm như nhau
    if err:
        _ledger_record(LEDGER_PROVIDER, info["model"], ok=False,
                       usage=info.get("usage"), error=err)
        return "", err, info
    _ledger_record(LEDGER_PROVIDER, info["model"], ok=True, usage=info.get("usage"))
    return text, None, info


def outcome_line(tag: str, info: dict, text: str, err: "str | None") -> str:
    """`[<tag>] ⏱ claude-cli: Ns · ✅ N ký tự · $x [· ↘ fallback <model>]` —
    cùng nếp `_agent_outcome_line` để `Select-String '⏱ claude-cli'` gom được."""
    el = float(info.get("elapsed_s") or 0)
    cost = info.get("cost_usd")
    cost_s = f" · ${cost:,.2f}" if isinstance(cost, (int, float)) else ""
    fb = f" · ↘ fallback {info.get('model')}" if info.get("fallback") else ""
    if err:
        return f"[{tag}] ⏱ claude-cli: {el:,.0f}s · ❌ {err[:160]}"
    return f"[{tag}] ⏱ claude-cli: {el:,.0f}s · ✅ {len(text):,} ký tự{cost_s}{fb}"


# ── Gọi connector MCP (08/10, U78/U79) ──────────────────────────────────────
# Đo 🖥️ 08/10 (`scripts/probe_mcp.py`): connector claude.ai SSI/TCBS/Finhay gọi
# được với bộ cờ GỌN dưới đây — tước settings/slash nhưng KHÔNG
# `--strict-mcp-config`, công cụ có sẵn chỉ còn ToolSearch (nhiều tool MCP ⇒
# CLI hoãn schema, model phải ToolSearch nạp trước). ~$0,06/lượt Sonnet cho một
# tool; bộ cờ đầy đủ (nạp skill/rules của máy) ~$0,29. Lúc `init` connector
# thường còn `pending` — gọi vẫn được. `complete()` ở trên GIỮ NGUYÊN chặn MCP.
# Số liệu KHÔNG đi qua chữ model: chỗ gọi đọc thẳng `tool_result` trong stream.
MCP_LEAN_FLAGS = ("--tools", "ToolSearch", "--setting-sources", "",
                  "--disable-slash-commands")
MCP_HELPER_TOOLS = ("ToolSearch",)


def mcp_server_prefix(server_name: str) -> str:
    """Tên server trong `mcp_servers` → tiền tố tool. Đo 08/10: server
    `claude.ai SSI MCP` ⇒ tool `mcp__claude_ai_SSI_MCP__…` (ký tự ngoài
    chữ/số/_/- thành `_`)."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", str(server_name)) + "__"


def mcp_command(exe: str, model: str, *, system: str, allowed_tools,
                max_turns: int = 8, system_file: "str | None" = None) -> list[str]:
    """Dòng lệnh một lượt gọi connector: bộ cờ gọn + đúng các tool cho phép
    (để CUỐI vì `--allowedTools` nhận nhiều giá trị). `system_file`: shim npm."""
    sys_args = ["--system-prompt-file", system_file] if system_file else ["--system-prompt", system]
    return [exe, "-p", TASK_LINE, "--output-format", "stream-json", "--verbose",
            "--model", model, "--no-session-persistence", "--permission-prompts", "none",
            *MCP_LEAN_FLAGS, *sys_args, "--max-turns", str(max_turns),
            "--allowedTools", *list(allowed_tools)]


def run_stream_json(cmd: list, stdin_text: str, timeout_s: int, *,
                    stop_at_init: bool = False,
                    cwd: "str | None" = None) -> "tuple[list, str | None, float]":
    """Chạy `claude -p … --output-format stream-json`, gom sự kiện JSON theo
    dòng (dòng không phải JSON bỏ qua). `stop_at_init`: thấy sự kiện `init` là
    giết tiến trình (chưa kịp tốn token). Không bao giờ ném."""
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", cwd=cwd or str(_REPO), env=cli_env())
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
        if (stop_at_init and isinstance(ev, dict) and ev.get("type") == "system"
                and ev.get("subtype") == "init"):
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


def _block_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def tool_exchanges(events: list) -> list[dict]:
    """Cặp tool_use ↔ tool_result trong stream: `{id, name, input, text,
    is_error}` theo thứ tự gọi (`text`/`is_error` None khi chưa có kết quả)."""
    out: list[dict] = []
    by_id: dict = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if ev.get("type") == "assistant" and b.get("type") == "tool_use":
                rec = {"id": b.get("id"), "name": str(b.get("name") or ""),
                       "input": b.get("input") if isinstance(b.get("input"), dict) else {},
                       "text": None, "is_error": None}
                out.append(rec)
                by_id[rec["id"]] = rec
            elif (ev.get("type") == "user" and b.get("type") == "tool_result"
                    and b.get("tool_use_id") in by_id):
                rec = by_id[b["tool_use_id"]]
                if rec["text"] is None:
                    rec["text"] = _block_text(b.get("content"))
                    rec["is_error"] = bool(b.get("is_error"))
    return out


def result_event(events: list) -> "dict | None":
    for ev in reversed(events or []):
        if isinstance(ev, dict) and ev.get("type") == "result":
            return ev
    return None


def complete_mcp(user: str, *, system: str, allowed_tools,
                 model: "str | None" = None, timeout_s: int = 300,
                 max_turns: int = 8, exe: "str | None" = None,
                 tag: str = "") -> "tuple[list[dict], str | None, dict]":
    """Một lượt Claude Code gọi connector MCP. Trả (exchanges, lỗi, info) —
    exchanges = `tool_exchanges` của các tool ĐƯỢC PHÉP (ToolSearch bỏ ra);
    chỗ gọi tự đọc số từ `text`, không tin chữ model. Chạy trong thư mục tạm
    RỖNG. Sổ LLM ghi mọi kết cục (provider ClaudeCode). Không bao giờ ném."""
    _ensure_env_loaded()
    model = model or _env("VNSTOCK_MCP_CLI_MODEL", default=DEFAULT_FALLBACK_MODEL)
    exe = exe or cli_executable()
    info: dict = {"requested_model": model, "tag": tag}
    if not exe:
        err = ("không tìm thấy lệnh `claude` (Claude Code CLI) trên PATH — cài CLI "
               "+ đăng nhập, hoặc đặt VNSTOCK_CLAUDE_CLI_EXE")
        info["no_exe"] = True
        _ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
        return [], err, info
    allowed = list(allowed_tools)
    with tempfile.TemporaryDirectory(prefix="vnstock_mcp_") as tmp:
        sys_file = None
        if system_needs_file(exe, system):            # shim npm: system qua file (12/10)
            sys_file = str(Path(tmp) / "system.txt")
            Path(sys_file).write_text(system, encoding="utf-8")
        cmd = mcp_command(exe, model, system=system, allowed_tools=allowed,
                          max_turns=max_turns, system_file=sys_file)
        events, run_err, elapsed = run_stream_json(cmd, user, timeout_s, cwd=tmp)
    info["elapsed_s"] = elapsed
    ex = tool_exchanges(events)
    info["helpers"] = sum(1 for e in ex if e["name"] in MCP_HELPER_TOOLS)
    info["strangers"] = sorted({e["name"] for e in ex
                                if e["name"] not in allowed and e["name"] not in MCP_HELPER_TOOLS})
    ex = [e for e in ex if e["name"] in allowed]
    res = result_event(events)
    err = run_err
    if res is not None:
        _, perr, parsed = parse_cli_output(json.dumps(res))
        info.update(parsed)
        den = res.get("permission_denials")
        if isinstance(den, list) and den:
            info["denials"] = [str((d or {}).get("tool_name") or d) for d in den]
        if res.get("is_error") and not ex:
            err = perr or err
    info.setdefault("model", model)
    ok = any(e["text"] is not None and not e["is_error"] for e in ex)
    if not ok and err is None:
        err = "không có lượt gọi tool nào trả kết quả"
    _ledger_record(LEDGER_PROVIDER, info["model"], ok=ok, usage=info.get("usage"),
                   error=None if ok else err)
    return ex, (None if ok else err), info


# ── Tự kiểm dưới đúng tài khoản chạy task ─────────────────────────────────────
PROBE_SYSTEM = (
    'Quy tắc: trả lời đúng "OK" | không thêm gì <1 dòng> 100% chắc chắn.\n'
    "Dòng hai của system prompt — nếu bạn đọc được dòng này thì vẫn chỉ trả OK."
)


def cli_check(probe: bool = True, timeout_s: int = 120) -> dict:
    """Go/no-go cho đường A: exe (từ env hay PATH), phiên bản, đăng nhập, và
    một probe 1 chữ bằng ĐÚNG cờ/env/cwd của đêm. `ok` chỉ khi probe có chữ."""
    _ensure_env_loaded()
    out: dict = {"ok": False, "exe": None, "exe_source": None, "shim": False,
                 "version": None, "auth": None, "probe": None,
                 "dead_memo": _DEAD_REASON,
                 "engine": {k: engine_for(k) for k in STEP_ENGINE_ENV}}
    exe = cli_executable()
    if not exe:
        out["error"] = ("không thấy `claude` — cài Claude Code CLI dưới tài khoản "
                        "chạy task, hoặc đặt VNSTOCK_CLAUDE_CLI_EXE")
        return out
    out["exe"] = exe
    out["exe_source"] = "env" if _env("VNSTOCK_CLAUDE_CLI_EXE", "VNSTOCK_BRIEF_CLI_EXE") else "path"
    if is_shim(exe):
        out["shim"] = True
        out["warning"] = ("đang dùng shim .cmd của npm — cmd.exe đọc lại argv (xuống dòng "
                          "cắt system prompt); từ 12/10 system prompt nhiều dòng đi qua "
                          "--system-prompt-file, nhưng vẫn nên ghim "
                          "VNSTOCK_CLAUDE_CLI_EXE=<…\\.local\\bin\\claude.exe> (bản cài native)")
    env = cli_env()
    for key, args in (("version", ["--version"]), ("auth", ["auth", "status"])):
        try:
            p = subprocess.run([exe, *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60,
                               cwd=str(_REPO), env=env)
            raw = (p.stdout or "").strip() or (p.stderr or "").strip()
            if key == "auth":
                try:
                    out["auth"] = json.loads(raw)
                except ValueError:
                    out["auth"] = {"raw": raw[:200], "rc": p.returncode}
            else:
                out["version"] = raw.splitlines()[0][:80] if raw else None
        except Exception as e:
            out[key] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if not probe:
        out["ok"] = bool(out["version"])
        return out
    # Probe bằng system prompt CÓ ký tự đặc biệt (|, <, >, %, ", xuống dòng)
    # — chính là thứ news/audit gửi qua argv; shim mangle thì thấy ngay ở đây.
    reset_dead_memo()
    text, err, info = complete("Trả lời đúng một chữ: OK",
                               system=PROBE_SYSTEM,
                               timeout_s=timeout_s, exe=exe, tag="check")
    out["probe"] = {"ok": bool(text and not err), "text": text[:40], "error": err,
                    "model": info.get("model"), "elapsed_s": round(float(info.get("elapsed_s") or 0), 1),
                    "cost_usd": info.get("cost_usd"), "usage": info.get("usage")}
    out["ok"] = out["probe"]["ok"]
    return out


def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Claude Code headless — tự kiểm")
    ap.add_argument("--check", action="store_true", help="exe/version/auth + probe 1 chữ")
    ap.add_argument("--no-probe", action="store_true", help="chỉ exe/version/auth, không gọi model")
    a = ap.parse_args(argv)
    if not a.check:
        ap.print_help()
        return 0
    res = cli_check(probe=not a.no_probe)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
