"""Màu + chữ của dashboard — MỘT nguồn (thiết kế lại giao diện P1, `docs/THIET-KE-GIAO-DIEN.md` §4).

Thuần, không dính Streamlit: CSS chung, iframe chart LWC, bảng screener HTML,
Plotly và `.streamlit/config.toml` cùng đọc từ đây. Thêm màu = thêm token ở đây,
KHÔNG gõ mã hex trong file UI — lưới `tests/test_theme_tokens.py` đếm hex từng
file (chỉ được GIẢM) và canh `config.toml` khớp `TOKENS`.

Giá theo quy ước bảng điện VN (user chốt 30/10): xanh tăng · đỏ giảm · vàng
tham chiếu · tím trần · xanh lơ sàn. Màu nhấn là XANH DƯƠNG — xanh lá đã mang
nghĩa "tăng". Mọi chữ nhỏ ≥ 4,5:1 trên `bg` (test đo).

SÁNG/TỐI (P4): hai bảng `DARK`/`LIGHT` cùng bộ khoá. `TOKENS` là bảng ĐỘNG — mỗi lần
đọc trả màu của chế độ đang dùng ở LƯỢT CHẠY hiện tại (`set_mode`, script chính gọi
đầu mỗi lượt theo `st.context.theme.type`). Vì vậy đọc `TOKENS[...]` LÚC VẼ, đừng chép
ra hằng ở cấp module (hằng đó đứng yên ở màu tối). Chưa ai gọi `set_mode` ⇒ tối.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from types import MappingProxyType

DARK = MappingProxyType({
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

# Nền sáng: màu giá đậm hơn để chữ đạt 4,5:1 trên nền trắng (xanh #10b981 trên trắng chỉ
# 2,5:1). Vàng tham chiếu đổi sang hổ phách — vàng tươi trên trắng không đọc được.
LIGHT = MappingProxyType({
    "bg": "#f6f8fb",
    "surface": "#ffffff",
    "surface_2": "#eef2f7",
    "border": "#dfe5ee",
    "text_strong": "#0b1220",
    "text": "#1f2937",
    "text_muted": "#4b5563",
    "text_faint": "#5b6472",
    "text_off": "#9ca3af",
    "accent": "#2563eb",
    "accent_fill": "#2563eb",
    "link": "#1d4ed8",
    "category": "#7c3aed",
    "up": "#047857",
    "down": "#c81e1e",
    "ref": "#a15c07",
    "ceil": "#a21caf",
    "floor": "#0e7490",
    "up_soft": "#0f766e",
    "down_soft": "#b42318",
    "warn": "#b45309",
    "on_fill": "#ffffff",
    "on_light": "#111827",
})
PALETTES = MappingProxyType({"dark": DARK, "light": LIGHT})

# Chế độ theo LUỒNG: mỗi phiên Streamlit chạy script trong luồng riêng.
_local = threading.local()


_resolver = None   # hàm trả "dark"/"light" của lượt hiện tại — script chính đăng ký


def set_mode(mode) -> str:
    """Chọn bảng màu cho lượt chạy hiện tại ('dark'/'light'; lạ ⇒ 'dark'). Trả chế độ đã chọn."""
    m = mode if mode in PALETTES else "dark"
    _local.mode = m
    return m


def set_mode_resolver(fn) -> None:
    """Đăng ký cách HỎI chế độ khi luồng chưa được `set_mode` — vd `lambda: st.context.theme.type`.

    `@st.fragment(run_every=…)` chạy lại trên LUỒNG MỚI, thân script chính (nơi gọi set_mode)
    không chạy lượt đó ⇒ không có resolver thì fragment Live tô màu TỐI giữa trang sáng (review
    31/10: chữ volume 1,16:1). Giữ module thuần: Streamlit nằm trong hàm của người đăng ký."""
    global _resolver
    _resolver = fn


def current_mode() -> str:
    m = getattr(_local, "mode", None)
    if m is None:
        try:
            m = _resolver() if _resolver is not None else None
        except Exception:      # ngoài lượt Streamlit (thread pool, test) ⇒ không biết ⇒ tối
            m = None
        m = m if m in PALETTES else "dark"
        _local.mode = m        # mỗi lượt fragment một luồng mới ⇒ hỏi một lần mỗi luồng
    return m


class _Tokens(Mapping):
    """Bảng màu theo chế độ hiện tại — đọc như dict thường."""

    def __getitem__(self, key: str) -> str:
        return PALETTES[current_mode()][key]

    def __iter__(self):
        return iter(DARK)

    def __len__(self) -> int:
        return len(DARK)

    def __repr__(self) -> str:
        return f"TOKENS[{current_mode()}]"


TOKENS = _Tokens()


def series(palette: Mapping | None = None) -> tuple[str, ...]:
    """Thứ tự màu chuỗi phân loại (Plotly / Altair qua `chartCategoricalColors`)."""
    t = palette or TOKENS
    return (t["link"], t["warn"], t["category"], t["floor"],
            t["up_soft"], t["down_soft"], t["ceil"], t["text_muted"])


SERIES = series(DARK)   # bản tối — giữ tên cũ cho chỗ cần hằng

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
/* Nền app do theme Streamlit vẽ (config.toml [theme.dark]/[theme.light] = token `bg`).
   KHÔNG đè `.stApp` ở đây: đè là đứng yên ở chế độ của lượt trước khi user đổi giao diện
   trong menu ⋮ (Streamlit không chạy lại script) — và theme_watch_html đọc nền này. */
.st-key-_theme_sync, .st-key-_theme_watch {{ display: none !important; }}
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


THEME_SYNC_KEY = "_theme_sync"     # nút ẩn — bấm = chạy lại script
THEME_WATCH_KEY = "_theme_watch"   # container ẩn chứa iframe theo dõi


def theme_watch_html(mode: str, sync_key: str = THEME_SYNC_KEY) -> str:
    """iframe ẩn (components.html) theo dõi nền `.stApp` của trang cha.

    Đổi Light/Dark trong menu ⋮ thì Streamlit KHÔNG chạy lại script (issue #11920) ⇒ CSS,
    bảng HTML, chart vẫn tô theo chế độ cũ (đo 31/10: chữ sáng trên nền sáng). Nền lệch
    `mode` của lượt này ⇒ bấm nút ẩn `sync_key` MỘT lần ⇒ lượt mới đọc
    `st.context.theme.type` đã cập nhật (đo 31/10). Không lặp: iframe chỉ dựng lại khi
    `mode` đổi, cờ `fired` giữ một lần bấm cho mỗi chế độ đích.
    """
    m = "dark" if mode == "dark" else "light"
    return f"""<script>
(function () {{
  var MODE = "{m}", fired = null, P = window.parent;
  function kind() {{
    var app = P.document.querySelector('[data-testid="stApp"]');
    if (!app) return null;
    var c = (P.getComputedStyle(app).backgroundColor.match(/[\\d.]+/g) || []).map(Number);
    if (c.length < 3 || (c.length > 3 && c[3] === 0)) return null;
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 < 0.5 ? "dark" : "light";
  }}
  setInterval(function () {{
    try {{
      var now = kind();
      if (!now || now === MODE || fired === now) return;
      var btn = P.document.querySelector('.st-key-{sync_key} button');
      if (btn) {{ fired = now; btn.click(); }}
    }} catch (e) {{}}
  }}, 700);
}})();
</script>"""


def category_colors(n: int) -> list[str]:
    """n màu phân loại KHÔNG lặp (pie nhiều lát): chuỗi phân loại rồi bản nhạt của nó."""
    base = list(series())
    out = base + [rgba(c, 0.55) for c in base]
    return [out[i % len(out)] for i in range(n)]


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
