# <Tên tính năng>

<Một đoạn mô tả hành vi người dùng thấy được, ví dụ: "Tạo ghi chú cho phép người dùng lưu một ghi chú có tiêu đề từ trình duyệt hoặc CLI, huỷ bản nháp, và xác nhận ghi chú đã lưu từ một view thứ hai.">

## Sub-features

- `<id-ngắn>` <một dòng mô tả một hành vi>
- `<id-ngắn>` <...>

## How to get to it (user POV)

- <Mọi entry point người dùng có: nút, phím tắt, route, lệnh CLI, endpoint API.>

## Driving it with <harness>

Preconditions:

- <Trạng thái cần có: app healthy ở URL/port, dữ liệu seed, không tồn tại bản ghi X.>

- **<Hành động 1>.** <Người dùng làm gì>. Chạy `<lệnh chính xác>`. <Kết quả quan sát được>.
- **<Hành động 2>.** ...
- **Xác nhận lưu bền.** <Đọc lại từ một view khác>. Chạy `<lệnh>`. <Kết quả>.
- **Bằng chứng.** Chạy `<lệnh chụp ảnh hoặc snapshot hoặc lưu output>` vào `artifacts/verify/<feature-id>/`.

## Gotchas

- <Bẫy làm hỏng hoặc vô hiệu hoá lần kiểm chứng, ví dụ: "nhấn `n` khi đang focus vào textbox sẽ gõ ký tự thay vì mở editor".>
- <Thông báo "đã lưu" một mình chưa đủ làm bằng chứng. Phải mở lại bản ghi.>
- <Dữ liệu cần dọn sau khi chạy (nhưng giữ bằng chứng).>
