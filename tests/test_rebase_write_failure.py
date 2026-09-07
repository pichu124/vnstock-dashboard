"""Lưới cho ĐƯỜNG GHI HỎNG — ca thật trên desktop 07/09.

Lượt `--from-drift-ledger --whole-series --apply` chữa xong 4 mã rồi chết::

    [rebase] 💾 sao lưu: ...\\backup_rebase\\BRC_20260907-210744
    Traceback (most recent call last):
      File "...rebase_ticker_history.py", line 827, in _rebase_one
        os.replace(tmp, path)
    PermissionError: [WinError 5] Access is denied:
      '...\\ticker=BRC\\year=2011\\1efa...-0.18844.tmp' ->
      '...\\ticker=BRC\\year=2011\\1efa...-0.parquet'

Ba lỗi lộ ra cùng lúc, và cái thứ ba nặng nhất:

1. **Không retry.** Kho là junction vào Dropbox. `shutil.copytree` sao lưu vừa
   chạm mọi file xong thì Dropbox mở chính chúng để băm/tải lên — `os.replace`
   đâm vào khoá tạm ngay sau dòng "💾 sao lưu". Chờ một nhịp là qua.
2. **Rác `.tmp` ở lại** trong `prices/year=*/`, làm mọi bộ đếm file/năm sau đó
   đọc sai.
3. **Một mã ném ra ngoài giết CẢ LÔ.** 4/73 mã xong, 68 mã còn lại không bao
   giờ được sờ tới — mà lệnh vẫn là lệnh user được bảo chạy.

Và hình dạng đáng sợ nhất KHÔNG phải "hỏng ngay file đầu" (mã còn nguyên) mà
là **hỏng ở giữa**: một phần file đã sang cơ sở mới, phần còn lại giữ cơ sở
cũ. Tệ hơn cả hai đầu, và chạy lại đè lên chỉ làm nát thêm.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebase_ticker_history.py"
_spec = importlib.util.spec_from_file_location("rebase_ticker_history_wf", _SCRIPT)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """Retry phải đo được mà không bắt bộ test ngủ 6 giây mỗi lượt."""
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)


class TestAtomicReplaceRetries:
    def test_a_transient_lock_is_ridden_out(self, tmp_path, monkeypatch):
        """Đúng ca Dropbox: khoá vài trăm ms rồi nhả."""
        src, dst = tmp_path / "a.tmp", tmp_path / "a.parquet"
        src.write_text("moi")
        dst.write_text("cu")
        calls = {"n": 0}
        real = os.replace

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("[WinError 5] Access is denied")
            return real(a, b)

        monkeypatch.setattr(R.os, "replace", flaky)
        R._atomic_replace(src, dst)
        assert dst.read_text() == "moi" and calls["n"] == 3

    def test_a_permanent_lock_raises_and_names_the_culprit(
            self, tmp_path, monkeypatch):
        """Báo "Access is denied" trần trụi thì user không biết làm gì. Kho
        nằm trong Dropbox — phải NÓI RA."""
        src, dst = tmp_path / "a.tmp", tmp_path / "a.parquet"
        src.write_text("x"); dst.write_text("y")
        monkeypatch.setattr(R.os, "replace", lambda *a: (_ for _ in ()).throw(
            PermissionError("[WinError 5]")))
        with pytest.raises(PermissionError) as ei:
            R._atomic_replace(src, dst)
        assert "Dropbox" in str(ei.value) and "antivirus" in str(ei.value)

    def test_the_readonly_bit_is_cleared_on_the_FIRST_failure(
            self, tmp_path, monkeypatch):
        """Bit read-only KHÔNG tự hết theo thời gian — ngủ đủ 5 lượt rồi mới
        báo hỏng là 6 giây phí cho một ca retry không bao giờ cứu được."""
        src, dst = tmp_path / "a.tmp", tmp_path / "a.parquet"
        src.write_text("x"); dst.write_text("y")
        seen = []
        monkeypatch.setattr(R.os, "chmod", lambda p, m: seen.append(m))
        n = {"i": 0}
        real = os.replace

        def flaky(a, b):
            n["i"] += 1
            if n["i"] == 1:
                raise PermissionError("read-only")
            return real(a, b)

        monkeypatch.setattr(R.os, "replace", flaky)
        R._atomic_replace(src, dst)
        assert seen, "không thử gỡ read-only lần hỏng đầu"

    def test_it_never_falls_back_to_a_plain_copy(self):
        """Rơi về copy-đè là phá đúng bất biến `_MUST_BE_ATOMIC` mà retry sinh
        ra để giữ — đọc-giữa-chừng sẽ thấy file nửa vời."""
        import inspect
        src = inspect.getsource(R._atomic_replace)
        assert "copyfile" not in src and "copy2" not in src


class TestTmpCleanup:
    def test_it_removes_only_this_run_s_tmp_files(self, tmp_path):
        d = tmp_path / "year=2011"
        d.mkdir(parents=True)
        mine = d / f"a.{os.getpid()}.tmp"
        other = d / "b.99999999.tmp"
        keep = d / "c.parquet"
        for f in (mine, other, keep):
            f.write_text("x")
        assert R._sweep_tmp(tmp_path) == 1
        assert not mine.exists()
        assert other.exists(), "xoá tmp của tiến trình KHÁC là phá lượt chạy khác"
        assert keep.exists()

    def test_it_never_raises_on_a_missing_dir(self, tmp_path):
        assert R._sweep_tmp(tmp_path / "khongco") == 0


class TestBatchSurvivesOneBadTicker:
    def _run(self, tmp_path, monkeypatch, rcs):
        seen = []

        def fake(tk, *a, **k):
            seen.append(tk)
            out = rcs.get(tk, 0)
            if isinstance(out, Exception):
                raise out
            return out

        monkeypatch.setattr(R, "_rebase_one", fake)
        monkeypatch.setattr(R, "_drift_ledger_targets",
                            lambda wh: list(rcs.keys()))
        rc = R.main(["--warehouse", str(tmp_path), "--from-drift-ledger"])
        return seen, rc

    def test_a_raising_ticker_does_not_kill_the_batch(self, tmp_path,
                                                      monkeypatch, capsys):
        """Vết 07/09: BRC ném PermissionError ⇒ 68/73 mã còn lại không bao giờ
        được sờ tới, mà đó vẫn là lệnh user được bảo chạy."""
        seen, rc = self._run(tmp_path, monkeypatch, {
            "AAM": 0, "BRC": PermissionError("WinError 5"), "CTI": 0})
        assert seen == ["AAM", "BRC", "CTI"]
        assert rc != 0
        assert "LỖI KHÔNG LƯỜNG" in capsys.readouterr().out

    def test_a_failed_ticker_is_reported_not_counted_as_done(
            self, tmp_path, monkeypatch, capsys):
        self._run(tmp_path, monkeypatch,
                  {"AAM": 0, "BRC": PermissionError("x"), "CTI": 0})
        out = capsys.readouterr().out
        assert "2/3 mã xong" in out and "BRC" in out

    def test_three_write_failures_in_a_row_stop_the_run(
            self, tmp_path, monkeypatch, capsys):
        """Hỏng GHI liên tiếp là chuyện của cả thư mục. Cày tiếp 70 mã để hỏng
        70 lần là phí một tiếng và đẻ 70 thư mục sao lưu vô ích."""
        seen, _ = self._run(tmp_path, monkeypatch,
                            {"A": 2, "B": 2, "C": 2, "D": 0, "E": 0})
        assert seen == ["A", "B", "C"]
        assert "DỪNG SỚM" in capsys.readouterr().out

    def test_a_plain_refusal_does_NOT_stop_the_run(self, tmp_path,
                                                   monkeypatch):
        """Từ chối (rc=1) là kết luận về MỘT mã — hoàn toàn khác hỏng ghi.
        Dừng sớm vì nó là bỏ dở cả lô vì những mã vốn không định chữa."""
        seen, _ = self._run(tmp_path, monkeypatch,
                            {"A": 1, "B": 1, "C": 1, "D": 1, "E": 0})
        assert len(seen) == 5


class TestPartialWriteIsCalledOut:
    def _plan(self, tmp_path, monkeypatch, fail_at):
        """Kho 3 file; `os.replace` hỏng ở lần thứ `fail_at` (1-based)."""
        tdir = tmp_path / "prices" / "ticker=BRC"
        for y in (2024, 2025, 2026):
            (tdir / f"year={y}").mkdir(parents=True)
            pd.DataFrame({"time": [pd.Timestamp(f"{y}-03-01")],
                          "close": [10.0]}).to_parquet(
                tdir / f"year={y}" / "p.parquet", index=False)
        n = {"i": 0}
        real = os.replace

        def flaky(a, b):
            n["i"] += 1
            if n["i"] >= fail_at:
                raise PermissionError("[WinError 5] Access is denied")
            return real(a, b)

        monkeypatch.setattr(R.os, "replace", flaky)
        return tdir

    def _fake_rebase_write(self, tmp_path, tdir):
        """Chạy đúng khối GHI của `_rebase_one` qua một plan dựng tay."""
        plan = {p: pd.read_parquet(p)
                for p in sorted(tdir.glob("year=*/*.parquet"))}
        done = []
        try:
            for path, out in plan.items():
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                out.to_parquet(tmp, index=False)
                R._atomic_replace(tmp, path)
                done.append(path)
        except Exception:
            R._sweep_tmp(tdir)
            return done, len(plan)
        return done, len(plan)

    def test_failing_on_the_first_file_leaves_nothing_half_done(
            self, tmp_path, monkeypatch):
        """Đúng ca BRC: `year=2011` là file ĐẦU theo thứ tự sắp xếp ⇒ chưa
        file nào bị thay ⇒ mã còn NGUYÊN."""
        tdir = self._plan(tmp_path, monkeypatch, fail_at=1)
        done, total = self._fake_rebase_write(tmp_path, tdir)
        assert done == [] and total == 3

    def test_no_tmp_file_survives_a_failure(self, tmp_path, monkeypatch):
        tdir = self._plan(tmp_path, monkeypatch, fail_at=2)
        self._fake_rebase_write(tmp_path, tdir)
        assert not list(tdir.glob("year=*/*.tmp"))

    def test_the_message_tells_the_user_NOT_to_rerun_over_a_partial_write(self):
        """Chạy lại đè lên một mã đang lẫn hai cơ sở chỉ làm nát thêm: bộ đo
        hệ số sẽ đọc trúng hỗn hợp."""
        import inspect
        src = inspect.getsource(R._rebase_one)
        assert "LẪN HAI CƠ SỞ" in src and "ĐỪNG chạy lại" in src
        assert "--restore" in src


class TestRestore:
    def _backed_up(self, tmp_path):
        tdir = tmp_path / "prices" / "ticker=BRC" / "year=2011"
        tdir.mkdir(parents=True)
        good = pd.DataFrame({"time": [pd.Timestamp("2011-03-01")],
                             "close": [10.0]})
        good.to_parquet(tdir / "p.parquet", index=False)
        bak = tmp_path / "_meta" / "backup_rebase" / "BRC_20260907-210744"
        (bak / "year=2011").mkdir(parents=True)
        good.to_parquet(bak / "year=2011" / "p.parquet", index=False)
        # kho bị ghi hỏng: giá sang cơ sở khác
        bad = good.copy(); bad["close"] = 14.9
        bad.to_parquet(tdir / "p.parquet", index=False)
        return tdir / "p.parquet"

    def test_it_puts_the_backup_back(self, tmp_path):
        pq = self._backed_up(tmp_path)
        assert R._restore_one("BRC", tmp_path, apply=True) == 0
        assert pd.read_parquet(pq)["close"].iloc[0] == pytest.approx(10.0)

    def test_dry_run_changes_nothing(self, tmp_path):
        pq = self._backed_up(tmp_path)
        assert R._restore_one("BRC", tmp_path, apply=False) == 0
        assert pd.read_parquet(pq)["close"].iloc[0] == pytest.approx(14.9)

    def test_it_picks_the_NEWEST_backup(self, tmp_path):
        self._backed_up(tmp_path)
        older = tmp_path / "_meta" / "backup_rebase" / "BRC_20260101-000000"
        (older / "year=2011").mkdir(parents=True)
        pd.DataFrame({"time": [pd.Timestamp("2011-03-01")],
                      "close": [99.0]}).to_parquet(
            older / "year=2011" / "p.parquet", index=False)
        assert R._newest_backup("BRC", tmp_path).name == "BRC_20260907-210744"

    def test_a_missing_backup_is_a_refusal_not_a_crash(self, tmp_path, capsys):
        assert R._restore_one("KHONGCO", tmp_path, apply=True) == 1
        assert "không có bản sao lưu" in capsys.readouterr().out

    def test_an_EMPTY_backup_never_wipes_the_warehouse(self, tmp_path, capsys):
        """Khôi phục từ một thư mục rỗng mà "thành công" là xoá sạch kho của
        mã — hỏng nặng hơn hẳn thứ đang chữa."""
        pq = self._backed_up(tmp_path)
        empty = tmp_path / "_meta" / "backup_rebase" / "BRC_20261231-235959"
        empty.mkdir(parents=True)
        assert R._restore_one("BRC", tmp_path, apply=True) == 1
        assert pd.read_parquet(pq)["close"].iloc[0] == pytest.approx(14.9)
        assert "RỖNG" in capsys.readouterr().out

    def test_restore_reaches_the_cli(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(R, "_restore_one",
                            lambda tk, wh, apply: seen.append((tk, apply)) or 0)
        R.main(["--ticker", "BRC", "--warehouse", str(tmp_path), "--restore",
                "--apply"])
        assert seen == [("BRC", True)]

    def test_restore_never_rebases(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "_restore_one", lambda *a, **k: 0)
        monkeypatch.setattr(R, "_rebase_one",
                            lambda *a, **k: pytest.fail("không được chữa"))
        R.main(["--ticker", "BRC", "--warehouse", str(tmp_path), "--restore"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


class TestStaleLedgerEntry:
    """Vết ACE, 07/09 — **vòng tự khoá thứ ba**.

    ACE chữa xong lúc 21:07, in *"✅ chuỗi đã liền … bộ dò MỨC cũng sạch"*.
    Lượt 21:20 đo lại: `tỉ lệ 1.0000× — kho KHÔNG lệch` ⇒ **chữa đã ăn**. Vậy
    mà ACE **vẫn nằm trong sổ cách ly**, và lượt đó từ chối nó (rc=1).

    Hai lỗi chồng nhau:

    1. `clear_drift` trả `None` và nuốt sạch ngoại lệ ⇒ chỗ gọi không có cách
       nào biết là hỏng. Dropbox đang giữ file đúng phút ấy (BRC chết vì
       `WinError 5` ngay sau đó).
    2. Ca "kho đã sạch mà sổ còn giữ mã" rơi vào nhánh TỪ CHỐI. Mà
       `clear_drift` **chỉ có đúng một chỗ gọi** — chính công cụ này. Không ai
       khác xoá sổ ⇒ mã sạch nằm lại VĨNH VIỄN, badge doctor warn mãi.

    Kết cục quen thuộc: badge đỏ cho một mã sạch, tức dạy người dùng bỏ qua
    badge — đúng thứ cả loạt bản vá này sinh ra để chặn.
    """

    def _stale(self, monkeypatch, tmp_path, aligned=True, pend=True):
        (tmp_path / "prices" / "ticker=ACE").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(R, "_basis_break_of", lambda *a, **k: None)
        monkeypatch.setattr(R, "_level_break_of", lambda *a, **k: {"break": None})
        monkeypatch.setattr(R, "_level_divergence", lambda *a, **k: None)
        monkeypatch.setattr(R, "_in_drift_ledger", lambda *a, **k: pend)
        monkeypatch.setattr(R, "_uniform_probe", lambda *a, **k: {
            "aligned": aligned, "uniform": False, "n": 240, "ratio": 1.0,
            "spread": 1.0009, "why": "tỉ lệ 1.0000× nằm trong ngưỡng 0.012"})
        import check_unit_continuity as cuc
        monkeypatch.setattr(cuc, "load_bars", lambda *a, **k: [], raising=False)
        import probe_price_basis as ppb
        monkeypatch.setattr(ppb, "_find_break", lambda *a, **k: None)

    def test_a_clean_ticker_still_in_the_ledger_gets_CLEARED_not_refused(
            self, tmp_path, monkeypatch, capsys):
        self._stale(monkeypatch, tmp_path)
        seen = []
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift",
                            lambda wh, tk: seen.append(tk) or True)
        rc = R._rebase_one("ACE", tmp_path, apply=True)
        assert rc == 0 and seen == ["ACE"]
        assert "bản ghi cũ" in capsys.readouterr().out

    def test_it_does_not_need_the_whole_series_flag(self, tmp_path,
                                                    monkeypatch):
        """Xoá một bản ghi cũ là việc NHỎ. Bắt user gõ cờ ghi-đè-trọn-lịch-sử
        cho nó là dạy sai thói quen."""
        self._stale(monkeypatch, tmp_path)
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift", lambda wh, tk: True)
        assert R._rebase_one("ACE", tmp_path, apply=True,
                             whole_series=False) == 0

    def test_dry_run_does_not_touch_the_ledger(self, tmp_path, monkeypatch):
        self._stale(monkeypatch, tmp_path)
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift",
                            lambda wh, tk: pytest.fail("không được ghi sổ"))
        assert R._rebase_one("ACE", tmp_path, apply=False) == 0

    def test_a_ticker_NOT_in_the_ledger_is_just_clean(self, tmp_path,
                                                      monkeypatch, capsys):
        """Không có trong sổ thì không có gì để xoá — đừng bịa ra một hành
        động."""
        self._stale(monkeypatch, tmp_path, pend=False)
        assert R._rebase_one("ACE", tmp_path, apply=True) == 0
        assert "bản ghi cũ" not in capsys.readouterr().out

    def test_an_unmeasurable_ticker_is_NEVER_cleared(self, tmp_path,
                                                     monkeypatch):
        """`aligned=False` gồm cả "không đo được". Xoá khỏi sổ vì KHÔNG BIẾT
        là gỡ cách ly cho một mã mình không có thông tin gì — ngược hẳn với
        việc cửa gác sinh ra để làm."""
        self._stale(monkeypatch, tmp_path, aligned=False)
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift",
                            lambda wh, tk: pytest.fail("không được xoá sổ"))
        assert R._rebase_one("ACE", tmp_path, apply=True) == 1

    def test_a_failed_clear_is_reported_not_swallowed(self, tmp_path,
                                                      monkeypatch, capsys):
        self._stale(monkeypatch, tmp_path)
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg, "clear_drift", lambda wh, tk: False)
        rc = R._rebase_one("ACE", tmp_path, apply=True)
        out = capsys.readouterr().out
        assert rc == 1 and "KHÔNG xoá được khỏi sổ" in out

    def test_the_aligned_flag_is_machine_readable_not_a_vietnamese_string(self):
        """Rẽ nhánh bằng cách dò chuỗi `why` là buộc logic vào câu chữ tiếng
        Việt — sửa một dấu phẩy là gãy im lặng."""
        import inspect
        src = inspect.getsource(R._rebase_one)
        assert '"aligned"' in src or "'aligned'" in src
        assert "kho KHÔNG lệch" not in src


class TestClearDriftContract:
    def test_it_reports_success_as_a_bool(self, tmp_path):
        import vnstock_basis_guard as bg
        monkeypatch_path = tmp_path / "_meta"
        monkeypatch_path.mkdir()
        bg.record_drift(tmp_path, "ACE", {"ratio": 1.08, "pct": 8.0, "n": 30})
        assert bg.clear_drift(tmp_path, "ACE") is True
        assert "ACE" not in bg.load_pending(tmp_path)

    def test_clearing_an_absent_ticker_is_success_not_failure(self, tmp_path):
        """Ý muốn là "mã không còn trong sổ". Vốn đã không có thì ý muốn đã
        đạt — trả False ở đây là đẻ ra một cảnh báo giả mỗi lượt."""
        import vnstock_basis_guard as bg
        assert bg.clear_drift(tmp_path, "KHONGCO") is True

    def test_a_locked_ledger_returns_False_instead_of_lying(self, tmp_path,
                                                            monkeypatch):
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg.time, "sleep", lambda *_: None)
        bg.record_drift(tmp_path, "ACE", {"ratio": 1.08, "pct": 8.0, "n": 30})
        monkeypatch.setattr(bg.os, "replace",
                            lambda *a: (_ for _ in ()).throw(
                                PermissionError("[WinError 5]")))
        assert bg.clear_drift(tmp_path, "ACE") is False

    def test_it_never_raises(self, tmp_path, monkeypatch):
        """Nó bị gọi từ những chỗ mà một lỗi ghi sổ không được phép làm hỏng
        cả lượt chạy."""
        import vnstock_basis_guard as bg
        monkeypatch.setattr(bg.time, "sleep", lambda *_: None)
        monkeypatch.setattr(bg, "load_pending",
                            lambda wh: (_ for _ in ()).throw(IOError("hỏng")))
        assert bg.clear_drift(tmp_path, "ACE") is False
