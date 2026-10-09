"""vnstock_assets_mcp — MCP Finhay/SSI cho kho đa tài sản (U82, 09/10).

Hermetic: `collect` tiêm (không spawn `claude`), kho về tmp (conftest). Payload mẫu là số THẬT
đo 09/10: Finhay XAU 4.182,09 · SJC miếng 14.180/14.480 nghìn đ/chỉ · SSI SBVN 24.398/26.860."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

import vnstock_assets as va
import vnstock_assets_mcp as am

TODAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 14, 0)
FP, SP = "mcp__claude_ai_Finhay__", "mcp__claude_ai_SSI_MCP__"

SBVN = json.dumps({"status": "ok", "data": {"rates": [
    {"currency_name": "SBVN_VND-USD", "buy": 24407.0, "sell": 26869.0, "trading_date": "08/10/2026"},
    {"currency_name": "SBVN_VND-EUR", "buy": 27318.0, "sell": 30194.0, "trading_date": "09/10/2026"},
    {"currency_name": "SBVN_VND-USD", "buy": 24398.0, "sell": 26860.0, "trading_date": "09/10/2026"}]}})
VCB = json.dumps({"status": "ok", "data": {"rates": [
    {"currency_name": "VCB_VND-USD", "buy": 25680.0, "sell": 26090.0, "transfer": 25710.0, "trading_date": "09/10/2026"}]}})


def _series(bars, **extra):
    return json.dumps({"series": bars, **extra})


def _exchanges(plan, texts: dict):
    out = []
    for p in plan:
        if p["key"] in texts:
            t = texts[p["key"]]
            out.append({"name": p["tool"], "input": dict(p["input"]), "text": t,
                        "is_error": t.startswith("ERR")})
    return out


def test_plan_daily_market_tools_only_and_shim_safe_prompt():
    plan = am.plan_daily(TODAY, FP, SP)
    assert len(plan) == 16
    tools = {p["tool"] for p in plan}
    assert tools == {FP + am.T_COMMODITY, FP + am.T_FOREX, FP + am.T_DEALER, SP + am.T_SSI_FX}
    assert not any(w in t for t in tools for w in ("portfolio", "order", "account", "asset_summary"))
    assert {p["key"] for p in plan} >= {"GOLD_BTMH_RING", "USD_CENTRAL", "XAU"}
    system, user = am.build_prompt(plan)
    assert not set('|<>%"\n') & set(system) and user.count("\n") == len(plan) + 1


def test_parse_finhay_commodity_and_dealer_units():
    rows = am.parse_finhay(_series([{"t": 1791478800, "o": 4144.68, "h": 4207.51, "l": 4141.84, "c": 4182.09}]), False)
    assert rows == [{"date": "2026-10-09", "close": 4182.09, "open": 4144.68, "high": 4207.51,
                     "low": 4141.84, "source": "finhay"}]
    d = am.parse_finhay(_series([{"t": 1791478800, "bid": 14180, "ask": 14480}], unit="chi"), True)
    assert d[0]["close"] == d[0]["ask"] == 144_800_000 and d[0]["bid"] == 141_800_000


def test_parse_ssi_sbvn_central_and_vcb():
    rows = am.parse_ssi(SBVN, "SBVN")
    assert [r["date"] for r in rows] == ["2026-10-08", "2026-10-09"]
    assert rows[-1]["close"] == 25629.0 and rows[-1]["source"] == "ssi-sbvn"
    v = am.parse_ssi(VCB, "VCB")[0]
    assert v["close"] == 26090 and v["bid"] == 25710 and v["source"] == "ssi"


def test_rows_from_exchanges_matches_and_reports_errors():
    plan = am.plan_daily(TODAY, FP, SP)
    ex = _exchanges(plan, {"XAU": _series([{"t": 1791478800, "c": 4182.09}]),
                           "WTI": "ERR 401", "USD_CENTRAL": SBVN, "GOLD_SJC_BAR": _series([])})
    ex[0]["input"]["from"] = str(ex[0]["input"]["from"])          # model đổi kiểu số
    rows, errors = am.rows_from_exchanges(plan, ex)
    assert set(rows) == {"XAU", "USD_CENTRAL"}
    assert errors["WTI"].startswith("ERR") and errors["GOLD_SJC_BAR"] == "kết quả rỗng"
    assert errors["BRENT"] == "model không gọi tool này"


def _collect_ok(user, system, allowed):
    plan = am.plan_daily(TODAY, *am.prefixes())
    texts = {k: _series([{"t": 1791478800, "c": 100.5}]) for k in ("BRENT", "WTI")}
    texts.update({"XAU": _series([{"t": 1791478800, "c": 4182.09}]),
                  "USDVND": _series([{"t": 1791478800, "c": 25881}, {"t": 1791219600, "c": 25993}]),
                  "USDVND_VCB": VCB, "USD_CENTRAL": SBVN})
    for k, _, _ in am.DAILY:
        if k.startswith("GOLD_"):
            texts[k] = _series([{"t": 1791478800, "bid": 14180, "ask": 14480}])
    return _exchanges(plan, texts), None, {"model": "claude-sonnet-5-5", "cost_usd": 0.12}


def test_refresh_writes_store_and_status():
    res = am.refresh(NOW, force=True, collect=_collect_ok)
    assert res["status"] == "ok" and res["keys_ok"] == 16
    assert va.series("USD_CENTRAL")["2026-10-09"] == 25629.0
    assert va.series("GOLD_DOJI_RING")["2026-10-09"] == 144_800_000
    st = va.read_status()["mcp"]
    assert st["status"] == "ok" and st["cost_usd"] == 0.12


def test_refresh_gates(monkeypatch):
    boom = lambda *a: pytest.fail("không được gọi")            # noqa: E731
    assert am.refresh(datetime(2026, 10, 9, 10, 0), collect=boom)["status"] == "skipped"   # không phải giờ đặt
    am.refresh(NOW, force=True, collect=_collect_ok)
    assert am.refresh(datetime(2026, 10, 9, 18, 0), stale_h=6, collect=boom)["status"] == "skipped"
    assert am.refresh(datetime(2026, 10, 9, 21, 0), stale_h=6, collect=_collect_ok)["status"] == "ok"
    no_exe = lambda *a: ([], "không tìm thấy", {"no_exe": True})   # noqa: E731
    assert am.refresh(NOW, force=True, collect=no_exe)["status"] == "skipped"
    monkeypatch.setenv("VNSTOCK_ASSETS_MCP", "0")
    assert am.refresh(NOW, force=True, collect=boom)["status"] == "disabled"


def test_plan_backfill_small_sessions():
    sessions = am.plan_backfill(TODAY, FP, SP)
    labels = [s[0] for s in sessions]
    assert labels[:3] == ["XAU", "BZ+CL", "USDVND"] and labels[-1] == "SSI SBVN 3 tháng"
    assert sum(1 for lb in labels if lb.startswith("SJC miếng")) == 3
    assert all(len(plan) <= 2 for _, plan in sessions)
    assert sessions[-1][1][0]["input"] == {"bank": "SBVN", "range": "3m"}


def test_verify_sbvn():
    rows = am.parse_ssi(SBVN, "SBVN")
    assert am.verify_sbvn(rows, {"2026-10-09": 25629.0, "2026-10-08": 25638.0})["verdict"] == "KHỚP"
    assert am.verify_sbvn(rows, {"2026-10-09": 25700.0})["verdict"] == "LỆCH"
    assert am.verify_sbvn(rows, {})["n"] == 0


def test_backfill_runs_sessions_and_records_verify():
    va.write("USD_CENTRAL", [va._row("2026-10-09", 25629.0, "mbk")], today=TODAY,
             fetched_at="2026-10-09T08:00:00")

    def collect(user, system, allowed):
        plan = [p for _, sess in am.plan_backfill(TODAY, *am.prefixes()) for p in sess]
        texts = {"XAU": _series([{"t": 1735750800, "c": 2657.29}]), "USD_CENTRAL": SBVN}
        return _exchanges([p for p in plan if p["tool"] in allowed], texts), None, {}
    logs = []
    rep = am.backfill(NOW, collect=collect, log=logs.append)
    assert rep["XAU"]["ok"] and rep["sbvn_verify"]["verdict"] == "KHỚP"
    assert va.series("XAU")["2025-01-02"] == 2657.29
    assert va.read_status()["sbvn_verify"]["n"] == 1
