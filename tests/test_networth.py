"""Tests cho vnstock_networth — net-worth curve NAV danh mục (món DojoAgents 20/07).

Hermetic: core `build_networth` thuần nhận dict/list (không I/O); test loader
end-to-end dùng tmp_path parquet (skip khi thiếu pandas/pyarrow).
"""

import json

import pytest

import vnstock_networth as nw


def _pos(tk="AAA", qty=100, price=10.0, date="2026-01-05"):
    return {"ticker": tk, "quantity": qty, "buy_price": price, "buy_date": date}


IDX = [("2026-01-05", 1000.0), ("2026-01-06", 1010.0),
       ("2026-01-07", 990.0), ("2026-01-08", 1020.0)]


def test_basic_curve_and_rebase():
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-06", 11.0),
                      ("2026-01-07", 9.0), ("2026-01-08", 12.0)]}
    res = nw.build_networth([_pos()], closes, IDX)
    assert res is not None
    assert res["dates"] == [d for d, _ in IDX]
    assert res["nav"] == [1000.0, 1100.0, 900.0, 1200.0]
    assert res["nav_rebased"][0] == 100.0
    assert abs(res["nav_rebased"][-1] - 120.0) < 1e-9
    assert abs(res["index_rebased"][-1] - 102.0) < 1e-9
    assert res["skipped_days"] == 0
    assert res["excluded"] == []


def test_implied_cash_before_second_buy():
    """Vị thế mua SAU: trước buy_date vốn tính như tiền mặt (không nhảy bước
    'nạp tiền' đội lốt lợi nhuận), từ buy_date mark-to-market."""
    closes = {
        "AAA": [("2026-01-05", 10.0), ("2026-01-06", 10.0),
                ("2026-01-07", 10.0), ("2026-01-08", 10.0)],
        "BBB": [("2026-01-05", 20.0), ("2026-01-06", 20.0),
                ("2026-01-07", 25.0), ("2026-01-08", 30.0)],
    }
    poss = [_pos("AAA"), _pos("BBB", qty=10, price=25.0, date="2026-01-07")]
    res = nw.build_networth(poss, closes, IDX)
    # trước 07/01: BBB là cash 250 (10×25) — KHÔNG hưởng đà 20→25 trước khi mua
    assert res["nav"][0] == 1000.0 + 250.0
    assert res["nav"][1] == 1000.0 + 250.0
    # 07/01 mua đúng giá close → NAV liên tục, không bước nhảy
    assert res["nav"][2] == 1000.0 + 250.0
    assert res["nav"][3] == 1000.0 + 300.0


def test_forward_fill_missing_bar():
    """Mã thiếu bar giữa chuỗi → carry close cuối, KHÔNG drop ngày."""
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-08", 12.0)]}
    res = nw.build_networth([_pos()], closes, IDX)
    assert res["skipped_days"] == 0
    assert res["nav"] == [1000.0, 1000.0, 1000.0, 1200.0]


def test_skip_days_before_first_bar():
    """Mã đang giữ CHƯA TỪNG có bar tính đến hôm đó → bỏ ngày + đếm skipped."""
    closes = {"AAA": [("2026-01-07", 9.0), ("2026-01-08", 12.0)]}
    res = nw.build_networth([_pos()], closes, IDX)
    assert res["skipped_days"] == 2
    assert res["dates"] == ["2026-01-07", "2026-01-08"]
    assert res["nav"] == [900.0, 1200.0]


def test_anchor_scale_both_directions():
    """Kho ↔ buy_price lệch lũy thừa 1000 (VND thô vs nghìn đồng) → neo về
    đơn vị buy_price của user."""
    closes = {"VCB": [("2026-01-05", 62.5), ("2026-01-06", 63.0),
                      ("2026-01-07", 62.0), ("2026-01-08", 64.0)]}
    res = nw.build_networth([_pos("VCB", qty=100, price=62500.0)], closes, IDX)
    assert abs(res["nav"][0] - 100 * 62500.0) < 1e-6
    assert abs(res["nav"][-1] - 100 * 64000.0) < 1e-6

    closes2 = {"VCB": [("2026-01-05", 62500.0), ("2026-01-08", 64000.0)]}
    res2 = nw.build_networth([_pos("VCB", qty=100, price=62.5)], closes2, IDX)
    assert abs(res2["nav"][0] - 100 * 62.5) < 1e-6
    assert abs(res2["nav"][-1] - 100 * 64.0) < 1e-6


def test_anchor_no_guess_when_ratio_odd():
    """Tỷ số lệch xa mọi lũy thừa 1000 → giữ 1.0, không đoán bừa."""
    assert nw._anchor_factor(["2026-01-05"], [30.0], "2026-01-05", 10.0) == 1.0
    # cùng đơn vị (ratio ~1) → 1.0
    assert nw._anchor_factor(["2026-01-05"], [10.5], "2026-01-05", 10.0) == 1.0


def test_curve_stats_maxdd_cumulative():
    s = nw.compute_curve_stats([100.0, 120.0, 60.0, 90.0])
    assert abs(s["cumulative_pct"] - (-10.0)) < 1e-9
    assert abs(s["max_drawdown_pct"] - (-50.0)) < 1e-9
    assert s["ann_vol_pct"] > 0
    assert s["n_days"] == 4
    assert s["calmar"] is not None

    # suy biến: 1 điểm / chuỗi phẳng
    assert nw.compute_curve_stats([100.0])["cumulative_pct"] is None
    flat = nw.compute_curve_stats([100.0, 100.0, 100.0])
    assert flat["ann_vol_pct"] == 0.0
    assert flat["sharpe"] is None
    assert flat["max_drawdown_pct"] == 0.0
    assert flat["calmar"] is None


def test_invalid_positions_filtered_to_none():
    assert nw.build_networth([], {}, IDX) is None
    bad = [
        {"ticker": "", "quantity": 5, "buy_price": 1, "buy_date": "2026-01-05"},
        {"ticker": "AAA", "quantity": 0, "buy_price": 1, "buy_date": "2026-01-05"},
        {"ticker": "AAA", "quantity": 1, "buy_price": 0, "buy_date": "2026-01-05"},
        {"ticker": "AAA", "quantity": 1, "buy_price": 1, "buy_date": "bad-date"},
    ]
    assert nw.build_networth(bad, {"AAA": [("2026-01-05", 1.0)]}, IDX) is None


def test_future_buy_date_dropped():
    """buy_date tương lai (gõ nhầm) → loại hẳn, không thành cash vĩnh viễn."""
    poss = [_pos(), _pos("BBB", qty=10, price=5.0, date="2026-02-01")]
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-08", 12.0)],
              "BBB": [("2026-01-05", 5.0)]}
    res = nw.build_networth(poss, closes, IDX, today="2026-01-08")
    assert res["nav"][0] == 1000.0


def test_ticker_without_data_excluded():
    poss = [_pos(), _pos("XXX", qty=10, price=5.0, date="2026-01-05")]
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-08", 12.0)], "XXX": []}
    res = nw.build_networth(poss, closes, IDX)
    assert res["excluded"] == ["XXX"]
    assert res["nav"][0] == 1000.0


def test_index_missing_fallback_axis():
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-06", 11.0)]}
    res = nw.build_networth([_pos()], closes, [])
    assert res is not None
    assert res["index_rebased"] is None
    assert res["dates"] == ["2026-01-05", "2026-01-06"]


def test_single_kept_date_returns_none():
    closes = {"AAA": [("2026-01-08", 12.0)]}
    res = nw.build_networth([_pos()], closes, IDX)
    assert res is None


def test_loader_end_to_end(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    from datetime import date, timedelta

    wh = tmp_path / "wh"
    (wh / "_meta").mkdir(parents=True)
    d0 = date.today() - timedelta(days=5)
    days = [d0 + timedelta(days=i) for i in range(4)]

    def _write(tk, closes):
        pdir = wh / "prices" / f"ticker={tk}" / "year=x"
        pdir.mkdir(parents=True)
        df = pd.DataFrame({
            "time": [str(d) for d in days],
            "open": closes, "high": closes, "low": closes,
            "close": closes, "volume": [1000] * len(days),
        })
        df.to_parquet(pdir / "data.parquet", index=False)

    _write("AAA", [10.0, 11.0, 9.0, 12.0])
    _write("VNINDEX", [1000.0, 1010.0, 990.0, 1020.0])
    (wh / "_meta" / "portfolio.json").write_text(json.dumps(
        [{"ticker": "AAA", "quantity": 100, "buy_price": 10.0,
          "buy_date": str(days[0])}]))

    res = nw.load_networth(wh)
    assert res is not None
    assert len(res["dates"]) == 4
    assert abs(res["nav_rebased"][-1] - 120.0) < 1e-6
    # VNINDEX bar > 500 bị _normalize_prices chia 1000 per-bar — nội bộ nhất
    # quán nên rebase vẫn đúng +2%
    assert res["index_rebased"] is not None
    assert abs(res["index_rebased"][-1] - 102.0) < 0.5


def test_cli_no_portfolio(tmp_path, capsys):
    assert nw.main(["--warehouse", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Chưa có vị thế" in out


def test_summary_parts_hides_risk_stats_when_few_sessions():
    """< 10 phiên → ẩn vol/Sharpe/Calmar (nhiễu thống kê — 'Calmar -16.02'
    trên 2 điểm, verify máy user 20/07); giữ tích lũy/VNINDEX/maxDD."""
    closes = {"AAA": [("2026-01-05", 10.0), ("2026-01-06", 9.0)]}
    idx2 = [("2026-01-05", 1000.0), ("2026-01-06", 990.0)]
    res = nw.build_networth([_pos()], closes, idx2)
    joined = " · ".join(nw.summary_parts(res))
    assert "2 phiên" in joined
    assert "tích lũy -10.0%" in joined
    assert "VNINDEX cùng kỳ -1.0%" in joined
    assert "maxDD" in joined
    assert "vol năm hóa" not in joined
    assert "Sharpe" not in joined.replace("vol/Sharpe/Calmar", "")
    assert "Calmar" not in joined.replace("vol/Sharpe/Calmar", "")
    assert "≥10 phiên" in joined


def test_summary_parts_shows_risk_stats_when_enough_sessions():
    n = 12
    days = [f"2026-01-{d:02d}" for d in range(1, n + 1)]
    closes = {"AAA": [(d, 10.0 + (i % 3) * 0.2) for i, d in enumerate(days)]}
    idx_n = [(d, 1000.0 + i) for i, d in enumerate(days)]
    res = nw.build_networth([_pos(date=days[0])], closes, idx_n)
    joined = " · ".join(nw.summary_parts(res))
    assert f"{n} phiên" in joined
    assert "vol năm hóa" in joined
    assert "Sharpe (rf=0)" in joined
    assert "≥10 phiên" not in joined
