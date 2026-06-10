"""Tests for vnstock_brief — accuracy evaluator + helpers."""

from __future__ import annotations

from datetime import date as _date

import pandas as pd
import pytest

from datetime import datetime as _datetime, timedelta as _timedelta

from vnstock_brief import (
    _detect_stance, _extract_section, evaluate_brief_accuracy,
    agent_accuracy_summary, _load_vn30_fundamentals, _vn30_fund_block,
    build_prompt, _recommendation_block, _fmt_rec_price,
    _augment_with_live_vnindex, market_data_freshness,
    _auto_refresh_market_overview, _bias_floor_dir, _maybe_reconcile_overdue,
)


# ─── _extract_section ─────────────────────────────────────────────────────────

def test_extract_section_finds_tldr():
    text = "## 🎯 TLDR\nBias: TĂNG.\n## Tổng quan\nBody."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out
    assert "Body" not in out


def test_extract_section_case_insensitive():
    text = "## tldr\nBias: TĂNG."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out


def test_extract_section_returns_empty_when_missing():
    text = "## Other\nNo TLDR here."
    assert _extract_section(text, "TLDR") == ""


# ─── _detect_stance ───────────────────────────────────────────────────────────

def test_detect_stance_explicit_bullish():
    tldr = "Stance ngày mai: TĂNG — giữ vị thế dài."
    assert _detect_stance(tldr) == "bullish"


def test_detect_stance_explicit_bearish():
    tldr = "Stance ngày mai: GIẢM — chuyển phòng thủ."
    assert _detect_stance(tldr) == "bearish"


def test_detect_stance_explicit_neutral():
    tldr = "Stance ngày mai: TRUNG TÍNH — đứng ngoài."
    assert _detect_stance(tldr) == "neutral"


def test_detect_stance_unknown_when_no_signal():
    tldr = "Some text without stance keywords."
    assert _detect_stance(tldr) == "unknown"


def test_detect_stance_canonical_line_beats_fallback():
    """Explicit 'Stance ngày mai: TRUNG TÍNH' wins over bullish keywords elsewhere."""
    tldr = (
        "Phiên trầm lắng. Một số mã tích cực.\n"
        "Stance ngày mai: TRUNG TÍNH — đứng ngoài chờ tín hiệu."
    )
    assert _detect_stance(tldr) == "neutral"


# ─── evaluate_brief_accuracy ──────────────────────────────────────────────────

def _mk_closes() -> pd.Series:
    """Build a deterministic VNINDEX close series for tests."""
    dates = pd.bdate_range("2026-05-20", periods=10)
    values = [1200, 1210, 1215, 1218, 1220, 1230, 1228, 1235, 1240, 1250]
    return pd.Series(values, index=[d.date() for d in dates])


def test_evaluate_returns_unknown_when_no_output():
    out = evaluate_brief_accuracy({"output": "", "brief_date": "2026-05-22"})
    assert out["stance"] == "unknown"
    assert out["match"] is None


def test_evaluate_bullish_correct_match():
    """Bullish brief on day where T+1 close is up → match=True.
    closes: 2026-05-26 (Tue) = 1220, 2026-05-27 (Wed) = 1230 → +0.82% up.
    """
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG — bullish.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bullish"
    assert out["actual"] == "up"
    assert out["match"] is True


def test_evaluate_bearish_incorrect_match():
    """Bearish brief on day where T+1 is up → match=False."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: GIẢM — bearish bias.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bearish"
    assert out["actual"] == "up"
    assert out["match"] is False


def test_evaluate_returns_none_match_when_not_enough_data():
    """Brief at the latest available date can't be evaluated yet."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": closes.index[-1].isoformat(),
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["match"] is None


def test_evaluate_flat_when_under_threshold():
    closes = _mk_closes()
    # Tighten threshold so 0.82% move counts as flat
    brief = {
        "output": "## TLDR\nStance ngày mai: TRUNG TÍNH.",
        "brief_date": "2026-05-26",  # baseline=1220, T+1=1230 → +0.82%
    }
    out = evaluate_brief_accuracy(
        brief, closes=closes, horizon_days=1, neutral_threshold_pct=1.0,
    )
    assert out["actual"] == "flat"
    assert out["match"] is True   # neutral stance vs flat → match


def test_evaluate_horizon_2_uses_2nd_close_after():
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": "2026-05-26",
    }
    out1 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    out2 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=2)
    assert out1["eval_close"] != out2["eval_close"]


# ─── agent_accuracy_summary ───────────────────────────────────────────────────

def test_summary_groups_by_agent_name():
    closes = _mk_closes()
    briefs = [
        {"agent_name": "Groq", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Groq", "brief_date": "2026-05-27",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Mistral", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: GIẢM."},
    ]
    # Patch the loader so the summary uses our deterministic closes
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert "Groq" in out and "Mistral" in out
    assert out["Groq"]["n_total"] == 2
    assert out["Mistral"]["n_total"] == 1


def test_summary_accuracy_is_match_over_evaluated():
    """2026-05-26 → 2026-05-27 up (+0.82%); 2026-05-28 → 2026-05-29 up (+0.55%)."""
    closes = _mk_closes()
    briefs = [
        {"agent_name": "A", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},  # actual up → match
        {"agent_name": "A", "brief_date": "2026-05-28",
         "output": "## TLDR\nStance ngày mai: GIẢM."},  # actual up → miss
    ]
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert out["A"]["n_evaluated"] == 2
    assert out["A"]["n_match"] == 1
    assert out["A"]["accuracy"] == pytest.approx(0.5)


# ─── VN30 fundamentals (D/E, ROE, operating cash flow) ────────────────────────

def _write_fund_parquet(tmp_path, rows: list[dict]):
    import pyarrow as pa
    import pyarrow.parquet as pq
    df = pd.DataFrame(rows)
    p = tmp_path / "fundamentals.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), str(p))
    return p


def test_load_vn30_fundamentals_filters_to_vn30(tmp_path):
    p = _write_fund_parquet(tmp_path, [
        {"ticker": "VCB", "debt_to_equity": 0.8, "roe": 18.0,
         "operating_cf": 12000.0, "updated_at": "2026-06-01"},
        {"ticker": "FPT", "debt_to_equity": 1.1, "roe": 25.0,
         "operating_cf": 8000.0, "updated_at": "2026-06-01"},
        # Not in VN30 → must be excluded
        {"ticker": "ZZZ", "debt_to_equity": 5.0, "roe": 1.0,
         "operating_cf": -50.0, "updated_at": "2026-06-01"},
    ])
    out = _load_vn30_fundamentals(path=p, vn30={"VCB", "FPT"})
    assert set(out.keys()) == {"VCB", "FPT"}
    assert out["VCB"]["de"] == 0.8
    assert out["FPT"]["roe"] == 25.0


def test_load_vn30_fundamentals_skips_all_null_rows(tmp_path):
    p = _write_fund_parquet(tmp_path, [
        {"ticker": "VCB", "debt_to_equity": None, "roe": None,
         "operating_cf": None, "updated_at": "2026-06-01"},
    ])
    out = _load_vn30_fundamentals(path=p, vn30={"VCB"})
    assert out == {}


def test_load_vn30_fundamentals_missing_file_returns_empty(tmp_path):
    assert _load_vn30_fundamentals(path=tmp_path / "nope.parquet") == {}


def test_vn30_fund_block_renders_medians_and_flags():
    funds = {
        "MBB": {"de": 9.0, "roe": 20.0, "ocf": -64000.0, "updated": "2026-06-01"},  # bank
        "HPG": {"de": 1.5, "roe": 12.0, "ocf": -300.0, "updated": "2026-06-01"},    # non-fin
        "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-01"},
    }
    block = _vn30_fund_block(funds)
    assert "VN30 Cơ bản" in block
    assert "Trung vị VN30" in block
    # HPG has the highest D/E among non-financials → must lead the leverage line
    assert "HPG 1.50" in block
    # HPG is the weakest (negative) non-financial CF → flagged + negative count
    assert "HPG" in block and "1 mã âm" in block
    assert "cập nhật 2026-06-01" in block


def test_vn30_fund_block_excludes_financials_from_risk_rankings():
    # Banks/securities dominate D/E and Op.CF purely by scale — they must NOT
    # surface as fundamental risk flags (regression for the "MBB Op.CF -64,972
    # tỷ" mis-flag). ROE is comparable so it still spans all sectors.
    funds = {
        "MBB": {"de": 12.0, "roe": 21.0, "ocf": -64972.0, "updated": "2026-06-01"},
        "VCB": {"de": 9.5,  "roe": 18.0, "ocf": -50000.0, "updated": "2026-06-01"},
        "SSI": {"de": 2.0,  "roe": 14.0, "ocf": -9000.0,  "updated": "2026-06-01"},
        "FPT": {"de": 1.1,  "roe": 25.0, "ocf": 8000.0,   "updated": "2026-06-01"},
        "HPG": {"de": 1.5,  "roe": 12.0, "ocf": -300.0,   "updated": "2026-06-01"},
    }
    block = _vn30_fund_block(funds)
    # No financial ticker, and crucially not the misleading bank mega-cash-flow
    assert "-64,972" not in block
    assert "MBB" not in block and "VCB" not in block and "SSI" not in block
    # Only non-financials rank → HPG weakest Op.CF, exactly 1 negative
    assert "HPG" in block and "1 mã âm" in block
    # ROE median spans all sectors (comparable across financials/non-financials)
    assert "ROE=" in block


def test_vn30_fund_block_empty_when_no_data():
    assert _vn30_fund_block({}) == ""


def test_build_prompt_includes_fundamentals_block():
    ctx = {
        "date": "2026-06-05",
        "time": "15:00",
        "vn30_fundamentals": {
            "VCB": {"de": 0.8, "roe": 18.0, "ocf": 12000.0, "updated": "2026-06-01"},
            "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-01"},
        },
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "VN30 Cơ bản" in prompt
    assert "D/E" in prompt


def test_build_prompt_movers_carry_absolute_price():
    # Watchlist setups must anchor to a REAL price — the movers block has to
    # surface the absolute price (in VND), not just the % change. "last" is
    # stored in thousand VND, so 124.0 → "124,000".
    ctx = {
        "date": "2026-06-08",
        "time": "15:00",
        "vn30_gainers": [
            {"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "Công nghệ", "last": 124.0},
        ],
        "vn30_losers": [
            {"Mã": "TCB", "Giá 1T %": -2.0, "Ngành": "Ngân hàng", "last": 27.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "FPT" in prompt and "Giá 124,000" in prompt
    assert "TCB" in prompt and "Giá 27,000" in prompt


def test_afternoon_watchlist_splits_direction_and_forbids_short_entry():
    # Watchlist must use two direction-specific templates with ordering
    # invariants, and must not frame a bearish idea as a short entry
    # ("SELL ở [giá]") — VN cash market has no retail short-selling.
    prompt = build_prompt({"date": "2026-06-08", "time": "15:00"},
                          brief_type="afternoon")
    assert "không cho NĐT cá nhân bán khống" in prompt
    assert "SL < entry < TP" in prompt
    assert "mục tiêu < hỗ trợ < mức hủy" in prompt
    assert "GIẢM TỶ TRỌNG/TRÁNH nếu thủng" in prompt


def test_afternoon_watchlist_caps_at_real_priced_vn30_tickers():
    # Must not pad to 3 with price-less / non-VN30 placeholders (e.g. "TCX —
    # Giá không có"); fewer setups is fine.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "TỐI ĐA 3 setup" in prompt
    assert "KHÔNG độn cho đủ 3" in prompt
    assert 'KHÔNG thêm dòng kiểu "Giá không có' in prompt


# ─── Market sentiment (tâm lý thị trường) ─────────────────────────────────────

def test_compute_market_sentiment_bullish():
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 65, "ad_ratio": 1.8},
        nn_net=300.0,
        vnindex_tech={"rsi14": 60, "close": 1840, "ma20": 1820,
                      "ma50": 1800, "ma200": 1700, "day_change_pct": 0.6},
        news_sentiment={"total": 100, "pos_pct": 60, "neg_pct": 15, "net_pct": 45},
    )
    assert ms["momentum"] > 40
    assert "Hưng phấn" in ms["mood"] or "Tích cực" in ms["mood"]
    assert ms["n_signals"] == 7


def test_compute_market_sentiment_bearish():
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 25, "ad_ratio": 0.5},
        nn_net=-350.0,
        vnindex_tech={"rsi14": 32, "close": 1700, "ma20": 1750,
                      "ma50": 1780, "ma200": 1820, "day_change_pct": -1.4},
        news_sentiment={"total": 80, "pos_pct": 10, "neg_pct": 55, "net_pct": -45},
    )
    assert ms["momentum"] < -40
    assert "Sợ hãi" in ms["mood"] or "Tiêu cực" in ms["mood"]


def test_compute_market_sentiment_partial_inputs_renormalise():
    """Only breadth available → still returns a reading weighted over it."""
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(breadth={"above_ma200_pct": 60})
    assert ms["n_signals"] == 1
    assert ms["momentum"] > 0


def test_compute_market_sentiment_empty_when_no_signal():
    from vnstock_market_sentiment import compute_market_sentiment
    assert compute_market_sentiment() == {}


def test_market_sentiment_block_renders():
    from vnstock_market_sentiment import compute_market_sentiment
    from vnstock_brief import _market_sentiment_block
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 60, "ad_ratio": 1.5}, nn_net=120.0,
        vnindex_tech={"rsi14": 55, "close": 1840, "ma20": 1820,
                      "ma50": 1800, "ma200": 1700, "day_change_pct": 0.3},
        news_sentiment={"total": 50, "pos_pct": 55, "neg_pct": 20, "net_pct": 35},
    )
    block = _market_sentiment_block(ms)
    assert "Tâm lý thị trường" in block
    assert "momentum" in block
    assert "Tin tức 7N" in block


def test_sector_flow_block_ranks_inflow_outflow():
    from vnstock_brief import _sector_flow_block
    sectors = [
        {"Ngành": "Ngân hàng",    "NN 1T (tỷ)": 1200.0, "GTGD TB (tỷ)": 5400.0},
        {"Ngành": "Bất động sản", "NN 1T (tỷ)": -800.0, "GTGD TB (tỷ)": 3200.0},
        {"Ngành": "Thép",         "NN 1T (tỷ)": 300.0,  "GTGD TB (tỷ)": 1800.0},
        {"Ngành": "Bảo hiểm",     "NN 1T (tỷ)": None,   "GTGD TB (tỷ)": 200.0},
    ]
    block = _sector_flow_block(sectors)
    assert "Dòng tiền ngành" in block
    assert "NN mua ròng" in block and "Ngân hàng" in block
    assert "NN bán ròng" in block and "Bất động sản" in block
    assert "Thanh khoản cao nhất" in block


def test_sector_flow_block_empty():
    from vnstock_brief import _sector_flow_block
    assert _sector_flow_block([]) == ""
    # All-zero NN + no GTGD → nothing to show
    assert _sector_flow_block([{"Ngành": "X", "NN 1T (tỷ)": None, "GTGD TB (tỷ)": 0}]) == ""


def test_build_prompt_includes_sector_flow():
    ctx = {
        "date": "2026-06-08", "time": "15:00",
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": 500.0, "GTGD TB (tỷ)": 4000.0},
            {"Ngành": "BĐS", "NN 1T (tỷ)": -300.0, "GTGD TB (tỷ)": 2000.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Dòng tiền ngành" in prompt


def test_build_prompt_includes_market_sentiment():
    ctx = {
        "date": "2026-06-08", "time": "15:00",
        "market_sentiment": {
            "mood": "📈 Tích cực", "momentum": 35, "n_signals": 2,
            "signals": [
                {"name": "Breadth (% trên MA200)", "value": "60%", "dir": 1},
                {"name": "NN ròng 1D", "value": "+120 tỷ", "dir": 1},
            ],
            "news": {},
        },
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Tâm lý thị trường" in prompt
    assert "momentum" in prompt


# ─── Recommendation block: overdue filtering + price precision ─────────────────

def test_fmt_rec_price_adaptive_precision():
    assert _fmt_rec_price(113.0) == "113"
    assert _fmt_rec_price(13.0) == "13"
    assert _fmt_rec_price(1.23) == "1.23"
    assert _fmt_rec_price(0.39) == "0.390"
    assert _fmt_rec_price(0) == "0"


def test_recommendation_block_excludes_overdue_and_keeps_precision(monkeypatch):
    now = _datetime.now()
    fresh   = (now - _timedelta(days=2)).isoformat()
    overdue = (now - _timedelta(days=34)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "FPT", "action": "buy", "entry_price": 124.0,
         "take_profit": 130.0, "cut_loss": 120.0, "horizon_days": 5,
         "created_at": fresh},
        {"ticker": "CWX", "action": "buy", "entry_price": 0.78,
         "take_profit": 0.94, "cut_loss": 0.69, "horizon_days": 5,
         "created_at": fresh},
        {"ticker": "CFPT2528", "action": "buy", "entry_price": 0.78,
         "take_profit": 0.94, "cut_loss": 0.69, "horizon_days": 5,
         "created_at": overdue},
    ])
    block = _recommendation_block()
    assert "FPT" in block and "entry=124" in block
    # Low-priced instrument keeps decimals instead of collapsing to entry=1
    assert "CWX" in block and "entry=0.780" in block
    # Overdue rec is NOT re-surfaced as a fresh actionable buy
    assert "CFPT2528" not in block


def test_recommendation_block_empty_when_all_overdue(monkeypatch):
    overdue = (_datetime.now() - _timedelta(days=40)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "KSF", "action": "buy", "entry_price": 113.0,
         "take_profit": 129.0, "cut_loss": 105.0, "horizon_days": 5,
         "created_at": overdue},
    ])
    assert _recommendation_block() == ""


# ─── Live intraday VNINDEX augmentation (morning brief uses today's session) ──

def test_augment_with_live_vnindex_folds_today_bar(tmp_path):
    today = _date.today()
    hist = pd.DataFrame({
        "time":  pd.to_datetime([today - _timedelta(days=2), today - _timedelta(days=1)]),
        "open":  [1800.0, 1795.0], "high": [1810.0, 1800.0],
        "low":   [1790.0, 1788.0], "close": [1795.0, 1790.5], "volume": [1, 1],
    })
    live = pd.DataFrame({
        "ticker": ["VNINDEX", "VNINDEX", "FPT"],
        "time":   pd.to_datetime([f"{today} 09:15", f"{today} 11:25", f"{today} 10:00"]),
        "open":   [1790.0, 1788.0, 100.0], "high": [1792.0, 1789.0, 101.0],
        "low":    [1785.0, 1782.0, 99.0],  "close": [1788.0, 1783.4, 100.5],
        "volume": [1000, 2000, 50],
    })
    live.to_parquet(tmp_path / f"bars_{today.isoformat()}.parquet")
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday") is True
    assert pd.to_datetime(out["time"]).dt.date.max() == today
    # Provisional bar: close = last live VNINDEX close (FPT ignored)
    assert float(out["close"].iloc[-1]) == pytest.approx(1783.4)
    assert float(out["high"].iloc[-1]) == pytest.approx(1792.0)


def test_augment_with_live_vnindex_noop_without_file(tmp_path):
    today = _date.today()
    hist = pd.DataFrame({"time": pd.to_datetime([today - _timedelta(days=1)]),
                         "close": [1790.5]})
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday", False) is False
    assert len(out) == 1


def test_augment_with_live_vnindex_skips_when_today_already_present(tmp_path):
    today = _date.today()
    live = pd.DataFrame({
        "ticker": ["VNINDEX"], "time": pd.to_datetime([f"{today} 09:15"]),
        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1788.0], "volume": [1],
    })
    live.to_parquet(tmp_path / f"bars_{today.isoformat()}.parquet")
    hist = pd.DataFrame({"time": pd.to_datetime([today]), "close": [1790.5]})
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday", False) is False
    assert len(out) == 1


def test_build_prompt_marks_intraday_vnindex():
    ctx = {"date": str(_date.today()), "time": "11:30",
           "vnindex_tech": {"close": 1788.0, "prev_close": 1790.5,
                            "day_change_pct": -0.14, "intraday": True}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "PHIÊN ĐANG DIỄN RA" in prompt
    assert "Giá hiện tại" in prompt


# ─── Data freshness: breadth/movers/regime lag vs intraday VNINDEX ────────────

def test_market_data_freshness_flags_stale_overview(tmp_path):
    import json as _json
    p = tmp_path / "market_overview.json"
    p.write_text(_json.dumps({"generated_at": "2026-06-08 09:00:00"}))
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is True
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale_blocks"]


def test_market_data_freshness_fresh_when_same_day(tmp_path):
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 11:00:00"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is False
    assert fr["stale_blocks"] == []


def test_market_data_freshness_prefers_data_date_over_generated_at(tmp_path):
    # generated_at is "today" but the DATA inside is from the prior session →
    # must be flagged stale (the regression: a fresh write time hid old data).
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 12:36:00", "data_date": "2026-06-08"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale"] is True


def test_market_data_freshness_old_file_falls_back_to_warehouse_eod(monkeypatch, tmp_path):
    # File written today but WITHOUT a data_date field: must not look fresh just
    # because generated_at is today — fall back to the warehouse EOD date.
    import vnstock_brief as vb
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 12:58:00"}')
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    fr = vb.market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale"] is True


def test_build_prompt_leader_block_weak_forces_no_leader():
    # Strongest +contrib is only +0.02pp → must NOT be named as accumulation.
    ctx = {"date": "2026-06-09", "time": "11:30",
           "lead_sector": {"name": "CNTT & Phần mềm", "contrib": 0.02},
           "lag_sector": {"name": "Hoá chất", "contrib": -0.40}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Chưa có nhóm dẫn dắt rõ ràng" in prompt
    assert "CHỈ CNTT & Phần mềm" not in prompt   # weak leader not endorsed
    assert "Hoá chất" in prompt                  # strong laggard is named


def test_build_prompt_leader_block_strong_names_only_top():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "lead_sector": {"name": "Ngân hàng", "contrib": 0.30},
           "lag_sector": {"name": "Bất động sản", "contrib": -0.40}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "CHỈ Ngân hàng" in prompt
    assert "Bất động sản" in prompt
    assert "KHÔNG CHỌN NGÀNH KHÁC" in prompt


def test_build_prompt_morning_gtgd_like_for_like_and_hides_incomplete_full_day():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "session_timing": {"signal": "sig", "detail": "det"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7165.4}},
                             "9h-15h": {"VNINDEX": {"gtgd": 7165.4}}},  # full==morning
           "morning_gtgd": {"today": 7165.4, "prev": 9650.4,
                            "avg5": 8000.0, "avg20": 8500.0}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "sáng phiên trước" in prompt and "TB sáng 5 phiên" in prompt
    # full==morning (incomplete) → full-day value line hidden, baselines shown
    assert "GTGD cả ngày:" not in prompt


def test_build_prompt_shows_full_day_gtgd_when_session_closed():
    ctx = {"date": "2026-06-09", "time": "15:30",
           "session_timing": {"signal": "sig", "detail": "det"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7000.0}},
                             "9h-15h": {"VNINDEX": {"gtgd": 15000.0}}},  # afternoon added
           "morning_gtgd": {"today": 7000.0, "prev": 6000.0,
                            "avg5": 6500.0, "avg20": 6800.0}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "GTGD cả ngày: 15,000.0 tỷ" in prompt


def test_build_prompt_renders_freshness_warning():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "freshness": {"data_date": "2026-06-09", "overview_date": "2026-06-08",
                      "stale": True, "stale_blocks": ["độ rộng", "regime"]},
    }
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Độ tươi dữ liệu" in prompt
    assert "2026-06-08" in prompt


def test_build_prompt_no_freshness_warning_when_fresh():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "freshness": {"data_date": "2026-06-09", "overview_date": "2026-06-09",
                      "stale": False, "stale_blocks": []},
    }
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Độ tươi dữ liệu" not in prompt


def test_auto_refresh_noop_when_overview_matches_warehouse(monkeypatch):
    import vnstock_brief as vb
    # Overview already at the latest available (EOD) data → don't churn.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-08")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    assert vb._auto_refresh_market_overview() is False


def test_auto_refresh_runs_when_overview_trails_warehouse(monkeypatch):
    import sys
    import types
    import vnstock_brief as vb

    # Overview is genuinely behind the warehouse EOD data → refresh helps.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-05")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    called = {}
    fake = types.ModuleType("vnstock_runner")
    fake.compute_market_overview = lambda *a, **k: (
        called.update(computed=True) or {"tickers": [{"Mã": "FPT"}],
                                         "sectors": [], "breadth": {}})
    fake.save_market_overview = lambda data, *a, **k: called.update(saved=True)
    monkeypatch.setitem(sys.modules, "vnstock_runner", fake)

    assert vb._auto_refresh_market_overview() is True
    assert called.get("computed") and called.get("saved")


def test_auto_refresh_disabled_by_env(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_REFRESH", "0")
    # Even when behind, the env opt-out short-circuits before any work.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-05")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    assert vb._auto_refresh_market_overview() is False


# ─── Movers timeframe label (Giá 1T % is a 1-week change, not 1 session) ──────

def test_build_prompt_movers_labelled_weekly_not_session():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "vn30_gainers": [{"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "Công nghệ",
                          "last": 124.0}],
        "vn30_losers": [{"Mã": "VIC", "Giá 1T %": -4.8, "Ngành": "Bất động sản",
                         "last": 40.0}],
    }
    prompt = build_prompt(ctx, brief_type="morning")
    # The mislabel that caused "VIC -4.8% phiên sáng" must be gone…
    assert "Top Gainers (1 phiên" not in prompt
    assert "Top Losers (1 phiên" not in prompt
    # …and the real (weekly) timeframe is shown on the lines.
    assert "(1 tuần/5 phiên)" in prompt


def test_morning_template_anomaly_section_forbids_session_label():
    prompt = build_prompt({"date": "2026-06-09", "time": "11:30"},
                          brief_type="morning")
    # The leaking example that taught the model to write "phiên sáng" is gone…
    assert "VIC -3.2% phiên sáng" not in prompt
    # …replaced by the honest weekly framing + explicit prohibition.
    section = prompt.split("Biến động bất thường")[1].split("##")[0]
    assert "1 tuần" in section and "KHÔNG ghi" in section


# ─── Bias floor (TLDR must follow strongly one-sided signals) ─────────────────

def test_bias_floor_dir_logic():
    assert _bias_floor_dir(-67, -5) == "GIẢM"
    assert _bias_floor_dir(-67, None) == "GIẢM"   # momentum alone
    assert _bias_floor_dir(None, -3) == "GIẢM"    # regime alone
    assert _bias_floor_dir(60, 4) == "TĂNG"
    assert _bias_floor_dir(-30, -2) is None       # neither strong → free
    assert _bias_floor_dir(-60, 4) is None        # conflict → don't force


def test_build_prompt_renders_bias_floor():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -5}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "RÀNG BUỘC BIAS" in prompt
    assert "Bias BẮT BUỘC = GIẢM" in prompt
    # The main scenario must also be forced to the bias direction.
    assert "kịch bản CHÍNH" in prompt and "thủng hỗ trợ/đi xuống" in prompt


def test_build_prompt_hides_full_day_and_morning_share_when_intraday():
    # 14:03: partial afternoon makes full > morning AND session_timing.detail
    # leaks "Sáng chiếm 78% cả ngày". Intraday → both must be suppressed.
    ctx = {"date": "2026-06-09", "time": "14:03",
           "vnindex_tech": {"close": 1792.6, "intraday": True},
           "session_timing": {"signal": "🌅 Institutional morning",
                              "detail": "Sáng chiếm `78%` GTGD cả ngày → tổ chức"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7165.4}},
                             "9h-15h": {"VNINDEX": {"gtgd": 9186.0}}},
           "morning_gtgd": {"today": 7165.4, "prev": 9650.4, "avg5": 7600.0}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "GTGD cả ngày:" not in prompt
    assert "78%" not in prompt                       # morning-share leak gone
    assert "Institutional morning" not in prompt     # bogus intraday classification gone
    assert "CHƯA đánh giá được" in prompt
    assert "sáng phiên trước" in prompt              # baselines still shown


def test_build_prompt_shows_session_timing_when_closed():
    # Not intraday (session closed) → the real morning-share signal IS shown.
    ctx = {"date": "2026-06-09", "time": "15:30",
           "session_timing": {"signal": "🌅 Institutional morning",
                              "detail": "Sáng chiếm `60%` GTGD cả ngày"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 9000.0}},
                             "9h-15h": {"VNINDEX": {"gtgd": 15000.0}}},
           "morning_gtgd": {"today": 9000.0, "prev": 8000.0, "avg5": 8500.0}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Institutional morning" in prompt
    assert "GTGD cả ngày: 15,000.0 tỷ" in prompt


def test_build_prompt_no_bias_floor_when_absent():
    prompt = build_prompt({"date": "2026-06-09", "time": "11:30"},
                          brief_type="morning")
    assert "RÀNG BUỘC BIAS" not in prompt


# ─── Auto-reconcile overdue/zombie recs before a brief ────────────────────────

def test_maybe_reconcile_noop_when_no_overdue(monkeypatch):
    import vnstock_brief as vb
    fresh = (_datetime.now() - _timedelta(days=1)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "FPT", "horizon_days": 5, "created_at": fresh}])
    assert vb._maybe_reconcile_overdue() == 0


def test_maybe_reconcile_runs_when_overdue(monkeypatch):
    import sys
    import types
    import vnstock_brief as vb
    overdue = (_datetime.now() - _timedelta(days=40)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "CFPT2528", "horizon_days": 5, "created_at": overdue}])
    fake = types.ModuleType("vnstock_train")
    fake.reconcile_recommendations = lambda verbose=True: {
        "closed": 2, "stale": 1, "still_open": 0}
    monkeypatch.setitem(sys.modules, "vnstock_train", fake)
    assert vb._maybe_reconcile_overdue() == 3   # closed + stale


def test_maybe_reconcile_disabled_by_env(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_RECONCILE", "0")
    assert vb._maybe_reconcile_overdue() == 0


def test_both_templates_require_all_three_mas():
    morning = build_prompt({"date": "2026-06-09", "time": "11:30"}, brief_type="morning")
    afternoon = build_prompt({"date": "2026-06-09", "time": "15:00"}, brief_type="afternoon")
    for p in (morning, afternoon):
        assert "ĐỦ CẢ BA" in p
        assert "MA20" in p and "MA50" in p and "MA200" in p


def test_morning_brief_uses_sector_flow_and_guards_data_gap():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1465.0, "GTGD TB (tỷ)": 5000.0},
            {"Ngành": "Công nghệ", "NN 1T (tỷ)": 1307.0, "GTGD TB (tỷ)": 800.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="morning")
    # The money-flow DATA block is injected …
    assert "Dòng tiền ngành (NN ròng" in prompt
    # … the morning template now tells the agent to USE it …
    assert "**Dòng tiền ngành:**" in prompt
    # … and "Đề xuất bổ sung" must not request data already provided.
    assert "TUYỆT ĐỐI KHÔNG xin lại" in prompt


def test_afternoon_stance_setup_requires_distinct_trigger_and_invalidation():
    # #1: Stance setup must not collapse trigger and invalidation to one level
    # (e.g. entry R1 == hủy R1).
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "2 MỨC KHÁC NHAU" in prompt
    assert "KHÔNG để mức trigger trùng mức hủy" in prompt


def test_afternoon_dan_dat_defers_to_deterministic_gate():
    # #3: close "Dẫn dắt" must honour the ±0.05pp gate, not name a weak sector.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "DÙNG ĐÚNG block" in prompt
    assert "KHÔNG nêu ngành đóng góp <0.05pp làm dẫn dắt" in prompt


def test_data_gap_guard_forbids_already_present_data_both_templates():
    # #2: don't re-request sentiment / foreign-flow that's already in the prompt.
    for bt in ("morning", "afternoon"):
        p = build_prompt({"date": "2026-06-09", "time": "15:00"}, brief_type=bt)
        assert "TÂM LÝ/momentum" in p
        assert "dòng tiền khối ngoại/NN ròng" in p


def test_afternoon_risk_only_uses_block_tickers_with_numbers():
    # #1: risk section must use only VN30-fundamentals tickers (never a ticker
    # outside the data like VCK), cite the real number, and not hand-wave
    # "cần thêm dữ liệu" or mislabel a positive Op.CF as negative.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "dẫn mã ngoài block/ngoài VN30 (vd VCK)" in prompt
    assert "PHẢI ghi kèm CON SỐ" in prompt
    assert 'nói "cần thêm dữ liệu' in prompt
    assert 'gọi "Op.CF âm" cho mã có Op.CF ≥ 0' in prompt


def test_build_prompt_precomputes_weekly_range_position():
    # #2: position in the weekly range is computed, not left to the LLM.
    # close 1793.05 in [1780.71, 1846.71] → ~18.7% → "gần đáy".
    ctx = {"date": "2026-06-09", "time": "15:00",
           "vnindex_tech": {"close": 1793.05, "week_low": 1780.71,
                            "week_high": 1846.71, "day_low": 1790.0,
                            "day_high": 1800.0}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Vị trí range tuần: 19%" in prompt   # round(18.7) = 19
    assert "gần đáy range" in prompt


def test_afternoon_trigger_stays_two_directional():
    # #3: "Trigger ngày mai" must keep both directions, separate from Stance.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "BẮT BUỘC nêu CẢ HAI chiều" in prompt


def test_afternoon_watchlist_nudges_to_use_priced_movers():
    # When movers carry a price, the watchlist must use them instead of bailing
    # with "Cần thêm dữ liệu giá" (observed empty watchlist despite STB/PLX).
    ctx = {"date": "2026-06-09", "time": "15:00",
           "vn30_gainers": [{"Mã": "STB", "Giá 1T %": 2.1, "Ngành": "Ngân hàng",
                             "last": 70.7}],
           "vn30_losers": [{"Mã": "PLX", "Giá 1T %": -1.5, "Ngành": "Năng lượng",
                            "last": 40.85}]}
    prompt = build_prompt(ctx, brief_type="afternoon")
    # the priced movers are present for the agent to anchor on …
    assert "Giá 70,700" in prompt and "Giá 40,850" in prompt
    # … and the instruction forces using them rather than bailing
    assert "BẮT BUỘC dùng ÍT NHẤT 1-2 mã đó làm setup" in prompt
    assert "CHỈ viết đúng 1 dòng" in prompt
