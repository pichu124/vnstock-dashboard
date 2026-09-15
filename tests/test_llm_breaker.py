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


# ── 3. OpenRouter: dự phòng chọn tay, cap 3, KHÔNG hỏi danh mục, 429 dừng ───
def _openrouter(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    return vb


def test_openrouter_candidates_are_curated_and_never_ask_the_catalog(monkeypatch):
    """Bản 14/09 hỏi /models để bỏ slug 'đã biến mất' — nhưng OpenRouter cắt
    trang ở 400 nên nemotron-ultra (đang sống, digest 2/2 OK) bị coi là biến
    mất ⇒ brief close 15/09 không có nấc dự phòng. Nay: không GET danh mục,
    slug chết thật chỉ tốn một call 404."""
    vb = _openrouter(monkeypatch)
    monkeypatch.setattr("requests.get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("không được hỏi danh mục")))
    cands = vb.OpenRouterAgent()._candidates("k")
    assert cands == ["nvidia/nemotron-3-super-120b-a12b:free",
                     "nvidia/nemotron-3-ultra-550b-a55b:free"]
    assert len(cands) <= vb.OpenRouterAgent._MAX_CANDIDATES
    assert not hasattr(vb.OpenRouterAgent, "_fetch_free_models")


def test_openrouter_stops_at_first_429(monkeypatch):
    """429 ở OpenRouter là quota theo KEY — gõ model kế cũng 429 và còn ăn
    thêm request của chính quota đó."""
    vb = _openrouter(monkeypatch)
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(429))[1])
    text, err = vb.OpenRouterAgent().generate("p", max_tokens=50)
    assert text == "" and calls == ["nvidia/nemotron-3-super-120b-a12b:free"]


def test_openrouter_cut_output_falls_to_ultra(monkeypatch):
    """Đêm 15/09: super cụt 2 lần, ultra sống — phải rơi xuống ultra."""
    vb = _openrouter(monkeypatch)
    calls = []

    def _post(*a, **k):
        m = k["json"]["model"]; calls.append(m)
        if "super" in m:
            return _Resp(200, {"choices": [{"message": {"content": "nửa"},
                                            "finish_reason": "length"}]})
        return _Resp(200, {"choices": [{"message": {"content": "brief đủ"},
                                        "finish_reason": "stop"}], "usage": {}})
    monkeypatch.setattr("requests.post", _post)
    text, err = vb.OpenRouterAgent().generate("p", max_tokens=50)
    assert err is None and "brief đủ" in text and "_(fallback: nvidia/nemotron-3-ultra" in text
    assert calls == ["nvidia/nemotron-3-super-120b-a12b:free",
                     "nvidia/nemotron-3-ultra-550b-a55b:free"]


def test_openrouter_still_falls_through_on_404(monkeypatch):
    vb = _openrouter(monkeypatch)
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


# ── 4. Vòng base (Gemini/Mistral/…): đợi-gọi-lại khi thoáng qua, rồi dự phòng ─
def _base(monkeypatch, env):
    import vnstock_brief as vb
    monkeypatch.setenv(env, "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    monkeypatch.setattr(vb._OpenAICompatAgent, "_TRANSIENT_RETRY_S", 0.0)  # không ngủ trong test
    return vb


def _ok(text="brief"):
    return _Resp(200, {"choices": [{"message": {"content": text},
                                    "finish_reason": "stop"}], "usage": {}})


def test_gemini_503_then_ok_on_retry_same_model(monkeypatch):
    """Brief close 15/09 trắng vì Gemini flash 429/503 ở hai lượt cách nhau vài
    giây và không ai đợi. Nay: đợi _TRANSIENT_RETRY_S rồi gọi lại ĐÚNG flash."""
    vb = _base(monkeypatch, "GEMINI_API_KEY")
    seq = [_Resp(503), _ok("brief flash")]
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), seq.pop(0))[1])
    text, err = vb.GeminiAgent().generate("p", max_tokens=50)
    assert (text, err) == ("brief flash", None)
    assert calls == ["gemini-3.5-flash", "gemini-3.5-flash"]


def test_gemini_flash_down_twice_falls_to_flash_lite(monkeypatch):
    vb = _base(monkeypatch, "GEMINI_API_KEY")
    seq = [_Resp(503), _Resp(429), _ok("brief lite")]
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), seq.pop(0))[1])
    text, err = vb.GeminiAgent().generate("p", max_tokens=50)
    assert err is None and text.endswith("brief lite")
    assert text.startswith("_(fallback: gemini-3.5-flash-lite)_")
    assert calls == ["gemini-3.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_gemini_cut_output_goes_straight_to_fallback_without_retry(monkeypatch):
    """Cụt (finish_reason=length) là cùng prompt cùng trần — gọi lại vô ích,
    sang thẳng flash-lite."""
    vb = _base(monkeypatch, "GEMINI_API_KEY")
    cut = _Resp(200, {"choices": [{"message": {"content": "nửa"}, "finish_reason": "length"}]})
    seq = [cut, _ok("brief lite")]
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), seq.pop(0))[1])
    text, err = vb.GeminiAgent().generate("p", max_tokens=50)
    assert err is None and calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_mistral_quota_429_retries_once_then_gives_up(monkeypatch):
    vb = _base(monkeypatch, "MISTRAL_API_KEY")
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(429))[1])
    text, err = vb.MistralAgent().generate("p", max_tokens=50)
    assert text == "" and "429" in err
    assert calls == ["mistral-small-latest", "mistral-small-latest"]   # không có dự phòng


def test_account_error_stops_immediately_no_retry_no_fallback(monkeypatch):
    vb = _base(monkeypatch, "GEMINI_API_KEY")
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), _Resp(403))[1])
    text, err = vb.GeminiAgent().generate("p", max_tokens=50)
    assert text == "" and "403" in err and calls == ["gemini-3.5-flash"]


def test_404_skips_retry_and_moves_to_fallback(monkeypatch):
    vb = _base(monkeypatch, "GEMINI_API_KEY")
    seq = [_Resp(404), _ok("lite")]
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: (calls.append(k["json"]["model"]), seq.pop(0))[1])
    text, err = vb.GeminiAgent().generate("p", max_tokens=50)
    assert err is None and calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_retry_sleeps_the_configured_backoff(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    monkeypatch.setattr(vb._OpenAICompatAgent, "_TRANSIENT_RETRY_S", 7.5)
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp(503))
    vb.MistralAgent().generate("p", max_tokens=50)
    assert slept == [7.5]


# ── 5. 4c (15/09): usage khi cụt + nới trần OpenRouter ────────────────────
# Ledger 15/09 20:41: nemotron super cụt 3/3, ultra cụt 1/1 cho brief ở 2.800
# token (ultra 2/2 OK cho digest ngắn) — dự phòng OpenRouter chưa gánh nổi
# brief. Sổ lại MÙ vì agent chỉ ghi usage khi OK ⇒ không biết trần bị ăn bởi
# câu trả lời dài hay bởi "suy nghĩ". Hai lưới: (a) ghi usage cả khi cụt, có
# tách reasoning; (b) OpenRouter nới trần như Gemini `_THINK_HEADROOM`.
_CUT_USAGE = {"prompt_tokens": 9_812, "completion_tokens": 2_800,
              "completion_tokens_details": {"reasoning_tokens": 2_650}}


def _cut(usage=_CUT_USAGE):
    return _Resp(200, {"choices": [{"message": {"content": "nửa"},
                                    "finish_reason": "length"}],
                       "usage": dict(usage)})


def test_ledger_keeps_usage_of_last_failed_call_and_reasoning_split(ledger_tmp):
    ll.record("OpenRouter", "nvidia/nemotron-3-super-120b-a12b:free", ok=False,
              usage=_CUT_USAGE, error="finish_reason=length (output cụt)")
    row = ll.summary()["providers"]["OpenRouter:nvidia/nemotron-3-super-120b-a12b:free"]
    assert row["fail"] == 1
    assert row["completion_tokens"] == 2_800 and row["reasoning_tokens"] == 2_650
    assert row["last_fail_usage"] == {"prompt": 9_812, "completion": 2_800,
                                      "reasoning": 2_650}
    lines = "\n".join(ll.summary_lines())
    assert "lần lỗi cuối tốn: vào 9,812 · ra 2,800 · trong đó suy nghĩ 2,650" in lines
    assert "suy nghĩ: 2,650 token (94% token ra)" in lines
    assert ll.summary()["totals"]["reasoning_tokens"] == 2_650


def test_ledger_reasoning_aggregates_over_ok_calls_and_never_trips_breaker(ledger_tmp):
    """Số token trong usage KHÔNG được lọt vào last_error: cầu dao dò
    \\b40[123]\\b — một lần cụt tốn đúng 402 token mà chặn provider cả ngày
    là tự bỏ nấc sống."""
    usage = {"prompt_tokens": 100, "completion_tokens": 402,
             "completion_tokens_details": {"reasoning_tokens": 401}}
    ll.record("Gemini", "gemini-3.5-flash", ok=True, usage=usage)
    ll.record("Gemini", "gemini-3.5-flash", ok=True, usage=usage)
    ll.record("Gemini", "gemini-3.5-flash", ok=False, usage=usage,
              error="finish_reason=length (output cụt)")
    row = ll.summary()["providers"]["Gemini:gemini-3.5-flash"]
    assert row["reasoning_tokens"] == 3 * 401 and row["completion_tokens"] == 3 * 402
    assert row["last_error"] == "finish_reason=length (output cụt)"
    assert ll.provider_blocked_today("Gemini") is None
    # cả khi hôm nay CHƯA có call OK nào — vẫn không phải hỏng tài khoản
    ll.record("Mistral", "mistral-small-latest", ok=False, usage=usage,
              error="finish_reason=length (output cụt)")
    assert ll.provider_blocked_today("Mistral") is None


def test_ledger_ok_call_without_reasoning_prints_no_think_line(ledger_tmp):
    ll.record("Groq", "gpt-oss-20b", ok=True,
              usage={"prompt_tokens": 10, "completion_tokens": 5})
    lines = "\n".join(ll.summary_lines())
    assert "suy nghĩ" not in lines and "lần lỗi cuối" not in lines


@pytest.mark.parametrize("cls,env", [
    ("GeminiAgent", "GEMINI_API_KEY"),        # vòng base
    ("OpenRouterAgent", "OPENROUTER_API_KEY"),
    ("CerebrasAgent", "CEREBRAS_API_KEY"),
])
def test_cut_output_records_usage_in_every_agent_loop(monkeypatch, cls, env):
    import vnstock_brief as vb
    monkeypatch.setenv(env, "k")
    monkeypatch.setattr(vb, "_account_dead_today", lambda label: None)
    monkeypatch.setattr(vb._OpenAICompatAgent, "_TRANSIENT_RETRY_S", 0.0)
    recorded = []
    monkeypatch.setattr(vb, "_ledger_record",
                        lambda provider, model, ok, usage=None, error=None:
                        recorded.append((model, ok, usage, error)))
    monkeypatch.setattr("requests.post", lambda *a, **k: _cut())
    text, err = getattr(vb, cls)().generate("p", max_tokens=50)
    assert text == "" and err
    cuts = [r for r in recorded if r[1] is False and "cụt" in str(r[3])]
    assert cuts, recorded
    for _model, _ok, usage, _error in cuts:
        assert usage == _CUT_USAGE


def test_anthropic_cut_records_usage(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    recorded = []
    monkeypatch.setattr(vb, "_ledger_record",
                        lambda provider, model, ok, usage=None, error=None:
                        recorded.append((provider, ok, usage)))
    body = {"stop_reason": "max_tokens", "content": [{"text": "nửa"}],
            "usage": {"input_tokens": 9_000, "output_tokens": 2_800}}
    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp(200, body))
    text, err = vb.ClaudeAgent().generate("p", max_tokens=50)
    assert text == "" and "cắt" in err
    assert recorded == [("Anthropic", False, body["usage"])]


def test_openrouter_adds_output_headroom_to_every_call(monkeypatch):
    """Trần brief 2.800 vừa khít brief tiếng Việt với tokenizer nemotron —
    nới như Gemini; là trần, :free không tốn."""
    vb = _openrouter(monkeypatch)
    sent = []
    monkeypatch.setattr("requests.post",
                        lambda *a, **k: (sent.append(k["json"]["max_tokens"]), _ok("brief"))[1])
    text, err = vb.OpenRouterAgent().generate("p", max_tokens=vb._BRIEF_MAX_TOKENS)
    assert err is None
    assert vb.OpenRouterAgent._OUTPUT_HEADROOM >= 3_000
    assert sent == [vb._BRIEF_MAX_TOKENS + vb.OpenRouterAgent._OUTPUT_HEADROOM]
    assert sent[0] >= 6_000
