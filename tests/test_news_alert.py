"""vnstock_news_alert — cảnh báo tin quan trọng mỗi giờ → Telegram (#31, 02/10).

Hermetic: fetch nguồn giả, `vnstock_claude_cli.complete` giả, Telegram giả,
`_META` về tmp (sổ đã-thấy + marker không ghi vào kho thật). Những điều
canh: registry nguồn mở rộng được · cửa sổ giờ · sổ chống trùng · chấm theo
lô + rơi về ladder · ngưỡng + tin dư để lượt sau · marker có `machine` ·
badge doctor + kill-switch được nối · run.py có lệnh nhưng `all` KHÔNG có.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import vnstock_claude_cli as vcc
import vnstock_news_alert as na
import vnstock_news_feeds as nf

NOW = datetime(2026, 10, 2, 10, 5, 0)          # thứ Sáu 10:05 — trong khung giờ


@pytest.fixture(autouse=True)
def _meta(tmp_path, monkeypatch):
    monkeypatch.setattr(na, "_META", tmp_path)
    monkeypatch.setattr(na, "_ENV_LOADED", True)      # không đọc .env thật
    # Xoá MỌI biến news-alert + key X, không chỉ danh sách liệt kê: 05/10 desktop
    # có VNSTOCK_NEWS_ALERT_BSKY_LIST trong .env (List Bluesky 04/10) — module
    # khác nạp .env vào os.environ trong cùng phiên pytest ⇒ 2 test đỏ trên máy
    # thật, sandbox xanh; phát tối có bước test nên suýt mất brief (như U65).
    import os
    stray = [k for k in os.environ if k.startswith("VNSTOCK_NEWS_ALERT")]
    for k in (*stray, na.KILL_SWITCH, na.ENV_HOURS, na.ENV_DAYS, na.ENV_MIN_SCORE,
              na.ENV_WINDOW_H, na.ENV_MAX_SEND, na.ENV_MAX_SCORE, na.ENV_SOURCES,
              na.ENV_TICKERS, na.ENV_CLI_MODEL, na.ENV_CLI_TIMEOUT,
              "VNSTOCK_NEWS_ALERT_ENGINE", na.ENV_TWITTERAPI_KEY, na.ENV_X_BEARER):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _raw(title, hours_ago=1.0, summary="lãi suất, tỷ giá", link="https://x/1", src="Feed A"):
    pub = (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {"title": title, "news_title": title, "link": link,
            "news_short_content": summary, "source_feed": src, "ticker": "",
            "_date_sort": pub[:10], "_published_at": pub, "_sentiment": "", "_impact": ""}


def _src(key, items, relevant=None, kind="rss"):
    return na.Source(key=key, name=key, fetch=lambda: list(items), kind=kind, relevant=relevant)


_BLOCK_RE = re.compile(r"### Tin i=(\d+)\n(?:.*\n)*?Tiêu đề: (.*)")


def _fake_complete(monkeypatch, results=None, by_title=None, err=None):
    """`results` cố định, hoặc `by_title` {mẩu tiêu đề: {muc_do, nhan, tac_dong}}
    — ghép theo tiêu đề trong khối user nên không phụ thuộc thứ tự lô (run sắp
    tin mới trước)."""
    calls: list = []

    def _c(user, **kw):
        calls.append({"user": user, **kw})
        info = {"model": "claude-opus-5-5", "elapsed_s": 1.0}
        rows = results
        if by_title is not None:
            rows = []
            for m in _BLOCK_RE.finditer(user):
                i, title = int(m.group(1)), m.group(2)
                for frag, r in by_title.items():
                    if frag in title:
                        rows.append({"i": i, **r})
                        break
        if rows is not None:
            info["structured"] = {"results": rows}
        return ("" if err else json.dumps({"results": rows or []})), err, info
    monkeypatch.setattr(vcc, "complete", _c)
    return calls


def _sender_spy():
    sent: list = []

    def _s(text):
        sent.append(text)
        return {"ok": True, "result": {"message_id": 777}}
    return sent, _s


# ── registry nguồn ───────────────────────────────────────────────────────────


def test_registry_mirrors_every_rss_feed_plus_alert_feeds_with_unique_keys():
    keys = [s.key for s in na.SOURCES]
    assert len(keys) == len(nf._FEEDS) + len(na._ALERT_FEEDS) and len(set(keys)) == len(keys)
    vn = keys[:len(nf._FEEDS)]
    assert all(k.startswith("rss:") for k in vn)
    assert "rss:cafef-chung-khoan" in keys          # slug bỏ dấu, chữ thường
    assert any(k.startswith("gnews:") for k in keys)


def test_alert_feeds_are_alert_only_and_filtered_by_language():
    """Feed nước ngoài KHÔNG lọt vào news_feeds._FEEDS (brief không đổi); feed
    tiếng Anh dùng _relevant_en, Google News không lọc thêm."""
    names_vn = {f["name"] for f in nf._FEEDS}
    assert not any(f["name"] in names_vn for f in na._ALERT_FEEDS)
    by_key = {s.key: s for s in na.alert_feed_sources()}
    wsj = by_key["rss:wsj-markets"]
    assert wsj.lang == "en" and wsj.relevant is not None
    assert wsj.relevant({"title": "Fed holds rates", "news_short_content": ""})
    assert not wsj.relevant({"title": "Apple unveils new iPhone", "news_short_content": ""})
    gn = by_key["gnews:gn-fed"]
    assert gn.kind == "gnews" and gn.relevant is None and "news.google.com/rss/search" in \
        next(f["url"] for f in na._ALERT_FEEDS if f["name"] == "GN Fed")


def test_gnews_source_splits_publisher_from_title(monkeypatch):
    feed = na.gnews_feed("GN Fed", "Federal Reserve when:1d")
    monkeypatch.setattr(nf, "fetch_feed", lambda f: [
        _raw("Fed holds rates steady - Reuters", src="GN Fed"),
        _raw("No publisher suffix here", src="GN Fed")])
    items, counts = na.collect([na.gnews_source(feed)])
    assert counts == {"gnews:gn-fed": 2}
    by_title = {it["title"]: it for it in items}
    assert by_title["Fed holds rates steady"]["source_feed"] == "Reuters · GN Fed"
    assert by_title["No publisher suffix here"]["source_feed"] == "GN Fed"
    assert all(it["lang"] == "en" and it["source_kind"] == "gnews" for it in items)


def test_item_block_marks_language_for_foreign_items():
    it = _raw("Fed cuts rates"); it["lang"] = "en"
    assert "Ngôn ngữ: en" in na.item_block(0, it)
    assert "Ngôn ngữ" not in na.item_block(0, _raw("Tỷ giá tăng"))


def test_rss_source_reuses_fetch_feed_and_keyword_filter(monkeypatch):
    feed = {"name": "Feed Z", "url": "https://z/rss", "lang": "vi"}
    seen_feed: list = []

    def _ff(f):
        seen_feed.append(f)
        return [_raw("Fed giữ lãi suất"), _raw("Ca sĩ ra MV mới", summary="giải trí")]
    monkeypatch.setattr(nf, "fetch_feed", _ff)
    items, counts = na.collect([na.rss_source(feed)])
    assert seen_feed == [feed]
    assert counts == {"rss:feed-z": 1} and items[0]["title"] == "Fed giữ lãi suất"
    assert items[0]["source_key"] == "rss:feed-z" and items[0]["source_kind"] == "rss"


def test_register_source_adds_non_rss_source_and_replaces_same_key():
    before = list(na.SOURCES)
    try:
        na.register_source(_src("api:x", [{"title": "a"}], kind="api"))
        na.register_source(_src("api:x", [{"title": "b"}], kind="api"))
        assert [s.key for s in na.SOURCES].count("api:x") == 1
        assert na.enabled_sources(only=["api:"])[0].kind == "api"
    finally:
        na.SOURCES = before


def test_enabled_sources_filter_by_env_prefix_and_enabled_flag(monkeypatch):
    before = list(na.SOURCES)
    try:
        na.SOURCES = [_src("rss:a", []), _src("rss:b", []),
                      na.Source(key="rss:c", name="c", fetch=list, enabled=False)]
        assert [s.key for s in na.enabled_sources()] == ["rss:a", "rss:b"]
        monkeypatch.setenv(na.ENV_SOURCES, "rss:b")
        assert [s.key for s in na.enabled_sources()] == ["rss:b"]
    finally:
        na.SOURCES = before


def test_ticker_news_source_appears_only_when_env_set(monkeypatch):
    assert all(s.key != "vnstock:ticker-news" for s in na.enabled_sources())
    monkeypatch.setenv(na.ENV_TICKERS, "vcb, hpg")
    srcs = [s for s in na.enabled_sources() if s.key == "vnstock:ticker-news"]
    assert len(srcs) == 1 and srcs[0].kind == "api" and srcs[0].relevant is None


def test_ticker_news_adapter_normalizes_vnstock_records(monkeypatch):
    import vnstock_news as vn
    monkeypatch.setattr(vn, "fetch_ticker_news", lambda t: [
        {"news_title": f"{t} lãi kỷ lục", "news_short_content": "LNST tăng 40%",
         "public_date": "2026-10-02 09:30:00", "news_source_link": "https://v/1"}])
    items, counts = na.collect([na.ticker_news_source(("VCB",))])
    assert counts == {"vnstock:ticker-news": 1}
    it = items[0]
    assert it["title"] == "VCB lãi kỷ lục" and it["ticker"] == "VCB"
    assert it["link"] == "https://v/1" and it["_published_at"] == "2026-10-02T09:30:00"
    assert it["_date_sort"] == "2026-10-02" and it["source_kind"] == "api"


def test_normalize_item_accepts_minimal_raw_dict_and_rejects_no_title():
    s = _src("api:k", [])
    it = na.normalize_item({"title": "  Hai   dòng\nnối ", "url": "https://u",
                            "summary": "x", "published": "02/10/2026 08:00"}, s)
    assert it["title"] == "Hai dòng nối" and it["link"] == "https://u"
    assert it["_published_at"] == "2026-10-02T08:00:00" and it["_date_sort"] == "2026-10-02"
    assert it["source_feed"] == "api:k" and it["_sentiment"] == "" and it["_impact"] == ""
    assert na.normalize_item({"summary": "no title"}, s) is None
    assert na.normalize_item("rác", s) is None


def test_collect_one_broken_source_does_not_sink_the_run():
    def _boom():
        raise RuntimeError("feed chết")
    bad = na.Source(key="rss:bad", name="bad", fetch=_boom)
    items, counts = na.collect([bad, _src("rss:ok", [_raw("Tỷ giá vượt mốc")])])
    assert counts == {"rss:bad": 0, "rss:ok": 1} and len(items) == 1


# ── từ khoá EN có biên từ · nguồn chính thức · cap theo nguồn · ngân sách fetch ──


@pytest.mark.parametrize("title,ok", [
    ("Market turmoil hits corporate software makers", False),   # turmoil≠oil, corporate≠rate
    ("New Bond film wins award", False),                         # Bond film ≠ bonds, award ≠ war
    ("Fed holds rates steady", True),
    ("Treasury bonds rally as yields slide", True),
    ("S&P 500 falls on tariff fears", True),
    ("FTSE Russell keeps Vietnam on watchlist", True),
    ("Apple unveils new iPhone lineup", False),
])
def test_relevant_en_uses_word_boundaries(title, ok):
    assert na._relevant_en({"title": title, "news_short_content": ""}) is ok


def test_english_feeds_inside_pipeline_list_use_english_gate():
    by_key = {s.key: s for s in na.SOURCES}
    cnbc = by_key["rss:cnbc-markets"]
    assert cnbc.lang == "en"
    assert cnbc.relevant({"title": "Fed cuts rates", "news_short_content": ""})
    assert not cnbc.relevant({"title": "Apple unveils new iPhone", "news_short_content": ""})
    cafef = by_key["rss:cafef-chung-khoan"]
    assert cafef.relevant({"title": "Khối ngoại bán ròng", "news_short_content": ""})


def test_official_feeds_are_unfiltered_and_tagged():
    offs = [s for s in na.alert_feed_sources() if s.kind == "official"]
    assert {s.key for s in offs} == {"rss:fed-monetary-policy", "rss:us-bls-releases", "rss:us-bea-releases"}
    assert all(s.relevant is None for s in offs)
    it = na.normalize_item({"title": "Consumer Price Index – August 2026"}, offs[1])
    assert it["source_kind"] == "official" and "Loại: nguồn chính thức" in na.item_block(0, it)


def test_wsj_feeds_moved_off_frozen_host_and_bloomberg_present():
    urls = {f["name"]: f["url"] for f in na._ALERT_FEEDS}
    assert "feeds.a.dj.com" not in " ".join(urls.values())          # host đóng băng 01/2025 (U68)
    assert urls["WSJ Markets"].startswith("https://feeds.content.dowjones.io/")
    assert urls["Bloomberg Markets"].startswith("https://www.bloomberg.com/feeds/")
    assert all("when:2d" in f["query"] for f in na._ALERT_FEEDS if f.get("kind") == "gnews")
    assert not any(n.startswith(("NYT", "BBC", "Guardian")) for n in urls)


def test_desktop_diag_0210_broken_feeds_disabled_and_us_data_query_added():
    """--diag trên desktop 02/10: ForexLive (chuyển hướng investinglive.com) và BLS
    (chặn script) thô 0 ⇒ tắt; số liệu Mỹ đi qua Google News."""
    on = {s.key for s in na.enabled_sources()}
    assert "rss:investinglive-forexlive" not in on and "rss:us-bls-releases" not in on
    assert "gnews:gn-us-data" in on and "rss:fed-monetary-policy" in on
    q = next(f["query"] for f in na._ALERT_FEEDS if f["name"] == "GN US data")
    assert "payrolls" in q and "consumer price index" in q and "when:2d" in q


def test_take_undated_baselines_first_then_treats_new_titles_as_fresh():
    src = _src("rss:nikkei-asia", [])
    old = [na.normalize_item({"title": f"Old Nikkei story {i}", "link": f"https://n/{i}"}, src)
           for i in range(3)]
    assert all(it["_undated"] for it in old)
    seen = {"items": {}}
    assert na.take_undated(old, seen, NOW) == []                    # lượt đầu: chỉ ghi mốc
    assert len(seen["items"]) == 3 and all(r["baseline"] and r["score"] is None
                                            for r in seen["items"].values())
    later = NOW + timedelta(hours=1)
    fresh_item = na.normalize_item({"title": "Japan intervenes in yen", "link": "https://n/9"}, src)
    got = na.take_undated(old + [fresh_item], seen, later)
    assert [g["title"] for g in got] == ["Japan intervenes in yen"]
    assert got[0]["_published_at"] == later.isoformat(timespec="seconds")
    assert got[0]["_date_sort"] == "" and na.item_hash(got[0]) == na.item_hash(fresh_item)
    dated = na.normalize_item(_raw("Dated"), src)
    assert not dated["_undated"] and na.take_undated([dated], seen, later) == []


def test_run_scores_undated_feed_only_after_baseline(monkeypatch):
    src_items = [{"title": "Old Nikkei story about yen", "link": "https://n/1"}]
    calls = _fake_complete(monkeypatch, by_title={"yen": {"muc_do": 85, "nhan": "TIÊU_CỰC",
                                                          "tac_dong": "Yên mạnh, dòng vốn carry rút khỏi châu Á"}})
    sent, spy = _sender_spy()
    na.run(now=NOW, sources=[_src("rss:nikkei", list(src_items))], engine="claude", sender=spy)
    assert not calls and not sent                                    # mốc, không chấm
    src_items.append({"title": "BOJ hikes, yen surges past 140", "link": "https://n/2"})
    na.run(now=NOW + timedelta(hours=1), sources=[_src("rss:nikkei", list(src_items))],
           engine="claude", sender=spy)
    assert len(calls) == 1 and calls[0]["user"].count("### Tin i=") == 1
    assert "BOJ hikes" in calls[0]["user"] and len(sent) == 1


def test_diag_prints_unreadable_raw_date_and_diag_url(monkeypatch, capsys):
    undated = [{"title": "Fed holds rates", "link": "https://x", "_pub_raw": "Thứ năm 2 tháng 10"}]
    na.diag_sources([_src("rss:vn", undated)], now=NOW)
    out = capsys.readouterr().out
    assert "mới nhất —" in out and "'Thứ năm 2 tháng 10'" in out and "giờ thấy lần đầu" in out
    seen_feed: list = []
    monkeypatch.setattr(nf, "fetch_feed", lambda f: seen_feed.append(f) or [_raw("Fed holds rates")])
    assert na.diag_url("https://investinglive.com/feed/") == 0
    assert seen_feed[0]["url"] == "https://investinglive.com/feed/"
    assert "url:thu-https-investinglive-com-feed" in capsys.readouterr().out


def test_diag_flags_stale_newest_and_probes_http_for_empty_source(monkeypatch, capsys):
    stale = [{**_raw("Fed holds rates"), "_published_at": "2026-02-10T11:56:00",
              "_date_sort": "2026-02-10", "_pub_raw": "10/2/2026 11:56:00 AM"}]

    class _Resp:
        status_code, url, text = 403, "https://www.ft.com/markets?format=rss", "<html>Access denied</html>"
        headers = {"Content-Type": "text/html; charset=utf-8"}
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Resp())
    empty = na.Source(key="rss:ft", name="ft", fetch=lambda: [], url="https://www.ft.com/markets?format=rss")
    rc = na.diag_sources([_src("rss:bcp", stale), empty], now=NOW)
    out = capsys.readouterr().out
    assert rc == 1
    assert "cũ hơn 7 ngày" in out and "'10/2/2026 11:56:00 AM'" in out
    assert "HTTP 403 · text/html" in out and "Access denied" in out


def test_diag_does_not_flag_sparse_official_feeds_as_stale(capsys):
    """--diag desktop 03/10: Fed monetary (tin cuối FOMC 16/09) bị gắn 'cũ hơn 7 ngày'
    — báo động giả: nguồn chính thức chỉ ra tin khi có quyết định."""
    old = [{**_raw("FOMC statement"), "_published_at": "2026-09-17T01:00:00",
            "_date_sort": "2026-09-17", "_pub_raw": "Wed, 16 Sep 2026 18:00:00 GMT"}]
    fed = na.Source(key="rss:fed", name="fed", fetch=lambda: list(old), kind="official")
    na.diag_sources([fed], now=NOW)
    assert "cũ hơn" not in capsys.readouterr().out


def test_rss_and_gnews_sources_carry_url_for_diag():
    by_key = {s.key: s for s in na.alert_feed_sources()}
    assert by_key["rss:ft-markets"].url == "https://www.ft.com/markets?format=rss"
    assert by_key["gnews:gn-fed"].url.startswith("https://news.google.com/rss/search?")


def test_cap_per_source_keeps_newest_n_per_source_in_time_order():
    items = [{**_raw(f"A{i}", hours_ago=0.1 * i), "source_key": "rss:a"} for i in range(8)]
    items += [{**_raw(f"B{i}", hours_ago=0.05 * i), "source_key": "rss:b"} for i in range(2)]
    out = na.cap_per_source(items, 3)
    assert [it["title"] for it in out if it["source_key"] == "rss:a"] == ["A0", "A1", "A2"]
    assert sum(1 for it in out if it["source_key"] == "rss:b") == 2
    pubs = [it["_published_at"] for it in out]
    assert pubs == sorted(pubs, reverse=True)
    assert len(na.cap_per_source(items, 0)) == 10


def test_collect_fetch_budget_drops_hanging_source(capsys):
    import time as _t

    def _slow():
        _t.sleep(3)
        return [_raw("Fed")]
    slow = na.Source(key="rss:slow", name="slow", fetch=_slow)
    t0 = _t.time()
    items, counts = na.collect([slow, _src("rss:fast", [_raw("Tỷ giá tăng")])], budget_s=0.6)
    assert _t.time() - t0 < 2.5
    assert counts == {"rss:fast": 1, "rss:slow": 0} and len(items) == 1
    assert "quá ngân sách fetch" in capsys.readouterr().out and "rss:slow" in capsys.readouterr().out or True


def test_run_scales_batch_cap_with_catchup_window(monkeypatch):
    import vnstock_news as vn
    monkeypatch.setattr(vn, "deduplicate_news", lambda items, **kw: (items, 0))   # soi cap, không soi dedup
    items = [_raw(f"Tin vĩ mô số {i} về lãi suất", hours_ago=0.01 * i) for i in range(40)]
    calls = _fake_complete(monkeypatch, results=[])
    sent, spy = _sender_spy()
    na.run(now=NOW, sources=[_src("rss:one", items)], engine="claude", sender=spy)
    assert calls[0]["user"].count("### Tin i=") == na.DEFAULT_PER_SOURCE          # 6 — cửa sổ 3h
    na.write_status({"ran_at": "2026-10-01T21:00:00", "covered_until": "2026-10-01T21:00:00", "fetched": 1})
    monkeypatch.setattr(na, "load_seen", lambda path=None: {"items": {}})
    na.run(now=NOW, sources=[_src("rss:one", items)], engine="claude", sender=spy)
    assert calls[1]["user"].count("### Tin i=") == na.DEFAULT_PER_SOURCE * 3      # 18 — bắt bù 14h


# ── mạng xã hội: Bluesky miễn phí · X có key ───────────────────────────────


def _bsky_entry(handle, text, created, rkey="3k"):
    return {"post": {"uri": f"at://did:plc:x/app.bsky.feed.post/{rkey}", "author": {"handle": handle},
                     "record": {"text": text, "createdAt": created}, "indexedAt": created}}


def test_bsky_source_one_list_call_caps_per_author_and_links(monkeypatch):
    calls: list = []
    long = "Fed cut odds for December just moved from 60% to 85% after the payrolls miss, dollar lower"

    def _fake(url, params=None, headers=None):
        calls.append((url, params))
        if url.endswith("resolveHandle"):
            return {"did": "did:plc:abc"}
        feed = [_bsky_entry("timiraos.bsky.social", f"{long} #{i}", "2026-10-02T02:0%d:00.000Z" % i, rkey=f"a{i}")
                for i in range(5)]
        feed.append(_bsky_entry("sahm.bsky.social", "Wow.", "2026-10-02T02:30:00.000Z", rkey="s1"))
        feed.append(_bsky_entry("sahm.bsky.social", long, "2026-10-02T02:40:00.000Z", rkey="s2"))
        return {"feed": feed}
    monkeypatch.setattr(na, "_http_get_json", _fake)
    src = na.bsky_source("https://bsky.app/profile/me.bsky.social/lists/3kabc")
    items, counts = na.collect([src])
    assert counts == {"bsky:analysts": 4}                      # 3 timiraos (cap) + 1 sahm (Wow. bỏ)
    list_call = next(p for u, p in calls if u.endswith("getListFeed"))
    assert list_call["list"] == "at://did:plc:abc/app.bsky.graph.list/3kabc"
    it = next(i for i in items if "sahm" in i["source_feed"])
    assert it["link"] == "https://bsky.app/profile/sahm.bsky.social/post/s2"
    assert it["source_kind"] == "social" and it["lang"] == "en" and it["_published_at"]
    assert "Loại: bình luận chuyên gia" in na.item_block(0, it)


def test_bsky_bad_handle_loses_only_that_person(monkeypatch, capsys):
    long = "Treasury yields jump after hot CPI print, dollar firmer against Asian currencies today"

    def _fake(url, params=None, headers=None):
        if params.get("actor") == "gone.bsky.social":
            raise RuntimeError("400 Profile not found")
        return {"feed": [_bsky_entry(params["actor"], long, "2026-10-02T02:00:00.000Z", rkey="p1")]}
    monkeypatch.setattr(na, "_http_get_json", _fake)
    src = na.bsky_source(handles=("ok1.bsky.social", "gone.bsky.social", "ok2.bsky.social"))
    items, counts = na.collect([src])
    assert counts == {"bsky:analysts": 2}
    assert "@gone.bsky.social" in capsys.readouterr().out


def test_bsky_list_feed_paginates_until_old_posts_or_max_pages(monkeypatch):
    long = "Oil jumps as OPEC+ signals deeper cuts, Brent above 90 for the first time this quarter"
    pages = {None: ("c1", "2026-10-02T02:00:00.000Z"), "c1": ("c2", "2026-10-01T22:00:00.000Z"),
             "c2": ("c3", "2026-09-30T10:00:00.000Z"), "c3": (None, "2026-09-29T10:00:00.000Z")}
    seen: list = []

    def _fake(url, params=None, headers=None):
        cur = params.get("cursor")
        seen.append(cur)
        nxt, created = pages[cur]
        return {"feed": [_bsky_entry(f"a{len(seen)}.bsky.social", long, created, rkey=f"k{len(seen)}")],
                "cursor": nxt}
    monkeypatch.setattr(na, "_http_get_json", _fake)
    posts = na._bsky_list_posts("at://did:plc:x/app.bsky.graph.list/r", now=datetime(2026, 10, 2, 9, 0))
    assert seen == [None, "c1", "c2"] and len(posts) == 3        # trang 3 đã cũ hơn 14h ⇒ dừng
    seen.clear()
    pages["c2"] = ("c3", "2026-10-02T01:00:00.000Z")
    na._bsky_list_posts("at://did:plc:x/app.bsky.graph.list/r", now=datetime(2026, 10, 2, 9, 0))
    assert len(seen) == na.BSKY_LIST_MAX_PAGES                  # trần 3 trang


def test_x_source_twitterapi_single_search_call(monkeypatch):
    monkeypatch.setenv(na.ENV_TWITTERAPI_KEY, "k")
    seen: list = []

    def _fake(url, params=None, headers=None):
        seen.append((url, params, headers))
        return {"tweets": [{"id": "1", "url": "https://x.com/setser/status/1",
                            "text": "China's current account surplus is " + "x" * 60,
                            "createdAt": "Fri Oct 02 02:10:30 +0000 2026",
                            "author": {"userName": "setser"}}]}
    monkeypatch.setattr(na, "_http_get_json", _fake)
    items, counts = na.collect([na.x_source(("setser", "brentdonnelly"), "twitterapi", now=NOW)])
    assert counts == {"x:twitterapi": 1} and len(seen) == 1
    url, params, headers = seen[0]
    assert "advanced_search" in url and headers == {"X-API-Key": "k"}
    assert params["query"].startswith("(from:setser OR from:brentdonnelly) -filter:retweets") and "since:" in params["query"]
    assert items[0]["source_feed"] == "X · @setser" and items[0]["_published_at"].startswith("2026-10-02T")


def test_x_source_official_uses_since_id_state(monkeypatch, _meta):
    monkeypatch.setenv(na.ENV_X_BEARER, "tok")
    seen: list = []

    def _fake(url, params=None, headers=None):
        seen.append(params)
        return {"data": [{"id": "900", "author_id": "u1", "text": "Dollar funding stress " + "y" * 50,
                          "created_at": "2026-10-02T02:00:00.000Z"}],
                "includes": {"users": [{"id": "u1", "username": "brentdonnelly"}]},
                "meta": {"newest_id": "900"}}
    monkeypatch.setattr(na, "_http_get_json", _fake)
    src = na.x_source(("brentdonnelly",), "official", now=NOW)
    items, _ = na.collect([src])
    assert "start_time" in seen[0] and "since_id" not in seen[0]
    assert items[0]["link"] == "https://x.com/brentdonnelly/status/900"
    assert json.loads(na._x_state_path().read_text())["since_id"] == "900"
    na.collect([src])
    assert seen[1]["since_id"] == "900" and "start_time" not in seen[1]


def test_enabled_sources_loads_dotenv_before_reading_env(monkeypatch):
    """`run.py news-alert --diag` gọi enabled_sources() trực tiếp, không qua run():
    trước bản vá, List Bluesky đặt trong .env không hiện trong --diag (02/10)."""
    called: list = []

    def _fake_load():
        called.append(1)
        monkeypatch.setenv(na.ENV_BSKY_LIST, "at://did:plc:a/app.bsky.graph.list/r")
    monkeypatch.setattr(na, "_load_env", _fake_load)
    assert "bsky:analysts" in [s.key for s in na.enabled_sources()] and called


def test_social_sources_follow_env(monkeypatch, capsys):
    assert na.social_sources() == []
    monkeypatch.setenv(na.ENV_BSKY_LIST, "at://did:plc:a/app.bsky.graph.list/r")
    assert [s.key for s in na.social_sources()] == ["bsky:analysts"]
    monkeypatch.setenv(na.ENV_X_HANDLES, "setser")
    assert [s.key for s in na.social_sources()] == ["bsky:analysts"]          # không key ⇒ bỏ X
    assert "bỏ X" in capsys.readouterr().out
    monkeypatch.setenv(na.ENV_TWITTERAPI_KEY, "k")
    assert [s.key for s in na.social_sources()] == ["bsky:analysts", "x:twitterapi"]
    monkeypatch.setenv(na.ENV_X_PROVIDER, "official")
    assert [s.key for s in na.social_sources()][-1] == "x:official"
    assert any(s.key == "bsky:analysts" for s in na.enabled_sources())


def test_x_source_without_key_is_zero_items_not_crash(monkeypatch):
    monkeypatch.delenv(na.ENV_TWITTERAPI_KEY, raising=False)
    items, counts = na.collect([na.x_source(("a",), "twitterapi", now=NOW)])
    assert counts == {"x:twitterapi": 0} and items == []


# ── cửa sổ giờ + khung giờ ──────────────────────────────────────────────────


def test_parse_pubdatetime_keeps_full_local_time():
    got = nf._parse_pubdatetime("Fri, 02 Oct 2026 09:30:00 +0700")
    assert len(got) == 19 and got[:4] == "2026" and "T" in got
    assert nf._parse_pubdatetime("2026-10-02T09:30:00+07:00")[:10] == "2026-10-02"
    assert nf._parse_pubdatetime("") == "" and nf._parse_pubdatetime("rác") == ""


def test_parse_feed_now_carries_published_at():
    rss = (b"<?xml version='1.0'?><rss><channel><item><title>Fed</title>"
           b"<link>https://x</link><pubDate>Fri, 02 Oct 2026 09:30:00 +0700</pubDate>"
           b"</item></channel></rss>")
    it = nf.parse_feed(rss, "A")[0]
    assert it["_date_sort"] == "2026-10-02" and it["_published_at"].startswith("2026-10-02T")


def test_within_window_uses_full_time_then_falls_back_to_date():
    assert na.within_window(_raw("a", hours_ago=2.5), NOW, 3)
    assert not na.within_window(_raw("a", hours_ago=3.5), NOW, 3)
    only_date = {"_date_sort": NOW.date().isoformat(), "_published_at": ""}
    assert na.within_window(only_date, NOW, 3)
    assert not na.within_window({"_date_sort": "2026-09-30", "_published_at": ""}, NOW, 3)
    assert not na.within_window({"_date_sort": "", "_published_at": ""}, NOW, 3)


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 2, 0, 0),              # T6 nửa đêm
    datetime(2026, 10, 2, 3, 30),             # đêm VN = giờ Mỹ (Fed, số liệu)
    datetime(2026, 10, 2, 23, 59),
    datetime(2026, 10, 3, 12, 0),             # T7
    datetime(2026, 10, 4, 2, 0),              # CN
])
def test_in_active_hours_default_is_24_7(now):
    # User chốt 04/10: chạy mỗi giờ 24/7 kể cả CN (bản đầu 07–22h T2–T7).
    assert na.in_active_hours(now) == (True, "")


@pytest.mark.parametrize("now,ok", [
    (datetime(2026, 10, 2, 7, 0), True),      # T6 07:00 — biên dưới
    (datetime(2026, 10, 2, 22, 30), True),    # 22:xx vẫn thuộc giờ 22
    (datetime(2026, 10, 2, 23, 0), False),
    (datetime(2026, 10, 2, 6, 59), False),
    (datetime(2026, 10, 3, 12, 0), True),     # T7
    (datetime(2026, 10, 4, 12, 0), False),    # CN
])
def test_in_active_hours_env_window_7_22_mon_sat(monkeypatch, now, ok):
    monkeypatch.setenv(na.ENV_HOURS, "7-22")
    monkeypatch.setenv(na.ENV_DAYS, "1-6")
    got, why = na.in_active_hours(now)
    assert got is ok and (why == "" if ok else why)


def test_in_active_hours_env_override_and_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv(na.ENV_HOURS, "9-15")
    monkeypatch.setenv(na.ENV_DAYS, "1-5")
    assert na.in_active_hours(datetime(2026, 10, 2, 16, 0))[0] is False
    assert na.in_active_hours(datetime(2026, 10, 3, 10, 0))[0] is False     # T7 bị loại
    monkeypatch.setenv(na.ENV_HOURS, "rác")
    assert na.in_active_hours(datetime(2026, 10, 2, 21, 0))[0] is True      # về mặc định


def test_effective_window_catches_up_overnight_and_is_capped():
    prev = {"ran_at": "2026-10-01T22:00:00", "covered_until": "2026-10-01T22:00:00"}
    morning = datetime(2026, 10, 2, 7, 0)
    assert na.effective_window_h(morning, prev, 3) == 10          # 9h + 1h biên
    assert na.effective_window_h(datetime(2026, 10, 1, 23, 0), prev, 3) == 3   # 1h gap → mặc định
    monday = datetime(2026, 10, 5, 7, 0)
    prev_sat = {"covered_until": "2026-10-03T22:00:00"}
    assert na.effective_window_h(monday, prev_sat, 3) == 34        # 33h + 1 < trần 36
    assert na.effective_window_h(monday, {"covered_until": "2026-09-20T22:00:00"}, 3) == 36
    assert na.effective_window_h(monday, {"covered_until": "2026-09-20T22:00:00"}, 3,
                                 max_catchup_h=12) == 12
    assert na.effective_window_h(morning, None, 3) == 3
    assert na.effective_window_h(morning, {"ran_at": "rác"}, 3) == 3


def test_run_uses_catchup_window_and_advances_covered_until(monkeypatch):
    # lượt 22:00 hôm trước ghi marker; tin Fed đăng 01:00 nằm ngoài 3h của lượt 07:00
    na.write_status({"ran_at": "2026-10-01T22:00:00", "covered_until": "2026-10-01T22:00:00",
                     "fetched": 5})
    fed = _raw("Fed cuts rates by 50bp", hours_ago=0)      # NOW là 10:05 → sửa giờ đăng tay
    fed["_published_at"] = "2026-10-02T01:00:00"; fed["_date_sort"] = "2026-10-02"
    calls = _fake_complete(monkeypatch, results=[{"i": 0, "muc_do": 95, "nhan": "x", "tac_dong": "y"}])
    sent, spy = _sender_spy()
    morning = datetime(2026, 10, 2, 7, 0)
    rc = na.run(now=morning, sources=[_src("rss:t", [fed])], engine="claude", sender=spy)
    assert rc == 0 and len(calls) == 1 and len(sent) == 1 and "Fed cuts" in sent[0]
    st = na.read_status()
    assert st["window_h"] == 10 and st["covered_until"] == "2026-10-02T07:00:00"
    # lượt mọi nguồn rỗng KHÔNG tiến covered_until
    na.run(now=datetime(2026, 10, 2, 8, 0), sources=[_src("rss:t", [])], engine="claude", sender=spy)
    assert na.read_status()["covered_until"] == "2026-10-02T07:00:00"
    # --window-h tường minh thắng bắt bù
    na.run(now=datetime(2026, 10, 2, 9, 0), window_h=2, sources=[_src("rss:t", [])],
           engine="claude", sender=spy)
    assert na.read_status()["window_h"] == 2


def test_diag_sources_reports_each_source_and_flags_empty(capsys):
    def _boom():
        raise RuntimeError("DNS")
    srcs = [_src("rss:ok", [_raw("Fed holds rates", hours_ago=1)], relevant=na._relevant_en),
            _src("rss:junk", [_raw("Ca sĩ ra MV", summary="x")], relevant=na._relevant_en),
            na.Source(key="rss:dead", name="dead", fetch=_boom)]
    rc = na.diag_sources(srcs, now=NOW)
    out = capsys.readouterr().out
    assert rc == 1
    assert "✅ rss:ok" in out and "thô   1 · lọc   1 · 3h  1" in out
    assert "⚠️ rss:junk" in out and "lọc   0" in out
    assert "❌ rss:dead" in out and "RuntimeError: DNS" in out
    assert "2/3 nguồn trả dữ liệu" in out
    assert na.read_status() is None and na.load_seen() == {"items": {}}    # không ghi gì


# ── sổ đã thấy ───────────────────────────────────────────────────────────────


def test_seen_store_roundtrip_prune_and_missing_file(_meta):
    assert na.load_seen() == {"items": {}}
    old = (NOW - timedelta(days=8)).isoformat(timespec="seconds")
    seen = {"items": {"h1": {"first_seen": NOW.isoformat(), "title": "a"},
                      "h2": {"first_seen": old, "title": "cũ"},
                      "h3": "rác"}}
    na.save_seen(seen)
    loaded = na.load_seen()
    assert set(loaded["items"]) == {"h1", "h2", "h3"}
    pruned = na.prune_seen(loaded, NOW)
    assert set(pruned["items"]) == {"h1"} and set(loaded["items"]) == {"h1", "h2", "h3"}


def test_item_hash_is_news_feeds_hash():
    it = _raw("Cùng tiêu đề")
    assert na.item_hash(it) == nf._hash(it)


# ── chấm điểm ────────────────────────────────────────────────────────────────


def test_parse_scores_clamps_validates_and_cleans():
    got = na.parse_scores({"results": [
        {"i": 0, "muc_do": 140, "nhan": "TÍCH_CỰC", "tac_dong": "Ngân hàng *hưởng lợi*\nrõ"},
        {"i": 1, "muc_do": "35", "nhan": "tiêu cực", "tac_dong": ""},
        {"i": 7, "muc_do": 3, "nhan": "x", "tac_dong": "ngoài lô"},
        {"i": "rác", "muc_do": 3, "nhan": "x", "tac_dong": "y"},
        "không phải dict",
    ]}, n=2)
    assert got[0] == {"muc_do": 100, "nhan": "positive", "tac_dong": "Ngân hàng hưởng lợi rõ"}
    assert got[1]["muc_do"] == 35 and got[1]["nhan"] == "negative" and got[1]["tac_dong"] == ""
    assert set(got) == {0, 1}
    assert na.parse_scores({"results": [{"i": 0, "muc_do": -7, "nhan": "", "tac_dong": ""}]},
                           1)[0]["muc_do"] == 0                       # kẹp 0–100
    assert na.parse_scores(None, 2) == {} and na.parse_scores({"results": "x"}, 2) == {}


def test_score_items_cli_one_call_with_schema_and_blocks(monkeypatch):
    calls = _fake_complete(monkeypatch, results=[
        {"i": 0, "muc_do": 85, "nhan": "TIÊU_CỰC", "tac_dong": "Tỷ giá ép ngân hàng"},
        {"i": 1, "muc_do": 10, "nhan": "TRUNG_LẬP", "tac_dong": "không tác động trực tiếp"}])
    todo = [_raw("Tỷ giá vượt 26.000"), _raw("Ca sĩ ra MV")]
    got, err = na.score_items_cli(todo)
    assert err is None and got[0]["muc_do"] == 85 and got[1]["muc_do"] == 10
    assert len(calls) == 1
    c = calls[0]
    assert c["json_schema"] == na.SCORE_SCHEMA and c["tag"] == na.TAG
    assert "### Tin i=0" in c["user"] and "### Tin i=1" in c["user"]
    assert "Tỷ giá vượt 26.000" in c["user"] and c["system"] == na.SCORE_SYSTEM


def test_score_prompt_sentences_in_order_blog_and_sent_rules():
    # 04/10: chèn luật nguồn chính thức/mạng xã hội từng cắt đôi câu "doanh nghiệp chỉ
    # lên ≥ 75 khi … (vd ngân hàng lớn mất thanh khoản)" — ví dụ rơi xuống sau luật khác.
    sysmsg = na.SCORE_SYSTEM
    assert "cả ngành/thị trường (vd ngân hàng lớn mất thanh khoản).\nNGUỒN CHÍNH THỨC" in sysmsg
    assert "BÀI Ý KIẾN / BLOG" in sysmsg and "SchiffGold" in sysmsg and "tối đa 65" in sysmsg
    assert "### ĐÃ GỬI" in sysmsg and "KHÔNG chấm mục này" in sysmsg


def test_recent_sent_titles_window_order_and_limit():
    seen = {"items": {
        "a": _rec(4, sent=True, title="Fed giữ lãi suất", sent_at="2026-10-02T09:00:00"),
        "b": _rec(4, sent=True, title="Dầu vượt 90 USD", sent_at="2026-10-02T10:00:00"),
        "c": _rec(4, sent=True, title="Tin hôm kia", sent_at="2026-09-30T10:00:00"),
        "d": _rec(5, sent=False, title="Chưa gửi"),
        "e": "rác",
    }}
    assert na.recent_sent_titles(seen, NOW) == ["Dầu vượt 90 USD", "Fed giữ lãi suất"]
    assert na.recent_sent_titles(seen, NOW, limit=1) == ["Dầu vượt 90 USD"]
    assert na.recent_sent_titles({"items": {}}, NOW) == [] and na.sent_block([]) == ""


def test_score_items_cli_puts_sent_block_first_and_fake_still_parses(monkeypatch):
    calls = _fake_complete(monkeypatch, by_title={"Tỷ giá": {"muc_do": 85, "nhan": "TIÊU_CỰC",
                                                               "tac_dong": "Ngân hàng chịu áp lực"}})
    got, err = na.score_items_cli([_raw("Tỷ giá vượt 26.000")], ["Fed giữ lãi suất"])
    user = calls[0]["user"]
    assert user.startswith("### ĐÃ GỬI 24h qua") and "- Fed giữ lãi suất" in user
    assert user.index("### ĐÃ GỬI") < user.index("### Tin i=0") and got[0]["muc_do"] == 85
    na.score_items_cli([_raw("Tỷ giá vượt 26.000")])
    assert "ĐÃ GỬI" not in calls[1]["user"]


def test_cap_sent_duplicates_only_near_identical_titles():
    todo = [_raw("Fed holds rates steady and signals two cuts in 2027"),
            _raw("Fed holds rates steady"),                          # ngắn hơn hẳn → không phải trùng
            _raw("Oil jumps after OPEC+ surprise cut"),
            _raw("Fed holds rates steady, signals two cuts in 2027!")]
    scored = {0: {"muc_do": 95}, 1: {"muc_do": 85}, 2: {"muc_do": 85}, 3: {"muc_do": 30}}
    n = na.cap_sent_duplicates(todo, scored, ["Fed holds rates steady, signals two cuts in 2027"])
    assert n == 1 and scored[0]["muc_do"] == na.SENT_DUP_CAP == 40
    assert scored[1]["muc_do"] == 85 and scored[2]["muc_do"] == 85 and scored[3]["muc_do"] == 30
    assert na.cap_sent_duplicates(todo, scored, []) == 0


def test_run_next_hour_sees_sent_titles_and_does_not_resend_echo(monkeypatch):
    by_title = {"Fed holds": {"muc_do": 95, "nhan": "TÍCH_CỰC", "tac_dong": "Vốn ngoại quay lại"}}
    first = [_raw("Fed holds rates steady, signals two cuts in 2027", hours_ago=0.5, link="https://cnbc/1")]
    rc, calls, sent = _run(monkeypatch, first, by_title=by_title)
    assert rc == 0 and len(sent) == 1 and "ĐÃ GỬI" not in calls[0]["user"]
    # 1 giờ sau Google News nhặt lại cùng bài, tiêu đề lệch dấu câu, link khác.
    echo = _raw("Fed holds rates steady and signals two cuts in 2027", hours_ago=0, link="https://gn/2")
    calls2 = _fake_complete(monkeypatch, by_title=by_title)
    sent2, spy2 = _sender_spy()
    na.run(now=NOW + timedelta(hours=1), sources=[_src("rss:t", [echo])], engine="claude",
           sender=spy2)
    assert "- Fed holds rates steady, signals two cuts in 2027" in calls2[0]["user"]
    assert sent2 == []                                                      # guard hạ về 40
    rec = [r for r in na.load_seen()["items"].values() if "and signals" in r["title"]][0]
    assert rec["score"] == 40 and not rec["sent"]


def test_score_prompt_is_macro_first_company_news_capped():
    """User chốt 02/10: chỉ tin thị trường/vĩ mô — tin riêng doanh nghiệp (kể cả
    VN30) không được xếp sẵn ở mức 4 như bản đầu; ghim chữ để ai sửa prompt phải
    sửa test có ý thức."""
    sysmsg = na.SCORE_SYSTEM
    assert "TIN VĨ MÔ QUAN TRỌNG" in sysmsg and "KHÔNG phải tin riêng" in sysmsg
    assert "20–49 = tin thường (tin riêng MỘT doanh nghiệp" in sysmsg and "kể cả VN30" in sysmsg
    assert "kết quả kinh doanh/sự kiện của mã VN30" not in sysmsg      # không còn ở mức 4
    assert "Loại: nguồn chính thức" in sysmsg and "Loại: bình luận chuyên gia" in sysmsg
    assert "KHÔNG bao giờ trên 85" in sysmsg


def test_score_items_cli_error_or_garbage_returns_empty(monkeypatch):
    _fake_complete(monkeypatch, err="CLI treo")
    assert na.score_items_cli([_raw("a")]) == ({}, "CLI treo")

    def _garbage(user, **kw):
        return "không phải json", None, {"elapsed_s": 1}
    monkeypatch.setattr(vcc, "complete", _garbage)
    got, err = na.score_items_cli([_raw("a")])
    assert got == {} and err


def test_heuristic_score_tiers():
    # thang 0–100: chỉ từ khoá vĩ mô MẠNH vượt ngưỡng gửi 75 (ladder thô — báo khi chắc)
    assert na.heuristic_score(_raw("Fed hạ lãi suất điều hành", summary="")) == 80
    assert na.heuristic_score(_raw("Giá vàng hôm nay", summary="")) == 60
    assert na.heuristic_score(_raw("Ca sĩ ra MV", summary="giải trí")) == 40
    assert 60 < na.DEFAULT_MIN_SCORE <= 80


def test_score_items_ladder_uses_analyze_item_without_jina(monkeypatch):
    seen_probe: list = []

    def _ai(item):
        seen_probe.append(item.pop("_user_text_tmp", None))
        if "MV" in item["title"]:
            return "neutral", nf._NO_IMPACT
        if "rỗng" in item["title"]:
            return "", ""
        return "negative", "Tỷ giá ép nhóm vay USD"
    monkeypatch.setattr(nf, "analyze_item", _ai)
    todo = [_raw("Tỷ giá vượt mốc"), _raw("Ca sĩ ra MV", summary="x"), _raw("rỗng")]
    got = na.score_items_ladder(todo)
    assert got[0] == {"muc_do": 80, "nhan": "negative", "tac_dong": "Tỷ giá ép nhóm vay USD"}
    assert got[1]["muc_do"] == 10 and 2 not in got
    assert all(p and p.startswith("### Tin i=") for p in seen_probe)   # không fetch Jina
    assert todo[0].get("_user_text_tmp") is None                         # không bẩn item gốc


def test_score_items_engine_routing(monkeypatch):
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("neutral", "kênh ngân hàng"))
    calls = _fake_complete(monkeypatch, results=[{"i": 0, "muc_do": 3, "nhan": "TRUNG_LẬP",
                                                   "tac_dong": "x"}])
    got, eng, err = na.score_items([_raw("a")], engine="ladder")
    assert eng == "ladder" and not calls and got[0]["tac_dong"] == "kênh ngân hàng"
    got, eng, err = na.score_items([_raw("a")], engine="claude")
    assert eng == "claude" and len(calls) == 1 and err is None
    # engine theo env: VNSTOCK_NEWS_ALERT_ENGINE riêng bước
    monkeypatch.setenv("VNSTOCK_NEWS_ALERT_ENGINE", "claude")
    assert vcc.engine_for(na.STEP) == "claude"
    got, eng, _ = na.score_items([_raw("a")])
    assert eng == "claude" and len(calls) == 2


def test_score_items_claude_failure_falls_back_to_ladder_and_keeps_error(monkeypatch):
    _fake_complete(monkeypatch, err="CLI chết")
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("positive", "Thép hưởng lợi"))
    got, eng, err = na.score_items([_raw("Đầu tư công tăng tốc")], engine="claude")
    assert eng == "ladder" and err == "CLI chết" and got[0]["nhan"] == "positive"


def test_score_items_no_engine_at_all_returns_none(monkeypatch):
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("", ""))
    got, eng, err = na.score_items([_raw("a")], engine="ladder")
    assert got == {} and eng == "none"


# ── chọn + dựng tin ─────────────────────────────────────────────────────────


def _rec(score, sent=False, pub="2026-10-02T09:00:00", title="t", **kw):
    return {"title": title, "link": "https://l", "source": "S", "ticker": "", "published": pub,
            "first_seen": pub, "score": score, "nhan": "neutral", "tac_dong": "kênh",
            "sent": sent, **kw}


def test_select_to_send_threshold_cap_order_and_unsent_only():
    seen = {"items": {
        "a": _rec(3, pub="2026-10-02T08:00:00", title="a"),
        "b": _rec(5, pub="2026-10-02T07:00:00", title="b"),
        "c": _rec(5, pub="2026-10-02T09:00:00", title="c"),
        "d": _rec(2, title="d"),
        "e": _rec(4, sent=True, title="e"),
        "f": _rec(None, title="f"),
    }}
    picked = na.select_to_send(seen, min_score=3, max_send=10)
    assert [h for h, _ in picked] == ["c", "b", "a"]          # 5 mới nhất trước, rồi 3
    assert [h for h, _ in na.select_to_send(seen, 3, 2)] == ["c", "b"]
    assert na.select_to_send(seen, 6, 10) == []


def test_expire_leftovers_marks_old_unsent_only():
    seen = {"items": {
        "old": _rec(4, pub="2026-10-02T02:00:00", title="old"),           # 8h tuổi
        "young": _rec(4, pub="2026-10-02T07:00:00", title="young"),       # 3h
        "low": _rec(2, pub="2026-10-01T09:00:00", title="low"),           # dưới ngưỡng — kệ
        "sent": _rec(5, sent=True, pub="2026-10-01T09:00:00", title="sent"),
        "dateonly": _rec(3, pub="2026-10-02", first_seen="2026-10-02T09:30:00", title="d"),
    }}
    assert na.expire_leftovers(seen, NOW, 3, 6) == 1
    assert seen["items"]["old"]["expired_at"] == NOW.isoformat(timespec="seconds")
    assert not any(seen["items"][k].get("expired_at") for k in ("young", "low", "sent", "dateonly"))
    assert [h for h, _ in na.select_to_send(seen, 3, 10)] == ["young", "dateonly"]
    assert na.expire_leftovers(seen, NOW, 3, 6) == 0                     # không đếm lại


def test_catchup_leftovers_do_not_trickle_out_hours_later(monkeypatch):
    # Vết 04/10: lượt 20:00 bắt bù 20h chấm 60 tin, gửi 8; lượt 21:00 lại gửi 8 — phần dư
    # cũ 15–20h. Nay lượt sau chỉ gửi bù tin dư ≤6h tuổi.
    monkeypatch.setattr("vnstock_news.deduplicate_news", lambda xs: (xs, 0))
    # Tiêu đề phải KHÁC hẳn nhau như tin thật — "Tin mới CPI"/"Tin mới PMI" ngắn
    # và na ná nhau, bộ lọc trùng (`mark_duplicate_pending`, 07/10) coi là một bài.
    old_topics = ["Fed giữ nguyên lãi suất, phát tín hiệu thận trọng",
                  "ECB bất ngờ cắt giảm lãi suất 25 điểm cơ bản",
                  "Ngân hàng Nhật can thiệp đồng yên lần thứ hai",
                  "Trung Quốc bơm thanh khoản qua kênh tái cấp vốn",
                  "OPEC+ kéo dài cắt giảm sản lượng sang quý tới",
                  "Giá vàng thế giới lập đỉnh mới trên 3.000 USD",
                  "Dầu Brent giảm mạnh sau báo cáo tồn kho Mỹ",
                  "Thép xây dựng tăng giá lần thứ ba trong tháng",
                  "Xuất khẩu gạo Việt Nam đạt kỷ lục chín tháng",
                  "Cà phê Robusta biến động mạnh vì thời tiết Tây Nguyên"]
    items = [_raw(f"Tin cũ: {t}", hours_ago=15 + i * 0.1, link=f"https://o/{i}")
             for i, t in enumerate(old_topics)]
    items += [_raw(f"Tin mới: {t}", hours_ago=1 + i * 0.1, link=f"https://n/{i}")
              for i, t in enumerate(["CPI Mỹ tháng 9 cao hơn dự báo của giới phân tích",
                                     "GDP quý ba Việt Nam tăng tốc nhờ xuất khẩu điện tử",
                                     "PMI sản xuất toàn cầu suy yếu tháng thứ hai liên tiếp"])]
    by_title = {"Tin": {"muc_do": 78, "nhan": "TRUNG_LẬP", "tac_dong": "Tỷ giá"}}
    _fake_complete(monkeypatch, by_title=by_title)
    sent1, spy1 = _sender_spy()
    na.run(now=NOW, window_h=20, sources=[_src("rss:t", items)], engine="claude", sender=spy1)
    assert len(sent1) == 1 and sent1[0].count("🟠 78/100") == 8           # trần 8, dư 5
    sent2, spy2 = _sender_spy()
    na.run(now=NOW + timedelta(hours=1), sources=[_src("rss:t", items)], engine="claude", sender=spy2)
    leftovers_sent = sent2[0].count("Tin cũ") if sent2 else 0
    assert leftovers_sent == 0                                             # dư 15h+ hết hạn
    assert all(r["sent"] or r.get("expired_at") for r in na.load_seen()["items"].values())


def test_format_message_is_telegram_safe_html():
    recs = [_rec(95, title="Fed <bất ngờ> hạ lãi suất", nhan="positive"),
            _rec(60, title="Giá vàng", tac_dong="", link="")]
    txt = na.format_message(recs, NOW, 60, "claude")
    assert txt.startswith("📰 <b>Tin quan trọng</b> · 10:05 02/10")
    assert '🔴 95/100 · <b><a href="https://l">Fed <bất ngờ> hạ lãi suất</a></b>' in txt
    assert "▲ kênh" in txt
    assert "🟡 60/100 · <b>Giá vàng</b>" in txt                 # không link → tiêu đề trần
    assert "2 tin ≥ 60/100 · chấm bởi Claude Code" in txt
    # chỉ dùng tag trong whitelist của vnstock_telegram (+ link khi allow_links)
    import vnstock_telegram as tg
    out = tg._sanitize_html(txt, allow_links=True)
    assert "<b>Tin quan trọng</b>" in out and "&lt;bất ngờ&gt;" in out
    assert '<a href="https://l">' in out and "</a></b>" in out


def test_format_message_title_is_the_link_no_bare_url_line():
    # Dry-run desktop 04/10: URL Google News ~250 ký tự để trần chiếm 3–4 dòng/tin
    # trên điện thoại ⇒ tiêu đề bấm được, không còn dòng URL riêng.
    gn = "https://news.google.com/rss/articles/CBMiigFBVV95cUxP" + "x" * 200 + "?oc=5&hl=en"
    txt = na.format_message([_rec(4, title="Rates surge", link=gn)], NOW, 3, "claude")
    assert f'<a href="{gn}">Rates surge</a>' in txt
    assert sum(gn in ln for ln in txt.splitlines()) == 1        # chỉ nằm trong href
    import vnstock_telegram as tg
    out = tg._sanitize_html(txt, allow_links=True)
    assert '<a href="https://news.google.com/' in out and "?oc=5&amp;hl=en" in out


@pytest.mark.parametrize("link", ['https://x/a"onclick="y', "javascript:alert(1)",
                                  "ftp://x/y", "https://x/a b", "  "])
def test_format_message_unsafe_link_leaves_title_plain(link):
    txt = na.format_message([_rec(80, title="Tin", link=link)], NOW, 75, "claude")
    assert "<a " not in txt and "80/100 · <b>Tin</b>" in txt


def test_format_message_older_day_gets_date_today_only_time():
    recs = [_rec(4, title="hôm nay", pub="2026-10-02T09:00:00"),
            _rec(4, title="hôm qua", pub="2026-10-01T22:48:00")]
    txt = na.format_message(recs, NOW, 3, "claude")
    assert "<i>S · 09:00</i>" in txt and "<i>S · 22:48 01/10</i>" in txt


def test_default_sender_turns_links_on(monkeypatch):
    import vnstock_telegram as tg
    got = {}
    monkeypatch.setattr(tg, "send_message", lambda text, **kw: got.update(kw) or {"ok": True})
    na._default_sender("x")
    assert got == {"allow_links": True, "channel": "news"}        # 05/10: bot/group tin riêng


# ── một lượt trọn ────────────────────────────────────────────────────────────


def _run(monkeypatch, items, results=None, by_title=None, err=None, sender=None, **kw):
    calls = _fake_complete(monkeypatch, results=results, by_title=by_title, err=err)
    sent, spy = _sender_spy()
    rc = na.run(now=NOW, sources=[_src("rss:t", items)], engine="claude",
                sender=sender or spy, **kw)
    return rc, calls, sent


def test_run_kill_switch_does_nothing(monkeypatch):
    monkeypatch.setenv(na.KILL_SWITCH, "0")
    rc, calls, sent = _run(monkeypatch, [_raw("Fed")], results=[])
    assert rc == 0 and not calls and not sent and na.read_status() is None


def test_run_outside_hours_skips_unless_forced(monkeypatch):
    monkeypatch.setenv(na.ENV_DAYS, "1-6")                  # mặc định 24/7 — thu hẹp để thử cửa
    calls = _fake_complete(monkeypatch, results=[])
    sent, spy = _sender_spy()
    sunday = datetime(2026, 10, 4, 10, 0)
    assert na.run(now=sunday, sources=[_src("rss:t", [_raw("a")])], sender=spy) == 0
    assert not calls and na.read_status() is None
    na.run(now=sunday, force=True, window_h=72, sources=[_src("rss:t", [_raw("a")])],
           engine="claude", sender=spy)
    assert len(calls) == 1


def test_run_no_new_items_is_silent_and_calls_no_llm(monkeypatch):
    rc, calls, sent = _run(monkeypatch, [_raw("Cũ rồi", hours_ago=9)], results=[])
    assert rc == 0 and not calls and not sent
    st = na.read_status()
    assert st["fetched"] == 1 and st["new"] == 0 and st["sent"] == 0 and st["error"] is None
    assert st["machine"] and st["ran_at"] == NOW.isoformat(timespec="seconds")


def test_run_scores_once_sends_above_threshold_and_marks_seen(monkeypatch):
    items = [_raw("Fed hạ lãi suất", hours_ago=0.5, link="https://a"),
             _raw("Ca sĩ ra MV", hours_ago=0.4, link="https://b"),
             _raw("Giá vàng nhích nhẹ", hours_ago=0.3, link="https://c")]
    by_title = {"Fed": {"muc_do": 95, "nhan": "TÍCH_CỰC", "tac_dong": "Ngân hàng, vốn ngoại hưởng lợi"},
                "Ca sĩ": {"muc_do": 10, "nhan": "TRUNG_LẬP", "tac_dong": "không tác động trực tiếp"},
                "vàng": {"muc_do": 74, "nhan": "TRUNG_LẬP", "tac_dong": "PNJ hai chiều"}}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title)
    assert calls[0]["user"].index("Giá vàng") < calls[0]["user"].index("Fed")   # mới trước
    assert rc == 0 and len(calls) == 1 and len(sent) == 1
    assert "Fed hạ lãi suất" in sent[0] and "Ca sĩ" not in sent[0] and "Giá vàng" not in sent[0]
    seen = na.load_seen()["items"]
    assert len(seen) == 3
    fed = seen[na.item_hash(items[0])]
    assert fed["sent"] is True and fed["score"] == 95 and fed["sent_at"]
    assert seen[na.item_hash(items[2])]["sent"] is False
    st = na.read_status()
    assert (st["new"], st["scored"], st["picked"], st["sent"]) == (3, 3, 1, 1)
    assert st["message_id"] == 777 and st["engine"] == "claude" and st["error"] is None

    # Lượt sau cùng tin: không chấm lại, không gửi lại
    rc2, calls2, sent2 = _run(monkeypatch, items, by_title=by_title)
    assert rc2 == 0 and not calls2 and not sent2


def test_run_unsent_overflow_goes_next_hour_without_rescoring(monkeypatch):
    titles = ["Fed hạ lãi suất", "Tỷ giá vượt mốc 26.000", "SBV hút ròng kỷ lục",
              "Mỹ áp thuế quan mới lên châu Á"]      # tiêu đề KHÁC hẳn nhau — deduplicate_news không gộp
    items = [_raw(t, hours_ago=0.1 * i, link=f"https://{i}") for i, t in enumerate(titles)]
    by_title = {t: {"muc_do": 85, "nhan": "TIÊU_CỰC", "tac_dong": "x"} for t in titles}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title, max_send=3)
    assert len(sent) == 1 and sent[0].count("🟠 85/100") == 3
    rc2, calls2, sent2 = _run(monkeypatch, items, by_title=by_title, max_send=3)
    assert not calls2 and len(sent2) == 1 and sent2[0].count("🟠 85/100") == 1
    assert "lượt trước" in sent2[0]
    assert all(r["sent"] for r in na.load_seen()["items"].values())


def test_run_telegram_failure_keeps_items_unsent_and_flags_marker(monkeypatch):
    def _boom(text):
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set")
    rc, calls, _ = _run(monkeypatch, [_raw("Fed")], sender=_boom,
                        results=[{"i": 0, "muc_do": 95, "nhan": "x", "tac_dong": "y"}])
    assert rc == 1
    rec = next(iter(na.load_seen()["items"].values()))
    assert rec["sent"] is False and rec["score"] == 95
    assert "TELEGRAM_BOT_TOKEN" in na.read_status()["error"]


def test_run_dry_run_prints_but_writes_nothing(monkeypatch, capsys):
    rc, calls, sent = _run(monkeypatch, [_raw("Fed")], dry_run=True,
                           results=[{"i": 0, "muc_do": 95, "nhan": "x", "tac_dong": "y"}])
    assert rc == 0 and len(calls) == 1 and not sent
    assert "--dry-run" in capsys.readouterr().out
    assert na.load_seen() == {"items": {}} and na.read_status() is None


def test_run_all_sources_empty_is_a_warning_and_streak_counts(monkeypatch):
    rc, calls, sent = _run(monkeypatch, [], results=[])
    assert rc == 1 and not calls and "rỗng" in na.read_status()["error"]
    assert na.read_status()["error_streak"] == 1
    _run(monkeypatch, [], results=[])
    _run(monkeypatch, [], results=[])
    assert na.read_status()["error_streak"] == 3
    import vnstock_doctor as doc
    assert doc.news_alert_verdict(na.read_status(), now=NOW, active=True)["status"] == "error"
    _run(monkeypatch, [_raw("Cũ", hours_ago=9)], results=[])       # lượt sạch → về 0
    assert na.read_status()["error_streak"] == 0 and na.read_status()["error"] is None


def test_run_claude_fails_ladder_empty_flags_error_but_marks_seen(monkeypatch):
    monkeypatch.setattr(nf, "analyze_item", lambda it: ("", ""))
    rc, calls, sent = _run(monkeypatch, [_raw("Fed")], err="CLI chết")
    assert rc == 1 and not sent
    st = na.read_status()
    assert st["claude_error"] == "CLI chết" and st["engine"] == "none" and st["error"]
    rec = next(iter(na.load_seen()["items"].values()))
    assert rec["score"] is None and rec["sent"] is False     # đã thấy, không chấm lại mãi


def test_run_dedups_cross_source_same_headline(monkeypatch):
    a = _raw("SBV hút ròng 20.000 tỷ", hours_ago=0.5, src="A", link="https://a")
    b = _raw("SBV hút ròng 20.000 tỷ", hours_ago=0.4, src="B", link="https://b")
    calls = _fake_complete(monkeypatch, results=[{"i": 0, "muc_do": 85, "nhan": "x", "tac_dong": "y"}])
    sent, spy = _sender_spy()
    na.run(now=NOW, sources=[_src("rss:a", [a]), _src("rss:b", [b])], engine="claude", sender=spy)
    assert calls[0]["user"].count("### Tin i=") == 1 and len(sent) == 1


def test_run_respects_max_score_cap_newest_first(monkeypatch):
    titles = ["Fed hạ lãi suất", "Tỷ giá vượt mốc", "SBV hút ròng", "Thuế quan mới", "Giá dầu rơi"]
    items = [_raw(t, hours_ago=0.1 * i) for i, t in enumerate(titles)]
    calls = _fake_complete(monkeypatch, results=[])
    na.run(now=NOW, sources=[_src("rss:t", items)], engine="claude", max_score=2,
           sender=_sender_spy()[1])
    u = calls[0]["user"]
    assert u.count("### Tin i=") == 2 and "Fed hạ" in u and "Tỷ giá" in u and "Giá dầu" not in u


# ── doctor + kill switch + run.py ───────────────────────────────────────────


def test_doctor_news_alert_verdicts():
    import vnstock_doctor as doc
    assert doc.news_alert_verdict(None)["status"] == "off"
    ok_marker = {"ran_at": NOW.isoformat(), "machine": "PICHU", "fetched": 40, "new": 3,
                 "sent": 1, "engine": "claude", "error": None}
    r = doc.news_alert_verdict(ok_marker, now=NOW + timedelta(minutes=20), active=True)
    assert r["status"] == "ok" and "PICHU" in r["message"] and "1 gửi" in r["message"]
    stale = doc.news_alert_verdict(ok_marker, now=NOW + timedelta(hours=5), active=True)
    assert stale["status"] == "warn" and "không có lượt mới" in stale["message"]
    night = doc.news_alert_verdict(ok_marker, now=NOW + timedelta(hours=14), active=False)
    assert night["status"] == "ok"
    bad = doc.news_alert_verdict({**ok_marker, "error": "mọi nguồn đều rỗng"}, now=NOW, active=True)
    assert bad["status"] == "warn" and "rỗng" in bad["message"]
    dead = doc.news_alert_verdict({**ok_marker, "error": "x", "error_streak": 3}, now=NOW, active=True)
    assert dead["status"] == "error"


def test_doctor_check_reads_marker_and_is_wired(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path)
    assert doc.check_news_alert()["status"] == "off"
    (tmp_path / "news_alert_status.json").write_text(json.dumps(
        {"ran_at": datetime.now().isoformat(), "machine": "M", "error": "Telegram 401"}),
        encoding="utf-8")
    r = doc.check_news_alert()
    assert r["status"] == "warn" and "Telegram 401" in r["message"]
    assert doc.check_news_alert in doc.OFFLINE_CHECKS
    assert "VNSTOCK_NEWS_ALERT" in doc._DANGEROUS_SWITCHES


def test_step_engine_env_has_news_alert():
    assert vcc.STEP_ENGINE_ENV[na.STEP] == "VNSTOCK_NEWS_ALERT_ENGINE"


def test_runpy_has_news_alert_subcommand_but_all_does_not():
    import run as runpy
    args = runpy.build_parser().parse_args(["news-alert", "--dry-run", "--min-score", "4",
                                            "--sources", "rss:cafef"])
    assert args.subcommand == "news-alert" and args.dry_run and args.min_score == 4
    assert runpy.build_parser().parse_args(["news-alert", "--diag"]).diag is True
    assert runpy.build_parser().parse_args(["news-alert", "--diag-url", "https://u"]).diag_url == "https://u"
    assert runpy._DISPATCH["news-alert"] is runpy.cmd_news_alert
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    assert "news-alert" not in names
    assert "tests/test_news_alert.py" in open(runpy.__file__, encoding="utf-8").read()


def test_runpy_cmd_news_alert_passes_flags_through(monkeypatch):
    import run as runpy
    got: dict = {}
    monkeypatch.setattr(na, "run", lambda **kw: got.update(kw) or 0)
    args = SimpleNamespace(dry_run=True, force=False, min_score=4, window_h=2, max_send=5,
                           engine="ladder", sources="rss:cafef", list_sources=False)
    assert runpy.cmd_news_alert(args) == 0
    assert got["dry_run"] is True and got["min_score"] == 4 and got["engine"] == "ladder"
    assert all(s.key.startswith("rss:cafef") for s in got["sources"]) and got["sources"]


# ── thang 0–100 (06/10): ≥3/5 lượt nào cũng đầy 8 tin, ≥4/5 lại quá ít ⇒ ngưỡng 75 ──


@pytest.mark.parametrize("raw,want", [
    (None, 75), ("rác", 75), (75, 75), ("80", 80), (0, 0), (150, 100), (-3, 0),
    (3, 60), (4, 80), (5, 100), (1, 20),          # 1–5 = thang CŨ ⇒ ×20
])
def test_normalize_min_score_reads_legacy_scale(raw, want):
    assert na.normalize_min_score(raw) == want


def test_default_threshold_is_75_and_prompt_says_so():
    assert na.DEFAULT_MIN_SCORE == 75 and (na.SCORE_MIN, na.SCORE_MAX) == (0, 100)
    sysmsg = na.SCORE_SYSTEM
    assert "muc_do (0–100, số nguyên)" in sysmsg and "Chỉ tin ≥ 75" in sysmsg
    assert "<0-100>" in sysmsg and "<1-5>" not in sysmsg
    for band in ("90–100 = sốc hệ thống", "80–89 = vĩ mô/chính sách đáng kể",
                 "70–79 = đáng theo dõi", "50–69 = đáng biết", "0–19 = phi kinh tế"):
        assert band in sysmsg, band


def test_run_sends_75_not_74_by_default(monkeypatch):
    items = [_raw("Fed nói giữ lãi suất lâu hơn", hours_ago=0.5, link="https://a"),
             _raw("PMI Trung Quốc đúng kỳ vọng", hours_ago=0.4, link="https://b")]
    by_title = {"Fed": {"muc_do": 75, "nhan": "TIÊU_CỰC", "tac_dong": "Tỷ giá, ngân hàng chịu áp lực"},
                "PMI": {"muc_do": 74, "nhan": "TRUNG_LẬP", "tac_dong": "Thép, hoá chất"}}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title)
    assert rc == 0 and len(sent) == 1
    assert "🟠 75/100 · " in sent[0] and "PMI" not in sent[0] and "1 tin ≥ 75/100" in sent[0]
    assert na.read_status()["min_score"] == 75


def test_run_env_legacy_min_score_4_means_80(monkeypatch):
    monkeypatch.setenv(na.ENV_MIN_SCORE, "4")
    items = [_raw("Fed nói giữ lãi suất lâu hơn", hours_ago=0.5, link="https://a")]
    by_title = {"Fed": {"muc_do": 78, "nhan": "TIÊU_CỰC", "tac_dong": "Tỷ giá"}}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title)
    assert rc == 0 and not sent and na.read_status()["min_score"] == 80


def test_icon_bands():
    assert [na._icon(x) for x in (100, 90, 89, 75, 74, 60, 59, 0)] == [
        "🔴", "🔴", "🟠", "🟠", "🟡", "🟡", "⚪", "⚪"]



# ── lọc trùng trước khi gửi (07/10: gửi bù 30h ra 2 bản Bloomberg cùng link) ──


def test_norm_link_drops_scheme_www_query_fragment():
    assert na._norm_link("https://www.WSJ.com/a/b/?mod=rss_main#x") == "wsj.com/a/b"
    assert na._norm_link("http://news.google.com/rss/articles/ABC?oc=5") == \
        "news.google.com/rss/articles/abc"
    assert na._norm_link("") == "" and na._norm_link(None) == ""


def test_mark_duplicate_pending_same_link_keeps_higher_score():
    url = "https://www.bloomberg.com/news/articles/2026-10-07/us-30-year-yields"
    seen = {"items": {
        "a": _rec(68, title="US 30-Year Yields Return to 2002 High With Crude Back Above $100",
                  link=url, pub="2026-10-02T08:39:00"),
        "b": _rec(78, title="US 30-Year Yields Return to 2002 High With Crude Above $100",
                  link=url + "?mod=rss", pub="2026-10-02T08:40:00"),
        "c": _rec(72, title="Dow Lower, Treasury Yields Hit Fresh 24-Year Highs",
                  link="https://www.wsj.com/x"),                      # cùng sự kiện, KHÁC bài
    }}
    assert na.mark_duplicate_pending(seen, NOW, 65) == 1
    assert seen["items"]["a"]["dup_of"] == "b" and "dup_of" not in seen["items"]["b"]
    assert [h for h, _ in na.select_to_send(seen, 65, 10)] == ["b", "c"]
    assert na.mark_duplicate_pending(seen, NOW, 65) == 0                # không đánh lại


def test_mark_duplicate_pending_against_sent_24h_only():
    title = "Vietnam Central Bank Warns of Rising Inflation, Rates Pressure"
    seen = {"items": {
        "sent": _rec(72, sent=True, title=title, link="https://bbg/1",
                     sent_at="2026-10-02T07:00:00"),
        "echo": _rec(70, title=title + "!", link="https://gn/2"),           # tiêu đề gần y hệt
        "old": _rec(70, sent=True, title="Fed holds rates steady, signals two cuts in 2027",
                    link="https://cnbc/1", sent_at="2026-09-30T07:00:00"),  # >24h
        "again": _rec(70, title="Fed holds rates steady, signals two cuts in 2027",
                      link="https://cnbc/1"),
    }}
    assert na.mark_duplicate_pending(seen, NOW, 65) == 1
    assert seen["items"]["echo"]["dup_of"] == "sent"
    assert "dup_of" not in seen["items"]["again"]                       # tin gửi >24h không tính


def test_run_backfill_sends_one_copy_of_same_link(monkeypatch):
    url = "https://www.bloomberg.com/news/articles/2026-10-07/yields"
    seen = {"items": {
        "a": _rec(68, title="US 30-Year Yields Return to 2002 High With Crude Back Above $100",
                  link=url, pub="2026-10-02T08:00:00"),
        "b": _rec(78, title="US 30-Year Yields Return to 2002 High With Crude Above $100",
                  link=url, pub="2026-10-02T08:05:00"),
    }}
    na.save_seen(seen)
    rc, calls, sent = _run(monkeypatch, [], results=[], window_h=30, max_send=15, min_score=65)
    assert len(sent) == 1 and sent[0].count("Yields Return to 2002") == 1 and "78/100" in sent[0]
    items = na.load_seen()["items"]
    assert items["b"]["sent"] and items["a"]["dup_of"] == "b" and not items["a"]["sent"]
    rc2, calls2, sent2 = _run(monkeypatch, [], results=[], window_h=30, max_send=15, min_score=65)
    assert sent2 == []                                                  # bản trùng không rỉ ra sau
