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
# VCI viết "Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%" (GMD 05/10) —
# thứ tự NGƯỢC với "thưởng cổ phiếu". So khớp CÓ DẤU: bỏ dấu thì "thưởng" trùng
# "thường", mà "cổ phiếu thường" là cổ phiếu PHỔ THÔNG (niêm yết bổ sung, hoán
# đổi…). Tiêu đề không dấu "co phieu thuong" vì thế KHÔNG được đọc (đặc tả R18).
_BONUS_ACCENTED = "cổ phiếu thưởng"
_CASH_WORDS = ("bang tien", "dong/cp", "dong/co phieu", "tien mat")
# Phát hành có giá mua — công thức khác, KHÔNG đoán.
_REFUSE_WORDS = ("quyen mua", "chao ban", "phat hanh them cho co dong",
                 "phat hanh rieng le")

# Sự kiện CÓ ngày chốt quyền nhưng KHÔNG đụng tới giá tham chiếu: chốt danh
# sách để DỰ HỌP / BỎ PHIẾU. Không có gì chia ra khỏi doanh nghiệp ⇒ HOSE
# KHÔNG điều chỉnh giá. Vết close 24/08: mã PNJ bị gắn "⚠️ GDKHQ … — giá
# tham chiếu TỰ ĐIỀU CHỈNH" cho sự kiện "Tổ chức ĐHĐCĐ bất thường 2026" —
# cảnh báo một cú giảm giá KHÔNG BAO GIỜ xảy ra, tệ hơn im lặng vì nó khiến
# người đọc bỏ qua một cú giảm THẬT ở mã khác.
_NON_ADJUSTING_WORDS = (
    "dai hoi dong co dong", "dai hoi co dong", "dhdcd",
    "lay y kien co dong", "lay y kien bang van ban",
    "to chuc dai hoi", "hop dai hoi", "tham du dai hoi",
    "hoi nghi nha dau tu",
)


def adjusts_price(title: str) -> bool:
    """Sự kiện này có làm giá tham chiếu đổi trong ngày GDKHQ không? Hàm thuần.

    Có phân phối (tiền/cổ phiếu) hoặc quyền mua ⇒ CÓ. Chỉ chốt danh sách dự
    họp/bỏ phiếu ⇒ KHÔNG. Không nhận ra ⇒ **mặc định CÓ** — cảnh báo thừa còn
    đỡ hơn bỏ sót một cú điều chỉnh thật.
    """
    t = _norm(title)
    if not t:
        return True
    if any(w in t for w in _STOCK_WORDS + _CASH_WORDS + _REFUSE_WORDS):
        return True                      # có chia/có quyền mua ⇒ giá đổi
    return not any(w in t for w in _NON_ADJUSTING_WORDS)


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
    is_stock = (any(w in t for w in _STOCK_WORDS)
                or _BONUS_ACCENTED in unicodedata.normalize("NFC", str(title)).lower())
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
        # VCI: "... - Đợt 2 2025 - 1,000 VND" — số tiền là trọn MỘT vế giữa
        # hai dấu gạch, hoặc đứng CUỐI tiêu đề ("- 2025 đồng thời …" không
        # phải tiền). Đứng sau nhánh % để "tỷ lệ 10% (mệnh giá 10.000 đồng)"
        # vẫn ra 1.000; mệnh giá trần thì không phải số tiền chia.
        m = (re.search(r"[-–—]\s*(\d[\d.,]*)\s*(?:vnd|dong)\s*(?=[-–—]|$)", t)
             or re.search(r"(\d[\d.,]*)\s*(?:vnd|dong)\s*[.)]?\s*$", t))
        if m and not t[:m.start(1)].rstrip(" -–—:,(").endswith("menh gia"):
            v = _to_number(m.group(1))
            return {"kind": "cash", "cash_vnd": v} if v and v > 0 else None
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
    """"1.500" → 1500 · "1,000" → 1000 · "1.500,5" → 1500.5 · "5.0" → 5.0.

    Nguồn trộn hai kiểu số: tiêu đề VN dùng '.' làm NGHÌN, VCI in kiểu EN
    ("1,000 VND"). Bản cũ coi mọi ',' là thập phân ⇒ "1,000" ra 1.0. Một luật
    cho CẢ HAI dấu: đủ hai dấu thì dấu ĐỨNG SAU là thập phân; chỉ một loại dấu
    thì các nhóm đúng 3 chữ số sau nó (nhóm đầu 1–3 chữ số, không mở bằng 0)
    là NGHÌN, còn lại là thập phân.
    """
    s = str(raw).strip()
    try:
        if "," in s and "." in s:
            dec = "," if s.rfind(",") > s.rfind(".") else "."
            thou = "." if dec == "," else ","
            return float(s.replace(thou, "").replace(dec, "."))
        sep = "," if "," in s else "." if "." in s else None
        if sep is None:
            return float(s)
        head, *tail = s.split(sep)
        if (1 <= len(head) <= 3 and not head.startswith("0")
                and all(len(g) == 3 for g in tail)):
            return float(head + "".join(tail))
        return float(f"{head}.{tail[0]}") if len(tail) == 1 else None
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
