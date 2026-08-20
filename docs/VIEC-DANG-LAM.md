# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 20/08/2026.

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

---

## 🔴 GẤP NHẤT — ⇄ CẢ HAI MÁY · 🖥️ desktop ✅ XONG · 💻 laptop ⏳ CHƯA

Code KHÔNG đồng bộ. Máy nào chưa merge là máy đó vẫn chạy bản cũ — và bản cũ
có đúng những lỗi hôm nay vừa vá (bộ chữa kho không hội tụ, tự kiểm mù,
`test_tests_badge_states` đỏ theo giờ trong ngày).

```powershell
cd C:\vnstock
git pull origin claude/tong-hop-cong-viec-test-w8mvrc
python run.py test
```

Phải ra **2.387 passed**. **Chạy `run.py test` NGAY sau khi merge** — đừng để
task 18:00 phát hiện hộ. Bài học 19/08: merge lúc 17:37 rồi để phát 18:00 chạy
full suite ở bước 9, một test đỏ là dừng cứng và **mất brief cả đêm**.

HEAD là `2.387` sau đợt `vnstock_corp_ratio` + guard GDKHQ tự quy đổi.

* 💻 **LAPTOP: ✅ XONG 20/08** — `2387 passed / 120,16s` trên máy thật, khớp CI
  từng test một. Laptop nay **sạch sổ**.
* 🖥️ **DESKTOP: ⏳ CHƯA — nên làm TRƯỚC 18:00 hôm nay (20/08)**, desktop vẫn
  đang ở `2.352`. Hôm nay đúng ngày GDKHQ của VIX: bản `2.352` chỉ cảnh báo
  "mốc CHƯA quy đổi"; bản `2.387` in thẳng `giá tham chiếu ≈ 12,476`. Không
  merge thì brief chiều nay vẫn là bản cảnh báo suông — không sai, chỉ kém.
  **Đừng merge sát 18:00**: chạy full suite xong hẵng thôi (laptop vừa đo
  ~2 phút), bài học 19/08 ngay trên.
* (Lượt merge 19/08 có 1 test đỏ do test PHỤ THUỘC KHO THẬT — đã vá, xem
  `docs/CLAUDE-NOTES.md` mục U18.)

*Ghi chú về bẫy `git pull`: `git pull origin <nhánh>` CÓ tác dụng (nó merge
`origin/<nhánh>` vào nhánh đang đứng). Bẫy "Already up to date" chỉ xảy ra với
`git pull` TRỐNG — khi đó git chỉ nhìn nhánh upstream của `main`.*

---

## 🖥️ DESKTOP — tối mai, sau khi phát 18:00 chạy xong (~19:15)

Đêm mai là phép thử thật của mọi thứ vá hôm nay. Bốn dòng, một lệnh:

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '⏱ TỔNG|⏱ CHẶNG|auto-heal|\[ohlc\]' | Select-Object -Last 10
```

| Dòng | Kỳ vọng | Nếu khác |
|---|---|---|
| `⏱ TỔNG` | **14 bước** (19/08 dừng ở 9) | Còn <14 ⇒ vẫn chết giữa chừng, đọc dòng `hard failure` ngay trên nó |
| `⏱ CHẶNG` | `auto-heal` teo hẳn so với 35,9' | Vẫn ~36' ⇒ chẩn đoán OHLC của Claude SAI, dán số để đọc lại |
| `[ohlc] … nới low/high cho N bar` | Có xuất hiện | Không có ⇒ hoặc nguồn hết bar mâu thuẫn (tốt), hoặc guard chưa chạy |
| `auto-heal: scanned=…` | `scanned` nhỏ hẳn so với 3.844 | Không giảm ⇒ nguồn bơm nằm chỗ khác |

Rồi:

```powershell
python run.py doctor
```
Hai badge MỚI, **vàng là dấu hiệu TỐT** (guard đang làm việc, không phải hỏng):
* **"Lệch cơ sở — mã bị cách ly"** — V1 vừa chặn một mã. Chữa:
  `python scripts\rebase_ticker_history.py --ticker <MÃ> --apply`
* **"Nới OHLC (bar tự mâu thuẫn)"** — in mã, số bar, mức nới rộng nhất so với
  trần 20%. Nới sát trần thì soi lại bar đó.

Và câu hỏi lớn nhất: **Telegram có brief chiều không?** Có = đêm tự động trọn
vẹn ĐẦU TIÊN, mở luôn cổng đang chặn mục "tầng B".

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

**Còn đúng một mục live mode, và nó cần MẮT NGƯỜI, script không thay được**
(W1 trong `docs/CLAUDE-NOTES.md`): heatmap VN30 có số THẬT chạy trong phiên hay
không. Trong **9:15–11:30 hoặc 13:00–14:30**:

```powershell
python run.py dashboard
```
→ sidebar trái bật **🔴 Live Mode → Real-time WSS** → sang tab **Thị trường** →
xem **Live Market Heatmap VN30** có đổi màu ô theo tick không. Đổi màu = xong
hẳn mục live mode.

*Dòng `write tick …: [WinError 5]` thoáng qua rồi tự sạch là **bình thường** —
Dropbox giữ file `_live/quote_*.json` đúng lúc ghi. Đã có retry, mất 1 tick vô
hại. Chỉ báo nếu nó KHÔNG tự sạch sau 15s.*

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

---

## 🟠 VIỆC CỦA CLAUDE — nói "làm đi" là chạy

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| ~~3~~ | ✅ **XONG 19/08** — 10 điểm ghi state chuyển sang nguyên tử, 9 file mới vào lưới `_MUST_BE_ATOMIC` | Gồm cả `fix_units` (ghi đè prices.parquet MỖI ĐÊM) và `screener_results.json` (dashboard poll rồi `json.load` trần) | — |
| ~~9~~ | ✅ **XONG 19/08** — tầng NGẮN KHÔNG chết: `_do_tune` trả dict trống-chỉ-có-error khi không ứng viên nào thắng, nên log in `trades=None`. Nay trả metrics THẬT của chiến lược đang chạy + `tune_note` | Dòng log nói sai chuyện gì đã xảy ra | — |
| ~~10~~ | ✅ **XONG 19/08** — `--sweep` nay LUÔN soi universe backtest (VN30/VNMID) dù dưới ngưỡng GTGD | Ngưỡng GTGD là phỏng đoán; universe chọn theo thành phần chỉ số — khoảng hở giữa hai tiêu chí đi thẳng vào backtest | — |
| 0 | **Đọc số đêm mai rồi mổ tiếp `auto-heal`** — đã chặn trần + chữa nguồn bơm, còn phải xem hàng đợi có teo thật không | Nó từng chiếm 51% cả phát | chờ đo |

---

## ⏳ TỰ ĐẾN — chỉ đọc

* **T7 22/08**: báo cáo model watch (Claude đã ghi sẵn 3 điểm cần soi).
* **Vài đêm tới**: #32 mới 39 lệnh, chỉ hơn sàn 30 đúng 9 — một vòng tune xấu
  là tụt dưới sàn và mục Khuyến nghị tự tắt. Theo dõi, chưa phải làm gì.
