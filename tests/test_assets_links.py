"""P4 đa tài sản (U85): độ nhạy cổ phiếu ↔ vàng/dầu/USD — `vnstock_assets_links`.

Kho giá tổng hợp (seed cố định) với quan hệ ĐÃ BIẾT: PVD = 0,5·Brent(lệch 1 phiên) + 0,8·VNINDEX + nhiễu,
HVN = −0,4·Brent, VHC không dính USD. Phép đo phải tìm lại đúng chiều/độ lớn, và nói "không thấy" khi
không có quan hệ — đúng tinh thần thiết kế §3: danh sách mã là giả thuyết, P4 đo."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import vnstock_assets as va
import vnstock_assets_links as al

TODAY = date(2026, 10, 10)
T = "2026-10-10T09:00:00"


def _sessions(n=130, end=date(2026, 10, 9)):
    out, x = [], end
    while len(out) < n:
        if x.weekday() < 5:
            out.append(x)
        x -= timedelta(days=1)
    return sorted(out)


def _write_ticker(wh, sym, dates, closes):
    d = wh / "prices" / f"ticker={sym}" / "year=2026"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time": pd.to_datetime(dates), "close": closes}).to_parquet(d / "data.parquet")


def _build(tmp_path):
    rng = np.random.default_rng(7)
    days = _sessions()
    n = len(days)
    brent_r = rng.normal(0, 0.02, n)                    # lợi suất Brent theo ngày Mỹ = ngày VN để đơn giản
    mkt_r = rng.normal(0, 0.01, n)
    brent = 90 * np.exp(np.cumsum(brent_r))
    va.write("BRENT", [va._row(d.isoformat(), float(c), "yahoo") for d, c in zip(days, brent)],
             today=TODAY, fetched_at=T)
    usd = 25000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    va.write("USDVND_VCB", [va._row(d.isoformat(), float(c), "vcb") for d, c in zip(days, usd)],
             today=TODAY, fetched_at=T)
    lagged = np.concatenate([[0.0], brent_r[:-1]])      # phiên t phản ứng với Brent ngày t−1
    pvd_r = 0.5 * lagged + 0.8 * mkt_r + rng.normal(0, 0.004, n)
    hvn_r = -0.4 * lagged + 0.9 * mkt_r + rng.normal(0, 0.004, n)
    vhc_r = 0.7 * mkt_r + rng.normal(0, 0.01, n)
    wh = tmp_path / "wh"
    for sym, r in (("VNINDEX", mkt_r), ("PVD", pvd_r), ("HVN", hvn_r), ("VHC", vhc_r)):
        _write_ticker(wh, sym, days, 100 * np.exp(np.cumsum(r)))
    return wh, days


def test_session_returns_drops_data_breaks():
    c = pd.Series([10.0, 10.5, 10500.0, 10600.0], index=pd.to_datetime(["2026-10-05", "2026-10-06",
                                                                           "2026-10-07", "2026-10-08"]))
    r = al.session_returns(c)
    assert list(r.index.strftime("%m-%d")) == ["10-06", "10-08"]           # cú ×1000 đổi đơn vị bị bỏ


def test_aligned_driver_returns_lag_and_weekend():
    lvl = pd.Series([100.0, 101.0, 103.0, 106.0, 110.0],
                    index=pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]))
    sess = pd.to_datetime(["2026-10-02", "2026-10-05", "2026-10-06"])
    same = al.aligned_driver_returns(lvl, sess, lag=False)
    assert same[pd.Timestamp("2026-10-05")] == pytest.approx(np.log(110 / 101))   # gom T7 + CN + T2
    lag = al.aligned_driver_returns(lvl, sess, lag=True)
    assert lag[pd.Timestamp("2026-10-05")] == pytest.approx(np.log(106 / 100))    # ngày < phiên
    assert lag[pd.Timestamp("2026-10-06")] == pytest.approx(np.log(110 / 106))


def test_ols_and_verdicts():
    rng = np.random.default_rng(1)
    x_m, x_d = rng.normal(0, 0.01, 200), rng.normal(0, 0.02, 200)
    y = 0.3 * x_d + 0.9 * x_m + rng.normal(0, 0.003, 200)
    fit = al.ols_driver(y, x_m, x_d)
    assert fit["beta"] == pytest.approx(0.3, abs=0.05) and fit["t"] > 10
    assert al.verdict({"n": 60, "t": 5.0, "beta": 0.3}, 1) == "có, đúng chiều"
    assert al.verdict({"n": 60, "t": 5.0, "beta": 0.3}, -1) == "có, NGƯỢC chiều kỳ vọng"
    assert al.verdict({"n": 60, "t": -3.0, "beta": -0.3}, None) == "có (−)"
    assert al.verdict({"n": 60, "t": 1.2, "beta": 0.1}, 1) == "không thấy"
    assert al.verdict({"n": 20, "t": 9.0, "beta": 0.1}, 1) == "chưa đủ dữ liệu"


def test_compute_recovers_known_links(tmp_path):
    wh, _ = _build(tmp_path)
    res = al.compute(warehouse=wh, today=TODAY)
    rows = {(r["ticker"], r["driver"]): r for r in res["rows"]}
    pvd = rows[("PVD", "BRENT")]
    assert pvd["verdict"] == "có, đúng chiều" and pvd["w60"]["beta"] == pytest.approx(0.5, abs=0.08)
    assert pvd["w60"]["n"] == al.WINDOW and pvd["lag"] is True
    hvn = rows[("HVN", "BRENT")]
    assert hvn["verdict"] == "có, đúng chiều" and hvn["w60"]["beta"] == pytest.approx(-0.4, abs=0.08)
    assert rows[("VHC", "USDVND_VCB")]["verdict"] == "không thấy"
    assert rows[("GAS", "BRENT")]["verdict"] == "chưa đủ dữ liệu"           # không có giá GAS trong kho
    pvd_line = next(ln for ln in al.show(res).splitlines() if ln.strip().startswith("PVD"))
    assert "Dầu Brent (HĐTL)" in pvd_line and "có, đúng chiều" in pvd_line and "1% ⇒ +0." in pvd_line


def test_refresh_writes_cache_and_kill_switch(tmp_path, monkeypatch):
    wh, _ = _build(tmp_path)
    assert al.refresh(warehouse=wh, today=TODAY)["status"] == "ok"
    cached = json.loads((va.META_DIR / al.CACHE_NAME).read_text(encoding="utf-8"))
    assert len(cached["rows"]) == len(al.LINKS) and al.load()["window"] == 60
    monkeypatch.setenv("VNSTOCK_ASSETS_LINKS", "0")
    assert al.refresh(warehouse=wh, today=TODAY) == {"status": "disabled"}


def test_links_tab_renders_table(tmp_path, monkeypatch):
    import sys
    import importlib
    from tests.test_tab_render_smoke import _fake_streamlit
    wh, _ = _build(tmp_path)
    al.refresh(warehouse=wh, today=TODAY)
    st = _fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    sys.modules.pop("dashboard.assets_tab", None)
    mod = importlib.import_module("dashboard.assets_tab")
    mod._render_links(va, None, None)
    df = st.dataframe.call_args.args[0]
    assert list(df["Mã"])[:3] == ["PNJ", "PNJ", "PVD"] and "Beta riêng 60p" in df.columns
    assert any("PVD ← Dầu Brent" in str(c.args[0]) for c in st.caption.call_args_list)
