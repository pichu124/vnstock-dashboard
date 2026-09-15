"""Cầu dao TÀI KHOẢN cho ladder LLM + tỉa dự phòng OpenRouter (việc #13, 14/09).

Ledger 14/09: 66 call · 29 lỗi. Bốn bậc chết về CẤU TRÚC: Cerebras `402
Payment Required` ×4 (brief ×2 + digest ×2 — hỏng tài khoản, đổi slug không
cứu), OpenRouter đi hết danh mục :free sau MỘT lần nemotron-super hụt (8 model
cụt `finish_reason=length`, 2×429, 1 timeout 90s, 1 KeyError — 0 bản dùng
được), Groq qwen 413 (đã có _BRIEF_AGENT_DISABLES), Mistral 429. Bước brief
754s. Hai lưới ở đây:

1. `provider_blocked_today`: 401/402/403 hôm nay + chưa call nào OK ⇒ mọi điểm
   gọi (brief agent, sentiment/analyze, digest) BỎ nấc đó trong ngày. 429/5xx
   KHÔNG chặn — chặn Gemini cả ngày vì một cơn 429 sáng là tự bỏ agent chính.
2. OpenRouter: dự phòng CHỌN TAY (`_MODEL_FALLBACKS`), tối đa 3 ứng viên, danh
   mục chỉ để BỎ slug đã biến mất; 429 = quota theo KEY ⇒ dừng, không gõ tiếp.
"""
from __future__ import annotations

import json

import pytest

import vnstock_llm_ledger as ll


class _Resp:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._body


@pytest.fixture()
def ledger_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "_META", tmp_path)
    monkeypatch.delenv(ll._BREAKER_ENV, raising=False)
    return tmp_path


# ── 1. provider_blocked_today ─────────────────────────────────────────────
def test_402_with_no_ok_today_blocks_the_provider(ledger_tmp):
    ll.record("Cerebras", "gpt-oss-120b", ok=False,
              error="HTTPError: 402 Client Error: Payment Required for url: x")
    ll.record("Cerebras", "gemma-4-31b", ok=False,
              error="HTTPError: 402 Client Error: Payment Required for url: x")
    why = ll.provider_blocked_today("Cerebras")
    assert why and "402" in why


def test_one_ok_call_today_unblocks(ledger_tmp):
    ll.record("Cerebras", "gpt-oss-120b", ok=False, error="402 Payment Required")
    ll.record("Cerebras", "gemma-4-31b", ok=True, usage={"prompt_tokens": 1})
    assert ll.provider_blocked_today("Cerebras") is None


def test_rate_limit_and_server_errors_never_block(ledger_tmp):
    """429/5xx/timeout là chuyện phút — Gemini dính 429 buổi sáng vẫn phải
    được gọi buổi chiều (agent chính)."""
    ll.record("Gemini", "gemini-3.5-flash", ok=False, error="429 Too Many Requests")
    ll.record("Gemini", "gemini-3.5-flash", ok=False, error="503 Service Unavailable")
    ll.record("OpenRouter", "x:free", ok=False, error="Read timed out. (read timeout=90)")
    assert ll.provider_blocked_today("Gemini") is None
    assert ll.provider_blocked_today("OpenRouter") is None


def test_unknown_provider_or_missing_ledger_is_not_blocked(ledger_tmp):
    assert ll.provider_blocked_today("Mistral") is None      # chưa có sổ
    ll.record("Groq", "openai/gpt-oss-20b", ok=True)
    assert ll.provider_blocked_today("Mistral") is None      # không có dòng


def test_kill_switch_disables_the_breaker(ledger_tmp, monkeypatch):
    ll.record("Cerebras", "gpt-oss-120b", ok=False, error="402 Payment Required")
    monkeypatch.setenv(ll._BREAKER_ENV, "0")
    assert ll.provider_blocked_today("Cerebras") is None


def test_401_and_403_count_as_account_dead(ledger_tmp):
    ll.record("Mistral", "mistral-small-latest", ok=False, error="401 Unauthorized")
    ll.record("Groq", "qwen/qwen3.6-27b", ok=False, error="403 Client Error: Forbidden")
    assert ll.provider_blocked_today("Mistral")
    assert ll.provider_blocked_today("Groq")


# ── 2. Điểm gọi tôn trọng cầu dao ────────────────────────────────────────
@pytest.fixture()
def no_http(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("KHÔNG được gọi HTTP khi tài khoản hỏng theo sổ")
    monkeypatch.setattr("requests.post", _boom)
    monkeypatch.setattr("requests.get", _boom)


@pytest.mark.parametrize("cls_name,env", [
    ("CerebrasAgent", "CEREBRAS_API_KEY"),
    ("MistralAgent", "MISTRAL_API_KEY"),
    ("OpenRouterAgent", "OPENROUTER_API_KEY"),
    ("GeminiAgent", "GEMINI_API_KEY"),
])
def test_brief_agents_skip_without_calling_when_account_dead(
        cls_name, env, monkeypatch, no_http):
    import vnstock_brief as vb
    monkeypatch.setenv(env, "k")
    monkeypatch.setattr(vb, "_account_dead_today",
                        lambda label: "402 Client Error: Payment Required")
    text, err = getattr(vb, cls_name)().generate("prompt", max_tokens=50)
    assert text == "" and "bỏ qua hôm nay" in err and "VNSTOCK_LLM_BREAKER=0" in err


def test_sentiment_ladder_skips_dead_provider(monkeypatch, no_http):
    import vnstock_sentiment as snt
    for p in snt._PROVIDERS:
        monkeypatch.setenv(p["env"], "k")
    monkeypatch.setattr(snt, "_provider_dead_today", lambda name: "402")
    monkeypatch.setattr(snt, "_alert_down", lambda *a, **k: None, raising=False)
    assert snt.chat_complete_ex("s", "u") is None            # cạn thang, 0 HTTP
    assert snt._call_provider(snt._PROVIDERS[0], "text") is None


def test_digest_free_call_skips_dead_provider(monkeypatch, no_http):
    import vnstock_report_digest as dg
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    monkeypatch.setattr(dg, "_provider_dead_today", lambda name: "402 Payment Required")
    warned = []
    monkeypatch.setattr(dg, "_warn_rung", lambda name, e, resp=None: warned.append(str(e)))
    assert dg._call_free("Cerebras", "gpt-oss-120b", "s", "u") is None
    assert warned and "tài khoản hỏng" in warned[0]


# ── 3. OpenRouter: dự phòng chọn tay, cap 3, 429 dừng ─────────────────────
def _openrouter(monkeypatch, catalog):
    import vnstock_brief as vb
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    monkeypatch.setattr(vb.OpenRouterAgent, "_fetch_free_models",
                        classmethod(lambda cls, key: list(catalog)))
    return vb


def test_openrouter_candidates_are_curated_not_the_whole_catalog(monkeypatch):
    vb = _openrouter(monkeypatch, [
        "cohere/north-mini-code:free", "dots-studio/dots-3-note-preview:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free", "inclusionai/ling-3.0-flash-fin:free",
        "liquid/lfm-2.5-2.6b:free", "nex-agi/nex-n2.5-mini:free",
        "google/gemma-4-26b-a4b-it:free", "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "x:free", "y:free", "z:free",
    ])
    cands = vb.OpenRouterAgent()._candidates("k")
    assert cands == ["nvidia/nemotron-3-super-120b-a12b:free",
                     "nvidia/nemotron-3-ultra-550b-a55b:free"]
    assert len(cands) <= vb.OpenRouterAgent._MAX_CANDIDATES


def test_openrouter_drops_fallback_that_left_the_catalog(monkeypatch):
    vb = _openrouter(monkeypatch, ["a:free", "b:free"])
    assert vb.OpenRouterAgent()._candidates("k") == ["nvidia/nemotron-3-super-120b-a12b:free"]


def test_openrouter_keeps_curated_fallbacks_when_catalog_unreachable(monkeypatch):
    vb = _openrouter(monkeypatch, [])
    assert vb.OpenRouterAgent()._candidates("k") == [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free"]


def test_openrouter_stops_at_first_429(monkeypatch):
    """429 ở OpenRouter là quota theo KEY — gõ model kế cũng 429 và còn ăn
    thêm request của chính quota đó."""
    vb = _openrouter(monkeypatch, [])
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(429))[1])
    text, err = vb.OpenRouterAgent().generate("p", max_tokens=50)
    assert text == "" and calls == ["nvidia/nemotron-3-super-120b-a12b:free"]


def test_openrouter_still_falls_through_on_404(monkeypatch):
    vb = _openrouter(monkeypatch, [])
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(404))[1])
    vb.OpenRouterAgent().generate("p", max_tokens=50)
    assert calls == ["nvidia/nemotron-3-super-120b-a12b:free",
                     "nvidia/nemotron-3-ultra-550b-a55b:free"]


def test_cerebras_402_stops_after_one_call(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(402))[1])
    text, err = vb.CerebrasAgent().generate("p", max_tokens=50)
    assert text == "" and calls == ["gpt-oss-120b"]
