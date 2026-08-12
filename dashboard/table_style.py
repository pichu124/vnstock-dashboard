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

GRAY_EMPTY = "#4b5563"      # ô trống / "—"
GRAY_UNPARSEABLE = "#6b7280"  # có giá trị nhưng không parse nổi
GRAY_NEUTRAL = "#9ca3af"
DEFAULT_COLOR = "#d1d5db"

_PCT_COLUMNS = ("1D%", "5D%", "20D%", "BB%", "52W%")
_MACD_COLORS = {
    "BUY": "#10b981", "BULL": "#34d399",
    "SELL": "#ef4444", "BEAR": "#f87171",
}

_GREEN, _RED = "#10b981", "#ef4444"
_GREEN_SOFT, _RED_SOFT = "#6ee7b7", "#fca5a5"


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
            return _GREEN if v > 0 else (_RED if v < 0 else GRAY_NEUTRAL)
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
        return "#e5e7eb"
    if col == "MACD":
        return _MACD_COLORS.get(str(val).upper(), GRAY_NEUTRAL)
    if col == "Trend":
        up = str(val).upper()
        return _GREEN if up == "UP" else (_RED if up in ("DOWN", "DN") else GRAY_NEUTRAL)
    if col == "Ticker":
        return "#60a5fa"
    if col == "Ngành":
        return "#a78bfa"
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
