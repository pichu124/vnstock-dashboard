"""
vnstock_corp_ratio.py — Đọc TỈ LỆ QUYỀN từ tiêu đề sự kiện, và quy đổi giá tham chiếu
=====================================================================================
Sinh 19/08 sau khi `run.py vietstock --ticker PET` cho một phép kiểm khớp đến 4
chữ số:

    2026-07-09  bonus  Trả cổ tức năm 2025 bằng cổ phiếu, tỷ lệ 20:1
    2026-07-09  bonus  Thưởng cổ phiếu, tỷ lệ 5:2
    ⇒ 100 cp → +5 +40 = 145 ⇒ hệ số 1.45
    Bộ chữa kho đo ĐỘC LẬP TỪ GIÁ: 1.4499×.  Lệch 0,007%.

Vì sao module này tồn tại: guard GDKHQ (`enforce_exdate_levels`) trước đây CỐ Ý
không quy đổi mốc giá, vì tỉ lệ chỉ nằm trong CHỮ và đoán sai còn hại hơn không
đoán. Nay tách phép đọc chữ thành hàm THUẦN có lưới, nên quy đổi được — nhưng
vẫn giữ nguyên tinh thần: **không chắc thì trả None**, chỗ gọi quay về hành vi
cảnh báo-không-kèm-số.

Ba luật, mỗi luật đều học từ dữ liệu thật chứ không từ trực giác
----------------------------------------------------------------
1. **`tỷ lệ A:B` = A cổ phiếu CŨ nhận thêm B cổ phiếu MỚI** ⇒ `r = B/A`.
   (`20:1` → +5% · `5:2` → +40%.)
2. **Nhiều sự kiện CÙNG một ngày GDKHQ thì CỘNG DỒN trên số cổ phiếu GỐC**,
   KHÔNG nhân dây chuyền. PET: `1 + 0.05 + 0.40 = 1.45` khớp số đo; nhân dây
   chuyền ra `1.05 × 1.40 = 1.47`, lệch 1,4% — đủ để sai.
3. **Cổ tức TIỀN MẶT trừ theo SỐ TUYỆT ĐỐI**, không theo % giá:
   `P_adj = (P − D) / (1 + r)`. Đây là cái bẫy VN kinh điển — "tỷ lệ 10%" của
   cổ tức tiền mặt là 10% MỆNH GIÁ (1.000đ), không phải 10% thị giá.

Cố ý KHÔNG xử
-------------
Phát hành thêm có giá mua (`quyền mua`, `chào bán`): công thức cần thêm giá
phát hành, không suy được từ tiêu đề ⇒ trả None để chỗ gọi cảnh báo suông.
"""

from __future__ import annotations

import re
import unicodedata

# Mệnh giá cổ phiếu VN — mốc quy đổi cho "cổ tức tiền mặt tỷ lệ X%".
PAR_VALUE_VND = 10_000.0

_STOCK_WORDS = ("bang co phieu", "thuong co phieu", "chia tach", "tach co phieu")
_CASH_WORDS = ("bang tien", "dong/cp", "dong/co phieu", "tien mat")
# Phát hành có giá mua — công thức khác, KHÔNG đoán.
_REFUSE_WORDS = ("quyen mua", "chao ban", "phat hanh them cho co dong",
                 "phat hanh rieng le")


def _norm(text: str) -> str:
    """Bỏ dấu + hạ chữ thường — tiêu đề đến từ nhiều nguồn, dấu không đồng nhất."""
    s = unicodedata.normalize("NFD", str(text or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def parse_event(title: str) -> "dict | None":
    """Một tiêu đề → `{"kind": "stock"|"cash", "share_ratio"|"cash_vnd"}`.

    Hàm THUẦN. Trả None khi không chắc — gồm cả loại phát hành có giá mua.
    """
    t = _norm(title)
    if not t or any(w in t for w in _REFUSE_WORDS):
        return None

    is_cash = any(w in t for w in _CASH_WORDS)
    is_stock = any(w in t for w in _STOCK_WORDS)
    if is_cash and not is_stock:
        # "500 dong/cp" hoặc "1.500 dong/co phieu"
        m = re.search(r"([\d][\d.,]*)\s*dong\s*/\s*(?:cp|co phieu)", t)
        if m:
            v = _to_number(m.group(1))
            return {"kind": "cash", "cash_vnd": v} if v and v > 0 else None
        # "ty le 10%" của cổ tức TIỀN MẶT = 10% MỆNH GIÁ, không phải thị giá
        m = re.search(r"t[iy] le\s*([\d]+(?:[.,]\d+)?)\s*%", t)
        if m:
            v = _to_number(m.group(1))
            return ({"kind": "cash", "cash_vnd": v / 100.0 * PAR_VALUE_VND}
                    if v and v > 0 else None)
        return None

    if is_stock:
        # "ty le 20:1" — A cũ nhận thêm B mới
        m = re.search(r"t[iy] le\s*([\d]+(?:[.,]\d+)?)\s*[:/]\s*([\d]+(?:[.,]\d+)?)", t)
        if m:
            a, b = _to_number(m.group(1)), _to_number(m.group(2))
            return ({"kind": "stock", "share_ratio": b / a}
                    if a and b and a > 0 and b > 0 else None)
        # "ty le 5%" của cổ phiếu = 5 cp mới trên 100 cp cũ
        m = re.search(r"t[iy] le\s*([\d]+(?:[.,]\d+)?)\s*%", t)
        if m:
            v = _to_number(m.group(1))
            return ({"kind": "stock", "share_ratio": v / 100.0}
                    if v and v > 0 else None)
    return None


def _to_number(raw: str) -> "float | None":
    """"1.500" → 1500 · "5.0" → 5.0 · "20" → 20. Số VN dùng '.' làm nghìn."""
    s = str(raw).strip()
    try:
        if "," in s:                       # "1.500,5" kiểu VN
            return float(s.replace(".", "").replace(",", "."))
        if s.count(".") == 1:
            intp, dec = s.split(".")
            # 3 chữ số sau dấu chấm ⇒ đó là dấu NGHÌN ("1.500"), không phải thập phân
            return float(s.replace(".", "")) if len(dec) == 3 else float(s)
        return float(s.replace(".", ""))
    except (TypeError, ValueError):
        return None


def combine(titles) -> "dict | None":
    """Gộp các sự kiện CÙNG một ngày GDKHQ → `{"share_ratio", "cash_vnd", "n"}`.

    Cộng dồn trên số cổ phiếu GỐC (luật 2 trong docstring module). Trả None khi
    KHÔNG đọc được sự kiện nào — "một phần" cũng không đủ để quy đổi, vì thiếu
    một vế là ra một con số sai trông rất thuyết phục.
    """
    parsed = [p for t in (titles or []) if (p := parse_event(t))]
    if not parsed or len(parsed) != len(list(titles or [])):
        return None
    return {
        "share_ratio": sum(p.get("share_ratio", 0.0) for p in parsed),
        "cash_vnd": sum(p.get("cash_vnd", 0.0) for p in parsed),
        "n": len(parsed),
    }


def adjusted_price(price: float, titles) -> "float | None":
    """Giá tham chiếu ngày GDKHQ: `P_adj = (P − D) / (1 + r)`.

    `price` tính bằng ĐỒNG (giá thị trường thật). Trả None khi không đọc được
    trọn bộ sự kiện, hoặc kết quả vô lý (≤ 0).
    """
    c = combine(titles)
    if c is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    adj = (p - c["cash_vnd"]) / (1.0 + c["share_ratio"])
    return adj if adj > 0 else None
