"""Tests cho vnstock_price_fallback (thuần — hermetic).

Từ vnstock thế hệ 6, updater KHÔNG còn nối module này (nguồn dự phòng nằm trong
luật `VNSTOCK_SOURCE`, vnstock tự sang nguồn kế tiếp) ⇒ test tích hợp
`update_ticker` ↔ fallback KBS đã bỏ; hành vi mới canh ở
`tests/test_updater_partial_bar.py` (mục "thế hệ 6")."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import vnstock_price_fallback as fb


# ── CircuitBreaker ──────────────────────────────────────────────────────────

def test_breaker_opens_after_consecutive_fails_and_probes():
    br = fb.CircuitBreaker(open_after=3, probe_every=4)
    assert br.allow_primary()
    assert br.record_fail() is False
    assert br.record_fail() is False
    assert br.record_fail() is True                # VỪA mở
    assert br.is_open
    # đang mở: chặn primary, trừ lượt probe thứ probe_every
    assert [br.allow_primary() for _ in range(4)] == [False, False, False, True]
    # probe thành công → đóng mạch (trả True đúng 1 lần)
    assert br.record_ok() is True
    assert br.record_ok() is False and not br.is_open
    assert br.allow_primary()


def test_breaker_ok_resets_consecutive_count():
    br = fb.CircuitBreaker(open_after=3)
    br.record_fail(); br.record_fail()
    br.record_ok()                                  # chuỗi liên tiếp đứt
    assert br.record_fail() is False and not br.is_open


def test_breaker_reset():
    br = fb.CircuitBreaker(open_after=1)
    br.record_fail()
    assert br.is_open
    br.reset()
    assert not br.is_open and br.allow_primary()


# ── Phân loại lỗi outage ────────────────────────────────────────────────────

def test_is_outage_error():
    assert fb.is_outage_error(
        "HTTPSConnectionPool(host='trading.vietcap.com.vn'): Read timed out.")
    assert fb.is_outage_error("RetryError[ConnectionError]")
    assert fb.is_outage_error("503 Service Unavailable")
    # lỗi riêng của mã — KHÔNG tính outage, không fallback
    assert not fb.is_outage_error("Invalid symbol XYZ")
    assert not fb.is_outage_error("KeyError: 'close'")
    assert not fb.is_outage_error("")


# ── reconcile_fallback_df ───────────────────────────────────────────────────

_D = date(2026, 7, 16)


def _df(close_overlap, unit=1.0):
    return pd.DataFrame({
        "time": [_D, date(2026, 7, 17)],
        "open": [close_overlap * unit, 122.0 * unit],
        "high": [close_overlap * unit, 123.0 * unit],
        "low": [close_overlap * unit, 120.0 * unit],
        "close": [close_overlap * unit, 121.5 * unit],
        "volume": [1e6, 1.2e6],
    })


def test_reconcile_pass_and_unit_divide():
    out, note = fb.reconcile_fallback_df(_df(120.0), 120.0, _D)
    assert out is not None and note == ""
    # VND thô ×1000 → chia cả OHLC, volume GIỮ nguyên
    out, note = fb.reconcile_fallback_df(_df(120.0, unit=1000.0), 120.0, _D)
    assert out is not None and "chia 1000" in note
    assert out["close"].iloc[0] == pytest.approx(120.0)
    assert out["open"].iloc[1] == pytest.approx(122.0)
    assert out["volume"].iloc[0] == pytest.approx(1e6)


def test_reconcile_rejects_divergence_and_missing_overlap():
    # lệch 15% > 8% → từ chối (khác adjustment basis)
    out, note = fb.reconcile_fallback_df(_df(138.0), 120.0, _D)
    assert out is None and "lệch" in note
    # không có bar overlap để đối chiếu → từ chối
    out, note = fb.reconcile_fallback_df(_df(120.0), 120.0, date(2026, 7, 10))
    assert out is None and "không trả bar" in note
    # không đọc được close warehouse → từ chối
    out, note = fb.reconcile_fallback_df(_df(120.0), None, _D)
    assert out is None and "warehouse" in note
    # df rỗng → pass-through (caller xử no_new_data)
    out, note = fb.reconcile_fallback_df(pd.DataFrame(), 120.0, _D)
    assert out is not None and out.empty
