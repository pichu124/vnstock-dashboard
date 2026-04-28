# Project notes for Claude Code

This file holds durable reminders/context for future sessions on this repo.
Items here get auto-loaded into Claude's context at session start.

---

## 📌 Pending suggestions (raise when relevant)

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

### 3. Tách nút Quét tín hiệu + Mở rộng training universe (TODO — tối 2026-04-28)

**Status**: Đã thảo luận, CHƯA implement. Cần làm tối nay.

**Công việc 1 — Tách nút Scan ra riêng (`dashboard/market_tab.py`)**:
- Xoá `emit_recommendations` ra khỏi `_run_training()` (cả Lite lẫn Full)
- Thêm nút riêng **"🔍 Quét tín hiệu toàn thị trường"** gọi:
  ```python
  universe = _scan_universe()
  recs = emit_recommendations(universe, max_recs=5)
  ```
- Hiển thị kết quả: "Đã quét X mã → Y khuyến nghị mới"
- Lý do: train 1 lần/ngày, quét có thể chạy sáng + chiều độc lập

**Công việc 2 — Stratified training universe (`vnstock_train.py`)**:
- Thêm `_VNMID_SAMPLE` — ~15 mã VNMID đại diện (mid-cap, thanh khoản khác VN30):
  ```python
  _VNMID_SAMPLE = ["PNJ","DGC","GMD","NLG","VHC","HSG","DPM","VIX",
                   "KDC","GEX","PHR","TCH","HAH","SCS","VGC"]
  ```
- Cập nhật `_training_universe()`:
  - `lite=True`  → 10 VN30 diverse + 5 VNMID = 15 mã
  - `lite=False` → VN30 đủ 30 + 15 VNMID = ~45 mã
- Thử `symbols_by_group('VNMID')` live trước khi dùng hardcoded
- Lý do: VN30 toàn bluechip/ngân hàng lớn — chiến lược học không khái quát được mid-cap

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
