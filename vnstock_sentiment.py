"""vnstock_sentiment.py — News sentiment scoring for VNStock Dashboard.

Scores news headlines via a lightweight LLM (Groq → Cerebras → OpenRouter).
Results are cached to SQLite so each article is only scored once.

Sentiment values: "positive" | "negative" | "neutral"
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date as _date, timedelta as _td
from pathlib import Path
from typing import Optional


# ── Strip think-tags + ledger (2 món deep-dive DojoAgents 2026-07-15) ───────
# Model reasoning free (deepseek-r1 style) suy nghĩ thành tiếng trong cặp
# thẻ <think>…</think>; một số provider còn NUỐT thẻ mở → output bắt đầu
# giữa dòng suy nghĩ và kết thúc bằng "</think>" rồi mới tới đáp án. Lọt
# vào digest/sentiment là phá format (cùng họ lỗi "bắt buộc"/CJK leak).
_THINK_NAMES = r"(think|thinking|reasoning|thought)"
_THINK_PAIR_RE = re.compile(
    rf"<\s*{_THINK_NAMES}\s*>.*?<\s*/\s*\1\s*>\s*", re.S | re.I)
_THINK_CLOSE_ORPHAN_RE = re.compile(
    rf"\A.*?<\s*/\s*{_THINK_NAMES}\s*>\s*", re.S | re.I)
_THINK_OPEN_ORPHAN_RE = re.compile(
    rf"<\s*{_THINK_NAMES}\s*>.*\Z", re.S | re.I)


def strip_think_tags(text: "str | None") -> str:
    """Xóa khối suy-nghĩ-thành-tiếng của model reasoning khỏi output.

    3 dạng theo thứ tự: cặp thẻ đủ → xóa cả khối; "</think>" MỒ CÔI (thẻ mở
    bị provider nuốt) → xóa từ đầu tới hết thẻ đóng; thẻ mở không đóng
    (bị cắt giữa chừng vì hết token) → xóa từ thẻ mở tới cuối. Chỉ khớp
    đúng 4 tên thẻ nên "P/E <10"/"M&A" không bị đụng."""
    if not text or "<" not in text:
        return (text or "").strip()
    out = _THINK_PAIR_RE.sub("", text)
    out = _THINK_CLOSE_ORPHAN_RE.sub("", out)
    out = _THINK_OPEN_ORPHAN_RE.sub("", out)
    return out.strip()


def _ledger_record(provider: str, model: str, ok: bool,
                   usage: "dict | None" = None,
                   error: "str | None" = None) -> None:
    """Ghi sổ call LLM — best-effort tuyệt đối (không bao giờ raise)."""
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


def _provider_dead_today(name: str) -> "str | None":
    """Provider hỏng TÀI KHOẢN hôm nay (401/402/403, chưa call nào OK)? Best-
    effort — sổ hỏng ⇒ None. Ca 14/09: Cerebras 402 mà ladder vẫn gõ mỗi lần."""
    try:
        from vnstock_llm_ledger import provider_blocked_today
        return provider_blocked_today(name)
    except Exception:
        return None


def _alert_down(context: str) -> None:
    """Cạn TOÀN BỘ nấc model → báo Telegram (yêu cầu user 22/07 khi chốt
    all-free). Throttle 1 lần/ngày + kill-switch VNSTOCK_LLM_ALERT nằm ở
    vnstock_llm_ledger.alert_ladder_down — đây chỉ là wrapper best-effort."""
    try:
        from vnstock_llm_ledger import alert_ladder_down
        alert_ladder_down(context)
    except Exception:
        pass

_REPO = Path(__file__).parent
SENTIMENT_DB_PATH = _REPO / "data_warehouse" / "_meta" / "sentiment_cache.db"

_db_lock = threading.Lock()

# ── DB ─────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    SENTIMENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SENTIMENT_DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_sentiment (
            item_hash TEXT PRIMARY KEY,
            ticker    TEXT NOT NULL,
            date      TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            model     TEXT,
            scored_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _item_hash(item: dict) -> str:
    ticker = (item.get("ticker") or "").upper()
    d      = (item.get("_date_sort") or "")[:10]
    title  = (item.get("news_title") or item.get("title") or item.get("head") or "").strip()
    return hashlib.md5(f"{ticker}|{d}|{title}".encode()).hexdigest()


# ── LLM providers ─────────────────────────────────────────────────────────

_SYSTEM = (
    "Bạn là chuyên gia phân tích tin tức chứng khoán Việt Nam. "
    "Phân loại sentiment của tin tức theo quan điểm nhà đầu tư: "
    "TÍCH_CỰC (tin tốt cho cổ phiếu), TIÊU_CỰC (tin xấu cho cổ phiếu), "
    "TRUNG_LẬP (không ảnh hưởng rõ ràng). "
    "Chỉ trả lời đúng 1 từ: TÍCH_CỰC hoặc TIÊU_CỰC hoặc TRUNG_LẬP."
)

# Ladder thay 22/07/2026 (probe 2 vòng trên máy thật — scripts/probe_models.py):
# ladder 8B llama cũ chết gần hết (Groq deprecate 17/06, Cerebras đã gỡ,
# OpenRouter hết bản :free). Nấc 1 = Gemini Flash-Lite (free tier 1,500
# req/ngày; key Postpay ~$0.10/$0.40 per 1M — vẫn ≈0 với volume sentiment).
# gpt-oss là REASONING model: cần "max_tokens" rộng để suy nghĩ trước khi
# trả 1 từ (mặc định 10 là cụt output) + "extra" reasoning_effort=low trên
# Groq; phần đuôi think-tag đã có strip_think_tags lo.
_PROVIDERS = [
    {
        "name": "Gemini",
        "env": "GEMINI_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-3.5-flash-lite",
        "max_tokens": 256,
    },
    {
        "name": "Groq",
        "env": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "openai/gpt-oss-20b",
        "max_tokens": 256,
        "extra": {"reasoning_effort": "low"},
    },
    # 29/09: nấc Cerebras gemma-4-31b GỠ — provider archive (HTTP 404, model
    # watch 19/09 + 26/09); ledger 22/09 đếm 10 call/ngày 404 vô ích vì cầu
    # dao chỉ chặn 401/402/403. Không thay nấc khác: tài khoản Cerebras đang
    # 402 (#3), OpenRouter thì quota 50 req/ngày phải để dành cho brief.
    # 22/08: nấc OpenRouter `openai/gpt-oss-20b:free` ĐÃ GỠ — probe T7 ra
    # HTTP 404 "This model is unavailable for free" và slug biến mất khỏi
    # danh mục. Nấc cuối chỉ có thể hỏng thì giữ lại là tốn một request mỗi
    # lần rơi hết thang. Muốn có lại nấc thứ 4 thì probe slug free mới TRÊN
    # MÁY THẬT trước (scripts/probe_models.py) — không chép từ catalog.
]

_SENTIMENT_MAP: dict[str, str] = {
    "tích_cực": "positive", "tiêu_cực": "negative", "trung_lập": "neutral",
    "tich_cuc": "positive", "tieu_cuc": "negative", "trung_lap": "neutral",
    "tích cực": "positive", "tiêu cực": "negative", "trung lập": "neutral",
    "positive": "positive", "negative": "negative", "neutral": "neutral",
}


# ── Claude Code theo LÔ (30/09, #26) ──────────────────────────────────────────
# Mỗi tin một tiến trình `claude -p` là spawn ×N (3–10s/lượt) — gom cả lô
# `to_score` vào MỘT call trả JSON, map `i` → item_hash tại chỗ (không bắt
# model chép md5). Tin thiếu/nhãn lạ → ladder từng tin như cũ; lỗi CLI ⇒ cả
# lô về ladder. Công tắc: VNSTOCK_NEWS_ENGINE / VNSTOCK_LLM_ENGINE = claude.
_CLI_BATCH_SIZE = 50
_CLI_TIMEOUT_S = 300
_BATCH_SYSTEM = _SYSTEM.replace(
    "Chỉ trả lời đúng 1 từ: TÍCH_CỰC hoặc TIÊU_CỰC hoặc TRUNG_LẬP.",
    "Nhận một DANH SÁCH tin (JSON, mỗi tin có số thứ tự `i`). Trả về JSON đúng "
    'schema {"results": [{"i": <i>, "sentiment": "TÍCH_CỰC|TIÊU_CỰC|TRUNG_LẬP"}]} '
    "— đủ MỌI i, không thêm chữ nào khác.")
_BATCH_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer"}, "sentiment": {"type": "string"}},
        "required": ["i", "sentiment"]}}},
    "required": ["results"],
}


def _label_of(raw) -> Optional[str]:
    low = str(raw or "").lower()
    for key_str, val in _SENTIMENT_MAP.items():
        if key_str in low:
            return val
    return None


def _claude_batch_enabled() -> bool:
    try:
        import vnstock_claude_cli as vcc
        return vcc.engine_for("news") == "claude"
    except Exception:
        return False


def cli_engine_label() -> Optional[str]:
    """"Claude Code (CLI)" khi bước news chạy engine claude — cổng chấm điểm ở
    run.py không còn đòi key free; None khi không."""
    return "Claude Code (CLI)" if _claude_batch_enabled() else None


def _item_prompt_fields(item: dict) -> dict:
    ticker = (item.get("ticker") or "").upper()
    title = (item.get("news_title") or item.get("title") or item.get("head") or "").strip()
    short = (item.get("news_short_content") or item.get("news_sub_title") or "").strip()[:200]
    return {"ma": ticker, "tieu_de": title, "tom_tat": short}


def score_batch_cli(items: list[dict]) -> dict[str, tuple[str, str]]:
    """Chấm CẢ LÔ qua Claude Code: {item_hash: (sentiment, model)}. Tin thiếu
    trong trả lời / nhãn lạ KHÔNG có trong dict (chỗ gọi đưa qua ladder).
    Lỗi CLI ở lô nào ⇒ dừng, trả những gì đã có."""
    import json as _json
    try:
        import vnstock_claude_cli as vcc
    except Exception:
        return {}
    out: dict[str, tuple[str, str]] = {}
    raw_t = (os.environ.get("VNSTOCK_NEWS_CLI_TIMEOUT_S") or "").strip()
    timeout = vcc.cli_timeout_s("VNSTOCK_NEWS_CLI_TIMEOUT_S") if raw_t else _CLI_TIMEOUT_S
    for start in range(0, len(items), _CLI_BATCH_SIZE):
        chunk = items[start:start + _CLI_BATCH_SIZE]
        rows = [{"i": i, **_item_prompt_fields(it)} for i, it in enumerate(chunk)]
        user = "Danh sách tin:\n" + _json.dumps(rows, ensure_ascii=False)
        text, err, info = vcc.complete(
            user, system=_BATCH_SYSTEM, json_schema=_BATCH_SCHEMA,
            model=vcc.cli_model("VNSTOCK_NEWS_CLI_MODEL"), timeout_s=timeout, tag="news")
        print(vcc.outcome_line("news", info, text, err))
        if err:
            break
        data = info.get("structured")
        if not isinstance(data, dict):
            try:
                data = _json.loads(text)
            except ValueError:
                break
        model = f"ClaudeCode:{info.get('model') or vcc.cli_model()}"
        for r in (data.get("results") or []) if isinstance(data, dict) else []:
            try:
                i = int((r or {}).get("i"))
            except (TypeError, ValueError):
                continue
            label = _label_of((r or {}).get("sentiment"))
            if label and 0 <= i < len(chunk):
                out[_item_hash(chunk[i])] = (label, model)
    return out


def _call_provider(provider: dict, text: str) -> Optional[str]:
    key = (os.environ.get(provider["env"]) or "").strip()
    if not key:
        return None
    if _provider_dead_today(provider["name"]):
        return None                           # tài khoản hỏng hôm nay — nấc kế
    try:
        import requests as _req
        resp = _req.post(
            provider["endpoint"],
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            json={
                "model": provider["model"],
                # reasoning model cần chỗ suy nghĩ — 10 token là cụt output
                "max_tokens": int(provider.get("max_tokens") or 64),
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
                **(provider.get("extra") or {}),
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        _ledger_record(provider["name"], provider["model"], ok=True,
                       usage=body.get("usage"))
        raw = strip_think_tags(
            body["choices"][0]["message"]["content"]).lower()
        for key_str, val in _SENTIMENT_MAP.items():
            if key_str in raw:
                return val
        return "neutral"
    except Exception as e:
        _ledger_record(provider["name"], provider["model"], ok=False,
                       error=str(e))
        return None


def available_provider() -> Optional[str]:
    """Return name of first available provider, or None."""
    for p in _PROVIDERS:
        if (os.environ.get(p["env"]) or "").strip():
            return p["name"]
    return None


# Provider CẮT đáp án vì chạm trần max_tokens: OpenAI-compat (Groq/Cerebras/
# OpenRouter + endpoint compat của Gemini) trả finish_reason "length", Gemini
# native "MAX_TOKENS", Anthropic stop_reason "max_tokens". Close 08/09: khối
# tin in "— tác động: Nh" — câu bị cắt giữa từ KHÔNG có "…", tức không phải
# sanitize_impact (nó cắt ở biên từ + thêm "…") mà là provider cắt ở 120 token,
# rồi câu cụt trông y hệt câu ngắn hợp lệ nên lọt vào cache vĩnh viễn. Nay
# đọc lý do dừng: bị cắt → gọi lại ĐÚNG nấc đó một lần với trần rộng gấp
# _TRUNCATE_RETRY_X, và trả cờ `truncated` để caller quyết (analyze_item
# KHÔNG cache câu cụt).
_TRUNCATED_REASONS = frozenset({"length", "max_tokens"})
_TRUNCATE_RETRY_X = 3


def _is_truncated(finish_reason) -> bool:
    """True khi lý do dừng của provider là "hết token" (mọi wire format)."""
    return str(finish_reason or "").strip().lower() in _TRUNCATED_REASONS


def chat_complete_ex(system: str, user: str, max_tokens: int = 80,
                     model_map: "dict | None" = None) -> "dict | None":
    """One-shot chat qua ladder provider, trả KÈM lý do dừng.

    ``{"text", "model": "Provider:model", "finish_reason", "truncated"}`` —
    nấc THẬT đã trả lời; ``None`` khi cạn thang. Provider cắt vì hết token →
    gọi lại đúng nấc đó MỘT lần với trần rộng hơn (bị cắt lần nữa hoặc lỗi
    thì trả kết quả lần đầu kèm ``truncated=True`` — caller tự quyết có dùng
    câu cụt không). ``chat_complete`` là wrapper giữ chữ ký cũ.

    ``model_map`` ({provider_name: model}) overrides the default per-provider
    model — e.g. a stronger 70B for nuanced analysis — and falls back to the
    provider's default model if the override is rejected.
    """
    model_map = model_map or {}
    import requests as _req

    def _post(p: dict, key: str, model: str, mt: int) -> tuple:
        resp = _req.post(
            p["endpoint"],
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": mt,
                  "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  # extra tune cho model MẶC ĐỊNH của provider (vd
                  # reasoning_effort của gpt-oss) — model override
                  # khác họ có thể 400 vì param lạ → không gửi kèm
                  **((p.get("extra") or {}) if model == p["model"] else {})},
            timeout=25,
        )
        resp.raise_for_status()
        body = resp.json()
        _ledger_record(p["name"], model, ok=True, usage=body.get("usage"))
        choice = (body.get("choices") or [{}])[0] or {}
        text = strip_think_tags((choice.get("message") or {}).get("content") or "")
        return text, choice.get("finish_reason")

    # Câu cụt giữ lại làm lưới CUỐI: chỉ trả khi cạn thang — ledger 09/09 cho
    # thấy lần gọi lại hay dính 429 (bắn ngay sau lần đầu), mà trả câu cụt về
    # là caller (analyze_item) từ chối ⇒ tin trống trong khi nấc kế còn sống.
    cut_fallback: "dict | None" = None
    for p in _PROVIDERS:
        key = (os.environ.get(p["env"]) or "").strip()
        if not key:
            continue
        if _provider_dead_today(p["name"]):
            continue                          # 401/402/403 hôm nay — bỏ nấc
        models: list[str] = []
        ov = model_map.get(p["name"])
        if ov and ov != p["model"]:
            models.append(ov)            # preferred (stronger) model first
        models.append(p["model"])        # default fallback
        # sàn max_tokens theo provider: reasoning model (gpt-oss…) tiêu budget
        # vào suy nghĩ trước — caller xin 80 mà cấp đúng 80 là cụt đáp án
        floor_mt = max(max_tokens, int(p.get("max_tokens") or 0))
        for model in models:
            try:
                text, fin = _post(p, key, model, floor_mt)
            except Exception as e:
                _ledger_record(p["name"], model, ok=False, error=str(e))
                continue
            if _is_truncated(fin):
                # Bị cắt giữa câu → thử lại đúng nấc này với trần rộng hơn.
                try:
                    text, fin = _post(p, key, model, floor_mt * _TRUNCATE_RETRY_X)
                except Exception as e:
                    _ledger_record(p["name"], model, ok=False, error=str(e))
                    # gọi lại lỗi (thường là 429 vì bắn sát lần đầu) → giữ câu
                    # cụt làm lưới cuối, rồi ĐI TIẾP nấc kế để lấy câu trọn
                    cut_fallback = cut_fallback or {
                        "text": text, "model": f"{p['name']}:{model}",
                        "finish_reason": fin, "truncated": True}
                    continue
            return {"text": text, "model": f"{p['name']}:{model}",
                    "finish_reason": fin, "truncated": _is_truncated(fin)}
    if cut_fallback:
        return cut_fallback          # cạn thang: câu cụt vẫn hơn tay trắng
    _alert_down("chat_complete (chấm tin/analyze fallback)")
    return None


def chat_complete(system: str, user: str, max_tokens: int = 80,
                  model_map: "dict | None" = None,
                  with_model: bool = False):
    """Generic one-shot chat over the provider ladder (Groq→Cerebras→OpenRouter).

    Returns the raw assistant text, or None when no provider key works / all
    fail. Additive helper (does not change score_one's behaviour) reused by the
    market-news analyzer to get sentiment + a one-line impact in a single call.

    ``with_model=True`` đổi kiểu trả về thành ``(text, "Provider:model")`` —
    nấc THẬT đã trả lời, để caller ghi sổ (điểm [8] classifier ghi cột `model`
    của kho phân loại). Cạn thang → ``(None, "")``. Mặc định False giữ nguyên
    chữ ký cũ cho mọi caller sẵn có.

    Wrapper mỏng trên ``chat_complete_ex`` — cần biết đáp án có bị provider
    cắt không thì gọi thẳng bản ``_ex``.
    """
    out = chat_complete_ex(system, user, max_tokens=max_tokens,
                           model_map=model_map)
    if out is None:
        return (None, "") if with_model else None
    return (out["text"], out["model"]) if with_model else out["text"]


_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
# Mặc định = model Claude repo đang dùng cho brief (ClaudeAgent) — đổi model
# qua tham số `model` (vd claude-opus-4-8 khi cần nuance tối đa). LƯU Ý:
# request KHÔNG gửi temperature — Opus 4.7+ đã bỏ sampling params (400).
_ANTHROPIC_MODEL_DEFAULT = "claude-haiku-4-5-20251001"


def anthropic_complete_ex(system: str, user: str, max_tokens: int = 120,
                          model: Optional[str] = None) -> "dict | None":
    """One-shot Anthropic Messages API — route TRẢ PHÍ cho tác vụ cần nuance
    hơn ladder free (TODO 1b: chấm tin ≤8 call/ngày → chi phí nhỏ; 70B free
    hay bịa chiều tác động). Wire format khác OpenAI-compat: system là field
    riêng, header x-api-key + anthropic-version, text nằm trong content
    blocks, lý do dừng ở ``stop_reason`` ("max_tokens" = bị cắt → gọi lại
    một lần với trần rộng hơn, như ``chat_complete_ex``).

    Trả ``{"text", "model", "finish_reason", "truncated"}``; None khi thiếu
    key / lỗi / rỗng — caller tự fallback ladder free.
    """
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    model = (model or "").strip() or _ANTHROPIC_MODEL_DEFAULT
    import requests as _req

    def _post(mt: int) -> tuple:
        resp = _req.post(
            _ANTHROPIC_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            json={"model": model, "max_tokens": mt,
                  "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=25,
        )
        resp.raise_for_status()
        body = resp.json()
        _ledger_record("Anthropic", model, ok=True, usage=body.get("usage"))
        text = "".join(b.get("text", "") for b in (body.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text")
        return strip_think_tags(text), body.get("stop_reason")

    try:
        text, fin = _post(max_tokens)
    except Exception as e:
        _ledger_record("Anthropic", model, ok=False, error=str(e))
        return None
    if _is_truncated(fin):
        try:
            text, fin = _post(max_tokens * _TRUNCATE_RETRY_X)
        except Exception as e:
            _ledger_record("Anthropic", model, ok=False, error=str(e))
    if not text:
        return None
    return {"text": text, "model": f"Anthropic:{model}",
            "finish_reason": fin, "truncated": _is_truncated(fin)}


def anthropic_complete(system: str, user: str, max_tokens: int = 120,
                       model: Optional[str] = None) -> Optional[str]:
    """Wrapper giữ chữ ký cũ của ``anthropic_complete_ex``: chỉ trả text
    (None khi thiếu key / lỗi / rỗng)."""
    out = anthropic_complete_ex(system, user, max_tokens=max_tokens, model=model)
    return out["text"] if out else None


def score_one(item: dict) -> tuple[str, str, Optional[str]]:
    """Score one news item. Returns (item_hash, sentiment, provider_name)."""
    h      = _item_hash(item)
    ticker = (item.get("ticker") or "").upper()
    title  = (item.get("news_title") or item.get("title") or item.get("head") or "").strip()
    short  = (
        item.get("news_short_content") or item.get("news_sub_title") or ""
    ).strip()[:200]

    text = f"Mã: {ticker}\nTiêu đề: {title}"
    if short:
        text += f"\nTóm tắt: {short}"

    for p in _PROVIDERS:
        result = _call_provider(p, text)
        if result:
            return h, result, p["name"]
    return h, "neutral", None


# ── Batch scoring ─────────────────────────────────────────────────────────

def score_news_batch(
    news: list[dict],
    max_workers: int = 5,
    progress_cb=None,
) -> dict[str, str]:
    """Score news list, skip already-cached items. Returns hash→sentiment map."""
    with _db_lock:
        conn = _get_conn()
        rows = conn.execute("SELECT item_hash, sentiment FROM news_sentiment").fetchall()
        conn.close()
    cached = {r[0]: r[1] for r in rows}

    to_score = [n for n in news if _item_hash(n) not in cached]
    total = len(to_score)
    done_count = 0
    new_rows: list[tuple] = []
    new_results: dict[str, str] = {}
    scored_at = datetime.now().isoformat()

    # Engine Claude: cả lô một call trước, phần thiếu mới qua ladder từng tin.
    if to_score and _claude_batch_enabled():
        got = score_batch_cli(to_score)
        rest: list[dict] = []
        for item in to_score:
            h = _item_hash(item)
            if h in got:
                sentiment, model = got[h]
                new_results[h] = sentiment
                new_rows.append((h, (item.get("ticker") or "").upper(),
                                 (item.get("_date_sort") or "")[:10],
                                 sentiment, model, scored_at))
                done_count += 1
                if progress_cb:
                    try:
                        progress_cb(done_count, total)
                    except Exception:
                        pass
            else:
                rest.append(item)
        print(f"[sentiment] Claude Code chấm {len(got)}/{total} tin theo lô; "
              f"{len(rest)} tin còn lại qua ladder")
        to_score = rest

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(score_one, item): item for item in to_score}
        for fut in as_completed(futures):
            try:
                h, sentiment, model = fut.result()
                item = futures[fut]
                new_results[h] = sentiment
                new_rows.append((
                    h,
                    (item.get("ticker") or "").upper(),
                    (item.get("_date_sort") or "")[:10],
                    sentiment,
                    model or "",
                    scored_at,
                ))
            except Exception:
                pass
            done_count += 1
            if progress_cb:
                try:
                    progress_cb(done_count, total)
                except Exception:
                    pass

    # Batch có tin cần chấm mà KHÔNG provider nào trả kết quả (cột model
    # rỗng toàn bộ) = ladder sentiment down → báo user (22/07). Ngưỡng ≥3
    # tránh báo nhầm vì 1-2 tin lẻ trục trặc.
    if total >= 3 and new_rows and all(not r[4] for r in new_rows):
        _alert_down("sentiment tin tức (score_news_batch)")

    # Tin KHÔNG provider nào chấm được (cột model rỗng) → `score_one` trả
    # "neutral" mặc định. Ghi nó vào cache là ĐÓNG BĂNG VĨNH VIỄN: lần sau
    # `cached` đã có hash nên tin không bao giờ được chấm lại, dù ladder đã
    # hồi (audit 06/08). Chỉ lưu tin CÓ model; tin còn lại để lần sau thử lại.
    unscored = [r for r in new_rows if not r[4]]
    if unscored:
        print(f"[sentiment] {len(unscored)}/{len(new_rows)} tin chưa chấm được "
              f"(ladder lỗi) — KHÔNG cache, sẽ thử lại lần sau")
        new_rows = [r for r in new_rows if r[4]]

    if new_rows:
        with _db_lock:
            conn = _get_conn()
            conn.executemany(
                "INSERT OR REPLACE INTO news_sentiment "
                "(item_hash, ticker, date, sentiment, model, scored_at) VALUES (?,?,?,?,?,?)",
                new_rows,
            )
            conn.commit()
            conn.close()

    return {**cached, **new_results}


def attach_sentiments(news: list[dict]) -> list[dict]:
    """Non-scoring: add '_sentiment' field from cache to each news item."""
    try:
        with _db_lock:
            conn = _get_conn()
            rows = conn.execute("SELECT item_hash, sentiment FROM news_sentiment").fetchall()
            conn.close()
        mapping = {r[0]: r[1] for r in rows}
        for item in news:
            item["_sentiment"] = mapping.get(_item_hash(item), "")
    except Exception:
        for item in news:
            item.setdefault("_sentiment", "")
    return news


def scored_count(news: list[dict]) -> int:
    """Number of items that already have a cached sentiment score."""
    try:
        with _db_lock:
            conn = _get_conn()
            rows = conn.execute("SELECT item_hash FROM news_sentiment").fetchall()
            conn.close()
        hashes = {r[0] for r in rows}
        return sum(1 for n in news if _item_hash(n) in hashes)
    except Exception:
        return 0


# ── Aggregation ───────────────────────────────────────────────────────────

_SIGNAL_LABEL = {
    "strong_pos": "🟢 Tích cực mạnh",
    "pos":        "🟡 Hơi tích cực",
    "neutral":    "⚪ Trung lập",
    "neg":        "🟠 Hơi tiêu cực",
    "strong_neg": "🔴 Tiêu cực mạnh",
}


def ticker_sentiment_summary(
    news: list[dict],
    days: int = 7,
) -> list[dict]:
    """Aggregate sentiment by ticker for the last N days.

    Returns list of dicts sorted by net_score desc.
    """
    cutoff = (_date.today() - _td(days=days)).isoformat()
    recent = [
        n for n in news
        if n.get("_date_sort", "") >= cutoff and n.get("_sentiment")
    ]

    counts: dict[str, dict[str, int]] = {}
    for n in recent:
        t = (n.get("ticker") or "").upper()
        if not t:
            continue
        if t not in counts:
            counts[t] = {"positive": 0, "negative": 0, "neutral": 0}
        s = n["_sentiment"]
        if s in counts[t]:
            counts[t][s] += 1

    rows = []
    for ticker, c in counts.items():
        total = c["positive"] + c["negative"] + c["neutral"]
        if total == 0:
            continue
        net = c["positive"] - c["negative"]
        if net >= 2:
            sig = _SIGNAL_LABEL["strong_pos"]
        elif net == 1:
            sig = _SIGNAL_LABEL["pos"]
        elif net == -1:
            sig = _SIGNAL_LABEL["neg"]
        elif net <= -2:
            sig = _SIGNAL_LABEL["strong_neg"]
        else:
            sig = _SIGNAL_LABEL["neutral"]

        rows.append({
            "Mã": ticker,
            "Tích cực": c["positive"],
            "Tiêu cực": c["negative"],
            "Trung lập": c["neutral"],
            "Tổng": total,
            "Net": net,
            "Tín hiệu": sig,
        })

    rows.sort(key=lambda r: r["Net"], reverse=True)
    return rows


def market_news_sentiment(news: list[dict], days: int = 7) -> dict:
    """Aggregate news sentiment across the WHOLE market for the last N days.

    Unlike ticker_sentiment_summary (per ticker), this rolls every scored
    article up into one market-mood reading. Returns:
      {positive, negative, neutral, total, pos_pct, neg_pct, net_pct}
    where net_pct = (positive - negative) / total * 100  (-100..+100).
    Empty dict if no scored news in the window.
    """
    cutoff = (_date.today() - _td(days=days)).isoformat()
    pos = neg = neu = 0
    for n in news:
        if n.get("_date_sort", "") < cutoff:
            continue
        s = n.get("_sentiment") or ""
        if s == "positive":
            pos += 1
        elif s == "negative":
            neg += 1
        elif s == "neutral":
            neu += 1
    total = pos + neg + neu
    if total == 0:
        return {}
    return {
        "positive": pos,
        "negative": neg,
        "neutral":  neu,
        "total":    total,
        "pos_pct":  round(pos / total * 100, 1),
        "neg_pct":  round(neg / total * 100, 1),
        "net_pct":  round((pos - neg) / total * 100, 1),
    }


def sentiment_timeline(
    ticker: str,
    news: list[dict],
    days: int = 30,
) -> list[dict]:
    """Return daily sentiment counts for one ticker (sorted by date)."""
    cutoff = (_date.today() - _td(days=days)).isoformat()
    ticker = ticker.upper()

    relevant = [
        n for n in news
        if n.get("ticker", "").upper() == ticker
        and n.get("_date_sort", "") >= cutoff
        and n.get("_sentiment")
    ]

    by_date: dict[str, dict[str, int]] = {}
    for n in relevant:
        d = (n.get("_date_sort") or "")[:10]
        if not d:
            continue
        if d not in by_date:
            by_date[d] = {"positive": 0, "negative": 0, "neutral": 0}
        s = n["_sentiment"]
        if s in by_date[d]:
            by_date[d][s] += 1

    return [{"date": d, **c} for d, c in sorted(by_date.items())]
