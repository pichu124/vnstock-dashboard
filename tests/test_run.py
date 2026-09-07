"""Smoke tests for run.py — orchestrator CLI dispatch."""

from __future__ import annotations

import argparse

import pytest

import run as orchestrator


def test_build_parser_lists_all_subcommands():
    parser = orchestrator.build_parser()
    # argparse exposes the subcommand names via the action's choices
    sub_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    names = set(sub_action.choices.keys())
    assert {"scan", "sync", "validate", "audit", "refresh-metadata",
            "remediate", "top-offenders", "diagnose", "registry",
            "vietstock", "freefloat", "screener", "test", "dashboard", "all"} <= names
    # `cash-dividends` đã BỎ 26/08 (U36): cào CafeF, 404 từ 19/08, không nằm
    # trong `cmd_all`, và thứ nó nuôi nay đọc thẳng sổ đăng ký.
    assert "cash-dividends" not in names


def test_dispatch_table_matches_parser():
    parser = orchestrator.build_parser()
    sub_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    names = set(sub_action.choices.keys())
    assert names == set(orchestrator._DISPATCH.keys())


def test_scan_runs_on_empty_warehouse(tmp_path, capsys):
    # scan should work even with no data — it just reports 0 tickers + warning
    rc = orchestrator.main(["--warehouse", str(tmp_path), "scan"])
    out = capsys.readouterr().out
    assert '"ticker_count": 0' in out
    # scan returns 1 when there are warnings, which is expected for empty dir
    assert rc in (0, 1)


def test_audit_on_empty_warehouse_returns_ok(tmp_path):
    # No data means no reconciliation drift and no anomalies → rc=0
    rc = orchestrator.main([
        "--warehouse", str(tmp_path), "audit", "--lookback", "5",
    ])
    assert rc == 0


def test_audit_with_null_auditor_works(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = orchestrator.main([
        "--warehouse", str(tmp_path), "audit", "--lookback", "5",
        "--llm", "--auditor", "null",
    ])
    assert rc == 0


def test_missing_subcommand_fails():
    with pytest.raises(SystemExit):
        orchestrator.main([])


# ── Phase 5C remediate CLI validation (covers checklist B3, B4, E2) ──────

def test_remediate_single_mode_requires_ticker_and_date(tmp_path, capsys):
    """Checklist B3: empty ticker/date without --all → exit 2 + error msg."""
    rc = orchestrator.main([
        "--warehouse", str(tmp_path),
        "remediate", "--action", "accept",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--ticker and --date" in err or "single-target mode" in err


def test_remediate_note_action_requires_note_text(tmp_path, capsys):
    """Checklist B4: --action note without --note → exit 2 + error msg."""
    # Prepare a quarantine entry so note has something to attach to (optional);
    # the validation fires before that anyway.
    rc = orchestrator.main([
        "--warehouse", str(tmp_path),
        "remediate",
        "--ticker", "VCB", "--date", "2026-04-15",
        "--action", "note",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--note" in err


def test_remediate_bulk_accept_writes_whitelist(tmp_path, capsys):
    """Checklist A2/A5: bulk accept via CLI writes the whitelist."""
    import json

    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "anomalies.json").write_text(json.dumps({
        "anomalies": [
            {"ticker": "VCB", "trading_date": "2026-04-15",
             "kind": "band", "severity": "warn",
             "detail": "test", "metrics": {}},
        ],
    }))

    rc = orchestrator.main([
        "--warehouse", str(tmp_path),
        "remediate", "--all", "--action", "accept",
    ])
    assert rc == 0
    wl = json.loads((meta / "anomaly_whitelist.json").read_text())
    tickers = [e["ticker"] for e in wl["entries"]]
    assert "VCB" in tickers


def test_remediate_bulk_ticker_filter_lowercases_match(tmp_path, capsys):
    """Checklist E2: `--ticker vcb` (lowercase) must only hit VCB rows."""
    import json

    meta = tmp_path / "_meta"
    meta.mkdir(parents=True)
    (meta / "anomalies.json").write_text(json.dumps({
        "anomalies": [
            {"ticker": "VCB", "trading_date": "2026-04-15",
             "kind": "band", "severity": "warn",
             "detail": "", "metrics": {}},
            {"ticker": "FPT", "trading_date": "2026-04-15",
             "kind": "band", "severity": "warn",
             "detail": "", "metrics": {}},
        ],
    }))

    rc = orchestrator.main([
        "--warehouse", str(tmp_path),
        "remediate", "--all", "--action", "accept",
        "--ticker", "vcb",   # lowercase on purpose
    ])
    assert rc == 0
    wl = json.loads((meta / "anomaly_whitelist.json").read_text())
    tickers = {e["ticker"] for e in wl["entries"]}
    assert tickers == {"VCB"}, f"expected only VCB, got {tickers}"


# ── cmd_sync self-heal integration ─────────────────────────────────────


def test_sync_runs_fix_units_and_auto_heal_by_default(tmp_path, monkeypatch):
    """After updater + rollup succeed, sync must invoke fix-units then
    quarantine auto-heal. Both are toggleable via --no-* flags."""
    # Stub out the two subprocess steps — they're heavy and off-topic
    monkeypatch.setattr(orchestrator, "_run", lambda _cmd: 0)

    called = {"fix_units": 0, "auto_heal": 0}

    class _FakeReport:
        fixes = []
        ticker_count = 0

    def _fake_fix(*_a, **_kw):
        called["fix_units"] += 1
        return _FakeReport()

    def _fake_heal(*_a, **_kw):
        called["auto_heal"] += 1
        return {
            "scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
            "archived": 0, "skipped_accepted": 0,
        }

    # Patch the import targets inside the modules cmd_sync lazy-imports from
    import vnstock_fix_units as _fu
    import vnstock_quarantine as _q
    monkeypatch.setattr(_fu, "run", _fake_fix)
    monkeypatch.setattr(_q, "auto_heal", _fake_heal)

    rc = orchestrator.main(["--warehouse", str(tmp_path), "sync"])
    assert rc == 0
    assert called["fix_units"] == 1, "sync must call fix-units"
    assert called["auto_heal"] == 1, "sync must call auto_heal"


def test_sync_no_fix_units_flag_skips_fix_units(tmp_path, monkeypatch):
    """--no-fix-units must not invoke fix-units, but auto-heal still runs."""
    monkeypatch.setattr(orchestrator, "_run", lambda _cmd: 0)
    called = {"fix_units": 0, "auto_heal": 0}

    def _fake_fix(*_a, **_kw):
        called["fix_units"] += 1
        class _R:
            fixes = []
            ticker_count = 0
        return _R()

    def _fake_heal(*_a, **_kw):
        called["auto_heal"] += 1
        return {"scanned": 0, "refetched_ok": 0, "refetched_fail": 0,
                 "archived": 0, "skipped_accepted": 0}

    import vnstock_fix_units as _fu
    import vnstock_quarantine as _q
    monkeypatch.setattr(_fu, "run", _fake_fix)
    monkeypatch.setattr(_q, "auto_heal", _fake_heal)

    rc = orchestrator.main([
        "--warehouse", str(tmp_path), "sync", "--no-fix-units",
    ])
    assert rc == 0
    assert called["fix_units"] == 0, "--no-fix-units must suppress the pass"
    assert called["auto_heal"] == 1, "auto-heal still runs by default"


class TestAutohealBudgetSwitch:
    """Vết 07/09 — **lời khuyên của badge làm NGƯỢC lại điều nó hứa.**

    Badge doctor in: *"hạ trần: VNSTOCK_AUTOHEAL_BUDGET_S=120 (hoặc 0 để tắt
    hẳn)"*. Code cũ::

        _budget = float(os.environ.get("VNSTOCK_AUTOHEAL_BUDGET_S")
                        or AUTO_HEAL_BUDGET_S)
        ... time_budget_s=_budget if _budget > 0 else None

    Chuỗi `"0"` là TRUTHY nên `or` không rơi về mặc định ⇒ `_budget = 0.0` ⇒
    `time_budget_s=None`, mà trong `auto_heal` `None` nghĩa là **KHÔNG CHẶN
    GIỜ**. Làm đúng theo badge sẽ cho auto-heal chạy **không giới hạn** — mỗi
    mục hàng đợi là một lần gọi mạng, và task Daily có trần cứng 120 phút.
    Đúng hình dạng đã giết lượt chạy 04/09 (sync một mình 179,4 phút).
    """

    def _b(self, monkeypatch, val):
        import run as R
        if val is None:
            monkeypatch.delenv("VNSTOCK_AUTOHEAL_BUDGET_S", raising=False)
        else:
            monkeypatch.setenv("VNSTOCK_AUTOHEAL_BUDGET_S", val)
        return R._autoheal_budget()

    def test_zero_now_means_OFF_not_unlimited(self, monkeypatch):
        assert self._b(monkeypatch, "0") == (False, 0.0)

    def test_a_positive_value_is_a_ceiling(self, monkeypatch):
        assert self._b(monkeypatch, "120") == (True, 120.0)

    def test_unset_uses_the_module_default(self, monkeypatch):
        from vnstock_quarantine import AUTO_HEAL_BUDGET_S
        assert self._b(monkeypatch, None) == (True, AUTO_HEAL_BUDGET_S)

    def test_an_empty_string_is_not_an_off_switch(self, monkeypatch):
        """Biến môi trường đặt rỗng là chuyện thường trên Windows — coi nó là
        'tắt' thì auto-heal biến mất mà không ai gõ lệnh nào."""
        from vnstock_quarantine import AUTO_HEAL_BUDGET_S
        assert self._b(monkeypatch, "") == (True, AUTO_HEAL_BUDGET_S)

    def test_garbage_falls_back_to_the_default_not_to_off(self, monkeypatch):
        from vnstock_quarantine import AUTO_HEAL_BUDGET_S
        assert self._b(monkeypatch, "rác") == (True, AUTO_HEAL_BUDGET_S)

    def test_words_work_too(self, monkeypatch):
        for w in ("off", "no", "false", "OFF"):
            assert self._b(monkeypatch, w) == (False, 0.0), w

    def test_there_is_NO_WAY_to_ask_for_an_uncapped_run(self, monkeypatch):
        """Không ai cần chế độ không-trần, và nó là cái bẫy đã có sẵn. Mọi
        đường vào phải ra một trần DƯƠNG hoặc ra TẮT."""
        for v in (None, "", "0", "-1", "rác", "600", "off"):
            on, budget = self._b(monkeypatch, v)
            assert (budget > 0) if on else (budget == 0.0), v

    def test_the_ceiling_never_reaches_auto_heal_as_None(self):
        """`None` là cách `auto_heal` hiểu 'không chặn giờ'. Nhánh bật phải
        truyền một con số, không bao giờ truyền None."""
        import inspect

        import run as R
        src = inspect.getsource(R.cmd_sync)
        assert "time_budget_s=_budget" in src
        assert "else None" not in src.split("auto-heal")[-1][:400]
