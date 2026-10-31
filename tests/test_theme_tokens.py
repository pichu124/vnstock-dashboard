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


# Tên ở dashboard.theme trả màu THEO CHẾ ĐỘ — dùng lúc import là đóng băng màu tối.
#   bảng động (TOKENS, và `_T` mà ui.py xuất lại): chỉ khi TRA (`_T["up"]`, `_T.get`) — truyền nguyên bảng thì vô hại;
#   hằng (SERIES = bản tối): mọi lần nhắc; hàm: khi GỌI.
_MAPPING_NAMES = {"TOKENS", "_T"}
_CONST_NAMES = {"SERIES"}
_FUNC_NAMES = {"series", "pct_color", "price_color", "status_color", "category_colors",
               "lwc_palette", "app_css", "current_mode"}


def _theme_names(tree: ast.Module) -> dict[str, str]:
    """Tên cục bộ → tên gốc, cho mọi `from …theme import X [as Y]` (kể cả `.theme`)."""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[-1] == "theme":
            for a in n.names:
                if a.name in _MAPPING_NAMES | _CONST_NAMES | _FUNC_NAMES:
                    out[a.asname or a.name] = a.name
    return out


def _frozen_reads(tree: ast.Module) -> list[int]:
    """Dòng đọc màu theo chế độ NGAY LÚC IMPORT: đi mọi nút cấp module (cả if/try/with/for, thân
    class, mặc định tham số, decorator), bỏ thân hàm, thân lambda và khối `if __name__ == "__main__"`."""
    names = _theme_names(tree)
    hits = []

    def kind(n):   # tên gốc nếu nút là một tên theo chế độ (Name hoặc thuộc tính `x.TOKENS`, `ui._T`)
        if isinstance(n, ast.Name):
            return names.get(n.id)
        if isinstance(n, ast.Attribute) and n.attr in _MAPPING_NAMES | _CONST_NAMES | _FUNC_NAMES:
            return n.attr
        return None

    def visit(n, parent=None):
        if isinstance(n, ast.Lambda):
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for x in [n.args, *n.decorator_list]:
                visit(x, n)
            return
        if (isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"):
            return
        k = kind(n)
        if k in _CONST_NAMES:
            hits.append(n.lineno)
        elif k in _MAPPING_NAMES and (
                (isinstance(parent, ast.Subscript) and parent.value is n)
                or (isinstance(parent, ast.Attribute) and parent.value is n)):
            hits.append(n.lineno)
        elif k in _FUNC_NAMES and isinstance(parent, ast.Call) and parent.func is n:
            hits.append(n.lineno)
        for c in ast.iter_child_nodes(n):
            if not isinstance(c, (ast.Import, ast.ImportFrom)):
                visit(c, n)

    for stmt in tree.body:
        visit(stmt)
    return sorted(set(hits))


def _import_time_files() -> list[Path]:
    """Module nạp MỘT lần (thân module không chạy lại mỗi lượt) — script chính thì chạy lại nên miễn."""
    files = [ROOT / "vnstock_freshness.py", ROOT / "vnstock_health.py"]
    files += sorted((ROOT / "dashboard").glob("*.py"))
    return [f for f in files if f.name != "theme.py"]


def test_frozen_read_scanner_cases():
    """Tự kiểm ĐÚNG hàm mà lưới dùng — sửa hàm quét mà hở thì test này đỏ."""
    src = """\
from dashboard.theme import TOKENS as _T, series, SERIES
from .theme import pct_color as pc
from dashboard import theme, ui
import dashboard.theme
_A = _T["up"]                                   # 5  tra bảng
_B: dict = {"x": series()[0]}                   # 6  gọi hàm
try:
    _C = pc(1.0)                                # 8  trong try, import tương đối
except Exception:
    pass
class K:
    COLOR = ui._T["down"]                       # 12 thuộc tính class, bảng xuất lại
@deco(color=theme.TOKENS["up"])                 # 13 decorator
def f(c=_T.get("down"), t=_T):                  # 14 mặc định tham số (t=_T vô hại)
    return _T["up"], series()                   #    thân hàm — chạy lúc vẽ
_D = dashboard.theme.SERIES[0]                  # 16 hằng tối qua đường đầy đủ
_OK1 = lambda: _T["up"]
_OK2 = theme.THEME_SYNC_KEY
_OK3 = {"bull": "up"}
for _i in range(1):
    _E = SERIES                                 # 21 trong for
if __name__ == "__main__":
    print(_T["up"])
"""
    assert _frozen_reads(ast.parse(src)) == [5, 6, 8, 12, 13, 14, 16, 21]


@pytest.mark.parametrize("path", _import_time_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_mode_colors_frozen_at_import(path):
    """Hằng màu cấp module (vd `_SENTIMENT_BADGE`, `_C1 = SERIES[0]`) nạp lúc import = màu TỐI mãi
    mãi. Đọc lúc vẽ: hàm nhỏ trả màu, hoặc lưu TÊN token rồi tra `TOKENS[tên]` khi vẽ."""
    bad = _frozen_reads(ast.parse(path.read_text(encoding="utf-8")))
    assert not bad, f"{path.name}: đọc màu lúc import ở dòng {bad}"


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
