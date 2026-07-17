"""Tests cho vnstock_price_fallback (thuần — hermetic) + integration
update_ticker (skip khi sandbox thiếu vnstock, chạy đủ trên máy user)."""
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


# ── Integration update_ticker (cần vnstock_updater import được) ─────────────

def _updater_or_skip():
    try:
        import vnstock_updater as up
        return up
    except Exception as e:                          # sandbox thiếu vnstock
        pytest.skip(f"vnstock_updater không import được ({e}) — chạy trên máy dev")


def _seed_warehouse(tmp_path, ticker="FPT", close=120.0):
    tdir = tmp_path / "prices" / f"ticker={ticker}"
    ydir = tdir / "year=2026"
    ydir.mkdir(parents=True)
    pd.DataFrame({
        "time": [date(2026, 7, 15), _D],
        "open": [119.0, 119.5], "high": [121.0, 120.5],
        "low": [118.0, 119.0], "close": [119.5, close],
        "volume": [1e6, 1e6],
    }).to_parquet(ydir / "data.parquet", index=False)
    return tmp_path / "prices", tdir


def test_update_ticker_falls_back_to_kbs_and_reconciles(tmp_path, monkeypatch):
    up = _updater_or_skip()
    prices_dir, tdir = _seed_warehouse(tmp_path)
    fb.BREAKER.reset()

    def _vci_dead(*a, **k):
        raise RuntimeError("HTTPSConnectionPool: Read timed out. (read timeout=30)")

    monkeypatch.setattr(up, "_fetch_prices", _vci_dead)
    monkeypatch.setattr(up, "_fetch_prices_fallback",
                        lambda t, start, end: _df(120.0))
    r = up.update_ticker("FPT", prices_dir, date(2026, 7, 17))
    assert r["status"] == "updated" and r["source"] == "kbs"
    assert r["new_days"] == 1
    merged = pd.read_parquet(tdir / "year=2026")
    assert len(merged) == 3                          # 15, 16 (đè), 17 (mới)


def test_update_ticker_rejects_mismatched_fallback(tmp_path, monkeypatch):
    up = _updater_or_skip()
    prices_dir, tdir = _seed_warehouse(tmp_path)
    fb.BREAKER.reset()
    monkeypatch.setattr(up, "_fetch_prices", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("Read timed out")))
    monkeypatch.setattr(up, "_fetch_prices_fallback",
                        lambda t, start, end: _df(150.0))   # lệch 25%
    r = up.update_ticker("FPT", prices_dir, date(2026, 7, 17))
    assert r["status"] == "error" and "lệch" in r["error"]
    merged = pd.read_parquet(tdir / "year=2026")
    assert len(merged) == 2                          # kho KHÔNG bị đụng


def test_update_ticker_non_outage_error_no_fallback(tmp_path, monkeypatch):
    up = _updater_or_skip()
    prices_dir, _ = _seed_warehouse(tmp_path)
    fb.BREAKER.reset()
    called = {"fb": 0}
    monkeypatch.setattr(up, "_fetch_prices", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("Invalid symbol FPT")))
    monkeypatch.setattr(up, "_fetch_prices_fallback",
                        lambda *a, **k: called.__setitem__("fb", called["fb"] + 1))
    r = up.update_ticker("FPT", prices_dir, date(2026, 7, 17))
    assert r["status"] == "error" and called["fb"] == 0     # không fallback bừa


def test_update_ticker_kill_switch_keeps_old_behavior(tmp_path, monkeypatch):
    up = _updater_or_skip()
    prices_dir, _ = _seed_warehouse(tmp_path)
    monkeypatch.setenv("VNSTOCK_PRICE_FALLBACK", "0")
    called = {"fb": 0}
    monkeypatch.setattr(up, "_fetch_prices", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("Read timed out")))
    monkeypatch.setattr(up, "_fetch_prices_fallback",
                        lambda *a, **k: called.__setitem__("fb", called["fb"] + 1))
    r = up.update_ticker("FPT", prices_dir, date(2026, 7, 17))
    assert r["status"] == "error" and called["fb"] == 0


def test_update_ticker_breaker_opens_and_skips_primary(tmp_path, monkeypatch):
    up = _updater_or_skip()
    prices_dir, _ = _seed_warehouse(tmp_path)
    fb.BREAKER.reset()
    monkeypatch.setattr(fb.BREAKER, "open_after", 2)
    vci_calls = {"n": 0}

    def _vci_dead(*a, **k):
        vci_calls["n"] += 1
        raise RuntimeError("Read timed out")

    monkeypatch.setattr(up, "_fetch_prices", _vci_dead)
    monkeypatch.setattr(up, "_fetch_prices_fallback",
                        lambda t, start, end: _df(120.0))
    for _ in range(4):                               # 2 mở mạch + 2 khi đã mở
        up.update_ticker("FPT", prices_dir, date(2026, 7, 17))
    assert fb.BREAKER.is_open
    assert vci_calls["n"] == 2                       # mạch mở → VCI không bị gọi thêm
