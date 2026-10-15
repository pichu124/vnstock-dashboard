# Playbook: Bug fix

1. **Tái hiện trên đúng bề mặt lỗi** (UI, CLI, API) bằng skill `verify-<app>` nếu có. Ghi lại bằng chứng của trạng thái hỏng. Không tái hiện được thì dừng và báo, kèm những gì đã thử.
2. **Khoanh vùng.** Giao cho `Explore` hoặc tự tìm. Đặt giả thuyết rồi kiểm từng cái bằng quan sát (log, breakpoint, test nhỏ), không đoán.
3. **Gốc rễ.** Hỏi "vì sao" tới khi tới nguyên nhân thật. Cấm vá bằng null-check, try/catch nuốt lỗi hay retry che triệu chứng.
4. **Giao `implementer`**: test fail trước (nếu có đường test cục bộ rẻ), rồi sửa nhỏ nhất, rồi `./scripts/check.sh`.
5. **`verifier` mới**: chạy lại đúng hành trình tái hiện ở bước 1 và vài ca biên lân cận. Bằng chứng trước/sau.
6. **`reviewer`** đọc diff.
7. Bàn giao. Nếu lỗi thuộc một lớp đã gặp trước đây, ghi đề xuất `/correct`.
