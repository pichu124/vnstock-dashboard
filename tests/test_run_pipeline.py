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
