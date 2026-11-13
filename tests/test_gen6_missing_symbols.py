"""`scripts/gen6_missing_symbols.classify` — tách mã bị bỏ sót (đang giao dịch) khỏi mã ngừng giao dịch."""
from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.gen6_missing_symbols import _last_date, classify, verdict


def test_classify_splits_recent_old_and_quarantined():
    last = {"FPT": date(2026, 11, 12), "BBC": date(2026, 11, 11), "VNM": date(2026, 11, 10),
            "AMD": date(2026, 6, 1), "NEW": None}
    c = classify(last, pending={"VNM"}, recent_days=10)
    assert c["session"] == date(2026, 11, 12)
    assert c["recent"] == ["BBC"] and c["old"] == ["AMD"] and c["quarantined"] == ["VNM"]


def test_classify_empty_warehouse():
    assert classify({}, set())["session"] is None


def test_last_date_takes_newest_year_and_all_files(tmp_path):
    t = tmp_path / "ticker=BBC"
    for y, files in {2025: {"a": ["2025-12-30"]}, 2026: {"a": ["2026-11-10"], "b": ["2026-11-11"]}}.items():
        (t / f"year={y}").mkdir(parents=True)
        for name, days in files.items():
            pd.DataFrame({"time": pd.to_datetime(days)}).to_parquet(t / f"year={y}" / f"{name}.parquet")
    assert _last_date(t) == date(2026, 11, 11)


def test_verdict_tells_thin_ticker_from_missed_and_dead():
    s, wh = date(2026, 11, 12), date(2026, 11, 9)
    assert "bình thường" in verdict(wh, s, {"dnse": date(2026, 11, 9), "fhsc": None})     # ABR 12/11
    assert "BỎ SÓT" in verdict(wh, s, {"dnse": None, "fhsc": date(2026, 11, 12)})
    assert "BỎ SÓT" in verdict(wh, s, {"dnse": date(2026, 11, 11)})
    assert "KHÔNG nguồn nào" in verdict(wh, s, {"dnse": None, "fhsc": None})


def test_verdict_warehouse_already_current_is_not_missed():
    # Desktop 13/11: FPT/VCB/HPG kho cuối 13/11 = phiên mới nhất, nguồn cũng 13/11 ⇒ KHÔNG "bỏ sót".
    s = date(2026, 11, 13)
    v = verdict(s, s, {"dnse": s, "fhsc": s})
    assert "khớp nguồn" in v and "BỎ SÓT" not in v
