# Playbook: Bug fix

1. **Tái hiện trên đúng bề mặt lỗi** (UI, CLI, API) bằng skill `verify-<app>` nếu có. Ghi lại bằng chứng của trạng thái hỏng. Không tái hiện được thì dừng và báo, kèm những gì đã thử.
2. **Khoanh vùng.** Giao cho `Explore` hoặc tự tìm. Đặt giả thuyết rồi kiểm từng cái bằng quan sát (log, breakpoint, test nhỏ), không đoán.
3. **Gốc rễ.** Hỏi "vì sao" tới khi tới nguyên nhân thật. Cấm vá bằng null-check, try/catch nuốt lỗi hay retry che triệu chứng.
4. **Lọt lưới?** Chạy `git log -L <đầu>,<cuối>:<file>` hoặc `git blame` trên dòng gây lỗi vừa tìm ra. Dòng đó đến từ thay đổi mà đội đã báo xong (commit của agent, PR đã merge, task đã bàn giao) thì đây là **lỗi lọt lưới**: sửa cả cổng kiểm, không chỉ sửa bug. Ngoài test tái hiện, làm thêm:
   - Thêm hành trình tái hiện vào feature map của skill `verify-<app>` (`.claude/skills/verify-<app>/features/`), để verifier lần sau đi qua đúng đường này. Dự án chưa có skill verify thì đề xuất `/create-verify-skill`.
   - Ghi một dòng **Vì sao lọt** cho bàn giao, chọn một trong bốn: check không phủ; verifier không đi hành trình này; reviewer không xem phần này; hợp đồng thiếu điều kiện.
   - Cùng lớp lỗi đã lọt từ 2 lần trở lên (xem mục I của báo cáo `audit-agent.sh` và `git log`) thì đề xuất `/correct`.
5. **Giao `implementer`**: test fail trước (nếu có đường test cục bộ rẻ), rồi sửa nhỏ nhất, rồi `./scripts/check.sh`.
6. **`verifier` mới**: chạy lại đúng hành trình tái hiện ở bước 1 và vài ca biên lân cận. Bằng chứng trước/sau.
7. **`reviewer`** đọc diff.
8. Bàn giao. Lỗi lọt lưới thì kèm dòng "Vì sao lọt". Nếu lỗi thuộc một lớp đã gặp trước đây, ghi đề xuất `/correct`.
