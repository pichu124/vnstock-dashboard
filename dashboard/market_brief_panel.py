"""Khối **🤖 AI Market Brief** của tab Thị trường — bộ điều phối 5 panel con.

Tách khỏi `dashboard/market_tab.py` (12/08, mục ④), rồi tự tách tiếp thành 5
panel con cùng ngày: khối gốc 1.172 dòng vượt xa mốc 800 của repo, mà đo bằng
AST thì 5 panel chỉ dính nhau qua `st` — tức chúng vốn đã rời nhau, chỉ là
nằm chung một hàm.

File này giữ đúng hai việc: dò xem `vnstock_brief` có dùng được không, và gọi
5 panel theo thứ tự. Panel nào hỏng thì tự nuốt lỗi bên trong panel đó.
"""
from __future__ import annotations

from dashboard.brief_accuracy_panel import render_accuracy_widget
from dashboard.brief_agent_settings import render_agent_settings
from dashboard.brief_history_panel import render_brief_history
from dashboard.brief_run_panel import render_brief_runner
from dashboard.brief_strategy_panel import render_strategy_panel


def render_brief_panel() -> None:
    """Render khối AI Market Brief. Gọi từ `render_market_tab` (nhánh có data)."""
    import streamlit as st

    st.markdown("---")
    st.markdown("#### 🤖 AI Market Brief")

    try:
        # Giữ NGUYÊN danh sách tên như bản cũ: thiếu bất kỳ tên nào cũng phải
        # tính là "brief không dùng được", không riêng gì thiếu cả file.
        from vnstock_brief import (  # noqa: F401
            AGENT_REGISTRY, build_agents, generate_brief,
            load_agent_configs, save_agent_configs,
        )
    except ImportError:
        st.warning("Không tìm thấy `vnstock_brief.py`. Đảm bảo file tồn tại trong thư mục gốc.")
        return

    render_agent_settings()
    render_brief_runner()
    render_accuracy_widget()
    render_brief_history()
    render_strategy_panel()
