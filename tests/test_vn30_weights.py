"""Tests for vnstock_vn30_weights — dynamic VN30 sector weights."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import vnstock_vn30_weights as vw
from vnstock_vn30_weights import (
    _FALLBACK_WEIGHTS, compute_vn30_sector_weights, cache_metadata,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect the cache file to a fresh temp path for every test."""
    cache_path = tmp_path / "vn30_weights.json"
    monkeypatch.setattr(vw, "_CACHE_PATH", cache_path)
    yield cache_path


# ─── Fallback ────────────────────────────────────────────────────────────────

def test_fallback_weights_sum_close_to_100():
    total = sum(_FALLBACK_WEIGHTS.values())
    assert 95 <= total <= 105   # allow small rounding


def test_fallback_includes_banking_as_dominant():
    assert _FALLBACK_WEIGHTS["Ngân hàng"] == max(_FALLBACK_WEIGHTS.values())


# ─── compute_vn30_sector_weights ─────────────────────────────────────────────

def test_compute_returns_dict_with_floats(monkeypatch):
    """When no industry map / ticker list available, falls back."""
    monkeypatch.setattr(vw, "_vn30_tickers", lambda: [])
    out = compute_vn30_sector_weights(force_refresh=True)
    assert isinstance(out, dict)
    assert all(isinstance(v, (int, float)) for v in out.values())


def test_compute_falls_back_when_no_tickers(monkeypatch):
    monkeypatch.setattr(vw, "_vn30_tickers", lambda: [])
    out = compute_vn30_sector_weights(force_refresh=True)
    assert out == _FALLBACK_WEIGHTS


def test_compute_equal_weight_mode_when_no_mcap(monkeypatch):
    """No fund_cache → equal-weight by sector ticker count."""
    monkeypatch.setattr(vw, "_vn30_tickers",
                        lambda: ["VCB", "TCB", "ACB", "FPT", "MSN"])
    monkeypatch.setattr(vw, "_industry_map", lambda: {
        "VCB": "Ngân hàng", "TCB": "Ngân hàng", "ACB": "Ngân hàng",
        "FPT": "Công nghệ thông tin & Phần mềm",
        "MSN": "Thực phẩm & Đồ uống",
    })
    monkeypatch.setattr(vw, "_ticker_market_caps", lambda _: {})
    out = compute_vn30_sector_weights(force_refresh=True)
    # 3 ngân hàng out of 5 → 60%
    assert out.get("Ngân hàng") == pytest.approx(60.0, abs=0.1)
    # Sum ≈ 100
    assert sum(out.values()) == pytest.approx(100.0, abs=0.5)


def test_compute_market_cap_mode_when_enough_data(monkeypatch):
    """≥20 fund_cache entries → market-cap weighted."""
    tickers = [f"T{i:02d}" for i in range(30)]
    monkeypatch.setattr(vw, "_vn30_tickers", lambda: tickers)
    # All in same sector for simplicity
    monkeypatch.setattr(vw, "_industry_map",
                        lambda: {t: "Ngân hàng" for t in tickers})
    # 25 tickers have market_cap, 5 don't
    mcaps = {t: 1e12 for t in tickers[:25]}
    monkeypatch.setattr(vw, "_ticker_market_caps", lambda _: mcaps)
    out = compute_vn30_sector_weights(force_refresh=True)
    meta = cache_metadata()
    assert meta["mode"] == "market_cap"
    # All in Ngân hàng → 100%
    assert out["Ngân hàng"] == pytest.approx(100.0, abs=0.1)


def test_cache_metadata_persists(monkeypatch, _isolated_cache):
    monkeypatch.setattr(vw, "_vn30_tickers", lambda: ["VCB", "TCB"])
    monkeypatch.setattr(vw, "_industry_map", lambda: {
        "VCB": "Ngân hàng", "TCB": "Ngân hàng",
    })
    monkeypatch.setattr(vw, "_ticker_market_caps", lambda _: {})

    compute_vn30_sector_weights(force_refresh=True)
    assert _isolated_cache.exists()
    payload = json.loads(_isolated_cache.read_text())
    assert "weights" in payload
    assert "mode" in payload
    assert "updated_at" in payload
    assert payload["n_tickers"] == 2


def test_cache_loaded_when_fresh(monkeypatch, _isolated_cache):
    """A non-force_refresh call should hit the cache."""
    _isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_cache.write_text(json.dumps({
        "weights": {"FakeSector": 100.0},
        "n_tickers": 30, "mode": "equal",
        "updated_at": "2030-01-01T00:00:00",
    }))
    monkeypatch.setattr(vw, "_vn30_tickers", lambda: [])
    out = compute_vn30_sector_weights()
    assert out == {"FakeSector": 100.0}


def test_stale_cache_ignored(monkeypatch, _isolated_cache):
    """Cache older than 7 days should be re-computed."""
    import os, time
    _isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_cache.write_text(json.dumps({
        "weights": {"Stale": 100.0}, "n_tickers": 30,
        "mode": "equal", "updated_at": "old",
    }))
    # Backdate mtime to 10 days ago
    old = time.time() - 10 * 86400
    os.utime(_isolated_cache, (old, old))

    monkeypatch.setattr(vw, "_vn30_tickers", lambda: [])
    out = compute_vn30_sector_weights()  # not force_refresh — but cache stale
    assert out != {"Stale": 100.0}
    assert out == _FALLBACK_WEIGHTS
