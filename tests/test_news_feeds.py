"""Tests for vnstock_news_feeds — RSS market-news fetch/parse/filter + brief wiring.

The live RSS fetch (requests) and LLM analysis (vnstock_sentiment) need network;
here we test the pure parsing/filter/dedup/cache logic with fixtures and the brief
block + guard.
"""
import json

import vnstock_news_feeds as nf


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Fed giu nguyen lai suat, chung khoan tang</title>
<link>https://x/1</link><pubDate>Mon, 15 Jun 2026 10:00:00 +0700</pubDate>
<description><![CDATA[<p>Lai suat &amp; ty gia on dinh</p>]]></description></item>
<item><title>Ca si A ra mat MV moi</title><link>https://x/2</link>
<pubDate>Mon, 15 Jun 2026 09:00:00 +0700</pubDate><description>giai tri</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>SBV bom rong thanh khoan he thong</title><link href="https://y/1"/>
<updated>2026-06-15T08:30:00+07:00</updated><summary>tin dung, ty gia</summary></entry>
</feed>"""


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_feed_rss_and_atom():
    a = nf.parse_feed(RSS, "RSS")
    assert len(a) == 2
    assert a[0]["title"].startswith("Fed giu")
    assert a[0]["_date_sort"] == "2026-06-15"
    assert a[0]["link"] == "https://x/1"
    assert "<p>" not in a[0]["news_short_content"] and "&" in a[0]["news_short_content"]
    b = nf.parse_feed(ATOM, "Atom")
    assert len(b) == 1 and b[0]["_date_sort"] == "2026-06-15"
    assert b[0]["link"] == "https://y/1"          # Atom link@href
    # garbage → [] (best-effort, never raises)
    assert nf.parse_feed(b"not xml", "x") == []


def test_parse_pubdate_handles_rfc822_and_iso():
    assert nf._parse_pubdate("Mon, 15 Jun 2026 10:00:00 +0700") == "2026-06-15"
    assert nf._parse_pubdate("2026-06-15T08:30:00+07:00") == "2026-06-15"
    assert nf._parse_pubdate("2026-06-15") == "2026-06-15"
    assert nf._parse_pubdate("rác") == ""


def test_strip_html():
    assert nf._strip_html("<p>Lãi suất &amp; tỷ giá</p>") == "Lãi suất & tỷ giá"


def test_is_relevant_keeps_market_drops_noise():
    items = nf.parse_feed(RSS, "RSS")
    rel = [it for it in items if nf._is_relevant(it)]
    titles = [it["title"] for it in rel]
    assert any("Fed" in t for t in titles)          # lãi suất/Fed → market
    assert not any("Ca si" in t for t in titles)    # entertainment → dropped


# ── analyze (LLM) parsing ────────────────────────────────────────────────────


def test_analyze_item_parses_sentiment_and_impact(monkeypatch):
    monkeypatch.setattr("vnstock_sentiment.chat_complete",
                        lambda *a, **k: "TIÊU_CỰC | Áp lực tỷ giá, bất lợi nhóm vay USD")
    s, imp = nf.analyze_item({"title": "VND mất giá mạnh"})
    assert s == "negative"
    assert imp == "Áp lực tỷ giá, bất lợi nhóm vay USD"
    # no provider → ('', '')
    monkeypatch.setattr("vnstock_sentiment.chat_complete", lambda *a, **k: None)
    assert nf.analyze_item({"title": "x"}) == ("", "")


def test_analyze_system_prompt_enforces_direction_consistency():
    # The impact must follow the headline's direction — guards against the
    # observed "giá vàng GIẢM → PNJ hưởng lợi từ giá vàng CAO" contradiction.
    assert "CHIỀU" in nf._ANALYZE_SYSTEM and "khớp tiêu đề" in nf._ANALYZE_SYSTEM
    assert "NGƯỢC" in nf._ANALYZE_SYSTEM


# ── refresh: dedup + merge prior analysis + cache ────────────────────────────


def test_refresh_dedups_filters_and_keeps_prior_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "_CACHE", tmp_path / "market_news_cache.json")
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u1"}, {"name": "B", "url": "u2"}])

    # Two feeds return the SAME market headline (cross-post) + one noise item.
    def _fake_fetch(feed):
        if feed["name"] == "A":
            return nf.parse_feed(RSS, "A")          # Fed item + entertainment
        return nf.parse_feed(ATOM, "B")             # SBV item

    monkeypatch.setattr(nf, "fetch_feed", _fake_fetch)
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("positive", "tác động X"))

    # Freeze "today" so the fixture dates (2026-06-15) are inside the window.
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 16)
    monkeypatch.setattr(nf, "_date", _FixedDate)

    items = nf.refresh(within_days=5, analyze=True, max_analyze=8)
    titles = [it["title"] for it in items]
    assert any("Fed" in t for t in titles) and any("SBV" in t for t in titles)
    assert not any("Ca si" in t for t in titles)             # noise filtered out
    assert all(it["_impact"] == "tác động X" for it in items)  # analyzed

    # Second refresh must NOT re-analyze (prior analysis kept) — analyze raises if called.
    def _boom(it):
        raise AssertionError("should not re-analyze cached items")
    monkeypatch.setattr(nf, "analyze_item", _boom)
    items2 = nf.refresh(within_days=5, analyze=True)
    assert all(it["_impact"] == "tác động X" for it in items2)


def _fixed_today(monkeypatch, y=2026, m=6, d=16):
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(y, m, d)
    monkeypatch.setattr(nf, "_date", _FixedDate)


def test_load_market_news_drops_no_impact_items(tmp_path, monkeypatch):
    p = tmp_path / "market_news_cache.json"
    monkeypatch.setattr(nf, "_CACHE", p)
    _fixed_today(monkeypatch)
    p.write_text(json.dumps({"items": [
        {"title": "Fed cắt lãi suất", "_date_sort": "2026-06-16",
         "_impact": "lợi cho ngân hàng"},
        {"title": "Tin địa chính trị xa", "_date_sort": "2026-06-16",
         "_impact": "không tác động trực tiếp"},
    ]}), encoding="utf-8")
    out = nf.load_market_news(within_days=3, limit=10, drop_no_impact=True)
    assert [o["title"] for o in out] == ["Fed cắt lãi suất"]   # noise dropped


def test_refresh_reanalyze_rescores_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "_CACHE", tmp_path / "c.json")
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u"}])
    monkeypatch.setattr(nf, "fetch_feed", lambda f: nf.parse_feed(RSS, "A"))
    _fixed_today(monkeypatch)

    monkeypatch.setattr(nf, "analyze_item", lambda it: ("neutral", "v1"))
    nf.refresh(within_days=5)
    assert nf.load_market_news(within_days=5)[0]["_impact"] == "v1"
    # a normal refresh keeps the cached v1
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("positive", "v2"))
    nf.refresh(within_days=5)
    assert nf.load_market_news(within_days=5)[0]["_impact"] == "v1"
    # reanalyze re-scores the newest with the new prompt → v2
    nf.refresh(within_days=5, reanalyze=True)
    assert nf.load_market_news(within_days=5)[0]["_impact"] == "v2"


def test_load_market_news_respects_window_and_limit(tmp_path, monkeypatch):
    p = tmp_path / "market_news_cache.json"
    monkeypatch.setattr(nf, "_CACHE", p)
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 16)
    monkeypatch.setattr(nf, "_date", _FixedDate)
    p.write_text(json.dumps({"items": [
        {"title": "moi", "_date_sort": "2026-06-16", "_impact": "x"},
        {"title": "cu", "_date_sort": "2026-06-01", "_impact": "y"},   # outside 3d
    ]}), encoding="utf-8")
    out = nf.load_market_news(within_days=3, limit=10)
    assert [o["title"] for o in out] == ["moi"]
    assert nf.load_market_news(within_days=3, limit=10, only_analyzed=True)


# ── brief block + guard ──────────────────────────────────────────────────────


def _ctx():
    return {"market_news": [
        {"title": "Fed giữ nguyên lãi suất", "_date_sort": "2026-06-15",
         "source_feed": "VnExpress", "_sentiment": "positive",
         "_impact": "Hỗ trợ dòng vốn ngoại"},
        {"title": "Giá dầu tăng do căng thẳng", "_date_sort": "2026-06-15",
         "source_feed": "CafeF", "_sentiment": "negative", "_impact": "Áp lực lạm phát"},
    ]}


def test_market_news_block_renders_icons_and_impact():
    import vnstock_brief as vb
    blk = vb._market_news_block(_ctx()["market_news"])
    assert "📰 Tin kinh tế/chính trị" in blk
    assert "🟢" in blk and "🔴" in blk
    assert "Fed giữ nguyên lãi suất" in blk and "Hỗ trợ dòng vốn ngoại" in blk


def test_enforce_market_news_canonicalizes_and_is_idempotent():
    import vnstock_brief as vb
    ctx = _ctx()
    brief = ("## 🎯 TLDR\nx\n\n## 📰 Tin kinh tế/chính trị nổi bật\n"
             "- Tin bịa không có thật\n\n## 💡 Đề xuất giao dịch\n- none\n")
    fixed = vb.enforce_market_news(brief, ctx)
    assert "Fed giữ nguyên lãi suất" in fixed and "Tin bịa" not in fixed
    assert "## 💡 Đề xuất giao dịch" in fixed                 # next section kept
    assert vb.enforce_market_news(fixed, ctx) == fixed        # idempotent
    assert vb.enforce_market_news(brief, {}) == brief          # no-op without ctx


def test_enforce_market_news_splices_over_denial():
    import vnstock_brief as vb
    brief = "## 🎯 TLDR\nKhông có tin kinh tế nổi bật hôm nay.\n"
    fixed = vb.enforce_market_news(brief, _ctx())
    assert "Fed giữ nguyên lãi suất" in fixed


def test_both_templates_have_market_news_section():
    import vnstock_brief as vb
    header = "## 📰 Tin kinh tế/chính trị nổi bật"
    assert vb._MORNING_TEMPLATE.count(header) == 1
    assert vb._AFTERNOON_TEMPLATE.count(header) == 1
