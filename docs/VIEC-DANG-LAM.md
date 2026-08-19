# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 19/08/2026, cuối ngày.

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

Phải ra **2.319 passed**. **Chạy `run.py test` NGAY sau khi merge** — đừng để
task 18:00 phát hiện hộ. Bài học 19/08: merge lúc 17:37 rồi để phát 18:00 chạy
full suite ở bước 9, một test đỏ là dừng cứng và **mất brief cả đêm**.

* 🖥️ **DESKTOP: ✅ xong 19/08** — fast-forward tới `1f9ea0b`, `2.319 passed`
  trên máy thật, khớp CI từng test một.
* 💻 **LAPTOP: ⏳ chưa** — chạy đúng hai lệnh trên khi nào mở máy. Không gấp
  (laptop không có task lịch) nhưng đừng chạy công cụ kho ở đó trước khi merge.

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

**Phân xử NSO / Jina.** Laptop ra NSO ❌ + Jina ⚠️, cả 3 URL đều
`ConnectTimeout`/`ConnectionReset` — lỗi tầng kết nối, chưa kết luận được.
```powershell
python run.py doctor --net
```
Desktop cũng ❌ = nguồn hỏng thật · desktop ✅ = chính sách mạng laptop.

**KHÔNG nâng vnstock trên desktop.** Bản 4.0.6 làm chết mọi lệnh gọi mạng
(`env.py:136 get_hosting_service()` UnboundLocalError), đã trả giá 19/08. Để
laptop soak vài ngày. Khi nâng: không sát 18:00, nâng xong chạy `doctor --net`
+ full suite ngay, hỏng thì `pip install vnstock==4.0.4 vnai==2.4.8`.

---

## 💻 LAPTOP — việc còn treo

**Thử sổ sự kiện quyền có dày lên được không** (CHỈ ĐỌC, không `--register`
nên không ghi gì vào kho):

```powershell
python run.py vietstock --ticker PET --fdate 2026-01-01
python run.py cash-dividends --ticker VNM
```

Vì sao đáng: sổ sự kiện đang mỏng — trong 70 mã lệch cơ sở chỉ **3 mã** tra ra
loại sự kiện. Đó là gốc khiến bộ chữa phải đoán khối lượng bằng heuristic, và
cũng là lý do guard GDKHQ chưa tự quy đổi được mốc giá. Ra sự kiện = đường này
dùng được. Timeout hết = mạng laptop chặn, thử lại trên desktop.

*Nhớ merge trước khi chạy bất cứ công cụ kho nào ở laptop — code không đồng bộ.*

---

## ○ MỘT LẦN — máy nào cũng được

**Trong giờ giao dịch (9h15–14h30, T2–T6)** — mục live mode còn treo, chỉ thiếu
một lần nhìn:
```powershell
python scripts\verify_wss_live.py --duration 120
```
Exit 0 = đạt cả 3 bất biến · 1 = ngoài giờ/thiếu tick (KHÔNG phải fail) · 2 = sai.
Hoặc bằng mắt: dashboard → 🔴 Live Mode ở sidebar → tab **Thị trường**.

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

---

## 🟠 VIỆC CỦA CLAUDE — nói "làm đi" là chạy

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| 0 | **Đọc số đêm mai rồi mổ tiếp `auto-heal`** — đã chặn trần + chữa nguồn bơm, còn phải xem hàng đợi có teo thật không | Nó từng chiếm 51% cả phát | chờ đo |
| 3 | **Ghi JSON nguyên tử** (12 điểm/7 file) + nối vào lưới `_MUST_BE_ATOMIC` | Pipeline đã bị kill 2 lần; bản cụt còn lây sang file dự phòng | ~30' |
| 7 | **Vá gốc lỗ hổng độ tươi** (bị cắt ở `vnstock_brief.py:1095`) | Hết phải kiểm độ tươi brief bằng tay | ~1 buổi |
| 9 | **Tầng NGẮN (#16) đang trắng** — `trades=None`, không đóng góp khuyến nghị nào | Nửa hệ chiến lược đang không chạy mà không ai biết | ~1 buổi |
| 10 | **Điểm mù ngưỡng GTGD của bộ quét** — NTP lệch từ 06/2026 mà chỉ lộ khi thanh khoản nhích qua 5 tỷ | Còn một lớp mã lệch đang chờ sẵn dưới ngưỡng | ~30' |

---

## ❓ CHỜ BẠN QUYẾT

**Q2. Mốc giờ coi là "phiên đã đóng"** — dùng cho việc #7. Đề xuất **15:05**
(khớp mốc screener đang dùng). Đồng ý thì Claude lấy luôn.

---

## ⏳ TỰ ĐẾN — chỉ đọc

* **T7 22/08**: báo cáo model watch (Claude đã ghi sẵn 3 điểm cần soi).
* **Vài đêm tới**: #32 mới 39 lệnh, chỉ hơn sàn 30 đúng 9 — một vòng tune xấu
  là tụt dưới sàn và mục Khuyến nghị tự tắt. Theo dõi, chưa phải làm gì.
