"""vnstock_sentiment.py — News sentiment scoring for VNStock Dashboard.

Scores news headlines via a lightweight LLM (Groq → Cerebras → OpenRouter).
Results are cached to SQLite so each article is only scored once.

Sentiment values: "positive" | "negative" | "neutral"
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date as _date, timedelta as _td
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).parent
SENTIMENT_DB_PATH = _REPO / "data_warehouse" / "_meta" / "sentiment_cache.db"

_db_lock = threading.Lock()

# ── DB ─────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    SENTIMENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SENTIMENT_DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_sentiment (
            item_hash TEXT PRIMARY KEY,
            ticker    TEXT NOT NULL,
            date      TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            model     TEXT,
            scored_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _item_hash(item: dict) -> str:
    ticker = (item.get("ticker") or "").upper()
    d      = (item.get("_date_sort") or "")[:10]
    title  = (item.get("news_title") or item.get("title") or item.get("head") or "").strip()
    return hashlib.md5(f"{ticker}|{d}|{title}".encode()).hexdigest()


# ── LLM providers ─────────────────────────────────────────────────────────

_SYSTEM = (
    "Bạn là chuyên gia phân tích tin tức chứng khoán Việt Nam. "
    "Phân loại sentiment của tin tức theo quan điểm nhà đầu tư: "
    "TÍCH_CỰC (tin tốt cho cổ phiếu), TIÊU_CỰC (tin xấu cho cổ phiếu), "
    "TRUNG_LẬP (không ảnh hưởng rõ ràng). "
    "Chỉ trả lời đúng 1 từ: TÍCH_CỰC hoặc TIÊU_CỰC hoặc TRUNG_LẬP."
)

_PROVIDERS = [
    {
        "name": "Groq",
        "env": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
    },
    {
        "name": "Cerebras",
        "env": "CEREBRAS_API_KEY",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "model": "llama3.1-8b",
    },
    {
        "name": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "model": "meta-llama/llama-3.1-8b-instruct:free",
    },
]

_SENTIMENT_MAP: dict[str, str] = {
    "tích_cực": "positive", "tiêu_cực": "negative", "trung_lập": "neutral",
    "tich_cuc": "positive", "tieu_cuc": "negative", "trung_lap": "neutral",
    "tích cực": "positive", "tiêu cực": "negative", "trung lập": "neutral",
    "positive": "positive", "negative": "negative", "neutral": "neutral",
}


def _call_provider(provider: dict, text: str) -> Optional[str]:
    key = (os.environ.get(provider["env"]) or "").strip()
    if not key:
        return None
    try:
        import requests as _req
        resp = _req.post(
            provider["endpoint"],
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            json={
                "model": provider["model"],
                "max_tokens": 10,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip().lower()
        for key_str, val in _SENTIMENT_MAP.items():
            if key_str in raw:
                return val
        return "neutral"
    except Exception:
        return None


def available_provider() -> Optional[str]:
    """Return name of first available provider, or None."""
    for p in _PROVIDERS:
        if (os.environ.get(p["env"]) or "").strip():
            return p["name"]
    return None


def chat_complete(system: str, user: str, max_tokens: int = 80,
                  model_map: "dict | None" = None) -> Optional[str]:
    """Generic one-shot chat over the provider ladder (Groq→Cerebras→OpenRouter).

    Returns the raw assistant text, or None when no provider key works / all
    fail. Additive helper (does not change score_one's behaviour) reused by the
    market-news analyzer to get sentiment + a one-line impact in a single call.

    ``model_map`` ({provider_name: model}) overrides the default per-provider
    model — e.g. a stronger 70B for nuanced analysis — and falls back to the
    provider's default model if the override is rejected.
    """
    model_map = model_map or {}
    import requests as _req
    for p in _PROVIDERS:
        key = (os.environ.get(p["env"]) or "").strip()
        if not key:
            continue
        models: list[str] = []
        ov = model_map.get(p["name"])
        if ov and ov != p["model"]:
            models.append(ov)            # preferred (stronger) model first
        models.append(p["model"])        # default fallback
        for model in models:
            try:
                resp = _req.post(
                    p["endpoint"],
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}"},
                    json={"model": model, "max_tokens": max_tokens,
                          "temperature": 0,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]},
                    timeout=25,
                )
                resp.raise_for_status()
                return (resp.json()["choices"][0]["message"]["content"] or "").strip()
            except Exception:
                continue
    return None


def score_one(item: dict) -> tuple[str, str, Optional[str]]:
    """Score one news item. Returns (item_hash, sentiment, provider_name)."""
    h      = _item_hash(item)
    ticker = (item.get("ticker") or "").upper()
    title  = (item.get("news_title") or item.get("title") or item.get("head") or "").strip()
    short  = (
        item.get("news_short_content") or item.get("news_sub_title") or ""
    ).strip()[:200]

    text = f"Mã: {ticker}\nTiêu đề: {title}"
    if short:
        text += f"\nTóm tắt: {short}"

    for p in _PROVIDERS:
        result = _call_provider(p, text)
        if result:
            return h, result, p["name"]
    return h, "neutral", None


# ── Batch scoring ─────────────────────────────────────────────────────────

def score_news_batch(
    news: list[dict],
    max_workers: int = 5,
    progress_cb=None,
) -> dict[str, str]:
    """Score news list, skip already-cached items. Returns hash→sentiment map."""
    with _db_lock:
        conn = _get_conn()
        rows = conn.execute("SELECT item_hash, sentiment FROM news_sentiment").fetchall()
        conn.close()
    cached = {r[0]: r[1] for r in rows}

    to_score = [n for n in news if _item_hash(n) not in cached]
    total = len(to_score)
    done_count = 0
    new_rows: list[tuple] = []
    new_results: dict[str, str] = {}
    scored_at = datetime.now().isoformat()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(score_one, item): item for item in to_score}
        for fut in as_completed(futures):
            try:
                h, sentiment, model = fut.result()
                item = futures[fut]
                new_results[h] = sentiment
                new_rows.append((
                    h,
                    (item.get("ticker") or "").upper(),
                    (item.get("_date_sort") or "")[:10],
                    sentiment,
                    model or "",
                    scored_at,
                ))
            except Exception:
                pass
            done_count += 1
            if progress_cb:
                try:
                    progress_cb(done_count, total)
                except Exception:
                    pass

    if new_rows:
        with _db_lock:
            conn = _get_conn()
            conn.executemany(
                "INSERT OR REPLACE INTO news_sentiment "
                "(item_hash, ticker, date, sentiment, model, scored_at) VALUES (?,?,?,?,?,?)",
                new_rows,
            )
            conn.commit()
            conn.close()

    return {**cached, **new_results}


def attach_sentiments(news: list[dict]) -> list[dict]:
    """Non-scoring: add '_sentiment' field from cache to each news item."""
    try:
        with _db_lock:
            conn = _get_conn()
            rows = conn.execute("SELECT item_hash, sentiment FROM news_sentiment").fetchall()
            conn.close()
        mapping = {r[0]: r[1] for r in rows}
        for item in news:
            item["_sentiment"] = mapping.get(_item_hash(item), "")
    except Exception:
        for item in news:
            item.setdefault("_sentiment", "")
    return news


def scored_count(news: list[dict]) -> int:
    """Number of items that already have a cached sentiment score."""
    try:
        with _db_lock:
            conn = _get_conn()
            rows = conn.execute("SELECT item_hash FROM news_sentiment").fetchall()
            conn.close()
        hashes = {r[0] for r in rows}
        return sum(1 for n in news if _item_hash(n) in hashes)
    except Exception:
        return 0


# ── Aggregation ───────────────────────────────────────────────────────────

_SIGNAL_LABEL = {
    "strong_pos": "🟢 Tích cực mạnh",
    "pos":        "🟡 Hơi tích cực",
    "neutral":    "⚪ Trung lập",
    "neg":        "🟠 Hơi tiêu cực",
    "strong_neg": "🔴 Tiêu cực mạnh",
}


def ticker_sentiment_summary(
    news: list[dict],
    days: int = 7,
) -> list[dict]:
    """Aggregate sentiment by ticker for the last N days.

    Returns list of dicts sorted by net_score desc.
    """
    cutoff = (_date.today() - _td(days=days)).isoformat()
    recent = [
        n for n in news
        if n.get("_date_sort", "") >= cutoff and n.get("_sentiment")
    ]

    counts: dict[str, dict[str, int]] = {}
    for n in recent:
        t = (n.get("ticker") or "").upper()
        if not t:
            continue
        if t not in counts:
            counts[t] = {"positive": 0, "negative": 0, "neutral": 0}
        s = n["_sentiment"]
        if s in counts[t]:
            counts[t][s] += 1

    rows = []
    for ticker, c in counts.items():
        total = c["positive"] + c["negative"] + c["neutral"]
        if total == 0:
            continue
        net = c["positive"] - c["negative"]
        if net >= 2:
            sig = _SIGNAL_LABEL["strong_pos"]
        elif net == 1:
            sig = _SIGNAL_LABEL["pos"]
        elif net == -1:
            sig = _SIGNAL_LABEL["neg"]
        elif net <= -2:
            sig = _SIGNAL_LABEL["strong_neg"]
        else:
            sig = _SIGNAL_LABEL["neutral"]

        rows.append({
            "Mã": ticker,
            "Tích cực": c["positive"],
            "Tiêu cực": c["negative"],
            "Trung lập": c["neutral"],
            "Tổng": total,
            "Net": net,
            "Tín hiệu": sig,
        })

    rows.sort(key=lambda r: r["Net"], reverse=True)
    return rows


def market_news_sentiment(news: list[dict], days: int = 7) -> dict:
    """Aggregate news sentiment across the WHOLE market for the last N days.

    Unlike ticker_sentiment_summary (per ticker), this rolls every scored
    article up into one market-mood reading. Returns:
      {positive, negative, neutral, total, pos_pct, neg_pct, net_pct}
    where net_pct = (positive - negative) / total * 100  (-100..+100).
    Empty dict if no scored news in the window.
    """
    cutoff = (_date.today() - _td(days=days)).isoformat()
    pos = neg = neu = 0
    for n in news:
        if n.get("_date_sort", "") < cutoff:
            continue
        s = n.get("_sentiment") or ""
        if s == "positive":
            pos += 1
        elif s == "negative":
            neg += 1
        elif s == "neutral":
            neu += 1
    total = pos + neg + neu
    if total == 0:
        return {}
    return {
        "positive": pos,
        "negative": neg,
        "neutral":  neu,
        "total":    total,
        "pos_pct":  round(pos / total * 100, 1),
        "neg_pct":  round(neg / total * 100, 1),
        "net_pct":  round((pos - neg) / total * 100, 1),
    }


def sentiment_timeline(
    ticker: str,
    news: list[dict],
    days: int = 30,
) -> list[dict]:
    """Return daily sentiment counts for one ticker (sorted by date)."""
    cutoff = (_date.today() - _td(days=days)).isoformat()
    ticker = ticker.upper()

    relevant = [
        n for n in news
        if n.get("ticker", "").upper() == ticker
        and n.get("_date_sort", "") >= cutoff
        and n.get("_sentiment")
    ]

    by_date: dict[str, dict[str, int]] = {}
    for n in relevant:
        d = (n.get("_date_sort") or "")[:10]
        if not d:
            continue
        if d not in by_date:
            by_date[d] = {"positive": 0, "negative": 0, "neutral": 0}
        s = n["_sentiment"]
        if s in by_date[d]:
            by_date[d][s] += 1

    return [{"date": d, **c} for d, c in sorted(by_date.items())]
