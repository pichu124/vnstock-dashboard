"""Guard CON SỐ — số trong brief phải khớp số thật, và hướng phải khớp dấu.

Một trong 3 nhóm tách từ `vnstock_brief_guards.py` (12/08, mục ④). Nhóm này lo
phần "brief nói SAI SỐ hoặc SAI CHIỀU": mức rủi ro, pivot, hỗ trợ/kháng cự,
kịch bản, GTGD (tổng, khung so sánh, % theo baseline), hướng so sánh, độ rộng,
tâm lý, đổi điểm VNINDEX, chiều phiên, động từ tăng/giảm so với dấu, vị trí
trong biên độ, và quy ước số EN.

Đặc trưng của nhóm: gần như guard nào cũng đọc số từ `ctx` (dữ liệu THẬT) rồi
so với số LLM viết ra — LLM hay phớt chỉ thị prompt nên chốt bằng code.

Guard trong file này KHÔNG tự chạy: phải được nối vào `apply_brief_guards`
(`vnstock_brief_guards`) mới sống — có lưới `tests/test_brief_split.py` canh.
"""
from __future__ import annotations

import re as _re

from vnstock_brief_canon import _FINANCIAL_TICKERS, _SR_MAX_MOVE_PCT, _gtgd_close_frame
from vnstock_brief_guards_common import (
    _PIVOT_LABEL_RE,
    _is_section_start,
    _parse_vn_number,
)


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
