"""Brief 3 khung — TRẠNG THÁI + I/O (P1a, chạy bóng). Lõi tính ở `vnstock_horizons`.

Thiết kế: `docs/THIET-KE-BRIEF-3-KHUNG.md` §3.10. File `_meta/horizon_state.json`:
  inputs[as_of]  = đầu vào từng phiên {close, score, n, label_old, floor_old,
                   momentum, breadth_pct, ad, nn, source, machine, recorded_at}
                   — phiên chỉ có `close` là nền lịch sử cho trung hạn/🚨.
  published[]    = append-only, mỗi phiên một bản: trạng thái 3 khung + mức +
                   🚨 + bảo vệ + Stance, kèm machine/computed_at/source.
Mọi tầng được GẤP từ inputs đã lưu (không đọc lại parquet mỗi đêm) ⇒ sửa bar
quá khứ không âm thầm đổi "từ ngày"; parquet chỉ để backfill + kiểm "revision".

Cổng ghi: as_of = bar VNINDEX mới nhất ≤ phiên phủ (`session_covered_at`, sau
15:05); đã có bản cho as_of ⇒ no-op (máy chạy sau, laptop "Cập nhật còn lại")
trừ `--force`. CHƯA nối brief — brief chỉ đọc file này từ P1b.

    python vnstock_horizons_state.py --update      # bước pipeline `horizons`
    python vnstock_horizons_state.py --backfill    # một lần sau khi merge (○)
    python vnstock_horizons_state.py --show | --replay
Kill-switch bước pipeline: VNSTOCK_HORIZONS_STEP=0.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

import vnstock_horizons as hz

_REPO = Path(__file__).resolve().parent
_WAREHOUSE = _REPO / "data_warehouse"
STATE_NAME = "horizon_state.json"
SCHEMA_VERSION = 1
PARAMS = hz.MediumParams()

_EMA_ALPHA = 2 / (200 + 1)
_RUNNER_LOOKBACK_DAYS = 400          # vnstock_runner: cutoff = hôm nay − 400 ngày
_MIN_SESSIONS = 260                  # ≥40 tuần có bar + 39 tuần cho bộ giải
_REVISION_TOL = 0.001                # đóng cửa lưu vs parquet lệch >0.1% ⇒ "revision"


def machine() -> str:
    return os.environ.get("COMPUTERNAME") or platform.node() or "?"


# ── Đọc kho (chỉ đọc) ────────────────────────────────────────────────────

def read_ticker(td: Path, min_year: int | None = None) -> pd.DataFrame:
    """Gộp mọi parquet của một mã (kể cả "(conflicted copy)"), khử trùng ngày."""
    frames = []
    for yd in sorted(td.glob("year=*")):
        try:
            if min_year and int(yd.name.split("=")[1]) < min_year:
                continue
        except ValueError:
            continue
        for pf in yd.glob("*.parquet"):
            try:
                frames.append(pd.read_parquet(pf))
            except Exception:
                continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df.columns = [str(c).lower() for c in df.columns]
    for col in ("time", "trading_date", "date"):
        if col in df.columns:
            df = df.rename(columns={col: "time"})
            break
    if "time" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    df["time"] = pd.to_datetime(df["time"]).dt.normalize()
    return (df.sort_values("time").drop_duplicates("time", keep="last")
              .reset_index(drop=True))


def load_vnindex(warehouse: Path = _WAREHOUSE) -> tuple[list[date], list[float]]:
    """VNINDEX ngày, KHÔNG ghép bar live (`augment=False`), khử trùng ngày."""
    for sym in ("VNINDEX", "VN-INDEX", "^VNINDEX"):
        df = read_ticker(warehouse / "prices" / f"ticker={sym}")
        if df.empty:
            continue
        c = df["close"].astype(float)
        if c.iloc[-1] > 5000:                    # như vnstock_brief._load_vnindex_df
            c = c / 1000
        return hz.dedupe_daily([t.date() for t in df["time"]], c.tolist())
    return [], []


def tech_frame(dates: list[date], closes: list[float]) -> pd.DataFrame:
    """Kỹ thuật VNINDEX từng phiên — cùng công thức `_vnindex_technicals`."""
    c = pd.Series(closes, index=pd.to_datetime(dates), dtype=float)
    d = c.diff(1)
    up = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(com=13, adjust=False).mean()
    return pd.DataFrame({
        "close": c, "ma20": c.rolling(20).mean(), "ma50": c.rolling(50).mean(),
        "ma200": c.rolling(200).mean(),
        "rsi14": 100.0 - 100.0 / (1.0 + up / dn.replace(0, np.nan)),
        "chg": (c / c.shift(1) - 1.0) * 100,
    })


def load_nn(warehouse: Path = _WAREHOUSE) -> dict[str, float]:
    p = warehouse / "_meta" / "foreign_net_daily.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for d, rec in raw.items():
        try:
            out[str(d)[:10]] = float(rec["net"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def breadth_history(warehouse: Path, targets: list[date]) -> dict[date, dict]:
    """% mã trên EMA200 + A/D cho TỪNG phiên, đếm như `compute_market_overview`:
    mã ≥5 bar trong 400 ngày lùi vào mẫu số; EMA200 (adjust=False) bắt đầu ở bar
    đầu cửa sổ, chỉ tính khi ≥200 bar; A/D = bar cuối so bar liền trước.
    EMA cửa sổ = EMA toàn chuỗi − (1−α)^k·(F[lo] − x[lo]) — O(1) mỗi phiên.
    Đối chiếu ctx đã in 58 phiên 06–10/2026: lệch TB 0.8 điểm %."""
    if not targets:
        return {}
    tgt = np.array([np.datetime64(d) for d in targets])
    cut = tgt - np.timedelta64(_RUNNER_LOOKBACK_DAYS, "D")
    n_t = len(tgt)
    total = np.zeros(n_t, int); above = np.zeros(n_t, int)
    adv = np.zeros(n_t, int); dec = np.zeros(n_t, int)
    min_year = targets[0].year - 2
    for td in sorted((warehouse / "prices").glob("ticker=*")):
        tk = td.name.split("=", 1)[1]
        if len(tk) > 5 or not tk.isalpha():
            continue
        df = read_ticker(td, min_year)
        if len(df) < 5:
            continue
        x = df["close"].astype(float).to_numpy()
        x = np.where(x > 500, x / 1000, x)       # vnstock_runner._normalize_prices
        t = df["time"].to_numpy().astype("datetime64[D]")
        f = pd.Series(x).ewm(alpha=_EMA_ALPHA, adjust=False).mean().to_numpy()
        hi = np.searchsorted(t, tgt, side="right") - 1
        lo = np.searchsorted(t, cut, side="left")
        n = hi - lo + 1
        ok = (hi >= 0) & (n >= 5)
        total += ok
        has200 = ok & (n >= 200)
        if has200.any():
            h, l_ = hi[has200], lo[has200]
            ema = f[h] - (1 - _EMA_ALPHA) ** (h - l_) * (f[l_] - x[l_])
            above[np.where(has200)[0][x[h] > ema]] += 1
        two = ok & (n >= 2)
        if two.any():
            h = hi[two]
            diff = x[h] - x[h - 1]
            idx = np.where(two)[0]
            adv[idx[diff > 0]] += 1
            dec[idx[diff < 0]] += 1
    out = {}
    for i, d in enumerate(targets):
        if total[i]:
            out[d] = {"total": int(total[i]),
                      "above_ma200_pct": round(above[i] / total[i] * 100, 1),
                      "advances": int(adv[i]), "declines": int(dec[i]),
                      "ad_ratio": round(adv[i] / max(dec[i], 1), 2)}
    return out


def live_breadth(warehouse: Path, as_of: date) -> tuple[dict, str]:
    """Breadth của as_of: `market_overview.json` (đúng thứ brief đêm nay thấy)
    nếu `data_date` khớp, không thì tái dựng từ parquet."""
    try:
        mo = json.loads((warehouse / "_meta" / "market_overview.json").read_text(encoding="utf-8"))
        if str(mo.get("data_date") or "")[:10] == as_of.isoformat() and mo.get("breadth"):
            return mo["breadth"], "market_overview"
    except Exception:
        pass
    return breadth_history(warehouse, [as_of]).get(as_of, {}), "parquet"


# ── Đầu vào từng phiên ───────────────────────────────────────────────────

def score_inputs(dates: list[date], closes: list[float], targets: list[date],
                 breadth: dict, nn: dict) -> dict[date, dict]:
    """Điểm 7 phiếu + nhãn/floor CŨ cho từng phiên `targets`, bằng chính code repo.
    Momentum KHÔNG gồm tin tức/vĩ mô (replay không có) — live và backfill cùng
    cách tính để so được với nhau (F2)."""
    from vnstock_brief_guards_common import _bias_floor_dir
    from vnstock_market_sentiment import compute_market_sentiment
    from vnstock_regime import classify_regime

    want = set(targets)
    tf = tech_frame(dates, closes)
    out: dict[date, dict] = {}
    for d, r in zip(dates, tf.itertuples()):
        if d not in want or not np.isfinite(r.ma200):
            continue
        tech = {"close": r.close, "ma20": r.ma20, "ma50": r.ma50, "ma200": r.ma200,
                "rsi14": round(float(r.rsi14), 1),
                "day_change_pct": round(float(r.chg), 2)}
        b = breadth.get(d, {})
        nn_d = nn.get(d.isoformat())
        reg = classify_regime(tech, b, round(nn_d, 1) if nn_d is not None else 0.0)
        mom = compute_market_sentiment(b, nn_d, tech).get("momentum")
        out[d] = {"score": int(reg["score"]), "n": int(reg["n_signals"]),
                  "label_old": reg.get("label_old", reg["label"]), "momentum": mom,
                  "floor_old": _bias_floor_dir(mom, reg["score"]),
                  "breadth_pct": b.get("above_ma200_pct"),
                  "ad": [b.get("advances"), b.get("declines")] if b.get("advances") is not None else None,
                  "nn": nn_d}
    return out


# ── Gấp trạng thái ───────────────────────────────────────────────────────

def _since(dates: list[date], series: list, end: int) -> date:
    i = end
    while i > 0 and series[i - 1] == series[end]:
        i -= 1
    return dates[i]


def fold(inputs: dict, as_of: date | None = None,
         params: hz.MediumParams = PARAMS) -> dict | None:
    """Trạng thái 3 khung tại `as_of` gấp từ inputs đã lưu (≤ as_of). None khi
    chưa đủ lịch sử (<_MIN_SESSIONS phiên có close)."""
    rows = sorted((date.fromisoformat(k), v) for k, v in inputs.items()
                  if v.get("close") is not None)
    if as_of is not None:
        rows = [(d, v) for d, v in rows if d <= as_of]
    if len(rows) < _MIN_SESSIONS:
        return None
    dates = [d for d, _ in rows]
    closes = [float(v["close"]) for _, v in rows]
    last = rows[-1][1]

    short, st = [], hz.CHUA_RO
    for _, v in rows:
        if v.get("score") is not None and v.get("n"):
            st = hz.short_step(st, int(v["score"]), int(v["n"]))
        short.append(st)
    weeks = hz.medium_series(dates, closes, params)
    medium = hz.medium_daily(dates, weeks)
    open_wk = hz.medium_series(dates, closes, params, include_open_week=True)
    alerts = hz.alert_series(closes)
    tiers = [a.tier for a in alerts]
    k = len(dates) - 1
    a = alerts[k]
    alert_since = None
    if a.tier:
        j = k
        while j > 0 and tiers[j - 1] > 0:
            j -= 1
        alert_since = dates[j].isoformat()
    w = weeks[-1] if weeks else None
    levels = hz.trigger_levels([x.close for x in weeks], w.state, closes[-1],
                               max(closes[-252:]), params) if w else []
    rule = hz.stance_rule(short[k], medium[k], a.tier)
    week_closed = bool(weeks) and weeks[-1].week_end == dates[-1]
    prov = open_wk[-1].state if open_wk and not week_closed else None
    return {
        "as_of": dates[-1].isoformat(),
        "short": short[k], "short_since": _since(dates, short, k).isoformat(),
        "score": last.get("score"), "n": last.get("n"),
        "medium": medium[k], "medium_since": _since(dates, medium, k).isoformat(),
        "pending": w.pending if w else 0, "week_closed": week_closed,
        "medium_provisional": prov,
        "levels": [{"kind": lv.kind, "price": round(lv.price, 2), "reachable": lv.reachable}
                   for lv in levels],
        "alert": {"tier": a.tier, "anchor": round(a.anchor, 2) if a.anchor else None,
                  "since": alert_since},
        "protect": hz.protection_level(last.get("floor_old"), short[k], medium[k], a.tier),
        "stance": {"forced": rule.forced, "allowed": list(rule.allowed)},
        "label_old": last.get("label_old"), "floor_old": last.get("floor_old"),
        # MA tuần cho brief (P1b-3) — ngoài _COMPARE_KEYS nên F1 không đổi
        "ma_w": ({"short": round(w.ma_short, 2) if w.ma_short else None,
                  "long": round(w.ma_long, 2) if w.ma_long else None} if w else None),
    }


_COMPARE_KEYS = ("short", "medium", "pending", "protect")


def same_state(a: dict, b: dict) -> bool:
    return (all(a.get(k) == b.get(k) for k in _COMPARE_KEYS)
            and (a.get("alert") or {}).get("tier") == (b.get("alert") or {}).get("tier")
            and (a.get("stance") or {}).get("forced") == (b.get("stance") or {}).get("forced"))


# ── Lưu ──────────────────────────────────────────────────────────────────

def state_path(warehouse: Path = _WAREHOUSE) -> Path:
    return warehouse / "_meta" / STATE_NAME


def load_state(warehouse: Path = _WAREHOUSE) -> dict:
    try:
        st = json.loads(state_path(warehouse).read_text(encoding="utf-8"))
        if isinstance(st, dict):
            st.setdefault("inputs", {}); st.setdefault("published", [])
            return st
    except (OSError, ValueError):
        pass
    return {"version": SCHEMA_VERSION, "inputs": {}, "published": []}


NO_STATE = "chưa có state"
EMPTY_STATE = "state rỗng"
BROKEN_STATE = "state hỏng (không đọc được JSON)"


class Latest(NamedTuple):
    """Bản published mới nhất + đủ dữ kiện để quyết "dùng được không"."""
    state: dict
    snap: "dict | None"           # bản published cuối; None khi NO/EMPTY/BROKEN_STATE
    missing: "str | None"         # NO_STATE | EMPTY_STATE | BROKEN_STATE | None
    expect: "date | None"         # bar VNINDEX mới nhất ≤ phiên phủ (`session_covered_at`)
    conflicted: tuple = ()        # tên file '(conflicted copy)' của state trong _meta

    @property
    def stale(self) -> bool:
        return bool(self.snap and self.expect
                    and str(self.snap.get("as_of")) < self.expect.isoformat())

    @property
    def usable(self) -> bool:
        return self.snap is not None and not self.stale and not self.conflicted

    @property
    def reason(self) -> "str | None":
        """Vì sao KHÔNG dùng được (None khi `usable`) — cùng câu chữ badge doctor."""
        if self.missing:
            return self.missing
        if self.conflicted:
            return f"conflicted copy: {', '.join(self.conflicted[:2])}"
        if self.stale:
            return f"cũ: bản cuối {self.snap.get('as_of')}, kho đã có bar {self.expect}"
        return None


def _state_file_ok(warehouse: Path) -> bool:
    try:
        return isinstance(json.loads(state_path(warehouse).read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def latest_published(warehouse: Path = _WAREHOUSE, now: datetime | None = None) -> Latest:
    """MỘT chỗ đọc state 3 khung cho mọi consumer (doctor; kẹp allocation, brief
    từ P1b): bản cuối + cũ so với kho + conflicted copy. CHỈ ĐỌC. Có thể ném khi
    đọc kho VNINDEX lỗi — caller bọc try (doctor, allocation đều đã bọc)."""
    if not state_path(warehouse).exists():
        return Latest(state=load_state(warehouse), snap=None, missing=NO_STATE, expect=None)
    if not _state_file_ok(warehouse):
        return Latest(state=load_state(warehouse), snap=None, missing=BROKEN_STATE, expect=None)
    st = load_state(warehouse)
    pub = st.get("published") or []
    if not pub:
        return Latest(state=st, snap=None, missing=EMPTY_STATE, expect=None)
    from vnstock_rollup import session_covered_at
    conflicted = tuple(sorted(f.name for f in (warehouse / "_meta").glob("horizon_state*conflicted*")))
    dates, _ = load_vnindex(warehouse)
    covered = session_covered_at(now or datetime.now())
    expect = max((d for d in dates if d <= covered), default=None)
    return Latest(state=st, snap=pub[-1], missing=None, expect=expect, conflicted=conflicted)


_BREADTH_4W_SESSIONS = 20          # "4 tuần trước" của % mã trên MA200 trong 🔭


def brief_view(lp: Latest) -> dict:
    """`ctx["horizons"]` cho brief (P1b-3, #21) — từ state ĐÃ LƯU, không đọc
    parquet: bản cuối + bản trước (dòng 🔁), số phiên của trạng thái ngắn hạn,
    số tuần của trung hạn, % mã trên MA200 hôm nay và 20 phiên trước, các mức
    "đã biết" cho guard giá. State không dùng được ⇒ `{"stale": True, …}`."""
    if not lp.usable:
        return {"stale": True, "as_of": (lp.snap or {}).get("as_of"), "reason": lp.reason}
    snap, inputs = lp.snap, lp.state.get("inputs") or {}
    days = sorted(k for k in inputs if k <= snap["as_of"])
    pub = lp.state.get("published") or []
    k = next((i for i in range(len(pub) - 1, -1, -1)
              if pub[i].get("as_of") == snap.get("as_of")), None)
    prev = pub[k - 1] if k else None             # bản published NGAY TRƯỚC snap (dòng 🔁)
    breadth = [inputs[k].get("breadth_pct") for k in days]
    alert = snap.get("alert") or {}
    known = [lv["price"] for lv in snap.get("levels") or [] if lv.get("price")]
    if alert.get("anchor"):
        known += [alert["anchor"], round(alert["anchor"] * hz.AlertParams().tier2_frac, 2)]
    known += [v for v in (snap.get("ma_w") or {}).values() if v]
    short_since = snap.get("short_since") or snap["as_of"]
    medium_since = date.fromisoformat(snap.get("medium_since") or snap["as_of"])
    end = date.fromisoformat(snap["as_of"])
    # "tuần N" = số tuần ĐÃ CHỐT mang trạng thái này (tuần chốt đổi = tuần 1; tuần
    # đang mở chưa tính) — đếm theo tuần LỊCH, không cần kho inputs phủ tới ngày
    # đổi. since rơi đầu tuần (thứ Sáu nghỉ ⇒ hiệu lực phiên đầu tuần sau) thì
    # tuần chốt đổi là tuần TRƯỚC since.
    weeks = (len({date.fromordinal(o).isocalendar()[:2]
                  for o in range(medium_since.toordinal(), end.toordinal() + 1)})
             - (0 if snap.get("week_closed") else 1) + (0 if medium_since.weekday() == 4 else 1))
    return {
        "stale": False, "snap": snap, "prev": prev,
        "short_sessions": max(1, sum(1 for k in days if k >= short_since)),
        "medium_weeks": max(1, weeks),
        "breadth_pct": breadth[-1] if breadth else None,
        "breadth_pct_4w": (breadth[-1 - _BREADTH_4W_SESSIONS]
                           if len(breadth) > _BREADTH_4W_SESSIONS else None),
        "known_levels": known,
    }


def write_state(st: dict, warehouse: Path = _WAREHOUSE) -> None:
    """Ghi nguyên tử (tmp + os.replace) như `vnstock_allocation._write_state`."""
    p = state_path(warehouse)
    p.parent.mkdir(parents=True, exist_ok=True)
    st["version"] = SCHEMA_VERSION
    st["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=0, sort_keys=True,
                              default=str), encoding="utf-8")
    os.replace(tmp, p)


def _published_dates(st: dict) -> set[str]:
    return {p.get("as_of") for p in st.get("published", [])}


def _ensure_closes(st: dict, dates: list[date], closes: list[float]) -> int:
    """Nền lịch sử cho trung hạn/🚨: thêm close cho phiên CHƯA có, không bao
    giờ ghi đè (sửa bar quá khứ hiện ở badge "revision", không đổi state)."""
    inp, n = st["inputs"], 0
    for d, c in zip(dates, closes):
        if d.isoformat() not in inp:
            inp[d.isoformat()] = {"close": round(float(c), 2), "source": "history"}
            n += 1
    return n


def _publish(st: dict, snap: dict, source: str) -> None:
    st["published"] = [p for p in st["published"] if p.get("as_of") != snap["as_of"]]
    st["published"].append({**snap, "source": source, "machine": machine(),
                            "computed_at": datetime.now().isoformat(timespec="seconds"),
                            "params": {"ma": [PARAMS.ma_short, PARAMS.ma_long],
                                       "band": PARAMS.band, "fuse": PARAMS.fuse}})
    st["published"].sort(key=lambda p: p.get("as_of", ""))


# ── Lệnh ─────────────────────────────────────────────────────────────────

def update(now: datetime | None = None, force: bool = False,
           warehouse: Path = _WAREHOUSE) -> int:
    """Bước pipeline: ghi inputs + published cho phiên phủ. 0 ok/no-op, 1 cảnh báo."""
    from vnstock_rollup import session_covered_at
    now = now or datetime.now()
    covered = session_covered_at(now)
    dates, closes = load_vnindex(warehouse)
    if len(dates) < _MIN_SESSIONS:
        print(f"[horizons] ⚠️ VNINDEX trong kho chỉ {len(dates)} phiên — chưa đủ lịch sử")
        return 1
    keep = [i for i, d in enumerate(dates) if d <= covered]
    dates, closes = [dates[i] for i in keep], [closes[i] for i in keep]
    as_of = dates[-1]
    st = load_state(warehouse)
    key = as_of.isoformat()
    if as_of < covered:
        print(f"[horizons] phiên phủ {covered} chưa có bar VNINDEX (nghỉ lễ hoặc sync hụt) "
              f"— bar mới nhất {as_of}")
    prev = next((p for p in st["published"] if p.get("as_of") == key), None)
    if not force and prev and prev.get("source") == "live":
        print(f"[horizons] ✓ {key} đã có (máy {prev.get('machine', '?')}) — bỏ qua (--force để ghi lại)")
        return 0
    _ensure_closes(st, dates, closes)
    breadth, src = live_breadth(warehouse, as_of)
    sc = score_inputs(dates, closes, [as_of], {as_of: breadth}, load_nn(warehouse)).get(as_of)
    if sc is None:
        print(f"[horizons] ⚠️ không chấm được điểm {key} (thiếu MA200?)")
        return 1
    st["inputs"][key] = {"close": round(closes[-1], 2), **sc, "breadth_src": src,
                         "source": "live", "machine": machine(),
                         "recorded_at": datetime.now().isoformat(timespec="seconds")}
    snap = fold(st["inputs"], as_of)
    if snap is None:
        print("[horizons] ⚠️ chưa đủ lịch sử để gấp trạng thái")
        return 1
    _publish(st, snap, "live")
    write_state(st, warehouse)
    print("[horizons] " + headline(snap))
    return 0


def backfill(days: int = 120, warehouse: Path = _WAREHOUSE) -> int:
    """Một lần sau khi merge (○): close toàn lịch sử + điểm `days` phiên gần nhất
    (breadth tái dựng từ parquet) + published cho các phiên CHƯA có. Không bao
    giờ đè bản live."""
    dates, closes = load_vnindex(warehouse)
    if len(dates) < _MIN_SESSIONS:
        print(f"[horizons] ❌ VNINDEX trong kho chỉ {len(dates)} phiên"); return 2
    st = load_state(warehouse)
    _ensure_closes(st, dates, closes)
    targets = [d for d in dates[-days:]
               if st["inputs"].get(d.isoformat(), {}).get("source") != "live"]
    print(f"[horizons] backfill {len(targets)} phiên ({targets[0] if targets else '-'} → "
          f"{targets[-1] if targets else '-'}): tái dựng breadth từ parquet…")
    breadth = breadth_history(warehouse, targets)
    scores = score_inputs(dates, closes, targets, breadth, load_nn(warehouse))
    for d, sc in scores.items():
        st["inputs"][d.isoformat()] = {"close": round(closes[dates.index(d)], 2), **sc,
                                       "breadth_src": "parquet", "source": "backfill"}
    done = _published_dates(st)
    n_pub = 0
    for d in dates[-days:]:
        if d.isoformat() in done:
            continue
        snap = fold(st["inputs"], d)
        if snap:
            _publish(st, snap, "backfill"); n_pub += 1
    write_state(st, warehouse)
    print(f"[horizons] ✓ {len(scores)} phiên có điểm, {n_pub} bản published mới")
    snap = fold(st["inputs"])
    if snap:
        print("[horizons] " + headline(snap))
    return 0


def verify(st: dict, warehouse: Path | None = _WAREHOUSE, last: int = 60) -> dict:
    """F1: gấp lại từ inputs đã lưu == published (bản live) · revision: close lưu
    vs parquet lệch >0.1% (`warehouse=None` bỏ phần parquet)."""
    live = [p for p in st.get("published", []) if p.get("source") == "live"][-last:]
    bad = [p["as_of"] for p in live
           if not same_state(fold(st["inputs"], date.fromisoformat(p["as_of"])) or {}, p)]
    rev: list[str] = []
    if warehouse is not None:
        dates, closes = load_vnindex(warehouse)
        pq = dict(zip((d.isoformat() for d in dates), closes))
        keys = sorted(k for k, v in st["inputs"].items() if v.get("close") is not None)[-last:]
        for k in keys:
            c0 = float(st["inputs"][k]["close"])
            c1 = pq.get(k)
            if c1 and abs(c1 / c0 - 1) > _REVISION_TOL:
                rev.append(k)
    return {"live": len(live), "fold_mismatch": bad, "revisions": rev}


_LEVEL_TXT = {"to_giam": "xuống GIẢM nếu đóng tuần <", "to_tang": "đọc TĂNG (cần 2 tuần) nếu >",
              "leave_tang": "rời TĂNG nếu đóng tuần <", "leave_giam": "rời GIẢM (cần 2 tuần) nếu >"}


def headline(s: dict) -> str:
    alert = s.get("alert") or {}
    pend = f" ⏳ {s['pending']}/{PARAMS.up_weeks}" if s.get("pending") else ""
    return (f"{s['as_of']}: Trung hạn {hz.MEDIUM_LABEL[s['medium']]} (từ {s['medium_since']}){pend}"
            f" · Ngắn hạn {hz.SHORT_LABEL[s['short']]} (điểm {s.get('score')}/{s.get('n')})"
            f" · 🚨 {'mức ' + str(alert.get('tier')) if alert.get('tier') else 'tắt'}"
            f" · bảo vệ {s.get('protect') or '-'}"
            f" · Stance {s['stance']['forced'] or 'agent chọn ' + '/'.join(s['stance']['allowed'])}")


def show(warehouse: Path = _WAREHOUSE, n: int = 10) -> int:
    st = load_state(warehouse)
    pub = st.get("published", [])
    if not pub:
        print("[horizons] chưa có state — chạy: python run.py horizons --backfill"); return 1
    s = pub[-1]
    print(headline(s) + f"  [{s.get('source')} · {s.get('machine')}]")
    for lv in s.get("levels", []):
        txt = f"{lv['price']:,.0f}" if lv["reachable"] else f"~{lv['price']:,.0f} (chưa thể trong tuần này)"
        print(f"  mức: {_LEVEL_TXT.get(lv['kind'], lv['kind'])} {txt}")
    if s.get("medium_provisional") is not None and s["medium_provisional"] != s["medium"]:
        print(f"  đọc tạm: nếu thứ Sáu đóng ở giá hôm nay ⇒ {hz.MEDIUM_LABEL[s['medium_provisional']]}")
    print(f"\n  {n} phiên gần nhất — CŨ (nhãn header / floor) vs MỚI (chạy bóng):")
    for p in pub[-n:]:
        al = (p.get("alert") or {}).get("tier") or 0
        print(f"  {p['as_of']} {str(p.get('label_old') or '-'):22s} {str(p.get('floor_old') or '-'):5s} | "
              f"{hz.MEDIUM_LABEL[p['medium']]:9s} {hz.SHORT_LABEL[p['short']]:11s} 🚨{al} "
              f"{str(p.get('protect') or '-'):4s} Stance {p['stance']['forced'] or '-':5s} "
              f"[{p.get('source')}]")
    return 0


def replay_check(warehouse: Path = _WAREHOUSE) -> int:
    st = load_state(warehouse)
    v = verify(st, warehouse)
    print(f"[horizons] F1 fold == published: {v['live'] - len(v['fold_mismatch'])}/{v['live']} bản live"
          + (f" — lệch: {', '.join(v['fold_mismatch'][:5])}" if v["fold_mismatch"] else ""))
    print(f"[horizons] revision (close lưu vs parquet >0.1%): "
          + (", ".join(v["revisions"][:5]) if v["revisions"] else "không có"))
    # F2: backfill lại các phiên live (không ghi) rồi so trạng thái ngắn hạn
    live_keys = [k for k, x in st["inputs"].items() if x.get("source") == "live"]
    if live_keys:
        dates, closes = load_vnindex(warehouse)
        targets = [date.fromisoformat(k) for k in sorted(live_keys)]
        sc = score_inputs(dates, closes, targets, breadth_history(warehouse, targets),
                          load_nn(warehouse))
        same = sum(1 for d in targets if sc.get(d, {}).get("score") == st["inputs"][d.isoformat()].get("score"))
        print(f"[horizons] F2 điểm backfill == điểm live: {same}/{len(targets)} phiên")
    return 1 if v["fold_mismatch"] else 0


def legend_text() -> str:
    """1 tin Telegram giải thích từ vựng brief 3 khung (P1b-7, #25) — ngưỡng đọc
    từ chính tham số lõi để lời giải thích không lệch code."""
    m, a = PARAMS, hz.AlertParams()
    return "\n".join([
        "🔭 <b>Brief 3 khung — đọc thế nào</b>",
        "",
        "<b>Ngắn hạn (vài phiên)</b>: nhịp hồi / chưa rõ / nhịp chỉnh, từ điểm kỹ thuật "
        "ngày (7 phiếu: giá–MA, RSI, độ rộng, khối ngoại…). Quyết Stance ngày mai; "
        "KHÔNG đổi xu hướng.",
        f"<b>Trung hạn (xu hướng tuần)</b>: TĂNG / ĐI NGANG / GIẢM, chỉ đọc giá ĐÓNG "
        f"CỬA TUẦN so MA{m.ma_long} tuần (±{m.band:.0%}) và MA{m.ma_short}/MA{m.ma_long} "
        f"tuần. Xuống cần 1 tuần, lên cần {m.up_weeks} tuần liền, mỗi tuần tối đa 1 bậc. "
        "Đây là tiêu đề của brief.",
        "<b>Dài hạn (6–12 tháng)</b>: đang thu thập dữ liệu — chưa chấm.",
        f"🚨 <b>Rủi ro ngắn hạn</b>: bật khi đóng cửa thấp hơn đỉnh {a.window} phiên "
        f"≥{a.drawdown:.0%}, hoặc 1 phiên ≤ {a.day_drop}%, hoặc 3 phiên ≤ {a.three_day_drop}%. "
        f"Mức 2 khi đóng < {a.tier2_frac:.0%} đỉnh neo. KHÔNG BAO GIỜ đổi xu hướng; tắt "
        f"khi lấy lại ≥{a.off_frac:.0%} đỉnh neo hoặc {a.off_above_ma} phiên liền trên "
        f"MA{a.window} (sau tối thiểu {a.dwell} phiên).",
        "🛡 <b>Lớp bảo vệ</b>: bật khi có nhịp chỉnh / trung hạn GIẢM / 🚨 / tín hiệu "
        "ngày một chiều giảm. Mức cứng (tín hiệu ngày giảm hoặc ≥2 tín hiệu): watchlist "
        "chỉ \"canh MUA NẾU vượt\", không GIA TĂNG vô điều kiện, hạ trước mã dưới MA50. "
        "Mức mềm (1 tín hiệu): chỉ nhắc không mua đuổi.",
        "💼 <b>Tỷ trọng cổ phiếu</b>: theo band phân bổ; KHÔNG tăng khi trung hạn chưa "
        "TĂNG hoặc 🚨 bật. Được tăng thì ⏳ báo trước 1 tuần, mỗi tuần tối đa 1 bậc. "
        "Giảm luôn đi qua.",
        "🎯 <b>Stance ngày mai</b>: nhịp chỉnh ⇒ GIẢM; nhịp hồi + trung hạn TĂNG + 🚨 tắt "
        "⇒ TĂNG; còn lại chỉ TRUNG TÍNH/GIẢM (TĂNG chỉ khi trung hạn TĂNG và 🚨 tắt). "
        "GIẢM luôn được phép.",
        "",
        "<i>Mức \"~1,803\" là mức làm tròn, tính lại mỗi tuần.</i>",
    ])


def legend(dry_run: bool = False) -> int:
    """`run.py horizons --legend`: gửi ĐÚNG 1 tin giải thích từ vựng. Không ghi kho,
    không đụng marker. ``dry_run`` chỉ in."""
    text = legend_text()
    if dry_run:
        print(text)
        return 0
    import vnstock_telegram as tg
    tg.send_message(text)
    print("[horizons] đã gửi 1 tin giải thích từ vựng 3 khung")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Brief 3 khung — trạng thái chạy bóng (P1a)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true", help="bước pipeline: ghi phiên phủ")
    g.add_argument("--backfill", action="store_true", help="một lần: dựng lịch sử từ kho")
    g.add_argument("--show", action="store_true", help="in trạng thái + 10 phiên gần nhất")
    g.add_argument("--replay", action="store_true", help="kiểm F1/F2/revision")
    g.add_argument("--legend", action="store_true",
                   help="gửi 1 tin Telegram giải thích từ vựng 3 khung (không ghi kho)")
    ap.add_argument("--force", action="store_true", help="--update: ghi đè phiên đã có")
    ap.add_argument("--days", type=int, default=120, help="--backfill: số phiên chấm điểm")
    ap.add_argument("--dry-run", action="store_true", help="--legend: chỉ in, không gửi")
    a = ap.parse_args(argv)
    try:                                   # kill-switch sống trong .env (như doctor)
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass
    if a.update:
        if os.environ.get("VNSTOCK_HORIZONS_STEP", "1") == "0":
            print("[horizons] tắt (VNSTOCK_HORIZONS_STEP=0)"); return 0
        return update(force=a.force)
    if a.backfill:
        return backfill(a.days)
    if a.replay:
        return replay_check()
    if a.legend:
        return legend(dry_run=a.dry_run)
    return show()


if __name__ == "__main__":
    sys.exit(main())
