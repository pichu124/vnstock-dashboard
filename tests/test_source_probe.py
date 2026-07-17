"""Tests cho vnstock_source_probe — tầng CHẤM ĐIỂM/XẾP HẠNG thuần (probe
thật cần vnstock + mạng → verify trên máy user; sandbox test logic).

Fixture tái hiện run THẬT 17/07 21:42: MSN trễ 2 phiên (bar cuối 07-15)
từng bị so close KHÁC NGÀY với KBS → "lệch giá BSR" OAN cho KBS. Scoring
date-aware phải: (a) không kết tội KBS, (b) dán nhãn MSN = TRỄ PHIÊN,
(c) outlier chỉ kết tội khi ≥3 nguồn cùng ngày, (d) 2 nguồn cãi nhau →
disputed (ghi chú, không loại)."""
from __future__ import annotations

import vnstock_source_probe as sp

_D_FRESH, _D_STALE = "2026-07-17", "2026-07-15"


def _stock(ok=True, secs=1.0, close=None, date=_D_FRESH, err=None):
    if ok:
        return {"ok": True, "secs": secs, "rows": 11, "last_close": close,
                "last_time": date, "has_vol": True}
    return {"ok": False, "secs": secs, "err": err or "Timeout"}


_RUN = {"at": "2026-07-17T21:42:00", "basket": ["FPT", "BSR", "SHS", "VGI"],
        "days": 14, "results": {
    # VCI ốm: BSR/index chết, SHS/VGI sống nhưng rề rề (retry 30s×N)
    "vci": {"source": "vci", "index": _stock(ok=False),
            "stocks": {"FPT": _stock(close=121.5, secs=8.5),
                       "BSR": _stock(ok=False, secs=62.0),
                       "SHS": _stock(close=14.2, secs=65.5),
                       "VGI": _stock(close=68.1, secs=33.9)}},
    # KBS khỏe toàn diện: đủ rổ + index + 0.4s
    "kbs": {"source": "kbs", "index": _stock(close=1782.12, secs=0.4),
            "stocks": {"FPT": _stock(close=121.5, secs=0.4),
                       "BSR": _stock(close=26.3, secs=0.5),
                       "SHS": _stock(close=14.2, secs=0.4),
                       "VGI": _stock(close=68.1, secs=0.4)}},
    # FMP: đủ rổ + cùng ngày nhưng VND THÔ (×1000), chậm hơn, không index
    "fmp": {"source": "fmp", "index": _stock(ok=False),
            "stocks": {"FPT": _stock(close=121500.0, secs=2.5),
                       "BSR": _stock(close=26300.0, secs=2.5),
                       "SHS": _stock(close=14200.0, secs=2.5),
                       "VGI": _stock(close=68100.0, secs=2.5)}},
    # MSN: đủ rổ NHƯNG bar cuối 07-15 (trễ 2 phiên) + close cũ khác close
    # mới >3% — ngày xưa bị chấm "lệch giá", nay phải ra TRỄ PHIÊN
    "msn": {"source": "msn", "index": _stock(close=1799.0, date=_D_STALE),
            "stocks": {"FPT": _stock(close=118.0, date=_D_STALE, secs=1.9),
                       "BSR": _stock(close=27.9, date=_D_STALE, secs=1.8),
                       "SHS": _stock(close=13.1, date=_D_STALE, secs=2.0),
                       "VGI": _stock(close=71.5, date=_D_STALE, secs=1.9)}},
    "dnse": {"source": "dnse", "unavailable": True, "index": None,
             "stocks": {"FPT": _stock(ok=False, err="Provider not found")}},
}}


def test_stale_source_not_blamed_as_mismatch():
    ranked = sp.score_results(_RUN)
    by = {e["source"]: e for e in ranked}
    # KBS sạch — KHÔNG còn bị vu "lệch giá BSR" vì so khác ngày
    assert by["kbs"]["mismatch"] == [] and by["kbs"]["verdict"].startswith("ứng viên tốt")
    # MSN = TRỄ PHIÊN đủ 4 mã, không phải "lệch giá"
    assert by["msn"]["mismatch"] == []
    assert by["msn"]["stale"] == ["BSR", "FPT", "SHS", "VGI"]
    assert "TRỄ PHIÊN" in by["msn"]["verdict"]


def test_ranking_and_fallback_order():
    ranked = sp.score_results(_RUN)
    order = [e["source"] for e in ranked]
    assert order[0] == "kbs"                       # phủ đủ + sạch + nhanh nhất
    assert "dnse" not in order
    # fallback: msn bị loại (trễ phiên), vci bị loại (thiếu độ phủ)
    assert sp.fallback_order(ranked) == ["kbs", "fmp"]
    by = {e["source"]: e for e in ranked}
    assert by["fmp"]["unit_x1000"] and "chia 1000" in by["fmp"]["verdict"]
    assert by["vci"]["verdict"] == "thiếu độ phủ"


def test_mismatch_needs_three_fresh_sources():
    # 3 nguồn cùng ngày, 1 outlier >3% → kết tội ĐÚNG nguồn lệch
    run = {"results": {
        "a": {"stocks": {"FPT": _stock(close=121.5)}, "index": None},
        "b": {"stocks": {"FPT": _stock(close=121.0)}, "index": None},
        "c": {"stocks": {"FPT": _stock(close=135.0)}, "index": None},
    }}
    by = {e["source"]: e for e in sp.score_results(run)}
    assert by["c"]["mismatch"] == ["FPT"] and "KHÔNG dùng" in by["c"]["verdict"]
    assert by["a"]["mismatch"] == [] and by["b"]["mismatch"] == []


def test_two_source_disagreement_is_disputed_not_condemned():
    # đúng 2 nguồn cùng ngày cãi nhau >3% → cả hai disputed, KHÔNG loại
    run = {"results": {
        "a": {"stocks": {"SHS": _stock(close=14.2)}, "index": None},
        "b": {"stocks": {"SHS": _stock(close=15.4)}, "index": None},
    }}
    ranked = sp.score_results(run)
    by = {e["source"]: e for e in ranked}
    assert by["a"]["disputed"] == ["SHS"] and by["b"]["disputed"] == ["SHS"]
    assert all(not e["mismatch"] for e in ranked)
    assert sp.fallback_order(ranked) == ["a", "b"]  # vẫn là ứng viên, có ghi chú
    assert "bất đồng" in by["a"]["verdict"]


def test_render_report_and_cumulative():
    ranked = sp.score_results(_RUN)
    txt = sp.render_report(_RUN, ranked)
    assert "kbs → fmp" in txt and "TRỄ PHIÊN" in txt and "snapshot" in txt
    cum = sp.cumulative_stats({"runs": [_RUN, _RUN]})
    assert cum["kbs"] == {"ok": 8, "n": 8, "runs": 2}
    assert "dnse" not in cum


def test_score_empty_run_safe():
    assert sp.score_results({}) == []
    assert sp.fallback_order([]) == []
