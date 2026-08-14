"""Tests cho run.py `all --no-sync` (nút "🧩 Cập nhật còn lại" trên dashboard):
bỏ ĐÚNG sync+validate, giữ nguyên thứ tự phần còn lại."""
from __future__ import annotations

from types import SimpleNamespace

import run as runpy


def test_all_steps_default_full_chain():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    assert names[:3] == ["sync", "validate", "screener"]
    assert "news" in names and names[-2:] == ["doctor", "brief"]


def test_all_steps_no_sync_drops_sync_and_validate_only():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace(no_sync=True))]
    assert "sync" not in names and "validate" not in names
    # phần còn lại giữ NGUYÊN thứ tự pipeline đêm (train SAU audit — rec vừa
    # đóng thì strategy health mới có số; TRƯỚC reflection)
    assert names == ["screener", "news", "foreign-flow", "macro", "gold",
                     "allocation", "test", "audit", "train", "reflection",
                     "doctor", "brief"]


def test_all_steps_no_sync_no_news():
    names = [n for n, _ in runpy._all_steps(
        SimpleNamespace(no_sync=True, no_news=True))]
    assert "news" not in names and names[0] == "screener"


def test_all_steps_no_train_drops_train_only():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace(no_train=True))]
    assert "train" not in names
    assert names[:3] == ["sync", "validate", "screener"]
    assert "audit" in names and "reflection" in names


def test_parser_accepts_no_sync_flag():
    args = runpy.build_parser().parse_args(["all", "--no-sync"])
    assert args.no_sync is True
    assert runpy.build_parser().parse_args(["all"]).no_sync is False


def test_parser_accepts_no_train_and_train_subcommand():
    assert runpy.build_parser().parse_args(["all", "--no-train"]).no_train is True
    assert runpy.build_parser().parse_args(["train"]).subcommand == "train"
    assert runpy._DISPATCH["train"] is runpy.cmd_train


def test_dashboard_button_wired_to_no_sync():
    src = (__import__("pathlib").Path(__file__).resolve().parent.parent
           / "vnstock_dashboard.py").read_text(encoding="utf-8")
    assert "Cập nhật còn lại" in src
    assert '"all", "--no-sync"' in src


# ─── Bước 14: brief chiều trong pipeline (thêm 29/07 — trước đây chạy tay) ──

def test_all_steps_no_brief_drops_brief_only():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace(no_brief=True))]
    assert "brief" not in names and names[-1] == "doctor"


def test_parser_accepts_no_brief_and_brief_subcommand():
    assert runpy.build_parser().parse_args(["all", "--no-brief"]).no_brief is True
    assert runpy.build_parser().parse_args(["all"]).no_brief is False
    assert runpy.build_parser().parse_args(["brief"]).subcommand == "brief"
    assert runpy._DISPATCH["brief"] is runpy.cmd_brief


def test_should_push_close_guards(tmp_path):
    from datetime import datetime as dt
    import json as _json
    marker = tmp_path / "brief_push.json"
    # Trước 15:00 (run-on-boot bù sáng hôm sau) → KHÔNG đẩy brief chiều cũ
    ok, why = runpy._should_push_close(dt(2026, 7, 29, 8, 5), marker)
    assert ok is False and "15:00" in why
    # Sau 15:00, chưa đẩy hôm nay → ĐẨY
    ok, _ = runpy._should_push_close(dt(2026, 7, 29, 18, 0), marker)
    assert ok is True
    # Marker ghi hôm nay đã đẩy → KHÔNG đẩy lần 2 (chống gửi trùng)
    marker.write_text(_json.dumps({"close": "2026-07-29"}), encoding="utf-8")
    ok, why = runpy._should_push_close(dt(2026, 7, 29, 19, 0), marker)
    assert ok is False and "trùng" in why
    # Sang ngày khác → marker cũ hết hiệu lực
    ok, _ = runpy._should_push_close(dt(2026, 7, 30, 18, 0), marker)
    assert ok is True


def test_cmd_brief_killswitch_skips_without_calling_telegram(tmp_path, monkeypatch):
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "0")
    import vnstock_telegram as _tg
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("kill-switch bật mà vẫn đẩy brief")))
    rc = runpy.cmd_brief(SimpleNamespace(warehouse=str(tmp_path)))
    assert rc == 0


def test_cmd_brief_pushes_and_writes_marker(tmp_path, monkeypatch):
    import json as _json

    import vnstock_telegram as _tg
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m: (True, ""))
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: {"result": {"message_id": 7}})

    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    marker = runpy._brief_push_marker(args)
    assert _json.loads(marker.read_text(encoding="utf-8"))["close"]

    # Telegram lỗi → exit 1 (cảnh báo, không fail cứng) và KHÔNG ghi marker
    marker.unlink()
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: (_ for _ in ()).throw(RuntimeError("token sai")))
    assert runpy.cmd_brief(args) == 1
    assert not marker.exists()


# ─── run.py weekend: gộp 3 việc cuối tuần (29/07 — thay 3 task lẻ T7/CN/T2) ──

def test_weekend_steps_order_and_flags():
    steps = runpy._weekend_steps(SimpleNamespace(warehouse="data_warehouse"))
    names = [n for n, _ in steps]
    # models ĐẦU TIÊN (07/08): nhẹ nhất ~10 call thử và là thứ duy nhất phát
    # hiện được "ladder sắp chết" → chạy trước để bước nặng lỗi vẫn kịp cảnh
    # báo. Rồi nhẹ→nặng, fundamentals ~25-30ph để cuối.
    assert names == ["models", "rates-weekly", "vietstock", "fundamentals"]
    cmds = {n: c for n, c in steps}
    # task tuần chạy CẢ chấm điểm bộ đề (GĐ2-3) — 1 tuần/lần nên gánh được
    assert "--eval" in cmds["models"]
    # vietstock phải giữ nguyên cờ của task cũ
    assert "--bulk" in cmds["vietstock"] and "--register" in cmds["vietstock"]
    # fundamentals PHẢI --force (không có = incremental no-op, bug 2026-07-10)
    assert "--force" in cmds["fundamentals"]


def test_cmd_weekend_continues_past_failures_and_reports_worst(monkeypatch):
    ran = []

    def _fake_run(cmd):
        ran.append(cmd)
        return 1 if len(ran) == 2 else 0    # bước thứ 2 lỗi

    monkeypatch.setattr(runpy, "_run", _fake_run)
    rc = runpy.cmd_weekend(SimpleNamespace(warehouse="data_warehouse"))
    assert len(ran) == 4        # lỗi giữa chừng KHÔNG chặn các bước sau
    assert rc == 1              # gom về cảnh báo


def test_weekend_model_watch_failure_does_not_block_the_rest(monkeypatch):
    """Bước models đứng đầu → nếu nó fail cứng mà chặn cả task tuần thì mất
    luôn rates/vietstock/fundamentals. Phải chỉ ghi nhận rồi chạy tiếp."""
    ran = []
    monkeypatch.setattr(runpy, "_run",
                        lambda cmd: (ran.append(cmd), 2 if len(ran) == 1 else 0)[1])
    rc = runpy.cmd_weekend(SimpleNamespace(warehouse="data_warehouse"))
    assert len(ran) == 4
    assert rc == 2


def test_parser_accepts_weekend_subcommand():
    assert runpy.build_parser().parse_args(["weekend"]).subcommand == "weekend"
    assert runpy._DISPATCH["weekend"] is runpy.cmd_weekend


def test_parser_accepts_models_subcommand():
    args = runpy.build_parser().parse_args(["models", "--eval"])
    assert args.subcommand == "models" and args.eval is True
    assert runpy._DISPATCH["models"] is runpy.cmd_models


def test_cmd_models_forwards_flags(monkeypatch):
    seen = {}
    import vnstock_model_watch as mw

    def _fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(mw, "main", _fake_main)
    rc = runpy.cmd_models(SimpleNamespace(eval=True, json=False))
    assert rc == 0 and seen["argv"] == ["--eval"]


# ─── Điểm [6] 29/07: auditor LLM (free cascade) bật mặc định trong pipeline ──

def test_audit_llm_enabled_default_on(monkeypatch):
    monkeypatch.delenv("VNSTOCK_AUDIT_LLM", raising=False)
    assert runpy._audit_llm_enabled(SimpleNamespace()) is True


def test_audit_llm_enabled_flag_and_env_killswitch(monkeypatch):
    monkeypatch.delenv("VNSTOCK_AUDIT_LLM", raising=False)
    assert runpy._audit_llm_enabled(SimpleNamespace(no_llm_audit=True)) is False
    for off in ("0", "false", "off"):
        monkeypatch.setenv("VNSTOCK_AUDIT_LLM", off)
        assert runpy._audit_llm_enabled(SimpleNamespace()) is False
    monkeypatch.setenv("VNSTOCK_AUDIT_LLM", "1")
    assert runpy._audit_llm_enabled(SimpleNamespace()) is True


def test_cmd_all_wires_llm_audit():
    """Mirror nếp inspect-source: cmd_all phải hỏi _audit_llm_enabled và bật
    args.llm cho bước audit trong chuỗi — thiếu là bước audit theo lịch lại
    câm LLM như trước 29/07."""
    import inspect
    src = inspect.getsource(runpy.cmd_all)
    assert "_audit_llm_enabled" in src
    assert "args.llm = True" in src


def test_audit_llm_context_carries_schema_notes():
    """Verify thật 29/07: Cerebras rồi Gemini đều disapprove toàn báo động
    giả vì thiếu chú giải schema (so reconciler với anomaly, tưởng 1 ngày,
    tưởng warn≈missing_in_api là double-count). Chú giải là guard
    deterministic — mất dòng nào là auditor lại kêu oan đêm đó."""
    ctx = runpy._audit_llm_context(6)
    assert "Daily audit for" in ctx
    assert "6 trading" in ctx                      # cửa sổ NHIỀU ngày, không phải 1
    assert "INDEPENDENT" in ctx                    # reconciler ≠ anomaly
    assert "missing_in_rolled" in ctx and "EXCLUDED" in ctx
    assert "missing_in_api" in ctx and "by design" in ctx
    assert "never add up" in ctx


def test_cmd_audit_wires_schema_notes():
    import inspect
    src = inspect.getsource(runpy.cmd_audit)
    assert "_audit_llm_context(len(recon.dates_checked))" in src


def test_parser_accepts_free_auditor_and_no_llm_audit():
    assert runpy.build_parser().parse_args(
        ["all", "--no-llm-audit"]).no_llm_audit is True
    assert runpy.build_parser().parse_args(["all"]).no_llm_audit is False
    assert runpy.build_parser().parse_args(
        ["audit", "--llm", "--auditor", "free"]).auditor == "free"
    assert runpy.build_parser().parse_args(
        ["all", "--auditor", "free"]).auditor == "free"


def test_close_session_date_mapping():
    from datetime import datetime as dt
    f = runpy._close_session_date
    assert f(dt(2026, 8, 14, 18, 0)).isoformat() == "2026-08-14"   # T6 → chính nó
    assert f(dt(2026, 8, 15, 9, 0)).isoformat() == "2026-08-14"    # T7 → T6
    assert f(dt(2026, 8, 16, 22, 0)).isoformat() == "2026-08-14"   # CN → T6
    assert f(dt(2026, 8, 17, 16, 0)).isoformat() == "2026-08-17"   # T2 → chính nó


def test_should_push_close_weekend_rules(tmp_path):
    """User chốt 15/08: T7/CN gửi GIỜ NÀO CŨNG ĐƯỢC (không có phiên mới),
    nhưng bất biến là MỘT brief cho mỗi PHIÊN — marker theo NGÀY PHIÊN chứ
    không phải ngày gửi. Luật cũ chặn <15:00 mọi ngày → brief chiều thứ 6
    MẤT VĨNH VIỄN mỗi khi máy tắt tối thứ 6 (chạy bù T7 sáng bị chặn, sang
    T2 đã thành phiên khác) — đúng ca user vấp 15/08."""
    from datetime import datetime as dt
    import json as _json
    marker = tmp_path / "brief_push.json"
    # T7 9h sáng (2026-08-15): ĐẨY — ca chạy bù cuối tuần
    ok, _ = runpy._should_push_close(dt(2026, 8, 15, 9, 0), marker)
    assert ok is True
    # Máy bật tối T6 đã gửi (marker = ngày phiên T6) → T7 chạy bù phải IM
    marker.write_text(_json.dumps({"close": "2026-08-14"}), encoding="utf-8")
    ok, why = runpy._should_push_close(dt(2026, 8, 15, 20, 0), marker)
    assert ok is False and "trùng" in why
    # CN chạy nữa → vẫn IM (cùng phiên thứ 6)
    ok, _ = runpy._should_push_close(dt(2026, 8, 16, 10, 0), marker)
    assert ok is False
    # Sang T2 sau 15:00 → phiên MỚI → đẩy bình thường
    ok, _ = runpy._should_push_close(dt(2026, 8, 17, 18, 0), marker)
    assert ok is True
    # T2 TRƯỚC 15:00 vẫn bị chặn như cũ (ngày làm việc, phiên chưa đóng)
    ok, why = runpy._should_push_close(dt(2026, 8, 17, 8, 0), marker)
    assert ok is False and "15:00" in why


def test_cmd_brief_marker_records_session_date(tmp_path, monkeypatch):
    """Marker phải mang NGÀY PHIÊN (T7/CN gửi thì ghi ngày thứ 6) — nếu ghi
    ngày gửi, chạy T7 xong CN sẽ bắn trùng brief của cùng phiên."""
    import json as _json
    from datetime import datetime as dt

    import vnstock_telegram as _tg
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m: (True, ""))
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: {"result": {"message_id": 9}})
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    payload = _json.loads(
        runpy._brief_push_marker(args).read_text(encoding="utf-8"))["close"]
    assert payload == runpy._close_session_date(dt.now()).isoformat()


def test_cmd_telegram_close_writes_session_marker(tmp_path, monkeypatch):
    """Lệnh tay `telegram close` phải ghi marker PHIÊN — không thì gửi tay
    xong chạy `all` là Telegram nhận brief TRÙNG cùng phiên (ca thật 15/08:
    user test tay message_id=212 rồi định chạy all ngay sau đó)."""
    import json as _json
    from datetime import datetime as dt

    import vnstock_telegram as _tg
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: {"result": {"message_id": 5}})
    args = SimpleNamespace(warehouse=str(tmp_path), action="close")
    assert runpy.cmd_telegram(args) == 0
    payload = _json.loads(
        runpy._brief_push_marker(args).read_text(encoding="utf-8"))["close"]
    assert payload == runpy._close_session_date(dt.now()).isoformat()
