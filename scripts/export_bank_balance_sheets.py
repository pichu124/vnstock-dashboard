#!/usr/bin/env python3
"""Xuất BẢNG CÂN ĐỐI KẾ TOÁN theo QUÝ của các ngân hàng ra một file Excel.

Mỗi ngân hàng một sheet, **bố cục dòng GIỐNG HỆT nhau giữa mọi sheet**.

Chạy trên máy có mạng + `VNSTOCK_API_KEY` trong `.env`:

    python scripts/export_bank_balance_sheets.py --from 2015 --to 2016
    python scripts/export_bank_balance_sheets.py --tickers VCB CTG BID
    python scripts/export_bank_balance_sheets.py --probe VCB     # soi trước 1 mã

════════════════════════════════════════════════════════════════════════════
HAI CÁI BẪY ĐÃ ĐỌC RA TỪ MÃ NGUỒN `vnstock` — nếu không né thì file ra SAI
mà KHÔNG báo lỗi:

1. **`limit` mặc định = 4 kỳ.**
   `vnstock.explorer.vci.financial.Finance._get_financial_report` có
   `effective_limit = limit if limit is not None else 4`, mà phương thức công
   khai `balance_sheet(period, lang, dropna, show_log)` **không hề nhận
   `limit`**. Gọi đường thông thường ⇒ chỉ có 4 quý gần nhất ⇒ 2015-2016 rỗng
   trơn, file vẫn ghi ra bình thường. Script này gọi thẳng
   `_get_financial_report(..., limit=N)` và kiểm lại tầm phủ.

2. **`dropna=True` (mặc định) BỎ các dòng toàn số 0.**
   Cùng chỗ đó: `df.loc[:, (df != 0).any(axis=0)]`. Frame là kỳ×chỉ-tiêu, nên
   nó bỏ CHỈ TIÊU — và mỗi ngân hàng bỏ một bộ khác nhau. Đó đúng là thứ phá
   yêu cầu "format đồng nhất giữa các sheet". Luôn dùng `dropna=False`, rồi
   tự hợp nhất danh mục chỉ tiêu.
════════════════════════════════════════════════════════════════════════════

Ô TRỐNG ≠ SỐ 0. Trong bảng cân đối, "không có số" và "bằng không" là hai
chuyện khác hẳn — script để trống ô thiếu, không điền 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Số kỳ xin về. 2015-Q1 cách hiện tại ~46 quý; xin dư cho chắc.
DEFAULT_LIMIT = 200

# Tên cột kỳ báo cáo có thể gặp — nguồn đổi nhãn theo `lang`/phiên bản.
_YEAR_KEYS = ("yearreport", "năm", "nam", "year", "reportyear")
_QUARTER_KEYS = ("lengthreport", "quý", "quy", "quarter", "reportquarter",
                 "kỳ", "ky")
# Cột không phải chỉ tiêu tài chính
_META_KEYS = set(_YEAR_KEYS) | set(_QUARTER_KEYS) | {
    "report_period", "ticker", "symbol", "mã", "ma", "cp"}


# ─────────────────────────────────────────────────────────────────────────
# Hàm THUẦN — test được không cần mạng
# ─────────────────────────────────────────────────────────────────────────
def quarters_between(year_from: int, year_to: int) -> list:
    """[(2015,1), (2015,2), … (2016,4)] — thứ tự cột, cố định mọi sheet."""
    return [(y, q) for y in range(year_from, year_to + 1) for q in (1, 2, 3, 4)]


def quarter_label(year: int, quarter: int) -> str:
    return f"{year}-Q{quarter}"


def _norm(name) -> str:
    return str(name).strip().lower()


def detect_period_columns(columns) -> "tuple[str, str] | None":
    """(cột NĂM, cột QUÝ) trong frame nguồn — None khi không nhận ra.

    Không đoán bừa: nhận không ra thì chỗ gọi phải dừng và in danh sách cột
    ra cho người xem, chứ không được ghi một file trông như thật.
    """
    cols = list(columns)
    lut = {_norm(c): c for c in cols}
    ycol = next((lut[k] for k in _YEAR_KEYS if k in lut), None)
    qcol = next((lut[k] for k in _QUARTER_KEYS if k in lut), None)
    if ycol is None or qcol is None:
        return None
    return (ycol, qcol)


def line_items(columns, year_col, quarter_col) -> list:
    """Các cột CHỈ TIÊU (bỏ cột kỳ/metadata), giữ nguyên thứ tự nguồn."""
    skip = {_norm(year_col), _norm(quarter_col)} | _META_KEYS
    return [c for c in columns if _norm(c) not in skip]


def tidy(df, year_col, quarter_col) -> dict:
    """{(năm, quý): {chỉ tiêu: giá trị}} — bỏ hàng không đọc được kỳ."""
    out: dict = {}
    items = line_items(df.columns, year_col, quarter_col)
    for _, row in df.iterrows():
        try:
            y, q = int(row[year_col]), int(row[quarter_col])
        except (TypeError, ValueError):
            continue
        if not 1 <= q <= 4:
            continue
        out[(y, q)] = {c: row[c] for c in items}
    return out


def unified_items(per_bank: dict) -> list:
    """Danh mục chỉ tiêu HỢP NHẤT — bộ xương dùng chung cho MỌI sheet.

    Giữ thứ tự xuất hiện đầu tiên (bảng cân đối có trật tự có nghĩa: tài sản
    → nợ → vốn chủ; sắp xếp abc là phá cấu trúc đó). Ngân hàng nào thiếu chỉ
    tiêu nào thì ô đó TRỐNG, không phải 0.
    """
    seen: list = []
    known = set()
    for data in per_bank.values():
        for period in sorted(data):
            for item in data[period]:
                if item not in known:
                    known.add(item)
                    seen.append(item)
    return seen


def sheet_matrix(items: list, quarters: list, data: dict) -> list:
    """Ma trận [chỉ tiêu][quý] — ô thiếu là None (ghi ra Excel là ô TRỐNG)."""
    rows = []
    for item in items:
        row = []
        for qq in quarters:
            v = (data.get(qq) or {}).get(item)
            row.append(None if _is_blank(v) else v)
        rows.append(row)
    return rows


def _is_blank(v) -> bool:
    if v is None:
        return True
    try:
        return v != v          # NaN
    except Exception:
        return False


def coverage_row(ticker: str, quarters: list, data: dict) -> dict:
    """Một dòng báo cáo TẦM PHỦ — để chỗ thiếu hiện ra, không im lặng."""
    have = [qq for qq in quarters if data.get(qq)]
    nums = [v for qq in have for v in (data.get(qq) or {}).values()
            if isinstance(v, (int, float)) and not _is_blank(v)]
    return {
        "ticker": ticker,
        "quarters_found": len(have),
        "quarters_asked": len(quarters),
        "first": quarter_label(*have[0]) if have else "",
        "last": quarter_label(*have[-1]) if have else "",
        "line_items": len(data.get(have[0], {})) if have else 0,
        "max_abs": max((abs(v) for v in nums), default=0),
    }


# ─────────────────────────────────────────────────────────────────────────
# Đường có MẠNG
# ─────────────────────────────────────────────────────────────────────────
def bank_tickers() -> list:
    """Danh sách ngân hàng — lấy từ `vnstock_brief_canon`, một nguồn duy nhất."""
    import re
    src = (REPO / "vnstock_brief_canon.py").read_text(encoding="utf-8")
    blk = src.split("# Ngân hàng")[1].split("# Chứng khoán")[0]
    return re.findall(r'"([A-Z]{3,4})"', blk)


def fetch_balance_sheet(ticker: str, limit: int = DEFAULT_LIMIT,
                        lang: str = "vi"):
    """Bảng cân đối theo quý, ĐỦ SÂU. Ném lỗi rõ ràng thay vì trả rỗng.

    Đi qua `_get_financial_report` vì đó là chỗ DUY NHẤT nhận `limit` —
    xem hai cái bẫy ở đầu file.
    """
    from vnstock_auth import ensure_api_key
    ensure_api_key()
    from vnstock.explorer.vci.financial import Finance

    fin = Finance(ticker, period="quarter", show_log=False)
    return fin._get_financial_report(
        "balance_sheet", period="quarter", lang=lang,
        dropna=False, limit=limit, show_log=False)


def probe(ticker: str, limit: int, lang: str) -> int:
    """Soi MỘT mã rồi in ra: hình dạng, cột kỳ, tầm phủ. Chạy cái này TRƯỚC."""
    df = fetch_balance_sheet(ticker, limit=limit, lang=lang)
    print(f"[probe] {ticker}: {df.shape[0]} hàng × {df.shape[1]} cột")
    if df.empty:
        print("[probe] ❌ nguồn trả về RỖNG")
        return 2
    per = detect_period_columns(df.columns)
    if per is None:
        print("[probe] ❌ KHÔNG nhận ra cột kỳ báo cáo. Dán danh sách cột này "
              "cho Claude để bổ sung:")
        print("  " + " | ".join(str(c) for c in list(df.columns)[:40]))
        return 2
    ycol, qcol = per
    data = tidy(df, ycol, qcol)
    ks = sorted(data)
    print(f"[probe] cột kỳ: năm='{ycol}' quý='{qcol}'")
    print(f"[probe] chỉ tiêu: {len(line_items(df.columns, ycol, qcol))}")
    print(f"[probe] tầm phủ: {quarter_label(*ks[0])} → {quarter_label(*ks[-1])}"
          f" ({len(ks)} quý)")
    print("[probe] 8 chỉ tiêu đầu: "
          + " | ".join(str(c) for c in line_items(df.columns, ycol, qcol)[:8]))
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Ghi Excel
# ─────────────────────────────────────────────────────────────────────────
_FONT = "Arial"
_NUM_FMT = "#,##0;(#,##0);-"


def write_workbook(path: Path, per_bank: dict, items: list, quarters: list,
                   coverage: list, lang: str) -> None:
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
        "• Đơn vị: theo nguồn VCI, KHÔNG quy đổi. Xem cột "
        "'|Giá trị| lớn nhất' để tự nhận ra thang (ngân hàng lớn cỡ 1e15 là "
        "VND; cỡ 1e6 là triệu VND).\n"
        "• 'Số quý CÓ' < 'Số quý XIN' nghĩa là nguồn thiếu kỳ, KHÔNG phải "
        "script bỏ sót.")
    note.font = Font(name=_FONT, size=9, italic=True)
    note.alignment = Alignment(wrap_text=True, vertical="top")
    cov.merge_cells(start_row=note.row, start_column=1,
                    end_row=note.row + 6, end_column=7)

    # ── Mỗi ngân hàng một sheet, BỐ CỤC Y HỆT NHAU ──────────────────────
    for ticker in sorted(per_bank):
        ws = wb.create_sheet(ticker[:31])
        ws.append([f"BẢNG CÂN ĐỐI KẾ TOÁN — {ticker} (theo quý)"])
        ws["A1"].font = Font(name=_FONT, bold=True, size=12)
        ws.append(["Chỉ tiêu"] + [quarter_label(*qq) for qq in quarters])
        for c in ws[2]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center")
        ws["A2"].alignment = Alignment(horizontal="left")

        for item, row in zip(items, sheet_matrix(items, quarters,
                                                 per_bank[ticker])):
            ws.append([item] + row)

        for r in ws.iter_rows(min_row=3, min_col=1, max_col=len(quarters) + 1):
            r[0].font = body_font
            r[0].alignment = Alignment(wrap_text=True, vertical="top")
            for c in r[1:]:
                c.font = body_font
                c.number_format = _NUM_FMT
        ws.column_dimensions["A"].width = 52
        for i in range(2, len(quarters) + 2):
            ws.column_dimensions[get_column_letter(i)].width = 18
        ws.freeze_panes = "B3"

    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Xuất bảng cân đối kế toán theo quý của các ngân hàng")
    ap.add_argument("--from", dest="y_from", type=int, default=2015)
    ap.add_argument("--to", dest="y_to", type=int, default=2016)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="Mặc định: toàn bộ ngân hàng trong vnstock_brief_canon")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="Số kỳ xin về từ nguồn (mặc định 200 — API mặc định "
                         "CHỈ 4, xem ghi chú đầu file)")
    ap.add_argument("--lang", default="vi", choices=("vi", "en"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--probe", metavar="MÃ", default=None,
                    help="Soi một mã rồi thoát — CHẠY CÁI NÀY TRƯỚC")
    args = ap.parse_args(argv)

    if args.probe:
        return probe(args.probe.upper(), args.limit, args.lang)

    quarters = quarters_between(args.y_from, args.y_to)
    tickers = [t.upper() for t in (args.tickers or bank_tickers())]
    out = Path(args.out or REPO /
               f"bang_can_doi_ngan_hang_{args.y_from}_{args.y_to}.xlsx")

    per_bank, coverage, failed = {}, [], []
    for i, tk in enumerate(tickers, 1):
        print(f"[{i:2d}/{len(tickers)}] {tk} …", end=" ", flush=True)
        try:
            df = fetch_balance_sheet(tk, limit=args.limit, lang=args.lang)
        except Exception as exc:
            print(f"LỖI: {type(exc).__name__}: {exc}")
            failed.append((tk, f"{type(exc).__name__}: {exc}"))
            continue
        if df.empty:
            print("rỗng")
            failed.append((tk, "nguồn trả về rỗng"))
            continue
        per = detect_period_columns(df.columns)
        if per is None:
            print("KHÔNG nhận ra cột kỳ")
            failed.append((tk, "không nhận ra cột kỳ báo cáo"))
            continue
        data = tidy(df, *per)
        kept = {qq: v for qq, v in data.items() if qq in set(quarters)}
        per_bank[tk] = kept
        coverage.append(coverage_row(tk, quarters, kept))
        print(f"{len(kept)}/{len(quarters)} quý")

    if not per_bank:
        print("\n❌ KHÔNG mã nào có dữ liệu — KHÔNG ghi file (file rỗng trông "
              "như thật là thứ nguy hiểm nhất ở đây).")
        for tk, why in failed:
            print(f"   {tk}: {why}")
        return 2

    items = unified_items(per_bank)
    write_workbook(out, per_bank, items, quarters, coverage, args.lang)
    print(f"\n✅ {out}")
    print(f"   {len(per_bank)} sheet ngân hàng · {len(items)} dòng chỉ tiêu "
          f"(GIỐNG NHAU mọi sheet) · {len(quarters)} cột quý")
    empty = [r["ticker"] for r in coverage if r["quarters_found"] == 0]
    if empty:
        print(f"   ⚠️ {len(empty)} mã KHÔNG có quý nào trong khoảng: "
              f"{', '.join(empty)}")
    if failed:
        print(f"   ⚠️ {len(failed)} mã hỏng: "
              + ", ".join(f"{t} ({w[:40]})" for t, w in failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
