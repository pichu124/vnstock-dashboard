"""Tests cho vnstock_model_watch + vnstock_model_eval (theo dõi model hàng tuần).

Ba giai đoạn user chốt 07/08:
  GĐ1 probe + diff danh mục → status/badge/cảnh báo
  GĐ2 bộ đề chuẩn chấm điểm THEO VIỆC (không có bảng "mạnh yếu" chung)
  GĐ3 đề xuất thay model, ngưỡng 2 lần liên tiếp chống thrash

Hermetic tuyệt đối: mọi HTTP đều monkeypatch, `_META` về tmp.
"""

import json

import pytest

import vnstock_model_eval as me
import vnstock_model_watch as mw


@pytest.fixture(autouse=True)
def _tmp_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "_META", tmp_path)
    monkeypatch.setenv("VNSTOCK_MODEL_WATCH_ALERT", "0")   # không bắn Telegram
    return tmp_path


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """Lưới cuối: test nào quên fake là nổ chứ không lặng lẽ gọi mạng thật."""
    def _boom(*a, **k):
        raise AssertionError("test gọi mạng THẬT — thiếu monkeypatch")
    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.text = json.dumps(body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


# ═══ GĐ1 — danh mục ════════════════════════════════════════════════════════

def test_fetch_catalog_parses_openai_shape(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _Resp({"data": [{"id": "m1"}, {"id": "m2"}]}))
    assert mw.fetch_catalog("Groq") == {"m1", "m2"}


def test_fetch_catalog_parses_gemini_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(
        {"models": [{"name": "models/gemini-3.5-flash"}]}))
    assert mw.fetch_catalog("Gemini") == {"gemini-3.5-flash"}


def test_fetch_catalog_follows_pagination(monkeypatch):
    """OpenRouter trả {data, links, total_count} và CẮT ở 400 (xác minh trên
    máy user 08/08). Đọc một trang là lưu mốc CỤT → tuần sau diff nổ ra một
    đống 'bị gỡ' giả."""
    pages = {
        "https://openrouter.ai/api/v1/models": {
            "data": [{"id": f"m{i}"} for i in range(400)],
            "links": {"next": "https://openrouter.ai/api/v1/models?offset=400"},
            "total_count": 640},
        "https://openrouter.ai/api/v1/models?offset=400": {
            "data": [{"id": f"m{i}"} for i in range(400, 640)],
            "links": {"next": None}, "total_count": 640},
    }
    monkeypatch.setattr("requests.get",
                        lambda url, **k: _Resp(pages[url]))
    got = mw.fetch_catalog("OpenRouter")
    assert got is not None and len(got) == 640


def test_fetch_catalog_uses_offset_when_no_next_link(monkeypatch):
    """Không có links.next nhưng total_count nói còn thiếu → thử offset."""
    calls = []

    def _get(url, headers=None, params=None, timeout=None):
        calls.append((params or {}).get("offset", 0))
        off = (params or {}).get("offset", 0)
        return _Resp({"data": [{"id": f"m{off + i}"} for i in range(3)],
                      "total_count": 6})

    monkeypatch.setattr("requests.get", _get)
    got = mw.fetch_catalog("OpenRouter")
    assert got is not None and len(got) == 6
    assert calls[:2] == [0, 3]


def test_incomplete_catalog_treated_as_unreadable(monkeypatch, capsys):
    """Gom mãi vẫn thiếu so với total_count → coi như KHÔNG đọc được (None)
    và nói to lý do. Diff một danh mục cụt là sinh báo động giả — thà không
    biết còn hơn báo sai (cùng doctrine với 'đọc hụt ≠ tập rỗng')."""
    monkeypatch.setattr("requests.get", lambda url, **k: _Resp(
        {"data": [{"id": "m1"}], "total_count": 900}))
    assert mw.fetch_catalog("OpenRouter") is None
    assert "900" in capsys.readouterr().out


def test_pagination_stops_on_repeated_url(monkeypatch):
    """links.next trỏ vòng lại chính nó → phải thoát, không lặp vô hạn."""
    monkeypatch.setattr("requests.get", lambda url, **k: _Resp(
        {"data": [{"id": "m1"}],
         "links": {"next": "https://openrouter.ai/api/v1/models"}}))
    assert mw.fetch_catalog("OpenRouter") == {"m1"}


def test_fetch_catalog_returns_none_on_failure(monkeypatch):
    """None ≠ tập rỗng. Gộp 2 ca này là báo "mọi model biến mất" khi thật ra
    chỉ là mạng lỗi — báo động giả tệ hơn không báo."""
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp({}, status=500))
    assert mw.fetch_catalog("Groq") is None


def test_fetch_catalog_none_without_key(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    assert mw.fetch_catalog("Cerebras") is None      # không gọi mạng (lưới _no_real_http)


def test_diff_detects_gone_and_new():
    prev = {"Groq": ["a", "b"], "Gemini": ["x"]}
    cur = {"Groq": ["b", "c"], "Gemini": ["x"]}
    d = mw.diff_catalogs(prev, cur)
    assert d["Groq"]["gone"] == ["a"] and d["Groq"]["new"] == ["c"]
    assert d["Gemini"]["gone"] == [] and d["Gemini"]["new"] == []


def test_diff_skips_provider_whose_fetch_failed():
    """Lỗi fetch (None) → BỎ QUA provider đó, tuyệt đối không suy ra "gone"."""
    d = mw.diff_catalogs({"Groq": ["a", "b"]}, {"Groq": None})
    assert d["Groq"]["status"] == "skipped"
    assert d["Groq"]["gone"] == []


def test_diff_skips_when_no_previous_snapshot():
    d = mw.diff_catalogs({}, {"Groq": ["a"]})
    assert d["Groq"]["status"] == "no_baseline"
    assert d["Groq"]["gone"] == []


def test_diff_reports_catalog_size():
    """Mốc lưu bao nhiêu model phải NHÌN THẤY — đọc thiếu (phân trang, response
    cụt) mà không lộ ra thì tuần sau diff nổ ra một đống "bị gỡ" giả."""
    d = mw.diff_catalogs({}, {"Groq": ["a", "b", "c"]})
    assert d["Groq"]["size"] == 3
    assert "3" in mw.render_report({
        "ran_at": "2026-08-15T09:00:00", "level": "green",
        "probe": {"ok": 0, "fail": 0, "rows": []},
        "catalog": {"diff": d, "gone_in_use": [], "skipped": []}})


def test_mass_disappearance_flagged_as_suspect_not_removal():
    """Nửa danh mục biến mất trong 1 tuần gần như chắc chắn là ĐỌC THIẾU chứ
    không phải provider gỡ thật. Vẫn báo, nhưng gắn nhãn nghi ngờ — báo nhầm
    "đã gỡ 40 model" là dạng nhiễu che mất tín hiệu thật."""
    prev = {"Groq": [f"m{i}" for i in range(20)]}
    cur = {"Groq": ["m0", "m1", "m2"]}
    d = mw.diff_catalogs(prev, cur)
    assert d["Groq"]["status"] == "suspect_partial"
    assert len(d["Groq"]["gone"]) == 17          # vẫn liệt kê để soi

    # mất ít thì vẫn là gỡ thật
    d2 = mw.diff_catalogs(prev, {"Groq": [f"m{i}" for i in range(18)]})
    assert d2["Groq"]["status"] == "ok"


def test_flood_of_new_models_flagged_as_stale_baseline():
    """Ca ngược của suspect_partial: mốc CŨ bị cụt (đọc thiếu tuần trước) →
    tuần này đọc đủ thì thấy cả trăm model "mới". Đó là hiện tượng đọc, không
    phải provider ra 240 model trong một tuần — phải nói đúng bản chất."""
    prev = {"OpenRouter": [f"m{i}" for i in range(400)]}
    cur = {"OpenRouter": [f"m{i}" for i in range(640)]}
    d = mw.diff_catalogs(prev, cur)
    assert d["OpenRouter"]["status"] == "suspect_baseline"
    assert len(d["OpenRouter"]["new"]) == 240

    # thêm vừa phải thì vẫn là model mới thật
    d2 = mw.diff_catalogs(prev, {"OpenRouter": [f"m{i}" for i in range(410)]})
    assert d2["OpenRouter"]["status"] == "ok"


def test_in_use_model_still_flagged_even_when_diff_suspect():
    """Nhãn nghi ngờ KHÔNG được nuốt mất tín hiệu quan trọng nhất: model đang
    dùng biến mất vẫn phải báo, để người soi tự quyết."""
    prev = {"Gemini": [f"m{i}" for i in range(20)] + ["gemini-3.5-flash"]}
    cur = {"Gemini": ["m0"]}
    d = mw.diff_catalogs(prev, cur)
    hits = mw.gone_models_in_use(d, {("Gemini", "gemini-3.5-flash"): "[8]"})
    assert hits == [("Gemini", "gemini-3.5-flash", "[8]")]


# ═══ GĐ1 — chỉ báo động cho model ĐANG DÙNG ════════════════════════════════

def test_alert_only_for_models_in_use():
    """Danh mục provider đổi liên tục; báo mọi thay đổi là spam tuần nào cũng
    có. Chỉ model ĐANG DÙNG biến mất mới đáng gọi dậy."""
    diff = {"Groq": {"gone": ["mo-hinh-la-hoac", "qwen/qwen3.6-27b"],
                     "new": [], "status": "ok"}}
    in_use = {("Groq", "qwen/qwen3.6-27b"): "[2] analyze + [8] classifier"}
    hits = mw.gone_models_in_use(diff, in_use)
    assert hits == [("Groq", "qwen/qwen3.6-27b", "[2] analyze + [8] classifier")]


def test_no_alert_when_unused_model_disappears():
    diff = {"Groq": {"gone": ["mo-hinh-khong-ai-dung"], "new": [], "status": "ok"}}
    assert mw.gone_models_in_use(diff, {("Groq", "dang-dung"): "[1]"}) == []


# ═══ GĐ1 — status file + mức độ ════════════════════════════════════════════

def _fake_probe(results):
    """results: {(provider, model): ok} → hàm thay probe_one."""
    return lambda prov, model, extra=None: (
        results.get((prov, model), True), "→ \"OK\"", 0.5)


def test_run_watch_writes_status_and_stays_green(monkeypatch, _tmp_meta):
    monkeypatch.setattr(mw, "_ladder_slugs",
                        lambda: [("Groq", "m1", "[1] sentiment", {})])
    monkeypatch.setattr(mw, "probe_one", _fake_probe({}))
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m1"]})

    status = mw.run_watch(do_eval=False)

    assert status["level"] == "green"
    assert status["probe"]["ok"] == 1 and status["probe"]["fail"] == 0
    on_disk = json.loads((_tmp_meta / "model_status.json").read_text(encoding="utf-8"))
    assert on_disk["level"] == "green"
    assert "ran_at" in on_disk


def test_dead_probe_turns_status_red(monkeypatch):
    monkeypatch.setattr(mw, "_ladder_slugs",
                        lambda: [("Groq", "m1", "[1] sentiment", {}),
                                 ("Groq", "m2", "[8] classifier", {})])
    monkeypatch.setattr(mw, "probe_one", _fake_probe({("Groq", "m2"): False}))
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m1", "m2"]})

    status = mw.run_watch(do_eval=False)

    assert status["level"] == "red"
    assert status["probe"]["fail"] == 1
    dead = [r for r in status["probe"]["rows"] if not r["ok"]]
    assert dead[0]["tag"] == "[8] classifier"       # biết hỏng ở tính năng nào


def test_kill_switch_skips_everything(monkeypatch, _tmp_meta):
    monkeypatch.setenv("VNSTOCK_MODEL_WATCH", "0")
    monkeypatch.setattr(mw, "probe_one",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("kill-switch bật mà vẫn probe")))
    status = mw.run_watch(do_eval=False)
    assert status["level"] == "skipped"


def test_history_keeps_bounded_number_of_runs(monkeypatch, _tmp_meta):
    monkeypatch.setattr(mw, "_ladder_slugs", lambda: [("Groq", "m1", "[1]", {})])
    monkeypatch.setattr(mw, "probe_one", _fake_probe({}))
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m1"]})
    for _ in range(mw._HISTORY_MAX + 3):
        mw.run_watch(do_eval=False)
    assert len(mw.load_history()["runs"]) == mw._HISTORY_MAX


# ═══ GĐ2 — chấm điểm THEO VIỆC ═════════════════════════════════════════════

def test_classification_scored_by_exact_industry():
    ok = json.dumps({"primary_industry": "Ngân hàng"}, ensure_ascii=False)
    assert me.score_classify(ok, "Ngân hàng") == 1.0
    assert me.score_classify(ok, "Thép & Kim loại") == 0.0


def test_classification_zero_when_json_broken():
    assert me.score_classify("xin lỗi tôi không rõ", "Ngân hàng") == 0.0


def test_classification_zero_for_invented_industry():
    """Bịa ngành ngoài danh sách phải bị phạt — đây đúng lỗi cần đo."""
    raw = json.dumps({"primary_industry": "Ngành Tự Chế"}, ensure_ascii=False)
    assert me.score_classify(raw, "Ngân hàng") == 0.0


def test_sentiment_scored_by_label():
    assert me.score_sentiment("TÍCH_CỰC | xuất khẩu hưởng lợi", "positive") == 1.0
    assert me.score_sentiment("TIÊU_CỰC | áp lực NIM", "positive") == 0.0


def test_json_task_scored_by_required_keys():
    good = json.dumps({"approved": True, "confidence": 0.9, "issues": []})
    assert me.score_json(good, ["approved", "confidence", "issues"]) == 1.0
    assert me.score_json(json.dumps({"approved": True}),
                         ["approved", "confidence", "issues"]) == 0.0


def test_golden_sets_are_non_empty_and_use_valid_industries():
    """Đáp án phân loại phải nằm trong danh sách ngành thật — đáp án sai thì
    cả bảng điểm vô nghĩa."""
    import vnstock_classifier as vc
    assert len(me.GOLDEN_CLASSIFY) >= 10
    assert len(me.GOLDEN_SENTIMENT) >= 8
    assert len(me.GOLDEN_JSON) >= 5
    for case in me.GOLDEN_CLASSIFY:
        assert case["expected"] in vc.INDUSTRY_GROUPS, case["ticker"]
    for case in me.GOLDEN_SENTIMENT:
        assert case["expected"] in ("positive", "negative", "neutral")


def test_run_eval_scores_per_task_not_one_global_rank(monkeypatch):
    """Cốt lõi GĐ2: model có thể giỏi việc này dở việc kia — bảng điểm phải
    TÁCH THEO VIỆC, không gộp thành một thứ hạng chung."""
    def _chat(provider, model, system, user, max_tokens=400):
        if model == "gioi-phan-loai":
            return json.dumps({"primary_industry": user_expected(user)},
                              ensure_ascii=False), None
        return "TRUNG_LẬP | không rõ", None

    def user_expected(user):
        for c in me.GOLDEN_CLASSIFY:
            if c["ticker"] in user:
                return c["expected"]
        return "Khác"

    monkeypatch.setattr(me, "chat_once", _chat)
    scores = me.run_eval([("Groq", "gioi-phan-loai")], tasks=("classify",))
    assert scores[("Groq", "gioi-phan-loai")]["classify"] == 1.0


def test_production_eval_passes_a_throttle_delay(monkeypatch):
    """Bộ đề ~25 ca × ~10 model = ~250 call. run_eval mặc định delay=0 (cho
    test chạy nhanh) — nhánh production PHẢI tự truyền ngưỡng lịch sự, không
    thì bắn liên tiếp lên free tier là dính rate limit (Groq TPM 8K)."""
    seen = {}
    monkeypatch.setattr(me, "run_eval",
                        lambda models, **kw: seen.update(kw) or {})
    monkeypatch.setattr(me, "propose_swaps", lambda *a, **k: [])
    monkeypatch.setattr(me, "current_models", lambda: {})
    mw._run_eval_stage([{"provider": "Groq", "model": "m", "ok": True}],
                       {"runs": []})
    assert seen.get("delay", 0) > 0


def test_run_eval_marks_model_that_cannot_answer(monkeypatch):
    monkeypatch.setattr(me, "chat_once", lambda *a, **k: (None, "HTTP 429"))
    scores = me.run_eval([("Groq", "chet")], tasks=("classify",))
    assert scores[("Groq", "chet")]["classify"] == 0.0
    assert scores[("Groq", "chet")]["errors"] > 0


# ═══ GĐ3 — đề xuất, KHÔNG tự áp ════════════════════════════════════════════

def test_proposal_needs_two_consecutive_runs(monkeypatch):
    """Chống thrash — tiền lệ qwen-235b:free sống→404→sống trong 1 ngày."""
    scores = {("Gemini", "dang-dung"): {"classify": 0.4},
              ("Groq", "ung-vien"): {"classify": 0.9}}
    current = {"classify": [("Gemini", "dang-dung")]}

    first = me.propose_swaps(scores, current, previous_proposals=[])
    assert first and first[0]["ripe"] is False          # lần 1: mới ghi nhận

    second = me.propose_swaps(scores, current, previous_proposals=first)
    assert second[0]["ripe"] is True                    # lần 2 mới chín


def test_no_proposal_when_gap_too_small():
    scores = {("Gemini", "dang-dung"): {"classify": 0.85},
              ("Groq", "ung-vien"): {"classify": 0.88}}
    assert me.propose_swaps(scores, {"classify": [("Gemini", "dang-dung")]},
                            previous_proposals=[]) == []


def test_no_proposal_when_current_is_already_best():
    scores = {("Gemini", "dang-dung"): {"classify": 0.95},
              ("Groq", "ung-vien"): {"classify": 0.40}}
    assert me.propose_swaps(scores, {"classify": [("Gemini", "dang-dung")]},
                            previous_proposals=[]) == []


def test_proposals_never_mutate_live_config(monkeypatch):
    """Ranh giới cứng: GĐ3 chỉ ĐỀ XUẤT. Brief bắn thẳng Telegram mỗi sáng —
    script tự đổi model là user đọc bản không ai duyệt."""
    import vnstock_classifier as vc
    before = dict(vc._CLASSIFY_MODELS)
    scores = {("Gemini", "gemini-3.5-flash"): {"classify": 0.2},
              ("Groq", "ung-vien"): {"classify": 0.99}}
    out = me.propose_swaps(scores,
                           {"classify": [("Gemini", "gemini-3.5-flash")]},
                           previous_proposals=[])
    assert out                                   # có đề xuất
    assert vc._CLASSIFY_MODELS == before         # nhưng KHÔNG đụng config
    assert not hasattr(me, "apply_swaps")        # và không có đường tự áp


def test_current_models_map_covers_the_three_eval_tasks():
    """Mỗi việc trong bộ đề phải trỏ được về điểm dùng thật, không thì đề
    xuất không biết đang so với cái gì."""
    cur = me.current_models()
    assert set(cur) == {"classify", "sentiment", "json"}
    for task, pairs in cur.items():
        assert pairs, task
        assert all(isinstance(p, tuple) and len(p) == 2 for p in pairs)
