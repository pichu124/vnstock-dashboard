#!/usr/bin/env python3
"""vnstock_report_digest.py — Digest báo cáo vĩ mô bằng LLM + cross-check + tilt (Phase 3).

Vị trí trong thiết kế (user duyệt 2026-07-13)
---------------------------------------------
P2 (`vnstock_reports`) đã có thư viện báo cáo (text + metadata). Phase 3 biến
mỗi báo cáo đủ điều kiện thành **digest có cấu trúc** rồi tổng hợp thành
**consensus → tilt ±1 band** cho `vnstock_allocation`:

* **Digest** (1 call LLM/báo cáo): JSON {tom_tat, stance 5 lớp tài sản
  (-2..+2, 0 = TRUNG_LẬP được phép), claims số + kỳ, risks}. Nguồn tiếng Anh
  → digest DỊCH sang tiếng Việt (brief có luật thuần-tiếng-Việt).
* **Provider**: key trả phí trước — Claude (ANTHROPIC_API_KEY) → GPT
  (OPENAI_API_KEY); ladder free 70B (Groq→Cerebras→OpenRouter qua
  `vnstock_sentiment.chat_complete`) CHỈ làm fallback (TODO 1b: 70B free yếu).
  Chi phí nhỏ: 1-2 báo cáo/tháng × ~2K token.
* **Sanitize cấu trúc**: mọi text từ LLM bị strip `#`/emoji/CJK + ép 1 dòng —
  digest sẽ được splice vào brief (P4) nên KHÔNG được chứa token mà
  section-parser của guard chain hiểu nhầm là ranh giới mục.
* **Cross-check số — REGISTRY THẮNG** (mirror `_fx_crosscheck`): claim mang
  key thuộc registry 13 chỉ số được so với giá trị registry hiện hành; lệch
  quá dung sai → cờ ``mismatch`` trên claim + ``has_mismatch`` trên digest.
  Claim mismatch KHÔNG được vào brief (P4 lọc); stance vẫn dùng cho consensus
  (quan điểm ≠ số đo — số sai thì số bị chặn, quan điểm giữ nhưng có cờ).
  Số từ báo cáo KHÔNG BAO GIỜ ghi vào registry (nguyên tắc #2).
* **Consensus + tilt**: stance "Cổ phiếu" trung bình có trọng số decay tuổi
  (≤30 ngày = 1.0, tuyến tính về 0 ở 90 ngày — đúng tham số duyệt) trên các
  digest hợp lệ. |consensus| ≥ ``_TILT_THRESHOLD`` (1.0) → tilt ∓1 band.
  Allocation áp tilt SAU band data (P1) — chỉ ±1, KHÔNG override data sống.

Cache: digest nằm NGAY TRONG record của ``reports_index.json``
(``rec["digest"]``) — một nguồn sự thật, xoá báo cáo là digest đi theo.

CLI::

    python vnstock_report_digest.py --refresh          # digest báo cáo chưa có
    python vnstock_report_digest.py --refresh --redigest   # chấm lại TẤT CẢ
    python vnstock_report_digest.py --show <id>
    python vnstock_report_digest.py --consensus        # stance tổng hợp + tilt
    python vnstock_report_digest.py --diag             # thử 1 call LLM (cần key)

Tắt tilt phía allocation: env ``VNSTOCK_ALLOCATION_TILT=0``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

import vnstock_reports as _rp

# Stance khai báo trên đúng 5 lớp tài sản của bảng phân bổ.
_ASSET_CLASSES = ("Cổ phiếu", "Trái phiếu", "Tiền gửi", "Vàng", "USD")

# Decay tuổi (tham số user duyệt): trọng số 1.0 tới 30 ngày, tuyến tính về 0
# ở 90 ngày (load_for_analysis đã loại > 90).
_DECAY_FULL_DAYS = 30
_DECAY_ZERO_DAYS = 90

# |consensus stance Cổ phiếu| phải ≥ ngưỡng này mới tilt (thang -2..+2 —
# 1.0 = các báo cáo nghiêng RÕ một chiều, không phải nhiễu quanh trung lập).
_TILT_THRESHOLD = 1.0

_PROMPT_MAX_CHARS = 12_000     # phần thân báo cáo đưa vào prompt
_DIGEST_MAX_TOKENS = 700

# Model mặc định — mirror brief agents (ClaudeAgent/OpenAIAgent).
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = "gpt-4o-mini"

# Cascade free THEO BẬC SỨC MẠNH (khi không có key Claude/GPT): mọi model
# BẬC 1 (mạnh nhất free, mọi provider) thử trước; lỗi hết mới rơi xuống BẬC 2
# (70B ổn định — đường cũ). Khác chat_complete (provider-major: thử cả yếu
# của Groq trước mạnh của Cerebras) — verify 14/07 cho thấy 70B đọc sai
# stance báo cáo thật (CP +0 thay vì -2, USD ngược chiều, bịa claim value 0)
# nên thứ tự phải ưu tiên CHẤT LƯỢNG, không phải provider. Id bậc 1 là ỨNG
# VIÊN theo catalog 2025-2026 — id sai/bị gỡ chỉ tốn 1 lần thử lỗi rồi
# cascade đi tiếp, không gãy. Ghi đè model bậc 1 không cần sửa code:
# env VNSTOCK_DIGEST_MODELS = "Groq=<model>;OpenRouter=<model>;Cerebras=<model>".
# (Đã dò bằng lỗi THẬT trên máy user 14/07 — địa hình free tier 2026:
#  * Groq BỎ khỏi bậc 1: TPM 8000/phút không gánh nổi prompt cỡ báo cáo +
#    budget reasoning (413 VỀ CẤU TRÚC), và cả 2 slug mạnh thử đều
#    model_not_found (kimi-k2, llama-4-maverick) — Groq chỉ còn ở bậc 2
#    (70B, budget nhỏ). Groq nới TPM/thêm model thì thêm lại qua env.
#  * Cerebras gpt-oss-120b: SỐNG và cho digest ĐẠT (verify 14/07: stance
#    CP -2 đúng đáp án) — reasoning model, PHẢI cấp 6000 token (3000 cụt).
#  * OpenRouter: deepseek-v3 lẫn kimi-k2 đều hết ':free' — qwen3-235b là
#    ứng viên chưa qua thử lửa.)
_FREE_MODELS = {
    "Cerebras": "gpt-oss-120b",
    "OpenRouter": "qwen/qwen3-235b-a22b:free",
}
# Budget token RA theo provider ở bậc 1 — reasoning cần chỗ suy nghĩ.
_TIER1_TOKENS = {"Groq": 900, "Cerebras": 6000, "OpenRouter": 3000}
_FREE_TIER2 = (                      # 70B — fallback ổn định đã chạy ổn từ P3
    ("Groq", "llama-3.3-70b-versatile"),
    ("Cerebras", "llama3.3-70b"),
    ("OpenRouter", "meta-llama/llama-3.3-70b-instruct:free"),
)
_TIER2_TOKENS = 1200                 # 70B không reasoning — 700-900 là đủ, dư chút
_PROVIDER_META = {                   # env + endpoint — mirror vnstock_sentiment._PROVIDERS
    "Groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions"),
    "Cerebras": ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions"),
    "OpenRouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions"),
}


def _free_models() -> dict:
    """Model BẬC 1 mỗi provider (+ ghi đè/THÊM từ env VNSTOCK_DIGEST_MODELS —
    thử model mới chỉ cần đổi env, không sửa code — TODO 1b hướng 2). Env
    thêm được cả provider không có sẵn ở bậc 1 (vd Groq quay lại khi nới TPM),
    miễn là provider có trong _PROVIDER_META."""
    out = dict(_FREE_MODELS)
    raw = (os.environ.get("VNSTOCK_DIGEST_MODELS") or "").strip()
    for part in raw.split(";"):
        name, sep, model = part.partition("=")
        if sep and name.strip() in _PROVIDER_META and model.strip():
            out[name.strip()] = model.strip()
    return out


def _free_ladder() -> list[tuple[str, str, int]]:
    """Cascade (provider, model, max_tokens) theo bậc: TOÀN BỘ bậc 1 trước,
    rồi bậc 2; bỏ model bậc 2 trùng bậc 1 (env override trỏ về 70B thì khỏi
    thử 2 lần). Budget ra đi kèm TỪNG NẤC (reasoning ≠ non-reasoning ≠ TPM)."""
    tier1 = [(p, m, _TIER1_TOKENS.get(p, _FREE_MAX_TOKENS))
             for p, m in _free_models().items()]
    seen = {(p, m) for p, m, _ in tier1}
    return tier1 + [(p, m, _TIER2_TOKENS)
                    for p, m in _FREE_TIER2 if (p, m) not in seen]

# Dung sai cross-check theo key registry (kỳ báo cáo có thể lệch kỳ registry
# nên dung sai RỘNG có chủ đích — chỉ chặn số SAI HẲN, không bắt nạt lệch kỳ).
#   ("rel", x) — lệch tương đối x%   ·   ("abs", x) — lệch tuyệt đối x đơn vị
_CLAIM_TOLERANCE: dict[str, tuple[str, float]] = {
    "usdvnd":              ("rel", 2.0),
    "sbv_policy_rate":     ("abs", 0.5),
    "interbank_on":        ("abs", 1.0),   # LNH dao động mạnh theo tuần
    "interbank_1w":        ("abs", 1.0),
    "govt_bond_yield_2y":  ("abs", 0.5),
    "govt_bond_yield_10y": ("abs", 0.5),
    "us10y":               ("abs", 0.5),
    "fed_funds":           ("abs", 0.5),
    "cpi_yoy":             ("abs", 1.0),
    "iip_yoy":             ("abs", 3.0),   # IIP tháng biến động lớn
    "pmi":                 ("abs", 2.0),
    "gdp_yoy":             ("abs", 1.5),
    "trade_balance":       ("abs", 2.0),   # tỷ USD, kỳ tháng ≠ lũy kế
}


def _registry_keys() -> list[str]:
    try:
        from vnstock_macro import _DEFS
        return list(_DEFS)
    except Exception:
        return list(_CLAIM_TOLERANCE)


# ── Sanitize (digest sẽ vào brief — không được phá section parser) ──────────

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")          # mirror enforce_no_cjk
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def sanitize_text(s: str) -> str:
    """1 dòng sạch: bỏ #/emoji/CJK/xuống dòng — an toàn để splice vào brief."""
    s = str(s or "")
    s = _CJK_RE.sub("", s)
    s = _EMOJI_RE.sub("", s)
    s = s.replace("#", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── LLM call (Claude → GPT → ladder free) ───────────────────────────────────

_DIGEST_SYSTEM = (
    "Bạn tóm tắt BÁO CÁO VĨ MÔ cho nhà đầu tư Việt Nam. Trả về DUY NHẤT một "
    "JSON object (không markdown, không giải thích) đúng schema:\n"
    '{"tom_tat": "<2-3 câu tiếng Việt tóm quan điểm vĩ mô chính>",\n'
    ' "stance": {"Cổ phiếu": <-2..2>, "Trái phiếu": <-2..2>, "Tiền gửi": <-2..2>,'
    ' "Vàng": <-2..2>, "USD": <-2..2>},\n'
    ' "claims": [{"key": "<key>", "value": <số>, "unit": "<đơn vị>",'
    ' "period": "<kỳ, vd 2026-06 / Q2/2026>", "text": "<trích ngắn>"}],\n'
    ' "risks": ["<rủi ro 1>", "<rủi ro 2>"]}\n'
    "Quy tắc: stance = quan điểm CỦA BÁO CÁO về từng lớp tài sản 3-6 tháng tới "
    "(-2 rất tiêu cực, 0 = trung lập/không nêu — ĐƯỢC PHÉP, +2 rất tích cực). "
    "ĐỌC KỸ mục kết luận/khuyến nghị: báo cáo viết 'không khuyến nghị mua'/"
    "'không recommend'/'tránh' một lớp tài sản → stance lớp đó PHẢI ÂM (-1 "
    "hoặc -2), KHÔNG được ghi 0; 'nắm giữ, không mua thêm' → 0/+1; 'giảm "
    "dần/chốt dần vị thế' → ÂM. 0 CHỈ dành cho lớp báo cáo KHÔNG nêu gì. "
    "claims CHỈ gồm số liệu vĩ mô báo cáo nêu RÕ RÀNG, key lấy từ danh sách: "
    "{keys} — không khớp key nào thì dùng \"khac\". MỖI claim bắt buộc có CON "
    "SỐ THẬT trích từ báo cáo trong \"text\"; câu định tính không có số "
    "(vd 'tỷ giá có thể giảm thêm') → KHÔNG tạo claim. Báo cáo tiếng Anh vẫn "
    "trả lời HOÀN TOÀN tiếng Việt. Số dùng định dạng EN (chấm thập phân). "
    "KHÔNG bịa số không có trong báo cáo."
)


def _ledger(provider: str, model: str, ok: bool,
            usage: "dict | None" = None, error: "str | None" = None) -> None:
    """Ghi sổ call LLM (món 3 deep-dive DojoAgents) — best-effort tuyệt đối."""
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


def _warn_rung(name: str, e: Exception, resp=None) -> None:
    """Có key mà call FAIL là degradation đáng nói (digest rơi xuống 70B free
    — TODO 1b đã ghi 70B yếu) — không được nuốt im lặng. In 1 dòng chẩn đoán
    (kèm body lỗi API nếu có) rồi ladder vẫn thử nấc sau như cũ."""
    detail = ""
    try:
        detail = " | " + str(resp.json())[:200]
    except Exception:
        pass
    print(f"[digest] ⚠ {name} có key nhưng call lỗi "
          f"({type(e).__name__}: {str(e)[:120]}{detail}) — thử nấc sau")


def _call_claude(system: str, user: str,
                 max_tokens: int = _DIGEST_MAX_TOKENS) -> "str | None":
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    resp = None
    try:
        import requests as _req
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"},
            json={"model": _CLAUDE_MODEL, "max_tokens": max_tokens,
                  "temperature": 0, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=90)
        resp.raise_for_status()
        _ledger("Anthropic", _CLAUDE_MODEL, True, resp.json().get("usage"))
        return resp.json()["content"][0]["text"]
    except Exception as e:
        _ledger("Anthropic", _CLAUDE_MODEL, False, error=str(e))
        _warn_rung(f"Claude ({_CLAUDE_MODEL})", e, resp)
        return None


def _call_openai(system: str, user: str,
                 max_tokens: int = _DIGEST_MAX_TOKENS) -> "str | None":
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    resp = None
    try:
        import requests as _req
        resp = _req.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            json={"model": _OPENAI_MODEL, "max_tokens": max_tokens,
                  "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=90)
        resp.raise_for_status()
        _ledger("OpenAI", _OPENAI_MODEL, True, resp.json().get("usage"))
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        _ledger("OpenAI", _OPENAI_MODEL, False, error=str(e))
        _warn_rung(f"GPT ({_OPENAI_MODEL})", e, resp)
        return None


def _ensure_env_loaded() -> None:
    """Load .env TRƯỚC khi check key — bẫy đã ghi trong CLAUDE.md (brief có
    _ensure_env_loaded, doctor có load_dotenv; module này quên → chạy từ CLI
    fresh báo 'không key nào chạy' dù .env có đủ key — dính thật khi user
    verify 14/07). Best-effort, idempotent (override=False)."""
    try:
        from pathlib import Path

        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    except Exception:
        pass


# Budget token cho nấc FREE: các model bậc 1 là REASONING model (gpt-oss…)
# tiêu token vào phần suy nghĩ TRƯỚC khi trả content — 700 token bị
# finish_reason=length khi content còn rỗng (lỗi thật Cerebras 14/07). Free
# nên nới rộng không tốn gì; Claude/GPT trả phí giữ _DIGEST_MAX_TOKENS.
_FREE_MAX_TOKENS = 3000


def _call_free(provider: str, model: str, system: str, user: str,
               max_tokens: int = _FREE_MAX_TOKENS) -> "str | None":
    """1 call OpenAI-compat tới đúng (provider, model) — None khi thiếu key
    hoặc call lỗi (có key mà lỗi thì cảnh báo, cascade đi tiếp)."""
    env, endpoint = _PROVIDER_META[provider]
    key = (os.environ.get(env) or "").strip()
    if not key:
        return None
    resp = None
    try:
        import requests as _req
        resp = _req.post(
            endpoint,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": max_tokens, "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=90)
        resp.raise_for_status()
        payload = resp.json()
        body = payload["choices"][0]
        content = (body.get("message") or {}).get("content")
        if not content:
            # reasoning model cạn budget giữa chừng suy nghĩ → coi là fail
            # có chẩn đoán, cascade thử nấc sau
            raise RuntimeError(
                f"content rỗng (finish_reason={body.get('finish_reason')}) — "
                f"model reasoning cạn max_tokens?")
        _ledger(provider, model, True, payload.get("usage"))
        return content
    except Exception as e:
        _ledger(provider, model, False, error=str(e))
        _warn_rung(f"{provider} ({model})", e, resp)
        return None


def digest_call(system: str, user: str, accept=None,
                feedback=None) -> tuple["str | None", str]:
    """(raw_text, provider) qua cascade GIẢM DẦN SỨC MẠNH: Claude → GPT →
    mọi model free bậc 1 → mọi model free bậc 2 (70B). Provider trả về ghi
    rõ model free nào đã digest ("Groq:kimi-k2…") để soi chất lượng về sau.

    ``accept(raw) -> bool``: model TRẢ LỜI nhưng output không đạt (vd JSON
    hỏng vì bị cắt — lỗi thật Cerebras 14/07) cũng là MỘT LOẠI LỖI MODEL →
    cascade thử nấc sau thay vì bỏ cuộc. None = nhận mọi output (--diag).

    ``feedback(raw) -> str`` (món 1 deep-dive DojoAgents 15/07 — mirror
    harness recovery): output KHÔNG ĐẠT → cho ĐÚNG NẤC ĐÓ 1 lượt tự sửa
    kèm mô tả lỗi cụ thể + output hỏng, TRƯỚC khi rơi xuống nấc sau. Chỉ
    retry 1 LẦN cho cả cascade (trần +1 call); provider trả về gắn đuôi
    "(retry)". Mọi output đều qua strip_think_tags trước khi chấm (model
    reasoning free suy nghĩ trong <think>…</think> chứa cả JSON nháp —
    không strip thì parse vớ nhầm khối nháp).

    (None, '') khi không nấc nào vừa chạy được vừa đạt."""
    _ensure_env_loaded()
    from vnstock_sentiment import strip_think_tags

    def _ok(raw: str, provider: str) -> bool:
        if accept is None or accept(raw):
            return True
        print(f"[digest] ⚠ {provider}: trả lời nhưng output không đạt "
              f"(JSON hỏng/bị cắt?) — thử nấc sau")
        return False

    rungs: list[tuple[str, "object"]] = [
        ("claude", lambda u: _call_claude(system, u)),
        ("openai", lambda u: _call_openai(system, u)),
    ]
    for provider, model, tokens in _free_ladder():
        rungs.append((f"{provider}:{model}",
                      lambda u, p=provider, m=model, t=tokens:
                      _call_free(p, m, system, u, max_tokens=t)))

    retried = False
    for name, call in rungs:
        raw = call(user)
        if not raw:
            continue
        raw = strip_think_tags(raw)
        if _ok(raw, name):
            return raw, name
        if feedback is not None and not retried:
            retried = True            # 1 lượt tự sửa cho CẢ cascade
            try:
                err = str(feedback(raw) or "output không đạt")
            except Exception:
                err = "output không đạt"
            retry_user = (
                f"{user}\n\n⚠️ OUTPUT TRƯỚC CỦA BẠN KHÔNG ĐẠT — lỗi: {err}\n"
                f"Output hỏng (phần đầu):\n{raw[:800]}\n"
                f"Hãy SỬA ĐÚNG lỗi trên và trả về DUY NHẤT một khối JSON "
                f"hợp lệ, không thêm bất kỳ chữ nào ngoài JSON.")
            print(f"[digest] 🔁 {name}: cho 1 lượt tự sửa (lỗi: {err[:100]})")
            raw2 = call(retry_user)
            if raw2:
                raw2 = strip_think_tags(raw2)
                if _ok(raw2, f"{name}(retry)"):
                    return raw2, f"{name}(retry)"
    return None, ""


def describe_digest_error(raw: str) -> str:
    """Mô tả CỤ THỂ vì sao output digest không đạt — bơm ngược cho model tự
    sửa trong lượt retry (lời phê càng trúng, model free càng dễ sửa)."""
    if not raw:
        return "output rỗng"
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return "không tìm thấy khối JSON {...} nào trong output"
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        return (f"JSON không parse được ({e.msg} tại vị trí {e.pos}) — "
                f"thường do bị cắt giữa chừng, thiếu ngoặc hoặc phẩy thừa")
    if not isinstance(data, dict):
        return "JSON parse được nhưng không phải object {...} ở tầng ngoài"
    return "JSON parse được nhưng thiếu nội dung theo schema (tom_tat/stance/claims)"


# ── Parse + validate digest JSON ─────────────────────────────────────────────


def parse_digest(raw: str) -> "dict | None":
    """JSON từ output LLM → digest đã validate/sanitize; None khi vô phương.

    Chấp nhận JSON lẫn trong văn bản/code fence (lấy từ ``{`` đầu tới ``}``
    cuối). stance ép int và clamp -2..+2, lớp thiếu → 0 (trung lập); claims
    giữ dòng có ``value`` số; mọi text qua ``sanitize_text``.
    """
    if not raw:
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    stance_in = data.get("stance") or {}
    stance = {}
    for cls in _ASSET_CLASSES:
        try:
            stance[cls] = max(-2, min(2, int(round(float(stance_in.get(cls, 0))))))
        except (TypeError, ValueError):
            stance[cls] = 0

    claims = []
    for c in (data.get("claims") or []):
        if not isinstance(c, dict):
            continue
        try:
            value = float(c.get("value"))
        except (TypeError, ValueError):
            continue
        text = sanitize_text(c.get("text") or "")[:160]
        # Luật deterministic chống bịa số (thấy 3 lần liên tiếp 14/07: câu
        # "USDVND có thể giảm thêm" không có số → model chế value=0): claim
        # là TRÍCH DẪN SỐ LIỆU — trích dẫn không chứa chữ số nào thì không
        # có số để claim → loại thẳng, khỏi chờ cross-check.
        if not any(ch.isdigit() for ch in text):
            continue
        claims.append({
            "key":    sanitize_text(c.get("key") or "khac").lower() or "khac",
            "value":  value,
            "unit":   sanitize_text(c.get("unit") or ""),
            "period": sanitize_text(c.get("period") or ""),
            "text":   text,
        })

    risks = [sanitize_text(r)[:160] for r in (data.get("risks") or [])
             if sanitize_text(r)]
    return {
        "tom_tat": sanitize_text(data.get("tom_tat") or "")[:400],
        "stance":  stance,
        "claims":  claims,
        "risks":   risks[:5],
    }


# ── Cross-check với registry (REGISTRY THẮNG) ───────────────────────────────


def cross_check_claims(claims: list[dict],
                       macro: "list[dict] | None") -> bool:
    """Đối chiếu claim số với registry — mutate cờ ``mismatch`` từng claim,
    trả True khi có ít nhất 1 mismatch.

    Registry là SỐ ĐO, báo cáo là QUAN ĐIỂM: lệch quá dung sai → claim bị cờ
    (P4 không đưa vào brief), registry KHÔNG bao giờ bị sửa theo báo cáo.
    Claim key "khac"/không có trong registry → bỏ qua (không có gì để đối
    chiếu). Registry trống → không check được, không cờ ai.
    """
    rows = {m.get("key"): m for m in (macro or [])}
    any_mismatch = False
    for c in claims:
        key = c.get("key")
        row = rows.get(key)
        tol = _CLAIM_TOLERANCE.get(key)
        if not row or not tol or row.get("value") is None:
            continue
        reg, val = float(row["value"]), float(c["value"])
        mode, lim = tol
        diff_ok = (abs(val - reg) / max(abs(reg), 1e-9) * 100 <= lim) \
            if mode == "rel" else (abs(val - reg) <= lim)
        if not diff_ok:
            c["mismatch"] = True
            c["registry_value"] = reg
            c["registry_as_of"] = row.get("as_of")
            any_mismatch = True
    return any_mismatch


# ── Digest 1 báo cáo + refresh cả thư viện ──────────────────────────────────


def digest_report(rec: dict, text: "str | None" = None) -> "dict | None":
    """Digest 1 báo cáo (1 call LLM) + cross-check. Trả digest dict hoặc None
    (không provider / parse fail) — KHÔNG tự ghi index (caller ghi)."""
    text = text if text is not None else _rp.load_report_text(rec["id"])
    if not text.strip():
        return None
    system = _DIGEST_SYSTEM.replace("{keys}", ", ".join(_registry_keys()))
    user = (f"Nguồn: {rec.get('source', '?')} — ngày báo cáo "
            f"{rec.get('report_date', '?')} — {rec.get('title') or ''}\n\n"
            f"{text[:_PROMPT_MAX_CHARS]}")
    # accept = parse được JSON: model trả rác/JSON cụt → trước tiên cho nấc
    # đó 1 lượt TỰ SỬA kèm lời phê cụ thể (feedback — deep-dive DojoAgents
    # 15/07), vẫn hỏng → cascade nấc sau (14/07: Cerebras trả content nhưng
    # JSON hỏng làm digest bỏ cuộc dù OpenRouter còn chưa được thử).
    raw, provider = digest_call(system, user,
                                accept=lambda r: parse_digest(r) is not None,
                                feedback=describe_digest_error)
    if not raw:
        print(f"[digest] ❌ {rec['id']}: không nấc nào vừa trả lời vừa ra JSON "
              f"hợp lệ (cần ANTHROPIC/OPENAI key, hoặc GROQ/CEREBRAS/OPENROUTER)")
        return None
    digest = parse_digest(raw)
    if digest is None:                     # không thể xảy ra sau accept — phòng hờ
        print(f"[digest] ❌ {rec['id']}: output không parse được JSON")
        return None
    try:
        from vnstock_macro import load_macro
        macro = load_macro()
    except Exception:
        macro = []
    digest["has_mismatch"] = cross_check_claims(digest["claims"], macro)
    digest["provider"] = provider
    digest["digested_at"] = datetime.now().isoformat(timespec="seconds")
    if digest["has_mismatch"]:
        bad = [c for c in digest["claims"] if c.get("mismatch")]
        print(f"[digest] ⚠ {rec['id']}: {len(bad)} claim lệch registry "
              f"(REGISTRY THẮNG — claim không vào brief): "
              + "; ".join(f"{c['key']} {c['value']:g} vs {c['registry_value']:g}"
                          for c in bad))
    return digest


def refresh(redigest: bool = False, max_reports: int = 10) -> list[dict]:
    """Digest các báo cáo đủ điều kiện chưa có digest (``redigest=True`` =
    chấm lại tất cả — dùng khi đổi prompt/extractor). Trả list record đã chấm."""
    done: list[dict] = []
    for rec in _rp.load_for_analysis():
        if len(done) >= max_reports:
            print(f"[digest] dừng ở {max_reports} báo cáo/lượt (--max để nới)")
            break
        if rec.get("digest") and not redigest:
            continue
        digest = digest_report(rec)
        if digest is None:
            continue
        _rp.set_digest(rec["id"], digest)
        done.append(rec | {"digest": digest})
        print(f"[digest] ✅ {rec['id']} [{rec.get('source')}] via "
              f"{digest['provider']} — stance CP "
              f"{digest['stance']['Cổ phiếu']:+d}")
    return done


# ── Consensus + tilt ─────────────────────────────────────────────────────────


def _age_weight(age_days: int) -> float:
    if age_days <= _DECAY_FULL_DAYS:
        return 1.0
    if age_days >= _DECAY_ZERO_DAYS:
        return 0.0
    return (_DECAY_ZERO_DAYS - age_days) / (_DECAY_ZERO_DAYS - _DECAY_FULL_DAYS)


def consensus(as_of: "str | None" = None) -> "dict | None":
    """Stance tổng hợp decay-theo-tuổi trên mọi digest hợp lệ + tilt đề xuất.

    Trả ``{stance: {lớp: float}, tilt: -1|0|+1, n_reports, drivers[]}`` —
    tilt từ stance "Cổ phiếu": ≥ +1.0 → -1 (nghiêng tấn công = về band thấp
    hơn), ≤ -1.0 → +1 (phòng thủ). None khi chưa có digest nào còn trọng số.
    v1 giữ ĐƠN GIẢN (1-2 báo cáo/tháng — tham số duyệt #2): trung bình có
    trọng số, không phân biệt uy tín nguồn (xếp hạng nguồn = P6).
    """
    rows = []
    for rec in _rp.load_for_analysis(as_of=as_of):
        d = rec.get("digest")
        if not d or not d.get("stance"):
            continue
        w = _age_weight(rec["age_days"])
        if w <= 0:
            continue
        rows.append((w, rec, d))
    if not rows:
        return None
    wsum = sum(w for w, _, _ in rows)
    stance = {cls: round(sum(w * d["stance"].get(cls, 0)
                             for w, _, d in rows) / wsum, 2)
              for cls in _ASSET_CLASSES}
    cp = stance["Cổ phiếu"]
    tilt = -1 if cp >= _TILT_THRESHOLD else (1 if cp <= -_TILT_THRESHOLD else 0)
    return {
        "stance": stance,
        "tilt": tilt,
        "n_reports": len(rows),
        "as_of": as_of or date.today().isoformat(),
        "drivers": [{"id": rec["id"], "source": rec.get("source"),
                     "report_date": rec.get("report_date"),
                     "age_days": rec["age_days"], "weight": round(w, 2),
                     "stance_cp": d["stance"].get("Cổ phiếu", 0),
                     "has_mismatch": bool(d.get("has_mismatch"))}
                    for w, rec, d in rows],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Digest báo cáo vĩ mô (LLM) + consensus/tilt — Phase 3")
    ap.add_argument("--refresh", action="store_true",
                    help="digest các báo cáo đủ điều kiện chưa có digest")
    ap.add_argument("--redigest", action="store_true",
                    help="cùng --refresh: chấm lại TẤT CẢ (đổi prompt/extractor)")
    ap.add_argument("--max", type=int, default=10,
                    help="tối đa báo cáo digest mỗi lượt (mặc định 10)")
    ap.add_argument("--show", metavar="ID", help="in digest của 1 báo cáo")
    ap.add_argument("--consensus", action="store_true",
                    help="in stance tổng hợp + tilt hiện hành")
    ap.add_argument("--diag", action="store_true",
                    help="thử 1 call LLM ngắn qua ladder (cần key + mạng)")
    args = ap.parse_args(argv)

    if args.refresh or args.redigest:
        done = refresh(redigest=args.redigest, max_reports=args.max)
        print(f"[digest] {len(done)} báo cáo đã digest")
        return 0
    if args.show:
        rec = next((r for r in _rp.list_reports() if r["id"] == args.show), None)
        if rec is None:
            print(f"[digest] ❌ không có id {args.show}")
            return 1
        if not rec.get("digest"):
            print(f"[digest] {args.show} chưa có digest — chạy --refresh")
            return 1
        print(json.dumps(rec["digest"], ensure_ascii=False, indent=2))
        return 0
    if args.consensus:
        c = consensus()
        if c is None:
            print("[digest] chưa có digest nào còn trọng số — ingest báo cáo "
                  "(vnstock_reports) rồi chạy --refresh")
            return 1
        print(f"🧭 Consensus {c['n_reports']} báo cáo (as_of {c['as_of']}):")
        for cls in _ASSET_CLASSES:
            print(f"  {cls:<12} {c['stance'][cls]:+.2f}")
        lab = {0: "không tilt", -1: "tilt -1 (tấn công hơn)",
               1: "tilt +1 (phòng thủ hơn)"}[c["tilt"]]
        print(f"  → {lab} (ngưỡng ±{_TILT_THRESHOLD})")
        for dr in c["drivers"]:
            flag = " ⚠mismatch" if dr["has_mismatch"] else ""
            print(f"    • {dr['report_date']} {dr['source']} "
                  f"(w={dr['weight']}, CP {dr['stance_cp']:+d}){flag}")
        return 0
    if args.diag:
        _ensure_env_loaded()
        for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
                    "CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
            has = bool((os.environ.get(env) or "").strip())
            print(f"  {'✅' if has else '⬜'} {env}")
        raw, provider = digest_call(
            "Trả về đúng JSON: {\"ok\": true}", "ping")
        print(f"LLM ladder: {'OK via ' + provider if raw else 'FAIL — không key nào chạy (cần .env + mạng)'}")
        if raw and any(provider.endswith(m) for _, m in _FREE_TIER2):
            print("  ⚠ đã rơi xuống bậc 70B (mọi model bậc 1 lỗi) — chất lượng "
                  "digest thấp hơn; xem cảnh báo bên trên để biết model bậc 1 "
                  "nào chết, hoặc đổi qua env VNSTOCK_DIGEST_MODELS.")
        return 0 if raw else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
