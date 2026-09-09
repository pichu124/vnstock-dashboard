"""Guard CHỮ NGHĨA — vệ sinh văn bản trước khi brief tới tay user.

Một trong 3 nhóm tách từ `vnstock_brief_guards.py` (12/08, mục ④). Nhóm này lo
phần "brief lộ ruột hoặc nói nhảm": chữ Hán/Nhật lọt vào, rò chỉ thị prompt,
rò placeholder, rò biệt ngữ nội bộ (composite / Net BS), rò chỉ thị bias,
tuyên bố "kỷ lục" không có căn cứ, và lặp lại momentum.

Đặc trưng của nhóm: chỉ nhìn TEXT, gần như không cần `ctx` — nên đây là nhóm
rẻ nhất để chạy và cũng là nhóm chạy CUỐI chuỗi.

Guard trong file này KHÔNG tự chạy: phải được nối vào `apply_brief_guards`
(`vnstock_brief_guards`) mới sống — có lưới `tests/test_brief_split.py` canh.
"""
from __future__ import annotations

import re as _re

from vnstock_brief_guards_common import _is_section_start, _parse_vn_number


_CJK_RE = _re.compile(r"[㐀-䶿一-鿿豈-﫿]+")


def enforce_no_cjk(text: str, ctx: dict | None = None) -> str:
    """Deterministic language-hygiene guard: strip Chinese/Japanese/Korean Han
    characters that leak into the Vietnamese brief (observed: "đạt 达到 5,153
    tỷ") and normalize recurring sentiment-label typos ("Sổ hãi"/"Sờ hãi" →
    "Sợ hãi" — the label is ours, from the sentiment block, so the spelling is
    known). No-op when the text is clean.
    """
    if not text:
        return text
    out = text
    if _CJK_RE.search(out):
        out = _CJK_RE.sub("", out)
        out = _re.sub(r"[ \t]{2,}", " ", out)    # collapse gaps left by removal
        out = _re.sub(r"[ \t]+([,.;:%)])", r"\1", out)
    out = _re.sub(r"S[ổờòỏõóô] hãi", "Sợ hãi", out)
    return out if out != text else text


# Template-instruction fragments the model sometimes echoes verbatim into the
# brief (observed close 21:19: a trailing "Giới hạn 500 từ. Nếu thị trường flat
# …" line copied from the prompt's own length/format guidance).
_INSTR_LEAK_RE = _re.compile(
    r"^\s*(?:Giới hạn\s*\d+\s*từ"
    r"|YÊU CẦU VỀ ĐỘ CỤ THỂ"
    r"|\(Hướng dẫn\b"
    r"|Viết\s+(?:MORNING|AFTERNOON|CLOSE)\s+BRIEF"
    # Dòng chỉ thị "→ …" của data block vĩ mô/tin (leak thật close 14/07 —
    # model echo / guard cũ splice). Bắt theo TỪ KHÓA chỉ-thị đặc trưng
    # ("KHÔNG bịa", "DÙNG bối cảnh/các tin") — KHÔNG bắt "→" trơn vì dòng
    # nội dung hợp lệ cũng hay mở đầu bằng "→" (vd "→ Dòng tiền khối ngoại…").
    r"|→.*?(?:KHÔNG bịa|TUYỆT ĐỐI KHÔNG|DÙNG bối cảnh này|DÙNG các tin trên"
    r"|DÙNG ĐÚNG số))",
    _re.IGNORECASE,
)

# Ký hiệu RÀNG BUỘC nội bộ lọt vào GIỮA câu — khác `_INSTR_LEAK_RE` (chỉ soi
# dòng chỉ thị nguyên vẹn). Template ghi `BẮT BUỘC SL < entry < TP`, và model
# nhại lại ngay sau setup: "cắt lỗ 77,600 (entry < TP > SL)" (Mistral, brief
# chiều 13/08 — user phát hiện). Hai cái sai một lúc: lộ ký hiệu nội bộ CHO
# NGƯỜI ĐỌC, và nhại SAI luật (đúng phải là SL < entry < TP).
#
# Chỉ bắt cụm gồm TOÀN ký hiệu nội bộ (entry/TP/SL/giá) nối bằng dấu so sánh,
# nằm trong ngoặc. Không đụng câu tiếng Việt có chữ "entry" bình thường
# ("entry quanh 80,000") vì cụm đó không có dấu < > nối hai ký hiệu.
_CONSTRAINT_NOTATION_RE = _re.compile(
    r"\s*[（(]\s*(?:entry|tp|sl|giá|price)\s*[<>=≤≥]+"
    r"(?:\s*(?:entry|tp|sl|giá|price)\s*[<>=≤≥]*)+\s*[）)]",
    _re.IGNORECASE,
)


def enforce_no_constraint_notation(text: str, ctx: dict | None = None) -> str:
    """Xoá ký hiệu ràng buộc nội bộ kiểu "(entry < TP > SL)" khỏi brief.

    Đây là chữ dành cho MODEL, không phải cho người đọc — và khi model nhại
    lại nó còn nhại sai chiều, thành ra vừa lộ ruột vừa sai. Xoá cụm, giữ
    nguyên phần còn lại của dòng (setup vẫn đầy đủ entry/TP/SL bằng tiếng Việt).

    No-op khi sạch; idempotent.
    """
    if not text:
        return text
    return _CONSTRAINT_NOTATION_RE.sub("", text)


def enforce_no_instruction_leak(text: str, ctx: dict | None = None) -> str:
    """Deterministic guard: drop lines that echo the prompt's own instructions
    (length cap / format rules) instead of brief content. No-op when clean."""
    if not text:
        return text
    kept = [l for l in text.splitlines()
            if not _INSTR_LEAK_RE.match(l)
            and "nếu thị trường flat và không có signal" not in l.lower()]
    src = text.splitlines()
    if len(kept) == len(src):
        return text
    return "\n".join(kept)


# Template ghi độ dài mong muốn NGAY TRONG header — "## 🎯 TLDR (2 dòng)",
# "## 🔧 Đề xuất bổ sung (1 dòng, optional)" — và model chép nguyên header ra
# bản gửi Telegram (close 08/09/2026: cả hai lọt). "(2 dòng)"/"optional" là chữ
# cho MODEL, không phải cho người đọc. Chỉ đụng DÒNG HEADER (## / emoji mục),
# và chỉ cắt ngoặc ở CUỐI header chứa "N dòng/câu" hoặc "optional" — câu nội
# dung có ngoặc ("(2 dòng)" giữa câu) không phải header nên không bị đụng.
_HEADER_SCAFFOLD_RE = _re.compile(
    r"^(?P<head>.*?\S)\s*\((?:[\d\-–]+\s*(?:dòng|câu)\b[^)]*|[^)]*\boptional\b[^)]*)\)"
    r"(?P<tail>[\s:*]*)$",
    _re.IGNORECASE,
)


def enforce_no_header_scaffold(text: str, ctx: dict | None = None) -> str:
    """Xoá chú thích độ dài/optional mà template gắn vào header khỏi brief:
    "## 🎯 TLDR (2 dòng)" → "## 🎯 TLDR", "**📊 Tổng kết (2-3 câu):**" →
    "**📊 Tổng kết:**". Dòng in đậm chỉ được đụng khi ngoặc nằm TRONG phần
    đậm (đuôi còn "**") — nhãn đậm mở đầu một câu nội dung thì để yên.
    No-op khi sạch; idempotent."""
    if not text or "(" not in text:
        return text
    out, changed = [], False
    for ln in text.splitlines():
        is_hdr = _is_section_start(ln)
        is_bold = ln.lstrip().startswith("**")
        if is_hdr or is_bold:
            m = _HEADER_SCAFFOLD_RE.match(ln)
            if m and (is_hdr or "**" in m.group("tail")):
                ln, changed = m.group("head") + m.group("tail").rstrip(), True
        out.append(ln)
    return "\n".join(out) if changed else text


# The risk-section format example uses a "<tên mã>" placeholder the model
# sometimes echoes literally as "MÃ D/E=8.83 (HNG)" instead of substituting the
# ticker (observed 22:29). Rewrite "MÃ <metric>=<val> (TICKER)" → "TICKER
# <metric>=<val>" and drop any leftover bare "MÃ " before a metric.
_PLACEHOLDER_LEAK_RE = _re.compile(
    r"\bMÃ\s+(D/E|Op\.?CF)\s*=\s*([^()]+?)\s*\(([A-Z]{3,4})\)", _re.IGNORECASE)


def enforce_no_placeholder_leak(text: str, ctx: dict | None = None) -> str:
    """Deterministic guard: fix echoed "MÃ D/E=… (TICKER)" placeholder leaks in
    the risk section → "TICKER D/E=…". No-op when clean."""
    if not text or "MÃ " not in text:
        return text
    out = _PLACEHOLDER_LEAK_RE.sub(
        lambda m: f"{m.group(3)} {m.group(1)}={m.group(2).strip()}", text)
    # any residual bare "MÃ D/E=" with no ticker → drop the stray placeholder word
    out = _re.sub(r"\bMÃ\s+(D/E|Op\.?CF)\s*=", r"\1=", out, flags=_re.IGNORECASE)
    return out


_COMPOSITE_LEAK_RE = _re.compile(r"\s*[\(|]?\s*composite\s*=\s*(-?[\d.,]+)\s*\)?",
                                 _re.IGNORECASE)


def enforce_no_composite_jargon(text: str, ctx: dict | None = None) -> str:
    """Deterministic guard: turn the internal "composite=-0.76" score the model
    sometimes echoes into a plain-Vietnamese label ("tín hiệu phân phối mạnh").
    No-op when clean."""
    if not text or "composite" not in text.lower():
        return text

    def _lbl(m: "_re.Match") -> str:
        v = _parse_vn_number(m.group(1))
        if v is None:
            return ""
        name = ("phân phối mạnh" if v <= -0.6 else "phân phối" if v <= -0.2
                else "tích luỹ mạnh" if v >= 0.6 else "tích luỹ" if v >= 0.2
                else "trung tính")
        return f" (tín hiệu {name})"

    return _COMPOSITE_LEAK_RE.sub(_lbl, text)


def enforce_composite_rotation_hygiene(text: str, ctx: dict | None = None) -> str:
    """Keep the composite-rotation lines but fix two recurring problems (user
    chose 'giữ nhưng guard'):

    (a) Bucket↔label contradiction — a sector in the 'Phân phối' (distribution)
        line carrying a 'tích luỹ' (accumulation) composite label, or vice versa
        (observed 23:44: "Phân phối cảnh báo: CNTT & Phần mềm (tín hiệu tích luỹ
        mạnh)"). Drop the contradictory '(tín hiệu …)' label; the consistent one
        is kept.
    (b) 'Net BS' jargon (English Buy/Sell) — "Net BS +51.7% volume" / "Net BS
        +6M" → Vietnamese "mua/bán ròng ~X% KL" / "~X triệu CP" (sign → mua/bán).

    Idempotent; no-op when clean.
    """
    if not text:
        return text
    # (a) per-line bucket↔label contradiction
    out = []
    for ln in text.splitlines():
        head = (ln.split(":", 1)[0] if ":" in ln else ln).lower()
        if "phân phối" in head and "tích lu" not in head:
            ln = _re.sub(r"\s*\(\s*tín hiệu\s+tích\s+lu[ỹy][^)]*\)", "", ln)
        elif "tích lu" in head and "phân phối" not in head:
            ln = _re.sub(r"\s*\(\s*tín hiệu\s+phân\s+phối[^)]*\)", "", ln)
        out.append(ln)
    res = "\n".join(out)

    # (b) Net BS jargon → Vietnamese
    # Source semantics (vnstock_market_analyzer): "1M/3M" = lookback WINDOW (1
    # tháng / 3 tháng); the "M" SUFFIX on a SIGNED value ("Net BS +6.0M") = MILLION
    # cổ phiếu. Distinguish by sign: signed → million CP, unsigned → month.
    def _verb(s: str) -> str:
        v = _parse_vn_number(s)
        return "bán" if (v is not None and v < 0) else "mua"
    res = _re.sub(r"Net\s*BS\s*([+-]?\d[\d.,]*)\s*%\s*(?:volume|vol)\b",
                  lambda m: f"{_verb(m.group(1))} ròng ~{m.group(1).lstrip('+-')}% KL",
                  res, flags=_re.IGNORECASE)
    res = _re.sub(r"Net\s*BS\s*([+-]\d[\d.,]*)\s*M\b",     # SIGNED → million CP
                  lambda m: f"{_verb(m.group(1))} ròng ~{m.group(1).lstrip('+-')} triệu CP",
                  res, flags=_re.IGNORECASE)
    # unsigned "1M/3M/6M" = lookback window → "X tháng"; only on composite lines,
    # never after a sign/digit/dot (that's a value, handled above).
    out2 = []
    for ln in res.splitlines():
        if any(k in ln.lower() for k in ("tích lu", "phân phối", "smart money",
                                         "dòng tiền", "net bs", "luân chuyển")):
            ln = _re.sub(r"(?<![+\-\d.])(\d{1,2})\s*M\b", r"\1 tháng", ln)
        out2.append(ln)
    res = "\n".join(out2)
    # remaining bare "Net BS" / "volume" → Vietnamese (never appear legitimately).
    res = _re.sub(r"Net\s*BS", "NN ròng", res, flags=_re.IGNORECASE)
    res = _re.sub(r"\bvolume\b", "KL", res, flags=_re.IGNORECASE)
    return res


def enforce_no_bias_directive_leak(text: str, ctx: dict | None = None) -> str:
    """The bias-floor block injects 'Bias BẮT BUỘC = <dir>' as an INTERNAL
    directive and explicitly tells the model never to print 'bắt buộc'. The LLM
    still leaks it into the TLDR (observed 12:24 & 12:51: 'bias GIẢM bắt buộc').
    Strip the 'bắt buộc' qualifier wherever it sits next to a bias/stance
    directive (either order); drop a trailing '(bắt buộc)'. No-op when clean."""
    if not text or "buộc" not in text.lower():
        return text
    # "<bias|stance|GIẢM|TĂNG> [là] bắt buộc" → drop the qualifier. Cho phép
    # [*_] bọc markdown quanh hướng — close 14/07: "bias **GIẢM** bắt buộc"
    # trượt pattern cũ vì "**" chen giữa từ hướng và khoảng trắng.
    out = _re.sub(r"(\b(?:bias|stance|GIẢM|TĂNG|TANG)\b[*_]{0,2})\s+(?:là\s+)?bắt\s*buộc\b",
                  r"\1", text, flags=_re.IGNORECASE)
    # "bắt buộc [=] <GIẢM|TĂNG>" → drop the qualifier (keep the direction)
    out = _re.sub(r"\bbắt\s*buộc\s*(?:=\s*)?(?=[*_]{0,2}(?:GIẢM|TĂNG|TANG)\b)",
                  "", out, flags=_re.IGNORECASE)
    # leftover "(bắt buộc)" parenthetical
    out = _re.sub(r"\s*\(\s*bắt\s*buộc\s*\)", "", out, flags=_re.IGNORECASE)
    return out


def enforce_no_record_superlative(text: str, ctx: dict | None = None) -> str:
    """The brief carries only TB5/TB20 baselines — never a historical extreme —
    so 'GTGD thấp kỷ lục' / 'thanh khoản thấp nhất lịch sử' (observed 12:51) are
    unfounded all-time claims. On a GTGD/thanh-khoản/volume line, drop the
    record/all-time qualifier, keeping the plain 'thấp'/'cao'. No-op when clean."""
    if not text:
        return text
    out = []
    for ln in text.splitlines():
        low = ln.lower()
        if ("gtgd" in low or "thanh khoản" in low or "khối lượng" in low
                or "thanh khoản" in low):
            ln = _re.sub(r"\s*(?:kỷ|kỉ)\s*lục\b", "", ln, flags=_re.IGNORECASE)
            ln = _re.sub(r"\s+nhất\s+(?:trong\s+)?lịch\s+sử\b", "", ln,
                         flags=_re.IGNORECASE)
        out.append(ln)
    return "\n".join(out)


def enforce_no_duplicate_momentum(text: str, ctx: dict | None = None) -> str:
    """Within a line, the composite 'momentum {N}/100' should appear once.
    Observed 13:14: the close 'Tổng kết phiên' stated 'momentum -61/100' twice in
    adjacent sentences (once tacked onto the breadth clause, once with tâm lý).
    Drop the earlier duplicate(s) of an IDENTICAL value, keeping the last (the
    tâm-lý placement); leave differing values alone. No-op when nothing repeats.
    """
    if not text or text.lower().count("momentum") < 2:
        return text
    pat = _re.compile(r"\s*[,;]?\s*momentum\s*([-+]?\d+)\s*/\s*100", _re.IGNORECASE)
    out = []
    for ln in text.splitlines():
        ms = list(pat.finditer(ln))
        if len(ms) >= 2:
            last_val = ms[-1].group(1)
            for m in reversed([m for m in ms[:-1] if m.group(1) == last_val]):
                ln = ln[:m.start()] + ln[m.end():]
            # gỡ ngoặc RỖNG còn sót khi "(momentum -29/100)" là toàn bộ ruột
            # ngoặc (close 14/07: "tâm lý sợ hãi ()" lọt ra brief)
            ln = _re.sub(r"\s*\(\s*\)", "", ln)
        out.append(ln)
    return "\n".join(out)
