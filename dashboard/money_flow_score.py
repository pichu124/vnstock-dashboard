"""dashboard/money_flow_score.py — chấm điểm dòng tiền + badge hiển thị.

Tách khỏi vnstock_dashboard 12/08 (xem dashboard/volume_profile.py cho lý do).
`score_bar_html` phụ thuộc trực tiếp `score_label` nên phải cùng file.
Khung HTML giữ nguyên (test assert theo substring); màu đi qua `dashboard.theme.TOKENS`.
"""
from __future__ import annotations

from dashboard.theme import TOKENS as _T


def compute_money_flow_score(nn_net: float, nn_median: float,
                              buy_ratio: float,
                              big_order_score: float = 0) -> float:
    """
    Tính money flow score (-100 đến +100).
    nn_net:          NN ròng cho mã này (tỷ VND)
    nn_median:       median |NN ròng| của toàn thị trường (dùng để normalize)
    buy_ratio:       buy/sell ratio (0-1)
    big_order_score: lệnh lớn score (-100 đến +100), 0 nếu chưa có data
    """
    # NN score: clamp nn_net / median * 50
    if nn_median > 0:
        nn_score = max(-100, min(100, (nn_net / nn_median) * 50))
    else:
        nn_score = 0

    # Buy/Sell score: 0.5 → 0, 0.7 → +40, 0.3 → -40
    bs_score = max(-100, min(100, (buy_ratio - 0.5) * 200))

    # BigOrder score: đã clamp -100~100 từ _fetch_order_stats_batch
    bo_score = max(-100, min(100, big_order_score))

    # Weighted combination: 40% NN + 35% BuySell + 25% BigOrder
    return round(0.40 * nn_score + 0.35 * bs_score + 0.25 * bo_score, 1)


def score_label(score: float) -> tuple:
    """Return (label, color_hex) cho money flow score."""
    if score > 30:
        return "VÀO", _T["up"]
    if score > 10:
        return "Vào nhẹ", _T["up_soft"]
    if score > -10:
        return "Trung lập", _T["text_muted"]
    if score > -30:
        return "Ra nhẹ", _T["down_soft"]
    return "RA", _T["down"]


def score_bar_html(score: float) -> str:
    """Render mini bar HTML cho score."""
    label, color = score_label(score)
    width = min(abs(score), 80)
    # Neo mép thanh ở vạch giữa: dương neo mép TRÁI (mọc sang phải), âm neo mép PHẢI.
    direction = "left" if score >= 0 else "right"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="width:80px;height:14px;background:{_T["border"]};border-radius:7px;'
        f'position:relative;overflow:hidden">'
        f'<div style="position:absolute;{direction}:50%;width:{width/2}%;height:100%;'
        f'background:{color};border-radius:7px"></div>'
        f'<div style="position:absolute;left:50%;width:1px;height:100%;'
        f'background:{_T["text_off"]}"></div></div>'
        f'<span style="color:{color};font-size:11px;font-weight:600;min-width:52px">'
        f'{label}</span></div>'
    )


# ── Subprocess launcher ──────────────────────────────────────────────────────
