"""#18 (30/09): GTGD cả ngày hụt vì MÃ LỚN thiếu bar — cổng coverage cũ đếm SỐ
MÃ (`_gtgd_baselines`, 70% trung vị count) nên 45 mã cách ly 16–29/09 gồm FPT ·
VPB · GAS · TCX · PVS (2,6% số mã, cả nghìn tỷ GTGD) lọt lưới: brief in "+27% so
với phiên trước" 17/09 rồi "thấp hơn TB" suốt hai tuần một phần vì thiếu data.

Runner kê mã lớn thiếu bar phiên mới nhất (`gtgd_missing_heavy`) + tổng từng
ngày ĐÃ LOẠI chúng (`excl_missing`); brief so % trên cùng tập mã, prompt + guard
nói rõ "(chưa gồm N mã lớn thiếu data)"; doctor có badge.
"""
from datetime import date

import pytest

import vnstock_runner as vr
from vnstock_brief import (_gtgd_baselines, build_prompt,
                           enforce_gtgd_missing_note)


def _series(start_day: int, n: int, val: float) -> dict:
    """{date: val} cho n ngày liên tiếp trong tháng 9/2026 từ start_day."""
    return {date(2026, 9, d): val for d in range(start_day, start_day + n)}


def test_heavy_missing_picks_big_names_absent_on_latest_day():
    latest = date(2026, 9, 29)
    by_ticker = {
        "FPT": _series(1, 16, 800.0),      # bar cuối 16/09 — đứng 13 ngày, lớn → THIẾU
        "VPB": _series(3, 20, 450.0),      # bar cuối 22/09 → THIẾU
        "HPG": _series(10, 20, 900.0),     # có bar 29/09 → không thiếu
        "XYZ": _series(1, 16, 4.0),        # nhỏ (4 tỷ/phiên) → bỏ qua
        "OLD": {date(2026, 6, 1): 700.0},  # bar cuối 120 ngày trước → hủy niêm yết, bỏ qua
        "EMP": {},
    }
    out = vr.heavy_missing(by_ticker, latest)
    assert [m["ticker"] for m in out] == ["FPT", "VPB"]          # sắp theo avg giảm dần
    assert out[0] == {"ticker": "FPT", "last_date": "2026-09-16", "avg_gtgd": 800.0}
    assert vr.heavy_missing(by_ticker, None) == []
    # ngưỡng đọc được: hạ min_avg thì XYZ vào
    assert "XYZ" in [m["ticker"] for m in vr.heavy_missing(by_ticker, latest, min_avg=1.0)]


def test_excl_missing_totals_subtracts_only_days_the_ticker_traded():
    by_ticker = {"FPT": {date(2026, 9, 15): 800.0, date(2026, 9, 16): 820.0},
                 "HPG": {date(2026, 9, 15): 900.0, date(2026, 9, 16): 910.0,
                         date(2026, 9, 17): 905.0}}
    totals = {date(2026, 9, 15): 15_000.0, date(2026, 9, 16): 15_200.0,
              date(2026, 9, 17): 14_100.0}
    missing = [{"ticker": "FPT", "last_date": "2026-09-16", "avg_gtgd": 810.0}]
    excl = vr.excl_missing_totals(totals, by_ticker, missing)
    assert excl[date(2026, 9, 15)] == pytest.approx(14_200.0)
    assert excl[date(2026, 9, 16)] == pytest.approx(14_380.0)
    assert excl[date(2026, 9, 17)] == pytest.approx(14_100.0)   # FPT không có bar → không trừ
    assert vr.excl_missing_totals(totals, by_ticker, []) == totals


def test_gtgd_baselines_use_excl_prefers_excl_missing_and_falls_back():
    byd = {f"2026-09-{d:02d}": {"total": 15_000.0, "count": 800, "excl_missing": 14_200.0}
           for d in range(1, 21)}
    byd["2026-09-05"] = {"total": 15_000.0, "count": 800}          # ngày không có key → total
    cmp_excl = _gtgd_baselines(byd, "2026-09-21", use_excl=True)
    assert cmp_excl["prev"] == 14_200.0
    assert 14_200.0 < cmp_excl["avg20"] < 15_000.0                # một ngày rơi về total
    cmp_plain = _gtgd_baselines(byd, "2026-09-21")
    assert cmp_plain["prev"] == 15_000.0 and cmp_plain["avg20"] == 15_000.0


def test_build_prompt_notes_missing_heavy_tickers():
    ctx = {"date": "2026-09-29", "time": "15:00", "full_day_gtgd": 13_698.0,
           "vnindex_tech": {"close": 1777.73, "intraday": False},
           "full_day_gtgd_cmp": {"prev": 16_500.0, "avg5": 16_000.0},
           "gtgd_missing_heavy": [{"ticker": "FPT", "last_date": "2026-09-16", "avg_gtgd": 812.0},
                                  {"ticker": "VPB", "last_date": "2026-09-22", "avg_gtgd": 455.0}],
           "gtgd_missing_est": 1_267.0}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "THIẾU bar phiên này của 2 mã lớn (FPT, VPB; ≈1,267 tỷ/phiên" in p
    assert "ƯỚC TÍNH THẤP" in p and "(chưa gồm 2 mã lớn thiếu data)" in p
    # không thiếu mã → không có dòng cảnh báo
    ctx2 = dict(ctx, gtgd_missing_heavy=[])
    assert "THIẾU bar" not in build_prompt(ctx2, brief_type="afternoon")


def test_enforce_gtgd_missing_note_appends_once_after_canonical_figure():
    ctx = {"full_day_gtgd": 13_698.0,
           "gtgd_missing_heavy": [{"ticker": "FPT"}, {"ticker": "VPB"}, {"ticker": "GAS"}]}
    t = ("**Kết quả phiên:** VNINDEX đóng cửa 1,777.73 (-0.17%) / GTGD 13,698.0 tỷ — áp lực bán.\n"
         "GTGD cả ngày đạt 13,698.0 tỷ đồng, thấp hơn -16% so với TB5.")
    f = enforce_gtgd_missing_note(t, ctx)
    assert f.count("(chưa gồm 3 mã lớn thiếu data)") == 1
    assert "GTGD 13,698.0 tỷ (chưa gồm 3 mã lớn thiếu data) — áp lực bán" in f
    assert enforce_gtgd_missing_note(f, ctx) == f                       # idempotent
    # "tỷ đồng" cũng bắt được khi lần đầu là dạng đó
    t2 = "GTGD cả ngày đạt 13,698.0 tỷ đồng, giảm."
    assert "13,698.0 tỷ đồng (chưa gồm 3 mã lớn thiếu data), giảm." in enforce_gtgd_missing_note(t2, ctx)
    # không thiếu mã / không có số canon → no-op
    assert enforce_gtgd_missing_note(t, {"full_day_gtgd": 13_698.0}) is t
    assert enforce_gtgd_missing_note("không có số", ctx) == "không có số"


def test_doctor_gtgd_coverage_states(tmp_path, monkeypatch):
    import json

    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path)
    assert doc.check_gtgd_coverage()["status"] == "off"                  # chưa có file
    p = tmp_path / "market_overview.json"
    p.write_text(json.dumps({"data_date": "2026-09-29"}), encoding="utf-8")
    assert doc.check_gtgd_coverage()["status"] == "off"                  # runner bản cũ
    p.write_text(json.dumps({"data_date": "2026-09-29", "gtgd_missing_heavy": [],
                             "gtgd_heavy_min": 50.0}), encoding="utf-8")
    r = doc.check_gtgd_coverage()
    assert r["status"] == "ok" and "2026-09-29" in r["message"]
    p.write_text(json.dumps({
        "data_date": "2026-09-29", "gtgd_heavy_min": 50.0, "gtgd_missing_est": 1267.0,
        "gtgd_missing_heavy": [{"ticker": "FPT", "last_date": "2026-09-16", "avg_gtgd": 812.0},
                               {"ticker": "VPB", "last_date": "2026-09-22", "avg_gtgd": 455.0}],
    }), encoding="utf-8")
    r = doc.check_gtgd_coverage()
    assert r["status"] == "warn"
    assert "thiếu bar 2 mã lớn ≈ 1,267 tỷ/phiên" in r["message"]
    assert "FPT (≈812 tỷ, bar cuối 2026-09-16)" in r["message"]
    assert "#15" in r["fix"]
    assert doc.check_gtgd_coverage in doc.OFFLINE_CHECKS
