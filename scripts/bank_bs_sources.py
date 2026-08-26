#!/usr/bin/env python3
"""NGUỒN bảng cân đối kế toán — mỗi nguồn quy về CÙNG một dạng frame.

Dạng chung (lấy theo VCI, vì đó là nguồn đã đo được):

    hàng = CHỈ TIÊU · cột = ``item`` + các kỳ ``2015-Q1`` … ``2026-Q2``

Nhờ vậy `export_bank_balance_sheets.py` không cần biết số liệu đến từ đâu —
`tidy` / `source_item_order` / `unified_items` dùng chung cho mọi nguồn.

⚠️ **TCBS ở đây CHƯA ĐƯỢC ĐO SỐNG.** Máy soạn script này bị chặn egress tới
mọi host tài chính VN (`403` từ agent proxy — `kbsec.com.vn`, `apipubaws.
tcbs.com.vn`, cả `hq.vnstocks.com`), nên phần mạng chỉ chạy được trên máy
user. Hai hệ quả VIẾT THẲNG VÀO ĐÂY để đừng ai (kể cả tôi) tưởng là đã kiểm:

* **Danh mục trường** dưới đây chép theo trí nhớ về API TCBS ⇒ có thể thiếu.
  Vì thế `tcbs_to_frame` **không lọc theo danh mục**: trường lạ vẫn ra bảng
  với tên gốc. Danh mục chỉ để DỊCH tên, không để chọn dòng.
* **Đơn vị chưa biết** (TCBS hay trả tỉ VND, VCI trả triệu VND). Không đoán —
  `--crosscheck` đối chiếu một quý trùng nhau giữa hai nguồn rồi in TỈ SỐ.
  Chưa có tỉ số đo được thì đừng nhân chia gì hết.
"""
from __future__ import annotations

import re

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
HTTP_TIMEOUT_S = 25

# ── TCBS ────────────────────────────────────────────────────────────────
TCBS_BS_URL = "https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance/{ticker}/balancesheet"
TCBS_PARAMS = {"yearly": 0, "isAll": "true"}

# Khoá mô tả KỲ, không phải chỉ tiêu — luôn bỏ khỏi thân bảng.
TCBS_META_KEYS = ("ticker", "quarter", "year")

# camelCase → tiếng Việt. THIẾU KHÔNG SAO (xem cảnh báo đầu file): trường lạ
# giữ nguyên tên gốc chứ không bị bỏ.
TCBS_VI = {
    # Tài sản
    "cash": "Tiền mặt, vàng bạc, đá quý",
    "centralBankDeposit": "Tiền gửi tại Ngân hàng Nhà nước",
    "otherBankDeposit": "Tiền gửi tại các TCTD khác",
    "otherBankLoan": "Cho vay các TCTD khác",
    "otherBankCredit": "Tiền gửi và cho vay các TCTD khác",
    "stockInvest": "Chứng khoán đầu tư",
    "customerLoan": "Cho vay khách hàng",
    "badLoan": "Nợ xấu",
    "provision": "Dự phòng rủi ro cho vay khách hàng",
    "netCustomerLoan": "Cho vay khách hàng (thuần)",
    "shortInvest": "Đầu tư ngắn hạn",
    "shortReceivable": "Các khoản phải thu ngắn hạn",
    "inventory": "Hàng tồn kho",
    "shortAsset": "Tài sản ngắn hạn",
    "fixedAsset": "Tài sản cố định",
    "longAsset": "Tài sản dài hạn",
    "otherAsset": "Tài sản có khác",
    "receivableInterest": "Lãi, phí phải thu",
    "asset": "TỔNG TÀI SẢN",
    # Nợ phải trả
    "oweCentralBank": "Các khoản nợ Ngân hàng Nhà nước",
    "oweOtherBank": "Tiền gửi và vay các TCTD khác",
    "deposit": "Tiền gửi của khách hàng",
    "valuablePaper": "Phát hành giấy tờ có giá",
    "payableInterest": "Lãi, phí phải trả",
    "payable": "Các khoản phải trả",
    "shortDebt": "Nợ ngắn hạn",
    "longDebt": "Nợ dài hạn",
    "otherDebt": "Các khoản nợ khác",
    "debt": "TỔNG NỢ PHẢI TRẢ",
    # Vốn chủ sở hữu
    "capital": "Vốn điều lệ",
    "fund": "Các quỹ",
    "unDistributedIncome": "Lợi nhuận chưa phân phối",
    "minorShareHolderProfit": "Lợi ích cổ đông thiểu số",
    "equity": "VỐN CHỦ SỞ HỮU",
}


def _camel_to_words(key: str) -> str:
    """`otherBankDeposit` → `Other bank deposit` — nhãn tạm cho trường lạ."""
    parts = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).strip().split()
    if not parts:
        return str(key)
    words = [parts[0].lower()] + [p.lower() for p in parts[1:]]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def tcbs_label(key: str, lang: str = "vi") -> str:
    if lang == "en":
        return _camel_to_words(key)
    return TCBS_VI.get(key, _camel_to_words(key))


def tcbs_period(rec) -> "tuple | None":
    """(năm, quý) của một bản ghi TCBS, hoặc None nếu không đọc ra."""
    try:
        y = int(rec["year"])
        q = int(rec["quarter"])
    except (KeyError, TypeError, ValueError):
        return None
    return (y, q) if 1 <= q <= 4 else None


def tcbs_records(payload) -> list:
    """Bóc danh sách bản ghi khỏi payload — chịu cả list lẫn dict bọc ngoài."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for k in ("data", "items", "result", "content"):
            v = payload.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def tcbs_field_order(records) -> list:
    """Thứ tự trường THEO NGUỒN — thứ tự khoá của bản ghi đầu, rồi bổ sung.

    Không tự sắp lại: thứ tự khoá của TCBS đã là thứ tự bảng cân đối, mà xếp
    nhầm một dòng thì cả bảng sai.
    """
    seen, out = set(), []
    for rec in records:
        for k in rec:
            if k in TCBS_META_KEYS or k in seen:
                continue
            seen.add(k)
            out.append(k)
    return out


def tcbs_to_frame(payload, lang: str = "vi"):
    """Payload TCBS → frame hàng=chỉ tiêu, cột=`item` + `2015-Q1`…

    Payload rỗng/không đọc được ⇒ frame RỖNG (chỗ gọi phải dừng, đừng ghi
    file). Không bao giờ điền 0 thay cho ô thiếu.
    """
    import pandas as pd

    records = tcbs_records(payload)
    dated = [(qq, r) for r in records if (qq := tcbs_period(r)) is not None]
    if not dated:
        return pd.DataFrame()

    dated.sort(key=lambda t: t[0])
    fields = tcbs_field_order([r for _, r in dated])
    if not fields:
        return pd.DataFrame()

    cols = {"item": [tcbs_label(f, lang) for f in fields]}
    for (y, q), rec in dated:
        cols[f"{y}-Q{q}"] = [rec.get(f) for f in fields]
    return pd.DataFrame(cols)


def fetch_tcbs(ticker: str, timeout: float = HTTP_TIMEOUT_S):
    """(payload, url) — ném lỗi rõ ràng chứ không nuốt."""
    import requests

    url = TCBS_BS_URL.format(ticker=ticker.upper())
    resp = requests.get(url, params=TCBS_PARAMS, headers=HTTP_HEADERS,
                        timeout=timeout)
    resp.raise_for_status()
    return resp.json(), resp.url


# ── CafeF (mới chỉ THĂM DÒ, chưa bóc số) ────────────────────────────────
CAFEF_BS_URL = ("https://s.cafef.vn/bao-cao-tai-chinh/{ticker}/BSheet/{year}/"
                "{quarter}/0/0/bao-cao-tai-chinh-.chn")

_CAFEF_QUARTER_PATTERNS = (
    re.compile(r"Quý\s*([1-4])\s*[-/]\s*(20\d{2})", re.I),
    re.compile(r"Q([1-4])\s*[-/]\s*(20\d{2})", re.I),
)


def cafef_quarters_in(html: str) -> list:
    """Các kỳ `(năm, quý)` NHÌN THẤY trong trang — dò tiêu đề cột, không bóc số.

    Chỉ để trả lời một câu: trang có thật sự chứa quý mình xin không. Bóc số
    chỉ viết sau khi nhìn cấu trúc bảng thật, không viết mò.
    """
    found = set()
    for pat in _CAFEF_QUARTER_PATTERNS:
        for m in pat.finditer(html or ""):
            found.add((int(m.group(2)), int(m.group(1))))
    return sorted(found)


def fetch_cafef(ticker: str, year: int, quarter: int,
                timeout: float = HTTP_TIMEOUT_S):
    """(status_code, text, url) — không ném, để probe còn in được lý do."""
    import requests

    url = CAFEF_BS_URL.format(ticker=ticker.upper(), year=year, quarter=quarter)
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    except Exception as exc:                      # noqa: BLE001 — probe báo cáo
        return None, f"{type(exc).__name__}: {exc}", url
    return resp.status_code, resp.text, resp.url
