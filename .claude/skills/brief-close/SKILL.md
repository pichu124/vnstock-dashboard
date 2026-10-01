---
name: brief-close
description: Viết brief chiều (close brief) chất lượng cao từ gói brief pack do pipeline xuất (data_warehouse/_meta/brief_pack.json + brief_prompt.md), ghi ra brief_claude.md rồi nạp lại bằng `run.py brief --from-file`. Dùng khi user gõ /brief-close, muốn tự tay thay bản ladder, hoặc pipeline đêm rơi về ladder.
---

# /brief-close — viết brief chiều bằng Claude, trọn vòng trên máy đang ngồi

Đường brief của repo (ctx → prompt → agent → 55 guard → memory → Telegram →
marker một-brief-mỗi-phiên) giữ nguyên; skill này chỉ thay **agent** bằng
Claude ở lượt TAY. Lượt ĐÊM tự động đi cùng lõi (`vnstock_brief_pack` +
`vnstock_claude_cli`) khi `.env` máy chạy pipeline đặt
`VNSTOCK_LLM_ENGINE=claude` (hoặc riêng `VNSTOCK_BRIEF_ENGINE=claude`)
— không cần skill. ○ Chạy được ở cả 🖥️ desktop lẫn 💻 laptop vì gói, file
brief và marker đều nằm trong kho Dropbox; CHỈ chạy trên máy có kho (phiên
Claude Code cloud không thấy `data_warehouse`, dừng ngay nếu thiếu thư mục đó).

## Python: LUÔN dùng venv, KHÔNG gõ `python` trần

Claude Code có thể được mở từ shell chưa kích hoạt venv (30/09 desktop:
`python` trỏ `C:\Python314` không có pandas ⇒ `--export-pack` chết). Cả hai
máy giữ venv ở `%USERPROFILE%\.venv` (desktop tài khoản `admin`, laptop
`Administrator`), nên gọi thẳng interpreter đó:

- Bash (tool Bash của Claude Code trên Windows = Git Bash):
  `PY=~/.venv/Scripts/python.exe`
- PowerShell: `$PY = "$env:USERPROFILE\.venv\Scripts\python.exe"`

Kiểm một lần trước khi làm gì: `$PY -c "import pandas, vnstock_brief_pack; print('venv ok')"`.
Lỗi import ⇒ sai venv, hỏi user đường venv thật, đừng cài gì.

## Quy trình

1. **Gói đúng phiên chưa?** Đọc `data_warehouse/_meta/brief_pack.json`, chỉ
   hai trường `session` và `created_at`. Phiên cần = hôm nay nếu là T2–T6 sau
   15:05, còn lại là phiên trước (T7/CN = thứ 6). Gói thiếu hoặc phiên cũ ⇒
   TỰ xuất: `$PY run.py brief --export-pack` (1–3′; VCI hay timeout, cửa
   ngân sách 120s tự dừng). Xuất xong mà `session` VẪN là hôm qua dù hôm nay
   là ngày phiên sau 15:05 ⇒ kho chưa có bar hôm nay (phát 18:00 của desktop
   chưa sync): nói rõ cho user, chọn chờ sync hoặc `$PY run.py sync` (5′–100′),
   rồi DỪNG — không viết brief từ dữ liệu cũ. ⚠️ Ngày làm việc từ 18:00 tới khi
   `run_daily.log` của desktop in `⏱ TỔNG`, KHÔNG xuất gói từ laptop (kho đang
   được pipeline ghi).
2. **Đọc prompt** ở `data_warehouse/_meta/brief_prompt.md` (bản nhiều dòng —
   KHÔNG đọc trường `prompt` trong JSON, nó là một dòng 40K ký tự và tool Read
   cắt dòng dài, sẽ viết từ prompt cụt). Đó là TOÀN BỘ dữ liệu phiên + hướng
   dẫn định dạng (mục, thứ tự, số kiểu EN `{:,.2f}`). Chỉ dùng số có trong
   prompt; thiếu thì nói thiếu. Không cần công cụ nào khác.
3. **Ghi thân brief** (chỉ thân, không lời dẫn, không khung ```) vào
   `data_warehouse/_meta/brief_claude.md`. Hiện cho user 6 dòng đầu + số dòng.
4. **Gửi — HỎI trước, gửi sau.** Telegram là hành động ra ngoài, không tự gửi.
   User gật thì chạy:
   `$PY run.py brief --from-file data_warehouse/_meta/brief_claude.md`
   Lệnh này chạy guard → validate → memory (agent_type=claude) → Telegram →
   marker (`engine=claude-file`). Đọc output và báo lại: dòng `[brief] ⚠️` là
   cảnh báo validator, `message_id` là đã tới Telegram. Hai cửa gác:
   - gói khác phiên đang gửi ⇒ lệnh từ chối; chỉ `--force` khi user cố ý;
   - phiên ĐÃ có brief (marker) ⇒ lệnh im; hỏi user có muốn gửi bản THỨ HAI
     bằng `--force` không (A/B có ý thức, ví dụ thay bản ladder tối đó).
   Gửi TRƯỚC 18:00 ngày phiên ⇒ marker đã ghi, bước brief của phát tối tự bỏ
   qua, không trùng.
5. **Khép:** nhắc sáng hôm sau `/brief-review` để chấm sao (≥4 thành mẫu
   few-shot cho cả Claude lẫn ladder).

## Đường A headless (🖥️ DESKTOP) — để tham chiếu khi user hỏi

- Go/no-go: `$PY vnstock_brief_pack.py --check` dưới đúng tài khoản chạy
  task (`admin`): in exe, version, `auth`, probe 1 chữ bằng ĐÚNG cờ của đêm,
  `shim` (true = bản npm `claude.cmd`, ghim bản native), 6 bước đang đặt
  engine gì. `ok: false` thì đọc `error`/`probe.error`.
- Bật: `.env` thêm `VNSTOCK_LLM_ENGINE=claude` (cả 5 bước LLM) hoặc chỉ
  `VNSTOCK_BRIEF_ENGINE=claude`; ghim `VNSTOCK_CLAUDE_CLI_EXE=<đường dẫn
  claude.exe>` vì Task Scheduler dùng PATH registry. Tắt = xoá dòng. `.env`
  không đồng bộ ⇒ mỗi máy một bản; laptop không có task nên chỉ cần khi chạy
  lệnh tay `--engine claude` ở đó.
- A/B có ý thức: `$PY run.py telegram close --engine claude --force`.
- Sáng hôm sau: `/brief-review`.

## Chuẩn chất lượng (guard sẽ dọn, nhưng viết đúng từ đầu tốt hơn)

- Mỗi nhận định gắn số từ prompt (điểm, %, tỷ); đọc kỹ khối "Độ tươi dữ liệu"
  và câu "(chưa gồm N mã lớn thiếu data)" — TB GTGD so trên cùng tập mã.
- Watchlist: mua / mục tiêu / cắt lỗ đúng thứ tự, cách nhau hợp lý (không
  mục tiêu về thấp hơn giá mua); không nhắc mã không có trong prompt. Mã đang
  có lệnh mở trong khối "Khuyến nghị" ⇒ nhắc lệnh đó, đừng cho hai bộ mốc.
- Đề xuất giao dịch viết thuần Việt: "MUA vùng · chốt lời · cắt lỗ · KL gợi
  ý", KHÔNG chép `BUY entry=…`, KHÔNG lộ `Strategy #N`/`conf`.
- Danh mục đang giữ: mỗi mã một hành động kèm MỨC giá nếu prompt có; không
  có mức thì nói thiếu ở "Đề xuất bổ sung" thay vì "Không cần bổ sung".
- Không lộ chữ nháp: "(2 dòng)", "(Giá X từ data)". Sự kiện sắp tới không
  gồm hôm nay. Ngành nhắc tới kèm %VNI khi prompt có.
- Tiếng Việt, gọn; mỗi mục ≤ 6 dòng; kết bằng một câu hành động cho phiên tới.
