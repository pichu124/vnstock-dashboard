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

Module thuần: không import gì ngoài stdlib, nên `vnstock_brief` và
`vnstock_brief_guards` cùng import được mà không tạo vòng.
"""
from __future__ import annotations


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
    # Chứng khoán
    "SSI", "VND", "HCM", "VCI", "VIX", "SHS", "MBS", "FTS", "BSI", "CTS",
    "AGR", "ORS", "VDS", "TVS", "APG",
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
        title = (it.get("title") or "").strip()
        src = it.get("source_feed", "")
        line = f"- {icon} [{d}] {title}" + (f" ({src})" if src else "")
        if it.get("_impact"):
            line += f" — tác động: {it['_impact']}"
        lines.append(line)
    if directive:
        lines.append(
            "→ DÙNG các tin trên khi đánh giá bối cảnh vĩ mô + rủi ro; gắn tin với "
            "ngành/cổ phiếu liên quan nếu có. 🟢=tích cực /🔴=tiêu cực cho TTCK. "
            "TUYỆT ĐỐI KHÔNG bịa tin/tiêu đề ngoài danh sách này."
        )
    return lines

# ── Khối báo cáo vĩ mô (P4) ───────────────────────────────────────────────────
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
                     f"{alloc.get('score', 0):+.2f}, phiên {alloc.get('as_of', '?')}")
        rt = alloc.get("report_tilt") or {}
        if rt.get("tilt"):
            band_line += (f"; đã gồm tilt {rt['tilt']:+d} từ báo cáo "
                          f"(band data: {alloc.get('band_data')})")
        lines.append(band_line)
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
def _allocation_table_lines(alloc: dict) -> list[str]:
    """Canonical các dòng bảng % + band cho brief allocation — dùng chung bởi
    prompt block VÀ guard enforce_allocation_table (nguyên tắc #1: LLM không
    sinh số %/band, chỉ hệ thống in bảng)."""
    rows = alloc.get("allocation") or {}
    if not rows or not alloc.get("band"):
        return []
    lines = [f"- {cls}: {pct}%" for cls, pct in rows.items()]
    lines.append(f"- Band: {alloc['band']} ({alloc.get('band_label', '')}) — "
                 f"điểm {alloc.get('score', 0):+.2f}, phiên {alloc.get('as_of', '?')}")
    return lines

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
