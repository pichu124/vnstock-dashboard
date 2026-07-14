"""Tests for vnstock_report_digest — Phase 3: digest LLM + cross-check + tilt.

Hermetic: reports store trỏ tmp_path (fixture), LLM call monkeypatch (không
mạng/không key), registry macro là fixture list. Phần tilt tích hợp
vnstock_allocation cũng test ở đây (fake consensus qua sys.modules).
"""
import json
import sys
import types
from datetime import date, timedelta

import pytest

import vnstock_allocation as alloc
import vnstock_report_digest as dg
import vnstock_reports as rp


_TEXT = ("Báo cáo chiến lược: CPI kiểm soát, lãi suất điều hành giữ 4.5%, "
         "ưu tiên cổ phiếu chọn lọc, thận trọng USD. " * 10)

_RAW_OK = """Đây là digest:
```json
{"tom_tat": "## Vĩ mô ổn định 达到, ưu tiên cổ phiếu. 🎯",
 "stance": {"Cổ phiếu": 1.6, "Trái phiếu": 0, "Vàng": -3, "USD": "x"},
 "claims": [
   {"key": "sbv_policy_rate", "value": 4.5, "unit": "%/năm", "period": "2026-07", "text": "SBV giữ 4.5%"},
   {"key": "usdvnd", "value": 27500, "unit": "VND", "period": "2026-07", "text": "tỷ giá 27,500"},
   {"key": "khac", "value": 12.3, "unit": "%", "period": "2026", "text": "tăng trưởng tín dụng"},
   {"key": "pmi", "value": "n/a", "period": "?", "text": "không phải số"}],
 "risks": ["Tỷ giá vượt đỉnh ##", "  "]}
```"""

_MACRO = [
    {"key": "sbv_policy_rate", "value": 4.5, "as_of": "2023-06-19"},
    {"key": "usdvnd", "value": 26200.0, "as_of": "2026-07-11"},
    {"key": "pmi", "value": 50.5, "as_of": "2026-07-01"},
]


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_INDEX", tmp_path / "reports_index.json")
    monkeypatch.setattr(rp, "_STORE", tmp_path / "reports")
    monkeypatch.setattr(alloc, "_STATE", tmp_path / "allocation_state.json")
    monkeypatch.setattr(alloc, "_CONFIG", tmp_path / "allocation_config.json")


def _add_report(days_old=3, source="SSI", text=_TEXT):
    d = (date.today() - timedelta(days=days_old)).isoformat()
    return rp.add_text(text, report_date=d, source=source)


# ── sanitize ─────────────────────────────────────────────────────────────────


def test_sanitize_strips_structure_breakers():
    out = dg.sanitize_text("## Mục 🎯 vĩ mô 达到 tốt\nxuống  dòng")
    assert "#" not in out and "🎯" not in out and "达" not in out
    assert "\n" not in out
    assert "Mục vĩ mô tốt xuống dòng" == out
    # số EN giữ nguyên
    assert dg.sanitize_text("CPI 4.69% — 26,200 VND") == "CPI 4.69% — 26,200 VND"


# ── parse_digest ─────────────────────────────────────────────────────────────


def test_parse_digest_validates_and_sanitizes():
    d = dg.parse_digest(_RAW_OK)
    assert d is not None
    # stance: float → int, clamp -2..2, thiếu lớp → 0, rác → 0
    assert d["stance"] == {"Cổ phiếu": 2, "Trái phiếu": 0, "Tiền gửi": 0,
                           "Vàng": -2, "USD": 0}
    # claims: dòng value không phải số bị loại
    assert [c["key"] for c in d["claims"]] == ["sbv_policy_rate", "usdvnd", "khac"]
    # text đã sanitize (không ## / CJK / emoji)
    assert "#" not in d["tom_tat"] and "达" not in d["tom_tat"]
    assert d["risks"] == ["Tỷ giá vượt đỉnh"]        # risk rỗng bị loại


def test_parse_digest_garbage_returns_none():
    assert dg.parse_digest("") is None
    assert dg.parse_digest("không có json") is None
    assert dg.parse_digest("{json hỏng") is None
    assert dg.parse_digest("[1, 2]") is None


# ── cross-check (REGISTRY THẮNG) ────────────────────────────────────────────


def test_cross_check_flags_only_out_of_tolerance():
    d = dg.parse_digest(_RAW_OK)
    has = dg.cross_check_claims(d["claims"], _MACRO)
    assert has is True
    by_key = {c["key"]: c for c in d["claims"]}
    # 4.5 vs 4.5 → khớp, không cờ
    assert "mismatch" not in by_key["sbv_policy_rate"]
    # 27,500 vs 26,200 = ~5% > dung sai 2% → cờ + kèm giá trị registry
    assert by_key["usdvnd"]["mismatch"] is True
    assert by_key["usdvnd"]["registry_value"] == 26200.0
    # key "khac" không có gì để đối chiếu → không cờ
    assert "mismatch" not in by_key["khac"]


def test_cross_check_empty_registry_flags_nothing():
    claims = [{"key": "usdvnd", "value": 99999.0}]
    assert dg.cross_check_claims(claims, []) is False
    assert dg.cross_check_claims(claims, None) is False
    assert "mismatch" not in claims[0]


# ── digest_report + refresh ──────────────────────────────────────────────────


def test_digest_report_end_to_end(monkeypatch):
    rec = _add_report()
    monkeypatch.setattr(dg, "digest_call", lambda s, u, accept=None: (_RAW_OK, "claude"))
    monkeypatch.setitem(sys.modules, "vnstock_macro", types.ModuleType("vnstock_macro"))
    sys.modules["vnstock_macro"].load_macro = lambda *a, **k: _MACRO
    d = dg.digest_report(rec)
    assert d["provider"] == "claude" and d["has_mismatch"] is True
    assert d["digested_at"]
    # prompt chứa metadata nguồn + thân báo cáo
    seen = {}
    monkeypatch.setattr(dg, "digest_call",
                        lambda s, u, accept=None: seen.update(s=s, u=u) or (_RAW_OK, "x"))
    dg.digest_report(rec)
    assert rec["source"] in seen["u"] and "Báo cáo chiến lược" in seen["u"]
    assert "sbv_policy_rate" in seen["s"]            # danh sách key registry


def test_digest_report_no_provider_returns_none(monkeypatch):
    rec = _add_report()
    monkeypatch.setattr(dg, "digest_call", lambda s, u, accept=None: (None, ""))
    assert dg.digest_report(rec) is None


def test_refresh_digests_only_missing_and_redigest_all(monkeypatch):
    _add_report(days_old=2, source="SSI", text=_TEXT + "a")
    _add_report(days_old=4, source="HSC", text=_TEXT + "b")
    calls = []
    monkeypatch.setattr(dg, "digest_call",
                        lambda s, u, accept=None: calls.append(1) or (_RAW_OK, "claude"))
    monkeypatch.setitem(sys.modules, "vnstock_macro", types.ModuleType("vnstock_macro"))
    sys.modules["vnstock_macro"].load_macro = lambda *a, **k: _MACRO
    done = dg.refresh()
    assert len(done) == 2 and len(calls) == 2
    assert all(r["digest"]["stance"]["Cổ phiếu"] == 2 for r in done)
    # digest đã cache trong index → refresh lần 2 không gọi LLM
    assert dg.refresh() == [] and len(calls) == 2
    # --redigest chấm lại tất cả
    assert len(dg.refresh(redigest=True)) == 2 and len(calls) == 4


def test_refresh_skips_reports_not_in_analysis(monkeypatch):
    rp.add_text(_TEXT)                               # thiếu metadata
    monkeypatch.setattr(dg, "digest_call", lambda s, u, accept=None: (_RAW_OK, "claude"))
    assert dg.refresh() == []


# ── consensus + decay + tilt ─────────────────────────────────────────────────


def _set_stance(rec, cp, days_old):
    d = {"tom_tat": "x", "stance": {**{c: 0 for c in dg._ASSET_CLASSES},
                                    "Cổ phiếu": cp},
         "claims": [], "risks": [], "has_mismatch": False}
    rp.set_digest(rec["id"], d)


def test_age_weight_decay_profile():
    assert dg._age_weight(0) == 1.0
    assert dg._age_weight(30) == 1.0
    assert dg._age_weight(60) == pytest.approx(0.5)
    assert dg._age_weight(90) == 0.0


def test_consensus_weighted_by_age_and_tilt_threshold():
    r1 = _add_report(days_old=5, source="SSI", text=_TEXT + "a")
    r2 = _add_report(days_old=60, source="HSC", text=_TEXT + "b")
    _set_stance(r1, -2, 5)                           # tươi, rất phòng thủ
    _set_stance(r2, +2, 60)                          # cũ (w=0.5), tấn công
    c = dg.consensus()
    # (-2×1.0 + 2×0.5) / 1.5 = -0.67 → chưa chạm ngưỡng ±1 → không tilt
    assert c["n_reports"] == 2
    assert c["stance"]["Cổ phiếu"] == pytest.approx(-0.67, abs=0.01)
    assert c["tilt"] == 0
    # bỏ báo cáo cũ → chỉ còn -2 → tilt +1 (phòng thủ)
    rp.remove(r2["id"])
    c2 = dg.consensus()
    assert c2["stance"]["Cổ phiếu"] == -2.0 and c2["tilt"] == 1
    assert c2["drivers"][0]["source"] == "SSI"


def test_consensus_none_without_digests():
    _add_report()                                    # có báo cáo, chưa digest
    assert dg.consensus() is None


# ── tilt tích hợp vào vnstock_allocation ────────────────────────────────────


def _full_inputs():
    return {"regime": {"score": 0}, "sentiment": {"momentum": 0},
            "breadth": {"above_ma200_pct": 45.0}}    # điểm ~0 → band data B2


def _fake_consensus(monkeypatch, tilt, cp=-2.0):
    mod = types.ModuleType("vnstock_report_digest")
    mod.consensus = lambda as_of=None: {
        "tilt": tilt, "n_reports": 1,
        "stance": {"Cổ phiếu": cp},
        "drivers": [{"source": "SSI"}]}
    monkeypatch.setitem(sys.modules, "vnstock_report_digest", mod)


def test_allocation_applies_report_tilt_over_data_band(monkeypatch):
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    _fake_consensus(monkeypatch, tilt=1)             # báo cáo phòng thủ
    state = alloc.run_allocation()
    assert state["band_data"] == "B2"                # data giữ nguyên
    assert state["band"] == "B3"                     # tilt +1
    assert state["allocation"] == alloc._DEFAULT_ALLOCATIONS["B3"]
    assert state["report_tilt"]["tilt"] == 1
    assert state["history"][-1]["band_data"] == "B2"
    assert state["history"][-1]["tilt"] == 1


def test_allocation_tilt_clamped_at_b4(monkeypatch):
    bear = {"regime": {"score": -5}, "sentiment": {"momentum": -80},
            "breadth": {"above_ma200_pct": 15.0}}
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", bear))
    _fake_consensus(monkeypatch, tilt=1)
    state = alloc.run_allocation()
    assert state["band_data"] == "B4" and state["band"] == "B4"   # kịch sàn


def test_allocation_hysteresis_anchored_on_band_data_not_tilted(monkeypatch):
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    _fake_consensus(monkeypatch, tilt=1)
    s1 = alloc.run_allocation()
    assert (s1["band_data"], s1["band"]) == ("B2", "B3")
    # phiên sau: data VẪN B2, tilt tắt đi (báo cáo hết hạn) → band về B2 NGAY
    # (không phải chờ hysteresis — vì band_data chưa từng rời B2)
    _fake_consensus(monkeypatch, tilt=0)
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-14", _full_inputs()))
    s2 = alloc.run_allocation()
    assert (s2["band_data"], s2["band"]) == ("B2", "B2")
    assert s2["report_tilt"] is None
    assert s2["pending"] is None                     # không pending giả từ tilt


def test_allocation_tilt_env_kill_switch(monkeypatch):
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    _fake_consensus(monkeypatch, tilt=1)
    monkeypatch.setenv("VNSTOCK_ALLOCATION_TILT", "0")
    state = alloc.run_allocation()
    assert state["band"] == state["band_data"] == "B2"
    assert state["report_tilt"] is None


def test_allocation_tilt_module_missing_is_noop(monkeypatch):
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    mod = types.ModuleType("vnstock_report_digest")  # không có consensus()
    monkeypatch.setitem(sys.modules, "vnstock_report_digest", mod)
    state = alloc.run_allocation()
    assert state["band"] == "B2" and state["report_tilt"] is None


# ── CLI smoke ────────────────────────────────────────────────────────────────


def test_cli_consensus_and_show(monkeypatch, capsys):
    rec = _add_report(days_old=3, source="SSI")
    _set_stance(rec, -2, 3)
    assert dg.main(["--consensus"]) == 0
    out = capsys.readouterr().out
    assert "tilt +1" in out and "SSI" in out
    assert dg.main(["--show", rec["id"]]) == 0
    assert '"stance"' in capsys.readouterr().out
    assert dg.main(["--show", "khong_co"]) == 1


def test_cli_refresh(monkeypatch, capsys):
    _add_report(days_old=1, source="SSI")
    monkeypatch.setattr(dg, "digest_call", lambda s, u, accept=None: (_RAW_OK, "claude"))
    monkeypatch.setitem(sys.modules, "vnstock_macro", types.ModuleType("vnstock_macro"))
    sys.modules["vnstock_macro"].load_macro = lambda *a, **k: _MACRO
    assert dg.main(["--refresh"]) == 0
    assert "1 báo cáo đã digest" in capsys.readouterr().out


def test_digest_call_loads_env_before_key_check():
    # Bẫy CLAUDE.md dính thật khi verify 14/07: CLI fresh chưa load .env →
    # "không key nào chạy" dù .env đủ key. Khoá: digest_call phải gọi
    # _ensure_env_loaded TRƯỚC khi thử provider nào.
    import inspect
    src = inspect.getsource(dg.digest_call)
    assert "_ensure_env_loaded()" in src
    assert src.index("_ensure_env_loaded()") < src.index("_call_claude")


def test_free_models_env_override(monkeypatch):
    # Mặc định: model mạnh nhất free mỗi provider (nâng từ llama-3.3-70b sau
    # verify 14/07 — 70B đọc sai stance báo cáo thật)
    base = dg._free_models()
    assert set(base) == {"Groq", "Cerebras", "OpenRouter"}
    assert base["Groq"] == "openai/gpt-oss-120b"
    # env override từng provider, provider không nêu giữ mặc định, rác bỏ qua
    monkeypatch.setenv("VNSTOCK_DIGEST_MODELS",
                       "Groq=llama-3.3-70b-versatile; OpenRouter = foo:free ;"
                       "KhongCoProvider=x;rac-khong-dau-bang")
    out = dg._free_models()
    assert out["Groq"] == "llama-3.3-70b-versatile"
    assert out["OpenRouter"] == "foo:free"
    assert out["Cerebras"] == base["Cerebras"]


def test_free_ladder_is_strength_major():
    # BẬC 1 (mạnh, mọi provider) đứng TRƯỚC toàn bộ bậc 2 (70B) — không phải
    # provider-major như chat_complete (yếu của Groq không được chen trước
    # mạnh của Cerebras).
    ladder = dg._free_ladder()
    models = [m for _, m in ladder]
    tier2_models = [m for _, m in dg._FREE_TIER2]
    first_tier2 = min(models.index(m) for m in tier2_models)
    assert first_tier2 == 3                          # đủ 3 model bậc 1 trước
    assert set(models[:3]) == set(dg._FREE_MODELS.values())
    # env override trỏ bậc 1 về đúng model bậc 2 → không thử trùng 2 lần
    import os
    os.environ["VNSTOCK_DIGEST_MODELS"] = "Groq=llama-3.3-70b-versatile"
    try:
        ladder2 = dg._free_ladder()
        assert ladder2.count(("Groq", "llama-3.3-70b-versatile")) == 1
    finally:
        os.environ.pop("VNSTOCK_DIGEST_MODELS")


def test_digest_call_cascades_to_next_strong_model(monkeypatch, capsys):
    # Không key Claude/GPT; Groq bậc 1 chết → phải sang Cerebras BẬC 1
    # (gpt-oss-120b), KHÔNG rơi xuống Groq 70B trước.
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("CEREBRAS_API_KEY", "ck")
    monkeypatch.setattr(dg, "_ensure_env_loaded", lambda: None)

    class _Resp:
        def __init__(self, model):
            self._m = model
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": f"ok:{self._m}"}}]}

    def _post(url, headers=None, json=None, timeout=None):
        if "groq" in url:
            raise RuntimeError("model decommissioned")
        return _Resp(json["model"])

    fake_req = types.ModuleType("requests")
    fake_req.post = _post
    monkeypatch.setitem(sys.modules, "requests", fake_req)

    raw, provider = dg.digest_call("s", "u")
    assert raw == "ok:gpt-oss-120b"
    assert provider == "Cerebras:gpt-oss-120b"       # ghi rõ model đã digest
    assert "Groq (openai/gpt-oss-120b)" in capsys.readouterr().out


def test_digest_call_falls_through_to_tier2(monkeypatch):
    # Mọi model bậc 1 chết → bậc 2 (70B) cứu; không key nào → (None, "")
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr(dg, "_ensure_env_loaded", lambda: None)

    class _Resp:
        def __init__(self, model):
            self._m = model
        def raise_for_status(self):
            if "gpt-oss" in self._m:
                raise RuntimeError("404 model not found")
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    fake_req = types.ModuleType("requests")
    fake_req.post = lambda url, headers=None, json=None, timeout=None: _Resp(json["model"])
    monkeypatch.setitem(sys.modules, "requests", fake_req)
    raw, provider = dg.digest_call("s", "u")
    assert raw == "ok" and provider == "Groq:llama-3.3-70b-versatile"

    monkeypatch.delenv("GROQ_API_KEY")
    assert dg.digest_call("s", "u") == (None, "")


def test_call_free_reasoning_model_empty_content_cascades(monkeypatch, capsys):
    # Lỗi thật Cerebras 14/07: gpt-oss-120b (reasoning model) cạn max_tokens
    # giữa phần suy nghĩ → message chỉ có 'reasoning', không có 'content'.
    # Phải coi là fail CÓ CHẨN ĐOÁN (không KeyError thô) rồi cascade tiếp.
    monkeypatch.setenv("CEREBRAS_API_KEY", "ck")

    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"finish_reason": "length",
                                 "message": {"reasoning": "We need to..."}}]}

    fake_req = types.ModuleType("requests")
    fake_req.post = lambda *a, **k: _Resp()
    monkeypatch.setitem(sys.modules, "requests", fake_req)
    assert dg._call_free("Cerebras", "gpt-oss-120b", "s", "u") is None
    out = capsys.readouterr().out
    assert "content rỗng" in out and "finish_reason=length" in out


def test_call_free_uses_wide_token_budget(monkeypatch):
    # Nấc free mặc định phải dùng _FREE_MAX_TOKENS (reasoning cần budget),
    # không phải 700 của nấc trả phí.
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    fake_req = types.ModuleType("requests")
    def _post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return _Resp()
    fake_req.post = _post
    monkeypatch.setitem(sys.modules, "requests", fake_req)
    assert dg._call_free("Groq", "openai/gpt-oss-120b", "s", "u") == "ok"
    assert seen["max_tokens"] == dg._FREE_MAX_TOKENS >= 3000


def test_digest_call_cascades_on_unparseable_output(monkeypatch, capsys):
    # 14/07: Cerebras TRẢ LỜI nhưng JSON hỏng (bị cắt) → trước đây digest bỏ
    # cuộc dù còn nấc chưa thử. Nay accept=parse-được là điều kiện của cascade.
    monkeypatch.setattr(dg, "_ensure_env_loaded", lambda: None)
    monkeypatch.setattr(dg, "_call_claude", lambda s, u: "json rác { hỏng")
    monkeypatch.setattr(dg, "_call_openai", lambda s, u: _RAW_OK)
    raw, provider = dg.digest_call(
        "s", "u", accept=lambda r: dg.parse_digest(r) is not None)
    assert provider == "openai" and dg.parse_digest(raw) is not None
    assert "claude: trả lời nhưng output không đạt" in capsys.readouterr().out
    # --diag (accept=None) vẫn nhận output đầu tiên bất kể nội dung
    raw2, provider2 = dg.digest_call("s", "u")
    assert provider2 == "claude" and raw2 == "json rác { hỏng"
