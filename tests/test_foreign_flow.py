"""Tests for vnstock_foreign_flow — full-market NN ròng cache + freshness loader.

The live API fetch (fetch_market_net via vnstock_data.TopStock) needs network and
is not exercised here; we test the cache/freshness/loader logic and the
per-symbol value extraction with synthetic data.
"""
import importlib
import json

import vnstock_foreign_flow as ff


def _use_tmp_cache(tmp_path, monkeypatch):
    p = tmp_path / "foreign_net_daily.json"
    monkeypatch.setattr(ff, "_CACHE", p)
    return p


def test_largest_value_prefers_value_columns_over_volume():
    # buy_value should win over a huge share-count "volume" column
    row = {"symbol": "VCB", "date": "2026-06-12", "buy_value": 1.2e11,
           "sell_value": 5.0e10, "volume": 9.9e8}
    assert ff._largest_value(row) == 1.2e11
    # fallback to largest numeric when no named value column present
    assert ff._largest_value({"symbol": "X", "foo": 3.0, "bar": 7.0}) == 7.0


def test_load_market_net_1d_is_date_aware_and_omits_missing(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({
        "2026-06-11": {"net": -504.0, "buy": 3000.0, "sell": 3504.0, "n_symbols": 420},
        "2026-06-12": {"net": -491.0, "buy": 3100.0, "sell": 3591.0, "n_symbols": 418},
    }), encoding="utf-8")
    # exact date → that day's full-market net (not a frozen value)
    assert ff.load_market_net_1d("2026-06-12") == -491.0
    assert ff.load_market_net_1d("2026-06-11") == -504.0
    # a date NOT in cache → None (caller omits the signal, never shows stale)
    assert ff.load_market_net_1d("2026-06-13") is None
    # no date → latest cached day
    assert ff.load_market_net_1d() == -491.0
    # empty cache → None
    p.write_text("{}", encoding="utf-8")
    assert ff.load_market_net_1d("2026-06-12") is None


def test_regime_loader_uses_full_market_source_date_aware(tmp_path, monkeypatch):
    # vnstock_regime._load_nn_net_1d must read the full-market per-date cache and
    # return the right day's value (or 0.0 → omit) — NOT the legacy top-100 cache.
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({"2026-06-12": {"net": -491.0, "n_symbols": 418}}),
                 encoding="utf-8")
    import vnstock_regime
    importlib.reload(vnstock_regime)
    assert vnstock_regime._load_nn_net_1d("2026-06-12") == -491.0
    # unknown date → 0.0 (sentiment omits the NN signal rather than showing stale)
    assert vnstock_regime._load_nn_net_1d("2099-01-01") == 0.0


def test_sentiment_loader_maps_zero_to_none(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    p.write_text(json.dumps({"2026-06-12": {"net": -491.0}}), encoding="utf-8")
    import vnstock_regime
    importlib.reload(vnstock_regime)
    import vnstock_market_sentiment
    importlib.reload(vnstock_market_sentiment)
    assert vnstock_market_sentiment._load_nn_net_1d("2026-06-12") == -491.0
    # no fresh figure → None so compute_market_sentiment skips the NN signal
    assert vnstock_market_sentiment._load_nn_net_1d("2099-01-01") is None
