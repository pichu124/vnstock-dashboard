"""Streamlit dashboard — tab modules + helper thuần.

Hai loại file ở đây:

* **Tab**: mỗi file một tab, expose đúng một hàm ``render_*_tab()``. Router
  ``vnstock_dashboard.py`` import lazy trong khối dispatch, nên một tab hỏng
  không kéo sập cả dashboard.
  Đã tách: ``market_tab``, ``analysis_tab``, ``news_tab``, ``macro_tab``,
  ``money_flow_tab``, ``screener_tab``, ``portfolio_tab``, ``allocation_tab``,
  ``reports_tab``, ``rates_report_tab``. System Health ở ``vnstock_health``
  (cùng pattern, module cũ hơn).

* **Helper thuần** (không import streamlit): logic kéo ra khỏi
  ``vnstock_dashboard.py`` để TEST IMPORT ĐƯỢC — module gốc gọi
  ``st.set_page_config()`` ở cấp module nên test không import nổi, hệ quả là
  suốt thời gian dài test chỉ chạy trên REPLICA chép tay (và replica trôi).
  Gồm: ``volume_profile``, ``money_flow_score``, ``chart_indicators``,
  ``table_style``, ``watchlist_io``.
  Cùng mục đích, ở cấp gốc: ``vnstock_price_units``, ``vnstock_console_launch``,
  ``vnstock_sectors``.
"""
