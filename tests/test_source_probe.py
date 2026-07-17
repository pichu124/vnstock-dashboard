"""Tests cho vnstock_source_probe — tầng CHẤM ĐIỂM/XẾP HẠNG thuần (probe
thật cần vnstock + mạng → verify trên máy user; sandbox test logic)."""
from __future__ import annotations

import vnstock_source_probe as sp


def _stock(ok=True, secs=1.0, close=None, err=None):
    if ok:
        return {"ok": True, "secs": secs, "rows": 10, "last_close": close,
                "has_vol": True}
    return {"ok": False, "secs": secs, "err": err or "Timeout"}


_RUN = {"at": "2026-07-17T22:00:00", "basket": ["FPT", "BSR", "SHS", "VGI"],
        "days": 14, "results": {
    # VCI outage: 2 mã đầu chết → fail-fast (chỉ probe 2)
    "vci": {"source": "vci", "fail_fast": True, "index": None,
            "stocks": {"FPT": _stock(ok=False, secs=62.0),
                       "BSR": _stock(ok=False, secs=61.0)}},
    # KBS khỏe toàn diện: đủ rổ + index + nhanh
    "kbs": {"source": "kbs", "index": _stock(close=1782.12),
            "stocks": {"FPT": _stock(close=121.5), "BSR": _stock(close=26.3),
                       "SHS": _stock(close=14.2), "VGI": _stock(close=68.1)}},
    # FMP: đủ rổ nhưng trả VND THÔ (×1000) + chậm hơn + không index
    "fmp": {"source": "fmp", "index": _stock(ok=False),
            "stocks": {"FPT": _stock(close=121500.0, secs=2.5),
                       "BSR": _stock(close=26300.0, secs=2.5),
                       "SHS": _stock(close=14200.0, secs=2.5),
                       "VGI": _stock(close=68100.0, secs=2.5)}},
    # MSN: thiếu HNX/UPCOM + BSR lệch giá 14% vs median → cấm dùng
    "msn": {"source": "msn", "index": _stock(ok=False),
            "stocks": {"FPT": _stock(close=121.5), "BSR": _stock(close=30.0),
                       "SHS": _stock(ok=False), "VGI": _stock(ok=False)}},
    # registry bản này không có → loại khỏi bảng
    "dnse": {"source": "dnse", "unavailable": True, "index": None,
             "stocks": {"FPT": _stock(ok=False, err="Provider not found")}},
}}


def test_score_ranking_order_and_verdicts():
    ranked = sp.score_results(_RUN)
    order = [e["source"] for e in ranked]
    assert order[0] == "kbs" and order[1] == "fmp"        # phủ đủ đứng đầu
    assert "dnse" not in order                             # unavailable bị loại
    by = {e["source"]: e for e in ranked}
    assert by["kbs"]["verdict"] == "ứng viên tốt"
    assert by["kbs"]["index_ok"] is True
    # FMP: đơn vị VND thô được nhận diện, KHÔNG bị coi là lệch giá
    assert by["fmp"]["unit_x1000"] is True and not by["fmp"]["mismatch"]
    assert "chia 1000" in by["fmp"]["verdict"]
    # MSN: BSR lệch 14% → mismatch → cấm dùng
    assert by["msn"]["mismatch"] == ["BSR"] and "KHÔNG dùng" in by["msn"]["verdict"]
    # VCI chết tại thời điểm probe
    assert by["vci"]["ok"] == 0 and "CHẾT" in by["vci"]["verdict"]


def test_fallback_order_excludes_partial_and_mismatch():
    ranked = sp.score_results(_RUN)
    assert sp.fallback_order(ranked) == ["kbs", "fmp"]     # msn/vci bị loại


def test_render_report_mentions_order_and_caveat():
    ranked = sp.score_results(_RUN)
    txt = sp.render_report(_RUN, ranked)
    assert "kbs → fmp" in txt
    assert "chia 1000" in txt and "snapshot" in txt


def test_cumulative_stats_accumulates_runs():
    cache = {"runs": [_RUN, _RUN]}
    cum = sp.cumulative_stats(cache)
    assert cum["kbs"] == {"ok": 8, "n": 8, "runs": 2}
    assert cum["vci"]["ok"] == 0 and cum["vci"]["n"] == 4
    assert "dnse" not in cum                               # unavailable bỏ qua


def test_score_empty_run_safe():
    assert sp.score_results({}) == []
    assert sp.fallback_order([]) == []
