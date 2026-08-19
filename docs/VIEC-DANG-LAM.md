# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Đây là bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) nằm ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 18/08/2026.

---

## 🔴 VIỆC CỦA BẠN — làm trên DESKTOP `C:\vnstock`

### Bước 1 — soi log (2 phút). LÀM SỚM, đừng để lâu.

```powershell
cd C:\vnstock
Select-String -Path run_daily.log -Encoding utf8 `
  -Pattern '^\[run\.py\] 20\d\d-.* all$|^\[brief\]|brief returned|^\[telegram\] close brief' `
  | Select-Object -Last 25
```

Dán kết quả cho Claude. Tự đọc thì theo bảng này — tìm dòng bắt đầu `[brief]`:

| Thấy gì | Nghĩa là | Làm gì |
|---|---|---|
| `VNSTOCK_PIPELINE_BRIEF=0` | kill-switch đang bật | **Xoá dòng đó khỏi `.env`** — không thì đêm nào brief cũng câm |
| `bỏ qua: chưa tới 15:00` | đúng thiết kế, không phải lỗi | làm tiếp **Bước 2** |
| `bỏ qua: … (marker)` | phiên đó đã có brief rồi | không phải làm gì |
| `❌ <Lỗi>` | lỗi thật | gửi nguyên dòng cho Claude |

*Vì sao gấp:* mỗi lần `run.py all` đổ ~2.200 dòng pytest vào log này, quá 5 MB là
log tự cắt chỉ giữ 1 MB cuối — bằng chứng biến mất.

### Bước 2 — CHỈ khi Bước 1 ra "chưa tới 15:00" (1 phút)

```powershell
python -c "import json;d=json.load(open(r'C:\vnstock\data_warehouse\_meta\market_overview.json',encoding='utf-8'));print(d.get('generated_at'),d.get('data_date'),d.get('gtgd_date'))"
```

* `generated_at` ≥ 15:05 → xong, không phải làm gì.
* `generated_at` < 15:00 → độ rộng (A/D, movers) trong brief 23:16 là số giữa
  phiên. Chạy `python run.py screener` để sửa số cho dashboard.
  **ĐỪNG gửi lại brief** — sẽ thành brief trùng.

### Bước 3 — khi rảnh, 1 lệnh (nợ treo từ 07/08)

```powershell
python vnstock_classifier.py --classify --limit 20
```
Soi: không còn đòi `ANTHROPIC_API_KEY`, và có dòng route "ladder free". Dán kết quả.

### Bước 4 — chỉ làm được TRONG GIỜ GIAO DỊCH (9h15–14h30, T2–T6)

Mở dashboard → bật 🔴 **Live Mode** ở sidebar trái → sang tab **Thị trường**.
Xác nhận heatmap VN30 có số nhảy thật. (Code đã xong + Playwright đã đối chứng,
chỉ thiếu một lần nhìn tận mắt.)

---

## 🟠 VIỆC CỦA CLAUDE — bạn chỉ cần nói "làm đi"

Xếp theo thứ tự nên làm. Mỗi việc xong Claude chạy `run.py test --fast`, bạn chỉ
cần `git fetch origin <nhánh> && git merge origin/<nhánh>` rồi chạy lại test trên máy thật.

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| 1 | **Test hết ghi bẩn `run_daily.log`** | Làm trước thì mọi lần soi log sau chỉ còn 1 dòng grep, và log hết bị tự cắt | ~30' |
| 2 | **Rec bị đóng sớm 20-40%** — horizon ghi bằng PHIÊN nhưng thi hành bằng NGÀY LỊCH | Lỗi số liệu nặng nhất; đang bóp méo verdict của #32 | ~30' |
| 3 | **Ghi JSON nguyên tử** (12 điểm/7 file) + nối vào lưới `_MUST_BE_ATOMIC` | Pipeline đã bị kill 2 lần; bản cụt còn lây sang file dự phòng | ~30' |
| 4 | **3 test bộ công cụ đơn vị giá vào `--fast`** | Đang sửa 3 script đó mà chạy `--fast` là chạy không lưới | vài phút |
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
