"""Tests for vnstock_scorecard — scorecard hồi tố band phân bổ (P6).

Pure core (monthly_periods / compute_scorecard / class_returns / source_log)
chạy trên fixture; refresh_scorecard test qua monkeypatch path + module fake.
"""
import json
import sys
import types

import pytest

import vnstock_scorecard as sc


def _hists():
    return {
        "vnindex": {"2026-05-02": 1700.0, "2026-06-02": 1751.0,
                    "2026-07-01": 1733.5},
        "y10":     {"2026-05-01": 4.50, "2026-06-01": 4.40, "2026-07-01": 4.60},
        "policy":  {"2023-06-19": 4.5},
        "gold":    {"2026-05-02": 3300.0, "2026-06-02": 3366.0},
        "usdvnd":  {"2026-05-02": 26000.0, "2026-06-02": 26130.0},
    }


_TABLE = {
    "B0": {"Cổ phiếu": 70, "Trái phiếu": 10, "Tiền gửi": 10, "Vàng": 5, "USD": 5},
    "B2": {"Cổ phiếu": 45, "Trái phiếu": 20, "Tiền gửi": 20, "Vàng": 10, "USD": 5},
    "B4": {"Cổ phiếu": 15, "Trái phiếu": 25, "Tiền gửi": 40, "Vàng": 12, "USD": 8},
}


# ── kỳ tháng từ history ──────────────────────────────────────────────────────


def test_monthly_periods_first_entry_per_month_completed_only():
    hist = [
        {"date": "2026-05-05", "band": "B2"},   # đầu tháng 5 (entry đầu)
        {"date": "2026-05-20", "band": "B3"},   # bị bỏ (không phải entry đầu)
        {"date": "2026-06-02", "band": "B3"},
        {"date": "2026-07-01", "band": "B2"},   # tháng cuối — mở kỳ cho T6
    ]
    periods = sc.monthly_periods(hist)
    assert [(p[0]["date"], p[1]) for p in periods] == [
        ("2026-05-05", "2026-06-02"),
        ("2026-06-02", "2026-07-01"),
    ]
    assert [p[0]["band"] for p in periods] == ["B2", "B3"]
    assert sc.monthly_periods([]) == []
    assert sc.monthly_periods([{"date": "2026-07-01", "band": "B2"}]) == []


# ── proxy returns từng lớp ───────────────────────────────────────────────────


def test_class_returns_all_proxies():
    r = sc.class_returns("2026-05-02", "2026-06-02", hists=_hists())
    assert r["Cổ phiếu"]["ret_pct"] == pytest.approx(3.0)      # 1700→1751
    # yield 4.50→4.40: −Δ×7 = +0.70
    assert r["Trái phiếu"]["ret_pct"] == pytest.approx(0.70)
    assert "proxy thô" in r["Trái phiếu"]["proxy"]
    # tiền gửi: 4.5%/năm × 31/365
    assert r["Tiền gửi"]["ret_pct"] == pytest.approx(4.5 * 31 / 365, abs=0.01)
    assert r["Vàng"]["ret_pct"] == pytest.approx(2.0)
    assert "premium SJC" in r["Vàng"]["proxy"]
    assert r["USD"]["ret_pct"] == pytest.approx(0.5)


def test_class_returns_missing_data_is_none_not_zero():
    hists = {k: {} for k in ("vnindex", "y10", "policy", "gold", "usdvnd")}
    r = sc.class_returns("2026-05-02", "2026-06-02", hists=hists)
    assert all(v["ret_pct"] is None for v in r.values())


# ── chấm điểm kỳ ─────────────────────────────────────────────────────────────


def test_compute_scorecard_port_vs_baseline():
    hist = [{"date": "2026-05-05", "band": "B0", "band_data": "B0", "tilt": 0},
            {"date": "2026-06-02", "band": "B4", "band_data": "B3", "tilt": 1},
            {"date": "2026-07-01", "band": "B2"}]
    fixed = {"Cổ phiếu": 3.0, "Trái phiếu": 0.7, "Tiền gửi": 0.38,
             "Vàng": 2.0, "USD": 0.5}

    def _rets(start, end):
        return {cls: {"ret_pct": v, "proxy": "x"} for cls, v in fixed.items()}

    rows = sc.compute_scorecard(hist, _TABLE, returns_fn=_rets)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["band"] == "B0" and r0["coverage_pct"] == 100
    exp_b0 = 0.70 * 3.0 + 0.10 * 0.7 + 0.10 * 0.38 + 0.05 * 2.0 + 0.05 * 0.5
    exp_b2 = 0.45 * 3.0 + 0.20 * 0.7 + 0.20 * 0.38 + 0.10 * 2.0 + 0.05 * 0.5
    assert r0["port_ret_pct"] == pytest.approx(exp_b0, abs=0.01)
    assert r0["baseline_b2_ret_pct"] == pytest.approx(exp_b2, abs=0.01)
    assert r0["delta_vs_b2"] == pytest.approx(exp_b0 - exp_b2, abs=0.02)
    # kỳ 2 mang band sau tilt + band_data để đối chiếu về sau
    assert rows[1]["band"] == "B4" and rows[1]["band_data"] == "B3"
    assert rows[1]["tilt"] == 1


def test_compute_scorecard_partial_coverage():
    hist = [{"date": "2026-05-05", "band": "B2"},
            {"date": "2026-06-02", "band": "B2"}]

    def _rets(start, end):
        return {cls: {"ret_pct": (3.0 if cls == "Cổ phiếu" else None),
                      "proxy": "x"} for cls in _TABLE["B2"]}

    rows = sc.compute_scorecard(hist, _TABLE, returns_fn=_rets)
    assert rows[0]["coverage_pct"] == 45              # chỉ lớp Cổ phiếu có data
    assert rows[0]["port_ret_pct"] == pytest.approx(0.45 * 3.0)
    assert rows[0]["class_returns"]["Vàng"] is None   # thiếu là None, không độn 0


# ── log nguồn báo cáo ────────────────────────────────────────────────────────


def test_source_log_only_after_horizon_and_none_without_prices():
    vnindex = {"2026-05-02": 1700.0, "2026-06-02": 1751.0}
    reports = [
        {"id": "a", "source": "SSI", "report_date": "2026-05-03",
         "digest": {"stance": {"Cổ phiếu": 2}, "has_mismatch": False}},
        {"id": "b", "source": "HSC", "report_date": "2026-07-10",     # chưa đủ 30d
         "digest": {"stance": {"Cổ phiếu": -1}}},
        {"id": "c", "source": "X", "report_date": "2026-05-03"},      # không digest
    ]
    rows = sc.source_log(reports, vnindex=vnindex, today="2026-07-13")
    assert len(rows) == 1
    assert rows[0]["source"] == "SSI" and rows[0]["stance_cp"] == 2
    assert rows[0]["vnindex_ret_30d"] == pytest.approx(3.0)
    # không có giá quanh kỳ → None (không bịa)
    rows2 = sc.source_log(reports[:1], vnindex={}, today="2026-07-13")
    assert rows2[0]["vnindex_ret_30d"] is None


# ── refresh end-to-end (fake modules + tmp path) ────────────────────────────


def test_refresh_scorecard_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "_SCORECARD", tmp_path / "allocation_scorecard.json")
    hist = [{"date": "2026-05-05", "band": "B2"},
            {"date": "2026-06-02", "band": "B0"},
            {"date": "2026-07-01", "band": "B2"}]
    alloc_mod = types.ModuleType("vnstock_allocation")
    alloc_mod.load_state = lambda: {"band": "B2", "history": hist}
    alloc_mod._load_config = lambda: {}
    alloc_mod._allocations_table = lambda cfg: _TABLE
    monkeypatch.setitem(sys.modules, "vnstock_allocation", alloc_mod)
    rp_mod = types.ModuleType("vnstock_reports")
    rp_mod.load_for_analysis = lambda **kw: []
    monkeypatch.setitem(sys.modules, "vnstock_reports", rp_mod)
    monkeypatch.setattr(
        sc, "class_returns",
        lambda s, e, hists=None: {cls: {"ret_pct": 1.0, "proxy": "x"}
                                  for cls in _TABLE["B2"]})
    out = sc.refresh_scorecard()
    assert out["n_periods"] == 2
    on_disk = json.loads(sc._SCORECARD.read_text(encoding="utf-8"))
    assert len(on_disk["periods"]) == 2 and on_disk["sources"] == []
    assert sc.load_scorecard()["n_periods"] == 2


def test_refresh_scorecard_none_without_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "_SCORECARD", tmp_path / "sc.json")
    alloc_mod = types.ModuleType("vnstock_allocation")
    alloc_mod.load_state = lambda: None
    alloc_mod._load_config = lambda: {}
    alloc_mod._allocations_table = lambda cfg: _TABLE
    monkeypatch.setitem(sys.modules, "vnstock_allocation", alloc_mod)
    assert sc.refresh_scorecard() is None
    assert not sc._SCORECARD.exists()
