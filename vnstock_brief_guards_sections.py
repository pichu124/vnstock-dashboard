"""Guard KHỐI NỘI DUNG — dựng lại đúng khối canon rồi ép brief khớp.

Một trong 3 nhóm tách từ `vnstock_brief_guards.py` (12/08, mục ④). Nhóm này
lo phần "brief nói SAI CHUYỆN GÌ": khối vĩ mô, tin tức, báo cáo, bảng phân bổ,
danh mục đang giữ, mục rủi ro, lead/lag, watchlist, hai chiều dòng tiền và các
nhãn NN (mua/bán ròng, khung thời gian, thanh khoản).

Đặc trưng của nhóm: guard ở đây phần lớn DỰNG LẠI khối từ `vnstock_brief_canon`
rồi thay vào — nên nó dùng chung hàm dựng khối với prompt builder, không thể
lệch chuẩn.

Guard trong file này KHÔNG tự chạy: phải được nối vào `apply_brief_guards`
(`vnstock_brief_guards`) mới sống — có lưới `tests/test_brief_split.py` canh.
"""
from __future__ import annotations

import re as _re

from vnstock_brief_canon import (
    _UNVALIDATED_STRATEGY_CAVEAT,
    VN30_TICKERS,
    _FINANCIAL_TICKERS,
    _WATCHLIST_GTGD_MIN_TY,
    _allocation_table_lines,
    _macro_body_lines,
    _macro_reports_body_lines,
    _market_news_body_lines,
    _portfolio_fact_line,
    _round_tick,
)
from vnstock_brief_guards_common import (
    _PIVOT_LABEL_RE,
    _is_section_start,
    _parse_vn_number,
)


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
    """A foreign-flow figure can't be both weekly AND one-day — and one
    SECTOR's week is not the MARKET's week. The composite 'NN ròng 1D' total
    (market-sentiment block) is a ONE-DAY net flow; sector 'NN 1T (tỷ)' values
    are per-sector WEEKLY flows. The LLM mixes both frames when narrating
    (12:42: "bán ròng mạnh 665 tỷ tuần này (1D: -665 tỷ)"; brief #212 15/08:
    TLDR "bán ròng **856 tỷ** tuần qua" — 856 is the 14/08 ONE-DAY total —
    and "Khối ngoại bán ròng 1,965 tỷ tuần qua (Họ VIN -1,965 tỷ…)" — Họ
    VIN's weekly figure claimed for the whole market).

    1) Self-contradiction (ctx-free, always safe): "<N tỷ> <tuần…> (1D…)" → drop
       the weekly tag — the model already labeled it 1D.
    2) The exact 1D magnitude from ctx tagged weekly with NO 1D marker → relabel
       to 1D. Skipped if a weekly sector value shares that magnitude (coincidence).
    3) A magnitude matching exactly ONE sector's weekly value claimed as a
       market-wide weekly total ("khối ngoại/NN bán|mua ròng <N> tỷ <tuần…>")
       → inject the sector name right after "ròng" so the claim is scoped.
       Skipped when ≥2 sectors share the magnitude or it equals the 1D total
       (can't referee), or the clause already names the sector there.

    Every gap tolerates markdown bold: #212's "**856 tỷ** tuần qua" slipped
    past the old whitespace-only regexes purely because of the '**' between
    figure and window word. Dropped bold markers are re-emitted so pairs stay
    balanced (an unbalanced '**' bleeds bold over the rest of a Telegram brief).
    """
    if not text:
        return text
    _wk = r"(?:trong\s+)?(?:tuần\s+này|tuần\s+qua|cả\s+tuần|1\s*tuần|tuần)"
    _g = r"[\s*]*"                       # gap: whitespace and/or markdown '**'

    def _stars(gap: str) -> str:
        return "*" * gap.count("*")

    # 1) "<N tỷ> [**] tuần… [**] (1D…)" → "<N tỷ>[**] (1D…)"
    new = _re.sub(
        rf"(\d[\d.,]*\s*tỷ)({_g}{_wk})({_g}\(\s*1D)",
        lambda m: m.group(1) + _stars(m.group(2)) + m.group(3),
        text)

    sectors = [s for s in ((ctx or {}).get("sectors") or [])
               if isinstance(s.get("NN 1T (tỷ)"), (int, float))]

    # 2) exact 1D magnitude tagged weekly, no 1D marker → relabel to 1D
    mag_1d = None
    ms = (ctx or {}).get("market_sentiment") or {}
    sig = next((s for s in ms.get("signals", [])
                if "1d" in str(s.get("name", "")).lower()
                and "nn" in str(s.get("name", "")).lower()), None)
    if sig:
        val = _parse_vn_number(
            str(sig.get("value", "")).replace("tỷ", "").replace("+", "").strip())
        if val is not None:
            mag_1d = f"{abs(val):,.0f}"
            coincident = any(f"{abs(s['NN 1T (tỷ)']):,.0f}" == mag_1d
                             for s in sectors)
            if not coincident:
                new = _re.sub(
                    rf"({_re.escape(mag_1d)}\s*tỷ)({_g}{_wk})\b(?!{_g}\(\s*1D)",
                    lambda m: (m.group(1) + _stars(m.group(2))
                               + " (1D, phiên gần nhất)"),
                    new)

    # 3) one sector's weekly figure claimed market-wide → scope it by name
    by_mag: dict[str, list[str]] = {}
    for s in sectors:
        by_mag.setdefault(f"{abs(s['NN 1T (tỷ)']):,.0f}", []).append(
            str(s.get("Ngành") or "").strip())
    for mag, names in by_mag.items():
        if len(names) != 1 or not names[0] or mag == mag_1d:
            continue
        new = _re.sub(
            rf"(\b(?:khối\s+ngoại|NN)\b{_g}(?:bán|mua)\s+ròng\s+(?:mạnh\s+)?{_g})"
            rf"({_re.escape(mag)}\s*tỷ{_g}{_wk}\b)",
            lambda m, _n=names[0]: m.group(1) + _n + " " + m.group(2),
            new, flags=_re.IGNORECASE)
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


# Cảnh báo GDKHQ tính bằng NGÀY LỊCH, hai ngưỡng cho hai loại mục:
# watchlist "sáng mai" chỉ quan tâm phiên kế tiếp (3 ngày phủ được T6→T2);
# đề xuất/khuyến nghị có horizon 5-20 phiên nên lấy trọn cửa sổ nạp sự kiện.
_EXDATE_WL_DAYS = 3
_EXDATE_REC_DAYS = 14
_EXDATE_MARK = "⚠️ GDKHQ"


def _exdate_map(ctx: dict | None, within_days: int) -> dict:
    """{MÃ: (ex_date, title)} của sự kiện quyền rơi trong `within_days` ngày.

    Mã có NHIỀU sự kiện thì giữ cái GẦN NHẤT — đó là cái làm hỏng mốc giá trước.
    `ctx["today"]` cho phép test cắm ngày cố định; ngoài đời lấy ngày hệ thống.
    """
    from datetime import date as _date, timedelta as _td

    today = (ctx or {}).get("today") or _date.today()
    if isinstance(today, str):
        try:
            today = _date.fromisoformat(today[:10])
        except ValueError:
            today = _date.today()
    limit = today + _td(days=within_days)
    out: dict = {}
    for e in (ctx or {}).get("upcoming_events") or []:
        try:
            d = _date.fromisoformat(str(e.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        if d < today or d > limit:
            continue
        tk = str(e.get("ticker") or "").strip().upper()
        if not tk:
            continue
        if tk not in out or d < out[tk][0]:
            out[tk] = (d, str(e.get("title") or "").strip())
    return out


def enforce_exdate_levels(text: str, ctx: dict) -> str:
    """Mốc giá của một mã sắp GDKHQ phải NÓI RA rằng nó chưa quy đổi quyền.

    Ca thật, brief chiều 19/08 — cùng một brief chứa hai khối đá nhau:
      * Watchlist: "VIX (Giá 13,100) — TRÁNH nếu thủng 12,700 … Áp lực bán gia
        tăng trước ngày giao dịch không hưởng quyền."
      * Sự kiện:   "VIX: Trả Cổ tức bằng Cổ phiếu tỉ lệ 5.0% — ngày 2026-08-20"
    13.100 × 100/105 = 12.476 ⇒ mốc "thủng 12.700" kích hoạt CƠ HỌC ngay lúc mở
    cửa hôm sau, không phải do ai bán; mốc hủy 13.500 thành bất khả. Câu diễn
    giải còn quy nhân quả sai. Cảnh báo GDKHQ vốn ĐÃ có — nhưng nó nằm ở mục Sự
    kiện và không lan sang Watchlist. Đây là lớp lỗi MỚI: guard cũ canh "nói
    đúng chuyện" TRONG từng mục, chưa cái nào canh NHẤT QUÁN GIỮA HAI MỤC.

    Cố ý KHÔNG tự quy đổi mốc giá. Tỉ lệ quyền chỉ nằm trong CHỮ của `title`, mà
    cổ tức TIỀN MẶT điều chỉnh theo MỆNH GIÁ (tỉ lệ × 10.000đ) chứ không theo %
    giá — đoán sai chỗ này còn hại hơn không đoán. Guard nêu SỰ KIỆN và nói
    thẳng "mốc chưa quy đổi", để người đọc tự trừ. Quy đổi tự động chờ kho sự
    kiện có tỉ lệ dạng SỐ (mục còn treo — kho đang mỏng).

    Idempotent: đã có dấu `⚠️ GDKHQ` trên dòng thì bỏ qua.
    """
    if not text:
        return text
    maps = {"wl": _exdate_map(ctx, _EXDATE_WL_DAYS),
            "rec": _exdate_map(ctx, _EXDATE_REC_DAYS)}
    if not maps["wl"] and not maps["rec"]:
        return text

    def _zone_of(line: str) -> "str | None":
        low = line.lower()
        if "watchlist" in low or "trọng tâm theo dõi" in low:
            return "wl"
        if "đề xuất giao dịch" in low or "khuyến nghị đang mở" in low:
            return "rec"
        return None

    out, zone, changed = [], None, False
    for line in text.splitlines():
        if _is_section_start(line) or line.lstrip().startswith(
                ("##", "⚠️", "📅", "💡", "🔧", "📋", "📌")):
            zone = _zone_of(line)
            out.append(line)
            continue
        item = _re.match(r"\s*(?:\d+\.|[-•*])\s+", line)
        if zone is None or not item or _EXDATE_MARK in line:
            out.append(line)
            continue
        hit = next(((tk, d, ti) for tk, (d, ti) in sorted(maps[zone].items())
                    if _re.search(rf"\b{_re.escape(tk)}\b", line)), None)
        if hit is None:
            out.append(line)
            continue
        tk, d, title = hit
        note = f" · {_EXDATE_MARK} {d.isoformat()}"
        if title:
            note += f" ({title[:60]})"
        note += " — giá tham chiếu tự điều chỉnh, mốc trên CHƯA quy đổi"
        out.append(line.rstrip() + note)
        changed = True
    # Không đổi gì thì trả NGUYÊN văn bản: `splitlines()/join` nuốt mất newline
    # cuối, và một guard no-op mà vẫn sửa text là thứ khó truy nhất khi xâu
    # chuỗi 47 guard lại với nhau.
    return "\n".join(out) if changed else text


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


def enforce_unvalidated_strategy_caveat(text: str, ctx: dict) -> str:
    """Khuyến nghị của chiến lược trượt kiểm định LỌT vào brief → phải NÓI RA.

    Từ 13/08 (user chốt "không đạt thì không khuyến nghị gì") đường CHÍNH đã
    chặn ở nguồn: `_recommendation_block` trượt kiểm định là thay danh sách
    bằng sentinel KHÔNG CÓ. Guard này còn lại vai trò HÀNG RÀO DỰ PHÒNG cho
    đường không chính thống — ai đó gọi `build_prompt(rec_block=...)` tự dựng,
    hoặc luồng cũ chưa cập nhật.

    Vì thế điều kiện bắn có thêm `strategy_recs_in_prompt=True` (cờ do
    `_recommendation_block` set khi THẬT SỰ đưa khuyến nghị vào prompt). Thiếu
    cờ mà cứ bắn là gắn nhãn oan: mục "Đề xuất giao dịch" còn chứa setup từ
    movers ⭐ — những setup đó KHÔNG đến từ chiến lược, caveat "chiến lược chưa
    kiểm định" đặt lên chúng là nói sai nguồn.

    Không đọc được kiểm định (chưa có chiến lược / DB lỗi) thì IM — không đo
    được khác đo ra kết quả xấu. Idempotent.

    17/08 (brief #217): caveat phải theo kiểm định của CHÍNH recs trong prompt
    (`strategy_recs_validation`, do `_recommendation_block` ghi cùng lúc với
    cờ) — KHÔNG phải của chiến lược active tầng ngắn. Hai tier chạy song song:
    đêm #32 [vị thế] ĐẠT p=0.012 mà guard này dán "(p=1.000)" của tầng ngắn
    lên chính rec của nó, tự mâu thuẫn với block "Khuyến nghị đang mở" ngay
    dưới. Thiếu key mới (luồng cũ chưa cập nhật / rec_block tự dựng) → rơi về
    `strategy_validation` — đúng vai trò hàng rào dự phòng nguyên bản.
    """
    val = (ctx or {}).get("strategy_recs_validation")
    if val is None:
        val = (ctx or {}).get("strategy_validation") or {}
    if not text or not val.get("known") or val.get("passed", True):
        return text
    if not (ctx or {}).get("strategy_recs_in_prompt"):
        return text
    if _UNVALIDATED_STRATEGY_CAVEAT[:40] in text:
        return text

    lines = text.splitlines()
    # Mục khuyến nghị: brief gọi "💡 Đề xuất giao dịch" (close) hoặc "Khuyến nghị"
    start = next((i for i, l in enumerate(lines)
                  if _is_section_start(l)
                  and ("đề xuất giao dịch" in l.lower() or "khuyến nghị" in l.lower())),
                 None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))
    if not any(l.strip() for l in lines[start + 1:end]):
        return text                      # mục rỗng → không có gì để cảnh báo

    _p = val.get("p")
    caveat = _UNVALIDATED_STRATEGY_CAVEAT + (f" (p={_p:.3f})" if isinstance(_p, float) else "")

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    return "\n".join(lines[:insert_at] + [caveat] + lines[insert_at:])
