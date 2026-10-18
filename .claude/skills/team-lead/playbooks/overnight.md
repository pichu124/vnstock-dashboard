# Playbook: Overnight / chạy dài không người trông

Dùng kèm playbook chính (bug-fix, feature, refactor). Playbook này thêm hợp đồng, nhật ký và lối thoát.

## Điều kiện trước khi chạy
Từ chối chạy không người trông và đề xuất chạy có người xem nếu thiếu một trong các điều sau: có lệnh check (`./scripts/check.sh` hoặc lệnh ghi trong hợp đồng) bắt được lỗi thật; có cách kiểm chứng hành vi (verify skill hoặc test end-to-end); điều kiện xong là một **vị từ pass/fail**. "Làm trong 4 giờ" không phải điều kiện xong.

## Hợp đồng (ghi vào đầu decision log)
- Mục tiêu và điều kiện xong (pass/fail).
- Nơi làm: worktree hoặc branch mới từ `<base>`, không đụng nhánh chính.
- Quyền: được commit cục bộ, được mở PR nháp. Không merge, không force-push, không deploy.
- Lối thoát: nếu không tiến triển sau N vòng hoặc X giờ, dừng và viết lý do.

Gợi ý gắn điều kiện bằng `/goal`, ví dụ: `/goal <vị từ>; hoặc dừng sau 40 lượt`.

## Vòng lặp
Mỗi vòng: kiểm điều kiện xong → một thay đổi nhỏ nhất có lý do → kiểm chứng trên hiện vật thật → có tiến triển thì commit, không thì **bỏ thay đổi** → ghi **một dòng** log.

Gặp vùng bằng phẳng (plateau) thì đổi hướng, không dừng. Không bao giờ nới lỏng điều kiện xong để tuyên bố thắng.

## Decision log
File `.audit/<task-slug>.tsv`, có header:
```
time	phase	decision	reason	evidence	result
```
`evidence` là con trỏ tới bằng chứng: lệnh, commit SHA, đường dẫn artifact. `result` là một trong `kept`, `discarded`, `blocked`.

## Buổi sáng
Giao `reviewer` (context mới) đọc decision log và diff, trả về mục **ATTENTION**: 3–5 điều người dùng cần xem trước, mỗi điều trỏ tới dòng log tương ứng. Báo cáo cho người dùng bắt đầu bằng ATTENTION.
