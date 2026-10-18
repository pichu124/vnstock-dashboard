# Đội agent (Agents-Team-coding)

- Task không tầm thường thì dùng `/team-lead <task>`. Chốt điều kiện xong dạng pass/fail trước khi làm.
- "Xong" nghĩa là `./scripts/check.sh` exit 0 cộng bằng chứng hành vi. Không chạy được check thì nói "inconclusive".
- Bug: tái hiện trước bằng test fail, rồi mới sửa nguyên nhân gốc.
- Người viết không tự kiểm: verify và review bằng subagent mới (`verifier`, `reviewer`).
- Bị người dùng sửa cùng một lỗi lần thứ hai thì đề xuất `/correct`.
- Cuối ngày làm việc: `./scripts/audit-agent.sh --all --since 1` dò sự cố từ file phiên của mọi dự án trên máy; có mục A, B, H hoặc F thì chạy `/agent-audit`; mục I có lớp lỗi lặp từ 2 lần thì `/correct`.
- Cuối tuần: `./scripts/audit-agent.sh --all --since 28` xem mục J (xu hướng).
- Cứ làm: đọc, sửa trong branch hoặc worktree, commit cục bộ, chạy test. Luôn hỏi người: force-push, push hoặc merge vào nhánh chính, xoá dữ liệu, deploy, publish.

| Rule | Thực thi bởi |
|---|---|
| Không kết thúc lượt khi check đỏ | `.claude/hooks/stop-gate.sh` (Stop) |
| Hỏi người trước hành động không đảo ngược được | `.claude/hooks/guard-irreversible.sh` (PreToolUse) |
| Không đọc file bí mật (`.env`, `*.pem`, `secrets/`) | `permissions.deny` trong `.claude/settings.json` |
| Format theo cấu hình của dự án | `.claude/hooks/post-edit-format.sh` (PostToolUse) |
| Không bớt ca "phải hỏi" của guard để cho dễ | `scripts/guard-ask-floor` (test-hooks đỏ khi số ca dưới sàn) |
