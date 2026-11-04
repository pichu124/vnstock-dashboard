"""Độ rộng trên TẬP MÃ ĐẦU TƯ ĐƯỢC (PTKT §16, `VNSTOCK_BREADTH_UNIVERSE`).

Canh: định nghĩa tập (≥200 bar/400 ngày + GTGD TB20 ≥1 tỷ + không trễ > N phiên), runner và
`breadth_history` ra CÙNG số cho cùng phiên, công tắc tắt ⇒ chữ brief y nguyên, bật ⇒ nhãn ghi
rõ tập, và công cụ chạy lại lịch sử chỉ đọc kho.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import vnstock_breadth_universe as bu

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("VNSTOCK_BREADTH", "VNSTOCK_SCREENER_STALE", "VNSTOCK_INDICATOR_LEGACY",
                         "VNSTOCK_HORIZONS")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VNSTOCK_HORIZONS", "0")


def _sessions(n: int, end: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    end = end if end is not None else pd.Timestamp.today().normalize()
    return pd.bdate_range(end=end, periods=n)


# ── Định nghĩa tập (hàm thuần) ───────────────────────────────────────────────

def test_universe_env_defaults_to_all_and_ignores_typos(monkeypatch):
    assert bu.breadth_universe() == "all"
    monkeypatch.setenv(bu.UNIVERSE_ENV, " Investable ")
    assert bu.breadth_universe() == "investable"
    monkeypatch.setenv(bu.UNIVERSE_ENV, "investible")
    assert bu.breadth_universe() == "all"


def test_investable_mask_bars_liquidity_and_staleness():
    s = _sessions(260)
    d = s[-1:]
    full = s
    liquid = np.full(len(full), 200_000.0)               # 20 nghìn × 200k cp = 4 tỷ/phiên
    close = np.full(len(full), 20.0)
    assert bu.investable_mask(full, close, liquid, s, d, max_lag=5).tolist() == [True]
    # < 200 bar trong 400 ngày
    assert not bu.investable_mask(full[-150:], close[-150:], liquid[-150:], s, d, max_lag=5)[0]
    # GTGD TB20 0,5 tỷ
    assert not bu.investable_mask(full, close, np.full(len(full), 25_000.0), s, d, max_lag=5)[0]
    # bar cuối trễ 6 phiên > 5 ⇒ loại; trần 6 ⇒ còn (nếu GTGD vẫn đủ)
    stale_t, stale_c = full[:-6], close[:-6]
    big = np.full(len(stale_t), 2_000_000.0)             # 40 tỷ/phiên: 14/20 phiên có bar vẫn đủ
    assert not bu.investable_mask(stale_t, stale_c, big, s, d, max_lag=5)[0]
    assert bu.investable_mask(stale_t, stale_c, big, s, d, max_lag=6)[0]
    assert bu.investable_mask(stale_t, stale_c, big, s, d, max_lag=0)[0]      # 0 = tắt lọc
    # không có lịch phiên ⇒ không tính được
    assert not bu.investable_mask(full, close, liquid, pd.DatetimeIndex([]), d, max_lag=5)[0]


def test_investable_mask_counts_sessions_without_bar_as_zero_gtgd():
    """Mã thưa bar: 10/20 phiên cuối có bar 1,6 tỷ ⇒ TB20 theo LỊCH PHIÊN = 0,8 tỷ < 1."""
    s = _sessions(260)
    keep = np.r_[np.arange(240), np.arange(240, 260, 2)]
    t = s[keep]
    vol = np.full(len(t), 80_000.0)                       # 20 × 80k / 1e6 = 1,6 tỷ
    assert not bu.investable_mask(t, np.full(len(t), 20.0), vol, s, s[-1:], max_lag=5)[0]
    g = bu.session_gtgd20(t, np.full(len(t), 20.0), vol, s)
    assert g.iloc[-1] == pytest.approx(0.8)


def test_investable_mask_matches_the_three_rules_on_every_session():
    """Mã thưa bar ngẫu nhiên, mọi phiên: mask (tổng tích luỹ) == ba luật đọc thẳng từ
    ``session_gtgd20`` (rolling) + ``session_lag`` + đếm bar trong 400 ngày."""
    rng = np.random.default_rng(9)
    s = _sessions(500)
    seen = set()
    for _ in range(6):
        keep = np.sort(rng.choice(len(s), size=int(rng.integers(150, 480)), replace=False))
        t = s[keep]
        close = 10 + rng.random(len(t)) * 20
        vol = rng.choice([20_000.0, 60_000.0, 150_000.0], size=len(t))
        days = s[30:]
        got = bu.investable_mask(t, close, vol, s, days, max_lag=5)
        g = bu.session_gtgd20(t, close, vol, s).reindex(days).to_numpy()
        lag = bu.session_lag(t, s, days)
        n = np.array([((t <= d) & (t >= d - pd.Timedelta(days=400))).sum() for d in days])
        exp = (n >= 200) & (np.nan_to_num(g, nan=-1) >= 1.0) & (np.nan_to_num(lag, nan=99) <= 5)
        assert got.tolist() == exp.tolist()
        seen |= set(exp.tolist())
    assert seen == {True, False}                                 # có ca cả hai phía


def test_investable_mask_reads_stale_limit_like_screener(monkeypatch):
    s = _sessions(260)
    t = s[:-8]
    args = (t, np.full(len(t), 20.0), np.full(len(t), 5_000_000.0), s, s[-1:])
    assert not bu.investable_mask(*args)[0]               # mặc định 5 phiên
    monkeypatch.setenv("VNSTOCK_SCREENER_STALE_SESSIONS", "10")
    assert bu.investable_mask(*args)[0]


def test_breadth_fields_picks_the_active_set_and_keeps_both():
    off = bu.breadth_fields(1000, 110, 270, 81, "all")
    assert (off["above_ma200"], off["above_ma200_pct"], off["breadth_universe"], off["breadth_n"]) \
        == (110, 11.0, "all", 1000)
    assert (off["above_ma200_pct_all"], off["above_ma200_pct_investable"]) == (11.0, 30.0)
    assert (off["ma200_n_all"], off["ma200_n_investable"]) == (1000, 270)
    on = bu.breadth_fields(1000, 110, 270, 81, "investable")
    assert (on["above_ma200"], on["above_ma200_pct"], on["breadth_universe"], on["breadth_n"]) \
        == (81, 30.0, "investable", 270)
    # tập thanh khoản không tính được ⇒ ghi đúng tập THỰC DÙNG
    na = bu.breadth_fields(1000, 110, 0, 0, "investable")
    assert (na["above_ma200_pct"], na["breadth_universe"], na["above_ma200_pct_investable"]) \
        == (11.0, "all", None)
    assert bu.with_universe(off, "investable") == on
    assert bu.with_universe(on, "all") == off


def test_label_suffix_only_for_investable():
    assert bu.label_suffix({"breadth_universe": "investable", "breadth_n": 1269}) \
        == " (1,269 mã thanh khoản)"
    assert bu.label_suffix({"breadth_universe": "all", "breadth_n": 1400}) == ""
    assert bu.label_suffix({}) == "" and bu.label_suffix(None) == ""


def test_compare_script_reuses_the_shared_gtgd_definition():
    spec = importlib.util.spec_from_file_location(
        "cif_bu", _ROOT / "scripts" / "compare_indicator_formulas.py")
    cif = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cif)
    assert cif.session_gtgd20 is bu.session_gtgd20


# ── Runner ↔ breadth_history: cùng phiên, cùng số ───────────────────────────

def _write(wh: Path, tk: str, t, close, volume) -> None:
    df = pd.DataFrame({"time": pd.DatetimeIndex(t), "open": close, "high": close, "low": close,
                       "close": close, "volume": volume})
    for y, g in df.groupby(df["time"].dt.year):
        d = wh / "prices" / f"ticker={tk}" / f"year={y}"
        d.mkdir(parents=True, exist_ok=True)
        g.to_parquet(d / "data.parquet", index=False)


@pytest.fixture()
def wh(tmp_path):
    pytest.importorskip("pyarrow")
    s = _sessions(300)
    up = 20 * np.exp(np.linspace(0, 0.5, len(s)))
    down = 20 * np.exp(np.linspace(0.5, 0, len(s)))
    liq = np.full(len(s), 200_000.0)
    _write(tmp_path, "VNINDEX", s, 1200 * np.exp(np.linspace(0, 0.1, len(s))), liq)
    _write(tmp_path, "AAA", s, up, liq)                              # thanh khoản, trên MA200
    _write(tmp_path, "BBB", s, down, liq)                            # thanh khoản, dưới
    _write(tmp_path, "CCC", s, up, np.full(len(s), 10_000.0))        # 0,2–0,3 tỷ: loại
    _write(tmp_path, "DDD", s[-150:], up[-150:], liq[-150:])         # < 200 bar: loại
    _write(tmp_path, "EEE", s[:-8], up[:-8], np.full(len(s) - 8, 5_000_000.0))  # trễ 8 phiên
    (tmp_path / "_meta").mkdir()
    pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
                  "primary_industry": ["Ngân hàng"] * 5}).to_parquet(
        tmp_path / "_meta" / "industry_classification.parquet", index=False)
    return tmp_path, s


_KEYS = ("above_ma200_pct", "breadth_universe", "breadth_n", "above_ma200_pct_all",
         "ma200_n_all", "above_ma200_pct_investable", "ma200_n_investable")


@pytest.mark.parametrize("universe, stale, exp", [
    ("all", None, (60.0, "all", 5, 60.0, 5, 50.0, 2)),
    ("investable", None, (50.0, "investable", 2, 60.0, 5, 50.0, 2)),
    ("investable", "10", (66.7, "investable", 3, 60.0, 5, 66.7, 3)),   # EEE trễ 8 ≤ 10 ⇒ vào
])
def test_runner_and_breadth_history_agree(wh, monkeypatch, universe, stale, exp):
    import vnstock_horizons_state as hs
    import vnstock_runner as vr
    root, s = wh
    if universe != "all":
        monkeypatch.setenv(bu.UNIVERSE_ENV, universe)
    if stale:
        monkeypatch.setenv("VNSTOCK_SCREENER_STALE_SESSIONS", stale)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    b = vr.build_market_overview(str(root))["breadth"]
    last = s[-1].date()
    h = hs.breadth_history(root, [last])[last]
    assert tuple(b[k] for k in _KEYS) == exp
    assert tuple(h[k] for k in _KEYS) == exp
    assert b["above_ma200"] == round(exp[0] * exp[2] / 100)
    assert b["total"] == h["total"] == 5                  # RSI/A-D vẫn trên mọi mã
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def test_runner_without_vnindex_falls_back_to_all(wh, monkeypatch):
    import shutil

    import vnstock_runner as vr
    root, _ = wh
    shutil.rmtree(root / "prices" / "ticker=VNINDEX")
    monkeypatch.setenv(bu.UNIVERSE_ENV, "investable")
    b = vr.build_market_overview(str(root))["breadth"]
    assert (b["above_ma200_pct"], b["breadth_universe"], b["above_ma200_pct_investable"]) \
        == (60.0, "all", None)


def test_breadth_history_universe_arg_matches_with_universe(wh):
    import vnstock_horizons_state as hs
    root, s = wh
    days = [x.date() for x in s[-30:]]
    a = hs.breadth_history(root, days, "all")
    i = hs.breadth_history(root, days, "investable")
    assert a.keys() == i.keys()
    assert all(bu.with_universe(a[d], "investable") == i[d] for d in days)


# ── horizons: inputs ghi tập, brief_view không so 4 tuần khác tập ────────────

def _closes(n: int = 260) -> tuple[list[date], list[float]]:
    s = _sessions(n)
    return [x.date() for x in s], list(1200 * np.exp(np.linspace(0, 0.1, n)))


def test_score_inputs_records_universe_only_when_investable():
    import vnstock_horizons_state as hs
    dates, closes = _closes()
    d = dates[-1]
    rec = {"total": 1000, **bu.breadth_fields(1000, 110, 270, 81, "all"),
           "advances": 400, "declines": 500, "ad_ratio": 0.8}
    old = hs.score_inputs(dates, closes, [d], {d: rec}, {})[d]
    assert set(old) == {"score", "n", "label_old", "momentum", "floor_old", "breadth_pct",
                        "ad", "nn"}
    assert old["breadth_pct"] == 11.0
    new = hs.score_inputs(dates, closes, [d], {d: bu.with_universe(rec, "investable")}, {})[d]
    assert (new["breadth_pct"], new["breadth_universe"], new["breadth_n"]) == (30.0, "investable", 270)


def _snap(as_of: str) -> dict:
    return {"as_of": as_of, "short": 0, "short_since": as_of, "medium": 0,
            "medium_since": as_of, "week_closed": False, "levels": [], "alert": {"tier": 0},
            "ma_w": None}


def test_brief_view_drops_4w_compare_across_sets():
    import vnstock_horizons_state as hs
    dates, _ = _closes(40)
    keys = [d.isoformat() for d in dates]
    inputs = {k: {"close": 1.0, "breadth_pct": 11.0} for k in keys}
    snap = _snap(keys[-1])

    def view(inp):
        lp = hs.Latest(state={"inputs": inp, "published": [snap]}, snap=snap, missing=None,
                       expect=dates[-1])
        return hs.brief_view(lp)

    v = view(inputs)
    assert v["breadth_pct_4w"] == 11.0 and "breadth_universe" not in v
    inv = {**inputs, keys[-1]: {"close": 1.0, "breadth_pct": 30.0,
                                "breadth_universe": "investable", "breadth_n": 270}}
    v = view(inv)                                          # vừa bật: 4 tuần trước là tập cũ
    assert (v["breadth_pct"], v["breadth_pct_4w"], v["breadth_universe"], v["breadth_n"]) \
        == (30.0, None, "investable", 270)
    both = {k: {"close": 1.0, "breadth_pct": 30.0, "breadth_universe": "investable",
                "breadth_n": 270} for k in keys}
    assert view(both)["breadth_pct_4w"] == 30.0


def test_horizon_medium_line_names_the_set():
    from vnstock_brief_canon import _horizon_medium_line
    base = {"snap": {"medium": 0, "medium_since": "2026-10-05"}, "medium_weeks": 4,
            "breadth_pct": 30.0, "breadth_pct_4w": 28.0}
    off = _horizon_medium_line(base, {})
    assert "; 30% mã trên MA200 (4 tuần trước 28%)." in off
    on = _horizon_medium_line({**base, "breadth_universe": "investable", "breadth_n": 270}, {})
    assert on == off.replace("trên MA200 (4", "trên MA200 (270 mã thanh khoản) (4")


# ── Brief: tắt ⇒ chữ y nguyên; bật ⇒ nhãn ghi tập ───────────────────────────

_BREADTH_OLD = {"total": 1407, "above_ma200": 157, "above_ma200_pct": 11.2,
                "rsi_oversold": 40, "rsi_overbought": 12, "advances": 500, "declines": 600,
                "ad_ratio": 0.83, "net_new_highs": -7}
_MIN_CTX = {"date": "2026-11-03", "time": "20:30"}


def _breadth_block(prompt: str) -> str:
    i = prompt.index("## Market Breadth")
    return prompt[i:prompt.index("\n\n", i + 1) if "\n\n" in prompt[i + 1:] else None]


def test_prompt_unchanged_when_switch_off():
    import vnstock_brief as vb
    new_keys = {**_BREADTH_OLD, **bu.breadth_fields(1407, 157, 269, 81, "all")}
    p_old = vb.build_prompt({**_MIN_CTX, "breadth": dict(_BREADTH_OLD)}, brief_type="close")
    p_new = vb.build_prompt({**_MIN_CTX, "breadth": new_keys}, brief_type="close")
    assert p_old == p_new
    assert ("## Market Breadth\nTrên MA200: 11% | A/D ratio: 0.83 | Net new highs: -7 | "
            "RSI oversold: 40 mã | RSI overbought: 12 mã\n→ ĐỘ RỘNG: TIÊU CỰC (A/D < 1.0 · ít mã "
            "trên MA200 → thị trường yếu) — DÙNG ĐÚNG nhãn này, KHÔNG tự suy ngược "
            "(A/D<1 = tiêu cực).") in p_old


def test_prompt_names_the_set_when_investable():
    import vnstock_brief as vb
    b = {**_BREADTH_OLD, **bu.breadth_fields(1407, 157, 269, 81, "investable")}
    blk = _breadth_block(vb.build_prompt({**_MIN_CTX, "breadth": b}, brief_type="close"))
    assert blk.startswith("## Market Breadth\nTrên MA200 (269 mã thanh khoản): 30% | ")
    assert 'PHẢI ghi kèm "(269 mã thanh khoản)"' in blk
    assert "RSI oversold: 40 mã" in blk                  # đếm RSI vẫn trên mọi mã


_INV = {"breadth": {"above_ma200_pct": 30.1, "breadth_universe": "investable", "breadth_n": 269}}
_ALL = {"breadth": {"above_ma200_pct": 30.1, "breadth_universe": "all", "breadth_n": 1407}}


@pytest.mark.parametrize("text, expect", [
    ("chỉ 30% mã cổ phiếu tăng giá, A/D 0.9",
     "chỉ 30% mã cổ phiếu trên MA200 (269 mã thanh khoản), A/D 0.9"),
    ("Có 30% mã trên MA200 hôm nay.", "Có 30% mã trên MA200 (269 mã thanh khoản) hôm nay."),
    ("Trên MA200: 30% | A/D", "Trên MA200 (269 mã thanh khoản): 30% | A/D"),
    ("30,1% số mã nằm trên đường MA200.", "30,1% số mã nằm trên đường MA200 (269 mã thanh khoản)."),
    ("30% mã trên MA200 (269 mã thanh khoản)", "30% mã trên MA200 (269 mã thanh khoản)"),
    ("12% mã trên MA200 tuần trước", "12% mã trên MA200 tuần trước"),     # số khác: không đụng
])
def test_breadth_label_guard_tags_the_set(text, expect):
    from vnstock_brief_guards_numbers import enforce_breadth_label
    out = enforce_breadth_label(text, _INV)
    assert out == expect
    assert enforce_breadth_label(out, _INV) == out


def test_breadth_label_guard_unchanged_when_switch_off():
    from vnstock_brief_guards_numbers import enforce_breadth_label
    t = "chỉ 30% mã cổ phiếu tăng giá; 30% mã trên MA200; Trên MA200: 30%"
    exp = "chỉ 30% mã cổ phiếu trên MA200; 30% mã trên MA200; Trên MA200: 30%"
    assert enforce_breadth_label(t, _ALL) == exp
    assert enforce_breadth_label(t, {"breadth": {"above_ma200_pct": 30.1}}) == exp


# ── Công cụ chạy lại lịch sử ──────────────────────────────────────────────────

def _replay():
    spec = importlib.util.spec_from_file_location(
        "replay_breadth_universe", _ROOT / "scripts" / "replay_breadth_universe.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_breadth_vote_follows_regime_thresholds():
    rb = _replay()
    assert [rb.breadth_vote(p) for p in (11.0, 35.0, 45.0, 55.0, 55.1, None)] \
        == [-1, 0, 0, 0, 1, None]


def test_compare_counts_vote_short_and_stance_changes():
    """Tập cũ 10% (phiếu −1) · tập mới 60% (phiếu +1) mọi phiên ⇒ 100% phiếu đổi; ngắn hạn
    và Stance khác đúng như gấp trực tiếp từ `score_inputs` từng tập."""
    import vnstock_horizons as hz
    import vnstock_horizons_state as hs
    from vnstock_ta_score_io import short_states_from_scores
    rb = _replay()
    rng = np.random.default_rng(3)
    s = _sessions(320)
    dates = [x.date() for x in s]
    closes = list(1200 * np.exp(np.cumsum(rng.normal(0, 0.01, len(s)))))
    targets = dates[199:]
    rec = {"total": 100, **bu.breadth_fields(100, 10, 20, 12, "all"),
           "advances": 50, "declines": 50, "ad_ratio": 1.0}
    breadth = {d: dict(rec) for d in targets}
    r = rb.compare(dates, closes, targets, breadth, {})
    assert r["sessions"] == len(targets) == r["investable_sessions"]
    assert r["breadth_median"] == {"all": 10.0, "investable": 60.0}
    assert r["vote"]["changed_pct"] == 100.0 and r["vote"]["transitions"] == {"-1 → +1": len(targets)}
    sh = {u: short_states_from_scores(
        dates, hs.score_inputs(dates, closes, targets,
                               {d: bu.with_universe(x, u) for d, x in breadth.items()}, {}))
        for u in ("all", "investable")}
    diff = sum(1 for k in sh["all"] if sh["all"][k] != sh["investable"].get(k))
    assert r["short"]["changed"] == diff > 0
    assert sum(r["short"]["transitions"].values()) == diff
    assert all(k.split(" → ")[0] in hz.SHORT_LABEL.values() for k in r["short"]["transitions"])
    assert r["stance"]["changed"] >= r["stance"]["forced_changed"] > 0
    for u in ("all", "investable"):
        t20 = r["t4"][u]["t20"]
        assert t20["_all"]["n"] == len(sh[u]) - 20
        assert sum(t20[lbl]["n"] for lbl in hz.SHORT_LABEL.values() if lbl in t20) == t20["_all"]["n"]


def test_replay_main_is_read_only_and_matches_rebuild_short_states(wh, tmp_path_factory, capsys):
    from vnstock_ta_score_io import rebuild_short_states
    rb = _replay()
    root, s = wh
    before = sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob("*"))
    out = tmp_path_factory.mktemp("out") / "out.json"
    assert rb.main(["--warehouse", str(root), "--json", str(out)]) == 0
    assert sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob("*")) == before
    text = capsys.readouterr().out
    assert "1) Phiếu độ rộng regime" in text and "4) T4" in text and "⏱" in text
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sessions"] == len(s) - 199
    assert set(data["t4"]) == {"all", "investable"} and set(data["t4"]["all"]) == {"t5", "t20", "t60"}
    # đúng đường rebuild_short_states, từng tập
    import vnstock_horizons_state as hs
    dates, closes = hs.load_vnindex(root)
    targets = dates[199:]
    breadth = hs.breadth_history(root, targets, "all", sessions=dates)
    for u in ("all", "investable"):
        b_u = {d: bu.with_universe(x, u) for d, x in breadth.items()}
        from vnstock_ta_score_io import short_states_from_scores
        mine = short_states_from_scores(dates, hs.score_inputs(dates, closes, targets, b_u, {}))
        assert mine == rebuild_short_states(root, u)


def test_replay_main_refuses_missing_warehouse(tmp_path, capsys):
    assert _replay().main(["--warehouse", str(tmp_path / "nope")]) == 2


def test_market_tab_ma200_card_uses_universe_denominator():
    """Bật tập investable mà thẻ vẫn chia cho tổng mã ⇒ "81/1407 mã" cạnh 30% (review 04/11)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "market_tab.py").read_text(encoding="utf-8")
    assert 'breadth.get("breadth_n") or breadth["total"]' in src


def test_market_commentary_breadth_line_names_the_universe():
    """Bật investable mà commentary vẫn in "X% mã trên MA200" trần ⇒ đọc như số cũ (review 04/11)."""
    from dashboard.market_commentary import breadth_lines
    base = {"above_ma200_pct": 30.0, "ad_ratio": 1.0, "rsi_oversold": 10, "rsi_overbought": 5,
            "net_new_highs": 0}
    old = "\n".join(breadth_lines(base))
    assert "30% mã trên MA200 —" in old                                   # tập all: chữ y nguyên
    inv = "\n".join(breadth_lines({**base, "breadth_universe": "investable", "breadth_n": 269}))
    assert "30% mã trên MA200 (269 mã thanh khoản) —" in inv
