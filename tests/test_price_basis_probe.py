"""Lưới cho `scripts/probe_price_basis.py` — phân định KHO lệch cơ sở vs NGUỒN sai.

Hai chẩn đoán đòi cách chữa NGƯỢC NHAU (ghi đè lịch sử kho / cách ly bar hỏng
ở nguồn), nên phán nhầm là sửa nhầm chỗ. Phần fetch cần mạng nên không test
được offline; toàn bộ phép phán nằm ở hàm THUẦN `basis_report` — test ở đây
chấm đúng hàm đó, đúng kiểu tách "logic thuần khỏi I/O" của repo.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import probe_price_basis as ppb  # noqa: E402

BRK = date(2026, 6, 15)


def _df(pairs):
    return pd.DataFrame({"time": [p[0] for p in pairs],
                         "close": [p[1] for p in pairs]})


def _dates(n, start=date(2026, 6, 10)):
    return [start + pd.Timedelta(days=i) for i in range(n)]


def test_warehouse_keeps_the_old_basis_before_the_break():
    """Ca VVS: nguồn LIỀN MẠCH quanh 15/06 (71-72), kho thì 112.5 → 71.21.
    Tỉ lệ kho/nguồn đổi bậc đúng tại ngày vách ⇒ lịch sử kho giữ cơ sở CŨ."""
    d = [date(2026, 6, 11), date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 110.0), (d[1], 112.5), (d[2], 71.21), (d[3], 72.0)])
    src = _df([(d[0], 69.62), (d[1], 71.20), (d[2], 71.21), (d[3], 72.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "warehouse_basis"
    assert rep["ratio_before"] == pytest.approx(1.58, abs=0.01)
    assert rep["ratio_after"] == pytest.approx(1.0, abs=0.01)
    assert rep["shift"] == pytest.approx(1.58, abs=0.01)


def test_source_broken_the_same_way_is_not_a_warehouse_problem():
    """Nguồn cũng gãy y hệt ⇒ kho chép đúng. Ghi đè kho là vô ích — phán nhầm
    ở đây khiến người ta đi sửa sai chỗ."""
    d = [date(2026, 6, 11), date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 110.0), (d[1], 112.5), (d[2], 71.21), (d[3], 72.0)])
    rep = ppb.basis_report(wh, wh.copy(), BRK)
    assert rep["verdict"] == "source_error"
    assert rep["ratio_before"] == pytest.approx(1.0, abs=1e-6)


def test_small_rounding_differences_still_count_as_same_basis():
    """Chênh lệch làm tròn/bước giá (~1%) KHÔNG được đọc thành đổi cơ sở."""
    d = _dates(6)
    wh = _df([(x, 100.0 + i * 0.1) for i, x in enumerate(d)])
    src = _df([(x, (100.0 + i * 0.1) * 1.008) for i, x in enumerate(d)])
    assert ppb.basis_report(wh, src, BRK)["verdict"] == "source_error"


def test_no_overlap_is_reported_not_guessed():
    wh = _df([(date(2026, 1, 5), 10.0)])
    src = _df([(date(2026, 7, 5), 10.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "no_overlap" and rep["n"] == 0


def test_one_sided_window_is_inconclusive_not_a_verdict():
    """Chỉ có bar một phía ngày vách thì KHÔNG đủ để phán — phải nói rõ
    "chưa kết luận" thay vì chọn bừa một trong hai chẩn đoán."""
    d = [date(2026, 6, 11), date(2026, 6, 12)]
    wh = _df([(d[0], 110.0), (d[1], 112.5)])
    src = _df([(d[0], 69.62), (d[1], 71.20)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["verdict"] == "inconclusive"
    assert rep["n_after"] == 0


def test_zero_and_negative_closes_are_dropped_before_dividing():
    """Bar giá 0 (mã nghỉ/giá tham chiếu lỗi) chia ra inf — phải loại trước."""
    d = [date(2026, 6, 12), BRK, date(2026, 6, 16)]
    wh = _df([(d[0], 112.5), (d[1], 0.0), (d[2], 72.0)])
    src = _df([(d[0], 71.20), (d[1], 71.21), (d[2], 72.0)])
    rep = ppb.basis_report(wh, src, BRK)
    assert rep["n"] == 2                      # bar 0 bị loại
    assert rep["verdict"] == "warehouse_basis"
