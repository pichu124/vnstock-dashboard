#!/usr/bin/env python3
"""vnstock_news_feeds.py — Tin kinh tế/chính trị diện rộng qua RSS (market news).

Bổ trợ cho ``vnstock_news.py`` (tin THEO MÃ từ vnstock company.news): module này
kéo tin VĨ MÔ / CHÍNH TRỊ ảnh hưởng thị trường — từ một bộ RSS feed MIỄN PHÍ
(báo tài chính VN + quốc tế). Lọc theo độ liên quan thị trường (từ khoá), dedup,
cache; brief hiển thị + LLM (``vnstock_sentiment``) chấm sentiment + tóm tắt tác
động 1 dòng.

Thiết kế:
  • Parse RSS bằng STDLIB (``xml.etree``) — KHÔNG thêm dependency (RSS 2.0/Atom).
  • Fetch best-effort qua ``requests`` (đã là dep). Feed lỗi → bỏ qua, không bịa.
  • Phân tích LLM CHỈ chạy cho tập đã lọc + top-N mới nhất (kiểm soát token), cache
    kết quả trong JSON nên không chấm lại.

Mạng: fetch RSS cần internet — chạy tốt trên MÁY LOCAL; web session bị egress
allowlist chặn (RSS không bị tường phí, chỉ là host chưa allowlist). Xác minh:

    python vnstock_news_feeds.py --diag          # thử từng feed, in số tin/feed
    python vnstock_news_feeds.py --refresh        # fetch + lọc + dedup + (LLM) → cache
    python vnstock_news_feeds.py --show

Cache: ``data_warehouse/_meta/market_news_cache.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as _date, datetime, timedelta as _td
from email.utils import parsedate_to_datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_CACHE = _REPO / "data_warehouse" / "_meta" / "market_news_cache.json"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Curated RSS feeds (free, no key). VN financial press covers global market-movers
# (Fed/oil/China) translated into Vietnamese, plus a couple of English sources.
# URLs are validated on a networked machine via --diag — prune dead ones here.
_FEEDS: list[dict] = [
    # ── Vietnam: vĩ mô / tài chính / chứng khoán ──
    {"name": "VnExpress Kinh doanh", "url": "https://vnexpress.net/rss/kinh-doanh.rss", "lang": "vi"},
    {"name": "VnExpress Thế giới",   "url": "https://vnexpress.net/rss/the-gioi.rss",   "lang": "vi"},
    {"name": "CafeF Vĩ mô-Đầu tư",   "url": "https://cafef.vn/vi-mo-dau-tu.rss",         "lang": "vi"},
    {"name": "CafeF Chứng khoán",    "url": "https://cafef.vn/thi-truong-chung-khoan.rss", "lang": "vi"},
    {"name": "CafeF Tài chính-NH",   "url": "https://cafef.vn/tai-chinh-ngan-hang.rss",  "lang": "vi"},
    {"name": "VnEconomy",            "url": "https://vneconomy.vn/chung-khoan.rss",      "lang": "vi"},
    {"name": "Tin nhanh CK (ĐTCK)",  "url": "https://www.tinnhanhchungkhoan.vn/rss/home.rss", "lang": "vi"},
    # ── Vĩ mô / chính sách (thêm 2026-07 từ khảo sát skill vimovietnam — nhóm
    # policy/vĩ mô trước đây thiếu hẳn. Diag 08/07: VnEconomy Tài chính ✅ 41
    # tin liên quan, Báo Chính phủ ✅ 29) ──
    {"name": "VnEconomy Tài chính",  "url": "https://vneconomy.vn/tai-chinh.rss",       "lang": "vi"},
    {"name": "Báo Chính phủ KT",     "url": "https://baochinhphu.vn/kinh-te.rss",        "lang": "vi"},
    # Báo Đầu tư: đã bỏ (08/07) — 2 slug đoán đều 404, không đoán tiếp. Muốn
    # thêm lại: lấy URL thật từ https://baodautu.vn/rssMain.html rồi thêm 1 dòng.
    # ── Quốc tế (tiếng Anh) ──
    {"name": "MarketWatch Top",      "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "lang": "en"},
    {"name": "CNBC Markets",         "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "lang": "en"},
    {"name": "Yahoo Finance",        "url": "https://finance.yahoo.com/news/rssindex", "lang": "en"},
]

# Market-moving economic + political keywords (lowercased). Feeds are already
# finance/macro categories, so this mainly drops obvious non-market items and
# filters the broad "Thế giới"/international feeds down to market-relevant ones.
_MARKET_KEYWORDS: tuple[str, ...] = (
    # tiền tệ / lãi suất / tỷ giá
    "lãi suất", "tỷ giá", "usd", "vnd", "fed", "frb", "ecb", "boj", "pboc",
    "chính sách tiền tệ", "ngân hàng nhà nước", "sbv", "nới lỏng", "thắt chặt",
    "bơm ròng", "hút ròng", "thanh khoản", "lợi suất", "trái phiếu",
    # vĩ mô
    "lạm phát", "cpi", "gdp", "tăng trưởng", "suy thoái", "kích thích",
    "thất nghiệp", "pmi", "fdi", "xuất khẩu", "nhập khẩu", "thương mại",
    "thuế", "tài khóa", "ngân sách", "tín dụng", "room tín dụng",
    # thị trường / hàng hoá
    "chứng khoán", "vn-index", "vnindex", "vn30", "khối ngoại", "cổ phiếu",
    "nâng hạng", "vàng", "dầu", "opec", "hàng hoá", "bất động sản",
    # chính trị / địa chính trị
    "chính phủ", "quốc hội", "chính sách", "chiến tranh", "xung đột", "căng thẳng",
    "trừng phạt", "cấm vận", "thuế quan", "địa chính trị", "bầu cử", "đàm phán",
    # english
    "rate", "inflation", "fed", "treasury", "yield", "tariff", "recession",
    "stimulus", "oil", "gold", "sanction", "stocks", "market", "economy",
)

_MAX_ANALYZE_DEFAULT = 8       # cap LLM calls per refresh (token control)
_RETAIN_DAYS = 30              # tin cũ giữ trong cache cho sub-tab Vĩ mô đọc lại
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ── Parsing helpers ──────────────────────────────────────────────────────────


def _localname(tag: str) -> str:
    """Tag without XML namespace, lowercased ('{...}item' → 'item')."""
    return str(tag).rsplit("}", 1)[-1].lower()


def _strip_html(s: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", s or "")).strip()


def _parse_pubdate(raw: str) -> str:
    """Normalise a feed date to ISO 'YYYY-MM-DD' ('' if unparseable).
    Handles RFC822 (RSS pubDate) and ISO 8601 (Atom updated/published)."""
    s = (raw or "").strip()
    if not s:
        return ""
    try:                                   # RFC822: 'Mon, 15 Jun 2026 10:00:00 +0700'
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:                                   # ISO 8601
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else ""


def parse_feed(content: "str | bytes", source: str = "") -> list[dict]:
    """Parse RSS 2.0 / Atom bytes into normalised items. [] on parse error."""
    out: list[dict] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return out
    for el in root.iter():
        if _localname(el.tag) not in ("item", "entry"):
            continue
        d: dict = {}
        for child in el:
            name = _localname(child.tag)
            if name == "link" and not d.get("link"):
                d["link"] = (child.text or child.get("href") or "").strip()
            elif name == "title":
                d["title"] = _strip_html(child.text or "")
            elif name in ("description", "summary", "content"):
                if not d.get("summary"):
                    d["summary"] = _strip_html(child.text or "")
            elif name in ("pubdate", "published", "updated", "date") and not d.get("_pub"):
                d["_pub"] = (child.text or "").strip()
        title = d.get("title", "")
        if not title:
            continue
        iso = _parse_pubdate(d.get("_pub", ""))
        out.append({
            "title": title,
            "news_title": title,                  # alias for dedup/sentiment reuse
            "link": d.get("link", ""),
            "news_short_content": d.get("summary", "")[:400],
            "source_feed": source,
            "ticker": "",                          # market-wide
            "_date_sort": iso,
            "_sentiment": "",
            "_impact": "",
        })
    return out


def _is_relevant(item: dict) -> bool:
    hay = f"{item.get('title','')} {item.get('news_short_content','')}".lower()
    return any(k in hay for k in _MARKET_KEYWORDS)


def _hash(item: dict) -> str:
    key = f"{(item.get('_date_sort') or '')[:10]}|{(item.get('title') or '').strip().lower()}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


# ── Fetch ────────────────────────────────────────────────────────────────────


def fetch_feed(feed: dict) -> list[dict]:
    """Fetch + parse one feed. [] on any failure (best-effort)."""
    try:
        import requests as _req
        resp = _req.get(feed["url"], headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
    except Exception:
        return []
    return parse_feed(resp.content, source=feed.get("name", ""))


# ── LLM analysis (sentiment + 1-line impact, one call) ───────────────────────

_ANALYZE_SYSTEM = (
    "Bạn phân tích tác động tin tức lên CỔ PHIẾU VIỆT NAM. Trả về DUY NHẤT 1 dòng:\n"
    "<TÍCH_CỰC|TIÊU_CỰC|TRUNG_LẬP> | <tác động>\n"
    "<tác động> = một câu (≤22 từ) nêu KÊNH ảnh hưởng tới NGÀNH/NHÓM CỔ PHIẾU VN "
    "cụ thể (nêu tên ngành/mã), KHÔNG kể lại sự kiện. Kênh: Fed/lãi suất→tỷ giá, "
    "ngân hàng, vốn ngoại; dầu→dầu khí GAS/PLX/BSR, vận tải; vàng→PNJ; tỷ giá/USD→"
    "nhóm vay USD, xuất khẩu (dệt may/thuỷ sản); đầu tư công→xây dựng, thép HPG; "
    "tín dụng→ngân hàng, BĐS; nhập siêu/CPI→sản xuất.\n"
    "NHÃN phải CÙNG CHIỀU <tác động>: hỗ trợ/tăng/hưởng lợi = TÍCH_CỰC; áp lực/"
    "giảm/bất lợi/tăng chi phí = TIÊU_CỰC; hai chiều/phụ thuộc = TRUNG_LẬP "
    "(vd 'PNJ hưởng lợi' ⇒ TÍCH_CỰC, KHÔNG được TIÊU_CỰC).\n"
    "CHIỀU <tác động> PHẢI khớp tiêu đề: tin nói GIẢM/rời mốc/xuống/lao dốc → mô "
    "tả theo chiều GIẢM; tin nói TĂNG/vượt/lập đỉnh → chiều TĂNG. TUYỆT ĐỐI KHÔNG "
    "mô tả chiều NGƯỢC với tiêu đề (vd tin 'giá vàng GIẢM / rời mốc 4.000 USD' "
    "KHÔNG được ghi 'PNJ hưởng lợi từ giá vàng CAO' — phải theo chiều giảm: 'PNJ: "
    "định giá tồn kho/giá vốn giảm theo' hoặc TRUNG_LẬP nếu tác động hai chiều).\n"
    "BẮT BUỘC: tin về vàng / dầu / lãi suất / tỷ giá / Fed / CPI / lạm phát / đầu "
    "tư công / tín dụng / xuất nhập khẩu LUÔN có kênh → PHẢI nêu ngành, TUYỆT ĐỐI "
    "KHÔNG trả 'không tác động'.\n"
    "CHỈ trả 'TRUNG_LẬP | không tác động trực tiếp' khi tin HOÀN TOÀN phi kinh tế "
    "(an ninh/quân sự/chính trị nước ngoài thuần tuý, hình sự, giải trí, thể thao).\n"
    "Chỉ in 1 dòng, không giải thích thêm."
)

# Nuanced analysis needs a stronger model than the 8B sentiment scorer — prefer a
# free 70B per provider, falling back to the provider default 8B if unavailable.
_ANALYZE_MODELS = {
    "Groq": "llama-3.3-70b-versatile",
    "Cerebras": "llama3.3-70b",
    "OpenRouter": "meta-llama/llama-3.3-70b-instruct:free",
}
# Impact sentinel for items with no clear VN-equity link → filtered from the brief.
_NO_IMPACT = "không tác động trực tiếp"


def analyze_item(item: dict) -> tuple[str, str]:
    """Return (sentiment, impact_line) for one item via the LLM, or ('','') when
    no provider is available. sentiment ∈ {positive,negative,neutral}."""
    try:
        from vnstock_sentiment import chat_complete, _SENTIMENT_MAP
    except Exception:
        return "", ""
    user = f"Tiêu đề: {item.get('title','')}"
    summ = (item.get("news_short_content") or "").strip()
    if summ:
        user += f"\nTóm tắt: {summ[:300]}"
    raw = chat_complete(_ANALYZE_SYSTEM, user, max_tokens=120, model_map=_ANALYZE_MODELS)
    if not raw:
        return "", ""
    head, _, impact = raw.partition("|")
    low = head.lower()
    sentiment = next((v for k, v in _SENTIMENT_MAP.items() if k in low), "neutral")
    return sentiment, _strip_html(impact)[:160]


# ── Cache I/O ────────────────────────────────────────────────────────────────


def _load_cache() -> list[dict]:
    try:
        if _CACHE.exists():
            data = json.loads(_CACHE.read_text(encoding="utf-8"))
            return data.get("items", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        pass
    return []


def _save_cache(items: list[dict]) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(
            json.dumps({"fetched_at": datetime.now().isoformat(), "items": items},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# ── Refresh / load ───────────────────────────────────────────────────────────


def refresh(within_days: int = 4, analyze: bool = True,
            max_analyze: int = _MAX_ANALYZE_DEFAULT, max_workers: int = 8,
            reanalyze: bool = False) -> list[dict]:
    """Fetch all feeds → filter (relevance) → dedup → merge with cache (keep prior
    analysis) → LLM-analyze the newest still-unanalyzed items (≤ max_analyze) →
    save. Returns the saved items (newest first). Best-effort throughout.

    reanalyze=True re-scores the newest `max_analyze` items even if already
    analyzed (use after changing the analysis prompt); older items keep theirs.
    """
    raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_feed, f): f for f in _FEEDS}
        for fut in as_completed(futures):
            try:
                raw.extend(fut.result())
            except Exception:
                pass

    cutoff = (_date.today() - _td(days=within_days)).isoformat()
    items = [it for it in raw
             if _is_relevant(it) and (it.get("_date_sort") or "") >= cutoff]

    # Dedup near-identical headlines (cross-posted across sources).
    try:
        from vnstock_news import deduplicate_news
        items, _ = deduplicate_news(items)
    except Exception:
        pass

    # Merge prior analysis so we never re-score a known item.
    prior = {_hash(it): it for it in _load_cache()}
    for it in items:
        p = prior.get(_hash(it))
        if p:
            it["_sentiment"] = it["_sentiment"] or p.get("_sentiment", "")
            it["_impact"] = it["_impact"] or p.get("_impact", "")

    items.sort(key=lambda x: x.get("_date_sort") or "", reverse=True)

    if analyze:
        if reanalyze:
            todo = items[:max_analyze]            # re-score newest with new prompt
            for it in todo:
                it["_sentiment"], it["_impact"] = "", ""
        else:
            todo = [it for it in items if not it.get("_impact")][:max_analyze]
        for it in todo:
            s, imp = analyze_item(it)
            if s:
                it["_sentiment"] = s
            if imp:
                it["_impact"] = imp

    # Giữ lại tin CŨ đã có trong cache (≤ _RETAIN_DAYS) — fetch window chỉ vài
    # ngày nên nếu không, mỗi refresh GHI ĐÈ cache cụt còn ~4 ngày; sub-tab
    # Vĩ mô (dashboard) cần đọc lại tin theo ngày dài hơn. Brief không đổi
    # hành vi: load_market_news vẫn lọc within_days riêng của nó.
    fresh = {_hash(it) for it in items}
    keep_cutoff = (_date.today() - _td(days=_RETAIN_DAYS)).isoformat()
    items += [p for h, p in prior.items()
              if h not in fresh and (p.get("_date_sort") or "") >= keep_cutoff]
    items.sort(key=lambda x: x.get("_date_sort") or "", reverse=True)

    _save_cache(items)
    return items


def load_market_news(within_days: int = 3, limit: int = 8,
                     only_analyzed: bool = False,
                     drop_no_impact: bool = False) -> list[dict]:
    """Recent market news from cache (newest first). only_analyzed → keep items
    that have an LLM impact line. drop_no_impact → drop items the LLM marked as
    having no direct VN-equity impact (filtered before slicing to `limit`).
    [] when cache missing/empty."""
    cutoff = (_date.today() - _td(days=within_days)).isoformat()
    items = [it for it in _load_cache() if (it.get("_date_sort") or "") >= cutoff]
    if only_analyzed:
        items = [it for it in items if it.get("_impact")]
    if drop_no_impact:
        items = [it for it in items
                 if _NO_IMPACT not in (it.get("_impact") or "").lower()]
    items.sort(key=lambda x: x.get("_date_sort") or "", reverse=True)
    return items[:limit]


# ── CLI ──────────────────────────────────────────────────────────────────────


def _diag() -> int:
    ok = 0
    print(f"[news-feeds] thử {len(_FEEDS)} feed (xác minh trên máy có mạng):")
    for f in _FEEDS:
        items = fetch_feed(f)
        rel = [it for it in items if _is_relevant(it)]
        flag = "✅" if items else "❌"
        if items:
            ok += 1
        print(f"  {flag} {f['name']:<22} {len(items):>3} tin / {len(rel):>3} liên quan  "
              f"({f['url']})")
    print(f"[news-feeds] {ok}/{len(_FEEDS)} feed trả dữ liệu. "
          f"Feed ❌ → URL sai/chặn, sửa trong _FEEDS.")
    return 0 if ok else 1


def _show(limit: int = 12) -> None:
    items = load_market_news(within_days=7, limit=limit)
    if not items:
        print(f"[news-feeds] cache rỗng ({_CACHE}). Chạy --refresh.")
        return
    for it in items:
        tag = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(it.get("_sentiment"), "·")
        print(f"  {tag} [{it.get('_date_sort','?')}] {it.get('title','')[:90]}")
        if it.get("_impact"):
            print(f"      → {it['_impact']}  ({it.get('source_feed','')})")


def main(argv: "list[str] | None" = None) -> int:
    # Load API keys from .env so the LLM analysis (sentiment + impact) works when
    # this module is run standalone (run.py news / the brief load .env themselves).
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Tin kinh tế/chính trị diện rộng (RSS).")
    ap.add_argument("--refresh", action="store_true", help="Fetch + lọc + dedup + LLM → cache")
    ap.add_argument("--no-analyze", action="store_true", help="Bỏ bước LLM (chỉ lọc + cache)")
    ap.add_argument("--reanalyze", action="store_true",
                    help="Chấm lại top tin mới bằng prompt hiện tại (sau khi đổi prompt)")
    ap.add_argument("--diag", action="store_true", help="Thử từng feed, in số tin trả về")
    ap.add_argument("--show", action="store_true", help="In tin trong cache")
    ap.add_argument("--within", type=int, default=4, help="Cửa sổ ngày khi refresh")
    ap.add_argument("--max-analyze", type=int, default=_MAX_ANALYZE_DEFAULT)
    a = ap.parse_args(argv)

    if a.diag:
        return _diag()
    if a.refresh:
        items = refresh(within_days=a.within, analyze=not a.no_analyze,
                        max_analyze=a.max_analyze, reanalyze=a.reanalyze)
        n_an = sum(1 for it in items if it.get("_impact"))
        print(f"[news-feeds] cache: {len(items)} tin liên quan, {n_an} đã phân tích.")
        _show()
        return 0
    if a.show:
        _show()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
