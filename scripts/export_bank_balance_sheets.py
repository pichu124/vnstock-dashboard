#!/usr/bin/env python3
"""Xuất BẢNG CÂN ĐỐI KẾ TOÁN theo QUÝ của các ngân hàng ra một file Excel.

Mỗi ngân hàng một sheet, **bố cục dòng GIỐNG HỆT nhau giữa mọi sheet**.

Chạy trên máy có mạng + `VNSTOCK_API_KEY` trong `.env`:

    python scripts/export_bank_balance_sheets.py --probe-all VCB  # soi TRƯỚC
    python scripts/export_bank_balance_sheets.py --crosscheck VCB # rồi soi ĐƠN VỊ
    python scripts/export_bank_balance_sheets.py --from 2018 --to 2019
    python scripts/export_bank_balance_sheets.py --tickers VCB CTG BID

⚠️ TẦM PHỦ THEO NGUỒN — đo 26/08 trên máy user, `--probe-all VCB`:
* `vci`   — ✅ 2018-Q1 → 2026-Q2, 83 chỉ tiêu. **Không có 2015-2016.**
* `kbs`   — ❌ chữ ký `balance_sheet` khác nhau giữa các bản `vnstock`; gọi
  theo chữ ký thật rồi thì vẫn trả về RỖNG.
* `tcbs`  — ❌ **404**, endpoint `apipubaws` đã chết. Giữ lại trong danh sách
  để `--probe-all` còn NÓI RA điều đó, thay vì im lặng bỏ qua.
* `cafef` — ✅ **có 2015-2016**, đơn vị trang ghi **`tỷ đồng`**. Mỗi trang =
  4 quý của MỘT năm, nên 2015-2016 là hai lượt tải mỗi mã.

Xin khoảng nguồn không có ⇒ script NÓI RA và gợi khoảng dùng được, chứ không
ghi ra một file rỗng trông như thật.

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

# ─────────────────────────────────────────────────────────────────────────
# Hàm THUẦN đã tách sang `bank_bs_shape` (trần 800 dòng/file). Nhập lại
# NGUYÊN TÊN ở đây để mọi chỗ gọi cũ — và lưới test — không phải đổi.
# ─────────────────────────────────────────────────────────────────────────
from scripts.bank_bs_shape import (  # noqa: E402
    _is_blank, _key, _LABEL_COLS, _norm, _strip_accents, coverage_row,
    detect_period_columns, find_row, is_heading, label_column,
    quarter_label, quarters_between, sheet_matrix, source_item_order,
    tidy, unified_items,
)

# ─────────────────────────────────────────────────────────────────────────
# Đường có MẠNG
# ─────────────────────────────────────────────────────────────────────────
def bank_tickers() -> list:
    """Danh sách ngân hàng — lấy từ `vnstock_brief_canon`, một nguồn duy nhất."""
    import re
    src = (REPO / "vnstock_brief_canon.py").read_text(encoding="utf-8")
    blk = src.split("# Ngân hàng")[1].split("# Chứng khoán")[0]
    return re.findall(r'"([A-Z]{3,4})"', blk)


SOURCES = ("vci", "kbs", "tcbs", "cafef")

# Năm mặc định cho nguồn CafeF khi chỗ gọi không nói rõ (mỗi trang = 1 năm).
CAFEF_DEFAULT_YEARS = (2015, 2016)

# Năm dùng để ĐỐI CHIẾU hai nguồn. Phải là năm CẢ HAI cùng có — VCI chỉ có từ
# 2018-Q1, nên đối chiếu ở 2015-2016 là đối chiếu với một bên rỗng.
CROSSCHECK_YEARS = (2018, 2019)


def _call_with_supported_kwargs(func, **kwargs):
    """Gọi `func` với ĐÚNG những kwarg chữ ký nó nhận.

    Vết 26/08: `vnstock` 4.0.4 trên máy user KHÔNG có `display_mode` trong
    `kbs…balance_sheet`, bản trong container thì CÓ. Truyền cứng ⇒ `TypeError`
    trên đúng máy duy nhất chạy được mạng. Đọc chữ ký rồi hãy gọi.
    """
    import inspect
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return func()
    ok = {k: v for k, v in kwargs.items() if k in params}
    return func(**ok)


def fetch_balance_sheet(ticker: str, limit: int = DEFAULT_LIMIT,
                        lang: str = "vi", source: str = "vci",
                        years=None):
    """Bảng cân đối theo quý, ĐỦ SÂU. Ném lỗi rõ ràng thay vì trả rỗng.

    Bốn nguồn, đo 26/08 trên máy user bằng `--probe-all VCB`:
    * `vci`   — ✅ sớm nhất **2018-Q1**, 83 chỉ tiêu. Trong `vnstock`.
    * `kbs`   — ❌ `TypeError` vì chữ ký khác giữa các bản `vnstock`; gọi
      theo chữ ký thật rồi vẫn **trả về RỖNG**.
    * `tcbs`  — ❌ **404**, endpoint `apipubaws` đã chết. Giữ lại để
      `--probe-all` còn nói ra điều đó thay vì im lặng bỏ qua.
    * `cafef` — ✅ **có 2015-2016**. Mỗi trang = 4 quý của MỘT năm, nên
      `years` quyết định tải mấy trang.
    """
    if source == "cafef":
        from scripts.bank_bs_sources import fetch_cafef_years
        return fetch_cafef_years(ticker, years or CAFEF_DEFAULT_YEARS, lang)

    if source == "tcbs":
        from scripts.bank_bs_sources import fetch_tcbs, tcbs_to_frame
        payload, _ = fetch_tcbs(ticker)
        return tcbs_to_frame(payload, lang)

    from vnstock_auth import ensure_api_key
    ensure_api_key()

    if source == "kbs":
        from vnstock.explorer.kbs.financial import Finance as KFinance
        fin = KFinance(ticker, period="quarter", show_log=False)
        return _call_with_supported_kwargs(
            fin.balance_sheet, period="quarter", lang=lang, show_log=False)

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


def source_coverage(ticker: str, limit: int, lang: str, source: str,
                    years=None) -> dict:
    """Đo MỘT nguồn: đọc được không · kỳ sớm nhất · bao nhiêu chỉ tiêu.

    Không ném: hỏng thì ghi lý do vào `error` để bảng so sánh vẫn in đủ dòng.
    """
    row = {"source": source, "ok": False, "rows": 0, "cols": 0,
           "first": None, "last": None, "n_periods": 0, "n_items": 0,
           "error": None}
    try:
        df = fetch_balance_sheet(ticker, limit=limit, lang=lang, source=source,
                                 years=years)
    except Exception as exc:                      # noqa: BLE001 — probe báo cáo
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row["rows"], row["cols"] = int(df.shape[0]), int(df.shape[1])
    if df.empty:
        row["error"] = "nguồn trả về RỖNG"
        return row
    periods = detect_period_columns(df.columns)
    if not periods or label_column(df.columns, lang) is None:
        row["error"] = "không nhận ra cột kỳ / cột tên chỉ tiêu"
        return row
    row.update(ok=True, first=periods[0][1], last=periods[-1][1],
               n_periods=len(periods), n_items=len(source_item_order(df, lang)))
    return row


def reaches(row: dict, year: int, quarter: int = 1) -> bool:
    """Nguồn có với tới kỳ này không? Chưa đọc được ⇒ False, không đoán."""
    return bool(row.get("ok")) and row["first"] <= (year, quarter)


def probe_all(ticker: str, limit: int, lang: str, want_year: int = 2015) -> int:
    """So MỌI nguồn trên cùng một mã — một lệnh, một câu trả lời dứt điểm."""
    print(f"[probe-all] {ticker} · xin tới {want_year}-Q1\n")
    print(f"{'NGUỒN':<8} {'ĐỌC ĐƯỢC':<9} {'SỚM NHẤT':<10} {'MỚI NHẤT':<10} "
          f"{'SỐ QUÝ':>7} {'CHỈ TIÊU':>9}  GHI CHÚ")
    years = (want_year, want_year + 1)
    rows = []
    for src in SOURCES:
        r = source_coverage(ticker, limit, lang, src, years=years)
        rows.append(r)
        first = quarter_label(*r["first"]) if r["first"] else "—"
        last = quarter_label(*r["last"]) if r["last"] else "—"
        mark = "✅" if r["ok"] else "❌"
        note = "" if r["ok"] else (r["error"] or "")[:60]
        print(f"{src:<8} {mark:<8} {first:<10} {last:<10} "
              f"{r['n_periods']:>7} {r['n_items']:>9}  {note}")

    winners = [r["source"] for r in rows if reaches(r, want_year)]
    print()
    if winners:
        print(f"👉 Nguồn với tới {want_year}-Q1: {', '.join(winners)}")
        print(f"   Chạy: python scripts/export_bank_balance_sheets.py "
              f"--from {want_year} --to {want_year + 1} --source {winners[0]}")
        if set(winners) - {"vci"}:
            print(f"   TRƯỚC ĐÓ: --crosscheck {ticker} --with {winners[0]} — "
                  f"đối chiếu ĐƠN VỊ với VCI ở quý trùng nhau. Chưa đo tỉ số "
                  f"thì đừng tin số.")
        return 0
    ok = [r for r in rows if r["ok"]]
    if ok:
        e = min(r["first"] for r in ok)
        print(f"❌ KHÔNG nguồn nào với tới {want_year}. Sớm nhất trong tay: "
              f"{quarter_label(*e)}.")
    else:
        print("❌ KHÔNG nguồn nào đọc được — xem cột GHI CHÚ.")
    cf = next((r for r in rows if r["source"] == "cafef"), None)
    if cf and not cf["ok"]:
        # Phân biệt HAI kiểu hỏng — hai cách chữa khác nhau, và nói nhầm là
        # đẩy người đọc đi sai đường.
        fetch_broke = "CafefFetchError" in (cf["error"] or "")
        print("\n   CafeF hỏng ở bước " +
              ("TẢI TRANG (mạng/URL), chưa tới bước bóc bảng."
               if fetch_broke else
               "BÓC BẢNG — trang tải được nhưng không nhận ra bảng."))
        print(f"   python scripts/export_bank_balance_sheets.py "
              f"--dump-cafef {ticker} --dump-year {want_year + 1}")
        print("   rồi dán phần tóm tắt cấu trúc ra — đừng đoán tiếp.")
    return 2


def dump_cafef(ticker: str, year: int, quarter: int = 4,
               out_dir: "Path | None" = None) -> int:
    """In CHẨN ĐOÁN trang CafeF + lưu HTML thô, để sửa bộ bóc mà không đoán.

    Bộ bóc được viết khi chưa ai nhìn trang thật (máy soạn code bị chặn
    egress). Trật thì cái cần là DỮ KIỆN về trang thật — nó hỏng kiểu gì —
    chứ không phải một lần đoán nữa. Thử CẢ HAI đường URL, vì hai đường có
    thể trả hai trang khác nhau.
    """
    from scripts.bank_bs_sources import (diagnose_cafef, fetch_cafef,
                                         header_periods, header_row_index,
                                         label_col_index, nonempty_rows,
                                         parse_tables, pick_balance_table,
                                         quarter_contexts, verdict_line)

    out_dir = Path(out_dir or REPO / "_cafef_dump")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[dump-cafef] {ticker} {year}-Q{quarter}\n")

    best = None
    for legacy in (False, True):
        tag = "legacy" if legacy else "mới"
        status, text, url = fetch_cafef(ticker, year, quarter, legacy=legacy)
        if status is None:
            print(f"── đường {tag}: ❌ {text}")
            continue
        path = out_dir / f"{ticker}_{year}Q{quarter}_{tag}.html"
        path.write_text(text, encoding="utf-8", errors="replace")
        d = diagnose_cafef(text)
        raw = d["raw"]
        print(f"── đường {tag}: HTTP {status} · {len(text):,} ký tự")
        print(f"   URL cuối : {url}")
        print(f"   đã lưu   : {path}")
        print(f"   thẻ thô  : <table>={raw['table']} <tr>={raw['tr']} "
              f"<td>={raw['td']} <script>={raw['script']}")
        print(f"   bộ bóc   : {d['tables_parsed']} bảng · bảng lớn nhất "
              f"{d['biggest_table_rows']} hàng · nhận ra bảng cân đối: "
              f"{'CÓ' if d['balance_table_found'] else 'KHÔNG'}")
        print(f"   kỳ thấy  : "
              + (", ".join(quarter_label(*q) for q in d["quarters_seen"]) or "—"))
        print(f"   đơn vị   : {d['unit_note'] or '— KHÔNG thấy'}")
        print(f"   ⇒ {verdict_line(d)}")
        # Ô nào CÓ CHỨA một năm 20xx? Đây là chẩn đoán dứt điểm cho ca "không
        # thấy kỳ nào": có ô kiểu "Quý 4 2016" ⇒ lỗi regex của tôi; không ô
        # nào chứa năm ⇒ tiêu đề nằm chỗ khác hẳn.
        print("   ô có chứa năm 20xx: "
              + (" · ".join(f"'{c}'" for c in d["year_cells"]) or "— KHÔNG Ô NÀO"))
        if d["data_urls"]:
            print("   URL nghi là đường dữ liệu:")
            for u in d["data_urls"]:
                print(f"      {u[:120]}")
        print()
        if best is None or d["balance_table_found"]:
            best = (text, d, tag)

    if best is None:
        print("❌ KHÔNG tải được trang nào ở cả hai đường.")
        return 2

    text, d, tag = best
    # Chuỗi kỳ nằm ở ĐÂU trong trang? Đây là câu hỏi quyết định: trong ô
    # <td>/<th> thì sửa selector, trong <div> hay JSON thì đổi hẳn cách lấy.
    ctx = quarter_contexts(text)
    if ctx:
        print(f"── chuỗi KỲ đứng ở đâu (đường {tag}):")
        for c in ctx:
            print(f"   …{c[:230]}…")
        print()

    tables = parse_tables(text)
    chosen = pick_balance_table(tables)
    # In BẢNG TO NHẤT dù có được chọn hay không — nó gần như chắc chắn là
    # bảng cân đối, và cái cần nhìn là các hàng CÓ CHỮ, không phải hàng chèn.
    ranked = sorted(tables, key=lambda tb: -len(tb.get("rows") or []))[:4]
    for tb in ranked:
        rows = tb.get("rows") or []
        if len(rows) < 4:
            continue
        i = tables.index(tb)
        ident = tb["attrs"].get("id") or tb["attrs"].get("class") or "—"
        star = " ⭐ ĐANG CHỌN" if tb is chosen else ""
        h = header_row_index(rows)
        hdr = f" · tiêu đề KỲ ở hàng {h}" if h is not None else " · KHÔNG có tiêu đề KỲ"
        ne = nonempty_rows(rows, limit=10)
        print(f"── bảng #{i}  {ident}  ·  {len(rows)} hàng "
              f"({len(ne)}+ có chữ){hdr}{star}")
        if h is not None:
            per = header_periods(rows[h])
            print(f"   cột kỳ: {[(ci, quarter_label(*qq)) for ci, qq in per]}")
            print(f"   cột tên chỉ tiêu đoán là: {label_col_index(rows, h, per)}")
        for ri, r in ne:
            print(f"   [{ri:3d}] " + " | ".join(str(c)[:24] for c in r[:9])[:160])
        print()

    print("\n👉 Dán TOÀN BỘ phần trên ra — đủ để sửa mà không phải đoán.")
    return 0 if d["balance_table_found"] else 2


# Nhãn dòng TỔNG TÀI SẢN ở các nguồn — dùng để đối chiếu đơn vị.
_TOTAL_ASSET_KEYS = ("TỔNG TÀI SẢN", "TỔNG CỘNG TÀI SẢN", "Tổng tài sản",
                     "TOTAL ASSETS", "Total assets")


def unit_ratios(data_a: dict, data_b: dict, items_a: list, items_b: list,
                keys=_TOTAL_ASSET_KEYS) -> list:
    """[(kỳ, giá trị A, giá trị B, tỉ số)] ở các quý CẢ HAI nguồn cùng có.

    Hàm thuần. Không kết luận hộ — chỉ đưa tỉ số ra để người nhìn. Tỉ số
    quanh 1 000 nghĩa là hai nguồn khác nhau một bậc đơn vị; tỉ số lởm chởm
    nghĩa là **hai bảng không cùng nói về một chỉ tiêu**, khi đó đừng ghép.
    """
    ia = find_row(items_a, *keys)
    ib = find_row(items_b, *keys)
    if ia is None or ib is None:
        return []
    name_a, name_b = items_a[ia], items_b[ib]
    out = []
    for qq in sorted(set(data_a) & set(data_b)):
        va, vb = data_a[qq].get(name_a), data_b[qq].get(name_b)
        try:
            fa, fb = float(va), float(vb)
        except (TypeError, ValueError):
            continue
        out.append((qq, fa, fb, (fa / fb) if fb else None))
    return out


def crosscheck(ticker: str, limit: int, lang: str,
               src_a: str = "vci", src_b: str = "cafef") -> int:
    """Đối chiếu HAI nguồn ở các quý trùng nhau — trước khi tin nguồn mới.

    Nguồn mới chưa đo mà đem ghi thẳng vào file là cách chắc chắn nhất để đẻ
    ra một bảng cân đối trông chuẩn mà sai đơn vị.

    Năm đối chiếu là `CROSSCHECK_YEARS`, **không phải** 2015-2016: VCI chỉ có
    từ 2018-Q1, mà so hai nguồn KHÔNG có quý nào chung thì không so được gì.
    """
    print(f"[crosscheck] {ticker}: {src_a} ⇄ {src_b} "
          f"(năm {'-'.join(str(y) for y in CROSSCHECK_YEARS)})")
    try:
        df_a = fetch_balance_sheet(ticker, limit=limit, lang=lang, source=src_a,
                                   years=CROSSCHECK_YEARS)
        df_b = fetch_balance_sheet(ticker, limit=limit, lang=lang, source=src_b,
                                   years=CROSSCHECK_YEARS)
    except Exception as exc:                      # noqa: BLE001
        print(f"❌ {type(exc).__name__}: {exc}")
        return 2
    if df_a.empty or df_b.empty:
        print(f"❌ rỗng: {src_a}={df_a.shape} · {src_b}={df_b.shape}")
        return 2
    rows = unit_ratios(tidy(df_a, lang), tidy(df_b, lang),
                       source_item_order(df_a, lang),
                       source_item_order(df_b, lang))
    if not rows:
        print("❌ KHÔNG tìm được dòng TỔNG TÀI SẢN ở cả hai nguồn, hoặc hai "
              "nguồn không có quý nào trùng. Dán 10 chỉ tiêu đầu của mỗi bên:")
        for nm, d in ((src_a, df_a), (src_b, df_b)):
            print(f"  [{nm}] " + " | ".join(source_item_order(d, lang)[:10]))
        return 2
    print(f"{'KỲ':<9} {src_a:>18} {src_b:>18} {'TỈ SỐ':>10}")
    for qq, fa, fb, ratio in rows[-12:]:
        r = f"{ratio:,.3f}" if ratio else "—"
        print(f"{quarter_label(*qq):<9} {fa:>18,.0f} {fb:>18,.0f} {r:>10}")
    vals = [r for *_, r in rows if r]
    if vals:
        lo, hi = min(vals), max(vals)
        print(f"\ntỉ số: {lo:,.3f} → {hi:,.3f}"
              + ("  ✅ ỔN ĐỊNH — chênh đúng một bậc đơn vị"
                 if hi and lo and hi / lo < 1.01 else
                 "  ⚠️ LỞM CHỞM — hai bảng KHÔNG cùng một chỉ tiêu, đừng ghép"))
    return 0


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Xuất bảng cân đối kế toán theo quý của các ngân hàng")
    ap.add_argument("--from", dest="y_from", type=int, default=2018,
                    help="VCI chỉ có từ 2018-Q1; muốn 2015-2016 thì "
                         "--source cafef")
    ap.add_argument("--to", dest="y_to", type=int, default=2019)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="Mặc định: toàn bộ ngân hàng trong vnstock_brief_canon")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="Số kỳ xin về từ nguồn (mặc định 200 — API mặc định "
                         "CHỈ 4, xem ghi chú đầu file)")
    ap.add_argument("--lang", default="vi", choices=("vi", "en"))
    ap.add_argument("--source", default="vci", choices=SOURCES,
                    help="cafef = nguồn DUY NHẤT có 2015-2016 · vci = "
                         "2018-Q1 trở đi · kbs/tcbs = đo 26/08 đều hỏng")
    ap.add_argument("--out", default=None)
    ap.add_argument("--probe", metavar="MÃ", default=None,
                    help="Soi một mã ở MỘT nguồn rồi thoát")
    ap.add_argument("--probe-all", dest="probe_all", metavar="MÃ", default=None,
                    help="So MỌI nguồn trên một mã — CHẠY CÁI NÀY TRƯỚC")
    ap.add_argument("--want-year", type=int, default=2015,
                    help="Năm cần với tới, dùng cho --probe-all")
    ap.add_argument("--crosscheck", metavar="MÃ", default=None,
                    help="Đối chiếu ĐƠN VỊ vci ⇄ nguồn khác ở quý trùng nhau")
    ap.add_argument("--with", dest="with_source", default="cafef",
                    choices=SOURCES, help="Nguồn đem đối chiếu với vci")
    ap.add_argument("--dump-cafef", dest="dump_cafef", metavar="MÃ",
                    default=None,
                    help="In CẤU TRÚC trang CafeF + lưu HTML thô, khi bộ bóc trật")
    ap.add_argument("--dump-year", type=int, default=2016)
    args = ap.parse_args(argv)

    if args.probe_all:
        return probe_all(args.probe_all.upper(), args.limit, args.lang,
                         args.want_year)
    if args.dump_cafef:
        return dump_cafef(args.dump_cafef.upper(), args.dump_year)
    if args.crosscheck:
        return crosscheck(args.crosscheck.upper(), args.limit, args.lang,
                          src_b=args.with_source)
    if args.probe:
        return probe(args.probe.upper(), args.limit, args.lang, args.source)

    quarters = quarters_between(args.y_from, args.y_to)
    tickers = [t.upper() for t in (args.tickers or bank_tickers())]
    out = Path(args.out or REPO /
               f"bang_can_doi_ngan_hang_{args.y_from}_{args.y_to}.xlsx")

    per_bank, coverage, failed = {}, [], []
    orders, earliest = {}, []
    unit_note = None          # câu "Đơn vị: …" của trang nguồn, GHI nguyên văn
    for i, tk in enumerate(tickers, 1):
        print(f"[{i:2d}/{len(tickers)}] {tk} …", end=" ", flush=True)
        try:
            df = fetch_balance_sheet(tk, limit=args.limit, lang=args.lang,
                                     source=args.source,
                                     years=range(args.y_from, args.y_to + 1))
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
        unit_note = unit_note or df.attrs.get("unit_note")
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
    write_workbook(out, per_bank, items, quarters, coverage, args.lang,
                   source=args.source, unit_note=unit_note)
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
