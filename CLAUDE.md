# Project notes for Claude Code

This file holds durable reminders/context for future sessions on this repo.
Items here get auto-loaded into Claude's context at session start.

---

## 📌 Pending suggestions (raise when relevant)

### 0. ⏰ NHẮC USER TEST — pending từ 2026-05-06 01:30

**Khi user mở session mới trong ngày 2026-05-07 hoặc sau đó:** chủ động nhắc test các fix dưới đây (user đã yêu cầu "mai nhắc tôi test"):

**Commit `9fec1d3` + `2ca28e2` — cần verify:**

1. **Screener tab "Thống kê giao dịch theo phiên"** (sau pull + restart Streamlit):
   - Cache cũ v3 tự purge → backfill chạy lại với `interval='5m'` + dedup
   - Check 9/3 và 10/3 trong 4 panel: số có ngang neighbors hay vẫn inflated?
   - Mỗi cell 9h-15h giờ có thêm fields `gtgd_matched` (chỉ khớp lệnh) và `gtgd_deal` (block deals).
   - Mở `data_warehouse/_meta/market_session_stats.json`, tìm `2026-03-09` → `9h-15h` → so sánh `gtgd` (total) vs `gtgd_matched` cho 9/3 vs 11/3.
   - Nếu `gtgd_matched` của 9/3 ≈ 11/3 nhưng `gtgd` chênh lệch → block deals giải thích, đề xuất switch UI sang `gtgd_matched`.
   - Recheck toàn bộ 30 ngày xem còn 0/0 cells nào không.

2. **News tab — POST-UPGRADE TEST (user upgrade vnstock 3.5.1 → 4.0.2):**
   - User đã quyết định upgrade vnstock + vnai. Sau upgrade restart Streamlit + click "🔄 Cập nhật tin tức".
   - **Verify 3 vấn đề:**
     a. VCI source còn `KeyError: 'data'` không? (Diagnostic test fetch → output có `vnstock_data.Company(source='VCI').news()` báo gì)
     b. Nếu VCI work → shape nhiều hơn 1 row/ticker không? (Hy vọng 5-10 articles/ticker thay vì 1)
     c. Date của latest article có move past 2026-04-29 không? (Nếu vẫn 4/29 → API limitation thật, không phải lib bug)
   - **Nếu VCI vẫn broken hoặc còn cap 1 tin/mã:** Đề xuất chuyển sang scrape vietstock.vn trực tiếp.
     - Pattern có sẵn trong `vnstock_vietstock.py` (đã dùng cho corp actions).
     - URL pattern: `https://finance.vietstock.vn/<TICKER>/tin-doanh-nghiep.htm`
     - Sẽ trả 10-30 articles/ticker với recency tốt.
     - Estimate: ~150 dòng code mới (parser HTML + tích hợp vào fetch_ticker_news fallback chain).
   - **User concern:** "tin tức không cập nhật từ 29/4 -> nhớ sửa lỗi này nhé". Pre-upgrade cache stuck ở 4/29 vì KBS chỉ trả tin tagged-to-ticker mới nhất, và những mã trong universe không có tin nào mới từ 4/29. Sau upgrade nếu VCI work → có thể có data tươi hơn.

**Branch:** `claude/fix-screener-trading-stats-2M4z2`
**Sau khi user confirm các fix work:** xoá entry này khỏi CLAUDE.md.

---

### 1. Auto-schedule `vnstock_train.py` (NOT YET SET UP)

**Status**: User chose to run manually for now (decided 2026-04-27).

**When to bring up again**:
- User mentions running `vnstock_train.py` and forgets / runs late
- User asks about automation, scheduling, or "letting it run on its own"
- User reports inconsistent / outdated training data
- User says brief quality is plateauing

**What to suggest**:
Set up Windows Task Scheduler (or cron on Linux) to run `python vnstock_train.py --once`
on a daily cadence aligned with VN market sessions:
- 11:35 (after morning session close) — optional
- 15:05 (after full close) — primary slot

PowerShell command ready to paste:
```powershell
schtasks /Create /SC DAILY /ST 15:05 /TN "VNStock Train" `
  /TR "<repo>\.venv\Scripts\python.exe <repo>\vnstock_train.py --once"
```

**Why daily and not continuous**: VN market data refreshes 1×/day. Running
the training loop more often wastes API tokens without new information.
The system is API-based (Claude/Groq/Mistral) — there are no model weights
to fine-tune locally; "training" here means refreshing prompt few-shots,
re-running strategy generation/backtest, and reconciling recommendations.

### 2. Xác nhận OpenRouter hoạt động sau fix dynamic model fetch (2026-04-28)

**Status**: Chưa xác nhận — commit `4f5ecce` deploy dynamic `/api/v1/models` fetch
nhưng user chưa test lại.

**When to bring up again**:
- User mở tab Thị trường và thấy OpenRouter vẫn lỗi
- User hỏi về OpenRouter agent

**What to check**:
- Nếu vẫn lỗi: xem error message cụ thể (giờ đã có response body)
- Nếu `_fetch_free_models` trả về list rỗng → /api/v1/models call thất bại
- Thử nút "🔌 Test" trong ⚙️ Cài đặt AI Agent để kiểm tra nhanh

### 3. ✅ Tách nút Quét tín hiệu + Dynamic training universe (DONE 2026-04-28)

**Commit**: `8485962`

- Nút "🔍 Quét tín hiệu toàn thị trường" tách biệt khỏi training buttons
- `emit_recommendations()` lọc vol ≥ 100K cổ/ngày (30-day avg)
- `_training_universe()` dynamic: live API → warehouse filter → volume rank
  - Lite: sector-stratified top-10 VN30 + top-7 VNMID = ~17 mã
  - Full: VN30 đủ + top-20 VNMID = ~50 mã
- `_sector_stratified()`: max 3 bank slots, 1 slot/ngành khác — không bao giờ cluster ngân hàng

---

## 🔧 Future improvements — tracked TODOs

### 1. Replace calibrated GTGD estimate with exact realtime source

**Status**: Currently using Option A — `vnstock_data Quote.history(interval='1m')`
intraday cumulative volume × per-index calibrated `avg_price/share` (computed
weekly from `Trading.price_history` last 10 days). Accuracy ~95-98% during
trading; auto-corrected to exact via `reconcile_with_price_history()` when
the EOD batch posts ~24h after market close.

**Why estimate**: vnstock_data does NOT expose realtime `total_value` for
indices. We exhaustively tested (see commit history of `_test_market_sources.py`):
- ❌ SSI iboard public URLs — all 404 (need DevTools URL discovery)
- ❌ cafef.vn public URLs — all 404
- ❌ `Trading.price_history` — EOD batch only, ~24h delay
- ❌ `Trading.put_through` — block deals only (~16% of total GTGD)
- ❌ `Trading.trading_stats / order_stats / side_stats` — `NotImplementedError`
- ❌ `Quote.intraday(VNINDEX)` — `ValueError: Invalid symbol`
- ❌ `Quote.history` columns — only OHLCV, no `total_value` for indices

**To improve when ready**:
1. Reverse-engineer real iboard.ssi.com.vn URL via browser DevTools network tab
   (look for XHR with `totalValue` / `totalNmValue` field)
2. Or test `price_board(all_HOSE_stocks)` batch latency — if <5s for 500
   symbols, can aggregate `match_price × accumulated_volume` per stock
3. Or use cafef live websocket if it exists
4. UPCOM symbol for `price_history` is unknown — currently tries fallbacks
   `["UPCOM", "UPINDEX", "UPCOM-INDEX", "HNXUPCOM"]`. Find the correct one.

**Files affected**: `vnstock_session_stats.py`, `dashboard/screener_tab.py`
(UI status indicator 🟡 estimate / 🟢 exact). Schema bumped to
`SESSION_STATS_FORMAT_VERSION = 3` to invalidate old data.

---

## ⚠️ Hard-won invariants — DO NOT change without reading this

### 4-panel chart sync (Price / Volume / RSI / MACD) — vnstock_dashboard.py

**MUST use logical-range API, never time-range API.**

```
subscribeVisibleLogicalRangeChange  ✓
getVisibleLogicalRange              ✓
setVisibleLogicalRange              ✓

subscribeVisibleTimeRangeChange     ✗  DO NOT USE
getVisibleRange                     ✗  DO NOT USE
setVisibleRange                     ✗  DO NOT USE
```

**Why**: `setVisibleRange({to: lastBarTime})` tells LWC the chart is at
"live position" and triggers a right-edge snap — all 4 panels lock to the
rightmost bar whenever the user pans right. Logical range uses bar indices
(floats, 0 … N-1+rightOffset); LWC never treats these as a time boundary.

**Prerequisite**: all 4 charts must have IDENTICAL bar counts. RSI/MACD
warmup bars (first ~14 / ~33 bars with no value) MUST be emitted as LWC
whitespace `{time: t}` (no `value` key), NOT skipped. If they are skipped,
the bar-count mismatch breaks the 1:1 logical-index mapping and re-introduces
the snap. See the data serialization loop (~line 2394) in `vnstock_dashboard.py`.

**Other rules in the same sync block**:
- Never call `setVisibleLogicalRange` from inside `subscribeVisibleLogicalRangeChange`
  on the same chart — corrupts LWC pan state (drag becomes zoom).
- `_ready` gate: keep callbacks suppressed until the initial
  `setVisibleLogicalRange` fires at T=200ms (prevents RSI/MACD auto-fit
  from polluting the range before the uniform initial view is applied).

---

## 🏗️ Architecture cheat sheet

- `vnstock_brief.py` — agent abstraction + brief generation + memory wiring
- `vnstock_memory.py` — SQLite store at `data_warehouse/_meta/brief_memory.db`
- `vnstock_strategy.py` — AST-sandboxed strategy executor + backtest engine
  - Sandbox: `InProcessExecutor` (Option A). Swap to `SubprocessExecutor`
    in `vnstock_strategy.py` when paranoid mode needed (Option B).
- `vnstock_train.py` — CLI orchestrator: `--once` / `--briefs-only` /
  `--strategy-only` / `--reconcile-only` / `--schedule`
- `dashboard/market_tab.py` — Streamlit UI: AI Brief panel + ⭐ rating +
  strategy/recommendation panel

API keys live in `.env` (auto-loaded by `python-dotenv`):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`,
`DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`.

Dashboard tab files:
- `dashboard/market_tab.py` — Thị trường: AI Brief + training + recommendations
- `dashboard/analysis_tab.py` — Phân tích cổ phiếu (có FUTURES/INDEX fallback)
