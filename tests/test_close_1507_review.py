"""Regression cho vòng review phản biện chéo close brief 15/07/2026 (workflow
7-cụm × verify): 5 guard gap tái hiện được trên code hiện tại. Hermetic."""

from __future__ import annotations

from vnstock_brief import (
    enforce_sector_nn_figures, enforce_net_flow_label, enforce_vnindex_change,
    enforce_gtgd_baseline_pct, enforce_sr_direction, apply_brief_guards,
)


# ── Fix 1: enforce_sector_nn_figures không được vượt ranh giới "trong khi" ──

_MF_CTX = {"sectors": [
    {"Ngành": "Họ VIN", "NN 1T (tỷ)": 1496.0},
    {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}]}


def test_sector_nn_no_cross_clause_corruption():
    # close 15/07: pass Họ VIN nuốt số 703 của Ngân hàng, pin thành +1,496
    line = ("NN mua ròng 1,496 tỷ đồng trong ngành Họ VIN (1 tuần), trong khi "
            "bán ròng 703 tỷ đồng trong ngành Ngân hàng.")
    out = enforce_sector_nn_figures(line, _MF_CTX)
    assert "703 tỷ đồng trong ngành Ngân hàng" in out
    assert "+1,496 tỷ đồng trong ngành Ngân hàng" not in out


def test_sector_nn_plus_sign_then_net_flow_fixes():
    # +703 (dấu sai) không bị sector_nn nhiễm, và net_flow_label bỏ dấu +
    line = ("NN mua ròng 1,496 tỷ đồng trong ngành Họ VIN (1 tuần), trong khi "
            "bán ròng +703 tỷ đồng trong ngành Ngân hàng.")
    out = enforce_net_flow_label(enforce_sector_nn_figures(line, _MF_CTX), _MF_CTX)
    assert "bán ròng 703 tỷ đồng trong ngành Ngân hàng" in out
    assert "+703" not in out


def test_sector_nn_still_fixes_own_fabricated_value():
    # ca legit (14/07): số bịa của CHÍNH ngành đó vẫn được pin
    legit = "Thép & Kim loại (đóng góp -0.03pp, 1 tuần, NN bán ròng -1372 tỷ)"
    out = enforce_sector_nn_figures(
        legit, {"sectors": [{"Ngành": "Thép & Kim loại", "NN 1T (tỷ)": -703.0}]})
    assert "-703 tỷ" in out


# ── Fix 2: enforce_vnindex_change nhánh % không hậu tố "so với" ─────────────

def test_vnindex_change_flat_bar_pins_fabricated_pct():
    # day_change=0.00 (bar VNINDEX phẳng) → "giảm 1.36%" bịa phải thành đi ngang
    ctx = {"vnindex_tech": {"day_change_pct": 0.0}}
    for t in ("**Kết quả phiên:** VNINDEX đóng cửa giảm 1.36% / GTGD 16,523.1 tỷ",
              "Kết quả toàn ngày cho thấy VNINDEX giảm 1.36% với GTGD đạt 16,523"):
        out = enforce_vnindex_change(t, ctx)
        assert "giảm 1.36%" not in out and "gần như đi ngang (0.00%)" in out
        assert enforce_vnindex_change(out, ctx) == out          # idempotent


def test_vnindex_change_does_not_touch_gtgd_or_sector():
    ctx = {"vnindex_tech": {"day_change_pct": 0.0}}
    # GTGD clause (chủ ngữ turnover) không bị đụng
    assert enforce_vnindex_change(
        "GTGD cả ngày giảm 1.36% so với TB5 phiên", ctx) == \
        "GTGD cả ngày giảm 1.36% so với TB5 phiên"
    # % ngành/tuần (không có chủ ngữ index) không bị đụng
    assert enforce_vnindex_change(
        "Bất động sản tăng 2.5% trong tuần", ctx) == "Bất động sản tăng 2.5% trong tuần"


def test_vnindex_change_real_move_preserved():
    ctx = {"vnindex_tech": {"day_change_pct": -1.36}}
    assert enforce_vnindex_change("VNINDEX đóng cửa giảm 1.36%", ctx) == \
        "VNINDEX đóng cửa giảm 1.36%"


# ── Fix 3: enforce_gtgd_baseline_pct Form 5 (bare-direction) ────────────────

def test_gtgd_bare_direction_flips_when_wrong():
    # F < avg5 → "cao hơn TB5" phải lật thành "thấp hơn"
    ctx = {"full_day_gtgd": 16523.1,
           "full_day_gtgd_cmp": {"avg5": 20000.0, "avg20": 18000.0, "prev": 17000.0}}
    t = ("## Tổng kết phiên\nGTGD đạt 16,523.1 tỷ, cao hơn trung bình 5 phiên "
         "gần nhất.")
    out = enforce_gtgd_baseline_pct(t, ctx)
    assert "thấp hơn trung bình 5 phiên" in out
    assert enforce_gtgd_baseline_pct(out, ctx) == out           # idempotent


def test_gtgd_bare_direction_noop_when_correct():
    ctx = {"full_day_gtgd": 22000.0, "full_day_gtgd_cmp": {"avg5": 20000.0}}
    t = "## Tổng kết phiên\nGTGD 22,000 tỷ, cao hơn trung bình 5 phiên."
    assert enforce_gtgd_baseline_pct(t, ctx) == t


def test_gtgd_bare_direction_close_gated():
    # thiếu "tổng kết phiên" → không đụng (morning / mục khác)
    ctx = {"full_day_gtgd": 16523.1, "full_day_gtgd_cmp": {"avg5": 20000.0}}
    assert enforce_gtgd_baseline_pct(
        "GTGD cao hơn trung bình 5 phiên", ctx) == "GTGD cao hơn trung bình 5 phiên"


# ── Fix 4: enforce_sr_direction (S < close < R) ────────────────────────────

_SR_CTX = {"vnindex_tech": {
    "close": 1782.12, "ma20": 1844.9, "ma50": 1854.5, "ma200": 1769.7,
    "support_1": None, "support_2": None,
    "resistance_1": 1800.80, "resistance_2": 1822.95,
    "week_low": 1775.0, "week_high": 1810.0, "month_low": 1755.0,
    "low_52w": 1445.64}}


def test_sr_direction_pins_support_equal_close():
    # S2=1,782.12 = close (hỗ trợ = giá hiện tại) → pin về mức known dưới close;
    # sau đó pass xếp vai thấy S1 (1,445) SÂU hơn S2 (1,775) → hoán đổi
    t = ("thủng S1=1,445.64 → mục tiêu S2=1,782.12; hủy nếu vượt lại "
         "R1=1,800.80 → test R2=1,822.95")
    out = enforce_sr_direction(t, _SR_CTX)
    assert "S2=1,782.12" not in out                 # = close bị bắt
    assert "S1=1,775.00" in out and "S2=1,445.64" in out   # vai đã xếp đúng
    assert "R1=1,800.80" in out and "R2=1,822.95" in out   # đúng chiều, giữ
    assert enforce_sr_direction(out, _SR_CTX) == out       # idempotent


def test_sr_direction_swaps_inverted_roles():
    # User bắt 17/07 (close 15:33): "thủng S1=1,445.64 → mục tiêu S2=1,774.22"
    # — thủng mức SÂU mà mục tiêu CAO HƠN. S1 phải là hỗ trợ GẦN nhất → swap.
    ctx = {"vnindex_tech": {"close": 1782.12, "week_low": 1774.22,
                            "low_52w": 1445.64, "resistance_1": 1800.80,
                            "resistance_2": 1822.95}}
    t = "GIẢM — canh giảm nếu thủng S1=1,445.64 → mục tiêu S2=1,774.22"
    out = enforce_sr_direction(t, ctx)
    assert "thủng S1=1,774.22 → mục tiêu S2=1,445.64" in out
    assert enforce_sr_direction(out, ctx) == out           # idempotent
    # R ngược vai (R1 xa hơn R2) cũng swap
    t2 = "vượt R1=1,822.95 → test R2=1,800.80"
    assert enforce_sr_direction(t2, ctx) == "vượt R1=1,800.80 → test R2=1,822.95"
    # cặp đúng vai giữ nguyên
    t3 = "thủng S1=1,774.22 → về S2=1,445.64; vượt R1=1,800.80 → test R2=1,822.95"
    assert enforce_sr_direction(t3, ctx) == t3
    # mỗi vai NHIỀU giá trị khác nhau → không đoán, không swap
    t4 = "S1=1,774.22 … S1=1,770.00 … S2=1,445.64"
    assert enforce_sr_direction(t4, ctx) == t4


def test_sr_direction_ignores_stock_prices_and_valid_levels():
    # giá cổ phiếu ngoài dải chỉ số → không đụng
    assert enforce_sr_direction("R1=71,500 · S1=68,000", _SR_CTX) == \
        "R1=71,500 · S1=68,000"
    # S/R đúng chiều (pivot_labels đã pin) → no-op
    ctx = {"vnindex_tech": {"close": 1782.12, "week_low": 1775.0}}
    assert enforce_sr_direction("S1=1,770.00 → S2=1,755.00", ctx) == \
        "S1=1,770.00 → S2=1,755.00"


def test_sr_direction_noop_without_close_or_candidates():
    assert enforce_sr_direction("S2=1,782.12", {}) == "S2=1,782.12"
    # close có nhưng không mức known nào dưới → không pin (để nguyên)
    ctx = {"vnindex_tech": {"close": 1782.12, "resistance_1": 1800.0}}
    assert enforce_sr_direction("S1=1,900.00", ctx) == "S1=1,900.00"


def test_sr_direction_dedupes_same_level_two_roles():
    # Close 17/07: giá ở đáy 52w → S1 lẫn S2 cùng pin về low_52w ra
    # "thủng S1=1,445.64 → mục tiêu S2=1,445.64" (vô nghĩa) — cắt vế S2 thừa
    t = ("GIẢM, canh giảm nếu thủng S1=1,445.64 → mục tiêu S2=1,445.64; "
         "hủy nếu vượt lại R1=1,800.80")
    out = enforce_sr_direction(t, _SR_CTX)
    assert "S2=" not in out and "S1=1,445.64" in out
    assert "→ mục tiêu" not in out                  # cả cụm mũi tên bị cắt
    assert "R1=1,800.80" in out
    assert enforce_sr_direction(out, _SR_CTX) == out       # idempotent
    # dạng "→ về S2=X" trong mục kỹ thuật cũng bị cắt
    t2 = "thủng S1=1,445.64 → về S2=1,445.64"
    assert enforce_sr_direction(t2, _SR_CTX) == "thủng S1=1,445.64"
    # cặp KHÁC số giữ nguyên (không đụng)
    t3 = "thủng S1=1,770.00 → về S2=1,755.00"
    ctx3 = {"vnindex_tech": {"close": 1782.12, "week_low": 1775.0,
                             "month_low": 1755.0}}
    assert enforce_sr_direction(t3, ctx3) == t3


# ── Fix 5: caveat BUY-vs-bias ở telegram (lệnh mở append ngoài guard chain) ─

def test_telegram_buy_bias_caveat_logic():
    import unittest.mock as m
    import vnstock_telegram as tg
    with m.patch.object(tg, "_market_is_bearish", return_value=True):
        assert tg._has_buy_under_bear([{"action": "BUY"}, {"action": "SELL"}])
        assert not tg._has_buy_under_bear([{"action": "SELL"}])
    with m.patch.object(tg, "_market_is_bearish", return_value=False):
        assert not tg._has_buy_under_bear([{"action": "BUY"}])


def test_open_recs_block_appends_caveat_under_bear():
    import unittest.mock as m
    import vnstock_telegram as tg
    from vnstock_brief import _BUY_BIAS_CAVEAT
    fake_opens = [{"ticker": "GMD", "action": "BUY", "entry_price": 78,
                   "take_profit": 84, "cut_loss": 74, "horizon_days": 5,
                   "created_at": "2026-07-15T00:00:00"}]
    with m.patch("vnstock_memory.open_recommendations", return_value=fake_opens), \
         m.patch.object(tg, "_market_is_bearish", return_value=True):
        out = tg._open_recs_block()
        assert _BUY_BIAS_CAVEAT in out and "GMD" in out
    with m.patch("vnstock_memory.open_recommendations", return_value=fake_opens), \
         m.patch.object(tg, "_market_is_bearish", return_value=False):
        assert _BUY_BIAS_CAVEAT not in tg._open_recs_block()


# ── End-to-end: chuỗi guard đầy đủ trên 1 khối mang mọi lỗi 15/07 ───────────

def test_apply_brief_guards_end_to_end_1507():
    ctx = {
        "vnindex_tech": {"day_change_pct": 0.0, "close": 1782.12,
                         "ma200": 1769.7, "support_1": None, "support_2": None,
                         "resistance_1": 1800.80, "resistance_2": 1822.95,
                         "week_low": 1775.0, "month_low": 1755.0, "low_52w": 1445.64},
        "sectors": [{"Ngành": "Họ VIN", "NN 1T (tỷ)": 1496.0},
                    {"Ngành": "Ngân hàng", "NN 1T (tỷ)": -703.0}],
        "full_day_gtgd": 16523.1,
        "full_day_gtgd_cmp": {"avg5": 20000.0, "avg20": 18000.0, "prev": 17000.0},
    }
    body = (
        "## 🎯 TLDR\n"
        "**Kết quả phiên:** VNINDEX đóng cửa giảm 1.36% / GTGD 16,523.1 tỷ.\n"
        "## 📊 Tổng kết phiên\n"
        "GTGD đạt 16,523.1 tỷ, cao hơn trung bình 5 phiên gần nhất.\n"
        "## 📈 Mức kỹ thuật chốt phiên (VNINDEX)\n"
        "**Trigger ngày mai:** thủng S1=1,445.64 → về S2=1,782.12\n"
        "## 💰 Dòng tiền đáng chú ý\n"
        "NN mua ròng 1,496 tỷ đồng trong ngành Họ VIN (1 tuần), trong khi "
        "bán ròng 703 tỷ đồng trong ngành Ngân hàng.\n"
    )
    out = apply_brief_guards(body, ctx)
    assert "giảm 1.36%" not in out                       # fix 2
    assert "thấp hơn trung bình 5 phiên" in out          # fix 3
    assert "S2=1,782.12" not in out                      # fix 4
    assert "+1,496 tỷ đồng trong ngành Ngân hàng" not in out   # fix 1
    assert "703 tỷ đồng trong ngành Ngân hàng" in out
