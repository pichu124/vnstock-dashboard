"""PTKT P2b — các cách tìm S/R (`vnstock_sr_methods`) + script đo `scripts/eval_sr_methods.py`.
Dữ liệu tổng hợp, không cần kho."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import vnstock_brief as vb
import vnstock_sr_methods as srm
import vnstock_ta_score as ts
from tests.test_compare_indicator_quality import _ohlcv, _write_ticker

ROOT = Path(__file__).resolve().parent.parent


def _noisy(n: int, seed: int, base: float = 20.0) -> pd.DataFrame:
    """OHLCV ngẫu nhiên có râu và KL đổi — đủ swing/đỉnh KL cho mọi phương pháp."""
    rng = np.random.default_rng(seed)
    c = base * np.exp(np.cumsum(rng.normal(0.0, 0.015, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"time": pd.bdate_range("2024-01-02", periods=n), "open": o, "high": hi,
                         "low": lo, "close": c, "volume": rng.uniform(1e5, 1e6, n)})


def _triangle(n: int = 130) -> pd.DataFrame:
    """Đi qua lại 100 ↔ 110, chu kỳ 20 phiên, kết thúc ở 105 khi đang lên."""
    k = (np.arange(n) - (n - 1) + 5) % 20          # bar cuối: pha 5 ⇒ 105, đang lên
    c = np.where(k < 10, 100 + k, 120 - k).astype(float)
    return pd.DataFrame({"time": pd.bdate_range("2024-01-02", periods=n), "open": c,
                         "high": c + 0.2, "low": c - 0.2, "close": c, "volume": 1e5})


# ── Từng phương pháp, số cụ thể ──────────────────────────────────────────────

def test_pivot60_matches_ticker_sr_levels():
    df = _noisy(300, seed=3)
    hits = 0
    for t in range(80, 300, 7):
        w = df.iloc[:t + 1]
        c = float(w["close"].iloc[-1])
        lv = srm.pivot60(w, c)
        sup, res = vb.ticker_sr_levels(w["high"].tolist(), w["low"].tolist(), c)
        assert (lv["support"] or [None])[0] == sup and (lv["resistance"] or [None])[0] == res
        hits += sup is not None and res is not None
    assert hits > 10


def test_pivot60_with_extremes_matches_vnindex_technicals(monkeypatch):
    df = _noisy(300, seed=4, base=1250.0)
    df.attrs["intraday"] = True                     # bỏ phần mẫu nến, không liên quan
    monkeypatch.setattr(vb, "_load_vnindex_df", lambda *a, **k: df)
    tech = vb._vnindex_technicals()
    lv = srm.pivot60(df, float(df["close"].iloc[-1]), with_extremes=True)
    assert (lv["support"] + [None, None])[:2] == [tech["support_1"], tech["support_2"]]
    assert (lv["resistance"] + [None, None])[:2] == [tech["resistance_1"], tech["resistance_2"]]


def test_touch_cluster_finds_repeated_highs_and_lows():
    lv = srm.touch_cluster(_triangle(), 105.0)
    # đỉnh swing 110,2 và đáy 99,8 lặp lại mỗi 20 phiên trong 120 phiên
    assert lv == {"support": [99.8], "resistance": [110.2]}
    assert srm.touch_cluster(_triangle(), 105.0, min_touches=7) == {"support": [], "resistance": []}


def test_touch_cluster_ignores_single_touch_swing():
    df = _triangle()
    # một đáy swing duy nhất ở 102,5 (gần giá hơn 99,8) — 1 lần chạm ⇒ không thành mức
    i = len(df) - 31                                # pha 15 ⇒ 105, đang xuống
    df.loc[i, "low"] = 102.5
    assert srm.touch_cluster(df, 105.0)["support"] == [99.8]


def test_volume_node_peaks_at_heavy_volume_prices():
    n = 40
    seg = lambda p, v: pd.DataFrame({"open": p, "high": p + 0.5, "low": p - 0.5,  # noqa: E731
                                     "close": p, "volume": v}, index=range(n))
    ramp = np.linspace(100.0, 105.0, n)
    df = pd.concat([seg(np.full(n, 111.0), 1e6), seg(np.full(n, 99.0), 1e6),
                    seg(ramp, 1e5)], ignore_index=True)
    lv = srm.volume_node(df, 105.0)
    assert lv["support"][0] == pytest.approx(99.0, abs=0.6)
    assert lv["resistance"][0] == pytest.approx(111.0, abs=0.6)
    assert srm.volume_node(df.drop(columns="volume"), 105.0) == {"support": [], "resistance": []}


def test_volume_profile_spreads_volume_uniformly_over_bar_range():
    df = pd.DataFrame({"low": [10.0, 11.0], "high": [12.0, 11.0], "volume": [100.0, 50.0]})
    centers, prof = srm.volume_profile(df, 1.0)
    assert list(centers) == [10.5, 11.5, 12.5]
    assert list(prof) == [50.0, 100.0, 0.0]          # phiên đứng giá 11 dồn vào bin [11, 12)


def test_round_number_steps():
    assert srm.round_number(None, 23.37) == {"support": [23.0, 22.5], "resistance": [23.5, 24.0]}
    # VN-Index: bước 50; 1.250 cách giá 0,27% < 0,5% ⇒ bỏ; 1.150 / 1.350 > 7% ⇒ bỏ
    assert srm.round_number(None, 1253.4) == {"support": [1200.0], "resistance": [1300.0]}


def test_atr_band_uses_wilder_atr():
    n = 40
    df = pd.DataFrame({"open": 100.0, "high": np.full(n, 101.0), "low": np.full(n, 99.0),
                       "close": np.full(n, 100.0)})
    assert srm.atr_band(df, 100.0) == {"support": [97.0, 94.0], "resistance": [103.0, 106.0]}
    assert srm.atr_band(df.tail(5), 100.0) == {"support": [], "resistance": []}  # < 14 bar


@pytest.mark.parametrize("name", list(srm.METHODS))
def test_every_method_obeys_shared_filter(name):
    df = _noisy(400, seed=7)
    seen = 0
    for t in range(200, 400, 9):
        c = float(df["close"].iloc[t])
        lv = srm.levels_at(df, t, srm.METHODS[name])
        for side, sign in (("support", -1), ("resistance", 1)):
            xs = lv[side]
            assert len(xs) <= 2
            assert xs == sorted(xs, key=lambda v: abs(v - c))
            for v in xs:
                assert sign * (v - c) > 0
                assert vb._SR_MIN_DIST_PCT <= abs(v / c - 1) <= srm._SR_MAX_MOVE_PCT
            if len(xs) == 2:
                assert abs(xs[1] / xs[0] - 1) >= vb._SR_MIN_GAP_PCT
            seen += len(xs)
    assert seen > 0


@pytest.mark.parametrize("name", list(srm.METHODS))
def test_levels_at_never_looks_ahead(name):
    df = _noisy(400, seed=11)
    t = 300
    before = srm.levels_at(df, t, srm.METHODS[name])
    future = df.copy()
    future.loc[t + 1:, ["open", "high", "low", "close"]] *= 1.3
    future.loc[t + 1:, "volume"] *= 50
    assert srm.levels_at(future, t, srm.METHODS[name]) == before
    # còn bar ≤ t thì có ảnh hưởng: cùng đổi giá phiên t ⇒ mức đổi
    past = df.copy()
    past.loc[:t, ["open", "high", "low", "close"]] *= 1.3
    assert srm.levels_at(past, t, srm.METHODS[name]) != before


@pytest.mark.parametrize("name", list(srm.METHODS))
def test_precomputed_atr_matches_window_atr(name):
    """Script đo tính ATR một lần trên cả chuỗi rồi đưa `atr_t` — phải ra đúng mức như
    `levels_at` tự tính trên cửa sổ."""
    from vnstock_indicators import atr
    df = _noisy(500, seed=13)
    a = atr(df["high"], df["low"], df["close"], srm.ATR_N).to_numpy()
    for t in range(270, 500, 11):
        got = srm.METHODS[name](srm.window_at(df, t), float(df["close"].iloc[t]), atr_t=a[t])
        assert got == srm.levels_at(df, t, srm.METHODS[name])


# ── Script đo ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def esm():
    spec = importlib.util.spec_from_file_location("eval_sr_methods",
                                                  ROOT / "scripts" / "eval_sr_methods.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sample_positions(esm):
    assert list(esm.sample_positions(215, 5)) == [199, 204, 209]
    assert list(esm.sample_positions(204, 5)) == []           # 200 bar nhưng thiếu 5 phiên sau


def test_eval_series_scores_with_ta_score_rules(esm):
    """Một phương pháp cố định S1=95/S2=90 trên giá dựng tay: thủng S1 rồi chạm S2."""
    n = 220
    c = np.full(n, 100.0)
    c[206:] = [97.0, 94.0, 92.0, 89.0, 88.0, 88.0, 88.0, 88.0, 88.0, 88.0, 88.0, 88.0, 88.0, 88.0]
    df = pd.DataFrame({"time": pd.bdate_range("2024-01-02", periods=n), "open": c,
                       "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 1e5})
    fixed = {"fixed": lambda b, close, **kw: {"support": [95.0, 90.0], "resistance": []}}
    acc = esm.new_acc(fixed)
    done = esm.eval_series(df, [204], fixed, acc, mid=pd.Timestamp("2030-01-01"))
    assert done == 1
    s = esm.summarize(acc)
    row = s["all"]["fixed"]
    assert row["mau"] == 1 and row["support"]["phu"] == 1.0
    assert row["support"]["that"]["pierced"] == 1            # đóng cửa 89 < 95×0,995
    assert row["trigger_support"]["that"] == ts.rate(1, 1)   # thủng 95 ở 94 ⇒ chạm 90
    assert row["trigger_support"]["gia"]["n"] == ts.FAKE_PER_LEVEL
    assert row["trigger_support"]["gia_cung_pct"]["n"] == ts.FAKE_PER_LEVEL
    assert row["resistance"]["phu"] == 0.0
    assert s["first_half"]["fixed"]["mau"] == 1 and s["second_half"]["fixed"]["mau"] == 0


def test_main_on_fake_warehouse(esm, tmp_path, capsys):
    pytest.importorskip("pyarrow")
    wh = tmp_path / "wh"
    start = (pd.Timestamp.today().normalize() - pd.offsets.BDay(320)).date().isoformat()
    _write_ticker(wh, "VNINDEX", _ohlcv(320, seed=1, start=start, base=1200.0))
    for i, tk in enumerate(("FPT", "AAA", "BBB")):
        _write_ticker(wh, tk, _noisy(320, seed=20 + i).assign(
            time=pd.bdate_range(start, periods=320)))
    thin = _noisy(320, seed=30).assign(time=pd.bdate_range(start, periods=320), volume=10.0)
    _write_ticker(wh, "CCC", thin)                            # GTGD ≈ 0 ⇒ ngoài tập mã
    before = sorted(p.relative_to(wh) for p in wh.rglob("*"))
    out = tmp_path / "out.json"
    rc = esm.main(["--warehouse", str(wh), "--json", str(out), "--fake-k", "5"])
    assert rc == 0
    assert sorted(p.relative_to(wh) for p in wh.rglob("*")) == before
    data = json.loads(out.read_text(encoding="utf-8"))
    n_days = len(esm.sample_positions(320, esm.DEFAULT_STEP))
    assert data["ma"]["meta"] == {"so_ma": 3, "mau": 3 * n_days, "cat_nua": data["cat_nua"]}
    assert data["vnindex"]["meta"]["mau"] == n_days
    for grp in ("ma", "vnindex"):
        res = data[grp]["ket_qua"]
        assert set(res) == {"all", "first_half", "second_half"}
        assert set(res["all"]) == set(srm.METHODS)
        for m, r in res["all"].items():
            assert r["mau"] == data[grp]["meta"]["mau"]
            assert (r["mau"] == res["first_half"][m]["mau"] + res["second_half"][m]["mau"])
    rn = data["ma"]["ket_qua"]["all"]["round_number"]["support"]
    assert rn["phu"] == 1.0 and rn["that"]["n"] == 3 * n_days
    assert rn["gia"]["n"] == 5 * rn["that"]["n"]
    text = capsys.readouterr().out
    assert "CHỒNG CỬA SỔ" in text and "CÙNG mã" not in text and "Thủng S1 ⇒ chạm S2" in text and "touch_cluster" in text


# ── Mốc khớp biến động (vết review 04/11) ────────────────────────────────────

def test_vol_matched_equals_same_pct_when_atr_constant(esm):
    """ATR% hằng 2% ⇒ 1,5 bội ATR = 3% ở mọi ngày: cùng seed phải bốc đúng ngày và ra đúng
    kết cục như mốc P0 cùng %."""
    df = _noisy(300, seed=5)
    ap = np.full(len(df), 2.0)
    for side in ("support", "resistance"):
        got = esm.vol_matched_level_outcomes(df, 1.5, side, ap, seed=77, exclude=[250])
        assert got == ts.fake_level_outcomes(df, 3.0, side, seed=77, exclude=[250])
        assert len(got) == ts.FAKE_PER_LEVEL
        for mult in (1.5, -0.5):                      # âm = phiên trigger đã qua mức 2
            got = esm.vol_matched_trigger_outcomes(df, mult, side, ap, seed=78,
                                                   exclude={10, 250})
            assert got == ts.fake_trigger_outcomes(df, 2.0 * mult, side, seed=78,
                                                   exclude={10, 250})


def _flat_dips(n: int = 12) -> pd.DataFrame:
    """Đóng cửa 100 mỗi phiên, râu 97–103 ⇒ mức trong ±3% luôn chạm, không bao giờ xuyên."""
    return pd.DataFrame({"time": pd.bdate_range("2024-01-02", periods=n), "open": 100.0,
                         "high": 103.0, "low": 97.0, "close": 100.0, "volume": 1e5})


def test_vol_matched_distance_scales_with_atr_of_fake_day(esm):
    df = _flat_dips()                                 # 12 bar, horizon 5 ⇒ ngày 0..6 bốc được
    ap = np.array([np.nan, 1.0, 1.0, 1.0, 4.0, 4.0, 4.0] + [4.0] * 5)
    # 1,5 bội: ATR% 1 ⇒ mức 98,5 / 101,5 (chạm, giữ); ATR% 4 ⇒ 94 / 106 (không chạm); ngày 0
    # chưa có ATR ⇒ không bốc
    want = [ts.HELD] * 3 + [ts.UNTOUCHED] * 3
    for side in ("support", "resistance"):
        assert esm.vol_matched_level_outcomes(df, 1.5, side, ap, k=50) == want
        assert esm.vol_matched_trigger_outcomes(df, 1.5, side, ap, k=50) == [True] * 3 + [False] * 3
        # mốc cùng % 1,5% chạm ở MỌI ngày — chính chỗ bias
        assert ts.fake_level_outcomes(df, 1.5, side, k=50) == [ts.HELD] * 7
    assert esm.vol_matched_level_outcomes(df, 1.5, "support", ap, k=50, exclude=[1, 4]) == \
        [ts.HELD] * 2 + [ts.UNTOUCHED] * 2
    assert esm.vol_matched_level_outcomes(df, 0.0, "support", ap) == []
    assert esm.vol_matched_trigger_outcomes(df, float("nan"), "support", ap) == []


def test_summarize_controls_against_atr_band(esm, capsys):
    acc = esm.new_acc(["x", "atr_band"])
    cell = acc["all"]
    for m, real, vol, same in (("atr_band", (6, 4), (5, 5), (3, 7)),
                               ("x", (8, 2), (5, 5), (2, 8))):
        c = cell[m]
        c["n"] = 10
        c["support"]["has"] = 10
        c["support"]["real"].update({ts.HELD: real[0], ts.PIERCED: real[1]})
        c["support"]["fake_vol"].update({ts.HELD: vol[0], ts.PIERCED: vol[1]})
        c["support"]["fake"].update({ts.HELD: same[0], ts.PIERCED: same[1]})
    s = esm.summarize(acc)["all"]
    assert s["atr_band"]["support"]["chenh_dpct"] == 10.0
    assert s["atr_band"]["support"]["chenh_cung_pct"] == 30.0
    assert s["atr_band"]["support"]["tru_atr_band"] == 0.0
    assert s["x"]["support"]["chenh_dpct"] == 30.0
    assert s["x"]["support"]["chenh_cung_pct"] == 60.0
    assert s["x"]["support"]["tru_atr_band"] == 20.0
    assert s["x"]["resistance"]["tru_atr_band"] is None      # chưa đo được ≠ 0
    assert esm.summarize(esm.new_acc(["x"]))["all"]["x"]["support"]["tru_atr_band"] is None
    text = esm.report("thử", esm.summarize(acc), {"mau": 10, "cat_nua": "2024-06-01"})
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("x "))
    assert "+30.0 ·  +20.0 ‖" in line and line.rstrip().endswith("+60.0 · 100%")
    assert "giả khớp ATR" in text and "giả cùng %" in text


def _vol_regime_walk(rng, n: int) -> pd.DataFrame:
    """Random walk KHÔNG drift (không có S/R thật), vol đổi chế độ 0,8% ↔ 3%/phiên mỗi 60 bar."""
    reg = np.repeat(rng.choice([0.008, 0.03], size=n // 60 + 1), 60)[:n]
    c = 50 * np.exp(np.cumsum(rng.standard_normal(n) * reg))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.standard_normal(n)) * reg * 0.5)
    lo = np.minimum(o, c) * (1 - np.abs(rng.standard_normal(n)) * reg * 0.5)
    return pd.DataFrame({"time": pd.bdate_range("2020-01-01", periods=n), "open": o, "high": hi,
                         "low": lo, "close": c, "volume": rng.uniform(1e5, 1e6, n)})


def test_vol_matched_baseline_removes_atr_bias_on_random_walk(esm):
    """Vết review 04/11: mốc cùng % đặt mức giả sang ngày biến động KHÁC ⇒ trên random walk vol
    cụm, atr_band (khoảng cách = 1,5·ATR(t)) "chạm thì giữ" CHÊNH ≈ +7–11 điểm %, trigger
    ≈ −10–17 dù không có S/R nào. Mốc khớp biến động phải kéo MỌI phương pháp về ≈ 0.

    Gộp S+R (null đối xứng, gấp đôi mẫu). Ngưỡng theo nhiễu: 12 chuỗi × 1.200 bar bước 5 ⇒
    "chạm thì giữ" n ≈ 1.000–3.400/phương pháp (SE ≈ 0,9–1,5 điểm); round_number còn lệch âm
    ~−1,5–2,7 có hệ thống (khoảng cách theo %, nhiễu ATR làm mốc khớp lệch ngược) ⇒ ngưỡng 3.
    Trigger atr_band/volume_node chỉ ~260–400 sự kiện (SE ≈ 3) ⇒ ngưỡng 6."""
    rng = np.random.default_rng(1)
    acc = esm.new_acc(srm.METHODS)
    for s in range(12):
        df = _vol_regime_walk(rng, 1200)
        esm.eval_series(df, esm.sample_positions(len(df), 5), srm.METHODS, acc,
                        df["time"].iloc[600], seed=s, fake_k=5)

    def hold(c, key):
        x = ts.level_summary((c["support"][key] + c["resistance"][key]).elements())
        return x["hold_if_touched"]["rate"] * 100

    def trig(c, k, n):
        return 100 * (sum(c[f"trigger_{s}"][k] for s in esm.SIDES)
                      / sum(c[f"trigger_{s}"][n] for s in esm.SIDES))

    vol, same = {}, {}
    for m, c in acc["all"].items():
        real_h, real_t = hold(c, "real"), trig(c, "k", "n")
        vol[m] = (real_h - hold(c, "fake_vol"), real_t - trig(c, "vk", "vn"))
        same[m] = (real_h - hold(c, "fake"), real_t - trig(c, "fk", "fn"))
    for m, (h, t) in vol.items():
        assert abs(h) <= 3.0, (m, "chạm thì giữ", round(h, 1))
        assert abs(t) <= 6.0, (m, "trigger", round(t, 1))
    # mốc cũ trên CÙNG dữ liệu: bias lớn — bỏ mốc mới thì các dòng trên đỏ
    assert same["atr_band"][0] > 6.0 and same["atr_band"][1] < -8.0, same["atr_band"]


def test_caveats_explain_vol_matched_baseline(esm):
    text = "\n".join(esm.caveats(10))
    assert "KHỚP BIẾN ĐỘNG" in text and "số bội ATR" in text and "−atr_band" in text


def test_caveats_flag_same_ticker_overlap_only_below_trigger_span(esm):
    assert "CÙNG mã" in esm.caveats(5)[0]
    assert "CÙNG mã" not in esm.caveats(10)[0]


def test_main_without_vnindex_fails_cleanly(esm, tmp_path, capsys):
    (tmp_path / "prices").mkdir()
    assert esm.main(["--warehouse", str(tmp_path)]) == 2
    assert "VNINDEX" in capsys.readouterr().out
