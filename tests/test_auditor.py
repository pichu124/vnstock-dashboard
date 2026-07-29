"""Tests for vnstock_auditor — AuditorAgent interface."""

from __future__ import annotations

import os

import pytest

import vnstock_auditor as va
from vnstock_auditor import (
    AuditVerdict,
    AuditorAgent,
    ClaudeAuditorAgent,
    FreeAuditorAgent,
    GPTAuditorAgent,
    NullAuditorAgent,
    make_auditor,
)


@pytest.fixture()
def _no_keys(monkeypatch):
    """Factory hermetic: chặn make_auditor load .env (máy thật có key free
    trong .env → auto sẽ trả FreeAuditor thay vì Null) + xoá sạch mọi key."""
    monkeypatch.setattr(va, "_ensure_env_loaded", lambda: None)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", *va._FREE_KEY_ENVS):
        monkeypatch.delenv(k, raising=False)


# ── Null agent ─────────────────────────────────────────────────────────────

def test_null_auditor_always_approves():
    v = NullAuditorAgent().audit({"anything": "goes"})
    assert v.approved is True
    assert v.issues == []
    assert v.backend == "null"


# ── Factory ────────────────────────────────────────────────────────────────

def test_make_auditor_forced_null():
    assert isinstance(make_auditor("null"), NullAuditorAgent)


def test_make_auditor_forced_claude():
    assert isinstance(make_auditor("claude"), ClaudeAuditorAgent)


def test_make_auditor_forced_gpt():
    assert isinstance(make_auditor("gpt"), GPTAuditorAgent)


def test_make_auditor_forced_free(_no_keys):
    # forced không cần key — key check nằm ở từng nấc cascade lúc audit()
    assert isinstance(make_auditor("free"), FreeAuditorAgent)


def test_make_auditor_auto_uses_null_when_no_keys(_no_keys):
    assert isinstance(make_auditor("auto"), NullAuditorAgent)


def test_make_auditor_auto_prefers_claude(_no_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("GEMINI_API_KEY", "gk-fake")
    assert isinstance(make_auditor("auto"), ClaudeAuditorAgent)


def test_make_auditor_auto_falls_back_to_gpt(_no_keys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    assert isinstance(make_auditor("auto"), GPTAuditorAgent)


def test_make_auditor_auto_free_when_only_free_key(_no_keys, monkeypatch):
    """Điểm [6] 29/07: máy all-free (chỉ key free tier) phải rơi vào Free
    chứ KHÔNG rơi thẳng Null như trước — Null = phê duyệt suông."""
    monkeypatch.setenv("GEMINI_API_KEY", "gk-fake")
    assert isinstance(make_auditor("auto"), FreeAuditorAgent)


def test_make_auditor_auto_free_accepts_any_cascade_key(_no_keys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake")
    assert isinstance(make_auditor("auto"), FreeAuditorAgent)


# ── Missing keys produce graceful verdicts (no exceptions) ─────────────────

def test_claude_missing_key_returns_unapproved(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    v = ClaudeAuditorAgent().audit({"x": 1})
    assert v.approved is False
    assert any("ANTHROPIC_API_KEY" in i for i in v.issues)


def test_gpt_missing_key_returns_unapproved(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    v = GPTAuditorAgent().audit({"x": 1})
    assert v.approved is False
    assert any("OPENAI_API_KEY" in i for i in v.issues)


# ── Prompt assembly & verdict parsing ──────────────────────────────────────

def test_prompt_includes_payload_and_context():
    prompt = AuditorAgent._build_prompt(
        {"rsi": 150, "ticker": "VCB"},
        context="Daily screener output",
    )
    assert "rsi" in prompt
    assert "VCB" in prompt
    assert "Daily screener output" in prompt
    assert "approved" in prompt   # expected JSON key in instructions


def test_prompt_truncates_large_payloads():
    big = {"tickers": ["T" + str(i) for i in range(5000)]}
    prompt = AuditorAgent._build_prompt(big, context="")
    assert len(prompt) < 15_000
    assert "truncated" in prompt


def test_parse_verdict_extracts_json_object():
    raw = 'Some preamble... {"approved": true, "confidence": 0.8, "issues": [], "suggestions": ["x"]} trailing'
    v = AuditorAgent._parse_verdict(raw, backend="test")
    assert v.approved is True
    assert v.confidence == pytest.approx(0.8)
    assert v.suggestions == ["x"]
    assert v.backend == "test"


def test_parse_verdict_clamps_confidence():
    raw = '{"approved": true, "confidence": 2.5, "issues": [], "suggestions": []}'
    v = AuditorAgent._parse_verdict(raw, backend="test")
    assert v.confidence == 1.0


def test_parse_verdict_handles_no_json():
    v = AuditorAgent._parse_verdict("sorry no json here", backend="test")
    assert v.approved is False
    assert any("no JSON" in i for i in v.issues)


def test_parse_verdict_handles_malformed_json():
    v = AuditorAgent._parse_verdict('{"approved": tru}', backend="test")
    assert v.approved is False
    assert any("JSON parse error" in i for i in v.issues)


# ── FreeAuditorAgent (điểm [6] all-free, 29/07) ────────────────────────────

def _fake_digest(result):
    """digest_call giả trả `result`, ghi lại call args để soi."""
    captured = {}

    def _call(system, user, accept=None, feedback=None):
        captured.update(system=system, user=user,
                        accept=accept, feedback=feedback)
        return result

    return _call, captured


def test_free_auditor_routes_through_digest_cascade(monkeypatch):
    import vnstock_report_digest as dg
    raw = ('{"approved": false, "confidence": 0.7, '
           '"issues": ["RSI 150 > 100"], "suggestions": ["check units"]}')
    fake, captured = _fake_digest((raw, "Gemini:gemini-3.5-flash"))
    monkeypatch.setattr(dg, "digest_call", fake)

    v = FreeAuditorAgent().audit({"rsi": 150}, context="unit test")

    assert v.approved is False
    assert v.issues == ["RSI 150 > 100"]
    assert v.backend == "free:Gemini:gemini-3.5-flash"   # soi model nào chấm
    # prompt tách tại CONTEXT: — chỉ dẫn ổn định làm system, data làm user
    assert "quantitative auditor" in captured["system"]
    assert captured["user"].startswith("CONTEXT:")
    assert "rsi" in captured["user"]
    assert "unit test" in captured["user"]


def test_free_auditor_accept_callback_gates_broken_json(monkeypatch):
    """accept của cascade = JSON verdict parse được — output cắt cụt (lỗi
    thật Cerebras 14/07) phải bị chấm rớt để cascade thử nấc sau."""
    import vnstock_report_digest as dg
    fake, captured = _fake_digest(('{"approved": true}', "Cerebras:gpt-oss-120b"))
    monkeypatch.setattr(dg, "digest_call", fake)

    FreeAuditorAgent().audit({"x": 1})

    accept = captured["accept"]
    assert accept('{"approved": true, "confidence": 1.0}') is True
    assert accept('nháp… {"approved": true} …đuôi') is True
    assert accept('{"approved": true, "confi') is False   # JSON bị cắt
    assert accept("no json at all") is False
    assert accept("") is False
    assert callable(captured["feedback"])                 # có lượt tự sửa


def test_free_auditor_all_rungs_down_returns_unapproved(monkeypatch):
    """Cạn thang (mọi model free lỗi) → approved=False để run.py audit exit 1
    cảnh báo, KHÔNG phê duyệt suông như NullAuditor."""
    import vnstock_report_digest as dg
    fake, _ = _fake_digest((None, ""))
    monkeypatch.setattr(dg, "digest_call", fake)

    v = FreeAuditorAgent().audit({"x": 1})

    assert v.approved is False
    assert v.confidence == 0.0
    assert v.backend == "free"
    assert any("mọi nấc" in i for i in v.issues)


# ── Abstract contract ─────────────────────────────────────────────────────

def test_auditoragent_is_abstract():
    with pytest.raises(TypeError):
        AuditorAgent()   # type: ignore[abstract]


def test_verdict_to_dict_roundtrip():
    v = AuditVerdict(approved=True, confidence=0.9, issues=["x"],
                     suggestions=["y"], backend="test")
    d = v.to_dict()
    assert d["approved"] is True
    assert d["issues"] == ["x"]
    assert d["backend"] == "test"
