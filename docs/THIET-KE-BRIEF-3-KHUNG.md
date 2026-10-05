# Brief theo 3 khung thời gian: tiêu đề trung hạn đổi chậm, Stance không lật sang TĂNG khi xu hướng chưa TĂNG, lớp bảo vệ nhanh tách riêng

> **Trạng thái: ĐỀ XUẤT — chưa code** (05/10/2026). Dựng bằng workflow 23 agent: 5 người đọc code + 1 người dựng dữ liệu VNINDEX (Finhay) → replay bộ phân loại regime hiện tại → 3 bản thiết kế độc lập (đa khung / chống lật / neo vĩ mô) × 3 giám khảo (nhà đầu tư · kỹ thuật · định lượng; điểm 6.8 / 6.6 / 6.0) → tổng hợp → 2 phản biện → bản cuối. Nguyên nhân gốc §2 đã đối chiếu lại tay với `vnstock_regime.py:206-217` và `vnstock_brief.py:1327-1343`.
> Script nghiên cứu (`scratchpad/brief_design/...` nhắc trong bài) chỉ nằm ở sandbox, KHÔNG có trong repo — P0 viết lại gọn thành `scripts/replay_horizons.py` chạy trên kho thật.

> **Về số liệu.** Mọi số "replay" trong tài liệu được dựng lại từ dữ liệu Finhay: VNINDEX 2017–2026 và khối ngoại (NN) từ 10/2021, **có gồm giao dịch thỏa thuận**. Breadth và A/D là số ước lượng (proxy). Dữ liệu được chạy qua chính các hàm của repo (`classify_regime`, `compute_market_sentiment`, `_bias_floor_dir`).
> - Đây **không phải** bản ghi các brief đã gửi. P0 sẽ đối chiếu với `brief_memory.db` và `brief_push.json`.
> - Script chỉ đọc, nằm ngoài repo: `scratchpad/brief_design/{whipsaw/core.py, final/*.py, v3/*.py}`.
> - Chỉ soi được **một giai đoạn** (n=1), và tham số được chọn **sau khi** đã thấy giai đoạn đó. Vì vậy mọi kết quả chỉ là minh họa, không phải kiểm định.
> - (*) = số lấy từ Finhay hoặc từ snapshot doctor 05/10, chưa đối chiếu được trên registry của máy.

## 0. Tóm tắt

**Vì sao brief lật nhanh.** Hiện brief chỉ có một "công tắc ngày": điểm 7 phiếu, không có trí nhớ, trong đó 2 phiếu chỉ nhìn 1 phiên. Công tắc này quyết cùng lúc ba thứ:
- chữ "Risk-on/Risk-off" trên header;
- Stance ngày mai bị ép theo `_bias_floor_dir`;
- lời khuyên cho danh mục đang giữ.

Vì vậy chỉ một nhịp hồi 2–3 phiên là lật cả bản tin.

**Thiết kế mới** tách việc ra thành 3 khung thời gian (đúng như ý bạn), một kênh rủi ro riêng và một lớp bảo vệ:

| Thành phần | Trạng thái | Đổi khi nào | Được quyết việc gì |
|---|---|---|---|
| **Ngắn hạn** (vài phiên) | nhịp hồi / chưa rõ / nhịp chỉnh | Cuối mỗi phiên. Vào nhịp chỉnh ngay khi điểm ≤ −4/7. Vào nhịp hồi chỉ từ "chưa rõ". | Stance ngày mai, theo bảng §3.4 |
| **Trung hạn** (xu hướng tuần) | TĂNG / ĐI NGANG / GIẢM | Chốt tuần. Xuống cần 1 tuần, lên cần 2 tuần liền. | **Tiêu đề bản tin**, việc nên làm, lời khuyên danh mục |
| **Dài hạn** (6–12 tháng) | THUẬN / CÂN BẰNG / BẤT LỢI | Chấm tháng, đổi khi giữ 2 kỳ liền. Chỉ in khi đo được ≥3/5 trụ. | Khung diễn giải. Từ P3 được dịch tỷ trọng ±1 nấc. |
| **🚨 Rủi ro ngắn hạn** | tắt / mức 1 / mức 2 | Cuối phiên. Từ P2 có thêm bản sớm khoảng 15:10. | Nhắc rủi ro. Không bao giờ đổi xu hướng. |
| **Lớp bảo vệ** | bật / tắt | Bật ngay khi một trong bốn tín hiệu bật: floor cũ GIẢM, nhịp chỉnh, trung hạn GIẢM, 🚨 | Chặn mua bắt đáy vô điều kiện, cảnh báo lệnh MUA, chặn GIA TĂNG |

**Bạn sẽ thấy gì trên Telegram.** Header còn 2 dòng: "Trung hạn: X (từ ngày …) · Cổ phiếu Y% · Nên: …". Dòng 🚨 chỉ hiện khi trung hạn chưa GIẢM. Chữ "Risk-on/Risk-off" biến mất.

**Áp vào 15/08–30/09/2026 (replay):**
- Tiêu đề trung hạn giữ ĐI NGANG suốt giai đoạn, rồi chuyển GIẢM ngày 02/10.
- Stance bị code ép đổi **2 lần** (hệ hiện tại: 16 lần).
- **0 ngày TĂNG** và **0 lần đảo TĂNG↔GIẢM**, vì TĂNG bị cấm khi trung hạn chưa TĂNG. Hệ hiện tại có 11 ngày ép TĂNG và 6 lần đảo.
- Lớp bảo vệ bật ở mọi ngày mà hệ hiện tại bật, và còn bật thêm.

**Cái giá, nói thẳng:**
- Không kiếm thêm được gì từ nhịp +7.3%.
- Stance ngắn hạn chậm hơn: trung vị 12 phiên sau đỉnh của nhịp ≥10% (cũ: 8), và 19 phiên sau đáy (cũ: 10).
- Trung hạn trễ khoảng 61 phiên ở các khúc quay ≥15%. Ở cú giảm Q1-2026 (−16%), nó chỉ rời TĂNG khi chỉ số đã mất 13.4%.
- Lớp bảo vệ bật ~51% số phiên, so với 23% hiện nay.
- Kết luận ĐI NGANG suốt giai đoạn là sát nút: ngày 28/08 chỉ chênh 0.71 điểm.

**Ý "kết hợp vĩ mô" của bạn được đáp ở đâu, và khi nào:**
- **P1:** chỉ in số vĩ mô kèm chiều thay đổi. Chưa chấm điểm.
- **P2:** bảng vĩ mô được chấm điểm. Nhóm trung hạn cho ra "độ tin cậy" của xu hướng; nhóm dài hạn cho ra trạng thái Dài hạn.
- **P3:** vĩ mô và định giá mới được phép dịch tỷ trọng ±1 nấc.

**P1 không lật tỷ trọng mới, nhưng chặn con số cũ không được tăng ngược xu hướng.** Đây là kẹp band v1 ở §3.8 (cần bạn duyệt).

---

## 1. Vấn đề & bằng chứng

### 1.1 Bạn đã quan sát gì, và replay có khớp không
- **Bạn quan sát:** khoảng 27/08–giữa 09/2026, brief chuyển từ risk-off sang risk-on. Rồi thị trường chỉnh mạnh và brief quay lại risk-off ngay.
- **Replay code hiện tại cho ra đúng hình dạng đó:**
  - Header `⚖️ Regime` in "🔥 Bull — Risk-on" (score +4) từ 24/08, và "❄️ Bear — Risk-off" từ 24/09. Nhãn lấy từ `vnstock_regime.py:32-38`, hiển thị ở `vnstock_telegram.py:232-256`.
  - "Stance ngày mai" bị prompt ép theo điểm ngày (`vnstock_brief.py:3088-3123`).
  - Notes không lưu nhãn header đã gửi, nên P0 phải đối chiếu với brief thật.

### 1.2 Replay 15/08–30/09 (30 phiên)

| Chỉ số | Giá trị |
|---|---|
| Số lần đổi nhãn header 5 mức | **17** |
| Số lần floor đổi (Stance bị ép) | **16**: 11 ngày ép TĂNG, 11 ngày ép GIẢM |
| Số lần đảo TĂNG↔GIẢM trên nhãn bị ép | **6** |
| Biến động điểm trung bình | 2.0 điểm/phiên |

### 1.3 So với giá
- **Nhịp hồi 19/08 → 04/09:** +7.32% trong 9 phiên. Khối lượng mỏng: ~553 triệu cp/phiên, trong khi H1 là ~780 triệu.
- **Nhịp chỉnh 04/09 → 02/10:** −6.23% trong 20 phiên. Chỉnh chậm: phiên tệ nhất chỉ −1.86%.
- **Lúc nhãn bật:**
  - "Risk-on" bật ở 1,788.78, khi chỉ số đã +3.6% từ đáy.
  - "Risk-off" bật ở 1,775.09, khi chỉ số đã −4.2% từ đỉnh.
  - Ai làm theo đúng hai nhãn này thì lỗ −0.8% trên chỉ số.
- **Kết luận:** mỗi đầu trễ khoảng 4% trong một sóng chỉ khoảng 7%, nên không còn gì để làm. Đó là "xoay sở không kịp", đo bằng số.

### 1.4 Bằng chứng chậm trong suốt giai đoạn
- MA50 dốc xuống từ 13/07, và cắt xuống MA200 ngày 07/09.
- Đỉnh thấp dần: 1,927.94 (18/05) → 1,878.02 (24/06) → 1,853.08 (04/09).
- MA10 tuần nằm dưới MA40 tuần từ 28/08, chênh chỉ 0.71 điểm.
- Độ rộng chỉ 9–18% số mã trên MA200.
- **Khối ngoại (Finhay, có thỏa thuận):**
  - Tổng 20 phiên âm gần như suốt giai đoạn, sâu nhất −6,979 tỷ (18/08), nhưng có lúc dương +184 tỷ (22/09).
  - Tổng 60 phiên lại đang **bớt bán**: từ ~−52 nghìn tỷ đầu tháng 7 xuống ~−17 nghìn tỷ đầu tháng 10.
  - Bức tranh dòng tiền vì vậy không một chiều như bản nháp trước đã viết.

### 1.5 Năm 2026 không phải ngoại lệ (2017-12 → 2026-10)
- **Nhãn header 5 mức:** đổi **112 lần/năm**; một trạng thái kéo dài trung vị **1 phiên**.
- **Floor gồm regime ±3 và momentum ±50:** đổi 88.4 lần/năm, đảo 16.7 lần/năm.
- **Riêng phần regime của floor:** đổi 68.8 lần/năm, đảo 9.0 lần/năm. 84% số lần đổi bị đảo ngược trong vòng 10 phiên.

### 1.6 Làm mượt cùng đầu vào không cứu được
Đã thử 9 cấu hình hysteresis và 6 cấu hình N-of-M/dwell. **Tất cả** vẫn bật ON trong khoảng 24/08–04/09, rồi tắt về cuối tháng 9. Không có một quy tắc nào vừa sớm vừa ổn định. Vì vậy phải tách tầng, không thể chỉ chỉnh ngưỡng.

### 1.7 Con số tỷ trọng cũng đã nhảy
Theo notes, band hiệu lực quanh 29/09–05/10 đi như sau:
- **~29/09–04/10:** B4 (15% cổ phiếu) = band dữ liệu B3 + tilt đủ 1 band từ báo cáo 10/07, theo luật cũ (`docs/CLAUDE-NOTES.md:7965`).
- **05/10 00:10:** về B3 trộn 10% sang B4, tức cổ phiếu ~28–29%. Nguyên nhân là luật phai theo tuổi mới.
- **Tối 05/10 (dự kiến):** lại B4 15% khi báo cáo Q4 được nạp (`:7174-7179`).

Tức là 15 → ~28 → 15% trong vài ngày, không do thị trường. Lịch sử band tháng 8–9 chưa đọc được trong sandbox (P0: `python vnstock_allocation.py --history 120`). Bản nháp trước viết "band không phải nguồn nỗi đau" — câu đó **sai** và đã bỏ.

---

## 2. Nguyên nhân gốc (trong code)

1. **Điểm 7 phiếu không có trạng thái.**
   - `classify_regime` (`vnstock_regime.py:100-234`) cộng 7 phiếu ±1. Điểm ≥4 in "Bull — Risk-on", ≤−4 in "Bear — Risk-off" (`:206-215`).
   - A/D 1 ngày và NN 1 ngày là 2 phiếu chỉ nhìn 1 phiên. Ngưỡng NN là ±100 tỷ, trong khi NN thực tế cỡ nghìn tỷ.
   - `load_regime` tính lại từ đầu mỗi lần gọi (`:237-242`). Nó gọi `_load_nn_net_1d()` **không truyền ngày** (`:241`), dù hàm nhận được `effective_date` (`:78`). Lượt chạy bù vì vậy có thể lệch giữa header và thân bài.
2. **Bias floor không có trí nhớ và đếm trùng.**
   - `_bias_floor_dir` (`vnstock_brief.py:1327-1343`) trả TĂNG/GIẢM ngay khi regime ±3 **hoặc** momentum ±50. Hàm được gọi ở `collect_context` (`:2628-2639`).
   - Prompt ghi "Bias BẮT BUỘC … TUYỆT ĐỐI KHÔNG ghi Trung tính" (`:3088-3123`).
   - Momentum dùng chung 6/7 đầu vào với regime.
   - Không có guard nào ghim nhãn Stance; chỉ có prompt.
3. **Lớp bảo vệ dính chặt vào floor ngày.** Ba chỗ chỉ chạy khi `bias_floor.dir == "GIẢM"`:
   - viết lại "MUA vùng" thành dạng có điều kiện (`vnstock_brief_guards_sections.py:470`);
   - `enforce_buy_vs_bias_caveat` (`:1411`);
   - `_market_is_bearish` → caveat lệnh MUA trên Telegram (`vnstock_telegram.py:399-421`).

   Floor tắt (vd điểm −2, momentum −40) thì bảo vệ tắt theo, kể cả khi xu hướng dài đang xấu.
4. **Tín hiệu ngày lan sang mọi phần khác.**
   - Lời khuyên danh mục "gắn với Stance/regime": template `:360`, `_portfolio_block` `:1958-1968`.
   - Chiều watchlist `:332`.
   - Brief sáng: TLDR Bias / Hành động ưu tiên `:218-221`, danh mục `:272`.
   - `_ALLOC_HORIZON_CAVEAT` (`guards_sections.py:237-242`) dặn "tôn trọng tín hiệu ngày khi vào/ra lệnh".
5. **Band "tháng" thực chất là band ngày được xác nhận 2 lần.**
   - Bước `allocation` chạy mỗi đêm (`run.py:1581`).
   - 60% trọng số là tín hiệu ngày (`vnstock_allocation.py:91-99`).
   - Hysteresis chỉ là lề 0.05 × 2 phiên (`:114-119`, `:211-251`). Ứng viên có thể cách 2 bậc.
   - Tilt báo cáo được áp sau hysteresis và **phai theo lịch** (`:457-495`; decay 30→90 ngày ở `vnstock_report_digest.py:60-61`). % cổ phiếu vì vậy trôi lên dù thị trường không đổi.
   - Pending không vào history (`:529-544`).
   - Nút "Tính lại band" (`dashboard/allocation_tab.py:70-73`): recompute cùng `as_of` đã được khử trùng (`:243-245`). Lỗ thật hẹp hơn: bấm **giữa phiên** sang ngày mới có thể ghi ngày đó bằng input trong phiên, vì `as_of` lấy theo `data_date` của overview (`:316-321`).
6. **Vĩ mô vào brief dưới dạng thay đổi 1 kỳ, dùng để chốt Bias ngày** (`vnstock_brief_canon.py:166-176`). Không có góc nhìn chậm nào.
7. **Không có thông báo đổi trạng thái.** Brief không có "từ ngày nào", không có "đã N phiên", không có mức để đổi lại. Mọi mức S/R đều bị chặn trong ±7% (`_SR_MAX_MOVE_PCT`, canon `:83`).
8. **Thước đo khuyến khích phản ứng theo hôm qua.** Stance chỉ được chấm ở T+1 (`vnstock_stance_track.py:27`, `:55-82`).

---

## 3. Thiết kế

### 3.1 Nguyên tắc
- **Mỗi tầng một việc, một bộ đầu vào và một nhịp đánh giá.** Tầng chậm không nhận đầu vào 1 phiên. Tầng nhanh không lật tầng chậm.
- **Bất đối xứng, nói đúng chỗ.**
  - Lớp bảo vệ là phần **nhanh**: bật trung vị 3 phiên sau đỉnh của các nhịp giảm ≥10%.
  - Stance GIẢM và tiêu đề trung hạn là phần **chậm**.
  - Chiều tăng rủi ro (Stance TĂNG, tăng tỷ trọng) luôn cần trung hạn đồng ý và có báo trước.
  - Chiều giảm rủi ro không bao giờ bị cấm.
- **Từ vựng riêng cho từng tầng**, và header chỉ mang 1 trạng thái:
  - Ngắn hạn: nhịp hồi / chưa rõ / nhịp chỉnh.
  - Trung hạn: TĂNG / ĐI NGANG / GIẢM.
  - Dài hạn: THUẬN / CÂN BẰNG / BẤT LỢI. Không dùng "TRUNG TÍNH" để khỏi trùng với Stance.
  - Điểm 7 phiếu chỉ còn được gọi là "điểm kỹ thuật ngày ±N/7".
- **Code tính, agent kể, guard ghim** (theo CLAUDE.md). Agent chỉ được thêm ≤1 câu ở 2 dòng.
- **Một con số tỷ trọng duy nhất trong brief** cho tới P3.
- **Không bịa mức giá.** Mọi mức là nghiệm của luật đã in. Mức nào không phải mức "đã biết" của guard thì in làm tròn "~1,803".

### 3.2 Bảng tầng

| Tầng | Câu hỏi | Đầu vào | Nhịp | Quyết định | Không được làm |
|---|---|---|---|---|---|
| Ngắn hạn | "Mấy phiên tới nghiêng chiều nào?" | Điểm 7 phiếu S, số phiếu n | Cuối phiên | Stance (§3.4) | Đổi tỷ trọng; dùng chữ "xu hướng" hay "risk-on" |
| Trung hạn | "Thị trường đang tăng, đi ngang hay giảm?" | Đóng tuần, MA10 tuần, MA40 tuần | Chốt tuần | Tiêu đề; việc nên làm; danh mục; tỷ trọng gốc (P3) | Nhận đầu vào 1 phiên ngoài giá đóng tuần |
| Bảng vĩ mô — nhóm T | "Vĩ mô–dòng tiền có ủng hộ xu hướng không?" | 6 trụ (§3.6) | Chốt tuần, giữ nhãn 2 tuần | Độ tin cậy CAO/TRUNG BÌNH/THẤP | Lật hay chặn trung hạn (chưa backtest) |
| Dài hạn = nhóm D | "Khung năm thuận hay bất lợi?" | 5 trụ phi giá (§3.6) | Tháng, 2 kỳ | Khung diễn giải; ±1 nấc từ P3 | Đóng vai tín hiệu thời điểm |
| 🚨 Rủi ro ngắn hạn | "Có đang rơi nhanh không?" | Sụt từ đỉnh 20 phiên, sốc 1 và 3 phiên | Cuối phiên (+15:10 từ P2) | Nhắc rủi ro; ⏳ đổi tỷ trọng chỉ từ P3 | Đổi xu hướng; viết "Risk-off" hay "bán" |
| Lớp bảo vệ | "Có nên chặn mua bắt đáy không?" | Bốn tín hiệu ở §3.4 | Cuối phiên | Ba guard bảo vệ; chặn GIA TĂNG vô điều kiện; brief sáng không BUY | Đổi nhãn Stance |

### 3.3 Ngắn hạn: máy trạng thái trên điểm 7 phiếu hiện có
- **Đầu vào:** `S` và `n` từ `classify_regime`, giữ nguyên để điểm vẫn so được với lịch sử. Ngưỡng `thr = ceil(4·n/7)`: n=6 hoặc 7 → 4, n=5 → 3.
- **Luật chuyển:**

  | Từ | Sang | Điều kiện |
  |---|---|---|
  | chưa rõ | nhịp hồi | `S ≥ +thr` |
  | chưa rõ **hoặc nhịp hồi** | nhịp chỉnh | `S ≤ −thr` (giảm rủi ro được nhảy thẳng) |
  | nhịp hồi | chưa rõ | `S ≤ 0` |
  | nhịp chỉnh | chưa rõ | `S ≥ 0` |
  | nhịp chỉnh | nhịp hồi | **không bao giờ trực tiếp**; phải qua chưa rõ |

- **Replay 2017-12 → 2026-10:**
  - 27.1 lần đổi/năm và 6.7 vòng hồi↔chỉnh/năm. Cú nhảy thẳng hồi→chỉnh chỉ xảy ra 1 lần trong 8.8 năm.
  - Giai đoạn 15/08–30/09: 6 lần đổi.
  - So với floor cũ: 88.4 lần đổi/năm.
- **Trễ** (đo lại cho đúng luật này, bỏ số "+2.8 phiên" mượn từ bản nghiên cứu): sau đỉnh nhịp ≥10% trung vị **12 phiên** (floor cũ: 8); sau đáy **19 phiên** (cũ: 10). Có 3/32 khúc quay bị bỏ lỡ hẳn.
- **Ngưỡng "hết nhịp chỉnh":** brief in "khi điểm kỹ thuật ngày về ≥ 0 (hiện −6/7)". **Không in mức giá**, vì điểm gồm cả phiếu breadth/NN, code không giải ra được một mức.

### 3.4 Stance ngày mai và lớp bảo vệ

**Bảng Stance** (code tính; guard `enforce_stance_horizon` ghim):

| Ngắn \ Trung | TĂNG | ĐI NGANG | GIẢM |
|---|---|---|---|
| **nhịp hồi** | **Ép TĂNG** nếu 🚨 tắt. Nếu 🚨 bật: không ép, cho phép {TĂNG, TRUNG TÍNH, GIẢM} | Không ép. Cho phép {TRUNG TÍNH, GIẢM}, mặc định TRUNG TÍNH ("nhịp hồi trong xu hướng đi ngang") | Như ĐI NGANG |
| **chưa rõ** | Không ép. Cho phép {TĂNG (chỉ khi 🚨 tắt), TRUNG TÍNH, GIẢM} | Không ép. Cho phép {TRUNG TÍNH, GIẢM} | Không ép. Cho phép {TRUNG TÍNH, GIẢM} |
| **nhịp chỉnh** | **Ép GIẢM** | **Ép GIẢM** | **Ép GIẢM** |

Tóm lại trong một câu:
- TĂNG chỉ được phép khi trung hạn TĂNG và 🚨 tắt.
- TĂNG chỉ bị ép khi có thêm điều kiện nhịp hồi.
- GIẢM không bao giờ bị cấm.
- GIẢM bị ép khi ngắn hạn là nhịp chỉnh.
- Momentum ±50 rời khỏi luật ép Stance (cần bạn duyệt). Nó vẫn đi vào lớp bảo vệ và vẫn có cảnh báo mềm `enforce_stance_sentiment_caution` (`guards_sections.py:1452-1496`).

**Hợp đồng `ctx`:**
- `ctx["bias_floor"] = {dir, source:"nhip", since, n}` **chỉ có** ở 2 ô bị ép. Prompt `:3088-3123` viết lại thành "Ngắn hạn: nhịp chỉnh phiên N (điểm −6/7)".
- `ctx["horizons"]["stance_allowed"]` cho các ô còn lại. Guard thay nhãn ngoài tập bằng TRUNG TÍNH và giữ nguyên setup có điều kiện.

**Phương án B** (bạn chọn ở §8): ô nhịp hồi × ĐI NGANG vẫn cho TĂNG (không ép). Khi đó Stance có thể quay lại TĂNG trong 26/08–04/09 và 15–18/09 nếu agent chọn TĂNG, tức tái tạo vòng TĂNG→GIẢM mà bạn phàn nàn.

**Lớp bảo vệ** `ctx["defensive"] = {on, reasons}` bật khi có **bất kỳ** điều kiện nào:
- (a) floor cũ ra GIẢM (giữ nguyên `_bias_floor_dir`: điểm ≤ −3 hoặc momentum ≤ −50);
- (b) nhịp chỉnh;
- (c) trung hạn GIẢM;
- (d) 🚨 bật.

Đây là **tập cha của hiện nay**, nên không ngày nào mất bảo vệ (có property test).

Các chỗ dùng lớp bảo vệ:
- guard `:470` và `:1411`, đọc qua helper `is_defensive(ctx)` trong `_guards_common`;
- `_market_is_bearish`;
- prompt danh mục: không GIA TĂNG vô điều kiện, hạ trước mã dưới MA50;
- brief sáng: "Hành động ưu tiên" không được BUY vô điều kiện;
- điều kiện caveat band (`guards_sections.py:310-321`): lệch khi B0/B1 mà bảo vệ đang bật, hoặc B3/B4 mà Stance TĂNG.

**Replay:**

| Chỉ số | Cũ | Mới |
|---|---|---|
| Nhãn Stance bị code quyết đổi, giai đoạn 15/08–30/09 | 16 lần | **2 lần** (GIẢM → không ép ngày 24/08; → GIẢM ngày 24/09) |
| Ngày TĂNG trong giai đoạn | 11 | **0** |
| Đảo TĂNG↔GIẢM trong giai đoạn | 6 | **0** |
| Đổi nhãn bị quyết, toàn mẫu | 88.4/năm | 23.4/năm |
| Đảo TĂNG↔GIẢM, toàn mẫu | 16.7/năm | 4.2/năm (chỉ xảy ra bên trong trung hạn TĂNG) |
| TĂNG được phép | — | 40% số phiên |
| Lớp bảo vệ bật | 22.8% số phiên | 51.2% (nhịp chỉnh thêm 5.3; trung hạn GIẢM thêm 15.0; 🚨 thêm 8.0) |
| Bảo vệ bật sau đỉnh nhịp ≥10% | — | trung vị 3 phiên |

Phản biện từng nêu 22 phiên sập mà Stance GIẢM bị cấm (vd 20/10/2025 −5.47%, điểm −3/6). Với luật mới, cả 22 phiên **đều được phép GIẢM và đều có bảo vệ**, vì 21/22 phiên có 🚨 bật.

**Ngày "chưa rõ" vẫn có thể đổi qua lại giữa TRUNG TÍNH và GIẢM** do agent chọn. Đó không phải đảo chiều TĂNG↔GIẢM, nhưng phải nói trước với bạn.

### 3.5 Trung hạn (xu hướng tuần): tiêu đề mới

**Đọc tuần `R`** tại bar cuối của tuần ISO:
- **TĂNG** nếu đóng tuần > 1.02 × MA40 tuần **và** MA10 tuần > MA40 tuần.
- **GIẢM** nếu đóng tuần < 0.98 × MA40 tuần **và** MA10 tuần < MA40 tuần.
- Còn lại là **ĐI NGANG**.

**Luật chuyển:** mỗi tuần tối đa 1 bậc, không có TĂNG↔GIẢM trực tiếp.

| Bước | Chiều | Điều kiện |
|---|---|---|
| ĐI NGANG → GIẢM | giảm rủi ro | 1 lần đọc GIẢM |
| TĂNG → ĐI NGANG | giảm rủi ro | 1 lần đóng tuần < MA40 tuần **hoặc** MA10 tuần < MA40 tuần |
| ĐI NGANG → TĂNG | tăng rủi ro | 2 tuần liền đọc TĂNG |
| GIẢM → ĐI NGANG | tăng rủi ro | 2 tuần liền đóng > MA40 tuần **hoặc** MA10 tuần > MA40 tuần |

**Tên gọi trung thực.** Tầng này dựa trên MA10 tuần (~2.5 tháng) và MA40 tuần (~9 tháng). Nó đổi 3.2 lần/năm, nên mỗi trạng thái kéo dài ~3–4 tháng. Trễ trung vị **61 phiên** sau đỉnh và 63 phiên sau đáy của các khúc quay ≥15%; **3/6 đỉnh lớn chưa bao giờ xuống GIẢM** trước khúc quay kế tiếp. Vì vậy gọi là "Trung hạn (xu hướng tuần)", không gọi "1–3 tháng". Đây là nhãn biên/xu hướng, **không phải tín hiệu thời điểm**.

**Replay** (`final/medvar.py`):

| Quy tắc | Lần đổi/năm | Bị đảo ngược trong ≤4 tuần |
|---|---|---|
| Bất đối xứng, chưa có hysteresis | 4.3 | 14/38 |
| **Bất đối xứng + hysteresis** | **3.2** | **3/28** |

Hysteresis không đổi ngày bước xuống ở 5 cú sập 2018 / 2020 / 04-2022 / 04-2025 / Q1-2026. Nhưng ở 07/2026 nó **dời bước xuống từ 17/07 (1,787.45) sang 24/07 (1,686.11)**, tức sau đáy 22/07. Đây là giá phải trả.

**Bộ giải mức kích hoạt — đủ cả 2 ràng buộc.** Gọi S39 là tổng 39 đóng tuần trước, S9 là tổng 9 đóng tuần trước, X là đóng tuần này. Khi đó MA40w = (S39+X)/40 và MA10w = (S9+X)/10.
- Ràng buộc giá: X < 0.98·S39/39.02 · X > 1.02·S39/38.98 · X > S39/39.
- Ràng buộc cắt MA: MA10w < MA40w ⇔ X < C, và MA10w > MA40w ⇔ X > C, với **C = (S39 − 4·S9)/3**.
- **Mức in ra:**
  - Xuống GIẢM: X < **min**(0.98·S39/39.02, C).
  - Lên TĂNG (lần đọc 1/2): X > **max**(1.02·S39/38.98, C).
  - Rời TĂNG: X < **max**(S39/39, C).
  - Rời GIẢM (lần đọc 1/2): X > **min**(S39/39, C).
  - Nếu mức vượt đỉnh 52 tuần hoặc cách giá > 8%, in "chưa thể trong tuần này".

Các mức này tính được từ thứ Hai, cho đúng tuần đó:

| Tuần kết thúc | Đóng tuần | Xuống GIẢM nếu < | Lên TĂNG nếu > (ràng buộc thắng) |
|---|---|---|---|
| 21/08 | 1,768.12 | ~1,722 (cắt MA) | ~1,820 (giá) |
| 28/08 | 1,832.12 | ~1,750 (giá) | **~1,842 (cắt MA)** — bản trước in sai ~1,823 |
| 04/09 | 1,853.08 | ~1,754 | ~1,954 → "chưa thể trong tuần này" |
| 11/09 → 25/09 | — | ~1,758 → ~1,764 | ~2,020 → ~2,100 (chưa thể) |
| 02/10 | 1,737.71 | ~1,766 → **đã chuyển GIẢM** | — |
| Tuần tới 09/10 | — | — | **Rời GIẢM nếu đóng > ~1,803** (giá thắng; cắt MA cần ~1,995) |

- **Đọc tạm giữa tuần:** cùng luật, tính trên giá đóng hôm nay. In dạng "nếu thứ Sáu đóng < ~X → GIẢM". Không bao giờ ghi thành trạng thái.
- **Độ báo trước, đo trung thực** (`final/lead.py`):
  - Mức tĩnh luôn được in, nhưng nó **không phải** lời báo trước nhiều tuần.
  - Cảnh báo tạm tính liên tục trước ngày chốt: trung vị **1 phiên**; 7/15 lần giảm rủi ro có **0 phiên**.
  - Ở giai đoạn này, tạm tính chạm mức đúng từ 01/10, tức 1 phiên trước khi chốt.
  - Bước tăng rủi ro **luôn** có "⏳ 1/2" báo trước ít nhất 1 tuần.
- **Chốt tuần không cần lịch nghỉ** (repo không có):
  - Tuần W được chốt ở lần chạy cuối ngày mà bar cuối của VNINDEX là thứ Sáu, **hoặc** ở lần chạy đầu tiên thấy bar thuộc tuần ISO sau.
  - MA10w/MA40w chỉ đếm những tuần **có bar**, nên tuần Tết rỗng thì bỏ qua và tuần ngắn vẫn tính.
  - Thứ Sáu nghỉ thì brief ghi "chốt tuần (bar cuối dd/mm)".
- **Chỉ số vốn hóa so với cổ phiếu trung vị.** VNINDEX bị vài mã lớn kéo, trong khi chỉ 9–18% số mã nằm trên MA200. Dòng trung hạn vì vậy luôn in kèm "x% mã trên MA200 (4 tuần trước y%)". P2 thêm đọc tuần của "cổ phiếu trung vị", chỉ hiển thị.
- **Khi tiêu đề có vẻ sai lúc đang sập:** nếu 🚨 bật hoặc giá đã sụt ≥8% từ đỉnh 60 phiên mà trung hạn vẫn TĂNG, dòng tiêu đề thêm "· đang điều chỉnh −X% từ đỉnh".

### 3.6 Bảng vĩ mô: một bảng, mỗi trụ thuộc đúng một tầng

**Chung cho cả hai nhóm:**
- Chỉ dùng dữ liệu trong repo; P2 bổ sung lịch sử qua kho chậm `_meta/macro_slow.json`.
- Trụ thiếu số thì in "chưa đo", không tính 0 ngầm.
- Ngưỡng mặc định dưới đây được **hiệu chỉnh theo phân vị ở P0**. Bản nháp trước dùng ngưỡng cố định, nên khối ngoại 60 phiên ≤ −5,000 tỷ bị tính bất lợi ở 99% (2024), 91% (2025) và 100% (2026) số ngày, thành một hằng số.

**Nhóm T — gắn vào trung hạn.** Chấm lúc chốt tuần. Nhãn chỉ đổi khi giữ 2 tuần liền, nên không thể lật hằng ngày.

| Trụ | Nguồn | Bất lợi / Thuận (mặc định) | Đọc 02/10 |
|---|---|---|---|
| T1 Khối ngoại 60 phiên | `foreign_net_daily.json` (khớp lệnh; repo có từ ~06/2026); hàm mới `load_market_net_window(n, effective_date)` cạnh `vnstock_foreign_flow.py:158-175` | Phân vị trong cửa sổ dài nhất có (mục tiêu 500 phiên): ≤P20 bất lợi, ≥P80 thuận. Dưới 250 phiên thì "chưa đo" | Repo: chưa đủ lịch sử → chưa đo. Finhay (*): −17,077 tỷ, phân vị 73, bớt bán ~34.7 nghìn tỷ so với 60 phiên trước → trung tính |
| T2 Độ rộng | % mã trên MA200 (overview; lưu hằng ngày vào `horizon_state`) | < 30% và 4 tuần không tăng ≥5 điểm → bất lợi. > 55% hoặc tăng ≥10 điểm → thuận | 9% (giữa 08 ~11%) → bất lợi |
| T3 Sản xuất | registry `pmi` | TB 3 tháng < 50 → bất lợi. ≥ 51 và tháng mới không giảm ≥1 điểm → thuận | TB 52.7, tháng 9 −1.4 (*) → trung tính |
| T4 Thanh khoản | registry `interbank_1w` − `sbv_policy_rate`, TB 20 lần đọc (không dùng ON vì lệch kỳ hạn, cf. `_TENOR_DIVERGENCE_PP`, `vnstock_macro.py:1014`) | > +1.0 điểm % → bất lợi. < −1.0 → thuận | chưa tính |
| T5 Chênh lệch quốc tế | gauge `intl` VN10Y−US10Y (`vnstock_macro.py:1114-1135`), thay đổi 3 tháng | giảm ≥0.25 điểm → bất lợi; tăng ≥0.25 → thuận; mức chỉ in kèm | mức −0.79; chiều chưa đo |
| T6 Tỷ giá | registry `usdvnd`, thay đổi 3 tháng | USD/VND ≥ +1.5% → bất lợi; ≤ −0.5% → thuận | Finhay (*) −1.1% (05/08→02/10) → thuận |

- **Nhãn độ tin cậy** (chỉ xét trụ đo được):
  - **CAO:** ≥3 trụ cùng chiều trung hạn và ≤1 trụ ngược chiều.
  - **THẤP:** số trụ ngược chiều nhiều hơn số trụ cùng chiều.
  - **TRUNG BÌNH:** còn lại.
  - **Chưa đủ dữ liệu:** dưới 3 trụ đo được.
  - Khi trung hạn ĐI NGANG thì in "nghiêng thuận/bất lợi k/m" thay cho độ tin cậy.
- **Hôm nay (minh họa):** bất lợi 1 (độ rộng), thuận 1 (tỷ giá*), trung tính 2, chưa đo 2 ⇒ **TRUNG BÌNH**. Bản nháp trước ra "4/6 bất lợi, CAO" chủ yếu do ngưỡng cố định.
- **Nhóm T không lật và không chặn trung hạn.** Khối ngoại đã bán ròng xuyên suốt nhịp tăng 2025; muốn dùng làm cổng thì phải backtest trước (P4).

**Nhóm D = Dài hạn (6–12 tháng), toàn trụ phi giá.** Bỏ trụ "xu hướng năm" của bản trước, vì độ dốc MA200 tương quan với MA10w/MA40w và gây đếm trùng.
- Chấm ở lần chạy đầu tiên từ ngày 7 mỗi tháng. Đổi trạng thái cần 2 kỳ liền.
- Một báo cáo mới tải lên chỉ đổi điểm hiển thị, không xác nhận lần đổi.

| Trụ | Nguồn | Chấm | Đọc 02/10 |
|---|---|---|---|
| D1 Tăng trưởng | registry `gdp_yoy`, `iip_yoy` | GDP quý mới − quý trước ≥ +0.3 điểm % → +1; ≤ −0.3 → −1 (IIP 3 tháng làm dự phòng) | +1 (Q3 9.95% vs Q2 8.39%*) |
| D2 Lạm phát & dư địa chính sách | registry `cpi_yoy` | CPI YoY tăng ≥0.5 điểm % trong 6 tháng → −1; giảm ≥0.5 → +1 | chiều đang tăng (áp lực vĩ mô doctor 05/10); độ lớn 6 tháng chưa đo (registry ≤60 lần đọc, `vnstock_macro.py:63`) |
| D3 Chu kỳ lãi suất | `sbv_policy_rate`, `fed_funds`; P2 thêm FRED `observation_start` (hiện chỉ lấy `limit: 10` bản mới nhất, `vnstock_fred.py:66-75`) | Lần đổi gần nhất trong 12 tháng: cắt +1, nâng −1, hai NHTW trái chiều 0 | chưa đo trong repo (Finhay*: lãi suất Mỹ 3.75% → 4.00% tháng 09/2026) |
| D4 Định giá | P3 `vnstock_valuation.py` | P/E vốn hóa (Σvốn hóa/ΣLN, xử lý EPS âm, biến thể bỏ VIC); lợi suất lợi nhuận − VN10Y | chưa đo |
| D5 Báo cáo | `consensus()` (`vnstock_report_digest.py:719-765`) | **+1** nếu stance cổ phiếu ≥ +1.0 và strength ≥ 0.5; **−1** nếu ≤ −1.0 và strength ≥ 0.5; **còn lại 0**. Giữ dấu tới khi có báo cáo mới hoặc quá 90 ngày | −1 (HedgeAcademy Q4, 04/10) |

- **Trạng thái** (chỉ khi ≥3/5 trụ đo được): tổng ≥ +2 → THUẬN; ≤ −2 → BẤT LỢI; còn lại → CÂN BẰNG (in "nghiêng …" khi tổng là ±1).
- **Hôm nay:** "chưa đủ dữ liệu (2/5: tăng trưởng thuận, báo cáo bất lợi)". Nói thẳng: tầng dài hạn chỉ có ý nghĩa sau khi P2 lấp đủ lịch sử và P3 có định giá.
- **Catalyst** (FOMC/NHNN, ngày công bố CPI/GDP, mùa BCTC, kỳ review rổ): **không tìm thấy nguồn lịch trong repo**. Để P4, hoặc dùng bảng nhập tay.
- `macro_pressure_score` (`vnstock_macro.py:1173-1211`) vẫn chỉ đi vào momentum, tức ngữ cảnh ngắn hạn. Chỉ thị canon `:166-176` viết lại thành: "thay đổi 1 kỳ = bối cảnh ngắn hạn; xu hướng vĩ mô xem bảng 🔭".

### 3.7 🚨 Cảnh báo rủi ro ngắn hạn
Biểu tượng đổi từ ⚡ sang 🚨, vì ⚡ đang là mục "## ⚡ Biến động bất thường" của brief sáng (`vnstock_brief.py:246`) và nằm trong `_SECTION_EMOJIS` (`vnstock_brief_guards_common.py:39`).

- **Bật mức 1** khi có một trong ba điều kiện: đóng cửa ≤ 95% đỉnh đóng cửa 20 phiên; một phiên ≤ −2.5%; ba phiên cộng lại ≤ −4%.
- **Neo:** lấy đỉnh 20 phiên tại lúc bật. Cảnh báo không tự tắt khi đỉnh trôi ra khỏi cửa sổ.
- **Mức 2:** đóng cửa ≤ 0.90 × neo, hoặc thêm một phiên ≤ −2.5% sau ngày bật. In là "~1,668 (90% đỉnh neo)". Mức này **trùng với đáy 22/07 chỉ là tình cờ**, nên không gắn nhãn "đáy".
- **Tắt:** sau ≥5 phiên, khi đóng cửa ≥ 97% neo **hoặc** 3 phiên liền đóng trên MA20.
- **Replay:**

  | Chỉ số | Giá trị |
  |---|---|
  | Số lần bật | 5.3/năm |
  | Thời gian ở trạng thái bật | 31.2% số phiên (mức 2: 16.9%) |
  | Độ dài một đợt bật | trung vị 12 phiên, p90 ~31, max 60 |
  | P(giảm thêm ≥3% trong 20 phiên) | 51% (n=47), so với nền 40% |
  | Lợi suất trung vị 20 phiên sau khi bật | **+1.7%**, so với trung vị không điều kiện +1.1% |
  | Bật sau đỉnh nhịp ≥10% | trung vị 6 phiên |

- **Diễn giải đúng:** 🚨 có lợi thế về **rủi ro**, không có lợi thế về **chiều**.
  - Ngôn từ: "không mua thêm; nếu đang vượt tỷ trọng thì hạ phần vượt; không bán tháo phần lõi".
  - **Bỏ lời khuyên "siết stop"**: sau cú −5% trong vùng biến động cao mà trung vị 20 phiên vẫn dương, siết stop dễ bị văng ra trước nhịp hồi.
- **Chống mỏi cảnh báo:**
  - Header chỉ hiện 🚨 khi trung hạn **chưa** GIẢM (18.1% số phiên; 3.9 lần bật/năm). Khi trung hạn đã GIẢM thì 🚨 chỉ là 1 dòng trong 🔭.
  - Tin riêng (P2) chỉ gửi khi bật, khi lên mức và khi tắt, và cũng chỉ khi trung hạn chưa GIẢM.
- **Độ trễ giao hàng.** Bản tối ra cùng brief, khoảng 21:00–23:15, có khi qua nửa đêm. Vì vậy 🚨 tối **không nhanh hơn brief**.
  - **P2** thêm bản sớm trong task `VnStock News Alert` đang chạy mỗi giờ ở 🖥️ desktop. Lượt đầu sau 15:05 ngày giao dịch lấy bar VNINDEX qua `vnstock_updater._fetch_prices` (`vnstock_updater.py:284`), chỉ đọc, không ghi kho.
  - Bản này tính 🚨 và đọc tạm thứ Sáu, rồi gửi nếu có sự kiện mới (khử trùng với bản tối). P2 phải xác minh hàm đó trả được bar chỉ số trong ngày.
  - Cảnh báo trong phiên (11:xx / 14:xx) để P4.

### 3.8 Tỷ trọng: một con số, và con số đó không được tăng ngược xu hướng

**P1 — band v1 giữ nguyên tham số đã chốt, cộng (nếu bạn duyệt) một kẹp và 3 vá cơ học:**
- **Kẹp `VNSTOCK_ALLOC_HORIZON_CAP`:** trong `run_allocation`, sau `apply_tilt`, nếu trung hạn GIẢM hoặc 🚨 bật mà % cổ phiếu mới **cao hơn** % hiệu lực hôm trước, thì giữ nguyên cả bảng % và band hiệu lực cũ.
  - Ghi `capped_by:"horizons"` kèm band/% đề xuất.
  - Kẹp chặn cả phần trôi do tilt phai theo lịch. Ví dụ: cú 15 → ~28% lúc 05/10 00:10 sẽ bị chặn, vì trung hạn đã GIẢM từ 02/10.
  - Hết kẹp thì tăng tối đa 1 bậc/tuần (~15 điểm %), có "⏳" báo trước 1 tuần.
  - Bước allocation chạy **sau** bước horizons (§3.10), nên cùng đêm đã đọc được trạng thái.
- **Vá 1:** mỗi lần đổi tối đa 1 bậc (`apply_hysteresis`, `vnstock_allocation.py:211-251`).
- **Vá 2:** nút dashboard (`allocation_tab.py:70-73`) không ghi ngày mới khi overview là giữa phiên (`reason=intraday`). Khi đó chỉ tính và hiện.
- **Vá 3:** ghi `pending` vào `_history_entry` (`:529-544`).
- **Hiển thị:**
  - Brief in "💼 Cổ phiếu Y% (band Bx)". Khi kẹp đang giữ thì in thêm "band dữ liệu đề xuất Z% — giữ Y% vì trung hạn GIẢM".
  - `raw_band`/`pending` **chỉ hiện ở dashboard**, không vào brief. Đó là điểm tổng hợp ngày nhiều nhiễu; in ra như "báo trước" là sai.

**P2 — band v2 chạy bóng** (dashboard/CLI, nhãn "thử nghiệm", **không vào brief**):
- Tỷ trọng gốc theo trung hạn, dùng bảng % bạn đã duyệt (`:80-86`): TĂNG 60% · ĐI NGANG 45% · GIẢM 30%.
- Ba biến thể 🚨 chạy song song; kẹp trong 15–70%.
- Luật chuyển: cắt làm ngay phiên kế tiếp; tăng ≤ 15 điểm %/tuần, chỉ ở phiên cuối tuần, khi 🚨 đã tắt ≥10 phiên và mục tiêu cao hơn hiện tại 2 phiên liền; không bao giờ tăng khi trung hạn GIẢM.

Replay toàn mẫu (`final/final2.py`; chỉ số giá, phí 0.15%/vòng quay, tiền mặt 0%, thực hiện phiên kế tiếp):

| Phương án | CAGR | Max DD | Lượt đổi/năm | Bị đảo ≤10 phiên | Bị đảo ≤20 phiên | Cổ phiếu TB |
|---|---|---|---|---|---|---|
| Cố định 45% | 3.63% | −23.1% | 0 | — | — | 45 |
| A0: chỉ trung hạn | 4.18% | −23.1% | 3.3 | 4% | 7% | 48.7 |
| A5+: 🚨1 chỉ nhắc, 🚨2 −1 nấc | 3.24% | −18.7% | 7.2 | 2%* | **16%** | 43.8 |
| A6: 🚨1 −1 nấc | 3.34% | −17.3% | 10.7 | 9% | 37% | 40.4 |
| A1: trả lại nhanh | 3.25% | −15.9% | 16.3 | 25% | 43% | 41.7 |
| Mua & giữ | 7.02% | −45.3% | — | — | — | 100 |

(*) Con số 2% của A5+ đúng **do cấu trúc**, vì luật bắt chờ ≥10 phiên 🚨 tắt rồi mới tăng lại. Phải nhìn cột ≤20 phiên.

Đọc bảng này cho trung thực:
- **A0 không giảm được max DD** so với cố định 45%. Toàn bộ phần giảm drawdown đến từ 🚨, và 🚨 lại sinh thêm lượt đổi.
- **Năm 2026, A5+ hai lần bán gần đáy rồi mua lại cao hơn 5–12%:**
  - 60 → 45% ngày 09/03 (1,652.79), → 30% ngày 20/03 (1,647.81); về 45% ngày 17/04 (1,817.17), 60% ngày 24/04 (1,853.29).
  - Cắt ngày 22/07 (1,668.53, đúng đáy) và 24/07 (1,686.11); mua lại ngày 21/08 (1,768.12).
  - Đó chính là kiểu "không xoay sở kịp", chỉ là ở cấp tỷ trọng.
- **Theo từng cú sập:** A5+ tệ hơn cố định 45% ở 5/9 đợt; tốt hơn rõ ở 2020 (−7.4% vs −16.1%) và 09–11/2022 (−5.6% vs −12.8%).
- **⇒ Chưa khuyến nghị phương án nào.** Chạy bóng A0, A5+ và A6 song song, rồi chọn ở P3 sau ≥4 lần chốt tuần. Nếu buộc phải chọn hôm nay thì A5+, kèm đủ các điểm trừ trên.

### 3.9 "Việc nên làm" theo cặp khung (bảng cố định trong canon; agent chỉ thêm 1 câu)

| Ngắn \ Trung | TĂNG | ĐI NGANG | GIẢM |
|---|---|---|---|
| **nhịp hồi** | Đồng pha tăng — giữ tỷ trọng theo band; mua mới ưu tiên khi chỉnh về hỗ trợ | Nhịp hồi trong xu hướng đi ngang — không nâng tỷ trọng; nếu chốt lời thì chốt phần vượt tỷ trọng | Nhịp hồi trong xu hướng giảm — dùng nhịp hồi hạ phần vượt tỷ trọng, không mua đuổi |
| **chưa rõ** | Nhịp chững trong xu hướng tăng — giữ phần lõi | Chưa rõ ở cả hai khung — giữ nguyên tỷ trọng | Nhịp chững trong xu hướng giảm — không bắt đáy theo 1–2 phiên xanh |
| **nhịp chỉnh** | Nhịp chỉnh trong xu hướng tăng — không bán phần lõi; trung hạn chỉ rời TĂNG nếu đóng tuần < ~X | Nhịp chỉnh trong xu hướng đi ngang — không bán tháo; trung hạn chuyển GIẢM nếu đóng tuần < ~X | Đồng pha giảm — giữ tỷ trọng thấp; không bắt đáy |

Bảng không dùng "cận trên/cận dưới biên", vì code không tính ra biên. Ô nào cũng chỉ trỏ tới các mức đã giải ở §3.5.

**Câu ghép Trung × Dài**, đủ 9 tổ hợp, cộng 1 câu khi chưa đủ dữ liệu:

| Trung \ Dài | THUẬN | CÂN BẰNG | BẤT LỢI |
|---|---|---|---|
| TĂNG | đồng pha — giữ tỷ trọng khung | tăng trung hạn, nền năm trung lập | tăng ngược nền — không vượt tỷ trọng khung |
| ĐI NGANG | đi ngang trên nền thuận — kiên nhẫn giữ lõi | chờ một trong hai khung ngả rõ | đi ngang trên nền yếu — ưu tiên phòng thủ |
| GIẢM | giảm trung hạn trên nền năm còn tốt — không bán tháo phần lõi | giảm trung hạn, nền năm trung lập — giữ tỷ trọng thấp | đồng pha với nền yếu — ưu tiên bảo toàn vốn |

Chưa đủ dữ liệu: "dài hạn: đang thu thập — chỉ đọc theo trung hạn".

- Không câu nào khuyên "lướt ngắn", vì ngắn hạn chưa chứng minh được lợi thế ở T+5. Câu được dùng: "nếu giao dịch ngắn thì nằm trong tỷ trọng hiện có".
- **Dòng 🔁 Thay đổi** chỉ in khi có tầng đổi hoặc đang chờ, và luôn nói rõ tầng nào **không** đổi.

### 3.10 Trạng thái lưu & kiến trúc

**Bước pipeline riêng `horizons`**, chèn giữa `gold` và `allocation` (`run.py:1580-1581`), tức trước `test`, `doctor` (`:1586`) và `brief` (`:1587`). Đặt ở đây để:
- badge doctor thấy trạng thái của cùng đêm;
- kẹp v1 (P1) và band v2 (P3) đọc được trạng thái cùng phiên;
- pipeline dừng ở bước test (như ca 30/09) vẫn đã lưu đủ đầu vào ngắn hạn của phiên đó.

**Ai đọc, ai ghi:**
- `collect_context`, `build_pack` (`vnstock_brief_pack.py:151`), train (`vnstock_train.py:383`), dashboard, brief sáng và news-alert **chỉ đọc**.
- Vì vậy `--export-pack` vẫn không đụng marker (`run.py:1438-1449`); `/brief-close` và A/B `telegram close --force` không ghi kho.

**Module `vnstock_horizons.py`** (hàm thuần) và file `_meta/horizon_state.json`:
- **`inputs[as_of]`** = {S, n, phiếu, breadth, A/D, NN 1D, nhãn header cũ, floor cũ, đóng cửa, đóng tuần khi chốt, `source: live|backfill`}.
- **`published[]`** append-only, không bao giờ ghi lại: {as_of, ngắn hạn, trung hạn, since, các mức, 🚨, nhóm T, nhóm D, kẹp, machine, computed_at}.
- **Mọi tầng được fold từ input đã lưu**, không đọc lại parquet mỗi đêm. Nhờ vậy sửa bar quá khứ (rebase, OHLC repair) không âm thầm đổi "since".
- Parquet chỉ dùng để backfill và kiểm toán. Lệch quá 0.1% thì badge "revision"; brief giữ "since" theo `published`.
- Ghi nguyên tử bằng tmp + `os.replace`, như `_write_state` (`vnstock_allocation.py:520-526`).

**Cổng ghi:**
- Chỉ ghi khi `as_of` = `covered_session` đã đóng sau 15:05 (cf. `vnstock_doctor.py:289`).
- Nếu bản ghi cho `as_of` này đã có thì không ghi lại (dùng `--force` để ghi đè). Máy chạy sau, kể cả laptop bấm "Cập nhật còn lại" (`run.py all --no-sync`), vì vậy thành no-op.
- Mỗi bản ghi có trường `machine`.
- Đêm bị hụt (21/09, 28/09) thì phiên đó được backfill với `source:"backfill"` và bị loại khỏi F1.

**Hợp đồng dữ liệu VNINDEX:**
- `_load_vnindex_df` gộp mọi file parquet trong năm mà **không khử trùng ngày** (`vnstock_brief.py:2713-2774`), và `augment=True` còn ghép bar live (`:2774`).
- Horizons dùng `augment=False`, khử trùng theo ngày (giữ bản mới nhất, như `vnstock_updater._read_year`, `vnstock_updater.py:130`).
- Kiểm đủ lịch sử: ≥40 tuần có bar, cộng 39 tuần cho bộ giải. Thiếu thì in "chưa đủ lịch sử", không bịa.

**Khi dữ liệu cũ hoặc hỏng** (`as_of` < `covered_session`, file lỗi, hoặc conflicted copy):
- Brief in "🔭 chưa cập nhật (as_of dd/mm)".
- `bias_floor` quay về đúng `_bias_floor_dir` cũ, không có `stance_allowed`, lớp bảo vệ = floor cũ. Tức an toàn như hôm nay.

**Hai máy:**
- File nằm trong kho Dropbox nên chữa một lần là đủ (○).
- Không chạy `run.py horizons --force` hay `--backfill` ở máy kia trong khung pipeline desktop (từ 18:00, hoặc lúc máy bật lên chạy bù, tới khi `run_daily.log` in `⏱ TỔNG`).

**Tin đẩy (P2):**
- Marker `_meta/horizon_push.json` dùng khóa `"<as_of>|<sự kiện>"` (🚨 bật / lên mức / tắt) và `"<năm-tuần ISO>|weekly"`. Khóa đã có thì bỏ qua.
- Chỉ gửi khi `$env:COMPUTERNAME` == `VNSTOCK_ALERT_HOST` (đặt trong `.env` của 🖥️ desktop).
- `telegram close --force` (A/B) không bao giờ đẩy 🚨.

**Các consumer vẫn neo tín hiệu ngày, có chủ đích:** `PRESET_SUGGESTIONS` theo regime (`vnstock_regime.py:24-30`), "💡 Đề xuất giao dịch" từ backtest, và gợi ý preset trên dashboard.

### 3.11 Chống đếm trùng

| Đầu vào | Ngắn hạn | Lớp bảo vệ | Trung hạn | Nhóm T (hiển thị) | Dài hạn | 🚨 | Band v1 | Band v2 (P3) |
|---|---|---|---|---|---|---|---|---|
| 7 phiếu (MA20/50/200, RSI, breadth, A/D, NN 1D) | ✔ | qua floor cũ | — | — | — | — | ✔ (cũ) | — |
| Momentum tâm lý | cảnh báo mềm | qua floor cũ | — | — | — | — | ✔ (cũ) | — |
| Đóng tuần / MA10w / MA40w | — | qua trung hạn GIẢM | ✔ | — | — | — | kẹp | ✔ |
| T1–T6 | — | — | — | ✔ | — | — | một phần (gauge cũ) | — |
| D1–D5 | — | — | — | — | ✔ | — | D5 ≈ tilt (cũ) | ±1 nấc |
| Sụt từ đỉnh, sốc 1 và 3 phiên | — | ✔ | — | — | — | ✔ | kẹp | theo phương án |

- Nhóm T và tầng dài hạn không bao giờ là đòn bẩy trước P3, nên phần chồng với các gauge của v1 không nhân đôi tác động.
- Ở P3, tilt báo cáo chỉ còn đi qua D5.

### 3.12 Trình bày & an toàn guard

**Header Telegram:** `_horizon_block` thay `_regime_block` (`vnstock_telegram.py:232-256`, dùng ở `:611` và `:657`). Header gồm 2 dòng, cộng dòng 🚨 khi trung hạn chưa GIẢM. Dòng 🧭 Tâm lý và điểm kỹ thuật ngày chuyển vào dòng "Ngắn hạn" trong 🔭.

**TLDR chiều thành 3 dòng.** Dòng 3 "**Trung hạn:** …" do code viết, guard `enforce_horizon_view` ghim. `_detect_stance` (`vnstock_brief.py:4463-4498`) phải bỏ dòng này trước khi chạy fallback đếm từ khóa, để chữ TĂNG/GIẢM của nó không làm bẩn kết quả (có test).

**Khối 🔭:**
- Đặt ngay sau TLDR, **≤6 gạch đầu dòng** (khớp luật "mỗi mục ≤ 6 dòng" của `/brief-close`, `.claude/skills/brief-close/SKILL.md:90`).
- Do code chèn, không tính vào giới hạn 500 từ của agent. Agent được ≤1 câu sau "→" ở dòng Ngắn hạn và dòng Trung hạn.
- Chi tiết từng trụ, MA10w/MA40w và bảng hành động chuyển sang tin thứ Bảy và dashboard.

**Quy tắc mức giá trong 🔭:**
- Chỉ in số 2 chữ số thập phân khi số đó nằm trong danh sách "đã biết" của `enforce_scenario_levels` (`guards_numbers.py:318-357`): close, MA20/50/200, S/R, tuần/tháng, 52w.
- Mọi mức khác in làm tròn "~1,803". Regex của guard chỉ bắt `\b[12],\d{3}\.\d{2}\b`, nên số làm tròn không bị đụng tới.
- Lưu ý: 52w trong `vnindex_tech` là **trong phiên** (1,933.11 / 1,578.42; `vnstock_brief.py:2899-2906`). Vì vậy 🔭 không in biên đóng cửa 1,580.54–1,927.94.
- Đồng thời đăng ký `vnindex_tech["horizon_levels"]` (MA10w, MA40w, neo 🚨, các mức kích hoạt) vào **cả hai** danh sách đã biết (`enforce_sr_direction` `:229-232` và `enforce_scenario_levels` `:340-343`), phòng khi agent tự chép các mức này vào câu của mình.

**Guard mới** trong `vnstock_brief_guards_sections.py`, nối sau `enforce_allocation_table` (`vnstock_brief_guards.py:250`), re-export qua `vnstock_brief`:
- `enforce_horizon_view` — dựng lại 🔭 và dòng TLDR 3 từ canon `_horizon_body_lines(ctx)`, theo mẫu `_macro_reports_body_lines` (`canon:254-302`); giữ ≤1 câu của agent.
- `enforce_stance_horizon` — ghim nhãn Stance theo §3.4.
- `enforce_horizon_vocab` — đổi "Risk-on/Risk-off" ở cấp thị trường thành "điểm kỹ thuật ngày …". Cụm "đảo chiều xu hướng (thị trường/VNINDEX)" khi trung hạn không đổi thì chỉ **đếm** vào `brief_watch`, chưa sửa. Không đụng chữ "đảo chiều" khi nói về mã hay mẫu hình.
- **Test vòng tròn:** khối 🔭 chuẩn đi qua toàn bộ `apply_brief_guards` phải ra **giống từng byte**.

**Emoji:**
- Thêm 🔭 vào `_SECTION_EMOJIS` (`guards_common.py:39`).
- Dòng con trong 🔭 luôn bắt đầu bằng "- ", nên 🚨, 💼, 🔁 không thành ranh giới mục.
- Dài hạn không dùng 🌐, vì 🌐 cũng là section emoji.

**Đổi nhãn** (có điều kiện theo `VNSTOCK_HORIZONS`):
- `REGIME_META` (`vnstock_regime.py:32-38`) thành "🟢/🔴 Kỹ thuật ngày: rất tích cực / rất tiêu cực…".
- "🔥 Risk-on / ❄️ Risk-off" của quant (`vnstock_market_analyzer.py:582-589`) thành "Dòng tiền ngành nghiêng mạnh tích cực/tiêu cực". Tiêu đề prompt "Quant Market Regime" (`vnstock_brief.py:3133-3145`) đổi theo.

**Brief sáng** (không có task lịch; `run.py:1430-1431`; `setup_scheduled_tasks.ps1` không đăng ký):
- Thêm 1 gạch đầu dòng trong TLDR.
- Bias sáng theo cùng `stance_allowed`; "Kịch bản phiên chiều" (`:3095-3100`) theo `bias_floor` mới.
- Không bao giờ đổi trạng thái trong phiên.

**Đi kèm khác:**
- `_few_shot_block` (`vnstock_brief.py:4093-4110`): cắt mẫu trước ngày P1b, để không dạy lại TLDR 2 dòng và từ vựng cũ.
- `brief_pack.json`: mang `ctx["horizons"]` để đường Claude và `--from-file` chạy cùng guard.
- `finalize_brief`: loại 🔭 khỏi đếm `guard_delta`, vì đó là code chèn chứ không phải guard sửa.
- `/brief-close`: thêm luật "không viết lại 🔭".
- **Độ chính xác Stance theo agent** (`vnstock_stance_track`, dashboard) ghi thêm `stance_source: code|agent`; view theo agent chỉ chấm ngày agent tự chọn. Lý do: khi nhãn bị ghim, T+1 đo **code** chứ không đo agent, và TRUNG TÍNH chỉ đúng khi |Δ| ≤ 0.3% (`vnstock_stance_track.py:27`).

**Độ dài:**
- 🔭 thêm khoảng 110–140 từ, nên brief chiều có thể tách thành 2 tin (`_MAX_MSG_LEN` 4000, `vnstock_telegram.py:31`).
- `_BRIEF_MAX_TOKENS` (2800, `vnstock_brief.py:186`) chỉ nâng nếu `llm_ledger --show` cho thấy bị cắt cụt.

---

## 4. Mẫu brief mới

Dựng cho brief chiều **phiên 02/10/2026**.
- 💼 = 15% (B4). Đây là band hiệu lực lúc đó theo luật cũ (notes `:7965`). Sau lượt 00:10 ngày 05/10, band là B3 trộn 10% (~28–29%). Kẹp ở §3.8 sẽ giữ 15%.
- Số vĩ mô có (*) là minh họa.
- **Ở P1b:** dòng vĩ mô chỉ in số và chiều, chưa có nhãn độ tin cậy; dòng dài hạn in "đang thu thập".

**(A) Header Telegram**
```
📊 VNINDEX 1,737.71 (-0.66%) · phiên 02/10
🔭 Trung hạn: GIẢM (tuần 1, từ 02/10) · 💼 Cổ phiếu 15% · Nên: giữ tỷ trọng thấp, không bắt đáy theo 1–2 phiên xanh
```
Phiên 01/10 (trung hạn còn ĐI NGANG nên 🚨 hiện):
```
📊 VNINDEX 1,749.30 (-1.09%) · phiên 01/10
🔭 Trung hạn: ĐI NGANG (từ 24/07, 10 tuần) · 💼 Cổ phiếu 15% · Nên: không bán tháo; chuyển GIẢM nếu thứ Sáu đóng < ~1,766
🚨 Rủi ro ngắn hạn: BẬT — thấp hơn đỉnh 20 phiên 5.6%; không đổi xu hướng
```

**(B) Brief chiều — phần đầu**
```
## 🎯 TLDR
**Kết quả phiên:** VNINDEX 1,737.71 (-0.66%), phiên giảm thứ 5 liên tiếp; khối ngoại bán ròng 3,297 tỷ.
**Stance ngày mai:** GIẢM — canh giảm nếu thủng S1=[engine S/R] → mục tiêu S2=[…]; hủy nếu vượt lại R1=[…].
**Trung hạn:** chuyển GIẢM từ 02/10 → không mua đuổi nhịp hồi; chỉ rời GIẢM khi 2 tuần liền đóng trên ~1,803 (mức tuần tới, tính lại mỗi tuần).

## 🔭 Góc nhìn theo khung thời gian
- 🔁 Thay đổi: trung hạn ĐI NGANG → GIẢM (chốt tuần 02/10, sau 10 tuần đi ngang). Ngắn hạn và dài hạn không đổi.
- Ngắn hạn (vài phiên): nhịp chỉnh, phiên thứ 7 (từ 24/09); điểm kỹ thuật ngày -6/7; tâm lý Sợ hãi. Hết nhịp chỉnh khi điểm về ≥ 0. → [≤1 câu agent]
- Trung hạn (xu hướng tuần): GIẢM, tuần 1; chỉ 9% mã trên MA200 — cổ phiếu trung vị yếu hơn chỉ số. Vĩ mô–dòng tiền: độ tin cậy TRUNG BÌNH (bất lợi: độ rộng · thuận: tỷ giá* · trung tính: khối ngoại*, PMI · chưa đo: thanh khoản, chênh lệch 10 năm). → [≤1 câu agent]
- Dài hạn (6–12 tháng): chưa đủ dữ liệu (2/5 trụ: tăng trưởng thuận — GDP Q3 tăng tốc*; báo cáo bất lợi — HedgeAcademy Q4). Chấm lại tháng 11.
- 🚨 Rủi ro ngắn hạn: BẬT từ 01/10, thấp hơn đỉnh ~1,853 (04/09) 6.2%; lên mức 2 nếu đóng < ~1,668 (90% đỉnh neo) hoặc thêm 1 phiên ≤ -2.5%. Không đổi xu hướng.
- 💼 Cổ phiếu 15% theo band (B4); không tăng khi trung hạn GIẢM hoặc 🚨 bật. Nên: giữ tỷ trọng thấp, không bắt đáy theo 1–2 phiên xanh; hạ trước mã đã thủng MA50.
```

**(C) Danh mục đang giữ** — dòng dữ kiện thêm trạng thái MA50 do code tính; hành động neo theo lớp bảo vệ + band:
```
- [dòng dữ kiện mã X] · dưới MA50 → GIẢM TỶ TRỌNG (trung hạn GIẢM, danh mục vượt 15% — hạ mã yếu trước)
- [dòng dữ kiện mã Y] · trên MA50 → GIỮ (vị thế lõi trong tỷ trọng 15%; không bán vì 1 phiên đỏ)
```

**(D) Brief sáng** (nếu còn dùng) — 1 gạch đầu dòng trong TLDR:
```
- 🔭 Trung hạn GIẢM (tuần 1) · ngắn hạn: nhịp chỉnh (phiên 7) · 💼 15% — Bias chỉ TRUNG TÍNH/GIẢM; không BUY vô điều kiện
```

**(E) Tin riêng khi 🚨 bật** (P2; ~15:10 qua task theo giờ, hoặc cùng brief tối):
```
🚨 RỦI RO NGẮN HẠN TĂNG — phiên 01/10/2026
VNINDEX 1,749.30, thấp hơn đỉnh 20 phiên (~1,853 ngày 04/09) 5.6%.
Không đổi: trung hạn ĐI NGANG (từ 24/07). Nếu thứ Sáu đóng < ~1,766 sẽ chuyển GIẢM.
Lịch sử 2017–2026: sau tín hiệu này 51% lần giảm thêm ≥3% trong 20 phiên, nhưng trung vị 20 phiên vẫn +1.7%.
Nên: không mua thêm; nếu đang vượt tỷ trọng thì hạ phần vượt. Không nên: bán tháo phần lõi.
```

**(F) Tin thứ Bảy "Góc nhìn tuần 28/09–02/10"** (P2; không qua guard brief nên in đủ số):
```
🔭 Trung hạn: ĐI NGANG → GIẢM. Đóng tuần 1,737.71; MA10 tuần 1,781.99 < MA40 tuần 1,801.32.
   Rời GIẢM: 2 tuần liền đóng > ~1,803 (tuần tới). Lên TĂNG: phải qua ĐI NGANG trước; hiện cần MA10 tuần vượt MA40 tuần (~1,995 trong 1 tuần — chưa thể).
   Độ rộng 9% mã trên MA200 (4 tuần trước ~[số]).
📊 Vĩ mô–dòng tiền: TRUNG BÌNH. Khối ngoại 60 phiên [số repo] · độ rộng bất lợi · PMI 51.9 (-1.4) trung tính · USD/VND -1.1%/2 tháng thuận · LNH 1W−điều hành [số] · VN10Y−US10Y -0.79 (chiều 3 tháng [số]).
🏛 Dài hạn: chưa đủ dữ liệu (tăng trưởng +1 · báo cáo -1 · lạm phát, chu kỳ lãi suất, định giá: chưa đo). Chấm lại tháng 11.
🚨 BẬT từ 01/10 (neo 1,853.08). Mức 2: < ~1,668. Tắt: ≥ ~1,797 hoặc 3 phiên trên MA20, sớm nhất 08/10.
📏 Độ ổn định 20 phiên: ngắn hạn đổi [k] lần · trung hạn 1 · nhãn header cũ (chạy bóng) [m].
```

**Bảng hành động** (in ở tin thứ Bảy và dashboard; cột % chỉ thêm từ P3):

| Trạng thái | Nên | Không nên |
|---|---|---|
| Trung hạn TĂNG | Giữ mã dẫn dắt; mua thêm khi chỉnh về hỗ trợ | Bán hết vì 1–2 phiên giảm |
| Trung hạn ĐI NGANG | Giữ lõi; chốt phần vượt tỷ trọng | Tăng tỷ trọng vì nhịp hồi 2–3 phiên |
| Trung hạn GIẢM | Ưu tiên tiền gửi/trái phiếu; chỉ mua có điều kiện | Bắt đáy theo 1–2 phiên xanh |
| ⏳ đang chờ 1/2 | Chuẩn bị danh sách mã và mức | Hành động trước khi xác nhận |
| 🚨 mức 1 | Không mua thêm; rà mã yếu hơn thị trường | Bán tháo phần lõi; đổi nhận định xu hướng |
| 🚨 mức 2 | Hạ phần vượt tỷ trọng ở phiên kế tiếp | Bán tháo ở phiên sàn |

---

## 5. Nếu áp cho giai đoạn 27/08 – tháng 09/2026

Cột "Cũ" là replay code hiện tại. Cột "Mới" là thiết kế này, replay trên cùng đầu vào. "Bảo vệ" là cột lớp bảo vệ.

| Ngày | VNINDEX | Cũ: header · Stance bị ép | Mới: ngắn hạn · Stance | Mới: trung hạn (mức in) | 🚨 | Bảo vệ |
|---|---|---|---|---|---|---|
| 20/08 | 1,734.24 | ❄️ Bear −5 · GIẢM | nhịp chỉnh · **GIẢM** (ép) | ĐI NGANG; GIẢM nếu đóng tuần < ~1,722 | tắt | bật |
| 21/08 (T6) | 1,768.12 (+1.95%) | Tiêu cực −1 · tự do | nhịp chỉnh · GIẢM (điểm −1 < 0) | ĐI NGANG | tắt | bật |
| **24/08** | **1,788.78** | **🔥 Bull Risk-on +4 · TĂNG** | → **chưa rõ** · TRUNG TÍNH/GIẢM (TĂNG bị cấm) | ĐI NGANG; tuần này GIẢM < ~1,750, lên TĂNG cần > **~1,842** (cắt MA) | tắt | tắt |
| 26/08 | 1,821.32 | Bull +4 · TĂNG | → nhịp hồi · TRUNG TÍNH ("nhịp hồi trong xu hướng đi ngang — không nâng tỷ trọng") | ĐI NGANG | tắt | tắt |
| 28/08 (T6) | 1,832.12 | Bull +4 · TĂNG | nhịp hồi · TRUNG TÍNH | Vẫn ĐI NGANG: 1,832.12 < ~1,842 (MA10w 1,786.90 < MA40w 1,787.61). Tuần sau: lên TĂNG "chưa thể" (~1,954) | tắt | tắt |
| 04/09 (T6) | 1,853.08 (đỉnh) | Bull +4 · TĂNG | nhịp hồi · TRUNG TÍNH | ĐI NGANG (1,785.02 < 1,792.57); GIẢM < ~1,758 | tắt | tắt |
| 07–10/09 | 1,821.64 → 1,829.23 | 0 → TĂNG bị ép | → chưa rõ · TRUNG TÍNH/GIẢM | ĐI NGANG | tắt | tắt |
| 11/09 | 1,795.21 (−1.86%) | GIẢM bị ép (momentum −53) | chưa rõ · TRUNG TÍNH/GIẢM | ĐI NGANG | tắt | **bật** (floor cũ) |
| 15–18/09 | 1,811.15 → 1,815.66 | Bull +4 · TĂNG | → nhịp hồi · TRUNG TÍNH | ĐI NGANG | tắt | tắt |
| 21–23/09 | 1,799.67 / 1,816.93 / 1,801.65 | GIẢM / TĂNG / GIẢM bị ép | → chưa rõ · TRUNG TÍNH/GIẢM | ĐI NGANG; GIẢM < ~1,764 | tắt | bật 21 và 23/09 |
| **24/09** | **1,775.09 (−1.47%)** | **❄️ Bear Risk-off −5 · GIẢM** | → nhịp chỉnh · **GIẢM** (ép) | ĐI NGANG ("nhịp chỉnh trong xu hướng đi ngang — không bán tháo; chuyển GIẢM nếu đóng tuần < ~1,764") | tắt | bật |
| 25/09 (T6) | 1,785.11 | Tiêu cực −2 | nhịp chỉnh · GIẢM | ĐI NGANG; tuần sau GIẢM < ~1,766 | tắt | bật |
| 01/10 | 1,749.30 (−1.09%) | Bear −6 | nhịp chỉnh · GIẢM | Tạm tính lần đầu chạm: "nếu thứ Sáu đóng < ~1,766 → GIẢM" | **BẬT mức 1** (−5.6%) | bật |
| **02/10 (T6)** | **1,737.71** | Bear −6 | nhịp chỉnh · GIẢM | **ĐI NGANG → GIẢM** | BẬT | bật |

**Tổng kết 15/08–30/09:**

| Chỉ số | Cũ (replay) | Mới |
|---|---|---|
| Đổi nhãn tiêu đề | 17 (nhãn 5 mức) | Trung hạn 0 (đổi GIẢM ngày 02/10) |
| Stance bị code quyết đổi | 16; 11 ngày TĂNG, 11 ngày GIẢM | 2; 0 ngày TĂNG; 10 ngày ép GIẢM; còn lại agent chọn TRUNG TÍNH/GIẢM |
| Đảo TĂNG↔GIẢM | 6 | 0 |
| Ngắn hạn đổi trạng thái | — | 6, gồm 1 vòng nhịp hồi → nhịp chỉnh (26/08 → 24/09, qua chưa rõ) |
| Lớp bảo vệ | bật đúng các ngày floor GIẢM | bật mọi ngày đó, cộng thêm ngày nhịp chỉnh / trung hạn GIẢM / 🚨 |
| Chữ "Risk-on/off" | xuất hiện | 0 |
| Báo trước đổi trung hạn | — | Mức tĩnh in hằng ngày, cách giá 2–6%; tạm tính chạm mức 1 phiên trước khi chốt (01/10) |
| 💼 | Band v1 đổi 15 → ~28–29% → 15% quanh 02–05/10 (§1.7) | Kẹp giữ 15% từ 02/10 |

Dòng ngắn hạn trong 🔭 vẫn đổi chữ (nhịp chỉnh → chưa rõ → nhịp hồi → chưa rõ → nhịp hồi → chưa rõ → nhịp chỉnh). Đó là mô tả nhịp, không phải lệnh. Header không mang dòng này.

**Cái giá, nói thẳng:**
1. Thiết kế mới không kiếm thêm gì từ nhịp +7.3%: Stance không lần nào TĂNG.
2. Stance GIẢM chậm hơn hệ cũ (trung vị 12 so với 8 phiên sau đỉnh). Bù lại bằng lớp bảo vệ, bật trung vị 3 phiên.
3. Kết luận "ĐI NGANG suốt giai đoạn" là sát nút: ngày 28/08 chỉ chênh 0.71 điểm.
   - Luật 2 tuần và hysteresis được chọn **sau** khi đã thấy giai đoạn.
   - Theo nghiên cứu, luật tuần cho ra ĐI NGANG với mọi biên ±1–3%. Còn luật ngày MA200 ±1–2% không có điều kiện độ dốc thì đã bật ON trong 28/08–08/09.
4. Ở Q1-2026 (−16.4%), trung hạn còn TĂNG tới 20/03 (−13.4%), và chỉ đi xuống ĐI NGANG chứ không xuống GIẢM. Chỉ có 🚨 cảnh báo, từ 28/01.
5. Bảo vệ bật 51% số phiên, nên watchlist sẽ thường xuyên ở dạng "mua có điều kiện" hơn.

---

## 6. Lộ trình

### P0 — Chốt tham số trên dữ liệu thật (0.5–1 ngày; không đổi production)

**Claude:** viết mới `scripts/replay_horizons.py`.
- Port từ các script scratch: `extract_stance_timeline.py` hiện chỉ có trong scratchpad, **không có trong repo**.
- Chỉ đọc parquet (khử trùng ngày), `foreign_net_daily.json`, `allocation_state.json`, `macro_indicators.json` và `brief_memory.db` (`mode=ro`).
- In CSV và bảng tóm tắt: nhãn và floor cũ đã in thật, ngắn hạn/trung hạn mới, mức kích hoạt, phân vị các trụ T.

**Bạn — ○ máy nào cũng được** (kho đồng bộ Dropbox; tránh khung pipeline desktop từ 18:00 tới khi `run_daily.log` in `⏱ TỔNG`):
- `git fetch origin <nhánh> && git merge origin/<nhánh>`
- `python scripts/replay_horizons.py --from 2026-06-01 --summary`
- `python vnstock_allocation.py --history 120`
- *(○, ghi kho một lần)* `python vnstock_foreign_flow.py --refresh --days 500`. Đây là thử backfill khối ngoại cho trụ T1; chưa xác minh API trả được lịch sử sâu. Lỗi thì bỏ, T1 tạm "chưa đo".

**Mục đích:**
- Xác nhận brief **thực sự** đã in gì trong 15/08–02/10: nhãn, Stance, band.
- Đo lại ngắn hạn với A/D và breadth thật.
- Đo độ sâu registry: CPI/PMI/GDP có đủ 3–6 tháng chưa; `usdvnd`/`interbank_1w` có ≥60 lần đọc chưa.
- Hiệu chỉnh ngưỡng T1–T6 theo phân vị, và chốt tham số theo **vùng phẳng** (biên ±1–3%, cấu hình 8–12 tuần / 30–50 tuần), không chọn theo điểm tối ưu.
- Bạn ký các quyết định ở §8.

### P1a — Tính và chạy bóng (~4–5 ngày công + ≥5 phiên chạy bóng; brief không đổi)
- **File chạm:**
  - `vnstock_horizons.py` (mới): ngắn hạn, trung hạn + bộ giải 2 ràng buộc, 🚨, lớp bảo vệ, fold, backfill, cổng ghi.
  - `_meta/horizon_state.json` (input + published + log nhãn/floor cũ chạy bóng).
  - `run.py`: thêm bước `horizons` giữa `gold` và `allocation` (`:1580-1581`), subparser `horizons --show|--backfill|--replay|--force` (cạnh `:2034`).
  - `vnstock_doctor.py`: badge `horizons` (cũ / conflicted copy / revision / fold ≠ published).
  - `vnstock_regime.py:241`: truyền `effective_date`.
- **Test** — `tests/test_horizons.py`, thêm vào whitelist `--fast` (`run.py:713+`):
  - ngắn hạn: ngưỡng theo n, nhảy thẳng sang nhịp chỉnh, cấm chỉnh→hồi;
  - trung hạn: các bước, hysteresis, 1 bậc/tuần, lên cần 2 tuần;
  - **bộ giải**: ca 28/08 phải ra ~1,842 chứ không phải ~1,823; "chưa thể trong tuần này"; rời GIẢM lấy min;
  - chốt tuần: thứ Sáu nghỉ, đêm bị hụt, tuần Tết rỗng/ngắn;
  - 🚨: 3 điều kiện bật, neo cố định, mức 2, dwell 5, tắt, không tự tắt khi đỉnh trôi ra khỏi cửa sổ;
  - fold idempotent; chạy lần 2 cùng `as_of` là no-op; trường `machine`; loader khử trùng ngày, `augment=False`, kiểm đủ lịch sử;
  - **property test**: nhiễu A/D, NN, breadth, RSI ở bất kỳ ngày nào, hoặc nhiễu giá ở ngày không chốt tuần, thì trung hạn không đổi. Sốc giá ở phiên chốt tuần chỉ được làm trung hạn **giảm** 1 bậc rủi ro, không bao giờ tăng.
- **Kill-switch:** `VNSTOCK_HORIZONS_STEP=0` bỏ bước tính/ghi.
- **Điều kiện qua P1b:**
  - 5 phiên liền ghi không lỗi;
  - fold từ input đã lưu = published (100%);
  - trạng thái chạy bóng khớp replay của các phiên đó;
  - test vòng tròn 🔭 xanh trên 5 ctx thật;
  - bạn duyệt 1 mẫu.

### P1b — Bật hiển thị, Stance mới, lớp bảo vệ, kẹp band (~5–6 ngày công)
- **`vnstock_brief.py`:**
  - `_bias_floor_dir` (`:1327-1343`) chỉ dùng khi fallback; `collect_context` (sau `:2639`) chỉ **đọc** state rồi gán `ctx["horizons"]`, `ctx["bias_floor"]`, `ctx["defensive"]`.
  - Prompt `:3088-3123`.
  - Template chiều: TLDR dòng 3 và 🔭 sau `:305`; watchlist `:332`; 📚 `:357`; danh mục `:360` + `_portfolio_block` `:1958-1968` (neo theo lớp bảo vệ + band; thêm MA50 vào `_portfolio_fact_line`, `vnstock_brief_canon.py:317`).
  - Template sáng `:218-221`, `:272`; `_few_shot_block`; `_detect_stance`; `Quant Market Regime` `:3133-3145`.
- **`vnstock_brief_canon.py`:** `_horizon_body_lines` (gồm dòng vĩ mô **chỉ số + chiều**, chưa chấm); viết lại chỉ thị `:166-176`.
- **Guards:**
  - 3 guard mới, nối vào chuỗi và re-export;
  - helper `is_defensive` trong `_guards_common`, dùng ở `:470` và `:1411`;
  - thêm 🔭 vào `_SECTION_EMOJIS`; thêm `horizon_levels` vào 2 danh sách mức đã biết;
  - viết lại `_ALLOC_HORIZON_CAVEAT` (`:237-242`): "tỷ trọng theo band và xu hướng trung hạn; nhịp ngày chỉ chọn thời điểm" + điều kiện lệch mới (`:310-321`).
- **`vnstock_telegram.py`:** `_horizon_block` (`:232-256`, `:611`, `:657`); `_market_is_bearish` (`:399-421`) đọc lớp bảo vệ; lệnh `run.py horizons --legend` gửi 1 tin giải thích từ vựng mới.
- **`vnstock_allocation.py`:** kẹp + 3 vá (§3.8). `dashboard/allocation_tab.py:70-73`.
- **Khác:** `dashboard/market_tab.py:481-500` (badge trung hạn + ngắn hạn); `vnstock_regime.py:32-38` và `vnstock_market_analyzer.py:582-589` đổi nhãn có điều kiện; `vnstock_stance_track` thêm `stance_source`; `vnstock_brief_pack.py` (pack mang horizons); `.claude/skills/brief-close/SKILL.md` (không viết lại 🔭).
- **Test** — `tests/test_brief_horizons.py`, thêm vào whitelist:
  - bảng Stance 9 ô × 🚨, GIẢM không bao giờ bị loại;
  - **property tập cha**: mọi ctx có floor cũ GIẢM thì lớp bảo vệ bật, và 3 consumer cùng chạy;
  - vòng tròn 🔭 qua `apply_brief_guards` giống từng byte, chỉ dùng số làm tròn hoặc mức đã biết;
  - `enforce_stance_horizon`; phạm vi `enforce_horizon_vocab`;
  - `_detect_stance` khi có TLDR dòng 3;
  - state cũ hoặc hỏng thì fallback đúng floor cũ;
  - `VNSTOCK_HORIZONS=0` cho prompt, template và header **giống hệt bản trước P1** (golden);
  - kẹp v1: % cổ phiếu không tăng khi GIẢM/🚨, kể cả lúc tilt phai; hết kẹp thì ≤1 bậc/tuần; vá 1 bậc; nút giữa phiên không ghi; pending vào history.
- **Cập nhật test cũ:**
  - `tests/test_brief.py`: 28 chỗ dùng `bias_floor`, gồm `test_bias_floor_dir_logic` `:2810-2816` (momentum đứng một mình không còn ép);
  - `tests/test_regime.py` (nhãn);
  - `tests/test_telegram.py:189-204` (`_regime_block`) và `:334-370` (`_market_is_bearish`);
  - `tests/test_close_1507_review.py:202-230` (patch `_market_is_bearish`, giữ tên hàm);
  - `tests/test_brief_split.py` (wiring `:133`, re-export `:197`/`:209`).
  - **Chạy FULL `python run.py test` trước khi tạo PR.**
- **Kill-switch:**
  - `VNSTOCK_HORIZONS=0`: trả lại **toàn bộ** header, nhãn, prompt, template, floor, guard bảo vệ, caveat và neo danh mục cũ.
  - `VNSTOCK_HORIZON_MACRO=0`: tắt dòng vĩ mô.
  - `VNSTOCK_ALLOC_HORIZON_CAP=0` và `VNSTOCK_ALLOC_ONE_STEP=0`.
  - Thêm tất cả vào danh sách env trong CLAUDE.md.
- **Tài liệu:** thêm `vnstock_horizons.py` vào bản đồ kiến trúc CLAUDE.md; thêm mục theo dõi vào `docs/VIEC-DANG-LAM.md`.
- **Việc của bạn:**
  - 🖥️ DESKTOP: merge code (pipeline chạy ở đây). 💻 LAPTOP chỉ cần merge nếu có dùng dashboard ở đó.
  - 🖥️ DESKTOP: chạy `python run.py horizons --legend` một lần.
  - 🖥️ DESKTOP: theo dõi `run_daily.log` và Telegram 5 phiên đầu.

### P2 — Bảng vĩ mô có chấm điểm, dài hạn, kênh tuần, 🚨 sớm, đo lường, v2 chạy bóng (~1.5–2 tuần công)
- **Nhóm T (§3.6):** `load_market_net_window` (`vnstock_foreign_flow.py`), `window_change` (`vnstock_macro.py`, cạnh `dense_history` `:856-875`), phân vị, nhãn tuần có giữ 2 tuần.
- **Dài hạn:** tối đa 5 trụ (D4 chờ P3), chấm tháng, đổi khi giữ 2 kỳ, chỉ in trạng thái khi ≥3/5 trụ đo được; D5 giữ dấu 90 ngày.
- **Kho chậm `_meta/macro_slow.json`** (ngoài trần 13 chỉ báo; cần bạn đồng ý): FRED `observation_start` 24 tháng cho `fed_funds`/`us10y`, lịch sử `usdvnd`, lãi suất điều hành NHNN.
- **Tin thứ Bảy:** bước `horizon-weekly` trong `_weekend_steps` (`run.py:1226-1241`), sau `rates-weekly`; hàm `push_horizon_weekly` cạnh `push_rates_weekly` (`vnstock_telegram.py:679`).
- **🚨 đẩy tin + bản sớm 15:10:** hook trong `vnstock_news_alert.run` (`:1269`), dùng marker khử trùng và `VNSTOCK_ALERT_HOST`; chọn kênh chính hay kênh `news`.
- **Đo lường:**
  - bộ chấm theo đường đi trong `vnstock_scorecard.py` (hiện chỉ chấm lần vào đầu tháng, `monthly_periods` `:142-156`) cho v1, v2 bóng (A0/A5+/A6) và cố định 45%;
  - `vnstock_stance_track`: T+5 cho ngắn hạn (so baseline "luôn TRUNG TÍNH" và "dấu 5 ngày"), T+20/T+60 cho trung hạn;
  - badge `horizon_stability` theo `MIN_SAMPLES` (dưới sàn mẫu hiện "ok n=…");
  - bộ đếm `brief_watch` cho cụm "đảo chiều xu hướng";
  - trường "kịp xoay sở?" cho `vnstock_brief_pack.py --rate`.
- **Band v2 chạy bóng** trong `horizon_state` + dashboard.
- **Test:**
  - từng trụ T/D (luật, phân vị, độ phủ, giữ nhãn 2 tuần/2 kỳ, luật ≥3/5, D5 giữ 90 ngày);
  - `load_market_net_window`, `window_change`, FRED `observation_start` + `macro_slow.json` (kill-switch; không chạm trần 13);
  - marker đẩy: chạy lại, `--force` A/B, máy không phải host, khóa tuần ISO;
  - hook 15:10: không ghi kho, khử trùng với bản tối;
  - bộ chấm đường đi; T+5/T+20/T+60; badge dưới sàn mẫu; trường đánh giá.
  - Thêm tất cả vào whitelist.
- **Kill-switch:** `VNSTOCK_HORIZON_BASE=0`, `VNSTOCK_HORIZON_WEEKLY=0`, `VNSTOCK_RISK_ALERT_PUSH=0`, `VNSTOCK_RISK_ALERT_EARLY=0`, `VNSTOCK_MACRO_SLOW=0`.
- **Việc của bạn:**
  - 🖥️ DESKTOP: thêm `VNSTOCK_ALERT_HOST=PICHU` vào `.env`.
  - 🖥️ DESKTOP: kiểm `FRED_API_KEY` có trong `.env`.
  - Không cần đăng ký lại task: task Weekend và News Alert đã có sẵn.

### P3 — Band v2 thành con số thật (cần bạn ký; chạy song song ≥4 lần chốt tuần trước khi chuyển)
- **`band_from_horizons()`** sau `VNSTOCK_ALLOC_V2` (mặc định 0):
  - tỷ trọng gốc theo trung hạn;
  - 🚨 theo phương án bạn chọn;
  - dài hạn ±1 nấc, chỉ khi ≥4/5 trụ đo được và đã giữ 2 tháng;
  - bỏ qua `compute_score` / `apply_hysteresis` / `apply_tilt`; tilt chỉ còn đi qua D5.
  - Lịch sử v1 giữ nguyên với `engine:"v1"`.
- **D4 định giá:** `vnstock_valuation.py` (P/E vốn hóa, EPS âm, biến thể bỏ VIC, tăng trưởng lợi nhuận DN). Ngừng vứt lịch sử tỷ số VCI ở `_best_ratio_row` (`vnstock_fundamental_updater.py:197-204`).
- **"Góc nhìn tháng":** template phân bổ (`vnstock_brief.py:381-418`) thêm dòng dài hạn. Chỉ đẩy Telegram nếu bạn đảo tham số duyệt #4.
- **Test:** luật chuyển; không bao giờ có 2 con số tỷ trọng trong brief; scorecard liên tục qua lần chuyển; định giá (thiếu dữ liệu thì "chưa đo").
- **Kill-switch:** `VNSTOCK_ALLOC_V2=0`, `VNSTOCK_VALUATION=0`.

### P4 — Nghiên cứu (sau ≥6 tháng dữ liệu sống)
- Phiếu NN và A/D 5 phiên thay phiếu 1 phiên.
- Dùng nhóm T làm cổng.
- 🚨 trong phiên.
- Lịch catalyst.
- Xác suất kịch bản, chỉ khi hiệu chỉnh xong và Brier tốt hơn climatology.

---

## 7. Rủi ro & cách đo

### 7.1 Rủi ro chính
1. **Tầng chậm thì trễ.**
   - Trung hạn trễ ~61 phiên; 3/6 đỉnh lớn chưa bao giờ xuống GIẢM.
   - Ngắn hạn chậm hơn floor cũ ~4 phiên sau đỉnh và ~9 phiên sau đáy.
   - Phần nhanh duy nhất là lớp bảo vệ và 🚨, và hai phần này **không đổi tỷ trọng trước P3**, trừ kẹp chặn chiều tăng.
2. **Overfit (n=1).**
   - Luật 2 tuần và hysteresis được chọn sau khi soi; ngày 28/08 sát nút 0.71 điểm.
   - Các phát hiện vững: nhiễu nền 70–110 lần đổi/năm; làm mượt không cứu được vòng đảo; tầng chậm thì ổn định nhưng trễ.
3. **🚨 có lợi thế về rủi ro, không có lợi thế về chiều.**
   - Trung vị 20 phiên sau khi bật vẫn dương; bật ~31% số phiên, dễ gây mỏi.
   - Gắn 🚨 vào tỷ trọng sẽ thêm lượt đổi, và năm 2026 A5+ đã bán gần đáy 2 lần.
4. **Dữ liệu proxy và định nghĩa:**
   - Breadth dùng EMA200, mẫu số gồm cả mã có < 200 bar (`vnstock_runner.py:364-369`); mã bị cách ly (70 mã tới 07/09, 45 mã 16–29/09) làm méo thêm.
   - NN của repo là khớp lệnh, chỉ có từ ~06/2026; Finhay có gồm thỏa thuận.
   - Registry chỉ giữ ≤60 lần đọc; FRED chỉ lấy bản mới nhất; PMI lấy qua RSS hoặc nhập tay.
5. **Lớp bảo vệ bật 51% số phiên:** watchlist sẽ "phòng thủ" thường xuyên hơn. Đo bằng số setup bị viết lại mỗi tuần.
6. **Va chạm guard làm hỏng 🔭 âm thầm.** Phòng bằng test vòng tròn, quy tắc số làm tròn và test wiring.
7. **Kho dùng chung.** Phòng bằng cổng ghi idempotent, trường `machine`, `VNSTOCK_ALERT_HOST` và badge conflicted copy.
8. **Nghĩa của độ chính xác Stance thay đổi:** T+1 có thể giảm (thêm TRUNG TÍNH). Không đánh giá thiết kế bằng T+1.
9. **Độ dài:** brief có thể tách thành 2 tin.

### 7.2 Scorecard (đăng ký trước; chấm ở mốc 3 tháng ≈ 60 phiên và 6 tháng ≈ 120 phiên)

| Mã | Thước đo | Ngưỡng đạt | Nguồn |
|---|---|---|---|
| F1 | Trung thực triển khai: fold từ **input đã lưu** = `published` | 100% số phiên `source:"live"` | `run.py horizons --replay` (badge) |
| F2 | Backfill từ parquet so với live: cùng trạng thái ngắn hạn | ≥90% (dung sai do cách ly/sửa bar) | như trên |
| W0 | Nhãn header và floor cũ (chạy bóng) so với hệ mới: số lần đổi và đảo trên dữ liệu sống | chỉ báo cáo | `horizon_state.inputs` |
| W1 | Ngắn hạn: số lần đổi / 60 phiên; số lần chỉnh→hồi trực tiếp | ≤10 (replay proxy ~6.5, chưa có breadth/A/D thật); 0 | `published` |
| W2 | Trung hạn: số lần đổi / 60 phiên; số lần bị đảo ≤4 tuần | ≤2; ≤1 trong 6 tháng | như trên |
| W3 | "Risk-on/off" trong **bản thô của agent** (trước guard) và trong bản đã xuất bản | thô giảm dần; xuất bản = 0 | `brief_claude_raw.md` + bộ đếm guard |
| N1 | Báo trước: bước tăng rủi ro có "⏳ 1/2" ≥1 tuần; bước giảm có mức in sẵn | 100% / 100%, kèm trung vị số phiên **và số giờ** từ lúc tin tới tay tới phiên mở cửa | log + marker |
| A1 | 🚨: số lần bật, % phiên bật, P(giảm thêm ≥3% trong 20 phiên) kèm khoảng tin cậy Wilson | chỉ báo cáo; n≥30 cần ~6 năm, nên 6 tháng **không phán được** | `brief_watch` |
| M1 | Giá trị của nhóm T: lợi suất 20/60 phiên sau, chia theo nhãn CAO/TRUNG BÌNH/THẤP | chỉ báo cáo kèm n | horizons + giá |
| E1 | Tỷ trọng: v1 (có kẹp) so với v2 bóng (A0/A5+/A6) và cố định 45% — lượt đổi, % bị đảo ≤10/20 phiên, lợi suất đường đi, max DD | v2 ≤8 lượt/năm, ≤20% bị đảo ≤20 phiên; không tệ hơn cố định 45% quá 2 điểm % ở bất kỳ đợt giảm ≥10% | bộ chấm đường đi |
| S1 | Stance: T+1 tách theo `stance_source`; T+5 của ngắn hạn so baseline | chỉ thông tin | `vnstock_stance_track` |
| U1 | Trải nghiệm: trường "kịp xoay sở?" (có/không) + sao cho 🔭 | tỷ lệ "có" ≥ 2/3; sao trung bình không giảm | `--rate` → memory DB |

- **3–6 tháng chứng minh được:** F1, F2, W0–W3, N1 và trải nghiệm.
- **3–6 tháng KHÔNG chứng minh được:** lợi thế của trung hạn, của 🚨 hay của nhóm T. Trung hạn chỉ ~3 lần đổi/năm. Chạy bóng chỉ kiểm được ống nước, không kiểm được tín hiệu.
- **Rollback:** đặt `VNSTOCK_HORIZONS=0` (và tắt kẹp nếu cần) khi có một trong các điều sau: F1 trượt; W1 hoặc W2 vượt ngưỡng 2 kỳ liền; test vòng tròn vỡ trên production; U1 giảm rõ.

### 7.3 Giảm "cái giá" — 5 cách, đã replay (05/10, sau câu hỏi của bạn)

Chạy lại trên cùng dữ liệu Finhay 2017-12 → 2026-10 (`scratchpad/brief_design/mitig/mitig.py`, chỉ đọc). Vẫn là n=1 cho giai đoạn 27/08–09, nhưng 4 phép thử dưới đây đo trên **toàn mẫu 8.8 năm**.

**1. Trung hạn trễ ở đỉnh lớn → thêm "cầu chì drawdown" một chiều (KHUYẾN NGHỊ).** Đang TĂNG mà đóng tuần ≤ 8% dưới đỉnh 60 phiên thì xuống ĐI NGANG ngay tuần đó (vẫn không nhảy thẳng xuống GIẢM; chiều lên giữ nguyên luật 2 tuần).

| Biến thể | Đổi/năm | Bị đảo ≤4 tuần | Rời TĂNG lúc đã giảm từ đỉnh: 2018 · 2020 · 04-2022 · 04-2025 · Q1-2026 | 27/08–09 có TĂNG? |
|---|---|---|---|---|
| Thiết kế §3.5 | 3.2 | 3/28 | −20.0% · −4.3% · −9.3% · −9.1% · **−13.4%** | không |
| **+ cầu chì 8%** | **4.3** | **8/38** | **−12.8%** · −4.3% · −9.3% · −9.1% · **−10.9%** | không |
| + cầu chì 6% | 5.4 | 18/48 | −7.0% · −4.3% · −9.3% · −9.1% · −7.7% | không |
| cầu chì 8% + rời GIẢM khi hồi ≥10–15% | 6.8–8.6 | 28–42/60–76 | như dòng 8% | không |

- 8% là điểm cân bằng: bớt 2.5–7 điểm % ở 2 cú sập trung hạn từng ngủ quên, đổi lại +1.1 lần đổi/năm và 5 lần bị đảo nhanh thêm trong 8.8 năm.
- 6% nhanh hơn nhưng nhiễu gấp đôi. **Cầu chì đối xứng (rời GIẢM sớm khi hồi mạnh) bị loại**: nó tái tạo đúng kiểu lật bạn phàn nàn (42/76 lần bị đảo).

**2. Lớp bảo vệ bật 51% số phiên → tách 2 mức (KHUYẾN NGHỊ).**
- **Cứng** = floor cũ GIẢM **hoặc** ≥ 2 trong 4 tín hiệu: chặn bắt đáy, cảnh báo lệnh MUA, chặn GIA TĂNG — **30.1%** số phiên (hệ cũ 22.8%).
- **Mềm** = đúng 1 tín hiệu và không phải floor cũ: chỉ nhắc "không mua đuổi", không viết lại watchlist — **19.8%** số phiên.
- Floor cũ một mình **luôn** là cứng: nếu định nghĩa cứng chỉ là "≥ 2 tín hiệu" thì 2.4% số phiên mất bảo vệ so với hôm nay — đã loại. Nhờ vậy mức cứng vẫn là tập cha của hệ cũ (P1 giữ property test).
- Sau đỉnh nhịp ≥10% (23 đỉnh): mềm bật trung vị ~2 phiên, cứng ~4 phiên (= floor cũ). Riêng 15/08–30/09: cứng 37% số phiên.

**3. "Không ăn được nhịp +7.3%" → giữ lõi, KHÔNG thêm túi lướt.**
- Ở ĐI NGANG danh mục vẫn cầm 45% cổ phiếu: từ đáy 17/08 tới đỉnh 04/09 phần lõi đã ăn **~3.3 điểm %**. Cái mất chỉ là phần *mua thêm*.
- Đã thử "túi lướt" thêm cổ phiếu khi nhịp hồi × ĐI NGANG (🚨 tắt): túi tự nó lãi 0.87%/năm, 48% số vòng lỗ ⇒ túi 10% chỉ đóng góp **+0.09 điểm %/năm**. Riêng 15/08–02/10/2026: 2 vòng, **cả 2 lỗ** (−0.1%, −0.8%). Không đáng thêm độ phức tạp, và chính là phương án B trá hình.

**4. Lo tham số "may" (overfit) → đã quét 18 tổ hợp lân cận.**
- **12/12** tổ hợp MA8w/MA30w và MA10w/MA40w × biên ±1/2/3% × cần 1/2 tuần đều **không TĂNG** trong 27/08–09 và đều ra GIẢM ngày 02/10. Kết luận ĐI NGANG không phải mũi kim của riêng bộ tham số đã chọn.
- **6/6** tổ hợp chậm hơn MA13w/MA52w lại **bật TĂNG** trong giai đoạn và không rời TĂNG trước cú sập 2018 lẫn Q1-2026 ⇒ khung càng dài **không** càng an toàn; đừng chậm hơn MA10w/MA40w.
- P0 trên kho thật chọn tham số ở **giữa vùng phẳng** này, không chọn điểm tối ưu.

**5. "Không xoay sở kịp" là chuyện BẤT NGỜ, không chỉ chuyện trễ.**
- Mức kích hoạt tuần (§3.5) tính được từ **sáng thứ Hai** ⇒ bạn đặt **cảnh báo giá** trên app môi giới ngay tại mức đó. Bước giảm rủi ro có cảnh báo tạm tính trung vị chỉ 1 phiên, nhưng mức tĩnh thì có cả tuần.
- Brief tối tới tay 21:00–23:15, có khi qua nửa đêm ⇒ **kéo bản 🚨 sớm ~15:10 (đang ở P2) lên P1b** để cảnh báo tới trước giờ ăn tối, task News Alert mỗi giờ ở 🖥️ đã có sẵn chỗ cắm.

**Không làm được bây giờ:** dùng vĩ mô/độ rộng để siết cầu chì khi nền xấu (vd 6% khi dài hạn BẤT LỢI, 8% bình thường) — breadth chỉ có lịch sử từ 06/2026, vĩ mô chưa chấm điểm. Ghi vào P2 để đo, không hứa trước.

---

## 8. Câu hỏi cần bạn chốt
1. **Nhãn:** bỏ "Bull — Risk-on / Bear — Risk-off"; tiêu đề brief là "Trung hạn" (xu hướng tuần); điểm 7 phiếu chỉ còn là "điểm kỹ thuật ngày".
2. **Luật Stance:**
   - Ép GIẢM khi nhịp chỉnh.
   - Ép TĂNG chỉ khi nhịp hồi + trung hạn TĂNG + 🚨 tắt.
   - Cấm TĂNG khi trung hạn chưa TĂNG; không bao giờ cấm GIẢM.
   - Bỏ momentum ±50 khỏi luật ép (vẫn vào lớp bảo vệ).
   - Hay phương án B: nhịp hồi × ĐI NGANG vẫn cho TĂNG?
3. **Chấp nhận Stance chậm hơn** (12 so với 8 phiên sau đỉnh), bù bằng lớp bảo vệ nhanh nhưng bật ~51% số phiên.
4. **Luật trung hạn tuần** (±2% quanh MA40 tuần + MA10w/MA40w; xuống 1 tuần, lên 2 tuần; rời TĂNG khi đóng dưới MA40 tuần), kèm độ trễ ~61 phiên.
5. **Kẹp band v1 từ P1** (không tăng % cổ phiếu khi trung hạn GIẢM hoặc 🚨 bật; hết kẹp thì ≤1 bậc/tuần) và 3 vá cơ học (1 bậc/lần, nút giữa phiên không ghi, pending vào history). Đây là thay đổi trên tham số bạn đã chốt.
6. **🚨:** ngưỡng 5% / −2.5% / −4%, dwell 5, neo đỉnh lúc bật; header chỉ hiện khi trung hạn chưa GIẢM; tin riêng gửi kênh chính hay kênh `news`; có làm bản sớm ~15:10 không.
7. **Bảng vĩ mô:** ngưỡng theo phân vị (P0 hiệu chỉnh), chấm theo tuần; dài hạn chỉ in trạng thái khi ≥3/5 trụ đo được.
8. **Kho dữ liệu chậm** `_meta/macro_slow.json` nằm ngoài trần 13 chỉ báo.
9. **P3:** có thay band v1 bằng v2 không; chọn A0 / A5+ / A6 sau ≥4 lần chốt tuần chạy bóng.
10. **Bản tin thứ Bảy:** có làm không; có đẩy brief tháng lên Telegram không (đảo tham số duyệt #4)?
11. **Brief sáng:** còn dùng không (hiện không có task lịch)?
12. **Header:** gọn 2 dòng (Tâm lý và điểm ngày chuyển vào thân); khối 🔭 nằm ngoài giới hạn 500 từ; brief có thể thành 2 tin.
13. **P0:** bạn chạy script replay (○) và thử backfill khối ngoại (○, ghi kho một lần).


**Khuyến nghị trả lời (05/10, sau §7.3)** — trả lời kiểu "theo khuyến nghị, trừ câu X" là đủ:

| # | Khuyến nghị | Cần bạn quyết thật? |
|---|---|---|
| 1 | Đồng ý bỏ Risk-on/off | ✅ |
| 2 | Luật chính, **không** phương án B (túi lướt ở §7.3 cho thấy B gần như không thêm lợi nhuận) | ✅ |
| 3 | Đồng ý, **kèm bảo vệ 2 mức** mềm/cứng (§7.3 mục 2) | ✅ |
| 4 | Đồng ý, **kèm cầu chì 8%** cho bước TĂNG→ĐI NGANG (§7.3 mục 1) | ✅ |
| 5 | Đồng ý kẹp + 3 vá (chặn được cú 15→~28→15% của 05/10) | ✅ |
| 6 | Ngưỡng như đề xuất; tin 🚨 gửi **kênh chính** (group Brief — là tín hiệu danh mục, không phải tin tức); **có** bản sớm ~15:10 và kéo lên P1b | ✅ kênh + thời điểm |
| 7 | Đồng ý | kỹ thuật |
| 8 | Đồng ý | kỹ thuật |
| 9 | Hoãn — quyết ở P3 khi có số chạy bóng | để sau |
| 10 | Có bản tin thứ Bảy; brief tháng lên Telegram tuỳ bạn | ✅ |
| 11 | Bạn cho biết còn đọc brief sáng không — không thì bỏ phần 🔭 cho brief sáng, bớt công P1 | ✅ |
| 12 | Đồng ý | kỹ thuật |
| 13 | Không phải quyết định — là việc ○ bạn chạy khi tôi viết xong script P0 | việc |

---

## Phụ lục: những điểm đã kiểm và sửa trong lúc thiết kế
- **Mức "lên TĂNG":** bản đầu chỉ giải ràng buộc giá. Ngày 28/08 mức đúng là ~1,842, không phải ~1,823; hiện tại là ~1,995, không phải ~1,840. Nay giải đủ 2 ràng buộc và có test.
- **Lớp bảo vệ:** bản đầu để 3 guard chống bắt đáy tắt khi ngắn hạn "chưa rõ", và cấm GIẢM ở 22 phiên sập. Nay bảo vệ là tập cha của hệ cũ, và GIẢM không bao giờ bị cấm.
- **Stance:** bản đầu vẫn ép TĂNG ở ô nhịp hồi × ĐI NGANG (9/30 phiên). Nay ô này không ép và cấm TĂNG.
- **Số liệu sai đã sửa:**
  - khối ngoại 20 phiên dao động −6,979 → +184 tỷ, không phải "−2,084 → −6,650";
  - "báo trước 5 tuần" thực ra là 1 phiên tạm tính;
  - hysteresis có dời bước xuống 07/2026;
  - A5+ bị đảo trong 20 phiên là 16%;
  - band v1 cũng đã nhảy.
- **Độ tin cậy vĩ mô "CAO":** chủ yếu do ngưỡng cố định. Theo phân vị, khối ngoại 60 phiên hôm nay là trung tính, và nhãn ra TRUNG BÌNH.
- **Va chạm guard đã xử lý:** mẫu 🔭 cũ dùng mức 2 chữ số không có trong danh sách đã biết (sẽ bị guard sửa), và dùng ⚡ trùng mục brief sáng.
- **Đường ghi:** bản đầu ghi state như tác dụng phụ trong `collect_context`. Nay là bước pipeline riêng, `collect_context` chỉ đọc, và tin đẩy có khử trùng.
- **Ước lượng công:** "3 ngày" cho P1 là không thực tế. Nay P1a + P1b ≈ 2 tuần công.

---

## Phụ lục B — Replay bộ phân loại hiện tại & các biến thể làm mượt (số thô)

Replay of the current `classify_regime` (baseline: breadth vote −1 as documented, A/D from the day-change proxy, Finhay NN; score on 02/10 = −6, the same as live).

**Lead-in.**
- Bear "Risk-off" ran most of 13/07–31/07, then a mixed stretch 03/08–12/08 (Sideways / Tích cực / Tiêu cực), then Bear "Risk-off" 13/08–20/08 (score −4 to −6, floor GIẢM).
- VNINDEX bottomed at 1,668.53 on 22/07 (higher low 1,726.69 on 19/08).

**15/08–30/09: 30 sessions.**
- The 5-level label changed **17 times**.
- The bias floor (which forces Stance) changed **16 times**: 11 days TĂNG, 11 days GIẢM.
- The header showed "Bull — Risk-on" on 6 days and "Bear — Risk-off" on 6 days.
- There were **2 full Risk-off↔Risk-on reversals**.
- Mean absolute score change was 2.0 per session.

| Date | Close (Δ%) | Score | Label | Note |
|---|---|---|---|---|
| 20/08 | 1,734.24 | −5 | Bear Risk-off | — |
| 21/08 | 1,768.12 (+1.95%) | −1 | Tiêu cực | — |
| **24/08** | **1,788.78 (+1.17%)** | **+4** | **Bull Risk-on, floor TĂNG** | 5 sessions / +3.6% after the 19/08 low; first close back above MA50 and MA200 |
| 25/08 | — | +3 | Tích cực | — |
| 26–28/08 | 1,821–1,832 | +4/+5/+4 | Bull | — |
| 03/09 | — | +2 | Tích cực | NN −1,520 bn |
| **04/09** | **1,853.08 (swing high)** | **+4** | **Bull** | — |
| 07/09 | — | 0 | Sideways | −1.70%, death cross |
| 08–10/09 | — | +1/+1/+3 | Tích cực | Floor TĂNG on 10/09 |
| 11/09 | — | 0 | Sideways | −1.86%; full floor GIẢM via momentum −53 |
| 14/09 | — | 0 | Sideways | — |
| 15/09 | 1,811.15 | +4 | Bull | — |
| 16–18/09 | — | +3/+2/+3 | Tích cực | — |
| 21/09 | — | −2 | Tiêu cực | — |
| 22/09 | — | +3 | Tích cực, TĂNG | — |
| 23/09 | — | −2 | Tiêu cực | — |
| **24/09** | **1,775.09 (−1.47%)** | **−5** | **Bear Risk-off** | 14 sessions / −4.2% after the peak |
| 25–29/09 | — | −2/−3/−3 | Tiêu cực, floor mostly GIẢM | — |
| 30/09–02/10 | — | −5/−6/−6 | Bear Risk-off | — |

**Against the price path.**
- Rally 19/08 → 04/09: +7.3% in 9 sessions.
- Correction 04/09 → 02/10: −6.2% in 20 sessions.
- The classifier caught neither turn early. Risk-on came after +3.6% off the low; Risk-off came after −4.2% off the high.
- In between it oscillated every 1–3 sessions.
- Acting on the 24/08 Risk-on and the 24/09 Risk-off returns −0.8%.

**Sensitivity.**
- With A/D removed: 12 label changes, and the header went Bull on 27/08 instead of 24/08; Risk-off still came on 24/09.
- With breadth neutral: 12 floor changes and the same ON/OFF dates.

**Wider window.** 01/06–02/10: 45 label changes in 87 sessions.

Same replayed inputs throughout. Full period is 2017-12..2026-10. Values in brackets are the 2021-10..2026-10 period, when all proxied inputs exist.
- Lag = median sessions from a zigzag pivot until the variant reaches the right side; hit = how many pivots it reached at all.
- "vs raw" = mean extra lag compared with RAW floor ±3.
- P&L uses exposure OFF/N/ON = 0/50/100%. Buy & hold: 7.0% CAGR / −45.3% max drawdown.

| Variant | Changes/yr | ON↔OFF reversals/yr | Undone ≤10 sessions | Lag at 10% turns: median (hit/32) | Extra lag vs raw | Lag at 15% turns: median (hit/13) | Episode 15/08–30/09 | P&L: CAGR / max DD / turnover |
|---|---|---|---|---|---|---|---|---|
| RAW floor ±3 (drives Stance) | 68.8 (82.9) | 9.0 (11.8) | 84% | 11.5 (28) | 0 | 13 (13) | 16 changes, 2 reversals; ON 24/08 → OFF 24/09 | 4.0% / −28.8% / 35 |
| RAW header Bull/Bear ±4 | 68.2 (77.7) | 5.6 (7.8) | 87% | 13 (25) | +3.0 | 18 (13) | 12 changes, 2 reversals; ON 24/08 → OFF 24/09 | 1.1% / −30.2% / 34 |
| RAW floor incl. momentum (proxy) | 88.4 (99.0) | 16.7 (20.7) | 86% | 9 (30) | −3.2 | – | 16 changes, 6 reversals; ON 24/08, OFF 11/09, 21/09, 23/09… | 3.1% / −31.4% / 47 |
| (a) 2-of-3 confirm | 29.7 (34.7) | 5.8 (6.2) | 60% | 15 (28) | +3.5 | 17 (13) | 7 changes, 2 reversals; ON 25/08 → OFF 28/09 | 6.0% / −18.1% / 15 |
| (a) 3-of-5 confirm | 21.0 (23.7) | 4.4 (5.4) | 50% | 16.5 (26) | +6.2 | 19 (13) | 7 changes, 2 reversals; ON 26/08 → OFF 29/09 | 5.5% / −22.4% / 11 |
| (a) 5-of-8 confirm | 12.9 (14.9) | 3.1 (3.8) | 25% | 19 (21) | +11.1 | 32 (12) | 2 changes, 1 reversal; ON 28/08 → OFF 01/10 | 5.6% / −19.8% / 7 |
| (b) Hysteresis on raw score, enter ±4 / exit 0 | 23.6 (28.1) | 5.6 (7.8) | 48% | 13 (25) | +2.7 | 18 (13) | 5 changes, 2 reversals; ON 24/08 → OFF 24/09 (direct jump) | 7.7% / −16.8% / 12 |
| (b) Same, one-step (must pass through Neutral) | 24.1 (28.5) | 5.6 (7.8) | 50% | 13 (25) | +2.8 | 18 (13) | 6 changes, 2 reversals; ON 26/08 → OFF 24/09 | 7.4% / −18.1% / 12 |
| (b) Hysteresis on EMA10 of score, enter ±2 / exit ±0.5 | 11.8 (12.9) | 3.7 (4.6) | 18% | 22.5 (24) | +11.1 | – | 3 changes, 1 reversal; ON 18/09 → OFF 01/10 | 3.5% / −28.1% / 6 |
| (b) Hysteresis on EMA10 of score, enter ±3 / exit ±1 | 8.6 (9.8) | 1.7 (2.2) | 21% | 20 (18) | +19.0 | – | Never ON; OFF 02/10 | 4.6% / −25.9% / 4 |
| (c) Minimum dwell 10 | 19.6 (21.3) | 5.1 (5.8) | 41% | 18 (27) | +7.0 | 20 (13) | 2 changes, 1 reversal; ON 27/08 → OFF 01/10 | 5.1% / −21.9% / 10 |
| (c) Minimum dwell 20 | 11.2 (11.6) | 3.1 (3.4) | 0% (by construction) | 21 (22) | +8.3 | – | ON 26/08 → OFF 28/09; stayed ON in the July slide until 29/07 | 6.3% / −22.7% / 6 |
| (a+c) 3-of-5 + dwell 10 | 15.1 (16.5) | 3.9 (4.4) | 32% | 18 (24) | +8.3 | 21.5 (12) | ON 04/09 (the peak) → Neutral 23/09 | 5.0% / −23.5% / 8 |
| (d) Close vs MA200 ±2% & MA50 vs MA200, 3-of-5 | 5.1 (4.2) | 0.7 (0.4) | 29% | 3 (17) | +13.9 | 62 (10) | ON 28/08 → Neutral 09/09, never OFF | 5.5% / −32.5% / 2.6 |
| (d) Same + MA50 20-session slope, 3-of-5 | 5.6 (5.2) | 0.7 (0.4) | 20% | 10.5 (14) | +18.7 | 62 (10) | NEUTRAL throughout (since 16/07) | 4.2% / −31.6% / 2.8 |
| (d) Weekly: 10-week vs 40-week average + close vs 40-week ±2% | 4.9 (4.8) | 0.9 (1.0) | 30% | 14 (15) | +20.5 | 67 (9) | NEUTRAL 17/07 → 01/10, OFF 02/10 | 7.2% / −20.7% / 2.4 |
| (d) Slow composite (MA200 band, MA50/MA200, 60-session return, NN 20-session sum) | 8.4 (9.6) | 1.2 (1.4) | 26% | 17.5 (14) | +19.1 | 59 (10) | Never ON; OFF 18/08, Neutral 25/08, OFF 15/09 | 3.8% / −34.7% / 4.2 |
| (d) MA50 vs MA200 only | 1.2 (1.4) | 1.2 | 0% | 0 (18) | +4.8 | – | ON until death cross 07/09, then OFF | 7.0% / −29.4% / 1.2 |
| (e) Alert: drawdown ≥5% from 20-session high | 3.7 onsets/yr, 53 alert-days/yr | n/a | n/a | n/a | n/a | n/a | Fired 01/10 only (15/07 and 28/01/26 earlier) | P(further −3% within 20 sessions) 61% vs 40% base |
| (e) Alert: 1-day ≤ −2.5% or 3-day ≤ −4% | 4.7 onsets/yr | n/a | n/a | n/a | n/a | n/a | Not fired 15/08–30/09 (fired 21/07) | 59% vs 40% |
| Layered: weekly (d) 80/50/20 + 3-of-5 tilt ±15pp + drawdown alert −20pp | ~11 exposure moves in the episode, 15pp steps | – | – | – | – | – | 50→35→65→50→65→50→65→50→35→15→0% | 6.0% / −16.1% / 6.6 |

**Parameter grid (step5_grid).**
- Every hysteresis setting (enter 3–5, exit +1..−1) and every N-of-M setting (2-of-3 up to 5-of-8) still went ON in late August, with 1–2 reversals in the episode.
- Among medium-term rules, ±1–2% bands without the slope condition went ON from 28/08 to 08/09. The slope condition, a ±3% band, or the weekly rule (any band from ±1% to ±3%) stayed Neutral.

## Recommendation
## 1. Stop presenting a daily vote count as "Risk-on/Risk-off"
Today's label is a 1-session state with 1-session wording. Its median run is 1 session, and it changes about 112 times a year.

## 2. Use three layers, each with its own rule and its own job

**Ngắn hạn (1–10 sessions): the current 7-vote score, plus a state machine.**
- Rule: hysteresis enter ±4 / exit at 0, with a one-step rule (ON↔OFF must pass through at least one session of Neutral).
- Effect since 2021-10: changes fall from 83 to 28.5 a year, reversals from 11.8 to 7.8 a year, and changes undone within 10 sessions from 87% to 53%. Extra lag is only +2.8 sessions at 10% turns.
- If you want it calmer, add 2-of-3 confirmation on top: 23 changes and 5.3 reversals a year, about +3 to +4 sessions more lag.
- This state, not the raw ±3 score, should drive `_bias_floor_dir`, Stance ngày mai and the watchlist direction.
- Show it as "Ngắn hạn: TĂNG — phiên thứ N (từ dd/mm)".
- Be honest about its limit: it still goes ON 26/08 → OFF 24/09 in this episode. No smoothing of these inputs avoids that.

**Trung hạn (1–3 months): this becomes the headline "Risk-on / Trung tính / Risk-off".**
- Rule, evaluated weekly on the last session of the week:
  - Risk-on = weekly close > 40-week SMA × 1.02 AND 10-week SMA > 40-week SMA.
  - Risk-off = the mirror image.
  - Otherwise "Trung tính / đi ngang".
- Daily equivalent if a weekly cadence is not wanted: close vs MA200 ±2% AND MA50 vs MA200 AND MA50 20-session slope agreeing, with 3-of-5 confirmation.
- Stability: about 5 changes a year, ≤1 reversal a year, never ON in Aug–Sep 2026. It reads Neutral 17/07 → 01/10 and Risk-off on 02/10.
- Explicit cost the user must accept:
  - Median 62–67 sessions late at 15% turns, and 3–4 of 13 such turns never confirmed.
  - It stayed Risk-on through the Q1-2026 −16% slide (13/01 → 23/03).
- That cost is why the alert layer exists. This layer should set the base equity weight and the advice on positions already held.

**Cảnh báo rủi ro nhanh: separate line, never flips the medium-term state.**
- Triggers: drawdown ≥5% from the 20-session closing high, OR 1-day ≤ −2.5% / 3-day ≤ −4%.
- About 4–5 onsets a year. P(further −3% within 20 sessions) is about 60% against a 40% base, but there is no directional edge: the median 20-session return is still positive.
- It fired 28/01/26 and 06/03/26 during the Q1 slide the medium layer missed.
- Wording: "rủi ro ngắn hạn tăng — cân nhắc giảm 10–20% tỷ trọng / siết stop", not "chuyển Risk-off".

**Dài hạn (6–12 months):** not testable with price-only data here. Leave it to the macro/valuation layer proposed by the other research. Do not reuse the daily inputs for it.

## 3. Turn state into gradual exposure, not a switch
- Medium-term state sets the base weight: 80 / 50 / 20%.
- Short-term state tilts it ±15 percentage points.
- An alert cuts 20 percentage points.
- Illustrative 2017–2026 result: 6.0% CAGR, −16.1% max drawdown, turnover 6.6 a year. Compare the raw floor mapped the same way (4.0% / −21.8% / turnover 21) and a constant 50% (3.9% / −25.4%).
- In the episode exposure moved in 15-point steps instead of jumping between 20% and 80%.

## 4. Tradeoff summary

| Choice | Flips per year | Lag at real turns | Aug–Sep 2026 |
|---|---|---|---|
| Fast layer | ~25–30 | +3 sessions vs today | Still round-trips |
| Medium layer | ~5 | +50–60 sessions at 15% turns | Stays Neutral |
| Alert layer | — | Covers the medium layer's blind spot | — |

There is no single rule that is both early and stable. That is the case for showing three labelled horizons instead of one.

## 5. Before shipping
- Re-run this replay on the real warehouse (breadth % above MA200 and A/D for every date) and on the memory DB ctx. Do it on any machine (○), since `data_warehouse` is shared through Dropbox.
- Fix parameters before looking at Aug–Sep again.
- Track flips per 20 sessions as a KPI and score the medium-term call at 20/60 sessions.
- Choosing the band/slope values is the user's decision: in this episode the result hinges on them.

## Caveats
- One motivating episode (n=1). The variants that stayed defensive in Aug–Sep did so because of a slope or band choice. The ±1–2% MA200 rule without a slope condition went ON from 28/08 to 08/09, so the episode outcome is parameter-fragile. The robust findings are the raw noise level, the fact that smoothing cannot prevent the round trip, and the long lag of slow states at 15%+ turns.
- Parameters for the medium-term rules are conventional (MA200, ±2%, 3-of-5, 10w/40w), but they were picked after the episode was known. Treat the episode result as illustration, not validation.
- Breadth % above MA200 has no history here. I held its vote at −1 from 2026-06-01, based on the documented 18% (16/06), 11% (about 12/08) and 9% (02/10), and absent before that. The pre-June-2026 score therefore has 6 votes, and only 5 before 2021-10 (no NN). Full-history raw flip counts likely understate the live 7-vote noise.
- A/D is a proxy derived from the index day change (+1 above +0.52%, −1 below −0.75%). It is calibrated on a single point (02/10). The notes contain a counter-example: 12/08, index +1.11%, real A/D 1.08. The proxy is mechanically tied to the day change and may inflate how uniform the flip rate looks. With A/D removed, episode label changes drop from 17 to 12 but the ON/OFF dates are unchanged.
- NN is Finhay's VNINDEX total including put-through, not the repo's full-market source. It is missing before 2021-10-05 and treated as absent there, mirroring the repo's nn==0 skip.
- Momentum lacks news (.15) and macro (.10), so the proxy is more extreme than live (−93 vs −61 on 02/10). The flip counts for 'floor incl. momentum' are overstated.
- P&L is illustrative only: price index without dividends, cash at 0%, 0.15% per unit of turnover, next-session execution, one market over 8.8 years. With breadth at 9–18%, most stocks missed the August rally, so the stock-level cost of acting on 'Risk-on' is probably larger than the index numbers show. Not measured.
- Zigzag turning points are defined with hindsight. The lag metric scores 'already on the right side at the pivot' as 0, which flatters slow rules that never flipped; read it together with the hit counts.
- The replay is not the record of what was actually sent. Real per-day regime/stance history (memory DB context_json, allocation_state, Telegram export) is not in this sandbox. Briefs for 21/09 and 28/09 were not sent, 22/09 was blank and 30/09 was lost (re-sent 01/10), and the writing engine changed during the window.
- The long-term (6–12 month) layer was not tested here: it would need valuation and macro history, not price alone.