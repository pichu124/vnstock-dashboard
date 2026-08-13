"""Nhóm ngành tuỳ biến ("Họ VIN", "Họ M") phải mở được ở cấp MÃ.

User báo 13/08: bảng ngành hiện đủ "Họ VIN" (4 mã) và "Họ M" (7 mã) với đầy đủ
số liệu, nhưng bấm vào để xem chi tiết thì ra **"Không có dữ liệu ticker cho
ngành Họ M"**. Mọi ngành chuẩn đều mở bình thường.

Nguyên nhân (đo bằng code, không đoán): `vnstock_runner` gom bảng cấp NGÀNH
theo nhóm tuỳ biến, nhưng cố ý để bảng cấp MÃ giữ `Ngành` = ngành GỐC — comment
tại chỗ ghi rõ lý do: brief dựa vào ngành gốc để nhận diện bất động sản / tài
chính, đổi đi là hỏng chỗ khác. Hệ quả: `df[df["Ngành"] == "Họ VIN"]` LUÔN rỗng
vì không mã nào mang nhãn đó.

Lỗi CÓ TỪ TRƯỚC đợt tách file 12-13/08 (dòng lọc có từ lần tách tab gốc, PR
#15) — nhóm tuỳ biến được thêm cho đường bảng-ngành + brief, không ai nối vào
đường drill-down.

Vá bằng `vnstock_sectors.rows_for_sector` dùng CHUNG cho cả hai chỗ lọc mã
theo ngành, để không đẻ ra hai bản tự chế rồi trôi khỏi nhau.
"""
import pandas as pd
import pytest

from vnstock_sectors import (
    CUSTOM_SECTOR_ORDER,
    SECTOR_ORDER,
    rows_for_sector,
    tickers_in_group,
)


@pytest.fixture
def tick_df():
    """Bảng MÃ đúng như runner sinh ra: `Ngành` là ngành GỐC, kể cả với mã
    thuộc nhóm tuỳ biến (VIC/VHM/VRE = Bất động sản, GEX = Đa ngành…)."""
    return pd.DataFrame({
        "Mã": ["VIC", "VHM", "VRE", "VPL", "GEX", "EIB", "VCB", "HPG"],
        "Ngành": ["Bất động sản", "Bất động sản", "Bất động sản", "Du lịch & Khách sạn",
                  "Đa ngành", "Ngân hàng", "Ngân hàng", "Thép & Kim loại"],
        "Giá 1M %": [1.0, -2.0, 3.0, 0.5, -1.5, 2.5, 0.8, -3.0],
    })


# ── tickers_in_group ────────────────────────────────────────────────────────

def test_returns_the_family_for_a_custom_group():
    assert tickers_in_group("Họ VIN") == frozenset({"VIC", "VHM", "VRE", "VPL"})


def test_returns_none_for_a_standard_sector():
    """None chứ không phải set rỗng — hai thứ đó khác nhau: rỗng nghĩa là
    'nhóm này không có mã nào', None nghĩa là 'đây không phải nhóm tuỳ biến'."""
    assert tickers_in_group("Ngân hàng") is None
    assert tickers_in_group("Ngành không tồn tại") is None


@pytest.mark.parametrize("label", CUSTOM_SECTOR_ORDER)
def test_every_declared_custom_group_is_resolvable(label):
    """Thêm họ mới vào registry mà quên chỗ khác → đỏ ngay ở đây."""
    fam = tickers_in_group(label)
    assert fam, f"Nhóm '{label}' khai trong registry nhưng tra không ra mã"


# ── rows_for_sector: chính ca user báo ──────────────────────────────────────

def test_custom_group_drilldown_is_not_empty(tick_df):
    """ĐÂY LÀ CA USER BÁO. Trước khi vá, dòng này trả về 0 mã."""
    rows = rows_for_sector(tick_df, "Họ VIN")
    assert not rows.empty, "Bấm vào Họ VIN vẫn ra rỗng — lỗi chưa được vá"
    assert set(rows["Mã"]) == {"VIC", "VHM", "VRE", "VPL"}


def test_custom_group_pulls_across_different_raw_sectors(tick_df):
    """Điểm mấu chốt: 4 mã họ VIN nằm ở HAI ngành gốc khác nhau (Bất động sản
    và Du lịch). Lọc theo cột `Ngành` không thể nào gom đủ."""
    rows = rows_for_sector(tick_df, "Họ VIN")
    assert set(rows["Ngành"]) == {"Bất động sản", "Du lịch & Khách sạn"}
    assert len(rows) == 4


def test_ho_m_pulls_only_its_own_members(tick_df):
    rows = rows_for_sector(tick_df, "Họ M")
    assert set(rows["Mã"]) == {"GEX", "EIB"}          # 2 mã có trong bảng mẫu
    assert "VCB" not in set(rows["Mã"])                # cùng ngành Ngân hàng với EIB


def test_standard_sector_still_filters_by_column(tick_df):
    """Không được làm hỏng đường cũ: ngành chuẩn vẫn lọc theo cột `Ngành`."""
    rows = rows_for_sector(tick_df, "Ngân hàng")
    assert set(rows["Mã"]) == {"EIB", "VCB"}


def test_unknown_label_returns_empty_not_error(tick_df):
    assert rows_for_sector(tick_df, "Ngành trên trời").empty


def test_does_not_mutate_the_input(tick_df):
    before = tick_df.copy()
    rows_for_sector(tick_df, "Họ VIN")
    pd.testing.assert_frame_equal(tick_df, before)


def test_custom_group_never_collides_with_a_standard_sector_name():
    """Nếu ai đặt tên nhóm tuỳ biến trùng một ngành chuẩn thì `rows_for_sector`
    sẽ luôn chọn nhánh nhóm tuỳ biến và ngành chuẩn kia mất hút."""
    assert not (set(CUSTOM_SECTOR_ORDER) & set(SECTOR_ORDER))


# ── Hai chỗ gọi phải dùng CHUNG helper, không tự chế lại ────────────────────

@pytest.mark.parametrize("path", [
    "dashboard/market_tab.py",
    "dashboard/market_commentary.py",
])
def test_no_call_site_filters_tickers_by_raw_sector_column(path):
    """Lưới chặn tái phát: chỗ nào lọc bảng MÃ theo nhãn ngành cũng phải đi qua
    `rows_for_sector`. Tự viết `df[df["Ngành"] == label]` là lặp lại đúng lỗi
    này cho nhóm tuỳ biến tiếp theo."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
    assert 'tick_data["Ngành"] ==' not in src, (
        f"{path}: lọc mã theo cột `Ngành` — nhóm tuỳ biến sẽ ra rỗng. "
        "Dùng `vnstock_sectors.rows_for_sector`.")
    assert "rows_for_sector" in src
