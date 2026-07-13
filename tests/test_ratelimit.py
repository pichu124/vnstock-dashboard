"""Tests for vnstock_ratelimit — chịu đòn rate-limit vnai (SystemExit!).

Fixture = message THẬT từ vnai/beam/quota.py (bản sys.exit thấy 13/07 khi
cập nhật giá chết ở 558/1724 mã). Điểm sống còn: helper phải bắt được
SystemExit (BaseException) — except Exception thường KHÔNG bắt được nó.
"""
from __future__ import annotations

import pytest

import vnstock_ratelimit as rl


# Đúng chuỗi vnai in + sys.exit trên máy user 13/07 (rút gọn phần khung)
_VNAI_MSG = (
    "Rate limit exceeded. \n"
    "⚠️  GIỚI HẠN API ĐÃ ĐẠT TỐI ĐA (Rate Limit Exceeded)\n"
    "   • Giới hạn: 500 requests/phút\n"
    "   • Đã sử dụng: 500/500\n"
    "   • Chờ 54 giây để tiếp tục (Wait to retry)\n"
    " Process terminated."
)


def test_is_rate_limit_and_wait_parse():
    exc = SystemExit(_VNAI_MSG)
    assert rl.is_rate_limit(exc)
    assert rl.wait_seconds(exc) == 56              # 54 + 2s đệm
    assert not rl.is_rate_limit(ValueError("mạng chặn"))
    # message không có số giây → fallback 61s; số khổng lồ → cap 300s
    assert rl.wait_seconds(SystemExit("Rate limit exceeded.")) == rl._DEFAULT_WAIT
    assert rl.wait_seconds(SystemExit("Rate limit. Chờ 3600 giây")) == rl._MAX_WAIT


def test_retry_survives_vnai_systemexit_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(rl.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise SystemExit(_VNAI_MSG)            # vnai sys.exit 2 lần đầu
        return "ok"

    waits = []
    out = rl.call_with_rate_limit_retry(_flaky, on_wait=lambda w, i: waits.append((w, i)))
    assert out == "ok" and calls["n"] == 3
    assert sleeps == [56, 56]                      # ngủ theo message vnai
    assert waits == [(56, 1), (56, 2)]


def test_retry_exhausted_becomes_plain_exception(monkeypatch):
    monkeypatch.setattr(rl.time, "sleep", lambda s: None)

    def _always():
        raise SystemExit(_VNAI_MSG)

    # Hết lượt chờ → RuntimeError (Exception THƯỜNG) — vòng per-ticker của
    # updater bắt được, 1 mã lỗi thay vì chết cả run
    with pytest.raises(RuntimeError) as ei:
        rl.call_with_rate_limit_retry(_always, retries=2)
    assert isinstance(ei.value, Exception)
    assert "rate limit" in str(ei.value).lower()


def test_non_rate_limit_errors_reraised_verbatim(monkeypatch):
    monkeypatch.setattr(rl.time, "sleep", lambda s: None)
    with pytest.raises(ValueError):
        rl.call_with_rate_limit_retry(lambda: (_ for _ in ()).throw(ValueError("x")))
    # SystemExit THẬT (không phải rate-limit) phải thoát nguyên vẹn
    with pytest.raises(SystemExit):
        rl.call_with_rate_limit_retry(lambda: (_ for _ in ()).throw(SystemExit("bye")))
    with pytest.raises(KeyboardInterrupt):
        rl.call_with_rate_limit_retry(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt()))


def test_price_updater_survives_rate_limit_systemexit(tmp_path, monkeypatch):
    """update_ticker: vnai sys.exit giữa fetch → chờ (patched) rồi thành công;
    hết lượt → status='error' chứ KHÔNG SystemExit lọt ra ngoài."""
    import pandas as pd

    # vnstock_updater hard-requires vnstock at import time — skip sạch trên
    # môi trường không có (sandbox/CI); chạy đủ trên máy dev (convention của
    # test_updater_partial_bar).
    up = pytest.importorskip("vnstock_updater")

    monkeypatch.setattr(rl.time, "sleep", lambda s: None)
    tdir = tmp_path / "prices" / "ticker=AAA" / "year=2026"
    tdir.mkdir(parents=True)
    pd.DataFrame({"time": [pd.Timestamp("2026-07-09")], "open": [1.0],
                  "high": [1.0], "low": [1.0], "close": [1.0],
                  "volume": [100]}).to_parquet(tdir / "d.parquet")

    calls = {"n": 0}

    def _flaky_fetch(ticker, start, end):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit(_VNAI_MSG)
        return pd.DataFrame()                       # lần 2: hết rate-limit

    monkeypatch.setattr(up, "_fetch_prices", _flaky_fetch)
    from datetime import date
    res = up.update_ticker("AAA", tmp_path / "prices", date(2026, 7, 13))
    assert res["status"] == "no_new_data" and calls["n"] == 2

    def _always_limited(ticker, start, end):
        raise SystemExit(_VNAI_MSG)

    monkeypatch.setattr(up, "_fetch_prices", _always_limited)
    res2 = up.update_ticker("AAA", tmp_path / "prices", date(2026, 7, 13))
    assert res2["status"] == "error" and "rate limit" in res2["error"].lower()


def test_fundamental_fetch_one_survives_rate_limit(monkeypatch):
    import vnstock_fundamental_updater as fu

    monkeypatch.setattr(rl.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def _flaky_ratios(ticker):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit(_VNAI_MSG)
        return {"pe": 10.0, "roe": 15.0}

    monkeypatch.setattr(fu, "_fetch_ratios", _flaky_ratios)
    monkeypatch.setattr(fu, "_fetch_cash_flow", lambda t: {})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: None)
    ticker, data, err = fu._fetch_one("VCB", delay=0.0)
    assert err is None and data["pe"] == 10.0 and calls["n"] == 2
