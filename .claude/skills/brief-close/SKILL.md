---
name: brief-close
description: Viết brief chiều (close brief) chất lượng cao từ gói brief pack do pipeline xuất (data_warehouse/_meta/brief_pack.json), ghi ra brief_claude.md rồi nạp lại bằng `run.py brief --from-file`. Dùng khi user gõ /brief-close, muốn tự tay thay bản ladder, hoặc pipeline đêm rơi về ladder.
---

# /brief-close — viết brief chiều bằng Claude

Đường brief của repo (ctx → prompt → agent → 55 guard → memory → Telegram →
marker một-brief-mỗi-phiên) giữ nguyên; skill này chỉ thay **agent** bằng
Claude ở lượt TAY. Lượt ĐÊM tự động đi cùng lõi (`vnstock_brief_pack`) khi
`.env` máy chạy pipeline đặt `VNSTOCK_BRIEF_ENGINE=claude` — không cần skill.

## Quy trình

1. **Đọc gói** `data_warehouse/_meta/brief_pack.json` (hoặc đường dẫn user
   đưa). Kiểm `session` = phiên hôm nay (T2–T6 sau 15:05 là hôm nay, cuối
   tuần là thứ 6). Không có gói hoặc gói cũ → bảo user chạy
   `python run.py brief --export-pack` (○ máy nào cũng được — kho chung qua
   Dropbox) rồi dừng, KHÔNG tự bịa dữ liệu.
2. **Viết brief** từ trường `prompt`: đó là TOÀN BỘ dữ liệu phiên + hướng dẫn
   định dạng (mục, thứ tự, số kiểu EN `{:,.2f}`). Chỉ dùng số có trong gói;
   thiếu thì nói thiếu. Không cần công cụ nào ngoài đọc gói.
3. **Ghi thân brief** (chỉ thân, không lời dẫn, không khung ```) vào
   `data_warehouse/_meta/brief_claude.md`.
4. **Bảo user gửi** (○ máy đang ngồi):
   `python run.py brief --from-file data_warehouse/_meta/brief_claude.md`
   Lệnh này chạy guard → validate → memory (agent_type=claude) → Telegram →
   marker. Cửa một-brief-mỗi-phiên chặn nếu phiên đó đã có brief; `--force`
   chỉ khi CỐ Ý gửi trùng. Muốn xem trước không gửi: đọc lại file md.

## Chuẩn chất lượng (guard sẽ dọn, nhưng viết đúng từ đầu tốt hơn)

- Mỗi nhận định gắn số từ gói (điểm, %, tỷ); đọc kỹ khối "Độ tươi dữ liệu"
  và câu "(chưa gồm N mã lớn thiếu data)" — TB GTGD so trên cùng tập mã.
- Watchlist: mua / mục tiêu / cắt lỗ đúng thứ tự, cách nhau hợp lý (không
  mục tiêu về thấp hơn giá mua); không nhắc mã không có trong gói.
- Không lộ chữ nháp: "(2 dòng)", "(Giá X từ data)", `BUY entry=…`, tên
  chiến lược `Strategy #N`. Sự kiện sắp tới không gồm hôm nay.
- Tiếng Việt, gọn; mỗi mục ≤ 6 dòng; kết bằng một câu hành động cho phiên tới.
