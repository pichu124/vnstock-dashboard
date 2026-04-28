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

### 3. ✅ Tách nút Quét tín hiệu + Dynamic training universe (DONE 2026-04-28)

**Commit**: `8485962`

- Nút "🔍 Quét tín hiệu toàn thị trường" tách biệt khỏi training buttons
- `emit_recommendations()` lọc vol ≥ 100K cổ/ngày (30-day avg)
- `_training_universe()` dynamic: live API → warehouse filter → volume rank
  - Lite: sector-stratified top-10 VN30 + top-7 VNMID = ~17 mã
  - Full: VN30 đủ + top-20 VNMID = ~50 mã
- `_sector_stratified()`: max 3 bank slots, 1 slot/ngành khác — không bao giờ cluster ngân hàng

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
