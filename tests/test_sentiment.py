"""Tests for vnstock_sentiment — cache, attach, aggregate."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import vnstock_sentiment as snt
from vnstock_sentiment import (
    _SENTIMENT_MAP, _item_hash, attach_sentiments, scored_count,
    ticker_sentiment_summary, available_provider,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets a fresh sentiment cache DB."""
    db = tmp_path / "sentiment.db"
    monkeypatch.setattr(snt, "SENTIMENT_DB_PATH", db)
    yield db


# ─── Sentiment mapping ────────────────────────────────────────────────────────

def test_sentiment_map_covers_vn_and_en():
    """All three sentiment values present, plus both VN and EN keys."""
    vals = set(_SENTIMENT_MAP.values())
    assert vals == {"positive", "negative", "neutral"}
    assert "tích cực" in _SENTIMENT_MAP
    assert "positive" in _SENTIMENT_MAP


# ─── _item_hash ──────────────────────────────────────────────────────────────

def test_item_hash_stable():
    item = {"news_title": "VCB tăng giá", "ticker": "VCB"}
    h1 = _item_hash(item)
    h2 = _item_hash(item)
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) >= 8


def test_item_hash_distinguishes_items():
    a = {"news_title": "VCB tăng giá", "ticker": "VCB"}
    b = {"news_title": "VCB giảm giá", "ticker": "VCB"}
    assert _item_hash(a) != _item_hash(b)


# ─── available_provider ──────────────────────────────────────────────────────

def test_available_provider_returns_none_when_no_keys(monkeypatch):
    for env in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert available_provider() is None


def test_available_provider_returns_first_set(monkeypatch):
    for env in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    # 29/09: nấc Cerebras (gemma-4-31b) đã GỠ khỏi thang — dùng nấc Groq.
    monkeypatch.setenv("GROQ_API_KEY", "abc123")
    out = available_provider()
    assert out is not None
    assert "groq" in out.lower()


# ─── attach_sentiments ───────────────────────────────────────────────────────

def test_attach_sentiments_empty_db_returns_blank():
    news = [{"news_title": "A", "ticker": "VCB"}, {"news_title": "B", "ticker": "FPT"}]
    out = attach_sentiments(news)
    assert all(n["_sentiment"] == "" for n in out)


def test_attach_sentiments_reads_cached_values(monkeypatch):
    """Pre-seed the DB then verify lookup."""
    item = {"news_title": "VCB lãi", "ticker": "VCB"}
    h = _item_hash(item)

    # Manually seed the cache via the same DB path
    conn = sqlite3.connect(str(snt.SENTIMENT_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_sentiment (
            item_hash TEXT PRIMARY KEY,
            sentiment TEXT,
            ticker TEXT,
            scored_at TEXT,
            provider TEXT
        )
    """)
    conn.execute(
        "INSERT INTO news_sentiment VALUES (?,?,?,?,?)",
        (h, "positive", "VCB", "2026-01-01", "test"),
    )
    conn.commit()
    conn.close()

    out = attach_sentiments([item])
    assert out[0]["_sentiment"] == "positive"


# ─── scored_count ────────────────────────────────────────────────────────────

def test_scored_count_zero_for_empty_db():
    news = [{"news_title": "A", "ticker": "VCB"}]
    assert scored_count(news) == 0


def test_scored_count_counts_present():
    item1 = {"news_title": "A", "ticker": "VCB"}
    item2 = {"news_title": "B", "ticker": "VCB"}

    conn = sqlite3.connect(str(snt.SENTIMENT_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_sentiment (
            item_hash TEXT PRIMARY KEY,
            sentiment TEXT,
            ticker TEXT,
            scored_at TEXT,
            provider TEXT
        )
    """)
    conn.execute(
        "INSERT INTO news_sentiment VALUES (?,?,?,?,?)",
        (_item_hash(item1), "positive", "VCB", "2026-01-01", "t"),
    )
    conn.commit()
    conn.close()

    assert scored_count([item1, item2]) == 1


# ─── ticker_sentiment_summary ─────────────────────────────────────────────────

def test_summary_empty_when_no_news():
    out = ticker_sentiment_summary([])
    assert out == []


def test_summary_strong_positive_signal():
    """3 positive vs 0 negative → strong_pos label."""
    from datetime import date
    today = date.today().isoformat()
    news = [
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": today},
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": today},
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": today},
    ]
    out = ticker_sentiment_summary(news)
    assert len(out) == 1
    assert out[0]["Mã"] == "VCB"
    assert "Tích cực mạnh" in out[0]["Tín hiệu"]


def test_summary_strong_negative_signal():
    from datetime import date
    today = date.today().isoformat()
    news = [
        {"ticker": "VIC", "_sentiment": "negative", "_date_sort": today},
        {"ticker": "VIC", "_sentiment": "negative", "_date_sort": today},
        {"ticker": "VIC", "_sentiment": "negative", "_date_sort": today},
    ]
    out = ticker_sentiment_summary(news)
    assert "Tiêu cực mạnh" in out[0]["Tín hiệu"]


def test_summary_skips_unscored_items():
    from datetime import date
    today = date.today().isoformat()
    news = [
        {"ticker": "VCB", "_sentiment": "",         "_date_sort": today},
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": today},
    ]
    out = ticker_sentiment_summary(news)
    # Should aggregate just the 1 scored item
    if out:
        assert out[0]["Tổng"] == 1


def test_summary_respects_day_cutoff():
    """Items older than `days` should be excluded."""
    news = [
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": "2020-01-01"},
    ]
    out = ticker_sentiment_summary(news, days=7)
    assert out == []


# ─── market_news_sentiment (market-wide aggregate) ───────────────────────────

def test_market_news_sentiment_aggregates_all_tickers():
    from datetime import date
    from vnstock_sentiment import market_news_sentiment
    today = date.today().isoformat()
    news = [
        {"ticker": "VCB", "_sentiment": "positive", "_date_sort": today},
        {"ticker": "FPT", "_sentiment": "positive", "_date_sort": today},
        {"ticker": "HPG", "_sentiment": "negative", "_date_sort": today},
        {"ticker": "SSI", "_sentiment": "neutral",  "_date_sort": today},
    ]
    out = market_news_sentiment(news, days=7)
    assert out["total"] == 4
    assert out["positive"] == 2 and out["negative"] == 1 and out["neutral"] == 1
    assert out["pos_pct"] == 50.0
    assert out["net_pct"] == 25.0  # (2-1)/4*100


def test_market_news_sentiment_empty_when_unscored():
    from datetime import date
    from vnstock_sentiment import market_news_sentiment
    today = date.today().isoformat()
    news = [{"ticker": "VCB", "_sentiment": "", "_date_sort": today}]
    assert market_news_sentiment(news) == {}


def test_market_news_sentiment_respects_cutoff():
    from vnstock_sentiment import market_news_sentiment
    news = [{"ticker": "VCB", "_sentiment": "positive", "_date_sort": "2020-01-01"}]
    assert market_news_sentiment(news, days=7) == {}
