#!/usr/bin/env python3
"""vnstock_assets_links.py — P4 đa tài sản: cổ phiếu VN nhạy với vàng · dầu · USD tới đâu (U85).

Danh sách cổ phiếu ở thiết kế §3 là GIẢ THUYẾT kênh truyền dẫn; module này ĐO trên kho giá sẵn có, mã
nào không thấy quan hệ thì nói thẳng "không thấy" (không giữ vì "nghe hợp lý").

Phép đo (mỗi cặp mã × yếu tố, cửa sổ 60 phiên — kèm 250 phiên làm nền):
- lợi suất log theo PHIÊN VN của mã; phiên |r| > 16% (vượt biên độ UPCoM) = đứt gãy dữ liệu ⇒ bỏ.
- yếu tố được ghép theo MỨC GIÁ về từng phiên VN rồi mới lấy chênh ⇒ biến động cuối tuần/nghỉ lễ của
  yếu tố không bị rơi. Giá QUỐC TẾ (XAU, Brent, DXY) đóng cửa SAU phiên VN ⇒ phiên t ghép mức giá của
  ngày yếu tố < t (lệch pha 1); giá NỘI (vàng nhẫn SJC, VCB bán) ghép cùng ngày (≤ t).
- `beta_riêng` = hệ số của yếu tố trong hồi quy r_mã = a + b_VNI·r_VNINDEX + b·r_yếu_tố — phần nhạy RIÊNG
  sau khi trừ nhịp chung thị trường; `t` theo sai số chuẩn OLS. Kết luận: < 40 phiên ⇒ chưa đủ dữ liệu;
  |t| ≥ 2 ⇒ có quan hệ (đúng/NGƯỢC chiều kỳ vọng); còn lại ⇒ không thấy.

Đọc kho giá (`data_warehouse/prices`) + kho tài sản; ghi `_meta/assets_links.json` cho tab 🪙 và brief.
CLI: `python vnstock_assets_links.py [--show]`. Kill-switch: `VNSTOCK_ASSETS_LINKS=0`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import vnstock_assets as va

_REPO = Path(__file__).resolve().parent
WAREHOUSE = _REPO / "data_warehouse"
CACHE_NAME = "assets_links.json"
ENV_SWITCH = "VNSTOCK_ASSETS_LINKS"

WINDOW = 60
WINDOW_LONG = 250
MIN_N = 40
T_SIG = 2.0
MAX_ABS_RET = 0.16

# Yếu tố: (khoá kho, nhãn, quốc tế ⇒ lệch pha 1 phiên)
DRIVERS = {
    "XAU": ("Vàng TG (USD/oz)", True),
    "GOLD_SJC_RING": ("Vàng nhẫn SJC (đồng)", False),
    "BRENT": ("Dầu Brent (HĐTL)", True),
    "DXY": ("DXY", True),
    "USDVND_VCB": ("USD/VND (VCB bán)", False),
}

# (mã, yếu tố, chiều kỳ vọng +1/−1/None, lý do) — thiết kế §3.
LINKS = (
    ("PNJ", "XAU", None, "bán lẻ trang sức: giá vàng đổi biên + tồn kho, chiều chưa rõ"),
    ("PNJ", "GOLD_SJC_RING", None, "giá vàng nội — đầu vào trực tiếp"),
    ("PVD", "BRENT", 1, "khoan: dầu cao ⇒ capex thượng nguồn"),
    ("PVS", "BRENT", 1, "dịch vụ kỹ thuật dầu khí"),
    ("GAS", "BRENT", 1, "giá bán khí neo dầu"),
    ("BSR", "BRENT", 1, "lọc dầu: tồn kho + crack spread"),
    ("PLX", "BRENT", 1, "phân phối xăng: lãi tồn kho khi giá lên"),
    ("OIL", "BRENT", 1, "phân phối xăng"),
    ("PVT", "BRENT", 1, "vận tải dầu"),
    ("DPM", "BRENT", None, "phân đạm: khí đầu vào neo dầu, giá urê theo năng lượng"),
    ("DCM", "BRENT", None, "phân đạm"),
    ("HVN", "BRENT", -1, "nhiên liệu bay là chi phí lớn"),
    ("VJC", "BRENT", -1, "nhiên liệu bay"),
    ("VHC", "USDVND_VCB", 1, "xuất khẩu cá tra thu USD"),
    ("ANV", "USDVND_VCB", 1, "xuất khẩu cá tra"),
    ("MSH", "USDVND_VCB", 1, "dệt may xuất khẩu"),
    ("HVN", "USDVND_VCB", -1, "nợ + chi phí USD"),
    ("VJC", "USDVND_VCB", -1, "chi phí USD (thuê tàu, nhiên liệu)"),
    ("VHC", "DXY", 1, "USD thế giới mạnh"),
    ("HVN", "DXY", -1, "USD thế giới mạnh"),
)


def enabled() -> bool:
    return (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in ("0", "false", "off", "no")


# ── đọc kho ──────────────────────────────────────────────────────────────────
def stock_close(ticker: str, *, warehouse: Path = WAREHOUSE, min_year: "int | None" = None) -> pd.Series:
    """Đóng cửa theo phiên của một mã/chỉ số từ `data_warehouse/prices` (rỗng khi không có)."""
    from vnstock_horizons_state import read_ticker
    for sym in ((ticker,) if ticker != "VNINDEX" else ("VNINDEX", "VN-INDEX", "^VNINDEX")):
        df = read_ticker(warehouse / "prices" / f"ticker={sym}", min_year=min_year)
        if not df.empty:
            return pd.Series(df["close"].astype(float).values, index=pd.DatetimeIndex(df["time"]), name=ticker)
    return pd.Series(dtype=float, name=ticker)


def driver_level(key: str, *, start: "str | None" = None, base=None) -> pd.Series:
    df = va.load(key, start=start, base=base)
    if not len(df):
        return pd.Series(dtype=float, name=key)
    ser = pd.Series(pd.to_numeric(df["close"], errors="coerce").values,
                    index=pd.to_datetime(df["date"]), name=key).dropna()
    return ser[~ser.index.duplicated(keep="last")].sort_index()


# ── thuần ────────────────────────────────────────────────────────────────────
def session_returns(close: pd.Series) -> pd.Series:
    """Lợi suất log theo phiên; |r| > MAX_ABS_RET (đứt gãy dữ liệu/đơn vị) ⇒ bỏ."""
    c = close.dropna().sort_index()
    c = c[c > 0]
    r = np.log(c / c.shift(1)).dropna()
    return r[r.abs() <= MAX_ABS_RET]


def aligned_driver_returns(level: pd.Series, sessions: pd.DatetimeIndex, *, lag: bool) -> pd.Series:
    """Mức giá yếu tố ghép về từng phiên VN (lag ⇒ ngày yếu tố < phiên, không thì ≤), rồi lấy log chênh
    giữa hai phiên liền nhau — gom cả biến động cuối tuần/nghỉ lễ của yếu tố."""
    if not len(level) or not len(sessions):
        return pd.Series(dtype=float)
    # Ép cùng độ phân giải thời gian: kho giá (parquet) ra ms, kho tài sản ra ns ⇒ merge_asof từ chối.
    left = pd.DataFrame({"t": pd.DatetimeIndex(sessions).astype("datetime64[ns]").sort_values()})
    right = pd.DataFrame({"d": pd.DatetimeIndex(level.index).astype("datetime64[ns]"),
                          "lvl": level.values}).sort_values("d")
    m = pd.merge_asof(left, right, left_on="t", right_on="d", direction="backward",
                      allow_exact_matches=not lag)
    lvl = pd.Series(m["lvl"].values, index=m["t"].values)
    src_day = pd.Series(m["d"].values, index=m["t"].values)
    r = np.log(lvl / lvl.shift(1))
    r[src_day == src_day.shift(1)] = 0.0             # yếu tố không có ngày mới giữa hai phiên
    return r.dropna()


def ols_driver(y: np.ndarray, x_mkt: np.ndarray, x_drv: np.ndarray) -> "dict | None":
    """y = a + b_m·x_mkt + b·x_drv ⇒ {beta, t, beta_mkt, r2}. None khi suy biến."""
    n = len(y)
    if n < 5:
        return None
    X = np.column_stack([np.ones(n), x_mkt, x_drv])
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None
    coef = xtx_inv @ X.T @ y
    resid = y - X @ coef
    dof = n - 3
    if dof <= 0:
        return None
    s2 = float(resid @ resid) / dof
    se = math.sqrt(max(s2 * xtx_inv[2, 2], 0.0))
    tss = float(((y - y.mean()) ** 2).sum())
    return {"beta": float(coef[2]), "t": float(coef[2] / se) if se > 0 else 0.0,
            "beta_mkt": float(coef[1]), "r2": 1 - float(resid @ resid) / tss if tss > 0 else 0.0}


def measure(stock_ret: pd.Series, mkt_ret: pd.Series, drv_ret: pd.Series, window: int) -> dict:
    """Một cửa sổ: n, tương quan thô, beta thô, beta riêng (đã trừ VNINDEX) + t."""
    df = pd.concat({"s": stock_ret, "m": mkt_ret, "d": drv_ret}, axis=1, join="inner").dropna().tail(window)
    n = len(df)
    out = {"n": n, "corr": None, "beta_raw": None, "beta": None, "t": None, "r2": None}
    if n < 5 or df["d"].std() == 0:
        return out
    out["corr"] = round(float(df["s"].corr(df["d"])), 3)
    out["beta_raw"] = round(float(df["s"].cov(df["d"]) / df["d"].var()), 3)
    fit = ols_driver(df["s"].values, df["m"].values, df["d"].values)
    if fit:
        out.update(beta=round(fit["beta"], 3), t=round(fit["t"], 2), r2=round(fit["r2"], 3))
    return out


def verdict(m: dict, expected: "int | None") -> str:
    if m["n"] < MIN_N or m["t"] is None:
        return "chưa đủ dữ liệu"
    if abs(m["t"]) < T_SIG:
        return "không thấy"
    sign = 1 if m["beta"] > 0 else -1
    if expected is None:
        return f"có ({'+' if sign > 0 else '−'})"
    return "có, đúng chiều" if sign == expected else "có, NGƯỢC chiều kỳ vọng"


# ── lượt tính ────────────────────────────────────────────────────────────────
def compute(*, warehouse: Path = WAREHOUSE, base=None, today: "date | None" = None) -> dict:
    today = today or date.today()
    start = (today - timedelta(days=int(WINDOW_LONG * 1.6))).isoformat()
    min_year = int(start[:4])
    mkt = session_returns(stock_close("VNINDEX", warehouse=warehouse, min_year=min_year))
    levels = {k: driver_level(k, start=start, base=base) for k in DRIVERS}
    rows, cache = [], {}
    for ticker, dkey, expected, why in LINKS:
        if ticker not in cache:
            cache[ticker] = session_returns(stock_close(ticker, warehouse=warehouse, min_year=min_year))
        sr = cache[ticker]
        label, lag = DRIVERS[dkey]
        dr = aligned_driver_returns(levels[dkey], sr.index, lag=lag) if len(sr) else pd.Series(dtype=float)
        short, long_ = measure(sr, mkt, dr, WINDOW), measure(sr, mkt, dr, WINDOW_LONG)
        rows.append({"ticker": ticker, "driver": dkey, "driver_label": label, "lag": lag,
                     "expected": expected, "why": why, "w60": short, "w250": long_,
                     "verdict": verdict(short, expected),
                     "last_session": sr.index[-1].date().isoformat() if len(sr) else None})
    return {"as_of": datetime.now().isoformat(timespec="seconds"), "today": today.isoformat(),
            "window": WINDOW, "window_long": WINDOW_LONG, "min_n": MIN_N, "t_sig": T_SIG,
            "vnindex_sessions": int(len(mkt)), "rows": rows}


def refresh(*, meta=None, **kw) -> dict:
    if not enabled():
        return {"status": "disabled"}
    res = compute(**kw)
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(res, Path(meta or va.META_DIR) / CACHE_NAME)
    return {"status": "ok", "rows": len(res["rows"]),
            "found": sum(1 for r in res["rows"] if r["verdict"].startswith("có"))}


def load(*, meta=None) -> dict:
    with contextlib.suppress(Exception):
        return json.loads((Path(meta or va.META_DIR) / CACHE_NAME).read_text(encoding="utf-8"))
    return {}


def fmt_row(r: dict) -> str:
    m = r["w60"]
    if m["beta"] is None:
        return f"{r['ticker']:<4} ← {r['driver_label']:<22} chưa đủ dữ liệu (n={m['n']})"
    return (f"{r['ticker']:<4} ← {r['driver_label']:<22} 1% ⇒ {m['beta']:+.2f}% (t={m['t']:+.1f}, n={m['n']}, "
            f"tương quan {m['corr']:+.2f}) · {r['verdict']}"
            + (f" · 250p {r['w250']['beta']:+.2f}%" if r["w250"]["beta"] is not None else ""))


def show(res: dict) -> str:
    if not res.get("rows"):
        return "Chưa có số liên kết — chạy: python vnstock_assets_links.py"
    lines = [f"Liên kết cổ phiếu ↔ vàng/dầu/USD · {res['window']} phiên, beta RIÊNG sau khi trừ VNINDEX "
             f"· |t| ≥ {res['t_sig']} mới tính là có · tính {res['as_of']}"]
    lines += ["  " + fmt_row(r) for r in res["rows"]]
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Độ nhạy cổ phiếu VN với vàng · dầu · USD (P4, U85)")
    ap.add_argument("--show", action="store_true", help="in bản đã lưu, không tính lại")
    a = ap.parse_args(argv)
    if a.show:
        print(show(load()))
        return 0
    res = refresh()
    print(f"[assets-links] {res}")
    if res.get("status") == "ok":
        print(show(load()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
