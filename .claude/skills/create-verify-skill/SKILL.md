---
name: create-verify-skill
description: Sinh skill kiểm chứng riêng cho dự án (.claude/skills/verify-TÊN-APP/) kèm feature map, để mọi agent chạy app thật như người dùng và thu bằng chứng theo cùng một cách. Dùng khi dự án chưa có cách có-script để chứng minh hành vi UI, CLI hoặc service.
disable-model-invocation: true
---

# Tạo verification skill cho dự án

Mục tiêu là một skill mà **agent khác đọc lạnh giữa chừng task** vẫn làm theo được: khởi động app, điều khiển một tính năng như người dùng, thu bằng chứng, dọn dẹp. Viết cho agent đọc, không viết cho người.

> Phỏng theo `create-verification-skill` trong pstack của Lauren Tan (MIT). Có thể thử `/verify` (built-in của Claude Code) trước. Nó tự ghi công thức đã chạy được vào `.claude/skills/verify/SKILL.md`, và skill này có thể dựa trên đó.

## 1. Phỏng vấn repo, không phỏng vấn người

Tự trả lời từ code. Chỉ hỏi người dùng những gì code không cho biết.
- **Bề mặt:** người dùng chạm vào gì (web UI, CLI hay TUI, API, desktop, mobile, thư viện)? Chọn bề mặt chính, ghi chú các bề mặt khác.
- **Chạy:** lệnh dev chính thức (package scripts, Makefile, README), port, biến môi trường, seed data, auth.
- **Điều khiển:** ưu tiên harness có sẵn (Playwright, Cypress, script expect, endpoint gọi được bằng curl). Không có thì dùng browser hoặc CDP cho web, tmux hoặc PTY cho CLI, HTTP cho service.
- **Quan sát:** những bằng chứng nào thu được (ảnh chụp, transcript terminal, response body, log, exit code, trạng thái DB)?
- **Cách ly:** hai instance chạy song song được không (port, thư mục dữ liệu)? Nếu không, ghi rõ và cấm drive instance dùng chung.

Repo không build hoặc không chạy được thì sửa (hoặc báo chính xác) trước khi sinh skill. Đừng viết skill dựa trên một nền đang hỏng.

## 2. Sinh `.claude/skills/verify-<app>/SKILL.md`

Frontmatter gồm `name: verify-<app>` và `description` nêu tên app, bề mặt và khi nào dùng. Skill có đúng các mục sau, mỗi mục dựa trên thứ đã tìm thấy ở bước 1, **không để placeholder**:
- **Launch:** lệnh chính xác để khởi động từ thư mục dữ liệu trống (gồm migration và seed), và dấu hiệu "sẵn sàng". Sẵn sàng nghĩa là *dùng được*, không chỉ là process đã trả lời. Kèm cách tắt.
- **Doctor:** một check chỉ-đọc: process đang chạy, đúng build, port thuộc về mình, auth hợp lệ.
- **Drive:** công thức với selector và lệnh *thật* của repo. Ưu tiên handle ổn định (ARIA role và tên, data attribute, route, chuỗi prompt) hơn toạ độ hay thứ tự tab.
- **Evidence:** thu gì, lưu ở đâu (mặc định `artifacts/verify/<slug>/`). Tiêu chuẩn bằng chứng: đi đường người dùng thật, không dùng setter nội bộ hay endpoint chỉ dành cho test; ghi *hành động* và *trạng thái kết quả*; kiểm cả side effect (file, row, message); chỉ mock ở ranh giới hệ thống bên ngoài.
- **Cleanup:** chỉ tắt thứ đã khởi động, không kill theo tên process. Giữ lại bằng chứng.
- **Helpers:** script đi kèm phải chạy được, và cách gọi phải ghi trong skill.

## 3. Gieo feature map

Tạo `.claude/skills/verify-<app>/features/README.md` (chỉ mục, điều kiện nền, quy ước điều khiển, tiêu chuẩn bằng chứng). Thêm một file cho mỗi tính năng người dùng thấy được, bắt đầu với 3–5 tính năng quan trọng nhất (lấy từ route, lệnh, menu, docs). Dùng mẫu [references/feature-template.md](references/feature-template.md) với đúng 4 mục: `Sub-features`, `How to get to it (user POV)`, `Driving it with <harness>`, `Gotchas`.

Seed data thiếu điều kiện cho một hành trình thì hành trình đó báo fail, và lý do ghi vào `Gotchas`. **Không bao giờ làm yếu hành trình để nó pass.**

## 4. Chứng minh skill trước khi bàn giao

Tự chạy chính skill vừa sinh, end-to-end một lần: Launch → Doctor → Drive MỘT tính năng → thu Evidence → Cleanup. Sau Cleanup, kiểm tra bằng chứng vẫn còn. Lỗi ở đâu thì sửa ở đó, và chạy Cleanup sau mỗi lần thử hỏng. **Skill chưa từng chạy là bản nháp, không phải sản phẩm.**

## 5. Bảo trì

Đề xuất với người dùng: chạy lại skill này (hoặc giao `verifier`) để đối chiếu feature map với app ít nhất mỗi tuần, hoặc mỗi ngày nếu app đổi nhanh, bằng `/schedule` hay `/loop`. Feature map lệch khỏi app thì sửa map trong một PR riêng. Map phát hiện lỗi sản phẩm thì báo lỗi, không sửa map để che lỗi.

Bàn giao: đường dẫn skill, danh sách tính năng đã map, bằng chứng của lần chạy thử, các bước chưa kiểm chứng.
