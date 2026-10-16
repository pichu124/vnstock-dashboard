"""Smoke tests for dashboard.screener_tab.

The UI and dashboard-level helpers (df_from_preset, render_table etc.)
are covered by their own tests in test_screener.py and test_dashboard.py.
This file only validates the tab module's import contract and signature.
"""

from __future__ import annotations

import inspect
import json


def test_module_imports_without_streamlit():
    """Module must be importable with just stdlib — Streamlit + dashboard
    helpers are lazy-imported inside render_screener_tab."""
    import importlib
    mod = importlib.import_module("dashboard.screener_tab")
    assert hasattr(mod, "render_screener_tab")
    assert callable(mod.render_screener_tab)


def test_render_signature_keyword_only():
    """All state parameters are keyword-only so callers can't pass
    positionally by accident — the dispatch block in vnstock_dashboard.py
    relies on this contract."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    for name, param in sig.parameters.items():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, \
            f"parameter {name!r} must be keyword-only"


def test_render_accepts_expected_params():
    """The wrapper in vnstock_dashboard.py passes exactly these names —
    this test locks the contract so a rename breaks loudly here."""
    from dashboard.screener_tab import render_screener_tab
    sig = inspect.signature(render_screener_tab)
    expected = {
        "presets_data", "industry_summary", "gen_time",
        "total_tickers", "classified", "total_hits", "top_preset",
    }
    assert set(sig.parameters.keys()) == expected


# ── Watchlist: file hỏng không bị ghi đè (state user, Dropbox đẩy sang máy kia) ──

def _watchlist_sidebar(path, click: str):
    from unittest.mock import MagicMock

    from dashboard.screener_tab import _render_watchlist_sidebar
    from dashboard.watchlist_io import load_watchlist, save_watchlist
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.text_input = lambda *a, **k: "VCB"
    st.button = lambda label, key=None, **k: key == click and not k.get("disabled")
    st.rerun = MagicMock()
    out = _render_watchlist_sidebar(
        st, lambda: load_watchlist(path), lambda t: save_watchlist(path, t), path)
    return st, out


def test_corrupt_watchlist_blocks_add_and_delete(tmp_path):
    path = tmp_path / "watchlist.json"
    truncated = b'{"tickers": ["FPT", "HPG", "SS'
    path.write_bytes(truncated)
    for click in ("wl_add_btn", "wl_del_btn"):
        st, (tickers, _) = _watchlist_sidebar(path, click)
        assert path.read_bytes() == truncated                 # không ghi đè bằng [] + VCB
        assert [p.name for p in tmp_path.iterdir()] == ["watchlist.json"]
        assert str(path) in st.error.call_args.args[0]
        assert tickers == [] and not st.rerun.called


def test_missing_watchlist_is_empty_and_add_writes(tmp_path):
    path = tmp_path / "watchlist.json"
    st, (tickers, _) = _watchlist_sidebar(path, "wl_add_btn")
    assert tickers == [] and not st.error.called
    assert json.loads(path.read_text(encoding="utf-8"))["tickers"] == ["VCB"]
    assert st.rerun.called


def test_watchlist_save_failure_is_reported(tmp_path, monkeypatch):
    import os

    import vnstock_parquet_io as pio
    path = tmp_path / "watchlist.json"
    path.write_text('{"tickers": ["FPT"]}', encoding="utf-8")

    def _fail(_a, _b):
        raise OSError("file đang bị khoá")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(os, "replace", _fail)
    st, _ = _watchlist_sidebar(path, "wl_add_btn")
    monkeypatch.undo()
    msg = st.error.call_args.args[0]
    assert str(path) in msg and "file đang bị khoá" in msg and not st.rerun.called
    assert json.loads(path.read_text(encoding="utf-8"))["tickers"] == ["FPT"]
