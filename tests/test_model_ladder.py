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
    """Guard chống lùi về slug chết: đúng thứ tự Gemini→Groq→Cerebras.

    Nấc OpenRouter `openai/gpt-oss-20b:free` GỠ 22/08 (probe model watch:
    HTTP 404 "unavailable for free" + slug biến mất khỏi danh mục). Thang
    còn 3 nấc — và Cerebras đang hỏng ở mức TÀI KHOẢN (402), nên thực tế
    chỉ Gemini + Groq còn sống. Thêm nấc mới thì PHẢI probe trên máy thật
    trước, đừng chép từ catalog.
    """
    got = [(p["name"], p["model"]) for p in snt._PROVIDERS]
    assert got == [
        ("Gemini", "gemini-3.5-flash-lite"),
        ("Groq", "openai/gpt-oss-20b"),
        ("Cerebras", "gemma-4-31b"),
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


def test_chat_complete_with_model_reports_the_rung_that_answered(
        monkeypatch, _tmp_meta):
    """`with_model=True` (thêm 07/08 cho điểm [8]) trả kèm nấc đã trả lời —
    classifier ghi cột `model` theo nấc THẬT thay vì mặc định CLI."""
    # Arrange — Gemini có key nhưng chết, Groq đỡ
    def _post(url, headers=None, json=None, timeout=None):
        if "generativelanguage" in url:
            return _Resp({}, status=503)
        return _Resp(_openai_body("ok"))

    monkeypatch.setattr("requests.post", _post)
    for env in ("CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    # Act
    text, model = snt.chat_complete("s", "u", with_model=True)

    # Assert
    assert text == "ok"
    assert model == "Groq:openai/gpt-oss-20b"


def test_chat_complete_ex_retries_once_with_a_wider_cap_when_provider_cuts(
        monkeypatch, _tmp_meta):
    """Close 08/09: khối tin in "— tác động: Nh" — provider cắt ở max_tokens
    (finish_reason "length"), câu cụt lọt cache vì trông y hệt câu ngắn hợp lệ.
    Nay: bị cắt → gọi lại ĐÚNG nấc đó một lần với trần ×_TRUNCATE_RETRY_X, trả
    kèm cờ `truncated` để caller quyết."""
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) == 1:
            body = _openai_body("TRUNG_LẬP | Nh")
            body["choices"][0]["finish_reason"] = "length"
            return _Resp(body)
        body = _openai_body("TRUNG_LẬP | Nhóm điện tử chịu áp lực nhập siêu")
        body["choices"][0]["finish_reason"] = "stop"
        return _Resp(body)

    monkeypatch.setattr("requests.post", _post)
    for env in ("GEMINI_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    out = snt.chat_complete_ex("s", "u", max_tokens=120)

    assert [c["max_tokens"] for c in calls] == [256, 256 * snt._TRUNCATE_RETRY_X]
    assert [c["model"] for c in calls] == ["openai/gpt-oss-20b"] * 2   # cùng nấc
    assert out["text"] == "TRUNG_LẬP | Nhóm điện tử chịu áp lực nhập siêu"
    assert out["truncated"] is False and out["finish_reason"] == "stop"
    assert out["model"] == "Groq:openai/gpt-oss-20b"


def test_chat_complete_ex_flags_a_cut_that_survives_the_retry(
        monkeypatch, _tmp_meta):
    """Vẫn cụt sau lần gọi lại → trả chữ đã có kèm truncated=True, và KHÔNG
    gọi lần thứ ba (một lần gọi lại là trần chi phí)."""
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        body = _openai_body("TRUNG_LẬP | Nh")
        body["choices"][0]["finish_reason"] = "length"
        return _Resp(body)

    monkeypatch.setattr("requests.post", _post)
    for env in ("GEMINI_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    out = snt.chat_complete_ex("s", "u")
    assert len(calls) == 2
    assert out["truncated"] is True and out["text"] == "TRUNG_LẬP | Nh"
    # wrapper cũ vẫn trả text trơn (caller cũ không biết cờ — đúng như trước)
    calls.clear()
    assert snt.chat_complete("s", "u") == "TRUNG_LẬP | Nh"


def test_chat_complete_ex_moves_to_the_next_rung_when_the_retry_errors(
        monkeypatch, _tmp_meta):
    """Ledger 09/09 (máy thật): 8 tin → 12 call flash, 3/4 lỗi là 429 ở lần
    GỌI LẠI (bắn sát lần đầu). Bản đầu trả câu cụt về ⇒ analyze_item từ chối
    ⇒ 3 tin trống trong khi flash-lite/Groq còn sống. Nay: gọi lại lỗi → đi
    tiếp nấc kế; câu cụt chỉ là lưới cuối khi cạn thang."""
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if "generativelanguage" in url:
            if len(calls) == 1:
                body = _openai_body("TRUNG_LẬP | Nh")
                body["choices"][0]["finish_reason"] = "length"
                return _Resp(body)
            return _Resp({}, status=429)          # gọi lại dính rate-limit
        body = _openai_body("TRUNG_LẬP | Nhóm điện tử chịu áp lực nhập siêu")
        body["choices"][0]["finish_reason"] = "stop"
        return _Resp(body)

    monkeypatch.setattr("requests.post", _post)
    for env in ("CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    out = snt.chat_complete_ex("s", "u", model_map={"Gemini": "gemini-3.5-flash"})
    # flash: đầu (cụt) + gọi lại (429); flash-lite: 429; Groq: trọn câu
    assert [c["model"] for c in calls] == [
        "gemini-3.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
        "openai/gpt-oss-20b"]
    assert out["truncated"] is False and out["model"] == "Groq:openai/gpt-oss-20b"
    assert out["text"] == "TRUNG_LẬP | Nhóm điện tử chịu áp lực nhập siêu"


def test_chat_complete_ex_returns_the_cut_answer_only_when_the_ladder_is_dry(
        monkeypatch, _tmp_meta):
    """Cạn thang thật thì câu cụt vẫn hơn tay trắng — trả kèm truncated=True
    để caller tự quyết (analyze_item vẫn từ chối, reflection thì dùng)."""
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) == 1:
            body = _openai_body("TRUNG_LẬP | Nh")
            body["choices"][0]["finish_reason"] = "length"
            return _Resp(body)
        return _Resp({}, status=503)

    monkeypatch.setattr("requests.post", _post)
    for env in ("CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("GROQ_API_KEY", "gk")

    out = snt.chat_complete_ex("s", "u")
    assert len(calls) == 3                          # lite: đầu (cụt) + gọi lại (503); Groq: 503
    assert out["truncated"] is True and out["text"] == "TRUNG_LẬP | Nh"
    assert out["model"].startswith("Gemini:")


def test_is_truncated_covers_every_wire_format():
    assert snt._is_truncated("length")          # OpenAI-compat
    assert snt._is_truncated("MAX_TOKENS")      # Gemini native
    assert snt._is_truncated("max_tokens")      # Anthropic
    assert not snt._is_truncated("stop") and not snt._is_truncated(None)


def test_chat_complete_with_model_returns_pair_when_ladder_dry(
        monkeypatch, _tmp_meta):
    """Cạn thang vẫn phải trả TUPLE — caller unpack, trả None là TypeError."""
    for env in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert snt.chat_complete("s", "u", with_model=True) == (None, "")
    assert snt.chat_complete("s", "u") is None      # chữ ký cũ không đổi


def test_record_keeps_last_error_text(_tmp_meta):
    """Phát hiện 11/08: pipeline KHÔNG có log (Task Scheduler vứt stdout) —
    ledger chỉ đếm thì error text của sự cố mất sạch (ca Groq qwen 0/2 không
    truy được bằng chứng). Nay giữ ĐUÔI LỖI CUỐI mỗi dòng; --show và tin
    alert tự thành công cụ chẩn đoán."""
    ledger.record("Groq", "qwen/qwen3.6-27b", ok=False,
                  error="Groq API 400: " + "x" * 500)
    ledger.record("Groq", "qwen/qwen3.6-27b", ok=True,
                  usage={"prompt_tokens": 5, "completion_tokens": 5})
    row = ledger.summary()["providers"]["Groq:qwen/qwen3.6-27b"]
    assert row["last_error"].startswith("Groq API 400")
    assert len(row["last_error"]) <= 160          # đuôi, không phải cả stack
    assert any("lỗi cuối" in ln for ln in ledger.summary_lines())


def test_last_error_overwritten_by_newest_fail(_tmp_meta):
    ledger.record("Groq", "m", ok=False, error="lỗi cũ")
    ledger.record("Groq", "m", ok=False, error="lỗi mới")
    assert ledger.summary()["providers"]["Groq:m"]["last_error"] == "lỗi mới"


def test_ok_only_rows_have_no_error_line(_tmp_meta):
    ledger.record("Gemini", "flash", ok=True,
                  usage={"prompt_tokens": 5, "completion_tokens": 5})
    assert not any("lỗi cuối" in ln for ln in ledger.summary_lines())


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
    # Nấc OpenRouter GỠ 22/08 (HTTP 404 + biến mất khỏi danh mục)
    assert dg._FREE_TIER2 == (
        ("Groq", "openai/gpt-oss-120b"),
        ("Groq", "qwen/qwen3.6-27b"),
        ("Gemini", "gemini-3.5-flash-lite"),
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


# ─── --test-alert: bắn tin (TEST) qua đúng đường ống thật (user gật 11/08) ──

def test_test_alert_skips_throttle_flag(monkeypatch, _tmp_meta):
    """Bẫy thiết kế PHẢI né: test-alert mà ghi cờ ngày thì test buổi sáng
    nuốt mất sự cố THẬT buổi chiều cùng ngày — phản tác dụng đúng chỗ hiểm."""
    sent = []
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda text, **k: sent.append(text) or {"ok": True})

    assert ledger.test_alert() == 0
    assert len(sent) == 1
    assert "(TEST)" in sent[0] and "LLM ladder DOWN" in sent[0]
    assert not (_tmp_meta / "llm_alert.json").exists()   # KHÔNG đụng cờ
    # và alert THẬT ngay sau đó vẫn gửi được — không bị test chặn
    assert ledger.alert_ladder_down("sự cố thật") is True
    assert len(sent) == 2


def test_test_alert_warns_when_killswitch_off(monkeypatch, _tmp_meta):
    """Gate tắt: VẪN gửi (chạy tay là chủ đích) nhưng exit 1 — phát hiện
    "alert thật đang câm" chính là một nửa lý do tồn tại của test này."""
    sent = []
    # conftest đã set VNSTOCK_LLM_ALERT=0 — giữ nguyên
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda text, **k: sent.append(text) or {"ok": True})
    assert ledger.test_alert() == 1
    assert len(sent) == 1 and "(TEST)" in sent[0]


def test_test_alert_reports_send_failure(monkeypatch, _tmp_meta, capsys):
    """Gửi fail → exit 2 KÈM lý do — test-alert không được nuốt lỗi như
    alert thật (mục đích của nó là lộ bệnh)."""
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("TELEGRAM_BOT_TOKEN chưa set trong .env")))
    assert ledger.test_alert() == 2
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_alert_body_shared_between_real_and_test(monkeypatch, _tmp_meta):
    """Parity: thân tin test = thân tin thật (cùng `_alert_message`) — format
    trôi là test hết giá trị chứng thực. Mirror doctrine apply_brief_guards."""
    sent = []
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda text, **k: sent.append(text) or {"ok": True})
    ledger.test_alert()
    ledger.alert_ladder_down("ctx")
    test_msg, real_msg = sent
    body = ledger._alert_message("test thủ công")   # builder dùng chung
    assert body in test_msg                 # test = banner (TEST) + body thật
    assert "Soi bệnh" in real_msg and "Soi bệnh" in test_msg


def test_cli_accepts_test_alert(monkeypatch, _tmp_meta):
    monkeypatch.setenv("VNSTOCK_LLM_ALERT", "1")
    monkeypatch.setattr("vnstock_telegram.send_message",
                        lambda *a, **k: {"ok": True})
    assert ledger.main(["--test-alert"]) == 0


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


# ─── Điểm [7] brief: Gemini chính + migration + thứ tự sức mạnh (22/07) ─────

def test_gemini_agent_registered_with_think_headroom(monkeypatch, _tmp_meta):
    import vnstock_brief as vb
    assert vb.AGENT_REGISTRY["gemini"] is vb.GeminiAgent

    sent = {}

    def _post(url, headers=None, json=None, timeout=None):
        sent.update(body=json, url=url)
        return _Resp(_openai_body("brief gemini"))

    monkeypatch.setattr("requests.post", _post)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")

    text, err = vb.GeminiAgent().generate("prompt", max_tokens=2800)

    assert (text, err) == ("brief gemini", None)
    assert "generativelanguage.googleapis.com" in sent["url"]
    # flash suy nghĩ mặc định → budget phải được nới thêm headroom
    assert sent["body"]["max_tokens"] == 2800 + vb.GeminiAgent._THINK_HEADROOM
    assert ledger.summary()["providers"]["Gemini:gemini-3.5-flash"]["ok"] == 1


def test_model_migrations_upgrade_saved_config(tmp_path, monkeypatch):
    """Bảng đổi số: slug chết trong brief_agents.json tự nâng cấp khi load,
    GIỮ NGUYÊN enabled/thứ tự; slug user tự gõ (ngoài bảng) không bị đụng."""
    import vnstock_brief as vb
    cfg_path = tmp_path / "brief_agents.json"
    cfg_path.write_text(json.dumps([
        {"type": "groq", "model": "llama-3.3-70b-versatile",
         "name": "Groq Llama-3.3-70B", "enabled": True, "max_tokens": 1200},
        {"type": "cerebras", "model": "llama3.3-70b",
         "name": "Cerebras", "enabled": False, "max_tokens": 1200},
        {"type": "openrouter", "model": "my/custom-model",
         "name": "Custom", "enabled": True, "max_tokens": 1200},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(vb, "AGENTS_CONFIG_PATH", cfg_path)

    out = vb.load_agent_configs()

    by_type = {c["type"]: c for c in out}
    assert by_type["groq"]["model"] == "qwen/qwen3.6-27b"     # đổi số
    # ĐỔI CHỦ Ý 11/08 (user quyết): bản 29/07 chốt "migration giữ enabled" —
    # nhưng CHÍNH kịch bản này (llama enabled → qwen giữ enabled) sinh ra 3
    # tuần 413 câm lặng: ghế brief Groq hỏng CẤU TRÚC (prompt ~10K > trần
    # 8K/request). Nay migrate xong bị tắt MỘT LẦN kèm marker; user bật lại
    # trong ⚙️ là chủ đích, không bị tắt nữa (test_brief_agent_config).
    assert by_type["groq"]["enabled"] is False
    assert "413" in by_type["groq"]["auto_disabled"]
    assert by_type["cerebras"]["model"] == "gpt-oss-120b"
    assert by_type["cerebras"]["enabled"] is False
    assert by_type["openrouter"]["model"] == "my/custom-model"  # không đụng
    # Tên hiển thị (lộ 30/07 trên dashboard A/B): tên mặc định mô tả model
    # CŨ ("Groq Llama-3.3-70B") phải được thay theo default mới; tên KHÔNG
    # nhắc model cũ ("Cerebras") là tên user chọn → giữ nguyên.
    assert by_type["groq"]["name"] == "Groq Qwen3.6-27B"
    assert by_type["cerebras"]["name"] == "Cerebras"
    # merge thêm Gemini (provider mới) vào config cũ, enabled sẵn
    assert by_type["gemini"]["model"] == "gemini-3.5-flash"
    assert by_type["gemini"]["enabled"] is True
    # file đã được ghi lại với slug mới
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert any(c["model"] == "qwen/qwen3.6-27b" for c in saved)


def test_strength_sorted_gemini_first():
    import vnstock_brief as vb
    agents = [vb.OpenRouterAgent(), vb.GroqAgent(), vb.GeminiAgent(),
              vb.CerebrasAgent()]
    got = [a.agent_type for a in vb._strength_sorted(agents)]
    assert got == ["gemini", "groq", "cerebras", "openrouter"]


def test_default_configs_no_dead_slugs_and_gemini_enabled():
    import vnstock_brief as vb
    cfgs = {c["type"]: c for c in vb._DEFAULT_AGENT_CONFIGS}
    assert vb._DEFAULT_AGENT_CONFIGS[0]["type"] == "gemini"
    assert cfgs["gemini"]["enabled"] is True
    dead = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3.3-70b",
            "llama3.1-8b", "meta-llama/llama-3.3-70b-instruct:free",
            "meta-llama/llama-3.1-8b-instruct:free"}
    assert not dead & {c["model"] for c in vb._DEFAULT_AGENT_CONFIGS}
    # migration map phải phủ hết slug chết của 3 provider free
    assert ("groq", "llama-3.3-70b-versatile") in vb._MODEL_MIGRATIONS
    assert ("cerebras", "llama3.1-8b") in vb._MODEL_MIGRATIONS
    assert ("openrouter", "meta-llama/llama-3.3-70b-instruct:free") \
        in vb._MODEL_MIGRATIONS


def test_generate_brief_orders_by_strength_and_has_fallback():
    """Mirror nếp test_brief (inspect source): generate_brief phải (i) sắp
    agent theo sức mạnh TRƯỚC khi chạy, (ii) sắp results tất định trước khi
    trả, (iii) có nhánh dự phòng + alert khi mọi agent lỗi."""
    import inspect

    import vnstock_brief as vb
    src = inspect.getsource(vb.generate_brief)
    assert "_strength_sorted(agents)" in src
    assert src.index("_strength_sorted(agents)") < src.index("ThreadPoolExecutor")
    assert "(dự phòng)" in src
    assert "_brief_alert_down" in src


# ─── Output cụt = LỖI agent (close 06/08 06:53) ─────────────────────────────

def test_brief_agents_truncated_output_is_error(monkeypatch, _tmp_meta):
    """Gemini flash nghĩ ~5k token → content đứt giữa câu nhưng HTTP 200 →
    bản CỤT được tính thành công, thắng bản trọn vẹn của agent yếu hơn và
    lên Telegram thiếu 8 mục. Nay finish_reason=length / stop_reason=
    max_tokens = LỖI agent (ledger ghi fail) → cơ chế dự phòng kích hoạt."""
    import vnstock_brief as vb

    def _post_openai(url, headers=None, json=None, timeout=None):
        return _Resp({"choices": [{"message": {"content": "nửa chừng và chỉ"},
                                   "finish_reason": "length"}],
                      "usage": {"prompt_tokens": 9000, "completion_tokens": 700}})

    monkeypatch.setattr("requests.post", _post_openai)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    text, err = vb.GeminiAgent().generate("prompt", max_tokens=2800)
    assert text == "" and "bị cắt" in err
    assert ledger.summary()["providers"]["Gemini:gemini-3.5-flash"]["fail"] == 1

    def _post_claude(url, headers=None, json=None, timeout=None):
        return _Resp({"content": [{"text": "nửa chừng"}],
                      "stop_reason": "max_tokens",
                      "usage": {"input_tokens": 9000, "output_tokens": 700}})

    monkeypatch.setattr("requests.post", _post_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    text, err = vb.ClaudeAgent().generate("prompt", max_tokens=2800)
    assert text == "" and "bị cắt" in err


def test_gemini_think_headroom_not_regressed():
    import vnstock_brief as vb
    # 3000 đã chứng minh KHÔNG đủ (close 06/08) — không được tụt lại
    assert vb.GeminiAgent._THINK_HEADROOM >= 8000


# ─── Quét slug chết TOÀN REPO (nếp quy trình chốt 22/07) ────────────────────
# Provider khai tử model → thêm slug vào _DEAD_SLUGS + 1 dòng _MODEL_MIGRATIONS
# (vnstock_brief) + thay ladder tương ứng. Test này là KHÓA CỬA: slug chết
# lọt lại BẤT KỲ đâu trong code (kể cả điểm dùng model thêm sau này, miễn
# khai báo trong _all_live_slugs) → đỏ ngay ở run.py test --fast.

_DEAD_SLUGS_22_07 = {
    # Groq deprecated 17/06/2026 (còn phục vụ nhưng sẽ gỡ — cấm dùng mới)
    "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
    # Cerebras đã gỡ (probe 22/07: catalog chỉ còn 3 model)
    "llama3.3-70b", "llama-3.3-70b", "llama3.1-70b", "llama3.1-8b",
    "qwen-3-32b",
    # Cerebras sắp dep 17/08/2026
    "zai-glm-4.7",
    # OpenRouter hết bản :free (qwen-235b:free = zombie chờn vờn theo giờ)
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen3-235b-a22b:free", "openai/gpt-oss-120b:free",
    # 22/08/2026: probe model watch ra HTTP 404 "This model is unavailable
    # for free" + slug biến mất khỏi danh mục OpenRouter.
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-8b-instruct:free",
    # Gemini dòng 2.5 khóa với project mới (key máy này không gọi được)
    "gemini-2.5-flash", "gemini-2.5-flash-lite",
}


def _all_live_slugs() -> set:
    """Mọi slug đang HOẠT ĐỘNG trong code — điểm dùng model mới thêm sau
    này PHẢI khai báo vào đây để được quét."""
    import vnstock_auditor as va
    import vnstock_brief as vb
    import vnstock_classifier as vc
    import vnstock_news_feeds as nf
    import vnstock_report_digest as dg
    slugs = set()
    slugs |= set(vc._CLASSIFY_MODELS.values())                 # [8] classifier
    slugs.add(vc._CLASSIFY_MODEL_DEFAULT)                      # [8] opt-in trả phí
    slugs |= {p["model"] for p in snt._PROVIDERS}              # [1] sentiment
    slugs |= set(nf._ANALYZE_MODELS.values())                  # [2] chấm tin
    slugs.add(nf._ANALYZE_MODEL_DEFAULT)                       # [2] opt-in trả phí
    slugs |= set(dg._FREE_MODELS.values())                     # [3-5] digest bậc 1
    slugs |= {m for _, m in dg._FREE_TIER2}                    # [3-5] digest bậc 2
    slugs.add(dg._CLAUDE_MODEL)
    slugs.add(dg._OPENAI_MODEL)
    slugs.add(va.ClaudeAuditorAgent.DEFAULT_MODEL)             # [6] auditor trả phí
    slugs.add(va.GPTAuditorAgent.DEFAULT_MODEL)                # [6] (Free dùng lại
    #                                                           cascade digest ở trên)
    slugs |= {c["model"] for c in vb._DEFAULT_AGENT_CONFIGS}   # [7] brief defaults
    for _cls in vb.AGENT_REGISTRY.values():                    # [7] fallback nội bộ
        slugs |= set(getattr(_cls, "_MODEL_FALLBACKS", []) or [])
    slugs |= {cls().model for cls in vb.AGENT_REGISTRY.values()}  # [7] __init__ defaults
    return slugs


def test_no_dead_slug_anywhere_in_code():
    leaked = _DEAD_SLUGS_22_07 & _all_live_slugs()
    assert not leaked, f"slug chết lọt lại vào code: {sorted(leaked)}"


def test_probe_ladder_covers_all_free_live_slugs():
    """`probe_models.py --ladder` (health check 29/07) phải tự gom ĐỦ slug
    free đang dùng ở [1]-[8] — thêm điểm dùng model free mới mà _ladder_slugs
    không gom được là health check thiếu mắt. Hermetic: chỉ gom, không call."""
    import importlib.util
    from pathlib import Path

    import vnstock_brief as vb
    import vnstock_news_feeds as nf
    import vnstock_report_digest as dg

    path = Path(__file__).resolve().parent.parent / "scripts" / "probe_models.py"
    spec = importlib.util.spec_from_file_location("_probe_models_for_test", path)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)

    entries = pm._ladder_slugs()
    got = {(p, m) for p, m, _, _ in entries}

    assert all(p in pm._PROVIDERS for p, _ in got)      # chỉ 4 provider free
    assert not _DEAD_SLUGS_22_07 & {m for _, m in got}  # không probe slug chết
    # [1] sentiment đủ 4 nấc
    assert {(p["name"], p["model"]) for p in snt._PROVIDERS} <= got
    # [2] analyze + [3-6] digest cả 2 bậc
    assert {(p, m) for p, m in nf._ANALYZE_MODELS.items()} <= got
    assert {(p, m) for p, m in dg._FREE_MODELS.items()} <= got
    assert set(dg._FREE_TIER2) <= got
    # [7] brief: agent chính + fallback nội bộ Cerebras
    assert ("Gemini", "gemini-3.5-flash") in got
    assert {("Cerebras", m) for m in vb.CerebrasAgent._MODEL_FALLBACKS} <= got
    assert {("OpenRouter", m) for m in vb.OpenRouterAgent._MODEL_FALLBACKS} <= got
    assert {("Gemini", m) for m in vb.GeminiAgent._MODEL_FALLBACKS} <= got
    # [8] classifier — điểm dùng model THÊM SAU (07/08); quên khai vào
    # _ladder_slugs là health check mù đúng cái ladder chạy 1.700 mã
    import vnstock_classifier as vc
    assert {(p, m) for p, m in vc._CLASSIFY_MODELS.items()} <= got
    # tag điểm dùng phải có mặt để đọc output biết lỗi ở tính năng nào
    notes = {note for _, _, note, _ in entries}
    assert any("[1]" in n for n in notes) and any("[7]" in n for n in notes)
    assert any("[8]" in n for n in notes)


def test_probe_ladder_survives_broken_vnstock_sdk(capsys):
    """Công cụ chẩn đoán KHÔNG được chết vì thứ nó không chẩn đoán.

    `vnstock_classifier` kéo theo cả SDK vnstock + xác thực mạng (máy user
    07/08: `--ladder` in ra "Authentication successful ... golden"). Key data
    hết hạn / mạng lỗi mà làm `--ladder` chết là mất health check LLM đúng lúc
    cần nhất. Hỏng thì bỏ qua nấc [8] nhưng phải KÊU TO — nuốt im lặng là
    quay lại điểm mù vừa vá."""
    import importlib.util
    import sys as _sys
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "probe_models.py"
    spec = importlib.util.spec_from_file_location("_probe_broken_sdk", path)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)

    class _BrokenModule:                 # import được, đọc slug thì nổ
        def __getattr__(self, name):
            raise RuntimeError("vnstock auth failed: key expired")

    real = _sys.modules.get("vnstock_classifier")
    _sys.modules["vnstock_classifier"] = _BrokenModule()
    try:
        entries = pm._ladder_slugs()     # KHÔNG được raise
    finally:
        if real is not None:
            _sys.modules["vnstock_classifier"] = real
        else:
            _sys.modules.pop("vnstock_classifier", None)

    assert entries, "mất sạch ladder chỉ vì 1 module hỏng"
    notes = {n for _, _, n, _ in entries}
    assert any("[1]" in n for n in notes)          # các nấc khác vẫn probe
    assert not any("[8]" in n for n in notes)      # nấc [8] bị bỏ qua
    warn = capsys.readouterr().out
    assert "[8]" in warn and "classifier" in warn  # và phải kêu to
    assert "RuntimeError" in warn                  # kèm lý do để chẩn đoán


def test_classifier_slugs_are_watched_by_both_nets():
    """Lưới chỉ soi slug được KHAI BÁO. Hôm nay `_CLASSIFY_MODELS` trùng giá
    trị với `_ANALYZE_MODELS` nên có vẻ an toàn — nhưng đó là TRÙNG HỢP, không
    phải bảo vệ: đổi model chấm tin mà quên classifier là slug của batch 1.700
    mã lập tức thành điểm mù. Test này chốt classifier phải tự đứng trong lưới,
    độc lập với news_feeds."""
    import vnstock_classifier as vc
    live = _all_live_slugs()
    for slug in (*vc._CLASSIFY_MODELS.values(), vc._CLASSIFY_MODEL_DEFAULT):
        assert slug in live, f"slug [8] ngoài tầm quét slug chết: {slug}"


def test_migrations_targets_are_live_and_cover_dead_defaults():
    import vnstock_brief as vb
    # Đích migration KHÔNG được là slug chết (bài học entry cũ dead-to-dead:
    # cerebras llama-3.3-70b → llama3.3-70b, cả 2 đều đã bị gỡ)
    bad_targets = set(vb._MODEL_MIGRATIONS.values()) & _DEAD_SLUGS_22_07
    assert not bad_targets, f"migration trỏ về slug chết: {sorted(bad_targets)}"
    # Mọi slug chết TỪNG là default của brief phải có đường migration
    for key in (("groq", "llama-3.3-70b-versatile"),
                ("groq", "llama-3.1-8b-instant"),
                ("cerebras", "llama3.3-70b"),
                ("cerebras", "llama-3.3-70b"),
                ("openrouter", "meta-llama/llama-3.3-70b-instruct:free")):
        assert key in vb._MODEL_MIGRATIONS, f"thiếu migration cho {key}"
