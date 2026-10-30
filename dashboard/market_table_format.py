"""Định dạng + tô màu bảng ngành (tab Thị trường) — thuần hàm, không Streamlit.

Tách khỏi `dashboard/market_tab.py` (12/08, mục ④ audit 06/08). Trước đó đây là
5 closure lồng trong hàm render 2.544 dòng: test không với tới, và `_amp_color`
bị **chép nguyên bản** thành `_dd_amp_color` cho khối drill-down — hai bản y hệt
nhau chỉ khác biến closure. Đúng họ lỗi vừa dọn ở mục ③: hai bản sống song song
thì sớm muộn cũng trôi khỏi nhau.

Cách sửa: thang màu nhận (vmin, vrange) làm THAM SỐ thay vì bắt qua closure,
nên bảng tổng và bảng drill-down dùng CHUNG một hàm với hai thang khác nhau.

Quy ước số: EN (`{:,.2f}` — phẩy nghìn, chấm thập phân), theo CLAUDE.md.
"""
from __future__ import annotations

import math

from dashboard.theme import TOKENS as _T

# ── Nhóm cột ────────────────────────────────────────────────────────────────
PRICE_PCT_COLS = ("Giá 1T %", "Giá 1M %", "Giá 3M %")
AMP_COLS = ("Biên 1T (%)", "Biên 1M (%)", "Biên 3M (%)")
NET_BS_COLS = ("Net BS 1T", "Net BS 1M", "Net BS 3M", "Net BS 6M")
NN_COLS = ("NN 1T (tỷ)", "NN 1M (tỷ)", "NN 3M (tỷ)")
AVG_VOL_COLS = ("AVG 5-10 %", "AVG 10-20 %")
FREE_VOL_COLS = ("Vol 5/Free %", "Vol 10/Free %", "Vol 20/Free %")
VOL_AVG_COLS = ("Vol Avg 5", "Vol Avg 10", "Vol Avg 20")
MONEY_COLS = ("Vốn hoá (tỷ)", "GTGD TB (tỷ)", "Freefloat (tỷ)")

# Từ token (P1 thiết kế lại giao diện). MISSING từng là #4b5563 (2,6:1 — dưới chuẩn đọc).
GREEN, RED, GRAY = _T["up"], _T["down"], _T["text_muted"]
MISSING = _T["text_faint"]
DEFAULT = _T["text"]

# Vol 5/20 %: trên 110 là dòng tiền đang vào, dưới 90 là đang rút.
_VOL_RATIO_HOT, _VOL_RATIO_COLD = 110, 90


def _is_nan(val) -> bool:
    return isinstance(val, float) and math.isnan(val)


def scale_range(values) -> tuple:
    """(min, max, range) cho thang màu. Rỗng hoặc phẳng → range = 1.

    Idiom này lặp 4 lần trong `market_tab` (biên độ / vol-freefloat × bảng tổng /
    drill-down). Range không bao giờ được 0: chia 0 khi mọi ngành cùng một giá
    trị là ca THẬT, không phải giả định.
    """
    vals = [v for v in (values or []) if v is not None and not _is_nan(v)]
    if not vals:
        return 0, 1, 1
    vmin, vmax = min(vals), max(vals)
    return vmin, vmax, (vmax - vmin if vmax > vmin else 1)


def amp_color(val, vmin, vrange) -> str:
    """Biên độ → gradient xanh lá (thấp) → vàng (TB) → đỏ (cao)."""
    t = max(0.0, min(1.0, (float(val) - vmin) / vrange))
    if t < 0.5:
        s = t / 0.5                                    # xanh lá → vàng
        r = int(16 + (245 - 16) * s)
        g = int(185 + (158 - 185) * s)
        b = int(129 + (11 - 129) * s)
    else:
        s = (t - 0.5) / 0.5                            # vàng → đỏ
        r = int(245 + (239 - 245) * s)
        g = int(158 + (68 - 158) * s)
        b = int(11 + (68 - 11) * s)
    return f"rgb({r},{g},{b})"


def fvol_colors(val, vmin, vrange) -> tuple:
    """(nền, chữ) — gradient vàng nhạt → cam → đỏ theo tỷ lệ vol/freefloat.
    Nền càng đậm thì chữ phải đổi sang trắng, nếu không là không đọc nổi."""
    t = max(0.0, min(1.0, (float(val) - vmin) / vrange))
    if t < 0.5:
        s = t / 0.5
        r = int(254 + (249 - 254) * s)
        g = int(252 + (115 - 252) * s)
        b = int(232 + (22 - 232) * s)
    else:
        s = (t - 0.5) / 0.5
        r = int(249 + (153 - 249) * s)
        g = int(115 + (27 - 115) * s)
        b = int(22 + (27 - 22) * s)
    return f"rgb({r},{g},{b})", (_T["on_light"] if t < 0.35 else _T["on_fill"])


def color_val(val, col, amp_min=0, amp_range=1) -> str:
    """Màu chữ của một ô theo giá trị + tên cột."""
    if val is None or _is_nan(val):
        return MISSING
    if col in PRICE_PCT_COLS + NN_COLS + NET_BS_COLS + AVG_VOL_COLS:
        v = float(val)
        return GREEN if v > 0 else (RED if v < 0 else GRAY)
    if col in FREE_VOL_COLS:
        return DEFAULT              # ô này tô nền riêng bằng fvol_colors
    if col == "Vol 5/20 %":
        v = float(val)
        return GREEN if v > _VOL_RATIO_HOT else (RED if v < _VOL_RATIO_COLD else DEFAULT)
    if col in AMP_COLS:
        return amp_color(val, amp_min, amp_range)
    return DEFAULT


def fmt(val, col) -> str:
    """Chuỗi hiển thị của một ô. Thiếu dữ liệu → "—" (không phải 0)."""
    if val is None:
        return "—"
    if isinstance(val, str):
        return val                                    # cột text như Ngành
    try:
        if math.isnan(float(val)):
            return "—"
    except (TypeError, ValueError):
        return str(val)
    v = float(val)
    if col in PRICE_PCT_COLS:
        return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
    if col in NN_COLS:
        return f"+{v:,.1f}" if v > 0 else f"{v:,.1f}"
    if col in NET_BS_COLS:
        return f"+{v:,.1f}M" if v > 0 else f"{v:,.1f}M"
    if col in VOL_AVG_COLS:
        return f"{v:,.1f}M"
    if col in AVG_VOL_COLS:
        return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
    if col in FREE_VOL_COLS:
        return f"{v:.2f}%"
    if col == "Vol 5/20 %":
        return f"{v:.0f}%"
    if col in MONEY_COLS:
        return f"{v:,.0f}"
    if col in AMP_COLS:
        return f"{v:.1f}%"
    return str(int(v)) if v == int(v) else f"{v:.1f}"
