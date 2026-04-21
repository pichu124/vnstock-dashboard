# Pending Work — Resume Checkpoint

**Last session ended at commit**: `f1d9068` (Step 8 refactor plan doc)
**Branch**: `claude/financial-data-architecture-SXZtC`
**Tests**: 344/344 pass

---

## ✅ Hoàn thành (không cần quay lại)

- Phase 1-4: foundation, contracts, anomaly, health, auditor, run.py orchestrator
- Phase 5A-D: quarantine + remediate CLI + dashboard action buttons + whitelist
- Phase 6A+6C: corp action registry + integration into anomaly & reconciler
- Phase 6B: CafeF cash-dividend scraper
- Option E: Smart WSS-miss detection in reconciler
- Top-offender analyzer, active-ticker filter, per-row diagnose tool
- BarAggregator sanity-check for suspect volumes
- Dashboard refactor plan documented (only Sức khỏe tab extracted so far)

**Metrics đạt được:**
| | Baseline | Sau session |
|---|---|---|
| Anomaly | 62,953 | ~1,979 (−97%) |
| Reconciler fail | 714 | 11 (−98.5%) |
| Tests | 121 | 344 (+185%) |

---

## ⏳ Việc còn dở (khi quay lại, làm theo thứ tự này)

### Ngay lập tức — verify hypothesis cho 11 reconciler fails còn lại

1. **Diagnose CDC + SBT** (xác nhận có phải cash dividend không)
   ```powershell
   python run.py --warehouse data_warehouse diagnose --ticker CDC --date 2026-04-15
   python run.py --warehouse data_warehouse diagnose --ticker SBT --date 2026-04-15
   ```
   → Paste output. Nếu verdict = "likely cash dividend" → đi bước 2. Nếu khác → xem xét ra sao.

2. **Import capital_history vào registry + re-audit**
   ```powershell
   python run.py --warehouse data_warehouse registry import-capital-history
   python run.py --warehouse data_warehouse registry show
   python run.py --warehouse data_warehouse audit --lookback 60
   ```
   → Expect: fail xuống < 5, active missing rate xuống ~3-5%.

3. **(Tuỳ chọn) Scrape CafeF cash dividends**
   - Thử 1 mã trước:
     ```powershell
     python run.py --warehouse data_warehouse cash-dividends --ticker CDC --register
     ```
   - Nếu work, full scrape (1-2 giờ):
     ```powershell
     python run.py --warehouse data_warehouse cash-dividends --bulk --register
     ```
   - Re-audit: CDC/SBT fails sẽ biến mất hoàn toàn.

### Ngắn hạn — verification còn dở

4. **PHASE_5C UI test** — 23 test case trong `docs/PHASE_5C_TEST_CHECKLIST.md` chạy từng cái để confirm UI buttons work đúng.

5. **Test LLM Auditor** — set `ANTHROPIC_API_KEY` trong `.env`, chạy:
   ```powershell
   python run.py --warehouse data_warehouse audit --llm
   ```
   Xem Claude audit response có ý nghĩa không.

6. **Setup Windows Scheduled Task** thay task PowerShell cũ:
   - Program: `python`
   - Args: `run.py --warehouse data_warehouse all`
   - Start in: repo root
   - Schedule: 18:00 thứ 2-6

### Trung hạn — code work còn lại

7. **Refactor 5 dashboard tabs theo `docs/REFACTOR_PLAN.md`:**
   - Portfolio tab (190 lines) — easiest, start here
   - Screener tab (389 lines)
   - Dòng Tiền tab (520 lines)
   - Thị trường tab (762 lines)
   - Phân tích tab (803 lines) — hardest, last
   - **⚠ Chỉ làm ngoài giờ live trading.** 1 tab / commit / session.

8. **WSS debug sâu** — fix root cause của volume inflation bug trong `vnstock_wss.py`
   - Sanity check defensive đã add (Step 6) nhưng chỉ chặn downstream.
   - Cần live data để debug: tìm code path nào dùng `accum_volume` thay vì `_delta_volume`.
   - Khi WSS chạy, monitor `BarAggregator.diagnostics()` → `suspect_count` > 0 là có bug.

### Dài hạn — nice-to-have

9. **Merge branch vào `main` qua PR** khi hài lòng.
10. **Archive old whitelist entries** — có 2,139 entries, nên organize.
11. **Add Vietstock scraper** như fallback cho CafeF.

---

## Quick commands để warm up khi quay lại

```powershell
# Sync code
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
git fetch origin --force --prune
git reset --hard origin/claude/financial-data-architecture-SXZtC
git log --oneline -5    # top phải là f1d9068

# Smoke test
python -m pytest tests/ -q     # phải thấy 344 passed

# Xem trạng thái warehouse
python run.py --warehouse data_warehouse scan --fast
```

---

## File mới tạo trong session (để navigate nhanh)

| File | Mục đích |
|---|---|
| `vnstock_contracts.py` | Pandera OHLCV/Fundamental/Tick schemas |
| `vnstock_quarantine.py` | Rejected row storage + retry |
| `vnstock_remediate.py` | Refetch/accept/archive CLI |
| `vnstock_reconciler.py` | Rollup vs API cross-reference |
| `vnstock_adjust.py` | Adjusted price layer |
| `vnstock_anomaly.py` | Band/OHLC/gap/vol_spike detection |
| `vnstock_health.py` | System health snapshot + ⚕️ Sức khỏe tab |
| `vnstock_auditor.py` | AuditorAgent abstract + Null/Claude/GPT |
| `vnstock_exchange_map.py` | Ticker → HOSE/HNX/UPCOM |
| `vnstock_corp_registry.py` | Authoritative corp action registry |
| `vnstock_cash_dividends.py` | CafeF cash dividend scraper |
| `vnstock_top_offenders.py` | Anomaly distribution analyzer |
| `vnstock_diagnose.py` | Per-row investigation tool |
| `run.py` | Unified orchestrator (10+ subcommands) |
| `tests/test_*.py` | 12 new test files, 344 cases |
| `docs/PHASE_5C_TEST_CHECKLIST.md` | 23 manual UI test cases |
| `docs/REFACTOR_PLAN.md` | Dashboard refactor roadmap |
| `docs/PENDING_WORK.md` | **This file** — resume checkpoint |
