"""Tests cho đợt thay ladder model 22/07/2026 (điểm [1]) + ledger phủ đủ
call trả phí + cột quy đổi tiền trong --show.

Bối cảnh: ladder 8B llama cũ chết (Groq deprecate 17/06, Cerebras gỡ,
OpenRouter hết :free) — slug mới đã probe sống trên máy thật 22/07
(scripts/probe_models.py). Hermetic — mọi call LLM đều fake.
"""

from __future__ import annotations

import json

import pytest

import vnstock_llm_ledger as ledger
import vnstock_sentiment as snt


@pytest.fixture()
def _tmp_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_META", tmp_path)
    return tmp_path


class _Resp:
    def __init__(self, body: dict, status: int = 200):
        self._body = body
        self.status_code = status
        self.text = json.dumps(body)

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _openai_body(content: str, usage: "dict | None" = None) -> dict:
    return {"choices": [{"message": {"content": content}}],
            "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20}}


# ─── Ladder sentiment mới (điểm [1]) ─────────────────────────────────────────

def test_providers_ladder_slugs_22_07():
    """Guard chống lùi về slug chết: đúng thứ tự Gemini→Groq→Cerebras→OR,
    đúng slug đã probe sống 22/07."""
    got = [(p["name"], p["model"]) for p in snt._PROVIDERS]
    assert got == [
        ("Gemini", "gemini-3.5-flash-lite"),
        ("Groq", "openai/gpt-oss-20b"),
        ("Cerebras", "gemma-4-31b"),
        ("OpenRouter", "openai/gpt-oss-20b:free"),
    ]
    # slug chết không được quay lại
    dead = {"llama-3.1-8b-instant", "llama3.1-8b",
            "meta-llama/llama-3.1-8b-instruct:free"}
    assert not dead & {m for _, m in got}


def test_call_provider_sends_max_tokens_and_extra(monkeypatch, _tmp_meta):
    # Arrange — nấc Groq gpt-oss: reasoning model cần max_tokens rộng + effort
    sent = {}

    def _post(url, headers=None, json=None, timeout=None):
        sent.update(body=json)
        return _Resp(_openai_body("TÍCH_CỰC"))

    monkeypatch.setattr("requests.post", _post)
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    groq = next(p for p in snt._PROVIDERS if p["name"] == "Groq")

    # Act
    out = snt._call_provider(groq, "VCB lãi kỷ lục")

    # Assert
    assert out == "positive"
    assert sent["body"]["max_tokens"] == 256          # không còn 10 token cụt
    assert sent["body"]["reasoning_effort"] == "low"  # extra được merge


def test_chat_complete_floors_max_tokens_but_keeps_extra_for_default_only(
        monkeypatch, _tmp_meta):
    # Arrange — caller xin 80 token; override model khác họ KHÔNG được kèm extra
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _Resp(_openai_body("ok"))

    monkeypatch.setattr("requests.post", _post)
    for env in ("GEMINI_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    # Act — override Groq sang model khác (giả lập _ANALYZE_MODELS)
    out = snt.chat_complete("s", "u", max_tokens=80,
                            model_map={"Groq": "some/other-model"})

    # Assert — call đầu là override: floor 256 nhưng KHÔNG có reasoning_effort
    assert out == "ok"
    assert calls[0]["model"] == "some/other-model"
    assert calls[0]["max_tokens"] == 256
    assert "reasoning_effort" not in calls[0]


# ─── Cột quy đổi tiền trong ledger ───────────────────────────────────────────

def test_cost_usd_prefix_match_and_free_default():
    row = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    # Haiku (khớp prefix bỏ suffix ngày): $1 in + $5 out
    assert ledger._cost_usd("Anthropic:claude-haiku-4-5-20251001", row) == 6.00
    # flash-lite phải khớp dòng lite, không dính giá flash thường
    assert ledger._cost_usd("Gemini:gemini-3.5-flash-lite", row) == pytest.approx(0.50)
    # model free / lạ → $0
    assert ledger._cost_usd("Groq:openai/gpt-oss-20b", row) == 0.0


def test_summary_lines_show_cost_only_when_paid(_tmp_meta):
    # Arrange — 1 call Haiku trả phí + 1 call free
    ledger.record("Anthropic", "claude-haiku-4-5-20251001", ok=True,
                  usage={"input_tokens": 2000, "output_tokens": 1000})
    ledger.record("Groq", "openai/gpt-oss-20b", ok=True,
                  usage={"prompt_tokens": 500, "completion_tokens": 50})

    # Act
    lines = ledger.summary_lines()

    # Assert — header có tổng $ và ~đ; dòng Haiku có $, dòng free thì không
    assert "≈ $" in lines[0] and "đ)" in lines[0]
    haiku_line = next(l for l in lines if "claude-haiku" in l)
    free_line = next(l for l in lines if "gpt-oss-20b" in l)
    assert "$" in haiku_line
    assert "$" not in free_line


# ─── Ledger phủ brief agent + auditor (trước 22/07 là điểm mù) ──────────────

def test_brief_claude_agent_records_ledger(monkeypatch, _tmp_meta):
    import vnstock_brief as vb

    def _post(url, headers=None, json=None, timeout=None):
        return _Resp({"content": [{"text": "brief ok"}],
                      "usage": {"input_tokens": 10, "output_tokens": 5}})

    monkeypatch.setattr("requests.post", _post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")

    text, err = vb.ClaudeAgent().generate("prompt", max_tokens=50)

    assert (text, err) == ("brief ok", None)
    s = ledger.summary()
    key = "Anthropic:claude-haiku-4-5-20251001"
    assert s["providers"][key]["ok"] == 1
    assert s["providers"][key]["prompt_tokens"] == 10


def test_auditor_claude_records_ledger(monkeypatch, _tmp_meta):
    import vnstock_auditor as va

    verdict_json = json.dumps({"approved": True, "confidence": 0.9,
                               "issues": [], "suggestions": []})

    def _post(url, headers=None, json=None, timeout=None):
        return _Resp({"content": [{"text": verdict_json}],
                      "usage": {"input_tokens": 30, "output_tokens": 8}})

    monkeypatch.setattr(va.requests, "post", _post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")

    v = va.ClaudeAuditorAgent().audit({"x": 1})

    assert v.approved is True
    s = ledger.summary()
    assert s["providers"]["Anthropic:claude-sonnet-4-6"]["ok"] == 1


# ─── Cascade digest all-free (điểm [3][4][5], 22/07) ─────────────────────────

def test_digest_free_tiers_slugs_22_07():
    """Guard chống lùi slug: bậc 1 + bậc 2 digest đúng bộ probe sống 22/07."""
    import vnstock_report_digest as dg
    assert dg._FREE_MODELS == {
        "Gemini": "gemini-3.5-flash",
        "Cerebras": "gpt-oss-120b",
        "OpenRouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    }
    assert dg._FREE_TIER2 == (
        ("Groq", "openai/gpt-oss-120b"),
        ("Groq", "qwen/qwen3.6-27b"),
        ("Gemini", "gemini-3.5-flash-lite"),
        ("OpenRouter", "openai/gpt-oss-20b:free"),
    )
    assert dg._PROVIDER_META["Gemini"][0] == "GEMINI_API_KEY"
    # bậc 2 có reasoning model — budget không được tụt về 1200 cũ
    assert dg._TIER2_TOKENS >= 3000


# ─── Alert "LLM ladder DOWN" (yêu cầu user 22/07 khi chốt all-free) ─────────

def test_alert_ladder_down_sends_once_per_day(monkeypatch, _tmp_meta):
    sent = []
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")     # đè kill-switch conftest
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda text, **k: sent.append(text) or {"ok": True})

    assert ledger.alert_ladder_down("digest test") is True
    assert len(sent) == 1 and "LLM ladder DOWN" in sent[0]
    # throttle: cùng ngày không báo lần 2
    assert ledger.alert_ladder_down("digest test") is False
    assert len(sent) == 1


def test_alert_ladder_down_killswitch_and_retry_on_send_fail(monkeypatch, _tmp_meta):
    # kill-switch (conftest đã set =0) → không gửi, không đụng telegram
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("kill-switch bật mà vẫn gửi")))
    assert ledger.alert_ladder_down() is False

    # gửi lỗi (thiếu token…) → False và KHÔNG ghi flag → lần sau THỬ LẠI
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set trong .env")

    monkeypatch.setattr("vnstock_telegram.send_message", _boom)
    assert ledger.alert_ladder_down() is False
    assert ledger.alert_ladder_down() is False
    assert calls["n"] == 2                            # không bị flag chặn


def test_doctor_ledger_all_fail_is_error(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    from datetime import date as _d
    monkeypatch.setattr(doc, "_META", tmp_path)
    (tmp_path / "llm_ledger.json").write_text(json.dumps(
        {"days": {_d.today().isoformat(): {
            "Groq:x": {"calls": 4, "ok": 0, "fail": 4, "rate_limited": 0}}}}),
        encoding="utf-8")
    r = doc.check_llm_ledger()
    assert r["status"] == "error" and "TOÀN BỘ" in r["message"]
