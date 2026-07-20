"""Tests cho 3 món deep-dive DojoAgents (2026-07-15):
1) digest retry-1-lượt-kèm-lỗi  2) strip think-tags  3) LLM call ledger.
Hermetic — mọi call LLM đều fake, ledger ghi vào tmp_path."""

from __future__ import annotations

import json

import pytest

import vnstock_llm_ledger as ledger
import vnstock_report_digest as rd
from vnstock_sentiment import strip_think_tags


# ─── Món 2: strip_think_tags ─────────────────────────────────────────────────

def test_strip_paired_think_block():
    raw = "<think>để xem, stance chắc là -2...</think>\n{\"a\": 1}"
    assert strip_think_tags(raw) == '{"a": 1}'
    raw2 = "<reasoning>blah</reasoning>kết quả"
    assert strip_think_tags(raw2) == "kết quả"


def test_strip_orphan_close_tag_r1_style():
    # provider nuốt thẻ mở (deepseek-r1 qua vài gateway) — output bắt đầu
    # giữa dòng suy nghĩ và kết thúc bằng </think> rồi mới tới đáp án
    raw = "chắc tỷ giá tăng thì USD dương...\n</think>\n{\"stance\": 1}"
    assert strip_think_tags(raw) == '{"stance": 1}'


def test_strip_orphan_open_tag_truncated():
    # bị cắt vì hết token giữa lúc suy nghĩ → đuôi là reasoning, bỏ
    raw = '{"a": 1}\n<think>và mình nghĩ tiếp là'
    assert strip_think_tags(raw) == '{"a": 1}'


def test_strip_leaves_normal_text_alone():
    for s in ("P/E <10 là rẻ", "tin M&A <3", '{"x": "a < b"}'):
        assert strip_think_tags(s) == s
    assert strip_think_tags(None) == ""
    assert strip_think_tags("") == ""


def test_strip_think_block_containing_draft_json():
    # khối nháp trong think CHỨA JSON — không strip thì parse vớ nhầm nháp
    raw = '<think>nháp: {"tom_tat": "SAI"}</think>{"tom_tat": "dung roi"}'
    out = strip_think_tags(raw)
    assert json.loads(out)["tom_tat"] == "dung roi"


# ─── Món 3: LLM ledger ───────────────────────────────────────────────────────

@pytest.fixture()
def _tmp_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_META", tmp_path)
    return tmp_path


def test_ledger_aggregates_ok_fail_ratelimit(_tmp_meta):
    ledger.record("Groq", "kimi", ok=True,
                  usage={"prompt_tokens": 100, "completion_tokens": 20})
    ledger.record("Groq", "kimi", ok=False, error="HTTP 429 Too Many Requests")
    ledger.record("Groq", "kimi", ok=False, error="timeout")
    ledger.record("Anthropic", "haiku", ok=True,
                  usage={"input_tokens": 50, "output_tokens": 10})  # kiểu Anthropic
    s = ledger.summary()
    row = s["providers"]["Groq:kimi"]
    assert row["calls"] == 3 and row["ok"] == 1 and row["fail"] == 2
    assert row["rate_limited"] == 1                     # chỉ lỗi 429
    assert row["prompt_tokens"] == 100 and row["completion_tokens"] == 20
    a = s["providers"]["Anthropic:haiku"]
    assert a["prompt_tokens"] == 50 and a["completion_tokens"] == 10
    assert s["totals"]["calls"] == 4


def test_ledger_never_raises_and_survives_garbage(_tmp_meta):
    (_tmp_meta / "llm_ledger.json").write_text("{{{rác", encoding="utf-8")
    ledger.record("X", "y", ok=True, usage="not-a-dict")   # không nổ
    ledger.record("X", "y", ok=False, error=None)
    assert ledger.summary()["providers"]["X:y"]["calls"] == 2
    assert ledger.summary_lines()                          # có dòng hiển thị


def test_ledger_summary_empty_when_missing(_tmp_meta):
    assert ledger.summary() == {}
    assert ledger.summary_lines() == []


# ─── Doctor check ────────────────────────────────────────────────────────────

def _write_doctor_ledger(meta, day_rows):
    from datetime import date
    (meta / "llm_ledger.json").write_text(json.dumps(
        {"days": {date.today().isoformat(): day_rows}}), encoding="utf-8")


def test_doctor_llm_ledger_states(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path)
    assert doc.check_llm_ledger()["status"] == "off"       # chưa có sổ

    _write_doctor_ledger(tmp_path, {"Groq:kimi": {
        "calls": 5, "ok": 5, "fail": 0, "rate_limited": 0}})
    assert doc.check_llm_ledger()["status"] == "ok"

    _write_doctor_ledger(tmp_path, {"Groq:kimi": {
        "calls": 5, "ok": 2, "fail": 3, "rate_limited": 2}})
    r = doc.check_llm_ledger()
    assert r["status"] == "warn" and "Groq:kimi" in r["message"]

    _write_doctor_ledger(tmp_path, {"Groq:kimi": {
        "calls": 6, "ok": 2, "fail": 4, "rate_limited": 0}})
    assert doc.check_llm_ledger()["status"] == "warn"      # quá nửa lỗi


# ─── Món 1: digest retry-kèm-lỗi ─────────────────────────────────────────────

_GOOD = '{"tom_tat": "Bao cao tot", "stance": {}, "claims": [], "risks": []}'
_BAD = '{"tom_tat": "cut giua chung...'


def _accept(r):
    return rd.parse_digest(r) is not None


def test_describe_digest_error_branches():
    assert "không tìm thấy khối JSON" in rd.describe_digest_error("toàn chữ")
    assert "không tìm thấy khối JSON" in rd.describe_digest_error('{"a": 1')  # thiếu } đóng
    assert "không parse được" in rd.describe_digest_error('{"a": 1,}')        # phẩy thừa
    assert rd.describe_digest_error("") == "output rỗng"


def test_digest_retry_same_rung_with_feedback(monkeypatch):
    calls = []

    def fake_claude(system, user, **k):
        calls.append(user)
        return _BAD if len(calls) == 1 else _GOOD

    monkeypatch.setattr(rd, "_call_claude", fake_claude)
    monkeypatch.setattr(rd, "_call_openai", lambda *a, **k: None)
    monkeypatch.setattr(rd, "_free_ladder", lambda: [])
    raw, provider = rd.digest_call("sys", "câu hỏi", accept=_accept,
                                   feedback=rd.describe_digest_error)
    assert provider == "claude(retry)"
    assert rd.parse_digest(raw)["tom_tat"] == "Bao cao tot"
    assert len(calls) == 2
    # lượt retry phải mang LỜI PHÊ + output hỏng cũ
    assert "OUTPUT TRƯỚC CỦA BẠN KHÔNG ĐẠT" in calls[1]
    assert "không tìm thấy khối JSON" in calls[1] and _BAD[:40] in calls[1]


def test_digest_retry_only_once_per_cascade(monkeypatch):
    claude_calls, openai_calls = [], []
    monkeypatch.setattr(rd, "_call_claude",
                        lambda s, u, **k: (claude_calls.append(u) or _BAD))
    monkeypatch.setattr(rd, "_call_openai",
                        lambda s, u, **k: (openai_calls.append(u) or _GOOD))
    monkeypatch.setattr(rd, "_free_ladder", lambda: [])
    raw, provider = rd.digest_call("sys", "hỏi", accept=_accept,
                                   feedback=rd.describe_digest_error)
    assert provider == "openai"
    assert len(claude_calls) == 2      # 1 lần + 1 retry (đã dùng hết quota)
    assert len(openai_calls) == 1      # openai KHÔNG được retry nữa


def test_digest_call_strips_think_before_parse(monkeypatch):
    # JSON nháp nằm TRONG think block — không strip là parse vớ nhầm nháp
    wrapped = f'<think>nháp: {{"tom_tat": "SAI"}}</think>{_GOOD}'
    monkeypatch.setattr(rd, "_call_claude", lambda s, u, **k: wrapped)
    monkeypatch.setattr(rd, "_call_openai", lambda *a, **k: None)
    monkeypatch.setattr(rd, "_free_ladder", lambda: [])
    raw, provider = rd.digest_call("sys", "hỏi", accept=_accept)
    assert provider == "claude"
    assert rd.parse_digest(raw)["tom_tat"] == "Bao cao tot"


def test_digest_no_feedback_keeps_old_cascade(monkeypatch):
    # accept fail + feedback=None → hành vi cũ: rơi thẳng nấc sau, không retry
    calls = []
    monkeypatch.setattr(rd, "_call_claude",
                        lambda s, u, **k: (calls.append(u) or _BAD))
    monkeypatch.setattr(rd, "_call_openai", lambda s, u, **k: _GOOD)
    monkeypatch.setattr(rd, "_free_ladder", lambda: [])
    raw, provider = rd.digest_call("sys", "hỏi", accept=_accept)
    assert provider == "openai" and len(calls) == 1
