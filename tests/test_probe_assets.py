"""scripts/probe_assets.py — P0 đa tài sản: đo nguồn vàng · dầu · USD (09/10).

Hermetic: HTTP giả qua `Ctx.http`, MCP giả qua `collect`, kho qua tmp_path. Payload
mẫu là số THẬT đo 09/10 qua connector trong phiên Claude: Finhay XAU 4.182,09 ·
SJC miếng 14.180/14.480 nghìn đ/chỉ · SSI SBVN mua 24.398 / bán 26.860."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import date
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probe_assets", _REPO / "scripts" / "probe_assets.py")
pa = importlib.util.module_from_spec(_spec)
sys.modules["probe_assets"] = pa          # @dataclass tra module qua sys.modules
_spec.loader.exec_module(pa)

TODAY = date(2026, 10, 9)
FIN = "mcp__claude_ai_Finhay__"
SSI = "mcp__claude_ai_SSI_MCP__"


def _fake_http(routes: dict):
    """routes: {chuỗi con của URL: (status, text) | Exception}; ghi lại mọi lượt gọi."""
    calls = []

    def http(method, url, *, params=None, data=None, headers=None, timeout=None):
        calls.append((method, url, params, data))
        for key, resp in routes.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp(params) if callable(resp) else resp
        raise ConnectionError("không có route")
    http.calls = calls
    return http


# ── tiện ích ────────────────────────────────────────────────────────────────
def test_scrub_hides_key_and_keeps_cause_only():
    raw = ("HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Max retries exceeded with url: "
           "/fred/series/observations?series_id=X&api_key=SECRET123&file_type=json (Caused by "
           "ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))")
    s = pa.scrub(raw, ("SECRET123",))
    assert "SECRET123" not in s and "Tunnel connection failed: 403 Forbidden" in s
    assert "api_key=***" in pa.scrub("…/x?api_key=SECRET123&a=1")
    assert "SECRET123" not in pa.scrub("token SECRET123 lộ", ("SECRET123",))


def test_iso_and_num_accept_source_formats():
    assert pa._iso("09/10/2026") == "2026-10-09" and pa._iso("2026-10-09T15:00") == "2026-10-09"
    assert pa._num("25,710.00") == 25710.0 and pa._num(".") is None and pa._num(True) is None


# ── FRED ────────────────────────────────────────────────────────────────────
def _fred_route(params):
    if params["sort_order"] == "desc":
        return 200, json.dumps({"observations": [{"date": "2026-10-09", "value": "."},
                                                 {"date": "2026-10-05", "value": "92.41"}]})
    return 200, json.dumps({"observations": [{"date": "1987-05-20", "value": "18.63"}]})


def test_probe_fred_reads_latest_number_and_first_date():
    ctx = pa.Ctx(today=TODAY, http=_fake_http({"stlouisfed": _fred_route}), fred_key="K")
    rows = pa.probe_fred(ctx)
    brent = next(r for r in rows if r["asset"] == "BRENT")
    assert brent["ok"] and brent["value"] == 92.41 and brent["as_of"] == "2026-10-05"
    assert brent["first"] == "1987-05-20" and pa.lag_days(brent, TODAY) == 4
    usd = next(r for r in rows if r["asset"] == "USD_INDEX")
    assert "KHÔNG phải ICE DXY" in usd["note"]


def test_probe_fred_without_key_does_not_call_and_errors_never_leak_key():
    http = _fake_http({})
    rows = pa.probe_fred(pa.Ctx(today=TODAY, http=http, fred_key=""))
    assert not http.calls and all("FRED_API_KEY" in r["error"] for r in rows)
    boom = ConnectionError("Max retries exceeded with url: /x?api_key=SECRET9 (Caused by Timeout)")
    rows = pa.probe_fred(pa.Ctx(today=TODAY, http=_fake_http({"stlouisfed": boom}), fred_key="SECRET9"))
    assert all(not r["ok"] and "SECRET9" not in r["error"] for r in rows)


# ── payload các nguồn ───────────────────────────────────────────────────────
def test_parse_fx_payload_three_shapes():
    assert pa.parse_fx_payload({"rates": {"VND": 25881.5}}) == 25881.5
    assert pa.parse_fx_payload({"usd": {"vnd": 25880}}) == 25880.0
    assert pa.parse_fx_payload({"rates": {"VND": 1.2}}) is None and pa.parse_fx_payload([]) is None


def test_parse_stooq_csv_ok_and_refusal():
    s = pa.parse_stooq_csv("Date,Open,High,Low,Close,Volume\n1990-01-02,1,1,1,401.5,0\n2026-10-08,1,1,1,4144.7,0\n")
    assert s[0] == ("1990-01-02", 401.5) and s[-1] == ("2026-10-08", 4144.7)
    with pytest.raises(ValueError, match="Exceeded"):
        pa.parse_stooq_csv("Exceeded the daily hits limit")


def test_parse_yahoo_chart_ok_and_error():
    payload = {"chart": {"result": [{"meta": {"gmtoffset": -14400},
                                     "timestamp": [1791432000, 1791518400],
                                     "indicators": {"quote": [{"close": [None, 4182.1]}]}}], "error": None}}
    assert pa.parse_yahoo_chart(payload) == [("2026-10-09", 4182.1)]   # 04:00 UTC − 4h
    with pytest.raises(ValueError, match="No data"):
        pa.parse_yahoo_chart({"chart": {"result": None, "error": {"description": "No data found"}}})


def test_parse_sjc_picks_hcm_one_luong_bar():
    payload = {"success": True, "data": [
        {"TypeName": "Vàng nhẫn SJC 99,99", "BranchName": "Hồ Chí Minh", "BuyValue": 140000000, "SellValue": 143000000},
        {"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hà Nội", "BuyValue": 141800000, "SellValue": 144820000},
        {"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hồ Chí Minh", "BuyValue": 141800000, "SellValue": 144800000}]}
    bar = pa.pick_sjc_bar(pa.parse_sjc(payload))
    assert bar["branch"] == "Hồ Chí Minh" and bar["sell"] == 144800000.0


def test_parse_vcb_json_and_xml():
    j = {"Data": [{"currencyCode": "EUR", "sell": "29,799.00"},
                  {"currencyCode": "USD", "cash": "25,680.00", "transfer": "25,710.00", "sell": "26,090.00"}]}
    assert pa.parse_vcb_json(j) == {"cash": 25680.0, "transfer": 25710.0, "sell": 26090.0}
    xml = ('<ExrateList><Exrate CurrencyCode="USD" CurrencyName="US DOLLAR" Buy="25,680.00" '
           'Transfer="25,710.00" Sell="26,090.00" /></ExrateList>')
    assert pa.parse_vcb_xml(xml)["sell"] == 26090.0 and pa.parse_vcb_xml("<x/>") is None


def test_probe_sjc_and_vcb_measure_depth_on_old_dates():
    sjc_ok = (200, json.dumps({"data": [{"TypeName": "Vàng SJC 1L", "BranchName": "Hồ Chí Minh",
                                         "BuyValue": 1, "SellValue": 2}]}))

    def vcb(params):
        if params["date"] < "2025-01-01":
            return 200, json.dumps({"Data": []})
        return 200, json.dumps({"Data": [{"currencyCode": "USD", "cash": "1", "transfer": "2", "sell": "3"}]})
    ctx = pa.Ctx(today=TODAY, http=_fake_http({"sjc.com.vn": sjc_ok, "exchangerates": vcb,
                                               "pXML": (500, "lỗi")}))
    sjc = pa.probe_sjc(ctx)[0]
    assert sjc["ok"] and "2025-10-09✓" in sjc["note"] and "2021-10-08✓" in sjc["note"]
    api, xml = pa.probe_vcb(ctx)
    assert api["ok"] and api["value"] == 3.0 and "2021-10-08✗" in api["note"]
    assert not xml["ok"] and "HTTP 500" in xml["error"]


def test_python_stage_survives_a_crashing_probe():
    def bad(ctx):
        raise RuntimeError("api_key=SECRET77 hỏng")
    rows = pa.run_python_stage(pa.Ctx(today=TODAY, fred_key="SECRET77"), probes=(bad,))
    assert rows[0]["ok"] is False and "SECRET77" not in rows[0]["error"]


def test_pipeline_gold_and_fx_endpoints_measured_one_by_one(monkeypatch):
    import vnstock_macro
    monkeypatch.setattr(vnstock_macro, "_FX_ENDPOINTS",        # conftest dọn về () — dựng lại 2 nấc
                        ("https://open.er-api.com/v6/latest/USD", "https://x.example/usd.json"))
    http = _fake_http({"goldprice.org": (200, json.dumps({"items": [{"xauPrice": 4182.09}]})),
                       "gold-api.com": (200, json.dumps({"price": 99999999})),
                       "er-api.com": (200, json.dumps({"rates": {"VND": 25881.5}}))})
    ctx = pa.Ctx(today=TODAY, http=http)
    gold = pa.probe_gold_endpoints(ctx)
    assert gold[0]["ok"] and gold[0]["value"] == 4182.09
    assert not gold[1]["ok"] and "ngoài khoảng" in gold[1]["error"]
    fx = pa.probe_fx_endpoints(ctx)
    assert fx[0]["ok"] and fx[0]["value"] == 25881.5 and sum(r["ok"] for r in fx) == 1


# ── tầng sponsor (không cần vnstock thật) ───────────────────────────────────
def test_kwargs_for_fills_dates_and_refuses_unknown_required():
    def f(start, end=None, date=None, source="x"):
        return None

    def g(symbol):
        return None
    kw = pa.kwargs_for(f, TODAY)
    assert kw["start"] == "2025-09-04" and kw["end"] == "2026-10-09" and kw["date"] == "2026-10-09"
    assert "source" not in kw and pa.kwargs_for(g, TODAY) is None


def test_call_with_timeout_returns_instead_of_hanging():
    v, e = pa.call_with_timeout(lambda: time.sleep(5), timeout=0.2)
    assert v is None and isinstance(e, TimeoutError)
    assert pa.call_with_timeout(lambda: 7) == (7, None)


def test_summarize_dataframe_reports_rows_and_date_range():
    import pandas as pd
    df = pd.DataFrame({"date": ["2025-01-02", "2026-10-08"], "buy": [1.0, 2.0]})
    s = pa.summarize(df)
    assert "2 dòng" in s and "2025-01-02→2026-10-08" in s


def test_find_modules_walks_files_without_importing(tmp_path, monkeypatch):
    pkg = tmp_path / "fakepkg"
    (pkg / "explorer" / "misc").mkdir(parents=True)
    for f in ("__init__.py", "explorer/__init__.py", "explorer/misc/__init__.py",
              "explorer/misc/gold_price.py", "explorer/quote.py"):
        (pkg / f).write_text("raise RuntimeError('không được import khi dò')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert pa.find_modules("fakepkg") == ["fakepkg.explorer.misc.gold_price"]
    assert pa.find_modules("không_có_gói_này") == []


# ── cache kho ───────────────────────────────────────────────────────────────
def test_probe_local_reads_existing_caches(tmp_path):
    g, m, s = tmp_path / "g.json", tmp_path / "m.json", tmp_path / "s.json"
    g.write_text(json.dumps({"history": {"2026-07-14": 4015.7, "2026-10-08": 4144.7}}), encoding="utf-8")
    m.write_text(json.dumps({"indicators": {"usdvnd": {"source": "er-api",
                                                       "history": {"2026-10-08": 25899.5}}}}), encoding="utf-8")
    rows = pa.probe_local(gold_path=g, macro_path=m, sbv_path=s)
    assert rows[0]["ok"] and rows[0]["first"] == "2026-07-14" and rows[0]["n"] == 2
    assert rows[1]["ok"] and "er-api" in rows[1]["note"]
    assert not rows[2]["ok"]


# ── MCP ─────────────────────────────────────────────────────────────────────
def test_vn_timestamps_match_finhay_daily_bars():
    assert pa.vn_ts(date(2025, 1, 2)) == 1735750800          # nến XAU đầu 2025 (đo 09/10)
    assert pa.ts_date(1791478800) == date(2026, 10, 9)


def test_mcp_plan_is_small_and_market_only():
    plan = pa.mcp_plan(TODAY, FIN, SSI)
    assert len(plan) == 5 * 5 + 9 + 2
    tools = {p["tool"] for p in plan}
    assert tools == {FIN + pa.T_COMMODITY, FIN + pa.T_FOREX, FIN + pa.T_DEALER, SSI + pa.T_SSI_FX}
    assert not any(k in t for t in tools for k in ("portfolio", "order", "account", "asset_summary"))
    system, user = pa.build_mcp_prompt(plan)
    assert not set('|<>%"\n') & set(system)
    assert f"select:{','.join(sorted(tools))}" in user and user.count("\n") == len(plan) + 1


def _series(bars, **extra):
    return json.dumps({"series": bars, **extra})


def test_mcp_results_depth_latest_and_sbv_band():
    plan = pa.mcp_plan(TODAY, FIN, SSI)

    def ex(asset, label, text, is_error=False):
        p = next(p for p in plan if p["asset"] == asset and p["label"] == label)
        return {"name": p["tool"], "input": dict(p["input"]), "text": text, "is_error": is_error}
    sbvn = json.dumps({"status": "ok", "data": {"rates": [
        {"currency_name": "SBVN_VND-USD", "buy": 24407.0, "sell": 26869.0, "trading_date": "08/10/2026"},
        {"currency_name": "SBVN_VND-EUR", "buy": 27318.0, "sell": 30194.0, "trading_date": "09/10/2026"},
        {"currency_name": "SBVN_VND-USD", "buy": 24398.0, "sell": 26860.0, "trading_date": "09/10/2026"}]}})
    exchanges = [
        ex("XAU", "2015", _series([])),
        ex("XAU", "2020", _series([])),
        ex("XAU", "2025", _series([{"t": 1735750800, "c": 2657.29}])),
        ex("XAU", pa.LATEST, _series([{"t": 1791392400, "c": 4144.73}, {"t": 1791478800, "c": 4182.09}])),
        ex("SJC_BAR", pa.LATEST, _series([{"t": 1791478800, "bid": 14180, "ask": 14480}],
                                         currency="VND", unit="chi")),
        ex("USDVND", pa.LATEST, "403 needs auth", is_error=True),
        ex("USD_CENTRAL", pa.LATEST, sbvn),
    ]
    exchanges[2]["input"]["from"] = str(exchanges[2]["input"]["from"])   # model đổi kiểu số
    rows = {r["asset"]: r for r in pa.mcp_results(plan, exchanges, TODAY)}
    xau = rows["XAU"]
    assert xau["ok"] and xau["value"] == 4182.09 and xau["as_of"] == "2026-10-09"
    assert xau["first"] == "2025-01-02" and "2015✗ 2020✗ 2024? 2025✓" in xau["note"]
    sjc = rows["SJC_BAR"]
    assert sjc["value"] == 14480 and "mua 14,180 · bán 14,480 (VND/chi)" in sjc["note"]
    assert not rows["USDVND"]["ok"]
    cen = rows["USD_CENTRAL"]
    assert cen["value"] == 25629.0 and cen["as_of"] == "2026-10-09" and "trần 26,910" in cen["note"]
    assert not rows["USDVND_VCB"]["ok"] and "không gọi" in rows["USDVND_VCB"]["error"]


def test_run_mcp_stage_passes_allowed_tools_and_handles_missing_cli(monkeypatch):
    monkeypatch.delenv(pa.ENV_FINHAY, raising=False)
    monkeypatch.delenv(pa.ENV_SSI, raising=False)
    seen = {}

    def collect(user, system, allowed):
        seen["allowed"] = allowed
        return [], None, {"model": "m", "elapsed_s": 1.0}
    rows, info = pa.run_mcp_stage(TODAY, collect=collect)
    assert FIN + pa.T_DEALER in seen["allowed"] and info["planned"] == 36 and info["called"] == 0
    assert all(not r["ok"] for r in rows)
    rows, _ = pa.run_mcp_stage(TODAY, collect=lambda *a: ([], "không tìm thấy claude", {"no_exe": True}))
    assert len(rows) == 1 and "claude" in rows[0]["error"]


# ── suy ra + kết luận ───────────────────────────────────────────────────────
def test_sjc_premium_matches_hand_calc_09_10():
    assert pa.sjc_premium(4182.09, 25881, 14480) == pytest.approx(10.96, abs=0.05)


def _r(asset, stage, value, as_of, first=None, ok=True, source=None):
    return pa.rec(asset, source or f"{stage}-{asset}", ok=ok, value=value, as_of=as_of,
                  first=first, stage=stage)


def test_derived_lines_premium_band_room_and_central_crosscheck():
    rows = [_r("XAU", "mcp", 4182.09, "2026-10-09"), _r("USDVND", "python", 25881.0, "2026-10-09"),
            _r("SJC_BAR", "mcp", 14480, "2026-10-09"), _r("USD_CENTRAL", "mcp", 25629.0, "2026-10-09"),
            _r("USDVND_VCB", "mcp", 26090.0, "2026-10-09"), _r("USD_CENTRAL", "local", 25600.0, "2026-10-03")]
    text = "\n".join(pa.derived_lines(rows))
    assert "≈ 11.0%" in text and "còn cách trần 26,910 ≈ 3.14%" in text and "lệch +0.11%" in text


def test_conclusions_pick_freshest_and_deepest_and_exit_codes():
    rows = [_r("BRENT", "python", 92.4, "2026-10-05", first="1987-05-20", source="FRED"),
            _r("BRENT", "mcp", 90.7, "2026-10-09", first="2025-01-02", source="Finhay"),
            _r("WTI", "python", None, None, ok=False)]
    lines = pa.conclusions(rows, TODAY)
    assert "tươi nhất Finhay (trễ 0d) · sâu nhất FRED (từ 1987-05-20)" in lines[0]
    assert lines[1].startswith("❌ WTI")
    assert pa.exit_code(rows) == 1 and pa.exit_code(rows[:2]) == 0 and pa.exit_code(rows[2:]) == 2
    out = pa.report(rows, TODAY)
    assert "== Kết luận theo tài sản ==" in out and "từ 1987-05-20" in out


def test_main_only_local_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "probe_local", lambda: [_r("XAU", "local", 4144.7, "2026-10-08")])
    out = tmp_path / "p.json"
    assert pa.main(["--only", "local", "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["results"][0]["value"] == 4144.7
