"""Tests for vnstock_macro — macro tracker (lãi suất & tỷ giá) + brief wiring.

The live FX fetch (fetch_usdvnd) needs network and is not exercised here; we test
the cache/seed/change-detection/loader logic, the pressure score, the macro-news
keyword filter, and the brief block/guard/sentiment integration with fixtures.
"""
import json

import vnstock_macro as mac


def _use_tmp_cache(tmp_path, monkeypatch):
    p = tmp_path / "macro_indicators.json"
    monkeypatch.setattr(mac, "_CACHE", p)
    return p


def _write(p, indicators):
    p.write_text(json.dumps({"indicators": indicators}), encoding="utf-8")


# ── cache / seed / set ───────────────────────────────────────────────────────


def test_ensure_defs_seeds_policy_rate_only_once(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    cache = mac._ensure_defs({})
    sbv = cache["indicators"]["sbv_policy_rate"]
    assert sbv["history"] == {"2023-06-19": 4.5}
    assert sbv["kind"] == "rate"
    # usdvnd / interbank have no seed → empty history (omitted from the brief)
    assert cache["indicators"]["usdvnd"]["history"] == {}
    assert cache["indicators"]["interbank_on"]["history"] == {}
    # idempotent: a user edit to the seed is not clobbered on re-scaffold
    sbv["history"]["2024-06-19"] = 4.5
    cache2 = mac._ensure_defs(cache)
    assert cache2["indicators"]["sbv_policy_rate"]["history"] == {
        "2023-06-19": 4.5, "2024-06-19": 4.5}


def test_set_value_round_trips_and_validates(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    mac.set_value("interbank_on", 4.2, as_of="2026-06-13")
    macro = mac.load_macro()
    ib = next(m for m in macro if m["key"] == "interbank_on")
    assert ib["value"] == 4.2 and ib["as_of"] == "2026-06-13"
    assert ib["source"] == "manual"
    # unknown key rejected
    try:
        mac.set_value("not_a_key", 1.0)
        assert False, "expected KeyError"
    except KeyError:
        pass


# ── change detection / effective-date picking ────────────────────────────────


def test_load_macro_change_fx_pct_and_rate_delta(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    _write(p, {
        "usdvnd": {"label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
                   "kind": "fx", "source": "open.er-api.com",
                   "history": {"2026-06-12": 25000.0, "2026-06-13": 25250.0}},
        "interbank_on": {"label": "Lãi suất liên ngân hàng ON", "unit": "%/năm",
                         "kind": "rate", "source": "manual",
                         "history": {"2026-06-12": 3.9, "2026-06-13": 4.2}},
    })
    macro = {m["key"]: m for m in mac.load_macro()}
    fx = macro["usdvnd"]
    assert fx["value"] == 25250.0 and fx["prev_value"] == 25000.0
    assert fx["change"]["dir"] == 1
    assert fx["change"]["pct"] == 1.0          # +250 / 25000 = +1.00%
    ib = macro["interbank_on"]
    assert round(ib["change"]["delta"], 2) == 0.30 and ib["change"]["dir"] == 1


def test_load_macro_is_effective_date_aware_state_not_flow(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    _write(p, {"usdvnd": {"label": "x", "unit": "VND", "kind": "fx",
                          "history": {"2026-06-10": 25000.0,
                                      "2026-06-13": 25300.0}}})
    # asking for 2026-06-12 → last reading on/before it (the 10th), with change
    # vs the prior reading (none here → change None). A level is a STATE, so we
    # surface the last-known one rather than dropping it like a daily flow.
    m = mac.load_macro("2026-06-12")[0]
    assert m["value"] == 25000.0 and m["as_of"] == "2026-06-10"
    assert m["change"] is None
    # asking for the latest date → newest reading + change vs the 10th
    m2 = mac.load_macro("2026-06-13")[0]
    assert m2["value"] == 25300.0 and m2["change"]["dir"] == 1
    # empty cache → []
    p.write_text("{}", encoding="utf-8")
    assert mac.load_macro("2026-06-13") == []


# ── pressure score (sentiment signal #8) ─────────────────────────────────────


def test_pressure_rates_up_and_vnd_weaker_are_bearish(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    _write(p, {
        "usdvnd": {"label": "x", "unit": "VND", "kind": "fx",
                   "history": {"2026-06-12": 25000.0, "2026-06-13": 25500.0}},
        "interbank_on": {"label": "y", "unit": "%/năm", "kind": "rate",
                         "history": {"2026-06-12": 3.5, "2026-06-13": 4.5}},
    })
    pr = mac.macro_pressure_score(mac.load_macro())
    assert pr is not None
    assert pr["score"] < 0 and pr["dir"] == -1          # tightening = bearish
    assert "thắt chặt" in pr["label"]


def test_pressure_easing_is_bullish_and_noise_is_ignored(tmp_path, monkeypatch):
    p = _use_tmp_cache(tmp_path, monkeypatch)
    # rate cut = easing → positive
    _write(p, {"sbv_policy_rate": {"label": "x", "unit": "%/năm", "kind": "rate",
                                   "history": {"2025-01-01": 4.5,
                                               "2026-01-01": 4.0}}})
    assert mac.macro_pressure_score(mac.load_macro())["dir"] == 1
    # a <0.3% FX wobble carries no signal → None (won't dilute the composite)
    _write(p, {"usdvnd": {"label": "x", "unit": "VND", "kind": "fx",
                          "history": {"2026-06-12": 25000.0,
                                      "2026-06-13": 25020.0}}})
    assert mac.macro_pressure_score(mac.load_macro()) is None
    # no change at all → None
    assert mac.macro_pressure_score([{"key": "usdvnd", "kind": "fx",
                                      "value": 1, "change": None}]) is None


# ── Vietstock interbank (VNIBOR) auto-fetch parsing ──────────────────────────


def test_extract_token_is_order_and_quote_agnostic():
    # name-before-value, double quotes
    assert mac._extract_token(
        '<input name="__RequestVerificationToken" type="hidden" value="ABC123"/>') == "ABC123"
    # value-before-name, single quotes (Vietstock markup varies)
    assert mac._extract_token(
        "<input value='XY9' name='__RequestVerificationToken'>") == "XY9"
    # token absent → None (handshake aborts, fetch returns None, cache untouched)
    assert mac._extract_token('<input name="other" value="z">') is None
    assert mac._extract_token("") is None
    # UNQUOTED attributes — Vietstock's real markup: value=jzkB… with no quotes
    assert mac._extract_token(
        "<input name=__RequestVerificationToken type=hidden "
        "value=jzkBOHmJ-ffdOg_4d5MJqek1>") == "jzkBOHmJ-ffdOg_4d5MJqek1"
    # fallback: token name in a non-<input> element, name…value order
    assert mac._extract_token(
        '<meta name="__RequestVerificationToken" value="TOK7">') == "TOK7"
    # fallback: value…name reversed order, outside an <input>
    assert mac._extract_token(
        '<x value="REV5" data-id="1" __RequestVerificationToken>') == "REV5"


def test_parse_vs_date_handles_formats():
    assert mac._parse_vs_date("2026-06-13T00:00:00") == "2026-06-13"
    assert mac._parse_vs_date("13/06/2026") == "2026-06-13"
    d = mac._parse_vs_date("/Date(1718323200000)/")          # ASP.NET ms epoch
    assert d and len(d) == 10 and d[4] == "-" and d[7] == "-"
    assert mac._parse_vs_date("rác") is None


def test_extract_interbank_on_prefers_overnight_and_latest():
    # mixed tenors + two overnight rows on different days → newest ON wins
    js = [
        {"ReportComponentName": "Qua đêm", "Value": 9.35, "ReportDate": "/Date(1718323200000)/"},
        {"ReportComponentName": "1 Tuần", "Value": 9.80, "ReportDate": "/Date(1718323200000)/"},
        {"ReportComponentName": "Qua đêm", "Value": 8.90, "ReportDate": "/Date(1718150400000)/"},
    ]
    val, as_of = mac.extract_interbank_on(js)
    assert val == 9.35                                       # ON, not the 1-week 9.80
    assert as_of == mac._parse_vs_date("/Date(1718323200000)/")   # tz-independent


def test_extract_interbank_on_wrapper_fallback_and_none():
    # {"data": [...]} wrapper + overnight label
    js = {"data": [{"ReportComponentName": "Overnight", "Value": 7.5,
                    "ReportDate": "2026-06-13"}]}
    assert mac.extract_interbank_on(js) == (7.5, "2026-06-13")
    # no overnight label → fall back to any in-range rate row
    assert mac.extract_interbank_on(
        [{"Tenor": "1 Tháng", "Value": 6.2, "Date": "2026-06-13"}]) == (6.2, "2026-06-13")
    # non-list / empty → None (caller keeps prior value, never fabricates)
    assert mac.extract_interbank_on("nope") is None
    assert mac.extract_interbank_on([]) is None


def test_refresh_records_interbank_only_when_opted_in(tmp_path, monkeypatch):
    # Vietstock VNIBOR is paywalled on the free tier → auto-fetch is opt-in via
    # VNSTOCK_MACRO_VIETSTOCK=1 (for paid accounts).
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: 25500.0)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    monkeypatch.setattr(mac, "fetch_interbank_on", lambda: (9.35, "2026-06-13"))
    monkeypatch.setenv("VNSTOCK_MACRO_VIETSTOCK", "1")
    mac.refresh()
    m = {x["key"]: x for x in mac.load_macro()}
    assert m["usdvnd"]["value"] == 25500.0
    assert m["interbank_on"]["value"] == 9.35
    assert m["interbank_on"]["as_of"] == "2026-06-13"
    assert m["interbank_on"]["source"] == "vietstock"
    # a FAILED interbank fetch must NOT clobber a manual --set value
    mac.set_value("interbank_on", 11.0, as_of="2026-06-14")
    monkeypatch.setattr(mac, "fetch_interbank_on", lambda: None)
    mac.refresh()
    assert {x["key"]: x for x in mac.load_macro()}["interbank_on"]["value"] == 11.0


def test_refresh_skips_interbank_fetch_by_default(tmp_path, monkeypatch):
    # Default (no opt-in): never even call the paywalled Vietstock fetch.
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.delenv("VNSTOCK_MACRO_VIETSTOCK", raising=False)
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: 25500.0)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    calls = {"n": 0}
    monkeypatch.setattr(mac, "fetch_interbank_on",
                        lambda: calls.__setitem__("n", calls["n"] + 1) or (9.9, "2026-06-13"))
    mac.refresh()
    assert calls["n"] == 0                                # not called by default
    keys = {x["key"] for x in mac.load_macro()}
    assert "usdvnd" in keys and "interbank_on" not in keys


# ── macro-news keyword filter ────────────────────────────────────────────────


def test_macro_news_filters_by_keyword():
    news = [
        {"news_title": "SBV điều hành tỷ giá trung tâm tăng", "_date_sort": "2026-06-13",
         "ticker": "VCB"},
        {"news_title": "Fed giữ nguyên lãi suất tháng 6", "_date_sort": "2026-06-12",
         "ticker": ""},
        {"news_title": "FPT ký hợp đồng phần mềm 100 tỷ", "_date_sort": "2026-06-13",
         "ticker": "FPT"},                              # not macro → excluded
    ]
    out = mac.macro_news(news=news, days=3650, limit=5)
    titles = [n["title"] for n in out]
    assert any("tỷ giá" in t for t in titles)
    assert any("lãi suất" in t for t in titles)
    assert not any("FPT" in t for t in titles)


# ── brief rendering + guard + sentiment wiring ───────────────────────────────


def test_macro_block_renders_en_numbers_arrows_and_asof():
    import vnstock_brief as vb
    macro = [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
         "kind": "fx", "value": 25500.0, "as_of": "2026-06-13",
         "prev_value": 25000.0, "prev_as_of": "2026-06-12",
         "change": {"delta": 500.0, "pct": 2.0, "dir": 1}, "source": "open.er-api.com"},
        {"key": "sbv_policy_rate", "label": "Lãi suất tái cấp vốn (SBV)",
         "unit": "%/năm", "kind": "rate", "value": 4.5, "as_of": "2023-06-19",
         "prev_value": None, "prev_as_of": None, "change": None, "source": "seed"},
    ]
    block = vb._macro_block(macro)
    assert "🌐 Vĩ mô" in block
    assert "25,500 VND" in block            # EN thousands separator
    assert "+2.00% so với 2026-06-12" in block and "▲" in block
    assert "VND yếu đi" in block
    assert "4.50%/năm" in block and "đi ngang" in block
    assert "tính đến 2026-06-13" in block   # header carries the latest as_of


def test_enforce_macro_replaces_section_body_and_is_idempotent():
    import vnstock_brief as vb
    ctx = {"macro": [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
         "kind": "fx", "value": 25500.0, "as_of": "2026-06-13",
         "prev_value": 25000.0, "prev_as_of": "2026-06-12",
         "change": {"delta": 500.0, "pct": 2.0, "dir": 1}, "source": "x"}]}
    # LLM mangled the figures (wrong rate + no change) — guard must canonicalise.
    text = (
        "## 🌐 Vĩ mô: lãi suất & tỷ giá\n"
        "- Tỷ giá USD/VND khoảng 24,000, ổn định\n"
        "## 💡 Đề xuất giao dịch\n- (none)\n"
    )
    fixed = vb.enforce_macro(text, ctx)
    assert "25,500 VND" in fixed and "24,000" not in fixed
    assert "## 💡 Đề xuất giao dịch" in fixed       # next section preserved
    # idempotent
    assert vb.enforce_macro(fixed, ctx) == fixed
    # no macro in ctx → no-op
    assert vb.enforce_macro(text, {}) == text


def test_enforce_macro_splices_over_denial_when_no_section():
    import vnstock_brief as vb
    ctx = {"macro": [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND", "unit": "VND", "kind": "fx",
         "value": 25500.0, "as_of": "2026-06-13", "prev_value": None,
         "prev_as_of": None, "change": None, "source": "x"}]}
    text = "## 🎯 TLDR\nChưa có dữ liệu vĩ mô nào đáng kể.\n"
    fixed = vb.enforce_macro(text, ctx)
    assert "25,500 VND" in fixed


def _fx_ctx():
    return {"macro": [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
         "kind": "fx", "value": 26173.8, "as_of": "2026-06-16",
         "prev_value": 26191.9, "prev_as_of": "2026-06-15",
         "change": {"delta": -18.1, "pct": -0.07, "dir": -1},
         "source": "open.er-api.com"}], "macro_news": []}


def test_enforce_macro_header_detection_is_loose_to_reformatting():
    # Close 16/06: macro section header without "##" wasn't pinned → a bad "-3%"
    # survived (load_macro had -0.07%). Looser header match pins it anyway.
    import vnstock_brief as vb
    brief = ("🌐 Vĩ mô: lãi suất & tỷ giá\n"
             "- Tỷ giá USD/VND (tham chiếu): 26,174 VND (tính đến 2026-06-16) "
             "▼ -3% so với 2026-06-15 (VND mạnh lên)\n"
             "## 💡 Đề xuất giao dịch\n- none\n")
    f = vb.enforce_macro(brief, _fx_ctx())
    assert "-0.07% so với" in f and "-3%" not in f


def test_enforce_macro_fx_pct_safety_net():
    import vnstock_brief as vb
    line = ("- Tỷ giá USD/VND (tham chiếu): 26,174 VND (tính đến 2026-06-16) "
            "▼ -3% so với 2026-06-15 (VND mạnh lên)")
    f = vb.enforce_macro_fx_pct(line, _fx_ctx())
    assert "▼ -0.07% so với" in f and "-3%" not in f
    assert vb.enforce_macro_fx_pct(f, _fx_ctx()) == f                 # idempotent
    # non-FX line + no-fx-change ctx → untouched
    assert vb.enforce_macro_fx_pct("- Lãi suất ON: 12.00%/năm — đi ngang",
                                   _fx_ctx()) == "- Lãi suất ON: 12.00%/năm — đi ngang"
    assert vb.enforce_macro_fx_pct(line, {}) == line


def test_sentiment_adds_macro_signal_and_shifts_momentum():
    from vnstock_market_sentiment import compute_market_sentiment
    base = compute_market_sentiment(breadth={"above_ma200_pct": 50, "ad_ratio": 1.1})
    tight = compute_market_sentiment(
        breadth={"above_ma200_pct": 50, "ad_ratio": 1.1},
        macro={"score": -0.8, "label": "lãi suất tăng (môi trường thắt chặt)"},
    )
    names = [s["name"] for s in tight["signals"]]
    assert "Vĩ mô (lãi suất/tỷ giá)" in names
    assert tight["momentum"] < base["momentum"]        # tightening drags momentum
    # a None macro reading adds no signal
    none_macro = compute_market_sentiment(
        breadth={"above_ma200_pct": 50, "ad_ratio": 1.1}, macro=None)
    assert all(s["name"] != "Vĩ mô (lãi suất/tỷ giá)" for s in none_macro["signals"])
