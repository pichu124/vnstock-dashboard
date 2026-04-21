# Phase 5C — Dashboard Action Buttons — Test Checklist

This doc tracks **manual** UI tests that must be run after the user's live-trading window closes. The Streamlit UI can't be unit-tested realistically, so these are eyes-on checks.

**Commit to verify:** `<fill in after push>` on `claude/financial-data-architecture-SXZtC`.

**Pre-requisites:**
```powershell
git fetch origin --force --prune
git reset --hard origin/claude/financial-data-architecture-SXZtC
python run.py --warehouse data_warehouse dashboard
# → click tab "⚕️ Sức khỏe"
# → scroll to section "🛠 Hành động nhanh"
```

## Test matrix

### A. Bulk tab (`🎯 Bulk (theo kind)`)

| # | Steps | Expected |
|---|---|---|
| A1 | Click tab Bulk | 3 dropdowns (Kind, Severity, Action) + Dry-run checkbox + Limit input + Execute button render without error |
| A2 | Kind=ohlc, Severity=fail, Action=accept, Dry-run ON, Execute | Green banner `total=N ok=N fail=0 error=0` where N is count of fail-severity ohlc anomalies |
| A3 | Kind=vol_spike, Severity=(tất cả), Action=accept, Dry-run ON, Execute | Green banner, numbers match `python run.py top-offenders --by-kind vol_spike` count |
| A4 | Same as A3 but Limit=5 | `total=5` or less |
| A5 | Same as A2, Dry-run **OFF** | `_meta/anomaly_whitelist.json` appended with N new entries. Info msg suggests re-audit. |
| A6 | Action=refetch, Kind=ohlc, Severity=fail, Limit=2, Dry-run OFF | 2 API calls; if API responds, `_meta/remediation_log.jsonl` gets 2 lines with action=refetch |
| A7 | Empty warehouse (no anomalies.json) | Info message "Chưa có anomaly — chạy `audit` trước." |

### B. Single bar tab (`🔧 Một bar cụ thể`)

| # | Steps | Expected |
|---|---|---|
| B1 | Open tab | Ticker + date fields pre-filled with first anomaly (if present). Action dropdown. Kind hint. Note field. |
| B2 | Ticker=VCB, Date=2026-04-15, Action=accept, Kind=band, Note="halt test", Execute | Green banner `✓ accept VCB 2026-04-15: ...`. `_meta/anomaly_whitelist.json` gains `VCB/2026-04-15/band`. |
| B3 | Empty ticker field + Execute | Red error "Cần cả ticker và date." |
| B4 | Action=note without Note text + Execute | Red error "Action `note` cần --note text." |
| B5 | Action=refetch, Ticker=nonsense, Date=2026-04-15, Execute | Warning/error with meaningful message (API failure propagated) |
| B6 | Action=archive, valid ticker/date that exists in warehouse, Execute | Green banner `✓ archive ...`. Warehouse parquet no longer contains that (ticker, date). **Destructive — verify on a test ticker only.** |

### C. Re-audit tab (`🔄 Chạy audit lại`)

| # | Steps | Expected |
|---|---|---|
| C1 | Click button with default Lookback=60, Include non-stocks=off | Spinner shows, then success/warning banner with exit code + stdout tail |
| C2 | Stdout tail contains the `[reconciler]` and `[audit]` lines that match CLI `python run.py audit --lookback 60` output |
| C3 | Reload dashboard — numbers in Reconciler and Anomalies sections update to reflect new audit |
| C4 | Lookback=30, Include non-stocks=ON + Execute | CLI includes `--include-non-stocks` in stdout |

### D. Cross-tab interactions

| # | Steps | Expected |
|---|---|---|
| D1 | Bulk accept 10 anomalies → Re-audit → anomaly count drops by ~10 | `_meta/anomalies.json` shows `skipped N whitelisted anomaly entry(ies)` in stderr |
| D2 | Single refetch 1 quarantined bar → quarantine entry cleared, warehouse has new row |
| D3 | `_meta/remediation_log.jsonl` grows by 1 line per action with correct JSON schema (at, action, ticker, date, result, detail) |

### E. Edge cases

| # | Steps | Expected |
|---|---|---|
| E1 | Click Execute on Bulk tab with no anomalies.json | Info message, no exception |
| E2 | Ticker with unicode (`vcb`) | Case-normalized to `VCB`, no error |
| E3 | Multiple dashboard windows open, both trigger bulk action | Atomic write retry absorbs Windows file lock; both succeed |

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
