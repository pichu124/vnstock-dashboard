"""Hệ guard hậu kiểm brief — 44 guard + chuỗi `apply_brief_guards` dùng chung.

Tách khỏi `vnstock_brief.py` (12/08, mục ④ audit 06/08): 2.548 dòng validator
+ chuỗi guard là cụm lớn nhất và tự chứa nhất của file 6.8K dòng.

⚠️ BẤT BIẾN (CLAUDE.md): `apply_brief_guards(text, ctx)` là **điểm parity duy
nhất** — brief sáng và brief chiều đi qua ĐÚNG một chuỗi này. KHÔNG BAO GIỜ
inline lại chuỗi vào `generate_brief`. Thêm guard = thêm vào chuỗi + viết test.

Vì sao guard tồn tại: LLM hay phớt chỉ thị prompt, nên mọi ràng buộc quan
trọng phải chốt bằng code deterministic hậu kiểm, không phải bằng câu chữ
trong prompt.

Phụ thuộc một chiều: module này import `vnstock_brief_canon` (hằng số + khối
canon) và KHÔNG import `vnstock_brief` — nhờ vậy không có vòng import.
Chiều ngược lại, `vnstock_brief` re-export mọi tên ở đây nên các đường import
cũ (`from vnstock_brief import enforce_...`) vẫn chạy nguyên.
"""
from __future__ import annotations

from vnstock_brief_canon import (
    VN30_TICKERS,
    _FINANCIAL_TICKERS,
    _SR_MAX_MOVE_PCT,
    _WATCHLIST_GTGD_MIN_TY,
    _allocation_table_lines,
    _gtgd_close_frame,
    _macro_body_lines,
    _macro_reports_body_lines,
    _market_news_body_lines,
    _portfolio_fact_line,
    _round_tick,
)





# ── Runtime hallucination validator ────────────────────────────────────────
#
# Defensive layer: scans the LLM's brief output AFTER generation to detect
# numbers that look like hallucinated VNINDEX levels. Won't catch every
# hallucination but catches the most painful class — wrong index price.
#
# Strategy:
#   1. Find all VNINDEX-magnitude numbers (1.000-2.500 range) in the text
#      that appear within 25 chars of "VNINDEX" or "VNI" (context window)
#   2. Compare each to the real injected close from ctx["vnindex_tech"]
#   3. Flag if relative error > 5% (allows for daily move + S/R nearby)
#
# Returns list of warning strings; empty list = brief looks clean.
import re as _re

_VNI_MAGNITUDE_RE = _re.compile(r"\b([12][.,]?\d{3}(?:[.,]\d{1,2})?)\b")
_VNI_CONTEXT_RE = _re.compile(r"VN[\s\-]?INDEX|VN-?I(?![A-Z])|VNI(?![A-Z])", _re.IGNORECASE)


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


_SECTION_EMOJIS = ("🎯", "📊", "📈", "🏆", "💰", "📋", "⚠️", "📅", "💡", "🔧", "⚡", "🔮", "🌐", "📰", "📌", "📚", "🧭")


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


def enforce_upcoming_events(text: str, ctx: dict) -> str:
    """Deterministic guard: the events section is pure data — no analysis — yet
    the LLM keeps mangling it (claimed "Không có sự kiện đáng chú ý" at 13:50
    with ACB in the prompt; listed only 1 of 2 same-day ACB events at 14:48 and
    15:20). When ctx carries upcoming_events, replace the whole section body
    with the canonical list (top 3 + GDKHQ note); with no section header,
    replace a stray denial line. No-op when there are no events.
    """
    events = ctx.get("upcoming_events") or []
    if not text or not events:
        return text

    def _fmt(e: dict) -> str:
        return (f"{e.get('ticker','?')}: {e.get('title') or 'Sự kiện DN'}"
                f" — ngày {e.get('ex_date','?')}")

    ev_lines = [_fmt(e) for e in events[:3]]
    ev_lines.append("(Giá tự điều chỉnh trong ngày GDKHQ — không phải giảm do thị trường.)")

    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "sự kiện sắp tới" in l.lower()), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if _is_section_start(lines[i])), len(lines))
        if lines[start + 1:end] == ev_lines:
            return text
        return "\n".join(lines[:start + 1] + ev_lines + lines[end:])

    out: list[str] = []
    replaced = False
    for line in lines:
        if not replaced and "không có sự kiện đáng chú ý" in line.lower():
            out.extend(ev_lines)
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


def enforce_macro(text: str, ctx: dict) -> str:
    """Deterministic guard: the macro section (🌐 lãi suất & tỷ giá) is pure data
    — exact levels, as_of dates and signed changes the LLM must not paraphrase or
    round into a wrong number. When ctx carries macro readings, replace the whole
    section body with the canonical bullets from `_macro_block` (minus the header,
    which the model already prints). No section header → splice over a stray "chưa
    có dữ liệu vĩ mô" denial. No-op (idempotent) when readings are absent.
    """
    macro = ctx.get("macro") or []
    if not text or not macro:
        return text

    # Canonical body WITHOUT header (model prints its own "## 🌐 Vĩ mô" which
    # we keep as anchor) và WITHOUT directive — chỉ thị "→ … DÙNG bối cảnh
    # này…" thuộc prompt, splice vào brief xuất bản là leak (close 14/07).
    body = _macro_body_lines(macro, ctx.get("macro_news"), directive=False)

    lines = text.splitlines()
    # Header detection 2 NẤC. Nấc 1 (ưu tiên): dòng section-start thật có "vĩ
    # mô". Nấc 2 (fallback — CHỈ khi không có nấc 1): dòng mang "vĩ mô" + lãi
    # suất/tỷ giá, bắt header bị LLM reformat nên _is_section_start trượt
    # (close 16/06). KHÔNG được thử nấc 2 trước: dòng VĂN XUÔI "Rủi ro vĩ mô:
    # lãi suất…" trong mục Rủi ro cũng khớp → body canonical splice nhầm vào
    # mục Rủi ro và NUỐT các dòng D/E, còn section 🌐 thật bị bỏ qua (bug thật
    # close 01:10 15/07).
    def _is_macro_header_loose(l: str) -> bool:
        low = l.lower()
        return "vĩ mô" in low and ("lãi suất" in low or "tỷ giá" in low)

    start = next((i for i, l in enumerate(lines)
                  if _is_section_start(l) and "vĩ mô" in l.lower()), None)
    if start is None:
        start = next((i for i, l in enumerate(lines)
                      if _is_macro_header_loose(l)), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if _is_section_start(lines[i])), len(lines))
        if lines[start + 1:end] == body:
            return text
        return "\n".join(lines[:start + 1] + body + lines[end:])

    out: list[str] = []
    replaced = False
    for line in lines:
        low = line.lower()
        if not replaced and "vĩ mô" in low and ("chưa có" in low or "không có" in low):
            out.extend(body)
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


def enforce_macro_fx_pct(text: str, ctx: dict) -> str:
    """Belt-and-suspenders: pin the USD/VND change % on its own line to the real
    macro reading, independent of enforce_macro's whole-section replacement.

    If enforce_macro's header detection misses (LLM reformats the header), a
    hallucinated FX % can survive (close 16/06: brief showed "▼ -3%" while
    load_macro had -0.07%). This finds the USD/VND line and pins its
    "[▲▼] ±N% so với" to the canonical change. No-op without an fx change.
    """
    macro = ctx.get("macro") or []
    fx = next((m for m in macro
               if m.get("kind") == "fx" and (m.get("change") or {}).get("pct") is not None),
              None)
    if not text or not fx:
        return text
    ch = fx["change"]
    canon = f"{'▲' if ch['dir'] > 0 else '▼'} {ch['pct']:+.2f}% so với"

    def _fix(line: str) -> str:
        if "usd/vnd" not in line.lower():
            return line
        return _re.sub(r"[▲▼]?\s*[+-]?\d[\d.,]*\s*%\s*so với", canon, line, count=1)

    return "\n".join(_fix(l) for l in text.splitlines())


def enforce_market_news(text: str, ctx: dict) -> str:
    """Deterministic guard: the "📰 Tin kinh tế/chính trị" section is a curated list
    of REAL headlines (+ LLM impact) — the LLM must not paraphrase into fabricated
    news. When ctx carries market_news, replace the section body with the canonical
    bullets; with no header, splice over a "không có tin" denial. No-op when none.
    """
    items = ctx.get("market_news") or []
    if not text or not items:
        return text

    # directive=False — dòng chỉ thị "→ DÙNG các tin trên… TUYỆT ĐỐI KHÔNG
    # bịa…" chỉ thuộc prompt, không được vào brief xuất bản (leak 14/07).
    body = _market_news_body_lines(items, directive=False)
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if ("tin kinh tế" in l.lower() or "kinh tế/chính trị" in l.lower())
                  and _is_section_start(l)), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if _is_section_start(lines[i])), len(lines))
        if lines[start + 1:end] == body:
            return text
        return "\n".join(lines[:start + 1] + body + lines[end:])

    out: list[str] = []
    replaced = False
    for line in lines:
        low = line.lower()
        if (not replaced and "kinh tế" in low
                and ("chưa có" in low or "không có" in low)):
            out.extend(body)
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


def enforce_macro_reports(text: str, ctx: dict) -> str:
    """Deterministic guard (P4): mục "📚 Báo cáo vĩ mô & phân bổ" là DATA thuần
    (band tháng + tom_tat digest + consensus) — LLM không được paraphrase band,
    bịa nguồn báo cáo hay đổi stance. Khi ctx có macro_reports/allocation, thay
    toàn bộ body mục bằng canonical bullets từ `_macro_reports_body_lines`
    (directive=False — dòng chỉ thị chỉ thuộc prompt); không có header → splice
    đè dòng phủ nhận "chưa có báo cáo". No-op khi ctx trống. Idempotent.
    """
    body = _macro_reports_body_lines(ctx, directive=False)
    if not text or not body:
        return text

    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "báo cáo vĩ mô" in l.lower() and _is_section_start(l)), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if _is_section_start(lines[i])), len(lines))
        if lines[start + 1:end] == body:
            return text
        return "\n".join(lines[:start + 1] + body + lines[end:])

    out: list[str] = []
    replaced = False
    for line in lines:
        low = line.lower()
        if (not replaced and "báo cáo vĩ mô" in low
                and ("chưa có" in low or "không có" in low)):
            out.extend(body)
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


# Caveat horizon (P4): band THÁNG nghiêng ngược bias floor NGÀY → gắn ngữ cảnh,
# KHÔNG override (mirror triết lý guard 27/28). Bắt đầu bằng "- ⚠️" (dash trước)
# để KHÔNG bị _is_section_start hiểu nhầm là ranh giới mục (bài học guard 27).
_ALLOC_HORIZON_CAVEAT = (
    "- ⚠️ Band phân bổ là khung THÁNG, tín hiệu phiên đang lệch chiều — hai "
    "khung thời gian khác nhau, không phủ định nhau: điều chỉnh tỷ trọng theo "
    "lộ trình vài phiên, tôn trọng tín hiệu ngày khi vào/ra lệnh."
)


def enforce_allocation_table(text: str, ctx: dict) -> str:
    """Deterministic guard (P4) — nguyên tắc #1: LLM không bao giờ sinh số
    %/band, guard pin. Ba việc, đều no-op khi ctx thiếu allocation:

    (a) Pin token "band B<x>" lạc ở BẤT KỲ ĐÂU về band thật (LLM hay chép nhầm
        B0/B2 từ bảng ví dụ); bỏ qua dòng canonical đã mang band data/tilt
        ("band data:", "Band phân bổ tháng", "- Band:") — các dòng đó do guard
        khác/chính guard này in, chứa band KHÁC band hiệu lực một cách hợp lệ.
    (b) Brief allocation: thay toàn bộ body mục "🧭 Phân bổ đề xuất" bằng bảng
        canonical từ `_allocation_table_lines` (LLM chỉ được viết lời ở mục khác).
    (c) Caveat horizon: band tháng nghiêng TẤN CÔNG (B0/B1) trong khi bias floor
        ngày GIẢM (hoặc ngược lại B3/B4 vs TĂNG) → chèn 1 dòng ngữ cảnh sau dòng
        band, KHÔNG đổi band/bias nào. Idempotent qua marker trên toàn văn.
    """
    alloc = ctx.get("allocation") or {}
    band = alloc.get("band")
    if not text or band not in ("B0", "B1", "B2", "B3", "B4"):
        return text

    _CANON_MARKS = ("band data", "band phân bổ tháng", "- band:")

    def _pin_band(line: str) -> str:
        low = line.lower()
        if any(m in low for m in _CANON_MARKS):
            return line
        # "band B0" (chữ band ngay trước) + "Band phân bổ:** B0" (TLDR brief
        # allocation — có "phân bổ"/markdown giữa "band" và token B).
        line = _re.sub(r"\b([Bb]and\s+)B[0-4]\b", rf"\g<1>{band}", line)
        return _re.sub(r"([Bb]and phân bổ[:\*\s]+)B[0-4]\b", rf"\g<1>{band}", line)

    lines = [_pin_band(l) for l in text.splitlines()]

    # (b) bảng % canonical cho brief allocation
    table = _allocation_table_lines(alloc)
    if table:
        start = next((i for i, l in enumerate(lines)
                      if "phân bổ đề xuất" in l.lower() and _is_section_start(l)),
                     None)
        if start is not None:
            end = next((i for i in range(start + 1, len(lines))
                        if _is_section_start(lines[i])), len(lines))
            if lines[start + 1:end] != table:
                lines = lines[:start + 1] + table + lines[end:]

    out = "\n".join(lines)

    # (d) Pin "%" gắn với TÊN LỚP TÀI SẢN trong VĂN XUÔI về đúng bảng band —
    # brief phân bổ đầu tiên trên máy user (15/07, Mistral Small) bịa ngay
    # trong TLDR: "Giảm tỷ trọng cổ phiếu xuống 10% (từ 15%), duy trì tiền
    # gửi 45%" — 10%/45% không thuộc band nào (B4: cổ phiếu 15, tiền gửi 40).
    # CHỈ chạy trong brief allocation (gate: có mục "Phân bổ đề xuất") để
    # "cổ phiếu…%" trong brief ngày không bị đụng; gap tên→số không vượt
    # dấu câu (ở lại cùng mệnh đề); giá trị đúng canonical giữ nguyên.
    alloc_pct = alloc.get("allocation") or {}
    if alloc_pct and "phân bổ đề xuất" in out.lower():
        for cls, pct in alloc_pct.items():
            def _pin_pct(m: "_re.Match", _p=pct) -> str:
                v = _parse_vn_number(m.group(2))
                if v is None or abs(v - _p) < 0.01:
                    return m.group(0)
                return f"{m.group(1)}{_p:g}{m.group(3)}"
            out = _re.sub(
                rf"({_re.escape(cls)}[^%\n.,;:()]{{0,30}}?)(\d+(?:\.\d+)?)(\s*%)",
                _pin_pct, out, flags=_re.IGNORECASE)

    # (c) caveat horizon — chỉ khi lệch chiều thật và chưa chèn (check toàn văn)
    bias = (ctx.get("bias_floor") or {}).get("dir")
    clash = (band in ("B0", "B1") and bias == "GIẢM") or \
            (band in ("B3", "B4") and bias == "TĂNG")
    if clash and _ALLOC_HORIZON_CAVEAT not in out:
        lines = out.splitlines()
        anchor = next((i for i, l in enumerate(lines)
                       if "band phân bổ tháng" in l.lower()
                       or l.lstrip().lower().startswith("- band:")), None)
        if anchor is not None:
            lines.insert(anchor + 1, _ALLOC_HORIZON_CAVEAT)
            out = "\n".join(lines)
    return out


def enforce_portfolio_facts(text: str, ctx: dict) -> str:
    """Deterministic guard: the '📌 Danh mục đang giữ' facts (số cp / vốn /
    hiện / lãi-lỗ %) are pure data the LLM must echo verbatim. Rebuild each
    position line as canonical-facts + the model's ' → hành động ...' suffix
    (kept); body lines naming tickers outside the portfolio are dropped (chống
    bịa mã/số tổng). Section missing → splice canonical facts over a "không có
    vị thế" denial, else insert before '💡 Đề xuất giao dịch' (or append).
    No-op when ctx has no positions. Idempotent.
    """
    positions = ctx.get("portfolio") or []
    if not text or not positions:
        return text

    facts = [(p["ticker"], _portfolio_fact_line(p)) for p in positions]
    lines = text.splitlines()

    start = next((i for i, l in enumerate(lines)
                  if "danh mục" in l.lower() and (_is_section_start(l) or "📌" in l)),
                 None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if _is_section_start(lines[i])), len(lines))
        old_body = lines[start + 1:end]
        new_body: list[str] = []
        for tk, fact in facts:
            suffix = ""
            for bl in old_body:
                if _re.search(rf"\b{tk}\b", bl):
                    m = _re.search(r"→(.+)$", bl)
                    if m and m.group(1).strip():
                        suffix = " → " + m.group(1).strip()
                    break
            new_body.append(fact + suffix)
        if old_body == new_body:
            return text
        return "\n".join(lines[:start + 1] + new_body + lines[end:])

    block = ["## 📌 Danh mục đang giữ"] + [f for _, f in facts]
    for i, l in enumerate(lines):
        low = l.lower()
        if "không có vị thế" in low or ("danh mục" in low and "không có" in low):
            return "\n".join(lines[:i] + block + lines[i + 1:])
    ins = next((i for i, l in enumerate(lines)
                if _is_section_start(l) and "đề xuất giao dịch" in l.lower()),
               len(lines))
    return "\n".join(lines[:ins] + block + lines[ins:])


def enforce_realestate_ocf_context(text: str, ctx: dict) -> str:
    """Deterministic guard: when the risk section names a real-estate ticker for
    weak operating cash flow but drops the land-bank context (observed: 13:50
    brief carried "do tích lũy quỹ đất…", the 14:48 one cited KBC/NVL bare),
    append the context note right after that line so a bare negative OCF is
    never read as distress. No-op when no RE ticker is cited for OCF or the
    context is already present.
    """
    re_tickers = ctx.get("realestate_tickers") or set()
    if not text or not re_tickers:
        return text
    low = text.lower()
    if "quỹ đất" in low or "tồn kho" in low:
        return text                      # context already present somewhere

    # Any HĐKD/operating cash-flow phrasing — incl. the model's frequent slip
    # "lưu LƯỢNG tiền HĐKD" (observed close brief: that wording escaped the
    # guard so KBC/NVL got no land-bank context). "hđkd" alone is safe here:
    # in the risk section it only appears in a cash-flow clause.
    _ocf_words = ("op.cf", "lưu chuyển tiền", "lưu lượng tiền", "hđkd")
    out: list[str] = []
    added = False
    for line in text.splitlines():
        out.append(line)
        if added or not any(w in line.lower() for w in _ocf_words):
            continue
        cited = [t for t in sorted(re_tickers)
                 if _re.search(rf"\b{_re.escape(t)}\b", line)]
        if cited:
            out.append(
                f"(Lưu ý: Op.CF âm của {', '.join(cited)} — BĐS — chủ yếu do "
                "tích lũy quỹ đất/hàng tồn kho dự án, không phải lỗ HĐKD; cần "
                "soi thêm D/E và nợ vay.)"
            )
            added = True
    return "\n".join(out)


# Meta-disclaimers the model sneaks into watchlist setups despite the template
# ("(đây là ví dụ, không dùng thực tế…)"), and the bail line it pads with even
# when a priced setup exists. Both are stripped deterministically.
_WL_META_RE = _re.compile(
    r"\s*\([^)]*(?:ví dụ|minh họa|minh hoạ|không dùng thực tế|giả định"
    r"|không có đủ thông tin|không đủ thông tin)[^)]*\)",
    _re.IGNORECASE,
)


def enforce_watchlist_hygiene(text: str, ctx: dict | None = None) -> str:
    """Deterministic guard for the watchlist section: strip meta-disclaimers
    from setup lines (observed: "MUA vùng 69,000 … (đây là ví dụ, không dùng
    thực tế…)"), DROP setups anchored to VNINDEX levels instead of the stock's
    own price (observed 13:25: "CII (Giá 17,300) — canh mua nếu vượt
    R1=1,800.80" — index points on a 17k-VND stock; eligible stocks trade
    ≥ 5,000 VND so a pivot value inside the 800-2500 index band can never be a
    valid stock level), and drop the "Cần thêm dữ liệu giá…" filler when at
    least one real priced setup is present. No-op without a watchlist section.
    """
    if not text:
        return text
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if "watchlist sáng mai" in l.lower()), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].lstrip().startswith(("##", "⚠️", "📅", "💡", "🔧", "📋"))),
               len(lines))

    def _uses_index_levels(l: str) -> bool:
        return bool(_re.match(r"\s*\d+\.", l)) and any(
            (n := _parse_vn_number(m.group(2))) is not None and 800 <= n <= 2500
            for m in _PIVOT_LABEL_RE.finditer(l)
        )

    body = lines[start + 1:end]
    dropped_invalid = any(_uses_index_levels(l) for l in body)
    sec = [_WL_META_RE.sub("", l).rstrip() for l in body
           if not _uses_index_levels(l)]
    # a real setup = direction keyword + a thousand-grouped price on the line
    has_priced_setup = any(
        _re.search(r"MUA|GIẢM TỶ TRỌNG|TRÁNH", l, _re.IGNORECASE)
        and _re.search(r"\d{1,3}[.,]\d{3}", l)
        for l in sec
    )
    if has_priced_setup:
        sec = [l for l in sec if "cần thêm dữ liệu giá" not in l.lower()]
    sec = [l for l in sec if not _re.fullmatch(r"\s*\d+\.\s*", l)]  # empty "2." stubs
    if dropped_invalid and not has_priced_setup and not any(
            "cần thêm dữ liệu giá" in l.lower() for l in sec):
        # every setup was invalid (index-level anchors) → honest bail line
        sec.append("Cần thêm dữ liệu giá cổ phiếu cụ thể")

    # Bias GIẢM: an unconditional "MUA vùng [giá hiện tại]" is a dip-buy /
    # bắt-dao-rơi the bias floor forbids (observed 21:31: CII MUA vùng 17,200
    # while Stance = GIẢM). Convert to a confirmation-breakout form, keeping the
    # numbers/order intact ("canh MUA NẾU vượt [entry] · mục tiêu [TP] · cắt lỗ
    # [SL]"). Defensive (GIẢM TỶ TRỌNG/TRÁNH) lines are left untouched.
    if (ctx or {}).get("bias_floor", {}).get("dir") == "GIẢM":
        sec = [(l.replace("MUA vùng", "canh MUA NẾU vượt").replace("· chốt lời", "· mục tiêu")
                if "MUA vùng" in l else l) for l in sec]

    # A breakout-buy trigger MUST sit MEANINGFULLY ABOVE the stock's current
    # price — else "canh MUA NẾU vượt X" is already true / a non-confirmation
    # (observed 22:22: CII "vượt 16,684" while Giá=17,200 = support; 11:03: CII
    # "vượt 17,200" = the price itself). Bump any trigger within +0.5% of Giá up
    # to ~+2% (a real confirmation breakout).
    def _setup_price(l: str) -> "float | None":
        # the stock price sits right after the bolded ticker, in EITHER form:
        # "**CII** (17,350)" or "**CII** (Giá 17,350)" (observed 21:19 dropped the
        # 'Giá' word, which the old Giá-only regex missed → trigger never bumped).
        m = _re.search(r"\(\s*(?:Giá\s*)?([\d][\d.,]*)\s*\)", l) \
            or _re.search(r"Giá\s*([\d][\d.,]*)", l)
        return _parse_vn_number(m.group(1)) if m else None

    def _fix_buy_trigger(l: str) -> str:
        if "canh mua" not in l.lower():
            return l
        P = _setup_price(l)
        if not P:
            return l

        def _sub(m: "_re.Match") -> str:
            x = _parse_vn_number(m.group(2))
            if x is not None and x < P * 1.005:
                return f"{m.group(1)}{_round_tick(P * 1.02, P):,}"
            return m.group(0)

        l = _re.sub(r"(vượt(?:\s*lại)?\s*)([\d][\d.,]*)", _sub, l, count=1)

        # Keep a sane reward after the bump: if "mục tiêu" sits within 1.5% of
        # the (possibly bumped) trigger (observed 23:56: vượt 17,550 → mục tiêu
        # 17,716 = +0.95%), raise the target to ~trigger+3%.
        tm = _re.search(r"vượt(?:\s*lại)?\s*([\d][\d.,]*)", l)
        trig = _parse_vn_number(tm.group(1)) if tm else None
        if trig:
            def _sub_tp(m: "_re.Match") -> str:
                y = _parse_vn_number(m.group(2))
                if y is not None and y < trig * 1.015:
                    return f"{m.group(1)}{_round_tick(trig * 1.03, trig):,}"
                return m.group(0)
            l = _re.sub(r"(mục tiêu\s*)([\d][\d.,]*)", _sub_tp, l, count=1)
        return l

    def _round_all_ticks(l: str) -> str:
        # Round EVERY setup price level to the stock's HOSE tick (observed odd
        # 17,716 / 92,635). Scope to numbers near the stock price (0.5×–1.5× Giá)
        # so list indices / % / GTGD are untouched.
        P = _setup_price(l)
        if not P:
            return l

        def _sub(m: "_re.Match") -> str:
            v = _parse_vn_number(m.group(0))
            return f"{_round_tick(v, P):,}" if v is not None and 0.5 * P <= v <= 1.5 * P \
                else m.group(0)

        return _re.sub(r"\d{1,3}(?:[.,]\d{3})+", _sub, l)

    sec = [_round_all_ticks(_fix_buy_trigger(l)) for l in sec]

    if sec == lines[start + 1:end]:
        return text
    return "\n".join(lines[:start + 1] + sec + lines[end:])


def enforce_lead_lag(text: str, ctx: dict) -> str:
    """Pin the lead/lag sector lines to the deterministic lead_sector/lag_sector.

    Both templates carry a "🎯 Dẫn dắt/Tụt hậu — CHỐT THEO DATA" directive, but
    it's only a prompt nudge. The close follows it; the MORNING brief ignored it
    (observed 13:40: denied the leader — "Chưa có nhóm dẫn dắt" while BĐS is
    +0.275pp — AND put the LEAD sector on the "Tránh/Bán" line with a wrong
    -0.03pp, contradicting its own TLDR). Canonicalise the buy/lead line
    (morning "Tích luỹ/Mua" / close "Dẫn dắt") and the avoid/lag line (morning
    "Tránh/Bán" / close "Tụt hậu") when they deny the call, name the WRONG side's
    sector, or omit the right one. Correct lines (the close) are left untouched;
    idempotent; no-op without lead/lag data.
    """
    lead = ctx.get("lead_sector") or {}
    lag = ctx.get("lag_sector") or {}
    lead_name = (lead.get("name") or "").strip()
    lag_name = (lag.get("name") or "").strip()
    if not text or not lead_name or not lag_name:
        return text
    lc = lead.get("contrib", 0) or 0
    gc = lag.get("contrib", 0) or 0
    lead_canon = (f"{lead_name} (đóng góp {lc:+.3f}pp, 1 tuần — mạnh nhất)."
                  if lc >= 0.05 else
                  f"Chưa có nhóm dẫn dắt rõ ràng (đóng góp lớn nhất chỉ {lc:+.3f}pp).")
    lag_canon = (f"{lag_name} (đóng góp {gc:+.3f}pp, 1 tuần — yếu nhất)."
                 if gc <= -0.05 else
                 f"Chưa có nhóm tụt hậu rõ rệt (đóng góp yếu nhất chỉ {gc:+.3f}pp).")
    lead_lab = _re.compile(r"(\**\s*(?:Tích lu[ỹy]/Mua|Dẫn dắt)\s*:\s*\**\s*)", _re.IGNORECASE)
    lag_lab = _re.compile(r"(\**\s*(?:Tránh/Bán|Tụt hậu)\s*:\s*\**\s*)", _re.IGNORECASE)
    _deny = ("chưa có", "không có", "không rõ", "chưa rõ")
    out, changed = [], False
    for ln in text.splitlines():
        m = lead_lab.match(ln)
        if m:
            bl = ln[m.end():].lower()
            wrong = ((lc >= 0.05 and (lead_name.lower() not in bl
                                      or any(d in bl for d in _deny)
                                      or lag_name.lower() in bl))
                     or (lc < 0.05 and not any(d in bl for d in _deny)))
            if wrong:
                ln, changed = m.group(1) + lead_canon, True
            out.append(ln)
            continue
        m = lag_lab.match(ln)
        if m:
            bl = ln[m.end():].lower()
            wrong = ((gc <= -0.05 and (lag_name.lower() not in bl
                                       or any(d in bl for d in _deny)
                                       or lead_name.lower() in bl))
                     or (gc > -0.05 and not any(d in bl for d in _deny)))
            if wrong:
                ln, changed = m.group(1) + lag_canon, True
            out.append(ln)
            continue
        out.append(ln)
    result = "\n".join(out) if changed else text

    # Pin the lead/lag sector's pp contribution wherever it's stated wrong — the
    # model invents a pp for the lead OUTSIDE the label lines too (observed
    # morning 23:14: TLDR "giảm tỷ trọng Bất động sản (đóng góp -0.504pp)" — it
    # borrowed the -504 tỷ NN market figure as a fake -0.504pp, contradicting the
    # +0.464pp leader in its own Trọng tâm). Pin {lead}/{lag} pp to the canonical
    # value anywhere it's off by > 0.005pp. Correct mentions are left; idempotent.
    for nm, cv in ((lead_name, lc), (lag_name, gc)):
        def _pp(m: "_re.Match", _cv=cv) -> str:
            v = _parse_vn_number(m.group(2))
            return (f"{m.group(1)}{_cv:+.3f}pp"
                    if v is not None and abs(v - _cv) > 0.005 else m.group(0))
        result = _re.sub(
            rf"({_re.escape(nm)}.{{0,30}}?đóng góp\s*)([+-]?[\d.,]+)\s*pp", _pp, result)

    # Pin luôn TRỌNG SỐ "%VNI" của lead/lag về ctx sector_weights — close
    # 23:58 14/07: "Họ VIN [1.6%VNI, đóng góp -0.873pp]" trong khi trọng số
    # thật ~25% (model mượn GTGD 1,653 tỷ mangle thành "1.6"); cặp số tự đá
    # nhau (hàm ý -55%/tuần). pp đã pin ở trên; trọng số cũng phải khớp data.
    sw = ctx.get("sector_weights") or {}
    for nm in (lead_name, lag_name):
        w = ((sw.get(nm) or {}).get("_weight", 0) or 0) * 100
        if w <= 0:
            continue
        def _wfix(m: "_re.Match", _w=w) -> str:
            v = _parse_vn_number(m.group(2))
            return (f"{m.group(1)}{_w:.1f}{m.group(3)}"
                    if v is not None and abs(v - _w) > 0.5 else m.group(0))
        result = _re.sub(
            rf"({_re.escape(nm)}\s*\[\s*)([\d.,]+)(\s*%\s*VNI)", _wfix, result)
    return result


def enforce_money_flow_two_sides(text: str, ctx: dict) -> str:
    """Deterministic guard: the money-flow commentary must carry BOTH the
    strongest foreign net-buy AND net-sell sector (observed 15:20: only the
    +708 tỷ buy side, dropped the dominant BĐS -5,111 tỷ sell). Works for BOTH
    briefs: the close's dedicated "💰 Dòng tiền đáng chú ý" section and the
    morning's inline "Dòng tiền ngành" line — it anchors on the money-flow line
    itself (not a section header) and appends the missing side right after it
    when its magnitude is ≥ 50 tỷ. No-op without the line or the data.
    """
    sectors = ctx.get("sectors") or []
    rows = [(s.get("Ngành"), s.get("NN 1T (tỷ)")) for s in sectors
            if s.get("Ngành") and isinstance(s.get("NN 1T (tỷ)"), (int, float))]
    if not text or not rows:
        return text

    lines = text.splitlines()
    # Prefer the DEDICATED money-flow anchor — the close's "💰 Dòng tiền đáng
    # chú ý" section header or the morning's "**Dòng tiền ngành:**" line. Only
    # fall back to a generic money keyword when neither exists (observed 13:25:
    # the generic match hit "dòng tiền" inside Tổng kết/Trọng tâm prose and
    # spliced the NN lines mid-section while the real section was already fine).
    anchor = next((i for i, l in enumerate(lines)
                   if "dòng tiền ngành" in l.lower()
                   or (_is_section_start(l) and "dòng tiền" in l.lower())),
                  None)
    if anchor is None:
        _kw = ("mua ròng", "bán ròng", "nn ròng", "dòng tiền")
        anchor = next((i for i, l in enumerate(lines)
                       if not _is_section_start(l) and any(k in l.lower() for k in _kw)),
                      None)
    if anchor is None:
        return text
    region_end = next((i for i in range(anchor + 1, len(lines))
                       if _is_section_start(lines[i])), len(lines))

    # In-place correct wrong per-sector NN figures the model wrote (observed
    # 11:19: "mua ròng 5 tỷ … Thực phẩm & Đồ uống" while the real NN 1T is +136
    # — and the canonical line below then said +136, contradicting it). Handles
    # the common VN phrasing "[verb] N tỷ [đồng] [trong ngành] <NAME>" where the
    # number PRECEDES the sector name. Uses the abs value (the mua/bán word
    # carries the sign).
    for i in range(anchor, region_end):
        for nm, vv in rows:
            av = abs(vv)
            if av < 30:                       # skip noise / tiny flows
                continue

            def _fix(m: "_re.Match", _av=av) -> str:
                cur = _parse_vn_number(m.group(1))
                return (f"{_av:,.0f}{m.group(2)}"
                        if cur is not None and abs(cur - _av) > max(1.0, 0.02 * _av)
                        else m.group(0))

            new = _re.sub(
                rf"(\d[\d.,]*)(\s*tỷ(?:\s*đồng)?\s*(?:trong\s+ngành\s+)?{_re.escape(nm)}\b)",
                _fix, lines[i])
            if new != lines[i]:
                lines[i] = new

            # number-AFTER-name in a parenthetical — "<NAME> (NN -1,372 tỷ)"
            # (observed 12:03: the model FABRICATED "Thép & Kim loại (NN -1,372
            # tỷ)" while the real NN 1T was nowhere near that; the before-name
            # regex above can't see it). The sign is explicit here, so correct
            # to the real SIGNED value — a wrong magnitude can't survive.
            def _fix_after(m: "_re.Match", _vv=vv) -> str:
                cur = _parse_vn_number(m.group(2))
                return (f"{m.group(1)}{_vv:+,.0f}{m.group(3)}"
                        if cur is not None and abs(cur - _vv) > max(1.0, 0.02 * abs(_vv))
                        else m.group(0))

            new = _re.sub(
                rf"({_re.escape(nm)}\s*\(\s*(?:NN\s*|khối\s+ngoại\s*)?)(-?\d[\d.,]*)(\s*tỷ)",
                _fix_after, lines[i])
            if new != lines[i]:
                lines[i] = new
    region_low = "\n".join(lines[anchor:region_end]).lower()

    top_buy = max(rows, key=lambda x: x[1])
    top_sell = min(rows, key=lambda x: x[1])

    def _num_present(v: float) -> bool:
        # the strongest side's tỷ figure already on the line (either , or .
        # thousands sep) — so we don't duplicate when the model gave the number.
        s = f"{abs(v):,.0f}"
        return s in region_low or s.replace(",", ".") in region_low

    _clauses = _re.split(r"[.;\n]", "\n".join(lines[anchor:region_end]).lower())

    def _named_in_side(name: str, side_kw: str) -> bool:
        # the TRUE strongest sector is named in the SAME CLAUSE as its side
        # keyword — so the ranking is right, not just the number present
        # (observed 12:03: Thép -1,372 was the biggest sell but sat in a "phân
        # phối" clause while Ngân hàng -703 was called "bán ròng mạnh nhất").
        nl = name.lower()
        return any(side_kw in c and nl in c for c in _clauses)

    # Append the canonical line unless the TRUE top sector is already named in
    # its side's clause WITH its figure.
    add: list[str] = []
    if top_sell[1] <= -50 and not (_named_in_side(top_sell[0], "bán ròng")
                                   and _num_present(top_sell[1])):
        add.append(f"NN bán ròng mạnh nhất (1 tuần): {top_sell[0]} {top_sell[1]:+,.0f} tỷ.")
    if top_buy[1] >= 50 and not (_named_in_side(top_buy[0], "mua ròng")
                                 and _num_present(top_buy[1])):
        add.append(f"NN mua ròng mạnh nhất (1 tuần): {top_buy[0]} {top_buy[1]:+,.0f} tỷ.")
    rebuilt = "\n".join(lines[:anchor + 1] + add + lines[anchor + 1:])
    return rebuilt if rebuilt != text else text


def enforce_sector_nn_figures(text: str, ctx: dict) -> str:
    """Correct a per-sector foreign-flow figure stated ANYWHERE in the brief, not
    just the money-flow section. Observed morning 14:11: the "Tránh/Bán" line
    carried "Thép & Kim loại (đóng góp -0.03pp, 1 tuần, NN bán ròng -1,372 tỷ)" —
    a fabricated value that also contradicts "Ngân hàng -703 tỷ mạnh nhất" in the
    same brief (if Thép were -1,372 it would be the top sell). enforce_money_flow
    misses it: the number follows 'NN bán ròng' deep in the parenthetical (not
    right after '(') and the line sits OUTSIDE the money-flow region.

    Wherever a sector name is followed — within ~40 chars on the same line — by a
    'NN/khối ngoại [bán/mua] ròng <num> tỷ' figure off from ctx by >2%, pin it to
    the real signed value. The 'ròng' keyword right before the number means the
    pp value ('-0.03pp') is never grabbed. Idempotent; no-op without data.
    """
    sectors = ctx.get("sectors") or []
    rows = [(s.get("Ngành"), s.get("NN 1T (tỷ)")) for s in sectors
            if s.get("Ngành") and isinstance(s.get("NN 1T (tỷ)"), (int, float))]
    if not text or not rows:
        return text
    all_names = {nm for nm, _ in rows}
    out = text
    for nm, vv in rows:
        def _fix(m: "_re.Match", _vv=vv, _nm=nm) -> str:
            cur = _parse_vn_number(m.group(2))
            if cur is None or abs(cur - _vv) <= max(1.0, 0.02 * abs(_vv)):
                return m.group(0)
            # Số này thuộc NGÀNH KHÁC nếu ngay sau nó gắn "trong ngành <other>"
            # (close 15/07: "…Họ VIN (1 tuần), trong khi bán ròng 703 tỷ đồng
            # trong ngành Ngân hàng" — pass Họ VIN nuốt số 703 của Ngân hàng
            # rồi pin thành +1,496). Đừng đụng nếu attribution ngay sau là ngành
            # khác nm.
            tail = m.string[m.end():m.end() + 44]
            tm = _re.match(r"\s*(?:đồng\s*)?trong\s+ngành\s+(.+)",
                           tail, _re.IGNORECASE)
            if tm:
                trailing = tm.group(1).strip().lower()
                if any(trailing.startswith(o.lower()) and o.lower() != _nm.lower()
                       for o in all_names):
                    return m.group(0)
            return f"{m.group(1)}{_vv:+,.0f}{m.group(3)}"
        # Số cho phép dấu "+" — close 14/07: "Ngân hàng bị bán ròng +1,471 tỷ"
        # (magnitude của ngành KHÁC gắn nhầm + sign dương) trượt vì pattern cũ
        # chỉ nhận "-?". Gap tên→verb KHÔNG được vượt ranh giới mệnh đề: cấm
        # ".<space>" (hết câu — dấu chấm THẬP PHÂN "-0.03pp" vẫn qua), token
        # "tỷ" (số+đơn vị đã chốt = mệnh đề ngành TRƯỚC đó) VÀ connector "trong
        # khi" (nối 2 vế dòng-tiền — close 15/07: pass Họ VIN vượt "…, trong
        # khi bán ròng…" sang số của Ngân hàng, pin nhầm thành +1,496).
        out = _re.sub(
            rf"({_re.escape(nm)}(?:(?!\.\s|tỷ\b|trong\s+khi)[^;\n]){{0,40}}?"
            rf"(?:NN|khối\s+ngoại)?\s*(?:bán|mua)\s+ròng\s*)"
            rf"([-+]?\d[\d.,]*)(\s*tỷ)",
            _fix, out)
    return out


def enforce_net_flow_label(text: str, ctx: dict) -> str:
    """A 'mua ròng'/'bán ròng' verb must match the SIGN of the named sector's
    real NN, and the figure must not carry a contradicting sign. Observed close
    30/06: "… trong khi bán ròng +129 tỷ trong ngành Ngân hàng" — 'bán ròng'
    (net SELL) with a '+' figure. Neither prior guard catches this 'verb → number
    → name' order: enforce_money_flow_two_sides pins only the magnitude (leaves
    the verb/sign), and enforce_sector_nn_figures needs the name BEFORE the verb.

    For each ctx sector named right after a "(mua|bán) ròng <num> tỷ" figure whose
    magnitude matches that sector's |NN 1T| (≥30 tỷ; two_sides has already pinned
    the magnitude), set the verb from sign(NN) and re-emit an unsigned magnitude
    (the verb carries the direction). Idempotent; no-op without sector data.
    """
    sectors = ctx.get("sectors") or []
    rows = [(s.get("Ngành"), s.get("NN 1T (tỷ)")) for s in sectors
            if s.get("Ngành") and isinstance(s.get("NN 1T (tỷ)"), (int, float))]
    if not text or not rows:
        return text
    out = text
    for nm, vv in rows:
        if abs(vv) < 30:                       # skip noise / tiny flows
            continue
        want = "mua ròng" if vv > 0 else "bán ròng"

        def _fix(m: "_re.Match", _want=want, _v=vv) -> str:
            mag = _parse_vn_number(m.group(3))
            if mag is None or abs(mag - abs(_v)) > max(1.0, 0.02 * abs(_v)):
                return m.group(0)              # number isn't this sector's → skip
            return f"{_want}{m.group(2)}{abs(_v):,.0f}{m.group(4)}"

        out = _re.sub(
            rf"(mua\s+ròng|bán\s+ròng)(\s*)([+-]?\d[\d.,]*)"
            rf"(\s*tỷ(?:\s*đồng)?\s*(?:trong\s+ngành\s+)?{_re.escape(nm)}\b)",
            _fix, out)
    return out


def enforce_nn_frame_labels(text: str, ctx: dict) -> str:
    """Số NN ròng THEO NGÀNH là khung 1 TUẦN — khi model nêu nó KHÔNG nhãn
    khung, gắn "(1 tuần)" vào ngay sau để khỏi bị đọc thành số hôm nay.

    Close 23:58 14/07 ("Tổng kết phiên"): "Khối ngoại bán ròng 159 tỷ, NN ròng
    ngành Ngân hàng -1,032 tỷ" — 159 là NN 1 NGÀY toàn thị trường (khung mặc
    định của mục = hôm nay, đúng), còn -1,032 là NN 1 TUẦN của Ngân hàng; đặt
    cạnh nhau không nhãn khiến người đọc hiểu Ngân hàng bị bán 1,032 tỷ RIÊNG
    HÔM NAY (gấp ~6.5 lần tổng cả thị trường trong ngày — tự vô lý). Chạy SAU
    các guard pin số (giá trị đã đúng, đây chỉ gắn nhãn khung); match giá trị
    phải khớp |NN 1T| của đúng ngành; bỏ qua khi cùng dòng phía trước đã có
    "tuần"/"1T" (vd dòng canonical của two_sides). Idempotent.
    """
    sectors = ctx.get("sectors") or []
    rows = [(s.get("Ngành"), s.get("NN 1T (tỷ)")) for s in sectors
            if s.get("Ngành") and isinstance(s.get("NN 1T (tỷ)"), (int, float))
            and abs(s.get("NN 1T (tỷ)")) >= 30]
    if not text or not rows:
        return text
    out = text
    for nm, vv in rows:
        def _fix(m: "_re.Match", _vv=vv) -> str:
            val = _parse_vn_number(m.group(2))
            if val is None or abs(abs(val) - abs(_vv)) > max(1.0, 0.02 * abs(_vv)):
                return m.group(0)                      # số khác → không phải NN 1T
            # ngữ cảnh cùng dòng phía trước + NGAY SAU match đã có nhãn khung?
            ls = out.rfind("\n", 0, m.start()) + 1
            window = out[ls:m.end()].lower()
            after = out[m.end():m.end() + 12].lower()
            if "tuần" in window or "1t" in window or "tuần" in after:
                return m.group(0)
            # cần từ khóa "ròng" trong cùng mệnh đề (đây là số NN, không phải GTGD)
            if "ròng" not in window[-80:]:
                return m.group(0)
            return m.group(0) + " (1 tuần)"
        out = _re.sub(
            rf"({_re.escape(nm)}[^\n\d]{{0,18}}?)([-+]?\d[\d.,]*)\s*tỷ",
            lambda m, _f=_fix: _f(m), out)

        # Dạng SỐ-TRƯỚC-TÊN (close 01:10 15/07): "NN mua ròng 1,471 tỷ trong
        # ngành Họ VIN" — số đứng sau verb, tên đứng cuối → pattern trên trượt.
        def _fix_rev(m: "_re.Match", _vv=vv) -> str:
            val = _parse_vn_number(m.group(2))
            if val is None or abs(abs(val) - abs(_vv)) > max(1.0, 0.02 * abs(_vv)):
                return m.group(0)
            ls = out.rfind("\n", 0, m.start()) + 1
            window = out[ls:m.end()].lower()
            after = out[m.end():m.end() + 12].lower()
            if "tuần" in window or "1t" in window or "tuần" in after:
                return m.group(0)
            return m.group(0) + " (1 tuần)"
        out = _re.sub(
            rf"((?:mua|bán)\s+ròng\s*)([-+]?\d[\d.,]*)(\s*tỷ"
            rf"(?:(?!\.\s)[^;,\n]){{0,25}}?ngành\s*{_re.escape(nm)})",
            lambda m, _f=_fix_rev: _f(m), out)
    return out


def enforce_liquidity_label(text: str, ctx: dict) -> str:
    """A 'thanh khoản'/liquidity claim must never carry a NEGATIVE per-sector tỷ
    figure — those are NN net-sell flows mislabeled as turnover (observed 12:33:
    "Thanh khoản ngành tập trung vào Ngân hàng (-703 tỷ), Bất động sản (-307 tỷ),
    Chứng khoán (2,353 tỷ)" — -703/-307 are foreign net-sell, GTGD is never < 0).
    The prompt warns against this twice and the LLM still conflates the two, so
    chốt bằng code: a liquidity clause (no NN-side keyword) that holds a negative
    figure is replaced with the canonical top-GTGD sectors from ctx; falls back
    to stripping the bogus negative parentheticals when no GTGD data. No-op
    otherwise — idempotent (the canonical line carries no negative figure).
    """
    sectors = ctx.get("sectors") or []
    if not text or not sectors:
        return text
    gtgd = sorted(((s.get("Ngành"), s.get("GTGD TB (tỷ)")) for s in sectors
                   if s.get("Ngành")
                   and isinstance(s.get("GTGD TB (tỷ)"), (int, float))
                   and (s.get("GTGD TB (tỷ)") or 0) > 0),
                  key=lambda x: -x[1])[:3]
    canonical = ("Thanh khoản cao nhất (GTGD TB 1 tuần): "
                 + ", ".join(f"{n} {g:,.0f} tỷ" for n, g in gtgd)) if gtgd else ""

    _liq = ("thanh khoản", "giá trị giao dịch")
    _nn = ("bán ròng", "mua ròng", "nn ròng")
    _neg = _re.compile(r"-\d[\d.,]*\s*tỷ")
    changed = False
    out_lines: list[str] = []
    for ln in text.splitlines():
        low = ln.lower()
        if not any(k in low for k in _liq) or not _neg.search(ln):
            out_lines.append(ln)
            continue
        parts = _re.split(r"([.;])", ln)        # keep delimiters at odd indices
        for j in range(0, len(parts), 2):
            cl = parts[j]
            cll = cl.lower()
            if not any(k in cll for k in _liq):     # not a liquidity clause
                continue
            if any(k in cll for k in _nn):          # genuine NN clause — leave it
                continue
            if not _neg.search(cl):                 # already clean
                continue
            lead = cl[:len(cl) - len(cl.lstrip())]  # preserve clause's leading space
            if canonical:
                parts[j] = f"{lead}{canonical}"
            else:
                parts[j] = _re.sub(
                    r"\s*\(\s*(?:NN\s*|khối\s+ngoại\s*)?-\d[\d.,]*\s*tỷ\s*\)", "", cl)
            changed = True
        out_lines.append("".join(parts))
    return "\n".join(out_lines) if changed else text


def enforce_nn_window_label(text: str, ctx: dict | None = None) -> str:
    """A foreign-flow figure can't be both weekly AND one-day. The composite
    'NN ròng 1D' total (from the market-sentiment block) is a ONE-DAY net flow,
    but the LLM weaves it into the (weekly) money-flow narrative tagged 'tuần'
    (observed 12:42: "Khối ngoại bán ròng mạnh 665 tỷ tuần này (1D: -665 tỷ)" —
    which also understates the week: Ngân hàng alone is -703 tỷ/tuần).

    1) Self-contradiction (ctx-free, always safe): "<N tỷ> <tuần…> (1D…)" → drop
       the weekly tag — the model already labeled it 1D.
    2) The exact 1D magnitude from ctx tagged weekly with NO 1D marker → relabel
       to 1D. Skipped if a weekly sector value shares that magnitude (coincidence).
    """
    if not text:
        return text
    _wk = r"(?:trong\s+)?(?:tuần\s+này|tuần\s+qua|cả\s+tuần|1\s*tuần|tuần)"
    new = _re.sub(rf"(\d[\d.,]*\s*tỷ)\s*{_wk}(\s*\(\s*1D)", r"\1\2", text)

    ms = (ctx or {}).get("market_sentiment") or {}
    sig = next((s for s in ms.get("signals", [])
                if "1d" in str(s.get("name", "")).lower()
                and "nn" in str(s.get("name", "")).lower()), None)
    if sig:
        val = _parse_vn_number(
            str(sig.get("value", "")).replace("tỷ", "").replace("+", "").strip())
        if val is not None:
            mag = f"{abs(val):,.0f}"
            coincident = any(
                isinstance(s.get("NN 1T (tỷ)"), (int, float))
                and f"{abs(s['NN 1T (tỷ)']):,.0f}" == mag
                for s in ((ctx or {}).get("sectors") or []))
            if not coincident:
                new = _re.sub(
                    rf"({_re.escape(mag)}\s*tỷ)\s*{_wk}\b(?!\s*\(\s*1D)",
                    r"\1 (1D, phiên gần nhất)", new)
    return new


def _canonical_risk_lines(ctx: dict) -> list:
    """Build the fundamental-risk lines deterministically from ctx fundamentals:
    highest D/E (≥1.5, non-financial, top-3) and lowest negative Op.CF (top-2,
    BĐS-tagged + land-bank context). The single source of truth for the risk
    section's facts. Returns [] when there's no data / nothing noteworthy."""
    funds = ctx.get("vn30_fundamentals") or {}
    if not funds:
        return []
    fin = set(ctx.get("financial_tickers") or ()) | _FINANCIAL_TICKERS
    re_t = ctx.get("realestate_tickers") or set()
    nonfin = {t: m for t, m in funds.items() if t not in fin}
    des = sorted(((t, m["de"]) for t, m in nonfin.items()
                  if isinstance(m.get("de"), (int, float))), key=lambda x: -x[1])
    ocfs = sorted(((t, m["ocf"]) for t, m in nonfin.items()
                   if isinstance(m.get("ocf"), (int, float))), key=lambda x: x[1])
    out: list[str] = []
    high_de = [(t, v) for t, v in des if v >= 1.5][:3]   # only genuinely high leverage
    if high_de:
        body = ", ".join(f"{t} D/E={v:.2f}" for t, v in high_de)
        out.append(f"Đòn bẩy cao nhất (phi tài chính): {body} — "
                   f"{high_de[0][0]} cao nhất trong nhóm theo dõi.")
    neg_ocf = [(t, v) for t, v in ocfs if v < 0][:2]
    if neg_ocf:
        body = ", ".join(f"{t} Op.CF={v:,.0f} tỷ{' (BĐS)' if t in re_t else ''}"
                         for t, v in neg_ocf)
        out.append(f"Lưu chuyển tiền HĐKD thấp nhất: {body}.")
        if any(t in re_t for t, _ in neg_ocf):
            out.append("(Lưu ý: Op.CF âm của mã (BĐS) chủ yếu do tích lũy quỹ đất/hàng "
                       "tồn kho dự án — vốn lưu động, KHÔNG phải lỗ HĐKD; soi thêm D/E "
                       "và nợ vay.)")
    return out


def enforce_risk_section(text: str, ctx: dict) -> str:
    """Deterministic guard: replace the FUNDAMENTAL claims in 'Rủi ro cần lưu ý'
    with the canonical block from _canonical_risk_lines(ctx). The section had
    recurring wrong-metric / wrong-number / wrong-superlative / mis-pick /
    self-contradiction bugs from the LLM, none of which it actually needs to
    author — the facts are fully data-driven. Keeps the model's macro/technical
    narrative (lines naming no fundamentals ticker and no D/E/Op.CF), drops its
    fundamental lines, appends the canonical ones. No-op without fundamentals or
    a risk section, and never blanks the section.
    """
    funds = ctx.get("vn30_fundamentals") or {}
    if not text or not funds:
        return text
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "rủi ro cần lưu ý" in l.lower()), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))
    body = lines[start + 1:end]

    _fund_kw = ("d/e", "op.cf", "lưu chuyển tiền", "lưu lượng tiền", "hđkd",
                "đòn bẩy", "quỹ đất")

    def _is_fundamental(l: str) -> bool:
        low = l.lower()
        return (any(k in low for k in _fund_kw)
                or any(_re.search(rf"\b{_re.escape(t)}\b", l) for t in funds))

    macro = [l for l in body if l.strip() and not _is_fundamental(l)]
    new_body = macro + _canonical_risk_lines(ctx)
    if not new_body or new_body == body:
        return text
    return "\n".join(lines[:start + 1] + new_body + lines[end:])


def enforce_risk_numbers(text: str, ctx: dict) -> str:
    """Deterministic guard: every ticker named in the risk section must carry
    its CORRECT number. Two failure modes seen in the wild: (a) tickers cited
    with no figure at all (15:27: "HNG, PET, VTZ có D/E cao") → append a data
    line; (b) tickers cited with a WRONG figure (23:08: "KBC D/E=8.83" — 8.83
    is HNG's; "HPG D/E=1.55" vs real 0.65) → rewrite the number in place to the
    real value from ctx["vn30_fundamentals"]. No-op when clean / data missing.
    """
    funds = ctx.get("vn30_fundamentals") or {}
    if not text or not funds:
        return text

    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "rủi ro cần lưu ý" in l.lower()), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))

    # (b) Correct mismatched "TICKER … D/E=x" / "TICKER … Op.CF=y" in place.
    # The bridge [^.;,()]* keeps the match within the ticker's own clause (no
    # jumping across commas/parentheses to a neighbour's figure).
    def _correct_line(line: str) -> str:
        for t, m in funds.items():
            if not _re.search(rf"\b{_re.escape(t)}\b", line):
                continue
            de, ocf = m.get("de"), m.get("ocf")
            if de is not None:
                def _fix_de(mt, _de=de):
                    v = _parse_vn_number(mt.group(2))
                    return (mt.group(1) + f"{_de:.2f}"
                            if v is None or abs(v - _de) > max(0.01, 0.01 * abs(_de))
                            else mt.group(0))
                line = _re.sub(rf"(\b{_re.escape(t)}\b[^.;,()]*?D/E\s*=\s*)(\d[\d.,]*\d|\d)",
                               _fix_de, line)
            if ocf is not None:
                def _fix_ocf(mt, _ocf=ocf):
                    v = _parse_vn_number(mt.group(2))
                    return (mt.group(1) + f"{_ocf:,.0f}"
                            if v is None or abs(v - _ocf) > max(1.0, 0.01 * abs(_ocf))
                            else mt.group(0))
                line = _re.sub(
                    rf"(\b{_re.escape(t)}\b[^;,()]*?Op\.?CF\s*=\s*)(-?\d[\d.,]*\d|-?\d)",
                    _fix_ocf, line)
        return line

    changed = False
    for i in range(start + 1, end):
        new = _correct_line(lines[i])
        if new != lines[i]:
            lines[i] = new
            changed = True

    # (c) Mis-PICK: a ticker flagged for leverage whose real D/E is LOW (< 1.5 →
    # actually safe) while a genuinely high-leverage non-financial exists in the
    # block (observed 09:02: "HPG D/E=0.65 … rủi ro cơ bản" — 0.65 is not a
    # risk; HNG 8.83 was the real top). Swap "LOW D/E=x" → "TOP D/E=y" when the
    # top isn't already cited in the section.
    _fin = set(ctx.get("financial_tickers") or set()) | _FINANCIAL_TICKERS
    _nonfin_de = {t: m["de"] for t, m in funds.items()
                  if t not in _fin and isinstance(m.get("de"), (int, float))}
    if _nonfin_de:
        _top = max(_nonfin_de, key=_nonfin_de.get)
        _topv = _nonfin_de[_top]
        if _topv >= 2.5:
            for i in range(start + 1, end):
                if _re.search(rf"\b{_re.escape(_top)}\b", "\n".join(lines[start + 1:end])):
                    break
                for t, de in sorted(_nonfin_de.items(), key=lambda kv: kv[1]):
                    if de >= 1.5 or t == _top:
                        continue
                    m2 = _re.search(rf"(\b{_re.escape(t)}\b[^.;,()]*?D/E\s*=\s*)([\d.,]+)",
                                    lines[i])
                    if m2:
                        lines[i] = lines[i].replace(
                            m2.group(0), f"{_top}{m2.group(1)[len(t):]}{_topv:.2f}")
                        changed = True
                        break

        # (d) Wrong SUPERLATIVE: the section claims "D/E cao nhất" for a ticker
        # that isn't the real max, and the real max isn't cited (observed 11:19:
        # "PET và VTZ có D/E cao nhất 2.67/2.63" while HNG=8.83 was omitted).
        # Prepend the real top and demote the false "cao nhất" → "cao".
        _section = "\n".join(lines[start + 1:end])
        if (_topv >= 2.5 and "d/e" in _section.lower()
                and not _re.search(rf"\b{_re.escape(_top)}\b", _section)):
            for i in range(start + 1, end):
                low = lines[i].lower()
                if _re.search(r"d/e.{0,25}cao nhất|cao nhất.{0,25}d/e", low):
                    lines[i] = _re.sub(r"cao nhất", "cao", lines[i], count=1,
                                       flags=_re.IGNORECASE)
                    lines[i] = (f"{_top} D/E={_topv:.2f} (đòn bẩy cao nhất); "
                                + lines[i].lstrip())
                    changed = True
                    break

    def _has_value(line: str, v: float, fmt: str) -> bool:
        s = format(v, fmt)
        return s in line or s.replace(",", "X").replace(".", ",").replace("X", ".") in line

    missing: list[str] = []
    seen: set[str] = set()
    for line in lines[start + 1:end]:
        low = line.lower()
        _ocf_kw = ("op.cf", "lưu chuyển tiền", "lưu lượng tiền", "hđkd")

        def _wants_ocf(pos: int) -> bool:
            """Per-ticker metric: pick D/E vs OCF by the keyword in the ticker's
            OWN SENTENCE (bounded by '.'), so "HNG có D/E cao nhất, tiếp theo PET
            và VTZ. KBC có lưu chuyển tiền HĐKD thấp" gives PET/VTZ D/E (their
            sentence has D/E) and KBC OCF — not OCF for PET/VTZ just because the
            next sentence mentions it. Falls back to nearest-after within the
            line when the sentence has both/neither keyword."""
            # Sentence bounds via '.' followed by whitespace/end — so a decimal
            # point ("8.83") doesn't split the sentence and strip its D/E.
            ends = [m.start() for m in _re.finditer(r"\.(?=\s|$)", low)]
            s0 = next((e + 1 for e in reversed(ends) if e < pos), 0)
            s1 = next((e for e in ends if e >= pos), len(low))
            sent = low[s0:s1]
            has_de = "d/e" in sent
            has_ocf = any(w in sent for w in _ocf_kw)
            if has_ocf != has_de:                 # exactly one present in the sentence
                return has_ocf
            rest = low[pos:]                       # ambiguous → nearest keyword after pos
            de_at = rest.find("d/e")
            ocf_at = min((p for p in (rest.find(w) for w in _ocf_kw) if p != -1),
                         default=-1)
            if de_at == -1:
                return ocf_at != -1
            if ocf_at == -1:
                return False
            return ocf_at < de_at

        # ordered by position so each ticker's clause is read left-to-right
        cited = sorted((t for t in funds
                        if t not in seen and (m := _re.search(rf"\b{_re.escape(t)}\b", line))),
                       key=lambda t: _re.search(rf"\b{_re.escape(t)}\b", line).start())
        for t in cited:
            seen.add(t)
            de, ocf = funds[t].get("de"), funds[t].get("ocf")
            # satisfied if EITHER of the ticker's figures already sits on the line
            if (de is not None and _has_value(line, de, ".2f")) or (
                    ocf is not None and _has_value(line, ocf, ",.0f")):
                continue
            pos = _re.search(rf"\b{_re.escape(t)}\b", line).start()
            if _wants_ocf(pos) and ocf is not None:
                missing.append(f"{t} Op.CF={ocf:,.0f} tỷ")
            elif de is not None:
                missing.append(f"{t} D/E={de:.2f}")
            elif ocf is not None:
                missing.append(f"{t} Op.CF={ocf:,.0f} tỷ")
    if not missing:
        return "\n".join(lines) if changed else text
    note = "(Số liệu: " + " · ".join(missing) + " — từ block Cơ bản nhóm theo dõi.)"
    return "\n".join(lines[:end] + [note] + lines[end:])


_PIVOT_LABEL_RE = _re.compile(r"\b(S1|S2|R1|R2)\s*=\s*([0-9][0-9.,]*[0-9]|[0-9])")


def enforce_pivot_labels(text: str, ctx: dict) -> str:
    """Deterministic guard: pin every 'S1/S2/R1/R2=<số>' to its canonical
    VNINDEX pivot from ctx (observed 08:55: TLDR wrote 'thủng S1=1,799.18 →
    mục tiêu S2=1,799.18' — S1 collapsed onto S2's value, and contradicted the
    Trigger section's S1=1,802.42). ONLY rewrites numbers in the VNINDEX
    magnitude band (800-2500) so the watchlist's reuse of the same labels for
    per-stock levels (e.g. 'R1=71,500') is left untouched. No-op without pivots.
    """
    vt = ctx.get("vnindex_tech") or {}
    canon = {"S1": vt.get("support_1"), "S2": vt.get("support_2"),
             "R1": vt.get("resistance_1"), "R2": vt.get("resistance_2")}
    canon = {k: v for k, v in canon.items() if isinstance(v, (int, float))}
    if not text or not canon:
        return text

    def _sub(m: "_re.Match") -> str:
        label, num = m.group(1), m.group(2)
        v = canon.get(label)
        parsed = _parse_vn_number(num)
        if v is None or parsed is None or not (800 <= parsed <= 2500):
            return m.group(0)                 # not an index-level token → leave it
        return f"{label}={v:,.2f}"

    return _PIVOT_LABEL_RE.sub(_sub, text)


# (_SR_MAX_MOVE_PCT — trần khoảng cách vai/mục tiêu S/R — định nghĩa cạnh
# _SR_MIN_DIST_PCT/_SR_MIN_GAP_PCT phía trên _select_sr_levels.)


def enforce_sr_direction(text: str, ctx: dict) -> str:
    """Sanity CHIỀU cho mức S/R: hỗ trợ (S1/S2) phải NẰM DƯỚI giá đóng cửa,
    kháng cự (R1/R2) phải NẰM TRÊN. Token sai chiều → pin về mức KNOWN hợp lệ
    gần nhất của ctx (không bịa mức mới).

    Close 15/07: setup "thủng S1=1,445.64 → mục tiêu S2=1,782.12" — S2=1,782.12
    ĐÚNG BẰNG giá đóng cửa (hỗ trợ = giá hiện tại, vô nghĩa). Gốc: support_1/
    support_2 trong ctx = None (giá ở đáy range, không có swing-low actionable)
    nên enforce_pivot_labels bỏ qua (canon rỗng) và LLM để lại số bịa. Guard
    này chạy SAU pivot_labels: chỉ đụng token SAI CHIỀU (S ≥ close hoặc R ≤
    close) trong dải chỉ số 800-2500, pin về mức known đúng phía gần nhất
    (close/MA/support/resistance/tuần/tháng/52w). Idempotent (pin xong đúng
    chiều → không tái kích). No-op khi thiếu close / không có mức known đúng phía.
    """
    vt = ctx.get("vnindex_tech") or {}
    close = vt.get("close")
    if not text or not isinstance(close, (int, float)):
        return text
    known = [vt.get(k) for k in (
        "ma20", "ma50", "ma200", "support_1", "support_2",
        "resistance_1", "resistance_2", "week_high", "week_low",
        "month_high", "month_low", "high_52w", "low_52w")]
    known = [k for k in known if isinstance(k, (int, float)) and 800 <= k <= 2500]
    below = [k for k in known if k < close]      # ứng viên hỗ trợ (dưới giá)
    above = [k for k in known if k > close]      # ứng viên kháng cự (trên giá)

    def _sub(m: "_re.Match") -> str:
        label, num = m.group(1), m.group(2)
        v = _parse_vn_number(num)
        if v is None or not (800 <= v <= 2500):
            return m.group(0)
        is_support = label.startswith("S")
        wrong = (is_support and v >= close) or ((not is_support) and v <= close)
        if not wrong:
            return m.group(0)
        cands = below if is_support else above
        if not cands:
            return m.group(0)                    # không có mức đúng phía để pin
        nk = min(cands, key=lambda k: abs(k - v))
        return f"{label}={nk:,.2f}"

    out = _PIVOT_LABEL_RE.sub(_sub, text)
    # XẾP LẠI VAI khi ngược thứ tự (user bắt 17/07, close 15:33): "thủng
    # S1=1,445.64 → mục tiêu S2=1,774.22" — thủng mức SÂU mà mục tiêu CAO HƠN
    # là phi logic. Quy ước: S1 = hỗ trợ GẦN giá nhất (cao hơn S2), R1 = kháng
    # cự gần nhất (thấp hơn R2). Cả 2 vai cùng dải chỉ số + mỗi vai đúng 1 giá
    # trị + thứ tự ngược → HOÁN ĐỔI số giữa 2 vai (mức vẫn là mức THẬT đã pin,
    # chỉ đổi nhãn vai). Idempotent: sau swap thứ tự đúng → không tái kích.
    for one, two, support in (("S1", "S2", True), ("R1", "R2", False)):
        ones = {m.group(1) for m in _re.finditer(rf"\b{one}=([\d.,]+)", out)}
        twos = {m.group(1) for m in _re.finditer(rf"\b{two}=([\d.,]+)", out)}
        if len(ones) != 1 or len(twos) != 1:
            continue                                 # nhiều giá trị/vai → không đoán
        a, b = ones.pop(), twos.pop()
        va, vb = _parse_vn_number(a), _parse_vn_number(b)
        if va is None or vb is None or not all(800 <= v <= 2500 for v in (va, vb)):
            continue
        if (va < vb) if support else (va > vb):      # S1 sâu hơn S2 / R1 xa hơn R2
            out = _re.sub(rf"\b{one}={_re.escape(a)}(?![\d])", f"{one}={b}", out)
            out = _re.sub(rf"\b{two}={_re.escape(b)}(?![\d])", f"{two}={a}", out)
    # VAI 2 = mức known KẾ TIẾP sau vai 1, TRONG TẦM biên độ (user bắt lần 2
    # 17/07: sau swap vẫn còn "thủng S1=1,774.22 → mục tiêu S2=1,445.64" —
    # mục tiêu cách giá ~19% vô nghĩa khi biên độ ngày ~7%, giữa đường còn
    # MA200/đáy tháng là mốc THẬT trong ctx). CHỈ can thiệp khi ctx KHÔNG có
    # canon cho vai 2 (support_2/resistance_2 — có canon thì enforce_pivot_labels
    # là chủ sở hữu). Không còn mức nào trong tầm → CẮT vế mục tiêu thay vì
    # giữ mục tiêu xa. Idempotent (pin xong v2 = expected / cắt xong hết token).
    for one, two, support in (("S1", "S2", True), ("R1", "R2", False)):
        canon2 = vt.get("support_2" if support else "resistance_2")
        if isinstance(canon2, (int, float)) and 800 <= canon2 <= 2500:
            continue
        ones = {m.group(1) for m in _re.finditer(rf"\b{one}=([\d.,]+)", out)}
        twos = {m.group(1) for m in _re.finditer(rf"\b{two}=([\d.,]+)", out)}
        if len(ones) != 1 or len(twos) != 1:
            continue
        a, b = ones.pop(), twos.pop()
        v1, v2 = _parse_vn_number(a), _parse_vn_number(b)
        if v1 is None or v2 is None or not all(800 <= v <= 2500 for v in (v1, v2)):
            continue
        side = below if support else above
        cands = [k for k in side
                 if ((k < v1 - 0.5) if support else (k > v1 + 0.5))]
        reach = [k for k in cands
                 if abs(k - close) / close <= _SR_MAX_MOVE_PCT]
        expected = (max(reach) if support else min(reach)) if reach else None
        if expected is None:
            if abs(v2 - close) / close > _SR_MAX_MOVE_PCT:
                out = _re.sub(                        # mục tiêu ngoài tầm → cắt vế
                    rf"\s*(?:→|->)\s*(?:mục tiêu|về|test|hướng)?\s*{two}={_re.escape(b)}(?![\d])",
                    "", out)
            continue
        if abs(v2 - expected) > 2.7:                  # chưa phải mức kế tiếp → pin
            out = _re.sub(rf"\b{two}={_re.escape(b)}(?![\d])",
                          f"{two}={expected:,.2f}", out)
    # Dedupe VAI TRÙNG MỨC (close 17/07): giá ở đáy 52w → cả S1 lẫn S2 pin về
    # cùng low_52w ra câu vô nghĩa "thủng S1=1,445.64 → mục tiêu S2=1,445.64".
    # Cùng số ở 2 vai → cắt mệnh đề mũi-tên của vai 2 (S2/R2) thừa; cặp khác
    # số không đụng. Idempotent (cắt xong hết token trùng để tái kích).
    for one, two in (("S1", "S2"), ("R1", "R2")):
        vals = {m.group(1) for m in _re.finditer(rf"\b{one}=([\d.,]+)", out)}
        for num in vals:
            out = _re.sub(
                rf"\s*(?:→|->)\s*(?:mục tiêu|về|test|hướng)?\s*{two}={_re.escape(num)}(?![\d])",
                "", out)
    return out


def enforce_scenario_levels(text: str, ctx: dict) -> str:
    """Pin a fabricated precise VNINDEX level to the nearest real data level.

    Observed morning 14:28: the recovery scenario cited "đóng cửa trên 1,801.99
    (đáy phiên)" — 1,801.99 matches no pivot/close/MA, and labelling it the
    session LOW is impossible (it's ABOVE the close 1,798.61). The template says
    scenario levels must come from the data block.

    Strict-but-safe: only PRECISE 2-decimal index-band tokens (1,xxx.xx in
    800-2500) are considered, and only when they match NONE of the real ctx
    levels (close, MA20/50/200, S1/S2/R1/R2, week/month/52w hi-lo) within ~2.7pt.
    Pivots/close/MAs are recognised → left as-is; round/approximate targets
    ("dưới 1,790", "quanh 1,795-1,805") have no 2-decimals → never touched. A
    matched fabrication is pinned to the nearest real level; a session-extreme
    label that then contradicts the close (đáy ≥ close / đỉnh ≤ close) is dropped.
    Idempotent; no-op without ctx levels.
    """
    vt = ctx.get("vnindex_tech") or {}
    close = vt.get("close")
    known = [vt.get(k) for k in (
        "close", "ma20", "ma50", "ma200", "support_1", "support_2",
        "resistance_1", "resistance_2", "week_high", "week_low",
        "month_high", "month_low", "high_52w", "low_52w")]
    known = [k for k in known if isinstance(k, (int, float)) and 800 <= k <= 2500]
    if not text or not known:
        return text

    def _pin(m: "_re.Match") -> str:
        v = _parse_vn_number(m.group(0))
        if v is None or not (800 <= v <= 2500):
            return m.group(0)
        nk = min(known, key=lambda k: abs(k - v))
        return m.group(0) if abs(v - nk) <= max(2.0, 0.0015 * v) else f"{nk:,.2f}"
    out = _re.sub(r"\b[12],\d{3}\.\d{2}\b", _pin, text)

    if isinstance(close, (int, float)):
        def _lbl(m: "_re.Match") -> str:
            v = _parse_vn_number(m.group(1))
            kind = m.group(2).lower()
            if v is None:
                return m.group(0)
            low = "đáy" in kind or "thấp" in kind
            high = "đỉnh" in kind or "cao" in kind
            if (low and v >= close) or (high and v <= close):
                return m.group(1)            # drop the contradictory extreme label
            return m.group(0)
        out = _re.sub(
            r"([12],\d{3}\.\d{2})\s*\((đáy phiên|đỉnh phiên|thấp nhất phiên|cao nhất phiên)\)",
            _lbl, out)
    return out


def enforce_watchlist_eligibility(text: str, ctx: dict) -> str:
    """Deterministic guard: drop watchlist setups whose ticker is a low-liquidity
    mover (NOT VN30 and avg GTGD < _WATCHLIST_GTGD_MIN_TY). The ⭐ marker is only
    a prompt hint, so a non-⭐ mover still leaked into a setup. Only removes
    tickers we have explicit
    sub-threshold GTGD evidence for; renumbers the rest; falls back to the bail
    line when nothing eligible remains. No-op without mover data.
    """
    movers = (ctx.get("vn30_gainers") or []) + (ctx.get("vn30_losers") or [])
    if not text or not movers:
        return text
    ineligible: set[str] = set()
    for m in movers:
        t = str(m.get("Mã", "")).upper()
        g = m.get("GTGD TB (tỷ)")
        if (t and t not in VN30_TICKERS and isinstance(g, (int, float))
                and not (isinstance(g, float) and g != g)
                and float(g) < _WATCHLIST_GTGD_MIN_TY):
            ineligible.add(t)
    if not ineligible:
        return text

    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if "watchlist sáng mai" in l.lower()), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))

    kept, dropped = [], False
    for l in lines[start + 1:end]:
        mt = _re.search(r"\*\*([A-Z]{3})\*\*", l) or _re.search(r"\b([A-Z]{3})\b\s*\(Giá", l)
        if mt and mt.group(1) in ineligible:
            dropped = True
            continue
        kept.append(l)
    if not dropped:
        return text

    # renumber surviving "N." setup lines; bail line if none survive
    has_setup = any(_re.match(r"\s*\d+\.", l) for l in kept)
    if not has_setup:
        kept = [l for l in kept if not _re.match(r"\s*\d+\.", l)]
        kept.append("Cần thêm dữ liệu giá cổ phiếu cụ thể")
    else:
        n = 0
        out = []
        for l in kept:
            if _re.match(r"\s*\d+\.", l):
                n += 1
                out.append(_re.sub(r"^\s*\d+\.", f"{n}.", l))
            else:
                out.append(l)
        kept = out
    return "\n".join(lines[:start + 1] + kept + lines[end:])


# Canonical caveat appended to the "Đề xuất giao dịch" section when BUY recs
# collide with a GIẢM bias floor. Kept as a module constant so the guard can do
# an exact-substring idempotency check (avoids unicode-normalization mismatches
# that .lower()-comparing two hand-typed diacritic strings would hit).
_BUY_BIAS_CAVEAT = (
    "⚠️ Các lệnh MUA trên là tín hiệu backtest TỪNG MÃ; bối cảnh chung đang "
    "GIẢM → vào lệnh thận trọng, tôn trọng cắt lỗ (SL), cân nhắc giảm tỷ trọng."
)


def enforce_buy_vs_bias_caveat(text: str, ctx: dict) -> str:
    """Deterministic guard: when the bias floor is GIẢM (bearish market) yet the
    "💡 Đề xuất giao dịch" section still lists BUY/MUA setups (from the backtested-
    strategy recs), append a one-line caveat reminding the reader these are
    PER-TICKER backtest signals to weigh against the bearish backdrop — enter
    cautiously, respect SL, consider trimming size.

    The recs are KEPT, not filtered: each carries its own stop-loss (defined risk),
    so we add context instead of hiding the signal — mirroring the BĐS Op.CF
    "context, don't drop" choice. Fires only when bias=GIẢM and a buy-side line is
    present in that section (SELL-only recs under GIẢM are already consistent).
    Idempotent; no-op without the floor / section / a buy line.
    """
    if not text or (ctx or {}).get("bias_floor", {}).get("dir") != "GIẢM":
        return text
    # Idempotent: the caveat starts with ⚠️ (a section emoji), so once inserted
    # it reads as a section boundary on re-parse — check the whole text, not the
    # bounded section body, or the second pass would append a duplicate.
    if _BUY_BIAS_CAVEAT in text:
        return text

    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "đề xuất giao dịch" in l.lower() and _is_section_start(l)), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))
    body = lines[start + 1:end]

    # A buy-side rec line carries a BUY/MUA action (the backtest action is "BUY";
    # the LLM may translate to "MUA"). A purely conditional "canh MUA NẾU vượt"
    # is already bias-aware (the watchlist guard rewrites unconditional dip-buys),
    # so it doesn't count as the contradiction we're flagging.
    def _is_buy_line(l: str) -> bool:
        low = l.lower()
        if "canh mua nếu" in low:
            return False
        return bool(_re.search(r"\b(buy|mua)\b", low))

    if not any(_is_buy_line(l) for l in body):
        return text

    # Insert right after the section's last non-blank content line so the caveat
    # sits under the recs (not after a trailing gap before the next section).
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    return "\n".join(lines[:insert_at] + [_BUY_BIAS_CAVEAT] + lines[insert_at:])


# "Tiêu cực" zone for the soft stance caution. The hard GIẢM floor (_bias_floor_dir)
# fires at momentum ≤ -50; this softer band (≤ -20) only adds a caveat, never
# overrides the stance. _STANCE_CAUTION_MARK doubles as the idempotency marker.
_STANCE_CAUTION_MOMENTUM = -20
_STANCE_CAUTION_MARK = "tâm lý thị trường đang TIÊU CỰC"


def enforce_stance_sentiment_caution(text: str, ctx: dict) -> str:
    """Soft guard: when the TLDR Stance/Bias leans TĂNG but market sentiment is
    moderately-or-more negative (momentum ≤ _STANCE_CAUTION_MOMENTUM, i.e. below
    the hard GIẢM floor at ≤ -50), append a one-line caution under the stance.

    Observed close 30/06: "Stance ngày mai: TĂNG" while sentiment was "📉 Tiêu cực
    (momentum -24)". -24 doesn't trip the hard floor, so the bullish lean is
    allowed — but we flag the tension (manage risk, add only on confirmation,
    respect SL) instead of overriding it (mirrors the BUY-vs-bias caveat:
    contextualize, don't force). Applies to both briefs (close "Stance ngày mai",
    morning "Bias"). Idempotent; no-op on a GIẢM/TRUNG TÍNH stance or when
    sentiment isn't negative enough.
    """
    sent = ctx.get("market_sentiment") or {}
    mom = sent.get("momentum")
    if (not text or not isinstance(mom, (int, float))
            or mom > _STANCE_CAUTION_MOMENTUM or _STANCE_CAUTION_MARK in text):
        return text

    lines = text.splitlines()
    stance_i = None
    for i, l in enumerate(lines):
        m = _re.search(r"(?:stance(?:\s+ngày\s+mai)?|bias)\s*[:：]\**\s*([^\s.]+)",
                       l, _re.IGNORECASE)
        if not m:
            continue
        tok = m.group(1).lower()
        if tok.startswith("tăng"):
            stance_i = i
            break
        if tok.startswith("giảm") or tok.startswith("trung"):
            return text                       # stance already bearish/neutral
    if stance_i is None:
        return text

    caveat = (f"⚠️ Stance nghiêng TĂNG nhưng {_STANCE_CAUTION_MARK} "
              f"(momentum {int(mom)}/100) — ưu tiên quản trị rủi ro, chỉ gia tăng "
              f"tỷ trọng khi giá XÁC NHẬN (vượt kháng cự), tôn trọng cắt lỗ.")
    return "\n".join(lines[:stance_i + 1] + [caveat] + lines[stance_i + 1:])


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


def enforce_number_format(text: str, ctx: dict | None = None) -> str:
    """Normalise Vietnamese-format numbers to the EN format the data block,
    guards and close brief use (comma = thousands, dot = decimal). The templates'
    examples used VN format ("1.815,42"), so the model reformatted some numbers
    to VN (1.798,61, 9.129,4, 1.858,39, -3,2%) while leaving guard/GTGD numbers EN
    (5,233.3, 1,789.31) — one brief, two conventions (observed morning 13:54).
    Convert only UNAMBIGUOUS VN tokens: thousands+decimal (dot-grouped, comma
    decimal), dot-grouped thousands immediately before tỷ/tỉ, and comma-decimal
    percentages. EN numbers, 3-decimal pp values, ratios (0.87) and ISO dates are
    left untouched; idempotent. No-op when already consistent.
    """
    if not text:
        return text

    def _vn_dec(m: "_re.Match") -> str:        # "1.798,61" → "1,798.61"
        intp, dec = m.group(0).split(",")
        return f"{int(intp.replace('.', '')):,}.{dec}"
    out = _re.sub(r"\d{1,3}(?:\.\d{3})+,\d+", _vn_dec, text)

    def _vn_th(m: "_re.Match") -> str:         # "5.038 tỷ" → "5,038 tỷ"
        return f"{int(m.group(1).replace('.', '')):,}{m.group(2)}"
    out = _re.sub(r"(\d{1,3}(?:\.\d{3})+)(\s*(?:tỷ|tỉ))", _vn_th, out)

    out = _re.sub(r"([+-]?\d+),(\d{1,2})%", r"\1.\2%", out)   # "-3,2%" → "-3.2%"
    return out


def enforce_range_position(text: str, ctx: dict) -> str:
    """Deterministic guard: the close brief's "Vị trí trong range" line must
    carry the computed % (observed 11:03: "Gần đáy range tuần" with no number,
    while 10:53 had "27%"). Insert the % — (close−week_low)/(week_high−week_low)
    — when the line lacks one. No-op without weekly range data or already %-ed.
    """
    vt = ctx.get("vnindex_tech") or {}
    wl, wh, cl = vt.get("week_low"), vt.get("week_high"), vt.get("close")
    if (not text or not all(isinstance(x, (int, float)) for x in (wl, wh, cl))
            or wh <= wl):
        return text
    pos = (cl - wl) / (wh - wl) * 100
    out, done = [], False
    for l in text.splitlines():
        if not done and "vị trí trong range" in l.lower() and "%" not in l:
            l = _re.sub(r"(vị trí trong range\s*:?\s*\**\s*)",
                        lambda m: f"{m.group(1)}{pos:.0f}% — ", l,
                        count=1, flags=_re.IGNORECASE)
            done = True
        out.append(l)
    return "\n".join(out) if done else text


# Keyword-anchored GTGD figure: the thousands-magnitude number (+ optional unit)
# right after a GTGD/turnover phrase — anchored so it never grabs the VNINDEX
# level on the same line. Groups: (1) keyword, (2) filler, (3) number, (4) unit.
_GTGD_CTX_RE = _re.compile(
    r"(GTGD|giá trị giao dịch)(\D{0,15}?)(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?)(\s*tỷ(?:\s*đồng)?)?",
    _re.IGNORECASE,
)


def enforce_gtgd_total(text: str, ctx: dict) -> str:
    """Deterministic guard for the GTGD figure in the brief's headline sections.
    Canonical full-day GTGD = live session capture (9h-15h) if present, else the
    EOD-derived total ctx["full_day_gtgd"] (Σ giá×KLGD) so EOD-only days still
    get a real number. PIN the cited figure to it (observed two runs on the SAME
    10/06 data citing 5,153 vs 14,118 tỷ); STRIP to "chưa có dữ liệu" when no
    canonical exists (observed 9.650,4 leak). Close uses full-day in "Kết quả
    phiên"/"Tổng kết phiên"; morning uses the session 9h-11h30 figure in "Tổng
    quan phiên sáng" (morning split is NOT derivable from EOD). Per-sector GTGD
    numbers elsewhere are never touched.
    """
    ss = ctx.get("session_stats") or {}
    try:
        eod_full = float(ctx["full_day_gtgd"]) if ctx.get("full_day_gtgd") else None
    except (TypeError, ValueError):
        eod_full = None
    if not text or (not ss and not eod_full):
        return text

    def _g(window):
        v = (ss.get(window, {}).get("VNINDEX", {}) or {}).get("gtgd")
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    morn = _g("9h-11h30")
    # Cùng khung với build_prompt/guard % (fix 21/07): capture nửa phiên không
    # còn đóng vai số cả ngày; ưu tiên WSS hợp lệ, fallback EOD.
    close_canon, _, _ = _gtgd_close_frame(ctx)
    intraday = bool((ctx.get("vnindex_tech") or {}).get("intraday"))

    lines = text.splitlines()
    sec = None
    changed = False
    for i, l in enumerate(lines):
        low = l.lower()
        if _is_section_start(l):
            sec = ("close" if "tổng kết phiên" in low
                   else "morning" if "tổng quan phiên sáng" in low else None)
        if sec == "close" or "kết quả phiên" in low:
            canonical, active = close_canon, (not intraday)
        elif sec == "morning":
            canonical, active = morn, True
        else:
            continue
        if not active or not _GTGD_CTX_RE.search(l):
            continue
        if canonical and canonical > 0:
            new = _GTGD_CTX_RE.sub(
                lambda m: f"{m.group(1)}{m.group(2)}{canonical:,.1f}{m.group(4) or ' tỷ'}", l)
        else:                                     # known-zero/missing → strip the fabrication
            new = _GTGD_CTX_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}chưa có dữ liệu", l)
        if new != l:
            lines[i] = new
            changed = True
    return "\n".join(lines) if changed else text


# A GTGD comparison against MORNING baselines (sáng-với-sáng) — a percentage
# tied to "sáng phiên trước"/"TB sáng"/"sáng N phiên". Matches up to the end of
# the sentence, allowing decimals inside numbers (period+space ends it, not the
# decimal point). Group 1 = the leading comma/space to preserve.
_MORNING_CMP_RE = _re.compile(
    # Mệnh đề so sánh phải MỞ ĐẦU bằng động-từ-so-sánh + % HOẶC % + "so/vs"
    # (một trong hai bắt buộc — "so" đơn thuần optional sẽ nuốt nhầm từ
    # "57% GTGD (15,513.6 tỷ)," đứng trước). Close 01:20 15/07: "cao hơn 35%
    # phiên trước (10,294.2 tỷ) và 23% trung bình 5 phiên sáng" — không có
    # "so" nào + baseline sáng dạng mới "trung bình N phiên sáng" (chữ
    # "sáng" đứng CUỐI).
    r"(,?\s*)(?:(?:thấp hơn|cao hơn|giảm|tăng)\s*\d[\d.,]*\s*%"
    r"|\d[\d.,]*\s*%\s*(?:so\b|vs\.?))\s*(?:so\b|vs\.?)?.*?"
    r"(?:sáng phiên trước|TB\s*sáng|sáng\s+\d+\s+phiên"
    r"|trung bình\s+\d+\s+phiên\s+sáng|\d+\s+phiên\s+sáng).*?(?=\.\s|\.$|$)",
    _re.IGNORECASE)

# Dạng NHÃN-TRƯỚC-%-SAU (close 23:18 20/07): "cao hơn TB sáng 5 phiên (+42%)
# nhưng cao hơn TB cả ngày (+53%)" — verb đứng TRƯỚC baseline, % nằm TRONG
# NGOẶC ở cuối → _MORNING_CMP_RE (đòi mở đầu verb+% hoặc %+so/vs) trượt, còn
# enforce_gtgd_baseline_pct Form 2 cố ý bỏ baseline có "sáng" → cả chuỗi sống
# sót nguyên vẹn. Bắt CHUỖI 1-3 mệnh đề "verb + TB/trung bình … (±N%)" nối
# bằng nhưng/và/phẩy để thay TRỌN chuỗi một lần (vế còn lại thường là nhãn mơ
# hồ "TB cả ngày" — cũng về canonical TB5/TB20 luôn).
_MORNING_LABEL_CLAUSE = (
    r"(?:cao hơn|thấp hơn|so với|ngang)\s+(?:TB|trung bình)"
    r"[^,;.()%]{0,30}\(\s*[+-]?[\d.,]+\s*%\s*\)"
)
_MORNING_LABEL_CMP_RE = _re.compile(
    _MORNING_LABEL_CLAUSE
    + r"(?:\s*(?:nhưng|và|,)\s*" + _MORNING_LABEL_CLAUSE + r"){0,2}",
    _re.IGNORECASE)

# Chủ ngữ hợp lệ của chuỗi so sánh GTGD dạng nhãn-trước-%-sau: câu về chủ
# thể KHÁC (khối ngoại, tự doanh…) có cùng bề mặt "cao hơn TB sáng … (+N%)"
# KHÔNG được viết lại bằng số GTGD (review 21/07 — _MORNING_LABEL_CMP_RE
# không tự anchor chủ ngữ). Soi trong phạm vi CÂU chứa chuỗi (sau ". "/"; ").
_GTGD_SUBJECT_RE = _re.compile(
    r"GTGD|giá trị giao dịch|thanh khoản|khớp lệnh", _re.IGNORECASE)


def enforce_gtgd_compare_frame(text: str, ctx: dict) -> str:
    """In the CLOSE 'Tổng kết phiên', the full-day GTGD figure must be compared
    full-day-vs-full-day, never against morning baselines (the Session Timing
    block hands the close BOTH frames and warns against mixing). Observed 13:00:
    "GTGD (11,929.2 tỷ), thấp hơn 43% so sáng phiên trước (9,129.4 tỷ) và 34% so
    TB sáng 5 phiên (7,959.6 tỷ)" — a full-day number against morning baselines,
    with an impossible direction (11,929 > 9,129). Replace the morning-baseline
    comparison in the close summary with the canonical full-day comparison
    (TB5/TB20 phiên) from ctx. No-op without the full-day cmp or the bad pattern.
    """
    # F + baselines CÙNG KHUNG qua _gtgd_close_frame (fix 21/07 — trước đây
    # luôn lấy khung EOD kể cả khi số hiển thị là capture WSS).
    F, cmp, _frame = _gtgd_close_frame(ctx)
    if not text or not F or not (cmp.get("avg5") or cmp.get("avg20")):
        return text
    p5 = (F / cmp["avg5"] - 1) * 100 if cmp.get("avg5") else None
    p20 = (F / cmp["avg20"] - 1) * 100 if cmp.get("avg20") else None
    parts = [f"{lbl} ({p:+.0f}%)" for lbl, p in
             (("TB5 phiên", p5), ("TB20 phiên", p20)) if p is not None]
    if not parts:
        return text
    pcts = [p for p in (p5, p20) if p is not None]
    verb = ("thấp hơn" if all(p < 0 for p in pcts)
            else "cao hơn" if all(p > 0 for p in pcts) else "so với")
    canonical = f"{verb} {' và '.join(parts)}"

    lines = text.splitlines()
    sec = None
    changed = False
    for i, l in enumerate(lines):
        if _is_section_start(l):
            sec = "close" if "tổng kết phiên" in l.lower() else None
            continue
        if sec != "close":
            continue
        new = _MORNING_CMP_RE.sub(lambda m: f"{m.group(1)}{canonical}", l, count=1)
        if new == l:
            # Dạng nhãn-trước-%-sau (20/07 23:18) — thay CẢ CHUỖI mệnh đề
            # khi có ≥1 baseline "sáng" (chuỗi +42% vs TB sáng và +53% vs
            # TB cả ngày còn VÔ LÝ NỘI TẠI: TB sáng > TB cả ngày là bất
            # khả — sáng là tập con của cả ngày). Chủ ngữ là GTGD SÁNG
            # (chữ "sáng" đứng TRƯỚC chuỗi trên dòng) → so sáng-với-sáng
            # HỢP LỆ, không đụng. CÂU chứa chuỗi phải nói về GTGD/thanh
            # khoản — chủ ngữ khác (khối ngoại, tự doanh…) cùng bề mặt thì
            # không thay (review 21/07). Canonical không chứa "sáng" và
            # câu đã thay vẫn giữ chủ ngữ GTGD → idempotent.
            def _lbl_repl(m: "_re.Match", _line: str = l) -> str:
                seg = m.group(0)
                if "sáng" not in seg.lower():
                    return seg
                prefix = _line[: m.start()]
                if "sáng" in prefix.lower():
                    return seg
                if not _GTGD_SUBJECT_RE.search(_re.split(r"[.;]\s", prefix)[-1]):
                    return seg
                return canonical
            new = _MORNING_LABEL_CMP_RE.sub(_lbl_repl, l)
        if new != l:
            lines[i] = new
            changed = True
    return "\n".join(lines) if changed else text


def enforce_gtgd_baseline_pct(text: str, ctx: dict) -> str:
    """In the CLOSE GTGD comparison, each % must match ITS baseline, in BOTH
    surface forms. Observed 12/06:
      • Form 1 "±N% vs/so <baseline>" (Tổng kết) — "(+4% vs TB5 phiên, +43% vs
        phiên trước)" had the % shifted onto the wrong baselines.
      • Form 2 "<baseline> (±N%)" (TLDR) — "cao hơn trung bình 5 phiên (+43%)"
        kept a stale/fabricated % while the pinned Tổng kết said +21% → the SAME
        brief contradicted itself on the TB5 figure.
    Pin every "% ↔ baseline" pairing (both orders) to the value computed from ctx
    full_day_gtgd_cmp (avg5/avg20/prev) so the TLDR and Tổng kết agree. Close-only
    (gated on "Tổng kết phiên"); morning sáng baselines are skipped; idempotent;
    no-op without cmp. A baseline with no cmp value (e.g. TB20 when <15 prior
    days) is left untouched here — it has no figure to pin to.
    """
    if not text or "tổng kết phiên" not in text.lower():
        return text
    # F + baselines CÙNG KHUNG qua _gtgd_close_frame (fix 21/07 — % pin phải
    # cùng khung với số GTGD mà enforce_gtgd_total đã chốt).
    F, cmp, _frame = _gtgd_close_frame(ctx)
    if not F or not cmp:
        # Form 3 (tự-chứa, không cần ctx): "N% so <base> (A tỷ vs B tỷ)" —
        # model tự ghi CẢ 2 vế thì % phải khớp (A/B − 1)×100. Close 14/07:
        # "giảm 29% so phiên trước (15,513.6 tỷ vs 19,751.0 tỷ)" trong khi
        # 15,513.6/19,751 − 1 = −21% — ctx thiếu F/cmp nên Form 1 bó tay.
        # CHỈ chạy khi ctx thiếu (ctx là nguồn chân lý khi có — tránh operand
        # bịa trong ngoặc override số đã pin từ ctx).
        def _fix3(m: "_re.Match") -> str:
            a = _parse_vn_number(m.group(3))
            b = _parse_vn_number(m.group(4))
            cur = _parse_vn_number(m.group(1))
            if not a or not b or b <= 0 or cur is None:
                return m.group(0)
            correct = (a / b - 1) * 100
            return (m.group(0) if abs(cur - correct) <= 1
                    else f"{correct:+.0f}{m.group(2)}")
        return _re.sub(
            r"([+-]?\d[\d.,]*)(\s*%\s*(?:vs|so với|so)\s+[^(,.\n]{0,30}"
            r"\(\s*([\d.,]+)\s*tỷ\s+vs\.?\s+([\d.,]+)\s*tỷ\s*\))",
            _fix3, text)

    def _base_v(base_low: str) -> "float | None":
        # Require an explicit GTGD-baseline phrase ("TB"/"trung bình"/"phiên
        # trước"). Matching bare substrings "20"/"5"/"trước" mis-read a DATE on
        # the tỷ giá line ("…% so với 2026-06-15" — "2026-06-15" contains "20")
        # as TB20 and overwrote the FX change with the GTGD-vs-TB20 % (close
        # 16/06: -0.07% → -3%). Skip morning baselines.
        if "sáng" in base_low:
            return None
        if "tb" in base_low or "trung bình" in base_low:
            return (cmp.get("avg20") if "20" in base_low
                    else cmp.get("avg5") if "5" in base_low else None)
        if "phiên trước" in base_low:
            return cmp.get("prev")
        return None

    # Form 1: "±N% vs/so <baseline>"  (number precedes the baseline)
    def _fix1(m: "_re.Match") -> str:
        bv = _base_v(m.group(3).lower())
        if not bv:
            return m.group(0)
        correct = (F / bv - 1) * 100
        cur = _parse_vn_number(m.group(1))
        return (m.group(0) if cur is not None and abs(cur - correct) <= 1
                else f"{correct:+.0f}{m.group(2)}{m.group(3)}")
    # Stop the baseline capture at a clause boundary ("và"/"nhưng"), not just at
    # ,.) — else a 2nd comparison joined by "và" WITHOUT a comma is swallowed into
    # group 3 and mis-classified (close 01/07: "tăng 0.39% so với phiên trước và
    # tăng 42% so với TB5" → group 3 = "phiên trước và … trung bình 5 phiên" → the
    # 'trung bình'/'5' hit made _base_v read it as TB5, so the 'phiên trước' % was
    # never checked against prev).
    out = _re.sub(
        r"([+-]?\d[\d.,]*)(\s*%\s*(?:vs|so với|so)\s+)([^,.)]+?)"
        r"(?=\s+(?:và|nhưng)\b|[,.)]|$)",
        _fix1, text)

    # Form 2: "<baseline> (±N%)"  (baseline precedes the parenthetical %)
    def _fix2(m: "_re.Match") -> str:
        bv = _base_v(m.group(1).lower())
        if not bv:
            return m.group(0)
        correct = (F / bv - 1) * 100
        cur = _parse_vn_number(m.group(2))
        return (m.group(0) if cur is not None and abs(cur - correct) <= 1
                else f"{m.group(1)} ({correct:+.0f}%)")
    out = _re.sub(
        r"((?:trung bình|TB)\s*\d+\s*phiên|phiên trước(?:\s+đó)?)\s*\(\s*([+-]?\d[\d.,]*)\s*%\s*\)",
        _fix2, out)

    # Form 4: "±N% <baseline>" — % CÓ DẤU đứng NGAY TRƯỚC baseline, không
    # connector (close 01:26 15/07: "(-21% phiên trước, +2% TB5 phiên)" —
    # vế prev đúng nhưng +2% lệch, TB5 thật -8%; Form 1 cần "so/vs", Form 2
    # cần baseline đứng trước → cả 2 trượt). DẤU BẮT BUỘC: quy ước signed →
    # pin signed an toàn; "thấp hơn 21% phiên trước" (verb mang chiều,
    # magnitude KHÔNG dấu) không bị đụng. Baseline phải mở đầu group ngay
    # sau % nên "±N% vs TB5" (đã qua Form 1) không bị xử lần 2.
    def _fix4(m: "_re.Match") -> str:
        bv = _base_v(m.group(3).lower())
        if not bv:
            return m.group(0)
        correct = (F / bv - 1) * 100
        cur = _parse_vn_number(m.group(1))
        return (m.group(0) if cur is not None and abs(cur - correct) <= 1
                else f"{correct:+.0f}{m.group(2)}{m.group(3)}")
    out = _re.sub(
        r"([+-]\d[\d.,]*)(\s*%\s+)((?:TB|trung bình|phiên trước)[^,).\n]{0,12})",
        _fix4, out)

    # Form 5 (bare-direction): "(cao hơn|thấp hơn) (trung bình N phiên|phiên
    # trước)" KHÔNG kèm %. Close 15/07: "GTGD 16,523.1 tỷ, cao hơn trung bình 5
    # phiên gần nhất" — mệnh đề định tính không số, không guard nào đối chiếu
    # chiều với F vs baseline. Lật từ cho khớp dấu(F/base−1); gate |p|>1% tránh
    # nhiễu quanh mốc bằng; idempotent (khớp → no-op); bỏ mệnh đề "sáng".
    def _fix5(m: "_re.Match") -> str:
        bv = _base_v(m.group(3).lower())
        if not bv:
            return m.group(0)
        p = (F / bv - 1) * 100
        if abs(p) <= 1:
            return m.group(0)
        want = "cao hơn" if p > 0 else "thấp hơn"
        if want == m.group(1).lower():
            return m.group(0)
        return want + m.group(2) + m.group(3)
    out = _re.sub(
        r"(cao hơn|thấp hơn)(\s+)((?:trung bình|TB)\s*\d+\s*phiên(?:\s*gần nhất)?"
        r"|phiên trước(?:\s*đó)?)",
        _fix5, out, flags=_re.IGNORECASE)
    return out


def enforce_compare_direction(text: str, ctx: dict | None = None) -> str:
    """A comparison word must match the sign / magnitude of its percentage.

    Form A (close 12/06: "GTGD … thấp hơn TB5 phiên (+43%)") — 'thấp hơn' with a
    POSITIVE % is a clash; flip the word to match the sign. Consistent pairs are
    left. The % must sit within ~30 chars of the word (same clause).

    Form B (morning 12/06: "8,397 tỷ … thấp hơn 11% TB sáng (7,549.1 tỷ)") — a
    bare % with the BASELINE VALUE in parens. The % carries no sign, so compare
    the line's subject tỷ value to the parenthetical baseline: 8,397 > 7,549 →
    'cao hơn', not 'thấp hơn'. Idempotent; no-op when clean.

    Form C (close 30/06: "GTGD … cao hơn -41% so với phiên trước và 37% so với
    TB20") — an INLINE signed % (no parens) after the word. Only acts when the %
    carries an EXPLICIT sign that clashes with the word; flips the word to match
    the sign AND drops the now-redundant sign ("thấp hơn 41% so với phiên trước").
    Gating on an explicit sign keeps it idempotent — a bare magnitude is never
    re-flipped — and leaves the 2nd comparison ("và 37% …") for the reader.
    """
    if not text:
        return text

    def _fix(m: "_re.Match") -> str:
        word, mid, paren, sign = m.group(1), m.group(2), m.group(3), m.group(4)
        positive = sign != "-"
        is_low = word.lower().startswith("thấp")
        if positive and is_low:
            return f"cao hơn{mid}{paren}"
        if not positive and not is_low:
            return f"thấp hơn{mid}{paren}"
        return m.group(0)

    out = _re.sub(
        r"(thấp hơn|cao hơn)([^.()]{0,30}?)(\(\s*([+-]?)\d[\d.,]*%\s*\))",
        _fix, text)

    # Form C: inline "<word> <sign><n>% so với …" with an EXPLICIT sign — for both
    # comparison words (cao/thấp hơn) and change verbs (tăng/giảm). Drops the now-
    # redundant sign (the word carries the direction). A change verb ALWAYS takes
    # the verb matching the sign (so both "tăng -10%" AND "giảm -10%" normalise to
    # "giảm 10%"); a comparison word only flips on a real clash (leaving a
    # consistent "cao hơn +37%" as-is). Close 01/07: after the baseline guard pins
    # "-10" onto "tăng … so với phiên trước", this yields "giảm 10% so với …".
    def _fixC(m: "_re.Match") -> str:
        word, sp, sign, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        wl = word.lower()
        positive = sign == "+"
        if wl in ("tăng", "giảm"):                 # verb carries direction
            return f"{'tăng' if positive else 'giảm'}{sp}{rest}"
        is_low = wl.startswith("thấp")
        if positive == is_low:                     # clash: (+ & thấp) or (- & cao)
            return f"{'cao hơn' if positive else 'thấp hơn'}{sp}{rest}"
        return m.group(0)                          # consistent → leave (keep sign)

    out = _re.sub(
        r"\b(thấp hơn|cao hơn|tăng|giảm)(\s+)([+-])(\d[\d.,]*\s*%\s*(?:so với|so)\b)",
        _fixC, out)

    # Form B: compare the line's subject value to a parenthetical baseline value.
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        sm = _re.search(r"(\d[\d.,]*)\s*tỷ", ln)
        subj = _parse_vn_number(sm.group(1)) if sm else None
        if subj is None:
            continue

        def _fixB(m: "_re.Match", _subj=subj) -> str:
            word, mid, base_s, unit = m.group(1), m.group(2), m.group(3), m.group(4)
            base = _parse_vn_number(base_s)
            if base is None:
                return m.group(0)
            is_low = word.lower().startswith("thấp")
            if _subj > base and is_low:
                return f"cao hơn{mid}{base_s}{unit}"
            if _subj < base and not is_low:
                return f"thấp hơn{mid}{base_s}{unit}"
            return m.group(0)

        # word may drop "hơn" ("thấp 11%" — observed 23:56); require a % right
        # after the word so a standalone adjective ("thanh khoản cao, X (Y tỷ)")
        # is never matched. Always re-emit the full "thấp hơn"/"cao hơn".
        lines[i] = _re.sub(
            r"(thấp|cao)(?:\s+hơn)?(\s*\d[\d.,]*\s*%[^()]{0,40}?\()(\d[\d.,]*)(\s*tỷ)",
            _fixB, ln)
    return "\n".join(lines)


def enforce_breadth_label(text: str, ctx: dict) -> str:
    """The only breadth % the brief has is "% mã trên MA200" (above_ma200_pct) —
    there is NO "% mã tăng giá" (advancing) figure. The model sometimes relabels
    the above-MA200 figure as advancing (observed close 12/06: "chỉ 17% mã cổ
    phiếu tăng giá" — 17% is the above-MA200 stat, while A/D 0.85 implies ~46%
    advancing). When a "<N>% mã [cổ phiếu] tăng giá/điểm" matches above_ma200_pct,
    relabel it "trên MA200". Gated on the value match so a genuine figure isn't
    touched; idempotent; no-op without breadth data.
    """
    b = ctx.get("breadth") or {}
    pct = b.get("above_ma200_pct")
    if not text or not isinstance(pct, (int, float)):
        return text

    def _fix(m: "_re.Match") -> str:
        n = _parse_vn_number(m.group(1))
        if n is None or abs(n - pct) > 1:        # only the above-MA200 mislabel
            return m.group(0)
        return f"{m.group(1)}% {m.group(2)} trên MA200"

    # "số mã cổ phiếu" (cả hai tiền tố ghép lại) — thấy thật close 14/07:
    # "chỉ 13% số mã cổ phiếu tăng giá" lọt qua vì regex cũ chỉ có từng nhánh lẻ.
    return _re.sub(
        r"(\d[\d.,]*)\s*%\s*((?:số\s+mã(?:\s+cổ phiếu)?|mã\s+cổ phiếu|cổ phiếu|mã))\s+(?:đang\s+)?tăng\s+(?:giá|điểm)",
        _fix, text)


# Composite-mood pieces (vnstock_market_sentiment._MOODS). Matched separately as
# emoji / word so the guard also fixes HYBRIDS the model emits (e.g. "❄️ Tiêu
# cực" — Sợ-hãi emoji + Tiêu-cực word), not just the exact canonical labels.
_MOOD_EMOJIS = ("🔥", "📈", "⚖️", "📉", "❄️")
_MOOD_WORDS = ("hưng phấn", "tích cực", "thận trọng", "tiêu cực", "sợ hãi")


def enforce_sentiment_consistency(text: str, ctx: dict) -> str:
    """Pin the body's cited market-mood label + momentum to the canonical
    ctx["market_sentiment"] (the same value the Telegram header shows and that
    was injected into the prompt).

    The LLM invents a different reading (close 16/06: header "📉 Tiêu cực,
    momentum -33" but body "❄️ Sợ hãi, momentum -24" — -24 doesn't match ❄️ Sợ
    hãi which needs < -50) or a HYBRID ("❄️ Tiêu cực" — wrong emoji + right word).
    Pins every "momentum N/100" to the real value and the mood after a "Tâm lý
    …:" cue (emoji and/or word) to the real label. Idempotent; no-op without data.
    """
    ms = ctx.get("market_sentiment") or {}
    mood = ms.get("mood")
    mom = ms.get("momentum")
    if not text or not mood or mom is None:
        return text
    try:
        mom = int(mom)
    except (TypeError, ValueError):
        return text
    # Dạng trực tiếp "momentum -51/100" (± markdown quanh số).
    out = _re.sub(r"momentum\s*[*_]{0,2}[+-]?\d+[*_]{0,2}\s*/\s*100",
                  f"momentum {mom:+d}/100", text, flags=_re.IGNORECASE)
    # Dạng chen tính từ "momentum tiêu cực (-51/100)" (close 30/07 01:21 —
    # LLM đệm chữ giữa "momentum" và số làm pattern trên trượt, số -51 là
    # VÍ DỤ trong prompt sống sót). Giữ tính từ, chỉ ghim số trong ngoặc;
    # không đụng dạng "(momentum -29/100)" vì '(' đứng TRƯỚC momentum.
    out = _re.sub(r"(momentum[^\d\n()]{0,24}\()\s*[+-]?\d+\s*(/\s*100\s*\))",
                  lambda m: f"{m.group(1)}{mom:+d}{m.group(2)}",
                  out, flags=_re.IGNORECASE)
    e_alt = "|".join(_re.escape(e) for e in _MOOD_EMOJIS)
    w_alt = "|".join(_MOOD_WORDS)
    # Mood word có thể bị model bọc markdown ("**Sợ hãi**") — close 14/07 lộ
    # ra: "Tâm lý: 📉 Tiêu cực **Sợ hãi**" (label đúng + ĐUÔI mood bịa dính
    # kèm) vì token có `**` không khớp pattern cũ. Cho phép [*_] quanh word
    # và nuốt luôn 1 mood word LẶP ngay sau → chỉ còn canonical.
    tok = rf"[*_]{{0,2}}(?:{w_alt})[*_]{{0,2}}"
    # after "Tâm lý …:" — an emoji+word (± duplicate word), a word alone, or
    # an emoji alone
    mood_pat = rf"(?:(?:{e_alt})\s*)?(?:{tok})(?:\s+{tok})?|(?:{e_alt})"
    out = _re.sub(rf"(Tâm lý[^\n]{{0,40}}?[:\-]\s*)(?:{mood_pat})",
                  lambda m: m.group(1) + mood, out, flags=_re.IGNORECASE)
    # Dạng KHÔNG dấu hai chấm "tâm lý sợ hãi (momentum -29/100)" (close 14/07 —
    # mood sai làm tính từ ngay sau "tâm lý"). CHỈ pin khi có "(…momentum" theo
    # sau (= claim trạng thái hiện tại, không đụng văn tường thuật quá khứ kiểu
    # "tâm lý hưng phấn đã biến mất"). Thay bằng CHỮ mood canonical (bỏ emoji,
    # thường-hóa) để hợp văn xuôi; idempotent (canonical → thay bằng chính nó).
    mood_word = mood.split(maxsplit=1)[-1]
    out = _re.sub(
        rf"(tâm lý\s+)[*_]{{0,2}}(?:{w_alt})[*_]{{0,2}}(?=\s*\([^)\n]*momentum)",
        lambda m: m.group(1) + mood_word.lower(), out, flags=_re.IGNORECASE)
    return out


def enforce_breadth_quality(text: str, ctx: dict) -> str:
    """Soften a positive breadth claim that contradicts a structurally weak tape.

    The only structural breadth metric is "% trên MA200"; when it's low and the
    backdrop is bearish, calling breadth "tích cực" overstates it (observed close
    16/06: "Độ rộng tích cực với A/D 1.33, và 18% trên MA200" — A/D is a 1-day
    advance/decline read, 18% above MA200 is weak → breadth is mixed). Swaps the
    positive adjective in the "độ rộng …" clause for "trái chiều". Gated on weak
    MA200% + bearish momentum so a genuinely broad market is untouched.
    """
    b = ctx.get("breadth") or {}
    pct = b.get("above_ma200_pct")
    ad = b.get("ad_ratio")
    mom = (ctx.get("market_sentiment") or {}).get("momentum")
    if not text or not isinstance(pct, (int, float)):
        return text
    if pct >= 40 or (mom is not None and mom >= 0):   # not structurally weak/bearish
        return text

    # Chiều NGƯỢC (close 23:58 14/07): A/D 1 phiên DƯƠNG (1.26 ≥ 1.05 — nhãn
    # canonical trong data block là "tích cực") mà brief gọi trơn "độ rộng
    # tiêu cực" ngay cạnh con số → người đọc hiểu phiên nhiều mã giảm hơn.
    # Cấu trúc yếu + ngày dương = "trái chiều" theo đúng quy ước của hệ.
    _neg_wrong = isinstance(ad, (int, float)) and ad >= 1.05

    def _fix(m: "_re.Match") -> str:
        clause = m.group(0)
        words = ("tích cực", "khả quan", "lành mạnh", "tốt", "mạnh")
        if _neg_wrong:
            words = words + ("tiêu cực", "xấu", "yếu")
        for w in words:
            if w in clause.lower():
                return _re.sub(w, "trái chiều", clause, count=1, flags=_re.IGNORECASE)
        return clause

    return _re.sub(r"[ĐđDd]ộ rộng[^\n.]{0,70}", _fix, text)


def enforce_vnindex_change(text: str, ctx: dict) -> str:
    """Pin the VNINDEX day-over-day % change to the real value (day_change_pct).

    The model sometimes drops another figure here (observed close 16/06: "tăng
    -24% so với phiên trước" — -24 is the sentiment momentum; the real change was
    +0.31%, also self-contradictory: "tăng" + a negative %). Only touches the
    "tăng/giảm X% so với phiên trước/hôm qua" day-change phrasing (not sector pp
    or weekly moves); idempotent; no-op without day_change_pct.
    """
    dc = (ctx.get("vnindex_tech") or {}).get("day_change_pct")
    if not text or not isinstance(dc, (int, float)):
        return text
    repl = f"{'tăng' if dc >= 0 else 'giảm'} {abs(dc):.2f}%"

    # CHỦ NGỮ phải là chỉ số: mệnh đề GTGD/thanh khoản cũng viết "X% so với
    # phiên trước" nhưng đó là ĐỔI GTGD — pin về day_change_pct là guard TỰ TẠO
    # lỗi (thấy thật close 14/07: "GTGD ... giảm 1.52% so với phiên trước" —
    # 1.52 là % đổi VNINDEX bị guard này đè vào). Nhìn ~45 ký tự trước match:
    # có từ khóa turnover → không đụng.
    _SUBJ_SKIP = ("gtgd", "thanh khoản", "khối lượng", "giá trị giao dịch")

    def _fix(m: "_re.Match") -> str:
        before = text[max(0, m.start() - 45):m.start()].lower()
        if any(k in before for k in _SUBJ_SKIP):
            return m.group(0)
        return repl + m.group(1)

    out = _re.sub(
        r"(?:tăng|giảm)\s*[+-]?\d[\d.,]*\s*%(\s*so với\s*"
        r"(?:phiên trước(?:\s*đó)?|hôm qua|phiên hôm qua))",
        _fix, text, flags=_re.IGNORECASE)

    # Nhánh 2 — "(tăng|giảm) X%" KHÔNG kèm hậu tố "so với…" (close 15/07:
    # "VNINDEX đóng cửa giảm 1.36% / GTGD…" và "VNINDEX giảm 1.36% với GTGD…"
    # — bar VNINDEX phẳng → day_change_pct=0.00 mà model bịa "giảm 1.36%",
    # mâu thuẫn mục kỹ thuật "+0.00%"). CHỈ đụng khi CHỦ NGỮ neo là chỉ số
    # (vnindex / chỉ số / kết quả phiên trong ~35 ký tự trước) và KHÔNG phải
    # GTGD/thanh khoản. dc≈0 → "gần như đi ngang (0.00%)" cho tự nhiên.
    _SUBJ_IDX = ("vnindex", "chỉ số", "kết quả phiên")
    flat = abs(dc) < 0.005
    repl2 = "gần như đi ngang (0.00%)" if flat else repl

    def _fix2(m: "_re.Match") -> str:
        # ĐỌC TỪ `out`, KHÔNG phải `text` (audit 06/08): nhánh 1 chạy trước và
        # ĐỔI ĐỘ DÀI chuỗi, nên `m.start()` — vị trí trong `out` — trỏ vào chỗ
        # KHÁC của `text`. Ca thật đã dựng lại: nhánh 1 rút "giảm 111,222.333%"
        # thành "tăng 0.31%" (lệch 7 ký tự) → cửa sổ đọc từ `text` mất chữ
        # "chỉ số" → guard bỏ qua đúng chỗ đáng lẽ phải sửa. Chiều ngược lại
        # còn tệ hơn: cửa sổ lệch có thể VÔ TÌNH thấy "vnindex" ở mệnh đề GTGD
        # rồi guard tự tay ghi đè số GTGD bằng day_change_pct.
        before = out[max(0, m.start() - 35):m.start()].lower()
        if any(k in before for k in _SUBJ_SKIP):
            return m.group(0)
        if not any(k in before for k in _SUBJ_IDX):
            return m.group(0)
        return repl2

    return _re.sub(r"(?:tăng|giảm)\s*[+-]?\d[\d.,]*\s*%", _fix2, out,
                   flags=_re.IGNORECASE)


def enforce_session_direction(text: str, ctx: dict) -> str:
    """Nhãn ĐỊNH TÍNH "phiên tăng/giảm (điểm)" phải khớp DẤU day_change_pct.

    Close 23:58 14/07: TLDR "VNINDEX đóng cửa +0.34% … — phiên GIẢM điểm nhẹ
    sau phiên tăng mạnh trước đó" — close DƯƠNG mà gọi phiên giảm (guard
    enforce_vnindex_change chỉ pin dạng có %, không đụng nhãn chữ). CHỈ sửa
    khi mệnh đề nói về PHIÊN NAY: dòng phải có neo "đóng cửa"/"kết quả
    phiên"; bỏ qua match nói về phiên KHÁC ("sau phiên tăng…", "phiên giảm
    trước đó", "hôm qua") và kịch bản tương lai ("nếu/kỳ vọng phiên tăng",
    "ngày mai"). Idempotent; no-op khi thiếu day_change_pct.
    """
    dc = (ctx.get("vnindex_tech") or {}).get("day_change_pct")
    if not text or not isinstance(dc, (int, float)) or dc == 0:
        return text
    want = "tăng" if dc > 0 else "giảm"

    def _fix_line(ln: str) -> str:
        low = ln.lower()
        if "đóng cửa" not in low and "kết quả phiên" not in low:
            return ln

        def _fix(m: "_re.Match") -> str:
            before = ln[max(0, m.start() - 12):m.start()].lower()
            after = ln[m.end():m.end() + 22].lower()
            # "sau phiên tăng…", "… trước đó/hôm qua", "nếu/kỳ vọng …",
            # "… ngày mai/tiếp theo" → phiên KHÁC, không đụng
            if _re.search(r"(?:sau|nếu|kỳ vọng|chờ)\s*$", before):
                return m.group(0)
            if _re.search(r"^\s*\S*\s*(?:trước|hôm qua|ngày mai|tiếp theo|kế tiếp)",
                          after):
                return m.group(0)
            return m.group(1) + want + (m.group(3) or "")

        return _re.sub(r"(phiên\s+)(tăng|giảm)(\s*điểm)?", _fix, ln,
                       flags=_re.IGNORECASE)

    return "\n".join(_fix_line(ln) for ln in text.splitlines())


def enforce_change_verb_sign(text: str, ctx: dict) -> str:
    """Fix a direction verb that contradicts the sign of its own % — "tăng -1%"
    → "giảm 1%", "giảm +5%" → "tăng 5%". The model writes these for the
    GTGD-vs-average and day-move clauses (observed close 16/06: "GTGD … tăng -1%
    so với TB5", "tăng -24% so với phiên trước"). The number's sign is taken as
    authoritative; flip the verb and drop the now-redundant sign. Consistent
    pairs ("tăng +X%", "giảm -…" ambiguous) are left alone; idempotent.
    """
    if not text:
        return text

    def _fix(m: "_re.Match") -> str:
        verb, sign, rest = m.group(1).lower(), m.group(2), m.group(3)
        if verb == "tăng" and sign == "-":
            return "giảm " + rest
        if verb == "giảm" and sign == "+":
            return "tăng " + rest
        return m.group(0)

    return _re.sub(r"(tăng|giảm)\s*([+-])\s*(\d[\d.,]*\s*%)", _fix, text,
                   flags=_re.IGNORECASE)


def validate_brief_factuality(text: str, ctx: dict) -> list[str]:
    """Scan brief output for VNINDEX-magnitude numbers far from real close.

    Returns list of warning strings (empty if no flags found).
    Each warning is a Vietnamese-readable single line for UI display.

    Tolerance: 5% relative error is allowed because S/R levels and intraday
    extremes can legitimately deviate from the closing price.
    """
    if not text:
        return []
    vt = ctx.get("vnindex_tech") or {}
    real_close = vt.get("close")
    if not real_close or real_close <= 0:
        # Without ground truth we cannot validate VNINDEX numbers — but we
        # can still flag if the brief mentions a VNINDEX level despite the
        # context having NO data. That is itself a hallucination.
        if any(_VNI_CONTEXT_RE.search(line) for line in text.splitlines()):
            for line in text.splitlines():
                if _VNI_CONTEXT_RE.search(line):
                    nums = [_parse_vn_number(m.group(1))
                            for m in _VNI_MAGNITUDE_RE.finditer(line)]
                    nums = [n for n in nums if n and 800 <= n <= 2500]
                    if nums:
                        return [
                            f"⚠️ Brief nêu mức VNINDEX ({nums[0]:,.0f}) trong khi data "
                            "không có dữ liệu VNINDEX hôm nay → có thể là hallucination."
                        ]
        return []

    warnings: list[str] = []
    real_low  = real_close * 0.95
    real_high = real_close * 1.05
    seen: set[float] = set()
    for line in text.splitlines():
        if not _VNI_CONTEXT_RE.search(line):
            continue
        for m in _VNI_MAGNITUDE_RE.finditer(line):
            n = _parse_vn_number(m.group(1))
            if n is None or n in seen:
                continue
            # Filter to VNINDEX magnitude — avoid catching ticker prices,
            # weights, %, etc. that happen to look like 4-digit numbers.
            if not (800 <= n <= 2500):
                continue
            seen.add(n)
            if not (real_low <= n <= real_high):
                rel_err = (n / real_close - 1) * 100
                warnings.append(
                    f"⚠️ Brief nêu VNINDEX ≈ **{n:,.0f}** ({rel_err:+.1f}% lệch "
                    f"so với close thực {real_close:,.2f}) → khả năng hallucinate."
                )
                if len(warnings) >= 3:
                    return warnings
    return warnings




# ── Chuỗi guard dùng chung — ĐIỂM PARITY sáng/chiều ────────────────────────

def apply_brief_guards(text: str, ctx: dict) -> str:
    """Run the full deterministic post-generation guard chain on a brief.

    The SINGLE source of truth for the fixup sequence — both the morning and
    close briefs go through this identical chain (generate_brief calls it for
    every agent's output regardless of brief_type). Each guard is itself
    brief_type-aware where it must be (section/anchor detection inside the
    guard), so morning↔close parity is guaranteed by construction: a fix added
    here applies to both briefs at once. Order matters (e.g. the canonical risk
    section runs before the defensive numeric guards). No-op-safe and
    idempotent end to end. Returns the (possibly) fixed text.
    """
    fixed = enforce_upcoming_events(text, ctx)
    fixed = enforce_macro(fixed, ctx)                # canonical macro levels/changes
    fixed = enforce_macro_fx_pct(fixed, ctx)         # USD/VND % safety net (header-miss)
    fixed = enforce_market_news(fixed, ctx)          # canonical econ/political headlines
    fixed = enforce_macro_reports(fixed, ctx)        # canonical 📚 band + digest báo cáo
    fixed = enforce_allocation_table(fixed, ctx)     # pin band/% + caveat horizon
    fixed = enforce_portfolio_facts(fixed, ctx)      # held-position facts are data
    fixed = enforce_risk_section(fixed, ctx)         # canonical risk facts first
    fixed = enforce_realestate_ocf_context(fixed, ctx)
    fixed = enforce_lead_lag(fixed, ctx)              # buy/avoid lines = lead/lag sector
    fixed = enforce_watchlist_hygiene(fixed, ctx)
    fixed = enforce_money_flow_two_sides(fixed, ctx)  # close section & morning inline
    fixed = enforce_sector_nn_figures(fixed, ctx)     # fabricated sector NN anywhere
    fixed = enforce_net_flow_label(fixed, ctx)        # mua/bán ròng verb+sign ↔ real NN
    fixed = enforce_nn_frame_labels(fixed, ctx)       # sector NN without frame → (1 tuần)
    fixed = enforce_liquidity_label(fixed, ctx)       # NN-sell figures ≠ thanh khoản
    fixed = enforce_nn_window_label(fixed, ctx)       # 1D NN total ≠ weekly
    fixed = enforce_risk_numbers(fixed, ctx)          # defensive no-op on canonical
    fixed = enforce_pivot_labels(fixed, ctx)
    fixed = enforce_sr_direction(fixed, ctx)          # S phải < close, R phải > close
    fixed = enforce_scenario_levels(fixed, ctx)       # scenario levels = real data only
    fixed = enforce_watchlist_eligibility(fixed, ctx)
    fixed = enforce_buy_vs_bias_caveat(fixed, ctx)    # GIẢM + BUY recs → caveat (keep, contextualize)
    fixed = enforce_stance_sentiment_caution(fixed, ctx)  # TĂNG stance + tâm lý tiêu cực → caveat
    fixed = enforce_gtgd_total(fixed, ctx)            # full-day (close) / sáng (morning)
    fixed = enforce_gtgd_compare_frame(fixed, ctx)    # close-only: full-day ≠ morning baseline
    fixed = enforce_gtgd_baseline_pct(fixed, ctx)     # close-only: % must match its baseline
    fixed = enforce_compare_direction(fixed, ctx)     # 'thấp/cao hơn' must match % sign
    fixed = enforce_breadth_label(fixed, ctx)         # above-MA200 % ≠ '% mã tăng giá'
    fixed = enforce_breadth_quality(fixed, ctx)       # 'độ rộng tích cực' vs weak MA200%
    fixed = enforce_sentiment_consistency(fixed, ctx)  # body mood/momentum = canonical
    fixed = enforce_vnindex_change(fixed, ctx)        # day % change = real day_change_pct
    fixed = enforce_session_direction(fixed, ctx)     # 'phiên giảm' label = day sign
    fixed = enforce_change_verb_sign(fixed, ctx)      # 'tăng -1%' → 'giảm 1%'
    fixed = enforce_no_cjk(fixed, ctx)
    fixed = enforce_no_instruction_leak(fixed, ctx)
    fixed = enforce_no_placeholder_leak(fixed, ctx)
    fixed = enforce_no_composite_jargon(fixed, ctx)
    fixed = enforce_composite_rotation_hygiene(fixed, ctx)  # no bucket↔label clash / 'Net BS'
    fixed = enforce_no_bias_directive_leak(fixed, ctx)   # 'bắt buộc' is internal
    fixed = enforce_no_record_superlative(fixed, ctx)    # no all-time GTGD claim
    fixed = enforce_no_duplicate_momentum(fixed, ctx)    # state momentum once
    fixed = enforce_range_position(fixed, ctx)
    fixed = enforce_number_format(fixed, ctx)            # one number convention (EN)
    return fixed
