"""Nhận định thị trường — chữ tiếng Việt USER ĐỌC, tách khỏi `market_tab` 12/08.

220 dòng sinh chữ cho user, trước giờ CHƯA CÓ TEST vì là closure lồng trong
hàm render 2.544 dòng và còn bắt `st.session_state` + `idx_df` qua closure.

Khi kéo ra: đối chiếu vi phân bản cũ (chép từ commit faf4667) với bản mới trên
**600 tổ hợp** (breadth × chỉ số × bảng ngành × bảng mã, kể cả None/rỗng/thiếu
cột) — 0 khác biệt. Test dưới đây chốt lại hành vi, tập trung vào NGƯỠNG: đây
là lời khuyên gửi tới user, đổi ngưỡng là đổi lời khuyên.
"""
import sys
import types

import numpy as np
import pandas as pd
import pytest

from dashboard.market_commentary import (
    breadth_lines,
    build_commentary,
    index_strength_lines,
    quant_lines,
)


def _idx(chg_vnindex, close=1_250.0, with_vn30=False):
    """Bảng chỉ số: dòng ĐẦU là phiên mới nhất (hàm dùng `.head(5)`)."""
    data = {"VNINDEX": [close] * len(chg_vnindex), "VNINDEX_chg": chg_vnindex}
    if with_vn30:
        data["VN30"] = [close + 100] * len(chg_vnindex)
        data["VN30_chg"] = list(reversed(chg_vnindex))
    return pd.DataFrame(data)


def _breadth(**kw):
    base = {"above_ma200_pct": 45.0, "ad_ratio": 1.0, "rsi_oversold": 0,
            "rsi_overbought": 0, "net_new_highs": 0}
    base.update(kw)
    return base


# ── Mục 1: sức mạnh chung ───────────────────────────────────────────────────

class TestIndexStrength:

    def test_header_always_present(self):
        assert index_strength_lines(None)[0] == "**📊 Sức mạnh chung**"

    def test_no_data_adds_no_claim(self):
        """Không có data thì im — tuyệt đối không bịa ra một nhận định."""
        assert index_strength_lines(pd.DataFrame()) == ["**📊 Sức mạnh chung**"]

    @pytest.mark.parametrize("avg,expect_icon,expect_word", [
        (1.0, "🟢", "tăng tích cực"),
        (0.1, "🟡", "đi ngang thiên tăng"),
        (-0.1, "🟠", "đi ngang thiên giảm"),
        (-1.0, "🔴", "giảm rõ rệt"),
    ])
    def test_four_trend_bands(self, avg, expect_icon, expect_word):
        line = index_strength_lines(_idx([avg] * 5))[1]
        assert expect_icon in line
        assert expect_word in line

    def test_band_boundaries(self):
        """0.3 và -0.3 là ngưỡng ĐÓNG phía dưới (`>`), không phải `>=`."""
        assert "đi ngang thiên tăng" in index_strength_lines(_idx([0.3] * 5))[1]
        assert "tăng tích cực" in index_strength_lines(_idx([0.31] * 5))[1]
        assert "giảm rõ rệt" in index_strength_lines(_idx([-0.3] * 5))[1]
        assert "đi ngang thiên giảm" in index_strength_lines(_idx([-0.29] * 5))[1]

    def test_counts_up_days_out_of_five(self):
        line = index_strength_lines(_idx([1.0, -1.0, 1.0, -1.0, 1.0]))[1]
        assert "3/5 tăng" in line

    def test_only_looks_at_five_most_recent_sessions(self):
        """Dòng đầu = phiên mới nhất. Phiên thứ 6 trở đi KHÔNG được tính."""
        line = index_strength_lines(_idx([1.0] * 5 + [-9.0] * 20))[1]
        assert "5/5 tăng" in line
        assert "+1.00%" in line

    def test_shows_last_close_with_thousands_separator(self):
        assert "(1,234)" in index_strength_lines(_idx([0.5] * 5, close=1234.4))[1]

    def test_missing_index_column_is_skipped_not_crashed(self):
        """Bảng chỉ có VNINDEX → không được ném vì thiếu VN30."""
        lines = index_strength_lines(_idx([0.5] * 5))
        assert len(lines) == 2
        assert "VN30" not in lines[1]

    def test_both_indexes_when_present(self):
        lines = index_strength_lines(_idx([0.5] * 5, with_vn30=True))
        assert "VNINDEX" in lines[1] and "VN30" in lines[2]

    def test_nan_rows_are_dropped_before_averaging(self):
        line = index_strength_lines(_idx([np.nan, 1.0, 1.0]))[1]
        assert "+1.00%" in line


# ── Mục 2: sức khỏe thị trường ──────────────────────────────────────────────

class TestBreadthLines:

    def test_no_breadth_returns_nothing_at_all(self):
        """RỖNG chứ không phải tiêu đề trống: tiêu đề không kèm nội dung khiến
        user tưởng số liệu về 0 chứ không phải thiếu số liệu."""
        assert breadth_lines(None) == []
        assert breadth_lines({}) == []

    @pytest.mark.parametrize("pct,icon", [(72.0, "🟢"), (41.0, "🟡"), (12.0, "🔴")])
    def test_three_ma200_bands(self, pct, icon):
        assert icon in breadth_lines(_breadth(above_ma200_pct=pct))[2]

    def test_ma200_boundaries_are_strict(self):
        assert "🟡" in breadth_lines(_breadth(above_ma200_pct=50.0))[2]
        assert "🟢" in breadth_lines(_breadth(above_ma200_pct=50.1))[2]
        assert "🔴" in breadth_lines(_breadth(above_ma200_pct=30.0))[2]

    def test_ad_ratio_only_speaks_when_decisive(self):
        """Vùng 0.8–1.2 là giằng co — nói ra chỉ thêm nhiễu."""
        assert not any("A/D" in ln for ln in breadth_lines(_breadth(ad_ratio=1.0)))
        assert "lực cầu" in breadth_lines(_breadth(ad_ratio=1.5))[3]
        assert "lực bán" in breadth_lines(_breadth(ad_ratio=0.5))[3]

    def test_rsi_extremes_only_when_broad(self):
        assert not any("RSI" in ln for ln in breadth_lines(_breadth(rsi_oversold=50)))
        assert any("RSI<30" in ln for ln in breadth_lines(_breadth(rsi_oversold=51)))
        assert not any("RSI" in ln for ln in breadth_lines(_breadth(rsi_overbought=30)))
        assert any("RSI>70" in ln for ln in breadth_lines(_breadth(rsi_overbought=31)))

    def test_net_new_highs_is_symmetric(self):
        assert "đỉnh mới tốt" in breadth_lines(_breadth(net_new_highs=11))[-1]
        assert "đáy mới" in breadth_lines(_breadth(net_new_highs=-11))[-1]
        assert not any("net new highs" in ln
                       for ln in breadth_lines(_breadth(net_new_highs=10)))

    def test_signed_format_for_net_new_highs(self):
        assert "+25 net new highs" in breadth_lines(_breadth(net_new_highs=25))[-1]
        assert "-25 net new highs" in breadth_lines(_breadth(net_new_highs=-25))[-1]

    def test_missing_key_is_a_hard_error(self):
        """Thiếu khoá breadth là DỮ LIỆU HỎNG — phải ném để thấy, không được
        lặng lẽ bỏ qua rồi in nhận định thiếu."""
        with pytest.raises(KeyError):
            breadth_lines({"above_ma200_pct": 50})


# ── Mục 3: quant ────────────────────────────────────────────────────────────

@pytest.fixture
def fake_analyzer(monkeypatch):
    """Thay `vnstock_market_analyzer` bằng bản giả — test ở đây soi CÁCH GHÉP
    CHỮ, không soi thuật toán chấm điểm (đã có test riêng)."""
    ma = types.ModuleType("vnstock_market_analyzer")
    ma.compute_scores = lambda df, presets=None, index_returns=None, exdiv_map=None: {"n": len(df)}
    ma.market_regime = lambda scores, breadth: {
        "regime": "RISK-ON", "conviction": 0.42, "detail": "test"}
    ma.format_row = lambda row, name_col="Ngành": [
        f"{row[name_col]} `{row['composite']:+.2f}`", "  dòng phụ"]
    ma.build_preset_sets = lambda x: None
    ma.compute_index_returns = lambda df, index_col="VNINDEX": {"1T": 1.2, "1M": -0.4, "3M": 5.6}
    ma.load_quarantine_tickers = lambda: set()
    ma.load_recent_exdiv = lambda days_back=7: {}
    ma.session_timing_signal = lambda t, h, index_name="VNINDEX": {"signal": "N/A", "detail": ""}

    def _rank(df, scores, n_top=5, n_bot=5, name_col="Ngành", quarantined=None):
        names = list(df[name_col])
        rows = [{name_col: n, "composite": round(1.5 - i, 2)} for i, n in enumerate(names)]
        return {"top": rows[:n_top], "avoid": list(reversed(rows))[:n_bot],
                "stealth": [], "distribution": [], "rotation": []}
    ma.rank = _rank
    monkeypatch.setitem(sys.modules, "vnstock_market_analyzer", ma)

    sess = types.ModuleType("vnstock_session_stats")
    sess.load_session_stats_history = lambda: {}
    monkeypatch.setitem(sys.modules, "vnstock_session_stats", sess)

    # Chặn luôn `vnstock_dashboard` — import thật sẽ kéo cả Streamlit vào.
    vnd = types.ModuleType("vnstock_dashboard")
    vnd.load_screener_results = lambda: None
    monkeypatch.setitem(sys.modules, "vnstock_dashboard", vnd)
    return ma


def _mkt(n=3):
    return pd.DataFrame({"Ngành": [f"N{i}" for i in range(n)],
                         "Giá 1M %": np.linspace(-2, 2, n)})


def _block(lines, title_fragment):
    """Các dòng thuộc một khối, từ sau tiêu đề tới dòng trống kế tiếp."""
    out, inside = [], False
    for ln in lines:
        if title_fragment in ln:
            inside = True
            continue
        if inside:
            if ln == "":
                break
            out.append(ln)
    return out


class TestQuantLines:

    def test_no_data_stays_silent(self):
        assert quant_lines(None, None) == []
        assert quant_lines(pd.DataFrame(), None) == []

    def test_missing_1m_column_stays_silent(self):
        """Không có "Giá 1M %" thì mọi điểm quant đều vô nghĩa."""
        assert quant_lines(pd.DataFrame({"Ngành": ["N0"]}), None) == []

    def test_regime_line_is_rendered(self, fake_analyzer):
        out = quant_lines(_mkt(), None)
        assert any("Quant regime: RISK-ON" in ln for ln in out)
        assert any("`+0.42`" in ln for ln in out)

    def test_benchmark_line_only_with_index_history(self, fake_analyzer):
        assert not any("benchmark" in ln for ln in quant_lines(_mkt(), None))
        with_idx = quant_lines(_mkt(), None, idx_long=_idx([1.0] * 5))
        assert any("VNINDEX benchmark" in ln for ln in with_idx)

    def test_negative_composites_are_cut_from_the_top_block(self, fake_analyzer):
        """Danh sách đã sắp xếp nên gặp composite âm là DỪNG, không lọc tiếp.
        (Mã âm vẫn xuất hiện ở khối ⛔ "nên tránh" — chỉ khối 🎯 mới cắt.)"""
        top_block = _block(quant_lines(_mkt(4), None), "🎯 Ngành đáng quan tâm")
        assert any("N0 `+1.50`" in ln for ln in top_block)
        assert any("N1 `+0.50`" in ln for ln in top_block)
        assert not any("`-" in ln for ln in top_block)

    def test_positive_composites_are_cut_from_the_avoid_block(self, fake_analyzer):
        avoid_block = _block(quant_lines(_mkt(4), None), "⛔ Ngành nên tránh")
        assert any("N3 `-1.50`" in ln for ln in avoid_block)
        assert not any("`+" in ln for ln in avoid_block)

    def test_sub_lines_keep_their_indent(self, fake_analyzer):
        """`format_row` trả dòng phụ đã thụt lề — không được gắn thêm "- "."""
        out = quant_lines(_mkt(), None)
        assert "  dòng phụ" in out
        assert "-   dòng phụ" not in out

    def test_analyzer_failure_degrades_to_a_visible_warning(self, monkeypatch):
        """Guard `except Exception` rộng là CÓ CHỦ Ý: quant hỏng thì mục 1+2
        vẫn phải tới tay user, kèm lý do nhìn thấy được."""
        broken = types.ModuleType("vnstock_market_analyzer")
        monkeypatch.setitem(sys.modules, "vnstock_market_analyzer", broken)
        out = quant_lines(_mkt(), None)
        assert any("Không tính được quant score" in ln for ln in out)

    def test_ticker_block_needs_a_sector_column(self, fake_analyzer):
        ticks = pd.DataFrame({"Mã": ["AAA"], "Giá 1M %": [1.0]})
        assert not any("Mã dẫn dắt" in ln for ln in quant_lines(_mkt(), None, tick_data=ticks))

    def test_ticker_block_renders_leaders(self, fake_analyzer):
        ticks = pd.DataFrame({"Mã": ["AAA", "BBB"], "Ngành": ["N0", "N0"],
                              "Giá 1M %": [1.0, 2.0]})
        out = "\n".join(quant_lines(_mkt(), None, tick_data=ticks))
        assert "⭐ Mã dẫn dắt" in out
        assert "**AAA**" in out


# ── Ghép ba mục ─────────────────────────────────────────────────────────────

class TestBuildCommentary:

    def test_sections_appear_in_order(self):
        out = build_commentary(_breadth(above_ma200_pct=70), None, _idx([0.5] * 5))
        assert out.index("📊 Sức mạnh chung") < out.index("🌡️ Sức khỏe thị trường")

    def test_quant_failure_does_not_lose_the_first_two_sections(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "vnstock_market_analyzer",
                            types.ModuleType("vnstock_market_analyzer"))
        out = build_commentary(_breadth(above_ma200_pct=70), _mkt(), _idx([0.5] * 5))
        assert "📊 Sức mạnh chung" in out
        assert "🌡️ Sức khỏe thị trường" in out
        assert "Không tính được quant score" in out

    def test_returns_a_string_even_with_nothing(self):
        assert build_commentary(None, None, None) == "**📊 Sức mạnh chung**"

    def test_does_not_touch_streamlit(self):
        """Cả module phải sạch Streamlit — đó là lý do nó tách ra được."""
        import ast
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "dashboard" / "market_commentary.py").read_text(encoding="utf-8")
        names = {a.name for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(str(n).startswith("streamlit") for n in names)
