"""Contract test: every attribute the dashboard tabs pull off the main module
(`_vnd.X` / `_vd.X` lazy attribute access) must exist in vnstock_dashboard.

Attribute access is invisible to import-based dead-code checks — deleting a
"seemingly unused" dashboard helper broke the Screener tab at runtime
("module 'main' has no attribute 'compute_session_stats'", 2026-07-06).
This static check catches that class of regression without needing Streamlit.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dashboard_defined_names() -> set[str]:
    tree = ast.parse((ROOT / "vnstock_dashboard.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                names.add(al.asname or al.name.split(".")[0])
    return names


def test_tab_attribute_pulls_exist_in_dashboard():
    defined = _dashboard_defined_names()
    pat = re.compile(r"\b_vn?d\.(\w+)")
    missing: list[str] = []
    for tab in sorted((ROOT / "dashboard").glob("*.py")):
        for attr in set(pat.findall(tab.read_text(encoding="utf-8"))):
            if attr not in defined:
                missing.append(f"{tab.name}: _vnd.{attr}")
    assert not missing, f"Tabs pull attributes vnstock_dashboard no longer defines: {missing}"
