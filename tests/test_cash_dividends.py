"""Tests for vnstock_cash_dividends — pure parsing/cache logic.

Network calls are NOT exercised in tests (they hit cafef.vn). The
parser is tested against canned HTML; the cache layer with tmp_path.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vnstock_cash_dividends import (
    CashDividend,
    _extract_cash_amount,
    _is_cash_dividend_row,
    _load_cache,
    _parse_date_safe,
    _save_cache,
    parse_cafef_html,
)


# ── _parse_date_safe ──────────────────────────────────────────────────────

def test_parse_date_dd_mm_yyyy():
    assert _parse_date_safe("15/04/2026") == date(2026, 4, 15)


def test_parse_date_yyyy_mm_dd():
    assert _parse_date_safe("2026-04-15") == date(2026, 4, 15)


def test_parse_date_with_extra_text():
    assert _parse_date_safe("Ngày: 15/04/2026") == date(2026, 4, 15)


def test_parse_date_invalid():
    assert _parse_date_safe("not a date") is None
    assert _parse_date_safe("") is None
    assert _parse_date_safe(None) is None


# ── _extract_cash_amount ──────────────────────────────────────────────────

def test_extract_cash_amount_with_dong_symbol():
    assert _extract_cash_amount("1,200 đ/cp") == 1200.0


def test_extract_cash_amount_with_vnd():
    assert _extract_cash_amount("Tiền 8% / 1500 VND") == 1500.0


def test_extract_cash_amount_with_dots_in_thousands():
    # CafeF sometimes uses dots: "1.200 đồng"
    assert _extract_cash_amount("1.200 đồng") == 1200.0


def test_extract_cash_amount_fallback_first_int():
    assert _extract_cash_amount("Cash 800") == 800.0


def test_extract_cash_amount_no_number():
    assert _extract_cash_amount("Empty cell") is None


# ── _is_cash_dividend_row ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Trả cổ tức bằng tiền mặt năm 2025", True),
    ("Cổ tức tiền mặt 8%", True),
    ("Cash dividend 2024", True),
    ("Cổ phiếu thưởng tỷ lệ 1:5", False),
    ("Phát hành thêm cổ phiếu", False),
    ("Chia tách cổ phiếu", False),
    ("Bonus issue", False),
    ("Trả cổ tức bằng cổ phiếu", False),  # ambiguous — has "cổ tức" but bằng cổ phiếu
    ("", False),
    (None, False),
])
def test_is_cash_dividend_row(text, expected):
    assert _is_cash_dividend_row(text) is expected


# ── parse_cafef_html ──────────────────────────────────────────────────────

_CANNED_HTML = """<!DOCTYPE html>
<html><body>
<table>
  <thead>
    <tr><th>Ngày GDKHQ</th><th>Sự kiện</th><th>Tỷ lệ</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>15/04/2026</td>
      <td>Trả cổ tức bằng tiền mặt</td>
      <td>1,200 đ/cp</td>
    </tr>
    <tr>
      <td>10/03/2025</td>
      <td>Cổ phiếu thưởng</td>
      <td>1:5</td>
    </tr>
    <tr>
      <td>20/01/2025</td>
      <td>Cash dividend</td>
      <td>800 VND</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_parse_cafef_html_picks_cash_only():
    events = parse_cafef_html(_CANNED_HTML, "VCB")
    assert len(events) == 2   # 2 cash, skipped 1 bonus
    dates = sorted(e.ex_date for e in events)
    assert dates == [date(2025, 1, 20), date(2026, 4, 15)]


def test_parse_cafef_html_normalises_ticker():
    events = parse_cafef_html(_CANNED_HTML, "vcb")
    for e in events:
        assert e.ticker == "VCB"


def test_parse_cafef_html_extracts_amount():
    events = parse_cafef_html(_CANNED_HTML, "VCB")
    cash_by_date = {e.ex_date: e.cash_amount_vnd for e in events}
    assert cash_by_date[date(2026, 4, 15)] == 1200.0
    assert cash_by_date[date(2025, 1, 20)] == 800.0


def test_parse_cafef_html_empty():
    assert parse_cafef_html("", "VCB") == []
    assert parse_cafef_html("<html></html>", "VCB") == []


def test_parse_cafef_html_malformed():
    # Missing closing tags etc. — should not raise
    assert parse_cafef_html("<table><tr><td>broken", "VCB") == []


# ── cache ─────────────────────────────────────────────────────────────────

def test_save_load_roundtrip(tmp_path):
    events = [
        CashDividend(ticker="VCB", ex_date=date(2026, 4, 15),
                      cash_amount_vnd=1200.0, note="dividend 8%"),
        CashDividend(ticker="VCB", ex_date=date(2025, 1, 20),
                      cash_amount_vnd=800.0, note=""),
    ]
    _save_cache(tmp_path, "VCB", events)

    loaded = _load_cache(tmp_path, "VCB")
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0].cash_amount_vnd == 1200.0
    assert loaded[1].ex_date == date(2025, 1, 20)


def test_load_cache_missing(tmp_path):
    assert _load_cache(tmp_path, "XYZ") is None


def test_load_cache_corrupt(tmp_path):
    cdir = tmp_path / "_meta" / "cash_dividends"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "VCB.json").write_text("{not json")
    assert _load_cache(tmp_path, "VCB") is None


# ── to_registry_event ─────────────────────────────────────────────────────

def test_to_registry_event_converts_to_thousand_vnd():
    e = CashDividend(ticker="VCB", ex_date=date(2026, 4, 15),
                      cash_amount_vnd=1200.0, note="x")
    payload = e.to_registry_event()
    assert payload["ticker"] == "VCB"
    assert payload["type_"] == "cash"
    assert payload["cash_amount"] == 1.2   # /1000 → thousand VND
    assert payload["source"] == "cafef"


# ── integration with registry ─────────────────────────────────────────────

def test_fetch_from_cache_then_register(tmp_path, monkeypatch):
    """End-to-end with cache: load 2 dividends → push to registry."""
    from vnstock_cash_dividends import fetch_and_register

    # Seed the cache
    events = [
        CashDividend(ticker="VCB", ex_date=date(2026, 4, 15),
                      cash_amount_vnd=1200.0, note="div 8%"),
        CashDividend(ticker="VCB", ex_date=date(2025, 1, 20),
                      cash_amount_vnd=800.0, note=""),
    ]
    _save_cache(tmp_path, "VCB", events)

    result = fetch_and_register("VCB", warehouse=tmp_path, use_cache=True)
    assert result["fetched"] == 2
    assert result["registered_added"] == 2

    # Verify registry has them
    from vnstock_corp_registry import get_events_for_ticker
    df = get_events_for_ticker("VCB", warehouse=tmp_path)
    assert len(df) == 2
    assert all(df["source"] == "cafef")
    assert all(df["type"] == "cash")
