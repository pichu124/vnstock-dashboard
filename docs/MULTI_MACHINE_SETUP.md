# Setup VnStock Dashboard trên máy thứ 2 (Desktop)

Hướng dẫn cài đặt vnstock_dashboard trên máy desktop khi đã có máy laptop chạy sẵn, dùng chung Dropbox folder.

## Bối cảnh

- **Máy 1 (Laptop)**: đã setup xong, có `.venv`, scheduled tasks đã chạy
- **Máy 2 (Desktop)**: chưa setup, muốn chạy cùng pipeline
- **Shared**: `C:\Users\<user>\Dropbox\Claude vnstock\` sync qua Dropbox
- **Coordination**: `data_warehouse/_meta/pipeline_status.json` điều phối — chỉ 1 máy chạy rollup/updater mỗi ngày, máy còn lại skip

---

## Checklist trước khi bắt đầu

- [ ] Desktop đã cài Python 3.10+ (`python --version`)
- [ ] Desktop đã cài Git
- [ ] Dropbox đã sync xong folder `Claude vnstock/`
- [ ] Có API key vnstock Golden sponsor (từ máy laptop): `vnstock_423e2d521631063b3a55ad4b356a884a`
- [ ] Golden tier còn slot device (6 thiết bị tổng, laptop đã chiếm 1)

---

## Bước 1: Mở PowerShell và vào project

```powershell
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
```

Kiểm tra git đã hoạt động:
```powershell
git status
git pull origin claude/pull-latest-code-rmAx6
```

Nếu git chưa config identity:
```powershell
git config user.name "Your Name"
git config user.email "you@example.com"
```

---

## Bước 2: Exclude `.venv` khỏi Dropbox sync ⚠️ QUAN TRỌNG

Venv có hàng ngàn file Python binary, **KHÔNG nên sync** qua Dropbox (chậm, dễ lỗi).

**Cách 1 — Dropbox Selective Sync:**
1. Click icon Dropbox ở system tray → Preferences
2. Tab **Sync** → **Selective Sync** → Settings
3. Tìm `Claude vnstock` → bỏ tick `.venv` (nếu có)
4. OK → chờ Dropbox unsync xong

**Cách 2 — Dùng tên venv khác nhau mỗi máy:**
- Laptop: `.venv` (đã có)
- Desktop: `.venv-desktop`

Ưu điểm: không cần cấu hình Dropbox selective sync. Nhược điểm: phải sửa script mỗi máy.

Chọn **Cách 1** cho đơn giản (khuyến nghị).

---

## Bước 3: Tạo venv NGOÀI Dropbox folder

**Quan trọng:** KHÔNG tạo venv trong Dropbox folder! Dropbox Smart Sync tạo placeholder files (online-only) khiến venv bị hỏng — `Test-Path` trả True nhưng file thật không tồn tại.

```powershell
# Tạo folder ngoài Dropbox
mkdir C:\venvs -Force

# Tạo venv ở path an toàn
python -m venv C:\venvs\vnstock-desktop

# Kích hoạt
C:\venvs\vnstock-desktop\Scripts\Activate.ps1
```

Nếu bị lỗi `execution of scripts is disabled`:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
Nhập `Y` để confirm, rồi chạy lại `Activate.ps1`.

Verify venv active:
```powershell
python -c "import sys; print(sys.prefix)"
# Expected: C:\venvs\vnstock-desktop
```

**Lưu ý path thật của Dropbox:** Nếu `C:\Users\admin\Dropbox` là symlink (trỏ tới `E:\Dropbox`), luôn dùng path thật `E:\Dropbox\Claude vnstock` để tránh lỗi junction khi tạo venv.

---

## Bước 4: Cài vnstock sponsor qua GUI installer

**Quan trọng:** Cài vnstock requirements **TRƯỚC** khi chạy GUI installer, nếu không uv sẽ fail do DLL locking trên Windows:

```powershell
python -m pip install --upgrade pip

# Bước 4a: Cài dependencies trước (BẮT BUỘC)
pip install -r https://vnstocks.com/files/requirements.txt

# Bước 4b: Cài installer
pip install --extra-index-url https://vnstocks.com/api/simple vnstock_installer
python -m vnstock_installer
```

GUI sẽ mở trong trình duyệt (bỏ qua lỗi "No module named pandas" trong terminal — đó là non-fatal):

| Field | Giá trị |
|---|---|
| **Phiên bản Python** | Mặc định (3.14 hoặc version đang dùng) |
| **Sử dụng môi trường ảo** | ✓ (tick) |
| **Đường dẫn môi trường ảo** | `C:\venvs\vnstock-desktop` |
| **API Key** | `vnstock_423e2d521631063b3a55ad4b356a884a` |
| **Gói cài đặt** | Tick hết 4 gói (Data, TA, News, Pipeline) |

Click **Tiếp Tục** rồi chờ cài xong (~2-5 phút).

**Lưu ý device limit:** Golden tier cho phép 2 thiết bị per OS. Nếu báo lỗi "You have 2 registered", vào https://vnstocks.com → Account → xoá device cũ rồi retry.

---

## Bước 5: Cài dependencies bổ sung cho dashboard + WSS

```powershell
pip install streamlit plotly pytz websocket-client flask lxml schedule scipy html2text
```

Kiểm tra import:
```powershell
python -c "import vnstock_data, vnstock_ta, vnstock_news, vnstock_pipeline, streamlit, pyarrow; print('All packages imported successfully!')"
```

---

## Bước 6: Verify vnstock sponsor tier

```powershell
python -c "from vnstock.core.utils.auth import check_status; print(check_status())"
```

Expected: `tier: 'golden'` (hoặc tier hiện tại của bạn).

Nếu báo lỗi device limit, login lại qua https://vnstocks.com hoặc liên hệ support.

---

## Bước 7: Test scripts hoạt động

Chạy health check:
```powershell
python vnstock_wss.py --health-check
```

Chạy rollup dry-run:
```powershell
python vnstock_rollup.py --dry-run
```

Nếu không có bars file hôm nay → thấy message "đã archive sẵn (máy khác đã chạy)" hoặc "không tồn tại" — cả 2 đều OK, chỉ là test module load được.

---

## Bước 8: Setup Windows Scheduled Tasks (PowerShell ADMIN)

**Đóng PowerShell hiện tại**. Mở PowerShell as Admin:

1. **Right-click** Start menu → **"Windows PowerShell (Admin)"** hoặc **"Terminal (Admin)"** (Win 11)
2. Accept UAC prompt

Trong PowerShell Admin:
```powershell
cd "E:\Dropbox\Claude vnstock"   # Dùng path THẬT, không qua symlink

# Preview trước (không cần Admin thật)
.\scripts\setup_scheduled_tasks.ps1 -DryRun -PythonExe "C:\venvs\vnstock-desktop\Scripts\python.exe"

# Tạo thật
.\scripts\setup_scheduled_tasks.ps1 -PythonExe "C:\venvs\vnstock-desktop\Scripts\python.exe"
```

**Lưu ý:** `-PythonExe` cần vì venv nằm ngoài project folder (không tự detect được).

Expected output:
```
Using custom Python: C:\venvs\vnstock-desktop\Scripts\python.exe

=== Setting up VnStock Scheduled Tasks ===
Hostname:     DESKTOP-PICHU
Project root: E:\Dropbox\Claude vnstock
Python:       C:\venvs\vnstock-desktop\Scripts\python.exe

Multi-machine mode: tasks will skip if another machine
has already completed today's job (checks pipeline_status.json).

---- VnStock Daily Rollup ----
  Trigger:   Daily at 15:30, Mon-Fri
  Command:   ... vnstock_rollup.py --skip-if-done
  [OK] Created

---- VnStock Daily Updater ----
  Trigger:   Daily at 18:00, Mon-Fri
  Command:   ... vnstock_updater.py --force --skip-if-done
  [OK] Created
```

---

## Bước 9: Verify tasks đã tạo

```powershell
Get-ScheduledTask -TaskName "VnStock *" | Format-Table TaskName, State, @{Label="NextRun";Expression={(Get-ScheduledTaskInfo $_).NextRunTime}}
```

Expected:
```
TaskName              State NextRun
--------              ----- -------
VnStock Daily Rollup  Ready <ngày kế tiếp thứ 2-6> 3:30:00 PM
VnStock Daily Updater Ready <ngày kế tiếp thứ 2-6> 6:00:00 PM
```

---

## Bước 10: Test manual trigger

```powershell
Start-ScheduledTask -TaskName "VnStock Daily Rollup"

# Đợi 1 phút rồi check kết quả
Start-Sleep -Seconds 60
Get-ScheduledTaskInfo -TaskName "VnStock Daily Rollup" | Select LastRunTime, LastTaskResult
```

Expected:
- `LastTaskResult: 0` = success
- `LastTaskResult: 267009` = đang chạy, đợi thêm
- `LastTaskResult != 0` = lỗi, xem Event Viewer

---

## Kiểm tra coordination giữa 2 máy

Sau vài ngày làm việc, kiểm tra pipeline_status:
```powershell
Get-Content data_warehouse\_meta\pipeline_status.json
```

Sẽ thấy thay đổi theo ngày:
```json
{
  "rollup": {
    "last_success_date": "2026-04-15",
    "last_run_at": "2026-04-15T15:30:22",
    "last_machine": "LAPTOP-ABC",     // Máy chạy thật hôm 15
    ...
  }
}
```

Ngày hôm sau có thể là `DESKTOP-PICHU` nếu desktop bật trước laptop lúc 15:30.

---

## Troubleshooting

### Dropbox conflict files xuất hiện
```
prices (DESKTOP-PICHU's conflicted copy 2026-04-15).parquet
```
→ Có nghĩa 2 máy đã write cùng lúc. Xoá file conflict, giữ file gốc:
```powershell
Get-ChildItem -Recurse -Filter "*conflicted copy*" | Remove-Item
```

Nếu xảy ra liên tục, tăng jitter trong `vnstock_rollup.py` line ~500: `random.uniform(0, 60)` thay vì `(0, 30)`.

### Scheduled task "Access is denied" khi Register
→ PowerShell chưa chạy as Administrator. Xem Bước 8.

### `python -m vnstock_installer` GUI không mở
→ Kiểm tra venv đã activate chưa. Re-run `.\.venv\Scripts\Activate.ps1`.

### Task chạy lúc 15:30 nhưng không có output
→ Task chạy trong background, không hiện terminal. Xem log qua:
```powershell
Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -MaxEvents 20 | Where-Object { $_.Message -match "VnStock" }
```

### Muốn xoá tasks để cài lại
```powershell
.\scripts\setup_scheduled_tasks.ps1 -Remove
```

---

## Lịch chạy tự động

| Thời điểm | Task | Làm gì |
|---|---|---|
| **15:30** Mon-Fri | VnStock Daily Rollup | Merge 1m bars → warehouse (máy nào chạy trước, máy kia skip) |
| **18:00** Mon-Fri | VnStock Daily Updater | Fetch missing daily data từ API (máy nào chạy trước, máy kia skip) |

**Lưu ý:** `vnstock_wss.py` (live polling 9:00-15:00) vẫn cần chạy manual nếu muốn real-time trong phiên. Task Scheduler không phù hợp cho daemon 6 tiếng.

---

## Nếu muốn chạy live polling trên desktop

Trong giờ giao dịch, mở PowerShell (không cần Admin):
```powershell
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
.\.venv\Scripts\Activate.ps1
python -m streamlit run vnstock_dashboard.py
```

Dashboard sẽ tự start WSS client khi bạn toggle "🔴 Live Mode" ở sidebar tab Phân tích.

**Không chạy WSS polling trên CẢ 2 máy cùng lúc** — sẽ tốn gấp đôi rate limit Golden tier (hiện dùng ~3% quota/máy, 2 máy = 6%, vẫn OK nhưng không cần thiết).
