"""Smoke tests for dashboard.screener_tab.

The UI and dashboard-level helpers (df_from_preset, render_table etc.)
are covered by their own tests in test_screener.py and test_dashboard.py.
This file only validates the tab module's import contract and signature.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import date

import pytest


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

def _watchlist_sidebar(path, click: str, typed: str = "VCB", snapshot=None):
    """`snapshot` = thứ `load_watchlist()` (cache 10 phút của dashboard) trả về; None ⇒
    đọc thẳng file như khi cache vừa hết hạn."""
    from unittest.mock import MagicMock

    from dashboard.screener_tab import _render_watchlist_sidebar
    from dashboard.watchlist_io import load_watchlist, save_watchlist
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.text_input = lambda *a, **k: typed
    st.button = lambda label, key=None, **k: key == click and not k.get("disabled")
    st.rerun = MagicMock()
    load = (lambda: list(snapshot)) if snapshot is not None else (lambda: load_watchlist(path))
    out = _render_watchlist_sidebar(st, load, lambda t: save_watchlist(path, t), path)
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



@pytest.mark.parametrize("payload", [b"null", b'["FPT", "HPG"]', b'{"tickers": "FPT"}'])
def test_wrong_shape_watchlist_blocks_add_and_delete(tmp_path, payload):
    """JSON hợp lệ nhưng sai dạng: từng sập tab (AttributeError lọt qua
    `except (OSError, ValueError)`) hoặc ghép chuỗi "FPT" với mã mới."""
    path = tmp_path / "watchlist.json"
    path.write_bytes(payload)
    for click in ("wl_add_btn", "wl_del_btn"):
        st, (tickers, _) = _watchlist_sidebar(path, click)
        assert path.read_bytes() == payload
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


@pytest.mark.parametrize("click, typed, expected", [("wl_add_btn", "CCC", ["AAA", "BBB", "CCC"]),
                                                    ("wl_del_btn", "AAA", ["BBB"])])
def test_watchlist_buttons_reread_file_not_cached_snapshot(tmp_path, click, typed, expected):
    """Cache 10 phút còn [AAA] trong khi máy kia (Dropbox) đã ghi [AAA, BBB]: Thêm/Xoá
    phải đọc LẠI file, không ghi từ bản chụp rồi đè mất BBB."""
    from dashboard.watchlist_io import load_watchlist, save_watchlist
    path = tmp_path / "watchlist.json"
    save_watchlist(path, ["AAA", "BBB"])

    st, _ = _watchlist_sidebar(path, click, typed=typed, snapshot=["AAA"])

    assert load_watchlist(path) == expected
    assert st.rerun.called and not st.error.called


@pytest.mark.parametrize("click", ["wl_add_btn", "wl_del_btn"])
def test_watchlist_reread_failure_writes_nothing(tmp_path, click):
    """Bản chụp còn tốt nhưng lúc bấm file trên đĩa đã hỏng (Dropbox đang ghi dở) ⇒ báo lỗi
    kèm đường dẫn, không ghi đè file."""
    path = tmp_path / "watchlist.json"
    truncated = b'{"tickers": ["AAA", "BB'
    path.write_bytes(truncated)

    st, _ = _watchlist_sidebar(path, click, typed="AAA", snapshot=["AAA"])

    assert path.read_bytes() == truncated
    assert str(path) in st.error.call_args.args[0] and not st.rerun.called


# ── Thống kê phiên: fragment chạy mỗi 30s ở tab mặc định ⇒ không tải lại EOD / ghi lại file ──

def _count_eod_fetches(monkeypatch, frames):
    """Thay vnstock Trading bằng bản giả đếm lượt gọi price_history (lượt mạng thật)."""
    import types

    import pandas as pd

    import vnstock_session_stats as ss
    calls = []

    class _Trading:
        def __init__(self, symbol, source):
            self.symbol = symbol

        def price_history(self, **kw):
            calls.append(self.symbol)
            return frames(self.symbol)

    monkeypatch.setitem(sys.modules, "vnstock.api.trading", types.SimpleNamespace(Trading=_Trading))
    for sponsor in ("vnstock_data", "vnii"):                 # nhánh dự phòng cũng không ra mạng
        monkeypatch.setitem(sys.modules, sponsor, None)
    bars = pd.DataFrame({"time": pd.to_datetime([f"{date.today()} 09:15"]), "volume": [1_000_000]})
    monkeypatch.setattr(ss, "_fetch_intraday_volume", lambda *a, **k: bars)
    monkeypatch.setattr(ss, "_PRICE_HISTORY_CACHE", {}, raising=False)
    return ss, calls


def _eod_frame(_symbol):
    import pandas as pd
    return pd.DataFrame({"trading_date": [date.today().isoformat()],
                         "total_value": [2.0e13], "total_volume": [8.0e8]})


def test_compute_session_stats_fetches_eod_history_once_per_day(monkeypatch):
    ss, calls = _count_eod_fetches(monkeypatch, _eod_frame)
    first = ss.compute_session_stats()
    second = ss.compute_session_stats()
    assert second == first                                    # kết quả số không đổi
    assert first["9h-10h"]["VNINDEX"] == {"vol": 1_000_000, "gtgd": 25.0, "gtgd_per_vol": 25_000,
                                          "status": "estimate"}   # calibration từ EOD giả
    assert sorted(calls) == sorted(ss._PRICE_HISTORY_SYMBOL.values())   # 4 lượt, không phải 8

    class _Tomorrow(date):
        @classmethod
        def today(cls):
            return cls.fromordinal(date.today().toordinal() + 1)

    monkeypatch.setattr(ss, "date", _Tomorrow)
    ss.compute_session_stats()
    assert len(calls) == 8                                    # sang ngày mới thì tải lại
    monkeypatch.setattr(ss, "_PRICE_HISTORY_TTL_S", 0)
    ss.compute_session_stats()
    assert len(calls) == 12                                   # hết TTL (EOD đăng giữa ngày) ⇒ tải lại


def test_eod_history_failure_is_not_cached(monkeypatch):
    import pandas as pd
    ss, calls = _count_eod_fetches(monkeypatch, lambda s: pd.DataFrame())
    ss.compute_session_stats()
    n = len(calls)
    ss.compute_session_stats()
    assert n > 0 and len(calls) == 2 * n                      # lỗi mạng ⇒ lượt sau thử lại


def test_save_session_stats_skips_identical_content(tmp_path, monkeypatch):
    import vnstock_parquet_io as pio
    import vnstock_session_stats as ss
    monkeypatch.setattr(ss, "SESSION_STATS_PATH", tmp_path / "market_session_stats.json")
    writes = []
    real = pio.write_json_atomic
    monkeypatch.setattr(pio, "write_json_atomic",
                        lambda payload, path, **k: writes.append(path) or real(payload, path, **k))
    stats = {"9h-10h": {"VNINDEX": {"vol": 123, "gtgd": 3.7, "gtgd_per_vol": 30000.0,
                                    "status": "estimate"}}}
    ss.save_session_stats(stats)
    ss.save_session_stats(json.loads(json.dumps(stats)))      # cùng nội dung ⇒ không ghi lại
    assert len(writes) == 1
    changed = {"9h-10h": {"VNINDEX": {**stats["9h-10h"]["VNINDEX"], "vol": 456}}}
    ss.save_session_stats(changed)
    assert len(writes) == 2
    assert ss.load_session_stats_history()[date.today().isoformat()] == changed
