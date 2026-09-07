"""
Lưới cho `scripts/triage_basis_drift.py` — soi sổ cách ly lệch cơ sở.

Bối cảnh 26/08: `run.py doctor` báo **47 mã ĐANG KHÔNG cập nhật giá**. Cửa
gác làm đúng việc (chặn không nối data lệch cơ sở), nhưng chặn xong thì chờ
người chữa — và ngày phát hiện trải từ 21/08 đến 25/08, tức nó **đang tích
tụ**, không phải một cục cũ.

Điều mà "47 mã" KHÔNG nói được là **mỗi mã lệch vì sao**, và đó mới là thứ
quyết định cách xử lý:

* có sự kiện quyền khớp ngày vách ⇒ chữa máy móc, hàng loạt;
* không sự kiện nào ⇒ **chữa mù là nhân bản một con số sai lên toàn bộ lịch
  sử của mã**, đúng thứ cửa gác sinh ra để chặn.

Vì thế lưới ở đây canh chặt hai điều: **không nhóm nào bị nuốt**, và **gợi ý
không bao giờ được trình bày như kết luận**.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "triage_basis_drift.py"
_spec = importlib.util.spec_from_file_location("triage_basis_drift", _SCRIPT)
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

TODAY = date(2026, 8, 26)


def _rec(detected="2026-08-24", ratio=1.05, pct=5.0, event=None):
    return {"detected_at": detected, "ratio": ratio, "pct": pct, "event": event}


class TestDaysStale:
    def test_counts_days_since_detection(self):
        assert T.days_stale("2026-08-21", TODAY) == 5

    def test_same_day_is_zero(self):
        assert T.days_stale("2026-08-26", TODAY) == 0

    def test_a_future_date_never_goes_negative(self):
        assert T.days_stale("2026-09-01", TODAY) == 0

    def test_a_timestamp_is_accepted(self):
        assert T.days_stale("2026-08-21T18:03:11", TODAY) == 5

    def test_an_unreadable_date_is_none_not_zero(self):
        """None nghĩa là KHÔNG ĐO ĐƯỢC. Trả 0 sẽ đọc thành 'mới phát hiện hôm
        nay' — trình bày cái chưa biết thành một phép đo."""
        assert T.days_stale("rác", TODAY) is None
        assert T.days_stale("", TODAY) is None


class TestNearRoundRatio:
    def test_a_ten_percent_bonus_is_recognised(self):
        assert T.near_round_ratio(1.1) == 1.10

    def test_a_slightly_off_ratio_still_matches(self):
        assert T.near_round_ratio(1.098) == 1.10

    def test_the_tolerance_is_tight_enough_to_mean_something(self):
        """Các mốc cách nhau 0,05. Nới rộng là bắt nhầm gần một phần ba dải:
        1.0424 "khớp" 1.05 rồi tụt khỏi nhóm ĐỎ — đúng nhóm cần người nhìn."""
        assert T.near_round_ratio(1.0424) is None
        assert T.near_round_ratio(1.1098) is None

    def test_an_odd_ratio_matches_nothing(self):
        assert T.near_round_ratio(1.0424) is None

    def test_a_two_for_one_split_is_recognised(self):
        assert T.near_round_ratio(2.0) == 2.00

    def test_garbage_does_not_raise(self):
        assert T.near_round_ratio(None) is None
        assert T.near_round_ratio("x") is None


class TestClassify:
    def test_a_matched_event_is_the_safe_group(self):
        assert T.classify(_rec(event="stock")) == "co_su_kien"

    def test_an_event_wins_even_when_the_ratio_is_odd(self):
        """Sự kiện là BẰNG CHỨNG, tỉ lệ tròn chỉ là gợi ý. Bằng chứng thắng."""
        assert T.classify(_rec(ratio=1.0371, pct=3.71, event="cash")) == "co_su_kien"

    def test_a_round_ratio_without_an_event_is_only_a_hint(self):
        assert T.classify(_rec(ratio=1.1015, pct=10.15)) == "tron_chua_ro"

    def test_an_odd_ratio_without_an_event_is_the_red_group(self):
        assert T.classify(_rec(ratio=1.0424, pct=4.24)) == "chua_ro"

    def test_a_tiny_drift_is_noise_not_a_mystery(self):
        assert T.classify(_rec(ratio=1.008, pct=0.8)) == "nhieu"

    def test_a_tiny_drift_WITH_an_event_is_still_the_safe_group(self):
        assert T.classify(_rec(ratio=1.008, pct=0.8, event="cash")) == "co_su_kien"

    def test_a_missing_pct_does_not_crash(self):
        assert T.classify({"ratio": 1.0424}) in T.NHOM_ORDER

    def test_every_class_has_a_label_and_a_reason(self):
        """Nhóm không có nhãn = nhóm bị nuốt lúc in ra."""
        assert set(T.NHOM) == set(T.NHOM_ORDER)
        assert all(len(v) == 2 and all(v) for v in T.NHOM.values())


class TestSummarize:
    PENDING = {
        "AAM": _rec("2026-08-24", 1.0424, 4.24),
        "BCF": _rec("2026-08-21", 1.1015, 10.15),   # sát 1.10 → chỉ là GỢI Ý
        "VCB": _rec("2026-08-25", 1.10, 10.0, event="stock"),
        "XYZ": _rec("2026-08-25", 1.008, 0.8),
    }

    def test_every_ticker_lands_in_exactly_one_group(self):
        st = T.summarize(self.PENDING, TODAY)
        landed = [r["ticker"] for g in st["groups"].values() for r in g]
        assert sorted(landed) == sorted(self.PENDING)
        assert len(landed) == len(set(landed))

    def test_the_total_matches_the_input(self):
        assert T.summarize(self.PENDING, TODAY)["total"] == 4

    def test_the_worst_staleness_is_reported(self):
        assert T.summarize(self.PENDING, TODAY)["max_stale"] == 5

    def test_lost_bars_are_summed_across_tickers(self):
        """Con số này là thứ đọc ra được TÁC ĐỘNG: 47 mã × mấy ngày = bao
        nhiêu bar giá đang thiếu trong kho."""
        assert T.summarize(self.PENDING, TODAY)["bars_lost"] == 2 + 5 + 1 + 1

    def test_tickers_come_out_sorted(self):
        st = T.summarize(self.PENDING, TODAY)
        red = [r["ticker"] for r in st["groups"]["chua_ro"]]
        assert red == sorted(red)

    def test_an_empty_ledger_gives_empty_groups_not_a_crash(self):
        st = T.summarize({}, TODAY)
        assert st["total"] == 0 and st["max_stale"] is None

    def test_the_input_is_not_mutated(self):
        """Sổ cách ly là dữ liệu thật của kho — bộ soi CHỈ ĐỌC."""
        import copy
        before = copy.deepcopy(self.PENDING)
        T.summarize(self.PENDING, TODAY)
        assert self.PENDING == before

    def test_an_unreadable_date_does_not_drop_the_ticker(self):
        st = T.summarize({"AAA": _rec("rác", 1.0424, 4.24)}, TODAY)
        assert st["groups"]["chua_ro"][0]["stale"] is None
        assert st["total"] == 1


class TestVn30Hits:
    def test_a_quarantined_vn30_name_is_surfaced(self):
        assert T.vn30_hits({"VCB": {}, "AAM": {}}, ["VCB", "FPT"]) == ["VCB"]

    def test_matching_is_case_insensitive(self):
        assert T.vn30_hits({"vcb": {}}, ["VCB"]) == ["VCB"]

    def test_nothing_in_the_basket_gives_nothing(self):
        assert T.vn30_hits({"AAM": {}}, ["VCB"]) == []

    def test_a_missing_basket_does_not_crash(self):
        assert T.vn30_hits({"AAM": {}}, None) == []


class TestBatchPlan:
    def test_the_safe_group_gets_a_dry_run_BEFORE_the_apply(self):
        """Chạy thử trước là bất biến, không phải phép lịch sự: `--apply` ghi
        đè lịch sử giá của mã."""
        st = T.summarize(TestSummarize.PENDING, TODAY)
        cmds = [c for _, c in T.batch_plan(st["groups"])]
        dry = next(i for i, c in enumerate(cmds)
                   if "rebase" in c and "--apply" not in c)
        apply_i = next(i for i, c in enumerate(cmds) if "--apply" in c)
        assert dry < apply_i

    def test_the_red_group_never_appears_in_a_rebase_command(self):
        """Đây là bất biến QUAN TRỌNG NHẤT của file này. Gộp một mã chưa rõ
        nguyên nhân vào lệnh chữa hàng loạt là nhân bản số sai."""
        st = T.summarize(TestSummarize.PENDING, TODAY)
        rebase = [c for _, c in T.batch_plan(st["groups"]) if "rebase" in c]
        assert all("AAM" not in c for c in rebase)

    def test_the_round_but_unmatched_group_is_also_kept_out_of_rebase(self):
        st = T.summarize(TestSummarize.PENDING, TODAY)
        rebase = [c for _, c in T.batch_plan(st["groups"]) if "rebase" in c]
        assert all("BCF" not in c for c in rebase)

    def test_unclear_tickers_get_a_probe_command_instead(self):
        st = T.summarize(TestSummarize.PENDING, TODAY)
        probes = [c for _, c in T.batch_plan(st["groups"]) if "probe" in c]
        assert any("AAM" in c for c in probes) and any("BCF" in c for c in probes)

    def test_no_safe_tickers_means_no_rebase_command_at_all(self):
        st = T.summarize({"AAM": _rec("2026-08-24", 1.0424, 4.24)}, TODAY)
        assert not [c for _, c in T.batch_plan(st["groups"]) if "rebase" in c]

    def test_every_line_carries_a_label(self):
        st = T.summarize(TestSummarize.PENDING, TODAY)
        assert all(lbl and cmd for lbl, cmd in T.batch_plan(st["groups"]))


class TestExitCode:
    def test_an_empty_ledger_exits_zero(self, tmp_path, capsys):
        assert T.main(["--warehouse", str(tmp_path)]) == 0
        assert "RỖNG" in capsys.readouterr().out

    def test_unclear_tickers_make_it_exit_nonzero(self, tmp_path, monkeypatch,
                                                  capsys):
        """Exit khác 0 để lượt chạy tự động không lặng lẽ coi là xong."""
        monkeypatch.setattr(T, "load_pending",
                            lambda wh: {"AAM": _rec("2026-08-24", 1.0424, 4.24)})
        assert T.main(["--warehouse", str(tmp_path)]) == 1

    def test_only_safe_tickers_exit_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(T, "load_pending",
                            lambda wh: {"VCB": _rec(event="stock")})
        assert T.main(["--warehouse", str(tmp_path)]) == 0

    def test_the_plan_warns_that_fixing_writes_the_shared_warehouse(
            self, tmp_path, monkeypatch, capsys):
        """Kho đi qua Dropbox — laptop chữa là desktop thấy, và phát 18:00
        đang chạy thì hai bên ghi cùng file."""
        monkeypatch.setattr(T, "load_pending",
                            lambda wh: {"VCB": _rec(event="stock")})
        T.main(["--warehouse", str(tmp_path), "--plan"])
        out = capsys.readouterr().out
        assert "GHI KHO" in out and "18:00" in out

    def test_the_red_group_gets_an_explicit_do_not_batch_warning(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(T, "load_pending",
                            lambda wh: {"AAM": _rec("2026-08-24", 1.0424, 4.24)})
        T.main(["--warehouse", str(tmp_path), "--plan"])
        assert "ĐỪNG gộp" in capsys.readouterr().out


class TestReadOnly:
    def test_the_script_never_imports_a_writer(self):
        """Bộ soi phải chạy được sát giờ phát 18:00. Nó chỉ được ĐỌC."""
        src = _SCRIPT.read_text(encoding="utf-8")
        # In RA một lệnh có `--apply` là hợp lệ — script gợi ý, người chạy.
        # Cấm là cấm tự GHI hoặc tự CHẠY.
        for forbidden in ("write_text(", "to_parquet(", "record_drift",
                          "os.remove", "shutil.", "subprocess", "os.system"):
            assert forbidden not in src, forbidden

    def test_it_reads_the_ledger_through_the_owning_module(self):
        """Sổ cách ly có một chủ sở hữu (`vnstock_basis_guard`). Tự mở file
        JSON ở đây là đẻ ra chỗ thứ hai biết định dạng của nó."""
        import inspect
        assert "vnstock_basis_guard" in inspect.getsource(T.load_pending)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


class TestThresholdComesFromTheGuard:
    """`CLAUDE.md`: ngưỡng phải KHỚP một nguồn, có test canh. Đặt một con số
    riêng ở đây là đẻ ra ngưỡng thứ hai phải giữ đồng bộ bằng tay."""

    def test_the_near_threshold_band_is_derived_not_hardcoded(self):
        from vnstock_basis_guard import TOL
        assert T._guard_tol_pct() == pytest.approx(TOL * 100.0)

    def test_the_band_starts_where_the_guard_fires(self):
        """Mọi mã trong sổ đều đã vượt ngưỡng gác — đó là lý do nó có mặt.
        Nên vùng 'sát ngưỡng' phải bắt đầu TỪ mốc đó, không thấp hơn."""
        assert T.NOISE_PCT > T._guard_tol_pct()

    def test_a_drift_below_the_guard_threshold_cannot_reach_this_ledger(self):
        assert T.classify(_rec(ratio=1.013, pct=1.3)) == "nhieu"


class TestBlindEventStore:
    """Chỗ dễ đọc sai nhất của cả bộ soi.

    Đo trên máy thật 26/08: **0/47 mã tra ra được loại sự kiện**. Chính
    `vnstock_updater._corp_event_kind` đã ghi *"Kho sự kiện đang MỎNG (19/08:
    70 mã lệch chỉ 3 mã tra ra loại)"* — tức `event: None` nghĩa là **kho tra
    cứu không biết**, KHÔNG phải "mã này không có sự kiện quyền".

    Xếp cả đống vào "🔴 chưa biết vì sao" khi ấy là **đổ lỗi cho các mã trong
    khi lỗi ở kho tra cứu**, và đẩy người đọc đi soi tay hàng chục mã thay vì
    nạp lại kho một lần.
    """

    def _groups(self, matched, unmatched):
        return {"co_su_kien": [{"ticker": f"S{i}"} for i in range(matched)],
                "chua_ro": [{"ticker": f"U{i}"} for i in range(unmatched)],
                "tron_chua_ro": [], "nhieu": []}

    def test_zero_matches_on_a_big_ledger_is_called_blind(self):
        assert T.event_store_is_blind(self._groups(0, 47))

    def test_a_healthy_match_rate_is_not_blind(self):
        assert not T.event_store_is_blind(self._groups(30, 17))

    def test_a_tiny_ledger_is_never_called_blind(self):
        """2 mã cùng không tra ra thì chưa nói lên gì về kho — kết luận từ
        mẫu bé là đúng lỗi repo đã dính (n=2 vẽ thành '0%', 13/08)."""
        assert not T.event_store_is_blind(self._groups(0, 2))

    def test_an_empty_ledger_is_not_blind(self):
        assert not T.event_store_is_blind(self._groups(0, 0))

    def test_match_rate_is_none_on_an_empty_ledger(self):
        assert T.match_rate(self._groups(0, 0)) is None

    def test_match_rate_counts_only_the_matched_group(self):
        assert T.match_rate(self._groups(1, 3)) == pytest.approx(0.25)


class TestPlanWhenBlind:
    def _blind_pending(self):
        return {f"T{i:02d}": _rec("2026-08-21", 1.05, 5.0) for i in range(12)}

    def test_the_plan_says_refill_the_store_FIRST(self, monkeypatch, tmp_path,
                                                  capsys):
        monkeypatch.setattr(T, "load_pending", lambda wh: self._blind_pending())
        T.main(["--warehouse", str(tmp_path), "--plan"])
        out = capsys.readouterr().out
        assert "vietstock --bulk --register" in out
        assert out.index("vietstock") < out.index("triage_basis_drift.py --plan")

    def test_it_does_NOT_dump_dozens_of_probe_commands(self, monkeypatch):
        """Soi tay 46 lần để rồi phát hiện cả 46 đều là cổ tức là 46 lần phí
        công — và là cách chắc chắn nhất để user bỏ cuộc giữa chừng."""
        st = T.summarize(self._blind_pending())
        cmds = [c for _, c in T.batch_plan(st["groups"])]
        assert len([c for c in cmds if "probe_price_basis" in c]) == 0

    def test_it_never_proposes_a_blind_rebase(self, monkeypatch):
        st = T.summarize(self._blind_pending())
        assert not [c for _, c in T.batch_plan(st["groups"]) if "rebase" in c]

    def test_the_banner_says_it_is_about_the_STORE_not_the_tickers(
            self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(T, "load_pending", lambda wh: self._blind_pending())
        T.main(["--warehouse", str(tmp_path)])
        out = capsys.readouterr().out
        assert "KHO SỰ KIỆN" in out and "KHÔNG phải về các mã" in out

    def test_the_red_group_is_relabelled_as_not_yet_looked_up(
            self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(T, "load_pending", lambda wh: self._blind_pending())
        T.main(["--warehouse", str(tmp_path)])
        assert "CHƯA TRA ĐƯỢC" in capsys.readouterr().out

    def test_the_scary_do_not_batch_line_is_suppressed_when_blind(
            self, monkeypatch, tmp_path, capsys):
        """Câu 'nhân bản số sai' đúng khi kho tra được mà vẫn không khớp. Khi
        kho đang mù, nó chỉ làm người đọc sợ nhầm chỗ."""
        monkeypatch.setattr(T, "load_pending", lambda wh: self._blind_pending())
        T.main(["--warehouse", str(tmp_path), "--plan"])
        assert "nhân bản một con số sai" not in capsys.readouterr().out

    def test_a_healthy_store_keeps_the_original_plan(self, monkeypatch,
                                                    tmp_path, capsys):
        pending = {f"S{i:02d}": _rec("2026-08-21", 1.10, 10.0, event="stock")
                   for i in range(11)}
        pending["AAM"] = _rec("2026-08-24", 1.0424, 4.24)
        monkeypatch.setattr(T, "load_pending", lambda wh: pending)
        T.main(["--warehouse", str(tmp_path), "--plan"])
        out = capsys.readouterr().out
        assert "rebase_ticker_history" in out and "nhân bản một con số sai" in out


class TestLiveRelookup:
    """⚠️ Cái bẫy suýt làm cả việc nạp kho trông như vô ích.

    Trường `event` trong sổ cách ly là **ảnh chụp lúc PHÁT HIỆN** —
    `vnstock_updater` ghi nó vào đúng lúc mã bị chặn. Nạp lại kho sự kiện
    (`run.py vietstock --bulk --register`, 26/08: ok=1520/1723) **không viết
    ngược lại sổ**. Bộ soi chỉ đọc ảnh chụp ⇒ nạp kho xong chạy lại vẫn ra y
    nguyên 0/47, và người dùng kết luận việc nạp kho vô ích — trong khi thật
    ra chỉ là đang đọc số cũ.
    """

    REC = {"detected_at": "2026-08-24", "ratio": 1.0424, "pct": 4.24,
           "event": None, "window": ["2026-07-25", "2026-08-24"]}

    def test_a_freshly_loaded_event_moves_the_ticker_to_the_safe_group(self):
        st = T.summarize({"AAM": self.REC}, TODAY,
                         resolve=lambda tk, rec: "cash")
        assert [r["ticker"] for r in st["groups"]["co_su_kien"]] == ["AAM"]

    def test_it_counts_how_many_the_relookup_rescued(self):
        """Con số này là bằng chứng việc nạp kho có tác dụng."""
        st = T.summarize({"AAM": self.REC, "BCF": dict(self.REC)}, TODAY,
                         resolve=lambda tk, rec: "cash")
        assert st["n_live"] == 2

    def test_without_a_resolver_the_stale_snapshot_is_used(self):
        st = T.summarize({"AAM": self.REC}, TODAY)
        assert st["n_live"] == 0
        assert [r["ticker"] for r in st["groups"]["chua_ro"]] == ["AAM"]

    def test_a_stored_event_is_never_overwritten_by_the_relookup(self):
        """Sổ đã ghi được loại thì đó là số đo lúc phát hiện — giữ nguyên."""
        rec = dict(self.REC, event="stock")
        st = T.summarize({"AAM": rec}, TODAY, resolve=lambda tk, r: "cash")
        assert st["groups"]["co_su_kien"][0]["event"] == "stock"
        assert st["n_live"] == 0

    def test_a_resolver_that_finds_nothing_changes_nothing(self):
        st = T.summarize({"AAM": self.REC}, TODAY, resolve=lambda tk, rec: None)
        assert st["n_live"] == 0 and len(st["groups"]["chua_ro"]) == 1

    def test_the_rescued_rows_are_marked_as_relooked_up(self):
        st = T.summarize({"AAM": self.REC}, TODAY, resolve=lambda tk, r: "cash")
        assert st["groups"]["co_su_kien"][0]["event_source"] == "tra lại"


class TestEventAround:
    def test_it_prefers_the_end_of_the_comparison_window(self):
        rec = {"window": ["2026-07-25", "2026-08-24"], "detected_at": "2026-08-26"}
        assert T.event_around(rec) == date(2026, 8, 24)

    def test_it_falls_back_to_the_detection_date(self):
        assert T.event_around({"detected_at": "2026-08-21"}) == date(2026, 8, 21)

    def test_a_null_window_end_falls_through_to_detection(self):
        rec = {"window": [None, None], "detected_at": "2026-08-21"}
        assert T.event_around(rec) == date(2026, 8, 21)

    def test_nothing_readable_gives_none_not_today(self):
        """Trả `date.today()` ở đây là bịa một ngày vách, rồi tra sự kiện quanh
        một mốc không có thật."""
        assert T.event_around({}) is None
        assert T.event_around({"detected_at": "rác"}) is None


class TestRelookupIsStillReadOnly:
    def test_the_live_lookup_only_reads(self):
        import inspect
        src = inspect.getsource(T.live_event_kind)
        # Bỏ docstring rồi mới soi — docstring có nhắc `--register` để GIẢI
        # THÍCH, và cấm nhầm chữ trong lời giải thích là một cách hay ho để
        # ép người sau viết code khó hiểu hơn.
        body = src.split('"""')[-1]
        assert "_corp_event_kind" in body
        for forbidden in ("write", "register", "--apply", "to_parquet"):
            assert forbidden not in body, forbidden

    def test_a_broken_lookup_never_raises(self, monkeypatch):
        """Bộ soi hỏng vì kho sự kiện hỏng thì mất luôn thứ duy nhất đang nói
        cho user biết 47 mã đứng giá."""
        assert T.live_event_kind("AAM", "/khong/co/kho", date(2026, 8, 24)) is None

    def test_the_flag_can_turn_the_relookup_off(self, tmp_path, monkeypatch,
                                                capsys):
        monkeypatch.setattr(T, "load_pending", lambda wh: {"AAM": self_rec()})
        monkeypatch.setattr(T, "live_event_kind",
                            lambda *a, **k: pytest.fail("không được tra lại"))
        T.main(["--warehouse", str(tmp_path), "--no-relookup"])
        assert "tra LẠI" not in capsys.readouterr().out


def self_rec():
    return {"detected_at": "2026-08-24", "ratio": 1.0424, "pct": 4.24,
            "event": None, "window": ["2026-07-25", "2026-08-24"]}


class TestTwoEventStores:
    """⚠️ Đo 26/08: app có **HAI kho sự kiện quyền song song, không nói chuyện
    với nhau** — và tôi đã bảo user nạp NHẦM kho.

    | kho | file | ai NẠP | ai ĐỌC |
    |---|---|---|---|
    | cache theo mã | `_meta/corp_actions/<MÃ>.parquet` | `vnstock_adjust.refresh_events` | `load_events` → `_corp_event_kind` → **cửa gác** |
    | sổ đăng ký | `_meta/corp_actions_registry.parquet` | `run.py vietstock --register` | `vnstock_corp_registry`, `load_recent_exdiv` |

    `vietstock --bulk --register` nạp 1.520 mã vào kho THỨ HAI, còn cửa gác
    tra kho THỨ NHẤT ⇒ vẫn ra 0/70. Bộ soi phải hỏi CẢ HAI.
    """

    def _registry(self, tmp_path, rows):
        import pandas as pd
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(meta / "corp_actions_registry.parquet")
        return tmp_path

    def _row(self, ticker="AAM", ex="2026-08-10", type_="cash"):
        return {"ticker": ticker, "ex_date": ex, "type": type_,
                "cash_amount": 500.0, "ratio": float("nan"),
                "source": "vietstock", "confidence": 0.8, "note": ""}

    def test_an_event_in_the_registry_is_found(self, tmp_path):
        wh = self._registry(tmp_path, [self._row()])
        assert T.registry_event_kind("AAM", wh, date(2026, 7, 25),
                                     date(2026, 8, 24)) == "cash"

    def test_matching_ignores_ticker_case(self, tmp_path):
        wh = self._registry(tmp_path, [self._row(ticker="aam")])
        assert T.registry_event_kind("AAM", wh, date(2026, 7, 25),
                                     date(2026, 8, 24)) == "cash"

    def test_an_event_outside_the_window_is_not_claimed(self, tmp_path):
        """Vơ một sự kiện cách xa vách gãy là gán sai NGUYÊN NHÂN, rồi mã đó
        rơi vào nhóm 'chữa máy móc được'."""
        wh = self._registry(tmp_path, [self._row(ex="2026-01-05")])
        assert T.registry_event_kind("AAM", wh, date(2026, 7, 25),
                                     date(2026, 8, 24)) is None

    def test_another_ticker_is_never_borrowed(self, tmp_path):
        wh = self._registry(tmp_path, [self._row(ticker="FPT")])
        assert T.registry_event_kind("AAM", wh, date(2026, 7, 25),
                                     date(2026, 8, 24)) is None

    def test_a_missing_registry_is_not_an_error(self, tmp_path):
        assert T.registry_event_kind("AAM", tmp_path, date(2026, 7, 1),
                                     date(2026, 9, 1)) is None

    def test_a_corrupt_registry_is_not_an_error(self, tmp_path):
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        (meta / "corp_actions_registry.parquet").write_text("rác", encoding="utf-8")
        assert T.registry_event_kind("AAM", tmp_path, date(2026, 7, 1),
                                     date(2026, 9, 1)) is None

    def test_the_registry_lookup_only_reads(self):
        import inspect
        body = inspect.getsource(T.registry_event_kind).split('"""')[-1]
        for forbidden in ("write", "to_parquet", "--apply"):
            assert forbidden not in body, forbidden


class TestEventWindow:
    """⚠️ Lưới này ĐÃ VIẾT SAI ở bản đầu — nó chốt cứng niềm tin "vách gãy nằm
    TRONG cửa sổ so sánh", nên test XANH trong khi code trượt 100%.

    Chiều đúng, từ chính cơ chế lỗi ghi ở `vnstock_basis_guard`:

        nguồn back-adjust MỌI bar TRƯỚC ex_date; bar từ ex_date trở đi giữ nguyên
        ⇒ ρ(d) = kho/nguồn = f ≠ 1 với d < ex_date, ρ(d) = 1.0 với d ≥ ex_date

    `check_basis` chỉ báo `basis_changed` khi TRUNG VỊ ρ trên `[first, last]`
    lệch khỏi 1 ⇒ mọi bar trong khoảng cùng một phía của ex_date ⇒
    **ex_date > last**. Nếu ex_date nằm TRƯỚC khoảng thì ρ = 1, verdict
    `aligned`, guard câm — không có gì vào sổ cả.

    Cửa sổ so sánh còn HẸP (~7 phiên: `WANT_BARS = MIN_BARS + 3`), nên
    `[first, last]` lại càng không thể chứa ex_date.
    """

    TODAY = date(2026, 8, 26)

    def test_it_searches_FORWARD_from_the_window_edge(self):
        rec = {"window": ["2026-08-01", "2026-08-09"], "detected_at": "2026-08-09"}
        lo, hi = T.event_window(rec, pad_days=5, today=self.TODAY)
        assert lo == date(2026, 8, 9) and hi == date(2026, 8, 14)

    def test_it_never_looks_inside_the_comparison_window(self):
        """Bản đầu trả (first, last) — khoảng mà ex_date CHẮC CHẮN không nằm
        trong. Đó là lý do nhánh tra sổ đăng ký ra 1/70."""
        rec = {"window": ["2026-08-01", "2026-08-09"], "detected_at": "2026-08-09"}
        lo, _ = T.event_window(rec, today=self.TODAY)
        assert lo >= date(2026, 8, 9)

    def test_the_range_covers_the_gap_the_warehouse_is_missing(self):
        rec = {"window": ["2026-08-01", "2026-08-09"], "detected_at": "2026-08-20"}
        lo, hi = T.event_window(rec, pad_days=5, today=self.TODAY)
        assert lo == date(2026, 8, 9) and hi == date(2026, 8, 25)

    def test_it_never_reaches_into_the_future(self):
        """Sự kiện chưa tới thì không thể là nguyên nhân giá đã lệch."""
        rec = {"window": ["2026-08-20", "2026-08-25"], "detected_at": "2026-08-25"}
        _, hi = T.event_window(rec, pad_days=30, today=self.TODAY)
        assert hi == self.TODAY

    def test_only_a_detection_date_still_gives_a_forward_range(self):
        lo, hi = T.event_window({"detected_at": "2026-08-24"}, pad_days=5,
                                today=self.TODAY)
        assert lo < hi and hi <= self.TODAY

    def test_nothing_readable_gives_none(self):
        assert T.event_window({}, today=self.TODAY) is None
        assert T.event_window({"detected_at": "rác"}, today=self.TODAY) is None

    def test_the_range_is_never_inverted(self):
        rec = {"window": [None, "2026-08-30"], "detected_at": "2026-08-30"}
        lo, hi = T.event_window(rec, today=date(2026, 8, 26))
        assert lo <= hi


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
