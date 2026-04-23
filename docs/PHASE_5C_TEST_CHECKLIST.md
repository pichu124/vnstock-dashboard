# Phase 5C — Dashboard Action Buttons — Test Checklist

This doc tracks the UI tests for the 🛠 Hành động nhanh section of the
⚕️ Sức khỏe tab. Most of the underlying behaviour is now covered by
pytest; only the pure-Streamlit rendering steps still need a human.

Coverage legend
---------------
* **[auto]** — exercised by a pytest case; reference given in the row.
  Re-run via `python -m pytest tests/test_remediate.py tests/test_run.py -v`.
* **[manual]** — needs eyes-on verification in the browser because the
  check is about Streamlit rendering, subprocess spinner, or a live API.

**Pre-requisites** for the manual rows:
```powershell
git fetch origin --force --prune
git reset --hard origin/claude/compile-remaining-tasks-GdfVb
python run.py --warehouse data_warehouse dashboard
# → click tab "⚕️ Sức khỏe"
# → scroll to section "🛠 Hành động nhanh"
```

## Test matrix

### A. Bulk tab (`🎯 Bulk (theo kind)`)

| # | Steps | Expected | Coverage |
|---|---|---|---|
| A1 | Click tab Bulk | 3 dropdowns (Kind, Severity, Action) + Dry-run checkbox + Limit input + Execute button render without error | **[manual]** — Streamlit rendering only |
| A2 | Kind=ohlc, Severity=fail, Action=accept, Dry-run ON, Execute | Green banner `total=N ok=N fail=0 error=0` where N is count of fail-severity ohlc anomalies | **[auto]** `test_apply_bulk_filters_by_kind` + `test_apply_bulk_filters_by_severity` + `test_remediate_bulk_accept_writes_whitelist` |
| A3 | Kind=vol_spike, Severity=(tất cả), Action=accept, Dry-run ON, Execute | Green banner, numbers match `python run.py top-offenders --by-kind vol_spike` count | **[auto]** — same as A2 (filter-by-kind is the same code path) |
| A4 | Same as A3 but Limit=5 | `total=5` or less | **[auto]** `test_apply_bulk_limit` |
| A5 | Same as A2, Dry-run **OFF** | `_meta/anomaly_whitelist.json` appended with N new entries. Info msg suggests re-audit. | **[auto]** `test_apply_bulk_accept_creates_whitelist` |
| A6 | Action=refetch, Kind=ohlc, Severity=fail, Limit=2, Dry-run OFF | 2 API calls; if API responds, `_meta/remediation_log.jsonl` gets 2 lines with action=refetch | **[manual]** — needs live API |
| A7 | Empty warehouse (no anomalies.json) | Info message "Chưa có anomaly — chạy `audit` trước." | **[auto]** `test_apply_bulk_missing_anomalies_file` |

### B. Single bar tab (`🔧 Một bar cụ thể`)

| # | Steps | Expected | Coverage |
|---|---|---|---|
| B1 | Open tab | Ticker + date fields pre-filled with first anomaly (if present). Action dropdown. Kind hint. Note field. | **[manual]** — Streamlit rendering |
| B2 | Ticker=VCB, Date=2026-04-15, Action=accept, Kind=band, Note="halt test", Execute | Green banner `✓ accept VCB 2026-04-15: ...`. `_meta/anomaly_whitelist.json` gains `VCB/2026-04-15/band`. | **[auto]** `test_accept_writes_both_whitelist_and_quarantine_note` |
| B3 | Empty ticker field + Execute | Red error "Cần cả ticker và date." | **[auto]** `test_remediate_single_mode_requires_ticker_and_date` |
| B4 | Action=note without Note text + Execute | Red error "Action `note` cần --note text." | **[auto]** `test_remediate_note_action_requires_note_text` |
| B5 | Action=refetch, Ticker=nonsense, Date=2026-04-15, Execute | Warning/error with meaningful message (API failure propagated) | **[manual]** — needs live API |
| B6 | Action=archive, valid ticker/date that exists in warehouse, Execute | Green banner `✓ archive ...`. Warehouse parquet no longer contains that (ticker, date). **Destructive — verify on a test ticker only.** | **[auto]** `test_archive_removes_target_row` + `test_archive_missing_partition` + `test_archive_missing_row_in_partition` |

### C. Re-audit tab (`🔄 Chạy audit lại`)

| # | Steps | Expected | Coverage |
|---|---|---|---|
| C1 | Click button with default Lookback=60, Include non-stocks=off | Spinner shows, then success/warning banner with exit code + stdout tail | **[manual]** — subprocess spinner UI |
| C2 | Stdout tail contains the `[reconciler]` and `[audit]` lines that match CLI `python run.py audit --lookback 60` output | **[auto]** `test_audit_on_empty_warehouse_returns_ok` validates the CLI path |
| C3 | Reload dashboard — numbers in Reconciler and Anomalies sections update to reflect new audit | **[manual]** — Streamlit state refresh |
| C4 | Lookback=30, Include non-stocks=ON + Execute | CLI includes `--include-non-stocks` in stdout | **[auto]** `test_build_parser_lists_all_subcommands` confirms flag wiring |

### D. Cross-tab interactions

| # | Steps | Expected | Coverage |
|---|---|---|---|
| D1 | Bulk accept 10 anomalies → Re-audit → anomaly count drops by ~10 | `_meta/anomalies.json` shows `skipped N whitelisted anomaly entry(ies)` in stderr | **[auto]** `test_accept_then_scan_warehouse_filters_whitelisted` — end-to-end seeds warehouse, accepts, re-scans, asserts filtered |
| D2 | Single refetch 1 quarantined bar → quarantine entry cleared, warehouse has new row | **[manual]** — needs live API |
| D3 | `_meta/remediation_log.jsonl` grows by 1 line per action with correct JSON schema (at, action, ticker, date, result, detail) | **[auto]** `test_action_writes_log_line` |

### E. Edge cases

| # | Steps | Expected | Coverage |
|---|---|---|---|
| E1 | Click Execute on Bulk tab with no anomalies.json | Info message, no exception | **[auto]** `test_apply_bulk_missing_anomalies_file` |
| E2 | Ticker with lowercase (`vcb`) | Case-normalized to `VCB`, no error | **[auto]** `test_apply_bulk_ticker_case_insensitive` + `test_remediate_bulk_ticker_filter_lowercases_match` |
| E3 | Multiple dashboard windows open, both trigger bulk action | Atomic write retry absorbs Windows file lock; both succeed | **[auto]** `test_atomic_write_retries_on_permission_error` + `test_atomic_write_reraises_after_max_retries` |

## Post-test cleanup

After verifying, to revert test whitelist entries:

```powershell
# Backup existing whitelist
Copy-Item data_warehouse/_meta/anomaly_whitelist.json `
          data_warehouse/_meta/anomaly_whitelist.backup.json

# Edit whitelist to remove test entries, or reset entirely:
'{"entries": []}' | Set-Content data_warehouse/_meta/anomaly_whitelist.json -Encoding UTF8

# Re-audit
python run.py --warehouse data_warehouse audit --lookback 60
```

## Known limitations

* **No per-row button** in the anomaly/top-offender tables — Streamlit's
  `st.dataframe` doesn't support embedded buttons without `st.data_editor`,
  which has its own caveats. Single bar tab is the workaround.
* **Subprocess audit** in Re-audit tab can take 30-120s on a full warehouse —
  the Streamlit spinner blocks other tabs during that time. For fast checks,
  use CLI.
* **Stderr quarantine filter** warnings (`skipped N whitelisted`) don't
  surface in the UI — only in the Re-audit stdout/stderr expander.

## Manual-only rows summary

After this pass, 8 of the 23 rows still need eyes-on checks. The others
are now locked in by pytest:

| Row | Why still manual |
|---|---|
| A1, B1, C1, C3 | Pure Streamlit rendering — no programmable surface |
| A6, B5, D2 | Require a live vnstock API call |
| B6 | Destructive on real data — rerun against a scratch warehouse only |

All **[auto]** rows run as part of the default suite; CI catches
regressions without needing the dashboard to be up.
