"""
Lưới cho `scripts/bank_bs_sources.py` + hai chế độ soi mới của
`scripts/export_bank_balance_sheets.py` (`--probe-all`, `--crosscheck`).

Bối cảnh: user cần bảng cân đối ngân hàng **2015-2016**, mà nguồn trong app
KHÔNG có (VCI sớm nhất 2018-Q1 · KBS trả rỗng). TCBS là nguồn thứ ba, gọi
HTTP thẳng — và **chưa ai đo sống nó**: máy soạn code bị chặn egress tới mọi
host tài chính VN. Vì thế phần THUẦN phải chặt hơn bình thường:

* trường lạ KHÔNG được rơi mất (danh mục dịch tên có thể thiếu, và thiếu tên
  thì tệ hơn nhiều nếu nó kéo theo mất luôn con số);
* payload rỗng/hỏng ⇒ frame RỖNG, để chỗ gọi dừng — chứ không ra frame nửa
  vời rồi ghi thành file;
* `unit_ratios` chỉ ĐƯA RA tỉ số, không tự kết luận đơn vị. Đơn vị TCBS chưa
  xác nhận; đoán sai một bậc nghìn là cả bảng sai mà nhìn vẫn "hợp lý".
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("bank_bs_sources", "bank_bs_sources.py")
E = _load("bank_bs_export_x", "export_bank_balance_sheets.py")


def _rec(year, quarter, **fields):
    return {"ticker": "VCB", "year": year, "quarter": quarter, **fields}


# ─────────────────────────────────────────────────────────────────────────
class TestTcbsLabels:
    def test_known_field_gets_the_vietnamese_name(self):
        assert S.tcbs_label("customerLoan") == "Cho vay khách hàng"

    def test_unknown_field_keeps_its_identity_instead_of_vanishing(self):
        assert S.tcbs_label("someBrandNewField") == "Some brand new field"

    def test_english_mode_never_uses_the_vietnamese_map(self):
        assert S.tcbs_label("customerLoan", "en") == "Customer loan"

    def test_single_word_field_is_capitalised(self):
        assert S.tcbs_label("equity", "en") == "Equity"

    def test_field_with_digits_survives(self):
        assert "1" in S.tcbs_label("tier1Capital", "en")


class TestTcbsRecords:
    def test_plain_list_passes_through(self):
        assert S.tcbs_records([{"a": 1}]) == [{"a": 1}]

    def test_wrapped_in_data_key(self):
        assert S.tcbs_records({"data": [{"a": 1}]}) == [{"a": 1}]

    def test_wrapped_in_items_key(self):
        assert S.tcbs_records({"items": [{"a": 1}]}) == [{"a": 1}]

    def test_non_dict_entries_are_dropped(self):
        assert S.tcbs_records([{"a": 1}, "rác", None]) == [{"a": 1}]

    def test_unrecognised_payload_returns_empty(self):
        assert S.tcbs_records("khong phai json") == []
        assert S.tcbs_records({"unexpected": 1}) == []


class TestTcbsPeriod:
    def test_reads_year_and_quarter(self):
        assert S.tcbs_period({"year": 2015, "quarter": 3}) == (2015, 3)

    def test_string_numbers_are_accepted(self):
        assert S.tcbs_period({"year": "2016", "quarter": "1"}) == (2016, 1)

    def test_missing_field_returns_none(self):
        assert S.tcbs_period({"year": 2015}) is None

    def test_quarter_out_of_range_returns_none(self):
        assert S.tcbs_period({"year": 2015, "quarter": 5}) is None

    def test_garbage_returns_none_instead_of_raising(self):
        assert S.tcbs_period({"year": "x", "quarter": "y"}) is None


class TestTcbsFrame:
    def test_shape_is_rows_are_items_columns_are_periods(self):
        df = S.tcbs_to_frame([_rec(2015, 1, cash=10, asset=100),
                              _rec(2015, 2, cash=11, asset=110)])
        assert list(df.columns) == ["item", "2015-Q1", "2015-Q2"]
        assert df.shape[0] == 2

    def test_periods_come_out_in_chronological_order(self):
        df = S.tcbs_to_frame([_rec(2016, 2, cash=2), _rec(2015, 4, cash=1),
                              _rec(2016, 1, cash=3)])
        assert list(df.columns)[1:] == ["2015-Q4", "2016-Q1", "2016-Q2"]

    def test_meta_keys_never_become_balance_sheet_rows(self):
        df = S.tcbs_to_frame([_rec(2015, 1, cash=10)])
        assert df["item"].tolist() == ["Tiền mặt, vàng bạc, đá quý"]

    def test_unknown_field_still_carries_its_numbers(self):
        df = S.tcbs_to_frame([_rec(2015, 1, weirdNewField=7)])
        assert df.loc[0, "2015-Q1"] == 7
        assert df.loc[0, "item"] == "Weird new field"

    def test_field_missing_in_one_quarter_stays_blank_not_zero(self):
        df = S.tcbs_to_frame([_rec(2015, 1, cash=10, asset=100),
                              _rec(2015, 2, cash=11)])
        row = df[df["item"] == "TỔNG TÀI SẢN"].iloc[0]
        assert row["2015-Q1"] == 100
        # Ô trống ≠ số 0. pandas biến None thành NaN; điều PHẢI giữ là nó
        # không được hoá thành 0 — 0 trong bảng cân đối là một khẳng định.
        assert E._is_blank(row["2015-Q2"])
        assert row["2015-Q2"] != 0

    def test_field_appearing_only_later_is_still_included(self):
        df = S.tcbs_to_frame([_rec(2015, 1, cash=1),
                              _rec(2015, 2, cash=2, badLoan=9)])
        assert "Nợ xấu" in df["item"].tolist()

    def test_empty_payload_gives_an_empty_frame(self):
        assert S.tcbs_to_frame([]).empty

    def test_records_without_a_period_give_an_empty_frame(self):
        assert S.tcbs_to_frame([{"cash": 1}]).empty

    def test_records_with_only_meta_keys_give_an_empty_frame(self):
        assert S.tcbs_to_frame([_rec(2015, 1)]).empty

    def test_frame_is_readable_by_the_shared_period_detector(self):
        df = S.tcbs_to_frame([_rec(2015, 1, cash=10), _rec(2015, 2, cash=11)])
        assert [qq for _, qq in E.detect_period_columns(df.columns)] == \
            [(2015, 1), (2015, 2)]

    def test_frame_is_readable_by_the_shared_tidy(self):
        df = S.tcbs_to_frame([_rec(2015, 1, asset=100)])
        assert E.tidy(df)[(2015, 1)]["TỔNG TÀI SẢN"] == 100


class TestCafefProbe:
    def test_finds_vietnamese_quarter_headers(self):
        assert (2016, 4) in S.cafef_quarters_in("… Quý 4-2016 …")

    def test_finds_short_form_headers(self):
        assert (2015, 1) in S.cafef_quarters_in("<th>Q1/2015</th>")

    def test_returns_sorted_unique_periods(self):
        html = "Quý 2-2016 Quý 1-2016 Quý 2-2016"
        assert S.cafef_quarters_in(html) == [(2016, 1), (2016, 2)]

    def test_no_headers_gives_empty_list(self):
        assert S.cafef_quarters_in("<html>không có gì</html>") == []

    def test_none_html_does_not_raise(self):
        assert S.cafef_quarters_in(None) == []

    def test_url_carries_ticker_year_and_quarter(self):
        url = S.CAFEF_BS_URL.format(ticker="VCB", year=2016, quarter=4)
        assert "/VCB/BSheet/2016/4/" in url


# ─────────────────────────────────────────────────────────────────────────
def _frame(items, quarters, values):
    recs = []
    for it in items:
        rec = {"item": it}
        for (y, q) in quarters:
            rec[f"{y}-Q{q}"] = values.get((it, y, q))
        recs.append(rec)
    return pd.DataFrame(recs)


class TestSourceCoverage:
    def test_reports_the_first_and_last_period(self, monkeypatch):
        df = _frame(["TỔNG TÀI SẢN"], [(2018, 1), (2018, 2)],
                    {("TỔNG TÀI SẢN", 2018, 1): 1, ("TỔNG TÀI SẢN", 2018, 2): 2})
        monkeypatch.setattr(E, "fetch_balance_sheet", lambda *a, **k: df)
        row = E.source_coverage("VCB", 200, "vi", "vci")
        assert row["ok"] and row["first"] == (2018, 1) and row["last"] == (2018, 2)

    def test_an_exception_becomes_a_reported_row_not_a_crash(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("proxy 403")
        monkeypatch.setattr(E, "fetch_balance_sheet", boom)
        row = E.source_coverage("VCB", 200, "vi", "tcbs")
        assert row["ok"] is False and "403" in row["error"]

    def test_empty_frame_is_reported_as_empty(self, monkeypatch):
        monkeypatch.setattr(E, "fetch_balance_sheet",
                            lambda *a, **k: pd.DataFrame())
        row = E.source_coverage("VCB", 200, "vi", "kbs")
        assert row["ok"] is False and "RỖNG" in row["error"]

    def test_unrecognised_shape_is_reported_not_guessed(self, monkeypatch):
        monkeypatch.setattr(E, "fetch_balance_sheet",
                            lambda *a, **k: pd.DataFrame({"a": [1], "b": [2]}))
        row = E.source_coverage("VCB", 200, "vi", "vci")
        assert row["ok"] is False and "cột kỳ" in row["error"]


class TestReaches:
    def test_source_starting_early_enough_reaches(self):
        assert E.reaches({"ok": True, "first": (2015, 1)}, 2015)

    def test_source_starting_later_does_not_reach(self):
        assert not E.reaches({"ok": True, "first": (2018, 1)}, 2015)

    def test_a_source_that_failed_never_reaches(self):
        assert not E.reaches({"ok": False, "first": None}, 2015)

    def test_exactly_on_the_boundary_counts_as_reaching(self):
        assert E.reaches({"ok": True, "first": (2015, 1)}, 2015, 1)


class TestUnitRatios:
    QS = [(2018, 1), (2018, 2)]

    def _pair(self, scale):
        items_a = ["TỔNG TÀI SẢN"]
        items_b = ["TỔNG TÀI SẢN"]
        a = {(2018, 1): {"TỔNG TÀI SẢN": 1_000_000.0},
             (2018, 2): {"TỔNG TÀI SẢN": 2_000_000.0}}
        b = {(2018, 1): {"TỔNG TÀI SẢN": 1_000_000.0 / scale},
             (2018, 2): {"TỔNG TÀI SẢN": 2_000_000.0 / scale}}
        return a, b, items_a, items_b

    def test_same_unit_gives_ratio_one(self):
        rows = E.unit_ratios(*self._pair(1))
        assert all(abs(r - 1.0) < 1e-9 for *_, r in rows)

    def test_one_order_of_magnitude_shows_up_as_a_flat_ratio(self):
        rows = E.unit_ratios(*self._pair(1000))
        assert [round(r) for *_, r in rows] == [1000, 1000]

    def test_only_overlapping_quarters_are_compared(self):
        a, b, ia, ib = self._pair(1)
        b.pop((2018, 2))
        rows = E.unit_ratios(a, b, ia, ib)
        assert [qq for qq, *_ in rows] == [(2018, 1)]

    def test_missing_total_asset_row_gives_no_rows(self):
        a, b, ia, ib = self._pair(1)
        rows = E.unit_ratios(a, b, ia, ["Cho vay khách hàng"])
        assert rows == []

    def test_non_numeric_values_are_skipped_not_crashed_on(self):
        a, b, ia, ib = self._pair(1)
        b[(2018, 1)]["TỔNG TÀI SẢN"] = "n/a"
        rows = E.unit_ratios(a, b, ia, ib)
        assert [qq for qq, *_ in rows] == [(2018, 2)]

    def test_zero_denominator_reports_none_instead_of_dividing(self):
        a, b, ia, ib = self._pair(1)
        b[(2018, 1)]["TỔNG TÀI SẢN"] = 0
        rows = E.unit_ratios(a, b, ia, ib)
        assert rows[0][3] is None

    def test_matching_ignores_accents_and_case(self):
        a, b, ia, _ = self._pair(1)
        b2 = {qq: {"Tổng tài sản": v["TỔNG TÀI SẢN"]} for qq, v in b.items()}
        rows = E.unit_ratios(a, b2, ia, ["Tổng tài sản"])
        assert len(rows) == 2

    def test_english_label_is_also_matched(self):
        a, b, ia, _ = self._pair(1)
        b2 = {qq: {"TOTAL ASSETS": v["TỔNG TÀI SẢN"]} for qq, v in b.items()}
        rows = E.unit_ratios(a, b2, ia, ["TOTAL ASSETS"])
        assert len(rows) == 2


class TestProbeAllExitCodes:
    def _cov(self, first):
        return {"source": "x", "ok": first is not None, "rows": 1, "cols": 2,
                "first": first, "last": first, "n_periods": 1, "n_items": 1,
                "error": None if first else "hỏng"}

    def test_exit_zero_when_a_source_reaches_the_wanted_year(self, monkeypatch):
        monkeypatch.setattr(E, "source_coverage",
                            lambda t, l, lg, s: self._cov((2015, 1)))
        monkeypatch.setattr(E, "SOURCES", ("vci",))
        assert E.probe_all("VCB", 200, "vi", 2015) == 0

    def test_exit_two_when_no_source_goes_back_far_enough(self, monkeypatch):
        monkeypatch.setattr(E, "source_coverage",
                            lambda t, l, lg, s: self._cov((2018, 1)))
        monkeypatch.setattr(E, "SOURCES", ("vci",))
        assert E.probe_all("VCB", 200, "vi", 2015) == 2

    def test_exit_two_when_every_source_is_broken(self, monkeypatch):
        monkeypatch.setattr(E, "source_coverage",
                            lambda t, l, lg, s: self._cov(None))
        monkeypatch.setattr(E, "SOURCES", ("vci", "kbs"))
        assert E.probe_all("VCB", 200, "vi", 2015) == 2


class TestCrosscheckExitCodes:
    def test_empty_source_refuses_to_conclude(self, monkeypatch):
        monkeypatch.setattr(E, "fetch_balance_sheet",
                            lambda *a, **k: pd.DataFrame())
        assert E.crosscheck("VCB", 200, "vi") == 2

    def test_network_failure_is_reported_as_failure(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("proxy 403")
        monkeypatch.setattr(E, "fetch_balance_sheet", boom)
        assert E.crosscheck("VCB", 200, "vi") == 2

    def test_matching_totals_give_a_clean_run(self, monkeypatch):
        df = _frame(["TỔNG TÀI SẢN"], [(2018, 1)], {("TỔNG TÀI SẢN", 2018, 1): 5})
        monkeypatch.setattr(E, "fetch_balance_sheet", lambda *a, **k: df)
        assert E.crosscheck("VCB", 200, "vi") == 0

    def test_no_shared_line_item_is_a_failure_not_a_silent_pass(self, monkeypatch):
        frames = iter([
            _frame(["TỔNG TÀI SẢN"], [(2018, 1)], {("TỔNG TÀI SẢN", 2018, 1): 5}),
            _frame(["Cho vay khách hàng"], [(2018, 1)],
                   {("Cho vay khách hàng", 2018, 1): 5}),
        ])
        monkeypatch.setattr(E, "fetch_balance_sheet", lambda *a, **k: next(frames))
        assert E.crosscheck("VCB", 200, "vi") == 2


class TestSourcesRegistry:
    def test_tcbs_is_a_selectable_source(self):
        assert "tcbs" in E.SOURCES

    def test_every_source_name_is_lowercase_and_short(self):
        assert all(s.islower() and len(s) <= 5 for s in E.SOURCES)


class TestNoNetworkAtImport:
    """Import module KHÔNG được chạm mạng — test suite chạy offline."""

    def test_importing_sources_does_not_require_requests(self):
        assert "requests" not in dir(S)

    def test_fetch_helpers_exist_but_are_not_called_at_import(self):
        assert callable(S.fetch_tcbs) and callable(S.fetch_cafef)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
