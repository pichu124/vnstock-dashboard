# THIẾT KẾ — Nâng chất lượng nhận định phân tích kỹ thuật của bot

> Trạng thái: **ĐANG LÀM P0 + P1** (user chốt hết 04/11, §14).
> Phạm vi (chốt 04/11): brief sáng/chiều (Telegram) + các mã brief nhắc tới **và** chữ AI ở tab Phân tích mã.

## 1. Vấn đề — đo từ code, không phải cảm giác

Khảo sát code 04/11 (file:line là ở `e55b632`).

### 1a. Bot đang "nhìn" kỹ thuật rất hẹp

- **VN-Index**: `_vnindex_technicals()` (`vnstock_brief.py:3262`) chỉ có:
  - MA20/50/200 (SMA) + độ dốc MA20 5 phiên;
  - RSI(14) Wilder, CHOP(14), nến + chuỗi Heikin-Ashi;
  - pivot S1/S2/R1/R2 từ đỉnh/đáy swing 60 phiên.
  - **Không** có khối lượng, MACD, ATR.
- **Từng mã trong brief** (`vn30_gainers/losers`, danh mục): chỉ có %1 tuần, giá, ngành, GTGD TB và S/R
  pivot 60 phiên (`_attach_ticker_sr`, :2457). Screener đã tính sẵn cho từng mã RSI, MACD cắt, xu hướng EMA,
  đột biến khối lượng, Bollinger %, ConnorsRSI, mẫu nến, hai đáy W (`vnstock_screener.py:156-290`), nhưng
  **không thứ nào tới brief**.
- **Đa khung chỉ có ở chỉ số** (`vnstock_horizons`, đóng tuần). Từng mã không có khung tuần.
- **Xoay vòng ngành bị tắt**:
  - brief gọi `compute_scores(df)` không truyền `index_returns` (`vnstock_brief.py:2620`; `compute_index_returns`
    import ở :2617 mà không dùng);
  - vì vậy `alpha_*`/`rotation` không bao giờ có, khối "Rotation signal" luôn rỗng;
  - dashboard thì có truyền (`dashboard/market_commentary.py:182`).

### 1b. Số liệu không nhất quán giữa các chỗ

- **RSI hai công thức**: SMA 14 ở screener, độ rộng và chart (`vnstock_screener.py:184`, `vnstock_runner.py:410`,
  `dashboard/chart_indicators.py`), nhưng Wilder ở VN-Index và `analyze_ticker` (`vnstock_brief.py:3346`,
  `vnstock_strategy.py:2508`). Comment :3342 "same formula as ticker indicators" là SAI. Gauge dashboard và
  chữ AI của cùng một mã có thể lệch nhau vài điểm RSI.
- **Độ rộng "MA200" thật ra là EMA200** (`vnstock_runner.py:402-429`), trong khi MA của chỉ số là SMA.
- **Ngưỡng RSI**: nhãn trong prompt dùng 70/30, phiếu regime dùng 60/40 (`vnstock_regime.py`).

### 1c. Phần chữ kỹ thuật gần như thả nổi

- Code dựng: 🔭 khung, nhãn Stance, nhãn độ rộng, % vị trí trong biên tuần.
- **Model tự viết**: cả đoạn "📈 Mức kỹ thuật" (vị trí so MA, đọc RSI, câu trigger), kịch bản, setup watchlist.
- Guard hiện có chỉ ghim **số** chỉ số trong dải 800–2500 và thứ tự S < giá < R. **Không guard nào** kiểm tra:
  - giá trị RSI model viết;
  - "trên/dưới MA" đúng hay sai;
  - chữ xu hướng (tăng/giảm/đi ngang) khớp độ dốc MA hay không;
  - lời về nến/CHOP;
  - S/R từng mã có khớp `sr_support`/`sr_resistance` không.
- Template sáng bắt nêu đủ MA20/50/200 nhưng không guard nào canh; trigger breakout không có điều kiện khối
  lượng dù template :349 có nhắc "% volume".

### 1d. Không có thước đo "nhận định kỹ thuật đúng hay sai"

- `brief_memory.db` lưu `context_json` đầy đủ (S1/R1, MA, horizons) nhưng **không lưu nhận định dạng cấu trúc**.
  Mọi bộ chấm phải đọc lại chữ.
- Chấm hiện có: chỉ **Stance T+1**, hai bộ chấm lệch ngưỡng nhau:
  - `vnstock_brief.py:5311` dùng ±0,5% và trộn brief sáng với chiều;
  - `vnstock_stance_track.py` chỉ brief chiều, dùng 0,1/0,3%.
- **Chưa bao giờ đo**:
  - S/R có được giá tôn trọng không;
  - trigger "vượt R1 → test R2" có trúng không;
  - setup watchlist của brief (vào/cắt lỗ/chốt lời) thắng hay thua — chỉ khuyến nghị của strategy backtest
    được chấm (`vnstock_train.reconcile_recommendations`);
  - "mức kích hoạt" tuần của horizons;
  - lợi suất sau mỗi trạng thái regime.
- Vòng học lại không dùng độ đúng:
  - few-shot lấy brief ≥4★ làm mẫu **văn phong**;
  - `vnstock_reflection` chỉ rút bài học từ khuyến nghị strategy;
  - độ đúng Stance không vào prompt nào.
- Kế hoạch đo P2 của `THIET-KE-BRIEF-3-KHUNG.md` (T+5/T+20, chấm theo đường đi, "kịp xoay sở?") chưa có code.

**Kết luận:** muốn nhận định "tốt hơn" thì trước hết phải có thước đo "tốt". Không có thước đo thì mọi sửa
prompt chỉ là đổi văn phong. Thứ tự các phần bên dưới vì vậy là **đo → sửa nền → cho bot nhìn đúng → khoá chữ
→ học từ kết quả**.

## 2. Nguyên tắc (giữ theo quy ước repo)

1. **Code tính, model diễn giải.** Mọi dữ kiện kỹ thuật (giá trị, trên/dưới, xu hướng, khối lượng xác nhận hay
   không) do code dựng thành câu có từ vựng cố định. Model chỉ nối các dữ kiện thành nhận định, không tự tính.
   Cách này giống mục ⚠️ Rủi ro (U75) và khối 🔭.
2. **Đếm trước, vá sau** (`vnstock_brief_watch`): nghi ngờ chưa đủ mẫu thì đếm, badge `ok n=…` dưới sàn mẫu.
3. **Không chỉnh ngưỡng bằng mắt.** Ngưỡng (khoảng cách S/R, khối lượng xác nhận, RSI quá mua) chỉ đổi khi có
   số từ thước đo ở P0/P5.
4. Mỗi phần có **công tắc env** (`VNSTOCK_TA_*`) và mặc định TẮT cho tới khi bản mẫu được duyệt, như
   `VNSTOCK_HORIZONS`.
5. **Không đổi số screener/preset âm thầm.** Sửa công thức RSI làm đổi kết quả lọc ⇒ user quyết (§8).

## 3. P0 — Thước đo nhận định kỹ thuật (làm TRƯỚC)

Module mới `vnstock_ta_score.py`, hàm thuần + CLI `run.py ta-score [--show|--backfill]`, chạy lại trên lịch sử
có sẵn trong `brief_memory.db` (`context_json` đã có S1/R1/MA của từng ngày ⇒ **backfill được ngay**, không
phải chờ):

| Mã đo | Đo cái gì | Cách chấm |
|---|---|---|
| T1 | S1/R1 của VN-Index có giữ không | trong N phiên: chạm-rồi-bật / xuyên thủng (đóng cửa vượt quá X%) / không chạm. Tỉ lệ "chạm thì giữ" so với **mốc ngẫu nhiên** (mức giả cùng khoảng cách) |
| T2 | Trigger "vượt R1 → test R2" / "thủng S1 → về S2" | khi đóng cửa vượt R1: P(chạm R2 trong N phiên); có khối lượng xác nhận vs không |
| T3 | Stance theo đúng **một** quy tắc | gộp hai bộ chấm về cùng ngưỡng; tách sáng/chiều; T+1 **và** T+5; so mốc "luôn trung tính" và "lặp hôm qua" |
| T4 | Regime / horizons | lợi suất T+5/T+20 sau từng trạng thái (đúng mục S1/A1 §7.2 thiết kế 3 khung) |
| T5 | S/R từng mã trong brief | như T1, cho các mã có `sr_support`/`sr_resistance` |

- Kết quả ghi `_meta/ta_score.json`; badge doctor `ta_score` dưới sàn mẫu luôn `ok n=…`.
- **Đây là mốc nền.** Mọi phần sau phải làm số này tốt lên, hoặc ít nhất không xấu đi.

## 4. P1 — Sửa nền số liệu (rẻ, ít rủi ro)

1. Một hàm chỉ báo dùng chung `vnstock_indicators.rsi_wilder(close, 14)`, `sma`, `ema`, `atr` — mọi nơi gọi chung.
   **RSI screener/độ rộng/chart chuyển sang Wilder là thay đổi thấy được** (đếm RSI<30/>70, preset dùng RSI) ⇒ chờ §8
   câu 2. Dù chọn gì: sửa comment sai :3342 và ghi rõ công thức trên nhãn.
2. Nhãn độ rộng: "% mã trên EMA200" (hoặc đổi sang SMA200 cho khớp chỉ số — §8 câu 2).
3. Truyền `index_returns` vào `compute_scores` trong brief ⇒ alpha vs VN-Index + tín hiệu xoay vòng ngành sống lại
   (đã có test phía dashboard). Một bước một dòng, nhưng nội dung brief sẽ có thêm khối ⇒ duyệt bản mẫu.
4. Thống nhất ngưỡng RSI giữa nhãn prompt và phiếu regime (giữ 2 tầng có tên: "mạnh/yếu" 60/40, "quá mua/quá bán"
   70/30) — một hằng ở `vnstock_brief_canon.py`.

## 5. P2 — "Thẻ kỹ thuật" do code dựng

Hàm thuần `ta_card(bars_daily, bars_weekly) -> dict + lines` dùng chung cho VN-Index và từng mã brief nhắc tới
(mã chạy mạnh/yếu, danh mục, ứng viên watchlist). Mỗi thẻ có:

| Nhóm | Dữ kiện | Từ vựng cố định |
|---|---|---|
| Xu hướng | giá vs MA20/50/200, MA xếp chồng, độ dốc MA20/MA50 | "xu hướng tăng / giảm / đi ngang" theo luật code |
| Khung tuần | đóng tuần vs MA10w/MA40w (như horizons) | "tuần cùng chiều / ngược chiều ngày" |
| Động lượng | RSI Wilder, MACD (trên/dưới tín hiệu, mới cắt) | "mạnh / yếu / quá mua / quá bán" |
| Khối lượng | KL phiên / TB20, KL phiên tăng vs giảm 10 phiên | "có / không xác nhận" |
| Biến động | ATR(14) % giá; khoảng tới S1/R1 tính bằng **bội ATR** | "S1 cách 1,2 ATR" |
| Mức giá | S/R pivot 60 phiên (đã có) + số lần chạm | — |
| Mẫu hình | nến, hai đáy W, Heikin-Ashi (đã có ở screener) | chỉ in khi bar đã đóng |

- Brief in thẻ VN-Index đầy đủ, thẻ từng mã **1 dòng nén** (vd. `FPT: ↗ tăng (trên MA20/50/200) · RSI 64 mạnh ·
  KL 1,4× xác nhận · S 112,5 (1,1 ATR) / R 121,0`).
- Prompt đổi từ "tự đọc chỉ báo" sang "**dùng đúng nhãn thẻ, chỉ được kết luận từ các dòng thẻ**".
- Khối lượng của VN-Index cần xác minh trên kho thật (rollup bỏ index — CLAUDE.md bất biến) ⇒ đo trước khi hứa.
- Đầu ra: bản mẫu `scripts/sample_ta_brief.py` trên ctx thật, user duyệt trước khi bật `VNSTOCK_TA_CARD`.

## 6. P3 — Khoá chữ kỹ thuật bằng guard

Thêm vào `_guards_numbers` / `_guards_text`, nối vào `apply_brief_guards`, mỗi guard một test:

- `enforce_rsi_value` — RSI model viết phải khớp thẻ (±1), nhãn RSI khớp ngưỡng canon.
- `enforce_ma_position` — "trên/dưới MA20/50/200" phải đúng chiều thẻ; template sáng thiếu MA nào thì code chèn.
- `enforce_trend_word` — chữ xu hướng của VN-Index/mã phải khớp nhãn thẻ (sửa hoặc gắn dòng thẻ vào).
- `enforce_ticker_sr` — số hỗ trợ/kháng cự từng mã phải là `sr_support`/`sr_resistance` (như `enforce_pivot_labels`
  cho chỉ số).
- `enforce_breakout_volume` — câu "vượt/thủng mức X" phải kèm điều kiện khối lượng của thẻ.
- Chưa chắc lời nào đúng (vd. đọc nến) ⇒ đếm bằng `vnstock_brief_watch` trước, không guard ngay.

## 7. P4 — Học từ kết quả (vòng phản hồi)

1. Lưu **nhận định dạng cấu trúc** cạnh chữ: stance + mức trigger/hủy + setup watchlist (vào/SL/TP) ⇒ bảng
   `brief_calls` trong `brief_memory.db`; chấm bằng lại `_grade_rec` (`vnstock_train.py:541`) như khuyến nghị strategy.
2. `vnstock_reflection` rút bài học từ **cả nhận định kỹ thuật của brief** (setup thua, trigger hụt) — 3 bài học
   mới nhất vào khối nội bộ như hiện tại.
3. Few-shot chọn theo **đúng + hay** (sao user × kết quả chấm), không chỉ sao.
4. P5 (sau ≥60 phiên số P0): hiệu chỉnh ngưỡng từ dữ liệu — khoảng cách S/R tối thiểu, KL xác nhận, trọng số
   phiếu regime — kèm khoảng tin cậy; chỉ ĐỀ XUẤT, user duyệt mới áp.

## 8. Câu hỏi cho user (chặn trước khi code)

1. **Phạm vi**: chỉ brief Telegram, hay cả chữ AI ở tab Phân tích mã (`analyze_ticker`, hiện không có guard nào)?
2. **RSI/độ rộng**: chuyển screener + độ rộng + chart sang RSI Wilder và SMA200 cho khớp chỉ số (số đếm RSI và
   kết quả preset sẽ ĐỔI), hay giữ nguyên và chỉ ghi rõ nhãn?
3. **Khung giao dịch của bạn**: thường giữ mã bao lâu (vài phiên / 2–4 tuần / vài tháng)? Quyết định N phiên
   dùng để chấm đúng/sai ở P0 và độ dài thẻ tuần.
4. **Ai viết đoạn "📈 Mức kỹ thuật"**: (a) code viết dữ kiện, model ≤2 dòng nhận định (chặt, như mục Rủi ro); hay
   (b) model viết như cũ nhưng bị guard ghim?
5. **Độ dài brief**: chấp nhận thêm 1 dòng thẻ cho mỗi mã được nhắc (khoảng 5–10 dòng) không?

## 9. Thứ tự và việc của user

| Bước | Ai | Máy |
|---|---|---|
| Trả lời §8 | user | — |
| P0 code + test (backfill từ lịch sử) | Claude | cloud |
| Chạy `run.py ta-score --backfill --show`, gửi kết quả | user | ○ máy nào cũng được (kho Dropbox chung), **tránh giờ pipeline 18:00 → `⏱ TỔNG`** |
| P1 + P2 + bản mẫu trên ctx thật | Claude | cloud |
| Duyệt bản mẫu, bật `VNSTOCK_TA_CARD` | user | 🖥️ DESKTOP (máy chạy task Daily đọc `.env` của nó) |
| P3, P4 | Claude | cloud |
| So số P0 sau ~20 và ~60 phiên | user + Claude | ○ |

## 10. Quyết định sau khi user trả lời (04/11)

### 10a. User đã trả lời

| Câu | Trả lời | Hệ quả |
|---|---|---|
| 1 Phạm vi | Cả hai | `analyze_ticker` (tab Phân tích mã) đọc **cùng** thẻ kỹ thuật + **cùng** bộ guard với brief — một nguồn, hai chỗ hiện |
| 2 Công thức | Chọn cái tốt hơn, dùng thống nhất | Xem §10b |
| 3 Khung | Cả 3 khung ngắn / trung / dài hạn, như thiết kế 3 khung | Thẻ và thước đo có đủ 3 khung — §10c |
| 4 Ai viết "📈 Mức kỹ thuật" | Claude đề xuất cách tốt nhất | §10d |
| 5 Thêm 1 dòng thẻ mỗi mã | Có | Mỗi mã 1 dòng nén, có 3 khung |

### 10b. Công thức: chọn RSI Wilder + SMA200

- **RSI Wilder** (trung bình trượt mũ, `ewm(alpha=1/14)`) là định nghĩa gốc của RSI và là số mà TradingView, bảng
  giá SSI/Vietstock hiển thị. RSI trung bình đơn (Cutler) chỉ có ở repo này. Dùng Wilder thì số trên dashboard khớp số
  bạn thấy ở app môi giới; dùng Cutler thì lệch tới vài điểm ở vùng 30/70.
- **SMA200** cho độ rộng "% mã trên MA200": chỉ số độ rộng chuẩn tính bằng SMA200, và MA của VN-Index trong brief
  cũng là SMA ⇒ một nghĩa cho chữ "MA200" ở mọi chỗ.
- **Làm sao cho an toàn**: đổi công thức làm ngưỡng cũ lệch (preset dùng RSI, phiếu độ rộng 55%/35%, đếm RSI<30/>70).
  Trước khi đổi: chạy cả hai công thức trên lịch sử giá, in số mã preset thay đổi và số phiên phiếu regime đổi chiều.
  Ngưỡng nào đổi kết quả nhiều thì hiệu chỉnh lại theo phân vị, không giữ nguyên số cũ. Lịch sử độ rộng (mới có từ
  06/2026) **tính lại từ kho giá** để chuỗi liền mạch.

### 10c. Ba khung trong phân tích kỹ thuật

| Khung | Dữ kiện kỹ thuật (thẻ) | Chấm đúng/sai sau | Mẫu để chấm |
|---|---|---|---|
| Ngắn hạn (vài phiên) | giá vs MA20, RSI, MACD, KL xác nhận, S1/R1, nến | T+1, T+5 | lịch sử brief (`brief_memory.db`) + backtest giá |
| Trung hạn (xu hướng tuần) | đóng tuần vs MA10w/MA40w (như horizons), độ dốc MA50, S/R tuần | T+20, T+60 | **backtest trên kho giá 2017 → nay** (lịch sử brief quá ngắn) |
| Dài hạn (6–12 tháng) | giá vs MA200 + độ dốc, vị trí 52 tuần, đóng tháng — xem §11 câu 1 | T+120, T+250 | chỉ backtest kho giá |

Hệ quả cho P0: tách hai phần — **(A) chấm nhận định ĐÃ PHÁT** từ lịch sử brief (chủ yếu ngắn hạn) và **(B) backtest
luật kỹ thuật** trên kho giá nhiều năm (trung/dài hạn, và cả ngắn hạn để có đủ mẫu).

### 10d. Đề xuất cho câu 4 — "code nói dữ kiện, model nói ý nghĩa, guard giữ ranh giới"

LLM giỏi tổng hợp và giải thích tín hiệu mâu thuẫn, nhưng hay sai số học, nhầm chiều và tự đặt số. Code thì ngược
lại. Cách tốt nhất là chia việc theo đúng sở trường đó:

1. **Code dựng khối "📈 Kỹ thuật"** (giống 🔭 và ⚠️ Rủi ro):
   - mỗi khung một dòng cho VN-Index, nhãn cố định:
     `Ngắn hạn: tăng — trên MA20, RSI 58 (mạnh), KL 1,3× TB20 xác nhận`;
   - dòng mức giá: `S1 1.245 (0,9 ATR) · R1 1.288 (1,4 ATR)`;
   - **dòng "tín hiệu lệch nhau"** do code phát hiện (vd. giá vượt MA20 nhưng KL không xác nhận; ngắn hạn tăng
     ngược trung hạn giảm) — đây là chỗ nhận định có giá trị nhất, và code thấy được một cách chắc chắn.
2. **Model viết tối đa 3 câu "Nhận định"**, theo khung bắt buộc:
   - ý chính, dựa trên các khung và dòng lệch nhau;
   - kịch bản 2 chiều, mỗi chiều kèm điều kiện: mức nào, khối lượng ra sao;
   - điều gì sẽ làm nhận định sai (mức huỷ).
3. **Guard giữ ranh giới:**
   - câu nhận định có số không nằm trong thẻ ⇒ bỏ câu đó;
   - chữ xu hướng ngược nhãn thẻ ⇒ sửa theo thẻ;
   - kịch bản "vượt/thủng" thiếu điều kiện khối lượng ⇒ code chèn điều kiện của thẻ;
   - model trả rỗng hoặc hỏng ⇒ khối vẫn đủ phần dữ kiện của code (không bao giờ trống).
4. **Chọn bằng số, không bằng cảm giác:**
   - chạy bóng song song bản cũ và bản mới ≥10 phiên (bản mới không gửi);
   - so 3 thứ: độ đúng của kịch bản (P0), số lần guard phải sửa, sao bạn chấm ở `/brief-review`;
   - bật bản mới khi không thua ở cả 3.
5. **Tab Phân tích mã** dùng y hệt: thẻ 3 khung hiện thành ô có màu, nút AI cho ra 3 câu nhận định qua cùng guard.

## 11. Câu còn mở (04/11, chặn trước khi code)

1. **Dài hạn kỹ thuật có tính vào đâu?** Thiết kế 3 khung (§3.6) cố ý để dài hạn của VN-Index là 5 trụ **phi giá**
   (vĩ mô, định giá…) và BỎ độ dốc MA200 vì đếm trùng với trung hạn. Với thẻ kỹ thuật thì chọn:
   (a) dòng dài hạn chỉ là **bối cảnh** (MA200, 52 tuần) — không ra nhãn, nhãn dài hạn vẫn do vĩ mô quyết;
   (b) có nhãn dài hạn kỹ thuật **riêng cho từng mã** (vĩ mô không áp được cho từng mã), VN-Index vẫn theo vĩ mô;
   (c) có nhãn dài hạn kỹ thuật cho cả VN-Index, đặt cạnh nhãn vĩ mô.
2. **Setup bạn có giao dịch theo không, và khớp lệnh kiểu nào?** Để chấm setup watchlist/khuyến nghị cho sát thật:
   vào lệnh giả định ở giá mở cửa phiên sau hay chạm đúng mức trigger; tính phí + thuế bao nhiêu (mặc định đề xuất
   0,15% mỗi chiều + 0,1% thuế bán); có tính T+2,5 (không bán được trước khi hàng về) không.
3. **Chi phí LLM ở tab Phân tích mã**: mỗi lần bấm AI là một lượt gọi. Dùng engine Claude (như brief) hay ladder
   free như bây giờ?
4. **Thông số thật từ kho** (○ máy nào cũng được, ngoài giờ pipeline) — chạy và dán kết quả để tôi chốt cỡ mẫu P0:
   `python -c "import sqlite3;c=sqlite3.connect('data_warehouse/_meta/brief_memory.db');print(c.execute('select brief_type,count(*),min(brief_date),max(brief_date) from briefs group by brief_type').fetchall())"`

## 12. Chốt lần 2 (04/11)

| Câu §11 | Trả lời | Hệ quả |
|---|---|---|
| 1 Dài hạn kỹ thuật | (b) | Mỗi mã có nhãn dài hạn kỹ thuật riêng (TĂNG / ĐI NGANG / GIẢM — từ vựng giá, KHÔNG dùng THUẬN/BẤT LỢI của vĩ mô để khỏi nhầm). VN-Index: nhãn dài hạn vẫn do 5 trụ vĩ mô; dòng MA200/52 tuần chỉ là bối cảnh |
| 2 Khớp lệnh | Khuyến nghị ra sau phiên ⇒ (i) phiên này đã chạm trigger thì mua giá **mở cửa phiên sau**; (ii) chưa chạm thì mua **lúc giá chạm trigger** ở phiên sau. Phí 0,15%/chiều + 0,1% thuế bán, **có T+2,5** | Bộ chấm setup — chi tiết + mặc định ở §13 |
| 3 Engine tab Phân tích mã | Claude | `analyze_ticker` qua `vnstock_claude_cli.complete`, ladder chỉ là đường rơi khi Claude lỗi; cache theo (mã, ngày dữ liệu) ⇒ bấm lại cùng ngày không tốn thêm lượt |
| 4 Số liệu kho | afternoon 729 bản 28/04 → 03/11 · morning 200 bản 28/04 → 05/10 · allocation 12 | Xem dưới |

**Đọc số liệu kho:**
- Brief chiều ~130 phiên nhưng 729 bản ⇒ **nhiều agent mỗi phiên** (ladder + Claude). P0 chấm theo từng agent (như bảng xếp hạng
  hiện có) VÀ riêng "bản đã gửi Telegram". Hiện `briefs` không có cờ "đã gửi" ⇒ P0 thêm cột `sent` từ nay; quá khứ suy theo
  `agent_type=claude` / marker khi xác định được, không suy được thì chỉ chấm theo agent.
- Brief sáng dừng lưu từ 05/10 là ĐÚNG (U11: brief sáng chỉ đọc lại state, chạy tay) ⇒ P0 chấm ngắn hạn chủ yếu trên brief chiều.
- ~130 phiên đủ chấm ngắn hạn T+1/T+5 (tỉ lệ có khoảng tin cậy ~±9 điểm). Trung hạn (T+20/T+60) và dài hạn (T+120/T+250)
  **không đủ** từ lịch sử brief ⇒ chỉ chấm bằng backtest luật trên kho giá 2017 → nay (đúng như §10c).

## 13. Câu còn mở (04/11, lần 3 — chặn trước khi code)

1. **Luật chấm setup — xác nhận các mặc định** (mua = phiên T):

   | Điểm | Mặc định đề xuất |
   |---|---|
   | Chưa chạm trigger thì setup còn hiệu lực | ngắn hạn 3 phiên · trung hạn 10 · dài hạn 20. Hết hạn chưa chạm = "không vào lệnh": không tính thắng/thua, nhưng đếm vào tỉ lệ khớp |
   | Mở cửa nhảy vượt trigger | mua giá mở cửa (xấu hơn trigger) |
   | Mở cửa ở giá trần | coi như không mua được |
   | T+2,5 | bán sớm nhất ở phiên T+2. Đã thủng cắt lỗ trước đó ⇒ bán giá mở cửa T+2 |
   | Một phiên chạm cả chốt lời lẫn cắt lỗ | tính cắt lỗ (thận trọng) |
   | Giữ tối đa, chưa chạm chốt lời/cắt lỗ | ngắn hạn 10 phiên · trung hạn 60 · dài hạn 250 ⇒ bán giá đóng cửa ngày hết hạn |
   | Kết quả | % mỗi lệnh sau phí/thuế, mỗi setup một phần bằng nhau; so với mua-giữ VN-Index cùng thời gian |

2. **Chi phí chạy bóng:** ≥10 phiên chạy song song bản cũ + bản mới ⇒ thêm khoảng một lượt Claude mỗi tối trong pipeline
   18:00 (thêm vài phút, chi phí cỡ một brief chiều — số thật xem `python vnstock_llm_ledger.py --show`). Tab Phân tích mã: một lượt
   mỗi (mã, ngày) khi bấm. Đồng ý?
3. **Thứ tự:** làm đo (P0) + sửa nền (P1) trước — mấy ngày công đầu brief CHƯA đổi gì thấy được, chỉ có bảng số chấm điểm.
   Rồi mới tới thẻ kỹ thuật (P2) chạy bóng. Đồng ý, hay muốn thấy thẻ kỹ thuật sớm hơn (P2 làm song song P0)?

## 14. Chốt lần 3 (04/11) — bắt đầu làm

| Câu §13 | Trả lời |
|---|---|
| 1 Luật chấm setup | Đồng ý toàn bộ mặc định §13.1 |
| 2 Chạy bóng | **Bỏ chạy song song 10 phiên.** Thay bằng **chạy lại trên lịch sử**: dựng bản mới cho 20–30 phiên cũ (mỗi phiên chỉ dùng dữ liệu tới ngày đó), đặt cạnh brief cũ cùng phiên, chấm cả hai bằng P0, user duyệt mẫu ⇒ **bật luôn**. Bản cũ giữ sau công tắc env để quay lại |
| 3 Thứ tự | P0 + P1 trước, rồi P2 |

### 14a. Đặc tả P0 (`vnstock_ta_score.py`)

- **Phần A — chấm nhận định đã phát** (`brief_memory.db`, brief chiều chủ yếu):
  - T1 S1/R1 VN-Index (`context_json.vnindex_tech.support_1/resistance_1`): trong 5 phiên — chạm rồi giữ / xuyên
    (đóng cửa vượt quá 0,5%) / không chạm; so với **mức giả** đặt cùng khoảng cách ở phía ngược lại của ngày ngẫu nhiên.
  - T2 trigger "đóng cửa vượt R1 ⇒ chạm R2" / "thủng S1 ⇒ chạm S2" trong 5 phiên; tách có/không khối lượng xác nhận
    (KL phiên ≥ 1,2× TB20; chỉ số không có KL thì ghi "không đo được").
  - T3 Stance theo **một** quy tắc: phẳng = |Δ| < 0,3%; T+1 và T+5; tách brief sáng/chiều, theo agent, và riêng bản đã
    gửi; mốc so: "luôn trung tính", "lặp chiều hôm qua".
  - T5 S/R từng mã (`sr_support`/`sr_resistance` của mover + danh mục) như T1.
- **Phần B — backtest trên kho giá** (đủ mẫu cho trung/dài hạn):
  - T4 trạng thái ngắn/trung hạn của horizons (dựng lại bằng `vnstock_horizons_state` từ lịch sử) ⇒ lợi suất VN-Index
    T+5/T+20/T+60 sau mỗi trạng thái, khoảng tin cậy Wilson cho tỉ lệ tăng.
- **Bộ chấm setup** `grade_setup(bars, setup, frame)` — hàm thuần theo đúng bảng §13.1 (dùng ở bước chạy lại lịch sử và P4).
- **Cột `sent`** trong `briefs` (bản đã gửi Telegram) — ghi từ nay, best-effort, không bao giờ chặn đường gửi.
- Đầu ra `_meta/ta_score.json` + `run.py ta-score [--show|--backfill]` + badge doctor `ta_score` (dưới sàn mẫu: ok n=…).

### 14b. Đặc tả P1 (đợt 1 — chưa đổi số screener)

- Hàm chỉ báo dùng chung trong `vnstock_indicators`: `rsi_wilder`, `rsi_cutler` (giữ để so), `sma`, `ema`, `atr`.
- `scripts/compare_indicator_formulas.py`: chạy trên kho thật, in mỗi ngày số mã RSI<30/>70 (Cutler vs Wilder), % mã
  trên EMA200 vs SMA200, số phiên phiếu regime đổi chiều, số mã preset đổi ⇒ user chạy, gửi số ⇒ đợt 2 mới chuyển
  screener/độ rộng/chart sang Wilder + SMA200 và hiệu chỉnh ngưỡng.
- Hằng ngưỡng RSI hai tầng trong `vnstock_brief_canon.py` (mạnh/yếu 60/40 · quá mua/quá bán 70/30), prompt + regime đọc chung.
- `compute_scores(df, index_returns=…)` trong brief sau công tắc `VNSTOCK_BRIEF_SECTOR_ALPHA` (mặc định tắt tới khi
  duyệt cùng đợt chạy lại lịch sử) — mở lại alpha vs VN-Index + xoay vòng ngành.
- Sửa comment sai `vnstock_brief.py:3342`.

## 15. Mốc nền P0 — kho thật (💻 laptop, 04/11, `run.py ta-score`)

Brief chiều: 463 dòng → 199 sau khử trùng → 167 được chấm (87 phiên, 28/04 → 02/11).

| Đo | Kết quả | Mốc | Đọc |
|---|---|---|---|
| T1 hỗ trợ VN-Index "chạm thì giữ" | 39% [27–53] n=51 | mức giả 46% | KHÔNG hơn ngẫu nhiên |
| T1 kháng cự VN-Index | 53% [39–67] n=47 | 38% | có thể hơn, mẫu nhỏ |
| T5 hỗ trợ / kháng cự từng mã | 33% / 38,5% | 35% / 35% | KHÔNG hơn ngẫu nhiên |
| T2 vượt R1 → chạm R2 (5 phiên) | 76,5% n=34 | 81% | KHÔNG có lợi thế |
| T2 thủng S1 → chạm S2 | 91% [76–97] n=33 | 69% [66–73] | **CÓ**: thủng hỗ trợ ⇒ đà giảm tiếp |
| T3 Stance T+1, nhãn model tự chọn (trước 3 khung) | 23% n=83 | trung tính 23,5% · lặp hôm qua 32% | thua mốc ngây thơ |
| T3 Stance T+1, từ 3 khung | 36% n=11 (11/11 phiên nhãn do code) | lặp hôm qua 45% | chưa đủ mẫu; nhãn KHÔNG còn là của model |
| T4 trung hạn TĂNG → T+20 | TB ≈ 0%, tăng 49,5% (5 đoạn) | mọi phiên +1,4% / 61% | nhãn TĂNG chưa có lợi thế (2024–2026) |
| T4 ngắn hạn "nhịp chỉnh" → T+20 (backfill 506 phiên) | +3,8%, tăng 80% (10 đoạn) | +1,5% / 62% | mua lúc chỉnh có lời — ít đoạn, MỘT giai đoạn |

Hệ quả cho P2:
1. S/R pivot 60 phiên không mang thông tin ⇒ P2 thay cách tìm S/R (số lần chạm, vùng KL, ATR) và **phải** thắng mốc ở T1/T5.
2. Thông điệp đáng tin duy nhất đo được: đóng cửa thủng S1 ⇒ nguy cơ về S2 cao (91% vs 69%) ⇒ thẻ kỹ thuật in rõ khi giá đã thủng hỗ trợ.
3. Chấm "model nào giỏi Stance" không còn ý nghĩa từ 14/10 (nhãn do code); đòn bẩy là luật code + dữ kiện thẻ, không phải đổi model.
4. Phát sinh đã sửa: cờ `stance_pinned` lây giữa agent (sửa `a5557da`, dữ liệu cũ không sửa ngược được); brief sáng nhãn "**Bias:**" không đọc được (`5bdaec7`).
