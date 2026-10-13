"""Tiện ích chung của hệ guard brief — dùng bởi cả 3 nhóm guard.

Tách 12/08 (mục ④): `vnstock_brief_guards.py` 2.646 dòng chia theo CHỦ ĐỀ
(khối nội dung / con số / chữ nghĩa). File này giữ đúng phần cả ba nhóm đều
cần, để ba nhóm không phải import chéo nhau (import chéo = vòng chờ sẵn).

Đọc số kiểu VN/EN, cắt một mục của brief, nhận diện dòng tiêu đề — và (P1b-1,
#19) MỘT nguồn "thị trường phòng thủ": floor cũ từ 2 tín hiệu header
(`_bias_floor_dir`) + cách đọc nó từ ctx (`floor_dir`, `is_defensive`). Brief
(`_market_floor`, khối prompt), guard và Telegram quyết "phòng thủ" qua
`is_defensive`; chạy bóng 3 khung dùng chung luật `_bias_floor_dir` — P1b chỉ
cần đổi `is_defensive` ở một chỗ.
"""
from __future__ import annotations

import re as _re


def _parse_vn_number(s: str) -> float | None:
    """Convert '1.815,42' / '1,815.42' / '1815' to float. None on failure."""
    s = s.strip()
    if not s:
        return None
    # Vietnamese: dot=thousand sep, comma=decimal. EN: comma=thousand, dot=decimal.
    # Heuristic: if both, the LAST occurrence is the decimal sep.
    has_dot   = "." in s
    has_comma = "," in s
    try:
        if has_dot and has_comma:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif has_comma:
            s = s.replace(",", ".") if s.count(",") == 1 and len(s.split(",")[1]) <= 2 else s.replace(",", "")
        elif has_dot and len(s.split(".")[1]) >= 3:
            # "1.815" with 3-digit suffix → thousand sep
            s = s.replace(".", "")
        return float(s)
    except (ValueError, IndexError):
        return None


def _bias_floor_dir(momentum: int | None, regime_score: int | None) -> str | None:
    """Force a TLDR Bias direction when the headline signals are strongly
    one-sided and not in conflict.

    Inputs are the two signals shown in the brief header: Tâm lý `momentum`
    (-100..100) and Regime `score` (signed, out of ~7). Returns "GIẢM", "TĂNG",
    or None (let the agent decide). Thresholds: momentum ±50 or regime ±3.
    """
    bear = (momentum is not None and momentum <= -50) or \
           (regime_score is not None and regime_score <= -3)
    bull = (momentum is not None and momentum >= 50) or \
           (regime_score is not None and regime_score >= 3)
    if bear and not bull:
        return "GIẢM"
    if bull and not bear:
        return "TĂNG"
    return None


def floor_dir(ctx: dict | None) -> str | None:
    """Chiều floor cũ đã dựng vào ctx ("GIẢM" | "TĂNG" | None). Chịu được ctx
    None, thiếu khoá, hoặc `bias_floor: None` (cách đọc cũ ném AttributeError)."""
    return ((ctx or {}).get("bias_floor") or {}).get("dir")


def is_defensive(ctx: dict | None) -> bool:
    """Thị trường đang PHÒNG THỦ (chặn mua bắt đáy / cảnh báo lệnh MUA)? Hôm nay
    = floor cũ ra GIẢM; P1b mở rộng thành tập cha ở đúng chỗ này."""
    return floor_dir(ctx) == "GIẢM"


_SECTION_EMOJIS = ("🎯", "📊", "📈", "🏆", "💰", "📋", "⚠️", "📅", "💡", "🔧", "⚡", "🔮", "🌐", "📰", "📌", "📚", "🧭",
                   "🪙", "🔭")


def _is_section_start(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("##") or s.startswith(_SECTION_EMOJIS)


def brief_section(text: str, marker: str) -> str:
    """Một mục của brief (header + body) theo `marker` trong dòng header —
    vd brief_section(output, "🌐") lấy mục Vĩ mô, "🎯" lấy TLDR. Dùng cho
    sub-tab Vĩ mô (dashboard) đọc lại brief đã lưu trong memory; "" khi
    không thấy. Cùng ranh giới mục với chuỗi guard (_is_section_start)."""
    if not text:
        return ""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if marker in l and _is_section_start(l)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines))
                if _is_section_start(lines[i])), len(lines))
    return "\n".join(lines[start:end]).strip()


_PIVOT_LABEL_RE = _re.compile(r"\b(S1|S2|R1|R2)\s*=\s*([0-9][0-9.,]*[0-9]|[0-9])")
