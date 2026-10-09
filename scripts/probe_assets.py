#!/usr/bin/env python3
"""
scripts/probe_assets.py — P0 đa tài sản: ĐO NGUỒN vàng · dầu · USD trước khi xây kho (09/10)
==========================================================================================
Vì sao: kế hoạch mở rộng dashboard sang vàng/dầu/USD (`docs/THIET-KE-DA-TAI-SAN.md`)
cần biết TRƯỚC nguồn nào sống trên MÁY THẬT, tươi tới đâu (trễ mấy ngày) và lịch
sử sâu bao nhiêu năm — catalog trên mạng hay sai, sandbox Claude bị chặn mạng.

Mỗi dòng kết quả = (tài sản, nguồn): giá trị mới nhất, ngày dữ liệu, TRỄ (so hôm
nay), ĐỘ SÂU (ngày đầu tiên có dữ liệu), thời gian gọi. Bốn tầng:

  python   HTTP thẳng, miễn phí: FRED Brent/WTI/chỉ số USD rộng (dùng FRED_API_KEY
           sẵn có cho us10y) · 2 endpoint vàng + 4 endpoint FX ĐANG chạy trong
           pipeline (đo từng cái) · stooq + Yahoo (ứng viên chuỗi dài; Yahoo không
           chính thức) · SJC + Vietcombank trực tiếp (ứng viên, chưa từng gọi).
  sponsor  gói vnstock_data / vnii (Golden) + vnstock free: dò module tên hàng hoá/
           vĩ mô/tỷ giá, in chữ ký hàm, gọi thử hàm khớp vàng/dầu/tỷ giá (≤16 lượt,
           60s/lượt, KHÔNG gọi hàm có chữ key/auth/limit/set/save…).
  local    cache kho đang có (gold_price.json · usdvnd trong macro_indicators.json ·
           tỷ giá trung tâm bản tin tuần SBV) — không gọi mạng.
  mcp      (chỉ khi --mcp; MỘT lượt claude -p qua `vnstock_claude_cli.complete_mcp`)
           Finhay XAU/BZ/CL/USDVND + vàng miếng SJC dò độ sâu 5 cửa sổ (01/2015 ·
           01/2020 · 01/2024 · 01/2025 · 10 ngày gần nhất); 9 sản phẩm vàng đại lý
           còn lại (SJC/PNJ/DOJI/BTMC/BTMH) chỉ cửa sổ gần nhất; SSI tỷ giá VCB và
           SBVN (Sở giao dịch NHNN). Số đọc thẳng `tool_result`, không qua chữ model.

🖥️ DESKTOP, dưới tài khoản chạy task (có .env FRED_API_KEY + connector đã đăng nhập):

    python scripts/probe_assets.py --mcp          # đủ 4 tầng (~2–6 phút)
    python scripts/probe_assets.py                # bỏ tầng mcp
    python scripts/probe_assets.py --only python  # một tầng
    python scripts/probe_assets.py --mcp --json probe_assets.json

Dán TOÀN BỘ output cho Claude. CHỈ ĐỌC: không ghi kho (trừ --json tới đường dẫn bạn
chọn); tầng mcp ghi 1 dòng sổ LLM như mọi lượt claude -p. Tool tài khoản Finhay
KHÔNG BAO GIỜ được mở — chỉ 4 tool thị trường Finhay + 1 tool SSI. Lỗi mạng in ra
đã xoá api_key. Exit: 0 = mọi tài sản đã đo có ≥1 nguồn sống · 1 = một phần ·
2 = không nguồn nào.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import importlib
import importlib.util
import inspect
import io
import json
import os
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

VN_TZ = timezone(timedelta(hours=7))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DEFAULT_TIMEOUT_S = 15
DEFAULT_MCP_TIMEOUT_S = 600
MCP_MAX_TURNS = 20
LUONG_OZ = 37.5 / 31.1034768          # 1 lượng = 37,5 g; 1 troy oz = 31,1034768 g
USD_BAND = 0.05                       # biên độ ±5% quanh tỷ giá trung tâm

ASSETS: dict[str, str] = {
    "XAU": "Vàng TG",
    "SJC_BAR": "SJC miếng",
    "SJC_RING": "SJC nhẫn",
    "PNJ_BAR": "PNJ miếng",
    "PNJ_RING": "PNJ nhẫn",
    "DOJI_BAR": "DOJI miếng",
    "DOJI_RING": "DOJI nhẫn",
    "BTMC_BAR": "BTMC miếng",
    "BTMC_RING": "BTMC nhẫn",
    "BTMH_BAR": "BTMH miếng",
    "BTMH_RING": "BTMH nhẫn",
    "BRENT": "Brent",
    "WTI": "WTI",
    "USD_INDEX": "Chỉ số USD",
    "USDVND": "USD/VND",
    "USDVND_VCB": "USD/VND VCB",
    "USD_CENTRAL": "Tỷ giá TT",
}
STAGES = ("python", "sponsor", "local", "mcp")


# ── Bản ghi kết quả ─────────────────────────────────────────────────────────
def rec(asset: str, source: str, *, ok: bool, value=None, unit: str = "",
        as_of: "str | None" = None, first: "str | None" = None, n: "int | None" = None,
        note: str = "", error: "str | None" = None, elapsed: "float | None" = None,
        stage: str = "python") -> dict:
    return {"stage": stage, "asset": asset, "source": source, "ok": bool(ok),
            "value": value, "unit": unit, "as_of": as_of, "first": first, "n": n,
            "note": note, "error": error,
            "elapsed": None if elapsed is None else round(elapsed, 2)}


_KEY_RE = re.compile(r"(api_key|apikey|key|token)=([^&\s'\"]+)", re.I)


def scrub(msg, secrets: "tuple[str, ...]" = ()) -> str:
    """Lỗi requests có thể chứa nguyên URL (cả api_key) — xoá trước khi in.
    Lỗi kết nối dài ('HTTPSConnectionPool(...) Max retries ... Caused by X(...)')
    rút về phần NGUYÊN NHÂN."""
    s = str(msg)
    m = re.search(r"Caused by (.+)$", s, re.S)
    if m:
        s = re.sub(r"[()'\"]+", " ", m.group(1))
        s = re.sub(r"\s+", " ", s).strip()
    for sec in secrets:
        if sec:
            s = s.replace(sec, "***")
    s = _KEY_RE.sub(lambda m: f"{m.group(1)}=***", s)
    return s[:220]


def _iso(d) -> "str | None":
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
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)          # DD/MM/YYYY
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def _num(v) -> "float | None":
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def lag_days(r: dict, today: date) -> "int | None":
    d = _iso(r.get("as_of"))
    return (today - date.fromisoformat(d)).days if d else None


def last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ── HTTP ─────────────────────────────────────────────────────────────────────
def http(method: str, url: str, *, params=None, data=None, headers=None,
         timeout: int = DEFAULT_TIMEOUT_S) -> "tuple[int, str]":
    import requests
    h = {"User-Agent": UA}
    h.update(headers or {})
    if method == "POST":
        r = requests.post(url, data=data, headers=h, timeout=timeout)
    else:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
    return r.status_code, r.text


@dataclass
class Ctx:
    today: date
    http: Callable = http
    timeout: int = DEFAULT_TIMEOUT_S
    fred_key: str = ""

    def get(self, url, **kw) -> "tuple[int, str]":
        return self.http("GET", url, timeout=self.timeout, **kw)

    def post(self, url, **kw) -> "tuple[int, str]":
        return self.http("POST", url, timeout=self.timeout, **kw)


def _json(text: str):
    return json.loads(text)


def _timed(fn):
    t0 = time.monotonic()
    try:
        return fn(), None, time.monotonic() - t0
    except Exception as e:                                   # noqa: BLE001
        return None, e, time.monotonic() - t0


def _http_err(status: int, text: str) -> str:
    snippet = re.sub(r"\s+", " ", text or "")[:100]
    return f"HTTP {status}: {snippet}"


# ── FRED ─────────────────────────────────────────────────────────────────────
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = (
    ("BRENT", "DCOILBRENTEU", "USD/thùng"),
    ("WTI", "DCOILWTICO", "USD/thùng"),
    ("USD_INDEX", "DTWEXBGS", "điểm (01/2006=100)"),
)


def fred_values(payload) -> "list[tuple[str, float]]":
    """[(ngày, giá trị)] theo thứ tự payload; bỏ ô '.' (ngày nghỉ)."""
    out = []
    for o in (payload or {}).get("observations") or []:
        v = _num(o.get("value"))
        d = _iso(o.get("date"))
        if v is not None and d:
            out.append((d, v))
    return out


def probe_fred(ctx: Ctx) -> list[dict]:
    out = []
    for asset, sid, unit in FRED_SERIES:
        src = f"FRED {sid}"
        if not ctx.fred_key:
            out.append(rec(asset, src, ok=False, unit=unit, error="thiếu FRED_API_KEY trong .env"))
            continue

        def run(sid=sid):
            base = {"series_id": sid, "api_key": ctx.fred_key, "file_type": "json"}
            st, txt = ctx.get(FRED_BASE, params={**base, "sort_order": "desc", "limit": 10})
            if st != 200:
                raise RuntimeError(_http_err(st, txt))
            latest = fred_values(_json(txt))
            st2, txt2 = ctx.get(FRED_BASE, params={**base, "sort_order": "asc", "limit": 5})
            first = fred_values(_json(txt2)) if st2 == 200 else []
            return latest, first

        got, err, el = _timed(run)
        if err or not got or not got[0]:
            out.append(rec(asset, src, ok=False, unit=unit, elapsed=el,
                           error=scrub(err or "không có observation số", (ctx.fred_key,))))
            continue
        latest, first = got
        out.append(rec(asset, src, ok=True, value=latest[0][1], unit=unit, as_of=latest[0][0],
                       first=first[0][0] if first else None, elapsed=el,
                       note="chỉ số rộng của Fed, KHÔNG phải ICE DXY" if asset == "USD_INDEX" else ""))
    return out


# ── Endpoint vàng + FX đang chạy trong pipeline ──────────────────────────────
def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url[:30]


def probe_gold_endpoints(ctx: Ctx) -> list[dict]:
    import vnstock_gold as g
    out = []
    for url, parse in g._ENDPOINTS:
        def run(url=url, parse=parse):
            st, txt = ctx.get(url)
            if st != 200:
                raise RuntimeError(_http_err(st, txt))
            v = _num(parse(_json(txt)))
            if v is None or not (g._RANGE[0] <= v <= g._RANGE[1]):
                raise ValueError(f"giá ngoài khoảng {g._RANGE}: {v}")
            return v
        v, err, el = _timed(run)
        out.append(rec("XAU", f"pipeline {_host(url)}", ok=err is None, value=v, unit="USD/oz",
                       as_of=ctx.today.isoformat() if err is None else None, elapsed=el,
                       note="chỉ giá hiện tại — lịch sử do pipeline tự chụp mỗi ngày",
                       error=scrub(err) if err else None))
    return out


def parse_fx_payload(data) -> "float | None":
    """USD/VND từ payload er-api / exchangerate.host / currency-api — cùng luật
    `vnstock_macro.fetch_usdvnd` (rates.VND hoặc usd.vnd chữ thường)."""
    if not isinstance(data, dict):
        return None
    rates = data.get("rates")
    vnd = rates.get("VND") if isinstance(rates, dict) else None
    if vnd is None:
        usd = data.get("usd")
        vnd = usd.get("vnd") if isinstance(usd, dict) else None
    v = _num(vnd)
    return v if v is not None and v > 1000 else None


def probe_fx_endpoints(ctx: Ctx) -> list[dict]:
    import vnstock_macro as m
    out = []
    for url in m._FX_ENDPOINTS:
        def run(url=url):
            st, txt = ctx.get(url)
            if st != 200:
                raise RuntimeError(_http_err(st, txt))
            v = parse_fx_payload(_json(txt))
            if v is None:
                raise ValueError("payload không có VND")
            return v
        v, err, el = _timed(run)
        out.append(rec("USDVND", f"pipeline {_host(url)}", ok=err is None, value=v, unit="VND",
                       as_of=ctx.today.isoformat() if err is None else None, elapsed=el,
                       note="tỷ giá tham chiếu, chỉ giá hiện tại",
                       error=scrub(err) if err else None))
    return out


# ── stooq + Yahoo (ứng viên chuỗi dài) ───────────────────────────────────────
STOOQ = (("XAU", "xauusd"), ("BRENT", "cb.f"), ("WTI", "cl.f"),
         ("USD_INDEX", "dx.f"), ("USDVND", "usdvnd"))
YAHOO = (("XAU", "GC=F"), ("BRENT", "BZ=F"), ("WTI", "CL=F"),
         ("USD_INDEX", "DX-Y.NYB"), ("USDVND", "VND=X"))


def parse_stooq_csv(text: str) -> "list[tuple[str, float]]":
    head = (text or "").lstrip()[:200]
    if not head.lower().startswith("date,"):
        raise ValueError(re.sub(r"\s+", " ", head)[:100] or "rỗng")
    out = []
    for row in csv.DictReader(io.StringIO(text.lstrip())):
        d, c = _iso(row.get("Date")), _num(row.get("Close"))
        if d and c is not None:
            out.append((d, c))
    if not out:
        raise ValueError("CSV không có dòng giá")
    return out


def parse_yahoo_chart(payload) -> "list[tuple[str, float]]":
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError(str((chart["error"] or {}).get("description") or chart["error"])[:100])
    res = (chart.get("result") or [None])[0] or {}
    ts = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        out.append((datetime.fromtimestamp(int(t) + off, tz=timezone.utc).date().isoformat(), float(c)))
    if not out:
        raise ValueError("chart rỗng")
    return out


def _series_rec(asset, src, series, el, unit="", note="") -> dict:
    return rec(asset, src, ok=True, value=series[-1][1], unit=unit, as_of=series[-1][0],
               first=series[0][0], n=len(series), elapsed=el, note=note)


def probe_stooq(ctx: Ctx) -> list[dict]:
    out = []
    for asset, sym in STOOQ:
        def run(sym=sym):
            st, txt = ctx.get(f"https://stooq.com/q/d/l/?s={sym}&i=d")
            if st != 200:
                raise RuntimeError(_http_err(st, txt))
            return parse_stooq_csv(txt)
        s, err, el = _timed(run)
        out.append(_series_rec(asset, f"stooq {sym}", s, el) if not err else
                   rec(asset, f"stooq {sym}", ok=False, elapsed=el, error=scrub(err)))
    return out


def probe_yahoo(ctx: Ctx) -> list[dict]:
    out = []
    now = int(time.time())
    for asset, sym in YAHOO:
        def run(sym=sym):
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}"
                   f"?period1=0&period2={now}&interval=1d")
            st, txt = ctx.get(url)
            if st != 200:
                raise RuntimeError(_http_err(st, txt))
            return parse_yahoo_chart(_json(txt))
        s, err, el = _timed(run)
        out.append(_series_rec(asset, f"yahoo {sym}", s, el, note="không chính thức") if not err else
                   rec(asset, f"yahoo {sym}", ok=False, elapsed=el, error=scrub(err)))
    return out


# ── SJC + Vietcombank trực tiếp (ứng viên) ───────────────────────────────────
SJC_URL = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"
VCB_JSON_URL = "https://www.vietcombank.com.vn/api/exchangerates"
VCB_XML_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"


def _pick_key(row: dict, *needles) -> "str | None":
    for k in row:
        kl = str(k).lower()
        if any(n in kl for n in needles):
            return k
    return None


def parse_sjc(payload) -> list[dict]:
    """Bảng giá SJC → [{name, branch, buy, sell}] (đơn vị nguyên trạng nguồn)."""
    rows = (payload or {}).get("data") if isinstance(payload, dict) else payload
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        kn, kb = _pick_key(r, "typename", "name", "type"), _pick_key(r, "branch")
        kbuy, ksell = _pick_key(r, "buy"), _pick_key(r, "sell")
        buy, sell = _num(r.get(kbuy)) if kbuy else None, _num(r.get(ksell)) if ksell else None
        if buy is None and sell is None:
            continue
        out.append({"name": str(r.get(kn) or ""), "branch": str(r.get(kb) or ""),
                    "buy": buy, "sell": sell})
    return out


def pick_sjc_bar(rows: list) -> "dict | None":
    """Vàng miếng SJC 1 lượng ở TP.HCM; không có thì dòng '1L' đầu, rồi dòng đầu."""
    bars = [r for r in rows if "1l" in r["name"].lower().replace(" ", "")]
    hcm = [r for r in bars if "hồ chí minh" in r["branch"].lower() or "hcm" in r["branch"].lower()]
    return (hcm or bars or rows or [None])[0]


def probe_sjc(ctx: Ctx) -> list[dict]:
    days = [last_weekday(ctx.today), last_weekday(ctx.today - timedelta(days=365)),
            last_weekday(ctx.today - timedelta(days=5 * 365))]

    def one(d: date):
        st, txt = ctx.post(SJC_URL, data=f"method=GetSJCGoldPriceByDate&toDate={d:%d/%m/%Y}",
                           headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        if st != 200:
            raise RuntimeError(_http_err(st, txt))
        return pick_sjc_bar(parse_sjc(_json(txt)))

    got, err, el = _timed(lambda: one(days[0]))
    if err or not got:
        return [rec("SJC_BAR", "sjc.com.vn trực tiếp", ok=False, elapsed=el,
                    error=scrub(err or "không có dòng giá"))]
    depth = []
    for d in days[1:]:
        old, e2, _ = _timed(lambda d=d: one(d))
        depth.append(f"{d.isoformat()}{'✓' if old and not e2 else '✗'}")
    return [rec("SJC_BAR", "sjc.com.vn trực tiếp", ok=True, value=got["sell"],
                unit="nguồn (bán ra)", as_of=days[0].isoformat(), elapsed=el,
                note=f"mua {got['buy']} · {got['name'][:28]} · {got['branch'][:16]} · sâu: {' '.join(depth)}")]


def parse_vcb_json(payload) -> "dict | None":
    for r in (payload or {}).get("Data") or (payload or {}).get("data") or []:
        if isinstance(r, dict) and str(r.get("currencyCode") or r.get("CurrencyCode")).upper() == "USD":
            return {"cash": _num(r.get("cash") or r.get("Cash")),
                    "transfer": _num(r.get("transfer") or r.get("Transfer")),
                    "sell": _num(r.get("sell") or r.get("Sell"))}
    return None


def parse_vcb_xml(text: str) -> "dict | None":
    m = re.search(r"<Exrate\b[^>]*CurrencyCode=\"USD\"[^>]*/?>", text or "", re.I)
    if not m:
        return None
    tag = m.group(0)

    def attr(name):
        a = re.search(name + r"=\"([^\"]*)\"", tag, re.I)
        return _num(a.group(1)) if a else None
    return {"cash": attr("Buy"), "transfer": attr("Transfer"), "sell": attr("Sell")}


def probe_vcb(ctx: Ctx) -> list[dict]:
    out = []
    days = [last_weekday(ctx.today), last_weekday(ctx.today - timedelta(days=365)),
            last_weekday(ctx.today - timedelta(days=5 * 365))]

    def one(d: date):
        st, txt = ctx.get(VCB_JSON_URL, params={"date": d.isoformat()})
        if st != 200:
            raise RuntimeError(_http_err(st, txt))
        return parse_vcb_json(_json(txt))

    got, err, el = _timed(lambda: one(days[0]))
    if err or not got or got.get("sell") is None:
        out.append(rec("USDVND_VCB", "vietcombank.com.vn api", ok=False, elapsed=el,
                       error=scrub(err or "không có dòng USD")))
    else:
        depth = []
        for d in days[1:]:
            old, e2, _ = _timed(lambda d=d: one(d))
            depth.append(f"{d.isoformat()}{'✓' if old and not e2 else '✗'}")
        out.append(rec("USDVND_VCB", "vietcombank.com.vn api", ok=True, value=got["sell"],
                       unit="VND (bán)", as_of=days[0].isoformat(), elapsed=el,
                       note=f"mua TM {got['cash']} · CK {got['transfer']} · sâu: {' '.join(depth)}"))

    def xml():
        st, txt = ctx.get(VCB_XML_URL)
        if st != 200:
            raise RuntimeError(_http_err(st, txt))
        return parse_vcb_xml(txt)
    got, err, el = _timed(xml)
    out.append(rec("USDVND_VCB", "portal VCB XML", ok=bool(got and got.get("sell")),
                   value=(got or {}).get("sell"), unit="VND (bán)",
                   as_of=ctx.today.isoformat() if got else None, elapsed=el,
                   note=f"mua TM {(got or {}).get('cash')} · CK {(got or {}).get('transfer')} · chỉ hôm nay" if got else "",
                   error=None if got and got.get("sell") else scrub(err or "không có dòng USD")))
    return out


PYTHON_PROBES = (probe_fred, probe_gold_endpoints, probe_fx_endpoints, probe_stooq,
                 probe_yahoo, probe_sjc, probe_vcb)


def run_python_stage(ctx: Ctx, probes=PYTHON_PROBES) -> list[dict]:
    """Các nhóm nguồn chạy SONG SONG (I/O), mỗi nhóm tuần tự bên trong; lỗi
    import/ngoại lệ của một nhóm thành một dòng ❌, không làm sập cả lượt."""
    def safe(p):
        try:
            return p(ctx)
        except Exception as e:                               # noqa: BLE001
            return [rec("?", p.__name__, ok=False, error=scrub(e, (ctx.fred_key,)))]
    with ThreadPoolExecutor(max_workers=min(8, len(probes))) as ex:
        groups = list(ex.map(safe, probes))
    return [r for g in groups for r in g]


# ── Gói sponsor / vnstock free: dò hàm hàng hoá · vĩ mô · tỷ giá ──────────────
SPONSOR_PKGS = ("vnstock_data", "vnii", "vnstock")
MODULE_RE = re.compile(r"(?i)commod|macro|gold|vang|forex|fx|exchange|currency|oil|crude|petro|misc")
METHOD_RE = re.compile(r"(?i)gold|oil|crude|brent|wti|petro|exchange|fx|forex|usd|dxy|currency|rate|commod")
UNSAFE_RE = re.compile(r"(?i)limit|key|auth|login|regist|token|quota|config|^set|save|write|delete|update|install|clear|cache")
MAX_MODULES = 40
MAX_SPONSOR_CALLS = 16
SPONSOR_CALL_TIMEOUT_S = 60


def find_modules(pkg: str, name_re=MODULE_RE, limit: int = MAX_MODULES) -> list[str]:
    """Tên module (dạng chấm) trong gói có ĐƯỜNG DẪN khớp `name_re` — đi file,
    KHÔNG import cả gói để dò."""
    try:
        spec = importlib.util.find_spec(pkg)
    except Exception:                                        # noqa: BLE001
        return []
    if not spec or not spec.submodule_search_locations:
        return []
    out: list[str] = []
    for base in spec.submodule_search_locations:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(("_", ".")) and d != "tests"]
            for f in sorted(files):
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                rel = os.path.relpath(os.path.join(root, f), base)[:-3].replace(os.sep, ".")
                if name_re.search(rel):
                    out.append(f"{pkg}.{rel}")
                    if len(out) >= limit:
                        return out
    return out


def _sig(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "(?)"


_START = ("start", "start_date", "from_date", "begin", "fromdate")
_END = ("end", "end_date", "to_date", "todate")


def kwargs_for(obj, today: date, back_days: int = 400) -> "dict | None":
    """Đối số cho một lượt gọi thử: điền start/end/date theo tên; tham số BẮT
    BUỘC tên lạ ⇒ None (không gọi mò)."""
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return {}
    kw: dict = {}
    for name, p in sig.parameters.items():
        if name in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        low = name.lower()
        if low in _START:
            kw[name] = (today - timedelta(days=back_days)).isoformat()
        elif low in _END:
            kw[name] = today.isoformat()
        elif low == "date":
            kw[name] = last_weekday(today).isoformat()
        elif p.default is inspect.Parameter.empty:
            return None
    return kw


def call_with_timeout(fn, timeout: float = SPONSOR_CALL_TIMEOUT_S):
    """(kết quả, lỗi) — chạy trong thread DAEMON: lượt treo không giữ tiến trình.
    KHÔNG đổi sys.stdout trong thread (toàn cục — lượt treo sẽ nuốt mọi dòng in sau)."""
    box: dict = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as e:                           # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, TimeoutError(f"quá {timeout:.0f}s")
    return box.get("v"), box.get("e")


def summarize(obj) -> str:
    """Một dòng mô tả kết quả: DataFrame → số dòng, cột, khoảng ngày, dòng cuối."""
    try:
        import pandas as pd
    except ImportError:                                      # pragma: no cover
        pd = None
    if pd is not None and isinstance(obj, pd.DataFrame):
        if obj.empty:
            return "DataFrame rỗng"
        cols = [str(c) for c in obj.columns][:8]
        dates = None
        dcol = next((c for c in obj.columns if re.search(r"(?i)date|time|ngay|day", str(c))), None)
        ser = obj[dcol] if dcol is not None else (obj.index.to_series()
                                                  if isinstance(obj.index, pd.DatetimeIndex) else None)
        if ser is not None:
            try:
                ds = pd.to_datetime(ser, errors="coerce").dropna()
                if len(ds):
                    dates = f"{ds.min().date()}→{ds.max().date()}"
            except Exception:                                # noqa: BLE001
                dates = None
        last = {str(k): v for k, v in list(obj.iloc[-1].items())[:5]}
        return f"{len(obj)} dòng · cột {cols}" + (f" · {dates}" if dates else "") + f" · cuối {last}"
    if isinstance(obj, dict):
        return f"dict {len(obj)} khoá {list(obj)[:6]}"
    if isinstance(obj, (list, tuple)):
        return f"{type(obj).__name__} {len(obj)} phần tử"
    return re.sub(r"\s+", " ", repr(obj))[:160]


def _members(mod) -> list:
    """(tên, đối tượng) công khai ĐỊNH NGHĨA trong module (không kéo theo import)."""
    out = []
    for name, obj in vars(mod).items():
        if name.startswith("_") or getattr(obj, "__module__", None) != mod.__name__:
            continue
        if inspect.isclass(obj) or inspect.isfunction(obj):
            out.append((name, obj))
    return out


def probe_sponsor(today: date, *, calls: bool = True, pkgs=SPONSOR_PKGS) -> list[dict]:
    with contextlib.suppress(Exception), contextlib.redirect_stdout(io.StringIO()):
        import vnstock_auth  # noqa: F401  (nạp .env + nhận diện gói sponsor như cả repo)
    out: list[dict] = []
    budget = [MAX_SPONSOR_CALLS]

    def try_call(label, fn, kw):
        if budget[0] <= 0:
            return
        budget[0] -= 1
        t0 = time.monotonic()
        v, e = call_with_timeout(lambda: fn(**kw))
        el = time.monotonic() - t0
        out.append(rec("?", label, ok=e is None and v is not None, stage="sponsor", elapsed=el,
                       note=f"kw={kw} → {summarize(v)}" if e is None else f"kw={kw}",
                       error=scrub(f"{type(e).__name__}: {e}") if e else None))

    for pkg in pkgs:
        mods = find_modules(pkg)
        if not mods:
            out.append(rec("?", pkg, ok=False, stage="sponsor",
                           error="không cài / không có module tên hàng hoá·vĩ mô·tỷ giá"))
            continue
        for mname in mods:
            v, e = call_with_timeout(lambda m=mname: importlib.import_module(m), 60)
            if e or v is None:
                out.append(rec("?", mname, ok=False, stage="sponsor",
                               error=scrub(f"import: {type(e).__name__}: {e}")))
                continue
            for name, obj in _members(v):
                if inspect.isclass(obj):
                    meths = [(mn, mo) for mn, mo in vars(obj).items()
                             if not mn.startswith("_") and callable(mo)
                             and METHOD_RE.search(mn) and not UNSAFE_RE.search(mn)]
                    if not meths and not METHOD_RE.search(name):
                        continue
                    out.append(rec("?", f"{mname}.{name}", ok=True, stage="sponsor",
                                   note=f"lớp{_sig(obj)} · hàm: " +
                                   ", ".join(f"{mn}{_sig(mo)}" for mn, mo in meths[:10])))
                    if not calls or not meths:
                        continue
                    ikw = kwargs_for(obj, today)
                    if ikw is None:
                        continue
                    inst, ie = call_with_timeout(lambda o=obj, k=ikw: o(**k), 60)
                    if ie or inst is None:
                        out.append(rec("?", f"{name}({ikw})", ok=False, stage="sponsor",
                                       error=scrub(f"khởi tạo: {type(ie).__name__}: {ie}")))
                        continue
                    for mn, _ in meths:
                        bound = getattr(inst, mn, None)
                        mkw = kwargs_for(bound, today) if bound else None
                        if mkw is not None:
                            try_call(f"{name}.{mn}", bound, mkw)
                elif METHOD_RE.search(name) and not UNSAFE_RE.search(name):
                    out.append(rec("?", f"{mname}.{name}", ok=True, stage="sponsor",
                                   note=f"hàm{_sig(obj)}"))
                    kw = kwargs_for(obj, today) if calls else None
                    if kw is not None:
                        try_call(name, obj, kw)
    return out


# ── Cache kho đang có ────────────────────────────────────────────────────────
def _read_json(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def _history_rec(asset, src, hist: dict, unit: str, note: str = "") -> dict:
    pts = sorted((d, _num(v)) for d, v in (hist or {}).items() if _iso(d) and _num(v) is not None)
    if not pts:
        return rec(asset, src, ok=False, stage="local", unit=unit, error="cache rỗng / chưa có")
    return rec(asset, src, ok=True, stage="local", value=pts[-1][1], unit=unit, as_of=pts[-1][0],
               first=pts[0][0], n=len(pts), note=note)


def probe_local(*, gold_path=None, macro_path=None, sbv_path=None) -> list[dict]:
    if gold_path is None or macro_path is None or sbv_path is None:
        import vnstock_gold
        import vnstock_macro
        import vnstock_sbv
        gold_path = gold_path or vnstock_gold._CACHE
        macro_path = macro_path or vnstock_macro._CACHE
        sbv_path = sbv_path or vnstock_sbv._cache_path()
    out = [_history_rec("XAU", "kho gold_price.json", _read_json(gold_path).get("history") or {},
                        "USD/oz", "pipeline tự chụp 1 điểm/ngày, trần 400")]
    usd = ((_read_json(macro_path).get("indicators") or {}).get("usdvnd") or {})
    out.append(_history_rec("USDVND", "kho macro usdvnd", usd.get("history") or {}, "VND",
                            f"nguồn {usd.get('source') or '?'}, trần 60 điểm"))
    sbv = _read_json(sbv_path)
    fx = _num(sbv.get("fx_central"))
    out.append(rec("USD_CENTRAL", "kho bản tin tuần SBV", ok=fx is not None, stage="local", value=fx,
                   unit="VND", as_of=_iso(sbv.get("as_of")), note="1 điểm/tuần",
                   error=None if fx is not None else "chưa có fx_central"))
    return out


# ── MCP: Finhay + SSI qua một lượt claude -p ─────────────────────────────────
ENV_FINHAY = "VNSTOCK_MCP_FINHAY_SERVER"
ENV_SSI = "VNSTOCK_MCP_SSI_SERVER"
DEFAULT_FINHAY = "claude.ai Finhay"            # tên server đo 08/10 trên 🖥️ (U78)
DEFAULT_SSI = "claude.ai SSI MCP"
T_COMMODITY = "get_commodity_history"
T_FOREX = "get_forex_history"
T_DEALER = "get_dealer_product_history"
T_SSI_FX = "marketdata_list_foreign_currency_converter"

# (tài sản, tool, tham số gốc, có dò độ sâu không)
MCP_SERIES = (
    ("XAU", T_COMMODITY, {"symbol": "XAU"}, True),
    ("BRENT", T_COMMODITY, {"symbol": "BZ"}, True),
    ("WTI", T_COMMODITY, {"symbol": "CL"}, True),
    ("USDVND", T_FOREX, {"symbol": "USDVND"}, True),
    ("SJC_BAR", T_DEALER, {"symbol": "XAU", "code": "GOLD_BAR_SJC"}, True),
    ("SJC_RING", T_DEALER, {"symbol": "XAU", "code": "GOLD_RING_SJC"}, False),
    ("PNJ_BAR", T_DEALER, {"symbol": "XAU", "code": "GOLD_BAR_PNJ"}, False),
    ("PNJ_RING", T_DEALER, {"symbol": "XAU", "code": "GOLD_RING_PNJ"}, False),
    ("DOJI_BAR", T_DEALER, {"symbol": "XAU", "code": "GOLD_BAR_DOJI"}, False),
    ("DOJI_RING", T_DEALER, {"symbol": "XAU", "code": "GOLD_RING_DOJI"}, False),
    ("BTMC_BAR", T_DEALER, {"symbol": "XAU", "code": "GOLD_BAR_BTMC"}, False),
    ("BTMC_RING", T_DEALER, {"symbol": "XAU", "code": "GOLD_RING_BTMC"}, False),
    ("BTMH_BAR", T_DEALER, {"symbol": "XAU", "code": "GOLD_BAR_BTMH"}, False),
    ("BTMH_RING", T_DEALER, {"symbol": "XAU", "code": "GOLD_RING_BTMH"}, False),
)
SSI_FX = (("USDVND_VCB", "VCB"), ("USD_CENTRAL", "SBVN"))
DEPTH_WINDOWS = (date(2015, 1, 5), date(2020, 1, 6), date(2024, 1, 8), date(2025, 1, 6))
WINDOW_DAYS = 7
LATEST_DAYS = 10
LATEST = "gần nhất"


def vn_ts(d: date) -> int:
    """Unix giây lúc 00:00 giờ VN — đúng cách Finhay đánh dấu nến ngày."""
    return int(datetime(d.year, d.month, d.day, tzinfo=VN_TZ).timestamp())


def ts_date(t) -> "date | None":
    try:
        return datetime.fromtimestamp(int(float(t)), tz=VN_TZ).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def mcp_prefixes() -> "tuple[str, str]":
    import vnstock_claude_cli as cc
    return (cc.mcp_server_prefix(os.environ.get(ENV_FINHAY) or DEFAULT_FINHAY),
            cc.mcp_server_prefix(os.environ.get(ENV_SSI) or DEFAULT_SSI))


def mcp_plan(today: date, finhay_prefix: str, ssi_prefix: str) -> list[dict]:
    plan = []
    for asset, tool, base, deep in MCP_SERIES:
        wins = [(str(w.year), w, w + timedelta(days=WINDOW_DAYS)) for w in DEPTH_WINDOWS] if deep else []
        wins.append((LATEST, today - timedelta(days=LATEST_DAYS), today + timedelta(days=1)))
        for label, a, b in wins:
            plan.append({"asset": asset, "label": label, "tool": finhay_prefix + tool,
                         "input": {**base, "from": vn_ts(a), "to": vn_ts(b)}})
    for asset, bank in SSI_FX:
        plan.append({"asset": asset, "label": LATEST, "tool": ssi_prefix + T_SSI_FX,
                     "input": {"bank": bank, "range": "1w"}})
    return plan


def build_mcp_prompt(plan: list) -> "tuple[str, str]":
    """(system, user). System KHÔNG có |<>%\" hay xuống dòng (shim .cmd trên Windows)."""
    tools = sorted({p["tool"] for p in plan})
    system = ("Bạn là bộ thu thập dữ liệu, không phân tích. Gọi ĐÚNG từng lệnh gọi tool "
              "liệt kê trong tin nhắn, mỗi lệnh một lần, tham số giữ y nguyên. Gọi song song "
              "tối đa mười tool mỗi lượt. Được dùng ToolSearch để nạp tool trước. Không gọi "
              "tool nào khác. Gọi xong tất cả thì trả lời đúng một chữ: XONG.")
    lines = [f"Nếu tool chưa có sẵn: gọi ToolSearch với query select:{','.join(tools)}",
             f"Danh sách {len(plan)} lệnh gọi (tên tool rồi tham số JSON):"]
    for i, p in enumerate(plan, 1):
        lines.append(f"{i}. {p['tool']} {json.dumps(p['input'], ensure_ascii=False)}")
    return system, "\n".join(lines)


def call_key(tool: str, inp: dict) -> str:
    inp = inp if isinstance(inp, dict) else {}
    ident = str(inp.get("code") or inp.get("bank") or inp.get("symbol") or "").upper()
    f = _num(inp.get("from"))
    return f"{tool}|{ident}|{int(f) if f is not None else ''}"


def _loads_tool_text(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        i = str(text).find("{")
        if i < 0:
            return None
        try:
            return json.loads(str(text)[i:])
        except ValueError:
            return None


def summarize_series(text) -> dict:
    """Kết quả tool lịch sử Finhay → {n, first, last, value, bid, ask, error}."""
    data = _loads_tool_text(text)
    if not isinstance(data, dict):
        return {"n": 0, "error": "kết quả không phải JSON"}
    series = data.get("series")
    if not isinstance(series, list):
        return {"n": 0, "error": str(data.get("error") or data.get("message") or "không có series")[:100]}
    pts = []
    for b in series:
        if not isinstance(b, dict):
            continue
        d = ts_date(b.get("t"))
        if d is None:
            continue
        pts.append((d, _num(b.get("c")), _num(b.get("bid")), _num(b.get("ask"))))
    if not pts:
        return {"n": 0}
    pts.sort()
    d, c, bid, ask = pts[-1]
    return {"n": len(pts), "first": pts[0][0].isoformat(), "last": d.isoformat(),
            "value": c if c is not None else ask, "bid": bid, "ask": ask,
            "unit": data.get("unit"), "currency": data.get("currency")}


def parse_ssi_usd(text) -> "dict | None":
    """Dòng '<NH>_VND-USD' ngày mới nhất → {date, buy, sell, transfer}."""
    data = _loads_tool_text(text)
    rates = (((data or {}).get("data") or {}).get("rates")) if isinstance(data, dict) else None
    best = None
    for r in rates or []:
        if not isinstance(r, dict) or not str(r.get("currency_name") or "").upper().endswith("-USD"):
            continue
        d = _iso(r.get("trading_date"))
        if d and (best is None or d > best["date"]):
            best = {"date": d, "buy": _num(r.get("buy")), "sell": _num(r.get("sell")),
                    "transfer": _num(r.get("transfer"))}
    return best


def central_from_sbvn(buy: float, sell: float) -> dict:
    """SBVN = giá USD tại Sở giao dịch NHNN. Đo 09/10 qua SSI: mua 24.398 · bán
    26.860 ⇒ (mua+bán)/2 = 25.629 và bán = trần − 50, mua = sàn + 50 khớp CẢ HAI
    với biên ±5% ⇒ trung tâm = (mua+bán)/2 (SUY LUẬN — đối chiếu bản tin SBV)."""
    c = (buy + sell) / 2
    return {"central": round(c, 1), "ceiling": round(c * (1 + USD_BAND)),
            "floor": round(c * (1 - USD_BAND))}


def mcp_results(plan: list, exchanges: list, today: date) -> list[dict]:
    by_key = {}
    for e in exchanges or []:
        by_key.setdefault(call_key(e.get("name"), e.get("input")), e)
    groups: dict = {}
    for p in plan:
        groups.setdefault(p["asset"], []).append(p)
    out = []
    for asset, calls in groups.items():
        tool = calls[0]["tool"]
        short = tool.split("__")[-1]
        src = f"MCP {short}"
        if short == T_SSI_FX:
            e = by_key.get(call_key(tool, calls[0]["input"]))
            bank = calls[0]["input"]["bank"]
            src = f"MCP SSI {bank}"
            if not e or e.get("text") is None or e.get("is_error"):
                out.append(rec(asset, src, ok=False, stage="mcp",
                               error=scrub((e or {}).get("text") or "model không gọi tool này")))
                continue
            row = parse_ssi_usd(e["text"])
            if not row or row["sell"] is None:
                out.append(rec(asset, src, ok=False, stage="mcp", error="không có dòng -USD"))
                continue
            if bank == "SBVN" and row["buy"]:
                band = central_from_sbvn(row["buy"], row["sell"])
                out.append(rec(asset, src, ok=True, stage="mcp", value=band["central"], unit="VND",
                               as_of=row["date"],
                               note=f"mua {row['buy']:,.0f} · bán {row['sell']:,.0f} ⇒ trung tâm "
                                    f"(mua+bán)/2, trần {band['ceiling']:,} · sàn {band['floor']:,}"))
            else:
                out.append(rec(asset, src, ok=True, stage="mcp", value=row["sell"], unit="VND (bán)",
                               as_of=row["date"],
                               note=f"mua {_fmt_val(row['buy'])} · CK {_fmt_val(row['transfer'])}"))
            continue
        ident = calls[0]["input"].get("code") or calls[0]["input"].get("symbol")
        src = f"MCP Finhay {ident}"
        wins, errs = {}, []
        for p in calls:
            e = by_key.get(call_key(tool, p["input"]))
            if not e or e.get("text") is None:
                errs.append(f"{p['label']}: model không gọi")
                continue
            if e.get("is_error"):
                errs.append(f"{p['label']}: {scrub(e['text'])[:60]}")
                continue
            wins[p["label"]] = summarize_series(e["text"])
        latest = wins.get(LATEST) or {}
        depth = " ".join(f"{lb}{'✓' if (wins.get(lb) or {}).get('n') else ('✗' if lb in wins else '?')}"
                         for lb in [p["label"] for p in calls if p["label"] != LATEST])
        first = next((wins[p["label"]]["first"] for p in calls
                      if (wins.get(p["label"]) or {}).get("n")), None)
        unit = latest.get("unit") or ""
        bits = []
        if latest.get("bid") is not None:
            bits.append(f"mua {latest['bid']:,.0f} · bán {latest['ask']:,.0f} ({latest.get('currency') or ''}/{unit})")
        if depth:
            bits.append(f"sâu: {depth}")
        if errs:
            bits.append("; ".join(errs[:3]))
        out.append(rec(asset, src, ok=bool(latest.get("n")), stage="mcp", value=latest.get("value"),
                       unit=unit, as_of=latest.get("last"), first=first, n=latest.get("n"),
                       note=" · ".join(bits),
                       error=None if latest.get("n") else (latest.get("error") or "cửa sổ gần nhất rỗng")))
    return out


def run_mcp_stage(today: date, *, collect=None, timeout_s: int = DEFAULT_MCP_TIMEOUT_S) -> "tuple[list, dict]":
    fp, sp = mcp_prefixes()
    plan = mcp_plan(today, fp, sp)
    system, user = build_mcp_prompt(plan)
    allowed = sorted({p["tool"] for p in plan})
    if collect is None:
        import vnstock_claude_cli as cc

        def collect(u, s, a):
            return cc.complete_mcp(u, system=s, allowed_tools=a, timeout_s=timeout_s,
                                   max_turns=MCP_MAX_TURNS, tag="probe_assets")
    exchanges, err, info = collect(user, system, allowed)
    info = dict(info or {})
    info["error"] = err
    info["planned"] = len(plan)
    info["called"] = len(exchanges or [])
    if info.get("no_exe"):
        return [rec("?", "MCP", ok=False, stage="mcp", error=err)], info
    return mcp_results(plan, exchanges, today), info


# ── Suy ra + kết luận ────────────────────────────────────────────────────────
def _best(results: list, asset: str, stage: "str | None" = None) -> "dict | None":
    ok = [r for r in results if r["asset"] == asset and r["ok"] and r.get("value") is not None
          and (stage is None or r["stage"] == stage)]
    ok.sort(key=lambda r: r.get("as_of") or "", reverse=True)
    return ok[0] if ok else None


def sjc_premium(xau_usd_oz: float, usdvnd: float, sell_k_per_chi: float) -> float:
    """% vàng miếng đắt hơn vàng TG quy đổi. Giá đại lý Finhay = NGHÌN đồng/chỉ
    (09/10: SJC 14.480 ⇔ 144,8 tr/lượng; 01/2025 8.620 ⇔ 86,2 tr — khớp thị trường)."""
    vnd_luong = sell_k_per_chi * 1000 * 10
    spot_luong = xau_usd_oz * usdvnd * LUONG_OZ
    return (vnd_luong / spot_luong - 1) * 100


def derived_lines(results: list) -> list[str]:
    out = []
    xau, usd = _best(results, "XAU"), _best(results, "USDVND")
    sjc = _best(results, "SJC_BAR", stage="mcp")
    if xau and usd and sjc:
        p = sjc_premium(xau["value"], usd["value"], sjc["value"])
        out.append(f"SJC miếng đắt hơn vàng TG quy đổi ≈ {p:,.1f}% (TG {xau['value']:,.2f} "
                   f"[{xau['source']}] × {usd['value']:,.0f} [{usd['source']}] × {LUONG_OZ:.5f} oz/lượng)")
    cen, vcb = _best(results, "USD_CENTRAL", stage="mcp"), _best(results, "USDVND_VCB")
    if cen and vcb:
        ceil = cen["value"] * (1 + USD_BAND)
        out.append(f"VCB bán {vcb['value']:,.0f} còn cách trần {ceil:,.0f} ≈ {(ceil / vcb['value'] - 1) * 100:,.2f}%")
    loc = _best(results, "USD_CENTRAL", stage="local")
    if cen and loc:
        out.append(f"Đối chiếu trung tâm: SBVN suy ra {cen['value']:,.0f} ({cen['as_of']}) vs bản tin tuần "
                   f"{loc['value']:,.0f} ({loc['as_of']}) — lệch {(cen['value'] / loc['value'] - 1) * 100:+.2f}%")
    return out


def conclusions(results: list, today: date) -> list[str]:
    lines = []
    probed = [a for a in ASSETS if any(r["asset"] == a for r in results)]
    for a in probed:
        ok = [r for r in results if r["asset"] == a and r["ok"] and r.get("as_of")]
        if not ok:
            lines.append(f"❌ {ASSETS[a]}: chưa nguồn nào sống")
            continue
        fresh = min(ok, key=lambda r: (lag_days(r, today), r.get("elapsed") or 0))
        deep = [r for r in ok if r.get("first")]
        txt = f"✅ {ASSETS[a]}: tươi nhất {fresh['source']} (trễ {lag_days(fresh, today)}d)"
        if deep:
            d = min(deep, key=lambda r: r["first"])
            txt += f" · sâu nhất {d['source']} (từ {d['first']})"
        lines.append(txt)
    return lines


def exit_code(results: list) -> int:
    probed = {r["asset"] for r in results if r["asset"] in ASSETS}
    alive = {r["asset"] for r in results if r["asset"] in ASSETS and r["ok"]}
    if not probed or not alive:
        return 2
    return 0 if alive == probed else 1


# ── In ───────────────────────────────────────────────────────────────────────
def _fmt_val(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) < 1000:
        return f"{v:,.2f}"
    return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)


def fmt_row(r: dict, today: date) -> str:
    icon = "✅" if r["ok"] else "❌"
    lab = ASSETS.get(r["asset"], "")
    head = f"{icon} {lab:<12} {r['source']:<34}"
    el = f" · {r['elapsed']:.1f}s" if r.get("elapsed") is not None else ""
    if not r["ok"]:
        return f"{head} lỗi: {r.get('error') or '?'}{el}" + (f" · {r['note']}" if r.get("note") else "")
    parts = [f"{_fmt_val(r.get('value'))} {r.get('unit') or ''}".rstrip()] if r.get("value") is not None else []
    if r.get("as_of"):
        parts.append(f"ngày {r['as_of']} (trễ {lag_days(r, today)}d)")
    if r.get("first"):
        parts.append(f"từ {r['first']}" + (f" ({r['n']} điểm)" if r.get("n") else ""))
    if r.get("note"):
        parts.append(r["note"])
    return f"{head} " + " · ".join(parts) + el


_STAGE_TITLE = {"python": "Python trực tiếp (miễn phí)", "sponsor": "Gói vnstock_data / vnii / vnstock",
                "local": "Cache kho đang có", "mcp": "MCP Finhay + SSI (claude -p)"}


def report(results: list, today: date, mcp_info: "dict | None" = None) -> str:
    out = [f"probe_assets · {datetime.now(VN_TZ):%Y-%m-%d %H:%M} · máy "
           f"{os.environ.get('COMPUTERNAME') or socket.gethostname()}"]
    for st in STAGES:
        rows = [r for r in results if r["stage"] == st]
        if not rows and not (st == "mcp" and mcp_info):
            continue
        out.append(f"\n== {_STAGE_TITLE[st]} ==")
        if st == "mcp" and mcp_info:
            out.append(f"   lượt claude -p: gọi {mcp_info.get('called')}/{mcp_info.get('planned')} tool · "
                       f"model {mcp_info.get('model')} · {mcp_info.get('elapsed_s')}s · "
                       f"chi phí quy đổi ${mcp_info.get('cost_usd')} · lỗi {mcp_info.get('error')}"
                       + (f" · bị chặn {mcp_info.get('denials')}" if mcp_info.get("denials") else ""))
        out.extend(fmt_row(r, today) for r in rows)
    der = derived_lines(results)
    if der:
        out.append("\n== Suy ra ==")
        out.extend(f"• {x}" for x in der)
    out.append("\n== Kết luận theo tài sản ==")
    out.extend(conclusions(results, today))
    return "\n".join(out)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="P0 đa tài sản: đo nguồn vàng/dầu/USD (chỉ đọc)")
    ap.add_argument("--mcp", action="store_true", help="chạy cả tầng MCP (1 lượt claude -p)")
    ap.add_argument("--only", action="append", choices=STAGES, help="chỉ chạy tầng này (lặp được)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="giây mỗi request HTTP")
    ap.add_argument("--mcp-timeout", type=int, default=DEFAULT_MCP_TIMEOUT_S)
    ap.add_argument("--no-calls", action="store_true", help="tầng sponsor chỉ liệt kê, không gọi thử")
    ap.add_argument("--json", metavar="PATH", help="ghi thêm kết quả thô ra file này")
    a = ap.parse_args(argv)
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    stages = set(a.only or ["python", "sponsor", "local"] + (["mcp"] if a.mcp else []))
    today = datetime.now(VN_TZ).date()
    ctx = Ctx(today=today, timeout=a.timeout, fred_key=(os.environ.get("FRED_API_KEY") or "").strip())
    results: list = []
    mcp_info = None
    if "python" in stages:
        print("… tầng python (HTTP song song)", flush=True)
        results += run_python_stage(ctx)
    if "sponsor" in stages:
        print("… tầng sponsor (dò gói vnstock)", flush=True)
        results += probe_sponsor(today, calls=not a.no_calls)
    if "local" in stages:
        results += probe_local()
    if "mcp" in stages:
        print(f"… tầng mcp (một lượt claude -p, tối đa {a.mcp_timeout}s)", flush=True)
        mres, mcp_info = run_mcp_stage(today, timeout_s=a.mcp_timeout)
        results += mres
    print(report(results, today, mcp_info))
    if a.json:
        Path(a.json).write_text(json.dumps({"today": today.isoformat(), "results": results,
                                            "mcp_info": mcp_info}, ensure_ascii=False, indent=1,
                                           default=str), encoding="utf-8")
        print(f"\n(đã ghi {a.json})")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
