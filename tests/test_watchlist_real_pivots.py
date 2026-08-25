"""
Lưới cho MỐC THẬT của watchlist (pivot 60 phiên) thay cho dải ±3%.

U23 đã bắt được rằng chính repo bịa hộ model: nhãn "hỗ trợ ~X / kháng cự ~Y"
dán lên `giá ×0,97` và `×1,03`. Lúc đó vá bằng cách **gọi đúng tên** ("dải
±3%"). Đây là bước hai: tính mốc THẬT.

⚠️ **Không dùng `vnstock_strategy._ticker_pivots`** dù tên nó nghe đúng việc:
nó trả CHUỖI tiếng Việt đã format, và `round(v, 0)` trên đơn vị nghìn VND —
với GAS ở 83,5 thì bước làm tròn là 1,2%, nhiễu còn lớn hơn khoảng cách tới
mốc. Nó cũng không có sàn khoảng cách/khoảng hở nào. Bản đúng là
`_select_sr_levels` — đã học đủ bài từ các ca nhiễu của đường chỉ số.

Bất biến sống chết: **thà KHÔNG có mốc còn hơn có mốc bịa.** Không đủ bar,
không ứng viên nào qua sàn, đọc kho hỏng ⇒ rơi về dải ±3% với nhãn thành thật,
KHÔNG được bịa một con số.
"""
from __future__ import annotations

import vnstock_brief as vb
from vnstock_brief import build_prompt, ticker_sr_levels


def _bars(n=80, base=10.0):
    """Chuỗi high/low quanh `base` đủ rộng để có ứng viên hai phía."""
    highs = [base * (1 + 0.02 + (i % 9) * 0.004) for i in range(n)]
    lows = [base * (1 - 0.02 - (i % 7) * 0.004) for i in range(n)]
    return highs, lows


class TestPureLevelPicker:
    def test_finds_a_level_on_each_side(self):
        hi, lo = _bars()
        sup, res = ticker_sr_levels(hi, lo, 10.0)
        assert sup is not None and res is not None
        assert sup < 10.0 < res

    def test_levels_respect_the_min_distance_floor(self):
        # Mốc sát giá (<0,5%) là nhiễu — phải bị loại
        hi = [10.001] * 80
        lo = [9.999] * 80
        assert ticker_sr_levels(hi, lo, 10.0) == (None, None)

    def test_levels_respect_the_max_move_ceiling(self):
        # Mốc cách >7% không actionable trong 1-2 phiên (biên HOSE)
        hi = [11.5] * 80
        lo = [8.5] * 80
        assert ticker_sr_levels(hi, lo, 10.0) == (None, None)

    def test_too_few_bars_gives_nothing_rather_than_a_guess(self):
        assert ticker_sr_levels([10.5] * 5, [9.5] * 5, 10.0) == (None, None)

    def test_a_broken_last_price_gives_nothing(self):
        hi, lo = _bars()
        assert ticker_sr_levels(hi, lo, None) == (None, None)
        assert ticker_sr_levels(hi, lo, 0) == (None, None)
        assert ticker_sr_levels(hi, lo, "x") == (None, None)

    def test_empty_input_is_safe(self):
        assert ticker_sr_levels([], [], 10.0) == (None, None)
        assert ticker_sr_levels(None, None, 10.0) == (None, None)

    def test_the_last_two_bars_are_excluded(self):
        """2 bar cuối còn dính giá hiện tại ⇒ chưa phải đỉnh/đáy đã hình thành."""
        hi, lo = _bars()
        hi = hi + [10.3, 10.3]          # đỉnh chỉ xuất hiện ở 2 bar cuối
        lo = lo + [9.7, 9.7]
        _, res = ticker_sr_levels(hi, lo, 10.0)
        assert res != 10.3

    def test_nan_values_are_dropped(self):
        hi, lo = _bars()
        hi = [float("nan")] + hi
        sup, res = ticker_sr_levels(hi, lo, 10.0)
        assert res is not None


class TestPromptRendering:
    def _ctx(self, mover):
        return {"date": "2026-08-25", "time": "15:00", "vn30_gainers": [mover]}

    def _star_line(self, ctx):
        for ln in build_prompt(ctx, brief_type="afternoon").splitlines():
            if "⭐" in ln and ln.startswith("- "):
                return ln
        return ""

    def test_both_levels_render_as_real_support_and_resistance(self):
        ln = self._star_line(self._ctx({
            "Mã": "GAS", "Giá 1T %": 2.0, "Ngành": "NL", "last": 83.5,
            "GTGD TB (tỷ)": 300.0, "sr_support": 81.2, "sr_resistance": 87.4}))
        assert "hỗ trợ 81,200 / kháng cự 87,400 — pivot 60 phiên" in ln
        assert "dải ±3%" not in ln

    def test_one_sided_says_so_instead_of_inventing_the_other(self):
        ln = self._star_line(self._ctx({
            "Mã": "VIX", "Giá 1T %": 1.0, "Ngành": "CK", "last": 13.1,
            "GTGD TB (tỷ)": 200.0, "sr_resistance": 13.9}))
        assert "kháng cự 13,900" in ln
        assert "CHƯA có mốc còn lại trong tầm" in ln
        assert "hỗ trợ" not in ln

    def test_no_levels_falls_back_to_the_honest_band_label(self):
        ln = self._star_line(self._ctx({
            "Mã": "PNJ", "Giá 1T %": 1.0, "Ngành": "BL", "last": 42.65,
            "GTGD TB (tỷ)": 200.0}))
        assert "dải ±3% quanh giá: 41,350 – 43,950" in ln
        assert "KHÔNG phải hỗ trợ/kháng cự đo được" in ln

    def test_levels_land_on_the_hose_tick_grid(self):
        # 13,1 nghìn ⇒ bước 50; mốc phải chia hết cho 50
        ln = self._star_line(self._ctx({
            "Mã": "VIX", "Giá 1T %": 1.0, "Ngành": "CK", "last": 13.1,
            "GTGD TB (tỷ)": 200.0, "sr_resistance": 13.887}))
        import re
        n = int(re.search(r"kháng cự ([\d,]+)", ln).group(1).replace(",", ""))
        assert n % 50 == 0

    def test_the_template_teaches_both_shapes(self):
        p = build_prompt(self._ctx({
            "Mã": "GAS", "Giá 1T %": 2.0, "Ngành": "NL", "last": 83.5,
            "GTGD TB (tỷ)": 300.0}), brief_type="afternoon")
        assert "pivot 60 phiên" in p and "mốc THAM CHIẾU" in p
        assert "TUYỆT ĐỐI KHÔNG bịa vế còn lại" in p

    def test_build_prompt_stays_io_free(self):
        """`build_prompt` bị test gọi với ctx 2 khoá và KHÔNG có kho — mọi I/O
        phải nằm ở `collect_context`."""
        import inspect
        src = inspect.getsource(vb.build_prompt)
        assert "_load_history" not in src and "read_parquet" not in src


class TestGuardStandsDownForRealLevels:
    def test_a_ticker_with_pivots_is_left_alone_by_the_band_guard(self):
        from vnstock_brief_guards_sections import _reference_bands
        ctx = {"vn30_gainers": [
            {"Mã": "GAS", "last": 83.5, "sr_support": 81.2},
            {"Mã": "PNJ", "last": 42.65}]}
        assert set(_reference_bands(ctx)) == {"PNJ"}

    def test_the_band_guard_still_fixes_a_band_only_ticker(self):
        from vnstock_brief_guards_sections import enforce_reference_band_wording
        ctx = {"vn30_gainers": [{"Mã": "PNJ", "last": 42.65}]}
        src = ("## 📋 Watchlist sáng mai\n"
               "1. **PNJ** (Giá 42,650) — giữ trên hỗ trợ 41,350.\n\n## ⚠️ Rủi ro\n")
        assert "mốc tham chiếu 41,350" in enforce_reference_band_wording(src, ctx)


class TestWiring:
    def test_collect_context_attaches_the_levels(self):
        import inspect
        src = inspect.getsource(vb.collect_context)
        assert "_attach_ticker_sr" in src

    def test_attach_never_raises_on_a_broken_warehouse(self, monkeypatch):
        movers = [{"Mã": "GAS", "last": 83.5}]
        monkeypatch.setattr(
            "vnstock_strategy._load_history_from_parquet",
            lambda *a, **k: (_ for _ in ()).throw(OSError("kho hỏng")))
        vb._attach_ticker_sr(movers)          # không được ném
        assert "sr_support" not in movers[0]

    def test_attach_is_a_noop_on_empty_input(self):
        vb._attach_ticker_sr([])
        vb._attach_ticker_sr(None)
