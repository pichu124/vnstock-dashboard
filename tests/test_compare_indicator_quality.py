"""PTKT P1 đợt 1b — `scripts/compare_indicator_formulas.py` phần 6 (chất lượng tín hiệu theo biến
thể) và 7 (chẩn đoán độ rộng theo mẫu số). Dữ liệu tổng hợp, không cần kho."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cif():
    spec = importlib.util.spec_from_file_location(
        "compare_indicator_formulas", ROOT / "scripts" / "compare_indicator_formulas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ohlcv(n: int, seed: int, start: str = "2025-01-02", base: float = 20.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = base * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
    return pd.DataFrame({"time": pd.bdate_range(start, periods=n), "open": c, "high": c * 1.01,
                         "low": c * 0.99, "close": c, "volume": 200_000.0})


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return a.index.equals(b.index) and np.allclose(a.to_numpy(float), b.to_numpy(float),
                                                   equal_nan=True, rtol=0, atol=0)


# ── 6) Chất lượng tín hiệu ───────────────────────────────────────────────────

def test_signal_panel_excess_return_hand_computed(cif):
    df = _ohlcv(100, seed=1)
    sessions = pd.DatetimeIndex(df["time"])
    df.loc[70, "close"] = 10.0
    df.loc[75, "close"] = 11.0                      # T+5 của phiên 70: +10%
    df = df.drop(index=90)                          # mã không khớp lệnh phiên 90
    df.loc[89, "close"] = 12.0
    vni = np.full(len(sessions), 1000.0)
    vni[75] = 1040.0                                # VN-Index +4% cùng kỳ
    p = cif.ticker_signal_panel(df, sessions, vni, sessions[[70, 85, 99]], horizons=(5, 20))
    assert list(p.index) == list(sessions[[70, 85, 99]])
    assert p.at[sessions[70], "ex_5"] == pytest.approx(6.0)
    # phiên đích 90 không có bar ⇒ giá khớp gần nhất TRƯỚC nó (phiên 89), không lấy bar sau
    c85 = df.set_index("time").at[sessions[85], "close"]
    assert p.at[sessions[85], "ex_5"] == pytest.approx((12.0 / c85 - 1) * 100)
    assert np.isnan(p.at[sessions[99], "ex_5"]) and np.isnan(p.at[sessions[85], "ex_20"])


def test_signal_panel_no_lookahead(cif):
    """Đổi bar SAU cửa sổ T+20 không đổi gì; đổi đúng bar T+20 chỉ đổi ex_20 của phiên đó."""
    df = _ohlcv(400, seed=7)
    sessions = pd.DatetimeIndex(df["time"])
    vni = np.linspace(1000, 1200, len(sessions))
    sig = sessions[300:350]
    base = cif.ticker_signal_panel(df, sessions, vni, sig)
    assert len(base) == 50 and base["ex_20"].notna().all()

    after = df.copy()
    after.loc[370:, ["open", "high", "low", "close"]] *= 3.0     # sau T+20 của phiên tín hiệu cuối
    after.loc[370:, "volume"] = 1.0
    assert _same(cif.ticker_signal_panel(after, sessions, vni, sig), base)

    inside = df.copy()
    inside.loc[320, "close"] *= 1.5                              # = T+20 của phiên 300
    got = cif.ticker_signal_panel(inside, sessions, vni, sig)
    t0 = sessions[300]
    assert got.at[t0, "ex_20"] != pytest.approx(base.at[t0, "ex_20"])
    assert got.at[t0, "ex_5"] == base.at[t0, "ex_5"]
    assert got.at[t0, "rsi_w"] == base.at[t0, "rsi_w"] and got.at[t0, "rsi_c"] == base.at[t0, "rsi_c"]
    assert got.at[sessions[315], "ex_5"] != pytest.approx(base.at[sessions[315], "ex_5"])
    assert got.at[sessions[301], "ex_20"] == base.at[sessions[301], "ex_20"]


def test_signal_panel_matches_screener_indicators(cif):
    from vnstock_screener import _calc_indicators
    df = _ohlcv(320, seed=4)
    sessions = pd.DatetimeIndex(df["time"])
    p = cif.ticker_signal_panel(df, sessions, np.ones(len(sessions)), sessions[-1:])
    ind = _calc_indicators(df.tail(300).reset_index(drop=True))
    assert p["rsi_c"].iloc[-1] == ind["rsi_14"]
    assert p["p52"].iloc[-1] == pytest.approx(ind["52w_pct"], abs=0.15)   # screener làm tròn H/L 2 số


def test_signal_panel_cutler_without_down_day_is_no_signal(cif):
    """Screener: 14 phiên không giảm ⇒ loss 0 ⇒ rsi_14 None ⇒ không vào overbought; Wilder còn nhớ
    phiên giảm cũ nên vẫn có số."""
    from vnstock_screener import _calc_indicators
    df = _ohlcv(90, seed=3)
    df.loc[70:, "close"] = 30.0 + np.arange(20)
    sessions = pd.DatetimeIndex(df["time"])
    p = cif.ticker_signal_panel(df, sessions, np.ones(len(sessions)), sessions[-1:])
    assert _calc_indicators(df)["rsi_14"] is None
    assert np.isnan(p["rsi_c"].iloc[-1]) and p["rsi_w"].iloc[-1] > 70
    assert not cif.signal_mask(p, "overbought", "rsi_c", 70.0).any()
    assert cif.signal_mask(p, "overbought", "rsi_w", 70.0).all()


def test_signal_panel_needs_bar_on_day_and_screener_min_rows(cif):
    df = _ohlcv(80, seed=2)
    sessions = pd.DatetimeIndex(df["time"])
    gap = df.drop(index=70)
    p = cif.ticker_signal_panel(gap, sessions, np.ones(len(sessions)), sessions[[50, 70, 75]])
    assert list(p.index) == [sessions[75]]          # phiên 50: mới 51 bar < 60; phiên 70: không bar


def test_session_gtgd20_counts_missing_sessions_as_zero(cif):
    sessions = pd.bdate_range("2026-01-05", periods=40)
    t = sessions[10::2]                             # khớp lệnh cách phiên, mỗi phiên 2 tỷ
    g = cif.session_gtgd20(t, np.full(len(t), 10.0), np.full(len(t), 200_000.0), sessions)
    assert g.iloc[:29].isna().all()                 # chưa đủ 20 phiên kể từ bar đầu (phiên 10)
    assert g.iloc[-1] == pytest.approx(1.0)


def test_wilson_interval(cif):
    assert cif.wilson(50, 100) == (40.4, 59.6)
    lo, hi = cif.wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-9) and hi == pytest.approx(27.8, abs=0.05)
    assert cif.wilson(0, 0) == (None, None)


def test_signal_masks_match_preset_lambdas(cif):
    from vnstock_screener import PRESETS
    rng = np.random.default_rng(0)
    n = 400
    rsi = rng.uniform(10, 90, n).round(1)
    rsi[::17] = np.nan
    rsi[5], rsi[6] = 30.0, 40.0
    p52 = rng.uniform(0, 40, n).round(1)
    p52[::13] = np.nan
    panel = pd.DataFrame({"rsi_c": rsi, "p52": p52})

    def row(i):
        r = {"rsi_14": None if np.isnan(rsi[i]) else float(rsi[i])}
        if not np.isnan(p52[i]):                    # < 50 bar ⇒ screener không có khoá 52w_pct
            r["52w_pct"] = float(p52[i])
        return r

    for sig, thr in (("oversold", 30.0), ("overbought", 70.0), ("reversal", 40.0)):
        want = [cif._match(PRESETS[sig]["filter"], row(i)) for i in range(n)]
        assert list(cif.signal_mask(panel, sig, "rsi_c", thr)) == want, sig


def _panel():
    # 6 mã·phiên của 3 mã; ex_5 đã biết, một dòng chưa có T+5
    return pd.DataFrame({
        "ticker": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
        "rsi_c": [25.0, 28.0, 50.0, np.nan, 75.0, 29.0],
        "rsi_w": [32.0, 26.0, 50.0, 33.0, 68.0, 31.0],
        "p52": [10.0, 5.0, 50.0, 12.0, 90.0, 14.0],
        "gtgd20": [2.0, 2.0, 0.5, 0.5, 3.0, np.nan],
        "ex_5": [4.0, -2.0, 1.0, 6.0, -3.0, np.nan],
    })


def test_signal_quality_rows(cif):
    rows = cif.signal_quality(_panel(), {"oversold": 35.0, "overbought": 66.9, "reversal": 42.2},
                              horizons=(5,), min_gtgd=1.0)
    get = {(r["loc"], r["tin_hieu"], r["bien_the"]): r for r in rows}
    nen = get[("tat_ca", "nen", "mọi mã·phiên")]
    assert (nen["n"], nen["so_ma"], nen["tb"], nen["trung_vi"]) == (5, 3, 1.2, 1.0)
    assert nen["duong_pct"] == 60.0 and nen["wilson_lo"] < 60 < nen["wilson_hi"]
    c30 = get[("tat_ca", "oversold", "Cutler 30 (hiện hành)")]
    assert (c30["n"], c30["so_ma"], c30["tb"], c30["duong_pct"]) == (2, 1, 1.0, 50.0)  # CCC 29 chưa có T+5
    w30 = get[("tat_ca", "oversold", "Wilder 30")]
    assert (w30["n"], w30["tb"]) == (1, -2.0)
    w35 = get[("tat_ca", "oversold", "Wilder 35 (gợi ý)")]
    assert (w35["n"], w35["so_ma"], w35["tb"]) == (3, 2, 2.67)
    assert get[("tat_ca", "overbought", "Wilder 66.9 (gợi ý)")]["tb"] == -3.0
    assert get[("tat_ca", "overbought", "Wilder 70")]["n"] == 0
    assert get[("tat_ca", "reversal", "Wilder 42.2 (gợi ý)")]["n"] == 3
    liq = get[("gtgd", "nen", "mọi mã·phiên")]
    assert (liq["n"], liq["so_ma"]) == (3, 2)        # BBB 0,5 tỷ và dòng NaN bị loại
    assert get[("gtgd", "oversold", "Wilder 35 (gợi ý)")]["n"] == 2


def test_signal_thresholds_from_run_or_fallback(cif):
    run = {"rsi_qua_ban_30": {"goi_y": 34.1}, "rsi_qua_mua_70": {"goi_y": None},
           "rsi_reversal_40": {"goi_y": 41.0}}
    assert cif.signal_thresholds(run) == {"oversold": 34.1, "overbought": 66.9, "reversal": 41.0}
    assert cif.signal_thresholds(None) == cif.SUGGESTED_FALLBACK


def test_stale_constant_matches_screener(cif):
    import vnstock_screener as vs
    assert cif.STALE_SESSIONS == vs.STALE_SESSIONS


# ── 7) Chẩn đoán độ rộng ─────────────────────────────────────────────────────

def test_ticker_breadth_extra_lag_matches_screener(cif):
    from vnstock_screener import stale_sessions
    sessions = pd.bdate_range("2026-01-05", periods=30)
    t = sessions[:21]
    days = sessions[-5:]
    ex = cif.ticker_breadth_extra(t, np.full(21, 10.0), np.full(21, 1e5), days, sessions)
    assert list(ex["lag"]) == [stale_sessions(t[-1], sessions[sessions <= d]) for d in days]
    assert list(ex["lag"]) == [5.0, 6.0, 7.0, 8.0, 9.0]


def test_breadth_by_denominator(cif):
    day = pd.Timestamp("2026-11-03")
    st = pd.DataFrame({
        "ticker": ["NEW", "BIG", "HNX", "OLD", "OUT"],
        "counted": [True, True, True, True, False],
        "above_ema": [np.nan, 1.0, 0.0, 1.0, 1.0],
        "above_sma": [np.nan, 1.0, 0.0, 0.0, 1.0],
        "gtgd20": [5.0, 2.0, 0.5, 3.0, 9.0],
        "lag": [0.0, 0.0, 0.0, 10.0, 0.0],
    }, index=[day] * 5)
    d = cif.breadth_by_denominator(st, hose={"BIG", "OLD"}, vn30={"BIG"}, min_gtgd=1.0)
    got = {k: (int(v.at[day, "n"]), v.at[day, "pct_sma200"], v.at[day, "pct_ema200"])
           for k, v in d.items()}
    assert got == {"a": (4, 25.0, 50.0), "a_fresh": (3, 33.3, 33.3), "b": (3, 33.3, 66.7),
                   "c": (2, 50.0, 100.0), "d": (2, 50.0, 100.0), "e": (1, 100.0, 100.0)}
    assert "d" not in cif.breadth_by_denominator(st, hose=None, vn30=set())
    assert int(cif.stale_counts(st).at[day]) == 1


# ── main trên kho giả (chỉ đọc) ──────────────────────────────────────────────

def _write_ticker(wh: Path, tk: str, df: pd.DataFrame) -> None:
    for y in sorted(set(df["time"].dt.year)):
        d = wh / "prices" / f"ticker={tk}" / f"year={y}"
        d.mkdir(parents=True)
        df[df["time"].dt.year == y].to_parquet(d / "data.parquet", index=False)


def test_main_prints_quality_and_breadth_diag(cif, tmp_path, capsys):
    pytest.importorskip("pyarrow")
    wh = tmp_path / "wh"
    _write_ticker(wh, "VNINDEX", _ohlcv(420, seed=1, start="2024-06-03", base=1200.0))
    for i, tk in enumerate(("FPT", "AAA", "BBB")):
        _write_ticker(wh, tk, _ohlcv(420, seed=10 + i, start="2024-06-03"))
    (wh / "_meta").mkdir()
    (wh / "_meta" / "exchange_map.json").write_text(json.dumps({"FPT": "HOSE", "AAA": "HNX"}))
    before = sorted(p.relative_to(wh) for p in wh.rglob("*"))
    out = tmp_path / "out.json"
    rc = cif.main(["--warehouse", str(wh), "--days", "30", "--no-presets", "--breadth-diag",
                   "--json", str(out)])
    assert rc == 0
    assert sorted(p.relative_to(wh) for p in wh.rglob("*")) == before
    data = json.loads(out.read_text(encoding="utf-8"))
    nen = [r for r in data["signal_quality"] if r["tin_hieu"] == "nen" and r["loc"] == "tat_ca"]
    assert {r["h"] for r in nen} == {5, 20} and all(r["n"] == 90 and r["so_ma"] == 3 for r in nen)
    assert set(data["breadth_diag"]) == {"a", "a_fresh", "b", "c", "d", "e", "stale"}
    assert data["breadth_diag"]["d"][-1]["n"] == 1 and data["breadth_diag"]["e"][-1]["n"] == 1
    text = capsys.readouterr().out
    assert "6) Chất lượng tín hiệu" in text and "CHỒNG NHAU" in text and "MỘT giai đoạn" in text
    assert "7) Chẩn đoán độ rộng" in text and "HOSE: BỎ" not in text


def test_main_without_exchange_map_skips_hose(cif, tmp_path, capsys):
    pytest.importorskip("pyarrow")
    wh = tmp_path / "wh"
    _write_ticker(wh, "VNINDEX", _ohlcv(300, seed=1, start="2025-01-02", base=1200.0))
    _write_ticker(wh, "AAA", _ohlcv(300, seed=2, start="2025-01-02"))
    rc = cif.main(["--warehouse", str(wh), "--days", "10", "--no-presets", "--breadth-diag",
                   "--no-signal-quality"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "HOSE: BỎ" in text and "6) Chất lượng" not in text
