---
name: brief-review
description: Soi brief chiều ĐÊM QUA mỗi sáng — engine nào viết (Claude hay rơi về ladder, vì sao), guard sửa bao nhiêu, rồi chấm sao để bản tốt thành mẫu few-shot cho các brief sau. Dùng khi user gõ /brief-review hoặc hỏi "brief tối qua sao rồi".
---

# /brief-review — soi brief đêm qua, chấm sao

○ Máy nào cũng được: marker, sổ LLM, memory, `brief_claude_raw.md` /
`brief_claude.md` đều nằm trong kho `data_warehouse/_meta` (Dropbox). Riêng
`run_daily.log` là của 🖥️ desktop.

## Python: dùng venv, không gõ `python` trần

Claude Code có thể mở từ shell chưa kích hoạt venv (30/09 desktop: `python`
= `C:\Python314`). Gọi thẳng `%USERPROFILE%\.venv\Scripts\python.exe`:
Bash `PY=~/.venv/Scripts/python.exe` · PowerShell
`$PY = "$env:USERPROFILE\.venv\Scripts\python.exe"`.

## Quy trình

1. Chạy `$PY vnstock_brief_pack.py --review` và đọc 4 khối:
   - **marker** (`brief_push.json`): `engine=claude` là bản Claude;
     `engine=ladder` kèm `claude_error` = Claude rơi về ladder, lý do ghi ngay đó.
   - **sổ** `ClaudeCode:<model>` hôm nay: call/OK/lỗi + lỗi cuối.
   - **memory** 2 bản `afternoon` mới nhất: id, agent, độ dài, auto_score, sao.
   - **guard**: `brief_claude_raw.md` (chữ thô Claude) so `brief_claude.md`
     (sau 55 guard) — bao nhiêu dòng bị sửa/xoá.
2. Tóm cho user trong ≤ 5 dòng: ai viết, model thật (fallback?), mấy giây,
   guard sửa bao nhiêu, cảnh báo validator (nếu có trong `run_daily.log`:
   `Select-String '\[brief\]' run_daily.log | Select-Object -Last 8`, 🖥️;
   đêm engine Claude phải có 4 dòng `⏱ claude-cli` cho news · audit · train ·
   brief: `Select-String '⏱ claude-cli' run_daily.log | Select-Object -Last 4`).
3. Nếu marker `ladder` + `claude_error`: in đúng lệnh chữa —
   `$PY vnstock_brief_pack.py --check` (🖥️ DESKTOP, dưới tài khoản chạy
   task) và, tuỳ lỗi, `VNSTOCK_CLAUDE_CLI_EXE=<đường dẫn claude>` trong `.env`
   hoặc `claude` → `/login`.
4. Hỏi user chấm bản đêm qua **1–5 sao + một câu nhận xét**, rồi ghi:
   `$PY vnstock_brief_pack.py --rate <id> <sao> "<nhận xét>"`.
   ≥ 4 sao ⇒ bản đó vào mẫu few-shot của prompt các đêm sau (Claude lẫn
   ladder cùng học). Không chấm thì thôi, đừng tự bịa sao.

## Đọc đúng

- `engine=ladder` không phải lỗi pipeline: brief vẫn đi, chỉ là bản Gemini.
  Badge doctor "Engine brief" đỏ khi Claude hỏng ≥ 3 ngày liền.
- Chi phí trong sổ là quy đổi giá API; gói thuê bao trừ hạn mức, không trừ tiền.
- So bản Claude với bản ladder bằng số: `$PY vnstock_stance_track.py --show`
  (stance ngày mai đúng bao nhiêu %) sau ≥ 5 phiên.
