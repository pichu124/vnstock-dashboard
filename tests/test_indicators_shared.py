"""PTKT P1 đợt 1 (§14b `docs/THIET-KE-PHAN-TICH-KY-THUAT.md`) — nền chỉ báo dùng chung.

* `vnstock_indicators.rsi_wilder/rsi_cutler/sma/ema/atr`: khớp TỪNG GIÁ TRỊ với công thức
  đang chạy ở brief (Wilder) và screener/runner (Cutler) — đợt 2 đổi chỗ gọi mà không đổi số.
* `_vnindex_technicals` gọi `rsi_wilder`, RSI VN-Index không đổi (hồi quy).
* Ngưỡng RSI hai tầng ở canon; nhãn prompt + phiếu regime không đổi chữ.
* `VNSTOCK_BRIEF_SECTOR_ALPHA`: tắt = lời gọi `compute_scores` cũ; bật = alpha vs VN-Index.
* `scripts/compare_indicator_formulas.py`: logic thuần chạy trên dữ liệu tổng hợp.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import vnstock_brief as vb
import vnstock_brief_canon as canon
from vnstock_indicators import atr, ema, rsi_cutler, rsi_wilder, sma

ROOT = Path(__file__).resolve().parent.parent


def _walk(n: int = 300, seed: int = 3, start: float = 1200.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n))))


# ── Công thức tham chiếu: chép NGUYÊN VĂN từ chỗ đang chạy (e55b632) ──────────

def _brief_rsi_ref(close: pd.Series) -> pd.Series:
    """vnstock_brief._vnindex_technicals (trước P1)."""
    delta = close.diff(1)
    up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    dn = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _screener_rsi_ref(c: pd.Series) -> pd.Series:
    """vnstock_screener._calc_indicators / vnstock_runner.build_market_overview."""
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ── rsi_wilder / rsi_cutler ──────────────────────────────────────────────────

class TestRsiWilder:
    def test_matches_brief_formula_value_by_value(self):
        c = _walk()
        new, ref = rsi_wilder(c), _brief_rsi_ref(c)
        np.testing.assert_allclose(new.iloc[14:].to_numpy(), ref.iloc[14:].to_numpy(),
                                   rtol=0, atol=1e-12)
        assert new.iloc[-1] == ref.iloc[-1]

    def test_warmup_is_nan_and_index_kept(self):
        c = _walk(40)
        c.index = pd.date_range("2026-01-01", periods=40, freq="B")
        r = rsi_wilder(c)
        assert r.index.equals(c.index)
        assert r.iloc[:14].isna().all() and r.iloc[14:].notna().all()

    def test_short_series_is_all_nan(self):
        assert rsi_wilder([10.0, 11.0, 12.0]).isna().all()
        assert rsi_wilder([]).empty

    def test_no_loss_means_100_and_flat_means_nan(self):
        up = rsi_wilder(np.arange(1.0, 31.0))
        assert (up.iloc[14:] == 100.0).all()
        assert rsi_wilder(np.full(30, 5.0)).isna().all()

    def test_falling_only_means_0_and_custom_period(self):
        r = rsi_wilder(np.arange(30.0, 0.0, -1.0), n=5)
        assert r.iloc[:5].isna().all() and (r.iloc[5:] == 0.0).all()

    def test_accepts_list_and_ndarray(self):
        c = _walk(60)
        assert rsi_wilder(list(c)).iloc[-1] == pytest.approx(rsi_wilder(c.to_numpy()).iloc[-1])


class TestRsiCutler:
    def test_matches_screener_formula_value_by_value(self):
        c = _walk(seed=11)
        new, ref = rsi_cutler(c), _screener_rsi_ref(c)
        mask = ref.notna()
        assert mask.sum() > 250
        np.testing.assert_allclose(new[mask].to_numpy(), ref[mask].to_numpy(), rtol=0, atol=1e-12)
        assert new.iloc[:14].isna().all()

    def test_no_loss_window_is_100_where_old_code_gave_none(self):
        """Khác biệt DUY NHẤT với code cũ: 14 phiên không giảm ⇒ 100 (cũ: NaN ⇒ None)."""
        c = pd.Series(np.r_[np.linspace(10, 9, 10), np.linspace(9, 12, 20)])
        assert np.isnan(_screener_rsi_ref(c).iloc[-1])
        assert rsi_cutler(c).iloc[-1] == 100.0

    def test_differs_from_wilder(self):
        c = _walk(seed=5)
        assert (rsi_cutler(c) - rsi_wilder(c)).abs().iloc[20:].max() > 1.0


# ── sma / ema / atr ──────────────────────────────────────────────────────────

class TestMovingAverages:
    def test_sma_matches_rolling_mean(self):
        c = _walk(250)
        s = sma(c, 200)
        assert s.iloc[:199].isna().all()
        assert s.iloc[-1] == pytest.approx(c.iloc[-200:].mean(), rel=1e-12)

    def test_ema_matches_screener_value_after_warmup(self):
        c = _walk(300)
        ref = c.ewm(span=200, adjust=False).mean()
        e = ema(c, 200)
        assert e.iloc[:199].isna().all()
        np.testing.assert_allclose(e.iloc[199:].to_numpy(), ref.iloc[199:].to_numpy(),
                                   rtol=0, atol=1e-9)

    def test_short_series(self):
        assert sma([1.0, 2.0], 5).isna().all() and ema([1.0, 2.0], 5).isna().all()


class TestAtr:
    def test_wilder_recursion_with_gap(self):
        h = pd.Series([10.0, 11.0, 12.0, 15.0])
        lo = pd.Series([9.0, 10.0, 11.0, 14.0])
        c = pd.Series([9.5, 10.5, 11.5, 14.5])
        # TR: 1 (bar đầu = H−L) · max(1, 1.5, 0.5)=1.5 · 1.5 · max(1, 3.5, 2.5)=3.5
        a = atr(h, lo, c, n=2)
        assert np.isnan(a.iloc[0])
        assert a.iloc[1] == pytest.approx(0.5 * 1 + 0.5 * 1.5)
        assert a.iloc[2] == pytest.approx(0.5 * a.iloc[1] + 0.5 * 1.5)
        assert a.iloc[3] == pytest.approx(0.5 * a.iloc[2] + 0.5 * 3.5)

    def test_constant_range_converges_to_range(self):
        n = 120
        c = pd.Series(np.full(n, 50.0))
        a = atr(c + 1.0, c - 1.0, c)
        assert a.iloc[:13].isna().all() and a.iloc[-1] == pytest.approx(2.0)

    def test_short_series(self):
        assert atr([2.0], [1.0], [1.5]).isna().all()


# ── _vnindex_technicals: chuyển sang rsi_wilder, số không đổi ────────────────

def _vni_df(n: int = 260) -> pd.DataFrame:
    c = _walk(n, seed=21)
    return pd.DataFrame({"time": pd.date_range("2025-06-02", periods=n, freq="B"),
                         "open": c * 0.998, "high": c * 1.006, "low": c * 0.993, "close": c})


def test_vnindex_rsi_regression(monkeypatch):
    df = _vni_df()
    monkeypatch.setattr(vb, "_load_vnindex_df", lambda *a, **k: df)
    tech = vb._vnindex_technicals()
    assert tech["rsi14"] == round(float(_brief_rsi_ref(df["close"]).iloc[-1]), 1)


def test_vnindex_technicals_calls_shared_rsi():
    import inspect
    src = inspect.getsource(vb._vnindex_technicals)
    assert "rsi_wilder" in src and "same formula as ticker indicators" not in src
    assert "ewm(com=13" not in src


# ── Ngưỡng RSI hai tầng ở canon ──────────────────────────────────────────────

def test_canon_thresholds():
    assert (canon.RSI_OVERSOLD, canon.RSI_WEAK, canon.RSI_STRONG, canon.RSI_OVERBOUGHT) == (30, 40, 60, 70)
    assert canon.RSI_OVERHEAT_SIDEWAYS == 72


@pytest.mark.parametrize("rsi, tag", [
    (70.0, "trung tính"), (70.1, "quá mua"), (30.0, "trung tính"),
    (29.9, "quá bán"), (55.3, "trung tính"), (85.0, "quá mua"),
])
def test_prompt_rsi_label_unchanged(rsi, tag):
    p = vb.build_prompt({"date": "2026-11-04", "time": "15:30", "vnindex_tech": {"close": 1300.0, "rsi14": rsi}},
                        "afternoon")
    assert f"- RSI(14): {rsi:.1f} ({tag})" in p


def _rsi_signal(rsi, close=1300.0, ma=1200.0):
    import vnstock_regime as vr
    tech = {"close": close, "ma20": ma, "ma50": ma, "ma200": ma, "rsi14": rsi}
    out = vr.classify_regime(tech, breadth={}, nn_net_1d=0)
    return out, next(s for s in out["signals"] if s["name"] == "RSI14")


@pytest.mark.parametrize("rsi, direction, detail", [
    (60.0, 0, "Trung tính"), (60.1, 1, "Momentum tích cực"),
    (40.0, 0, "Trung tính"), (39.9, -1, "Momentum yếu"),
])
def test_regime_rsi_vote_unchanged(rsi, direction, detail):
    _, sig = _rsi_signal(rsi)
    assert (sig["direction"], sig["detail"], sig["value"]) == (direction, detail, f"{rsi:.0f}")


def test_regime_overheat_override_unchanged():
    assert _rsi_signal(72.0)[0]["regime"] == "bull"
    assert _rsi_signal(72.1)[0]["regime"] == "sideways"


def test_regime_reads_canon(monkeypatch):
    import vnstock_regime as vr
    monkeypatch.setattr(vr, "RSI_STRONG", 50)
    assert _rsi_signal(55.0)[1]["direction"] == 1


# ── VNSTOCK_BRIEF_SECTOR_ALPHA ───────────────────────────────────────────────

_SECTORS = [
    {"Ngành": "Ngân hàng", "Giá 1T %": 2.0, "Giá 1M %": 12.0, "Giá 3M %": 1.0,
     "Vốn hoá (tỷ)": 900_000.0, "Vol Avg 20": 2.0, "NN 1M (tỷ)": 300.0},
    {"Ngành": "Bất động sản", "Giá 1T %": -1.0, "Giá 1M %": -4.0, "Giá 3M %": 6.0,
     "Vốn hoá (tỷ)": 700_000.0, "Vol Avg 20": 1.0, "NN 1M (tỷ)": -200.0},
    {"Ngành": "Thép", "Giá 1T %": 0.5, "Giá 1M %": 1.0, "Giá 3M %": 0.0,
     "Vốn hoá (tỷ)": 200_000.0, "Vol Avg 20": 1.5, "NN 1M (tỷ)": 10.0},
]


@pytest.fixture
def no_alpha_env(monkeypatch):
    for k in [k for k in __import__("os").environ if k.startswith("VNSTOCK_BRIEF_SECTOR_ALPHA")]:
        monkeypatch.delenv(k)
    return monkeypatch


def _record_compute_scores(monkeypatch):
    import vnstock_market_analyzer as ma
    calls, real = [], ma.compute_scores

    def _spy(*a, **k):
        calls.append((len(a), sorted(k)))
        return real(*a, **k)
    monkeypatch.setattr(ma, "compute_scores", _spy)
    return calls


def test_sector_alpha_off_keeps_old_call(no_alpha_env):
    calls = _record_compute_scores(no_alpha_env)
    no_alpha_env.setattr(vb, "_load_vnindex_df",
                         lambda *a, **k: pytest.fail("tắt công tắc mà vẫn đọc VN-Index"))
    ctx = {"sectors": list(_SECTORS), "breadth": {}}
    vb._fill_quant(ctx)
    assert calls == [(1, [])]
    assert "alpha_1M" not in ctx["quant_top"][0] and ctx["quant_rotation"] == []


def test_sector_alpha_on_feeds_index_returns_into_prompt(no_alpha_env):
    no_alpha_env.setenv("VNSTOCK_BRIEF_SECTOR_ALPHA", "1")
    calls = _record_compute_scores(no_alpha_env)
    # VN-Index phẳng 60 phiên đầu rồi +1%/20 phiên: 1M ≈ +1.0%, 3M ≈ +1.0%
    close = np.r_[np.full(200, 1000.0), np.full(40, 1000.0), np.full(20, 1010.0)]
    df = pd.DataFrame({"time": pd.date_range("2025-06-02", periods=len(close), freq="B"),
                       "close": close})
    seen = {}

    def _load(augment=True):
        seen["augment"] = augment
        return df
    no_alpha_env.setattr(vb, "_load_vnindex_df", _load)
    ctx = {"sectors": list(_SECTORS), "breadth": {}}
    vb._fill_quant(ctx)
    assert calls == [(1, ["index_returns"])] and seen["augment"] is False
    bank = next(r for r in ctx["quant_top"] + ctx["quant_avoid"] if r["Ngành"] == "Ngân hàng")
    assert bank["alpha_1M"] == pytest.approx(12.0 - 1.0)
    assert [r["Ngành"] for r in ctx["quant_rotation"]] == ["Ngân hàng"]

    p = vb.build_prompt({"date": "2026-11-04", "time": "15:30", **ctx}, "afternoon")
    assert "## Rotation signal" in p and "**Ngân hàng** rotation=+11.0pp" in p
    assert "(α +11.0pp vs VNI)" in p


def test_sector_alpha_on_but_index_missing_falls_back(no_alpha_env, caplog):
    no_alpha_env.setenv("VNSTOCK_BRIEF_SECTOR_ALPHA", "1")
    calls = _record_compute_scores(no_alpha_env)
    no_alpha_env.setattr(vb, "_load_vnindex_df", lambda *a, **k: pd.DataFrame())
    ctx = {"sectors": list(_SECTORS), "breadth": {}}
    vb._fill_quant(ctx)
    assert calls == [(1, [])]
    assert "sector_alpha" in ctx["loader_errors"] and "sector_alpha" in caplog.text
    assert ctx["quant_top"]


@pytest.mark.parametrize("val, on", [("0", False), ("", False), ("1", True),
                                     ("true", True), ("off", False)])
def test_sector_alpha_switch_parsing(no_alpha_env, val, on):
    no_alpha_env.setenv("VNSTOCK_BRIEF_SECTOR_ALPHA", val)
    assert vb._sector_alpha_enabled() is on


def test_sector_alpha_switch_listed_in_claude_md():
    assert "VNSTOCK_BRIEF_SECTOR_ALPHA" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


# ── scripts/compare_indicator_formulas.py ────────────────────────────────────

def _load_script():
    spec = importlib.util.spec_from_file_location(
        "compare_indicator_formulas", ROOT / "scripts" / "compare_indicator_formulas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cif():
    return _load_script()


def _runner_breadth_ref(df: pd.DataFrame, day: pd.Timestamp) -> dict:
    """Đúng cách tính của vnstock_runner.build_market_overview, cắt tại `day`."""
    w = df[(df["time"] <= day) & (df["time"] >= day - pd.Timedelta(days=400))]
    if len(w) < 5:
        return {"counted": False}
    c = w["close"].astype(float)
    out = {"counted": True, "above_ema": None, "rsi_c": _screener_rsi_ref(c).iloc[-1]}
    if len(c) >= 200:
        out["above_ema"] = bool(c.iloc[-1] > c.ewm(span=200, adjust=False).mean().iloc[-1])
        out["above_sma"] = bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1])
    return out


def _ticker_df(n: int, seed: int, start="2024-01-02") -> pd.DataFrame:
    return pd.DataFrame({"time": pd.date_range(start, periods=n, freq="B"),
                         "close": _walk(n, seed=seed, start=20.0).to_numpy()})


def test_ticker_day_flags_match_runner_window(cif):
    df = _ticker_df(520, seed=8)
    days = pd.DatetimeIndex(df["time"].iloc[-30:])
    flags = cif.ticker_day_flags(df["time"], df["close"], days)
    for d in days[::7]:
        ref = _runner_breadth_ref(df, d)
        row = flags.loc[d]
        assert bool(row["counted"]) is ref["counted"]
        assert bool(row["above_ema"]) is ref["above_ema"]
        assert bool(row["above_sma"]) is ref["above_sma"]
        assert row["rsi_c"] == pytest.approx(ref["rsi_c"], abs=1e-9)


def test_ticker_day_flags_window_seed_matters(cif):
    """EMA200 của runner gieo ở đầu cửa sổ 400 ngày — khác EMA từ đầu lịch sử."""
    df = _ticker_df(900, seed=13)
    d = df["time"].iloc[-1]
    w = df[df["time"] >= d - pd.Timedelta(days=400)]["close"]
    seeded = w.ewm(span=200, adjust=False).mean().iloc[-1]
    full = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
    assert abs(seeded - full) > 1e-6
    got = cif._seeded_ema(df["close"].to_numpy(), len(df) - len(w), len(df) - 1, 200)
    assert float(got) == pytest.approx(seeded, rel=1e-10)


def test_ticker_day_flags_short_or_missing(cif):
    df = _ticker_df(3, seed=1, start="2026-10-28")
    days = pd.DatetimeIndex([pd.Timestamp("2026-10-01"), df["time"].iloc[-1]])
    f = cif.ticker_day_flags(df["time"], df["close"], days)
    assert not f["counted"].any()


def _flags(rsi_c, rsi_w, ema_, sma_):
    return pd.DataFrame({"counted": True, "rsi_c": rsi_c, "rsi_w": rsi_w,
                         "above_ema": ema_, "above_sma": sma_})


def test_summarize_daily_counts_and_votes(cif):
    day = pd.Timestamp("2026-11-03")
    per_ticker = []
    # 10 mã: 6 trên EMA, 3 trên SMA ⇒ 60% (phiếu +1) vs 30% (phiếu −1)
    for i in range(10):
        f = _flags([25.0 if i < 2 else 50.0], [32.0 if i == 0 else (25.0 if i < 2 else 75.0 if i == 9 else 50.0)],
                   [i < 6], [i < 3])
        f.index = [day]
        per_ticker.append(f)
    daily = cif.summarize_daily(per_ticker)
    row = daily.loc[day]
    assert row["total"] == 10
    assert (row["rsi_ov_cutler"], row["rsi_ov_wilder"]) == (2, 1)
    assert (row["rsi_ob_cutler"], row["rsi_ob_wilder"]) == (0, 1)
    assert row["rsi_zone_changed"] == 2
    assert (row["pct_ema200"], row["pct_sma200"]) == (60.0, 30.0)
    assert (row["vote_ema200"], row["vote_sma200"]) == (1, -1)


def test_vote_flips(cif):
    daily = pd.DataFrame({"vote_ema200": [1, 1, 0, -1], "vote_sma200": [1, 0, 0, 1]})
    assert cif.vote_flips(daily) == {"khac_phieu": 2, "nguoc_chieu": 1, "so_phien": 4}


def test_breadth_vote_matches_regime(cif):
    import vnstock_regime as vr
    for pct in (55.0, 55.1, 35.0, 34.9, 45.0):
        sig = next(s for s in vr.classify_regime({}, breadth={"above_ma200_pct": pct},
                                                 nn_net_1d=0)["signals"]
                   if s["name"] == "Breadth MA200")
        assert cif.breadth_vote(pct) == sig["direction"]


def test_quantile_threshold_keeps_label_rate(cif):
    old = np.arange(100.0)                    # 30% < 30
    new = np.arange(100.0) * 0.5 + 10         # tỉ lệ 30% ⇔ ngưỡng 25
    thr = cif.quantile_threshold(old, new, 30.0, "below")
    assert thr == pytest.approx(25.0, abs=0.5)
    assert np.mean(new < thr) == pytest.approx(0.30, abs=0.01)
    thr_hi = cif.quantile_threshold(old, new, 70.0, "above")
    assert np.mean(new > thr_hi) == pytest.approx(np.mean(old > 70.0), abs=0.01)
    assert cif.quantile_threshold(old, new, -5.0, "below") is None


def test_affected_presets_found_from_registry(cif):
    assert set(cif.affected_presets()) == {"oversold", "overbought", "reversal",
                                           "golden_cross", "strong_uptrend"}


def test_screener_variant_and_preset_diff(cif):
    from vnstock_screener import _calc_indicators
    rng = np.random.default_rng(4)
    n = 300
    c = pd.Series(20 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n))))
    df = pd.DataFrame({"time": pd.date_range("2025-01-02", periods=n, freq="B"),
                       "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                       "volume": 1e5})
    old = _calc_indicators(df)
    new = cif.screener_variant(old, df)
    assert new["rsi_14"] == round(float(rsi_wilder(c).iloc[-1]), 1)
    assert new["above_ma200"] is bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1])
    assert old["rsi_14"] == round(float(_screener_rsi_ref(c).iloc[-1]), 1)
    assert "rsi_14" in old and old is not new

    rows_old = {"AAA": {"rsi_14": 28.0}, "BBB": {"rsi_14": 31.0}, "CCC": {"rsi_14": 50.0}}
    rows_new = {"AAA": {"rsi_14": 31.0}, "BBB": {"rsi_14": 29.0}, "CCC": {"rsi_14": 29.5}}
    d = cif.preset_diff(rows_old, rows_new, ["oversold"])["oversold"]
    assert (d["cu"], d["moi"], d["vao"], d["ra"]) == (1, 2, ["BBB", "CCC"], ["AAA"])


def test_main_writes_json_and_prints_vietnamese(cif, tmp_path, capsys, monkeypatch):
    """Lớp đọc kho mỏng: kho giả trong tmp_path, chỉ ĐỌC (không đẻ file trong kho)."""
    wh = tmp_path / "wh"
    days = pd.date_range("2024-01-02", periods=420, freq="B")
    for tk, seed in (("VNINDEX", 1), ("AAA", 2), ("BBB", 3), ("CCC", 4)):
        c = _walk(len(days), seed=seed, start=1000.0 if tk == "VNINDEX" else 20.0).to_numpy()
        for y in sorted(set(days.year)):
            m = days.year == y
            d = wh / "prices" / f"ticker={tk}" / f"year={y}"
            d.mkdir(parents=True)
            pd.DataFrame({"time": days[m], "open": c[m], "high": c[m] * 1.01,
                          "low": c[m] * 0.99, "close": c[m], "volume": 1e5}
                         ).to_parquet(d / "data.parquet", index=False)
    before = sorted(p.relative_to(wh) for p in wh.rglob("*"))
    out = tmp_path / "out.json"
    rc = cif.main(["--warehouse", str(wh), "--days", "20", "--json", str(out)])
    assert rc == 0
    assert sorted(p.relative_to(wh) for p in wh.rglob("*")) == before
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["daily"]) == 20 and data["daily"][-1]["total"] == 3
    assert set(data["nguong_goi_y"]) >= {"rsi_qua_ban_30", "rsi_qua_mua_70", "do_rong_55", "do_rong_35"}
    text = capsys.readouterr().out
    assert "RSI<30" in text and "SMA200" in text and "Phiếu độ rộng" in text
