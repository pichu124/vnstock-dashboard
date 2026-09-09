# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 09/09/2026 — 🚨 HAI KHO TÁCH NHAU từ 07/09 21:07, laptop = bản trước chiến dịch (việc #0, KHÔNG --apply) · 5 lỗi brief ĐÃ VÁ (#6–#10, U55); laptop đã merge, `3.158 passed`; **desktop CHƯA merge** — brief tối vẫn code cũ tới khi merge.

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
desktop). **Phiên hiện tại: 💻 LAPTOP** (user báo 09/09).

---

# 🔴 CÒN PHẢI LÀM

## 0. 🚨 HAI KHO ĐÃ TÁCH NHAU từ 07/09 ~21:07 — kho laptop là BẢN TRƯỚC CHIẾN DỊCH

Đo 09/09 trên 💻 laptop (U56), toàn lệnh chỉ đọc:

* Sổ cách ly `basis_drift_pending.json`: **70 mã**, ghi lần cuối **07/09 21:07:41**,
  `detected_at` = 08-21 ×23 · 08-24 ×6 · 08-25 ×2 · 08-28 ×8 · 09-04 ×2 · **09-07 ×29**.
* `--from-drift-ledger --whole-series` (chạy thử): **69/70 lệch THẬT**, ACE sạch.
  Và chẩn đoán trùng U53 **từng con số**: VIM 35 · HU4 24 · SGR 9 · PJS 6 ·
  ND2 5 · CHP 4 bar nhân hệ số; DRG `spread lõi 1.0016, thô 1.0251, 1 bar lẻ`;
  GH3 1.1356× / 1.033 bar. Tức kho laptop đang nhìn = **đúng trạng thái TRƯỚC
  khi chiến dịch 07/09 chữa 73 → 0**.
* `prices/` **0** conflicted copy; `_meta/` chỉ có conflicted copy cũ tháng 5–7.
* Junction laptop OK → `C:\Users\Administrator\Dropbox\vnstock_data\data_warehouse`.
* Cùng chiều: VNINDEX bar cuối 07/09 · market_overview 07/09 · NN ròng 07/09.

⇒ **Mọi thứ ghi vào kho sau 07/09 21:07 (chiến dịch 73→0, phát 08/09) KHÔNG tới
bản kho laptop đang đọc.** Hai bản kho đã tách nhau. Chưa biết client Dropbox
bên nào ngừng sync (laptop hay desktop) — chỉ máy thật trả lời được.

### 🛑 TUYỆT ĐỐI KHÔNG `--apply` trên laptop
Chữa lại 69 mã trên bản laptop là tạo bản chữa THỨ HAI, độc lập; khi sync nối
lại là 69 parquet + sổ đẻ conflicted copy cùng lúc — CLAUDE.md hệ quả #3 ở quy
mô cả chiến dịch. Bản desktop (có chiến dịch + data 08/09) là bản đúng.

### Ba lệnh chỉ đọc để biết bên nào đứng
```powershell
# 💻 LAPTOP — client Dropbox có chạy/đang "Up to date" không (nhìn icon khay), và
#             kho laptop nhận được phát nào cuối cùng, từ máy nào
Get-Process Dropbox -ErrorAction SilentlyContinue | Select-Object Name,StartTime
Get-Content data_warehouse\_meta\pipeline_status.json
```
```powershell
# 🖥️ DESKTOP — icon Dropbox ở khay: đang sync / paused / lỗi?  Rồi:
Get-Item C:\vnstock\data_warehouse | Format-List LinkType,Target      # E:\ còn không
Get-Content data_warehouse\_meta\pipeline_status.json                # phải có 09-08
python scripts\triage_basis_drift.py                                   # phải RỖNG nếu chiến dịch còn
Get-ScheduledTask -TaskName 'VnStock *' | Get-ScheduledTaskInfo | Format-List TaskName,LastRunTime,LastTaskResult
```

### Đường hồi phục (sau khi sync nối lại)
1. Bản desktop thắng — laptop chưa hề ghi `prices/` nên parquet không xung đột.
2. Laptop hôm nay chỉ ghi vài file `_meta` (`test_status`, `market_news_cache`,
   `doctor_status`, chuyển `brief_watch.json` vào `backup_rebase/`) ⇒ có thể đẻ
   vài conflicted copy nhỏ trong `_meta` — xoá, vô hại.
3. Kiểm trên laptop: `python scripts\triage_basis_drift.py` → RỖNG, và
   `python run.py doctor` → VNINDEX bar cuối = phiên gần nhất.
4. Nếu bản desktop cũng KHÔNG có chiến dịch (triage desktop ≠ RỖNG) ⇒ chiến dịch
   07/09 đã mất thật — dán cho Claude trước khi làm gì; `backup_rebase/` là chỗ soi.

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

🖥️ **DESKTOP CHƯA MERGE — vẫn `2.615`, tức brief tối vẫn sinh bằng CODE CŨ**
(cả 5 lỗi #6–#10 còn nguyên trên Telegram cho tới khi merge). Code không đi
qua Dropbox nên phải làm ⇄ ở desktop, và làm **NGOÀI 18:00–19:xx** (pipeline
đang chạy thì đừng đổi code dưới chân nó):
```powershell
cd C:\vnstock
git fetch origin claude/laptop-work-ono4qt
git merge origin/claude/laptop-work-ono4qt
git log --oneline -1            # dòng đầu phải ghi (HEAD -> main, origin/claude/laptop-work-ono4qt)
python run.py test --fast       # ~2.565 passed; badge xanh
```
Hôm nay 09/09 là thứ Tư ⇒ pipeline 18:00 chạy. Merge **trước 18:00** thì brief
tối nay đã là code mới; không kịp thì đợi bước 14/14 xong (~19:30) rồi merge,
brief đầu tiên có bản vá là phiên kế tiếp.

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
