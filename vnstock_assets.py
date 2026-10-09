#!/usr/bin/env python3
"""vnstock_assets.py — KHO ĐA TÀI SẢN vàng · dầu · USD (P1, U82).

Thiết kế + quyết định user: `docs/THIET-KE-DA-TAI-SAN.md` (§4c bảng nguồn, §4d chuẩn độ tươi,
§4e kết quả đo). Ba luật không nhượng bộ:

1. **Mỗi chuỗi = MỘT công cụ.** Giao ngay ≠ hợp đồng tương lai (Brent giao ngay EIA 125 vs
   HĐTL 103 ngày 06/10): nguồn của một chuỗi phải báo CÙNG công cụ; hai nguồn lệch quá
   `xtol_pct` khi lấy gần nhau ⇒ cờ trong `_meta/assets_status.json`, không nối lặng lẽ.
2. **Số quốc tế phải có TRONG NGÀY** (user 09/10). Chuỗi gốc chậm (EIA, Fed H.10) chỉ được
   hiện qua chuỗi `*_EST` — ước tính neo số chính thức gần nhất × biến động một chuỗi sống,
   kèm dải sai số ĐÃ ĐO; quá ngưỡng ⇒ không ghi (ẩn). Brent giao ngay không ước tính được
   (p90 5,7%) ⇒ `display="hide"`, màn chính dùng đường cong HĐTL.
3. **Kho riêng, một máy ghi.** `data_warehouse/assets/<KHOÁ>/<YYYY>.parquet` (Dropbox); KHÔNG
   vào registry 13 chỉ số vĩ mô. Ghi từ 🖥️ desktop (task tin mỗi giờ + pipeline đêm); khoá
   theo máy chặn hai tiến trình cùng ghi.

Luật gộp khi một ngày đã có dòng từ nguồn khác: ngày ≥ hôm qua (giá trong ngày) ⇒ bản lấy
MỚI hơn thắng; ngày cũ hơn ⇒ theo thứ tự ưu tiên `Spec.sources`.

Nhịp: nguồn Python MỖI GIỜ (`hourly`, gọi từ task News Alert qua `run.py news-alert`) +
MCP Finhay/SSI vào các giờ `VNSTOCK_ASSETS_MCP_HOURS` (mặc định 9,11,14,16,20 giờ VN) qua
`vnstock_assets_mcp`. Pipeline đêm có thêm bước `assets` (sau gold) và `assets-mcp` (sau
brief). Kill-switch: `VNSTOCK_ASSETS=0` (tất cả) · `VNSTOCK_ASSETS_HOURLY=0` · `VNSTOCK_ASSETS_MCP=0`.

CLI: `--refresh` · `--mcp` · `--hourly` · `--backfill [--with-mcp] [--vcb-days N] [--steps …]` ·
`--mcp-backfill [--only KHOÁ,KHOÁ]` (chỉ lịch sử MCP, chạy lại phần hỏng) · `--show`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import vnstock_assets_sources as src

_REPO = Path(__file__).resolve().parent
ASSETS_DIR = _REPO / "data_warehouse" / "assets"
META_DIR = _REPO / "data_warehouse" / "_meta"
LOCK_DIR = Path(tempfile.gettempdir())        # khoá THEO MÁY — không đi qua Dropbox
STATUS_NAME = "assets_status.json"
FX_CACHE_NAME = "assets_fx_days.json"
WEIGHTS_CACHE_NAME = "assets_fed_weights.json"
SOURCES_LEDGER_NAME = "assets_sources.json"     # P3: giá từng NGUỒN theo ngày, để đối chiếu
SCHEMA = 1

ENV_SWITCH = "VNSTOCK_ASSETS"
ENV_HOURLY = "VNSTOCK_ASSETS_HOURLY"
ENV_MCP = "VNSTOCK_ASSETS_MCP"
ENV_MCP_HOURS = "VNSTOCK_ASSETS_MCP_HOURS"
ENV_DEMOTE = "VNSTOCK_ASSETS_DEMOTE"            # "XAU:finhay,BRENT:finhay" — hạ ưu tiên nguồn bằng tay
DEFAULT_MCP_HOURS = (9, 11, 14, 16, 20)
_OFF = ("0", "false", "off", "no")

LUONG_OZ = 37.5 / 31.1034768      # 1 lượng = 37,5 g; 1 troy oz = 31,1034768 g
USD_BAND = 0.05                   # biên ±5% quanh tỷ giá trung tâm
RECENT_DAYS = 1                   # ngày ≥ hôm qua: bản lấy MỚI hơn thắng
XCHECK_WINDOW_H = 3               # dòng gần đây: chỉ so hai nguồn lấy cách nhau ≤ 3 giờ
XCHECK_KEEP = 60
FX_CACHE_DAYS = 40
FX_WINDOW_DAYS = 14               # số ngày tỷ giá cần cho ước tính USD rộng (neo trễ ≤7 ngày)
FX_REFETCH_DAYS = 3               # tải lại N ngày gần nhất mỗi lượt (file ngày có thể ra muộn/sửa)
WEIGHTS_MAX_AGE_D = 7
LOCK_STALE_S = 30 * 60
CURVE_MONTHS = 8
CURVE_FRESH_DAYS = 5

# Ước tính trong ngày — số đo P0b 🖥️ 09/10 20:20 (`scripts/probe_nowcast.py`, thiết kế §4e).
USD_BROAD_SHIFT = 1               # file currency-api ngày D+1 ↔ số Fed ngày D
USD_BROAD_BAND_PCT = 0.30         # p90 |sai| 0,28–0,31% ở MỌI h=1…5 phiên (nhiễu ngày, không trôi)
USD_BROAD_MAX_H = 10
WTI_SPOT_BAND_PCT = 1.64          # p90 ở h=3 phiên, 120 ngày gần nhất
WTI_SPOT_MAX_H = 3                # h=5 p90 3,86% > ngưỡng 3% ⇒ quá 3 phiên thì ẨN

# P3 — đối chiếu MCP ↔ Python (thiết kế §11): MCP Finhay/SSI là nguồn ưu tiên từ P1 (phương án
# LAI user duyệt 09/10); P3 KIỂM ĐỊNH nó trên ngày đã đóng: GATE_N phiên gần nhất lệch ≤ xtol_pct
# (cho phép 1 phiên lệch) ⇒ "đạt"; ≥2/GATE_N lệch ⇒ "lệch" ⇒ doctor réo + gợi ý VNSTOCK_ASSETS_DEMOTE.
MCP_SOURCES = ("finhay", "ssi")
LEDGER_DAYS = 45
GATE_N = 5
GATE_MAX_BAD = 1

COLUMNS = ["date", "open", "high", "low", "close", "bid", "ask", "contract",
           "source", "fetched_at", "meta"]
_NUM_COLS = ("open", "high", "low", "close", "bid", "ask")


def enabled(env: str = ENV_SWITCH) -> bool:
    return (os.environ.get(env) or "1").strip().lower() not in _OFF


# ── Registry ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    unit: str
    group: str                         # gold | oil | usd
    sources: tuple                     # ưu tiên cho NGÀY ĐÃ QUA, cao → thấp
    lo: float = 0.0
    hi: float = float("inf")
    weekends: bool = False             # thị trường có giao dịch cuối tuần không
    xtol_pct: "float | None" = None    # hai nguồn lệch quá ngưỡng ⇒ cờ
    display: str = "show"              # show | est (chỉ hiện qua *_EST) | hide
    curve: bool = False                # nhiều dòng/ngày theo kỳ hạn (cột contract)


def _gold(key: str, label: str, sources: tuple = ("finhay",)) -> Spec:
    return Spec(key, label, "VND/lượng", "gold", sources, 20e6, 1e9, weekends=True, xtol_pct=0.5)


DEALERS = ("SJC", "PNJ", "DOJI", "BTMC", "BTMH")
REGISTRY: "dict[str, Spec]" = {s.key: s for s in [
    Spec("XAU", "Vàng thế giới (giao ngay)", "USD/oz", "gold", ("finhay", "gold-api"),
         500, 20000, xtol_pct=0.5),
    _gold("GOLD_SJC_BAR", "SJC miếng", ("finhay", "sjc")),
    _gold("GOLD_SJC_RING", "SJC nhẫn"),
    _gold("GOLD_PNJ_BAR", "PNJ miếng"), _gold("GOLD_PNJ_RING", "PNJ nhẫn"),
    _gold("GOLD_DOJI_BAR", "DOJI miếng"), _gold("GOLD_DOJI_RING", "DOJI nhẫn"),
    _gold("GOLD_BTMC_BAR", "BTMC miếng"), _gold("GOLD_BTMC_RING", "BTMC nhẫn"),
    _gold("GOLD_BTMH_BAR", "BTMH miếng"), _gold("GOLD_BTMH_RING", "BTMH nhẫn"),
    Spec("BRENT", "Brent HĐTL tháng gần", "USD/thùng", "oil", ("finhay", "yahoo"), 5, 500, xtol_pct=1.0),
    Spec("WTI", "WTI HĐTL tháng gần", "USD/thùng", "oil", ("finhay", "yahoo"), 5, 500, xtol_pct=1.0),
    Spec("CURVE_BRENT", "Đường cong Brent (HĐTL theo tháng)", "USD/thùng", "oil", ("yahoo",),
         5, 500, curve=True),
    Spec("CURVE_WTI", "Đường cong WTI (HĐTL theo tháng)", "USD/thùng", "oil", ("yahoo",),
         5, 500, curve=True),
    Spec("BRENT_SPOT", "Brent giao ngay EIA", "USD/thùng", "oil", ("fred",), 5, 500, display="hide"),
    Spec("WTI_SPOT", "WTI giao ngay EIA", "USD/thùng", "oil", ("fred",), 5, 500, display="est"),
    Spec("WTI_SPOT_EST", "WTI giao ngay — ước tính trong ngày", "USD/thùng", "oil", ("est",), 5, 500),
    Spec("DXY", "DXY (ICE)", "điểm", "usd", ("yahoo",), 50, 200),
    Spec("USD_BROAD", "Chỉ số USD rộng (Fed)", "điểm (01/2006=100)", "usd", ("fred",), 50, 250,
         display="est"),
    Spec("USD_BROAD_EST", "Chỉ số USD rộng — ước tính trong ngày", "điểm (01/2006=100)", "usd",
         ("est",), 50, 250),
    Spec("USDVND", "USD/VND thị trường", "VND", "usd",
         ("finhay", "er-api", "currency-api", "yahoo"), 15000, 40000, xtol_pct=0.5),
    Spec("USDVND_VCB", "USD/VND Vietcombank (bán)", "VND", "usd", ("vcb", "ssi"), 15000, 40000,
         xtol_pct=0.3),
    Spec("USD_CENTRAL", "Tỷ giá trung tâm NHNN", "VND", "usd", ("mbk", "sbv-weekly"),
         15000, 40000, xtol_pct=0.1),
    # Mua/bán tham khảo Cục QLNH (SSI "SBVN") — KHÔNG phải trung tâm: (mua+bán)/2 lệch 0–7 đ (10/10).
    Spec("USD_SBV_REF", "Giá bán USD tham khảo NHNN (Cục QLNH)", "VND", "usd", ("ssi",),
         15000, 40000),
]}


# ── Kho Parquet ──────────────────────────────────────────────────────────────
def key_dir(key: str, base: "Path | None" = None) -> Path:
    return Path(base or ASSETS_DIR) / key


def _empty():
    import pandas as pd
    return pd.DataFrame(columns=COLUMNS)


def _read_year(kdir: Path, year: str):
    """Mọi file của năm (bản chính + bản Dropbox '(conflicted copy)'), khử trùng giữ
    bản lấy MỚI nhất theo (ngày, kỳ hạn)."""
    import pandas as pd
    frames = []
    for pf in sorted(kdir.glob(f"{year}*.parquet"), key=lambda p: p.stat().st_mtime):
        try:
            frames.append(pd.read_parquet(pf))
        except Exception as e:                                     # noqa: BLE001
            print(f"  [assets] ⚠ {pf.name} không đọc được ({type(e).__name__}) — bỏ qua")
    if not frames:
        return _empty()
    df = pd.concat(frames, ignore_index=True)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["contract"] = df["contract"].fillna("")
    df = df.sort_values("fetched_at", kind="stable").drop_duplicates(["date", "contract"], keep="last")
    return df[COLUMNS]


def load(key: str, *, start: "str | None" = None, base: "Path | None" = None):
    """DataFrame cột `COLUMNS`, sắp theo (ngày, kỳ hạn); rỗng khi chưa có."""
    import pandas as pd
    kdir = key_dir(key, base)
    if not kdir.exists():
        return _empty()
    years = sorted({p.name[:4] for p in kdir.glob("*.parquet") if p.name[:4].isdigit()})
    if start:
        years = [y for y in years if y >= start[:4]]
    frames = [_read_year(kdir, y) for y in years]
    frames = [f for f in frames if len(f)]
    if not frames:
        return _empty()
    df = pd.concat(frames, ignore_index=True)
    if start:
        df = df[df["date"] >= start]
    for c in _NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["date", "contract"]).reset_index(drop=True)


def series(key: str, *, start: "str | None" = None, base: "Path | None" = None) -> "dict[str, float]":
    """{ngày: close} — chuỗi một dòng/ngày (không dùng cho đường cong)."""
    df = load(key, start=start, base=base)
    return {str(d): float(c) for d, c in zip(df["date"], df["close"]) if c == c}


def _norm_row(row: dict, fetched_at: str) -> dict:
    r = {c: row.get(c) for c in COLUMNS}
    r["date"] = src.iso(r["date"])
    r["contract"] = r["contract"] or ""
    r["fetched_at"] = r["fetched_at"] or fetched_at
    if isinstance(r["meta"], (dict, list)):
        r["meta"] = json.dumps(r["meta"], ensure_ascii=False, sort_keys=True)
    for c in _NUM_COLS:
        r[c] = src.num(r[c])
    return r


def merge(existing, rows: list, spec: Spec, today: date, fetched_at: str) -> "tuple[object, list]":
    """Gộp `rows` vào `existing` (thuần). Trả (DataFrame, cờ). Xem luật gộp ở docstring module."""
    import pandas as pd
    demoted = demoted_sources(spec.key)
    order = [s for s in spec.sources if s not in demoted] + [s for s in spec.sources if s in demoted]
    rank = {s: i for i, s in enumerate(order)}
    # Luật 1 chốt bằng code: nguồn không khai trong Spec.sources ⇒ không vào chuỗi (dòng cũ
    # của nguồn đã gỡ — vd "ssi-sbvn" trong USD_CENTRAL trước 10/10 — rơi khỏi file ở lượt ghi kế).
    recs = [r for r in (existing.to_dict("records") if len(existing) else []) if r.get("source") in rank]
    idx = {(r["date"], r["contract"] or ""): i for i, r in enumerate(recs)}
    recent_from = (today - timedelta(days=RECENT_DAYS)).isoformat()
    flags = []
    for raw in rows:
        r = _norm_row(raw, fetched_at)
        val = r["close"]
        if not r["date"] or val is None:
            continue
        if r["source"] not in rank:
            flags.append({"key": spec.key, "date": r["date"], "kind": "source", "source": r["source"]})
            continue
        if not (spec.lo <= val <= spec.hi):
            flags.append({"key": spec.key, "date": r["date"], "kind": "sanity",
                          "source": r["source"], "value": val})
            continue
        if not spec.weekends and date.fromisoformat(r["date"]).weekday() >= 5:
            continue
        k = (r["date"], r["contract"])
        if k not in idx:
            idx[k] = len(recs)
            recs.append(r)
            continue
        old = recs[idx[k]]
        recent = r["date"] >= recent_from
        if old["source"] != r["source"] and spec.xtol_pct and src.num(old["close"]):
            near = True
            if recent:
                with contextlib.suppress(Exception):
                    gap = abs((datetime.fromisoformat(r["fetched_at"]) -
                               datetime.fromisoformat(str(old["fetched_at"]))).total_seconds())
                    near = gap <= XCHECK_WINDOW_H * 3600
            dev = (val / float(old["close"]) - 1) * 100
            if near and abs(dev) > spec.xtol_pct:
                flags.append({"key": spec.key, "date": r["date"], "kind": "xcheck",
                              "a_src": old["source"], "a": float(old["close"]),
                              "b_src": r["source"], "b": val, "dev_pct": round(dev, 3)})
        if old["source"] == r["source"]:
            recs[idx[k]] = r
        elif (r["source"] in demoted) != (old["source"] in demoted):
            if old["source"] in demoted:               # nguồn bị hạ tay luôn nhường, kể cả trong ngày
                recs[idx[k]] = r
        elif recent:
            if str(r["fetched_at"]) >= str(old["fetched_at"]):
                recs[idx[k]] = r
        elif rank.get(r["source"], 99) < rank.get(old["source"], 99):
            recs[idx[k]] = r
    df = pd.DataFrame(recs, columns=COLUMNS)
    return df.sort_values(["date", "contract"]).reset_index(drop=True), flags


def write(key: str, rows: list, *, today: date, fetched_at: "str | None" = None,
          base: "Path | None" = None) -> list:
    """Gộp rồi ghi nguyên tử theo năm; xoá bản '(conflicted copy)' của năm vừa ghi."""
    import pyarrow as pa
    from vnstock_parquet_io import write_table_atomic
    spec = REGISTRY[key]
    fetched_at = fetched_at or datetime.now().isoformat(timespec="seconds")
    by_year: dict = {}
    for r in rows or []:
        d = src.iso(r.get("date"))
        if d:
            by_year.setdefault(d[:4], []).append(r)
    if base is None:
        with contextlib.suppress(Exception):
            _ledger_record(spec, rows, fetched_at, today)
    kdir = key_dir(key, base)
    flags = []
    for year, yrows in sorted(by_year.items()):
        merged, f = merge(_read_year(kdir, year), yrows, spec, today, fetched_at)
        flags += f
        if not len(merged):
            continue
        for c in ("contract", "source", "fetched_at", "meta", "date"):
            merged[c] = merged[c].astype("object").where(merged[c].notna(), None)
        out = kdir / f"{year}.parquet"
        write_table_atomic(pa.Table.from_pandas(merged, preserve_index=False), out)
        for extra in kdir.glob(f"{year}*.parquet"):
            if extra != out:
                with contextlib.suppress(Exception):
                    extra.unlink()
    return flags


# ── P3: hạ ưu tiên bằng tay + sổ nguồn + đối chiếu ──────────────────────────
def demoted_sources(key: str) -> "set[str]":
    """Nguồn bị hạ ưu tiên cho `key` theo VNSTOCK_ASSETS_DEMOTE ("XAU:finhay,BRENT:finhay")."""
    out = set()
    for part in (os.environ.get(ENV_DEMOTE) or "").split(","):
        k, _, sname = part.strip().partition(":")
        if k.strip().upper() == key and sname.strip():
            out.add(sname.strip().lower())
    return out


def _cross_checked(spec: Spec) -> bool:
    """Chuỗi có cả nguồn MCP lẫn nguồn Python ⇒ đối chiếu được."""
    srcs = set(spec.sources) - {"est"}
    return not spec.curve and bool(srcs & set(MCP_SOURCES)) and bool(srcs - set(MCP_SOURCES))


def _ledger_record(spec: Spec, rows: list, fetched_at: str, today: date, meta=None) -> None:
    """Ghi giá TỪNG nguồn theo ngày (lượt lấy sau đè lượt trước cùng nguồn) — kho chỉ giữ bản
    thắng, nên không có sổ này thì không so được hai nguồn trên cùng một ngày đã đóng."""
    if not _cross_checked(spec):
        return
    lo = (today - timedelta(days=LEDGER_DAYS)).isoformat()
    hi = today.isoformat()
    got = [(src.iso(r.get("date")), r.get("source"), src.num(r.get("close")), r.get("fetched_at") or fetched_at)
           for r in rows or []]
    got = [g for g in got if g[0] and lo <= g[0] <= hi and g[1] in spec.sources and g[2]]
    if not got:
        return
    led = _read_json(SOURCES_LEDGER_NAME, meta)
    k = led.setdefault(spec.key, {})
    for d, sname, v, fa in got:
        cur = k.setdefault(d, {}).get(sname)
        if not cur or str(fa) >= str(cur[1]):
            k[d][sname] = [v, str(fa)]
    for key in list(led):
        led[key] = {d: v for d, v in led[key].items() if d >= lo}
    _write_json(SOURCES_LEDGER_NAME, led, meta)


def agreement(key: str, *, ledger: "dict | None" = None, today: "date | None" = None,
              meta=None) -> dict:
    """{"mcp~python": {...}} cho chuỗi đối chiếu được — chỉ ngày ĐÃ ĐÓNG (< hôm nay), GATE_N ngày
    chung gần nhất: n, số lệch > xtol, lệch lớn nhất, ngày cuối, trạng thái đạt/lệch/chưa đủ."""
    spec = REGISTRY[key]
    if not _cross_checked(spec):
        return {}
    today = today or date.today()
    led = (ledger if ledger is not None else _read_json(SOURCES_LEDGER_NAME, meta)).get(key) or {}
    tol = spec.xtol_pct or 0.5
    out = {}
    mcp = [s for s in spec.sources if s in MCP_SOURCES]
    alts = [s for s in spec.sources if s not in MCP_SOURCES and s != "est"]
    for m in mcp:
        for a in alts:
            devs = [(d, (by[m][0] / by[a][0] - 1) * 100) for d, by in sorted(led.items())
                    if d < today.isoformat() and m in by and a in by and by[a][0]]
            last = devs[-GATE_N:]
            bad = sum(1 for _, x in last if abs(x) > tol)
            status = ("chưa đủ" if len(last) < GATE_N else
                      ("lệch" if bad > GATE_MAX_BAD else "đạt"))
            out[f"{m}~{a}"] = {"n": len(devs), "window": len(last), "bad": bad, "tol_pct": tol,
                               "max_abs_pct": round(max((abs(x) for _, x in last), default=0.0), 3),
                               "last": {"date": last[-1][0], "dev_pct": round(last[-1][1], 3)} if last else None,
                               "status": status}
    return out


def agreement_all(*, today: "date | None" = None, meta=None) -> dict:
    """{khoá: {cặp: …}} cho mọi chuỗi đối chiếu được, kèm cặp tốt nhất (đạt > chưa đủ > lệch)."""
    led = _read_json(SOURCES_LEDGER_NAME, meta)
    return {k: agreement(k, ledger=led, today=today) for k, sp in REGISTRY.items() if _cross_checked(sp)}


def gate_summary(ag: dict) -> dict:
    """Một chuỗi ĐẠT khi có ít nhất một cặp đạt; LỆCH khi có cặp lệch mà không cặp nào đạt."""
    out = {"đạt": [], "lệch": [], "chưa đủ": []}
    for key, pairs in ag.items():
        st = {p["status"] for p in pairs.values()}
        out["đạt" if "đạt" in st else ("lệch" if "lệch" in st else "chưa đủ")].append(key)
    return out


# ── Trạng thái + khoá ────────────────────────────────────────────────────────
def status_path(meta: "Path | None" = None) -> Path:
    return Path(meta or META_DIR) / STATUS_NAME


def read_status(meta: "Path | None" = None) -> dict:
    try:
        return json.loads(status_path(meta).read_text(encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return {}


def update_status(section: str, payload: dict, flags: "list | None" = None,
                  meta: "Path | None" = None, now: "datetime | None" = None) -> dict:
    from vnstock_parquet_io import write_json_atomic
    st = read_status(meta)
    st.update(schema=SCHEMA, machine=os.environ.get("COMPUTERNAME") or socket.gethostname())
    st[section] = payload
    if flags:
        # Mỗi giờ nguồn Python gửi lại 5 phiên gần nhất ⇒ cùng một chỗ lệch sẽ lặp lại mỗi
        # lượt; chỉ ghi lần đầu (khoá: chuỗi, ngày, loại, hai nguồn) để sổ không ngập.
        at = (now or datetime.now()).isoformat(timespec="seconds")
        old = st.get("xcheck") or []
        seen = {_flag_id(f) for f in old}
        new = [{**f, "at": at} for f in flags if _flag_id(f) not in seen]
        st["xcheck"] = (old + new)[-XCHECK_KEEP:]
    write_json_atomic(st, status_path(meta))
    return st


def _flag_id(f: dict) -> tuple:
    return (f.get("key"), f.get("date"), f.get("kind"), f.get("a_src"), f.get("b_src"), f.get("source"))


@contextlib.contextmanager
def machine_lock(name: str = "vnstock_assets.lock"):
    """True khi giữ được khoá; False khi tiến trình khác (cùng máy) đang ghi kho tài sản."""
    p = Path(LOCK_DIR) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        if p.exists() and time.time() - p.stat().st_mtime > LOCK_STALE_S:
            p.unlink()
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        yield True
    finally:
        os.close(fd)
        with contextlib.suppress(Exception):
            p.unlink()


def _read_json(name: str, meta: "Path | None" = None) -> dict:
    try:
        return json.loads((Path(meta or META_DIR) / name).read_text(encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return {}


def _write_json(name: str, payload: dict, meta: "Path | None" = None) -> None:
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(payload, Path(meta or META_DIR) / name)


# ── Nguồn Python: mỗi tác vụ trả {khoá: [dòng]} ──────────────────────────────
def _row(d, close, source, **kw) -> dict:
    return {"date": src.iso(d), "close": close, "source": source, **kw}


def _yahoo_rows(sym: str, rng: str = "5d") -> list:
    return [_row(b["date"], b["close"], "yahoo", open=b["open"], high=b["high"], low=b["low"])
            for b in src.fetch_yahoo(sym, rng)]


def _curve_rows(root: str, today: date) -> list:
    fresh = (today - timedelta(days=CURVE_FRESH_DAYS)).isoformat()
    out = []
    for tk in src.contract_tickers(root, today, CURVE_MONTHS):
        with contextlib.suppress(Exception):
            bars = src.fetch_yahoo(tk, "5d")
            b = bars[-1]
            if b["date"] >= fresh:
                out.append(_row(b["date"], b["close"], "yahoo", contract=tk.split(".")[0]))
    if not out:
        raise RuntimeError(f"không mã tháng {root} nào có giá ≤{CURVE_FRESH_DAYS} ngày")
    return out


def python_tasks(today: date, fkey: str) -> "list[tuple[str, object]]":
    t = today.isoformat()

    def fred():
        if not fkey:
            raise RuntimeError("thiếu FRED_API_KEY trong .env")
        out = {}
        for key, sid in (("BRENT_SPOT", "DCOILBRENTEU"), ("WTI_SPOT", "DCOILWTICO"),
                         ("USD_BROAD", "DTWEXBGS")):
            out[key] = [_row(d, v, "fred") for d, v in src.fetch_fred(sid, fkey)]
        return out

    def usdvnd():
        try:
            return {"USDVND": [_row(t, src.fetch_er_api_vnd(), "er-api")]}
        except Exception:                                          # noqa: BLE001
            return {"USDVND": [_row(t, src.fetch_fx_latest()["vnd"], "currency-api")]}

    def vcb():
        v = src.fetch_vcb(t)
        return {"USDVND_VCB": [_row(t, v["sell"], "vcb", bid=v["transfer"], ask=v["sell"],
                                    meta={"cash": v["cash"]})]}

    def sjc():
        v = src.fetch_sjc(today)
        return {"GOLD_SJC_BAR": [_row(t, v["sell"], "sjc", bid=v["buy"], ask=v["sell"])]}

    def mbk():
        got = src.fetch_mbk_central((today - timedelta(days=14)).isoformat(), t)
        if not got:
            raise RuntimeError("vnstock_data không có / rỗng")
        return {"USD_CENTRAL": [_row(d, v, "mbk") for d, v in got]}

    return [
        ("gold-api", lambda: {"XAU": [_row(t, src.fetch_gold_api(), "gold-api")]}),
        ("yahoo-brent", lambda: {"BRENT": _yahoo_rows("BZ=F")}),
        ("yahoo-wti", lambda: {"WTI": _yahoo_rows("CL=F")}),
        ("yahoo-dxy", lambda: {"DXY": _yahoo_rows("DX-Y.NYB")}),
        ("yahoo-usdvnd", lambda: {"USDVND": _yahoo_rows("VND=X")}),
        ("curve-brent", lambda: {"CURVE_BRENT": _curve_rows("BZ", today)}),
        ("curve-wti", lambda: {"CURVE_WTI": _curve_rows("CL", today)}),
        ("fred", fred), ("usdvnd", usdvnd), ("vcb", vcb), ("sjc", sjc), ("mbk", mbk),
    ]


def run_tasks(tasks: list, secrets: tuple = ()) -> "tuple[dict, dict]":
    """Chạy song song (I/O). Trả ({khoá: [dòng]}, {tác vụ: kết quả})."""
    def one(item):
        name, fn = item
        t0 = time.monotonic()
        try:
            got = fn() or {}
            return name, got, None, time.monotonic() - t0
        except Exception as e:                                     # noqa: BLE001
            return name, {}, src.scrub(f"{type(e).__name__}: {e}", secrets), time.monotonic() - t0
    rows: dict = {}
    report: dict = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for name, got, err, el in ex.map(one, tasks):
            for k, v in got.items():
                rows.setdefault(k, []).extend(v)
            report[name] = {"ok": err is None, "rows": sum(len(v) for v in got.values()),
                            "error": err, "elapsed_s": round(el, 1)}
    return rows, report


# ── Ước tính trong ngày ──────────────────────────────────────────────────────
def refresh_fx_cache(today: date, meta: "Path | None" = None, days: int = FX_WINDOW_DAYS) -> dict:
    """Bổ sung tỷ giá currency-api theo ngày còn thiếu + tải lại FX_REFETCH_DAYS ngày gần nhất
    + bản "latest" dưới khoá NGÀY GHI TRONG FILE, giữ FX_CACHE_DAYS ngày. 10/10 01:00 VN: bản
    latest vẫn là file 09/10 mà bị cất dưới khoá 10/10 và không bao giờ tải lại ⇒ chỉ số tự
    tính đứng một ngày."""
    cache = _read_json(FX_CACHE_NAME, meta)
    want = [(today - timedelta(days=i)).isoformat() for i in range(days, -1, -1)]
    recent = set(want[-(FX_REFETCH_DAYS + 1):])
    for d in want:
        if d not in cache or d in recent:
            with contextlib.suppress(Exception):
                cache[d] = src.fetch_fx_day(d)
    with contextlib.suppress(Exception):
        d, rates = src.fetch_fx_latest_dated()
        if d and d <= today.isoformat():
            cache[d] = rates
    keep = sorted(cache)[-FX_CACHE_DAYS:]
    cache = {d: cache[d] for d in keep}
    _write_json(FX_CACHE_NAME, cache, meta)
    return cache


def fed_weights(today: date, meta: "Path | None" = None) -> "tuple[int | None, dict, str | None]":
    """(năm, trọng số, lỗi lần tải gần nhất). Cache 7 ngày; tải hỏng ⇒ dùng bản cũ nếu có."""
    c = _read_json(WEIGHTS_CACHE_NAME, meta)
    err = None
    fresh = c.get("fetched") and (today - date.fromisoformat(c["fetched"])).days < WEIGHTS_MAX_AGE_D
    if not fresh:
        try:
            year, w = src.fetch_fed_weights()
            c = {"fetched": today.isoformat(), "year": year, "weights": w}
            _write_json(WEIGHTS_CACHE_NAME, c, meta)
        except Exception as e:                                     # noqa: BLE001
            err = src.scrub(f"{type(e).__name__}: {e}")[:160]
    return c.get("year"), c.get("weights") or {}, err


def estimate_usd_broad(official: dict, fx_days: dict, weights: dict,
                       weights_err: "str | None" = None) -> "tuple[dict | None, str | None]":
    """(ước tính, lý do ẩn) — lý do chỉ ĐÚNG khâu hỏng để đọc từ `--show` là biết sửa gì."""
    if not weights:
        return None, f"ẩn: thiếu trọng số Fed ({weights_err or 'chưa tải được'})"
    if not fx_days:
        return None, "ẩn: chưa có tỷ giá currency-api theo ngày (_meta/assets_fx_days.json)"
    # File currency-api ngày D+shift ↔ số Fed ngày D ⇒ chỉ giữ file ứng với NGÀY LÀM VIỆC của Fed:
    # ước tính mang ngày Fed (không phải ngày file — 10/10 ước tính ghi thứ Bảy bị kho cuối tuần
    # bỏ, `--show` in "chưa có dữ liệu") và `h` đếm PHIÊN, không đếm file cuối tuần.
    rep = {d: v for d, v in src.replica_index(fx_days, weights).items()
           if (date.fromisoformat(d) - timedelta(days=USD_BROAD_SHIFT)).weekday() < 5}
    if not rep:
        return None, (f"ẩn: chỉ số tự tính rỗng — {len(fx_days)} ngày tỷ giá, không ngày nào "
                      f"đủ {100 - 2:.0f}% trọng số")
    if not official:
        return None, "ẩn: chưa có số Fed (USD_BROAD) 60 ngày gần nhất"
    est = src.nowcast(official, rep, shift=USD_BROAD_SHIFT)
    if not est:
        return None, (f"ẩn: số Fed mới nhất {max(official)} chưa có tỷ giá ngày +{USD_BROAD_SHIFT} "
                      f"(chỉ số tự tính {min(rep)}→{max(rep)}, {len(rep)} ngày)")
    if est["h"] > USD_BROAD_MAX_H:
        return None, f"ẩn: {est['h']} phiên kể từ số Fed {est['anchor_date']} (> {USD_BROAD_MAX_H})"
    fed_day = (date.fromisoformat(est["driver_date"]) - timedelta(days=USD_BROAD_SHIFT)).isoformat()
    return {**est, "date": fed_day, "band_pct": USD_BROAD_BAND_PCT,
            "method": "trọng số Fed × currency-api"}, None


def estimate_wti_spot(official: dict, futures: dict) -> "tuple[dict | None, str | None]":
    """(ước tính, lý do ẩn). Quá WTI_SPOT_MAX_H phiên kể từ số EIA ⇒ ẩn."""
    est = src.nowcast(official, futures, shift=0)
    if not est:
        return None, "chưa đủ dữ liệu"
    if est["h"] > WTI_SPOT_MAX_H:
        return None, f"ẩn: {est['h']} phiên kể từ số EIA {est['anchor_date']} (> {WTI_SPOT_MAX_H})"
    return {**est, "band_pct": WTI_SPOT_BAND_PCT, "method": "EIA × biến động WTI HĐTL"}, None


def refresh_estimates(today: date, fetched_at: str, *, meta=None, base=None,
                      fx_days: "dict | None" = None) -> "tuple[dict, list]":
    out, flags = {}, []
    start = (today - timedelta(days=60)).isoformat()
    year, w, werr = fed_weights(today, meta)
    fx = fx_days if fx_days is not None else _read_json(FX_CACHE_NAME, meta)
    usd, why_usd = estimate_usd_broad(series("USD_BROAD", start=start, base=base), fx, w, werr)
    if usd:
        flags += write("USD_BROAD_EST", [_row(usd["date"], usd["value"], "est",
                                              meta={**usd, "weights_year": year})],
                       today=today, fetched_at=fetched_at, base=base)
        out["USD_BROAD_EST"] = {"value": round(usd["value"], 2), "date": usd["date"],
                                "anchor": usd["anchor"], "anchor_date": usd["anchor_date"],
                                "h": usd["h"], "band_pct": usd["band_pct"]}
    else:
        out["USD_BROAD_EST"] = {"hidden": why_usd}
    wti, why = estimate_wti_spot(series("WTI_SPOT", start=start, base=base),
                                 series("WTI", start=start, base=base))
    if wti:
        flags += write("WTI_SPOT_EST", [_row(wti["driver_date"], wti["value"], "est", meta=wti)],
                       today=today, fetched_at=fetched_at, base=base)
        out["WTI_SPOT_EST"] = {"value": round(wti["value"], 2), "date": wti["driver_date"],
                               "anchor": wti["anchor"], "anchor_date": wti["anchor_date"],
                               "h": wti["h"], "band_pct": wti["band_pct"]}
    else:
        out["WTI_SPOT_EST"] = {"hidden": why}
    return out, flags


# ── Một lượt Python / mỗi giờ / backfill ─────────────────────────────────────
def refresh_python(now: "datetime | None" = None, *, tasks: "list | None" = None,
                   base=None, meta=None) -> dict:
    if not enabled():
        return {"status": "disabled"}
    now = now or datetime.now()
    today = now.date()
    fetched_at = now.isoformat(timespec="seconds")
    fkey = src.fred_key()
    with machine_lock() as got:
        if not got:
            return {"status": "busy", "reason": "tiến trình khác trên máy này đang ghi kho tài sản"}
        rows, report = run_tasks(tasks if tasks is not None else python_tasks(today, fkey), (fkey,))
        flags = []
        for key, krows in rows.items():
            if key in REGISTRY:
                flags += write(key, krows, today=today, fetched_at=fetched_at, base=base)
        fx = refresh_fx_cache(today, meta) if tasks is None else None
        est, f2 = refresh_estimates(today, fetched_at, meta=meta, base=base, fx_days=fx)
        flags += f2
        ok = sum(1 for r in report.values() if r["ok"])
        payload = {"run_at": fetched_at, "ok": ok, "fail": len(report) - ok, "tasks": report,
                   "status": "ok" if ok == len(report) else ("partial" if ok else "error")}
        update_status("python", payload, flags, meta, now)
        update_status("estimates", est, None, meta, now)
    return {**payload, "flags": flags, "estimates": est}


def mcp_hours() -> "tuple[int, ...]":
    raw = os.environ.get(ENV_MCP_HOURS)
    if not raw:
        return DEFAULT_MCP_HOURS
    with contextlib.suppress(ValueError):
        return tuple(sorted({int(x) for x in raw.split(",") if x.strip()}))
    return DEFAULT_MCP_HOURS


def mcp_due(now: datetime, status: dict, *, min_gap_h: float = 1.0) -> bool:
    """Đúng giờ trong VNSTOCK_ASSETS_MCP_HOURS và chưa chạy MCP trong `min_gap_h` giờ."""
    if not enabled(ENV_MCP) or now.hour not in mcp_hours():
        return False
    last = (status.get("mcp") or {}).get("run_at")
    with contextlib.suppress(Exception):
        if last and (now - datetime.fromisoformat(last)).total_seconds() < min_gap_h * 3600:
            return False
    return True


def hourly(now: "datetime | None" = None) -> dict:
    """Gọi từ task News Alert mỗi giờ: nguồn Python + MCP vào giờ đã đặt. Không bao giờ ném."""
    if not enabled() or not enabled(ENV_HOURLY):
        return {"status": "disabled"}
    now = now or datetime.now()
    res = {"python": refresh_python(now)}
    if mcp_due(now, read_status()):
        import vnstock_assets_mcp as am
        res["mcp"] = am.refresh(now)
    return res


def _gold_cache_rows() -> list:
    with contextlib.suppress(Exception):
        import vnstock_gold
        hist = json.loads(vnstock_gold._CACHE.read_text(encoding="utf-8")).get("history") or {}
        return [_row(d, v, "gold-api") for d, v in hist.items()]
    return []


BACKFILL_STEPS = ("fred", "yahoo", "vcb", "mbk", "gold-cache", "fx")


def backfill(*, with_mcp: bool = False, vcb_days: int = 730, now: "datetime | None" = None,
             log=print, base=None, meta=None, tasks: "list | None" = None,
             steps: "set[str] | None" = None) -> dict:
    """MỘT LẦN sau khi merge (🖥️ desktop, ngoài giờ pipeline): lịch sử dài từ FRED, Yahoo,
    Vietcombank (theo ngày), vnstock_data (tỷ giá trung tâm), cache vàng cũ; --with-mcp thêm
    Finhay (vàng TG từ 2025, vàng đại lý, SJC miếng từ 2015) + đo lệch ngày mbk. Cuối cùng
    MỘT lượt Python như mỗi giờ (đường cong HĐTL, số hôm nay, ước tính, `status.python`) —
    10/10 thiếu bước này nên doctor báo "chưa có lượt nào" dù kho đã đầy. `steps` ⊂
    BACKFILL_STEPS ⇒ chỉ chạy các bước đó (vd {"mbk"} để nạp lại tỷ giá trung tâm đã dời ngày)."""
    now = now or datetime.now()
    today = now.date()
    fetched_at = now.isoformat(timespec="seconds")
    fkey = src.fred_key()
    report: dict = {}

    def step(name, fn):
        if steps and name.split("-")[0] not in steps and name not in steps:
            return
        log(f"… {name}")
        t0 = time.monotonic()
        try:
            got = fn() or {}
            n = 0
            for key, rows in got.items():
                write(key, rows, today=today, fetched_at=fetched_at, base=base)
                n += len(rows)
            report[name] = {"ok": True, "rows": n, "elapsed_s": round(time.monotonic() - t0, 1)}
            log(f"  ✅ {name}: {n} dòng ({report[name]['elapsed_s']}s)")
        except Exception as e:                                     # noqa: BLE001
            report[name] = {"ok": False, "error": src.scrub(e, (fkey,))}
            log(f"  ❌ {name}: {report[name]['error']}")

    def fred_full():
        if not fkey:
            raise RuntimeError("thiếu FRED_API_KEY")
        return {k: [_row(d, v, "fred") for d, v in src.fetch_fred(sid, fkey, start=s)]
                for k, sid, s in (("BRENT_SPOT", "DCOILBRENTEU", "1987-01-01"),
                                  ("WTI_SPOT", "DCOILWTICO", "1986-01-01"),
                                  ("USD_BROAD", "DTWEXBGS", "2006-01-01"))}

    def vcb_hist():
        days = [today - timedelta(days=i) for i in range(vcb_days, 0, -1)]
        days = [d for d in days if d.weekday() < 5]

        def one(d):
            with contextlib.suppress(Exception):
                v = src.fetch_vcb(d.isoformat())
                return _row(d, v["sell"], "vcb", bid=v["transfer"], ask=v["sell"],
                            meta={"cash": v["cash"]})
            return None
        with ThreadPoolExecutor(max_workers=4) as ex:
            rows = [r for r in ex.map(one, days) if r]
        if not rows:
            raise RuntimeError("không ngày nào tải được")
        return {"USDVND_VCB": rows}

    def mbk_hist():
        raw = src.fetch_mbk_central("2016-01-01", today.isoformat(), shift=False)
        if not raw:
            raise RuntimeError("vnstock_data không có / rỗng")
        wd = Counter(date.fromisoformat(d).weekday() for d, _ in raw)
        log("  mbk THÔ theo thứ (T2…CN): " + " · ".join(str(wd.get(i, 0)) for i in range(7))
            + " · 10 dòng cuối: " + ", ".join(f"{d}({_THU[date.fromisoformat(d).weekday()]})={v:,.0f}"
                                               for d, v in raw[-10:]))
        return {"USD_CENTRAL": [_row(d, v, "mbk") for d, v in src.shift_mbk_dates(raw)]}

    with machine_lock() as got_lock:
        if not got_lock:
            log("⛔ tiến trình khác trên máy này đang ghi kho tài sản — thử lại sau")
            return {"status": "busy"}
        step("fred", fred_full)
        for name, key, sym in (("yahoo-brent", "BRENT", "BZ=F"), ("yahoo-wti", "WTI", "CL=F"),
                               ("yahoo-dxy", "DXY", "DX-Y.NYB"), ("yahoo-usdvnd", "USDVND", "VND=X")):
            step(name, lambda key=key, sym=sym: {key: _yahoo_rows(sym, "max")})
        step("vcb", vcb_hist)
        step("mbk", mbk_hist)
        step("gold-cache", lambda: {"XAU": _gold_cache_rows()})
        if not steps or "fx" in steps:
            fx = refresh_fx_cache(today, meta, days=FX_CACHE_DAYS - 1)
            log(f"  {'✅' if fx else '❌'} fx: {len(fx)} ngày tỷ giá currency-api trong cache")
    if with_mcp:
        import vnstock_assets_mcp as am
        report["mcp"] = am.backfill(now, log=log)
    report["python"] = _final_python_pass(log, now, base=base, meta=meta, tasks=tasks)
    update_status("backfill", {"run_at": fetched_at, "report": report}, None, meta, now)
    return report


def _final_python_pass(log, now: datetime, *, base=None, meta=None, tasks=None) -> dict:
    log("… lượt Python như mỗi giờ (đường cong HĐTL, số hôm nay, ước tính trong ngày)")
    res = refresh_python(now, tasks=tasks, base=base, meta=meta)
    log(f"  lượt Python: {res.get('status')} ({res.get('ok')}/"
        f"{(res.get('ok') or 0) + (res.get('fail') or 0)})")
    for name, r in (res.get("tasks") or {}).items():
        if not r.get("ok"):
            log(f"  ❌ {name}: {r.get('error')}")
    for k, e in (res.get("estimates") or {}).items():
        log(f"  {k}: " + (e["hidden"] if e.get("hidden") else
                          f"{e['value']:,.2f} ±{e['band_pct']}% (neo {e['anchor_date']}, h={e['h']})"))
    return {k: res.get(k) for k in ("status", "ok", "fail", "estimates")}


CENTRAL_LAGS = (-1, 0, 1)
CENTRAL_MIN_N = 10                 # dưới sàn phiên chung ⇒ "chưa rõ", doctor im
CENTRAL_MIN_HIT = 0.80             # giả thuyết đúng phải khớp ≥80% phiên
CENTRAL_MIN_MARGIN = 0.10          # và hơn giả thuyết kế tiếp ≥10 điểm %


def verify_central(sbvn_rows: list, mbk: "dict[str, float]") -> dict:
    """Tỷ giá trung tâm trong kho có ĐÚNG ngày không, đo bằng (mua+bán)/2 giá tham khảo Cục QLNH
    (SSI SBVN, `USD_SBV_REF`) — thước đo TRỄ LẪN: đo 🖥️ 10/10 trên 62 phiên, sau khi dời ngày
    mbk (đã khớp báo chí 01→09/10), giữa = trung tâm CÙNG phiên 26/63, = phiên TRƯỚC 43/62
    (SSI chụp giá trước/sau lúc NHNN cập nhật). Vòng trước so riêng từng lệch nên kho ĐÚNG vẫn
    ra "lệch +1 nhiều nhất" ⇒ báo động giả "LÙI 1 phiên".

    Nay chấm giả thuyết "kho lệch L phiên" (K ngày D giữ trung tâm của phiên D+L) bằng TỈ LỆ PHIÊN
    mà giữa SBVN khớp (≤1 đ) MỘT TRONG HAI: kho phiên D−L hoặc D−L−1 (lịch phiên SBVN). L đúng ⇒
    ~100%; L sai ⇒ chỉ phần cùng phiên hoặc phần phiên trước (~40–70%). `by_shift` giữ số khớp
    từng lệch riêng để soi."""
    mids = {r["date"]: (float(r["bid"]) + float(r["ask"])) / 2 for r in sbvn_rows
            if src.num(r.get("bid")) and src.num(r.get("ask"))}
    days = sorted(mids)
    tail = {d: mbk[d] for d in sorted(mbk)[-6:]}

    def at(i):
        return mbk.get(days[i]) if 0 <= i < len(days) else None

    def ok(m, v):
        return v is not None and abs(m - v) <= 1.0
    by_shift = {}
    for sh in (-1, 0, 1, 2):
        pairs = [(mids[d], at(i - sh)) for i, d in enumerate(days) if at(i - sh) is not None]
        if pairs:
            by_shift[str(sh)] = {"n": len(pairs), "exact": sum(ok(m, v) for m, v in pairs)}
    by_lag = {}
    for lag in CENTRAL_LAGS:
        n = hit = 0
        for i, d in enumerate(days):
            a, b = at(i - lag), at(i - lag - 1)
            if a is None or b is None:                 # mép chuỗi: thiếu một vế ⇒ không chấm
                continue
            n += 1
            hit += ok(mids[d], a) or ok(mids[d], b)
        if n:
            by_lag[lag] = {"n": n, "hit": hit, "rate": round(hit / n, 3)}
    if not by_lag:
        return {"n": 0, "verdict": "không có phiên chung với mbk — chưa kiểm được",
                "sbvn_days": len(days), "mbk_tail": tail}
    ranked = sorted(by_lag, key=lambda lg: (-by_lag[lg]["rate"], abs(lg)))
    best, b = ranked[0], by_lag[ranked[0]]
    second = by_lag[ranked[1]]["rate"] if len(ranked) > 1 else 0.0
    if b["n"] < CENTRAL_MIN_N or b["rate"] < CENTRAL_MIN_HIT or b["rate"] - second < CENTRAL_MIN_MARGIN:
        verdict = "chưa rõ (ít phiên chung / chưa tách được giả thuyết)"
    elif best == 0:
        verdict = "mbk ĐÚNG ngày"
    else:
        verdict = f"mbk ghi {'LÙI' if best > 0 else 'TIẾN'} {abs(best)} phiên"
    return {"n": b["n"], "best_lag": best, "verdict": verdict,
            "by_lag": {str(lg): v for lg, v in by_lag.items()}, "by_shift": by_shift, "mbk_tail": tail}


def central_dating(*, base=None) -> dict:
    """`verify_central` trên kho: USD_SBV_REF (bid/ask) vs USD_CENTRAL nguồn mbk."""
    ref = load("USD_SBV_REF", base=base)
    cen = load("USD_CENTRAL", base=base)
    mbk = {str(d): float(c) for d, c, s_ in zip(cen["date"], cen["close"], cen["source"]) if s_ == "mbk"}
    return verify_central(ref.to_dict("records"), mbk)


# ── Đọc cho UI/brief (P2) ────────────────────────────────────────────────────
def latest(key: str, *, base=None) -> "dict | None":
    df = load(key, start=(date.today() - timedelta(days=400)).isoformat(), base=base)
    if not len(df):
        return None
    last = df[df["date"] == df["date"].max()]
    if REGISTRY[key].curve:
        rows = last.to_dict("records")
        rows.sort(key=lambda r: src.contract_month(r["contract"]) or "")
        return {"date": str(last["date"].iloc[0]), "points": rows}
    return last.iloc[-1].to_dict()


def curve_spreads(key: str, *, base=None) -> "dict | None":
    lt = latest(key, base=base)
    pts = (lt or {}).get("points") or []
    if len(pts) < 2:
        return None
    m1 = pts[0]["close"]

    def sp(p):
        return {"to": p["contract"], "usd": round(m1 - p["close"], 2),
                "pct": round((m1 / p["close"] - 1) * 100, 2)}
    return {"date": lt["date"], "m1": pts[0]["contract"], "m1_close": m1, "m1_m2": sp(pts[1]),
            "m1_m6": sp(pts[min(5, len(pts) - 1)]),
            "shape": "backwardation" if m1 > pts[1]["close"] else "contango"}


def sjc_premium_pct(*, base=None) -> "dict | None":
    """% vàng miếng SJC (giá bán) đắt hơn vàng TG quy đổi theo USD/VND thị trường."""
    sjc, xau, usd = (latest(k, base=base) for k in ("GOLD_SJC_BAR", "XAU", "USDVND"))
    if not (sjc and xau and usd):
        return None
    ask = src.num(sjc.get("ask")) or src.num(sjc.get("close"))
    spot = float(xau["close"]) * float(usd["close"]) * LUONG_OZ
    return {"pct": round((ask / spot - 1) * 100, 2), "date": sjc["date"],
            "sjc_ask": ask, "spot_vnd_luong": round(spot)}


def usd_ceiling_room_pct(*, base=None) -> "dict | None":
    vcb, cen = latest("USDVND_VCB", base=base), latest("USD_CENTRAL", base=base)
    if not (vcb and cen):
        return None
    ceil = float(cen["close"]) * (1 + USD_BAND)
    sell = src.num(vcb.get("ask")) or float(vcb["close"])
    return {"pct": round((ceil / sell - 1) * 100, 2), "ceiling": round(ceil),
            "vcb_sell": sell, "central": float(cen["close"]), "central_date": cen["date"]}


_LABEL_W = 40
_THU = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


def _fmt_value(v: float, unit: str) -> str:
    """VND (giá đồng, lượng vàng) không phần lẻ; còn lại 2 số lẻ."""
    return f"{v:,.0f} {unit}" if unit.startswith("VND") else f"{v:,.2f} {unit}"


def show(*, base=None, meta=None, today: "date | None" = None) -> str:
    today = today or date.today()
    st = read_status(meta)
    lines = [f"Kho tài sản · {ASSETS_DIR if base is None else base}"]
    for grp, title in (("gold", "VÀNG"), ("oil", "DẦU"), ("usd", "USD")):
        lines.append(f"\n== {title} ==")
        for key, spec in REGISTRY.items():
            if spec.group != grp:
                continue
            lt = latest(key, base=base)
            if not lt:
                lines.append(f"  ⬜ {spec.label:<{_LABEL_W}} chưa có dữ liệu")
                continue
            if spec.curve:
                cs = curve_spreads(key, base=base) or {}
                pts = " · ".join(f"{p['contract']} {p['close']:,.2f}" for p in lt["points"])
                lines.append(f"  ✅ {spec.label:<{_LABEL_W}} {lt['date']}: {pts}")
                if cs:
                    lines.append(f"     M1−M2 {cs['m1_m2']['usd']:+.2f}$ ({cs['m1_m2']['pct']:+.2f}%) · "
                                 f"M1−{cs['m1_m6']['to']} {cs['m1_m6']['usd']:+.2f}$ ⇒ {cs['shape']}")
                continue
            age = (today - date.fromisoformat(str(lt["date"]))).days
            tag = "✅" if spec.display == "show" else "🔒"
            note = {"hide": " · ẩn khỏi màn chính", "est": " · chỉ hiện qua ước tính"}.get(spec.display, "")
            extra = ""
            if src.num(lt.get("bid")) and src.num(lt.get("ask")):
                extra = f" (mua {lt['bid']:,.0f} · bán {lt['ask']:,.0f})"
            lines.append(f"  {tag} {spec.label:<{_LABEL_W}} {_fmt_value(float(lt['close']), spec.unit)}"
                         f"{extra} · {lt['date']} (trễ {age}d) · {lt['source']}{note}")
    prem, room = sjc_premium_pct(base=base), usd_ceiling_room_pct(base=base)
    lines.append("\n== Suy ra ==")
    lines.append(f"  SJC miếng đắt hơn vàng TG quy đổi: {prem['pct']:+.2f}% ({prem['date']})"
                 if prem else "  SJC miếng vs vàng TG: chưa đủ dữ liệu")
    lines.append(f"  VCB bán còn cách trần {room['ceiling']:,} (trung tâm {room['central']:,.0f} ngày "
                 f"{room['central_date']}): {room['pct']:.2f}%"
                 if room else "  Dư địa tới trần tỷ giá: chưa đủ dữ liệu")
    cv = central_dating(base=base)
    if cv.get("n"):
        by = cv.get("by_lag") or {}
        lines.append(f"  Ngày tỷ giá trung tâm (so giá tham khảo NHNN, {cv['n']} phiên): {cv['verdict']} · "
                     + " · ".join(f"giả thuyết lệch {k}: khớp {v['hit']}/{v['n']}" for k, v in by.items()))
    for k, e in (st.get("estimates") or {}).items():
        lines.append(f"  {k}: " + (e["hidden"] if e.get("hidden") else
                     f"{e['value']:,.2f} ±{e['band_pct']}% ({e['date']}, neo {e['anchor']:,.2f} ngày "
                     f"{e['anchor_date']}, h={e['h']})"))
    lines.append(f"\n== Đối chiếu MCP ↔ Python (ngày đã đóng, {GATE_N} phiên chung gần nhất) ==")
    for key, pairs in agreement_all(today=today, meta=meta).items():
        for pair, a in pairs.items():
            last = a["last"] or {}
            lines.append(f"  {key:<14} {pair:<22} {a['status']:<8} lệch>{a['tol_pct']}%: {a['bad']}/{a['window']}"
                         f" · lớn nhất {a['max_abs_pct']:.2f}% · cuối {last.get('date', '—')} "
                         f"{last.get('dev_pct', 0):+.2f}% · tổng {a['n']} ngày chung")
    dem = (os.environ.get(ENV_DEMOTE) or "").strip()
    if dem:
        lines.append(f"  (đang hạ ưu tiên bằng tay: {ENV_DEMOTE}={dem})")
    py, mc = st.get("python") or {}, st.get("mcp") or {}
    lines.append(f"\nLượt Python: {py.get('run_at')} · {py.get('status')} ({py.get('ok')}/"
                 f"{(py.get('ok') or 0) + (py.get('fail') or 0)}) · lượt MCP: {mc.get('run_at')} · "
                 f"{mc.get('status')} · máy {st.get('machine')}")
    for name, r in (py.get("tasks") or {}).items():
        if not r.get("ok"):
            lines.append(f"  ❌ {name}: {r.get('error')}")
    flags = [f for f in st.get("xcheck") or [] if str(f.get("at", ""))[:10] >= (today - timedelta(days=1)).isoformat()]
    for f in flags[-8:]:
        lines.append(f"  ⚠ lệch nguồn {f}")
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Kho đa tài sản vàng · dầu · USD (U82)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--refresh", action="store_true", help="một lượt nguồn Python (mặc định)")
    g.add_argument("--mcp", action="store_true", help="một lượt MCP Finhay/SSI (bỏ qua giờ đặt)")
    g.add_argument("--hourly", action="store_true", help="lượt mỗi giờ: Python + MCP nếu tới giờ")
    g.add_argument("--backfill", action="store_true", help="MỘT LẦN: nạp lịch sử dài")
    g.add_argument("--show", action="store_true", help="in giá mới nhất + suy ra, không gọi mạng")
    g.add_argument("--mcp-backfill", action="store_true",
                   help="chỉ lịch sử MCP Finhay/SSI (+ một lượt Python cuối)")
    g.add_argument("--mcp-stale", type=float, metavar="GIỜ",
                   help="pipeline: lượt MCP nếu lượt trước cũ hơn GIỜ giờ")
    ap.add_argument("--with-mcp", action="store_true", help="--backfill: thêm lịch sử Finhay + kiểm SBVN")
    ap.add_argument("--vcb-days", type=int, default=730)
    ap.add_argument("--steps", help=f"--backfill: chỉ các bước, phẩy ({','.join(BACKFILL_STEPS)})")
    ap.add_argument("--only", help="--mcp-backfill: khoá kho, phẩy (vd GOLD_SJC_BAR,USD_SBV_REF)")
    a = ap.parse_args(argv)
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    if a.show:
        print(show())
        return 0
    if not enabled():
        print(f"[assets] tắt ({ENV_SWITCH}=0)")
        return 0
    if a.backfill:
        steps = {x.strip().lower() for x in (a.steps or "").split(",") if x.strip()} or None
        if steps and steps - set(BACKFILL_STEPS):
            print(f"[assets] bước không có: {sorted(steps - set(BACKFILL_STEPS))} — chọn trong {BACKFILL_STEPS}")
            return 2
        rep = backfill(with_mcp=a.with_mcp, vcb_days=a.vcb_days, steps=steps)
        print(show())
        return 0 if all(v.get("ok", True) for v in rep.values() if isinstance(v, dict)) else 1
    if a.mcp_backfill:
        import vnstock_assets_mcp as am
        only = {k.strip().upper() for k in (a.only or "").split(",") if k.strip()} or None
        if only and only - set(REGISTRY):
            print(f"[assets] khoá không có trong registry: {sorted(only - set(REGISTRY))}")
            return 2
        rep = am.backfill(only=only)
        _final_python_pass(print, datetime.now())
        print(show())
        return 0 if all(v.get("ok", True) for v in rep.values() if isinstance(v, dict)) else 1
    if a.mcp or a.mcp_stale is not None:
        import vnstock_assets_mcp as am
        res = am.refresh(force=a.mcp, stale_h=a.mcp_stale)
        print(f"[assets-mcp] {res.get('status')} · {res.get('rows', 0)} dòng · {res.get('error') or ''}")
        return 0 if res.get("status") in ("ok", "skipped", "disabled") else 1
    if a.hourly:
        res = hourly()
        py = res.get("python") or {}
        print(f"[assets] mỗi giờ: python {py.get('status')} ({py.get('ok')}/"
              f"{(py.get('ok') or 0) + (py.get('fail') or 0)})"
              + (f" · mcp {res['mcp'].get('status')}" if res.get("mcp") else ""))
        return 0
    res = refresh_python()
    print(f"[assets] python {res.get('status')} ({res.get('ok')}/{(res.get('ok') or 0) + (res.get('fail') or 0)})"
          + "".join(f"\n  ❌ {n}: {r['error']}" for n, r in (res.get("tasks") or {}).items() if not r["ok"]))
    # P4: lượt pipeline tối (sau sync giá) tính lại độ nhạy cổ phiếu ↔ vàng/dầu/USD — lượt mỗi giờ thì không.
    try:
        import vnstock_assets_links as al
        print(f"[assets] liên kết cổ phiếu: {al.refresh()}")
    except Exception as e:                                         # noqa: BLE001
        print(f"[assets] liên kết cổ phiếu lỗi: {type(e).__name__}: {e}")
    return 0 if res.get("status") in ("ok", "busy", "disabled") else 1


if __name__ == "__main__":
    sys.exit(main())
