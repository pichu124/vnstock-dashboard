# Mở rộng dashboard sang VÀNG · DẦU · USD — THIẾT KẾ + P0 ĐO NGUỒN

> **Trạng thái 09/10/2026 tối: P0 + P0b XONG trên 🖥️ desktop** (`probe_assets.py --mcp` 19:51 §4b ·
> `probe_nowcast.py` 20:20 §4e). User thêm CHUẨN ĐỘ TƯƠI (§4d): số quốc tế + tin phải có TRONG NGÀY.
> Bảng nguồn §4c đã chỉnh theo P0b. **User duyệt P1 09/10 tối ⇒ P1 CODE XONG (§9, CLAUDE-NOTES U82)** —
> chờ 🖥️ desktop merge + `run.py assets --backfill --with-mcp`. P2 (tab 🪙) chưa làm.**
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
| `CURVE_BRENT` · `CURVE_WTI` | đường cong HĐTL M1…M7 (`BZ`/`CL` + mã tháng `.NYM`) | Yahoo, trong ngày | — | lưu ảnh chụp mỗi lượt (không có lịch sử lùi) | thay vai trò giá giao ngay (§4e) |
| `WTI_SPOT` | giao ngay EIA | **ước tính** = EIA × biến động CL tháng gần, CHỈ khi ≤3 phiên kể từ số EIA, kèm dải ±1,6% | — | FRED (từ 1986) | hết 3 phiên ⇒ ẩn |
| `BRENT_SPOT` | giao ngay EIA | **KHÔNG HIỆN** (ước tính p90 5,7% > 3%) — lưu FRED vào kho cho lịch sử, màn chính dùng đường cong | — | FRED (từ 1987) | — |
| `DXY` | ICE DXY | Yahoo DX-Y.NYB | — | Yahoo (từ 1971) | — |
| `USD_BROAD` | chỉ số USD rộng Fed | **ước tính tự tính** (trọng số Fed 2026 × currency-api, lệch pha +1), kèm dải ±0,3% | — | FRED (từ 2006) làm neo | P1 thử thêm tỷ giá Yahoo làm chuỗi dẫn, giữ cái p90 thấp hơn |
| `USDVND` | tỷ giá thị trường | MCP Finhay USDVND | er-api → currency-api | Yahoo VND=X (từ 2003) | er-api ±0,5% |
| `USDVND_VCB` | VCB mua TM/CK/bán | vietcombank.com.vn api | MCP SSI VCB | VCB api theo ngày (2 năm ≈ 500 lượt, giãn 0,3s) | SSI VCB ±0,3% |
| `USD_CENTRAL` | tỷ giá trung tâm NHNN | vnstock_data mbk (lượt Python mỗi giờ), **ngày dời +1 phiên** (§9c) | bản tin tuần SBV | vnstock_data mbk "Tỷ giá trung tâm" (từ 2016) | ~~SBVN (mua+bán)/2~~ — **bác 10/10** (§9b); ngày kiểm mỗi lần `--show`/doctor so `USD_SBV_REF` |
| `USD_SBV_REF` (10/10) | mua/bán USD tham khảo Cục QLNH (close = bán) | MCP SSI SBVN | — | MCP SSI 3 tháng (range 1m × 3) | thước đo ngày của mbk |

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

## 4e. Kết quả P0b trên máy thật (🖥️ PICHU 09/10 20:20) — chốt từng chuỗi

| Chuỗi | Sai số ước tính (p90, \|sai\|) | Kết luận |
|---|---|---|
| USD rộng tự tính (26/26 tiền tệ, trọng số Fed **2026**: EUR 21,0 · MXN 14,8 · CAD 12,8 · CNY 10,9 · GBP 5,2 · JPY 5,2%; lệch pha **+1**) | h=1…5 phiên: trung vị ~0,09–0,11% · p90 0,28–0,31% · max 0,62% (n≈105) | **TẠM ⇒ hiện kèm dải ±0,3%.** Sai số KHÔNG lớn dần theo h ⇒ là nhiễu từng ngày (giờ chốt tỷ giá currency-api ≠ giờ trưa New York của Fed), không phải trôi trọng số. Ước tính 09/10: **121,23** (neo Fed 121,38 ngày 02/10) |
| Brent giao ngay EIA | 120 ngày: h=3 p90 **5,69%**, h=5 6,90%; 3 năm h=3 2,79% | **KHÔNG HIỆN.** Cùng ngày 06/10: giao ngay 125,44 vs HĐTL 100,58 ⇒ **+24,7%** — chênh biến động mạnh nên neo + HĐTL không theo kịp |
| WTI giao ngay EIA | 120 ngày: h=1 0,67% · h=3 **1,64%** · h=5 3,86% | **TẠM khi ≤3 phiên** kể từ số EIA (kèm dải); quá 3 phiên ⇒ ẩn. Cùng ngày 06/10: 96,24 vs 89,44 ⇒ +7,6% |
| Đường cong HĐTL Yahoo | trong ngày, đủ 6–7 kỳ hạn | **DÙNG.** Brent BZZ26 103,17 → BZK27 92,90: M1−M2 **+3,29$ (+3,29%)**, M1−05/2027 +10,27$ (+11,05%); WTI CLX26 90,92 → CLK27 84,30: M1−M2 +0,96$ (+1,07%) — **backwardation**, cùng chiều với chênh giao ngay lớn |
| Giá rổ OPEC | HTTP 403 Cloudflare ("Just a moment…") cả 2 URL | **BỎ** |

⇒ Màn chính phần dầu: HĐTL tháng gần (Finhay/Yahoo) + đường cong + chênh kỳ hạn — đều trong ngày; giá giao
ngay EIA chỉ còn WTI dạng ước tính ≤3 phiên. Phần USD: DXY trong ngày + USD rộng ước tính ±0,3%.

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

## 9. P1 — đã làm (09/10 tối, CLAUDE-NOTES U82)

**Module:** `vnstock_assets_sources.py` (parser + fetch Python, mạng qua MỘT chỗ `HTTP`) ·
`vnstock_assets.py` (registry 25 chuỗi, kho, luật gộp, ước tính, trạng thái, mỗi giờ, backfill, CLI) ·
`vnstock_assets_mcp.py` (Finhay/SSI qua `complete_mcp`, lượt ngày 16 tool, backfill theo lượt nhỏ, kiểm SBVN).

**Kho:** `data_warehouse/assets/<KHOÁ>/<YYYY>.parquet`, cột `date open high low close bid ask contract
source fetched_at meta`; ghi nguyên tử (`write_table_atomic`), đọc gộp cả bản "(conflicted copy)" giữ bản
lấy mới nhất, ghi xong xoá bản trùng của năm. Vàng nội lưu ĐỒNG/lượng (Finhay × 10.000, SJC trực tiếp
× 1.000), `close` = giá BÁN.

**Luật gộp** (`merge`): ngày ≥ hôm qua ⇒ bản lấy MỚI hơn thắng (giá trong ngày); cũ hơn ⇒ theo thứ tự
`Spec.sources`. Hai nguồn khác nhau lệch > `xtol_pct` (dòng gần đây: chỉ khi lấy cách nhau ≤3 giờ) ⇒ cờ
`xcheck` trong `_meta/assets_status.json` (ghi một lần mỗi chỗ lệch). Ngoài khoảng sanity ⇒ cờ, không ghi.
Thị trường nghỉ cuối tuần (mọi thứ trừ vàng nội) ⇒ bỏ dòng T7/CN (Finhay forex có nến đứng giá).

**Ước tính trong ngày** (`refresh_estimates`, ghi chuỗi `*_EST` source `est`, meta có neo/h/dải):
`USD_BROAD_EST` = số Fed gần nhất × chỉ số tự tính (trọng số Fed cache 7 ngày `_meta/assets_fed_weights.json`
× tỷ giá theo ngày cache `_meta/assets_fx_days.json`), lệch pha +1, dải ±0,30%; `WTI_SPOT_EST` = EIA ×
biến động WTI HĐTL, dải ±1,64%, CHỈ khi ≤3 phiên kể từ số EIA (quá ⇒ ẩn, ghi lý do). Brent giao ngay
không ước tính (`display="hide"`).

**Nhịp:** `run.py news-alert` (task mỗi giờ 24/7 🖥️) gọi `vnstock_assets.py --hourly` trong tiến trình con
trần 360s (task tin có trần 15′) — exit code của tin không đổi; dry-run/lọc nguồn không móc. MCP vào giờ
`VNSTOCK_ASSETS_MCP_HOURS` (mặc định 9,11,14,16,20 giờ VN). Pipeline đêm: bước `assets` (sau gold) +
`assets-mcp` (cuối, chỉ khi lượt MCP trước cũ hơn 6 giờ). Khoá THEO MÁY (thư mục tạm) chặn hai tiến trình
cùng ghi; MCP gọi `claude -p` KHÔNG giữ khoá, chỉ khoá lúc ghi. Kill-switch: `VNSTOCK_ASSETS` ·
`VNSTOCK_ASSETS_HOURLY` · `VNSTOCK_ASSETS_MCP`.

**Doctor `assets`** (chỉ warn): lượt Python >3 giờ · chuỗi hiện màn chính không có số trong ngày (vàng nội
>1 ngày, còn lại >3 ngày cho cuối tuần) · MCP >30 giờ/lỗi · cờ lệch nguồn 24 giờ.

**Dọn kèm:** gỡ goldprice.org (403) khỏi `vnstock_gold._ENDPOINTS`, exchangerate.host (hết VND) khỏi
`vnstock_macro._FX_ENDPOINTS`; nhãn "premium SJC ~15-20%" thay bằng số đo từ kho (`_premium_note`).

**Lệch so với §4c (có lý do):** lịch sử WTI lấy Yahoo CL=F thay vì `vnstock_data.oil_crude` (cùng công
cụ, bớt một phụ thuộc; vnstock_data giữ cho tỷ giá trung tâm mbk). Chỉ số USD tự tính dùng currency-api
— nguồn này cập nhật ~1 lần/ngày (~07:00 VN) nên ước tính "trong ngày" chứ chưa "trong giờ"; thử tỷ giá
Yahoo làm chuỗi dẫn để lại sau khi có ≥1 tuần số thật.

**Lệnh:** `run.py assets` (lượt Python) · `--show` · `--backfill [--with-mcp] [--vcb-days N]` ·
`--mcp-backfill [--only KHOÁ,…]` · `--mcp` · `run.py assets-mcp`. Test: `tests/test_assets.py` (25) ·
`test_assets_sources.py` (12) · `test_assets_mcp.py` (11), whitelist `--fast`; conftest đưa kho/meta/khoá
về tmp, chặn mạng, tắt móc giờ.

## 9b. Lượt máy thật đầu tiên (🖥️ PICHU 10/10 ~00:xx) + sửa

**Chạy tốt:** `--fast` 3.390 passed · FRED 23.822 dòng · Yahoo Brent 4.779 / WTI 6.561 / DXY 14.161 /
USDVND 5.949 · VCB 522 ngày (67s) · mbk 3.182 · MCP XAU 461 · BZ+CL 307 · USDVND 50 · 9 sản phẩm đại lý
~450–560 dòng · `WTI_SPOT_EST` 98,30 · VCB còn 3,22% tới trần.

**Bốn lỗ và cách vá:**
1. *SJC miếng (3 khung) + SBVN 3m "kết quả rỗng"* — thật ra Claude Code CẮT kết quả MCP > ~25k token
   (đo trong phiên: đại lý ~15 token/ngày ⇒ 4 năm ~37k; SBVN 1 tháng = 154 dòng ~7k, mô tả tool: "từ 3m
   trở lên >1.000 dòng"). Code cũ gộp mọi trường hợp không ra dòng thành "kết quả rỗng". Vá: SJC miếng
   xin TỪNG NĂM 2015→nay (2 năm/phiên `claude -p`), SBVN 3 lượt `range=1m` + `toDate` lùi 30 ngày (ghép
   lượt theo cả `toDate`); `empty_reason` phân biệt rỗng thật / nguồn báo lỗi / text không đọc được
   (in 200 ký tự đầu). Lệnh chạy lại riêng phần hỏng: `--mcp-backfill --only GOLD_SJC_BAR,USD_SBV_REF`.
2. *SBVN KHÔNG phải tỷ giá trung tâm.* Báo chí 08/10: "tỷ giá tham khảo tại Cục QLNH 24.407 – 26.869" =
   đúng từng đồng SSI SBVN 08/10, mà trung tâm 08/10 là 25.634 ≠ (mua+bán)/2 = 25.638. Đối chiếu 05–09/10
   (trung tâm báo chí 25.636 · 25.643 · 25.638 · 25.634 · 25.629; giữa SBVN 25.636 · 25.643 · 25.645 ·
   25.638 · 25.629) ⇒ khớp 3/5 phiên. Vá: SBVN thành chuỗi riêng `USD_SBV_REF` (close = giá bán);
   `USD_CENTRAL` chỉ còn mbk (+ bản tin tuần). Luật "một chuỗi một công cụ" nay chốt bằng code:
   `merge` từ chối nguồn không khai trong `Spec.sources` (cờ `kind=source`) và bỏ dòng cũ của nguồn đã gỡ.
3. *mbk nghi ghi LÙI 1 phiên:* dòng mbk 08/10 = 25.629 = số NHNN công bố sáng 09/10 (08/10 là 25.634),
   và lúc 00:xx 10/10 mbk chưa có dòng 09/10. Chưa sửa ngày (một điểm chưa đủ): `verify_central` đo trên
   ~60 phiên giữa SBVN vs mbk ở lệch −1/0/+1 phiên, ghi `_meta/assets_status.json` `central_verify` +
   dòng trong `--show` kèm 6 giá trị mbk cuối để đối chiếu báo chí. Kết luận "LÙI 1 phiên" ⇒ dời ngày ở
   `parse_mbk_central` + backfill lại mbk. Ảnh hưởng tới lúc đó: trần tính từ trung tâm cũ 1 phiên (±5 đ,
   ~0,02%) — không đổi kết luận dư địa.
4. *Đường cong HĐTL trống, doctor "chưa có lượt nào", ước tính USD rộng ẩn không rõ vì sao:* backfill
   không chạy lượt Python thường. Vá: backfill (và `--mcp-backfill`) chốt bằng MỘT lượt Python như mỗi giờ
   rồi in từng nguồn lỗi + từng ước tính; `estimate_usd_broad` trả (ước tính, lý do) chỉ đúng khâu hỏng
   (trọng số Fed + lỗi tải / chưa có tỷ giá / chỉ số tự tính rỗng / chưa có số Fed / số Fed chưa có tỷ giá
   ngày +1 / quá 10 phiên).

`--show`: VND không phần lẻ, cột thẳng (nhãn 🔒 chuyển xuống cuối dòng), dòng trần ghi trung tâm + ngày.

## 9c. Vòng 2 trên máy thật (🖥️ PICHU 10/10 01:03) + sửa

**Chạy tốt:** `--fast` 3.398 passed · SJC miếng 2015→nay 4.303 dòng (6 phiên, không phiên nào cắt) ·
`USD_SBV_REF` 67 dòng · đường cong Brent M1−M2 +3,41$ / WTI +0,87$ (backwardation) · 21/22 chuỗi trong
ngày · chênh SJC +10,86% · VCB còn 3,22% tới trần.

**mbk ghi LÙI 1 phiên — XÁC NHẬN.** `verify_central` 62 phiên: lệch +1 khớp 32 (trung vị lệch 1 đ), đúng
ngày 8 (10 đ), −1 3 (15 đ). Báo chí khớp từng đồng: mbk 01/10 = 25.636 = NHNN 02/10 · mbk thứ Sáu 02/10 =
25.636 = NHNN thứ Hai 05/10 · mbk 06/10 = 25.638 = NHNN 07/10 · 07/10 = 25.634 = NHNN 08/10 · 08/10 =
25.629 = NHNN 09/10. Vá `src.shift_mbk_dates` (trong `fetch_mbk_central`, mọi đường gọi): giá ở ngày d
sang ngày làm việc kế tiếp CÓ trong chuỗi mbk (qua nghỉ lễ), dòng cuối sang ngày làm việc kế theo lịch,
trùng đích thì dòng ghi SAU thắng (nếu mbk lùi theo ngày lịch và có dòng CN thì CN = số thứ Hai — đúng
cả hai giả thuyết). Kiểm SỐNG từ kho, không mạng: `central_dating()` (USD_SBV_REF vs USD_CENTRAL nguồn
mbk) in ở `--show` + doctor warn khi lệch ≠ 0 (n ≥ 5) ⇒ vnstock_data đổi cách ghi ngày là biết ngay.
Kho cũ ghi đè bằng `--backfill --steps mbk` (cùng nguồn ⇒ dòng mới thắng).

**Ước tính USD rộng tính ra mà KHÔNG vào kho:** mang ngày FILE currency-api (thứ Bảy 10/10) ⇒ kho bỏ dòng
cuối tuần ⇒ `--show` "chưa có dữ liệu", doctor "USD_BROAD_EST trống"; `h=7` đếm cả file cuối tuần. File
D+1 ↔ số Fed D ⇒ ước tính nay mang NGÀY FED (file − 1), chỉ giữ file ứng với ngày làm việc của Fed ⇒ h
đếm PHIÊN (10/10: neo 02/10, h=5, ngày 09/10).

**Cache tỷ giá ghi sai khoá:** bản "latest" lúc 01:00 VN vẫn là file hôm qua mà bị cất dưới khoá hôm nay,
và ngày đã có thì không bao giờ tải lại ⇒ chỉ số tự tính đứng một ngày. Nay khoá theo `date` GHI TRONG file
(`fetch_fx_latest_dated`) + tải lại `FX_REFETCH_DAYS`=3 ngày gần nhất mỗi lượt (khoá sai cũ tự lành).

**Vòng 3 (🖥️ 10/10 01:22) — kho ĐÚNG, thước SAI.** Sau `--backfill --steps mbk,fx`: 22/22 chuỗi trong
ngày, MCP ok 154 dòng, `USD_BROAD_EST` 121,23 ngày 09/10 h=5, trung tâm 09/10 = 25.629 (khớp báo chí).
Nhưng doctor vẫn "LÙI 1 phiên": khớp từng lệch riêng −1: 5 · 0: 26/63 · +1: 43/62. Nghĩa là thước —
giữa giá tham khảo SBVN — chỉ ~40% phiên bằng trung tâm CÙNG phiên, ~70% bằng phiên TRƯỚC (SSI chụp
trước/sau lúc NHNN cập nhật). So từng lệch riêng thì kho đúng ngày vẫn ra "+1 nhiều nhất" ⇒ báo động giả.
Sửa: chấm giả thuyết "kho lệch L" bằng tỉ lệ phiên mà giữa SBVN khớp kho phiên D−L **hoặc** D−L−1 (thiếu
một vế thì không chấm); L đúng ⇒ ~100%, L sai ⇒ ~40–70%; kết luận khi ≥10 phiên, ≥80% và hơn giả thuyết
kế ≥10 điểm %, không thì "chưa rõ" (doctor im). `--backfill --steps mbk` in thêm mbk THÔ: số dòng theo
thứ + 10 dòng cuối (3.182 thô → 2.650 phiên ⇒ ~1 dòng cuối tuần/tuần — để chốt luật dòng CN bằng số).

**Vòng 4 (🖥️ 10/10 01:37) — P1 XONG.** `--fast` 3.408 passed · `--show` "mbk ĐÚNG ngày" (giả thuyết lệch
0 khớp 59/61, −1 24/61, +1 43/60) · doctor "Kho tài sản" ✅ 22/22 chuỗi trong ngày, MCP ok. mbk thô theo thứ
T2 535 · T3 538 · T4 537 · T5 537 · T6 502 · T7 1 · **CN 532** ⇒ mbk ghi số ngày D vào NGÀY LỊCH D−1 (dòng CN
= số thứ Hai — luật "dòng sau đè" của `shift_mbk_dates` đúng). **Đính chính số báo chí §9c:** đọc lại theo
chuỗi tăng/giảm, NHNN 05/10 = 25.643 (+7 từ 25.636) và 06/10 = 25.645 (+2) — không phải 25.636/25.643; với
số đúng, giữa giá tham khảo SBVN = trung tâm phiên TRƯỚC 4/5 phiên 05–09/10, cùng phiên 1/5 (09/10).

**Còn lại (không lỗi):** doctor "MCP Finhay/SSI chưa chạy" — lượt MCP ngày chưa từng chạy (giờ đặt 9, 11,
14, 16, 20; bước pipeline `assets-mcp`); chạy tay một lần `run.py assets --mcp`. VCB ReadTimeout 15s một
lượt — lượt giờ sau tự thử lại. `--backfill --steps fred,yahoo,vcb,mbk,gold-cache,fx` chạy riêng từng bước.

## 10. P2 — tab "🪙 Hàng hoá & Tiền tệ" (10/10, CLAUDE-NOTES U83)

**File:** `vnstock_assets_view.py` (số THUẦN, đọc kho, không mạng/Streamlit — test được) · `dashboard/assets_tab.py`
(chỉ vẽ) · nối `_TAB_OPTIONS` + nhánh `if _active_tab == "🪙 Hàng hoá & Tiền tệ"` trong `vnstock_dashboard.py`.

**Bố cục:** dòng trạng thái (giờ lượt Python/MCP, máy) · chọn khung 3 tháng…tất cả · 3 thẻ `st.tabs` (render đủ
cả 3 mỗi lượt — dữ liệu nhỏ, test chạm được hết):
- 🥇 Vàng — ô XAU · SJC miếng · SJC nhẫn · chênh SJC vs TG (điểm % so 1 tuần); bảng 10 sản phẩm 5 đại lý (mua,
  bán, chênh mua–bán %, so SJC miếng, chênh vs TG %, sản phẩm chưa có giá hôm nay ⇒ ⚠️); biểu đồ SJC bán vs
  vàng TG quy đổi (đồng/lượng), biểu đồ chênh % RIÊNG (không hai trục), XAU USD/oz.
- 🛢️ Dầu — ô Brent/WTI HĐTL M1 · WTI giao ngay ước tính (± dải, neo EIA, số phiên — hoặc LÝ DO ẨN) · Brent−WTI;
  đường cong theo tháng đáo hạn (nét liền = mới nhất, nét chấm = ~1 tuần trước) + M1−M2/M1−M6 ⇒ backwardation/
  contango; M1 hai chuỗi; chênh Brent−WTI; expander giá giao ngay EIA + vì sao Brent giao ngay ẩn.
- 💵 USD — ô DXY · USD rộng ước tính · USD/VND thị trường · VCB bán · trung tâm · giá bán tham khảo NHNN · dư địa
  tới trần; biểu đồ biên ±5% (VCB bán, giá tham khảo, trung tâm + TRẦN là đường tham chiếu xám nét đứt); DXY;
  USD rộng Fed + ước tính; dòng kiểm ngày tỷ giá trung tâm.

**Quy ước số:** % đổi theo NGÀY LỊCH (1 phiên = điểm liền trước · 1 tuần = điểm gần nhất ≤ cuối − 7 ngày · 1
tháng ≤ −30 · YTD ≤ 31/12 năm trước) vì vàng nội có giá cuối tuần còn dầu/USD thì không; thiếu lịch sử ⇒ "—",
không bịa. Cũ: > 1 ngày (vàng nội) / > 3 ngày (còn lại) ⇒ "⚠️ cũ N ngày". Vàng TG quy đổi ghép ngày gần nhất
≤ ngày vàng nội, lệch tối đa 4 ngày (T7/CN dùng số thứ Sáu). VND không phần lẻ.

**Biểu đồ (skill dataviz):** một trục y; đường 2px; ≥2 chuỗi có chú thích; màu theo THỰC THỂ (Brent luôn xanh,
WTI luôn cam) từ 3 ô đầu bảng màu đã kiểm mù màu (`#3987e5` · `#d95926` · `#199e70`); chuỗi < 3 điểm vẽ thêm
chấm; trục ngày `dd/mm/yy`. Đã render thật trên Streamlit + chụp Chromium (kho mẫu) — sửa 4 chỗ: `$` trong
caption bị Streamlit đọc thành công thức (nay ghi "USD", test chặn ký tự `$`), xuống dòng caption cần "  \n",
trục ngày tiếng Anh, chuỗi 1 điểm vô hình.

**Test:** `tests/test_assets_view.py` (11, whitelist `--fast`): % đổi theo lịch, cũ theo lịch thị trường,
chênh SJC cuối tuần, bảng đại lý, ảnh đường cong, biên tỷ giá, render đủ 3 mục không nhánh lỗi (≥9 biểu đồ, lý
do ẩn WTI hiện ra), kho trống ⇒ hướng dẫn nạp, tab có trong điều hướng, không `$`.

**Chưa làm (pha sau):** P3 (MCP làm nguồn chính sau 5 phiên chạy bóng) · P4 thẻ "Liên kết cổ phiếu" (tương
quan/beta 60 phiên) · P5 brief/Telegram/Phân bổ (duyệt riêng).

