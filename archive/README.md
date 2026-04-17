# Archive

Legacy / disposable files kept for reference. Not imported by the active
codebase.

| File | Status | Replacement |
|------|--------|-------------|
| `vnstock_platform.py` | Legacy v1 | `vnstock_platform_v2.py` (root) |
| `debug_screener.py` | Ad-hoc debug | `tests/test_screener.py` |
| `debug_value_preset.py` | Ad-hoc debug | `tests/test_screener.py` |
| `check_units.py` | One-off unit check | `tests/test_dashboard.py::price normalization` |

Safe to delete permanently after one release cycle of stability on the new
pipeline (contracts + reconciler).
