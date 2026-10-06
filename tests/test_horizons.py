"""vnstock_horizons — lõi brief 3 khung (docs/THIET-KE-BRIEF-3-KHUNG.md).

Các số neo (1,841.56 / 1,749.84 / 1,803.15) là VNINDEX thật tuần 28/08 và
09/10/2026 — bản đầu của thiết kế từng in sai ~1,823 vì chỉ giải ràng buộc giá.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

import vnstock_horizons as hz
from vnstock_horizons import (CHINH, CHUA_RO, DI_NGANG, GIAM, HOI, TANG,
                              STANCE_DOWN, STANCE_FLAT, STANCE_UP)

# 39 đóng tuần đã chốt trước tuần 28/08/2026 (tuần cuối = 21/08, 1,768.12)
W_TO_0821 = [1654.93, 1690.99, 1741.32, 1646.89, 1704.31, 1729.8, 1784.49, 1867.9,
             1879.13, 1870.79, 1829.04, 1755.49, 1824.09, 1880.33, 1767.84, 1696.24,
             1647.81, 1672.8, 1684.04, 1750.0, 1817.17, 1853.29, 1854.1, 1915.37,
             1921.6, 1877.13, 1863.49, 1838.9, 1791.65, 1824.53, 1871.91, 1862.08,
             1828.34, 1787.45, 1686.11, 1735.78, 1768.06, 1729.08, 1768.12]
# 39 đóng tuần tới 02/10/2026 (1,737.71 — tuần chuyển GIẢM)
W_TO_1002 = W_TO_0821[6:] + [1832.12, 1853.08, 1795.21, 1815.66, 1785.11, 1737.71]


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _daily_from_weekly(weekly: list[float], start: date = date(2020, 1, 6)):
    """Mỗi tuần 5 phiên, giá phẳng = đóng tuần (để trung hạn chỉ thấy đóng tuần)."""
    dates = _weekdays(start, 5 * len(weekly))
    closes = [w for w in weekly for _ in range(5)]
    return dates, closes


# ── Ngắn hạn ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n,thr", [(7, 4), (6, 4), (5, 3), (4, 3), (3, 2)])
def test_short_threshold_scales_with_signal_count(n, thr):
    assert hz.short_threshold(n) == thr


def test_short_enters_rebound_only_from_unclear():
    assert hz.short_step(CHUA_RO, 4, 7) == HOI
    assert hz.short_step(CHUA_RO, 3, 7) == CHUA_RO
    assert hz.short_step(CHINH, 7, 7) == CHUA_RO     # cấm chỉnh → hồi trực tiếp


def test_short_derisk_jumps_straight_to_correction():
    assert hz.short_step(HOI, -4, 7) == CHINH
    assert hz.short_step(HOI, 0, 7) == CHUA_RO
    assert hz.short_step(HOI, 1, 7) == HOI


def test_short_correction_exits_at_zero_and_no_signals_holds():
    assert hz.short_step(CHINH, -1, 7) == CHINH
    assert hz.short_step(CHINH, 0, 7) == CHUA_RO
    assert hz.short_step(HOI, -7, 0) == HOI          # n=0 ⇒ giữ nguyên


def test_short_series_never_goes_correction_to_rebound_in_one_session():
    rng = random.Random(7)
    scores = [rng.randint(-7, 7) for _ in range(2000)]
    st = hz.short_series(scores, [7] * len(scores))
    assert not any(a == CHINH and b == HOI for a, b in zip(st, st[1:]))


# ── Trung hạn ────────────────────────────────────────────────────────────

def _states(weekly, **kw):
    d, c = _daily_from_weekly(weekly)
    return [w.state for w in hz.medium_series(d, c, hz.MediumParams(**kw))]


def test_medium_needs_two_up_readings_but_one_down_reading():
    base = [100.0] * 40
    up = _states(base + [110, 112, 114], fuse=None)
    assert up[40] == DI_NGANG and up[41] == TANG      # đọc TĂNG lần 2 mới lên
    dn = _states(base + [90], fuse=None)
    assert dn[40] == GIAM                             # xuống: 1 lần đọc


def test_medium_never_jumps_tang_to_giam_in_one_week():
    st = _states([100.0] * 40 + [110, 112, 115, 118, 80], fuse=None)
    assert st[-2] == TANG and st[-1] == DI_NGANG


def test_medium_leaves_tang_below_ma40_without_band():
    # đóng tuần dưới MA40 một chút (không cần −2%) là rời TĂNG
    st = _states([100.0] * 40 + [110, 112, 114, 116, 103.5], fuse=None)
    assert st[-2] == TANG and st[-1] == TANG          # 103.5 > MA40, MA10 > MA40
    st = _states([100.0] * 40 + [110, 112, 114, 116, 101.0, 99.0], fuse=None)
    assert st[-1] == DI_NGANG


def test_medium_fuse_steps_down_on_8pct_drawdown_from_weekly_high():
    weekly = [100.0] * 40 + [110, 115, 120, 125, 114]   # −8.8% từ đỉnh 125
    assert _states(weekly, fuse=None)[-1] == TANG       # vẫn trên MA40
    d, c = _daily_from_weekly(weekly)
    ws = hz.medium_series(d, c, hz.MediumParams(fuse=0.08))
    assert ws[-1].state == DI_NGANG and ws[-1].fused


def test_medium_leaving_giam_needs_two_weeks():
    st = _states([100.0] * 40 + [90, 101, 101], fuse=None)
    assert st[40] == GIAM and st[41] == GIAM and st[42] == DI_NGANG


def test_medium_ignores_mid_week_noise():
    """Trung hạn chỉ nhận đóng tuần: sốc giá các ngày giữa tuần (kể cả đỉnh mới)
    không đổi được bất kỳ trạng thái tuần nào."""
    rng = random.Random(3)
    weekly = [100 + 10 * ((i // 15) % 2) + rng.uniform(-6, 6) for i in range(120)]
    d, c = _daily_from_weekly(weekly)
    base = [w.state for w in hz.medium_series(d, c)]
    noisy = list(c)
    for i in range(len(noisy)):
        if d[i].weekday() != 4:
            noisy[i] *= rng.uniform(0.85, 1.20)
    assert [w.state for w in hz.medium_series(d, noisy)] == base


def test_medium_open_week_is_not_folded_and_holiday_friday_closes_next_week():
    d, c = _daily_from_weekly([100.0] * 41)
    wed = d[-3]                                         # thứ Tư tuần cuối
    ws = hz.medium_series(d[:-2], c[:-2])
    assert ws[-1].week_end < wed                        # tuần dở bị bỏ
    assert hz.medium_series(d[:-2], c[:-2], include_open_week=True)[-1].week_end == wed
    thu = d[-2]                                         # thứ Sáu nghỉ: bar cuối = thứ Năm
    assert not hz.week_is_closed(thu, thu)
    assert hz.week_is_closed(thu, thu + timedelta(days=4))
    assert hz.medium_effective_from(thu, thu + timedelta(days=4)) == thu + timedelta(days=4)


def test_weekly_bars_skips_empty_tet_week():
    days = _weekdays(date(2026, 2, 2), 5) + _weekdays(date(2026, 2, 16), 5)
    wk = hz.weekly_bars(days, list(range(10)))
    assert [w[0] for w in wk] == [date(2026, 2, 6), date(2026, 2, 20)]


def test_medium_daily_maps_states_from_effective_dates():
    d, c = _daily_from_weekly([100.0] * 40 + [90])
    ws = hz.medium_series(d, c)
    daily = hz.medium_daily(d, ws)
    assert daily[-1] == GIAM and daily[-2] == DI_NGANG  # đổi đúng phiên thứ Sáu


def test_dedupe_daily_keeps_last_copy_and_sorts():
    ds, cs = hz.dedupe_daily([date(2026, 1, 2), date(2026, 1, 1), date(2026, 1, 2)],
                             [10.0, 5.0, 11.0])
    assert ds == [date(2026, 1, 1), date(2026, 1, 2)] and cs == [5.0, 11.0]


# ── Mức kích hoạt ────────────────────────────────────────────────────────

def test_trigger_levels_28_08_solves_both_constraints():
    lv = {l.kind: l for l in hz.trigger_levels(W_TO_0821, DI_NGANG, 1768.12, 1927.94)}
    assert lv["to_tang"].price == pytest.approx(1841.56, abs=0.05)   # cắt MA thắng
    assert lv["to_giam"].price == pytest.approx(1749.84, abs=0.05)
    assert lv["to_tang"].reachable and lv["to_giam"].reachable


def test_trigger_levels_leave_giam_takes_the_easier_constraint():
    (lv,) = hz.trigger_levels(W_TO_1002, GIAM, 1737.71, 1927.94)
    assert lv.kind == "leave_giam" and lv.price == pytest.approx(1803.15, abs=0.05)


def test_trigger_levels_unreachable_beyond_gap_or_52w_high():
    (up,) = [l for l in hz.trigger_levels(W_TO_1002, DI_NGANG, 1737.71, 1927.94)
             if l.kind == "to_tang"]
    assert up.price == pytest.approx(1995.4, abs=0.5) and not up.reachable
    (lv,) = hz.trigger_levels(W_TO_1002, GIAM, 1737.71, high_52w=1790.0)
    assert not lv.reachable                              # mức > đỉnh 52 tuần


def test_trigger_levels_need_enough_history():
    assert hz.trigger_levels(W_TO_0821[:20], DI_NGANG, 1768.12, 1927.94) == []


@pytest.mark.parametrize("seed", range(5))
def test_trigger_levels_agree_with_the_reading_rule(seed):
    """X ngay trên/dưới mức giải ra phải cho đúng lần đọc của luật tuần."""
    rng = random.Random(seed)
    prior = [1500 + rng.uniform(-150, 150) for _ in range(39)]
    p = hz.MediumParams(fuse=None)

    def reading(x):
        w = prior + [x]
        return hz.medium_reading(x, sum(w[-10:]) / 10, sum(w[-40:]) / 40, p.band)

    lv = {l.kind: l.price for l in hz.trigger_levels(prior, DI_NGANG, prior[-1], 9e9, p)}
    assert reading(lv["to_tang"] + 0.01) == TANG and reading(lv["to_tang"] - 0.01) != TANG
    assert reading(lv["to_giam"] - 0.01) == GIAM and reading(lv["to_giam"] + 0.01) != GIAM


def test_trigger_level_leave_tang_includes_fuse():
    prior = [100.0] * 30 + [110, 115, 120, 125, 126, 127, 128, 129, 130]
    (with_fuse,) = hz.trigger_levels(prior, TANG, 130, 130)
    (no_fuse,) = hz.trigger_levels(prior, TANG, 130, 130, hz.MediumParams(fuse=None))
    assert with_fuse.price == pytest.approx(0.92 * 130)
    assert no_fuse.price < with_fuse.price


# ── 🚨 ───────────────────────────────────────────────────────────────────

def _tiers(closes):
    return [a.tier for a in hz.alert_series(closes)]


@pytest.mark.parametrize("tail", [
    [99.0, 98.0, 97.0, 96.0, 94.9],     # sụt ≥5% từ đỉnh 20 phiên
    [97.4],                             # một phiên ≤ −2.5%
    [99.0, 98.0, 95.9],                 # ba phiên cộng ≤ −4%
])
def test_alert_onset_conditions(tail):
    t = _tiers([100.0] * 25 + tail)
    assert t[-1] == 1 and t[24] == 0


def test_alert_anchor_is_fixed_and_tier2_and_dwell():
    closes = [100.0] * 25 + [97.0, 96.0, 95.0, 94.0, 89.9]
    days = hz.alert_series(closes)
    assert days[25].onset and days[25].anchor == 100.0
    assert days[-1].tier == 2 and days[-1].anchor == 100.0
    # hồi ngay về 99 nhưng chưa đủ 5 phiên ⇒ chưa tắt
    t = _tiers([100.0] * 25 + [97.0, 99.0, 99.5])
    assert t[-1] == 1


def test_alert_turns_off_after_dwell_when_back_near_anchor():
    t = _tiers([100.0] * 25 + [96.0] * 6 + [96.5])
    assert t[-1] == 1                                    # 96.5 < 97% neo
    t = _tiers([100.0] * 25 + [96.0] * 6 + [97.1])
    assert t[-1] == 0                                    # ≥ 97% neo, đã ≥5 phiên
    t = _tiers([100.0] * 25 + [96.0, 97.2, 97.2])
    assert t[-1] == 1                                    # về gần neo nhưng chưa đủ 5 phiên


def test_alert_does_not_switch_off_when_peak_rolls_out_of_window():
    closes = [100.0] * 25 + [94.0] + [93.0] * 30          # đỉnh 100 trôi khỏi 20 phiên
    assert _tiers(closes)[-1] >= 1


# ── Bảo vệ + Stance ──────────────────────────────────────────────────────

def test_protection_hard_is_superset_of_old_floor():
    for s in (HOI, CHUA_RO, CHINH):
        for m in (TANG, DI_NGANG, GIAM):
            for a in (0, 1, 2):
                assert hz.protection_level(STANCE_DOWN, s, m, a) == hz.PROTECT_HARD


def test_protection_grades():
    assert hz.protection_level(None, HOI, TANG, 0) is None
    assert hz.protection_level(None, HOI, GIAM, 0) == hz.PROTECT_SOFT
    assert hz.protection_level(None, CHUA_RO, DI_NGANG, 1) == hz.PROTECT_SOFT
    assert hz.protection_level(None, CHINH, GIAM, 0) == hz.PROTECT_HARD
    assert hz.protection_level(STANCE_UP, CHINH, DI_NGANG, 2) == hz.PROTECT_HARD


def test_stance_table():
    r = hz.stance_rule(HOI, TANG, 0)
    assert r.forced == STANCE_UP
    r = hz.stance_rule(HOI, TANG, 1)
    assert r.forced is None and STANCE_UP in r.allowed
    r = hz.stance_rule(CHUA_RO, TANG, 1)
    assert STANCE_UP not in r.allowed
    for m in (DI_NGANG, GIAM):
        r = hz.stance_rule(HOI, m, 0)
        assert r.forced is None and STANCE_UP not in r.allowed and r.default == STANCE_FLAT
    for m in (TANG, DI_NGANG, GIAM):
        assert hz.stance_rule(CHINH, m, 0).forced == STANCE_DOWN


def test_stance_down_only_excluded_in_the_forced_up_cell_and_up_only_in_uptrend():
    """GIẢM chỉ vắng ở ô ép TĂNG (hồi × TĂNG × 🚨 tắt) — ô đó cần 🚨 tắt, tức
    không có cú rơi nhanh nào; mọi phiên có 🚨 đều được GIẢM."""
    for s in (HOI, CHUA_RO, CHINH):
        for m in (TANG, DI_NGANG, GIAM):
            for a in (0, 1, 2):
                r = hz.stance_rule(s, m, a)
                if (s, m, a) != (HOI, TANG, 0):
                    assert STANCE_DOWN in r.allowed
                if a > 0:
                    assert STANCE_DOWN in r.allowed
                if STANCE_UP in r.allowed:
                    assert m == TANG
