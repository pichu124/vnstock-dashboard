# CLAUDE.md — vnstock-dashboard

Nền tảng phân tích chứng khoán VN (Streamlit): screener 9 preset, phân tích
kỹ thuật/cơ bản, tổng quan thị trường, live mode WSS ~1.100 mã, warehouse
Parquet local, AI brief sáng/chiều gửi Telegram.

> ## 🟦 ĐỌC TRƯỚC — `data_warehouse` ĐỒNG BỘ QUA DROPBOX GIỮA HAI MÁY
>
> Desktop `PICHU` và laptop `CFA-BINHLD-LT` **dùng CHUNG một kho**. User xác
> nhận 19/08/2026. Ghi chú cũ "đã bỏ Dropbox, hai kho độc lập" là **SAI** và đã
> làm hỏng nguyên một ngày làm việc — xem `docs/CLAUDE-NOTES.md` mục U11.
>
> **Cơ chế (xác nhận 19/08 bằng `Get-Item`):** `C:\vnstock\data_warehouse` là
> **Junction** trỏ sang `E:\Dropbox\vnstock_data\data_warehouse`. Tức **KHO
> đồng bộ, CODE thì không** — repo `C:\vnstock` đi bằng git, `run_daily.log` ở
> gốc repo nên KHÔNG đồng bộ (nó là nhân chứng riêng của từng máy).
> Hệ quả phụ: MỌI thứ dưới `data_warehouse` đều nằm trong Dropbox, kể cả
> `_meta/backup_rebase/` (đã đo 19/08: 77 thư mục = 10,4 MB — **không đáng
> làm gì**, đừng đề xuất dọn nữa).
>
> **4 hệ quả, thuộc lòng trước khi giao việc cho user:**
> 1. **Chữa kho làm MỘT LẦN là đủ** — đừng bao giờ gán nhãn ⇄ CẢ HAI cho việc
>    đụng `data_warehouse`. Máy kia tự có sau vài phút.
> 2. **Marker + badge cũng đồng bộ.** `pipeline_status.json` /`brief_push.json`/
>    `test_status.json` / `doctor_status.json` đều nằm TRONG kho và **không có
>    trường máy** ⇒ badge sidebar có thể là kết quả của MÁY KIA;
>    `run.py telegram close` chạy ở laptop là desktop câm brief tối đó.
> 3. **Đừng đụng kho ở máy kia trong lúc pipeline chạy** (18:00-19:xx ngày làm
>    việc). Hai bên ghi cùng file ⇒ Dropbox đẻ `... (conflicted copy).parquet`
>    NGAY trong `prices/`. Đường GHI đã xử đủ (`read_year_frames` gộp mọi file ·
>    `_read_year` khử trùng giữ bản mtime mới · `_write_year` dồn về 1 file ·
>    `run.py scan` báo year-dir >1 file) nên không mất data — nhưng vẫn tránh,
>    vì trước lần sync kế tiếp thì các đường ĐỌC khác còn đếm trùng.
> 4. **Đừng suy hạ tầng từ timestamp.** File Dropbox tải xuống nhận
>    `CreationTime` LÚC TẢI còn TÊN do bên gửi đặt — 19/08 tôi đọc dấu hiệu này
>    thành "chép tay" và sai suốt buổi. Hạ tầng không đọc được từ code thì HỎI.

## Môi trường & lệnh chính
- Windows + venv: `& "C:\Users\Administrator\.venv\Scripts\Activate.ps1"`,
  thư mục làm việc `C:\vnstock` (đường dẫn Dropbox CŨ không còn dùng, nhưng
  Dropbox VẪN đồng bộ thư mục này giữa hai máy — xem cảnh báo bên dưới).
- `pip install -r requirements.txt`. API keys trong `.env` (VNSTOCK_API_KEY,
  ANTHROPIC/GROQ/CEREBRAS/OPENROUTER, FRED_API_KEY) — không bao giờ commit.
- Orchestrator: `python run.py <sub>` — scan / doctor / sync / validate /
  audit / test / dashboard / all. Exit code: 0 ok, 1 cảnh báo, 2 fail cứng.
- Dashboard: `python run.py dashboard` (Streamlit, localhost:8501).
- Lịch chạy tự động: `scripts/setup_scheduled_tasks.ps1` (2 task: Daily
  18:00 ngày làm việc + Weekend — gộp từ 29/07; đăng ký THEO MÁY — máy mới
  phải chạy lại script này, Run as Administrator). Trần task Daily 120 phút:
  sync phình >~75' là task bị chấm dứt TRƯỚC bước brief (bước cuối 14/14).
- ⚠️ HAI MÁY: desktop `PICHU` (2 task lịch, sinh brief) · laptop
  `CFA-BINHLD-LT` (không task). **KHÔNG nhận dạng bằng đường dẫn hay tên venv**
  — cả hai đều `C:\vnstock`, và venv đổi theo TÀI KHOẢN đăng nhập chứ không
  theo máy (desktop in `\admin\`, phát trước in `\Administrator\`). Dấu hiệu
  duy nhất đáng tin: `$env:COMPUTERNAME` + `Get-ScheduledTask -TaskName
  'VnStock *'` (2 task = desktop). Đã quy sai máy 3 lần ngày 19/08.
- Cửa `--skip-if-done` cố ý bỏ qua cross-machine (đúng cho kho dùng chung —
  xem banner đầu file); kho tách riêng thì bật `VNSTOCK_INDEPENDENT_WAREHOUSE=1`.
- ⚠️ **MỌI việc/test giao cho user PHẢI ghi rõ máy nào**, theo 4 nhãn dùng trong
  `docs/VIEC-DANG-LAM.md`: 🖥️ DESKTOP · 💻 LAPTOP · ⇄ CẢ HAI (phải làm lặp lại
  ở từng máy khi việc đó KHÔNG nằm trong kho — kho thì Dropbox lo) · ○ máy nào
  cũng được. Lệnh soi trạng
  thái (`run_daily.log`, `_meta/*.json`, `Get-ScheduledTaskInfo`) là 🖥️ DESKTOP
  — log và task đăng ký theo máy (kho thì Dropbox lo). Việc CHỮA KHO là **○ một
  lần**, KHÔNG phải ⇄ CẢ HAI (sửa 19/08).

## Test discipline
- Sửa module lõi nào → `python run.py test --fast` (~1.951 test; ~40s trên CI).
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, 2.442 test).
  Đo trên MÁY THẬT 19/08 (sau đợt vá): **2.181 passed / 100,3s** — khớp CI từng test một
  (CI ~36s; máy thật chậm hơn ~3× vì có kho dữ liệu, không phải vì bỏ test).
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
  duy nhất). 47 guard chia 3 chủ đề: `_guards_sections` (sai chuyện gì) /
  `_guards_numbers` (sai số, sai chiều) / `_guards_text` (lộ ruột, nói nhảm),
  tiện ích chung ở `_guards_common`, hằng số + khối canon mà CẢ prompt lẫn
  guard dựng chung ở `vnstock_brief_canon.py`. Một chiều: brief → guards →
  3 nhóm → common/canon (`tests/test_brief_split.py` canh). Mọi tên vẫn
  re-export qua `vnstock_brief` nên đường import cũ không đổi.
- `vnstock_corp_ratio` — đọc TỈ LỆ QUYỀN từ tiêu đề sự kiện (hàm thuần).
  `tỷ lệ A:B` = A cũ nhận thêm B mới; nhiều sự kiện CÙNG ngày GDKHQ thì **cộng
  dồn trên số cổ phiếu GỐC**, KHÔNG nhân dây chuyền (PET 19/08: 1.45 khớp số đo
  từ giá 1.4499×, còn nhân dây chuyền ra 1.47 — lệch 1,4%). Cổ tức TIỀN MẶT trừ
  theo SỐ TUYỆT ĐỐI, "tỷ lệ 10%" là 10% MỆNH GIÁ. `P_adj = (P − D)/(1 + r)`.
  Không đọc trọn bộ sự kiện ⇒ trả None, chỗ gọi cảnh báo không kèm số.
- `vnstock_ohlc_repair` — nới `low`/`high` cho bar TỰ MÂU THUẪN ngay ở đường
  ghi (19/08). `low := min(low, open, close)`, `high := max(high, open, close)`
  — giá mới là open/close ĐÃ khớp nên không bịa số. Nới > `MAX_WIDEN_PCT`
  (20%, trên cả biên độ ±15% của UPCoM) ⇒ bar HỎNG, không sửa, để hợp đồng
  cách ly như cũ. Ghi vết `_meta/ohlc_repairs.json` + badge doctor.
- `vnstock_basis_guard` — cửa gác LỆCH CƠ SỞ ở đường ghi chính (V1, 19/08 sau
  ca 70/159 mã). `update_ticker` nới fetch lùi 30 ngày CHỈ để đối chiếu (cắt
  lại trước khi merge); trung vị kho/nguồn lệch >1,2% ⇒ **KHÔNG nối**, ghi mã
  vào `_meta/basis_drift_pending.json` + badge doctor. Bar `last_date` loại
  khỏi phép so (có thể dở dang). Ngưỡng phải KHỚP
  `probe_price_basis.SAME_BASIS_TOL` (có test canh).
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
- `vnstock_vn30.py` — **rổ VN30 hiện hành, một nguồn sự thật duy nhất**. HOSE
  xét lại rổ 2 lần/năm (đầu tháng 2 và đầu tháng 8) ⇒ danh sách chép cứng ở
  `vnstock_brief_canon.VN30_TICKERS` / `vnstock_wss.VN30_SYMBOLS` /
  `vnstock_news._VN30_FALLBACK` chỉ còn là **lưới cuối**, KHÔNG phải nguồn.
  Thứ tự: API sống → cache `_meta/vn30_members.json` (7 ngày, đi qua Dropbox
  nên fetch 1 lần phục vụ cả 2 máy) → hằng số. ⚠️ `symbols_by_group` trả
  **pd.Series** chứ không phải DataFrame — dò `.columns` là ném im lặng
  (`extract_symbols` nhận mọi dạng). Chẩn đoán: `python vnstock_vn30.py --diag`.
  `validate()` từ chối rổ dưới 25 mã (API dở dang làm rổ TEO âm thầm còn tệ
  hơn rổ cũ). Badge doctor `vn30_basket` réo khi rổ thật lệch hằng số. Kỳ
  08/2026 (đo 20/08): VÀO BSR·LPB·MCH·TCX·VPL — RỜI BCM·BVH·PLX·POW·TPB.
- Động cơ live (`vnstock_wss`) chia **tầng nóng/lạnh**: VN30 + index + futures
  quét MỖI vòng, ~1.100 mã còn lại mỗi `COLD_EVERY_N` (5) vòng — heatmap bám
  tick mà vẫn giữ Live Scan toàn thị trường. `split_hot_cold` là hàm thuần và
  KHÔNG BAO GIỜ trả vòng quét rỗng. Nhịp thật đọc ở `get_status()["cycle_s"]`
  và caption sidebar, đừng đoán.

## Quy ước
- Output cho người dùng (brief, UI) bằng tiếng Việt; format số kiểu EN
  (`{:,.2f}` — phẩy nghìn, chấm thập phân).
- LLM hay phớt chỉ thị prompt → mọi ràng buộc quan trọng chốt bằng guard
  deterministic trong code + test đi kèm. Thêm guard = viết trong
  `vnstock_brief_guards.py` + NỐI VÀO `apply_brief_guards` + viết test (guard
  quên nối = code chết trông y như code sống; có lưới canh).
- Mọi auto-refresh đều best-effort và có env kill-switch
  (`VNSTOCK_BRIEF_AUTO_*`, `VNSTOCK_MACRO_*`, `VNSTOCK_BASIS_GUARD`,
  `VNSTOCK_OHLC_REPAIR`, `VNSTOCK_AUTOHEAL_BUDGET_S`, `VNSTOCK_VN30_DYNAMIC`,
  `VNSTOCK_WSS_HOT_TIER`).
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
- Độ tươi `market_overview` so CẢ GIỜ, không chỉ ngày: cùng phiên mà chốt
  trước `SESSION_CLOSE_CUTOFF` (15:05) là GIỮA PHIÊN ⇒ stale, `reason=intraday`.

## Nhật ký chi tiết
**Hỏi "còn việc gì?" → mở `docs/VIEC-DANG-LAM.md`** (1 trang, việc-của-user vs
việc-của-Claude, có lệnh sẵn). Bản đầy đủ kèm file:line và lý do nằm ở mục
"📌 VIỆC PHẢI LÀM" CUỐI `docs/CLAUDE-NOTES.md` — kho lưu, không phải để làm theo.
Toàn bộ lịch sử fix, 30+ guard brief, khảo sát nguồn data, mục chờ verify
(4.8K dòng) nằm ở `docs/CLAUDE-NOTES.md`. Khi làm việc trên brief / macro /
strategy / chart: MỞ FILE ĐÓ tra mục liên quan trước khi sửa. Đừng chép
ngược nội dung dài vào file này — CLAUDE.md giữ dưới ~100 dòng.