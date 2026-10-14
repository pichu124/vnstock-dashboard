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
_REAL_OVERVIEW_INTRADAY = alloc.overview_intraday     # fixture autouse chặn bản thật


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_ALLOC"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(alloc, "_load_report_tilt", lambda as_of: None)
    monkeypatch.setattr(alloc, "overview_intraday", lambda as_of=None: False)


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

def test_case_27_08_flat_trend_is_announced_a_week_ahead_not_jumped():
    """Câu 14 = A (14/10, #27): ĐI NGANG không bị CẤM tăng — nhưng không nhảy ngay
    B4 → B3: ⏳ báo trước 1 tuần rồi mới lên (cú 27/08 không còn tăng trong đêm)."""
    prev = _st("B4", "2026-08-26")
    out = alloc.apply_horizon_cap(_st("B3", "2026-08-27"), prev, _hz(DI_NGANG), "2026-08-27")
    assert out["band"] == "B4" and out["allocation"]["Cổ phiếu"] == 15
    assert not out.get("capped_by")
    assert out["ramp"] == {"band": "B3", "pct": 30, "since": "2026-08-27"}
    assert out["band_data"] == "B3"            # band DATA vẫn đi tiếp — chỉ band hiệu lực chờ


def test_unknown_medium_is_held_like_a_downtrend():
    out = alloc.apply_horizon_cap(_st("B3", "2026-10-06"), _st("B4", "2026-10-05"),
                                  _hz(None), "2026-10-06")
    assert out["allocation"]["Cổ phiếu"] == 15 and "trung hạn ?" in out["capped_by"]["why"]


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
    assert d0["ramp"] == {"band": "B2", "pct": 45, "since": "2026-11-03"}   # ⏳ báo trước

    d3 = alloc.apply_horizon_cap(_st("B2", "2026-11-06"), d0, _hz(TANG), "2026-11-06")
    assert d3["band"] == "B4" and d3["ramp"]["since"] == "2026-11-03"

    d7 = alloc.apply_horizon_cap(_st("B2", "2026-11-10"), d3, _hz(TANG), "2026-11-10")
    assert d7["band"] == "B3" and d7["allocation"] == _TABLE["B3"]       # đúng 1 bậc
    assert d7["ramp"] == {"band": "B2", "pct": 45, "since": "2026-11-10"}   # bậc kế: thêm 1 tuần

    d14 = alloc.apply_horizon_cap(_st("B2", "2026-11-17"), d7, _hz(TANG), "2026-11-17")
    assert d14["band"] == "B2" and d14["allocation"] == _TABLE["B2"] and not d14.get("ramp")


def test_ramp_counts_equity_points_not_band_labels():
    """Review #20: tilt trôi 30→37% CÙNG band B3 cũng là tăng ⇒ ⏳ 1 tuần; mỗi
    tuần ≤ một bậc của bảng (B3 30% → trần B2 45%), không +22 điểm trong 8 ngày."""
    prev = _st("B3", "2026-11-02")
    d0 = alloc.apply_horizon_cap(_st("B3", "2026-11-03", pct=37), prev, _hz(TANG), "2026-11-03")
    assert d0["allocation"]["Cổ phiếu"] == 30 and d0["ramp"]["since"] == "2026-11-03"
    d7 = alloc.apply_horizon_cap(_st("B3", "2026-11-10", pct=37), d0, _hz(TANG), "2026-11-10")
    assert d7["allocation"]["Cổ phiếu"] == 37 and not d7.get("ramp")    # ≤ trần 45% ⇒ đi qua
    d8 = alloc.apply_horizon_cap(_st("B2", "2026-11-11", pct=52), d7, _hz(TANG), "2026-11-11")
    assert d8["allocation"]["Cổ phiếu"] == 37 and d8["ramp"]["since"] == "2026-11-11"
    d15 = alloc.apply_horizon_cap(_st("B2", "2026-11-18", pct=52), d8, _hz(TANG), "2026-11-18")
    assert d15["band"] == "B2" and d15["allocation"] == _TABLE["B2"]     # trần 1 bậc: 45%
    assert d15["ramp"]["since"] == "2026-11-18"


@pytest.mark.parametrize("held", [
    {"capped_by": {"by": "horizons", "why": "trung hạn GIẢM", "proposed_band": "B2",
                   "proposed_pct": 45}},
    {"ramp": {"band": "B2", "pct": 45, "since": "2026-10-01"}},
])
def test_unusable_state_while_holding_ramps_instead_of_releasing_the_gap(held):
    """Review #20: state 3 khung cũ/hỏng một đêm mà xả cả khoảng B4→B2 thì đêm sau
    GIẢM cũng không kéo lại được (kẹp chỉ so % hôm trước) ⇒ đi theo ⏳ 1 bậc/tuần."""
    prev = {**_st("B4", "2026-10-05"), "band_data": "B2", **held}
    out = alloc.apply_horizon_cap(_st("B2", "2026-10-06"), prev, None, "2026-10-06",
                                  note="cũ: bản cuối 2026-10-02")
    assert out["band"] == "B4" and out["allocation"]["Cổ phiếu"] == 15
    assert out["ramp"]["band"] == "B2" and out["horizon_note"] == "cũ: bản cuối 2026-10-02"
    assert out["ramp"]["since"] == (held.get("ramp") or {}).get("since", "2026-10-06")


def test_decrease_goes_through_while_the_cap_is_holding():
    prev = {**_st("B3", "2026-10-05"), "band_data": "B1",
            "capped_by": {"by": "horizons", "why": "trung hạn GIẢM", "proposed_band": "B1",
                          "proposed_pct": 60}}
    out = alloc.apply_horizon_cap(_st("B4", "2026-10-06"), prev, _hz(GIAM, 1), "2026-10-06")
    assert out["band"] == "B4" and out["allocation"]["Cổ phiếu"] == 15
    assert not out.get("capped_by")


def test_held_tilt_is_not_reported_as_applied():
    """Review #20: bảng bị giữ KHÔNG phải bảng trộn tilt hôm nay ⇒ report_tilt = None
    (history/scorecard không ghi tilt chưa áp), nhãn tilt đi vào capped_by."""
    st = _st("B3", "2026-10-06", pct=37)
    st["band_data"] = "B4"
    st["report_tilt"] = {"tilt": -1, "strength": 0.6, "label": "-1 band × 60% (B4→B3, báo cáo cũ dần)"}
    out = alloc.apply_horizon_cap(st, _st("B4", "2026-10-05"), _hz(GIAM), "2026-10-06")
    assert out["allocation"]["Cổ phiếu"] == 15 and out["report_tilt"] is None
    assert out["capped_by"]["tilt"] == "-1 band × 60% (B4→B3, báo cáo cũ dần)"
    assert alloc._history_entry({**out, "score": 0, "inputs": []})["tilt"] == 0


def test_ramp_is_dropped_when_the_proposal_falls_back():
    prev = _st("B4", "2026-11-03", ramp={"band": "B3", "pct": 30, "since": "2026-11-03"})
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
    assert h["horizon_note"] is None
    assert alloc._history_entry({**st, "horizon_note": "cũ"})["horizon_note"] == "cũ"


def test_off_values_match_the_doctor_kill_switch_check():
    import vnstock_doctor
    assert alloc._OFF_VALUES == vnstock_doctor._OFF_VALUES


class _LP:
    def __init__(self, usable, reason="", snap=None):
        self.usable, self.reason, self.snap = usable, reason, snap


def test_load_horizon_reads_medium_and_alert_or_returns_the_reason(monkeypatch):
    import vnstock_horizons_state as hs
    monkeypatch.setattr(hs, "latest_published", lambda wh=None, now=None: _LP(
        True, snap={"as_of": "2026-10-10", "medium": -1, "alert": {"tier": 1}}))
    assert alloc._load_horizon() == ({"as_of": "2026-10-10", "medium": -1, "alert_tier": 1}, None)
    monkeypatch.setattr(hs, "latest_published", lambda wh=None, now=None: _LP(
        False, reason="cũ: bản cuối 2026-10-02"))
    assert alloc._load_horizon() == (None, "cũ: bản cuối 2026-10-02")
    monkeypatch.setattr(hs, "latest_published", lambda wh=None, now=None: 1 / 0)
    hz, why = alloc._load_horizon()
    assert hz is None and "ZeroDivisionError" in why


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


@pytest.mark.parametrize("intraday,written", [(True, False), (False, True), (None, True)])
def test_run_allocation_never_writes_from_an_intraday_overview(_io, monkeypatch, intraday, written):
    """Vá 2 ở MỌI đường gọi (nút 🧩 chạy `run.py all --no-sync` giữa phiên cũng
    vào đây); không xác định được ⇒ pipeline vẫn ghi (đêm overview đã chốt)."""
    monkeypatch.setattr(alloc, "_load_horizon", lambda: (None, "chưa có state"))
    monkeypatch.setattr(alloc, "overview_intraday", lambda as_of=None: intraday)
    st = alloc.run_allocation()
    assert alloc._STATE.exists() is written
    assert st.get("preview_only") == (None if written else "intraday")


def test_overview_intraday_reads_the_meta_overview(tmp_path, monkeypatch):
    monkeypatch.setattr(alloc, "_META", tmp_path)
    (tmp_path / "market_overview.json").write_text(json.dumps(
        {"data_date": "2026-10-06", "generated_at": "2026-10-06T11:02:00"}), encoding="utf-8")
    assert _REAL_OVERVIEW_INTRADAY("2026-10-06") is True
    (tmp_path / "market_overview.json").write_text(json.dumps(
        {"data_date": "2026-10-06", "generated_at": "2026-10-06T18:40:00"}), encoding="utf-8")
    assert _REAL_OVERVIEW_INTRADAY("2026-10-06") is False


@pytest.mark.parametrize("intraday,persist", [(True, False), (False, True), (None, False)])
def test_dashboard_refresh_persists_only_when_surely_after_close(monkeypatch, intraday, persist):
    from dashboard import allocation_tab
    calls = []
    monkeypatch.setattr(alloc, "run_allocation", lambda **k: calls.append(k) or {})
    monkeypatch.setattr(alloc, "overview_intraday", lambda as_of=None: intraday)
    assert allocation_tab._refresh_allocation()[0] is persist      # lỗi ⇒ KHÔNG ghi
    assert calls == [{"persist": persist}]


def test_dashboard_first_run_button_also_goes_through_the_intraday_gate():
    import inspect
    from dashboard import allocation_tab
    src = inspect.getsource(allocation_tab)
    assert "alloc.run_allocation(" not in src.replace("alloc.run_allocation(persist=", "")


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
    ramping["ramp"]["pct"] = 45
    assert _macro_reports_body_lines({"allocation": ramping})[0].endswith(
        "; ⏳ chờ lên B2 (45% cổ phiếu) — mỗi tuần tối đa 1 bậc, tính từ 2026-11-03")
    tilted = {**capped, "band_data": "B4",
              "capped_by": {**capped["capped_by"], "proposed_pct": 37, "tilt": "-1 band × 60%"}}
    assert _allocation_table_lines(tilted)[-1].endswith(
        "giữ nguyên vì trung hạn GIẢM — band dữ liệu B4 + tilt -1 band × 60% đề xuất B3 "
        "(37% cổ phiếu)")
    no_pct = {**capped, "capped_by": {**capped["capped_by"], "proposed_pct": None}}
    assert _allocation_table_lines(no_pct)[-1].endswith("band dữ liệu đề xuất B3")
    plain = {**_st("B4", "2026-10-06"), "score": -0.6}
    assert "giữ nguyên" not in _macro_reports_body_lines({"allocation": plain})[0]
