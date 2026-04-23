"""Streamlit dashboard tab modules.

Each tab lives in its own file and exposes a single ``render_*_tab()``
function. The top-level ``vnstock_dashboard.py`` router imports the
relevant module lazily inside the tab-dispatch block, so a failure in
one tab doesn't bring the whole dashboard down.

Tabs extracted so far:
* ``portfolio_tab`` — 💼 Portfolio (position tracker with live P&L)

Not yet extracted: Screener, Phân tích, Thị trường, Dòng Tiền. System
Health ships from ``vnstock_health`` (same pattern, older module).
"""
