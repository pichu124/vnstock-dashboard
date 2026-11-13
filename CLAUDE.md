# CLAUDE.md — vnstock-dashboard

Nền tảng phân tích chứng khoán VN (Streamlit): screener 14 preset, phân tích
kỹ thuật/cơ bản, tổng quan thị trường, live mode WSS ~1.100 mã, warehouse
Parquet local, AI brief sáng/chiều gửi Telegram.

File này chỉ giữ thứ phải nhớ MỖI PHIÊN. Bản đầy đủ (lý do, số đo, vết sự cố):
**`docs/VAN-HANH.md`** (hai máy, kho, môi trường, test, công tắc env) và
**`docs/KIEN-TRUC.md`** (từng module) — MỞ file tương ứng trước khi đụng việc đó.

> ## 🟦 ĐỌC TRƯỚC — `data_warehouse` ĐỒNG BỘ QUA DROPBOX GIỮA HAI MÁY
>
> Desktop `PICHU` và laptop `CFA-BINHLD-LT` **dùng CHUNG một kho**:
> `C:\vnstock\data_warehouse` là Junction sang `E:\Dropbox\vnstock_data\data_warehouse`.
> **KHO đồng bộ, CODE thì không** — repo đi bằng git; `run_daily.log` ở gốc repo là
> nhân chứng riêng của từng máy. Ghi chú cũ "hai kho độc lập" là SAI (U11).
>
> 1. **Chữa kho làm MỘT LẦN là đủ** — không bao giờ gán ⇄ CẢ HAI cho việc đụng
>    `data_warehouse`; máy kia tự có sau vài phút.
> 2. **Marker + badge cũng đồng bộ** và phần lớn không có trường máy
>    (`pipeline_status` / `brief_push` / `test_status`.json; `doctor_status.json` có
>    `machine`) ⇒ badge có thể là kết quả của MÁY KIA; `run.py telegram close` ở
>    laptop là desktop câm brief tối đó.
> 3. **Đừng đụng kho ở máy kia trong lúc pipeline chạy** — từ lúc task Daily khởi
>    động tới khi `run_daily.log` in `⏱ TỔNG`. Hai bên ghi cùng file ⇒ Dropbox đẻ
>    `(conflicted copy).parquet` ngay trong `prices/`. Marker
>    `_meta/pipeline_running.json` khoá nút 📥/🧩/🚀 trên dashboard.
> 4. **Đừng suy hạ tầng từ timestamp** (file Dropbox tải xuống nhận `CreationTime`
>    LÚC TẢI). Hạ tầng không đọc được từ code thì HỎI.
> 5. **Sync có thể bị TẮT bằng tay và quên bật**: hai máy thấy kho khác nhau mà
>    `prices/` KHÔNG có conflicted copy ⇒ nghi sync tắt TRƯỚC khi nghi code (icon
>    Dropbox ở khay + so `_meta/pipeline_status.json` hai bên). Bên tắt sync giữ
>    bản đúng — đừng chữa lại ở máy kia.
>
> `_meta/backup_rebase/` chỉ ~10 MB — đừng đề xuất dọn.

## Môi trường & lệnh chính
- Windows + venv **vnstock thế hệ 6**: `& "$HOME\.venv_6x\Scripts\Activate.ps1"`; thư mục
  làm việc `C:\vnstock`. Venv cũ `$HOME\.venv` (vnstock 4.x) chỉ để đối chiếu.
- `pip install -r requirements.txt`. API keys trong `.env` — không bao giờ commit.
- Nguồn dữ liệu khai MỘT chỗ: `VNSTOCK_SOURCE` / `VNSTOCK_SOURCE_ROUTES` trong `.env`, áp ở
  `vnstock_auth.configure_sources()`; KHÔNG ghi tên nguồn vào lệnh gọi (xem `AGENTS.md`).
  Mặt tiền `vnstock_auth.get_vnstock(t)`. Không tắt `SchemaChangeWarning`
  (`keep_schema_warnings()` sau mọi `filterwarnings("ignore")`). Updater KHÔNG còn nhánh
  fallback riêng: thứ tự nguồn dự phòng nằm trong `VNSTOCK_SOURCE`; dấu hiệu lỗi là `❌ N lỗi`.
- Orchestrator: `python run.py <sub>` — scan / doctor / sync / validate / audit / test /
  dashboard / all. Exit code: 0 ok, 1 cảnh báo, 2 fail cứng. Dashboard: `python run.py dashboard`.
- Lịch tự động: `scripts/setup_scheduled_tasks.ps1` — 3 task: Daily 18:00 ngày làm việc (trần
  240′), Weekend, News Alert mỗi giờ 24/7. Đăng ký THEO MÁY, Run as Administrator **trong shell
  ĐÃ kích hoạt venv** (script từ chối Python hệ thống).
- ⚠️ HAI MÁY: desktop `PICHU` (Daily + Weekend, sinh brief) · laptop `CFA-BINHLD-LT` (CHỈ News
  Alert từ 11/11; KHÔNG bật VPN công ty — Anthropic chặn 403). **KHÔNG nhận dạng bằng đường dẫn
  hay tên venv**; chỉ tin `$env:COMPUTERNAME` + `Get-ScheduledTask -TaskName 'VnStock *'`
  (≥2 task = desktop).
- ⚠️ **MÁY ĐANG NGỒI LÀ TRẠNG THÁI DÍNH**: user báo đổi máy thì mới đổi; đừng hỏi lại mỗi lượt,
  đừng suy từ venv.
- Cửa `--skip-if-done` và brief chiều so **PHIÊN PHỦ** (`covered_session`), KHÔNG so ngày lịch.
- ⚠️ **MỌI việc/test giao cho user PHẢI ghi rõ máy nào**: 🖥️ DESKTOP · 💻 LAPTOP · ⇄ CẢ HAI
  (việc KHÔNG nằm trong kho: git, pip, venv, task lịch, `.env`) · ○ máy nào cũng được. Soi
  `run_daily.log` / task lịch là 🖥️ DESKTOP. CHỮA KHO là **○ một lần**, không phải ⇄.

## Test discipline
- Sửa module lõi nào → `python run.py test --fast`. Danh sách `--fast` là WHITELIST trong
  `run.py` — thêm file test mới thì phải ghi vào đó, không thì `--fast` không chạy nó.
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ). **Đổi slug/migration ⇒ chạy FULL
  trước khi push** (30/09 mất brief vì test ngoài whitelist, U65). Test đọc env PHẢI xoá biến
  theo TIỀN TỐ — `.env` máy thật lọt vào pytest.
- Kết quả ghi `data_warehouse/_meta/test_status.json` → badge sidebar. Badge đỏ = KHÔNG merge/deploy.
- ~44s của `--fast` là `test_sandbox_isolation` — **ĐÃ CHỐT GIỮ**, đừng đề xuất bỏ.
- Số test và thời gian đo từng đợt: `docs/VAN-HANH.md`.

## Bản đồ kiến trúc (một dòng mỗi khu — chi tiết `docs/KIEN-TRUC.md`)
- **UI**: `vnstock_dashboard.py` + các trang trong `dashboard/` (sổ trang `dashboard/pages.py`).
- **Brief**: `vnstock_brief.py` (context → prompt → agent). Chuỗi `apply_brief_guards(text, ctx)`
  ở `vnstock_brief_guards.py` là điểm parity DUY NHẤT của cả 2 brief — KHÔNG BAO GIỜ inline lại
  vào `generate_brief`. Guard chia `_guards_sections` / `_numbers` / `_text`, chung ở
  `_guards_common`, hằng số ở `vnstock_brief_canon.py`; phụ thuộc MỘT chiều
  (`tests/test_brief_split.py` canh).
- **Engine Claude**: `vnstock_claude_cli.py` (`complete` = `claude -p` 0 công cụ; `complete_mcp`
  cho connector) + `vnstock_brief_pack.py`. Công tắc `VNSTOCK_LLM_ENGINE` /
  `VNSTOCK_<BƯỚC>_ENGINE`; hỏng khâu nào ⇒ rơi về ladder OpenAI-compat (`_OpenAICompatAgent`).
- **Brief 3 khung**: `vnstock_horizons.py` + `vnstock_horizons_state.py` (`_meta/horizon_state.json`).
- **Pipeline data**: `vnstock_updater` → `vnstock_rollup` → `vnstock_warehouse` →
  `vnstock_runner`/`vnstock_screener` → brief. Cửa ở đường ghi: `vnstock_basis_guard` (lệch cơ
  sở >1,2% ⇒ KHÔNG nối, vào sổ cách ly), `vnstock_ohlc_repair`, `vnstock_corp_ratio` (tỉ lệ
  quyền; nhiều sự kiện cùng ngày GDKHQ **cộng dồn trên số cổ phiếu GỐC**, không nhân dây chuyền).
- **Vĩ mô**: `vnstock_macro` + `vnstock_nso` / `_fred` / `_vbma` / `_sbv_rates`. **Tin**:
  `vnstock_news_feeds` + `vnstock_sentiment`; cảnh báo mỗi giờ `vnstock_news_alert.py` (chạy ở
  ĐÚNG MỘT máy). **Chiến lược**: `vnstock_strategy` (AST sandbox), `vnstock_train`. **Bộ nhớ
  brief**: `vnstock_memory` (SQLite). **Gửi**: `vnstock_telegram`.
- **Đa tài sản** `vnstock_assets*` · **phái sinh NN** `vnstock_futures_foreign*` · **connector
  MCP chạy bóng** `vnstock_mcp_enrich.py` · **thước đo kỹ thuật** `vnstock_ta_score*`,
  `vnstock_indicators`.
- **Rổ VN30**: `vnstock_vn30.py` là nguồn sự thật duy nhất (hằng số chép cứng chỉ là lưới cuối;
  `symbols_by_group` trả **pd.Series**, không phải DataFrame). Nhóm ngành: `vnstock_sectors.py`.
- **Live** `vnstock_wss`: tầng nóng/lạnh; công tắc ở SIDEBAR CHUNG, tab chỉ ĐỌC cờ.
- **Model**: `vnstock_model_watch` + `vnstock_model_eval` chỉ ĐỀ XUẤT, không tự áp.
- `scripts/export_bank_balance_sheets.py`: tầm phủ nguồn đã tra hết 26/08 — ĐỪNG DÒ LẠI (U34).

## Quy ước
- Output cho người dùng (brief, UI) bằng tiếng Việt; format số kiểu EN
  (`{:,.2f}` — phẩy nghìn, chấm thập phân).
- Màu/chữ UI: MỘT nguồn `dashboard/theme.py` (`TOKENS`; `.streamlit/config.toml` chép lại, test canh).
  Đừng gõ hex vào file UI — `tests/test_theme_tokens.py` đếm hex từng file, ngân sách chỉ GIẢM. Giá theo
  bảng điện VN (tím trần · xanh tăng · vàng TC · đỏ giảm · xanh lơ sàn); font IBM Plex tự host `static/fonts/`.
  Sáng/tối (P4): `TOKENS` là bảng ĐỘNG theo chế độ của lượt chạy ⇒ đọc `TOKENS[...]` LÚC VẼ, đừng chép ra
  hằng cấp module (đứng yên ở màu tối). Điều hướng = `st.navigation` từ sổ `dashboard/pages.py`; debug/
  traceback chỉ sau `dashboard.ui.diag_on()`. Lộ trình P1→P5: `docs/THIET-KE-GIAO-DIEN.md`.
- LLM hay phớt chỉ thị prompt → mọi ràng buộc quan trọng chốt bằng guard
  deterministic trong code + test đi kèm. Thêm guard = viết trong
  `vnstock_brief_guards.py` + NỐI VÀO `apply_brief_guards` + viết test (guard
  quên nối = code chết trông y như code sống; có lưới canh).
- Mọi auto-refresh đều best-effort và có env kill-switch. Danh sách đầy đủ ở
  `docs/VAN-HANH.md` mục "Công tắc env" — thêm công tắc mới PHẢI ghi vào đó (test canh).
- Nghi ngờ CHƯA đủ căn cứ để vá → **đừng ghi vào notes, hãy ĐẾM**:
  `vnstock_brief_watch` nhặt bằng chứng mỗi phiên vào `_meta/brief_watch.json`,
  badge doctor `brief_watch` chỉ réo khi ≥ `MIN_SAMPLES` phiên. Dưới sàn mẫu
  badge phải **ok kèm n=…**, không bao giờ warn (vết 13/08: n=2 vẽ thành "0%").
  Soi xong mà là SỐ THẬT ⇒ `python vnstock_brief_watch.py --verify <MÃ…>` (sổ riêng
  `_meta/brief_watch_verified.json`, khoá mã + giá trị: số đổi mới réo lại) — ĐỪNG xoá sổ.
- Model LLM: slug MỚI phải probe sống trước khi vào code —
  `python scripts/probe_models.py --slug "Groq=<model>"` trên máy thật
  (catalog trên mạng hay sai/lỗi thời). Provider khai tử model → 1 dòng
  `_MODEL_MIGRATIONS` (vnstock_brief) + thêm slug vào `_DEAD_SLUGS` ở
  `tests/test_model_ladder.py` (test quét slug chết TOÀN repo).
- THÊM ĐIỂM DÙNG MODEL MỚI → phải khai vào CẢ HAI lưới: `_all_live_slugs`
  (test quét slug chết) và `_ladder_slugs` (`vnstock_model_watch`). Lưới chỉ
  soi thứ ĐƯỢC KHAI BÁO — trùng slug với điểm khác là may, không phải bảo vệ.

## Git — máy user làm việc trên `main`
Claude push lên nhánh feature → trên máy user `git pull` báo "Already up to date" dù vừa tải
commit mới. Lấy code mới: `git fetch origin <nhánh> && git merge origin/<nhánh>`. Nghi máy chạy
code cũ → `git log --oneline -1` đối chiếu commit cuối Claude báo.

## ⚠️ Bất biến — đọc docs/CLAUDE-NOTES.md trước khi đụng
- Chart 4 panel (Price/Volume/RSI/MACD): CHỈ dùng logical-range API của
  Lightweight Charts, cấm time-range API; 4 chart phải cùng số bar (bar
  warmup RSI/MACD emit whitespace, không được skip).
- Rollup cố tình skip index → brief sáng thấy data hôm nay duy nhất qua
  `_augment_with_live_vnindex()`.
- `Giá 1T %` = đổi 1 TUẦN (5 phiên), không phải 1 phiên — mọi nhãn phải ghi rõ.
- `GTGD cả ngày` = Σ giá×KLGD của mã CÓ bar phiên đó; mã LỚN (TB ≥ 50 tỷ/phiên)
  thiếu bar ⇒ runner kê `gtgd_missing_heavy`, baseline TB5/TB20 so trên CÙNG tập mã
  (`excl_missing`), prompt + guard ghi "(chưa gồm N mã lớn thiếu data)", doctor
  badge `gtgd_coverage` (#18, 30/09 — 45 mã cách ly 16–29/09 làm brief đọc sai TB).
- Độ tươi `market_overview` so CẢ GIỜ, không chỉ ngày: cùng phiên mà chốt
  trước `SESSION_CLOSE_CUTOFF` (15:05) là GIỮA PHIÊN ⇒ stale, `reason=intraday`.

## Agent skills

Plugin `mattpocock-skills@mattpocock` (GitHub `mattpocock/skills`) khai trong `.claude/settings.json`,
`autoUpdate` theo BẢN PHÁT HÀNH (`plugin.json` ghim version, commit lẻ không tới). Phiên cloud
KHÔNG nạp plugin khai trong repo ⇒ ở cloud đọc SKILL.md từ GitHub rồi làm tay. Engine `claude -p`
của pipeline (tước settings) KHÔNG nạp nó — đo 🖥️ 13/10 bằng `cli_command`: init chỉ 2 plugin builtin, 0 skill.

### Issue tracker

GitHub Issues của `pichu124/vnstock-dashboard` (phiên cloud không có `gh` ⇒ công cụ GitHub
MCP); `docs/VIEC-DANG-LAM.md` vẫn là trang việc của user, skill không ghi vào. Xem
`docs/agents/issue-tracker.md`.

### Triage labels

5 nhãn mặc định: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`,
`wontfix`. Xem `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` ở gốc repo, tạo dần khi cần; quyết định cũ ở
`docs/THIET-KE-*.md` và mục `Uxx` của `docs/CLAUDE-NOTES.md`. Xem `docs/agents/domain.md`.

## Nhật ký chi tiết
**Hỏi "còn việc gì?" → mở `docs/VIEC-DANG-LAM.md`** (việc-của-user vs việc-của-Claude, có lệnh
sẵn). Bản đầy đủ kèm file:line và lý do nằm ở mục "📌 VIỆC PHẢI LÀM" CUỐI
`docs/CLAUDE-NOTES.md` — kho lưu, không phải để làm theo. Toàn bộ lịch sử fix, guard brief,
khảo sát nguồn data, mục chờ verify cũng nằm ở `docs/CLAUDE-NOTES.md`: khi làm việc trên
brief / macro / strategy / chart, MỞ FILE ĐÓ tra mục liên quan trước khi sửa.
Đừng chép ngược nội dung dài vào file này — chi tiết vận hành vào `docs/VAN-HANH.md`, chi tiết
module vào `docs/KIEN-TRUC.md`; CLAUDE.md giữ dưới ~180 dòng.
