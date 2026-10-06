"""scripts/replay_horizons.py — P0 brief 3 khung, chỉ đọc kho.

Chỗ dễ sai nhất là breadth tái dựng THEO NGÀY: nó dùng mẹo EMA cửa sổ O(1)
thay cho việc tính lại EMA200 cho từng (mã, phiên). Test so với cách đếm
nguyên bản của `vnstock_runner.compute_market_overview` làm tay từng phiên.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "replay_horizons", Path(__file__).resolve().parent.parent / "scripts" / "replay_horizons.py")
rh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rh)


def _bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _write(wh: Path, ticker: str, days: list[date], closes, extra_copy=False):
    df = pd.DataFrame({"time": pd.to_datetime(days), "close": closes,
                       "volume": 1e5, "high": closes, "low": closes})
    for y, g in df.groupby(df.time.dt.year):
        d = wh / "prices" / f"ticker={ticker}" / f"year={y}"
        d.mkdir(parents=True, exist_ok=True)
        g.to_parquet(d / "data.parquet")
        if extra_copy:
            g.tail(3).to_parquet(d / "data (conflicted copy).parquet")


@pytest.fixture()
def warehouse(tmp_path):
    rng = np.random.default_rng(5)
    days = _bdays(date(2024, 1, 1), 520)
    for k in range(12):
        x = 20 * np.exp(np.cumsum(rng.normal(0, 0.02, len(days))))
        if k == 2:
            x = x * 1000                       # mã lưu đơn vị VND
        sub = slice(None) if k != 4 else slice(-150, None)   # mã non <200 bar
        _write(tmp_path, "T" + "ABCDEFGHIJKL"[k] + "X", days[sub], x[sub],
               extra_copy=(k == 1))
    _write(tmp_path, "E1VFVN30", days, np.full(len(days), 20.0))  # ETF: bị loại
    vni = 1200 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days))))
    _write(tmp_path, "VNINDEX", days, vni, extra_copy=True)
    (tmp_path / "_meta").mkdir()
    return tmp_path, days


def _brute_breadth(wh: Path, d: date) -> dict:
    total = above = adv = dec = 0
    for td in sorted((wh / "prices").glob("ticker=*")):
        tk = td.name.split("=", 1)[1]
        if len(tk) > 5 or not tk.isalpha():
            continue
        df = rh._read_ticker(td)
        df = df[(df.time <= pd.Timestamp(d))
                & (df.time >= pd.Timestamp(d - timedelta(days=400)))]
        if len(df) < 5:
            continue
        c = df.close.astype(float)
        c = c.where(c <= 500, c / 1000)
        total += 1
        if len(c) >= 200 and c.iloc[-1] > c.ewm(span=200, adjust=False).mean().iloc[-1]:
            above += 1
        chg = c.iloc[-1] - c.iloc[-2]
        adv += chg > 0
        dec += chg < 0
    return {"total": total, "above": above, "adv": adv, "dec": dec}


def test_breadth_history_matches_runner_counting(warehouse):
    wh, days = warehouse
    targets = days[-60:]
    got = rh.breadth_history(wh, targets)
    for d in targets[::7] + [targets[-1]]:
        exp = _brute_breadth(wh, d)
        g = got[d]
        assert g["total"] == exp["total"]
        assert round(g["above_ma200_pct"] * g["total"] / 100) == exp["above"]
        assert (g["advances"], g["declines"]) == (exp["adv"], exp["dec"])


def test_load_vnindex_dedupes_conflicted_copies(warehouse):
    wh, days = warehouse
    dates, closes = rh.load_vnindex(wh)
    assert dates == days and len(closes) == len(days)


def test_printed_briefs_reads_latest_valid_row_read_only(warehouse):
    wh, _ = warehouse
    import vnstock_memory as mem
    db = wh / "_meta" / "brief_memory.db"
    con = sqlite3.connect(db)
    con.executescript(mem._SCHEMA)
    ctx = json.dumps({"bias_floor": {"dir": "GIẢM"}, "breadth": {"above_ma200_pct": 20.0}})
    rows = [("2026-09-24T21:00", "TĂNG", None), ("2026-09-24T22:00", "GIẢM", None),
            ("2026-09-24T23:00", "TĂNG", "boom")]       # bản lỗi mới nhất bị bỏ
    for ts, st, err in rows:
        con.execute("INSERT INTO briefs(created_at,brief_date,brief_type,agent_name,"
                    "agent_type,output,error,context_json) VALUES (?,?,?,?,?,?,?,?)",
                    (ts, "2026-09-24", "afternoon", "claude", "claude",
                     f"## 🎯 TLDR\n- Stance ngày mai: {st}\n", err, ctx))
    con.commit(); con.close()
    before = db.stat().st_mtime_ns
    got = rh.printed_briefs(wh)["2026-09-24"]
    assert got["stance"] == "GIẢM" and got["floor"] == "GIẢM" and got["breadth_pct"] == 20.0
    assert db.stat().st_mtime_ns == before


def test_main_smoke_prints_states_and_levels(warehouse, capsys, tmp_path):
    wh, days = warehouse
    out_csv = tmp_path / "out.csv"
    rc = rh.main(["--warehouse", str(wh), "--from", days[-40].isoformat(),
                  "--table", "--csv", str(out_csv)])
    text = capsys.readouterr().out
    assert rc == 0
    assert "Trung hạn:" in text and "mức tuần tới" in text and "Vùng phẳng" in text
    assert len(pd.read_csv(out_csv)) == 40


def test_main_refuses_short_history(tmp_path, capsys):
    _write(tmp_path, "VNINDEX", _bdays(date(2026, 1, 1), 50), np.full(50, 1200.0))
    assert rh.main(["--warehouse", str(tmp_path), "--no-grid"]) == 2
