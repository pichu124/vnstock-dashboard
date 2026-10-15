"""
Lưới cho `scripts/export_bank_balance_sheets.py`.

Yêu cầu user chốt: **format bảng cân đối phải ĐỒNG NHẤT giữa các sheet.** Đó
chính xác là thứ nguồn dữ liệu KHÔNG cho sẵn — `vnstock` mặc định
`dropna=True`, và chỗ đó làm `df.loc[:, (df != 0).any(axis=0)]`, tức **bỏ các
CHỈ TIÊU toàn 0**, mỗi ngân hàng bỏ một bộ khác nhau.

Ca nguy hiểm thứ hai, tệ hơn: `_get_financial_report` có
`effective_limit = limit if limit is not None else 4`, mà phương thức công
khai `balance_sheet()` KHÔNG nhận `limit`. Đi đường thường ⇒ chỉ 4 quý gần
nhất. **File rỗng trông như thật là thứ nguy hiểm nhất ở đây**, nên script từ
chối ghi khi không mã nào có dữ liệu trong khoảng đã xin.

⚠️ DẠNG FRAME THẬT (đo bằng `--probe VCB`, 26/08) — **ngược hẳn giả định đầu
tiên của tôi**:

    86 hàng × 37 cột
    item | item_en | item_id | 2018-Q1 | 2018-Q2 | … | 2026-Q2

tức **HÀNG là chỉ tiêu, CỘT là kỳ**. Và kỳ SỚM NHẤT nguồn có là **2018-Q1** —
2015-2016 KHÔNG tồn tại ở nguồn này.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import needs

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_bank_balance_sheets.py"
_spec = importlib.util.spec_from_file_location("bank_bs_export", _SCRIPT)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def _frame(items, quarters, values=None, drop=()):
    """Frame ĐÚNG DẠNG NGUỒN: hàng = chỉ tiêu, cột = kỳ (`2018-Q1`…)."""
    recs = []
    for i, it in enumerate(items):
        if it in drop:
            continue
        rec = {"item": it, "item_en": it, "item_id": i}
        for (y, q) in quarters:
            rec[f"{y}-Q{q}"] = (values or {}).get((it, y, q))
        recs.append(rec)
    return pd.DataFrame(recs)


_Q = [(2018, 1), (2018, 2)]


class TestQuarterAxis:
    def test_two_years_give_eight_quarters_in_order(self):
        qs = _m.quarters_between(2018, 2019)
        assert len(qs) == 8 and qs[0] == (2018, 1) and qs[-1] == (2019, 4)

    def test_label_format(self):
        assert _m.quarter_label(2018, 3) == "2018-Q3"


class TestPeriodColumnDetection:
    def test_finds_the_real_vci_period_columns(self):
        cols = ["item", "item_en", "item_id", "2018-Q1", "2018-Q2", "2026-Q2"]
        assert _m.detect_period_columns(cols) == [
            ("2018-Q1", (2018, 1)), ("2018-Q2", (2018, 2)),
            ("2026-Q2", (2026, 2))]

    def test_periods_come_back_sorted(self):
        got = _m.detect_period_columns(["2019-Q1", "2018-Q3", "2018-Q1"])
        assert [p for _, p in got] == [(2018, 1), (2018, 3), (2019, 1)]

    def test_label_columns_are_not_mistaken_for_periods(self):
        assert _m.detect_period_columns(["item", "item_en", "item_id"]) == []

    def test_no_period_columns_returns_empty_not_a_guess(self):
        # Đoán bừa dạng frame = ghi ra file trông như thật (vết 26/08)
        assert _m.detect_period_columns(["a", "b"]) == []

    def test_label_column_follows_lang(self):
        cols = ["item", "item_en", "item_id"]
        assert _m.label_column(cols, "vi") == "item"
        assert _m.label_column(cols, "en") == "item_en"

    def test_label_column_missing_is_none(self):
        assert _m.label_column(["2018-Q1"], "vi") is None


class TestTidy:
    def test_transposes_rows_of_items_into_periods(self):
        df = _frame(["TS", "NO"], _Q,
                    {("TS", 2018, 1): 10, ("NO", 2018, 1): 4,
                     ("TS", 2018, 2): 11, ("NO", 2018, 2): 5})
        assert _m.tidy(df, "vi") == {(2018, 1): {"TS": 10, "NO": 4},
                                     (2018, 2): {"TS": 11, "NO": 5}}

    def test_a_frame_without_period_columns_yields_nothing(self):
        assert _m.tidy(pd.DataFrame([{"item": "TS"}]), "vi") == {}

    def test_source_row_order_is_preserved(self):
        """Nguồn ĐÃ trả đúng thứ tự bảng cân đối (tài sản → nợ → vốn chủ).
        Tự sắp lại theo khung riêng là rước rủi ro xếp nhầm dòng."""
        order = ["TỔNG TÀI SẢN", "1. Tiền mặt", "2. Tiền gửi"]
        df = _frame(order, _Q)
        assert _m.source_item_order(df, "vi") == order


class TestHeadingDetection:
    def test_all_caps_and_totals_are_headings(self):
        assert _m.is_heading("TỔNG TÀI SẢN")
        assert _m.is_heading("A. TÀI SẢN")
        assert _m.is_heading("Tổng nợ phải trả")

    def test_ordinary_line_items_are_not(self):
        assert not _m.is_heading("1. Tiền mặt, vàng bạc, đá quý")
        assert not _m.is_heading("Cho vay khách hàng")

    def test_blank_is_not_a_heading(self):
        assert not _m.is_heading("") and not _m.is_heading(None)


class TestOrdinalStripping:
    def test_a_leading_number_is_stripped(self):
        assert _m._key("1. Tiền mặt, vàng bạc, đá quý") == "tien mat vang bac da quy"

    def test_a_roman_numeral_is_stripped(self):
        assert _m._key("IV. Chứng khoán đầu tư") == "chung khoan dau tu"

    def test_a_leading_letter_of_a_real_word_is_NOT_eaten(self):
        """Vết 26/08: regex bỏ số thứ tự ăn luôn chữ cái đầu — 'Cho vay khách
        hàng' thành 'ho vay khach hang' (c là chữ số La Mã), 'Vốn điều lệ'
        thành 'on dieu le'. Phải có dấu ngăn phía sau mới được bóc."""
        assert _m._key("Cho vay khách hàng") == "cho vay khach hang"
        assert _m._key("Vốn điều lệ") == "von dieu le"
        assert _m._key("Chi phí dự phòng") == "chi phi du phong"


class TestUnifiedLayout:
    """Trái tim của yêu cầu 'format đồng nhất giữa các sheet'."""

    def _two_banks(self):
        a = _frame(["TS", "NO"], _Q, {("TS", 2018, 1): 1, ("NO", 2018, 1): 2})
        b = _frame(["TS", "VON"], _Q, {("TS", 2018, 1): 3, ("VON", 2018, 1): 4})
        per = {"AAA": _m.tidy(a, "vi"), "BBB": _m.tidy(b, "vi")}
        orders = {"AAA": _m.source_item_order(a, "vi"),
                  "BBB": _m.source_item_order(b, "vi")}
        return per, orders

    def test_union_covers_items_only_one_bank_has(self):
        per, orders = self._two_banks()
        assert set(_m.unified_items(per, orders)) == {"TS", "NO", "VON"}

    def test_source_order_is_preserved_not_alphabetised(self):
        per, orders = self._two_banks()
        assert _m.unified_items(per, orders) == ["TS", "NO", "VON"]

    def test_every_bank_gets_the_same_number_of_rows(self):
        per, orders = self._two_banks()
        items = _m.unified_items(per, orders)
        sizes = {tk: len(_m.sheet_matrix(items, _Q, d)) for tk, d in per.items()}
        assert set(sizes.values()) == {3}

    def test_a_missing_item_is_BLANK_not_zero(self):
        """Trong bảng cân đối, 'không có số' và 'bằng 0' là hai chuyện khác
        hẳn — điền 0 là bịa một dữ kiện."""
        per, orders = self._two_banks()
        items = _m.unified_items(per, orders)
        rows = _m.sheet_matrix(items, _Q, per["AAA"])
        assert rows[items.index("VON")][0] is None

    def test_a_missing_quarter_is_blank_across_the_whole_column(self):
        per, orders = self._two_banks()
        items = _m.unified_items(per, orders)
        rows = _m.sheet_matrix(items, [(2018, 1), (2019, 4)], per["AAA"])
        assert all(r[1] is None for r in rows)

    def test_nan_is_treated_as_missing(self):
        d = _m.tidy(_frame(["TS"], _Q, {("TS", 2018, 1): float("nan")}), "vi")
        assert _m.sheet_matrix(["TS"], [(2018, 1)], d) == [[None]]


class TestCoverage:
    def test_reports_gaps_instead_of_hiding_them(self):
        d = _m.tidy(_frame(["TS"], [(2018, 1)], {("TS", 2018, 1): 5}), "vi")
        r = _m.coverage_row("AAA", _m.quarters_between(2018, 2019), d)
        assert r["quarters_found"] == 1 and r["quarters_asked"] == 8
        assert r["first"] == "2018-Q1" and r["last"] == "2018-Q1"

    def test_max_abs_lets_the_reader_infer_the_unit(self):
        d = _m.tidy(_frame(["TS"], [(2018, 1)], {("TS", 2018, 1): -1.2e15}), "vi")
        assert _m.coverage_row("AAA", [(2018, 1)], d)["max_abs"] == pytest.approx(1.2e15)

    def test_a_bank_with_nothing_reports_zero_not_a_crash(self):
        r = _m.coverage_row("ZZZ", _m.quarters_between(2018, 2019), {})
        assert r["quarters_found"] == 0 and r["first"] == ""


@needs("openpyxl")
class TestWorkbook:
    def _build(self, tmp_path):
        items_a = ["TÀI SẢN", "1. Tiền mặt", "TỔNG TÀI SẢN",
                   "TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU"]
        items_b = ["TÀI SẢN", "1. Tiền mặt", "2. Cho vay khách hàng",
                   "TỔNG TÀI SẢN", "TỔNG NỢ PHẢI TRẢ VÀ VỐN CHỦ SỞ HỮU"]
        va = {(it, 2018, 1): 10 for it in items_a}
        vb = {(it, 2018, 1): 20 for it in items_b}
        fa, fb = _frame(items_a, _Q, va), _frame(items_b, _Q, vb)
        per = {"AAA": _m.tidy(fa, "vi"), "BBB": _m.tidy(fb, "vi")}
        orders = {"AAA": _m.source_item_order(fa, "vi"),
                  "BBB": _m.source_item_order(fb, "vi")}
        items = _m.unified_items(per, orders)
        cov = [_m.coverage_row(t, _Q, d) for t, d in per.items()]
        out = tmp_path / "x.xlsx"
        _m.write_workbook(out, per, items, _Q, cov, "vi")
        return out, items

    def test_it_really_writes_a_readable_workbook(self, tmp_path):
        from openpyxl import load_workbook
        out, items = self._build(tmp_path)
        wb = load_workbook(out)
        assert wb.sheetnames[0].startswith("0_")
        assert set(wb.sheetnames[1:]) == {"AAA", "BBB"}

        def _layout(ws):
            return [ws.cell(row=r, column=1).value
                    for r in range(2, ws.max_row + 1)]
        assert _layout(wb["AAA"]) == _layout(wb["BBB"])

        row = 3 + items.index("2. Cho vay khách hàng")
        assert wb["AAA"].cell(row=row, column=2).value is None   # TRỐNG, không phải 0
        assert wb["BBB"].cell(row=row, column=2).value == 20

    def test_the_balance_check_is_a_formula_not_a_python_result(self, tmp_path):
        from openpyxl import load_workbook
        out, _ = self._build(tmp_path)
        ws = load_workbook(out)["AAA"]
        assert "KIỂM TRA" in str(ws.cell(row=ws.max_row, column=1).value)
        f = str(ws.cell(row=ws.max_row, column=2).value)
        assert f.startswith("=IFERROR(") and "-" in f

    def test_headings_are_bold(self, tmp_path):
        from openpyxl import load_workbook
        out, items = self._build(tmp_path)
        ws = load_workbook(out)["AAA"]
        r_head = 3 + items.index("TỔNG TÀI SẢN")
        r_item = 3 + items.index("1. Tiền mặt")
        assert ws.cell(row=r_head, column=1).font.bold
        assert not ws.cell(row=r_item, column=1).font.bold

    def test_sheet_names_stay_within_the_excel_limit(self, tmp_path):
        from openpyxl import load_workbook
        long_tk = "A" * 40
        f = _frame(["TS"], _Q, {("TS", 2018, 1): 1})
        per = {long_tk: _m.tidy(f, "vi")}
        out = tmp_path / "y.xlsx"
        _m.write_workbook(out, per, ["TS"], _Q,
                          [_m.coverage_row(long_tk, _Q, per[long_tk])], "vi")
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

    def test_asking_before_the_source_starts_says_so_and_suggests_a_range(
            self, tmp_path, monkeypatch, capsys):
        """Ca THẬT 26/08: user xin 2015-2016, nguồn chỉ có từ 2018-Q1. Script
        phải nói ra kỳ sớm nhất và gợi khoảng dùng được — im lặng trả file
        rỗng là đổ lỗi cho user."""
        df = _frame(["TS"], [(2018, 1), (2018, 2)], {("TS", 2018, 1): 5})
        monkeypatch.setattr(_m, "fetch_balance_sheet", lambda *a, **k: df)
        out = tmp_path / "z.xlsx"
        rc = _m.main(["--tickers", "AAA", "--from", "2015", "--to", "2016",
                      "--out", str(out)])
        got = capsys.readouterr().out
        assert rc == 2 and not out.exists()
        assert "2018-Q1" in got and "--from 2018" in got

    @needs("openpyxl")
    def test_a_bank_with_no_quarters_is_dropped_not_shipped_blank(
            self, tmp_path, monkeypatch):
        """Mã không có quý nào trong khoảng thì không được thành một sheet
        trống rỗng nằm giữa các sheet có số."""
        full = _frame(["TS"], [(2018, 1)], {("TS", 2018, 1): 5})
        empty = _frame(["TS"], [(2020, 1)], {("TS", 2020, 1): 7})
        seq = {"AAA": full, "BBB": empty}
        monkeypatch.setattr(_m, "fetch_balance_sheet",
                            lambda tk, **k: seq[tk])
        out = tmp_path / "z.xlsx"
        assert _m.main(["--tickers", "AAA", "BBB", "--from", "2018",
                        "--to", "2018", "--out", str(out)]) == 0
        from openpyxl import load_workbook
        assert set(load_workbook(out).sheetnames[1:]) == {"AAA"}


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


class TestSourceSelection:
    """Ba nguồn, TẦM PHỦ khác nhau: VCI sớm nhất 2018-Q1 (đo 26/08) · KBS trả
    RỖNG (đo 26/08) · TCBS gọi HTTP thẳng, chưa đo sống. Script phải cho
    chọn, và `--probe` phải in ra nguồn nào đang dùng, chứ không để người đọc
    tự đoán."""

    def test_all_four_sources_are_offered(self):
        assert set(_m.SOURCES) == {"vci", "kbs", "tcbs", "cafef"}

    def test_cafef_is_present_because_it_is_the_only_2015_source(self):
        # Đo 26/08: vci sớm nhất 2018-Q1 · kbs rỗng · tcbs 404 · cafef có 2016.
        assert "cafef" in _m.SOURCES

    def test_kbs_goes_through_the_kbs_explorer(self):
        import inspect
        src = inspect.getsource(_m.fetch_balance_sheet)
        assert "vnstock.explorer.kbs.financial" in src
        assert "vnstock.explorer.vci.financial" in src

    def test_probe_names_the_source_it_used(self, monkeypatch, capsys):
        monkeypatch.setattr(_m, "fetch_balance_sheet",
                            lambda *a, **k: _frame(["TS"], [(2018, 1)],
                                                   {("TS", 2018, 1): 1}))
        _m.probe("VCB", 200, "vi", "kbs")
        assert "nguồn=kbs" in capsys.readouterr().out

    def test_probe_shouts_the_earliest_period(self, monkeypatch, capsys):
        """Câu hỏi sống còn với yêu cầu 2015-2016 là 'nguồn có từ bao giờ'."""
        monkeypatch.setattr(_m, "fetch_balance_sheet",
                            lambda *a, **k: _frame(["TS"], [(2018, 1), (2019, 2)],
                                                   {("TS", 2018, 1): 1}))
        _m.probe("VCB", 200, "vi", "vci")
        out = capsys.readouterr().out
        assert "KỲ SỚM NHẤT" in out and "2018-Q1" in out
