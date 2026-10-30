"""Thành phần UI dùng chung (thiết kế lại giao diện P2/P3, `docs/THIET-KE-GIAO-DIEN.md` §4c).

Thay HTML tự vẽ rải rác bằng vài khối có tên: tiêu đề trang, ô số liệu, chấm trạng thái,
báo lỗi một câu, và CHẾ ĐỘ CHẨN ĐOÁN — nơi duy nhất được hiện stack trace, JSON thô,
khối "Debug". Màu đi qua `dashboard.theme`.
"""
from __future__ import annotations

import html

from dashboard.theme import TOKENS as _T, status_color

# Streamlit import LƯỜI trong từng hàm: test thay `sys.modules["streamlit"]` bằng bản giả
# SAU khi module này đã nạp — bind ở đầu file là đọc nhầm st thật.

# Cờ thường (KHÔNG phải key widget): công tắc ở trang Hệ thống dùng key riêng
# `diag_mode_toggle` rồi gán tay cờ này — widget rời cây render là bị Streamlit
# dọn state (bài học Live Mode 17/08).
DIAG_FLAG = "diag_mode"


def diag_on() -> bool:
    """Đang bật chế độ chẩn đoán (trang Hệ thống)?"""
    import streamlit as st
    return bool(st.session_state.get(DIAG_FLAG, False))


def page_header(title: str, subtitle: str | None = None) -> None:
    """Tiêu đề trang (cấp 1) + một dòng phụ (phiên dữ liệu, nguồn…)."""
    import streamlit as st
    sub = (f'<div style="margin-top:2px;font-size:13px;color:{_T["text_faint"]}">'
           f'{html.escape(subtitle)}</div>') if subtitle else ""
    st.markdown(
        f'<div style="margin:0 0 14px"><div style="font-size:24px;font-weight:600;'
        f'color:{_T["text_strong"]};letter-spacing:-0.01em;line-height:1.25">'
        f'{html.escape(title)}</div>{sub}</div>',
        unsafe_allow_html=True)


def section(title: str, caption: str | None = None) -> None:
    """Tiêu đề mục (cấp 2): 16px đậm vừa — thay `###`/`####`/`######`/.section-title lẫn lộn."""
    import streamlit as st
    cap = (f'<div style="font-size:12px;color:{_T["text_faint"]};margin-top:2px">'
           f'{html.escape(caption)}</div>') if caption else ""
    st.markdown(
        f'<div style="margin:18px 0 8px"><div style="font-size:16px;font-weight:600;'
        f'color:{_T["text_strong"]}">{html.escape(title)}</div>{cap}</div>',
        unsafe_allow_html=True)


def empty_state(message: str, hint: str | None = None) -> None:
    """Trạng thái RỖNG thống nhất (P5): một câu vì sao trống + việc nên làm — thay cho
    `st.warning("Không có dữ liệu.")` vàng rực như báo lỗi."""
    import streamlit as st
    tip = (f'<div style="margin-top:4px;font-size:13px;color:{_T["text_muted"]}">'
           f'{html.escape(hint)}</div>') if hint else ""
    st.markdown(
        f'<div style="padding:16px 18px;border:1px dashed {_T["border"]};border-radius:8px;'
        f'background:{_T["surface"]}"><div style="color:{_T["text"]}">{html.escape(message)}</div>'
        f'{tip}</div>', unsafe_allow_html=True)


def status_dot(level: str, size: int = 8) -> str:
    """HTML chấm tròn theo mức ok/warn/error/off."""
    c = status_color(level)
    return (f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'border-radius:50%;background:{c};flex:none"></span>')


def show_error(message: str, exc: BaseException | None = None) -> None:
    """Một câu tiếng Việt cho người dùng; chi tiết kỹ thuật chỉ khi bật chẩn đoán."""
    import streamlit as st
    st.error(message)
    if exc is not None and diag_on():
        st.exception(exc)
    elif exc is not None:
        st.caption("Chi tiết kỹ thuật: bật **Chế độ chẩn đoán** ở trang Hệ thống.")
