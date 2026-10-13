"""vnstock_brief_pack — "gói brief" cho engine NGOÀI ladder (Claude Code).

Ladder free (Gemini flash-lite / Nemotron) viết brief chiều chưa đạt (user
30/09) → cho Claude viết, nhưng KHÔNG viết lại đường brief: mọi thứ quanh
thân brief (ctx, prompt, 55 guard, memory, sổ LLM, khung Telegram, marker
một-brief-mỗi-phiên) vẫn là code cũ. Module này chỉ tách ĐÚNG HAI mặt cắt:

    build_pack()      ctx + prompt  ──►  JSON (kho `_meta/brief_pack.json`)
                                        + `_meta/brief_prompt.md` (prompt
                                        nhiều dòng cho skill /brief-close)
    finalize_brief()  thân brief (chữ) ──►  guards → validate → memory
    run_claude_cli()  prompt ──► `vnstock_claude_cli.complete` ──► chữ

Ba đường dùng CÙNG lõi:
  • pipeline đêm (`run.py brief`, VNSTOCK_BRIEF_ENGINE=claude hoặc công tắc
    chung VNSTOCK_LLM_ENGINE=claude): build_pack → run_claude_cli →
    finalize_brief → push_close_brief(ai_block=…). Lỗi bất kỳ (không có CLI,
    timeout, trắng) ⇒ rơi về ladder như cũ — brief LUÔN đi.
  • tay/laptop: `run.py brief --export-pack` rồi skill `/brief-close` viết
    `_meta/brief_claude.md` rồi `run.py brief --from-file <md>`.
  • gửi lại không tốn call: bản SAU guard được ghi `_meta/brief_claude.md`
    trước khi đẩy Telegram — Telegram lỗi thì `--from-file` gửi lại.

Cờ CLI, sổ, giấu key, timeout: ở `vnstock_claude_cli` (một bản cho mọi bước).
Nút vặn riêng brief: VNSTOCK_BRIEF_ENGINE, VNSTOCK_BRIEF_CLI_MODEL,
VNSTOCK_BRIEF_CLI_TIMEOUT_S (trống = theo VNSTOCK_CLAUDE_CLI_*).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import vnstock_claude_cli as vcc

_REPO = Path(__file__).resolve().parent

PACK_VERSION = 2            # v2 (30/09): set trong ctx ghi list + `ctx_set_keys`
PACK_NAME = "brief_pack.json"
PROMPT_NAME = "brief_prompt.md"
RAW_NAME = "brief_claude_raw.md"
OUT_NAME = "brief_claude.md"

ENGINE_ENV = vcc.STEP_ENGINE_ENV["brief"]
ENGINE_LADDER = vcc.ENGINE_LADDER
ENGINE_CLAUDE = vcc.ENGINE_CLAUDE
ENGINES = vcc.ENGINES

DEFAULT_CLI_MODEL = vcc.DEFAULT_MODEL
DEFAULT_CLI_FALLBACK_MODEL = vcc.DEFAULT_FALLBACK_MODEL
DEFAULT_CLI_TIMEOUT_S = vcc.DEFAULT_TIMEOUT_S
LEDGER_PROVIDER = vcc.LEDGER_PROVIDER
AGENT_TYPE = "claude"           # memory/dashboard: cùng type với ClaudeAgent

# System prompt cho lượt headless (qua `--system-prompt`, thay hẳn system
# prompt ~20K token của Claude Code). Prompt trong pack viết cho model yếu
# (nhiều "TUYỆT ĐỐI KHÔNG"), Claude chỉ cần biết vai + luật trả lời.
CLI_PREFACE = (
    "Bạn là engine viết brief chiều cho VNStock Dashboard. Nội dung nhận vào là "
    "toàn bộ dữ liệu phiên và hướng dẫn định dạng. Viết brief bằng tiếng Việt, "
    "đúng các mục và thứ tự mà hướng dẫn yêu cầu, số theo format EN ({:,.2f}). "
    "Chỉ dùng số có trong dữ liệu; thiếu thì nói thiếu, không suy đoán. "
    "Trả lời THẲNG bằng thân brief: không lời dẫn, không đóng khung code."
)
CLI_TASK_LINE = vcc.TASK_LINE


# ── Đường dẫn ────────────────────────────────────────────────────────────────
def pack_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / PACK_NAME


def prompt_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / PROMPT_NAME


def raw_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / RAW_NAME


def brief_out_path(warehouse: "Path | str" = "data_warehouse") -> Path:
    return Path(warehouse) / "_meta" / OUT_NAME


# ── Engine / nút vặn (ủy cho vnstock_claude_cli) ─────────────────────────────
def engine_from_env(default: str = ENGINE_LADDER) -> str:
    """Engine bước brief: VNSTOCK_BRIEF_ENGINE > VNSTOCK_LLM_ENGINE > ladder
    (đã load .env; chữ lạ = ladder)."""
    eng = vcc.engine_for("brief")
    return eng if eng in ENGINES else default


def cli_model() -> str:
    return vcc.cli_model("VNSTOCK_BRIEF_CLI_MODEL")


def cli_fallback_model() -> "str | None":
    return vcc.cli_fallback_model()


def cli_timeout_s() -> int:
    return vcc.cli_timeout_s("VNSTOCK_BRIEF_CLI_TIMEOUT_S")


def cli_executable() -> "str | None":
    return vcc.cli_executable()


def cli_env() -> dict:
    return vcc.cli_env()


def cli_command(exe: str, model: str) -> list[str]:
    return vcc.cli_command(exe, model, system=CLI_PREFACE,
                           fallback_model=cli_fallback_model())


def parse_cli_output(stdout: str) -> "tuple[str, str | None, dict]":
    return vcc.parse_cli_output(stdout)


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
    khối few-shot/lệnh mở/tin) — khác duy nhất: không gọi agent nào.
    ctx trả về là ctx TRONG BỘ NHỚ (set vẫn là set) — đường đêm đưa thẳng
    vào guard, byte-identical với `generate_brief`."""
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


def _pack_for_disk(pack: dict) -> dict:
    """Bản ghi đĩa: set/frozenset ở tầng 1 của ctx → list đã sort + danh sách
    khoá để `read_pack` trả lại set (guard đọc `financial_tickers` /
    `realestate_tickers` / `mover_universe` như set — `default=str` của
    write_json_atomic biến set thành chuỗi repr, guard sẽ so từng KÝ TỰ).
    KHÔNG đụng ctx trong bộ nhớ."""
    ctx = pack.get("ctx") or {}
    set_keys = sorted(k for k, v in ctx.items() if isinstance(v, (set, frozenset)))
    disk_ctx = {k: (sorted(str(x) for x in v) if k in set_keys else v)
                for k, v in ctx.items()}
    out = dict(pack)
    out["ctx"] = disk_ctx
    out["ctx_set_keys"] = set_keys
    return out


def write_pack(pack: dict, path: "Path | str") -> Path:
    """Ghi gói (atomic) + `brief_prompt.md` cạnh nó (prompt nhiều dòng — tool
    Read của skill cắt dòng dài, trường `prompt` một-dòng-40K trong JSON làm
    Claude viết từ prompt cụt mà không ai biết)."""
    from vnstock_parquet_io import write_json_atomic
    path = Path(path)
    write_json_atomic(_pack_for_disk(pack), path)
    try:
        _write_text_atomic(str(pack.get("prompt") or ""), path.with_name(PROMPT_NAME))
    except Exception:
        pass
    return path


def read_pack(path: "Path | str") -> dict:
    path = Path(path)
    pack = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(pack, dict) or not pack.get("prompt"):
        raise ValueError(f"pack hỏng hoặc thiếu prompt: {path}")
    if int(pack.get("version") or 0) != PACK_VERSION:
        raise ValueError(f"pack version {pack.get('version')} ≠ {PACK_VERSION} — "
                         f"chạy lại `run.py brief --export-pack`: {path}")
    ctx = pack.get("ctx") or {}
    for k in pack.get("ctx_set_keys") or []:
        if isinstance(ctx.get(k), list):
            ctx[k] = set(ctx[k])
    pack["ctx"] = ctx
    return pack


def _write_text_atomic(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path


def write_raw(text: str, warehouse: "Path | str" = "data_warehouse") -> "Path | None":
    """Chữ THÔ của CLI trước guard — để `/brief-review` so guard sửa gì."""
    try:
        return _write_text_atomic(text, raw_path(warehouse))
    except Exception:
        return None


def write_final(text: str, warehouse: "Path | str" = "data_warehouse") -> "Path | None":
    """Bản SAU guard, ghi TRƯỚC khi đẩy Telegram — Telegram lỗi thì
    `run.py brief --from-file` gửi lại, không tốn call Opus thứ hai."""
    try:
        return _write_text_atomic(text, brief_out_path(warehouse))
    except Exception:
        return None


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


def _strip_code_inserted(text: str) -> str:
    """Bỏ phần CODE chèn (khối 🔭 + TLDR dòng 3 "**Trung hạn:**", P1b-3) — đó
    không phải guard sửa chữ agent nên không được tính vào guard_delta."""
    from vnstock_brief import _HORIZON_TLDR_PREFIX, _is_section_start
    out, skip = [], False
    for ln in (text or "").split("\n"):
        if _is_section_start(ln):
            skip = "🔭" in ln
        if skip or ln.strip().startswith(_HORIZON_TLDR_PREFIX):
            continue
        out.append(ln)
    return "\n".join(out)


def _guard_delta(raw: str, fixed: str) -> int:
    """Số ký tự guard đã thêm/bớt trên chữ agent (không tính phần code chèn)."""
    return len(_strip_code_inserted(fixed)) - len(_strip_code_inserted(raw))


def finalize_brief(text: str, pack: dict, *, agent_name: str, model: str,
                   agent_type: str = AGENT_TYPE) -> dict:
    """Chữ thô → qua ĐÚNG chuỗi hậu kỳ của ladder: apply_brief_guards →
    validate_brief_factuality → memory.save_brief → brief_watch. Trả
    {"text", "warnings", "brief_id", "auto_score", "guard_delta"}; text rỗng
    nghĩa là không có gì để gửi (chỗ gọi rơi về ladder)."""
    import vnstock_brief as vb

    ctx = pack.get("ctx") or {}
    raw = _clean_text(text)
    if not raw:
        return {"text": "", "warnings": [], "brief_id": None, "auto_score": 0.0,
                "guard_delta": 0}
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
            "auto_score": score, "guard_delta": _guard_delta(raw, fixed)}


# ── Claude Code headless ─────────────────────────────────────────────────────
def run_claude_cli(prompt: str, *, model: "str | None" = None,
                   timeout_s: "int | None" = None,
                   exe: "str | None" = None) -> "tuple[str, str | None, dict]":
    """Gọi Claude Code headless cho brief: preface làm system prompt, prompt
    qua STDIN, fallback model theo env. Trả (chữ, lỗi, info); KHÔNG ném."""
    return vcc.complete(prompt, system=CLI_PREFACE,
                        model=model or cli_model(),
                        fallback_model=cli_fallback_model() or "",
                        timeout_s=timeout_s or cli_timeout_s(),
                        exe=exe or cli_executable(), tag="brief")


def outcome_line(info: dict, text: str, err: "str | None") -> str:
    return vcc.outcome_line("brief", info, text, err)


# ── Soi lại sáng hôm sau (skill /brief-review) ──────────────────────────────
def review_report(warehouse: "Path | str" = "data_warehouse") -> str:
    """Tóm đêm qua: marker (engine/agent/lý do rơi), dòng sổ ClaudeCode, 2
    bản memory mới nhất, guard sửa bao nhiêu (raw vs final). Best-effort:
    thiếu gì in "—", không ném."""
    wh = Path(warehouse)
    lines: list[str] = []
    try:
        mk = json.loads((wh / "_meta" / "brief_push.json").read_text(encoding="utf-8"))
    except Exception:
        mk = {}
    lines.append(f"marker: close={mk.get('close', '—')} · engine={mk.get('engine', '—')}"
                 f" · agent={mk.get('agent', '—')} · máy={mk.get('machine', '—')}")
    if mk.get("claude_error"):
        lines.append(f"  ↳ Claude rơi về ladder: {mk['claude_error']}")
    try:
        from vnstock_llm_ledger import summary
        s = summary()
        rows = {k: v for k, v in (s.get("providers") or {}).items()
                if k.startswith(LEDGER_PROVIDER + ":")}
        if rows:
            for k, r in rows.items():
                lines.append(f"sổ {s.get('day')}: {k} · {r.get('calls', 0)} call · "
                             f"{r.get('ok', 0)} OK · {r.get('fail', 0)} lỗi"
                             + (f" · lỗi cuối: {r.get('last_error')}" if r.get('last_error') else ""))
        else:
            lines.append(f"sổ {s.get('day', '—')}: không có dòng {LEDGER_PROVIDER}")
    except Exception:
        lines.append("sổ: —")
    try:
        import vnstock_memory as _mem
        for b in _mem.recent_briefs("afternoon", limit=2):
            lines.append(f"memory #{b.get('id')}: {b.get('brief_date')} · {b.get('agent_name')} · "
                         f"{len(b.get('output') or ''):,} ký tự · auto {b.get('auto_score')} · "
                         f"sao {b.get('user_rating') or '—'}")
    except Exception:
        lines.append("memory: —")
    try:
        raw = raw_path(wh).read_text(encoding="utf-8").splitlines()
        fin = brief_out_path(wh).read_text(encoding="utf-8").splitlines()
        changed = sum(1 for a, b in zip(raw, fin) if a != b) + abs(len(raw) - len(fin))
        lines.append(f"guard: raw {len(raw)} dòng → final {len(fin)} dòng · {changed} dòng khác")
    except Exception:
        lines.append("guard: chưa có raw/final để so")
    return "\n".join(lines)


def rate_brief(brief_id: int, stars: int, feedback: str = "") -> None:
    """Chấm sao bản brief trong memory (≥4 sao thành mẫu few-shot)."""
    import vnstock_memory as _mem
    _mem.update_rating(int(brief_id), int(stars), feedback or "")


def main(argv: "list[str] | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Brief pack — engine Claude cho brief chiều")
    ap.add_argument("--check", action="store_true",
                    help="go/no-go đường A: exe · version · đăng nhập · probe 1 chữ")
    ap.add_argument("--review", action="store_true", help="tóm brief đêm qua (skill /brief-review)")
    ap.add_argument("--rate", nargs="+", metavar=("ID", "SAO"),
                    help="chấm sao: --rate <id> <1-5> [nhận xét]")
    ap.add_argument("--warehouse", default="data_warehouse")
    a = ap.parse_args(argv)
    if a.check:
        res = vcc.cli_check()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if a.review:
        print(review_report(a.warehouse))
        return 0
    if a.rate:
        if len(a.rate) < 2:
            print("--rate cần <id> <sao> [nhận xét]")
            return 2
        rate_brief(int(a.rate[0]), int(a.rate[1]), " ".join(a.rate[2:]))
        print(f"đã chấm #{a.rate[0]}: {a.rate[1]} sao")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
