"""vnstock_brief_pack — "gói brief" cho engine NGOÀI ladder (Claude Code).

Ladder free (Gemini flash-lite / Nemotron) viết brief chiều chưa đạt (user
30/09) → cho Claude viết, nhưng KHÔNG viết lại đường brief: mọi thứ quanh
thân brief (ctx, prompt, 55 guard, memory, sổ LLM, khung Telegram, marker
một-brief-mỗi-phiên) vẫn là code cũ. Module này chỉ tách ĐÚNG HAI mặt cắt:

    build_pack()      ctx + prompt  ──►  JSON (kho `_meta/brief_pack.json`)
    finalize_brief()  thân brief (chữ) ──►  guards → validate → memory
    run_claude_cli()  gói ──► `claude -p` (Claude Code headless) ──► chữ

Ba đường dùng CÙNG lõi:
  • pipeline đêm (`run.py brief`, VNSTOCK_BRIEF_ENGINE=claude): build_pack →
    run_claude_cli → finalize_brief → push_close_brief(ai_block=…). Lỗi bất
    kỳ (không có CLI, timeout, trắng) ⇒ rơi về ladder như cũ — brief LUÔN đi.
  • tay/laptop: `run.py brief --export-pack` rồi skill `/brief-close` viết
    `_meta/brief_claude.md` rồi `run.py brief --from-file <md>`.
  • Routine cloud (sau): pack đi qua git, chữ về qua cùng `--from-file`.

Kill-switch / nút vặn (nếp repo VNSTOCK_*):
  VNSTOCK_BRIEF_ENGINE        ladder (mặc định) | claude
  VNSTOCK_BRIEF_CLI_MODEL     slug model cho `claude --model` (mặc định Opus)
  VNSTOCK_BRIEF_CLI_TIMEOUT_S trần chờ CLI (mặc định 900s — trần task 240′
                              còn dư, nhưng bước brief không được ăn hết)
  VNSTOCK_BRIEF_CLI_EXE       đường dẫn `claude` khi không có trên PATH
  VNSTOCK_BRIEF_CLI_API_KEY   =1 mới cho CLI thấy ANTHROPIC_API_KEY (mặc
                              định GIẤU để CLI dùng đăng nhập thuê bao, không
                              âm thầm tính tiền API)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent

PACK_VERSION = 1
PACK_NAME = "brief_pack.json"
OUT_NAME = "brief_claude.md"

ENGINE_ENV = "VNSTOCK_BRIEF_ENGINE"
ENGINE_LADDER = "ladder"
ENGINE_CLAUDE = "claude"
ENGINES = (ENGINE_LADDER, ENGINE_CLAUDE)

DEFAULT_CLI_MODEL = "claude-opus-5-5"
DEFAULT_CLI_TIMEOUT_S = 900
_CLI_MAX_TURNS = "4"           # trả lời thẳng là 1 lượt; dư cho lỡ đọc file
LEDGER_PROVIDER = "ClaudeCode"  # sổ LLM: tách khỏi "Anthropic" (API trả phí)
AGENT_TYPE = "claude"           # memory/dashboard: cùng type với ClaudeAgent

# Lời dặn đặt TRƯỚC prompt khi chạy headless — prompt trong pack viết cho
# model yếu (nhiều "TUYỆT ĐỐI KHÔNG"), Claude chỉ cần biết vai + luật trả lời.
CLI_PREFACE = (
    "Bạn là engine viết brief chiều cho VNStock Dashboard. Dưới đây là toàn bộ "
    "dữ liệu phiên và hướng dẫn định dạng. Viết brief bằng tiếng Việt, đúng "
    "các mục và thứ tự mà hướng dẫn yêu cầu, số theo format EN ({:,.2f}). "
    "Chỉ dùng số có trong dữ liệu; thiếu thì nói thiếu, không suy đoán. "
    "KHÔNG dùng công cụ, KHÔNG đọc file, KHÔNG hỏi lại — trả lời THẲNG bằng "
    "thân brief, không lời dẫn, không đóng khung code.\n\n"
    "════════ DỮ LIỆU + HƯỚNG DẪN ════════\n"
)
CLI_TASK_LINE = "Viết brief chiều theo dữ liệu và hướng dẫn nhận vào từ stdin."

_OFF = ("0", "false", "off", "no")


# ── Đường dẫn ────────────────────────────────────────────────────────────────
def pack_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / PACK_NAME


def brief_out_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / OUT_NAME


def engine_from_env(default: str = ENGINE_LADDER) -> str:
    """Engine theo env; chữ lạ → mặc định (không bao giờ ném)."""
    raw = (os.environ.get(ENGINE_ENV) or "").strip().lower()
    return raw if raw in ENGINES else default


def cli_model() -> str:
    return (os.environ.get("VNSTOCK_BRIEF_CLI_MODEL") or "").strip() or DEFAULT_CLI_MODEL


def engine_label(model: str) -> str:
    """Nhãn footer Telegram / tên agent trong memory: "Claude Code · opus-5-5"."""
    short = model.replace("claude-", "", 1) if model.startswith("claude-") else model
    return f"Claude Code · {short}"


# ── Gói ──────────────────────────────────────────────────────────────────────
def _hostname() -> str:
    try:
        from vnstock_rollup import get_hostname
        return get_hostname()
    except Exception:
        return os.environ.get("COMPUTERNAME") or "?"


def build_pack(brief_type: str = "afternoon") -> dict:
    """ctx + prompt y HỆT đường `generate_brief` (cùng bước refresh, cùng
    khối few-shot/lệnh mở/tin) — khác duy nhất: không gọi agent nào."""
    import vnstock_brief as vb

    vb._ensure_env_loaded()
    vb._maybe_reconcile_overdue()
    vb._maybe_refresh_events()
    vb._maybe_refresh_macro()
    vb._maybe_refresh_market_news()
    ctx = vb.collect_context(brief_type, auto_refresh=True)
    prompt = vb.build_prompt(
        ctx, brief_type,
        few_shot=vb._few_shot_block(brief_type),
        rec_block=vb._recommendation_block(ctx),
        news_block=vb._news_block(),
    )
    return {
        "version": PACK_VERSION,
        "brief_type": brief_type,
        "session": str(ctx.get("date") or ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "machine": _hostname(),
        "prompt": prompt,
        "ctx": ctx,
    }


def write_pack(pack: dict, path: "Path | str") -> Path:
    from vnstock_parquet_io import write_json_atomic
    path = Path(path)
    write_json_atomic(pack, path)
    return path


def read_pack(path: "Path | str") -> dict:
    path = Path(path)
    pack = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(pack, dict) or not pack.get("prompt"):
        raise ValueError(f"pack hỏng hoặc thiếu prompt: {path}")
    if int(pack.get("version") or 0) != PACK_VERSION:
        raise ValueError(f"pack version {pack.get('version')} ≠ {PACK_VERSION}: {path}")
    return pack


# ── Nhận thân brief ──────────────────────────────────────────────────────────
def _clean_text(text: str) -> str:
    """Bỏ khung ```…``` nếu model lỡ bọc, và khoảng trắng hai đầu."""
    t = (text or "").strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        t = t[first_nl + 1:] if first_nl >= 0 else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def finalize_brief(text: str, pack: dict, *, agent_name: str, model: str,
                   agent_type: str = AGENT_TYPE) -> dict:
    """Chữ thô → qua ĐÚNG chuỗi hậu kỳ của ladder: apply_brief_guards →
    validate_brief_factuality → memory.save_brief → brief_watch. Trả
    {"text", "warnings", "brief_id", "auto_score"}; text rỗng nghĩa là
    không có gì để gửi (chỗ gọi rơi về ladder)."""
    import vnstock_brief as vb

    ctx = pack.get("ctx") or {}
    raw = _clean_text(text)
    if not raw:
        return {"text": "", "warnings": [], "brief_id": None, "auto_score": 0.0}
    fixed = vb.apply_brief_guards(raw, ctx)
    try:
        warnings = list(vb.validate_brief_factuality(fixed, ctx) or [])
    except Exception:
        warnings = []
    score = 0.0
    try:
        from vnstock_train import auto_score_brief
        score = float(auto_score_brief(fixed) or 0.0)
    except Exception:
        pass
    brief_id = None
    try:
        import vnstock_memory as _mem
        brief_id = _mem.save_brief(
            brief_date=str(pack.get("session") or ctx.get("date") or ""),
            brief_type=str(pack.get("brief_type") or "afternoon"),
            agent_name=agent_name,
            agent_type=agent_type,
            model=model,
            prompt=str(pack.get("prompt") or ""),
            output=fixed,
            error=None,
            context={k: v for k, v in ctx.items() if k != "tickers"},
            auto_score=score,
        )
    except Exception:
        pass
    try:
        import vnstock_brief_watch as _watch
        _watch.observe_brief(_REPO / "data_warehouse", fixed, ctx,
                             today=ctx.get("date"))
    except Exception:
        pass
    return {"text": fixed, "warnings": warnings, "brief_id": brief_id,
            "auto_score": score}


# ── Claude Code headless ─────────────────────────────────────────────────────
def cli_executable() -> "str | None":
    exe = (os.environ.get("VNSTOCK_BRIEF_CLI_EXE") or "").strip()
    if exe:
        return exe if Path(exe).exists() else None
    return shutil.which("claude")


def cli_timeout_s() -> int:
    try:
        return max(30, int(os.environ.get("VNSTOCK_BRIEF_CLI_TIMEOUT_S") or DEFAULT_CLI_TIMEOUT_S))
    except ValueError:
        return DEFAULT_CLI_TIMEOUT_S


def cli_env() -> dict:
    """Môi trường cho tiến trình CLI. GIẤU ANTHROPIC_API_KEY (nếu .env có)
    để CLI dùng đăng nhập thuê bao — có key trong env là CLI chuyển sang
    tính tiền API mà không ai thấy. Muốn dùng key: VNSTOCK_BRIEF_CLI_API_KEY=1."""
    env = dict(os.environ)
    keep = (env.get("VNSTOCK_BRIEF_CLI_API_KEY") or "").strip().lower()
    if keep in ("", *_OFF):
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def cli_command(exe: str, model: str) -> list[str]:
    return [exe, "-p", CLI_TASK_LINE, "--output-format", "json",
            "--model", model, "--max-turns", _CLI_MAX_TURNS]


def parse_cli_output(stdout: str) -> "tuple[str, str | None, dict]":
    """(chữ, lỗi, info) từ stdout của `claude -p --output-format json`.
    info: usage kiểu OpenAI (prompt/completion) cho sổ, cost_usd, duration_ms.
    stdout không phải JSON → coi cả stdout là chữ (CLI cũ in text)."""
    raw = (stdout or "").strip()
    if not raw:
        return "", "CLI không in gì (stdout rỗng)", {}
    try:
        body = json.loads(raw)
    except ValueError:
        return raw, None, {}
    if not isinstance(body, dict):
        return raw, None, {}
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
    text = body.get("result")
    text = text if isinstance(text, str) else ""
    if body.get("is_error"):
        return "", f"CLI báo lỗi: {(text or body.get('subtype') or '?')[:200]}", info
    if not text.strip():
        return "", f"CLI trả kết quả rỗng (subtype={body.get('subtype')})", info
    return text, None, info


def run_claude_cli(prompt: str, *, model: "str | None" = None,
                   timeout_s: "int | None" = None,
                   exe: "str | None" = None) -> "tuple[str, str | None, dict]":
    """Gọi Claude Code headless: prompt qua STDIN (Windows giới hạn dòng lệnh
    32K ký tự — prompt brief ~40K). Trả (chữ, lỗi, info); KHÔNG bao giờ ném.
    Ghi sổ LLM provider "ClaudeCode" (ok chỉ khi có chữ thật — nếp 30/09)."""
    import vnstock_brief as vb

    model = model or cli_model()
    timeout_s = timeout_s or cli_timeout_s()
    exe = exe or cli_executable()
    if not exe:
        return "", ("không tìm thấy lệnh `claude` (Claude Code CLI) trên PATH — "
                    "cài CLI + đăng nhập, hoặc đặt VNSTOCK_BRIEF_CLI_EXE"), {}
    payload = CLI_PREFACE + prompt
    t0 = time.time()
    try:
        proc = subprocess.run(
            cli_command(exe, model), input=payload, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, cwd=str(_REPO), env=cli_env(),
        )
    except subprocess.TimeoutExpired:
        err = f"claude CLI quá {timeout_s}s — bỏ"
        vb._ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
        return "", err, {"elapsed_s": time.time() - t0}
    except OSError as e:
        err = f"không chạy được claude CLI: {type(e).__name__}: {str(e)[:120]}"
        vb._ledger_record(LEDGER_PROVIDER, model, ok=False, error=err)
        return "", err, {"elapsed_s": time.time() - t0}
    elapsed = time.time() - t0
    text, err, info = parse_cli_output(proc.stdout)
    info["elapsed_s"] = elapsed
    info["model"] = model
    if proc.returncode != 0 and not text:
        tail = (proc.stderr or "").strip().splitlines()
        err = f"claude CLI rc={proc.returncode}: {(tail[-1] if tail else err or '?')[:200]}"
    if err:
        vb._ledger_record(LEDGER_PROVIDER, model, ok=False,
                          usage=info.get("usage"), error=err)
        return "", err, info
    vb._ledger_record(LEDGER_PROVIDER, model, ok=True, usage=info.get("usage"))
    return text, None, info


def outcome_line(info: dict, text: str, err: "str | None") -> str:
    """Dòng log `[brief] ⏱ claude-cli: Ns · ✅ N ký tự · $x` — cùng nếp
    `_agent_outcome_line` để `Select-String '\\[brief\\] ⏱'` gom được."""
    el = float(info.get("elapsed_s") or 0)
    cost = info.get("cost_usd")
    cost_s = f" · ${cost:,.2f}" if isinstance(cost, (int, float)) else ""
    if err:
        return f"[brief] ⏱ claude-cli: {el:,.0f}s · ❌ {err[:160]}"
    return f"[brief] ⏱ claude-cli: {el:,.0f}s · ✅ {len(text):,} ký tự{cost_s}"
