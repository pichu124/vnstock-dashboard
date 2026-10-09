#!/usr/bin/env python3
"""vnstock_assets_view.py — số cho tab "🪙 Hàng hoá & Tiền tệ" (P2, U83).

THUẦN: chỉ đọc kho `data_warehouse/assets` qua `vnstock_assets`, không mạng, không Streamlit —
tab `dashboard/assets_tab.py` chỉ vẽ. Mọi hàm nhận `base` (thư mục kho) để test dựng kho tạm.

Thay đổi theo NGÀY LỊCH chứ không theo số phiên: vàng nội có giá cả cuối tuần, dầu/USD thì
không ⇒ "1 tuần" = so với điểm gần nhất ≤ ngày cuối − 7 ngày (cùng nghĩa cho mọi chuỗi), "1
phiên" = so với điểm liền trước, YTD = so với điểm cuối cùng ≤ 31/12 năm trước.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import vnstock_assets as va

CHANGE_WINDOWS = (("1 phiên", None), ("1 tuần", 7), ("1 tháng", 30), ("YTD", "ytd"))
STALE_DAYS = 3                    # thị trường nghỉ cuối tuần (dầu, USD, vàng TG)
STALE_DAYS_WEEKEND = 1            # vàng nội có giá cả T7/CN
JOIN_TOL_DAYS = 4                 # ghép chuỗi khác lịch (vàng nội ↔ vàng TG) tối đa lệch 4 ngày
DEALER_KINDS = (("BAR", "miếng"), ("RING", "nhẫn"))


def frame(key: str, *, start: "str | None" = None, base=None) -> pd.DataFrame:
    """Chuỗi một dòng/ngày, index = Timestamp ngày (không dùng cho đường cong)."""
    df = va.load(key, start=start, base=base)
    if not len(df):
        return pd.DataFrame(columns=["close", "open", "high", "low", "bid", "ask", "source"])
    df = df.copy()
    df.index = pd.to_datetime(df["date"])
    return df[["close", "open", "high", "low", "bid", "ask", "source", "meta"]].sort_index()


def changes(ser: pd.Series) -> "dict[str, float | None]":
    """{nhãn: % đổi} theo CHANGE_WINDOWS; không đủ lịch sử ⇒ None (không bịa)."""
    s = pd.to_numeric(ser, errors="coerce").dropna().sort_index()
    out: dict = {label: None for label, _ in CHANGE_WINDOWS}
    if len(s) < 2:
        return out
    last_d, last = s.index[-1], float(s.iloc[-1])

    def at_or_before(d):
        sub = s[s.index <= d]
        return float(sub.iloc[-1]) if len(sub) else None
    for label, w in CHANGE_WINDOWS:
        if w is None:
            ref = float(s.iloc[-2])
        elif w == "ytd":
            ref = at_or_before(pd.Timestamp(last_d.year - 1, 12, 31))
        else:
            ref = at_or_before(last_d - pd.Timedelta(days=w))
        out[label] = round((last / ref - 1) * 100, 2) if ref else None
    return out


def card(key: str, *, base=None, today: "date | None" = None) -> "dict | None":
    """Ô số: giá mới nhất + nguồn + ngày + tuổi + % đổi. None khi chuỗi trống."""
    today = today or date.today()
    spec = va.REGISTRY[key]
    df = frame(key, start=(today - timedelta(days=400)).isoformat(), base=base)
    if not len(df):
        return None
    last = df.iloc[-1]
    d = df.index[-1].date()
    age = (today - d).days
    return {"key": key, "label": spec.label, "unit": spec.unit, "value": float(last["close"]),
            "date": d.isoformat(), "source": last["source"], "age": age,
            "stale": age > (STALE_DAYS_WEEKEND if spec.weekends else STALE_DAYS),
            "bid": _num(last["bid"]), "ask": _num(last["ask"]), "chg": changes(df["close"])}


def _num(v) -> "float | None":
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def fmt_value(v: "float | None", unit: str) -> str:
    """VND (giá đồng, vàng đồng/lượng) không phần lẻ; còn lại 2 số lẻ — format số kiểu EN."""
    if v is None:
        return "—"
    return f"{v:,.0f}" if unit.startswith("VND") else f"{v:,.2f}"


def fmt_changes(chg: dict, skip: tuple = ()) -> str:
    return " · ".join(f"{k} {v:+.2f}%" if v is not None else f"{k} —"
                      for k, v in chg.items() if k not in skip)


# ── Vàng ─────────────────────────────────────────────────────────────────────
def world_gold_vnd(*, start: "str | None" = None, base=None) -> pd.Series:
    """Vàng TG quy đổi đồng/lượng = XAU (USD/oz) × USD/VND thị trường × 37,5/31,1035."""
    xau, usd = frame("XAU", start=start, base=base), frame("USDVND", start=start, base=base)
    if not (len(xau) and len(usd)):
        return pd.Series(dtype=float)
    j = pd.merge_asof(xau[["close"]].rename(columns={"close": "xau"}),
                      usd[["close"]].rename(columns={"close": "usd"}),
                      left_index=True, right_index=True,
                      tolerance=pd.Timedelta(days=JOIN_TOL_DAYS)).dropna()
    return (j["xau"] * j["usd"] * va.LUONG_OZ).rename("world")


def premium_frame(key: str = "GOLD_SJC_BAR", *, start: "str | None" = None, base=None) -> pd.DataFrame:
    """Theo ngày của sản phẩm vàng nội: giá bán, vàng TG quy đổi (điểm gần nhất ≤ ngày đó, lệch
    ≤ JOIN_TOL_DAYS), % chênh. Vàng TG nghỉ cuối tuần ⇒ T7/CN dùng số thứ Sáu."""
    vn = frame(key, start=start, base=base)
    world = world_gold_vnd(start=start, base=base)
    if not (len(vn) and len(world)):
        return pd.DataFrame(columns=["ask", "world", "pct"])
    ask = vn["ask"].where(vn["ask"].notna(), vn["close"]).rename("ask").to_frame()
    j = pd.merge_asof(ask, world.to_frame(), left_index=True, right_index=True,
                      tolerance=pd.Timedelta(days=JOIN_TOL_DAYS)).dropna()
    j["pct"] = (j["ask"] / j["world"] - 1) * 100
    return j


def dealer_table(*, base=None, today: "date | None" = None) -> pd.DataFrame:
    """10 sản phẩm vàng đại lý: mua, bán, chênh mua–bán %, so SJC miếng (đồng), chênh vs TG %."""
    today = today or date.today()
    world = world_gold_vnd(start=(today - timedelta(days=30)).isoformat(), base=base)
    w_last = float(world.iloc[-1]) if len(world) else None
    sjc = card("GOLD_SJC_BAR", base=base, today=today)
    sjc_ask = (sjc or {}).get("ask") or (sjc or {}).get("value")
    rows = []
    for dealer in va.DEALERS:
        for kind, name in DEALER_KINDS:
            c = card(f"GOLD_{dealer}_{kind}", base=base, today=today)
            if not c:
                continue
            ask = c["ask"] or c["value"]
            bid = c["bid"]
            rows.append({"Đại lý": dealer, "Loại": name, "Mua": bid, "Bán": ask,
                         "Chênh mua–bán %": round((ask - bid) / ask * 100, 2) if bid else None,
                         "Bán − SJC miếng": ask - sjc_ask if sjc_ask else None,
                         "Chênh vs TG %": round((ask / w_last - 1) * 100, 2) if w_last else None,
                         "Ngày": c["date"], "Cũ": c["stale"]})
    return pd.DataFrame(rows)


# ── Dầu ──────────────────────────────────────────────────────────────────────
def curve_snapshots(key: str, *, back_days: int = 7, base=None,
                    today: "date | None" = None) -> dict:
    """{"latest": (ngày, [(mã, tháng, giá)…]), "prior": (ngày, …) | None} — ảnh chụp đường cong
    mới nhất và ảnh gần nhất ≤ mới nhất − back_days (kho chỉ có từ khi lượt mỗi giờ chạy)."""
    today = today or date.today()
    df = va.load(key, start=(today - timedelta(days=back_days + 30)).isoformat(), base=base)
    if not len(df):
        return {"latest": None, "prior": None}

    def snap(d):
        pts = [(r["contract"], va.src.contract_month(r["contract"]), float(r["close"]))
               for r in df[df["date"] == d].to_dict("records")]
        return d, sorted((p for p in pts if p[1]), key=lambda p: p[1])
    dates = sorted(df["date"].unique())
    last = dates[-1]
    cutoff = (date.fromisoformat(last) - timedelta(days=back_days)).isoformat()
    older = [d for d in dates if d <= cutoff]
    return {"latest": snap(last), "prior": snap(older[-1]) if older else None}


def spread_series(a: str = "BRENT", b: str = "WTI", *, start: "str | None" = None,
                  base=None) -> pd.Series:
    """a − b trên ngày chung (USD/thùng)."""
    fa, fb = frame(a, start=start, base=base), frame(b, start=start, base=base)
    j = fa[["close"]].join(fb[["close"]], lsuffix="_a", rsuffix="_b", how="inner").dropna()
    return (j["close_a"] - j["close_b"]).rename(f"{a}−{b}")


# ── USD ──────────────────────────────────────────────────────────────────────
def usd_band_frame(*, start: "str | None" = None, base=None) -> pd.DataFrame:
    """Theo ngày: trung tâm, trần (×1,05), sàn (×0,95), VCB bán, giá bán tham khảo NHNN."""
    cen = frame("USD_CENTRAL", start=start, base=base)["close"].rename("central")
    vcb = frame("USDVND_VCB", start=start, base=base)
    sbv = frame("USD_SBV_REF", start=start, base=base)["close"].rename("sbv_sell")
    vcb_sell = vcb["ask"].where(vcb["ask"].notna(), vcb["close"]).rename("vcb_sell")
    df = pd.concat([cen, vcb_sell, sbv], axis=1).sort_index()
    df["ceiling"] = df["central"] * (1 + va.USD_BAND)
    df["floor"] = df["central"] * (1 - va.USD_BAND)
    return df


def estimate(key: str, *, base=None, meta=None) -> "dict | None":
    """Ước tính trong ngày (`*_EST`) như lượt Python gần nhất ghi: số, dải, neo, h — hoặc lý do ẩn."""
    return (va.read_status(meta).get("estimates") or {}).get(key)


def run_info(*, meta=None) -> dict:
    st = va.read_status(meta)
    py, mc = st.get("python") or {}, st.get("mcp") or {}
    return {"python_at": py.get("run_at"), "python_status": py.get("status"),
            "mcp_at": mc.get("run_at"), "mcp_status": mc.get("status"), "machine": st.get("machine")}
