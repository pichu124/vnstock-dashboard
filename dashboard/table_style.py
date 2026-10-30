"""Tô màu / độ đậm cho bảng screener HTML — thuần hàm, không dính Streamlit.

Tách khỏi `vnstock_dashboard.py` (12/08). Trước đó hai hàm này là closure lồng
trong hàm render bảng, nên test chỉ có REPLICA — và replica ĐÃ TRÔI: nó thiếu
nhánh `Trend`, thiếu `Ticker`/`Ngành`, và bắt `except Exception` rộng trong khi
đồ thật đã siết còn `(ValueError, TypeError)`.

Quy ước bắt `(ValueError, TypeError)` chứ không phải `Exception` là CÓ CHỦ Ý:
`float(val)` chỉ hỏng theo hai kiểu đó; bắt rộng sẽ nuốt cả KeyboardInterrupt
từ `__str__` của object lạ.
"""
from __future__ import annotations

from dashboard.theme import TOKENS as _T

# Màu lấy từ token (P1 thiết kế lại giao diện). Ô trống/không parse nổi từng là
# #4b5563/#6b7280 — 2,6:1 và 4,0:1 trên nền, dưới chuẩn đọc ⇒ nay `text_faint`.
GRAY_EMPTY = _T["text_faint"]        # ô trống / "—"
GRAY_UNPARSEABLE = _T["text_faint"]  # có giá trị nhưng không parse nổi
GRAY_NEUTRAL = _T["text_muted"]
DEFAULT_COLOR = _T["text"]

_PCT_COLUMNS = ("1D%", "5D%", "20D%", "BB%", "52W%")
# Đổi 1 PHIÊN = so tham chiếu ⇒ 0% tô VÀNG như bảng điện; đổi nhiều phiên thì 0 chỉ
# là "không đổi" — để xám.
_SESSION_PCT = "1D%"
_MACD_COLORS = {
    "BUY": _T["up"], "BULL": _T["up_soft"],
    "SELL": _T["down"], "BEAR": _T["down_soft"],
}

_GREEN, _RED = _T["up"], _T["down"]
_GREEN_SOFT, _RED_SOFT = _T["up_soft"], _T["down_soft"]


def _as_pct(val) -> float:
    """"+1.23%" → 1.23. Ném ValueError/TypeError nếu không phải số."""
    return float(str(val).replace("%", "").replace("+", ""))


def cell_color(col, val) -> str:
    """Màu chữ cho một ô của bảng screener."""
    if not val or val == "—":
        return GRAY_EMPTY
    if col in _PCT_COLUMNS:
        try:
            v = _as_pct(val)
            if v == 0:
                # Chuỗi đã làm tròn 1 chữ số: "+0.0%"/"-0.0%" là có đổi (mã giá cao lên/xuống
                # 1 bước giá ≈ 0,04%) — giữ CHIỀU theo dấu; chỉ "0.0%" mới là đứng giá.
                sign = str(val).strip()[:1]
                if sign in "+-":
                    return _GREEN if sign == "+" else _RED
                return _T["ref"] if col == _SESSION_PCT else GRAY_NEUTRAL
            return _GREEN if v > 0 else _RED
        except (ValueError, TypeError):
            return GRAY_UNPARSEABLE
    if col == "RSI":
        try:
            v = float(val)
        except (ValueError, TypeError):
            return GRAY_UNPARSEABLE
        if v < 30:
            return _GREEN
        if v > 70:
            return _RED
        if v < 40:
            return _GREEN_SOFT
        if v > 60:
            return _RED_SOFT
        return _T["text"]
    if col == "MACD":
        return _MACD_COLORS.get(str(val).upper(), GRAY_NEUTRAL)
    if col == "Trend":
        up = str(val).upper()
        return _GREEN if up == "UP" else (_RED if up in ("DOWN", "DN") else GRAY_NEUTRAL)
    if col == "Ticker":
        return _T["link"]
    if col == "Ngành":
        return _T["category"]
    return DEFAULT_COLOR


def cell_weight(col, val) -> str:
    """`font-weight` cho một ô — làm nổi tín hiệu mạnh (RSI cực trị, BUY/SELL)."""
    if col == "Ticker":
        return "600"
    if col in _PCT_COLUMNS:
        try:
            return "500" if _as_pct(val) != 0 else "400"
        except (ValueError, TypeError):
            return "400"
    if col == "RSI":
        try:
            v = float(val)
        except (ValueError, TypeError):
            return "400"
        return "700" if (v < 30 or v > 70) else "400"
    if col == "MACD" and str(val).upper() in ("BUY", "SELL"):
        return "700"
    return "400"
