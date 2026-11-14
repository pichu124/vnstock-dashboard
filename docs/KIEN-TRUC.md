# Bản đồ kiến trúc — từng module, lý do và vết sự cố

> Tách nguyên văn khỏi `CLAUDE.md` ngày 13/11/2026. `CLAUDE.md` giữ bản đồ MỘT DÒNG mỗi khu;
> file này là bản đầy đủ — MỞ trước khi sửa module tương ứng. Thêm module/đổi hành vi ⇒ ghi ở đây.
> Luật vận hành (hai máy, kho, test, công tắc env): `docs/VAN-HANH.md`.

- `vnstock_dashboard.py` — UI chính; các tab trong `dashboard/` (market,
  analysis, news+macro, money_flow, screener, portfolio, allocation,
  reports, rates_report).
- `vnstock_brief.py` — sinh AI brief morning/close (context → prompt → agent).
  Chuỗi `apply_brief_guards(text, ctx)` ở `vnstock_brief_guards.py` DÙNG CHUNG
  cho cả 2 brief — KHÔNG BAO GIỜ inline lại vào `generate_brief` (điểm parity
  duy nhất). 57 guard chia 3 chủ đề: `_guards_sections` (sai chuyện gì) /
  `_guards_numbers` (sai số, sai chiều) / `_guards_text` (lộ ruột, nói nhảm),
  tiện ích chung ở `_guards_common`, hằng số + khối canon mà CẢ prompt lẫn
  guard dựng chung ở `vnstock_brief_canon.py`. Một chiều: brief → guards →
  3 nhóm → common/canon (`tests/test_brief_split.py` canh). Mọi tên vẫn
  re-export qua `vnstock_brief` nên đường import cũ không đổi.
  Mục ⚠️ Rủi ro = `enforce_risk_today` (U75, `docs/THIET-KE-MUC-RUI-RO.md`): CODE dựng từ
  phơi nhiễm hôm nay (📌 danh mục, lệnh mở footer, GDKHQ, tiền tệ/NN mạnh), model ≤1 dòng
  không số; khối cực trị D/E·Op.CF toàn vũ trụ RỜI brief ngày (`VNSTOCK_BRIEF_RISK_TODAY=0` trả lại),
  chỉ in lại dòng `- Kỳ BCTC mới — …` (kèm kỳ trước) khi nguồn có KỲ MỚI chạm bảng: updater ghi cột
  `de_period`/`ocf_period` + sổ `_meta/fundamentals_periods.json` (lần đầu = MỐC), brief CHIỀU ghi
  `_meta/fund_period_announced.json` (mỗi kỳ mới xét đúng 1 phiên); soi: `python vnstock_fund_periods.py`.
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
  JSON = LỖI; `claude` là shim `.cmd` npm + system nhiều dòng/`|<>%` ⇒ đi `--system-prompt-file` — cmd.exe CẮT argv ở xuống dòng, 12/10). Công tắc: `VNSTOCK_LLM_ENGINE=claude` cho mọi bước, đè riêng
  `VNSTOCK_<BRIEF|NEWS|AUDIT|TRAIN|REFLECTION|DIGEST>_ENGINE`; đọc `.env` TRƯỚC
  khi chọn. **5 bước LLM đều nối** (#26): news = sentiment + chấm tin RSS theo
  LÔ một call `--json-schema` (`score_batch_cli` / `analyze_items_cli`, tin
  thiếu ⇒ ladder từng tin); audit + reflection + debate = nấc `claude-cli` ĐẦU
  cascade `report_digest.digest_call(step=)`; train = `ClaudeCodeAgent` làm
  lead (`_inject_claude_lead`), ladder free = pool. Mọi chỗ lỗi ⇒ ladder như
  cũ, log `[<bước>] ⏱ claude-cli: …`. Brief: `build_pack` (ctx+prompt, `_meta/brief_pack.json` v2 +
  `brief_prompt.md`) → CLI → `finalize_brief` (57 guard → validate → memory
  `agent_type=claude` → brief_watch) → `push_close_brief(ai_block, engine)`;
  raw/final ghi `_meta/brief_claude_raw.md` / `brief_claude.md` (Telegram lỗi
  ⇒ `run.py brief --from-file` gửi lại không tốn call). Hỏng khâu nào ⇒ **rơi
  về ladder** + marker `brief_push.json{engine, agent, machine, claude_error}`
  + badge doctor `brief_engine` (đỏ khi hỏng ≥3 ngày). Lệnh:
  `run.py brief --engine|--export-pack|--from-file`, `telegram close --engine
  claude --force` (A/B), `python vnstock_brief_pack.py --check|--review|--rate`,
  skill `/brief-close` (tay) và `/brief-review` (sáng hôm sau, chấm sao →
  few-shot). CLI bị GIẤU `ANTHROPIC_API_KEY` trừ `VNSTOCK_CLAUDE_CLI_API_KEY=1`.
- `vnstock_report_vision.py` — báo cáo 🖼 (PDF scan / DOCX toàn ảnh) ⇒ Claude Code
  `--tools Read` xem ảnh trong thư mục tạm, chép thành text ⇒ `vnstock_reports.set_text`
  (`text_via=claude-vision`) rồi digest như thường. Gọi tay (nút 👁 / CLI), được ăn cả
  (U69, 04/10). `vnstock_claude_cli.complete(tools=, cwd=)` mặc định vẫn 0 công cụ.
- `vnstock_horizons.py` — brief 3 khung (U70/U71, `docs/THIET-KE-BRIEF-3-KHUNG.md`, chốt 05/10):
  lõi THUẦN ngắn hạn/trung hạn tuần (+cầu chì 8% trên đỉnh 12 đóng tuần)/mức kích hoạt/🚨/
  bảo vệ 2 mức/bảng Stance. `vnstock_horizons_state.py` = CHẠY BÓNG (P1a, 05/10): bước pipeline
  `horizons` sau gold ghi `_meta/horizon_state.json` (inputs + published append-only, gấp từ input
  đã lưu, có bản live thì no-op, kill-switch `VNSTOCK_HORIZONS_STEP=0`) + badge doctor `horizons`;
  `run.py horizons --show|--backfill|--replay|--legend`. **P1b (#19–#26) brief ĐỌC state** sau
  `VNSTOCK_HORIZONS` (mặc định BẬT từ 14/10 — duyệt bản mẫu; `=0` về khung cũ): 🔭 + TLDR dòng 3, bảng Stance,
  lớp bảo vệ 2 mức (`defensive_level`/`is_defensive`), từ vựng (`vnstock_regime.vocab_label`;
  `label_old` chạy bóng giữ nhãn cũ), header Telegram; kẹp tỷ trọng #20 chạy thật. Bản mẫu +
  vòng tròn ctx thật: `scripts/sample_horizons_brief.py [--check 5]`. P0: `scripts/replay_horizons.py`.
- **Connector MCP (SSI/TCBS/Finhay — gắn TÀI KHOẢN Claude, Python không gọi thẳng)** (U78/U79,
  08/10): `vnstock_claude_cli.complete_mcp(user, system=, allowed_tools=)` = bộ cờ GỌN đã đo 🖥️
  (`--tools ToolSearch` + tước settings, KHÔNG `--strict-mcp-config`, ~$0,06/lượt Sonnet), đọc
  THẲNG `tool_result` trong stream-json — số không đi qua chữ model. `complete()` vẫn CHẶN MCP.
  `vnstock_mcp_enrich.py` = CHẠY BÓNG: bước `mcp-enrich` SAU brief, TCBS overview (cp lưu hành vs
  niêm yết — tách cp thưởng vừa GDKHQ khỏi phát hành thêm) + 5 công bố, cho mã đang giữ + lệnh mở
  ⇒ `_meta/mcp_enrich.json`; brief CHƯA đọc. `run.py mcp-enrich --show`. Đo: `scripts/probe_mcp.py`.
- **Đa tài sản vàng · dầu · USD** (U81 thiết kế · U82 P1 code, 09/10): `docs/THIET-KE-DA-TAI-SAN.md` (§4c
  nguồn, §4e số đo, §9 P1). `vnstock_assets` (registry 25 chuỗi, kho `data_warehouse/assets/<KHOÁ>/<YYYY>.parquet`
  — KHÔNG vào registry vĩ mô) + `_sources` (Python, mạng qua một chỗ `HTTP`) + `_mcp` (Finhay/SSI). Mỗi chuỗi =
  MỘT công cụ (giao ngay ≠ HĐTL); lệch nguồn ⇒ cờ `xcheck`. **Chuẩn user: số quốc tế phải có TRONG NGÀY** ⇒
  nguồn Python MỖI GIỜ qua task News Alert (`run.py news-alert` → `vnstock_assets.py --hourly`, trần 360s) +
  MCP giờ `VNSTOCK_ASSETS_MCP_HOURS`; chuỗi chậm chỉ hiện qua `*_EST` (USD rộng ±0,3%, WTI giao ngay ≤3 phiên;
  Brent giao ngay ẩn). Pipeline: `assets` sau gold, `assets-mcp` cuối. Doctor `assets`. Tab 💱 (P2, U83; nhãn KHÔNG dùng 🪙 — Windows 10 vẽ ô vuông, brief/Telegram vẫn 🪙):
  `dashboard/assets_tab.py` chỉ vẽ, số ở `vnstock_assets_view` (thuần; % đổi theo NGÀY LỊCH); không `$` trong caption.
  P3 đối chiếu MCP↔Python (`agreement`, sổ `_meta/assets_sources.json`) · P4 `vnstock_assets_links` (beta riêng 60p)
  · P5: mục 🪙 brief = dòng CODE (`vnstock_assets_brief` → guard `enforce_assets_section`), cảnh báo biến động mỗi giờ
  (`vnstock_assets_alerts`, kênh tin), scorecard lớp Vàng đo bằng VND (nhẫn SJC).
  ⚠️ SSI "SBVN" = giá tham khảo Cục QLNH (`USD_SBV_REF`), KHÔNG phải trung tâm; mbk ghi trung tâm LÙI 1 phiên
  ⇒ `shift_mbk_dates` dời (đo 10/10, §9c) — `--show`/doctor kiểm lại ngày từ kho mỗi lần.
- **Vị thế phái sinh khối ngoại HĐTL VN30** (U88, 15/10): `vnstock_futures_foreign` (kho
  `data_warehouse/futures`, seed 2 năm `data/seed/…csv.gz`, lượt SSI MCP qua `complete_mcp`; mã KRX `41I1`+năm+tháng)
  + `vnstock_futures_foreign_view` (thuần: Σ mua−bán từ niêm yết, sau đáo hạn, chuỗi, sai số). Bước `futures-foreign`
  TRƯỚC brief; mục brief `📑` = dòng CODE (guard `enforce_futures_foreign_section`); tab `📑 Phái sinh NN`; doctor
  `futures_foreign`. `run.py futures-foreign --show|--seed|--force|--dry-run`.
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
  Lệnh mở xuyên GDKHQ (U74): reconcile TREO khi kho chưa rebase, chấm mốc × hệ số đo tại
  neo `rec_basis_anchor` khi đã rebase, quá hạn ⇒ `corp_action` không giá; sổ sự kiện đã qua
  `_meta/corp_actions_ledger.json`.
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
  `probe_price_basis.SAME_BASIS_TOL` (có test canh). Thế hệ 6 (11/11) đã bỏ nhánh
  fallback KBS + cửa riêng 8% ⇒ MỌI lượt nối đều qua V1. ⚠️ Đổi nguồn trong
  `VNSTOCK_SOURCE` (hoặc nguồn dự phòng trả bar) có thể lệch cơ sở với kho cũ ⇒ mã
  vào sổ cách ly hàng loạt: đối chiếu trước bằng `probe_price_basis`. Triage in `0d` (kho có bar hôm nay) KHÔNG có nghĩa kho sạch
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
- `scripts/export_bank_balance_sheets.py` — xuất BCTC ngân hàng ra Excel. Thế hệ 6:
  `--source vnstock` đi `Fundamental().equity(t)` của nguồn khai ở `VNSTOCK_SOURCE_ROUTES`
  (`fundamental.equity.*=…`); tầm phủ dưới đây là của dòng CŨ, nguồn mới phải đo lại.
  🛑 **Tầm phủ đã tra hết 26/08, ĐỪNG DÒ LẠI:** `vci` sớm nhất **2018-Q1**
  (đúng khung ngân hàng — dùng cái này) · `cafef` có 2015-2016 nhưng **sai
  khung (doanh nghiệp thường)** · `kbs` rỗng · `tcbs` 404 · `finhay` (MCP)
  đúng khung nhưng **trần 5 kỳ** và script chạy trên máy user nên không gọi
  được MCP. Xin sớm hơn 2018 ⇒ chỉ còn đường user xuất Wichart/FiinPro. Lý do
  bác từng nguồn + 8 lượt dò: mục **U34** `docs/CLAUDE-NOTES.md`.

- `vnstock_news_alert.py` — **cảnh báo tin quan trọng MỖI GIỜ → Telegram**
  (02/10, #31; task `VnStock News Alert` mỗi giờ 24/7 ở ĐÚNG MỘT máy — 08/11 user chuyển sang 💻 laptop
  bằng `setup_scheduled_tasks.ps1 -OnlyNewsAlert` + `Disable-ScheduledTask` ở desktop; log tin nằm ở
  `run_daily.log` của MÁY ĐÓ; KHÔNG nằm trong `all`). Registry `SOURCES`: 11 RSS của `_FEEDS` + 20 nguồn nước ngoài
  RIÊNG `_ALERT_FEEDS` (Bloomberg/WSJ host `feeds.content.dowjones.io`/FT/CNBC/Fed/
  BLS/BEA + Google News `site:reuters.com`… — URL ứng viên, 🖥️ `run.py news-alert
  --diag` xác minh) + Bluesky/X qua env (U68; adapter tin theo mã TẮT, user chốt
  02/10 chỉ tin vĩ mô) → cửa sổ 3h, lượt đầu sau khi máy tắt/ngủ BẮT BÙ tới `covered_until`
  lượt trước (trần 36h) → cap 6 tin/nguồn, tường fetch 45s
  → sổ `_meta/news_alert_seen.json` → Claude Code chấm 0–100 cả LÔ một call (06/10, U76;
  `MIN_SCORE` 1–5 cũ ⇒ ×20) (rơi về ladder + điểm từ khoá; không engine ⇒ KHÔNG gửi tin thô) → ≥75 gửi,
  ≤8 tin/lượt, dư để lượt sau không chấm lại → **BƯỚC 2 ĐỌC KỸ** (12/10, U87: tin đạt tác động ≤10/lượt
  lấy THÂN BÀI qua Jina — tường phí/GNews = chỉ tiêu đề — Claude chấm GIÁ TRỊ ĐỌC + điểm chính, guard: số
  trong điểm chính PHẢI có trong bài; gửi khi đạt CẢ HAI, `VNSTOCK_NEWS_ALERT_MIN_VALUE` 60; tin đã loại
  không bao giờ đi; Claude lỗi ⇒ gửi theo tác động kèm nhãn; hiệu chỉnh `--recheck-sent 24`; **chỉ tiêu ~1 tin/giờ** (user 12/10): 3h qua gửi chưa đủ ⇒ BÙ tin đã đọc kỹ tốt nhất trên sàn đọc 40/tác động 30, nhãn `➕ tin bù`, `VNSTOCK_NEWS_ALERT_TARGET_PER_H` 0 = tắt) → marker
  `news_alert_status.json{machine,error_streak}` + badge doctor. Không tin mới
  = im lặng, không gọi LLM. Không đụng `market_news_cache.json`. Thêm nguồn =
  một `Source(...)`. Lệnh: `run.py news-alert --dry-run|--force|--list-sources`.
  Gửi qua KÊNH `news` (05/10): `TELEGRAM_NEWS_BOT_TOKEN`/`_CHAT_ID` = bot + group
  riêng, thiếu biến nào lấy mặc định; brief + mọi thứ khác vẫn `TELEGRAM_BOT_TOKEN`/
  `_CHAT_ID`. Lấy id group: `run.py telegram chats [--channel news]`.
- `vnstock_ta_score.py` (+`_io`) — thước đo nhận định kỹ thuật (PTKT P0, `docs/THIET-KE-PHAN-TICH-KY-THUAT.md`):
  S/R + trigger + Stance T+1/T+5 chấm lại từ `brief_memory.db`, trạng thái horizons → lợi suất, `grade_setup` (luật
  §13.1: mua mở cửa/chạm trigger, T+2,5, phí+thuế); `run.py ta-score [--backfill|--show]`, badge doctor `ta_score`;
  cột `briefs.sent` = bản đã gửi Telegram. Chỉ báo dùng chung: `vnstock_indicators` (`rsi_wilder`/`sma`/`ema`/`atr`).
- `vnstock_fund_checked.py` + `vnstock_fundamental_updater.py` — **cơ bản T7 XOAY VÒNG** (14/11). Thế hệ 6:
  `--force --workers 4 --delay 1` chạy ~5,8 mã/phút (đo 🖥️: 939 mã / 2h42, 0 lỗi) ⇒ đủ 1.754 mã ≈ 5 giờ, quá trần
  180′ của task Weekend; danh sách mã xếp ABC nên tuần nào cũng cắt ở mã ~850, nửa sau bảng chữ cái không bao giờ
  được cập nhật mà doctor vẫn xanh (chỉ nhìn mtime). Chữa bằng THỨ TỰ, không nâng trần: sổ
  `_meta/fundamentals_checked.json` `{mã: ngày}` ghi lần cuối nguồn TRẢ LỜI (có số hoặc rỗng — mã "giữ data cũ"
  không đổi `updated_at` nên phải có sổ riêng; mã LỖI không ghi ⇒ thử lại sớm); `fetch_order` = chưa kiểm → cũ
  nhất → mới nhất. Hai thứ Bảy phủ hết kho. Chạy bù trong ngày: `--force --min-age-days 1`. Doctor `fundamentals`
  thêm lớp độ phủ: >10% mã (có thư mục giá) bị bỏ quên quá 21 ngày ⇒ warn; chưa có sổ ⇒ chỉ xét mtime như cũ.
  Task Weekend ra `267014` giữa bước này là bình thường. Lệnh của task KHÔNG đổi.
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
  và caption sidebar, đừng đoán. Công tắc ở SIDEBAR CHUNG (render mọi lượt — nav
  `st.pills` chỉ vẽ tab đang mở, widget trong tab bị dọn state khi rời tab):
  🔴 Live Mode (`live_mode_toggle` → cờ `live_mode`) + Live Scan (05/10 gộp 2 toggle
  Screener/Dòng Tiền: `live_scan_toggle` → cờ `live_scan`, khoá + về OFF khi
  Live Mode tắt). Tab chỉ ĐỌC cờ — `tests/test_live_mode_crosstab.py` canh.
