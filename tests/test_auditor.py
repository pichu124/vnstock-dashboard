"""Tests for vnstock_auditor — AuditorAgent interface."""

from __future__ import annotations

import os

import pytest

from vnstock_auditor import (
    AuditVerdict,
    AuditorAgent,
    ClaudeAuditorAgent,
    GPTAuditorAgent,
    NullAuditorAgent,
    make_auditor,
)


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


def test_make_auditor_auto_uses_null_when_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(make_auditor("auto"), NullAuditorAgent)


def test_make_auditor_auto_prefers_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    assert isinstance(make_auditor("auto"), ClaudeAuditorAgent)


def test_make_auditor_auto_falls_back_to_gpt(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    assert isinstance(make_auditor("auto"), GPTAuditorAgent)


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
