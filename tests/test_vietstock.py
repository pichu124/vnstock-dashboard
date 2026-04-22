"""Tests for vnstock_vietstock — Vietstock corp action scraper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vnstock_vietstock import (
    _CHANNEL_TYPE,
    _get_csrf_token,
    _parse_ms_date,
    _parse_note,
    fetch_corp_events,
)

# ── _parse_ms_date ─────────────────────────────────────────────────────────────

def test_parse_ms_date_valid():
    # 1776358800000 ms = 2026-04-16 17:00 UTC = 2026-04-17 00:00 Vietnam (UTC+7)
    result = _parse_ms_date("/Date(1776358800000)/")
    assert result == "2026-04-17"


def test_parse_ms_date_none():
    assert _parse_ms_date(None) is None


def test_parse_ms_date_malformed():
    assert _parse_ms_date("not-a-date") is None


# ── _parse_note ────────────────────────────────────────────────────────────────

def test_parse_note_cash_dividend():
    note = "Trả cổ tức  đợt 2/2019 bằng tiền, 2,000 đồng/CP"
    result = _parse_note(note, channel_id=13)
    assert result["cash_amount"] == pytest.approx(2.0)


def test_parse_note_cash_small():
    note = "Trả cổ tức năm 2017 bằng tiền, 1,200 đồng/CP"
    result = _parse_note(note, channel_id=13)
    assert result["cash_amount"] == pytest.approx(1.2)


def test_parse_note_bonus_shares():
    note = "Thưởng cổ phiếu, tỷ lệ 100:20"
    result = _parse_note(note, channel_id=14)
    assert result["ratio"] == pytest.approx(0.2)


def test_parse_note_bonus_fraction():
    note = "Thưởng cổ phiếu, tỷ lệ 5:2"
    result = _parse_note(note, channel_id=14)
    assert result["ratio"] == pytest.approx(0.4)


def test_parse_note_stock_dividend():
    note = "Trả cổ tức năm 2010 bằng cổ phiếu, tỷ lệ 100:10"
    result = _parse_note(note, channel_id=15)
    assert result["ratio"] == pytest.approx(0.1)


def test_parse_note_rights_issue():
    note = "Thực hiện quyền mua cổ phiếu phát hành thêm, tỷ lệ 1:1, giá 10,000 đồng/CP"
    result = _parse_note(note, channel_id=16)
    assert result["ratio"] == pytest.approx(1.0)
    assert result["cash_amount"] == pytest.approx(10.0)


def test_parse_note_rights_2to1():
    note = "Thực hiện quyền mua cổ phiếu phát hành thêm, tỷ lệ 2:1, giá 10,000 đồng/CP"
    result = _parse_note(note, channel_id=16)
    assert result["ratio"] == pytest.approx(0.5)
    assert result["cash_amount"] == pytest.approx(10.0)


def test_parse_note_unknown_channel_returns_empty():
    result = _parse_note("something", channel_id=99)
    assert result == {}


# ── channel type mapping ───────────────────────────────────────────────────────

def test_channel_type_mapping():
    assert _CHANNEL_TYPE[13] == "cash"
    assert _CHANNEL_TYPE[14] == "bonus"
    assert _CHANNEL_TYPE[15] == "bonus"
    assert _CHANNEL_TYPE[16] == "rights"


# ── fetch_corp_events (mocked HTTP) ───────────────────────────────────────────

def _make_fake_response(rows: list[dict], total: int = None) -> MagicMock:
    total = total if total is not None else len(rows)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = [rows, [], [total]]
    return mock_resp


def test_fetch_corp_events_parses_rows():
    rows = [
        {
            "ChannelID": 13,
            "GDKHQDate": "/Date(1776358800000)/",
            "Note": "Trả cổ tức bằng tiền, 2,000 đồng/CP",
            "Code": "VCB",
        },
        {
            "ChannelID": 16,
            "GDKHQDate": "/Date(1776358800000)/",
            "Note": "Phát hành thêm, tỷ lệ 1:1, giá 10,000 đồng/CP",
            "Code": "VCB",
        },
    ]
    with patch("vnstock_vietstock._get_csrf_token", return_value="tok"):
        mock_sess = MagicMock()
        mock_sess.post.return_value = _make_fake_response(rows)
        events = fetch_corp_events("VCB", session=mock_sess, _csrf_token="tok")

    assert len(events) == 2
    assert events[0]["type_"] == "cash"
    assert events[0]["cash_amount"] == pytest.approx(2.0)
    assert events[1]["type_"] == "rights"
    assert events[1]["ratio"] == pytest.approx(1.0)


def test_fetch_corp_events_skips_unknown_channel():
    rows = [{"ChannelID": 99, "GDKHQDate": "/Date(1776358800000)/", "Note": "", "Code": "X"}]
    with patch("vnstock_vietstock._get_csrf_token", return_value="tok"):
        mock_sess = MagicMock()
        mock_sess.post.return_value = _make_fake_response(rows)
        events = fetch_corp_events("X", session=mock_sess, _csrf_token="tok")
    assert events == []


def test_fetch_corp_events_skips_missing_date():
    rows = [{"ChannelID": 13, "GDKHQDate": None, "Note": "2,000 đồng/CP", "Code": "X"}]
    with patch("vnstock_vietstock._get_csrf_token", return_value="tok"):
        mock_sess = MagicMock()
        mock_sess.post.return_value = _make_fake_response(rows)
        events = fetch_corp_events("X", session=mock_sess, _csrf_token="tok")
    assert events == []


def test_fetch_corp_events_empty_body_returns_empty():
    """Empty response body (ticker not in Vietstock) → empty list, not exception."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = ""
    with patch("vnstock_vietstock._get_csrf_token", return_value="tok"):
        mock_sess = MagicMock()
        mock_sess.post.return_value = mock_resp
        events = fetch_corp_events("AAH", session=mock_sess, _csrf_token="tok")
    assert events == []


def test_fetch_corp_events_raises_without_csrf():
    with patch("vnstock_vietstock._get_csrf_token", return_value=None):
        with pytest.raises(RuntimeError, match="CSRF"):
            fetch_corp_events("VCB")


def test_fetch_corp_events_source_is_vietstock():
    rows = [{"ChannelID": 14, "GDKHQDate": "/Date(1776358800000)/",
             "Note": "Thưởng cổ phiếu, tỷ lệ 100:20", "Code": "VCB"}]
    with patch("vnstock_vietstock._get_csrf_token", return_value="tok"):
        mock_sess = MagicMock()
        mock_sess.post.return_value = _make_fake_response(rows)
        events = fetch_corp_events("VCB", session=mock_sess, _csrf_token="tok")
    assert events[0]["source"] == "vietstock"
    assert events[0]["ticker"] == "VCB"
