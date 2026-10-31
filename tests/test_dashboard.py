"""Test helper của dashboard — chuẩn hoá giá, chỉ báo, value area, bảng, v.v.

ĐỢT 2 GỠ REPLICA (12/08) — file này giờ import **ĐỒ THẬT** hoàn toàn, không
còn hàm chép tay nào.

Vì sao từng có replica: `vnstock_dashboard.py` gọi `st.set_page_config()` ở
cấp module rồi dựng UI ngay khi import, nên test không import nổi. Giải pháp
cũ là chép hàm sang đây — và bản chép TRÔI: `compute_indicators` replica vẫn
giữ công thức RSI cũ (để NaN ở đuôi), `cell_color` replica thiếu hẳn nhánh
`Trend`/`Ticker`/`Ngành`. Test xanh trên bản chép = không bảo vệ gì cả.
Giải pháp mới: kéo logic ra module thuần (`vnstock_price_units`,
`dashboard/chart_indicators` …) rồi import thẳng.

Mock streamlit vẫn giữ: một số module dưới `dashboard/` còn import streamlit.
⚠️ Mock chạy Ở CẤP MODULE nên có hiệu lực từ lúc pytest THU THẬP — tức nhiễm
sang MỌI file test khác trong phiên, bất kể thứ tự chạy.
`sys.modules["vnstock_wss"] = MagicMock()` từng nằm đây đã bị GỠ (06/08) vì nó
làm mọi test đụng tới vnstock_wss nhận phải MagicMock —
`tests/test_audit_high_fixes.py` đỏ 4 test vì vậy, và chỉ đỏ khi chạy CẢ SUITE
(chạy riêng thì xanh) nên rất khó lần ra.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

_st_mock = MagicMock()
_st_mock.set_page_config = MagicMock()
_st_mock.cache_data = lambda *a, **kw: (lambda f: f)
_st_mock.cache_resource = lambda *a, **kw: (lambda f: f)
sys.modules["streamlit"] = _st_mock
sys.modules["streamlit.components"] = MagicMock()
sys.modules["streamlit.components.v1"] = MagicMock()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.chart_indicators import compute_indicators          # noqa: E402
from dashboard.table_style import cell_color, cell_weight          # noqa: E402
from dashboard.theme import TOKENS as T                            # noqa: E402
from dashboard.volume_profile import calc_value_area as _calc_value_area  # noqa: E402
from dashboard.watchlist_io import (                               # noqa: E402
    load_watchlist as _load_watchlist,
    save_watchlist as _save_watchlist,
)
from vnstock_console_launch import build_ps_command                # noqa: E402
from vnstock_price_units import (                                  # noqa: E402
    normalize_live_price as _normalize_live_price,
    normalize_quote_price as _normalize_quote_price,
    normalize_price_units as _normalize_price_units,
)
from vnstock_sectors import SECTOR_GROUPS as _SECTOR_GROUPS        # noqa: E402
from vnstock_sectors import get_sector as _get_sector              # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 100, base: float = 50.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-04-10", periods=n)
    closes = base + np.cumsum(rng.normal(0, 0.5, n))
    closes = np.maximum(closes, 1.0)
    return pd.DataFrame({
        "time": dates,
        "open": closes + rng.normal(0, 0.1, n),
        "high": closes + abs(rng.normal(0.2, 0.1, n)),
        "low": closes - abs(rng.normal(0.2, 0.1, n)),
        "close": closes,
        "volume": rng.integers(10_000, 500_000, n),
    })


# ── _normalize_price_units ──────────────────────────────────────────────────

class TestNormalizePriceUnits:

    def test_vnd_divided_by_1000(self):
        df = pd.DataFrame({
            "open": [77800.0], "high": [78000.0],
            "low": [77500.0], "close": [77700.0],
        })
        result = _normalize_price_units(df)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)
        assert result["open"].iloc[0] == pytest.approx(77.8, rel=1e-3)

    def test_thousand_vnd_unchanged(self):
        df = pd.DataFrame({
            "open": [77.8], "high": [78.0],
            "low": [77.5], "close": [77.7],
        })
        result = _normalize_price_units(df)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)

    def test_mixed_units_per_cell(self):
        df = pd.DataFrame({
            "open": [77.8], "high": [78000.0],
            "low": [77.5], "close": [77700.0],
        })
        result = _normalize_price_units(df)
        assert result["open"].iloc[0] == pytest.approx(77.8, rel=1e-3)
        assert result["close"].iloc[0] == pytest.approx(77.7, rel=1e-3)
        assert result["high"].iloc[0] == pytest.approx(78.0, rel=1e-3)

    def test_high_priced_stock_keeps_thousand_units(self):
        """HLB/VNZ có giá thật > 500 nghìn (18/10: HLB 660, VNZ 579). Chia 1000 từng ô > 500
        biến HLB thành 0.66 bên cạnh bar 445 cũ ⇒ 20D −99,85%, RSI 0.1, lọt oversold."""
        df = pd.DataFrame({"close": [350.0, 445.4, 505.9, 798.0, 660.0]})
        result = _normalize_price_units(df)
        assert result["close"].tolist() == [350.0, 445.4, 505.9, 798.0, 660.0]

    def test_vnd_cells_divided_against_series_median(self):
        """Bar VND lẫn trong chuỗi nghìn (ATB/BII… còn 18 bar như vậy trong kho) vẫn chia 1000."""
        df = pd.DataFrame({"close": [0.75, 0.8, 750.0, 0.78], "open": [0.74, 790.0, 0.8, 0.77]})
        result = _normalize_price_units(df)
        assert result["close"].tolist() == pytest.approx([0.75, 0.8, 0.75, 0.78])
        assert result["open"].tolist() == pytest.approx([0.74, 0.79, 0.8, 0.77])

    def test_penny_vnd_series_crossing_500_stays_one_scale(self):
        """Mã penny lưu VND quanh mốc 500: chia từng ô từng đẻ [480, 0.51, 495] — return giả
        ±×1000 (vết preset_score 15/07). Cả chuỗi cùng thang thì return đúng."""
        df = pd.DataFrame({"close": [480.0, 510.0, 495.0]})
        assert _normalize_price_units(df)["close"].tolist() == [480.0, 510.0, 495.0]

    def test_float32_columns_like_the_warehouse(self):
        """Kho lưu OHLC float32. Gán v/1000 (float64) vào cột float32 qua `.loc`: pandas 2
        FutureWarning, pandas 3 TypeError ⇒ mọi loader gọi helper vỡ trên kho thật."""
        import warnings
        df = pd.DataFrame({"close": np.array([25.3, 25.4, 25_450.0, 25.6], dtype="float32")})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            out = _normalize_price_units(df)
        assert out["close"].tolist() == pytest.approx([25.3, 25.4, 25.45, 25.6], rel=1e-6)

    def test_empty_dataframe(self):
        result = _normalize_price_units(pd.DataFrame())
        assert result.empty

    def test_does_not_modify_original(self):
        df = pd.DataFrame({"open": [77800.0], "high": [78000.0],
                           "low": [77500.0], "close": [77700.0]})
        original_close = df["close"].iloc[0]
        _normalize_price_units(df)
        assert df["close"].iloc[0] == original_close


# ── _normalize_live_price ────────────────────────────────────────────────────

class TestNormalizeLivePrice:

    def test_live_in_vnd_historical_in_thousand(self):
        result = _normalize_live_price(77.7, 77700.0)
        assert result == pytest.approx(77.7, rel=1e-3)

    def test_live_in_thousand_historical_in_vnd(self):
        result = _normalize_live_price(77700.0, 77.7)
        assert result == pytest.approx(77700.0, rel=1e-3)

    def test_same_scale_unchanged(self):
        result = _normalize_live_price(77.7, 78.0)
        assert result == pytest.approx(78.0, rel=1e-3)

    def test_zero_historical(self):
        assert _normalize_live_price(0, 77700.0) == 77700.0

    def test_zero_live(self):
        assert _normalize_live_price(77.7, 0) == 0


class TestNormalizeQuotePrice:
    """Quote live / giá nhập tay ⇒ nghìn đồng, mốc = close kho (đã chuẩn hoá)."""

    @pytest.mark.parametrize("ref, price, want", [
        (660.0, 660.0, 660.0),         # HLB quote nghìn: ngưỡng cứng >500 từng chia ra 0.66
        (660.0, 660_000.0, 660.0),     # HLB quote VND
        (0.3, 300.0, 0.3),             # mã 300 đ quote VND: ngưỡng cứng giữ 300 (= 300 nghìn)
        (77.7, 77_700.0, 77.7),
        (77.7, 78.0, 78.0),
        (0.0, 77_700.0, 77.7),         # không có mốc kho ⇒ ngưỡng như cũ
        (0.0, 30.0, 30.0),
        (float("nan"), 77_700.0, 77.7),
        (77.7, 0.0, 0.0),
    ])
    def test_scale(self, ref, price, want):
        assert _normalize_quote_price(ref, price) == pytest.approx(want)


# ── compute_indicators ──────────────────────────────────────────────────────

class TestComputeIndicators:

    def test_adds_indicator_columns(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        for col in ("rsi", "ema9", "ema21", "macd", "macd_signal",
                     "macd_hist", "bb_up", "bb_lo", "bb_mid", "vol_ma20"):
            assert col in result.columns, f"Missing column: {col}"

    def test_rsi_bounded(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        rsi = result["rsi"].dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_bollinger_band_order(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        valid = result.dropna(subset=["bb_up", "bb_lo"])
        assert (valid["bb_up"] >= valid["bb_lo"]).all()

    def test_output_same_length(self):
        df = _make_ohlcv(100)
        result = compute_indicators(df)
        assert len(result) == len(df)


# ── _calc_value_area ─────────────────────────────────────────────────────────

class TestCalcValueArea:

    def test_basic_value_area(self):
        profile = [
            {"price": 80.0, "total_vol": 100},
            {"price": 79.0, "total_vol": 500},
            {"price": 78.0, "total_vol": 300},
            {"price": 77.0, "total_vol": 50},
        ]
        poc_idx, vah_idx, val_idx, poc_p, vah_p, val_p = _calc_value_area(profile)
        assert poc_p == 79.0
        assert vah_p >= val_p

    def test_empty_profile(self):
        assert _calc_value_area([]) == (0, 0, 0, 0, 0, 0)

    def test_single_level(self):
        profile = [{"price": 50.0, "total_vol": 1000}]
        poc_idx, vah_idx, val_idx, poc_p, vah_p, val_p = _calc_value_area(profile)
        assert poc_p == 50.0

    def test_poc_is_max_volume(self):
        profile = [
            {"price": 82.0, "total_vol": 10},
            {"price": 81.0, "total_vol": 20},
            {"price": 80.0, "total_vol": 999},
            {"price": 79.0, "total_vol": 30},
            {"price": 78.0, "total_vol": 15},
        ]
        _, _, _, poc_p, _, _ = _calc_value_area(profile)
        assert poc_p == 80.0


# ── cell_color / cell_weight ────────────────────────────────────────────────
# Đồ THẬT từ `dashboard/table_style.py`. Replica cũ ở đây thiếu hẳn nhánh
# Trend/Ticker/Ngành và bậc RSI 40/60 — các nhánh đó nay có test ở dưới.

_cell_color = cell_color
_cell_weight = cell_weight


class TestCellColor:

    def test_positive_pct_is_green(self):
        assert _cell_color("1D%", "+2.5%") == T["up"]

    def test_negative_pct_is_red(self):
        assert _cell_color("5D%", "-3.1%") == T["down"]

    def test_zero_session_pct_is_reference_yellow(self):
        """1D% so với tham chiếu ⇒ đứng giá tô VÀNG như bảng điện (user chốt 30/10)."""
        assert _cell_color("1D%", "0.0%") == T["ref"]

    @pytest.mark.parametrize("val,tok", [("+0.0%", "up"), ("-0.0%", "down")])
    def test_rounded_zero_keeps_its_direction(self, val, tok):
        """Mã giá cao đổi 1 bước giá (~0,04%) hiện "+0.0%" — có đổi thật, không phải đứng giá."""
        assert _cell_color("1D%", val) == T[tok]

    def test_zero_multi_session_pct_is_gray(self):
        """5D%/20D% bằng 0 chỉ là "không đổi" — không có tham chiếu nào để vàng."""
        assert _cell_color("5D%", "0.0%") == T["text_muted"]

    def test_rsi_oversold_green(self):
        assert _cell_color("RSI", "25") == T["up"]

    def test_rsi_overbought_red(self):
        assert _cell_color("RSI", "75") == T["down"]

    def test_dash_placeholder_returns_gray(self):
        assert _cell_color("1D%", "—") == T["text_faint"]

    def test_none_returns_gray(self):
        assert _cell_color("1D%", None) == T["text_faint"]

    def test_garbage_string_falls_back(self):
        # ValueError from float("abc") — caught by narrow except
        assert _cell_color("1D%", "abc%") == T["text_faint"]

    def test_rsi_garbage_falls_back(self):
        assert _cell_color("RSI", "N/A") == T["text_faint"]

    def test_narrow_except_lets_keyboardinterrupt_escape(self):
        """Proves bare except would have swallowed this — narrow one doesn't."""
        class Trap:
            def __str__(self):
                raise KeyboardInterrupt("user pressed Ctrl+C")
        with pytest.raises(KeyboardInterrupt):
            _cell_color("1D%", Trap())


class TestCellWeight:

    def test_ticker_is_bold(self):
        assert _cell_weight("Ticker", "VCB") == "600"

    def test_extreme_rsi_is_heavy(self):
        assert _cell_weight("RSI", "15") == "700"
        assert _cell_weight("RSI", "85") == "700"

    def test_mid_rsi_is_normal(self):
        assert _cell_weight("RSI", "50") == "400"

    def test_nonzero_pct_is_medium(self):
        assert _cell_weight("1D%", "+1.5%") == "500"

    def test_zero_pct_is_normal(self):
        assert _cell_weight("1D%", "0.0%") == "400"

    def test_unparseable_falls_back(self):
        assert _cell_weight("1D%", "abc") == "400"
        assert _cell_weight("RSI", "xyz") == "400"


# ── Watchlist I/O roundtrip ─────────────────────────────────────────────────

class TestWatchlistIO:

    def test_empty_when_missing(self, tmp_path):
        path = tmp_path / "watchlist.json"
        assert _load_watchlist(path) == []

    def test_roundtrip_dedupes_and_sorts(self, tmp_path):
        path = tmp_path / "watchlist.json"
        _save_watchlist(path, ["VCB", "FPT", "VCB", "HPG"])
        result = _load_watchlist(path)
        assert result == ["FPT", "HPG", "VCB"]

    def test_corrupt_json_raises(self, tmp_path):
        """File hỏng KHÔNG được đọc thành [] — nút Thêm sẽ ghi đè cả watchlist."""
        path = tmp_path / "watchlist.json"
        path.write_text("{ this is not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            _load_watchlist(path)

    @pytest.mark.parametrize("payload", [
        "null",                                   # gốc không phải object
        '["VCB", "FPT"]',                         # list thay vì {"tickers": [...]}
        '{"tickers": "VCB"}',                     # tickers không phải list
        '{"tickers": ["VCB", 1]}',                # mã không phải chuỗi
    ])
    def test_wrong_shape_raises_value_error(self, tmp_path, payload):
        """JSON hợp lệ nhưng sai dạng từng ném AttributeError (caller chỉ bắt
        OSError/ValueError ⇒ sập tab) hoặc lọt chuỗi "VCB" thành 3 "mã"."""
        path = tmp_path / "watchlist.json"
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError, match="sai định dạng"):
            _load_watchlist(path)


# ── launch_in_new_console PowerShell command generation ──────────────────────

def _build_ps_command(commands, python_exe="/usr/bin/python"):
    """Đồ thật, chỉ gắn sẵn python_exe cho gọn ở phần assert bên dưới."""
    return build_ps_command(commands, python_exe)


class TestLaunchInNewConsole:

    def test_single_command_includes_args(self):
        cmd = _build_ps_command([
            {"label": "Screener", "args": ["vnstock_runner.py"]},
        ])
        assert "=== Screener ===" in cmd
        assert "'vnstock_runner.py'" in cmd
        assert "Read-Host 'Hoan tat" in cmd

    def test_chained_commands_stop_on_error(self):
        cmd = _build_ps_command([
            {"label": "Update", "args": ["vnstock_updater.py", "--force"]},
            {"label": "Screen", "args": ["vnstock_runner.py"]},
        ])
        assert "vnstock_updater.py" in cmd
        assert "--force" in cmd
        assert "if ($LASTEXITCODE -ne 0)" in cmd  # stop-on-error guard
        assert "vnstock_runner.py" in cmd
        # Guard appears exactly once (between 2 commands, not after last)
        assert cmd.count("if ($LASTEXITCODE -ne 0)") == 1

    def test_stop_on_error_opt_out(self):
        cmd = _build_ps_command([
            {"label": "A", "args": ["a.py"], "stop_on_error": False},
            {"label": "B", "args": ["b.py"]},
        ])
        assert "if ($LASTEXITCODE -ne 0)" not in cmd

    def test_utf8_encoding_set(self):
        cmd = _build_ps_command([{"label": "X", "args": ["x.py"]}])
        assert "PYTHONIOENCODING='utf-8'" in cmd
        assert "chcp 65001" in cmd


# ── Money Flow helpers (replica from vnstock_dashboard.py) ───────────────────

# SECTOR_GROUPS / _get_sector: đồ THẬT từ `vnstock_sectors` (import ở đầu file).

from dashboard.money_flow_score import (  # đồ THẬT, không còn replica
    compute_money_flow_score as _compute_money_flow_score,
    score_bar_html as _score_bar_html,
    score_label as _score_label,
)


class TestGetSector:

    def test_direct_mapping(self):
        assert _get_sector("Ngân hàng") == "Ngân hàng"
        assert _get_sector("Bất động sản") == "Bất động sản"
        assert _get_sector("Thép & Kim loại") == "Thép & Kim loại"

    def test_grouped_mapping(self):
        assert _get_sector("Vật liệu xây dựng") == "Hoá chất & Vật liệu"
        assert _get_sector("Hóa chất & Phân bón") == "Hoá chất & Vật liệu"
        assert _get_sector("Nhựa & Bao bì") == "Hoá chất & Vật liệu"
        assert _get_sector("Cơ khí & Thiết bị công nghiệp") == "Hoá chất & Vật liệu"

    def test_energy_group(self):
        assert _get_sector("Dầu khí") == "Năng lượng"
        assert _get_sector("Điện & Năng lượng tái tạo") == "Năng lượng"
        assert _get_sector("Khai khoáng & Tài nguyên") == "Năng lượng"

    def test_consumer_group(self):
        assert _get_sector("Bán lẻ & Thương mại") == "Tiêu dùng"
        assert _get_sector("Thực phẩm & Đồ uống") == "Tiêu dùng"
        assert _get_sector("Dệt may & May mặc") == "Tiêu dùng"

    def test_unknown_falls_back_to_khac(self):
        assert _get_sector("Ngành không tồn tại") == "Khác"
        assert _get_sector("") == "Khác"

    def test_all_31_industries_mapped(self):
        """Every original industry must map to one of the 15 sectors."""
        expected_sectors = {
            "Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản",
            "Xây dựng & Hạ tầng", "Thép & Kim loại", "Hoá chất & Vật liệu",
            "Năng lượng", "Công nghệ", "Tiêu dùng", "Nông & Thuỷ sản",
            "Y tế & Dược", "Vận tải & Cảng", "Dịch vụ & Du lịch", "Khác",
        }
        for industry, sector in _SECTOR_GROUPS.items():
            assert sector in expected_sectors, f"{industry} → {sector} not valid"


class TestComputeMoneyFlowScore:

    def test_strong_inflow(self):
        """NN mua ròng lớn + buy dominant → score cao."""
        score = _compute_money_flow_score(nn_net=100, nn_median=50, buy_ratio=0.7)
        assert score > 50

    def test_strong_outflow(self):
        """NN bán ròng lớn + sell dominant → score âm."""
        score = _compute_money_flow_score(nn_net=-100, nn_median=50, buy_ratio=0.3)
        assert score < -50

    def test_neutral(self):
        """NN = 0, buy/sell cân bằng → score gần 0."""
        score = _compute_money_flow_score(nn_net=0, nn_median=50, buy_ratio=0.5)
        assert -5 <= score <= 5

    def test_clamped_at_boundaries(self):
        """Score phải nằm trong khoảng -100 ~ +100."""
        score_high = _compute_money_flow_score(nn_net=99999, nn_median=1, buy_ratio=1.0)
        score_low = _compute_money_flow_score(nn_net=-99999, nn_median=1, buy_ratio=0.0)
        assert -100 <= score_high <= 100
        assert -100 <= score_low <= 100

    def test_zero_median_no_crash(self):
        """nn_median = 0 → NN score = 0, only buy/sell matters."""
        score = _compute_money_flow_score(nn_net=100, nn_median=0, buy_ratio=0.7)
        assert score > 0  # buy dominant still positive

    def test_mixed_signals(self):
        """NN mua ròng nhưng sell dominant → score trung lập."""
        score = _compute_money_flow_score(nn_net=50, nn_median=50, buy_ratio=0.35)
        assert -20 <= score <= 20


class TestScoreLabel:

    def test_strong_inflow(self):
        label, color = _score_label(50)
        assert label == "VÀO"
        assert color == T["up"]

    def test_light_inflow(self):
        label, color = _score_label(20)
        assert label == "Vào nhẹ"
        assert color == T["up_soft"]

    def test_neutral(self):
        label, color = _score_label(0)
        assert label == "Trung lập"
        assert color == T["text_muted"]

    def test_light_outflow(self):
        label, color = _score_label(-20)
        assert label == "Ra nhẹ"
        assert color == T["down_soft"]

    def test_strong_outflow(self):
        label, color = _score_label(-50)
        assert label == "RA"
        assert color == T["down"]

    def test_boundary_values(self):
        assert _score_label(30.1)[0] == "VÀO"
        assert _score_label(30)[0] == "Vào nhẹ"
        assert _score_label(10)[0] == "Trung lập"
        assert _score_label(-9.9)[0] == "Trung lập"
        assert _score_label(-10)[0] == "Ra nhẹ"
        assert _score_label(-29.9)[0] == "Ra nhẹ"
        assert _score_label(-30)[0] == "RA"


class TestScoreBarHtml:

    def test_positive_score_contains_label(self):
        html = _score_bar_html(60)
        assert "VÀO" in html
        assert T["up"] in html
        # Thanh mọc từ vạch giữa SANG PHẢI: neo mép trái ở 50%. (Bản cũ ghim
        # "right:50%" — neo mép PHẢI ở giữa nên thanh dương mọc sang trái, và
        # assert âm "left:50%" luôn đúng nhờ chính cái vạch giữa.)
        assert "left:50%;width:30.0%" in html
        assert "right:50%" not in html

    def test_negative_score_contains_label(self):
        html = _score_bar_html(-60)
        assert "RA" in html
        assert T["down"] in html
        assert "right:50%;width:30.0%" in html  # mọc từ vạch giữa sang trái

    def test_zero_score(self):
        html = _score_bar_html(0)
        assert "Trung lập" in html

    def test_extreme_score_bar_capped(self):
        """Bar width capped at 80 → width/2 = 40%."""
        html = _score_bar_html(200)
        assert "width:40.0%" in html
