"""Định dạng/tô màu bảng ngành + sparkline — đồ tách khỏi `market_tab` (12/08).

Cả 6 hàm này trước nằm trong hàm render 2.544 dòng nên CHƯA TỪNG có test. Khi
kéo ra, đối chiếu vi phân với bản gốc (1.480 phép so sánh cho bảng, 24 cho
sparkline, so cả KIỂU NGOẠI LỆ) — 0 khác biệt. Test dưới đây chốt lại hành vi
đó để lần sau ai sửa là biết ngay.

Trọng tâm là các bất biến DỄ HỎNG ÂM THẦM:
* thiếu dữ liệu phải ra "—", không được ra 0 (0 là một con số có nghĩa);
* thang màu phải chịu được dải phẳng (chia 0) — chỗ bản drill-down từng thiếu
  chốt chặn mà bản bảng tổng lại có;
* chữ trên nền đậm phải đổi sang trắng, nếu không là không đọc nổi.
"""


import pytest

from dashboard.market_table_format import (
    AMP_COLS,
    FREE_VOL_COLS,
    NET_BS_COLS,
    NN_COLS,
    amp_color,
    color_val,
    fmt,
    fvol_colors,
    scale_range,
)
from dashboard.sparkline import sparkline_svg


# ── scale_range: chốt chặn chia 0 ───────────────────────────────────────────

class TestScaleRange:

    def test_normal_range(self):
        assert scale_range([1, 5, 3]) == (1, 5, 4)

    def test_empty_never_returns_zero_range(self):
        """Rỗng → (0, 1, 1): range 0 sẽ làm mọi hàm màu chia 0."""
        assert scale_range([]) == (0, 1, 1)
        assert scale_range(None) == (0, 1, 1)

    def test_flat_series_gets_range_one(self):
        """Mọi ngành cùng một giá trị là ca THẬT (ngành 1 mã), không phải giả
        định — đây chính là chỗ bản drill-down cũ thiếu chốt và chia 0."""
        vmin, vmax, vrange = scale_range([7.0, 7.0, 7.0])
        assert (vmin, vmax) == (7.0, 7.0)
        assert vrange == 1

    def test_ignores_none_and_nan(self):
        assert scale_range([None, 2.0, float("nan"), 6.0]) == (2.0, 6.0, 4.0)

    def test_flat_scale_does_not_crash_the_color_ramps(self):
        vmin, _, vrange = scale_range([3.3, 3.3])
        assert amp_color(3.3, vmin, vrange).startswith("rgb(")
        assert fvol_colors(3.3, vmin, vrange)[0].startswith("rgb(")


# ── Thang màu ───────────────────────────────────────────────────────────────

class TestAmpColor:

    def test_low_end_is_green(self):
        r, g, b = _rgb(amp_color(0, 0, 10))
        assert (r, g, b) == (16, 185, 129)

    def test_high_end_is_red(self):
        assert _rgb(amp_color(10, 0, 10)) == (239, 68, 68)

    def test_midpoint_is_amber(self):
        assert _rgb(amp_color(5, 0, 10)) == (245, 158, 11)

    @pytest.mark.parametrize("val", [-100, 1e9])
    def test_out_of_scale_values_are_clamped(self, val):
        """Giá trị ngoài thang (ngành mới, data lỗi) phải kẹp về đầu/cuối
        gradient chứ không sinh mã màu vô nghĩa như rgb(-800,…)."""
        r, g, b = _rgb(amp_color(val, 0, 10))
        assert all(0 <= c <= 255 for c in (r, g, b))

    def test_same_value_different_scale_gives_different_color(self):
        """Bảng tổng và drill-down dùng CHUNG hàm này với hai thang khác nhau —
        trước đây là hai bản chép y hệt, chờ ngày trôi khỏi nhau."""
        assert amp_color(5, 0, 10) != amp_color(5, 0, 100)


class TestFvolColors:

    def test_returns_background_and_text(self):
        bg, text = fvol_colors(0, 0, 10)
        assert bg.startswith("rgb(")
        assert text == "#111827"

    def test_dark_background_flips_text_to_white(self):
        """Nền đậm mà chữ vẫn đen là ô không đọc được."""
        assert fvol_colors(10, 0, 10)[1] == "#ffffff"

    def test_threshold_is_at_35_percent(self):
        assert fvol_colors(3.4, 0, 10)[1] == "#111827"
        assert fvol_colors(3.6, 0, 10)[1] == "#ffffff"


def _rgb(css: str) -> tuple:
    return tuple(int(x) for x in css[4:-1].split(","))


# ── color_val ───────────────────────────────────────────────────────────────

class TestColorVal:

    @pytest.mark.parametrize("col", ["Giá 1T %", "NN 1M (tỷ)", "Net BS 3M", "AVG 5-10 %"])
    def test_sign_columns_are_green_red_gray(self, col):
        assert color_val(1.0, col) == "#10b981"
        assert color_val(-1.0, col) == "#ef4444"
        assert color_val(0.0, col) == "#9ca3af"

    def test_missing_value_is_gray(self):
        assert color_val(None, "Giá 1T %") == "#4b5563"
        assert color_val(float("nan"), "Giá 1T %") == "#4b5563"

    def test_vol_ratio_thresholds(self):
        assert color_val(110.1, "Vol 5/20 %") == "#10b981"
        assert color_val(89.9, "Vol 5/20 %") == "#ef4444"
        assert color_val(100, "Vol 5/20 %") == "#e5e7eb"

    def test_free_vol_columns_defer_to_cell_heatmap(self):
        """Cột này tô NỀN riêng bằng fvol_colors nên màu chữ phải trung tính."""
        for col in FREE_VOL_COLS:
            assert color_val(5.0, col) == "#e5e7eb"

    def test_amp_columns_use_the_passed_scale(self):
        for col in AMP_COLS:
            assert color_val(0, col, 0, 10) == amp_color(0, 0, 10)

    def test_unknown_column_gets_default(self):
        assert color_val(123, "Cột lạ") == "#e5e7eb"


# ── fmt ─────────────────────────────────────────────────────────────────────

class TestFmt:

    def test_missing_is_dash_not_zero(self):
        """0 là một con số CÓ NGHĨA (đứng yên), khác hẳn 'không có dữ liệu'."""
        assert fmt(None, "Giá 1T %") == "—"
        assert fmt(float("nan"), "Giá 1T %") == "—"
        assert fmt(0.0, "Giá 1T %") == "0.0%"

    def test_text_column_passes_through(self):
        assert fmt("Ngân hàng", "Ngành") == "Ngân hàng"

    def test_positive_percent_gets_explicit_plus(self):
        assert fmt(2.53, "Giá 1M %") == "+2.5%"
        assert fmt(-2.53, "Giá 1M %") == "-2.5%"

    def test_en_number_convention(self):
        """CLAUDE.md: phẩy nghìn, chấm thập phân."""
        assert fmt(1234.5, "NN 1T (tỷ)") == "+1,234.5"
        assert fmt(1234567.0, "Vốn hoá (tỷ)") == "1,234,567"

    def test_net_bs_carries_million_suffix(self):
        for col in NET_BS_COLS:
            assert fmt(12.34, col) == "+12.3M"

    def test_nn_columns_have_no_suffix(self):
        for col in NN_COLS:
            assert fmt(12.34, col).endswith("12.3")

    def test_free_vol_keeps_two_decimals(self):
        assert fmt(1.234, "Vol 5/Free %") == "1.23%"

    def test_amp_keeps_one_decimal(self):
        assert fmt(4.26, "Biên 1M (%)") == "4.3%"

    def test_unknown_column_drops_trailing_zero(self):
        assert fmt(7.0, "Số mã") == "7"
        assert fmt(7.5, "Số mã") == "7.5"

    def test_unconvertible_value_falls_back_to_str(self):
        assert fmt([1, 2], "Số mã") == "[1, 2]"


# ── sparkline ───────────────────────────────────────────────────────────────

class TestSparkline:

    def test_too_few_points_renders_a_dash(self):
        """1 điểm không vẽ được xu hướng — vẽ đường giả còn tệ hơn không vẽ."""
        assert "—" in sparkline_svg([1.0])
        assert "<svg" not in sparkline_svg([])

    def test_nan_and_none_are_dropped(self):
        assert "—" in sparkline_svg([None, float("nan")])

    def test_positive_ending_is_green(self):
        svg = sparkline_svg([-1.0, 0.0, 2.5])
        assert "#10b981" in svg and "#ef4444" not in svg

    def test_negative_ending_is_red(self):
        svg = sparkline_svg([1.0, 0.0, -2.5])
        assert "#ef4444" in svg and "#10b981" not in svg

    def test_label_shows_last_value_with_sign(self):
        assert ">+2.5%<" in sparkline_svg([0.0, 2.5])
        assert ">-2.5%<" in sparkline_svg([0.0, -2.5])

    def test_flat_series_does_not_divide_by_zero(self):
        assert "<svg" in sparkline_svg([3.0, 3.0, 3.0])

    def test_points_stay_inside_the_box(self):
        vals = [-8.0, 12.0, -3.0, 5.0, 0.0]
        svg = sparkline_svg(vals, width=80, height=28)
        poly = svg.split('<polyline points="')[1].split('"')[0]
        for pair in poly.split():
            x, y = (float(v) for v in pair.split(","))
            assert 0 <= x <= 80
            assert 0 <= y <= 28

    def test_zero_line_is_clipped_to_the_box(self):
        """Toàn số dương/âm thì đường 0 nằm ngoài dải — phải kẹp lại, không thì
        SVG vẽ vạch ra ngoài khung và đè lên hàng bên cạnh."""
        for vals in ([1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]):
            line = sparkline_svg(vals).split('<line x1="0" y1="')[1].split('"')[0]
            assert 2 <= float(line) <= 26

    def test_respects_custom_size(self):
        assert 'width="120" height="40"' in sparkline_svg([1.0, 2.0], 120, 40)

    def test_does_not_mutate_input(self):
        vals = [1.0, None, 2.0]
        sparkline_svg(vals)
        assert vals == [1.0, None, 2.0]

    def test_nan_in_the_middle_does_not_leak_into_coordinates(self):
        """NaN lọt vào toạ độ là SVG câm (trình duyệt bỏ cả đường), không báo lỗi."""
        svg = sparkline_svg([1.0, float("nan"), 3.0])
        assert "nan" not in svg.lower()
        assert ">+3.0%<" in svg          # điểm cuối vẫn là 3.0, NaN chỉ bị bỏ
