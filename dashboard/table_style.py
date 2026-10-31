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

# Màu lấy từ token LÚC VẼ (P1 màu, P4 sáng/tối): hằng cấp module sẽ đứng yên ở màu tối.
# Ô trống/không parse nổi từng là #4b5563/#6b7280 (2,6:1 và 4,0:1) ⇒ nay `text_faint`.
_PCT_COLUMNS = ("1D%", "5D%", "20D%", "BB%", "52W%")
# Đổi 1 PHIÊN = so tham chiếu ⇒ 0% tô VÀNG như bảng điện; đổi nhiều phiên thì 0 chỉ
# là "không đổi" — để xám.
_SESSION_PCT = "1D%"
_MACD_TOKENS = {"BUY": "up", "BULL": "up_soft", "SELL": "down", "BEAR": "down_soft"}


def _as_pct(val) -> float:
    """"+1.23%" → 1.23. Ném ValueError/TypeError nếu không phải số."""
    return float(str(val).replace("%", "").replace("+", ""))


def cell_color(col, val) -> str:
    """Màu chữ cho một ô của bảng screener."""
    if not val or val == "—":
        return _T["text_faint"]
    if col in _PCT_COLUMNS:
        try:
            v = _as_pct(val)
            if v == 0:
                # Chuỗi đã làm tròn 1 chữ số: "+0.0%"/"-0.0%" là có đổi (mã giá cao lên/xuống
                # 1 bước giá ≈ 0,04%) — giữ CHIỀU theo dấu; chỉ "0.0%" mới là đứng giá.
                sign = str(val).strip()[:1]
                if sign in "+-":
                    return _T["up"] if sign == "+" else _T["down"]
                return _T["ref"] if col == _SESSION_PCT else _T["text_muted"]
            return _T["up"] if v > 0 else _T["down"]
        except (ValueError, TypeError):
            return _T["text_faint"]
    if col == "RSI":
        try:
            v = float(val)
        except (ValueError, TypeError):
            return _T["text_faint"]
        if v < 30:
            return _T["up"]
        if v > 70:
            return _T["down"]
        if v < 40:
            return _T["up_soft"]
        if v > 60:
            return _T["down_soft"]
        return _T["text"]
    if col == "MACD":
        return _T[_MACD_TOKENS.get(str(val).upper(), "text_muted")]
    if col == "Trend":
        up = str(val).upper()
        return _T["up"] if up == "UP" else (_T["down"] if up in ("DOWN", "DN") else _T["text_muted"])
    if col == "Ticker":
        return _T["link"]
    if col == "Ngành":
        return _T["category"]
    return _T["text"]


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
