"""Sparkline SVG nội tuyến cho bảng ngành — thuần chuỗi, không dính Streamlit.

Tách khỏi `dashboard/market_tab.py` (12/08). Trước đó là closure lồng trong
hàm render 2.544 dòng nên test không với tới được.

Vẽ alpha (lợi suất vượt VNINDEX) 30 phiên: xanh nếu điểm cuối dương, đỏ nếu âm,
kèm đường 0 nét đứt để mắt bắt được vượt/thua ngay.
"""
from __future__ import annotations

import math

from dashboard.theme import TOKENS as _T, rgba as _rgba

_EMPTY = f'<span style="color:{_T["text_faint"]};font-size:10px">—</span>'

_UP_LINE, _DOWN_LINE = _T["up"], _T["down"]
_UP_FILL, _DOWN_FILL = _rgba(_T["up"], 0.13), _rgba(_T["down"], 0.13)
_ZERO_LINE = _T["text_off"]


def _clean(values) -> list:
    """Bỏ None/NaN. NaN phải lọc bằng `x != x` (so sánh NaN luôn False) —
    dùng `math.isnan` sẽ ném TypeError với giá trị không phải số."""
    out = []
    for v in values or []:
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        out.append(v)
    return out


def sparkline_svg(values: list, width: int = 80, height: int = 28) -> str:
    """Trả SVG nội tuyến. Dưới 2 điểm dữ liệu → dấu "—" (không vẽ đường giả)."""
    vals = _clean(values)
    if len(vals) < 2:
        return _EMPTY

    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1.0
    n = len(vals)
    # y của đường 0, kẹp vào [2, h-2] để không dính mép
    zero_y = max(2, min(height - 2, height - (-mn / rng) * height))
    pts = [(round(i / (n - 1) * width), round(height - (v - mn) / rng * height))
           for i, v in enumerate(vals)]
    pt_str = " ".join(f"{x},{y}" for x, y in pts)

    last_val = vals[-1]
    lc = _UP_LINE if last_val >= 0 else _DOWN_LINE
    fc = _UP_FILL if last_val >= 0 else _DOWN_FILL

    # Polygon tô từ đường 0 xuống/lên đường giá
    fill_pts = [(pts[0][0], int(zero_y))] + pts + [(pts[-1][0], int(zero_y))]
    fp_str = " ".join(f"{x},{y}" for x, y in fill_pts)
    last_disp = f"{last_val:+.1f}%"

    return (f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
            f'style="display:inline-block;vertical-align:middle;overflow:visible">'
            f'<polygon points="{fp_str}" fill="{fc}" stroke="none"/>'
            f'<polyline points="{pt_str}" fill="none" stroke="{lc}" stroke-width="1.5" stroke-linejoin="round"/>'
            f'<line x1="0" y1="{zero_y:.0f}" x2="{width}" y2="{zero_y:.0f}" '
            f'stroke="{_ZERO_LINE}" stroke-width="0.5" stroke-dasharray="3,3"/>'
            f'<text x="{width+2}" y="{height//2+4}" font-size="9" fill="{lc}" '
            f'font-family="IBM Plex Mono,monospace">{last_disp}</text>'
            f'</svg>')
