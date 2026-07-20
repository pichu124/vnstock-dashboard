"""Tests for vnstock_allocation — Phase 1: band B0-B4 + hysteresis + state.

Pure core (compute_score / band_from_score / apply_hysteresis /
compute_allocation) chạy trên fixture tổng hợp; phần I/O (run_allocation,
collect_inputs) monkeypatch path + loader nên hermetic — không đọc cache repo,
không mạng, không LLM.
"""
import json
import sys
import types

import pytest

import vnstock_allocation as alloc


@pytest.fixture(autouse=True)
def _no_report_tilt(monkeypatch):
    """P3 thêm tilt ±1 band từ digest báo cáo — tắt trong file này để test
    core P1 hermetic (máy user có digest thật sẽ không làm lệch band kỳ
    vọng). Tilt được test riêng ở test_report_digest.py."""
    monkeypatch.setattr(alloc, "_load_report_tilt", lambda as_of: None)


def _mk_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _full_inputs(**over):
    """Bộ 7 input thô hợp lệ, trung tính-nhẹ; override từng key khi cần."""
    base = {
        "regime":         {"score": 1, "value": "score +1"},
        "sentiment":      {"momentum": 10, "value": "momentum +10/100"},
        "breadth":        {"above_ma200_pct": 50.0, "value": "50%"},
        "macro_pressure": {"score": 0.1, "value": "+0.10"},
        "liquidity":      {"dir": 0, "value": "spread +0.10"},
        "term":           {"dir": 0, "slope_dir": 0, "value": "spread +0.90"},
        "intl":           {"dir": 0, "value": "spread +0.30"},
    }
    base.update(over)
    return base


# ── band mapping ─────────────────────────────────────────────────────────────


def test_band_thresholds():
    assert alloc.band_from_score(0.9) == "B0"
    assert alloc.band_from_score(0.50) == "B0"     # biên thuộc band tấn công hơn
    assert alloc.band_from_score(0.3) == "B1"
    assert alloc.band_from_score(0.15) == "B1"
    assert alloc.band_from_score(0.0) == "B2"
    assert alloc.band_from_score(-0.149) == "B2"
    assert alloc.band_from_score(-0.3) == "B3"
    assert alloc.band_from_score(-0.6) == "B4"
    assert alloc.band_from_score(-1.0) == "B4"


def test_default_allocations_all_sum_to_100_and_cover_5_classes():
    for band, row in alloc._DEFAULT_ALLOCATIONS.items():
        assert set(row) == set(alloc._ASSET_CLASSES), band
        assert sum(row.values()) == 100, band


# ── compute_score: chuẩn hoá + renormalize ───────────────────────────────────


def test_compute_score_favorable_and_stress_directions():
    bull = alloc.compute_score(_full_inputs(
        regime={"score": 5}, sentiment={"momentum": 80},
        breadth={"above_ma200_pct": 70},
        macro_pressure={"score": 0.8},
        liquidity={"dir": 1}, term={"dir": 0, "slope_dir": 0}, intl={"dir": 0},
    ))
    assert bull["score"] > 0.5
    assert alloc.band_from_score(bull["score"]) == "B0"

    bear = alloc.compute_score(_full_inputs(
        regime={"score": -5}, sentiment={"momentum": -80},
        breadth={"above_ma200_pct": 18},
        macro_pressure={"score": -0.8},
        liquidity={"dir": -1}, term={"dir": -1, "slope_dir": -1},
        intl={"dir": -1},
    ))
    assert bear["score"] < -0.5
    assert alloc.band_from_score(bear["score"]) == "B4"


def test_compute_score_renormalizes_over_available_inputs():
    # Chỉ 1 input → weight hiệu dụng = 1.0, score = sub-score của nó
    out = alloc.compute_score({"sentiment": {"momentum": -50}})
    assert out["score"] == pytest.approx(-0.5)
    assert len(out["inputs"]) == 1
    assert out["inputs"][0]["weight"] == pytest.approx(1.0)


def test_compute_score_skips_malformed_input_and_returns_none_when_empty():
    out = alloc.compute_score({"regime": {"score": "x"},
                               "breadth": {"above_ma200_pct": 55}})
    assert [r["key"] for r in out["inputs"]] == ["breadth"]
    assert alloc.compute_score({}) is None
    assert alloc.compute_score({"unknown_key": {"dir": 1}}) is None


def test_compute_score_rows_carry_source_and_as_of():
    out = alloc.compute_score({"breadth": {
        "above_ma200_pct": 55, "value": "55% mã trên MA200",
        "source": "market_overview.json", "as_of": "2026-07-11"}})
    row = out["inputs"][0]
    assert row["source"] == "market_overview.json"
    assert row["as_of"] == "2026-07-11"
    assert row["value"] == "55% mã trên MA200"


def test_term_subscore_averages_slope_dir():
    out = alloc.compute_score({"term": {"dir": -1, "slope_dir": 0}})
    assert out["score"] == pytest.approx(-0.5)
    out2 = alloc.compute_score({"term": {"dir": -1}})    # thiếu slope → chỉ dir
    assert out2["score"] == pytest.approx(-1.0)


# ── hysteresis ───────────────────────────────────────────────────────────────


def test_hysteresis_first_run_applies_raw_band_immediately():
    h = alloc.apply_hysteresis(None, -0.3, "2026-07-13")
    assert h["band"] == "B3" and h["pending"] is None


def test_hysteresis_needs_two_distinct_sessions_to_switch():
    state = {"band": "B2"}
    d1 = alloc.apply_hysteresis(state, -0.3, "2026-07-13")
    assert d1["band"] == "B2"                       # phiên 1: chưa đổi
    assert d1["pending"] == {"band": "B3", "dates": ["2026-07-13"]}
    # recompute CÙNG NGÀY không đếm thêm phiên (idempotent)
    d1b = alloc.apply_hysteresis({"band": "B2", "pending": d1["pending"]},
                                 -0.3, "2026-07-13")
    assert d1b["band"] == "B2"
    assert d1b["pending"]["dates"] == ["2026-07-13"]
    # phiên 2 (ngày mới) xác nhận → đổi band
    d2 = alloc.apply_hysteresis({"band": "B2", "pending": d1["pending"]},
                                -0.3, "2026-07-14")
    assert d2["band"] == "B3" and d2["pending"] is None


def test_hysteresis_margin_deadband_blocks_boundary_wobble():
    # −0.16 chỉ vượt biên B2/B3 (−0.15) có 0.01 < margin 0.05 → không arm
    h = alloc.apply_hysteresis({"band": "B2"}, -0.16, "2026-07-13")
    assert h["band"] == "B2" and h["pending"] is None
    assert h["raw_band"] == "B3"                     # điểm thô vẫn ghi nhận
    # −0.25 vượt biên rõ → arm pending
    h2 = alloc.apply_hysteresis({"band": "B2"}, -0.25, "2026-07-13")
    assert h2["pending"] == {"band": "B3", "dates": ["2026-07-13"]}


def test_hysteresis_wobble_back_clears_pending():
    pending = {"band": "B3", "dates": ["2026-07-13"]}
    h = alloc.apply_hysteresis({"band": "B2", "pending": pending},
                               0.0, "2026-07-14")
    assert h["band"] == "B2" and h["pending"] is None


def test_hysteresis_pending_resets_when_candidate_changes():
    pending = {"band": "B3", "dates": ["2026-07-13"]}
    h = alloc.apply_hysteresis({"band": "B2", "pending": pending},
                               -0.7, "2026-07-14")
    # đề xuất mới B4 ≠ pending B3 → đếm lại từ đầu, band chưa đổi
    assert h["band"] == "B2"
    assert h["pending"] == {"band": "B4", "dates": ["2026-07-14"]}


# ── compute_allocation + config override ────────────────────────────────────


def test_compute_allocation_returns_band_table_and_reasons():
    state = alloc.compute_allocation(_full_inputs(), as_of="2026-07-13")
    assert state["band"] in alloc._BANDS
    assert set(state["allocation"]) == set(alloc._ASSET_CLASSES)
    assert sum(state["allocation"].values()) == 100
    assert state["n_inputs"] == 7
    assert state["as_of"] == "2026-07-13"
    assert state["band_label"] == alloc._BAND_LABELS[state["band"]]


def test_compute_allocation_returns_none_without_inputs():
    assert alloc.compute_allocation({}, as_of="2026-07-13") is None


def test_config_override_valid_applied_invalid_ignored(capsys):
    cfg = {"allocations": {
        # hợp lệ: đủ 5 lớp, tổng 100
        "B2": {"Cổ phiếu": 50, "Trái phiếu": 20, "Tiền gửi": 15,
               "Vàng": 10, "USD": 5},
        # sai: tổng 90 → bỏ qua
        "B0": {"Cổ phiếu": 60, "Trái phiếu": 10, "Tiền gửi": 10,
               "Vàng": 5, "USD": 5},
        # sai: thiếu lớp Vàng → bỏ qua
        "B4": {"Cổ phiếu": 20, "Trái phiếu": 25, "Tiền gửi": 45, "USD": 10},
    }}
    table = alloc._allocations_table(cfg)
    assert table["B2"]["Cổ phiếu"] == 50
    assert table["B0"] == alloc._DEFAULT_ALLOCATIONS["B0"]
    assert table["B4"] == alloc._DEFAULT_ALLOCATIONS["B4"]
    out = capsys.readouterr().out
    assert "B0" in out and "B4" in out            # có cảnh báo cho 2 band sai


def test_config_weights_override_shifts_score():
    inputs = {"regime": {"score": 5}, "sentiment": {"momentum": -100}}
    default = alloc.compute_score(inputs)["score"]
    tilted = alloc.compute_score(inputs, weights={"regime": 0.9,
                                                  "sentiment": 0.01})["score"]
    assert tilted > default


# ── run_allocation: persist + history log ────────────────────────────────────


def _use_tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(alloc, "_STATE", tmp_path / "allocation_state.json")
    monkeypatch.setattr(alloc, "_CONFIG", tmp_path / "allocation_config.json")
    return alloc._STATE


def test_run_allocation_persists_state_and_appends_history(tmp_path, monkeypatch):
    p = _use_tmp_state(tmp_path, monkeypatch)
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    state = alloc.run_allocation()
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["band"] == state["band"]
    assert len(on_disk["history"]) == 1
    h = on_disk["history"][0]
    assert h["date"] == "2026-07-13"
    assert set(h["inputs"]) == set(_full_inputs())   # đủ để scorecard chấm sau

    # phiên mới → history thêm dòng; cùng ngày → thay dòng, không nhân đôi
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-14", _full_inputs()))
    alloc.run_allocation()
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-14", _full_inputs()))
    state3 = alloc.run_allocation()
    assert [h["date"] for h in state3["history"]] == ["2026-07-13", "2026-07-14"]


def test_run_allocation_no_inputs_keeps_previous_state(tmp_path, monkeypatch):
    p = _use_tmp_state(tmp_path, monkeypatch)
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    first = alloc.run_allocation()
    assert first is not None
    # nguồn chết hết → trả None, file cũ NGUYÊN VẸN (không ghi đè bằng rỗng)
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-14", {}))
    assert alloc.run_allocation() is None
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["as_of"] == "2026-07-13"
    assert on_disk["band"] == first["band"]


def test_run_allocation_band_switch_via_hysteresis_end_to_end(tmp_path, monkeypatch):
    _use_tmp_state(tmp_path, monkeypatch)
    bull = _full_inputs(regime={"score": 5}, sentiment={"momentum": 80},
                        breadth={"above_ma200_pct": 70},
                        macro_pressure={"score": 0.8},
                        liquidity={"dir": 1})
    bear = _full_inputs(regime={"score": -5}, sentiment={"momentum": -80},
                        breadth={"above_ma200_pct": 18},
                        macro_pressure={"score": -0.8},
                        liquidity={"dir": -1},
                        term={"dir": -1, "slope_dir": -1}, intl={"dir": -1})
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", bull))
    s1 = alloc.run_allocation()
    assert s1["band"] == "B0"                       # lần đầu áp ngay
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-14", bear))
    s2 = alloc.run_allocation()
    assert s2["band"] == "B0" and s2["pending"]["band"] == "B4"
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-15", bear))
    s3 = alloc.run_allocation()
    assert s3["band"] == "B4" and s3["pending"] is None
    assert s3["allocation"]["Cổ phiếu"] == 15 and s3["allocation"]["USD"] == 8


def test_run_allocation_history_capped(tmp_path, monkeypatch):
    _use_tmp_state(tmp_path, monkeypatch)
    monkeypatch.setattr(alloc, "_HISTORY_MAX", 3)
    for d in ("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"):
        monkeypatch.setattr(alloc, "collect_inputs",
                            lambda _=None, d=d: (d, _full_inputs()))
        state = alloc.run_allocation()
    assert [h["date"] for h in state["history"]] == \
        ["2026-07-02", "2026-07-03", "2026-07-04"]


def test_config_file_override_read_by_run_allocation(tmp_path, monkeypatch):
    _use_tmp_state(tmp_path, monkeypatch)
    alloc._CONFIG.write_text(json.dumps({"allocations": {
        "B2": {"Cổ phiếu": 40, "Trái phiếu": 25, "Tiền gửi": 20,
               "Vàng": 10, "USD": 5}}}), encoding="utf-8")
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    state = alloc.run_allocation()
    if state["band"] == "B2":
        assert state["allocation"]["Cổ phiếu"] == 40


# ── collect_inputs: best-effort, hermetic qua fake modules ───────────────────


def test_collect_inputs_zero_caches_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(alloc, "_load_overview", lambda: {})
    for name in ("vnstock_regime", "vnstock_market_sentiment", "vnstock_macro"):
        monkeypatch.setitem(sys.modules, name, _mk_module(name))  # import gãy
    as_of, inputs = alloc.collect_inputs("2026-07-13")
    assert as_of == "2026-07-13"
    assert inputs == {}


def test_collect_inputs_gathers_all_sources(monkeypatch):
    monkeypatch.setattr(alloc, "_load_overview", lambda: {
        "data_date": "2026-07-11",
        "breadth": {"above_ma200_pct": 42.0},
    })
    monkeypatch.setitem(sys.modules, "vnstock_regime", _mk_module(
        "vnstock_regime",
        load_regime=lambda: {"score": -2, "n_signals": 7,
                             "label": "📉 Tiêu cực"}))
    monkeypatch.setitem(sys.modules, "vnstock_market_sentiment", _mk_module(
        "vnstock_market_sentiment",
        load_market_sentiment=lambda: {"momentum": -24, "mood": "📉 Tiêu cực"}))
    macro_rows = [
        {"key": "interbank_on", "as_of": "2026-07-03", "value": 4.9},
        {"key": "sbv_policy_rate", "as_of": "2023-06-19", "value": 4.5},
        {"key": "govt_bond_yield_10y", "as_of": "2026-07-03", "value": 4.4},
        {"key": "us10y", "as_of": "2026-07-10", "value": 4.3},
    ]
    monkeypatch.setitem(sys.modules, "vnstock_macro", _mk_module(
        "vnstock_macro",
        load_macro=lambda eff=None: macro_rows,
        macro_pressure_score=lambda m: {"score": -0.3, "label": "lãi suất tăng"},
        liquidity_spread=lambda m: {"spread": 0.4, "dir": -1, "label": "CĂNG"},
        term_spread=lambda m: {"spread": -0.1, "dir": -1, "slope_dir": 0,
                               "label": "ÂM"},
        intl_spread=lambda m: {"spread": 0.1, "dir": 0, "label": "mỏng"}))

    as_of, inputs = alloc.collect_inputs()
    assert as_of == "2026-07-11"                     # data_date của overview
    assert set(inputs) == {"breadth", "regime", "sentiment", "macro_pressure",
                           "liquidity", "term", "intl"}
    # as_of gauge = as_of CŨ nhất trong các chỉ số nền THỊ TRƯỜNG —
    # sbv_policy_rate (seed 2023, "ngày quyết định" chứ không phải độ cũ data)
    # bị loại khỏi phép min (bắt được khi verify 2026-07-14)
    assert inputs["liquidity"]["as_of"] == "2026-07-03"
    assert inputs["term"]["as_of"] == "2026-07-03"
    assert inputs["intl"]["as_of"] == "2026-07-03"
    state = alloc.compute_allocation(inputs, as_of=as_of)
    assert state["band"] in ("B3", "B4")             # nền tiêu cực → phòng thủ
    assert all(r["as_of"] for r in state["inputs"])


def test_collect_inputs_one_dead_source_does_not_block_others(monkeypatch):
    monkeypatch.setattr(alloc, "_load_overview", lambda: {
        "data_date": "2026-07-11", "breadth": {"above_ma200_pct": 55.0}})

    def _boom():
        raise RuntimeError("cache hỏng")

    monkeypatch.setitem(sys.modules, "vnstock_regime", _mk_module(
        "vnstock_regime", load_regime=_boom))
    monkeypatch.setitem(sys.modules, "vnstock_market_sentiment", _mk_module(
        "vnstock_market_sentiment", load_market_sentiment=_boom))
    monkeypatch.setitem(sys.modules, "vnstock_macro",
                        _mk_module("vnstock_macro"))
    as_of, inputs = alloc.collect_inputs()
    assert set(inputs) == {"breadth"}
    assert alloc.compute_allocation(inputs, as_of=as_of) is not None


# ── CLI smoke ────────────────────────────────────────────────────────────────


def test_cli_show_without_state_hints_refresh(tmp_path, monkeypatch, capsys):
    _use_tmp_state(tmp_path, monkeypatch)
    rc = alloc.main(["--show"])
    assert rc == 1
    assert "--refresh" in capsys.readouterr().out


def test_cli_refresh_then_show_and_history(tmp_path, monkeypatch, capsys):
    _use_tmp_state(tmp_path, monkeypatch)
    monkeypatch.setattr(alloc, "collect_inputs",
                        lambda d=None: ("2026-07-13", _full_inputs()))
    assert alloc.main(["--refresh"]) == 0
    out = capsys.readouterr().out
    assert "band B" in out and "Cổ phiếu" in out and "nguồn:" in out
    assert alloc.main(["--show"]) == 0
    assert alloc.main(["--history"]) == 0
    assert "2026-07-13" in capsys.readouterr().out
    assert alloc.main(["--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["band"] in alloc._BANDS
