"""So công thức chỉ báo CŨ (Cutler/EMA200) với công thức đang chạy (Wilder/SMA200) trên KHO THẬT
— CHỈ ĐỌC (PTKT P1, §14b).

`docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §10b chốt RSI Wilder + SMA200; đợt 2 đã chuyển screener/
độ rộng/chart (giữ ngưỡng 30/70/40). Bản CŨ tái tạo ngay trong script (không đọc từ production,
không phụ thuộc `VNSTOCK_INDICATOR_LEGACY`) để vẫn so được:

1. RSI(14) Cutler (SMA 14, cũ) vs Wilder: số mã RSI<30 / >70 mỗi phiên + số mã đổi nhóm;
2. % mã trên EMA200 (cũ) vs SMA200 — đúng tập mã + cửa sổ 400 ngày của
   `vnstock_runner.build_market_overview`;
3. số phiên phiếu độ rộng của `vnstock_regime` (>55% / <35%) đổi khi thay EMA200 → SMA200;
4. preset screener đọc RSI / MA200 (dò từ `vnstock_screener.PRESETS`): mã vào/ra ở phiên cuối;
5. ngưỡng mới theo phân vị để giữ nguyên TỈ LỆ mã·phiên (hoặc phiên) bị gắn nhãn như cũ;
6. (`--signal-quality`, mặc định bật) đếm số mã không trả lời "công thức nào TỐT HƠN" ⇒ lợi
   suất VƯỢT VN-Index T+5/T+20 sau quá bán / quá mua / reversal cho Cutler ngưỡng cũ · Wilder
   ngưỡng cũ · Wilder ngưỡng gợi ý (mục 5), có và không lọc GTGD TB20 (`--min-gtgd`). Cửa sổ
   tín hiệu = `--days` phiên kết thúc `--fwd` phiên trước phiên cuối; chỉ dùng bar SAU phiên
   tín hiệu tới đúng T+h;
7. (`--breadth-diag`) % mã trên SMA200/EMA200 theo 5 mẫu số + số mã kho đứng — để biết độ
   rộng ~11% là thị trường hẹp THẬT hay do mẫu số của runner.

Không ghi gì vào kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop đang chạy
(18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi.

    python scripts/compare_indicator_formulas.py --breadth-diag --json so_cong_thuc.json
    python scripts/compare_indicator_formulas.py --days 250 --no-signal-quality

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

from vnstock_breadth_universe import session_gtgd20, session_lag  # noqa: E402
from vnstock_indicators import rsi_cutler, rsi_wilder_unfrozen, sma  # noqa: E402

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
    rc = np.where(rc < 100, rc, np.nan)          # code cũ: loss = 0 ⇒ NaN ⇒ không đếm
    rw = rsi_wilder_unfrozen(x, RSI_N).to_numpy()
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
    """Bản SAO chỉ báo screener với RSI Wilder + SMA200 (cùng làm tròn như `_calc_indicators`) —
    biến thể đã đo và đợt 2 ship nguyên văn (test canh `_calc_indicators` == bản này)."""
    c = df["close"].astype(float)
    new = dict(ind)
    if len(c) >= RSI_N + 1:
        v = rsi_wilder_unfrozen(c, RSI_N).iloc[-1]
        new["rsi_14"] = round(float(v), 1) if not np.isnan(v) else None
    if len(c) >= MA_LONG:
        s200 = round(float(sma(c, MA_LONG).iloc[-1]), 2)
        s50 = round(float(sma(c, 50).iloc[-1]), 2)
        new["above_ma200"] = bool(new["last_close"] > s200)
        new["long_trend"] = "BULL" if s50 > s200 else "BEAR"
    return new


def screener_legacy(ind: dict, df: pd.DataFrame) -> dict:
    """Bản SAO chỉ báo screener với công thức CŨ (trước đợt 2): RSI Cutler — cửa sổ không phiên
    giảm ⇒ None — và EMA50/EMA200 cho ``long_trend`` / ``above_ma200``."""
    c = df["close"].astype(float)
    old = dict(ind)
    if len(c) >= RSI_N + 1:
        v = rsi_cutler(c, RSI_N).iloc[-1]
        old["rsi_14"] = round(float(v), 1) if v < 100 else None      # NaN < 100 cũng False
    if len(c) >= MA_LONG:
        e200 = round(float(c.ewm(span=MA_LONG, adjust=False).mean().iloc[-1]), 2)
        e50 = round(float(c.ewm(span=50, adjust=False).mean().iloc[-1]), 2)
        old["above_ma200"] = bool(old["last_close"] > e200)
        old["long_trend"] = "BULL" if e50 > e200 else "BEAR"
    return old


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


# ── 6) Chất lượng tín hiệu theo biến thể ─────────────────────────────────────

SCREENER_MIN_ROWS = 60              # min_rows mặc định của MarketScreener.scan
P52_BARS, P52_MIN_BARS = 252, 50    # _calc_indicators: df.tail(252), cần ≥ 50 bar
REVERSAL_P52 = 15.0                 # preset reversal: 52w_pct < 15
STALE_SESSIONS = 5                  # = vnstock_screener.STALE_SESSIONS (test canh)
# Ngưỡng Wilder giữ tỉ lệ gắn nhãn, đo kho thật 120 phiên tới 03/11 — chỉ dùng khi lượt chạy
# không tự tính được (`suggest_thresholds` trả None).
SUGGESTED_FALLBACK = {"oversold": 35.0, "overbought": 66.9, "reversal": 42.2}
_SUGGEST_KEY = {"oversold": "rsi_qua_ban_30", "overbought": "rsi_qua_mua_70",
                "reversal": "rsi_reversal_40"}
_OLD_THR = {"oversold": 30.0, "overbought": 70.0, "reversal": 40.0}


def ticker_signal_panel(df: pd.DataFrame, sessions, vni_close, sig_days,
                        horizons=(5, 20)) -> pd.DataFrame:
    """Mỗi phiên ``sig_days`` mã CÓ bar (và đủ ``SCREENER_MIN_ROWS`` bar tính tới đó): chỉ báo như
    screener đọc ở phiên đó + lợi suất VƯỢT VN-Index ``ex_<h>`` (%), đóng cửa phiên tín hiệu →
    đóng cửa ``h`` phiên sau theo lịch ``sessions`` (mã không có bar phiên đó ⇒ giá khớp gần nhất
    TRƯỚC nó, không bao giờ bar sau). Thiếu ``h`` phiên phía sau ⇒ NaN.

    Cột: ``rsi_c`` (Cutler, cửa sổ không phiên giảm ⇒ NaN như screener) · ``rsi_w`` · ``p52``
    (52w_pct) — cùng làm tròn 1 chữ số như ``_calc_indicators`` · ``gtgd20`` (tỷ VND)."""
    t = pd.DatetimeIndex(pd.to_datetime(df["time"])).normalize()
    c = df["close"].astype(float).reset_index(drop=True)
    s = pd.DatetimeIndex(sessions)
    vni = np.asarray(vni_close, dtype=float)
    rc = rsi_cutler(c, RSI_N).round(1)
    rc = rc.where(rc < 100)
    hh = df["high"].astype(float).reset_index(drop=True).rolling(P52_BARS, min_periods=P52_MIN_BARS).max()
    ll = df["low"].astype(float).reset_index(drop=True).rolling(P52_BARS, min_periods=P52_MIN_BARS).min()
    p52 = ((c - ll) / (hh - ll) * 100).where(hh > ll, 50.0).where(hh.notna()).round(1)

    sel = np.flatnonzero(t.isin(pd.DatetimeIndex(sig_days)) & (np.arange(1, len(c) + 1) >= SCREENER_MIN_ROWS))
    pos = s.get_indexer(t[sel])
    out = pd.DataFrame({"rsi_c": rc.to_numpy()[sel],
                        "rsi_w": rsi_wilder_unfrozen(c, RSI_N).round(1).to_numpy()[sel],
                        "p52": p52.to_numpy()[sel],
                        "gtgd20": session_gtgd20(t, c, df["volume"], s).to_numpy()[pos]},
                       index=t[sel])
    x, tv, sv = c.to_numpy(), t.to_numpy(), s.to_numpy()
    for h in horizons:
        j = pos + h
        ok = j < len(s)
        jj = np.where(ok, j, 0)
        k = np.searchsorted(tv, sv[jj], side="right") - 1     # bar cuối ≤ phiên đích
        r = x[k] / x[sel] - 1.0
        rv = vni[jj] / vni[pos] - 1.0
        out[f"ex_{h}"] = np.where(ok, (r - rv) * 100.0, np.nan)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> "tuple[float, float] | tuple[None, None]":
    """Khoảng Wilson 95% (%) cho tỉ lệ k/n. Giả định quan sát ĐỘC LẬP — mã·phiên chồng nhau
    thì khoảng thật rộng hơn."""
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(float(mid - half) * 100, 1), round(float(mid + half) * 100, 1)


def signal_thresholds(thresholds: "dict | None") -> dict:
    """Ngưỡng Wilder gợi ý theo phân vị: lấy từ lượt chạy (`suggest_thresholds`), thiếu thì
    hằng đã đo."""
    out = {}
    for sig, key in _SUGGEST_KEY.items():
        v = (thresholds or {}).get(key, {}).get("goi_y")
        out[sig] = float(v) if v is not None else SUGGESTED_FALLBACK[sig]
    return out


def signal_variants(suggested: dict) -> list[tuple[str, str, str, float]]:
    """(tín hiệu, nhãn biến thể, cột RSI, ngưỡng) — Cutler ngưỡng cũ · Wilder ngưỡng cũ · Wilder
    ngưỡng gợi ý."""
    out = []
    for sig in ("oversold", "overbought", "reversal"):
        old, new = _OLD_THR[sig], suggested[sig]
        out += [(sig, f"Cutler {old:g} (cũ)", "rsi_c", old),
                (sig, f"Wilder {old:g}", "rsi_w", old),
                (sig, f"Wilder {new:g} (gợi ý)", "rsi_w", new)]
    return out


def signal_mask(panel: pd.DataFrame, sig: str, col: str, thr: float) -> pd.Series:
    """Đúng lambda preset (NaN/thiếu ⇒ không khớp, như ``r.get(...)`` + so None ném lỗi)."""
    r = panel[col]
    if sig == "oversold":
        return r < thr
    if sig == "overbought":
        return r > thr
    return (panel["p52"] < REVERSAL_P52) & (r < thr)


def excess_stats(ex: pd.Series, tickers: pd.Series) -> dict:
    ok = ex.notna()
    x = ex[ok].to_numpy(dtype=float)
    n = int(x.size)
    if not n:
        return {"n": 0, "so_ma": 0, "tb": None, "trung_vi": None, "duong_pct": None,
                "wilson_lo": None, "wilson_hi": None}
    k = int((x > 0).sum())
    lo, hi = wilson(k, n)
    return {"n": n, "so_ma": int(tickers[ok].nunique()), "tb": round(float(x.mean()), 2),
            "trung_vi": round(float(np.median(x)), 2), "duong_pct": round(k / n * 100, 1),
            "wilson_lo": lo, "wilson_hi": hi}


def signal_quality(panel: pd.DataFrame, suggested: dict, horizons=(5, 20),
                   min_gtgd: float = 1.0) -> list[dict]:
    """Bảng chất lượng: mỗi (lọc thanh khoản × chân trời × tín hiệu × biến thể) một dòng, kèm dòng
    ``nền`` (mọi mã·phiên cùng lọc) để biết tín hiệu có khác ngẫu nhiên không. ``panel`` = các
    ``ticker_signal_panel`` gộp, có cột ``ticker``."""
    rows = []
    liquid = panel["gtgd20"] >= min_gtgd
    for loc, keep in (("tat_ca", pd.Series(True, index=panel.index)), ("gtgd", liquid)):
        p = panel[keep.to_numpy()]
        for h in horizons:
            ex = p[f"ex_{h}"]
            rows.append({"loc": loc, "h": h, "tin_hieu": "nen", "bien_the": "mọi mã·phiên",
                         **excess_stats(ex, p["ticker"])})
            for sig, label, col, thr in signal_variants(suggested):
                m = signal_mask(p, sig, col, thr).to_numpy()
                rows.append({"loc": loc, "h": h, "tin_hieu": sig, "bien_the": label,
                             **excess_stats(ex[m], p["ticker"][m])})
    return rows


# ── 7) Chẩn đoán độ rộng: % trên MA200 theo mẫu số ───────────────────────────

DENOMINATORS = [
    ("a", "runner (mọi mã ≥5 bar/400 ngày; <200 bar = không trên)"),
    ("a_fresh", "(a) bỏ mã bar cuối trễ > 5 phiên"),
    ("b", "chỉ mã ≥ 200 bar trong 400 ngày"),
    ("c", "(b) + GTGD TB20 ≥ ngưỡng"),
    ("d", "(b) ∩ HOSE"),
    ("e", "(b) ∩ VN30 (rổ hằng số)"),
]


def ticker_breadth_extra(time, close, volume, days, sessions) -> pd.DataFrame:
    """Thêm cho mỗi phiên ``days``: ``gtgd20`` (tỷ, theo lịch phiên) + ``lag`` = số phiên lịch
    SAU bar cuối ≤ phiên đó (như ``vnstock_screener.stale_sessions``; NaN khi chưa có bar)."""
    t = pd.DatetimeIndex(pd.to_datetime(pd.Series(time))).normalize()
    d = pd.DatetimeIndex(days)
    g = session_gtgd20(t, close, volume, pd.DatetimeIndex(sessions)).reindex(d)
    return pd.DataFrame({"gtgd20": g.to_numpy(), "lag": session_lag(t, sessions, d)}, index=d)


def breadth_by_denominator(st: pd.DataFrame, hose: "set | None", vn30: set,
                           min_gtgd: float = 1.0) -> dict[str, pd.DataFrame]:
    """``st``: cờ ``ticker_day_flags`` + ``ticker_breadth_extra`` mọi mã gộp, cột ``ticker``,
    index = phiên. Trả {mẫu số: DataFrame(n, pct_ema200, pct_sma200)}; ``hose`` None ⇒ bỏ (d)."""
    counted = st["counted"].astype(bool)
    has200 = counted & st["above_sma"].notna()
    masks = {"a": counted, "a_fresh": counted & (st["lag"] <= STALE_SESSIONS),
             "b": has200, "c": has200 & (st["gtgd20"] >= min_gtgd),
             "e": has200 & st["ticker"].isin(vn30)}
    if hose is not None:
        masks["d"] = has200 & st["ticker"].isin(hose)
    days = st.index.unique().sort_values()
    out = {}
    for key, _ in DENOMINATORS:
        if key not in masks:
            continue
        sub = st[masks[key].to_numpy()]
        g = sub.groupby(level=0)
        n = g.size().reindex(days, fill_value=0)
        e = (sub["above_ema"] == 1).groupby(level=0).sum().reindex(days, fill_value=0)
        s_ = (sub["above_sma"] == 1).groupby(level=0).sum().reindex(days, fill_value=0)
        den = n.where(n > 0)
        out[key] = pd.DataFrame({"n": n.astype(int), "pct_ema200": (e / den * 100).round(1),
                                 "pct_sma200": (s_ / den * 100).round(1)})
    return out


def stale_counts(st: pd.DataFrame) -> pd.Series:
    """Mỗi phiên: số mã runner vẫn đếm mà bar cuối trễ > ``STALE_SESSIONS`` phiên."""
    m = st["counted"].astype(bool) & (st["lag"] > STALE_SESSIONS)
    return m.groupby(level=0).sum().astype(int)


# ── Đọc kho (mỏng) ───────────────────────────────────────────────────────────

def _vnindex(wh: Path) -> tuple[pd.DatetimeIndex, np.ndarray]:
    from vnstock_horizons_state import load_vnindex
    dates, closes = load_vnindex(wh)
    return pd.DatetimeIndex(pd.to_datetime(dates)), np.asarray(closes, dtype=float)


SIGNAL_HISTORY_DAYS = 600           # 252 bar cho 52w_pct + ~100 bar cho RSI Wilder hết phụ thuộc gieo


def _scan(wh: Path, days, sessions, vni, sig_days, horizons, want_diag: bool) -> dict:
    """Đọc mỗi mã MỘT lần (chỉ đọc). Cờ độ rộng vẫn tính trên đúng các năm như trước (số cũ
    không đổi khi đọc thêm lịch sử cho phần tín hiệu)."""
    from vnstock_horizons_state import read_ticker
    from vnstock_price_units import normalize_price_units
    y_breadth = (days[0] - pd.Timedelta(days=RUNNER_LOOKBACK_DAYS)).year
    min_year = y_breadth
    if sig_days is not None and len(sig_days):
        min_year = min(min_year, (sig_days[0] - pd.Timedelta(days=SIGNAL_HISTORY_DAYS)).year)
    flags, panels, diag = [], [], []
    for td in sorted((wh / "prices").glob("ticker=*")):
        tk = td.name.split("=", 1)[1]
        if len(tk) > 5 or not tk.isalpha():          # tập mã của runner
            continue
        full = read_ticker(td, min_year)
        if len(full) < MIN_BARS:
            continue
        full = normalize_price_units(full)
        df = full[full["time"].dt.year >= y_breadth]
        if len(df) >= MIN_BARS:
            f = ticker_day_flags(df["time"], df["close"], days)
            flags.append(f)
            if want_diag and "volume" in df.columns:
                diag.append(f.join(ticker_breadth_extra(df["time"], df["close"], df["volume"],
                                                        days, sessions)).assign(ticker=tk))
        if sig_days is not None and {"high", "low", "volume"} <= set(full.columns):
            p = ticker_signal_panel(full, sessions, vni, sig_days, horizons)
            if len(p):
                panels.append(p.assign(ticker=tk))
    return {"flags": flags, "panels": panels, "diag": diag}


def _hose_tickers(wh: Path) -> "set | None":
    """Sàn từ `_meta/exchange_map.json` + `industry_classification.parquet` (chỉ đọc, không mạng)."""
    from vnstock_exchange_map import load_exchange_map
    m = load_exchange_map(wh)
    return {t for t, ex in m.items() if ex == "HOSE"} if m else None


def _screener_rows(wh: Path) -> tuple[dict, dict, str]:
    """Chỉ báo screener phiên cuối (đúng `MarketScreener`): bản cũ tái tạo + bản Wilder/SMA200."""
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
        old[t], new[t] = screener_legacy(ind, df), screener_variant(ind, df)
        last = max(last, df["time"].iloc[-1]) if last is not None else df["time"].iloc[-1]
    return old, new, (pd.Timestamp(last).date().isoformat() if last is not None else "")


# ── In ───────────────────────────────────────────────────────────────────────

_ROWS = [("RSI<30 Cutler (cũ)", "rsi_ov_cutler"), ("RSI<30 Wilder", "rsi_ov_wilder"),
         ("RSI>70 Cutler (cũ)", "rsi_ob_cutler"), ("RSI>70 Wilder", "rsi_ob_wilder"),
         ("Mã đổi nhóm RSI", "rsi_zone_changed"),
         ("% trên EMA200 (cũ)", "pct_ema200"), ("% trên SMA200", "pct_sma200")]


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


_SIG_LABEL = {"nen": "nền", "oversold": "quá bán", "overbought": "quá mua", "reversal": "reversal"}


def _num(v, fmt: str) -> str:
    return "—" if v is None else format(v, fmt)


def report_signal_quality(rows: list[dict], sig_days, horizons, min_gtgd: float) -> str:
    lines = ["", f"6) Chất lượng tín hiệu — {len(sig_days)} phiên tín hiệu {sig_days[0].date()} → "
                 f"{sig_days[-1].date()}; lợi suất VƯỢT VN-Index (%), đóng cửa phiên tín hiệu → "
                 f"đóng cửa T+{'/T+'.join(map(str, horizons))}:",
             "  ⚠ Mã·phiên CHỒNG NHAU (cùng mã nhiều phiên liền dùng chung bar tương lai; mọi mã cùng "
             "phiên chịu chung một cú thị trường) ⇒ Wilson 95% giả định độc lập, HẸP hơn thật nhiều.",
             f"  ⚠ {len(sig_days)} phiên là MỘT giai đoạn thị trường — 'tốt hơn' ở đây chỉ đúng cho giai "
             "đoạn này. So từng dòng với dòng 'nền' (mọi mã·phiên cùng lọc): chỉ phần CHÊNH là tín hiệu.",
             "  ⚠ Quá mua là tín hiệu CẢNH BÁO ⇒ biến thể tốt hơn là vượt VN-Index THẤP hơn nền; quá bán "
             "/ reversal là tín hiệu mua ⇒ CAO hơn nền."]
    for loc, title in (("tat_ca", "không lọc thanh khoản"),
                       ("gtgd", f"GTGD TB20 ≥ {min_gtgd:,.2f} tỷ VND")):
        for h in horizons:
            lines += ["", f"  [{title}] T+{h}:",
                      f"    {'tín hiệu':10s} {'biến thể':24s} {'n':>8s} {'số mã':>6s} {'TB %':>7s}"
                      f" {'trung vị %':>10s} {'dương %':>8s}  Wilson 95%"]
            for r in rows:
                if r["loc"] != loc or r["h"] != h:
                    continue
                ci = ("—" if r["wilson_lo"] is None
                      else f"{r['wilson_lo']:,.1f}–{r['wilson_hi']:,.1f}")
                lines.append(f"    {_SIG_LABEL[r['tin_hieu']]:10s} {r['bien_the']:24s} {r['n']:>8,d}"
                             f" {r['so_ma']:>6,d} {_num(r['tb'], '>7,.2f')} {_num(r['trung_vi'], '>10,.2f')}"
                             f" {_num(r['duong_pct'], '>8,.1f')}  {ci}")
    return "\n".join(lines)


def report_breadth_diag(diag: dict, stale: pd.Series, hose_ok: bool, min_gtgd: float) -> str:
    lines = ["", "7) Chẩn đoán độ rộng — % mã trên SMA200 / EMA200 theo MẪU SỐ (n = số mã mẫu số):"]
    labels = dict(DENOMINATORS)
    labels["c"] = labels["c"].replace("ngưỡng", f"{min_gtgd:,.2f} tỷ")
    if not hose_ok:
        lines.append("  (d) HOSE: BỎ — kho không có `_meta/exchange_map.json` lẫn "
                     "`industry_classification.parquet` (dựng: `python vnstock_exchange_map.py --build`).")
    lines.append("  (e) VN30 dùng rổ HẰNG SỐ hiện hành cho mọi phiên (rổ đổi đầu tháng 8 không được tính).")
    lines.append(f"  {'mẫu số':58s} {'n trung vị':>10s}   SMA200 min/p25/tv/p75/max"
                 "            EMA200 min/p25/tv/p75/max")
    for k, d in diag.items():
        qs = [d[c].quantile([0, .25, .5, .75, 1]).to_list() for c in ("pct_sma200", "pct_ema200")]
        lines.append(f"  ({k}) {labels[k]:53s} {int(d['n'].median()):>10,d}   "
                     + "  ".join("/".join(f"{v:,.1f}" for v in q) for q in qs))
    lines += ["", f"  Mã runner vẫn đếm mà bar cuối trễ > {STALE_SESSIONS} phiên (đứng/cách ly): "
                  f"trung vị {int(stale.median()) if len(stale) else 0:,d}/phiên",
              "", "  10 phiên gần nhất — %SMA200 / %EMA200 (n):",
              "  phiên       " + "".join(f"{'(' + k + ')':>22s}" for k in diag) + f"{'trễ>5':>8s}"]
    days = next(iter(diag.values())).index[-10:]
    for day in days:
        cells = "".join(f"{_num(d.at[day, 'pct_sma200'], ',.1f') + '/' + _num(d.at[day, 'pct_ema200'], ',.1f')}"
                        f" ({int(d.at[day, 'n']):,d})".rjust(22) for d in diag.values())
        lines.append(f"  {day.date()} {cells}{int(stale.get(day, 0)):>8,d}")
    return "\n".join(lines)


def _clean(v):
    return None if isinstance(v, float) and np.isnan(v) else v


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=120, help="số phiên gần nhất (mặc định 120)")
    ap.add_argument("--json", default=None, help="ghi kết quả JSON ra đường dẫn này")
    ap.add_argument("--warehouse", default=str(_REPO / "data_warehouse"))
    ap.add_argument("--no-presets", action="store_true", help="bỏ phần preset screener (nhanh hơn)")
    ap.add_argument("--signal-quality", action=argparse.BooleanOptionalAction, default=True,
                    help="6) lợi suất sau tín hiệu theo biến thể (mặc định bật)")
    ap.add_argument("--fwd", type=int, default=20,
                    help="chân trời dài nhất (phiên); cửa sổ tín hiệu = --days phiên kết thúc "
                         "--fwd phiên trước phiên cuối (mặc định 20)")
    ap.add_argument("--min-gtgd", type=float, default=1.0, help="lọc GTGD TB20 tối thiểu, tỷ VND")
    ap.add_argument("--breadth-diag", action="store_true", help="7) % trên MA200 theo mẫu số")
    a = ap.parse_args(argv)

    wh = Path(a.warehouse)
    sessions, vni = _vnindex(wh)
    days = sessions[-max(1, a.days):]
    if not len(days):
        print(f"❌ Kho {wh} không có VNINDEX — không dựng được lịch phiên")
        return 2
    fwd = max(1, a.fwd)
    horizons = tuple(sorted({min(5, fwd), fwd}))
    sig_days = None
    if a.signal_quality:
        sig_days = sessions[max(0, len(sessions) - fwd - max(1, a.days)):len(sessions) - fwd]
        if not len(sig_days):
            print(f"⚠ Lịch VNINDEX chỉ {len(sessions)} phiên, không đủ {fwd} phiên phía sau — bỏ phần 6")
            sig_days = None
    print(f"Đọc kho {wh}: {len(days)} phiên {days[0].date()} → {days[-1].date()} ...")
    scan = _scan(wh, days, sessions, vni, sig_days, horizons, a.breadth_diag)
    per_ticker = scan["flags"]
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

    quality, suggested = None, signal_thresholds(thresholds)
    if sig_days is not None and scan["panels"]:
        quality = signal_quality(pd.concat(scan["panels"]), suggested, horizons, a.min_gtgd)
        print(report_signal_quality(quality, sig_days, horizons, a.min_gtgd))
    diag_out = None
    if a.breadth_diag and scan["diag"]:
        st = pd.concat(scan["diag"])
        hose = _hose_tickers(wh)
        from vnstock_vn30 import fallback_members
        diag = breadth_by_denominator(st, hose, set(fallback_members()), a.min_gtgd)
        stale = stale_counts(st)
        print(report_breadth_diag(diag, stale, hose is not None, a.min_gtgd))
        diag_out = {k: [{"date": str(i.date()), **{c: _clean(v) for c, v in r.items()}}
                        for i, r in d.iterrows()] for k, d in diag.items()}
        diag_out["stale"] = {str(i.date()): int(v) for i, v in stale.items()}

    if a.json:
        rec = daily.reset_index(names="date")
        rec["date"] = rec["date"].dt.date.astype(str)
        payload = {"warehouse": str(wh), "days": len(daily),
                   "tu": str(days[0].date()), "den": str(days[-1].date()),
                   "daily": rec.to_dict("records"), "vote_flips": flips,
                   "presets": presets, "preset_day": preset_day, "nguong_goi_y": thresholds,
                   "signal_quality": quality, "nguong_tin_hieu": suggested,
                   "breadth_diag": diag_out}
        Path(a.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=float),
                                encoding="utf-8")
        print(f"\n→ JSON: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
