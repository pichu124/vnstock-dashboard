"""Tests for vnstock_fundamental_updater._annual_operating_cf.

VCI's cash_flow spans many fiscal years; the naive "latest row" picked the
in-progress current year (FPT 2026 Q1 working-capital outflow → -2,847.8 tỷ),
and naive quarterly-summing added several years (→ +9,795 tỷ). The correct value
is the operating cash flow of the most recent COMPLETE fiscal year.
"""

from __future__ import annotations

import importlib.util
from datetime import date

import pandas as pd
import pytest

from vnstock_fundamental_updater import _annual_operating_cf


_OCF = "Net cash inflows/(outflows) from operating activities"
_CUR = date.today().year


def test_annual_uses_last_complete_year():
    df = pd.DataFrame({
        "report_period": [str(_CUR - 1), str(_CUR - 2), str(_CUR - 3)],
        _OCF: [5000e9, 4000e9, 3000e9],
    })
    assert _annual_operating_cf(df) == pytest.approx(5000e9)   # last year, not a sum


def test_excludes_in_progress_current_year():
    # Current year is a partial, negative row (FPT-like) → must be excluded;
    # return the last COMPLETE year, which is positive.
    df = pd.DataFrame({
        "report_period": [str(_CUR), str(_CUR - 1), str(_CUR - 2)],
        _OCF: [-2847.8e9, 5000e9, 4500e9],
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx(5000e9)
    assert val > 0


def test_quarterly_sums_last_complete_year_only():
    # Quarterly rows: 4 quarters of last complete year + 1 partial current-year
    # quarter. Sum only the complete year's 4 quarters; exclude the partial one.
    df = pd.DataFrame({
        "report_period": [f"{_CUR}-Q1",
                          f"{_CUR-1}-Q4", f"{_CUR-1}-Q3", f"{_CUR-1}-Q2", f"{_CUR-1}-Q1"],
        _OCF: [-2847.8e9, 4000e9, 1500e9, 1000e9, -500e9],
    })
    val = _annual_operating_cf(df)
    assert val == pytest.approx((4000 + 1500 + 1000 - 500) * 1e9)   # = 6000e9
    assert val > 0


def test_mixed_annual_and_quarterly_prefers_annual_row():
    # FPT's real shape: a pure-year annual row ("2025") PLUS the 4 quarterly rows
    # of that year PLUS a partial current-year quarter. Must return the annual
    # row only — not annual + 4 quarters (≈ 2×), and not the partial quarter.
    df = pd.DataFrame({
        "report_period": [f"{_CUR}-Q1",
                          f"{_CUR-1}-Q4", f"{_CUR-1}-Q3", f"{_CUR-1}-Q2", f"{_CUR-1}-Q1",
                          str(_CUR - 1)],
        _OCF: [-2847.8e9, 4108.5e9, 4344.0e9, 4190.5e9, -2506.9e9, 10136.0e9],
    })
    assert _annual_operating_cf(df) == pytest.approx(10136.0e9)


def test_no_parseable_year_falls_back_to_latest_row():
    # Integer period-ids (no year) → can't determine the year → latest row.
    df = pd.DataFrame({
        "report_period": [3, 2, 1],
        _OCF: [7000e9, 4000e9, 3000e9],
    })
    assert _annual_operating_cf(df) == pytest.approx(7000e9)


def test_empty_returns_none():
    assert _annual_operating_cf(pd.DataFrame()) is None


# ── update() --workers: song song phải cho KẾT QUẢ Y HỆT tuần tự ─────────────
# (fetch monkeypatched — không mạng; file ghi vào tmp_path qua FUND_PATH)


def _run_update(tmp_path, monkeypatch, workers):
    import vnstock_fundamental_updater as fu

    monkeypatch.setattr(fu, "FUND_PATH", tmp_path / f"fund_w{workers}.parquet")
    # _save còn chụp ảnh tháng vào FUND_HISTORY_DIR — không chuyển hướng thì test
    # ghi AAA/BBB/CCC giả vào kho THẬT, và "bản đầu tháng thắng" khoá luôn ảnh
    # thật của tháng đó (05/10: kho có fundamentals-2026-10.parquet 3 dòng giả).
    monkeypatch.setattr(fu, "FUND_HISTORY_DIR", tmp_path / "hist")
    monkeypatch.setattr(fu, "_fetch_ratios",
                        lambda t: ({"pe": 10.0, "roe": 15.0} if t != "EMPTY" else {}))
    monkeypatch.setattr(fu, "_fetch_cash_flow",
                        lambda t: {"operating_cf": 1234.0})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: 1.5)
    tickers = ["AAA", "BBB", "CCC", "DDD", "EMPTY", "FPT", "VCB", "HPG"]
    df = fu.update(tickers=tickers, force=True, delay=0.0,
                   batch_save=3, workers=workers)
    return df.sort_values("ticker").reset_index(drop=True)


def test_update_parallel_matches_sequential(tmp_path, monkeypatch):
    seq = _run_update(tmp_path, monkeypatch, workers=1)
    par = _run_update(tmp_path, monkeypatch, workers=4)
    # Cùng bộ mã, cùng giá trị — thứ tự hoàn thành khác nhau không được đổi data
    assert list(seq["ticker"]) == list(par["ticker"])
    for col in ("pe", "roe", "operating_cf", "debt_to_equity"):
        pd.testing.assert_series_equal(seq[col], par[col], check_names=False)
    # 7 mã có data + 1 placeholder EMPTY (chưa từng có data → NaN row vẫn ghi)
    assert len(seq) == 8
    assert seq.loc[seq["ticker"] == "EMPTY", "pe"].isna().all()
    assert seq.loc[seq["ticker"] == "FPT", "operating_cf"].iloc[0] == 1234.0
    # ảnh chụp tháng rơi vào tmp, không phải kho thật
    assert list((tmp_path / "hist").glob("fundamentals-*.parquet"))


def test_update_parallel_reports_worker_errors(tmp_path, monkeypatch, capsys):
    import vnstock_fundamental_updater as fu

    monkeypatch.setattr(fu, "FUND_PATH", tmp_path / "fund_err.parquet")
    monkeypatch.setattr(fu, "FUND_HISTORY_DIR", tmp_path / "hist")

    def _boom(t):
        if t == "BAD":
            raise RuntimeError("api nổ")
        return {"pe": 9.0, "roe": 12.0}

    monkeypatch.setattr(fu, "_fetch_ratios", _boom)
    monkeypatch.setattr(fu, "_fetch_cash_flow", lambda t: {})
    monkeypatch.setattr(fu, "_fetch_debt_to_equity", lambda t: None)
    df = fu.update(tickers=["OKA", "BAD", "OKB"], force=True, delay=0.0,
                   workers=3)
    # Mã lỗi KHÔNG chặn mã khác; lỗi được đếm, 2 mã OK vẫn vào parquet
    assert sorted(df["ticker"]) == ["OKA", "OKB"]


# ── Thế hệ 6: Fundamental().equity(t).<bctc>/ratio (qua mặt tiền get_vnstock) ──

def _long(rows):
    """BCTC dạng DÀI của thế hệ 6 (hồ sơ v5): period, id, name, order, level, unit, value, line_code."""
    return pd.DataFrame([
        {"period": p, "id": i, "name": n, "order": k, "level": 1, "unit": "VND",
         "value": v, "line_code": i}
        for k, (p, i, n, v) in enumerate(rows)])


class _Gen6Fin:
    """`Fundamental().equity(t)` giả: ghi lại tham số, tham số lạ ⇒ InputError như thế hệ 6."""
    _OK = {"ratio": {"period", "year"},
           "cash_flow": {"company_type", "period", "lang", "drop_empty", "format"},
           "balance_sheet": {"company_type", "period", "lang", "drop_empty", "format"}}

    def __init__(self, **frames):
        self.frames, self.calls = frames, []

    def __getattr__(self, name):
        if name not in self._OK:
            raise AttributeError(name)

        def call(**kw):
            from vnstock.errors import InputError
            self.calls.append((name, kw))
            bad = set(kw) - self._OK[name]
            if bad or ("lang" in kw and name == "ratio"):
                raise InputError(f"tham số lạ {bad}", code="VNSTOCK_INPUT_PARAM")
            v = self.frames[name]
            if isinstance(v, Exception):
                raise v
            return v
        return call


def _patch_fin(monkeypatch, fin):
    import vnstock_auth
    monkeypatch.setattr(vnstock_auth, "get_vnstock",
                        lambda t, *a, **k: type("S", (), {"finance": fin})())


_needs_vnstock = pytest.mark.skipif(importlib.util.find_spec("vnstock") is None,
                                    reason="cần vnstock thế hệ 6 (CI cài tối thiểu, không có vnstock)")


@_needs_vnstock
def test_gen6_ratio_columns_map_to_legacy_fields(monkeypatch):
    import vnstock_fundamental_updater as fu
    fin = _Gen6Fin(ratio=pd.DataFrame([
        {"year": 2024, "quarter": None, "pe": 10.0, "pb": 1.5, "roe": 15.0, "roa": 2.0,
         "eps": 3000.0, "net_margin": 10.0, "gross_margin": 30.0,
         "liabilities_to_equity": 2.0, "debt_to_assets": 0.6},
        {"year": 2025, "quarter": None, "pe": 12.0, "pb": 1.8, "roe": 18.0, "roa": 1.7,
         "eps": 3500.0, "net_margin": 1.5, "gross_margin": 32.0,
         "liabilities_to_equity": 2.81, "debt_to_assets": 0.65},
    ]))
    _patch_fin(monkeypatch, fin)

    out = fu._fetch_ratios("FPT")

    assert fin.calls == [("ratio", {"period": "year"})]
    assert out == {"pe": 12.0, "pb": 1.8, "roe": 18.0, "roa": 1.7, "eps": 3500.0,
                   "net_margin": 1.5, "gross_margin": 32.0, "debt_ratio": 0.65,
                   "debt_to_equity": 2.81, "de_period": "2025"}


@_needs_vnstock
def test_gen6_long_cash_flow_gives_last_complete_year(monkeypatch):
    import vnstock_fundamental_updater as fu
    y1, y2 = _CUR - 2, _CUR - 1
    fin = _Gen6Fin(cash_flow=_long([
        (str(y1), "CF_NET_OPERATING", "Net cash flows from operating activities", 5e12),
        (str(y1), "CF_NET_INVESTING", "Net cash flows from investing activities", -1e12),
        (str(y2), "CF_NET_OPERATING", "Net cash flows from operating activities", 7.25e12),
        (str(y2), "CF_NET_INVESTING", "Net cash flows from investing activities", -2e12),
    ]))
    _patch_fin(monkeypatch, fin)

    assert fu._fetch_cash_flow("FPT") == {"operating_cf": 7250.0, "ocf_period": str(y2)}
    assert fin.calls == [("cash_flow", {"period": "year", "lang": "en"})]


@_needs_vnstock
def test_gen6_long_balance_sheet_gives_debt_to_equity(monkeypatch):
    import vnstock_fundamental_updater as fu
    fin = _Gen6Fin(balance_sheet=_long([
        ("2024", "BS_TOTAL_LIABILITIES", "Total liabilities", 800.0),
        ("2024", "BS_OWNERS_EQUITY", "Owners' equity", 100.0),
        ("2025", "BS_TOTAL_LIABILITIES", "Total liabilities", 1_120.0),
        ("2025", "BS_OWNERS_EQUITY", "Owners' equity", 100.0),
        # dòng tổng chứa CẢ "total liabilities" lẫn "owner…equity" — phải giữ thứ tự taxonomy
        ("2025", "BS_TOTAL_RESOURCES", "Total liabilities and owners' equity", 1_220.0),
    ]))
    _patch_fin(monkeypatch, fin)

    assert fu._fetch_debt_to_equity("VCB") == 11.2
    assert fin.calls == [("balance_sheet", {"period": "year", "lang": "en"})]


@_needs_vnstock
def test_gen6_rate_limit_reaches_the_retry_wrapper(monkeypatch):
    """RateLimitError không được nuốt thành 'statement rỗng' — `_fetch_one` bọc
    `call_with_rate_limit_retry` cần thấy nó để chờ rồi thử lại."""
    from vnstock.errors import RateLimitError
    import vnstock_fundamental_updater as fu
    _patch_fin(monkeypatch, _Gen6Fin(ratio=RateLimitError("quá trần", code="VNSTOCK_RATE_LIMIT")))
    with pytest.raises(RateLimitError):
        fu._fetch_ratios("FPT")


@_needs_vnstock
def test_gen6_source_error_is_an_empty_statement(monkeypatch):
    from vnstock.errors import UnsupportedError
    import vnstock_fundamental_updater as fu
    _patch_fin(monkeypatch, _Gen6Fin(
        cash_flow=UnsupportedError("không đọc", code="VNSTOCK_ROUTE_UNSUPPORTED")))
    assert fu._fetch_cash_flow("FPT") == {}
