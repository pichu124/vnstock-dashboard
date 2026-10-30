"""Màu + chữ của dashboard — MỘT nguồn (thiết kế lại giao diện P1, `docs/THIET-KE-GIAO-DIEN.md` §4).

Thuần, không dính Streamlit: CSS chung, iframe chart LWC, bảng screener HTML,
Plotly và `.streamlit/config.toml` cùng đọc từ đây. Thêm màu = thêm token ở đây,
KHÔNG gõ mã hex trong file UI — lưới `tests/test_theme_tokens.py` đếm hex từng
file (chỉ được GIẢM) và canh `config.toml` khớp `TOKENS`.

Giá theo quy ước bảng điện VN (user chốt 30/10): xanh tăng · đỏ giảm · vàng
tham chiếu · tím trần · xanh lơ sàn. Màu nhấn là XANH DƯƠNG — xanh lá đã mang
nghĩa "tăng". Mọi chữ nhỏ ≥ 4,5:1 trên `bg` (test đo).
"""
from __future__ import annotations

import math
from types import MappingProxyType

TOKENS = MappingProxyType({
    # nền
    "bg": "#0a0e1a",           # nền app + nền chart
    "surface": "#111827",      # thẻ, sidebar, header bảng
    "surface_2": "#1a2234",    # hover, vạch hàng
    "border": "#1f2937",
    # chữ
    "text_strong": "#f9fafb",  # con số chính
    "text": "#e5e7eb",
    "text_muted": "#9ca3af",   # nhãn
    "text_faint": "#8b95a5",   # chú thích, giờ cập nhật — thay #6b7280 (4,0:1) và #4b5563 (2,6:1)
    "text_off": "#6b7280",     # chữ của nút/ô đang KHOÁ — không dùng cho chữ đọc được
    # nhấn
    "accent": "#3b82f6",       # gạch chân trang đang chọn, đường chỉ số, viền ô đang gõ
    "accent_fill": "#2563eb",  # NỀN nút chính — chữ trắng 5,2:1 (trên #3b82f6 chỉ 3,7)
    "link": "#60a5fa",
    "category": "#a78bfa",     # nhãn ngành / nhóm
    # giá — bảng điện VN
    "up": "#10b981",
    "down": "#ef4444",
    "ref": "#fbbf24",
    "ceil": "#d946ef",
    "floor": "#22d3ee",
    "up_soft": "#34d399",      # chữ trên nền nhạt / tín hiệu yếu
    "down_soft": "#f87171",
    # trạng thái
    "warn": "#f59e0b",
    # chữ trên nền đặc
    "on_fill": "#ffffff",
    "on_light": "#111827",
})

# Thứ tự màu cho chuỗi phân loại (Plotly / Altair qua `chartCategoricalColors`).
SERIES = (TOKENS["link"], TOKENS["warn"], TOKENS["category"], TOKENS["floor"],
          TOKENS["up_soft"], TOKENS["down_soft"], TOKENS["ceil"], TOKENS["text_muted"])

FONT_SANS = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"
# (họ, độ đậm, file trong static/fonts/) — bản "complete" của IBM, đủ dấu tiếng Việt.
FONT_FILES = (
    (FONT_SANS, "400", "IBMPlexSans-Regular.woff2"),
    (FONT_SANS, "500", "IBMPlexSans-Medium.woff2"),
    (FONT_SANS, "600", "IBMPlexSans-SemiBold.woff2"),
    (FONT_SANS, "700", "IBMPlexSans-Bold.woff2"),
    (FONT_MONO, "400", "IBMPlexMono-Regular.woff2"),
    (FONT_MONO, "500", "IBMPlexMono-Medium.woff2"),
    (FONT_MONO, "600", "IBMPlexMono-SemiBold.woff2"),
)
# `server.enableStaticServing` phục vụ <repo>/static/ ở /app/static/. Đường TUYỆT
# ĐỐI vì iframe `components.html` (srcdoc) không có thư mục gốc riêng.
STATIC_FONT_URL = "/app/static/fonts/"

# Plotly: nền trong suốt để chart nằm đúng trên thẻ/nền app. Phần còn lại (chữ,
# lưới, chuỗi màu) do theme Streamlit lo — nó đọc `.streamlit/config.toml`.
PLOTLY_BG = MappingProxyType({"paper_bgcolor": "rgba(0,0,0,0)",
                              "plot_bgcolor": "rgba(0,0,0,0)"})

_STATUS = {"ok": "up", "green": "up", "pass": "up",
           "warn": "warn", "yellow": "warn", "reconnecting": "warn",
           "error": "down", "red": "down", "fail": "down"}


def rgba(hex_color: str, alpha: float) -> str:
    """`#rrggbb` + độ mờ → `rgba(r,g,b,a)` (nền nhạt của chip, cột KL…)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:g})"


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def pct_color(v, flat: str = "text_muted") -> str:
    """Màu theo DẤU của một mức đổi: dương xanh, âm đỏ, bằng 0 = token `flat`.

    Đổi 1 phiên so tham chiếu thì gọi `flat="ref"` (bảng điện tô vàng); đổi nhiều
    phiên thì 0 chỉ là "không đổi" — để xám.
    """
    if _is_missing(v):
        return TOKENS["text_faint"]
    v = float(v)
    if v > 0:
        return TOKENS["up"]
    if v < 0:
        return TOKENS["down"]
    return TOKENS[flat]


def price_color(price, ref, ceil=None, floor=None) -> str:
    """Màu bảng điện của một GIÁ so tham chiếu/trần/sàn của phiên.

    Chạm trần/sàn thắng tăng/giảm. Thiếu giá hoặc tham chiếu ⇒ xám chú thích,
    không đoán chiều.
    """
    if _is_missing(price) or _is_missing(ref):
        return TOKENS["text_faint"]
    p, r = float(price), float(ref)
    if not _is_missing(ceil) and p >= float(ceil):
        return TOKENS["ceil"]
    if not _is_missing(floor) and p <= float(floor):
        return TOKENS["floor"]
    if p > r:
        return TOKENS["up"]
    if p < r:
        return TOKENS["down"]
    return TOKENS["ref"]


def status_color(level) -> str:
    """ok/warn/error (và tên cũ green/yellow/red) → màu trạng thái; còn lại (off,
    skipped, lạ) = xám NHÃN — badge dùng màu này cho cả CHỮ nên phải đọc được."""
    return TOKENS[_STATUS.get(str(level or "").lower(), "text_muted")]


def contrast(fg: str, bg: str) -> float:
    """Tỉ lệ tương phản WCAG 2.x giữa hai mã `#rrggbb`."""
    def lum(h: str) -> float:
        h = h.lstrip("#")
        chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def font_face_css(url_prefix: str = STATIC_FONT_URL) -> str:
    """@font-face cho iframe (chart, bảng): Streamlit chỉ nạp font cho trang chính."""
    return "".join(
        f"@font-face{{font-family:'{fam}';src:url('{url_prefix}{f}') format('woff2');"
        f"font-weight:{w};font-style:normal;font-display:swap;}}"
        for fam, w, f in FONT_FILES)


def app_css() -> str:
    """Khối CSS chung của dashboard (thay khối hex rời ở `vnstock_dashboard.py`).

    Giữ nguyên tên class + cỡ chữ cũ — P1 chỉ đổi màu/chữ, bố cục để P3.
    """
    t = TOKENS
    return f"""
html, body, [class*="css"] {{ font-family: '{FONT_SANS}', sans-serif; }}
.stApp {{ background: {t['bg']}; }}
.metric-card {{ background: {t['surface']}; border: 1px solid {t['border']};
  border-radius: 8px; padding: 16px 20px; text-align: center; }}
.metric-card .label {{ font-size: 11px; color: {t['text_faint']}; text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 6px; }}
.metric-card .value {{ font-family: '{FONT_MONO}', monospace; font-size: 26px; font-weight: 500;
  color: {t['text_strong']}; }}
.metric-card .sub {{ font-size: 11px; color: {t['text_faint']}; margin-top: 4px; }}
.preset-tag {{ display: inline-block; background: {t['border']}; color: {t['text_muted']};
  font-size: 11px; padding: 3px 10px; border-radius: 20px; margin: 2px; cursor: pointer; }}
.preset-tag.active {{ background: {rgba(t['accent'], 0.18)}; color: {t['link']};
  border: 1px solid {t['accent']}; }}
.up   {{ color: {t['up']} !important; }}
.down {{ color: {t['down']} !important; }}
.neutral {{ color: {t['text_muted']} !important; }}
.updated-at {{ font-size: 11px; color: {t['text_faint']}; font-family: '{FONT_MONO}', monospace; }}
[data-testid="stDataFrame"] {{ border: 1px solid {t['border']}; border-radius: 8px; }}
.card {{ background: {t['surface']}; border: 1px solid {t['border']};
  border-radius: 10px; padding: 16px 20px; margin-bottom: 12px; }}
.card-title {{ font-size: 11px; color: {t['text_faint']}; text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 8px; }}
.section-title {{ font-size: 13px; font-weight: 500; color: {t['text_faint']};
  text-transform: uppercase; letter-spacing: 0.06em; margin: 20px 0 10px; }}
.fscore-bar {{ height: 8px; border-radius: 4px; background: {t['border']}; margin: 6px 0; }}
.fscore-fill {{ height: 8px; border-radius: 4px; }}
.tag {{ display: inline-block; padding: 2px 10px; border-radius: 20px;
  font-size: 11px; font-weight: 500; margin: 2px; }}
/* P2 — thanh trạng thái + nhãn mục sidebar */
.vn-strip {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 22px; font-size: 13px;
  color: {t['text']}; }}
.vn-strip-item {{ display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }}
.vn-chip {{ padding: 1px 8px; border-radius: 10px; background: {t['border']}; color: {t['text']}; }}
.vn-side-label {{ font-size: 12px; color: {t['text_muted']}; text-transform: uppercase;
  letter-spacing: 0.06em; margin: 4px 0 6px; }}
"""


def lwc_palette() -> dict:
    """Màu cho iframe chart Lightweight Charts 4 panel (`render_chart`).

    Chỉ là MÀU — logical-range / whitespace warmup của chart không đi qua đây.
    Màu đường chỉ báo giữ như cũ (người dùng đã quen), chỉ gom về một chỗ.
    """
    t = TOKENS
    return {
        "bg": t["bg"], "text": t["text_muted"], "label": t["text_faint"],
        "grid": t["surface_2"], "border": t["border"],
        "crosshair": t["text_off"], "crosshair_label": t["border"],
        "up": t["up"], "down": t["down"], "wick_up": "#059669", "wick_down": "#dc2626",
        "vol_up": rgba(t["up"], 0.6), "vol_down": rgba(t["down"], 0.6),
        "hist_up": rgba(t["up"], 0.8), "hist_down": rgba(t["down"], 0.8),
        "rsi_hi": rgba(t["down"], 0.4), "rsi_lo": rgba(t["up"], 0.4),
        "last": t["ref"], "o": t["text"], "h": t["up"], "l": t["down"], "c": t["ref"],
        "ema9": t["link"], "ema21": "#c084fc", "ema50": "#fbbf24", "ema200": "#f97316",
        "bb": "rgba(139,92,246,0.5)", "bb_mid": "rgba(139,92,246,0.25)",
        "vwap": "#e879f9", "vwap_1": "rgba(232,121,249,0.3)", "vwap_2": "rgba(232,121,249,0.15)",
        "rsi": t["category"], "macd": t["link"], "signal": "#f97316",
    }
