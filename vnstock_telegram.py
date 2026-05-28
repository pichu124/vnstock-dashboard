"""vnstock_telegram.py — Telegram bot push for VNStock Dashboard.

Sends formatted daily briefs to a Telegram chat.

Setup (.env):
    TELEGRAM_BOT_TOKEN=<token from @BotFather>
    TELEGRAM_CHAT_ID=<your chat ID>

Usage:
    python run.py telegram test          # verify connection
    python run.py telegram morning       # push morning brief
    python run.py telegram close         # push close brief
    python run.py telegram screener      # push screener alerts only
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_MSG_LEN  = 4000  # Telegram hard limit is 4096; stay safe


# ── Credentials ──────────────────────────────────────────────────────────────

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=False)
    except Exception:
        pass


def _token() -> str:
    _load_env()
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_id() -> str:
    _load_env()
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


# ── Transport ─────────────────────────────────────────────────────────────────

def send_message(text: str, parse_mode: str = "HTML") -> dict:
    """Send text to the configured Telegram chat. Returns API response."""
    import requests

    token = _token()
    chat  = _chat_id()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set trong .env")
    if not chat:
        raise RuntimeError("TELEGRAM_CHAT_ID chưa set trong .env")

    # Truncate if needed (keep last chars so footer always shows)
    if len(text) > _MAX_MSG_LEN:
        text = text[:_MAX_MSG_LEN - 30] + "\n…\n<i>[tin bị rút gọn]</i>"

    url  = _TELEGRAM_API.format(token=token, method="sendMessage")
    resp = requests.post(url, json={
        "chat_id":                  chat,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Message blocks ────────────────────────────────────────────────────────────

def _vnindex_line() -> str:
    try:
        from vnstock_regime import _load_vnindex_tech
        t = _load_vnindex_tech()
        c = t.get("close")
        if c:
            rsi = t.get("rsi14")
            rsi_str = f" | RSI {rsi:.0f}" if rsi else ""
            return f"🌏 VNINDEX: <b>{c:,.1f}</b>{rsi_str}"
    except Exception:
        pass
    return "🌏 VNINDEX: —"


def _regime_block() -> str:
    try:
        from vnstock_regime import load_regime
        r     = load_regime()
        label = r.get("label", "—")
        score = r.get("score", 0)
        n     = r.get("n_signals", 0)
        conv  = int(r.get("confidence", 0) * 100)
        sigs  = r.get("signals", [])

        # Pick top 3 most extreme signals (bear first if bearish, bull first if bullish)
        sorted_sigs = sorted(sigs, key=lambda s: abs(s["direction"]), reverse=True)
        sig_parts   = []
        for s in sorted_sigs[:3]:
            icon = "🟢" if s["direction"] > 0 else "🔴" if s["direction"] < 0 else "⚪"
            sig_parts.append(f"{icon} {s['name']}: {s['value']}")

        lines = [
            f"⚖️ <b>Regime:</b> {label}  (score {score:+d}/{n}, conviction {conv}%)",
        ]
        if sig_parts:
            lines.append("   " + " | ".join(sig_parts))
        return "\n".join(lines)
    except Exception as e:
        return f"⚖️ Regime: lỗi ({e})"


def _brief_snippet(brief_type: str) -> str:
    """Return first meaningful paragraph (~350 chars) from the best agent brief."""
    try:
        from vnstock_brief import generate_brief
        results = generate_brief(brief_type=brief_type, force=True)
        for key, val in results.items():
            if key.startswith("_"):
                continue
            text, err = val
            if not text or err:
                continue
            # Strip markdown headers, get first 6 non-empty lines
            lines = [
                ln.lstrip("#").strip()
                for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("---")
            ]
            snippet = " ".join(lines[:6])
            return snippet[:380] + ("…" if len(snippet) > 380 else "")
        # Check timing sentinel
        if "_timing" in results:
            return results["_timing"][1] or "Brief chưa khả dụng."
        return "Chưa có brief (agent chưa chạy)."
    except Exception as e:
        return f"Brief không khả dụng: {e}"


def _open_recs_block() -> str:
    try:
        import vnstock_memory as _vm
        opens = _vm.open_recommendations()
        if not opens:
            return "📋 <b>Khuyến nghị đang mở:</b> không có"

        lines = [f"📋 <b>Khuyến nghị đang mở ({len(opens)} mã):</b>"]
        for r in opens[:5]:
            ticker = r.get("ticker", "?")
            action = r.get("action", "?").upper()
            entry  = float(r.get("entry_price") or 0)
            tp     = float(r.get("take_profit") or 0)
            sl     = float(r.get("cut_loss") or 0)
            horizon = int(r.get("horizon_days") or 5)
            tp_pct  = ((tp / entry) - 1) * 100 if entry else 0
            sl_pct  = ((sl / entry) - 1) * 100 if entry else 0
            try:
                age = (datetime.now() - datetime.fromisoformat(r["created_at"])).days
            except Exception:
                age = 0
            lines.append(
                f"  • <b>{ticker}</b> {action} @{entry:,.0f}"
                f" → TP {tp_pct:+.1f}% | SL {sl_pct:+.1f}%"
                f" | ngày {age}/{horizon}"
            )
        if len(opens) > 5:
            lines.append(f"  … và {len(opens)-5} mã khác")
        return "\n".join(lines)
    except Exception as e:
        return f"📋 Khuyến nghị: lỗi ({e})"


def _closed_today_block() -> str:
    try:
        import vnstock_memory as _vm
        closed = _vm.recent_closed_recommendations(limit=20)
        today  = datetime.now().date().isoformat()
        today_recs = [
            c for c in closed
            if (c.get("closed_at") or "")[:10] == today
            and c.get("hit_target") != "superseded"
        ]
        if not today_recs:
            return ""
        icon_map = {"tp": "✅", "sl": "🛑", "expire": "⏰"}
        lines = [f"📊 <b>Đóng hôm nay ({len(today_recs)} lệnh):</b>"]
        for c in today_recs:
            icon = icon_map.get(c.get("hit_target", ""), "•")
            pnl  = c.get("pnl_pct") or 0
            lines.append(
                f"  {icon} <b>{c.get('ticker','?')}</b>: {pnl:+.2f}%"
                f" ({c.get('hit_target','?')})"
            )
        return "\n".join(lines)
    except Exception:
        return ""


def _screener_block() -> str:
    """Top screener signals from the warehouse (no API call needed)."""
    try:
        import json
        p = _REPO / "data_warehouse" / "_meta" / "screener_signals.json"
        if not p.exists():
            return ""
        signals = json.loads(p.read_text(encoding="utf-8"))
        if not signals:
            return ""
        # signals is a list of {ticker, preset, score, ...} or similar
        if not isinstance(signals, list):
            return ""
        top = signals[:5]
        lines = [f"🔍 <b>Screener alerts ({len(signals)} tín hiệu):</b>"]
        for s in top:
            ticker = s.get("ticker") or s.get("symbol", "?")
            preset = s.get("preset", "?")
            score  = s.get("score")
            score_str = f" (score {score:.2f})" if score is not None else ""
            lines.append(f"  • <b>{ticker}</b> — {preset}{score_str}")
        if len(signals) > 5:
            lines.append(f"  … và {len(signals)-5} tín hiệu khác")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Public push functions ─────────────────────────────────────────────────────

def push_test() -> dict:
    """Send a simple test message to verify bot is configured correctly."""
    text = (
        "✅ <b>VNStock Telegram Bot — Kết nối OK!</b>\n"
        f"<i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>\n\n"
        "Bot đã sẵn sàng gửi brief hàng ngày."
    )
    return send_message(text)


def push_morning_brief() -> dict:
    """Build and send the morning brief message."""
    date_str   = datetime.now().strftime("%d/%m/%Y")
    screener   = _screener_block()

    blocks = [
        f"📊 <b>VNStock Morning Brief</b> — {date_str}\n",
        _vnindex_line(),
        _regime_block(),
        "",
        "🧠 <b>AI Brief:</b>",
        _brief_snippet("morning"),
        "",
        _open_recs_block(),
    ]
    if screener:
        blocks += ["", screener]
    blocks.append("\n<i>Powered by VNStock Dashboard</i>")

    text = "\n".join(b for b in blocks if b is not None)
    return send_message(text)


def push_close_brief() -> dict:
    """Build and send the afternoon/close brief message."""
    date_str    = datetime.now().strftime("%d/%m/%Y %H:%M")
    closed_blk  = _closed_today_block()

    blocks = [
        f"📉 <b>VNStock Close Brief</b> — {date_str}\n",
        _vnindex_line(),
        _regime_block(),
        "",
        "🧠 <b>AI Outlook:</b>",
        _brief_snippet("afternoon"),
        "",
        _open_recs_block(),
    ]
    if closed_blk:
        blocks += ["", closed_blk]
    blocks.append("\n<i>Powered by VNStock Dashboard</i>")

    text = "\n".join(b for b in blocks if b is not None)
    return send_message(text)


def push_screener_alerts() -> dict:
    """Push screener alerts only (no brief generation)."""
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    screener = _screener_block()
    if not screener:
        return send_message(
            f"🔍 <b>Screener</b> — {date_str}\n"
            "Không có tín hiệu mới hôm nay."
        )
    text = (
        f"🔍 <b>Screener Alerts</b> — {date_str}\n\n"
        f"{screener}\n\n"
        "<i>Powered by VNStock Dashboard</i>"
    )
    return send_message(text)
