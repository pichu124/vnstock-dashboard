# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 26/08/2026, chiều — sau khi `--whole-series` xong.

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
desktop). **Phiên hiện tại: 🖥️ DESKTOP** (user báo 07/09).

---

# 🔴 CÒN PHẢI LÀM

## 1. 📏 Đo phát 18:00 — 🖥️ desktop, TỐI NAY

Phát tối nay là phép đo của **bốn bản vá cùng lúc**, và là lượt đầu chạy trong
điều kiện sạch (không chạy tay gì trước).

| Bản vá | Kỳ vọng |
|---|---|
| Cửa sổ đối chiếu hẹp (26/08) | `updater` giảm |
| Screener 14 lượt → 1 | `screener` từ 1.318s xuống mạnh |
| fix-units lọc footer | từ 316s xuống mạnh (đã đo: đọc ít hơn 1.125×) |
| Mốc watchlist THẬT | nhìn trong brief, không phải trong log |

⚠️ **Từ giờ tới 18:00 đừng gõ lệnh kho nào** — `run.py sync` / `all` /
`fix-units` không có `--dry-run`, và **đặc biệt là `run.py screener`**.

Bẫy cụ thể với `screener`: nó **ghi cache Net BS** (`_meta/net_bs_cache.json`,
TTL 12h). Chạy tay trước 18:00 thì phát tối **trúng cache và bỏ qua hẳn** vòng
Net BS ⇒ đo được một bước `screener` KHÔNG có Net BS, không so được với mốc
1.318s. Bản vá lớn nhất lại thành thứ duy nhất không đo được.

⚠️ **PHẢI ĐỌC LOG Ở 🖥️ DESKTOP.** `run_daily.log` nằm ở **gốc repo**, mà repo
đi bằng git chứ không qua Dropbox ⇒ **log KHÔNG đồng bộ**, nó là nhân chứng
riêng của từng máy. Ngồi 💻 laptop thì **không có** `⏱ TỔNG` / `⏱ CHẶNG` —
chỉ thấy được phần nằm TRONG kho (badge `pipeline_status.json` /
`brief_push.json` / `doctor_status.json`), tức biết phát có chạy trọn không,
KHÔNG biết mỗi chặng mất bao lâu. Mà chặng mới là thứ cần đo.
⇒ Tối nay ngồi desktop lúc ~19:15, hoặc chép `run_daily.log` sang rồi dán.

Sau ~19:15, dán **ba thứ**:
```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '⏱ TỔNG|⏱ CHẶNG|Net Buy-Sell' | Select-Object -Last 6
python run.py doctor
```
+ **bản brief Telegram** (lần đầu watchlist có `pivot 60 phiên`).

Dòng có **`[ngày giờ]`** là dòng MỚI — không có dấu thì phát chưa xong, khỏi dán.

`⏱ TỔNG` không giảm rõ so với 69,0′ ⇒ còn biến số chưa thấy, đáng đào tiếp
(đúng như lần `updater` hoá ra mới là kẻ ăn 57 phút chứ không phải `auto-heal`).

## 2. 💳 Quyết Cerebras 402 — ○ máy nào cũng được

Model watch T7 22/08: **Cerebras HTTP 402 "Payment required"** ở cả hai model.
Đây là hỏng **TÀI KHOẢN**, không phải model chết — đổi slug KHÔNG cứu được.

Hệ thống vẫn chạy, nhưng lưới dự phòng mỏng hẳn:

| Điểm | Còn sống |
|---|---|
| [1] sentiment | Gemini → Groq (từ 4 nấc còn 2) |
| [3-6] digest | Gemini + nemotron · Groq×2 → Gemini-lite |
| [7] brief | Gemini (agent CHÍNH) |

⚠️ **Gemini nay gánh cả ba chỗ** — nghẽn Gemini là hụt nhiều nơi cùng lúc.

Ba lựa chọn: **kệ** (rẻ nhất, rủi ro dồn vào Gemini) · **nạp tiền Cerebras**
(về nguyên trạng, không đụng code) · **tìm free thay thế** — phải probe SỐNG
trước rồi báo Claude:
```powershell
python scripts\probe_models.py --slug "OpenRouter=<slug>"
```

## 3. ⏰ NSO qua mạng khác — ○ MÁY NÀO CŨNG ĐƯỢC (cần 4G), CÓ HẠN

CPI / IIP / GDP / cán cân thương mại đang dùng cache `as_of 2026-07-31`. Kỳ
tháng 8 công bố **cuối tháng** — không kéo được là brief nói số vĩ mô cũ, mà
**doctor KHÔNG báo giúp** (nó chỉ biết "fetch hỏng", không biết "số đã lỗi thời").

Nhãn cũ ghi 🖥️ desktop là **SAI** (sửa 26/08): việc này chỉ kiểm **mạng nhà
có chặn NSO không**, chẳng dính máy nào. Kết quả ghi `_meta/doctor_status.json`
— nằm TRONG kho nên máy kia tự thấy. Đang ngồi máy nào thì làm luôn máy đó.

Phát 4G từ điện thoại, nối máy vào, rồi:
```powershell
python run.py doctor --net
```
NSO ✅ = mạng NHÀ chặn ⇒ xử ở router/ISP, **không đụng code**.
Vẫn ❌ = nguồn thật sự đổi ⇒ lúc đó mới đáng sửa `vnstock_nso`.

*(Jina ⚠️ cùng cụm nhưng **không gấp** — chỉ làm tin chấm bằng title+summary.)*

## 4. 💻 Laptop — merge + nâng vnstock 4.0.7 TRƯỚC desktop

Laptop đang ở `2.615`, HEAD là **`3.120`** (07/09, sau `--whole-series`).

```powershell
cd C:\vnstock
git pull origin claude/tong-hop-cong-viec-test-w8mvrc
python run.py test          # phải ra 3.120 passed
```

**📦 vnstock 4.0.7 đã ra — cổng gỡ chặn 4.0.6 đã mở.** Đúng thứ tự:
1. 💻 Laptop TRƯỚC: `pip install vnstock==4.0.7` → `run.py doctor --net` +
   `run.py test` **ngay**.
2. Chạy vài ngày xem có gì lạ.
3. Sạch rồi mới đụng 🖥️ desktop, và **không nâng sát 18:00**.
4. Hỏng thì lùi: `pip install vnstock==4.0.4 vnai==2.4.8`.

Desktop giữ 4.0.4 — nó chạy phát tối, không phải chỗ để thử.
*(4.0.6 làm chết mọi lệnh gọi mạng — `env.py:136 UnboundLocalError`.)*

## 5. 🧬 Lệch cơ sở — 🖥️ CÒN 1 MÃ (DRG), KHÔNG GẤP

**Sổ 73 → 1.** GH3 đã chữa (1.033 bar, spread 1.0022, phủ 100% lịch sử kho).

**DRG là ca cuối, và nó cần một cái nhìn chứ không cần nới ngưỡng.** 195 bar ở
1.0204× rồi đúng MỘT bar ở 0.9964 — hai cách đọc đối nghịch mà không con số
tổng hợp nào tách được: vách thật (chữa phần trước) hay lệch đồng đều kèm một
bar hỏng (chữa trọn chuỗi). `--explain` nay in đuôi chuỗi để tách:

```powershell
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc
python scripts\rebase_ticker_history.py --ticker DRG --explain
```
Chỉ đọc. Dán khối **ĐUÔI** cho Claude — 12 bar cuối kèm tỉ lệ từng bar. Bar
✓ đứng một mình giữa toàn ✗ ⇒ nghi bar hỏng; có vài bar ✓ liền nhau ở cuối ⇒
vách thật.

---

# 🔔 MÁY TỰ NHẮC — không phải việc gõ tay

Chạy `python run.py doctor` và chỉ **nhìn badge**. Vàng ở đây thường là dấu
hiệu guard đang LÀM VIỆC, không phải hỏng.

| Badge | Khi nào gọi Claude |
|---|---|
| **Sổ theo dõi nghi ngờ brief** | Chuyển `⚠️ ĐỦ mẫu, đáng quyết` (Op.CF/vốn hoá · câu dòng tiền ngoại ngược data) |
| **Hiệu suất auto-heal** | `⚠️` = 0 lành dù đủ mẫu ⇒ quyết hạ trần `VNSTOCK_AUTOHEAL_BUDGET_S=120` hay tắt hẳn |
| **Lệch cơ sở — mã bị cách ly** | Có mã ⇒ xem việc **#5** (đa số cần `--whole-series`, lệnh cũ sẽ TỪ CHỐI và nói vì sao) |
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
| Lệch cơ sở kho giá | **76 mã** đã chữa · quét ra `160 mã KHÔNG đổi bậc` · V1 chặn tái phát ở đường ghi |
| Rổ VN30 kỳ 08/2026 | Lấy động (API → cache → hằng số) · VÀO BSR·LPB·MCH·TCX·VPL, RỜI BCM·BVH·PLX·POW·TPB · cả 30 mã có giá trong kho |
| Live mode | `verify_wss_live` ✅ cả 3 bất biến (24/30 mã volume) + **mắt người** xác nhận heatmap chạy |
| Tốc độ heatmap | Fragment 5s → 2s · tầng nóng (VN30 mỗi vòng, ~1.100 mã mỗi 5 vòng) |
| Rủi ro chạm trần task | 166,3′ → 69,0′ ⇒ đệm 13,7′ → **111′** *(số chưa sạch — xem việc #1)* |
| Phát tự động trọn vẹn | 21/08, 24/08, 25/08 đều đủ 14 bước và **có brief Telegram** |
| Chất lượng brief | Guard số chỉ số (trạng từ) · dọn khối tin · GDKHQ không cảnh báo cho ĐHĐCĐ · dải ±3% gọi đúng tên |
| Đồng bộ code | 🖥️ desktop `2.615 passed` = HEAD lúc 26/08 sáng; HEAD nay **3.120** (đợt vá lệch cơ sở + `--whole-series`) |
| `fix-units` đối chứng | 26/08 trên KHO THẬT: `fix_count` khớp, giải nén **ít hơn 1.125×**, bỏ qua **98,6%** mã. Lượt đối chứng còn tìm ra bug HFB (`time` trộn kiểu ⇒ mã bị bỏ sót im lặng) — đã vá (U32) |
| Sổ lệnh | **Không mất** — 805 briefs · 148 rec · 138 outcome |
| BCTC ngân hàng 2015-2016 | **TẠM DỪNG** (user chốt 26/08) — đã đo 5 nguồn: `vci` sớm nhất 2018-Q1 (đúng khung, tốt nhất) · `finhay` trần 5 kỳ · `cafef` có 2015-2016 nhưng **sai khung (doanh nghiệp thường)** · `kbs` rỗng · `tcbs` 404. Muốn data cũ hơn ⇒ user xuất Wichart/FiinPro, Claude viết bộ đọc. **Đừng dò lại** — xem U34 `docs/CLAUDE-NOTES.md` |
| Rác `C:\proc` | **Không tồn tại** — Claude suy nhầm là đã tạo, user kiểm 25/08 ra PathNotFound (U26) |
