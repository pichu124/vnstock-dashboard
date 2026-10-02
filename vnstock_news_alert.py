"""vnstock_news_alert — cảnh báo TIN QUAN TRỌNG theo giờ → Telegram (02/10/2026, #31).

Chạy bằng Task Scheduler 🖥️ DESKTOP mỗi giờ 07–22h T2–T7 (`run.py news-alert`):

    NGUỒN (registry `SOURCES`) → `normalize_item` (schema chung) → lọc liên quan
    (từng nguồn tự khai) → CỬA SỔ GIỜ (`WINDOW_H`, mặc định 3h) → khử trùng
    (`deduplicate_news` + sổ `_meta/news_alert_seen.json`) → CHẤM MỨC ĐỘ 1–5
    (Claude Code theo LÔ, MỘT call `--json-schema`; hỏng ⇒ ladder free từng tin
    + điểm từ khoá) → ngưỡng `MIN_SCORE` (3) → Telegram (≤ `MAX_SEND` tin/lượt,
    dư thì lượt sau, KHÔNG chấm lại) → sổ + marker `_meta/news_alert_status.json`.

Thiết kế cho nhiều nguồn: thêm nguồn = MỘT `Source(...)` (RSS, API, scraper…)
trả list dict thô bất kỳ dạng {title, link, summary, published}; đường chấm /
gửi không đổi. RSS lấy thẳng từ `vnstock_news_feeds._FEEDS` (một nguồn sự
thật với bước news của pipeline — thêm feed ở đó là cả hai cùng thấy). Nguồn
thứ hai (tin theo mã qua vnstock, bật bằng `VNSTOCK_NEWS_ALERT_TICKERS`) là
mẫu adapter KHÔNG-RSS.

Không bao giờ đụng `market_news_cache.json` — file đó của bước news phát 18:00
trên CÙNG desktop; hai tiến trình ghi một file là đua. Không có tin mới ⇒ im
lặng, không gọi LLM. Kill-switch `VNSTOCK_NEWS_ALERT=0`.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

_REPO = Path(__file__).resolve().parent
_META = _REPO / "data_warehouse" / "_meta"          # tests monkeypatch chỗ này
SEEN_NAME = "news_alert_seen.json"
STATUS_NAME = "news_alert_status.json"

STEP = "news_alert"                                 # khoá engine (vnstock_claude_cli)
KILL_SWITCH = "VNSTOCK_NEWS_ALERT"
ENV_HOURS = "VNSTOCK_NEWS_ALERT_HOURS"              # "7-22" — giờ ĐẦU..CUỐI, bao cả hai đầu
ENV_DAYS = "VNSTOCK_NEWS_ALERT_DAYS"                # "1-6"  — ISO: 1=T2 … 6=T7, 7=CN
ENV_MIN_SCORE = "VNSTOCK_NEWS_ALERT_MIN_SCORE"
ENV_WINDOW_H = "VNSTOCK_NEWS_ALERT_WINDOW_H"
ENV_MAX_SEND = "VNSTOCK_NEWS_ALERT_MAX_SEND"
ENV_MAX_SCORE = "VNSTOCK_NEWS_ALERT_MAX_SCORE"
ENV_SOURCES = "VNSTOCK_NEWS_ALERT_SOURCES"          # lọc key nguồn, phẩy
ENV_TICKERS = "VNSTOCK_NEWS_ALERT_TICKERS"          # "VCB,HPG" bật adapter tin theo mã
ENV_CLI_MODEL = "VNSTOCK_NEWS_ALERT_CLI_MODEL"
ENV_CLI_TIMEOUT = "VNSTOCK_NEWS_ALERT_CLI_TIMEOUT_S"

DEFAULT_HOURS = (7, 22)
DEFAULT_DAYS = (1, 6)
DEFAULT_MIN_SCORE = 3
DEFAULT_WINDOW_H = 3
DEFAULT_MAX_SEND = 8
DEFAULT_MAX_SCORE = 30          # trần tin CHẤM mỗi lượt (token) — dư rơi khỏi cửa sổ giờ
DEFAULT_CLI_TIMEOUT_S = 180
SEEN_RETAIN_DAYS = 7
SCORE_MIN, SCORE_MAX = 1, 5
_OFF = ("0", "false", "off", "no")
TAG = "news-alert"

_ENV_LOADED = False


def _load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass


def _env_int(name: str, default: int, lo: int = 0, hi: int = 10_000) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return default


def enabled() -> bool:
    return (os.environ.get(KILL_SWITCH) or "1").strip().lower() not in _OFF


# ── Registry NGUỒN ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    """Một nguồn tin. `fetch()` trả list dict THÔ (dạng gì cũng được, miễn có
    tiêu đề); `relevant` lọc tin liên quan thị trường (None = lấy hết — dùng
    cho nguồn vốn đã chuyên ngành như tin theo mã)."""
    key: str
    name: str
    fetch: Callable[[], list]
    kind: str = "rss"
    lang: str = "vi"
    enabled: bool = True
    relevant: Optional[Callable[[dict], bool]] = None


def _slug(s: str) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


_NO_FILTER = object()        # sentinel: "không lọc" khác với "mặc định"


def rss_source(feed: dict, relevant=_NO_FILTER, key_prefix: str = "rss") -> Source:
    """Adapter RSS/Atom — dùng lại fetch_feed của news_feeds. `relevant` mặc
    định = bộ lọc từ khoá tiếng Việt của news_feeds (`_is_relevant`); feed
    tiếng Anh truyền `_relevant_en`; feed đã chuyên đề (Google News theo truy
    vấn) truyền None = lấy hết."""
    import vnstock_news_feeds as nf

    def _fetch(f: dict = feed) -> list:
        return nf.fetch_feed(f)

    if relevant is _NO_FILTER:
        relevant = (lambda it: nf._is_relevant(it))
    return Source(key=f"{key_prefix}:" + _slug(feed["name"]), name=feed["name"], fetch=_fetch,
                  kind=feed.get("kind", "rss"), lang=feed.get("lang", "vi"),
                  enabled=feed.get("enabled", True), relevant=relevant)


# Từ khoá tiếng Anh cho feed nước ngoài (news_feeds._MARKET_KEYWORDS thiên tiếng
# Việt). Mục tiêu là VĨ MÔ ảnh hưởng VN: Fed/USD/lợi suất, dầu, thuế quan, Trung
# Quốc, dòng vốn EM — tin doanh nghiệp Mỹ lẻ (earnings Apple…) KHÔNG qua cửa này.
_EN_KEYWORDS: tuple = (
    "fed", "federal reserve", "fomc", "powell", "rate", "yield", "treasury", "inflation",
    "cpi", "pce", "gdp", "payroll", "jobs report", "unemployment", "recession", "pmi",
    "dollar", "dxy", "yuan", "yen", "ecb", "boj", "pboc", "central bank", "tariff",
    "trade war", "sanction", "export control", "oil", "brent", "opec", "crude", "gold",
    "china", "vietnam", "asean", "emerging market", "em flows", "stimulus", "debt ceiling",
    "default", "bond", "liquidity", "war", "ceasefire", "geopolit", "strait", "shipping",
    "semiconductor", "chip export", "s&p 500", "nasdaq", "wall street", "stocks fall",
    "stocks rise", "sell-off", "selloff", "rally", "volatility", "vix",
)


def _relevant_en(item: dict) -> bool:
    hay = f"{item.get('title', '')} {item.get('news_short_content', '')}".lower()
    return any(k in hay for k in _EN_KEYWORDS)


def gnews_feed(name: str, query: str, lang: str = "en", enabled: bool = True) -> dict:
    """Feed Google News RSS theo TRUY VẤN (miễn phí, không key) — một dòng một
    chủ đề. Tiêu đề Google News có đuôi " - <Báo>", `gnews_source` tách ra làm
    source_feed. Link là link chuyển hướng news.google.com (Telegram mở được)."""
    from urllib.parse import quote_plus
    hl, gl, ceid = ("vi", "VN", "VN:vi") if lang == "vi" else ("en-US", "US", "US:en")
    url = (f"https://news.google.com/rss/search?q={quote_plus(query)}"
           f"&hl={hl}&gl={gl}&ceid={ceid}")
    return {"name": name, "url": url, "lang": lang, "kind": "gnews", "enabled": enabled,
            "query": query}


_GNEWS_TITLE_RE = re.compile(r"^(.*\S)\s+-\s+([^-]{2,60})$")


def gnews_source(feed: dict) -> Source:
    """Google News RSS: truy vấn đã chuyên đề ⇒ không lọc từ khoá; tách báo gốc
    khỏi đuôi tiêu đề để Telegram ghi đúng nguồn."""
    base = rss_source(feed, relevant=None, key_prefix="gnews")

    def _fetch(inner=base.fetch, label=feed["name"]) -> list:
        out = []
        for it in inner() or []:
            m = _GNEWS_TITLE_RE.match(it.get("title") or "")
            if m:
                it = {**it, "title": m.group(1), "news_title": m.group(1),
                      "source_feed": f"{m.group(2).strip()} · {label}"}
            out.append(it)
        return out

    return Source(key=base.key, name=base.name, fetch=_fetch, kind="gnews", lang=base.lang,
                  enabled=base.enabled, relevant=None)


# Nguồn NƯỚC NGOÀI chỉ cho cảnh báo (KHÔNG vào news_feeds._FEEDS để brief chiều
# và cache tin không đổi). URL là ứng viên — sandbox không fetch được, 🖥️ desktop
# xác minh bằng `python run.py news-alert --diag`; feed ❌ thì enabled=False hoặc
# xoá dòng. Danh sách chốt theo khảo sát U68 (02/10).
_ALERT_FEEDS: list = [
    # ── Báo / chính thức, RSS trực tiếp (tiếng Anh, lọc _EN_KEYWORDS) ──
    {"name": "WSJ Markets",        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "lang": "en"},
    {"name": "WSJ World",          "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",   "lang": "en"},
    {"name": "NYT Economy",        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "lang": "en"},
    {"name": "BBC Business",       "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "lang": "en"},
    {"name": "Guardian Business",  "url": "https://www.theguardian.com/uk/business/rss",   "lang": "en"},
    {"name": "Fed press releases", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "lang": "en"},
    {"name": "Nikkei Asia",        "url": "https://asia.nikkei.com/rss/feed/nar",           "lang": "en"},
    # ── Google News theo truy vấn (không lọc thêm — truy vấn đã là bộ lọc) ──
    gnews_feed("GN Fed",            "Federal Reserve rates OR FOMC when:1d"),
    gnews_feed("GN Vietnam macro",  "Vietnam economy OR Vietnam tariff OR Vietnam exports when:1d"),
    gnews_feed("GN Oil",            "Brent crude OR OPEC when:1d"),
    gnews_feed("GN China macro",    "China economy OR PBOC OR yuan when:1d"),
    gnews_feed("GN Treasuries USD", "Treasury yields OR dollar index when:1d"),
]


def alert_feed_sources() -> list:
    out = []
    for f in _ALERT_FEEDS:
        if f.get("kind") == "gnews":
            out.append(gnews_source(f))
        else:
            out.append(rss_source(f, relevant=_relevant_en if f.get("lang") == "en" else _NO_FILTER))
    return out


def ticker_news_source(tickers: tuple) -> Source:
    """Adapter KHÔNG-RSS mẫu: tin theo mã qua vnstock (`fetch_ticker_news`).
    Mỗi mã một call API ⇒ chỉ bật cho vài mã (`VNSTOCK_NEWS_ALERT_TICKERS`)."""
    def _fetch() -> list:
        import vnstock_news as vn
        out: list = []
        for t in tickers:
            try:
                rows = vn.fetch_ticker_news(t)[:10]
            except Exception:
                rows = []
            for r in rows:
                link = next((r.get(k) for k in vn._LINK_KEYS if r.get(k)), "")
                out.append({"title": r.get("news_title") or r.get("title"),
                            "link": link, "summary": r.get("news_short_content"),
                            "published": r.get("public_date") or r.get("_date_sort"),
                            "ticker": t, "source_feed": f"vnstock · {t}"})
        return out

    return Source(key="vnstock:ticker-news", name="vnstock tin theo mã",
                  fetch=_fetch, kind="api", relevant=None)


def _default_sources() -> list:
    """RSS của pipeline (`_FEEDS`, lọc từ khoá Việt) + nguồn nước ngoài riêng
    cho cảnh báo (`_ALERT_FEEDS`)."""
    import vnstock_news_feeds as nf
    return [rss_source(f) for f in nf._FEEDS] + alert_feed_sources()


SOURCES: list = _default_sources()


def register_source(src: Source) -> None:
    """Module khác thêm nguồn (một dòng) — cùng key thì thay."""
    global SOURCES
    SOURCES = [s for s in SOURCES if s.key != src.key] + [src]


def _env_sources() -> list:
    raw = (os.environ.get(ENV_TICKERS) or "").strip()
    tickers = tuple(t.strip().upper() for t in raw.split(",") if t.strip())
    return [ticker_news_source(tickers)] if tickers else []


def enabled_sources(only: Optional[list] = None) -> list:
    """Nguồn sẽ chạy: registry + nguồn bật qua env, trừ `enabled=False`;
    `only` (hoặc env VNSTOCK_NEWS_ALERT_SOURCES) lọc theo key / tiền tố key."""
    allow = [k.strip().lower() for k in (only or
             (os.environ.get(ENV_SOURCES) or "").split(",")) if k and k.strip()]
    out = []
    for s in SOURCES + _env_sources():
        if not s.enabled:
            continue
        if allow and not any(s.key.lower().startswith(a) for a in allow):
            continue
        out.append(s)
    return out


# ── Chuẩn hoá ────────────────────────────────────────────────────────────────


def _one_line(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _iso_dt(raw) -> str:
    """ISO giờ địa phương 'YYYY-MM-DDTHH:MM:SS' từ chuỗi ngày/giờ thường gặp;
    '' nếu không đọc được. Chỉ có ngày ⇒ 'YYYY-MM-DDT00:00:00'."""
    s = _one_line(raw)
    if not s:
        return ""
    try:
        from vnstock_news_feeds import _parse_pubdatetime
        got = _parse_pubdatetime(s)
        if got:
            return got
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def normalize_item(raw: dict, src: Source) -> Optional[dict]:
    """Dict thô của BẤT KỲ nguồn → schema chung (cùng khoá với news_feeds để
    dedup/sentiment/brief dùng lại). None khi không có tiêu đề."""
    if not isinstance(raw, dict):
        return None
    title = _one_line(raw.get("title") or raw.get("news_title") or raw.get("headline"))
    if not title:
        return None
    published = raw.get("_published_at") or _iso_dt(
        raw.get("published") or raw.get("public_date") or raw.get("_date_sort"))
    date_sort = raw.get("_date_sort") or (published[:10] if published else "")
    return {
        "title": title,
        "news_title": title,
        "link": _one_line(raw.get("link") or raw.get("url") or raw.get("news_source_link")),
        "news_short_content": _one_line(raw.get("news_short_content") or raw.get("summary"))[:400],
        "source_feed": _one_line(raw.get("source_feed")) or src.name,
        "source_key": src.key,
        "source_kind": src.kind,
        "lang": src.lang,
        "ticker": _one_line(raw.get("ticker")).upper(),
        "_date_sort": date_sort,
        "_published_at": published,
        "_sentiment": "",
        "_impact": "",
    }


def collect(sources: list, max_workers: int = 8) -> "tuple[list[dict], dict[str, int]]":
    """Fetch song song mọi nguồn (một nguồn nổ = 0 tin, không kéo sập lượt) →
    chuẩn hoá → lọc liên quan. Trả (items, {key: số tin sau lọc})."""
    items: list = []
    counts: dict = {}
    if not sources:
        return items, counts

    def _one(src: Source) -> "tuple[Source, list]":
        try:
            return src, list(src.fetch() or [])
        except Exception:
            return src, []

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(sources)))) as pool:
        futs = [pool.submit(_one, s) for s in sources]
        for fut in as_completed(futs):
            try:
                src, raw = fut.result()
            except Exception:
                continue
            n = 0
            for r in raw:
                it = normalize_item(r, src)
                if it is None:
                    continue
                if src.relevant is not None:
                    try:
                        if not src.relevant(it):
                            continue
                    except Exception:
                        continue
                items.append(it)
                n += 1
            counts[src.key] = n
    return items, counts


# ── Cửa sổ giờ + khung giờ chạy ─────────────────────────────────────────────


def _parse_range(raw: str, default: tuple) -> tuple:
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", raw or "")
    if not m:
        return default
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if a <= b else default


def in_active_hours(now: datetime, hours: Optional[tuple] = None,
                    days: Optional[tuple] = None) -> "tuple[bool, str]":
    """Có đúng khung giờ gửi không (code gác, Task Scheduler là lớp ngoài)."""
    h0, h1 = hours or _parse_range(os.environ.get(ENV_HOURS, ""), DEFAULT_HOURS)
    d0, d1 = days or _parse_range(os.environ.get(ENV_DAYS, ""), DEFAULT_DAYS)
    wd = now.isoweekday()
    if not (d0 <= wd <= d1):
        day = "CN" if wd == 7 else f"thứ {wd + 1}"
        return False, f"{day} ngoài khung ngày {d0}-{d1} (ISO)"
    if not (h0 <= now.hour <= h1):
        return False, f"{now:%H:%M} ngoài khung giờ {h0:02d}-{h1:02d}h"
    return True, ""


def _published_dt(item: dict) -> Optional[datetime]:
    p = item.get("_published_at") or ""
    if p:
        try:
            return datetime.fromisoformat(p)
        except ValueError:
            pass
    return None


def within_window(item: dict, now: datetime, window_h: int) -> bool:
    """Tin trong `window_h` giờ qua. Có giờ đầy đủ ⇒ so giờ; chỉ có ngày ⇒ so
    ngày (ngày trong cửa sổ là giữ — sổ đã-thấy lo việc không gửi lại)."""
    cutoff = now - timedelta(hours=window_h)
    dt = _published_dt(item)
    if dt is not None:
        return dt >= cutoff
    d = item.get("_date_sort") or ""
    return bool(d) and d >= cutoff.date().isoformat()


ENV_MAX_CATCHUP_H = "VNSTOCK_NEWS_ALERT_MAX_CATCHUP_H"
DEFAULT_MAX_CATCHUP_H = 36        # T7 22:00 → T2 07:00 = 33h vẫn bắt được tin CN
CATCHUP_MARGIN_H = 1              # feed đăng muộn hơn giờ bài ⇒ nới thêm 1h


def effective_window_h(now: datetime, prev_status: Optional[dict], default_h: int,
                       max_catchup_h: Optional[int] = None) -> int:
    """Cửa sổ thật của lượt này. Bình thường = default (3h). Nếu lượt trước
    cách đây lâu hơn (qua đêm 22:00→07:00, cuối tuần, máy tắt) thì nới tới
    `covered_until` của lượt trước + 1h, kẹp `max_catchup_h` — không thì tin
    Fed lúc 01:00 VN rơi khỏi cửa sổ 3h của lượt 07:00 (lỗ hổng #32)."""
    cap = max_catchup_h if max_catchup_h is not None else \
        _env_int(ENV_MAX_CATCHUP_H, DEFAULT_MAX_CATCHUP_H, 1, 24 * 14)
    raw = (prev_status or {}).get("covered_until") or (prev_status or {}).get("ran_at") or ""
    try:
        last = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return default_h
    gap_h = (now - last).total_seconds() / 3600 + CATCHUP_MARGIN_H
    if gap_h <= default_h:
        return default_h
    import math
    return int(min(cap, math.ceil(gap_h)))


def item_hash(item: dict) -> str:
    from vnstock_news_feeds import _hash
    return _hash(item)


# ── Sổ đã thấy ───────────────────────────────────────────────────────────────


def _seen_path() -> Path:
    return _META / SEEN_NAME


def load_seen(path: Optional[Path] = None) -> dict:
    p = path or _seen_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), dict):
                return {"items": dict(data["items"])}
    except (OSError, ValueError):
        pass
    return {"items": {}}


def save_seen(seen: dict, path: Optional[Path] = None) -> None:
    p = path or _seen_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"saved_at": datetime.now().isoformat(timespec="seconds"),
                                 "items": seen.get("items", {})}, ensure_ascii=False),
                     encoding="utf-8")
    except OSError:
        pass


def prune_seen(seen: dict, now: datetime, days: int = SEEN_RETAIN_DAYS) -> dict:
    """Bản MỚI chỉ giữ bản ghi ≤ `days` ngày (không đụng dict vào)."""
    cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
    kept = {h: r for h, r in (seen.get("items") or {}).items()
            if isinstance(r, dict) and str(r.get("first_seen") or "") >= cutoff}
    return {"items": kept}


def _record(item: dict, score: Optional[dict], now: datetime) -> dict:
    rec = {
        "title": item.get("title", "")[:200],
        "link": item.get("link", "")[:400],
        "source": item.get("source_feed", "")[:60],
        "ticker": item.get("ticker", ""),
        "published": item.get("_published_at") or item.get("_date_sort") or "",
        "first_seen": now.isoformat(timespec="seconds"),
        "score": None, "nhan": "", "tac_dong": "",
        "sent": False,
    }
    if score:
        rec.update({"score": int(score["muc_do"]), "nhan": score.get("nhan", ""),
                    "tac_dong": score.get("tac_dong", "")})
    return rec


# ── Chấm mức độ ──────────────────────────────────────────────────────────────

SCORE_SYSTEM = (
    "Bạn là biên tập viên tài chính lọc TIN VĨ MÔ QUAN TRỌNG cho nhà đầu tư CỔ PHIẾU "
    "VIỆT NAM, đọc mỗi giờ. Mục tiêu là tin ảnh hưởng CẢ THỊ TRƯỜNG (tiền tệ, tỷ giá, "
    "lạm phát, chính sách, địa chính trị, dòng vốn, hàng hoá), KHÔNG phải tin riêng "
    "từng doanh nghiệp. Với TỪNG tin (mở đầu `### Tin i=<số>`), chấm:\n"
    "• muc_do (1–5) = mức ảnh hưởng tới thị trường chứng khoán VN trong vài phiên tới:\n"
    "  5 = sốc hệ thống (Fed/SBV đổi lãi suất điều hành, thuế quan áp lên VN, nâng/hạ "
    "hạng thị trường, chiến sự lớn, khủng hoảng thanh khoản, chính sách lớn về chứng "
    "khoán/BĐS/tín dụng có hiệu lực);\n"
    "  4 = vĩ mô/chính sách đáng kể (CPI/GDP/PMI bất ngờ, tỷ giá vượt mốc, SBV bơm/hút "
    "mạnh, room tín dụng, giá dầu/vàng biến động lớn, số liệu Mỹ/TQ làm đổi kỳ vọng Fed, "
    "khối ngoại bán/mua ròng kỷ lục, chính sách ngành lớn như thuế/BĐS/ngân hàng);\n"
    "  3 = đáng theo dõi (chính sách đang bàn, số liệu đúng kỳ vọng, phát ngôn quan "
    "chức, diễn biến thị trường thế giới bình thường, tin ngành hẹp);\n"
    "  2 = tin thường (tin riêng MỘT doanh nghiệp — kết quả kinh doanh, cổ tức, ĐHĐCĐ, "
    "nhân sự, kể cả VN30 — phân tích bình luận, khuyến nghị mã, tin lặp lại);\n"
    "  1 = phi kinh tế hoặc không liên quan (giải trí, thể thao, hình sự, đời sống).\n"
    "• nhan = TÍCH_CỰC | TIÊU_CỰC | TRUNG_LẬP theo chiều ảnh hưởng tới cổ phiếu VN; "
    "hai chiều/mơ hồ = TRUNG_LẬP. Nhãn phải CÙNG CHIỀU với tac_dong.\n"
    "• tac_dong = MỘT câu ≤ 22 từ nêu KÊNH ảnh hưởng tới ngành/nhóm cổ phiếu VN cụ thể "
    "(nêu tên ngành/mã), KHÔNG kể lại sự kiện. Chiều phải khớp tiêu đề (tin GIẢM thì "
    "mô tả theo chiều giảm). Tin muc_do 1 ⇒ tac_dong = \"không tác động trực tiếp\".\n"
    "Khắt khe: phần lớn tin là 2–3; chỉ chấm 4–5 khi thật sự thay đổi kỳ vọng của CẢ "
    "thị trường. Tin một doanh nghiệp chỉ lên 4 khi nó đổi kỳ vọng cả ngành/thị trường "
    "(vd ngân hàng lớn mất thanh khoản). Tin trùng SỰ KIỆN với tin khác trong lô — kể cả "
    "KHÁC NGÔN NGỮ (báo VN dịch lại tin nước ngoài) — ⇒ giữ nguyên tin đầu, tin sau chấm "
    "thấp hơn 1 bậc. Tin tiếng Anh: tac_dong vẫn viết TIẾNG VIỆT.\n"
    'Trả về DUY NHẤT JSON đúng schema {"results": [{"i": <i>, "muc_do": <1-5>, "nhan": '
    '"…", "tac_dong": "…"}]} — đủ MỌI i, không thêm chữ nào ngoài JSON.'
)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer"}, "muc_do": {"type": "integer"},
                       "nhan": {"type": "string"}, "tac_dong": {"type": "string"}},
        "required": ["i", "muc_do", "nhan", "tac_dong"]}}},
    "required": ["results"],
}

_LABEL_FALLBACK = {"tích_cực": "positive", "tích cực": "positive", "positive": "positive",
                   "tiêu_cực": "negative", "tiêu cực": "negative", "negative": "negative",
                   "trung_lập": "neutral", "trung lập": "neutral", "neutral": "neutral"}


def _label(raw) -> str:
    low = str(raw or "").lower()
    try:
        from vnstock_sentiment import _SENTIMENT_MAP as m
    except Exception:
        m = _LABEL_FALLBACK
    return next((v for k, v in m.items() if k in low), "neutral")


def _clean_impact(raw) -> str:
    try:
        from vnstock_brief_canon import sanitize_impact
        from vnstock_news_feeds import _strip_html
        return sanitize_impact(_strip_html(str(raw or "")))
    except Exception:
        return _one_line(raw)[:160]


def item_block(i: int, it: dict) -> str:
    """Khối user cho một tin — tiêu đề + tóm tắt (KHÔNG fetch thân bài: lượt
    giờ phải xong dưới một phút)."""
    lines = [f"### Tin i={i}", f"Nguồn: {it.get('source_feed', '')}"]
    if (it.get("lang") or "vi") != "vi":
        lines.append(f"Ngôn ngữ: {it['lang']}")
    if it.get("ticker"):
        lines.append(f"Mã: {it['ticker']}")
    if it.get("_published_at"):
        lines.append(f"Đăng: {it['_published_at'][:16].replace('T', ' ')}")
    lines.append(f"Tiêu đề: {it.get('title', '')}")
    summ = (it.get("news_short_content") or "").strip()
    if summ:
        lines.append(f"Tóm tắt: {summ[:300]}")
    return "\n".join(lines)


def parse_scores(data, n: int) -> "dict[int, dict]":
    """{i: {muc_do, nhan, tac_dong}} từ JSON model — i lạ / muc_do rác bị bỏ,
    muc_do kẹp 1–5, tac_dong dọn như khối tin brief."""
    out: dict = {}
    rows = (data or {}).get("results") if isinstance(data, dict) else None
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            i = int(r.get("i"))
            sc = int(float(r.get("muc_do")))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n):
            continue
        out[i] = {"muc_do": max(SCORE_MIN, min(SCORE_MAX, sc)),
                  "nhan": _label(r.get("nhan")),
                  "tac_dong": _clean_impact(r.get("tac_dong"))}
    return out


def score_items_cli(todo: list) -> "tuple[dict[int, dict], str | None]":
    """Cả lô MỘT call Claude Code. ({}, lỗi) khi CLI hỏng — chỗ gọi rơi về ladder."""
    if not todo:
        return {}, None
    try:
        import vnstock_claude_cli as vcc
    except Exception as e:
        return {}, f"không import được vnstock_claude_cli: {e}"
    user = "\n\n".join(item_block(i, it) for i, it in enumerate(todo))
    raw_t = (os.environ.get(ENV_CLI_TIMEOUT) or "").strip()
    timeout = vcc.cli_timeout_s(ENV_CLI_TIMEOUT) if raw_t else DEFAULT_CLI_TIMEOUT_S
    text, err, info = vcc.complete(user, system=SCORE_SYSTEM, json_schema=SCORE_SCHEMA,
                                   model=vcc.cli_model(ENV_CLI_MODEL),
                                   timeout_s=timeout, tag=TAG)
    print(vcc.outcome_line(TAG, info, text, err))
    if err:
        return {}, err
    data = info.get("structured")
    if not isinstance(data, dict):
        try:
            data = json.loads(text)
        except ValueError:
            return {}, "CLI trả chữ không phải JSON"
    got = parse_scores(data, len(todo))
    return got, (None if got else "JSON không có kết quả hợp lệ")


# Điểm từ khoá cho đường ladder (ladder chỉ trả nhãn + tác động, không có mức độ).
_TIER_HIGH = (
    "fed", "lãi suất điều hành", "ngân hàng nhà nước", "sbv", "tỷ giá", "thuế quan",
    "tariff", "nâng hạng", "vn-index", "vnindex", "gdp", "cpi", "lạm phát", "inflation",
    "chiến tranh", "xung đột", "trừng phạt", "sanction", "khối ngoại", "room tín dụng",
    "opec", "giá dầu", "oil", "recession", "suy thoái", "rate cut", "rate hike",
)
_TIER_MID = (
    "chứng khoán", "cổ phiếu", "trái phiếu", "tín dụng", "thanh khoản", "vàng", "gold",
    "bất động sản", "fdi", "xuất khẩu", "nhập khẩu", "ngân sách", "thuế", "chính phủ",
    "quốc hội", "market", "stocks", "economy", "treasury", "yield", "lợi suất", "pmi",
)


def heuristic_score(item: dict) -> int:
    hay = f"{item.get('title', '')} {item.get('news_short_content', '')}".lower()
    if any(k in hay for k in _TIER_HIGH):
        return 4
    if any(k in hay for k in _TIER_MID):
        return 3
    return 2


def score_items_ladder(todo: list) -> "dict[int, dict]":
    """Rơi về ladder free từng tin (`analyze_item` của news_feeds — cùng prompt
    chấm tin của brief): nhãn + tác động từ model, MỨC ĐỘ từ từ khoá. Không
    provider ⇒ {} (không gửi gì — không có bộ chấm thì không đẩy tin thô)."""
    out: dict = {}
    if not todo:
        return out
    try:
        import vnstock_news_feeds as nf
    except Exception:
        return out
    for i, it in enumerate(todo):
        probe = dict(it)
        probe["_user_text_tmp"] = item_block(i, it)       # không fetch Jina
        try:
            s, imp = nf.analyze_item(probe)
        except Exception:
            s, imp = "", ""
        if not imp:
            continue
        score = SCORE_MIN if nf._NO_IMPACT in imp.lower() else heuristic_score(it)
        out[i] = {"muc_do": score, "nhan": s or "neutral", "tac_dong": imp}
    return out


def score_items(todo: list, engine: Optional[str] = None) -> "tuple[dict[int, dict], str, str | None]":
    """(điểm, engine đã dùng, lỗi claude nếu có). Engine: env riêng bước
    `VNSTOCK_NEWS_ALERT_ENGINE` > `VNSTOCK_LLM_ENGINE` > ladder."""
    if not todo:
        return {}, "none", None
    if engine is None:
        try:
            import vnstock_claude_cli as vcc
            engine = vcc.engine_for(STEP)
        except Exception:
            engine = "ladder"
    err = None
    if engine == "claude":
        got, err = score_items_cli(todo)
        if got:
            return got, "claude", None
        print(f"[{TAG}] Claude Code không chấm được ({err}) — rơi về ladder")
    got = score_items_ladder(todo)
    return got, ("ladder" if got else "none"), err


# ── Chọn + dựng tin Telegram ────────────────────────────────────────────────


def select_to_send(seen: dict, min_score: int, max_send: int) -> "list[tuple[str, dict]]":
    """Tin đã chấm ≥ ngưỡng, CHƯA gửi — mức cao trước, mới trước; ≤ max_send."""
    cands = [(h, r) for h, r in (seen.get("items") or {}).items()
             if isinstance(r, dict) and isinstance(r.get("score"), int)
             and r["score"] >= min_score and not r.get("sent")]
    # hai lượt sort ổn định: mới trước, rồi điểm cao trước (cùng điểm giữ mới trước)
    cands.sort(key=lambda hr: (hr[1].get("published") or "", hr[1].get("first_seen") or ""),
               reverse=True)
    cands.sort(key=lambda hr: -hr[1]["score"])
    return cands[:max(0, max_send)]


_ICON = {5: "🔴", 4: "🟠", 3: "🟡", 2: "⚪", 1: "⚪"}
_ARROW = {"positive": "▲", "negative": "▼", "neutral": "◆"}
_ENGINE_LABEL = {"claude": "Claude Code", "ladder": "ladder free", "none": "chưa chấm",
                 "prev": "lượt trước (tin dư)"}


def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def format_message(recs: list, now: datetime, min_score: int = DEFAULT_MIN_SCORE,
                   engine: str = "none") -> str:
    """HTML Telegram (tag chỉ trong whitelist của vnstock_telegram: b/i). Link
    để trần — Telegram tự nhận; `send_message` escape `&`/`<`/`>` lạc."""
    lines = [f"📰 <b>Tin quan trọng</b> · {now:%H:%M %d/%m}", ""]
    for r in recs:
        sc = int(r.get("score") or 0)
        lines.append(f"{_ICON.get(sc, '⚪')} {sc}/5 · <b>{_one_line(r.get('title'))}</b>")
        if r.get("tac_dong"):
            lines.append(f"   {_ARROW.get(r.get('nhan'), '◆')} {_one_line(r['tac_dong'])}")
        meta = " · ".join(x for x in (_one_line(r.get("source")), _hhmm(r.get("published") or ""),
                                      r.get("ticker") or "") if x)
        if meta:
            lines.append(f"   <i>{meta}</i>")
        if r.get("link"):
            lines.append(f"   {r['link']}")
        lines.append("")
    lines.append(f"<i>{len(recs)} tin ≥ mức {min_score}/5 · chấm bởi "
                 f"{_ENGINE_LABEL.get(engine, engine)}</i>")
    return "\n".join(lines)


def _default_sender(text: str) -> dict:
    import vnstock_telegram as tg
    return tg.send_message(text)


# ── Marker ───────────────────────────────────────────────────────────────────


def _machine() -> str:
    try:
        from vnstock_rollup import get_hostname
        return get_hostname()
    except Exception:
        import socket
        return os.environ.get("COMPUTERNAME") or socket.gethostname() or "?"


def write_status(payload: dict) -> Optional[Path]:
    p = _META / STATUS_NAME
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    except OSError:
        return None


def read_status() -> Optional[dict]:
    try:
        data = json.loads((_META / STATUS_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# ── Một lượt ─────────────────────────────────────────────────────────────────


def run(*, now: Optional[datetime] = None, dry_run: bool = False, force: bool = False,
        min_score: Optional[int] = None, window_h: Optional[int] = None,
        max_send: Optional[int] = None, max_score: Optional[int] = None,
        sources: Optional[list] = None, engine: Optional[str] = None,
        sender: Optional[Callable[[str], dict]] = None) -> int:
    """Một lượt cảnh báo. Exit: 0 ok/không có gì · 1 cảnh báo (mọi nguồn rỗng,
    chấm hỏng, Telegram lỗi) · không bao giờ 2 (job giờ không được làm Task
    Scheduler báo fail cứng vì một feed ốm)."""
    _load_env()
    now = now or datetime.now()
    if not enabled():
        print(f"[{TAG}] tắt bằng {KILL_SWITCH}=0 — bỏ qua")
        return 0
    ok, why = in_active_hours(now)
    if not ok and not force:
        print(f"[{TAG}] ngoài khung giờ ({why}) — bỏ qua (thêm --force để chạy)")
        return 0
    min_score = min_score if min_score is not None else _env_int(ENV_MIN_SCORE, DEFAULT_MIN_SCORE, 1, 5)
    prev = read_status() or {}
    if window_h is None:
        base_h = _env_int(ENV_WINDOW_H, DEFAULT_WINDOW_H, 1, 168)
        window_h = effective_window_h(now, prev, base_h)
        if window_h > base_h:
            print(f"[{TAG}] bắt bù: cửa sổ {window_h}h (lượt trước "
                  f"{prev.get('covered_until') or prev.get('ran_at') or '?'})")
    max_send = max_send if max_send is not None else _env_int(ENV_MAX_SEND, DEFAULT_MAX_SEND, 1, 50)
    max_score = max_score if max_score is not None else _env_int(ENV_MAX_SCORE, DEFAULT_MAX_SCORE, 1, 200)

    srcs = sources if sources is not None else enabled_sources()
    items, counts = collect(srcs)
    fetched = sum(counts.values())
    print(f"[{TAG}] {len(srcs)} nguồn · {fetched} tin liên quan · "
          f"{sum(1 for v in counts.values() if v)} nguồn có tin")

    seen = prune_seen(load_seen(), now)
    fresh = [it for it in items if within_window(it, now, window_h)]
    try:
        from vnstock_news import deduplicate_news
        fresh, _ = deduplicate_news(fresh)
    except Exception:
        pass
    new = [it for it in fresh if item_hash(it) not in seen["items"]]
    new.sort(key=lambda x: x.get("_published_at") or x.get("_date_sort") or "", reverse=True)
    todo = new[:max_score]

    scored: dict = {}
    eng, claude_err = "none", None
    if todo:
        scored, eng, claude_err = score_items(todo, engine=engine)
        print(f"[{TAG}] {len(new)} tin mới trong {window_h}h · chấm {len(scored)}/{len(todo)} "
              f"bằng {eng}")
    else:
        print(f"[{TAG}] không có tin mới trong {window_h}h — không gọi LLM")

    for i, it in enumerate(todo):
        seen["items"][item_hash(it)] = _record(it, scored.get(i), now)

    picked = select_to_send(seen, min_score, max_send)
    sent, message_id, send_err = 0, None, None
    if picked:
        engine_label = eng if eng != "none" else "prev"
        text = format_message([r for _, r in picked], now, min_score, engine_label)
        if dry_run:
            print(f"[{TAG}] --dry-run: {len(picked)} tin sẽ gửi\n" + text)
        else:
            try:
                resp = (sender or _default_sender)(text)
                message_id = ((resp or {}).get("result") or {}).get("message_id")
                stamp = now.isoformat(timespec="seconds")
                for h, _ in picked:
                    seen["items"][h] = {**seen["items"][h], "sent": True, "sent_at": stamp}
                sent = len(picked)
                print(f"[{TAG}] ✅ gửi {sent} tin · message_id={message_id}")
            except Exception as e:
                send_err = f"{type(e).__name__}: {e}"
                print(f"[{TAG}] ❌ Telegram lỗi: {send_err} — giữ tin, lượt sau gửi lại")
    else:
        print(f"[{TAG}] không tin nào ≥ mức {min_score} — im lặng")

    if not dry_run:
        save_seen(seen)
    error = send_err or (claude_err if (todo and not scored) else None)
    if todo and not scored and not claude_err:
        error = "không có engine chấm (Claude tắt/hỏng, ladder không provider)"
    if fetched == 0 and srcs:
        error = error or "mọi nguồn đều rỗng — mạng hoặc feed hỏng"
    streak = (int(prev.get("error_streak") or 0) + 1) if (error and prev.get("error")) \
        else (1 if error else 0)        # badge doctor đỏ khi ≥3 lượt lỗi liền
    # covered_until: mốc tin đã được NHÌN — chỉ tiến khi có nguồn trả tin (lượt
    # mọi nguồn rỗng không được "nuốt" khoảng giờ đó).
    covered = now.isoformat(timespec="seconds") if fetched > 0 else \
        (prev.get("covered_until") or prev.get("ran_at"))
    status = {
        "ran_at": now.isoformat(timespec="seconds"),
        "covered_until": covered,
        "machine": _machine(),
        "dry_run": dry_run,
        "engine": eng,
        "claude_error": claude_err,
        "sources": counts,
        "fetched": fetched,
        "in_window": len(fresh),
        "new": len(new),
        "scored": len(scored),
        "picked": len(picked),
        "sent": sent,
        "message_id": message_id,
        "min_score": min_score,
        "window_h": window_h,
        "error": error,
        "error_streak": streak,
    }
    if not dry_run:
        write_status(status)
    return 1 if error else 0


def diag_sources(sources: Optional[list] = None, now: Optional[datetime] = None) -> int:
    """Thử TỪNG nguồn trên máy có mạng: số tin thô / sau lọc / mới nhất / giây.
    Exit 1 khi có nguồn rỗng (URL sai, chặn UA, hết feed) để user sửa `_ALERT_FEEDS`.
    Không ghi sổ, không gọi LLM, không gửi."""
    import time as _time
    now = now or datetime.now()
    srcs = sources if sources is not None else enabled_sources()
    print(f"[{TAG}] --diag {len(srcs)} nguồn (xác minh trên máy có mạng):")
    bad = 0
    for s in srcs:
        t0 = _time.time()
        try:
            raw = list(s.fetch() or [])
        except Exception as e:                      # noqa: BLE001 — diag phải chạy hết
            raw, err = [], f"{type(e).__name__}: {e}"
        else:
            err = ""
        items = [it for it in (normalize_item(r, s) for r in raw) if it]
        kept = [it for it in items if s.relevant is None or _safe_relevant(s, it)]
        newest = max((it.get("_published_at") or it.get("_date_sort") or "" for it in items),
                     default="")
        in3h = sum(1 for it in kept if within_window(it, now, DEFAULT_WINDOW_H))
        icon = "✅" if kept else ("⚠️" if raw else "❌")
        if not raw:
            bad += 1
        print(f"  {icon} {s.key:34s} thô {len(raw):3d} · lọc {len(kept):3d} · 3h {in3h:2d} · "
              f"mới nhất {newest[:16] or '—':16s} · {_time.time() - t0:4.1f}s {err}")
    print(f"[{TAG}] {len(srcs) - bad}/{len(srcs)} nguồn trả dữ liệu. ❌ = URL sai/chặn/hết "
          f"feed → sửa hoặc enabled=False trong _ALERT_FEEDS (nước ngoài) / _FEEDS (VN).")
    return 1 if bad else 0


def _safe_relevant(s: Source, it: dict) -> bool:
    try:
        return bool(s.relevant(it))
    except Exception:
        return False


def print_sources(sources: Optional[list] = None) -> None:
    for s in (sources if sources is not None else enabled_sources()):
        print(f"  {s.key:40s} {s.kind:4s} {s.lang:2s}  {s.name}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Cảnh báo tin quan trọng theo giờ → Telegram")
    ap.add_argument("--dry-run", action="store_true", help="in tin, không gửi, không ghi sổ")
    ap.add_argument("--force", action="store_true", help="bỏ cửa khung giờ/ngày")
    ap.add_argument("--min-score", type=int, default=None)
    ap.add_argument("--window-h", type=int, default=None)
    ap.add_argument("--max-send", type=int, default=None)
    ap.add_argument("--sources", default=None, help="lọc key nguồn (tiền tố, phẩy)")
    ap.add_argument("--engine", choices=["ladder", "claude"], default=None)
    ap.add_argument("--list-sources", action="store_true")
    ap.add_argument("--diag", action="store_true", help="thử từng nguồn, không gửi/ghi")
    a = ap.parse_args(argv)
    _load_env()
    only = [k for k in (a.sources or "").split(",") if k.strip()] or None
    if a.list_sources:
        print_sources(enabled_sources(only))
        return 0
    if a.diag:
        return diag_sources(enabled_sources(only))
    return run(dry_run=a.dry_run, force=a.force, min_score=a.min_score,
               window_h=a.window_h, max_send=a.max_send, engine=a.engine,
               sources=enabled_sources(only) if only else None)


if __name__ == "__main__":
    raise SystemExit(main())
