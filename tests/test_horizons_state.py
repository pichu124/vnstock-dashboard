"""vnstock_horizons_state — brief 3 khung CHẠY BÓNG (P1a): cổng ghi, backfill,
gấp từ input đã lưu, F1/revision, badge doctor, bước `run.py horizons`."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import vnstock_horizons_state as hs


def _bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _write(wh: Path, ticker: str, days, closes):
    df = pd.DataFrame({"time": pd.to_datetime(days), "close": closes,
                       "volume": 1e5, "high": closes, "low": closes})
    for y, g in df.groupby(df.time.dt.year):
        d = wh / "prices" / f"ticker={ticker}" / f"year={y}"
        d.mkdir(parents=True, exist_ok=True)
        g.to_parquet(d / "data.parquet")


@pytest.fixture()
def wh(tmp_path, monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("VNSTOCK_HORIZONS"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COMPUTERNAME", "TESTBOX")
    rng = np.random.default_rng(11)
    days = _bdays(date(2025, 1, 6), 300)
    for k in range(6):
        _write(tmp_path, "T" + "ABCDEF"[k] + "X", days,
               20 * np.exp(np.cumsum(rng.normal(0, 0.02, len(days)))))
    vni = 1200 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(days))))
    _write(tmp_path, "VNINDEX", days, vni)
    (tmp_path / "_meta").mkdir()
    return tmp_path, days


def _evening(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 20, 0)


# ── Cổng ghi ─────────────────────────────────────────────────────────────

def test_update_writes_live_record_with_machine_then_is_a_noop(wh, capsys):
    root, days = wh
    assert hs.update(now=_evening(days[-1]), warehouse=root) == 0
    st = hs.load_state(root)
    key = days[-1].isoformat()
    assert st["inputs"][key]["source"] == "live" and st["inputs"][key]["machine"] == "TESTBOX"
    assert st["published"][-1]["as_of"] == key and st["published"][-1]["source"] == "live"
    before = hs.state_path(root).read_text(encoding="utf-8")
    assert hs.update(now=_evening(days[-1]), warehouse=root) == 0      # máy chạy sau
    assert hs.state_path(root).read_text(encoding="utf-8") == before
    assert "đã có" in capsys.readouterr().out


def test_update_force_rewrites(wh):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    st = hs.load_state(root)
    st["published"][-1]["computed_at"] = "old"
    hs.write_state(st, root)
    assert hs.update(now=_evening(days[-1]), force=True, warehouse=root) == 0
    assert hs.load_state(root)["published"][-1]["computed_at"] != "old"


def test_update_before_close_cutoff_uses_previous_session(wh):
    root, days = wh
    d = days[-1]
    hs.update(now=datetime(d.year, d.month, d.day, 10, 0), warehouse=root)
    assert hs.load_state(root)["published"][-1]["as_of"] == days[-2].isoformat()


def test_update_refuses_short_history(tmp_path):
    days = _bdays(date(2026, 1, 5), 100)
    _write(tmp_path, "VNINDEX", days, np.full(100, 1200.0))
    assert hs.update(now=_evening(days[-1]), warehouse=tmp_path) == 1
    assert not hs.state_path(tmp_path).exists()


def test_update_replaces_a_backfilled_record_with_live(wh):
    root, days = wh
    hs.backfill(5, warehouse=root)
    assert hs.load_state(root)["published"][-1]["source"] == "backfill"
    hs.update(now=_evening(days[-1]), warehouse=root)
    pub = [p for p in hs.load_state(root)["published"] if p["as_of"] == days[-1].isoformat()]
    assert len(pub) == 1 and pub[0]["source"] == "live"


def test_backfill_never_overwrites_live(wh):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    st = hs.load_state(root)
    st["inputs"][days[-1].isoformat()]["score"] = 99          # dấu vết bản live
    hs.write_state(st, root)
    hs.backfill(10, warehouse=root)
    st = hs.load_state(root)
    assert st["inputs"][days[-1].isoformat()]["score"] == 99
    assert st["inputs"][days[-3].isoformat()]["source"] == "backfill"
    assert sum(1 for p in st["published"] if p["as_of"] == days[-1].isoformat()) == 1


# ── Gấp + kiểm ───────────────────────────────────────────────────────────

def test_fold_medium_and_alert_come_from_closes_only(wh):
    root, days = wh
    hs.backfill(20, warehouse=root)
    st = hs.load_state(root)
    base = hs.fold(st["inputs"])
    for k, v in st["inputs"].items():
        if v.get("score") is not None:
            v["score"] = -v["score"]                          # đảo điểm mọi phiên
    other = hs.fold(st["inputs"])
    assert other["medium"] == base["medium"] and other["medium_since"] == base["medium_since"]
    assert other["alert"] == base["alert"] and other["levels"] == base["levels"]


def test_verify_detects_tampered_published_and_revised_close(wh):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    st = hs.load_state(root)
    assert hs.verify(st, root) == {"live": 1, "fold_mismatch": [], "revisions": []}
    st["published"][-1]["medium"] = 9
    key = days[-5].isoformat()
    st["inputs"][key]["close"] = st["inputs"][key]["close"] * 1.01
    v = hs.verify(st, root)
    assert v["fold_mismatch"] == [days[-1].isoformat()] and v["revisions"] == [key]


def test_state_write_is_atomic_and_corrupt_file_loads_empty(wh):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    assert not list((root / "_meta").glob("*.tmp"))
    hs.state_path(root).write_text("{not json", encoding="utf-8")
    assert hs.load_state(root) == {"version": hs.SCHEMA_VERSION, "inputs": {}, "published": []}


def test_kill_switch_skips_update(wh, monkeypatch):
    monkeypatch.setenv("VNSTOCK_HORIZONS_STEP", "0")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)   # .env máy thật không lọt
    called = []
    monkeypatch.setattr(hs, "update", lambda **k: called.append(k) or 0)
    assert hs.main(["--update"]) == 0 and not called


# ── Hàm đọc dùng chung (P1b-1, #19) ─────────────────────────────────────

def test_latest_published_tells_missing_empty_fresh_stale_and_conflicted(wh):
    root, days = wh
    lp = hs.latest_published(root, now=_evening(days[-1]))
    assert lp.snap is None and lp.missing == "chưa có state" and not lp.usable
    hs.write_state({"inputs": {}, "published": []}, root)
    lp = hs.latest_published(root, now=_evening(days[-1]))
    assert lp.snap is None and lp.missing == "state rỗng" and not lp.usable

    hs.update(now=_evening(days[-2]), warehouse=root)
    lp = hs.latest_published(root, now=_evening(days[-2]))
    assert lp.usable and not lp.stale and lp.snap["as_of"] == days[-2].isoformat()
    assert lp.state["published"][-1] is lp.snap

    lp = hs.latest_published(root, now=_evening(days[-1]))      # kho đã có bar mới hơn
    assert lp.stale and not lp.usable and lp.expect == days[-1]

    assert lp.reason == f"cũ: bản cuối {days[-2].isoformat()}, kho đã có bar {days[-1]}"

    (root / "_meta" / "horizon_state (PICHU's conflicted copy).json").write_text("{}")
    lp = hs.latest_published(root, now=_evening(days[-2]))
    assert lp.conflicted and not lp.stale and not lp.usable
    assert lp.reason.startswith("conflicted copy: horizon_state (PICHU")


def test_latest_published_tells_a_broken_file_apart_from_an_empty_one(wh):
    root, days = wh
    hs.state_path(root).write_text("{not json", encoding="utf-8")
    lp = hs.latest_published(root, now=_evening(days[-1]))
    assert lp.snap is None and lp.missing == hs.BROKEN_STATE and lp.reason == hs.BROKEN_STATE


def test_doctor_stays_warn_when_the_reader_blows_up(doc, wh, monkeypatch):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    monkeypatch.setattr(hs, "load_vnindex", lambda wh: 1 / 0)
    r = doc.check_horizons(now=_evening(days[-1]))
    assert r["status"] == "warn" and "ZeroDivisionError" in r["message"]


# ── Doctor ───────────────────────────────────────────────────────────────

@pytest.fixture()
def doc(wh, monkeypatch):
    import vnstock_doctor as d
    root, _ = wh
    monkeypatch.setattr(d, "_META", root / "_meta")
    return d


def test_doctor_warns_when_state_missing(doc, wh):
    r = doc.check_horizons(now=_evening(wh[1][-1]))
    assert r["status"] == "warn" and "--backfill" in r["fix"]
    assert r["message"] == "chưa có state (P1a vừa merge?)"     # câu chữ như trước P1b-1


def test_doctor_ok_after_update_then_stale_when_kho_moves_ahead(doc, wh):
    root, days = wh
    hs.update(now=_evening(days[-2]), warehouse=root)
    assert doc.check_horizons(now=_evening(days[-2]))["status"] == "ok"
    r = doc.check_horizons(now=_evening(days[-1]))
    assert r["status"] == "warn" and "cũ" in r["message"]


def test_doctor_flags_conflicted_copy_and_off_switch(doc, wh, monkeypatch):
    root, days = wh
    hs.update(now=_evening(days[-1]), warehouse=root)
    (root / "_meta" / "horizon_state (PICHU's conflicted copy).json").write_text("{}")
    r = doc.check_horizons(now=_evening(days[-1]))
    assert r["status"] == "warn" and "conflicted" in r["message"]
    monkeypatch.setenv("VNSTOCK_HORIZONS_STEP", "0")
    assert doc.check_horizons()["status"] == "off"
    assert doc.check_horizons in doc.OFFLINE_CHECKS


# ── run.py ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ns,expect", [
    (SimpleNamespace(), ["--update"]),
    (SimpleNamespace(force=True), ["--update", "--force"]),
    (SimpleNamespace(backfill=True, days=30), ["--backfill", "--days", "30"]),
    (SimpleNamespace(show=True), ["--show"]),
    (SimpleNamespace(replay=True), ["--replay"]),
])
def test_runpy_cmd_horizons_builds_the_right_call(monkeypatch, ns, expect):
    import run as runpy
    seen = []
    monkeypatch.setattr(runpy, "_run", lambda cmd: seen.append(cmd) or 0)
    assert runpy.cmd_horizons(ns) == 0
    assert seen[0][1].endswith("vnstock_horizons_state.py") and seen[0][2:] == expect


def test_runpy_horizons_step_never_hard_fails_and_is_wired(monkeypatch):
    import run as runpy
    monkeypatch.setattr(runpy, "_run", lambda cmd: 2)
    assert runpy.cmd_horizons(SimpleNamespace()) == 1
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    # U82 (09/10): bước `assets` (kho đa tài sản) chen giữa gold và horizons
    assert names.index("gold") < names.index("assets") < names.index("horizons")
    assert names.index("horizons") < names.index("allocation") < names.index("brief")
    args = runpy.build_parser().parse_args(["horizons", "--backfill", "--days", "50"])
    assert args.backfill and args.days == 50 and runpy._DISPATCH["horizons"] is runpy.cmd_horizons
    assert "tests/test_horizons_state.py" in open(runpy.__file__, encoding="utf-8").read()
