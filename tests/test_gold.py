"""Tests for vnstock_gold — giá vàng spot display-only (P6). Hermetic: cache
trỏ tmp_path, HTTP fake qua sys.modules."""
import json
import sys
import types
from datetime import date

import pytest

import vnstock_gold as gold


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gold, "_CACHE", tmp_path / "gold_price.json")


def _fake_requests(monkeypatch, payloads):
    """payloads: url-substring → dict JSON | Exception."""
    class _Resp:
        def __init__(self, data):
            self._d = data
        def raise_for_status(self):
            pass
        def json(self):
            return self._d

    def _get(url, **kw):
        for frag, data in payloads.items():
            if frag in url:
                if isinstance(data, Exception):
                    raise data
                return _Resp(data)
        raise RuntimeError("blocked")

    mod = types.ModuleType("requests")
    mod.get = _get
    monkeypatch.setitem(sys.modules, "requests", mod)


def test_fetch_parses_gold_api_shape(monkeypatch):
    # goldprice.org gỡ 09/10 (403 trên 🖥️ desktop, U82) — chỉ còn gold-api.com
    assert not any("goldprice" in url for url, _ in gold._ENDPOINTS)
    _fake_requests(monkeypatch, {"gold-api.com": {"price": 3300.15}})
    assert gold.fetch_gold_usd() == 3300.15
    _fake_requests(monkeypatch, {"gold-api.com": RuntimeError("down")})
    assert gold.fetch_gold_usd() is None


def test_fetch_rejects_out_of_range_and_all_dead(monkeypatch):
    _fake_requests(monkeypatch, {"gold-api.com": {"price": 999999}})
    assert gold.fetch_gold_usd() is None
    _fake_requests(monkeypatch, {})
    assert gold.fetch_gold_usd() is None


def test_refresh_writes_history_and_keeps_cache_on_fail(monkeypatch):
    monkeypatch.setattr(gold, "fetch_gold_usd", lambda timeout=15: 3350.0)
    assert gold.refresh() == 3350.0
    hist = json.loads(gold._CACHE.read_text(encoding="utf-8"))["history"]
    assert hist[date.today().isoformat()] == 3350.0
    # fetch fail → cache cũ NGUYÊN VẸN, không bịa
    monkeypatch.setattr(gold, "fetch_gold_usd", lambda timeout=15: None)
    assert gold.refresh() is None
    assert json.loads(gold._CACHE.read_text(encoding="utf-8"))["history"] == hist


def test_refresh_disabled_by_env(monkeypatch):
    monkeypatch.setenv("VNSTOCK_GOLD", "0")
    monkeypatch.setattr(gold, "fetch_gold_usd", lambda timeout=15: 3350.0)
    assert gold.refresh() is None
    assert not gold._CACHE.exists()


def test_load_gold_change_and_note():
    gold._write_cache({"history": {"2026-07-10": 3300.0, "2026-07-11": 3366.0}})
    g = gold.load_gold()
    assert g["value"] == 3366.0 and g["as_of"] == "2026-07-11"
    assert "premium SJC" in g["note"]                 # nhãn bắt buộc
    assert g["change"]["dir"] == 1
    assert g["change"]["pct"] == pytest.approx(2.0)
    assert gold.load_gold() is not None
    gold._write_cache({})
    assert gold.load_gold() is None


def test_price_on_nearest_at_or_before():
    gold._write_cache({"history": {"2026-07-01": 3300.0, "2026-07-10": 3350.0}})
    assert gold.price_on("2026-07-05") == 3300.0      # gần nhất ≤ ngày hỏi
    assert gold.price_on("2026-07-10") == 3350.0
    assert gold.price_on("2026-06-30") is None


def test_history_capped(monkeypatch):
    monkeypatch.setattr(gold, "_MAX_HISTORY", 2)
    gold._write_cache({"history": {"2026-07-01": 1500.0, "2026-07-02": 1501.0}})
    monkeypatch.setattr(gold, "fetch_gold_usd", lambda timeout=15: 1502.0)
    gold.refresh()
    hist = json.loads(gold._CACHE.read_text(encoding="utf-8"))["history"]
    assert sorted(hist) == ["2026-07-02", date.today().isoformat()]
