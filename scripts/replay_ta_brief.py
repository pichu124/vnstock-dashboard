"""Chạy lại lịch sử cho brief CHIỀU có thẻ kỹ thuật (PTKT §14 câu 2 — duyệt trước khi bật `VNSTOCK_TA_CARD`).

Mỗi phiên cũ: lấy ctx ĐÃ LƯU của brief (`brief_memory.db`, `context_json`) — KHÔNG gọi lại
`collect_context` (nó đọc dữ liệu hiện tại ⇒ nhìn trước) — gắn thẻ bằng đúng hàm production
`vnstock_brief._attach_ta_cards` với bar VN-Index + bar từng mã CẮT tới ngày brief; mức S/R là của
ctx đã lưu (`vnindex_tech`, `sr_support/sr_resistance` của mover) như brief gốc thấy. Rồi dựng prompt
`build_prompt(ctx, "afternoon")`, (tuỳ chọn) gọi engine Claude của brief chiều
(`vnstock_brief_pack.run_claude_cli`, sổ LLM ghi như thường) và chạy `apply_brief_guards`.

KHÔNG gửi Telegram, KHÔNG ghi `brief_memory.db` (mở chỉ-đọc), KHÔNG ghi `_meta/brief_*` — chỉ ghi
thư mục output riêng (mặc định `data_warehouse/_meta/replay_ta/<ngày chạy>/`):
`report.md` + `report.json` + `prompts/<phiên>.md` (+ `new/<phiên>.raw.md|.md` khi `--run`).

🖥️ DESKTOP (máy có `claude` CLI), ngoài khung pipeline 18:00 → `⏱ TỔNG`:

    python scripts/replay_ta_brief.py                     # dry-run: prompt + thẻ, 0 lượt gọi
    python scripts/replay_ta_brief.py --run --limit 20    # gọi model 20 lượt (hỏi xác nhận)

Khối "Kết cục 5 phiên sau" đọc kho HIỆN TẠI — dữ liệu TƯƠNG LAI so với phiên brief, chỉ để đối chiếu.
Kho đã rebase (GDKHQ) sau phiên thì thẻ mã dựng trên giá đã điều chỉnh: báo cáo ghi chú khi giá
kho lệch giá trong ctx > 2%.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable
from unittest import mock

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import vnstock_brief as vb  # noqa: E402  (sau sys.path)
import vnstock_ta_score_io as tsio  # noqa: E402
from vnstock_brief_canon import TA_INSIGHT_LABEL, TA_SECTION_TITLES  # noqa: E402
from vnstock_brief_guards_common import _is_section_start, is_ta_heading  # noqa: E402
from vnstock_brief_guards_numbers import (  # noqa: E402
    enforce_ta_breakout_volume, enforce_ta_numbers, enforce_ta_rsi_words, enforce_ta_trend_words)
from vnstock_brief_guards_sections import _ta_agent_sentences  # noqa: E402
from vnstock_brief_guards_text import enforce_ta_no_level_promise  # noqa: E402

BRIEF_TYPE = "afternoon"
DEFAULT_LIMIT = 20
ENGINE_FAIL_STREAK_MAX = 2       # 2 phiên liền engine lỗi ⇒ dừng (timeout 600s/lượt × 20 = 3 tiếng)
FWD_SESSIONS = 5
VOL_AVG_BARS = 20
REBASE_TOL = 0.02              # giá kho vs giá trong ctx lệch > 2% ⇒ nghi kho đã rebase sau phiên
# Ước tính chi phí: đo thật 30/09 (`[brief] ⏱ claude-cli: 56s · ✅ 5,636 ký tự · $0.31`, VIEC-DANG-LAM)
# + quy đổi token theo bảng giá `vnstock_llm_ledger` (cận dưới — không tính token suy nghĩ/cache).
MEASURED_S_PER_CALL = 56
MEASURED_USD_PER_CALL = 0.31
CHARS_PER_TOKEN = 3.0
OUTPUT_TOKENS_EST = 3000

# Năm luật chữ kỹ thuật của guard mới (mục 📈, từng câu) — khoá · nhãn báo cáo · guard.
TA_RULES: tuple = (
    ("so_bia", "số ngoài thẻ", enforce_ta_numbers),
    ("xu_huong", "xu hướng ngược thẻ", enforce_ta_trend_words),
    ("hua_hen", "hứa hẹn mức", enforce_ta_no_level_promise),
    ("rsi", "RSI gọi sai vùng", enforce_ta_rsi_words),
    ("kl", "vượt/thủng thiếu KL", enforce_ta_breakout_volume),
)
RULE_KEYS = tuple(k for k, _, _ in TA_RULES)
RULE_NAMES = {k: n for k, n, _ in TA_RULES}


# ── Chọn phiên ───────────────────────────────────────────────────────────

def select_sessions(briefs: list[dict], limit: int = DEFAULT_LIMIT) -> list[dict]:
    """N phiên brief CHIỀU gần nhất, mỗi phiên MỘT bản: đã gửi > bản Claude, cùng hạng lấy bản tạo
    sau cùng. Chỉ xét bản đã gửi hoặc `agent_type='claude'`, có `context_json` đọc được. Trả theo
    phiên tăng dần."""
    best: dict[str, tuple] = {}
    for b in briefs:
        if b.get("brief_type") != BRIEF_TYPE or not (b.get("output") or "").strip():
            continue
        sent, claude = bool(b.get("sent")), b.get("agent_type") == "claude"
        if not (sent or claude) or not tsio._ctx(b):
            continue
        d = str(b.get("brief_date") or "")[:10]
        rank = (sent, claude, str(b.get("created_at") or ""))
        if d and (d not in best or rank > best[d][0]):
            best[d] = (rank, b)
    days = sorted(best)[-limit:] if limit > 0 else []
    return [best[d][1] for d in days]


# ── ctx đã lưu + thẻ không nhìn trước ────────────────────────────────────

def _as_set(v):
    """`save_brief` ghi ctx bằng `json.dumps(default=str)` ⇒ set thành chuỗi repr ("{'VCB', …}")."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "set()":
        return set()
    if s.startswith("frozenset(") and s.endswith(")"):
        s = s[len("frozenset("):-1]
    if s.startswith("{'") and s.endswith("'}"):
        try:
            out = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return v
        return set(out) if isinstance(out, (set, frozenset)) else v
    return v


def stored_ctx(brief: dict) -> dict:
    """ctx đã lưu của brief, set ở tầng 1 trả lại thành set (guard đọc `financial_tickers`,
    `mover_universe`… như set — so chuỗi repr là so từng ký tự)."""
    ctx = {k: _as_set(v) for k, v in tsio._ctx(brief).items()}
    ctx["brief_type"] = BRIEF_TYPE
    # Guard ⚠️ GDKHQ so sự kiện với "hôm nay": thiếu khoá ⇒ `date.today()` lúc chạy lại ⇒ mọi
    # sự kiện của phiên cũ thành "đã qua", bản mới mất cảnh báo mà production đã có.
    if not ctx.get("today") and ctx.get("date"):
        ctx["today"] = str(ctx["date"])[:10]
    return ctx


def cut_bars(df: "pd.DataFrame | None", until: str, days: int | None = None) -> pd.DataFrame:
    """Bar tới hết ngày ``until`` (không nhìn trước); ``days`` ⇒ chỉ giữ ``days`` ngày lịch trước
    ``until`` — cùng cửa sổ `_load_history_from_parquet(days=…)` của brief chạy đúng hôm đó."""
    if df is None or df.empty or "time" not in df.columns:
        return pd.DataFrame()
    t = pd.to_datetime(df["time"]).dt.normalize()
    end = pd.Timestamp(until)
    keep = t <= end
    if days is not None:
        keep &= t >= end - pd.Timedelta(days=days)
    return df[keep].reset_index(drop=True)


def attach_cards(ctx: dict, index_bars: pd.DataFrame,
                 load_ticker: Callable[[str], pd.DataFrame]) -> dict:
    """Bản sao ``ctx`` có ``ta_card`` + ``ta_cards`` dựng bằng `vnstock_brief._attach_ta_cards` trên
    bar CẮT tới ``ctx["date"]``. ``load_ticker(mã)`` trả TOÀN BỘ lịch sử mã; bộ đọc kho mà hàm
    production gọi (`vnstock_strategy._load_history_from_parquet`) được thay tạm bằng bản cắt.
    Thẻ VN-Index lệch `vnindex_tech` đã lưu ⇒ ValueError (như production)."""
    import vnstock_strategy
    out = copy.deepcopy(ctx)
    until = str(out.get("date") or "")[:10]
    if not until:
        raise ValueError("ctx không có 'date'")

    def _cut_loader(tk: str, days: int, prices_dir=None) -> pd.DataFrame:
        return cut_bars(load_ticker(tk), until, days)

    with mock.patch.object(vnstock_strategy, "_load_history_from_parquet", _cut_loader):
        vb._attach_ta_cards(out, cut_bars(index_bars, until))
    if not out.get("ta_card"):
        raise ValueError("không dựng được thẻ VN-Index (ctx thiếu vnindex_tech.close?)")
    return out


def rebase_notes(ctx: dict) -> list[str]:
    """Mã có thẻ mà giá đóng cửa kho (dựng lại) lệch giá trong ctx > `REBASE_TOL` ⇒ nghi kho đã
    rebase (GDKHQ) sau phiên: thẻ mã đó dựng trên giá đã điều chỉnh, mức S/R của ctx vẫn giá cũ."""
    cards = ctx.get("ta_cards") or {}
    ref = {str(m.get("Mã") or "").upper(): m.get("last")
           for m in (ctx.get("vn30_gainers") or []) + (ctx.get("vn30_losers") or [])}
    ref.update({str(p.get("ticker") or "").upper(): p.get("last_close")
                for p in ctx.get("portfolio") or [] if str(p.get("ticker") or "").upper() not in ref})
    out = []
    for tk, c in cards.items():
        last, close = ref.get(tk), (c or {}).get("close")
        if isinstance(last, (int, float)) and last > 0 and isinstance(close, (int, float)):
            if abs(close / last - 1) > REBASE_TOL:
                out.append(f"{tk}: đóng cửa kho {close:,.2f} vs ctx {last:,.2f} "
                           f"({(close / last - 1) * 100:+,.2f}%) — kho có thể đã rebase sau phiên")
    return out


# ── Mục 📈: câu, vi phạm, guard sửa gì ──────────────────────────────────

def ta_section(text: str) -> str:
    """Mục "📈 Mức kỹ thuật …" (tiêu đề + thân) của brief; "" khi không có."""
    lines = (text or "").split("\n")
    s = next((i for i, l in enumerate(lines) if is_ta_heading(l)), None)
    if s is None:
        return ""
    e = next((j for j in range(s + 1, len(lines)) if _is_section_start(lines[j])), len(lines))
    return "\n".join(lines[s:e]).strip()


def section_sentences(section: str, ctx: dict) -> list[str]:
    """Câu CHỮ MODEL trong mục 📈 — cùng cách `enforce_ta_card_block` gom: bỏ dòng thẻ chép nguyên,
    bỏ dòng dữ kiện/khung template ("Đóng cửa:", "Hỗ trợ gần:"…), bỏ nhãn "**…:**"."""
    if not section:
        return []
    card = [str(l) for l in ((ctx.get("ta_card") or {}).get("lines") or [])]
    return _ta_agent_sentences(section.split("\n")[1:], card)


def count_violations(section: str, ctx: dict) -> dict[str, list[str]]:
    """Từng câu chữ model của mục 📈 qua từng guard trong 5 luật mới (ctx có thẻ): guard đổi câu
    (bỏ / bỏ mệnh đề / chèn KL) = câu vi phạm luật đó. Chạy từng câu riêng để luật này không che
    luật kia."""
    hits: dict[str, list[str]] = {k: [] for k in RULE_KEYS}
    title = TA_SECTION_TITLES[BRIEF_TYPE]
    for s in section_sentences(section, ctx):
        probe = f"{title}\n{TA_INSIGHT_LABEL} {s}"
        for key, _, fn in TA_RULES:
            if fn(probe, ctx) != probe:
                hits[key].append(s)
    return hits


def n_violations(hits: dict | None) -> int:
    return sum(len(v) for v in (hits or {}).values())


def guard_diff(raw: str, final: str, ctx: dict) -> dict:
    """Câu chữ model của mục 📈 trước vs sau chuỗi guard: giữ nguyên / bị bỏ (không còn nguyên
    văn) / mới hoặc bị sửa (bỏ mệnh đề, chèn KL, đổi định dạng số); dòng thẻ có đủ không."""
    before = section_sentences(ta_section(raw), ctx)
    after_sec = ta_section(final)
    after = section_sentences(after_sec, ctx)
    card = [str(l) for l in ((ctx.get("ta_card") or {}).get("lines") or [])]
    return {
        "raw_sentences": len(before), "final_sentences": len(after),
        "kept": sum(1 for s in after if s in before),
        "dropped": [s for s in before if s not in after],
        "changed": [s for s in after if s not in before],
        "card_lines_ok": bool(card) and all(l in after_sec.split("\n") for l in card),
    }


# ── Kết cục sau phiên (dữ liệu tương lai, chỉ đối chiếu) ─────────────────

def forward_outcome(index_bars: pd.DataFrame, session: str, vt: dict,
                    n: int = FWD_SESSIONS) -> dict:
    """VN-Index ``n`` phiên SAU ``session``: đổi đóng cửa T+1/T+n, phiên đầu chạm S1/S2/R1/R2 (low ≤
    S, high ≥ R) của ``vt`` đã lưu, KL T+1 so TB20 (20 phiên tới hết ``session``)."""
    bars = tsio.normalize_bars(index_bars)
    t = bars["time"].dt.date.astype(str).tolist()
    if session not in t:
        return {"available": False, "reason": f"kho không có bar phiên {session}"}
    base = t.index(session)
    fwd = bars.iloc[base + 1:base + 1 + n]
    c0 = float(bars["close"].iloc[base])
    out: dict = {"available": True, "close": round(c0, 2), "sessions_after": int(len(fwd)),
                 "t1_pct": None, f"t{n}_pct": None, "touch": {}, "vol_t1_ratio": None}
    if len(fwd) >= 1:
        out["t1_pct"] = round((float(fwd["close"].iloc[0]) / c0 - 1) * 100, 2)
    if len(fwd) >= n:
        out[f"t{n}_pct"] = round((float(fwd["close"].iloc[n - 1]) / c0 - 1) * 100, 2)
    for key, name, col, hit in (("support_1", "S1", "low", lambda x, lv: x <= lv),
                                ("support_2", "S2", "low", lambda x, lv: x <= lv),
                                ("resistance_1", "R1", "high", lambda x, lv: x >= lv),
                                ("resistance_2", "R2", "high", lambda x, lv: x >= lv)):
        lv = vt.get(key)
        if not isinstance(lv, (int, float)):
            continue
        first = next((k + 1 for k, x in enumerate(fwd[col]) if hit(float(x), float(lv))), None)
        out["touch"][name] = {"level": float(lv), "first_session": first}
    if "volume" in bars.columns and len(fwd) >= 1:
        avg = bars["volume"].iloc[max(0, base + 1 - VOL_AVG_BARS):base + 1].astype(float).mean()
        v1 = float(fwd["volume"].iloc[0])
        if avg and avg == avg and avg > 0 and v1 == v1:
            out["vol_t1_ratio"] = round(v1 / avg, 2)
    return out


# ── Một phiên ────────────────────────────────────────────────────────────

def prepare_session(brief: dict, index_bars: pd.DataFrame,
                    load_ticker: Callable[[str], pd.DataFrame]) -> dict:
    """Phần KHÔNG gọi model: ctx + thẻ + prompt mới, mục 📈 cũ + vi phạm theo luật mới, kết cục.
    Lỗi ⇒ ``row["error"]``, không ném."""
    d = str(brief.get("brief_date") or "")[:10]
    old = brief.get("output") or ""
    row: dict = {"session": d, "brief_id": brief.get("id"), "agent": brief.get("agent_name"),
                 "agent_type": brief.get("agent_type"), "sent": bool(brief.get("sent")),
                 "old_section": ta_section(old), "error": None}
    try:
        ctx = attach_cards(stored_ctx(brief), index_bars, load_ticker)
        row["ctx"] = ctx
        row["ta_card"] = dict(ctx["ta_card"])
        row["ta_cards"] = ctx.get("ta_cards") or {}
        row["rebase_notes"] = rebase_notes(ctx)
        row["card_errors"] = (ctx.get("loader_errors") or {}).get("ta_cards")
        row["prompt"] = vb.build_prompt(ctx, BRIEF_TYPE)
        row["old_violations"] = count_violations(row["old_section"], ctx)
        row["outcome"] = forward_outcome(index_bars, d, ctx.get("vnindex_tech") or {})
    except Exception as e:                       # một phiên hỏng không kéo cả lượt chạy
        row["error"] = f"dựng ctx/prompt: {type(e).__name__}: {e}"
    return row


Engine = Callable[[str], "tuple[str, str | None, dict]"]


def _raw_path(out_dir: Path, session: str) -> Path:
    return Path(out_dir) / "new" / f"{session}.raw.md"


def run_engine(row: dict, engine: Engine, out_dir: "Path | None" = None) -> dict:
    """Gọi engine cho phiên đã dựng, làm sạch như `finalize_brief` (`_clean_text`) rồi
    `apply_brief_guards(text, ctx)`. KHÔNG memory, KHÔNG brief_watch, KHÔNG Telegram.

    ``out_dir`` ⇒ chữ thô ghi ra `new/<phiên>.raw.md` NGAY sau lượt gọi (Ctrl+C / máy ngủ ở
    phiên 15 không mất 14 bản đã trả tiền), và phiên đã có file đó thì DÙNG LẠI, không gọi."""
    import vnstock_brief_pack as vbp
    if row.get("error"):
        return row
    cached = _raw_path(out_dir, row["session"]) if out_dir is not None else None
    if cached is not None and cached.is_file() and cached.read_text(encoding="utf-8").strip():
        text, err, info = cached.read_text(encoding="utf-8"), None, {"reused": True}
    else:
        try:
            text, err, info = engine(row["prompt"])
        except Exception as e:
            text, err, info = "", f"{type(e).__name__}: {e}", {}
    row["engine_info"] = {k: info.get(k) for k in ("model", "elapsed_s", "cost_usd", "fallback",
                                                   "reused") if k in (info or {})}
    raw = vbp._clean_text(text)
    if err or not raw:
        row["error"] = f"engine: {err or 'trả chữ rỗng'}"
        return row
    row["new_raw"], ctx = raw, row["ctx"]
    if cached is not None and not (info or {}).get("reused"):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(raw, encoding="utf-8")
    try:
        final = vb.apply_brief_guards(raw, ctx)
    except Exception as e:                       # chữ đã trả tiền vẫn được ghi ra `new/`
        row["error"] = f"guard: {type(e).__name__}: {e}"
        return row
    row["new_final"] = final
    row["new_section"] = ta_section(final)
    row["new_raw_violations"] = count_violations(ta_section(raw), ctx)
    row["new_final_violations"] = count_violations(row["new_section"], ctx)
    row["guard"] = guard_diff(raw, final, ctx)
    return row


# ── Ước tính ─────────────────────────────────────────────────────────────

def estimate(rows: list[dict], model: str) -> dict:
    """Số lượt gọi + thời gian/chi phí: theo lượt đo 30/09 và theo token × bảng giá sổ LLM."""
    import vnstock_brief_pack as vbp
    from vnstock_llm_ledger import _cost_usd
    ready = [r for r in rows if not r.get("error")]
    chars = sum(len(r["prompt"]) + len(vbp.CLI_PREFACE) for r in ready)
    p_tok = int(chars / CHARS_PER_TOKEN)
    c_tok = OUTPUT_TOKENS_EST * len(ready)
    return {"calls": len(ready), "model": model, "prompt_chars": chars,
            "prompt_tokens_est": p_tok, "completion_tokens_est": c_tok,
            "usd_tokens": round(_cost_usd(f"ClaudeCode:{model}",
                                          {"prompt_tokens": p_tok, "completion_tokens": c_tok}), 2),
            "usd_measured": round(MEASURED_USD_PER_CALL * len(ready), 2),
            "minutes_measured": round(MEASURED_S_PER_CALL * len(ready) / 60, 1)}


def estimate_line(est: dict) -> str:
    return (f"Ước tính: {est['calls']} lượt gọi {est['model']} · ~{est['minutes_measured']:,.1f} phút "
            f"· ~${est['usd_measured']:,.2f} theo lượt đo 30/09 (${MEASURED_USD_PER_CALL:,.2f}/lượt, "
            f"{MEASURED_S_PER_CALL}s) · cận dưới theo bảng giá sổ LLM ${est['usd_tokens']:,.2f} "
            f"(~{est['prompt_tokens_est']:,} token vào + ~{est['completion_tokens_est']:,} ra). "
            "Thuê bao Claude không trừ tiền, nhưng ăn chung hạn mức với phiên code.")


# ── Báo cáo ──────────────────────────────────────────────────────────────

def _viol_txt(hits: dict | None) -> str:
    if hits is None:
        return "—"
    parts = [f"{RULE_NAMES[k]} {len(v)}" for k, v in hits.items() if v]
    return f"{n_violations(hits)} ({', '.join(parts)})" if parts else "0"


def _viol_lines(hits: dict | None) -> list[str]:
    return [f"  - [{RULE_NAMES[k]}] {s}" for k, v in (hits or {}).items() for s in v]


def _pct(v) -> str:
    return "—" if v is None else f"{v:+,.2f}%"


def _outcome_lines(o: dict | None) -> list[str]:
    if not o:
        return ["- —"]
    if not o.get("available"):
        return [f"- {o.get('reason')}"]
    out = [f"- Đóng cửa phiên {o['close']:,.2f} · T+1 {_pct(o.get('t1_pct'))} · "
           f"T+{FWD_SESSIONS} {_pct(o.get(f't{FWD_SESSIONS}_pct'))} "
           f"({o['sessions_after']} phiên sau có trong kho)"]
    touch = [f"{k} {v['level']:,.2f}: " + (f"chạm phiên T+{v['first_session']}"
                                         if v["first_session"] else "không chạm")
             for k, v in o.get("touch", {}).items()]
    if touch:
        out.append("- Mức của brief trong " + f"{FWD_SESSIONS} phiên: " + " · ".join(touch))
    if o.get("vol_t1_ratio") is not None:
        out.append(f"- KL T+1 = {o['vol_t1_ratio']:,.2f}× TB20")
    return out


def _block(text: str) -> list[str]:
    return ["```", text.strip() if text and text.strip() else "(không có mục 📈)", "```"]


def session_md(r: dict, dry_run: bool) -> list[str]:
    tag = "đã gửi" if r.get("sent") else ("bản Claude" if r.get("agent_type") == "claude" else "")
    out = [f"## Phiên {r['session']} · brief #{r.get('brief_id')} · {r.get('agent') or '?'}"
           + (f" ({tag})" if tag else ""), ""]
    if r.get("error") and not r.get("ta_card"):
        return out + [f"❌ Lỗi: {r['error']}", ""]
    out += [f"### Thẻ kỹ thuật dựng lại (bar tới hết {r['session']})"]
    out += [str(l) for l in (r.get("ta_card") or {}).get("lines") or []]
    for tk, c in (r.get("ta_cards") or {}).items():
        out.append(f"- {tk}: {(c or {}).get('line')}")
    out += [f"- ⚠️ {n}" for n in r.get("rebase_notes") or []]
    if r.get("card_errors"):
        out.append(f"- ⚠️ thẻ mã lỗi (bỏ mã đó): {r['card_errors']}")
    out += ["", "### 📈 brief CŨ (chữ trong DB)"] + _block(r.get("old_section", ""))
    out += [f"Vi phạm theo 5 luật mới: {_viol_txt(r.get('old_violations'))}"]
    out += _viol_lines(r.get("old_violations")) + ["", "### 📈 brief MỚI (sau guard)"]
    if r.get("error") and not r.get("prompt"):
        out += [f"❌ Lỗi: {r['error']}"]
    elif dry_run:
        out += [f"(dry-run — chưa gọi model; prompt ở `prompts/{r['session']}.md`)"]
    elif r.get("error"):
        out += [f"❌ Lỗi: {r['error']}"]
    else:
        g = r.get("guard") or {}
        out += _block(r.get("new_section", ""))
        out += [f"Guard: {g.get('raw_sentences', 0)} câu model → {g.get('final_sentences', 0)} câu"
                f" · bỏ {len(g.get('dropped') or [])} · mới/sửa {len(g.get('changed') or [])}"
                f" · dòng thẻ {'đủ' if g.get('card_lines_ok') else 'THIẾU'}"]
        out += [f"  - [bỏ] {s}" for s in g.get("dropped") or []]
        out += [f"  - [mới/sửa] {s}" for s in g.get("changed") or []]
        out += [f"Vi phạm chữ model TRƯỚC guard: {_viol_txt(r.get('new_raw_violations'))}"]
        out += _viol_lines(r.get("new_raw_violations"))
        out += [f"Vi phạm còn lại SAU guard: {_viol_txt(r.get('new_final_violations'))}"]
    out += ["", f"### Kết cục {FWD_SESSIONS} phiên sau — DỮ LIỆU TƯƠNG LAI (brief không thấy, "
                "chỉ để đối chiếu)"]
    return out + _outcome_lines(r.get("outcome")) + [""]


def summarize(rows: list[dict], dry_run: bool) -> dict:
    ok = [r for r in rows if r.get("ta_card")]
    ran = [r for r in ok if r.get("guard")]

    def _by_rule(key: str, src: list[dict]) -> dict[str, int]:
        return {k: sum(len((r.get(key) or {}).get(k) or []) for r in src) for k in RULE_KEYS}
    return {
        "sessions": len(rows), "with_card": len(ok), "ran": len(ran),
        "errors": [{"session": r["session"], "error": r["error"]} for r in rows if r.get("error")],
        "old_violations": _by_rule("old_violations", ok),
        "old_violations_on_ran": _by_rule("old_violations", ran),
        "new_raw_violations": _by_rule("new_raw_violations", ran),
        "new_final_violations": _by_rule("new_final_violations", ran),
        "dropped_sentences": sum(len(r["guard"]["dropped"]) for r in ran),
        "changed_sentences": sum(len(r["guard"]["changed"]) for r in ran),
        "dry_run": dry_run,
    }


def render_report(rows: list[dict], meta: dict) -> str:
    dry = bool(meta.get("dry_run"))
    s = summarize(rows, dry)
    head = [f"# Chạy lại lịch sử — brief chiều có thẻ kỹ thuật ({meta.get('run_date')})", "",
            f"- {len(rows)} phiên: {', '.join(r['session'] for r in rows) or '—'}",
            f"- Chế độ: {'DRY-RUN (không gọi model)' if dry else 'gọi model ' + str(meta.get('model'))}",
            "- Thẻ dựng bằng `vnstock_brief._attach_ta_cards` trên bar CẮT tới phiên; mức S/R của ctx "
            "đã lưu. Prompt mới = `build_prompt(ctx, \"afternoon\")` — KHÔNG có few-shot / lệnh mở / "
            "khối tin của hôm đó (dựng lại từ dữ liệu hiện tại là nhìn trước).",
            "- Vi phạm = câu chữ model trong mục 📈 mà 1 trong 5 guard mới sẽ bỏ/sửa (chạy từng câu, "
            "ctx có thẻ). Bản CŨ viết khi chưa có luật này — con số đo khoảng cách, không phải lỗi "
            "của bản cũ.", ""]
    body: list[str] = []
    for r in rows:
        body += session_md(r, dry)
    tbl = ["## Bảng tổng", "",
           "| Phiên | Vi phạm cũ | Vi phạm mới (trước guard) | Sau guard | Câu bị bỏ | Lỗi |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        g = r.get("guard")
        tbl.append(f"| {r['session']} | {_viol_txt(r.get('old_violations')) if r.get('ta_card') else '—'}"
                   f" | {_viol_txt(r.get('new_raw_violations')) if g else '—'}"
                   f" | {_viol_txt(r.get('new_final_violations')) if g else '—'}"
                   f" | {len(g['dropped']) if g else '—'} | {(r.get('error') or '').replace('|', '/')} |")
    tot = ["", f"- Phiên có thẻ: {s['with_card']}/{s['sessions']} · đã gọi model OK: {s['ran']} · "
               f"phiên lỗi: {len(s['errors'])}"]
    for name, key in (("Vi phạm bản CŨ (mọi phiên có thẻ)", "old_violations"),
                      ("Vi phạm bản CŨ (chỉ phiên đã chạy model)", "old_violations_on_ran"),
                      ("Vi phạm bản MỚI trước guard", "new_raw_violations"),
                      ("Vi phạm bản MỚI sau guard", "new_final_violations")):
        if key != "old_violations" and dry:
            continue
        v = s[key]
        tot.append(f"- {name}: {sum(v.values())} — "
                   + " · ".join(f"{RULE_NAMES[k]} {v[k]}" for k in RULE_KEYS))
    if not dry:
        tot.append(f"- Câu guard bỏ ở bản mới: {s['dropped_sentences']} · câu mới/sửa: "
                   f"{s['changed_sentences']}")
    return "\n".join(head + body + tbl + tot) + "\n"


def _json_row(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("ctx", "prompt", "new_raw", "new_final")}


def write_outputs(out_dir: Path, rows: list[dict], meta: dict) -> Path:
    out_dir = Path(out_dir)
    (out_dir / "prompts").mkdir(parents=True, exist_ok=True)
    for r in rows:
        if r.get("prompt"):
            (out_dir / "prompts" / f"{r['session']}.md").write_text(r["prompt"], encoding="utf-8")
        if r.get("new_raw"):
            (out_dir / "new").mkdir(exist_ok=True)
            (out_dir / "new" / f"{r['session']}.raw.md").write_text(r["new_raw"], encoding="utf-8")
        if r.get("new_final"):
            (out_dir / "new" / f"{r['session']}.md").write_text(r["new_final"], encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(rows, meta), encoding="utf-8")
    payload = {"meta": meta, "summary": summarize(rows, bool(meta.get("dry_run"))),
               "sessions": [_json_row(r) for r in rows]}
    (out_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out_dir


# ── IO + CLI ─────────────────────────────────────────────────────────────

def _ticker_loader(prices_dir: Path, sessions: list[dict]) -> Callable[[str], pd.DataFrame]:
    """Toàn bộ lịch sử mã cần cho phiên cũ nhất (+ cửa sổ thẻ), đọc kho một lần mỗi mã."""
    from vnstock_strategy import _load_history_from_parquet
    first = min((str(b["brief_date"])[:10] for b in sessions), default=date.today().isoformat())
    days = (date.today() - date.fromisoformat(first)).days + vb._TA_CARD_HISTORY_DAYS + 10
    cache: dict[str, pd.DataFrame] = {}

    def _load(tk: str) -> pd.DataFrame:
        if tk not in cache:
            cache[tk] = _load_history_from_parquet(tk, days, prices_dir=prices_dir)
        return cache[tk]
    return _load


def _default_out(dry_run: bool) -> Path:
    """Dry-run ghi thư mục RIÊNG `<ngày>-dry`: chạy lại dry-run buổi chiều không được đè
    `report.*` của lượt `--run` đã trả tiền buổi sáng. Lượt `--run` cùng ngày dùng chung
    `<ngày>/` để DÙNG LẠI `new/*.raw.md` đã có (chạy tiếp sau khi đứt giữa chừng)."""
    name = date.today().isoformat() + ("-dry" if dry_run else "")
    return _REPO / "data_warehouse" / "_meta" / "replay_ta" / name


def _reset_timeout_memo() -> None:
    """Một lượt timeout 600s làm `vnstock_claude_cli` ghi nhớ "CLI chết" cho cả tiến trình —
    đúng cho brief đêm (1 lượt), sai cho 20 phiên: phiên 4..20 sẽ hỏng trong vài giây. Chỉ
    xoá ghi nhớ khi lý do là TIMEOUT; thiếu exe / chưa đăng nhập vẫn giữ (lượt nào cũng thế)."""
    import vnstock_claude_cli as vcc
    if str(vcc._DEAD_REASON or "").startswith("claude CLI quá"):
        vcc.reset_dead_memo()


def main(argv: list[str] | None = None, *, engine: Engine | None = None,
         ask: Callable[[str], str] = input) -> int:
    ap = argparse.ArgumentParser(description="Chạy lại lịch sử brief chiều có thẻ kỹ thuật (PTKT §14)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="số phiên gần nhất (mặc định 20)")
    ap.add_argument("--run", action="store_true", help="gọi model (mặc định: dry-run, 0 lượt gọi)")
    ap.add_argument("--yes", action="store_true", help="không hỏi xác nhận trước khi gọi model")
    ap.add_argument("--out", type=Path, default=None,
                    help="thư mục output (mặc định data_warehouse/_meta/replay_ta/<ngày chạy>/, dry-run <ngày chạy>-dry/). Lượt --run dùng lại new/<phiên>.raw.md đã có trong thư mục")
    ap.add_argument("--db", type=Path, default=None, help="brief_memory.db (mặc định của vnstock_memory)")
    a = ap.parse_args(argv)

    vb._ensure_env_loaded()
    os.environ["VNSTOCK_TA_CARD"] = "1"            # chỉ tiến trình này — không đụng .env
    import vnstock_brief_pack as vbp
    db = a.db or tsio._db_path()
    sessions = select_sessions(tsio.load_briefs(db), a.limit)
    if not sessions:
        print(f"Không có brief chiều đã gửi / bản Claude có context_json trong {db}")
        return 1
    index_bars = vb._load_vnindex_df(augment=False)
    load_ticker = _ticker_loader(vb._VNINDEX_PRICES_DIR, sessions)
    rows = [prepare_session(b, index_bars, load_ticker) for b in sessions]
    model = vbp.cli_model()
    meta = {"run_date": date.today().isoformat(), "dry_run": not a.run, "model": model,
            "db": str(db), "limit": a.limit}
    print(f"{len(rows)} phiên: {rows[0]['session']} → {rows[-1]['session']} · "
          f"lỗi dựng: {sum(1 for r in rows if r.get('error'))}")
    out_dir = a.out or _default_out(not a.run)
    if a.run:
        # Phiên đã có `new/<phiên>.raw.md` dùng lại bản đó (0 lượt gọi) ⇒ không tính vào ước tính:
        # sửa guard rồi chạy lại đúng lệnh là chấm lại 20 bản đã trả tiền MIỄN PHÍ.
        def _cached(r: dict) -> bool:
            p = _raw_path(out_dir, r["session"])
            return p.is_file() and bool(p.read_text(encoding="utf-8").strip())
        est = estimate([r for r in rows if not _cached(r)], model)
        est["reused"] = sum(1 for r in rows if not r.get("error") and _cached(r))
        meta["estimate"] = est
        print(estimate_line(est) + (f" · dùng lại {est['reused']} bản đã có (0 lượt gọi)"
                                    if est["reused"] else ""))
        if est["calls"] and not a.yes and ask(f"Gọi {est['calls']} lượt? [y/N] ").strip().lower() \
                not in ("y", "yes", "c", "có"):
            print("Huỷ — không gọi model.")
            return 1
    if a.run:
        eng = engine or vbp.run_claude_cli
        streak = 0
        try:
            for r in rows:
                if r.get("error"):
                    continue
                _reset_timeout_memo()
                run_engine(r, eng, out_dir)
                reused = (r.get("engine_info") or {}).get("reused")
                print(f"  {r['session']}: " + (f"❌ {r['error']}" if r.get("error") else
                                               f"✅ {len(r.get('new_raw') or ''):,} ký tự"
                                               + (" (dùng lại bản đã có)" if reused else "")))
                failed = str(r.get("error") or "").startswith("engine:")
                streak = streak + 1 if failed else 0
                if streak >= ENGINE_FAIL_STREAK_MAX:
                    print(f"⛔ DỪNG SỚM: {streak} phiên liên tiếp engine lỗi — chạy lại ĐÚNG lệnh "
                          f"này sau (phiên đã xong được dùng lại, không tốn lượt gọi).")
                    meta["stopped_early"] = True
                    break
        finally:                                 # Ctrl+C giữa chừng vẫn có report cho phần đã chạy
            out = write_outputs(out_dir, rows, meta)
            print(f"Báo cáo: {out / 'report.md'}")
        return 0
    out = write_outputs(out_dir, rows, meta)
    print(f"Báo cáo: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
