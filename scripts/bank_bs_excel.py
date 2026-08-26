#!/usr/bin/env python3
"""GHI EXCEL cho bảng cân đối — tách khỏi `export_bank_balance_sheets.py`
(26/08) để file đó khỏi vượt trần 800 dòng của repo.

Chỉ lo TRÌNH BÀY. Mọi quyết định về NỘI DUNG (chỉ tiêu nào, kỳ nào, ô nào
trống) đã chốt xong ở `bank_bs_shape`; ở đây không được đụng vào con số.

Ô TRỐNG ghi ra là ô TRỐNG — không bao giờ điền 0 thay cho "nguồn không có
số". Trong bảng cân đối đó là hai khẳng định khác hẳn nhau.
"""
from __future__ import annotations

from pathlib import Path

from scripts.bank_bs_shape import (find_row, is_heading, quarter_label,
                                   sheet_matrix)


# ─────────────────────────────────────────────────────────────────────────
# Ghi Excel
# ─────────────────────────────────────────────────────────────────────────
_FONT = "Arial"
_NUM_FMT = "#,##0;(#,##0);-"


def write_workbook(path: Path, per_bank: dict, items: list, quarters: list,
                   coverage: list, lang: str, source: str = "vci",
                   unit_note: "str | None" = None) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(name=_FONT, bold=True, size=10)
    body_font = Font(name=_FONT, size=10)
    head_fill = PatternFill("solid", fgColor="DDEBF7")

    # ── Sheet 1: TẦM PHỦ (đọc TRƯỚC khi tin bất kỳ sheet nào) ───────────
    cov = wb.active
    cov.title = "0_TẦM PHỦ"
    cov.append(["Mã", "Số quý CÓ", "Số quý XIN", "Quý đầu", "Quý cuối",
                "Số chỉ tiêu", "|Giá trị| lớn nhất"])
    for c in cov[1]:
        c.font, c.fill = head_font, head_fill
    for r in coverage:
        cov.append([r["ticker"], r["quarters_found"], r["quarters_asked"],
                    r["first"], r["last"], r["line_items"], r["max_abs"]])
    for row in cov.iter_rows(min_row=2):
        for c in row:
            c.font = body_font
        row[6].number_format = _NUM_FMT
    for i, w in enumerate((10, 12, 12, 12, 12, 14, 22), start=1):
        cov.column_dimensions[get_column_letter(i)].width = w
    cov.freeze_panes = "A2"

    note = cov.cell(row=len(coverage) + 3, column=1)
    note.value = (
        "GHI CHÚ — đọc trước khi dùng số:\n"
        "• Ô TRỐNG = nguồn KHÔNG có số cho ô đó. KHÁC hẳn số 0.\n"
        "• Mọi sheet ngân hàng dùng CHUNG một bộ dòng chỉ tiêu (hợp nhất từ "
        "tất cả các mã) và CHUNG một bộ cột quý, nên so ngang được.\n"
        f"• Nguồn: {source}. "
        + (f"Trang nguồn ghi 'Đơn vị: {unit_note}' — ĐÂY LÀ GHI CHÚ THAM "
           f"KHẢO, KHÔNG PHẢI KẾT LUẬN. " if unit_note else "Nguồn KHÔNG ghi đơn vị. ")
        + "Script KHÔNG quy đổi gì cả. Thang THẬT đọc ở cột '|Giá trị| lớn "
        "nhất' bên trái: ngân hàng lớn cỡ 1e15 là ĐỒNG nguyên, cỡ 1e12 là "
        "triệu đồng, cỡ 1e9 là tỷ đồng. (Đo 26/08: trang CafeF ghi 'tỷ đồng' "
        "mà ô số lại là đồng nguyên — nên đừng tin câu đó.)\n"
        "• 'Số quý CÓ' < 'Số quý XIN' nghĩa là nguồn thiếu kỳ, KHÔNG phải "
        "script bỏ sót.")
    note.font = Font(name=_FONT, size=9, italic=True)
    note.alignment = Alignment(wrap_text=True, vertical="top")
    cov.merge_cells(start_row=note.row, start_column=1,
                    end_row=note.row + 6, end_column=7)

    # ── Mỗi ngân hàng một sheet, BỐ CỤC Y HỆT NHAU ──────────────────────
    # Thứ tự dòng dựng MỘT LẦN từ `items` — đó chính là điều kiện "đồng nhất".
    # Dòng nào nhìn như TIÊU ĐỀ MỤC (toàn hoa, hoặc "TỔNG …") thì tô đậm để
    # bảng đọc ra hình dạng bảng cân đối; KHÔNG tự chèn tiêu đề của mình và
    # KHÔNG đổi tên chỉ tiêu — nguồn đã trả đúng thứ tự báo cáo, sắp lại theo
    # khung riêng là rước rủi ro xếp nhầm dòng.
    sec_font = Font(name=_FONT, bold=True, size=10)
    sec_fill = PatternFill("solid", fgColor="F2F2F2")
    chk_font = Font(name=_FONT, bold=True, size=10, italic=True)

    for ticker in sorted(per_bank):
        ws = wb.create_sheet(ticker[:31])
        ws.append([f"BẢNG CÂN ĐỐI KẾ TOÁN — {ticker} (theo quý)"])
        ws["A1"].font = Font(name=_FONT, bold=True, size=12)
        ws.append(["Chỉ tiêu"] + [quarter_label(*qq) for qq in quarters])
        for c in ws[2]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center")
        ws["A2"].alignment = Alignment(horizontal="left")

        by_item = dict(zip(items, sheet_matrix(items, quarters,
                                               per_bank[ticker])))
        row_of: dict = {}
        for label in items:
            ws.append([label] + by_item[label])
            row_of[label] = ws.max_row
            r = ws[ws.max_row]
            head = is_heading(label)
            r[0].font = sec_font if head else body_font
            r[0].alignment = Alignment(wrap_text=True, vertical="top")
            for c in r[1:]:
                c.font = sec_font if head else body_font
                c.number_format = _NUM_FMT
            if head:
                for c in r:
                    c.fill = sec_fill

        _append_balance_check(ws, items, row_of, quarters, chk_font)

        ws.column_dimensions["A"].width = 52
        for i in range(2, len(quarters) + 2):
            ws.column_dimensions[get_column_letter(i)].width = 18
        ws.freeze_panes = "B3"

    wb.save(path)


def _append_balance_check(ws, items, row_of, quarters, font):
    """Hàng KIỂM TRA CÂN ĐỐI — bằng CÔNG THỨC, không phải số Python tính sẵn.

    Bảng cân đối chỉ có đúng một bất biến: TỔNG TÀI SẢN = TỔNG NGUỒN VỐN.
    Viết bằng công thức để nó tự tính lại khi ai đó sửa số trong file.

    Không định vị được cả hai dòng ⇒ ghi một dòng NÓI RÕ là không kiểm được,
    chứ không im lặng bỏ qua.
    """
    from openpyxl.utils import get_column_letter

    ta = find_row(items, "tong tai san", "total assets")
    tn = find_row(items, "tong no phai tra va von chu so huu",
                  "tong nguon von", "total liabilities and owner s equity",
                  "total resources")
    ws.append([])
    if ta is None or tn is None:
        ws.append(["⚠ Không định vị được dòng TỔNG TÀI SẢN và/hoặc TỔNG NGUỒN "
                   "VỐN trong dữ liệu nguồn → KHÔNG kiểm được cân đối"])
        ws[ws.max_row][0].font = font
        return
    r_ta, r_tn = row_of[items[ta]], row_of[items[tn]]
    ws.append(["KIỂM TRA: Tổng tài sản − Tổng nguồn vốn (phải = 0)"])
    r = ws.max_row
    ws[r][0].font = font
    for i in range(len(quarters)):
        col = get_column_letter(i + 2)
        c = ws.cell(row=r, column=i + 2)
        c.value = f"=IFERROR({col}{r_ta}-{col}{r_tn},\"\")"
        c.font = font
        c.number_format = _NUM_FMT
