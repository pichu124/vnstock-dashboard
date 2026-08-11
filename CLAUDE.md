# CLAUDE.md — vnstock-dashboard

Nền tảng phân tích chứng khoán VN (Streamlit): screener 9 preset, phân tích
kỹ thuật/cơ bản, tổng quan thị trường, live mode WSS ~1.100 mã, warehouse
Parquet local, AI brief sáng/chiều gửi Telegram.

## Môi trường & lệnh chính
- Windows + venv: `& "C:\Users\Administrator\.venv\Scripts\Activate.ps1"`,
  thư mục làm việc `C:\vnstock` (KHÔNG còn đường dẫn Dropbox cũ).
- `pip install -r requirements.txt`. API keys trong `.env` (VNSTOCK_API_KEY,
  ANTHROPIC/GROQ/CEREBRAS/OPENROUTER, FRED_API_KEY) — không bao giờ commit.
- Orchestrator: `python run.py <sub>` — scan / doctor / sync / validate /
  audit / test / dashboard / all. Exit code: 0 ok, 1 cảnh báo, 2 fail cứng.
- Dashboard: `python run.py dashboard` (Streamlit, localhost:8501).
- Lịch chạy tự động: `scripts/setup_scheduled_tasks.ps1` (4 task, đăng ký
  THEO MÁY — máy mới phải chạy lại script này, Run as Administrator).

## Test discipline
- Sửa module lõi nào → `python run.py test --fast` (~1.034 test, ~26s).
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, ~1.561
  test, ~31s).
- Kết quả ghi `data_warehouse/_meta/test_status.json` → badge sidebar.
  Badge đỏ = KHÔNG merge/deploy.

## Bản đồ kiến trúc
- `vnstock_dashboard.py` — UI chính; các tab trong `dashboard/` (market,
  analysis, news+macro, money_flow, screener, portfolio, allocation,
  reports, rates_report).
- `vnstock_brief.py` — sinh AI brief morning/close. Chuỗi guard hậu kiểm
  `apply_brief_guards(text, ctx)` DÙNG CHUNG cho cả 2 brief — KHÔNG BAO GIỜ
  inline lại chuỗi vào `generate_brief` (điểm parity duy nhất).
- Pipeline data: `vnstock_updater` (sync giá) → `vnstock_rollup` (1m→daily)
  → `vnstock_warehouse` (Parquet) → `vnstock_runner`/`vnstock_screener`
  (screener + market_overview.json) → brief.
- Vĩ mô: `vnstock_macro` + nguồn `vnstock_nso` / `vnstock_fred` /
  `vnstock_vbma` / `vnstock_sbv_rates`. Tin tức: `vnstock_news_feeds` +
  `vnstock_sentiment`. Chiến lược/backtest: `vnstock_strategy` (AST sandbox),
  `vnstock_train`. Bộ nhớ brief: `vnstock_memory` (SQLite). Gửi:
  `vnstock_telegram`.
- Theo dõi model: `vnstock_model_watch` (probe ladder + diff danh mục
  provider, chạy trong `run.py weekend` T7) + `vnstock_model_eval` (bộ đề
  chuẩn chấm điểm THEO VIỆC + đề xuất thay model). Chỉ ĐỀ XUẤT, không tự áp.
- `vnstock_sectors.py` — nhóm ngành custom ("Họ VIN", "Họ M") dùng chung
  dashboard + brief; thêm họ mới = thêm 1 dòng registry.

## Quy ước
- Output cho người dùng (brief, UI) bằng tiếng Việt; format số kiểu EN
  (`{:,.2f}` — phẩy nghìn, chấm thập phân).
- LLM hay phớt chỉ thị prompt → mọi ràng buộc quan trọng chốt bằng guard
  deterministic trong code + test đi kèm. Thêm guard = thêm vào
  `apply_brief_guards` + viết test.
- Mọi auto-refresh đều best-effort và có env kill-switch
  (`VNSTOCK_BRIEF_AUTO_*`, `VNSTOCK_MACRO_*`).
- Model LLM: slug MỚI phải probe sống trước khi vào code —
  `python scripts/probe_models.py --slug "Groq=<model>"` trên máy thật
  (catalog trên mạng hay sai/lỗi thời). Provider khai tử model → 1 dòng
  `_MODEL_MIGRATIONS` (vnstock_brief) + thêm slug vào `_DEAD_SLUGS` ở
  `tests/test_model_ladder.py` (test quét slug chết TOÀN repo).
- THÊM ĐIỂM DÙNG MODEL MỚI → phải khai vào CẢ HAI lưới: `_all_live_slugs`
  (test quét slug chết) và `_ladder_slugs` (`vnstock_model_watch`). Lưới chỉ
  soi thứ ĐƯỢC KHAI BÁO — trùng slug với điểm khác là may, không phải bảo vệ.

## Git — máy user làm việc trên `main`
Claude push lên nhánh feature → trên máy user `git pull` báo "Already up to
date" DÙ vừa tải commit mới về (git chỉ merge nhánh đang theo dõi). Lấy code
mới phải dùng `git fetch origin <nhánh> && git merge origin/<nhánh>`. Nghi máy
chạy code cũ → `git log --oneline -1` đối chiếu commit cuối Claude báo.

## ⚠️ Bất biến — đọc docs/CLAUDE-NOTES.md trước khi đụng
- Chart 4 panel (Price/Volume/RSI/MACD): CHỈ dùng logical-range API của
  Lightweight Charts, cấm time-range API; 4 chart phải cùng số bar (bar
  warmup RSI/MACD emit whitespace, không được skip).
- Rollup cố tình skip index → brief sáng thấy data hôm nay duy nhất qua
  `_augment_with_live_vnindex()`.
- `Giá 1T %` = đổi 1 TUẦN (5 phiên), không phải 1 phiên — mọi nhãn phải ghi rõ.

## Nhật ký chi tiết
Việc còn phải làm/test: mục **"📌 VIỆC PHẢI LÀM — chốt 11/08/2026"** ở CUỐI
`docs/CLAUDE-NOTES.md` (đọc mục này trước khi hỏi "còn việc gì").
Toàn bộ lịch sử fix, 30+ guard brief, khảo sát nguồn data, mục chờ verify
(4.8K dòng) nằm ở `docs/CLAUDE-NOTES.md`. Khi làm việc trên brief / macro /
strategy / chart: MỞ FILE ĐÓ tra mục liên quan trước khi sửa. Đừng chép
ngược nội dung dài vào file này — CLAUDE.md giữ dưới ~100 dòng.