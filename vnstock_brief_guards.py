"""Chuỗi guard hậu kiểm brief — ĐIỂM PARITY sáng/chiều, và mục lục của hệ guard.

⚠️ BẤT BIẾN (CLAUDE.md): `apply_brief_guards(text, ctx)` là **điểm parity duy
nhất** — brief sáng và brief chiều đi qua ĐÚNG một chuỗi này. KHÔNG BAO GIỜ
inline lại chuỗi vào `generate_brief`. Thêm guard = viết ở module chủ đề tương
ứng + NỐI VÀO chuỗi dưới đây + viết test (guard quên nối = code chết trông y
như code sống; `tests/test_brief_split.py` canh cả hai chiều).

Vì sao guard tồn tại: LLM hay phớt chỉ thị prompt, nên mọi ràng buộc quan trọng
phải chốt bằng code deterministic hậu kiểm, không phải bằng câu chữ trong prompt.

44 guard chia theo CHỦ ĐỀ (12/08, mục ④ — file này từng là 2.646 dòng):

* `vnstock_brief_guards_sections` — brief nói SAI CHUYỆN GÌ (dựng lại khối canon)
* `vnstock_brief_guards_numbers`  — brief nói SAI SỐ / SAI CHIỀU
* `vnstock_brief_guards_text`     — brief lộ ruột hoặc nói nhảm (vệ sinh chữ)
* `vnstock_brief_guards_common`   — tiện ích cả ba nhóm dùng

File này giữ CHUỖI + validator hallucination, và re-export mọi tên để đường
import cũ (`from vnstock_brief import enforce_...`) không đổi.

Phụ thuộc một chiều: brief → guards → {sections, numbers, text} → common/canon.
Ba module chủ đề KHÔNG import lẫn nhau và KHÔNG import file này.
"""
from __future__ import annotations

import re as _re



from vnstock_brief_guards_common import (  # noqa: F401  (re-export)
    _PIVOT_LABEL_RE,
    _SECTION_EMOJIS,
    _is_section_start,
    _parse_vn_number,
    brief_section,
)

from vnstock_brief_guards_sections import (  # noqa: F401  (re-export)
    _ALLOC_HORIZON_CAVEAT,
    _BUY_BIAS_CAVEAT,
    _STANCE_CAUTION_MARK,
    _STANCE_CAUTION_MOMENTUM,
    _WL_META_RE,
    _canonical_risk_lines,
    enforce_allocation_table,
    enforce_buy_vs_bias_caveat,
    enforce_lead_lag,
    enforce_liquidity_label,
    enforce_macro,
    enforce_macro_fx_pct,
    enforce_macro_reports,
    enforce_market_news,
    enforce_money_flow_two_sides,
    enforce_net_flow_label,
    enforce_nn_frame_labels,
    enforce_nn_window_label,
    enforce_portfolio_facts,
    enforce_realestate_ocf_context,
    enforce_risk_section,
    enforce_sector_nn_figures,
    enforce_stance_sentiment_caution,
    enforce_unvalidated_strategy_caveat,
    enforce_upcoming_events,
    enforce_watchlist_eligibility,
    enforce_watchlist_hygiene,
)

from vnstock_brief_guards_numbers import (  # noqa: F401  (re-export)
    _MA200_CALL_IT_WEAK,
    _GTGD_CTX_RE,
    _GTGD_SUBJECT_RE,
    _MOOD_EMOJIS,
    _MOOD_WORDS,
    _MORNING_CMP_RE,
    _MORNING_LABEL_CLAUSE,
    _MORNING_LABEL_CMP_RE,
    enforce_breadth_label,
    enforce_breadth_quality,
    enforce_change_verb_sign,
    enforce_compare_direction,
    enforce_gtgd_baseline_pct,
    enforce_gtgd_compare_frame,
    enforce_gtgd_total,
    enforce_number_format,
    enforce_pivot_labels,
    enforce_range_position,
    enforce_risk_numbers,
    enforce_scenario_levels,
    enforce_sentiment_consistency,
    enforce_session_direction,
    enforce_sr_direction,
    enforce_vnindex_change,
)

from vnstock_brief_guards_text import (  # noqa: F401  (re-export)
    _CONSTRAINT_NOTATION_RE,
    _CJK_RE,
    _COMPOSITE_LEAK_RE,
    _INSTR_LEAK_RE,
    _PLACEHOLDER_LEAK_RE,
    enforce_composite_rotation_hygiene,
    enforce_no_bias_directive_leak,
    enforce_no_cjk,
    enforce_no_composite_jargon,
    enforce_no_constraint_notation,
    enforce_no_duplicate_momentum,
    enforce_no_instruction_leak,
    enforce_no_placeholder_leak,
    enforce_no_record_superlative,
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

_VNI_MAGNITUDE_RE = _re.compile(r"\b([12][.,]?\d{3}(?:[.,]\d{1,2})?)\b")

_VNI_CONTEXT_RE = _re.compile(r"VN[\s\-]?INDEX|VN-?I(?![A-Z])|VNI(?![A-Z])", _re.IGNORECASE)

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
    fixed = enforce_unvalidated_strategy_caveat(fixed, ctx)  # chiến lược trượt kiểm định → nói ra
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
    fixed = enforce_no_constraint_notation(fixed, ctx)  # '(entry < TP > SL)' là chữ cho model
    fixed = enforce_no_composite_jargon(fixed, ctx)
    fixed = enforce_composite_rotation_hygiene(fixed, ctx)  # no bucket↔label clash / 'Net BS'
    fixed = enforce_no_bias_directive_leak(fixed, ctx)   # 'bắt buộc' is internal
    fixed = enforce_no_record_superlative(fixed, ctx)    # no all-time GTGD claim
    fixed = enforce_no_duplicate_momentum(fixed, ctx)    # state momentum once
    fixed = enforce_range_position(fixed, ctx)
    fixed = enforce_number_format(fixed, ctx)            # one number convention (EN)
    return fixed
