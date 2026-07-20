"""Tests cho run.py `all --no-sync` (nút "🧩 Cập nhật còn lại" trên dashboard):
bỏ ĐÚNG sync+validate, giữ nguyên thứ tự phần còn lại."""
from __future__ import annotations

from types import SimpleNamespace

import run as runpy


def test_all_steps_default_full_chain():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    assert names[:3] == ["sync", "validate", "screener"]
    assert "news" in names and names[-1] == "doctor"


def test_all_steps_no_sync_drops_sync_and_validate_only():
    names = [n for n, _ in runpy._all_steps(SimpleNamespace(no_sync=True))]
    assert "sync" not in names and "validate" not in names
    # phần còn lại giữ NGUYÊN thứ tự pipeline đêm (train SAU audit — rec vừa
    # đóng thì strategy health mới có số; TRƯỚC reflection)
    assert names == ["screener", "news", "foreign-flow", "macro", "gold",
                     "allocation", "test", "audit", "train", "reflection",
                     "doctor"]


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
