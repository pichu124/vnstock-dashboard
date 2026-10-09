"""scripts/probe_nowcast.py — ước tính HÔM NAY cho chuỗi chậm (USD rộng Fed, dầu giao ngay EIA) +
đo sai số trên lịch sử (P0b đa tài sản, 09/10). Hermetic: HTTP giả qua `Ctx.http`."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("probe_nowcast", _REPO / "scripts" / "probe_nowcast.py")
pn = importlib.util.module_from_spec(_spec)
sys.modules["probe_nowcast"] = pn
_spec.loader.exec_module(pn)
pa = pn.pa

TODAY = date(2026, 10, 9)

WEIGHTS_HTML = """<html><body><table class="pubtables">
<thead><tr><th>Country or Region</th><th>2023</th><th>2024</th><th>2025</th></tr></thead>
<tbody>""" + "".join(
    f"<tr><th scope='row'>{name}</th><td>1.0</td><td>2.0</td><td>{w}</td></tr>"
    for name, w in [("Euro area", 18.0), ("Canada", 13.0), ("Japan", 5.0), ("Mexico", 13.5),
                    ("China", 11.0), ("United Kingdom", 5.0), ("Switzerland", 2.5), ("Australia", 1.4),
                    ("Sweden", 0.5), ("Argentina", 0.5), ("Brazil", 1.9), ("Chile", 0.6),
                    ("Colombia", 0.6), ("Hong Kong", 1.3), ("India", 2.9), ("Indonesia", 0.7),
                    ("Israel", 1.0), ("Korea", 3.8), ("Malaysia", 1.3), ("Philippines", 0.6),
                    ("Russia", 0.3), ("Saudi Arabia", 0.5), ("Singapore", 1.9), ("Taiwan", 2.8),
                    ("Thailand", 1.2), ("Vietnam", 2.5)]) + "</tbody></table></body></html>"


def _bdays(start: date, n: int) -> list:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── trọng số Fed + tỷ giá ───────────────────────────────────────────────────
def test_parse_fed_weights_takes_latest_year_and_normalises():
    year, w = pn.parse_fed_weights(WEIGHTS_HTML)
    assert year == 2025 and len(w) == 26 and w["vnd"] > 0
    assert sum(w.values()) == pytest.approx(1.0) and w["eur"] == pytest.approx(18.0 / 94.3, rel=1e-3)


def test_parse_fed_weights_rejects_page_without_table():
    with pytest.raises(ValueError):
        pn.parse_fed_weights("<html><p>bảo trì</p></html>")


def test_parse_usd_rates_lowercase_positive_only():
    assert pn.parse_usd_rates({"usd": {"EUR": 0.86, "vnd": 25881, "bad": "x", "z": 0}}) == {"eur": 0.86, "vnd": 25881.0}


def test_replica_index_is_weighted_geometric_chain():
    w = {"eur": 0.5, "jpy": 0.5}
    fx = {"2026-10-01": {"eur": 1.0, "jpy": 100.0}, "2026-10-02": {"eur": 1.1, "jpy": 100.0},
          "2026-10-03": {"eur": 1.1}}                     # thiếu 50% trọng số ⇒ bỏ ngày
    rep = pn.replica_index(fx, w)
    assert rep["2026-10-01"] == 1.0 and rep["2026-10-02"] == pytest.approx(math.sqrt(1.1))
    assert "2026-10-03" not in rep


# ── sai số ước tính ─────────────────────────────────────────────────────────
def test_nowcast_errors_zero_when_driver_tracks_official_and_shift_detected():
    days = _bdays(date(2026, 6, 1), 60)
    official = {d: 120 * (1 + 0.001 * i) ** 1 for i, d in enumerate(days)}
    # chuỗi dẫn = chính thức nhưng ghi lùi 1 ngày lịch (giờ chốt khác) ⇒ cần lệch pha +1
    driver = {(date.fromisoformat(d) + timedelta(days=1)).isoformat(): v / 120 for d, v in official.items()}
    shift, st = pn.best_shift(official, driver)
    assert shift == 1 and st[1]["med"] == 0 and st[5]["p90"] == 0


def test_err_stats_and_verdict_thresholds():
    st = pn.err_stats([0.1, -0.2, 0.05, 0.3, -0.1])
    assert st["n"] == 5 and st["med"] == 0.1 and st["max"] == 0.3
    assert pn.verdict({5: {"p90": 0.1}}, "usd", 5).startswith("TỐT")
    assert pn.verdict({5: {"p90": 0.3}}, "usd", 5).startswith("TẠM")
    assert pn.verdict({3: {"p90": 5.0}}, "oil", 3).startswith("KHÔNG NÊN")
    assert pn.verdict({3: None}, "oil", 3) == "chưa đủ dữ liệu"


def test_nowcast_today_anchors_latest_official_with_driver():
    official = {"2026-10-02": 121.38, "2026-09-25": 121.0}
    driver = {"2026-09-25": 1.0, "2026-10-02": 1.0, "2026-10-09": 1.01}
    t = pn.nowcast_today(official, driver)
    assert t["anchor_date"] == "2026-10-02" and t["driver_date"] == "2026-10-09"
    assert t["value"] == pytest.approx(121.38 * 1.01)


# ── đường cong HĐTL + OPEC ──────────────────────────────────────────────────
def test_contract_tickers_wrap_year():
    tk = pn.contract_tickers("CL", TODAY, n=4)
    assert tk == [("10/2026", "CLV26.NYM"), ("11/2026", "CLX26.NYM"),
                  ("12/2026", "CLZ26.NYM"), ("01/2027", "CLF27.NYM")]


def test_curve_spreads_backwardation():
    pts = [{"label": f"{m}", "close": c} for m, c in zip(range(6), [103.0, 100.0, 98.0, 97.0, 96.0, 95.0])]
    sp = pn.curve_spreads(pts)
    assert sp["m1_m2"]["usd"] == 3.0 and sp["m1_m6"]["usd"] == 8.0 and sp["shape"].startswith("BACKWARDATION")
    assert pn.curve_spreads(pts[:1]) == {}


def test_parse_opec_xml_sorted():
    xml = '<BasketList><BasketPrice data="2026-10-08" val="101.5" /><BasketPrice data="2026-10-07" val="99.1" /></BasketList>'
    assert pn.parse_opec_xml(xml) == [("2026-10-07", 99.1), ("2026-10-08", 101.5)]


# ── các phần với HTTP giả ───────────────────────────────────────────────────
def _http(routes):
    def http(method, url, *, params=None, data=None, headers=None, timeout=None):
        for key, resp in routes.items():
            if key in url:
                return resp(url, params) if callable(resp) else resp
        raise ConnectionError("không có route")
    return http


def test_part_usd_end_to_end_small(monkeypatch):
    monkeypatch.setattr(pn, "USD_DAYS", 20)
    days = [TODAY - timedelta(days=i) for i in range(20, -1, -1)]
    _, w = pn.parse_fed_weights(WEIGHTS_HTML)
    base = {c: 10.0 for c in w}

    def rates_for(d: date):
        k = (d - days[0]).days
        return {c: v * (1 + 0.001 * k) for c, v in base.items()}   # USD mạnh dần 0,1%/ngày

    def fx(url, params):
        ds = url.split("@")[1].split("/")[0] if "@" in url else url.split("//")[1].split(".")[0]
        if ds == "latest":
            return 200, json.dumps({"usd": rates_for(TODAY)})
        return 200, json.dumps({"usd": rates_for(date.fromisoformat(ds))})

    def fred(url, params):
        obs = [{"date": d.isoformat(), "value": str(100 * (1 + 0.001 * (d - days[0]).days))}
               for d in days[:-3] if d.weekday() < 5]
        return 200, json.dumps({"observations": obs[::-1]})
    ctx = pa.Ctx(today=TODAY, fred_key="K",
                 http=_http({"federalreserve.gov": (200, WEIGHTS_HTML), "stlouisfed": fred,
                             "currency-api": fx}))
    res = pn.part_usd(ctx)
    assert res["n_ccy"] == 26 and res["weights_year"] == 2025 and res["shift"] == 0
    assert res["stats"][1]["p90"] < 0.01
    assert res["today"]["driver_date"] == TODAY.isoformat()
    assert res["today"]["value"] == pytest.approx(100 * (1 + 0.001 * 20), rel=1e-4)
    assert "ƯỚC TÍNH" in pn.report({"usd": res}, TODAY)


def test_part_usd_without_key_or_weights():
    assert "FRED_API_KEY" in pn.part_usd(pa.Ctx(today=TODAY, fred_key=""))["error"]
    ctx = pa.Ctx(today=TODAY, fred_key="K", http=_http({"federalreserve.gov": (503, "bảo trì")}))
    assert pn.part_usd(ctx)["error"].startswith("trọng số Fed")


def test_part_curve_keeps_fresh_contracts_only():
    def chart(url, params):
        fresh = "CLX26" in url or "CLZ26" in url
        ts = 1791518400 if fresh else 1780000000        # 09/10 vs 05/2026 (đáo hạn cũ)
        close = 91.0 if "CLX26" in url else 89.5
        return 200, json.dumps({"chart": {"result": [{"meta": {"gmtoffset": -14400}, "timestamp": [ts],
                                                      "indicators": {"quote": [{"close": [close]}]}}]}})
    ctx = pa.Ctx(today=TODAY, http=_http({"yahoo": chart}))
    res = pn.part_curve(ctx)
    wti = res["curves"]["WTI"]
    assert [p["ticker"] for p in wti["points"]] == ["CLX26.NYM", "CLZ26.NYM"]
    assert wti["spreads"]["m1_m2"]["usd"] == 1.5
    assert pn.exit_code({"curve": res}) == 0


def test_exit_code_partial():
    assert pn.exit_code({"usd": {"part": "usd", "error": "x"}, "opec": {"part": "opec", "last": 1}}) == 1
    assert pn.exit_code({"usd": {"part": "usd", "error": "x"}}) == 2
