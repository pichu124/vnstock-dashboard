"""Tests cho vnstock_candle_patterns (port StockSharp CandlePatternRegistry)
+ wiring screener (metrics & presets). Hermetic — data tự chế, zero I/O."""

from __future__ import annotations

import pandas as pd

from vnstock_candle_patterns import (
    detect, detect_df, pattern_labels, PATTERNS, _has_unit_break,
)


def _downtrend(n=7, start=100.0, step=1.5):
    """n nến giảm dần — nền cho các mẫu đảo chiều tăng (gate trend)."""
    out = []
    px = start
    for _ in range(n):
        out.append((px, px + 0.3, px - step - 0.3, px - step))
        px -= step
    return out


def _uptrend(n=7, start=100.0, step=1.5):
    out = []
    px = start
    for _ in range(n):
        out.append((px, px + step + 0.3, px - 0.3, px + step))
        px += step
    return out


def _keys(hits):
    return {h["key"] for h in hits}


# ─── mẫu 2 nến ────────────────────────────────────────────────────────────────

def test_bullish_engulfing():
    candles = _downtrend() + [
        (88, 89, 86, 86.5),      # nến đen
        (85.5, 90, 85, 89.5),    # trắng bao trọn thân nến trước
    ]
    assert "bullish_engulfing" in _keys(detect(candles))


def test_bearish_engulfing():
    candles = _uptrend() + [
        (112, 114, 111.5, 113.5),   # nến trắng
        (114.5, 115, 111, 111.5),   # đen bao trọn thân nến trước
    ]
    assert "bearish_engulfing" in _keys(detect(candles))


def test_tweezer_bottom_uses_tolerance_not_float_equality():
    base = _downtrend()
    # 2 đáy lệch 0.05% — bước giá HOSE khiến equality float không bao giờ khớp
    candles = base + [(88, 89, 85.00, 86.0), (85.8, 88.5, 85.04, 88.0)]
    assert "tweezer_bottom" in _keys(detect(candles))
    # đáy lệch hẳn 1% → không phải tweezer
    candles2 = base + [(88, 89, 85.00, 86.0), (85.8, 88.5, 85.9, 88.0)]
    assert "tweezer_bottom" not in _keys(detect(candles2))


def test_on_neck_tolerance():
    candles = _uptrend() + [
        (100, 100.5, 95, 95.5),        # đen dài
        (94.5, 95.02, 94, 95.01),      # trắng đóng ≈ đáy nến trước
    ]
    assert "on_neck" in _keys(detect(candles))


# ─── mẫu 1 nến — gate xu hướng cho cặp song sinh ─────────────────────────────

def test_hammer_requires_preceding_downtrend():
    hammer_bar = (90, 90.6, 87.5, 90.5)   # thân nhỏ, râu dưới dài, râu trên ~0
    assert "hammer" in _keys(detect(_downtrend() + [hammer_bar]))
    # cùng bar sau nhịp TĂNG → không phải hammer (vùng hanging man)
    assert "hammer" not in _keys(detect(_uptrend() + [hammer_bar]))


def test_hanging_man_requires_preceding_uptrend():
    hm_bar = (110, 110.4, 107, 110.2)
    hits_up = _keys(detect(_uptrend() + [hm_bar]))
    assert "hanging_man" in hits_up and "hammer" not in hits_up
    assert "hanging_man" not in _keys(detect(_downtrend() + [hm_bar]))


def test_twins_never_fire_together_without_trend():
    # đi ngang (trend < 1%) → cả hammer lẫn hanging_man đều bị bỏ
    flat = [(100, 100.6, 99.5, 100.1)] * 7
    hits = _keys(detect(flat + [(100, 100.4, 97.5, 100.2)]))
    assert "hammer" not in hits and "hanging_man" not in hits


def test_shooting_star_after_uptrend():
    bar = (110, 113.5, 109.9, 110.3)   # râu trên dài, thân nhỏ, râu dưới ~0
    assert "shooting_star" in _keys(detect(_uptrend() + [bar]))


def test_marubozu_with_tolerance():
    candles = _downtrend() + [(90.0, 93.0, 89.995, 92.997)]  # O≈L, C≈H
    assert "white_marubozu" in _keys(detect(candles))


# ─── bẫy nến 1 giá (trần/sàn) ────────────────────────────────────────────────

def test_one_price_candle_no_shape_patterns_no_crash():
    candles = _uptrend() + [(110, 110, 110, 110)]  # kịch trần cả phiên
    hits = detect(candles)
    assert all(h["n"] > 1 for h in hits)  # không mẫu hình-dạng đơn nào
    for k in ("dragonfly", "gravestone", "hammer", "hanging_man"):
        assert k not in _keys(hits)


# ─── mẫu 3 & 5 nến ───────────────────────────────────────────────────────────

def test_morning_star():
    candles = _downtrend() + [
        (92, 92.5, 88, 88.5),        # đen dài (B=3.5)
        (88.2, 88.8, 87.6, 88.0),    # thân nhỏ (< 50% thân trước)
        (88.4, 92, 88.2, 91.5),      # trắng
    ]
    assert "morning_star" in _keys(detect(candles))


def test_three_white_soldiers():
    candles = _downtrend() + [
        (88, 90.5, 87.8, 90),
        (89, 92.5, 88.8, 92),
        (91, 94.5, 90.8, 94),
    ]
    assert "three_white_soldiers" in _keys(detect(candles))


def test_rising_three_methods():
    candles = [
        (100, 106.2, 99.8, 106),      # trắng dài (B=6)
        (105.5, 105.8, 103.2, 103.5), # 3 nến đen nhỏ (B < 3)
        (104.5, 104.8, 102.4, 102.7),
        (103.5, 103.8, 101.8, 102.0),
        (102.5, 108.5, 102.3, 108.2), # trắng dài B=5.7 > 2×1.5
    ]
    hits = _keys(detect(candles))
    assert "rising_three_methods" in hits


def test_multi_candle_patterns_sorted_first():
    candles = _downtrend() + [
        (92, 92.5, 88, 88.5),
        (88.2, 88.8, 87.6, 88.0),
        (88.4, 92, 88.2, 91.5),
    ]
    hits = detect(candles)
    assert hits and hits[0]["n"] >= hits[-1]["n"]


# ─── guard dữ liệu rác ───────────────────────────────────────────────────────

def test_unit_break_guard_blocks_mixed_unit_series():
    # per-bar normalization quanh mốc 500 VND: 480 → 0.51 (bẫy đã ghi ở
    # vnstock_preset_score._stitch_units) — không được nhận diện gì
    assert _has_unit_break([480, 0.51, 495, 0.52])
    candles = [(480, 485, 475, 480), (0.51, 0.52, 0.50, 0.51),
               (495, 500, 490, 495), (0.52, 0.53, 0.51, 0.52)]
    assert detect(candles) == []


def test_bad_bar_skipped_no_crash():
    candles = _downtrend() + [(90, 85, 92, 91)]  # high < low: bar hỏng
    assert detect(candles) == []


def test_detect_df_and_labels():
    rows = _downtrend() + [(88, 89, 86, 86.5), (85.5, 90, 85, 89.5)]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    hits = detect_df(df)
    assert "bullish_engulfing" in _keys(hits)
    labels = pattern_labels(hits)
    assert len(labels) <= 3 and any("Bao phủ tăng" in s for s in labels)
    # thiếu cột → [] (không nổ)
    assert detect_df(pd.DataFrame({"close": [1, 2, 3]})) == []
    assert detect_df(None) == []


def test_registry_directions_are_valid():
    assert all(s["direction"] in ("bull", "bear", "neutral")
               for s in PATTERNS.values())
    assert all(s["n"] in (1, 2, 3, 5) for s in PATTERNS.values())


# ─── wiring screener ─────────────────────────────────────────────────────────

def _screener_df(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = pd.date_range("2026-01-01", periods=len(df), freq="D")
    df["volume"] = 100_000
    return df


def test_calc_indicators_emits_candle_and_crsi_fields():
    from vnstock_screener import _calc_indicators
    # 130 bar giảm dần rồi bao phủ tăng ở cuối → đủ cho CRSI (cần 102 bar)
    rows = []
    px = 300.0
    for _ in range(128):
        rows.append((px, px + 0.4, px - 1.1, px - 0.9))
        px -= 0.9
    rows += [(px, px + 0.3, px - 2.0, px - 1.8),
             (px - 2.3, px + 1.5, px - 2.5, px + 1.2)]
    r = _calc_indicators(_screener_df(rows))
    assert r.get("candle_bull") is True
    assert "bullish_engulfing" in r.get("candle_patterns", "")
    assert isinstance(r.get("crsi"), float)


def test_new_presets_filter_on_flags():
    from vnstock_screener import PRESETS
    assert PRESETS["candle_bull"]["filter"]({"candle_bull": True})
    assert not PRESETS["candle_bull"]["filter"]({})
    assert PRESETS["candle_bear"]["filter"]({"candle_bear": True})
    assert not PRESETS["candle_bear"]["filter"]({"candle_bull": True})
    assert PRESETS["crsi_oversold"]["filter"]({"crsi": 5.2})
    assert not PRESETS["crsi_oversold"]["filter"]({"crsi": 55.0})
    assert not PRESETS["crsi_oversold"]["filter"]({})


def test_preset_score_groups_include_new_meanrev_presets():
    from vnstock_preset_score import _MEANREV_PRESETS, _TREND_PRESETS
    assert "candle_bull" in _MEANREV_PRESETS
    assert "crsi_oversold" in _MEANREV_PRESETS
    assert "candle_bear" not in _MEANREV_PRESETS + _TREND_PRESETS
