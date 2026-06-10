"""Tests for vnstock_events (upcoming corp-action calendar) + its brief block."""

from __future__ import annotations

from datetime import date

import pandas as pd

import vnstock_events as ev
from vnstock_brief import _upcoming_events_block, build_prompt


def _write(tmp_path):
    p = tmp_path / "upcoming_events.parquet"
    pd.DataFrame([
        {"ticker": "VIC", "ex_date": "2026-06-12", "type": "cash",
         "cash_amount": 1500, "ratio": None},
        {"ticker": "MWG", "ex_date": "2026-06-30", "type": "split",
         "cash_amount": None, "ratio": 2.0},                     # >14d out
        {"ticker": "FPT", "ex_date": "2026-06-01", "type": "cash",
         "cash_amount": 1000, "ratio": None},                    # past
        {"ticker": "GEX", "ex_date": "2026-06-13", "type": "bonus",
         "cash_amount": None, "ratio": 1.5},
    ]).to_parquet(p, index=False)
    return p


def test_load_upcoming_filters_window(tmp_path):
    out = ev.load_upcoming(within_days=14, path=_write(tmp_path),
                           today=date(2026, 6, 10))
    names = [e["ticker"] for e in out]
    assert "VIC" in names and "GEX" in names    # inside [10/06, 24/06]
    assert "MWG" not in names                    # 30/06 is out of window
    assert "FPT" not in names                    # past
    assert names == ["VIC", "GEX"]               # sorted by ex_date


def test_load_upcoming_ticker_filter(tmp_path):
    out = ev.load_upcoming(within_days=14, path=_write(tmp_path),
                           today=date(2026, 6, 10), tickers={"VIC"})
    assert [e["ticker"] for e in out] == ["VIC"]


def test_load_upcoming_missing_file(tmp_path):
    assert ev.load_upcoming(path=tmp_path / "nope.parquet") == []


def test_upcoming_events_block_renders():
    block = _upcoming_events_block([
        {"ticker": "VIC", "ex_date": "2026-06-12", "type": "cash",
         "cash_amount": 1500, "ratio": None},
        {"ticker": "GEX", "ex_date": "2026-06-13", "type": "bonus",
         "cash_amount": None, "ratio": 1.5},
    ])
    assert "Sự kiện sắp tới" in block
    assert "VIC" in block and "GDKHQ 2026-06-12" in block
    assert "cổ tức tiền mặt 1,500đ" in block
    assert "GEX" in block and "thưởng" in block


def test_upcoming_events_block_empty():
    assert _upcoming_events_block([]) == ""


def test_build_prompt_includes_upcoming_events():
    ctx = {"date": "2026-06-10", "time": "15:00",
           "upcoming_events": [
               {"ticker": "VIC", "ex_date": "2026-06-12", "type": "cash",
                "cash_amount": 1500, "ratio": None}]}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Sự kiện sắp tới" in prompt and "VIC" in prompt
