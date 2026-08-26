#!/usr/bin/env python3
"""NGUỒN bảng cân đối kế toán — mỗi nguồn quy về CÙNG một dạng frame.

Dạng chung (lấy theo VCI, vì đó là nguồn đã đo được):

    hàng = CHỈ TIÊU · cột = ``item`` + các kỳ ``2015-Q1`` … ``2026-Q2``

Nhờ vậy `export_bank_balance_sheets.py` không cần biết số liệu đến từ đâu —
`tidy` / `source_item_order` / `unified_items` dùng chung cho mọi nguồn.

**Đo 26/08 trên máy user** (`--probe-all VCB`) — bảng này là SỰ THẬT, phần
còn lại của file chỉ là cách xử lý nó:

| nguồn   | kết quả                                            |
|---------|----------------------------------------------------|
| `vci`   | ✅ 2018-Q1 → 2026-Q2, 83 chỉ tiêu                   |
| `kbs`   | ❌ `TypeError: balance_sheet() got an unexpected keyword` |
| `tcbs`  | ❌ `404` — endpoint `apipubaws` đã chết             |
| `cafef` | ✅ HTTP 200, trang `/2016/4/…` chứa đủ **Quý 1-2016 → Quý 4-2016** |

⚠️ **Máy soạn script này bị chặn egress tới mọi host tài chính VN** (`403` từ
agent proxy — `kbsec.com.vn`, `apipubaws.tcbs.com.vn`, cả `hq.vnstocks.com`),
nên MỌI phần mạng chỉ chạy được trên máy user. Ba hệ quả viết thẳng vào đây
để đừng ai (kể cả tôi) tưởng là đã kiểm:

* **Danh mục trường TCBS** chép theo trí nhớ ⇒ có thể thiếu. Vì thế
  `tcbs_to_frame` **không lọc theo danh mục**: trường lạ vẫn ra bảng với tên
  gốc. Danh mục chỉ để DỊCH tên, không để chọn dòng.
* **Bộ bóc CafeF viết mà chưa nhìn trang thật.** Nó nhận diện bảng theo HÌNH
  DẠNG (có ≥2 cột tiêu đề là kỳ, đủ dòng) chứ không theo `id`/`class`, và
  không nhận ra thì trả frame RỖNG. Trật thì `--dump-cafef` in ra cấu trúc
  thật để sửa — đừng đoán tiếp.
* **Đơn vị không quy đổi.** Câu "Đơn vị: …" của trang được ghi NGUYÊN VĂN vào
  `df.attrs["unit_note"]` rồi in lên sheet. `--crosscheck` đối chiếu quý
  trùng nhau giữa hai nguồn và in TỈ SỐ; chưa có tỉ số đo được thì đừng nhân
  chia gì hết.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

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


# ── CafeF ───────────────────────────────────────────────────────────────
# Đo 26/08 trên máy user (`--probe-all VCB`): HTTP 200, trang `.../2016/4/…`
# chứa ĐÚNG bốn tiêu đề `Quý 1-2016 … Quý 4-2016`. Tức **một trang = 4 quý
# của năm xin**, nên lấy 2015-2016 là hai lượt tải, không phải tám.
CAFEF_BS_URL = ("https://cafef.vn/du-lieu/bao-cao-tai-chinh/{ticker_lower}/"
                "bsheet/{year}/{quarter}/0/0/bao-cao-tai-chinh-.chn")
# Đường cũ, để dành nếu đường trên đổi. `s.cafef.vn` chuyển hướng sang đường
# trên (thấy trong `URL cuối` của lần đo 26/08).
CAFEF_BS_URL_LEGACY = ("https://s.cafef.vn/bao-cao-tai-chinh/{ticker}/BSheet/"
                       "{year}/{quarter}/0/0/bao-cao-tai-chinh-.chn")

CAFEF_RATE_LIMIT_S = 1.5   # lịch sự: 26 ngân hàng × 2 trang = 52 lượt

_CAFEF_QUARTER_PATTERNS = (
    re.compile(r"Quý\s*([1-4])\s*[-/]\s*(20\d{2})", re.I),
    re.compile(r"Q([1-4])\s*[-/]\s*(20\d{2})", re.I),
)
_UNIT_RE = re.compile(r"Đơn\s*vị\s*[:：]?\s*([^<\n\r|]{1,40})", re.I)


def cafef_quarters_in(html: str) -> list:
    """Các kỳ `(năm, quý)` NHÌN THẤY trong trang — dò tiêu đề, không bóc số."""
    found = set()
    for pat in _CAFEF_QUARTER_PATTERNS:
        for m in pat.finditer(html or ""):
            found.add((int(m.group(2)), int(m.group(1))))
    return sorted(found)


def cell_quarter(text) -> "tuple | None":
    """Ô tiêu đề này là một KỲ? → (năm, quý), không thì None."""
    for pat in _CAFEF_QUARTER_PATTERNS:
        m = pat.search(str(text or ""))
        if m:
            return (int(m.group(2)), int(m.group(1)))
    return None


def cafef_unit_note(html: str) -> "str | None":
    """Câu "Đơn vị: Triệu VNĐ" trong trang — GHI LẠI, không quy đổi.

    Quy đổi hộ là cách chắc chắn nhất để sai một bậc nghìn mà bảng vẫn nhìn
    hợp lý. Ghi nguyên văn vào sheet, để người đọc tự biết mình đang đọc gì.
    """
    m = _UNIT_RE.search(html or "")
    if not m:
        return None
    note = re.sub(r"\s+", " ", m.group(1)).strip(" .:;")
    return note or None


# ── Bóc bảng bằng THƯ VIỆN CHUẨN ────────────────────────────────────────
# `lxml`/`html5lib`/`bs4` đều KHÔNG có trong `requirements.txt`, nên không
# được phép dựa vào. `html.parser` có sẵn ở mọi máy.
class _TableParser(HTMLParser):
    """Bóc mọi `<table>` thành [{attrs, rows:[[ô, …]]}] — chịu được HTML bẩn."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack = [], []
        self._row, self._cell = None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append({"attrs": dict(attrs), "rows": []})
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._stack:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._stack:
                self._stack[-1]["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def finish(self) -> list:
        self.close()
        while self._stack:                        # thẻ </table> thiếu
            self.tables.append(self._stack.pop())
        return self.tables


def parse_tables(html: str) -> list:
    """[{'attrs': {...}, 'rows': [[ô, …], …]}] cho từng `<table>` trong trang."""
    parser = _TableParser()
    try:
        parser.feed(html or "")
    except Exception:                             # noqa: BLE001 — HTML bẩn
        pass
    return parser.finish()


def header_periods(row) -> list:
    """[(chỉ số cột, (năm, quý))] cho các ô tiêu đề là KỲ."""
    out = []
    for i, cell in enumerate(row or []):
        qq = cell_quarter(cell)
        if qq is not None:
            out.append((i, qq))
    return out


def pick_balance_table(tables, min_rows: int = 10) -> "dict | None":
    """Bảng nào là bảng cân đối? — bảng có tiêu đề KỲ và nhiều dòng nhất.

    Nhận diện theo HÌNH DẠNG (có ≥2 cột kỳ, đủ dòng), không theo `id`/`class`
    — tên lớp CSS của CafeF đổi lúc nào không ai báo, còn hình dạng thì không.
    """
    best, best_rows = None, 0
    for tb in tables or []:
        rows = tb.get("rows") or []
        if len(rows) < min_rows:
            continue
        hdr = next((r for r in rows[:6] if len(header_periods(r)) >= 2), None)
        if hdr is None:
            continue
        if len(rows) > best_rows:
            best, best_rows = tb, len(rows)
    return best


_NUM_CLEAN_RE = re.compile(r"[^\d,.\-()]")


def parse_vn_number(text):
    """Ô số kiểu CafeF → float. Ô TRỐNG → None (trống ≠ 0).

    Chịu `1,234,567` lẫn `1.234.567`, âm trong ngoặc `(1,234)`. Dấu ngăn
    NGHÌN và dấu THẬP PHÂN phân biệt bằng chỗ đứng: dấu cuối cùng mà theo sau
    KHÔNG phải đúng 3 chữ số thì đó là dấu thập phân.
    """
    s = str(text or "").strip()
    if not s or s in ("-", "--", "N/A", "n/a"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = _NUM_CLEAN_RE.sub("", s).strip("()")
    if s.startswith("-"):
        neg, s = True, s[1:]
    if not s or not any(c.isdigit() for c in s):
        return None
    seps = [(i, c) for i, c in enumerate(s) if c in ",."]
    if seps:
        last_i, _ = seps[-1]
        tail = s[last_i + 1:]
        if len(tail) == 3 and tail.isdigit():
            s = s.replace(",", "").replace(".", "")     # tất cả là dấu nghìn
        else:
            s = s[:last_i].replace(",", "").replace(".", "") + "." + tail
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def cafef_to_frame(html: str, lang: str = "vi"):
    """Trang CafeF → frame hàng=chỉ tiêu, cột=`item` + `2016-Q1`…

    Không nhận ra bảng ⇒ frame RỖNG. Đơn vị của trang gắn vào
    `df.attrs["unit_note"]` NGUYÊN VĂN, không quy đổi.
    """
    import pandas as pd

    table = pick_balance_table(parse_tables(html))
    if table is None:
        return pd.DataFrame()
    rows = table["rows"]
    h_idx = next(i for i, r in enumerate(rows[:6]) if len(header_periods(r)) >= 2)
    periods = header_periods(rows[h_idx])

    items, cols = [], {qq: [] for _, qq in periods}
    seen = set()
    for row in rows[h_idx + 1:]:
        if not row:
            continue
        name = str(row[0]).strip()
        if not name or cell_quarter(name) is not None:
            continue
        key = name.lower()
        if key in seen:                      # CafeF lặp lại dòng tổng ở cuối
            continue
        seen.add(key)
        items.append(name)
        for ci, qq in periods:
            cols[qq].append(parse_vn_number(row[ci]) if ci < len(row) else None)

    if not items:
        return pd.DataFrame()
    df = pd.DataFrame({"item": items,
                       **{f"{y}-Q{q}": cols[(y, q)] for (y, q) in
                          sorted(cols)}})
    df.attrs["unit_note"] = cafef_unit_note(html)
    return df


def merge_frames(frames):
    """Ghép nhiều frame cùng dạng theo CỘT KỲ, giữ thứ tự chỉ tiêu của frame đầu.

    Chỉ tiêu chỉ có ở frame sau vẫn được nối vào cuối — bỏ đi là mất số.
    """
    import pandas as pd

    live = [f for f in frames if f is not None and not f.empty]
    if not live:
        return pd.DataFrame()
    if len(live) == 1:
        return live[0]

    order, seen = [], set()
    for f in live:
        for name in f["item"]:
            if name not in seen:
                seen.add(name)
                order.append(name)

    out = {"item": order}
    unit = None
    for f in live:
        unit = unit or f.attrs.get("unit_note")
        lut = {row["item"]: row for _, row in f.iterrows()}
        for col in f.columns:
            if col == "item" or col in out:
                continue
            out[col] = [lut[n][col] if n in lut else None for n in order]
    period_cols = sorted((c for c in out if c != "item"),
                         key=lambda c: (int(c[:4]), int(c[-1])))
    df = pd.DataFrame({"item": order, **{c: out[c] for c in period_cols}})
    df.attrs["unit_note"] = unit
    return df


def fetch_cafef(ticker: str, year: int, quarter: int = 4,
                timeout: float = HTTP_TIMEOUT_S, legacy: bool = False):
    """(status_code, text, url) — không ném, để probe còn in được lý do."""
    import requests

    tpl = CAFEF_BS_URL_LEGACY if legacy else CAFEF_BS_URL
    url = tpl.format(ticker=ticker.upper(), ticker_lower=ticker.lower(),
                     year=year, quarter=quarter)
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    except Exception as exc:                      # noqa: BLE001 — probe báo cáo
        return None, f"{type(exc).__name__}: {exc}", url
    return resp.status_code, resp.text, resp.url


class CafefFetchError(RuntimeError):
    """KHÔNG tải được trang — khác hẳn tải được mà không bóc ra bảng.

    Hai chuyện này cần hai cách chữa khác nhau (đổi URL/mạng vs sửa bộ bóc),
    nên gộp chúng thành "rỗng" là đẩy người đọc đi sai đường. Vết 26/08: bản
    đầu nuốt cả hai, rồi gợi ý "hỏng ở bước bóc bảng" ngay cả khi thật ra
    proxy chặn ở bước tải.
    """


def fetch_cafef_years(ticker: str, years, lang: str = "vi",
                      pause_s: float = CAFEF_RATE_LIMIT_S):
    """Bảng cân đối nhiều NĂM — mỗi năm một trang (`quý=4` ⇒ đủ Q1…Q4).

    Tải hỏng ⇒ ném `CafefFetchError` kèm mã HTTP. Tải được mà bóc ra rỗng ⇒
    trả frame RỖNG (đó mới là lỗi bộ bóc).
    """
    import time

    import pandas as pd

    frames, problems, got_page = [], [], False
    for i, y in enumerate(sorted(set(years))):
        if i:
            time.sleep(pause_s)
        status, text, url = fetch_cafef(ticker, y, 4)
        if status != 200:
            problems.append(f"{y}: {'HTTP ' + str(status) if status else text}")
            continue
        got_page = True
        f = cafef_to_frame(text, lang)
        if not f.empty:
            frames.append(f)
    if not got_page:
        raise CafefFetchError(f"{ticker}: không tải được trang nào — "
                              + " · ".join(problems)[:200])
    return merge_frames(frames) if frames else pd.DataFrame()
