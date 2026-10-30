"""Lưới canh hệ màu + chữ (thiết kế lại giao diện P1, `docs/THIET-KE-GIAO-DIEN.md` §4).

Bốn thứ dễ trôi mà mắt không bắt được tới khi user mở app:
1. `.streamlit/config.toml` lệch `dashboard/theme.TOKENS` (sửa một bên quên bên kia).
2. Font khai trong config mà file không có trong `static/fonts/` ⇒ rơi về font hệ thống IM LẶNG.
3. Màu chữ trượt chuẩn đọc (4,5:1) — chính lỗi #6b7280/#4b5563 cũ.
4. Hex mới gõ thẳng vào file UI thay vì đi qua token — đếm từng file, ngân sách chỉ GIẢM.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from dashboard import theme
from dashboard.theme import DARK, LIGHT, PALETTES, TOKENS

ROOT = Path(__file__).resolve().parent.parent
tomllib = pytest.importorskip("tomllib")
_CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
_HEX6 = re.compile(r"^#[0-9a-f]{6}$")


# ── 1. config.toml ↔ TOKENS ─────────────────────────────────────────────────

_CONFIG_TO_TOKEN = {
    "primaryColor": "accent",
    "backgroundColor": "bg",
    "secondaryBackgroundColor": "surface",
    "textColor": "text",
    "borderColor": "border",
    "linkColor": "link",
    "greenColor": "up",
    "redColor": "down",
    "yellowColor": "ref",
    "orangeColor": "warn",
    "violetColor": "category",
    "blueColor": "accent",
    "grayColor": "text_muted",
    "dataframeBorderColor": "border",
    "dataframeHeaderBackgroundColor": "surface",
}


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_tokens_are_lowercase_hex_and_same_keys(mode):
    pal = PALETTES[mode]
    assert set(pal) == set(DARK), "hai bảng phải cùng bộ khoá — thiếu khoá là KeyError khi đổi chế độ"
    for name, val in pal.items():
        assert _HEX6.match(val), f"{mode}.{name}={val!r} phải là #rrggbb chữ thường"


def test_both_modes_declared_with_dark_fallback():
    """Trước P4 thiếu `base` ⇒ máy để chế độ sáng dựng theme sáng dưới CSS tối (chụp 30/10).
    Từ P4: hai bộ màu thật, Streamlit theo hệ điều hành; `base` chỉ là dự phòng."""
    assert _CONFIG["theme"]["base"] == "dark"
    assert {"dark", "light"} <= set(_CONFIG["theme"])


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("key,token", sorted(_CONFIG_TO_TOKEN.items()))
def test_config_color_matches_token(mode, key, token):
    assert _CONFIG["theme"][mode][key].lower() == PALETTES[mode][token], (
        f"config.toml [theme.{mode}] {key} lệch dashboard/theme.{mode.upper()}[{token!r}] — sửa CẢ HAI")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_chart_colors_match_series(mode):
    got = [c.lower() for c in _CONFIG["theme"][mode]["chartCategoricalColors"]]
    assert got == list(theme.series(PALETTES[mode]))


def test_tokens_follow_the_mode_of_this_run():
    """TOKENS là bảng ĐỘNG: script chính gọi set_mode mỗi lượt theo st.context.theme.type."""
    try:
        assert theme.set_mode("light") == "light" and TOKENS["bg"] == LIGHT["bg"]
        assert theme.set_mode("lạ") == "dark" and TOKENS["bg"] == DARK["bg"]
        assert theme.set_mode(None) == "dark"
    finally:
        theme.set_mode("dark")


def test_mode_is_per_thread():
    """Mỗi phiên Streamlit chạy script ở luồng riêng — phiên sáng không được nhuộm phiên tối."""
    import threading
    seen = {}
    theme.set_mode("light")
    try:
        t = threading.Thread(target=lambda: seen.update(bg=TOKENS["bg"]))
        t.start(); t.join()
        assert seen["bg"] == DARK["bg"] and TOKENS["bg"] == LIGHT["bg"]
    finally:
        theme.set_mode("dark")


def test_render_time_lookup_not_frozen_at_import():
    """Hằng màu cấp module đứng yên ở màu tối — 3 module tô bảng phải đổi theo chế độ."""
    from dashboard.market_table_format import color_val
    from dashboard.sparkline import sparkline_svg
    from dashboard.table_style import cell_color
    try:
        theme.set_mode("light")
        assert cell_color("1D%", "+1.0%") == LIGHT["up"]
        assert color_val(-1.0, "Giá 1T %") == LIGHT["down"]
        assert LIGHT["up"] in sparkline_svg([0.0, 1.0])
        assert LIGHT["surface"] in theme.app_css() and DARK["surface"] not in theme.app_css()
    finally:
        theme.set_mode("dark")


@pytest.fixture
def _resolver_restored():
    saved = theme._resolver
    yield
    theme.set_mode_resolver(saved)


def _in_new_thread(fn):
    """Như lượt `@st.fragment(run_every=…)`: luồng MỚI, thân script chính (set_mode) không chạy."""
    import threading
    out = {}
    t = threading.Thread(target=lambda: out.update(v=fn()))
    t.start(); t.join()
    return out["v"]


def test_fragment_thread_asks_resolver_for_mode(_resolver_restored):
    """Review 31/10: fragment Live ở trang SÁNG vẽ màu TỐI (luồng mới ⇒ mode mặc định 'dark')."""
    theme.set_mode_resolver(lambda: "light")
    assert _in_new_thread(lambda: TOKENS["bg"]) == LIGHT["bg"]
    assert _in_new_thread(lambda: theme.series()[0]) == theme.series(LIGHT)[0]
    # set_mode của script chính vẫn thắng resolver
    assert _in_new_thread(lambda: (theme.set_mode("dark"), TOKENS["bg"])[1]) == DARK["bg"]


@pytest.mark.parametrize("resolver", [None, lambda: None, lambda: "lạ", lambda: 1 / 0],
                         ids=["none", "returns-none", "returns-junk", "raises"])
def test_resolver_unknown_or_failing_falls_back_to_dark(_resolver_restored, resolver):
    theme.set_mode_resolver(resolver)
    assert _in_new_thread(theme.current_mode) == "dark"


def test_main_script_registers_mode_resolver():
    src = (ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8")
    assert "_set_theme_mode_resolver(lambda: st.context.theme.type)" in src


# Tên ở dashboard.theme trả màu THEO CHẾ ĐỘ — gọi lúc import là đóng băng màu tối.
_MODE_NAMES = {"TOKENS", "SERIES", "series", "pct_color", "price_color", "status_color",
               "category_colors", "lwc_palette", "app_css", "current_mode"}


def _theme_aliases(tree: ast.Module) -> set[str]:
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "dashboard.theme":
            names |= {a.asname or a.name for a in n.names if a.name in _MODE_NAMES}
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= {a.asname for a in n.names if a.asname and a.name.endswith("theme")}
            names |= {"theme" for a in n.names if a.name == "theme" and not a.asname}
    return names


def _eager_reads(node, aliases: set[str]) -> list[int]:
    """Dòng đọc màu THEO CHẾ ĐỘ ngay khi biểu thức chạy (bỏ qua thân lambda — chạy sau)."""
    hits, stack = [], [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Lambda):
            continue
        if isinstance(n, ast.Name) and n.id in aliases:
            hits.append(n.lineno)
        stack.extend(ast.iter_child_nodes(n))
    return hits


def _import_time_files() -> list[Path]:
    """Module nạp MỘT lần (thân module không chạy lại mỗi lượt) — script chính thì chạy lại nên miễn."""
    files = [ROOT / "vnstock_freshness.py", ROOT / "vnstock_health.py"]
    files += sorted((ROOT / "dashboard").glob("*.py"))
    return [f for f in files if f.name != "theme.py"]


def test_eager_read_scanner_catches_frozen_constants():
    src = ("from dashboard.theme import TOKENS as _T, series\n"
           "_A = _T['up']\n_B = {'x': series()[0]}\n_OK = lambda: _T['up']\n"
           "def f(c=_T['down']):\n    return _T['up']\n")
    tree = ast.parse(src)
    al = _theme_aliases(tree)
    hits = [ln for st in tree.body if not isinstance(st, ast.ImportFrom)
            for ln in (_eager_reads(st.value, al) if isinstance(st, ast.Assign)
                       else _eager_reads(st.args, al) if isinstance(st, ast.FunctionDef) else [])]
    assert sorted(hits) == [2, 3, 5]


@pytest.mark.parametrize("path", _import_time_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_mode_colors_frozen_at_import(path):
    """Hằng màu cấp module (vd `_SENTIMENT_BADGE`, `_C1 = SERIES[0]`) nạp lúc import = màu TỐI mãi
    mãi. Đọc lúc vẽ: hàm nhỏ trả màu, hoặc lưu TÊN token rồi tra `TOKENS[tên]` khi vẽ."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = _theme_aliases(tree)
    bad = []
    for st in tree.body:
        if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and st.value is not None:
            bad += _eager_reads(st.value, aliases)
        elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bad += _eager_reads(st.args, aliases)            # giá trị mặc định chạy lúc import
            bad += [ln for d in st.decorator_list for ln in _eager_reads(d, aliases)]
        elif isinstance(st, ast.ClassDef):
            bad += [ln for s in st.body if isinstance(s, (ast.Assign, ast.AnnAssign)) and s.value
                    for ln in _eager_reads(s.value, aliases)]
    assert not bad, f"{path.name}: đọc màu lúc import ở dòng {sorted(set(bad))}"


def test_category_colors_do_not_repeat_for_many_slices():
    """Pie danh mục > 8 ngành: 8 màu theme lặp lát thứ 9 (review 31/10)."""
    cols = theme.category_colors(12)
    assert len(cols) == 12 and len(set(cols)) == 12
    assert cols[:len(theme.series())] == list(theme.series())


# ── 2. Font tự host ─────────────────────────────────────────────────────────

def test_static_serving_on_for_fonts():
    assert _CONFIG["server"]["enableStaticServing"] is True


def test_font_faces_match_theme_and_files_exist():
    faces = _CONFIG["theme"]["fontFaces"]
    got = [(f["family"], str(f["weight"]), f["url"]) for f in faces]
    want = [(fam, w, f"app/static/fonts/{fn}") for fam, w, fn in theme.FONT_FILES]
    assert got == want
    for _, _, fn in theme.FONT_FILES:
        path = ROOT / "static" / "fonts" / fn
        assert path.is_file() and path.stat().st_size > 10_000, f"thiếu font {path}"
    assert (ROOT / "static" / "fonts" / "OFL.txt").is_file(), "OFL bắt buộc đi kèm font IBM Plex"


def test_config_font_families_are_the_hosted_ones():
    assert _CONFIG["theme"]["font"].startswith(theme.FONT_SANS)
    assert _CONFIG["theme"]["codeFont"].startswith(theme.FONT_MONO)


def test_font_face_css_covers_every_file():
    css = theme.font_face_css()
    for fam, w, fn in theme.FONT_FILES:
        assert f"{theme.STATIC_FONT_URL}{fn}" in css
        assert f"font-family:'{fam}'" in css and f"font-weight:{w}" in css


# ── 3. Độ tương phản ────────────────────────────────────────────────────────

_READABLE = ("text_strong", "text", "text_muted", "text_faint", "link", "category",
             "up", "down", "ref", "ceil", "floor", "up_soft", "down_soft", "warn")


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("token", _READABLE)
@pytest.mark.parametrize("ground", ["bg", "surface"])
def test_readable_text_passes_wcag_aa(mode, token, ground):
    pal = PALETTES[mode]
    ratio = theme.contrast(pal[token], pal[ground])
    assert ratio >= 4.5, f"[{mode}] {token} trên {ground} chỉ {ratio:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_button_text_on_accent_fill_passes(mode):
    assert theme.contrast(PALETTES[mode]["on_fill"], PALETTES[mode]["accent_fill"]) >= 4.5


def test_white_on_dark_accent_fails_hence_accent_fill():
    """Chữ trắng trên #3b82f6 chỉ 3,7:1 — lý do có `accent_fill`."""
    assert theme.contrast(DARK["on_fill"], DARK["accent"]) < 4.5


def test_contrast_reference_values():
    assert theme.contrast("#ffffff", "#000000") == pytest.approx(21.0)
    assert theme.contrast("#6b7280", "#0a0e1a") == pytest.approx(3.98, abs=0.01)


# ── Hàm màu ─────────────────────────────────────────────────────────────────

class TestPriceColor:
    """Bảng điện VN: trần/sàn thắng tăng/giảm; đứng giá = vàng."""

    def test_board_colors(self):
        assert theme.price_color(56300, 52700, 56300, 49050) == TOKENS["ceil"]
        assert theme.price_color(49050, 52700, 56300, 49050) == TOKENS["floor"]
        assert theme.price_color(53700, 52700, 56300, 49050) == TOKENS["up"]
        assert theme.price_color(52400, 52700, 56300, 49050) == TOKENS["down"]
        assert theme.price_color(52700, 52700, 56300, 49050) == TOKENS["ref"]

    def test_without_ceil_floor_falls_back_to_direction(self):
        assert theme.price_color(56300, 52700) == TOKENS["up"]

    @pytest.mark.parametrize("price,ref", [(None, 1.0), (1.0, None), (float("nan"), 1.0)])
    def test_missing_does_not_guess(self, price, ref):
        assert theme.price_color(price, ref) == TOKENS["text_faint"]


class TestPctColor:

    def test_sign(self):
        assert theme.pct_color(0.5) == TOKENS["up"]
        assert theme.pct_color(-0.5) == TOKENS["down"]

    def test_zero_defaults_gray_and_session_is_ref(self):
        assert theme.pct_color(0.0) == TOKENS["text_muted"]
        assert theme.pct_color(0.0, flat="ref") == TOKENS["ref"]

    @pytest.mark.parametrize("v", [None, float("nan")])
    def test_missing(self, v):
        assert theme.pct_color(v) == TOKENS["text_faint"]


@pytest.mark.parametrize("level,token", [
    ("ok", "up"), ("green", "up"), ("warn", "warn"), ("yellow", "warn"),
    ("error", "down"), ("red", "down"), ("off", "text_muted"), ("skipped", "text_muted"),
    (None, "text_muted"), ("lạ", "text_muted"),
])
def test_status_color(level, token):
    assert theme.status_color(level) == TOKENS[token]


def test_rgba():
    assert theme.rgba("#10b981", 0.6) == "rgba(16,185,129,0.6)"


def test_lwc_palette_values_are_colors():
    for k, v in theme.lwc_palette().items():
        assert _HEX6.match(v) or v.startswith("rgba("), f"lwc_palette[{k}]={v!r}"


def test_app_css_uses_only_token_colors():
    css_hex = set(re.findall(r"#[0-9a-f]{6}", theme.app_css()))
    assert css_hex <= set(DARK.values())
    assert "@import" not in theme.app_css(), "font đi [[theme.fontFaces]], không @import Google Fonts"


def test_app_css_does_not_pin_app_background():
    """Đè nền `.stApp` = đứng yên ở chế độ cũ khi user đổi giao diện trong menu ⋮; nền do
    config.toml lo, và theme_watch_html đọc chính nền đó để biết phải chạy lại."""
    assert ".stApp {" not in theme.app_css().replace(" ", " ")
    assert "st-key-_theme_sync" in theme.app_css()


@pytest.mark.parametrize("mode,other", [("dark", "light"), ("light", "dark")])
def test_theme_watch_clicks_sync_button_once_on_mismatch(mode, other):
    js = theme.theme_watch_html(mode)
    assert f'MODE = "{mode}"' in js and ".st-key-_theme_sync button" in js
    assert "fired === now" in js and "fired = now" in js      # một lần mỗi chế độ đích
    assert theme.theme_watch_html("lạ").count('MODE = "light"') == 1


def test_theme_module_is_pure():
    """Test + CSS + chart cùng import nó — cấm dính Streamlit."""
    tree = ast.parse((ROOT / "dashboard" / "theme.py").read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m and m.split(".")[0] == "streamlit" for m in mods)


def test_light_mode_toggle_removed():
    """Toggle cũ chỉ đè 9 selector (nửa sáng nửa tối) — bỏ ở P1, làm thật ở P4."""
    src = (ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8")
    assert 'key="light_mode"' not in src
    assert "THEMES[" not in src


# ── 4. Ngân sách hex — chỉ GIẢM ─────────────────────────────────────────────
# Đếm mã #rrggbb[aa] trong CHUỖI (comment không tính) của từng file UI. Thêm màu
# ⇒ thêm token ở dashboard/theme.py. Gỡ hex ⇒ HẠ con số ở đây (test đỏ nếu quên,
# để con số không nằm cao chờ hex quay lại). Mốc HEAD f5029d7 trước P1: 582.

# P3 (31/10): MỌI file UI về 0 — ngân sách rỗng. Thêm hex vào file UI nào cũng đỏ.
HEX_BUDGET: dict[str, int] = {}

_HEX = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?(?![0-9a-zA-Z])")
_STR_TOKENS = {tokenize.STRING} | (
    {tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())


def _ui_files() -> list[Path]:
    files = [ROOT / "vnstock_dashboard.py", ROOT / "vnstock_health.py"]
    files += sorted((ROOT / "dashboard").glob("*.py"))
    return [f for f in files if f.name != "theme.py"]


def _hex_in_strings(path: Path) -> int:
    toks = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
    return sum(len(_HEX.findall(t.string)) for t in toks if t.type in _STR_TOKENS)


def test_hex_counter_skips_comments():
    src = 'x = "#10b981"  # #ef4444 chỉ là ghi chú\ny = f"color:{c};bg:#111827"\n'
    toks = tokenize.generate_tokens(io.StringIO(src).readline)
    assert sum(len(_HEX.findall(t.string)) for t in toks if t.type in _STR_TOKENS) == 2


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_hex_budget_only_shrinks(path):
    rel = path.relative_to(ROOT).as_posix()
    got, budget = _hex_in_strings(path), HEX_BUDGET.get(rel, 0)
    assert got <= budget, (f"{rel}: {got} mã hex > ngân sách {budget} — dùng "
                           f"dashboard.theme.TOKENS thay vì gõ hex")
    assert got == budget, (f"{rel}: đã gỡ bớt hex ({got} < {budget}) — hạ HEX_BUDGET[{rel!r}] "
                           f"xuống {got} để hex không quay lại được")


def test_budget_lists_only_real_files():
    real = {p.relative_to(ROOT).as_posix() for p in _ui_files()}
    assert set(HEX_BUDGET) <= real
