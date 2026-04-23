# Dashboard Refactor Plan

**Goal**: Break the 287 KB monolithic `vnstock_dashboard.py` into focused modules, one per tab, each ~200-800 lines. Keep the top-level file as a thin router that imports and dispatches to each tab's `render_*()` function.

**Status**: 1 of 6 tabs extracted (⚕️ Sức khỏe → `vnstock_health.py::render_health_tab`). That one served as proof of concept for the pattern.

## Proven pattern (from Sức khỏe tab)

```python
# vnstock_dashboard.py (top-level router)
if _active_tab == "⚕️ Sức khỏe":
    try:
        from vnstock_health import render_health_tab
        render_health_tab()
    except Exception as _e:
        st.error(f"Không render được Health tab: {_e}")
```

```python
# vnstock_health.py (tab module)
def render_health_tab(warehouse: Path = DEFAULT_WAREHOUSE) -> None:
    """All Streamlit rendering for the Sức khỏe tab."""
    import streamlit as st
    # ... full tab UI ...
```

Benefits proven:
* Dashboard only needs `render_health_tab()` — full UI lives in its own module with its own tests.
* Lazy `import streamlit as st` inside the function so the module stays importable by unit tests without needing the Streamlit runtime.
* The `try/except` wrapper keeps other tabs alive if this one throws.

## Per-tab scope (remaining 5)

| # | Tab | Lines | Proposed module | Risk | Priority |
|---|---|---|---|---|---|
| 1 | 💼 **Portfolio** | 190 | `dashboard/portfolio_tab.py` | **Low** — small, self-contained, uses positions JSON | **First (easiest)** |
| 2 | 📊 **Screener** | 389 | `dashboard/screener_tab.py` | Low — feeds from presets JSON, no heavy deps | Second |
| 3 | 💰 **Dòng Tiền** | 520 | `dashboard/money_flow_tab.py` | Medium — 3-tier caching + sector aggregation logic | Third |
| 4 | 🌏 **Thị trường** | 762 | `dashboard/market_tab.py` | Medium — many sub-sections (indices, breadth, flows) | Fourth |
| 5 | 🔬 **Phân tích** | 803 | `dashboard/analysis_tab.py` | **High** — biggest + most state (ticker selector, chart options) | **Last** |

## Package structure (proposed)

```
dashboard/
├── __init__.py
├── _shared.py           # theme, utility helpers shared across tabs
├── portfolio_tab.py     # def render_portfolio_tab(warehouse, positions)
├── screener_tab.py      # def render_screener_tab(warehouse, presets_data, ...)
├── money_flow_tab.py    # def render_money_flow_tab(warehouse, ...)
├── market_tab.py        # def render_market_tab(warehouse, ...)
└── analysis_tab.py      # def render_analysis_tab(warehouse, ...)
```

Top-level `vnstock_dashboard.py` shrinks to ~3,500 lines (header + data loaders + tab dispatch). Long-term we can move loaders into `dashboard/_data.py` too.

## Per-tab refactor checklist

For each tab:

1. **Identify boundaries** — start line = `if _active_tab == ...`, end line = the next `if _active_tab ==` or EOF.
2. **Extract function signature** — `render_<tab>_tab(*args, **kwargs)`. Arguments are whatever state the tab reads: `warehouse`, `presets_data`, `positions`, `industry_summary`, etc.
3. **Hoist imports** — any `from x import y` currently inside the tab block lifts to the module top; `streamlit` imported lazily inside the function.
4. **Rewire shared state** — variables set BEFORE the tab block (e.g. `_t` theme dict) become function arguments.
5. **Smoke-test** — run `streamlit run vnstock_dashboard.py`, click through the tab, verify no regression.
6. **Delete the old block** from `vnstock_dashboard.py`, replace with the 6-line wrapper.
7. **Add a minimal import test** — verify the module imports cleanly without Streamlit runtime.
8. **Commit each tab separately** — atomic, revertable if a regression is found.

## Shared-state inventory (to guide extraction)

Audit these to see which tabs depend on which:

* `_t` — theme colours (dark/light). Used by every tab. Goes into `dashboard/_shared.py`.
* `presets_data`, `industry_summary` — loaded once at top. Pass as args.
* `positions` — portfolio state. Pass as arg or re-load in portfolio_tab.
* `market_overview`, `money_flow_snapshot`, etc. — loaded lazily by specific tabs.

## Test strategy

The existing `tests/test_dashboard.py` (48 tests, mostly unit tests on pure functions) stays as-is. Each new tab module MAY have its own `tests/test_<tab>_tab.py` with:

* Import test — `from dashboard.X_tab import render_X_tab` must not raise.
* Pure-logic tests — if the tab has non-UI helper functions, test those directly.
* UI rendering — not unit-tested; manual QA per `docs/PHASE_5C_TEST_CHECKLIST.md`-style checklists.

## Timeline estimate

| Tab | Effort | Includes |
|---|---|---|
| Portfolio | 1 hour | Extract, test, commit |
| Screener | 1 hour | Extract + run screener preset smoke test |
| Money Flow | 2 hours | Carefully preserve 3-tier cache semantics |
| Thị trường | 2-3 hours | Multiple sub-sections, each needs a quick eyeball |
| Phân tích | 3-4 hours | Chart options, ticker selector state, candle rendering |

**Total: 9-11 hours** spread across 5 commits. Safe to parallel-batch or spread across sessions.

## When to do this

* **Do NOT mass-refactor during live trading hours** — Streamlit reruns on file save; a broken module takes the dashboard down.
* **Run on a weekend or after-hours** — gives room to smoke-test each tab without pressure.
* **Do one tab per session** — each is its own atomic commit; PR review friendly.

## Success criteria

After all 5 tabs extracted:

* `vnstock_dashboard.py` is ≤ 4,000 lines (from 6,341).
* Each tab module is ≤ 1,000 lines.
* 344 existing tests still pass.
* No visible UI regression when clicking through all 6 tabs.
* PR description lists the 5 commits + manual smoke-test log.

## Out of scope

* Rewriting the screener presets logic itself (that's in `vnstock_screener.py` / `vnstock_runner.py`, which are already separate modules).
* Adding a routing framework like `streamlit-pages` — overkill for 6 tabs.
* CSS / theming changes — the `_t` dict stays exactly as-is, just moves location.
