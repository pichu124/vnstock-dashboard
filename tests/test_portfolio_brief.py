"""Tests for the position-aware brief: portfolio loader, prompt block,
template parity and the enforce_portfolio_facts guard."""
from __future__ import annotations

import json

import pandas as pd
import pytest

import vnstock_brief as vb


def _wh(tmp_path, close=27.1):
    """Tiny warehouse: portfolio.json (tab schema, buy_price in raw VND) +
    one HPG year file (OHLCV như kho thật, close in nghìn đồng)."""
    (tmp_path / "_meta").mkdir(parents=True)
    (tmp_path / "_meta" / "portfolio.json").write_text(json.dumps([
        {"ticker": "HPG", "quantity": 1000, "buy_price": 25300},
        {"ticker": "", "quantity": 10, "buy_price": 100},       # malformed → skipped
        {"ticker": "ZZZ", "quantity": 0, "buy_price": 100},     # qty 0 → skipped
    ]), encoding="utf-8")
    ydir = tmp_path / "prices" / "ticker=HPG" / "year=2026"
    ydir.mkdir(parents=True)
    pd.DataFrame({
        "time": pd.to_datetime(["2026-07-02", "2026-07-03"]),
        "open": [26.0, close], "high": [26.0, close], "low": [26.0, close],
        "close": [26.0, close], "volume": [1e5, 1e5],
    }).to_parquet(ydir / "prices.parquet")
    return tmp_path


# ── loader ───────────────────────────────────────────────────────────────────

def test_load_portfolio_positions_normalises_units_and_computes_pnl(tmp_path):
    pos = vb.load_portfolio_positions(warehouse=_wh(tmp_path))
    assert len(pos) == 1
    p = pos[0]
    assert p["ticker"] == "HPG"
    assert p["buy_price"] == 25.3          # 25,300 VND → nghìn đồng
    assert p["last_close"] == 27.1
    assert p["pnl_pct"] == pytest.approx(7.1, abs=0.05)


def _wh_one(tmp_path, ticker, buy_price, closes):
    (tmp_path / "_meta").mkdir(parents=True)
    (tmp_path / "_meta" / "portfolio.json").write_text(json.dumps(
        [{"ticker": ticker, "quantity": 100, "buy_price": buy_price}]), encoding="utf-8")
    ydir = tmp_path / "prices" / f"ticker={ticker}" / "year=2026"
    ydir.mkdir(parents=True)
    pd.DataFrame({
        "time": pd.bdate_range("2026-08-03", periods=len(closes)),
        "open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e5,
    }).to_parquet(ydir / "prices.parquet")
    return tmp_path


def test_load_portfolio_positions_high_priced_stock_not_divided(tmp_path):
    """HLB 18/10: giá thật 660 nghìn. Luật cũ `last > 500 ⇒ /1000` ra 0.66 ⇒ PnL ≈ −99,9%."""
    wh = _wh_one(tmp_path, "HLB", 600_000, [445.0] * 30 + [660.0] * 5)
    p = vb.load_portfolio_positions(warehouse=wh)[0]
    assert p["buy_price"] == 600.0
    assert p["last_close"] == 660.0
    assert p["pnl_pct"] == pytest.approx(10.0)


def test_load_portfolio_positions_last_bar_in_raw_vnd(tmp_path):
    """Kho trộn đơn vị: bar cuối lưu VND thô (27.100) giữa chuỗi nghìn đồng."""
    wh = _wh_one(tmp_path, "HPG", 25_300, [26.0] * 20 + [27_100.0])
    p = vb.load_portfolio_positions(warehouse=wh)[0]
    assert p["last_close"] == 27.1
    assert p["pnl_pct"] == pytest.approx(7.1, abs=0.05)


def test_load_portfolio_positions_penny_buy_price_in_vnd(tmp_path):
    """Mã 300 đ: buy 300 VND không > 500 nên luật cũ giữ 300 (= 300 nghìn) ⇒ PnL −99,9%."""
    wh = _wh_one(tmp_path, "AVF", 300, [0.3] * 20 + [0.33])
    p = vb.load_portfolio_positions(warehouse=wh)[0]
    assert p["buy_price"] == 0.3
    assert p["pnl_pct"] == pytest.approx(10.0)


def test_load_portfolio_positions_missing_ticker_data_keeps_position(tmp_path):
    wh = _wh(tmp_path)
    (wh / "_meta" / "portfolio.json").write_text(json.dumps(
        [{"ticker": "NOPQ", "quantity": 100, "buy_price": 50000}]), encoding="utf-8")
    pos = vb.load_portfolio_positions(warehouse=wh)
    assert len(pos) == 1
    assert pos[0]["last_close"] is None and pos[0]["pnl_pct"] is None


def test_load_portfolio_positions_missing_file_and_corrupt(tmp_path):
    assert vb.load_portfolio_positions(warehouse=tmp_path) == []
    (tmp_path / "_meta").mkdir()
    (tmp_path / "_meta" / "portfolio.json").write_text("{corrupt", encoding="utf-8")
    assert vb.load_portfolio_positions(warehouse=tmp_path) == []


def test_load_portfolio_positions_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("VNSTOCK_BRIEF_PORTFOLIO", "0")
    assert vb.load_portfolio_positions(warehouse=_wh(tmp_path)) == []


# ── prompt block + template parity ───────────────────────────────────────────

def _pos():
    return [{"ticker": "HPG", "qty": 1000.0, "buy_price": 25.3,
             "last_close": 27.1, "pnl_pct": 7.1}]


def test_build_prompt_includes_portfolio_block():
    ctx = {"date": "2026-07-06", "time": "15:00", "portfolio": _pos()}
    prompt = vb.build_prompt(ctx, brief_type="afternoon")
    assert "Danh mục đang giữ" in prompt
    assert "HPG: 1,000 cp | vốn 25.30 | hiện 27.10 | lãi +7.1%" in prompt


def test_both_templates_have_portfolio_output_section():
    for bt in ("morning", "afternoon"):
        prompt = vb.build_prompt({"date": "2026-07-06", "time": "09:00"}, brief_type=bt)
        assert "## 📌 Danh mục đang giữ" in prompt, bt


# ── guard ────────────────────────────────────────────────────────────────────

def _ctx():
    return {"portfolio": _pos()}


def test_enforce_portfolio_facts_pins_numbers_and_keeps_action():
    text = ("## 📌 Danh mục đang giữ\n"
            "- HPG: 999 cp | vốn 20.00 | hiện 30.00 | lãi +50.0% → GIỮ — trend còn tốt\n"
            "\n## 💡 Đề xuất giao dịch\n- x")
    out = vb.enforce_portfolio_facts(text, _ctx())
    assert "HPG: 1,000 cp | vốn 25.30 | hiện 27.10 | lãi +7.1%" in out
    assert "→ GIỮ — trend còn tốt" in out          # LLM action preserved
    assert "+50.0%" not in out                     # fabricated pnl gone
    assert vb.enforce_portfolio_facts(out, _ctx()) == out   # idempotent


def test_enforce_portfolio_facts_drops_fabricated_ticker_and_totals():
    text = ("## 📌 Danh mục đang giữ\n"
            "- HPG: 1,000 cp | vốn 25.30 | hiện 27.10 | lãi +7.1% → GIỮ\n"
            "- SSI: 500 cp | lãi +9.0% → MUA THÊM\n"
            "Tổng danh mục lãi +12%\n"
            "## Kết\nx")
    out = vb.enforce_portfolio_facts(text, _ctx())
    assert "SSI" not in out
    assert "Tổng danh mục" not in out
    assert "→ GIỮ" in out


def test_enforce_portfolio_facts_splices_over_denial():
    text = "## 🎯 TLDR\nabc\nKhông có vị thế đang mở\n## 💡 Đề xuất giao dịch\nx"
    out = vb.enforce_portfolio_facts(text, _ctx())
    assert "Không có vị thế" not in out
    assert "HPG: 1,000 cp" in out


def test_enforce_portfolio_facts_inserts_before_recommendations_when_missing():
    text = "## 🎯 TLDR\nabc\n## 💡 Đề xuất giao dịch\nx"
    out = vb.enforce_portfolio_facts(text, _ctx())
    assert out.index("Danh mục đang giữ") < out.index("Đề xuất giao dịch")


def test_enforce_portfolio_facts_noop_without_positions():
    text = "## 📌 Danh mục đang giữ\n- HPG: 999 cp | lãi +50.0%"
    assert vb.enforce_portfolio_facts(text, {}) == text


def test_guard_is_wired_into_apply_brief_guards():
    text = ("## 📌 Danh mục đang giữ\n"
            "- HPG: 999 cp | vốn 20.00 | hiện 30.00 | lãi +50.0% → GIỮ\n")
    out = vb.apply_brief_guards(text, _ctx())
    assert "1,000 cp" in out and "+7.1%" in out
