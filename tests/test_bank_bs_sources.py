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
        url = S.CAFEF_BS_URL.format(ticker="VCB", ticker_lower="vcb",
                                    year=2016, quarter=4)
        assert "/vcb/bsheet/2016/4/" in url

    def test_legacy_url_is_kept_as_a_spare(self):
        url = S.CAFEF_BS_URL_LEGACY.format(ticker="VCB", ticker_lower="vcb",
                                           year=2016, quarter=4)
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
                            lambda t, l, lg, s, years=None: self._cov((2015, 1)))
        monkeypatch.setattr(E, "SOURCES", ("vci",))
        assert E.probe_all("VCB", 200, "vi", 2015) == 0

    def test_exit_two_when_no_source_goes_back_far_enough(self, monkeypatch):
        monkeypatch.setattr(E, "source_coverage",
                            lambda t, l, lg, s, years=None: self._cov((2018, 1)))
        monkeypatch.setattr(E, "SOURCES", ("vci",))
        assert E.probe_all("VCB", 200, "vi", 2015) == 2

    def test_exit_two_when_every_source_is_broken(self, monkeypatch):
        monkeypatch.setattr(E, "source_coverage",
                            lambda t, l, lg, s, years=None: self._cov(None))
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


# ─────────────────────────────────────────────────────────────────────────
# CafeF: bộ bóc bảng. Viết KHI CHƯA NHÌN TRANG THẬT (máy soạn code bị chặn
# egress), nên lưới ở đây canh HÀNH VI chứ không canh một trang cụ thể:
# nhận diện theo hình dạng, trật thì trả RỖNG, và không bao giờ biến ô trống
# thành số 0.
# ─────────────────────────────────────────────────────────────────────────
_CAFEF_PAGE = """
<html><body>
<div>Đơn vị: Triệu VNĐ</div>
<table id="menu"><tr><td>Trang chủ</td><td>Dữ liệu</td></tr></table>
<table id="tblGridData">
  <tr><th>CHỈ TIÊU</th><th>Quý 1-2016</th><th>Quý 2-2016</th>
      <th>Quý 3-2016</th><th>Quý 4-2016</th></tr>
  <tr><td>A. TÀI SẢN</td><td></td><td></td><td></td><td></td></tr>
  <tr><td>I. Tiền mặt, vàng bạc, đá quý</td><td>8,552</td><td>9,001</td>
      <td>9,120</td><td>10,340</td></tr>
  <tr><td>II. Cho vay khách hàng</td><td>420,000</td><td>430,500</td>
      <td>445,120</td><td>460,000</td></tr>
  <tr><td>III. Dự phòng rủi ro</td><td>(5,120)</td><td>(5,400)</td>
      <td>(5,610)</td><td>(6,000)</td></tr>
  <tr><td>TỔNG TÀI SẢN</td><td>750,000</td><td>770,000</td>
      <td>790,000</td><td>820,000</td></tr>
  <tr><td>B. NỢ PHẢI TRẢ</td><td>700,000</td><td>-</td>
      <td>740,000</td><td>770,000</td></tr>
  <tr><td>VỐN CHỦ SỞ HỮU</td><td>50,000</td><td>52,000</td>
      <td>54,000</td><td>56,000</td></tr>
  <tr><td>Vốn điều lệ</td><td>35,977</td><td>35,977</td>
      <td>35,977</td><td>35,977</td></tr>
  <tr><td>Lợi nhuận chưa phân phối</td><td>8,120</td><td>9,050</td>
      <td>10,200</td><td>11,400</td></tr>
  <tr><td>Các quỹ</td><td>5,903</td><td>6,973</td><td>7,823</td>
      <td>8,623</td></tr>
</table>
</body></html>
"""


class TestTableParser:
    def test_finds_every_table(self):
        assert len(S.parse_tables(_CAFEF_PAGE)) == 2

    def test_cells_come_out_as_trimmed_text(self):
        tables = S.parse_tables(_CAFEF_PAGE)
        assert tables[0]["rows"][0] == ["Trang chủ", "Dữ liệu"]

    def test_table_attributes_are_kept(self):
        ids = {t["attrs"].get("id") for t in S.parse_tables(_CAFEF_PAGE)}
        assert ids == {"menu", "tblGridData"}

    def test_a_missing_closing_tag_does_not_lose_the_table(self):
        assert len(S.parse_tables("<table><tr><td>a</td></tr>")) == 1

    def test_empty_input_gives_no_tables(self):
        assert S.parse_tables("") == [] and S.parse_tables(None) == []

    def test_entities_are_decoded(self):
        rows = S.parse_tables("<table><tr><td>a&amp;b</td></tr></table>")
        assert rows[0]["rows"][0] == ["a&b"]


class TestPickBalanceTable:
    def test_picks_the_table_with_quarter_headers(self):
        tb = S.pick_balance_table(S.parse_tables(_CAFEF_PAGE), min_rows=5)
        assert tb["attrs"]["id"] == "tblGridData"

    def test_a_navigation_table_is_never_picked(self):
        tables = [{"attrs": {"id": "menu"},
                   "rows": [["a", "b"]] * 40}]
        assert S.pick_balance_table(tables) is None

    def test_one_quarter_column_is_not_enough(self):
        tables = [{"attrs": {}, "rows": [["CHỈ TIÊU", "Quý 1-2016"]] + [["x", "1"]] * 20}]
        assert S.pick_balance_table(tables) is None

    def test_nothing_recognised_returns_none_instead_of_the_first_table(self):
        assert S.pick_balance_table([{"attrs": {}, "rows": [["a"]] * 30}]) is None

    def test_empty_input_returns_none(self):
        assert S.pick_balance_table([]) is None and S.pick_balance_table(None) is None


class TestParseVnNumber:
    def test_comma_thousands(self):
        assert S.parse_vn_number("1,234,567") == 1234567.0

    def test_dot_thousands(self):
        assert S.parse_vn_number("1.234.567") == 1234567.0

    def test_parentheses_mean_negative(self):
        assert S.parse_vn_number("(5,120)") == -5120.0

    def test_leading_minus_means_negative(self):
        assert S.parse_vn_number("-5,120") == -5120.0

    def test_a_real_decimal_is_kept(self):
        assert S.parse_vn_number("1,234.56") == 1234.56

    def test_blank_is_none_not_zero(self):
        assert S.parse_vn_number("") is None
        assert S.parse_vn_number("   ") is None

    def test_a_dash_placeholder_is_none_not_zero(self):
        assert S.parse_vn_number("-") is None

    def test_text_is_none(self):
        assert S.parse_vn_number("n/a") is None
        assert S.parse_vn_number("chưa có") is None

    def test_a_genuine_zero_stays_zero(self):
        assert S.parse_vn_number("0") == 0.0

    def test_none_does_not_raise(self):
        assert S.parse_vn_number(None) is None


class TestCafefToFrame:
    def test_shape_matches_the_shared_contract(self):
        df = S.cafef_to_frame(_CAFEF_PAGE)
        assert list(df.columns)[0] == "item"
        assert [qq for _, qq in E.detect_period_columns(df.columns)] == \
            [(2016, 1), (2016, 2), (2016, 3), (2016, 4)]

    def test_numbers_are_parsed_not_left_as_text(self):
        d = E.tidy(S.cafef_to_frame(_CAFEF_PAGE))
        assert d[(2016, 1)]["TỔNG TÀI SẢN"] == 750000.0

    def test_negative_in_parentheses_survives(self):
        d = E.tidy(S.cafef_to_frame(_CAFEF_PAGE))
        assert d[(2016, 1)]["III. Dự phòng rủi ro"] == -5120.0

    def test_a_dash_cell_is_blank_not_zero(self):
        d = E.tidy(S.cafef_to_frame(_CAFEF_PAGE))
        assert E._is_blank(d[(2016, 2)]["B. NỢ PHẢI TRẢ"])

    def test_heading_rows_with_no_numbers_are_kept_as_rows(self):
        assert "A. TÀI SẢN" in S.cafef_to_frame(_CAFEF_PAGE)["item"].tolist()

    def test_source_row_order_is_preserved(self):
        items = S.cafef_to_frame(_CAFEF_PAGE)["item"].tolist()
        assert items[0] == "A. TÀI SẢN"
        assert items.index("TỔNG TÀI SẢN") < items.index("VỐN CHỦ SỞ HỮU")

    def test_the_header_row_never_becomes_a_line_item(self):
        assert "CHỈ TIÊU" not in \
            [i for i in S.cafef_to_frame(_CAFEF_PAGE)["item"] if "Quý" in i]

    def test_unit_note_is_recorded_verbatim(self):
        assert "Triệu" in (S.cafef_to_frame(_CAFEF_PAGE).attrs["unit_note"] or "")

    def test_a_page_without_a_balance_table_gives_an_empty_frame(self):
        assert S.cafef_to_frame("<html><body>lỗi 404</body></html>").empty

    def test_empty_html_gives_an_empty_frame(self):
        assert S.cafef_to_frame("").empty


class TestCafefUnitNote:
    def test_reads_the_unit_sentence(self):
        assert S.cafef_unit_note("<i>Đơn vị: Tỷ VNĐ</i>") == "Tỷ VNĐ"

    def test_missing_unit_is_none_not_a_guess(self):
        assert S.cafef_unit_note("<html>không nói</html>") is None

    def test_none_input_does_not_raise(self):
        assert S.cafef_unit_note(None) is None


class TestMergeFrames:
    def test_two_years_become_eight_quarter_columns(self):
        a = S.cafef_to_frame(_CAFEF_PAGE.replace("2016", "2015"))
        b = S.cafef_to_frame(_CAFEF_PAGE)
        out = S.merge_frames([a, b])
        assert len(E.detect_period_columns(out.columns)) == 8

    def test_quarter_columns_come_out_in_order(self):
        a = S.cafef_to_frame(_CAFEF_PAGE.replace("2016", "2015"))
        b = S.cafef_to_frame(_CAFEF_PAGE)
        cols = [qq for _, qq in E.detect_period_columns(S.merge_frames([a, b]).columns)]
        assert cols == sorted(cols) and cols[0] == (2015, 1)

    def test_an_item_only_in_the_later_year_is_not_dropped(self):
        a = S.cafef_to_frame(_CAFEF_PAGE.replace("2016", "2015"))
        b = S.cafef_to_frame(
            _CAFEF_PAGE.replace("<td>Các quỹ</td>", "<td>Chỉ tiêu MỚI</td>"))
        assert "Chỉ tiêu MỚI" in S.merge_frames([a, b])["item"].tolist()

    def test_an_item_missing_from_one_year_is_blank_there_not_zero(self):
        a = S.cafef_to_frame(_CAFEF_PAGE.replace("2016", "2015"))
        b = S.cafef_to_frame(
            _CAFEF_PAGE.replace("<td>Các quỹ</td>", "<td>Chỉ tiêu MỚI</td>"))
        d = E.tidy(S.merge_frames([a, b]))
        assert E._is_blank(d[(2015, 1)]["Chỉ tiêu MỚI"])

    def test_a_single_frame_passes_through(self):
        a = S.cafef_to_frame(_CAFEF_PAGE)
        assert S.merge_frames([a]) is a

    def test_empty_frames_are_ignored(self):
        a = S.cafef_to_frame(_CAFEF_PAGE)
        assert not S.merge_frames([pd.DataFrame(), a]).empty

    def test_all_empty_gives_empty(self):
        assert S.merge_frames([pd.DataFrame(), None]).empty

    def test_unit_note_survives_the_merge(self):
        a = S.cafef_to_frame(_CAFEF_PAGE.replace("2016", "2015"))
        b = S.cafef_to_frame(_CAFEF_PAGE)
        assert S.merge_frames([a, b]).attrs.get("unit_note")


class TestSignatureSafeCall:
    """Vết 26/08: `vnstock` 4.0.4 trên máy user KHÔNG có `display_mode` trong
    `kbs…balance_sheet`, bản trong container thì CÓ. Truyền cứng ⇒ TypeError
    trên đúng cái máy duy nhất chạy được mạng."""

    def test_an_unsupported_kwarg_is_dropped_instead_of_raising(self):
        def f(period=None):
            return period
        assert E._call_with_supported_kwargs(f, period="quarter",
                                             display_mode=None) == "quarter"

    def test_a_supported_kwarg_is_passed_through(self):
        def f(period=None, show_log=False):
            return (period, show_log)
        assert E._call_with_supported_kwargs(
            f, period="quarter", show_log=True) == ("quarter", True)

    def test_a_function_taking_nothing_is_called_bare(self):
        assert E._call_with_supported_kwargs(lambda: "ok", period="quarter") == "ok"


class TestCrosscheckYears:
    def test_crosscheck_years_overlap_what_vci_actually_has(self):
        """VCI sớm nhất 2018-Q1. Đối chiếu ở 2015-2016 là đối chiếu với một
        bên RỖNG — không so được gì mà lại trông như đã kiểm."""
        assert min(E.CROSSCHECK_YEARS) >= 2018

    def test_cafef_default_years_are_the_ones_the_user_asked_for(self):
        assert set(E.CAFEF_DEFAULT_YEARS) == {2015, 2016}


class TestCafefFetchVsParseFailure:
    """Hai kiểu hỏng, hai cách chữa: KHÔNG tải được trang (mạng/URL) khác hẳn
    tải được mà bộ bóc không nhận ra bảng. Gộp thành 'rỗng' là đẩy người đọc
    đi sai đường — vết 26/08."""

    def test_no_page_downloaded_raises_instead_of_returning_empty(self, monkeypatch):
        monkeypatch.setattr(S, "fetch_cafef",
                            lambda t, y, q=4, **k: (403, "", "u"))
        with pytest.raises(S.CafefFetchError):
            S.fetch_cafef_years("VCB", (2015, 2016), pause_s=0)

    def test_the_error_names_the_http_status(self, monkeypatch):
        monkeypatch.setattr(S, "fetch_cafef",
                            lambda t, y, q=4, **k: (404, "", "u"))
        with pytest.raises(S.CafefFetchError, match="404"):
            S.fetch_cafef_years("VCB", (2016,), pause_s=0)

    def test_a_downloaded_but_unparseable_page_returns_empty_not_an_error(
            self, monkeypatch):
        monkeypatch.setattr(S, "fetch_cafef",
                            lambda t, y, q=4, **k: (200, "<html>trống</html>", "u"))
        assert S.fetch_cafef_years("VCB", (2016,), pause_s=0).empty

    def test_one_good_year_survives_one_bad_year(self, monkeypatch):
        def fake(t, y, q=4, **k):
            return (200, _CAFEF_PAGE, "u") if y == 2016 else (404, "", "u")
        monkeypatch.setattr(S, "fetch_cafef", fake)
        df = S.fetch_cafef_years("VCB", (2015, 2016), pause_s=0)
        assert len(E.detect_period_columns(df.columns)) == 4

    def test_two_good_years_merge_into_eight_quarters(self, monkeypatch):
        def fake(t, y, q=4, **k):
            return (200, _CAFEF_PAGE.replace("2016", str(y)), "u")
        monkeypatch.setattr(S, "fetch_cafef", fake)
        df = S.fetch_cafef_years("VCB", (2015, 2016), pause_s=0)
        assert len(E.detect_period_columns(df.columns)) == 8


# ─────────────────────────────────────────────────────────────────────────
# Chẩn đoán: bộ bóc trật ở trang THẬT (đo 26/08 lượt 2). `cafef_quarters_in`
# THẤY đủ 4 kỳ trong HTML mà `pick_balance_table` không ra bảng nào — tức
# chuỗi kỳ nằm ngoài ô <td>/<th>. Lưới ở đây canh việc chẩn đoán phân biệt
# đúng các CA HỎNG, vì mỗi ca chữa một kiểu.
# ─────────────────────────────────────────────────────────────────────────
_JS_PAGE = """<html><body><div id="app"></div>
<script>var cfg={url:"/Ajax/CongTy/BaoCaoTaiChinh.ashx?sym=VCB&type=BSheet"};
var d=[{"name":"Quý 1-2016","v":1},{"name":"Quý 4-2016","v":2}];</script>
</body></html>"""

_DIV_PAGE = """<html><body>
<div class="row"><div>CHỈ TIÊU</div><div>Quý 1-2016</div><div>Quý 4-2016</div></div>
<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>
</body></html>"""


class TestRawTagCounts:
    def test_counts_tables_rows_and_cells(self):
        c = S.raw_tag_counts(_CAFEF_PAGE)
        assert c["table"] == 2 and c["tr"] > 5 and c["td"] > 5

    def test_a_javascript_page_has_no_tables(self):
        assert S.raw_tag_counts(_JS_PAGE)["table"] == 0

    def test_scripts_are_counted(self):
        assert S.raw_tag_counts(_JS_PAGE)["script"] == 1

    def test_empty_input_gives_zeros(self):
        assert S.raw_tag_counts("")["table"] == 0
        assert S.raw_tag_counts(None)["tr"] == 0


class TestContextAround:
    def test_shows_the_text_surrounding_a_hit(self):
        ctx = S.context_around("xxx<th>Quý 1-2016</th>yyy", "Quý 1-2016", width=10)
        assert ctx and "th" in ctx[0]

    def test_whitespace_is_collapsed_so_one_paste_stays_readable(self):
        ctx = S.context_around("a\n\n  b Quý 1-2016 c", "Quý 1-2016")
        assert "\n" not in ctx[0]

    def test_multiple_hits_are_capped(self):
        html = "Quý 1-2016 " * 10
        assert len(S.context_around(html, "Quý 1-2016", limit=3)) == 3

    def test_no_hit_gives_nothing(self):
        assert S.context_around("<html/>", "Quý 1-2016") == []

    def test_none_html_does_not_raise(self):
        assert S.context_around(None, "x") == []


class TestCandidateDataUrls:
    def test_finds_an_ajax_handler_url(self):
        urls = S.candidate_data_urls(_JS_PAGE)
        assert any("BaoCaoTaiChinh.ashx" in u for u in urls)

    def test_a_plain_table_page_offers_nothing_misleading(self):
        assert S.candidate_data_urls(_CAFEF_PAGE) == []

    def test_duplicates_are_collapsed(self):
        html = '"/api/x/data.ashx" "/api/x/data.ashx"'
        assert len(S.candidate_data_urls(html)) == 1

    def test_the_list_is_capped(self):
        html = " ".join(f'"/api/{i}/data.ashx"' for i in range(50))
        assert len(S.candidate_data_urls(html, limit=5)) == 5

    def test_none_html_does_not_raise(self):
        assert S.candidate_data_urls(None) == []


class TestDiagnoseAndVerdict:
    def test_a_good_page_is_diagnosed_as_recognised(self):
        d = S.diagnose_cafef(_CAFEF_PAGE)
        assert d["balance_table_found"] is True
        assert "nhận ra bảng" in S.verdict_line(d)

    def test_a_javascript_page_points_at_the_data_url_not_the_selector(self):
        d = S.diagnose_cafef(_JS_PAGE)
        assert d["raw"]["table"] == 0
        assert "JS dựng" in S.verdict_line(d)
        assert d["data_urls"]

    def test_headers_outside_cells_are_named_as_such(self):
        """Đúng ca của lần đo 26/08: thấy chuỗi kỳ trong trang, mà không ô
        <td>/<th> nào chứa nó."""
        d = S.diagnose_cafef(_DIV_PAGE)
        assert d["quarters_seen"] and not d["balance_table_found"]
        assert "ngoài ô" in S.verdict_line(d)

    def test_diagnosis_reports_the_quarters_it_saw(self):
        d = S.diagnose_cafef(_CAFEF_PAGE)
        assert d["quarters_seen"] == [(2016, 1), (2016, 2), (2016, 3), (2016, 4)]

    def test_diagnosis_reports_the_biggest_table_size(self):
        assert S.diagnose_cafef(_CAFEF_PAGE)["biggest_table_rows"] >= 10

    def test_an_empty_page_does_not_raise(self):
        d = S.diagnose_cafef("")
        assert d["balance_table_found"] is False and d["quarters_seen"] == []


# ─────────────────────────────────────────────────────────────────────────
# Trang CafeF THẬT (đo 26/08 lượt 3, `--dump-cafef VCB`): 124 thẻ <table>,
# bảng lớn nhất `tableContent` 119 hàng, đơn vị "tỷ đồng", và **4 hàng đầu
# rỗng trơn**. Bảng LỒNG trong bảng là chuyện bình thường ở đó. Ba lưới dưới
# đây tái hiện đúng ba thứ đã làm bộ bóc trượt.
# ─────────────────────────────────────────────────────────────────────────
_NESTED_PAGE = """<html><body>
<div>Đơn vị: tỷ đồng</div>
<table id="outer">
  <tr><td><table id="inner"><tr><td>quảng cáo</td></tr></table></td>
      <td>CỘT SAU BẢNG LỒNG</td></tr>
</table>
</body></html>"""

_REAL_SHAPE_PAGE = """<html><body>
<div>Đơn vị: tỷ đồng</div>
<table id="tableContent">
  <tr></tr>
  <tr><td></td><td></td></tr>
  <tr></tr>
  <tr></tr>
  <tr><td></td><td>CHỈ TIÊU</td><td>Quý 1 - 2016</td><td>Quý 2 - 2016</td>
      <td>Quý 3 - 2016</td><td>Quý 4 - 2016</td></tr>
  <tr><td>+</td><td>TỔNG TÀI SẢN</td><td>750,000</td><td>770,000</td>
      <td>790,000</td><td>820,000</td></tr>
  <tr><td>+</td><td>Cho vay khách hàng</td><td>420,000</td><td>430,500</td>
      <td>445,120</td><td>460,000</td></tr>
  <tr><td></td><td>Dự phòng rủi ro</td><td>(5,120)</td><td>(5,400)</td>
      <td>(5,610)</td><td>(6,000)</td></tr>
  <tr><td></td><td>VỐN CHỦ SỞ HỮU</td><td>50,000</td><td>52,000</td>
      <td>54,000</td><td>56,000</td></tr>
  <tr><td></td><td>Vốn điều lệ</td><td>35,977</td><td>35,977</td>
      <td>35,977</td><td>35,977</td></tr>
  <tr><td></td><td>Các quỹ</td><td>5,903</td><td>6,973</td><td>7,823</td>
      <td>8,623</td></tr>
  <tr><td></td><td>Lợi nhuận chưa phân phối</td><td>8,120</td><td>9,050</td>
      <td>10,200</td><td>11,400</td></tr>
  <tr><td></td><td>Tiền mặt</td><td>8,552</td><td>9,001</td><td>9,120</td>
      <td>10,340</td></tr>
  <tr><td></td><td>Tiền gửi tại NHNN</td><td>10,000</td><td>11,000</td>
      <td>12,000</td><td>13,000</td></tr>
  <tr><td></td><td>Tài sản có khác</td><td>3,000</td><td>3,100</td>
      <td>3,200</td><td>3,300</td></tr>
</table>
</body></html>"""


class TestNestedTables:
    """Bản đầu giữ hàng/ô ở mức TOÀN CỤC, nên `</tr>` của bảng CON đặt hàng
    đang mở về None và mọi ô còn lại của hàng NGOÀI rơi mất. Đó là lý do
    bảng 119 hàng ra 4 hàng đầu rỗng trơn — mất luôn hàng tiêu đề."""

    def test_a_cell_after_a_nested_table_is_not_lost(self):
        outer = next(t for t in S.parse_tables(_NESTED_PAGE)
                     if t["attrs"].get("id") == "outer")
        assert "CỘT SAU BẢNG LỒNG" in outer["rows"][0]

    def test_the_inner_table_is_reported_separately(self):
        inner = next(t for t in S.parse_tables(_NESTED_PAGE)
                     if t["attrs"].get("id") == "inner")
        assert inner["rows"] == [["quảng cáo"]]

    def test_inner_text_does_not_leak_into_the_outer_cell(self):
        outer = next(t for t in S.parse_tables(_NESTED_PAGE)
                     if t["attrs"].get("id") == "outer")
        assert "quảng cáo" not in " ".join(outer["rows"][0])

    def test_the_row_key_is_not_left_behind_in_the_result(self):
        assert all("row" not in t for t in S.parse_tables(_NESTED_PAGE))

    def test_deeply_nested_tables_all_come_back(self):
        html = "<table><tr><td><table><tr><td><table><tr><td>x</td></tr>" \
               "</table></td></tr></table></td></tr></table>"
        assert len(S.parse_tables(html)) == 3


class TestHeaderRowIndex:
    def test_finds_a_header_that_is_not_in_the_first_rows(self):
        rows = S.parse_tables(_REAL_SHAPE_PAGE)[0]["rows"]
        assert S.header_row_index(rows) == 4

    def test_a_table_without_periods_has_no_header(self):
        assert S.header_row_index([["a", "b"], ["c", "d"]]) is None

    def test_one_period_cell_is_not_a_header(self):
        assert S.header_row_index([["CHỈ TIÊU", "Quý 1-2016"]]) is None

    def test_empty_rows_do_not_raise(self):
        assert S.header_row_index([]) is None and S.header_row_index(None) is None


class TestLabelColIndex:
    def test_picks_the_text_column_not_the_leading_button_column(self):
        rows = S.parse_tables(_REAL_SHAPE_PAGE)[0]["rows"]
        h = S.header_row_index(rows)
        assert S.label_col_index(rows, h, S.header_periods(rows[h])) == 1

    def test_falls_back_to_column_zero_when_there_is_nothing_to_the_left(self):
        rows = [["CHỈ TIÊU", "Quý 1-2016", "Quý 2-2016"], ["TS", "1", "2"]]
        assert S.label_col_index(rows, 0, S.header_periods(rows[0])) == 0


class TestRealShapePage:
    """Cả ba khiếm khuyết cùng lúc: hàng chèn rỗng, tiêu đề kỳ có khoảng
    trắng (`Quý 1 - 2016`), cột đầu là nút bấm chứ không phải tên chỉ tiêu."""

    def test_the_balance_table_is_recognised(self):
        assert S.pick_balance_table(S.parse_tables(_REAL_SHAPE_PAGE)) is not None

    def test_all_four_quarters_come_through(self):
        df = S.cafef_to_frame(_REAL_SHAPE_PAGE)
        assert [qq for _, qq in E.detect_period_columns(df.columns)] == \
            [(2016, 1), (2016, 2), (2016, 3), (2016, 4)]

    def test_item_names_come_from_the_right_column(self):
        items = S.cafef_to_frame(_REAL_SHAPE_PAGE)["item"].tolist()
        assert "TỔNG TÀI SẢN" in items and "+" not in items

    def test_numbers_land_under_the_right_quarter(self):
        d = E.tidy(S.cafef_to_frame(_REAL_SHAPE_PAGE))
        assert d[(2016, 1)]["TỔNG TÀI SẢN"] == 750000.0
        assert d[(2016, 4)]["TỔNG TÀI SẢN"] == 820000.0

    def test_negatives_in_parentheses_survive(self):
        d = E.tidy(S.cafef_to_frame(_REAL_SHAPE_PAGE))
        assert d[(2016, 2)]["Dự phòng rủi ro"] == -5400.0

    def test_the_unit_is_recorded_verbatim_not_converted(self):
        assert S.cafef_to_frame(_REAL_SHAPE_PAGE).attrs["unit_note"] == "tỷ đồng"

    def test_the_header_row_never_becomes_a_line_item(self):
        assert "CHỈ TIÊU" not in \
            [i for i in S.cafef_to_frame(_REAL_SHAPE_PAGE)["item"]
             if S.cell_quarter(i)]

    def test_the_diagnosis_now_says_recognised(self):
        assert "nhận ra bảng" in S.verdict_line(S.diagnose_cafef(_REAL_SHAPE_PAGE))


class TestQuarterContexts:
    """Vết 26/08: bản đầu dò bằng chuỗi ghép tay `f"Quý {q}-{y}"`, nên trang
    thật viết `Quý 4 - 2016` là không khớp — phần chẩn đoán quan trọng nhất
    im lặng bỏ qua. Đã thấy bằng regex nào thì phải định vị bằng regex đó."""

    def test_a_spaced_quarter_label_is_located(self):
        ctx = S.quarter_contexts("<td>Quý 4 - 2016</td>")
        assert ctx and "td" in ctx[0]

    def test_it_finds_what_cafef_quarters_in_found(self):
        html = "<div>Quý 1 - 2016</div>"
        assert S.cafef_quarters_in(html) and S.quarter_contexts(html)

    def test_output_is_capped(self):
        html = " ".join(f"Quý {q} - 2016" for q in (1, 2, 3, 4)) * 5
        assert len(S.quarter_contexts(html, limit=4)) == 4

    def test_no_quarter_gives_nothing(self):
        assert S.quarter_contexts("<html/>") == []

    def test_none_html_does_not_raise(self):
        assert S.quarter_contexts(None) == []


class TestNonemptyRows:
    def test_leading_blank_rows_are_skipped(self):
        rows = S.parse_tables(_REAL_SHAPE_PAGE)[0]["rows"]
        assert S.nonempty_rows(rows)[0][0] == 4

    def test_the_original_row_index_is_kept(self):
        out = S.nonempty_rows([[""], ["x"], [""], ["y"]])
        assert [i for i, _ in out] == [1, 3]

    def test_the_list_is_capped(self):
        assert len(S.nonempty_rows([["x"]] * 50, limit=6)) == 6

    def test_all_blank_gives_nothing(self):
        assert S.nonempty_rows([[""], ["", " "]]) == []


class TestDuplicateItemNames:
    """Bỏ dòng trùng tên là MẤT SỐ im lặng. Bảng cân đối thật có nhãn lặp
    lại ở hai mục khác nhau; đánh số là việc tất định nên mọi ngân hàng vẫn
    ra cùng một bộ nhãn, xếp ngang được."""

    _DUP = _REAL_SHAPE_PAGE.replace(
        "<td>Tài sản có khác</td><td>3,000</td>",
        "<td>Tài sản có khác</td><td>3,000</td>", 1).replace(
        "</table>",
        "<tr><td></td><td>Tài sản có khác</td><td>777</td><td>778</td>"
        "<td>779</td><td>780</td></tr></table>", 1)

    def test_the_second_occurrence_is_numbered_not_dropped(self):
        items = S.cafef_to_frame(self._DUP)["item"].tolist()
        assert "Tài sản có khác" in items and "Tài sản có khác (2)" in items

    def test_the_second_occurrence_keeps_its_own_numbers(self):
        d = E.tidy(S.cafef_to_frame(self._DUP))
        assert d[(2016, 1)]["Tài sản có khác"] == 3000.0
        assert d[(2016, 1)]["Tài sản có khác (2)"] == 777.0

    def test_row_count_grows_by_one(self):
        assert len(S.cafef_to_frame(self._DUP)) == \
            len(S.cafef_to_frame(_REAL_SHAPE_PAGE)) + 1
