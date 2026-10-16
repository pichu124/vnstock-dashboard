---
name: agent-audit
description: Dò sự cố của đội agent từ file phiên Claude Code trên máy này (guard bỏ sót hoặc hỏi thừa, Stop gate chặn sai hoặc chậm, hook lỗi), rồi sửa những gì có thể chứng minh bằng test và mở PR nháp cho người duyệt. Dùng khi gõ /agent-audit [số ngày], cuối mỗi ngày thử nghiệm, hoặc định kỳ hằng tuần.
disable-model-invocation: true
---

# Agent audit: dò sự cố rồi sửa có kiểm chứng

Khoảng thời gian cần soát: `$ARGUMENTS` ngày (trống thì 7).

Guard, Stop gate và hook là **chốt an toàn** của đội. Skill này được tìm lỗi, viết test và đề xuất bản sửa, nhưng **không được tự đưa bản sửa vào dùng**: đầu ra cuối cùng là một PR nháp do người duyệt.

## 1. Lập báo cáo
Chạy bằng Bash tool (trên Windows là Git Bash). Đường dẫn dưới đây đúng cho cả kit cài vào dự án lẫn kit cài dạng plugin:
```bash
bash "${CLAUDE_SKILL_DIR}/../../../scripts/audit-agent.sh" --all --since <số ngày> --out "${TMPDIR:-/tmp}/agent-audit.md"
```
`--all` soát mọi dự án trên máy, mỗi dòng ghi thư mục của lệnh; bỏ `--all` thì chỉ soát dự án hiện tại. Biến `${CLAUDE_SKILL_DIR}` không được thay (bản Claude Code cũ) thì dùng `./scripts/audit-agent.sh` của dự án, hoặc `~/.claude/plugins/cache/agents-team-coding/agent-team/*/scripts/audit-agent.sh`. Đọc báo cáo. Exit 2 nghĩa là không thấy file phiên: thử `--transcripts <thư mục>` (file phiên nằm ở `~/.claude/projects/<tên thư mục dự án, ký tự đặc biệt thành ->/`). Không có gì ở mục A, B, H, F và Stop gate bình thường thì báo "không có sự cố" và dừng.

## 2. Phân loại từng mục, theo thứ tự ưu tiên
| Mục | Làm gì |
|---|---|
| **B. Hồi quy** (trước hỏi, nay cho qua) | Luôn là lỗi. Sửa trước. |
| **H. Chạy lúc guard không hỏi** (nay đã hỏi) | Guard không hoạt động lúc đó. Tìm nguyên nhân trong mục F và trong cách mở phiên (thư mục chưa trust, phiên mở ở thư mục cha, matcher thiếu tool). Báo cho người, không cần sửa guard. |
| **A. Có thể bỏ sót** | Tự hỏi: lệnh này chạy nhầm chỗ có làm **mất dữ liệu hoặc ảnh hưởng người khác** không? Có thì là lỗi thật. Chỉ là thao tác trong thư mục tạm của chính agent thì ghi "không phải lỗi" kèm lý do. |
| **G. Bị từ chối mà guard không hỏi** | Dòng "bạn từ chối" mà lệnh nguy hiểm thì xử lý như A; lệnh vô hại thì bỏ qua. Dòng "auto mode chặn" hay "luật deny chặn" là lớp bảo vệ khác đã làm việc: chỉ thống kê. |
| **F. Lỗi hook** | Tái hiện bằng cách chạy hook với input tương tự, rồi sửa nguyên nhân gốc (CRLF, quyền chạy, Python, đường dẫn...). |
| **E. Stop gate** | Chặn nhiều lần hoặc "nhả sau N lần": tìm vì sao check đỏ. Quá chậm (trung vị trên 5 phút): chỉ đề xuất cách làm nhanh, **không** nới Stop gate. |
| **C. Hỏi rồi bạn duyệt** | Chỉ là **ứng viên** hỏi thừa. Lặp lại nhiều lần với cùng một kiểu lệnh rõ ràng vô hại thì mới đề xuất nới. |

## 3. Sửa theo playbook bug-fix, mỗi lỗi một commit
Sửa ở đâu: lệnh nằm trong dự án tự cài kit (có `.claude/hooks/guard-irreversible.sh` riêng) thì sửa trong dự án đó. Lệnh nằm trong dự án không cài kit (guard đến từ plugin `agent-team`) thì bản sửa thuộc repo kit `pichu124/Agents-Team-coding`: clone vào thư mục tạm và làm các bước dưới trong bản clone.
1. **Tái hiện trước**: thêm ca vào `scripts/test-hooks.sh` (lệnh nguy hiểm vào danh sách `expect_guard ask`, lỗi hook thành một ca riêng). Chạy `./scripts/test-hooks.sh` và thấy **đỏ**.
2. Sửa nhỏ nhất trong `.claude/hooks/`. Chạy lại cho tới khi **xanh**, rồi `./scripts/check.sh` xanh.
3. Ca "phải hỏi" mới làm số ca tăng: nâng `scripts/guard-ask-floor` lên đúng số test in ra.

Cấm, kể cả khi làm vậy cho nhanh:
- Xoá hay sửa ca `expect_guard ask` có sẵn, hoặc **hạ** `scripts/guard-ask-floor`.
- Tắt Stop gate, nới `AGENT_STOP_GATE_MAX`, bỏ test trong `check.sh`.
- Nới guard (bớt hỏi) mà không ghi rõ trong PR. Thay đổi kiểu này phải để riêng một commit tên `guard: NỚI LỎNG ...`.

## 4. Kiểm bởi người khác
Gọi agent `reviewer` (context mới) soát toàn bộ diff, đặc biệt xem bản sửa có làm guard bỏ sót thêm lệnh nào không. Có lỗi chặn thì sửa rồi review lại.

## 5. Mở PR nháp
Tạo branch `fix/agent-audit-<YYYYMMDD>` từ branch hiện tại, commit, push, mở **PR nháp** (không merge, không push lên nhánh chính). Mô tả PR gồm:
- bảng: mục báo cáo, quyết định (lỗi thật / không phải lỗi / chỉ đề xuất), commit tương ứng;
- dòng "Thắt chặt" và dòng "Nới lỏng" tách riêng, để người duyệt biết chỗ nào cần đọc kỹ;
- nhắc: file trong `.claude/hooks/` là bản chép từ bộ kit, nên đồng bộ bản sửa về repo kit.

## Trả lời
Tóm tắt số mục từng loại, những gì đã sửa (kèm output đỏ rồi xanh), những gì để người quyết, và link PR nháp.
