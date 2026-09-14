# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 14/09/2026 22:04 — 🖥️ desktop đã làm bước 1 của #0: sổ cách ly **25 mã MỚI** (không phải 70 mã cũ ⇒ Dropbox đã lấy đúng bản desktop) · updater 14/09 kết thúc CÓ LỖI (marker còn 11/09) · sync lưỡng cực 9′ / 85–113′ · trần task thật là **180′**. Còn: đợi `⏱ TỔNG` 14/09 → dọn conflicted → merge → brief_watch + doctor → rebase 25 mã → brief 15/09 là brief đầu tiên có bản vá.

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

## 0. 🚨 HAI KHO ĐÃ TÁCH NHAU từ 07/09 ~21:07 — NGUYÊN NHÂN ĐÃ RÕ, đang sync lại

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
  8 mã `0d` (BMI DVN DVP ELC PDN PTB TIP VLW) kho đã có bar 14/09 ⇒ gác đã
  thả, sổ chưa xoá — rebase chạy thử sẽ in `↩ kho ĐÃ SẠCH … chỉ cần xoá sổ`.
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
- Lúc 22:04 phát 14/09 **chưa in `⏱ TỔNG`** (chặng sync xong 21:55, còn ~35–45′)
  ⇒ mọi bước GHI dưới đây đợi dòng `⏱ TỔNG [2026-09-14 …]`.

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
| 14/09 | chưa xong lúc 22:04 | 5.118s | **4.860s** | — | — | — |

Đọc: (a) **updater lưỡng cực** — ~270s ngày thường (bản vá 10.527s → 316s vẫn
ăn) nhưng 4.860–6.500s ba trong năm phát; cùng 1.613 mã, cùng code ⇒ nghi
rate-limit/mạng chứ không phải khối lượng. Bằng chứng cần: số dòng `rate-limit,
chờ` và dòng `❌ N lỗi` của từng phát (#0 bước 5). (b) Trần task thật là
**180′** (ps1 nâng 19/08) — 152′/159′ không bị chấm dứt, nhưng đệm chỉ còn
~25′ vào đêm xấu. (c) screener 656–762s: Net BS vẫn là khối lớn nhất, không
đổi. (d) validate 91 → 354 → 330 → 157s: vẫn chưa rõ vì sao, dao động 4×.
(e) brief 322–523s so 59s hôm 07/09 — chưa rõ, có thể ladder gọi lại; ledger
Gemini sẽ nói.

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

## 4b. 📰 Sau đợt vá brief 09/09 — đối chiếu brief kế tiếp

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

Rồi brief close **ĐẦU TIÊN SAU KHI DESKTOP MERGE** (xem #6 — trước đó brief
vẫn là code cũ, soi cũng vô ích), soi 4 chỗ (dán cho Claude nếu lệch):
1. Header không còn `(2 dòng)` / `(1 dòng, optional)`.
2. Dòng "Kỳ hạn & đường cong": nếu 10Y − điều hành vẫn trong ±0.10 thì phải
   đọc là *"mỏng — sát 0 (… chưa tính ÂM)"*, và điểm band phân bổ nhích lên
   (−0.12 → khoảng −0.07 nếu các gauge khác giữ nguyên).
3. "Sự kiện sắp tới" KHÔNG còn sự kiện ngày của chính phiên đó.
4. Dẫn dắt/Tụt hậu cùng 3 số lẻ `pp`.

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

**📦 vnstock 4.0.7 đã ra — cổng gỡ chặn 4.0.6 đã mở.** Đúng thứ tự:
1. 💻 Laptop TRƯỚC: `pip install vnstock==4.0.7` → `run.py doctor --net` +
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
| **Sổ theo dõi nghi ngờ brief** | Chuyển `⚠️ ĐỦ mẫu, đáng quyết` (Op.CF/vốn hoá · câu dòng tiền ngoại ngược data) |
| **Hiệu suất auto-heal** | `⚠️` = 0 lành dù đủ mẫu ⇒ quyết hạ trần `VNSTOCK_AUTOHEAL_BUDGET_S=120` hay tắt hẳn |
| **Lệch cơ sở — mã bị cách ly** | ~~Sổ RỖNG (07/09)~~ **doctor 09/09: 70 mã, ngày cũ ⇒ xem việc #0**. Có mã mới ⇒ `python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series` (chạy thử) rồi thêm `--apply`. Mã bị từ chối ⇒ `--ticker <MÃ> --explain` |
| **Nới OHLC (bar tự mâu thuẫn)** | Nới sát trần 20% ⇒ soi lại bar đó |
| **Rổ VN30** | `⚠️ rổ thật đã đổi` ⇒ dán dòng badge cho Claude |

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

| 11 | **Doctor: "phát tối chưa tới kho này" là một badge riêng** | 🟠 MỚI 10/09 — kiểm `check_warehouse` thì nó ĐÃ đếm theo phiên với dung sai 2 phiên cố ý (VNINDEX EOD về trễ) — không phải lỗi. Cái thiếu là badge nói thẳng hai khả năng: sau ~20:00 ngày làm việc mà `_meta/pipeline_status.json` `last_success_date` < phiên gần nhất ⇒ warn *"phát tối chưa tới kho này: pipeline không chạy HOẶC sync Dropbox tắt — kiểm icon khay + `Get-ScheduledTaskInfo` ở desktop"*. Rẻ, chạy được ở máy nào cũng đúng, và lộ vụ 07/09 ngay sáng 08/09. |

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
| Lệch cơ sở kho giá | **SỔ RỖNG 07/09 — nhưng doctor 09/09 lại thấy 70 mã với ngày cũ (việc #0, đang tra)** — 73 mã chữa trong một tối (76 mã đợt 18-19/08 + 73 đợt này) · V1 chặn tái phát ở đường ghi · công cụ nay có `--whole-series`, `--from-drift-ledger`, `--explain`, `--restore` |
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
