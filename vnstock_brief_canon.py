"""Nguồn CANON của brief — hằng số + khối nội dung mà cả prompt lẫn guard dựa vào.

Tách khỏi `vnstock_brief.py` (12/08, mục ④ audit 06/08). Đây KHÔNG phải "file
tiện ích lặt vặt": nó là đường ranh giới thật của hệ guard.

Cơ chế brief có hai tầng, và tầng nào cũng cần đúng MỘT bộ sự thật:

* **Prompt builder** dựng khối số liệu đưa vào prompt cho LLM;
* **Guard hậu kiểm** (`vnstock_brief_guards`) dựng LẠI đúng khối đó rồi ép
  output của LLM khớp — vì LLM hay phớt chỉ thị prompt (quy ước CLAUDE.md).

Hai tầng dựng cùng một khối bằng CÙNG MỘT HÀM ở đây, nên không thể lệch nhau.
Nếu tách đôi (mỗi bên một bản), guard sẽ "sửa" output về một chuẩn khác chuẩn
đã đưa vào prompt — đúng loại lỗi im lặng khó lần nhất.

Module thuần: cấp module không import gì ngoài stdlib, nên `vnstock_brief` và
`vnstock_brief_guards` cùng import được mà không tạo vòng. Vài hàm import LƯỜI
module lá không phụ thuộc brief (`vnstock_macro` cho định dạng số vĩ mô,
`vnstock_horizons` — lõi 3 khung thuần stdlib — cho nhãn/ngưỡng của khối 🔭).
"""
from __future__ import annotations

import re


# ── Cảnh báo chiến lược chưa qua kiểm định ──────────────────────────────────
# Dùng ở CẢ HAI phía: `_recommendation_block` gắn vào prompt, và
# `enforce_unvalidated_strategy_caveat` bảo đảm nó sống sót tới brief cuối
# (LLM hay lược bỏ đúng những câu bất lợi).
#
# Vì sao phải có: `_recommendation_block` viết trong docstring là "open
# recommendations from VALIDATED strategies" nhưng CHƯA HỀ kiểm — nên khuyến
# nghị của một chiến lược trượt kiểm định chống-ăn-may vẫn vào brief y như
# chiến lược đạt, không phân biệt được (user phát hiện 13/08: chiến lược đang
# hoạt động có p=0.974, expectancy −0.58, 0/49 lệnh chạm chốt lời).
#
# Chọn CẢNH BÁO chứ không LỌC BỎ — cùng doctrine với `_BUY_BIAS_CAVEAT` và
# khối BĐS Op.CF: mỗi khuyến nghị đã tự mang cắt lỗ (rủi ro có giới hạn), nên
# thêm bối cảnh đúng hơn là giấu tín hiệu.
_UNVALIDATED_STRATEGY_CAVEAT = (
    "⚠️ Khuyến nghị trên đến từ chiến lược CHƯA QUA kiểm định chống-ăn-may "
    "— coi là ý tưởng tham khảo, không phải tín hiệu đã được kiểm chứng; "
    "bắt buộc tôn trọng cắt lỗ và cân nhắc giảm tỷ trọng."
)


# ── Vũ trụ mã ─────────────────────────────────────────────────────────────────
# VN30 tickers — current composition (keep in sync with _VN30_FALLBACK in vnstock_news.py)
# Try dynamic fetch first; fall back to this set when vnstock API is unavailable.
VN30_TICKERS: set[str] = {
    "ACB", "BID", "BSR", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", "LPB",
    "MBB", "MCH", "MSN", "MWG", "SAB", "SHB", "SSB", "SSI", "STB", "TCB",
    "TCX", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VPL", "VRE",
}
# Financial-sector tickers (banks / securities / insurance). Their balance-sheet
# leverage (bank D/E ~9-17 is NORMAL) and operating cash flow (driven by
# deposit/loan/trading flows = tens of trillions VND) are structurally NOT
# comparable to non-financial companies. We exclude them from the fundamental
# risk rankings (highest D/E, weakest Op.CF) so a bank never gets mis-flagged as
# a risk purely because of its scale — e.g. "MBB Op.CF -64,972 tỷ".
_FINANCIAL_TICKERS: frozenset[str] = frozenset({
    # Ngân hàng
    "ACB", "BID", "CTG", "HDB", "MBB", "SHB", "SSB", "STB", "TCB", "TPB",
    "VCB", "VIB", "VPB", "MSB", "EIB", "LPB", "OCB", "NAB", "ABB", "BAB",
    "KLB", "PGB", "SGB", "VAB", "VBB", "NVB",
    # Chứng khoán (TCX = Techcom Securities/TCBS, niêm yết HOSE 21/10/2025,
    # vào VN30 kỳ 08/2026 — công ty CHỨNG KHOÁN, phải nằm đây để không bị
    # chấm là "rủi ro cơ bản" chỉ vì đòn bẩy kiểu định chế tài chính)
    "SSI", "VND", "HCM", "VCI", "VIX", "SHS", "MBS", "FTS", "BSI", "CTS",
    "AGR", "ORS", "VDS", "TVS", "APG", "TCX",
    # Bảo hiểm
    "BVH", "BIC", "BMI", "MIG", "PVI", "PGI", "ABI", "BLI",
})

# ── Ngưỡng dùng chung ─────────────────────────────────────────────────────────
# Stricter floor (tỷ VND/phiên) for a mover to be eligible as an ACTIONABLE
# watchlist setup. The broad ≥10 tỷ pool feeds analysis/"biến động bất thường";
# only VN30 OR names trading ≥ this much should anchor a MUA/GIẢM setup, so a
# thin mid-cap (e.g. VIW) is described but never turned into a trade idea.
# Tunable: 30 tỷ keeps leading mid-cap banks (e.g. ABB ~45-50 tỷ) eligible.
_WATCHLIST_GTGD_MIN_TY: float = 30.0
# TRẦN khoảng cách cho VAI/MỤC TIÊU S/R (fraction of close như 2 hằng trên —
# review 21/07 đồng nhất đơn vị: giá trị cũ 7.0 là percent, dùng phải /100):
# biên độ HOSE 7%/ngày là trần vật lý — mức cách giá hơn thế không thể
# actionable trong 1-2 phiên (user chốt 17/07, siết nguồn 20/07). Dùng ở cả
# _select_sr_levels (nguồn) lẫn enforce_sr_direction tầng 3 (kéo/cắt mục tiêu).
_SR_MAX_MOVE_PCT: float = 0.07

# ── Bước giá HOSE ─────────────────────────────────────────────────────────────
def _vn_tick(price_vnd: float) -> int:
    """HOSE price tick (VND): <10k → 10, 10k-<50k → 50, ≥50k → 100. Watchlist
    setup levels must land on a valid tick (observed odd 16,684 / 92,635)."""
    p = abs(price_vnd)
    return 10 if p < 10_000 else 50 if p < 50_000 else 100
def _round_tick(value_vnd: float, ref_price_vnd: float) -> int:
    """Round a price level to the tick of the reference (stock) price."""
    t = _vn_tick(ref_price_vnd)
    return int(round(value_vnd / t) * t)

# ── Khối vĩ mô ────────────────────────────────────────────────────────────────
def _macro_line(ind: dict) -> str:
    """One canonical macro bullet: 'Label: value unit (tính đến as_of) <change>'.

    Formatting (decimals/units/labels) is delegated to vnstock_macro's
    fmt_value/fmt_change so a new indicator only touches its `_DEFS` entry —
    the brief and the CLI can never drift apart. EN number convention matches
    every other data block and enforce_number_format.
    """
    from vnstock_macro import fmt_change, fmt_value
    line = f"- {ind['label']}: {fmt_value(ind)} (tính đến {ind['as_of']})"
    fc = fmt_change(ind)
    if fc:
        arrow, mag, hint = fc
        line += f" {arrow} {mag} so với {ind['prev_as_of']} ({hint})"
    return line
def _macro_body_lines(macro: list[dict],
                      macro_news: "list[dict] | None" = None,
                      directive: bool = True) -> list[str]:
    """Canonical macro bullets (NO section header) ± directive.

    Shared by the prompt renderer and the post-gen guard so the guard can splice
    exactly the body without slicing the header off a joined string. Indicators
    with NO recent change are compressed into one 'Đi ngang' line so the block
    doesn't grow a bullet per indicator as the registry expands (8+ nay).

    ``directive=False`` cho guard — dòng chỉ thị "→ Lãi suất TĂNG… DÙNG bối
    cảnh này…" chỉ thuộc PROMPT, không được splice vào brief xuất bản (leak
    thật close 14/07 — phần 2/2 mở đầu bằng nguyên dòng chỉ thị nội bộ).
    """
    from vnstock_macro import (fmt_change, fmt_value, intl_spread,
                               liquidity_spread, pmi_reminder, term_spread)
    moved = [m for m in macro if fmt_change(m)]
    flat = [m for m in macro if not fmt_change(m)]
    lines = [_macro_line(m) for m in moved]
    if flat:
        parts = "; ".join(
            f"{m['label']} {fmt_value(m)} ({m['as_of']})" for m in flat)
        lines.append(f"- Đi ngang/chưa có kỳ mới: {parts}")
    liq = liquidity_spread(macro)      # gauge dẫn xuất ON − lãi suất điều hành
    if liq:
        line = (f"- Chênh lệch thanh khoản: LNH ON − lãi suất điều hành = "
                f"{liq['spread']:+.2f} điểm % → {liq['label']}")
        if liq.get("slope_10y_on") is not None:
            line += f"; dốc 10Y − ON = {liq['slope_10y_on']:+.2f} điểm %"
        lines.append(line)
    ts = term_spread(macro)            # gauge kỳ hạn 10Y − điều hành (+ dốc 10Y − 2Y)
    if ts:
        line = (f"- Kỳ hạn & đường cong: 10Y − lãi suất điều hành = "
                f"{ts['spread']:+.2f} điểm % → {ts['label']}")
        if ts.get("slope_2_10") is not None:
            line += (f"; dốc 10Y − 2Y = {ts['slope_2_10']:+.2f} điểm % → "
                     f"{ts['slope_label']}")
        lines.append(line)
    intl = intl_spread(macro)          # gauge chênh lệch quốc tế VN10Y − US10Y
    if intl:
        lines.append(f"- Chênh lệch quốc tế: VN10Y − US10Y = "
                     f"{intl['spread']:+.2f} điểm % → {intl['label']}")
    rem = pmi_reminder(macro)          # PMI tháng trước chưa set sau ngày công bố
    if rem:
        lines.append(f"- {rem}")
    for n in (macro_news or [])[:3]:
        lines.append(f"- Tin liên quan [{n.get('ticker','')}] {n.get('date','')}: "
                     f"{n.get('title','')}")
    if directive:
        # Fed có reading thật (fed_funds từ FRED) thì bỏ mệnh đề "Fed chưa có
        # data" — trước đó phải CẤM BỊA vì không có nguồn; luật "không bịa chỉ
        # số ngoài danh sách" vẫn giữ nguyên cho mọi thứ khác.
        have_fed = any(m.get("key") == "fed_funds" for m in macro)
        lines.append(
            "→ Lãi suất TĂNG / VND mất giá (USD/VND tăng) / CPI tăng tốc = môi trường "
            "THẮT CHẶT, bất lợi cho cổ phiếu (đặc biệt nhóm vay nợ cao; khối ngoại dễ "
            "bán ròng). Lãi suất giảm / VND ổn định / GDP-IIP-PMI cải thiện = thuận "
            "lợi hơn (PMI < 50 điểm = sản xuất thu hẹp; cán cân thương mại ÂM = nhập "
            "siêu, kéo dài là áp lực tỷ giá). DÙNG bối cảnh này khi chốt Bias + Rủi "
            "ro để ĐÓN ĐẦU thay đổi. DÙNG ĐÚNG số + as_of ở trên, KHÔNG bịa chỉ số "
            "vĩ mô ngoài danh sách trên"
            + ("." if have_fed else " (Fed… chưa có trong data).")
        )
    return lines

# ── Khối tin kinh tế / chính trị ──────────────────────────────────────────────
_MKT_NEWS_SENT_ICON = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}

IMPACT_MAX_CHARS = 160


def sanitize_impact(s, max_len: int = IMPACT_MAX_CHARS) -> str:
    """Dọn câu "tác động:" của LLM trước khi dán vào MỘT dòng bullet.

    Bản close 21/08 lộ hai lỗi cùng lúc trong khối tin:

        — tác động: An ninh tại Horm          ← cắt GIỮA TỪ, không dấu …
        — tác động: `
        *                                     ← rác markdown + XUỐNG DÒNG

    Xuống dòng là thứ nguy hiểm nhất: khối tin dựng theo TỪNG DÒNG, một ký tự
    `\n` trong `_impact` đẩy phần còn lại thành dòng lạc, nhìn hệt như câu bị
    cụt. Nên gộp MỌI khoảng trắng (kể cả xuống dòng) về một dấu cách, bỏ ký
    tự điều khiển markdown, rồi mới cắt — và cắt ở BIÊN TỪ kèm "…" để người
    đọc biết là còn nữa.

    Hàm thuần, chạy ở đường HIỂN THỊ nên cache cũ (đã bẩn) cũng được dọn.
    """
    if not s:
        return ""
    import re as _re2
    t = _re2.sub(r"[`*_~>#]+", " ", str(s))      # rác markdown
    t = _re2.sub(r"\s+", " ", t).strip()          # gộp cả \n \t về 1 dấu cách
    if not t:
        return ""
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0].rstrip(" ,.;:-–—")
    return (cut or t[:max_len].rstrip()) + "…"


def _one_line(s) -> str:
    """Gộp mọi khoảng trắng về một dấu cách — tiêu đề tin cũng có thể có \n."""
    if not s:
        return ""
    import re as _re2
    return _re2.sub(r"\s+", " ", str(s)).strip()
def _market_news_body_lines(items: list[dict],
                            directive: bool = True) -> list[str]:
    """Canonical market-news bullets (NO section header) ± directive. Shared by
    the prompt renderer and the guard so the section is fabrication-proof.
    ``directive=False`` cho guard — dòng chỉ thị "→ DÙNG các tin trên…" chỉ
    thuộc prompt, không splice vào brief xuất bản (leak thật close 14/07)."""
    lines: list[str] = []
    for it in items:
        icon = _MKT_NEWS_SENT_ICON.get(it.get("_sentiment", ""), "•")
        d = it.get("_date_sort", "") or "?"
        title = _one_line(it.get("title"))
        src = _one_line(it.get("source_feed"))
        line = f"- {icon} [{d}] {title}" + (f" ({src})" if src else "")
        impact = sanitize_impact(it.get("_impact"))
        if impact:
            line += f" — tác động: {impact}"
        lines.append(line)
    if directive:
        lines.append(
            "→ DÙNG các tin trên khi đánh giá bối cảnh vĩ mô + rủi ro; gắn tin với "
            "ngành/cổ phiếu liên quan nếu có. 🟢=tích cực /🔴=tiêu cực cho TTCK. "
            "TUYỆT ĐỐI KHÔNG bịa tin/tiêu đề ngoài danh sách này."
        )
    return lines

# ── Khối báo cáo vĩ mô (P4) ───────────────────────────────────────────────────
def _score2(v) -> float:
    """Điểm band làm tròn 2 số lẻ, không bao giờ in "-0.00" (close 16/09:
    điểm −0.004 in thành "điểm -0.00"). `+ 0.0` xoá dấu của số không âm."""
    try:
        return round(float(v or 0), 2) + 0.0
    except (TypeError, ValueError):
        return 0.0


def _macro_reports_body_lines(ctx: dict, directive: bool = True) -> list[str]:
    """Canonical bullets mục 📚 — dùng chung bởi prompt renderer VÀ guard
    (enforce_macro_reports) nên mục này fabrication-proof by construction.

    Cap ~5 dòng (tham số duyệt): 1 dòng band + ≤3 báo cáo + 1 dòng consensus.
    Claim mismatch KHÔNG BAO GIỜ xuất hiện ở đây (chỉ tom_tat + stance — số
    lệch registry bị chặn từ tầng digest). ``directive=False`` cho guard —
    dòng chỉ thị chỉ thuộc prompt, không được splice vào brief xuất bản.
    """
    reps = ctx.get("macro_reports") or []
    alloc = ctx.get("allocation") or {}
    cons = ctx.get("reports_consensus") or {}
    lines: list[str] = []
    if alloc.get("band"):
        band_line = (f"- 🧭 Band phân bổ tháng: {alloc['band']} "
                     f"({alloc.get('band_label', '')}) — điểm "
                     f"{_score2(alloc.get('score')):+.2f}, phiên {alloc.get('as_of', '?')}")
        rt = alloc.get("report_tilt") or {}
        if rt.get("tilt"):
            band_line += (f"; đã gồm tilt {rt.get('label') or format(rt['tilt'], '+d')}"
                          f" từ báo cáo (band data: {alloc.get('band_data')})")
        lines.append(band_line + _alloc_cap_note(alloc))
    for r in reps[:3]:
        d = r.get("digest") or {}
        cp = (d.get("stance") or {}).get("Cổ phiếu", 0)
        line = (f"- [{r.get('report_date', '?')}] {r.get('source', '?')}: "
                f"{d.get('tom_tat', '')} (stance cổ phiếu {cp:+d})")
        if d.get("has_mismatch"):
            line += " — ⚠ báo cáo có số lệch registry, số liệu của nó không được trích dẫn"
        lines.append(line)
    if cons and cons.get("n_reports"):
        cp = (cons.get("stance") or {}).get("Cổ phiếu", 0)
        tail = (f" → tilt {cons['tilt']:+d} band" if cons.get("tilt")
                else " → không đủ nghiêng để tilt band")
        lines.append(f"- Consensus {cons['n_reports']} báo cáo: stance cổ phiếu "
                     f"{cp:+.2f}{tail}")
    if lines and directive:
        lines.append(
            "→ Bối cảnh KHUNG THÁNG (phân bổ tài sản trung hạn) — KHÔNG dùng để "
            "đổi Bias/Stance NGÀY; lệch chiều với bias ngày = khung thời gian "
            "khác nhau, không phải mâu thuẫn. KHÔNG bịa band/% ngoài block này.")
    return lines

# ── Khối bảng phân bổ ─────────────────────────────────────────────────────────
def _pct_tail(pct) -> str:
    return f" ({pct:g}% cổ phiếu)" if isinstance(pct, (int, float)) else ""


def _alloc_proposal_text(alloc: dict, *, compact: bool = False) -> str:
    """Câu "band đề xuất" khi kẹp đang giữ — MỘT chỗ cho CLI, tab Phân bổ, brief
    (``compact`` = dạng gọn " B3 30%" cho dòng 💼 của 🔭). Có tilt bị bỏ thì nói
    rõ đề xuất = band dữ liệu + tilt (khỏi trái "(band data)")."""
    cap = alloc.get("capped_by") or {}
    src = (f"band dữ liệu {alloc.get('band_data')} + tilt {cap['tilt']} đề xuất"
           if cap.get("tilt") else "band dữ liệu đề xuất")
    pct = cap.get("proposed_pct")
    tail = ((f" {pct:g}%" if isinstance(pct, (int, float)) else "") if compact
            else _pct_tail(pct))
    return f"{src} {cap.get('proposed_band')}{tail}"


def _alloc_cap_note(alloc: dict) -> str:
    """Đuôi dòng band khi kẹp theo trung hạn đang giữ (P1b-2, #20) — nói rõ band
    hiệu lực KHÁC band dữ liệu là cố ý, để LLM không "sửa" band/% về bảng gốc."""
    if cap := alloc.get("capped_by"):
        return f"; giữ nguyên vì {cap.get('why')} — {_alloc_proposal_text(alloc)}"
    if ramp := alloc.get("ramp"):
        return (f"; ⏳ chờ lên {ramp.get('band')}{_pct_tail(ramp.get('pct'))} — mỗi tuần "
                f"tối đa 1 bậc, tính từ {ramp.get('since')}")
    return ""


def _allocation_table_lines(alloc: dict) -> list[str]:
    """Canonical các dòng bảng % + band cho brief allocation — dùng chung bởi
    prompt block VÀ guard enforce_allocation_table (nguyên tắc #1: LLM không
    sinh số %/band, chỉ hệ thống in bảng)."""
    rows = alloc.get("allocation") or {}
    if not rows or not alloc.get("band"):
        return []
    lines = [f"- {cls}: {pct}%" for cls, pct in rows.items()]
    band_row = (f"- Band: {alloc['band']} ({alloc.get('band_label', '')}) — "
                f"điểm {_score2(alloc.get('score')):+.2f}, phiên {alloc.get('as_of', '?')}")
    rt = alloc.get("report_tilt") or {}
    if rt.get("tilt") and (rt.get("strength") or 1) < 1:
        # 05/10 tilt nhạt dần: % ở trên là TRỘN giữa 2 band, không khớp bảng
        # band nào — nói rõ để LLM không "sửa" về bảng gốc.
        band_row += f" — tỷ trọng trộn: tilt {rt.get('label')}"
    lines.append(band_row + _alloc_cap_note(alloc))
    return lines

# ── Khối 🔭 Góc nhìn theo khung thời gian (P1b-3, #21) ───────────────────────
# `docs/THIET-KE-BRIEF-3-KHUNG.md` §3.9 (bảng việc nên làm), §3.12, §4 (B). Code
# dựng toàn bộ số + nhãn từ bản published 3 khung (`ctx["horizons"]` =
# `vnstock_horizons_state.brief_view`); agent chỉ được ≤1 câu sau "→" ở dòng
# Ngắn hạn / Trung hạn. Mức giá ngoài danh sách đã biết in làm tròn "~1,803".
_HORIZON_TITLE = "## 🔭 Góc nhìn theo khung thời gian"
_HORIZON_TLDR_PREFIX = "**Trung hạn:**"
_HORIZON_TLDR_LINE_RE = re.compile(r"^\s*(?:[-*•]\s*)?\*{0,2}Trung hạn\*{0,2}\s*[:：]",
                                   re.IGNORECASE)   # dòng 3 TLDR, cả bản agent tự viết
_HORIZON_AGENT_PREFIXES = ("- Ngắn hạn (vài phiên):", "- Trung hạn (xu hướng tuần):")
# nhóm T §3.6 có trong registry → nhãn GỌN: dòng có "vĩ mô" + "lãi suất"/"tỷ giá" là
# header lỏng của enforce_macro (nấc 2) — chữ code in không được giống mẫu guard khác bắt
_HORIZON_MACRO_KEYS = {"pmi": ("PMI", "{:.1f}"), "usdvnd": ("USD/VND", "{:,.0f}"),
                       "interbank_1w": ("LNH 1 tuần", "{:.1f}%")}

# (ngắn hạn, trung hạn) → (nhãn cặp khung, việc nên làm) — §3.9; "{x}" = mức kích hoạt
_HORIZON_ACTIONS = {
    (1, 1): ("đồng pha tăng", "giữ tỷ trọng theo band; mua mới ưu tiên khi chỉnh về hỗ trợ"),
    (1, 0): ("nhịp hồi trong xu hướng đi ngang",
             "không nâng tỷ trọng; nếu chốt lời thì chốt phần vượt tỷ trọng"),
    (1, -1): ("nhịp hồi trong xu hướng giảm",
              "dùng nhịp hồi hạ phần vượt tỷ trọng, không mua đuổi"),
    (0, 1): ("nhịp chững trong xu hướng tăng", "giữ phần lõi"),
    (0, 0): ("chưa rõ ở cả hai khung", "giữ nguyên tỷ trọng"),
    (0, -1): ("nhịp chững trong xu hướng giảm", "không bắt đáy theo 1–2 phiên xanh"),
    (-1, 1): ("nhịp chỉnh trong xu hướng tăng",
              "không bán phần lõi; trung hạn chỉ rời TĂNG nếu đóng tuần < {x}"),
    (-1, 0): ("nhịp chỉnh trong xu hướng đi ngang",
              "không bán tháo; trung hạn chuyển GIẢM nếu đóng tuần < {x}"),
    (-1, -1): ("đồng pha giảm", "giữ tỷ trọng thấp; không bắt đáy"),
}
_HORIZON_ACTION_LEVEL = {1: "leave_tang", 0: "to_giam"}


def _hz_ddmm(iso) -> str:
    s = str(iso or "")
    return f"{s[8:10]}/{s[5:7]}" if len(s) >= 10 else "?"


def _hz_approx(x) -> str:
    return f"~{x:,.0f}"


def _hz_signed(n) -> str:
    n = int(round(float(n or 0)))
    return f"{n:+d}" if n else "0"


def _hz_level(snap: dict, kind: str) -> "dict | None":
    return next((lv for lv in snap.get("levels") or [] if lv.get("kind") == kind
                 and isinstance(lv.get("price"), (int, float))), None)


def _hz_weeks(view: dict) -> str:
    """Tuổi trung hạn = số lần ĐÓNG TUẦN mang trạng thái (`brief_view.medium_weeks`).
    "tuần 2 (từ 02/10)" bị đọc thành tuần thứ 2 tính từ 02/10 — mà 13/10 đã là tuần
    thứ 3 (duyệt mẫu 14/10) ⇒ nói thẳng đơn vị đếm."""
    return f"{view.get('medium_weeks') or 1} lần đóng tuần"


def _hz_not_updated(as_of) -> str:
    return (f"- 🔭 chưa cập nhật (as_of {_hz_ddmm(as_of)})." if as_of
            else "- 🔭 chưa cập nhật (chưa đọc được state 3 khung).")


def _horizon_view(ctx: dict) -> "dict | None":
    v = (ctx or {}).get("horizons")
    return v if isinstance(v, dict) else None


def _horizon_change_line(view: dict) -> "str | None":
    """🔁 chỉ khi có tầng đổi so với bản published trước, hoặc trung hạn đang
    chờ xác nhận; luôn nói rõ tầng nào KHÔNG đổi (§3.9)."""
    from vnstock_horizons import MEDIUM_LABEL, SHORT_LABEL, MediumParams
    snap, prev = view["snap"], view.get("prev") or {}
    tier = (snap.get("alert") or {}).get("tier") or 0
    moved, same = [], []
    if prev and prev.get("short") != snap.get("short"):
        moved.append(f"ngắn hạn {SHORT_LABEL.get(prev.get('short'), '?')} → "
                     f"{SHORT_LABEL.get(snap.get('short'), '?')} ({_hz_ddmm(snap.get('short_since'))})")
    else:
        same.append("ngắn hạn")
    if prev and prev.get("medium") != snap.get("medium"):
        moved.append(f"trung hạn {MEDIUM_LABEL.get(prev.get('medium'), '?')} → "
                     f"{MEDIUM_LABEL.get(snap.get('medium'), '?')} ({_hz_ddmm(snap.get('medium_since'))})")
    else:
        same.append("trung hạn")
    ptier = (prev.get("alert") or {}).get("tier") or 0
    if prev and ptier != tier:
        if not tier:
            moved.append("🚨 tắt")
        elif not ptier:
            moved.append(f"🚨 bật mức {tier} ({_hz_ddmm((snap.get('alert') or {}).get('since'))})")
        else:
            moved.append(f"🚨 mức {ptier} → mức {tier}")
    else:
        same.append("🚨")
    if snap.get("pending"):
        nxt = MEDIUM_LABEL.get((snap.get("medium") or 0) + 1) if snap.get("medium") in (-1, 0) \
            else None
        if nxt:
            moved.append(f"⏳ trung hạn chờ xác nhận lên {nxt} "
                         f"({snap['pending']}/{MediumParams().up_weeks} tuần)")
    if not moved:
        return None
    tail = ""
    if same:
        names = f"{', '.join(same[:-1])} và {same[-1]}" if len(same) > 1 else same[0]
        tail = f" {names[:1].upper()}{names[1:]} không đổi."
    return f"- 🔁 Thay đổi: {'; '.join(moved)}.{tail}"


def _horizon_short_line(view: dict, ctx: dict) -> str:
    from vnstock_horizons import CHINH, HOI, SHORT_LABEL, short_threshold
    snap = view["snap"]
    short, score, n = snap.get("short"), snap.get("score") or 0, snap.get("n") or 0
    line = (f"- Ngắn hạn (vài phiên): {SHORT_LABEL.get(short, '?')}, phiên thứ "
            f"{view.get('short_sessions') or 1} (từ {_hz_ddmm(snap.get('short_since'))}); "
            f"điểm kỹ thuật ngày {_hz_signed(score)}/{n}")
    mood = ((ctx.get("market_sentiment") or {}).get("mood") or "").strip()
    if mood:
        line += f"; tâm lý {mood}"
    if short == CHINH:
        return line + ". Hết nhịp chỉnh khi điểm về ≥ 0."
    if short == HOI:
        return line + ". Hết nhịp hồi khi điểm về ≤ 0."
    thr = short_threshold(n) if n else 0
    return line + (f". Vào nhịp hồi khi điểm ≥ +{thr}, nhịp chỉnh khi ≤ -{thr}."
                   if thr else ".")


def _horizon_macro_snippet(ctx: dict) -> str:
    """Nhóm T (§3.6) ở P1b: chỉ SỐ + CHIỀU 1 kỳ, CHƯA chấm độ tin cậy. Công tắc
    VNSTOCK_HORIZON_MACRO chốt vào ``horizons["macro"]`` lúc dựng ctx (pack
    --from-file dựng lại đúng khối prompt đã thấy). Số ≤1 chữ số lẻ — 2 chữ số
    lẻ là dạng của mức chỉ số, guard giá soi."""
    if (_horizon_view(ctx) or {}).get("macro") is False:
        return ""
    rows = {m.get("key"): m for m in ctx.get("macro") or [] if isinstance(m, dict)}
    parts = []
    for key, (label, fmt) in _HORIZON_MACRO_KEYS.items():
        m = rows.get(key)
        if not m or not isinstance(m.get("value"), (int, float)):
            continue
        d = (m.get("change") or {}).get("dir") or 0
        parts.append(f"{label} {fmt.format(m['value'])}" + (" ▲" if d > 0 else " ▼" if d < 0 else ""))
    return f" Vĩ mô (chưa chấm): {' · '.join(parts)}." if parts else ""


def _horizon_medium_line(view: dict, ctx: dict) -> str:
    from vnstock_horizons import MEDIUM_LABEL
    snap = view["snap"]
    line = (f"- Trung hạn (xu hướng tuần): {MEDIUM_LABEL.get(snap.get('medium'), '?')} "
            f"từ {_hz_ddmm(snap.get('medium_since'))} ({_hz_weeks(view)})")
    b, b4 = view.get("breadth_pct"), view.get("breadth_pct_4w")
    if isinstance(b, (int, float)):
        line += f"; {b:.0f}% mã trên MA200"
        if isinstance(b4, (int, float)):
            line += f" (4 tuần trước {b4:.0f}%)"
    return line + "." + _horizon_macro_snippet(ctx)


def _horizon_alert_line(snap: dict) -> str:
    from vnstock_horizons import GIAM, AlertParams
    al = snap.get("alert") or {}
    tier, anchor = al.get("tier") or 0, al.get("anchor")
    if not tier:
        return "- 🚨 Rủi ro ngắn hạn: tắt."
    line = (f"- 🚨 Rủi ro ngắn hạn: BẬT mức {tier} từ {_hz_ddmm(al.get('since'))}" if tier == 1
            else f"- 🚨 Rủi ro ngắn hạn: BẬT từ {_hz_ddmm(al.get('since'))}, đã lên mức {tier}")
    if isinstance(anchor, (int, float)):
        line += f", neo đỉnh {_hz_approx(anchor)}"
        if tier == 1:
            p = AlertParams()
            line += (f"; lên mức 2 nếu đóng < {_hz_approx(anchor * p.tier2_frac)} "
                     f"({p.tier2_frac:.0%} neo) hoặc thêm 1 phiên ≤ {p.day_drop}%")
    # trung hạn đã GIẢM thì "không đổi xu hướng" là câu thừa (duyệt mẫu 14/10)
    return line + ("." if snap.get("medium") == GIAM else ". Không đổi xu hướng.")


def _horizon_cap_text(alloc: dict) -> str:
    """Đuôi dòng 💼 khi kẹp #20 đang giữ / ⏳ đang leo — cùng câu chữ với 📚."""
    if (cap := alloc.get("capped_by")):
        return f"; {_alloc_proposal_text(alloc, compact=True)} — giữ vì {cap.get('why')}"
    if (ramp := alloc.get("ramp")):
        pct = ramp.get("pct")
        pct_s = f" {pct:g}%" if isinstance(pct, (int, float)) else ""
        return f"; ⏳ chờ lên {ramp.get('band')}{pct_s}, mỗi tuần tối đa 1 bậc"
    return ""


def _horizon_advice(snap: dict) -> "tuple[str, str]":
    """(nhãn cặp khung, việc nên làm) theo bảng §3.9 — MỘT chỗ cho 🔭 💼 và header
    Telegram; ô có "~X" điền mức kích hoạt (thiếu mức ⇒ bỏ vế đó)."""
    key = (snap.get("short"), snap.get("medium"))
    label, advice = _HORIZON_ACTIONS.get(key, _HORIZON_ACTIONS[(0, 0)])
    if "{x}" in advice:
        lv = _hz_level(snap, _HORIZON_ACTION_LEVEL.get(snap.get("medium"), ""))
        advice = (advice.format(x=_hz_approx(lv["price"]))
                  + ("" if lv.get("reachable") else _hz_unreachable(snap)) if lv
                  else advice.split(";")[0])
    return label, advice


def _horizon_portfolio_line(snap: dict, ctx: dict) -> str:
    label, advice = _horizon_advice(snap)
    alloc = ctx.get("allocation") or {}
    pct = (alloc.get("allocation") or {}).get("Cổ phiếu")
    head = "- 💼 "
    if isinstance(pct, (int, float)) and alloc.get("band"):
        head += f"Cổ phiếu {pct:g}% (band {alloc['band']}{_horizon_cap_text(alloc)}). "
    return f"{head}Nên ({label}): {advice}."


def _horizon_body_lines(ctx: dict) -> list[str]:
    """Thân khối 🔭 (≤6 gạch, KHÔNG tiêu đề) — dùng chung prompt + guard."""
    view = _horizon_view(ctx)
    if view is None:
        return []
    if view.get("stale") or not isinstance(view.get("snap"), dict):
        return [_hz_not_updated(view.get("as_of"))]
    snap = view["snap"]
    lines = [_horizon_change_line(view), _horizon_short_line(view, ctx),
             _horizon_medium_line(view, ctx),
             "- Dài hạn (6–12 tháng): đang thu thập — chỉ đọc theo trung hạn.",
             _horizon_alert_line(snap), _horizon_portfolio_line(snap, ctx)]
    return [ln for ln in lines if ln]


def _horizon_render(ctx: dict) -> "tuple[list[str], str | None]":
    """(thân 🔭, TLDR dòng 3) cho prompt + guard. Snapshot dị dạng (trường thiếu /
    sai kiểu) ⇒ "🔭 chưa cập nhật", KHÔNG làm sập cả brief."""
    try:
        return _horizon_body_lines(ctx), _horizon_tldr_line(ctx)
    except Exception:
        view = _horizon_view(ctx) or {}
        as_of = view.get("as_of") or (view.get("snap") or {}).get("as_of")
        return [_hz_not_updated(as_of)], None


def _hz_week_word(snap: dict) -> str:
    """Mức kích hoạt tính trên các tuần ĐÃ CHỐT: thứ Sáu (tuần vừa chốt) thì mức
    là của tuần TỚI, giữa tuần là của tuần NÀY."""
    return "tuần tới" if snap.get("week_closed") else "tuần này"


def _hz_unreachable(snap: dict) -> str:
    return f" (chưa thể trong {_hz_week_word(snap)})"


def _horizon_morning_line(ctx: dict) -> "str | None":
    """Gạch 🔭 trong TLDR brief SÁNG (mẫu §4 D, P1b-6) — trạng thái của bản
    published phiên trước, không bao giờ đổi trong phiên. None khi công tắc tắt."""
    from vnstock_horizons import MEDIUM_LABEL, SHORT_LABEL
    view = _horizon_view(ctx)
    if view is None:
        return None
    if view.get("stale") or not isinstance(view.get("snap"), dict):
        return _hz_not_updated(view.get("as_of"))
    snap = view["snap"]
    parts = [f"Trung hạn {MEDIUM_LABEL.get(snap.get('medium'), '?')} "
             f"({_hz_weeks(view)})",
             f"ngắn hạn: {SHORT_LABEL.get(snap.get('short'), '?')} "
             f"(phiên {view.get('short_sessions') or 1})"]
    pct = ((ctx.get("allocation") or {}).get("allocation") or {}).get("Cổ phiếu")
    if isinstance(pct, (int, float)):
        parts.append(f"💼 {pct:g}%")
    rule = snap.get("stance") or {}
    bias = (f"Bias {rule['forced']}" if rule.get("forced")
            else f"Bias chỉ {'/'.join(rule.get('allowed') or [])}" if rule.get("allowed") else "")
    if (ctx.get("defensive") or {}).get("level") == "cứng":
        bias += ("; " if bias else "") + "không BUY vô điều kiện"
    return "- 🔭 " + " · ".join(parts) + (f" — {bias}" if bias else "")


def _horizon_tldr_line(ctx: dict) -> "str | None":
    """TLDR dòng 3 "**Trung hạn:** …" (code viết, guard ghim); None khi state cũ.
    Số tuần còn cần để lên bậc trừ đi ``pending`` (tuần đọc đã có)."""
    from vnstock_horizons import DI_NGANG, GIAM, MEDIUM_LABEL, TANG, MediumParams
    view = _horizon_view(ctx)
    if view is None or view.get("stale") or not isinstance(view.get("snap"), dict):
        return None
    snap = view["snap"]
    med = snap.get("medium")
    need = max(1, MediumParams().up_weeks - int(snap.get("pending") or 0))
    wk = _hz_week_word(snap)

    def lv_txt(kind: str, fmt: str) -> str:
        lv = _hz_level(snap, kind)
        if lv is None:
            return ""
        tail = "" if lv.get("reachable") else _hz_unreachable(snap)
        return fmt.format(x=_hz_approx(lv["price"])) + tail

    def up_txt(kind: str, many: str, one: str) -> str:
        """Câu lên bậc: còn ≥2 tuần ⇒ ``many``; chỉ còn 1 tuần ⇒ ``one`` + đã có."""
        if need > 1:
            return lv_txt(kind, many.format(n=need, x="{x}"))
        return lv_txt(kind, one.format(wk=wk, x="{x}") + f" (đã có {snap.get('pending')}/"
                      f"{MediumParams().up_weeks} tuần)")

    head = (f"{_HORIZON_TLDR_PREFIX} {MEDIUM_LABEL.get(med, '?')} từ "
            f"{_hz_ddmm(snap.get('medium_since'))} → ")
    if med == GIAM:
        lv = _hz_level(snap, "leave_giam")
        tail = ""
        if lv:
            tail = "; " + up_txt("leave_giam", "chỉ rời GIẢM khi {n} tuần liền đóng trên {x}",
                                 "rời GIẢM nếu {wk} đóng trên {x}")
            if lv.get("reachable"):
                tail += f" (mức {wk}, tính lại mỗi tuần)" if need > 1 else ""
        return head + "không mua đuổi nhịp hồi" + tail + "."
    if med == DI_NGANG:
        parts = [p for p in (lv_txt("to_giam", "chuyển GIẢM nếu đóng tuần < {x}"),
                             up_txt("to_tang", "lên TĂNG cần {n} tuần đọc > {x}",
                                    "lên TĂNG nếu {wk} đọc > {x}")) if p]
        return head + "; ".join(["không nâng tỷ trọng theo nhịp hồi"] + parts) + "."
    if med == TANG:
        parts = [p for p in (lv_txt("leave_tang", "chỉ rời TĂNG nếu đóng tuần < {x}"),) if p]
        return head + "; ".join(["giữ tỷ trọng theo band"] + parts) + "."
    return None

# ── Khối danh mục đang giữ ────────────────────────────────────────────────────
def _portfolio_fact_line(p: dict) -> str:
    """Canonical fact line for one held position — shared by the prompt block and
    enforce_portfolio_facts so the qty/vốn/hiện/lãi numbers are fabrication-proof."""
    line = f"- {p['ticker']}: {p['qty']:,.0f} cp | vốn {p['buy_price']:,.2f}"
    if p.get("last_close"):
        line += f" | hiện {p['last_close']:,.2f}"
    if p.get("pnl_pct") is not None:
        word = "lãi" if p["pnl_pct"] >= 0 else "lỗ"
        line += f" | {word} {p['pnl_pct']:+,.1f}%"
    if isinstance(p.get("above_ma50"), bool):        # P1b-5: chỉ có khi VNSTOCK_HORIZONS bật
        line += " | trên MA50" if p["above_ma50"] else " | dưới MA50"
    return line

# ── Khung GTGD phiên đóng cửa ─────────────────────────────────────────────────
def _gtgd_close_frame(ctx: dict) -> "tuple[float | None, dict, str]":
    """(F, cmp, frame) — MỘT KHUNG DUY NHẤT cho GTGD cả ngày của close brief,
    DÙNG CHUNG bởi build_prompt + enforce_gtgd_total / enforce_gtgd_compare_
    frame / enforce_gtgd_baseline_pct (parity by construction).

    Fix 21/07: close 16:18 in "GTGD 20,453.9 tỷ (+0% vs TB20)" — SỐ lấy từ
    capture WSS còn % bị guard pin theo khung EOD (14,878.9 / TB20 14,869.6);
    bản 01:22 "+28%" cùng họ lỗi. Hai khung lệch hệ thống ~20-40% (WSS đủ
    sàn, EOD Σ giá×KLGD subset mã đã sync) nên % cross-frame vô nghĩa.

    Ưu tiên WSS-với-WSS (capture 9h-15h hợp lệ + baseline ``full_wss_gtgd``
    cùng cửa sổ); WSS có số nhưng KHÔNG có lịch sử trong khi EOD đủ bộ số+cmp
    → dùng TRỌN khung EOD; còn lại WSS trơ (không %) rồi mới tới EOD trơ.
    frame ∈ {"wss", "eod", ""} để prompt dán nhãn nguồn."""
    w = dict(ctx.get("full_wss_gtgd") or {})
    if not w.get("today"):
        ss = ctx.get("session_stats") or {}

        def _g(window):
            v = (ss.get(window, {}).get("VNINDEX", {}) or {}).get("gtgd")
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        full, morn = _g("9h-15h"), _g("9h-11h30")
        if full and full > 0 and (not morn or full > morn * 1.05):
            w = {"today": full}
    try:
        eod_f = float(ctx["full_day_gtgd"]) if ctx.get("full_day_gtgd") else None
    except (TypeError, ValueError):
        eod_f = None
    eod_cmp = dict(ctx.get("full_day_gtgd_cmp") or {})
    if w.get("today"):
        cmp = {k: w[k] for k in ("prev", "avg5", "avg20") if w.get(k)}
        if cmp or not (eod_f and eod_cmp):
            return float(w["today"]), cmp, "wss"
        return eod_f, eod_cmp, "eod"   # WSS thiếu lịch sử, EOD đủ bộ → trọn EOD
    if eod_f:
        return eod_f, eod_cmp, "eod"
    return None, {}, ""


# ── Mục "⚠️ Rủi ro cần lưu ý" theo PHƠI NHIỄM (risk_today, 06/10) ─────────────
# Đặc tả: docs/THIET-KE-MUC-RUI-RO.md. Khối cũ (top D/E · Op.CF toàn vũ trụ) lặp
# y hệt nhiều tháng vì số BCTC năm đứng yên và phép chọn là xếp hạng cực trị
# trên nhóm ổn định. Mục mới do CODE dựng từ thứ user ĐANG phơi nhiễm hôm nay
# (danh mục 📌, lệnh mở ở footer, ngành của chúng, GDKHQ, tiền tệ/khối ngoại
# biến động mạnh); model chỉ được thêm ≤1 dòng KHÔNG chữ số. Hằng ở đây dùng
# chung cho prompt (khối "Dữ kiện rủi ro hôm nay") và guard `enforce_risk_today`.
# Mọi ngưỡng chỉ chỉnh SAU khi sổ brief_watch đếm đủ mẫu (R17).

# Từ khoá CƠ BẢN — #8 cũ dùng tuple cục bộ y hệt; nay một nơi.
_FUND_KW = ("d/e", "op.cf", "lưu chuyển tiền", "lưu lượng tiền", "hđkd",
            "đòn bẩy", "quỹ đất")
_RISK_AGENT_DROP_KW = _FUND_KW + ("nợ vay", "kiệt quệ", "margin", "ký quỹ", "roe")
# Tiền tố CỐ ĐỊNH của dòng do code in — guard nhận diện bằng tiền tố nên chạy
# lại chuỗi guard bao nhiêu lần cũng ra y hệt (gỡ theo tiền tố rồi dựng lại).
# Bảng cực trị D/E · Op.CF in lại CHỈ khi có KỲ BCTC MỚI (U75 pha 2, câu 1 = b).
_RISK_PERIOD_PREFIX = "- Kỳ BCTC mới"
# Mục 🪙 (P5 đa tài sản, U86) — tiêu đề dùng chung cho khối prompt (vnstock_assets_brief) và guard
# enforce_assets_section; thân mục là dòng CODE dựng (ctx["assets_lines"]).
_ASSETS_SECTION_TITLE = "## 🪙 Hàng hoá & Tiền tệ"
_RISK_LINE_PREFIXES = (
    "- Danh mục tập trung", "- Mã đang giữ", "- GDKHQ chạm", "- Tiền tệ xấu đi",
    "- Khối ngoại bán ròng mạnh", "- Cơ bản lệnh mới", "- Không có rủi ro mới",
    _RISK_PERIOD_PREFIX,
)
_RISK_FALLBACK_LINE = ("- Không có rủi ro mới chạm danh mục hay lệnh đang mở "
                       "trong phiên này.")
# Thay ĐÚNG đoạn luật D/E/Op.CF trong hai template (không chứa ngoặc nhọn vì
# template còn `.format`).
_RISK_TODAY_RULES = (
    "[Hệ thống TỰ IN các dòng có số của mục này từ block \"Dữ kiện rủi ro hôm nay\" "
    "— KHÔNG chép lại các dòng đó, KHÔNG tự viết số.]\n"
    "Được viết THÊM TỐI ĐA 1 dòng nhận định KHÔNG chứa chữ số nào, chỉ về mã/ngành "
    "trong danh mục đang giữ hoặc lệnh đang mở (vd rủi ro chung của danh mục). "
    "KHÔNG nêu D/E, Op.CF, đòn bẩy, dòng tiền HĐKD, quỹ đất, nợ vay, margin; KHÔNG "
    "nêu mã ngoài danh mục/lệnh mở; KHÔNG lặp lại khối ngoại/GDKHQ/tỷ giá mà dòng "
    "hệ thống đã nói. Không có gì đáng thêm thì bỏ trống — hệ thống tự ghi."
)
_RISK_MAX_LINES = 4
_RISK_TIER_CAPS = {"P": 2, "M": 2, "R": 2, "F": 1}
_RISK_CLUSTER_SHARE = 0.50          # một cụm ≥ 50% giá trị danh mục
_RISK_SECTOR_TOP_SELL = 3           # top-3 ngành NN 1T âm nhất
_RISK_CLUSTER_NN_SELL_TY = -500.0   # hoặc Σ NN 1T ngành dòng tiền của cụm ≤ −500 tỷ
_RISK_TICKER_NN_SELL_TY = -50.0     # NN 1T của CHÍNH mã đang giữ
_RISK_HELD_SHOCK_1D_PCT = -3.0      # mã đang giữ giảm ≥ 3% trong phiên
_RISK_HELD_WEEK_PCT = -7.0          # … hoặc ≥ 7% sau 5 phiên
_RISK_PEER_WEEK_PCT = -5.0          # mã cùng ngành gốc giảm ≥ 5% sau 5 phiên
_RISK_EXDATE_DAYS = 3
_RISK_FX_PCT = 0.30                 # USD/VND tăng ≥ 0,30%
_RISK_ON_DELTA = 1.00               # LNH qua đêm tăng ≥ 1 điểm %
_RISK_10Y_DELTA = 0.15              # lợi suất TPCP 10Y tăng ≥ 0,15 điểm %
_RISK_MACRO_MAX_AGE_DAYS = 5
_RISK_NN_1D_HEAVY_TY = -1000.0      # NN ròng 1D toàn thị trường
_RISK_FUND_DE_MIN = 1.5
_RISK_NEW_REC_DAYS = 1
_RISK_REPEAT_WARN = 0.5             # badge doctor: mục Rủi ro trùng phiên trước ≥ 50%
# R11 — dòng code đi qua ~29 guard phía sau và không được dẫm lên brief 3 khung.
_RISK_FORBIDDEN_VOCAB = (
    "🚨", "💼", "🔭", "đỉnh 20 phiên", "MA50", "MA200", "band", "Risk-on",
    "Risk-off", "Trung hạn", "Ngắn hạn", "cao nhất", "momentum", "tâm lý", "GTGD",
    "thanh khoản", "đóng cửa", "so với phiên trước", "thấp hơn", "cao hơn", "vĩ mô",
    "kỷ lục", "bắt buộc", "BUY", "entry=",
)


def _fmt_footer_price(p: float) -> str:
    """Giá lệnh (đơn vị NGHÌN) — y hệt footer Telegram (`vnstock_telegram._fmt_price`
    gọi lại hàm này): mã giá thấp giữ đủ chữ số có nghĩa thay vì "@1"/"@0"."""
    a = abs(p)
    if a == 0:
        return "0"
    if a < 1:
        return f"{p:,.3f}"
    if a < 10:
        return f"{p:,.2f}"
    return f"{p:,.0f}"


def _fmt_adj_price(p: float) -> str:
    """Giá quy đổi quyền: tối đa 2 số lẻ, bỏ số 0 thừa — 52.0 → '52', 23.5 → '23.5'."""
    return f"{p:,.2f}".rstrip("0").rstrip(".")
