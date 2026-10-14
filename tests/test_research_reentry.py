"""#27 (nghiên cứu) — lõi mô phỏng của `scripts/research_reentry.py` trên chuỗi
tổng hợp: tín hiệu A/B/C, đáy ≥15%, kẹp giữ tỷ trọng, mỗi hướng mở ĐÚNG 1 bậc,
ca kiểu 27/08 (ĐI NGANG, 🚨 tắt, không sâu, không lực đẩy) không mở.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

import vnstock_horizons as hz

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location(
        "research_reentry", _REPO / "scripts" / "research_reentry.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod            # @dataclass cần module đã đăng ký
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def _days(rr, closes, scores, mediums, tiers, ratios=None):
    d0 = date(2025, 1, 1)
    ratios = ratios or [0.5] * len(closes)
    return [rr.Day(d0 + timedelta(days=i), c, s, m, t, r)
            for i, (c, s, m, t, r) in enumerate(zip(closes, scores, mediums, tiers, ratios))]


def _v_shape(rr, medium_after=hz.DI_NGANG, tier_after=0, n=120):
    """Đỉnh 1000 → đáy 750 (−25%) phiên 40 → hồi chữ V về 980; dữ liệu band tốt
    lên ngay sau đáy, trung hạn GIẢM rồi ĐI NGANG từ phiên 70, 🚨 tắt từ phiên 50."""
    closes = [1000.0] * 10 + [1000 - 250 * k / 30 for k in range(1, 31)] + \
             [750 + 230 * k / (n - 40) for k in range(1, n - 39)]
    scores = [0.6] * 10 + [-0.8] * 35 + [0.6] * (n - 45)
    mediums = [hz.TANG] * 15 + [hz.GIAM] * 55 + [medium_after] * (n - 70)
    tiers = [0] * 12 + [1] * 38 + [tier_after] * (n - 50)
    return _days(rr, closes[:n], scores[:n], mediums[:n], tiers[:n])


def test_thrust_needs_a_fast_swing_from_below_40_to_above_61_5(rr):
    ratios = [0.35] * 15 + [0.9] * 10
    days = _days(rr, [1000.0] * 25, [0.0] * 25, [hz.DI_NGANG] * 25, [0] * 25, ratios)
    flags = rr.thrust_days(days)
    assert any(flags[15:]) and not any(flags[:15])
    slow = [0.35] * 15 + [0.55] * 30 + [0.9] * 10
    days = _days(rr, [1000.0] * 55, [0.0] * 55, [hz.DI_NGANG] * 55, [0] * 55, slow)
    assert not any(rr.thrust_days(days))                # từ <40% mà quá 10 phiên mới lên


def test_troughs_find_the_v_bottom(rr):
    days = _v_shape(rr)
    (t, e), = rr.troughs(days)
    assert days[t].close == pytest.approx(750.0) and e > t


def test_cap_holds_low_equity_while_nocap_climbs_back(rr):
    days = _v_shape(rr)
    nocap, cap = rr.simulate(days, "nocap"), rr.simulate(days, "capB")
    assert nocap[-1] > cap[-1] == 15.0                  # kẹp giữ đáy vì trung hạn chưa TĂNG
    assert max(nocap[60:]) >= 60


@pytest.mark.parametrize("variant", ["B", "C"])
def test_reentry_variants_open_exactly_one_band(rr, variant):
    days = _v_shape(rr)
    cap, eq = rr.simulate(days, "capB"), rr.simulate(days, variant)
    after = eq[45:]                                     # sau cú sập (band đã về B4)
    assert max(after) - cap[-1] == 15.0                 # đúng +1 bậc (B4 15% → B3 30%)
    ups = [i for i in range(1, len(after)) if after[i] > after[i - 1]]
    assert len(ups) == 1


def test_alert_on_blocks_b_and_c(rr):
    days = _v_shape(rr, tier_after=1)
    assert rr.simulate(days, "B") == rr.simulate(days, "capB")
    assert rr.simulate(days, "C") == rr.simulate(days, "capB")


def test_case_like_27_08_keeps_15_percent(rr):
    """ĐI NGANG, 🚨 tắt, không sụt sâu, độ rộng bình thường, band dữ liệu B4→B3."""
    n = 40
    days = _days(rr, [1800.0 + k for k in range(n)], [-0.6] * 20 + [-0.4] * 20,
                 [hz.DI_NGANG] * n, [0] * n, [0.5] * n)
    for v in ("A", "B", "C"):
        assert rr.simulate(days, v) == rr.simulate(days, "capB")
    assert rr.simulate(days, "capB")[-1] == 15.0 and rr.simulate(days, "nocap")[-1] == 30.0


def test_current_cap_lets_a_flat_trend_raise_equity_but_still_holds_in_a_downtrend(rr):
    """Luật đang chạy (Câu 14 = A từ 14/10): ĐI NGANG được tăng (dần), GIẢM vẫn giữ như capB."""
    n = 40
    flat = _days(rr, [1800.0 + k for k in range(n)], [-0.6] * 20 + [-0.4] * 20,
                 [hz.DI_NGANG] * n, [0] * n, [0.5] * n)
    assert rr.simulate(flat, "cap")[-1] == rr.simulate(flat, "nocap")[-1] == 30.0
    assert rr.simulate(flat, "capB")[-1] == 15.0
    down = _days(rr, [1800.0 + k for k in range(n)], [-0.6] * 20 + [-0.4] * 20,
                 [hz.GIAM] * n, [0] * n, [0.5] * n)
    assert rr.simulate(down, "cap") == rr.simulate(down, "capB")
    assert rr.simulate(down, "cap")[-1] == 15.0


def test_report_renders_both_tables(rr):
    text = rr.report(_v_shape(rr))
    assert "## 1. Phần bị lỡ" in text and "## 2. So 3 hướng" in text
    assert "| cap |" in text and "| capB |" in text and "| C |" in text


# ── VNINDEX sâu hơn kho: nối trong bộ nhớ sau khi đối chiếu phần chồng ──────

def _wh_series(n=60, d0=date(2024, 1, 2)):
    dates = [d0 + timedelta(days=i) for i in range(n)]
    return dates, [1100.0 + i for i in range(n)]


def test_deepen_prepends_older_bars_when_the_overlap_matches(rr):
    dates, closes = _wh_series()
    old = {date(2023, 1, 2) + timedelta(days=i): 1000.0 + i for i in range(300)
           if date(2023, 1, 2) + timedelta(days=i) < dates[0]}
    src = {**old, **{d: c * 1.001 for d, c in zip(dates, closes)}}      # lệch 0.1% < 0.5%
    seen = {}

    def fetch(s, e):
        seen.update(start=s, end=e)
        return src
    d2, c2, why = rr.deepen_vnindex(dates, closes, date(2023, 1, 1), fetch=fetch)
    assert d2[0] == date(2023, 1, 2) and d2[len(old):] == dates and c2[len(old):] == closes
    assert "nối" in why and "không ghi kho" in why and seen["start"] == "2023-01-01"


@pytest.mark.parametrize("src_factor,expect", [(1.02, "lệch kho"), (None, "không lấy được")])
def test_deepen_refuses_a_shifted_source_or_a_failed_fetch(rr, src_factor, expect):
    dates, closes = _wh_series()

    def fetch(s, e):
        if src_factor is None:
            raise RuntimeError("timeout")
        older = {date(2023, 6, 1) + timedelta(days=i): 1000.0 for i in range(30)}
        return {**older, **{d: c * src_factor for d, c in zip(dates, closes)}}
    d2, c2, why = rr.deepen_vnindex(dates, closes, date(2023, 1, 1), fetch=fetch)
    assert (d2, c2) == (dates, closes) and expect in why


def test_deepen_is_a_no_op_when_the_warehouse_is_already_deep(rr):
    dates, closes = _wh_series()
    assert rr.deepen_vnindex(dates, closes, dates[0], fetch=lambda s, e: 1 / 0)[2] == "kho đã đủ sâu"


def test_thin_breadth_and_coverage(rr):
    b = {date(2018, 3, 1): {"total": 120}, date(2018, 3, 2): {"total": 140},
         date(2024, 3, 1): {"total": 1500}}
    assert list(rr.thin_breadth(b)) == [date(2024, 3, 1)]
    assert rr.coverage_by_year(b) == {2018: 140, 2024: 1500}


def test_report_prints_the_data_notes(rr):
    text = rr.report(_v_shape(rr), ["VNINDEX trong kho: X", "VNINDEX sâu hơn: nối 5 phiên"])
    assert "- VNINDEX trong kho: X" in text and "- VNINDEX sâu hơn: nối 5 phiên" in text


# ── #20: Vá 1 chỉ chặn chiều tăng (capCut) ──────────────────────────────────

def test_hysteresis_one_step_up_cuts_straight_down_but_still_climbs_one_band():
    import vnstock_allocation as alloc
    b1 = {"band": "B1", "pending": None}
    worst = -1.0                                         # điểm sâu nhất ⇒ bậc dữ liệu B4
    h1 = alloc.apply_hysteresis(b1, worst, "2026-01-05", one_step="up")
    h2 = alloc.apply_hysteresis({"band": h1["band"], "pending": h1["pending"]}, worst,
                                "2026-01-06", one_step="up")
    assert h1["band"] == "B1" and h2["band"] == "B4"     # 2 phiên xác nhận rồi cắt thẳng
    both = alloc.apply_hysteresis({"band": "B1", "pending": {"band": "B2",
                                   "dates": ["2026-01-05"]}}, worst, "2026-01-06", one_step="both")
    assert both["band"] == "B2"                          # cách cũ: từng bậc
    b4 = {"band": "B4", "pending": {"band": "B3", "dates": ["2026-01-05"]}}
    assert alloc.apply_hysteresis(b4, 1.0, "2026-01-06", one_step="up")["band"] == "B3"


def test_cap_cut_falls_faster_in_a_crash(rr):
    days = _v_shape(rr)
    cap, cut = rr.simulate(days, "cap"), rr.simulate(days, "capCut")
    first = lambda eq: next(i for i, v in enumerate(eq) if v == 15.0)
    assert first(cut) < first(cap)                      # chạm 15% sớm hơn


def test_report_has_the_crash_table(rr):
    text = rr.report(_v_shape(rr))
    assert "## 3. #20" in text and "| capCut |" in text and "Cắt rồi mua lại" in text
