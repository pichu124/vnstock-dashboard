\# CLAUDE.md — vnstock-dashboard



Nền tảng phân tích chứng khoán VN (Streamlit): screener 9 preset, phân tích

kỹ thuật/cơ bản, tổng quan thị trường, live mode WSS \~1.100 mã, warehouse

Parquet local, AI brief sáng/chiều gửi Telegram.



\## Môi trường \& lệnh chính

\- Windows + venv: `\& "C:\\Users\\Administrator\\.venv\\Scripts\\Activate.ps1"`,

&#x20; thư mục làm việc `C:\\vnstock` (KHÔNG còn đường dẫn Dropbox cũ).

\- `pip install -r requirements.txt`. API keys trong `.env` (VNSTOCK\_API\_KEY,

&#x20; ANTHROPIC/GROQ/CEREBRAS/OPENROUTER, FRED\_API\_KEY) — không bao giờ commit.

\- Orchestrator: `python run.py <sub>` — scan / doctor / sync / validate /

&#x20; audit / test / dashboard / all. Exit code: 0 ok, 1 cảnh báo, 2 fail cứng.

\- Dashboard: `python run.py dashboard` (Streamlit, localhost:8501).

\- Lịch chạy tự động: `scripts/setup\_scheduled\_tasks.ps1` (4 task, đăng ký

&#x20; THEO MÁY — máy mới phải chạy lại script này, Run as Administrator).



\## Test discipline

\- Sửa module lõi nào → `python run.py test --fast` (\~121 test, \~0.7s).

\- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, \~6s).

\- Kết quả ghi `data\_warehouse/\_meta/test\_status.json` → badge sidebar.

&#x20; Badge đỏ = KHÔNG merge/deploy.



\## Bản đồ kiến trúc

\- `vnstock\_dashboard.py` — UI chính; các tab trong `dashboard/` (market,

&#x20; analysis, news+macro, money\_flow, screener, portfolio, allocation,

&#x20; reports, rates\_report).

\- `vnstock\_brief.py` — sinh AI brief morning/close. Chuỗi guard hậu kiểm

&#x20; `apply\_brief\_guards(text, ctx)` DÙNG CHUNG cho cả 2 brief — KHÔNG BAO GIỜ

&#x20; inline lại chuỗi vào `generate\_brief` (điểm parity duy nhất).

\- Pipeline data: `vnstock\_updater` (sync giá) → `vnstock\_rollup` (1m→daily)

&#x20; → `vnstock\_warehouse` (Parquet) → `vnstock\_runner`/`vnstock\_screener`

&#x20; (screener + market\_overview.json) → brief.

\- Vĩ mô: `vnstock\_macro` + nguồn `vnstock\_nso` / `vnstock\_fred` /

&#x20; `vnstock\_vbma` / `vnstock\_sbv\_rates`. Tin tức: `vnstock\_news\_feeds` +

&#x20; `vnstock\_sentiment`. Chiến lược/backtest: `vnstock\_strategy` (AST sandbox),

&#x20; `vnstock\_train`. Bộ nhớ brief: `vnstock\_memory` (SQLite). Gửi:

&#x20; `vnstock\_telegram`.

\- `vnstock\_sectors.py` — nhóm ngành custom ("Họ VIN", "Họ M") dùng chung

&#x20; dashboard + brief; thêm họ mới = thêm 1 dòng registry.



\## Quy ước

\- Output cho người dùng (brief, UI) bằng tiếng Việt; format số kiểu EN

&#x20; (`{:,.2f}` — phẩy nghìn, chấm thập phân).

\- LLM hay phớt chỉ thị prompt → mọi ràng buộc quan trọng chốt bằng guard

&#x20; deterministic trong code + test đi kèm. Thêm guard = thêm vào

&#x20; `apply\_brief\_guards` + viết test.

\- Mọi auto-refresh đều best-effort và có env kill-switch

&#x20; (`VNSTOCK\_BRIEF\_AUTO\_\*`, `VNSTOCK\_MACRO\_\*`).



\## ⚠️ Bất biến — đọc docs/CLAUDE-NOTES.md trước khi đụng

\- Chart 4 panel (Price/Volume/RSI/MACD): CHỈ dùng logical-range API của

&#x20; Lightweight Charts, cấm time-range API; 4 chart phải cùng số bar (bar

&#x20; warmup RSI/MACD emit whitespace, không được skip).

\- Rollup cố tình skip index → brief sáng thấy data hôm nay duy nhất qua

&#x20; `\_augment\_with\_live\_vnindex()`.

\- `Giá 1T %` = đổi 1 TUẦN (5 phiên), không phải 1 phiên — mọi nhãn phải ghi rõ.



\## Nhật ký chi tiết

Toàn bộ lịch sử fix, 30+ guard brief, khảo sát nguồn data, mục chờ verify

(2.9K dòng) nằm ở `docs/CLAUDE-NOTES.md`. Khi làm việc trên brief / macro /

strategy / chart: MỞ FILE ĐÓ tra mục liên quan trước khi sửa. Đừng chép

ngược nội dung dài vào file này — CLAUDE.md giữ dưới \~100 dòng.

