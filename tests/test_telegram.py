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


def test_send_message_truncates_long_text(monkeypatch):
    monkeypatch.setattr(tg, "_token",   lambda: "abc")
    monkeypatch.setattr(tg, "_chat_id", lambda: "12345")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status.return_value = None

    long_text = "x" * 5000
    with patch("requests.post", return_value=mock_resp) as mp:
        tg.send_message(long_text)

    sent = mp.call_args[1]["json"]["text"]
    # Should be truncated below 4096
    assert len(sent) < 4096
    assert "[tin bị rút gọn]" in sent


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
