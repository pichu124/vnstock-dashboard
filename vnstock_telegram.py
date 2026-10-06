"""vnstock_telegram.py — Telegram bot push for VNStock Dashboard.

Sends formatted daily briefs to a Telegram chat.

Setup (.env):
    TELEGRAM_BOT_TOKEN=<token from @BotFather>
    TELEGRAM_CHAT_ID=<your chat ID>
    # (tuỳ) kênh "news" — cảnh báo tin mỗi giờ sang bot + group riêng (05/10).
    # Thiếu biến nào thì biến đó lấy mặc định ở trên.
    TELEGRAM_NEWS_BOT_TOKEN=<token bot thứ hai>
    TELEGRAM_NEWS_CHAT_ID=<id group tin, dạng -100…>

Usage:
    python run.py telegram test          # verify connection
    python run.py telegram morning       # push morning brief
    python run.py telegram close         # push close brief
    python run.py telegram screener      # push screener alerts only
    python run.py telegram chats [--channel news]   # in id các group bot đã vào
    python run.py telegram test --channel news      # thử bot/group tin mỗi giờ
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_MSG_LEN  = 4000  # Telegram hard limit is 4096; stay safe

# Tag CHỦ ĐÍCH mà các builder trong file này tự chèn — được giữ nguyên khi
# sanitize. Mọi < > & khác trong thân brief (model viết "<3", tin RSS "M&A",
# digest "P/E <10"…) phải escape, không thì Telegram trả 400
# "can't parse entities" và NUỐT nguyên phần tin đó (bug thật 14/07: close
# brief phần 2/2 không bao giờ tới nơi).
_ALLOWED_TAGS = ("b", "i", "u", "s", "code", "pre")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
# Link chủ đích (`allow_links=True`, chỉ builder tự dựng như cảnh báo tin):
# CHỈ http(s), không khoảng trắng/ngoặc kép — `javascript:` hay href lạ vẫn
# bị escape thành text. Áp SAU bước escape nên `&` trong URL đã là `&amp;`
# (đúng chuẩn thuộc tính HTML, Telegram tự giải).
_LINK_OPEN_RE = re.compile(r'&lt;a href="(https?://[^"\s<>]+)"&gt;')


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


# Kênh gửi (05/10, user: tin mỗi giờ sang bot + group riêng, phần còn lại giữ
# bot hiện tại). None = mặc định (brief, báo cáo, cảnh báo hệ thống).
CHANNELS = ("news",)


def channel_env(channel: str) -> "tuple[str, str]":
    """Tên biến (token, chat) của một kênh — vd TELEGRAM_NEWS_BOT_TOKEN."""
    up = channel.upper()
    return f"TELEGRAM_{up}_BOT_TOKEN", f"TELEGRAM_{up}_CHAT_ID"


def _creds(channel: "str | None" = None) -> "tuple[str, str]":
    """(token, chat) của kênh; biến riêng nào thiếu thì lấy mặc định ⇒ không
    đặt gì = y như trước khi có kênh."""
    tok, chat = _token(), _chat_id()
    if channel:
        tok_env, chat_env = channel_env(channel)
        tok = (os.environ.get(tok_env) or "").strip() or tok
        chat = (os.environ.get(chat_env) or "").strip() or chat
    return tok, chat


# ── Transport ─────────────────────────────────────────────────────────────────

def _split_for_telegram(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """Split text into chunks ≤ limit, breaking at LINE boundaries so HTML tags
    (always within a single line in our briefs) stay balanced across messages.
    A pathologically long single line is hard-split as a last resort."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:                     # single line longer than a message
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(line[:limit]); line = line[limit:]
        if not cur:
            cur = line
        elif len(cur) + 1 + len(line) <= limit:
            cur += "\n" + line
        else:
            chunks.append(cur); cur = line
    if cur:
        chunks.append(cur)
    return chunks


def _sanitize_html(text: str, allow_links: bool = False) -> str:
    """Escape < > & để parse_mode=HTML không chết 400, GIỮ tag chủ đích
    (<b>/<i>/…) mà builder tự chèn. Escape TRƯỚC rồi un-escape whitelist —
    idempotent với tag hợp lệ, mọi ký tự lạc còn lại đều an toàn.
    `allow_links` giữ thêm `<a href="http(s)://…">…</a>` (mặc định TẮT: brief
    do LLM viết không được tự chèn link)."""
    out = (text.replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;"))
    for t in _ALLOWED_TAGS:
        out = out.replace(f"&lt;{t}&gt;", f"<{t}>")
        out = out.replace(f"&lt;/{t}&gt;", f"</{t}>")
    if allow_links:
        out = _LINK_OPEN_RE.sub(r'<a href="\1">', out).replace("&lt;/a&gt;", "</a>")
    return out


def _tg_error_detail(resp) -> str:
    """Mô tả lỗi thật từ body API (400 của Telegram luôn kèm 'description'
    chỉ rõ ký tự/byte lỗi — raise_for_status cũ vứt mất nên không soi được)."""
    try:
        body = resp.json()
        desc = str(body.get("description") or resp.text[:200])
        new_id = (body.get("parameters") or {}).get("migrate_to_chat_id")
        if new_id:
            # Group thường bị Telegram nâng lên supergroup (bật quyền admin,
            # đổi lịch sử…) ⇒ id ĐỔI, id cũ trả 400 mãi.
            desc += f" — group đã thành supergroup, đổi CHAT_ID trong .env thành {new_id}"
        return desc
    except Exception:
        try:
            return str(resp.text[:200])
        except Exception:
            return ""


def _migrated_to(resp) -> "int | str | None":
    """id supergroup mới khi Telegram báo group cũ đã bị nâng cấp (400 kèm
    `parameters.migrate_to_chat_id`), không thì None."""
    try:
        return (resp.json().get("parameters") or {}).get("migrate_to_chat_id") or None
    except Exception:
        return None


def _chat_var(channel: "str | None") -> str:
    """Biến .env đang cấp chat id cho kênh (kênh thiếu biến riêng ⇒ mặc định)."""
    if channel and (os.environ.get(channel_env(channel)[1]) or "").strip():
        return channel_env(channel)[1]
    return "TELEGRAM_CHAT_ID"


def send_message(text: str, parse_mode: str = "HTML", allow_links: bool = False,
                 channel: "str | None" = None) -> dict:
    """Send text to the configured Telegram chat. Long briefs are split into
    multiple messages (Telegram caps at 4096 chars) so nothing is dropped —
    previously the tail (📰 tin tức) was truncated. Returns the LAST API response.

    HTML mode: body được `_sanitize_html` trước khi gửi; nếu Telegram VẪN trả
    400 (entity lỗi ngoài dự kiến) → gửi lại phần đó dạng PLAIN (bỏ tag) để
    nội dung luôn tới nơi, đồng thời in description thật của API để soi.
    `allow_links=True` giữ `<a href="http(s)://…">` (xem `_sanitize_html`).
    `channel="news"` gửi bằng bot/chat của kênh đó (xem `_creds`).
    """
    import requests

    token, chat = _creds(channel)
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set trong .env")
    if not chat:
        raise RuntimeError("TELEGRAM_CHAT_ID chưa set trong .env")

    url = _TELEGRAM_API.format(token=token, method="sendMessage")
    if parse_mode == "HTML":
        text = _sanitize_html(text, allow_links=allow_links)
    parts = _split_for_telegram(text, _MAX_MSG_LEN)
    n     = len(parts)
    resp_json: dict = {}
    for i, part in enumerate(parts):
        body = part if n == 1 else f"{part}\n<i>({i + 1}/{n})</i>"
        payload = {"chat_id": chat, "text": body, "parse_mode": parse_mode,
                   "disable_web_page_preview": True}
        resp = requests.post(url, json=payload, timeout=15)
        new_id = _migrated_to(resp) if getattr(resp, "status_code", None) == 400 else None
        if new_id:
            # Group bị Telegram NÂNG lên supergroup (đổi quyền thành viên, cho
            # bot làm admin, đổi lịch sử…) ⇒ id ĐỔI, id cũ trả 400 mãi. Đi theo
            # id mới ngay để brief/tin không mất, và réo sửa .env (05/10: user
            # đổi quyền cả 2 group ⇒ cả 2 bot câm).
            print(f"[telegram] ⚠️ group đã thành supergroup — gửi tới id mới {new_id}. "
                  f"Sửa .env: {_chat_var(channel)}={new_id}")
            chat = new_id
            resp = requests.post(url, json={**payload, "chat_id": chat}, timeout=15)
        if getattr(resp, "status_code", None) == 400 and parse_mode:
            detail = _tg_error_detail(resp)
            print(f"[telegram] ⚠️ HTML bị từ chối ở phần {i + 1}/{n} "
                  f"({detail}) — gửi lại dạng plain")
            resp = requests.post(url, json={
                "chat_id":                  chat,
                "text":                     _TAG_RE.sub("", body),
                "disable_web_page_preview": True,
            }, timeout=15)
        if getattr(resp, "status_code", None) is not None and not resp.ok:
            detail = _tg_error_detail(resp)
            raise requests.HTTPError(
                f"{resp.status_code} Telegram: {detail}", response=resp)
        resp.raise_for_status()
        resp_json = resp.json()
    return resp_json


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


def _market_sentiment_line() -> str | None:
    """One-line composite market mood for the brief header. None if no data."""
    try:
        from vnstock_market_sentiment import load_market_sentiment
        ms = load_market_sentiment()
        if ms:
            return (f"🧭 <b>Tâm lý:</b> {ms['mood']} "
                    f"(momentum {ms['momentum']:+d}/100, {ms['n_signals']} tín hiệu)")
    except Exception:
        pass
    return None


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


# Agent/model đã viết bản brief vừa chọn ở `_brief_snippet` (ladder) — footer
# Telegram in `🤖 <agent>` cho MỌI bản, không chỉ bản Claude (giám khảo 30/09:
# người đọc phải biết ai viết, kể cả đêm rơi về ladder).
LAST_BRIEF_AGENT: "str | None" = None
_FALLBACK_PREFIX_RE = re.compile(r"^_\(fallback:\s*([^)]+)\)_$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _fallback_model_of(text: str) -> "str | None":
    """Model dự phòng nếu agent OpenAI-compat gắn dòng đầu `_(fallback: m)_`."""
    for ln in (text or "").splitlines():
        if ln.strip():
            m = _FALLBACK_PREFIX_RE.match(ln.strip())
            return m.group(1).strip() if m else None
    return None


def _snippet_from_text(text: str) -> str:
    """Thân brief → khối Telegram: bỏ dấu `#` tiêu đề markdown, dòng `---` và
    dòng `_(fallback: …)_` (chuyển sang footer), `**đậm**` → `<b>đậm</b>`
    (qua được whitelist `_sanitize_html`; theo từng dòng nên
    `_split_for_telegram` không cắt giữa tag). Dùng CHUNG cho bản ladder
    (`_brief_snippet`) và bản engine ngoài (`push_close_brief(ai_block=…)`,
    30/09) — một luật dọn."""
    out: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("---") or _FALLBACK_PREFIX_RE.match(s):
            continue
        s = ln.lstrip("#").strip()
        out.append(_BOLD_RE.sub(r"<b>\1</b>", s))
    return "\n".join(out)


def _brief_snippet(brief_type: str) -> str:
    """Return first meaningful paragraph (~350 chars) from the best agent brief."""
    global LAST_BRIEF_AGENT
    LAST_BRIEF_AGENT = None
    try:
        from vnstock_brief import generate_brief
        results = generate_brief(brief_type=brief_type, force=True)
        for key, val in results.items():
            if key.startswith("_"):
                continue
            text, err = val
            if not text or err:
                continue
            fb = _fallback_model_of(text)
            LAST_BRIEF_AGENT = f"{key} (fallback: {fb})" if fb else key
            return _snippet_from_text(text)
        # Check sentinel keys (timing / no-agent / no-available)
        for _sentinel in ("_timing", "_no_agent", "_no_available"):
            if _sentinel in results:
                return results[_sentinel][1] or "Brief chưa khả dụng."
        return "Chưa có brief (agent chưa chạy)."
    except Exception as e:
        return f"Brief không khả dụng: {e}"


def _fmt_price(p: float) -> str:
    """Format an entry/exit price (vnstock unit = thousand VND).

    Blue-chips trade in the tens/hundreds so 0 decimals reads fine, but covered
    warrants / penny tickers trade in hundreds of VND (≈ 0.1–2.0 in this unit),
    where `.0f` collapses them to a meaningless "@1" / "@0". Use adaptive
    precision so low-priced instruments keep their significant digits.
    """
    a = abs(p)
    if a == 0:
        return "0"
    if a < 1:
        return f"{p:,.3f}"
    if a < 10:
        return f"{p:,.2f}"
    return f"{p:,.0f}"


def _open_recs_block() -> str:
    """Lệnh đang mở cho push Telegram.

    Mục 10 (user chốt 15/08, phương án b): lệnh có chiến lược nguồn TRƯỢT
    kiểm định chống-ăn-may bị ẨN khỏi Telegram — cùng luật
    `split_recs_by_validation` với brief (ẩn ⇔ known-và-trượt; không đo được
    vẫn hiện) — chỉ còn dòng đếm trỏ về dashboard. Sổ lệnh trên dashboard
    vẫn đầy đủ để đối soát; kênh đóng là kênh ĐẨY tới user, không phải sổ.
    """
    try:
        import vnstock_memory as _vm
        opens = _vm.open_recommendations()
        if not opens:
            return "📋 <b>Khuyến nghị đang mở:</b> không có"

        from vnstock_brief import split_recs_by_validation
        shown, _hidden_vals = split_recs_by_validation(opens)
        n_hidden = len(opens) - len(shown)
        hidden_note = (
            f"  · {n_hidden} lệnh ẩn — chiến lược nguồn chưa đạt kiểm định "
            f"(xem đầy đủ trong dashboard)"
        ) if n_hidden else None
        if not shown:
            return "📋 <b>Khuyến nghị đang mở:</b>\n" + hidden_note

        lines = [f"📋 <b>Khuyến nghị đang mở ({len(shown)} mã):</b>"]
        for r in shown:
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
            # horizon đếm PHIÊN, age đếm NGÀY LỊCH — so thẳng là dán nhãn
            # "quá hạn" sớm ~30% (vết 19/08).
            from vnstock_brief import _horizon_calendar_days
            overdue = " ⚠️ quá hạn" if age > _horizon_calendar_days(horizon) else ""
            lines.append(
                f"  • <b>{ticker}</b> {action} @{_fmt_price(entry)}"
                f" → TP {tp_pct:+.1f}% | SL {sl_pct:+.1f}%"
                f" | ngày {age}/{horizon}{overdue}"
            )
        if hidden_note:
            lines.append(hidden_note)
        # Cảnh báo BUY dưới bối cảnh GIẢM (mirror guard #27 enforce_buy_vs_bias
        # _caveat, NHƯNG lệnh mở được append Ở ĐÂY — telegram-side, NGOÀI
        # apply_brief_guards — nên guard body không với tới; đặt caveat đúng
        # chỗ lệnh hiện. Gắn cảnh báo, KHÔNG lọc (lệnh có SL = rủi ro xác định).
        # Chỉ xét lệnh ĐANG HIỆN — lệnh ẩn không in ra thì không cần caveat.
        if _has_buy_under_bear(shown):
            from vnstock_brief import _BUY_BIAS_CAVEAT
            lines.append(_BUY_BIAS_CAVEAT)
        return "\n".join(lines)
    except Exception as e:
        return f"📋 Khuyến nghị: lỗi ({e})"


def _market_is_bearish() -> bool:
    """Bối cảnh GIẢM theo đúng luật bias floor (_bias_floor_dir): regime score
    ≤ -3 HOẶC momentum tâm lý ≤ -50. Best-effort — thiếu tín hiệu → False."""
    momentum = regime_score = None
    try:
        from vnstock_market_sentiment import load_market_sentiment
        ms = load_market_sentiment()
        if ms and ms.get("momentum") is not None:
            momentum = int(ms["momentum"])
    except Exception:
        pass
    try:
        from vnstock_regime import load_regime
        r = load_regime()
        if r and r.get("score") is not None:
            regime_score = int(r["score"])
    except Exception:
        pass
    try:
        from vnstock_brief import _bias_floor_dir
        return _bias_floor_dir(momentum, regime_score) == "GIẢM"
    except Exception:
        return False


def _has_buy_under_bear(opens: list) -> bool:
    """≥1 lệnh mở action=BUY VÀ thị trường đang GIẢM."""
    has_buy = any(str(r.get("action", "")).upper() == "BUY" for r in opens)
    return bool(has_buy and _market_is_bearish())


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
        icon_map = {"tp": "✅", "sl": "🛑", "expire": "⏰", "corp_action": "⏸"}
        lines = [f"📊 <b>Đóng hôm nay ({len(today_recs)} lệnh):</b>"]
        for c in today_recs:
            icon = icon_map.get(c.get("hit_target", ""), "•")
            pnl  = c.get("pnl_pct")
            # Đóng KHÔNG GIÁ (corp_action/stale) in "+0.00%" là nói dối: lệnh
            # không hoà vốn, nó không được chấm.
            res  = f"{pnl:+.2f}%" if pnl is not None else "không chấm"
            lines.append(
                f"  {icon} <b>{c.get('ticker','?')}</b>: {res}"
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

def push_test(channel: "str | None" = None) -> dict:
    """Send a simple test message to verify bot is configured correctly."""
    what = ("cảnh báo tin mỗi giờ" if channel == "news"
            else "brief hàng ngày + báo cáo")
    text = (
        "✅ <b>VNStock Telegram Bot — Kết nối OK!</b>\n"
        f"<i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>\n\n"
        f"Bot đã sẵn sàng gửi {what}."
    )
    return send_message(text, channel=channel)


def _lookup_token(channel: "str | None") -> str:
    """Token cho lệnh DÒ (chats/whoami) — KHÔNG lùi về bot mặc định như khi gửi:
    05/10 dòng TELEGRAM_NEWS_BOT_TOKEN bị `#` ⇒ `chats --channel news` lặng lẽ
    dùng bot brief, in group Brief, user lẫn Claude đọc thành "bot tin nằm
    nhầm group"."""
    if not channel:
        tok = _token()
        if not tok:
            raise RuntimeError("TELEGRAM_BOT_TOKEN chưa set trong .env")
        return tok
    _load_env()
    env = channel_env(channel)[0]
    tok = (os.environ.get(env) or "").strip()
    if not tok:
        raise RuntimeError(f"{env} chưa có trong .env (hoặc dòng đang bị # tắt) — "
                           "lệnh dò này KHÔNG dùng bot mặc định")
    return tok


def bot_identity(channel: "str | None" = None) -> str:
    """"@username (tên hiển thị)" của bot mà token kênh trỏ tới (getMe) — để
    đối chiếu token ↔ bot mà không phải in token."""
    import requests

    resp = requests.get(_TELEGRAM_API.format(token=_lookup_token(channel),
                                             method="getMe"), timeout=15)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} Telegram: {_tg_error_detail(resp)}",
                                 response=resp)
    me = resp.json().get("result") or {}
    return f"@{me.get('username', '?')} ({me.get('first_name', '')})"


def find_chats(channel: "str | None" = None) -> list[dict]:
    """Các chat bot (của kênh) đã thấy trong 24h qua — để lấy id group mà
    KHÔNG phải dán token vào trình duyệt. Bot vừa được thêm vào group sinh
    update `my_chat_member` nên thấy ngay. Chỉ ĐỌC (không xoá hàng đợi)."""
    import requests

    token = _lookup_token(channel)
    resp = requests.get(_TELEGRAM_API.format(token=token, method="getUpdates"),
                        timeout=15)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} Telegram: {_tg_error_detail(resp)}",
                                 response=resp)
    seen: dict = {}
    for upd in resp.json().get("result") or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member",
                    "chat_member"):
            chat = (upd.get(key) or {}).get("chat")
            if chat and "id" in chat:
                name = (chat.get("title") or chat.get("username")
                        or chat.get("first_name") or "")
                seen[chat["id"]] = {"id": chat["id"], "type": chat.get("type", "?"),
                                    "name": name}
    return list(seen.values())


def _iso_to_dmy(iso_str: str) -> str:
    """'2026-06-05' → '05/06/2026'. Returns input unchanged on parse failure."""
    try:
        y, m, d = iso_str[:10].split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return iso_str


def _brief_header(emoji: str, title: str) -> str:
    """Build a header that states the trading session the brief describes plus
    the push timestamp. When the session date differs from today (brief pushed
    on a weekend / before market open) both are shown with a clear marker so
    the reader knows the data is from the latest session, not today."""
    now = datetime.now()
    push_str = now.strftime("%d/%m/%Y %H:%M")
    session_dmy = push_str.split()[0]  # default to today's date
    try:
        from vnstock_brief import effective_trading_date
        session_iso = effective_trading_date()
        session_dmy = _iso_to_dmy(session_iso)
    except Exception:
        session_iso = ""

    head = f"{emoji} <b>{title}</b> — Phiên GD {session_dmy}\n🕐 Gửi lúc: {push_str}"
    # Flag stale data: session date is before today (weekend / pre-open push)
    if session_iso and session_iso < now.strftime("%Y-%m-%d"):
        head += "  ⚠️ <i>data phiên gần nhất</i>"
    else:
        # VNINDEX is current but breadth/movers/regime may trail a session.
        try:
            from vnstock_brief import market_data_freshness
            fr = market_data_freshness(session_iso or None)
            if fr.get("stale"):
                head += (f"  ⚠️ <i>độ rộng/regime: phiên "
                         f"{_iso_to_dmy(fr['overview_date'])}</i>")
        except Exception:
            pass
    return head + "\n"


def push_morning_brief() -> dict:
    """Build and send the morning brief message."""
    # Load .env before _brief_snippet() checks agent availability (see
    # push_close_brief for the full ordering rationale).
    _load_env()
    screener   = _screener_block()

    # Snippet trước, header sau — cùng lý do race close 30/07 01:21 (xem
    # push_close_brief): generate_brief refresh dữ liệu, header phải đọc SAU.
    ai_blk = _brief_snippet("morning")

    blocks = [
        _brief_header("📊", "VNStock Morning Brief"),
        _vnindex_line(),
        _regime_block(),
        _market_sentiment_line(),
        "",
        "🧠 <b>AI Brief:</b>",
        ai_blk,
        "",
        _open_recs_block(),
    ]
    if screener:
        blocks += ["", screener]
    blocks.append("\n<i>Powered by VNStock Dashboard</i>")

    text = "\n".join(b for b in blocks if b is not None)
    return send_message(text)


def push_close_brief(ai_block: "str | None" = None,
                     engine: "str | None" = None) -> dict:
    """Build and send the afternoon/close brief message.

    `ai_block` (30/09): thân brief ĐÃ SINH SẴN bởi engine ngoài (Claude Code
    qua `vnstock_brief_pack`) — đã qua guard/memory ở chỗ gọi; hàm này chỉ
    dọn markdown và dựng khung Telegram y như bản ladder. None = đường cũ:
    `_brief_snippet` chạy ladder agent. `engine` = nhãn in ở footer để người
    đọc biết bản này do engine nào viết."""
    # Load .env up front so agent API keys are in os.environ before
    # _brief_snippet() checks agent availability (it runs before
    # send_message(), which is otherwise the first thing to load .env).
    global LAST_BRIEF_AGENT
    _load_env()
    closed_blk  = _closed_today_block()

    # Sinh AI brief TRƯỚC khi dựng header (close 30/07 01:21 lộ race: list
    # blocks cũ gọi _market_sentiment_line() TRƯỚC _brief_snippet(), mà
    # generate_brief bên trong snippet mới là bước refresh news/overview →
    # header in composite CŨ (-60) còn thân brief ghim theo ctx MỚI (-51).
    # Header dựng SAU snippet = cùng nền cache; vnindex/regime hưởng ké).
    LAST_BRIEF_AGENT = None
    ai_blk = (_snippet_from_text(ai_block) if ai_block
              else _brief_snippet("afternoon"))
    if not ai_block and not engine:
        engine = LAST_BRIEF_AGENT          # footer nói agent ladder nào viết

    blocks = [
        _brief_header("📉", "VNStock Close Brief"),
        _vnindex_line(),
        _regime_block(),
        _market_sentiment_line(),
        "",
        "🧠 <b>AI Outlook:</b>",
        ai_blk,
        "",
        _open_recs_block(),
    ]
    if closed_blk:
        blocks += ["", closed_blk]
    blocks.append(_powered_by(engine))

    text = "\n".join(b for b in blocks if b is not None)
    return send_message(text)


def _powered_by(engine: "str | None" = None) -> str:
    """Footer Telegram; kèm tên engine khi thân brief do engine ngoài viết."""
    tail = f" · 🤖 {engine}" if engine else ""
    return f"\n<i>Powered by VNStock Dashboard{tail}</i>"


def push_rates_weekly() -> dict:
    """Đẩy tóm tắt tuần lãi suất & tiền tệ lên Telegram (hướng B khảo sát
    baocaolaisuatvatiente). Text gọn từ `vnstock_rates_report.render_telegram`
    — zero fetch, đọc cache sẵn có. Cadence tuần (gọi tay / nút dashboard /
    lịch riêng — KHÔNG vào brief 2×/ngày)."""
    _load_env()
    try:
        from vnstock_rates_report import build_report_data, render_telegram
        data = build_report_data()
    except Exception as e:                                    # noqa
        return {"ok": False, "error": f"build report lỗi: {e}"}
    if not data.get("rates") and not data.get("curve"):
        return {"ok": False, "error": "cache vĩ mô/HNX rỗng — chạy run.py macro"}
    text = render_telegram(data) + "\n\n<i>Powered by VNStock Dashboard</i>"
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
