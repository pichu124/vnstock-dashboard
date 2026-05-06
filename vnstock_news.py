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
import re
from urllib.parse import urljoin, urlparse

# VCI's company.news() returns `news_source_link` as host-less paths like
# "2026/02/<slug>-737-1404929.htm" — the year/month + dash-separated
# numeric category + article id + .htm pattern is vietstock.vn's layout
# (cafef.vn uses .chn URLs and a different scheme).
_DEFAULT_NEWS_BASE = "https://vietstock.vn/"
_LINK_KEYS = ("news_source_link", "source_link", "url", "link", "href")
_VIETSTOCK_PATH_RE = re.compile(r"^/?\d{4}/\d{2}/.+-\d+-\d+\.htm$")


def _absolutize_url(url: str) -> str:
    """Return an absolute URL pointing at the right publisher host.

    Also rewrites legacy cached URLs that were wrongly prefixed with
    cafef.vn but carry a vietstock-pattern path.
    """
    if not url or not url.strip():
        return ""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if (
            parsed.netloc.endswith("cafef.vn")
            and _VIETSTOCK_PATH_RE.match(parsed.path)
        ):
            return f"https://vietstock.vn{parsed.path}"
        return url
    if url.startswith("//"):
        return "https:" + url
    return urljoin(_DEFAULT_NEWS_BASE, url.lstrip("/"))

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
def build_universe(extra: list[str] | None = None, top_screener: int = 100) -> list[str]:
    """Return a deduplicated ticker list for news fetching.

    Base: VN30 (always included).
    Expanded by screener top-N (sorted by score → most active/liquid first).
    top_screener=500 covers near-full liquid market (~1,600 scored tickers).
    Falls back to warehouse enumeration if screener data is unavailable.
    """
    tickers: list[str] = list(_VN30_FALLBACK)

    # Try to get live VN30 from brief module
    try:
        sys.path.insert(0, str(_REPO))
        from vnstock_brief import get_vn30_live  # type: ignore
        live = get_vn30_live()
        if live:
            tickers = sorted(live)
    except Exception:
        pass

    # Screener: top-N by composite score (covers all ~1,600 classified tickers)
    screener_added = 0
    try:
        data = json.loads(SCREENER_PATH.read_text(encoding="utf-8"))
        scored = sorted(data.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
        tickers += [k for k, _ in scored[:top_screener]]
        screener_added = min(len(scored), top_screener)
    except Exception:
        pass

    # Fallback: if screener unavailable, pull from price warehouse
    if screener_added == 0:
        try:
            prices_dir = _REPO / "data_warehouse" / "prices"
            wh_tickers = sorted(
                d.name.split("=", 1)[-1].upper()
                for d in prices_dir.glob("ticker=*")
                if "=" in d.name and d.is_dir()
            )
            tickers += wh_tickers[:top_screener]
        except Exception:
            pass

    # Portfolio tickers always included
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


# Date field names VCI / KBS / providers may use. Order matters: most-likely first.
# Confirmed via debug expander: KBS uses `publish_time` (snake_case ISO).
_DATE_FIELDS = (
    "publish_time", "public_date", "publicDate", "publish_date", "publishDate",
    "time_publish", "publishTime", "publishedAt", "published_at",
    "publishedTime", "published_time", "publish_at", "publishAt",
    "created_at", "createdAt", "create_date", "createDate", "create_time", "created_time",
    "date", "news_date", "newsDate",
)


def _normalize_date(raw) -> str:
    """Normalise a publish date into canonical 'YYYY-MM-DD'.

    Returns '' if unparseable. Handles ISO strings, Unix timestamps (10 or
    13 digits), and pandas Timestamp string repr ('2026-04-02 14:30:00+07:00').
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() in ("none", "nan", "nat"):
        return ""
    # Unix timestamp (digits only)
    if s.isdigit():
        try:
            ts = int(s)
            if ts > 10**12:  # milliseconds
                ts //= 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return ""
    # ISO / pandas Timestamp string — first 10 chars are YYYY-MM-DD if well-formed
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # DD/MM/YYYY (Vietnamese sites)
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        try:
            return datetime.strptime(s[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            return ""
    # Fallback: try fromisoformat
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _detect_publish_date(d: dict) -> str:
    """Find publish date from a record dict. Returns canonical YYYY-MM-DD or ''.

    Strategy (in order):
      1. Try known field names from _DATE_FIELDS
      2. Dynamic fallback: scan any key whose name contains
         date / time / publish / create (case-insensitive)
    """
    for k in _DATE_FIELDS:
        if d.get(k):
            candidate = _normalize_date(d[k])
            if candidate:
                return candidate
    for k, v in d.items():
        if not v or k in ("ticker", "source_provider", "_date_sort"):
            continue
        kl = k.lower()
        if any(s in kl for s in ("date", "time", "publish", "create")):
            candidate = _normalize_date(v)
            if candidate:
                return candidate
    return ""


def _rehydrate_date_sort(items: list[dict]) -> int:
    """Re-run date normalization on cached items with empty _date_sort.

    The on-disk cache may have been written by older code that didn't
    populate _date_sort, or written before the field-detection logic was
    fixed. This function applies the current detection in-place to
    rescue those items without requiring a full re-fetch from the API.

    Returns the number of items whose _date_sort was newly populated.
    """
    fixed = 0
    for d in items:
        if d.get("_date_sort"):
            continue
        normalised = _detect_publish_date(d)
        if normalised:
            d["_date_sort"] = normalised
            if not d.get("public_date"):
                d["public_date"] = normalised
            fixed += 1
    return fixed


def _is_news_dataframe(df) -> bool:
    """Check if a DataFrame is actually news data, not an API error response.

    Some providers (KBS) return error responses in the same shape as a
    DataFrame, e.g. {st:'err', msg:'s must not be greater than 20',
    code:'1', error_code:'500'} when an unsupported param is passed.
    Without this guard those error rows would be saved into the cache
    and shown to the user as "108/108 tin không có ngày phát hành".
    """
    if df is None or len(df) == 0:
        return False
    cols = set(map(str, df.columns))
    # Explicit error signatures
    if {"st", "error_code"} & cols:
        first = df.iloc[0]
        if str(first.get("st", "")).lower() == "err":
            return False
        if str(first.get("error_code", "")) in ("500", "400", "401", "403", "429"):
            return False
    # Must have at least one news-like column
    news_cols = {
        "title", "head", "news_title", "article_id", "headline",
        "publish_time", "public_date", "publishedAt", "publishedTime",
    }
    return bool(news_cols & cols)


def _is_valid_news_item(d: dict) -> bool:
    """Check if a cached record is actually news, not an old error response."""
    if not isinstance(d, dict):
        return False
    if str(d.get("st", "")).lower() == "err":
        return False
    if str(d.get("error_code", "")) in ("500", "400", "401", "403", "429"):
        return False
    # Need at least one meaningful content field
    return bool(
        d.get("title") or d.get("head") or d.get("news_title")
        or d.get("article_id") or d.get("headline")
    )


def fetch_ticker_news(ticker: str, source: str = "VCI") -> list[dict]:
    """Fetch news for one ticker. Returns list of dicts (empty on any error).

    Priority order (verified empirically against vnstock 4.0.2 + sponsor pkg):
      1. vnstock free `Vnstock().stock(...).company.news()` — returns ~50
         articles per ticker with the rich 21-column schema (news_title,
         news_short_content, news_full_content, public_date, ...). Best
         coverage and recency.
      2. vnstock_data.Company(source='KBS').news() as fallback — only
         returns 1 article per ticker but works when free path fails.
      3. vnstock_data.Company(source='VCI').news() — currently broken
         in vnstock 4.0.2 (KeyError: 'data'); skipped.
    """
    # Free path FIRST — vnstock 4.0.2 returns 50 articles per ticker
    # with the full schema we want. Try VCI then KBS as source.
    sources = [source] + ([s for s in ("VCI", "KBS") if s != source])
    for src in sources:
        try:
            from vnstock import Vnstock  # type: ignore
            stock = Vnstock().stock(symbol=ticker, source=src)
            df = stock.company.news()
            if _is_news_dataframe(df):
                return _records_from_df(df, ticker, src)
        except Exception:
            continue

    # Sponsor fallback — vnstock_data.Company. KBS returns 1 article;
    # VCI is still broken (KeyError: 'data') in 4.0.2 so we only try KBS.
    try:
        import vnstock_data as _vd
        for kwargs in ({"size": 20}, {"page_size": 20}, {}):
            try:
                comp = _vd.Company(symbol=ticker, source="KBS")
                df = comp.news(**kwargs)
                if _is_news_dataframe(df):
                    return _records_from_df(df, ticker, "KBS")
            except TypeError:
                continue
            except Exception:
                break
    except ImportError:
        pass
    return []


def diagnose_news_fetch(ticker: str = "VCB") -> dict:
    """Run a diagnostic fetch for one ticker, return raw API output details.

    Used by the news_tab debug expander so the user can see what each
    code path returns without having to read source code. Returns a dict
    with one entry per attempted code path: status, latency, shape,
    columns, sample row.
    """
    import time as _time
    import inspect as _inspect
    out: dict = {}

    # vnstock_data.Company — try both VCI and KBS so we see what each returns
    try:
        import vnstock_data as _vd
        for src in ("VCI", "KBS"):
            label = f"vnstock_data.Company(source='{src}').news()"
            try:
                comp = _vd.Company(symbol=ticker, source=src)
                t0 = _time.time()
                df = comp.news()
                dt = (_time.time() - t0) * 1000
                out[label] = {
                    "latency_ms": round(dt, 0),
                    "shape": tuple(df.shape) if df is not None and hasattr(df, "shape") else None,
                    "columns": list(df.columns) if df is not None and hasattr(df, "columns") else [],
                    "is_news": _is_news_dataframe(df) if df is not None else False,
                    "sample": df.iloc[0].to_dict() if df is not None and not df.empty else None,
                }
            except Exception as e:
                out[label] = {"error": f"{type(e).__name__}: {e}"}
    except ImportError as e:
        out["vnstock_data.Company"] = {"error": f"ImportError: {e}"}

    # vnstock free
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        t0 = _time.time()
        df = stock.company.news()
        dt = (_time.time() - t0) * 1000
        out["vnstock.company.news()"] = {
            "latency_ms": round(dt, 0),
            "shape": tuple(df.shape) if df is not None and hasattr(df, "shape") else None,
            "columns": list(df.columns) if df is not None and hasattr(df, "columns") else [],
            "sample": df.iloc[0].to_dict() if df is not None and not df.empty else None,
        }
    except Exception as e:
        out["vnstock.company.news()"] = {"error": f"{type(e).__name__}: {e}"}

    return out


def _records_from_df(df, ticker: str, source: str) -> list[dict]:
    """Convert a news DataFrame to records with ticker, source, _date_sort, links."""
    records = []
    for _, row in df.iterrows():
        d = _to_dict(row)
        d["ticker"] = ticker
        d["source_provider"] = source
        d["_date_sort"] = _detect_publish_date(d)
        if d["_date_sort"] and not d.get("public_date"):
            d["public_date"] = d["_date_sort"]
        for k in _LINK_KEYS:
            if d.get(k):
                d[k] = _absolutize_url(d[k])
                break
        records.append(d)
    return records


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

    # Sort newest first. Items without a parseable date go to the END
    # (use sentinel "0000-00-00" so they don't bubble to the top via reverse=True).
    all_news.sort(
        key=lambda x: x.get("_date_sort") or "0000-00-00",
        reverse=True,
    )

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
    """Load from disk; returns [] on any error.

    Auto-rehydrates _date_sort for cached items missing it (e.g. cache
    written before the field-detection logic was fixed). Persists the
    updated cache back to disk so subsequent loads don't repeat the work.
    """
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
            raw_items = data.get("items", [])
            # Filter out error responses that older buggy fetches saved
            # into the cache (e.g. KBS 'st:err' rows).
            items = [d for d in raw_items if _is_valid_news_item(d)]
            removed = len(raw_items) - len(items)
            fixed = _rehydrate_date_sort(items)
            if fixed > 0 or removed > 0:
                # Re-sort newest-first now that dates are populated.
                items.sort(
                    key=lambda x: x.get("_date_sort") or "0000-00-00",
                    reverse=True,
                )
                # Persist so subsequent loads see the rehydrated cache.
                try:
                    NEWS_CACHE_PATH.write_text(
                        json.dumps(
                            {"fetched_at": data.get("fetched_at",
                                                    datetime.now().isoformat()),
                             "items": items},
                            ensure_ascii=False, indent=None,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
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
