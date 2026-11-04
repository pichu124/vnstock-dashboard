"""PTKT P2a — thẻ kỹ thuật 3 khung (`vnstock_ta_card`). Dữ liệu tổng hợp, không cần kho."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import vnstock_horizons as hz
import vnstock_ta_card as tc


def _bars(closes, start="2025-01-06", volume=None, spread=0.01):
    c = np.asarray(closes, dtype=float)
    t = pd.bdate_range(start, periods=len(c))
    df = pd.DataFrame({"time": t, "open": c, "high": c * (1 + spread), "low": c * (1 - spread),
                       "close": c})
    if volume is not None:
        df["volume"] = np.asarray(volume, dtype=float)
    return df


def _trend(n, daily_pct, start=100.0, wiggle=0.004):
    """Xu hướng đều + răng cưa ±wiggle (để RSI/ATR có cả phiên tăng lẫn giảm)."""
    steps = np.full(n, daily_pct / 100) + np.where(np.arange(n) % 2, -wiggle, wiggle)
    return start * np.exp(np.cumsum(steps))


# ── Nhãn ở biên ──────────────────────────────────────────────────────────

# So CHẶT như canon (prompt >70/<30, regime >60/<40): đúng mốc 70/60 thuộc nấc dưới,
# đúng mốc 40/30 thuộc nấc trên — thẻ, prompt, regime cùng nhãn ở mốc.
@pytest.mark.parametrize("rsi, want", [
    (70.01, tc.RSI_MOMENTUM), (85.0, tc.RSI_MOMENTUM), (70.0, tc.RSI_STRONG_LBL),
    (60.01, tc.RSI_STRONG_LBL), (60.0, tc.RSI_NEUTRAL), (40.0, tc.RSI_NEUTRAL),
    (39.99, tc.RSI_WEAK_LBL), (30.0, tc.RSI_WEAK_LBL), (29.99, tc.RSI_OVERSOLD_LBL),
    (None, None), (float("nan"), None),
])
def test_rsi_label_boundaries(rsi, want):
    assert tc.rsi_label(rsi) == want


def test_rsi_vocabulary_is_momentum_not_warning():
    assert tc.rsi_label(75) == "đà mạnh"
    assert {tc.RSI_MOMENTUM, tc.RSI_STRONG_LBL, tc.RSI_NEUTRAL, tc.RSI_WEAK_LBL,
            tc.RSI_OVERSOLD_LBL} == {"đà mạnh", "mạnh", "trung tính", "yếu", "quá bán"}


@pytest.mark.parametrize("close, ma, slope, want", [
    (101, 100, 0.31, tc.DIR_UP),
    (101, 100, 0.30, tc.DIR_FLAT),          # đúng bằng ngưỡng phẳng ⇒ chưa dốc
    (100, 100, 2.0, tc.DIR_FLAT),           # giá ngang MA
    (99, 100, 2.0, tc.DIR_FLAT),            # dưới MA mà MA dốc lên
    (99, 100, -0.31, tc.DIR_DOWN),
    (99, 100, -0.30, tc.DIR_FLAT),
    (101, 100, -1.0, tc.DIR_FLAT),
    (None, 100, 1.0, None), (101, None, 1.0, None), (101, 100, None, None),
])
def test_direction_boundaries(close, ma, slope, want):
    assert tc.direction(close, ma, slope, 0.3) == want


def test_direction_labels_are_price_vocabulary_shared_with_horizons():
    assert (tc.DIR_UP, tc.DIR_FLAT, tc.DIR_DOWN) == ("TĂNG", "ĐI NGANG", "GIẢM")
    assert tc.DIR_UP == hz.MEDIUM_LABEL[hz.TANG]


# ── Thẻ trên chuỗi tổng hợp ─────────────────────────────────────────────

def test_steady_uptrend_all_three_frames_up_with_exact_facts():
    df = _bars(_trend(320, 0.3), volume=np.full(320, 1000.0))
    card = tc.ta_card(df, label="AAA")
    c = df["close"]
    assert card["close"] == pytest.approx(c.iloc[-1])
    assert card["as_of"] == df["time"].iloc[-1].date().isoformat()
    assert card["n_bars"] == 320
    sh, md, lg = card["short"], card["medium"], card["long"]
    assert (sh["label"], md["label"], lg["label"]) == (tc.DIR_UP, tc.DIR_UP, tc.DIR_UP)
    ma20 = c.iloc[-20:].mean()
    assert sh["ma20"] == pytest.approx(ma20)
    assert sh["ma20_dist_pct"] == pytest.approx((c.iloc[-1] / ma20 - 1) * 100)
    assert sh["ma20_slope_pct"] == pytest.approx((ma20 / c.iloc[-25:-5].mean() - 1) * 100)
    sma200 = c.iloc[-200:].mean()
    assert lg["sma200"] == pytest.approx(sma200)
    assert lg["sma200_slope_pct"] == pytest.approx((sma200 / c.iloc[-220:-20].mean() - 1) * 100)
    assert sh["rsi_label"] == tc.RSI_MOMENTUM
    assert sh["vol_ratio"] == pytest.approx(1.0) and sh["vol_confirmed"] is False
    assert card["conflicts"] == []


def test_steady_downtrend_all_three_frames_down_rsi_oversold():
    card = tc.ta_card(_bars(_trend(320, -0.3)))
    assert (card["short"]["label"], card["medium"]["label"], card["long"]["label"]) == \
        (tc.DIR_DOWN, tc.DIR_DOWN, tc.DIR_DOWN)
    assert card["short"]["rsi_label"] == tc.RSI_OVERSOLD_LBL


def test_medium_is_exactly_horizons_weekly_state_of_last_closed_week():
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(0.001 + 0.015 * rng.standard_normal(400)))
    df = _bars(closes)
    df = df[df["time"].dt.day_of_week <= 2].reset_index(drop=True)   # bar cuối = thứ Tư (tuần mở)
    card = tc.ta_card(df)
    dates = [t.date() for t in df["time"]]
    weeks = hz.medium_series(dates, df["close"].tolist())
    assert card["medium"]["label"] == hz.MEDIUM_LABEL[weeks[-1].state]
    assert card["medium"]["label"] == hz.MEDIUM_LABEL[hz.medium_daily(dates, weeks)[-1]]
    assert card["medium"]["week_end"] == weeks[-1].week_end.isoformat()
    assert card["medium"]["week_end"] < card["as_of"]              # tuần đang mở bị bỏ
    assert card["medium"]["ma40w"] == pytest.approx(weeks[-1].ma_long)


def test_position_in_52_week_range():
    closes = np.r_[np.linspace(50, 150, 150), np.linspace(150, 100, 100)]
    df = _bars(closes, spread=0.0)
    card = tc.ta_card(df)
    assert card["long"]["pos_52w_pct"] == pytest.approx(50.0)
    assert tc.ta_card(df.iloc[1:])["long"]["pos_52w_pct"] is None   # 249 bar: chưa đủ


def test_atr_pct_and_level_distances_in_atr_multiples():
    df = _bars(_trend(60, 0.1))
    card = tc.ta_card(df, sr={"support_1": 95.0, "support_2": 90.0, "resistance_1": 120.0})
    from vnstock_indicators import atr
    a = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
    close = card["close"]
    assert card["volatility"]["atr_pct"] == pytest.approx(a / close * 100)
    assert card["levels"]["s1_atr"] == pytest.approx((close - 95.0) / a)
    assert card["levels"]["r1_atr"] == pytest.approx((120.0 - close) / a)
    assert card["broke_support"] is False
    lines = tc.card_lines(card)
    assert any(ln.startswith("- Mức giá: S1 95.00 (") and "R1 120.00" in ln for ln in lines)
    assert not any(tc.BROKE_SUPPORT_TEXT in ln for ln in lines)


def test_close_below_s1_flags_broke_support_with_s2_target():
    df = _bars(np.full(40, 100.0))
    card = tc.ta_card(df, sr={"support_1": 100.5, "support_2": 97.0, "resistance_1": 104.0})
    assert card["broke_support"] is True
    line = next(ln for ln in tc.card_lines(card) if tc.BROKE_SUPPORT_TEXT in ln)
    assert line == f"- ⚠️ đóng cửa dưới S1 100.50: {tc.BROKE_SUPPORT_TEXT} 97.00"
    assert f"{tc.BROKE_SUPPORT_TEXT} 97.00" in tc.card_line(card)


def test_close_exactly_at_s1_is_not_broken_and_missing_s2_is_said():
    df = _bars(np.full(40, 100.0))
    assert tc.ta_card(df, sr={"support_1": 100.0})["broke_support"] is False
    card = tc.ta_card(df, sr={"support_1": 101.0})
    assert card["broke_support"] is True
    assert "(chưa có mức S2)" in tc.card_line(card)


def test_no_sr_means_no_level_line_and_bad_values_ignored():
    df = _bars(_trend(60, 0.1))
    for sr in (None, {}, {"support_1": None, "resistance_1": "x"}, {"support_1": -5}):
        card = tc.ta_card(df, sr=sr)
        assert card["levels"] is None and card["broke_support"] is False
        assert not any(ln.startswith("- Mức giá") for ln in tc.card_lines(card))


# ── Khối lượng ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("last_vol, confirmed", [(120.0, True), (119.9, False), (300.0, True)])
def test_volume_ratio_vs_prior_20_sessions_at_threshold(last_vol, confirmed):
    vol = np.r_[np.full(30, 999.0), [5000.0], np.full(20, 100.0), [last_vol]]
    card = tc.ta_card(_bars(np.full(len(vol), 100.0), volume=vol))
    assert card["short"]["vol_ratio"] == pytest.approx(last_vol / 100.0)   # bar 21 trước bị loại
    assert card["short"]["vol_confirmed"] is confirmed
    assert ("KL " + f"{last_vol / 100:,.2f}" + "× TB20 " + (tc.VOL_YES if confirmed else tc.VOL_NO)
            ) in tc.card_line(card)


def test_volume_unmeasurable_without_column_or_with_zero_volume():
    closes = _trend(40, 0.1)
    for df in (_bars(closes), _bars(closes, volume=np.zeros(40))):
        card = tc.ta_card(df)
        assert card["short"]["vol_ratio"] is None and card["short"]["vol_confirmed"] is None
        assert f"KL {tc.NO_DATA}" in tc.card_line(card)


def test_vol_threshold_is_ta_score_t2_constant():
    import vnstock_ta_score as ts
    assert tc.VOL_MULT is ts.VOL_MULT


# ── MACD ─────────────────────────────────────────────────────────────────

def _oracle_hist(closes):
    c = pd.Series(closes, dtype=float)
    line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    return (line - line.ewm(span=9, adjust=False).mean()).to_numpy()


def test_macd_recent_cross_matches_screener_formula_on_every_prefix():
    closes = np.r_[np.linspace(120, 100, 60), np.linspace(100, 112, 30), np.linspace(112, 104, 30)]
    seen = set()
    for k in range(40, len(closes) + 1):
        card = tc.ta_card(_bars(closes[:k]))
        h = _oracle_hist(closes[:k])
        want = (None, None)
        for ago in range(3):
            i = k - 1 - ago
            if h[i] > 0 >= h[i - 1]:
                want = (tc.CROSS_UP, ago)
                break
            if h[i] < 0 <= h[i - 1]:
                want = (tc.CROSS_DOWN, ago)
                break
        got = (card["short"]["macd_cross"], card["short"]["macd_cross_ago"])
        assert got == want, k
        assert card["short"]["macd_above"] is bool(h[-1] > 0)
        seen.add(want)
    assert {(tc.CROSS_UP, 0), (tc.CROSS_UP, 2), (tc.CROSS_DOWN, 0), (None, None)} <= seen


def test_macd_needs_enough_bars():
    card = tc.ta_card(_bars(_trend(30, 0.2)))
    assert card["short"]["macd_above"] is None
    assert f"MACD {tc.NO_DATA}" in "\n".join(tc.card_lines(card))


# ── Tín hiệu lệch nhau ──────────────────────────────────────────────────

def _card(close=100.0, short=None, medium=None, long=None):
    return {"close": close, "short": short or {}, "medium": medium or {}, "long": long or {}}


@pytest.mark.parametrize("card, want", [
    (_card(short={"crossed_ma20_up": True, "vol_confirmed": False}), tc.CONFLICT_BREAKOUT_NO_VOL),
    (_card(short={"label": tc.DIR_UP}, medium={"label": tc.DIR_DOWN}),
     tc.CONFLICT_SHORT_UP_MEDIUM_DOWN),
    (_card(short={"label": tc.DIR_DOWN}, medium={"label": tc.DIR_UP}),
     tc.CONFLICT_SHORT_DOWN_MEDIUM_UP),
    (_card(close=90, short={"rsi_label": tc.RSI_MOMENTUM}, long={"sma200": 100}),
     tc.CONFLICT_RSI_STRONG_BELOW_SMA200),
    (_card(close=99, short={"macd_cross": tc.CROSS_UP, "ma20": 100}),
     tc.CONFLICT_MACD_UP_BELOW_MA20),
    (_card(close=101, short={"macd_cross": tc.CROSS_DOWN, "ma20": 100}),
     tc.CONFLICT_MACD_DOWN_ABOVE_MA20),
])
def test_each_conflict_rule_fires(card, want):
    assert tc.find_conflicts(card) == [want]


@pytest.mark.parametrize("card", [
    _card(short={"crossed_ma20_up": True, "vol_confirmed": True}),
    _card(short={"crossed_ma20_up": True, "vol_confirmed": None}),       # KL không đo được
    _card(short={"crossed_ma20_up": False, "vol_confirmed": False}),
    _card(short={"label": tc.DIR_UP}, medium={"label": tc.DIR_FLAT}),
    _card(short={"label": tc.DIR_UP}, medium={"label": None}),
    _card(close=100, short={"rsi_label": tc.RSI_MOMENTUM}, long={"sma200": 100}),
    _card(close=90, short={"rsi_label": tc.RSI_MOMENTUM}, long={"sma200": None}),
    _card(close=101, short={"macd_cross": tc.CROSS_UP, "ma20": 100}),
    _card(close=99, short={"macd_cross": tc.CROSS_DOWN, "ma20": 100}),
    _card(close=None, short={"macd_cross": tc.CROSS_UP, "ma20": 100}),
    {},
])
def test_conflict_rules_stay_silent(card):
    assert tc.find_conflicts(card) == []


def test_conflicts_keep_fixed_order():
    card = _card(close=90, short={"crossed_ma20_up": True, "vol_confirmed": False,
                                  "label": tc.DIR_UP, "rsi_label": tc.RSI_MOMENTUM,
                                  "macd_cross": tc.CROSS_UP, "ma20": 95},
                 medium={"label": tc.DIR_DOWN}, long={"sma200": 100})
    assert tc.find_conflicts(card) == [
        tc.CONFLICT_BREAKOUT_NO_VOL, tc.CONFLICT_SHORT_UP_MEDIUM_DOWN,
        tc.CONFLICT_RSI_STRONG_BELOW_SMA200, tc.CONFLICT_MACD_UP_BELOW_MA20]


def test_breakout_above_ma20_on_thin_volume_shows_in_card():
    closes = np.r_[np.full(40, 100.0) + np.where(np.arange(40) % 2, -0.2, 0.2), [103.0]]
    vol = np.r_[np.full(40, 1000.0), [500.0]]
    card = tc.ta_card(_bars(closes, volume=vol))
    assert card["short"]["crossed_ma20_up"] is True
    assert tc.CONFLICT_BREAKOUT_NO_VOL in card["conflicts"]
    assert any(ln == f"- Tín hiệu lệch nhau: {'; '.join(card['conflicts'])}"
               for ln in tc.card_lines(card))
    assert f"lệch: {tc.CONFLICT_BREAKOUT_NO_VOL}" in tc.card_line(card)
    card_ok = tc.ta_card(_bars(closes, volume=np.r_[np.full(40, 1000.0), [1500.0]]))
    assert tc.CONFLICT_BREAKOUT_NO_VOL not in card_ok["conflicts"]


# ── Thiếu dữ liệu ───────────────────────────────────────────────────────

@pytest.mark.parametrize("daily", [None, pd.DataFrame(), pd.DataFrame({"x": [1, 2]}),
                                   pd.DataFrame({"close": [np.nan, 0.0]})])
def test_no_usable_bars_never_raises(daily):
    card = tc.ta_card(daily, label="ZZZ")
    assert card["close"] is None and card["n_bars"] == 0 and card["conflicts"] == []
    assert tc.card_line(card) == f"ZZZ: {tc.NO_DATA}"
    assert tc.card_lines(card) == [f"📈 Kỹ thuật ZZZ: {tc.NO_DATA}"]


def test_few_bars_fill_none_and_say_not_enough_data():
    card = tc.ta_card(_bars([100, 101, 102, 101, 103]), label="NEW")
    sh, lg = card["short"], card["long"]
    assert all(sh[k] is None for k in ("ma20", "rsi", "rsi_label", "label", "macd_above",
                                       "vol_ratio"))
    assert lg["sma200"] is None and lg["label"] is None and card["medium"]["label"] is None
    assert card["volatility"]["atr_pct"] is None
    line = tc.card_line(card)
    assert line.startswith("NEW 103.00: ngắn chưa đủ dữ liệu · tuần chưa đủ dữ liệu · "
                           "dài chưa đủ dữ liệu")


def test_short_history_between_frames():
    """60 bar: ngắn hạn có, dài hạn chưa — không trộn số."""
    card = tc.ta_card(_bars(_trend(60, 0.3)))
    assert card["short"]["label"] == tc.DIR_UP
    assert card["long"]["label"] is None and card["long"]["sma200_dist_pct"] is None
    assert f"SMA200 {tc.NO_DATA}" in "\n".join(tc.card_lines(card))


def test_without_time_column_medium_says_no_dates():
    card = tc.ta_card(_bars(_trend(320, 0.3)).drop(columns=["time"]))
    assert card["medium"]["label"] is None and card["medium"]["reason"] == tc.NO_DATES
    assert card["as_of"] is None
    assert card["short"]["label"] == tc.DIR_UP and card["long"]["label"] == tc.DIR_UP


# ── Không nhìn trước ────────────────────────────────────────────────────

def test_card_reads_only_last_bar_of_given_daily_no_lookahead():
    base = _trend(300, 0.2)
    crash = np.r_[base, base[-1] * np.linspace(0.98, 0.70, 20)]
    boom = np.r_[base, base[-1] * np.linspace(1.02, 1.40, 20)]
    vol = np.full(320, 1000.0)
    a = tc.ta_card(_bars(crash, volume=vol).iloc[:300], sr={"support_1": 50.0})
    b = tc.ta_card(_bars(boom, volume=vol).iloc[:300], sr={"support_1": 50.0})
    assert a == b
    assert a["as_of"] == _bars(crash).iloc[299]["time"].date().isoformat()
    full = tc.ta_card(_bars(crash, volume=vol))
    assert full["as_of"] > a["as_of"] and full["close"] != a["close"]


def test_unsorted_duplicate_dates_are_sorted_and_last_copy_wins():
    df = _bars(_trend(60, 0.1))
    dup = df.iloc[[-1]].assign(close=999.0, high=999.0, low=999.0, open=999.0)
    shuffled = pd.concat([df.iloc[::-1], dup], ignore_index=True)
    card = tc.ta_card(shuffled)
    assert card["close"] == 999.0 and card["n_bars"] == 60


# ── In ra ────────────────────────────────────────────────────────────────

def test_numbers_use_en_format():
    df = _bars(_trend(320, 0.2, start=1200.0))
    card = tc.ta_card(df, sr={"support_1": 1234.5}, label="VN-Index")
    text = "\n".join(tc.card_lines(card))
    assert f"đóng cửa {card['close']:,.2f}" in text and "," in f"{card['close']:,.2f}"
    assert "S1 1,234.50" in text


def test_index_lines_long_frame_is_context_without_label():
    card = tc.ta_card(_bars(_trend(320, 0.3)), label="VN-Index")
    lines = tc.card_lines(card)
    long_line = next(ln for ln in lines if ln.startswith("- Dài hạn"))
    assert long_line.startswith("- Dài hạn (bối cảnh): trên SMA200 +")
    assert not any(w in long_line for w in (tc.DIR_UP, tc.DIR_FLAT, tc.DIR_DOWN))
    # "Xu hướng MA20" (không "Ngắn hạn" — brief VN-Index đã có "Ngắn hạn" của 3 khung, bản mẫu 04/11)
    assert lines[1].startswith(f"- Xu hướng MA20: {tc.DIR_UP} — trên MA20 +")
    assert lines[2].startswith(f"- Trung hạn: {tc.DIR_UP} — đóng tuần ")


def test_ticker_line_carries_three_labels_and_no_warning_words():
    card = tc.ta_card(_bars(_trend(320, 0.3)), label="FPT")
    line = tc.card_line(card)
    assert line.startswith(f"FPT {card['close']:,.2f}: ngắn {tc.DIR_UP} · tuần {tc.DIR_UP} · "
                           f"dài {tc.DIR_UP} (SMA200 +")
    assert f"RSI {card['short']['rsi']:.1f} đà mạnh" in line          # RSI 1 chữ số thập phân
    assert "quá mua" not in line and "cảnh báo" not in line
    assert "\n" not in line


# ── Bản mẫu trên kho tổng hợp ───────────────────────────────────────────

def _write_ticker(prices, tk, df):
    for y, part in df.groupby(df["time"].dt.year):
        d = prices / f"ticker={tk}" / f"year={y}"
        d.mkdir(parents=True)
        part.to_parquet(d / "data.parquet", index=False)


def test_sample_script_reads_warehouse_and_cuts_at_date(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sample_ta_card", tc.__file__.replace("vnstock_ta_card.py", "scripts/sample_ta_card.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    prices = tmp_path / "prices"
    t = pd.bdate_range(end="2026-10-30", periods=320)
    idx = _bars(_trend(320, 0.1, start=1200.0)).assign(time=t, volume=0.0)
    _write_ticker(prices, "VNINDEX", idx)
    for k, tk in enumerate(("FPT", "HPG", "VCB")):
        _write_ticker(prices, tk, _bars(_trend(320, 0.1 * (k - 1), start=50.0),
                                        volume=np.full(320, 1e6 * (k + 1))).assign(time=t))
    before = sorted(p for p in tmp_path.rglob("*"))
    assert mod.main(["--prices", str(prices), "--top", "2", "--date", "2026-10-20"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("📈 Kỹ thuật VN-Index — phiên 2026-10-20, đóng cửa ")
    assert "Từng mã (VN30, 2 mã GTGD TB20 lớn nhất):" in out
    ticker_lines = [ln for ln in out.splitlines() if ln.startswith("- ") and ": ngắn " in ln]
    assert [ln.split()[1] for ln in ticker_lines] == ["VCB", "HPG"]
    assert "không có dữ liệu trong kho:" in out and "FPT" not in out.split("không có")[1]
    assert sorted(p for p in tmp_path.rglob("*")) == before          # chỉ đọc


# ── Sau bản mẫu kho thật 04/11 ──────────────────────────────────────────

def test_level_already_crossed_reads_as_crossed_not_negative_atr():
    """VN-Index đóng 1.733 trên R1 1.709 (mức công bố trước phiên) từng in "R1 (-0.92 ATR)"."""
    lv = {"support_1": 95.0, "resistance_1": 99.0, "s1_atr": 1.5, "r1_atr": -0.92}
    assert tc._level_txt(lv) == "S1 95.00 (1.50 ATR) · đã vượt R1 99.00 (0.92 ATR)"
    lv = {"support_1": 101.0, "s1_atr": -0.4}
    assert tc._level_txt(lv) == "đã thủng S1 101.00 (0.40 ATR)"
    assert "-" not in tc._level_txt({"support_1": 95.0, "resistance_1": 99.0,
                                     "s1_atr": -1.0, "r1_atr": -2.0})


def test_ticker_line_flags_stale_data_against_market_session():
    """TCB đứng 28/10 (GDKHQ chưa rebase) mà vẫn in như phiên hôm nay (bản mẫu 04/11)."""
    card = tc.ta_card(_bars(_trend(320, 0.3)), label="TCB")
    later = "2999-01-01"
    assert tc.card_line(card, market_as_of=later).startswith(
        f"⚠️ TCB (dữ liệu dừng từ {card['as_of']}, số dưới đây là của phiên đó)")
    assert tc.card_line(card, market_as_of=card["as_of"]).startswith("TCB ")
    assert tc.card_line(card).startswith("TCB ")
