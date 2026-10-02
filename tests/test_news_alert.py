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
    for k in (na.KILL_SWITCH, na.ENV_HOURS, na.ENV_DAYS, na.ENV_MIN_SCORE, na.ENV_WINDOW_H,
              na.ENV_MAX_SEND, na.ENV_MAX_SCORE, na.ENV_SOURCES, na.ENV_TICKERS,
              na.ENV_CLI_MODEL, na.ENV_CLI_TIMEOUT, "VNSTOCK_NEWS_ALERT_ENGINE"):
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


def test_registry_mirrors_every_rss_feed_with_unique_keys():
    keys = [s.key for s in na.SOURCES]
    assert len(keys) == len(nf._FEEDS) and len(set(keys)) == len(keys)
    assert all(k.startswith("rss:") for k in keys)
    assert "rss:cafef-chung-khoan" in keys          # slug bỏ dấu, chữ thường


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


@pytest.mark.parametrize("now,ok", [
    (datetime(2026, 10, 2, 7, 0), True),      # T6 07:00 — biên dưới
    (datetime(2026, 10, 2, 22, 30), True),    # 22:xx vẫn thuộc giờ 22
    (datetime(2026, 10, 2, 23, 0), False),
    (datetime(2026, 10, 2, 6, 59), False),
    (datetime(2026, 10, 3, 12, 0), True),     # T7
    (datetime(2026, 10, 4, 12, 0), False),    # CN
])
def test_in_active_hours_default_7_22_mon_sat(now, ok):
    got, why = na.in_active_hours(now)
    assert got is ok and (why == "" if ok else why)


def test_in_active_hours_env_override_and_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv(na.ENV_HOURS, "9-15")
    monkeypatch.setenv(na.ENV_DAYS, "1-5")
    assert na.in_active_hours(datetime(2026, 10, 2, 16, 0))[0] is False
    assert na.in_active_hours(datetime(2026, 10, 3, 10, 0))[0] is False     # T7 bị loại
    monkeypatch.setenv(na.ENV_HOURS, "rác")
    assert na.in_active_hours(datetime(2026, 10, 2, 21, 0))[0] is True      # về mặc định


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
        {"i": 0, "muc_do": 9, "nhan": "TÍCH_CỰC", "tac_dong": "Ngân hàng *hưởng lợi*\nrõ"},
        {"i": 1, "muc_do": "2", "nhan": "tiêu cực", "tac_dong": ""},
        {"i": 7, "muc_do": 3, "nhan": "x", "tac_dong": "ngoài lô"},
        {"i": "rác", "muc_do": 3, "nhan": "x", "tac_dong": "y"},
        "không phải dict",
    ]}, n=2)
    assert got[0] == {"muc_do": 5, "nhan": "positive", "tac_dong": "Ngân hàng hưởng lợi rõ"}
    assert got[1]["muc_do"] == 2 and got[1]["nhan"] == "negative" and got[1]["tac_dong"] == ""
    assert set(got) == {0, 1}
    assert na.parse_scores(None, 2) == {} and na.parse_scores({"results": "x"}, 2) == {}


def test_score_items_cli_one_call_with_schema_and_blocks(monkeypatch):
    calls = _fake_complete(monkeypatch, results=[
        {"i": 0, "muc_do": 4, "nhan": "TIÊU_CỰC", "tac_dong": "Tỷ giá ép ngân hàng"},
        {"i": 1, "muc_do": 1, "nhan": "TRUNG_LẬP", "tac_dong": "không tác động trực tiếp"}])
    todo = [_raw("Tỷ giá vượt 26.000"), _raw("Ca sĩ ra MV")]
    got, err = na.score_items_cli(todo)
    assert err is None and got[0]["muc_do"] == 4 and got[1]["muc_do"] == 1
    assert len(calls) == 1
    c = calls[0]
    assert c["json_schema"] == na.SCORE_SCHEMA and c["tag"] == na.TAG
    assert "### Tin i=0" in c["user"] and "### Tin i=1" in c["user"]
    assert "Tỷ giá vượt 26.000" in c["user"] and c["system"] == na.SCORE_SYSTEM


def test_score_prompt_is_macro_first_company_news_capped():
    """User chốt 02/10: chỉ tin thị trường/vĩ mô — tin riêng doanh nghiệp (kể cả
    VN30) không được xếp sẵn ở mức 4 như bản đầu; ghim chữ để ai sửa prompt phải
    sửa test có ý thức."""
    sysmsg = na.SCORE_SYSTEM
    assert "TIN VĨ MÔ QUAN TRỌNG" in sysmsg and "KHÔNG phải tin riêng" in sysmsg
    assert "2 = tin thường (tin riêng MỘT doanh nghiệp" in sysmsg and "kể cả VN30" in sysmsg
    assert "kết quả kinh doanh/sự kiện của mã VN30" not in sysmsg      # không còn ở mức 4


def test_score_items_cli_error_or_garbage_returns_empty(monkeypatch):
    _fake_complete(monkeypatch, err="CLI treo")
    assert na.score_items_cli([_raw("a")]) == ({}, "CLI treo")

    def _garbage(user, **kw):
        return "không phải json", None, {"elapsed_s": 1}
    monkeypatch.setattr(vcc, "complete", _garbage)
    got, err = na.score_items_cli([_raw("a")])
    assert got == {} and err


def test_heuristic_score_tiers():
    assert na.heuristic_score(_raw("Fed hạ lãi suất điều hành", summary="")) == 4
    assert na.heuristic_score(_raw("Giá vàng hôm nay", summary="")) == 3
    assert na.heuristic_score(_raw("Ca sĩ ra MV", summary="giải trí")) == 2


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
    assert got[0] == {"muc_do": 4, "nhan": "negative", "tac_dong": "Tỷ giá ép nhóm vay USD"}
    assert got[1]["muc_do"] == 1 and 2 not in got
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


def test_format_message_is_telegram_safe_html():
    recs = [_rec(5, title="Fed <bất ngờ> hạ lãi suất", nhan="positive"),
            _rec(3, title="Giá vàng", tac_dong="", link="")]
    txt = na.format_message(recs, NOW, 3, "claude")
    assert txt.startswith("📰 <b>Tin quan trọng</b> · 10:05 02/10")
    assert "🔴 5/5 · <b>Fed <bất ngờ> hạ lãi suất</b>" in txt and "▲ kênh" in txt
    assert "🟡 3/5" in txt and "https://l" in txt
    assert "2 tin ≥ mức 3/5 · chấm bởi Claude Code" in txt
    # chỉ dùng tag trong whitelist của vnstock_telegram → sanitize giữ nguyên tag chủ đích
    import vnstock_telegram as tg
    out = tg._sanitize_html(txt)
    assert "<b>Tin quan trọng</b>" in out and "&lt;bất ngờ&gt;" in out


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
    by_title = {"Fed": {"muc_do": 5, "nhan": "TÍCH_CỰC", "tac_dong": "Ngân hàng, vốn ngoại hưởng lợi"},
                "Ca sĩ": {"muc_do": 1, "nhan": "TRUNG_LẬP", "tac_dong": "không tác động trực tiếp"},
                "vàng": {"muc_do": 2, "nhan": "TRUNG_LẬP", "tac_dong": "PNJ hai chiều"}}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title)
    assert calls[0]["user"].index("Giá vàng") < calls[0]["user"].index("Fed")   # mới trước
    assert rc == 0 and len(calls) == 1 and len(sent) == 1
    assert "Fed hạ lãi suất" in sent[0] and "Ca sĩ" not in sent[0] and "Giá vàng" not in sent[0]
    seen = na.load_seen()["items"]
    assert len(seen) == 3
    fed = seen[na.item_hash(items[0])]
    assert fed["sent"] is True and fed["score"] == 5 and fed["sent_at"]
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
    by_title = {t: {"muc_do": 4, "nhan": "TIÊU_CỰC", "tac_dong": "x"} for t in titles}
    rc, calls, sent = _run(monkeypatch, items, by_title=by_title, max_send=3)
    assert len(sent) == 1 and sent[0].count("🟠 4/5") == 3
    rc2, calls2, sent2 = _run(monkeypatch, items, by_title=by_title, max_send=3)
    assert not calls2 and len(sent2) == 1 and sent2[0].count("🟠 4/5") == 1
    assert "lượt trước" in sent2[0]
    assert all(r["sent"] for r in na.load_seen()["items"].values())


def test_run_telegram_failure_keeps_items_unsent_and_flags_marker(monkeypatch):
    def _boom(text):
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set")
    rc, calls, _ = _run(monkeypatch, [_raw("Fed")], sender=_boom,
                        results=[{"i": 0, "muc_do": 5, "nhan": "x", "tac_dong": "y"}])
    assert rc == 1
    rec = next(iter(na.load_seen()["items"].values()))
    assert rec["sent"] is False and rec["score"] == 5
    assert "TELEGRAM_BOT_TOKEN" in na.read_status()["error"]


def test_run_dry_run_prints_but_writes_nothing(monkeypatch, capsys):
    rc, calls, sent = _run(monkeypatch, [_raw("Fed")], dry_run=True,
                           results=[{"i": 0, "muc_do": 5, "nhan": "x", "tac_dong": "y"}])
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
    calls = _fake_complete(monkeypatch, results=[{"i": 0, "muc_do": 4, "nhan": "x", "tac_dong": "y"}])
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
