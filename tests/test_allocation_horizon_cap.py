"""P1b-2 (#20) — kẹp tỷ trọng theo trung hạn + 3 vá allocation.

Kẹp (§3.8, câu 14 = B): trung hạn KHÁC TĂNG hoặc 🚨 bật mà % cổ phiếu mới CAO
hơn % hiệu lực hôm trước ⇒ giữ nguyên band + bảng % cũ; giảm luôn đi qua. Hết
kẹp ⇒ tăng ≤1 bậc/tuần, báo trước ⏳ 1 tuần. Vá 1: mỗi lần đổi band ≤1 bậc.
Vá 2: nút dashboard giữa phiên chỉ tính, không ghi. Vá 3: pending vào history.
"""
from __future__ import annotations

import json

import pytest

import vnstock_allocation as alloc

TANG, DI_NGANG, GIAM = 1, 0, -1
_TABLE = alloc._DEFAULT_ALLOCATIONS


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_ALLOC"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(alloc, "_load_report_tilt", lambda as_of: None)


def _st(band: str, as_of: str, *, pct: "int | None" = None, **extra) -> dict:
    """State hiệu lực tối thiểu: band + bảng % (pct ghi đè % cổ phiếu khi tilt trộn dở)."""
    a = dict(_TABLE[band])
    if pct is not None:
        a["Cổ phiếu"] = pct
    return {"as_of": as_of, "band": band, "band_data": band, "band_label": alloc._BAND_LABELS[band],
            "raw_band": band, "pending": None, "allocation": a, **extra}


def _hz(medium: int, alert: int = 0) -> dict:
    return {"as_of": "x", "medium": medium, "alert_tier": alert}


# ── Kẹp ──────────────────────────────────────────────────────────────────────

def test_case_27_08_flat_trend_holds_15_pct_instead_of_jumping_to_b3():
    prev = _st("B4", "2026-08-26")
    out = alloc.apply_horizon_cap(_st("B3", "2026-08-27"), prev, _hz(DI_NGANG), "2026-08-27")
    assert out["band"] == "B4" and out["allocation"]["Cổ phiếu"] == 15
    cap = out["capped_by"]
    assert cap["by"] == "horizons" and cap["proposed_band"] == "B3" and cap["proposed_pct"] == 30
    assert "ĐI NGANG" in cap["why"]
    assert out["band_data"] == "B3"            # band DATA vẫn đi tiếp — chỉ band hiệu lực bị giữ


def test_tilt_fade_drift_is_blocked_when_trend_is_down():
    prev = _st("B4", "2026-10-04")                       # 15%
    fading = _st("B4", "2026-10-05", pct=28)             # tilt phai: 15 → ~28% cùng band
    out = alloc.apply_horizon_cap(fading, prev, _hz(GIAM), "2026-10-05")
    assert out["allocation"]["Cổ phiếu"] == 15 and out["capped_by"]["proposed_pct"] == 28
    assert "GIẢM" in out["capped_by"]["why"]


def test_alert_blocks_increase_even_in_uptrend():
    out = alloc.apply_horizon_cap(_st("B3", "2026-10-06"), _st("B4", "2026-10-05"),
                                  _hz(TANG, alert=1), "2026-10-06")
    assert out["allocation"]["Cổ phiếu"] == 15 and "🚨" in out["capped_by"]["why"]


@pytest.mark.parametrize("medium,alert", [(GIAM, 1), (DI_NGANG, 0), (TANG, 0)])
def test_decrease_always_goes_through(medium, alert):
    out = alloc.apply_horizon_cap(_st("B4", "2026-10-06"), _st("B2", "2026-10-05"),
                                  _hz(medium, alert), "2026-10-06")
    assert out["band"] == "B4" and out["allocation"]["Cổ phiếu"] == 15
    assert not out.get("capped_by") and not out.get("ramp")


def test_unusable_horizon_state_means_no_cap_with_a_note():
    out = alloc.apply_horizon_cap(_st("B3", "2026-10-06"), _st("B4", "2026-10-05"),
                                  None, "2026-10-06", note="cũ: bản cuối 2026-10-02")
    assert out["allocation"]["Cổ phiếu"] == 30 and not out.get("capped_by")
    assert out["horizon_note"] == "cũ: bản cuối 2026-10-02"


def test_first_run_without_previous_state_is_not_capped():
    out = alloc.apply_horizon_cap(_st("B2", "2026-10-06"), None, _hz(GIAM), "2026-10-06")
    assert out["allocation"]["Cổ phiếu"] == 45 and not out.get("capped_by")


# ── Hết kẹp: ≤1 bậc/tuần, ⏳ báo trước 1 tuần ─────────────────────────────────

def test_uptrend_increase_is_announced_then_steps_one_band_per_week():
    prev = _st("B4", "2026-11-02")
    d0 = alloc.apply_horizon_cap(_st("B2", "2026-11-03"), prev, _hz(TANG), "2026-11-03")
    assert d0["band"] == "B4" and d0["allocation"]["Cổ phiếu"] == 15
    assert d0["ramp"] == {"band": "B2", "since": "2026-11-03"}          # ⏳ báo trước

    d3 = alloc.apply_horizon_cap(_st("B2", "2026-11-06"), d0, _hz(TANG), "2026-11-06")
    assert d3["band"] == "B4" and d3["ramp"]["since"] == "2026-11-03"

    d7 = alloc.apply_horizon_cap(_st("B2", "2026-11-10"), d3, _hz(TANG), "2026-11-10")
    assert d7["band"] == "B3" and d7["allocation"] == _TABLE["B3"]       # đúng 1 bậc
    assert d7["ramp"] == {"band": "B2", "since": "2026-11-10"}          # bậc kế: thêm 1 tuần

    d14 = alloc.apply_horizon_cap(_st("B2", "2026-11-17"), d7, _hz(TANG), "2026-11-17")
    assert d14["band"] == "B2" and d14["allocation"] == _TABLE["B2"] and not d14.get("ramp")


def test_ramp_is_dropped_when_the_proposal_falls_back():
    prev = _st("B4", "2026-11-03", ramp={"band": "B3", "since": "2026-11-03"})
    out = alloc.apply_horizon_cap(_st("B4", "2026-11-05"), prev, _hz(TANG), "2026-11-05")
    assert out["band"] == "B4" and not out.get("ramp")


def test_kill_switch_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("VNSTOCK_ALLOC_HORIZON_CAP", "0")
    out = alloc.apply_horizon_cap(_st("B2", "2026-10-06"), _st("B4", "2026-10-05"),
                                  _hz(GIAM, alert=2), "2026-10-06")
    assert out["band"] == "B2" and out["allocation"]["Cổ phiếu"] == 45
    assert not out.get("capped_by") and not out.get("ramp")


# ── Vá 1: mỗi lần đổi band ≤1 bậc ────────────────────────────────────────────

@pytest.mark.parametrize("cur,score,expect", [
    ("B4", 0.9, "B3"),    # điểm nhảy tới B0 → chỉ lên 1 bậc
    ("B0", -0.9, "B1"),   # điểm rơi tới B4 → chỉ xuống 1 bậc
])
def test_hysteresis_moves_at_most_one_band_per_change(cur, score, expect):
    prev = {"band": cur, "pending": {"band": expect, "dates": ["2026-10-05"]}}
    assert alloc.apply_hysteresis(prev, score, "2026-10-06")["band"] == expect


def test_one_step_kill_switch_allows_the_old_two_band_jump(monkeypatch):
    monkeypatch.setenv("VNSTOCK_ALLOC_ONE_STEP", "0")
    prev = {"band": "B4", "pending": {"band": "B0", "dates": ["2026-10-05"]}}
    assert alloc.apply_hysteresis(prev, 0.9, "2026-10-06")["band"] == "B0"


# ── Vá 3: pending (+ kẹp, ⏳) vào history ─────────────────────────────────────

def test_history_entry_keeps_pending_cap_and_ramp():
    st = _st("B4", "2026-10-06", pending={"band": "B3", "dates": ["2026-10-06"]},
             capped_by={"by": "horizons", "why": "trung hạn GIẢM", "proposed_band": "B3",
                        "proposed_pct": 30},
             ramp=None, score=-0.4, inputs=[])
    h = alloc._history_entry(st)
    assert h["pending"] == {"band": "B3", "dates": ["2026-10-06"]}
    assert h["capped_by"]["proposed_pct"] == 30 and h["ramp"] is None


# ── run_allocation: đọc state 3 khung, ghi kẹp; persist=False không ghi (Vá 2) ─

@pytest.fixture()
def _io(tmp_path, monkeypatch):
    monkeypatch.setattr(alloc, "_STATE", tmp_path / "allocation_state.json")
    monkeypatch.setattr(alloc, "_CONFIG", tmp_path / "allocation_config.json")
    monkeypatch.setattr(alloc, "collect_inputs", lambda effective_date=None: (
        "2026-10-06", {"regime": {"score": 6, "value": "+6"},
                       "sentiment": {"momentum": 80, "value": "+80"}}))
    return tmp_path


def test_run_allocation_applies_the_cap_from_horizon_state(_io, monkeypatch):
    # hysteresis đã chờ 1 phiên đổi sang B3 ⇒ hôm nay xác nhận B3 (30%) — kẹp phải giữ 15%
    alloc._write_state(_st("B4", "2026-10-05", history=[],
                           pending={"band": "B3", "dates": ["2026-10-05"]}))
    monkeypatch.setattr(alloc, "_load_horizon", lambda: (_hz(GIAM), None))
    st = alloc.run_allocation()
    assert st["allocation"]["Cổ phiếu"] == 15 and st["capped_by"]["by"] == "horizons"
    saved = json.loads(alloc._STATE.read_text(encoding="utf-8"))
    assert saved["capped_by"]["proposed_band"] == "B3" and saved["band_data"] == "B3"
    assert saved["history"][-1]["capped_by"]["by"] == "horizons"


def test_run_allocation_persist_false_computes_without_writing(_io, monkeypatch):
    monkeypatch.setattr(alloc, "_load_horizon", lambda: (None, "chưa có state"))
    st = alloc.run_allocation(persist=False)
    assert st is not None and not alloc._STATE.exists()


def test_dashboard_refresh_does_not_persist_intraday(monkeypatch):
    from dashboard import allocation_tab
    calls = []
    monkeypatch.setattr(alloc, "run_allocation", lambda **k: calls.append(k) or {})
    monkeypatch.setattr(allocation_tab, "_overview_is_intraday", lambda: True)
    assert allocation_tab._refresh_allocation()[0] is False
    monkeypatch.setattr(allocation_tab, "_overview_is_intraday", lambda: False)
    assert allocation_tab._refresh_allocation()[0] is True
    assert calls == [{"persist": False}, {"persist": True}]


# ── Brief: dòng band nói rõ kẹp đang giữ (code dựng, guard ghim) ──────────────

def test_brief_band_lines_explain_the_cap_and_the_ramp():
    from vnstock_brief import _allocation_table_lines, _macro_reports_body_lines
    capped = {**_st("B4", "2026-10-06"), "score": -0.31,
              "capped_by": {"by": "horizons", "why": "trung hạn GIẢM",
                            "proposed_band": "B3", "proposed_pct": 30}}
    band_line = _macro_reports_body_lines({"allocation": capped})[0]
    assert band_line.startswith("- 🧭 Band phân bổ tháng: B4")
    assert band_line.endswith("; giữ nguyên vì trung hạn GIẢM — band dữ liệu đề xuất B3 (30% cổ phiếu)")
    assert _allocation_table_lines(capped)[-1].endswith("band dữ liệu đề xuất B3 (30% cổ phiếu)")
    ramping = {**_st("B4", "2026-11-04"), "score": 0.2,
               "ramp": {"band": "B2", "since": "2026-11-03"}}
    assert _macro_reports_body_lines({"allocation": ramping})[0].endswith(
        "; ⏳ chờ lên B2 — mỗi tuần tối đa 1 bậc, tính từ 2026-11-03")
    plain = {**_st("B4", "2026-10-06"), "score": -0.6}
    assert "giữ nguyên" not in _macro_reports_body_lines({"allocation": plain})[0]
