"""Tests for vnstock_brief — accuracy evaluator + helpers."""

from __future__ import annotations

from datetime import date as _date

import pandas as pd
import pytest

from datetime import datetime as _datetime, timedelta as _timedelta

from vnstock_brief import (
    _detect_stance, _extract_section, evaluate_brief_accuracy,
    agent_accuracy_summary, _load_vn30_fundamentals, _vn30_fund_block,
    build_prompt, _recommendation_block, _fmt_rec_price,
    _augment_with_live_vnindex, market_data_freshness,
    _auto_refresh_market_overview, _bias_floor_dir, _maybe_reconcile_overdue,
    _select_liquid_movers,
)


# ─── _extract_section ─────────────────────────────────────────────────────────

def test_extract_section_finds_tldr():
    text = "## 🎯 TLDR\nBias: TĂNG.\n## Tổng quan\nBody."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out
    assert "Body" not in out


def test_extract_section_case_insensitive():
    text = "## tldr\nBias: TĂNG."
    out = _extract_section(text, "TLDR")
    assert "Bias: TĂNG" in out


def test_extract_section_returns_empty_when_missing():
    text = "## Other\nNo TLDR here."
    assert _extract_section(text, "TLDR") == ""


# ─── _detect_stance ───────────────────────────────────────────────────────────

def test_detect_stance_explicit_bullish():
    tldr = "Stance ngày mai: TĂNG — giữ vị thế dài."
    assert _detect_stance(tldr) == "bullish"


def test_detect_stance_explicit_bearish():
    tldr = "Stance ngày mai: GIẢM — chuyển phòng thủ."
    assert _detect_stance(tldr) == "bearish"


def test_detect_stance_explicit_neutral():
    tldr = "Stance ngày mai: TRUNG TÍNH — đứng ngoài."
    assert _detect_stance(tldr) == "neutral"


def test_detect_stance_unknown_when_no_signal():
    tldr = "Some text without stance keywords."
    assert _detect_stance(tldr) == "unknown"


def test_detect_stance_canonical_line_beats_fallback():
    """Explicit 'Stance ngày mai: TRUNG TÍNH' wins over bullish keywords elsewhere."""
    tldr = (
        "Phiên trầm lắng. Một số mã tích cực.\n"
        "Stance ngày mai: TRUNG TÍNH — đứng ngoài chờ tín hiệu."
    )
    assert _detect_stance(tldr) == "neutral"


# ─── evaluate_brief_accuracy ──────────────────────────────────────────────────

def _mk_closes() -> pd.Series:
    """Build a deterministic VNINDEX close series for tests."""
    dates = pd.bdate_range("2026-05-20", periods=10)
    values = [1200, 1210, 1215, 1218, 1220, 1230, 1228, 1235, 1240, 1250]
    return pd.Series(values, index=[d.date() for d in dates])


def test_evaluate_returns_unknown_when_no_output():
    out = evaluate_brief_accuracy({"output": "", "brief_date": "2026-05-22"})
    assert out["stance"] == "unknown"
    assert out["match"] is None


def test_evaluate_bullish_correct_match():
    """Bullish brief on day where T+1 close is up → match=True.
    closes: 2026-05-26 (Tue) = 1220, 2026-05-27 (Wed) = 1230 → +0.82% up.
    """
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG — bullish.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bullish"
    assert out["actual"] == "up"
    assert out["match"] is True


def test_evaluate_bearish_incorrect_match():
    """Bearish brief on day where T+1 is up → match=False."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: GIẢM — bearish bias.",
        "brief_date": "2026-05-26",
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["stance"] == "bearish"
    assert out["actual"] == "up"
    assert out["match"] is False


def test_evaluate_returns_none_match_when_not_enough_data():
    """Brief at the latest available date can't be evaluated yet."""
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": closes.index[-1].isoformat(),
    }
    out = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    assert out["match"] is None


def test_evaluate_flat_when_under_threshold():
    closes = _mk_closes()
    # Tighten threshold so 0.82% move counts as flat
    brief = {
        "output": "## TLDR\nStance ngày mai: TRUNG TÍNH.",
        "brief_date": "2026-05-26",  # baseline=1220, T+1=1230 → +0.82%
    }
    out = evaluate_brief_accuracy(
        brief, closes=closes, horizon_days=1, neutral_threshold_pct=1.0,
    )
    assert out["actual"] == "flat"
    assert out["match"] is True   # neutral stance vs flat → match


def test_evaluate_horizon_2_uses_2nd_close_after():
    closes = _mk_closes()
    brief = {
        "output": "## TLDR\nStance ngày mai: TĂNG.",
        "brief_date": "2026-05-26",
    }
    out1 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=1)
    out2 = evaluate_brief_accuracy(brief, closes=closes, horizon_days=2)
    assert out1["eval_close"] != out2["eval_close"]


# ─── agent_accuracy_summary ───────────────────────────────────────────────────

def test_summary_groups_by_agent_name():
    closes = _mk_closes()
    briefs = [
        {"agent_name": "Groq", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Groq", "brief_date": "2026-05-27",
         "output": "## TLDR\nStance ngày mai: TĂNG."},
        {"agent_name": "Mistral", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: GIẢM."},
    ]
    # Patch the loader so the summary uses our deterministic closes
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert "Groq" in out and "Mistral" in out
    assert out["Groq"]["n_total"] == 2
    assert out["Mistral"]["n_total"] == 1


def test_summary_accuracy_is_match_over_evaluated():
    """2026-05-26 → 2026-05-27 up (+0.82%); 2026-05-28 → 2026-05-29 up (+0.55%)."""
    closes = _mk_closes()
    briefs = [
        {"agent_name": "A", "brief_date": "2026-05-26",
         "output": "## TLDR\nStance ngày mai: TĂNG."},  # actual up → match
        {"agent_name": "A", "brief_date": "2026-05-28",
         "output": "## TLDR\nStance ngày mai: GIẢM."},  # actual up → miss
    ]
    import vnstock_brief
    orig = vnstock_brief._load_vnindex_closes
    vnstock_brief._load_vnindex_closes = lambda: closes
    try:
        out = agent_accuracy_summary(briefs, horizon_days=1)
    finally:
        vnstock_brief._load_vnindex_closes = orig

    assert out["A"]["n_evaluated"] == 2
    assert out["A"]["n_match"] == 1
    assert out["A"]["accuracy"] == pytest.approx(0.5)


# ─── VN30 fundamentals (D/E, ROE, operating cash flow) ────────────────────────

def _write_fund_parquet(tmp_path, rows: list[dict]):
    import pyarrow as pa
    import pyarrow.parquet as pq
    df = pd.DataFrame(rows)
    p = tmp_path / "fundamentals.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), str(p))
    return p


def test_load_vn30_fundamentals_filters_to_vn30(tmp_path):
    p = _write_fund_parquet(tmp_path, [
        {"ticker": "VCB", "debt_to_equity": 0.8, "roe": 18.0,
         "operating_cf": 12000.0, "updated_at": "2026-06-01"},
        {"ticker": "FPT", "debt_to_equity": 1.1, "roe": 25.0,
         "operating_cf": 8000.0, "updated_at": "2026-06-01"},
        # Not in VN30 → must be excluded
        {"ticker": "ZZZ", "debt_to_equity": 5.0, "roe": 1.0,
         "operating_cf": -50.0, "updated_at": "2026-06-01"},
    ])
    out = _load_vn30_fundamentals(path=p, vn30={"VCB", "FPT"})
    assert set(out.keys()) == {"VCB", "FPT"}
    assert out["VCB"]["de"] == 0.8
    assert out["FPT"]["roe"] == 25.0


def test_load_vn30_fundamentals_skips_all_null_rows(tmp_path):
    p = _write_fund_parquet(tmp_path, [
        {"ticker": "VCB", "debt_to_equity": None, "roe": None,
         "operating_cf": None, "updated_at": "2026-06-01"},
    ])
    out = _load_vn30_fundamentals(path=p, vn30={"VCB"})
    assert out == {}


def test_load_vn30_fundamentals_missing_file_returns_empty(tmp_path):
    assert _load_vn30_fundamentals(path=tmp_path / "nope.parquet") == {}


def test_vn30_fund_block_renders_medians_and_flags():
    funds = {
        "MBB": {"de": 9.0, "roe": 20.0, "ocf": -64000.0, "updated": "2026-06-01"},  # bank
        "HPG": {"de": 1.5, "roe": 12.0, "ocf": -300.0, "updated": "2026-06-01"},    # non-fin
        "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-01"},
    }
    block = _vn30_fund_block(funds)
    assert "Cơ bản nhóm theo dõi" in block
    assert "Trung vị nhóm" in block
    # HPG has the highest D/E among non-financials → must lead the leverage line
    assert "HPG 1.50" in block
    # HPG is the weakest (negative) non-financial CF → flagged + negative count
    assert "HPG" in block and "1 mã âm" in block
    assert "cập nhật 2026-06-01" in block


def test_vn30_fund_block_excludes_financials_from_risk_rankings():
    # Banks/securities dominate D/E and Op.CF purely by scale — they must NOT
    # surface as fundamental risk flags (regression for the "MBB Op.CF -64,972
    # tỷ" mis-flag). ROE is comparable so it still spans all sectors.
    funds = {
        "MBB": {"de": 12.0, "roe": 21.0, "ocf": -64972.0, "updated": "2026-06-01"},
        "VCB": {"de": 9.5,  "roe": 18.0, "ocf": -50000.0, "updated": "2026-06-01"},
        "SSI": {"de": 2.0,  "roe": 14.0, "ocf": -9000.0,  "updated": "2026-06-01"},
        "FPT": {"de": 1.1,  "roe": 25.0, "ocf": 8000.0,   "updated": "2026-06-01"},
        "HPG": {"de": 1.5,  "roe": 12.0, "ocf": -300.0,   "updated": "2026-06-01"},
    }
    block = _vn30_fund_block(funds)
    # No financial ticker, and crucially not the misleading bank mega-cash-flow
    assert "-64,972" not in block
    assert "MBB" not in block and "VCB" not in block and "SSI" not in block
    # Only non-financials rank → HPG weakest Op.CF, exactly 1 negative
    assert "HPG" in block and "1 mã âm" in block
    # ROE median spans all sectors (comparable across financials/non-financials)
    assert "ROE=" in block


def test_vn30_fund_block_tags_realestate_ocf_with_context():
    # A real-estate developer's huge negative Op.CF (e.g. KBC -17,344 tỷ) is
    # land-bank / project-inventory build, not distress. It stays in the ranking
    # but is tagged "(BĐS)" and gets a context line so the brief never calls it
    # "kiệt quệ tiền mặt".
    funds = {
        "KBC": {"de": 1.1, "roe": 6.3, "ocf": -17343.9, "updated": "2026-06-01"},
        "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-01"},
        "HPG": {"de": 1.5, "roe": 12.0, "ocf": -300.0, "updated": "2026-06-01"},
    }
    block = _vn30_fund_block(funds, realestate={"KBC"})
    assert "KBC -17,344 tỷ (BĐS)" in block
    assert "tích lũy quỹ đất" in block and "kiệt quệ" in block
    # a non-RE name in the same ranking is NOT tagged
    assert "HPG -300 tỷ (BĐS)" not in block


def test_vn30_fund_block_empty_when_no_data():
    assert _vn30_fund_block({}) == ""


def test_enforce_realestate_ocf_context_appends_when_missing():
    # 14:48 brief cited "KBC và NVL có lưu chuyển tiền HĐKD thấp nhất" with no
    # land-bank context → the guard must append it after that line.
    from vnstock_brief import enforce_realestate_ocf_context
    ctx = {"realestate_tickers": {"KBC", "NVL"}}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "HNG có D/E cao nhất với 8.83, KBC và NVL có lưu chuyển tiền HĐKD thấp nhất.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_realestate_ocf_context(text, ctx)
    assert "quỹ đất" in fixed and "không phải lỗ HĐKD" in fixed
    assert "KBC, NVL" in fixed
    # the note lands right after the citing line, before the next section
    lines = fixed.splitlines()
    assert lines[2].startswith("(Lưu ý: Op.CF âm của KBC, NVL")
    assert lines[3] == "📅 Sự kiện sắp tới"


def test_enforce_realestate_ocf_context_noop_cases():
    from vnstock_brief import enforce_realestate_ocf_context
    ctx = {"realestate_tickers": {"KBC"}}
    # context already written by the model → untouched
    t1 = "KBC có Op.CF=-17,344 tỷ, chủ yếu do tích lũy quỹ đất và hàng tồn kho."
    assert enforce_realestate_ocf_context(t1, ctx) == t1
    # RE ticker absent from the OCF line → untouched
    t2 = "HPG có lưu chuyển tiền HĐKD thấp nhất -300 tỷ."
    assert enforce_realestate_ocf_context(t2, ctx) == t2
    # no realestate set in ctx → untouched
    t3 = "KBC có Op.CF thấp nhất."
    assert enforce_realestate_ocf_context(t3, {}) == t3


def test_enforce_watchlist_hygiene_strips_meta_and_filler():
    # 15:11 brief: setup line carried "(đây là ví dụ, không dùng thực tế vì
    # không có đủ thông tin về setup)" + a padded "Cần thêm dữ liệu giá…" line
    # below a real priced setup. Both must be stripped.
    from vnstock_brief import enforce_watchlist_hygiene
    text = ("📋 Watchlist sáng mai\n"
            "1. **STB** (Giá 70,700) — MUA vùng 69,000 · chốt lời 73,000 · cắt lỗ 67,000"
            " (đây là ví dụ, không dùng thực tế vì không có đủ thông tin về setup)\n"
            "2. Cần thêm dữ liệu giá cổ phiếu cụ thể\n"
            "⚠️ Rủi ro cần lưu ý\n"
            "HNG có D/E cao nhất với 8.83.")
    fixed = enforce_watchlist_hygiene(text, {})
    assert "đây là ví dụ" not in fixed and "không dùng thực tế" not in fixed
    assert "Cần thêm dữ liệu giá" not in fixed
    assert "MUA vùng 69,000 · chốt lời 73,000 · cắt lỗ 67,000" in fixed
    assert "⚠️ Rủi ro cần lưu ý" in fixed and "HNG có D/E cao nhất" in fixed


def test_enforce_watchlist_hygiene_drops_index_level_setups():
    # 13:25 brief: "CII (Giá 17,300) — canh mua nếu vượt R1=1,800.80 → mục tiêu
    # R2=1,801.66; hủy nếu thủng S1=1,789.31" — VNINDEX points on a stock setup.
    # Eligible stocks trade ≥ 5,000 VND, so pivot values inside the 800-2500
    # index band are never valid stock levels → the setup is dropped (bail line
    # appended when nothing valid remains). Stock-scale labels are kept.
    from vnstock_brief import enforce_watchlist_hygiene
    t1 = ("📋 Watchlist sáng mai\n"
          "1. **CII** (Giá 17,300) — canh mua nếu vượt R1=1,800.80 → mục tiêu "
          "R2=1,801.66; hủy nếu thủng S1=1,789.31.\n"
          "⚠️ Rủi ro cần lưu ý")
    f1 = enforce_watchlist_hygiene(t1, {})
    assert "CII" not in f1
    assert "Cần thêm dữ liệu giá cổ phiếu cụ thể" in f1
    # per-stock scale levels survive (STB R1=71,500 is outside the index band)
    t2 = ("📋 Watchlist sáng mai\n"
          "1. **STB** (Giá 70,600) — canh mua nếu vượt R1=71,500 → mục tiêu "
          "74,000; hủy nếu thủng S1=69,000\n"
          "⚠️ Rủi ro cần lưu ý")
    assert enforce_watchlist_hygiene(t2, {}) == t2


def test_wallclock_intraday_detection():
    # A mid-session updater run leaves a partial TODAY bar with no live file;
    # wall-clock must classify the session as in-progress before 15:05 so the
    # morning-share signal and the full-day GTGD pin stay suppressed.
    from datetime import datetime
    from vnstock_brief import _wallclock_intraday
    assert _wallclock_intraday("2026-06-11", now=datetime(2026, 6, 11, 13, 25))
    assert not _wallclock_intraday("2026-06-11", now=datetime(2026, 6, 11, 15, 10))
    assert not _wallclock_intraday("2026-06-10", now=datetime(2026, 6, 11, 13, 25))


def test_money_flow_guard_prefers_dedicated_anchor():
    # 13:25 close: generic keyword match hit "dòng tiền" inside "Tổng kết phiên"
    # prose and spliced the NN lines there, while the real "💰 Dòng tiền đáng
    # chú ý" section already carried both sides → must be a no-op now.
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "CNTT", "NN 1T (tỷ)": 87.0},
                       {"Ngành": "Bất động sản", "NN 1T (tỷ)": -5222.0}]}
    t = ("📊 Tổng kết phiên\n"
         "Kết quả phiên cho thấy dòng tiền không mạnh mẽ.\n"
         "💰 Dòng tiền đáng chú ý\n"
         "NN mua ròng CNTT (+87 tỷ), trong khi Bất động sản bị bán ròng (-5,222 tỷ).\n"
         "📋 Watchlist sáng mai")
    assert enforce_money_flow_two_sides(t, ctx) == t
    # morning: insert after the dedicated "Dòng tiền ngành" line, not after the
    # earlier prose that merely mentions "dòng tiền"
    t2 = ("🎯 Trọng tâm theo dõi\n"
          "**Tích luỹ/Mua:** Bất động sản — tích cực về dòng tiền.\n"
          "**Dòng tiền ngành:** NN mua ròng CNTT +87 tỷ\n"
          "⚡ Biến động bất thường")
    f2 = enforce_money_flow_two_sides(t2, ctx)
    lines = f2.splitlines()
    i = next(k for k, l in enumerate(lines) if "Dòng tiền ngành" in l)
    assert lines[i + 1].startswith("NN bán ròng mạnh nhất (1 tuần): Bất động sản -5,222 tỷ")
    assert "bán ròng" not in lines[2]      # nothing spliced after the prose line


def test_enforce_watchlist_hygiene_keeps_legit_bail_and_noop():
    from vnstock_brief import enforce_watchlist_hygiene
    # no priced setup at all → the bail line is legitimate and stays
    t1 = ("📋 Watchlist sáng mai\n"
          "Cần thêm dữ liệu giá cổ phiếu cụ thể\n"
          "⚠️ Rủi ro cần lưu ý")
    assert enforce_watchlist_hygiene(t1, {}) == t1
    # clean watchlist → untouched; no watchlist section → untouched
    t2 = ("📋 Watchlist sáng mai\n"
          "1. **STB** (Giá 70,700) — MUA vùng 69,000 · chốt lời 73,000 · cắt lỗ 67,000\n"
          "⚠️ Rủi ro cần lưu ý")
    assert enforce_watchlist_hygiene(t2, {}) == t2
    t3 = "🎯 TLDR\nKhông có watchlist."
    assert enforce_watchlist_hygiene(t3, {}) == t3


def test_enforce_money_flow_two_sides_appends_missing_sell_side():
    # 15:20 brief: "NN mua ròng: CNTT +708 tỷ, Dầu khí +40 tỷ" — dropped the
    # dominant BĐS -5,431 tỷ sell side → guard appends it from ctx["sectors"].
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [
        {"Ngành": "Công nghệ thông tin & Phần mềm", "NN 1T (tỷ)": 708.0},
        {"Ngành": "Bất động sản", "NN 1T (tỷ)": -5431.0},
    ]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "NN mua ròng: Công nghệ thông tin & Phần mềm (+708 tỷ), Dầu khí (+40 tỷ)\n"
            "📋 Watchlist sáng mai")
    fixed = enforce_money_flow_two_sides(text, ctx)
    assert "NN bán ròng mạnh nhất (1 tuần): Bất động sản -5,431 tỷ." in fixed
    # inserted inside the section (right after the dedicated header), and the
    # following section is untouched
    assert fixed.splitlines()[1].startswith("NN bán ròng mạnh nhất")
    assert fixed.splitlines()[-1] == "📋 Watchlist sáng mai"


def test_enforce_watchlist_hygiene_bumps_subprice_buy_trigger():
    # 22:22: "CII (Giá 17,200) — canh MUA NẾU vượt 16,684 …" — the breakout
    # trigger is BELOW price (already true → meaningless). Bump it above Giá
    # (~+2% → 17,550). Defensive "thủng/vượt lại" lines stay untouched.
    from vnstock_brief import enforce_watchlist_hygiene
    text = ("📋 Watchlist sáng mai\n"
            "1. **CII** (Giá 17,200) — canh MUA NẾU vượt 16,684 · mục tiêu 17,716 · cắt lỗ 16,400\n"
            "2. **GEE** (Giá 95,500) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 92,635 · mục tiêu về 89,000 · hủy nếu vượt lại 98,365\n"
            "⚠️ Rủi ro")
    fixed = enforce_watchlist_hygiene(text, {"bias_floor": {"dir": "GIẢM"}})
    assert "canh MUA NẾU vượt 17,550" in fixed
    assert "vượt 16,684" not in fixed
    # the target is bumped along with the trigger so the reward isn't squeezed
    # to <1% (observed 23:56: vượt 17,550 → mục tiêu 17,716 = +0.95%)
    assert "mục tiêu 18,100" in fixed and "17,716" not in fixed
    assert "hủy nếu vượt lại 98,400" in fixed      # defensive line (rounded to tick 100)
    # an already-correct trigger (above price) is left as-is
    t2 = ("📋 Watchlist sáng mai\n"
          "1. **CII** (Giá 17,200) — canh MUA NẾU vượt 17,716 · mục tiêu 18,200 · cắt lỗ 16,800\n"
          "⚠️ Rủi ro")
    f2 = enforce_watchlist_hygiene(t2, {"bias_floor": {"dir": "GIẢM"}})
    assert "vượt 17,700" in f2 and "mục tiêu 18,200" in f2   # 17,716 → tick 50


def test_enforce_no_cjk_normalizes_sentiment_typo():
    # Recurring model typo on our own sentiment label: "Sổ hãi" (23:56) and
    # "Sờ hãi" (earlier run) → "Sợ hãi".
    from vnstock_brief import enforce_no_cjk
    assert enforce_no_cjk("Tâm lý: ❄️ Sổ hãi, momentum -61/100") == \
        "Tâm lý: ❄️ Sợ hãi, momentum -61/100"
    assert enforce_no_cjk("Tâm lý ❄️ Sờ hãi hôm nay") == "Tâm lý ❄️ Sợ hãi hôm nay"
    t = "Tâm lý: ❄️ Sợ hãi, momentum -61/100"
    assert enforce_no_cjk(t) == t


def test_enforce_money_flow_two_sides_requires_numbers_not_just_sides():
    # 21:31: "mua ròng đáng kể FnB, CNTT … bán ròng BĐS" — both sides named but
    # zero tỷ numbers. The guard must append the numbered canonical lines.
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "Thực phẩm & Đồ uống", "NN 1T (tỷ)": 98.0},
                       {"Ngành": "Bất động sản", "NN 1T (tỷ)": -5275.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "Khối ngoại mua ròng đáng kể FnB, CNTT, trong khi bán ròng BĐS.\n"
            "📋 Watchlist sáng mai")
    fixed = enforce_money_flow_two_sides(text, ctx)
    assert "Bất động sản -5,275 tỷ" in fixed
    assert "Thực phẩm & Đồ uống +98 tỷ" in fixed


def test_enforce_watchlist_hygiene_converts_dipbuy_under_giam_bias():
    # Bias GIẢM: an unconditional "MUA vùng [giá]" dip-buy must become a
    # confirmation-breakout ("canh MUA NẾU vượt"), numbers/order intact;
    # defensive lines untouched. Without a GIẢM floor it's left alone.
    from vnstock_brief import enforce_watchlist_hygiene
    text = ("📋 Watchlist sáng mai\n"
            "1. **CII** (Giá 17,200) — MUA vùng 17,200 · chốt lời 17,716 · cắt lỗ 16,684\n"
            "2. **GEE** (Giá 95,500) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 92,635 · mục tiêu về 90,000\n"
            "⚠️ Rủi ro")
    fixed = enforce_watchlist_hygiene(text, {"bias_floor": {"dir": "GIẢM"}})
    assert "canh MUA NẾU vượt 17,200 · mục tiêu 17,700 · cắt lỗ 16,700" in fixed
    assert "MUA vùng" not in fixed
    assert "GIẢM TỶ TRỌNG/TRÁNH nếu thủng 92,600" in fixed   # defensive: level rounded to tick
    # no GIẢM floor → dip-buy left as-is
    assert "MUA vùng 17,200" in enforce_watchlist_hygiene(text, {})


def test_enforce_money_flow_two_sides_noop_cases():
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "CNTT", "NN 1T (tỷ)": 708.0},
                       {"Ngành": "BĐS", "NN 1T (tỷ)": -5431.0}]}
    # both sides already present → untouched
    t1 = ("💰 Dòng tiền đáng chú ý\n"
          "NN mua ròng CNTT +708 tỷ; NN bán ròng BĐS -5,431 tỷ.\n"
          "📋 Watchlist")
    assert enforce_money_flow_two_sides(t1, ctx) == t1
    # no money-flow section → untouched; no sector data → untouched
    t2 = "🎯 TLDR\nKhông có gì."
    assert enforce_money_flow_two_sides(t2, ctx) == t2
    assert enforce_money_flow_two_sides(t1, {}) == t1
    # flows below the 50-tỷ floor are noise → not appended
    ctx_small = {"sectors": [{"Ngành": "Dầu khí", "NN 1T (tỷ)": 40.0},
                             {"Ngành": "Thép", "NN 1T (tỷ)": -30.0}]}
    t3 = "💰 Dòng tiền đáng chú ý\nGiao dịch NN cân bằng.\n📋 Watchlist"
    assert enforce_money_flow_two_sides(t3, ctx_small) == t3


def test_bias_floor_giam_adds_watchlist_conditional_buy_rule():
    # Stance GIẢM kept producing unconditional dip-buys ("MUA vùng 69,000" with
    # price at 70,700). The bias-floor block must carry a watchlist-specific
    # directive: MUA only as a conditional breakout, prefer a defensive setup.
    ctx = {"date": "2026-06-10", "time": "15:00",
           "bias_floor": {"dir": "GIẢM", "momentum": -59, "regime_score": -4}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "canh MUA NẾU vượt lại" in prompt
    assert "bắt dao rơi" in prompt
    # 22:59 leaked "bias GIẢM bắt buộc" into the TLDR — the block must tell the
    # model the directive wording is internal-only
    assert "KHÔNG in chữ" in prompt and "'bắt buộc' vào brief" in prompt
    # TĂNG floor → no such restriction
    ctx_up = {"date": "2026-06-10", "time": "15:00",
              "bias_floor": {"dir": "TĂNG", "momentum": 60, "regime_score": 4}}
    assert "bắt dao rơi" not in build_prompt(ctx_up, brief_type="afternoon")


def test_bias_floor_block_is_brief_type_aware():
    # The bias block must name the right section per brief: morning's scenario
    # is "Kịch bản phiên chiều", the close's directional call is "Stance ngày
    # mai" (regression: the block hardcoded "Kịch bản phiên chiều" for both).
    base = {"date": "2026-06-10",
            "bias_floor": {"dir": "GIẢM", "momentum": -59, "regime_score": -4}}
    seg_m = build_prompt({**base, "time": "11:30"}, brief_type="morning").split("RÀNG BUỘC BIAS")[1][:600]
    seg_a = build_prompt({**base, "time": "15:00"}, brief_type="afternoon").split("RÀNG BUỘC BIAS")[1][:600]
    assert "Kịch bản phiên chiều" in seg_m and "Stance ngày mai" not in seg_m
    assert "Stance ngày mai" in seg_a
    # GIẢM dip-buy ban present in both, scoped to the right section
    assert "Trọng tâm theo dõi / Kịch bản" in seg_m
    assert "Watchlist sáng mai" in seg_a


def test_both_templates_have_risk_section_and_money_flow_guard_parity():
    # Feature parity: morning gained a "Rủi ro cần lưu ý" section carrying the
    # same fundamentals/BĐS/numbers rules as close, so those guards apply to it.
    for bt, tm in (("morning", "11:30"), ("afternoon", "15:00")):
        p = build_prompt({"date": "2026-06-10", "time": tm}, brief_type=bt)
        assert "## ⚠️ Rủi ro cần lưu ý" in p
        assert "tích lũy quỹ đất" in p          # BĐS context rule
        assert "PHẢI kèm CON SỐ" in p           # numbers-required rule


def test_enforce_no_cjk_strips_han_characters():
    # Close brief leaked "giá trị giao dịch 达到 5,153 tỷ" — CJK is never valid in
    # the Vietnamese brief; strip it and tidy the spacing.
    from vnstock_brief import enforce_no_cjk
    assert enforce_no_cjk("giá trị giao dịch 达到 5,153 tỷ") == "giá trị giao dịch 5,153 tỷ"
    # full Vietnamese with diacritics is untouched
    t = "VNINDEX đóng cửa 1.803,71 — độ rộng tiêu cực; NN bán ròng BĐS."
    assert enforce_no_cjk(t) == t
    assert enforce_no_cjk("") == ""


def test_morning_brief_never_sees_full_day_gtgd():
    # Morning brief = the 11:30 viewpoint. On an EOD re-run the session stats
    # carry the full day, and 00:36 leaked "Phiên chiều chiếm 56% GTGD" into
    # the MORNING overview. The morning prompt must keep GTGD sáng (+ baselines)
    # but never the full-day figure, afternoon share, or institutional detail.
    ctx = {"date": "2026-06-11", "time": "11:30",
           "vnindex_tech": {"close": 1798.61, "intraday": False},
           "session_timing": {"signal": "🔵 institutional",
                              "detail": "sáng chiếm 44% cả ngày"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 5233.3}},
                             "9h-15h": {"VNINDEX": {"gtgd": 11929.2}}},
           "morning_gtgd": {"today": 5233.3, "prev": 9129.4, "avg5": 7959.6},
           "full_day_gtgd": 11929.2,
           "full_day_gtgd_cmp": {"prev": 11673.4, "avg5": 13000.0}}
    p_morning = build_prompt(ctx, brief_type="morning")
    assert "GTGD sáng (9h-11h30): 5,233.3 tỷ" in p_morning      # morning data kept
    assert "sáng-với-sáng" in p_morning
    assert "GTGD cả ngày: 11,929" not in p_morning              # full-day data line hidden
    assert "11,929.2" not in p_morning                          # the value never injected
    assert "sáng chiếm 44%" not in p_morning                    # share/detail hidden
    assert "KHÔNG bàn về phiên chiều" in p_morning
    # the close brief on the same ctx still gets the full-day figure
    p_close = build_prompt(ctx, brief_type="afternoon")
    assert "GTGD cả ngày: 11,929.2 tỷ" in p_close


def test_morning_gtgd_example_has_no_leakable_literal():
    # The morning GTGD instruction used a concrete example "9.650,4 tỷ" which the
    # model copied verbatim when real morning GTGD was absent. The example must
    # carry no leakable number + a no-invent fallback.
    p = build_prompt({"date": "2026-06-10", "time": "11:30"}, brief_type="morning")
    assert "9.650,4" not in p
    assert "Chưa có GTGD phiên sáng" in p


def test_enforce_gtgd_total_pins_close_summary_to_session_value():
    # Two runs on the same 10/06 data cited 5,153 vs 14,118 for full-day GTGD;
    # pin both the TLDR "Kết quả phiên" line and the "Tổng kết phiên" section to
    # the canonical session_stats full-day value, leaving sector GTGD alone.
    from vnstock_brief import enforce_gtgd_total
    ctx = {"session_stats": {"9h-15h": {"VNINDEX": {"gtgd": 10800.0}},
                             "9h-11h30": {"VNINDEX": {"gtgd": 5153.0}}},
           "vnindex_tech": {"intraday": False}}
    text = ("🎯 TLDR\n"
            "**Kết quả phiên:** VNINDEX +0.59% với GTGD 5,153 tỷ đồng — phiên yếu.\n"
            "## 📊 Tổng kết phiên\n"
            "Thanh khoản giá trị giao dịch 5,153 tỷ, thấp hơn trung bình.\n"
            "## 💰 Dòng tiền đáng chú ý\n"
            "Dầu khí GTGD 1,114 tỷ.")          # sector GTGD must NOT be touched
    fixed = enforce_gtgd_total(text, ctx)
    assert "GTGD 10,800.0 tỷ" in fixed
    assert "giá trị giao dịch 10,800.0 tỷ" in fixed
    assert "5,153" not in fixed
    assert "Dầu khí GTGD 1,114 tỷ" in fixed     # sector line untouched


def test_enforce_gtgd_total_noop_intraday_and_missing():
    from vnstock_brief import enforce_gtgd_total
    t = "**Kết quả phiên:** GTGD 5,153 tỷ"
    # intraday → no full-day pin
    assert enforce_gtgd_total(t, {"session_stats": {"9h-15h": {"VNINDEX": {"gtgd": 10800.0}}},
                                  "vnindex_tech": {"intraday": True}}) == t
    # no session_stats at all → untouched (ambiguous, don't strip)
    assert enforce_gtgd_total(t, {}) == t


def test_build_prompt_emits_eod_full_day_gtgd():
    # When session capture is absent but the EOD-derived total is in ctx, the
    # Session Timing block must surface it (so the close brief can cite a real
    # GTGD on EOD-only days) and label it as an EOD estimate.
    ctx = {"date": "2026-06-10", "time": "15:00", "full_day_gtgd": 10800.0,
           "vnindex_tech": {"close": 1803.71, "intraday": False}}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "GTGD cả ngày: 10,800.0 tỷ" in p
    assert "ước tính từ EOD" in p


def test_build_prompt_flags_partial_eod_gtgd_coverage():
    # 10/06 reality: EOD batch only partly landed (379/1388 mã) → the partial
    # sum must be flagged "chưa đủ dữ liệu", never shown as the market figure.
    ctx = {"date": "2026-06-10", "time": "15:00",
           "vnindex_tech": {"close": 1803.71, "intraday": False},
           "session_timing": {"signal": "trung tính", "detail": "x"},
           "session_stats": {"9h-15h": {"VNINDEX": {"gtgd": 0.0}},
                             "9h-11h30": {"VNINDEX": {"gtgd": 0.0}}},
           "full_day_gtgd_partial": 6157.7,
           "full_day_gtgd_count": 379, "full_day_gtgd_universe": 1388}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "CHƯA ĐỦ DỮ LIỆU" in p and "379 mã" in p
    assert "6,157" not in p          # the partial number is not surfaced as GTGD


def test_pick_gtgd_session_skips_in_progress_day():
    # Real 11/06 case: mid-day updater run gave today 4,508 tỷ/706 mã while
    # yesterday is complete (11,673/808). Count can't tell them apart (~80% of
    # names print a trade by noon) — the picker must use wall-clock (session
    # still open) and total-vs-median (stale mid-session fetch) instead.
    from datetime import datetime
    from vnstock_runner import _pick_gtgd_session
    byd = {"2026-06-11": {"total": 4508.6, "count": 706},
           "2026-06-10": {"total": 11673.4, "count": 808},
           "2026-06-09": {"total": 12097.6, "count": 797},
           "2026-06-08": {"total": 16925.3, "count": 825},
           "2026-06-05": {"total": 13082.8, "count": 869}}
    # (a) run at 12:35 the same day → session open → step back to 10/06
    d, total, count = _pick_gtgd_session(byd, now=datetime(2026, 6, 11, 12, 35))
    assert d == "2026-06-10" and total == 11673.4 and count == 808
    # (b) run at 16:00 NEXT day but the 11/06 bar is still the stale noon fetch
    # → total 4,508 ≪ median of the other days → still stepped back
    assert _pick_gtgd_session(byd, now=datetime(2026, 6, 12, 16, 0))[0] == "2026-06-10"
    # (c) evening re-run refreshed today's bars to the full session → today wins
    byd_evening = dict(byd, **{"2026-06-11": {"total": 11900.0, "count": 810}})
    assert _pick_gtgd_session(
        byd_evening, now=datetime(2026, 6, 11, 18, 0))[0] == "2026-06-11"
    assert _pick_gtgd_session({}) == (None, 0.0, 0)


def test_enforce_gtgd_total_falls_back_to_eod_total():
    # session_stats empty/zero but the EOD-derived full-day GTGD is available
    # (ctx["full_day_gtgd"]) → pin the close figure to it instead of stripping.
    from vnstock_brief import enforce_gtgd_total
    ctx = {"session_stats": {"9h-15h": {"VNINDEX": {"gtgd": 0.0}}},
           "full_day_gtgd": 10800.0,
           "vnindex_tech": {"intraday": False}}
    text = "**Kết quả phiên:** VNINDEX +0.59% với GTGD 5,153 tỷ đồng."
    fixed = enforce_gtgd_total(text, ctx)
    assert "GTGD 10,800.0 tỷ" in fixed and "5,153" not in fixed


def test_enforce_gtgd_total_strips_fabrication_when_session_is_zero():
    # The real 10/06 case: session_stats present but every GTGD window is 0.0
    # (WSS didn't run / EOD-only) → the model fabricated numbers. Strip them.
    from vnstock_brief import enforce_gtgd_total
    ctx = {"session_stats": {"9h-15h": {"VNINDEX": {"gtgd": 0.0}},
                             "9h-11h30": {"VNINDEX": {"gtgd": 0.0}}},
           "vnindex_tech": {"intraday": False}}
    text = ("**Kết quả phiên:** VNINDEX +0.59% với GTGD 5,153 tỷ đồng.\n"
            "## 📊 Tổng quan phiên sáng\n"
            "GTGD sáng đạt 9.650,4 tỷ, cao hơn trung bình.")
    fixed = enforce_gtgd_total(text, ctx)
    assert "5,153" not in fixed and "9.650,4" not in fixed
    assert "GTGD chưa có dữ liệu" in fixed
    assert "GTGD sáng đạt chưa có dữ liệu" in fixed


def test_money_flow_guard_handles_morning_inline_line():
    # The two-sides guard must also fix the morning's inline "Dòng tiền ngành"
    # line (no dedicated section header), not just the close section.
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [
        {"Ngành": "Công nghệ thông tin & Phần mềm", "NN 1T (tỷ)": 708.0},
        {"Ngành": "Bất động sản", "NN 1T (tỷ)": -5111.0},
    ]}
    text = ("## 🎯 Trọng tâm theo dõi\n"
            "**Tích luỹ/Mua:** Ngân hàng\n"
            "**Dòng tiền ngành:** NN mua ròng Công nghệ thông tin & Phần mềm +708 tỷ\n"
            "**Theo dõi:** chưa rõ\n"
            "## ⚡ Biến động bất thường")
    fixed = enforce_money_flow_two_sides(text, ctx)
    lines = fixed.splitlines()
    i = next(k for k, l in enumerate(lines) if "Dòng tiền ngành" in l)
    assert lines[i + 1].startswith("NN bán ròng mạnh nhất (1 tuần): Bất động sản -5,111 tỷ")


def test_enforce_risk_numbers_appends_missing_values():
    # 15:27 brief: "một số mã như HNG, PET, VTZ có D/E cao, cần được quan tâm" —
    # zero numbers despite the template. The guard appends the real values.
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "roe": 2.0, "ocf": 500.0},
        "PET": {"de": 3.10, "roe": 9.0, "ocf": 200.0},
        "VTZ": {"de": 2.95, "roe": 7.0, "ocf": 100.0},
        "KBC": {"de": 1.12, "roe": 6.3, "ocf": -17343.9},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "Một số mã như HNG, PET, VTZ có D/E cao, cần được quan tâm.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HNG D/E=8.83" in fixed and "PET D/E=3.10" in fixed and "VTZ D/E=2.95" in fixed
    assert "KBC" not in fixed.splitlines()[2]          # uncited ticker not added
    assert fixed.splitlines()[3] == "📅 Sự kiện sắp tới"  # appended inside section


def test_enforce_risk_numbers_per_ticker_metric_on_mixed_line():
    # One line flags some tickers for D/E and others for Op.CF (observed 20:59:
    # "HNG, PET, VTZ có D/E cao, và KBC, NVL, VRE có lưu chuyển tiền HĐKD thấp").
    # The appended figures must match each ticker's OWN clause — D/E for the
    # leverage names, Op.CF for the cash-flow names — not Op.CF for all.
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "ocf": 915.0}, "PET": {"de": 2.67, "ocf": -1389.0},
        "VTZ": {"de": 2.63, "ocf": -318.0}, "KBC": {"de": 1.12, "ocf": -17344.0},
        "NVL": {"de": 3.50, "ocf": -6145.0}, "VRE": {"de": 0.40, "ocf": -3262.0},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "Các mã như HNG, PET, VTZ có D/E cao, và các mã như KBC, NVL, VRE "
            "có lưu chuyển tiền HĐKD thấp.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HNG D/E=8.83" in fixed and "PET D/E=2.67" in fixed and "VTZ D/E=2.63" in fixed
    assert "KBC Op.CF=-17,344 tỷ" in fixed and "NVL Op.CF=-6,145 tỷ" in fixed
    assert "VRE Op.CF=-3,262 tỷ" in fixed
    assert "HNG Op.CF" not in fixed        # leverage names → D/E, not Op.CF


def test_enforce_risk_numbers_swaps_low_de_mispick_for_real_top():
    # 09:02: "HPG D/E=0.65 … rủi ro cơ bản" — 0.65 is low (safe), HNG 8.83 is
    # the real top leverage. The guard swaps the low-D/E mis-pick for the top.
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HPG": {"de": 0.65, "ocf": 12000.0},
        "HNG": {"de": 8.83, "ocf": 915.0},
        "KBC": {"de": 1.12, "ocf": -17344.0},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "HPG D/E=0.65 và KBC Op.CF=-17,344 tỷ — lưu ý rủi ro cơ bản.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HNG D/E=8.83" in fixed and "HPG D/E" not in fixed
    assert "KBC Op.CF=-17,344 tỷ" in fixed       # OCF pick untouched
    # if the top is already cited, no swap (avoid duplicate)
    t2 = ("⚠️ Rủi ro cần lưu ý\nHNG D/E=8.83, HPG D/E=0.65.\n📅 Sự kiện")
    f2 = enforce_risk_numbers(t2, ctx)
    assert f2.count("HNG D/E=8.83") == 1


def test_enforce_risk_numbers_corrects_wrong_figures_in_place():
    # 23:08: "HPG D/E=1.55, KBC D/E=8.83" — 1.55 fabricated (real 0.65) and
    # 8.83 is HNG's figure pinned to KBC (real 1.12). The guard must REWRITE
    # the numbers in place (not just append a contradicting data line).
    from vnstock_brief import enforce_risk_numbers
    # no high-D/E alternative here → isolates the in-place CORRECTION (the
    # low-D/E-mispick SWAP is covered by its own test above)
    ctx = {"vn30_fundamentals": {
        "HPG": {"de": 0.65, "ocf": 12000.0},
        "KBC": {"de": 1.12, "ocf": -17344.0},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "KBC Op.CF=-17,344 tỷ (BĐS). HPG D/E=1.55, KBC D/E=8.83 — đòn bẩy cao.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HPG D/E=0.65" in fixed and "KBC D/E=1.12" in fixed
    assert "1.55" not in fixed and "D/E=8.83" not in fixed
    assert "KBC Op.CF=-17,344 tỷ" in fixed          # correct figure untouched
    assert "(Số liệu:" not in fixed                 # no contradicting append
    # wrong Op.CF figure is corrected too
    t2 = ("⚠️ Rủi ro cần lưu ý\nKBC Op.CF=-20,000 tỷ — dòng tiền âm.\n📅 Sự kiện")
    assert "KBC Op.CF=-17,344 tỷ" in enforce_risk_numbers(t2, ctx)


def test_enforce_risk_numbers_ocf_and_noop_cases():
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "roe": 2.0, "ocf": 500.0},
        "KBC": {"de": 1.12, "roe": 6.3, "ocf": -17343.9},
    }}
    # numbers already on the line → untouched
    t1 = ("⚠️ Rủi ro cần lưu ý\n"
          "HNG có D/E cao nhất với 8.83, KBC có Op.CF=-17,344 tỷ.\n"
          "📅 Sự kiện sắp tới")
    assert enforce_risk_numbers(t1, ctx) == t1
    # OCF-context line without the figure → Op.CF value appended (not D/E)
    t2 = ("⚠️ Rủi ro cần lưu ý\n"
          "KBC có lưu chuyển tiền HĐKD thấp nhất.\n"
          "📅 Sự kiện sắp tới")
    f2 = enforce_risk_numbers(t2, ctx)
    assert "KBC Op.CF=-17,344 tỷ" in f2
    # no risk section / no fundamentals → untouched
    t3 = "🎯 TLDR\nHNG yếu."
    assert enforce_risk_numbers(t3, ctx) == t3
    assert enforce_risk_numbers(t1, {}) == t1


def test_enforce_watchlist_eligibility_drops_low_liquidity_mover():
    # A sub-threshold mover (not VN30) leaked into a setup despite the ⭐ bar.
    # The guard drops it, keeps STB (VN30), and renumbers. Threshold-relative so
    # the test holds when _WATCHLIST_GTGD_MIN_TY is retuned.
    from vnstock_brief import enforce_watchlist_eligibility, _WATCHLIST_GTGD_MIN_TY
    ctx = {
        "vn30_gainers": [
            {"Mã": "STB", "Giá 1T %": 6.8, "GTGD TB (tỷ)": 800.0},   # VN30 → keep
            {"Mã": "XYZ", "Giá 1T %": 6.3,
             "GTGD TB (tỷ)": _WATCHLIST_GTGD_MIN_TY - 5},            # below bar, not VN30
        ],
        "vn30_losers": [],
    }
    text = ("📋 Watchlist sáng mai\n"
            "1. **STB** (Giá 70,600) — canh giảm nếu thủng 68,000 → mục tiêu 65,000; hủy 73,000\n"
            "2. **XYZ** (Giá 16,900) — canh giảm nếu thủng 16,000 → mục tiêu 15,000; hủy 18,000\n"
            "⚠️ Rủi ro cần lưu ý")
    fixed = enforce_watchlist_eligibility(text, ctx)
    assert "XYZ" not in fixed
    assert "STB" in fixed
    assert "1. **STB**" in fixed          # renumbered to 1
    assert "⚠️ Rủi ro cần lưu ý" in fixed


def test_enforce_watchlist_eligibility_bail_when_none_survive_and_noops():
    from vnstock_brief import enforce_watchlist_eligibility
    ctx = {"vn30_gainers": [{"Mã": "VIW", "Giá 1T %": 9.0, "GTGD TB (tỷ)": 12.0}],
           "vn30_losers": []}
    # the only setup is an ineligible name → replaced by the bail line
    t1 = ("📋 Watchlist sáng mai\n"
          "1. **VIW** (Giá 25,600) — MUA vùng 24,500 · chốt lời 27,000 · cắt lỗ 23,500\n"
          "⚠️ Rủi ro")
    f1 = enforce_watchlist_eligibility(t1, ctx)
    assert "VIW" not in f1 and "Cần thêm dữ liệu giá cổ phiếu cụ thể" in f1
    # eligible-only watchlist → untouched; no mover data → untouched
    t2 = ("📋 Watchlist sáng mai\n1. **STB** (Giá 70,600) — MUA vùng 69,000\n⚠️ Rủi ro")
    assert enforce_watchlist_eligibility(t2, {"vn30_gainers":
        [{"Mã": "STB", "GTGD TB (tỷ)": 800.0}], "vn30_losers": []}) == t2
    assert enforce_watchlist_eligibility(t2, {}) == t2


def test_select_sr_levels_filters_noise_and_clusters():
    # Real 11/06 data: close 1,798.61 with raw nearest levels S1=1,798.05
    # (0.03% away!) and R1=1,800.80 → R2=1,801.66 (0.05% apart) — useless as
    # triggers. The picker must skip sub-0.5% noise and enforce ≥0.8% gaps.
    from vnstock_brief import _select_sr_levels
    last = 1798.61
    above = [1800.80, 1801.66, 1824.03, 1846.71]          # ascending (nearest first)
    below = [1798.05, 1789.31, 1786.50, 1780.71, 1760.0]  # descending (nearest first)
    res = _select_sr_levels(above, last)
    sup = _select_sr_levels(below, last)
    assert res == [1824.03, 1846.71]      # 1,800.80/1,801.66 = noise → skipped
    # 1,798.05 (0.03%) skipped; 1,789.31 ✓; 1,786.50 too close to S1 (0.16%) →
    # skipped; 1,780.71 only 0.48% from S1 → skipped; 1,760 ✓
    assert sup == [1789.31, 1760.0]
    # min distance from price respected on both sides
    assert all(abs(v / last - 1) >= 0.005 for v in res + sup)
    assert _select_sr_levels([], last) == []


def test_enforce_pivot_labels_pins_index_levels_only():
    # 08:55 brief: TLDR "thủng S1=1,799.18 → mục tiêu về S2=1,799.18" — S1 took
    # S2's value and contradicted the Trigger section (S1=1,802.42). Pin each
    # label to its canonical pivot; leave per-stock reuse (R1=71,500) alone.
    from vnstock_brief import enforce_pivot_labels
    ctx = {"vnindex_tech": {"support_1": 1802.42, "support_2": 1799.18,
                            "resistance_1": 1822.95, "resistance_2": 1824.03}}
    text = ("Stance: canh giảm nếu thủng S1=1,799.18 → mục tiêu về S2=1,799.18;"
            " hủy nếu vượt lại R1=1,822.95.\n"
            "Watchlist: STB canh mua nếu vượt R1=71,500 → mục tiêu 74,000;"
            " hủy nếu thủng S1=69,000.")
    fixed = enforce_pivot_labels(text, ctx)
    assert "S1=1,802.42" in fixed                    # corrected to canonical S1
    assert "S2=1,799.18" in fixed                    # S2 unchanged (already right)
    assert "thủng S1=1,799.18" not in fixed          # the wrong duplicate is gone
    # per-stock labels (out of the 800-2500 band) are left untouched
    assert "R1=71,500" in fixed and "S1=69,000" in fixed


def test_stance_line_pivots_rewritten_to_filtered_levels():
    # The Stance line shares the S1/S2/R1 source with the Trigger line — after
    # the S/R quality filter, the canonical pivots change and the pin guard
    # must rewrite the Stance's glued old values too (user-reported line,
    # verbatim from the 22:29 brief).
    from vnstock_brief import enforce_pivot_labels
    ctx = {"vnindex_tech": {"support_1": 1789.31, "support_2": 1760.0,
                            "resistance_1": 1824.03, "resistance_2": 1846.71}}
    text = ("**Stance ngày mai:** **GIẢM** — canh giảm nếu thủng S1=1,798.05 → "
            "mục tiêu S2=1,789.31; hủy nếu vượt lại R1=1,800.80.")
    fixed = enforce_pivot_labels(text, ctx)
    assert "S1=1,789.31" in fixed and "S2=1,760.00" in fixed and "R1=1,824.03" in fixed
    assert "1,798.05" not in fixed and "1,800.80" not in fixed
    # trigger level (S1) and cancel level (R1) are now genuinely distinct (~2%)


def test_enforce_pivot_labels_noop_without_data():
    from vnstock_brief import enforce_pivot_labels
    t = "thủng S1=1,799.18 → S2=1,795.00"
    assert enforce_pivot_labels(t, {}) == t                       # no tech data
    assert enforce_pivot_labels("no pivots here", {"vnindex_tech": {
        "support_1": 1800.0}}) == "no pivots here"


def test_validate_brief_factuality_exists_and_flags_hallucination():
    # Regression: an edit once swallowed the `def validate_brief_factuality`
    # line, leaving its body as dead code inside the preceding function — the
    # file still parsed, every test passed, and generate_brief crashed at
    # runtime with NameError. Pin the symbol + its behavior directly.
    from vnstock_brief import validate_brief_factuality
    ctx = {"vnindex_tech": {"close": 1793.05}}
    # far-off VNINDEX level (>5% from close) → flagged
    assert validate_brief_factuality("VNINDEX đóng cửa 1.215,4", ctx)
    # consistent level → clean
    assert validate_brief_factuality("VNINDEX đóng cửa 1.793,05", ctx) == []
    # empty text → clean
    assert validate_brief_factuality("", ctx) == []


def test_build_prompt_includes_fundamentals_block():
    ctx = {
        "date": "2026-06-05",
        "time": "15:00",
        "vn30_fundamentals": {
            "VCB": {"de": 0.8, "roe": 18.0, "ocf": 12000.0, "updated": "2026-06-01"},
            "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-01"},
        },
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Cơ bản nhóm theo dõi" in prompt
    assert "D/E" in prompt


def test_build_prompt_movers_carry_absolute_price():
    # Watchlist setups must anchor to a REAL price — the movers block has to
    # surface the absolute price (in VND), not just the % change. "last" is
    # stored in thousand VND, so 124.0 → "124,000".
    ctx = {
        "date": "2026-06-08",
        "time": "15:00",
        "vn30_gainers": [
            {"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "Công nghệ", "last": 124.0},
        ],
        "vn30_losers": [
            {"Mã": "TCB", "Giá 1T %": -2.0, "Ngành": "Ngân hàng", "last": 27.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "FPT" in prompt and "Giá 124,000" in prompt
    assert "TCB" in prompt and "Giá 27,000" in prompt


def test_afternoon_watchlist_splits_direction_and_forbids_short_entry():
    # Watchlist must use two direction-specific templates with ordering
    # invariants, and must not frame a bearish idea as a short entry
    # ("SELL ở [giá]") — VN cash market has no retail short-selling.
    prompt = build_prompt({"date": "2026-06-08", "time": "15:00"},
                          brief_type="afternoon")
    assert "không cho NĐT cá nhân bán khống" in prompt
    assert "SL < entry < TP" in prompt
    assert "mục tiêu < hỗ trợ < mức hủy" in prompt
    assert "GIẢM TỶ TRỌNG/TRÁNH nếu thủng" in prompt
    # per-stock setups must anchor to the stock's own price, never VNINDEX S/R
    # (regression: STB setup used VNINDEX R1=1,801.66 instead of ~70,700)
    assert "KHÔNG dùng mức S1/S2/R1/R2 của VNINDEX" in prompt


def test_afternoon_watchlist_caps_at_real_priced_vn30_tickers():
    # Must not pad to 3 with price-less / non-VN30 placeholders (e.g. "TCX —
    # Giá không có"); fewer setups is fine.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "TỐI ĐA 3 setup" in prompt
    assert "KHÔNG độn cho đủ 3" in prompt
    assert 'KHÔNG thêm dòng kiểu "Giá không có' in prompt


# ─── Market sentiment (tâm lý thị trường) ─────────────────────────────────────

def test_compute_market_sentiment_bullish():
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 65, "ad_ratio": 1.8},
        nn_net=300.0,
        vnindex_tech={"rsi14": 60, "close": 1840, "ma20": 1820,
                      "ma50": 1800, "ma200": 1700, "day_change_pct": 0.6},
        news_sentiment={"total": 100, "pos_pct": 60, "neg_pct": 15, "net_pct": 45},
    )
    assert ms["momentum"] > 40
    assert "Hưng phấn" in ms["mood"] or "Tích cực" in ms["mood"]
    assert ms["n_signals"] == 7


def test_compute_market_sentiment_bearish():
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 25, "ad_ratio": 0.5},
        nn_net=-350.0,
        vnindex_tech={"rsi14": 32, "close": 1700, "ma20": 1750,
                      "ma50": 1780, "ma200": 1820, "day_change_pct": -1.4},
        news_sentiment={"total": 80, "pos_pct": 10, "neg_pct": 55, "net_pct": -45},
    )
    assert ms["momentum"] < -40
    assert "Sợ hãi" in ms["mood"] or "Tiêu cực" in ms["mood"]


def test_compute_market_sentiment_partial_inputs_renormalise():
    """Only breadth available → still returns a reading weighted over it."""
    from vnstock_market_sentiment import compute_market_sentiment
    ms = compute_market_sentiment(breadth={"above_ma200_pct": 60})
    assert ms["n_signals"] == 1
    assert ms["momentum"] > 0


def test_compute_market_sentiment_empty_when_no_signal():
    from vnstock_market_sentiment import compute_market_sentiment
    assert compute_market_sentiment() == {}


def test_market_sentiment_block_renders():
    from vnstock_market_sentiment import compute_market_sentiment
    from vnstock_brief import _market_sentiment_block
    ms = compute_market_sentiment(
        breadth={"above_ma200_pct": 60, "ad_ratio": 1.5}, nn_net=120.0,
        vnindex_tech={"rsi14": 55, "close": 1840, "ma20": 1820,
                      "ma50": 1800, "ma200": 1700, "day_change_pct": 0.3},
        news_sentiment={"total": 50, "pos_pct": 55, "neg_pct": 20, "net_pct": 35},
    )
    block = _market_sentiment_block(ms)
    assert "Tâm lý thị trường" in block
    assert "momentum" in block
    assert "Tin tức 7N" in block


def test_sector_flow_block_ranks_inflow_outflow():
    from vnstock_brief import _sector_flow_block
    sectors = [
        {"Ngành": "Ngân hàng",    "NN 1T (tỷ)": 1200.0, "GTGD TB (tỷ)": 5400.0},
        {"Ngành": "Bất động sản", "NN 1T (tỷ)": -800.0, "GTGD TB (tỷ)": 3200.0},
        {"Ngành": "Thép",         "NN 1T (tỷ)": 300.0,  "GTGD TB (tỷ)": 1800.0},
        {"Ngành": "Bảo hiểm",     "NN 1T (tỷ)": None,   "GTGD TB (tỷ)": 200.0},
    ]
    block = _sector_flow_block(sectors)
    assert "Dòng tiền ngành" in block
    assert "NN mua ròng" in block and "Ngân hàng" in block
    assert "NN bán ròng" in block and "Bất động sản" in block
    assert "Thanh khoản cao nhất" in block


def test_sector_flow_block_flags_stale_foreign_data():
    # Foreign feed lags the session (observed: BĐS NN ~-5,277 on 09/06 still
    # showing -5,275 two sessions later because the window was wall-clock
    # anchored). When nn_data_date < session_date the block labels the real
    # window end and warns, not presenting stale NN as current.
    from vnstock_brief import _sector_flow_block
    sectors = [{"Ngành": "Bất động sản", "NN 1T (tỷ)": -5275.0, "GTGD TB (tỷ)": 3004.0}]
    stale = _sector_flow_block(sectors, nn_data_date="2026-06-09",
                               session_date="2026-06-11")
    assert "NN ròng 5 phiên đến 2026-06-09" in stale
    assert "MỚI ĐẾN 2026-06-09" in stale and "chưa có phiên 2026-06-11" in stale
    fresh = _sector_flow_block(sectors, nn_data_date="2026-06-11",
                               session_date="2026-06-11")
    assert "NN ròng 1 tuần" in fresh and "MỚI ĐẾN" not in fresh


def test_sector_flow_block_empty():
    from vnstock_brief import _sector_flow_block
    assert _sector_flow_block([]) == ""
    # All-zero NN + no GTGD → nothing to show
    assert _sector_flow_block([{"Ngành": "X", "NN 1T (tỷ)": None, "GTGD TB (tỷ)": 0}]) == ""


def test_build_prompt_includes_sector_flow():
    ctx = {
        "date": "2026-06-08", "time": "15:00",
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": 500.0, "GTGD TB (tỷ)": 4000.0},
            {"Ngành": "BĐS", "NN 1T (tỷ)": -300.0, "GTGD TB (tỷ)": 2000.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Dòng tiền ngành" in prompt


def test_build_prompt_includes_market_sentiment():
    ctx = {
        "date": "2026-06-08", "time": "15:00",
        "market_sentiment": {
            "mood": "📈 Tích cực", "momentum": 35, "n_signals": 2,
            "signals": [
                {"name": "Breadth (% trên MA200)", "value": "60%", "dir": 1},
                {"name": "NN ròng 1D", "value": "+120 tỷ", "dir": 1},
            ],
            "news": {},
        },
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Tâm lý thị trường" in prompt
    assert "momentum" in prompt


# ─── Recommendation block: overdue filtering + price precision ─────────────────

def test_fmt_rec_price_adaptive_precision():
    assert _fmt_rec_price(113.0) == "113"
    assert _fmt_rec_price(13.0) == "13"
    assert _fmt_rec_price(1.23) == "1.23"
    assert _fmt_rec_price(0.39) == "0.390"
    assert _fmt_rec_price(0) == "0"


def test_recommendation_block_excludes_overdue_and_keeps_precision(monkeypatch):
    now = _datetime.now()
    fresh   = (now - _timedelta(days=2)).isoformat()
    overdue = (now - _timedelta(days=34)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "FPT", "action": "buy", "entry_price": 124.0,
         "take_profit": 130.0, "cut_loss": 120.0, "horizon_days": 5,
         "created_at": fresh},
        {"ticker": "CWX", "action": "buy", "entry_price": 0.78,
         "take_profit": 0.94, "cut_loss": 0.69, "horizon_days": 5,
         "created_at": fresh},
        {"ticker": "CFPT2528", "action": "buy", "entry_price": 0.78,
         "take_profit": 0.94, "cut_loss": 0.69, "horizon_days": 5,
         "created_at": overdue},
    ])
    block = _recommendation_block()
    assert "FPT" in block and "entry=124" in block
    # Low-priced instrument keeps decimals instead of collapsing to entry=1
    assert "CWX" in block and "entry=0.780" in block
    # Overdue rec is NOT re-surfaced as a fresh actionable buy
    assert "CFPT2528" not in block


def test_recommendation_block_empty_when_all_overdue(monkeypatch):
    overdue = (_datetime.now() - _timedelta(days=40)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "KSF", "action": "buy", "entry_price": 113.0,
         "take_profit": 129.0, "cut_loss": 105.0, "horizon_days": 5,
         "created_at": overdue},
    ])
    assert _recommendation_block() == ""


# ─── Live intraday VNINDEX augmentation (morning brief uses today's session) ──

def test_augment_with_live_vnindex_folds_today_bar(tmp_path):
    today = _date.today()
    hist = pd.DataFrame({
        "time":  pd.to_datetime([today - _timedelta(days=2), today - _timedelta(days=1)]),
        "open":  [1800.0, 1795.0], "high": [1810.0, 1800.0],
        "low":   [1790.0, 1788.0], "close": [1795.0, 1790.5], "volume": [1, 1],
    })
    live = pd.DataFrame({
        "ticker": ["VNINDEX", "VNINDEX", "FPT"],
        "time":   pd.to_datetime([f"{today} 09:15", f"{today} 11:25", f"{today} 10:00"]),
        "open":   [1790.0, 1788.0, 100.0], "high": [1792.0, 1789.0, 101.0],
        "low":    [1785.0, 1782.0, 99.0],  "close": [1788.0, 1783.4, 100.5],
        "volume": [1000, 2000, 50],
    })
    live.to_parquet(tmp_path / f"bars_{today.isoformat()}.parquet")
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday") is True
    assert pd.to_datetime(out["time"]).dt.date.max() == today
    # Provisional bar: close = last live VNINDEX close (FPT ignored)
    assert float(out["close"].iloc[-1]) == pytest.approx(1783.4)
    assert float(out["high"].iloc[-1]) == pytest.approx(1792.0)


def test_augment_with_live_vnindex_noop_without_file(tmp_path):
    today = _date.today()
    hist = pd.DataFrame({"time": pd.to_datetime([today - _timedelta(days=1)]),
                         "close": [1790.5]})
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday", False) is False
    assert len(out) == 1


def test_augment_with_live_vnindex_skips_when_today_already_present(tmp_path):
    today = _date.today()
    live = pd.DataFrame({
        "ticker": ["VNINDEX"], "time": pd.to_datetime([f"{today} 09:15"]),
        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1788.0], "volume": [1],
    })
    live.to_parquet(tmp_path / f"bars_{today.isoformat()}.parquet")
    hist = pd.DataFrame({"time": pd.to_datetime([today]), "close": [1790.5]})
    out = _augment_with_live_vnindex(hist, live_dir=tmp_path, today=today)
    assert out.attrs.get("intraday", False) is False
    assert len(out) == 1


def test_build_prompt_marks_intraday_vnindex():
    ctx = {"date": str(_date.today()), "time": "11:30",
           "vnindex_tech": {"close": 1788.0, "prev_close": 1790.5,
                            "day_change_pct": -0.14, "intraday": True}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "PHIÊN ĐANG DIỄN RA" in prompt
    assert "Giá hiện tại" in prompt


# ─── Data freshness: breadth/movers/regime lag vs intraday VNINDEX ────────────

def test_market_data_freshness_flags_stale_overview(tmp_path):
    import json as _json
    p = tmp_path / "market_overview.json"
    p.write_text(_json.dumps({"generated_at": "2026-06-08 09:00:00"}))
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is True
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale_blocks"]


def test_market_data_freshness_fresh_when_same_day(tmp_path):
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 11:00:00"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is False
    assert fr["stale_blocks"] == []


def test_market_data_freshness_prefers_data_date_over_generated_at(tmp_path):
    # generated_at is "today" but the DATA inside is from the prior session →
    # must be flagged stale (the regression: a fresh write time hid old data).
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 12:36:00", "data_date": "2026-06-08"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale"] is True


def test_market_data_freshness_old_file_falls_back_to_warehouse_eod(monkeypatch, tmp_path):
    # File written today but WITHOUT a data_date field: must not look fresh just
    # because generated_at is today — fall back to the warehouse EOD date.
    import vnstock_brief as vb
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 12:58:00"}')
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    fr = vb.market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale"] is True


def test_build_prompt_leader_block_weak_forces_no_leader():
    # Strongest +contrib is only +0.02pp → must NOT be named as accumulation.
    ctx = {"date": "2026-06-09", "time": "11:30",
           "lead_sector": {"name": "CNTT & Phần mềm", "contrib": 0.02},
           "lag_sector": {"name": "Hoá chất", "contrib": -0.40}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Chưa có nhóm dẫn dắt rõ ràng" in prompt
    assert "CHỈ CNTT & Phần mềm" not in prompt   # weak leader not endorsed
    assert "Hoá chất" in prompt                  # strong laggard is named


def test_build_prompt_leader_block_strong_names_only_top():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "lead_sector": {"name": "Ngân hàng", "contrib": 0.30},
           "lag_sector": {"name": "Bất động sản", "contrib": -0.40}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "CHỈ Ngân hàng" in prompt
    assert "Bất động sản" in prompt
    assert "KHÔNG CHỌN NGÀNH KHÁC" in prompt


def test_build_prompt_morning_gtgd_like_for_like_and_hides_incomplete_full_day():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "session_timing": {"signal": "sig", "detail": "det"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7165.4}},
                             "9h-15h": {"VNINDEX": {"gtgd": 7165.4}}},  # full==morning
           "morning_gtgd": {"today": 7165.4, "prev": 9650.4,
                            "avg5": 8000.0, "avg20": 8500.0}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "sáng phiên trước" in prompt and "TB sáng 5 phiên" in prompt
    # full==morning (incomplete) → full-day value line hidden, baselines shown
    assert "GTGD cả ngày:" not in prompt


def test_build_prompt_shows_full_day_gtgd_when_session_closed():
    ctx = {"date": "2026-06-09", "time": "15:30",
           "session_timing": {"signal": "sig", "detail": "det"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7000.0}},
                             "9h-15h": {"VNINDEX": {"gtgd": 15000.0}}},  # afternoon added
           "morning_gtgd": {"today": 7000.0, "prev": 6000.0,
                            "avg5": 6500.0, "avg20": 6800.0}}
    # full-day GTGD belongs to the CLOSE brief (the morning view is gated)
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "GTGD cả ngày: 15,000.0 tỷ" in prompt


def test_build_prompt_renders_freshness_warning():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "freshness": {"data_date": "2026-06-09", "overview_date": "2026-06-08",
                      "stale": True, "stale_blocks": ["độ rộng", "regime"]},
    }
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Độ tươi dữ liệu" in prompt
    assert "2026-06-08" in prompt


def test_build_prompt_no_freshness_warning_when_fresh():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "freshness": {"data_date": "2026-06-09", "overview_date": "2026-06-09",
                      "stale": False, "stale_blocks": []},
    }
    prompt = build_prompt(ctx, brief_type="morning")
    assert "Độ tươi dữ liệu" not in prompt


def test_auto_refresh_noop_when_overview_matches_warehouse(monkeypatch):
    import vnstock_brief as vb
    # Overview already at the latest available (EOD) data → don't churn.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-08")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    assert vb._auto_refresh_market_overview() is False


def test_auto_refresh_runs_when_overview_trails_warehouse(monkeypatch):
    import sys
    import types
    import vnstock_brief as vb

    # Overview is genuinely behind the warehouse EOD data → refresh helps.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-05")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    called = {}
    fake = types.ModuleType("vnstock_runner")
    fake.compute_market_overview = lambda *a, **k: (
        called.update(computed=True) or {"tickers": [{"Mã": "FPT"}],
                                         "sectors": [], "breadth": {}})
    fake.save_market_overview = lambda data, *a, **k: called.update(saved=True)
    monkeypatch.setitem(sys.modules, "vnstock_runner", fake)

    assert vb._auto_refresh_market_overview() is True
    assert called.get("computed") and called.get("saved")


def test_auto_refresh_disabled_by_env(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_REFRESH", "0")
    # Even when behind, the env opt-out short-circuits before any work.
    monkeypatch.setattr(vb, "_market_overview_data_date", lambda path=None: "2026-06-05")
    monkeypatch.setattr(vb, "_warehouse_eod_date", lambda: "2026-06-08")
    assert vb._auto_refresh_market_overview() is False


# ─── Movers timeframe label (Giá 1T % is a 1-week change, not 1 session) ──────

def test_build_prompt_movers_labelled_weekly_not_session():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "vn30_gainers": [{"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "Công nghệ",
                          "last": 124.0}],
        "vn30_losers": [{"Mã": "VIC", "Giá 1T %": -4.8, "Ngành": "Bất động sản",
                         "last": 40.0}],
    }
    prompt = build_prompt(ctx, brief_type="morning")
    # The mislabel that caused "VIC -4.8% phiên sáng" must be gone…
    assert "Top Gainers (1 phiên" not in prompt
    assert "Top Losers (1 phiên" not in prompt
    # …and the real (weekly) timeframe is shown on the lines.
    assert "(1 tuần/5 phiên)" in prompt


def test_morning_template_anomaly_section_forbids_session_label():
    prompt = build_prompt({"date": "2026-06-09", "time": "11:30"},
                          brief_type="morning")
    # The leaking example that taught the model to write "phiên sáng" is gone…
    assert "VIC -3.2% phiên sáng" not in prompt
    # …replaced by the honest weekly framing + explicit prohibition.
    section = prompt.split("Biến động bất thường")[1].split("##")[0]
    assert "1 tuần" in section and "KHÔNG ghi" in section


# ─── Bias floor (TLDR must follow strongly one-sided signals) ─────────────────

def test_bias_floor_dir_logic():
    assert _bias_floor_dir(-67, -5) == "GIẢM"
    assert _bias_floor_dir(-67, None) == "GIẢM"   # momentum alone
    assert _bias_floor_dir(None, -3) == "GIẢM"    # regime alone
    assert _bias_floor_dir(60, 4) == "TĂNG"
    assert _bias_floor_dir(-30, -2) is None       # neither strong → free
    assert _bias_floor_dir(-60, 4) is None        # conflict → don't force


def test_build_prompt_renders_bias_floor():
    ctx = {"date": "2026-06-09", "time": "11:30",
           "bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -5}}
    prompt = build_prompt(ctx, brief_type="morning")
    assert "RÀNG BUỘC BIAS" in prompt
    assert "Bias BẮT BUỘC = GIẢM" in prompt
    # The main scenario must also be forced to the bias direction.
    assert "kịch bản CHÍNH" in prompt and "thủng hỗ trợ/đi xuống" in prompt


def test_build_prompt_hides_full_day_and_morning_share_when_intraday():
    # 14:03: partial afternoon makes full > morning AND session_timing.detail
    # leaks "Sáng chiếm 78% cả ngày". Intraday → both must be suppressed.
    ctx = {"date": "2026-06-09", "time": "14:03",
           "vnindex_tech": {"close": 1792.6, "intraday": True},
           "session_timing": {"signal": "🌅 Institutional morning",
                              "detail": "Sáng chiếm `78%` GTGD cả ngày → tổ chức"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 7165.4}},
                             "9h-15h": {"VNINDEX": {"gtgd": 9186.0}}},
           "morning_gtgd": {"today": 7165.4, "prev": 9650.4, "avg5": 7600.0}}
    # afternoon: the intraday rule does the suppression (morning has its own gate)
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "GTGD cả ngày:" not in prompt
    assert "78%" not in prompt                       # morning-share leak gone
    assert "Institutional morning" not in prompt     # bogus intraday classification gone
    assert "CHƯA đánh giá được" in prompt
    assert "sáng phiên trước" in prompt              # baselines still shown


def test_build_prompt_shows_session_timing_when_closed():
    # Not intraday (session closed) → the real morning-share signal IS shown.
    ctx = {"date": "2026-06-09", "time": "15:30",
           "session_timing": {"signal": "🌅 Institutional morning",
                              "detail": "Sáng chiếm `60%` GTGD cả ngày"},
           "session_stats": {"9h-11h30": {"VNINDEX": {"gtgd": 9000.0}},
                             "9h-15h": {"VNINDEX": {"gtgd": 15000.0}}},
           "morning_gtgd": {"today": 9000.0, "prev": 8000.0, "avg5": 8500.0}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Institutional morning" in prompt
    assert "GTGD cả ngày: 15,000.0 tỷ" in prompt


def test_build_prompt_no_bias_floor_when_absent():
    prompt = build_prompt({"date": "2026-06-09", "time": "11:30"},
                          brief_type="morning")
    assert "RÀNG BUỘC BIAS" not in prompt


# ─── Auto-reconcile overdue/zombie recs before a brief ────────────────────────

def test_maybe_reconcile_noop_when_no_overdue(monkeypatch):
    import vnstock_brief as vb
    fresh = (_datetime.now() - _timedelta(days=1)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "FPT", "horizon_days": 5, "created_at": fresh}])
    assert vb._maybe_reconcile_overdue() == 0


def test_maybe_reconcile_runs_when_overdue(monkeypatch):
    import sys
    import types
    import vnstock_brief as vb
    overdue = (_datetime.now() - _timedelta(days=40)).isoformat()
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "CFPT2528", "horizon_days": 5, "created_at": overdue}])
    fake = types.ModuleType("vnstock_train")
    fake.reconcile_recommendations = lambda verbose=True: {
        "closed": 2, "stale": 1, "still_open": 0}
    monkeypatch.setitem(sys.modules, "vnstock_train", fake)
    assert vb._maybe_reconcile_overdue() == 3   # closed + stale


def test_maybe_reconcile_disabled_by_env(monkeypatch):
    import vnstock_brief as vb
    monkeypatch.setenv("VNSTOCK_BRIEF_AUTO_RECONCILE", "0")
    assert vb._maybe_reconcile_overdue() == 0


def test_both_templates_require_all_three_mas():
    morning = build_prompt({"date": "2026-06-09", "time": "11:30"}, brief_type="morning")
    afternoon = build_prompt({"date": "2026-06-09", "time": "15:00"}, brief_type="afternoon")
    for p in (morning, afternoon):
        assert "ĐỦ CẢ BA" in p
        assert "MA20" in p and "MA50" in p and "MA200" in p


def test_morning_brief_uses_sector_flow_and_guards_data_gap():
    ctx = {
        "date": "2026-06-09", "time": "11:30",
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1465.0, "GTGD TB (tỷ)": 5000.0},
            {"Ngành": "Công nghệ", "NN 1T (tỷ)": 1307.0, "GTGD TB (tỷ)": 800.0},
        ],
    }
    prompt = build_prompt(ctx, brief_type="morning")
    # The money-flow DATA block is injected …
    assert "Dòng tiền ngành (NN ròng" in prompt
    # … the morning template now tells the agent to USE it …
    assert "**Dòng tiền ngành:**" in prompt
    # … and "Đề xuất bổ sung" must not request data already provided.
    assert "TUYỆT ĐỐI KHÔNG xin lại" in prompt


def test_afternoon_stance_setup_requires_distinct_trigger_and_invalidation():
    # #1: Stance setup must not collapse trigger and invalidation to one level
    # (e.g. entry R1 == hủy R1).
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "2 MỨC KHÁC NHAU" in prompt
    assert "KHÔNG để mức trigger trùng mức hủy" in prompt


def test_afternoon_dan_dat_defers_to_deterministic_gate():
    # #3: close "Dẫn dắt" must honour the ±0.05pp gate, not name a weak sector.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "DÙNG ĐÚNG block" in prompt
    assert "KHÔNG nêu ngành đóng góp <0.05pp làm dẫn dắt" in prompt


def test_data_gap_guard_forbids_already_present_data_both_templates():
    # #2: don't re-request sentiment / foreign-flow that's already in the prompt.
    for bt in ("morning", "afternoon"):
        p = build_prompt({"date": "2026-06-09", "time": "15:00"}, brief_type=bt)
        assert "TÂM LÝ/momentum" in p
        assert "dòng tiền khối ngoại/NN ròng" in p


def test_afternoon_risk_only_uses_block_tickers_with_numbers():
    # #1: risk section must use only VN30-fundamentals tickers (never a ticker
    # outside the data like VCK), cite the real number, and not hand-wave
    # "cần thêm dữ liệu" or mislabel a positive Op.CF as negative.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "dẫn mã KHÔNG có trong block (vd VCK)" in prompt
    assert "CON SỐ THẬT copy từ block" in prompt
    assert 'nói "cần thêm dữ liệu' in prompt
    assert 'gọi "Op.CF âm" cho mã có Op.CF ≥ 0' in prompt
    # no leakable placeholder like "X Op.CF=−Y" + must say skip OCF when none
    assert "X Op.CF=−Y" not in prompt
    assert "KHÔNG in nguyên ký hiệu mẫu" in prompt
    assert "CHỈ nêu rủi ro D/E (mã cao nhất)" in prompt


def test_build_prompt_precomputes_weekly_range_position():
    # #2: position in the weekly range is computed, not left to the LLM.
    # close 1793.05 in [1780.71, 1846.71] → ~18.7% → "gần đáy".
    ctx = {"date": "2026-06-09", "time": "15:00",
           "vnindex_tech": {"close": 1793.05, "week_low": 1780.71,
                            "week_high": 1846.71, "day_low": 1790.0,
                            "day_high": 1800.0}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Vị trí range tuần: 19%" in prompt   # round(18.7) = 19
    assert "gần đáy range" in prompt


def test_afternoon_trigger_stays_two_directional():
    # #3: "Trigger ngày mai" must keep both directions, separate from Stance.
    prompt = build_prompt({"date": "2026-06-09", "time": "15:00"},
                          brief_type="afternoon")
    assert "BẮT BUỘC nêu CẢ HAI chiều" in prompt


def test_afternoon_watchlist_nudges_to_use_priced_movers():
    # When movers carry a price, the watchlist must use them instead of bailing
    # with "Cần thêm dữ liệu giá" (observed empty watchlist despite STB/PLX).
    ctx = {"date": "2026-06-09", "time": "15:00",
           "vn30_gainers": [{"Mã": "STB", "Giá 1T %": 2.1, "Ngành": "Ngân hàng",
                             "last": 70.7}],
           "vn30_losers": [{"Mã": "PLX", "Giá 1T %": -1.5, "Ngành": "Năng lượng",
                            "last": 40.85}]}
    prompt = build_prompt(ctx, brief_type="afternoon")
    # the priced movers are present for the agent to anchor on … (VN30 → ⭐)
    assert "Giá 70,700" in prompt and "Giá 40,850" in prompt
    # … and the instruction forces using the ⭐ movers rather than bailing
    assert "BẮT BUỘC dùng ÍT NHẤT 1-2 mã ⭐ đó làm setup" in prompt
    assert "CHỈ viết đúng 1 dòng" in prompt


# ─── Whole-market liquidity-filtered movers (broader than VN30) ───────────────

def test_select_liquid_movers_whole_market_filtered():
    tickers = [
        {"Mã": "FPT", "Giá 1T %": 1.5, "Ngành": "CNTT", "last": 124.0,
         "GTGD TB (tỷ)": 500},                      # VN30, liquid
        {"Mã": "GEX", "Giá 1T %": 8.0, "Ngành": "Công nghiệp", "last": 25.0,
         "GTGD TB (tỷ)": 300},                      # non-VN30 mid-cap, liquid
        {"Mã": "PENNY", "Giá 1T %": 20.0, "Ngành": "X", "last": 3.0,
         "GTGD TB (tỷ)": 2},                        # illiquid → excluded
        {"Mã": "STB", "Giá 1T %": -3.0, "Ngành": "Ngân hàng", "last": 27.0,
         "GTGD TB (tỷ)": 0.5},                      # VN30 but low GTGD → kept
        {"Mã": "POM", "Giá 1T %": 15.0, "Ngành": "Thép", "last": 4.3,
         "GTGD TB (tỷ)": 50},                       # liquid but sub-5k penny → excluded
    ]
    g, l, uni = _select_liquid_movers(tickers, min_gtgd_ty=10, min_price_ty=5.0, n=5)
    names = {r["Mã"] for r in g} | {r["Mã"] for r in l}
    assert "GEX" in names            # liquid mid-cap surfaced (not just VN30)
    assert "PENNY" not in names      # illiquid excluded
    assert "PENNY" not in uni
    assert "POM" not in names        # liquid but sub-5k penny → price floor
    assert "POM" not in uni
    assert "STB" in uni              # VN30 always kept despite low GTGD
    assert g[0]["Mã"] == "GEX"       # ranked by 1-week % change
    # GTGD carried through so the renderer can tag watchlist-eligible (⭐) movers
    assert "GTGD TB (tỷ)" in g[0]


def test_movers_mark_watchlist_eligible_with_star():
    # Watchlist setups are gated to ⭐ = VN30 OR GTGD ≥ _WATCHLIST_GTGD_MIN_TY.
    # A thin mid-cap (below the bar) is shown for analysis but must NOT get ⭐, so it
    # cannot be turned into a trade idea (regression for the "VIW MUA setup").
    from vnstock_brief import _WATCHLIST_GTGD_MIN_TY
    ctx = {
        "date": "2026-06-09", "time": "15:00",
        "vn30_gainers": [
            {"Mã": "STB", "Giá 1T %": 2.1, "Ngành": "Ngân hàng", "last": 70.7,
             "GTGD TB (tỷ)": 5.0},                            # VN30 → ⭐ dù GTGD thấp
            {"Mã": "GEX", "Giá 1T %": 8.0, "Ngành": "CN", "last": 30.0,
             "GTGD TB (tỷ)": _WATCHLIST_GTGD_MIN_TY + 1},     # mid-cap thanh khoản → ⭐
        ],
        "vn30_losers": [
            {"Mã": "VIW", "Giá 1T %": -3.0, "Ngành": "Nước", "last": 25.6,
             "GTGD TB (tỷ)": 12.0},                           # mid-cap mỏng → KHÔNG ⭐
        ],
    }
    prompt = build_prompt(ctx, brief_type="afternoon")
    lines = {l.split()[1]: l for l in prompt.splitlines()
             if l.startswith("- ") and len(l.split()) > 1}
    assert "⭐" in lines["STB"]        # VN30 eligible despite sub-threshold GTGD
    assert "⭐" in lines["GEX"]        # liquid mid-cap eligible
    assert "⭐" not in lines["VIW"]    # thin mid-cap → analysis only, no setup
    assert "CÓ DẤU ⭐" in prompt       # instruction gates setups on the ⭐ marker


def test_select_liquid_movers_guarantees_eligible_anchor():
    # Top-% movers are all thin non-⭐ names; VN30/liquid names exist but didn't
    # crack the top-n by weekly move. The block must still surface ≥1 ⭐ name so
    # the watchlist has an anchor (regression: 11/06 empty watchlist).
    from vnstock_brief import _WATCHLIST_GTGD_MIN_TY
    tickers = [
        {"Mã": "THIN1", "Giá 1T %": 25.0, "Ngành": "X", "last": 12.0, "GTGD TB (tỷ)": 12},
        {"Mã": "THIN2", "Giá 1T %": 20.0, "Ngành": "X", "last": 11.0, "GTGD TB (tỷ)": 11},
        {"Mã": "THIN3", "Giá 1T %": -22.0, "Ngành": "X", "last": 9.0, "GTGD TB (tỷ)": 13},
        {"Mã": "THIN4", "Giá 1T %": -18.0, "Ngành": "X", "last": 8.0, "GTGD TB (tỷ)": 14},
        {"Mã": "FPT", "Giá 1T %": 1.2, "Ngành": "CNTT", "last": 120.0,
         "GTGD TB (tỷ)": _WATCHLIST_GTGD_MIN_TY + 500},   # ⭐ but small move
    ]
    g, l, _ = _select_liquid_movers(tickers, n=2)
    shown = {r["Mã"] for r in g} | {r["Mã"] for r in l}
    assert "FPT" in shown            # eligible anchor forced in despite tiny move
    assert "FPT" in {r["Mã"] for r in g}   # +1.2% → gainer side


def test_build_prompt_full_day_gtgd_comparison_is_day_over_day():
    # Close brief must compare full-day GTGD day-over-day, not borrow the
    # morning's sáng-với-sáng % (observed: "GTGD 11,929 tỷ, giảm 43% so với
    # sáng phiên trước" — wrong baseline). 11,929 vs prev 13,000 ≈ -8%.
    ctx = {"date": "2026-06-11", "time": "15:00",
           "vnindex_tech": {"close": 1798.61, "intraday": False},
           "full_day_gtgd": 11929.2,
           "full_day_gtgd_cmp": {"prev": 13000.0, "avg5": 12500.0, "avg20": 14000.0}}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "So sánh cả-ngày-với-cả-ngày" in p or "So sánh CẢ-NGÀY-với-CẢ-NGÀY" in p
    assert "phiên trước 13,000.0 tỷ (-8%)" in p
    assert "TB5 phiên 12,500.0 tỷ (-5%)" in p
    assert "TB20 phiên 14,000.0 tỷ (-15%)" in p   # real TB20 (model invented it before)
    assert "KHÔNG tự suy TB khác" in p


def test_enforce_watchlist_hygiene_rounds_levels_to_hose_tick():
    # Setup levels must land on the HOSE tick (CII 17,200 → tick 50; GEE 95,500
    # → tick 100). Odd model levels (17,716 / 16,684 / 92,635 / 98,365) get
    # rounded; the stock price and list index are untouched.
    from vnstock_brief import enforce_watchlist_hygiene
    text = ("📋 Watchlist sáng mai\n"
            "1. **CII** (Giá 17,200) — canh mua nếu vượt 17,716 · mục tiêu 18,530 · cắt lỗ 16,684\n"
            "2. **GEE** (Giá 95,500) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng 92,635 · mục tiêu về 89,940 · hủy nếu vượt lại 98,365\n"
            "⚠️ Rủi ro")
    fixed = enforce_watchlist_hygiene(text, {})
    assert "vượt 17,700" in fixed and "cắt lỗ 16,700" in fixed and "18,550" in fixed
    assert "thủng 92,600" in fixed and "98,400" in fixed and "89,900" in fixed
    assert "17,716" not in fixed and "92,635" not in fixed
    # all setup numbers are now valid ticks
    import re as _re
    for n in _re.findall(r"\d{1,3}(?:,\d{3})+", fixed):
        v = int(n.replace(",", ""))
        tick = 50 if v < 50_000 else 100
        assert v % tick == 0, f"{v} not on tick"


def test_movers_star_line_carries_per_stock_reference_levels():
    # ⭐ movers must surface ±3% reference levels computed from the stock's own
    # price, so the watchlist anchors a setup to those instead of grabbing the
    # VNINDEX S/R (recurring empty-watchlist bug). 70.6 (nghìn) → 70,600 →
    # support ~68,482→68,500, resistance ~72,718→72,700 (tick 100).
    ctx = {"date": "2026-06-11", "time": "15:00",
           "vn30_gainers": [{"Mã": "STB", "Giá 1T %": 1.0, "Ngành": "NH",
                             "last": 70.6, "GTGD TB (tỷ)": 800.0}]}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "STB" in p and "⭐" in p
    assert "mốc của mã: hỗ trợ ~68,500 / kháng cự ~72,700" in p
    assert "LẤY TỪ" in p          # watchlist instruction points at these levels


def test_enforce_no_composite_jargon_labels_score():
    # "Thép & Kim loại (composite=-0.76)" → plain label so the reader doesn't
    # face an internal quant number. Threshold buckets verified at the edges.
    from vnstock_brief import enforce_no_composite_jargon
    assert enforce_no_composite_jargon(
        "Tránh: Thép & Kim loại (composite=-0.76).", {}
    ) == "Tránh: Thép & Kim loại (tín hiệu phân phối mạnh)."
    assert "tín hiệu phân phối)" in enforce_no_composite_jargon("X composite=-0.30", {})
    assert "tín hiệu tích luỹ mạnh" in enforce_no_composite_jargon("Y composite=0.70", {})
    # VN-format number + no "composite" → untouched
    assert enforce_no_composite_jargon("không có gì", {}) == "không có gì"


def test_build_prompt_sector_blocks_use_composite_label_not_raw():
    # The quant blocks must feed a label, never "composite=<số>".
    ctx = {"date": "2026-06-11", "time": "15:00",
           "quant_distribution": [{"Ngành": "Thép & Kim loại", "composite": -0.76}]}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "tín hiệu phân phối mạnh" in p
    assert "composite=-0.76" not in p          # the raw VALUE is never fed as data
    assert "Thép & Kim loại** —" in p          # rendered with the label, not the score


def test_enforce_no_placeholder_leak_fixes_ma_echo():
    # 22:29: "MÃ D/E=8.83 (HNG), MÃ D/E=2.67 (PET)" — the "<tên mã>" placeholder
    # echoed literally as "MÃ". Rewrite to "HNG D/E=8.83 …".
    from vnstock_brief import enforce_no_placeholder_leak
    text = ("⚠️ Rủi ro\nMÃ D/E=8.83 (HNG), MÃ D/E=2.67 (PET), MÃ Op.CF=-17,344 tỷ (KBC).")
    fixed = enforce_no_placeholder_leak(text, {})
    assert "HNG D/E=8.83" in fixed and "PET D/E=2.67" in fixed
    assert "KBC Op.CF=-17,344 tỷ" in fixed
    assert "MÃ D/E" not in fixed and "MÃ Op.CF" not in fixed
    # clean text untouched (no stray "MÃ ")
    t2 = "HNG D/E=8.83 — đòn bẩy cao."
    assert enforce_no_placeholder_leak(t2, {}) == t2


def test_enforce_no_instruction_leak_strips_echoed_guidance():
    from vnstock_brief import enforce_no_instruction_leak
    text = ("🔧 Đề xuất bổ sung\nCần theo dõi CPI, lãi suất.\n"
            "Giới hạn 500 từ. Nếu thị trường flat và không có signal rõ thì nói thẳng.")
    fixed = enforce_no_instruction_leak(text, {})
    assert "Giới hạn 500 từ" not in fixed
    assert "Cần theo dõi CPI" in fixed          # real content kept
    # clean brief untouched
    t2 = "🎯 TLDR\nVNINDEX -0.28%."
    assert enforce_no_instruction_leak(t2, {}) == t2


def test_build_prompt_movers_header_is_liquidity_not_vn30():
    ctx = {"date": "2026-06-09", "time": "15:00",
           "vn30_gainers": [{"Mã": "GEX", "Giá 1T %": 8.0, "Ngành": "CN",
                             "last": 25.0}]}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "Top Gainers thanh khoản cao" in prompt
    assert "VN30 Top Gainers" not in prompt


def test_build_prompt_breadth_label_negative_when_ad_below_one():
    # A/D 0.90 < 1.0 must be labelled TIÊU CỰC (regression: was called "tích cực").
    ctx = {"date": "2026-06-09", "time": "15:00",
           "breadth": {"ad_ratio": 0.90, "above_ma200_pct": 16,
                       "net_new_highs": -5, "rsi_oversold": 40,
                       "rsi_overbought": 2}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "ĐỘ RỘNG: TIÊU CỰC (A/D < 1.0" in prompt
    assert "ít mã trên MA200 → thị trường yếu" in prompt


def test_build_prompt_breadth_label_positive_when_ad_above_one():
    ctx = {"date": "2026-06-09", "time": "15:00",
           "breadth": {"ad_ratio": 1.40, "above_ma200_pct": 65,
                       "net_new_highs": 20, "rsi_oversold": 3,
                       "rsi_overbought": 30}}
    prompt = build_prompt(ctx, brief_type="afternoon")
    assert "ĐỘ RỘNG: TÍCH CỰC (A/D > 1.0" in prompt


def test_vn30_fund_block_excludes_financials_by_industry():
    # Mid-cap financials not in _FINANCIAL_TICKERS (e.g. BVB bank, VPX) must be
    # excluded from the D/E & Op.CF rankings via the industry-derived set.
    funds = {
        "BVB": {"de": 16.88, "roe": 9.0, "ocf": -35042.0, "updated": "2026-06-10"},
        "VPX": {"de": 3.0, "roe": 5.0, "ocf": -35042.0, "updated": "2026-06-10"},
        "HPG": {"de": 1.5, "roe": 12.0, "ocf": -300.0, "updated": "2026-06-10"},
        "FPT": {"de": 1.1, "roe": 25.0, "ocf": 8000.0, "updated": "2026-06-10"},
    }
    block = _vn30_fund_block(funds, extra_financial={"BVB", "VPX"})
    assert "BVB" not in block and "VPX" not in block      # financials excluded
    assert "-35,042" not in block                         # the bank-scale OCF gone
    assert "16.88" not in block                           # bank D/E gone
    assert "HPG" in block and "1 mã âm" in block          # non-fin still ranked
