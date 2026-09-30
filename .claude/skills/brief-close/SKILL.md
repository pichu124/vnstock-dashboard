---
name: brief-close
description: Viết brief chiều (close brief) chất lượng cao từ gói brief pack do pipeline xuất (data_warehouse/_meta/brief_pack.json + brief_prompt.md), ghi ra brief_claude.md rồi nạp lại bằng `run.py brief --from-file`. Dùng khi user gõ /brief-close, muốn tự tay thay bản ladder, hoặc pipeline đêm rơi về ladder.
---

# /brief-close — viết brief chiều bằng Claude

Đường brief của repo (ctx → prompt → agent → 55 guard → memory → Telegram →
marker một-brief-mỗi-phiên) giữ nguyên; skill này chỉ thay **agent** bằng
Claude ở lượt TAY. Lượt ĐÊM tự động đi cùng lõi (`vnstock_brief_pack` +
`vnstock_claude_cli`) khi `.env` máy chạy pipeline đặt
`VNSTOCK_BRIEF_ENGINE=claude` (hoặc công tắc chung `VNSTOCK_LLM_ENGINE=claude`)
— không cần skill.

## Quy trình

1. **Đọc gói**: `data_warehouse/_meta/brief_pack.json` chỉ để kiểm `session`
   = phiên hôm nay (T2–T6 sau 15:05 là hôm nay, cuối tuần là thứ 6) và
   `created_at`. Không có gói hoặc gói cũ → bảo user chạy
   `python run.py brief --export-pack` (○ máy nào cũng được — kho chung qua
   Dropbox) rồi dừng, KHÔNG tự bịa dữ liệu.
2. **Đọc prompt** ở `data_warehouse/_meta/brief_prompt.md` (bản nhiều dòng —
   KHÔNG đọc trường `prompt` trong JSON, nó là một dòng 40K ký tự và tool Read
   cắt dòng dài, sẽ viết từ prompt cụt). Đó là TOÀN BỘ dữ liệu phiên + hướng
   dẫn định dạng (mục, thứ tự, số kiểu EN `{:,.2f}`). Chỉ dùng số có trong
   prompt; thiếu thì nói thiếu. Không cần công cụ nào khác.
3. **Ghi thân brief** (chỉ thân, không lời dẫn, không khung ```) vào
   `data_warehouse/_meta/brief_claude.md`.
4. **Bảo user gửi** (○ máy đang ngồi):
   `python run.py brief --from-file data_warehouse/_meta/brief_claude.md`
   Lệnh này chạy guard → validate → memory (agent_type=claude) → Telegram →
   marker (`engine=claude-file`). Cửa một-brief-mỗi-phiên chặn nếu phiên đó
   đã có brief; `--force` chỉ khi CỐ Ý gửi trùng. Gói khác phiên bị từ chối.

## Đường A headless (🖥️ DESKTOP) — để tham chiếu khi user hỏi

- Go/no-go: `python vnstock_brief_pack.py --check` dưới đúng tài khoản chạy
  task (`admin`): in exe, version, `auth status`, probe 1 chữ bằng ĐÚNG cờ
  của đêm. `ok: false` thì đọc `error`/`probe.error`.
- Bật: `.env` thêm `VNSTOCK_BRIEF_ENGINE=claude`; ghim
  `VNSTOCK_CLAUDE_CLI_EXE=<đường dẫn claude>` vì Task Scheduler dùng PATH
  registry. Tắt = xoá dòng.
- A/B có ý thức: `python run.py telegram close --engine claude --force`.
- Sáng hôm sau: `/brief-review`.

## Chuẩn chất lượng (guard sẽ dọn, nhưng viết đúng từ đầu tốt hơn)

- Mỗi nhận định gắn số từ prompt (điểm, %, tỷ); đọc kỹ khối "Độ tươi dữ liệu"
  và câu "(chưa gồm N mã lớn thiếu data)" — TB GTGD so trên cùng tập mã.
- Watchlist: mua / mục tiêu / cắt lỗ đúng thứ tự, cách nhau hợp lý (không
  mục tiêu về thấp hơn giá mua); không nhắc mã không có trong prompt.
- Không lộ chữ nháp: "(2 dòng)", "(Giá X từ data)", `BUY entry=…`, tên
  chiến lược `Strategy #N`. Sự kiện sắp tới không gồm hôm nay.
- Tiếng Việt, gọn; mỗi mục ≤ 6 dòng; kết bằng một câu hành động cho phiên tới.
