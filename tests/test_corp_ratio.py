"""Lưới cho `vnstock_corp_ratio` — đọc tỉ lệ quyền từ TIÊU ĐỀ sự kiện.

Module này sinh ra sau một phép kiểm khớp đến 4 chữ số (19/08). Vietstock trả
về cho PET hai sự kiện cùng ngày GDKHQ 09/07 — `20:1` và `5:2` — cộng dồn trên
số cổ phiếu gốc ra hệ số **1.45**, trong khi bộ chữa kho đo ĐỘC LẬP TỪ GIÁ được
**1.4499×**. Lệch 0,007%. Đó là bằng chứng cho cả chẩn đoán lệch cơ sở lẫn LUẬT
GHÉP dùng ở đây.

Lưới canh ba cái bẫy, cả ba đều đủ sức tạo ra một con số sai trông thuyết phục:
  1. Cộng dồn ≠ nhân dây chuyền (1.45 vs 1.47).
  2. "Tỷ lệ 10%" của cổ tức TIỀN MẶT là 10% MỆNH GIÁ, không phải 10% thị giá.
  3. Đọc được MỘT PHẦN sự kiện còn tệ hơn không đọc được gì.
"""
from __future__ import annotations

import pytest

from vnstock_corp_ratio import (
    PAR_VALUE_VND,
    adjusted_price,
    combine,
    parse_event,
)


# ── Ca thật: PET 19/08 ──────────────────────────────────────────────────────

_PET = ["Trả cổ tức  năm 2025  bằng cổ phiếu, tỷ lệ 20:1",
        "Thưởng cổ phiếu, tỷ lệ 5:2"]


def test_pet_matches_the_factor_measured_from_prices():
    """1 + 0.05 + 0.40 = 1.45 — khớp 1.4499× mà bộ chữa đo từ giá."""
    c = combine(_PET)
    assert c["share_ratio"] == pytest.approx(0.45)
    assert 1 + c["share_ratio"] == pytest.approx(1.4499, abs=1e-3)


def test_same_exdate_events_add_up_they_do_not_compound():
    """Nhân dây chuyền ra 1.47 — lệch 1,4%, đủ để sai."""
    c = combine(_PET)
    assert 1 + c["share_ratio"] == pytest.approx(1.45)
    assert 1 + c["share_ratio"] != pytest.approx(1.05 * 1.40)


# ── Đọc từng tiêu đề ────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,ratio", [
    ("Trả cổ tức bằng cổ phiếu, tỷ lệ 20:1", 1 / 20),
    ("Thưởng cổ phiếu, tỷ lệ 5:2", 2 / 5),
    ("Trả Cổ tức bằng Cổ phiếu tỉ lệ 5.0%", 0.05),
    ("THUONG CO PHIEU, TY LE 10:3", 0.3),          # không dấu, chữ hoa
    ("Trả cổ tức bằng cổ phiếu tỷ lệ 100/12", 0.12),
])
def test_stock_ratios(title, ratio):
    assert parse_event(title) == {"kind": "stock",
                                  "share_ratio": pytest.approx(ratio)}


@pytest.mark.parametrize("title,vnd", [
    ("Trả cổ tức năm 2024 bằng tiền, 500 đồng/CP", 500.0),
    ("Trả cổ tức bằng tiền, 1.500 đồng/cổ phiếu", 1500.0),
    ("Trả cổ tức bằng tiền mặt, tỷ lệ 10%", 0.10 * PAR_VALUE_VND),
])
def test_cash_amounts(title, vnd):
    assert parse_event(title) == {"kind": "cash", "cash_vnd": pytest.approx(vnd)}


def test_cash_percent_is_of_par_value_not_of_market_price():
    """Bẫy VN kinh điển: 10% của cổ tức tiền mặt = 1.000đ, không phải 10% thị giá."""
    got = parse_event("Trả cổ tức bằng tiền, tỷ lệ 10%")
    assert got["cash_vnd"] == pytest.approx(1_000.0)


# ── Từ chối khi không chắc ──────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Phát hành thêm cho cổ đông hiện hữu, tỷ lệ 2:1",   # có giá mua
    "Chào bán cổ phiếu ra công chúng, tỷ lệ 10:1",
    "Quyền mua cổ phiếu, tỷ lệ 5:1",
])
def test_rights_issues_are_refused_not_guessed(title):
    """Phát hành có giá mua cần thêm giá phát hành — không suy được từ tiêu đề."""
    assert parse_event(title) is None


@pytest.mark.parametrize("title", [
    "Đại hội cổ đông thường niên 2026",
    "Trả cổ tức bằng cổ phiếu",          # có loại, KHÔNG có tỉ lệ
    "", None, "tỷ lệ 0:0",
])
def test_unreadable_titles_return_none(title):
    assert parse_event(title) is None


def test_partial_parse_is_worse_than_none():
    """Đọc được 1/2 sự kiện thì KHÔNG được gộp — thiếu một vế là ra 1.05 hoặc
    1.40 thay vì 1.45, và cả hai đều trông hợp lý."""
    assert combine([_PET[0], "Đại hội cổ đông thường niên"]) is None


def test_combine_of_nothing_is_none():
    assert combine([]) is None and combine(None) is None


# ── Quy đổi giá tham chiếu ──────────────────────────────────────────────────

def test_vix_reference_price():
    """Ca thật brief 19/08: VIX 13,100 + cổ tức cổ phiếu 5% → 12,476."""
    assert adjusted_price(13_100, ["Trả Cổ tức bằng Cổ phiếu tỉ lệ 5.0%"]) \
        == pytest.approx(12_476, abs=1)


def test_pet_reference_price_uses_both_events():
    assert adjusted_price(29_000, _PET) == pytest.approx(20_000, abs=1)


def test_cash_is_subtracted_before_the_ratio_is_applied():
    """`P_adj = (P − D) / (1 + r)` — trừ tiền TRƯỚC rồi mới chia tỉ lệ."""
    got = adjusted_price(20_000, ["Trả cổ tức bằng tiền, 1.000 đồng/CP",
                                  "Thưởng cổ phiếu, tỷ lệ 10:1"])
    assert got == pytest.approx((20_000 - 1_000) / 1.1)


def test_cash_only_event_just_subtracts():
    assert adjusted_price(20_000, ["Trả cổ tức bằng tiền, 500 đồng/CP"]) \
        == pytest.approx(19_500)


@pytest.mark.parametrize("price", [0, -1, None, "x"])
def test_bad_price_returns_none(price):
    assert adjusted_price(price, _PET) is None


def test_absurd_result_is_refused():
    """Cổ tức tiền mặt lớn hơn cả thị giá ⇒ dữ liệu sai, không trả số âm."""
    assert adjusted_price(400, ["Trả cổ tức bằng tiền, 500 đồng/CP"]) is None


def test_unreadable_events_give_no_number():
    assert adjusted_price(13_100, ["Đại hội cổ đông thường niên"]) is None
