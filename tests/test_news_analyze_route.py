"""Tests cho route chấm tin TRẢ PHÍ (TODO 1b — kích hoạt 21/07).

analyze_item ưu tiên Anthropic (nuance tốt hơn 70B free đang bịa chiều tác
động), lỗi/thiếu key/kill-switch → fallback ladder free y như cũ. Hermetic:
mọi network đều monkeypatch; fulltext tắt qua env.
"""

import vnstock_news_feeds as nf
import vnstock_sentiment as vs


def _ex(text, model="Fake:m", truncated=False):
    """Đáp án của `*_complete_ex`: dict kèm cờ provider-cắt. None = cạn/lỗi."""
    if text is None:
        return None
    return {"text": text, "model": model,
            "finish_reason": "max_tokens" if truncated else "end_turn",
            "truncated": truncated}


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _anthropic_body(text):
    return {"content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


# ── anthropic_complete (vnstock_sentiment) ─────────────────────────────────

def test_anthropic_complete_parses_text_blocks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    sent = {}

    def _post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, body=json)
        return _Resp(_anthropic_body("TÍCH_CỰC | Xuất khẩu hưởng lợi"))

    monkeypatch.setattr("requests.post", _post)
    out = vs.anthropic_complete("sys", "user text")
    assert out == "TÍCH_CỰC | Xuất khẩu hưởng lợi"
    assert sent["url"] == vs._ANTHROPIC_ENDPOINT
    assert sent["headers"]["x-api-key"] == "sk-test"
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    assert sent["body"]["system"] == "sys"
    assert sent["body"]["model"] == vs._ANTHROPIC_MODEL_DEFAULT
    # Opus 4.7+ bỏ sampling params (400) — request không được gửi temperature
    assert "temperature" not in sent["body"]


def test_anthropic_complete_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("requests.post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "không được gọi network khi thiếu key")))
    assert vs.anthropic_complete("s", "u") is None


def test_anthropic_complete_none_on_http_error_and_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp({}, status=500))
    assert vs.anthropic_complete("s", "u") is None
    monkeypatch.setattr("requests.post",
                        lambda *a, **k: _Resp({"content": []}))
    assert vs.anthropic_complete("s", "u") is None   # refusal/rỗng → fallback


def test_anthropic_complete_model_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    sent = {}

    def _post(url, headers=None, json=None, timeout=None):
        sent.update(body=json)
        return _Resp(_anthropic_body("TRUNG_LẬP | hai chiều"))

    monkeypatch.setattr("requests.post", _post)
    vs.anthropic_complete("s", "u", model="claude-opus-4-8")
    assert sent["body"]["model"] == "claude-opus-4-8"


def test_anthropic_complete_ex_retries_once_when_cut_at_max_tokens(monkeypatch):
    """Cùng lỗi với ladder free (close 08/09 "— tác động: Nh"): stop_reason
    "max_tokens" = bị cắt → gọi lại ĐÚNG MỘT lần với trần rộng gấp
    _TRUNCATE_RETRY_X; kết quả lần hai dừng tự nhiên → truncated=False."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(json["max_tokens"])
        if len(calls) == 1:
            return _Resp({**_anthropic_body("TRUNG_LẬP | Nh"),
                          "stop_reason": "max_tokens"})
        return _Resp({**_anthropic_body("TRUNG_LẬP | Nhóm điện tử chịu áp lực"),
                      "stop_reason": "end_turn"})

    monkeypatch.setattr("requests.post", _post)
    out = vs.anthropic_complete_ex("s", "u", max_tokens=120)
    assert calls == [120, 120 * vs._TRUNCATE_RETRY_X]
    assert out["text"] == "TRUNG_LẬP | Nhóm điện tử chịu áp lực"
    assert out["truncated"] is False and out["model"].startswith("Anthropic:")
    # wrapper cũ vẫn chỉ trả text
    calls.clear()
    assert vs.anthropic_complete("s", "u") == "TRUNG_LẬP | Nhóm điện tử chịu áp lực"


def test_anthropic_complete_ex_flags_a_cut_that_survives_the_retry(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    n = {"calls": 0}

    def _post(url, headers=None, json=None, timeout=None):
        n["calls"] += 1
        return _Resp({**_anthropic_body("TRUNG_LẬP | Nh"), "stop_reason": "max_tokens"})

    monkeypatch.setattr("requests.post", _post)
    out = vs.anthropic_complete_ex("s", "u", max_tokens=120)
    assert n["calls"] == 2                       # đúng MỘT lần gọi lại, không lặp vô hạn
    assert out["truncated"] is True and out["text"] == "TRUNG_LẬP | Nh"


# ── routing trong analyze_item (vnstock_news_feeds) ────────────────────────

def test_paid_route_wins_and_free_ladder_untouched(monkeypatch):
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "1")   # 22/07: opt-in, phải bật
    monkeypatch.delenv(nf._ANALYZE_MODEL_ENV, raising=False)
    seen = {}

    def _paid(system, user, max_tokens=120, model=None):
        seen["model"] = model
        return _ex("TIÊU_CỰC | Ngân hàng chịu áp lực NIM", model=f"Anthropic:{model}")

    monkeypatch.setattr("vnstock_sentiment.anthropic_complete_ex", _paid)
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "ladder free không được gọi khi paid trả kết quả")))
    s, imp = nf.analyze_item({"title": "Lãi suất tăng"})
    assert s == "negative"
    assert imp == "Ngân hàng chịu áp lực NIM"
    # route trả phí (khi opt-in) vẫn mặc định Opus; env override được
    assert seen["model"] == nf._ANALYZE_MODEL_DEFAULT == "claude-opus-4-8"


def test_paid_route_falls_back_to_free_ladder(monkeypatch):
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "1")
    monkeypatch.setattr("vnstock_sentiment.anthropic_complete_ex",
                        lambda *a, **k: None)                 # lỗi/thiếu key
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TÍCH_CỰC | Dệt may thêm lợi thế"))
    s, imp = nf.analyze_item({"title": "Đối thủ bị áp thuế"})
    assert s == "positive"
    assert imp == "Dệt may thêm lợi thế"


def test_paid_route_kill_switch(monkeypatch):
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "0")
    monkeypatch.setattr("vnstock_sentiment.anthropic_complete_ex",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "kill-switch bật mà vẫn gọi route trả phí")))
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TRUNG_LẬP | hai chiều"))
    s, _imp = nf.analyze_item({"title": "Margin kỷ lục"})
    assert s == "neutral"


def test_paid_switch_values():
    assert nf._paid_analyze_enabled() in (True, False)  # smoke — chi tiết dưới


def test_paid_switch_parsing(monkeypatch):
    # đảo mặc định 22/07 (free-first): unset/rỗng/0 = TẮT, bật phải tường minh
    for v, want in (("0", False), ("false", False), ("off", False),
                    ("", False), ("1", True), ("true", True),
                    ("on", True), ("yes", True)):
        monkeypatch.setenv(nf._ANALYZE_PAID_ENV, v)
        assert nf._paid_analyze_enabled() is want, v
    monkeypatch.delenv(nf._ANALYZE_PAID_ENV, raising=False)
    assert nf._paid_analyze_enabled() is False


def test_default_free_first_skips_paid_route(monkeypatch):
    """Mặc định (không set env) → đi thẳng ladder free, KHÔNG gọi Anthropic."""
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    monkeypatch.delenv(nf._ANALYZE_PAID_ENV, raising=False)
    monkeypatch.setattr("vnstock_sentiment.anthropic_complete_ex",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "free-first mà vẫn gọi route trả phí")))
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TÍCH_CỰC | Dầu khí hưởng lợi"))
    s, imp = nf.analyze_item({"title": "Giá dầu tăng"})
    assert s == "positive" and imp == "Dầu khí hưởng lợi"


def test_analyze_models_slugs_22_07():
    """Guard chống lùi về slug chết (llama 70B deprecated/gỡ, qwen-235b:free
    zombie) — map override phải đúng bộ probe sống 22/07."""
    assert nf._ANALYZE_MODELS == {
        "Gemini": "gemini-3.5-flash",
        "Groq": "qwen/qwen3.6-27b",
        "OpenRouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    }


# ── prompt chống 3 lỗi quan sát 20-21/07 ───────────────────────────────────

def test_analyze_prompt_has_new_neutral_anchors():
    p = nf._ANALYZE_SYSTEM
    assert "KHÔNG SUY DIỄN NGƯỢC NỘI DUNG" in p       # vụ kim cương → PNJ
    assert "HAI CHIỀU" in p and "KỶ LỤC" in p          # vụ margin kỷ lục 🟢
    assert "nước KHÁC" in p and "cạnh tranh" in p      # vụ thuế Canada ngược chiều
    assert "KHÔNG ÉP CHIỀU" in p                       # nới luật ép kênh
