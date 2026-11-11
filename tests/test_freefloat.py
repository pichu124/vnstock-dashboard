"""Freefloat trên vnstock thế hệ 6: `Reference().company(t).shareholders()` + `.listing()`."""
from __future__ import annotations

import pandas as pd
import pytest

import vnstock_freefloat as ff


def _patch_company(monkeypatch, *, shareholders=None, listing=None, sh_exc=None, li_exc=None):
    import vnstock

    class _Company:
        def __init__(self, t):
            self.t = t

        def shareholders(self):
            if sh_exc is not None:
                raise sh_exc
            return shareholders

        def listing(self):
            if li_exc is not None:
                raise li_exc
            return listing

    class _Ref:
        def __init__(self, *a, **k):
            pass

        def company(self, t):
            return _Company(t)

    monkeypatch.setattr(vnstock, "Reference", _Ref)


_SH = pd.DataFrame({
    "symbol": ["FPT"] * 3,
    "name": ["A", "B", "C"],
    "shareholder_type": ["individual", "institution", "institution"],
    "total_shares": [100, 50, 30],
    "rate": [0.07, 0.065, 0.055],       # hồ sơ v5: PHÂN SỐ (ownership_percent × 0.01)
    "date": ["2026-06-30"] * 3,
})


def test_freefloat_from_listing_shares(monkeypatch):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    _patch_company(monkeypatch, shareholders=_SH, listing=pd.DataFrame({
        "symbol": ["FPT"], "exchange": ["HOSE"], "listed_shares": [1_500.0],
        "outstanding_shares": [1_000.0], "treasury_shares": [0.0],
        "free_float_shares": [823.0], "free_float_percent": [82.3],
    }))

    out = ff.fetch_freefloat_for_ticker("FPT")

    assert out["freefloat_pct"] == 82.3
    assert out["shareholders_count"] == 3


def test_freefloat_from_listing_percent_when_shares_missing(monkeypatch):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    _patch_company(monkeypatch, shareholders=_SH, listing=pd.DataFrame({
        "symbol": ["FPT"], "outstanding_shares": [None], "free_float_shares": [None],
        "free_float_percent": [64.0],
    }))
    assert ff.fetch_freefloat_for_ticker("FPT")["freefloat_pct"] == 64.0


def test_freefloat_falls_back_to_major_holders_rate(monkeypatch):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    from vnstock.errors import UnsupportedError
    _patch_company(monkeypatch, shareholders=_SH,
                   li_exc=UnsupportedError("không đọc", code="VNSTOCK_ROUTE_UNSUPPORTED"))

    out = ff.fetch_freefloat_for_ticker("FPT")

    assert out["freefloat_pct"] == 81.0          # 100 − 100·(0,07 + 0,065 + 0,055)
    assert out["shareholders_count"] == 3


def test_no_shareholders_means_no_row(monkeypatch):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    from vnstock.errors import InputError
    _patch_company(monkeypatch, sh_exc=InputError("Chưa chọn nguồn", code="VNSTOCK_INPUT_SOURCE"))
    assert ff.fetch_freefloat_for_ticker("FPT") is None
    _patch_company(monkeypatch, shareholders=pd.DataFrame())
    assert ff.fetch_freefloat_for_ticker("FPT") is None


def test_freefloat_row_fits_the_parquet_schema(monkeypatch, tmp_path):
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    _patch_company(monkeypatch, shareholders=_SH, listing=pd.DataFrame())
    row = ff.fetch_freefloat_for_ticker("FPT")
    upd = ff.FreefloatUpdater(str(tmp_path))
    upd.save(pd.DataFrame([row]))
    assert upd.load_map() == {"FPT": pytest.approx(81.0)}


def test_listing_source_error_writes_no_estimate(monkeypatch):
    """listing() lỗi mạng/hạn mức ⇒ KHÔNG rơi sang ước tính từ cổ đông lớn (ghi đè số công bố cũ)."""
    pytest.importorskip("vnstock")   # CI tối thiểu không cài vnstock thế hệ 6
    from vnstock.errors import RateLimitError
    _patch_company(monkeypatch, shareholders=_SH,
                   li_exc=RateLimitError("vượt giới hạn", code="VNSTOCK_SOURCE_RATE_LIMITED"))
    assert ff.fetch_freefloat_for_ticker("FPT") is None
