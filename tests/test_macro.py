"""Tests for vnstock_macro — macro tracker (lãi suất & tỷ giá) + brief wiring.

The live FX fetch (fetch_usdvnd) needs network and is not exercised here; we test
the cache/seed/change-detection/loader logic, the pressure score, the macro-news
keyword filter, and the brief block/guard/sentiment integration with fixtures.
"""
import json

import pytest

import vnstock_macro as mac


@pytest.fixture(autouse=True)
def _no_external_macro_fetch(monkeypatch):
    """refresh() gọi cả loạt fetcher mạng — chặn TOÀN BỘ mặc định để test
    hermetic; test nào cần thì tự re-patch. BÀI HỌC desktop 17/07: sandbox
    bị chặn mạng nên fetcher lọt fixture vẫn 'vô tình pass', chạy trên máy
    CÓ MẠNG là fetch thật đè fixture (ON 4.11 thật đè 9.35 fake) — thêm
    fetcher mới vào refresh() thì PHẢI thêm vào đây."""
    monkeypatch.setattr(mac, "_fetch_nso", lambda: None)
    monkeypatch.setattr(mac, "_fetch_fred", lambda: None)
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    monkeypatch.setattr(mac, "_fetch_hnx", lambda: None)
    monkeypatch.setattr(mac, "_fetch_sbv", lambda: None)
    monkeypatch.setattr(mac, "_fetch_sbv_daily", lambda: None)
    monkeypatch.setattr(mac, "_fetch_sbv_policy", lambda: None)
    # FX: chặn qua ENDPOINT rỗng (không patch hàm — test parser cần hàm thật)
    monkeypatch.setattr(mac, "_FX_ENDPOINTS", ())


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
    # chỉ số không đổi bị NÉN vào 1 dòng gộp thay vì mỗi chỉ số 1 bullet
    assert "Đi ngang/chưa có kỳ mới: Lãi suất tái cấp vốn (SBV) 4.50%/năm "\
           "(2023-06-19)" in block
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


def test_enforce_macro_strips_prompt_directive_from_published_brief():
    # Leak thật close 14/07: phần (2/2) Telegram mở đầu bằng nguyên dòng chỉ
    # thị "→ Lãi suất TĂNG … DÙNG bối cảnh này … KHÔNG bịa chỉ số" — directive
    # thuộc PROMPT, guard splice body không được mang nó vào brief xuất bản.
    import vnstock_brief as vb
    ctx = {"macro": [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
         "kind": "fx", "value": 25500.0, "as_of": "2026-06-13",
         "prev_value": 25000.0, "prev_as_of": "2026-06-12",
         "change": {"delta": 500.0, "pct": 2.0, "dir": 1}, "source": "x"}]}
    text = (
        "## 🌐 Vĩ mô: lãi suất & tỷ giá\n"
        "- Tỷ giá USD/VND khoảng 24,000\n"
        "→ Lãi suất TĂNG / VND mất giá = THẮT CHẶT. DÙNG bối cảnh này khi chốt "
        "Bias. KHÔNG bịa chỉ số vĩ mô ngoài danh sách trên.\n"
        "## 💡 Đề xuất giao dịch\n- (none)\n"
    )
    fixed = vb.enforce_macro(text, ctx)
    assert "DÙNG bối cảnh này" not in fixed and "KHÔNG bịa" not in fixed
    assert "25,500 VND" in fixed
    # prompt renderer VẪN có directive (chỉ guard mới bỏ)
    body_prompt = vb._macro_body_lines(ctx["macro"])
    assert any("KHÔNG bịa chỉ số" in l for l in body_prompt)
    # catch-all: model echo directive ở chỗ khác → enforce_no_instruction_leak dọn
    echoed = ("## 🎯 TLDR\nThị trường giảm.\n"
              "→ DÙNG các tin trên khi đánh giá bối cảnh vĩ mô + rủi ro. "
              "TUYỆT ĐỐI KHÔNG bịa tin/tiêu đề ngoài danh sách này.\n"
              "→ Dòng tiền khối ngoại chuyển sang mua ròng dầu khí.\n")
    cleaned = vb.enforce_no_instruction_leak(echoed, {})
    assert "TUYỆT ĐỐI" not in cleaned
    assert "→ Dòng tiền khối ngoại" in cleaned    # "→" nội dung thật giữ nguyên


def test_enforce_market_news_strips_directive_from_published_brief():
    import vnstock_brief as vb
    ctx = {"market_news": [
        {"title": "Tin A", "_sentiment": "negative", "_date_sort": "2026-07-14",
         "source_feed": "CafeF", "_impact": "xấu cho ngân hàng"}]}
    text = ("## 📰 Tin kinh tế/chính trị nổi bật\n"
            "- Tin bịa nào đó\n"
            "→ DÙNG các tin trên khi đánh giá bối cảnh vĩ mô + rủi ro.\n"
            "## 📌 Kế tiếp\n- x\n")
    fixed = vb.enforce_market_news(text, ctx)
    assert "DÙNG các tin trên" not in fixed and "Tin A" in fixed
    assert vb.enforce_market_news(fixed, ctx) == fixed        # idempotent
    # prompt renderer vẫn giữ directive
    assert any("TUYỆT ĐỐI KHÔNG bịa" in l
               for l in vb._market_news_body_lines(ctx["market_news"]))


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


# ── _DEFS metadata: fmt helpers + pressure generic (CPI/IIP/PMI) ─────────────


def test_fmt_value_uses_per_def_decimals_and_units():
    assert mac.fmt_value({"key": "usdvnd", "value": 26219.4, "unit": "VND",
                          "kind": "fx"}) == "26,219 VND"
    assert mac.fmt_value({"key": "interbank_on", "value": 5.67,
                          "unit": "%/năm", "kind": "rate"}) == "5.67%/năm"
    assert mac.fmt_value({"key": "cpi_yoy", "value": 4.69,
                          "unit": "%", "kind": "pct"}) == "4.69%"
    assert mac.fmt_value({"key": "pmi", "value": 48.9,
                          "unit": "điểm", "kind": "index"}) == "48.9 điểm"


def test_fmt_change_pmi_uses_diem_and_moves_labels():
    arrow, mag, hint = mac.fmt_change({
        "key": "pmi", "kind": "index", "unit": "điểm", "value": 48.9,
        "change": {"delta": -1.5, "pct": None, "dir": -1}})
    assert (arrow, mag, hint) == ("▼", "-1.50 điểm", "PMI suy yếu")
    assert mac.fmt_change({"key": "pmi", "change": None}) is None


def test_fmt_change_suppresses_zero_at_display_precision():
    # FX nhích 0.3đ trên 26,178 → pct +0.001% làm tròn "+0.00%" nhưng dir=+1
    # → từng hiện "▲ +0.00% (VND yếu đi)" = tín hiệu giả (báo cáo tuần 17/07)
    assert mac.fmt_change({
        "key": "usdvnd", "kind": "fx", "unit": "VND", "value": 26178.4,
        "change": {"delta": 0.3, "pct": 0.001, "dir": 1}}) is None
    # lãi suất delta +0.001đ% → "+0.00 điểm %" cũng bị nén
    assert mac.fmt_change({
        "key": "interbank_on", "kind": "rate", "unit": "%/năm", "value": 4.16,
        "change": {"delta": 0.001, "pct": None, "dir": 1}}) is None
    # đổi thật ≥ 0.01 giữ nguyên
    assert mac.fmt_change({
        "key": "usdvnd", "kind": "fx", "unit": "VND", "value": 26178.0,
        "change": {"delta": 80.0, "pct": 0.31, "dir": 1}}) is not None


def test_pressure_generic_cpi_bearish_iip_bullish_pmi_noise_ignored():
    rows = [
        {"key": "cpi_yoy", "kind": "pct",
         "change": {"delta": 0.5, "pct": None, "dir": 1}},    # lạm phát tăng → âm
        {"key": "iip_yoy", "kind": "pct",
         "change": {"delta": 2.0, "pct": None, "dir": 1}},    # IIP tăng tốc → dương
        {"key": "pmi", "kind": "index",
         "change": {"delta": 0.5, "pct": None, "dir": 1}},    # < min 1.0 → bỏ qua
    ]
    p = mac.macro_pressure_score(rows)
    assert p is not None
    assert "lạm phát tăng" in p["label"] and "sản xuất CN tăng tốc" in p["label"]
    assert "PMI" not in p["label"]
    # cpi: -0.5/2 = -0.25; iip: +2/5 = +0.4 → trung bình +0.075
    assert p["score"] == 0.08 or abs(p["score"] - 0.075) < 0.01


# ── PMI từ RSS cache (P3) ────────────────────────────────────────────────────


# tham chiếu HÀM THẬT, chụp trước khi autouse fixture patch mac._pmi_from_news
_REAL_PMI_FROM_NEWS = mac._pmi_from_news


def _patch_news(monkeypatch, items):
    import vnstock_news_feeds as nf
    monkeypatch.setattr(nf, "_load_cache", lambda: items)


def test_pmi_from_news_picks_latest_vn_title_skips_foreign(monkeypatch):
    _patch_news(monkeypatch, [
        {"title": "PMI ngành sản xuất Việt Nam tháng 6/2026 đạt 48,9 điểm",
         "_date_sort": "2026-07-01T08:00:00"},
        {"title": "PMI sản xuất Trung Quốc bật lên 50,4 điểm",
         "_date_sort": "2026-07-02T08:00:00"},          # nước ngoài → bỏ
        {"title": "PMI Việt Nam tháng 5 đạt 51,2 điểm",
         "_date_sort": "2026-06-02T08:00:00"},          # cũ hơn
        {"title": "PMI cải thiện tháng thứ 3 liên tiếp",
         "_date_sort": "2026-07-03T08:00:00"},          # không có số
        {"title": "Chỉ số PMI đạt 99,9 điểm",
         "_date_sort": "2026-07-04T08:00:00"},          # ngoài sanity 25-75
    ])
    assert _REAL_PMI_FROM_NEWS() == (48.9, "2026-07-01")


def test_pmi_from_news_none_when_cache_empty(monkeypatch):
    _patch_news(monkeypatch, [])
    assert _REAL_PMI_FROM_NEWS() is None


def test_refresh_pmi_records_only_when_newer_than_existing(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    # --set tay 05/07 = 50.0; tin cũ hơn (01/07) KHÔNG được đè
    mac.set_value("pmi", 50.0, as_of="2026-07-05")
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: (48.9, "2026-07-01"))
    mac.refresh()
    row = {x["key"]: x for x in mac.load_macro()}["pmi"]
    assert row["value"] == 50.0 and row["source"] == "manual"
    # tin MỚI HƠN (06/07) → ghi, nguồn news-rss
    monkeypatch.setattr(mac, "_pmi_from_news", lambda: (49.5, "2026-07-06"))
    mac.refresh()
    row = {x["key"]: x for x in mac.load_macro()}["pmi"]
    assert row["value"] == 49.5 and row["source"] == "news-rss"
    assert row["as_of"] == "2026-07-06"


def test_refresh_pmi_news_kill_switch(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    monkeypatch.setenv("VNSTOCK_MACRO_PMI_NEWS", "0")
    monkeypatch.setattr(mac, "fetch_usdvnd", lambda: None)
    monkeypatch.setattr(mac, "_fetch_vbma", lambda: None)
    calls = {"n": 0}
    monkeypatch.setattr(mac, "_pmi_from_news",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    mac.refresh()
    assert calls["n"] == 0


def test_macro_block_compresses_flat_indicators_into_one_line():
    import vnstock_brief as vb
    macro = [
        {"key": "cpi_yoy", "label": "CPI so với cùng kỳ (YoY)", "unit": "%",
         "kind": "pct", "value": 4.69, "as_of": "2026-06-30",
         "prev_value": 4.19, "prev_as_of": "2026-05-31",
         "change": {"delta": 0.5, "pct": 11.9, "dir": 1}, "source": "nso"},
        {"key": "sbv_policy_rate", "label": "Lãi suất tái cấp vốn (SBV)",
         "unit": "%/năm", "kind": "rate", "value": 4.5, "as_of": "2023-06-19",
         "prev_value": None, "prev_as_of": None, "change": None, "source": "seed"},
        {"key": "pmi", "label": "PMI sản xuất VN (S&P Global)", "unit": "điểm",
         "kind": "index", "value": 48.9, "as_of": "2026-06-30",
         "prev_value": None, "prev_as_of": None, "change": None, "source": "manual"},
    ]
    body = vb._macro_body_lines(macro)
    # chỉ số CÓ thay đổi giữ bullet riêng, kèm delta "điểm %" + nhãn moves
    assert any("CPI so với cùng kỳ (YoY): 4.69%" in l
               and "+0.50 điểm %" in l and "lạm phát tăng" in l for l in body)
    # 2 chỉ số không đổi gộp đúng 1 dòng
    flat = [l for l in body if l.startswith("- Đi ngang")]
    assert len(flat) == 1
    assert "Lãi suất tái cấp vốn (SBV) 4.50%/năm (2023-06-19)" in flat[0]
    assert "PMI sản xuất VN (S&P Global) 48.9 điểm (2026-06-30)" in flat[0]


# ── nhắc set PMI khi quên (deterministic, chèn vào brief) ────────────────────


def test_pmi_reminder_fires_when_missing_or_stale_after_grace():
    # chưa từng có PMI, đã qua mùng 3 → nhắc đúng THÁNG TRƯỚC
    rem = mac.pmi_reminder([], today="2026-07-08")
    assert rem and "PMI tháng 6/2026" in rem and "--set pmi" in rem
    # có số nhưng là của kỳ cũ (as_of tháng trước) → nhắc kèm số đang có
    stale = [{"key": "pmi", "kind": "index", "unit": "điểm", "value": 51.2,
              "as_of": "2026-06-02", "change": None}]
    rem2 = mac.pmi_reminder(stale, today="2026-07-08")
    assert rem2 and "51.2 điểm" in rem2 and "2026-06-02" in rem2


def test_pmi_reminder_silent_when_fresh_or_in_grace_window():
    # PMI tháng 6 ghi ngày 01/07 (news) → as_of thuộc tháng hiện tại → im lặng
    fresh = [{"key": "pmi", "kind": "index", "unit": "điểm", "value": 48.9,
              "as_of": "2026-07-01", "change": None}]
    assert mac.pmi_reminder(fresh, today="2026-07-08") is None
    # mùng 1-2 = ân hạn cho đường RSS tự động → chưa nhắc dù thiếu
    assert mac.pmi_reminder([], today="2026-07-02") is None


def test_pmi_reminder_january_wraps_to_december():
    rem = mac.pmi_reminder([], today="2026-01-05")
    assert rem and "PMI tháng 12/2025" in rem


def test_macro_body_lines_include_pmi_reminder(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setattr(mac, "pmi_reminder",
                        lambda macro, today=None: "⏰ PMI tháng 6/2026 chưa được cập nhật")
    body = vb._macro_body_lines([
        {"key": "usdvnd", "label": "Tỷ giá USD/VND", "unit": "VND", "kind": "fx",
         "value": 26219.0, "as_of": "2026-07-08", "prev_value": None,
         "prev_as_of": None, "change": None, "source": "x"}])
    assert any(l.startswith("- ⏰ PMI tháng 6/2026") for l in body)


def test_brief_section_extracts_by_marker():
    import vnstock_brief as vb
    out = ("## 🎯 TLDR\n- Stance: TRUNG TÍNH\n\n"
           "## 🌐 Vĩ mô: lãi suất & tỷ giá (tính đến 2026-07-08)\n"
           "- CPI so với cùng kỳ (YoY): 4.69% (tính đến 2026-06-30)\n"
           "## 💡 Đề xuất giao dịch\n- (none)\n")
    sec = vb.brief_section(out, "🌐")
    assert sec.startswith("## 🌐 Vĩ mô")
    assert "CPI so với cùng kỳ" in sec
    assert "Đề xuất giao dịch" not in sec                  # dừng đúng ranh giới mục
    assert vb.brief_section(out, "🎯").endswith("TRUNG TÍNH")
    assert vb.brief_section(out, "📚") == ""               # không có mục → rỗng
    assert vb.brief_section("", "🌐") == ""


# ── gauge thanh khoản dẫn xuất: ON − lãi suất điều hành ──────────────────────


def _liq_rows(on=None, policy=None, y10=None):
    rows = []
    if on is not None:
        rows.append({"key": "interbank_on", "label": "Lãi suất liên ngân hàng ON",
                     "kind": "rate", "unit": "%/năm",
                     "value": on, "as_of": "2026-07-03", "change": None})
    if policy is not None:
        rows.append({"key": "sbv_policy_rate", "label": "Lãi suất tái cấp vốn (SBV)",
                     "kind": "rate", "unit": "%/năm",
                     "value": policy, "as_of": "2026-06-15", "change": None})
    if y10 is not None:
        rows.append({"key": "govt_bond_yield_10y", "label": "Lợi suất TPCP 10 năm",
                     "kind": "rate",
                     "unit": "%/năm", "value": y10, "as_of": "2026-07-03",
                     "change": None})
    return rows


def _term_rows(policy=None, y2=None, y10=None):
    rows = _liq_rows(policy=policy, y10=y10)
    if y2 is not None:
        rows.append({"key": "govt_bond_yield_2y", "label": "Lợi suất TPCP 2 năm",
                     "kind": "rate",
                     "unit": "%/năm", "value": y2, "as_of": "2026-07-03",
                     "change": None})
    return rows


def test_liquidity_spread_bands_and_slope():
    # Data thật 08/07: ON 5.67 vs điều hành 4.5 → +1.17 = CĂNG (dir -1)
    liq = mac.liquidity_spread(_liq_rows(on=5.67, policy=4.5, y10=4.4))
    assert liq["spread"] == pytest.approx(1.17)
    assert liq["dir"] == -1 and "CĂNG" in liq["label"]
    assert liq["slope_10y_on"] == pytest.approx(-1.27)
    # ON thấp sâu dưới điều hành → DƯ THỪA (dir +1)
    flush = mac.liquidity_spread(_liq_rows(on=2.0, policy=4.5))
    assert flush["dir"] == 1 and "DƯ THỪA" in flush["label"]
    assert "slope_10y_on" not in flush                 # thiếu 10Y → không có dốc
    # trong band → bình thường
    assert mac.liquidity_spread(_liq_rows(on=4.6, policy=4.5))["dir"] == 0


def test_liquidity_spread_none_when_inputs_missing():
    assert mac.liquidity_spread(_liq_rows(on=5.67)) is None       # thiếu điều hành
    assert mac.liquidity_spread(_liq_rows(policy=4.5)) is None    # thiếu ON
    assert mac.liquidity_spread([]) is None
    assert mac.liquidity_spread(None) is None


def test_term_spread_bands_and_slope():
    # Data thật 03/07: 10Y 4.40 vs điều hành 4.5 → −0.10 = ÂM (dir −1);
    # 10Y − 2Y = +0.90 → dốc bình thường
    ts = mac.term_spread(_term_rows(policy=4.5, y2=3.5, y10=4.4))
    assert ts["spread"] == pytest.approx(-0.10)
    assert ts["dir"] == -1 and "ÂM" in ts["label"]
    assert ts["slope_2_10"] == pytest.approx(0.90)
    assert ts["slope_dir"] == 0 and "bình thường" in ts["slope_label"]
    # inversion: 2Y > 10Y → ĐẢO NGƯỢC (slope_dir −1)
    inv = mac.term_spread(_term_rows(policy=4.5, y2=5.2, y10=5.0))
    assert inv["slope_2_10"] == pytest.approx(-0.20)
    assert inv["slope_dir"] == -1 and "ĐẢO NGƯỢC" in inv["slope_label"]
    # spread mỏng (0 ≤ spread < 0.5) → nhãn cảnh giác nhưng dir 0
    thin = mac.term_spread(_term_rows(policy=4.5, y10=4.8))
    assert thin["dir"] == 0 and "mỏng" in thin["label"]
    assert "slope_2_10" not in thin                    # thiếu 2Y → không có dốc
    # spread dày → bình thường
    assert mac.term_spread(_term_rows(policy=4.5, y10=5.5))["dir"] == 0


def test_term_spread_noise_band_does_not_call_a_4bp_gap_negative():
    """Close 08/09: 10Y 4.46 vs điều hành 4.50 → −0.04 điểm % (4 bp) mà gauge
    gắn nhãn "ÂM — chính sách THẮT (rủi ro chu kỳ)" + dir −1, rồi band phân bổ
    ăn −0.05 trên tổng −0.12 chỉ vì nhiễu làm tròn giữa hai nguồn. Trong biên
    ±_GAUGE_NOISE_BAND → dir 0, nhãn nói rõ là sát 0, không phải ÂM."""
    ts = mac.term_spread(_term_rows(policy=4.5, y2=3.9, y10=4.46))
    assert ts["spread"] == pytest.approx(-0.04)
    assert ts["dir"] == 0
    assert "ÂM" not in ts["label"].split("chưa tính")[0]   # không mở đầu bằng ÂM
    assert "sát 0" in ts["label"] and "mỏng" in ts["label"]
    # dốc 2-10 KHÔNG bị ảnh hưởng bởi vùng chết của spread
    assert ts["slope_2_10"] == pytest.approx(0.56) and ts["slope_dir"] == 0
    # biên là ĐÚNG mức −0.10: data 03/07 (−0.10) vẫn là ÂM — không nới hơn
    assert mac.term_spread(_term_rows(policy=4.5, y10=4.4))["dir"] == -1
    assert mac.term_spread(_term_rows(policy=4.5, y10=4.41))["dir"] == 0
    # phía dương không đổi: 0 ≤ spread < 0.5 vẫn là "mỏng" thường
    assert "sát 0" not in mac.term_spread(_term_rows(policy=4.5, y10=4.52))["label"]


def test_intl_spread_shares_the_noise_band():
    """Cùng bệnh phía âm: có _INTL_THIN_SPREAD cho phía dương nhưng −0.01 đã
    thành "ÂM — kém hấp dẫn vốn ngoại". Dưới 10 bp → dir 0."""
    near = mac.intl_spread(_intl_rows(vn10=4.30, us10=4.35))
    assert near["spread"] == pytest.approx(-0.05)
    assert near["dir"] == 0 and "sát 0" in near["label"]
    assert mac.intl_spread(_intl_rows(vn10=4.25, us10=4.35))["dir"] == -1   # −0.10 = ÂM
    # mức thật close 08/09 (−0.31) vẫn là ÂM
    assert mac.intl_spread(_intl_rows(vn10=4.46, us10=4.77))["dir"] == -1


def test_allocation_term_input_is_zero_inside_the_noise_band():
    """Điểm chốt của lỗi: gauge nhiễu đẩy band. Với data close 08/09 sub-score
    `term` phải là 0, không phải −0.5."""
    import vnstock_allocation as alloc
    ts = mac.term_spread(_term_rows(policy=4.5, y2=3.9, y10=4.46))
    out = alloc.compute_score({"term": {"dir": ts["dir"], "slope_dir": ts["slope_dir"]}})
    assert out["score"] == pytest.approx(0.0)


def test_term_spread_none_when_inputs_missing():
    assert mac.term_spread(_term_rows(y10=4.4)) is None        # thiếu điều hành
    assert mac.term_spread(_term_rows(policy=4.5)) is None     # thiếu 10Y
    assert mac.term_spread(_term_rows(policy=4.5, y2=3.5)) is None  # 2Y không đủ
    assert mac.term_spread([]) is None
    assert mac.term_spread(None) is None


def test_macro_body_lines_include_term_gauge():
    import vnstock_brief as vb
    body = vb._macro_body_lines(_term_rows(policy=4.5, y2=3.5, y10=4.4))
    ts_lines = [l for l in body if "Kỳ hạn & đường cong" in l]
    assert len(ts_lines) == 1
    assert "-0.10 điểm %" in ts_lines[0] and "ÂM" in ts_lines[0]
    assert "dốc 10Y − 2Y = +0.90 điểm %" in ts_lines[0]
    # thiếu input → không có dòng (no-op, không phát nhãn sai)
    body2 = vb._macro_body_lines(_term_rows(y2=3.5, y10=4.4))
    assert not any("Kỳ hạn & đường cong" in l for l in body2)


def _intl_rows(vn10=None, us10=None):
    rows = _liq_rows(y10=vn10)
    if us10 is not None:
        rows.append({"key": "us10y", "label": "Lợi suất TPCP Mỹ 10 năm (US10Y)",
                     "kind": "rate",
                     "unit": "%/năm", "value": us10, "as_of": "2026-07-09",
                     "change": None})
    return rows


def test_intl_spread_bands():
    # VN 4.40 vs US 4.35 → +0.05 = mỏng (dir 0)
    thin = mac.intl_spread(_intl_rows(vn10=4.4, us10=4.35))
    assert thin["spread"] == pytest.approx(0.05)
    assert thin["dir"] == 0 and "mỏng" in thin["label"]
    # VN thấp hơn Mỹ → ÂM (dir −1) — kém hấp dẫn vốn ngoại
    neg = mac.intl_spread(_intl_rows(vn10=3.0, us10=4.35))
    assert neg["spread"] == pytest.approx(-1.35)
    assert neg["dir"] == -1 and "ÂM" in neg["label"]
    # lợi thế rõ → dương
    assert mac.intl_spread(_intl_rows(vn10=5.5, us10=4.0))["dir"] == 0
    # thiếu 1 trong 2 → None
    assert mac.intl_spread(_intl_rows(vn10=4.4)) is None
    assert mac.intl_spread(_intl_rows(us10=4.35)) is None
    assert mac.intl_spread(None) is None


def test_macro_body_lines_include_intl_gauge_and_fed_directive():
    import vnstock_brief as vb
    rows = _intl_rows(vn10=4.4, us10=4.35)
    body = vb._macro_body_lines(rows)
    intl_lines = [l for l in body if "Chênh lệch quốc tế" in l]
    assert len(intl_lines) == 1 and "+0.05 điểm %" in intl_lines[0]
    # CHƯA có fed_funds → directive vẫn cấm bịa Fed
    assert any("Fed… chưa có trong data" in l for l in body)
    # CÓ fed_funds → mệnh đề cấm Fed được nới (luật không-bịa chung giữ nguyên)
    rows.append({"key": "fed_funds", "label": "Lãi suất Fed (effective)",
                 "kind": "rate", "unit": "%/năm", "value": 4.33,
                 "as_of": "2026-07-10", "change": None})
    body2 = vb._macro_body_lines(rows)
    assert not any("Fed… chưa có trong data" in l for l in body2)
    assert any("KHÔNG bịa chỉ số" in l for l in body2)


def test_fetch_usdvnd_parses_currency_api_lowercase(monkeypatch):
    # Nấc 3 (currency-api fawazahmed0) trả {"usd": {"vnd": ...}} chữ thường —
    # 2 nấc đầu fail thì vẫn phải ra số. Autouse fixture đã dọn _FX_ENDPOINTS
    # rỗng (hermetic) → test parser tự dựng lại ladder 3 nấc fake.
    monkeypatch.setattr(mac, "_FX_ENDPOINTS",
                        ("http://fake-1", "http://fake-2", "http://fake-3"))
    payloads = iter([OSError("nấc 1 chết"), OSError("nấc 2 chết"),
                     {"date": "2026-07-11", "usd": {"vnd": 26234.6}}])

    class _Resp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def _fake_get(url, timeout=None):
        p = next(payloads)
        if isinstance(p, Exception):
            raise p
        return _Resp(p)

    monkeypatch.setattr("requests.get", _fake_get)
    assert mac.fetch_usdvnd() == pytest.approx(26234.6)


def test_macro_body_lines_include_liquidity_gauge():
    import vnstock_brief as vb
    body = vb._macro_body_lines(_liq_rows(on=5.67, policy=4.5, y10=4.4))
    liq_lines = [l for l in body if "Chênh lệch thanh khoản" in l]
    assert len(liq_lines) == 1
    assert "+1.17 điểm %" in liq_lines[0] and "CĂNG" in liq_lines[0]
    assert "dốc 10Y − ON = -1.27 điểm %" in liq_lines[0]
    # thiếu input → không có dòng (no-op, không phát nhãn sai)
    body2 = vb._macro_body_lines(_liq_rows(on=5.67))
    assert not any("Chênh lệch thanh khoản" in l for l in body2)


# ─── -0.0 ở gauge (brief 23/09 in "10Y − lãi suất điều hành = -0.00 điểm %") ──

def test_gauges_never_emit_negative_zero():
    """round(-0.001, 2) là -0.0 → f"{:+.2f}" in "-0.00", đọc như ÂM trong khi
    nhánh nhãn đã coi là 0 ("mỏng"). Cả ba gauge + hai dốc phải ra +0.00."""
    import math
    import vnstock_macro as vm
    macro = [
        {"key": "govt_bond_yield_10y", "value": 4.499},
        {"key": "sbv_policy_rate",     "value": 4.50},
        {"key": "govt_bond_yield_2y",  "value": 4.5},
        {"key": "interbank_on",        "value": 4.501},
        {"key": "us10y",               "value": 4.5},
    ]
    keys = {m["key"] for m in macro}
    ts = vm.term_spread(macro)
    assert ts is not None
    assert math.copysign(1.0, ts["spread"]) == 1.0
    assert f"{ts['spread']:+.2f}" == "+0.00"
    if ts.get("slope_2_10") is not None:
        assert math.copysign(1.0, ts["slope_2_10"]) == 1.0
    liq = vm.liquidity_spread(macro)
    if liq is not None:                      # key ON có thể tên khác trong registry
        assert math.copysign(1.0, liq["spread"]) == 1.0
        if liq.get("slope_10y_on") is not None:
            assert math.copysign(1.0, liq["slope_10y_on"]) == 1.0
    intl = vm.intl_spread(macro)
    if intl is not None:
        assert math.copysign(1.0, intl["spread"]) == 1.0
    assert "govt_bond_yield_10y" in keys
