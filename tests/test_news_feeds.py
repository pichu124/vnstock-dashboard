"""Tests for vnstock_news_feeds — RSS market-news fetch/parse/filter + brief wiring.

The live RSS fetch (requests) and LLM analysis (vnstock_sentiment) need network;
here we test the pure parsing/filter/dedup/cache logic with fixtures and the brief
block + guard.
"""
import json

import vnstock_news_feeds as nf


def _ex(text, truncated=False):
    """Đáp án của `chat_complete_ex`: dict kèm cờ provider-cắt. None = cạn thang."""
    if text is None:
        return None
    return {"text": text, "model": "Fake:m",
            "finish_reason": "length" if truncated else "stop",
            "truncated": truncated}


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
    # tắt route trả phí để test hermetic (máy thật có ANTHROPIC_API_KEY)
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "0")
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TIÊU_CỰC | Áp lực tỷ giá, bất lợi nhóm vay USD"))
    s, imp = nf.analyze_item({"title": "VND mất giá mạnh"})
    assert s == "negative"
    assert imp == "Áp lực tỷ giá, bất lợi nhóm vay USD"
    # no provider → ('', '')
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex", lambda *a, **k: None)
    assert nf.analyze_item({"title": "x"}) == ("", "")


def test_analyze_item_refuses_impact_the_provider_cut_short(monkeypatch, caplog):
    """Close 08/09: khối tin in "— tác động: Nh" và "— tác động: Tỷ giá" —
    cắt GIỮA TỪ, không có "…" ⇒ không phải sanitize_impact mà là provider cắt
    ở max_tokens. Câu cụt trông y hệt câu ngắn hợp lệ, và refresh giữ phân
    tích cũ mãi ⇒ phải TỪ CHỐI ngay ở đường ghi (trả ('','') = chưa chấm)."""
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "0")
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TRUNG_LẬP | Nh", truncated=True))
    item = {"title": "Điện tử nhập siêu 60 tỷ USD"}
    with caplog.at_level("WARNING"):
        assert nf.analyze_item(item) == ("", "")
    # từ chối thì phải để VẾT: đánh dấu trên item (CLI/--show đọc) + log
    assert item["_impact_cut"] == "Fake:m"
    assert "provider cắt" in caplog.text and "Điện tử nhập siêu" in caplog.text
    # đối chứng: cùng chữ nhưng provider dừng tự nhiên → chấm bình thường,
    # và vết cũ được xoá
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TRUNG_LẬP | Nh"))
    assert nf.analyze_item(item) == ("neutral", "Nh")
    assert "_impact_cut" not in item


def test_refresh_leaves_a_cut_short_item_unanalyzed_for_the_next_run(tmp_path, monkeypatch):
    """Hệ quả ở tầng refresh: tin bị từ chối KHÔNG được ghi `_impact`, nên lượt
    refresh sau vẫn thấy nó trong hàng đợi chưa chấm (thay vì cache câu cụt)."""
    monkeypatch.setattr(nf, "_CACHE", tmp_path / "market_news.json")
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u1"}])
    monkeypatch.setattr(nf, "fetch_feed", lambda feed: nf.parse_feed(RSS, "A"))
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 16)
    monkeypatch.setattr(nf, "_date", _FixedDate)
    calls = []

    def _cut(it):
        calls.append(it["title"])
        return "", ""                       # analyze_item từ chối câu cụt
    monkeypatch.setattr(nf, "analyze_item", _cut)
    items = nf.refresh(within_days=5, analyze=True, max_analyze=8)
    assert calls and all(not it.get("_impact") for it in items)
    # lượt sau: vẫn đem ra chấm lại (không bị coi là "đã phân tích")
    calls.clear()
    nf.refresh(within_days=5, analyze=True, max_analyze=8)
    assert calls


def test_cli_refresh_summary_counts_cut_items_and_show_explains_them(monkeypatch, capsys):
    """09/09 user chạy `--refresh --reanalyze`, 3/8 tin trống mà console không
    nói vì sao. Tổng kết phải đếm số bị cắt, --show phải ghi lý do ngay dưới tin."""
    items = [
        {"title": "A", "_date_sort": "2026-09-09", "_sentiment": "positive",
         "_impact": "x", "source_feed": "F"},
        {"title": "B", "_date_sort": "2026-09-09", "_sentiment": "", "_impact": "",
         "_impact_cut": "Gemini:gemini-3.5-flash"},
    ]
    monkeypatch.setattr(nf, "refresh", lambda **k: items)
    monkeypatch.setattr(nf, "load_market_news", lambda **k: items)
    assert nf.main(["--refresh"]) == 0
    out = capsys.readouterr().out
    assert "1 đã phân tích, 1 bỏ vì provider cắt giữa câu" in out
    assert "✂ provider cắt giữa câu (Gemini:gemini-3.5-flash)" in out
    # không có tin bị cắt → tổng kết không thêm mệnh đề thừa
    monkeypatch.setattr(nf, "refresh", lambda **k: items[:1])
    monkeypatch.setattr(nf, "load_market_news", lambda **k: items[:1])
    nf.main(["--refresh"])
    assert "bỏ vì provider cắt" not in capsys.readouterr().out


def test_reanalyze_clears_the_cut_marker_before_rescoring(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "_CACHE", tmp_path / "market_news.json")
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u1"}])
    monkeypatch.setattr(nf, "fetch_feed", lambda feed: nf.parse_feed(RSS, "A"))
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 16)
    monkeypatch.setattr(nf, "_date", _FixedDate)

    def _cut(it):
        it["_impact_cut"] = "Fake:m"
        return "", ""
    monkeypatch.setattr(nf, "analyze_item", _cut)
    items = nf.refresh(within_days=5, analyze=True)
    assert all(it.get("_impact_cut") for it in items)
    # lượt sau chấm được → vết phải biến mất (reanalyze xoá trước khi chấm)
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("positive", "ok"))
    items = nf.refresh(within_days=5, analyze=True, reanalyze=True)
    assert all(it["_impact"] == "ok" and "_impact_cut" not in it for it in items)


def test_analyze_item_asks_for_a_wide_token_cap_up_front(monkeypatch):
    """Ledger 09/09: ~nửa câu đầu bị cắt ở 256 (model suy nghĩ tiêu trần) rồi
    phải gọi lại — trả tiền hai lần và bắn hai call sát nhau (429). Kê rộng từ
    đầu; retry ×3 chỉ còn là lưới."""
    monkeypatch.setenv(nf._ANALYZE_PAID_ENV, "0")
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    seen = {}

    def _fake(system, user, max_tokens=None, model_map=None):
        seen["max_tokens"] = max_tokens
        return _ex("TÍCH_CỰC | ok")
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex", _fake)
    nf.analyze_item({"title": "t"})
    assert seen["max_tokens"] == nf._ANALYZE_MAX_TOKENS >= 768


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


# ── full text qua Jina Reader (best-effort) ──────────────────────────────────


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_fulltext_strips_jina_preamble_and_markdown(monkeypatch):
    jina = ("Title: Bài báo\nURL Source: https://x/1\nMarkdown Content:\n"
            "Đoạn 1 có ![ảnh](https://img/1.png) và [liên kết](https://x) trong bài.\n\n"
            "Đoạn   2.")
    captured = {}

    def _fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _FakeResp(jina)

    monkeypatch.setattr("requests.get", _fake_get)
    out = nf.fetch_fulltext("https://x/1")
    assert captured["url"] == "https://r.jina.ai/https://x/1"
    assert out == "Đoạn 1 có và liên kết trong bài. Đoạn 2."
    assert "Title:" not in out and "![" not in out


def test_fetch_fulltext_truncates_at_word_boundary(monkeypatch):
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _FakeResp("từ " * 2000))
    out = nf.fetch_fulltext("https://x/1")
    assert len(out) <= nf._FULLTEXT_MAX_CHARS
    assert out.endswith("từ")                # cắt tại ranh giới từ, không lửng


def test_fetch_fulltext_rejects_non_http_and_survives_errors(monkeypatch):
    def _boom(*a, **k):
        raise OSError("mạng chặn")
    monkeypatch.setattr("requests.get", _boom)
    assert nf.fetch_fulltext("") == ""                       # không có link
    assert nf.fetch_fulltext("ftp://x") == ""                # không phải http
    assert nf.fetch_fulltext("https://x/1") == ""            # lỗi mạng → ''


def test_fetch_fulltext_sends_jina_key_when_present(monkeypatch):
    captured = {}

    def _fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers or {}
        return _FakeResp("Markdown Content:\nbody")

    monkeypatch.setattr("requests.get", _fake_get)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    nf.fetch_fulltext("https://x/1")
    assert "Authorization" not in captured["headers"]
    monkeypatch.setenv("JINA_API_KEY", "jk")
    nf.fetch_fulltext("https://x/1")
    assert captured["headers"]["Authorization"] == "Bearer jk"


def test_analyze_item_feeds_fulltext_into_prompt(monkeypatch):
    prompts = {}

    def _fake_chat(system, user, **k):
        prompts["user"] = user
        return _ex("TÍCH_CỰC | Ngân hàng hưởng lợi")

    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex", _fake_chat)
    monkeypatch.setattr(nf, "fetch_fulltext", lambda url, **k: "THÂN BÀI ĐẦY ĐỦ")
    monkeypatch.delenv("VNSTOCK_NEWS_FULLTEXT", raising=False)
    s, imp = nf.analyze_item({"title": "SBV hạ lãi suất",
                              "link": "https://x/1"})
    assert s == "positive"
    assert "Nội dung bài (rút gọn): THÂN BÀI ĐẦY ĐỦ" in prompts["user"]
    assert prompts["user"].startswith("Tiêu đề: SBV hạ lãi suất")


def test_analyze_item_fulltext_disabled_by_env(monkeypatch):
    def _boom(url, **k):
        raise AssertionError("không được fetch fulltext khi đã tắt")
    monkeypatch.setattr(nf, "fetch_fulltext", _boom)
    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex",
                        lambda *a, **k: _ex("TRUNG_LẬP | x"))
    monkeypatch.setenv("VNSTOCK_NEWS_FULLTEXT", "0")
    s, _ = nf.analyze_item({"title": "t", "link": "https://x/1"})
    assert s == "neutral"


def test_analyze_item_fulltext_failure_keeps_title_summary(monkeypatch):
    prompts = {}

    def _fake_chat(system, user, **k):
        prompts["user"] = user
        return _ex("TIÊU_CỰC | y")

    monkeypatch.setattr("vnstock_sentiment.chat_complete_ex", _fake_chat)
    monkeypatch.setattr(nf, "fetch_fulltext", lambda url, **k: "")   # fail → ''
    monkeypatch.delenv("VNSTOCK_NEWS_FULLTEXT", raising=False)
    nf.analyze_item({"title": "t", "news_short_content": "tóm tắt",
                     "link": "https://x/1"})
    assert "Nội dung bài" not in prompts["user"]
    assert "Tóm tắt: tóm tắt" in prompts["user"]


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


def test_refresh_retains_old_cached_items_within_retention(tmp_path, monkeypatch):
    # Fetch window chỉ vài ngày — tin CŨ trong cache (≤ _RETAIN_DAYS) phải được
    # GIỮ LẠI qua refresh (sub-tab Vĩ mô đọc lại theo ngày), tin quá hạn bị bỏ.
    import json
    p = tmp_path / "market_news_cache.json"
    monkeypatch.setattr(nf, "_CACHE", p)
    monkeypatch.setattr(nf, "_FEEDS", [{"name": "A", "url": "u"}])
    monkeypatch.setattr(nf, "fetch_feed", lambda f: nf.parse_feed(RSS, "A"))
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("positive", "x"))
    _fixed_today(monkeypatch)                    # today = 2026-06-16

    old = {"title": "Tin lãi suất 10 ngày trước", "news_title": "Tin lãi suất 10 ngày trước",
           "link": "", "news_short_content": "", "source_feed": "A", "ticker": "",
           "_date_sort": "2026-06-06", "_sentiment": "neutral", "_impact": "cũ"}
    ancient = dict(old, title="Tin 40 ngày trước", news_title="Tin 40 ngày trước",
                   _date_sort="2026-05-07")
    p.write_text(json.dumps({"items": [old, ancient]}, ensure_ascii=False),
                 encoding="utf-8")

    items = nf.refresh(within_days=5, analyze=True)
    titles = [it["title"] for it in items]
    assert "Tin lãi suất 10 ngày trước" in titles          # giữ (≤30 ngày)
    assert "Tin 40 ngày trước" not in titles               # quá retention → bỏ
    assert any("Fed" in t for t in titles)                 # tin mới vẫn vào
    # thứ tự vẫn mới-nhất-trước
    dates = [it.get("_date_sort") or "" for it in items]
    assert dates == sorted(dates, reverse=True)


def test_cli_reanalyze_alone_implies_refresh(monkeypatch):
    # `--reanalyze` trần từng rơi xuống print_help (không chạy gì) — phải
    # tương đương `--refresh --reanalyze` như CLAUDE.md hướng dẫn.
    calls = {}

    def _fake_refresh(within_days, analyze, max_analyze, reanalyze):
        calls.update(reanalyze=reanalyze, analyze=analyze)
        return []

    monkeypatch.setattr(nf, "refresh", _fake_refresh)
    monkeypatch.setattr(nf, "_show", lambda *a, **k: None)
    assert nf.main(["--reanalyze"]) == 0
    assert calls == {"reanalyze": True, "analyze": True}


# ── ngày lệch chuẩn (--diag desktop 02/10: Báo Chính phủ + Nikkei "mới nhất —") ──


import pytest as _pytest


@_pytest.mark.parametrize("raw,day,hhmm", [
    ("Thu, 02 Oct 2026 19:00:00 GMT+7", "2026-10-02", "19:00"),
    ("Thu, 02 Oct 2026 19:00:00 GMT+07:00", "2026-10-02", "19:00"),
    ("02/10/2026 19:00", "2026-10-02", "19:00"),
    ("Thứ năm, 02/10/2026 - 19:00", "2026-10-02", "19:00"),
    ("2/10/2026", "2026-10-02", "00:00"),
    ("2026/10/02 19:00:00", "2026-10-02", "19:00"),
])
def test_loose_dates_parse_in_vietnam_time(raw, day, hhmm, monkeypatch):
    import time as _t
    monkeypatch.setenv("TZ", "Asia/Ho_Chi_Minh")
    if hasattr(_t, "tzset"):
        _t.tzset()
    try:
        assert nf._parse_pubdate(raw) == day
        assert nf._parse_pubdatetime(raw) == f"{day}T{hhmm}:00"
    finally:
        monkeypatch.undo()
        if hasattr(_t, "tzset"):
            _t.tzset()


def test_gmt_plus_offset_is_not_silently_dropped():
    """parsedate_to_datetime('… GMT+7') trả giờ KHÔNG tz (bỏ +7) — phải chuẩn hoá trước."""
    assert nf._norm_tz_words("Thu, 02 Oct 2026 19:00:00 GMT+7").endswith(" +0700")
    assert nf._norm_tz_words("Thu, 02 Oct 2026 19:00:00 UTC-05:30").endswith(" -0530")
    assert nf._norm_tz_words("Thu, 02 Oct 2026 19:00:00 GMT") == "Thu, 02 Oct 2026 19:00:00 GMT"


def test_standard_dates_unchanged_and_garbage_still_empty():
    assert nf._parse_pubdate("Mon, 15 Jun 2026 10:00:00 +0700") == "2026-06-15"
    assert nf._parse_pubdate("2026-06-15T08:30:00+07:00") == "2026-06-15"
    assert nf._parse_pubdate("rác") == "" and nf._parse_pubdatetime("rác") == ""
    assert nf._parse_pubdate("") == "" and nf._parse_pubdatetime("") == ""


@_pytest.mark.parametrize("raw,expected", [
    # Báo Chính phủ (--diag desktop 02/10): ASP.NET kiểu Mỹ tháng/ngày + AM/PM
    ("10/2/2026 11:56:00 AM", "2026-10-02T11:56:00"),
    ("10/1/2026 9:05:00 PM", "2026-10-01T21:05:00"),
    ("10/2/2026 12:15:00 AM", "2026-10-02T00:15:00"),
    ("9/30/2026 8:00 AM", "2026-09-30T08:00:00"),       # 30 không thể là tháng ⇒ chỉ một cách hiểu
    # kiểu VN ngày/tháng vẫn đúng
    ("02/10/2026 19:00", "2026-10-02T19:00:00"),
    ("30/9/2026 08:00", "2026-09-30T08:00:00"),
    ("12/10/2026", "2026-10-12T00:00:00"),               # cả hai cách hiểu đều tương lai ⇒ gần nhất
])
def test_ambiguous_day_month_picks_reading_closest_to_now(raw, expected):
    from datetime import datetime as _dt
    got = nf._parse_dt_loose(raw, now=_dt(2026, 10, 2, 20, 20))
    assert got is not None and got.isoformat(timespec="seconds") == expected


def test_parse_feed_keeps_short_raw_date_for_diag():
    rss = (b"<?xml version='1.0'?><rss><channel>"
           b"<item><title>A</title><link>https://a</link><pubDate>2 thang 10</pubDate></item>"
           b"<item><title>B</title><link>https://b</link></item>"
           b"<item><title>C</title><link>https://c</link><pubDate>Fri, 02 Oct 2026 09:00:00 +0700</pubDate></item>"
           b"</channel></rss>")
    a, b, c = nf.parse_feed(rss, "X")
    assert a["_pub_raw"] == "2 thang 10" and b["_pub_raw"] == "(feed không có thẻ ngày)"
    assert c["_pub_raw"] == "Fri, 02 Oct 2026 09:00:00 +0700" and c["_date_sort"] == "2026-10-02"
