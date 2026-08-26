#!/usr/bin/env python3
"""HÌNH DẠNG bảng cân đối — hàm THUẦN, dùng chung cho mọi nguồn.

Tách khỏi `export_bank_balance_sheets.py` (26/08) để file đó khỏi vượt trần
800 dòng của repo. Không có logic mạng, không có openpyxl — nhờ vậy test
chạy được offline và nhanh.

Quy ước xuyên suốt: frame nguồn có **hàng = CHỈ TIÊU, cột = KỲ** (`item`,
`2015-Q1`, `2015-Q2`, …). Ô TRỐNG ≠ SỐ 0 — "không có số" và "bằng không" là
hai chuyện khác hẳn trong một bảng cân đối.
"""
from __future__ import annotations

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
