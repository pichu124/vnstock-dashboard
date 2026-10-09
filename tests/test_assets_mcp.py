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
    assert {p["key"] for p in plan} >= {"GOLD_BTMH_RING", "USD_SBV_REF", "XAU"}
    assert "USD_CENTRAL" not in {p["key"] for p in plan}          # SBVN ≠ tỷ giá trung tâm (10/10)
    system, user = am.build_prompt(plan)
    assert not set('|<>%"\n') & set(system) and user.count("\n") == len(plan) + 1


def test_parse_finhay_commodity_and_dealer_units():
    rows = am.parse_finhay(_series([{"t": 1791478800, "o": 4144.68, "h": 4207.51, "l": 4141.84, "c": 4182.09}]), False)
    assert rows == [{"date": "2026-10-09", "close": 4182.09, "open": 4144.68, "high": 4207.51,
                     "low": 4141.84, "source": "finhay"}]
    d = am.parse_finhay(_series([{"t": 1791478800, "bid": 14180, "ask": 14480}], unit="chi"), True)
    assert d[0]["close"] == d[0]["ask"] == 144_800_000 and d[0]["bid"] == 141_800_000


def test_parse_ssi_sbvn_reference_rate_and_vcb():
    rows = am.parse_ssi(SBVN, "SBVN")
    assert [r["date"] for r in rows] == ["2026-10-08", "2026-10-09"]
    assert rows[-1] == {"date": "2026-10-09", "close": 26860.0, "bid": 24398.0, "ask": 26860.0,
                        "source": "ssi"}
    v = am.parse_ssi(VCB, "VCB")[0]
    assert v["close"] == 26090 and v["bid"] == 25710 and v["source"] == "ssi"


TRUNCATED = ("Error: MCP tool \"get_dealer_product_history\" response (37,412 tokens) exceeds maximum "
             "allowed tokens (25,000). Please use pagination, filtering, or limit parameters")


def test_rows_from_exchanges_matches_and_reports_errors():
    plan = am.plan_daily(TODAY, FP, SP)
    ex = _exchanges(plan, {"XAU": _series([{"t": 1791478800, "c": 4182.09}]),
                           "WTI": "ERR 401", "USD_SBV_REF": SBVN, "GOLD_SJC_BAR": _series([]),
                           "GOLD_PNJ_BAR": TRUNCATED,
                           "GOLD_PNJ_RING": json.dumps({"status": "error", "error": "range too large"})})
    ex[0]["input"]["from"] = str(ex[0]["input"]["from"])          # model đổi kiểu số
    rows, errors = am.rows_from_exchanges(plan, ex)
    assert set(rows) == {"XAU", "USD_SBV_REF"}
    assert errors["WTI"].startswith("ERR") and errors["GOLD_SJC_BAR"].startswith("kết quả rỗng")
    assert errors["GOLD_PNJ_BAR"].startswith("không đọc được kết quả") and "exceeds maximum" in errors["GOLD_PNJ_BAR"]
    assert errors["GOLD_PNJ_RING"] == "nguồn báo lỗi: range too large"
    assert errors["BRENT"] == "model không gọi tool này"


def test_rows_from_exchanges_same_key_many_windows():
    """Backfill SBVN 3 lượt cùng bank khác toDate: ghép đủ cả 3, không lượt nào nuốt lượt khác."""
    plan = dict(am.plan_backfill(TODAY, FP, SP))[f"SSI SBVN {am.SBVN_MONTHS} tháng"]
    texts = [json.dumps({"status": "ok", "data": {"rates": [
        {"currency_name": "SBVN_VND-USD", "buy": 24400.0 + i, "sell": 26860.0 + i, "trading_date": d}]}})
        for i, d in enumerate(("09/10/2026", "09/09/2026", "10/08/2026"))]
    ex = [{"name": p["tool"], "input": dict(p["input"]), "text": t, "is_error": False}
          for p, t in zip(plan, texts)]
    rows, errors = am.rows_from_exchanges(plan, ex)
    assert sorted(r["date"] for r in rows["USD_SBV_REF"]) == ["2026-08-10", "2026-09-09", "2026-10-09"]
    ex[1]["text"] = TRUNCATED
    rows, errors = am.rows_from_exchanges(plan, ex)
    assert len(rows["USD_SBV_REF"]) == 2 and "exceeds" in errors["USD_SBV_REF"]   # tháng hỏng không lặng lẽ


def _collect_ok(user, system, allowed):
    plan = am.plan_daily(TODAY, *am.prefixes())
    texts = {k: _series([{"t": 1791478800, "c": 100.5}]) for k in ("BRENT", "WTI")}
    texts.update({"XAU": _series([{"t": 1791478800, "c": 4182.09}]),
                  "USDVND": _series([{"t": 1791478800, "c": 25881}, {"t": 1791219600, "c": 25993}]),
                  "USDVND_VCB": VCB, "USD_SBV_REF": SBVN})
    for k, _, _ in am.DAILY:
        if k.startswith("GOLD_"):
            texts[k] = _series([{"t": 1791478800, "bid": 14180, "ask": 14480}])
    return _exchanges(plan, texts), None, {"model": "claude-sonnet-5-5", "cost_usd": 0.12}


def test_refresh_writes_store_and_status():
    res = am.refresh(NOW, force=True, collect=_collect_ok)
    assert res["status"] == "ok" and res["keys_ok"] == 16
    assert va.series("USD_SBV_REF")["2026-10-09"] == 26860.0 and not va.series("USD_CENTRAL")
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


def test_plan_backfill_small_windows():
    """10/10 🖥️: SJC miếng 3–4 năm/lượt và SBVN 3m vượt trần ~25k token ⇒ "rỗng". Nay mỗi lượt
    ≤1 năm (Finhay) / 1 tháng (SSI), mỗi phiên ≤2 lượt Finhay."""
    sessions = am.plan_backfill(TODAY, FP, SP)
    labels = [s[0] for s in sessions]
    assert labels[:3] == ["XAU", "BZ+CL", "USDVND"] and labels[-1] == "SSI SBVN 3 tháng"
    sjc = [p for lb, plan in sessions if lb.startswith("SJC miếng") for p in plan]
    years = [am.ts_date(p["input"]["from"])[:4] for p in sjc]
    assert years == [str(y) for y in range(2015, 2027)]
    assert all(p["input"]["to"] - p["input"]["from"] <= 366 * 86400 for p in sjc)
    assert all(len(plan) <= 2 for lb, plan in sessions if not lb.startswith("SSI"))
    sb = sessions[-1][1]
    assert [p["input"]["toDate"] for p in sb] == ["09/10/2026", "09/09/2026", "10/08/2026"]
    assert {p["input"]["range"] for p in sb} == {"1m"} and {p["key"] for p in sb} == {"USD_SBV_REF"}


# Số THẬT: SSI SBVN 05–09/10 (đo 10/10) · tỷ giá trung tâm NHNN báo chí: 05/10 25.636,
# 06/10 25.643, 07/10 25.638, 08/10 25.634, 09/10 25.629.
SBVN_WEEK = [("2026-10-05", 24405, 26867), ("2026-10-06", 24411, 26875), ("2026-10-07", 24413, 26877),
             ("2026-10-08", 24407, 26869), ("2026-10-09", 24398, 26860)]
OFFICIAL = {"2026-10-05": 25636.0, "2026-10-06": 25643.0, "2026-10-07": 25638.0,
            "2026-10-08": 25634.0, "2026-10-09": 25629.0}


def _sbvn_rows(week=SBVN_WEEK):
    return [{"date": d, "close": s, "bid": b, "ask": s, "source": "ssi"} for d, b, s in week]


def ruler_case(lag: int, n: int = 30):
    """Chuỗi tổng hợp: trung tâm O tăng đều (không trùng số), thước giữa SBVN = O cùng phiên 1/3
    số phiên và = O phiên trước 2/3 (đúng dạng đo 10/10), kho K(D_j) = O(D_{j+lag})."""
    from datetime import date as _d, timedelta as _td
    days, x = [], _d(2026, 8, 24)
    while len(days) < n + 2:
        if x.weekday() < 5:
            days.append(x.isoformat())
        x += _td(days=1)
    o = [25600.0 + 3 * i for i in range(len(days))]
    mid = [o[i] if i % 3 == 0 or i == 0 else o[i - 1] for i in range(n)]
    sbvn = [{"date": days[i], "close": mid[i] + 1231, "bid": mid[i] - 1231, "ask": mid[i] + 1231,
             "source": "ssi"} for i in range(n)]
    kho = {days[j]: o[j + lag] for j in range(n) if 0 <= j + lag < len(o)}
    return sbvn, kho


@pytest.mark.parametrize("lag,verdict", [(0, "mbk ĐÚNG ngày"), (1, "mbk ghi LÙI 1 phiên"),
                                         (-1, "mbk ghi TIẾN 1 phiên")])
def test_verify_central_tells_lag_with_mixed_ruler(lag, verdict):
    """Thước giữa SBVN trễ lẫn (cùng phiên / phiên trước). 10/10 phép so từng lệch riêng gọi kho
    ĐÚNG là "LÙI 1 phiên" (lệch +1 khớp nhiều nhất) ⇒ nay chấm giả thuyết bằng cặp (D−L, D−L−1)."""
    res = va.verify_central(*ruler_case(lag))
    assert res["best_lag"] == lag and res["verdict"] == verdict
    assert res["by_lag"][str(lag)]["rate"] == 1.0
    if lag == 0:
        assert res["by_shift"]["1"]["exact"] > res["by_shift"]["0"]["exact"]   # cái bẫy vòng trước


def test_verify_central_real_week_and_floors():
    off = {**OFFICIAL, "2026-10-02": 25636.0}
    res = va.verify_central(_sbvn_rows(), off)
    assert res["by_lag"]["0"] == {"n": 4, "hit": 3, "rate": 0.75}   # 07/10: 25.645 vs 25.638/25.643
    assert res["verdict"].startswith("chưa rõ")                                # 5 phiên < sàn 10
    assert va.verify_central(_sbvn_rows(), {})["n"] == 0


def test_backfill_runs_sessions_and_records_verify():
    va.write("USD_CENTRAL", [va._row(d, v, "mbk") for d, v in OFFICIAL.items()], today=TODAY,
             fetched_at="2026-10-09T08:00:00")
    sbvn = json.dumps({"status": "ok", "data": {"rates": [
        {"currency_name": "SBVN_VND-USD", "buy": float(b), "sell": float(s),
         "trading_date": f"{d[8:]}/{d[5:7]}/{d[:4]}"} for d, b, s in SBVN_WEEK]}})

    def collect(user, system, allowed):
        plan = [p for _, sess in am.plan_backfill(TODAY, *am.prefixes()) for p in sess]
        texts = {"XAU": _series([{"t": 1735750800, "c": 2657.29}]), "USD_SBV_REF": sbvn,
                 "GOLD_SJC_BAR": _series([{"t": 1451581200, "bid": 3255, "ask": 3292}])}
        return _exchanges([p for p in plan if p["tool"] in allowed], texts), None, {}
    logs = []
    rep = am.backfill(NOW, collect=collect, log=logs.append)
    assert rep["XAU"]["ok"] and rep["central_verify"]["best_lag"] == 0
    assert va.series("XAU")["2025-01-02"] == 2657.29
    assert va.series("GOLD_SJC_BAR")["2016-01-01"] == 32_920_000          # 3.292 nghìn đ/chỉ
    assert va.series("USD_SBV_REF")["2026-10-09"] == 26860.0
    assert va.central_dating()["by_lag"]["0"]["hit"] == 3             # đo lại từ kho, không mạng


def test_backfill_only_runs_selected_keys():
    seen = []

    def collect(user, system, allowed):
        seen.append(user)
        return [], "không có lượt gọi tool nào trả kết quả", {}
    am.backfill(NOW, collect=collect, log=lambda *_: None, only={"USD_SBV_REF"})
    assert len(seen) == 1 and "SBVN" in seen[0] and "GOLD_" not in seen[0]
