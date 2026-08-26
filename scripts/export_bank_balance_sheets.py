#!/usr/bin/env python3
"""Xuất BẢNG CÂN ĐỐI KẾ TOÁN theo QUÝ của các ngân hàng ra một file Excel.

Mỗi ngân hàng một sheet, **bố cục dòng GIỐNG HỆT nhau giữa mọi sheet**.

Chạy trên máy có mạng + `VNSTOCK_API_KEY` trong `.env`:

    python scripts/export_bank_balance_sheets.py --probe VCB     # soi TRƯỚC
    python scripts/export_bank_balance_sheets.py --from 2018 --to 2019
    python scripts/export_bank_balance_sheets.py --tickers VCB CTG BID

⚠️ **KỲ SỚM NHẤT NGUỒN CÓ LÀ 2018-Q1** (đo bằng `--probe VCB` ngày 26/08:
`item | item_en | item_id | 2018-Q1 | … | 2026-Q2`). Xin 2015-2016 thì nguồn
KHÔNG có — script sẽ nói ra và gợi khoảng dùng được, chứ không ghi file rỗng.

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

# ── DẠNG THẬT của frame VCI (đo bằng --probe VCB, 26/08) ────────────────
#   86 hàng × 37 cột
#   item | item_en | item_id | 2018-Q1 | 2018-Q2 | … | 2026-Q2
# Tức **HÀNG là chỉ tiêu, CỘT là kỳ** — ngược hẳn giả định ban đầu của tôi
# (tôi đã đoán hàng=kỳ, cột=chỉ tiêu theo kiểu `yearReport`/`lengthReport`).
# Đây chính là lý do `--probe` phải chạy trước: đoán sai dạng thì script ghi
# ra một file trông như thật.
#
# ⚠️ VÀ: kỳ SỚM NHẤT nguồn có là **2018-Q1**. 2015-2016 KHÔNG tồn tại ở
# nguồn này, không phải script bỏ sót.
_LABEL_COLS = ("item", "item_en", "item_id", "ticker", "symbol")




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


def detect_period_columns(columns) -> list:
    """[(tên cột, (năm, quý))] cho các cột kỳ dạng `2018-Q1`, theo thứ tự tăng.

    Nhận không ra cột kỳ nào ⇒ trả [] và chỗ gọi PHẢI dừng: đoán bừa dạng
    frame là ghi ra một file trông như thật (vết 26/08 — tôi đoán hàng=kỳ,
    thực tế hàng=chỉ tiêu).
    """
    import re
    pat = re.compile(r"^\s*(\d{4})\s*[-/ ]?\s*Q([1-4])\s*$", re.I)
    out = []
    for c in columns:
        m = pat.match(str(c))
        if m:
            out.append((c, (int(m.group(1)), int(m.group(2)))))
    return sorted(out, key=lambda t: t[1])


def label_column(columns, lang: str = "vi") -> "str | None":
    """Cột chứa TÊN chỉ tiêu. `item` = tiếng Việt, `item_en` = tiếng Anh."""
    lut = {str(c).strip().lower(): c for c in columns}
    order = ("item_en", "item") if lang == "en" else ("item", "item_en")
    return next((lut[k] for k in order if k in lut), None)


def tidy(df, lang: str = "vi") -> dict:
    """{(năm, quý): {chỉ tiêu: giá trị}} từ frame dạng hàng=chỉ tiêu.

    Giữ NGUYÊN thứ tự hàng của nguồn — đó đã là thứ tự bảng cân đối chuẩn
    (tài sản → nợ → vốn chủ). Tự sắp lại theo khung của mình là rước rủi ro
    xếp nhầm dòng, mà xếp nhầm một dòng thì cả bảng sai.
    """
    periods = detect_period_columns(df.columns)
    lbl = label_column(df.columns, lang)
    if not periods or lbl is None:
        return {}
    out: dict = {qq: {} for _, qq in periods}
    for _, row in df.iterrows():
        name = str(row[lbl]).strip()
        if not name or name.lower() == "nan":
            continue
        for col, qq in periods:
            out[qq][name] = row[col]
    return out


def source_item_order(df, lang: str = "vi") -> list:
    """Danh sách chỉ tiêu THEO ĐÚNG thứ tự nguồn trả về."""
    lbl = label_column(df.columns, lang)
    if lbl is None:
        return []
    seen, out = set(), []
    for v in df[lbl]:
        name = str(v).strip()
        if name and name.lower() != "nan" and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def unified_items(per_bank: dict, orders: "dict | None" = None) -> list:
    """Danh mục chỉ tiêu HỢP NHẤT — bộ xương dùng chung cho MỌI sheet.

    Ưu tiên thứ tự NGUỒN của từng mã (`orders`), vì đó đã là thứ tự bảng cân
    đối chuẩn. Mã nào có chỉ tiêu mà mã khác không có thì chỉ tiêu đó vẫn
    xuất hiện ở mọi sheet — ô của mã thiếu để TRỐNG.
    """
    seen, out = set(), []
    for tk in sorted(per_bank):
        src = (orders or {}).get(tk)
        if not src:
            src = []
            for period in sorted(per_bank[tk]):
                src.extend(per_bank[tk][period])
        for item in src:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


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


SOURCES = ("vci", "kbs")


def fetch_balance_sheet(ticker: str, limit: int = DEFAULT_LIMIT,
                        lang: str = "vi", source: str = "vci"):
    """Bảng cân đối theo quý, ĐỦ SÂU. Ném lỗi rõ ràng thay vì trả rỗng.

    Hai nguồn có sẵn trong `vnstock`, TẦM PHỦ KHÁC NHAU — đo bằng `--probe`,
    đừng tin nguồn nào "chắc là có":
    * `vci` — đo 26/08: sớm nhất **2018-Q1** (86 chỉ tiêu).
    * `kbs` — nguồn thứ hai, CHƯA ĐO. Có thể sâu hơn, có thể không.
    """
    from vnstock_auth import ensure_api_key
    ensure_api_key()

    if source == "kbs":
        from vnstock.explorer.kbs.financial import Finance as KFinance
        return KFinance(ticker, period="quarter", show_log=False)\
            .balance_sheet(period="quarter", display_mode=None, show_log=False)

    from vnstock.explorer.vci.financial import Finance
    # `_get_financial_report` là chỗ DUY NHẤT nhận `limit` — xem bẫy ① đầu file
    return Finance(ticker, period="quarter", show_log=False)._get_financial_report(
        "balance_sheet", period="quarter", lang=lang,
        dropna=False, limit=limit, show_log=False)


def probe(ticker: str, limit: int, lang: str, source: str = "vci") -> int:
    """Soi MỘT mã: hình dạng, cột kỳ, TẦM PHỦ THẬT. Chạy cái này TRƯỚC."""
    df = fetch_balance_sheet(ticker, limit=limit, lang=lang, source=source)
    print(f"[probe] nguồn={source}")
    print(f"[probe] {ticker}: {df.shape[0]} hàng × {df.shape[1]} cột")
    if df.empty:
        print("[probe] ❌ nguồn trả về RỖNG")
        return 2
    periods = detect_period_columns(df.columns)
    lbl = label_column(df.columns, lang)
    if not periods or lbl is None:
        print("[probe] ❌ KHÔNG nhận ra cột kỳ / cột tên chỉ tiêu. Dán danh "
              "sách cột này cho Claude:")
        print("  " + " | ".join(str(c) for c in list(df.columns)[:45]))
        return 2
    items = source_item_order(df, lang)
    print(f"[probe] cột tên chỉ tiêu: '{lbl}' · {len(items)} chỉ tiêu")
    print(f"[probe] TẦM PHỦ: {quarter_label(*periods[0][1])} → "
          f"{quarter_label(*periods[-1][1])} ({len(periods)} quý)")
    print(f"[probe] ⚠️ KỲ SỚM NHẤT nguồn có: "
          f"{quarter_label(*periods[0][1])} — xin sớm hơn là KHÔNG có data")
    print("[probe] 8 chỉ tiêu đầu:")
    for it in items[:8]:
        print(f"          {it}")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Xuất bảng cân đối kế toán theo quý của các ngân hàng")
    ap.add_argument("--from", dest="y_from", type=int, default=2018,
                    help="Nguồn VCI chỉ có từ 2018-Q1")
    ap.add_argument("--to", dest="y_to", type=int, default=2019)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="Mặc định: toàn bộ ngân hàng trong vnstock_brief_canon")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="Số kỳ xin về từ nguồn (mặc định 200 — API mặc định "
                         "CHỈ 4, xem ghi chú đầu file)")
    ap.add_argument("--lang", default="vi", choices=("vi", "en"))
    ap.add_argument("--source", default="vci", choices=SOURCES,
                    help="vci = đã đo, sớm nhất 2018-Q1 · kbs = nguồn thứ hai, CHƯA đo tầm phủ")
    ap.add_argument("--out", default=None)
    ap.add_argument("--probe", metavar="MÃ", default=None,
                    help="Soi một mã rồi thoát — CHẠY CÁI NÀY TRƯỚC")
    args = ap.parse_args(argv)

    if args.probe:
        return probe(args.probe.upper(), args.limit, args.lang, args.source)

    quarters = quarters_between(args.y_from, args.y_to)
    tickers = [t.upper() for t in (args.tickers or bank_tickers())]
    out = Path(args.out or REPO /
               f"bang_can_doi_ngan_hang_{args.y_from}_{args.y_to}.xlsx")

    per_bank, coverage, failed = {}, [], []
    orders, earliest = {}, []
    for i, tk in enumerate(tickers, 1):
        print(f"[{i:2d}/{len(tickers)}] {tk} …", end=" ", flush=True)
        try:
            df = fetch_balance_sheet(tk, limit=args.limit, lang=args.lang,
                                     source=args.source)
        except Exception as exc:
            print(f"LỖI: {type(exc).__name__}: {exc}")
            failed.append((tk, f"{type(exc).__name__}: {exc}"))
            continue
        if df.empty:
            print("rỗng")
            failed.append((tk, "nguồn trả về rỗng"))
            continue
        avail = detect_period_columns(df.columns)
        if not avail or label_column(df.columns, args.lang) is None:
            print("KHÔNG nhận ra cột kỳ / cột tên chỉ tiêu")
            failed.append((tk, "không nhận ra cột kỳ / tên chỉ tiêu"))
            continue
        earliest.append(avail[0][1])
        data = tidy(df, args.lang)
        kept = {qq: v for qq, v in data.items() if qq in set(quarters)}
        per_bank[tk] = kept
        orders[tk] = source_item_order(df, args.lang)
        coverage.append(coverage_row(tk, quarters, kept))
        print(f"{len(kept)}/{len(quarters)} quý"
              + ("" if kept else
                 f"  (nguồn chỉ có từ {quarter_label(*avail[0][1])})"))

    covered = [tk for tk, d in per_bank.items() if d]
    if not covered:
        print("\n❌ KHÔNG mã nào có dữ liệu trong khoảng "
              f"{args.y_from}-{args.y_to} — KHÔNG ghi file (file rỗng trông "
              "như thật là thứ nguy hiểm nhất ở đây).")
        if earliest:
            e = min(earliest)
            print(f"\n   👉 Kỳ SỚM NHẤT nguồn có là {quarter_label(*e)}. "
                  f"Xin sớm hơn thì nguồn KHÔNG có, không phải script bỏ sót.")
            print(f"   👉 Thử lại: --from {e[0]} --to {e[0] + 1}")
        for tk, why in failed[:5]:
            print(f"   {tk}: {why}")
        return 2

    per_bank = {tk: d for tk, d in per_bank.items() if d}
    items = unified_items(per_bank, orders)
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


# ─────────────────────────────────────────────────────────────────────────
# Sắp chỉ tiêu theo KHUNG bảng cân đối — hàm thuần
# ─────────────────────────────────────────────────────────────────────────
def _strip_accents(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", str(text or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


# Số thứ tự đầu dòng: "1." "1)" "IV." "a)" — PHẢI có dấu ngăn phía sau.
# Không có ràng buộc đó thì bộ lọc ăn luôn chữ cái đầu của chỉ tiêu thật:
# "Cho vay khách hàng" → "ho vay khach hang" (c là chữ số La Mã), "Vốn điều
# lệ" → "on dieu le". Bắt được lúc chạy thử tay 26/08.
_ORDINAL_RE = None


def _key(label: str) -> str:
    """Chuẩn hoá nhãn để so khớp: bỏ dấu, bỏ số thứ tự đầu dòng, bỏ dấu câu."""
    import re
    global _ORDINAL_RE
    if _ORDINAL_RE is None:
        _ORDINAL_RE = re.compile(
            r"^\s*(?:\d+|[IVXLCDM]+|[a-zA-Z])\s*[\.\)\-–]\s*")
    s = _strip_accents(label)
    while True:                       # "I. 1. Tiền mặt" — bóc nhiều tầng
        stripped = _ORDINAL_RE.sub("", s)
        if stripped == s:
            break
        s = stripped
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def is_heading(label: str) -> bool:
    """Dòng này là TIÊU ĐỀ MỤC / dòng TỔNG? (để tô đậm, thuần trình bày)

    Chỉ nhìn HÌNH DẠNG nhãn, không suy diễn ý nghĩa: viết hoa toàn bộ, hoặc
    bắt đầu bằng "TỔNG"/"TOTAL". Nhận nhầm chỉ làm đậm nhầm một dòng — không
    đụng tới con số.
    """
    t = str(label or "").strip()
    if not t:
        return False
    k = _key(t)
    if k.startswith(("tong ", "total ")) or k in ("tong tai san", "tong nguon von"):
        return True
    letters = [c for c in _strip_accents(t) if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def find_row(items: list, *keys) -> "int | None":
    """Vị trí (0-based) của chỉ tiêu khớp một trong `keys`. None nếu không có."""
    want = {_key(k) for k in keys}
    for i, it in enumerate(items):
        if _key(it) in want:
            return i
    return None
