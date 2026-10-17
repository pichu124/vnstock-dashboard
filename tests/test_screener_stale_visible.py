"""Mã screener EOD bỏ vì kho đứng im (`stale_excluded` trong screener_results.json) phải
NHÌN THẤY được: tab Screener liệt kê mã + độ trễ, doctor có badge đếm tỉ lệ.

Đo 17/10 trên kho thật: ~390/1.724 mã trễ > 5 phiên — con số lớn mà trước đó chỉ nằm
trong JSON, không nơi nào hiện.
"""
import ast
import inspect
import json
from pathlib import Path

import pytest

import dashboard.screener_tab as tab


def _stale(tickers: dict, limit: int = 5) -> dict:
    return {"limit": limit, "count": len(tickers), "tickers": tickers}


# ── tab Screener ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", [None, {}, {"limit": 5, "count": 0, "tickers": {}}])
def test_stale_table_none_when_nothing_excluded(data):
    assert tab._stale_table(data) is None


def test_stale_table_lists_tickers_with_lag_newest_stale_first():
    label, df = tab._stale_table(_stale({"BEL": 23, "ABC": 7, "XYZ": 7, "OLD": 120}))
    assert label == "⏸ 4 mã bị loại khỏi mọi preset vì kho đứng im > 5 phiên"
    assert list(df.columns) == ["Mã", "Trễ (phiên)"]
    # Mới đứng im (trễ ít) lên đầu — nhóm đáng soi nhất; trễ bằng nhau thì theo mã.
    assert df["Mã"].tolist() == ["ABC", "XYZ", "BEL", "OLD"]
    assert df["Trễ (phiên)"].tolist() == [7, 7, 23, 120]


def test_stale_table_label_uses_thousands_separator():
    label, df = tab._stale_table(_stale({f"T{i:04d}": 6 for i in range(1234)}, limit=8))
    assert label.startswith("⏸ 1,234 mã") and label.endswith("> 8 phiên")
    assert len(df) == 1234


def test_dashboard_passes_every_render_param():
    """Wrapper ở vnstock_dashboard.py phải truyền ĐÚNG các tham số của render_screener_tab
    (kể cả `stale_excluded`) — thiếu một cái là tab nổ TypeError lúc chạy thật."""
    src = Path(__file__).resolve().parents[1] / "vnstock_dashboard.py"
    calls = [n for n in ast.walk(ast.parse(src.read_text(encoding="utf-8")))
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "render_screener_tab"]
    assert len(calls) == 1
    passed = {kw.arg for kw in calls[0].keywords}
    assert passed == set(inspect.signature(tab.render_screener_tab).parameters)
    assert "stale_excluded" in passed


# ── doctor badge ─────────────────────────────────────────────────────────────

@pytest.fixture
def doc(tmp_path, monkeypatch):
    import vnstock_doctor as doc
    monkeypatch.setattr(doc, "_META", tmp_path)
    return doc


def _write(tmp_path, **data):
    (tmp_path / "screener_results.json").write_text(
        json.dumps({"generated_at": "2026-10-16 18:07:47", "total_tickers": 1724, **data}),
        encoding="utf-8")


def test_doctor_stale_off_without_file_or_key_or_when_filter_disabled(doc, tmp_path):
    assert doc.check_screener_stale()["status"] == "off"                 # chưa có file
    _write(tmp_path)
    r = doc.check_screener_stale()
    assert r["status"] == "off" and "stale_excluded" in r["message"]     # runner bản cũ
    _write(tmp_path, stale_excluded=_stale({}, limit=0))
    r = doc.check_screener_stale()
    assert r["status"] == "off" and "VNSTOCK_SCREENER_STALE_SESSIONS" in r["message"]


def test_doctor_stale_error_on_corrupt_file(doc, tmp_path):
    (tmp_path / "screener_results.json").write_text("{hỏng", encoding="utf-8")
    assert doc.check_screener_stale()["status"] == "error"


def test_doctor_stale_ok_at_measured_baseline(doc, tmp_path):
    # Ca thật 16/10: 390/1.724 (22.6%) — 132 mã trễ 6–20 phiên, 258 mã > 20 phiên.
    lags = {f"N{i:03d}": 10 for i in range(132)} | {f"O{i:03d}": 60 for i in range(258)}
    _write(tmp_path, stale_excluded=_stale(lags))
    r = doc.check_screener_stale()
    assert r["status"] == "ok"
    assert "390/1,724 mã (22.6%)" in r["message"]
    assert "> 5 phiên" in r["message"]
    assert "132 mã trễ 6–20 phiên" in r["message"] and "258 mã > 20 phiên" in r["message"]
    assert "2026-10-16" in r["message"]


def test_doctor_stale_warn_only_above_ratio(doc, tmp_path):
    at = round(1724 * doc.SCREENER_STALE_WARN_RATIO)                     # đúng ngưỡng ⇒ vẫn ok
    _write(tmp_path, stale_excluded=_stale({f"T{i:04d}": 30 for i in range(at)}))
    assert doc.check_screener_stale()["status"] == "ok"
    _write(tmp_path, stale_excluded=_stale({f"T{i:04d}": 8 for i in range(at + 1)}))
    r = doc.check_screener_stale()
    assert r["status"] == "warn"
    assert "Lệch cơ sở" in r["fix"] and "tab Screener" in r["fix"]


def test_doctor_stale_registered(doc):
    assert doc.check_screener_stale in doc.OFFLINE_CHECKS
    assert 0 < doc.SCREENER_STALE_WARN_RATIO < 1


def test_doctor_stale_warns_when_filter_could_not_run(doc, tmp_path):
    # Kho thiếu lịch VNINDEX ⇒ screener không lọc được gì; "0 mã bỏ" lúc đó KHÔNG phải kho sạch.
    _write(tmp_path, stale_excluded=_stale({}) | {"sessions": 0})
    r = doc.check_screener_stale()
    assert r["status"] == "warn" and "VNINDEX" in r["message"]
    _write(tmp_path, stale_excluded=_stale({}) | {"sessions": 300})
    assert doc.check_screener_stale()["status"] == "ok"
