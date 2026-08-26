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


# Nhãn CHỈ CÓ Ở BẢNG CÂN ĐỐI NGÂN HÀNG. Nếu một bảng không có dòng nào trong
# số này thì nó đang dùng khung DOANH NGHIỆP THƯỜNG — tên dòng không mang
# nghĩa kế toán ngân hàng, và người đọc phải biết điều đó TRƯỚC khi dùng số.
BANK_ONLY_ITEMS = ("Cho vay khách hàng", "Tiền gửi của khách hàng",
                   "Tiền gửi tại Ngân hàng Nhà nước",
                   "Phát hành giấy tờ có giá",
                   "Dự phòng rủi ro cho vay khách hàng")
# Nhãn ĐẶC TRƯNG khung doanh nghiệp — có chúng ở một ngân hàng là dấu hiệu
# nguồn đã ép số vào khung sai.
CORPORATE_ITEMS = ("Hàng tồn kho", "Tài sản ngắn hạn", "Tài sản dài hạn",
                   "Các khoản phải thu ngắn hạn", "Nợ ngắn hạn")

# Khung nào là BẰNG CHỨNG sai — chỉ chặn ghi file ở những khung này.
# "KHÔNG NHẬN RA" nghĩa là chưa biết, KHÔNG phải sai: chặn vì chưa biết là
# đẻ ra từ chối oan cho mọi nguồn đặt tên khác danh mục trên.
WRONG_TEMPLATES = ("DOANH NGHIỆP THƯỜNG", "LẪN LỘN")


def template_kind(items: list) -> dict:
    """Bảng này theo khung NGÂN HÀNG hay khung DOANH NGHIỆP THƯỜNG?

    Hàm thuần, đếm nhãn đặc trưng chứ không suy diễn. Trả DỮ KIỆN kèm một
    nhãn ngắn; chỗ gọi in ra để người đọc tự quyết, vì đây là chuyện NGHĨA
    của con số, không phải chuyện định dạng.
    """
    bank = [k for k in BANK_ONLY_ITEMS if find_row(items, k) is not None]
    corp = [k for k in CORPORATE_ITEMS if find_row(items, k) is not None]
    if bank:
        kind = "NGÂN HÀNG" if len(bank) >= len(corp) else "LẪN LỘN"
    else:
        kind = "DOANH NGHIỆP THƯỜNG" if corp else "KHÔNG NHẬN RA"
    return {"kind": kind, "bank_hits": bank, "corporate_hits": corp}


# Trần TỈNH TÁO cho một ô trong bảng cân đối ngân hàng VN, tính bằng ĐỒNG.
# Ngân hàng lớn nhất nước cỡ 2-3 triệu tỷ = ~3e15. Vượt 1e18 thì đó KHÔNG
# phải một con số kế toán, đó là lỗi bóc số — và một ô như thế lọt vào file
# sẽ kéo lệch mọi phép so sánh mà chẳng ai để ý.
SANE_MAX_VND = 1e18


def insane_values(per_bank: dict, ceiling: float = SANE_MAX_VND) -> list:
    """[(mã, kỳ, chỉ tiêu, giá trị)] cho các ô vượt trần tỉnh táo.

    Hàm thuần. Không tự sửa và không tự bỏ — chỉ NÊU RA, vì một ô sai kiểu
    này là dấu hiệu bộ bóc hỏng chứ không phải một ngoại lệ cần vá riêng.
    """
    out = []
    for tk in sorted(per_bank):
        for qq in sorted(per_bank[tk]):
            for name, v in (per_bank[tk][qq] or {}).items():
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if not _is_blank(f) and abs(f) > ceiling:
                    out.append((tk, qq, name, f))
    return out


def show_items(ticker: str, limit: int, lang: str, source: str, years) -> int:
    """In DANH SÁCH chỉ tiêu của một mã + khung bảng — để trả lời câu hỏi
    NGHĨA: nguồn có thật sự đưa bảng cân đối NGÂN HÀNG không.

    Định dạng đúng mà nghĩa sai là ca tệ nhất ở đây: file mở ra trông chuẩn,
    26 sheet đều nhau, mà tên dòng lại là khung doanh nghiệp.
    """
    df = fetch_balance_sheet(ticker, limit=limit, lang=lang, source=source,
                             years=years)
    if df.empty:
        print(f"[items] ❌ {source} trả về RỖNG cho {ticker}")
        return 2
    items = source_item_order(df, lang)
    data = tidy(df, lang)
    periods = [qq for _, qq in detect_period_columns(df.columns)]
    tk = template_kind(items)

    print(f"[items] {ticker} · nguồn={source} · {len(items)} chỉ tiêu · "
          f"{len(periods)} quý")
    print(f"[items] KHUNG BẢNG: {tk['kind']}")
    print(f"        nhãn ngân hàng thấy được: "
          + (", ".join(tk["bank_hits"]) or "— KHÔNG CÓ"))
    print(f"        nhãn doanh nghiệp thấy được: "
          + (", ".join(tk["corporate_hits"]) or "— không có"))
    if tk["kind"] != "NGÂN HÀNG":
        print("        ⚠️ Tên dòng KHÔNG mang nghĩa kế toán ngân hàng. Đọc số "
              "theo tên dòng ở đây là hiểu sai.")
    print(f"\n{'#':>4}  {'CÓ SỐ':>6}  CHỈ TIÊU")
    for i, name in enumerate(items, 1):
        n = sum(1 for qq in periods if not _is_blank((data.get(qq) or {}).get(name)))
        print(f"{i:>4}  {n:>2}/{len(periods):<3}  {name[:70]}")
    empty = sum(1 for name in items
                if all(_is_blank((data.get(qq) or {}).get(name)) for qq in periods))
    print(f"\n{empty}/{len(items)} chỉ tiêu KHÔNG có số ở kỳ nào — "
          f"để TRỐNG, không điền 0.")
    return 0


# Nhãn dòng TỔNG TÀI SẢN ở các nguồn — dùng để đối chiếu đơn vị.
_TOTAL_ASSET_KEYS = ("TỔNG TÀI SẢN", "TỔNG CỘNG TÀI SẢN", "Tổng tài sản",
                     "TOTAL ASSETS", "Total assets")


def _ratio_rows(name_a: str, name_b: str, data_a: dict, data_b: dict) -> list:
    """[(kỳ, A, B, tỉ số)] cho MỘT cặp nhãn — bỏ ô trống/NaN, không bỏ số 0."""
    out = []
    for qq in sorted(set(data_a) & set(data_b)):
        va, vb = data_a[qq].get(name_a), data_b[qq].get(name_b)
        try:
            fa, fb = float(va), float(vb)
        except (TypeError, ValueError):
            continue
        if _is_blank(fa) or _is_blank(fb):
            continue
        out.append((qq, fa, fb, (fa / fb) if fb else None))
    return out


def unit_ratios(data_a: dict, data_b: dict, items_a: list, items_b: list,
                keys=_TOTAL_ASSET_KEYS) -> list:
    """[(kỳ, giá trị A, giá trị B, tỉ số)] ở các quý CẢ HAI nguồn cùng có.

    Thử LẦN LƯỢT từng nhãn và **bỏ qua nhãn nào rỗng số**. Vết 26/08: bản
    đầu lấy nhãn khớp ĐẦU TIÊN rồi thôi — nó trúng một dòng TIÊU ĐỀ MỤC mà
    CafeF để trống, thế là cả phép đối chiếu ra `nan` và không kết luận được
    gì, trong khi bảng có thừa số để so.

    Hàm thuần. Không kết luận hộ — chỉ đưa tỉ số ra để người nhìn.
    """
    def _candidates(items):
        out = []
        for key in keys:
            i = find_row(items, key)
            if i is not None and items[i] not in out:
                out.append(items[i])
        return out

    # Hai nguồn có thể gọi cùng một dòng bằng hai tên (VI ⇄ EN), nên thử MỌI
    # cặp — và cặp nào rỗng số thì đi tiếp, đừng dừng lại ở nó.
    for name_a in _candidates(items_a):
        for name_b in _candidates(items_b):
            rows = _ratio_rows(name_a, name_b, data_a, data_b)
            if rows:
                return rows
    return []


def _max_abs(period_values: dict):
    """|giá trị| lớn nhất trong một kỳ — None nếu kỳ đó không có số nào."""
    nums = []
    for v in (period_values or {}).values():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not _is_blank(f):
            nums.append(abs(f))
    return max(nums) if nums else None


def magnitude_ratios(data_a: dict, data_b: dict) -> list:
    """Tỉ số THANG ĐO, KHÔNG cần nhãn: |giá trị| lớn nhất mỗi kỳ ở mỗi nguồn.

    Lưới cuối cho câu hỏi ĐƠN VỊ khi hai nguồn đặt tên chỉ tiêu khác nhau.
    Trong một bảng cân đối, số lớn nhất luôn là tổng tài sản (hoặc tổng
    nguồn vốn, bằng nhau), nên tỉ số này đo đúng thứ cần đo — bậc đơn vị —
    mà không phụ thuộc vào việc khớp được nhãn hay không.

    Nó KHÔNG chứng minh hai bảng nói cùng một chỉ tiêu. Chỉ trả lời: chênh
    nhau mấy bậc nghìn.
    """
    out = []
    for qq in sorted(set(data_a) & set(data_b)):
        ma, mb = _max_abs(data_a[qq]), _max_abs(data_b[qq])
        if ma is None or mb is None:
            continue
        out.append((qq, ma, mb, (ma / mb) if mb else None))
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
    ta, tb = tidy(df_a, lang), tidy(df_b, lang)
    rows = unit_ratios(ta, tb, source_item_order(df_a, lang),
                       source_item_order(df_b, lang))
    how = "dòng TỔNG TÀI SẢN"
    if not rows:
        # Không khớp được nhãn thì vẫn còn đo được BẬC ĐƠN VỊ, và đó mới là
        # câu hỏi ở đây. Nói rõ đang đo bằng cách nào.
        rows = magnitude_ratios(ta, tb)
        how = "|giá trị| LỚN NHẤT mỗi kỳ (không khớp được nhãn)"
    if not rows:
        print("❌ Hai nguồn không có quý nào trùng, hoặc một bên không có số "
              "nào. Dán 10 chỉ tiêu đầu của mỗi bên:")
        for nm, d in ((src_a, df_a), (src_b, df_b)):
            print(f"  [{nm}] " + " | ".join(source_item_order(d, lang)[:10]))
        return 2
    print(f"đo bằng: {how}\n")
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
# Ghi Excel đã tách sang `bank_bs_excel` (trần 800 dòng/file).
# ─────────────────────────────────────────────────────────────────────────
from scripts.bank_bs_excel import write_workbook  # noqa: E402


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
    ap.add_argument("--allow-any-template", dest="allow_any_template",
                    action="store_true",
                    help="Ghi file KỂ CẢ khi nguồn dùng khung kế toán khác "
                         "(mặc định: từ chối ghi)")
    ap.add_argument("--items", metavar="MÃ", default=None,
                    help="In danh sách chỉ tiêu + KHUNG bảng (ngân hàng hay "
                         "doanh nghiệp thường) rồi thoát")
    args = ap.parse_args(argv)

    if args.probe_all:
        return probe_all(args.probe_all.upper(), args.limit, args.lang,
                         args.want_year)
    if args.dump_cafef:
        return dump_cafef(args.dump_cafef.upper(), args.dump_year)
    if args.crosscheck:
        return crosscheck(args.crosscheck.upper(), args.limit, args.lang,
                          src_b=args.with_source)
    if args.items:
        return show_items(args.items.upper(), args.limit, args.lang,
                          args.source, range(args.y_from, args.y_to + 1))
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

    # ── Chốt chặn NGHĨA. "File rỗng trông như thật" đã chặn ở trên; đây là
    # ca tệ hơn: file ĐẦY SỐ, 26 sheet đều tăm tắp, mà tên dòng thuộc khung
    # kế toán khác. Đọc số theo tên dòng khi đó là hiểu sai, và không có gì
    # trong file tự nói ra điều đó.
    tk_info = template_kind(items)
    if tk_info["kind"] in WRONG_TEMPLATES and not args.allow_any_template:
        print(f"\n❌ KHUNG BẢNG là {tk_info['kind']} — KHÔNG ghi file.")
        print("   nhãn ngân hàng thấy được: "
              + (", ".join(tk_info["bank_hits"]) or "— KHÔNG CÓ"))
        print("   nhãn doanh nghiệp thấy được: "
              + (", ".join(tk_info["corporate_hits"]) or "— không có"))
        print("   Nguồn đang ép số ngân hàng vào khung kế toán KHÁC. File sẽ")
        print("   đầy số và đều tăm tắp, mà tên dòng KHÔNG mang nghĩa kế toán")
        print("   ngân hàng — đó là kiểu sai khó phát hiện nhất.")
        print(f"   Soi cụ thể: --items {tickers[0]} --source {args.source}")
        print("   Vẫn muốn ghi (để tự xem): thêm --allow-any-template")
        return 2
    if tk_info["kind"] == "KHÔNG NHẬN RA":
        # CHẶN thì phải có BẰNG CHỨNG. Không đủ nhãn để kết luận là "chưa
        # biết", không phải "sai" — chặn ở đây là đẻ ra từ chối oan cho mọi
        # nguồn đặt tên khác với danh mục của tôi.
        print("\n⚠️ Không đủ nhãn đặc trưng để nói khung này là ngân hàng hay "
              f"không. Kiểm bằng: --items {tickers[0]} --source {args.source}")

    bad = insane_values(per_bank)
    if bad:
        print(f"\n⚠️ {len(bad)} ô vượt trần tỉnh táo ({SANE_MAX_VND:,.0f} đồng) "
              f"— dấu hiệu BÓC SỐ HỎNG, không phải ngoại lệ kế toán:")
        for tkr, qq, name, v in bad[:5]:
            print(f"   {tkr} {quarter_label(*qq)} · {name[:40]} = {v:,.0f}")
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
