"""Tests for vnstock_telegram — message builders + transport guards."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

import vnstock_telegram as tg


# ─── Credentials guards ──────────────────────────────────────────────────────

def test_send_message_raises_without_token(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        tg.send_message("hello")


def test_send_message_raises_without_chat_id(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "")
    with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
        tg.send_message("hello")


# ─── Transport ───────────────────────────────────────────────────────────────

def test_sanitize_html_escapes_stray_chars_keeps_intended_tags():
    # Bug thật 14/07: brief phần 2/2 chứa < > & lạc → Telegram 400
    # "can't parse entities" và cả phần tin biến mất.
    out = tg._sanitize_html("<b>Tiêu đề</b> P/E <10 & RSI >70 <i>chú thích</i>")
    assert "<b>Tiêu đề</b>" in out and "<i>chú thích</i>" in out
    assert "&lt;10" in out and "&amp;" in out and "&gt;70" in out
    # tag lạ (không whitelist) bị escape thành text
    assert tg._sanitize_html("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"


def test_send_message_sanitizes_html_body(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {"ok": True}

    with patch("requests.post", return_value=mock_resp) as mp:
        tg.send_message("lãi suất <4% & M&A")
    sent = mp.call_args[1]["json"]["text"]
    assert sent == "lãi suất &lt;4% &amp; M&amp;A"


def test_send_message_400_falls_back_to_plain(monkeypatch):
    # Telegram từ chối HTML (entity lỗi ngoài dự kiến) → phần đó phải được
    # GỬI LẠI dạng plain (bỏ tag) thay vì raise và nuốt mất nội dung.
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    bad = MagicMock()
    bad.status_code = 400
    bad.ok = False
    bad.json.return_value = {"ok": False,
                             "description": "Bad Request: can't parse entities"}
    good = MagicMock()
    good.status_code = 200
    good.ok = True
    good.json.return_value = {"ok": True}

    with patch("requests.post", side_effect=[bad, good]) as mp:
        out = tg.send_message("<b>đậm</b> nội dung")
    assert out["ok"] is True and mp.call_count == 2
    retry_payload = mp.call_args_list[1][1]["json"]
    assert "parse_mode" not in retry_payload          # gửi plain
    assert retry_payload["text"] == "đậm nội dung"    # tag bị bỏ


def test_send_message_error_carries_api_description(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    bad = MagicMock()
    bad.status_code = 403
    bad.ok = False
    bad.json.return_value = {"ok": False, "description": "Forbidden: bot was blocked"}
    with patch("requests.post", return_value=bad):
        with pytest.raises(Exception, match="Forbidden: bot was blocked"):
            tg.send_message("hello")


def test_send_message_posts_to_api(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 7}}
    mock_resp.raise_for_status.return_value = None

    with patch("requests.post", return_value=mock_resp) as mp:
        out = tg.send_message("hello world")

    assert out["ok"] is True
    assert mp.called
    call_args = mp.call_args
    # URL contains the token + method
    assert "abc" in call_args[0][0]
    assert "sendMessage" in call_args[0][0]
    # Payload includes the message
    payload = call_args[1]["json"]
    assert payload["chat_id"] == "12345"
    assert payload["text"] == "hello world"
    assert payload["parse_mode"] == "HTML"


def test_send_message_splits_long_text_into_multiple_messages(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status.return_value = None

    # A long multi-line brief (> one Telegram message) must be SPLIT, not cut.
    long_text = "\n".join(f"Dòng tin số {i} về thị trường" for i in range(400))
    with patch("requests.post", return_value=mock_resp) as mp:
        tg.send_message(long_text)

    assert mp.call_count >= 2                       # sent as several messages
    for call in mp.call_args_list:
        assert len(call[1]["json"]["text"]) <= 4096  # each within Telegram's hard limit
    # nothing dropped: first and last source lines both appear across the chunks
    joined = "\n".join(c[1]["json"]["text"] for c in mp.call_args_list)
    assert "Dòng tin số 0 " in joined and "Dòng tin số 399 " in joined


def test_send_message_single_message_when_short(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status.return_value = None
    with patch("requests.post", return_value=mock_resp) as mp:
        tg.send_message("ngắn gọn")
    assert mp.call_count == 1
    assert mp.call_args[1]["json"]["text"] == "ngắn gọn"   # no (k/n) suffix


# ─── Message builders ────────────────────────────────────────────────────────

def test_vnindex_line_dash_when_no_data(monkeypatch):
    monkeypatch.setattr(
        "vnstock_regime._load_vnindex_tech", lambda: {}
    )
    out = tg._vnindex_line()
    assert "VNINDEX" in out
    assert "—" in out


def test_vnindex_line_shows_close_when_present(monkeypatch):
    monkeypatch.setattr(
        "vnstock_regime._load_vnindex_tech",
        lambda: {"close": 1275.5, "rsi14": 52.3},
    )
    out = tg._vnindex_line()
    assert "1,275" in out
    assert "RSI 52" in out


def test_regime_block_contains_label(monkeypatch):
    monkeypatch.setattr(
        "vnstock_regime.load_regime",
        lambda: {
            "label": "📉 Tiêu cực",
            "score": -1,
            "n_signals": 7,
            "confidence": 0.14,
            "signals": [
                {"name": "VNINDEX / MA20",   "value": "-1.3%", "direction": -1},
                {"name": "Breadth MA200",    "value": "19%",   "direction": -1},
                {"name": "VNINDEX / MA50",   "value": "+4.1%", "direction": 1},
            ],
        },
    )
    out = tg._regime_block()
    assert "Tiêu cực" in out
    assert "score -1/7" in out


def test_open_recs_block_handles_empty(monkeypatch):
    monkeypatch.setattr(
        "vnstock_memory.open_recommendations",
        lambda: [],
    )
    out = tg._open_recs_block()
    assert "không có" in out


def test_open_recs_block_formats_entries(monkeypatch):
    # Hermetic (bài học 15/08): rec giả không mang strategy_id → gate mục 10
    # rơi về kiểm định của chiến lược ACTIVE = đọc SQLite THẬT của máy chạy
    # test → máy có chiến lược trượt sẽ ẩn rec và test đỏ oan. Ý đồ test là
    # FORMAT, không phải gating — chốt thế giới: không có chiến lược active.
    monkeypatch.setattr("vnstock_memory.get_active_family",
                        lambda *a, **k: None)
    monkeypatch.setattr(
        "vnstock_memory.open_recommendations",
        lambda: [{
            "ticker": "VCB", "action": "buy",
            "entry_price": 90000, "take_profit": 95000, "cut_loss": 87000,
            "horizon_days": 5,
            "created_at": "2026-05-28T10:00:00",
        }],
    )
    out = tg._open_recs_block()
    assert "VCB" in out
    assert "BUY" in out
    assert "TP" in out
    assert "SL" in out


def test_fmt_price_keeps_precision_for_low_priced_instruments():
    # Blue-chips read fine at 0 decimals…
    assert tg._fmt_price(113.0) == "113"
    assert tg._fmt_price(25.0) == "25"
    # …but covered warrants / penny tickers must not collapse to @1 / @0.
    assert tg._fmt_price(1.23) == "1.23"
    assert tg._fmt_price(0.5) == "0.500"
    assert tg._fmt_price(0) == "0"


def test_open_recs_block_low_price_cw_not_rounded_to_zero(monkeypatch):
    monkeypatch.setattr("vnstock_memory.get_active_family",  # hermetic mục 10
                        lambda *a, **k: None)
    monkeypatch.setattr(
        "vnstock_memory.open_recommendations",
        lambda: [{
            "ticker": "CFPT2528", "action": "buy",
            "entry_price": 1.23, "take_profit": 1.48, "cut_loss": 1.09,
            "horizon_days": 5,
            "created_at": "2026-06-08T10:00:00",
        }],
    )
    out = tg._open_recs_block()
    assert "@1.23" in out
    assert "@1 " not in out and "@0 " not in out


def test_open_recs_block_flags_overdue(monkeypatch):
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=34)).isoformat()
    fresh = (datetime.now() - timedelta(days=2)).isoformat()
    monkeypatch.setattr("vnstock_memory.get_active_family",  # hermetic mục 10
                        lambda *a, **k: None)
    monkeypatch.setattr(
        "vnstock_memory.open_recommendations",
        lambda: [
            {"ticker": "CFPT2528", "action": "buy", "entry_price": 1.0,
             "take_profit": 1.2, "cut_loss": 0.9, "horizon_days": 5,
             "created_at": old},
            {"ticker": "ACB", "action": "buy", "entry_price": 25.0,
             "take_profit": 27.0, "cut_loss": 24.0, "horizon_days": 5,
             "created_at": fresh},
        ],
    )
    out = tg._open_recs_block()
    lines = out.splitlines()
    cw_line = next(l for l in lines if "CFPT2528" in l)
    acb_line = next(l for l in lines if "ACB" in l)
    # Overdue position (age 34 > horizon 5) is flagged; fresh one is not.
    assert "quá hạn" in cw_line
    assert "quá hạn" not in acb_line


# ─── Mục 10 (user chốt 15/08, phương án b): lệnh có chiến lược nguồn TRƯỢT ────
# kiểm định bị ẨN khỏi Telegram (dòng đếm trỏ về dashboard); unknown vẫn hiện.
# Stub Ở TẦNG SQLITE (get_active_family/latest_backtest) chứ không stub
# splitter — để chuỗi thật open_recs → split_recs_by_validation →
# _validation_of_strategy chạy đủ, hermetic trên mọi máy.

def _muc10_recs(action_a="buy", action_b="buy"):
    from datetime import datetime
    now = datetime.now().isoformat()
    return [
        {"ticker": "AAA", "action": action_a, "entry_price": 10.0,
         "take_profit": 11.0, "cut_loss": 9.5, "horizon_days": 5,
         "created_at": now, "strategy_id": 7},
        {"ticker": "BBB", "action": action_b, "entry_price": 20.0,
         "take_profit": 22.0, "cut_loss": 19.0, "horizon_days": 5,
         "created_at": now, "strategy_id": 8},
    ]


def _muc10_stub_db(monkeypatch, failed_sids, unknown_sids=()):
    import json
    bt_fail = {"metrics_json": json.dumps({
        "validation": {"passed": False, "p_value_adj": 0.764,
                       "reasons": ["p quá cao"]},
        "n_trades": 40}), "n_trades": 40}
    bt_pass = {"metrics_json": json.dumps({
        "validation": {"passed": True, "p_value_adj": 0.012, "reasons": []},
        "n_trades": 40}), "n_trades": 40}
    monkeypatch.setattr("vnstock_memory.get_active_family",
                        lambda *a, **k: None)
    monkeypatch.setattr(
        "vnstock_memory.latest_backtest",
        lambda sid: (None if sid in unknown_sids
                     else bt_fail if sid in failed_sids else bt_pass))


def test_open_recs_block_hides_failed_validation_with_summary(monkeypatch):
    monkeypatch.setattr("vnstock_memory.open_recommendations",
                        lambda: _muc10_recs())
    _muc10_stub_db(monkeypatch, failed_sids={7}, unknown_sids={8})
    monkeypatch.setattr(tg, "_market_is_bearish", lambda: False)
    out = tg._open_recs_block()
    assert "AAA" not in out                      # known-và-trượt → ẩn
    assert "BBB" in out                          # unknown: không đo được ≠ trượt
    assert "Khuyến nghị đang mở (1 mã)" in out   # đếm theo lệnh HIỆN
    assert "1 lệnh ẩn" in out and "dashboard" in out


def test_open_recs_block_all_hidden_keeps_header_and_count(monkeypatch):
    monkeypatch.setattr("vnstock_memory.open_recommendations",
                        lambda: _muc10_recs())
    _muc10_stub_db(monkeypatch, failed_sids={7, 8})
    out = tg._open_recs_block()
    assert out.startswith("📋")
    assert "AAA" not in out and "BBB" not in out
    assert "2 lệnh ẩn" in out and "dashboard" in out


def test_open_recs_block_passed_validation_untouched_no_hidden_note(monkeypatch):
    monkeypatch.setattr("vnstock_memory.open_recommendations",
                        lambda: _muc10_recs())
    _muc10_stub_db(monkeypatch, failed_sids=set())
    monkeypatch.setattr(tg, "_market_is_bearish", lambda: False)
    out = tg._open_recs_block()
    assert "AAA" in out and "BBB" in out
    assert "Khuyến nghị đang mở (2 mã)" in out
    assert "lệnh ẩn" not in out


def test_open_recs_block_buy_bear_caveat_considers_shown_only(monkeypatch):
    # Lệnh BUY bị ẨN không được kéo caveat "BUY dưới bối cảnh GIẢM" vào block
    # — caveat nói về thứ ĐANG in ra trước mặt user.
    from vnstock_brief import _BUY_BIAS_CAVEAT
    monkeypatch.setattr("vnstock_memory.open_recommendations",
                        lambda: _muc10_recs(action_a="buy", action_b="sell"))
    _muc10_stub_db(monkeypatch, failed_sids={7})     # AAA (BUY) ẩn, BBB (SELL) hiện
    monkeypatch.setattr(tg, "_market_is_bearish", lambda: True)
    out = tg._open_recs_block()
    assert _BUY_BIAS_CAVEAT not in out
    # đối chứng: BUY đang HIỆN + thị trường GIẢM → caveat phải có
    monkeypatch.setattr("vnstock_memory.open_recommendations",
                        lambda: _muc10_recs(action_a="sell", action_b="buy"))
    out2 = tg._open_recs_block()
    assert _BUY_BIAS_CAVEAT in out2


def test_open_recs_block_delegates_to_shared_splitter():
    # Net parity (gương của test_recommendation_block_delegates_to_shared_
    # splitter bên test_brief): hai kênh một luật, ai inline lại là đỏ.
    import inspect
    assert "split_recs_by_validation" in inspect.getsource(tg._open_recs_block)


def test_screener_block_empty_when_no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "_REPO", tmp_path)
    out = tg._screener_block()
    assert out == ""


# ─── Public push functions wrap send_message ─────────────────────────────────

def test_push_test_calls_send(monkeypatch):
    captured = {}
    def _stub(text, parse_mode="HTML"):
        captured["text"] = text
        return {"ok": True}
    monkeypatch.setattr(tg, "send_message", _stub)
    tg.push_test()
    assert "Kết nối OK" in captured["text"]


def test_push_briefs_build_snippet_before_header():
    """Close 30/07 01:21: header đọc composite sentiment TRƯỚC khi
    generate_brief (chạy trong _brief_snippet) refresh news/overview →
    header momentum -60 vs thân brief -51. Guard nếp inspect-source:
    snippet phải sinh TRƯỚC khi dựng dòng header ở CẢ 2 hàm push."""
    import inspect
    for fn in (tg.push_close_brief, tg.push_morning_brief):
        src = inspect.getsource(fn)
        assert src.index("_brief_snippet(") < src.index(
            "_market_sentiment_line("), fn.__name__


# ─── Engine ngoài (30/09): push_close_brief(ai_block=…) ──────────────────────

def _stub_close_blocks(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(tg, "_load_env", lambda: None)
    monkeypatch.setattr(tg, "_closed_today_block", lambda: "")
    monkeypatch.setattr(tg, "_brief_header", lambda e, t: "HDR")
    monkeypatch.setattr(tg, "_vnindex_line", lambda: "VNI")
    monkeypatch.setattr(tg, "_regime_block", lambda: "REG")
    monkeypatch.setattr(tg, "_market_sentiment_line", lambda: "SENT")
    monkeypatch.setattr(tg, "_open_recs_block", lambda: "RECS")
    monkeypatch.setattr(tg, "send_message",
                        lambda text, parse_mode="HTML": captured.update(text=text) or {"ok": True})
    return captured


def test_push_close_brief_ai_block_skips_ladder_and_labels_engine(monkeypatch):
    captured = _stub_close_blocks(monkeypatch)
    monkeypatch.setattr(tg, "_brief_snippet",
                        lambda bt: (_ for _ in ()).throw(AssertionError("ladder chạy dù có ai_block")))
    tg.push_close_brief(ai_block="## Tổng quan\nDòng 1\n---\nDòng 2\n",
                        engine="Claude Code · opus-5-5")
    text = captured["text"]
    assert "Tổng quan\nDòng 1\nDòng 2" in text      # dọn `#` và `---` như bản ladder
    assert "🤖 Claude Code · opus-5-5" in text        # footer nói engine nào viết
    assert text.index("HDR") < text.index("Tổng quan") < text.index("RECS")


def test_push_close_brief_without_ai_block_keeps_ladder_and_plain_footer(monkeypatch):
    captured = _stub_close_blocks(monkeypatch)
    monkeypatch.setattr(tg, "_brief_snippet", lambda bt: "LADDER")
    tg.push_close_brief()
    assert "LADDER" in captured["text"]
    assert "🤖" not in captured["text"]
    assert captured["text"].rstrip().endswith("<i>Powered by VNStock Dashboard</i>")


def test_snippet_from_text_is_the_single_cleaning_rule(monkeypatch):
    import vnstock_brief as vb
    raw = "# Tiêu đề\n---\n\nDòng x\n"
    monkeypatch.setattr(vb, "generate_brief", lambda **kw: {"A": (raw, None)})
    assert tg._brief_snippet("afternoon") == tg._snippet_from_text(raw) == "Tiêu đề\nDòng x"


def test_snippet_strips_fallback_prefix_and_converts_bold():
    raw = "_(fallback: gemini-3.5-flash-lite)_\n\n## TLDR\n**Stance:** TĂNG\n---\nx"
    assert tg._fallback_model_of(raw) == "gemini-3.5-flash-lite"
    assert tg._snippet_from_text(raw) == "TLDR\n<b>Stance:</b> TĂNG\nx"
    assert tg._fallback_model_of("## TLDR\nx") is None


def test_ladder_footer_names_the_agent_that_wrote(monkeypatch):
    import vnstock_brief as vb
    captured = _stub_close_blocks(monkeypatch)
    raw = "_(fallback: gemini-3.5-flash-lite)_\n\n## TLDR\nDòng"
    monkeypatch.setattr(vb, "generate_brief",
                        lambda **kw: {"Gemini 3.5 Flash": (raw, None)})
    tg.push_close_brief()
    text = captured["text"]
    assert "🤖 Gemini 3.5 Flash (fallback: gemini-3.5-flash-lite)" in text
    assert "_(fallback" not in text and "TLDR\nDòng" in text
    assert tg.LAST_BRIEF_AGENT == "Gemini 3.5 Flash (fallback: gemini-3.5-flash-lite)"
