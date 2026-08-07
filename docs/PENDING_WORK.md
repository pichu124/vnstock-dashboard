# Pending Work — Resume Checkpoint

> ⚠️ **File này ĐÃ CŨ (chốt 2026-05-28) và có nội dung lặp.** Danh sách việc
> phải làm/chờ verify ĐANG DÙNG nằm ở `docs/CLAUDE-NOTES.md`, mục
> **"📌 VIỆC PHẢI LÀM — chốt 08/08/2026"** (cuối file). Giữ file này làm sử
> liệu thôi.
>
> Riêng §6/§7 "WSS volume inflation bug" bên dưới: **đã fix 07/08**
> (`accum_raw is None` → delta 0, không nhiễm `_last_accum_vol`), chỉ còn
> chờ xác nhận live — xem mục CHỜ VERIFY 07/08 §1.

**Last session ended**: 2026-05-28 (post-review tune-up)
**Branch**: `claude/review-code-summary-DkAI7`
**Current state**: F1-F7 done, code review tune-ups applied (json logging,
data staleness badges, dynamic VN30 weights)

---

## ✅ Đã hoàn thành (gần đây nhất)

### Session 2026-05-27 — F1 + F3 features
- ✅ **F1. AI Brief Consensus + History** — consensus banner, lịch sử brief, accuracy tracker T+N
- ✅ **F3. News sentiment scoring** — Groq/Cerebras/OpenRouter batch scoring, SQLite cache, aggregate table, timeline chart, filter theo sentiment
- ✅ Bug fix: aggregate table không còn empty khi filter "Hôm nay"
- ✅ Bug fix: sticky "Hôm nay" filter tự reset sau refresh
- ✅ Brief accuracy baseline (2026-05-22): Groq 67%, Mistral/OpenRouter/Cerebras 50%
- ✅ News sentiment scoring: 5360/5360 tin đã chấm, tỷ lệ Trung lập cao phù hợp với loại tin corporate disclosure

### Session 2026-05-18 — code review + dọn dẹp tồn đọng
- ✅ Reconciler **fail: 714 → 0**
- ✅ Bug fix `vnstock_remediate.py` — `VnstockWarehouse` case + `verbose` kwarg
- ✅ OpenRouter confirmed kết nối OK
- ✅ Dashboard refactor confirmed 7/7 tabs done
- ✅ UPCOM symbol alias: `UPCOMINDEX` — 100 rows, GTGD UPCOM real-time hoạt động
- ✅ Hallucination guard verified — không cite sai giá VNINDEX

**Metrics:**
| | Baseline ban đầu | Đạt được |
|---|---|---|
| Reconciler fail | 714 | **0** ✅ |
| Anomaly | 62,953 | ~705 (−99%) |
| News sentiment | 0 | 5360 tin scored ✅ |

---

## ⏳ Việc còn cần làm

### 🔴 Verify khi có data

1. **Verify VNINDEX loader** — sau phiên giao dịch 2026-05-28 (sau 15h):
   ```powershell
   python -c "
   from vnstock_session_stats import _fetch_price_history
   df = _fetch_price_history('VNINDEX')
   print(df[['trading_date','close','total_value']].tail(3))
   "
   ```
   - Kết quả mong đợi: 3 dòng cuối, ngày mới nhất = hôm nay hoặc ngày GD gần nhất
   - Nếu rỗng / thiếu ngày → chạy `python vnstock_train.py --once` để sync
   - Nếu vẫn rỗng → debug `collect_context()` trong `vnstock_brief.py`
   - Mục đích: F5 cần data này để tính MA20/MA50/MA200/RSI (4 trong 7 tín hiệu)

### 🟡 Verification còn dở

2. **Kiểm tra accuracy Brief sau 3–5 ngày** (từ 2026-05-22)
   - Vào tab Thị trường → mở "📜 Lịch sử brief" → chọn T+1, ngưỡng ±0.5%
   - Baseline: Groq 67% (2/3), Mistral/OpenRouter/Cerebras 50%
   - Sample mục tiêu: ≥ 10 briefs evaluated/agent mới có ý nghĩa thống kê
   - Nếu 1 agent nổi bật → dùng làm primary source cho Consensus

3. **PHASE_5C UI test** — 23 test case trong `docs/PHASE_5C_TEST_CHECKLIST.md`.

4. **Test LLM Auditor** — set `ANTHROPIC_API_KEY` trong `.env`:
   ```powershell
   python run.py --warehouse data_warehouse audit --llm
   ```

5. **Hallucination guard — observe production**
   Dùng AI Brief vài ngày. Nếu thấy banner 🚨 hoặc brief cite sai → báo lại.

### 🟠 Khi có thời điểm thích hợp

6. **CafeF scraper bị 404**
   - CafeF redesign 2026 → 4 URL template đều 404.
   - Fix: mở browser CafeF DevTools → tìm URL thực → update `CAFEF_URL_TEMPLATES`.
   - Alternative: thêm Vietstock.vn scraper làm fallback.

7. **WSS volume inflation bug** (`vnstock_wss.py`) — chỉ debug được trong giờ giao dịch.
   - Khi WSS chạy live: monitor `BarAggregator.diagnostics()` → `suspect_count > 0` là có bug.

### 🟢 Dài hạn / nice-to-have

8. Merge branch `claude/review-code-summary-DkAI7` vào `main` qua PR.
9. Archive/organize anomaly whitelist entries cũ.
10. Auto-schedule `vnstock_train.py` — hiện chạy manual.
11. Tìm realtime GTGD chính xác (iboard DevTools hoặc per-stock batch agg).

---

## 💡 Tính năng đề xuất — còn lại

### ✅ Đã làm
- **F1. AI Brief — Consensus + History** ✅ Done 2026-05-27
- **F2. Telegram bot push daily brief** ✅ Done 2026-05-28
- **F3. News sentiment scoring** ✅ Done 2026-05-27
- **F4. Foreign flow deep dive tab** ✅ Done 2026-05-27
- **F5. Market regime detector** ✅ Done 2026-05-27
- **F6. Backtest equity curve viz** ✅ Done 2026-05-28

### 🎯 Tiếp theo — ROI cao

**F2. Telegram bot push daily brief**
- Sáng 7h + chiều 15h tự push brief vào Telegram chat
- Bonus: push alert khi screener phát hiện setup mới qua ngày
- Reuse `generate_brief()` + Telegram bot token
- Effort: ~3-4 giờ

### 🟡 ROI trung — cần code mới

**F4. Foreign flow deep dive tab**
- Top 10 mã khối ngoại mua/bán ròng (today/week/month)
- Cumulative net buy/sell theo sector
- Foreign ownership ratio gần room (cảnh báo tránh mã sắp full)

**F5. Market regime detector**
- Bull / bear / sideways / risk-off classifier từ VNINDEX + breadth + foreign flow
- Auto-suggest screener preset phù hợp regime hiện tại

### 🟢 ROI thấp / nice-to-have

**F6. Backtest equity curve viz** — chart drawdown/equity cho strategy tab
**F7. Portfolio sector exposure** — % theo ngành + so VNINDEX benchmark
**F8. Tax calculator** — 0.1% bán + capital gain VN, realized/unrealized P&L

---

## Quick warm-up commands

```powershell
cd "E:\Dropbox\Claude vnstock"
git fetch origin --prune
git pull origin claude/review-code-summary-DkAI7
git log --oneline -5

# Xem trạng thái warehouse
python run.py --warehouse data_warehouse scan --fast

# Re-audit để check fail count
python run.py --warehouse data_warehouse audit --lookback 60
```

---

## Architecture cheat sheet (quick reference)

**Tab files** (sau refactor):
- `dashboard/screener_tab.py`, `analysis_tab.py`, `market_tab.py`,
  `money_flow_tab.py`, `news_tab.py`, `portfolio_tab.py`
- `vnstock_health.py` (⚕️ Sức khỏe — không trong dashboard/)
- `vnstock_dashboard.py` (router + shared loaders, ~3500 lines)

**Core modules:**
- `vnstock_brief.py` — AI agents + brief generation + memory wiring
- `vnstock_strategy.py` — AST-sandboxed strategy executor + backtest
- `vnstock_session_stats.py` — GTGD calibration (UPCOM = `UPCOMINDEX`)
- `vnstock_reconciler.py` — rollup vs API cross-reference
- `vnstock_sentiment.py` — news sentiment scoring (Groq/Cerebras/OpenRouter)
- `run.py` — unified orchestrator (10+ subcommands)

**Invariants không được phá** (xem CLAUDE.md):
- 4-panel chart sync: dùng logical-range API, KHÔNG time-range
- Hallucination guard: prompt sentinels + validator + UI banner (3 layer)


---

## ✅ Đã hoàn thành (gần đây nhất)

### Session 2026-05-18 — code review + dọn dẹp tồn đọng
- ✅ Reconciler **fail: 714 → 0** (fix HSG 2026-04-29 stale rolled data)
- ✅ Bug fix `vnstock_remediate.py` — `VnstockWarehouse` case + `verbose` kwarg
- ✅ OpenRouter confirmed kết nối OK
- ✅ Dashboard refactor confirmed 7/7 tabs done (docs cũ sai)
- ✅ UPCOM symbol alias: `UPCOMINDEX` — 100 rows, GTGD UPCOM real-time hoạt động
- ✅ Hallucination guard verified — không cite sai giá VNINDEX

### Sessions trước
- Phase 1-4: foundation, contracts, anomaly, health, auditor, run.py orchestrator
- Phase 5A-D: quarantine + remediate CLI + dashboard action buttons + whitelist
- Phase 6A-C: corp action registry + CafeF cash-dividend scraper (broken, see below)
- Option E: Smart WSS-miss detection in reconciler
- Top-offender analyzer, active-ticker filter, per-row diagnose tool
- BarAggregator sanity-check for suspect volumes
- **Dashboard refactor**: extract 7/7 tabs into `dashboard/*.py` + `vnstock_health.py`

**Metrics:**
| | Baseline ban đầu | Đạt được |
|---|---|---|
| Reconciler fail | 714 | **0** ✅ |
| Anomaly | 62,953 | ~705 (−99%) |

---

## ⏳ Việc còn cần làm

### 🔴 Verify khi có data hôm nay

1. **Verify VNINDEX loader** sau khi daily sync chạy:
   ```powershell
   python -c "
   from vnstock_session_stats import _fetch_price_history
   df = _fetch_price_history('VNINDEX')
   print(df[['trading_date','total_value']].tail(3))
   "
   ```
   Nếu rỗng → debug `collect_context()` trong `vnstock_brief.py` (loader nào fail).

### 🟡 Verification còn dở

2. **Kiểm tra accuracy Brief sau 3–5 ngày** (từ 2026-05-22)
   - Vào tab Thị trường → mở "📜 Lịch sử brief" → chọn T+1, ngưỡng ±0.5%
   - Baseline hiện tại (2026-05-22): Groq 67% (2/3), Mistral/OpenRouter/Cerebras 50% (1–2 briefs đánh giá được)
   - Sample mục tiêu: ≥ 10 briefs evaluated/agent mới có ý nghĩa thống kê
   - Nếu 1 agent nổi bật hơn hẳn → xem xét dùng làm primary source cho Consensus
   - Nếu tất cả đều ~50% ở T+1 → thử T+2 hoặc T+3 horizon thay thế

3. **PHASE_5C UI test** — 23 test case trong `docs/PHASE_5C_TEST_CHECKLIST.md`.
   Chạy từng `[manual]` case để confirm UI buttons work đúng.

3. **Test LLM Auditor** — set `ANTHROPIC_API_KEY` trong `.env`:
   ```powershell
   python run.py --warehouse data_warehouse audit --llm
   ```

4. **Hallucination guard — observe production**
   Dùng AI Brief vài ngày. Nếu thấy banner 🚨 xuất hiện hoặc brief cite sai
   giá VNINDEX → báo lại để mở rộng validator pattern.

### 🟠 Khi có thời điểm thích hợp

5. **CafeF scraper bị 404**
   - CafeF redesign 2026 → 4 URL template đều 404, WebFetch bị bot-detection chặn.
   - Workaround: register manual qua `run.py registry add` từ output `diagnose`.
   - Fix: mở browser CafeF DevTools → tìm URL thực → update `CAFEF_URL_TEMPLATES`
     trong `vnstock_cash_dividends.py`.
   - Alternative: thêm Vietstock.vn scraper làm fallback.

6. **WSS volume inflation bug** (`vnstock_wss.py`) — chỉ debug được trong giờ giao dịch.
   - Sanity check defensive đã có (Step 6) nhưng chỉ chặn downstream.
   - Khi WSS chạy live: monitor `BarAggregator.diagnostics()` → `suspect_count > 0` là có bug.
   - Tìm code path nào dùng `accum_volume` thay vì `_delta_volume`.

### 🟢 Dài hạn / nice-to-have

7. Merge branch `claude/review-code-summary-DkAI7` vào `main` qua PR.
8. Archive/organize 2,139 anomaly whitelist entries cũ.
9. Auto-schedule `vnstock_train.py` — hiện chạy manual.
10. Tìm realtime GTGD chính xác (iboard DevTools hoặc per-stock batch agg).

---

## 💡 Tính năng đề xuất (2026-05-18 brainstorm)

### 🎯 ROI cao — extend code đã có

**F1. AI Brief — Consensus + History** ⭐ ưu tiên
- Consensus view: tổng hợp stance/sector/risk từ tất cả agents → 1 dòng quyết định
- Brief history: lưu mỗi brief kèm rating ⭐ vào SQLite (reuse `vnstock_memory.py`)
- "Why this rating?": link past brief với giá thực tế T+1, T+5 → tracking AI accuracy
- Feedback loop: ratings thấp → tự động vào memory để tránh repeat
- Effort: ~1 ngày

**F2. Telegram bot push daily brief**
- Sáng 7h + chiều 15h tự push brief vào Telegram chat
- Bonus: push alert khi screener phát hiện setup mới qua ngày
- Reuse `generate_brief()` + Telegram bot token
- Effort: ~3-4 giờ — practical cao cho retail trader

### 🟡 ROI trung — cần code mới

**F3. News sentiment scoring**
- Thêm cột sentiment (+/−/neutral) qua AI cho mỗi tin
- Aggregate theo ticker: "tuần này VCB tin chủ yếu tích cực"
- Sentiment timeline + giá → correlation news-price
- Reuse Groq/Cerebras (rẻ + nhanh) chạy batch sentiment

**F4. Foreign flow deep dive tab**
- Top 10 mã khối ngoại mua/bán ròng (today/week/month)
- Cumulative net buy/sell theo sector
- Foreign ownership ratio gần room (cảnh báo tránh mã sắp full)

**F5. Market regime detector**
- Bull / bear / sideways / risk-off classifier
  từ VNINDEX + breadth + foreign flow
- Auto-suggest screener preset phù hợp regime hiện tại

### 🟢 ROI thấp / nice-to-have

**F6. Backtest equity curve viz** — chart drawdown/equity cho strategy tab
**F7. Portfolio sector exposure** — % theo ngành + so VNINDEX benchmark
**F8. Tax calculator** — 0.1% bán + capital gain VN, realized/unrealized P&L


---

## Quick warm-up commands

```powershell
cd "E:\Dropbox\Claude vnstock"
git fetch origin --prune
git pull origin claude/review-code-summary-DkAI7
git log --oneline -5     # top phải là 04ef7a7 hoặc mới hơn

# Xem trạng thái warehouse
python run.py --warehouse data_warehouse scan --fast

# Re-audit để check fail count
python run.py --warehouse data_warehouse audit --lookback 60
```

---

## Architecture cheat sheet (quick reference)

**Tab files** (sau refactor):
- `dashboard/screener_tab.py`, `analysis_tab.py`, `market_tab.py`,
  `money_flow_tab.py`, `news_tab.py`, `portfolio_tab.py`
- `vnstock_health.py` (⚕️ Sức khỏe — không trong dashboard/)
- `vnstock_dashboard.py` (router + shared loaders, ~3500 lines)

**Core modules:**
- `vnstock_brief.py` — AI agents + brief generation + memory wiring
- `vnstock_strategy.py` — AST-sandboxed strategy executor + backtest
- `vnstock_session_stats.py` — GTGD calibration (UPCOM = `UPCOMINDEX`)
- `vnstock_reconciler.py` — rollup vs API cross-reference
- `run.py` — unified orchestrator (10+ subcommands)

**Data flow:**
```
API → warehouse (prices/) → display
WSS → rolled/ → reconciler vs API → flag drift
```

**Invariants không được phá** (xem CLAUDE.md):
- 4-panel chart sync: dùng logical-range API, KHÔNG time-range
- Hallucination guard: prompt sentinels + validator + UI banner (3 layer)
