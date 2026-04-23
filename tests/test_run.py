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
            "cash-dividends", "test", "dashboard", "all"} <= names


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
