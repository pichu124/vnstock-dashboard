# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 09/09/2026 — 5 lỗi brief close 08/09 ĐÃ VÁ (#6–#10, U55); NSO đã có kỳ tháng 8.

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
🖥️ **Việc của anh: xoá `data_warehouse\_meta\brief_watch.json` để đếm lại**
— sổ cũ toàn số rác. Vài phiên nữa badge sẽ nói điều khác.

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

## 4b. 📰 Sau đợt vá brief 09/09 — ○ MỘT LẦN dọn cache + đối chiếu brief kế tiếp

Hai câu cụt (`— tác động: Nh`, `— tác động: Tỷ giá`) **vẫn nằm trong cache**
`_meta/market_news_cache.json` (kho chung) — bản vá chỉ chặn câu cụt MỚI.
Dọn một lần, máy nào cũng được:
```powershell
python vnstock_news_feeds.py --refresh --reanalyze    # chấm lại 8 tin mới nhất
python vnstock_news_feeds.py --show                   # không còn dòng "tác động:" cụt
```
Rồi brief close kế tiếp, soi 4 chỗ (dán cho Claude nếu lệch):
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

Laptop đang ở `2.615`, HEAD là **`3.141` + 17 test mới** (09/09, đợt vá brief
#6–#10 — nhánh `claude/laptop-work-ono4qt`, đã gộp sẵn lịch sử `main` 09/08).

```powershell
cd C:\vnstock
git fetch origin claude/laptop-work-ono4qt
git merge origin/claude/laptop-work-ono4qt
python run.py test          # kỳ vọng ≈3.158 passed (3.141 + 17)
```

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
| **Lệch cơ sở — mã bị cách ly** | Sổ đang RỖNG (07/09). Có mã mới ⇒ `python scripts\rebase_ticker_history.py --from-drift-ledger --whole-series` (chạy thử) rồi thêm `--apply`. Mã bị từ chối ⇒ `--ticker <MÃ> --explain` |
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
| Lệch cơ sở kho giá | **SỔ RỖNG 07/09** — 73 mã chữa trong một tối (76 mã đợt 18-19/08 + 73 đợt này) · V1 chặn tái phát ở đường ghi · công cụ nay có `--whole-series`, `--from-drift-ledger`, `--explain`, `--restore` |
| Rổ VN30 kỳ 08/2026 | Lấy động (API → cache → hằng số) · VÀO BSR·LPB·MCH·TCX·VPL, RỜI BCM·BVH·PLX·POW·TPB · cả 30 mã có giá trong kho |
| Live mode | `verify_wss_live` ✅ cả 3 bất biến (24/30 mã volume) + **mắt người** xác nhận heatmap chạy |
| Tốc độ heatmap | Fragment 5s → 2s · tầng nóng (VN30 mỗi vòng, ~1.100 mã mỗi 5 vòng) |
| Rủi ro chạm trần task | 166,3′ → 69,0′ ⇒ đệm 13,7′ → **111′** *(số chưa sạch — xem việc #1)* |
| Phát tự động trọn vẹn | 21/08, 24/08, 25/08 đều đủ 14 bước và **có brief Telegram** |
| Chất lượng brief | Guard số chỉ số (trạng từ) · dọn khối tin · GDKHQ không cảnh báo cho ĐHĐCĐ · dải ±3% gọi đúng tên |
| Đồng bộ code | 🖥️ desktop `2.615 passed` = HEAD lúc 26/08 sáng; HEAD nay **3.141** (đợt vá lệch cơ sở + `--whole-series`) |
| `fix-units` đối chứng | 26/08 trên KHO THẬT: `fix_count` khớp, giải nén **ít hơn 1.125×**, bỏ qua **98,6%** mã. Lượt đối chứng còn tìm ra bug HFB (`time` trộn kiểu ⇒ mã bị bỏ sót im lặng) — đã vá (U32) |
| Sổ lệnh | **Không mất** — 805 briefs · 148 rec · 138 outcome |
| BCTC ngân hàng 2015-2016 | **TẠM DỪNG** (user chốt 26/08) — đã đo 5 nguồn: `vci` sớm nhất 2018-Q1 (đúng khung, tốt nhất) · `finhay` trần 5 kỳ · `cafef` có 2015-2016 nhưng **sai khung (doanh nghiệp thường)** · `kbs` rỗng · `tcbs` 404. Muốn data cũ hơn ⇒ user xuất Wichart/FiinPro, Claude viết bộ đọc. **Đừng dò lại** — xem U34 `docs/CLAUDE-NOTES.md` |
| Rác `C:\proc` | **Không tồn tại** — Claude suy nhầm là đã tạo, user kiểm 25/08 ra PathNotFound (U26) |
