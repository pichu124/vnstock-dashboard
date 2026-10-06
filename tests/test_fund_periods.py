"""Pha 2 của câu 1 = b (U75): bảng cực trị D/E · Op.CF in lại CHỈ khi có KỲ
BCTC MỚI, kèm kỳ trước.

Canh bốn tầng: nhãn kỳ + sổ kỳ (`vnstock_fund_periods`, hàm thuần) · updater
ghi cột kỳ + sổ CẠNH `FUND_PATH` (bài học U17: không bao giờ vào kho thật) ·
brief đọc sổ và đánh dấu "đã báo" chỉ ở phiên CHIỀU · guard dựng dòng
'- Kỳ BCTC mới — …' idempotent qua toàn chuỗi, chế độ cũ không đổi một byte.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import vnstock_brief as vb
import vnstock_fund_periods as fp
import vnstock_fundamental_updater as fu
from tests.test_brief_risk_today import LEGACY_05_10, RAW_0510, _ctx_0510, _section
from vnstock_brief_canon import _RISK_FALLBACK_LINE, _RISK_LINE_PREFIXES, _RISK_PERIOD_PREFIX
from vnstock_brief_guards_sections import (
    _canonical_risk_lines,
    _risk_extremes,
    _risk_period_lines,
    enforce_risk_today,
)


# ── Nhãn kỳ ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,label,text", [
    ("2025", "2025", "năm 2025"),
    ("2025.0", "2025", "năm 2025"),
    (2024, "2024", "năm 2024"),
    ("2026-Q2", "2026-Q2", "Q2/2026"),
    ("Q3/2026", "2026-Q3", "Q3/2026"),
    ("2026-LK3", "2026-LK3", "lũy kế 3 quý 2026"),
    ("2026-LK4", "2026", "năm 2026"),          # đủ 4 quý = cả năm
    ("TTM", None, ""),
    (None, None, ""),
])
def test_norm_period_and_text(raw, label, text):
    assert fp.norm_period(raw) == label
    assert fp.period_text(raw) == text


def test_period_key_order():
    order = ["2024", "2025-Q1", "2025-Q4", "2025-LK3", "2025", "2026-Q1"]
    assert sorted(order, key=fp.period_key) == [
        "2024", "2025-Q1", "2025-LK3", "2025-Q4", "2025", "2026-Q1"]
    assert fp.period_key("2025") > fp.period_key("2025-LK3") > fp.period_key("2025-Q3")


@pytest.mark.parametrize("row,label", [
    ({"report_period": "2026-Q1", "Debt/Equity": 1.2}, "2026-Q1"),
    ({"report_period": "2025", "Debt/Equity": 1.2}, "2025"),
    ({("Meta", "yearReport"): 2025, ("Meta", "lengthReport"): 5}, "2025"),
    ({("Meta", "yearReport"): 2025, ("Meta", "lengthReport"): 2}, "2025-Q2"),
    ({"Debt/Equity": 1.2}, None),
])
def test_row_period_label(row, label):
    assert fp.row_period_label(pd.Series(row)) == label


# ── Sổ kỳ ───────────────────────────────────────────────────────────────────

def _row(t, de=None, dep=None, ocf=None, ocfp=None):
    return {"ticker": t, "debt_to_equity": de, "de_period": dep,
            "operating_cf": ocf, "ocf_period": ocfp}


def test_fold_bootstrap_is_baseline_not_event():
    led = fp.fold(None, [_row("kbc", 1.1, "2025", -17344.0, "2025")], "2026-10-10")
    kbc = led["tickers"]["KBC"]
    assert kbc["ocf"] == {"period": "2025", "value": -17344.0,
                          "first_seen": None, "prev": None}
    assert kbc["de"]["first_seen"] is None
    assert fp.period_news(led, {}, ["KBC"], "2026-10-12") == {}


def test_fold_rules_and_no_mutation():
    base = fp.fold(None, [_row("KBC", 1.1, "2025", -17344.0, "2025")], "2026-10-10")
    snap = json.loads(json.dumps(base))
    led = fp.fold(base, [_row("KBC", 1.3, "2024", -16510.0, "2026-LK3")], "2027-01-09")
    assert base == snap                                     # không sửa sổ cũ
    assert led["tickers"]["KBC"]["de"]["period"] == "2025"  # kỳ CŨ hơn ⇒ bỏ qua
    assert led["tickers"]["KBC"]["ocf"] == {
        "period": "2026-LK3", "value": -16510.0, "first_seen": "2027-01-09",
        "prev": {"period": "2025", "value": -17344.0}}
    # cùng kỳ, nguồn sửa số ⇒ cập nhật số, GIỮ first_seen/prev
    led2 = fp.fold(led, [_row("KBC", None, None, -16600.0, "2026-LK3")], "2027-01-16")
    assert led2["tickers"]["KBC"]["ocf"]["value"] == -16600.0
    assert led2["tickers"]["KBC"]["ocf"]["first_seen"] == "2027-01-09"
    # thiếu kỳ hoặc thiếu số ⇒ không đụng
    led3 = fp.fold(led2, [_row("KBC", 9.9, None, None, "2027")], "2027-02-01")
    assert led3["tickers"] == led2["tickers"]


def _ledger_with_event(first_seen="2027-01-09"):
    base = fp.fold(None, [_row("KBC", 1.1, "2025", -17344.0, "2025"),
                          _row("VTZ", 2.81, "2025")], "2026-10-10")
    return fp.fold(base, [_row("KBC", 1.1, "2025", -16510.0, "2026-LK3")], first_seen)


def test_period_news_window_and_announced():
    led = _ledger_with_event()
    ev = {"KBC": {"ocf": {"period": "2026-LK3", "first_seen": "2027-01-09",
                          "prev_period": "2025", "prev_value": -17344.0}}}
    assert fp.period_news(led, {}, ["KBC", "VTZ"], "2027-01-12") == ev
    assert fp.period_news(led, {}, ["VTZ"], "2027-01-12") == {}          # lọc theo mã
    same = {"KBC|ocf|2026-LK3": "2027-01-12"}
    assert fp.period_news(led, same, ["KBC"], "2027-01-12") == ev        # chạy lại cùng phiên
    assert fp.period_news(led, same, ["KBC"], "2027-01-13") == {}        # phiên sau: im
    assert fp.period_news(led, {}, ["KBC"], "2027-03-01") == {}          # quá 45 ngày
    # updater chạy T7 sau phiên T6 (chạy bù) ⇒ tuổi âm vẫn được xét
    assert fp.period_news(led, {}, ["KBC"], "2027-01-08") == ev


def test_mark_announced_keeps_first_date_and_prunes():
    news = {"KBC": {"ocf": {"period": "2026-LK3"}}}
    old = {"KBC|ocf|2026-LK3": "2027-01-12", "X|de|2020": "2025-01-01"}
    out = fp.mark_announced(old, news, "2027-01-13")
    assert out == {"KBC|ocf|2026-LK3": "2027-01-12"}     # giữ ngày đầu, bỏ khoá cũ
    assert old["X|de|2020"] == "2025-01-01"              # không sửa input


def test_record_frame_counts_only_new_events(tmp_path):
    path = tmp_path / "led.json"
    df = pd.DataFrame([_row("KBC", 1.1, "2025", -17344.0, "2025")])
    assert fp.record_frame(df, path, today="2026-10-10") == 0       # mốc
    assert fp.record_frame(df, path, today="2026-10-17") == 0       # không đổi
    df2 = pd.DataFrame([_row("KBC", 1.1, "2026-Q2", -17344.0, "2025")])
    assert fp.record_frame(df2, path, today="2026-10-24") == 1
    assert fp.record_frame(df2, path, today="2026-10-31") == 0      # sự kiện cũ không đếm lại
    assert json.loads(path.read_text(encoding="utf-8"))["tickers"]["KBC"]["de"][
        "prev"] == {"period": "2025", "value": 1.1}


# ── Updater ─────────────────────────────────────────────────────────────────

def _cf(rows):
    return pd.DataFrame([{"report_period": p, "Net cash from operating activities": v}
                         for p, v in rows])


def test_annual_ocf_period_labels():
    assert fu._annual_operating_cf_period(_cf([("2020", 5e9), ("2020-Q1", 1e9)])) == (
        5e9, "2020")
    assert fu._annual_operating_cf_period(
        _cf([("2020-Q1", 1e9), ("2020-Q2", 2e9), ("2020-Q3", 3e9)])) == (6e9, "2020-LK3")
    assert fu._annual_operating_cf_period(
        _cf([(f"2020-Q{i}", 1e9) for i in range(1, 5)])) == (4e9, "2020")
    no_year = pd.DataFrame([{"Net cash from operating activities": 7e9}])
    assert fu._annual_operating_cf_period(no_year) == (7e9, None)
    assert fu._annual_operating_cf(_cf([("2020", 5e9)])) == 5e9   # chữ ký cũ giữ nguyên


def test_fetch_ratios_records_period_of_chosen_row(monkeypatch):
    import vnstock_auth

    ratios = pd.DataFrame([
        {"report_period": "2026-Q2", "P/E": float("nan"), "Debt/Equity": float("nan")},
        {"report_period": "2025", "P/E": 12.0, "Debt/Equity": 2.81},
    ])

    class _Fin:
        def ratio(self, **kw):
            return ratios

    class _Stock:
        finance = _Fin()

    monkeypatch.setattr(vnstock_auth, "get_vnstock", lambda t: _Stock())
    out = fu._fetch_ratios("VTZ")
    assert out["debt_to_equity"] == 2.81 and out["de_period"] == "2025"


def test_fetch_one_drops_period_when_de_comes_from_balance_sheet(monkeypatch):
    monkeypatch.setattr(fu, "_fetch_ratios", lambda t: {"pe": 9.0, "debt_to_equity": 0.0,
                                                        "de_period": "2025"})
    monkeypatch.setattr(fu, "_fetch_cash_flow", lambda t: {})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: 11.2)
    _, data, err = fu._fetch_one("VCB", delay=0.0)
    assert err is None and data["debt_to_equity"] == 11.2 and data["de_period"] is None


def test_update_writes_period_columns_and_ledger_next_to_fund_path(tmp_path, monkeypatch):
    fund = tmp_path / "w" / "fundamentals.parquet"
    fund.parent.mkdir()
    monkeypatch.setattr(fu, "FUND_PATH", fund)
    monkeypatch.setattr(fu, "FUND_HISTORY_DIR", tmp_path / "w" / "hist")
    per = {"de": "2025"}
    monkeypatch.setattr(fu, "_fetch_ratios",
                        lambda t: {"pe": 10.0, "debt_to_equity": 2.5, "de_period": per["de"]})
    monkeypatch.setattr(fu, "_fetch_cash_flow",
                        lambda t: {"operating_cf": -100.0, "ocf_period": "2025"})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: None)
    fu.update(tickers=["VTZ", "KBC"], force=True, delay=0.0)
    df = pd.read_parquet(fund)
    assert set(df["de_period"]) == {"2025"} and set(df["ocf_period"]) == {"2025"}
    led_path = fund.parent / fp.LEDGER_NAME
    led = json.loads(led_path.read_text(encoding="utf-8"))
    assert led["tickers"]["VTZ"]["de"]["first_seen"] is None          # lần đầu = mốc
    per["de"] = "2026-Q2"
    fu.update(tickers=["VTZ", "KBC"], force=True, delay=0.0)
    led = json.loads(led_path.read_text(encoding="utf-8"))
    assert led["tickers"]["VTZ"]["de"]["prev"]["period"] == "2025"
    assert led["tickers"]["VTZ"]["de"]["first_seen"]


def test_update_without_period_keys_still_saves(tmp_path, monkeypatch):
    """Fetch cũ/không nhãn kỳ (test khác patch kiểu này) ⇒ cột kỳ rỗng, không nổ."""
    monkeypatch.setattr(fu, "_fetch_ratios", lambda t: {"pe": 10.0, "roe": 15.0})
    monkeypatch.setattr(fu, "_fetch_cash_flow", lambda t: {"operating_cf": 1.0})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: 1.5)
    fu.update(tickers=["AAA"], force=True, delay=0.0)
    df = pd.read_parquet(fu.FUND_PATH)
    assert df["de_period"].isna().all() and df["ocf_period"].isna().all()


def test_conftest_keeps_writers_off_the_real_warehouse():
    from pathlib import Path
    real = Path(fu.__file__).parent / "data_warehouse" / "_meta"
    for p in (fu.FUND_PATH, fu.FUND_HISTORY_DIR, fp.META_DIR):
        assert real not in Path(p).parents and Path(p) != real


# ── Brief: loader + sổ đã báo ───────────────────────────────────────────────

def test_loader_carries_period_labels(tmp_path):
    p = tmp_path / "f.parquet"
    pd.DataFrame([{"ticker": "VTZ", "debt_to_equity": 2.81, "de_period": "2025",
                   "operating_cf": None, "ocf_period": None, "roe": 5.0}]).to_parquet(p)
    out = vb._load_vn30_fundamentals(path=p, vn30={"VTZ"})
    assert out["VTZ"]["de_period"] == "2025" and "ocf_period" not in out["VTZ"]
    old = tmp_path / "old.parquet"
    pd.DataFrame([{"ticker": "VTZ", "debt_to_equity": 2.81}]).to_parquet(old)
    assert "de_period" not in vb._load_vn30_fundamentals(path=old, vn30={"VTZ"})["VTZ"]


def test_news_marked_only_by_afternoon_brief():
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(_ledger_with_event(), fp.META_DIR / fp.LEDGER_NAME)
    funds = {"KBC": {}, "VTZ": {}}
    ann = fp.META_DIR / fp.ANNOUNCED_NAME
    assert vb._load_fund_period_news(funds, "2027-01-12", "morning")
    assert not ann.exists()                               # sáng: chỉ đọc
    first = vb._load_fund_period_news(funds, "2027-01-12", "afternoon")
    assert first and json.loads(ann.read_text(encoding="utf-8")) == {
        "KBC|ocf|2026-LK3": "2027-01-12"}
    assert vb._load_fund_period_news(funds, "2027-01-12", "afternoon") == first
    assert vb._load_fund_period_news(funds, "2027-01-13", "afternoon") == {}
    assert vb._load_fund_period_news({}, "2027-01-12", "afternoon") == {}


def test_fund_periods_env_switch(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("VNSTOCK_BRIEF_FUND"):
            monkeypatch.delenv(k)
    assert vb._fund_periods_enabled() is True
    for v in ("0", "false", "off", "no"):
        monkeypatch.setenv("VNSTOCK_BRIEF_FUND_PERIODS", v)
        assert vb._fund_periods_enabled() is False
    import inspect
    src = inspect.getsource(vb.collect_context)
    assert 'ctx["risk_today"] and _fund_periods_enabled()' in src
    assert "_load_fund_period_news(" in src


# ── Guard ───────────────────────────────────────────────────────────────────

GOLD_DE = ("- Kỳ BCTC mới — đòn bẩy cao nhất (phi tài chính): VTZ D/E=2.95 (Q2/2026; "
           "kỳ trước năm 2025: 2.81), VJC D/E=2.74 (năm 2025), PET D/E=2.41 (năm 2025); "
           "rời nhóm: HNG D/E=1.20 (Q2/2026; kỳ trước năm 2025: 8.83).")
GOLD_OCF = ("- Kỳ BCTC mới — Op.CF thấp nhất: KBC Op.CF=-16,510 tỷ (BĐS · lũy kế 3 quý "
            "2026; kỳ trước năm 2025: -17,344 tỷ), NVL Op.CF=-6,145 tỷ (BĐS · năm 2025). "
            "Lưu ý: Op.CF âm của mã (BĐS) chủ yếu do tích lũy quỹ đất/hàng tồn kho dự án "
            "— vốn lưu động, KHÔNG phải lỗ HĐKD; soi thêm D/E và nợ vay.")


def _ev(period, prev_period, prev_value):
    return {"period": period, "prev_period": prev_period, "prev_value": prev_value,
            "first_seen": "2026-10-03"}


def _pctx(**over):
    funds = {
        "VTZ": {"de": 2.95, "de_period": "2026-Q2"}, "VJC": {"de": 2.74, "de_period": "2025"},
        "PET": {"de": 2.41, "de_period": "2025"},
        "KBC": {"de": 1.1, "de_period": "2025", "ocf": -16510, "ocf_period": "2026-LK3"},
        "NVL": {"ocf": -6145, "ocf_period": "2025"},
        "HNG": {"de": 1.2, "de_period": "2026-Q2"},
        "EIB": {"de": 9.0, "de_period": "2026-Q2"}, "SSI": {"de": 2.0},
    }
    news = {"VTZ": {"de": _ev("2026-Q2", "2025", 2.81)},
            "KBC": {"ocf": _ev("2026-LK3", "2025", -17344.0)},
            "HNG": {"de": _ev("2026-Q2", "2025", 8.83)},
            "EIB": {"de": _ev("2026-Q2", "2025", 12.0)}}         # ngân hàng: bị loại
    return _ctx_0510(**{"vn30_fundamentals": funds, "fund_period_news": news, **over})


def test_period_lines_golden():
    assert _risk_period_lines(_pctx()) == [GOLD_DE, GOLD_OCF]
    assert _RISK_PERIOD_PREFIX in _RISK_LINE_PREFIXES


def test_full_chain_appends_after_exposure_and_is_idempotent():
    out = vb.apply_brief_guards(RAW_0510, _pctx())
    sec = _section(out)
    assert sec[-2:] == [GOLD_DE, GOLD_OCF] and len(sec) == 4     # P1 + R + 2 dòng kỳ
    assert vb.apply_brief_guards(out, _pctx()) == out


def test_legacy_mode_ignores_period_news():
    for c in (_pctx(risk_today=False), {k: v for k, v in _pctx().items()
                                        if k != "risk_today"}):
        c["vn30_fundamentals"] = _ctx_0510()["vn30_fundamentals"]
        assert _section(vb.apply_brief_guards(RAW_0510, c)) == LEGACY_05_10


def test_legacy_canonical_lines_unchanged_by_refactor():
    ctx = _ctx_0510(risk_today=False)
    assert _canonical_risk_lines(ctx) == LEGACY_05_10[2:]
    vals = {"A": 1.6, "B": 3.0, "C": 1.6, "D": 0.4, "E": 2.0}
    assert _risk_extremes(vals, "de") == [("B", 3.0), ("E", 2.0), ("A", 1.6)]
    assert _risk_extremes({"A": -1, "B": 5, "C": -9, "D": -1}, "ocf") == [("C", -9), ("A", -1)]
    assert _risk_extremes({"A": True, "B": None}, "de") == []


@pytest.mark.parametrize("news,expect", [
    ({}, []),
    # mã có kỳ mới nhưng KHÔNG chạm bảng (không trong bảng, không rời bảng) ⇒ im
    ({"KBC": {"de": _ev("2025", "2024", 1.0)}}, []),
    # kỳ trong sổ LỆCH kỳ của số đang dùng ⇒ im (dấu sổ/parquet không cùng lượt)
    ({"VTZ": {"de": _ev("2026-Q3", "2026-Q2", 2.81)}}, []),
    # chỉ Op.CF có kỳ mới ⇒ chỉ dòng Op.CF
    ({"KBC": {"ocf": _ev("2026-LK3", "2025", -17344.0)}}, [GOLD_OCF]),
])
def test_period_lines_trigger_rules(news, expect):
    assert _risk_period_lines(_pctx(fund_period_news=news)) == expect


def test_period_lines_off_when_mode_off_or_no_funds():
    assert _risk_period_lines(_pctx(risk_today=False)) == []
    assert _risk_period_lines(_pctx(vn30_fundamentals={})) == []


def test_period_lines_empty_table_and_leaving_only():
    funds = {"HNG": {"de": 1.2, "de_period": "2026-Q2"}, "PET": {"de": 1.3, "de_period": "2025"}}
    ctx = _pctx(vn30_fundamentals=funds, fund_period_news={"HNG": {"de": _ev(
        "2026-Q2", "2025", 8.83)}})
    assert _risk_period_lines(ctx) == [
        "- Kỳ BCTC mới — đòn bẩy cao nhất (phi tài chính): không còn mã D/E ≥ 1.50; "
        "rời nhóm: HNG D/E=1.20 (Q2/2026; kỳ trước năm 2025: 8.83)."]


def test_period_lines_with_fallback_and_insert():
    quiet = _pctx(portfolio=[], open_recs=[], upcoming_events=[])
    assert _section(vb.apply_brief_guards(RAW_0510, quiet)) == [
        _RISK_FALLBACK_LINE, GOLD_DE, GOLD_OCF]
    no_sec = RAW_0510.split("## ⚠️ Rủi ro cần lưu ý")[0] + "## 📅 Sự kiện sắp tới\n- x\n"
    out = enforce_risk_today(no_sec, quiet)
    lines = out.splitlines()
    i = lines.index("## ⚠️ Rủi ro cần lưu ý")
    assert lines[i + 1:i + 3] == [GOLD_DE, GOLD_OCF]


def test_prompt_block_lists_period_lines():
    block = vb._risk_today_block(_pctx())
    assert GOLD_DE in block and GOLD_OCF in block


def test_pack_roundtrip_carries_period_news(tmp_path):
    from vnstock_brief_pack import PACK_VERSION, read_pack, write_pack
    ctx = _pctx()
    p = write_pack({"version": PACK_VERSION, "prompt": "x", "ctx": ctx}, tmp_path / "p.json")
    back = read_pack(p)["ctx"]
    assert vb.apply_brief_guards(RAW_0510, back) == vb.apply_brief_guards(RAW_0510, ctx)


def test_summary_cli_lines():
    assert fp.summary({}, {})[1].startswith("(chưa có")
    lines = fp.summary(_ledger_with_event(), {"KBC|ocf|2026-LK3": "2027-01-12"}, "2027-01-12")
    assert "  ocf: 1 mã — lũy kế 3 quý 2026 ×1" in lines
    assert lines[-1] == ("  KBC ocf: năm 2025 → lũy kế 3 quý 2026 (thấy 2027-01-09; "
                         "đã xét phiên 2027-01-12)")
