# Mở rộng dashboard sang VÀNG · DẦU · USD — THIẾT KẾ + P0 ĐO NGUỒN

> **Trạng thái 09/10/2026 tối: P0 XONG — 🖥️ desktop đã chạy `probe_assets.py --mcp` (19:51, §4b).
> User thêm CHUẨN ĐỘ TƯƠI (§4d): chỉ số quốc tế + tin liên quan phải có TRONG NGÀY ⇒ P0b
> `scripts/probe_nowcast.py` đo ước tính trong ngày cho 3 chuỗi chậm, CHỜ 🖥️ chạy. Bảng nguồn §4c chờ
> duyệt sau P0b; P1 CHƯA code.**
>
> **User chốt 09/10:**
> 1. Giao diện: **tab riêng** "🪙 Hàng hoá & Tiền tệ".
> 2. MCP: "tuỳ Claude, hiện dùng MCP chưa mất chi phí" ⇒ Claude chọn **LAI**: MCP Finhay/SSI làm nguồn
>    NGÀY (tươi trong phiên, đủ mở/cao/thấp/đóng, có giá đại lý vàng nội); Python (FRED/stooq) nạp lịch
>    sử nhiều năm + làm dự phòng khi MCP lỗi; mỗi đêm đối chiếu hai đường. Chốt hẳn SAU khi đọc kết quả
>    probe (độ sâu, độ ổn định trên máy thật). Chi phí MCP trong sổ là QUY ĐỔI giá API — gói thuê bao
>    trừ hạn mức, không trừ tiền.
> 3. Vàng trong nước: lấy **cả 5 đại lý** Finhay có (SJC · PNJ · DOJI · BTMC · BTMH, miếng + nhẫn = 10 sản
>    phẩm, thêm một sản phẩm gần như không tốn gì). Mặc định hiển thị SJC miếng · SJC nhẫn · PNJ nhẫn,
>    các sản phẩm còn lại ở bảng phụ.
> 4. Danh sách cổ phiếu liên kết: theo §3 (user đồng ý danh sách gốc, Claude được thêm bớt).

## 1. Mục tiêu

Dashboard và brief hiện chỉ có CỔ PHIẾU + một rổ vĩ mô nhỏ. Vàng, dầu, USD tác động thẳng tới cổ phiếu VN
(PNJ, nhóm dầu khí, hàng không, xuất khẩu, khối ngoại) nhưng hệ thống chỉ có TIN, gần như không có SỐ:
prompt brief còn lấy "giá dầu Brent/WTI" làm VÍ DỤ cho thứ đang thiếu (`vnstock_brief.py:308`, `:396`).

Đích: một kho chuỗi giá tài sản riêng + tab xem + chỉ số suy ra có nghĩa với VN (chênh SJC, dư địa tới
trần tỷ giá, độ nhạy cổ phiếu) — rồi mới tới brief/cảnh báo (P5, duyệt riêng). Sau ba tài sản này, khung
mở được cho bạc/đồng/khí (Finhay có XAG · HG · NG) hay thép/phân bón nếu có nguồn.

## 2. Hiện trạng (đã kiểm code 09/10)

| Tài sản | Đang có | Thiếu / sai |
|---|---|---|
| Vàng | `vnstock_gold.py`: spot USD/oz, 2 endpoint free, chụp 1 điểm/ngày, trần 400 (`:37`); chỉ ở sub-tab 🧭 Phân bổ + proxy lớp Vàng của scorecard; KHÔNG vào registry 13 chỉ số (nguyên tắc P6) | Không OHLC, không chuỗi dài, không giá vàng NỘI. Nhãn cứng "premium SJC ~15-20%" (`vnstock_gold.py:39`) — đo 09/10 chỉ còn **~9–11%** ⇒ phải TÍNH, không ghi cứng |
| USD | `usdvnd` trong registry vĩ mô (er-api → currency-api, cross-check VCB qua PDF VBMA), trần 60 điểm (`vnstock_macro.py:63`); tỷ giá trung tâm từ bản tin TUẦN SBV (`vnstock_sbv.py:51`) | Không chỉ số USD thế giới, không chuỗi dài, không giá VCB theo ngày, không "còn bao xa tới trần biên độ" |
| Dầu | Không có số. Tin dầu đi đường RSS từ khoá | Ghi chú khảo sát 07/2026 "dầu không có API free" (CLAUDE-NOTES:1767) **sót FRED** — FRED (key đã có cho `us10y`) có Brent `DCOILBRENTEU` + WTI `DCOILWTICO` |

## 3. Khung nghiên cứu từng tài sản — xem gì, nối với cổ phiếu nào

Danh sách cổ phiếu là GIẢ THUYẾT kênh truyền dẫn; P4 ĐO bằng tương quan/beta 60 phiên trên kho giá sẵn có,
mã nào không thấy quan hệ thì nói thẳng, không giữ vì "nghe hợp lý".

### 3.1 Vàng
- **Thế giới (XAU, USD/oz):** chịu lợi suất thực Mỹ (US10Y − kỳ vọng lạm phát; `us10y` đã có trong
  registry), chỉ số USD, NHTW mua ròng, rủi ro địa chính trị.
- **Trong nước:** vàng miếng SJC do Nhà nước độc quyền thương hiệu ⇒ giá tách khỏi thế giới; **chênh
  SJC − thế giới quy đổi** là thước đo cung cầu nội + chính sách (NHNN bán can thiệp). Nhẫn trơn bám thế
  giới sát hơn. Chênh mua–bán của đại lý cho biết thị trường căng hay lỏng.
- **Hiển thị:** XAU; giá mua/bán 10 sản phẩm đại lý (triệu đ/lượng); % chênh miếng/nhẫn so thế giới quy
  đổi (theo tỷ giá thị trường VÀ tỷ giá bán VCB — ghi rõ dùng cái nào); chênh mua–bán.
- **Cổ phiếu:** PNJ (bán lẻ trang sức — biên và tồn kho chịu giá vàng). Giả thuyết phụ cần đo: vàng tăng
  mạnh ⇒ tiền nhỏ lẻ rời chứng khoán.

### 3.2 Dầu
- **Brent** = chuẩn cho dầu thô VN (giá bán dầu thô/khí neo Brent); **WTI** = chuẩn Mỹ. Chênh Brent−WTI
  phản ánh cung Mỹ/xuất khẩu. Động lực: OPEC+, tồn kho EIA, địa chính trị (eo Hormuz), chu kỳ cầu, USD.
- **VN:** giá xăng bán lẻ điều hành theo kỳ (Bộ Công Thương) ⇒ CPI nhóm giao thông. Nguồn giá xăng VN
  CHƯA có — để dành (không thuộc P0).
- **Hiển thị:** Brent, WTI (đóng cửa + mở/cao/thấp khi có), chênh Brent−WTI, thay đổi 1N/1T/1Th/YTD.
- **Cổ phiếu:** thượng nguồn PVD · PVS (giá dầu ⇒ capex khoan/dịch vụ); khí GAS (giá bán neo dầu);
  lọc dầu BSR (crack spread, tồn kho); phân phối PLX · OIL (lãi/lỗ tồn kho khi giá đổi); vận tải PVT;
  phía CHỊU chi phí nhiên liệu HVN · VJC; *bổ sung của Claude:* DPM · DCM (khí đầu vào phân đạm).

### 3.3 USD
- **Thế giới:** ICE DXY (rổ 6 đồng, EUR ~58%) ≠ chỉ số USD rộng của Fed `DTWEXBGS` (rổ thương mại rộng,
  có CNY/MXN) — HAI chỉ số khác nhau, UI phải ghi đúng tên cái đang hiện.
- **VN:** NHNN công bố **tỷ giá trung tâm** mỗi ngày, NHTM giao dịch trong biên **±5%** ⇒ trần = trung
  tâm × 1,05. Tỷ giá bán của NHTM (VCB) áp trần = áp lực tỷ giá thật. Kênh: chênh lãi suất VND−USD
  (liên ngân hàng + Fed funds đã có trong registry), cán cân thương mại (đã có), dòng vốn ngoại (đã có).
- **Hiển thị:** USD/VND thị trường · trung tâm · VCB mua/CK/bán; **% còn tới trần**; chỉ số USD thế giới.
- **Cổ phiếu:** xuất khẩu hưởng lợi USD mạnh VHC · ANV · *bổ sung:* MSH (dệt may); chi phí/nợ USD HVN ·
  VJC. Khối ngoại bán ròng khi USD mạnh — đo bằng chuỗi NN ròng sẵn có (`vnstock_foreign_flow`).

## 4. Bản đồ nguồn — số đo 09/10 (qua connector trong phiên Claude, KHÔNG phải máy thật)

| Nguồn | Có gì | Tươi | Sâu | Ghi chú |
|---|---|---|---|---|
| **Finhay MCP** `get_commodity_history` | XAU · XAG · HG · **CL** · **BZ** · NG, nến ngày mở/cao/thấp/đóng | trong phiên (nến hôm nay đang chạy) | XAU có ở 01/2025, RỖNG 01/2020; CL rỗng 01/2024 ⇒ ~1–2 năm | probe đo chính xác 5 cửa sổ |
| **Finhay MCP** `get_forex_history` | USDVND · EURUSD · USDJPY · GBPUSD | trong phiên | USDVND chỉ từ **03/08/2026** | có cả ngày nghỉ (01–03/09 đứng giá) |
| **Finhay MCP** `get_dealer_product_*` | vàng miếng + nhẫn của SJC/PNJ/DOJI/BTMC/BTMH, giá mua/bán | 19:20 cùng ngày | SJC miếng có ở 01/2025 | đơn vị **nghìn đ/chỉ** (14.480 ⇔ 144,8 tr/lượng; 01/2025 8.620 ⇔ 86,2 tr — khớp thị trường) |
| **SSI MCP** `foreign_currency_converter` | tỷ giá theo NGÂN HÀNG (VCB, BID, ACB, TCB, AGRB, SCB, **SBVN**) | ngày | 730 ngày | VCB 09/10: mua 25.680 · CK 25.710 · bán 26.090 |
| FRED | Brent, WTI, `DTWEXBGS` | trễ vài ngày (EIA/Fed cập nhật theo tuần) — probe đo | hàng chục năm | key có sẵn |
| goldprice.org / gold-api.com | XAU hiện tại | tức thời | 0 (pipeline tự chụp) | đang chạy trong pipeline |
| er-api / currency-api… | USD/VND hiện tại | tức thời | 0 | đang chạy |
| stooq CSV | xauusd, cb.f, cl.f, **dx.f (DXY hợp đồng tương lai ICE)**, usdvnd | ? | ? | ứng viên — probe đo; có thể đòi hạn mức/khoá |
| Yahoo chart | GC=F, BZ=F, CL=F, DX-Y.NYB, VND=X | ? | ? | KHÔNG chính thức — chỉ xếp cuối |
| sjc.com.vn / vietcombank.com.vn | giá SJC / tỷ giá VCB trực tiếp | ? | ? | endpoint ứng viên — probe đo |
| vnstock_data (Golden) / vnstock | ? hàng hoá / tỷ giá | ? | ? | probe dò module + chữ ký hàm, gọi thử |

**Phát hiện 09/10 (cần đối chiếu trên máy thật):**
- **SBVN trong SSI = giá USD tại Sở giao dịch NHNN.** Mua 24.398 · bán 26.860 ⇒ (mua+bán)/2 = **25.629**;
  25.629 × 1,05 = 26.910 = bán + 50, 25.629 × 0,95 = 24.348 = mua − 50 — khớp CẢ HAI phía ⇒ tỷ giá trung
  tâm NGÀY suy ra được từ SSI (bản tin SBV hiện chỉ cho 1 điểm/TUẦN). VCB bán 26.090 ⇒ còn **~3,1%** tới
  trần; thị trường (Finhay) 25.881 ≈ trung tâm +1,0%. Probe tự đối chiếu với `fx_central` bản tin tuần.
- **Chênh SJC miếng:** bán 144,8 tr/lượng vs XAU 4.182,09 × 25.881 × 1,20565 oz/lượng = 130,5 tr ⇒
  **+11,0%** (dùng VCB bán 26.090 ⇒ +10,1%; giá mua 141,8 ⇒ +8,7%). Nhãn cứng "~15–20%" là lỗi thời.
- **Độ sâu MCP ngắn** (USDVND ~2 tháng, XAU ~2 năm) ⇒ chuỗi dài bắt buộc từ nguồn Python.

## 4b. Kết quả P0 trên MÁY THẬT (🖥️ PICHU 09/10 19:51, `--fast` 3.335 passed trước đó)

| Nguồn | Kết quả | Ghi chú |
|---|---|---|
| FRED `DCOILBRENTEU` / `DCOILWTICO` | ✅ 125,44 / 96,24 (06/10, trễ 3d), từ 1987 / 1986 | **GIAO NGAY EIA**, không phải hợp đồng tương lai (xem cảnh báo dưới) |
| FRED `DTWEXBGS` | ✅ 121,38 (02/10, trễ 7d), từ 2006 | chỉ số rộng của Fed |
| goldprice.org | ❌ HTTP 403 | **nấc 1 của `vnstock_gold` đã chết** — pipeline đang sống nhờ nấc 2 |
| gold-api.com | ✅ 4.180 (giao ngay) | |
| er-api · 2 nấc currency-api | ✅ 25.868 · 25.922 · 25.835 | |
| exchangerate.host | ❌ payload không có VND | **nấc 2 của `usdvnd` đã chết** (dịch vụ đòi key) |
| stooq | ❌ trả trang HTML (chặn) | bỏ |
| Yahoo GC=F · BZ=F · CL=F · DX-Y.NYB · VND=X | ✅ trễ 0d, từ 2000 · 2007 · 2000 · **1971** · 2003 | không chính thức; DX-Y.NYB = **DXY thật của ICE** |
| sjc.com.vn | ✅ bán 144.800 / mua 141.800 nghìn đ/lượng, TP.HCM; ngày 2025-10 ✓ 2021-10 ✓ | chính thức, tra theo ngày |
| vietcombank.com.vn api | ✅ bán 26.070 · CK 25.690 · TM 25.660; 2025-10 ✓ 2021-10 ✓ | chính thức, tra theo ngày |
| `vnstock_data` `CommodityPrice` (spl) | ✅ `gold_vn` mua/bán 140.800/143.800 · `gold_global` OHLC 4.206,7 · `oil_crude` OHLC 90,95 | gold_global = **HĐTL vàng** (khớp GC=F), oil_crude = **WTI HĐTL** (khớp CL=F); gold_vn chưa rõ sản phẩm (thấp hơn SJC 1.000) |
| `vnstock_data` `Macro` (mbk) | ✅ `exchange_rate` 658 dòng dạng dài, có "Tỷ giá trung tâm (từ 04/01/2016)" | nguồn LỊCH SỬ tỷ giá trung tâm — dùng kiểm công thức SBVN |
| `vnstock_data` `Macro` (asean) | ✅ center/vcb/market rate theo ngày | **dừng ở 10/09 (trễ 29d)** |
| `vnstock` misc | `sjc_gold_price(date)` · `btmc_goldprice()` · `vcb_exchange_rate(date)` | không cần — đã gọi thẳng nguồn gốc |
| MCP Finhay (36/36 tool, 54s, quy đổi $0,25) | ✅ trễ 0d cho XAU · BZ · CL · USDVND · 10 sản phẩm vàng | độ sâu: XAU từ 01/2025; BZ/CL/USDVND **rỗng ở 01/2025**; **SJC miếng có từ 01/2015** |
| MCP SSI VCB · SBVN | ✅ 26.090 · trung tâm suy ra 25.629 (trần 26.910) | |

**Ba điều phải thiết kế theo:**
1. **Cùng tên nhưng KHÁC công cụ.** Vàng: giao ngay 4.180–4.183 (gold-api, Finhay) vs HĐTL 4.206 (Yahoo,
   vnstock_data) — lệch 0,6%. Dầu: Brent HĐTL 102,9–103,1 (Finhay, Yahoo) vs Brent giao ngay EIA **125,44**
   (FRED, 06/10) — lệch ~22%; WTI HĐTL 90,9–91,1 vs giao ngay EIA 96,24. ⇒ Mỗi chuỗi trong kho = MỘT công
   cụ; nguồn của một chuỗi phải báo cùng công cụ đó, đối chiếu lệch quá ngưỡng ⇒ cờ, không nối. Chênh giao
   ngay − HĐTL tự nó là chỉ báo (thị trường vật chất căng) — nhưng phải so CÙNG NGÀY trước khi kết luận.
2. **Độ sâu MCP ngắn trừ vàng miếng SJC** ⇒ lịch sử dầu/USD lấy từ Yahoo/FRED/vnstock_data; MCP làm nguồn NGÀY.
3. **Hai nấc chết đang nằm im trong pipeline** (goldprice.org 403, exchangerate.host không còn VND) —
   không gây lỗi vì nấc sau gánh; dọn ở P1 khi kho mới thay `vnstock_gold`.

## 4c. Bảng nguồn đề xuất cho P1 — CHỜ DUYỆT

Đơn vị lưu: vàng nội **VND/lượng** (Finhay nghìn đ/chỉ × 10.000; SJC trực tiếp nghìn đ/lượng × 1.000),
vàng TG USD/oz, dầu USD/thùng, tỷ giá VND/USD.

| Khoá | Công cụ | Nguồn ngày (chính) | Dự phòng ngày | Lịch sử (backfill 1 lần) | Đối chiếu |
|---|---|---|---|---|---|
| `XAU` | vàng giao ngay | MCP Finhay XAU (OHLC) | gold-api.com | Finhay (từ 01/2025) + 51 điểm kho cũ | gold-api ±0,5% |
| `GOLD_<ĐẠI LÝ>_<MIẾNG/NHẪN>` ×10 | giá mua/bán đại lý | MCP Finhay dealer | SJC miếng: sjc.com.vn | Finhay dealer (SJC miếng từ 2015; 9 sản phẩm còn lại đo khi backfill) | SJC miếng: sjc.com.vn ±0,5% |
| `BRENT` | Brent HĐTL tháng gần | MCP Finhay BZ | Yahoo BZ=F | Yahoo BZ=F (từ 2007) | Yahoo ±1% |
| `WTI` | WTI HĐTL tháng gần | MCP Finhay CL | Yahoo CL=F | vnstock_data `oil_crude` (gói trả phí) → Yahoo | vnstock_data/Yahoo ±1% |
| `BRENT_SPOT` · `WTI_SPOT` | giao ngay EIA | FRED (trễ ~3d) | — | FRED (từ 1986–87) | — (chuỗi chính thức) |
| `DXY` | ICE DXY | Yahoo DX-Y.NYB | — | Yahoo (từ 1971) | — |
| `USD_BROAD` | chỉ số USD rộng Fed | FRED `DTWEXBGS` (trễ ~7d) | — | FRED (từ 2006) | — |
| `USDVND` | tỷ giá thị trường | MCP Finhay USDVND | er-api → currency-api | Yahoo VND=X (từ 2003) | er-api ±0,5% |
| `USDVND_VCB` | VCB mua TM/CK/bán | vietcombank.com.vn api | MCP SSI VCB | VCB api theo ngày (2 năm ≈ 500 lượt, giãn 0,3s) | SSI VCB ±0,3% |
| `USD_CENTRAL` | tỷ giá trung tâm NHNN | MCP SSI SBVN, (mua+bán)/2 | bản tin tuần SBV | vnstock_data mbk "Tỷ giá trung tâm" (từ 2016) | **kiểm công thức** SBVN vs mbk trên ~2 năm SSI cho phép |

Bước pipeline: `assets` (Python, sau `macro`) + `assets-mcp` (sau brief, như `mcp-enrich`); MCP một lượt/
đêm ~16 tool cửa sổ 10 ngày (ghi đè bar trùng). Yahoo không chính thức ⇒ mọi chuỗi phụ thuộc Yahoo có
nguồn ngày khác (trừ DXY) và badge doctor báo tuổi.

## 4d. Chuẩn độ tươi (user 09/10) + giải pháp cho 3 chuỗi chậm

> User: "những chỉ số liên quan đến quốc tế như vàng, USD, dầu và các tin tức liên quan phải có trong
> ngày hoặc tần suất cập nhật thấp hơn thì mới đạt yêu cầu."

**Luật:** chuỗi nào nguồn gốc chậm hơn một ngày ⇒ CHỈ được hiện dưới dạng **ước tính trong ngày có sai
số đã đo**, hoặc KHÔNG hiện. Không bao giờ hiện số cũ nhiều ngày như số hiện hành.

| Chuỗi | Đạt chuẩn? | Cách đạt |
|---|---|---|
| Vàng TG giao ngay, 10 sản phẩm vàng nội, Brent/WTI HĐTL, DXY, USD/VND thị trường, VCB, trung tâm (SBVN) | ✅ trễ 0d | nguồn sống trong ngày (§4c) |
| Brent / WTI giao ngay EIA | ❌ trễ 3–9d (EIA công bố theo tuần) | (1) **ước tính** = số EIA gần nhất × biến động HĐTL tháng gần từ ngày đó; (2) **đường cong HĐTL** M1…M8 + chênh M1−M2, M1−M6 thời gian thực = thước đo "vật chất căng" thay vai trò giá giao ngay; (3) giá rổ OPEC nếu feed sống (trễ 1 ngày — chỉ tham khảo) |
| Chỉ số USD rộng (Fed) | ❌ trễ ≤7d (H.10 theo tuần) | **tự tính hằng ngày**: trọng số chính thức Fed (26 tiền tệ, có VND) × tỷ giá ngày currency-api, neo số Fed gần nhất; DXY (Yahoo) vẫn là thước USD thời gian thực |
| Tin vàng/dầu/USD | ✅ mỗi giờ 24/7 (`vnstock_news_alert`, Bloomberg/Reuters/FT/CNBC/Fed…) | P5: thêm nguồn chuyên hàng hoá/FX vào `SOURCES` |

Không có nguồn MIỄN PHÍ nhanh hơn cho chính các chuỗi chậm: Dated Brent là định giá Platts/Argus (trả
phí); EIA API trực tiếp cùng nhịp tuần như FRED; Bloomberg Dollar Spot trả phí.

**Ngưỡng sai số** (`probe_nowcast.THRESHOLDS`, đo bằng p90 |sai|): USD rộng ở h=5 phiên ≤0,15% ⇒ hiện
như số · ≤0,40% ⇒ hiện kèm dải sai số · lớn hơn ⇒ không hiện. Dầu giao ngay ở h=3 phiên, 120 ngày gần
nhất: ≤1% / ≤3% / lớn hơn. Chênh giao ngay − HĐTL ~22% (Brent, §4b) ⇒ ước tính dầu có thể KHÔNG đạt —
khi đó dashboard hiện đường cong + số EIA kèm NGÀY, không hiện ước tính.

**Nhịp cập nhật trong ngày (cho P1):** nguồn Python sống (Yahoo, gold-api, er-api, VCB, SJC, FRED cho
neo) chạy MỖI GIỜ — ghép vào task `VnStock News Alert` mỗi giờ sẵn có trên 🖥️ desktop hoặc task riêng;
MCP Finhay/SSI 3–4 lượt/ngày giờ VN (vàng đại lý đổi giá nhiều lần/ngày; user: MCP chưa tốn phí); tab
có nút "Cập nhật ngay" gọi nguồn Python sống. Kho ghi bởi một máy (desktop) như mọi bước khác.

**P0b — đo:** 🖥️ `python scripts/probe_nowcast.py` (chỉ đọc; 4 phần usd · oil · curve · opec; thử lệch
pha −1/0/+1 ngày vì giờ chốt tỷ giá khác nhau; in "ƯỚC TÍNH <ngày>" + đánh giá theo ngưỡng).

## 5. Kiến trúc đích (P1–P4)

**Nguyên tắc (giữ đúng luật repo):**
1. Kho RIÊNG `data_warehouse/assets/<KHOÁ>/<YYYY>.parquet` — cột `date, open, high, low, close, bid, ask,
   source, fetched_at`. KHÔNG vào registry 13 chỉ số vĩ mô (đã chốt trần) và không đụng `prices/` cổ phiếu.
2. Ladder nguồn theo từng chuỗi, sanity range, lỗi ⇒ GIỮ số cũ, không bịa; mỗi điểm ghi `source`.
3. MCP chỉ qua `vnstock_claude_cli.complete_mcp` (connector gắn tài khoản, Python không gọi thẳng); số
   đọc từ `tool_result`, không qua chữ model.
4. Mỗi bước có kill-switch env, badge doctor, ghi nguyên tử, test + whitelist `--fast`, docs.
5. Kho đi Dropbox ⇒ bước ghi chạy ở pipeline 🖥️ desktop; laptop chỉ đọc (tránh conflicted copy).

**Module:**
- `vnstock_assets.py` — registry (1 dòng / chuỗi: khoá, nhãn, đơn vị, ladder, sanity), store đọc/ghi
  Parquet theo năm, `refresh()`, `load(key, days)`, chuỗi suy ra: `sjc_premium_pct` (mỗi sản phẩm vàng),
  `gold_vnd_luong`, `usd_central` (từ SBVN), `usd_ceiling_room_pct`, `brent_wti_spread`. Backfill một lần
  từ FRED (+ stooq nếu probe thấy sống).
- `vnstock_assets_mcp.py` (hoặc trong `vnstock_assets`) — một lượt `complete_mcp` mỗi đêm: Finhay 4 chuỗi
  + 10 sản phẩm vàng (cửa sổ 10 ngày, ghi đè bar trùng) + SSI VCB/SBVN; đối chiếu với nguồn Python,
  lệch > ngưỡng ⇒ cờ, không ghi đè lặng lẽ.
- `dashboard/assets_tab.py` — tab "🪙 Hàng hoá & Tiền tệ" thêm vào `_TAB_OPTIONS` (`vnstock_dashboard.py:3712`),
  pills con Vàng · Dầu · USD · Liên kết cổ phiếu; ô số (giá, Δ1N/1T/1Th/YTD, nguồn + ngày), biểu đồ giá
  (nến khi có OHLC, plotly như `dashboard/macro_tab.py:118`), biểu đồ chênh; CHỈ đọc kho.
- Pipeline: bước `assets` sau `macro`/`gold` (`VNSTOCK_ASSETS`), bước MCP chạy sau brief như `mcp-enrich`
  (`VNSTOCK_ASSETS_MCP`). `vnstock_gold` giữ nguyên tới khi P1 chuyển nguồn của nó sang kho mới (proxy
  scorecard không đổi hành vi).
- Doctor `assets`: tuổi từng chuỗi + số cờ lệch nguồn; dưới sàn mẫu thì ok kèm n=… (luật brief_watch).

## 6. Pha (điểm dừng nào cũng dùng được)

| Pha | Việc | Máy | Điểm dừng |
|---|---|---|---|
| **P0** | `scripts/probe_assets.py` + tài liệu này | Claude viết · 🖥️ chạy | user dán output ⇒ chốt nguồn từng chuỗi |
| P1 | kho + registry + nguồn Python + backfill + bước pipeline + doctor | Claude · 🖥️ verify | kho có chuỗi dài, badge xanh |
| P2 | tab 🪙 Vàng · Dầu · USD | Claude · ○ xem | user nhìn tab thật |
| P3 | MCP nguồn ngày + đối chiếu (5 phiên chạy bóng rồi mới làm nguồn chính) | Claude · 🖥️ | 5 phiên không lệch bất thường |
| P4 | liên kết cổ phiếu: tương quan/beta 60 phiên | Claude · ○ | bảng độ nhạy có số |
| P5 | brief khối 🪙 (code dựng số, guard khoá) · cảnh báo Telegram biến động · Phân bổ dùng vàng VND | duyệt RIÊNG | — |

## 7. P0 — chạy và đọc kết quả

🖥️ DESKTOP, dưới tài khoản chạy task (có `.env` FRED_API_KEY, connector đã đăng nhập):

```
python scripts/probe_assets.py --mcp
```

Output gồm 4 tầng (python · sponsor · local · mcp), khối "Suy ra" (chênh SJC, dư địa tới trần, đối chiếu
trung tâm) và "Kết luận theo tài sản" (nguồn TƯƠI nhất + SÂU nhất cho từng chuỗi). Exit 0/1/2.

Đọc để quyết P1:
- FRED Brent/WTI/USD index sống ⇒ nguồn lịch sử dài cho dầu/USD; ghi lại độ trễ thật.
- stooq/Yahoo sống ⇒ thêm XAU dài + **DXY của ICE** (stooq dx.f = hợp đồng tương lai, Yahoo DX-Y.NYB =
  chỉ số); cả hai chết ⇒ USD thế giới chỉ có `DTWEXBGS` (ghi đúng tên trên UI).
- vnstock_data có hàm hàng hoá/tỷ giá ⇒ cân nhắc làm nấc giữa ladder (đã có quyền Golden).
- SJC/VCB trực tiếp sống ⇒ dự phòng khi MCP lỗi cho vàng nội / tỷ giá VCB.
- MCP: độ sâu thật từng chuỗi + đủ 36/36 lượt gọi ⇒ đủ tin để thành nguồn ngày ở P3.

## 8. Chưa biết / rủi ro

- Kết quả trong §4 đo trong phiên Claude (connector của phiên), KHÔNG phải trên máy thật dưới tài khoản
  task — có thể khác (tên server, độ trễ, quota).
- Suy luận "trung tâm = (mua+bán)/2 của SBVN" phải khớp bản tin SBV vài lần trước khi dùng thật.
- Finhay lịch sử có ngày nghỉ đứng giá (01–03/09) — P1 phải lọc theo lịch giao dịch của từng thị trường.
- Đơn vị giá đại lý (nghìn đ/chỉ) đo trên 2 mốc; P1 thêm sanity theo chênh với thế giới (vd ngoài
  −5%…+40% ⇒ nghi đơn vị, cách ly điểm đó).
