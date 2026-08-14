"""
Lưới cho run_daily.log (run.py, thêm 13/08) — file log ĐẦU TIÊN của pipeline.

Bối cảnh (entry 11/08 (e) + 13/08 (j)): Task Scheduler vứt stdout nên
`run_daily.log` mà notes nhắc suốt CHƯA TỪNG tồn tại — mọi mục "soi log"
đều bất khả thi. Vá 13/08: main() tee stdout/stderr ra file, _run() bơm
output tiến trình con qua PIPE để cùng chảy vào tee. Lưới này canh:
  1. chuỗi chặn con → pipe → tee → file KHÔNG đứt (test tích hợp thật),
  2. đường ghi file chết KHÔNG kéo pipeline chết (best-effort),
  3. main() còn gọi _install_run_log, _run còn đi đường PIPE (net AST —
     ai gỡ tee là test đỏ, tránh lặp lại chính vụ 11/08 (e)).
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import run as run_mod


class TestLogPathContract:
    def test_log_is_run_daily_in_repo_root(self):
        # Tên + chỗ đứng là hợp đồng với MỌI tham chiếu cũ trong notes
        assert run_mod.RUN_LOG_PATH.name == "run_daily.log"
        assert run_mod.RUN_LOG_PATH.parent == run_mod.REPO_ROOT

    def test_log_is_gitignored(self):
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "run_daily.log" in gitignore.splitlines()


class TestTee:
    def test_write_reaches_both_sides(self, tmp_path):
        log = open(tmp_path / "t.log", "a", encoding="utf-8")
        console = io.StringIO()
        tee = run_mod._Tee(console, log)
        tee.write("xin chào log\n")
        log.close()
        assert "xin chào log" in console.getvalue()
        assert "xin chào log" in (tmp_path / "t.log").read_text(encoding="utf-8")

    def test_dead_log_side_never_raises_console_still_served(self, tmp_path):
        class _DeadHandle:
            def write(self, _):
                raise OSError("disk full")
            def flush(self):
                raise OSError("disk full")

        console = io.StringIO()
        tee = run_mod._Tee(console, _DeadHandle())
        tee.write("vẫn phải tới console\n")   # không được nổ
        tee.flush()
        assert "vẫn phải tới console" in console.getvalue()

    def test_dead_console_side_never_raises_log_still_served(self, tmp_path):
        class _DeadStream:
            def write(self, _):
                raise OSError("no console (Task Scheduler)")
            def flush(self):
                raise OSError("no console")

        log_path = tmp_path / "t.log"
        log = open(log_path, "a", encoding="utf-8")
        tee = run_mod._Tee(_DeadStream(), log)
        tee.write("vẫn phải vào file\n")
        log.close()
        assert "vẫn phải vào file" in log_path.read_text(encoding="utf-8")

    def test_attribute_passthrough(self):
        console = io.StringIO()
        tee = run_mod._Tee(console, io.StringIO())
        assert tee.getvalue() == ""           # uỷ quyền cho console stream


class TestRunStreamsChildThroughTee:
    def test_child_stdout_and_stderr_reach_log_file(self, tmp_path, monkeypatch):
        """Tích hợp thật cả chuỗi: con → PIPE → print cha → tee → file."""
        log_path = tmp_path / "run_daily.log"
        log = open(log_path, "a", encoding="utf-8")
        monkeypatch.setattr(sys, "stdout", run_mod._Tee(sys.stdout, log))
        rc = run_mod._run([
            sys.executable, "-c",
            "import sys; print('hello-child-stdout'); "
            "sys.stderr.write('hello-child-stderr\\n')",
        ])
        log.close()
        content = log_path.read_text(encoding="utf-8")
        assert rc == 0
        assert "hello-child-stdout" in content
        assert "hello-child-stderr" in content   # stderr=STDOUT gộp chung

    def test_child_exit_code_still_propagates(self, tmp_path, monkeypatch):
        log = open(tmp_path / "l.log", "a", encoding="utf-8")
        monkeypatch.setattr(sys, "stdout", run_mod._Tee(sys.stdout, log))
        rc = run_mod._run([sys.executable, "-c", "raise SystemExit(2)"])
        log.close()
        assert rc == 2


class TestInstallRunLog:
    def test_header_written_and_prints_teed(self, tmp_path, monkeypatch):
        log_path = tmp_path / "run_daily.log"
        monkeypatch.setattr(run_mod, "RUN_LOG_PATH", log_path)
        # đăng ký stdout/stderr gốc để pytest tự trả lại sau test
        monkeypatch.setattr(sys, "stdout", sys.stdout)
        monkeypatch.setattr(sys, "stderr", sys.stderr)
        run_mod._install_run_log("all --thu-nghiem")
        print("dòng-sau-khi-tee")
        handle = sys.stdout._log
        handle.close()
        content = log_path.read_text(encoding="utf-8")
        assert "[run.py]" in content and "all --thu-nghiem" in content
        assert "dòng-sau-khi-tee" in content

    def test_unwritable_log_dir_does_not_break_startup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_mod, "RUN_LOG_PATH",
                            tmp_path / "khong-ton-tai" / "x" / "run_daily.log")
        before_out, before_err = sys.stdout, sys.stderr
        run_mod._install_run_log("doctor")     # không được nổ
        assert sys.stdout is before_out and sys.stderr is before_err


class TestTrim:
    def test_oversized_log_cut_to_tail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_mod, "_RUN_LOG_MAX_BYTES", 1_000)
        monkeypatch.setattr(run_mod, "_RUN_LOG_KEEP_BYTES", 200)
        p = tmp_path / "run_daily.log"
        p.write_bytes(b"A" * 5_000 + b"DUOI-PHAI-GIU-LAI")
        run_mod._trim_run_log(p)
        data = p.read_bytes()
        assert len(data) < 1_000
        assert data.endswith(b"DUOI-PHAI-GIU-LAI")
        assert data.startswith(b"[run.py]")

    def test_small_log_untouched(self, tmp_path):
        p = tmp_path / "run_daily.log"
        p.write_bytes(b"nho xiu")
        run_mod._trim_run_log(p)
        assert p.read_bytes() == b"nho xiu"


class TestWiringNets:
    """Net AST: ai gỡ tee/pipe là đỏ — tránh tái diễn vụ 11/08 (e)."""

    @staticmethod
    def _func_source(name: str) -> str:
        tree = ast.parse((REPO_ROOT / "run.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.unparse(node)
        raise AssertionError(f"run.py không còn hàm {name}")

    def test_main_installs_run_log_before_dispatch(self):
        src = self._func_source("main")
        assert "_install_run_log(" in src
        assert src.index("_install_run_log(") < src.index("_DISPATCH")

    def test_run_streams_children_through_pipe(self):
        src = self._func_source("_run")
        assert "Popen" in src and "PIPE" in src and "STDOUT" in src

    def test_strategy_loop_prints_tier_marker(self):
        # Bằng chứng "đêm nay train tầng nào" trong log = dòng tier=…
        src = (REPO_ROOT / "vnstock_train.py").read_text(encoding="utf-8")
        assert "tier={tier}" in src


class TestStepTiming:
    """Mục ② (14/08): cmd_all tự đo từng bước — số đo máy thật nằm sẵn trong
    run_daily.log mỗi đêm, khỏi cần phiên profiling riêng."""

    def test_summary_ranks_heaviest_first_and_totals_minutes(self):
        line = run_mod._format_step_summary(
            [("sync", 100.0), ("test", 300.0), ("brief", 20.0)])
        assert "⏱ TỔNG 7.0 phút (3 bước)" in line
        assert line.index("test 300s") < line.index("sync 100s") < \
            line.index("brief 20s")

    def test_summary_uses_en_thousands_format(self):
        line = run_mod._format_step_summary([("sync", 1234.5)])
        assert "sync 1,234s" in line     # quy ước format số EN của repo

    def test_cmd_all_wires_timing(self):
        # Net AST: ai gỡ đo giờ khỏi cmd_all là đỏ — số đo là đầu vào quyết ②
        src = TestWiringNets._func_source("cmd_all")
        assert "⏱" in src and "_format_step_summary" in src
