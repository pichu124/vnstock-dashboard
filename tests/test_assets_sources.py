"""vnstock_assets_sources — parser + fetcher nguồn Python của kho đa tài sản (U82, 09/10).

Hermetic: mạng qua `src.HTTP` giả (conftest chặn mặc định). Số mẫu là số THẬT đo trên 🖥️
desktop 09/10 (`scripts/probe_assets.py` / `probe_nowcast.py`)."""
from __future__ import annotations

import json
import math
from datetime import date

import pytest

import vnstock_assets_sources as src

TODAY = date(2026, 10, 9)


def _http(routes: dict, calls: "list | None" = None):
    def http(method, url, *, params=None, data=None, headers=None, timeout=None):
        if calls is not None:
            calls.append((method, url, params, data))
        for key, resp in routes.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp(url, params) if callable(resp) else resp
        raise ConnectionError("không có route")
    return http


def test_conftest_blocks_network_by_default():
    with pytest.raises(ConnectionError):
        src.fetch_gold_api()


def test_scrub_hides_key_and_keeps_cause():
    raw = ("HTTPSConnectionPool(host='api.stlouisfed.org'): Max retries exceeded with url: /x?api_key=SECRET9 "
           "(Caused by ProxyError('Unable to connect', OSError('Tunnel connection failed: 403 Forbidden')))")
    s = src.scrub(raw, ("SECRET9",))
    assert "SECRET9" not in s and "403 Forbidden" in s
    assert "api_key=***" in src.scrub("/x?api_key=SECRET9&y=1")


def test_iso_and_num():
    assert src.iso("09/10/2026") == "2026-10-09" and src.iso("2026-10-09T08:00") == "2026-10-09"
    assert src.num("25,710.00") == 25710.0 and src.num(".") is None and src.num(float("nan")) is None


def test_fred_parse_and_backfill_params(monkeypatch):
    calls = []
    payload = {"observations": [{"date": "2026-10-06", "value": "125.44"}, {"date": "2026-10-05", "value": "."}]}
    monkeypatch.setattr(src, "HTTP", _http({"stlouisfed": (200, json.dumps(payload))}, calls))
    assert src.fetch_fred("DCOILBRENTEU", "K") == [("2026-10-06", 125.44)]
    src.fetch_fred("DTWEXBGS", "K", start="2006-01-01")
    assert calls[-1][2]["observation_start"] == "2006-01-01" and calls[-1][2]["sort_order"] == "asc"


def test_parse_yahoo_ohlc_skips_empty_close():
    payload = {"chart": {"result": [{"meta": {"gmtoffset": -14400}, "timestamp": [1791432000, 1791518400],
                                     "indicators": {"quote": [{"open": [1, 102.0], "high": [1, 103.5],
                                                               "low": [1, 101.0], "close": [None, 103.17]}]}}]}}
    assert src.parse_yahoo(payload) == [{"date": "2026-10-09", "close": 103.17, "open": 102.0,
                                         "high": 103.5, "low": 101.0}]
    with pytest.raises(ValueError, match="No data"):
        src.parse_yahoo({"chart": {"error": {"description": "No data found"}}})


def test_fetch_yahoo_max_uses_period_range(monkeypatch):
    calls = []
    payload = {"chart": {"result": [{"meta": {}, "timestamp": [1791518400],
                                     "indicators": {"quote": [{"close": [102.29]}]}}]}}
    monkeypatch.setattr(src, "HTTP", _http({"yahoo": (200, json.dumps(payload))}, calls))
    src.fetch_yahoo("DX-Y.NYB", "max")
    src.fetch_yahoo("BZ=F")
    assert "period1=0&period2=" in calls[0][1] and "range=5d" in calls[1][1]


def test_contract_tickers_and_month():
    assert src.contract_tickers("CL", TODAY, 4) == ["CLV26.NYM", "CLX26.NYM", "CLZ26.NYM", "CLF27.NYM"]
    assert src.contract_month("BZZ26") == "2026-12" and src.contract_month("BZF27.NYM") == "2027-01"
    assert src.contract_month("rác") is None


def test_parse_usd_rates_and_fx_day_fallback(monkeypatch):
    assert src.parse_usd_rates({"usd": {"EUR": 0.86, "vnd": 25881, "x": "a", "b": True}}) == {"eur": 0.86, "vnd": 25881.0}
    monkeypatch.setattr(src, "HTTP", _http({"jsdelivr": (404, "nf"),
                                            "currency-api.pages.dev": (200, json.dumps({"usd": {"vnd": 25900}}))}))
    assert src.fetch_fx_day("2026-10-08") == {"vnd": 25900.0}


def test_parse_vcb_and_sjc_units():
    j = {"Data": [{"currencyCode": "USD", "cash": "25,660.00", "transfer": "25,690.00", "sell": "26,070.00"}]}
    assert src.parse_vcb(j) == {"cash": 25660.0, "transfer": 25690.0, "sell": 26070.0}
    sjc = {"data": [{"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hà Nội", "BuyValue": 141800, "SellValue": 144820},
                    {"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hồ Chí Minh", "BuyValue": 141800, "SellValue": 144800}]}
    assert src.parse_sjc(sjc) == {"buy": 141_800_000, "sell": 144_800_000}     # nghìn đ/lượng → đồng
    assert src.to_vnd_luong(144_800_000) == 144_800_000


WEIGHTS_HTML = ("<table><tr><th>Country</th><th>2025</th><th>2026</th></tr>" + "".join(
    f"<tr><th>{n}</th><td>1</td><td>{w}</td></tr>" for n, w in
    [("Euro area", 21.0), ("Canada", 12.8), ("Japan", 5.2), ("Mexico", 14.8), ("China", 10.9),
     ("United Kingdom", 5.2), ("Switzerland", 2.5), ("Australia", 1.4), ("Sweden", 0.5), ("Argentina", 0.5),
     ("Brazil", 1.9), ("Chile", 0.6), ("Colombia", 0.6), ("Hong Kong", 1.3), ("India", 2.9), ("Indonesia", 0.7),
     ("Israel", 1.0), ("Korea", 3.8), ("Malaysia", 1.3), ("Philippines", 0.6), ("Russia", 0.3),
     ("Saudi Arabia", 0.5), ("Singapore", 1.9), ("Taiwan", 2.8), ("Thailand", 1.2), ("Vietnam", 2.5)])
    + "</table>")


def test_parse_fed_weights_latest_year_normalised():
    year, w = src.parse_fed_weights(WEIGHTS_HTML)
    assert year == 2026 and len(w) == 26 and sum(w.values()) == pytest.approx(1.0) and w["vnd"] > 0
    with pytest.raises(ValueError):
        src.parse_fed_weights("<p>bảo trì</p>")


def test_replica_and_nowcast_shift_and_h():
    w = {"eur": 0.5, "jpy": 0.5}
    fx = {"2026-10-01": {"eur": 1.0, "jpy": 100.0}, "2026-10-02": {"eur": 1.1, "jpy": 100.0},
          "2026-10-03": {"eur": 1.1}, "2026-10-05": {"eur": 1.1, "jpy": 110.0}}
    rep = src.replica_index(fx, w)
    assert rep["2026-10-02"] == pytest.approx(math.sqrt(1.1)) and "2026-10-03" not in rep
    est = src.nowcast({"2026-10-01": 120.0}, rep, shift=1)        # neo 01/10 ↔ dẫn 02/10
    assert est["driver_from"] == "2026-10-02" and est["driver_date"] == "2026-10-05" and est["h"] == 1
    assert est["value"] == pytest.approx(120.0 * math.sqrt(1.1))
    assert src.nowcast({}, rep) is None


def test_parse_mbk_central_long_frame():
    import pandas as pd
    df = pd.DataFrame({"last_updated": ["2026-10-08", "2026-10-07", "2026-10-08"],
                       "name": ["Tỷ giá trung tâm (từ 04/01/2016)", "Tỷ giá trung tâm (từ 04/01/2016)", "Tỷ giá VCB"],
                       "value": [25629.0, 25633.0, 26170.0], "unit": ["USD/VNĐ"] * 3})
    assert src.parse_mbk_central(df) == [("2026-10-07", 25633.0), ("2026-10-08", 25629.0)]
    assert src.parse_mbk_central(pd.DataFrame({"a": [1]})) == []


# mbk THÔ (10 dòng cuối, có dòng CN) in bởi `--backfill --steps mbk` 🖥️ 10/10 01:37, và tỷ giá
# trung tâm NHNN báo chí cùng kỳ (chuỗi tăng/giảm liền mạch 25.624 → +12 → +7 → +2 → −7 → −4 → −5).
MBK_RAW = [("2026-09-28", 25630.0), ("2026-09-29", 25627.0), ("2026-09-30", 25624.0),
           ("2026-10-01", 25636.0), ("2026-10-02", 25636.0), ("2026-10-04", 25643.0),
           ("2026-10-05", 25645.0), ("2026-10-06", 25638.0), ("2026-10-07", 25634.0),
           ("2026-10-08", 25629.0)]
NHNN = {"2026-10-01": 25624.0, "2026-10-02": 25636.0, "2026-10-05": 25643.0, "2026-10-06": 25645.0,
        "2026-10-07": 25638.0, "2026-10-08": 25634.0, "2026-10-09": 25629.0}


def test_shift_mbk_dates_matches_official_rate():
    got = dict(src.shift_mbk_dates(MBK_RAW))
    assert {d: got[d] for d in NHNN} == NHNN                       # CN 04/10 → thứ Hai 05/10, đè T6
    assert "2026-09-28" not in got and max(got) == "2026-10-09"    # dòng cuối → ngày làm việc kế


def test_shift_mbk_dates_weekend_rows_and_holiday():
    # mbk có dòng cuối tuần (lùi theo NGÀY LỊCH): dòng CN = số thứ Hai, đè dòng thứ Sáu/T7.
    cal = [("2026-10-02", 25630.0), ("2026-10-03", 25630.0), ("2026-10-04", 25636.0), ("2026-10-05", 25645.0)]
    assert dict(src.shift_mbk_dates(cal)) == {"2026-10-05": 25636.0, "2026-10-06": 25645.0}
    # Nghỉ lễ 02/09 (thứ Tư) không có dòng: số trước lễ sang phiên đầu sau lễ, không rơi vào ngày lễ.
    hol = [("2026-09-01", 26100.0), ("2026-09-03", 26110.0)]
    assert dict(src.shift_mbk_dates(hol)) == {"2026-09-03": 26100.0, "2026-09-04": 26110.0}
    assert src.shift_mbk_dates([("2026-10-09", 1.0)]) == [("2026-10-12", 1.0)]   # thứ Sáu → thứ Hai
    assert src.shift_mbk_dates([]) == []


def test_fetch_fx_latest_dated_reads_file_date(monkeypatch):
    payload = {"date": "2026-10-09", "usd": {"eur": 0.86, "vnd": 25881}}
    monkeypatch.setattr(src, "HTTP", _http({"latest": (200, json.dumps(payload))}))
    assert src.fetch_fx_latest_dated() == ("2026-10-09", {"eur": 0.86, "vnd": 25881.0})
    assert src.fetch_fx_latest() == {"eur": 0.86, "vnd": 25881.0}
