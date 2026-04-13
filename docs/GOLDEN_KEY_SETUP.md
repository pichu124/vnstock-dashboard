# Hướng dẫn Setup & Bảo vệ Golden Key — Desktop + Laptop

> Cập nhật: 2026-04-14 (sau khi fix bug Golden key bị reset)

---

## Thông tin chung

| Item | Giá trị |
|------|---------|
| **Golden API Key** | `vnstock_423e2d521631063b3a55ad4b356a884a` |
| **Tier** | Golden — 500 requests/phút |
| **Device limit** | 2 thiết bị per OS (tổng 6) |
| **Desktop** | User `admin`, Python `C:\Python314`, Venv `C:\Users\admin\.venv` |
| **Laptop** | User `Administrator`, Project `C:\Users\Administrator\Dropbox\Claude vnstock` |
| **Shared folder** | Dropbox `Claude vnstock` — sync giữa 2 máy |
| **Git branch** | `claude/pull-latest-code-ntmnb` |

---

## ⚠️ CẢNH BÁO: Tại sao Golden key bị mất

**Nguyên nhân gốc:** Thư viện `vnstock` (free) có hàm `change_api_key()` sẽ **ghi đè** authentication của `vnstock_data` (Sponsor), đưa về Community tier (60 req/phút).

**Quy tắc bắt buộc:**
1. **KHÔNG BAO GIỜ** gọi `change_api_key()` khi đã có `vnstock_data` Sponsor
2. **LUÔN** dùng venv (nơi có `vnstock_data`) để chạy mọi script
3. **KHÔNG** dùng Python chính (`C:\Python314\python.exe`) — nó không có `vnstock_data`
4. Code đã fix trong `vnstock_auth.py` — tự động skip `change_api_key()` khi detect `vnstock_data`

---

## Setup Desktop từ đầu (nếu cần làm lại)

### Bước 1: Vào project folder

```powershell
cd "E:\Dropbox\Claude vnstock"
git checkout claude/pull-latest-code-ntmnb
git pull
```

### Bước 2: Tạo venv (nếu chưa có)

**KHÔNG tạo trong Dropbox folder** — Dropbox Smart Sync sẽ hỏng venv.

```powershell
python -m venv "C:\Users\admin\.venv"
```

### Bước 3: Kích hoạt venv

```powershell
& "C:\Users\admin\.venv\Scripts\Activate.ps1"
```

Prompt sẽ hiện `(.venv)` ở đầu. **Từ đây mọi lệnh `python` đều dùng venv.**

### Bước 4: Cài vnstock Sponsor qua GUI installer

```powershell
pip install --upgrade pip
pip install -r https://vnstocks.com/files/requirements.txt
pip install --extra-index-url https://vnstocks.com/api/simple vnstock_installer
python -m vnstock_installer
```

Khi GUI mở:

| Field | Giá trị |
|-------|---------|
| Phiên bản Python | Mặc định |
| Sử dụng môi trường ảo | ✅ Tick |
| Đường dẫn môi trường ảo | `C:\Users\admin\.venv` |
| API Key | `vnstock_423e2d521631063b3a55ad4b356a884a` |

Nhấn **Tiếp Tục** → chọn hết 4 gói → **Bắt Đầu Cài Đặt**.

### Bước 5: Cài dependencies bổ sung

```powershell
pip install streamlit plotly pyarrow rich tqdm python-dotenv pytz
```

### Bước 6: Verify Golden tier

```powershell
python -c "from vnstock.core.utils.auth import check_status; print(check_status())"
```

**Phải thấy:** `tier: golden`, `per_minute: 500`

### Bước 7: Update file .env

```powershell
Set-Content -Path "E:\Dropbox\Claude vnstock\.env" -Value "VNSTOCK_API_KEY=vnstock_423e2d521631063b3a55ad4b356a884a"
```

### Bước 8: Test chạy

```powershell
cd "E:\Dropbox\Claude vnstock"

# Test updater
python vnstock_updater.py --force

# Test dashboard
python -m streamlit run vnstock_dashboard.py
```

---

## Setup Laptop (tương tự)

### Khác biệt so với Desktop

| Item | Desktop | Laptop |
|------|---------|--------|
| User | `admin` | `Administrator` |
| Project path | `E:\Dropbox\Claude vnstock` | `C:\Users\Administrator\Dropbox\Claude vnstock` |
| Venv path | `C:\Users\admin\.venv` | Cần tạo mới (ví dụ `C:\Users\Administrator\.venv`) |

### Các bước

```powershell
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
git checkout claude/pull-latest-code-ntmnb
git pull

# Tạo venv
python -m venv "C:\Users\Administrator\.venv"
& "C:\Users\Administrator\.venv\Scripts\Activate.ps1"

# Cài Sponsor (GUI installer)
pip install --upgrade pip
pip install -r https://vnstocks.com/files/requirements.txt
pip install --extra-index-url https://vnstocks.com/api/simple vnstock_installer
python -m vnstock_installer
# → Đường dẫn venv: C:\Users\Administrator\.venv
# → API Key: vnstock_423e2d521631063b3a55ad4b356a884a

# Cài dependencies
pip install streamlit plotly pyarrow rich tqdm python-dotenv pytz

# Verify
python -c "from vnstock.core.utils.auth import check_status; print(check_status())"

# Update .env
Set-Content -Path "C:\Users\Administrator\Dropbox\Claude vnstock\.env" -Value "VNSTOCK_API_KEY=vnstock_423e2d521631063b3a55ad4b356a884a"
```

---

## Chạy hàng ngày

### Luôn activate venv trước!

**Desktop:**
```powershell
& "C:\Users\admin\.venv\Scripts\Activate.ps1"
cd "E:\Dropbox\Claude vnstock"
```

**Laptop:**
```powershell
& "C:\Users\Administrator\.venv\Scripts\Activate.ps1"
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
```

### Các lệnh chạy (sau khi activate venv)

| Tác vụ | Lệnh |
|--------|-------|
| **Dashboard** | `python -m streamlit run vnstock_dashboard.py` |
| **Update giá** | `python vnstock_updater.py --force` |
| **Screener** | `python vnstock_runner.py` |
| **Rollup** | `python vnstock_rollup.py` |

### Coordination 2 máy

- File `data_warehouse/_meta/pipeline_status.json` (sync qua Dropbox) theo dõi máy nào đã chạy
- Updater/Rollup có flag `--skip-if-done` — nếu máy kia đã chạy hôm nay thì skip
- **KHÔNG chạy updater trên cả 2 máy cùng lúc** — dễ conflict Dropbox

### Lịch chạy tự động (Scheduled Tasks)

| Thời điểm | Task | Ghi chú |
|-----------|------|---------|
| **15:30** Mon-Fri | Rollup | Merge 1m bars → warehouse |
| **18:00** Mon-Fri | Updater | Fetch daily OHLCV từ API |

Setup scheduled tasks (chạy PowerShell as Admin):

```powershell
# Desktop
.\scripts\setup_scheduled_tasks.ps1 -PythonExe "C:\Users\admin\.venv\Scripts\python.exe"

# Laptop
.\scripts\setup_scheduled_tasks.ps1 -PythonExe "C:\Users\Administrator\.venv\Scripts\python.exe"
```

---

## Kiểm tra Golden key vẫn hoạt động

Chạy bất kỳ lúc nào để verify:

```powershell
python -c "from vnstock.core.utils.auth import check_status; print(check_status())"
```

**Kết quả đúng:**
```
✓ Tier (Gói): golden
✓ Giới hạn (Limits): {'per_minute': 500, 'per_hour': 30000}
```

**Nếu thấy `tier: free` hoặc `community`:**
1. Kiểm tra đang dùng venv: `python -c "import sys; print(sys.prefix)"` — phải thấy path `.venv`
2. Kiểm tra `vnstock_data` có cài: `python -c "import vnstock_data; print('OK')"`
3. Nếu thiếu → chạy lại **Bước 4** (GUI installer)

---

## Troubleshooting

### Git pull "Permission denied"
Dropbox đang lock file. Đợi 30 giây rồi thử lại, hoặc:
```powershell
git fetch origin claude/pull-latest-code-ntmnb
git reset --hard origin/claude/pull-latest-code-ntmnb
```

### Dropbox conflict files
```powershell
Get-ChildItem -Recurse -Filter "*conflicted copy*" | Remove-Item
```

### "No module named 'pyarrow'" khi Refresh Screener
Dashboard chạy subprocess bằng Python chính thay vì venv. Đã fix trong code — pull code mới nhất.

### Muốn đổi device (hết slot)
1. Đăng nhập [vnstocks.com/login](https://vnstocks.com/login)
2. Vào quản lý tài khoản → xoá device cũ
3. Chạy lại GUI installer trên máy mới
