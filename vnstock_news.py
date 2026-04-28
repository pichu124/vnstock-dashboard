"""vnstock_news.py — News data layer for VNStock Dashboard.

Fetches per-ticker news from vnstock (VCI source, KBS fallback), caches to
disk, and exposes helpers for AI agents in brief and analysis contexts.

Universe strategy (practical "all market"):
  • VN30 always included (30 stocks)
  • Top-N tickers from screener results by score (if available)
  • Portfolio tickers (if available)
  Total: typically 50–100 tickers — covers major market movers.

Cache: data_warehouse/_meta/news_cache.json
  Refreshed on demand (button in UI) or via refresh_news().
  TTL: 2 hours within the same process (file always re-usable across sessions).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent
NEWS_CACHE_PATH = _REPO / "data_warehouse" / "_meta" / "news_cache.json"
SCREENER_PATH   = _REPO / "data_warehouse" / "_meta" / "screener_results.json"
PORTFOLIO_PATH  = _REPO / "data_warehouse" / "_meta" / "portfolio.json"

# ── VN30 baseline (hardcoded fallback if dashboard symbols unavailable) ────
_VN30_FALLBACK: list[str] = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

# ── In-process cache (avoids re-reading disk on every Streamlit rerun) ─────
_cache_lock = threading.Lock()
_in_memory: list[dict] = []
_cache_loaded_at: Optional[datetime] = None
_MEMORY_TTL_SECONDS = 7200  # 2 hours


# ── Universe helpers ───────────────────────────────────────────────────────
def build_universe(extra: list[str] | None = None, top_screener: int = 30) -> list[str]:
    """Return a deduplicated ticker list covering the whole market."""
    tickers: list[str] = list(_VN30_FALLBACK)

    # Try to get VN30 from dashboard module (may have fresher list)
    try:
        import sys
        sys.path.insert(0, str(_REPO))
        from vnstock_dashboard import VN30_SYMBOLS  # type: ignore
        if VN30_SYMBOLS:
            tickers = list(VN30_SYMBOLS)
    except Exception:
        pass

    # Add top screener tickers by composite score
    try:
        data = json.loads(SCREENER_PATH.read_text(encoding="utf-8"))
        scored = sorted(data.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
        tickers += [k for k, _ in scored[:top_screener]]
    except Exception:
        pass

    # Add portfolio tickers
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
        tickers += [p["ticker"] for p in portfolio if "ticker" in p]
    except Exception:
        pass

    if extra:
        tickers += extra

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in tickers:
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ── Fetch helpers ──────────────────────────────────────────────────────────
def _to_dict(row) -> dict:
    """Convert a pandas Series / dict row to plain dict with str values."""
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    return {k: (str(v) if v is not None else "") for k, v in row.items()}


def fetch_ticker_news(ticker: str, source: str = "VCI") -> list[dict]:
    """Fetch news for one ticker. Returns list of dicts (empty on any error)."""
    sources = [source] + ([s for s in ("VCI", "KBS") if s != source])
    for src in sources:
        try:
            from vnstock import Vnstock  # type: ignore
            stock = Vnstock().stock(symbol=ticker, source=src)
            df = stock.company.news()
            if df is None or df.empty:
                continue
            records = []
            for _, row in df.iterrows():
                d = _to_dict(row)
                d["ticker"] = ticker
                d["source_provider"] = src
                # Normalise date field
                raw_date = d.get("public_date") or d.get("created_at") or ""
                d["_date_sort"] = raw_date[:10] if raw_date else ""
                records.append(d)
            if records:
                return records
        except Exception:
            continue
    return []


# ── Parallel refresh ───────────────────────────────────────────────────────
def refresh_news(
    universe: list[str] | None = None,
    max_workers: int = 8,
    progress_cb=None,
) -> list[dict]:
    """Fetch news for all tickers in universe in parallel, save cache, return list.

    progress_cb: optional callable(done, total) for UI progress updates.
    """
    if universe is None:
        universe = build_universe()

    all_news: list[dict] = []
    done = 0
    total = len(universe)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_ticker_news, t): t for t in universe}
        for fut in as_completed(futures):
            try:
                records = fut.result()
                all_news.extend(records)
            except Exception:
                pass
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:
                    pass

    # Sort newest first
    all_news.sort(key=lambda x: x.get("_date_sort", ""), reverse=True)

    save_news_cache(all_news)
    _set_memory_cache(all_news)
    return all_news


# ── Cache I/O ──────────────────────────────────────────────────────────────
def save_news_cache(news: list[dict]) -> None:
    NEWS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = NEWS_CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"fetched_at": datetime.now().isoformat(), "items": news},
                   ensure_ascii=False, indent=None),
        encoding="utf-8",
    )
    tmp.replace(NEWS_CACHE_PATH)


def load_news_cache() -> list[dict]:
    """Load from disk; returns [] on any error."""
    global _in_memory, _cache_loaded_at

    with _cache_lock:
        # Return in-memory copy if fresh
        if _in_memory and _cache_loaded_at:
            age = (datetime.now() - _cache_loaded_at).total_seconds()
            if age < _MEMORY_TTL_SECONDS:
                return _in_memory

        if not NEWS_CACHE_PATH.exists():
            return []
        try:
            data = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
            items = data.get("items", [])
            _set_memory_cache(items)
            return items
        except Exception:
            return []


def _set_memory_cache(items: list[dict]) -> None:
    global _in_memory, _cache_loaded_at
    _in_memory = items
    _cache_loaded_at = datetime.now()


def cache_info() -> dict:
    """Return metadata about the current cache (age, count)."""
    if not NEWS_CACHE_PATH.exists():
        return {"exists": False, "count": 0, "fetched_at": None, "age_minutes": None}
    try:
        data = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at_str = data.get("fetched_at", "")
        fetched_at = datetime.fromisoformat(fetched_at_str) if fetched_at_str else None
        age = (datetime.now() - fetched_at).total_seconds() / 60 if fetched_at else None
        return {
            "exists": True,
            "count": len(data.get("items", [])),
            "fetched_at": fetched_at_str,
            "age_minutes": round(age, 1) if age is not None else None,
        }
    except Exception:
        return {"exists": True, "count": 0, "fetched_at": None, "age_minutes": None}


# ── Query helpers ──────────────────────────────────────────────────────────
def news_for_ticker(ticker: str, news: list[dict] | None = None) -> list[dict]:
    """Filter cached news for one ticker."""
    if news is None:
        news = load_news_cache()
    ticker = ticker.upper()
    return [n for n in news if n.get("ticker", "").upper() == ticker]


def news_for_date(target_date: str, news: list[dict] | None = None) -> list[dict]:
    """Filter news by date string YYYY-MM-DD."""
    if news is None:
        news = load_news_cache()
    return [n for n in news if n.get("_date_sort", "").startswith(target_date)]


def latest_news(n: int = 50, news: list[dict] | None = None) -> list[dict]:
    if news is None:
        news = load_news_cache()
    return news[:n]


# ── AI context formatter ───────────────────────────────────────────────────
def news_context_block(
    tickers: list[str] | None = None,
    max_items: int = 20,
    date_filter: str | None = None,
) -> str:
    """Return a formatted string of recent news for injection into AI prompts.

    If tickers is given, only news for those tickers is included.
    date_filter: YYYY-MM-DD string to restrict to one day (default: today).
    """
    news = load_news_cache()
    if not news:
        return ""

    today = date_filter or date.today().isoformat()
    # Use today's news; if empty, fall back to most recent 3 days
    filtered = [n for n in news if n.get("_date_sort", "") >= today]
    if not filtered:
        filtered = news  # fall back to whatever we have

    if tickers:
        upper = {t.upper() for t in tickers}
        filtered = [n for n in filtered if n.get("ticker", "").upper() in upper]

    filtered = filtered[:max_items]
    if not filtered:
        return ""

    lines = ["## Tin tức thị trường gần đây"]
    for item in filtered:
        ticker  = item.get("ticker", "")
        title   = item.get("news_title", "").strip()
        summary = (item.get("news_short_content") or item.get("news_sub_title") or "").strip()
        d       = item.get("_date_sort", "")
        if not title:
            continue
        line = f"[{ticker}] {d}: {title}"
        if summary:
            # Truncate long summaries
            summary_short = summary[:200] + ("…" if len(summary) > 200 else "")
            line += f"\n  → {summary_short}"
        lines.append(line)

    return "\n".join(lines)
