"""
Auditor Agent — "phản biện" layer between raw statistics and dashboard
output (Phase 4, Feature 4).

Purpose
-------
Screener presets and sector metrics are produced by deterministic code. But
deterministic code can still be wrong in subtle ways — a misapplied formula,
a dataset that's silently stale, a preset that's technically correct but
nonsensical in current market conditions. The Auditor is a pluggable layer
that takes a statistical payload and asks an LLM to scrutinise it for logic
errors before the dashboard renders.

Design
------
* ``AuditorAgent`` is an ABC with one method: ``audit(payload, context) ->
  AuditVerdict``. Payloads are arbitrary JSON-serialisable dicts (screener
  output, reconciler summary, anomaly report, etc.).
* ``NullAuditorAgent`` always approves. Used in tests and when no API key
  is configured — the pipeline keeps working, just without LLM oversight.
* ``ClaudeAuditorAgent`` / ``GPTAuditorAgent`` are HTTP-based concrete
  implementations. They reuse the same ``requests.post`` pattern already
  in ``vnstock_classifier.py``, so no new SDK dependency is added.
* The factory ``make_auditor()`` inspects env vars and returns the best
  available agent; callers never have to know which backend is in use.

Verdict schema
--------------
``AuditVerdict(approved: bool, confidence: float, issues: list[str],
               suggestions: list[str], raw_response: str | None)``

An ``approved=False`` verdict should prevent the dashboard from surfacing
the payload to end users. Confidence is on [0, 1]; the LLM self-reports.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore


def _ledger_record(provider: str, model: str, ok: bool,
                   usage: "dict | None" = None,
                   error: "str | None" = None) -> None:
    """Ghi sổ call LLM (vnstock_llm_ledger) — best-effort, không bao giờ raise.
    Trước 22/07 auditor KHÔNG ghi sổ → run.py audit gọi Claude mà ledger mù."""
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Verdict
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AuditVerdict:
    approved: bool
    confidence: float = 1.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    raw_response: str | None = None
    backend: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────────────────────────────────


class AuditorAgent(ABC):
    """
    An auditor scrutinises a statistical payload and returns a verdict.

    Implementations MUST:
    * Return an ``AuditVerdict`` — never raise on recoverable LLM errors.
      Instead, return ``approved=False, issues=["<error>"]``.
    * Tolerate large payloads by truncating or summarising; callers should
      not be forced to pre-process.
    * Be side-effect free besides the external API call.
    """

    name: str = "AuditorAgent"

    @abstractmethod
    def audit(
        self,
        payload: dict,
        *,
        context: str = "",
    ) -> AuditVerdict:
        ...

    # ── Shared helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(payload: dict, context: str) -> str:
        """Render the common audit prompt. Keep this stable across backends."""
        body = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
        if len(body) > 8000:
            body = body[:8000] + "\n… (truncated)"
        ctx = context.strip() or "A screener / market-statistics payload."
        return (
            "You are a Vietnamese-equities quantitative auditor. Scrutinise the\n"
            "payload below for LOGIC errors — not stylistic choices. Examples of\n"
            "issues to flag:\n"
            "  • price units mixed (VND vs thousand VND)\n"
            "  • daily change % outside the exchange band (HOSE 7, HNX 10, UPCOM 15)\n"
            "  • RSI > 100 or < 0, volumes that are negative, market cap\n"
            "    inconsistent with share count × price\n"
            "  • sector aggregates whose constituents do not sum\n"
            "  • stale dates (newest bar > 3 trading days old)\n"
            "  • obvious NaN / Inf leakage\n\n"
            f"CONTEXT: {ctx}\n\n"
            "PAYLOAD (JSON):\n"
            f"{body}\n\n"
            "Respond with a STRICT JSON object, nothing else:\n"
            "{\n"
            '  "approved": <bool>,\n'
            '  "confidence": <float in [0,1]>,\n'
            '  "issues": [<str>, ...],\n'
            '  "suggestions": [<str>, ...]\n'
            "}\n"
        )

    @staticmethod
    def _parse_verdict(raw: str, backend: str) -> AuditVerdict:
        """Best-effort JSON extraction from the LLM response."""
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if not m:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=["LLM response contained no JSON object"],
                raw_response=raw, backend=backend,
            )
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=[f"JSON parse error: {e}"],
                raw_response=raw, backend=backend,
            )
        approved = bool(data.get("approved", False))
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        issues = list(data.get("issues") or [])
        suggestions = list(data.get("suggestions") or [])
        return AuditVerdict(
            approved=approved,
            confidence=confidence,
            issues=[str(i) for i in issues],
            suggestions=[str(s) for s in suggestions],
            raw_response=raw,
            backend=backend,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Concrete implementations
# ─────────────────────────────────────────────────────────────────────────────


class NullAuditorAgent(AuditorAgent):
    """Always approves. Useful when no API key is configured or in tests."""

    name = "null"

    def audit(self, payload: dict, *, context: str = "") -> AuditVerdict:
        return AuditVerdict(
            approved=True, confidence=1.0,
            issues=[], suggestions=[],
            raw_response=None, backend=self.name,
        )


class ClaudeAuditorAgent(AuditorAgent):
    """Uses Anthropic's Messages API. Requires ANTHROPIC_API_KEY."""

    name = "claude"
    ENDPOINT = "https://api.anthropic.com/v1/messages"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 800,
                 timeout: int = 60):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def audit(self, payload: dict, *, context: str = "") -> AuditVerdict:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=["ANTHROPIC_API_KEY not set"],
                backend=self.name,
            )
        if requests is None:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=["requests library not installed"],
                backend=self.name,
            )
        prompt = self._build_prompt(payload, context)
        try:
            resp = requests.post(
                self.ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body["content"][0]["text"]
            _ledger_record("Anthropic", self.model, ok=True,
                           usage=body.get("usage"))
        except Exception as e:
            _ledger_record("Anthropic", self.model, ok=False,
                           error=f"{type(e).__name__}: {str(e)[:120]}")
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=[f"Claude API error: {type(e).__name__}: {str(e)[:120]}"],
                backend=self.name,
            )
        return self._parse_verdict(text, backend=self.name)


class GPTAuditorAgent(AuditorAgent):
    """Uses OpenAI Chat Completions. Requires OPENAI_API_KEY."""

    name = "gpt"
    ENDPOINT = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 800,
                 timeout: int = 60):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def audit(self, payload: dict, *, context: str = "") -> AuditVerdict:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=["OPENAI_API_KEY not set"],
                backend=self.name,
            )
        if requests is None:
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=["requests library not installed"],
                backend=self.name,
            )
        prompt = self._build_prompt(payload, context)
        try:
            resp = requests.post(
                self.ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
            _ledger_record("OpenAI", self.model, ok=True,
                           usage=body.get("usage"))
        except Exception as e:
            _ledger_record("OpenAI", self.model, ok=False,
                           error=f"{type(e).__name__}: {str(e)[:120]}")
            return AuditVerdict(
                approved=False, confidence=0.0,
                issues=[f"OpenAI API error: {type(e).__name__}: {str(e)[:120]}"],
                backend=self.name,
            )
        return self._parse_verdict(text, backend=self.name)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


def make_auditor(prefer: str = "auto") -> AuditorAgent:
    """
    Return the best-available auditor based on env vars.

    prefer = "auto" → try Claude, then GPT, then Null.
    prefer = "claude" | "gpt" | "null" forces a specific backend.
    """
    prefer = prefer.lower()
    if prefer == "null":
        return NullAuditorAgent()
    if prefer == "claude":
        return ClaudeAuditorAgent()
    if prefer == "gpt":
        return GPTAuditorAgent()
    # auto
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeAuditorAgent()
    if os.environ.get("OPENAI_API_KEY"):
        return GPTAuditorAgent()
    return NullAuditorAgent()


__all__ = [
    "AuditVerdict",
    "AuditorAgent",
    "NullAuditorAgent",
    "ClaudeAuditorAgent",
    "GPTAuditorAgent",
    "make_auditor",
]
