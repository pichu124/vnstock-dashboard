# 🌐 Macro cheatsheet — lãi suất & tỷ giá (`vnstock_macro.py`)

Ghi nhanh cách cập nhật dữ liệu vĩ mô cho AI brief. Chạy trong thư mục repo
(venv đã kích hoạt).

## 3 chỉ số + key

| Key | Ý nghĩa | Đơn vị | Nguồn |
|-----|---------|--------|-------|
| `usdvnd` | Tỷ giá USD/VND (tham chiếu) | VND | **AUTO** (API FX) |
| `sbv_policy_rate` | Lãi suất tái cấp vốn (SBV) | %/năm | nhập tay |
| `interbank_on` | Lãi suất liên ngân hàng qua đêm (VNIBOR ON) | %/năm | nhập tay* |

\* Vietstock VNIBOR bị tường phí (bản Basic) → nhập tay. Nếu có tài khoản
Vietstock trả phí: đặt biến môi trường `VNSTOCK_MACRO_VIETSTOCK=1` rồi
`python run.py macro` để auto.

## Lệnh SET tay (cái bạn cần)

```powershell
# Lãi suất điều hành SBV — đổi vài lần/năm (khi SBV ra quyết định)
python vnstock_macro.py --set sbv_policy_rate 4.5

# Lãi suất liên ngân hàng qua đêm — cập nhật khi để ý nó nhảy đáng kể
python vnstock_macro.py --set interbank_on 12.0

# Kèm ngày hiệu lực (mặc định = hôm nay). Set 2 mốc ngày khác giá trị
# → brief tự hiện mũi tên ▲/▼ + mức thay đổi.
python vnstock_macro.py --set interbank_on 9.0 --as-of 2026-06-20

# Ghi đè tỷ giá tay (vd muốn dùng giá NHTM thay vì tham chiếu) — tùy chọn
python vnstock_macro.py --set usdvnd 26200
```

→ `--set` LUÔN thắng auto-fetch (fetch lỗi không ghi đè giá trị bạn đã set).

## Lệnh xem / cập nhật / kiểm tra

```powershell
python vnstock_macro.py --show       # xem cache hiện tại + "Áp lực vĩ mô"
python vnstock_macro.py --refresh    # auto-fetch tỷ giá → cache (lãi suất giữ nguyên)
python vnstock_macro.py --diag       # thử fetch tỷ giá (xác minh mạng/API)
python run.py macro                  # = --refresh, dùng trong pipeline
```

## Khi nào cập nhật?

- **Tỷ giá**: KHÔNG cần đụng — tự refresh qua lịch `run.py all` (tối T2–T6),
  nút "📥 Cập nhật giá" trên dashboard, và brief tự refresh 1×/ngày.
- **`sbv_policy_rate`**: chỉ khi SBV đổi lãi suất điều hành (~2–4 lần/năm).
- **`interbank_on`**: khi thấy lãi suất LNH nhảy (xem tin / mục "🌐 Vĩ mô" trong
  brief). Cập nhật 1×/tuần là đủ cho 1 dòng bối cảnh.

## Giá trị tham chiếu (cập nhật khi đổi)

- `sbv_policy_rate`: 4.5%/năm (giữ từ 2023-06-19).
- `interbank_on`: ~12%/năm (giữa 06/2026, thanh khoản căng) — nhớ hạ xuống khi
  thị trường tiền tệ dịu lại.
- `usdvnd`: ~26,192 (14/06/2026) — auto, chỉ tham khảo.

## Tắt auto (nếu cần)

- `VNSTOCK_BRIEF_AUTO_MACRO=0` → brief không tự refresh macro.
- `VNSTOCK_MACRO_VIETSTOCK=1` → bật auto lãi suất LNH (chỉ khi có Vietstock trả phí).
