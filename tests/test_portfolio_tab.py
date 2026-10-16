"""Smoke tests for dashboard.portfolio_tab — the Streamlit UI is tested
manually; this file covers the non-UI helpers, the import path, and the write
guard when portfolio.json is corrupt or cannot be written (fake Streamlit)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_module_imports_without_streamlit():
    """The tab module must be importable even when Streamlit is not
    available — Streamlit is only imported inside render_portfolio_tab."""
    import importlib
    mod = importlib.import_module("dashboard.portfolio_tab")
    assert hasattr(mod, "render_portfolio_tab")
    assert callable(mod.render_portfolio_tab)


def test_load_portfolio_returns_empty_when_file_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio
    assert _load_portfolio(tmp_path) == []


def test_load_portfolio_raises_on_corrupt_file(tmp_path: Path):
    """File hỏng KHÔNG được đọc thành [] — nút Thêm/Xoá sẽ ghi đè cả danh mục."""
    from dashboard.portfolio_tab import _load_portfolio
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "portfolio.json").write_text("{not valid json")
    with pytest.raises(ValueError):
        _load_portfolio(tmp_path)


def test_save_load_round_trip(tmp_path: Path):
    from dashboard.portfolio_tab import _load_portfolio, _save_portfolio
    positions = [
        {"ticker": "VCB", "quantity": 100, "buy_price": 90000,
         "buy_date": "2026-01-15"},
        {"ticker": "FPT", "quantity": 50, "buy_price": 120000,
         "buy_date": "2026-02-01"},
    ]
    _save_portfolio(tmp_path, positions)
    assert _load_portfolio(tmp_path) == positions


def test_save_is_atomic_and_raises_on_failure(tmp_path: Path, monkeypatch):
    """Ghi lỗi phải RAISE (tab báo st.error) — không nuốt im lặng; file cũ giữ nguyên."""
    from dashboard.portfolio_tab import _save_portfolio, _portfolio_path
    import os as _os
    import vnstock_parquet_io as pio

    _save_portfolio(tmp_path, [{"ticker": "FPT"}])
    before = _portfolio_path(tmp_path).read_bytes()

    def _fail(_a, _b):
        raise OSError("disk full")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(_os, "replace", _fail)
    with pytest.raises(OSError):
        _save_portfolio(tmp_path, [{"ticker": "VCB"}])
    monkeypatch.undo()

    assert _portfolio_path(tmp_path).read_bytes() == before
    assert not any(p.name.startswith("portfolio") and p.suffix.endswith(".tmp")
                   for p in (tmp_path / "_meta").glob("*"))


def test_live_quote_returns_none_when_missing(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    assert _live_quote("XYZ", tmp_path) is None


def test_live_quote_parses_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text(json.dumps({
        "ticker": "VCB", "price": 91000, "ts": "2026-04-22T10:00:00",
    }))
    q = _live_quote("VCB", tmp_path)
    assert q is not None
    assert q["price"] == 91000


def test_live_quote_handles_corrupt_json(tmp_path: Path):
    from dashboard.portfolio_tab import _live_quote
    live = tmp_path / "_live"
    live.mkdir(parents=True)
    (live / "quote_VCB.json").write_text("not-json")
    assert _live_quote("VCB", tmp_path) is None


# ── tripwire ⚠ sai đơn vị giá (review 21/07: tách hàm thuần + nới ngưỡng) ──

def test_unit_suspect_same_day_thousandfold_loss():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", -99.7) is True


def test_unit_suspect_same_day_thousandfold_gain():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-21", "2026-07-21", 99_900.0) is True


def test_unit_suspect_legit_bands_not_flagged():
    """HOSE ±7% · HNX ±10% · UPCoM ±15% · chào sàn ±40% · mua đáy −N% đóng
    trần +N% — tất cả là %L/L cùng-ngày HỢP LỆ, không được dán nhãn 'gần như
    chắc chắn sai' như ngưỡng ±7.5% cũ."""
    from dashboard.portfolio_tab import _unit_suspect
    for pct in (6.9, -9.8, 14.9, -15.0, 39.9, -40.0, 42.0, 133.0):
        assert _unit_suspect("2026-07-21", "2026-07-21", pct) is False, pct


def test_unit_suspect_only_fires_on_buy_day():
    from dashboard.portfolio_tab import _unit_suspect
    assert _unit_suspect("2026-07-18", "2026-07-21", -99.7) is False
    assert _unit_suspect("", "2026-07-21", -99.7) is False
    assert _unit_suspect("2026-07-21", "", -99.7) is False


# ── trục X chart NAV (review 21/07: tách hàm thuần cho nhánh dtick) ────────

def test_nav_xaxis_short_series_forces_daily_dtick():
    from dashboard.portfolio_tab import _nav_xaxis
    x = _nav_xaxis(5)
    assert x["dtick"] == 86_400_000
    assert x["tickformat"] == "%d/%m"
    assert x["rangebreaks"] == [{"bounds": ["sat", "mon"]}]


def test_nav_xaxis_long_series_keeps_auto_ticks():
    from dashboard.portfolio_tab import _nav_xaxis
    assert "dtick" not in _nav_xaxis(11)
    assert _nav_xaxis(11)["tickformat"] == "%d/%m"


# ── File hỏng / ghi lỗi không được làm mất danh mục (Dropbox đẩy sang máy kia) ──

class _Rerun(Exception):
    """st.rerun thật dừng script bằng exception — giả lập đúng như vậy."""


def _render_clicking_add(monkeypatch, warehouse: Path):
    from tests.test_tab_render_smoke import _fake_streamlit
    st = _fake_streamlit()
    st.button = lambda label, key=None, **k: key == "pf_add" and not k.get("disabled")
    st.text_input = lambda label, **k: "VCB" if k.get("key") == "pf_ticker" else ""
    st.number_input = lambda label, min_value=0, max_value=None, value=0, **k: (
        25_000.0 if k.get("key") == "pf_price" else value)

    def _rerun():
        raise _Rerun

    st.rerun = _rerun
    monkeypatch.setitem(sys.modules, "streamlit", st)
    from dashboard.portfolio_tab import render_portfolio_tab
    try:
        render_portfolio_tab(warehouse)
    except _Rerun:
        pass
    return st


def test_corrupt_portfolio_blocks_writes_and_keeps_bytes(tmp_path: Path, monkeypatch):
    from dashboard.portfolio_tab import _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    truncated = b'[\n  {\n    "ticker": "HPG",\n    "quantity": 1000,\n    "buy_pr'
    path.write_bytes(truncated)

    st = _render_clicking_add(monkeypatch, tmp_path)

    assert path.read_bytes() == truncated                    # không ghi đè bằng [] + 1 vị thế
    assert sorted(p.name for p in path.parent.iterdir()) == ["portfolio.json"]   # không đổi tên/xoá
    assert str(path) in st.error.call_args.args[0]


def test_portfolio_save_failure_is_reported(tmp_path: Path, monkeypatch):
    from dashboard.portfolio_tab import _portfolio_path
    import os as _os
    import vnstock_parquet_io as pio

    def _fail(_a, _b):
        raise OSError("file đang bị khoá")

    monkeypatch.setattr(pio, "_REPLACE_BACKOFF", 0)
    monkeypatch.setattr(_os, "replace", _fail)
    st = _render_clicking_add(monkeypatch, tmp_path)

    assert not _portfolio_path(tmp_path).exists()
    msg = st.error.call_args.args[0]
    assert str(_portfolio_path(tmp_path)) in msg and "file đang bị khoá" in msg


# ── Xoá vị thế: theo VỊ TRÍ dòng, không theo nhãn ───────────────────────────

def test_delete_second_of_two_identical_labels_keeps_first(tmp_path: Path, monkeypatch):
    """Hai lô cùng mã/số lượng/giá (khác ngày mua) có CÙNG nhãn trong selectbox;
    `_options.index(nhãn)` trả lô ĐẦU ⇒ chọn xoá lô thứ hai lại xoá lô đầu."""
    from tests.test_tab_render_smoke import _fake_streamlit
    from dashboard.portfolio_tab import _portfolio_path, _save_portfolio, _load_portfolio
    lot1 = {"ticker": "VCB", "quantity": 100, "buy_price": 90000, "buy_date": "2026-01-15"}
    lot2 = {"ticker": "VCB", "quantity": 100, "buy_price": 90000, "buy_date": "2026-03-02"}
    lot3 = {"ticker": "FPT", "quantity": 50, "buy_price": 120000, "buy_date": "2026-02-01"}
    _save_portfolio(tmp_path, [lot1, lot2, lot3])

    st = _fake_streamlit()
    shown: list = []

    def _selectbox(label, options=(), format_func=str, **k):
        options = list(options)
        if k.get("key") != "pf_del_select":
            return options[0] if options else None
        shown.extend(format_func(o) for o in options)
        return options[2]                                       # [—, lô 1, LÔ 2, lô 3]

    st.selectbox = _selectbox
    st.button = lambda label, key=None, **k: key == "pf_del_btn"

    def _rerun():
        raise _Rerun

    st.rerun = _rerun
    monkeypatch.setitem(sys.modules, "streamlit", st)
    from dashboard.portfolio_tab import render_portfolio_tab
    with pytest.raises(_Rerun):
        render_portfolio_tab(tmp_path)

    assert _portfolio_path(tmp_path).exists()
    assert _load_portfolio(tmp_path) == [lot1, lot3]
    assert shown == ["—", "VCB (100 cp @ 90,000)", "VCB (100 cp @ 90,000)",
                     "FPT (50 cp @ 120,000)"]


# ── JSON hợp lệ nhưng SAI DẠNG: cũng là file hỏng, không phải danh mục ──────

_WRONG_SHAPE = ["null",                                          # gốc không phải list
                '[{"ticker": "VCB", "quantity": 100}, 1]',       # phần tử không phải dict
                '{"ticker": "VCB", "quantity": 100}']            # dict thay vì list


@pytest.mark.parametrize("payload", _WRONG_SHAPE)
def test_load_portfolio_rejects_wrong_shape(tmp_path: Path, payload: str):
    from dashboard.portfolio_tab import _load_portfolio, _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="sai định dạng"):
        _load_portfolio(tmp_path)


@pytest.mark.parametrize("payload", _WRONG_SHAPE)
def test_wrong_shape_portfolio_blocks_writes(tmp_path: Path, monkeypatch, payload: str):
    """Trước đây lọt qua `_load_portfolio` rồi chết TypeError giữa render
    (`None + [...]`, `1["ticker"]`) thay vì báo file hỏng."""
    from dashboard.portfolio_tab import _portfolio_path
    path = _portfolio_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()

    st = _render_clicking_add(monkeypatch, tmp_path)

    assert path.read_bytes() == before
    assert str(path) in st.error.call_args.args[0]
