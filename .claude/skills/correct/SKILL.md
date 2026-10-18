---
name: correct
description: Tìm các lỗi mà agent cứ lặp lại trong repo này và làm cho chúng không thể xảy ra. Sửa ở tầng cao nhất có thể (kiến trúc → type → lint/CI → hook → test → chữ), chứng minh check mới fail trên lỗi thật trong quá khứ, và cập nhật bảng Rule ↔ Thứ thực thi trong CLAUDE.md. Dùng khi gõ /correct, hoặc sau khi người dùng phải sửa cùng một lỗi lần thứ hai.
disable-model-invocation: true
---

# Correct: mã hoá bài học vào cấu trúc

Người dùng cứ phải sửa agent vì cùng một kiểu lỗi. Hãy đổi repo để agent tiếp theo **không thể** mắc lỗi đó.

> Phỏng theo skill `/correct` trong pstack của Lauren Tan (MIT) và nguyên tắc "hook là tất định, CLAUDE.md chỉ là khuyến nghị" trong best practices của Claude Code.

Phạm vi lớn (quét lịch sử dài, nhiều lớp lỗi) thì giao cho agent `gardener` và chỉ nhận về bảng kết quả.

## 1. Tìm các lớp lỗi
Nguồn đầu tiên là mục I "Bạn phải sửa agent" của báo cáo audit:
```bash
bash "${CLAUDE_SKILL_DIR}/../../../scripts/audit-agent.sh" --since 14 --no-replay
```
Ở dự án có kit chép vào, `./scripts/audit-agent.sh` cũng được. Mỗi dòng là một lần người dùng ngắt agent, từ chối tool kèm lời nhắn, hoặc gõ câu sửa. Câu sửa dò bằng từ khoá nên có thể khớp thừa: đọc rồi mới gom lớp. Exit 2 là máy không có file phiên: bỏ qua nguồn này.

Rồi đọc commit gần đây, revert, review comment, `CLAUDE.md`, memory của gardener, và comment giải thích workaround. Gom lại thành lớp. **Một lớp chỉ được tính khi đã xảy ra 2 lần**, kèm bằng chứng.

Nếu được gọi ngay sau khi người dùng vừa sửa bạn: lỗi vừa sửa là ứng viên đầu tiên.

## 2. Sửa mỗi lớp ở tầng cao nhất làm được
1. **Kiến trúc:** xoá cách cũ hoặc code chết để không còn gì sai để chép; mỗi state một chủ; ẩn internals.
2. **Type:** trạng thái sai không viết ra được.
3. **Lint hoặc check** trong `scripts/check.local.sh` (hoặc config linter). Thông báo lỗi **chỉ ra cách đúng**. Pattern sai đã phổ biến thì chỉ fail trên phần thêm mới.
4. **Hook** trong `.claude/hooks/` và `.claude/settings.json`, cho điều phải chặn ngay trong phiên.
5. **Test hành vi.** Sửa hoặc xoá test vẫn pass khi mọi hàm trả về rỗng.
6. **Chữ** trong CLAUDE.md hoặc skill: chỉ dùng cho quyết định cần phán đoán. Viết một dòng, kèm ví dụ thất bại.

## 3. Sửa và chứng minh
- Mỗi lớp một commit.
- **Chứng minh check mới fail trên lỗi thật cũ** (áp lại đoạn code sai hoặc checkout commit cũ), rồi pass trên code hiện tại. Dán hai output này vào báo cáo.
- Check chạy giống hệt ở local và CI: đi qua `./scripts/check.sh`.
- Bằng chứng từ mục I ghi vào commit hay PR thì tóm tắt (tên lớp lỗi, số lần), không chép nguyên lời người dùng: repo có thể công khai.

## 4. Giữ bảng rule
Cập nhật bảng **Rule ↔ Thứ thực thi** cuối `CLAUDE.md`. Rule đã có trong bảng mà vẫn bị vi phạm và chưa có gì thực thi nó là một lần lặp lại: đẩy nó lên tầng cao hơn trong cùng thay đổi này. Xoá rule có lỗi không còn xảy ra được.

## Trả lời
Với mỗi lớp lỗi: bằng chứng, tầng đã chọn, vì sao không chọn được tầng cao hơn, output "fail trên lỗi cũ / pass trên code mới". Cuối cùng so số lần sửa trên 10 lượt (mục J của cùng báo cáo) giữa tuần này và tuần trước.
