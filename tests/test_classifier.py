"""Tests cho điểm [8] — đường LLM của vnstock_classifier (free-first).

Trước 07/08: `_call_claude` RAISE khi thiếu ANTHROPIC_API_KEY → batch ~1.700
mã chết ngay mã đầu tiên, máy all-free không chạy được classifier. Nay mirror
đúng route đã dùng cho chấm tin (`vnstock_news_feeds`): ladder FREE mặc định
(Gemini 3.5-flash dẫn đầu — slug probe sống cho điểm [8]), Claude thành
OPT-IN qua `VNSTOCK_CLASSIFY_PAID=1`.

Hermetic: không test nào chạm network — mọi nấc LLM đều monkeypatch. Import
module THẬT (không replica) — bài học audit 06/08 về test trôi xa bản thật.
"""

import json

import pytest

import vnstock_classifier as vc


# ── Công tắc opt-in ──────────────────────────────────────────────────────────

def test_paid_switch_defaults_off(monkeypatch):
    """Có key Anthropic KHÔNG đủ để bật route trả phí — batch 1.700 mã tự ý
    tiêu tiền là hồi quy đắt, phải bật tường minh."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    assert vc._paid_classify_enabled() is False


def test_paid_switch_parsing(monkeypatch):
    for v, want in (("0", False), ("false", False), ("off", False),
                    ("", False), ("1", True), ("true", True),
                    ("on", True), ("yes", True)):
        monkeypatch.setenv(vc._CLASSIFY_PAID_ENV, v)
        assert vc._paid_classify_enabled() is want, v


def test_classify_models_are_probed_slugs():
    """Guard chống lùi về slug chết. Bộ này = bộ đã probe sống 22/07 và đang
    chạy thật ở route chấm tin; `gemini-3.5-flash` chính là ứng viên ghi cho
    điểm [8] trong scripts/probe_models.py."""
    assert vc._CLASSIFY_MODELS == {
        "Gemini": "gemini-3.5-flash",
        "Groq": "qwen/qwen3.6-27b",
        "OpenRouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    }


# ── Định tuyến free / paid ───────────────────────────────────────────────────

def test_free_ladder_used_when_no_anthropic_key(monkeypatch):
    """Bug gốc của điểm [8]: thiếu key là CRASH. Nay phải chạy bình thường."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: ("{}", "Gemini:gemini-3.5-flash"))
    text, model = vc._call_llm("prompt")
    assert text == "{}"
    assert model == "Gemini:gemini-3.5-flash"


def test_default_free_first_never_touches_claude(monkeypatch):
    """Mặc định đi thẳng ladder free — kể cả khi máy CÓ key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr(vc, "_call_claude",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "free-first mà vẫn gọi route trả phí")))
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: ("ok", "Groq:qwen/qwen3.6-27b"))
    assert vc._call_llm("prompt")[0] == "ok"


def test_paid_route_used_when_opted_in(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv(vc._CLASSIFY_PAID_ENV, "1")
    monkeypatch.delenv(vc._CLASSIFY_MODEL_ENV, raising=False)
    seen = {}

    def _paid(prompt, model=None, max_tokens=800):
        seen["model"] = model
        return "paid answer"

    monkeypatch.setattr(vc, "_call_claude", _paid)
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "paid trả kết quả rồi còn gọi ladder free")))
    text, model = vc._call_llm("prompt")
    assert text == "paid answer"
    assert seen["model"] == vc._CLASSIFY_MODEL_DEFAULT
    assert model == vc._CLASSIFY_MODEL_DEFAULT


def test_paid_route_falls_back_to_free_on_failure(monkeypatch):
    """Key hết hạn / API 500 giữa batch 1.700 mã → rơi xuống free, không chết."""
    monkeypatch.setenv(vc._CLASSIFY_PAID_ENV, "1")
    monkeypatch.setattr(vc, "_call_claude",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("HTTP 529 overloaded")))
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: ("free answer", "Gemini:gemini-3.5-flash"))
    text, model = vc._call_llm("prompt")
    assert text == "free answer"
    assert model == "Gemini:gemini-3.5-flash"


def test_paid_model_override_via_env(monkeypatch):
    monkeypatch.setenv(vc._CLASSIFY_PAID_ENV, "1")
    monkeypatch.setenv(vc._CLASSIFY_MODEL_ENV, "claude-opus-4-8")
    seen = {}
    monkeypatch.setattr(vc, "_call_claude",
                        lambda prompt, model=None, max_tokens=800:
                        (seen.update(model=model), "x")[1])
    assert vc._call_llm("prompt")[1] == "claude-opus-4-8"
    assert seen["model"] == "claude-opus-4-8"


def test_free_ladder_gets_probed_model_map(monkeypatch):
    """Ladder phải được truyền model_map — không truyền là rơi về flash-lite
    mặc định của sentiment (yếu hơn cho việc phân loại 32 nhóm ngành)."""
    seen = {}

    def _chat(system, user, max_tokens=80, model_map=None, with_model=False):
        seen.update(system=system, user=user, model_map=model_map,
                    with_model=with_model)
        return ("{}", "Gemini:gemini-3.5-flash")

    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr("vnstock_sentiment.chat_complete", _chat)
    vc._call_llm("PROMPT BODY")
    assert seen["model_map"] == vc._CLASSIFY_MODELS
    assert seen["with_model"] is True
    # chỉ dẫn ổn định làm system, dữ liệu biến thiên làm user
    assert seen["system"] == vc._CLASSIFY_SYSTEM
    assert seen["user"] == "PROMPT BODY"


def test_raises_actionable_error_when_every_rung_dead(monkeypatch):
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: (None, ""))
    with pytest.raises(RuntimeError) as e:
        vc._call_llm("prompt")
    msg = str(e.value)
    assert "GEMINI_API_KEY" in msg          # chỉ đúng đường sửa
    assert vc._CLASSIFY_PAID_ENV in msg


def test_empty_answer_is_not_reported_as_dry_ladder(monkeypatch):
    """Nấc CÓ trả lời nhưng rỗng (refusal/bị cắt) ≠ cạn thang. Phải trả về
    kèm tên nấc để chẩn đoán đúng, không raise "không key nào chạy được"."""
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: ("", "Gemini:gemini-3.5-flash"))
    text, used = vc._call_llm("prompt")
    assert text == ""
    assert used == "Gemini:gemini-3.5-flash"


def test_claude_path_still_reports_missing_key(monkeypatch):
    """`_call_claude` giữ nguyên hợp đồng cũ (raise khi thiếu key) — nó chỉ
    không còn là đường DUY NHẤT."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        vc._call_claude("prompt")


# ── Parse: phân biệt "model hỏng" với "model bảo Khác" ───────────────────────

def _valid_payload(primary="Ngân hàng"):
    return json.dumps({"primary_industry": primary,
                       "secondary_industries": [],
                       "revenue_breakdown": {primary: "~100%"},
                       "business_summary": "Ngân hàng thương mại."},
                      ensure_ascii=False)


def test_parse_returns_none_when_no_json():
    assert vc._parse_classification("xin lỗi tôi không thể") is None


def test_parse_returns_none_on_broken_json():
    assert vc._parse_classification('{"primary_industry": "Ngân hàng"') is None


def test_parse_keeps_khac_for_industry_outside_list():
    """"Khác" do model TRẢ LỜI là kết quả hợp lệ — khác hẳn model hỏng."""
    out = vc._parse_classification(_valid_payload("Ngành Bịa Đặt"))
    assert out is not None
    assert out["primary_industry"] == "Khác"


def test_parse_filters_invalid_secondary_industries():
    raw = json.dumps({"primary_industry": "Ngân hàng",
                      "secondary_industries": ["Bảo hiểm", "Ngành Ma"],
                      "revenue_breakdown": {},
                      "business_summary": ""}, ensure_ascii=False)
    out = vc._parse_classification(raw)
    assert json.loads(out["secondary_industries"]) == ["Bảo hiểm"]


def test_parse_survives_markdown_fence():
    """Model free hay bọc ```json — không được tính là hỏng."""
    out = vc._parse_classification("```json\n" + _valid_payload() + "\n```")
    assert out is not None and out["primary_industry"] == "Ngân hàng"


# ── run_classify: không đóng băng kết quả hỏng ───────────────────────────────

class _StubWarehouse:
    """Chỉ cần load_profile — run_classify nhận tickers_override nên không
    đụng tới companies_dir."""

    def load_profile(self, ticker):
        return {"ticker": ticker, "company_name": f"CTCP {ticker}",
                "sector_icb": "Banks", "exchange": "HOSE",
                "profile": "Ngân hàng thương mại cổ phần.",
                "revenue_str": ""}


def _store(tmp_path):
    return vc.ClassificationStore(str(tmp_path))


def test_unparseable_response_is_not_stored(tmp_path, monkeypatch):
    """Cùng họ bug với sentiment đóng băng "neutral" (fix 07/08): ghi kết quả
    RÁC vào kho là đóng băng vĩnh viễn — `is_classified` chặn lần chấm sau.
    Model trả rác → coi như lỗi, để mã đó chấm lại lần chạy tới."""
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    monkeypatch.setattr(vc, "_call_llm", lambda *a, **k: ("rác không JSON", "X:y"))
    store = _store(tmp_path)
    vc.run_classify(_StubWarehouse(), store, delay=0, tickers_override=["VCB"])
    assert store.all().empty
    assert not store.is_classified("VCB")


def test_valid_response_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "_call_llm",
                        lambda *a, **k: (_valid_payload(), "X:y"))
    store = _store(tmp_path)
    vc.run_classify(_StubWarehouse(), store, delay=0, tickers_override=["VCB"])
    assert store.is_classified("VCB")
    assert store.get("VCB")["primary_industry"] == "Ngân hàng"


def test_stored_model_is_the_one_that_answered(tmp_path, monkeypatch):
    """Cột `model` phải ghi nấc THẬT đã trả lời — ghi mặc định CLI là nói dối
    sổ sách, hết soi được chất lượng theo model về sau."""
    monkeypatch.setattr(vc, "_call_llm",
                        lambda *a, **k: (_valid_payload(),
                                         "Gemini:gemini-3.5-flash"))
    store = _store(tmp_path)
    vc.run_classify(_StubWarehouse(), store, delay=0, tickers_override=["VCB"])
    assert store.get("VCB")["model"] == "Gemini:gemini-3.5-flash"


def test_end_to_end_without_anthropic_key(tmp_path, monkeypatch):
    """Bug gốc điểm [8], dựng lại NGUYÊN chuỗi: chỉ fake `requests.post`, đi
    qua `chat_complete` thật. Trước fix: EnvironmentError ngay mã đầu tiên."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(vc._CLASSIFY_PAID_ENV, raising=False)
    for env in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": _valid_payload()}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def _post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, model=json["model"])
        return _Resp()

    monkeypatch.setattr("requests.post", _post)
    store = _store(tmp_path)
    vc.run_classify(_StubWarehouse(), store, delay=0, tickers_override=["VCB"])

    assert store.get("VCB")["primary_industry"] == "Ngân hàng"
    assert store.get("VCB")["model"] == "Gemini:gemini-3.5-flash"
    assert "generativelanguage.googleapis.com" in seen["url"]
    assert seen["model"] == "gemini-3.5-flash"


def test_llm_failure_does_not_abort_the_batch(tmp_path, monkeypatch):
    """1.700 mã: một mã lỗi không được làm chết cả batch."""
    calls = {"n": 0}

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mọi nấc model free đều lỗi")
        return (_valid_payload(), "Gemini:gemini-3.5-flash")

    monkeypatch.setattr(vc, "_call_llm", _flaky)
    store = _store(tmp_path)
    vc.run_classify(_StubWarehouse(), store, delay=0,
                    tickers_override=["AAA", "VCB"])
    assert not store.is_classified("AAA")
    assert store.is_classified("VCB")
