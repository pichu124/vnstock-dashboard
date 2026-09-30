# CLAUDE.md — vnstock-dashboard

Nền tảng phân tích chứng khoán VN (Streamlit): screener 14 preset, phân tích
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
> 4. **Đừng suy hạ tầng từ timestamp.** File Dropbox tải xuống nhận
>    `CreationTime` LÚC TẢI còn TÊN do bên gửi đặt — 19/08 tôi đọc dấu hiệu này
>    thành "chép tay" và sai suốt buổi. Hạ tầng không đọc được từ code thì HỎI.
> 5. **Sync có thể bị TẮT bằng tay và quên bật** (desktop 07/09→10/09, U56):
>    hai máy thấy kho khác nhau mà `prices/` KHÔNG có conflicted copy ⇒ nghi
>    sync tắt TRƯỚC khi nghi code. Kiểm rẻ nhất: icon Dropbox ở khay + so
>    `_meta/pipeline_status.json` hai bên. Bên đang tắt sync là bên giữ bản đúng
>    của mọi thứ nó đã ghi — đừng chữa lại ở máy kia.

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
  phải chạy lại script này, Run as Administrator **trong shell ĐÃ kích hoạt
  venv hoặc kèm `-PythonExe <venv>\Scripts\python.exe`** — 30/09 cửa sổ Admin
  trần đã đăng ký `C:\Python314` không thư viện; script nay từ chối Python hệ
  thống trừ `-AllowSystemPython`). Trần task Daily **240
  phút** trong script từ 29/09 (180 giết phát 21/09 GIỮA bước brief: sync 99′ +
  screener 23′ + news 17′ + train 12′ ⇒ brief bắt đầu ở phút 168; máy còn đăng
  ký 180 tới khi chạy lại script). Bước brief đêm VCI ốm từng mất 23–42′ vì
  auto-refresh sự kiện GDKHQ gõ VCI 52 mã × timeout 30s (22/09) — nay
  `refresh_upcoming` dừng sau 3 mã lỗi liền, giữ cache (#21); log in
  `[brief] ⏱ <agent>: Ns` từng agent + `ctx+prompt`.
  Updater lưỡng cực (đo 08–14/09): ~270s khi VCI khoẻ, 4.860–6.500s đêm VCI
  timeout ⇒ fallback KBS 1.130–1.245 mã + 150–181 lỗi (0 rate-limit). Dấu hiệu:
  dòng `⚡ Fallback KBS` + `❌ N lỗi` trong log. Đêm ấy marker `pipeline_status`
  updater KHÔNG ghi (chỉ ghi khi lỗi = 0) — đừng đọc thành "updater không chạy".
- ⚠️ HAI MÁY: desktop `PICHU` (2 task lịch, sinh brief) · laptop
  `CFA-BINHLD-LT` (không task). **KHÔNG nhận dạng bằng đường dẫn hay tên venv**
  — cả hai đều `C:\vnstock`, và venv đổi theo TÀI KHOẢN đăng nhập chứ không
  theo máy (desktop in `\admin\`, phát trước in `\Administrator\`). Dấu hiệu
  duy nhất đáng tin: `$env:COMPUTERNAME` + `Get-ScheduledTask -TaskName
  'VnStock *'` (2 task = desktop). Đã quy sai máy 3 lần ngày 19/08.
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
- Sửa module lõi nào → `python run.py test --fast` (~2.719 test; ~45s trên CI,
  86s máy thật 15/09 tối). Danh sách file `--fast` là WHITELIST trong `run.py` —
  thêm file test mới thì phải ghi vào đó, không thì `--fast` không chạy nó.
- Trước khi tạo PR về `main` → `python run.py test` (đầy đủ, ~3.235 test — pipeline 29/09 chạy full 3.235 passed / 134s).
  Đo trên MÁY THẬT (💻 laptop) 09/09: **3.158 passed / 161,8s** tại `c969d6a` — khớp
  CI từng test một (máy thật chậm hơn ~3× vì có kho dữ liệu, không phải vì bỏ test).
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
  duy nhất). 53 guard chia 3 chủ đề: `_guards_sections` (sai chuyện gì) /
  `_guards_numbers` (sai số, sai chiều) / `_guards_text` (lộ ruột, nói nhảm),
  tiện ích chung ở `_guards_common`, hằng số + khối canon mà CẢ prompt lẫn
  guard dựng chung ở `vnstock_brief_canon.py`. Một chiều: brief → guards →
  3 nhóm → common/canon (`tests/test_brief_split.py` canh). Mọi tên vẫn
  re-export qua `vnstock_brief` nên đường import cũ không đổi.
  Agent OpenAI-compat (`_OpenAICompatAgent`): 429/5xx ⇒ đợi 20s gọi lại ĐÚNG
  model một lần, rồi sang `_MODEL_FALLBACKS` cùng provider (Gemini flash →
  flash-lite; OpenRouter super → ultra); output cụt ⇒ sang dự phòng ngay;
  401/402/403 ⇒ dừng hẳn + cầu dao ngày. Body mổ ở MỘT chỗ `_openai_extract`
  (30/09): HTTP 200 kèm `{"error": …}` không `choices` (OpenRouter upstream
  503) = lỗi provider, KHÔNG KeyError; content RỖNG (model chỉ "suy nghĩ") =
  lỗi agent, sổ ghi fail — sổ chỉ ghi OK khi có chữ thật (22/09: sổ 3 OK mà
  brief trắng). KHÔNG hỏi danh mục provider để bỏ
  slug (OpenRouter cắt trang 400 — 15/09 bỏ nhầm ultra đang sống, brief trắng).
  Trần output là TRẦN, không phải chi phí: Gemini `_THINK_HEADROOM` 8.000,
  OpenRouter `_OUTPUT_HEADROOM` 5.200 (nemotron cụt brief ở 2.800). Cụt vẫn
  ghi usage vào sổ ⇒ `llm_ledger --show` in "lần lỗi cuối tốn: vào · ra ·
  suy nghĩ" — đọc số đó trước khi nới trần hay đổi model.
- `vnstock_claude_cli.py` + `vnstock_brief_pack.py` — **engine CLAUDE** (30/09,
  U61/U62). `vnstock_claude_cli.complete(user, system=, json_schema=)` = MỘT
  lượt Claude Code headless (`claude -p`, prompt qua STDIN, `--output-format
  json`, `--tools ""`, tước context repo `--setting-sources "" --disable-
  slash-commands --strict-mcp-config` (20K → ~1,6K token system), `--fallback-
  model` Sonnet, sổ LLM provider `ClaudeCode` ghi MỌI kết cục, stdout không
  JSON = LỖI). Công tắc: `VNSTOCK_LLM_ENGINE=claude` cho mọi bước, đè riêng
  `VNSTOCK_<BRIEF|NEWS|AUDIT|TRAIN|REFLECTION|DIGEST>_ENGINE`; đọc `.env` TRƯỚC
  khi chọn. Brief: `build_pack` (ctx+prompt, `_meta/brief_pack.json` v2 +
  `brief_prompt.md`) → CLI → `finalize_brief` (55 guard → validate → memory
  `agent_type=claude` → brief_watch) → `push_close_brief(ai_block, engine)`;
  raw/final ghi `_meta/brief_claude_raw.md` / `brief_claude.md` (Telegram lỗi
  ⇒ `run.py brief --from-file` gửi lại không tốn call). Hỏng khâu nào ⇒ **rơi
  về ladder** + marker `brief_push.json{engine, agent, machine, claude_error}`
  + badge doctor `brief_engine` (đỏ khi hỏng ≥3 ngày). Lệnh:
  `run.py brief --engine|--export-pack|--from-file`, `telegram close --engine
  claude --force` (A/B), `python vnstock_brief_pack.py --check|--review|--rate`,
  skill `/brief-close` (tay) và `/brief-review` (sáng hôm sau, chấm sao →
  few-shot). CLI bị GIẤU `ANTHROPIC_API_KEY` trừ `VNSTOCK_CLAUDE_CLI_API_KEY=1`.
- `vnstock_corp_ratio` — đọc TỈ LỆ QUYỀN từ tiêu đề sự kiện (hàm thuần).
  `adjusts_price(title)` lọc sự kiện chỉ chốt danh sách DỰ HỌP (ĐHĐCĐ, lấy ý
  kiến bằng văn bản) — chúng KHÔNG đổi giá tham chiếu, gắn ⚠️ GDKHQ cho chúng
  là cảnh báo cú giảm không bao giờ xảy ra (vết PNJ 24/08). Không nhận ra ⇒
  mặc định CÓ đổi giá.
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
  `probe_price_basis.SAME_BASIS_TOL` (có test canh). Nhánh fallback KBS (đêm
  VCI timeout) KHÔNG qua V1 mà qua cửa riêng 8% ⇒ lệch 2–8% có thể lọt thành
  VÁCH giữa chuỗi (BAL 16/09: 3 bar sau vách 27/08 khớp nguồn); lệch >8% thì
  KBS bị từ chối thành `error`, **KHÔNG vào sổ cách ly** ⇒ badge mù, mã đứng
  im (việc #15). Triage in `0d` (kho có bar hôm nay) KHÔNG có nghĩa kho sạch
  (14/09: BMI/DVN/DVP/ELC `0d` mà rebase vẫn thấy vách 06–09/09).
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
- `scripts/export_bank_balance_sheets.py` — xuất BCTC ngân hàng ra Excel.
  🛑 **Tầm phủ đã tra hết 26/08, ĐỪNG DÒ LẠI:** `vci` sớm nhất **2018-Q1**
  (đúng khung ngân hàng — dùng cái này) · `cafef` có 2015-2016 nhưng **sai
  khung (doanh nghiệp thường)** · `kbs` rỗng · `tcbs` 404 · `finhay` (MCP)
  đúng khung nhưng **trần 5 kỳ** và script chạy trên máy user nên không gọi
  được MCP. Xin sớm hơn 2018 ⇒ chỉ còn đường user xuất Wichart/FiinPro. Lý do
  bác từng nguồn + 8 lượt dò: mục **U34** `docs/CLAUDE-NOTES.md`.

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
  `VNSTOCK_WSS_HOT_TIER`, `VNSTOCK_BRIEF_WATCH`,
  `VNSTOCK_FIXUNITS_FOOTER_PRUNE`, `VNSTOCK_NETBS_WORKERS`, `VNSTOCK_LLM_ENGINE`
  + `VNSTOCK_<BƯỚC>_ENGINE` + `VNSTOCK_CLAUDE_CLI_{EXE,MODEL,FALLBACK_MODEL,
  TIMEOUT_S,API_KEY,REPO_CONTEXT}`, `VNSTOCK_LLM_BREAKER`
  — cầu dao tài khoản LLM: provider 401/402/403 hôm nay + chưa call nào OK ⇒
  mọi điểm gọi bỏ nấc đó trong ngày; 429/5xx KHÔNG chặn).
- Nghi ngờ CHƯA đủ căn cứ để vá → **đừng ghi vào notes, hãy ĐẾM**:
  `vnstock_brief_watch` nhặt bằng chứng mỗi phiên vào `_meta/brief_watch.json`,
  badge doctor `brief_watch` chỉ réo khi ≥ `MIN_SAMPLES` phiên. Dưới sàn mẫu
  badge phải **ok kèm n=…**, không bao giờ warn (vết 13/08: n=2 vẽ thành "0%").
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
- `GTGD cả ngày` = Σ giá×KLGD của mã CÓ bar phiên đó; mã LỚN (TB ≥ 50 tỷ/phiên)
  thiếu bar ⇒ runner kê `gtgd_missing_heavy`, baseline TB5/TB20 so trên CÙNG tập mã
  (`excl_missing`), prompt + guard ghi "(chưa gồm N mã lớn thiếu data)", doctor
  badge `gtgd_coverage` (#18, 30/09 — 45 mã cách ly 16–29/09 làm brief đọc sai TB).
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