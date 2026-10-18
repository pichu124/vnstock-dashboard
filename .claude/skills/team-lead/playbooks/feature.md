# Playbook: Feature

1. **Chốt điều kiện xong** dưới dạng hành vi quan sát được, ví dụ "lệnh X với cờ --json in ra JSON parse được; output text giữ nguyên từng byte".
2. **Thiết kế.** Nếu thay đổi chạm nhiều file hoặc vượt ranh giới module, giao `architect`. Nhận về data shape, plan theo đơn vị kiểm chứng được, và các đơn vị có thể chạy song song. Mô tả được trong một câu thì bỏ qua bước này.
3. **Thực thi theo đơn vị.** Mỗi đơn vị giao cho một `implementer` mới. Đơn vị không chung file thì chạy song song với `isolation: "worktree"`. Gộp theo thứ tự plan và chạy `./scripts/check.sh` sau mỗi lần gộp.
4. **Kiểm chứng.** `verifier` mới đi qua mọi entry point của tính năng trong feature map. Nếu tính năng là mới, đề xuất thêm một file vào feature map của `verify-<app>`.
5. **`reviewer`** đọc toàn bộ diff dựa trên hợp đồng.
6. Bàn giao: commit theo đơn vị; PR có bằng chứng.
