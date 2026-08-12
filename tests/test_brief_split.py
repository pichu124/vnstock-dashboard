"""Lưới giữ ranh giới sau khi tách `vnstock_brief.py` (mục ④ audit 06/08).

Tách file lớn chỉ có giá trị nếu ranh giới KHÔNG mờ lại. Ba kiểu mờ đã thấy
trong repo này:

1. **Vòng import lén** — module con import ngược module cha "cho tiện", rồi
   một hôm đổi thứ tự import là gãy.
2. **Định nghĩa trùng** — đúng bài học vừa rút ở mục ③: bản chép tay sống
   song song bản thật rồi TRÔI, mà test vẫn xanh vì nó soi bản chép.
3. **Guard viết ra rồi bỏ quên** — họ lỗi lặp lại nhiều lần nhất ở đây:
   "lưới chỉ soi thứ ĐƯỢC KHAI BÁO". Một `enforce_*` không được nối vào
   `apply_brief_guards` là code chết trông y như code sống.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_MODULES = {
    "brief": ROOT / "vnstock_brief.py",
    "guards": ROOT / "vnstock_brief_guards.py",
    "canon": ROOT / "vnstock_brief_canon.py",
    "common": ROOT / "vnstock_brief_guards_common.py",
    "sections": ROOT / "vnstock_brief_guards_sections.py",
    "numbers": ROOT / "vnstock_brief_guards_numbers.py",
    "text": ROOT / "vnstock_brief_guards_text.py",
}
# 3 module chủ đề — 44 guard chia theo "sai chuyện gì / sai số / lộ ruột"
_THEMES = ("sections", "numbers", "text")


def _tree(key: str) -> ast.Module:
    return ast.parse(_MODULES[key].read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set:
    """Mọi module được import, KỂ CẢ import lười nằm trong thân hàm."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def _bindings(tree: ast.Module) -> set:
    """Tên do CHÍNH module định nghĩa (bỏ qua tên chỉ import về)."""
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


# ── 1. Phụ thuộc một chiều ──────────────────────────────────────────────────

@pytest.mark.parametrize("mod", ["guards", *_THEMES, "common"])
def test_guards_never_import_brief(mod):
    """`vnstock_brief` import guards, nên guards import ngược = vòng.
    Soi cả import LƯỜI trong thân hàm — kiểu lách hay gặp nhất."""
    assert "vnstock_brief" not in _imported_modules(_tree(mod))


@pytest.mark.parametrize("mod", _THEMES)
def test_theme_modules_never_import_the_chain(mod):
    """Chuỗi import 3 nhóm; nhóm import ngược chuỗi = vòng."""
    assert "vnstock_brief_guards" not in _imported_modules(_tree(mod))


@pytest.mark.parametrize("mod", _THEMES)
def test_theme_modules_never_import_each_other(mod):
    """Ba nhóm phải ĐỘC LẬP. Cần dùng chung thì đưa xuống
    `vnstock_brief_guards_common` — import chéo là vòng chờ sẵn."""
    others = {f"vnstock_brief_guards_{m}" for m in _THEMES if m != mod}
    assert not (_imported_modules(_tree(mod)) & others)


def test_common_stays_a_leaf():
    imported = _imported_modules(_tree("common"))
    assert not any(str(m).startswith("vnstock_brief") for m in imported)


def test_canon_is_a_leaf_module():
    """Canon là nguồn sự thật cho CẢ HAI bên nên không được phụ thuộc bên nào."""
    imported = _imported_modules(_tree("canon"))
    assert not (imported & {"vnstock_brief", "vnstock_brief_guards"})


def test_brief_imports_guards_not_the_other_way():
    assert "vnstock_brief_guards" in _imported_modules(_tree("brief"))


# ── 2. Không định nghĩa trùng ───────────────────────────────────────────────

@pytest.mark.parametrize("other", ["guards", "canon", "common", *_THEMES])
def test_no_duplicate_definition_left_in_brief(other):
    """Tên đã chuyển đi mà `vnstock_brief` vẫn còn định nghĩa riêng = hai bản
    sống song song. Re-export thì KHÔNG tính (chỉ là import lại)."""
    dupes = sorted(_bindings(_tree("brief")) & _bindings(_tree(other)))
    assert not dupes, f"Định nghĩa trùng giữa vnstock_brief và {other}: {dupes}"


def test_no_name_is_defined_twice_across_the_split():
    """Quét chéo TẤT CẢ các file của hệ brief: một tên chỉ được định nghĩa ở
    ĐÚNG MỘT nơi. Đây là lưới chống đúng thứ vừa dọn ở mục ③."""
    seen, dupes = {}, []
    for mod in ("brief", "guards", "canon", "common", *_THEMES):
        for name in _bindings(_tree(mod)):
            if name in seen:
                dupes.append(f"{name}: {seen[name]} + {mod}")
            else:
                seen[name] = mod
    assert not dupes, "Định nghĩa trùng: " + "; ".join(sorted(dupes))


# ── 3. Guard nào cũng phải được NỐI VÀO CHUỖI ───────────────────────────────

def _all_guards() -> set:
    """Mọi `enforce_*` định nghĩa ở BA module chủ đề. Thêm module chủ đề mới
    → thêm vào `_THEMES`; lưới chỉ soi thứ ĐƯỢC KHAI BÁO."""
    return {n.name for mod in _THEMES for n in _tree(mod).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("enforce_")}


def test_every_guard_is_wired_into_the_chain():
    """Họ lỗi lặp lại nhiều nhất repo này: lưới chỉ soi thứ ĐƯỢC KHAI BÁO.
    Viết `enforce_x` mà quên nối vào `apply_brief_guards` = guard chết, nhưng
    nhìn code thì y hệt guard sống — và test riêng của nó vẫn xanh."""
    import inspect

    import vnstock_brief_guards as g

    chain = inspect.getsource(g.apply_brief_guards)
    orphan = sorted(d for d in _all_guards() if f"{d}(" not in chain)
    assert not orphan, f"Guard không nằm trong apply_brief_guards: {orphan}"


def test_no_guard_hides_outside_the_theme_modules():
    """Guard viết thẳng vào file chuỗi (hoặc common) sẽ lọt khỏi lưới bên trên
    — nên chặn luôn: `enforce_*` chỉ được ở module chủ đề."""
    stray = sorted(n for mod in ("guards", "common", "canon", "brief")
                   for n in _bindings(_tree(mod)) if n.startswith("enforce_"))
    assert not stray, f"Guard nằm ngoài 3 module chủ đề: {stray}"


def test_the_44_guards_are_all_accounted_for():
    """Con số chốt: chuỗi gọi đúng bằng số guard được định nghĩa, không dư
    không thiếu."""
    import inspect
    import re

    import vnstock_brief_guards as g
    called = re.findall(r"fixed = (enforce_\w+)\(",
                        inspect.getsource(g.apply_brief_guards))
    assert len(called) == len(set(called)), "Có guard bị gọi hai lần trong chuỗi"
    assert set(called) == _all_guards()


def test_chain_calls_only_real_guards():
    """Chiều ngược lại: chuỗi gọi tên không tồn tại = AttributeError lúc chạy
    brief thật (18:00, không ai ngồi nhìn)."""
    import inspect
    import re

    import vnstock_brief_guards as g

    called = set(re.findall(r"fixed = (enforce_\w+)\(", inspect.getsource(g.apply_brief_guards)))
    missing = sorted(c for c in called if not callable(getattr(g, c, None)))
    assert not missing, f"Chuỗi gọi guard không tồn tại: {missing}"


def test_chain_lives_in_the_guards_module():
    """Điểm parity phải nằm CÙNG CHỖ với các guard nó gọi — CLAUDE.md cấm
    inline chuỗi vào `generate_brief`, và cấm luôn nuôi bản thứ hai."""
    import vnstock_brief
    import vnstock_brief_guards

    assert vnstock_brief.apply_brief_guards is vnstock_brief_guards.apply_brief_guards
    assert "apply_brief_guards" not in _bindings(_tree("brief"))


# ── 4. Hợp đồng re-export — đường import cũ không được gãy ──────────────────

@pytest.mark.parametrize("name", [
    # các tên module/test ngoài đang import qua `vnstock_brief`
    "VN30_TICKERS",            # vnstock_events, vnstock_train
    "_BUY_BIAS_CAVEAT",        # vnstock_telegram
    "_FINANCIAL_TICKERS", "_SR_MAX_MOVE_PCT", "_WATCHLIST_GTGD_MIN_TY",
    "_ALLOC_HORIZON_CAVEAT", "_MORNING_CMP_RE",
    "_macro_body_lines", "_macro_reports_body_lines", "_allocation_table_lines",
    "_gtgd_close_frame", "_round_tick",
    "apply_brief_guards", "validate_brief_factuality",
    "enforce_macro", "enforce_gtgd_total", "enforce_sr_direction",
])
def test_old_import_paths_still_work(name):
    import vnstock_brief
    assert hasattr(vnstock_brief, name), (
        f"`from vnstock_brief import {name}` đã gãy — thiếu re-export")


def test_all_moved_names_are_reexported():
    """Quét TOÀN BỘ chứ không chỉ danh sách trên: mọi tên định nghĩa ở các
    module đã tách phải với tới được qua `vnstock_brief`."""
    import vnstock_brief

    moved = set()
    for mod in ("guards", "canon", "common", *_THEMES):
        moved |= _bindings(_tree(mod))
    gone = sorted(n for n in moved if not hasattr(vnstock_brief, n))
    assert not gone, f"Tên đã chuyển nhưng KHÔNG re-export: {gone}"
