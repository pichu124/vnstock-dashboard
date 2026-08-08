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
def _no_real_sleep(monkeypatch):
    """Retry hạn mức ngủ 5s + 15s THẬT. 12 ca × 20s = 4 phút cho MỘT test —
    đủ để phá ngân sách ~30s của cả suite. Test nào cần soi thời gian ngủ thì
    tự setattr đè (monkeypatch sau thắng)."""
    monkeypatch.setattr(me.time, "sleep", lambda s: None)
    monkeypatch.setattr(mw.time, "sleep", lambda s: None)


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


def test_fetch_catalog_returns_none_on_failure(monkeypatch, capsys):
    """None ≠ tập rỗng. Gộp 2 ca này là báo "mọi model biến mất" khi thật ra
    chỉ là mạng lỗi — báo động giả tệ hơn không báo.

    Và lỗi phải NÓI RA: báo cáo chỉ in "không đọc được danh mục" — không kèm
    lý do thì không chẩn đoán được là hết key, đổi endpoint hay mạng chập."""
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp({}, status=500))
    assert mw.fetch_catalog("Groq") is None
    out = capsys.readouterr().out
    assert "Groq" in out and "500" in out


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


_RL_BODY = ('HTTP 429: {"error":{"message":"Rate limit exceeded: '
            'free-models-per-day. Add 10 credits to unlock 1000 free models"}}')


def test_rate_limited_probe_is_not_reported_dead(monkeypatch, _tmp_meta):
    """Ca thật 08/08: 3 model OpenRouter dính `free-models-per-day` (do CHÍNH
    eval của ta đốt) bị báo ❌ chết + đẩy trạng thái đỏ. Hết hạn mức trong
    ngày ≠ model chết — cùng họ bug vừa sửa ở bảng điểm."""
    monkeypatch.setattr(mw, "_ladder_slugs",
                        lambda: [("OpenRouter", "m1", "[7] brief", {}),
                                 ("Groq", "m2", "[1] sentiment", {})])
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m2"]})
    monkeypatch.setattr(mw, "probe_one",
                        lambda p, m, e=None: (False, _RL_BODY, 0.6)
                        if p == "OpenRouter" else (True, "ok", 0.8))

    st = mw.run_watch(do_eval=False)

    assert st["level"] == "warn"                  # KHÔNG phải red
    assert st["probe"]["fail"] == 0               # không tính là chết
    assert st["probe"]["rate_limited"] == 1
    row = next(r for r in st["probe"]["rows"] if r["provider"] == "OpenRouter")
    assert row["rate_limited"] is True


def test_real_death_still_red_alongside_rate_limit(monkeypatch, _tmp_meta):
    monkeypatch.setattr(mw, "_ladder_slugs",
                        lambda: [("OpenRouter", "m1", "[7]", {}),
                                 ("Groq", "m2", "[1]", {})])
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {})
    monkeypatch.setattr(mw, "probe_one",
                        lambda p, m, e=None: (False, _RL_BODY, 0.6)
                        if p == "OpenRouter"
                        else (False, "HTTP 404: model_not_found", 0.3))
    st = mw.run_watch(do_eval=False)
    assert st["level"] == "red" and st["probe"]["fail"] == 1


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


# ═══ Độ trễ theo tuần ══════════════════════════════════════════════════════

def _hist(*runs):
    """runs: mỗi run là dict {"Provider:model": giây}."""
    return {"runs": [{"at": f"2026-08-{i+1:02d}T09:00:00", "probe_seconds": r}
                     for i, r in enumerate(runs)]}


def test_history_stores_probe_seconds(monkeypatch, _tmp_meta):
    monkeypatch.setattr(mw, "_ladder_slugs", lambda: [("Groq", "m1", "[1]", {})])
    monkeypatch.setattr(mw, "probe_one", lambda *a, **k: (True, "ok", 1.25))
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m1"]})
    mw.run_watch(do_eval=False)
    assert mw.load_history()["runs"][-1]["probe_seconds"] == {"Groq:m1": 1.25}


def test_median_ignores_runs_without_timings():
    """Lịch sử cũ (trước 08/08) không có khoá probe_seconds — phải bỏ qua chứ
    không nổ."""
    hist = {"runs": [{"at": "x", "catalogs": {}},          # bản cũ
                     {"at": "y", "probe_seconds": {"Groq:m1": 2.0}},
                     {"at": "z", "probe_seconds": {"Groq:m1": 4.0}}]}
    assert mw._latency_medians(hist) == {"Groq:m1": 3.0}


def test_slow_needs_both_factor_and_absolute_floor():
    """Bài học tối 07/08: chạy dồn 4 lần/45 phút làm free tier bóp băng thông
    → 0.9s thành 17s rồi tự hồi. Nhân hệ số thôi thì 0.8s → 2.4s (3×) cũng
    kêu, toàn nhiễu. Phải kèm sàn tuyệt đối."""
    hist = _hist({"Groq:m1": 0.8, "OpenRouter:m2": 1.0},
                 {"Groq:m1": 0.8, "OpenRouter:m2": 1.0})
    rows = [{"provider": "Groq", "model": "m1", "tag": "[1]", "ok": True,
             "seconds": 2.4},                       # 3× nhưng chỉ 2.4s → bỏ qua
            {"provider": "OpenRouter", "model": "m2", "tag": "[7]", "ok": True,
             "seconds": 12.0}]                      # 12× và 12s → bắt
    slow = mw._latency_flags(rows, hist)
    assert [s["key"] for s in slow] == ["OpenRouter:m2"]
    assert slow[0]["median"] == 1.0 and slow[0]["factor"] == 12.0


def test_no_latency_flag_without_enough_history():
    """1 mẫu không đủ làm median — tuần đầu tuyệt đối không kêu."""
    assert mw._latency_flags(
        [{"provider": "Groq", "model": "m1", "tag": "[1]", "ok": True,
          "seconds": 30.0}], _hist({"Groq:m1": 1.0})) == []


def test_dead_model_not_counted_in_latency():
    """Model chết đã có cảnh báo riêng; đừng đếm nó vào thống kê độ trễ."""
    hist = _hist({"Groq:m1": 1.0}, {"Groq:m1": 1.0})
    rows = [{"provider": "Groq", "model": "m1", "tag": "[1]", "ok": False,
             "seconds": 45.0}]
    assert mw._latency_flags(rows, hist) == []


def test_severe_slowdown_warns_but_mild_does_not(monkeypatch, _tmp_meta):
    """Chậm vừa = thông tin, không đổi màu badge. Chậm tới ngưỡng sắp chạm
    timeout 25s của chat_complete mới đáng nâng mức."""
    monkeypatch.setattr(mw, "_ladder_slugs", lambda: [("Groq", "m1", "[1]", {})])
    monkeypatch.setattr(mw, "snapshot_catalogs", lambda: {"Groq": ["m1"]})
    monkeypatch.setattr(mw, "save_history", lambda h: None)
    monkeypatch.setattr(mw, "load_history",
                        lambda: _hist({"Groq:m1": 1.0}, {"Groq:m1": 1.0}))

    monkeypatch.setattr(mw, "probe_one", lambda *a, **k: (True, "ok", 6.0))
    assert mw.run_watch(do_eval=False)["level"] == "green"     # 6× nhưng 6s

    monkeypatch.setattr(mw, "probe_one", lambda *a, **k: (True, "ok", 18.0))
    st = mw.run_watch(do_eval=False)
    assert st["level"] == "warn"
    assert st["latency"]["slow"][0]["severe"] is True


def test_report_shows_latency_section():
    hist = _hist({"OpenRouter:m2": 1.0}, {"OpenRouter:m2": 1.0})
    rows = [{"provider": "OpenRouter", "model": "m2", "tag": "[7] brief",
             "ok": True, "seconds": 12.0, "detail": "ok"}]
    slow = mw._latency_flags(rows, hist)
    txt = mw.render_report({
        "ran_at": "2026-08-15T09:00:00", "level": "warn",
        "probe": {"ok": 1, "fail": 0, "rows": rows},
        "catalog": {"diff": {}, "gone_in_use": [], "skipped": []},
        "latency": {"slow": slow}})
    assert "12.0s" in txt and "median 1.0s" in txt


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


def test_rate_limited_task_is_unmeasured_not_zero(monkeypatch):
    """Ca thật 08/08: gemini-3.5-flash được classify=1.00 (bắt buộc phải xuất
    JSON đúng 12 lần) nhưng json=0.00 — vô lý. Bài chạy trước ăn hết quota,
    bài sau bị 429, mà 429 lại bị chấm 0 điểm.

    Cùng họ bug với "sentiment đóng băng neutral" và "JSON hỏng ghi thành
    Khác": gộp KHÔNG ĐO ĐƯỢC với ĐO RA KẾT QUẢ KÉM. Nay hụt quá ngưỡng →
    None (khuyết khỏi bảng), không phải 0.0."""
    monkeypatch.setattr(me, "chat_once", lambda *a, **k: (None, "HTTP 429"))
    scores = me.run_eval([("Groq", "bi-bop")], tasks=("classify",))
    assert "classify" not in scores[("Groq", "bi-bop")]
    assert scores[("Groq", "bi-bop")]["errors"] == len(me.GOLDEN_CLASSIFY)


def test_few_errors_still_scored_over_answered_cases(monkeypatch):
    """Hụt lác đác thì vẫn chấm — nhưng chấm trên số ca THỰC SỰ trả lời."""
    seen = {"n": 0}

    def _chat(provider, model, system, user, max_tokens=400):
        seen["n"] += 1
        if seen["n"] == 1:
            return None, "HTTP 500"
        exp = next((c["expected"] for c in me.GOLDEN_CLASSIFY
                    if c["ticker"] in user), "Khác")
        return json.dumps({"primary_industry": exp}, ensure_ascii=False), None

    monkeypatch.setattr(me, "chat_once", _chat)
    sc = me.run_eval([("Groq", "hut-1-ca")], tasks=("classify",))[("Groq", "hut-1-ca")]
    assert sc["classify"] == 1.0        # 11/11 ca trả lời đều đúng
    assert sc["errors"] == 1
    assert sc["coverage"]["classify"] == len(me.GOLDEN_CLASSIFY) - 1


def test_rate_limit_is_retried_before_giving_up(monkeypatch):
    """429 là "thử lại sau", không phải "model hỏng" — phải lùi rồi thử lại
    thay vì bỏ luôn cả bài."""
    calls = {"n": 0}
    slept = []

    def _chat(provider, model, system, user, max_tokens=400):
        calls["n"] += 1
        if calls["n"] <= 2:
            return None, "HTTP 429: rate limit exceeded"
        return json.dumps({"primary_industry": "Ngân hàng"},
                          ensure_ascii=False), None

    monkeypatch.setattr(me, "chat_once", _chat)
    monkeypatch.setattr(me.time, "sleep", lambda s: slept.append(s))
    raw, err = me._chat_with_retry("Groq", "m", "s", "u")
    assert err is None and raw is not None
    assert len(slept) == 2 and slept[1] > slept[0]     # lùi tăng dần


def test_eval_respects_per_provider_budget(monkeypatch):
    """OpenRouter free = 50 req/ngày; 3 model × 25 ca = 75 call → eval của
    CHÍNH TA đốt sạch quota, hôm sau production mất nấc dự phòng (ca thật
    08/08). Có hạn mức thì chỉ đo được bao nhiêu đo, phần còn lại để tuần sau."""
    monkeypatch.setattr(me, "chat_once",
                        lambda *a, **k: (json.dumps({"primary_industry": "Khác"}), None))
    models = [("OpenRouter", f"m{i}") for i in range(3)]
    sc = me.run_eval(models, tasks=("classify",), budget={"OpenRouter": 25})
    measured = [k for k, v in sc.items() if "classify" in v]
    assert len(measured) == 2          # 12 ca/model → chỉ lọt 2 model trong 25
    assert sc[("OpenRouter", "m2")]["skipped"] == "budget"


def test_budget_free_providers_untouched(monkeypatch):
    monkeypatch.setattr(me, "chat_once",
                        lambda *a, **k: (json.dumps({"primary_industry": "Khác"}), None))
    sc = me.run_eval([("Groq", f"m{i}") for i in range(3)],
                     tasks=("classify",), budget={"OpenRouter": 25})
    assert all("classify" in v for v in sc.values())


def test_eval_rotates_models_not_measured_recently(monkeypatch):
    """Không xoay vòng thì model bị cắt vì hạn mức sẽ KHÔNG BAO GIỜ được đo."""
    hist = {"runs": [{"at": "x", "eval_measured": ["OpenRouter:m0", "OpenRouter:m1"]}]}
    order = mw._eval_order([("OpenRouter", "m0"), ("OpenRouter", "m1"),
                            ("OpenRouter", "m2")], hist)
    assert order[0] == ("OpenRouter", "m2")     # chưa đo lần trước → lên đầu


def test_gives_up_task_after_consecutive_rate_limits(monkeypatch):
    """Quota CẢ NGÀY cạn thì retry chỉ đốt thời gian: 25 ca × 20s × 10 model
    = hơn một tiếng cho task T7. Dính liên tiếp thì bỏ nốt bài, đừng cố."""
    calls = {"n": 0}

    def _chat(*a, **k):
        calls["n"] += 1
        return None, "HTTP 429: quota exceeded"

    monkeypatch.setattr(me, "chat_once", _chat)
    sc = me.run_eval([("Gemini", "het-quota")], tasks=("classify",))
    assert "classify" not in sc[("Gemini", "het-quota")]      # n/a
    # bỏ sớm: KHÔNG chạy hết 12 ca (mỗi ca 3 lần gọi kể cả retry)
    assert calls["n"] < 3 * len(me.GOLDEN_CLASSIFY)


def test_non_rate_limit_error_not_retried(monkeypatch):
    """404 model_not_found thì thử lại chỉ tốn thời gian."""
    calls = {"n": 0}

    def _chat(*a, **k):
        calls["n"] += 1
        return None, "HTTP 404: model_not_found"

    monkeypatch.setattr(me, "chat_once", _chat)
    monkeypatch.setattr(me.time, "sleep", lambda s: None)
    assert me._chat_with_retry("Groq", "m", "s", "u")[1] is not None
    assert calls["n"] == 1


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
