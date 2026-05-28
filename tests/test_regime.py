"""Tests for vnstock_regime.classify_regime() — market regime classifier."""

from __future__ import annotations

import pytest

from vnstock_regime import classify_regime, PRESET_SUGGESTIONS, REGIME_META


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bull_tech() -> dict:
    """VNINDEX above all MAs, healthy RSI."""
    return {"close": 1280.0, "ma20": 1240, "ma50": 1200, "ma200": 1150, "rsi14": 62}


def _bear_tech() -> dict:
    """VNINDEX below all MAs, weak RSI."""
    return {"close": 1080.0, "ma20": 1110, "ma50": 1150, "ma200": 1200, "rsi14": 32}


def _flat_tech() -> dict:
    return {"close": 1200.0, "ma20": 1200, "ma50": 1200, "ma200": 1200, "rsi14": 50}


# ─── Score → regime mapping ───────────────────────────────────────────────────

def test_bull_inputs_yield_bull_regime():
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 70, "advances": 300, "declines": 100},
        nn_net_1d=250.0,
    )
    assert out["regime"] == "bull"
    assert out["score"] >= 4
    assert "🔥" in out["label"] or "Bull" in out["label"]


def test_bear_inputs_yield_bear_regime():
    out = classify_regime(
        vnindex_tech=_bear_tech(),
        breadth={"above_ma200_pct": 18, "advances": 80, "declines": 350},
        nn_net_1d=-450.0,
    )
    assert out["regime"] == "bear"
    assert out["score"] <= -4


def test_flat_inputs_yield_sideways():
    out = classify_regime(
        vnindex_tech=_flat_tech(),
        breadth={"above_ma200_pct": 45, "advances": 200, "declines": 200},
        nn_net_1d=20.0,
    )
    assert out["regime"] == "sideways"
    assert abs(out["score"]) <= 0


def test_mild_bullish_yields_bullish_not_bull():
    """Score in [1,3] → 'bullish', not 'bull'."""
    out = classify_regime(
        vnindex_tech={"close": 1210, "ma20": 1200, "ma50": 1190,
                      "ma200": 1300, "rsi14": 52},
        breadth={"above_ma200_pct": 40, "advances": 220, "declines": 180},
        nn_net_1d=50.0,
    )
    assert out["regime"] == "bullish"
    assert 1 <= out["score"] <= 3


def test_mild_bearish_yields_bearish_not_bear():
    out = classify_regime(
        vnindex_tech={"close": 1180, "ma20": 1190, "ma50": 1200,
                      "ma200": 1170, "rsi14": 48},
        breadth={"above_ma200_pct": 42, "advances": 190, "declines": 220},
        nn_net_1d=-70.0,
    )
    assert out["regime"] == "bearish"
    assert -3 <= out["score"] <= -1


# ─── Special overrides ────────────────────────────────────────────────────────

def test_overbought_rsi_overrides_to_sideways():
    """RSI > 72 + score ≥ 2 → forced sideways (caution)."""
    out = classify_regime(
        vnindex_tech={"close": 1290, "ma20": 1240, "ma50": 1200,
                      "ma200": 1150, "rsi14": 78},
        breadth={"above_ma200_pct": 60, "advances": 250, "declines": 130},
        nn_net_1d=120.0,
    )
    assert out["regime"] == "sideways"
    assert out["rsi14"] == 78


# ─── Signal generation ────────────────────────────────────────────────────────

def test_signal_count_grows_with_data_completeness():
    """Empty inputs → 0 signals; full inputs → 7 signals."""
    empty = classify_regime(vnindex_tech={}, breadth={}, nn_net_1d=0.0)
    assert empty["n_signals"] == 0

    full = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 70, "advances": 300, "declines": 100},
        nn_net_1d=250.0,
    )
    assert full["n_signals"] == 7


def test_ad_ratio_skipped_when_breadth_missing():
    """A/D signal should NOT fire if 'advances'/'declines' keys absent."""
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 60},  # no advances/declines
        nn_net_1d=0.0,
    )
    names = [s["name"] for s in out["signals"]]
    assert "A/D ratio" not in names


def test_nn_flow_skipped_when_zero():
    """NN signal only fires when value != 0."""
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 60, "advances": 300, "declines": 100},
        nn_net_1d=0.0,
    )
    names = [s["name"] for s in out["signals"]]
    assert "NN ròng 1D" not in names


def test_signals_have_direction_in_minus1_to_1():
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 50, "advances": 200, "declines": 200},
        nn_net_1d=10.0,
    )
    for sig in out["signals"]:
        assert sig["direction"] in (-1, 0, 1)


# ─── Preset suggestions ───────────────────────────────────────────────────────

def test_each_regime_has_preset_suggestions():
    """All 5 regimes have at least 1 preset suggestion."""
    for regime in ("bull", "bullish", "sideways", "bearish", "bear"):
        assert regime in PRESET_SUGGESTIONS
        assert len(PRESET_SUGGESTIONS[regime]) > 0


def test_bull_suggests_momentum_or_breakout():
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 70, "advances": 300, "declines": 100},
        nn_net_1d=250.0,
    )
    assert any(p in out["suggested_presets"]
               for p in ("momentum", "breakout", "strong_uptrend"))


def test_bear_suggests_oversold_or_reversal():
    out = classify_regime(
        vnindex_tech=_bear_tech(),
        breadth={"above_ma200_pct": 15, "advances": 80, "declines": 350},
        nn_net_1d=-450.0,
    )
    assert any(p in out["suggested_presets"]
               for p in ("oversold", "reversal"))


# ─── Output shape ─────────────────────────────────────────────────────────────

def test_classify_returns_required_keys():
    out = classify_regime(_bull_tech(), {}, 0.0)
    for k in ("regime", "label", "color", "bg", "score", "n_signals",
              "confidence", "signals", "suggested_presets",
              "vnindex_close", "rsi14"):
        assert k in out


def test_confidence_in_zero_to_one():
    out = classify_regime(
        vnindex_tech=_bull_tech(),
        breadth={"above_ma200_pct": 60, "advances": 200, "declines": 200},
        nn_net_1d=150.0,
    )
    assert 0.0 <= out["confidence"] <= 1.0


def test_regime_meta_consistent():
    """All regime keys map to a label/color/bg."""
    for regime in PRESET_SUGGESTIONS:
        assert regime in REGIME_META
        meta = REGIME_META[regime]
        assert "label" in meta
        assert meta["color"].startswith("#")
        assert meta["bg"].startswith("#")
