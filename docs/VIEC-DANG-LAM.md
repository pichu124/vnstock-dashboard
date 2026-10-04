# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 04/10/2026 tối — **news-alert CHẠY 24/7 trên 🖥️ desktop (#31): lượt tự động 20:00 + 21:00 ✅ (`message_id` 303/304), Bluesky List cảnh báo 24 người chọn bằng số liệu (`bsky_eval.py`), List đọc thử 69. VIỆC CÒN LẠI gom ở đầu mục 9 ("📋 CÒN PHẢI LÀM"); nhắc tự động 08:00 CN 01/11 chấm lại List sau FOMC.** Bản trước 04/10/2026 rạng sáng — **news-alert CHẠY THẬT trên 🖥️ desktop (#31): diag 31/31, gửi tay 8 tin (`message_id=302`, Sonnet $0,03/lượt), badge ✅, test full 3.486 passed/171s, 3 task đã đăng ký (Daily trần 240′).** Bản trước 02/10/2026 trưa — **02/10 trưa — news-alert MỞ RỘNG (U68): cửa sổ bắt bù qua đêm, 20 nguồn nước ngoài riêng (Bloomberg/WSJ/FT/CNBC/Fed/BLS/BEA + Google News `site:reuters.com`…), adapter Bluesky (miễn phí) + X (có key), `--diag` — 🖥️ DESKTOP chạy `--diag` TRƯỚC khi đăng ký task.** **02/10 sáng — CẢNH BÁO TIN QUAN TRỌNG MỖI GIỜ → Telegram (#31, mục 9): code xong trên nhánh `claude/magical-dirac-yu672i`, CHỜ 🖥️ DESKTOP merge + chạy lại `setup_scheduled_tasks.ps1` (task thứ ba `VnStock News Alert`).** Bản trước 01/10 rạng sáng — **01/10 sáng — `/brief-close` thành vòng trọn (tự export gói, venv Python, hỏi rồi gửi) chạy ở cả hai máy, ⇄ CẢ HAI merge (mục 8 B).** **01/10 sáng — `/brief-review` đầu tiên trên desktop: #914 chấm 4★; validator VNINDEX báo giả (năm trong ngày ISO) đã vá #30 (`49c78d6`, gộp về nhánh Claude `7da5a4a`, U66).** **PHÁT 30/09 (chạy bù 23:47) DỪNG Ở BƯỚC TEST rc=2 ⇒ KHÔNG CÓ BRIEF 30/09** — test slug ngoài whitelist còn ghim qwen chết (#17), đã vá + vào whitelist (fast 2.773 · full 3.359, U65); 🖥️ desktop đã merge `ceddbfb`, full 3.359 xanh / 101s ⇒ phát 18:00 01/10 qua được bước test. **DESKTOP ĐÃ BẬT ENGINE CLAUDE** (mục 8: bước 1·2·4 xong, native exe ghim, `--check` 6/6 claude; A/B chưa) ⇒ **phát 18:00 01/10 là đêm Claude đầu tiên**, sáng 02/10 `/brief-review`. Bản trước 30/09 chiều — **Hội đồng chấm tin 290: 4★ (U64), #28 vá guard khung NN.** **CẢ 5 BƯỚC LLM DÙNG CLAUDE (#26 xong, U62 §3b)**: một dòng `VNSTOCK_LLM_ENGINE=claude` trong `.env` desktop bật news (sentiment + chấm tin theo lô), audit, train (lead), reflection và brief; mỗi chỗ lỗi ⇒ ladder free như cũ. Chờ user làm 4 bước mục 8. Bản trước 30/09 trưa — **BRIEF CHIỀU BẰNG CLAUDE đã qua thẩm định 3 giám khảo (U62)**: A (CLI headless trong pipeline) là đường chính, B (skill tay) ghi đè, Routine cloud loại. Vá theo thẩm định: stdout không JSON không bao giờ thành brief, `.env` được đọc trước khi chọn engine, set trong ctx sống sót qua JSON (pack v2), `brief_prompt.md`/`raw`/`final`, marker ghi agent+máy+lý do rơi, badge doctor "Engine brief", `--check`/`/brief-review`. **User muốn cả 5 bước LLM dùng Claude (#26, đang làm)** — backend chung `vnstock_claude_cli` + công tắc `VNSTOCK_LLM_ENGINE`. Bản trước 30/09 sáng — **BRIEF CHIỀU BẰNG CLAUDE (mục 8, #25, U61)**: user chê chất lượng brief ladder free ⇒ lõi `vnstock_brief_pack` + skill `/brief-close` đã vào nhánh, test fast 2.689. Code chạy được ba đường (CLI headless trong pipeline / tay bằng skill / API); **chờ user chọn đường và làm 3 bước ở mục 8** — chưa bật gì, pipeline đêm nay vẫn ladder. Bản trước: 29/09/2026 khuya — **SOI BRIEF 16–29/09 xong (U60)**: 8 brief close + brief phân bổ T9. Ba bản vá 16/09 đã ăn từ 17/09 (header sạch, Watchlist từ 1, điểm band không còn -0.00). Bốn lỗi mới đã vá cùng đêm (chờ 🖥️ desktop merge + `--fast`): mốc Watchlist sai chiều/phi lý (NLG về 10.300 từ 21.650, GAS mục tiêu TRÊN hỗ trợ, GEE TP dưới entry) → guard bỏ setup; lộ "(Giá X từ data)"; "Đề xuất giao dịch" bê dòng data thô `BUY entry=… (Strategy #69)`; `-0.00` ở gauge kỳ hạn. **#17 xong:** hai slug chết model watch réo hai T7 liền (Groq qwen3.6-27b 404, Cerebras gemma-4-31b archived) → gpt-oss-120b / gỡ. **Ba nghi chờ số liệu:** (a) THIẾU brief hai thứ Hai 21/09 và 28/09; (b) 22/09 ladder DOWN (flash-lite 46/46 lỗi) — brief trắng; (c) LNH ON rơi 6,84% → 0,48% trong 5 phiên mà 1W lên 6,20% (chênh 5,7 điểm — nghi dữ liệu nguồn, và nó đang bơm +0,10 vào điểm band). Bản trước 29/09 tối — user nghỉ 13 ngày, pipeline tự chạy đủ (badge Phát tối ✅ 29/09, test full 3.235 passed trong pipeline). **Sổ cách ly dồn 45 mã** (mùa quyền; TCX 1,2000× ĐỨNG 13 ngày từ 16/09 — VN30 thiếu bar hai tuần) ⇒ **đã chữa 45/45 cùng tối**: 44 mã bằng `--from-drift-ledger --whole-series --apply` 21:14; FPT bằng `--ticker FPT --break-date 2026-05-28 --apply` 22:39 (hai đợt quyền trong một năm — U59) + `vnstock_updater.py --tickers FPT` nối 7 bar ⇒ `--explain` SẠCH, doctor 22:39 sổ cách ly RỖNG. Doctor 22:39: 21✅/4⚠️ — còn brief_watch (xoá file, mục 1) · brief phân bổ tháng 9 · auto-heal 0s (để) · **sổ LLM 66 call · 30 OK · 36 lỗi** (`--show` 22:45): chuyện chính là **Gemini flash 23 call · 3 OK · 20 lỗi 503** — flash-lite gánh 17 OK (5 lỗi là read timeout 15s, cỡ timeout đường sentiment `vnstock_sentiment.py:193`, brief agent dùng 90s) ⇒ brief hôm nay nhiều khả năng từ dự phòng flash-lite, bước brief 1.743s = mỗi lượt Gemini trả 503 → đợi 20s → 503 → sang lite. **Mistral 10 call · 0 OK · 10/10 429** (0 OK từ 15/09 tới nay: 15/09 quota, 16/09 429 ×2) ⇒ giọng thứ tư user giữ 11/08 đã CHẾT hai tuần, mỗi lượt tốn 2 call + 20s chờ và giữ badge sổ LLM ⚠️ vĩnh viễn (che mất chuyện flash). **User đã TẮT Mistral 22:50** qua `save_agent_configs` (`_meta/brief_agents.json`, trong kho ⇒ cả hai máy): ladder brief còn gemini · openrouter · cerebras (402, cầu dao ăn 1 call/ngày). Model watch T7 vẫn probe Mistral vì `_ladder_slugs` gom từ `_DEFAULT_AGENT_CONFIGS` không đọc cờ `enabled` ⇒ báo cáo cuối tuần cho biết lúc nào sống lại thì bật lại (cùng lệnh, `enabled=True`). Cerebras 402 1 call = cầu dao ăn đúng (#3 còn treo). OpenRouter super 5/5 · ultra 4/4 OK, suy nghĩ 53%/79% (4c). Chi phí $0,0042. **4c ĐO XONG:** nemotron super 5/5 · ultra 4/4 OK ở trần 8.000, suy nghĩ chiếm 53%/79% token ra ⇒ trần 2.800 cũ bị thinking ăn hết. **Sổ theo dõi brief đủ mẫu (8 phiên, KBC/PVC ×9)** — đối chiếu BCTC Finhay 29/09: KBC Op.CF TTM ≈ −16.510 tỷ (Q3/25 −7.146 · Q4/25 −2.128 · Q1/26 −2.913 · Q2/26 −4.323), PVC TTM ≈ −462 tỷ ⇒ SỐ THẬT, không phải lỗi đơn vị ⇒ không cần guard, xoá `_meta/brief_watch.json` để đếm lại (mục 1). Brief bước 14 tối 29/09 **1.743s** (flash 3/23 OK, 503 cả ngày) — chưa có dòng log tách theo agent. Bản cũ: 15/09/2026 tối — **brief close 15/09 TRẮNG** ("LLM ladder DOWN", AI Outlook "Chưa có brief"): Gemini 429 rồi 503 đúng lúc chạy, Mistral quota, Cerebras 402, OpenRouter super cụt ×2 mà KHÔNG rơi xuống ultra vì bộ lọc danh mục tôi thêm ở #13 bỏ nhầm ultra (danh mục cắt trang 400). Đã vá: bỏ hỏi danh mục; agent base đợi 20s gọi lại khi 429/5xx rồi sang dự phòng cùng provider (Gemini flash → flash-lite). 🖥️ desktop **đã merge `661b193`, `--fast` 2.591/86s, rồi `telegram close --force` 20:41 ⇒ brief CÓ AI Outlook** (Gemini flash 503 → đợi 20s → OK; Cerebras bị cầu dao bỏ; super cụt → ultra được gọi nhưng CŨNG cụt; Mistral 429 ×2). 4b soi 4/4 đạt. **4c đã vá cùng tối** (sổ ghi usage khi cụt + OpenRouter nới trần +5.200). **16/09: #11 xong** (badge "Phát tối — đã tới kho này chưa") **+ vá hai lỗ hổng đường chạy bù** (#14: marker so PHIÊN PHỦ thay vì ngày lịch; T7/CN sync `--force`) — 🖥️ desktop đã merge `cf644f8`, `--fast` 2.632/98s. **Badge chạy thật lần đầu tối 16/09** (khám giữa phát): ✅ "phát tối 2026-09-16 đang tới kho này — sync partial 200 lỗi lúc 21:16 bởi PICHU · brief chiều chưa (phát còn đang chạy…)" — rồi 22:10 sau khi phát xong: ✅ "phát tối 2026-09-16 đã tới kho này — sync partial 200 lỗi lúc 16/09 21:16 bởi PICHU · brief chiều đã đẩy". **Hai verdict đúng theo thứ tự — phép đo #11 đường bình thường XONG.** Đêm 16/09 là đêm VCI ốm thứ 5/7 (partial 200). **Brief tự động 16/09 (22:06) CÓ AI Outlook, sinh bởi flash-lite qua DỰ PHÒNG** (flash 503 ×6 trong ngày) — bản vá `661b193` cứu brief ngay đêm đầu. Phát khởi động 20:25 (bật muộn), TỔNG 101,4′ (sync 3.415s · screener 776s · brief 624s). Ba lỗi chữ trong brief vá cùng tối (guard + test): header `(nếu có ... trong data)` lọt · Watchlist đánh số từ 2 · `điểm -0.00`. 🖥️ desktop đã merge `f5e512e`, `--fast` 2.635 passed / 156s (lượt trưa 98s). Sổ cách ly có 3 mã mới ACG·BAL·BHN — **đã chữa 22:07 cùng tối** (`--from-drift-ledger --whole-series --apply` 3/3: ACG 1,0322× và BHN 1,1022× lệch đều toàn chuỗi = nguồn vừa điều chỉnh lùi; BAL vách 27/08 với 3 bar sau vách khớp nguồn = đúng ca bar lọt qua cửa KBS 8% — bộ dò MỨC bắt được). VCI vẫn timeout lúc 22:02–22:07. Còn đo: sáng 17/09 badge phải "đã tới … brief chiều đã đẩy"; brief tự động 16/09; lần chạy bù kế tiếp soi #14. **Tối 17/09 soi TCX bằng tay** (`--ticker TCX --explain`) vì cửa KBS từ chối KHÔNG vào sổ (#15) — mốc so sánh 16/09 22:10: TCX sạch 1,0000× trên 224 bar, đứng 0 ngày (trước GDKHQ). #12 chạy đúng (marker `partial: 214`), #0 xong (sổ cách ly RỖNG, VNINDEX 15/09).

## 🏷️ NHÃN MÁY — quy tắc gốc: KHO đồng bộ, CODE thì không

`C:\vnstock\data_warehouse` là **Junction** trỏ sang
`E:\Dropbox\vnstock_data\data_warehouse`. Repo `C:\vnstock` đi bằng **git**.

| Nhãn | Nghĩa |
|---|---|
| ○ **MỘT LẦN** | Đụng `data_warehouse`. Dropbox lo máy kia — **đừng làm hai lần**. |
| ⇄ **CẢ HAI** | KHÔNG nằm trong kho: `git merge`, pip, venv, task lịch, biến môi trường, `run_daily.log`. |
| 🖥️ **DESKTOP** | Máy chạy pipeline (`PICHU`, 3 task lịch): log phát đêm, `Get-ScheduledTaskInfo`, brief tự động. |
| 💻 **LAPTOP** | Thử nghiệm rủi ro (`CFA-BINHLD-LT`, không task) — hỏng cũng không mất brief đêm. |

**Máy đang ngồi là TRẠNG THÁI DÍNH** (chốt 20/08): user báo đổi máy thì mới
đổi; không báo thì giữ nguyên máy của lượt trước. Đừng suy từ đường dẫn venv —
cả hai đều `C:\vnstock`, venv đổi theo TÀI KHOẢN đăng nhập. Thật sự chưa biết
thì: `$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *'` (≥2 task =
desktop). **Phiên hiện tại: 🖥️ DESKTOP** (user báo 10/09).

---

# 🔴 CÒN PHẢI LÀM

## 0. ✅ XONG 15/09 13:33 — HAI KHO ĐÃ TÁCH NHAU từ 07/09 (Dropbox desktop tắt sync) · đã sync lại, merge, chữa 25/25 mã lệch cơ sở

**Nguyên nhân (user 10/09): Dropbox ở 🖥️ desktop bị TẮT SYNC bằng tay từ tối
07/09, quên bật lại.** Không phải code, không phải junction, không phải
conflicted copy. Đã bật lại 10/09 — đang upload.

Bằng chứng đã đo 09/09 trên laptop (U56): sổ cách ly 70 mã mtime 07/09 21:07 ·
`--from-drift-ledger --whole-series` (thử) tái tạo nguyên văn bảng U53 (VIM 35 ·
HU4 24 · SGR 9 · PJS 6 · ND2 5 · CHP 4) ⇒ bản laptop = bản trước chiến dịch ·
laptop Dropbox "Up to date" ⇒ server cũng vậy ⇒ bên không upload là desktop.

### 🖥️ DESKTOP — làm theo thứ tự, mỗi bước đợi bước trước xong

**Bước 1 ĐÃ LÀM tối 14/09 (22:04) — khác dự đoán ở 3 chỗ, đều đọc được:**
- `triage_basis_drift.py` KHÔNG rỗng: **25 mã** — nhưng KHÔNG PHẢI 70 mã cũ của
  laptop (không có VIM/HU4/SGR/PJS/ND2/CHP) ⇒ Dropbox đã đưa đúng bản desktop
  lên. 22/25 kho đứng 0–7 ngày = lệch cơ sở MỚI, phát sinh SAU chiến dịch 07/09
  (mùa sự kiện quyền tháng 9: HTN 1,50 · VIB 1,0952 · DGC 1,21 · PHR 1,84…).
  8 mã `0d` (BMI DVN DVP ELC PDN PTB TIP VLW) kho đã có bar 14/09 — **KHÔNG
  phải sạch** (đoán sai lúc 22:04): rebase chạy thử vẫn thấy vách 06–09/09 với
  2–4 bar cuối khớp nguồn ⇒ bar mới vào kho bằng đường KHÁC V1 (đêm 14/09 là
  đêm fallback KBS, cửa riêng 8%). Chữa như các mã kia.
  TW3 đứng **175 ngày** (kho dừng ~23/03) — mã đóng băng kiểu GH3. **VIB là
  VN30** ⇒ brief/heatmap thiếu bar VIB từ 09/09. "Kho sự kiện mù 0/25" là
  chuyện sổ đăng ký, không phải cửa chữa — script tự nói vậy.
- `pipeline_status.json`: updater `last_success 11/09` dù phát 14/09 đã qua
  chặng sync lúc 21:55 ⇒ updater 14/09 kết thúc với **`Errors > 0`** (marker
  chỉ ghi khi `error == 0`, `vnstock_updater.py:889`; `basis_drift` KHÔNG đếm
  là lỗi). Lỗi gì thì dòng tổng kết ở bước 5 nói. Rollup `18/08` là BÌNH
  THƯỜNG: chỉ ghi marker khi có data 1 phút để cuộn (`vnstock_rollup.py:559`).
- `⏱`: sync lưỡng cực — 10/09 9,0′ · 11/09 8,7′ nhưng 08/09 109′ · 09/09 113′ ·
  14/09 85′ (updater 4.860s). Trần task là **180′** (nâng 19/08, không phải
  120′ như CLAUDE.md cũ ghi) nên 152′/159′ vẫn đủ 14/14. Nghi đầu tiên:
  rate-limit (`⏳ …: rate-limit, chờ Ns`, `vnstock_updater.py:493`) — đếm ở bước 5.
- ✅ `⏱ TỔNG [2026-09-14 22:51] 140,8′ (14 bước)` đã in ⇒ các bước ghi bên dưới
  được phép chạy (user dán 22:5x).

2. **Đợi `⏱ TỔNG` 14/09 + icon Dropbox "Up to date"**, rồi dọn conflicted copy
   (laptop ghi vài file `_meta` hôm 09/09; `prices/` không có gì để dọn):
   ```powershell
   Select-String -Path run_daily.log -Pattern '⏱ TỔNG' | Select-Object -Last 1
   Get-ChildItem data_warehouse\_meta -Filter '*conflicted copy 2026-09*'
   Get-ChildItem data_warehouse\_meta -Filter '*conflicted copy 2026-09*' | Remove-Item
   ```
3. **Merge code** (⇄, code không đi qua Dropbox; mỗi bước pipeline là một
   subprocess riêng nên đổi code giữa chừng = các bước sau chạy code khác bước
   trước — vì thế mới phải đợi `⏱ TỔNG`):
   ```powershell
   git fetch origin claude/laptop-work-ono4qt
   git merge origin/claude/laptop-work-ono4qt
   git log --oneline -1            # dòng đầu phải ghi (HEAD -> main, origin/claude/laptop-work-ono4qt)
   python run.py test --fast       # ~2.565 passed
   ```
4. **Xoá lại `brief_watch.json`** rồi doctor. Kỳ vọng MỚI: "đã soi 0 phiên";
   sổ cách ly **25 mã** (chưa rỗng — chữa ở bước 5); VNINDEX bar cuối = **14/09**:
   ```powershell
   Remove-Item data_warehouse\_meta\brief_watch.json
   python run.py doctor
   ```
5. **Chữa 25 mã theo sổ cách ly** (○ một lần vì kho dùng chung — làm ở desktop
   vì đang ngồi đây; TUYỆT ĐỐI ngoài cửa sổ pipeline) + lấy dòng tổng kết updater
   14/09 (số lỗi + số lần chờ rate-limit) cho mục #2:
   ```powershell
   python scripts\triage_basis_drift.py --plan
   python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series   # chạy thử — dán cho Claude
   Select-String -Path run_daily.log -Pattern '✅ Updated|❌ \d+ lỗi|Fallback KBS' | Select-Object -Last 8
   (Get-Content run_daily.log | Select-Object -Skip 49482 | Select-String -Pattern 'rate-limit, chờ' | Measure-Object).Count
   ```
   Chạy thử ổn (mỗi mã tự qua cửa `uniform_offset_report`; mã bị từ chối ⇒
   `--ticker <MÃ> --explain`) ⇒ thêm `--apply`, rồi `triage --plan` lại phải vơi.

   **✅ 15/09 — XONG 24/25.** 06:41–07:31 chạy thử lại: 14 OK, 5 không lấy được
   nguồn (VCI timeout ngắt quãng, mỗi mã ~6 lần × 30s), dừng sớm ĐÚNG thông
   điệp mới. 12:40 `--ticker ×14 --whole-series --apply`: **14/14 trong 70s**,
   không một timeout. 13:23 `--from-drift-ledger` chạy thử 10/11 rồi `--apply`
   **10/11 trong 45s** (VIB xong ⇒ VN30 đủ). Mỗi mã: sao lưu
   `_meta/backup_rebase/<MÃ>_20260915-*`, ghi nguyên tử, "chuỗi đã liền · bộ
   dò MỨC cũng sạch", tự xoá khỏi sổ. Hệ số đáng nhớ: PHR 1,8426 · HTN 1,5000
   · PTB 1,2624 · DGC 1,2064 · HUB 1,1372 · SVT 1,1065 · VIB 1,0950 (nguồn
   không đổi khối lượng ⇒ tool giữ nguyên, đúng). Bài học: VCI khoẻ/ốm theo
   GIỜ — 06:40 và 23:00 ốm, 12:40 và 13:20 khoẻ; lượt sau cứ thăm dò
   `--ticker BMI --explain` trước.
   **Còn TW3** (kho dừng ~23/03, 176 ngày): `--whole-series` từ chối vì tỉ lệ
   kho/nguồn trong vùng chồng lấn đi từ 1,0000 lên 1,0837 — có VÁCH trong vùng
   chồng lấn mà bộ dò bậc không thấy (dưới sàn 5 bar/phía sát ngày đóng
   băng?). Đường đi: `--ticker TW3 --explain` (đọc 12 bar đuôi, tìm ngày tỉ
   lệ đổi) ⇒ `--ticker TW3 --break-date <ngày> ` chạy thử ⇒ `--apply`.
   **✅ 13:32 XONG:** `--explain` cho thấy 11 bar đuôi 1,0834× và bar cuối 23/03
   khớp 1,0000× (13,00 ÷ 1,0834 = 12,00 — chính phiên GDKHQ); bộ dò MỨC cần
   ≥2 bar sau vách nên im. `--ticker TW3 --break-date 2026-03-23 --apply`:
   2.256 bar lấy thẳng nguồn + 6 bar (18–25/10/2016, trước độ phủ nguồn)
   nhân hệ số, "chuỗi đã liền". `triage --plan` ⇒ **sổ cách ly RỖNG**.

   **Kết quả 14/09 23:16–23:52:** `--plan` in đúng ba lệnh (sổ đăng ký 37 mã /
   493 dòng ⇒ không nạp lại). Chạy thử **10/25 mã OK** — BMI DGC DHG DIG DMC DNC
   DP1 DVN DVP ELC đều "lấy thẳng từ nguồn", giữ nguyên khối lượng — rồi
   **DỪNG SỚM**: `trading.vietcap.com.vn` Read timed out (30s) ~40 lần trong
   35 phút ⇒ HAD (RetryError), HTN, HUB ("nguồn trả rỗng") không lấy được nguồn;
   **12 mã chưa tới lượt** (IST PDN PHR PTB SHC SVT SZC TIP TW3 VAV **VIB** VLW).
   Dòng dừng sớm đổ cho "bước GHI / Dropbox/AV" là SAI (chạy thử không ghi gì)
   — đã vá `rebase_ticker_history.py`: phân loại nguồn/ghi, in đúng nguyên
   nhân, tổng kết tách "chưa lấy được nguồn" và "chưa tới lượt".
   Updater 14/09: `⚡ Fallback KBS: 1245 mã · Updated 1524 · Errors 181`;
   09/09: `Fallback KBS 1130 · Errors 150`; 10/09 và 11/09: `Errors 0`;
   `rate-limit, chờ` = **0** ⇒ chậm là VCI timeout, không phải rate-limit.
   **Còn làm (🖥️ desktop, ngoài cửa sổ pipeline, khi VCI trả lời):**
   ```powershell
   git fetch origin claude/laptop-work-ono4qt; git merge origin/claude/laptop-work-ono4qt   # bản vá dừng sớm
   python scripts\rebase_ticker_history.py --ticker BMI --explain            # thăm dò: xong trong vài giây = VCI sống
   python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series   # chạy thử đủ 25 mã
   python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series --apply
   python scripts\triage_basis_drift.py --plan                              # phải vơi
   ```
6. Brief close **15/09** là brief đầu tiên có đủ bản vá (tối 14/09 vẫn code cũ)
   — soi 4 chỗ ở mục 4b + dòng ledger Gemini.

### Bài học vận hành (đã đưa vào CLAUDE.md, hệ quả #5)
Kho lệch giữa hai máy mà `prices/` **không** có conflicted copy ⇒ nghi **sync bị
tắt** trước khi nghi code. Dấu hiệu rẻ nhất: icon Dropbox ở khay, và
`pipeline_status.json` hai bên lệch ngày. Doctor 09/09 trên laptop THẬT RA đã
réo — ⚠️ market_overview 07/09 · ⚠️ NN ròng 07/09 — nhưng đọc thành "pipeline
chưa chạy" chứ không phải "phát đã chạy ở máy kia mà chưa tới đây" (việc #11).

## 1. 🎚️ Hai badge "đủ mẫu" — ĐÃ XỬ, và cả hai đều khác dự đoán

**(a) auto-heal — ĐỪNG tắt vội, và lời khuyên cũ của badge là BẪY.**
`VNSTOCK_AUTOHEAL_BUDGET_S=0` trước đây **không tắt** mà **bỏ trần giờ** —
làm đúng theo badge sẽ cho auto-heal chạy không giới hạn, đúng hình dạng đã
giết lượt chạy 04/09. Đã vá (U54): `0` nay tắt thật.

Nhưng **đừng đặt nó**: `⏱ CHẶNG` tối 07/09 ghi `auto-heal 0s` — nó không tốn
gì. Badge chỉ đo HIỆU SUẤT (0 lành), không đo CHI PHÍ, và Claude đã chép lời
nó thành một lý do kinh tế mà số đo không đỡ. Yield 0 là **hệ quả của bản vá
`vnstock_ohlc_repair`** (rút mất lớp chiếm phần lớn hàng đợi), không phải dấu
hiệu hỏng. Tắt thì hàng đợi cách ly còn không được **dọn**, chỉ phình.

⇒ Để nguyên. Khi nào `auto-heal` ăn giờ trong `⏱ CHẶNG` thì mới hạ trần
`=120`, hoặc `=0` để tắt hẳn (chạy tay khi cần: `python run.py heal`).

**(b) Op.CF/vốn hoá — số THẬT, không lệch đơn vị. Sổ đếm nhầm ngành.**
Đầu bảng BID · BSI · DSE · HDB · NAB — **5/6 là ngân hàng/chứng khoán**, mà
với định chế tài chính thì Op.CF theo VAS gồm cả biến động tiền gửi/cho vay
(dòng bảng cân đối). Repo đã biết từ trước và xếp hạng rủi ro của brief ĐÃ
loại nhóm này. Sổ đang đếm mã không bao giờ tới được mục Rủi ro.

Đã vá: `scan_ocf_scale` dùng CHUNG danh sách với xếp hạng. KBC (BĐS) vẫn giữ.
○ **Việc của anh (một lần, kho chung — nhãn cũ 🖥️ là sai): xoá
`data_warehouse\_meta\brief_watch.json` để đếm lại** — sổ cũ toàn số rác. Vài
phiên nữa badge sẽ nói điều khác.

## 2. 📊 ĐÃ ĐO XONG phát tối 07/09 — còn đúng một chỗ đáng đào

**⏱ TỔNG 90,3′ → 38,3′** (mốc 09-03; 09-04 bị trần 120′ chấm dứt).
**Đệm dưới trần: 29,7′ → 81,7′** ⇒ rủi ro chạm trần coi như hết.

| bước | 09-03 | 09-07 | |
|---|---|---|---|
| ↳ updater | 10.527s* | **316s** | **−97%** — bản vá lớn nhất |
| brief | 646s | 59s | −91% |
| sync | 2.748s | 572s | −79% |
| train | 485s | 159s | −67% |
| screener | 846s | 669s | −21% |
| **validate** | 84s | **286s** | **+240%** ⚠️ chưa rõ vì sao |

\* từ chặng 09-04 (lần bị kill).

**Net BS là chỗ duy nhất còn đáng đào.** 09-03 `377s · 3,7 mã/s` → 09-07
`411s · 3,4 mã/s` — **chậm hơn**, và chiếm **411s/669s** của bước screener.
Screener trừ Net BS còn ~258s so với mốc 1.318s ⇒ bản vá 14 lượt → 1 đã ăn.

Hai cách đọc chưa tách được: (a) trần 8 req/s chạy đúng thiết kế và con số
"~125s" là phép tính sai vì giả định 1 request/mã — nếu mỗi mã tốn ~2,4
request thì ra đúng 3,3 mã/s; (b) song song không đạt nhịp. Muốn tách phải
đếm số request thật/mã.

**Đo lại 08–14/09 (desktop dán tối 14/09):**

| phát | ⏱ TỔNG | sync | updater | screener | brief | validate |
|---|---|---|---|---|---|---|
| 08/09 | 152,4′ | 6.547s | — | 656s | 322s | 91s |
| 09/09 | 158,6′ | 6.805s | 6.501s | 762s | 444s | 354s |
| 10/09 | 50,9′ | 540s | 263s | 690s | 523s | 330s |
| 11/09 | 41,7′ | 525s | 274s | 669s | 340s | 157s |
| 14/09 | **140,8′** (xong 22:51) | 5.121s | **4.860s** | **1.117s** | 754s | 89s |

Đọc: (a) **updater lưỡng cực — ĐÃ RÕ (14/09):** ~270s khi VCI khoẻ (10/09,
11/09: `Errors 0`), 4.860–6.500s đêm VCI timeout: 09/09 `⚡ Fallback KBS 1130 mã ·
Errors 150`, 14/09 `Fallback KBS 1245 · Errors 181`; `rate-limit, chờ` = 0.
Không phải khối lượng, không phải code — là nguồn. Hệ quả: đêm ấy marker
`pipeline_status` updater không ghi (chỉ ghi khi lỗi = 0) ⇒ việc #12. (b) Trần task thật là
**180′** (ps1 nâng 19/08) — 152′/159′ không bị chấm dứt, nhưng đệm chỉ còn
~25′ vào đêm xấu. (c) screener 656–762s: Net BS vẫn là khối lớn nhất, không
đổi. (d) validate 91 → 354 → 330 → 157s: vẫn chưa rõ vì sao, dao động 4×.
(e) brief 322–754s so 59s hôm 07/09 — chưa rõ, có thể ladder gọi lại; ledger
Gemini sẽ nói. (f) 14/09: screener **1.117s** (cao nhất từ 09-03: 846s) và
test **302s** (mọi đêm khác 95–109s) — cùng lúc user chạy triage/đọc log và
Dropbox đang upload sau khi bật lại; đêm 15/09 mà vẫn cao thì mới là việc.
Đệm dưới trần 180′ đêm 14/09: 39′.

## 3. 💳 Quyết Cerebras 402 — ○ máy nào cũng được · **NAY CÓ BẰNG CHỨNG**

Model watch T7 22/08: **Cerebras HTTP 402 "Payment required"** ở cả hai model.
Đây là hỏng **TÀI KHOẢN**, không phải model chết — đổi slug KHÔNG cứu được.

Hệ thống vẫn chạy, nhưng lưới dự phòng mỏng hẳn:

| Điểm | Còn sống |
|---|---|
| [1] sentiment | Gemini → Groq (từ 4 nấc còn 2) |
| [3-6] digest | Gemini + nemotron · Groq×2 → Gemini-lite |
| [7] brief | Gemini (agent CHÍNH) |

⚠️ **Gemini nay gánh cả ba chỗ** — nghẽn Gemini là hụt nhiều nơi cùng lúc.

📌 **Và nó đã nghẽn thật.** Doctor 07/09: `86 call · 30 lỗi · 25 rate-limit —
chạm trần Gemini:gemini-3.5-flash, Gemini:gemini-3.5-flash-lite,
Mistral:mistral-small-latest`. Đây không còn là lo xa.

Ba lựa chọn: **kệ** (rẻ nhất, rủi ro dồn vào Gemini) · **nạp tiền Cerebras**
(về nguyên trạng, không đụng code) · **tìm free thay thế** — phải probe SỐNG
trước rồi báo Claude:
```powershell
python scripts\probe_models.py --slug "OpenRouter=<slug>"
```

## 4. ⏰ NSO — ✅ TỰ XONG, KHÔNG PHẢI LÀM GÌ

Brief close 08/09 đã ghi **CPI 4.89% · IIP 14.4% · cán cân −0.12 tỷ USD, tất
cả `as_of 2026-08-31`** — kỳ tháng 8 đã về, không còn kẹt ở `2026-07-31`. GDP
vẫn `2026-06-30` là ĐÚNG (quý). ⇒ mạng nhà KHÔNG chặn NSO, bỏ luôn việc phát
4G. *(Jina ⚠️ cùng cụm nhưng **không gấp** — chỉ làm tin chấm bằng title+summary.)*

## 4b. ✅ XONG 15/09 20:41 — đối chiếu brief kế tiếp sau đợt vá 09/09: 4/4 đạt

~~Dọn cache tin cụt~~ — **không cần nữa** (đo 09/09): `--reanalyze` chỉ chấm
lại 8 tin MỚI NHẤT, mà 09/09 đã có 12 tin mới nên hai câu cụt của 08/09 không
được đụng tới — nhưng chúng cũng đã **rơi khỏi cửa sổ brief** (brief lấy 6 tin
mới nhất trong 3 ngày). Vô hại; chỉ còn hiện ở sub-tab Vĩ mô của dashboard.
Muốn sạch hẳn thì `python vnstock_news_feeds.py --reanalyze --max-analyze 30`
(≈30 call LLM, ngoài giờ pipeline) — tuỳ, không bắt buộc.

Lượt `--reanalyze` 09/09: 3/8 tin trống. Ledger đọc ra: **~nửa câu đầu bị cắt
ở 256 token** (Gemini 3.5 Flash suy nghĩ tiêu trần — gốc thật của "tác động:
Nh") và 3 lần gọi lại dính 429 vì bắn sát lần đầu. Đã vá tiếp (U55-1b): kê
768 token từ đầu · gọi lại lỗi thì đi tiếp nấc kế thay vì trả câu cụt · có vết
`✂ provider cắt giữa câu (<nấc>)` trong `--show` + tổng kết CLI + WARNING trong
`run_daily.log`. Lần `--refresh` sau kỳ vọng: **12 call cho 8 tin → ~8-9**,
không còn dòng `✂` (có thì dán cho Claude).

Brief close 15/09 20:41 (`telegram close --force`, code `661b193`) — soi 4 chỗ:
1. ✅ Header sạch, không còn `(2 dòng)` / `(1 dòng, optional)`.
2. ✅ "10Y − lãi suất điều hành = -0.07 điểm % → mỏng — sát 0 (… chưa tính
   ÂM)"; band phân bổ −0.08 (dự đoán ≈ −0.07; ON nhảy +1,88 điểm % lên 5,16%
   nên gauge thanh khoản đổi, lệch 0,01 là hợp lý).
3. ✅ "Sự kiện sắp tới" chỉ 16/09 (MSR) và 17/09 (TCX, GEE) — không có 15/09.
4. ✅ Dẫn dắt +0.099pp · Tụt hậu -0.273pp — cùng 3 số lẻ.

Quan sát thêm, CHƯA đủ mẫu để vá (để `brief_watch` đếm, đừng ghi thành việc):
- TLDR "thanh khoản vẫn dưới trung bình" nhưng Tổng kết "tăng 4% so với trung
  bình 5 phiên" — có thể TLDR so trung bình dài hơn; soi lại nếu lặp.
- Danh mục EIB: "GIỮ vì … có thông tin thay đổi địa điểm chi nhánh hỗ trợ kỹ
  thuật" — model gán tin vặt làm lý do kỹ thuật (nói nhảm mềm, guard chữ
  không bắt được).
- 17/09 TCX (VN30) trả cổ tức cổ phiếu 20% ⇒ đêm 17/09 (hoặc 18/09) V1/cửa
  KBS sẽ cách ly TCX (lệch ~16,7%), badge doctor `basis_drift` réo — là ĐÚNG,
  chữa bằng `--from-drift-ledger --whole-series` như mục Lệch cơ sở. MSR cổ
  tức tiền 1.000đ có thể cũng vào sổ (tuỳ giá).

## 4c. ✅ XONG — đo 29/09: super 5/5 · ultra 4/4 OK ở trần 8.000; suy nghĩ 53–79% token ra (trần 2.800 cũ bị thinking ăn)

Đo 15/09: super cụt 3/3, ultra cụt 1/1 cho brief (ultra 2/2 OK cho digest
ngắn; 14/09 super 2/3 OK) ⇒ trần `_BRIEF_MAX_TOKENS` = 2.800 vừa khít bản brief
tiếng Việt ~1.100 từ với tokenizer nemotron (2–3 token/từ), ngày dài tin/sự
kiện là đứt; Gemini có `_THINK_HEADROOM` 8.000 nên không sao.

**Vá (cùng commit):**
1. Sổ LLM ghi `usage` cả khi call LỖI (mọi vòng: base/Gemini/Mistral, Cerebras,
   OpenRouter, Claude) và tách `reasoning_tokens` từ
   `completion_tokens_details` ⇒ `python vnstock_llm_ledger.py --show` in thêm
   `↳ suy nghĩ: N token (x% token ra)` và `↳ lần lỗi cuối tốn: vào · ra · trong
   đó suy nghĩ`. Số cố ý KHÔNG vào `last_error` (cầu dao dò `\b40[123]\b`).
2. `OpenRouterAgent._OUTPUT_HEADROOM = 5200` cộng vào mọi call (2.800 → 8.000
   cho brief) — trần, :free không tốn.

**Phép đo (ledger đêm kế có gọi OpenRouter, tức khi Gemini hỏng ≥ 1 lượt):**
- super hoặc ultra có `OK ≥ 1` cho brief ⇒ nới trần là đủ, đóng mục.
- vẫn cụt: đọc dòng `lần lỗi cuối tốn` — `ra ≈ 8.000` mà `suy nghĩ` gần hết ⇒
  model nghĩ tiêu budget ⇒ bước kế là tắt/giới hạn reasoning (tham số
  `reasoning` của OpenRouter — PHẢI probe sống trên máy thật trước, chưa có
  bằng chứng nemotron nhận tham số này); `suy nghĩ ~0` mà `ra ≈ 8.000` ⇒ model
  lan man, đổi model.
- Không thấy dòng nào vì Gemini OK cả đêm ⇒ chưa đo được, KHÔNG phải xong.
- **Đo 16/09:** super 2 call · 1 OK · 1 cụt (trần 8.000 — từ 0/4 lên 1/2), ultra 1/1 OK. Call cụt KHÔNG mang usage (không có dòng `lần lỗi cuối tốn`) ⇒ nghi OpenRouter không trả `usage` khi cắt, hoặc call đó chạy trước khi merge 4c. Chưa kết luận reasoning — đo thêm một đêm có OpenRouter gọi.
- **Đo 29/09 (chốt):** super 5 call/5 OK, `suy nghĩ: 3,589 token (53% token ra)`; ultra 4/4 OK, `4,709 token (79%)`. Nới trần là đủ và đúng chẩn đoán: thinking ăn gần hết 2.800 cũ. Hệ quả: call nemotron dài hơn (mỗi call ≤90s timeout), brief bước 14 tối 29/09 1.743s — nếu lặp, cân nhắc giới hạn reasoning (tham số `reasoning` OpenRouter, PHẢI probe sống) hoặc log giờ từng agent.

## 5. 🧭 Brief phân bổ tháng 9 — ✅ XONG 29/09 ~23:00

Tạo từ dashboard (Tin tức → 🧭 Phân bổ → 📝 Tạo brief): Gemini (qua lite) +
Nemotron Super đều ra bản đủ; Cerebras bị cầu dao bỏ đúng thiết kế. Điểm tổng
hợp −0,342 khớp 7 dòng trọng số. Bản Super: thập phân kiểu VN ("-0,34",
"25 917"), lẫn tiếng Anh/Pháp ("weakening", "dominer") và đọc SAI nghĩa tilt
(+1 band = phòng thủ hơn, không phải "xu hướng tăng") — chỉ là bản phụ, ghi
nhận cho 4c. Badge `allocation` sẽ hết ⚠️ ở doctor kế.

## 8. 🤖 Brief chiều bằng CLAUDE thay ladder free — code xong 30/09 (đã qua thẩm định 3 góc), CHỜ USER LÀM 4 BƯỚC

Lõi `vnstock_claude_cli` (backend Claude Code headless dùng chung) +
`vnstock_brief_pack` + `run.py brief --engine|--export-pack|--from-file` +
skill `/brief-close` (viết tay) + `/brief-review` (soi sáng hôm sau) đã vào
nhánh (#25, U61 + U62). Mọi thứ quanh thân brief (guard, memory, sổ LLM, khung
Telegram, marker một-brief-mỗi-phiên) là code cũ — chỉ AGENT đổi. Đường Claude
hỏng ⇒ tự rơi về ladder, KHÔNG mất brief; marker ghi `claude_error`, badge
doctor "Engine brief" nói lý do, đỏ khi hỏng ≥ 3 ngày liền.

**Thẩm định (workflow 3 thiết kế × 3 giám khảo, 30/09):** A = CLI headless
trong bước 14 (8/7/8) là đường chính; B = tay bằng skill là đường ghi đè; C =
API trả tiền chỉ khi user muốn; D = Routine cloud LOẠI (cloud không gọi được
`api.telegram.org`, kho không lên cloud, cửa gác nửa đêm chặn fallback).

**A. 🖥️ DESKTOP — 4 bước, làm dưới ĐÚNG tài khoản Windows chạy task (`admin`)**

> **Trạng thái 01/10 ~01:30 (🖥️ desktop, tài khoản `admin`):** bước 1 ✅
> (`c7686ca`, `--fast` 2.759 / 108s, 30/09 tối) · bước 2 ✅ (`--check` ok,
> auth Max, probe `claude-opus-5-5` 4,8s; lần đầu `shim: true` vì máy chỉ có
> `claude.cmd` npm → cài native v2.1.285 vào `C:\Users\admin\.local\bin`,
> ghim `VNSTOCK_CLAUDE_CLI_EXE` bằng dấu `/`, `shim: false`) · bước 4 ✅
> (`VNSTOCK_LLM_ENGINE=claude`, `--check` 6/6 engine = claude) · bước 3 A/B ✅
> 01/10 ~02:45 `telegram close --engine claude --force` bù phiên 30/09: log
> `[brief] ⏱ claude-cli: 56s · ✅ 5,636 ký tự · $0.31` — ĐƯỜNG A CHẠY THẬT trên
> desktop lần đầu. Phát 30/09 chạy ladder (công tắc bật sau 18:00). **Phát 18:00 01/10 là
> ĐÊM CLAUDE ĐẦU TIÊN** — sáng 02/10: `/brief-review` (○) + 🖥️
> `Select-String '⏱ claude-cli' run_daily.log` phải có `[news]` `[audit]`
> `[train]` `[brief]`; #913 và #914 đều 4 sao (#914 chấm qua `/brief-review` desktop 01/10 sáng, U66).
> **`--review` sau lượt bù (01/10 ~03:00):** marker `close=2026-09-30 · engine=claude ·
> máy=PICHU`, memory #914 (8.136 ký tự, auto 0.823), guard raw 73 → final 77 ·
> 48 dòng khác. **Soi diff raw/final #914** (`Get-Content -Encoding UTF8`): gần
> hết 48 dòng là khối canon thay theo thiết kế (vĩ mô 13 · tin 6 · sự kiện 4 ·
> báo cáo 3 · rủi ro 3 · dẫn dắt 1 · caveat 1); sửa thật vào chữ Claude chỉ
> "tăng +8%" → "tăng 8%" và dạng dòng Tụt hậu — KHÔNG có số nào phải sửa. Giá
> phải trả: guard canon BỎ 3 câu đúng và có giá trị của Claude — "Hàm ý: môi
> trường thắt chặt nhẹ, bất lợi cho nhóm vay nợ cao và dòng vốn ngoại" (vĩ mô),
> "Khung tháng đồng chiều với bias GIẢM của ngày" (báo cáo), "PET vừa tăng
> +28.2%…" (rủi ro) — và bản sự kiện gộp gọn có thêm MWG/KDH 07/10. Guard sinh
> ra cho ladder hay bịa; với Claude nó đang cắt bớt. **CHỜ ĐẾM ≥3 đêm Claude rồi
> quyết** (ứng viên: canon guard giữ câu "Hàm ý" KHÔNG chứa số của model).
1. Merge code: `git fetch origin claude/laptop-work-ono4qt && git merge
   origin/claude/laptop-work-ono4qt` rồi `python run.py test --fast`.
2. Cài Claude Code CLI **bản cài native** (ra `claude.exe`, không phải
   `claude.cmd` của npm) + đăng nhập (`claude` → `/login`). Go/no-go bằng
   ĐÚNG cờ của đêm: `python vnstock_brief_pack.py --check` → JSON `ok: true`,
   `auth.loggedIn: true`, `probe.model`, **`shim: false`**. Nếu `shim: true`
   hoặc `exe_source: path` thì ghim `VNSTOCK_CLAUDE_CLI_EXE=C:\\Users\\admin\\.local\\bin\\claude.exe`
   vào `.env` (Task Scheduler dùng PATH registry; shim `.cmd` làm cmd.exe
   đọc lại argv ⇒ prompt của news/audit có `|<>%` sẽ hỏng dù brief chạy được).
   Gói thuê bao không mở Opus ⇒ `VNSTOCK_CLAUDE_CLI_MODEL=claude-sonnet-5-5`.
3. A/B có ý thức (sau 15:05, sẽ gửi TRÙNG nếu phiên đã có brief):
   `python run.py telegram close --engine claude --force` → log
   `[brief] ⏱ claude-cli: Ns · ✅ N ký tự · $x`, Telegram footer
   `🤖 Claude Code · opus-5-5`, kho có `_meta\brief_claude_raw.md` +
   `_meta\brief_claude.md`.
4. Bật cho pipeline: `.env` thêm **`VNSTOCK_LLM_ENGINE=claude`** (công tắc
   CHUNG cho cả 5 bước LLM: news · audit · train · reflection · brief — #26
   xong) — hoặc chỉ một bước, ví dụ `VNSTOCK_BRIEF_ENGINE=claude`; đè riêng
   `VNSTOCK_<NEWS|AUDIT|TRAIN|REFLECTION|DIGEST|BRIEF>_ENGINE=ladder` để tắt
   lẻ. `.env` KHÔNG đồng bộ ⇒ chỉ desktop. Tắt = xoá dòng. Phép đo sáng hôm
   sau ngoài brief: `Select-String '⏱ claude-cli' run_daily.log` phải có dòng
   `[news]`, `[audit]`, `[train]` (và `[reflection]` khi có lệnh đóng);
   `llm_ledger --show` dòng `ClaudeCode:*` nhiều call.
   Sáng hôm sau: `/brief-review` (○) — nó chạy `vnstock_brief_pack.py --review`
   rồi hỏi chấm sao; ≥4 sao thành mẫu few-shot.

**B. ○ tay — `/brief-close`** (khi muốn tự thay bản ladder hôm đó, hoặc
desktop đêm rơi về ladder). **Từ 01/10 skill làm TRỌN VÒNG trên máy đang
ngồi** (🖥️ desktop hay 💻 laptop đều được, miễn Claude Code mở tại
`C:\vnstock` có kho): tự kiểm gói đúng phiên, thiếu/cũ thì tự `run.py brief
--export-pack`, đọc `brief_prompt.md`, ghi `_meta\brief_claude.md`, HỎI user
rồi mới `run.py brief --from-file` (guard → memory → Telegram → marker
`engine=claude-file`). Python luôn gọi thẳng `%USERPROFILE%\.venv\Scripts\
python.exe` vì Claude Code mở từ shell trần từng trỏ `C:\Python314` không có
pandas (30/09 desktop). Điều kiện: kho đã có bar hôm nay (sau sync 18:00 hoặc
tự `run.py sync`); gói xuất lúc kho chưa sync là phiên HÔM QUA — skill tự nhận
ra và dừng, không viết từ dữ liệu cũ. Ngày làm việc từ 18:00 tới `⏱ TỔNG` KHÔNG
xuất gói từ laptop (pipeline đang ghi kho). Cửa một-brief-mỗi-phiên: phiên đã
có brief thì lệnh im, skill hỏi có gửi bản thứ hai bằng `--force` không (A/B
có ý thức); gửi TRƯỚC 18:00 thì bước brief của phát tối tự bỏ qua, không trùng.
Không có Claude Code thì dán `brief_prompt.md` vào claude.ai, dán trả lời vào
`brief_claude.md`, rồi `--from-file` tay. Telegram lỗi đêm A ⇒ gửi lại bằng
`--from-file` (bản đã qua guard ở `brief_claude.md`, không tốn call). Skill là
file trong repo ⇒ **⇄ CẢ HAI merge** mới có bản mới. `/brief-review` cũng đã
đổi sang venv Python.

**C. API trả tiền theo token**: `ANTHROPIC_API_KEY` + bật agent Claude trong
⚙️ (checkbox nay hết bị khoá — `ClaudeAgent._ENV_KEY`). `ClaudeAgent` vẫn
Haiku qua HTTP thô; nâng lên Opus 5.5 + SDK chỉ khi user chọn C.

## 7. 🔎 Soi brief 16–29/09 — việc còn lại cho user (chi tiết U60)

**🖥️ DESKTOP, thứ tự:** (1) ✅ đã merge `34f614e`, `--fast` 2.640 passed / 137s
(29/09 ~23:20). (1b) ✅ đã merge `1a45a91` (cửa brief chiều), `--fast` 2.643 / 327s (máy bận
nhất thời). (1c) ✅ **đã merge `a4407b0`** (log từng agent + cap 240 trong
script), `--fast` 2.645 passed / 102s (30/09 00:40) — phát tối 30/09 in
`[brief] ⏱ …`. (1d) 00:50 chạy lại script Admin: `PT4H` ✅ NHƯNG script chọn
**`C:\Python314\python.exe`** (Python hệ thống 3.14) vì cửa sổ Admin chưa kích
hoạt venv ⇒ đăng ký lại ngay 00:55 với venv thật ✅ (`Actions.Execute` =
`C:\Users\admin\.venv\Scripts\python.exe`, `PT4H`, Weekend cũng theo venv). Lệnh đã dùng:
```powershell
.\scripts\setup_scheduled_tasks.ps1 -PythonExe 'C:\Users\admin\.venv\Scripts\python.exe'
(Get-ScheduledTask -TaskName 'VnStock Daily Pipeline').Actions.Execute
```
(dòng cuối phải in đường venv; đường này lấy từ chính dòng `Update: …` của gói
vnstock trên desktop). Script đã thêm lưới: nhận `$env:VIRTUAL_ENV`, từ chối
Python hệ thống trừ `-AllowSystemPython`.
(1e) ✅ **01:15 desktop merge `e3ffab4`** (cửa dừng VCI trong `refresh_upcoming` +
lưới script), `--fast` 2.647 passed / 102s ⇒ phát tối 30/09 chạy với TRỌN BỘ vá
đêm 29/09: guard brief, slug mới, cửa brief phiên phủ, log từng agent, cap 240
bằng venv, cửa dừng VCI. Phép đo: `Select-String '⏱ TỔNG|\[brief\] ⏱|\[events\]'
run_daily.log | Select-Object -Last 10`.
(1f) ✅ **01:40 desktop merge `22e1678`** (gauge thanh khoản phân kỳ kỳ hạn, #19),
`--fast` 2.648 passed / 101s. Không còn việc nào chờ tay user cho phát 30/09.
(2) **28/09 ĐÃ RÕ** (log 29/09 23:30): pipeline khởi động 21:15, sync 7.272s
(VCI ốm → KBS 1.027 mã, partial 151 lúc 23:11), tới bước brief lúc **00:13** →
cửa `_should_push_close` thấy "ngày làm việc, trước 15:00" → bỏ qua như chạy
bù sáng → `brief 0s`. Đã vá (#20a). **21/09 chưa rõ**: `run_daily.log` xoay
vòng ở 5 MB nên chỉ còn từ 25/09; đời cũ ở `run_daily.1.log`. Dán:
```powershell
Select-String '⏱ TỔNG' run_daily.1.log, run_daily.2.log
Select-String '\[brief\] (bỏ qua|close brief sent|❌)' run_daily.log, run_daily.1.log, run_daily.2.log
Get-ScheduledTaskInfo -TaskName 'VnStock Daily Pipeline' | Select-Object LastRunTime, LastTaskResult, NextRunTime
```
(tên task đúng là `VnStock Daily Pipeline`; `brief_push.json` chỉ giữ phiên
mới nhất nên không kể được quá khứ.)
**Đọc log 23:55:** `run_daily.1.log` có `⏱ TỔNG` 11→18/09 và 22→25/09, **KHÔNG có
21/09**; `[brief]` nhảy từ msg 271 (18/09) sang 275 (22/09) — 272/273 là hai tin T7
19/09, 274 là alert ladder DOWN 22/09 ⇒ 21/09 không gửi gì. Nhưng sổ LLM 21/09 có
133 call gồm đúng bộ agent brief (Mistral 4 · super 3 · ultra 2) ⇒ pipeline 21/09
CHẠY tới bước brief rồi CHẾT giữa chừng (không `⏱ TỔNG`, không dòng `[brief]`):
nghi chạm trần 180′ ngay trong bước brief (bước brief từ 22/09 mất 1.393–2.532s vì
Gemini 503/timeout) hoặc máy tắt. 28/09 xác nhận bằng dòng log
`[brief] bỏ qua: chưa tới 15:00 (hiện 00:13)` — đúng bug #20a. Task lịch khoẻ
(LastTaskResult 0, Next 30/09 18:00). Lệnh kế, 🖥️ DESKTOP:
```powershell
Select-String '^\[run\.py\] 2026-09|=== run.py all ::|\[run\.py\] ⏱ |partial:|Fallback KBS|Traceback' run_daily.1.log | Where-Object { $_.LineNumber -gt 28158 -and $_.LineNumber -lt 39830 }
Select-String 'OpenRouter|Nemotron|Gemini|Mistral|Cerebras|ladder|\[brief\]|không đạt|loại' run_daily.1.log | Where-Object { $_.LineNumber -gt 33500 -and $_.LineNumber -lt 39830 } | Select-Object -Last 80
```
**Đọc log 00:20 — 21/09 ĐÃ RÕ:** khởi động 20:12:20, sync 5.940s (KBS 1.165 mã,
partial 171), screener 1.363s, news 1.041s, train 739s, audit 460s… cộng dồn 168′
khi `=== brief ===` bắt đầu (~23:00); 25 dòng sau là header phát 22/09 ⇒ **trần
180′ giết giữa bước brief** lúc ~23:12. Sổ LLM: doctor đếm 133 call trước brief,
cuối ngày vẫn 133 ⇒ bước brief chưa ghi nổi một call (calls Mistral/super/ultra
21/09 là của `strategy_loop` trong train + auditor). Vá: (a) script cap Daily
180 → 240 (#21) — 🖥️ DESKTOP **Run as Administrator** chạy lại
`scripts\setup_scheduled_tasks.ps1` thì mới ăn; (b) log bước brief nay in
`[brief] ⏱ ctx+prompt: Ns` + `[brief] ⏱ <agent>: Ns · ✅/❌ …` từng agent (#21a).
**22/09 đoạn log thô (01:00) — thủ phạm của cả #21:** bước brief mở 21:49, rồi 52
dòng `vnstock.core.utils.client - ERROR - API request failed: … iq.vietcap.com.vn …
Read timed out (read timeout=30)` liên tiếp tới 22:17 = 28′ trong 30,8′ của bước.
Đó là `_auto_refresh_events` → `vnstock_events.refresh_upcoming` gõ VCI cho VN30 ∪
movers (~52 mã) đúng đêm VCI ngã (updater đã phải rơi sang KBS), không có cửa dừng.
Đã vá (#21b, `refresh_upcoming` dừng sau 3 mã lỗi liền, giữ cache, không ghi đè
file khi 0 mã OK). Phần LLM chỉ ~2′; "+1 OK mà bản trắng" (#24) chờ dòng log từng
agent ở phát kế.
(3) Đêm 22/09 ladder DOWN: `python vnstock_llm_ledger.py --show --day 2026-09-22`
(tin Telegram cắt sau dòng flash-lite, chưa thấy OpenRouter/Groq đêm đó).
(4) ✅ LNH ON: `--diag` 01:20 fetch tươi in y hệt cache (28/09 ON 0,48 · 1W 6,20;
25/09 ON 0,87 · 1W 4,73; 24/09 ON 1,10 · 1W 5,06) ⇒ parse đúng, số của SBV. Vá ở
gauge (#19): ON và 1W phân kỳ > 1,5 điểm ⇒ `dir 0`, nhãn in cả hai số — chờ desktop
merge cùng đợt sau. **○ máy nào cũng được:** console.mistral.ai xem quota để biết
có bật lại giọng thứ tư không.

## 6. 💻 Laptop — merge + nâng vnstock 4.0.7 TRƯỚC desktop

✅ **Laptop ĐÃ merge** `claude/laptop-work-ono4qt` — full `3.158 passed / 161,8s`
tại `c969d6a`, rồi `--fast` **2.565 passed / 110,6s** tại `b04c908` (09/09,
vnstock 4.0.4). Laptop `main` = đầu nhánh.

🖥️ **DESKTOP CHƯA MERGE (tới 14/09 22:04) — brief tối 14/09 vẫn sinh bằng CODE
CŨ.** Lệnh merge nằm ở #0 bước 3. Làm **ngoài cửa sổ pipeline**: từ lúc task
Daily khởi động (18:00; máy tắt giờ đó thì `StartWhenAvailable` chạy bù ngay khi
bật máy — phát 08–14/09 đều khởi động ~20:15–20:40) tới dòng `⏱ TỔNG`
(~21:00–23:15). Brief đầu tiên có bản vá = phiên kế tiếp sau khi merge.

**📦 vnstock 4.0.8 đã ra (16/09; 4.0.7 ra trước đó) — cổng gỡ chặn 4.0.6 đã mở.** Đúng thứ tự:
1. 💻 Laptop TRƯỚC: `pip install vnstock==4.0.8` → `run.py doctor --net` +
   `run.py test` **ngay**.
2. Chạy vài ngày xem có gì lạ.
3. Sạch rồi mới đụng 🖥️ desktop, và **không nâng sát 18:00**.
4. Hỏng thì lùi: `pip install vnstock==4.0.4 vnai==2.4.8`.

Desktop giữ 4.0.4 — nó chạy phát tối, không phải chỗ để thử.
*(4.0.6 làm chết mọi lệnh gọi mạng — `env.py:136 UnboundLocalError`.)*

## 9. 📰 Cảnh báo TIN QUAN TRỌNG mỗi giờ → Telegram — ĐÃ CHẠY trên 🖥️ desktop 04/10 (#31)

### 📋 CÒN PHẢI LÀM — chốt 04/10 tối (news-alert + Bluesky)

**Việc của USER**

| # | Việc | Máy | Khi nào | Lệnh / cách làm |
|---|---|---|---|---|
| ~~U1~~ | ✅ **XONG 04/10** — đã merge bản vá **tin dư hết hạn sau 6h** (`d6c723c`) | 🖥️ DESKTOP | — | `git fetch origin claude/magical-dirac-yu672i` rồi `git merge origin/claude/magical-dirac-yu672i` |
| ~~U2~~ | ✅ **XONG 04/10** — đã xoá mật khẩu khỏi phiên + **thu hồi App Password** (lần sau cần thêm/bớt người thì tạo mới) | 🖥️ DESKTOP + app Bluesky | — | `Remove-Item Env:BSKY_APP_PASSWORD, Env:BSKY_HANDLE` · bsky.app → Settings → Privacy and security → App passwords → xoá |
| U3 | Để máy **bật, không ngủ** — 24/7 chỉ chạy khi máy thức (tắt/ngủ thì bật lại chạy bù 1 lượt, gom tối đa 36h) | 🖥️ DESKTOP | Một lần | Settings → System → Power → Sleep: Never |
| U4 | **Theo dõi số tin/giờ** vài ngày: hết tin tồn mỗi giờ nên 0–3 tin. Đều 6–8 tin vô giá trị ⇒ thêm `VNSTOCK_NEWS_ALERT_MIN_SCORE=4` vào `.env` (chỉ nhận ≥4/5) hoặc forward vài tin thừa cho Claude | 🖥️ DESKTOP / Telegram | 05–10/10 | `Select-String '\[news-alert\]' C:\vnstock\run_daily.log \| Select-Object -Last 12` |
| U5 | Thấy **một sự kiện bị gửi lặp** qua nhiều giờ (bài theo sau KHÁC tiêu đề — mới chặn bằng prompt) ⇒ forward 2–3 tin mẫu cho Claude | Telegram | Khi gặp | — |
| U6 | **Chấm lại List Bluesky sau FOMC cuối tháng 10** — Claude tự NHẮC lúc 08:00 CN 01/11 (Routine `trig_01GKctN7TFpWfc1Dr4f7GXqZ`) | 🖥️ DESKTOP | 01/11 | merge → `python scripts/bsky_eval.py` → `y` → dán output cho Claude → Claude sửa ⭐ → `bsky_make_list.py --write-env --prune` (App Password, nhập TỪNG DÒNG) |
| U7 | (Tuỳ) Nâng `vnii 0.2.6` / `vnstock-installer 3.1.3` — thử ở laptop TRƯỚC, `run.py test` xanh rồi mới desktop | 💻 LAPTOP → 🖥️ | Khi rảnh | lệnh `pip install --upgrade --extra-index-url https://vnstocks.com/api/simple …` in trong cảnh báo pytest |
| U8 | (Việc cũ, không thuộc news-alert) doctor ⚠️ — hướng dẫn 04/10 tối: (a) **PMI tháng 9 = 51,9** (Finhay `vn-pmi-manufacturing`; T8 53,3) ⇒ `python vnstock_macro.py --set pmi 51.9 --as-of 2026-10-01` · (b) 16 mã cách ly ⇒ `python scripts/rebase_ticker_history.py --from-drift-ledger --whole-series` (thử) → không có ✗ TỪ CHỐI thì thêm `--apply`; ✗ thì gửi Claude · (c) TPB thiếu bar 02/10 ⇒ `Select-String TPB data_warehouse\_meta\basis_drift_pending.json` — có thì (b) lo, không thì `--ticker TPB --explain` gửi Claude (#15) · (d) brief phân bổ tháng 10: `python run.py dashboard` → Tin tức → 🧭 Phân bổ → 📝 Tạo brief · (e) `python run.py doctor`. KHÔNG chạy (b)(c) khi task Daily đang chạy (T2–T6 18:00 → `⏱ TỔNG`) | ○ một lần (kho) — chạy ở 🖥️ | 04/10 tối | xem cột việc |

**LLM báo cáo vĩ mô (user hỏi 04/10):** digest báo cáo (`vnstock_report_digest.digest_call(step="digest")`, nút 🧠 tab Báo cáo / `python vnstock_report_digest.py --refresh`) ĐÃ đi Claude Code nấc đầu từ 30/09 (#26) khi `VNSTOCK_LLM_ENGINE=claude` (🖥️ desktop có; 💻 laptop thì tuỳ `.env`) — digest cũ trước 30/09 xem "via …" ở tab Báo cáo, chấm lại: `--refresh --redigest`. Brief PHÂN BỔ (nút 📝) trước đây chạy agent ladder (Gemini…) vì agent Claude Code tắt trong config — nay `_allocation_claude_lead` cho Claude Code làm lead khi engine bước brief = claude (ladder vẫn chạy kèm, lỗi CLI vẫn có bản). Báo cáo lãi suất tuần: KHÔNG dùng LLM.

**Việc của CLAUDE — chờ user gọi** (nói "làm #…" là chạy)

| # | Việc | Điều kiện |
|---|---|---|
| #32 | **Gửi im lặng ban đêm** 23:00–06:00 (trừ lô có tin 5/5) — thiết kế ở bảng cuối file | User gọi |
| ~~#33~~ | ✅ **XONG 04/10** — gỡ Yahoo Finance `rssindex` khỏi `_FEEDS` (11 feed còn lại), test ghim không thêm lại | — |
| — | Guard deterministic "cùng SỰ KIỆN đã gửi" cho bài KHÁC tiêu đề (hiện chỉ có luật prompt + guard tiêu đề gần trùng 0,85) | Khi U5 có mẫu |
| — | Trần RIÊNG cho nguồn Bluesky (hiện chung 6 bài/lượt, 18 lượt bắt bù) | Khi `--diag --sources bsky` thường > 6 bài mới/giờ |
| — | Đảo thứ tự luật `bsky_eval.verdict` (xét lạc đề TRƯỚC khi cho ⭐) | Chỉ khi tự động hoá việc chọn ⭐ — hiện Claude đọc bảng rồi mới chốt |


User hỏi 02/10: dùng Claude Code/Cowork kéo tin kinh tế-tài chính về Telegram
mỗi giờ được không. Ba đường đã cân (U67): **A** Task Scheduler + `run.py
news-alert` (CHỌN) · B Routine cloud (loại — đo lại 02/10 cloud vẫn 403
`api.telegram.org` + mọi feed, kho không lên cloud, mỗi lượt là một phiên Claude
Code) · C Cowork scheduled task (cùng ràng buộc máy mở như A mà kém tất định).

**Đường chạy** (`vnstock_news_alert.py`): registry `SOURCES` (11 feed RSS — Yahoo gỡ 04/10, #33 — lấy
thẳng từ `vnstock_news_feeds._FEEDS` — thêm feed ở đó là bước news lẫn cảnh báo
cùng thấy; adapter tin theo mã qua vnstock bật bằng
`VNSTOCK_NEWS_ALERT_TICKERS=VCB,HPG`; nguồn mới = một `Source(key, name, fetch,
kind, relevant)` hoặc `register_source`) → `normalize_item` → lọc liên quan từng
nguồn → tin đăng trong **3h** (`_published_at` mới thêm vào `parse_feed`) →
`deduplicate_news` + sổ `_meta/news_alert_seen.json` (7 ngày, trong kho ⇒
Dropbox lo chống trùng hai máy) → **Claude Code chấm 1–5 cả lô MỘT call**
`--json-schema` (engine `VNSTOCK_NEWS_ALERT_ENGINE` > `VNSTOCK_LLM_ENGINE`; hỏng
⇒ ladder free từng tin + mức độ từ từ khoá; không provider ⇒ KHÔNG gửi tin thô)
→ **≥ 3/5** gửi, ≤ 8 tin/lượt, dư để lượt sau không chấm lại → marker
`_meta/news_alert_status.json{machine, error, error_streak}` → badge doctor
**"Cảnh báo tin mỗi giờ"** (⬜ chưa chạy · ⚠️ lượt lỗi / >3h không lượt trong
khung giờ · ❌ lỗi ≥3 lượt liền). Không tin mới ⇒ im lặng, không gọi LLM. Không
đụng `market_news_cache.json`. Kill-switch `VNSTOCK_NEWS_ALERT=0` (doctor réo).
Nút vặn: `VNSTOCK_NEWS_ALERT_{HOURS=0-23, DAYS=1-7 (24/7 từ 04/10), MIN_SCORE=3, WINDOW_H=3,
MAX_SEND=8, MAX_SCORE=30, SOURCES, CLI_MODEL, CLI_TIMEOUT_S}`. Log:
`Select-String '\[news-alert\]' run_daily.log` (main() tee mọi lệnh).
**Model chấm: đặt `VNSTOCK_NEWS_ALERT_CLI_MODEL=claude-sonnet-5-5` trong `.env`
desktop** — A/B 04/10: Sonnet 13s/$0,04 vs Opus 29s/$0,11 mỗi lượt, điểm lệch
±1 ở 2/7 tin chung (U68). Không đặt ⇒ ăn Opus mặc định của CLI (~16 lượt/ngày,
trừ chung hạn mức gói Claude với phiên code).

> 💤 **Để dành (#32):** gửi IM LẶNG ban đêm 23:00–06:00 (trừ tin 5/5) — user 04/10 hẹn làm sau; thiết kế ở bảng việc của Claude.

**🖥️ DESKTOP — 2 bước (tài khoản chạy task `admin`, venv đã kích hoạt):**
1. Merge code: `git fetch origin claude/magical-dirac-yu672i && git merge
   origin/claude/magical-dirac-yu672i` rồi `python run.py test --fast`
   (whitelist có `tests/test_news_alert.py`, +71; sandbox thiếu `vnstock` nên chỉ
   đo được 2.748 passed, 33 fail đều là ModuleNotFoundError — U67 (d)). Thử tay
   TRƯỚC khi đăng ký:
   `python run.py news-alert --diag` (từng nguồn: thô/lọc/3h/mới nhất/giây — ❌ ⇒
   sửa URL hoặc `enabled: False` trong `_ALERT_FEEDS`, dán kết quả cho Claude),
   `python run.py news-alert --dry-run --force` (in tin sẽ gửi, không gửi, không
   ghi sổ; `--force` bỏ cửa khung giờ) rồi `python run.py news-alert --force` một
   lần để nhận tin thật trên Telegram. Lượt đầu chỉ xét tin 3h qua nên không dội.
2. Đăng ký task thứ ba: Run as Administrator **trong shell đã kích hoạt venv**
   `.\scripts\setup_scheduled_tasks.ps1` (script tự thay 2 task cũ, thêm
   `VnStock News Alert` mỗi giờ 24/7 kể cả CN (từ 04/10; bản 02/10 là 07–22h T2–T7), trần 15′;
   đổi khung: `-NewsAlertStart 08:00 -NewsAlertEnd 20:00 -NewsAlertDays Monday,Friday` +
   `VNSTOCK_NEWS_ALERT_HOURS/DAYS` trong `.env` cho khớp; không muốn: `-NoNewsAlert`).
   Kiểm: `Get-ScheduledTask -TaskName 'VnStock *'` phải ra **3 task**. 💻 LAPTOP
   KHÔNG chạy script này (gửi đôi tới khi Dropbox sync sổ).

**User chốt 02/10 sáng:** chỉ tin THỊ TRƯỜNG / VĨ MÔ quan trọng; adapter tin theo
mã (nguồn 2) ĐỂ TẮT — không đặt `VNSTOCK_NEWS_ALERT_TICKERS`. Prompt chấm đổi theo:
tin riêng một doanh nghiệp (kể cả VN30) mặc định mức 2, chỉ lên 4 khi đổi kỳ vọng
cả ngành/thị trường (test ghim `test_score_prompt_is_macro_first_company_news_capped`).
Khử trùng chéo nguồn 1↔2 vì thế KHÔNG cần — hai nguồn không trùng bài (nguồn 2 là
bài Vietstock gắn mã, nguồn 1 không có feed Vietstock), chỉ có thể trùng sự kiện.

**Mở rộng 02/10 trưa (U68) — báo nước ngoài + mạng xã hội, user hỏi "lấy tin
báo nước ngoài / phân tích từ X được không":**
- **Cửa sổ bắt bù qua đêm (#32):** lượt 07:00 tự nới cửa sổ tới `covered_until`
  của lượt trước + 1h (trần 36h, `VNSTOCK_NEWS_ALERT_MAX_CATCHUP_H`) — tin Fed 01:00
  VN không rơi mất; lô chấm nở theo (tối đa ×2 trần 30, ≤ 6×3 tin/nguồn).
- **20 nguồn nước ngoài RIÊNG cho cảnh báo** (`_ALERT_FEEDS`, không vào `_FEEDS` ⇒
  brief không đổi): Bloomberg Markets/Economics · WSJ Markets/World (host MỚI
  `feeds.content.dowjones.io` — host cũ `feeds.a.dj.com` ĐÓNG BĂNG 01/2025 dù vẫn
  200) · FT Markets · MarketWatch Bulletins · CNBC World/Asia · investingLive
  (ForexLive) · OilPrice · Nikkei Asia (lọc `_relevant_en`, từ khoá có BIÊN TỪ);
  Fed monetary / BLS / BEA (chính thức, không lọc, prompt chấm ≥4 cho dữ liệu);
  6 Google News `when:2d`: `site:reuters.com`, Fed, Vietnam macro + VN-Index/FTSE
  Russell, Oil, China, Treasuries/USD. CNBC/MarketWatch/Yahoo trong `_FEEDS` nay
  cũng lọc `_relevant_en`. Mỗi nguồn ≤ 6 tin/lô, fetch có tường 45s
  (`VNSTOCK_NEWS_ALERT_FETCH_BUDGET_S`). **URL là ứng viên — sandbox không fetch
  được**: `python run.py news-alert --diag` in thô/lọc/3h/mới nhất/giây từng
  nguồn, ❌ thì sửa hoặc `enabled: False`.
- **Bluesky (đường chính cho "phân tích chuyên gia", miễn phí, sạch ToS):** danh
  sách gợi ý **140 tài khoản / 6 mảng, nhóm ⭐ xuất phát 24 — ✅ List ĐÃ TẠO 04/10 (24/24, URL trong `.env` desktop, `--diag` ✅)** (`--check` 04/10 bỏ 6 tài khoản ngừng đăng, 3 hãng tin thành ⛔) đã khảo sát 02/10 ở
  `docs/bluesky-macro-list.md` (mỗi handle kèm URL bằng chứng + độ tin cậy; bẫy tài
  khoản giả ghi ở ghi chú từng mảng). **Không cần thêm tay**: tạo App Password
  (Bluesky → Settings → Privacy and security → App passwords), rồi 🖥️ DESKTOP
  `python scripts/bsky_make_list.py --check` (xác minh handle, không đăng nhập) →
  `python scripts/bsky_make_list.py --write-env` (tạo List, thêm nhóm ⭐, ghi `.env`;
  chạy lại an toàn, chỉ thêm người chưa có; `--all` = cả bảng trừ độ tin cậy thấp và ⛔). Muốn đọc thử cả bảng để chọn người: `--browse` tạo List RIÊNG "Vĩ mô — đọc thử (đầy đủ)" (86 người sau khi `--check --browse` 04/10 ⛔ 45 tài khoản giả/rỗng/ngừng đăng/báo lớn — ✅ ĐÃ TẠO 04/10, 86/86, user Pin to home; **✅ ĐÃ CHẤM 04/10** (`bsky_eval.py`, 541 bài, ~$0,8): ⭐ +8/−8 (vẫn 24), List đọc thử ⛔ 17 (còn 69) — chi tiết đầu `docs/bluesky-macro-list.md`. **✅ ÁP 04/10 trên 🖥️ desktop:** List cảnh báo +8/−8 (24), List đọc thử −17 (69), 0 lỗi; `.env` không đổi (cùng URL List — lượt giờ kế tiếp tự đọc danh sách mới). Chấm lại sau FOMC cuối tháng 10 (tuần mẫu không có họp Fed), `johnauthers` tên trống đã xác minh tay là THẬT 04/10), không đụng `.env` (gộp vào List cảnh báo thì suất 6 bài/lượt rơi vào người đăng nhiều nhất).
  Hoặc tay: tạo List trong app, thêm nhóm ⭐, rồi `.env`:
  `VNSTOCK_NEWS_ALERT_BSKY_LIST=https://bsky.app/profile/<handle>/lists/<rkey>`
  (hoặc `VNSTOCK_NEWS_ALERT_BSKY_HANDLES=a.bsky.social,b.bsky.social`). Một call
  `getListFeed`/giờ, ≤3 bài/người, bỏ bài <60 ký tự; prompt chấm bình luận theo
  giá trị phân tích, tối đa 4.
- **X (chỉ khi muốn, có key):** `VNSTOCK_NEWS_ALERT_X_HANDLES=setser,brentdonnelly`
  + MỘT trong hai: `TWITTERAPI_IO_KEY` (twitterapi.io, $0,15/1.000 tweet ≈ $1–5/tháng,
  VÙNG XÁM ToS — rủi ro ở nhà cung cấp) hoặc `X_BEARER_TOKEN` (X API trả theo lượt
  đọc $0,005/post từ 06/02/2026, sạch ToS, ≈ $10–15/tháng cho ≤10 tài khoản;
  `since_id` lưu `_meta/news_alert_x_state.json` để không trả tiền hai lần).
  Ép provider: `VNSTOCK_NEWS_ALERT_X_PROVIDER=twitterapi|official`. Một call tìm
  kiếm `from:a OR from:b` mỗi giờ. KHÔNG dùng Nitter/RSSHub/Grok x_search (lý do U68).

**Đo thật 02/10 tối (🖥️ desktop):** `--fast` 2.862 passed; `--diag` 30/32 nguồn ✅. ForexLive + BLS ❌ ⇒ tắt (BLS thay bằng Google News "GN US data"); Báo Chính phủ + Nikkei không đọc được ngày ⇒ vá bộ đọc ngày + lấy giờ thấy lần đầu (U68). Thử URL feed mới: `python run.py news-alert --diag-url <url>`.

**Phép đo sau 1 ngày:** `python run.py doctor` badge "Cảnh báo tin mỗi giờ" ✅
kèm `N gửi · engine claude`; `python vnstock_llm_ledger.py --show` dòng
`ClaudeCode` ~10–15 call/ngày; Telegram ≤ ~8 tin/giờ. Nhiễu quá ⇒
`VNSTOCK_NEWS_ALERT_MIN_SCORE=4`; im quá ⇒ `=2`. Muốn nguồn mới: một dòng
`_FEEDS` (RSS) hoặc một `Source` + `register_source` (API/scraper).

---

# 🔔 MÁY TỰ NHẮC — không phải việc gõ tay

Chạy `python run.py doctor` và chỉ **nhìn badge**. Vàng ở đây thường là dấu
hiệu guard đang LÀM VIỆC, không phải hỏng.

| Badge | Khi nào gọi Claude |
|---|---|
| **Sổ theo dõi nghi ngờ brief** | ⚠️ ĐỦ mẫu 29/09 (Op.CF/vốn hoá KBC·PVC ×9) — **đã quyết 29/09: số THẬT** (BCTC Finhay: KBC OCF TTM −16.510 tỷ, PVC −462 tỷ; ngưỡng 0,5× vốn hoá bắt đúng BĐS/vốn hoá nhỏ chứ không bắt lỗi đơn vị) ⇒ 🖥️ desktop xoá `data_warehouse\_meta\brief_watch.json` để đếm lại; nếu lại đủ mẫu cùng mã ⇒ nâng `OCF_SCALE_NOTE` hoặc bỏ phép đo này (việc của Claude, nói "làm đi"). Câu dòng tiền ngoại ngược data chưa lần nào ghi. |
| **Hiệu suất auto-heal** | `⚠️` = 0 lành dù đủ mẫu ⇒ quyết hạ trần `VNSTOCK_AUTOHEAL_BUDGET_S=120` hay tắt hẳn |
| **Lệch cơ sở — mã bị cách ly** | **29/09 21:14 chữa 44/45** (`--from-drift-ledger --whole-series --apply`, VCI khoẻ; VN30 TCX 1,2× · PVS 1,2× · VPB 1,2603× · GAS vách 21/09 đã liền; SZL lệch đều 1,7889× lấy nguyên nguồn; CMP kho đứng từ 01/12/2025 — đuổi kịp ở sync kế; XHC hệ số đo trên 1 bar, chỉ 5 bar cũ nhân hệ số). **FPT chữa 22:39** bằng `--ticker FPT --break-date 2026-05-28 --apply`: `--whole-series` từ chối ĐÚNG vì hai đợt quyền trong một năm (Finhay: cổ tức tiền 1.000đ GDKHQ 28/05/2026 ⇒ bậc 1,0137; cổ phiếu thưởng 10:1 GDKHQ 21/09/2026 ⇒ 1,10 trọn chuỗi; 1,10 × 1,0138 = 1,1152 khớp trung vị). Chạy thử đạt cả ba điều kiện: probe tại vách 1,0138× (20 bar trước · 22 sau), `nguồn phủ từ 2006-12-13` (4.931 bar), **4.924 bar lấy thẳng nguồn · 0 nhân hệ số** — `last_divergent_day` thấy bar lệch cuối 18/09 nên kéo mốc cắt tới 19/09, một lượt xử cả hai bậc. Khối lượng giữ nguyên (nguồn/kho 1,0000×, cổ tức tiền không đổi số CP). 21 file nguyên tử, sao lưu `_meta/backup_rebase/FPT_20260929-223915`. Tool KHÔNG nối bar mới ⇒ `python vnstock_updater.py --tickers FPT` (không `--skip-if-done`, không đụng marker) nối 7 bar 19→29/09; `--explain` sau đó: 4.931 bar, đứng 0 ngày, 1,0000×/spread 1,0000, SẠCH. Chi tiết U59. ⚠️ Bẫy PowerShell: output qua ống `\|` phải đặt `$env:PYTHONUTF8='1'` + `[Console]::OutputEncoding=UTF8`, không thì Python chết im ở dòng đầu (UnicodeEncodeError vào ống, màn hình trống). | Có mã mới ⇒ `python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series` (chạy thử) rồi thêm `--apply`. Mã bị từ chối ⇒ `--ticker <MÃ> --explain` |
| **Nới OHLC (bar tự mâu thuẫn)** | Nới sát trần 20% ⇒ soi lại bar đó |
| **Rổ VN30** | `⚠️ rổ thật đã đổi` ⇒ dán dòng badge cho Claude |
| **Phát tối — đã tới kho này chưa** | ⚠️ `CHƯA tới kho này` ⇒ ⇄ CẢ HAI kiểm icon Dropbox ở khay TRƯỚC, rồi 🖥️ DESKTOP `Get-ScheduledTaskInfo -TaskName 'VnStock Daily Pipeline'` + đuôi `run_daily.log`. ⚠️ `brief chiều CHƯA` (chỉ hiện từ sáng hôm sau) ⇒ 🖥️ DESKTOP soi `[brief]` trong log; gửi tay ○ MỘT LẦN `python run.py telegram close`. Badge do pipeline tự ghi (bước 13) luôn chụp TRƯỚC brief ⇒ ghi "đang tới … xét lại từ sáng mai" là bình thường; muốn thấy "đã đẩy" thì chạy `python run.py doctor` tay (trong giờ pipeline chạy thì `python vnstock_doctor.py --no-save` để không đè badge). Caption badge nay ghi MÁY nào khám. |
| **Cảnh báo tin mỗi giờ (news-alert)** | ⬜ = task chưa đăng ký (mục 9). ⚠️ `>3h không có lượt mới` (24/7 từ 04/10 — máy tắt/ngủ cũng réo) ⇒ 🖥️ DESKTOP `Get-ScheduledTaskInfo -TaskName 'VnStock News Alert'` (máy tắt? task tắt? Dropbox tắt?). ⚠️ `mọi nguồn đều rỗng` ⇒ mạng/feed: `python vnstock_news_feeds.py --diag`. ⚠️ Telegram/Claude lỗi ⇒ `run.py telegram test` / `vnstock_brief_pack.py --check`. ❌ lỗi ≥3 lượt liền ⇒ dán dòng badge cho Claude. Caption ghi MÁY nào chạy lượt. |
---

# 🟠 VIỆC CỦA CLAUDE — nói "làm đi" là chạy

| # | Việc | Trạng thái |
|---|---|---|
| ~~1~~ | **Pivot THẬT cho mốc watchlist** | ✅ **XONG 26/08** — `ticker_sr_levels` (pivot 60 phiên, bỏ 2 bar cuối, có 3 sàn nhiễu). Thiếu vế nào thì NÓI là thiếu, không bịa. *(Recon lật kế hoạch: `_ticker_pivots` là hàm SAI — trả chuỗi, làm tròn 1,2%, không sàn nào.)* |
| ~~2~~ | **`screener` 1.318s** | ✅ **XONG 26/08** — nó quét kho **14 lần y hệt nhau** (14 preset, filter chỉ áp SAU khi đã đọc + tính). Nhớ chỉ báo ⇒ 14 lượt → 1. |
| ~~3~~ | **`fix-units` 316s** | ✅ **XONG 26/08** — lọc bằng **thống kê footer parquet** (tương đương chứng minh được, không thêm state), + chỉ giải nén `time`/`close`. |
| ~~1~~ | **Vòng lặp Net BS** | ✅ **XONG 26/08** — song song có nhịp (8 luồng, tổng tốc độ chặn ở 8 req/s < quota 10). Kỳ vọng ~650s → ~125s. |
| ~~5~~ | **`--whole-series` — chữa lớp lệch ĐỒNG ĐỀU** | ✅ **XONG 26/08** — U42 mới chỉ làm công cụ *từ chối trung thực*; nay có đường chữa thật. Cửa vào KHÔNG phải `_probe` (nó luôn phán `aligned` vì trước = sau) mà là `uniform_offset_report`, chặt hơn: tỉ lệ phải **ổn định**. Thêm bước tự kiểm thứ 3 đo MỨC — hai bước cũ đều đo đạo hàm nên mù đúng lớp lỗi này. Xem U43 · việc user: **#5** |
| ~~4~~ | **Đường CafeF `cash-dividends`** | ✅ **XONG 26/08** — soi ra chuyện lớn hơn: cái nó nuôi (`load_recent_exdiv`, bộ chặn cờ "phân phối" giả) **chạy chay từ 19/08**, im lặng. Nối sang sổ đăng ký → badge xác nhận `registry trả 1 mã` → **xoá hẳn** cả đường ghi lẫn đường đọc. Xem U36 |

| ~~6~~ | **Impact tin bị cắt CỤT** | ✅ **XONG 09/09** — `chat_complete_ex`/`anthropic_complete_ex` (`vnstock_sentiment`) đọc `finish_reason`/`stop_reason`; bị cắt ⇒ gọi lại ĐÚNG nấc đó **một lần** với trần ×3, trả cờ `truncated`. `analyze_item` gặp cờ ⇒ trả `('','')` = **không cache**, lượt refresh sau chấm lại. Bản cũ `chat_complete`/`anthropic_complete` là wrapper, chữ ký không đổi. Xem U55 |
| ~~7~~ | **`term_spread` không có vùng chết** | ✅ **XONG 09/09** — `_GAUGE_NOISE_BAND = 0.10` dùng chung `term_spread` + `intl_spread`: âm dưới 10 bp ⇒ nhãn "mỏng — sát 0 (… chưa tính ÂM)", `dir=0`; **−0.10 vẫn là ÂM** (data 03/07 giữ nguyên). Với data close 08/09, sub-score `term` của band phân bổ về 0 thay vì −0.5 (điểm −0.12 → −0.07). |
| ~~8~~ | **Header prompt lọt ra brief** | ✅ **XONG 09/09** — guard `enforce_no_header_scaffold` (`_guards_text`, nối sau `enforce_no_instruction_leak`): cắt "(N dòng/câu)" / "(… optional)" ở CUỐI dòng header (`##`/emoji mục/nhãn đậm); câu nội dung có ngoặc để yên. |
| ~~9~~ | **"Sự kiện sắp tới" brief CLOSE tính cả hôm nay** | ✅ **XONG 09/09** — `_upcoming_window_start(brief_type, data_date)`: brief chiều mở cửa sổ từ **ngày kế tiếp** phiên đã đóng; brief sáng giữ hôm nay. Có lưới nối dây (`test_collect_context_wires_the_window_start_into_load_upcoming`). |
| ~~10~~ | **`pp` khi 2 số lẻ, khi 3** | ✅ **XONG 09/09** — chốt **3 số lẻ** (không phải 2 như ghi hôm qua): ngưỡng lead/lag 0.05pp nằm ở số lẻ thứ 2, in 2 số lẻ thì "+0.05pp < 0.05" tự đá nhau. Đổi đúng một chỗ: header khối ngành `vnstock_brief.py` `:+.2f` → `:+.3f`. |

| ~~11~~ | **Doctor: "phát tối chưa tới kho này" là một badge riêng** | ✅ **XONG 16/09** — `check_pipeline_reach` (hàm thuần `pipeline_reach_verdict`, `now` cắm được; `vnstock_doctor.py`) đọc `pipeline_status.json[updater]` + `brief_push.json`. Ba luật rút từ vòng phản biện 3 góc nhìn: (1) sync so **phiên PHỦ** (`covered_session`; marker cũ suy từ giờ chạy với mốc 15:05), không so ngày lịch; (2) **cùng đêm không bao giờ kết luận "brief chưa"** — doctor bước 13 luôn trước brief bước 14, kết luận đó ghi vào `doctor_status.json` là sai suốt 24h ở CẢ HAI máy; brief chỉ xét từ sáng hôm sau, cửa sổ 150′ cho chạy bù ngày khác; (3) hạn phát tối **23:00** (máy bật muộn xong tới 23:15), sáng hôm sau verdict không đổi. ⚠️ "CHƯA tới kho này" nói cả hai nguyên nhân (pipeline không chạy / Dropbox tắt sync) + hedge máy bật muộn, nghỉ lễ, chạy bù T7 code cũ. Cờ `VNSTOCK_PIPELINE_BRIEF=0` là theo MÁY (.env không đồng bộ) ⇒ `cmd_brief` ghi `skipped` vào marker chung để máy kia không réo giả. `doctor_status.json` + caption sidebar có `machine`. Test: `tests/test_doctor.py` (+21, có parity `_session_for` ↔ `run._close_session_date`, `_BRIEF_OFF` ↔ `_OFF_VALUES`). |
| ~~14~~ | **Đường chạy bù (StartWhenAvailable): marker so NGÀY LỊCH** | ✅ **XONG 16/09** — hai lỗ hổng: (1) máy tắt 18:00 T2, bật 08:20 T3 ⇒ sync bù lấy bar tới T2 nhưng đóng dấu ngày T3 ⇒ task 18:00 T3 "✓ đã chạy hôm nay" bỏ sync, bar T3 chờ tới T4, brief chiều T3 dựng trên bar T2; (2) chạy bù T7 ⇒ updater bỏ qua cuối tuần (không `--force`) mà brief T6 vẫn đẩy (luật 15/08) trên bar T5, bar T6 chờ tới T2. Vá: `vnstock_rollup.session_covered_at(now)` (trước 15:05 = phiên trước; T7/CN = T6; mốc PHẢI KHỚP `vnstock_brief.SESSION_CLOSE_CUTOFF`, có test canh), marker updater/rollup ghi `covered_session`, `is_already_done_today(job, now)` so trường đó (`marker_covered_session` đọc được marker cũ qua `last_run_at`); rollup mặc định cuộn phiên PHỦ (chạy bù sáng cuộn bar 1m hôm qua, T7 cuộn T6); `run.py sync` thêm `--force` cho updater T7/CN (chỉ tắt `skip_weekends`, không gì khác). Test: `test_pipeline_status_gate.py` (+6, hai timeline đều fail trước/pass sau), `test_run_pipeline.py` (+2). **Phép đo: lần chạy bù kế tiếp** — 🖥️ DESKTOP dán `run_daily.log` đoạn `[run.py] $ ... vnstock_updater.py` (T7/CN phải có `--force`), dòng `✓ Updater đã phủ phiên ...` nếu bị bỏ qua, và `_meta/pipeline_status.json` (trường `covered_session` phải là phiên TRƯỚC khi chạy sáng). |

| ~~12~~ | **Marker updater câm đêm fallback** | ✅ **XONG 15/09** — `updater_status_update(stats, today, now, machine)` (hàm thuần, `vnstock_updater.py`): lỗi = 0 ⇒ `success` như cũ; lỗi > 0 ⇒ `last_result: "partial"` + `last_partial_date` + `errors` + `fallback` + `tickers_updated`, **không đụng `last_success_date`** ⇒ `is_already_done_today` vẫn không coi lượt hụt là xong. Console in `partial: N lỗi · F mã qua KBS`. Test: `test_pipeline_status_gate.py` (+2). |
| ~~13~~ | **Tỉa ladder LLM — 29/66 call lỗi đêm 14/09, brief 754s** | ✅ **XONG 15/09** — hai lưới: (1) **cầu dao tài khoản** `vnstock_llm_ledger.provider_blocked_today(provider)`: hôm nay có lỗi 401/402/403 và CHƯA call nào OK ⇒ brief agent (base/Cerebras/OpenRouter), sentiment `_call_provider` + `chat_complete_ex`, digest `_call_free` đều BỎ nấc đó trong ngày (Cerebras 402 hết tốn 4 call/đêm); 429/5xx/timeout KHÔNG chặn (Gemini dính 429 sáng vẫn được gọi chiều). Kill-switch `VNSTOCK_LLM_BREAKER=0`. (2) **OpenRouter** không đi hết danh mục `:free` nữa: `_MODEL_FALLBACKS = [nemotron-3-ultra-550b:free]` (slug đã sống trong code — không thêm slug chưa probe), `_MAX_CANDIDATES = 3`, danh mục chỉ để BỎ slug đã biến mất; **429 ⇒ dừng** (quota theo KEY, 50 req/ngày), chỉ 404/5xx mới sang model kế. Groq qwen 413 đã có `_BRIEF_AGENT_DISABLES`. Đã khai vào cả hai lưới `_all_live_slugs` + `_ladder_slugs`. Test: `tests/test_llm_breaker.py`. **Phép đo 15/09: ledger 34 call · 9 lỗi (từ 66/29), không còn chuỗi OpenRouter cụt, Cerebras 1 call (cầu dao ăn) — NHƯNG brief close TRẮNG** vì (a) bộ lọc "có trong danh mục" bỏ nhầm nemotron-ultra (danh mục /models cắt trang 400, ultra sống: digest 2/2 OK) nên super cụt ×2 là hết nấc; (b) Gemini flash 429 rồi 503 hai lượt cách vài giây, base agent không đợi; (c) Mistral quota, Cerebras 402. **Vá tối 15/09:** bỏ hỏi danh mục (`_candidates` chỉ = chính + dự phòng chọn tay); `_OpenAICompatAgent.generate` thành vòng ứng viên: 429/5xx ⇒ đợi `_TRANSIENT_RETRY_S`=20s gọi lại ĐÚNG model một lần ⇒ sang `_MODEL_FALLBACKS`; cụt ⇒ sang dự phòng ngay; 401/402/403 dừng hẳn. Gemini có `_MODEL_FALLBACKS=[flash-lite]`. Lưới gom fallback qua `AGENT_REGISTRY`. Test 28. Desktop merge `661b193` + `--fast` 2.591 passed / 86s tối 15/09. **Đo 20:41 (`telegram close --force`): brief CÓ AI Outlook.** Ledger 19:12→20:41: +6 call · +1 OK · +5 lỗi = flash 503 → đợi 20s → OK (nguồn brief) · Cerebras 0 call (cầu dao ăn) · flash-lite 0 call (không cần) · Mistral 429 ×2 (đợi rồi gọi lại, đúng thiết kế) · super cụt → **ultra ĐƯỢC gọi nhưng cũng cụt** (`finish_reason=length` ở 2.800 token — ultra 2/2 OK cho digest ngắn, brief thì không; 14/09 super còn 2/3 OK ⇒ cụt là chuyện dài/ngắn bản brief, không phải slug chết). Dự phòng OpenRouter vì thế CHƯA gánh nổi brief — xem 4c. **Còn đo: brief tự động 16/09 phải CÓ AI Outlook; ledger có dòng flash-lite chỉ khi flash hỏng cả hai lượt.** |

| 15 | **Cửa KBS 8% từ chối thì phải VÀO SỔ cách ly** | 🟠 MỚI 16/09 — đêm VCI timeout, mã đi đường KBS: `reconcile_fallback_df` lệch >8% ⇒ `status="error"` "khác adjustment basis? — giữ kho cũ" (`vnstock_updater.py` ~L526), CHỈ đếm vào `❌ N lỗi`, **không `record_drift`** ⇒ badge Lệch cơ sở mù, mã đứng im tới khi có người soi. Nguy hiểm đúng ngày GDKHQ lớn rơi vào đêm VCI ốm (TCX 17/09 chia 20% ⇒ lệch ~16,7% > 8%): VN30 đóng băng mà doctor xanh. Vá: nhánh fallback từ chối vì lệch cơ sở ⇒ gọi `bg.record_drift` với ratio đo được (kèm `source=kbs`), giữ `status=error` như cũ; test ở `tests/test_price_fallback*.py`. Đo: đêm KBS kế tiếp badge phải liệt kê mã bị KBS từ chối. |

| 16 | **rebase: ca HAI BẬC trong một năm (cổ tức tiền + thưởng)** | 🟠 MỚI 29/09 — FPT: `--whole-series` từ chối vì 33% bar khác trung vị, `--explain` chỉ in 12 bar đuôi nên phải tra lịch quyền bằng tay (Finhay) mới biết vách 28/05. Hai việc nhỏ trong `scripts/rebase_ticker_history.py`: (a) `--explain` in **PHÂN ĐOẠN** tỉ lệ kho/nguồn theo thời gian (hàm thuần gom bar liên tiếp cùng tỉ lệ ±1,2%: `29/09/25→27/05/26: 1,1151× (161 bar) · 28/05→18/09: 1,1000× (81 bar)`) ⇒ đọc ra ngày vách và số đợt ngay; (b) `--whole-series` cho ca **nhiều bậc** khi `nguồn phủ từ ≤ bar đầu kho`: mọi bar đều lấy thẳng nguồn, `0 nhân hệ số`, nên hệ số không đồng đều cũng không 'bôi cái sai' — chỉ từ chối khi còn bar ngoài vùng phủ. Test: `tests/test_rebase_whole_series.py` (+ ca hai bậc phủ trọn / không phủ trọn). (c) câu `⚠️ còn bậc SAU vách … (mã bị rebase nhiều lần)` (`rebase_ticker_history.py:1132`) phải nói thêm 'hoặc có ĐỢT QUYỀN THỨ HAI sau vách' — FPT 29/09 là ca này, chữ cũ làm người đọc đi tìm lượt rebase không có. Mùa quyền nào cũng có VN30 dính ca này (FPT, VNM…). **Ca FPT 29/09 đã chữa xong bằng `--break-date` (U59) — việc này chỉ còn là tiện tay cho lần sau.** |
| ~~17~~ | **Slug chết + 4 lỗi brief soi 16–29/09** | ✅ **XONG 29/09 khuya** (chờ desktop merge). Groq `qwen/qwen3.6-27b` 404 "does not exist", Cerebras `gemma-4-31b` archived — model watch réo 19/09 + 26/09, không ai ở nhà. qwen → `openai/gpt-oss-120b` (Groq, slug sống ở digest bậc 2 từ 22/07, watch 26/09 không réo) tại `_ANALYZE_MODELS` · `_CLASSIFY_MODELS` · `_FREE_TIER2` (gỡ dòng) · `_DEFAULT_AGENT_CONFIGS` · `GroqAgent` · `_BRIEF_AGENT_DISABLES` (413 là trần tier, giữ tắt) · `_MODEL_MIGRATIONS` (+ llama-3.3-70b đổi đích); gemma gỡ khỏi `vnstock_sentiment._PROVIDERS` (thang còn 2 nấc, 22/09 tốn 10 call/ngày 404 vì cầu dao không chặn 404) và Cerebras `_MODEL_FALLBACKS`. `_DEAD_SLUGS` +2. Bốn guard/vá: `enforce_watchlist_levels` (mốc sai chiều hoặc cách mốc kích hoạt >25% → bỏ setup; ô mẫu "mục tiêu về thấp hơn" → cắt), `enforce_no_price_scaffold` ("(Giá X từ data)"), `enforce_rec_line_format` (`BUY entry=…` → "MUA vùng · chốt lời · cắt lỗ"), `vnstock_macro` ba gauge `+ 0.0` (hết `-0.00`). Test: `tests/test_brief.py` +4, `tests/test_macro.py` +1, ladder/sentiment/classifier sửa theo. Fast 2.640 passed. |
| ~~27~~ | **Guard #17 trượt biến thể của Claude (tin 290)** | ✅ **XONG 30/09 chiều** — `enforce_rec_line_format` bắt `- MSN BUY entry=68.7 · TP=74.6 · SL=65.6 (~1,400 cp, rủi ro 1% NAV).` (không dấu hai chấm, ngăn `·`, đuôi KL gợi ý giữ lại) và bỏ nhãn `(Strategy #69, conf …)` ở mọi dòng; test bằng chính 3 dòng tin 290. Hội đồng 10 agent chốt **4★** (U64; lệnh `--rate <id> 4 "…"` sẵn ở đó) — điểm trừ chính do Claude: nhãn `(Strategy #69, conf …)` tự gom, FRT hai bộ mốc trong một tin, EIB/SSI không mốc. |
| ~~28~~ | **Guard khung NN trượt dòng Danh mục tin 290** | ✅ **XONG 30/09 chiều** — `enforce_nn_frame_labels` không bắt `ngân hàng bị NN bán ròng mạnh nhất (-2,536 tỷ)` (tên ngành chữ thường, cách số 27 ký tự > cửa sổ 18) ⇒ số tuần đứng không khung cạnh `NN ròng toàn thị trường 1D -380 tỷ`. Nay IGNORECASE + cửa sổ 40, trong ngoặc gắn `, 1 tuần`. Test bằng đúng dòng EIB. Hội đồng chấm tìm ra (U64). |
| ~~29~~ | **Phát 30/09 dừng ở bước test (rc=2) — không brief** | ✅ **XONG 01/10 rạng sáng** — `test_analyze_models_slugs_22_07` (`tests/test_news_analyze_route.py`, NGOÀI whitelist) còn ghim `qwen/qwen3.6-27b` mà #17 đổi 29/09 ⇒ lần full đầu sau #17 đỏ, pipeline dừng trước audit/train/reflection/brief. Vá test + đưa file vào whitelist (fast 2.773, full 3.359; `.env` engine Claude vô can). ✅ 🖥️ desktop đã merge `ceddbfb`, full **3.359 passed / 101s** (01/10 ~02:30). Phiên 30/09 đã bù ~02:45 bằng đường A (`claude-cli: 56s · 5,636 ký tự`): `--rate 913 4 …` rồi `python run.py telegram close --engine claude --force`. **Chờ user:** test đỏ có nên chặn brief? (U65) |
| ~~30~~ | **Validator VNINDEX báo hallucinate GIẢ — năm trong ngày ISO của headline tin** | ✅ **XONG 01/10 sáng** (Claude Code desktop `49c78d6`, gộp về nhánh Claude `7da5a4a`) — `validate_brief_factuality` quét số 800–2500 trên dòng có 'VN-Index'; dòng tin canon `- ⚪ [2026-10-01] Lãi suất và VN-Index…` ⇒ đọc 2026 thành chỉ số ⇒ log 'VNINDEX ≈ 2,026 (+14.6%) → khả năng hallucinate' cho #914 dù brief ghi 1,768.62 đúng. Chỉ cảnh báo, không chặn gửi; réo với MỌI engine khi headline có 'VN-Index' + ngày 2026. Vá: strip `\d{4}-\d{2}-\d{2}` trước khi quét ở cả hai điểm; 2 ca test. Fast 2.773 · full 3.359. Còn hở: năm trần ('VN-Index năm 2026') vẫn lọt — chờ thấy mới vá. #914 chấm 4 sao (U66). |
| 31 | **Cảnh báo tin quan trọng MỖI GIỜ → Telegram (news-alert)** | ✅ **CHẠY THẬT 04/10** (🖥️ desktop merge `a0bd94a`, `.env` `VNSTOCK_NEWS_ALERT_CLI_MODEL=claude-sonnet-5-5`, task đăng ký; còn: soi lượt tự động 07:00 05/10 + vài ngày xem bài theo sau KHÁC tiêu đề có lặp không — U68) — `vnstock_news_alert.py`: registry nguồn (12 RSS từ `_FEEDS` + adapter tin theo mã) → cửa sổ 3h → sổ đã-thấy → Claude chấm 1–5 theo lô → ≥3 gửi ≤8 tin, dư lượt sau · `run.py news-alert` · task thứ ba trong `setup_scheduled_tasks.ps1` · badge doctor + kill-switch `VNSTOCK_NEWS_ALERT` · `parse_feed` thêm `_published_at` · 71 test (U67, U68). Routine cloud đo lại 02/10 vẫn 403 ⇒ loại. **Mở rộng 02/10 trưa (U68): bắt bù qua đêm, 20 nguồn nước ngoài riêng, Bluesky/X adapter, `--diag`, cap 6 tin/nguồn, tường fetch 45s.** **User chốt 02/10: chỉ tin vĩ mô, nguồn 2 tắt** — prompt hạ tin riêng doanh nghiệp về mức 2. |
| 32 | **Cảnh báo tin: GỬI IM LẶNG ban đêm (không rung)** | 💤 **CHỜ USER GỌI** — user 04/10: "lưu lại, khi nào cần tôi sẽ làm sau" (sinh ra khi chuyển news-alert sang 24/7, #31). Thiết kế đã chốt với user: 23:00–06:00 gửi bằng `disable_notification=True` của Telegram Bot API (tin vẫn tới, vẫn đếm chưa đọc, chỉ không rung/kêu) — **TRỪ lô có tin 5/5** (sốc hệ thống: Fed/SBV đổi lãi suất, thuế quan lên VN, chiến sự lớn) vẫn rung. Khác Mute cả bot: ban ngày + brief sáng/chiều không bị ảnh hưởng. Cách làm: `vnstock_telegram.send_message(..., disable_notification=False)` truyền vào cả hai lần POST (kể cả nhánh rơi về plain) · `vnstock_news_alert`: env `VNSTOCK_NEWS_ALERT_QUIET_HOURS` (mặc định `23-6`, khoảng vắt qua nửa đêm; `off` = tắt) → `_default_sender` nhận cờ im lặng khi `now` trong khung VÀ `max(score) < 5` · marker ghi `silent: true/false` · footer tin nhắn thêm 🔕 · test: trong/ngoài khung, vắt nửa đêm, lô có 5/5 vẫn rung, `off`, env rác về mặc định. User nói "làm đi" là làm (~30′, 🖥️ desktop chỉ cần merge, không phải đăng ký lại task). |
| ~~33~~ | **Gỡ Yahoo Finance `rssindex` khỏi `_FEEDS`** | ✅ **XONG 04/10 tối** (user gật) — xoá dòng + chú thích lý do trong `_FEEDS`, test `test_dead_yahoo_rssindex_stays_removed` (11 feed). Trước đó: 💤 CHỜ USER ĐỒNG Ý — `--diag` 04/10: chuỗi ngày mới nhất `2026-09-23T01:52:26Z`, đứng 11 ngày; `_FEEDS` dùng chung bước news (brief) lẫn cảnh báo tin nên gỡ là đổi cả hai — cần user gật. Cách làm: xoá/`enabled: False` mục Yahoo trong `vnstock_news_feeds._FEEDS` + test đếm feed + ghi U68. |
| ~~18~~ | **GTGD cả ngày hụt vì MÃ LỚN bị cách ly — cổng coverage đếm SỐ MÃ, mù với GIÁ TRỊ** | ✅ **XONG 30/09 02:10** (chờ desktop merge) — `vnstock_runner`: giữ `{ticker: {ngày: giá×KLGD}}` 22 bar cuối; `heavy_missing()` (thuần) kê mã TB ≥ `_HEAVY_GTGD_TY` 50 tỷ/phiên KHÔNG có bar ở phiên mới nhất nhưng còn bar trong 45 ngày (lâu hơn = hủy niêm yết); `excl_missing_totals()` = total từng ngày trừ giá trị NGÀY ĐÓ của các mã thiếu (chỉ trừ khi mã có bar) → `gtgd_by_date[d]["excl_missing"]`, top-level `gtgd_missing_heavy` [{ticker,last_date,avg_gtgd}] + `gtgd_missing_est` + `gtgd_heavy_min`. `vnstock_brief._gtgd_baselines(use_excl=)` lấy excl khi brief nói đúng phiên runner kê thiếu ⇒ prev/TB5/TB20 cùng tập mã với hôm nay (hết "+27%" ảo); ctx `gtgd_missing_heavy`; prompt in "⚠️ Kho THIẾU bar phiên này của N mã lớn (…; ≈X tỷ/phiên) → ƯỚC TÍNH THẤP"; guard `enforce_gtgd_missing_note` gắn "(chưa gồm N mã lớn thiếu data)" một lần sau số canon. Doctor `check_gtgd_coverage` (off/ok/warn kê 5 mã + bar cuối, fix trỏ #15). Test `tests/test_gtgd_coverage.py` (6, vào whitelist). Fast 2.654. Mức tuyệt đối vẫn là Σ mã có bar (không bù bịa) — chỉ % và chú thích được sửa. |
| ~~19~~ | **LNH ON 0,48% mà 1W 6,20% — gauge thanh khoản +1,00 dựng trên ON phân kỳ** | ✅ **XONG 30/09 01:30** (chờ desktop merge) — `--diag` 01:20 fetch tươi từ SBV in y hệt cache: 28/09 ON 0,48 · 1W 6,20 · 2W 6,18 · 1M 6,60 · 3M 6,99 · 6M 7,69; 25/09 ON 0,87 · 1W 4,73; 24/09 ON 1,10 · 1W 5,06 ⇒ parse ĐÚNG, đây là số SBV công bố. Vậy vá ở gauge: `vnstock_macro.liquidity_spread` thêm `_TENOR_DIVERGENCE_PP = 1.5` — có `interbank_1w` và \|ON − 1W\| > 1,5 điểm ⇒ `dir 0`, nhãn "ON 0.48% và 1 tuần 6.20% phân kỳ 5.72 điểm % — ON không đại diện thanh khoản hệ thống, không kết luận" (brief in nhãn này sau dấu →; allocation nhận `dir 0` ⇒ hết +0,10 vào điểm band). 1W đồng thuận thì luật cũ nguyên vẹn; không có 1W thì giữ luật cũ. Test `tests/test_macro.py` +1 với đúng số 28/09 và 25/09. Không thêm badge doctor: gauge đã tự nói. |
| ~~20a~~ | **Cửa brief chiều chặn nhầm lượt tràn nửa đêm** | ✅ **XONG 29/09 23:40** (chờ desktop merge) — `run.py._close_session_date` nay = `vnstock_rollup.session_covered_at` (PHIÊN PHỦ, cùng luật `--skip-if-done` #14): trước 15:05 ngày làm việc là phiên TRƯỚC, nên 00:13 T3 = phiên T2 và marker ghi đúng phiên (bản cũ sẽ ghi 29/09 → brief T3 tối đó bị coi là trùng). `_should_push_close(now, marker, started=)`: lượt KHỞI ĐỘNG trong ngày phiên (`args.pipeline_started`, cmd_all gắn) tràn qua nửa đêm vẫn đẩy; chạy bù sáng và lệnh tay không biết giờ khởi động thì chặn như cũ (user chốt 15/08). `_CLOSE_CUTOFF` = 15:05 có test parity với rollup. Test `tests/test_run_pipeline.py` +3, parity doctor đổi mốc 12:00→16:00. Fast 2.643. |
| ~~20~~ | **Thiếu brief thứ Hai 21/09** | ✅ **RÕ 30/09 00:20** — trần 180′ giết giữa bước brief (mục 7). 22/09 ladder DOWN tách sang #24. | 
| ~~24~~ | **22/09 brief trắng dù bước brief có 1 call OK (super)** | ✅ **VÁ THEO GIẢ THUYẾT MẠNH NHẤT 30/09 02:40** — đọc code ra lỗ hổng khớp mọi dấu vết: bản cũ GHI SỔ OK **trước** khi mổ `choice["message"]["content"]`, và content RỖNG (model reasoning trả toàn "suy nghĩ", `content: ""`) vẫn `return "", None` ⇒ generate_brief thấy bản trắng, alert "mọi agent đều lỗi", mà sổ đếm OK (22/09: super +1 OK trong bước brief, bản trắng). Nay `_openai_extract` coi content rỗng là LỖI agent ("content rỗng (suy nghĩ N token…)"), sổ ghi fail, sang model dự phòng ngay; sổ chỉ ghi OK khi có chữ thật. Chưa có bằng chứng trực tiếp của đêm 22/09 (log cũ không in từng agent) — dòng `[brief] ⏱ <agent>` từ phát 30/09 là phép đo; nếu ca khác thì mở lại. |
| ~~25~~ | **Brief chiều bằng CLAUDE — engine ngoài ladder** | ✅ **CODE XONG 30/09 sáng, CỨNG HOÁ theo thẩm định 30/09 trưa (U62)** (chờ user làm 4 bước mục 8) — `vnstock_brief_pack`: `build_pack` (ctx+prompt cùng đường refresh của `generate_brief` → `_meta/brief_pack.json`), `finalize_brief` (chữ → 55 guard → validate → memory `agent_type=claude` → brief_watch), `run_claude_cli` (`claude -p` prompt qua STDIN, `--output-format json`, sổ `ClaudeCode`, giấu `ANTHROPIC_API_KEY`). `run.py brief --engine {ladder,claude}` / `--export-pack` / `--from-file MD [--force]`; `cmd_brief` + `telegram close` đi chung `_send_close_brief` (lỗi ⇒ rơi về ladder, in `↩`); marker `engine`; `push_close_brief(ai_block, engine)` + `_snippet_from_text` (một luật dọn markdown); footer `🤖`. Skill `.claude/skills/brief-close/SKILL.md` (test canh nó nói đúng tên gói/lệnh). Giá Opus/Sonnet 5.5 vào sổ; slug vào `_all_live_slugs`. Test `tests/test_brief_pack.py` (25, whitelist) + pipeline +8 + telegram +3 ⇒ fast **2.689**. Chưa làm: `ClaudeAgent` API lên Opus/SDK (đường C), điểm AI khác, brief sáng. Chi tiết U61. |
| ~~26~~ | **Claude cho 4 bước LLM còn lại: news (sentiment + chấm tin theo LÔ), audit, train, reflection** | ✅ **CODE XONG 30/09 chiều** (chờ user bật) — cùng backend `vnstock_claude_cli.complete` (U62 §3b). (1) `vnstock_report_digest.digest_call(…, step=)` thêm nấc **`claude-cli` ĐẦU cascade** khi `engine_for(step)=claude` — `vnstock_reflection._reflect_call` (step reflection), `FreeAuditorAgent` (step audit; `make_auditor("auto")` chọn Free khi engine claude, thắng cả key API), debate/digest (step digest); `accept`/feedback/self-fix/alert như cũ; lỗi ⇒ nấc kế. (2) `vnstock_sentiment.score_batch_cli`: cả lô `to_score` (chunk 50) MỘT call `--json-schema` `{results:[{i,sentiment}]}`, map `i`→hash tại chỗ, nhãn lạ/thiếu ⇒ ladder từng tin, cột `model=ClaudeCode:<slug>`; `cli_engine_label()` mở cổng `cmd_news` khi không key free. (3) `vnstock_news_feeds.analyze_items_cli`: ≤8 tin một call (`_ANALYZE_SYSTEM` + CHẾ ĐỘ LÔ), Jina fulltext vẫn từng tin, `sanitize_impact` từng câu, thiếu ⇒ `analyze_item`. (4) `vnstock_train._inject_claude_lead`: engine train = claude ⇒ `ClaudeCodeAgent` làm LEAD (revise/cold-start), ladder free = pool thi đấu; không CLI ⇒ giữ ladder. (5) `vnstock_brief.ClaudeCodeAgent` (type `claude-code`, TẮT mặc định, `_AGENT_STRENGTH` đầu) — bật trong ⚙️ để A/B trên nút brief dashboard. Trần chờ nấc: digest/audit/reflection/news 300s (đè `VNSTOCK_<STEP>_CLI_TIMEOUT_S`), model đè `VNSTOCK_<STEP>_CLI_MODEL`. Test `tests/test_claude_steps.py` (18, whitelist). **Bật tất cả = một dòng `.env`: `VNSTOCK_LLM_ENGINE=claude`** (mục 8 bước 4). **Thẩm định ngược cùng chiều (U62 §3c) vá 9 chỗ**: lưới hermetic conftest (fast xanh cả khi mô phỏng env desktop), memo "CLI chết" trong tiến trình, trần 300 tin/lượt sentiment (dư để đêm sau), `allow_cli=False` cho dashboard, né shim `claude.cmd` + probe ký tự đặc biệt trong `--check`, audit `--json-schema` + nhãn `claude-cli`, dự phòng brief không spawn lần 2, log candidate bị bỏ, doctor keys biết engine, `.env.example`. |
| 21 | **Bước brief phình 1.393–2.532s từ 22/09 (trước đó 37–754s) — cùng đêm VCI ốm là chạm trần 180′** | 🟠 MỚI 29/09 khuya — `⏱ TỔNG` 22/09 brief 1.848s · 23/09 1.930s · 24/09 2.532s · 25/09 1.393s · 29/09 1.743s, trùng đúng đợt Gemini flash 503 + lite read-timeout 90s (agent đợi 20s gọi lại rồi sang lite, mỗi nấc lại 90s). Với sync 7.272s đêm 28/09 thì brief chỉ còn 2′ trước trần; 21/09 có thể đã chết đúng chỗ này. **GỐC RỄ TÌM RA 01:00 (đoạn log thô 22/09): 52 timeout VCI × 30s trong `refresh_upcoming` (auto-refresh sự kiện GDKHQ của brief) = 28′/31′ của bước brief; LLM chỉ ~2′.** **(b) ✅ 01:10** `vnstock_events.refresh_upcoming(max_consecutive_failures=3)`: 3 mã lỗi liền → dừng, giữ cache cũ, 0 mã OK thì không ghi đè file (mtime giữ để lượt sau thử lại); `tests/test_events.py` +2. **(a) ✅ 30/09 00:30** `_agent_outcome_line` + dòng `ctx+prompt` trong `generate_brief`. **Cap Daily 240 đã đăng ký** (00:55). **(c) ✅ 30/09 trưa — đo thật trên 💻 laptop:** `run.py brief --export-pack` 12:46→12:56 in **18 dòng `Read timed out` (VCI)** dù cửa (b) đã có: thư viện vnstock tự thử lại ~6 lần/mã ⇒ 3 mã = 18 timeout = 9,8′. Thêm NGÂN SÁCH TƯỜNG 120s (`refresh_upcoming(budget_s=)`, env `VNSTOCK_EVENTS_REFRESH_BUDGET_S`): có mã lỗi mà quá budget ⇒ dừng ngay sau mã đầu (~3′ thay vì 10′); + BACKOFF 90′ (`_meta/upcoming_events.backoff.json`, env `VNSTOCK_EVENTS_BACKOFF_MIN`): lượt trắng tay ghi marker, `_maybe_refresh_events` bỏ qua tới hết hạn (in `[events] bỏ qua auto-refresh…`), refresh thành công xoá marker; chạy tay `vnstock_events.py --refresh` không xét backoff. Test `tests/test_events.py` +4. Marker đi Dropbox ⇒ máy kia cũng nghỉ (VCI ngã là ngã chung). Còn để ngỏ, chưa cần: ngân sách tường cho bước brief; đưa `test` xuống sau brief; news 1.041s đêm 21/09 (vs 72–85s) có thể cùng bệnh VCI ở chỗ khác — soi khi có đêm VCI ốm kế với log mới. |
| ~~23~~ | **OpenRouter trả body không có `choices`/`message` → agent nổ `KeyError` thay vì in lỗi của provider** | ✅ **XONG 30/09 02:40** (chờ desktop merge) — `vnstock_brief._openai_extract(body)` mổ body OpenAI-compat ở MỘT chỗ cho cả ba agent (base/Cerebras/OpenRouter): `{"error": {"message", "code"}}` hoặc không `choices` ⇒ lỗi "provider trả lỗi trong body: Upstream error from Nvidia … (code 503)", transient (429/5xx trong body) thì base agent đợi 20s gọi lại đúng model một lần, OpenRouter/Cerebras sang model kế; cụt như cũ; sổ ghi fail kèm usage. Test: body thật 21–22/09 → sang ultra, sổ đúng 1 lỗi mang chữ provider, không còn "KeyError". Đường digest/sentiment vẫn tự bắt exception và in body ("thử nấc sau") nên chỉ xấu chữ, không sửa thêm. |

**📏 Phát kế tiếp là phép đo của cả ba bản vá** — dán `⏱ TỔNG` + `⏱ CHẶNG` +
dòng `screener` như thường lệ.

---

# ⏳ TỰ ĐẾN — chỉ đọc

* **T7 hàng tuần**: model watch. Bản mới gộp lỗi TÀI KHOẢN thành một dòng 🏦
  thay vì n dòng ❌ (U24).
* **Vài đêm tới**: #32 mới 39 lệnh, chỉ hơn sàn 30 đúng 9 — một vòng tune xấu
  là mục Khuyến nghị tự tắt. Close 24/08 báo **14 lệnh ẩn** (tăng từ 11) ⇒
  chiến lược nguồn vẫn CHƯA đạt kiểm định. Đó là cổng đang đóng, không phải lỗi.
* **~2 đêm nữa**: hàng đợi auto-heal sạch (1.704 → 1.631 → 778 → …). Rút bằng
  LƯU TRỮ chứ không phải bằng chữa — `healed = 0 / 4.707 lượt` qua ba đêm.
* **Phát tối mai — GH3 có đuổi kịp không.** Kho nó đóng băng từ **2025-09-24**
  (348 ngày), tức **11 tháng TRƯỚC** khi cửa gác ra đời ⇒ gác không phải
  nguyên nhân. Nguồn có sẵn 1.267 bar trong khi kho chỉ 1.033 ⇒ ~234 bar đang
  chờ nối. Chữa cơ sở xong, gác hết lý do chặn. Đuổi kịp ⇒ xong chuyện; vẫn
  dừng ở 2025-09-24 ⇒ nguyên nhân nằm chỗ khác, dán `--explain --ticker GH3`.

---

# ✅ ĐÃ ĐÓNG — không phải làm lại

| Việc | Kết quả |
|---|---|
| Lệch cơ sở kho giá | **SỔ RỖNG 15/09** (70 mã 09/09 là ảnh chụp cũ do Dropbox desktop tắt sync — U56; 25 mã mới tháng 9 chữa 15/09 — U57) — 73 mã chữa trong một tối (76 mã đợt 18-19/08 + 73 đợt này) · V1 chặn tái phát ở đường ghi · công cụ nay có `--whole-series`, `--from-drift-ledger`, `--explain`, `--restore` |
| Rổ VN30 kỳ 08/2026 | Lấy động (API → cache → hằng số) · VÀO BSR·LPB·MCH·TCX·VPL, RỜI BCM·BVH·PLX·POW·TPB · cả 30 mã có giá trong kho |
| Live mode | `verify_wss_live` ✅ cả 3 bất biến (24/30 mã volume) + **mắt người** xác nhận heatmap chạy |
| Tốc độ heatmap | Fragment 5s → 2s · tầng nóng (VN30 mỗi vòng, ~1.100 mã mỗi 5 vòng) |
| Rủi ro chạm trần task | 166,3′ → 69,0′ ⇒ đệm 13,7′ → **111′** *(số chưa sạch — xem việc #1)* |
| Phát tự động trọn vẹn | 21/08, 24/08, 25/08 đều đủ 14 bước và **có brief Telegram** |
| Chất lượng brief | Guard số chỉ số (trạng từ) · dọn khối tin · GDKHQ không cảnh báo cho ĐHĐCĐ · dải ±3% gọi đúng tên |
| Đồng bộ code | 💻 laptop = đầu nhánh `b04c908` (`--fast` 2.565 / 110,6s, full 3.158 tại `c969d6a`); 🖥️ desktop **vẫn `2.615`, chưa merge** — xem việc #6 |
| `fix-units` đối chứng | 26/08 trên KHO THẬT: `fix_count` khớp, giải nén **ít hơn 1.125×**, bỏ qua **98,6%** mã. Lượt đối chứng còn tìm ra bug HFB (`time` trộn kiểu ⇒ mã bị bỏ sót im lặng) — đã vá (U32) |
| Sổ lệnh | **Không mất** — 805 briefs · 148 rec · 138 outcome |
| BCTC ngân hàng 2015-2016 | **TẠM DỪNG** (user chốt 26/08) — đã đo 5 nguồn: `vci` sớm nhất 2018-Q1 (đúng khung, tốt nhất) · `finhay` trần 5 kỳ · `cafef` có 2015-2016 nhưng **sai khung (doanh nghiệp thường)** · `kbs` rỗng · `tcbs` 404. Muốn data cũ hơn ⇒ user xuất Wichart/FiinPro, Claude viết bộ đọc. **Đừng dò lại** — xem U34 `docs/CLAUDE-NOTES.md` |
| Rác `C:\proc` | **Không tồn tại** — Claude suy nhầm là đã tạo, user kiểm 25/08 ra PathNotFound (U26) |
