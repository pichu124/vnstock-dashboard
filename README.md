# VnStock Dashboard

Nền tảng phân tích chứng khoán Việt Nam chạy cục bộ (Streamlit): screener 14 preset,
phân tích kỹ thuật/cơ bản, tổng quan thị trường, live mode ~1.100 mã, kho Parquet
local, AI brief sáng/chiều và cảnh báo tin gửi Telegram.

Luật phải nhớ (kho Dropbox, hai máy, test, quy ước, bất biến): [`CLAUDE.md`](CLAUDE.md).
Bản đầy đủ: [`docs/VAN-HANH.md`](docs/VAN-HANH.md) (vận hành, công tắc env) và
[`docs/KIEN-TRUC.md`](docs/KIEN-TRUC.md) (từng module). Việc đang làm:
[`docs/VIEC-DANG-LAM.md`](docs/VIEC-DANG-LAM.md).

## Cài đặt

Windows, venv riêng cho vnstock thế hệ 6:

```powershell
& "$HOME\.venv_6x\Scripts\Activate.ps1"
pip install -r requirements.txt
```

Khoá và nguồn dữ liệu khai trong `.env` ở gốc repo (mẫu: `.env.example`; không bao giờ
commit `.env`). Nguồn giá khai MỘT chỗ: `VNSTOCK_SOURCE` / `VNSTOCK_SOURCE_ROUTES`.

## Chạy

Mọi thứ đi qua `run.py` (exit code: 0 ok · 1 cảnh báo · 2 lỗi cứng):

```powershell
python run.py dashboard      # Streamlit, http://localhost:8501
python run.py all            # pipeline tối: sync → screener → … → brief
python run.py doctor         # tự kiểm sức khoẻ kho + pipeline
python run.py test --fast    # sau khi sửa module lõi
python run.py test           # đầy đủ, trước khi tạo PR về main
```

Danh sách lệnh con: `python run.py --help`.

## Lịch chạy tự động (Windows Task Scheduler)

```powershell
# Run as Administrator, trong shell ĐÃ kích hoạt venv
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduled_tasks.ps1
```

Ba task, đăng ký theo máy: **Daily** 18:00 ngày làm việc (`run.py all`), **Weekend**
(`run.py weekend`), **News Alert** mỗi giờ (`run.py news-alert`).

## Cấu trúc

```
run.py                  # orchestrator: mọi lệnh con + pipeline
vnstock_dashboard.py    # UI chính; các trang ở dashboard/
vnstock_*.py            # module lõi (bản đồ: docs/KIEN-TRUC.md)
scripts/                # cài task lịch, công cụ đo/chữa kho chạy tay
tests/                  # pytest
docs/                   # thiết kế (THIET-KE-*.md), việc đang làm, nhật ký
data_warehouse/         # kho dữ liệu (không commit; đồng bộ qua Dropbox)
```

## License

Private project.
