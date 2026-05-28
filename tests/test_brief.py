"""Tests for vnstock_brief — accuracy evaluator + helpers."""

from __future__ import annotations

from datetime import date as _date

import pandas as pd
import pytest

from vnstock_brief import (
    _detect_stance, _extract_section, evaluate_brief_accuracy,
    agent_accuracy_summary,
)


# ─── _extract_section ─────────────────────────────────────────────────────────

def test_extract_section_finds_tldr():
    text = "## 🎯 TLDR\nBias: TĂNG.\n## Tổng quan\nBody."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out
    assert "Body" not in out


def test_extract_section_case_insensitive():
    text = "## tldr\nBias: TĂNG."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out


def test_extract_section_returns_empty_when_missing():
    text = "## Other\nNo TLDR here."
    assert _extract_section(text, "TLDR") == ""


# ─── _detect_stance ───────────────────────────────────────────────────────────

def test_detect_stance_explicit_bullish():
    tldr = "Stance ngày mai: TĂNG — giữ vị thế dài."
    assert _detect_stance(tldr) == "bullish"


def test_detect_stance_explicit_bearish():
    tldr = "Stance ngày mai: GIẢM — chuyển phòng thủ."
    assert _detect_stance(tldr) == "bearish"


def test_detect_stance_explicit_neutral():
    tldr = "Stance ngày mai: TRUNG TÍNH — đứng ngoài."
    assert _detect_stance(tldr) == "neutral"


def test_detect_stance_unknown_when_no_signal():
    tldr = "Some text without stance keywords."
    assert _detect_stance(tldr) == "unknown"


def test_detect_stance_canonical_line_beats_fallback():
    """Explicit 'Stance ngày mai: TRUNG TÍNH' wins over bullish keywords elsewhere."""
    tldr = (
        "Phiên trầm lắng. Một số mã tích cực.\n"
        "Stance ngày mai: TRUNG TÍNH — đứng ngoài chờ tín hiệu."
    )
    assert _detect_stance(tldr) == "neutral"


# ─── evaluate_brief_accuracy ──────────────────────────────────────────────────

def _mk_closes() -> pd.Series:
    """Build a deterministic VNINDEX close series for tests."""
    dates = pd.bdate_range("2026-05-20", periods=10)
    values = [1200, 1210, 1215, 1218, 1220, 1230, 1228, 1235, 1240, 1250]
    return pd.Series(values, index=[d.date() for d in dates])


def test_evaluate_returns_unknown_when_no_output():
    out = evaluate_brief_accuracy({"output": "", "brief_date": "2026-05-22"})
    assert out["stance"] == "unknown"
    assert out["match"] is None


def test_evaluate_bullish_correct_match():
    """Bullish brief on day where T+1 close is up → match=True.
    closes: 2026-05-26 (Tue) = 1220, 2026-05-27 (Wed) = 1230 → +0.82% up.
    """
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG — bullish.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bullish"
    assert out["actual"] == "up"
    assert out["match"] is True


def test_evaluate_bearish_incorrect_match():
    """Bearish brief on day where T+1 is up → match=False."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: GIẢM — bearish bias.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bearish"
    assert out["actual"] == "up"
    assert out["match"] is False


def test_evaluate_returns_none_match_when_not_enough_data():
    """Brief at the latest available date can't be evaluated yet."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": closes.index[-1].isoformat(),
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["match"] is None


def test_evaluate_flat_when_under_threshold():
    closes = _mk_closes()
    # Tighten threshold so 0.82% move counts as flat
    brief = {
        "output": "## TLDR\nStance ngày mai: TRUNG TÍNH.",
        "brief_date": "2026-05-26",  # baseline=1220, T+1=1230 → +0.82%
    }
    out = evaluate_brief_accuracy(
        brief, closes=closes, horizon_days=1, neutral_threshold_pct=1.0,
    )
    assert out["actual"] == "flat"
    assert out["match"] is True   # neutral stance vs flat → match


def test_evaluate_horizon_2_uses_2nd_close_after():
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": "2026-05-26",
    }
    out1 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    out2 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=2)
    assert out1["eval_close"] != out2["eval_close"]


# ─── agent_accuracy_summary ───────────────────────────────────────────────────

def test_summary_groups_by_agent_name():
    closes = _mk_closes()
    briefs = [
        {"agent_name": "Groq", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Groq", "brief_date": "2026-05-27",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Mistral", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: GIẢM."},
    ]
    # Patch the loader so the summary uses our deterministic closes
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert "Groq" in out and "Mistral" in out
    assert out["Groq"]["n_total"] == 2
    assert out["Mistral"]["n_total"] == 1


def test_summary_accuracy_is_match_over_evaluated():
    """2026-05-26 → 2026-05-27 up (+0.82%); 2026-05-28 → 2026-05-29 up (+0.55%)."""
    closes = _mk_closes()
    briefs = [
        {"agent_name": "A", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},  # actual up → match
        {"agent_name": "A", "brief_date": "2026-05-28",
         "output": "## TLDR\nStance ngày mai: GIẢM."},  # actual up → miss
    ]
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert out["A"]["n_evaluated"] == 2
    assert out["A"]["n_match"] == 1
    assert out["A"]["accuracy"] == pytest.approx(0.5)
