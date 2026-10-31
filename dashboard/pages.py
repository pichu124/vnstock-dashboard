"""Sổ đăng ký trang cho `st.navigation(position="top")` (thiết kế lại giao diện P2, §5a).

Dữ liệu THUẦN — không import Streamlit, không import module trang (import trang là dựng
UI). `vnstock_dashboard.py` biến mỗi dòng thành `st.Page`; `scripts/ui_snapshots.py` đọc
`url_path` để chụp từng trang; test canh url không trùng, đúng một trang mặc định, hàm
trang có thật.

Thêm trang = thêm một `PageSpec`. `module="<main>"` = hàm nằm trong vnstock_dashboard.py
(cần biến của script chính: dữ liệu screener, nút pipeline…).
"""
from __future__ import annotations

from typing import NamedTuple


class PageSpec(NamedTuple):
    section: str
    title: str
    icon: str          # Material Symbols — emoji bị Windows 10 vẽ ô vuông (vết 🪙 10/10)
    url_path: str      # không dấu, gạch ngang; trang mặc định bỏ qua (URL gốc)
    module: str
    func: str


MAIN = "<main>"
DEFAULT_URL = "tong-quan"   # user chốt 30/10: mở app vào Tổng quan thị trường

PAGES: tuple[PageSpec, ...] = (
    PageSpec("Thị trường", "Tổng quan", ":material/monitoring:", "tong-quan",
             "dashboard.market_tab", "render_market_tab"),
    PageSpec("Thị trường", "Dòng tiền", ":material/account_balance_wallet:", "dong-tien",
             "dashboard.money_flow_tab", "render_money_flow_tab"),
    PageSpec("Thị trường", "Phái sinh NN", ":material/swap_vert:", "phai-sinh-nn",
             "dashboard.futures_foreign_tab", "render_futures_foreign_tab"),
    PageSpec("Thị trường", "Hàng hoá & Tiền tệ", ":material/currency_exchange:", "hang-hoa-tien-te",
             "dashboard.assets_tab", "render_assets_tab"),
    PageSpec("Thị trường", "Vĩ mô", ":material/public:", "vi-mo",
             "dashboard.macro_tab", "render_macro_subtab"),
    PageSpec("Cổ phiếu", "Bộ lọc", ":material/filter_alt:", "bo-loc", MAIN, "_page_screener"),
    PageSpec("Cổ phiếu", "Phân tích mã", ":material/candlestick_chart:", "phan-tich",
             "dashboard.analysis_tab", "render_analysis_tab"),
    PageSpec("Tin & Báo cáo", "Tin theo mã", ":material/newspaper:", "tin-tuc",
             "dashboard.news_tab", "render_ticker_news"),
    PageSpec("Tin & Báo cáo", "Báo cáo tuần", ":material/description:", "bao-cao-tuan",
             "dashboard.rates_report_tab", "render_rates_report_subtab"),
    PageSpec("Tin & Báo cáo", "Báo cáo", ":material/library_books:", "bao-cao",
             "dashboard.reports_tab", "render_reports_subtab"),
    PageSpec("Danh mục", "Danh mục", ":material/work:", "danh-muc",
             "dashboard.portfolio_tab", "render_portfolio_tab"),
    PageSpec("Danh mục", "Phân bổ", ":material/pie_chart:", "phan-bo",
             "dashboard.allocation_tab", "render_allocation_subtab"),
    PageSpec("Hệ thống", "Hệ thống", ":material/monitor_heart:", "he-thong", MAIN, "_page_system"),
)


def sections() -> dict[str, list[PageSpec]]:
    """Nhóm → trang, giữ thứ tự khai báo (thứ tự menu)."""
    out: dict[str, list[PageSpec]] = {}
    for p in PAGES:
        out.setdefault(p.section, []).append(p)
    return out


def by_url(url_path: str) -> PageSpec | None:
    return next((p for p in PAGES if p.url_path == url_path), None)
