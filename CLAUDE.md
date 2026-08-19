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
- Lịch chạy tự động: `scripts/setup_scheduled_tasks.ps1` (2 task: Daily
  18:00 ngày làm việc + Weekend — gộp từ 29/07; đăng ký THEO MÁY — máy mới
  phải chạy lại script này, Run as Administrator). Trần task Daily 120 phút:
  sync phình >~75' là task bị chấm dứt TRƯỚC bước brief (bước cuối 14/14).
- ⚠️ MỌI lệnh soi trạng thái (đọc `run_daily.log`, `data_warehouse/_meta/*.json`,
  `Get-ScheduledTaskInfo`) CHỈ chạy được TRÊN DESKTOP chạy pipeline. Log + kho
  đều trong `.gitignore`, kho là local (bỏ Dropbox), task đăng ký theo máy →
  laptop clone repo về KHÔNG có gì để soi. Đừng bảo user chạy trên laptop.

## Test discipline
- Sửa module lõi nào → `python run.py test --fast` (~1.648 test; ~30s trên CI,
  **~64s trên máy thật** vì có kho dữ liệu + mạng).
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, 2.168 test).
- Kết quả ghi `data_warehouse/_meta/test_status.json` → badge sidebar.
  Badge đỏ = KHÔNG merge/deploy.
- `--fast` ì → `python run.py test --fast --slow` (20 test chậm nhất). Đo phải
  làm TRÊN MÁY THẬT: số CI không thấy được I/O đĩa/mạng.
- ~44s của `--fast` là `test_sandbox_isolation` (41 test spawn process). **ĐÃ
  CHỐT GIỮ** (user 13/08) — đừng đề xuất bỏ ra để chạy nhanh hơn.

## Bản đồ kiến trúc
- `vnstock_dashboard.py` — UI chính; các tab trong `dashboard/` (market,
  analysis, news+macro, money_flow, screener, portfolio, allocation,
  reports, rates_report).
- `vnstock_brief.py` — sinh AI brief morning/close (context → prompt → agent).
  Chuỗi `apply_brief_guards(text, ctx)` ở `vnstock_brief_guards.py` DÙNG CHUNG
  cho cả 2 brief — KHÔNG BAO GIỜ inline lại vào `generate_brief` (điểm parity
  duy nhất). 46 guard chia 3 chủ đề: `_guards_sections` (sai chuyện gì) /
  `_guards_numbers` (sai số, sai chiều) / `_guards_text` (lộ ruột, nói nhảm),
  tiện ích chung ở `_guards_common`, hằng số + khối canon mà CẢ prompt lẫn
  guard dựng chung ở `vnstock_brief_canon.py`. Một chiều: brief → guards →
  3 nhóm → common/canon (`tests/test_brief_split.py` canh). Mọi tên vẫn
  re-export qua `vnstock_brief` nên đường import cũ không đổi.
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
  deterministic trong code + test đi kèm. Thêm guard = viết trong
  `vnstock_brief_guards.py` + NỐI VÀO `apply_brief_guards` + viết test (guard
  quên nối = code chết trông y như code sống; có lưới canh).
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
**Hỏi "còn việc gì?" → mở `docs/VIEC-DANG-LAM.md`** (1 trang, việc-của-user vs
việc-của-Claude, có lệnh sẵn). Bản đầy đủ kèm file:line và lý do nằm ở mục
"📌 VIỆC PHẢI LÀM" CUỐI `docs/CLAUDE-NOTES.md` — kho lưu, không phải để làm theo.
Toàn bộ lịch sử fix, 30+ guard brief, khảo sát nguồn data, mục chờ verify
(4.8K dòng) nằm ở `docs/CLAUDE-NOTES.md`. Khi làm việc trên brief / macro /
strategy / chart: MỞ FILE ĐÓ tra mục liên quan trước khi sửa. Đừng chép
ngược nội dung dài vào file này — CLAUDE.md giữ dưới ~100 dòng.