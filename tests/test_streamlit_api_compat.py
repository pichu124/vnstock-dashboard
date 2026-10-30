"""Mọi lời gọi Streamlit trong file UI chỉ dùng tham số CÓ THẬT ở bản đang cài (ghim 1.56).

Vết 31/10 (giao diện P5): `st.container(..., wrap=False)` — `wrap` chỉ có từ Streamlit 1.66.
Test render dùng Streamlit GIẢ (MagicMock nhận mọi thứ) nên xanh; app thật ném TypeError,
hai nút trên thanh trạng thái biến mất (lớp chặn lỗi giữ trang sống nên càng khó thấy).
Lưới này đọc AST, so tên keyword với `inspect.signature` của hàm Streamlit THẬT.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
import streamlit.components.v1 as stc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_UI_FILES = [ROOT / "vnstock_dashboard.py", ROOT / "vnstock_health.py",
             *sorted((ROOT / "dashboard").glob("*.py"))]
# Tên trùng hàm Streamlit nhưng là API khác (pandas, plotly, chuỗi…) — bỏ khi người nhận rõ ràng
# không phải Streamlit.
_NOT_ST = {"pd", "np", "json", "re", "os", "Path", "go", "px", "fig", "df", "datetime", "math"}
# Bí danh của `streamlit.components.v1` trong code (`components.html` ≠ `st.html`).
_COMPONENTS = {"_stc", "_comp", "components", "stc"}


def _signature(name: str, receiver: str | None = None):
    fn = getattr(stc if receiver in _COMPONENTS else st, name, None)
    if not callable(fn):
        return None
    try:
        return inspect.signature(fn)
    except (TypeError, ValueError):
        return None


def _receiver(node: ast.Attribute) -> str | None:
    base = node.value
    while isinstance(base, ast.Attribute):
        base = base.value
    if isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute):
        return _receiver(base.func)
    return base.id if isinstance(base, ast.Name) else None


def _calls(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        kws = [k.arg for k in node.keywords if k.arg]
        if not kws or _receiver(node.func) in _NOT_ST:
            continue
        sig = _signature(node.func.attr, _receiver(node.func))
        if sig is not None:
            yield node.lineno, node.func.attr, kws, sig


def test_scanner_catches_the_wrap_case():
    src = 'c.container(horizontal=True, wrap=False)\n'
    node = ast.parse(src).body[0].value
    sig = _signature("container")
    assert "horizontal" in sig.parameters
    if "wrap" not in sig.parameters:   # bản ghim 1.56: phải bắt được
        assert [k.arg for k in node.keywords if k.arg not in sig.parameters] == ["wrap"]


@pytest.mark.parametrize("path", _UI_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_streamlit_keywords_exist_in_installed_version(path):
    bad = []
    for line, name, kws, sig in _calls(path):
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue
        unknown = [k for k in kws if k not in sig.parameters]
        if unknown:
            bad.append(f"{path.name}:{line} st.{name}(…{', '.join(unknown)}=…)")
    assert not bad, (f"Tham số không có ở Streamlit {st.__version__}: " + "; ".join(bad))
