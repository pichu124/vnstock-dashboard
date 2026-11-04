"""Thước đo PTKT — bảng dễ đọc đúng (sau lần chạy kho thật đầu tiên, 04/11).

T3 tách giai đoạn 3 khung + nguồn nhãn (code/agent), so model cùng phiên, mốc cho T2
trigger, phễu cỡ mẫu, nhãn ít đoạn ở T4, badge chấm nhóm "từ 3 khung × agent".
Dữ liệu tổng hợp, không cần kho."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import vnstock_ta_score as ts
import vnstock_ta_score_io as tio

PRE, HZ = ts.PERIOD_PRE, ts.PERIOD_HZ


def _bars(closes, start="2025-01-01", spread=0.0):
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"time": pd.bdate_range(start, periods=len(c)), "open": c,
                         "high": c * (1 + spread), "low": c * (1 - spread), "close": c})


def _index_history(n=420):
    rng = np.random.default_rng(3)
    return _bars(1200 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)), spread=0.006)


def _brief(d, agent, stance, ctx, sent=None, btype="afternoon", error=None, created=None):
    return {"id": 0, "brief_date": d, "brief_type": btype, "agent_name": agent,
            "agent_type": "x", "sent": sent, "error": error,
            "created_at": created or f"{d}T18:30:00",
            "output": f"## TLDR\n- Stance ngày mai: {stance}\n## Khác\n…",
            "context_json": json.dumps(ctx)}


def _hz(forced=None, allowed=None, stale=False):
    return {"horizons": {"stale": stale, "snap": {"stance": {"forced": forced,
                                                              "allowed": allowed or []}}}}


def _rec(d, agent, match, period, source, bn=False, br=False):
    h = {"match": match, "base_neutral": bn, "base_repeat": br, "actual": "flat",
         "ret_pct": 0.0, "repeat_stance": "bullish"}
    return {"brief_type": "afternoon", "brief_date": d, "agent_name": agent, "sent": None,
            "stance": "neutral", "period": period, "source": source, "h1": h, "h5": None}


_RECS = [_rec("2026-10-01", "A", True, PRE, "agent", bn=True),
         _rec("2026-10-01", "B", False, PRE, "code", bn=True),
         _rec("2026-10-20", "A", False, HZ, "agent", br=True),
         _rec("2026-10-21", "A", True, HZ, "agent"),
         _rec("2026-10-21", "B", True, HZ, "code")]


# ── 1. T3 tách giai đoạn + nguồn nhãn ───────────────────────────────────

def test_stances_split_by_period_and_source_each_with_own_session_baseline():
    h1 = ts.summarize_stances(_RECS)["afternoon"]["h1"]
    pre, hz = h1["by_period"][PRE], h1["by_period"][HZ]
    assert pre["all"] == ts.rate(1, 2) and pre["n_sessions"] == 1
    assert pre["baseline_neutral"] == ts.rate(1, 1)          # mốc chỉ trên phiên 01/10
    assert hz["all"] == ts.rate(2, 3) and hz["n_sessions"] == 2
    assert hz["baseline_neutral"] == ts.rate(0, 2) and hz["baseline_repeat"] == ts.rate(1, 2)
    assert hz["by_source"]["agent"]["all"] == ts.rate(1, 2)
    assert hz["by_source"]["code"]["n_sessions"] == 1
    assert hz["by_source"]["code"]["baseline_repeat"] == ts.rate(0, 1)
    code, agent = h1["by_source"]["code"], h1["by_source"]["agent"]
    assert code["all"] == ts.rate(1, 2) and code["n_sessions"] == 2
    assert code["baseline_neutral"] == ts.rate(1, 2)
    assert agent["all"] == ts.rate(2, 3) and agent["n_sessions"] == 3
    assert (hz["first"], hz["last"]) == ("2026-10-20", "2026-10-21")


def test_compute_reads_period_from_ctx_and_source_like_stance_track():
    idx = _index_history()
    d = [t.date().isoformat() for t in idx["time"]]
    briefs = [
        _brief(d[300], "A", "TĂNG", {}),                                    # trước: không có 3 khung
        _brief(d[301], "A", "TĂNG", _hz(allowed=["TĂNG"], stale=True)),     # trước: state cũ
        _brief(d[302], "A", "TĂNG", {"horizons": {"snap": {}}}),            # trước: snap thiếu luật
        _brief(d[303], "A", "TRUNG TÍNH", _hz(allowed=["TRUNG TÍNH"])),     # từ 3 khung, agent
        _brief(d[304], "A", "GIẢM", {**_hz(forced="GIẢM"),                  # ô ép, nhãn ĐÚNG chiều
                                     "bias_floor": {"dir": "GIẢM"}}),
        _brief(d[305], "A", "TRUNG TÍNH", {**_hz(allowed=["TRUNG TÍNH"]),   # code đổi nhãn
                                           "stance_pinned": {"agent": "TĂNG",
                                                             "code": "TRUNG TÍNH"}}),
        _brief(d[306], "A", "TĂNG", {"bias_floor": {"dir": "GIẢM"}}),       # agent cãi floor cũ
    ]
    h1 = tio.compute(briefs, idx, lambda tk: pd.DataFrame())["t3"]["afternoon"]["h1"]
    assert h1["by_period"][PRE]["all"]["n"] == 4 and h1["by_period"][HZ]["all"]["n"] == 3
    assert h1["by_source"]["code"]["all"]["n"] == 2 and h1["by_source"]["agent"]["all"]["n"] == 5
    assert h1["by_period"][HZ]["by_source"]["agent"]["all"]["n"] == 1


# ── 2. So model cùng phiên ──────────────────────────────────────────────

def test_paired_compares_each_agent_only_on_shared_sessions():
    h1 = ts.summarize_stances(_RECS)["afternoon"]["h1"]
    a, b = h1["paired"]["A"], h1["paired"]["B"]
    assert a["n_sessions"] == 2 and a["acc"] == ts.rate(2, 2)      # 20/10 A đi một mình: bỏ
    assert a["others_rate"] == 0.5 and a["diff_pp"] == 50.0
    assert b["n_sessions"] == 2 and b["acc"] == ts.rate(1, 2)
    assert b["others_rate"] == 1.0 and b["diff_pp"] == -50.0
    assert (h1["by_agent"]["A"]["first"], h1["by_agent"]["A"]["last"]) == \
        ("2026-10-01", "2026-10-21")
    assert h1["by_agent"]["A"]["n"] == 3                            # bảng cũ giữ nguyên số


def test_paired_skips_agent_that_never_shares_a_session():
    recs = [_rec("2026-10-01", "A", True, PRE, "agent"), _rec("2026-10-02", "B", True, PRE, "agent")]
    assert ts.summarize_stances(recs)["afternoon"]["h1"]["paired"] == {}


# ── 3. T2 trigger có mốc cùng khoảng cách ───────────────────────────────

def test_fake_trigger_outcomes_same_gap_seeded_and_excludes_event_days():
    flat = _bars([100.0] * 40)
    assert ts.fake_trigger_outcomes(flat, 1.0, "resistance") == [False] * ts.FAKE_PER_LEVEL
    assert ts.fake_trigger_outcomes(flat, 0.0, "support") == [True] * ts.FAKE_PER_LEVEL
    up = _bars(100 * 1.005 ** np.arange(40), spread=0.001)
    assert all(ts.fake_trigger_outcomes(up, 1.2, "resistance"))         # 5 phiên +2,5% ≥ 1,2%
    assert not any(ts.fake_trigger_outcomes(up, 1.2, "support"))
    down = _bars(100 * 0.995 ** np.arange(40), spread=0.001)
    assert all(ts.fake_trigger_outcomes(down, 1.2, "support"))
    assert ts.fake_trigger_outcomes(up, 3.0, "resistance", seed=7) == \
        ts.fake_trigger_outcomes(up, 3.0, "resistance", seed=7)
    short = _bars([100.0] * 10)                                           # 5 ngày bốc được
    assert len(ts.fake_trigger_outcomes(short, 1.0, "resistance", exclude=[0, 1, 2, 3])) == 1
    assert ts.fake_trigger_outcomes(short, 1.0, "resistance", exclude=range(5)) == []


def _trend_session(r2_gap_pct):
    """Chỉ số tăng đều 0,5%/phiên; brief phiên 30: R1 ngay trên giá ⇒ phiên 31 vượt R1."""
    idx = _bars(100 * 1.005 ** np.arange(80), spread=0.001)
    c = idx["close"].to_numpy()
    d = idx["time"][30].date().isoformat()
    return {d: {"vnindex_tech": {"resistance_1": c[30] * 1.003,
                                 "resistance_2": c[31] * (1 + r2_gap_pct / 100)}}}, idx


def test_t2_baseline_uses_same_distance_as_each_real_event():
    near, idx = _trend_session(1.2)
    t2 = tio.score_index(near, idx)[1]["resistance"]
    assert t2["all"] == ts.rate(1, 1)
    base = t2["baseline"]
    assert base["all"]["n"] == ts.FAKE_PER_LEVEL and base["all"]["rate"] == 1.0
    assert base["unmeasurable"]["n"] == ts.FAKE_PER_LEVEL and base["confirmed"]["n"] == 0
    far, idx = _trend_session(20.0)
    t2 = tio.score_index(far, idx)[1]["resistance"]
    assert t2["all"] == ts.rate(0, 1) and t2["baseline"]["all"] == ts.rate(0, ts.FAKE_PER_LEVEL)


def test_t2_table_prints_baseline_beside_each_line():
    idx = _index_history()
    d = [t.date().isoformat() for t in idx["time"]]
    briefs = []
    for i in range(300, 340):
        c = float(idx["close"][i])
        ctx = {"vnindex_tech": {"support_1": c * 0.999, "support_2": c * 0.99,
                                "resistance_1": c * 1.001, "resistance_2": c * 1.01}}
        briefs.append(_brief(d[i], "A", "TĂNG", ctx))
    sc = tio.compute(briefs, idx, lambda tk: pd.DataFrame())
    for side in ("resistance", "support"):
        t2 = sc["t2"][side]
        assert t2["all"]["n"] > 0
        assert t2["baseline"]["all"]["n"] == ts.FAKE_PER_LEVEL * t2["all"]["n"]
    json.dumps(sc)
    txt = tio.format_table(sc)
    t2_txt = txt.split("T2 ·")[1].split("T3 ·")[0]
    assert t2_txt.count("mốc cùng khoảng cách") == 4                   # 2 dòng × 2 chiều


# ── 4. Minh bạch cỡ mẫu ─────────────────────────────────────────────────

def test_funnel_counts_every_brief_into_exactly_one_bucket():
    idx = _index_history()
    d = [t.date().isoformat() for t in idx["time"]]
    unk = {**_brief(d[102], "C", "x", {}), "output": "## TLDR\nxyz\n"}
    briefs = [_brief(d[100], "A", "TĂNG", {}, created=f"{d[100]}T18:00:00"),
              _brief(d[100], "A", "GIẢM", {}, created=f"{d[100]}T19:00:00"),   # chạy lại
              _brief(d[101], "B", "TĂNG", {}, error="timeout"),
              _brief("2025-01-04", "A", "TĂNG", {}),                          # thứ 7: không bar
              unk,
              _brief(d[-1], "A", "TĂNG", {}),                                 # chưa có T+1
              _brief(d[103], "A", "TĂNG", {}),
              _brief(d[103], "A", "TĂNG", {}, btype="morning"),
              _brief(d[103], "A", "TĂNG", {}, btype="allocation")]
    sc = tio.compute(briefs, idx, lambda tk: pd.DataFrame())
    assert sc["funnel"]["afternoon"] == {"db": 7, "dedup": 6, "error": 1, "no_bar": 1,
                                         "unknown": 1, "pending": 1, "scored": 2}
    assert sc["funnel"]["morning"]["scored"] == 1 and "allocation" not in sc["funnel"]
    txt = tio.format_table(sc)
    head = txt.split("T1 ·")[0]
    assert ("chiều: 7 dòng → 6 sau khử trùng → bỏ: lỗi 1 · không có bar đúng ngày 1 · "
            "stance không đọc được 1 · chưa tới T+1 1 → chấm 2") in head


def test_t4_prints_first_index_date_and_flags_states_with_few_episodes():
    closes = list(100 + np.arange(40.0))
    states = [1] * 10 + [0, None] * 15                    # trạng thái 0: 15 đoạn, 1: 1 đoạn
    t4 = {"period": ["2024-03-01", "2026-11-03"], "short": None, "short_sessions": 0,
          "medium": ts.forward_returns_by_state(closes, states, horizons=(5,),
                                                labels={1: "TĂNG", 0: "NGANG"})}
    txt = tio.format_table({"computed_at": "x", "machine": "m", "t4": t4})
    assert "dữ liệu VN-Index từ 2024-03-01" in txt
    lines = {ln.split()[1]: ln for ln in txt.splitlines() if ln.strip().startswith("T5 ")}
    assert "ít đoạn — chưa kết luận" in lines["TĂNG"]
    assert "ít đoạn" not in lines["NGANG"]


def _h1(all_k, all_n, neutral=0.4, hz_agent=None):
    h1 = {"all": ts.rate(all_k, all_n), "sent": ts.rate(0, 0),
          "baseline_neutral": {"rate": neutral}, "baseline_repeat": {"rate": 0.3}}
    if hz_agent:
        k, n, bn = hz_agent
        h1["by_period"] = {HZ: {"by_source": {"agent": {
            "all": ts.rate(k, n), "baseline_neutral": {"rate": bn},
            "baseline_repeat": {"rate": 0.1}}}}}
    return {"t3": {"afternoon": {"h1": h1}}}


def test_badge_grades_hz_agent_group_when_it_reaches_the_floor():
    n = ts.MIN_SAMPLES
    # tổng thể thắng mốc, nhưng nhóm "từ 3 khung × agent" đủ mẫu và THUA mốc của chính nó
    st, msg = ts.badge_verdict(_h1(int(n * 0.6), n * 3, hz_agent=(int(n * 0.3), n, 0.5)))
    assert st == "warn" and "từ 3 khung" in msg and "agent" in msg and f"n={n}" in msg
    st, msg = ts.badge_verdict(_h1(int(n * 0.3), n * 3, hz_agent=(int(n * 0.6), n, 0.5)))
    assert st == "ok" and "từ 3 khung" in msg


def test_badge_falls_back_when_hz_agent_group_is_below_floor():
    n = ts.MIN_SAMPLES
    st, msg = ts.badge_verdict(_h1(int(n * 0.3), n, hz_agent=(0, n - 1, 0.9)))
    assert st == "warn" and "mọi bản" in msg and "từ 3 khung" not in msg
    st, msg = ts.badge_verdict(_h1(0, n - 1, hz_agent=(0, 3, 0.9)))
    assert st == "ok" and f"n={n - 1}" in msg


def test_t3_table_prints_groups_paired_and_agent_date_range():
    idx = _index_history()
    d = [t.date().isoformat() for t in idx["time"]]
    briefs = []
    for i in range(300, 330):
        ctx = _hz(allowed=["TĂNG", "TRUNG TÍNH"]) if i >= 315 else {}
        briefs += [_brief(d[i], "Gemini", "TĂNG", ctx), _brief(d[i], "Claude", "TRUNG TÍNH", ctx)]
    briefs.append(_brief(d[331], "Groq", "GIẢM", {}))
    txt = tio.format_table(tio.compute(briefs, idx, lambda tk: pd.DataFrame()))
    t3 = txt.split("T3 ·")[1].split("T4 ·")[0]
    assert "trước 3 khung" in t3 and "từ 3 khung" in t3 and "nhãn agent tự chọn" in t3
    assert "so cùng phiên" in t3 and f"{d[300]} → {d[329]}" in t3
    paired = t3.split("so cùng phiên")[1].split("brief")[0]
    assert "Gemini" in paired and "Groq" not in paired                # Groq không chung phiên


# ── stance_pinned không lây giữa các agent (04/11) ─────────────────────────

def test_stance_pinned_is_recorded_per_agent_not_shared():
    """ctx dùng chung giữa các agent: agent bị code ép nhãn không được làm agent khác cùng
    phiên bị sổ Stance tính là "code" (vnstock_stance_track._stance_source đọc cờ này)."""
    import inspect

    import vnstock_brief as vb

    src = inspect.getsource(vb.generate_brief)
    loop = src[src.index("pinned_by_agent: dict = {}"):src.index("validate_brief_factuality(")]
    # xoá cờ TRƯỚC lượt guard của từng agent, cất riêng sau lượt, dọn sau vòng
    assert loop.index('ctx.pop("stance_pinned", None)') < loop.index("apply_brief_guards(text, ctx)")
    assert "pinned_by_agent[agent.name] = ctx[\"stance_pinned\"]" in loop
    assert "_ctx_for_agent(ctx_small, pinned_by_agent, agent.name)" in src
    pinned = {"A": {"agent": "TĂNG", "code": "GIẢM"}}
    ctx_small = {"date": "2026-11-03", "stance_pinned": {"lây": 1}}
    assert vb._ctx_for_agent(ctx_small, pinned, "A")["stance_pinned"] == pinned["A"]
    assert "stance_pinned" not in vb._ctx_for_agent(ctx_small, pinned, "B")
    assert ctx_small["stance_pinned"] == {"lây": 1}                 # không đổi dict gốc


def test_dedupe_drops_errored_rerun_before_choosing():
    """Bản chạy lại sau mà LỖI không được chiếm chỗ bản hợp lệ cũ hơn cùng (loại, phiên, agent)."""
    import vnstock_ta_score_io as tio
    good = {"id": 1, "brief_date": "2026-10-01", "brief_type": "afternoon", "agent_name": "A",
            "created_at": "2026-10-01T18:30:00", "error": None, "sent": None, "output": "x"}
    bad = {**good, "id": 2, "created_at": "2026-10-01T21:00:00", "error": "timeout"}
    kept = tio.dedupe_briefs([good, bad])
    assert [b["id"] for b in kept] == [1]


# ── Sau lần chạy kho thật thứ 2 (04/11) ─────────────────────────────────────

@pytest.mark.parametrize("tldr,want", [
    ("## 🎯 TLDR\n**Bias:** GIẢM — thị trường yếu.", "bearish"),
    ("## 🎯 TLDR\n- **Bias:** TRUNG TÍNH — chờ xác nhận.", "neutral"),
    ("## 🎯 TLDR\nBias: TĂNG — dòng tiền vào.", "bullish"),
    ("## 🎯 TLDR\n- Stance ngày mai: GIẢM — cẩn trọng.", "bearish"),
])
def test_detect_stance_reads_morning_bias_label(tldr, want):
    """Brief sáng ghi "**Bias:**", không phải "Stance" — 14/34 brief sáng từng thành unknown."""
    import vnstock_brief as vb
    assert vb._detect_stance(tldr) == want


def test_plain_run_reuses_saved_backfill_with_published_winning(tmp_path):
    import vnstock_ta_score_io as tio
    meta = tmp_path / "_meta"
    meta.mkdir()
    (meta / "horizon_state.json").write_text(json.dumps({"published": [
        {"as_of": "2026-11-03", "short": 1}]}), encoding="utf-8")
    assert tio.merge_short_states(tmp_path) == ({"2026-11-03": 1}, "horizon_state.json")
    tio.save_backfill(tmp_path, {"2026-11-02": -1, "2026-11-03": 0})
    states, src = tio.merge_short_states(tmp_path)
    assert states == {"2026-11-02": -1, "2026-11-03": 1}            # published thắng ngày trùng
    assert src.startswith("dựng lại ngày") and "horizon_state.json" in src
