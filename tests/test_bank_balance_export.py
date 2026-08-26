"""
Lưới cho `scripts/export_bank_balance_sheets.py`.

Yêu cầu user chốt: **format bảng cân đối phải ĐỒNG NHẤT giữa các sheet.** Đó
chính xác là thứ nguồn dữ liệu KHÔNG cho sẵn — `vnstock` mặc định
`dropna=True`, và chỗ đó làm `df.loc[:, (df != 0).any(axis=0)]`, tức **bỏ các
CHỈ TIÊU toàn 0**, mỗi ngân hàng bỏ một bộ khác nhau.

Ca nguy hiểm thứ hai, tệ hơn: `_get_financial_report` có
`effective_limit = limit if limit is not None else 4`, mà phương thức công
khai `balance_sheet()` KHÔNG nhận `limit`. Đi đường thường ⇒ chỉ 4 quý gần
nhất ⇒ file 2015-2016 RỖNG mà vẫn ghi ra bình thường. **File rỗng trông như
thật là thứ nguy hiểm nhất ở đây**, nên script từ chối ghi khi không có mã nào
có dữ liệu.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_bank_balance_sheets.py"
_spec = importlib.util.spec_from_file_location("bank_bs_export", _SCRIPT)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def _frame(rows, items):
    """Frame giống nguồn: hàng = kỳ, cột = chỉ tiêu."""
    recs = []
    for (y, q), vals in rows.items():
        rec = {"yearReport": y, "lengthReport": q, "report_period": "quarter"}
        rec.update({it: vals.get(it) for it in items})
        recs.append(rec)
    return pd.DataFrame(recs)


class TestQuarterAxis:
    def test_two_years_give_eight_quarters_in_order(self):
        qs = _m.quarters_between(2015, 2016)
        assert len(qs) == 8 and qs[0] == (2015, 1) and qs[-1] == (2016, 4)

    def test_label_format(self):
        assert _m.quarter_label(2015, 3) == "2015-Q3"


class TestPeriodColumnDetection:
    def test_finds_the_vci_column_names(self):
        assert _m.detect_period_columns(
            ["yearReport", "lengthReport", "Tổng tài sản"]) == \
            ("yearReport", "lengthReport")

    def test_finds_vietnamese_labels(self):
        assert _m.detect_period_columns(["Năm", "Quý", "X"]) == ("Năm", "Quý")

    def test_returns_none_rather_than_guessing(self):
        # Đoán bừa cột kỳ = ghi ra một file trông như thật nhưng sai kỳ
        assert _m.detect_period_columns(["a", "b", "c"]) is None

    def test_missing_one_of_the_pair_is_still_none(self):
        assert _m.detect_period_columns(["yearReport", "Tổng tài sản"]) is None


class TestTidy:
    def test_maps_periods_to_line_items(self):
        df = _frame({(2015, 1): {"TS": 10, "NO": 4}}, ["TS", "NO"])
        got = _m.tidy(df, "yearReport", "lengthReport")
        assert got == {(2015, 1): {"TS": 10, "NO": 4}}

    def test_metadata_columns_are_not_line_items(self):
        df = _frame({(2015, 1): {"TS": 10}}, ["TS"])
        assert list(_m.tidy(df, "yearReport", "lengthReport")[(2015, 1)]) == ["TS"]

    def test_unreadable_period_rows_are_dropped_not_guessed(self):
        df = pd.DataFrame([{"yearReport": "x", "lengthReport": 1, "TS": 5},
                           {"yearReport": 2015, "lengthReport": 9, "TS": 6},
                           {"yearReport": 2015, "lengthReport": 2, "TS": 7}])
        assert list(_m.tidy(df, "yearReport", "lengthReport")) == [(2015, 2)]


class TestUnifiedLayout:
    """Trái tim của yêu cầu 'format đồng nhất'."""

    def _two_banks(self):
        a = _m.tidy(_frame({(2015, 1): {"TS": 1, "NO": 2}}, ["TS", "NO"]),
                    "yearReport", "lengthReport")
        b = _m.tidy(_frame({(2015, 1): {"TS": 3, "VON": 4}}, ["TS", "VON"]),
                    "yearReport", "lengthReport")
        return {"AAA": a, "BBB": b}

    def test_union_covers_items_only_one_bank_has(self):
        assert set(_m.unified_items(self._two_banks())) == {"TS", "NO", "VON"}

    def test_source_order_is_preserved_not_alphabetised(self):
        # Bảng cân đối có trật tự CÓ NGHĨA (tài sản → nợ → vốn chủ);
        # sắp xếp abc là phá cấu trúc đó
        assert _m.unified_items(self._two_banks()) == ["TS", "NO", "VON"]

    def test_every_bank_gets_the_same_number_of_rows(self):
        per = self._two_banks()
        items, qs = _m.unified_items(per), _m.quarters_between(2015, 2015)
        sizes = {tk: len(_m.sheet_matrix(items, qs, d)) for tk, d in per.items()}
        assert len(set(sizes.values())) == 1 == len(set(sizes.values()))
        assert set(sizes.values()) == {3}

    def test_a_missing_item_is_BLANK_not_zero(self):
        """Trong bảng cân đối, 'không có số' và 'bằng 0' là hai chuyện khác
        hẳn — điền 0 là bịa một dữ kiện."""
        per = self._two_banks()
        items, qs = _m.unified_items(per), _m.quarters_between(2015, 2015)
        rows = _m.sheet_matrix(items, qs, per["AAA"])
        assert rows[items.index("VON")][0] is None

    def test_a_missing_quarter_is_blank_across_the_whole_column(self):
        per = self._two_banks()
        items, qs = _m.unified_items(per), _m.quarters_between(2015, 2015)
        rows = _m.sheet_matrix(items, qs, per["AAA"])
        assert all(r[3] is None for r in rows)          # Q4 không có data

    def test_nan_is_treated_as_missing(self):
        d = _m.tidy(_frame({(2015, 1): {"TS": float("nan")}}, ["TS"]),
                    "yearReport", "lengthReport")
        assert _m.sheet_matrix(["TS"], [(2015, 1)], d) == [[None]]


class TestCoverage:
    def test_reports_gaps_instead_of_hiding_them(self):
        d = _m.tidy(_frame({(2015, 1): {"TS": 5}}, ["TS"]),
                    "yearReport", "lengthReport")
        r = _m.coverage_row("AAA", _m.quarters_between(2015, 2016), d)
        assert r["quarters_found"] == 1 and r["quarters_asked"] == 8
        assert r["first"] == "2015-Q1" and r["last"] == "2015-Q1"

    def test_max_abs_lets_the_reader_infer_the_unit(self):
        d = _m.tidy(_frame({(2015, 1): {"TS": -1.2e15}}, ["TS"]),
                    "yearReport", "lengthReport")
        assert _m.coverage_row("AAA", [(2015, 1)], d)["max_abs"] == pytest.approx(1.2e15)

    def test_a_bank_with_nothing_reports_zero_not_a_crash(self):
        r = _m.coverage_row("ZZZ", _m.quarters_between(2015, 2016), {})
        assert r["quarters_found"] == 0 and r["first"] == ""


class TestWorkbook:
    def test_it_really_writes_a_readable_workbook(self, tmp_path):
        from openpyxl import load_workbook
        per = {"AAA": _m.tidy(_frame({(2015, 1): {"TS": 1, "NO": 2}}, ["TS", "NO"]),
                              "yearReport", "lengthReport"),
               "BBB": _m.tidy(_frame({(2015, 2): {"TS": 3, "VON": 4}}, ["TS", "VON"]),
                              "yearReport", "lengthReport")}
        qs = _m.quarters_between(2015, 2015)
        items = _m.unified_items(per)
        cov = [_m.coverage_row(t, qs, d) for t, d in per.items()]
        out = tmp_path / "x.xlsx"
        _m.write_workbook(out, per, items, qs, cov, "vi")

        wb = load_workbook(out)
        assert wb.sheetnames[0].startswith("0_")        # tầm phủ đứng đầu
        assert set(wb.sheetnames[1:]) == {"AAA", "BBB"}

        # BỐ CỤC ĐỒNG NHẤT: cùng dòng chỉ tiêu, cùng cột quý
        def _layout(ws):
            heads = [c.value for c in ws[2]]
            labels = [ws.cell(row=r, column=1).value
                      for r in range(3, 3 + len(items))]
            return heads, labels
        assert _layout(wb["AAA"]) == _layout(wb["BBB"])

        # Ô thiếu phải TRỐNG, không phải 0
        row_von = 3 + items.index("VON")
        assert wb["AAA"].cell(row=row_von, column=2).value is None

    def test_sheet_names_stay_within_the_excel_limit(self, tmp_path):
        from openpyxl import load_workbook
        long_tk = "A" * 40
        per = {long_tk: _m.tidy(_frame({(2015, 1): {"TS": 1}}, ["TS"]),
                                "yearReport", "lengthReport")}
        qs = _m.quarters_between(2015, 2015)
        out = tmp_path / "y.xlsx"
        _m.write_workbook(out, per, ["TS"], qs,
                          [_m.coverage_row(long_tk, qs, per[long_tk])], "vi")
        assert all(len(n) <= 31 for n in load_workbook(out).sheetnames)


class TestRefusesToShipAnEmptyFile:
    def test_no_data_means_no_file(self, tmp_path, monkeypatch, capsys):
        """File rỗng trông như thật là thứ nguy hiểm nhất ở đây."""
        monkeypatch.setattr(_m, "fetch_balance_sheet",
                            lambda *a, **k: pd.DataFrame())
        out = tmp_path / "z.xlsx"
        rc = _m.main(["--tickers", "AAA", "--out", str(out)])
        assert rc == 2 and not out.exists()
        assert "KHÔNG ghi file" in capsys.readouterr().out


class TestTheTrapsAreDocumentedWhereTheyBite:
    def test_the_fetch_passes_limit_and_disables_dropna(self):
        """Hai cái bẫy của nguồn: `limit` mặc định 4 kỳ, và `dropna=True` bỏ
        chỉ tiêu toàn 0 (khác nhau giữa các mã ⇒ phá format đồng nhất)."""
        import inspect
        src = inspect.getsource(_m.fetch_balance_sheet)
        assert "dropna=False" in src and "limit=limit" in src
        assert "_get_financial_report" in src   # đường CÔNG KHAI không nhận limit

    def test_default_limit_is_deep_enough_for_2015(self):
        # 2015-Q1 cách hiện tại ~46 quý
        assert _m.DEFAULT_LIMIT >= 60
