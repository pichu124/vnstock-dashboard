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
    # a trigger AT the current price (11:03 CII "vượt 17,200") is not a real
    # breakout → bumped to ~+2%
    t3 = ("📋 Watchlist sáng mai\n"
          "1. **CII** (Giá 17,200) — canh MUA NẾU vượt 17,200 · mục tiêu 17,700 · cắt lỗ 16,700\n"
          "⚠️ Rủi ro")
    assert "vượt 17,550" in enforce_watchlist_hygiene(t3, {"bias_floor": {"dir": "GIẢM"}})


def test_enforce_no_cjk_normalizes_sentiment_typo():
    # Recurring model typo on our own sentiment label: "Sổ hãi" (23:56) and
    # "Sờ hãi" (earlier run) → "Sợ hãi".
    from vnstock_brief import enforce_no_cjk
    assert enforce_no_cjk("Tâm lý: ❄️ Sổ hãi, momentum -61/100") == \
        "Tâm lý: ❄️ Sợ hãi, momentum -61/100"
    assert enforce_no_cjk("Tâm lý ❄️ Sờ hãi hôm nay") == "Tâm lý ❄️ Sợ hãi hôm nay"
    t = "Tâm lý: ❄️ Sợ hãi, momentum -61/100"
    assert enforce_no_cjk(t) == t


def test_enforce_money_flow_ranks_true_top_sell_not_mislabeled_bucket():
    # 12:03: Thép -1,372 was the biggest foreign sell but sat in a "phân phối"
    # clause while Ngân hàng -703 was called "bán ròng mạnh nhất". The guard must
    # surface the TRUE top sell (named in a bán-ròng line), not just trust the
    # number's presence.
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": -1372.0},
                       {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0},
                       {"Ngành": "Thực phẩm & Đồ uống", "NN 1T (tỷ)": 136.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "Khối ngoại bán ròng mạnh Ngân hàng -703 tỷ. Smart money phân phối tại "
            "Thép & Kim loại (NN -1,372 tỷ).\n"
            "📋 Watchlist")
    fixed = enforce_money_flow_two_sides(text, ctx)
    assert "NN bán ròng mạnh nhất (1 tuần): Thép & Kim loại -1,372 tỷ" in fixed
    # already-correct ranking → no duplicate
    t2 = ("💰 Dòng tiền đáng chú ý\n"
          "Bán ròng mạnh Thép & Kim loại -1,372 tỷ, Ngân hàng -703 tỷ; mua ròng "
          "Thực phẩm & Đồ uống +136 tỷ.\n📋 Watchlist")
    assert enforce_money_flow_two_sides(t2, ctx) == t2


def test_enforce_money_flow_corrects_fabricated_number_after_name():
    # 12:03 root cause: the model attached a FABRICATED foreign-flow figure to a
    # sector in a parenthetical — "Thép & Kim loại (NN -1,372 tỷ)" — while the
    # real NN 1T was far smaller. The number-AFTER-name corrector must rewrite it
    # to the true signed value (the before-name regex can't see parentheticals).
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": -180.0},
                       {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0},
                       {"Ngành": "Thực phẩm & Đồ uống", "NN 1T (tỷ)": 136.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "Khối ngoại bán ròng mạnh Ngân hàng -703 tỷ. Smart money phân phối tại "
            "Thép & Kim loại (NN -1,372 tỷ).\n"
            "📋 Watchlist")
    fixed = enforce_money_flow_two_sides(text, ctx)
    assert "Thép & Kim loại (NN -180 tỷ)" in fixed
    assert "-1,372" not in fixed
    # Ngân hàng -703 is now the true top sell, named in a bán-ròng clause → no
    # canonical sell line; only the missing buy side is appended.
    assert "NN bán ròng mạnh nhất" not in fixed
    assert "NN mua ròng mạnh nhất (1 tuần): Thực phẩm & Đồ uống +136 tỷ" in fixed


def test_enforce_money_flow_corrects_wrong_sector_number_in_prose():
    # 11:19: "mua ròng 5 tỷ … Thực phẩm & Đồ uống" while the real NN 1T = +136
    # (and the canonical line said +136 → contradiction). Correct the prose
    # number (number-precedes-name phrasing); abs value, sign from mua/bán.
    from vnstock_brief import enforce_money_flow_two_sides
    ctx = {"sectors": [{"Ngành": "Thực phẩm & Đồ uống", "NN 1T (tỷ)": 136.0},
                       {"Ngành": "Dầu khí", "NN 1T (tỷ)": 44.0},
                       {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "NN mua ròng 5 tỷ đồng trong ngành Thực phẩm & Đồ uống và 44 tỷ đồng "
            "trong ngành Dầu khí, trong khi bán ròng 703 tỷ đồng trong ngành Ngân hàng.\n"
            "📋 Watchlist")
    fixed = enforce_money_flow_two_sides(text, ctx)
    assert "136 tỷ đồng trong ngành Thực phẩm & Đồ uống" in fixed
    assert "5 tỷ đồng trong ngành Thực phẩm" not in fixed
    assert "44 tỷ đồng trong ngành Dầu khí" in fixed       # already right, untouched
    assert "703 tỷ đồng trong ngành Ngân hàng" in fixed    # already right, untouched


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
    # MUA vùng → conditional; trigger at price (17,200) bumped to ~+2% (17,550),
    # target follows (18,100), levels rounded to tick 50
    assert "canh MUA NẾU vượt 17,550 · mục tiêu 18,100 · cắt lỗ 16,700" in fixed
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


def test_enforce_liquidity_label_replaces_negative_thanh_khoan_with_gtgd():
    # 12:33: "Thanh khoản ngành tập trung vào Ngân hàng (-703 tỷ), Bất động sản
    # (-307 tỷ), Chứng khoán (2,353 tỷ)" — -703/-307 are NN net-sell figures
    # mislabeled as turnover. The liquidity clause must become the canonical
    # top-GTGD line; the sibling NN clause on the same line is untouched.
    from vnstock_brief import enforce_liquidity_label
    ctx = {"sectors": [
        {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0, "GTGD TB (tỷ)": 4100.0},
        {"Ngành": "Chứng khoán & Đầu tư tài chính", "NN 1T (tỷ)": -433.0, "GTGD TB (tỷ)": 2353.0},
        {"Ngành": "Bất động sản", "NN 1T (tỷ)": -307.0, "GTGD TB (tỷ)": 1800.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "NN bán ròng mạnh: Ngân hàng -703 tỷ, Bất động sản -307 tỷ. "
            "Thanh khoản ngành tập trung vào Ngân hàng (-703 tỷ), Bất động sản "
            "(-307 tỷ), Chứng khoán (2,353 tỷ).\n"
            "📋 Watchlist")
    fixed = enforce_liquidity_label(text, ctx)
    # the bogus negative liquidity figures are gone
    assert "Ngân hàng (-703 tỷ)" not in fixed
    assert "Bất động sản (-307 tỷ)" not in fixed
    # canonical top-GTGD line (positive figures, real ranking) inserted
    assert "Thanh khoản cao nhất (GTGD TB 1 tuần): Ngân hàng 4,100 tỷ" in fixed
    # the genuine NN clause is preserved (the -703/-307 NN figures stay there)
    assert "NN bán ròng mạnh: Ngân hàng -703 tỷ, Bất động sản -307 tỷ." in fixed
    # idempotent
    assert enforce_liquidity_label(fixed, ctx) == fixed


def test_enforce_liquidity_label_noop_when_clean():
    from vnstock_brief import enforce_liquidity_label
    ctx = {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0, "GTGD TB (tỷ)": 4100.0}]}
    # positive liquidity figures → untouched
    t1 = ("💰 Dòng tiền đáng chú ý\nThanh khoản cao nhất: Ngân hàng 4,100 tỷ.\n📋 Watchlist")
    assert enforce_liquidity_label(t1, ctx) == t1
    # genuine NN clause mentioning a negative, even with 'thanh khoản' elsewhere
    # in the same clause window, is not mangled
    t2 = ("💰 Dòng tiền đáng chú ý\nNN bán ròng BĐS -5,275 tỷ; thanh khoản dồn "
          "vào nhóm vốn hóa lớn.\n📋 Watchlist")
    assert enforce_liquidity_label(t2, ctx) == t2
    # no sector data → untouched
    assert enforce_liquidity_label(t1, {}) == t1


def test_enforce_nn_window_label_fixes_1d_tagged_weekly():
    # 12:42: "Khối ngoại bán ròng mạnh 665 tỷ tuần này (1D: -665 tỷ)" — the 1D
    # foreign total is tagged 'tuần này' (and understates the week: Ngân hàng
    # alone is -703 tỷ/tuần). The self-contradiction (weekly + (1D)) must lose
    # the weekly tag.
    from vnstock_brief import enforce_nn_window_label
    ctx = {"market_sentiment": {"signals": [{"name": "NN ròng 1D", "value": "-665 tỷ"}]},
           "sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    text = ("💰 Dòng tiền đáng chú ý\n"
            "Khối ngoại bán ròng mạnh 665 tỷ tuần này (1D: -665 tỷ). Ngân hàng "
            "(-703 tỷ) bị bán mạnh nhất.\n📋 Watchlist")
    fixed = enforce_nn_window_label(text, ctx)
    assert "665 tỷ (1D: -665 tỷ)" in fixed
    assert "tuần này (1D" not in fixed
    assert "665 tỷ tuần này" not in fixed
    # idempotent
    assert enforce_nn_window_label(fixed, ctx) == fixed


def test_enforce_nn_window_label_relabels_1d_without_marker():
    # 1D magnitude tagged weekly with no "(1D" marker → relabel to 1D (ctx-driven).
    from vnstock_brief import enforce_nn_window_label
    ctx = {"market_sentiment": {"signals": [{"name": "NN ròng 1D", "value": "-665 tỷ"}]},
           "sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    text = "Khối ngoại bán ròng 665 tỷ tuần này.\n"
    fixed = enforce_nn_window_label(text, ctx)
    assert "665 tỷ (1D, phiên gần nhất)" in fixed
    assert "665 tỷ tuần này" not in fixed


def test_enforce_nn_window_label_noop_cases():
    from vnstock_brief import enforce_nn_window_label
    ctx = {"market_sentiment": {"signals": [{"name": "NN ròng 1D", "value": "-665 tỷ"}]},
           "sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    # a genuine weekly sector figure (703) tagged weekly is NOT relabeled
    t1 = "NN bán ròng Ngân hàng 703 tỷ tuần này.\n"
    assert enforce_nn_window_label(t1, ctx) == t1
    # coincidence guard: if a sector's weekly value equals the 1D magnitude, skip
    ctx_coin = {"market_sentiment": {"signals": [{"name": "NN ròng 1D", "value": "-703 tỷ"}]},
                "sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    t2 = "Ngân hàng bán ròng 703 tỷ tuần này.\n"
    assert enforce_nn_window_label(t2, ctx_coin) == t2
    # no 1D signal → untouched
    assert enforce_nn_window_label("665 tỷ tuần này.\n", {}) == "665 tỷ tuần này.\n"


def test_enforce_nn_window_label_tolerates_markdown_bold():
    # Brief #212 (15/08) NGUYÊN VĂN: "khối ngoại bán ròng **856 tỷ** tuần qua"
    # — 856 là NN ròng MỘT NGÀY 14/08, ctx có đủ dữ liệu, nhưng guard cũ đòi
    # khoảng trắng thuần giữa số và "tuần" nên cặp ** của markdown lọt qua.
    from vnstock_brief import enforce_nn_window_label
    ctx = {"market_sentiment": {"signals": [{"name": "NN ròng 1D",
                                             "value": "-856 tỷ"}]},
           "sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": -1965.0}]}
    text = ("Độ rộng thị trường tiêu cực (A/D=0.56), khối ngoại bán ròng "
            "**856 tỷ** tuần qua. Tâm lý: Sợ hãi.\n")
    fixed = enforce_nn_window_label(text, ctx)
    assert "**856 tỷ** (1D, phiên gần nhất)" in fixed
    assert "tuần qua" not in fixed
    assert fixed.count("**") % 2 == 0        # bold không được lệch cặp
    assert enforce_nn_window_label(fixed, ctx) == fixed   # idempotent


def test_enforce_nn_window_label_scopes_sector_week_claimed_marketwide():
    # Brief #212: "Khối ngoại **bán ròng 1,965 tỷ** tuần qua (Họ VIN -1,965
    # tỷ, GTGD 1,594 tỷ)" — số TUẦN của RIÊNG Họ VIN nói như toàn thị trường.
    # Guard chèn tên ngành ngay sau "ròng" để phạm vi claim đúng.
    from vnstock_brief import enforce_nn_window_label
    ctx = {"market_sentiment": {"signals": [{"name": "NN ròng 1D",
                                             "value": "-856 tỷ"}]},
           "sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": -1965.0},
                       {"Ngành": "Họ M", "NN 1T (tỷ)": 477.0}]}
    text = ("Khối ngoại **bán ròng 1,965 tỷ** tuần qua (Họ VIN -1,965 tỷ, "
            "GTGD 1,594 tỷ) — áp lực phân phối rõ rệt.\n")
    fixed = enforce_nn_window_label(text, ctx)
    assert "**bán ròng Họ VIN 1,965 tỷ** tuần qua" in fixed
    assert enforce_nn_window_label(fixed, ctx) == fixed   # idempotent
    # câu ĐÃ nêu tên ngành trước con số thì không đụng (không chèn trùng)
    ok = "NN bán ròng Họ VIN 1,965 tỷ tuần qua.\n"
    assert enforce_nn_window_label(ok, ctx) == ok
    # dòng canon "mạnh nhất (1 tuần): {ngành} {v} tỷ" cũng không được đụng
    canon = "NN mua ròng mạnh nhất (1 tuần): Họ M +477 tỷ.\n"
    assert enforce_nn_window_label(canon, ctx) == canon


def test_enforce_nn_window_label_sector_scope_skips_unrefereeable():
    from vnstock_brief import enforce_nn_window_label
    # ≥2 ngành trùng magnitude tuần → không biết của ai → không đụng
    ctx2 = {"sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": -1965.0},
                        {"Ngành": "Ngân hàng", "NN 1T (tỷ)": 1965.0}]}
    t = "Khối ngoại bán ròng 1,965 tỷ tuần qua.\n"
    assert enforce_nn_window_label(t, ctx2) == t
    # magnitude trùng tổng 1D → cũng không phân xử được → không đụng
    # (nhánh 2 đã skip vì coincident với ngành — nhánh 3 phải skip nốt)
    ctx3 = {"market_sentiment": {"signals": [{"name": "NN ròng 1D",
                                              "value": "-1,965 tỷ"}]},
            "sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": -1965.0}]}
    assert enforce_nn_window_label(t, ctx3) == t


def test_enforce_no_bias_directive_leak_strips_bat_buoc():
    # 12:24 & 12:51 leaked the internal directive word into the TLDR:
    # "bias GIẢM bắt buộc". The qualifier must be stripped, the direction kept.
    from vnstock_brief import enforce_no_bias_directive_leak
    t1 = ("🎯 TLDR\n**Thị trường yếu, momentum tiêu cực (-61/100), bias GIẢM bắt buộc.**\n"
          "Stance ngày mai: GIẢM")
    f1 = enforce_no_bias_directive_leak(t1, {})
    assert "bias GIẢM." in f1
    assert "bắt buộc" not in f1.lower()
    # other orderings / casings
    assert "Bias = TĂNG" in enforce_no_bias_directive_leak("Bias bắt buộc = TĂNG", {}).replace("  ", " ")
    assert "buộc" not in enforce_no_bias_directive_leak("Stance GIẢM (bắt buộc)", {}).lower()
    # idempotent + no-op when clean
    assert enforce_no_bias_directive_leak(f1, {}) == f1
    clean = "🎯 TLDR\nStance ngày mai: GIẢM"
    assert enforce_no_bias_directive_leak(clean, {}) == clean


def test_enforce_no_record_superlative_strips_all_time_gtgd_claim():
    # 12:51: "GTGD thấp kỷ lục (11,929.2 tỷ, -35% vs TB20)" — the brief has no
    # historical extreme, only TB5/TB20 → drop the all-time qualifier.
    from vnstock_brief import enforce_no_record_superlative
    t = ("📊 Tổng kết phiên\nGTGD thấp kỷ lục (11,929.2 tỷ, -35% vs TB20 phiên).\n"
         "Thanh khoản thấp nhất lịch sử cho thấy thị trường yếu.")
    f = enforce_no_record_superlative(t, {})
    assert "GTGD thấp (11,929.2 tỷ" in f
    assert "kỷ lục" not in f
    assert "lịch sử" not in f
    assert "Thanh khoản thấp cho thấy" in f
    # a non-liquidity line keeps 'kỷ lục' (e.g. record profit, data-backed elsewhere)
    keep = "Lợi nhuận quý đạt kỷ lục."
    assert enforce_no_record_superlative(keep, {}) == keep


def test_enforce_gtgd_compare_frame_swaps_morning_baseline_for_fullday():
    # 13:00: the close summary compared the full-day GTGD against MORNING
    # baselines with an impossible direction — "(11,929.2 tỷ), thấp hơn 43% so
    # sáng phiên trước (9,129.4 tỷ) và 34% so TB sáng 5 phiên (7,959.6 tỷ)".
    # Must become the canonical full-day comparison (TB5/TB20 phiên).
    from vnstock_brief import enforce_gtgd_compare_frame
    ctx = {"full_day_gtgd": 11929.2,
           "full_day_gtgd_cmp": {"prev": 13000.0, "avg5": 13556.0, "avg20": 18353.0}}
    text = ("📊 Tổng kết phiên\n"
            "Phiên chiều chủ đạo chiếm 56% GTGD (11,929.2 tỷ), thấp hơn 43% so "
            "sáng phiên trước (9,129.4 tỷ) và 34% so TB sáng 5 phiên (7,959.6 tỷ). "
            "Độ rộng tiêu cực (A/D=0.87).\n"
            "📈 Mức kỹ thuật")
    fixed = enforce_gtgd_compare_frame(text, ctx)
    assert "sáng phiên trước" not in fixed
    assert "TB sáng" not in fixed
    assert "thấp hơn TB5 phiên (-12%) và TB20 phiên (-35%)" in fixed
    # the full-day number and the rest of the sentence survive
    assert "GTGD (11,929.2 tỷ), thấp hơn TB5 phiên" in fixed
    assert "Độ rộng tiêu cực (A/D=0.87)." in fixed
    # idempotent
    assert enforce_gtgd_compare_frame(fixed, ctx) == fixed


def test_enforce_gtgd_compare_frame_noop_cases():
    from vnstock_brief import enforce_gtgd_compare_frame
    ctx = {"full_day_gtgd": 11929.2,
           "full_day_gtgd_cmp": {"avg5": 13556.0, "avg20": 18353.0}}
    # a correct full-day comparison is left alone
    ok = ("📊 Tổng kết phiên\nGTGD cả ngày 11,929.2 tỷ thấp hơn TB5 phiên (-12%) "
          "và TB20 phiên (-35%).\n📈 Mức kỹ thuật")
    assert enforce_gtgd_compare_frame(ok, ctx) == ok
    # the morning brief's own sáng-với-sáng comparison (not in a "Tổng kết phiên"
    # close section) is untouched
    morn = ("📊 Tổng quan phiên sáng\nGTGD sáng 5,200 tỷ, thấp hơn 43% so sáng "
            "phiên trước (9,129.4 tỷ).\n📈 Mức kỹ thuật")
    assert enforce_gtgd_compare_frame(morn, ctx) == morn
    # no cmp data → untouched
    assert enforce_gtgd_compare_frame(
        "📊 Tổng kết phiên\nGTGD (1 tỷ) thấp hơn 9% so sáng phiên trước (2 tỷ).", {}) \
        == "📊 Tổng kết phiên\nGTGD (1 tỷ) thấp hơn 9% so sáng phiên trước (2 tỷ)."


def test_enforce_no_duplicate_momentum_collapses_repeat():
    # 13:14: "Tổng kết phiên" stated momentum twice in one line — once on the
    # breadth clause, once with tâm lý. Keep the last (tâm-lý) mention only.
    from vnstock_brief import enforce_no_duplicate_momentum
    t = ("📊 Tổng kết phiên\n"
         "Độ rộng tiêu cực (A/D=0.87, 17% trên MA200), momentum -61/100. Tâm lý: "
         "❄️ Sợ hãi, momentum -61/100 → xu hướng ngắn hạn yếu.\n📈 Mức kỹ thuật")
    f = enforce_no_duplicate_momentum(t, {})
    assert f.count("momentum -61/100") == 1
    assert "17% trên MA200). Tâm lý:" in f          # earlier dup removed cleanly
    assert "Sợ hãi, momentum -61/100 → xu hướng" in f  # tâm-lý mention kept
    assert enforce_no_duplicate_momentum(f, {}) == f   # idempotent


def test_enforce_no_duplicate_momentum_keeps_distinct_and_single():
    from vnstock_brief import enforce_no_duplicate_momentum
    # a single mention is untouched
    one = "Tâm lý: Sợ hãi, momentum -61/100 → yếu."
    assert enforce_no_duplicate_momentum(one, {}) == one
    # two DIFFERENT values are both kept (not a redundancy)
    two = "momentum -61/100 hôm nay vs momentum -40/100 phiên trước."
    assert enforce_no_duplicate_momentum(two, {}) == two


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


def test_enforce_watchlist_hygiene_bumps_trigger_with_paren_price_format():
    # 21:19: "CII (17,350) — canh MUA NẾU vượt 16,850" — the trigger 16,850 is
    # BELOW the price (it's CII's support). The price was in "(17,350)" form (no
    # "Giá" word), so the old bump regex missed it. Extract price from either
    # format and bump the trigger to a real breakout (~+2% above price).
    import re
    from vnstock_brief import enforce_watchlist_hygiene
    text = ("📋 Watchlist sáng mai\n"
            "1. **CII** (17,350) — canh MUA NẾU vượt 16,850 · mục tiêu 18,000 · cắt lỗ 16,500\n"
            "⚠️ Rủi ro")
    fixed = enforce_watchlist_hygiene(text, {"bias_floor": {"dir": "GIẢM"}})
    assert "vượt 16,850" not in fixed                  # support-as-trigger removed
    m = re.search(r"vượt (\d[\d,]*)", fixed)
    assert m and int(m.group(1).replace(",", "")) > 17350   # trigger now above price
    # the "(Giá ...)" form still works
    text2 = text.replace("(17,350)", "(Giá 17,350)")
    f2 = enforce_watchlist_hygiene(text2, {"bias_floor": {"dir": "GIẢM"}})
    assert "vượt 16,850" not in f2


def test_enforce_compare_direction_flips_word_to_match_sign():
    # Close 12/06: "GTGD cả ngày 18,353.2 tỷ (+4% vs TB20), thấp hơn TB5 phiên
    # (+43%) nhưng cao hơn phiên trước (+80%)" — 'thấp hơn' with +43% is a clash.
    from vnstock_brief import enforce_compare_direction
    t = ("GTGD cả ngày 18,353.2 tỷ (+4% vs TB20 phiên), thấp hơn TB5 phiên (+43%) "
         "nhưng cao hơn phiên trước (+80%).")
    f = enforce_compare_direction(t, {})
    assert "cao hơn TB5 phiên (+43%)" in f           # thấp + (+%) → cao
    assert "thấp hơn TB5" not in f
    assert "cao hơn phiên trước (+80%)" in f          # consistent → kept
    # cao + (-%) → thấp
    assert "thấp hơn X (-5%)" in enforce_compare_direction("cao hơn X (-5%)", {})
    # consistent pairs untouched
    ok = "GTGD thấp hơn TB20 (-12%) và TB5 (-35%)."
    assert enforce_compare_direction(ok, {}) == ok
    assert enforce_compare_direction(f, {}) == f      # idempotent


def test_enforce_compare_direction_form_c_inline_signed_pct():
    # Close 30/06: "GTGD … cao hơn -41% so với phiên trước và 37% so với TB20" —
    # inline signed % (no parens). 'cao hơn' + (-41%) is a clash → flip the word
    # and drop the now-redundant sign; the 2nd (unsigned) comparison is left.
    from vnstock_brief import enforce_compare_direction
    t = ("VNINDEX … GTGD 20,392.2 tỷ, cao hơn -41% so với phiên trước và 37% "
         "so với trung bình 20 phiên.")
    f = enforce_compare_direction(t, {})
    assert "thấp hơn 41% so với phiên trước" in f
    assert "cao hơn -41%" not in f
    assert "37% so với trung bình 20 phiên" in f      # 2nd comparison untouched
    assert enforce_compare_direction(f, {}) == f       # idempotent (no sign left)
    # reverse clash: 'thấp hơn +43% so với' → 'cao hơn 43% so với'
    assert "cao hơn 43% so với" in enforce_compare_direction(
        "thấp hơn +43% so với phiên trước", {})
    # consistent inline pair is left alone (keeps its explicit sign)
    assert enforce_compare_direction("cao hơn +37% so với TB20", {}) == "cao hơn +37% so với TB20"
    # change verbs (tăng/giảm) carry direction → verb from sign, sign always dropped
    assert enforce_compare_direction("GTGD tăng -10% so với phiên trước", {}) == "GTGD giảm 10% so với phiên trước"
    assert enforce_compare_direction("GTGD giảm -10% so với phiên trước", {}) == "GTGD giảm 10% so với phiên trước"
    assert enforce_compare_direction("GTGD giảm +42% so với TB5", {}) == "GTGD tăng 42% so với TB5"
    assert enforce_compare_direction("GTGD tăng +42% so với TB5", {}) == "GTGD tăng 42% so với TB5"


def test_enforce_gtgd_baseline_pct_handles_va_joined_dual_comparison():
    # Close 01/07: "GTGD toàn ngày 18,298.7 tỷ, tăng 0.39% so với phiên trước và
    # tăng 42% so với TB5" — the 'phiên trước' % (borrowed index change 0.39%) was
    # swallowed into one over-captured baseline. With the clause boundary it is
    # classified against prev and pinned; enforce_compare_direction then fixes the
    # verb ("tăng -10%" → "giảm 10%").
    from vnstock_brief import enforce_gtgd_baseline_pct, enforce_compare_direction
    ctx = {"full_day_gtgd": 18298.7,
           "full_day_gtgd_cmp": {"prev": 20392.2, "avg5": 12886.0}}
    t = ("📊 Tổng kết phiên\nGTGD toàn ngày đạt 18,298.7 tỷ, tăng 0.39% so với "
         "phiên trước và tăng 42% so với trung bình 5 phiên.\n📈 Mức kỹ thuật")
    f = enforce_compare_direction(enforce_gtgd_baseline_pct(t, ctx), ctx)
    assert "giảm 10% so với phiên trước" in f            # prev: down ~10%
    assert "tăng 42% so với trung bình 5 phiên" in f     # TB5: up ~42% (kept)
    assert "tăng 0.39% so với phiên trước" not in f      # index % no longer borrowed
    assert "tăng -" not in f and "giảm -" not in f       # no verb/sign clash left


def test_enforce_net_flow_label_aligns_verb_and_sign_to_ctx():
    # Close 30/06: "… trong khi bán ròng +129 tỷ trong ngành Ngân hàng" — a net
    # SELL with a '+' figure. Align the verb+sign to the sector's real NN.
    from vnstock_brief import enforce_net_flow_label
    # real NN is negative → keep 'bán ròng', strip the '+', emit magnitude
    ctx_sell = {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -129.0}]}
    t = "NN mua ròng 2,570 tỷ trong ngành Họ VIN, trong khi bán ròng +129 tỷ trong ngành Ngân hàng."
    f = enforce_net_flow_label(t, ctx_sell)
    assert "bán ròng 129 tỷ trong ngành Ngân hàng" in f
    assert "+129" not in f
    assert enforce_net_flow_label(f, ctx_sell) == f          # idempotent
    # real NN is POSITIVE → the 'bán ròng' label is wrong → flip to 'mua ròng'
    ctx_buy = {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": 129.0}]}
    assert "mua ròng 129 tỷ trong ngành Ngân hàng" in enforce_net_flow_label(t, ctx_buy)
    # noise (<30 tỷ) and missing data → no-op
    assert enforce_net_flow_label(t, {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": 5.0}]}) == t
    assert enforce_net_flow_label(t, {}) == t


def test_enforce_gtgd_baseline_pct_pins_pct_to_its_baseline():
    # Close 12/06: "GTGD cả ngày 18,353.2 tỷ (+4% vs TB5 phiên, +43% vs phiên
    # trước)" — % shifted onto wrong baselines (real: TB5 +43%, phiên trước +80%).
    from vnstock_brief import enforce_gtgd_baseline_pct
    ctx = {"full_day_gtgd": 18353.2,
           "full_day_gtgd_cmp": {"prev": 10196.0, "avg5": 12834.0, "avg20": 17647.0}}
    t = ("📊 Tổng kết phiên\nGTGD cả ngày 18,353.2 tỷ (+4% vs TB5 phiên, "
         "+43% vs phiên trước).\n📈 Mức kỹ thuật")
    f = enforce_gtgd_baseline_pct(t, ctx)
    assert "+43% vs TB5 phiên" in f
    assert "+80% vs phiên trước" in f
    assert "+4% vs TB5" not in f
    assert enforce_gtgd_baseline_pct(f, ctx) == f                  # idempotent
    # a correct mapping is left alone
    ok = ("📊 Tổng kết phiên\nGTGD cả ngày 18,353.2 tỷ (+43% vs TB5 phiên, "
          "+4% vs TB20 phiên).\n📈")
    assert enforce_gtgd_baseline_pct(ok, ctx) == ok
    # morning (no "Tổng kết phiên") is never touched
    morn = "📊 Tổng quan phiên sáng\nGTGD sáng cao hơn 60% so với sáng phiên trước."
    assert enforce_gtgd_baseline_pct(morn, ctx) == morn


def test_enforce_gtgd_baseline_pct_form_b_baseline_then_pct():
    # Close 12/06: TLDR "thanh khoản cao hơn trung bình 5 phiên (+43%)" while the
    # pinned Tổng kết said +21% — same brief, two TB5 figures. Form 2 ("baseline
    # (±N%)") must also be pinned so TLDR and Tổng kết agree.
    from vnstock_brief import enforce_gtgd_baseline_pct
    # avg5 here gives +21% (18353.2/15168-1≈+21%); prev gives +52%.
    ctx = {"full_day_gtgd": 18353.2,
           "full_day_gtgd_cmp": {"prev": 12074.0, "avg5": 15168.0, "avg20": 17647.0}}
    t = ("🎯 TLDR\nThanh khoản cao hơn trung bình 5 phiên (+43%) nhưng yếu.\n"
         "📊 Tổng kết phiên\nGTGD cả ngày 18,353.2 tỷ (+52% vs phiên trước, "
         "+21% vs TB5 phiên).\n📈 Mức kỹ thuật")
    f = enforce_gtgd_baseline_pct(t, ctx)
    assert "trung bình 5 phiên (+21%)" in f       # TLDR form-2 pinned to avg5
    assert "(+43%)" not in f
    assert "+21% vs TB5 phiên" in f               # Tổng kết stays consistent
    assert "+52% vs phiên trước" in f             # prev correct → unchanged
    assert enforce_gtgd_baseline_pct(f, ctx) == f  # idempotent


def test_enforce_gtgd_baseline_pct_ignores_fx_date_line():
    # Close 16/06 root cause: the tỷ giá line "▼ -0.07% so với 2026-06-15" was
    # matched as a GTGD baseline because the DATE "2026-06-15" contains "20"
    # (→ mis-read as TB20) and "5", overwriting the FX change with GTGD-vs-TB20
    # (-3%). Baseline detection now requires a real GTGD phrase (TB/trung bình/
    # phiên trước), so a date is left alone.
    from vnstock_brief import enforce_gtgd_baseline_pct
    ctx = {"full_day_gtgd": 19252.3,
           "full_day_gtgd_cmp": {"avg5": 19450.0, "avg20": 19848.0, "prev": 25300.0}}
    t = ("📊 Tổng kết phiên\nGTGD 19,252.3 tỷ.\n"
         "- Tỷ giá USD/VND (tham chiếu): 26,174 VND (tính đến 2026-06-16) "
         "▼ -0.07% so với 2026-06-15 (VND mạnh lên)\n")
    f = enforce_gtgd_baseline_pct(t, ctx)
    assert "▼ -0.07% so với 2026-06-15" in f       # FX % untouched (was → -3%)
    assert "-3%" not in f


def test_enforce_composite_rotation_hygiene_fixes_contradiction_and_jargon():
    # 23:44: "Phân phối cảnh báo: CNTT & Phần mềm (tín hiệu tích luỹ mạnh)" —
    # distribution bucket with an accumulation label → drop the contradictory
    # label. And "Net BS +51.7% volume" → Vietnamese.
    from vnstock_brief import enforce_composite_rotation_hygiene
    text = ("- Smart money tích luỹ ngầm: Giáo dục (giá đi ngang, Net BS +51.7% volume), "
            "Hóa chất (Net BS -13.6% volume).\n"
            "- Phân phối cảnh báo: Công nghệ thông tin & Phần mềm (tín hiệu tích luỹ mạnh).")
    f = enforce_composite_rotation_hygiene(text, {})
    # (a) contradiction label dropped from the distribution bucket
    assert "Phân phối cảnh báo: Công nghệ thông tin & Phần mềm" in f
    assert "tín hiệu tích luỹ mạnh" not in f
    # (b) Net BS jargon → Vietnamese, sign → mua/bán
    assert "mua ròng ~51.7% KL" in f
    assert "bán ròng ~13.6% KL" in f
    assert "Net BS" not in f
    # a consistent accumulation label under an accumulation bucket is KEPT
    keep = "- Smart money tích luỹ ngầm: Giáo dục (tín hiệu tích luỹ mạnh)."
    assert enforce_composite_rotation_hygiene(keep, {}) == keep
    assert enforce_composite_rotation_hygiene(f, {}) == f          # idempotent
    # bare "volume" + "1M" window (observed 23:56): "1M" = 1 tháng (lookback),
    # "volume" → KL. (Net BS value with M suffix stays million CP.)
    t2 = "- Phân phối: CNTT & Phần mềm (dòng tiền thoát 1M -8.5% volume)."
    f2 = enforce_composite_rotation_hygiene(t2, {})
    assert "volume" not in f2 and "-8.5% KL" in f2
    assert "1 tháng" in f2 and "1M" not in f2          # window → tháng
    # signed M suffix = million CP (not month); unsigned 3M = window
    t3 = "- Smart money tích luỹ ngầm: Giáo dục (Net BS +6M), CNTT (Net BS -2.5% volume)."
    f3 = enforce_composite_rotation_hygiene(t3, {})
    assert "mua ròng ~6 triệu CP" in f3                 # +6M signed → million CP
    assert "bán ròng ~2.5% KL" in f3                    # -2.5% volume → KL
    assert "Net BS" not in f3


def test_enforce_breadth_label_relabels_above_ma200_as_advancing():
    # Close 12/06: "chỉ 17% mã cổ phiếu tăng giá" — 17% is the above-MA200 stat
    # (A/D 0.85 implies ~46% advancing), so 'tăng giá' is a mislabel → 'trên MA200'.
    from vnstock_brief import enforce_breadth_label
    ctx = {"breadth": {"above_ma200_pct": 17.0, "ad_ratio": 0.85}}
    t = "Độ rộng tiêu cực với chỉ 17% mã cổ phiếu tăng giá và A/D ratio tại 0.85."
    f = enforce_breadth_label(t, ctx)
    assert "17% mã cổ phiếu trên MA200" in f
    assert "tăng giá" not in f
    assert enforce_breadth_label(f, ctx) == f                  # idempotent
    # a different value (not the above-MA200 figure) is left alone
    t2 = "46% mã tăng giá hôm nay."
    assert enforce_breadth_label(t2, ctx) == t2
    # no breadth data → untouched
    assert enforce_breadth_label(t, {}) == t


def test_enforce_sentiment_consistency_pins_mood_and_momentum():
    # Close 16/06: header "📉 Tiêu cực, momentum -33" but body invented
    # "❄️ Sợ hãi, momentum -24" (and -24 ≠ ❄️ Sợ hãi which needs < -50).
    from vnstock_brief import enforce_sentiment_consistency
    ctx = {"market_sentiment": {"mood": "📉 Tiêu cực", "momentum": -33}}
    t = "Tâm lý thị trường: ❄️ Sợ hãi, momentum -24/100, tiêu cực chiếm ưu thế."
    f = enforce_sentiment_consistency(t, ctx)
    assert "📉 Tiêu cực" in f and "❄️ Sợ hãi" not in f
    assert "momentum -33/100" in f and "-24/100" not in f
    assert enforce_sentiment_consistency(f, ctx) == f          # idempotent
    # no sentiment data → untouched
    assert enforce_sentiment_consistency(t, {}) == t


def test_enforce_sentiment_consistency_markdown_and_duplicate_mood():
    # Close 14/07: "Tâm lý: 📉 Tiêu cực **Sợ hãi**, momentum -29/100" — mood
    # word bọc ** không khớp pattern cũ → đuôi "Sợ hãi" bịa sống sót cạnh
    # label đúng. Nay [*_] quanh word được nhận + mood LẶP ngay sau bị nuốt.
    from vnstock_brief import enforce_sentiment_consistency
    ctx = {"market_sentiment": {"mood": "📉 Tiêu cực", "momentum": -29}}
    t = "Tâm lý: 📉 Tiêu cực **Sợ hãi**, momentum -29/100 → xu hướng yếu."
    f = enforce_sentiment_consistency(t, ctx)
    assert "Tâm lý: 📉 Tiêu cực, momentum -29/100" in f
    assert "Sợ hãi" not in f
    assert enforce_sentiment_consistency(f, ctx) == f          # idempotent
    # mood word đơn lẻ bọc markdown cũng bị pin
    t2 = "Tâm lý: **Sợ hãi**, momentum -29/100."
    f2 = enforce_sentiment_consistency(t2, ctx)
    assert "📉 Tiêu cực" in f2 and "Sợ hãi" not in f2


def test_enforce_sentiment_consistency_adjective_paren_form():
    # Close 30/07 01:21: thân brief in "momentum tiêu cực (-51/100)" — tính
    # từ chen giữa "momentum" và số làm pattern ghim trượt, số -51 (trùng VÍ
    # DỤ trong prompt) sống sót. Nay ghim số trong ngoặc, GIỮ tính từ.
    from vnstock_brief import enforce_sentiment_consistency
    ctx = {"market_sentiment": {"mood": "❄️ Sợ hãi", "momentum": -60}}
    t = "GTGD thấp nhưng momentum tiêu cực (-51/100), bias GIẢM."
    f = enforce_sentiment_consistency(t, ctx)
    assert "momentum tiêu cực (-60/100)" in f and "-51" not in f
    assert enforce_sentiment_consistency(f, ctx) == f          # idempotent
    # markdown quanh số ở dạng trực tiếp cũng bị ghim
    t2 = "Tâm lý: ❄️ Sợ hãi, momentum **-51**/100."
    f2 = enforce_sentiment_consistency(t2, ctx)
    assert "momentum -60/100" in f2 and "-51" not in f2
    # dạng "(momentum -29/100)" — ngoặc TRƯỚC momentum — không bị regex mới đụng
    t3 = "tâm lý sợ hãi (momentum -60/100) duy trì."
    assert enforce_sentiment_consistency(t3, ctx) == t3


def test_close_1407_guard_regressions():
    # 4 biến thể trượt guard lộ ra ở close brief 23:46 14/07 — mỗi cái 1 fix.
    import vnstock_brief as vb

    # (1) "bias **GIẢM** bắt buộc" — markdown quanh hướng làm guard 14 trượt
    f = vb.enforce_no_bias_directive_leak(
        "momentum tiêu cực (-29/100), bias **GIẢM** bắt buộc.", {})
    assert "bắt buộc" not in f and "**GIẢM**" in f

    # (2) "tâm lý sợ hãi (momentum -29/100)" không dấu ':' → pin mood word;
    #     dedup momentum không được để lại ngoặc rỗng "()"
    ctx = {"market_sentiment": {"mood": "📉 Tiêu cực", "momentum": -29}}
    t = ("Độ rộng tiêu cực (A/D=1.26), tâm lý sợ hãi (momentum -29/100). "
         "Tâm lý: 📉 Tiêu cực, momentum -29/100 → xu hướng yếu.")
    s = vb.enforce_no_duplicate_momentum(
        vb.enforce_sentiment_consistency(t, ctx), ctx)
    assert "tâm lý tiêu cực" in s and "sợ hãi" not in s
    assert "()" not in s and "momentum -29/100" in s
    # văn tường thuật quá khứ (không có ngoặc momentum) KHÔNG bị đụng
    past = "tâm lý hưng phấn đã biến mất từ tháng trước."
    assert vb.enforce_sentiment_consistency(past, ctx) == past

    # (3) số ngành khác gắn nhầm + dấu '+': "Ngân hàng bị bán ròng +1,471 tỷ"
    #     (thật -1,032); pass của ngành đứng trước không được với qua câu sau
    ctx3 = {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1032.0},
                        {"Ngành": "Họ VIN", "NN 1T (tỷ)": 1471.0}]}
    t3 = ("Khối ngoại mua ròng mạnh nhất: Họ VIN +1,471 tỷ. "
          "Ngân hàng bị bán ròng +1,471 tỷ (GTGD 4,072 tỷ).")
    f3 = vb.enforce_sector_nn_figures(t3, ctx3)
    assert "Ngân hàng bị bán ròng -1,032 tỷ" in f3
    assert "Họ VIN +1,471 tỷ" in f3                       # số đúng giữ nguyên
    assert vb.enforce_sector_nn_figures(f3, ctx3) == f3   # idempotent

    # (4) % so phiên trước sai số học dù model TỰ ghi cả 2 vế — ctx thiếu
    #     full_day_gtgd/cmp → Form 3 tự-chứa tính từ chính 2 operand
    t4 = ("## 📊 Tổng kết phiên\nthanh khoản cả ngày giảm 29% so phiên trước "
          "(15,513.6 tỷ vs 19,751.0 tỷ).\n")
    f4 = vb.enforce_compare_direction(vb.enforce_gtgd_baseline_pct(t4, {}), {})
    assert "giảm 21% so phiên trước" in f4 and "29%" not in f4
    # ctx đầy đủ → Form 1 (nguồn chân lý) vẫn thắng như cũ
    ctx4 = {"full_day_gtgd": 15513.6,
            "full_day_gtgd_cmp": {"prev": 19751.0, "avg5": 16800.0}}
    assert "-21% so phiên trước" in vb.enforce_gtgd_baseline_pct(t4, ctx4)


def test_close_1407_2358_review_fixes():
    # 3 cụm lỗi qua vòng review phản biện chéo của close 23:58 14/07.
    import vnstock_brief as vb

    # (1) NN theo ngành (khung 1 TUẦN) nêu không nhãn cạnh NN 1 NGÀY toàn thị
    #     trường trong "Tổng kết phiên" → gắn "(1 tuần)"
    ctx = {"sectors": [{"Ngành": "Ngân hàng", "NN 1T (tỷ)": -1032.0},
                       {"Ngành": "Họ VIN", "NN 1T (tỷ)": 1471.0}]}
    t = ("Khối ngoại bán ròng 159 tỷ, NN ròng ngành Ngân hàng -1,032 tỷ.\n"
         "NN mua ròng mạnh nhất (1 tuần): Họ VIN +1,471 tỷ.\n")
    f = vb.enforce_nn_frame_labels(t, ctx)
    assert "Ngân hàng -1,032 tỷ (1 tuần)" in f
    assert "159 tỷ (1 tuần)" not in f                 # số 1D không bị gắn nhầm
    assert f.count("Họ VIN +1,471 tỷ (1 tuần)") == 0  # dòng đã có nhãn → giữ
    assert vb.enforce_nn_frame_labels(f, ctx) == f    # idempotent
    # GTGD không phải NN → không đụng
    t_g = "Ngân hàng GTGD 4,072 tỷ."
    assert vb.enforce_nn_frame_labels(t_g, ctx) == t_g

    # (2) A/D 1 phiên DƯƠNG (1.26) mà gọi "độ rộng tiêu cực" → "trái chiều";
    #     A/D thấp thật thì "tiêu cực" giữ nguyên
    ctx2 = {"breadth": {"above_ma200_pct": 13, "ad_ratio": 1.26},
            "market_sentiment": {"momentum": -29}}
    t2 = "Độ rộng tiêu cực (A/D=1.26, 13% trên MA200), tâm lý tiêu cực."
    f2 = vb.enforce_breadth_quality(t2, ctx2)
    assert "Độ rộng trái chiều" in f2
    assert "tâm lý tiêu cực" in f2                    # chỉ mệnh đề độ rộng bị sửa
    assert vb.enforce_breadth_quality(f2, ctx2) == f2
    low_ad = {"breadth": {"above_ma200_pct": 13, "ad_ratio": 0.7},
              "market_sentiment": {"momentum": -29}}
    assert vb.enforce_breadth_quality(t2, low_ad) == t2

    # (3) sector có contrib/weight hàm ý %đổi tuần vượt trần sàn (Họ VIN
    #     -0.873pp / 1.6% ⇒ -55%/tuần = data hỏng) → loại khỏi lead/lag
    items = vb._leadlag_candidates({
        "Họ VIN": {"_weight": 0.016, "_1d_contrib": -0.873},
        "Ngân hàng": {"_weight": 0.25, "_1d_contrib": -0.35},
        "Dầu khí": {"_weight": 0.042, "_1d_contrib": 0.06}})
    assert min(items, key=lambda x: x[1])[0] == "Ngân hàng"
    assert all(n != "Họ VIN" for n, _ in items)
    # sector bình thường (kể cả biến động lớn hợp lệ) không bị loại
    ok = vb._leadlag_candidates({"Thép": {"_weight": 0.05, "_1d_contrib": -1.2}})
    assert ok == [("Thép", -1.2)]                     # hàm ý -24%/tuần, hợp lệ

    # (4) "%VNI" của lead/lag bịa (chẩn đoán data 14/07: kho ĐỦ 4 mã, trọng
    #     số thật ~25% — model mượn GTGD 1,653 tỷ mangle thành "1.6%VNI")
    #     → pin về ctx sector_weights; số đúng giữ nguyên
    ctx4 = {"lead_sector": {"name": "Dầu khí", "contrib": 0.06},
            "lag_sector": {"name": "Họ VIN", "contrib": -0.873},
            "sector_weights": {
                "Họ VIN": {"_weight": 0.251, "_1d_contrib": -0.873},
                "Dầu khí": {"_weight": 0.042, "_1d_contrib": 0.06}}}
    t4 = ("**Dẫn dắt:** Dầu khí [4.2%VNI, đóng góp +0.060pp (1 tuần)]\n"
          "**Tụt hậu:** Họ VIN [1.6%VNI, đóng góp -0.873pp (1 tuần)]")
    f4 = vb.enforce_lead_lag(t4, ctx4)
    assert "Họ VIN [25.1%VNI" in f4
    assert "Dầu khí [4.2%VNI" in f4                   # trọng số đúng giữ nguyên
    assert vb.enforce_lead_lag(f4, ctx4) == f4        # idempotent


def test_allocation_prose_pct_pinned_to_band_table():
    # Brief phân bổ ĐẦU TIÊN trên máy user (15/07): TLDR bịa "Giảm tỷ trọng
    # cổ phiếu xuống 10% (từ 15%), duy trì tiền gửi 45%" — 10%/45% không
    # thuộc band nào (nguyên tắc #1: LLM không sinh số %). Pass (d) của
    # enforce_allocation_table pin % gắn tên lớp về bảng band.
    import vnstock_brief as vb
    ctx = {"allocation": {"band": "B4", "band_label": "căng thẳng",
                          "score": -0.36, "as_of": "2026-07-14",
                          "allocation": {"Cổ phiếu": 15, "Trái phiếu": 25,
                                         "Tiền gửi": 40, "Vàng": 12, "USD": 8}}}
    t = ("## 🎯 TLDR\n"
         "**Hành động:** Giảm tỷ trọng cổ phiếu xuống 10% (từ 15%), "
         "duy trì vàng 12% và tiền gửi 45%.\n"
         "## 🧭 Phân bổ đề xuất\n"
         "- Cổ phiếu: 15%\n- Tiền gửi: 40%\n"
         "- Band: B4 (căng thẳng) — điểm -0.36, phiên 2026-07-14\n")
    f = vb.enforce_allocation_table(t, ctx)
    assert "cổ phiếu xuống 15%" in f and "10%" not in f
    assert "tiền gửi 40%" in f and "45%" not in f
    assert "vàng 12%" in f                              # số đúng giữ nguyên
    assert vb.enforce_allocation_table(f, ctx) == f     # idempotent
    # brief NGÀY (không có mục "Phân bổ đề xuất") → không đụng chữ "cổ phiếu…%"
    daily = "Chỉ 13% mã cổ phiếu trên MA200. Cổ phiếu ngân hàng chiếm 30% thanh khoản."
    assert vb.enforce_allocation_table(daily, ctx) == daily


def test_close_1507_0110_fixes():
    # Close 01:10 15/07: 2 lỗi lộ sau khi loạt fix đêm trước đã ăn.
    import vnstock_brief as vb
    ctx = {"macro": [
        {"key": "usdvnd", "label": "Tỷ giá USD/VND (tham chiếu)", "unit": "VND",
         "kind": "fx", "value": 26190.0, "as_of": "2026-07-14",
         "prev_value": 26271.0, "prev_as_of": "2026-07-13",
         # change THẬT (−0.31%) — đổi làm tròn về 0 nay bị fmt_change nén
         # thành "không đổi" (fix 17/07) → row rơi vào dòng gộp "Đi ngang"
         "change": {"delta": -81.0, "pct": -0.31, "dir": -1}, "source": "x"}]}

    # (1) enforce_macro anchor 2 nấc: dòng văn xuôi "Rủi ro vĩ mô: lãi suất…"
    #     KHÔNG được hijack body canonical khi section 🌐 thật tồn tại
    #     (bug 01:10: khối vĩ mô splice vào mục Rủi ro, nuốt dòng D/E,
    #     section 🌐 thật thì không được canonical-hóa)
    t = ("## ⚠️ Rủi ro cần lưu ý\n"
         "Rủi ro vĩ mô: lãi suất liên ngân hàng giảm mạnh có thể đảo chiều.\n"
         "Đòn bẩy cao nhất: HNG D/E=8.83.\n"
         "## 🌐 Vĩ mô: lãi suất & tỷ giá\n"
         "Tỷ giá USD/VND hiện tại là 26,190 VND.\n"
         "## 📰 Tin\n- x\n")
    f = vb.enforce_macro(t, ctx)
    assert "Đòn bẩy cao nhất: HNG D/E=8.83." in f      # mục Rủi ro nguyên vẹn
    assert f.index("Tỷ giá USD/VND (tham chiếu): 26,190") > f.index("## 🌐")
    assert vb.enforce_macro(f, ctx) == f               # idempotent
    # không có section thật (header bị reformat) → nấc lỏng vẫn bắt (fix 16/06)
    t_loose = "🌐 Vĩ mô: lãi suất & tỷ giá\n- Tỷ giá khoảng 24,000\n## 📰 Tin\n- x\n"
    assert "26,190" in vb.enforce_macro(t_loose, ctx)

    # (2) nhãn khung NN dạng SỐ-TRƯỚC-TÊN: "NN mua ròng 1,471 tỷ trong ngành
    #     Họ VIN" → gắn "(1 tuần)" (pattern tên-trước của guard cũ trượt)
    ctx2 = {"sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": 1471.0},
                        {"Ngành": "Dầu khí", "NN 1T (tỷ)": 271.0}]}
    t2 = "NN mua ròng 1,471 tỷ trong ngành Họ VIN và 271 tỷ trong ngành Dầu khí."
    f2 = vb.enforce_nn_frame_labels(t2, ctx2)
    assert "ngành Họ VIN (1 tuần)" in f2
    assert vb.enforce_nn_frame_labels(f2, ctx2) == f2  # idempotent

    # (3) template "Đề xuất bổ sung": CPI/Fed nay ĐÃ CÓ — không còn nằm trong
    #     ví dụ "thứ thực sự thiếu" (model từng chép nguyên ví dụ để xin CPI)
    from vnstock_brief import _MORNING_TEMPLATE, _AFTERNOON_TEMPLATE
    for tpl in (_MORNING_TEMPLATE, _AFTERNOON_TEMPLATE):
        assert "vd: giá dầu Brent/WTI" in tpl
        assert "vd: CPI/lạm phát" not in tpl
        assert "CPI/lạm phát, IIP, PMI, GDP" in tpl    # đã vào danh sách ĐÃ CÓ

    # (4) close 01:20: so cả-ngày với baseline SÁNG nhưng KHÔNG có chữ "so"
    #     + baseline dạng "trung bình 5 phiên sáng" (chữ "sáng" đứng cuối) →
    #     _MORNING_CMP_RE nới; "57% GTGD (…)" đứng trước phải được GIỮ NGUYÊN
    ctx4 = {"full_day_gtgd": 15513.6,
            "full_day_gtgd_cmp": {"prev": 19751.0, "avg5": 16800.0,
                                  "avg20": 16900.0}}
    t4 = ("## 📊 Tổng kết phiên\n"
          "Phiên chiều chiếm 57% GTGD (15,513.6 tỷ), cao hơn 35% phiên trước "
          "(10,294.2 tỷ) và 23% trung bình 5 phiên sáng. Độ rộng trái chiều.\n")
    f4 = vb.enforce_gtgd_compare_frame(t4, ctx4)
    assert "57% GTGD (15,513.6 tỷ)" in f4              # số đứng trước giữ nguyên
    assert "TB5 phiên (-8%)" in f4 and "phiên sáng" not in f4
    assert "10,294.2" not in f4                        # baseline sáng bị thay
    assert vb.enforce_gtgd_compare_frame(f4, ctx4) == f4   # idempotent
    # so cả-ngày-vs-cả-ngày đúng khung → không đụng
    ok4 = ("## 📊 Tổng kết phiên\n"
           "GTGD 15,513.6 tỷ, thấp hơn TB5 phiên (-8%) và TB20 phiên (-8%).\n")
    assert vb.enforce_gtgd_compare_frame(ok4, ctx4) == ok4

    # (5) close 01:26: Form 4 — "±N% <baseline>" (% CÓ DẤU đứng trước
    #     baseline, không "so"): "(-21% phiên trước, +2% TB5 phiên)" — vế
    #     prev đúng giữ nguyên, +2% pin về TB5 thật; verb + magnitude
    #     KHÔNG dấu ("thấp hơn 21% phiên trước") không bị đụng
    ctx5 = {"full_day_gtgd": 15513.6,
            "full_day_gtgd_cmp": {"prev": 19751.0, "avg5": 16862.0}}
    t5 = ("## 📊 Tổng kết phiên\n"
          "GTGD cả ngày 15,513.6 tỷ (-21% phiên trước, +2% TB5 phiên).\n")
    f5 = vb.enforce_gtgd_baseline_pct(t5, ctx5)
    assert "-21% phiên trước" in f5 and "-8% TB5 phiên" in f5
    assert "+2%" not in f5
    assert vb.enforce_gtgd_baseline_pct(f5, ctx5) == f5    # idempotent
    verb = "## 📊 Tổng kết phiên\nthanh khoản thấp hơn 21% phiên trước.\n"
    assert vb.enforce_gtgd_baseline_pct(verb, ctx5) == verb
    ma = "## 📊 Tổng kết phiên\ntrên MA200=1,769.66 (+2.1%).\n"
    assert vb.enforce_gtgd_baseline_pct(ma, ctx5) == ma


def test_enforce_session_direction_pins_qualitative_label():
    # Close 23:58 14/07: "VNINDEX đóng cửa +0.34% … — phiên GIẢM điểm nhẹ sau
    # phiên tăng mạnh trước đó" — close dương mà gọi phiên giảm; guard % không
    # đụng nhãn CHỮ. Pin theo dấu day_change_pct, chừa phiên KHÁC/tương lai.
    from vnstock_brief import enforce_session_direction
    ctx = {"vnindex_tech": {"day_change_pct": 0.34}}
    t = ("**Kết quả phiên:** VNINDEX đóng cửa +0.34% (1,806.63) — phiên giảm "
         "điểm nhẹ sau phiên tăng mạnh trước đó.")
    f = enforce_session_direction(t, ctx)
    assert "phiên tăng điểm nhẹ" in f
    assert "sau phiên tăng mạnh trước đó" in f          # phiên TRƯỚC giữ nguyên
    assert enforce_session_direction(f, ctx) == f        # idempotent
    # close âm mà gọi phiên tăng → lật
    f2 = enforce_session_direction(
        "VNINDEX đóng cửa -0.80%, một phiên tăng điểm ấn tượng.",
        {"vnindex_tech": {"day_change_pct": -0.8}})
    assert "phiên giảm điểm" in f2
    # không đụng: kịch bản tương lai, dòng không neo "đóng cửa", nhãn đã đúng
    fut = "Kịch bản: nếu phiên tăng tiếp theo xuất hiện thì đảo chiều."
    assert enforce_session_direction(fut, ctx) == fut
    noanchor = "Thị trường hồi phục sau phiên giảm hôm qua."
    assert enforce_session_direction(noanchor, ctx) == noanchor
    ok = "VNINDEX đóng cửa -0.5%, phiên giảm thứ ba liên tiếp."
    assert enforce_session_direction(ok, {"vnindex_tech": {"day_change_pct": -0.5}}) == ok
    assert enforce_session_direction(t, {}) == t         # thiếu data → no-op


def test_enforce_breadth_quality_softens_positive_claim_when_weak():
    # Close 16/06: "Độ rộng ... tích cực ... 18% trên MA200" — 18% above MA200 is
    # structurally weak; under a bearish tape that's mixed, not 'tích cực'.
    from vnstock_brief import enforce_breadth_quality
    ctx = {"breadth": {"above_ma200_pct": 18}, "market_sentiment": {"momentum": -33}}
    t = "Độ rộng thị trường hiện tại tích cực với A/D ratio là 1.33, và 18% trên MA200."
    f = enforce_breadth_quality(t, ctx)
    assert "trái chiều" in f and "hiện tại tích cực" not in f
    assert enforce_breadth_quality(f, ctx) == f                # idempotent
    # broad + non-bearish market → left alone
    healthy = {"breadth": {"above_ma200_pct": 62}, "market_sentiment": {"momentum": 15}}
    assert enforce_breadth_quality(t, healthy) == t
    assert enforce_breadth_quality(t, {}) == t                 # no breadth data


def test_enforce_vnindex_change_pins_day_change_pct():
    # Close 16/06: "tăng -24% so với phiên trước" — -24 is the momentum leaking in;
    # the real day change is +0.31% (and "tăng -24%" is self-contradictory).
    from vnstock_brief import enforce_vnindex_change
    ctx = {"vnindex_tech": {"day_change_pct": 0.31}}
    t = "VNINDEX đóng cửa 1,804.97, tăng -24% so với phiên trước. Độ rộng yếu."
    f = enforce_vnindex_change(t, ctx)
    assert "tăng 0.31% so với phiên trước" in f and "-24%" not in f
    assert enforce_vnindex_change(f, ctx) == f                 # idempotent
    # negative day → 'giảm', positive-signed % corrected
    ctx2 = {"vnindex_tech": {"day_change_pct": -1.5}}
    assert "giảm 1.50% so với hôm qua" in enforce_vnindex_change(
        "VNINDEX giảm +0.31% so với hôm qua.", ctx2)
    # does NOT touch sector pp / weekly moves, and no-op without data
    assert enforce_vnindex_change("Ngân hàng +0.537pp (1 tuần).", ctx) == \
        "Ngân hàng +0.537pp (1 tuần)."
    assert enforce_vnindex_change(t, {}) == t


def test_enforce_change_verb_sign_flips_contradiction():
    # Close 16/06: "GTGD ... tăng -1% so với TB5" — verb 'tăng' contradicts the
    # negative %; the number's sign wins → 'giảm 1%'.
    from vnstock_brief import enforce_change_verb_sign
    f = enforce_change_verb_sign("GTGD 19,252.3 tỷ, tăng -1% so với TB5 phiên.", {})
    assert "giảm 1% so với TB5" in f and "tăng -1%" not in f
    assert "tăng 5%" in enforce_change_verb_sign("giảm +5% so với TB20", {})  # other way
    assert enforce_change_verb_sign(f, {}) == f                  # idempotent
    # consistent pairs left alone
    assert enforce_change_verb_sign("tăng 0.31% so với phiên trước", {}) == \
        "tăng 0.31% so với phiên trước"
    assert enforce_change_verb_sign("tăng +2% hôm nay", {}) == "tăng +2% hôm nay"


def test_enforce_compare_direction_form_b_compares_baseline_value():
    # Morning 12/06: "Phiên sáng 8,397.0 tỷ, cao hơn 60% ... (5,233.3 tỷ) nhưng
    # thấp hơn 11% TB sáng (7,549.1 tỷ)" — 8,397 > 7,549 so it's HIGHER, not
    # 'thấp hơn'. Bare % (no sign) → compare subject vs parenthetical baseline.
    from vnstock_brief import enforce_compare_direction
    t = ("Phiên sáng giao dịch 8,397.0 tỷ, cao hơn 60% phiên sáng trước "
         "(5,233.3 tỷ) nhưng thấp hơn 11% trung bình 5 phiên sáng (7,549.1 tỷ).")
    f = enforce_compare_direction(t, {})
    assert "cao hơn 11% trung bình 5 phiên sáng (7,549.1 tỷ)" in f   # flipped
    assert "thấp hơn 11%" not in f
    assert "cao hơn 60% phiên sáng trước (5,233.3 tỷ)" in f          # was right, kept
    assert enforce_compare_direction(f, {}) == f                     # idempotent
    # genuinely lower (subject < baseline) keeps 'thấp hơn'
    ok = "GTGD 5,000.0 tỷ, thấp hơn 30% TB sáng (7,100.0 tỷ)."
    assert enforce_compare_direction(ok, {}) == ok
    # bare 'thấp' (no 'hơn') is also handled (observed 23:56: "thấp 11%")
    t2 = "GTGD sáng 8,397.0 tỷ, thấp 11% so TB 5 phiên (7,549.1 tỷ)."
    f2 = enforce_compare_direction(t2, {})
    assert "cao hơn 11% so TB 5 phiên (7,549.1 tỷ)" in f2
    assert "thấp 11%" not in f2
    # a standalone adjective (no % after the word) is NOT touched
    safe = "Thanh khoản cao, ngành Ngân hàng (5,067 tỷ) dẫn đầu."
    assert enforce_compare_direction(safe, {}) == safe


def test_enforce_lead_lag_pins_lead_sector_pp_anywhere():
    # Morning 12/06 TLDR: "giảm tỷ trọng nhóm Bất động sản (đóng góp -0.504pp
    # tuần)" — fabricated (borrowed the -504 tỷ NN figure); BĐS is the +0.464pp
    # leader. Pin any lead/lag pp mention to the canonical value.
    from vnstock_brief import enforce_lead_lag
    ctx = {"lead_sector": {"name": "Bất động sản", "contrib": 0.464},
           "lag_sector": {"name": "Bán lẻ & Thương mại", "contrib": -0.067}}
    text = ("🎯 TLDR\nDEFENSIVE — giảm tỷ trọng nhóm Bất động sản (đóng góp -0.504pp tuần).\n"
            "## 🎯 Trọng tâm theo dõi\n"
            "**Tích luỹ/Mua:** Bất động sản (đóng góp +0.464pp, 1 tuần — mạnh nhất).\n"
            "**Tránh/Bán:** Bán lẻ & Thương mại (đóng góp -0.067pp, 1 tuần — yếu nhất).\n"
            "## ⚡ Biến động")
    f = enforce_lead_lag(text, ctx)
    assert "Bất động sản (đóng góp +0.464pp tuần)" in f      # TLDR pp pinned
    assert "-0.504pp" not in f
    # the already-correct Trọng tâm lines are untouched
    assert "**Tích luỹ/Mua:** Bất động sản (đóng góp +0.464pp, 1 tuần — mạnh nhất)." in f
    assert "**Tránh/Bán:** Bán lẻ & Thương mại (đóng góp -0.067pp, 1 tuần — yếu nhất)." in f
    assert enforce_lead_lag(f, ctx) == f                     # idempotent


def test_enforce_scenario_levels_pins_fabricated_and_keeps_real():
    # Morning 14:28: "đóng cửa trên 1,801.99 (đáy phiên), test R1=1,822.95" —
    # 1,801.99 matches no real level and "đáy phiên" above the close is
    # impossible. Pin it to the nearest real level and drop the bad label;
    # leave pivots, close, MAs and round/approx targets alone.
    from vnstock_brief import enforce_scenario_levels
    ctx = {"vnindex_tech": {"close": 1798.61, "ma20": 1858.39, "ma50": 1830.77,
                            "ma200": 1749.10, "support_1": 1789.31, "support_2": 1758.96,
                            "resistance_1": 1822.95, "resistance_2": 1846.19,
                            "week_high": 1860.0, "week_low": 1790.0}}
    text = ("🔮 Kịch bản phiên chiều\n"
            "Chính: thủng S1=1,789.31 → về S2=1,758.96, đóng cửa dưới 1,790.\n"
            "Phụ: giữ trên S1=1,789.31 → đóng cửa trên 1,801.99 (đáy phiên), test R1=1,822.95.\n"
            "MA20=1,858.39.")
    f = enforce_scenario_levels(text, ctx)
    assert "1,801.99" not in f                      # fabricated level pinned away
    assert "(đáy phiên)" not in f                    # contradictory label dropped
    assert "S1=1,789.31" in f and "S2=1,758.96" in f # pivots untouched
    assert "R1=1,822.95" in f                        # pivot untouched
    assert "đóng cửa dưới 1,790." in f               # round target untouched
    assert "MA20=1,858.39" in f                      # MA untouched
    assert enforce_scenario_levels(f, ctx) == f      # idempotent
    # no ctx levels → untouched
    assert enforce_scenario_levels(text, {}) == text


def test_enforce_sector_nn_figures_fixes_fabricated_flow_outside_money_section():
    # Morning 14:11: the "Tránh/Bán" line carried "Thép & Kim loại (đóng góp
    # -0.03pp, 1 tuần, NN bán ròng -1,372 tỷ)" — fabricated, and contradicting
    # "Ngân hàng -703 tỷ mạnh nhất". Pin it to Thép's real ctx NN; don't touch
    # the pp value or correct figures.
    from vnstock_brief import enforce_sector_nn_figures
    ctx = {"sectors": [
        {"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": -180.0},
        {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}
    text = ("**Tránh/Bán:** Bán lẻ & Thương mại (-0.064pp) + Thép & Kim loại "
            "(đóng góp -0.03pp, 1 tuần, NN bán ròng -1,372 tỷ).\n"
            "**Dòng tiền ngành:** NN bán ròng mạnh nhất: Ngân hàng -703 tỷ.")
    f = enforce_sector_nn_figures(text, ctx)
    assert "NN bán ròng -180 tỷ" in f
    assert "-1,372" not in f
    assert "-0.03pp" in f                              # pp value untouched
    assert "Ngân hàng -703 tỷ" in f                    # correct figure untouched
    assert enforce_sector_nn_figures(f, ctx) == f      # idempotent


def test_enforce_number_format_normalizes_vn_to_en():
    # Morning 13:54 mixed VN format (1.798,61 / 9.129,4 / 1.858,39 / -3,2% /
    # 5.038 tỷ) with EN (5,233.3 / 1,789.31). Normalise the VN tokens to EN; leave
    # EN numbers, pp 3-decimals, ratios and dates alone.
    from vnstock_brief import enforce_number_format
    t = ("Đóng cửa 1.798,61. GTGD sáng 5,233.3 tỷ (-43% so 9.129,4 tỷ). "
         "MA20=1.858,39 (dưới -3,2%). S1=1,789.31. NN Ngân hàng (GTGD 5.038 tỷ). "
         "BĐS đóng góp +0.275pp. A/D 0.87. GDKHQ 2026-06-15. Cổ tức 13.0%.")
    f = enforce_number_format(t, {})
    assert "1,798.61" in f and "1.798,61" not in f      # VN thousands+decimal → EN
    assert "9,129.4" in f and "9.129,4" not in f
    assert "1,858.39" in f and "1.858,39" not in f
    assert "-3.2%" in f and "-3,2%" not in f            # VN percentage → EN
    assert "5,038 tỷ" in f and "5.038 tỷ" not in f      # VN thousands+tỷ → EN
    assert "5,233.3 tỷ" in f                            # EN GTGD untouched
    assert "S1=1,789.31" in f                           # EN pivot untouched
    assert "+0.275pp" in f                              # 3-decimal pp untouched
    assert "A/D 0.87" in f                              # ratio untouched
    assert "2026-06-15" in f                            # ISO date untouched
    assert "13.0%" in f                                 # EN percent untouched
    assert enforce_number_format(f, {}) == f            # idempotent


def test_enforce_lead_lag_fixes_morning_swap_keeps_close():
    # 13:40 morning: "Tích luỹ/Mua: Chưa có nhóm dẫn dắt" (denied the leader) and
    # "Tránh/Bán: Bất động sản (-0.03pp)" (put the LEAD sector on the avoid line)
    # while BĐS is the deterministic lead (+0.275pp). Both lines must be pinned.
    from vnstock_brief import enforce_lead_lag
    ctx = {"lead_sector": {"name": "Bất động sản", "contrib": 0.275},
           "lag_sector": {"name": "Bán lẻ & Thương mại", "contrib": -0.064}}
    morning = ("## 🎯 Trọng tâm theo dõi\n"
               "**Tích luỹ/Mua:** Chưa có nhóm dẫn dắt rõ ràng (+0.00pp).\n"
               "**Tránh/Bán:** **Bất động sản** (đóng góp -0.03pp, NN bán ròng -307 tỷ) — phân phối mạnh.\n"
               "## ⚡ Biến động bất thường")
    f = enforce_lead_lag(morning, ctx)
    assert "**Tích luỹ/Mua:** Bất động sản (đóng góp +0.275pp, 1 tuần — mạnh nhất)." in f
    assert "**Tránh/Bán:** Bán lẻ & Thương mại (đóng góp -0.064pp, 1 tuần — yếu nhất)." in f
    assert "Chưa có nhóm dẫn dắt" not in f
    assert "-0.03pp" not in f
    assert enforce_lead_lag(f, ctx) == f                       # idempotent
    # close: already matches the deterministic lead/lag → untouched
    close = ("## 🏆 Dẫn dắt & Tụt hậu\n"
             "**Dẫn dắt:** Bất động sản (đóng góp +0.275pp, 1 tuần).\n"
             "**Tụt hậu:** Bán lẻ & Thương mại (đóng góp -0.064pp, 1 tuần).\n"
             "## 💰 Dòng tiền")
    assert enforce_lead_lag(close, ctx) == close
    # no lead/lag data → untouched
    assert enforce_lead_lag(morning, {}) == morning


def test_apply_brief_guards_is_the_single_shared_chain():
    # generate_brief must route every agent's output through apply_brief_guards
    # so morning & close share the IDENTICAL guard sequence.
    import inspect, vnstock_brief
    src = inspect.getsource(vnstock_brief.generate_brief)
    assert "apply_brief_guards(" in src
    # idempotent end to end
    t = ("## 🎯 TLDR\n**Bias:** GIẢM — thị trường yếu.\n"
         "## 📊 Tổng quan phiên sáng\nGTGD sáng 5,200 tỷ.")
    once = vnstock_brief.apply_brief_guards(t, {})
    assert vnstock_brief.apply_brief_guards(once, {}) == once


def test_morning_brief_gets_all_session_guards_end_to_end():
    # PARITY: a MORNING brief carrying every bug pattern guarded this session must
    # come out clean after the shared apply_brief_guards chain — proving the
    # fixes are integrated for morning, not just close.
    from vnstock_brief import apply_brief_guards
    ctx = {
        "sectors": [
            {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0, "GTGD TB (tỷ)": 4100.0},
            {"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": -180.0, "GTGD TB (tỷ)": 1500.0},
            {"Ngành": "Thực phẩm & Đồ uống", "NN 1T (tỷ)": 136.0, "GTGD TB (tỷ)": 900.0},
        ],
        "market_sentiment": {"signals": [{"name": "NN ròng 1D", "value": "-665 tỷ"}]},
        "bias_floor": {"dir": "GIẢM", "momentum": -61, "regime_score": -4},
        "lead_sector": {"name": "Bất động sản", "contrib": 0.275},
        "lag_sector": {"name": "Bán lẻ & Thương mại", "contrib": -0.064},
    }
    morning = (
        "## 🎯 TLDR\n"
        "**Bias:** GIẢM bắt buộc — thị trường yếu.\n"            # bắt buộc leak
        "## 📊 Tổng quan phiên sáng\n"
        "GTGD sáng thấp kỷ lục (5,200 tỷ), độ rộng tiêu cực, momentum -61/100. "  # kỷ lục + dup momentum
        "Tâm lý ❄️ Sợ hãi, momentum -61/100 → yếu.\n"
        "## 🎯 Trọng tâm theo dõi\n"
        "**Tích luỹ/Mua:** Chưa có nhóm dẫn dắt rõ ràng (+0.00pp).\n"             # denied real leader
        "**Tránh/Bán:** Bất động sản (đóng góp -0.03pp) — phân phối mạnh.\n"      # lead sector on avoid line
        "**Dòng tiền ngành:** Khối ngoại bán ròng mạnh 665 tỷ tuần này (1D: -665 tỷ). "  # 1D tagged weekly
        "Smart money phân phối tại Thép & Kim loại (NN -1,372 tỷ). "                      # fabricated paren NN
        "Thanh khoản tập trung Ngân hàng (-703 tỷ).\n"                                    # NN as thanh khoản
        "## ⚡ Biến động bất thường\nPhẳng."
    )
    fixed = apply_brief_guards(morning, ctx)
    # 1) bắt buộc directive leak stripped, direction kept
    assert "bắt buộc" not in fixed.lower()
    assert "**Bias:** GIẢM —" in fixed
    # 2) all-time superlative on the morning GTGD line dropped
    assert "kỷ lục" not in fixed
    assert "GTGD sáng thấp (5,200 tỷ)" in fixed
    # 3) the same-line duplicate momentum collapsed (kept the tâm-lý one)
    assert fixed.count("momentum -61/100") == 1
    assert "Sợ hãi, momentum -61/100 → yếu" in fixed
    # 4) the 1D foreign total no longer tagged weekly
    assert "665 tỷ tuần này" not in fixed
    assert "(1D: -665 tỷ)" in fixed
    # 5) fabricated paren NN corrected to the true value (Thép is -180, not -1,372)
    assert "-1,372" not in fixed
    assert "Thép & Kim loại (NN -180 tỷ)" in fixed
    # 6) NN-sell figure no longer mislabeled as thanh khoản (negative gone / GTGD used)
    assert "Ngân hàng (-703 tỷ)" not in fixed
    assert "Thanh khoản cao nhất (GTGD TB 1 tuần): Ngân hàng 4,100 tỷ" in fixed
    # 7) lead/lag pinned: BĐS is the leader (not "chưa có", not on the avoid line)
    assert "**Tích luỹ/Mua:** Bất động sản (đóng góp +0.275pp, 1 tuần — mạnh nhất)." in fixed
    assert "**Tránh/Bán:** Bán lẻ & Thương mại (đóng góp -0.064pp, 1 tuần — yếu nhất)." in fixed
    # idempotent
    assert apply_brief_guards(fixed, ctx) == fixed


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


def test_enforce_risk_numbers_metric_by_sentence_not_next_clause():
    # 10:53: "HNG có D/E cao nhất 8.83, tiếp theo là PET và VTZ. KBC có lưu
    # chuyển tiền HĐKD thấp nhất …" — PET/VTZ belong to the D/E sentence but the
    # old "nearest keyword after" logic grabbed KBC's OCF clause. The append must
    # give PET/VTZ their D/E, KBC its Op.CF.
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "ocf": 915.0}, "PET": {"de": 2.67, "ocf": -1389.0},
        "VTZ": {"de": 2.63, "ocf": -318.0}, "KBC": {"de": 1.12, "ocf": -17344.0},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "HNG có D/E cao nhất với 8.83, tiếp theo là PET và VTZ. KBC có lưu "
            "chuyển tiền HĐKD thấp nhất với -17,344 tỷ.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "PET D/E=2.67" in fixed and "VTZ D/E=2.63" in fixed
    assert "PET Op.CF" not in fixed and "VTZ Op.CF" not in fixed


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


def test_enforce_risk_numbers_keeps_list_separators_on_correct_values():
    # 11:43: the canonical "HNG D/E=8.83, PET D/E=2.67, VTZ D/E=2.63" came out as
    # "HNG D/E=8.83 PET D/E=2.67 VTZ..." — the value regex grabbed the trailing
    # list comma ("8.83,"), mis-parsed it as 883, and "corrected" it, dropping
    # the comma. Correct values (with separators) must pass through untouched.
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "ocf": 915.0}, "PET": {"de": 2.67, "ocf": -1389.0},
        "VTZ": {"de": 2.63, "ocf": -318.0}, "KBC": {"de": 1.12, "ocf": -17344.0}}}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "Đòn bẩy cao nhất: HNG D/E=8.83, PET D/E=2.67, VTZ D/E=2.63 — HNG cao nhất.\n"
            "Op.CF thấp nhất: KBC Op.CF=-17,344 tỷ.\n"
            "📅 Sự kiện")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HNG D/E=8.83, PET D/E=2.67, VTZ D/E=2.63" in fixed   # commas intact
    assert "KBC Op.CF=-17,344 tỷ" in fixed                       # thousands sep intact


def test_enforce_risk_section_canonicalizes_all_failure_modes():
    # One deterministic guard replaces the LLM's fundamental claims with the
    # canonical block — fixing every recurring class at once: wrong metric, wrong
    # number, wrong superlative, mis-pick, self-contradiction. Macro narrative is
    # kept; financials excluded; BĐS tagged with context.
    from vnstock_brief import enforce_risk_section
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "ocf": 915.0},
        "PET": {"de": 2.67, "ocf": -1389.0},
        "VTZ": {"de": 2.63, "ocf": -318.0},
        "KBC": {"de": 1.12, "ocf": -17344.0},
        "NVL": {"de": 3.50, "ocf": -6145.0},
        "VCB": {"de": 9.0, "ocf": -50000.0},          # bank → must be excluded
    }, "financial_tickers": {"VCB"}, "realestate_tickers": {"KBC", "NVL"}}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "Rủi ro vĩ mô và kỹ thuật vẫn hiện hữu khi VNINDEX gần đáy range.\n"
            "PET và VTZ có D/E cao nhất với 2.67 và 2.63; KBC Op.CF=-99,999 tỷ.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_section(text, ctx)
    # macro line kept
    assert "Rủi ro vĩ mô và kỹ thuật vẫn hiện hữu" in fixed
    # canonical D/E: HNG is the real top, financials excluded
    assert "HNG D/E=8.83" in fixed and "HNG cao nhất trong nhóm theo dõi" in fixed
    assert "VCB" not in fixed
    # the model's wrong superlative + wrong KBC figure are gone
    assert "D/E cao nhất với 2.67" not in fixed and "-99,999" not in fixed
    # canonical Op.CF: lowest two, BĐS-tagged, with context
    assert "KBC Op.CF=-17,344 tỷ (BĐS)" in fixed and "NVL Op.CF=-6,145 tỷ (BĐS)" in fixed
    assert "tích lũy quỹ đất" in fixed
    # section ends cleanly at the next header
    assert fixed.splitlines()[-1] == "📅 Sự kiện sắp tới"


def test_enforce_risk_section_skips_low_de_and_noops():
    from vnstock_brief import enforce_risk_section
    # all D/E < 1.5 → no leverage line (low D/E is not a risk); only neg OCF
    ctx = {"vn30_fundamentals": {"AAA": {"de": 0.8, "ocf": -500.0},
                                 "BBB": {"de": 1.1, "ocf": 200.0}},
           "realestate_tickers": set()}
    text = "⚠️ Rủi ro cần lưu ý\nMột số rủi ro vĩ mô.\n📅 Sự kiện"
    fixed = enforce_risk_section(text, ctx)
    assert "Đòn bẩy cao nhất" not in fixed           # no high D/E → no leverage line
    assert "AAA Op.CF=-500 tỷ" in fixed
    # no fundamentals / no section → untouched
    assert enforce_risk_section(text, {}) == text
    assert enforce_risk_section("🎯 TLDR\nx", ctx) == "🎯 TLDR\nx"


def test_enforce_risk_numbers_inserts_real_top_de_when_superlative_wrong():
    # 11:19: "PET và VTZ có D/E cao nhất với 2.67 và 2.63" while HNG=8.83 (the
    # real top) was omitted. Prepend HNG and demote the false "cao nhất" → "cao".
    from vnstock_brief import enforce_risk_numbers
    ctx = {"vn30_fundamentals": {
        "HNG": {"de": 8.83, "ocf": 915.0}, "PET": {"de": 2.67, "ocf": -1389.0},
        "VTZ": {"de": 2.63, "ocf": -318.0}, "KBC": {"de": 1.12, "ocf": -17344.0},
    }}
    text = ("⚠️ Rủi ro cần lưu ý\n"
            "PET và VTZ có D/E cao nhất với 2.67 và 2.63; KBC có Op.CF=-17,344 tỷ.\n"
            "📅 Sự kiện sắp tới")
    fixed = enforce_risk_numbers(text, ctx)
    assert "HNG D/E=8.83 (đòn bẩy cao nhất)" in fixed
    assert "PET và VTZ có D/E cao với 2.67" in fixed   # demoted, not "cao nhất"
    assert fixed.count("cao nhất") == 1                # only HNG keeps it


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


def test_enforce_buy_vs_bias_caveat_appends_under_giam():
    # Bias floor = GIẢM but the "Đề xuất giao dịch" section still lists BUY recs
    # from backtested strategies → a one-line caveat is appended (recs KEPT).
    from vnstock_brief import enforce_buy_vs_bias_caveat
    ctx = {"bias_floor": {"dir": "GIẢM", "momentum": -67, "regime_score": -4}}
    text = ("## 💡 Đề xuất giao dịch (nếu có Khuyến nghị trong data)\n"
            "- FPT BUY entry=120,000 TP=132,000 SL=114,000\n"
            "- HPG BUY entry=28,000 TP=31,000 SL=26,500\n"
            "\n"
            "## ⚠️ Rủi ro cần lưu ý\n"
            "- ...")
    fixed = enforce_buy_vs_bias_caveat(text, ctx)
    assert "tín hiệu backtest TỪNG MÃ" in fixed
    assert "tôn trọng cắt lỗ" in fixed
    # recs are kept, not filtered
    assert "FPT BUY" in fixed and "HPG BUY" in fixed
    # caveat sits INSIDE the rec section (before the next ## header)
    assert fixed.index("backtest TỪNG MÃ") < fixed.index("## ⚠️ Rủi ro")
    # idempotent
    assert enforce_buy_vs_bias_caveat(fixed, ctx) == fixed
    # and it survives the full shared chain (wired into apply_brief_guards)
    from vnstock_brief import apply_brief_guards
    assert "tín hiệu backtest TỪNG MÃ" in apply_brief_guards(text, ctx)


def test_enforce_buy_vs_bias_caveat_noops():
    from vnstock_brief import enforce_buy_vs_bias_caveat
    buy_sec = ("## 💡 Đề xuất giao dịch\n"
               "- FPT BUY entry=120,000 TP=132,000 SL=114,000\n")
    # no bias floor → untouched
    assert enforce_buy_vs_bias_caveat(buy_sec, {}) == buy_sec
    # bias TĂNG → BUY recs are consistent → untouched
    assert enforce_buy_vs_bias_caveat(buy_sec, {"bias_floor": {"dir": "TĂNG"}}) == buy_sec
    ctx_giam = {"bias_floor": {"dir": "GIẢM"}}
    # SELL-only recs under GIẢM are already consistent → no caveat
    sell_sec = ("## 💡 Đề xuất giao dịch\n"
                "- FPT SELL entry=120,000 TP=110,000 SL=126,000\n")
    assert enforce_buy_vs_bias_caveat(sell_sec, ctx_giam) == sell_sec
    # purely conditional 'canh MUA NẾU vượt' is already bias-aware → no caveat
    cond_sec = ("## 💡 Đề xuất giao dịch\n"
                "- FPT: canh MUA NẾU vượt 122,000 → mục tiêu 130,000; cắt lỗ 116,000\n")
    assert enforce_buy_vs_bias_caveat(cond_sec, ctx_giam) == cond_sec
    # no rec section at all → untouched
    no_sec = "## 🎯 TLDR\nStance: GIẢM\n## ⚠️ Rủi ro\n- ..."
    assert enforce_buy_vs_bias_caveat(no_sec, ctx_giam) == no_sec


def test_enforce_stance_sentiment_caution_flags_bullish_vs_negative_mood():
    # Close 30/06: "Stance ngày mai: TĂNG" while sentiment was "📉 Tiêu cực
    # (momentum -24)". -24 doesn't trip the hard GIẢM floor (≤ -50), so the
    # bullish lean stands — but a caution is appended under the stance.
    from vnstock_brief import enforce_stance_sentiment_caution
    ctx = {"market_sentiment": {"momentum": -24}}
    t = ("## 🎯 TLDR\n**Stance ngày mai:** TĂNG bias với canh mua nếu vượt R1.\n"
         "## 📊 Tổng kết phiên\n…")
    f = enforce_stance_sentiment_caution(t, ctx)
    assert "tâm lý thị trường đang TIÊU CỰC" in f
    assert "momentum -24/100" in f and "tôn trọng cắt lỗ" in f
    # the caveat sits under the stance line, before the next section
    assert f.index("đang TIÊU CỰC") < f.index("## 📊 Tổng kết")
    assert enforce_stance_sentiment_caution(f, ctx) == f          # idempotent
    # morning "Bias:" form is handled too
    tm = "## 🎯 TLDR\n**Bias:** TĂNG — đà phục hồi.\n## 📊"
    assert "tâm lý thị trường đang TIÊU CỰC" in enforce_stance_sentiment_caution(tm, ctx)


def test_enforce_stance_sentiment_caution_noop_cases():
    from vnstock_brief import enforce_stance_sentiment_caution
    neg = {"market_sentiment": {"momentum": -24}}
    # bearish / neutral stance → consistent → no caveat
    assert "TIÊU CỰC" not in enforce_stance_sentiment_caution("**Stance ngày mai:** GIẢM bias.", neg)
    assert "TIÊU CỰC" not in enforce_stance_sentiment_caution("**Stance ngày mai:** TRUNG TÍNH.", neg)
    # sentiment not negative enough (> -20) → no caveat
    t = "**Stance ngày mai:** TĂNG bias."
    assert enforce_stance_sentiment_caution(t, {"market_sentiment": {"momentum": -5}}) == t
    assert enforce_stance_sentiment_caution(t, {"market_sentiment": {"momentum": 30}}) == t
    # missing sentiment → no-op
    assert enforce_stance_sentiment_caution(t, {}) == t


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


def test_fmt_rec_price_keeps_a_decimal_in_the_10_100_band():
    """Vết brief chiều 19/08: in `SBT entry=24 TP=25 SL=23` trong khi sổ ghi
    TP +7,4% / SL −2,7% trên entry ≈ 23,5 — mốc TP thật ≈ 25,2. Bỏ hết thập
    phân ở dải 10-100 (nơi phần lớn cổ phiếu VN nằm) sai tới ±0,5 nghìn, tức
    hơn một phần tư một mục tiêu 7,4%, và lệch cả hai chiều BẤT LỢI cho người
    đọc: chốt lời sớm, cắt lỗ sát hơn ý đồ."""
    assert _fmt_rec_price(23.5) == "23.5"
    assert _fmt_rec_price(25.24) == "25.2"
    assert _fmt_rec_price(42.6) == "42.6"
    # giá tròn vẫn đọc gọn, không đuôi ".0"
    assert _fmt_rec_price(49.03) == "49"
    assert _fmt_rec_price(99.9) == "99.9"


def test_fmt_rec_price_error_stays_under_half_a_percent():
    """Bất biến thật sự cần giữ, không phải số chữ số: sai số hiển thị phải
    nhỏ hơn hẳn biên TP/SL điển hình (5-15%)."""
    for v in (10.04, 12.37, 23.51, 47.83, 99.94, 137.4, 213.6):
        shown = float(_fmt_rec_price(v).replace(",", ""))
        assert abs(shown - v) / v < 0.005, f"{v} hiển thị {shown}"
    assert _fmt_rec_price(0) == "0"


def test_recommendation_block_excludes_overdue_and_keeps_precision(monkeypatch):
    now = _datetime.now()
    fresh   = (now - _timedelta(days=2)).isoformat()
    overdue = (now - _timedelta(days=34)).isoformat()
    # Hermetic (bài học 15/08, đỏ lần đầu trên MÁY BÀN): rec giả không mang
    # strategy_id → _recommendation_block rơi về kiểm định của chiến lược
    # ACTIVE = đọc DB SQLite THẬT của máy đang chạy test. Máy có chiến lược
    # trượt kiểm định (desktop: p=0.764) → mọi rec bị chặn đúng luật → test
    # đỏ oan. Ý đồ test này là lọc-quá-hạn + độ chính xác giá, không phải
    # gating — chốt thế giới: không có chiến lược active.
    monkeypatch.setattr("vnstock_memory.get_active_family",
                        lambda *a, **k: None)
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
    # Cùng lỗ hermetic với test trên — chốt thế giới không chiến lược active
    monkeypatch.setattr("vnstock_memory.get_active_family",
                        lambda *a, **k: None)
    monkeypatch.setattr("vnstock_memory.open_recommendations", lambda: [
        {"ticker": "KSF", "action": "buy", "entry_price": 113.0,
         "take_profit": 129.0, "cut_loss": 105.0, "horizon_days": 5,
         "created_at": overdue},
    ])
    assert _recommendation_block() == ""


# ─── split_recs_by_validation: luật ẩn dùng chung brief + Telegram (mục 10) ───

def test_split_recs_by_validation_hides_only_known_failed(monkeypatch):
    import vnstock_brief as vb
    vals = {
        7: {"known": True, "passed": False, "p": 0.764, "reasons": ["p quá cao"]},
        8: {"known": True, "passed": True, "p": 0.012, "reasons": []},
        9: {"known": False, "passed": True, "p": None, "reasons": []},
    }
    monkeypatch.setattr(vb, "_validation_of_strategy", lambda sid: vals[sid])
    monkeypatch.setattr(vb, "_active_strategy_validation",
                        lambda ctx=None: {"known": True, "passed": False,
                                          "p": 0.5, "reasons": ["active trượt"]})
    recs = [{"ticker": "AAA", "strategy_id": 7},
            {"ticker": "BBB", "strategy_id": 8},
            {"ticker": "CCC", "strategy_id": 9},   # unknown → VẪN phát
            {"ticker": "DDD"},                     # legacy → active (trượt) → ẩn
            {"ticker": "EEE", "strategy_id": 7}]   # cùng chiến lược 7 → dedup
    emitted, hidden = vb.split_recs_by_validation(recs)
    assert [r["ticker"] for r in emitted] == ["BBB", "CCC"]
    # hidden_vals: validation-dict dedup (7 bị ẩn 2 rec nhưng chỉ 1 entry),
    # còn đủ p/lý do để chỗ gọi in sentinel
    assert {v["p"] for v in hidden} == {0.764, 0.5}
    assert len(hidden) == 2


def test_recommendation_block_delegates_to_shared_splitter():
    # Net parity (mục 10): luật ẩn nằm MỘT chỗ — ai inline lại _val_of vào
    # _recommendation_block là tách luật brief khỏi luật Telegram (cùng họ
    # lỗi với inline lại apply_brief_guards).
    import inspect
    import vnstock_brief as vb
    assert "split_recs_by_validation(" in inspect.getsource(vb._recommendation_block)


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

def test_market_data_freshness_flags_stale_overview(tmp_path, monkeypatch):
    import json as _json
    import vnstock_brief as _vb
    # Legacy overview without data_date → the fallback reads the real warehouse
    # EOD date. Pin it to None so this test (which exercises the generated_at
    # last-resort) is deterministic regardless of the machine's warehouse.
    monkeypatch.setattr(_vb, "_warehouse_eod_date", lambda: None)
    p = tmp_path / "market_overview.json"
    p.write_text(_json.dumps({"generated_at": "2026-06-08 09:00:00"}))
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is True
    assert fr["overview_date"] == "2026-06-08"
    assert fr["stale_blocks"]


def test_market_data_freshness_fresh_when_same_day_and_after_the_close(tmp_path):
    """Cùng phiên VÀ chốt SAU 15:05 mới là tươi.

    Bản cũ của test này chỉ đòi CÙNG NGÀY, và nó chính là lỗ hổng: overview
    chốt lúc 11:00 mang cùng `data_date` với overview chốt phiên nên được coi
    là tươi, trong khi độ rộng/movers/dòng tiền mới thấy nửa buổi sáng. Xem
    `tests/test_brief_freshness_intraday.py`.
    """
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 18:30:00"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is False
    assert fr["stale_blocks"] == []


def test_market_data_freshness_same_day_but_mid_session_is_stale(tmp_path):
    p = tmp_path / "market_overview.json"
    p.write_text('{"generated_at": "2026-06-09 11:00:00"}')
    fr = market_data_freshness(data_date="2026-06-09", overview_path=p)
    assert fr["stale"] is True and fr["reason"] == "intraday"


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


def test_enforce_range_position_inserts_computed_pct():
    # 11:03: "**Vị trí trong range:** Gần đáy range tuần" lacked the %. Insert
    # (close−week_low)/(week_high−week_low) — here 27%.
    from vnstock_brief import enforce_range_position
    ctx = {"vnindex_tech": {"close": 1798.61, "week_low": 1780.71, "week_high": 1846.71}}
    text = ("📈 Mức kỹ thuật chốt phiên\n"
            "**Vị trí trong range:** Gần đáy range tuần\n"
            "**Vs MA:** dưới MA20")
    fixed = enforce_range_position(text, ctx)
    assert "**Vị trí trong range:** 27% — Gần đáy range tuần" in fixed
    # already has a % → untouched; no range data → untouched
    t2 = "**Vị trí trong range:** 27% (gần đáy)"
    assert enforce_range_position(t2, ctx) == t2
    assert enforce_range_position(text, {}) == text


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


# ── P4: 📚 Báo cáo vĩ mô & phân bổ + brief allocation ────────────────────────

def _p4_ctx():
    return {
        "allocation": {
            "band": "B3", "band_label": "thắt chặt", "band_data": "B2",
            "score": -0.21, "as_of": "2026-07-11",
            "report_tilt": {"tilt": 1, "stance_cp": -1.5, "n_reports": 2,
                            "sources": ["SSI", "HSC"]},
            "allocation": {"Cổ phiếu": 30, "Trái phiếu": 25, "Tiền gửi": 30,
                           "Vàng": 10, "USD": 5},
            "inputs": [{"key": "regime", "label": "Regime thị trường",
                        "value": "score -2 (7 tín hiệu)", "score": -0.4,
                        "weight": 0.25, "source": "vnstock_regime",
                        "as_of": "2026-07-11"}],
        },
        "macro_reports": [
            {"id": "abc", "report_date": "2026-07-08", "source": "SSI",
             "digest": {"tom_tat": "Vĩ mô thắt chặt, hạ tỷ trọng cổ phiếu.",
                        "stance": {"Cổ phiếu": -2}, "has_mismatch": False}},
            {"id": "def", "report_date": "2026-07-05", "source": "HSC",
             "digest": {"tom_tat": "Trung lập, chờ số liệu quý.",
                        "stance": {"Cổ phiếu": -1}, "has_mismatch": True}},
        ],
        "reports_consensus": {"n_reports": 2, "tilt": 1,
                              "stance": {"Cổ phiếu": -1.5}},
    }


def test_macro_reports_body_lines_cap_and_content():
    from vnstock_brief import _macro_reports_body_lines
    body = _macro_reports_body_lines(_p4_ctx(), directive=False)
    # 1 band + 2 báo cáo + 1 consensus = 4 dòng (cap ~5), không dòng chỉ thị
    assert len(body) == 4
    assert "Band phân bổ tháng: B3" in body[0]
    assert "tilt +1" in body[0] and "band data: B2" in body[0]
    assert "[2026-07-08] SSI" in body[1] and "stance cổ phiếu -2" in body[1]
    assert "số lệch registry" in body[2]              # mismatch được ghi chú
    assert "Consensus 2 báo cáo" in body[3] and "-1.50" in body[3]
    assert not any(l.startswith("→") for l in body)   # directive=False
    # prompt renderer có dòng chỉ thị
    with_directive = _macro_reports_body_lines(_p4_ctx(), directive=True)
    assert with_directive[-1].startswith("→")
    # ctx trống → []
    assert _macro_reports_body_lines({}, directive=False) == []


def test_enforce_macro_reports_replaces_section_and_denial():
    from vnstock_brief import _macro_reports_body_lines, enforce_macro_reports
    ctx = _p4_ctx()
    body = _macro_reports_body_lines(ctx, directive=False)
    # (1) thay body mục có header — LLM bịa band B0 + nguồn lạ
    text = ("## 📰 Tin kinh tế/chính trị nổi bật\n- tin A\n"
            "## 📚 Báo cáo vĩ mô & phân bổ\n- Band B0, VNDirect khuyên mua.\n"
            "## 📌 Danh mục đang giữ\nKhông có vị thế đang mở")
    out = enforce_macro_reports(text, ctx)
    assert "VNDirect khuyên mua" not in out
    assert "Band phân bổ tháng: B3" in out
    assert "Không có vị thế đang mở" in out           # mục sau còn nguyên
    assert enforce_macro_reports(out, ctx) == out     # idempotent
    # (2) không header → splice đè dòng phủ nhận
    text2 = "## 🎯 TLDR\nx\nChưa có báo cáo vĩ mô nào.\n## 📊 Tổng kết phiên\ny"
    out2 = enforce_macro_reports(text2, ctx)
    assert "Chưa có báo cáo vĩ mô nào." not in out2
    assert "Band phân bổ tháng: B3" in out2
    # (3) no-op khi ctx trống
    assert enforce_macro_reports(text, {}) == text


def test_enforce_allocation_table_pins_band_tokens():
    from vnstock_brief import enforce_allocation_table
    ctx = _p4_ctx()
    text = ("## 🎯 TLDR\n**Bias:** GIẢM — phù hợp band B0 hiện tại.\n"
            "## 📚 Báo cáo vĩ mô & phân bổ\n"
            "- 🧭 Band phân bổ tháng: B3 (thắt chặt) — điểm -0.21, phiên "
            "2026-07-11; đã gồm tilt +1 từ báo cáo (band data: B2)\n")
    out = enforce_allocation_table(text, ctx)
    assert "band B3 hiện tại" in out                  # token lạc được pin
    assert "band data: B2" in out                     # dòng canonical giữ B2
    assert enforce_allocation_table(out, ctx) == out  # idempotent
    assert enforce_allocation_table(text, {}) == text # no-op không allocation


def test_enforce_allocation_table_canonical_table_for_allocation_brief():
    from vnstock_brief import _allocation_table_lines, enforce_allocation_table
    ctx = _p4_ctx()
    text = ("## 🎯 TLDR\n**Band phân bổ:** B1 — tích cực.\n"
            "## 🧭 Phân bổ đề xuất\n- Cổ phiếu: 70%\n- Vàng: 2%\n"
            "## 📊 Vì sao ở band này\nregime yếu.")
    out = enforce_allocation_table(text, ctx)
    assert "**Band phân bổ:** B3" in out              # TLDR band được pin
    assert "- Cổ phiếu: 30%" in out                   # bảng canonical thay bảng bịa
    assert "- Vàng: 10%" in out and "- Vàng: 2%" not in out
    assert "- Band: B3 (thắt chặt)" in out
    assert "regime yếu." in out                       # mục sau còn nguyên
    assert out == enforce_allocation_table(out, ctx)  # idempotent
    assert _allocation_table_lines({}) == []


def test_enforce_allocation_table_horizon_caveat():
    from vnstock_brief import _ALLOC_HORIZON_CAVEAT, enforce_allocation_table
    # band TẤN CÔNG (B1) + bias floor ngày GIẢM → caveat sau dòng band
    ctx = _p4_ctx()
    ctx["allocation"] = {**ctx["allocation"], "band": "B1",
                         "band_label": "tích cực", "report_tilt": None}
    ctx["bias_floor"] = {"dir": "GIẢM", "momentum": -60}
    text = ("## 📚 Báo cáo vĩ mô & phân bổ\n"
            "- 🧭 Band phân bổ tháng: B1 (tích cực) — điểm 0.30, phiên 2026-07-11\n"
            "## 📌 Danh mục đang giữ\nx")
    out = enforce_allocation_table(text, ctx)
    assert _ALLOC_HORIZON_CAVEAT in out
    lines = out.splitlines()
    assert lines[lines.index(_ALLOC_HORIZON_CAVEAT) - 1].startswith("- 🧭 Band")
    assert out == enforce_allocation_table(out, ctx)  # không chèn trùng
    # caveat KHÔNG phải ranh giới mục (bắt đầu bằng "- ")
    from vnstock_brief import _is_section_start
    assert not _is_section_start(_ALLOC_HORIZON_CAVEAT)
    # cùng chiều (band B3 + bias GIẢM) → không caveat
    ctx2 = _p4_ctx()
    ctx2["bias_floor"] = {"dir": "GIẢM"}
    text2 = "- 🧭 Band phân bổ tháng: B3 (thắt chặt) — điểm -0.21, phiên 2026-07-11"
    assert _ALLOC_HORIZON_CAVEAT not in enforce_allocation_table(text2, ctx2)


def test_build_prompt_macro_reports_block_and_allocation_template():
    ctx = {"date": "2026-07-13", "time": "15:00", **_p4_ctx()}
    # brief ngày: có block 📚, KHÔNG có block bảng % đầy đủ
    day = build_prompt(ctx, brief_type="afternoon")
    assert "## 📚 Báo cáo vĩ mô & phân bổ (khung THÁNG — trung hạn)" in day
    assert "Band phân bổ tháng: B3" in day
    assert "## 🧭 Phân bổ hiện hành" not in day
    # brief allocation: template riêng + block state đầy đủ (bảng % + lý do)
    al = build_prompt(ctx, brief_type="allocation")
    assert "BRIEF PHÂN BỔ TÀI SẢN" in al
    assert "## 🧭 Phân bổ hiện hành" in al
    assert "- Cổ phiếu: 30%" in al
    assert "Lý do: Regime thị trường" in al and "vnstock_regime" in al
    assert "Watchlist sáng mai" not in al             # không lẫn template ngày


def test_apply_brief_guards_includes_p4_guards():
    import inspect

    import vnstock_brief
    src = inspect.getsource(vnstock_brief.apply_brief_guards)
    assert "enforce_macro_reports(" in src
    assert "enforce_allocation_table(" in src
    # chuỗi chung chạy sạch trên brief mang mục 📚 bịa + ctx P4
    ctx = _p4_ctx()
    text = ("## 📚 Báo cáo vĩ mô & phân bổ\n- Band B0, mua mạnh cổ phiếu.\n"
            "## 📌 Danh mục đang giữ\nKhông có vị thế đang mở")
    out = vnstock_brief.apply_brief_guards(text, ctx)
    assert "Band phân bổ tháng: B3" in out and "mua mạnh" not in out
    assert vnstock_brief.apply_brief_guards(out, ctx) == out


def test_brief_max_tokens_bumped_for_p4():
    from vnstock_brief import _BRIEF_MAX_TOKENS
    assert _BRIEF_MAX_TOKENS == 2800


# ── Vá guard từ close brief thật 14/07 (verify P4 với data thật) ─────────────

def test_breadth_label_catches_so_ma_co_phieu():
    # Close 14/07: "chỉ 13% số mã cổ phiếu tăng giá" — 13% là above_ma200_pct;
    # regex cũ có nhánh "số mã" và "mã cổ phiếu" nhưng thiếu tổ hợp GHÉP
    # "số mã cổ phiếu" → lọt lưới.
    from vnstock_brief import enforce_breadth_label
    ctx = {"breadth": {"above_ma200_pct": 13}}
    out = enforce_breadth_label(
        "Độ rộng tiêu cực, với chỉ 13% số mã cổ phiếu tăng giá và A/D 0.47.",
        ctx)
    assert "tăng giá" not in out
    assert "13% số mã cổ phiếu trên MA200" in out
    assert enforce_breadth_label(out, ctx) == out     # idempotent
    # số KHÔNG khớp above_ma200_pct → không đụng (46% tăng thật từ A/D)
    keep = "46% số mã cổ phiếu tăng giá"
    assert enforce_breadth_label(keep, ctx) == keep


def test_vnindex_change_skips_gtgd_subject():
    # Close 14/07: "GTGD ... giảm 1.52% so với phiên trước" — 1.52 là % đổi
    # VNINDEX bị enforce_vnindex_change ĐÈ vào mệnh đề GTGD (guard tự tạo lỗi
    # vì regex whole-text không kiểm tra chủ ngữ).
    from vnstock_brief import enforce_vnindex_change
    ctx = {"vnindex_tech": {"day_change_pct": -1.52}}
    text = ("VNINDEX đóng cửa 1,800.54, tăng -24% so với phiên trước. "
            "GTGD toàn thị trường đạt 23,620.6 tỷ đồng, giảm 8.30% so với "
            "phiên trước và tăng 25% so với trung bình 5 phiên.")
    out = enforce_vnindex_change(text, ctx)
    # mệnh đề chỉ số: pin về day_change_pct thật
    assert "giảm 1.52% so với phiên trước" in out
    # mệnh đề GTGD: GIỮ NGUYÊN số của nó, không bị đè
    assert "giảm 8.30% so với phiên trước" in out
    assert enforce_vnindex_change(out, ctx) == out    # idempotent


# ── Reflection + debate wiring (khảo sát TradingAgents 14/07) ────────────────

def test_reflections_block_in_prompt_all_types_not_a_brief_section():
    from vnstock_brief import _reflections_block
    ctx = {"date": "2026-07-14", "time": "15:00",
           "reflections": [{"id": "rec-1", "date": "2026-07-10",
                            "label": "BUY HPG +8.2% (tp)",
                            "lesson": "Chỉ vào breakout khi GTGD xác nhận."}]}
    for btype in ("morning", "afternoon", "allocation"):
        prompt = build_prompt(ctx, brief_type=btype)
        assert "## 🧠 Bài học từ quyết định đã đóng" in prompt, btype
        assert "BUY HPG +8.2%" in prompt
        assert "KHÔNG tạo mục 'Bài học'" in prompt   # chỉ thị chống echo
    assert _reflections_block([]) == ""
    # không có reflections trong ctx → prompt sạch
    assert "🧠 Bài học" not in build_prompt(
        {"date": "2026-07-14", "time": "15:00"}, brief_type="afternoon")


def test_debate_block_only_in_allocation_prompt():
    from vnstock_brief import _debate_block
    ctx = {"date": "2026-07-14", "time": "15:00",
           "allocation": {"band": "B4", "band_label": "căng thẳng",
                          "score": -0.7, "as_of": "2026-07-13",
                          "allocation": {"Cổ phiếu": 15, "Trái phiếu": 25,
                                         "Tiền gửi": 40, "Vàng": 12, "USD": 8},
                          "inputs": []},
           "allocation_debate": {"band": "B4", "as_of": "2026-07-13",
                                 "points": ["Độ rộng 13% là vùng quá bán.",
                                            "Điều kiện đảo ngược: vượt MA20."]}}
    al = build_prompt(ctx, brief_type="allocation")
    assert "## 🗣 Phản biện band B4" in al
    assert "Độ rộng 13% là vùng quá bán." in al
    assert "PHẢI đối diện các phản biện" in al
    # brief NGÀY không mang block phản biện (khung thời gian khác)
    day = build_prompt(ctx, brief_type="afternoon")
    assert "🗣 Phản biện" not in day
    assert _debate_block(None) == "" and _debate_block({"points": []}) == ""


def test_generate_brief_source_wires_debate_for_allocation_only():
    import inspect

    import vnstock_brief
    src = inspect.getsource(vnstock_brief.generate_brief)
    assert "run_debate" in src
    assert 'brief_type == "allocation"' in src


# ─── CHOP(14) + mẫu nến trong block VNINDEX kỹ thuật (khảo sát StockSharp) ───

def test_build_prompt_includes_chop_and_candle_pattern_lines():
    ctx = {"date": "2026-07-15", "time": "15:00",
           "vnindex_tech": {"close": 1803.71, "intraday": False,
                            "chop14": 63.4,
                            "candle_patterns": ["Nến búa (Hammer)",
                                                "Đáy nhíp (Tweezer Bottom)"]}}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "CHOP(14): 63.4" in p and "đi ngang/choppy" in p
    assert "Mẫu nến phiên gần nhất: Nến búa (Hammer); Đáy nhíp (Tweezer Bottom)" in p
    assert "cần nến xác nhận" in p
    # nhãn CHOP theo band: có xu hướng rõ khi < 38.2
    ctx["vnindex_tech"]["chop14"] = 31.0
    assert "có xu hướng rõ" in build_prompt(ctx, brief_type="afternoon")


def test_build_prompt_omits_chop_and_candle_lines_when_absent():
    ctx = {"date": "2026-07-15", "time": "15:00",
           "vnindex_tech": {"close": 1803.71, "intraday": False}}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "CHOP(14)" not in p
    assert "Mẫu nến phiên gần nhất" not in p


def test_build_prompt_includes_ha_streak_line():
    ctx = {"date": "2026-07-15", "time": "15:00",
           "vnindex_tech": {"close": 1803.71, "intraday": False,
                            "ha_streak": 4}}
    p = build_prompt(ctx, brief_type="afternoon")
    assert "Heikin-Ashi: 4 nến xanh (tăng) sạch liên tiếp" in p
    ctx["vnindex_tech"]["ha_streak"] = -3
    assert "Heikin-Ashi: 3 nến đỏ (giảm) sạch liên tiếp" in build_prompt(
        ctx, brief_type="afternoon")
    # streak 0/1 hoặc thiếu → không render (nhiễu)
    ctx["vnindex_tech"]["ha_streak"] = 1
    assert "Heikin-Ashi" not in build_prompt(ctx, brief_type="afternoon")
    del ctx["vnindex_tech"]["ha_streak"]
    assert "Heikin-Ashi" not in build_prompt(ctx, brief_type="afternoon")
