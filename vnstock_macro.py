#!/usr/bin/env python3
"""vnstock_macro.py — Theo dõi vĩ mô (lãi suất, tỷ giá, CPI/IIP, PMI) cho AI brief.

Tại sao có module này
---------------------
Block "🔧 Đề xuất bổ sung" của brief từ lâu vẫn liệt kê *tin VĨ MÔ — lãi suất /
tỷ giá* là thứ THIẾU (xem `vnstock_brief` template + ghi chú trong
`vnstock_events`: "tin VĨ MÔ ... chưa tích hợp"). Module này lấp đúng khoảng
trống đó: theo dõi một rổ nhỏ chỉ số vĩ mô cốt lõi — **tỷ giá USD/VND**,
**lãi suất điều hành SBV**, **lãi suất liên ngân hàng** — cache lại theo ngày,
phát hiện THAY ĐỔI (để "đón đầu" biến động), và để brief nạp nhanh.

Chiến lược lấy dữ liệu (HYBRID — auto + ghi đè tay)
--------------------------------------------------
* **Tỷ giá USD/VND**: auto-fetch best-effort từ API FX miễn phí (không cần key).
  Khi mạng bị chặn (egress allowlist của web session) hoặc API lỗi → GIỮ cache
  cũ, KHÔNG bao giờ hiện số bịa.
* **Lãi suất điều hành SBV**: đổi vài lần/năm → seed giá trị đã công bố gần nhất
  (có `as_of` + nguồn "seed"), cập nhật tay khi SBV ra quyết định mới.
* **Lãi suất liên ngân hàng ON/1W + lợi suất TPCP 10Y**: auto từ báo cáo tuần
  VBMA (``vnstock_vbma`` — PDF free). Vietstock VNIBOR ĐÃ BỊ TƯỜNG PHÍ ở bản
  Basic — trả ``[]`` (xác minh 2026-06-14); code fetch vẫn còn, bật bằng env
  ``VNSTOCK_MACRO_VIETSTOCK=1`` nếu có tài khoản trả phí.
* **CPI YoY + IIP YoY**: auto từ báo cáo tháng NSO (``vnstock_nso`` — HTML free,
  công bố ~mùng 3 tháng sau). Tắt: ``VNSTOCK_MACRO_NSO=0``.
* **PMI sản xuất VN**: nguồn chính ``--set pmi <số>`` mùng 1-2 hàng tháng (URL
  press-release S&P đổi hash mỗi tháng — không crawler); nguồn phụ regex tiêu
  đề trong RSS cache sẵn có (không fetch mới). Tắt: ``VNSTOCK_MACRO_PMI_NEWS=0``.
* **Cross-check tỷ giá**: er-api vs trung bình mua/bán VCB trong PDF VBMA —
  lệch >2% in cảnh báo + cờ ``fx_crosscheck`` trong cache (hiện ở ``--show``).
* Mọi chỉ số đều có thể GHI ĐÈ TAY: ``python vnstock_macro.py --set <key> <value>``.

Giống `vnstock_foreign_flow`: live fetch cần mạng nên KHÔNG chạy được trong
sandbox; **xác minh trên máy có mạng**::

    python vnstock_macro.py --diag         # thử fetch FX 1 lần, in kết quả
    python vnstock_macro.py --refresh       # cập nhật cache cho pipeline
    python vnstock_macro.py --show          # xem cache hiện tại
    python vnstock_macro.py --set sbv_policy_rate 4.5 --as-of 2024-06-19

Cache: ``data_warehouse/_meta/macro_indicators.json``
  {
    "updated_at": "...ISO...",
    "indicators": {
      "<key>": {"label", "unit", "kind", "source", "history": {date: value}}
    }
  }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "macro_indicators.json"

# Keep per-indicator history small — enough for a trend, not a time series.
_MAX_HISTORY = 60

# Free, no-auth FX endpoints (tried in order). Both return JSON with a USD-based
# rate table containing "VND". Reference/market rate, not the bank board rate —
# good enough to track direction; override with --set for an exact bank rate.
_FX_ENDPOINTS = (
    "https://open.er-api.com/v6/latest/USD",
    "https://api.exchangerate.host/latest?base=USD&symbols=VND",
    # Nấc 3 (2026-07-11, từ khảo sát public-apis — 2 nấc trên cũng nằm trong
    # chính danh mục đó): currency-api của fawazahmed0 — free, KHÔNG rate
    # limit, host CDN, payload {"usd": {"vnd": ...}} chữ thường.
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
    "https://latest.currency-api.pages.dev/v1/currencies/usd.json",
)

# Indicator definitions — TOÀN BỘ metadata hiển thị + pressure nằm ở đây
# (thêm chỉ số mới = thêm 1 entry, KHÔNG nhân if/elif theo kind ở nơi khác):
#   * ``order``    — thứ tự hiển thị
#   * ``decimals`` — số lẻ khi in giá trị (fmt_value)
#   * ``delta_unit`` — đơn vị của THAY ĐỔI tuyệt đối ("điểm %" cho chỉ số %,
#     "điểm" cho index như PMI); fx dùng % tương đối thay vì delta
#   * ``moves``    — (nhãn khi tăng, nhãn khi giảm) dùng cho cả dòng brief lẫn
#     driver của pressure score
#   * ``pressure`` — {mode: "pct"|"delta", scale, min, sign}: đóng góp vào
#     macro_pressure_score = sign × (thay đổi / scale), bỏ qua khi |thay đổi| <
#     min (noise). sign=-1: tăng là BẤT LỢI cho cổ phiếu (lãi suất, tỷ giá,
#     CPI); sign=+1: tăng là THUẬN LỢI (IIP, PMI). Không có ``pressure`` =
#     không phát tín hiệu.
#   * ``seed`` (optional) — baseline đã công bố, ghi 1 lần ở refresh đầu
#     (source="seed", as_of hiển thị rõ); chỉ DELTA mới đẩy sentiment nên seed
#     tĩnh là trung tính.
_RATE_PRESSURE = {"mode": "delta", "scale": 1.0, "min": 0.1, "sign": -1}
_RATE_MOVES = ("lãi suất tăng", "lãi suất giảm")
_DEFS: dict[str, dict] = {
    "usdvnd": {
        "label": "Tỷ giá USD/VND (tham chiếu)",
        "unit": "VND", "kind": "fx", "order": 0, "decimals": 0,
        "moves": ("VND yếu đi", "VND mạnh lên"),
        "pressure": {"mode": "pct", "scale": 2.0, "min": 0.3, "sign": -1},
        # no seed — auto-fetched (or --set); omitted from the brief until present
    },
    "sbv_policy_rate": {
        "label": "Lãi suất tái cấp vốn (SBV)",
        "unit": "%/năm", "kind": "rate", "order": 1, "decimals": 2,
        "moves": _RATE_MOVES, "pressure": _RATE_PRESSURE,
        # SBV cut the refinancing rate to 4.5% on 2023-06-19 and has held it
        # since; seed that as the baseline. CẬP NHẬT TAY khi SBV ra quyết định.
        "seed": {"value": 4.5, "as_of": "2023-06-19"},
    },
    "interbank_on": {
        "label": "Lãi suất liên ngân hàng ON",
        "unit": "%/năm", "kind": "rate", "order": 2, "decimals": 2,
        "moves": _RATE_MOVES, "pressure": _RATE_PRESSURE,
        # auto từ báo cáo tuần VBMA (vnstock_vbma) — free PDF, cadence tuần;
        # --set tay vẫn là đường sống. (Vietstock VNIBOR tường phí — opt-in
        # VNSTOCK_MACRO_VIETSTOCK=1 nếu có tài khoản trả phí.)
    },
    "interbank_1w": {
        "label": "Lãi suất liên ngân hàng 1 tuần",
        "unit": "%/năm", "kind": "rate", "order": 3, "decimals": 2,
        "moves": _RATE_MOVES, "pressure": _RATE_PRESSURE,
        # auto từ VBMA weekly (cùng bảng với ON)
    },
    "govt_bond_yield_2y": {
        "label": "Lợi suất TPCP 2 năm",
        # order 3.5: chen giữa 1W (3) và 10Y (4) — curve ngắn→dài, không renumber
        "unit": "%/năm", "kind": "rate", "order": 3.5, "decimals": 2,
        "moves": _RATE_MOVES, "pressure": _RATE_PRESSURE,
        # auto từ VBMA weekly (cùng ma trận tenor với 10Y, zero request mới) —
        # đầu ngắn của curve; thêm 2026-07-10 (khảo sát VnBondLab, user chốt
        # nới cap registry 10→11 vì cùng nguồn) → gauge dốc 10Y − 2Y.
    },
    "govt_bond_yield_10y": {
        "label": "Lợi suất TPCP 10 năm",
        "unit": "%/năm", "kind": "rate", "order": 4, "decimals": 2,
        "moves": _RATE_MOVES, "pressure": _RATE_PRESSURE,
        # auto từ VBMA weekly — proxy chi phí vốn dài hạn / khẩu vị rủi ro
    },
    "us10y": {
        "label": "Lợi suất TPCP Mỹ 10 năm (US10Y)",
        "unit": "%/năm", "kind": "rate", "order": 4.6, "decimals": 2,
        "moves": ("lợi suất Mỹ tăng", "lợi suất Mỹ giảm"),
        "pressure": _RATE_PRESSURE,      # US yield tăng = hút vốn khỏi EM → bất lợi
        # auto từ FRED DGS10 daily (vnstock_fred, cần FRED_API_KEY free) —
        # thêm 2026-07-11 (khảo sát public-apis, user chốt nới cap 11→13) →
        # gauge chênh lệch VN10Y − US10Y (trụ 3 VnBondLab từng bỏ vì thiếu nguồn)
    },
    "fed_funds": {
        "label": "Lãi suất Fed (effective)",
        "unit": "%/năm", "kind": "rate", "order": 4.8, "decimals": 2,
        "moves": ("Fed thắt chặt", "Fed nới lỏng"),
        "pressure": _RATE_PRESSURE,
        # auto từ FRED DFF daily — có reading là directive brief TỰ NỚI lệnh
        # "cấm bịa Fed" (xem _macro_body_lines)
    },
    "cpi_yoy": {
        "label": "CPI so với cùng kỳ (YoY)",
        "unit": "%", "kind": "pct", "order": 5, "decimals": 2,
        "moves": ("lạm phát tăng", "lạm phát hạ nhiệt"),
        # CPI YoY nhích 0.5 điểm % giữa 2 tháng đã là chuyển biến đáng kể
        "pressure": {"mode": "delta", "scale": 2.0, "min": 0.2, "sign": -1},
        # auto từ báo cáo tháng NSO (vnstock_nso) — công bố ~mùng 3 tháng sau
    },
    "iip_yoy": {
        "label": "Sản xuất công nghiệp IIP (YoY)",
        "unit": "%", "kind": "pct", "order": 6, "decimals": 1,
        "moves": ("sản xuất CN tăng tốc", "sản xuất CN chậm lại"),
        "pressure": {"mode": "delta", "scale": 5.0, "min": 1.0, "sign": 1},
        # auto từ NSO cùng bài với CPI
    },
    "pmi": {
        "label": "PMI sản xuất VN (S&P Global)",
        "unit": "điểm", "kind": "index", "order": 7, "decimals": 1,
        "delta_unit": "điểm",
        "moves": ("PMI cải thiện", "PMI suy yếu"),
        "pressure": {"mode": "delta", "scale": 5.0, "min": 1.0, "sign": 1},
        # URL press-release S&P đổi hash mỗi tháng → KHÔNG crawler; nguồn chính
        # là --set pmi <số> mùng 1-2 hàng tháng, nguồn phụ regex tiêu đề RSS
        # cache sẵn có (_pmi_from_news — không fetch mới).
    },
    "gdp_yoy": {
        "label": "GDP quý (YoY)",
        "unit": "%", "kind": "pct", "order": 8, "decimals": 2,
        "moves": ("tăng trưởng GDP tăng tốc", "tăng trưởng GDP chậm lại"),
        "pressure": {"mode": "delta", "scale": 3.0, "min": 0.3, "sign": 1},
        # auto từ NSO — CHỈ bài quý (4 lần/năm); giữa các quý reading giữ
        # nguyên với as_of cũ (staleness hiện rõ trong brief)
    },
    "trade_balance": {
        "label": "Cán cân thương mại tháng",
        "unit": "tỷ USD", "kind": "balance", "order": 9, "decimals": 2,
        "delta_unit": "tỷ USD",
        "moves": ("cán cân thương mại cải thiện", "cán cân thương mại xấu đi"),
        "pressure": {"mode": "delta", "scale": 3.0, "min": 0.5, "sign": 1},
        # auto từ NSO — xuất siêu dương / nhập siêu âm; nhập siêu kéo dài =
        # áp lực tỷ giá (liên thông chuỗi VND yếu → NN bán ròng của block)
    },
}

# ── Cache I/O ────────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    try:
        if _CACHE.exists():
            d = json.loads(_CACHE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except (OSError, ValueError):
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=0),
            encoding="utf-8",
        )
    except OSError:
        pass


def _ensure_defs(cache: dict) -> dict:
    """Make sure every defined indicator exists (definitions + optional seed).

    Idempotent: existing history/values are preserved; only missing scaffolding
    and a one-time seed value are added.
    """
    inds = cache.setdefault("indicators", {})
    for key, d in _DEFS.items():
        ind = inds.setdefault(key, {})
        ind["label"] = d["label"]
        ind["unit"] = d["unit"]
        ind["kind"] = d["kind"]
        ind.setdefault("history", {})
        ind.setdefault("source", "")
        seed = d.get("seed")
        if seed and not ind["history"]:
            ind["history"][seed["as_of"]] = float(seed["value"])
            ind["source"] = "seed (cập nhật tay khi đổi)"
    return cache


def _record(cache: dict, key: str, value: float, as_of: str, source: str) -> None:
    """Write one reading into an indicator's per-date history (capped)."""
    inds = cache.setdefault("indicators", {})
    ind = inds.setdefault(key, {})
    ind.setdefault("history", {})[as_of] = float(value)
    ind["source"] = source
    # Trim to the newest _MAX_HISTORY dates.
    hist = ind["history"]
    if len(hist) > _MAX_HISTORY:
        for k in sorted(hist)[: len(hist) - _MAX_HISTORY]:
            hist.pop(k, None)


# ── Live fetch (best-effort) ─────────────────────────────────────────────────


def fetch_usdvnd() -> "float | None":
    """Fetch the USD/VND reference rate from a free FX API. None on any failure
    (no network / host not allowlisted / unexpected payload)."""
    try:
        import requests as _req
    except ImportError:
        return None
    for url in _FX_ENDPOINTS:
        try:
            resp = _req.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        # open.er-api.com → {"rates": {"VND": 25400, ...}}
        # exchangerate.host → {"rates": {"VND": 25400}}
        # currency-api (fawazahmed0) → {"usd": {"vnd": 25400.5}} (chữ thường)
        rates = data.get("rates") if isinstance(data, dict) else None
        vnd = (rates or {}).get("VND") if isinstance(rates, dict) else None
        if vnd is None and isinstance(data, dict):
            usd = data.get("usd")
            vnd = usd.get("vnd") if isinstance(usd, dict) else None
        try:
            v = float(vnd)
            if v > 1000:                      # sanity: USD/VND is tens of thousands
                return round(v, 1)
        except (TypeError, ValueError):
            pass
    return None


# Vietstock macro datafeed — free, no commercial key, but needs a per-session
# anti-forgery (CSRF) handshake: GET a page to obtain cookies + the hidden
# __RequestVerificationToken, then POST it to /data/getdatabynormid. VNIBOR
# (lãi suất liên ngân hàng) lives at normid 66 (the page slug ends "-66").
# Best-effort + fragile by nature (breaks if Vietstock changes markup) → every
# failure returns None and the cache keeps its prior/manual value.
_VS_BASE = "https://finance.vietstock.vn"
_VS_NORM_URL = _VS_BASE + "/data/getdatabynormid"
_VS_INTERBANK_NORMID = 66
_VS_INTERBANK_PAGE = _VS_BASE + f"/vi-mo/du-lieu/lai-suat-lien-ngan-hang-vnibor-{_VS_INTERBANK_NORMID}"
_VS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_VS_HEADERS = {
    "User-Agent": _VS_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
}
_VS_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
# Vietstock renders the token UNQUOTED (value=jzkB…), so accept double/single
# quoted AND bare values (bare value runs until whitespace or '>').
_VAL = r'(?:"([^"]+)"|\'([^\']+)\'|([^\s">]+))'
_VS_VALUE_RE = re.compile(r"value\s*=\s*" + _VAL, re.IGNORECASE)


_VS_TOK_FWD_RE = re.compile(
    r"__RequestVerificationToken\b[^>]{0,300}?value\s*=\s*" + _VAL, re.IGNORECASE)
_VS_TOK_REV_RE = re.compile(
    r"value\s*=\s*" + _VAL + r"[^>]{0,160}?__RequestVerificationToken\b",
    re.IGNORECASE)


def _first_group(m) -> "str | None":
    """First non-empty capture group (the value alternation has 3 branches:
    double-quoted / single-quoted / bare)."""
    return next((g for g in m.groups() if g), None) if m else None


def _extract_token(html: "str | None") -> "str | None":
    """Pull the __RequestVerificationToken value from a Vietstock page.

    Tolerant of attribute order, quote style (incl. UNQUOTED — Vietstock renders
    value=jzkB… without quotes) and element type:
      1. scan each <input> tag for the token name then its value;
      2. name…value anywhere (any element/order);
      3. value…name (reversed order).
    """
    if not html:
        return None
    for m in _VS_INPUT_RE.finditer(html):
        tag = m.group(0)
        if "__RequestVerificationToken" in tag:
            v = _first_group(_VS_VALUE_RE.search(tag))
            if v:
                return v
    for rx in (_VS_TOK_FWD_RE, _VS_TOK_REV_RE):
        v = _first_group(rx.search(html))
        if v:
            return v
    return None
_MS_DATE_RE = re.compile(r"/Date\((\d+)")
# Term/component labels that mean the overnight tenor.
_ON_HINTS = ("qua đêm", "overnight")


def _parse_vs_date(v) -> "str | None":
    """Parse a Vietstock date into ISO. Handles ASP.NET '/Date(ms)/', ISO and
    dd/mm/yyyy; None when unparseable."""
    s = str(v or "")
    m = _MS_DATE_RE.search(s)
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)) / 1000).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        try:
            return datetime.strptime(s[:10], "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None
    return None


def _first_rate_value(row: dict) -> "float | None":
    """A plausible interest-rate number (0 < v < 30 %/năm) from a row's
    value-ish key, else any in-range float in the row."""
    for k, val in row.items():
        if any(t in str(k).lower() for t in ("value", "giá tr", "lãi", "rate")):
            try:
                f = float(val)
                if 0 < f < 30:
                    return round(f, 2)
            except (TypeError, ValueError):
                pass
    for val in row.values():                 # fallback: first in-range float
        try:
            f = float(val)
            if 0 < f < 30:
                return round(f, 2)
        except (TypeError, ValueError):
            pass
    return None


def _first_date(row: dict) -> "str | None":
    for k, val in row.items():
        if any(t in str(k).lower() for t in ("date", "ngày", "time", "term")):
            d = _parse_vs_date(val)
            if d:
                return d
    return None


def extract_interbank_on(js) -> "tuple[float, str] | None":
    """Pull the latest OVERNIGHT (qua đêm) interbank rate from a getdatabynormid
    payload. Heuristic + shape-tolerant (Vietstock's exact schema isn't pinned):
    prefer rows whose term/component label says overnight, else any rate row;
    pick the most recent by date. Returns (value %/năm, as_of ISO) or None.
    """
    rows = js if isinstance(js, list) else (
        js.get("data") if isinstance(js, dict) else None)
    if not isinstance(rows, list):
        return None

    def _is_on(r: dict) -> bool:
        label = " ".join(
            str(r.get(k, "")) for k in r
            if any(t in str(k).lower() for t in ("name", "component", "term", "tenor"))
        ).lower()
        return any(h in label for h in _ON_HINTS) or bool(re.search(r"\bon\b", label))

    dicts = [r for r in rows if isinstance(r, dict)]
    pool = [r for r in dicts if _is_on(r)] or dicts
    best: "tuple[str, float] | None" = None
    for r in pool:
        val = _first_rate_value(r)
        if val is None:
            continue
        d = _first_date(r) or ""
        if best is None or d >= best[0]:
            best = (d, val)
    if best is None:
        return None
    return best[1], (best[0] or datetime.now().date().isoformat())


def fetch_vietstock_norm(normid: int = _VS_INTERBANK_NORMID):
    """POST getdatabynormid after the CSRF handshake. Returns the parsed JSON
    (list/dict) or None on any failure (no requests / blocked / no token)."""
    try:
        import requests as _req
    except ImportError:
        return None
    try:
        s = _req.Session()
        s.headers.update(_VS_HEADERS)
        page = s.get(_VS_INTERBANK_PAGE, timeout=15)
        token = _extract_token(page.text)
        if not token:
            return None
        resp = s.post(
            _VS_NORM_URL,
            data={"normid": normid, "type": "1",
                  "__RequestVerificationToken": token},
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Origin": _VS_BASE, "Referer": _VS_INTERBANK_PAGE},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def trace_vietstock(normid: int = _VS_INTERBANK_NORMID):
    """Verbose step-by-step handshake (for --diag --dump debugging). Prints each
    step's outcome so a failure is pinpointed (GET status / token found? / POST
    status + body). Returns the parsed JSON or None. Never raises."""
    try:
        import requests as _req
    except ImportError:
        print("  • requests chưa cài"); return None
    s = _req.Session()
    s.headers.update(_VS_HEADERS)
    try:
        page = s.get(_VS_INTERBANK_PAGE, timeout=15)
    except Exception as e:                                  # noqa
        print(f"  • GET page LỖI: {type(e).__name__}: {str(e)[:160]}"); return None
    print(f"  • GET {_VS_INTERBANK_PAGE}")
    print(f"    → HTTP {page.status_code}, {len(page.text or '')} bytes, "
          f"content-type={page.headers.get('content-type','?')}")
    print(f"    → cookies: {list(s.cookies.keys())}")
    # Ground truth for the right POST params: dump how the page's own JS calls
    # getdatabynormid (it renders the chart, so it uses the correct payload).
    html = page.text or ""
    hits = list(re.finditer("getdatabynormid", html, re.IGNORECASE))
    if hits:
        print(f"  • call-site 'getdatabynormid' trong page ({len(hits)} lần) — "
              f"gửi tôi mấy dòng này để biết param đúng:")
        for i, mm in enumerate(hits[:2]):
            a, b = max(0, mm.start() - 40), min(len(html), mm.end() + 320)
            print(f"    [{i}] …{html[a:b]!r}…")
    else:
        print("  • KHÔNG thấy 'getdatabynormid' inline (call có thể ở file JS ngoài).")
    token = _extract_token(page.text)
    if not token:
        html = page.text or ""
        present = "__RequestVerificationToken" in html
        print(f"  • token: KHÔNG tách được (chuỗi token có trong HTML: {present}).")
        if present:
            print("  • ngữ cảnh quanh token (gửi tôi 2-3 dòng này để chỉnh parser):")
            for i, mm in enumerate(re.finditer("__RequestVerificationToken", html)):
                if i >= 3:
                    break
                a, b = max(0, mm.start() - 90), min(len(html), mm.end() + 160)
                print(f"    [{i}] …{html[a:b]!r}…")
        else:
            print("    → token nạp bằng JS hoặc bị chặn; cân nhắc đổi nguồn.")
        # Last resort: the anti-forgery cookie token (some setups accept it).
        ck = s.cookies.get("__RequestVerificationToken")
        print(f"  • cookie token khả dụng: {bool(ck)}")
        return None
    print(f"  • token: OK ({len(token)} ký tự)")
    try:
        resp = s.post(_VS_NORM_URL,
                      data={"normid": normid, "type": "1",
                            "__RequestVerificationToken": token},
                      headers={"X-Requested-With": "XMLHttpRequest",
                               "Origin": _VS_BASE, "Referer": _VS_INTERBANK_PAGE},
                      timeout=20)
    except Exception as e:                                  # noqa
        print(f"  • POST LỖI: {type(e).__name__}: {str(e)[:160]}"); return None
    print(f"  • POST {_VS_NORM_URL} (normid={normid})")
    print(f"    → HTTP {resp.status_code}, content-type="
          f"{resp.headers.get('content-type','?')}, {len(resp.text or '')} bytes")
    print(f"    → body 400 ký tự đầu: {(resp.text or '')[:400]!r}")
    try:
        return resp.json()
    except Exception as e:                                  # noqa
        print(f"  • parse JSON LỖI: {type(e).__name__}: {str(e)[:120]}")
        return None


def fetch_interbank_on() -> "tuple[float, str] | None":
    """Latest overnight VNIBOR (value %/năm, as_of ISO) from Vietstock, or None.
    Best-effort end to end — never raises."""
    js = fetch_vietstock_norm(_VS_INTERBANK_NORMID)
    if js is None:
        return None
    try:
        return extract_interbank_on(js)
    except Exception:
        return None


# ── Public mutation API ──────────────────────────────────────────────────────


def refresh(*, as_of: "str | None" = None) -> dict:
    """Ensure indicator scaffolding/seed, then auto-fetch what we can.

    USD/VND is fetched from a free FX API. The overnight interbank rate
    (Vietstock VNIBOR) is PAYWALLED on the free/Basic tier (getdatabynormid
    returns [] — confirmed 2026-06-14), so it is SKIPPED by default; opt in with
    env VNSTOCK_MACRO_VIETSTOCK=1 only if you have a paid Vietstock account.
    Otherwise set lãi suất manually via --set (changes slowly).

    Best-effort: a blocked/failed fetch leaves that indicator's prior cache
    untouched (manual --set values are never clobbered). Returns the cache.
    """
    cache = _ensure_defs(_load_cache())
    day = as_of or datetime.now().date().isoformat()

    fx = fetch_usdvnd()
    if fx is not None:
        _record(cache, "usdvnd", fx, day, "open.er-api.com")

    if os.environ.get("VNSTOCK_MACRO_VIETSTOCK") == "1":   # paid account opt-in
        ib = fetch_interbank_on()                          # (value, as_of)
        if ib is not None:
            ib_val, ib_as_of = ib
            _record(cache, "interbank_on", ib_val, as_of or ib_as_of, "vietstock")

    # VBMA weekly PDF (free): LNH ON/1W + lợi suất TPCP 2Y/10Y. Best-effort —
    # fetch/parse lỗi → None → giữ nguyên cache (kể cả giá trị --set tay).
    # Tắt: VNSTOCK_MACRO_VBMA=0.
    vb = None
    if os.environ.get("VNSTOCK_MACRO_VBMA", "1") != "0":
        vb = _fetch_vbma()
        if vb:
            vb_as_of = vb.get("as_of") or day
            for key in ("interbank_on", "interbank_1w",
                        "govt_bond_yield_2y", "govt_bond_yield_10y"):
                if vb.get(key) is not None:
                    _record(cache, key, float(vb[key]), vb_as_of, "vbma")

    # HNX (SAU VBMA để GHI ĐÈ 2Y/10Y — nguồn NGÀY chính thức, robust hơn PDF
    # tuần). Tắt: VNSTOCK_MACRO_HNX=0 / VNSTOCK_HNX=0. Best-effort.
    if os.environ.get("VNSTOCK_MACRO_HNX", "1") != "0":
        hx = _fetch_hnx()
        if hx:
            hx_as_of = hx.get("as_of") or day
            for key in ("govt_bond_yield_2y", "govt_bond_yield_10y"):
                if hx.get(key) is not None:
                    _record(cache, key, float(hx[key]), hx_as_of, "hnx")

    # SBV weekly (nguồn CHÍNH THỨC thứ 2): LNH ON cross-source với VBMA + OMO
    # ròng (SỐ, không suy từ tin) + tỷ giá trung tâm. Tắt: VNSTOCK_MACRO_SBV=0
    # / VNSTOCK_SBV=0. Best-effort. LNH ON: resolve SBV↔VBMA theo ĐỘ MỚI của
    # DATA (user chốt 17/07 "luôn cập nhật nhất": tuần data mới hơn thắng;
    # cùng tuần → VBMA điểm cuối tuần sát hơn TB tuần SBV; cờ lệch >ngưỡng);
    # OMO/tỷ-giá-trung-tâm lưu display-only (ngoài registry).
    if os.environ.get("VNSTOCK_MACRO_SBV", "1") != "0":
        sb = _fetch_sbv()
        if sb:
            from vnstock_sbv import resolve_interbank_on
            sb_as_of = sb.get("week_end") or sb.get("as_of")
            val, src, diverged = resolve_interbank_on(
                sb.get("overnight"), (vb or {}).get("interbank_on"),
                sbv_as_of=sb_as_of, vbma_as_of=(vb or {}).get("as_of"))
            if val is not None and src == "sbv":
                # Không ghi đè khi registry đã có reading MỚI hơn (vd VBMA fail
                # lượt này nhưng lượt trước đã ghi tuần mới hơn) — giá trị đọc
                # theo ngày mới nhất nên chỉ source label bị sai nếu ghi bừa.
                hist = (((cache.get("indicators") or {}).get("interbank_on")
                         or {}).get("history") or {})
                if not hist or (sb_as_of or day) >= max(hist):
                    _record(cache, "interbank_on", float(val), sb_as_of or day, "sbv")
            cache.setdefault("_meta", {})["sbv"] = {
                "omo_net": sb.get("omo_net"),
                "fx_central": sb.get("fx_central"),
                "interbank_on_diverged": bool(diverged),
                "as_of": sb_as_of,
            }

    # Cross-check chất lượng tỷ giá (mượn rule vimovietnam "2 nguồn chênh >2%"):
    # er-api (market ref, daily) vs trung bình mua/bán Vietcombank trong chính
    # PDF VBMA (weekly). Lệch quá _FX_XCHECK_MAX_PCT → CẢNH BÁO (không tự sửa —
    # kiểm tra nguồn / --set usdvnd); ghi vào cache để --show còn thấy.
    _fx_crosscheck(cache, fx, (vb or {}).get("usdvnd_vcb_mid"), day)

    # FRED (Mỹ): US10Y (DGS10) + Fed funds (DFF) daily — cần FRED_API_KEY
    # free trong .env (không có → fetch_daily trả None, bỏ qua). Mỗi series
    # mang as_of RIÊNG (DGS10 nghỉ cuối tuần/lễ). Tắt: VNSTOCK_MACRO_FRED=0.
    if os.environ.get("VNSTOCK_MACRO_FRED", "1") != "0":
        fr = _fetch_fred()
        if fr:
            for key, (val, f_as_of) in fr.items():
                if key in _DEFS:
                    _record(cache, key, float(val), f_as_of or day, "fred")

    # NSO monthly (free HTML): CPI YoY + IIP YoY từ báo cáo KTXH tháng
    # (công bố ~mùng 3 tháng sau). Tắt: VNSTOCK_MACRO_NSO=0.
    if os.environ.get("VNSTOCK_MACRO_NSO", "1") != "0":
        ns = _fetch_nso()
        if ns:
            ns_as_of = ns.get("as_of") or day
            for key in ("cpi_yoy", "iip_yoy", "gdp_yoy", "trade_balance"):
                if ns.get(key) is not None:
                    _record(cache, key, float(ns[key]), ns_as_of, "nso")

    # PMI: regex tiêu đề trong RSS cache SẴN CÓ (không fetch mới) — nguồn phụ
    # cho --set tay. Chỉ ghi khi tin MỚI HƠN reading hiện có (không đè --set).
    # Tắt: VNSTOCK_MACRO_PMI_NEWS=0.
    if os.environ.get("VNSTOCK_MACRO_PMI_NEWS", "1") != "0":
        pm = _pmi_from_news()
        if pm:
            pmi_val, pmi_as_of = pm
            hist = ((cache.get("indicators") or {}).get("pmi") or {}).get("history") or {}
            if not hist or pmi_as_of > max(hist):
                _record(cache, "pmi", pmi_val, pmi_as_of, "news-rss")

    _save_cache(cache)
    return cache


# Ngưỡng cảnh báo lệch tỷ giá giữa 2 nguồn độc lập (%).
_FX_XCHECK_MAX_PCT = 2.0


def _fx_crosscheck(cache: dict, er_api: "float | None",
                   vcb_mid: "float | None", day: str) -> None:
    """So er-api với VCB mid (từ VBMA); lệch > ngưỡng → in cảnh báo + lưu
    ``cache["fx_crosscheck"]``; trong ngưỡng/thiếu 1 nguồn → xoá cờ cũ."""
    if er_api is None or not vcb_mid:
        return
    dev = (er_api - vcb_mid) / vcb_mid * 100.0
    if abs(dev) > _FX_XCHECK_MAX_PCT:
        cache["fx_crosscheck"] = {
            "date": day, "er_api": er_api, "vbma_vcb_mid": vcb_mid,
            "diff_pct": round(dev, 2),
        }
        print(f"[macro] ⚠ tỷ giá er-api {er_api:,.0f} lệch {dev:+.1f}% so với "
              f"VCB mua/bán trung bình {vcb_mid:,.0f} (VBMA) — kiểm tra nguồn "
              f"FX hoặc --set usdvnd.")
    else:
        cache.pop("fx_crosscheck", None)


def _fetch_nso() -> "dict | None":
    """CPI/IIP tháng qua vnstock_nso.fetch_monthly() — mọi lỗi → None."""
    try:
        from vnstock_nso import fetch_monthly
        return fetch_monthly()
    except Exception:
        return None


# Tiêu đề PMI của THỊ TRƯỜNG KHÁC (Mỹ/TQ/EU…) không được nhận nhầm là PMI VN.
_PMI_FOREIGN = ("mỹ", "hoa kỳ", "trung quốc", "eurozone", "châu âu", "nhật",
                "hàn quốc", "asean", "toàn cầu", "global", "caixin", "ism")
# Neo "XX,X điểm" (tiêu đề PMI hầu như luôn ghi "… đạt 48,9 điểm") thay vì đo
# khoảng cách tới chữ PMI — giữa chúng thường có chữ số khác ("tháng 6/2026").
_PMI_RE = re.compile(r"(\d{2}[.,]\d{1,2})\s*điểm")


def _pmi_from_news() -> "tuple[float, str] | None":
    """(giá trị, ngày ISO) PMI VN mới nhất regex được từ tiêu đề trong
    ``market_news_cache.json`` (vd "PMI Việt Nam tháng 6 đạt 52,8 điểm").
    Deterministic, không fetch mạng; None khi cache thiếu/không có tin."""
    try:
        from vnstock_news_feeds import _load_cache as _load_news
        items = _load_news()
    except Exception:
        return None
    best: "tuple[float, str] | None" = None
    for it in items or []:
        title = (it.get("title") or "").strip()
        low = title.lower()
        if "pmi" not in low or any(k in low for k in _PMI_FOREIGN):
            continue
        m = _PMI_RE.search(title)
        if not m:
            continue
        v = float(m.group(1).replace(",", "."))
        if not 25.0 <= v <= 75.0:                   # sanity: PMI quanh mốc 50
            continue
        d = (it.get("_date_sort") or "")[:10]
        if d and (best is None or d > best[1]):
            best = (v, d)
    return best


def _fetch_vbma() -> "dict | None":
    """Báo cáo tuần VBMA qua vnstock_vbma.fetch_weekly() — mọi lỗi → None."""
    try:
        from vnstock_vbma import fetch_weekly
        return fetch_weekly()
    except Exception:
        return None


def _fetch_fred() -> "dict | None":
    """US10Y + Fed funds qua vnstock_fred.fetch_daily() — mọi lỗi → None."""
    try:
        from vnstock_fred import fetch_daily
        return fetch_daily()
    except Exception:
        return None


def _fetch_sbv() -> "dict | None":
    """Bản tin tuần SBV qua vnstock_sbv.refresh() — LNH ON/1W + OMO ròng +
    tỷ giá trung tâm. Mọi lỗi → None (best-effort)."""
    try:
        import vnstock_sbv
        return vnstock_sbv.refresh()
    except Exception:
        return None


def _fetch_hnx() -> "dict | None":
    """Lợi suất TPCP 2Y/10Y từ HNX (vnstock_hnx) — nguồn NGÀY chính thức,
    ưu tiên hơn VBMA PDF tuần. Trả {'govt_bond_yield_2y','govt_bond_yield_10y',
    'as_of'} hoặc None. Mọi lỗi → None (best-effort)."""
    try:
        import vnstock_hnx
        got = vnstock_hnx.refresh()          # fetch + ghi history cache riêng
        if not got:
            got = (vnstock_hnx.load_yields() or (None, None))[1]  # fallback cache
        if not got:
            return None
        loaded = vnstock_hnx.load_yields()
        out = {}
        if got.get("2Y") is not None:
            out["govt_bond_yield_2y"] = float(got["2Y"])
        if got.get("10Y") is not None:
            out["govt_bond_yield_10y"] = float(got["10Y"])
        if out and loaded:
            out["as_of"] = loaded[0]
        return out or None
    except Exception:
        return None


def set_value(key: str, value: float, as_of: "str | None" = None) -> dict:
    """Manual override for any indicator (always works, no network)."""
    if key not in _DEFS:
        raise KeyError(f"Chỉ số không hợp lệ: {key!r}. Hợp lệ: {', '.join(_DEFS)}")
    cache = _ensure_defs(_load_cache())
    day = as_of or datetime.now().date().isoformat()
    _record(cache, key, float(value), day, "manual")
    _save_cache(cache)
    return cache


# ── Read / derive ────────────────────────────────────────────────────────────


def _pick(history: dict, effective_date: "str | None") -> "tuple | None":
    """Return (as_of, value, prev_as_of, prev_value) for an indicator.

    A rate/FX level is a STATE (not a daily flow like NN ròng), so the last
    known reading on-or-before ``effective_date`` is meaningful — we surface it
    with its as_of so staleness is always visible, rather than dropping it the
    way the foreign-flow loader drops a missing exact day. ``prev_*`` is the
    reading before it (for change detection); None when only one reading exists.
    """
    if not history:
        return None
    dates = sorted(history)
    if effective_date:
        usable = [d for d in dates if d <= effective_date]
        chosen = usable[-1] if usable else dates[0]
    else:
        chosen = dates[-1]
    idx = dates.index(chosen)
    prev = dates[idx - 1] if idx > 0 else None
    return (
        chosen, float(history[chosen]),
        prev, (float(history[prev]) if prev is not None else None),
    )


def load_macro(effective_date: "str | None" = None) -> list[dict]:
    """Current macro indicators (only those with a reading), each with change.

    Returns a list sorted by ``_DEFS`` order:
      {key, label, unit, kind, value, as_of, source,
       change: {delta, pct, dir} | None, prev_value, prev_as_of}
    ``dir`` is +1 / -1 / 0. Empty list when the cache holds no readings.
    """
    cache = _load_cache()
    inds = (cache.get("indicators") or {})
    out: list[dict] = []
    for key in sorted(_DEFS, key=lambda k: _DEFS[k].get("order", 99)):
        ind = inds.get(key) or {}
        picked = _pick(ind.get("history") or {}, effective_date)
        if picked is None:
            continue
        as_of, value, prev_as_of, prev_value = picked
        change = None
        if prev_value is not None:
            delta = round(value - prev_value, 4)
            pct = round(delta / prev_value * 100, 2) if prev_value else None
            change = {"delta": delta, "pct": pct,
                      "dir": (1 if delta > 0 else (-1 if delta < 0 else 0))}
        out.append({
            "key": key,
            "label": ind.get("label") or _DEFS[key]["label"],
            "unit": ind.get("unit") or _DEFS[key]["unit"],
            "kind": ind.get("kind") or _DEFS[key]["kind"],
            "source": ind.get("source") or "",
            "value": value, "as_of": as_of,
            "prev_value": prev_value, "prev_as_of": prev_as_of,
            "change": change,
        })
    return out


def _def_for(ind: dict) -> dict:
    """Definition metadata for a load_macro row; kind-based fallback for rows
    built by hand (tests) or left in the cache by a removed definition."""
    d = _DEFS.get(ind.get("key") or "")
    if d:
        return d
    kind = ind.get("kind") or ""
    return {"kind": kind, "decimals": 0 if kind == "fx" else 2,
            "moves": (("VND yếu đi", "VND mạnh lên") if kind == "fx"
                      else _RATE_MOVES),
            "pressure": ({"mode": "pct", "scale": 2.0, "min": 0.3, "sign": -1}
                         if kind == "fx" else _RATE_PRESSURE)}


def fmt_value(ind: dict) -> str:
    """Canonical EN-format value string ('26,219 VND', '5.67%/năm',
    '50.5 điểm') — single source for the CLI and the brief block."""
    d = _def_for(ind)
    unit = ind.get("unit") or ""
    sep = "" if unit.startswith("%") else " "
    return f"{ind['value']:,.{d.get('decimals', 2)}f}{sep}{unit}".rstrip()


def fmt_change(ind: dict) -> "tuple[str, str, str] | None":
    """(arrow, magnitude, hint-label) for a row's change, or None when flat.

    FX renders the RELATIVE move ('+0.30%'); everything else the absolute
    delta with the def's delta_unit ('+0.25 điểm %' / '+1.2 điểm')."""
    ch = ind.get("change")
    if not ch or not ch.get("dir"):
        return None
    d = _def_for(ind)
    arrow = "▲" if ch["dir"] > 0 else "▼"
    if d.get("kind") == "fx" and ch.get("pct") is not None:
        mag = f"{ch['pct']:+.2f}%"
    else:
        mag = f"{ch['delta']:+.2f} {d.get('delta_unit', 'điểm %')}"
    up, down = d.get("moves", ("tăng", "giảm"))
    return arrow, mag, (up if ch["dir"] > 0 else down)


# Chênh lệch thanh khoản (framework Hedge Academy 2026-07-08): lãi suất LNH
# phải đọc TƯƠNG ĐỐI so với lãi suất điều hành — ON cao hơn = ngân hàng vay
# lẫn nhau đắt hơn cả vay SBV = hệ thống CĂNG; ON thấp sâu dưới = dư thừa.
_LIQ_TIGHT_SPREAD = 0.5        # ON − điều hành > +0.5 điểm % → căng
_LIQ_FLUSH_SPREAD = -1.5       # ON − điều hành < −1.5 điểm % → dư thừa


def liquidity_spread(macro: "list[dict] | None") -> "dict | None":
    """Gauge thanh khoản hệ thống DẪN XUẤT từ 2 chỉ số đã có (zero fetch):
    ``{spread, label, dir, slope_10y_on?}`` — spread = ON − lãi suất điều
    hành (điểm %), dir −1 căng / +1 dư thừa / 0 bình thường; slope = 10Y − ON
    (độ dốc curve, có khi đủ data). None khi thiếu ON hoặc lãi suất điều hành.
    Level-gauge thuần hiển thị — KHÔNG vào pressure score (score là change-based).
    """
    rows = {m.get("key"): m for m in (macro or [])}
    on, policy = rows.get("interbank_on"), rows.get("sbv_policy_rate")
    if not on or not policy:
        return None
    spread = round(float(on["value"]) - float(policy["value"]), 2)
    if spread > _LIQ_TIGHT_SPREAD:
        label, d = ("thanh khoản hệ thống CĂNG — LNH cao hơn lãi suất "
                    "điều hành, ngân hàng vay lẫn nhau đắt hơn vay SBV"), -1
    elif spread < _LIQ_FLUSH_SPREAD:
        label, d = "thanh khoản DƯ THỪA — LNH thấp sâu dưới lãi suất điều hành", 1
    else:
        label, d = "thanh khoản bình thường", 0
    out = {"spread": spread, "label": label, "dir": d}
    y10 = rows.get("govt_bond_yield_10y")
    if y10:
        out["slope_10y_on"] = round(float(y10["value"]) - float(on["value"]), 2)
    return out


# Gauge kỳ hạn dẫn xuất (2026-07-10, từ khảo sát VnBondLab/Macro Alert System —
# 2 trong 4 "trụ cột" cảnh báo của nó tính được thuần từ registry, zero fetch):
#   • term spread = 10Y − lãi suất điều hành ("Taylor-rule xấp xỉ"): ÂM/mỏng =
#     chính sách chặt so với kỳ vọng dài hạn → rủi ro chu kỳ.
#   • slope 10Y − 2Y (khi có 2Y từ VBMA): ĐẢO NGƯỢC = thị trường TPCP định giá
#     rủi ro suy giảm; phẳng = cảnh giác cuối chu kỳ.
# LEVEL-gauge thuần hiển thị — KHÔNG vào pressure score (mirror liquidity_spread;
# 2 trụ còn lại của VnBondLab cần US10Y/percentile lịch sử — chưa có nguồn/mẫu).
_TERM_THIN_SPREAD = 0.5        # 10Y − điều hành < +0.5 điểm % → mỏng
_YC_FLAT_SLOPE = 0.3           # 10Y − 2Y < +0.3 điểm % → phẳng


def term_spread(macro: "list[dict] | None") -> "dict | None":
    """Gauge kỳ hạn & đường cong: ``{spread, label, dir, slope_2_10?,
    slope_label?, slope_dir?}`` — spread = 10Y − lãi suất điều hành (điểm %),
    slope = 10Y − 2Y (chỉ khi có 2Y). dir/slope_dir: −1 xấu, 0 bình thường.
    None khi thiếu 10Y hoặc lãi suất điều hành."""
    rows = {m.get("key"): m for m in (macro or [])}
    y10, policy = rows.get("govt_bond_yield_10y"), rows.get("sbv_policy_rate")
    if not y10 or not policy:
        return None
    spread = round(float(y10["value"]) - float(policy["value"]), 2)
    if spread < 0:
        label, d = ("ÂM — lợi suất 10Y dưới lãi suất điều hành, chính sách "
                    "THẮT so với kỳ vọng dài hạn (rủi ro chu kỳ)"), -1
    elif spread < _TERM_THIN_SPREAD:
        label, d = "mỏng — chính sách tương đối chặt so với đầu dài", 0
    else:
        label, d = "bình thường", 0
    out = {"spread": spread, "label": label, "dir": d}
    y2 = rows.get("govt_bond_yield_2y")
    if y2:
        slope = round(float(y10["value"]) - float(y2["value"]), 2)
        if slope < 0:
            s_label, s_d = ("ĐẢO NGƯỢC — thị trường TPCP định giá rủi ro "
                            "suy giảm chu kỳ"), -1
        elif slope < _YC_FLAT_SLOPE:
            s_label, s_d = "phẳng — cảnh giác cuối chu kỳ", 0
        else:
            s_label, s_d = "dốc bình thường", 0
        out.update({"slope_2_10": slope,
                    "slope_label": s_label, "slope_dir": s_d})
    return out


# Gauge chênh lệch quốc tế (2026-07-11 — "trụ cột 3" của VnBondLab/Macro Alert
# System, làm được sau khi có us10y từ FRED qua khảo sát public-apis): VN10Y −
# US10Y. ÂM = lợi suất VN kém hấp dẫn hơn Mỹ → vốn ngoại dễ rút (liên thông
# chuỗi VND yếu → NN bán ròng đã có trong block vĩ mô). LEVEL-gauge thuần hiển
# thị — KHÔNG vào pressure score (mirror liquidity_spread/term_spread). Trụ 4
# còn lại của VnBondLab (ngưỡng percentile lịch sử) vẫn để dành chờ đủ mẫu.
_INTL_THIN_SPREAD = 0.5        # 0 ≤ spread < +0.5 điểm % → lợi thế không đáng kể


def intl_spread(macro: "list[dict] | None") -> "dict | None":
    """Gauge chênh lệch quốc tế: ``{spread, label, dir}`` — spread = VN10Y −
    US10Y (điểm %), dir −1 khi ÂM / 0 bình thường. None khi thiếu 1 trong 2."""
    rows = {m.get("key"): m for m in (macro or [])}
    vn, us = rows.get("govt_bond_yield_10y"), rows.get("us10y")
    if not vn or not us:
        return None
    spread = round(float(vn["value"]) - float(us["value"]), 2)
    if spread < 0:
        label, d = ("ÂM — lợi suất VN thấp hơn Mỹ, kém hấp dẫn vốn ngoại "
                    "(áp lực tỷ giá, khối ngoại dễ bán ròng)"), -1
    elif spread < _INTL_THIN_SPREAD:
        label, d = "mỏng — lợi thế lợi suất so với Mỹ không đáng kể", 0
    else:
        label, d = "dương — còn lợi thế lợi suất so với Mỹ", 0
    return {"spread": spread, "label": label, "dir": d}


# Nhắc set PMI từ mùng mấy hàng tháng (mùng 1-2 là ân hạn: S&P công bố ~mùng 1,
# đường RSS tự động thường bắt được trong 1-2 ngày — chỉ nhắc khi CẢ auto trượt).
_PMI_REMIND_FROM_DAY = 3


def pmi_reminder(macro: "list[dict] | None",
                 today: "str | None" = None) -> "str | None":
    """Dòng nhắc khi PMI THÁNG TRƯỚC vẫn chưa vào registry sau ngày công bố.

    Trả None khi: chưa tới mùng ``_PMI_REMIND_FROM_DAY`` (ân hạn cho đường RSS
    tự động), hoặc đã có reading với as_of trong tháng hiện tại (= PMI tháng
    trước đã ghi — news ghi as_of ngày đăng tin đầu tháng, --set mặc định
    as_of hôm nay). Deterministic — dùng cho brief block + CLI --show."""
    from datetime import date as _date
    t = _date.fromisoformat(today) if today else _date.today()
    if t.day < _PMI_REMIND_FROM_DAY:
        return None
    row = next((m for m in (macro or []) if m.get("key") == "pmi"), None)
    if row and (row.get("as_of") or "") >= t.replace(day=1).isoformat():
        return None
    prev_m, prev_y = (t.month - 1, t.year) if t.month > 1 else (12, t.year - 1)
    have = (f" (số đang có: {fmt_value(row)}, tính đến {row['as_of']})"
            if row else "")
    return (f"⏰ PMI tháng {prev_m}/{prev_y} chưa được cập nhật — S&P công bố "
            f"~mùng 1, RSS chưa bắt được{have}. Chạy: "
            f"python vnstock_macro.py --set pmi <số>")


def macro_pressure_score(macro: "list[dict] | None") -> "dict | None":
    """Composite macro pressure on equities from RECENT CHANGES, in [-1, 1].

    Tightening = bearish: rates/CPI rising and/or VND weakening push the score
    negative; easing (or IIP/PMI improving) pushes it positive. Per-indicator
    behaviour comes from ``_DEFS[key]["pressure"]`` (mode/scale/min/sign) —
    adding an indicator never touches this function. Returns
    ``{score, label, dir}`` only when there's a meaningful recent move to react
    to (so a stable macro backdrop doesn't dilute the sentiment composite);
    None otherwise. Levels still show in the brief block regardless.
    """
    if not macro:
        return None
    subs: list[float] = []
    drivers: list[str] = []
    for ind in macro:
        ch = ind.get("change")
        if not ch:
            continue
        d = _def_for(ind)
        cfg = d.get("pressure")
        if not cfg:
            continue
        x = ch.get("pct") if cfg["mode"] == "pct" else ch.get("delta")
        if x is None or abs(x) < cfg["min"]:
            continue
        subs.append(_clamp(cfg["sign"] * x / cfg["scale"]))
        up, down = d.get("moves", ("tăng", "giảm"))
        drivers.append(up if x > 0 else down)
    if not subs:
        return None
    score = _clamp(sum(subs) / len(subs))
    direction = 1 if score > 0.05 else (-1 if score < -0.05 else 0)
    label = ", ".join(dict.fromkeys(drivers))        # dedup, keep order
    if direction < 0:
        label += " (môi trường thắt chặt)"
    elif direction > 0:
        label += " (môi trường nới lỏng)"
    return {"score": round(score, 2), "label": label or "ổn định", "dir": direction}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── Macro news (keyword filter over the existing news cache) ─────────────────

# Lowercased substrings that mark a headline as macro-relevant. Focused to keep
# false positives low (per-ticker corporate news dominates the cache).
_MACRO_KEYWORDS = (
    "lãi suất", "tỷ giá", "usd/vnd", "tỷ giá trung tâm", "ngân hàng nhà nước",
    " sbv", "omo", "tín phiếu", "bơm ròng", "hút ròng", "thanh khoản hệ thống",
    "dự trữ ngoại hối", "lạm phát", " cpi", " fed", "cục dự trữ liên bang",
    "lợi suất", "trái phiếu chính phủ", "điều hành tỷ giá", "điều hành lãi suất",
)


def macro_news(news: "list[dict] | None" = None, days: int = 7,
               limit: int = 5) -> list[dict]:
    """Macro-relevant headlines from the existing news cache (no new fetch).

    Scans titles/summaries for rate/FX/CPI/Fed keywords. Returns up to ``limit``
    recent items as {ticker, date, title}. Empty list when the cache is missing
    or nothing matches.
    """
    try:
        if news is None:
            from vnstock_news import load_news_cache
            news = load_news_cache()
    except Exception:
        return []
    if not news:
        return []
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.today() - _td(days=days)).isoformat()
    out: list[dict] = []
    seen: set[str] = set()
    for item in news:
        d = item.get("_date_sort", "") or ""
        if d and d < cutoff:
            continue
        title = (item.get("news_title") or item.get("title")
                 or item.get("head") or "").strip()
        if not title:
            continue
        summary = (item.get("news_short_content") or "").strip()
        hay = f"{title} {summary}".lower()
        if not any(k in hay for k in _MACRO_KEYWORDS):
            continue
        norm = title.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append({"ticker": item.get("ticker", ""), "date": d, "title": title})
        if len(out) >= limit:
            break
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────


def _show() -> None:
    macro = load_macro()
    if not macro:
        print(f"[macro] cache rỗng ({_CACHE}). Chạy --refresh hoặc --set để khởi tạo.")
        return
    print(f"[macro] {_CACHE}")
    for ind in macro:
        fc = fmt_change(ind)
        chs = f"  ({fc[1]} vs {ind['prev_as_of']})" if fc else ""
        print(f"  • {ind['label']}: {fmt_value(ind)}  (tính đến {ind['as_of']}"
              f", nguồn {ind['source'] or '—'}){chs}")
    p = macro_pressure_score(macro)
    if p:
        print(f"  → Áp lực vĩ mô: {p['label']} (score {p['score']:+.2f})")
    liq = liquidity_spread(macro)
    if liq:
        slope = (f"; dốc 10Y − ON = {liq['slope_10y_on']:+.2f} điểm %"
                 if liq.get("slope_10y_on") is not None else "")
        print(f"  → Thanh khoản: ON − điều hành = {liq['spread']:+.2f} điểm % "
              f"({liq['label']}){slope}")
    ts = term_spread(macro)
    if ts:
        slope = (f"; dốc 10Y − 2Y = {ts['slope_2_10']:+.2f} điểm % "
                 f"({ts['slope_label']})"
                 if ts.get("slope_2_10") is not None else "")
        print(f"  → Kỳ hạn: 10Y − điều hành = {ts['spread']:+.2f} điểm % "
              f"({ts['label']}){slope}")
    intl = intl_spread(macro)
    if intl:
        print(f"  → Quốc tế: VN10Y − US10Y = {intl['spread']:+.2f} điểm % "
              f"({intl['label']})")
    rem = pmi_reminder(macro)
    if rem:
        print(f"  {rem}")
    xc = _load_cache().get("fx_crosscheck")
    if xc:
        print(f"  ⚠ Tỷ giá er-api {xc['er_api']:,.0f} lệch {xc['diff_pct']:+.1f}% "
              f"so với VCB (VBMA {xc['vbma_vcb_mid']:,.0f}, ngày {xc['date']}) — "
              f"kiểm tra nguồn FX hoặc --set usdvnd.")


def main(argv: "list[str] | None" = None) -> int:
    # .env TRƯỚC khi refresh: FRED là nguồn vĩ mô ĐẦU TIÊN cần key
    # (FRED_API_KEY) — thiếu bước này thì `run.py macro`/CLI skip FRED lặng lẽ
    # dù `vnstock_fred.py --diag` (tự load .env) chạy được (bẫy thật 13/07).
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Theo dõi vĩ mô: lãi suất & tỷ giá.")
    ap.add_argument("--refresh", action="store_true",
                    help="Seed/scaffold + auto-fetch tỷ giá → cache")
    ap.add_argument("--diag", action="store_true",
                    help="Thử fetch FX + lãi suất LNH 1 lần, in kết quả (xác minh trên máy có mạng)")
    ap.add_argument("--dump", action="store_true",
                    help="Cùng --diag: in RAW JSON từ Vietstock để soi/chỉnh parser")
    ap.add_argument("--show", action="store_true", help="In cache hiện tại")
    ap.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"),
                    help=f"Ghi đè tay 1 chỉ số. KEY ∈ {{{', '.join(_DEFS)}}}")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD",
                    help="Ngày hiệu lực cho --set / --refresh (mặc định hôm nay)")
    a = ap.parse_args(argv)

    if a.diag:
        ok = True
        # 1) FX
        fx = fetch_usdvnd()
        if fx is None:
            print("[macro] ❌ fetch FX thất bại (không mạng / host bị chặn / API lỗi).")
            ok = False
        else:
            print(f"[macro] ✅ USD/VND tham chiếu = {fx:,.1f}")
        # 2) Interbank ON (Vietstock VNIBOR). With --dump use the verbose tracer
        #    so a failed handshake is pinpointed (GET/token/POST), not silent.
        if a.dump:
            print("── TRACE Vietstock handshake ──")
            raw = trace_vietstock(_VS_INTERBANK_NORMID)
        else:
            raw = fetch_vietstock_norm(_VS_INTERBANK_NORMID)
        if raw is None:
            print("[macro] ❌ fetch Vietstock VNIBOR thất bại — chạy lại với "
                  "`--diag --dump` để xem bước nào hỏng rồi gửi tôi output.")
            ok = False
        else:
            ib = None
            try:
                ib = extract_interbank_on(raw)
            except Exception as e:                       # noqa
                print(f"[macro] ⚠ parse VNIBOR lỗi: {e}")
            if ib:
                print(f"[macro] ✅ Lãi suất LNH ON = {ib[0]:.2f}%/năm (as_of {ib[1]})")
            elif isinstance(raw, list) and not raw:
                print("[macro] ⚠ Vietstock trả [] (rỗng) — gần như chắc do TƯỜNG PHÍ "
                      "bản Basic. Dùng `--set interbank_on <số>` cho lãi suất.")
                ok = False
            else:
                print("[macro] ⚠ Vietstock trả dữ liệu nhưng KHÔNG tách được ON.")
                ok = False
            if a.dump:
                print("── RAW getdatabynormid (cắt 2000 ký tự) ──")
                print(json.dumps(raw, ensure_ascii=False)[:2000])
        return 0 if ok else 1

    if a.set:
        key, val = a.set
        try:
            set_value(key, float(val), as_of=a.as_of)
        except (KeyError, ValueError) as e:
            print(f"[macro] ❌ {e}")
            return 1
        print(f"[macro] đã ghi {key} = {val} (as_of {a.as_of or 'hôm nay'}).")
        _show()
        return 0

    if a.refresh:
        refresh(as_of=a.as_of)
        _show()
        return 0

    if a.show:
        _show()
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
