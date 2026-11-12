"""P0 PTKT — thước đo nhận định kỹ thuật (`vnstock_ta_score` + `_io`) và cột `briefs.sent`.

Mọi test chạy trên dữ liệu tổng hợp, không cần kho (cloud không có data_warehouse/)."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

import vnstock_memory as vm


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    db = tmp_path / "brief_memory.db"
    monkeypatch.setattr(vm, "DB_PATH", db)
    return db


def _save(date_="2026-10-01", agent="Gemini", btype="afternoon", output="x" * 50, ctx=None):
    return vm.save_brief(date_, btype, agent, "gemini", "m", "p", output, None, ctx or {})


# ── Cột sent + mark_sent ────────────────────────────────────────────────

def test_sent_column_added_to_existing_db_without_it(mem_db):
    c = sqlite3.connect(mem_db)
    c.execute("CREATE TABLE briefs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT "
              "NULL, brief_date TEXT NOT NULL, brief_type TEXT NOT NULL, agent_name TEXT NOT "
              "NULL, agent_type TEXT NOT NULL, model TEXT, prompt TEXT, output TEXT, error TEXT,"
              " context_json TEXT, auto_score REAL, user_rating INTEGER, user_feedback TEXT)")
    c.execute("INSERT INTO briefs (created_at, brief_date, brief_type, agent_name, agent_type) "
              "VALUES ('t', '2026-01-02', 'afternoon', 'A', 'a')")
    c.commit()
    c.close()
    vm.init_db()
    vm.init_db()                                          # chạy lại: không ALTER lần hai
    c = sqlite3.connect(mem_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(briefs)")]
    assert cols.count("sent") == 1
    assert c.execute("SELECT sent FROM briefs").fetchone() == (None,)


def test_mark_sent_by_id_and_by_key(mem_db):
    a = _save(agent="Gemini")
    b = _save(agent="Claude Opus")
    other = _save(agent="Claude Opus", date_="2026-10-02")
    assert vm.mark_sent(a) == 1
    assert vm.mark_sent(brief_date="2026-10-01", brief_type="afternoon",
                        agent_name="Claude Opus") == 1
    sent = {r["id"]: r["sent"] for r in vm.recent_briefs(limit=10)}
    assert sent == {a: 1, b: 1, other: None}


def test_mark_sent_requires_id_or_full_key(mem_db):
    with pytest.raises(ValueError):
        vm.mark_sent(brief_date="2026-10-01")


def test_mark_brief_sent_marks_row_after_cmd_brief_sends(mem_db, tmp_path, monkeypatch):
    import run as runpy
    bid = _save(agent="Claude Opus")
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))

    def _send(args):
        args.brief_id = bid
        return {"result": {"message_id": 3}}, "claude"
    monkeypatch.setattr(runpy, "_send_close_brief", _send)
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    assert vm.recent_briefs(limit=1)[0]["sent"] == 1


def test_sent_ledger_failure_never_blocks_send_or_marker(mem_db, tmp_path, monkeypatch, capsys):
    import run as runpy
    _save()
    monkeypatch.delenv("VNSTOCK_PIPELINE_BRIEF", raising=False)
    monkeypatch.setattr(runpy, "_should_push_close", lambda now, m, **kw: (True, ""))
    sent = []

    def _send(args):
        sent.append(1)
        args.brief_id = 1
        return {"result": {"message_id": 3}}, "ladder"

    def _boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(runpy, "_send_close_brief", _send)
    monkeypatch.setattr(vm, "mark_sent", _boom)
    args = SimpleNamespace(warehouse=str(tmp_path))
    assert runpy.cmd_brief(args) == 0
    assert sent == [1]
    marker = json.loads(runpy._brief_push_marker(args).read_text(encoding="utf-8"))
    assert marker["engine"] == "ladder"
    assert "database is locked" in capsys.readouterr().out
    # lệnh tay `telegram close` cũng vậy
    runpy._brief_push_marker(args).unlink()
    assert runpy.cmd_telegram(SimpleNamespace(warehouse=str(tmp_path), action="close",
                                              force=False)) == 0
    assert runpy._brief_push_marker(args).exists()


def test_mark_brief_sent_does_not_create_missing_db(tmp_path, monkeypatch):
    import run as runpy
    db = tmp_path / "none.db"
    monkeypatch.setattr(vm, "DB_PATH", db)
    runpy._mark_brief_sent(SimpleNamespace(brief_id=4))
    assert not db.exists()


def test_ladder_path_carries_brief_id_of_chosen_agent(monkeypatch):
    import run as runpy
    import vnstock_brief as vb
    import vnstock_telegram as tg
    monkeypatch.setattr(vb, "generate_brief", lambda **kw: {
        "Groq": ("", "429"), "Gemini": ("## TLDR\nStance ngày mai: TĂNG", None),
        "_brief_ids": {"Groq": 11, "Gemini": 12}})
    tg._brief_snippet("afternoon")
    assert (tg.LAST_BRIEF_AGENT, tg.LAST_BRIEF_ID) == ("Gemini", 12)

    def _push():
        tg.LAST_BRIEF_ID = 12
        return {"result": {"message_id": 1}}
    monkeypatch.setattr(runpy, "_brief_engine", lambda args: "ladder")
    monkeypatch.setattr(tg, "push_close_brief", _push)
    args = SimpleNamespace(warehouse="x")
    assert runpy._send_close_brief(args)[1] == "ladder"
    assert args.brief_id == 12


# ── Dữ liệu tổng hợp ────────────────────────────────────────────────────

import numpy as np  # noqa: E402

import vnstock_ta_score as ts  # noqa: E402
import vnstock_ta_score_io as tio  # noqa: E402


def _bars(rows, start="2026-01-05", volume=None):
    """rows = [(open, high, low, close)] theo ngày làm việc."""
    t = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", t)
    if volume is not None:
        df["volume"] = volume
    return df


def _flat(n, px=100.0):
    return [(px, px, px, px)] * n


# ── Thống kê ────────────────────────────────────────────────────────────

def test_wilson_interval_known_values():
    assert ts.wilson(0, 0) is None
    lo, hi = ts.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    assert ts.rate(0, 0) == {"k": 0, "n": 0, "rate": None, "ci": None}


# ── T1 ──────────────────────────────────────────────────────────────────

def test_score_levels_support_held_pierced_untouched():
    held = _bars([(101, 102, 99.5, 100.5)] + _flat(4, 101))           # chạm 100, đóng trên
    shallow = _bars([(101, 101, 99.0, 99.6)] + _flat(4, 101))         # đóng dưới 0,4% — chưa xuyên
    pierced = _bars([(101, 102, 99.5, 101)] + [(100, 100, 99, 99.4)] + _flat(3, 99))
    away = _bars(_flat(5, 103))
    assert ts.score_levels(held, 100, "support") == ts.HELD
    assert ts.score_levels(shallow, 100, "support") == ts.HELD
    assert ts.score_levels(pierced, 100, "support") == ts.PIERCED
    assert ts.score_levels(away, 100, "support") == ts.UNTOUCHED
    assert ts.score_levels(away.iloc[:4], 100, "support") is None     # chưa đủ 5 phiên
    with pytest.raises(ValueError):
        ts.score_levels(away, 100, "up")


def test_score_levels_resistance_mirror_and_window():
    held = _bars([(99, 100.2, 98, 99.5)] + _flat(4, 99))
    pierced = _bars([(99, 101, 98, 100.6)] + _flat(4, 100))
    late = _bars(_flat(5, 99) + [(99, 102, 99, 101.5)])                # xuyên ở phiên 6 ⇒ ngoài cửa sổ
    assert ts.score_levels(held, 100, "resistance") == ts.HELD
    assert ts.score_levels(pierced, 100, "resistance") == ts.PIERCED
    assert ts.score_levels(late, 100, "resistance") == ts.UNTOUCHED


def test_level_summary_hold_rate_excludes_untouched():
    s = ts.level_summary([ts.HELD, ts.HELD, ts.PIERCED, ts.UNTOUCHED, None])
    assert (s["n"], s["held"], s["pierced"], s["untouched"]) == (4, 2, 1, 1)
    assert s["hold_if_touched"]["rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["touch"]["rate"] == 0.75


def test_fake_levels_seeded_same_distance():
    rng = np.random.default_rng(1)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    bars = _bars([(x, x * 1.01, x * 0.99, x) for x in c])
    a = ts.fake_level_outcomes(bars, 2.0, "support", k=15, seed=7)
    b = ts.fake_level_outcomes(bars, 2.0, "support", k=15, seed=7)
    assert a == b and len(a) == 15 and all(o in (ts.HELD, ts.PIERCED, ts.UNTOUCHED) for o in a)
    flat = _bars(_flat(50))
    assert set(ts.fake_level_outcomes(flat, 1.0, "support", k=10)) == {ts.UNTOUCHED}
    assert ts.fake_level_outcomes(flat, 1.0, "support", exclude=range(45)) == []
    assert ts.level_distance_pct(98, 100, "support") == pytest.approx(2.0)
    assert ts.level_distance_pct(101, 100, "support") is None          # sai phía


# ── T2 ──────────────────────────────────────────────────────────────────

def _trigger_bars(after, vol_trigger=150.0):
    rows = _flat(21, 100) + after
    vol = [100.0] * 21 + [vol_trigger] + [100.0] * (len(after) - 1)
    return _bars(rows, volume=vol)


def test_trigger_breakout_hits_r2_with_volume_split():
    after = [(100, 101.5, 100, 101.2)] + [(101, 101.8, 101, 101.5)] * 2 \
        + [(101.5, 102.1, 101, 102)] + _flat(5, 102)
    r = ts.score_trigger(_trigger_bars(after), 20, 101, 102, "resistance")
    assert r == {"triggered": True, "trigger_pos": 21, "hit": True, "volume": "confirmed",
                 "gap_pct": pytest.approx((102 / 101.2 - 1) * 100)}  # R2 cách đóng cửa trigger
    r = ts.score_trigger(_trigger_bars(after, vol_trigger=110), 20, 101, 102, "resistance")
    assert r["volume"] == "unconfirmed"
    nov = _trigger_bars(after).drop(columns="volume")
    assert ts.score_trigger(nov, 20, 101, 102, "resistance")["volume"] == "unmeasurable"
    zero = _trigger_bars(after, vol_trigger=0)
    assert ts.score_trigger(zero, 20, 101, 102, "resistance")["volume"] == "unmeasurable"


def test_trigger_miss_none_and_same_day_close_beyond_level2():
    miss = [(100, 101.5, 100, 101.2)] + _flat(9, 101.2)
    assert ts.score_trigger(_trigger_bars(miss), 20, 101, 102, "resistance")["hit"] is False
    never = _flat(10, 100.5)
    assert ts.score_trigger(_trigger_bars(never), 20, 101, 102, "resistance")["triggered"] is False
    gap = [(100, 103, 100, 102.5)] + _flat(5, 102.5)
    assert ts.score_trigger(_trigger_bars(gap), 20, 101, 102, "resistance")["hit"] is True
    short = [(100, 101.5, 100, 101.2)] + _flat(4, 101.2)              # thiếu phiên sau trigger
    r = ts.score_trigger(_trigger_bars(short), 20, 101, 102, "resistance")
    assert r["triggered"] and r["hit"] is None
    down = [(100, 100, 98.5, 98.8)] + [(98.8, 98.8, 97.9, 98)] + _flat(8, 98)
    r = ts.score_trigger(_trigger_bars(down), 20, 99, 98, "support")
    assert r["triggered"] and r["hit"] is True


def test_trigger_summary_groups_by_volume():
    rows = [{"triggered": True, "hit": True, "volume": "confirmed"},
            {"triggered": True, "hit": False, "volume": "unconfirmed"},
            {"triggered": True, "hit": None, "volume": "confirmed"},
            {"triggered": False, "hit": None, "volume": None}]
    s = ts.trigger_summary(rows)
    assert s["all"]["n"] == 2 and s["confirmed"]["rate"] == 1.0 and s["unconfirmed"]["rate"] == 0


# ── T3 ──────────────────────────────────────────────────────────────────

def test_brief_stance_reads_tldr_like_evaluate_brief_accuracy():
    out = "## TLDR\n- Stance ngày mai: GIẢM — áp lực bán\n## Khác\nTăng mạnh tăng mạnh"
    assert ts.brief_stance(out) == "bearish"
    assert ts.brief_stance("") == "unknown"


def test_base_index_by_brief_type():
    dates = ts.date_positions(pd.bdate_range("2026-10-01", periods=5))
    assert ts.base_index(dates, "2026-10-02", "afternoon") == 1
    assert ts.base_index(dates, "2026-10-02", "morning") == 1              # trước giờ mở cửa
    assert ts.base_index(dates, "2026-10-02", "morning", intraday=True) == 0
    assert ts.base_index(dates, "2026-10-04", "afternoon") is None         # không có bar


def test_stance_outcome_single_flat_rule_and_baselines():
    closes = [100, 101, 101.2, 100.5, 100, 99, 98]
    up = ts.stance_outcome("bullish", closes, 1, 1)                        # +0,198% ⇒ phẳng
    assert up["actual"] == "flat" and up["match"] is False
    assert up["base_neutral"] is True and up["base_repeat"] is False      # hôm qua +1% ⇒ "up"
    dn = ts.stance_outcome("bearish", closes, 2, 1)                        # −0,69%
    assert dn["actual"] == "down" and dn["match"] is True
    assert ts.stance_outcome("bearish", closes, 1, 5)["actual"] == "down"
    assert ts.stance_outcome("neutral", closes, 3, 5) is None             # chưa đủ phiên
    assert ts.stance_outcome("unknown", closes, 2, 1)["match"] is None


def test_summarize_stances_baseline_counted_once_per_session():
    def rec(d, agent, stance, match, sent=None, bn=True, br=False):
        h = {"match": match, "base_neutral": bn, "base_repeat": br, "actual": "flat",
             "ret_pct": 0.0, "repeat_stance": "bullish"}
        return {"brief_type": "afternoon", "brief_date": d, "agent_name": agent,
                "sent": sent, "stance": stance, "h1": h, "h5": None}
    recs = [rec("2026-10-01", "A", "neutral", True, sent=1),
            rec("2026-10-01", "B", "bullish", False),
            rec("2026-10-01", "C", "bullish", False),
            rec("2026-10-02", "A", "bearish", False, sent=1, bn=False, br=True)]
    s = ts.summarize_stances(recs)["afternoon"]
    h1 = s["h1"]
    assert h1["all"]["n"] == 4 and h1["all"]["k"] == 1
    assert h1["sent"] == ts.rate(1, 2)
    assert h1["n_sessions"] == 2
    assert h1["baseline_neutral"] == ts.rate(1, 2) and h1["baseline_repeat"] == ts.rate(1, 2)
    assert h1["by_agent"]["A"]["n"] == 2 and s["stance_dist"]["bullish"] == 2
    assert s["h5"]["all"]["n"] == 0


# ── T4 ──────────────────────────────────────────────────────────────────

def test_forward_returns_by_state():
    closes = [100, 110, 121, 100, 90, 81]
    states = [1, 1, -1, -1, None, None]
    out = ts.forward_returns_by_state(closes, states, horizons=(1,), labels={1: "UP"})
    up, dn, al = out["t1"]["UP"], out["t1"]["-1"], out["t1"]["_all"]
    assert (up["n"], up["k"], up["mean_pct"]) == (2, 2, 10.0)
    assert (dn["n"], dn["k"], dn["mean_pct"]) == (2, 0, pytest.approx(-13.678, abs=1e-3))
    assert up["episodes"] == 1 and al["n"] == 4 and al["episodes"] is None
    two = ts.forward_returns_by_state([1, 2, 3, 4, 5], [1, 0, 1, 0, 1], horizons=(1,))
    assert two["t1"]["1"]["episodes"] == 3 and two["t1"]["1"]["n"] == 2


# ── Bộ chấm setup §13.1 ─────────────────────────────────────────────────

SETUP = {"date": "2026-01-05", "trigger": 105.0, "sl": 95.0, "tp": 115.0, "side": "long"}


def test_setup_trigger_touched_on_signal_day_buys_next_open():
    rows = [(100, 105.5, 99, 104)] + [(104.5, 106, 104, 105)] + _flat(12, 106)
    g = ts.grade_setup(_bars(rows), SETUP)
    assert g["status"] == "filled" and g["entry_date"] == "2026-01-06" and g["entry"] == 104.5


def test_setup_untouched_fills_when_touched_inside_validity_window():
    rows = [(100, 102, 99, 101)] + _flat(2, 101) + [(101, 106, 101, 105)] + _flat(12, 105)
    g = ts.grade_setup(_bars(rows), SETUP, frame="short")             # chạm ở phiên thứ 3
    assert g["status"] == "filled" and g["entry"] == 105.0 and g["entry_date"] == "2026-01-08"
    late = [(100, 102, 99, 101)] + _flat(3, 101) + [(101, 106, 101, 105)] + _flat(12, 105)
    g = ts.grade_setup(_bars(late), SETUP, frame="short")
    assert (g["status"], g["reason"], g["entry"]) == ("not_filled", "no_trigger", None)
    assert ts.grade_setup(_bars(late), SETUP, frame="medium")["entry_date"] == "2026-01-09"
    pend = [(100, 102, 99, 101)] + _flat(2, 101)                       # cửa sổ chưa hết
    assert ts.grade_setup(_bars(pend), SETUP)["reason"] == "pending"


def test_setup_gap_open_above_trigger_buys_open():
    rows = [(100, 102, 99, 101)] + [(107, 108, 106.5, 107.5)] + _flat(12, 107.5)
    g = ts.grade_setup(_bars(rows), SETUP)
    assert g["entry"] == 107.0


def test_setup_pullback_trigger_below_price_buys_at_trigger():
    s = {**SETUP, "trigger": 98.0, "sl": 94.0, "tp": 110.0}
    rows = [(100, 101, 99, 100)] + [(99.5, 100, 97.5, 99)] + _flat(12, 99)
    g = ts.grade_setup(_bars(rows), s)
    assert g["entry"] == 98.0 and g["entry_date"] == "2026-01-06"


def test_setup_open_at_ceiling_cannot_buy_exchange_specific():
    s = {**SETUP, "trigger": 21.0, "sl": 19.0, "tp": 25.0}
    rows = _flat(3, 20) + [(21.40, 21.40, 21.40, 21.40)] + _flat(12, 21.4)  # trần ở phiên 3/3
    assert ts.ceiling_price(20.0, "HOSE") == pytest.approx(21.40)
    g = ts.grade_setup(_bars(rows), s)
    assert (g["status"], g["reason"]) == ("not_filled", "ceiling")
    assert ts.grade_setup(_bars(rows), s, exchange="HNX")["entry"] == 21.40   # trần HNX 22,0
    assert ts.grade_setup(_bars(rows), s, limit_pct=10.0)["status"] == "filled"
    then = [(20, 20.2, 19.8, 20)] + [(21.40, 21.40, 21.40, 21.40)] \
        + [(21.2, 21.6, 21.0, 21.5)] + _flat(12, 21.5)
    g = ts.grade_setup(_bars(then), s)                                 # phiên sau hết trần ⇒ mua
    assert g["status"] == "filled" and g["entry_date"] == "2026-01-07" and g["entry"] == 21.2


def test_setup_t25_sl_breached_before_t2_sells_open_t2():
    rows = [(100, 105.5, 99, 104), (104, 104, 103, 103.5),            # mua T0 104
            (103, 103, 94, 96),                                        # T+1 thủng SL — chưa bán được
            (97, 99, 96.5, 98)] + _flat(12, 98)
    g = ts.grade_setup(_bars(rows), SETUP)
    assert (g["reason"], g["exit_date"], g["exit"]) == ("sl", "2026-01-08", 97.0)


def test_setup_tp_before_t2_not_sold_then_expires():
    rows = [(100, 105.5, 99, 104), (104, 116, 103, 110),               # T0 chạm TP — chưa bán được
            (109, 112, 108, 110)] + _flat(12, 110)
    b = _bars(rows)
    g = ts.grade_setup(b, SETUP, frame="short")
    assert g["reason"] == "expire" and g["exit_date"] == b["time"][11].date().isoformat()
    assert g["exit"] == 110.0


def test_setup_same_session_tp_and_sl_counts_sl():
    rows = [(100, 105.5, 99, 104), (104, 104, 103, 104), (104, 104, 103, 104),
            (104, 116, 94, 100)] + _flat(10, 100)
    g = ts.grade_setup(_bars(rows), SETUP)
    assert (g["reason"], g["exit"]) == ("sl", 95.0)


def test_setup_tp_and_gap_exits():
    rows = [(100, 105.5, 99, 104), (104, 106, 103, 105), (105, 106, 104, 105),
            (106, 115.5, 105, 114)] + _flat(10, 114)
    g = ts.grade_setup(_bars(rows), SETUP)
    assert (g["reason"], g["exit"]) == ("tp", 115.0)
    gap = rows[:3] + [(118, 119, 117, 118)] + _flat(10, 118)
    assert ts.grade_setup(_bars(gap), SETUP)["exit"] == 118.0


@pytest.mark.parametrize("frame,hold", [("short", 10), ("medium", 60), ("long", 250)])
def test_setup_max_hold_exits_close_on_expiry(frame, hold):
    rows = [(100, 105.5, 99, 104), (104, 106, 103, 105)] \
        + [(105, 106, 104, 105 + (i % 3) * 0.1) for i in range(hold + 5)]
    b = _bars(rows)
    g = ts.grade_setup(b, SETUP, frame=frame)
    assert g["reason"] == "expire"
    assert g["exit_date"] == b["time"][1 + hold].date().isoformat()
    assert g["exit"] == b["close"][1 + hold]


def test_setup_net_return_fees_and_benchmark():
    rows = [(100, 105.5, 99, 104), (104, 106, 103, 105), (105, 106, 104, 105),
            (106, 115.5, 105, 114)] + _flat(10, 114)
    b = _bars(rows)
    bench = pd.Series([1000, 1010, 1020, 1030] + [1030] * 10, index=b["time"])
    g = ts.grade_setup(b, SETUP, bench=bench)
    assert g["ret_pct_net"] == pytest.approx((115 * (1 - 0.0025) / (104 * 1.0015) - 1) * 100,
                                             abs=1e-3)
    assert g["bench_ret_pct"] == pytest.approx((1030 / 1000 - 1) * 100)
    assert ts.grade_setup(b, SETUP, fee_pct=0, tax_pct=0)["ret_pct_net"] == \
        pytest.approx((115 / 104 - 1) * 100, abs=1e-3)


def test_setup_open_position_and_invalid_inputs():
    rows = [(100, 105.5, 99, 104), (104, 106, 103, 105), (105, 106, 104, 105)]
    g = ts.grade_setup(_bars(rows), SETUP)
    assert (g["status"], g["reason"], g["exit"]) == ("filled", "open", None)
    assert ts.grade_setup(_bars(rows), {**SETUP, "date": "2025-01-01"})["status"] == "no_data"
    with pytest.raises(ValueError):
        ts.grade_setup(_bars(rows), {**SETUP, "sl": 106})
    with pytest.raises(ValueError):
        ts.grade_setup(_bars(rows), {**SETUP, "side": "short"})
    with pytest.raises(ValueError):
        ts.grade_setup(_bars(rows), SETUP, frame="weekly")


# ── Badge ───────────────────────────────────────────────────────────────

def _score_h1(all_k, all_n, sent_k=0, sent_n=0, neutral=0.4, repeat=0.3,
              neutral_sent=None, repeat_sent=None):
    return {"t3": {"afternoon": {"h1": {
        "all": ts.rate(all_k, all_n), "sent": ts.rate(sent_k, sent_n),
        "baseline_neutral": {"rate": neutral}, "baseline_repeat": {"rate": repeat},
        "baseline_neutral_sent": {"rate": neutral if neutral_sent is None else neutral_sent},
        "baseline_repeat_sent": {"rate": repeat if repeat_sent is None else repeat_sent}}}}}


def test_badge_ok_below_floor_even_when_all_wrong():
    st, msg = ts.badge_verdict(_score_h1(0, ts.MIN_SAMPLES - 1))
    assert st == "ok" and f"n={ts.MIN_SAMPLES - 1}" in msg
    assert ts.badge_verdict(None)[0] == "off"


def test_badge_warns_only_when_enough_samples_and_worse_than_naive():
    n = ts.MIN_SAMPLES
    assert ts.badge_verdict(_score_h1(int(n * 0.3), n))[0] == "warn"      # 30% < trung tính 40%
    assert ts.badge_verdict(_score_h1(int(n * 0.5), n))[0] == "ok"
    # có đủ bản đã gửi ⇒ chấm theo bản đã gửi
    st, msg = ts.badge_verdict(_score_h1(int(n * 0.3), n, sent_k=int(n * 0.6), sent_n=n))
    assert st == "ok" and "bản đã gửi" in msg


def test_doctor_ta_score_badge(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path)
    assert doc.check_ta_score()["status"] == "off"
    (tmp_path / "ta_score.json").write_text(json.dumps(
        {**_score_h1(1, 5), "computed_at": "2026-11-04T20:00:00"}), encoding="utf-8")
    r = doc.check_ta_score()
    assert r["key"] == "ta_score" and r["status"] == "ok" and "n=5" in r["message"]
    (tmp_path / "ta_score.json").write_text("{hỏng", encoding="utf-8")
    assert doc.check_ta_score()["status"] == "error"
    assert doc.check_ta_score in doc.OFFLINE_CHECKS


# ── Lớp IO trên dữ liệu tổng hợp ────────────────────────────────────────

def test_load_briefs_read_only_handles_missing_db_and_old_schema(tmp_path):
    assert tio.load_briefs(tmp_path / "missing.db") == []
    assert not (tmp_path / "missing.db").exists()
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.execute("CREATE TABLE briefs (id INTEGER PRIMARY KEY, created_at TEXT, brief_date TEXT, "
              "brief_type TEXT, agent_name TEXT, agent_type TEXT, output TEXT, error TEXT, "
              "context_json TEXT)")
    c.execute("INSERT INTO briefs VALUES (1,'t','2026-10-01','afternoon','A','a','x',NULL,'{}')")
    c.commit()
    c.close()
    rows = tio.load_briefs(old)
    assert rows[0]["sent"] is None and rows[0]["agent_name"] == "A"
    cols = [r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(briefs)")]
    assert "sent" not in cols                                          # không chạy migration


def test_dedupe_prefers_sent_then_latest():
    def b(i, agent, created, sent=None):
        return {"brief_type": "afternoon", "brief_date": "2026-10-01", "agent_name": agent,
                "created_at": created, "sent": sent, "id": i}
    bs = [b(1, "A", "2026-10-01T18:00", 1), b(2, "A", "2026-10-01T19:00"),
          b(3, "B", "2026-10-01T18:00"), b(4, "B", "2026-10-01T19:00")]
    assert sorted(x["id"] for x in tio.dedupe_briefs(bs)) == [1, 4]


def _index_history(n=420):
    rng = np.random.default_rng(3)
    c = 1200 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return _bars([(x, x * 1.006, x * 0.994, x) for x in c], start="2025-01-01")


def _brief(d, agent, stance, ctx, sent=None, btype="afternoon"):
    return {"id": 0, "brief_date": d, "brief_type": btype, "agent_name": agent,
            "agent_type": "x", "sent": sent, "error": None, "created_at": f"{d}T18:30:00",
            "output": f"## TLDR\n- Stance ngày mai: {stance}\n## Khác\n…",
            "context_json": json.dumps(ctx)}


def test_compute_end_to_end_on_synthetic_history():
    idx = _index_history()
    dates = [t.date().isoformat() for t in idx["time"]]
    briefs = []
    for i in range(380, 400):
        c = float(idx["close"][i])
        ctx = {"vnindex_tech": {"close": c, "support_1": c * 0.99, "support_2": c * 0.98,
                                "resistance_1": c * 1.01, "resistance_2": c * 1.02},
               "vn30_gainers": [{"Mã": "AAA", "last": 50.0, "sr_support": 49.0,
                                 "sr_resistance": 51.0}],
               "vn30_losers": [{"Mã": "BBB", "last": 10.0, "sr_support": 9.5}],
               "portfolio": [{"ticker": "CCC", "last_close": 20.0, "sr_resistance": 21.0}]}
        briefs += [_brief(dates[i], "Gemini", "TĂNG", ctx),
                   _brief(dates[i], "Claude", "TRUNG TÍNH", ctx, sent=1),
                   _brief(dates[i], "Gemini", "GIẢM", ctx, btype="morning")]
    briefs.append({**briefs[0], "brief_type": "allocation"})

    def load_ticker(tk):
        px = {"AAA": 50.0, "BBB": 20.0, "CCC": 20.0}[tk]                # BBB: kho gấp đôi ⇒ bỏ
        return _bars(_flat(len(idx), px), start="2025-01-01").assign(volume=1000)

    short = {dates[i]: (i // 50) % 2 - 1 for i in range(300, 420)}
    sc = tio.compute(briefs, idx, load_ticker, short_states=short, short_source="test")
    assert sc["n_sessions_afternoon"] == 20 and sc["n_briefs_dedup"] == 61
    t1s = sc["t1"]["support"]["real"]
    assert t1s["n"] == 20 and t1s["held"] + t1s["pierced"] + t1s["untouched"] == 20
    assert sc["t1"]["support"]["fake"]["n"] == 20 * ts.FAKE_PER_LEVEL
    assert len(sc["t1"]["detail"]) == 20
    h1 = sc["t3"]["afternoon"]["h1"]
    assert h1["all"]["n"] == 40 and h1["sent"]["n"] == 20 and h1["n_sessions"] == 20
    assert set(h1["by_agent"]) == {"Gemini", "Claude"}
    assert "morning" in sc["t3"] and "allocation" not in sc["t3"]
    assert sc["t4"]["medium"]["t5"]["_all"]["n"] > 0
    assert sc["t4"]["short"] is not None and sc["t4"]["short_source"] == "test"
    t5 = sc["t5"]
    assert t5["n_tickers"] == 2 and t5["basis_skipped"] == 20
    assert t5["support"]["real"]["untouched"] == 20                   # giá phẳng 50 > 49
    assert t5["resistance"]["real"]["n"] == 40
    json.dumps(sc)                                                     # ghi được JSON
    txt = tio.format_table(sc)
    assert "T1 · S1/R1 VN-Index" in txt and "T5 · S/R từng mã" in txt
    assert "Badge: warn" in txt and "THUA mốc" in txt   # bản gửi luôn TRUNG TÍNH, chỉ số đi ~1%/phiên


def test_compute_morning_intraday_uses_previous_close():
    idx = _bars(_flat(2, 100) + [(100, 100, 100, 101), (101, 101, 101, 101.1)]
                + _flat(10, 101.1), start="2026-10-01")
    d = idx["time"][2].date().isoformat()
    pre = _brief(d, "A", "TĂNG", {"vnindex_tech": {}}, btype="morning")
    intra = _brief(d, "B", "TĂNG", {"vnindex_tech": {"intraday": True}}, btype="morning")
    sc = tio.compute([pre, intra], idx, lambda tk: pd.DataFrame())
    by = sc["t3"]["morning"]["h1"]["by_agent"]
    assert by["A"]["k"] == 0                                           # 101 → 101,1: phẳng
    assert by["B"]["k"] == 1                                           # 100 → 101: tăng


def test_ticker_levels_rescaled_after_rebase():
    d = pd.bdate_range("2026-10-01", periods=30)[10].date().isoformat()
    ctx = {"vn30_gainers": [{"Mã": "AAA", "last": 50.0, "sr_support": 49.0}]}
    rows = _flat(11, 45.0) + [(45, 45, 44.0, 44.5)] + _flat(18, 45.0)   # kho rebase ×0,9
    sc = tio.score_tickers({d: ctx}, lambda tk: _bars(rows, start="2026-10-01"))
    assert sc["rescaled"] == 1 and sc["support"]["real"][ts.HELD] == 1  # 49×0,9 = 44,1 chạm


def test_short_states_from_published_state(tmp_path):
    (tmp_path / "_meta").mkdir()
    (tmp_path / "_meta" / "horizon_state.json").write_text(json.dumps({"published": [
        {"as_of": "2026-10-01", "short": 1}, {"as_of": "2026-10-02", "short": -1},
        {"as_of": "2026-10-03"}]}), encoding="utf-8")
    assert tio.load_short_states(tmp_path) == {"2026-10-01": 1, "2026-10-02": -1}
    assert tio.load_short_states(tmp_path / "none") == {}


def test_cli_show_and_run_write_only_tmp(tmp_path, monkeypatch, capsys):
    import run as runpy
    import vnstock_brief as vb
    assert runpy._DISPATCH["ta-score"] is runpy.cmd_ta_score
    a = runpy.build_parser().parse_args(["ta-score", "--show", "--backfill"])
    assert a.show and a.backfill
    assert runpy.cmd_ta_score(SimpleNamespace(warehouse=str(tmp_path), show=True)) == 1
    assert "chưa có _meta/ta_score.json" in capsys.readouterr().out
    monkeypatch.setattr(vm, "DB_PATH", tmp_path / "brief_memory.db")
    monkeypatch.setattr(vb, "_load_vnindex_df", lambda augment=True: _index_history())
    assert runpy.cmd_ta_score(SimpleNamespace(warehouse=str(tmp_path))) == 0
    assert (tmp_path / "_meta" / "ta_score.json").exists()
    assert not (tmp_path / "brief_memory.db").exists()
    assert runpy.cmd_ta_score(SimpleNamespace(warehouse=str(tmp_path), show=True)) == 0
    assert "T3 · Stance" in capsys.readouterr().out


# ── Sửa sau review P0 (04/11) ───────────────────────────────────────────

def test_badge_compares_sent_against_baseline_of_the_same_sessions():
    """Bản đã gửi chỉ có từ 04/11 ⇒ so với mốc của CHÍNH các phiên đó, không phải mốc ~130 phiên."""
    n = ts.MIN_SAMPLES
    # gửi đúng 60%; mốc trung tính mọi phiên 35% nhưng trên các phiên có bản gửi là 70%
    sc = _score_h1(int(n * 0.5), n * 3, sent_k=int(n * 0.6), sent_n=n,
                   neutral=0.35, neutral_sent=0.70)
    st, msg = ts.badge_verdict(sc)
    assert st == "warn" and "bản đã gửi" in msg and "70%" in msg
    # chưa đủ bản gửi ⇒ quay về mọi bản + mốc mọi phiên
    sc2 = _score_h1(int(n * 0.5), n, sent_k=1, sent_n=2, neutral=0.35, neutral_sent=0.9)
    assert ts.badge_verdict(sc2)[0] == "ok"


def test_summarize_stances_sent_baseline_only_over_sessions_with_a_sent_brief():
    def rec(d, agent, sent, bn):
        h = {"match": True, "base_neutral": bn, "base_repeat": False, "actual": "flat",
             "ret_pct": 0.0, "repeat_stance": "bullish"}
        return {"brief_type": "afternoon", "brief_date": d, "agent_name": agent,
                "sent": sent, "stance": "neutral", "h1": h, "h5": None}
    h1 = ts.summarize_stances([rec("2026-10-01", "A", None, False),
                               rec("2026-10-02", "A", None, False),
                               rec("2026-11-04", "A", 1, True)])["afternoon"]["h1"]
    assert h1["baseline_neutral"] == ts.rate(1, 3)
    assert h1["baseline_neutral_sent"] == ts.rate(1, 1)


def test_compute_morning_intraday_base_is_price_seen_at_run_time():
    """Brief sáng 11:35 đã thấy +1% ⇒ gốc là giá lúc chạy, không được tính công phần đã biết."""
    idx = _bars(_flat(2, 100) + [(100, 100, 100, 101), (101, 101, 101, 101.1)]
                + _flat(10, 101.1), start="2026-10-01")
    d = idx["time"][2].date().isoformat()
    seen = _brief(d, "B", "TĂNG", {"vnindex_tech": {"intraday": True, "close": 101.0}},
                  btype="morning")
    sc = tio.compute([seen], idx, lambda tk: pd.DataFrame())
    assert sc["t3"]["morning"]["h1"]["by_agent"]["B"]["k"] == 0       # 101 (lúc chạy) → 101: phẳng


def test_setup_ceiling_then_window_not_over_is_pending_not_final():
    """Phiên ra khuyến nghị đã chạm trigger, phiên sau mở cửa trần, chưa có bar tiếp theo ⇒
    cửa sổ 3 phiên còn mở ⇒ 'pending', không phải kết cục 'ceiling'."""
    s = {**SETUP, "trigger": 20.1, "sl": 19.0, "tp": 25.0}
    rows = [(20, 20.2, 19.8, 20)] + [(21.40, 21.40, 21.40, 21.40)]
    g = ts.grade_setup(_bars(rows), s)
    assert (g["status"], g["reason"]) == ("not_filled", "pending")
