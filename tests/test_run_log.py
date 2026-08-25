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


    def test_write_none_never_raises(self):
        """Bài học 15/08: cmd_test đưa proc.stdout=None vào tee (chuỗi decode
        cp1252 chết trên máy bàn) → len(None) nổ NGOÀI try, giết cả pipeline
        dù lời hứa của tee là best-effort trọn vẹn. None phải thành no-op."""
        console = io.StringIO()
        tee = run_mod._Tee(console, io.StringIO())
        assert tee.write(None) == 0            # không nổ, không ghi gì
        assert console.getvalue() == ""

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

    def test_oversized_log_is_rotated_not_destroyed(self, tmp_path, monkeypatch):
        """Chính sách CŨ vứt 80% log vĩnh viễn — nó đã xoá bằng chứng phát
        18/08, rồi cắt tiếp một lần nữa ngay tối 19/08 giữa lúc đang gỡ."""
        monkeypatch.setattr(run_mod, "_RUN_LOG_MAX_BYTES", 1_000)
        monkeypatch.setattr(run_mod, "_RUN_LOG_KEEP_BYTES", 200)
        p = tmp_path / "run_daily.log"
        p.write_bytes(b"DAU-PHAI-CON-O-DOI-1" + b"A" * 5_000 + b"DUOI")
        run_mod._trim_run_log(p)
        gen1 = tmp_path / "run_daily.1.log"
        assert gen1.exists(), "log cũ bị vứt thay vì xoay vòng"
        assert gen1.read_bytes().startswith(b"DAU-PHAI-CON-O-DOI-1")
        assert p.read_bytes().endswith(b"DUOI")      # file mới vẫn liền ngữ cảnh

    def test_rotation_keeps_a_bounded_number_of_generations(self, tmp_path,
                                                            monkeypatch):
        monkeypatch.setattr(run_mod, "_RUN_LOG_MAX_BYTES", 1_000)
        monkeypatch.setattr(run_mod, "_RUN_LOG_KEEP_BYTES", 50)
        monkeypatch.setattr(run_mod, "_RUN_LOG_KEEP_GENERATIONS", 2)
        p = tmp_path / "run_daily.log"
        for marker in (b"DOI-A", b"DOI-B", b"DOI-C"):
            p.write_bytes(marker + b"Z" * 5_000)
            run_mod._trim_run_log(p)
        assert (tmp_path / "run_daily.1.log").read_bytes().startswith(b"DOI-C")
        assert (tmp_path / "run_daily.2.log").read_bytes().startswith(b"DOI-B")
        assert not (tmp_path / "run_daily.3.log").exists()   # đời quá hạn đã bỏ

    def test_rotation_failure_falls_back_to_the_old_cut(self, tmp_path,
                                                        monkeypatch):
        """Xoay vòng hỏng (file bị khoá) vẫn phải chặn log phình vô hạn."""
        monkeypatch.setattr(run_mod, "_RUN_LOG_MAX_BYTES", 1_000)
        monkeypatch.setattr(run_mod, "_RUN_LOG_KEEP_BYTES", 200)
        monkeypatch.setattr(run_mod, "_rotate_run_log",
                            lambda _p: (_ for _ in ()).throw(PermissionError("khoá")))
        p = tmp_path / "run_daily.log"
        p.write_bytes(b"A" * 5_000 + b"DUOI")
        run_mod._trim_run_log(p)
        assert len(p.read_bytes()) < 1_000 and p.read_bytes().endswith(b"DUOI")
        assert not (tmp_path / "run_daily.1.log").exists()

    def test_small_log_untouched(self, tmp_path):
        p = tmp_path / "run_daily.log"
        p.write_bytes(b"nho xiu")
        run_mod._trim_run_log(p)
        assert p.read_bytes() == b"nho xiu"
        assert not (tmp_path / "run_daily.1.log").exists()


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


    def test_cmd_test_captures_with_explicit_encoding(self):
        # Bug 15/08: capture pytest không khai encoding → Windows cp1252
        # chết giữa chừng, proc.stdout=None. Net canh encoding tường minh.
        src = self._func_source("cmd_test")
        assert "encoding" in src and "utf-8" in src

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
        assert "7.0 phút (3 bước)" in line
        assert line.index("test 300s") < line.index("sync 100s") < \
            line.index("brief 20s")

    def test_summary_carries_the_run_timestamp(self):
        """`run_daily.log` xoay vòng và giữ nhiều đêm trong MỘT file, còn dòng
        `⏱` thì trần trụi không mang ngày. Vết 25/08: grep ra 4 dòng `⏱` mà
        không ai biết dòng nào của đêm nào ⇒ phép đo "bản vá có nhanh hơn
        không" phải chờ thêm một đêm chỉ vì thiếu 16 ký tự."""
        from datetime import datetime
        line = run_mod._format_step_summary(
            [("sync", 100.0)], now=datetime(2026, 8, 26, 18, 5))
        assert "[2026-08-26 18:05]" in line

    def test_the_stamp_sits_between_the_label_and_the_number(self):
        # Grep vẫn phải bắt được "⏱ TỔNG", và mắt vẫn đọc được số ngay sau dấu
        from datetime import datetime
        line = run_mod._format_step_summary(
            [("sync", 100.0)], now=datetime(2026, 8, 26, 18, 5))
        assert line.index("⏱ TỔNG") < line.index("[2026-08-26") < \
            line.index("1.7 phút")

    def test_stage_line_is_stamped_too(self):
        import inspect
        src = inspect.getsource(run_mod._print_sync_breakdown)
        assert "_stamp()" in src and "⏱ CHẶNG" in src

    def test_summary_uses_en_thousands_format(self):
        line = run_mod._format_step_summary([("sync", 1234.5)])
        assert "sync 1,234s" in line     # quy ước format số EN của repo

    def test_cmd_all_wires_timing(self):
        # Net AST: ai gỡ đo giờ khỏi cmd_all là đỏ — số đo là đầu vào quyết ②
        src = TestWiringNets._func_source("cmd_all")
        assert "⏱" in src and "_format_step_summary" in src


# ── Log vận hành phải SẠCH: chỉ dấu vết pipeline thật (thêm 19/08) ──────────
#
# Vấp thật 19/08: `run_daily.log` phình qua 5 MB → `_trim_run_log` cắt còn 1 MB
# → mất sạch dấu vết phát chạy 18/08, nên không truy được vì sao brief không
# gửi. Hai nguồn rác, vá cả hai:
#   (a) bước `test` echo output `pytest -v` (1 dòng/test) qua _Tee vào log;
#   (b) `tests/test_run.py` gọi `main()` 10 lần → 9 khối header GIẢ.

class TestRunLogStaysClean:

    def _src(self, name):
        import inspect, run as runpy
        return inspect.getsource(getattr(runpy, name))

    def test_pytest_not_run_verbose_so_log_does_not_explode(self):
        """`-v` đẻ 1 dòng/test (đo được 2.204 dòng mỗi lần chạy full) mà KHÔNG
        cho phản hồi tiến độ nào — output bị capture rồi mới echo một lần."""
        src = self._src("cmd_test")
        assert '"-v"' not in src, "cmd_test dùng lại -v → log lại phình"
        assert '"-q"' in src

    def test_failed_tests_still_named_in_output(self):
        """Bỏ `-v` KHÔNG được làm mất tên test đỏ — đó là thứ duy nhất người
        đọc log cần khi pipeline dừng cứng ở bước test."""
        src = self._src("cmd_test")
        assert '"-r", "fE"' in src or '"-rfE"' in src

    def test_install_run_log_is_a_noop_on_the_real_log_under_pytest(self):
        """Test gọi run.main() KHÔNG được ghi vào log VẬN HÀNH (đường thật)."""
        import run as runpy
        real = runpy.REPO_ROOT / "run_daily.log"
        before = real.read_bytes() if real.exists() else None
        real_stdout = sys.stdout
        runpy._install_run_log("--warehouse data_warehouse all")
        assert sys.stdout is real_stdout, "không được thay stdout khi dưới pytest"
        after = real.read_bytes() if real.exists() else None
        assert after == before, "đã ghi vào run_daily.log vận hành khi chạy test"

    def test_guard_is_narrow_redirected_log_still_written(self, tmp_path, monkeypatch):
        """Cửa chặn chỉ né ĐÚNG file vận hành: test cố tình kiểm cơ chế (trỏ
        RUN_LOG_PATH sang tmp_path) vẫn phải chạy đủ đường — chặn rộng hơn là
        tự vô hiệu hoá lưới canh chính nó."""
        import run as runpy
        log = tmp_path / "run_daily.log"
        monkeypatch.setattr(runpy, "RUN_LOG_PATH", log)
        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            runpy._install_run_log("--warehouse data_warehouse all")
            print("duong-chuyen-huong")
            sys.stdout.flush()
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
        assert log.exists() and "duong-chuyen-huong" in log.read_text(encoding="utf-8")


class TestSyncReportsItsOwnBreakdown:
    """`sync` là bước nặng nhất (60' đêm 18/08 = 62% tổng) nhưng nó gộp 4 việc
    khác bản chất — dòng ⏱ ở cmd_all chỉ nói "sync lâu", không nói lâu ở đâu.
    Thiếu số thì tối ưu là đoán mò (bẫy đã tránh khi chấm mục ②)."""

    def _src(self, name):
        import inspect, run as runpy
        return inspect.getsource(getattr(runpy, name))

    def test_all_four_stages_are_timed(self):
        src = self._src("cmd_sync")
        for stage in ("updater", "rollup", "fix-units", "auto-heal"):
            assert f'_timed("{stage}"' in src, f"chặng {stage} không được đo"

    def test_breakdown_printed_even_when_a_stage_fails_hard(self):
        """Chặng chết giữa chừng là lúc CẦN số nhất — không được im."""
        src = self._src("cmd_sync")
        assert src.count("_print_sync_breakdown(_sub)") >= 3

    def test_breakdown_ranks_heaviest_first(self):
        import run as runpy
        out = []
        runpy._print_sync_breakdown([("updater", 60.0), ("fix-units", 900.0),
                                     ("rollup", 30.0)])
        src = self._src("_print_sync_breakdown")
        assert "sorted" in src and "-nd[1]" in src

    def test_fix_units_reports_scan_size_even_with_zero_fixes(self):
        """Bước này quét TOÀN KHO mỗi đêm; "không tìm thấy gì" vẫn tốn đúng
        ngần ấy I/O, nên con số scanned phải hiện để quyết có thu hẹp không."""
        src = self._src("cmd_sync")
        assert "scanned_tickers" in src and "scanned_bars" in src
        assert "if report.fixes:" not in src, "vẫn giấu số khi không có fix"
