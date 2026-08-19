"""Tests for vnstock_quarantine — storage + retrieval + summary."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from vnstock_quarantine import (
    accept_quarantine,
    bump_retry,
    clear_quarantine,
    list_quarantine,
    quarantine_dropped,
    quarantine_row,
    summary,
)


# ── quarantine_row ─────────────────────────────────────────────────────────

def test_quarantine_row_writes_file(tmp_path):
    path = quarantine_row(
        "VCB", "2026-04-15", "close<=0",
        {"close": 0, "volume": 1000},
        warehouse=tmp_path,
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["ticker"] == "VCB"
    assert data["bar_date"] == "2026-04-15"
    assert data["reason"] == "close<=0"
    assert data["raw_values"]["close"] == 0


def test_quarantine_row_normalises_ticker_case(tmp_path):
    quarantine_row("vcb", "2026-04-15", "x", {}, warehouse=tmp_path)
    path = tmp_path / "_meta/quarantine/VCB/2026-04-15.json"
    assert path.exists()


def test_quarantine_row_normalises_date(tmp_path):
    quarantine_row("VCB", pd.Timestamp("2026-04-15"), "x", {}, warehouse=tmp_path)
    assert (tmp_path / "_meta/quarantine/VCB/2026-04-15.json").exists()


def test_quarantine_row_preserves_retry_count_on_overwrite(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    bump_retry("VCB", "2026-04-15", warehouse=tmp_path)
    bump_retry("VCB", "2026-04-15", warehouse=tmp_path)
    # Re-quarantining the same bar should keep retry_count
    quarantine_row("VCB", "2026-04-15", "b", {}, warehouse=tmp_path)
    data = json.loads((tmp_path / "_meta/quarantine/VCB/2026-04-15.json").read_text())
    assert data["retry_count"] == 2
    assert data["reason"] == "b"


# ── list_quarantine ────────────────────────────────────────────────────────

def test_list_quarantine_empty(tmp_path):
    df = list_quarantine(tmp_path)
    assert df.empty


def test_list_quarantine_returns_all(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    quarantine_row("VCB", "2026-04-16", "b", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "c", {}, warehouse=tmp_path)
    df = list_quarantine(tmp_path)
    assert len(df) == 3
    assert set(df["ticker"]) == {"VCB", "FPT"}


def test_list_quarantine_filter_by_ticker(tmp_path):
    quarantine_row("VCB", "2026-04-15", "a", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "b", {}, warehouse=tmp_path)
    df = list_quarantine(tmp_path, ticker="FPT")
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "FPT"


# ── accept / clear / bump ─────────────────────────────────────────────────

def test_accept_marks_entry(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path, note="ok")
    data = json.loads((tmp_path / "_meta/quarantine/VCB/2026-04-15.json").read_text())
    assert data["accepted"] is True
    assert data["note"] == "ok"


def test_accept_missing_returns_false(tmp_path):
    assert accept_quarantine("XXX", "2026-04-15", warehouse=tmp_path) is False


def test_clear_removes_file(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert clear_quarantine("VCB", "2026-04-15", warehouse=tmp_path)
    assert not (tmp_path / "_meta/quarantine/VCB/2026-04-15.json").exists()


def test_bump_retry_increments(tmp_path):
    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    assert bump_retry("VCB", "2026-04-15", warehouse=tmp_path) == 1
    assert bump_retry("VCB", "2026-04-15", warehouse=tmp_path) == 2


# ── summary ────────────────────────────────────────────────────────────────

def test_summary_empty(tmp_path):
    s = summary(tmp_path)
    assert s["total"] == 0
    assert s["pending"] == 0


def test_summary_counts_and_breakdown(tmp_path):
    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    quarantine_row("VCB", "2026-04-16", "high<low", {}, warehouse=tmp_path)
    accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path)
    s = summary(tmp_path)
    assert s["total"] == 3
    assert s["accepted"] == 1
    assert s["pending"] == 2
    assert s["by_reason"]["close<=0"] == 2
    assert s["by_reason"]["high<low"] == 1


# ── quarantine_dropped (bulk from contract output) ────────────────────────

def test_quarantine_dropped_bulk(tmp_path):
    dropped = pd.DataFrame({
        "ticker": ["VCB", "FPT", "MBB"],
        "time": ["2026-04-15", "2026-04-15", "2026-04-16"],
        "close": [0, -1, 100],
        "volume": [1000, 1000, -5],
    })
    n = quarantine_dropped(
        dropped,
        reasons=["close<=0", "close<=0", "volume<0"],
        warehouse=tmp_path,
    )
    assert n == 3
    df = list_quarantine(tmp_path)
    assert len(df) == 3


def test_quarantine_dropped_empty_df(tmp_path):
    assert quarantine_dropped(pd.DataFrame(), "x", warehouse=tmp_path) == 0


def test_quarantine_dropped_single_reason_broadcasts(tmp_path):
    dropped = pd.DataFrame({
        "ticker": ["VCB", "FPT"],
        "time": ["2026-04-15", "2026-04-15"],
        "close": [0, -1],
    })
    n = quarantine_dropped(dropped, reasons="bad data", warehouse=tmp_path)
    assert n == 2
    for t in ("VCB", "FPT"):
        data = json.loads((tmp_path / f"_meta/quarantine/{t}/2026-04-15.json").read_text())
        assert data["reason"] == "bad data"


# ── auto_heal ────────────────────────────────────────────────────────────


def test_auto_heal_empty_warehouse(tmp_path):
    """No quarantine → zero stats, no errors."""
    from vnstock_quarantine import auto_heal
    stats = auto_heal(tmp_path)
    assert stats == {
        "scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
        "archived": 0, "skipped_accepted": 0,
    }


def test_auto_heal_skips_accepted_entries(tmp_path, monkeypatch):
    """User-accepted entries are left alone — we never retry them."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    accept_quarantine("VCB", "2026-04-15", warehouse=tmp_path)

    called = {"n": 0}

    def _fake_refetch(*_a, **_kw):
        called["n"] += 1
        return {"status": "ok"}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert called["n"] == 0
    assert stats["skipped_accepted"] == 1
    assert stats["refetched_ok"] == 0


def test_auto_heal_refetches_and_clears_on_success(tmp_path, monkeypatch):
    """Happy path — refetch returns ok, entry is cleared by refetch()."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)

    def _fake_refetch(ticker, bar_date, *, warehouse, **_kw):
        # Simulate successful refetch: clear the entry the way the real
        # vnstock_remediate.refetch does.
        clear_quarantine(ticker, bar_date, warehouse=warehouse)
        return {"status": "ok", "rows_written": 1}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats == {
        "scanned": 1, "refetched_ok": 1, "refetched_fail": 0,
        "archived": 0, "skipped_accepted": 0,
    }
    assert list_quarantine(tmp_path).empty


def test_auto_heal_bumps_retry_on_failure(tmp_path, monkeypatch):
    """Failed refetch → retry_count goes up, entry stays in quarantine."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        return {"status": "fail", "reason": "API down"}

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats["refetched_fail"] == 1
    df = list_quarantine(tmp_path)
    assert len(df) == 1
    assert int(df.iloc[0]["retry_count"]) == 1


def test_auto_heal_archives_after_max_retries(tmp_path, monkeypatch):
    """retry_count >= max_retries → entry is removed + log line appended."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    # Pre-bump to 3 (MAX_RETRIES_DEFAULT)
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("refetch must not be called when retries exhausted")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path)
    assert stats["archived"] == 1
    assert stats["refetched_ok"] == 0
    assert list_quarantine(tmp_path).empty

    log = tmp_path / "_meta" / "remediation_log.jsonl"
    assert log.exists()
    line = json.loads(log.read_text().strip().splitlines()[-1])
    assert line["action"] == "auto_archive"
    assert line["ticker"] == "VCB"
    assert line["date"] == "2026-04-15"
    assert "retries=3" in line["detail"]


def test_auto_heal_dry_run_never_mutates(tmp_path, monkeypatch):
    """dry_run=True: scans and reports but touches nothing."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    # Push past max_retries so an archive WOULD happen
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("should not be called during dry_run")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path, dry_run=True)
    assert stats["archived"] == 1   # counted but not executed
    # Entry still on disk; log not written
    df = list_quarantine(tmp_path)
    assert len(df) == 1
    log = tmp_path / "_meta" / "remediation_log.jsonl"
    assert not log.exists()


def test_auto_heal_dry_run_counts_pending_refetches(tmp_path, monkeypatch):
    """dry-run on fresh entries must surface the planned refetch count so
    the operator sees WHAT would happen, not a silent all-zero report."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    quarantine_row("FPT", "2026-04-15", "x", {}, warehouse=tmp_path)

    def _fake_refetch(*_a, **_kw):
        raise AssertionError("should not be called during dry_run")

    monkeypatch.setattr("vnstock_remediate.refetch", _fake_refetch)
    stats = auto_heal(tmp_path, dry_run=True)
    assert stats["refetched_ok"] == 2, \
        "dry-run should report the planned refetch count, not 0"
    assert stats["archived"] == 0
    # Nothing mutated — retry_count stays at 0 and entries survive
    df = list_quarantine(tmp_path)
    assert len(df) == 2
    assert all(int(r["retry_count"]) == 0 for _, r in df.iterrows())


def test_auto_heal_no_archive_option_leaves_exhausted_entries(tmp_path, monkeypatch):
    """archive_exhausted=False: count archives but keep on disk."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "x", {}, warehouse=tmp_path)
    for _ in range(3):
        bump_retry("VCB", "2026-04-15", warehouse=tmp_path)

    monkeypatch.setattr("vnstock_remediate.refetch",
                         lambda *a, **k: {"status": "ok"})
    stats = auto_heal(tmp_path, archive_exhausted=False)
    assert stats["archived"] == 1
    # Entry survives
    assert not list_quarantine(tmp_path).empty


# ── Trần thời gian auto_heal ─────────────────────────────────────────────
# Đo trên máy thật 19/08: `auto-heal 2.156,7s` = 35,9 phút = 83% cả bước sync
# và 51% cả phát pipeline. Mỗi mục hàng đợi là MỘT lần gọi mạng, nên hàng đợi
# phình là cửa sổ chạy đêm phình theo — mà task lịch có trần cứng, chạm trần
# là mất brief. Cắt được vì auto_heal idempotent: phần chưa xử lý còn nguyên.


def _queue(tmp_path, n: int, day0: int = 1):
    for i in range(n):
        quarantine_row("VCB", f"2026-04-{day0 + i:02d}", "close<=0", {},
                       warehouse=tmp_path)


def test_auto_heal_stops_at_the_time_budget_and_reports_the_rest(
        tmp_path, monkeypatch):
    from vnstock_quarantine import auto_heal

    _queue(tmp_path, 5)
    clock = {"t": 0.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])

    def _slow_refetch(ticker, bar_date, *, warehouse, **_kw):
        clock["t"] += 10.0                      # mỗi mục "tốn" 10s
        clear_quarantine(ticker, bar_date, warehouse=warehouse)
        return {"status": "ok"}

    monkeypatch.setattr("vnstock_remediate.refetch", _slow_refetch)
    stats = auto_heal(tmp_path, time_budget_s=25.0)

    assert stats["stopped_early"] is True
    assert stats["scanned"] == 3                # 0s, 10s, 20s → mục thứ 4 bị chặn
    assert stats["remaining"] == 2
    assert stats["refetched_ok"] == 3


def test_auto_heal_without_a_budget_runs_the_whole_queue(tmp_path, monkeypatch):
    from vnstock_quarantine import auto_heal

    _queue(tmp_path, 4)
    clock = {"t": 0.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])

    def _slow_refetch(ticker, bar_date, *, warehouse, **_kw):
        clock["t"] += 1_000.0
        clear_quarantine(ticker, bar_date, warehouse=warehouse)
        return {"status": "ok"}

    monkeypatch.setattr("vnstock_remediate.refetch", _slow_refetch)
    stats = auto_heal(tmp_path, time_budget_s=None)
    assert stats["scanned"] == 4
    assert "stopped_early" not in stats


def test_auto_heal_within_budget_reports_nothing_extra(tmp_path, monkeypatch):
    """Không được thêm khoá lạ vào stats khi chạy trọn — dòng log trong
    `run.py` chỉ in cảnh báo khi THẬT SỰ bị cắt."""
    from vnstock_quarantine import auto_heal

    _queue(tmp_path, 2)

    def _fast_refetch(ticker, bar_date, *, warehouse, **_kw):
        clear_quarantine(ticker, bar_date, warehouse=warehouse)
        return {"status": "ok"}

    monkeypatch.setattr("vnstock_remediate.refetch", _fast_refetch)
    stats = auto_heal(tmp_path, time_budget_s=600.0)
    assert stats == {"scanned": 2, "refetched_ok": 2, "refetched_fail": 0,
                     "archived": 0, "skipped_accepted": 0}


def test_dry_run_ignores_the_budget(tmp_path, monkeypatch):
    """Chạy thử không gọi mạng nên không có gì để chặn — cắt ở đây chỉ làm
    người đọc thấy sai hình dạng hàng đợi."""
    from vnstock_quarantine import auto_heal

    _queue(tmp_path, 6)
    monkeypatch.setattr("time.monotonic", lambda: 10_000.0)
    stats = auto_heal(tmp_path, dry_run=True, time_budget_s=1.0)
    assert stats["scanned"] == 6 and "stopped_early" not in stats


def test_budget_default_is_wired_and_bounded():
    """Trần mặc định phải TỒN TẠI và nhỏ hơn hẳn 36 phút đã đo."""
    from vnstock_quarantine import AUTO_HEAL_BUDGET_S
    assert 0 < AUTO_HEAL_BUDGET_S <= 900


# ── Vắng CÓ CẤU TRÚC vs trục trặc nhất thời ──────────────────────────────
# Đo 19/08 trên máy thật: `scanned=3844 healed=35 retry_bumped=3809 archived=0`
# — 99,1% lượt gọi mạng vô ích, và mỗi mục còn phải trượt đủ max_retries ĐÊM
# nữa mới được dọn, mỗi đêm 36 phút. Nguồn TRẢ LỜI được mà không có bar ngày
# đó thì thử lại đêm mai chắc chắn cũng vậy.


def test_structural_absence_is_archived_immediately(tmp_path, monkeypatch):
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    monkeypatch.setattr(
        "vnstock_remediate.refetch",
        lambda *a, **k: {"status": "fail", "reason": "no row for target date"})

    stats = auto_heal(tmp_path)
    assert stats["archived"] == 1
    assert stats["archived_structural"] == 1
    assert stats["refetched_fail"] == 0
    assert list_quarantine(tmp_path).empty, "mục vắng cấu trúc phải được dọn"


def test_empty_api_response_still_goes_through_the_retry_path(tmp_path,
                                                              monkeypatch):
    """"API returned empty" là MƠ HỒ — có thể là outage cả cửa sổ 5 ngày. Dọn
    ngay ở đây là một đợt outage xoá sạch hàng đợi."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    monkeypatch.setattr(
        "vnstock_remediate.refetch",
        lambda *a, **k: {"status": "fail", "reason": "API returned empty"})

    stats = auto_heal(tmp_path)
    assert stats["refetched_fail"] == 1
    assert stats["archived"] == 0
    assert not list_quarantine(tmp_path).empty     # vẫn giữ để thử lại


def test_transient_error_still_goes_through_the_retry_path(tmp_path, monkeypatch):
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    monkeypatch.setattr(
        "vnstock_remediate.refetch",
        lambda *a, **k: {"status": "error", "reason": "fetch failed: timeout"})

    stats = auto_heal(tmp_path)
    assert stats["refetched_fail"] == 1 and stats["archived"] == 0


def test_structural_archive_is_traceable_in_the_remediation_log(tmp_path,
                                                                monkeypatch):
    """Dọn mà không để lại vết là xoá dữ liệu trong bóng tối."""
    import json

    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    monkeypatch.setattr(
        "vnstock_remediate.refetch",
        lambda *a, **k: {"status": "fail", "reason": "no row for target date"})
    auto_heal(tmp_path)

    log = tmp_path / "_meta" / "remediation_log.jsonl"
    assert log.exists()
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]
    assert any("vắng cấu trúc" in str(r) for r in rows)


def test_archive_exhausted_false_never_deletes_anything(tmp_path, monkeypatch):
    """Cờ tắt-dọn phải chặn CẢ đường vắng-cấu-trúc, không chỉ đường hết lượt."""
    from vnstock_quarantine import auto_heal

    quarantine_row("VCB", "2026-04-15", "close<=0", {}, warehouse=tmp_path)
    monkeypatch.setattr(
        "vnstock_remediate.refetch",
        lambda *a, **k: {"status": "fail", "reason": "no row for target date"})

    auto_heal(tmp_path, archive_exhausted=False)
    assert not list_quarantine(tmp_path).empty
