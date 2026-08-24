# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 24/08/2026, cuối ngày.

## 🏷️ NHÃN MÁY — quy tắc gốc: KHO đồng bộ, CODE thì không

`C:\vnstock\data_warehouse` là **Junction** trỏ sang
`E:\Dropbox\vnstock_data\data_warehouse` (xác nhận `Get-Item` 19/08). Repo
`C:\vnstock` đi bằng **git**. Từ đó ra 4 nhãn:

| Nhãn | Nghĩa |
|---|---|
| ○ **MỘT LẦN** | Đụng `data_warehouse` (chữa kho, quét, backtest, sổ lệnh). Dropbox lo phần còn lại — làm ở máy nào cũng được, **đừng làm hai lần**. |
| ⇄ **CẢ HAI** | KHÔNG nằm trong kho: `git merge`, thư viện pip, venv, task lịch, biến môi trường, `run_daily.log`. Phải lặp lại ở từng máy. |
| 🖥️ **DESKTOP** | Chỉ máy chạy pipeline (`PICHU`, 2 task lịch) mới có: log phát đêm, `Get-ScheduledTaskInfo`, brief tự động. |
| 💻 **LAPTOP** | Thử nghiệm rủi ro — hỏng cũng không mất brief đêm (`CFA-BINHLD-LT`, không task). |

**Đang ngồi máy nào** (2 giây; đừng đoán bằng đường dẫn hay tên venv — cả hai
đều `C:\vnstock`, venv đổi theo tài khoản đăng nhập; đã quy sai 3 lần 19/08):

```powershell
$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *' | Select-Object TaskName
```
2 task = **desktop**. Rỗng = **laptop**.

**Quy ước (user chốt 20/08): máy đang ngồi là TRẠNG THÁI DÍNH.** User báo đổi
máy thì mới đổi; không báo thì mặc định vẫn là máy của lượt trước. Lệnh trên
chỉ dùng khi thật sự chưa biết — hỏi lại điều user đã nói cũng là một kiểu quy
sai máy. **Phiên hiện tại: 🖥️ DESKTOP** (user báo 20/08, sau khi làm xong ở laptop).

---

## ✅ HẾT GẤP — 🖥️ DESKTOP đã ở `2.532` (24/08)

`2532 passed / 84,47s`, badge xanh, exit 0. **Phát 18:00 mai chạy trên code
mới** — brief sẽ hết cả 3 lỗi thấy trong bản 24/08 (cảnh báo GDKHQ sai cho
ĐHĐCĐ · khối tin cụt chữ · dải ±3% bị gọi là hỗ trợ/kháng cự).

* 💻 **LAPTOP: ⏳ chưa** — đang ở `2.447`. Không gấp (không có task lịch),
  nhưng đừng chạy công cụ kho ở đó trước khi merge.

```powershell
cd C:\vnstock
git pull origin claude/tong-hop-cong-viec-test-w8mvrc
python run.py test
```

**Chạy `run.py test` NGAY sau khi merge, và KHÔNG merge sát 18:00** — bài học
19/08 VÀ 24/08: `test` là bước 9/14, một test đỏ là `exit 2` dừng cứng, mất
luôn train / reflection / doctor / **brief**.

*Ghi chú về bẫy `git pull`: `git pull origin <nhánh>` CÓ tác dụng (nó merge
`origin/<nhánh>` vào nhánh đang đứng). Bẫy "Already up to date" chỉ xảy ra với
`git pull` TRỐNG — khi đó git chỉ nhìn nhánh upstream của `main`.*

---

## 🖥️ DESKTOP — hai phép đo còn NỢ

### ✅ Câu hỏi lớn nhất đã có đáp án
Phát 18:00 **21/08 chạy trọn và Telegram CÓ brief chiều** — đêm tự động trọn
vẹn đầu tiên, xác nhận bằng chính bản brief user dán lại. Bước 14/14 tới nơi.

### ⏳ NHƯNG bốn dòng số thì chưa ai đọc
Biết "chạy xong" khác với biết "chạy hết bao lâu, vào đâu". Chẩn đoán
`auto-heal` chiếm 51% cả phát vẫn **chưa được kiểm chứng**:

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '⏱ TỔNG|⏱ CHẶNG|auto-heal|\[ohlc\]' | Select-Object -Last 12
```

| Dòng | Kỳ vọng | Nếu khác |
|---|---|---|
| `⏱ TỔNG` | **14 bước** | Còn <14 ⇒ đọc dòng `hard failure` ngay trên nó |
| `⏱ CHẶNG` | `auto-heal` teo hẳn so với 35,9′ | Vẫn ~36′ ⇒ chẩn đoán của Claude SAI, dán số để đọc lại |
| `[ohlc] … nới low/high cho N bar` | Có xuất hiện | Không có ⇒ hoặc nguồn hết bar mâu thuẫn (tốt), hoặc guard chưa chạy |
| `auto-heal: scanned=…` | nhỏ hẳn so với 3.844 | Không giảm ⇒ nguồn bơm nằm chỗ khác |

### ✅ Lượt T7 22/08 — đã chạy lại xong
`run.py weekend` chạy trọn, gửi được cả báo cáo model watch lẫn báo cáo tuần
lãi suất. Hai lỗi TRÌNH BÀY tìm ra ở đó đã vá (U24). **Không còn nợ gì.**

### ✅ Phát T2 24/08 — chạy trọn, có brief
Nhưng chạy trên bản `2.447` nên brief còn 3 lỗi đã vá ở HEAD. Chi tiết U25.

Sau khi merge, chạy:

```powershell
python run.py doctor
```
Badge **vàng là dấu hiệu TỐT** (guard đang làm việc, không phải hỏng): "Lệch
cơ sở — mã bị cách ly" (chữa: `python scripts\rebase_ticker_history.py
--ticker <MÃ> --apply`) · "Nới OHLC (bar tự mâu thuẫn)" · "Sổ theo dõi nghi
ngờ brief" (xem mục 🔔 cuối trang).

---

## 💳 QUYẾT ĐỊNH CỦA USER — Cerebras hết quyền truy cập (402)

Model watch T7 22/08: **Cerebras trả HTTP 402 "Payment required"** ở cả hai
model đang dùng. Đây là **hỏng TÀI KHOẢN, không phải model chết** — đổi slug
không cứu được, mọi model Cerebras sẽ 402 y như vậy.

Hệ thống **KHÔNG chết** (brief 21/08 vẫn ra) nhưng lưới dự phòng mỏng hẳn:

| Điểm | Còn sống |
|---|---|
| [1] sentiment | Gemini → Groq (từ 4 nấc còn 2) |
| [3-6] digest | Gemini + nemotron · Groq×2 → Gemini-lite |
| [7] brief | Gemini (agent CHÍNH) |

⚠️ **Gemini nay gánh cả brief lẫn digest bậc 1 lẫn nấc 1 sentiment** — nghẽn
Gemini là hụt nhiều chỗ cùng lúc.

**Ba lựa chọn, bạn chọn:**
1. **Kệ** — Gemini + Groq đủ chạy. Rẻ nhất, rủi ro tập trung vào Gemini.
2. **Nạp tiền Cerebras** — khôi phục nguyên trạng, không đụng code.
3. **Tìm nhà cung cấp free thay thế** — phải probe SỐNG trên máy thật trước:
   ```powershell
   python scripts\probe_models.py --slug "OpenRouter=<slug>"
   ```
   Ra ✅ thì báo Claude, Claude nối vào thang + lưới.

*(Đã tự xử: `openai/gpt-oss-20b:free` của OpenRouter chết thật — HTTP 404 +
biến mất khỏi danh mục — nên đã gỡ khỏi cả hai thang, thêm vào `_DEAD_SLUGS`,
và sửa một migration đang trỏ vào chính nó. Không thêm slug mới vì quy tắc
repo là phải probe sống trước.)*

---

## 🖥️ DESKTOP — khi rảnh, không gấp

**✅ Đã phân xử NSO / Jina — KHÔNG phải chính sách riêng của laptop.**
Desktop chạy `doctor --net` 19/08 ra **28 ✅ · 1 ⚠️ · 1 ❌**, hỏng đúng hai
nguồn y như laptop: NSO ❌, Jina ⚠️. Loại được giả thuyết "mạng laptop chặn".

⚠️ **Nhưng chưa loại được "mạng NHÀ chặn"** — hai máy nhiều khả năng chung một
đường ra internet, nên phép thử không độc lập. Muốn chốt hẳn thì thử từ mạng
khác (phát 4G từ điện thoại) rồi chạy lại `doctor --net`. Ra ✅ = mạng nhà
chặn · vẫn ❌ = nguồn thật sự hỏng, lúc đó mới đáng sửa code.

**Mức khẩn:** Jina chỉ làm tin chấm bằng title+summary — **không gấp**. NSO thì
có HẠN: các chỉ số CPI / IIP / GDP / cán cân thương mại hiện đang dùng số
`as_of 2026-07-31` từ cache. Kỳ công bố tháng 8 rơi vào cuối tháng — **không
kéo được kỳ đó là brief bắt đầu nói số vĩ mô cũ**, mà doctor KHÔNG báo giúp
(nó chỉ biết "nguồn fetch hỏng", không biết "số trong brief đã lỗi thời").
Còn ~2 tuần.

**Việc cụ thể: phát 4G từ điện thoại, nối máy vào, rồi chạy**
```powershell
python run.py doctor --net
```
NSO ✅ = mạng nhà chặn, xử ở router/ISP, KHÔNG đụng code · vẫn ❌ = nguồn thật
sự đổi, lúc đó mới đáng sửa `vnstock_nso`. Làm trong 2 tuần tới là kịp.

**📦 vnstock 4.0.7 ĐÃ RA (thấy trong log 24/08) — cổng gỡ chặn đã mở.**
Quy trình đã chốt, làm ĐÚNG THỨ TỰ:
1. 💻 **Laptop TRƯỚC**: `pip install vnstock==4.0.7` → `python run.py doctor --net`
   + `python run.py test` NGAY.
2. Chạy vài ngày xem có gì lạ.
3. Chỉ khi laptop sạch mới đụng 🖥️ desktop, và **không nâng sát 18:00**.
4. Hỏng thì lùi: `pip install vnstock==4.0.4 vnai==2.4.8`.

Desktop giữ 4.0.4 — nó là máy chạy phát tối, không phải chỗ để thử.

**⛔ vnstock 4.0.6 BỊ CHẶN — không nâng máy nào cả.** Bản đó làm chết mọi
lệnh gọi mạng (`env.py:136 get_hosting_service()` UnboundLocalError). Laptop
đã nâng thử 19/08 rồi **phải lùi ngay** về 4.0.4 / vnai 2.4.8 để chạy được
probe; desktop chưa từng nâng.

⚠️ Sửa ghi chú sai: từng ghi "laptop XONG, desktop chờ soak" — **không có cuộc
soak nào cả**, cả hai máy đều đang ở 4.0.4 (xác nhận 19/08 qua warning pytest
trên cả hai). Mục này KHÔNG chờ thời gian, nó chờ **bản vá của nhà cung cấp**.

Khi 4.0.7+ ra: nâng ở 💻 **laptop trước**, chạy `doctor --net` + full suite
ngay, chạy được vài ngày rồi mới đụng desktop, và **không nâng sát 18:00**.
Hỏng thì lùi: `pip install vnstock==4.0.4 vnai==2.4.8`.

---

## 💻 LAPTOP — sau khi merge thì HẾT việc riêng

**Việc treo cuối cùng của laptop đã xong 19/08.** `run.py vietstock` **chạy
được** và trả tỉ lệ quyền có cấu trúc: PET ra `20:1` + `5:2` cùng ngày 09/07
⇒ hệ số 1.45, khớp 1.4499× mà bộ chữa kho đo độc lập từ giá (lệch 0,007%) —
xác nhận độc lập cho toàn bộ chẩn đoán lệch cơ sở. Kết quả đó đã thành code:
`vnstock_corp_ratio` đọc tỉ lệ từ tiêu đề sự kiện, guard GDKHQ nay **tự quy
đổi** mốc giá thay vì chỉ cảnh báo.

`run.py cash-dividends` thì **hỏng** (CafeF 404) — nhưng Vietstock đã trả cả
sự kiện tiền mặt nên đường đó nhiều khả năng thừa; Claude sẽ quyết bỏ hay giữ,
KHÔNG cần user thử lại. Chi tiết: mục U19 trong `docs/CLAUDE-NOTES.md`.

⇒ Việc bắt buộc cuối cùng — **merge + `run.py test`** — cũng đã xong 20/08
(`2387 passed`). **Laptop hiện KHÔNG còn việc riêng nào**; mọi thứ còn lại đều
là ○ (máy nào cũng được) hoặc 🖥️ desktop.

*Nhớ merge trước khi chạy bất cứ công cụ kho nào ở laptop — code không đồng bộ.*

---

## ○ MỘT LẦN — máy nào cũng được

**✅ `verify_wss_live` ĐẠT CẢ 3 — 20/08, cửa sổ 09:59:51 → 10:04:51.**
`24/30 mã volume > 0` (top HDB 31,600 · FPT 24,900 · SSB 8,400) · index/futures
im lặng đúng thiết kế · `suspect_count = 0`. Mục 1 của checklist live mode
**đóng**. (Lượt 120s trước đó ⚠️ vì đo trúng khung không khớp lệnh — xem U20.)

**✅ W1 (mắt người) cũng XONG 20/08 — heatmap CHẠY.** Và chính lượt nhìn đó
bắt được **hai lỗi mà script không thể thấy** (mục U21): rổ VN30 vẽ **rổ CŨ**
(HOSE đã đổi rổ) và phản hồi chậm. Cả hai đã vá — xem ⬇️.

### ✅ RỔ VN30 ĐÃ XONG HẲN (20/08)

Rổ kỳ tháng 8/2026 đã đo trên máy thật, hằng số ở cả 3 file đã sửa, và
`--diag` xác nhận **✅ rổ sống 30 mã · ✅ khớp hằng số · ✅ cả 30 mã đều có giá
trong kho**:

| VÀO rổ | RỜI rổ |
|---|---|
| BSR · LPB · MCH · TCX · VPL | BCM · BVH · PLX · POW · TPB |

Cache `_meta/vn30_members.json` đã ghi (💾 xác nhận 20/08) ⇒ dashboard/brief
không gọi API nữa trong 7 ngày, và **desktop hưởng luôn qua Dropbox** — không
phải làm lại ở máy kia. **Mục này đóng.**

**✅ TCX đã tra xong:** = CTCP Chứng khoán Kỹ Thương (Techcom Securities /
TCBS), niêm yết HOSE 21/10/2025. Đã điền `securities` — và bổ sung vào
`_FINANCIAL_TICKERS`, chỗ suýt bỏ sót: thiếu đó thì brief gọi tên một công ty
chứng khoán như "rủi ro cơ bản" chỉ vì đòn bẩy kiểu định chế tài chính. Có
lưới canh để kỳ đổi rổ sau không lặp lại.

---

## ✅ ĐÃ XONG 19/08 — không phải làm lại

| Việc | Kết quả |
|---|---|
| Lệch cơ sở kho giá | **76 mã** đã chữa · quét ra `160 mã: KHÔNG đổi bậc` |
| V1 chặn tái phát | `vnstock_basis_guard` ở đường ghi chính + badge + kill-switch |
| Kiểm định #32 | Chấm lại trên kho sạch — **vẫn ĐẠT** (39 lệnh, expectancy 3.02, p=0.012, TP 51%). ⚠️ tầng NGẮN (#16) đang trắng |
| Bộ chữa kho | Vá 2 lỗi: không hội tụ với mã đa bậc · tự kiểm mù đúng lớp lỗi nó chữa |
| Guard GDKHQ | Mốc giá mã sắp chốt quyền tự nói "chưa quy đổi" (ca VIX 20/08) |
| Độ chính xác giá brief | `_fmt_rec_price` giữ 1 thập phân dải 10-100 |
| Nới OHLC | Bar tự mâu thuẫn hết rơi vào hàng đợi cách ly |
| auto-heal | Trần 600s + dọn ngay bar vắng cấu trúc |
| Hạ tầng | Log xoay vòng · retry ghi nguyên tử · de-dup loader backtest |
| Trần task Daily | `PT3H` |
| Sổ lệnh | **Không mất** — 805 briefs · 148 rec · 138 outcome |
| Live mode (20/08) | `verify_wss_live` **✅ đạt cả 3 bất biến** trong phiên (24/30 mã có volume, index im lặng, suspect = 0). Bộ chấm nay biết lịch phiên |
| W1 mắt người (20/08) | Heatmap **chạy thật**. Lượt nhìn bắt được 2 lỗi script không thấy: rổ VN30 cũ · phản hồi chậm — đã vá (U21) |

---

## 🟠 VIỆC CỦA CLAUDE — nói "làm đi" là chạy

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| ~~3~~ | ✅ **XONG 19/08** — 10 điểm ghi state chuyển sang nguyên tử, 9 file mới vào lưới `_MUST_BE_ATOMIC` | Gồm cả `fix_units` (ghi đè prices.parquet MỖI ĐÊM) và `screener_results.json` (dashboard poll rồi `json.load` trần) | — |
| ~~9~~ | ✅ **XONG 19/08** — tầng NGẮN KHÔNG chết: `_do_tune` trả dict trống-chỉ-có-error khi không ứng viên nào thắng, nên log in `trades=None`. Nay trả metrics THẬT của chiến lược đang chạy + `tune_note` | Dòng log nói sai chuyện gì đã xảy ra | — |
| ~~10~~ | ✅ **XONG 19/08** — `--sweep` nay LUÔN soi universe backtest (VN30/VNMID) dù dưới ngưỡng GTGD | Ngưỡng GTGD là phỏng đoán; universe chọn theo thành phần chỉ số — khoảng hở giữa hai tiêu chí đi thẳng vào backtest | — |
| 0 | **Mổ tiếp `auto-heal`** — đã chặn trần + chữa nguồn bơm, còn phải xem hàng đợi có teo thật không | Nó từng chiếm 51% cả phát | chờ user dán `⏱ CHẶNG` |
| 1 | **Nối pivot THẬT vào mốc watchlist** (`vnstock_strategy._ticker_pivots`, 60 bar, bỏ 2 bar cuối) ở tầng dựng ctx — rồi mới được gọi là hỗ trợ/kháng cự | Hiện mốc là dải ±3%, đã gọi đúng tên nhưng vẫn là số vô nghĩa về kỹ thuật (U23) | 1 buổi |
| 2 | **Bỏ hay giữ đường CafeF `cash-dividends`** (404 từ 19/08) — Vietstock đã trả cả sự kiện tiền mặt | Code chết trông như code sống | nhỏ |

---

## 🔔 SỔ TỰ NHẮC — không phải việc gõ tay

Ba nghi ngờ từ đợt soi brief 21/08 nay **máy tự theo dõi**, bạn không phải nhớ:

| Nghi ngờ | Cơ chế nhắc |
|---|---|
| Op.CF quá lớn so với vốn hoá (KBC 0,83×) | Mỗi phiên brief tự ghi vào `_meta/brief_watch.json` |
| Câu "khối ngoại bán ròng nhóm X" ngược data (ca SSI) | như trên |

Badge **"Sổ theo dõi nghi ngờ brief"** trong `python run.py doctor`:
* `✅ … chưa nhặt được nghi ngờ nào` → im lặng, không phải làm gì.
* `✅ … CHƯA đủ mẫu (cần ≥5 phiên)` → đang đếm, **cố ý chưa kết luận**.
* `⚠️ … ĐỦ mẫu, đáng quyết` → **lúc đó mới gọi Claude**, dán nguyên dòng badge.
  Quyết xong thì xoá `_meta/brief_watch.json` để đếm lại.

Tắt hẳn: `VNSTOCK_BRIEF_WATCH=0`.

**Việc mở của Claude (không cần bạn làm gì):** nối pivot thật
(`vnstock_strategy._ticker_pivots`) vào mốc watchlist, để chúng được gọi là
hỗ trợ/kháng cự một cách trung thực. Hiện tại chúng là dải ±3% và **đã được
gọi đúng tên** — xem `docs/CLAUDE-NOTES.md` mục U23.

---

## ⏳ TỰ ĐẾN — chỉ đọc

* **✅ T7 22/08**: model watch đã ra — Cerebras 402, OpenRouter gỡ slug. Xem
  mục 💳 phía trên (cần bạn quyết một việc).
* **Vài đêm tới**: #32 mới 39 lệnh, chỉ hơn sàn 30 đúng 9 — một vòng tune xấu
  là tụt dưới sàn và mục Khuyến nghị tự tắt. Theo dõi, chưa phải làm gì.
  *(Close 24/08 báo **14 lệnh ẩn** — tăng từ 11 hôm 21/08, tức chiến lược
  nguồn vẫn CHƯA đạt kiểm định. Đó là cổng đang đóng, không phải lỗi.)*
* **T7 29/08**: kỳ model watch kế tiếp — báo cáo sẽ dùng bản mới, gộp lỗi
  TÀI KHOẢN thành một dòng 🏦 thay vì n dòng ❌ (U24).
