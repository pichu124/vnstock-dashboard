# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Đây là bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) nằm ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 18/08/2026.

---

## 🔴 VIỆC CỦA BẠN — làm trên DESKTOP `C:\vnstock`

### ⏰ GẤP — làm TRƯỚC 18:00 bất kỳ ngày làm việc nào

Nếu bỏ qua, task đêm vẫn có nguy cơ bị Windows chấm dứt trước bước brief.

```powershell
cd C:\vnstock
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc
```

Rồi mở PowerShell **quyền Administrator**:

```powershell
$t = Get-ScheduledTask -TaskName 'VnStock Daily Pipeline'
$t.Settings.ExecutionTimeLimit = 'PT180M'
Set-ScheduledTask -TaskName 'VnStock Daily Pipeline' -Settings $t.Settings
(Get-ScheduledTask -TaskName 'VnStock Daily Pipeline').Settings.ExecutionTimeLimit
```
Dòng cuối phải in `PT3H` (hoặc `PT180M`). Xong thì **để yên máy qua 18:00**.

*Vì sao:* phát gần nhất chạy hết **96,6 phút mới tới bước 9/14** (sync 60' +
screener 28'), còn 4 bước nữa mới tới brief → dư địa chỉ 16 phút dưới trần 120.
Một đêm sync phình như 17/08 (74') là vượt trần. Đã sửa sẵn trong
`setup_scheduled_tasks.ps1` (commit 943e5ea) nhưng file đó chỉ có tác dụng khi
đăng ký lại task — lệnh trên là đường tắt.

### Sáng hôm sau — kiểm 1 phút (nay có thêm 1 dòng đáng xem)

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern 'CHANG|CHẶNG' | Select-Object -Last 3
```
Dòng `[sync] ⏱ CHẶNG …` nói sync tiêu 60 phút vào chặng nào (updater / rollup /
fix-units / auto-heal). Dán cho Claude — đây là số còn thiếu để chữa đúng chỗ.

### Brief chiều — kiểm 1 phút

Telegram có brief chiều không? **Có** = đêm tự động trọn vẹn ĐẦU TIÊN (mở luôn
cổng đang chặn mục "tầng B"). **Không** → chạy lệnh này rồi dán cho Claude:

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '[brief]' -SimpleMatch | Select-Object -Last 5
Get-Content C:\vnstock\run_daily.log -Tail 15
```

### Khi rảnh — 1 lệnh (nợ treo từ 07/08)

```powershell
python vnstock_classifier.py --classify --limit 20
```
Soi: không còn đòi `ANTHROPIC_API_KEY`, có dòng route "ladder free". Dán kết quả.

### Chỉ làm được TRONG GIỜ GIAO DỊCH (9h15–14h30, T2–T6)

Mở dashboard → bật 🔴 **Live Mode** ở sidebar trái → tab **Thị trường**. Xác nhận
heatmap VN30 có số nhảy thật. (Code + Playwright đã xong, chỉ thiếu một lần nhìn.)

### ĐỪNG làm bây giờ

Nâng vnstock 4.0.4→4.0.6 / vnai 2.4.8→2.5.7 / vnii 0.2.4→0.2.5 (máy đã báo có
bản mới). Để sau khi pipeline chạy trót lọt một đêm đã — nâng lúc này là thêm
một biến số vào đúng lúc đang gỡ.

---

## ✅ ĐÃ CHỐT — không phải làm lại

* **Vì sao brief không gửi**: pipeline **chết ở bước `test` (9/14)** với
  `rc=2 → stopping`, nên train/reflection/doctor/brief chưa bao giờ được gọi.
  Không phải bị bỏ qua, không phải kill-switch, không phải marker.
* **Test đó nay ĐÃ XANH trên máy thật** (`18 passed`) — phát chết là chạy trên
  code cũ trước khi merge. Đêm tới sẽ đi qua được bước 9.
* **Máy không thiếu code**: HEAD đã ở đúng commit mới nhất.
* **Log đã bị tự cắt** (còn 1,19 MB) → bằng chứng các phát trước MẤT. Nguyên
  nhân nằm ở việc #1 của Claude bên dưới.

---

## 🟠 VIỆC CỦA CLAUDE — bạn chỉ cần nói "làm đi"

Xếp theo thứ tự nên làm. Mỗi việc xong Claude chạy `run.py test --fast`, bạn chỉ
cần `git fetch origin <nhánh> && git merge origin/<nhánh>` rồi chạy lại test trên máy thật.

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| 0 | ⏳ **Mổ `sync` 60 phút** — đã cắm đồng hồ từng chặng (`a83ee51`), **chờ số đêm nay** | Chiếm 62% thời gian chạy. Nghi phạm số 1: `fix-units` quét TOÀN KHO mỗi đêm | chờ đo |
| ~~1~~ | ✅ **XONG 19/08** (`970a504`) — test hết ghi bẩn `run_daily.log` | Đo lại: chạy full suite xong log không đổi **một byte** | — |
| ~~2~~ | ✅ **XONG 19/08** (`a83ee51`) — rec hết bị đóng sớm; lệnh thủng SL nay nhận ra ngay thay vì chờ hết horizon | Verdict #32 từ nay chấm trên đúng khung | — |
| 3 | **Ghi JSON nguyên tử** (12 điểm/7 file) + nối vào lưới `_MUST_BE_ATOMIC` | Pipeline đã bị kill 2 lần; bản cụt còn lây sang file dự phòng | ~30' |
| ~~4~~ | ✅ **XONG 19/08** (`970a504`) — 3 test bộ công cụ đơn vị giá đã vào `--fast` | `--fast` nay 1.636 test | — |
| 5 | **Doctor soi kill-switch** (`VNSTOCK_PIPELINE_BRIEF`…) | Chính ẩn số của Bước 1 lẽ ra phải có badge báo | ~30' |
| 6 | **`telegram close` phải có cửa gác** | Gõ 2 lần = 2 brief; gõ trước 15:00 = câm brief tối đó | ~30' |
| 7 | **Vá gốc lỗ hổng độ tươi** (giờ bị cắt ở `vnstock_brief.py:1095`) | Vá xong thì khỏi phải làm Bước 2 bằng tay nữa | ~1 buổi |

---

## ❓ CHỜ BẠN QUYẾT — Claude không code cho tới khi có câu trả lời

**Q1. Guard chặn tái phát lệch cơ sở** (việc kỹ thuật đáng nhất còn lại).
Đường VCI chính đang ghi đè kho im lặng, không đối chiếu gì. Cần chốt 3 điều:
* Lệch bao nhiêu % thì coi là đáng ngờ? (nhánh fallback đang dùng 8%)
* Có tra lịch sự kiện quyền trước khi báo động không? (tránh báo nhầm ngày GDKHQ)
* Gặp nghi vấn thì **cách ly + cảnh báo**, hay chỉ **ghi log cảnh báo** rồi vẫn ghi?

**Q2. Mốc giờ coi là "phiên đã đóng"** — dùng cho việc #7 ở trên. Đề xuất 15:05
(khớp mốc mà screener đang dùng). Đồng ý thì Claude lấy luôn.

---

## ⏳ TỰ ĐẾN — không phải làm gì, chỉ đọc

* **T7 22/08**: báo cáo model watch. Claude đã ghi sẵn 3 điểm cần soi + cảnh báo
  "sửa cái này sẽ làm đỏ test nào".
* **2-3 đêm nữa**: sync phải xuống < ~10 phút. Không teo thì mổ bước heal, hoặc
  nới trần 120 phút của task (nghi phạm chính khiến đêm tự động chưa lần nào
  chạy tới brief).
* **Vài tuần**: #32 tự chứng minh bằng lệnh live (nhưng xem việc #2 — verdict
  hiện đang bị chấm trên khung ngắn hơn thiết kế).
