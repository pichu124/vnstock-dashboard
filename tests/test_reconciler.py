"""Tests for vnstock_reconciler cross-reference logic."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vnstock_reconciler import (
    _classify, _load_api_daily, _normalise_units, _pct_diff, reconcile,
)


def test_pct_diff_symmetric():
    assert _pct_diff(100.0, 101.0) == 1.0
    assert _pct_diff(100.0, 99.0) == 1.0


def test_pct_diff_nan_and_zero():
    assert _pct_diff(None, 10) is None
    assert _pct_diff(10, None) is None
    assert _pct_diff(0.0, 5.0) is None


def test_classify_ok_within_tolerance():
    sev, _ = _classify(close_diff=0.1, volume_diff=1.0)
    assert sev == "ok"


def test_classify_warn_on_volume_only_when_enabled():
    # Default: volume ignored
    sev, reason = _classify(close_diff=0.1, volume_diff=10.0)
    assert sev == "ok"
    assert "volume drift" not in reason

    # Enabled: volume pushes to warn
    sev, reason = _classify(close_diff=0.1, volume_diff=10.0, check_volume=True)
    assert sev == "warn"
    assert "volume drift" in reason


def test_classify_volume_fail_only_when_enabled():
    # Default: 200% volume drift is ignored
    sev, _ = _classify(close_diff=0.1, volume_diff=200.0)
    assert sev == "ok"

    # Enabled: 200% volume drift → fail
    sev, _ = _classify(close_diff=0.1, volume_diff=200.0, check_volume=True)
    assert sev == "fail"


def test_classify_fail_on_close():
    sev, reason = _classify(close_diff=5.0, volume_diff=None)
    assert sev == "fail"
    assert "close drift" in reason


def test_classify_close_fail_always_wins():
    # Even with volume checking enabled, close fail takes priority
    sev, _ = _classify(close_diff=5.0, volume_diff=10.0, check_volume=True)
    assert sev == "fail"


# ── unit normalisation ────────────────────────────────────────────────────
# Kho (api) chuẩn hoá ở loader trên chuỗi dài; rolled (WSS, VND thô) theo tỷ lệ với close api
# cùng mã. Ngưỡng cứng "close > 500 ⇒ /1000" sai với HLB 660 nghìn và với mã penny 400 đ.

def test_normalise_rescales_rolled_against_api_close():
    api = pd.DataFrame({
        "ticker": ["AAA", "FPT", "HLB", "AVF"],
        "close": [7.12, 120.0, 660.0, 0.4],
    })
    rolled = pd.DataFrame({
        "ticker": ["AAA", "FPT", "HLB", "AVF", "NEW"],
        "close": [7120.0, 120000.0, 660000.0, 400.0, 9000.0],
    })
    rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is True
    # NEW không có api cùng mã ⇒ không mốc ⇒ ngưỡng như cũ.
    assert rolled_out["close"].tolist() == pytest.approx([7.12, 120.0, 660.0, 0.4, 9.0])
    assert rolled["close"].iloc[0] == 7120.0        # bản gốc không bị sửa


def test_normalise_keeps_rolled_already_in_thousand():
    """Bar tổng hợp của wss_backfill chép close kho (nghìn): HLB 660 giữ nguyên."""
    api = pd.DataFrame({"ticker": ["AAA", "HLB"], "close": [7.12, 660.0]})
    rolled = pd.DataFrame({"ticker": ["AAA", "HLB"], "close": [7.15, 660.0]})
    rolled_out, rescaled = _normalise_units(api, rolled)
    assert rescaled is False
    assert rolled_out["close"].tolist() == [7.15, 660.0]


def test_normalise_handles_empty_frames():
    empty = pd.DataFrame(columns=["ticker", "close"])
    one = pd.DataFrame({"ticker": ["X"], "close": [7.12]})
    assert _normalise_units(empty, one)[1] is False
    assert _normalise_units(one, empty)[1] is False


def test_load_api_daily_normalises_on_ticker_history(tmp_path):
    """Kho trộn đơn vị: B có bar VND sót (5600) giữa chuỗi nghìn; X chỉ 1 bar VND, không có
    mốc ⇒ chia như luật cũ; HLB 660 nghìn có mốc ≤ 500 trong chuỗi ⇒ giữ."""
    d = date(2026, 4, 20)
    hist = [date(2026, 4, k) for k in range(1, 18)]
    _seed_history(tmp_path, "B", [(h, 5.5) for h in hist] + [(d, 5600.0)])
    _seed_history(tmp_path, "X", [(d, 7120.0)])
    _seed_history(tmp_path, "HLB", [(h, 300.0) for h in hist] + [(d, 660.0)])
    api = _load_api_daily(tmp_path, None, [d]).set_index("ticker")["close"]
    assert api.to_dict() == pytest.approx({"B": 5.6, "X": 7.12, "HLB": 660.0})


@pytest.mark.parametrize("ticker, history, target, close, rolled_close", [
    # HLB 660 nghìn: luật cũ chia api còn 0.66, rolled 660.000 đ ra 660 ⇒ "lệch 99,9%" giả.
    ("HLB", [(date(2026, 4, k), 300.0) for k in range(1, 18)], date(2026, 4, 20), 660.0, 660_000.0),
    # Đầu năm toàn bar > 500 nghìn ⇒ mốc đơn vị phải lấy từ năm trước.
    ("VNZ", [(date(2026, 12, k), 400.0) for k in range(1, 25)] + [(date(2027, 1, 4), 570.0)],
     date(2027, 1, 5), 579.0, 579_000.0),
    # Mã penny: rolled 400 đ ≤ 500 không bị chia ⇒ "lệch" 1000× giả.
    ("AVF", [(date(2026, 4, k), 0.4) for k in range(1, 18)], date(2026, 4, 20), 0.4, 400.0),
])
def test_reconcile_price_units_follow_ticker_reference(
        tmp_path, ticker, history, target, close, rolled_close):
    _seed_history(tmp_path, ticker, history + [(target, close)])
    _seed_rolled(tmp_path, target, [{
        "time": pd.Timestamp(target), "ticker": ticker, "close": rolled_close,
        "volume": 1_000, "open": rolled_close, "high": rolled_close, "low": rolled_close,
    }])
    report = reconcile(tmp_path, dates=[target])
    assert (report.ok, report.warn, report.fail) == (1, 0, 0), report.discrepancies


# ── Smart WSS-miss detection (Option E) ────────────────────────────────────

def _seed_warehouse(path: Path, ticker: str, d: date, close: float, volume: int):
    year_dir = path / "prices" / f"ticker={ticker}" / f"year={d.year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "time": [pd.Timestamp(d)],
        "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [volume],
    })
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   year_dir / "p.parquet")



def _seed_history(path: Path, ticker: str, rows: list[tuple[date, float]], volume: int = 1_000):
    """Nhiều bar/mã, chia file theo năm; OHLC float32 như kho thật."""
    df = pd.DataFrame({"time": [pd.Timestamp(d) for d, _ in rows], "close": [c for _, c in rows]})
    df = df.assign(open=df["close"], high=df["close"], low=df["close"], volume=volume).astype(
        {c: "float32" for c in ("open", "high", "low", "close")})
    for year, g in df.groupby(df["time"].dt.year):
        year_dir = path / "prices" / f"ticker={ticker}" / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(g, preserve_index=False), year_dir / "p.parquet")

def _seed_rolled(path: Path, d: date, rows: list[dict]):
    live_dir = path / "_live"
    live_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    df = pd.DataFrame(rows)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   live_dir / f"bars_{d.isoformat()}.parquet")


def test_wss_miss_counted_as_missing_not_fail(tmp_path):
    """When rolled_volume=0 AND api_volume>0, treat as missing_in_rolled
    not fail. This is the Option E fix: WSS didn't capture the session,
    so the close comparison is meaningless."""
    d = date(2026, 4, 20)

    # API has real data
    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=1_000_000)

    # Rolled has a degenerate row: volume=0, stale close
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 75.0,                # stale, differs from API
        "volume": 0,                  # ← the signal
        "open": 75.0, "high": 75.0, "low": 75.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, f"WSS-miss should not be a fail, got {report.fail}"
    assert report.missing_in_rolled >= 1, \
        f"WSS-miss should increment missing_in_rolled, got {report.missing_in_rolled}"


def test_real_drift_still_flagged_when_both_sides_have_volume(tmp_path):
    """A genuine close drift (both sides have volume > 0) still trips fail."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=1_000_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 85.0,                # +9.4% close drift
        "volume": 500_000,            # non-zero rolled volume
        "open": 85.0, "high": 85.0, "low": 85.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail >= 1 or report.warn >= 1, \
        "A real 9.4% close drift must still surface"


def test_wss_partial_miss_downgraded_from_fail_to_warn(tmp_path):
    """Rolled captured < 50% of API volume → rolled_close is a random
    intraday tick, not the session close. Don't flag as fail even if
    close drift is huge. This is the PNJ 2026-04-20 case: rolled
    captured 4.5% of volume, showing 46% close drift — which is infra
    noise, not a data bug."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "PNJ", d, close=76.67, volume=1_870_506)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "PNJ",
        "close": 112.5,                # huge apparent drift
        "volume": 83_284,              # only 4.5% of API volume
        "open": 112.5, "high": 112.5, "low": 112.5,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, "wss_partial_miss must not escalate to fail"
    assert report.warn >= 1, "significant close drift should still surface as warn"
    disc = [d for d in report.discrepancies if d.ticker == "PNJ"]
    assert disc, "PNJ row must be reported"
    assert "wss_partial_miss" in disc[0].reason
    assert disc[0].severity == "warn"


def test_wss_partial_miss_stays_ok_when_close_within_tolerance(tmp_path):
    """If WSS captured little volume but happened to land on a tick near
    the real close, the row is silently OK — no noise."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VIC", d, close=191.0, volume=5_425_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VIC",
        "close": 190.9,                # within tolerance
        "volume": 902_582,             # 16.6% of API — under floor
        "open": 190.9, "high": 190.9, "low": 190.9,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0
    # No discrepancy recorded for ok rows
    assert not any(d.ticker == "VIC" for d in report.discrepancies)


def test_wss_atc_miss_detected_at_75pct_capture(tmp_path):
    """Realistic ATC (auction-at-close) miss: WSS caught most of the
    session but dropped the closing auction, leaving rolled_close as
    the pre-ATC tick. HPT 2026-04-20 had ~75% coverage and 3.70% drift —
    must be classified as wss_partial_miss, not a real fail."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "HPT", d, close=27.0, volume=4000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "HPT",
        "close": 28.0,                 # pre-ATC tick
        "volume": 3000,                # 75% captured — above the old 50% floor
        "open": 28.0, "high": 28.0, "low": 28.0,
    }])

    report = reconcile(tmp_path, dates=[d])
    assert report.fail == 0, "ATC miss must not escalate to fail"
    disc = [d for d in report.discrepancies if d.ticker == "HPT"]
    assert disc and "wss_partial_miss" in disc[0].reason


def test_reconciler_respects_anomaly_whitelist(tmp_path):
    """User accepting a (ticker, date) via `remediate --action accept`
    should stop BOTH the anomaly scan AND the reconciler from re-flagging
    it. Otherwise the operator has to accept twice for one event."""
    from vnstock_remediate import add_to_whitelist

    d = date(2026, 4, 15)

    # Real genuine drift — without the whitelist, this should fail.
    _seed_warehouse(tmp_path, "SBT", d, close=20.66, volume=500_000)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d), "ticker": "SBT",
        "close": 21.9, "volume": 500_000,     # both have vol → real drift
        "open": 21.9, "high": 21.9, "low": 21.9,
    }])

    # 1) Without whitelist entry — expect fail (close drift 6%)
    r = reconcile(tmp_path, dates=[d])
    assert r.fail >= 1, "genuine drift must fire before whitelist"

    # 2) Whitelist the entry and re-run — must NOT fail anymore
    add_to_whitelist("SBT", d, kind="band", warehouse=tmp_path,
                      note="WSS corrupted rolled")
    r2 = reconcile(tmp_path, dates=[d])
    assert r2.fail == 0, "whitelisted entry must be skipped by reconciler"
    assert r2.ok >= 1


def test_both_zero_volume_not_counted_as_wss_miss(tmp_path):
    """If api_volume is ALSO 0 (holiday / halted ticker), don't reclassify
    as WSS-miss — nothing to miss. Goes through normal classification."""
    d = date(2026, 4, 20)

    _seed_warehouse(tmp_path, "VCB", d, close=77.7, volume=0)
    _seed_rolled(tmp_path, d, [{
        "time": pd.Timestamp(d),
        "ticker": "VCB",
        "close": 77.7,
        "volume": 0,
        "open": 77.7, "high": 77.7, "low": 77.7,
    }])

    report = reconcile(tmp_path, dates=[d])
    # No fail expected — close matches — but also not a missing_in_rolled
    # because the premise "api_volume > 0" doesn't hold.
    assert report.fail == 0
    assert report.ok >= 1
