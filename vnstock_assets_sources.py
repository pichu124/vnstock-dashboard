#!/usr/bin/env python3
"""vnstock_assets_sources.py — nguồn PYTHON cho kho đa tài sản (vàng · dầu · USD), P1 (U82).

Hàm THUẦN (parse) + hàm gọi mạng mỏng (fetch) cho từng nguồn đã đo sống trên 🖥️ desktop
09/10 (`scripts/probe_assets.py`, `scripts/probe_nowcast.py`; thiết kế
`docs/THIET-KE-DA-TAI-SAN.md` §4b–§4e). Không ghi kho — `vnstock_assets` gộp và ghi.

Mọi lượt gọi mạng đi qua MỘT chỗ `HTTP(method, url, ...) -> (status, text)` để test tiêm
giả (conftest đặt nó ném lỗi cho MỌI test — không test nào được ra mạng thật).

Nguồn: FRED (Brent/WTI giao ngay EIA, chỉ số USD rộng) · Yahoo chart (HĐTL tháng gần, mã
tháng `.NYM` cho đường cong, DXY, VND=X — KHÔNG chính thức) · gold-api.com (vàng giao
ngay) · er-api + currency-api (USD/VND tham chiếu; currency-api bản theo NGÀY cho chỉ số
USD rộng tự tính) · vietcombank.com.vn api · sjc.com.vn · trang trọng số H.10 của Fed ·
`vnstock_data` mbk (tỷ giá trung tâm, gói Golden — có thì dùng).
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT_S = 15
VN_TZ = timezone(timedelta(hours=7))


def _requests_http(method: str, url: str, *, params=None, data=None, headers=None,
                   timeout: int = TIMEOUT_S) -> "tuple[int, str]":
    import requests
    h = {"User-Agent": UA}
    h.update(headers or {})
    if method == "POST":
        r = requests.post(url, data=data, headers=h, timeout=timeout)
    else:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
    return r.status_code, r.text


HTTP = _requests_http                     # conftest thay bằng hàm ném lỗi

_KEY_RE = re.compile(r"(api_key|apikey|key|token)=([^&\s'\"]+)", re.I)


def scrub(msg, secrets: "tuple[str, ...]" = ()) -> str:
    """Lỗi requests chứa nguyên URL (kể cả api_key) — xoá, rút về NGUYÊN NHÂN."""
    s = str(msg)
    m = re.search(r"Caused by (.+)$", s, re.S)
    if m:
        s = re.sub(r"\s+", " ", re.sub(r"[()'\"]+", " ", m.group(1))).strip()
    for sec in secrets:
        if sec:
            s = s.replace(sec, "***")
    return _KEY_RE.sub(lambda mm: f"{mm.group(1)}=***", s)[:200]


def num(v) -> "float | None":
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def iso(d) -> "str | None":
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    s = str(d).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)                 # DD/MM/YYYY
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def _ok(status: int, text: str) -> str:
    if status != 200:
        snippet = re.sub(r"\s+", " ", text or "")[:80]
        raise RuntimeError(f"HTTP {status}: {snippet}")
    return text


# ── FRED ─────────────────────────────────────────────────────────────────────
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def parse_fred(payload) -> "list[tuple[str, float]]":
    """[(ngày, giá trị)] theo thứ tự payload; bỏ ô '.' (ngày nghỉ)."""
    out = []
    for o in (payload or {}).get("observations") or []:
        v, d = num(o.get("value")), iso(o.get("date"))
        if v is not None and d:
            out.append((d, v))
    return out


def fetch_fred(series_id: str, api_key: str, *, limit: int = 10,
               start: "str | None" = None) -> "list[tuple[str, float]]":
    """Mới nhất trước (limit) — hoặc cả chuỗi từ `start` (backfill)."""
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    if start:
        params.update(observation_start=start, sort_order="asc", limit=100000)
    else:
        params.update(sort_order="desc", limit=limit)
    st, txt = HTTP("GET", FRED_BASE, params=params, timeout=TIMEOUT_S * 2)
    return sorted(parse_fred(json.loads(_ok(st, txt))))


# ── Yahoo chart (không chính thức) ──────────────────────────────────────────
def parse_yahoo(payload) -> "list[dict]":
    """[{date, open, high, low, close}] — ngày theo giờ sàn (gmtoffset)."""
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError(str((chart["error"] or {}).get("description") or chart["error"])[:100])
    res = (chart.get("result") or [None])[0] or {}
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    out = []
    for i, t in enumerate(ts):
        c = num((q.get("close") or [None] * len(ts))[i])
        if c is None:
            continue
        d = datetime.fromtimestamp(int(t) + off, tz=timezone.utc).date().isoformat()
        out.append({"date": d, "close": c,
                    **{k: num((q.get(k) or [None] * len(ts))[i]) for k in ("open", "high", "low")}})
    if not out:
        raise ValueError("chart rỗng")
    return out


def fetch_yahoo(sym: str, rng: str = "5d") -> "list[dict]":
    """`rng="max"` dùng period1=0…bây giờ — đúng dạng đã đo sống trên 🖥️ 09/10 (từ 1971 cho
    DX-Y.NYB); `range=max` có lúc trả nến thưa hơn nến ngày."""
    base = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}"
    if rng == "max":
        url = f"{base}?period1=0&period2={int(datetime.now(timezone.utc).timestamp())}&interval=1d"
    else:
        url = f"{base}?range={rng}&interval=1d"
    st, txt = HTTP("GET", url, timeout=TIMEOUT_S * (3 if rng == "max" else 1))
    return parse_yahoo(json.loads(_ok(st, txt)))


MONTH_CODES = "FGHJKMNQUVXZ"


def contract_tickers(root: str, today: date, n: int = 8, suffix: str = ".NYM") -> "list[str]":
    """Mã Yahoo n tháng giao hàng tính từ tháng hiện tại, vd CLX26.NYM (đo 09/10: sống)."""
    out = []
    for k in range(n):
        m0 = today.month - 1 + k
        y, m = today.year + m0 // 12, m0 % 12 + 1
        out.append(f"{root}{MONTH_CODES[m - 1]}{y % 100:02d}{suffix}")
    return out


def contract_month(ticker: str) -> "str | None":
    """'BZZ26.NYM' → '2026-12' (sắp xếp đường cong theo tháng giao hàng)."""
    m = re.match(r"^[A-Z]{2}([FGHJKMNQUVXZ])(\d{2})", ticker or "")
    if not m:
        return None
    return f"20{m.group(2)}-{MONTH_CODES.index(m.group(1)) + 1:02d}"


# ── Vàng giao ngay + USD/VND tham chiếu ──────────────────────────────────────
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
ER_API_URL = "https://open.er-api.com/v6/latest/USD"
FX_LATEST_URLS = ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
                  "https://latest.currency-api.pages.dev/v1/currencies/usd.json")
FX_DAY_URLS = ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.json",
               "https://{d}.currency-api.pages.dev/v1/currencies/usd.json")


def fetch_gold_api() -> float:
    st, txt = HTTP("GET", GOLD_API_URL)
    v = num((json.loads(_ok(st, txt)) or {}).get("price"))
    if v is None:
        raise ValueError("payload không có price")
    return v


def fetch_er_api_vnd() -> float:
    st, txt = HTTP("GET", ER_API_URL)
    v = num(((json.loads(_ok(st, txt)) or {}).get("rates") or {}).get("VND"))
    if v is None:
        raise ValueError("payload không có VND")
    return v


def parse_usd_rates(payload) -> "dict[str, float]":
    """currency-api: {"usd": {"eur": 0.86, "vnd": 25881, …}} → đơn vị ngoại tệ / 1 USD."""
    usd = (payload or {}).get("usd") if isinstance(payload, dict) else None
    return {k.lower(): float(v) for k, v in (usd or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}


def _first_ok_dated(urls) -> "tuple[str | None, dict]":
    """(ngày GHI TRONG file, tỷ giá) — file "latest" lúc 01:00 VN vẫn là file hôm qua."""
    last = None
    for url in urls:
        try:
            st, txt = HTTP("GET", url)
            payload = json.loads(_ok(st, txt))
            rates = parse_usd_rates(payload)
            if rates:
                return (iso(payload.get("date")) if isinstance(payload, dict) else None), rates
            last = ValueError("payload rỗng")
        except Exception as e:                                   # noqa: BLE001
            last = e
    raise last or ValueError("không nguồn nào")


def _first_ok(urls) -> dict:
    return _first_ok_dated(urls)[1]


def fetch_fx_latest() -> "dict[str, float]":
    return _first_ok(FX_LATEST_URLS)


def fetch_fx_latest_dated() -> "tuple[str | None, dict[str, float]]":
    return _first_ok_dated(FX_LATEST_URLS)


def fetch_fx_day(d: str) -> "dict[str, float]":
    return _first_ok([u.format(d=d) for u in FX_DAY_URLS])


# ── Vietcombank + SJC trực tiếp (chính thức, tra theo ngày) ──────────────────
VCB_URL = "https://www.vietcombank.com.vn/api/exchangerates"
SJC_URL = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"


def parse_vcb(payload) -> "dict | None":
    """Dòng USD → {cash, transfer, sell} (VND)."""
    for r in (payload or {}).get("Data") or (payload or {}).get("data") or []:
        if isinstance(r, dict) and str(r.get("currencyCode") or r.get("CurrencyCode")).upper() == "USD":
            out = {"cash": num(r.get("cash") or r.get("Cash")),
                   "transfer": num(r.get("transfer") or r.get("Transfer")),
                   "sell": num(r.get("sell") or r.get("Sell"))}
            return out if out["sell"] else None
    return None


def fetch_vcb(d: str) -> dict:
    st, txt = HTTP("GET", VCB_URL, params={"date": d})
    got = parse_vcb(json.loads(_ok(st, txt)))
    if not got:
        raise ValueError("không có dòng USD")
    return got


def _pick_key(row: dict, *needles) -> "str | None":
    for k in row:
        if any(n in str(k).lower() for n in needles):
            return k
    return None


def to_vnd_luong(v: "float | None") -> "float | None":
    """SJC trực tiếp ghi NGHÌN đồng/lượng (đo 09/10: bán 144.800 ⇔ 144,8 tr); số đã là
    đồng (≥ 10 triệu) thì giữ nguyên."""
    if v is None:
        return None
    return v * 1000 if v < 1e7 else v


def parse_sjc(payload) -> "dict | None":
    """Vàng miếng SJC 1 lượng ở TP.HCM (không có thì dòng '1L' đầu, rồi dòng đầu) →
    {buy, sell} ĐỒNG/lượng."""
    rows = (payload or {}).get("data") if isinstance(payload, dict) else payload
    parsed = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        kn, kb = _pick_key(r, "typename", "name", "type"), _pick_key(r, "branch")
        kbuy, ksell = _pick_key(r, "buy"), _pick_key(r, "sell")
        buy = to_vnd_luong(num(r.get(kbuy)) if kbuy else None)
        sell = to_vnd_luong(num(r.get(ksell)) if ksell else None)
        if sell:
            parsed.append({"name": str(r.get(kn) or ""), "branch": str(r.get(kb) or ""),
                           "buy": buy, "sell": sell})
    bars = [r for r in parsed if "1l" in r["name"].lower().replace(" ", "")]
    hcm = [r for r in bars if "hồ chí minh" in r["branch"].lower() or "hcm" in r["branch"].lower()]
    best = (hcm or bars or parsed or [None])[0]
    return {"buy": best["buy"], "sell": best["sell"]} if best else None


def fetch_sjc(d: date) -> dict:
    st, txt = HTTP("POST", SJC_URL, data=f"method=GetSJCGoldPriceByDate&toDate={d:%d/%m/%Y}",
                   headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    got = parse_sjc(json.loads(_ok(st, txt)))
    if not got:
        raise ValueError("không có dòng giá")
    return got


# ── Chỉ số USD rộng: trọng số Fed + chỉ số tự tính + ước tính ────────────────
FED_WEIGHTS_URLS = ("https://www.federalreserve.gov/releases/h10/weights/default.htm",
                    "https://www.federalreserve.gov/releases/h10/weights/")
# Tên dòng bảng trọng số Fed (chữ thường, khớp chuỗi con) → mã currency-api.
FED_COUNTRY_CCY = (
    ("euro", "eur"), ("canada", "cad"), ("japan", "jpy"), ("mexico", "mxn"),
    ("china", "cny"), ("united kingdom", "gbp"), ("switzerland", "chf"),
    ("australia", "aud"), ("sweden", "sek"), ("argentina", "ars"), ("brazil", "brl"),
    ("chile", "clp"), ("colombia", "cop"), ("hong kong", "hkd"), ("india", "inr"),
    ("indonesia", "idr"), ("israel", "ils"), ("korea", "krw"), ("malaysia", "myr"),
    ("philippines", "php"), ("russia", "rub"), ("saudi", "sar"), ("singapore", "sgd"),
    ("taiwan", "twd"), ("thailand", "thb"), ("vietnam", "vnd"),
)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_fed_weights(html: str) -> "tuple[int, dict[str, float]]":
    """(năm, {mã tiền tệ: trọng số chuẩn hoá tổng 1}) — cột NĂM MỚI NHẤT của bảng có
    ≥20 tiền tệ khớp (đo 09/10: 26/26, năm 2026)."""
    p = _Tables()
    p.feed(html or "")
    for table in p.tables:
        hdr_i = next((i for i, row in enumerate(table)
                      if sum(bool(re.fullmatch(r"\d{4}", c)) for c in row) >= 2), None)
        if hdr_i is None:
            continue
        hdr = table[hdr_i]
        years = {j: int(c) for j, c in enumerate(hdr) if re.fullmatch(r"\d{4}", c)}
        col = max(years, key=years.get)
        raw: dict = {}
        for row in table[hdr_i + 1:]:
            if not row:
                continue
            ccy = next((c for k, c in FED_COUNTRY_CCY if k in row[0].lower()), None)
            j = col + (len(row) - len(hdr))
            v = num(row[j]) if ccy and 0 <= j < len(row) else None
            if ccy and v is not None and ccy not in raw:
                raw[ccy] = v
        if len(raw) >= 20:
            tot = sum(raw.values())
            return years[col], {c: v / tot for c, v in raw.items()}
    raise ValueError("không thấy bảng trọng số có ≥20 tiền tệ")


def fetch_fed_weights() -> "tuple[int, dict[str, float]]":
    last = None
    for url in FED_WEIGHTS_URLS:
        try:
            st, txt = HTTP("GET", url)
            return parse_fed_weights(_ok(st, txt))
        except Exception as e:                                   # noqa: BLE001
            last = e
    raise last or ValueError("không tải được trọng số Fed")


def replica_index(fx_by_date: "dict[str, dict]", weights: "dict[str, float]",
                  max_missing: float = 0.02) -> "dict[str, float]":
    """Chỉ số tự tính nối chuỗi từ 1,0: Δln I = Σ w_c·ln(e_c,t / e_c,t−1), e = ngoại tệ / 1 USD
    (USD mạnh lên ⇒ tăng, đúng chiều Fed). Ngày thiếu > max_missing trọng số ⇒ bỏ ngày."""
    out, level, prev = {}, 1.0, None
    for d in sorted(fx_by_date):
        rates = fx_by_date[d] or {}
        if prev is None:
            if sum(w for c, w in weights.items() if c in rates) >= 1 - max_missing:
                out[d], prev = level, rates
            continue
        have = {c: w for c, w in weights.items() if c in rates and c in prev}
        tot = sum(have.values())
        if tot < 1 - max_missing:
            continue
        level *= math.exp(sum(w / tot * math.log(rates[c] / prev[c]) for c, w in have.items()))
        out[d], prev = level, rates
    return out


def nowcast(official: "dict[str, float]", driver: "dict[str, float]",
            shift: int = 0) -> "dict | None":
    """Neo số chính thức MỚI NHẤT có chuỗi dẫn ở ngày (neo + shift), nhân biến động dẫn tới
    điểm dẫn mới nhất. `h` = số điểm dẫn sau điểm neo (đếm phiên)."""
    if not official or not driver:
        return None
    last = max(driver)
    for t0 in sorted(official, reverse=True):
        d0 = (date.fromisoformat(t0) + timedelta(days=shift)).isoformat()
        if d0 in driver and driver[d0]:
            h = sum(1 for d in driver if d0 < d <= last)
            return {"anchor_date": t0, "anchor": official[t0], "driver_from": d0,
                    "driver_date": last, "h": h,
                    "value": official[t0] * driver[last] / driver[d0]}
    return None


# ── vnstock_data (gói Golden) — tỷ giá trung tâm lịch sử ─────────────────────
def parse_mbk_central(df) -> "list[tuple[str, float]]":
    """DataFrame Macro(mbk).exchange_rate dạng dài: dòng tên chứa 'trung tâm' → (ngày, giá)."""
    try:
        cols = {str(c).lower(): c for c in df.columns}
        cn, cv = cols.get("name"), cols.get("value")
        cd = next((cols[k] for k in ("last_updated", "date", "time", "report_date") if k in cols), None)
        if cn is None or cv is None or cd is None:
            return []
        out = {}
        for _, r in df.iterrows():
            if "trung tâm" in str(r[cn]).lower():
                d, v = iso(r[cd]), num(r[cv])
                if d and v and v > 1000:
                    out[d] = v
        return sorted(out.items())
    except Exception:                                            # noqa: BLE001
        return []


def _next_weekday(d: str) -> str:
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x.isoformat()


def shift_mbk_dates(rows: "list[tuple[str, float]]") -> "list[tuple[str, float]]":
    """mbk ghi tỷ giá trung tâm của ngày D vào NGÀY LỊCH D−1 — chốt 🖥️ 10/10 bằng bản thô: số
    dòng theo thứ T2 535 · T3 538 · T4 537 · T5 537 · T6 502 · T7 1 · CN 532 (dòng CN = số thứ
    Hai; dòng T6 = "thứ Bảy" = số thứ Sáu giữ nguyên). Tail thô 30/09 25.624 · 01/10 25.636 ·
    02/10 25.636 · CN 04/10 25.643 · 05/10 25.645 · 06/10 25.638 · 07/10 25.634 · 08/10 25.629
    = NHNN 01/10 · 02/10 · (T7) · 05/10 · 06/10 · 07/10 · 08/10 · 09/10 (chuỗi báo chí tăng/giảm
    liền mạch: 25.624 → +12 → +7 → +2 → −7 → −4 → −5). Sau khi dời, so giá tham khảo NHNN 61
    phiên: giả thuyết đúng ngày khớp 59/61 (`vnstock_assets.verify_central`).

    Dời giá ở ngày d sang NGÀY LÀM VIỆC kế tiếp CÓ trong chuỗi mbk (qua được nghỉ lễ); dòng
    cuối ⇒ ngày làm việc kế tiếp theo lịch. Hai dòng cùng đích ⇒ dòng ghi SAU thắng (dòng CN —
    số thứ Hai — đè dòng thứ Sáu/thứ Bảy mang số thứ Sáu)."""
    import bisect
    rows = sorted(rows)
    work = [d for d, _ in rows if date.fromisoformat(d).weekday() < 5]
    out: dict = {}
    for d, v in rows:
        i = bisect.bisect_right(work, d)
        out[work[i] if i < len(work) else _next_weekday(d)] = v
    return sorted(out.items())


def fetch_mbk_central(start: str, end: str, *, shift: bool = True) -> "list[tuple[str, float]]":
    """Rỗng khi máy không có vnstock_data (laptop/CI) — nguồn phụ, không bắt buộc. Ngày đã
    dời về đúng phiên (`shift_mbk_dates`); `shift=False` trả bản thô (backfill in để soi)."""
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import vnstock_auth  # noqa: F401  (nạp .env + nhận gói sponsor như cả repo)
            from vnstock_data.explorer.mbk.macro import Macro
            df = Macro().exchange_rate(start=start, end=end, period="day")
    except Exception:                                            # noqa: BLE001
        return []
    rows = parse_mbk_central(df)
    return shift_mbk_dates(rows) if shift else rows


def fred_key() -> str:
    return (os.environ.get("FRED_API_KEY") or "").strip()
