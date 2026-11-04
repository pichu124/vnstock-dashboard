"""Thước đo nhận định kỹ thuật (P0 PTKT) — LÕI THUẦN, không I/O.

Đặc tả: `docs/THIET-KE-PHAN-TICH-KY-THUAT.md` §3, §13.1 (luật chấm setup, user đồng ý
nguyên văn), §14a. Lớp đọc kho + CLI ở `vnstock_ta_score_io.py` (`run.py ta-score`).

  T1  S1/R1 VN-Index có giữ không        `score_levels` + mốc mức giả `fake_level_outcomes`
  T2  đóng cửa vượt R1 ⇒ chạm R2 (S đối xứng) `score_trigger`, tách khối lượng xác nhận
  T3  Stance theo MỘT quy tắc              `stance_outcome` / `summarize_stances`
  T4  trạng thái horizons ⇒ lợi suất sau    `forward_returns_by_state`
  T5  S/R từng mã                          như T1, trên bar của mã
  Setup watchlist (vào / cắt lỗ / chốt lời) `grade_setup`

`bars` ở mọi hàm = DataFrame sắp tăng theo ngày, cột `open/high/low/close` (+ `volume`
nếu có, + `time`). Giá cổ phiếu tính bằng nghìn VND như kho.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HELD, PIERCED, UNTOUCHED = "held", "pierced", "untouched"
FLAT_PCT = 0.3                 # T3: |Δ| < 0,3% là phẳng (§14a)
PIERCE_PCT = 0.5               # T1/T5: đóng cửa vượt mức quá 0,5% là xuyên
HORIZON = 5                    # T1/T2/T5: số phiên sau brief
VOL_MULT = 1.2                 # T2: KL phiên ≥ 1,2× TB20 là có xác nhận
FAKE_PER_LEVEL = 20            # T1/T5: số mức giả cho mỗi mức thật
SEED = 20261104                # mốc ngẫu nhiên cố định — chạy lại ra cùng số
MIN_SAMPLES = 20               # badge doctor: dưới sàn luôn ok n=…

# §13.1: (hiệu lực khi chưa chạm trigger, giữ tối đa) theo phiên
FRAMES = {"short": (3, 10), "medium": (10, 60), "long": (20, 250)}
LIMIT_PCT = {"HOSE": 7.0, "HNX": 10.0, "UPCOM": 15.0}
FEE_PCT = 0.15                 # mỗi chiều
SELL_TAX_PCT = 0.1


# ── Thống kê ─────────────────────────────────────────────────────────────

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Khoảng Wilson 95% cho tỉ lệ k/n (đơn vị 0–1). n=0 ⇒ None."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)


def rate(k: int, n: int) -> dict:
    """{k, n, rate, ci} — rate/ci None khi n=0 (chưa đo được ≠ 0%)."""
    return {"k": int(k), "n": int(n), "rate": round(k / n, 4) if n else None,
            "ci": wilson(k, n)}


# ── T1 / T5: mức hỗ trợ / kháng cự ───────────────────────────────────────

def score_levels(bars: pd.DataFrame, level: float, side: str,
                 horizon: int = HORIZON, pierce_pct: float = PIERCE_PCT) -> str | None:
    """Số phận một mức trong `horizon` phiên ĐẦU của `bars` (các phiên SAU brief).

    support: chạm = low ≤ mức; xuyên = có phiên đóng cửa < mức×(1−pierce_pct%).
    resistance đối xứng (high ≥ mức; đóng cửa > mức×(1+pierce_pct%)).
    Xuyên ở bất kỳ phiên nào trong cửa sổ ⇒ `pierced` (bật rồi thủng vẫn là thủng).
    Chưa đủ `horizon` phiên ⇒ None (chưa chấm được)."""
    if side not in ("support", "resistance"):
        raise ValueError(f"side phải là support/resistance, nhận {side!r}")
    lo, hi, cl = (bars[c].to_numpy(dtype=float)[:horizon] for c in ("low", "high", "close"))
    return _level_outcome(lo, hi, cl, level, side, horizon, pierce_pct)


def _level_outcome(lo, hi, cl, level, side, horizon, pierce_pct) -> str | None:
    """Lõi `score_levels` trên mảng numpy (mức giả gọi hàng chục nghìn lần)."""
    if len(cl) < horizon or not level or level <= 0:
        return None
    k = pierce_pct / 100
    if side == "support":
        touched, pierced = (lo <= level).any(), (cl < level * (1 - k)).any()
    else:
        touched, pierced = (hi >= level).any(), (cl > level * (1 + k)).any()
    if pierced:
        return PIERCED
    return HELD if touched else UNTOUCHED


def level_summary(outcomes: Iterable[str | None]) -> dict:
    """Đếm kết cục; `hold_if_touched` = held / (held + pierced)."""
    xs = [o for o in outcomes if o]
    held, pierced = xs.count(HELD), xs.count(PIERCED)
    return {"n": len(xs), HELD: held, PIERCED: pierced, UNTOUCHED: xs.count(UNTOUCHED),
            "touch": rate(held + pierced, len(xs)),
            "hold_if_touched": rate(held, held + pierced)}


def fake_level_outcomes(bars: pd.DataFrame, dist_pct: float, side: str,
                        k: int = FAKE_PER_LEVEL, seed: int = SEED,
                        horizon: int = HORIZON, pierce_pct: float = PIERCE_PCT,
                        exclude: Sequence[int] = ()) -> list[str | None]:
    """Mốc so cho T1/T5: `k` mức GIẢ cùng khoảng cách % tới giá đóng cửa, đặt ở các
    ngày ngẫu nhiên (seed cố định) trong `bars`.

    Vì sao: mức gần giá thì dễ chạm, mức xa thì dễ "giữ" — tỉ lệ thô không nói được
    pivot có nghĩa hay không. Giữ nguyên khoảng cách, đổi ngày ⇒ phần chênh giữa mức
    thật và mức giả là phần pivot thêm vào. `exclude` = vị trí bar không được bốc
    (chính ngày brief, để mức giả không trùng mức thật)."""
    n_ok = len(bars) - horizon
    if n_ok <= 1 or dist_pct <= 0:
        return []
    pool = np.delete(np.arange(n_ok), [e for e in exclude if 0 <= e < n_ok])
    if not len(pool):
        return []
    rng = np.random.default_rng(seed)
    picks = rng.choice(pool, size=min(k, len(pool)), replace=False)
    lo, hi, cl = (bars[c].to_numpy(dtype=float) for c in ("low", "high", "close"))
    sign = -1 if side == "support" else 1
    out = []
    for i in sorted(picks):
        w = slice(i + 1, i + 1 + horizon)
        out.append(_level_outcome(lo[w], hi[w], cl[w], cl[i] * (1 + sign * dist_pct / 100),
                                  side, horizon, pierce_pct))
    return out


def level_distance_pct(level: float, close: float, side: str) -> float | None:
    """Khoảng cách % từ giá tới mức, dương khi mức nằm ĐÚNG phía (S dưới, R trên)."""
    if not level or not close or close <= 0:
        return None
    d = (close - level) / close * 100 if side == "support" else (level - close) / close * 100
    return d if d > 0 else None


# ── T2: trigger vượt R1 ⇒ chạm R2 ────────────────────────────────────────

def _volume_confirmed(bars: pd.DataFrame, i: int, mult: float) -> str:
    """confirmed / unconfirmed / unmeasurable — KL phiên i so TB20 của 20 phiên TRƯỚC."""
    if "volume" not in bars.columns or i < 20:
        return "unmeasurable"
    v = pd.to_numeric(bars["volume"], errors="coerce").to_numpy(dtype=float)
    prev = v[i - 20:i]
    if not np.isfinite(v[i]) or v[i] <= 0 or not np.isfinite(prev).all() or (prev <= 0).any():
        return "unmeasurable"
    return "confirmed" if v[i] >= mult * prev.mean() else "unconfirmed"


def score_trigger(bars: pd.DataFrame, base_idx: int, level1: float, level2: float,
                  side: str, horizon: int = HORIZON, vol_mult: float = VOL_MULT) -> dict:
    """Trigger trong `horizon` phiên sau `base_idx` (phiên brief):
    resistance: đóng cửa > R1 ⇒ có chạm R2 (high ≥ R2) trong `horizon` phiên SAU phiên
    trigger không; support: đóng cửa < S1 ⇒ chạm S2 (low ≤ S2). Phiên trigger đóng cửa
    đã qua luôn R2/S2 ⇒ tính là chạm.

    Trả {triggered, trigger_pos, hit, volume}. `hit` None = chưa đủ phiên để chấm."""
    out = {"triggered": False, "trigger_pos": None, "hit": None, "volume": None}
    if not level1 or not level2 or len(bars) <= base_idx + horizon:
        return out
    c = bars["close"].to_numpy(dtype=float)
    up = side == "resistance"
    for t in range(base_idx + 1, base_idx + horizon + 1):
        if (c[t] > level1) if up else (c[t] < level1):
            break
    else:
        return out
    out.update(triggered=True, trigger_pos=t, volume=_volume_confirmed(bars, t, vol_mult))
    if (c[t] >= level2) if up else (c[t] <= level2):
        out["hit"] = True
        return out
    w = bars.iloc[t + 1:t + 1 + horizon]
    if len(w) < horizon:
        return out
    out["hit"] = bool((w["high"] >= level2).any() if up else (w["low"] <= level2).any())
    return out


def trigger_summary(rows: Iterable[dict]) -> dict:
    """P(chạm mức 2 | trigger) — chung và tách theo khối lượng."""
    rs = [r for r in rows if r.get("triggered") and r.get("hit") is not None]
    out = {"all": rate(sum(r["hit"] for r in rs), len(rs))}
    for v in ("confirmed", "unconfirmed", "unmeasurable"):
        sub = [r for r in rs if r.get("volume") == v]
        out[v] = rate(sum(r["hit"] for r in sub), len(sub))
    return out


# ── T3: Stance ───────────────────────────────────────────────────────────

def brief_stance(output: str) -> str:
    """Stance từ TLDR — ĐÚNG đường đọc của `evaluate_brief_accuracy` (chỉ đọc)."""
    import vnstock_brief as vb
    if not output:
        return "unknown"
    return vb._detect_stance(vb._extract_section(output, "TLDR") or output[:400])


def direction(ret_pct: float, flat_pct: float = FLAT_PCT) -> str:
    return "flat" if abs(ret_pct) < flat_pct else ("up" if ret_pct > 0 else "down")


_MATCH = {"bullish": "up", "bearish": "down", "neutral": "flat"}
_FROM_DIR = {v: k for k, v in _MATCH.items()}


def date_positions(dates: Iterable) -> dict[str, int]:
    """{ISO ngày: vị trí} — dựng một lần cho mỗi chuỗi bar rồi đưa vào `base_index`."""
    return {str(d)[:10]: i for i, d in enumerate(dates)}


def base_index(pos: Mapping[str, int], brief_date: str, brief_type: str,
               intraday: bool = False) -> int | None:
    """Vị trí phiên GỐC so (`pos` = `date_positions(bars["time"])`).

    `brief_date` của brief là NGÀY DỮ LIỆU (`collect_context` lấy bar VNINDEX cuối):
      • chiều ⇒ gốc = đóng cửa phiên `brief_date`;
      • sáng chạy TRƯỚC giờ mở cửa ⇒ `brief_date` đã là phiên trước ⇒ gốc = phiên đó;
      • sáng chạy TRONG phiên (`intraday`: bar `brief_date` là bar dở) ⇒ gốc = phiên
        TRƯỚC `brief_date`, đích T+1 = đóng cửa phiên `brief_date`.
    Không có bar đúng `brief_date` ⇒ None (không đoán)."""
    i = pos.get(str(brief_date)[:10])
    if i is None:
        return None
    if brief_type == "morning" and intraday:
        return i - 1 if i >= 1 else None
    return i


def stance_outcome(stance: str, closes: Sequence[float], base: int, horizon: int,
                   flat_pct: float = FLAT_PCT, base_close: float | None = None) -> dict | None:
    """Chấm một stance ở T+horizon so gốc `base`. None = chưa đủ phiên / không chấm.

    `base_close`: giá LÚC brief chạy, cho brief sáng trong phiên — gốc là giá nó đã thấy,
    không phải đóng cửa hôm qua (không thì được tính công cho phần biến động đã biết;
    review P0 04/11). Mốc "lặp chiều hôm qua" vẫn theo chiều phiên `base`."""
    if base is None or base < 1 or base + horizon >= len(closes):
        return None
    c0 = float(base_close) if base_close else float(closes[base])
    c1 = float(closes[base + horizon])
    ret = (c1 / c0 - 1) * 100
    act = direction(ret, flat_pct)
    prev = direction((float(closes[base]) / float(closes[base - 1]) - 1) * 100, flat_pct)
    return {"ret_pct": round(ret, 3), "actual": act,
            "match": (_MATCH.get(stance) == act) if stance in _MATCH else None,
            "base_neutral": act == "flat",
            "base_repeat": prev == act, "repeat_stance": _FROM_DIR[prev]}


def _tally(rows: list[dict], key: str = "match") -> dict:
    xs = [r for r in rows if r.get(key) is not None]
    return rate(sum(bool(r[key]) for r in xs), len(xs))


def summarize_stances(records: list[dict], horizons: Sequence[int] = (1, 5)) -> dict:
    """records: {brief_type, brief_date, agent_name, sent, stance, h1, h5…} (h = kết quả
    `stance_outcome`). Mốc so tính MỖI PHIÊN một lần (không nhân theo số agent)."""
    out: dict = {}
    for bt in sorted({r["brief_type"] for r in records}):
        rs = [r for r in records if r["brief_type"] == bt]
        blk: dict = {"n_briefs": len(rs), "stance_dist": {}}
        for r in rs:
            blk["stance_dist"][r["stance"]] = blk["stance_dist"].get(r["stance"], 0) + 1
        for h in horizons:
            hk = f"h{h}"
            ev = [dict(r[hk], agent=r["agent_name"], sent=r.get("sent"), date=r["brief_date"])
                  for r in rs if r.get(hk)]
            sess = {e["date"]: e for e in ev}.values()
            sent_sess = [e for e in sess if any(x.get("sent") and x["date"] == e["date"]
                                                for x in ev)]
            agents = {}
            for a in sorted({e["agent"] for e in ev}):
                agents[a] = _tally([e for e in ev if e["agent"] == a])
            blk[hk] = {"all": _tally(ev),
                       "sent": _tally([e for e in ev if e.get("sent")]),
                       "by_agent": agents,
                       "baseline_neutral": _tally(list(sess), "base_neutral"),
                       "baseline_repeat": _tally(list(sess), "base_repeat"),
                       # mốc trên ĐÚNG tập phiên có bản gửi — so "sent" với mốc mọi phiên là
                       # so hai mẫu khác nhau (review P0 04/11)
                       "baseline_neutral_sent": _tally(sent_sess, "base_neutral"),
                       "baseline_repeat_sent": _tally(sent_sess, "base_repeat"),
                       "n_sessions": len(sess)}
        out[bt] = blk
    return out


# ── T4: lợi suất sau trạng thái ──────────────────────────────────────────

def _episodes(states: Sequence, key) -> int:
    """Số đoạn liên tục mang trạng thái `key`."""
    return sum(1 for i, s in enumerate(states) if s == key and (i == 0 or states[i - 1] != key))


def forward_returns_by_state(closes: Sequence[float], states: Sequence,
                             horizons: Sequence[int] = (5, 20, 60),
                             labels: Mapping | None = None) -> dict:
    """Lợi suất T+h sau mỗi phiên theo trạng thái phiên đó (states[i] ứng closes[i],
    None = không có trạng thái). Trả theo nhãn: n, TB, trung vị, tỉ lệ tăng + Wilson,
    số ĐOẠN liên tục (`episodes`) — các phiên trong cùng đoạn chồng cửa sổ nhau nên
    Wilson ở đây HẸP hơn thật; đọc kèm `episodes`. Khoá `_all` = mốc mọi phiên."""
    c = np.asarray(closes, dtype=float)
    labels = labels or {}
    out: dict = {}
    keys = sorted({s for s in states if s is not None}, key=str)
    for h in horizons:
        ret = np.full(len(c), np.nan)
        if len(c) > h:
            ret[:-h] = (c[h:] / c[:-h] - 1) * 100
        blk = {}
        for key in [*keys, "_all"]:
            mask = np.array([(s is not None) if key == "_all" else (s == key) for s in states])
            r = ret[mask & np.isfinite(ret)]
            blk[str(labels.get(key, key))] = {
                **rate(int((r > 0).sum()), len(r)),
                "mean_pct": round(float(r.mean()), 3) if len(r) else None,
                "median_pct": round(float(np.median(r)), 3) if len(r) else None,
                "episodes": _episodes(states, key) if key != "_all" else None}
        out[f"t{h}"] = blk
    return out


# ── Bộ chấm setup (§13.1) ────────────────────────────────────────────────

def _tick(price: float, exchange: str) -> float:
    """Bước giá, nghìn VND: HOSE 10/50/100 VND theo vùng giá, HNX/UPCoM 100 VND."""
    if exchange.upper() == "HOSE":
        return 0.01 if price < 10 else 0.05 if price < 50 else 0.10
    return 0.10


def ceiling_price(prev_close: float, exchange: str = "HOSE",
                  limit_pct: float | None = None) -> float:
    """Giá trần = tham chiếu × (1 + biên độ), làm tròn XUỐNG bước giá."""
    lim = LIMIT_PCT[exchange.upper()] if limit_pct is None else limit_pct
    raw = prev_close * (1 + lim / 100)
    t = _tick(raw, exchange)
    return math.floor(raw / t + 1e-9) * t


def _at_ceiling(bars: pd.DataFrame, i: int, exchange: str, limit_pct: float | None) -> bool:
    if i < 1:
        return False
    prev = float(bars["close"].iloc[i - 1])
    cp = ceiling_price(prev, exchange, limit_pct)
    return float(bars["open"].iloc[i]) >= cp - _tick(cp, exchange) / 2


def _find_entry(bars, i0, trig, valid, exchange, limit_pct) -> tuple[int | None, float, str]:
    """(vị trí phiên mua, giá mua, lý do khi không mua được)."""
    n = len(bars)
    o, h, lo = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low"))
    breakout = trig >= float(bars["close"].iloc[i0])
    blocked = False
    if lo[i0] <= trig <= h[i0] and i0 + 1 < n:        # (i) phiên ra khuyến nghị đã chạm
        if not _at_ceiling(bars, i0 + 1, exchange, limit_pct):
            return i0 + 1, o[i0 + 1], ""
        blocked = True
        start = i0 + 2
    else:
        start = i0 + 1
    for j in range(start, min(n, i0 + 1 + valid)):     # (ii) chạm trong cửa sổ hiệu lực
        reached = h[j] >= trig if breakout else lo[j] <= trig
        if not reached:
            continue
        if _at_ceiling(bars, j, exchange, limit_pct):
            blocked = True
            continue
        return j, (max(o[j], trig) if breakout else min(o[j], trig)), ""
    if n < i0 + 1 + valid:          # cửa sổ hiệu lực chưa hết ⇒ còn có thể khớp, kể cả khi
        return None, 0.0, "pending"   # một phiên trước đó mở cửa trần (review P0 04/11)
    return None, 0.0, "ceiling" if blocked else "no_trigger"


def _find_exit(bars, e, sl, tp, hold) -> tuple[int | None, float, str, bool]:
    """(vị trí phiên bán, giá bán, lý do, bán ở giá mở cửa?). Phiên mua và T+1 không bán
    được; low của CHÍNH phiên mua ≤ SL cũng tính là đã thủng (không biết thứ tự trong
    phiên ⇒ chọn hướng thận trọng, cùng tinh thần "chạm cả hai ⇒ SL")."""
    o, h, lo, c = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    breached = any(lo[k] <= sl for k in range(e, min(e + 2, len(bars))))
    for k in range(e + 2, min(len(bars), e + hold + 1)):
        if k == e + 2 and breached:
            return k, o[k], "sl", True                  # T+2,5: thủng trước đó ⇒ mở cửa T+2
        if o[k] <= sl:
            return k, o[k], "sl", True
        if o[k] >= tp:
            return k, o[k], "tp", True
        if lo[k] <= sl:                                 # cùng phiên chạm cả hai ⇒ SL
            return k, sl, "sl", False
        if h[k] >= tp:
            return k, tp, "tp", False
        if k == e + hold:
            return k, c[k], "expire", False
    return None, 0.0, "open", False


def _bench_return(bench: pd.Series | None, start, end) -> float | None:
    """Mua-giữ chỉ số: đóng cửa phiên TRƯỚC ngày mua → đóng cửa ngày bán (không phí)."""
    if bench is None or bench.empty:
        return None
    s = bench.copy()
    s.index = pd.to_datetime(s.index)
    a, b = s[s.index < pd.Timestamp(start)], s[s.index <= pd.Timestamp(end)]
    if a.empty or b.empty:
        return None
    return round((float(b.iloc[-1]) / float(a.iloc[-1]) - 1) * 100, 3)


def grade_setup(bars: pd.DataFrame, setup: Mapping, frame: str = "short",
                fee_pct: float = FEE_PCT, tax_pct: float = SELL_TAX_PCT,
                exchange: str = "HOSE", limit_pct: float | None = None,
                bench: pd.Series | None = None) -> dict:
    """Chấm MỘT setup mua theo đúng bảng §13.1.

    setup = {date: ngày ra khuyến nghị (sau phiên), trigger, sl, tp, side: "long"}.
    Vào lệnh: phiên `date` đã chạm trigger ⇒ mua giá mở cửa phiên sau; chưa chạm ⇒ mua
    khi chạm trigger trong cửa sổ hiệu lực (ngắn 3 / trung 10 / dài 20 phiên); mở cửa
    nhảy qua trigger ⇒ giá mở cửa; mở cửa ở giá trần ⇒ phiên đó không mua được.
    Trigger ≥ giá đóng cửa phiên `date` = lệnh mua vượt (chạm khi high ≥ trigger), dưới
    giá = lệnh chờ mua thấp (chạm khi low ≤ trigger).
    Thoát: bán sớm nhất phiên T+2; đã thủng SL trước đó ⇒ bán giá mở cửa T+2; cùng phiên
    chạm cả TP và SL ⇒ SL; mở cửa nhảy qua SL/TP ⇒ giá mở cửa; giữ tối đa ngắn 10 /
    trung 60 / dài 250 phiên ⇒ bán giá đóng cửa ngày hết hạn.
    Phí `fee_pct` mỗi chiều + thuế bán `tax_pct`. `bench` = chuỗi đóng cửa VN-Index
    (index ngày) ⇒ `bench_ret_pct` mua-giữ cùng thời gian.

    status: filled / not_filled (reason no_trigger | ceiling | pending) / no_data;
    reason khi filled: tp / sl / expire / open (chưa tới lúc thoát)."""
    if str(setup.get("side", "long")).lower() != "long":
        raise ValueError("grade_setup chỉ chấm lệnh mua (side=long)")
    if frame not in FRAMES:
        raise ValueError(f"frame phải là một trong {sorted(FRAMES)}")
    trig, sl, tp = (float(setup[k]) for k in ("trigger", "sl", "tp"))
    if not (0 < sl < trig < tp):
        raise ValueError(f"setup cần 0 < sl < trigger < tp (nhận {sl}, {trig}, {tp})")
    valid, hold = FRAMES[frame]
    res = {"status": "no_data", "entry_date": None, "entry": None, "exit_date": None,
           "exit": None, "reason": None, "ret_pct_net": None, "bench_ret_pct": None}
    b = bars.reset_index(drop=True)
    t = pd.to_datetime(b["time"]).dt.normalize()
    pos = np.flatnonzero(t <= pd.Timestamp(setup["date"]).normalize())
    if not len(pos):
        return res
    i0 = int(pos[-1])
    e, entry, why = _find_entry(b, i0, trig, valid, exchange, limit_pct)
    if e is None:
        return {**res, "status": "not_filled", "reason": why}
    x, exit_px, reason, at_open = _find_exit(b, e, sl, tp, hold)
    res.update(status="filled", entry_date=t[e].date().isoformat(), entry=round(entry, 4),
               reason=reason)
    if x is None:
        return res
    net = (exit_px * (1 - (fee_pct + tax_pct) / 100)) / (entry * (1 + fee_pct / 100)) - 1
    # Bán ở giá mở cửa ⇒ chỉ số so tới đóng cửa phiên trước (cùng thời điểm thị trường).
    bench_end = t[x - 1] if at_open else t[x]
    res.update(exit_date=t[x].date().isoformat(), exit=round(exit_px, 4),
               ret_pct_net=round(net * 100, 3),
               bench_ret_pct=_bench_return(bench, t[e], bench_end))
    return res


# ── Badge doctor ─────────────────────────────────────────────────────────

def badge_verdict(score: Mapping | None, min_samples: int = MIN_SAMPLES) -> tuple[str, str]:
    """(status, message) cho badge `ta_score`. Đọc Stance T+1 brief chiều: bản đã gửi
    nếu có ≥ sàn mẫu, không thì mọi bản. Dưới sàn ⇒ LUÔN ok kèm n=… (chưa đo được
    không phải đo ra xấu). Đủ mẫu mà thua mốc ngây thơ tốt hơn ⇒ warn."""
    if not score:
        return "off", "chưa chạy `run.py ta-score`"
    h1 = (((score.get("t3") or {}).get("afternoon") or {}).get("h1")) or {}
    sent, allb = h1.get("sent") or {}, h1.get("all") or {}
    use_sent = (sent.get("n") or 0) >= min_samples
    pick, tag = (sent, "bản đã gửi") if use_sent else (allb, "mọi bản")
    sfx = "_sent" if use_sent else ""
    n = int(pick.get("n") or 0)
    if n < min_samples:
        return "ok", f"Stance T+1 brief chiều n={n} — chưa đủ mẫu (cần ≥{min_samples})"
    acc = pick.get("rate") or 0.0
    bases = {"luôn trung tính": (h1.get(f"baseline_neutral{sfx}") or {}).get("rate"),
             "lặp chiều hôm qua": (h1.get(f"baseline_repeat{sfx}") or {}).get("rate")}
    name, best = max(((k, v) for k, v in bases.items() if v is not None),
                     key=lambda kv: kv[1], default=(None, None))
    msg = f"Stance T+1 brief chiều ({tag}) đúng {acc:.0%} n={n}"
    if best is None:
        return "ok", msg
    msg += f" · mốc {name} {best:.0%}"
    return ("warn", msg + " — THUA mốc ngây thơ") if acc < best else ("ok", msg)
