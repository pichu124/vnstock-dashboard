"""Tests cho run.py `all --no-sync` (nút "🧩 Cập nhật còn lại" trên dashboard):
bỏ ĐÚNG sync+validate, giữ nguyên thứ tự phần còn lại."""
from __future__ import annotations

import sys
from datetime import datetime as _dt
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
    assert ok is False and "15:05" in why
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
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
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
    assert ok is False and "15:05" in why


def test_should_push_close_same_night_run_past_midnight(tmp_path):
    """Đêm 28/09: pipeline khởi động 21:15, sync 121′ (VCI ốm → KBS 1.027 mã)
    → bước brief lúc 00:13 T3 29/09. Cửa cũ thấy "ngày làm việc, trước 15:00"
    và chặn như chạy bù sáng → `brief 0s`, Telegram mất brief T2. Lượt KHỞI
    ĐỘNG trong ngày phiên thì tràn nửa đêm vẫn đẩy; phiên = 28/09 (marker ghi
    phiên, không ghi ngày gửi); chạy bù sáng và lệnh tay vẫn chặn (15/08)."""
    from datetime import datetime as dt
    import json as _json
    marker = tmp_path / "brief_push.json"
    now, started = dt(2026, 9, 29, 0, 13), dt(2026, 9, 28, 21, 15)
    assert runpy._close_session_date(now).isoformat() == "2026-09-28"
    ok, _ = runpy._should_push_close(now, marker, started=started)
    assert ok is True
    # marker phiên 28/09 → cùng lượt gọi lại thì im (chống trùng)
    marker.write_text(_json.dumps({"close": "2026-09-28"}), encoding="utf-8")
    ok, why = runpy._should_push_close(now, marker, started=started)
    assert ok is False and "trùng" in why
    # tối 29/09 (sau 15:05) là phiên MỚI → marker 28/09 không chặn
    ok, _ = runpy._should_push_close(dt(2026, 9, 29, 20, 49), marker,
                                     started=dt(2026, 9, 29, 19, 7))
    assert ok is True
    # chạy bù sáng hôm sau (khởi động 08:20 T3) → vẫn chặn như user chốt 15/08
    ok, why = runpy._should_push_close(dt(2026, 9, 29, 8, 25), tmp_path / "a.json",
                                       started=dt(2026, 9, 29, 8, 20))
    assert ok is False and "15:05" in why
    # lệnh tay `run.py brief` lúc 00:13, không biết giờ khởi động → chặn như cũ
    ok, _ = runpy._should_push_close(now, tmp_path / "b.json")
    assert ok is False


def test_close_session_date_is_the_covered_session():
    """Trước 15:05 ngày làm việc là PHIÊN TRƯỚC (cùng luật `--skip-if-done`)."""
    from datetime import datetime as dt
    f = runpy._close_session_date
    assert f(dt(2026, 9, 29, 0, 13)).isoformat() == "2026-09-28"    # tràn nửa đêm
    assert f(dt(2026, 9, 29, 8, 20)).isoformat() == "2026-09-28"    # bù sáng
    assert f(dt(2026, 9, 29, 15, 10)).isoformat() == "2026-09-29"   # sau đóng cửa
    assert f(dt(2026, 9, 28, 0, 30)).isoformat() == "2026-09-25"    # T2 rạng sáng → T6
    import vnstock_rollup as rl
    assert runpy._CLOSE_CUTOFF == rl._SESSION_CLOSE_CUTOFF            # một mốc, hai nơi


def test_cmd_brief_passes_pipeline_start_to_the_gate(tmp_path, monkeypatch):
    """cmd_all gắn `args.pipeline_started`; cmd_brief phải chuyển nó vào cửa —
    quên chuyển thì lượt tràn nửa đêm lại bị chặn y như cũ."""
    from datetime import datetime as dt
    seen = {}

    def _gate(now, m, started=None):
        seen["started"] = started
        return False, "dừng ở cửa"
    monkeypatch.setattr(runpy, "_should_push_close", _gate)
    args = type("A", (), {})()
    args.warehouse = str(tmp_path)
    args.pipeline_started = dt(2026, 9, 28, 21, 15)
    assert runpy.cmd_brief(args) == 0
    assert seen["started"] == dt(2026, 9, 28, 21, 15)


def test_cmd_brief_marker_records_session_date(tmp_path, monkeypatch):
    """Marker phải mang NGÀY PHIÊN (T7/CN gửi thì ghi ngày thứ 6) — nếu ghi
    ngày gửi, chạy T7 xong CN sẽ bắn trùng brief của cùng phiên."""
    import json as _json
    from datetime import datetime as dt

    import vnstock_telegram as _tg
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
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
    user test tay message_id=212 rồi định chạy all ngay sau đó).

    Từ 19/08 cửa gửi này đi qua `_should_push_close` nên test phải nói rõ ý
    định bằng `--force` (chạy trong giờ CI thì cửa gác giờ chặn) — điều PHẢI
    giữ ở đây là: hễ ĐÃ GỬI thì marker được đóng dấu."""
    import json as _json
    from datetime import datetime as dt

    import vnstock_telegram as _tg
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: {"result": {"message_id": 5}})
    args = SimpleNamespace(warehouse=str(tmp_path), action="close", force=True)
    assert runpy.cmd_telegram(args) == 0
    payload = _json.loads(
        runpy._brief_push_marker(args).read_text(encoding="utf-8"))["close"]
    assert payload == runpy._close_session_date(dt.now()).isoformat()


# ── `telegram close` phải đi qua đúng cửa gác của bước brief (vá 19/08) ─────
#
# Vết: cửa gửi tay GHI marker nhưng KHÔNG ĐỌC nó và không có cửa gác giờ. Hai
# cách hỏng âm thầm: gõ hai lần → hai brief cùng phiên; gõ trước 15:00 ngày làm
# việc → marker bị đóng dấu, làm CÂM brief của task 18:00 cùng phiên.

class TestTelegramCloseRespectsTheSameGates:

    def _args(self, tmp_path, force=False):
        import argparse
        return argparse.Namespace(action="close", warehouse=str(tmp_path),
                                  force=force)

    def _fake_tg(self, sent):
        import types
        m = types.SimpleNamespace()
        m.push_close_brief = lambda: sent.append(1) or {"result": {"message_id": 9}}
        return m

    def _after_close_bell(self, monkeypatch):
        """Đông cứng giờ vào 16:00 một ngày làm việc — nếu không, cửa gác GIỜ
        chặn trước và test hoá ra xanh vì lý do khác với thứ nó định kiểm."""
        import run as runpy

        class _Clock:
            @staticmethod
            def now():
                return _dt(2026, 8, 18, 16, 0, 0)      # thứ Ba, sau 15:00

        monkeypatch.setattr(runpy, "_datetime", _Clock)
        return _dt(2026, 8, 18, 16, 0, 0)

    def test_marker_of_the_same_session_blocks_a_second_send(
            self, tmp_path, monkeypatch):
        import json
        import run as runpy
        now = self._after_close_bell(monkeypatch)
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        sess = runpy._close_session_date(now).isoformat()
        (meta / "brief_push.json").write_text(json.dumps({"close": sess}),
                                              encoding="utf-8")
        sent: list = []
        monkeypatch.setitem(sys.modules, "vnstock_telegram", self._fake_tg(sent))
        rc = runpy.cmd_telegram(self._args(tmp_path))
        assert rc == 0 and sent == [], "gửi trùng brief cho cùng một phiên"

    def test_sends_normally_after_the_bell_when_no_marker(
            self, tmp_path, monkeypatch):
        """Cửa gác phải HẸP: sau 15:00 mà chưa có marker thì vẫn gửi bình
        thường, không cần --force."""
        import run as runpy
        self._after_close_bell(monkeypatch)
        (tmp_path / "_meta").mkdir(parents=True)
        sent: list = []
        monkeypatch.setitem(sys.modules, "vnstock_telegram", self._fake_tg(sent))
        assert runpy.cmd_telegram(self._args(tmp_path)) == 0
        assert sent == [1]

    def test_before_the_bell_it_refuses_and_leaves_no_marker(
            self, tmp_path, monkeypatch):
        """Ca hỏng nguy hiểm nhất: gõ trước 15:00 thì marker KHÔNG được đóng
        dấu — đóng dấu là làm CÂM brief của task 18:00 cùng phiên."""
        import run as runpy

        class _Clock:
            @staticmethod
            def now():
                return _dt(2026, 8, 18, 9, 30, 0)      # thứ Ba, trước 15:00

        monkeypatch.setattr(runpy, "_datetime", _Clock)
        (tmp_path / "_meta").mkdir(parents=True)
        sent: list = []
        monkeypatch.setitem(sys.modules, "vnstock_telegram", self._fake_tg(sent))
        assert runpy.cmd_telegram(self._args(tmp_path)) == 0
        assert sent == []
        assert not (tmp_path / "_meta" / "brief_push.json").exists()

    def test_force_overrides_the_gate(self, tmp_path, monkeypatch):
        import json
        import run as runpy
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        sess = runpy._close_session_date(_dt.now()).isoformat()
        (meta / "brief_push.json").write_text(json.dumps({"close": sess}),
                                              encoding="utf-8")
        sent: list = []
        monkeypatch.setitem(sys.modules, "vnstock_telegram", self._fake_tg(sent))
        rc = runpy.cmd_telegram(self._args(tmp_path, force=True))
        assert rc == 0 and sent == [1], "--force phải vượt được cửa gác"

    def test_force_flag_exists_on_the_parser(self):
        import run as runpy
        ns = runpy.build_parser().parse_args(["telegram", "close", "--force"])
        assert ns.force is True
        ns2 = runpy.build_parser().parse_args(["telegram", "close"])
        assert ns2.force is False


# ── 16/09: đường chạy bù — T7/CN sync --force; cờ tắt brief ghi vào marker chung ──
class _Clock:
    fixed = _dt(2026, 9, 19, 10, 0, 0)           # thứ 7

    @classmethod
    def now(cls):
        return cls.fixed


def _sync_cmds(monkeypatch, tmp_path, when):
    cmds = []
    monkeypatch.setattr(runpy, "_run", lambda cmd: cmds.append(list(cmd)) or 0)
    monkeypatch.setattr(runpy, "_print_sync_breakdown", lambda _sub: None)
    _Clock.fixed = when
    monkeypatch.setattr(runpy, "_datetime", _Clock)
    rc = runpy.cmd_sync(SimpleNamespace(warehouse=str(tmp_path), no_fix_units=True,
                                        no_auto_heal=True))
    assert rc == 0
    return cmds


def test_cmd_sync_forces_the_updater_on_weekends_only(tmp_path, monkeypatch):
    """Chạy bù T7 (máy tắt tối T6): updater tự bỏ qua cuối tuần nếu thiếu
    --force ⇒ brief T6 từng đẩy trên bar T5. Thị trường đóng nên fetch an toàn."""
    sat = _sync_cmds(monkeypatch, tmp_path, _dt(2026, 9, 19, 10, 0))
    assert sat[0][1:] == ["vnstock_updater.py", "--skip-if-done", "--force"]
    assert sat[1][1:] == ["vnstock_rollup.py", "--skip-if-done"]
    tue = _sync_cmds(monkeypatch, tmp_path, _dt(2026, 9, 15, 18, 0))
    assert tue[0][1:] == ["vnstock_updater.py", "--skip-if-done"]


def test_cmd_brief_kill_switch_writes_skipped_without_touching_close(tmp_path, monkeypatch):
    """.env không đồng bộ giữa hai máy — máy nào tắt brief phải ghi vào marker
    DÙNG CHUNG, không thì badge doctor ở máy kia réo "brief chưa" mỗi đêm.
    KHÔNG đụng "close" để cửa gửi tay vẫn mở."""
    import json as _json
    import vnstock_telegram as _tg
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "0")
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda: (_ for _ in ()).throw(AssertionError("không được đẩy")))
    _Clock.fixed = _dt(2026, 9, 15, 19, 20)              # thứ 3
    monkeypatch.setattr(runpy, "_datetime", _Clock)
    args = SimpleNamespace(warehouse=str(tmp_path))
    marker = runpy._brief_push_marker(args)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_json.dumps({"close": "2026-09-14"}), encoding="utf-8")
    assert runpy.cmd_brief(args) == 0
    saved = _json.loads(marker.read_text(encoding="utf-8"))
    assert saved["close"] == "2026-09-14"
    assert saved["skipped"]["session"] == "2026-09-15"
    assert saved["skipped"]["reason"] == "VNSTOCK_PIPELINE_BRIEF=0"
    assert saved["skipped"]["machine"] and saved["skipped"]["at"].startswith("2026-09-15T19:20")
    # marker chưa có / rác ⇒ vẫn ghi được, không nổ
    marker.write_text("{rác", encoding="utf-8")
    assert runpy.cmd_brief(args) == 0
    assert "skipped" in _json.loads(marker.read_text(encoding="utf-8"))
    # "no" cũng là tắt (khớp doctor._OFF_VALUES)
    monkeypatch.setenv("VNSTOCK_PIPELINE_BRIEF", "no")
    assert runpy.cmd_brief(args) == 0


# ─── Engine brief chiều (30/09): ladder | claude, --export-pack, --from-file ──

def _claude_engine_stubs(monkeypatch, cli_result, tmp_path) -> dict:
    """Dựng đường claude hoàn toàn hermetic; trả dict ghi nhận gì đã gửi."""
    import vnstock_brief_pack as bp
    import vnstock_telegram as _tg
    seen: dict = {}
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
    monkeypatch.setattr(bp, "build_pack", lambda bt="afternoon": {
        "version": 1, "brief_type": bt, "session": "2026-09-30",
        "prompt": "PROMPT", "ctx": {"date": "2026-09-30"}})
    monkeypatch.setattr(bp, "write_pack",
                        lambda pack, path: seen.setdefault("pack_path", path))
    monkeypatch.setattr(bp, "run_claude_cli",
                        lambda prompt, **kw: seen.setdefault("prompt", prompt) and cli_result)
    monkeypatch.setattr(bp, "finalize_brief",
                        lambda text, pack, **kw: {"text": text + "|G", "warnings": ["w"],
                                                  "brief_id": 1, "auto_score": 0.5})

    def _push(ai_block=None, engine=None):
        seen["ai_block"], seen["engine"] = ai_block, engine
        return {"result": {"message_id": 5}}
    monkeypatch.setattr(_tg, "push_close_brief", _push)
    return seen


def test_cmd_brief_engine_claude_sends_claude_text_and_marks_engine(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("VNSTOCK_BRIEF_ENGINE", "claude")
    seen = _claude_engine_stubs(monkeypatch, ("BODY", None, {"model": "claude-opus-5-5",
                                                             "elapsed_s": 40}), tmp_path)
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    assert seen["prompt"] == "PROMPT"
    assert seen["ai_block"] == "BODY|G" and "Claude Code" in seen["engine"]
    assert str(seen["pack_path"]).endswith("brief_pack.json")   # gói luôn ra kho để soi
    marker = _json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["close"] and marker["engine"] == "claude"


def test_cmd_brief_engine_claude_falls_back_to_ladder_when_cli_fails(tmp_path, monkeypatch, capsys):
    import json as _json
    monkeypatch.setenv("VNSTOCK_BRIEF_ENGINE", "claude")
    seen = _claude_engine_stubs(monkeypatch, ("", "claude CLI quá 900s — bỏ", {"elapsed_s": 900}),
                                tmp_path)
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    assert seen["ai_block"] is None and seen["engine"] is None      # ladder như cũ
    marker = _json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["engine"] == "ladder"
    out = capsys.readouterr().out
    assert "[brief] ⏱ claude-cli:" in out and "❌" in out and "rơi về ladder" in out


def test_cmd_brief_engine_claude_falls_back_when_guards_empty_the_text(tmp_path, monkeypatch):
    import vnstock_brief_pack as bp
    monkeypatch.setenv("VNSTOCK_BRIEF_ENGINE", "claude")
    seen = _claude_engine_stubs(monkeypatch, ("BODY", None, {"model": "m", "elapsed_s": 1}), tmp_path)
    monkeypatch.setattr(bp, "finalize_brief",
                        lambda text, pack, **kw: {"text": "", "warnings": [], "brief_id": None,
                                                  "auto_score": 0.0})
    assert runpy.cmd_brief(SimpleNamespace(warehouse=str(tmp_path))) == 0
    assert seen["ai_block"] is None


def test_cmd_brief_default_engine_is_ladder_and_flag_overrides_env(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.delenv("VNSTOCK_BRIEF_ENGINE", raising=False)
    seen = _claude_engine_stubs(monkeypatch, ("BODY", None, {}), tmp_path)
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    assert seen["ai_block"] is None and "prompt" not in seen        # không gọi CLI
    marker = _json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["engine"] == "ladder"

    monkeypatch.setenv("VNSTOCK_BRIEF_ENGINE", "ladder")
    seen2 = _claude_engine_stubs(monkeypatch, ("BODY", None, {"model": "m"}), tmp_path)
    assert runpy.cmd_brief(SimpleNamespace(warehouse=str(tmp_path), engine="claude")) == 0
    assert seen2["ai_block"] == "BODY|G"


def test_cmd_brief_export_pack_writes_pack_only(tmp_path, monkeypatch):
    import vnstock_brief_pack as bp
    import vnstock_telegram as _tg
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    # cửa gác chặn mà --export-pack vẫn chạy: xuất gói không phải gửi brief
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (False, "chặn"))
    monkeypatch.setattr(bp, "build_pack", lambda bt="afternoon": {
        "version": 1, "brief_type": bt, "session": "2026-09-30", "prompt": "P", "ctx": {}})
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("--export-pack mà gửi")))
    args = SimpleNamespace(warehouse=str(tmp_path), export_pack=True)
    assert runpy.cmd_brief(args) == 0
    assert bp.pack_path(tmp_path).exists()
    assert not runpy._brief_push_marker(args).exists()


def test_cmd_brief_from_file_ingests_and_requires_same_session_pack(tmp_path, monkeypatch):
    import json as _json

    import vnstock_brief_pack as bp
    import vnstock_telegram as _tg
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
    sess = runpy._close_session_date(runpy._datetime.now()).isoformat()
    bp.write_pack({"version": 1, "brief_type": "afternoon", "session": sess,
                   "prompt": "P", "ctx": {"date": sess}}, bp.pack_path(tmp_path))
    md = tmp_path / "brief_claude.md"
    md.write_text("## Tổng quan\nBODY", encoding="utf-8")
    seen: dict = {}
    monkeypatch.setattr(bp, "finalize_brief",
                        lambda text, pack, **kw: seen.update(text=text, kw=kw) or
                        {"text": "BODY|G", "warnings": [], "brief_id": 1, "auto_score": 0.1})
    monkeypatch.setattr(_tg, "push_close_brief",
                        lambda ai_block=None, engine=None:
                        seen.update(ai_block=ai_block) or {"result": {"message_id": 3}})
    args = SimpleNamespace(warehouse=str(tmp_path), from_file=str(md))
    assert runpy.cmd_brief(args) == 0
    assert seen["text"].startswith("## Tổng quan") and seen["ai_block"] == "BODY|G"
    assert seen["kw"]["agent_name"].endswith("(file)")
    marker = _json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["engine"] == "claude-file"

    # gói phiên KHÁC → lỗi rõ, không gửi, không marker (trừ --force)
    runpy._brief_push_marker(args).unlink()
    bp.write_pack({"version": 1, "brief_type": "afternoon", "session": "2020-01-02",
                   "prompt": "P", "ctx": {}}, bp.pack_path(tmp_path))
    seen.clear()
    assert runpy.cmd_brief(args) == 1
    assert "ai_block" not in seen and not runpy._brief_push_marker(args).exists()
    assert runpy.cmd_brief(SimpleNamespace(warehouse=str(tmp_path), from_file=str(md),
                                           force=True)) == 0
    assert seen["ai_block"] == "BODY|G"


def test_parser_accepts_brief_engine_flags():
    p = runpy.build_parser()
    a = p.parse_args(["brief", "--engine", "claude", "--export-pack",
                      "--from-file", "x.md", "--force"])
    assert (a.engine, a.export_pack, a.from_file, a.force) == ("claude", True, "x.md", True)
    a = p.parse_args(["brief"])
    assert a.engine is None and not a.export_pack and a.from_file is None


def test_cmd_telegram_close_goes_through_engine_dispatch(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
    monkeypatch.setattr(runpy, "_send_close_brief",
                        lambda args: ({"result": {"message_id": 1}}, "claude"))
    args = SimpleNamespace(warehouse=str(tmp_path), action="close", force=False)
    assert runpy.cmd_telegram(args) == 0
    marker = _json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["engine"] == "claude"
