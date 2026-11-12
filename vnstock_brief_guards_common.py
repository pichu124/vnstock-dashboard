"""Tiện ích chung của hệ guard brief — dùng bởi cả 3 nhóm guard.

Tách 12/08 (mục ④): `vnstock_brief_guards.py` 2.646 dòng chia theo CHỦ ĐỀ
(khối nội dung / con số / chữ nghĩa). File này giữ đúng phần cả ba nhóm đều
cần, để ba nhóm không phải import chéo nhau (import chéo = vòng chờ sẵn).

Đọc số kiểu VN/EN, cắt một mục của brief, nhận diện dòng tiêu đề — và (P1b-1,
#19) MỘT nguồn "thị trường phòng thủ": floor cũ từ 2 tín hiệu header
(`_bias_floor_dir`) + cách đọc nó từ ctx (`floor_dir`, `is_defensive`). Brief
(`_market_floor`, khối prompt), guard và Telegram quyết "phòng thủ" qua
`is_defensive`; chạy bóng 3 khung dùng chung luật `_bias_floor_dir` — P1b chỉ
cần đổi `is_defensive` ở một chỗ.
"""
from __future__ import annotations

import re as _re


def _parse_vn_number(s: str) -> float | None:
    """Convert '1.815,42' / '1,815.42' / '1815' to float. None on failure."""
    s = s.strip()
    if not s:
        return None
    # Vietnamese: dot=thousand sep, comma=decimal. EN: comma=thousand, dot=decimal.
    # Heuristic: if both, the LAST occurrence is the decimal sep.
    has_dot   = "." in s
    has_comma = "," in s
    try:
        if has_dot and has_comma:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif has_comma:
            s = s.replace(",", ".") if s.count(",") == 1 and len(s.split(",")[1]) <= 2 else s.replace(",", "")
        elif has_dot and len(s.split(".")[1]) >= 3:
            # "1.815" with 3-digit suffix → thousand sep
            s = s.replace(".", "")
        return float(s)
    except (ValueError, IndexError):
        return None


def _bias_floor_dir(momentum: int | None, regime_score: int | None) -> str | None:
    """Force a TLDR Bias direction when the headline signals are strongly
    one-sided and not in conflict.

    Inputs are the two signals shown in the brief header: Tâm lý `momentum`
    (-100..100) and Regime `score` (signed, out of ~7). Returns "GIẢM", "TĂNG",
    or None (let the agent decide). Thresholds: momentum ±50 or regime ±3.
    """
    bear = (momentum is not None and momentum <= -50) or \
           (regime_score is not None and regime_score <= -3)
    bull = (momentum is not None and momentum >= 50) or \
           (regime_score is not None and regime_score >= 3)
    if bear and not bull:
        return "GIẢM"
    if bull and not bear:
        return "TĂNG"
    return None


def floor_dir(ctx: dict | None) -> str | None:
    """Chiều floor cũ đã dựng vào ctx ("GIẢM" | "TĂNG" | None). Chịu được ctx
    None, thiếu khoá, hoặc `bias_floor: None` (cách đọc cũ ném AttributeError)."""
    return ((ctx or {}).get("bias_floor") or {}).get("dir")


def defensive_level(ctx: dict | None) -> str | None:
    """Mức lớp bảo vệ: "cứng" / "mềm" / None. Có ``ctx["defensive"]`` (brief 3
    khung, P1b-5) ⇒ đọc đúng nó; không có (công tắc tắt / state cũ) ⇒ floor cũ
    GIẢM = cứng như hôm nay (P1b-4 dời floor cũ sang ``bias_floor_old``)."""
    d = (ctx or {}).get("defensive")
    if isinstance(d, dict):
        return d.get("level") if d.get("on") else None
    old = ((ctx or {}).get("bias_floor_old") or {}).get("dir")
    return "cứng" if floor_dir(ctx) == "GIẢM" or old == "GIẢM" else None


def is_defensive(ctx: dict | None) -> bool:
    """Thị trường PHÒNG THỦ mức CỨNG — consumer làm đủ (viết lại "MUA vùng",
    caveat MUA ngược bias, cảnh báo Telegram…). Mức mềm chỉ nhắc, đọc qua
    ``defensive_level``. Tập cha của hôm nay: floor cũ GIẢM luôn là cứng."""
    return defensive_level(ctx) == "cứng"


_SECTION_EMOJIS = ("🎯", "📊", "📈", "🏆", "💰", "📋", "⚠️", "📅", "💡", "🔧", "⚡", "🔮", "🌐", "📰", "📌", "📚", "🧭",
                   "🪙", "🔭", "📑")


def _is_section_start(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("##") or s.startswith(_SECTION_EMOJIS)


def brief_section(text: str, marker: str) -> str:
    """Một mục của brief (header + body) theo `marker` trong dòng header —
    vd brief_section(output, "🌐") lấy mục Vĩ mô, "🎯" lấy TLDR. Dùng cho
    sub-tab Vĩ mô (dashboard) đọc lại brief đã lưu trong memory; "" khi
    không thấy. Cùng ranh giới mục với chuỗi guard (_is_section_start)."""
    if not text:
        return ""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if marker in l and _is_section_start(l)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))
    return "\n".join(lines[start:end]).strip()


# ── Mục "📈 Mức kỹ thuật" khi có thẻ kỹ thuật (PTKT P2c/P3) — dùng chung cho guard ở 3 nhóm ──
_TA_INSIGHT_RE = _re.compile(r"^\s*(?:[-*•]\s*)?\*{0,2}Nhận định\*{0,2}\s*[:：]\s*\*{0,2}\s*",
                             _re.IGNORECASE)
_TA_SENTENCE_SPLIT_RE = _re.compile(r"(?<=[.!?…])\s+")
_TA_TICKER_RE = _re.compile(r"\b[A-Z][A-Z0-9]{2}\b")


def ta_ctx(ctx: dict | None) -> dict | None:
    """Thẻ VN-Index của ctx khi guard chữ kỹ thuật phải chạy: brief sáng/chiều + có dòng thẻ.
    ctx không có ``ta_card`` (công tắc VNSTOCK_TA_CARD tắt, pack cũ) ⇒ None ⇒ guard no-op."""
    ta = (ctx or {}).get("ta_card")
    if not isinstance(ta, dict) or not ta.get("lines"):
        return None
    if ((ctx or {}).get("brief_type") or "afternoon") not in ("morning", "afternoon"):
        return None
    return ta


# Lõi chữ của tiêu đề mục 📈 — `vnstock_brief_canon.TA_SECTION_TITLES` bỏ "## 📈" và "(VNINDEX)"
# (common là lá, không import canon; test canh hai bên khớp) + bản trơn "Mức kỹ thuật".
_TA_TITLE_CORES = frozenset({"mức kỹ thuật", "mức kỹ thuật quan trọng", "mức kỹ thuật chốt phiên"})
_TA_TITLE_TAIL_RE = _re.compile(r"\s*\(?\s*vn-?index\s*\)?\s*$")


def is_ta_heading(line: str) -> bool:
    """Tiêu đề mục "📈 Mức kỹ thuật …" (cả bản model bỏ emoji / đuôi "(VNINDEX)" / in đậm) — CHỈ
    tiêu đề mục đó, không phải mọi tiêu đề có cụm "mức kỹ thuật" ("⚠️ Rủi ro: thủng mức kỹ
    thuật" là mục khác: gộp nhầm thì chữ của nó bị bỏ)."""
    if not _is_section_start(line):
        return False
    core = _re.sub(r"^[^\w]+", "", line.replace("*", "").strip().lower())
    return " ".join(_TA_TITLE_TAIL_RE.sub("", core).split()) in _TA_TITLE_CORES


def ta_split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _TA_SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]


def ta_card_for(sentence: str, ta: dict, cards: dict | None) -> dict:
    """Thẻ mà câu nói tới: mã có thẻ được nêu tên trong câu ⇒ thẻ mã đó; còn lại ⇒ VN-Index."""
    for tk in _TA_TICKER_RE.findall(sentence or ""):
        if isinstance((cards or {}).get(tk), dict):
            return cards[tk]
    return ta


# Chữ hoa 3 ký tự mà KHÔNG phải mã: tên chỉ báo.
_TA_NOT_TICKERS = frozenset({"RSI", "ATR", "SMA", "EMA", "ADX", "OBV", "CCI", "MFI", "ROC", "SAR"})
_TA_OTHER_INDEX_RE = _re.compile(
    r"\b(?:HNX|UPCOM|VN30|VN100|VNMID|VNSML|HNX30)\b|\b(?!vn[- ]?index\b)\w+[- ]index\b",
    _re.IGNORECASE)
_TA_VNINDEX_RE = _re.compile(r"\bvn[- ]?index\b", _re.IGNORECASE)
_TA_NEGATION_RE = _re.compile(r"\b(?:không|chưa|chẳng)\b", _re.IGNORECASE)


def ta_subject(sentence: str, ta: dict, cards: dict | None) -> dict | None:
    """Thẻ của ĐÚNG MỘT chủ thể câu nói tới — mã có thẻ, không nêu ai thì VN-Index. None khi
    không phán được: câu nêu ≥2 chủ thể (mã/VN-Index), hoặc nêu mã/chỉ số KHÔNG có thẻ (HPG
    ngoài ``ta_cards``, HNX-Index, UPCoM) — so chữ với thẻ VN-Index lúc đó là so nhầm người."""
    s = sentence or ""
    if _TA_OTHER_INDEX_RE.search(s):
        return None
    tickers = {t for t in _TA_TICKER_RE.findall(s) if t not in _TA_NOT_TICKERS}
    if any(not isinstance((cards or {}).get(t), dict) for t in tickers):
        return None
    if len(tickers) + bool(_TA_VNINDEX_RE.search(s)) > 1:
        return None
    return cards[next(iter(tickers))] if tickers else ta


_TA_CLAUSE_SEP_RE = _re.compile(r"\s*;\s*|,\s+|\s+nhưng\s+", _re.IGNORECASE)


def ta_drop_clauses(sentence: str, bad) -> str | None:
    """Bỏ MỆNH ĐỀ mà ``bad(mệnh đề)`` đúng — tách ở ";", ", " (dấu phẩy KÈM khoảng trắng: số
    1,748.80 không bị cắt), " nhưng ", không tách trong ngoặc. Không mệnh đề nào tự sai (cụm vắt
    qua ranh giới) hoặc bỏ hết ⇒ None (bỏ câu). Giữ dấu kết câu; câu gốc viết hoa đầu thì mệnh
    đề đầu còn lại cũng viết hoa."""
    body = sentence.rstrip(".!?… ")
    end = sentence[len(body):].strip() or "."
    clauses, seps, prev = [], [], 0
    for m in _TA_CLAUSE_SEP_RE.finditer(body):
        if body[:m.start()].count("(") > body[:m.start()].count(")"):
            continue
        clauses.append(body[prev:m.start()])
        seps.append(m.group(0))
        prev = m.end()
    clauses.append(body[prev:])
    real = [i for i, c in enumerate(clauses) if c.strip()]
    keep = [i for i in real if not bad(clauses[i])]
    if not keep or len(keep) == len(real):
        return None
    out = (clauses[keep[0]] + "".join(seps[i - 1] + clauses[i] for i in keep[1:])).strip()
    if sentence[:1].isupper():
        out = out[:1].upper() + out[1:]
    return out + end


def ta_rewrite_insight(text: str, ctx: dict, fn) -> str:
    """Áp ``fn(câu, thẻ của câu) -> câu | None`` lên từng câu của dòng "**Nhận định:**" trong mục
    📈 (None ⇒ bỏ câu; hết câu ⇒ bỏ dòng). No-op khi không có thẻ / mục / dòng nhận định."""
    ta = ta_ctx(ctx)
    if not text or not ta:
        return text
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if is_ta_heading(l)), None)
    if start is None:
        return text
    end = next((j for j in range(start + 1, len(lines)) if _is_section_start(lines[j])), len(lines))
    idx = next((i for i in range(start + 1, end) if _TA_INSIGHT_RE.match(lines[i])), None)
    if idx is None:
        return text
    m = _TA_INSIGHT_RE.match(lines[idx])
    sents = ta_split_sentences(lines[idx][m.end():])
    cards = ctx.get("ta_cards") or {}
    new = [s2 for s in sents if (s2 := fn(s, ta_card_for(s, ta, cards)))]
    if new == sents:
        return text
    if new:
        lines[idx] = f"{lines[idx][:m.end()].rstrip()} {' '.join(new)}"
    else:
        del lines[idx]
    return "\n".join(lines)


_PIVOT_LABEL_RE = _re.compile(r"\b(S1|S2|R1|R2)\s*=\s*([0-9][0-9.,]*[0-9]|[0-9])")


# ── Khung thời gian của một số NN ngành (dùng chung guard số NN + guard nhãn thiếu phiên) ─────────
_NN_MONTH_NAMES = r"mười|một|giêng|chạp|hai|ba|tư|năm|sáu|bảy|tám|chín"
# Khoảng thời gian KHÔNG có trong dữ liệu (NN 1T/1M): "tháng rưỡi", N≥2 tháng, quý ⇒ guard KHÔNG
# ghim số và không gắn nhãn khung tuần (ghim về số tuần hay tháng đều sai khung). Chỉ nhìn NGAY SAU số.
_NN_NUM_WORD = r"(?:\d+|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)"
_NN_SPAN_HEAD = (r"(?:hơn\s+)?(?:(?:" + _NN_NUM_WORD + r"\s+)?tháng\s+rưỡi\b"
                 r"|(?:[2-9]|1\d|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)\s+tháng\b")
# Sau dấu phẩy / không tiền tố: "quý III", "quý một" là mệnh đề khác (BCTC) — loại.
_NN_SPAN = _NN_SPAN_HEAD + r"|(?:(?:1|một)\s+)?quý\b(?!\s*(?:[IVX]+\b|một\b|hai\b|ba\b|bốn\b)))"
# Sau "trong" / "(": "trong quý III", "(9 tháng đầu năm)" là khoảng của CHÍNH số — giữ.
_NN_SPAN_TRONG = (_NN_SPAN_HEAD + r"|(?:(?:1|một)\s+)?quý\b"
                  r"(?:\s+(?:[IVX]+|một|hai|ba|bốn|\d)\b)?)")
# Theo sau là trước/sau/tới/cuối/đầu/số/tên tháng ⇒ MỆNH ĐỀ KHÁC ("2 tháng trước còn mua ròng", "quý tới").
_NN_SPAN_NOT = (r"(?!\s*(?::\s*)?[-+]?\s*\d|\s*(?:trước|sau|tới|cuối|đầu|thứ|qua\s+nữa|"
                + _NN_MONTH_NAMES + r")\b)")
# Sau "trong"/"(": xét CẢ cụm tới hết mệnh đề (dấu câu / đóng ngoặc) thay vì liệt kê đuôi hợp lệ —
# cụm là khoảng của CHÍNH số khi đi hết mà không gặp dấu hiệu MỆNH ĐỀ KHÁC: ":", một số "… tỷ" khác,
# mua/bán/ròng, dự kiến/dự báo, tới, "trước đó"/"sau đó". Không cần nhóm nguyên tử: vòng lặp không
# được đi QUA dấu hiệu, và phải dừng ĐÚNG ở dấu câu ⇒ regex lùi lại cũng không lách được.
_NN_CLAUSE_STOP = (r"(?!:|tỷ\b|ròng\b|mua\b|bán\b|dự\s+(?:kiến|báo)\b|tới\b"
                   r"|(?:trước|sau)\s*(?:đó\b|[.,;)]|$))")
_NN_OTHER_SPAN_RE = _re.compile(
    r"(?:\s*đồng)?\s*(?:\(\s*" + _NN_SPAN_TRONG + r"(?:" + _NN_CLAUSE_STOP + r"[^()\n])*\)"
    + r"|trong\s+" + _NN_SPAN_TRONG + r"(?!\s*(?:thứ|qua\s+nữa)\b)(?:" + _NN_CLAUSE_STOP
    + r"[^.,;:()\n])*(?=[.,;)\n]|$)"
    + r"|,\s*" + _NN_SPAN + r"(?:\s+(?:qua|gần\s+nhất))?\s*(?=[).;,]|$)"
    + r"|" + _NN_SPAN + _NN_SPAN_NOT + r")", _re.IGNORECASE | _re.MULTILINE)


def _nn_other_span(s: str, pos: int) -> bool:
    return bool(_NN_OTHER_SPAN_RE.match(s, pos))
