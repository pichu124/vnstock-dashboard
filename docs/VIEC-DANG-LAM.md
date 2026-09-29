# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 29/09/2026 tối — user nghỉ 13 ngày, pipeline tự chạy đủ (badge Phát tối ✅ 29/09, test full 3.235 passed trong pipeline). **Sổ cách ly dồn 45 mã** (mùa quyền; TCX 1,2000× ĐỨNG 13 ngày từ 16/09 — VN30 thiếu bar hai tuần) ⇒ **đã chữa 45/45 cùng tối**: 44 mã bằng `--from-drift-ledger --whole-series --apply` 21:14; FPT bằng `--ticker FPT --break-date 2026-05-28 --apply` 22:39 (hai đợt quyền trong một năm — U59) + `vnstock_updater.py --tickers FPT` nối 7 bar ⇒ `--explain` SẠCH, doctor 22:39 sổ cách ly RỖNG. Doctor 22:39: 21✅/4⚠️ — còn brief_watch (xoá file, mục 1) · brief phân bổ tháng 9 · auto-heal 0s (để) · **sổ LLM 66 call · 30 OK · 36 lỗi** (`--show` 22:45): chuyện chính là **Gemini flash 23 call · 3 OK · 20 lỗi 503** — flash-lite gánh 17 OK (5 lỗi là read timeout 15s, cỡ timeout đường sentiment `vnstock_sentiment.py:193`, brief agent dùng 90s) ⇒ brief hôm nay nhiều khả năng từ dự phòng flash-lite, bước brief 1.743s = mỗi lượt Gemini trả 503 → đợi 20s → 503 → sang lite. **Mistral 10 call · 0 OK · 10/10 429** (0 OK từ 15/09 tới nay: 15/09 quota, 16/09 429 ×2) ⇒ giọng thứ tư user giữ 11/08 đã CHẾT hai tuần, mỗi lượt tốn 2 call + 20s chờ và giữ badge sổ LLM ⚠️ vĩnh viễn (che mất chuyện flash). ĐỀ XUẤT: tắt Mistral (expander ⚙️ Cài đặt AI Agent, hoặc lệnh ở mục 3 bảng việc-của-user), soi console.mistral.ai xem hết quota hay đổi gói rồi bật lại. Cerebras 402 1 call = cầu dao ăn đúng (#3 còn treo). OpenRouter super 5/5 · ultra 4/4 OK, suy nghĩ 53%/79% (4c). Chi phí $0,0042. **4c ĐO XONG:** nemotron super 5/5 · ultra 4/4 OK ở trần 8.000, suy nghĩ chiếm 53%/79% token ra ⇒ trần 2.800 cũ bị thinking ăn hết. **Sổ theo dõi brief đủ mẫu (8 phiên, KBC/PVC ×9)** — đối chiếu BCTC Finhay 29/09: KBC Op.CF TTM ≈ −16.510 tỷ (Q3/25 −7.146 · Q4/25 −2.128 · Q1/26 −2.913 · Q2/26 −4.323), PVC TTM ≈ −462 tỷ ⇒ SỐ THẬT, không phải lỗi đơn vị ⇒ không cần guard, xoá `_meta/brief_watch.json` để đếm lại (mục 1). Brief bước 14 tối 29/09 **1.743s** (flash 3/23 OK, 503 cả ngày) — chưa có dòng log tách theo agent. Bản cũ: 15/09/2026 tối — **brief close 15/09 TRẮNG** ("LLM ladder DOWN", AI Outlook "Chưa có brief"): Gemini 429 rồi 503 đúng lúc chạy, Mistral quota, Cerebras 402, OpenRouter super cụt ×2 mà KHÔNG rơi xuống ultra vì bộ lọc danh mục tôi thêm ở #13 bỏ nhầm ultra (danh mục cắt trang 400). Đã vá: bỏ hỏi danh mục; agent base đợi 20s gọi lại khi 429/5xx rồi sang dự phòng cùng provider (Gemini flash → flash-lite). 🖥️ desktop **đã merge `661b193`, `--fast` 2.591/86s, rồi `telegram close --force` 20:41 ⇒ brief CÓ AI Outlook** (Gemini flash 503 → đợi 20s → OK; Cerebras bị cầu dao bỏ; super cụt → ultra được gọi nhưng CŨNG cụt; Mistral 429 ×2). 4b soi 4/4 đạt. **4c đã vá cùng tối** (sổ ghi usage khi cụt + OpenRouter nới trần +5.200). **16/09: #11 xong** (badge "Phát tối — đã tới kho này chưa") **+ vá hai lỗ hổng đường chạy bù** (#14: marker so PHIÊN PHỦ thay vì ngày lịch; T7/CN sync `--force`) — 🖥️ desktop đã merge `cf644f8`, `--fast` 2.632/98s. **Badge chạy thật lần đầu tối 16/09** (khám giữa phát): ✅ "phát tối 2026-09-16 đang tới kho này — sync partial 200 lỗi lúc 21:16 bởi PICHU · brief chiều chưa (phát còn đang chạy…)" — rồi 22:10 sau khi phát xong: ✅ "phát tối 2026-09-16 đã tới kho này — sync partial 200 lỗi lúc 16/09 21:16 bởi PICHU · brief chiều đã đẩy". **Hai verdict đúng theo thứ tự — phép đo #11 đường bình thường XONG.** Đêm 16/09 là đêm VCI ốm thứ 5/7 (partial 200). **Brief tự động 16/09 (22:06) CÓ AI Outlook, sinh bởi flash-lite qua DỰ PHÒNG** (flash 503 ×6 trong ngày) — bản vá `661b193` cứu brief ngay đêm đầu. Phát khởi động 20:25 (bật muộn), TỔNG 101,4′ (sync 3.415s · screener 776s · brief 624s). Ba lỗi chữ trong brief vá cùng tối (guard + test): header `(nếu có ... trong data)` lọt · Watchlist đánh số từ 2 · `điểm -0.00`. 🖥️ desktop đã merge `f5e512e`, `--fast` 2.635 passed / 156s (lượt trưa 98s). Sổ cách ly có 3 mã mới ACG·BAL·BHN — **đã chữa 22:07 cùng tối** (`--from-drift-ledger --whole-series --apply` 3/3: ACG 1,0322× và BHN 1,1022× lệch đều toàn chuỗi = nguồn vừa điều chỉnh lùi; BAL vách 27/08 với 3 bar sau vách khớp nguồn = đúng ca bar lọt qua cửa KBS 8% — bộ dò MỨC bắt được). VCI vẫn timeout lúc 22:02–22:07. Còn đo: sáng 17/09 badge phải "đã tới … brief chiều đã đẩy"; brief tự động 16/09; lần chạy bù kế tiếp soi #14. **Tối 17/09 soi TCX bằng tay** (`--ticker TCX --explain`) vì cửa KBS từ chối KHÔNG vào sổ (#15) — mốc so sánh 16/09 22:10: TCX sạch 1,0000× trên 224 bar, đứng 0 ngày (trước GDKHQ). #12 chạy đúng (marker `partial: 214`), #0 xong (sổ cách ly RỖNG, VNINDEX 15/09).

## 🏷️ NHÃN MÁY — quy tắc gốc: KHO đồng bộ, CODE thì không

`C:\vnstock\data_warehouse` là **Junction** trỏ sang
`E:\Dropbox\vnstock_data\data_warehouse`. Repo `C:\vnstock` đi bằng **git**.

| Nhãn | Nghĩa |
|---|---|
| ○ **MỘT LẦN** | Đụng `data_warehouse`. Dropbox lo máy kia — **đừng làm hai lần**. |
| ⇄ **CẢ HAI** | KHÔNG nằm trong kho: `git merge`, pip, venv, task lịch, biến môi trường, `run_daily.log`. |
| 🖥️ **DESKTOP** | Máy chạy pipeline (`PICHU`, 2 task lịch): log phát đêm, `Get-ScheduledTaskInfo`, brief tự động. |
| 💻 **LAPTOP** | Thử nghiệm rủi ro (`CFA-BINHLD-LT`, không task) — hỏng cũng không mất brief đêm. |

**Máy đang ngồi là TRẠNG THÁI DÍNH** (chốt 20/08): user báo đổi máy thì mới
đổi; không báo thì giữ nguyên máy của lượt trước. Đừng suy từ đường dẫn venv —
cả hai đều `C:\vnstock`, venv đổi theo TÀI KHOẢN đăng nhập. Thật sự chưa biết
thì: `$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *'` (2 task =
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

## 5. 🧭 Brief phân bổ tháng 9 — 🖥️ desktop, trong dashboard

Badge `allocation` ⚠️: band B3 (thắt chặt), 7 tín hiệu, nhưng **chưa có brief
phân bổ tháng 9/2026** (cadence tháng). Không phải lệnh gõ — vào dashboard →
tab **Tin tức** → sub-tab **🧭 Phân bổ** → nút **📝 Tạo brief**.

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
