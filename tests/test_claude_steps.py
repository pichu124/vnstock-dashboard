"""#26 (30/09): Claude Code cho 4 bước LLM còn lại — nấc `claude-cli` đầu
cascade digest (reflection / audit / debate), sentiment + chấm tin theo LÔ,
lead strategy loop, `ClaudeCodeAgent` trong ladder brief. Hermetic:
`vnstock_claude_cli.complete` giả, .env không đọc."""
from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path

import pytest

import vnstock_claude_cli as vcc

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setattr(vcc, "_ENV_LOADED", True)
    for k in ("VNSTOCK_LLM_ENGINE", *vcc.STEP_ENGINE_ENV.values(),
              "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VNSTOCK_CLAUDE_CLI_MODEL",
              "VNSTOCK_NEWS_CLI_MODEL", "VNSTOCK_AUDIT_CLI_TIMEOUT_S",
              "VNSTOCK_NEWS_CLI_TIMEOUT_S", "VNSTOCK_CLAUDE_CLI_EXE",
              "VNSTOCK_BRIEF_CLI_EXE"):
        monkeypatch.delenv(k, raising=False)


def _fake_complete(monkeypatch, text, err=None, structured=None, model="claude-opus-5-5"):
    calls: list[dict] = []

    def _c(user, **kw):
        calls.append({"user": user, **kw})
        info = {"model": model, "elapsed_s": 1.0}
        if structured is not None:
            info["structured"] = structured
        return text, err, info
    monkeypatch.setattr(vcc, "complete", _c)
    return calls


# ─── digest cascade: nấc claude-cli ──────────────────────────────────────────

def _digest(monkeypatch, free_text="FREE"):
    import vnstock_report_digest as dg
    monkeypatch.setattr(dg, "_ensure_env_loaded", lambda: None)
    monkeypatch.setattr(dg, "_free_ladder", lambda: [("Gemini", "m", 100)])
    free_calls: list = []
    monkeypatch.setattr(dg, "_call_free",
                        lambda p, m, s, u, max_tokens=0: free_calls.append(u) or free_text)
    return dg, free_calls


def test_digest_call_puts_claude_cli_first_when_engine_claude(monkeypatch):
    dg, free_calls = _digest(monkeypatch)
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    calls = _fake_complete(monkeypatch, '{"ok": 1}')
    raw, prov = dg.digest_call("SYS", "USR", step="audit")
    assert (raw, prov) == ('{"ok": 1}', "claude-cli")
    assert free_calls == []                                   # free không chạy
    c = calls[0]
    assert c["user"] == "USR" and c["system"] == "SYS" and c["tag"] == "audit"
    assert c["timeout_s"] == dg._CLI_TIMEOUT_S and c["model"] == "claude-opus-5-5"


def test_digest_call_step_override_and_ladder_default(monkeypatch):
    dg, free_calls = _digest(monkeypatch)
    calls = _fake_complete(monkeypatch, "X")
    assert dg.digest_call("S", "U") == ("FREE", "Gemini:m")   # mặc định ladder
    assert calls == []
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    monkeypatch.setenv("VNSTOCK_REFLECTION_ENGINE", "ladder")  # riêng bước đè chung
    assert dg.digest_call("S", "U", step="reflection") == ("FREE", "Gemini:m")
    assert calls == []
    assert dg.digest_call("S", "U", step="digest") == ("X", "claude-cli")
    assert len(calls) == 1 and calls[0]["tag"] == "digest"


def test_digest_call_cli_error_falls_to_next_rung(monkeypatch):
    dg, free_calls = _digest(monkeypatch)
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    _fake_complete(monkeypatch, "", err="claude CLI quá 300s — bỏ")
    assert dg.digest_call("S", "U", step="reflection") == ("FREE", "Gemini:m")
    assert free_calls == ["U"]


def test_digest_call_accept_gates_cli_then_self_fix_then_next(monkeypatch):
    dg, free_calls = _digest(monkeypatch, free_text='{"b": 2}')
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    calls = _fake_complete(monkeypatch, "không phải json")
    raw, prov = dg.digest_call("S", "U", accept=lambda r: r.startswith("{"),
                               feedback=lambda r: "thiếu JSON", step="audit")
    assert (raw, prov) == ('{"b": 2}', "Gemini:m")
    assert len(calls) == 2 and "OUTPUT TRƯỚC" in calls[1]["user"]   # 1 lượt tự sửa


def test_digest_cli_timeout_env_override(monkeypatch):
    dg, _ = _digest(monkeypatch)
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    monkeypatch.setenv("VNSTOCK_AUDIT_CLI_TIMEOUT_S", "45")
    calls = _fake_complete(monkeypatch, "{}")
    dg.digest_call("S", "U", step="audit")
    assert calls[0]["timeout_s"] == 45


# ─── reflection / audit đi qua cascade với đúng `step` ──────────────────────

def test_reflect_call_tags_step_reflection(monkeypatch):
    import vnstock_reflection as rf
    import vnstock_report_digest as dg
    seen: dict = {}
    monkeypatch.setattr(dg, "digest_call",
                        lambda s, u, **kw: seen.update(kw=kw) or ("LESSON", "claude-cli"))
    assert rf._reflect_call("S", "U") == "LESSON"
    assert seen["kw"] == {"step": "reflection"}


def test_make_auditor_auto_prefers_free_cascade_when_engine_claude(monkeypatch):
    import vnstock_auditor as va
    monkeypatch.setattr(va, "_ensure_env_loaded", lambda: None)
    for k in va._FREE_KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    assert isinstance(va.make_auditor("auto"), va.NullAuditorAgent)
    monkeypatch.setenv("VNSTOCK_AUDIT_ENGINE", "claude")
    assert isinstance(va.make_auditor("auto"), va.FreeAuditorAgent)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")        # engine claude thắng cả key API
    assert isinstance(va.make_auditor("auto"), va.FreeAuditorAgent)
    assert isinstance(va.make_auditor("claude"), va.ClaudeAuditorAgent)   # ép vẫn ép


def test_free_auditor_passes_step_audit_and_labels_backend(monkeypatch):
    import vnstock_auditor as va
    import vnstock_report_digest as dg
    seen: dict = {}
    raw = '{"approved": true, "confidence": 0.9, "issues": [], "suggestions": []}'
    monkeypatch.setattr(dg, "digest_call",
                        lambda s, u, accept=None, feedback=None, **kw:
                        seen.update(kw=kw) or (raw, "claude-cli"))
    v = va.FreeAuditorAgent().audit({"rsi": 50}, context="t")
    assert v.approved is True and v.backend == "free:claude-cli"
    assert seen["kw"] == {"step": "audit"}


# ─── sentiment theo lô ───────────────────────────────────────────────────────

def _news():
    return [{"ticker": "VCB", "news_title": "VCB lãi kỷ lục", "_date_sort": "2026-09-30",
             "news_short_content": "Lợi nhuận tăng 20%"},
            {"ticker": "HPG", "news_title": "HPG giảm giá thép", "_date_sort": "2026-09-30"},
            {"ticker": "FPT", "news_title": "FPT ký hợp đồng", "_date_sort": "2026-09-30"}]


def test_score_batch_cli_maps_index_to_hash_and_drops_junk(monkeypatch):
    import vnstock_sentiment as snt
    items = _news()
    structured = {"results": [{"i": 0, "sentiment": "TÍCH_CỰC"},
                              {"i": 1, "sentiment": "lạ"},
                              {"i": 7, "sentiment": "TIÊU_CỰC"},
                              {"i": "2", "sentiment": "neutral"}]}
    calls = _fake_complete(monkeypatch, json.dumps(structured), structured=structured)
    got = snt.score_batch_cli(items)
    assert got == {snt._item_hash(items[0]): ("positive", "ClaudeCode:claude-opus-5-5"),
                   snt._item_hash(items[2]): ("neutral", "ClaudeCode:claude-opus-5-5")}
    c = calls[0]
    payload = json.loads(c["user"].split("\n", 1)[1])
    assert payload[0] == {"i": 0, "ma": "VCB", "tieu_de": "VCB lãi kỷ lục",
                          "tom_tat": "Lợi nhuận tăng 20%"}
    assert c["json_schema"] == snt._BATCH_SCHEMA and c["tag"] == "news"
    assert "schema" in c["system"] and "1 từ" not in c["system"]
    assert c["timeout_s"] == snt._CLI_TIMEOUT_S


def test_score_batch_cli_error_gives_nothing(monkeypatch):
    import vnstock_sentiment as snt
    _fake_complete(monkeypatch, "", err="không thấy claude")
    assert snt.score_batch_cli(_news()) == {}


def test_score_news_batch_uses_cli_then_ladder_for_the_rest(tmp_path, monkeypatch):
    import vnstock_sentiment as snt
    db = tmp_path / "s.db"
    monkeypatch.setattr(snt, "SENTIMENT_DB_PATH", db)
    monkeypatch.setenv("VNSTOCK_NEWS_ENGINE", "claude")
    items = _news()
    structured = {"results": [{"i": 0, "sentiment": "TÍCH_CỰC"},
                              {"i": 2, "sentiment": "TRUNG_LẬP"}]}
    _fake_complete(monkeypatch, json.dumps(structured), structured=structured)
    ladder: list = []
    monkeypatch.setattr(snt, "score_one",
                        lambda item: ladder.append(item["ticker"]) or
                        (snt._item_hash(item), "negative", "Gemini"))
    out = snt.score_news_batch(items)
    h = [snt._item_hash(i) for i in items]
    assert out == {h[0]: "positive", h[1]: "negative", h[2]: "neutral"}
    assert ladder == ["HPG"]                                    # chỉ tin thiếu qua ladder
    rows = dict((r[0], r[1]) for r in sqlite3.connect(str(db)).execute(
        "SELECT item_hash, model FROM news_sentiment").fetchall())
    assert rows == {h[0]: "ClaudeCode:claude-opus-5-5", h[1]: "Gemini",
                    h[2]: "ClaudeCode:claude-opus-5-5"}

    # engine ladder: lô CLI không được gọi
    monkeypatch.setenv("VNSTOCK_NEWS_ENGINE", "ladder")
    monkeypatch.setattr(snt, "score_batch_cli",
                        lambda items: (_ for _ in ()).throw(AssertionError("CLI chạy dù ladder")))
    extra = [{"ticker": "MWG", "news_title": "MWG mới", "_date_sort": "2026-09-30"}]
    out2 = snt.score_news_batch(extra)               # trả cả cache cũ + tin mới
    assert out2[snt._item_hash(extra[0])] == "negative" and ladder[-1] == "MWG"


def test_cli_engine_label_and_news_gate(monkeypatch):
    import vnstock_sentiment as snt
    import run as runpy
    assert snt.cli_engine_label() is None
    monkeypatch.setenv("VNSTOCK_LLM_ENGINE", "claude")
    assert snt.cli_engine_label() == "Claude Code (CLI)"
    src = inspect.getsource(runpy.cmd_news)
    assert "available_provider() or _snt.cli_engine_label()" in src


# ─── chấm tin RSS theo lô ────────────────────────────────────────────────────

def test_analyze_items_cli_parses_labels_and_sanitizes_impact(monkeypatch):
    import vnstock_news_feeds as nf
    monkeypatch.setattr(nf, "_fulltext_enabled", lambda: False)
    structured = {"results": [
        {"i": 0, "nhan": "TÍCH_CỰC", "tac_dong": "<b>PNJ hưởng lợi</b>\n từ giá vàng"},
        {"i": 1, "nhan": "TRUNG_LẬP", "tac_dong": ""},
        {"i": 9, "nhan": "TIÊU_CỰC", "tac_dong": "x"}]}
    calls = _fake_complete(monkeypatch, json.dumps(structured), structured=structured)
    got = nf.analyze_items_cli([{"title": "Vàng tăng", "news_short_content": "tóm"},
                                {"title": "Tin 2"}])
    assert list(got) == [0] and got[0][0] == "positive"
    assert "PNJ hưởng lợi" in got[0][1] and "<b>" not in got[0][1] and "\n" not in got[0][1]
    c = calls[0]
    assert "### Tin i=0\nTiêu đề: Vàng tăng\nTóm tắt: tóm" in c["user"]
    assert "### Tin i=1\nTiêu đề: Tin 2" in c["user"]
    assert c["system"].startswith(nf._ANALYZE_SYSTEM) and "CHẾ ĐỘ LÔ" in c["system"]
    assert c["json_schema"] == nf._ANALYZE_BATCH_SCHEMA and c["tag"] == "news"
    assert nf.analyze_items_cli([]) == {}
    _fake_complete(monkeypatch, "", err="lỗi")
    assert nf.analyze_items_cli([{"title": "x"}]) == {}


def test_refresh_uses_cli_batch_then_ladder_for_the_rest(tmp_path, monkeypatch):
    import vnstock_news_feeds as nf
    monkeypatch.setattr(nf, "_CACHE", tmp_path / "market_news_cache.json")
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u"}])
    monkeypatch.setattr(nf, "_is_relevant", lambda it: True)
    items = [{"title": "Fed giữ lãi suất", "link": "http://a/1", "source": "A",
              "_date_sort": "2026-09-30", "news_short_content": "", "_sentiment": "", "_impact": ""},
             {"title": "SBV bơm ròng", "link": "http://a/2", "source": "A",
              "_date_sort": "2026-09-30", "news_short_content": "", "_sentiment": "", "_impact": ""}]
    monkeypatch.setattr(nf, "fetch_feed", lambda feed: [dict(i) for i in items])
    import datetime as _dt

    class _D(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 30)
    monkeypatch.setattr(nf, "_date", _D)
    monkeypatch.setenv("VNSTOCK_NEWS_ENGINE", "claude")
    monkeypatch.setattr(nf, "analyze_items_cli",
                        lambda todo: {i: ("positive", "CLI impact") for i, it in enumerate(todo)
                                      if "Fed" in it["title"]})
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("neutral", "ladder impact"))
    out = {it["title"]: it["_impact"] for it in nf.refresh(within_days=5, analyze=True)}
    assert out == {"Fed giữ lãi suất": "CLI impact", "SBV bơm ròng": "ladder impact"}


# ─── strategy loop: Claude Code làm lead ─────────────────────────────────────

def test_inject_claude_lead(monkeypatch):
    import vnstock_brief as vb
    import vnstock_train as vt
    g = vb.GeminiAgent()
    assert vt._inject_claude_lead([g], verbose=False) == [g]           # engine ladder
    monkeypatch.setenv("VNSTOCK_TRAIN_ENGINE", "claude")
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    assert vt._inject_claude_lead([g], verbose=False) == [g]           # không có CLI
    monkeypatch.setattr(vcc, "cli_executable", lambda: "/fake/claude")
    got = vt._inject_claude_lead([g], verbose=False)
    assert got[0].agent_type == "claude-code" and got[0].tag == "train" and got[1] is g
    assert vt._inject_claude_lead([], verbose=False)[0].agent_type == "claude-code"
    src = inspect.getsource(vt.strategy_loop)
    assert src.index("_inject_claude_lead(") < src.index("if not available:")


# ─── ClaudeCodeAgent trong ladder ────────────────────────────────────────────

def test_claude_code_agent_registry_default_off_and_strongest(monkeypatch):
    import vnstock_brief as vb
    assert vb.AGENT_REGISTRY["claude-code"] is vb.ClaudeCodeAgent
    cfg = next(c for c in vb._DEFAULT_AGENT_CONFIGS if c["type"] == "claude-code")
    assert cfg["enabled"] is False and cfg["model"] == vcc.DEFAULT_MODEL
    agents = [vb.GeminiAgent(), vb.ClaudeCodeAgent(), vb.OpenRouterAgent()]
    assert [a.agent_type for a in vb._strength_sorted(agents)] == \
        ["claude-code", "gemini", "openrouter"]
    monkeypatch.setattr(vcc, "cli_executable", lambda: None)
    assert vb.ClaudeCodeAgent().is_available is False
    monkeypatch.setattr(vcc, "cli_executable", lambda: "/x")
    assert vb.ClaudeCodeAgent().is_available is True
    assert vb.ClaudeCodeAgent().name == "Claude Code · opus-5-5"


def test_claude_code_agent_generate_goes_through_complete(monkeypatch):
    import vnstock_brief as vb
    calls = _fake_complete(monkeypatch, "TEXT")
    a = vb.ClaudeCodeAgent(tag="train")
    assert a.generate("PROMPT", max_tokens=2000) == ("TEXT", None)
    c = calls[0]
    assert c["user"] == "PROMPT" and c["tag"] == "train"
    assert c["system"] == vb.ClaudeCodeAgent._SYSTEM and c["model"] == "claude-opus-5-5"
    _fake_complete(monkeypatch, "", err="claude CLI quá 600s — bỏ")
    assert a.generate("P") == ("", "claude CLI quá 600s — bỏ")


def test_dashboard_agent_settings_checks_is_available_for_keyless_agents():
    src = (_REPO / "dashboard" / "brief_agent_settings.py").read_text(encoding="utf-8")
    assert "_cls().is_available" in src
