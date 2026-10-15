# Playbook: Refactor (giữ nguyên hành vi)

1. **Khoá hành vi trước.** Xác định check chứng minh hành vi không đổi: test hiện có, hoặc snapshot output của lệnh hay API trên vài đầu vào thật, chạy và lưu lại *trước* khi sửa.
2. **Trừ trước khi cộng.** Xoá code chết, lớp bọc một-caller, cấu hình thừa trước, rồi mới tái cấu trúc phần còn lại.
3. **Chuyển caller rồi xoá API cũ trong cùng một đợt.** Không để lại lớp tương thích tạm thời trừ khi có caller ngoài repo.
4. **Build the lever.** Thay đổi lặp lại trên nhiều file thì viết codemod hay script và giao `implementer` chạy nó. Script là thứ reviewer chạy lại được.
5. Chia thành các đơn vị, mỗi đơn vị kết thúc ở trạng thái xanh. Sau mỗi đơn vị so lại snapshot ở bước 1: phải giống hệt.
6. `verifier` chạy lại snapshot và hành trình chính. `reviewer` chú ý thay đổi hành vi ngoài ý muốn.
