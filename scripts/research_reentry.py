"""#27 (P1b-9, NGHIÊN CỨU) — cửa tái nhập sớm cho kẹp tỷ trọng: đo phần bị lỡ của
kẹp hiện tại (#20) sau mỗi đáy ≥15% của VNINDEX + backtest 3 hướng mở sớm.

CHỈ ĐỌC kho ⇒ ○ máy nào cũng được, nhưng tránh lúc pipeline desktop đang chạy
(18:00 → `⏱ TỔNG`) vì nó đọc parquet đang bị ghi. Chạy ~1–3 phút (độ rộng tái dựng
từ parquet cho mọi phiên).

    python scripts/research_reentry.py                     # 2017-12 → nay, in bảng Markdown
    python scripts/research_reentry.py --out reentry.md    # ghi ra file để gửi Claude

Mô hình (ghi rõ để đọc số cho trung thực):
- **Band dữ liệu (không kẹp)** = band v1 của `vnstock_allocation` dựng lại từ 3 input
  tái dựng được theo ngày: regime 7 phiếu, momentum tâm lý (KHÔNG có tin/vĩ mô) và
  độ rộng % mã trên MA200 — trọng số renormalize như code thật; hysteresis 2 phiên
  + Vá 1 (1 bậc/lần). Thiếu vĩ mô/tilt báo cáo ⇒ đây là PROXY của band thật.
- **Kẹp (#20)** = `apply_horizon_cap` thật trên trung hạn/🚨 của `vnstock_horizons`.
- **A — lực đẩy độ rộng**: TB 10 phiên tỷ lệ mã tăng/(tăng+giảm) đi từ <40% lên
  >61.5% trong ≤10 phiên ⇒ +1 bậc dù trung hạn chưa TĂNG (đề bài không đặt điều
  kiện 🚨 cho A — lực đẩy thường tới khi 🚨 còn trong 5 phiên tối thiểu).
- **B — mở kẹp từng phần**: trung hạn rời GIẢM lên ĐI NGANG **và** 🚨 tắt ≥10 phiên
  ⇒ +1 bậc rồi đứng tới khi TĂNG.
- **C — theo độ sâu**: sụt ≥20% từ đỉnh 52 tuần **và** 🚨 tắt ⇒ +1 bậc.
  Mỗi hướng mở tối đa 1 lần cho tới khi trung hạn lên TĂNG (rồi mới mở lại).
- Danh mục: % cổ phiếu × lợi suất VNINDEX (chỉ số giá), phần còn lại 0%; quyết ở
  phiên t, thực hiện phiên t+1 (ăn lợi suất từ t+2); phí 0.15% × |đổi tỷ trọng|.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import vnstock_horizons as hz  # noqa: E402

_FEE = 0.0015
_THRUST_LO, _THRUST_HI, _THRUST_WIN = 0.40, 0.615, 10
_B_ALERT_OFF = 10
_C_DEPTH = -0.20
_TROUGH_DEPTH = -0.15
_TROUGH_WINDOW = 120          # phiên sau đáy để đo phần lỡ (hoặc tới khi lập đỉnh mới)
_REVERSAL = 20
VARIANTS = ("nocap", "cap", "A", "B", "C")


@dataclass
class Day:
    d: date
    close: float
    score: "float | None"         # điểm tổng hợp band (proxy) [-1, 1]
    medium: int
    tier: int
    adv_ratio: "float | None"     # tăng/(tăng+giảm) phiên đó


# ── Tín hiệu ──────────────────────────────────────────────────────────────

def thrust_days(days: list[Day]) -> list[bool]:
    """Lực đẩy độ rộng kiểu Zweig: TB 10 phiên tỷ lệ tăng vượt 61.5% trong khi ≤10
    phiên trước đó còn dưới 40%."""
    ma: list["float | None"] = []
    for i in range(len(days)):
        w = [x.adv_ratio for x in days[max(0, i - _THRUST_WIN + 1):i + 1]
             if x.adv_ratio is not None]
        ma.append(sum(w) / len(w) if len(w) == _THRUST_WIN else None)
    out = []
    for i, m in enumerate(ma):
        lows = [x for x in ma[max(0, i - _THRUST_WIN):i] if x is not None]
        out.append(m is not None and m > _THRUST_HI and bool(lows) and min(lows) < _THRUST_LO)
    return out


def drawdown_52w(days: list[Day]) -> list[float]:
    out = []
    for i, x in enumerate(days):
        top = max(y.close for y in days[max(0, i - 251):i + 1])
        out.append(x.close / top - 1)
    return out


def unlock_flags(days: list[Day], variant: str) -> list[bool]:
    """Ngày hướng mở sớm KÍCH HOẠT (chưa xét mỗi đợt 1 lần — simulate lo)."""
    n = len(days)
    if variant == "A":
        return thrust_days(days)
    if variant == "C":
        dd = drawdown_52w(days)
        return [dd[i] <= _C_DEPTH and days[i].tier == 0 for i in range(n)]
    if variant == "B":
        flags, left_giam, off = [], False, 0
        for i, x in enumerate(days):
            if x.medium == hz.GIAM:
                left_giam = False
            elif i and days[i - 1].medium == hz.GIAM and x.medium == hz.DI_NGANG:
                left_giam = True
            if x.medium == hz.TANG:
                left_giam = False
            off = off + 1 if x.tier == 0 else 0
            flags.append(left_giam and x.medium == hz.DI_NGANG and off >= _B_ALERT_OFF)
        return flags
    return [False] * n


# ── Mô phỏng tỷ trọng ─────────────────────────────────────────────────────

def simulate(days: list[Day], variant: str) -> list[float]:
    """% cổ phiếu hiệu lực mỗi phiên (0..100) theo band v1 proxy + kẹp/hướng mở."""
    import vnstock_allocation as alloc
    table = alloc._allocations_table()
    unlock = unlock_flags(days, variant)
    out: list[float] = []
    hyst_prev: "dict | None" = None
    prev: "dict | None" = None
    used = False
    for i, x in enumerate(days):
        if x.score is None:
            out.append(out[-1] if out else float(table["B2"]["Cổ phiếu"]))
            continue
        iso = x.d.isoformat()
        h = alloc.apply_hysteresis(hyst_prev, x.score, iso)
        hyst_prev = {"band": h["band"], "pending": h["pending"]}
        state = {"as_of": iso, "band": h["band"], "allocation": dict(table[h["band"]])}
        if variant != "nocap":
            if x.medium == hz.TANG:
                used = False
            opened = False
            if (variant in ("A", "B", "C") and unlock[i] and not used and prev
                    and alloc._BANDS.index(h["band"]) < alloc._BANDS.index(prev["band"])):
                step = alloc._BANDS[max(0, alloc._BANDS.index(prev["band"]) - 1)]
                state = {"as_of": iso, "band": step, "allocation": dict(table[step]),
                         "unlocked": variant}
                used = opened = True
            if not opened:
                alloc.apply_horizon_cap(state, prev, {"medium": x.medium, "alert_tier": x.tier},
                                        iso)
        prev = state
        out.append(float(state["allocation"]["Cổ phiếu"]))
    return out


def portfolio(days: list[Day], eq: list[float]) -> list[float]:
    """Giá trị danh mục (bắt đầu 1.0): ăn lợi suất phiên t bằng tỷ trọng quyết ở t−2."""
    val, out = 1.0, []
    for i in range(len(days)):
        if i >= 2:
            r = days[i].close / days[i - 1].close - 1
            w, w_prev = eq[i - 2] / 100, (eq[i - 3] if i >= 3 else eq[i - 2]) / 100
            val *= 1 + w * r - _FEE * abs(w - w_prev)
        out.append(val)
    return out


def max_dd(vals: list[float]) -> float:
    peak, worst = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def cagr(days: list[Day], vals: list[float]) -> float:
    yrs = (days[-1].d - days[0].d).days / 365.25
    return (vals[-1] / vals[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def troughs(days: list[Day]) -> list[tuple[int, int]]:
    """(chỉ số đáy, chỉ số cuối cửa sổ đo) cho mỗi đợt sụt ≥15% từ đỉnh 52 tuần."""
    dd = drawdown_52w(days)
    out, i, n = [], 0, len(days)
    while i < n:
        if dd[i] > _TROUGH_DEPTH:
            i += 1
            continue
        j = i
        while j < n and dd[j] < 0:
            j += 1                                   # tới khi lập đỉnh 52 tuần mới
        seg = range(i, j)
        t = min(seg, key=lambda k: days[k].close)
        out.append((t, min(t + _TROUGH_WINDOW, j - 1 if j < n else n - 1)))
        i = j + 1
    return out


def reversals(days: list[Day], eq: list[float], base: list[float]) -> "tuple[int, int, int]":
    """(số lần mở sớm, bị đảo tỷ trọng ≤20 phiên, giá 20 phiên sau thấp hơn)."""
    n_open = rev = lower = 0
    for i in range(1, len(eq)):
        if eq[i] > base[i] and eq[i] > eq[i - 1] and base[i] <= base[i - 1]:
            n_open += 1
            ahead = eq[i:i + _REVERSAL + 1]
            rev += any(v < eq[i] for v in ahead)
            k = min(i + _REVERSAL, len(days) - 1)
            lower += days[k].close < days[i].close
    return n_open, rev, lower


# ── Báo cáo ───────────────────────────────────────────────────────────────

def report(days: list[Day]) -> str:
    eqs = {v: simulate(days, v) for v in VARIANTS}
    vals = {v: portfolio(days, eqs[v]) for v in VARIANTS}
    lines = [f"# #27 — tái nhập sớm cho kẹp tỷ trọng ({days[0].d} → {days[-1].d}, "
             f"{len(days)} phiên)", ""]
    lines += ["## 1. Phần bị lỡ của kẹp hiện tại sau mỗi đáy ≥15%", "",
              "| Đáy | VNINDEX | Cửa sổ | Phiên kẹp < không kẹp | Lỡ (điểm %) cap | A | B | C |",
              "|---|---|---|---|---|---|---|---|"]
    for t, e in troughs(days):
        gap = {v: (vals["nocap"][e] / vals["nocap"][t] - vals[v][e] / vals[v][t]) * 100
               for v in ("cap", "A", "B", "C")}
        stuck = sum(1 for k in range(t, e + 1) if eqs["cap"][k] < eqs["nocap"][k])
        lines.append(f"| {days[t].d} | {days[t].close:,.0f} | {e - t} phiên | {stuck} | "
                     f"{gap['cap']:+.1f} | {gap['A']:+.1f} | {gap['B']:+.1f} | {gap['C']:+.1f} |")
    lines += ["", "(+ = lợi nhuận kém hơn KHÔNG kẹp trong cửa sổ; A/B/C cùng cửa sổ)", "",
              "## 2. So 3 hướng với kẹp hiện tại (toàn mẫu)", "",
              "| Phương án | CAGR | Max DD | Cổ phiếu TB | Mở sớm | Đảo ≤20 phiên | Giá 20p sau thấp hơn | 27/08/2026 |",
              "|---|---|---|---|---|---|---|---|"]
    i2708 = next((k for k, x in enumerate(days) if x.d.isoformat() == "2026-08-27"), None)
    for v in VARIANTS:
        opened = ("—", "—", "—")
        if v in ("A", "B", "C"):
            opened = tuple(str(x) for x in reversals(days, eqs[v], eqs["cap"]))
        e27 = f"{eqs[v][i2708]:g}%" if i2708 is not None else "—"
        lines.append(f"| {v} | {cagr(days, vals[v]) * 100:.2f}% | {max_dd(vals[v]) * 100:.1f}% | "
                     f"{sum(eqs[v]) / len(eqs[v]):.1f} | {opened[0]} | {opened[1]} | "
                     f"{opened[2]} | {e27} |")
    lines += ["", "Điều kiện bắt buộc: cột 27/08/2026 của A/B/C phải BẰNG dòng cap "
              "(ca 27/08 vẫn giữ tỷ trọng). Mô hình là PROXY (thiếu vĩ mô/tilt) — "
              "đọc chênh lệch giữa các dòng, không đọc mức tuyệt đối."]
    return "\n".join(lines)


def load_days(warehouse: Path, start: date) -> list[Day]:
    import vnstock_allocation as alloc
    import vnstock_horizons_state as hs
    dates, closes = hs.load_vnindex(warehouse)
    keep = [k for k, d in enumerate(dates) if d >= start]
    targets = [dates[k] for k in keep]
    print(f"[#27] dựng độ rộng {len(targets)} phiên từ parquet…", file=sys.stderr)
    breadth = hs.breadth_history(warehouse, targets)
    sc = hs.score_inputs(dates, closes, targets, breadth, hs.load_nn(warehouse))
    weeks = hz.medium_series(dates, closes, hs.PARAMS)
    medium = hz.medium_daily(dates, weeks)
    tiers = [a.tier for a in hz.alert_series(closes)]
    out = []
    for k in keep:
        d = dates[k]
        b, s = breadth.get(d, {}), sc.get(d, {})
        inputs = {}
        if s.get("score") is not None:
            inputs["regime"] = {"score": s["score"]}
        if s.get("momentum") is not None:
            inputs["sentiment"] = {"momentum": s["momentum"]}
        if b.get("above_ma200_pct") is not None:
            inputs["breadth"] = {"above_ma200_pct": b["above_ma200_pct"]}
        comp = alloc.compute_score(inputs) if inputs else None
        adv, dec = b.get("advances"), b.get("declines")
        ratio = adv / (adv + dec) if adv is not None and dec and adv + dec > 0 else None
        out.append(Day(d, closes[k], comp["score"] if comp else None, medium[k], tiers[k], ratio))
    return out


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="#27: phần lỡ của kẹp + backtest A/B/C (chỉ đọc kho)")
    ap.add_argument("--from", dest="start", default="2017-12-01")
    ap.add_argument("--out", default=None, help="ghi bảng Markdown ra file (ngoài kho)")
    a = ap.parse_args(argv)
    import vnstock_horizons_state as hs
    days = load_days(hs._WAREHOUSE, date.fromisoformat(a.start))
    if len(days) < 300:
        print(f"[#27] ❌ chỉ có {len(days)} phiên VNINDEX — cần kho thật")
        return 2
    text = report(days)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"[#27] đã ghi {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
