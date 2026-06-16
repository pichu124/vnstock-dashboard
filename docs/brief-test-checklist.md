# 🔬 Checklist test Close Brief (sau khi đóng phiên)

Brief các lần test sáng 16/06 đều chạy **trước 15:00** → "đóng cửa" thực ra là
**bar dở dang** (phiên chưa đóng), GTGD "chưa đủ dữ liệu". Cần test lại **SAU
15:00** (lý tưởng: sau `run.py all` tối, khi đã down data cả ngày + chạy screener)
để xác nhận các hành vi phụ-thuộc-data-cả-ngày.

**Cách chạy lại:**
```powershell
# Sau 15:00 (và tốt nhất sau khi pipeline tối chạy xong)
python run.py telegram close
# hoặc xem trong dashboard panel AI Brief
```

---

## ✅ ĐÃ FIX — xác nhận hoạt động (sáng 16/06)
- [x] **Tâm lý header = body** (momentum + nhãn khớp; hết "❄️ Sợ hãi/-24" mâu thuẫn "-33") — `enforce_sentiment_consistency`
- [x] **Độ rộng** không còn gọi sai "tích cực" khi % trên MA200 yếu — `enforce_breadth_quality`
- [x] **Telegram tách tin** (1/2)+(2/2) — mục 📰 hiện đầy đủ, hết "[tin bị rút gọn]"
- [x] **Vs MA đúng chiều** ("dưới MA20 (-1.9%)" thay vì "trên MA20 (-1.9%)")
- [x] **Vĩ mô** (tỷ giá auto + lãi suất) & **📰 tin** (sentiment + tác động ngành) hiển thị đúng

---

## 🔬 CẦN TEST LẠI SAU 15:00 (data cả ngày)
Các điểm này CHỈ đúng/đủ khi phiên đã đóng + đã down data cả ngày:

- [ ] **Header KHÔNG còn** "⚠️ độ rộng/regime: phiên cũ" (sau khi `run.py screener` với data hôm nay)
- [ ] **"Kết quả phiên / Đóng cửa"** là số CHỐT THẬT (không phải bar dở giữa phiên)
- [ ] **GTGD cả ngày HIỆN** (không còn "chưa đủ dữ liệu") — vì phiên đã đóng
- [ ] **Mục "Tổng kết phiên"** so GTGD cả-ngày-vs-cả-ngày (TB5/TB20), KHÔNG dùng baseline sáng
- [ ] **session_timing** (institutional/retail) hiện lại (morning_share hợp lệ sau khi đóng)
- [ ] **Stance ngày mai** bám regime/sentiment (bias floor)
- [ ] **Dẫn dắt/Tụt hậu** đúng lead/lag deterministic + đóng góp pp (1 tuần)
- [ ] **Watchlist**: neo giá thật, mã ⭐ đủ thanh khoản, BUY/SELL nhất quán
- [ ] **Rủi ro**: không mis-flag ngân hàng/CK; D/E + Op.CF (BĐS có ngữ cảnh quỹ đất)
- [ ] **Khuyến nghị đang mở**: số ngày hợp lý, rec quá hạn đã reconcile
- [ ] **Mọi % giá** có khung thời gian rõ; mã chỉ trong VN30/watchlist

---

## ⏳ VẤN ĐỀ CÒN MỞ (chưa fix — quyết định sau khi test)
Ghi lại để bàn tiếp; chưa code vì chờ test bản đóng phiên:

1. **#3 — Close brief chạy TRƯỚC 15:00** → "đóng cửa" là bar dở. Hướng fix khả dĩ:
   thêm cảnh báo/chặn khi tạo close brief lúc phiên chưa đóng (`force=True` qua
   telegram đang bỏ qua cổng giờ 15:00). *Quyết định: có thêm cảnh báo không?*
2. **#4 — Tin toàn 🟢 nhưng Stance GIẢM** → brief chưa nhoà giải mâu thuẫn
   "kỹ thuật yếu vs tin/dòng tiền tốt". Hướng: thêm 1 câu reconcile trong Tổng kết.
3. **#5 — Watchlist 2 lệnh đều MUA-điều-kiện** dưới stance GIẢM → thiếu kèo phòng
   thủ. Hướng: ép ≥1 hướng "GIẢM TỶ TRỌNG/TRÁNH nếu thủng hỗ trợ" (guard).
4. **Nhỏ** — A/D 1.33 thực ra hơi DƯƠNG (>1); "trái chiều" (A/D dương + cấu trúc
   MA200 yếu) chính xác hơn "nghiêng tiêu cực". Cân nhắc mở rộng `enforce_breadth_quality`.

> Sau khi test bản close brief THẬT (sau 15:00), tick các ô 🔬 ở trên và quyết định
> xử #3/#4/#5 hay không.
