"""Sổ đăng ký trang `st.navigation` (giao diện P2): url duy nhất, một trang mặc định,
hàm trang có thật — đọc bằng AST, không import module trang (import là dựng UI)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from dashboard.pages import DEFAULT_URL, MAIN, PAGES, by_url, sections

ROOT = Path(__file__).resolve().parent.parent


def _top_level_funcs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_url_paths_unique_and_slug_shaped():
    urls = [p.url_path for p in PAGES]
    assert len(urls) == len(set(urls))
    for u in urls:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", u), u


def test_titles_unique_within_section():
    for sec, pages in sections().items():
        titles = [p.title for p in pages]
        assert len(titles) == len(set(titles)), sec


def test_default_page_is_market_overview():
    """User chốt 30/10: mở app vào Tổng quan thị trường (thay Screener)."""
    p = by_url(DEFAULT_URL)
    assert p is not None and p.title == "Tổng quan" and p.section == "Thị trường"


def test_five_sections_in_menu_order():
    assert list(sections()) == ["Thị trường", "Cổ phiếu", "Tin & Báo cáo", "Danh mục", "Hệ thống"]


def test_icons_are_material_not_emoji():
    """Emoji nhãn tab bị Windows 10 vẽ ô vuông (🪙, 10/10) — nav dùng Material Symbols."""
    for p in PAGES:
        assert re.fullmatch(r":material/[a-z0-9_]+:", p.icon), p


def test_regrouped_subtabs_from_news():
    """Gom nhóm §5a (user đồng ý 30/10): Vĩ mô → Thị trường, Phân bổ → Danh mục."""
    sec = {p.title: p.section for p in PAGES}
    assert sec["Vĩ mô"] == "Thị trường" and sec["Phân bổ"] == "Danh mục"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.url_path)
def test_page_function_exists(page):
    path = (ROOT / "vnstock_dashboard.py" if page.module == MAIN
            else ROOT / (page.module.replace(".", "/") + ".py"))
    assert path.is_file(), path
    assert page.func in _top_level_funcs(path), f"{path.name} thiếu hàm {page.func}"


@pytest.mark.parametrize("page", [p for p in PAGES if p.module != MAIN], ids=lambda p: p.url_path)
def test_page_functions_need_no_arguments(page):
    """st.Page gọi hàm KHÔNG đối số."""
    tree = ast.parse((ROOT / (page.module.replace(".", "/") + ".py")).read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == page.func)
    a = fn.args
    required = len(a.args) - len(a.defaults) + sum(1 for d in a.kw_defaults if d is None)
    assert required == 0, f"{page.func} cần {required} đối số"
