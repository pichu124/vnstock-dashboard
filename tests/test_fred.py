"""Tests for vnstock_fred — US10Y + Fed funds từ FRED + vnstock_macro wiring.

Fetch thật cần mạng + FRED_API_KEY; ở đây test parse/sanity/best-effort với
requests.get giả và wiring vào registry vĩ mô (mirror test_vbma/test_nso).
"""
from __future__ import annotations

import pytest

import vnstock_fred as fred
import vnstock_macro as mac


@pytest.fixture(autouse=True)
def _no_external_macro_fetch(monkeypatch):
    monkeypatch.setattr(mac, "_fetch_nso", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: None)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_get_factory(payload_by_series):
    def _fake_get(url, params=None, timeout=None):
        return _FakeResp(payload_by_series[params["series_id"]])
    return _fake_get


# ── fetch_series: parse + skip "." + sanity ──────────────────────────────────


def test_fetch_series_skips_missing_dot_values(monkeypatch):
    # DGS10 nghỉ cuối tuần/lễ → observation value "." phải bị nhảy qua
    monkeypatch.setattr("requests.get", _fake_get_factory({"DGS10": {
        "observations": [
            {"date": "2026-07-11", "value": "."},
            {"date": "2026-07-10", "value": "."},
            {"date": "2026-07-09", "value": "4.35"},
        ]}}))
    assert fred.fetch_series("DGS10", "k") == (4.35, "2026-07-09")


def test_fetch_series_none_on_error_or_empty(monkeypatch):
    def _boom(*a, **k):
        raise OSError("mạng chặn")
    monkeypatch.setattr("requests.get", _boom)
    assert fred.fetch_series("DGS10", "k") is None
    monkeypatch.setattr("requests.get",
                        _fake_get_factory({"DGS10": {"observations": []}}))
    assert fred.fetch_series("DGS10", "k") is None


def test_fetch_daily_requires_key_and_applies_ranges(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred.fetch_daily() is None                    # không key → None

    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr("requests.get", _fake_get_factory({
        "DGS10": {"observations": [{"date": "2026-07-09", "value": "4.35"}]},
        "DFF":   {"observations": [{"date": "2026-07-10", "value": "99.0"}]},
    }))
    got = fred.fetch_daily()
    # DFF 99 ngoài sanity range (0-20) → bị loại; DGS10 giữ, as_of riêng
    assert got == {"us10y": (4.35, "2026-07-09")}


# ── vnstock_macro wiring ─────────────────────────────────────────────────────


def _use_tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro_indicators.json")
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)


def test_refresh_records_fred_readings_with_per_series_as_of(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "_fetch_fred", lambda: {
        "us10y": (4.35, "2026-07-09"),
        "fed_funds": (4.33, "2026-07-10"),
    })
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["us10y"]["value"] == pytest.approx(4.35)
    assert rows["us10y"]["as_of"] == "2026-07-09"        # as_of RIÊNG từng series
    assert rows["fed_funds"]["as_of"] == "2026-07-10"
    assert rows["us10y"]["source"] == "fred"


def test_refresh_fred_kill_switch_and_failure_keeps_cache(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    mac.set_value("us10y", 9.9, as_of="2026-07-01")
    monkeypatch.setattr(mac, "_fetch_fred", lambda: None)   # fetch hỏng
    mac.refresh()
    rows = {x["key"]: x for x in mac.load_macro()}
    assert rows["us10y"]["value"] == pytest.approx(9.9)     # giữ giá trị --set

    monkeypatch.setenv("VNSTOCK_MACRO_FRED", "0")
    calls = {"n": 0}
    monkeypatch.setattr(mac, "_fetch_fred",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    mac.refresh()
    assert calls["n"] == 0                                  # kill-switch


def test_fred_key_gate_reads_env(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred._api_key() == ""
    monkeypatch.setenv("FRED_API_KEY", "  abc  ")
    assert fred._api_key() == "abc"


def test_macro_cli_loads_dotenv_for_fred_key(tmp_path, monkeypatch):
    # `run.py macro` / CLI từng KHÔNG load .env → FRED bị skip lặng lẽ dù
    # `vnstock_fred.py --diag` (tự load .env) chạy được — bẫy thật 13/07.
    monkeypatch.setattr(mac, "_REPO", tmp_path)
    monkeypatch.setattr(mac, "_CACHE", tmp_path / "macro.json")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    (tmp_path / ".env").write_text("FRED_API_KEY=key_tu_dotenv\n",
                                   encoding="utf-8")
    mac.main(["--show"])                       # main phải load .env dù chỉ --show
    import os
    assert os.environ.get("FRED_API_KEY") == "key_tu_dotenv"
