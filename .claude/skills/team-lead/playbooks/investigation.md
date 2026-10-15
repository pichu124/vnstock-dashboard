# Playbook: Investigation (chỉ đọc)

Sản phẩm là **một câu trả lời có trích dẫn**, không phải code.

1. Viết lại câu hỏi thành 1–3 câu hỏi con có thể trả lời bằng bằng chứng.
2. Phạm vi hẹp thì tự đọc. Phạm vi rộng thì giao cho `Explore`, mỗi câu hỏi con một agent, chạy song song, và yêu cầu trả về `file:line`.
3. Câu hỏi "vì sao được làm thế này": đọc `git log -L` hoặc `git log -S` và `git blame` trên đoạn code, cùng PR hay issue liên quan nếu có `gh`.
4. Câu hỏi về hành vi runtime: **chạy thử** (lệnh nhỏ, test, script tạm trong thư mục scratch) thay vì suy luận.
5. Trả lời: kết luận trước, rồi bằng chứng (`file:line`, lệnh kèm output), rồi điều chưa chắc chắn. Không sửa file sản phẩm.
