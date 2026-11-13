# Vận hành — hai máy, kho Dropbox, môi trường, test, công tắc env

> Bản ĐẦY ĐỦ của các luật vận hành, tách nguyên văn khỏi `CLAUDE.md` ngày 13/11/2026.
> `CLAUDE.md` chỉ giữ bản tóm tắt phải nhớ MỖI PHIÊN; lý do, số đo và vết sự cố nằm ở đây.
> Sửa một luật vận hành ⇒ sửa ở đây VÀ dòng tóm tắt tương ứng trong `CLAUDE.md`.
> Kiến trúc từng module: `docs/KIEN-TRUC.md`.

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
>    Badge doctor **"Phát tối — đã tới kho này chưa"** (16/09) đọc đúng hai
>    marker này (sync `covered_session` + brief `close`/`skipped`) ⇒ nói về
>    BẢN KHO của máy VỪA chạy doctor; ⚠️ "CHƯA tới kho này" = pipeline không
>    chạy HOẶC sync tắt — kiểm icon Dropbox TRƯỚC khi nghi code (hệ quả #5).
>    `doctor_status.json` nay có trường `machine`.
> 3. **Đừng đụng kho ở máy kia trong lúc pipeline chạy** — từ lúc task Daily
>    khởi động (18:00 ngày làm việc; máy tắt lúc đó thì `StartWhenAvailable`
>    chạy bù NGAY KHI BẬT MÁY, phát 08–14/09 đều khởi động ~20:15–20:40 và
>    xong ~21:00–23:15) tới khi `run_daily.log` in `⏱ TỔNG`. Hai bên ghi cùng
>    file ⇒ Dropbox đẻ `... (conflicted copy).parquet` NGAY trong `prices/`. Đường GHI đã xử đủ (`read_year_frames` gộp mọi file ·
>    `_read_year` khử trùng giữ bản mtime mới · `_write_year` dồn về 1 file ·
>    `run.py scan` báo year-dir >1 file) nên không mất data — nhưng vẫn tránh,
>    vì trước lần sync kế tiếp thì các đường ĐỌC khác còn đếm trùng.
>    Marker (17/10): `run.py all|sync` + nút 📥 ghi `_meta/pipeline_running.json`
>    {machine, pid, started_at, command}, xoá ở `finally`; marker tươi (< 5h) ⇒ dashboard
>    khoá 📥/🧩/🚀, ô "Vẫn chạy" để bỏ chặn. Task Daily KHÔNG đọc marker (chỉ ghi).
> 4. **Đừng suy hạ tầng từ timestamp.** File Dropbox tải xuống nhận
>    `CreationTime` LÚC TẢI còn TÊN do bên gửi đặt — 19/08 tôi đọc dấu hiệu này
>    thành "chép tay" và sai suốt buổi. Hạ tầng không đọc được từ code thì HỎI.
> 5. **Sync có thể bị TẮT bằng tay và quên bật** (desktop 07/09→10/09, U56):
>    hai máy thấy kho khác nhau mà `prices/` KHÔNG có conflicted copy ⇒ nghi
>    sync tắt TRƯỚC khi nghi code. Kiểm rẻ nhất: icon Dropbox ở khay + so
>    `_meta/pipeline_status.json` hai bên. Bên đang tắt sync là bên giữ bản đúng
>    của mọi thứ nó đã ghi — đừng chữa lại ở máy kia.

## Môi trường & lệnh chính
- Windows + venv **vnstock thế hệ 6**: `& "$HOME\.venv_6x\Scripts\Activate.ps1"` (từ 11/2026; venv cũ
  `$HOME\.venv` = dòng cũ vnstock 4.x/vnstock_data, ngừng xác thực 10/11/2026 — chỉ để đối chiếu),
  thư mục làm việc `C:\vnstock` (đường dẫn Dropbox CŨ không còn dùng, nhưng
  Dropbox VẪN đồng bộ thư mục này giữa hai máy — xem cảnh báo bên dưới).
- `pip install -r requirements.txt`. API keys trong `.env` (VNSTOCK_API_KEY,
  ANTHROPIC/GROQ/CEREBRAS/OPENROUTER, FRED_API_KEY) — không bao giờ commit.
- **vnstock thế hệ 6** (`AGENTS.md` khối vnstock-guide): nguồn dữ liệu khai MỘT chỗ — `VNSTOCK_SOURCE` /
  `VNSTOCK_SOURCE_ROUTES` trong `.env`, áp ở `vnstock_auth.configure_sources()`; KHÔNG ghi tên nguồn vào lệnh gọi.
  Khoá nguồn: user tự `vnstock keys set <nguồn>`; tài khoản: `vnstock status`/`vnstock login`. Mặt tiền
  `vnstock_auth.get_vnstock(t)` giữ cách gọi cũ trên `Market/Reference/Fundamental`. Không tắt `SchemaChangeWarning`
  (`keep_schema_warnings()` sau mọi `filterwarnings("ignore")`). Hồ sơ cột `v5`.
- Orchestrator: `python run.py <sub>` — scan / doctor / sync / validate /
  audit / test / dashboard / all. Exit code: 0 ok, 1 cảnh báo, 2 fail cứng.
- Dashboard: `python run.py dashboard` (Streamlit, localhost:8501).
- Lịch chạy tự động: `scripts/setup_scheduled_tasks.ps1` (3 task: Daily
  18:00 ngày làm việc + Weekend — gộp từ 29/07 + News Alert mỗi giờ
  24/7 kể cả CN (02/10, #31; 24/7 từ 04/10); đăng ký THEO MÁY — máy mới
  phải chạy lại script này, Run as Administrator **trong shell ĐÃ kích hoạt
  venv hoặc kèm `-PythonExe <venv>\Scripts\python.exe`** — 30/09 cửa sổ Admin
  trần đã đăng ký `C:\Python314` không thư viện; script nay từ chối Python hệ
  thống trừ `-AllowSystemPython`). Trần task Daily **240
  phút** trong script từ 29/09 (180 giết phát 21/09 GIỮA bước brief: sync 99′ +
  screener 23′ + news 17′ + train 12′ ⇒ brief bắt đầu ở phút 168; máy còn đăng
  ký 180 tới khi chạy lại script). Bước brief đêm VCI ốm từng mất 23–42′ vì
  auto-refresh sự kiện GDKHQ gõ VCI 52 mã × timeout 30s (22/09) — nay
  `refresh_upcoming` dừng sau 3 mã lỗi liền, giữ cache (#21); **30/09 đo lại:
  3 mã = 18 timeout = 10′ vì thư viện tự thử lại ~6 lần/mã** ⇒ thêm ngân sách
  tường 120s (`VNSTOCK_EVENTS_REFRESH_BUDGET_S`) + backoff 90′ qua marker
  `_meta/upcoming_events.backoff.json` (`VNSTOCK_EVENTS_BACKOFF_MIN`; chạy tay
  `vnstock_events.py --refresh` không xét); log in
  `[brief] ⏱ <agent>: Ns` từng agent + `ctx+prompt`.
  Updater thế hệ 6 (11/11): KHÔNG còn nhánh fallback KBS — thứ tự nguồn dự phòng nằm
  trong `VNSTOCK_SOURCE` (`.env`), thư viện tự thử theo thứ tự. Dấu hiệu lỗi: `❌ N lỗi`
  trong log. Marker `pipeline_status` updater chỉ ghi khi lỗi = 0 — đừng đọc thành
  "updater không chạy".
- ⚠️ HAI MÁY: desktop `PICHU` (task Daily + Weekend, sinh brief; task News Alert ĐÃ TẮT 11/11) · laptop
  `CFA-BINHLD-LT` (CHỈ task News Alert từ 11/11 — `-OnlyNewsAlert`; Claude CLI qua
  `CLAUDE_CODE_OAUTH_TOKEN` trong `.env`; KHÔNG được bật VPN công ty — Anthropic chặn 403). **KHÔNG nhận dạng bằng đường dẫn hay tên venv**
  — cả hai đều `C:\vnstock`, và venv đổi theo TÀI KHOẢN đăng nhập chứ không
  theo máy (desktop in `\admin\`, phát trước in `\Administrator\`). Dấu hiệu
  duy nhất đáng tin: `$env:COMPUTERNAME` + `Get-ScheduledTask -TaskName
  'VnStock *'` (≥2 task = desktop). Đã quy sai máy 3 lần ngày 19/08.
- ⚠️ **MÁY ĐANG NGỒI LÀ TRẠNG THÁI DÍNH** (user chốt 20/08): user báo đổi máy
  thì mới đổi, KHÔNG báo thì **giữ nguyên máy của lượt trước**. Đừng hỏi lại
  mỗi lượt và đừng suy từ venv — hỏi lại khi user đã nói rồi cũng là một kiểu
  quy sai máy.
- Cửa `--skip-if-done` so **PHIÊN PHỦ** (`covered_session`: chạy trước 15:05
  = phiên trước, T7/CN = thứ 6), KHÔNG so ngày lịch (16/09: chạy bù sáng từng
  làm task 18:00 cùng ngày bỏ sync, bar hôm đó chờ tới mai); T7/CN `run.py
  sync` tự thêm `--force` cho updater (không thì chạy bù T7 đẩy brief T6 trên
  bar T5). **Brief chiều cũng so PHIÊN PHỦ** (29/09): lượt pipeline khởi động
  trong ngày phiên mà tràn qua nửa đêm vẫn đẩy (28/09: sync 121′ → brief lúc
  00:13 bị chặn nhầm thành `brief 0s`); chạy bù sáng vẫn chặn. Cửa cố ý bỏ qua cross-machine (đúng cho kho dùng chung — xem banner
  đầu file); kho tách riêng thì bật `VNSTOCK_INDEPENDENT_WAREHOUSE=1`.
- ⚠️ **MỌI việc/test giao cho user PHẢI ghi rõ máy nào**, theo 4 nhãn dùng trong
  `docs/VIEC-DANG-LAM.md`: 🖥️ DESKTOP · 💻 LAPTOP · ⇄ CẢ HAI (phải làm lặp lại
  ở từng máy khi việc đó KHÔNG nằm trong kho — kho thì Dropbox lo) · ○ máy nào
  cũng được. Lệnh soi trạng
  thái (`run_daily.log`, `_meta/*.json`, `Get-ScheduledTaskInfo`) là 🖥️ DESKTOP
  — log và task đăng ký theo máy (kho thì Dropbox lo). Việc CHỮA KHO là **○ một
  lần**, KHÔNG phải ⇄ CẢ HAI (sửa 19/08).

## Test discipline
- Sửa module lõi nào → `python run.py test --fast` (~2.773 test; ~45s trên CI,
  86s máy thật 15/09 tối). Danh sách file `--fast` là WHITELIST trong `run.py` —
  thêm file test mới thì phải ghi vào đó, không thì `--fast` không chạy nó.
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, ~3.655 test — 🖥️ desktop 05/10 3.592 passed / 156–242s; test đọc env PHẢI xoá biến theo TIỀN TỐ — `.env` máy thật lọt vào pytest, 05/10 suýt mất brief). **Đổi slug/migration ⇒ chạy FULL trước khi push**: 30/09 test ghim slug NGOÀI whitelist còn qwen chết ⇒ phát dừng ở bước test, MẤT brief (U65).
  Đo trên MÁY THẬT (💻 laptop) 09/09: **3.158 passed / 161,8s** tại `c969d6a` — khớp
  CI từng test một (máy thật chậm hơn ~3× vì có kho dữ liệu, không phải vì bỏ test).
- Kết quả ghi `data_warehouse/_meta/test_status.json` → badge sidebar.
  Badge đỏ = KHÔNG merge/deploy.
- `--fast` ì → `python run.py test --fast --slow` (20 test chậm nhất). Đo phải
  làm TRÊN MÁY THẬT: số CI không thấy được I/O đĩa/mạng.
- ~44s của `--fast` là `test_sandbox_isolation` (41 test spawn process). **ĐÃ
  CHỐT GIỮ** (user 13/08) — đừng đề xuất bỏ ra để chạy nhanh hơn.

## Git — máy user làm việc trên `main`
Claude push lên nhánh feature → trên máy user `git pull` báo "Already up to
date" DÙ vừa tải commit mới về (git chỉ merge nhánh đang theo dõi). Lấy code
mới phải dùng `git fetch origin <nhánh> && git merge origin/<nhánh>`. Nghi máy
chạy code cũ → `git log --oneline -1` đối chiếu commit cuối Claude báo.

## Công tắc env (kill-switch)

Mỗi công tắc MỚI phải được ghi vào danh sách này. KHÔNG có lưới chung: `tests/test_indicators_shared.py`
chỉ ghim tên 2 công tắc (`VNSTOCK_BRIEF_SECTOR_ALPHA`, `VNSTOCK_INDICATOR_LEGACY`); các công tắc khác phải tự nhớ ghi.

- Mọi auto-refresh đều best-effort và có env kill-switch
  (`VNSTOCK_BRIEF_AUTO_*`, `VNSTOCK_MACRO_*`, `VNSTOCK_BASIS_GUARD`,
  `VNSTOCK_OHLC_REPAIR`, `VNSTOCK_AUTOHEAL_BUDGET_S`, `VNSTOCK_VN30_DYNAMIC`,
  `VNSTOCK_WSS_HOT_TIER`, `VNSTOCK_BRIEF_WATCH`, `VNSTOCK_NEWS_ALERT[_REVIEW]`,
  `VNSTOCK_FIXUNITS_FOOTER_PRUNE`, `VNSTOCK_NETBS_WORKERS`, `VNSTOCK_NN_RATE_WAIT_BUDGET_S` (trần giây CHỜ hạn mức của NN ròng trong runner, mặc định 300, `0` không chờ), `VNSTOCK_NN_SCREENER_CACHE` (`0` tắt đệm NN ròng theo ngày `_meta/nn_screener/` — một lượt screener ≈50s), `VNSTOCK_HORIZONS_STEP`, `VNSTOCK_HORIZONS` (brief 3 khung, mặc định BẬT từ 14/10; test ghim `0` làm nền), `VNSTOCK_HORIZON_MACRO`, `VNSTOCK_REGIME_NN_SAME_SESSION`, `VNSTOCK_ALLOC_HORIZON_CAP`, `VNSTOCK_ALLOC_ONE_STEP`, `VNSTOCK_REC_GDKHQ_HOLD`, `VNSTOCK_BRIEF_RISK_TODAY`, `VNSTOCK_BRIEF_SECTOR_ALPHA` (alpha ngành vs VN-Index, mặc định TẮT), `VNSTOCK_INDICATOR_LEGACY` (`1` ⇒ RSI Cutler + EMA200 cũ ở screener/độ rộng/chart; mặc định Wilder + SMA200), `VNSTOCK_BRIEF_FUND_PERIODS`, `VNSTOCK_MCP_ENRICH`, `VNSTOCK_ASSETS[_HOURLY|_MCP|_DEMOTE|_LINKS|_ALERTS]`, `VNSTOCK_BRIEF_ASSETS`, `VNSTOCK_FUTURES_FOREIGN`, `VNSTOCK_BRIEF_FUTURES_FOREIGN`, `VNSTOCK_PIPELINE_MARKER`, `VNSTOCK_KEEP_AWAKE` (`all`/`sync`/`weekend` chặn Windows ngủ do rảnh trong lúc chạy — 05/11 desktop ngủ 18:19→20:58 giữa task Daily, mất brief), `VNSTOCK_SCREENER_STALE_SESSIONS` (screener EOD + Live Scan bỏ mã có bar cuối trễ > N phiên, mặc định 5, `0` tắt), `VNSTOCK_DELISTED_MIN_DAYS` (updater: nguồn báo mã không tồn tại + bar cuối cũ hơn N ngày ⇒ "ngừng giao dịch", không tính lỗi; mặc định 30, `0` = lỗi như cũ), `VNSTOCK_BREADTH_UNIVERSE` (`investable` ⇒ % trên MA200 chỉ tính mã ≥200 phiên + GTGD TB20 ≥1 tỷ + không trễ; mặc định `all`; bật thì ⇄ CẢ HAI máy — `.env` theo máy mà market_overview/horizon_state đi chung Dropbox), `VNSTOCK_BREADTH_DISPLAY` (`investable` ⇒ brief + dashboard IN số tập thanh khoản kèm toàn thị trường; quyết định vẫn `above_ma200_pct`; mặc định `all`), `VNSTOCK_TA_CARD` (thẻ kỹ thuật + guard chữ kỹ thuật trong brief, mặc định TẮT; BẬT ở `.env` 🖥️ desktop từ 05/11 sau replay 20 phiên), `VNSTOCK_LLM_ENGINE`
  + `VNSTOCK_<BƯỚC>_ENGINE` + `VNSTOCK_CLAUDE_CLI_{EXE,MODEL,FALLBACK_MODEL,
  TIMEOUT_S,API_KEY,REPO_CONTEXT}`, `VNSTOCK_CLAUDE_MCP_SETTING_SOURCES` (`--setting-sources` của lượt connector MCP, mặc định `user` từ 13/11 — bản CLI mới với "" thấy 0 connector, `user` gọi được SSI/Finhay ~$0,23/lượt; `empty` = "" cũ · `none` = bỏ cờ; đo bằng `scripts/probe_mcp.py`), `VNSTOCK_LLM_BREAKER`
  — cầu dao tài khoản LLM: provider 401/402/403 hôm nay + chưa call nào OK ⇒
  mọi điểm gọi bỏ nấc đó trong ngày; 429/5xx KHÔNG chặn).
