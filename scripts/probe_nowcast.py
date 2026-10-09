#!/usr/bin/env python3
"""
scripts/probe_nowcast.py — P0b đa tài sản: ƯỚC TÍNH HÔM NAY cho chuỗi CHẬM + đo sai số (09/10)
==============================================================================================
User 09/10: Brent/WTI giao ngay (EIA qua FRED, trễ ~3–9 ngày) và chỉ số USD rộng (Fed H.10, trễ
≤7 ngày) chậm quá. Không có nguồn miễn phí nào nhanh hơn cho CHÍNH các chuỗi đó (Dated Brent là
định giá Platts/Argus trả phí; EIA và Fed công bố theo TUẦN) ⇒ hướng giải: NEO vào số chính thức
gần nhất rồi nhân với biến động của một chuỗi CÓ NGAY trong ngày. Script này ĐO trên lịch sử thật
xem sai bao nhiêu trước khi đưa lên dashboard (chỉ đọc, không ghi kho):

  usd    Tự tính lại chỉ số USD rộng mỗi ngày: trọng số chính thức Fed (trang H.10 weights, 26
         tiền tệ) × tỷ giá ngày của currency-api (bản lưu theo ngày trên jsdelivr). Ước tính
         = số Fed gần nhất × Π(tỷ giá hôm nay / tỷ giá ngày đó)^trọng số. Thử lệch pha −1/0/+1
         ngày (giờ chốt tỷ giá khác nhau), báo sai số theo số phiên kể từ số Fed gần nhất.
  oil    Ước tính Brent/WTI giao ngay EIA = số EIA gần nhất × (HĐTL tháng gần hôm nay / HĐTL
         ngày đó), HĐTL lấy Yahoo BZ=F/CL=F 3 năm. Sai số cả giai đoạn và 120 ngày gần nhất
         (chênh giao ngay − HĐTL đang lớn thì ước tính dễ sai). In chênh CÙNG NGÀY gần nhất.
  curve  Đường cong HĐTL Yahoo (BZ/CL tháng cụ thể, `.NYM`): M1…M8 và chênh M1−M2, M1−M6 —
         thước đo "thị trường vật chất căng" THỜI GIAN THỰC, thay vai trò của giá giao ngay.
  opec   Giá rổ OPEC theo ngày (giá dầu vật chất, công bố sau 1 ngày) — URL ứng viên.

🖥️ DESKTOP (có FRED_API_KEY trong .env, như probe_assets):

    python scripts/probe_nowcast.py              # đủ 4 phần (~1–3 phút, ~200 request nhỏ)
    python scripts/probe_nowcast.py --only usd   # một phần
    python scripts/probe_nowcast.py --json nowcast.json

Dán TOÀN BỘ output cho Claude. Exit: 0 = mọi phần có kết quả · 1 = một phần · 2 = không phần nào.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import probe_assets as pa  # noqa: E402  (Ctx, http, FRED, Yahoo, scrub — một chỗ)

PARTS = ("usd", "oil", "curve", "opec")
HORIZONS = (1, 2, 3, 5)                # số phiên chính thức kể từ điểm neo
SHIFTS = (-1, 0, 1)                    # lệch pha ngày của chuỗi dẫn
USD_DAYS = 160                         # lịch sử tỷ giá tải về (ngày lịch)
OIL_RECENT_DAYS = 120
# Ngưỡng p90 (%): ≤ tốt ⇒ hiện như số; ≤ tạm ⇒ hiện kèm dải sai số; lớn hơn ⇒ không hiện.
THRESHOLDS = {"usd": (0.15, 0.40), "oil": (1.0, 3.0)}

# ── Chỉ số USD rộng của Fed ──────────────────────────────────────────────────
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
FX_HIST_URLS = ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.json",
                "https://{d}.currency-api.pages.dev/v1/currencies/usd.json")
FX_LATEST_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"


class _Tables(HTMLParser):
    """Gom mọi bảng HTML thành list[list[list[str]]] (bảng → dòng → ô th/td)."""

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
    """(năm, {mã tiền tệ: trọng số chuẩn hoá tổng 1}) từ bảng có cột năm; lấy cột NĂM MỚI NHẤT."""
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
        off = len(hdr)                       # dòng dữ liệu có thể dài hơn tiêu đề 1 ô (nhãn)
        raw: dict = {}
        for row in table[hdr_i + 1:]:
            if not row:
                continue
            label = row[0].lower()
            ccy = next((c for k, c in FED_COUNTRY_CCY if k in label), None)
            j = col + (len(row) - off)
            v = pa._num(row[j]) if ccy and 0 <= j < len(row) else None
            if ccy and v is not None and ccy not in raw:
                raw[ccy] = v
        if len(raw) >= 20:
            tot = sum(raw.values())
            return years[col], {c: v / tot for c, v in raw.items()}
    raise ValueError("không thấy bảng trọng số có ≥20 tiền tệ")


def parse_usd_rates(payload) -> "dict[str, float]":
    usd = (payload or {}).get("usd") if isinstance(payload, dict) else None
    return {k.lower(): float(v) for k, v in (usd or {}).items()
            if isinstance(v, (int, float)) and v > 0}


def replica_index(fx_by_date: "dict[str, dict]", weights: "dict[str, float]",
                  max_missing: float = 0.02) -> "dict[str, float]":
    """Chỉ số tự tính, nối chuỗi từ 1,0: ln I_t − ln I_{t−1} = Σ w_c · ln(e_c,t / e_c,t−1),
    e = đơn vị ngoại tệ trên 1 USD (USD mạnh lên ⇒ chỉ số tăng, đúng chiều Fed). Ngày thiếu
    tiền tệ có tổng trọng số > max_missing ⇒ bỏ ngày đó (không ghi, không đổi mốc so)."""
    out, level, prev = {}, 1.0, None
    for d in sorted(fx_by_date):
        rates = fx_by_date[d]
        if prev is None:
            if sum(w for c, w in weights.items() if c in rates) >= 1 - max_missing:
                out[d], prev = level, rates
            continue
        have = {c: w for c, w in weights.items() if c in rates and c in prev}
        if sum(have.values()) < 1 - max_missing:
            continue
        tot = sum(have.values())
        level *= math.exp(sum(w / tot * math.log(rates[c] / prev[c]) for c, w in have.items()))
        out[d], prev = level, rates
    return out


# ── Sai số ước tính (chung cho USD và dầu) ───────────────────────────────────
def _shifted(driver: "dict[str, float]", d: str, shift: int) -> "float | None":
    return driver.get((date.fromisoformat(d) + timedelta(days=shift)).isoformat())


def nowcast_errors(official: "dict[str, float]", driver: "dict[str, float]",
                   horizons=HORIZONS, shift: int = 0, since: "str | None" = None) -> "dict[int, list]":
    """ước tính(t0+h) = chính thức(t0) × dẫn(t0+h)/dẫn(t0); sai % so với chính thức(t0+h).
    h đếm theo QUAN SÁT chính thức (phiên), không theo ngày lịch."""
    days = sorted(official)
    out = {h: [] for h in horizons}
    for i, t0 in enumerate(days):
        if since and t0 < since:
            continue
        d0 = _shifted(driver, t0, shift)
        if not d0:
            continue
        for h in horizons:
            if i + h >= len(days):
                break
            t1 = days[i + h]
            d1 = _shifted(driver, t1, shift)
            if d1:
                est = official[t0] * d1 / d0
                out[h].append((est / official[t1] - 1) * 100)
    return out


def err_stats(errs: list) -> "dict | None":
    if not errs:
        return None
    a = sorted(abs(e) for e in errs)
    return {"n": len(a), "med": round(statistics.median(a), 3),
            "p90": round(a[min(len(a) - 1, int(0.9 * len(a)))], 3), "max": round(a[-1], 3)}


def best_shift(official, driver, horizons=HORIZONS, shifts=SHIFTS, since=None) -> "tuple[int, dict]":
    """Lệch pha cho trung vị |sai| ở h nhỏ nhất thấp nhất → (shift, {h: stats}). So trên số
    CHƯA làm tròn; hoà thì ưu tiên lệch pha gần 0."""
    best = None
    for s in shifts:
        errs = nowcast_errors(official, driver, horizons, s, since)
        first = errs[horizons[0]]
        if not first:
            continue
        key = (statistics.median(abs(e) for e in first), abs(s))
        if best is None or key < best[0]:
            best = (key, s, {h: err_stats(v) for h, v in errs.items()})
    return (best[1], best[2]) if best else (0, {h: None for h in horizons})


def nowcast_today(official: "dict[str, float]", driver: "dict[str, float]", shift: int = 0) -> "dict | None":
    """Neo số chính thức MỚI NHẤT có dẫn cùng ngày, nhân biến động dẫn tới điểm dẫn mới nhất."""
    last_drv = max(driver) if driver else None
    for t0 in sorted(official, reverse=True):
        d0 = _shifted(driver, t0, shift)
        if d0 and last_drv:
            return {"anchor_date": t0, "anchor": official[t0], "driver_date": last_drv,
                    "value": official[t0] * driver[last_drv] / d0}
    return None


def verdict(stats: dict, part: str, h: int) -> str:
    good, ok = THRESHOLDS[part]
    st = stats.get(h)
    if not st:
        return "chưa đủ dữ liệu"
    if st["p90"] <= good:
        return f"TỐT (p90 {st['p90']}% ≤ {good}%)"
    if st["p90"] <= ok:
        return f"TẠM — hiện kèm dải sai số (p90 {st['p90']}%)"
    return f"KHÔNG NÊN dùng làm số (p90 {st['p90']}% > {ok}%)"


# ── Tải dữ liệu ──────────────────────────────────────────────────────────────
def fred_history(ctx: "pa.Ctx", sid: str, limit: int) -> "dict[str, float]":
    st, txt = ctx.get(pa.FRED_BASE, params={"series_id": sid, "api_key": ctx.fred_key,
                                            "file_type": "json", "sort_order": "desc", "limit": limit})
    if st != 200:
        raise RuntimeError(pa._http_err(st, txt))
    return dict(pa.fred_values(json.loads(txt)))


def yahoo_history(ctx: "pa.Ctx", sym: str, rng: str = "3y") -> "dict[str, float]":
    from urllib.parse import quote
    st, txt = ctx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}"
                      f"?range={rng}&interval=1d")
    if st != 200:
        raise RuntimeError(pa._http_err(st, txt))
    return dict(pa.parse_yahoo_chart(json.loads(txt)))


def fetch_fx_history(ctx: "pa.Ctx", days: "list[date]") -> "dict[str, dict]":
    def one(d: date):
        for url in FX_HIST_URLS:
            with contextlib.suppress(Exception):
                st, txt = ctx.get(url.format(d=d.isoformat()))
                if st == 200:
                    rates = parse_usd_rates(json.loads(txt))
                    if rates:
                        return d.isoformat(), rates
        return d.isoformat(), None
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(one, days))
    return {d: r for d, r in got if r}


# ── Các phần ─────────────────────────────────────────────────────────────────
def part_usd(ctx: "pa.Ctx") -> dict:
    res: dict = {"part": "usd"}
    if not ctx.fred_key:
        return {**res, "error": "thiếu FRED_API_KEY (cần số Fed chính thức để so)"}
    html, err = None, None
    for url in FED_WEIGHTS_URLS:
        try:
            st, txt = ctx.get(url)
            if st == 200:
                year, weights = parse_fed_weights(txt)
                res.update(weights_year=year, n_ccy=len(weights), weights_url=url,
                           top=sorted(weights.items(), key=lambda kv: -kv[1])[:6])
                html = txt
                break
            err = pa._http_err(st, txt)
        except Exception as e:                               # noqa: BLE001
            err = pa.scrub(e)
    if html is None:
        return {**res, "error": f"trọng số Fed: {err}"}
    missing = [c for k, c in FED_COUNTRY_CCY if c not in weights]
    res["missing_ccy"] = missing
    official = fred_history(ctx, "DTWEXBGS", 140)
    days = [ctx.today - timedelta(days=i) for i in range(USD_DAYS, -1, -1)]
    fx = fetch_fx_history(ctx, days)
    with contextlib.suppress(Exception):
        st, txt = ctx.get(FX_LATEST_URL)
        latest = parse_usd_rates(json.loads(txt)) if st == 200 else {}
        if latest and ctx.today.isoformat() not in fx:
            fx[ctx.today.isoformat()] = latest
    res["fx_days"] = len(fx)
    rep = replica_index(fx, weights)
    res["replica_days"] = len(rep)
    shift, stats = best_shift(official, rep)
    res.update(shift=shift, stats=stats, official_last=max(official) if official else None)
    res["today"] = nowcast_today(official, rep, shift)
    res["verdict"] = {h: verdict(stats, "usd", h) for h in HORIZONS}
    return res


def part_oil(ctx: "pa.Ctx") -> dict:
    res: dict = {"part": "oil", "series": {}}
    if not ctx.fred_key:
        return {**res, "error": "thiếu FRED_API_KEY"}
    since = (ctx.today - timedelta(days=OIL_RECENT_DAYS)).isoformat()
    for name, sid, fut in (("Brent", "DCOILBRENTEU", "BZ=F"), ("WTI", "DCOILWTICO", "CL=F")):
        one: dict = {}
        try:
            spot = fred_history(ctx, sid, 800)
            fut_h = yahoo_history(ctx, fut, "3y")
        except Exception as e:                               # noqa: BLE001
            res["series"][name] = {"error": pa.scrub(e, (ctx.fred_key,))}
            continue
        common = sorted(set(spot) & set(fut_h))
        if common:
            d = common[-1]
            one["basis"] = {"date": d, "spot": spot[d], "fut": fut_h[d],
                            "pct": round((spot[d] / fut_h[d] - 1) * 100, 2)}
        shift, all_st = best_shift(spot, fut_h)
        one.update(shift=shift, stats_all=all_st,
                   stats_recent={h: err_stats(v) for h, v in
                                 nowcast_errors(spot, fut_h, HORIZONS, shift, since).items()},
                   spot_last=max(spot), today=nowcast_today(spot, fut_h, shift))
        one["verdict"] = {h: verdict(one["stats_recent"], "oil", h) for h in HORIZONS}
        res["series"][name] = one
    return res


MONTH_CODES = "FGHJKMNQUVXZ"


def contract_tickers(root: str, today: date, n: int = 8, suffix: str = ".NYM") -> "list[tuple[str, str]]":
    """[(nhãn tháng, mã Yahoo)] cho n tháng giao hàng tính từ tháng hiện tại, vd CLZ26.NYM."""
    out = []
    for k in range(n):
        m0 = today.month - 1 + k
        y, m = today.year + m0 // 12, m0 % 12 + 1
        out.append((f"{m:02d}/{y}", f"{root}{MONTH_CODES[m - 1]}{y % 100:02d}{suffix}"))
    return out


def curve_spreads(points: "list[dict]") -> dict:
    """points sắp theo tháng giao hàng, mỗi điểm {label, ticker, close, date}."""
    if len(points) < 2:
        return {}
    m1 = points[0]["close"]

    def sp(i):
        if i >= len(points):
            return None
        return {"to": points[i]["label"], "usd": round(m1 - points[i]["close"], 2),
                "pct": round((m1 / points[i]["close"] - 1) * 100, 2)}
    return {"m1_m2": sp(1), "m1_m6": sp(5) or sp(len(points) - 1),
            "shape": "BACKWARDATION (gần đắt hơn xa — vật chất căng)" if m1 > points[1]["close"]
            else "CONTANGO (gần rẻ hơn xa — dư cung)"}


def part_curve(ctx: "pa.Ctx") -> dict:
    res: dict = {"part": "curve", "curves": {}}
    fresh = (ctx.today - timedelta(days=5)).isoformat()
    for name, root in (("Brent", "BZ"), ("WTI", "CL")):
        pts, errs = [], []
        for label, tk in contract_tickers(root, ctx.today):
            try:
                h = yahoo_history(ctx, tk, "5d")
            except Exception as e:                           # noqa: BLE001
                errs.append(f"{tk}: {pa.scrub(e)[:40]}")
                continue
            d = max(h)
            if d >= fresh:
                pts.append({"label": label, "ticker": tk, "close": h[d], "date": d})
        res["curves"][name] = {"points": pts, "spreads": curve_spreads(pts), "errors": errs[:3]}
    return res


OPEC_URLS = ("https://www.opec.org/basket/basketDayArchives.xml",
             "https://www.opec.org/opec_web/en/data_graphs/40.htm")
_OPEC_XML_RE = re.compile(r'data="(\d{4}-\d{2}-\d{2})"\s+val="([\d.]+)"')


def parse_opec_xml(text: str) -> "list[tuple[str, float]]":
    return sorted((d, float(v)) for d, v in _OPEC_XML_RE.findall(text or ""))


def part_opec(ctx: "pa.Ctx") -> dict:
    tries = []
    for url in OPEC_URLS:
        try:
            st, txt = ctx.get(url)
        except Exception as e:                               # noqa: BLE001
            tries.append(f"{pa._host(url)}: {pa.scrub(e)[:80]}")
            continue
        pts = parse_opec_xml(txt) if st == 200 else []
        if pts:
            return {"part": "opec", "url": url, "last": pts[-1], "first": pts[0], "n": len(pts)}
        snippet = re.sub(r"[\s<>]+", " ", txt or "")[:60]
        tries.append(f"{url[-40:]}: HTTP {st}, không thấy dạng data=… val=… ({snippet})")
    return {"part": "opec", "error": " | ".join(tries)}


PART_FUNCS = {"usd": part_usd, "oil": part_oil, "curve": part_curve, "opec": part_opec}


# ── In ───────────────────────────────────────────────────────────────────────
def _st(st) -> str:
    return "—" if not st else f"trung vị {st['med']}% · p90 {st['p90']}% · max {st['max']}% (n={st['n']})"


def _stats_lines(stats: dict, indent="   ") -> list:
    return [f"{indent}h={h} phiên: {_st(stats.get(h))}" for h in HORIZONS]


def report(results: dict, today: date) -> str:
    out = [f"probe_nowcast · {datetime.now(pa.VN_TZ):%Y-%m-%d %H:%M} · máy "
           f"{os.environ.get('COMPUTERNAME') or pa.socket.gethostname()}"]
    u = results.get("usd")
    if u:
        out.append("\n== Chỉ số USD rộng (Fed DTWEXBGS): tự tính hằng ngày ==")
        if u.get("error"):
            out.append(f"❌ {u['error']}")
        else:
            top = " · ".join(f"{c.upper()} {w * 100:.1f}%" for c, w in u["top"])
            out.append(f"   trọng số Fed năm {u['weights_year']}: {u['n_ccy']}/26 tiền tệ"
                       + (f" (thiếu {', '.join(u['missing_ccy'])})" if u["missing_ccy"] else "")
                       + f" · lớn nhất: {top}")
            out.append(f"   tỷ giá currency-api: {u['fx_days']} ngày · chỉ số tự tính: {u['replica_days']} ngày · "
                       f"lệch pha tốt nhất {u['shift']:+d} ngày · số Fed mới nhất {u['official_last']}")
            out.append("   sai số ước tính so với số Fed (h = số phiên kể từ số Fed gần nhất):")
            out.extend(_stats_lines(u["stats"]))
            t = u.get("today")
            if t:
                out.append(f"   ⇒ ƯỚC TÍNH {t['driver_date']}: {t['value']:,.2f} (neo Fed {t['anchor']:,.2f} ngày "
                           f"{t['anchor_date']})")
            out.append(f"   đánh giá h=5: {u['verdict'][5]}")
    o = results.get("oil")
    if o:
        out.append("\n== Dầu giao ngay EIA (FRED): ước tính từ HĐTL tháng gần (Yahoo) ==")
        if o.get("error"):
            out.append(f"❌ {o['error']}")
        for name, s in (o.get("series") or {}).items():
            if s.get("error"):
                out.append(f"❌ {name}: {s['error']}")
                continue
            b = s.get("basis")
            out.append(f"   {name}: giao ngay EIA mới nhất {s['spot_last']}"
                       + (f" · CÙNG NGÀY {b['date']}: giao ngay {b['spot']} vs HĐTL {b['fut']} ⇒ {b['pct']:+.2f}%"
                          if b else ""))
            out.append(f"   cả 3 năm (lệch pha {s['shift']:+d}):")
            out.extend(_stats_lines(s["stats_all"], "      "))
            out.append(f"   {OIL_RECENT_DAYS} ngày gần nhất:")
            out.extend(_stats_lines(s["stats_recent"], "      "))
            t = s.get("today")
            if t:
                out.append(f"   ⇒ ƯỚC TÍNH {t['driver_date']}: {t['value']:,.2f} (neo EIA {t['anchor']:,.2f} ngày "
                           f"{t['anchor_date']})")
            out.append(f"   đánh giá h=3 (120 ngày): {s['verdict'][3]}")
    c = results.get("curve")
    if c:
        out.append("\n== Đường cong HĐTL (Yahoo, mã tháng .NYM) — thời gian thực ==")
        for name, cv in (c.get("curves") or {}).items():
            pts = cv["points"]
            if not pts:
                out.append(f"❌ {name}: không mã tháng nào có giá ≤5 ngày ({'; '.join(cv['errors'])})")
                continue
            out.append(f"   {name}: " + " · ".join(f"{p['ticker']} {p['close']:,.2f}" for p in pts)
                       + f" (ngày {pts[0]['date']})")
            sp = cv["spreads"]
            if sp:
                parts = [f"M1−M2 {sp['m1_m2']['usd']:+.2f}$ ({sp['m1_m2']['pct']:+.2f}%)"]
                if sp.get("m1_m6"):
                    parts.append(f"M1−{sp['m1_m6']['to']} {sp['m1_m6']['usd']:+.2f}$ ({sp['m1_m6']['pct']:+.2f}%)")
                out.append(f"      {' · '.join(parts)} ⇒ {sp['shape']}")
    p = results.get("opec")
    if p:
        out.append("\n== Giá rổ OPEC theo ngày ==")
        out.append(f"❌ {p['error']}" if p.get("error") else
                   f"✅ {p['last'][1]} USD/thùng ngày {p['last'][0]} · từ {p['first'][0]} ({p['n']} điểm) · {p['url']}")
    return "\n".join(out)


def exit_code(results: dict) -> int:
    def ok(r):
        if not r or r.get("error"):
            return False
        if r.get("part") == "oil":
            return any(not s.get("error") for s in r["series"].values())
        if r.get("part") == "curve":
            return any(cv["points"] for cv in r["curves"].values())
        return True
    good = [ok(r) for r in results.values()]
    return 2 if not any(good) else (0 if all(good) else 1)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="P0b: ước tính hôm nay cho chuỗi chậm + sai số (chỉ đọc)")
    ap.add_argument("--only", action="append", choices=PARTS)
    ap.add_argument("--timeout", type=int, default=pa.DEFAULT_TIMEOUT_S)
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args(argv)
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv
        load_dotenv(pa._REPO / ".env", override=False)
    ctx = pa.Ctx(today=datetime.now(pa.VN_TZ).date(), timeout=a.timeout,
                 fred_key=(os.environ.get("FRED_API_KEY") or "").strip())
    results = {}
    for part in (a.only or PARTS):
        print(f"… {part}", flush=True)
        t0 = time.monotonic()
        try:
            results[part] = PART_FUNCS[part](ctx)
        except Exception as e:                               # noqa: BLE001
            results[part] = {"part": part, "error": pa.scrub(f"{type(e).__name__}: {e}", (ctx.fred_key,))}
        results[part]["elapsed"] = round(time.monotonic() - t0, 1)
    print(report(results, ctx.today))
    if a.json:
        Path(a.json).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\n(đã ghi {a.json})")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
