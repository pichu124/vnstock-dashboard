"""Đo các cách tìm hỗ trợ/kháng cự trên KHO THẬT — CHỈ ĐỌC (PTKT P2b).

`docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §15: S/R pivot 60 phiên KHÔNG hơn mức giả cùng khoảng cách
⇒ trước khi đổi đường brief, đo mỗi phương pháp của `vnstock_sr_methods` bằng ĐÚNG thước P0
(`vnstock_ta_score`):

  • "chạm thì giữ" S1 / R1 trong 5 phiên (xuyên = đóng cửa vượt 0,5%) — `score_levels`;
  • "thủng S1 ⇒ chạm S2" / "vượt R1 ⇒ chạm R2" — `score_trigger`.

Mốc so CHÍNH = mức giả KHỚP BIẾN ĐỘNG ở ngày ngẫu nhiên của CHÍNH chuỗi đó: cùng số bội ATR(14)
(`vol_matched_level_outcomes` / `vol_matched_trigger_outcomes`). Mốc P0 cùng % (`ts.fake_level_
outcomes` / `fake_trigger_outcomes`) in kèm để so — nó thiên vị phương pháp có khoảng cách bám
ATR (vết review 04/11, xem `caveats`). Cột '−atr_band' = CHÊNH trừ CHÊNH của mốc ngây thơ atr_band.

Mẫu: mỗi mã lấy một ngày t mỗi `--step` phiên, toàn lịch sử có ≥ 200 bar tính tới t, chỉ khi GTGD
TB20 tại t ≥ `--min-gtgd` tỷ (cách tính `compare_indicator_formulas.session_gtgd20`); VN-Index
chấm riêng (pivot60 kèm đỉnh/đáy 20 phiên + 52 tuần như `_vnindex_technicals`). Mức tại t chỉ
dùng bar ≤ t (`vnstock_sr_methods.levels_at`). Tách nửa đầu / nửa sau lịch phiên để thấy độ bền.

Không ghi gì vào kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop đang chạy
(18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi.

    python scripts/eval_sr_methods.py --json sr_methods.json      # bước 10 phiên (~8 phút/1.700 mã)
    python scripts/eval_sr_methods.py --step 5 --min-gtgd 5       # mẫu dày gấp đôi, lâu gấp đôi
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from collections import Counter
from functools import partial
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import vnstock_sr_methods as srm  # noqa: E402
import vnstock_ta_score as ts  # noqa: E402
from scripts.compare_indicator_formulas import session_gtgd20  # noqa: E402
from vnstock_indicators import atr  # noqa: E402
from vnstock_ta_score_io import normalize_bars  # noqa: E402

MIN_HISTORY = 200
# Brief xin mỗi 5 phiên; đo kho giả 1.700 mã × 600 phiên: bước 5 ≈ 15 phút ⇒ mặc định 10 (≈ một
# nửa). Bước ≥ 10 còn khiến hai ngày liền của CÙNG mã không chung bar tương lai của trigger.
DEFAULT_STEP = 10
TRIGGER_SPAN = 2 * ts.HORIZON       # tới 5 phiên chờ kích hoạt + 5 phiên chạm mức 2
SIDES = ("support", "resistance")
PERIODS = ("all", "first_half", "second_half")
_PERIOD_LABEL = {"all": "toàn kỳ", "first_half": "nửa đầu", "second_half": "nửa sau"}
_SIDE_LABEL = {"support": "Hỗ trợ S1 — chạm thì giữ", "resistance": "Kháng cự R1 — chạm thì giữ"}
_TRIG_LABEL = {"support": "Thủng S1 ⇒ chạm S2", "resistance": "Vượt R1 ⇒ chạm R2"}


# ── Lõi (thuần trên DataFrame) ───────────────────────────────────────────────

def sample_positions(n_bars: int, step: int = DEFAULT_STEP, min_history: int = MIN_HISTORY,
                     horizon: int = ts.HORIZON) -> range:
    """Vị trí t có ≥ `min_history` bar tính tới t và đủ `horizon` phiên phía sau."""
    return range(min_history - 1, n_bars - horizon, max(1, step))


def atr_pct(bars: pd.DataFrame) -> np.ndarray:
    """ATR(14) Wilder / đóng cửa × 100 cho từng bar; NaN khi chưa đủ bar."""
    a = atr(bars["high"], bars["low"], bars["close"], srm.ATR_N).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return a / bars["close"].to_numpy(dtype=float) * 100


def _vol_picks(n_bars: int, ap: np.ndarray, k: int, seed: int, horizon: int,
               exclude) -> np.ndarray:
    """Ngày bốc mức giả: đủ `horizon` phiên sau, có ATR%, không thuộc `exclude`."""
    n_ok = n_bars - horizon
    if n_ok <= 0:
        return np.array([], dtype=int)
    ok = np.isfinite(ap[:n_ok]) & (ap[:n_ok] > 0)
    ok[[e for e in exclude if 0 <= e < n_ok]] = False
    pool = np.flatnonzero(ok)
    if not len(pool):
        return pool
    return np.sort(np.random.default_rng(seed).choice(pool, size=min(k, len(pool)),
                                                       replace=False))


def _cols(bars, *names) -> list[np.ndarray]:
    """Cột giá dạng float — `bars` là DataFrame hoặc dict cột numpy (vòng đo truyền dict để
    khỏi rút cột DataFrame mỗi lần gọi)."""
    return [np.asarray(bars[c], dtype=float) for c in names]


def vol_matched_level_outcomes(bars, atr_mult: float, side: str,
                               ap: np.ndarray, k: int = ts.FAKE_PER_LEVEL,
                               seed: int = ts.SEED, horizon: int = ts.HORIZON,
                               pierce_pct: float = ts.PIERCE_PCT,
                               exclude=()) -> list[str | None]:
    """Mốc T1/T5 KHỚP BIẾN ĐỘNG: như `ts.fake_level_outcomes` nhưng ở ngày ngẫu nhiên i mức
    giả cách giá `atr_mult` × ATR%(i) — cùng số bội ATR với mức thật (atr_mult = dist_t /
    ATR%_t), không phải cùng %. `ap` = `atr_pct(bars)`. Cùng `seed` + ATR% đủ mọi ngày ⇒
    bốc đúng các ngày của `ts.fake_level_outcomes`.

    Vì sao (vết review 04/11): cùng % đặt sang ngày biến động khác thì mức có khoảng cách bám
    ATR(t) (atr_band, volume_node, touch_cluster) được CHÊNH dương dù chuỗi không có S/R."""
    lo, hi, cl = _cols(bars, "low", "high", "close")
    picks = _vol_picks(len(cl), ap, k, seed, horizon, exclude)
    if not len(picks) or not atr_mult > 0:
        return []
    w = picks[:, None] + 1 + np.arange(horizon)
    sign = -1 if side == "support" else 1
    lvl = cl[picks] * (1 + sign * atr_mult * ap[picks] / 100)
    kk = pierce_pct / 100
    if side == "support":
        touched = (lo[w] <= lvl[:, None]).any(axis=1)
        pierced = (cl[w] < (lvl * (1 - kk))[:, None]).any(axis=1)
    else:
        touched = (hi[w] >= lvl[:, None]).any(axis=1)
        pierced = (cl[w] > (lvl * (1 + kk))[:, None]).any(axis=1)
    return [None if v <= 0 else ts.PIERCED if p else ts.HELD if t else ts.UNTOUCHED
            for v, p, t in zip(lvl, pierced, touched)]


def vol_matched_trigger_outcomes(bars, atr_mult: float, side: str,
                                 ap: np.ndarray, k: int = ts.FAKE_PER_LEVEL,
                                 seed: int = ts.SEED, horizon: int = ts.HORIZON,
                                 exclude=()) -> list[bool]:
    """Mốc T2 KHỚP BIẾN ĐỘNG: như `ts.fake_trigger_outcomes` nhưng đích ở ngày i cách đóng
    cửa `atr_mult` × ATR%(i) (atr_mult = gap_pct / ATR% của phiên trigger; âm = phiên trigger
    đã qua mức 2 ⇒ luôn chạm, như bản cùng %)."""
    hi, lo, cl = _cols(bars, "high", "low", "close")
    picks = _vol_picks(len(cl), ap, k, seed, horizon, exclude)
    if not len(picks) or not np.isfinite(atr_mult):
        return []
    w = picks[:, None] + 1 + np.arange(horizon)
    c0 = cl[picks]
    if side == "resistance":
        tgt = c0 * (1 + atr_mult * ap[picks] / 100)
        hit = (c0 >= tgt) | (hi[w] >= tgt[:, None]).any(axis=1)
    else:
        tgt = c0 * (1 - atr_mult * ap[picks] / 100)
        hit = (c0 <= tgt) | (lo[w] <= tgt[:, None]).any(axis=1)
    return [bool(x) for x in hit]


def _cell() -> dict:
    out: dict = {"n": 0}
    for s in SIDES:
        out[s] = {"has": 0, "real": Counter(), "fake": Counter(), "fake_vol": Counter()}
        out[f"trigger_{s}"] = {"k": 0, "n": 0, "fk": 0, "fn": 0, "vk": 0, "vn": 0}
    return out


def new_acc(methods) -> dict:
    return {p: {m: _cell() for m in methods} for p in PERIODS}


def eval_series(bars: pd.DataFrame, positions, methods: dict, acc: dict, mid: pd.Timestamp,
                seed: int = ts.SEED, fake_k: int = ts.FAKE_PER_LEVEL) -> int:
    """Chấm mọi phương pháp trên MỘT chuỗi (bar đã `normalize_bars`) tại các vị trí
    `positions`, cộng vào `acc`. Mức giả dùng cùng seed cho mọi phương pháp ở cùng ngày t
    (so cặp). Trả số ngày đã chấm."""
    times = pd.DatetimeIndex(bars["time"])
    close = bars["close"].to_numpy(dtype=float)
    atr_all = atr(bars["high"], bars["low"], bars["close"], srm.ATR_N).to_numpy()
    ap = atr_pct(bars)
    cols = dict(zip(("high", "low", "close"), _cols(bars, "high", "low", "close")))
    trig_rows: dict = {(m, s): [] for m in methods for s in SIDES}
    done = 0
    for t in positions:
        per = ("all", "first_half" if times[t] < mid else "second_half")
        fwd = bars.iloc[t + 1:t + 1 + ts.HORIZON]
        nxt = close[t + 1:t + 1 + ts.HORIZON]
        win = srm.window_at(bars, t)
        a_t = None if np.isnan(atr_all[t]) else float(atr_all[t])
        done += 1
        for name, fn in methods.items():
            lv = fn(win, close[t], atr_t=a_t)
            for p in per:
                acc[p][name]["n"] += 1
            for side in SIDES:
                lst = lv[side]
                if not lst:
                    continue
                o = ts.score_levels(fwd, lst[0], side)
                dist = ts.level_distance_pct(lst[0], close[t], side)
                fk = fv = []
                if o is not None and dist:
                    fk = [x for x in ts.fake_level_outcomes(bars, dist, side, k=fake_k,
                                                            seed=seed + t, exclude=[t]) if x]
                    fv = [x for x in vol_matched_level_outcomes(
                        cols, dist / ap[t], side, ap, k=fake_k, seed=seed + t, exclude=[t]) if x]
                for p in per:
                    c = acc[p][name][side]
                    c["has"] += 1
                    if o is not None and dist:
                        c["real"][o] += 1
                        c["fake"].update(fk)
                        c["fake_vol"].update(fv)
                # Điều kiện kích hoạt y như `score_trigger` — lọc trước để khỏi gọi khi không có
                # phiên nào đóng cửa qua mức 1 (đa số ngày; hàm đó tốn ~0,4 ms mỗi lần gọi).
                fired = (nxt < lst[0]).any() if side == "support" else (nxt > lst[0]).any()
                if len(lst) >= 2 and fired:
                    r = ts.score_trigger(bars, t, lst[0], lst[1], side)
                    if r["triggered"] and r["hit"] is not None:
                        trig_rows[(name, side)].append((per, r))
    # seed mức giả trigger theo TÊN phương pháp — thêm/bớt phương pháp không đổi mốc của cái khác
    tseed = {key: zlib.crc32("/".join(key).encode()) % 1_000_000 * 1_000 for key in trig_rows}
    for (name, side), rows in trig_rows.items():
        days = {r["trigger_pos"] for _, r in rows}
        for k, (per, r) in enumerate(rows):
            sd = seed + tseed[(name, side)] + k
            fk = ts.fake_trigger_outcomes(bars, r["gap_pct"], side, k=fake_k, seed=sd,
                                          exclude=days)
            fv = vol_matched_trigger_outcomes(cols, r["gap_pct"] / ap[r["trigger_pos"]], side,
                                              ap, k=fake_k, seed=sd, exclude=days)
            for p in per:
                c = acc[p][name][f"trigger_{side}"]
                c["k"] += int(r["hit"])
                c["n"] += 1
                c["fk"] += sum(fk)
                c["fn"] += len(fk)
                c["vk"] += sum(fv)
                c["vn"] += len(fv)
    return done


def _diff_pp(a: dict, b: dict) -> float | None:
    if a.get("rate") is None or b.get("rate") is None:
        return None
    return round((a["rate"] - b["rate"]) * 100, 1)


CONTROL = "atr_band"     # mốc ngây thơ thuần ATR — chuẩn đối chứng cho mọi phương pháp
_MEASURES = SIDES + tuple(f"trigger_{s}" for s in SIDES)


def summarize(acc: dict) -> dict:
    """{kỳ: {phương pháp: {mau, support/resistance: {phu, that, gia, chenh_dpct, gia_cung_pct,
    chenh_cung_pct, tru_atr_band}, trigger_*: {that, gia, chenh_dpct, …}}}}.

    `gia`/`chenh_dpct` = mốc KHỚP BIẾN ĐỘNG (cùng số bội ATR) — số chính; `gia_cung_pct`/
    `chenh_cung_pct` = mốc cũ cùng % (để so); `tru_atr_band` = CHÊNH chính của phương pháp trừ
    CHÊNH chính của `atr_band` (None khi không chấm atr_band). Tỉ lệ theo `ts.rate`."""
    out: dict = {}
    for p, methods in acc.items():
        out[p] = {}
        for m, c in methods.items():
            row: dict = {"mau": c["n"]}
            for s in SIDES:
                real = ts.level_summary(c[s]["real"].elements())
                vol = ts.level_summary(c[s]["fake_vol"].elements())
                same = ts.level_summary(c[s]["fake"].elements())
                hold = real["hold_if_touched"]
                row[s] = {"phu": round(c[s]["has"] / c["n"], 4) if c["n"] else None,
                          "that": real, "gia": vol,
                          "chenh_dpct": _diff_pp(hold, vol["hold_if_touched"]),
                          "gia_cung_pct": same,
                          "chenh_cung_pct": _diff_pp(hold, same["hold_if_touched"])}
                tc = c[f"trigger_{s}"]
                that = ts.rate(tc["k"], tc["n"])
                vol_t, same_t = ts.rate(tc["vk"], tc["vn"]), ts.rate(tc["fk"], tc["fn"])
                row[f"trigger_{s}"] = {"that": that, "gia": vol_t,
                                       "chenh_dpct": _diff_pp(that, vol_t),
                                       "gia_cung_pct": same_t,
                                       "chenh_cung_pct": _diff_pp(that, same_t)}
            out[p][m] = row
        ctl = out[p].get(CONTROL)
        for row in out[p].values():
            for ms in _MEASURES:
                a, b = row[ms]["chenh_dpct"], ctl[ms]["chenh_dpct"] if ctl else None
                row[ms]["tru_atr_band"] = (None if a is None or b is None
                                           else round(a - b, 1))
    return out


def _r(x: dict) -> str:
    if x.get("rate") is None:
        return f"{'—':>6s} {'':13s} n={x['n']:,d}"
    lo, hi = x["ci"]
    return f"{x['rate'] * 100:5.1f}% [{lo * 100:4.1f}–{hi * 100:4.1f}] n={x['n']:,d}"


def _d(v) -> str:
    return "     —" if v is None else f"{v:+6.1f}"


def _row(m: str, x: dict, tail: str = "") -> str:
    """thật · giả khớp ATR · CHÊNH · −atr_band ‖ giả cùng % · CHÊNH cùng % [· phủ]."""
    return (f"      {m:14s} {_r(x['that'])} · {_r(x['gia'])} · {_d(x['chenh_dpct'])} · "
            f"{_d(x['tru_atr_band'])} ‖ {_r(x['gia_cung_pct'])} · {_d(x['chenh_cung_pct'])}"
            f"{tail}")


_HEAD = "thật · giả khớp ATR · CHÊNH (điểm %) · −atr_band ‖ giả cùng % · CHÊNH cùng %"


def report(group: str, summary: dict, meta: dict) -> str:
    lines = ["", f"══ {group} — {meta.get('so_ma', 1):,d} chuỗi · {meta['mau']:,d} ngày chấm · cắt nửa "
                 f"{meta['cat_nua']}"]
    for p in PERIODS:
        rows = summary.get(p) or {}
        if not rows:
            continue
        lines += ["", f"  [{_PERIOD_LABEL[p]}]"]
        for s in SIDES:
            lines.append(f"    {_SIDE_LABEL[s]}:  {_HEAD} · phủ")
            for m, r in rows.items():
                x = r[s]
                phu = "—" if x["phu"] is None else f"{x['phu'] * 100:.0f}%"
                hold = dict(x, **{k: x[k]["hold_if_touched"]
                                  for k in ("that", "gia", "gia_cung_pct")})
                lines.append(_row(m, hold, f" · {phu}"))
        for s in SIDES:
            lines.append(f"    {_TRIG_LABEL[s]} (5 phiên):  {_HEAD}")
            for m, r in rows.items():
                lines.append(_row(m, r[f"trigger_{s}"]))
    return "\n".join(lines)


def caveats(step: int) -> list[str]:
    same = (f"--step {step} < {TRIGGER_SPAN} ⇒ hai ngày liền của CÙNG mã dùng chung bar tương lai "
            "của trigger; " if step < TRIGGER_SPAN else "")
    return [
        f"⚠ Ngày chấm CHỒNG CỬA SỔ: {same}mọi mã cùng ngày chịu chung một cú thị trường, và mức "
        "giả bốc ngày trùng nhau giữa các phương pháp ⇒ Wilson 95% giả định độc lập, HẸP hơn thật "
        "nhiều. Chỉ tin CHÊNH lớn và BỀN qua cả hai nửa.",
        "⚠ Mức giả bốc ngày ngẫu nhiên trên CẢ chuỗi (trước lẫn sau t) — là mốc so, không phải dự "
        "báo; mức thật chỉ dùng bar ≤ t.",
        "⚠ CHÊNH chính so với mốc KHỚP BIẾN ĐỘNG: ở ngày giả i, khoảng cách = (khoảng cách % ngày "
        "t ÷ ATR% ngày t) × ATR% ngày i — cùng số bội ATR. Mốc cũ CÙNG % (cột sau ‖) thiên vị "
        "phương pháp có khoảng cách bám ATR(t) (atr_band, volume_node, touch_cluster): mức đặt "
        "lúc biến động cao/thấp được so với mức giả cùng % ở ngày biến động khác ⇒ CHÊNH dương "
        "dù không có S/R thật (random walk vol đổi chế độ: atr_band 'chạm thì giữ' +7–8 điểm %, "
        "trigger −10–12). Hai cột lệch nhau nhiều = phần đó là bias biến động, không phải mức. "
        "Mốc khớp cũng không hoàn hảo: khoảng cách cố định theo % (round_number) bị lệch NGƯỢC "
        "~−2 điểm khi vol đổi chế độ mạnh, trigger còn dư vài điểm (ATR chưa kịp bắt cú biến "
        "động làm nên ngày trigger).",
        f"⚠ '−atr_band' = CHÊNH chính của phương pháp TRỪ CHÊNH chính của {CONTROL} (mốc ngây thơ "
        "thuần ATR: 'chạm thì giữ' của nó ≈ 0 theo cách dựng). Phương pháp chỉ đáng tin khi CHÊNH "
        "dương VÀ hơn atr_band, bền qua cả hai nửa.",
        "⚠ 'phủ' = tỉ lệ ngày phương pháp đưa ra được mức (qua luật lọc chung 0,5%–7%, cách nhau "
        "≥ 0,8%); phương pháp phủ thấp được chấm trên tập ngày KHÁC.",
    ]


# ── Đọc kho (mỏng) ───────────────────────────────────────────────────────────

def _read(td: Path) -> pd.DataFrame:
    from vnstock_horizons_state import read_ticker
    return read_ticker(td)


def load_index_bars(wh: Path) -> pd.DataFrame:
    """VNINDEX ngày (OHLC), đơn vị điểm như `vnstock_brief._load_vnindex_df`."""
    for sym in ("VNINDEX", "VN-INDEX", "^VNINDEX"):
        df = _read(wh / "prices" / f"ticker={sym}")
        if df.empty:
            continue
        df = normalize_bars(df)
        if float(df["close"].iloc[-1]) > 5000:
            for c in ("open", "high", "low", "close"):
                df[c] = df[c].astype(float) / 1000
        return df
    return normalize_bars(pd.DataFrame())


def ticker_bars(td: Path) -> pd.DataFrame | None:
    from vnstock_price_units import normalize_price_units
    raw = _read(td)
    if raw.empty or not {"high", "low", "volume"} <= set(raw.columns):
        return None
    bars = normalize_bars(normalize_price_units(raw))
    return bars if len(bars) >= MIN_HISTORY + ts.HORIZON else None


def run(wh: Path, step: int = DEFAULT_STEP, min_gtgd: float = 1.0,
        fake_k: int = ts.FAKE_PER_LEVEL, progress: bool = True) -> dict:
    t0 = time.time()
    idx = load_index_bars(wh)
    if idx.empty or len(idx) < MIN_HISTORY + ts.HORIZON:
        raise ValueError(f"Kho {wh} không có VNINDEX đủ {MIN_HISTORY + ts.HORIZON} phiên")
    sessions = pd.DatetimeIndex(idx["time"])
    first, last = sessions[MIN_HISTORY - 1], sessions[-1 - ts.HORIZON]
    mid = first + (last - first) / 2

    idx_methods = dict(srm.METHODS, pivot60=partial(srm.pivot60, with_extremes=True))
    acc_idx = new_acc(idx_methods)
    n_idx = eval_series(idx, sample_positions(len(idx), step), idx_methods, acc_idx, mid,
                        seed=ts.SEED, fake_k=fake_k)

    acc_tk, n_tk, n_series = new_acc(srm.METHODS), 0, 0
    dirs = [td for td in sorted((wh / "prices").glob("ticker=*"))
            if len(td.name.split("=", 1)[1]) <= 5 and td.name.split("=", 1)[1].isalpha()]
    for i, td in enumerate(dirs, 1):
        tk = td.name.split("=", 1)[1]
        bars = ticker_bars(td)
        if bars is not None:
            t_idx = pd.DatetimeIndex(bars["time"])
            g = (session_gtgd20(t_idx, bars["close"], bars["volume"], sessions)
                 .reindex(t_idx).to_numpy())
            pos = [t for t in sample_positions(len(bars), step) if g[t] >= min_gtgd]
            if pos:
                n_tk += eval_series(bars, pos, srm.METHODS, acc_tk, mid,
                                    seed=ts.SEED + zlib.crc32(tk.encode()), fake_k=fake_k)
                n_series += 1
        if progress and i % 200 == 0:
            print(f"  … {i:,d}/{len(dirs):,d} mã · {time.time() - t0:,.0f}s", flush=True)
    cut = str(mid.date())
    return {"warehouse": str(wh), "step": step, "min_gtgd": min_gtgd, "fake_k": fake_k,
            "tu": str(first.date()), "den": str(last.date()), "cat_nua": cut,
            "giay": round(time.time() - t0, 1),
            "vnindex": {"meta": {"so_ma": 1, "mau": n_idx, "cat_nua": cut},
                        "ket_qua": summarize(acc_idx)},
            "ma": {"meta": {"so_ma": n_series, "mau": n_tk, "cat_nua": cut},
                   "ket_qua": summarize(acc_tk)}}


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warehouse", default=str(_REPO / "data_warehouse"))
    ap.add_argument("--step", type=int, default=DEFAULT_STEP,
                    help=f"mỗi mã lấy một ngày mỗi N phiên (mặc định {DEFAULT_STEP})")
    ap.add_argument("--min-gtgd", type=float, default=1.0, help="GTGD TB20 tối thiểu tại t, tỷ VND")
    ap.add_argument("--fake-k", type=int, default=ts.FAKE_PER_LEVEL,
                    help=f"số mức giả mỗi mức thật (mặc định {ts.FAKE_PER_LEVEL} như ta-score)")
    ap.add_argument("--json", default=None, help="ghi kết quả JSON ra đường dẫn này")
    a = ap.parse_args(argv)

    wh = Path(a.warehouse)
    print(f"Đọc kho {wh} (chỉ đọc) — bước {a.step} phiên, GTGD TB20 ≥ {a.min_gtgd:,.2f} tỷ ...")
    try:
        res = run(wh, a.step, a.min_gtgd, a.fake_k)
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    print(f"Lịch chấm {res['tu']} → {res['den']} · {res['giay']:,.1f}s")
    for w in caveats(a.step):
        print(w)
    print(report("VN-Index", res["vnindex"]["ket_qua"], res["vnindex"]["meta"]))
    print(report(f"Mã (GTGD TB20 ≥ {a.min_gtgd:,.2f} tỷ)", res["ma"]["ket_qua"], res["ma"]["meta"]))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float),
                                encoding="utf-8")
        print(f"\n→ JSON: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
