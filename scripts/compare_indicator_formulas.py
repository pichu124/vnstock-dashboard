"""So công thức chỉ báo hiện hành với công thức đích trên KHO THẬT — CHỈ ĐỌC (PTKT P1 đợt 1, §14b).

`docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §10b chốt RSI Wilder + SMA200. Đổi công thức làm
ngưỡng cũ lệch ⇒ trước khi đổi screener/độ rộng/chart (đợt 2) phải có số:

1. RSI(14) Cutler (SMA 14, hiện hành) vs Wilder: số mã RSI<30 / >70 mỗi phiên + số mã đổi nhóm;
2. % mã trên EMA200 (hiện hành) vs SMA200 — đúng tập mã + cửa sổ 400 ngày của
   `vnstock_runner.build_market_overview`;
3. số phiên phiếu độ rộng của `vnstock_regime` (>55% / <35%) đổi khi thay EMA200 → SMA200;
4. preset screener đọc RSI / MA200 (dò từ `vnstock_screener.PRESETS`): mã vào/ra ở phiên cuối;
5. ngưỡng mới theo phân vị để giữ nguyên TỈ LỆ mã·phiên (hoặc phiên) bị gắn nhãn như cũ.

Không ghi gì vào kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop đang chạy
(18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi.

    python scripts/compare_indicator_formulas.py
    python scripts/compare_indicator_formulas.py --days 250 --json so_cong_thuc.json

Giới hạn: RSI Wilder lấy trên CẢ chuỗi đã đọc (gieo đầu chuỗi; sau ~100 bar không còn phụ
thuộc chỗ gieo). Preset mới: `above_ma200` = giá > SMA200, `long_trend` = SMA50 > SMA200
(golden cross chuẩn); chỉ báo khác giữ nguyên số screener.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from vnstock_indicators import rsi_cutler, rsi_wilder, sma  # noqa: E402

# Phiếu "Breadth MA200" của `vnstock_regime.classify_regime` (test canh khớp).
BREADTH_BULL = 55.0
BREADTH_BEAR = 35.0
RUNNER_LOOKBACK_DAYS = 400          # vnstock_runner: cutoff = hôm nay − 400 ngày
MIN_BARS = 5                        # runner: mã < 5 bar trong cửa sổ không vào mẫu số
MA_LONG = 200
RSI_N = 14
_PRESET_KEYS = {"rsi_14", "above_ma200", "long_trend"}


# ── Logic thuần ──────────────────────────────────────────────────────────────

def _seeded_ema(x: np.ndarray, s, j, span: int):
    """EMA(span, adjust=False) gieo ở bar ``s`` đọc tại bar ``j`` (số hoặc mảng) — như runner
    gieo ở đầu cửa sổ 400 ngày. = EMA toàn chuỗi − (1−α)^(j−s)·(F[s] − x[s]), O(1) mỗi phiên."""
    f = pd.Series(x, dtype=float).ewm(span=span, adjust=False).mean().to_numpy()
    a = 2.0 / (span + 1)
    return f[j] - (1 - a) ** (np.asarray(j) - s) * (f[s] - x[s])


def ticker_day_flags(time, close, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Cờ của MỘT mã tại từng phiên ``days``, cắt dữ liệu tới phiên đó như runner đếm.

    Cột: ``counted`` (vào mẫu số độ rộng) · ``rsi_c`` (Cutler đúng như runner: cửa sổ không
    phiên giảm ⇒ NaN) · ``rsi_w`` (Wilder) · ``above_ema`` / ``above_sma`` (1/0, NaN khi
    < 200 bar trong cửa sổ)."""
    t = pd.to_datetime(pd.Series(time)).to_numpy().astype("datetime64[D]")
    x = np.asarray(close, dtype=float)
    tgt = pd.DatetimeIndex(days).to_numpy().astype("datetime64[D]")
    hi = np.searchsorted(t, tgt, side="right") - 1
    lo = np.searchsorted(t, tgt - np.timedelta64(RUNNER_LOOKBACK_DAYS, "D"), side="left")
    n = hi - lo + 1
    counted = (hi >= 0) & (n >= MIN_BARS)
    h = np.clip(hi, 0, None)
    out = pd.DataFrame({"counted": counted}, index=pd.DatetimeIndex(days))
    if not len(x):
        for col in ("rsi_c", "rsi_w", "above_ema", "above_sma"):
            out[col] = np.nan
        return out

    rc = rsi_cutler(x, RSI_N).to_numpy()
    rc = np.where(rc < 100, rc, np.nan)          # code hiện hành: loss = 0 ⇒ NaN ⇒ không đếm
    rw = rsi_wilder(x, RSI_N).to_numpy()
    has_rsi = counted & (n >= RSI_N + 1)
    out["rsi_c"] = np.where(has_rsi, rc[h], np.nan)
    out["rsi_w"] = np.where(has_rsi, rw[h], np.nan)

    s200 = sma(x, MA_LONG).to_numpy()
    long_ = counted & (n >= MA_LONG)
    ema_w = _seeded_ema(x, np.clip(lo, 0, len(x) - 1), h, MA_LONG)
    out["above_ema"] = np.where(long_, (x[h] > ema_w).astype(float), np.nan)
    out["above_sma"] = np.where(long_, (x[h] > s200[h]).astype(float), np.nan)
    return out


def breadth_vote(pct: float) -> int:
    """Phiếu độ rộng của regime: > 55% ⇒ +1 · < 35% ⇒ −1 · còn lại 0."""
    return 1 if pct > BREADTH_BULL else -1 if pct < BREADTH_BEAR else 0


def _zone(r: pd.Series) -> np.ndarray:
    return np.select([r < 30, r > 70, r.notna()], [-1, 1, 0], default=9)


def summarize_daily(per_ticker: list[pd.DataFrame]) -> pd.DataFrame:
    """Gộp cờ từng mã thành bảng mỗi phiên (mẫu số = mã ``counted``, như runner)."""
    st = pd.concat(per_ticker)
    st = st[st["counted"].astype(bool)].copy()
    st["ov_c"], st["ov_w"] = st["rsi_c"] < 30, st["rsi_w"] < 30
    st["ob_c"], st["ob_w"] = st["rsi_c"] > 70, st["rsi_w"] > 70
    st["zone_changed"] = _zone(st["rsi_c"]) != _zone(st["rsi_w"])
    st["ema"], st["sma"] = st["above_ema"] == 1, st["above_sma"] == 1
    g = st.groupby(level=0)
    daily = pd.DataFrame({
        "total": g.size(),
        "rsi_ov_cutler": g["ov_c"].sum(), "rsi_ov_wilder": g["ov_w"].sum(),
        "rsi_ob_cutler": g["ob_c"].sum(), "rsi_ob_wilder": g["ob_w"].sum(),
        "rsi_zone_changed": g["zone_changed"].sum(),
        "above_ema200": g["ema"].sum(), "above_sma200": g["sma"].sum(),
    }).astype(int)
    daily["pct_ema200"] = (daily["above_ema200"] / daily["total"] * 100).round(1)
    daily["pct_sma200"] = (daily["above_sma200"] / daily["total"] * 100).round(1)
    daily["vote_ema200"] = daily["pct_ema200"].map(breadth_vote)
    daily["vote_sma200"] = daily["pct_sma200"].map(breadth_vote)
    return daily.sort_index()


def vote_flips(daily: pd.DataFrame) -> dict:
    ve, vs = daily["vote_ema200"], daily["vote_sma200"]
    return {"khac_phieu": int((ve != vs).sum()), "nguoc_chieu": int((ve * vs == -1).sum()),
            "so_phien": int(len(daily))}


def quantile_threshold(old_values, new_values, old_thr: float, side: str):
    """Ngưỡng cho chuỗi MỚI gắn nhãn cùng tỉ lệ như ``old_thr`` trên chuỗi CŨ.

    ``side="below"``: nhãn khi < ngưỡng; ``"above"``: khi > ngưỡng. Tỉ lệ cũ 0% hoặc 100%
    (không có gì để giữ) ⇒ None."""
    old = np.asarray(old_values, dtype=float)
    new = np.asarray(new_values, dtype=float)
    old, new = old[np.isfinite(old)], new[np.isfinite(new)]
    if not old.size or not new.size:
        return None
    p = float(np.mean(old < old_thr) if side == "below" else np.mean(old > old_thr))
    if p <= 0 or p >= 1:
        return None
    q = np.quantile(new, p if side == "below" else 1 - p)
    return round(float(q), 1)


def affected_presets() -> list[str]:
    """Preset screener mà filter đọc RSI / MA200 — dò từ hằng trong lambda của registry."""
    from vnstock_screener import PRESETS
    return [name for name, cfg in PRESETS.items()
            if cfg.get("filter") is not None
            and _PRESET_KEYS & set(cfg["filter"].__code__.co_consts)]


def screener_variant(ind: dict, df: pd.DataFrame) -> dict:
    """Bản SAO chỉ báo screener với RSI Wilder + SMA200 (cùng làm tròn như `_calc_indicators`)."""
    c = df["close"].astype(float)
    new = dict(ind)
    if len(c) >= RSI_N + 1:
        v = rsi_wilder(c, RSI_N).iloc[-1]
        new["rsi_14"] = round(float(v), 1) if not np.isnan(v) else None
    if len(c) >= MA_LONG:
        s200 = round(float(sma(c, MA_LONG).iloc[-1]), 2)
        s50 = round(float(sma(c, 50).iloc[-1]), 2)
        new["above_ma200"] = bool(new["last_close"] > s200)
        new["long_trend"] = "BULL" if s50 > s200 else "BEAR"
    return new


def _match(fn, row: dict) -> bool:
    try:
        return bool(fn(row))
    except Exception:                    # như MarketScreener.scan: filter ném ⇒ không khớp
        return False


def preset_diff(rows_old: dict, rows_new: dict, presets: list[str]) -> dict:
    from vnstock_screener import PRESETS
    out = {}
    for p in presets:
        fn = PRESETS[p]["filter"]
        a = {t for t, r in rows_old.items() if _match(fn, r)}
        b = {t for t, r in rows_new.items() if _match(fn, r)}
        out[p] = {"cu": len(a), "moi": len(b), "vao": sorted(b - a), "ra": sorted(a - b)}
    return out


def suggest_thresholds(per_ticker: list[pd.DataFrame], daily: pd.DataFrame) -> dict:
    st = pd.concat(per_ticker)
    st = st[st["counted"].astype(bool)]
    rc, rw = st["rsi_c"].to_numpy(), st["rsi_w"].to_numpy()
    out = {}
    for key, thr, side, old, new in (
            ("rsi_qua_ban_30", 30.0, "below", rc, rw),
            ("rsi_reversal_40", 40.0, "below", rc, rw),
            ("rsi_qua_mua_70", 70.0, "above", rc, rw),
            ("do_rong_55", BREADTH_BULL, "above", daily["pct_ema200"], daily["pct_sma200"]),
            ("do_rong_35", BREADTH_BEAR, "below", daily["pct_ema200"], daily["pct_sma200"])):
        o = np.asarray(old, dtype=float)
        o = o[np.isfinite(o)]
        rate = (np.mean(o < thr) if side == "below" else np.mean(o > thr)) if o.size else None
        n = np.asarray(new, dtype=float)
        n = n[np.isfinite(n)]
        rate_new = (np.mean(n < thr) if side == "below" else np.mean(n > thr)) if n.size else None
        out[key] = {"cu": thr, "ty_le_cu_pct": None if rate is None else round(float(rate) * 100, 2),
                    "ty_le_moi_cung_nguong_pct": None if rate_new is None
                    else round(float(rate_new) * 100, 2),
                    "goi_y": quantile_threshold(old, new, thr, side)}
    return out


# ── Đọc kho (mỏng) ───────────────────────────────────────────────────────────

def _sessions(wh: Path, days: int) -> pd.DatetimeIndex:
    from vnstock_horizons_state import load_vnindex
    dates, _ = load_vnindex(wh)
    return pd.DatetimeIndex(pd.to_datetime(dates[-days:]))


def _breadth_flags(wh: Path, days: pd.DatetimeIndex) -> list[pd.DataFrame]:
    from vnstock_horizons_state import read_ticker
    from vnstock_price_units import normalize_price_units
    min_year = (days[0] - pd.Timedelta(days=RUNNER_LOOKBACK_DAYS)).year
    out = []
    for td in sorted((wh / "prices").glob("ticker=*")):
        tk = td.name.split("=", 1)[1]
        if len(tk) > 5 or not tk.isalpha():          # tập mã của runner
            continue
        df = read_ticker(td, min_year)
        if len(df) < MIN_BARS:
            continue
        df = normalize_price_units(df)
        out.append(ticker_day_flags(df["time"], df["close"], days))
    return out


def _screener_rows(wh: Path) -> tuple[dict, dict, str]:
    """Chỉ báo screener hiện hành (đúng `MarketScreener`) + bản đổi công thức, phiên cuối."""
    from vnstock_screener import MarketScreener, _calc_indicators, stale_lag
    scr = MarketScreener(str(wh))
    old, new, last = {}, {}, None
    for t in scr.tickers:
        df = scr._load_ticker(t)
        if df.empty or len(df) < 60:                 # min_rows mặc định của scan()
            continue
        if len(scr.sessions) and stale_lag(df["time"].iloc[-1], scr.sessions):
            continue
        ind = _calc_indicators(df)
        if not ind:
            continue
        old[t], new[t] = ind, screener_variant(ind, df)
        last = max(last, df["time"].iloc[-1]) if last is not None else df["time"].iloc[-1]
    return old, new, (pd.Timestamp(last).date().isoformat() if last is not None else "")


# ── In ───────────────────────────────────────────────────────────────────────

_ROWS = [("RSI<30 Cutler (hiện hành)", "rsi_ov_cutler"), ("RSI<30 Wilder", "rsi_ov_wilder"),
         ("RSI>70 Cutler (hiện hành)", "rsi_ob_cutler"), ("RSI>70 Wilder", "rsi_ob_wilder"),
         ("Mã đổi nhóm RSI", "rsi_zone_changed"),
         ("% trên EMA200 (hiện hành)", "pct_ema200"), ("% trên SMA200", "pct_sma200")]


def _pct_table(daily: pd.DataFrame) -> list[str]:
    lines = [f"  {'chỉ số':28s} {'min':>8s} {'p25':>8s} {'trung vị':>9s} {'p75':>8s} {'max':>8s}"]
    for label, col in _ROWS:
        q = daily[col].quantile([0, .25, .5, .75, 1]).to_list()
        lines.append(f"  {label:28s} " + " ".join(f"{v:>8,.1f}" if i != 2 else f"{v:>9,.1f}"
                                                   for i, v in enumerate(q)))
    return lines


def report(daily: pd.DataFrame, flips: dict, presets: "dict | None", preset_day: str,
           thresholds: dict) -> str:
    d0, d1 = daily.index[0].date(), daily.index[-1].date()
    gap = (daily["pct_sma200"] - daily["pct_ema200"])
    i_max = gap.abs().idxmax()
    lines = [f"So công thức chỉ báo — {len(daily)} phiên {d0} → {d1} "
             f"(mẫu số phiên cuối: {int(daily['total'].iloc[-1]):,} mã)",
             "", "1) Số mã/phiên — RSI(14) Cutler vs Wilder, % mã trên EMA200 vs SMA200 (phân vị):"]
    lines += _pct_table(daily)
    lines += ["", f"2) % trên MA200: chênh SMA200 − EMA200 trung bình {gap.mean():+,.1f} điểm %; "
              f"lớn nhất {gap.loc[i_max]:+,.1f} (phiên {i_max.date()}: "
              f"EMA200 {daily.at[i_max, 'pct_ema200']:,.1f}% vs SMA200 {daily.at[i_max, 'pct_sma200']:,.1f}%)",
              "", f"3) Phiếu độ rộng regime (>{BREADTH_BULL:.0f}% = +1, <{BREADTH_BEAR:.0f}% = −1): "
              f"khác phiếu {flips['khac_phieu']}/{flips['so_phien']} phiên, "
              f"ngược chiều (+1 ↔ −1) {flips['nguoc_chieu']} phiên"]
    if presets is not None:
        lines += ["", f"4) Preset screener đọc RSI/MA200 — phiên cuối {preset_day} "
                      "(cũ → mới, vào/ra khi đổi sang Wilder + SMA200):"]
        for p, r in presets.items():
            lines.append(f"  {p:15s} {r['cu']:>5,d} → {r['moi']:>5,d}   vào {len(r['vao']):>4,d}"
                         f"  ra {len(r['ra']):>4,d}"
                         + (f"   vào: {', '.join(r['vao'][:8])}" if r["vao"] else "")
                         + (f"   ra: {', '.join(r['ra'][:8])}" if r["ra"] else ""))
    lines += ["", "5) Ngưỡng gợi ý giữ nguyên TỈ LỆ gắn nhãn (RSI: theo mã·phiên; độ rộng: theo phiên):"]
    for k, r in thresholds.items():
        old_r = "—" if r["ty_le_cu_pct"] is None else f"{r['ty_le_cu_pct']:,.2f}%"
        same = ("—" if r["ty_le_moi_cung_nguong_pct"] is None
                else f"{r['ty_le_moi_cung_nguong_pct']:,.2f}%")
        sug = ("— (tỉ lệ cũ 0% hoặc 100%, không có gì để giữ)" if r["goi_y"] is None
               else f"{r['goi_y']:,.1f}")
        lines.append(f"  {k:16s} ngưỡng {r['cu']:>4,.0f}: tỉ lệ cũ {old_r:>8s} · "
                     f"công thức mới cùng ngưỡng {same:>8s} · ngưỡng mới gợi ý {sug}")
    tail = daily.tail(10)
    lines += ["", "10 phiên gần nhất:",
              "  phiên        tổng  <30 C  <30 W  >70 C  >70 W  đổi  %EMA200  %SMA200  phiếu E/S"]
    for d, r in tail.iterrows():
        lines.append(f"  {d.date()} {int(r.total):>6,d} {int(r.rsi_ov_cutler):>6,d} {int(r.rsi_ov_wilder):>6,d}"
                     f" {int(r.rsi_ob_cutler):>6,d} {int(r.rsi_ob_wilder):>6,d} {int(r.rsi_zone_changed):>4,d}"
                     f" {r.pct_ema200:>8,.1f} {r.pct_sma200:>8,.1f}  {int(r.vote_ema200):+d}/{int(r.vote_sma200):+d}")
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=120, help="số phiên gần nhất (mặc định 120)")
    ap.add_argument("--json", default=None, help="ghi kết quả JSON ra đường dẫn này")
    ap.add_argument("--warehouse", default=str(_REPO / "data_warehouse"))
    ap.add_argument("--no-presets", action="store_true", help="bỏ phần preset screener (nhanh hơn)")
    a = ap.parse_args(argv)

    wh = Path(a.warehouse)
    days = _sessions(wh, max(1, a.days))
    if not len(days):
        print(f"❌ Kho {wh} không có VNINDEX — không dựng được lịch phiên")
        return 2
    print(f"Đọc kho {wh}: {len(days)} phiên {days[0].date()} → {days[-1].date()} ...")
    per_ticker = _breadth_flags(wh, days)
    if not per_ticker:
        print("❌ Không có mã nào đủ dữ liệu")
        return 2
    daily = summarize_daily(per_ticker)
    flips = vote_flips(daily)
    thresholds = suggest_thresholds(per_ticker, daily)
    presets, preset_day = None, ""
    if not a.no_presets:
        old, new, preset_day = _screener_rows(wh)
        presets = preset_diff(old, new, affected_presets())
    print(report(daily, flips, presets, preset_day, thresholds))

    if a.json:
        rec = daily.reset_index(names="date")
        rec["date"] = rec["date"].dt.date.astype(str)
        payload = {"warehouse": str(wh), "days": len(daily),
                   "tu": str(days[0].date()), "den": str(days[-1].date()),
                   "daily": rec.to_dict("records"), "vote_flips": flips,
                   "presets": presets, "preset_day": preset_day, "nguong_goi_y": thresholds}
        Path(a.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=float),
                                encoding="utf-8")
        print(f"\n→ JSON: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
