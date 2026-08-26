"""
Lưới cho bộ chặn cờ "phân phối" GIẢ — `load_recent_exdiv` + badge doctor.

**Lỗi im lặng phát hiện 26/08.** `dashboard/market_commentary` gọi
`load_recent_exdiv(days_back=7)` để BỎ QUA cờ phân phối khi giá rơi chỉ vì cổ
tức. Nhưng đường nạp DUY NHẤT của nó là `_meta/cash_dividends/*.json`, mà kho
đó chỉ do `run.py cash-dividends` ghi — và lệnh ấy:

* cào CafeF, **404 từ 19/08** (U17 mục 2), và
* **KHÔNG nằm trong `cmd_all`**, nên chưa bao giờ tự chạy.

Cửa sổ mặc định 7 ngày ⇒ từ khoảng 26/08 hàm **luôn trả `{}`** và cờ giả đi
thẳng ra dashboard. `{}` là giá trị hợp lệ nên không chỗ nào kêu: **code chết
trông y như code sống.**

Vá: đọc SỔ ĐĂNG KÝ `_meta/corp_actions_registry.parquet` (nhiều nguồn nạp, có
sẵn cột `cash_amount`) làm nguồn DUY NHẤT. Badge `exdiv_source` canh để nó
không lặng lẽ chết lần nữa.

Kho JSON cũ đã **xoá hẳn** cùng ngày, sau khi badge trên máy thật xác nhận sổ
đăng ký trả lời được. Nó chứng minh được là rỗng vĩnh viễn: mọi chỗ gọi dùng
cửa sổ 7 ngày, nên nó chỉ có thể chứa sự kiện từ 19/08 trở đi — mà từ 19/08
lệnh ghi đã 404.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import vnstock_doctor
import vnstock_market_analyzer as ma


def _registry(tmp_path, rows):
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(meta / "corp_actions_registry.parquet")
    return tmp_path


def _row(ticker, ex_date, type_="cash", cash_amount=500.0):
    return {"ticker": ticker, "ex_date": ex_date, "type": type_,
            "cash_amount": cash_amount, "ratio": float("nan"),
            "source": "vietstock", "confidence": 0.8,
            "registered_at": pd.Timestamp("2026-08-26"), "note": ""}


TODAY = date.today()
CUTOFF = TODAY - timedelta(days=7)


class TestRegistryReader:
    def test_a_recent_cash_event_is_found(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY - timedelta(days=2))])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert got["VNM"]["amount"] == 500.0

    def test_an_event_outside_the_window_is_ignored(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY - timedelta(days=40))])
        assert ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh) == {}

    def test_a_future_event_is_ignored(self, tmp_path):
        """Sự kiện CHƯA tới thì giá chưa rơi — chặn cờ lúc này là chặn nhầm."""
        wh = _registry(tmp_path, [_row("VNM", TODAY + timedelta(days=3))])
        assert ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh) == {}

    def test_non_cash_events_are_ignored(self, tmp_path):
        """Chia tách / thưởng điều chỉnh giá theo TỈ LỆ, không phải số tuyệt
        đối — đường này chỉ lo cổ tức tiền mặt."""
        wh = _registry(tmp_path, [_row("VNM", TODAY, type_="split")])
        assert ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh) == {}

    def test_the_latest_event_wins_when_a_ticker_has_two(self, tmp_path):
        wh = _registry(tmp_path, [
            _row("VNM", TODAY - timedelta(days=5), cash_amount=100.0),
            _row("VNM", TODAY - timedelta(days=1), cash_amount=900.0),
        ])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert got["VNM"]["amount"] == 900.0

    def test_a_missing_amount_still_suppresses_the_flag(self, tmp_path):
        """Sổ có sự kiện mà thiếu số tiền vẫn là bằng chứng giá rơi vì cổ tức.
        Bỏ dòng đó đi là mất một lần chặn cờ giả chỉ vì thiếu một con số."""
        wh = _registry(tmp_path, [_row("VNM", TODAY, cash_amount=float("nan"))])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert "VNM" in got and got["VNM"]["amount"] == 0.0

    def test_tickers_come_back_uppercased(self, tmp_path):
        wh = _registry(tmp_path, [_row("vnm", TODAY)])
        assert "VNM" in ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)

    def test_a_missing_registry_is_not_an_error(self, tmp_path):
        assert ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=tmp_path) == {}

    def test_a_corrupt_registry_is_not_an_error(self, tmp_path):
        meta = tmp_path / "_meta"
        meta.mkdir(parents=True)
        (meta / "corp_actions_registry.parquet").write_text("rác", encoding="utf-8")
        assert ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=tmp_path) == {}

    def test_an_unparseable_date_is_skipped_not_crashed_on(self, tmp_path):
        # Cả cột để dạng CHUỖI — parquet không cho trộn `date` với `str`, và
        # sổ thật lưu `date`; ca này mô phỏng sổ bị ghi lệch kiểu.
        wh = _registry(tmp_path, [_row("VNM", "không phải ngày"),
                                  _row("FPT", TODAY.isoformat())])
        assert list(ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)) == ["FPT"]

    def test_a_registry_storing_dates_as_strings_still_reads(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY.isoformat())])
        assert "VNM" in ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)


class TestContractUnchanged:
    """`compute_scores(exdiv_map=…)` đọc đúng hai khoá này. Đổi hình dạng là
    phá chỗ gọi mà không ai báo."""

    def test_shape_is_ticker_to_exdate_and_amount(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY)])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert set(got["VNM"]) == {"ex_date", "amount"}

    def test_ex_date_is_an_iso_string_not_a_date_object(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY)])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert got["VNM"]["ex_date"] == TODAY.isoformat()

    def test_amount_is_a_float(self, tmp_path):
        wh = _registry(tmp_path, [_row("VNM", TODAY)])
        got = ma._exdiv_from_registry(CUTOFF, TODAY, warehouse=wh)
        assert isinstance(got["VNM"]["amount"], float)


class TestSingleSource:
    """Một nguồn, và nó phải NÓI RA khi rỗng chứ không âm thầm trả {}."""

    def test_it_reads_the_registry(self, monkeypatch):
        monkeypatch.setattr(ma, "_exdiv_from_registry",
                            lambda c, t: {"VNM": {"ex_date": "2026-08-20",
                                                  "amount": 900.0}})
        assert ma.load_recent_exdiv()["VNM"]["amount"] == 900.0

    def test_an_empty_registry_gives_empty(self, monkeypatch):
        monkeypatch.setattr(ma, "_exdiv_from_registry", lambda c, t: {})
        assert ma.load_recent_exdiv() == {}

    def test_it_never_raises_when_the_registry_is_missing(self):
        assert isinstance(ma.load_recent_exdiv(days_back=7), dict)

    def test_the_dead_cafef_reader_is_gone(self):
        """Kho JSON của CafeF chỉ nhận được sự kiện từ 19/08 trở đi, mà từ
        19/08 lệnh ghi đã 404 — với cửa sổ 7 ngày thì nó rỗng vĩnh viễn. Giữ
        lại là nuôi thêm một đoạn code chết trông như sống."""
        assert not hasattr(ma, "_exdiv_from_cafef_cache")

    def test_the_window_is_honoured(self, monkeypatch):
        seen = {}

        def spy(cutoff, today):
            seen["days"] = (today - cutoff).days
            return {}
        monkeypatch.setattr(ma, "_exdiv_from_registry", spy)
        ma.load_recent_exdiv(days_back=30)
        assert seen["days"] == 30


class TestDoctorBadge:
    def _status(self, monkeypatch, recent=0, total=0):
        monkeypatch.setattr(ma, "exdiv_source_status",
                            lambda days_back=7: {
                                "recent": recent, "total_cash": total,
                                "source": "registry" if recent else "none",
                                "days_back": 7})

    def test_the_registry_answering_is_ok(self, monkeypatch):
        self._status(monkeypatch, recent=3, total=400)
        r = vnstock_doctor.check_exdiv_source()
        assert r["status"] == "ok" and "3 mã" in r["message"]

    def test_it_shows_the_whole_ledger_size_so_a_small_number_is_readable(
            self, monkeypatch):
        """'trả 1 mã' một mình không đọc được — 1 vì tuần này im, hay 1 vì sổ
        gần rỗng? Con số tổng làm nó có nghĩa."""
        self._status(monkeypatch, recent=1, total=412)
        assert "412" in vnstock_doctor.check_exdiv_source()["message"]

    def test_a_quiet_week_with_a_populated_ledger_is_OK_not_a_warning(
            self, monkeypatch):
        """7 ngày không mã nào chia cổ tức là chuyện BÌNH THƯỜNG. Kêu ở đây là
        báo động giả, mà báo động giả dạy người ta bỏ qua badge."""
        self._status(monkeypatch, recent=0, total=412)
        r = vnstock_doctor.check_exdiv_source()
        assert r["status"] == "ok" and "không mã nào chia" in r["message"]

    def test_an_empty_ledger_warns(self, monkeypatch):
        self._status(monkeypatch, recent=0, total=0)
        r = vnstock_doctor.check_exdiv_source()
        assert r["status"] == "warn" and "chạy CHAY" in r["message"]

    def test_the_warning_names_a_command_that_still_works(self, monkeypatch):
        """Gợi ý `run.py cash-dividends` là gợi ý một lệnh đã xoá — đúng cái
        bẫy vừa gỡ. Và lệnh gợi ý GHI KHO nên phải nói rõ thời điểm."""
        self._status(monkeypatch, recent=0, total=0)
        fix = vnstock_doctor.check_exdiv_source()["fix"]
        assert "vietstock" in fix and "GHI KHO" in fix and "404" in fix

    def test_a_broken_reader_is_reported_as_error_not_silence(self, monkeypatch):
        def boom(days_back=7):
            raise RuntimeError("hỏng")
        monkeypatch.setattr(ma, "exdiv_source_status", boom)
        assert vnstock_doctor.check_exdiv_source()["status"] == "error"

    def test_the_check_is_wired_into_the_offline_run(self):
        """Guard quên nối = code chết trông y như code sống — đúng chủ đề của
        chính bản vá này."""
        names = [f.__name__ for f in vnstock_doctor.OFFLINE_CHECKS]
        assert "check_exdiv_source" in names


class TestStatusHelper:
    def test_it_names_the_registry_when_there_are_recent_events(self, tmp_path,
                                                                monkeypatch):
        monkeypatch.setattr(ma, "_exdiv_from_registry",
                            lambda c, t: {"VNM": {}})
        assert ma.exdiv_source_status()["source"] == "registry"

    def test_none_when_the_window_is_empty(self, monkeypatch):
        monkeypatch.setattr(ma, "_exdiv_from_registry",
                            lambda c, t: {} if (t - c).days <= 7 else {"A": {}})
        assert ma.exdiv_source_status()["source"] == "none"

    def test_total_counts_every_period_not_just_the_window(self, monkeypatch):
        monkeypatch.setattr(
            ma, "_exdiv_from_registry",
            lambda c, t: {"A": {}} if (t - c).days <= 7 else {"A": {}, "B": {}})
        st = ma.exdiv_source_status()
        assert st["recent"] == 1 and st["total_cash"] == 2

    def test_the_window_size_is_reported(self, monkeypatch):
        monkeypatch.setattr(ma, "_exdiv_from_registry", lambda c, t: {})
        assert ma.exdiv_source_status(days_back=30)["days_back"] == 30


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
