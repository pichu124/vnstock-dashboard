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
