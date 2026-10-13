"""Brief 3 khung thời gian — LÕI THUẦN (không I/O, không ghi kho).

Thiết kế + số replay: `docs/THIET-KE-BRIEF-3-KHUNG.md` (chốt 05/10/2026, U70).
Module này là phần TÍNH của P1a; P0 (`scripts/replay_horizons.py`) dùng ĐÚNG
các hàm này trên kho thật để chốt tham số — replay và production không được
lệch nhau. Chưa nối vào pipeline/brief (P1a/P1b làm việc đó).

Năm thành phần:
  • Ngắn hạn  — máy trạng thái trên điểm 7 phiếu của `classify_regime`
                (nhịp hồi / chưa rõ / nhịp chỉnh). Quyết Stance ngày mai.
  • Trung hạn — xu hướng TUẦN: đóng tuần so MA40 tuần ±band + MA10/MA40.
                Xuống 1 tuần, lên 2 tuần, mỗi tuần ≤1 bậc, cầu chì 8% từ đỉnh
                12 đóng tuần cho bước TĂNG→ĐI NGANG (§7.3). Là TIÊU ĐỀ brief.
                CHỈ đọc giá đóng tuần — nhiễu giữa tuần không đổi được nó.
  • Mức kích hoạt — giải đóng tuần X cần để đổi trạng thái (2 ràng buộc).
  • 🚨 Rủi ro ngắn hạn — sụt 5% từ đỉnh 20 phiên / −2.5% một phiên / −4% ba
                phiên; neo đỉnh lúc bật; KHÔNG BAO GIỜ đổi xu hướng.
  • Lớp bảo vệ 2 mức + bảng Stance (§3.4, §7.3).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date
from typing import Sequence

HOI, CHUA_RO, CHINH = 1, 0, -1
TANG, DI_NGANG, GIAM = 1, 0, -1
SHORT_LABEL = {HOI: "nhịp hồi", CHUA_RO: "chưa rõ", CHINH: "nhịp chỉnh"}
MEDIUM_LABEL = {TANG: "TĂNG", DI_NGANG: "ĐI NGANG", GIAM: "GIẢM"}

STANCE_UP, STANCE_FLAT, STANCE_DOWN = "TĂNG", "TRUNG TÍNH", "GIẢM"


def horizons_enabled() -> bool:
    """Công tắc brief 3 khung VNSTOCK_HORIZONS (mặc định TẮT cho tới #26) — MỘT
    chỗ đọc cho brief, nhãn regime/quant, Telegram, dashboard. Ngoại lệ I/O duy
    nhất của module lõi (chỉ đọc biến môi trường)."""
    return os.environ.get("VNSTOCK_HORIZONS", "0").strip().lower() in ("1", "true", "on", "yes")
PROTECT_HARD, PROTECT_SOFT = "cứng", "mềm"


# ── Ngắn hạn ─────────────────────────────────────────────────────────────

def short_threshold(n_signals: int) -> int:
    """Ngưỡng vào nhịp: ceil(4n/7) — n=6,7 → 4; n=4,5 → 3."""
    return math.ceil(4 * n_signals / 7)


def short_step(prev: int, score: int, n_signals: int) -> int:
    """Một phiên của máy trạng thái ngắn hạn (§3.3).

    Giảm rủi ro được nhảy thẳng (hồi → chỉnh khi S ≤ −thr); tăng rủi ro thì
    không: chỉnh → hồi PHẢI qua chưa rõ. n=0 (không phiếu nào) ⇒ giữ nguyên.
    """
    if n_signals <= 0:
        return prev
    thr = short_threshold(n_signals)
    if score <= -thr:
        return CHINH
    if prev == CHINH:
        return CHUA_RO if score >= 0 else CHINH
    if prev == HOI:
        return CHUA_RO if score <= 0 else HOI
    return HOI if score >= thr else CHUA_RO


def short_series(scores: Sequence[int], n_signals: Sequence[int],
                 start: int = CHUA_RO) -> list[int]:
    out, st = [], start
    for s, n in zip(scores, n_signals):
        st = short_step(st, int(s), int(n))
        out.append(st)
    return out


# ── Trung hạn (tuần) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class MediumParams:
    ma_short: int = 10          # tuần
    ma_long: int = 40           # tuần
    band: float = 0.02          # ±2% quanh MA dài
    up_weeks: int = 2           # tăng rủi ro cần N lần đọc liền
    fuse: float | None = 0.08   # cầu chì TĂNG→ĐI NGANG; None = tắt
    fuse_weeks: int = 12        # đỉnh ĐÓNG TUẦN để đo cầu chì (≈60 phiên;
                                # replay 2017–2026 trùng hệt bản đỉnh 60 phiên ngày)


@dataclass(frozen=True)
class WeekState:
    week_end: date              # bar cuối của tuần ISO
    close: float
    ma_short: float | None
    ma_long: float | None
    reading: int | None         # đọc thô tuần này (None = chưa đủ MA)
    state: int                  # trạng thái SAU tuần này
    pending: int                # số lần đọc liền đang chờ để tăng rủi ro
    fused: bool = False         # bước xuống tuần này do cầu chì


def dedupe_daily(dates: Sequence[date], closes: Sequence[float]
                 ) -> tuple[list[date], list[float]]:
    """Sắp tăng dần, trùng ngày giữ bản XUẤT HIỆN SAU (conflicted copy Dropbox)."""
    by_day: dict[date, float] = {}
    for d, c in zip(dates, closes):
        if c is None or not math.isfinite(float(c)):
            continue
        by_day[d] = float(c)
    ds = sorted(by_day)
    return ds, [by_day[d] for d in ds]


def weekly_bars(dates: Sequence[date], closes: Sequence[float]
                ) -> list[tuple[date, float, int]]:
    """[(bar cuối tuần ISO, đóng, chỉ số bar ngày)] — tuần rỗng (Tết) tự bỏ."""
    out: list[tuple[date, float, int]] = []
    last_key = None
    for i, (d, c) in enumerate(zip(dates, closes)):
        key = d.isocalendar()[:2]
        if key == last_key:
            out[-1] = (d, c, i)
        else:
            out.append((d, c, i))
            last_key = key
    return out


def week_is_closed(week_end: date, latest_bar: date) -> bool:
    """Tuần chốt khi bar cuối là thứ Sáu, hoặc đã thấy bar của tuần sau."""
    return week_end.weekday() == 4 or latest_bar.isocalendar()[:2] != week_end.isocalendar()[:2]


def medium_reading(x: float, ma_s: float | None, ma_l: float | None,
                   band: float) -> int | None:
    if ma_s is None or ma_l is None:
        return None
    if x > (1 + band) * ma_l and ma_s > ma_l:
        return TANG
    if x < (1 - band) * ma_l and ma_s < ma_l:
        return GIAM
    return DI_NGANG


def medium_series(dates: Sequence[date], closes: Sequence[float],
                  params: MediumParams = MediumParams(),
                  include_open_week: bool = False) -> list[WeekState]:
    """Gấp toàn bộ lịch sử ngày → trạng thái từng tuần (§3.5 + cầu chì §7.3).

    `dates`/`closes` phải đã khử trùng + sắp tăng (`dedupe_daily`). Tuần cuối
    chưa chốt bị bỏ trừ khi `include_open_week` (đọc tạm, KHÔNG ghi state).
    """
    p = params
    wk = weekly_bars(dates, closes)
    if wk and not include_open_week and not week_is_closed(wk[-1][0], dates[-1]):
        wk = wk[:-1]
    wc = [c for _, c, _ in wk]
    st, pend, out = DI_NGANG, 0, []
    for i, (d, x, _di) in enumerate(wk):
        ma_s = sum(wc[i - p.ma_short + 1:i + 1]) / p.ma_short if i + 1 >= p.ma_short else None
        ma_l = sum(wc[i - p.ma_long + 1:i + 1]) / p.ma_long if i + 1 >= p.ma_long else None
        r = medium_reading(x, ma_s, ma_l, p.band)
        fused = False
        if r is not None:
            if st == TANG:
                hi = max(wc[max(0, i - p.fuse_weeks + 1):i + 1])
                fused = p.fuse is not None and x <= (1 - p.fuse) * hi
                if x < ma_l or ma_s < ma_l or fused:
                    fused = fused and not (x < ma_l or ma_s < ma_l)
                    st, pend = DI_NGANG, 0
            elif st == GIAM:
                pend = pend + 1 if (x > ma_l or ma_s > ma_l) else 0
                if pend >= p.up_weeks:
                    st, pend = DI_NGANG, 0
            elif r == GIAM:
                st, pend = GIAM, 0
            elif r == TANG:
                pend += 1
                if pend >= p.up_weeks:
                    st, pend = TANG, 0
            else:
                pend = 0
        out.append(WeekState(d, x, ma_s, ma_l, r, st, pend, fused))
    return out


def medium_effective_from(week_end: date, next_bar: date | None) -> date:
    """Ngày brief đầu tiên in trạng thái của tuần: thứ Sáu chính nó, thứ Sáu
    nghỉ thì phiên đầu tuần sau (lượt chạy đầu tiên thấy bar tuần mới)."""
    if week_end.weekday() == 4 or next_bar is None:
        return week_end
    return next_bar


def medium_daily(dates: Sequence[date], weeks: Sequence[WeekState]) -> list[int]:
    """Trạng thái trung hạn mà brief MỖI NGÀY in (theo tuần đã chốt gần nhất)."""
    eff: list[tuple[date, int]] = []
    pos = {d: i for i, d in enumerate(dates)}
    for w in weeks:
        i = pos.get(w.week_end)
        nxt = dates[i + 1] if i is not None and i + 1 < len(dates) else None
        eff.append((medium_effective_from(w.week_end, nxt), w.state))
    out, j, st = [], 0, DI_NGANG
    for d in dates:
        while j < len(eff) and eff[j][0] <= d:
            st = eff[j][1]
            j += 1
        out.append(st)
    return out


# ── Mức kích hoạt (giải đóng tuần X, đủ 2 ràng buộc) ─────────────────────

@dataclass(frozen=True)
class Level:
    kind: str            # to_giam | to_tang | leave_tang | leave_giam
    price: float
    reachable: bool      # False ⇒ in "chưa thể trong tuần này"


def trigger_levels(prior_weekly: Sequence[float], state: int, last_price: float,
                   high_52w: float, params: MediumParams = MediumParams(),
                   max_gap: float = 0.08) -> list[Level]:
    """Mức đóng tuần X đổi trạng thái tuần NÀY (§3.5).

    `prior_weekly` = các đóng tuần ĐÃ CHỐT trước tuần này. Với l=MA dài,
    s=MA ngắn, S_l = tổng l−1 tuần trước, S_s = tổng s−1 tuần trước:
      giá:   X > (1+b)·S_l/(l−1−b)  ·  X < (1−b)·S_l/(l−1+b)  ·  X ≷ S_l/(l−1)
      cắt:   MA_s ≷ MA_l  ⇔  X ≷ C = (s·S_l − l·S_s)/(l − s)
    """
    p = params
    s, l, b = p.ma_short, p.ma_long, p.band
    if len(prior_weekly) < l - 1 or s >= l:
        return []
    S_l = sum(prior_weekly[-(l - 1):])
    S_s = sum(prior_weekly[-(s - 1):]) if s > 1 else 0.0
    cross = (s * S_l - l * S_s) / (l - s)
    up_px = (1 + b) * S_l / (l - 1 - b)
    dn_px = (1 - b) * S_l / (l - 1 + b)
    ma_eq = S_l / (l - 1)

    def _lv(kind: str, x: float) -> Level:
        ok = abs(x / last_price - 1) <= max_gap if last_price else False
        if kind in ("to_tang", "leave_giam") and x > high_52w:
            ok = False
        return Level(kind, x, ok)

    if state == DI_NGANG:
        return [_lv("to_giam", min(dn_px, cross)), _lv("to_tang", max(up_px, cross))]
    if state == TANG:
        x = max(ma_eq, cross)
        if p.fuse is not None and p.fuse_weeks > 1:
            hi = max(prior_weekly[-(p.fuse_weeks - 1):])
            x = max(x, (1 - p.fuse) * hi)
        return [_lv("leave_tang", x)]
    return [_lv("leave_giam", min(ma_eq, cross))]


# ── 🚨 Rủi ro ngắn hạn ───────────────────────────────────────────────────

@dataclass(frozen=True)
class AlertParams:
    drawdown: float = 0.05      # đóng ≤ 95% đỉnh đóng 20 phiên
    day_drop: float = -2.5      # % một phiên
    three_day_drop: float = -4.0
    tier2_frac: float = 0.90    # đóng ≤ 90% neo ⇒ mức 2
    dwell: int = 5              # phiên tối thiểu trước khi tắt
    off_frac: float = 0.97      # tắt khi đóng ≥ 97% neo …
    off_above_ma: int = 3       # … hoặc N phiên liền đóng trên MA20
    window: int = 20


@dataclass(frozen=True)
class AlertDay:
    tier: int                   # 0 tắt · 1 · 2
    anchor: float | None        # đỉnh 20 phiên lúc bật
    onset: bool = False


def alert_series(closes: Sequence[float], params: AlertParams = AlertParams()
                 ) -> list[AlertDay]:
    """🚨 theo từng phiên (§3.7). Neo cố định từ lúc bật — không tự tắt khi
    đỉnh trôi khỏi cửa sổ 20 phiên."""
    p = params
    out: list[AlertDay] = []
    tier, anchor, n_on, above = 0, None, 0, 0
    for i, x in enumerate(closes):
        chg1 = (x / closes[i - 1] - 1) * 100 if i >= 1 else None
        chg3 = (x / closes[i - 3] - 1) * 100 if i >= 3 else None
        hi = max(closes[i - p.window + 1:i + 1]) if i + 1 >= p.window else None
        ma = sum(closes[i - p.window + 1:i + 1]) / p.window if i + 1 >= p.window else None
        if tier == 0:
            trig = ((hi is not None and x <= (1 - p.drawdown) * hi)
                    or (chg1 is not None and chg1 <= p.day_drop)
                    or (chg3 is not None and chg3 <= p.three_day_drop))
            if trig and hi is not None:
                tier, anchor, n_on, above = 1, hi, 0, 0
                out.append(AlertDay(1, anchor, True))
                continue
            out.append(AlertDay(0, None))
            continue
        n_on += 1
        above = above + 1 if (ma is not None and x > ma) else 0
        if tier == 1 and (x <= p.tier2_frac * anchor
                          or (chg1 is not None and chg1 <= p.day_drop)):
            tier = 2
        if n_on >= p.dwell and (x >= p.off_frac * anchor or above >= p.off_above_ma):
            out.append(AlertDay(0, None))
            tier, anchor = 0, None
            continue
        out.append(AlertDay(tier, anchor))
    return out


# ── Lớp bảo vệ + Stance ──────────────────────────────────────────────────

def protection_level(floor_old: str | None, short: int, medium: int,
                     alert_tier: int) -> str | None:
    """2 mức (§7.3). Floor cũ GIẢM MỘT MÌNH luôn là cứng ⇒ mức cứng là tập
    cha của bảo vệ hiện nay (không phiên nào mất bảo vệ so với trước)."""
    sigs = (floor_old == STANCE_DOWN, short == CHINH, medium == GIAM, alert_tier > 0)
    n = sum(sigs)
    if floor_old == STANCE_DOWN or n >= 2:
        return PROTECT_HARD
    return PROTECT_SOFT if n == 1 else None


@dataclass(frozen=True)
class StanceRule:
    forced: str | None          # code ép nhãn; None = agent chọn trong `allowed`
    allowed: tuple[str, ...]
    default: str                # nhãn khi agent chọn ngoài tập


def stance_rule(short: int, medium: int, alert_tier: int) -> StanceRule:
    """Bảng §3.4: TĂNG chỉ khi trung hạn TĂNG; ép TĂNG chỉ ở ô hồi × TĂNG ×
    🚨 tắt. Ngoài ô đó GIẢM luôn được phép — mọi phiên có 🚨 đều được GIẢM."""
    alert = alert_tier > 0
    if short == CHINH:
        return StanceRule(STANCE_DOWN, (STANCE_DOWN,), STANCE_DOWN)
    if medium == TANG:
        if short == HOI and not alert:
            return StanceRule(STANCE_UP, (STANCE_UP,), STANCE_UP)
        if short == HOI:
            return StanceRule(None, (STANCE_UP, STANCE_FLAT, STANCE_DOWN), STANCE_FLAT)
        up = () if alert else (STANCE_UP,)
        return StanceRule(None, up + (STANCE_FLAT, STANCE_DOWN), STANCE_FLAT)
    return StanceRule(None, (STANCE_FLAT, STANCE_DOWN), STANCE_FLAT)
