# Thiết kế lại GIAO DIỆN dashboard cho chuyên nghiệp — KẾ HOẠCH

> **Trạng thái 31/10/2026: user DUYỆT bản mẫu P0 · P1 (màu + chữ) CODE XONG trên nhánh
> `claude/adoring-bardeen-vpuq5b` — chờ user merge + restart dashboard (§7 hàng P1). Kế tiếp: P2.**
> Bản mẫu (canvas riêng tư của user, 3 artboard, số thật SSI phiên 30/10): https://claude.ai/artifact/ERUSopdPGkjDQsS9KGWgxD
> Khảo sát code ở `f5029d7`. Mỗi pha một PR, merge riêng được, **không đổi một con
> số nào** — chỉ đổi cách trình bày.

## 1. "Chuyên nghiệp" nghĩa là gì — tiêu chí đo được

Không đo bằng cảm giác. Xong khi đạt cả 8 điều sau:

| # | Tiêu chí | Hôm nay (đo 30/10) | Đích |
|---|---|---|---|
| 1 | Một bảng màu | **60 mã hex** khác nhau trong 29 file UI; 4 sắc xanh "tăng" (`#10b981` `#22c55e` `#34d399` `#199e70`), 3 nền tối (`#0a0e1a` `#0e1117` `#0d1117`) | ~20 token ở MỘT file, test chặn hex mới |
| 2 | Màu giá theo bảng điện VN | Chỉ xanh/đỏ, không phân biệt trần/sàn/tham chiếu | xanh tăng · đỏ giảm · vàng tham chiếu · **tím trần · xanh lơ sàn** |
| 3 | Chữ đọc được | Nhãn `#6b7280` trên nền = **3,98:1**, giờ cập nhật/chú thích `#4b5563` = **2,55:1** (chuẩn WCAG AA chữ nhỏ là 4,5:1) | mọi chữ ≥ 4,5:1 |
| 4 | Màn hình đầu trả lời "hôm nay thế nào, data tươi chưa" | Thứ đầu tiên thấy ở sidebar là `✅ Tests fast: … passed`; đầu MỌI tab là 3 nút pipeline | thanh trạng thái thị trường + độ tươi data trên mọi trang |
| 5 | Không lộ ruột | Expander "🔬 Debug", "Stack trace", `st.json` thô, lệnh `run.py` nằm ngay trên trang người dùng (§2) | ẩn sau "Chế độ chẩn đoán" |
| 6 | Một giọng chữ | Trộn Anh/Việt ("VnStock Analysis Dashboard", "Breadth Indicators", "Technical Score", "Portfolio" và "Danh mục đầu tư" cùng tồn tại); trộn `###`/`####`/`######`/`.section-title`/`st.subheader` | tiêu đề tiếng Việt, 3 cấp cố định; giữ thuật ngữ chuẩn ngành (RSI, MACD, P/E, VN30) |
| 7 | Icon không phụ thuộc hệ điều hành | Nav + tiêu đề dùng emoji — Windows 10 đã vẽ 🪙 thành ô vuông (CLAUDE-NOTES:7074) | Material Symbols của Streamlit (`:material/…:`) cho nav/nút/tiêu đề |
| 8 | Sáng/tối hoặc chạy thật, hoặc không có | Toggle "☀️ Light mode" chỉ đè 9 selector — bảng HTML, chart, Plotly, badge vẫn nền tối ⇒ nửa sáng nửa tối | quyết ở §9 câu 3 |

**Ngoài phạm vi:** không đổi framework (12,7K dòng UI Streamlit + test smoke — viết lại React là dự án khác);
không đổi logic/số liệu; **không đụng chữ trong brief/Telegram** (guard parse emoji đầu mục — đổi là phải test
FULL, U65). Khối brief trên dashboard vẫn hiện đúng chữ của brief.

## 2. Hiện trạng — đã kiểm code 30/10 (`f5029d7`)

**Điều hướng** — `st.pills` 9 nút emoji (`vnstock_dashboard.py:3581`), render có điều kiện để chỉ chạy tab
đang mở. Hệ quả: không có URL riêng từng trang (F5 = về Screener), không Back được, không mở thẳng một mã
từ link. 9 nút ngang không nhóm ⇒ nhìn như một hàng nút, không phải một app.

**Sidebar** — xếp từ trên xuống: 3 badge kỹ thuật HTML tự vẽ (tests `:3366`, doctor `:3408`, ladder model
`:3442`) → Live Mode + Live Scan (`:3488`) → Light mode (`:3559`) → phần riêng từng tab chèn thêm (Phân
tích 4 mục `analysis_tab.py:70`, Screener watchlist + bộ lọc `screener_tab.py:101`, Dòng tiền
`money_flow_tab.py:142`, Danh mục `portfolio_tab.py:278`). Sidebar là nơi dài nhất app và thứ quan trọng
cho nhà đầu tư nằm dưới cùng.

**Đầu trang** — dòng "Cập nhật lúc" + 3 nút 📥/🧩/🚀 + cảnh báo khoá pipeline (`:3201–3356`) đứng trên
MỌI tab. Thao tác vận hành ngang hàng nội dung.

**Màu & CSS** — một khối CSS chung (`:689–773`, IBM Plex qua Google Fonts `@import`) + **217 `style="`
inline** + **108 `unsafe_allow_html`** (nhiều nhất: `money_flow_tab` 65, `market_tab` 57, `analysis_tab` 55
style). Plotly 3 kiểu nền: `#0a0e1a` (`market_tab.py:1160,1201`), `#0e1117` (`portfolio_tab.py:493,590,617`,
`brief_strategy_panel.py:241,261`), trong suốt (còn lại). Chart nến LWC cứng màu trong iframe
(`:2324` nền, `:2398–2400` màu nến).

**Bảng** — bảng screener tự viết HTML + JS sort trong iframe (`render_table`, `:2819`); 36 chỗ
`st.dataframe` nhưng chỉ `money_flow_tab` dùng `column_config` (định dạng số, thanh tiến độ…).

**Lộ ruột trên trang người dùng** — `news_tab.py:435` (🔬 Debug: cấu trúc dữ liệu thô), `:463`, `:685`,
`:702` (context inject vào AI) · `money_flow_tab.py:237` (NN Mua = 0 — debug info) · `analysis_tab.py:849`
(Stack trace), `:952` (🔍 Debug: … = None).

**Tiêu đề** — Phân tích có 2 tiêu đề chồng nhau (`analysis_tab.py:71` ở sidebar "🔬 Phân tích", `:278`
"## 🔬 VnStock Analysis Dashboard"). Tin tức nhét 5 sub-tab mà 2 cái không phải tin (Vĩ mô, Phân bổ —
`news_tab.py:200`).

**Đáng GIỮ** — nền tối hợp giao dịch; IBM Plex (có bộ chữ tiếng Việt) hợp số; đã tách hàm thuần
(`table_style`, `market_table_format`, `sparkline`) và có smoke test render (`tests/test_tab_render_smoke.py`)
— hai thứ làm việc thiết kế lại an toàn được.

**Phiên bản** — máy thật chạy Streamlit **1.56** (`tests/test_portfolio_tab.py:489`). Đã cài 1.56.0 kiểm
30/10: có đủ `st.navigation(position="top")`, `st.Page`, `st.badge`, `st.popover`, `st.metric(border=,
chart_data=)`, `st.container(horizontal=)`, theme `[theme.light]`/`[theme.dark]`, `fontFaces`, `baseRadius`,
`chartCategoricalColors`, `dataframeHeaderBackgroundColor`. `requirements.txt` vẫn ghim `>=1.35` ⇒ nâng lên
`>=1.56`.

## 3. Nguyên tắc thiết kế

1. **Bảng điện, không phải trang trí.** Mật độ cao nhưng có thứ bậc: mỗi khối một con số chính, nhãn nhỏ
   xám, số mono căn phải, `tabular-nums` để cột số thẳng hàng.
2. **Màu = nghĩa.** Màu chỉ dành cho tăng/giảm/trần/sàn/tham chiếu và trạng thái. Còn lại là thang xám.
   Màu không bao giờ đứng một mình: luôn kèm dấu `+`/`−` hoặc ▲▼ (người mù màu đỏ-lục vẫn đọc được). Màu nhấn (nút chính, trang đang chọn) là **xanh dương** — không dùng xanh lá làm màu nhấn vì trùng nghĩa
   "tăng".
3. **Ba cấp chữ cố định:** tiêu đề trang (kèm 1 dòng phụ: phiên dữ liệu + độ tươi) · tiêu đề mục · nhãn thẻ.
4. **Tiếng Việt nhất quán**, số kiểu EN (`{:,.2f}`) như quy ước cũ.
5. **Thông tin vận hành ở MỘT chỗ.** Nhà đầu tư thấy 1 chấm trạng thái; người vận hành bấm vào thấy hết.
6. **Lỗi nói tiếng người.** Trang người dùng hiện 1 câu + việc nên làm; chi tiết kỹ thuật ở chế độ chẩn đoán.

## 4. Hệ thống thiết kế (P1)

### 4a. Bảng màu — nền tối (mặc định)

Giữ gần màu cũ để không "lạ mắt"; chỉ sửa chỗ hỏng độ tương phản và gộp các sắc trùng nghĩa. Tỉ lệ tương
phản đo trên nền `bg`.

| Token | Mã | Dùng cho | Tương phản |
|---|---|---|---|
| `bg` | `#0a0e1a` | nền app, nền chart (giữ nguyên) | — |
| `surface` | `#111827` | thẻ, sidebar | — |
| `surface_2` | `#1a2234` | header bảng, hover | — |
| `border` | `#1f2937` | viền | — |
| `text` | `#e5e7eb` | chữ chính | 15,6 |
| `text_muted` | `#9ca3af` | nhãn | 7,6 |
| `text_faint` | `#8b95a5` | chú thích, giờ cập nhật (**thay** `#6b7280`/`#4b5563`) | 6,4 |
| `accent` | `#3b82f6` | gạch chân trang đang chọn, đường biểu đồ chỉ số | 5,2 |
| `accent_fill` | `#2563eb` | NỀN nút chính — chữ trắng 5,2:1 (trắng trên `#3b82f6` chỉ 3,7, trượt chuẩn; phát hiện khi làm P0) | — |
| `up` | `#10b981` | tăng (sắc đang dùng nhiều nhất — 67 chỗ) | 7,6 |
| `down` | `#ef4444` | giảm (77 chỗ) | 5,1 |
| `ref` | `#fbbf24` | tham chiếu / đứng giá | 11,5 |
| `ceil` | `#d946ef` | trần | 5,6 |
| `floor` | `#22d3ee` | sàn | 10,7 |
| `warn` | `#f59e0b` | cảnh báo | 9,0 |
| `up_soft` / `down_soft` | `#34d399` / `#f87171` | chữ trên nền nhạt (chip %, chip RSI) | 10,0 / 7,0 |
| `series_1..3` | `#60a5fa` · `#f59e0b` · `#a78bfa` | EMA·MACD · đường tín hiệu · RSI | 7,6 · 9,0 · 7,1 |

Trạng thái (ok/warn/error/off) dùng lại `up`/`warn`/`down`/`text_faint` — **một** sắc xanh trong cả app.
Biểu đồ: `chartCategoricalColors` 8 màu cho ngành, `chartDivergingColors` đỏ→xám→xanh cho heatmap — kiểm
phân biệt được với mù màu đỏ-lục trước khi chốt (P0).

### 4b. Chữ

IBM Plex Sans (chữ) + IBM Plex Mono (số), **tự host** `static/fonts/*.woff2` qua `[[theme.fontFaces]]` —
bỏ `@import` Google Fonts (máy mất mạng/chậm thì app rơi về font hệ thống). Thang cỡ 12 · 13 · 14 · 16 ·
20 · 24; số chính thẻ KPI 24 mono. Bo góc `baseRadius` 8px; khoảng cách theo lưới 4/8/12/16/24.

### 4c. Hai module mới (thuần, test được)

- **`dashboard/theme.py`** ✅ P1 — `TOKENS` (§4a + `text_strong`, `text_off` cho ô khoá, `link`, `category`,
  `on_fill`/`on_light`) · `app_css()` (khối CSS chung, giữ tên class cũ) · `font_face_css()` cho iframe ·
  `lwc_palette()` → biến JS `PAL` trong iframe chart · `PLOTLY_BG` (nền trong suốt) · `price_color(price, ref,
  ceil, floor)` · `pct_color(v, flat=)` · `status_color(level)` · `rgba()` · `contrast()`.
  `.streamlit/config.toml [theme]` ghi cùng giá trị — test canh hai bên khớp.
  **Plotly KHÔNG dùng `pio.templates.default`** (đổi so kế hoạch, 31/10): `st.plotly_chart` mặc định
  `theme="streamlit"` tự dựng template từ `config.toml` (font, chữ, `chartCategoricalColors`) — template riêng
  sẽ bị đè. Chỉ cần bỏ nền hex ở call site (`**PLOTLY_BG`).
- **`dashboard/ui.py`** — thành phần dùng chung thay HTML tự vẽ: `page_header(title, subtitle)` ·
  `kpi_row(items)` (`st.metric(border=True)`) · `section(title, help=)` · `status_pill(level, text)` ·
  `empty_state(msg, action=)` · `price_table(df, ...)` (`st.dataframe` + `column_config`) ·
  `diag_expander(title)` (chỉ hiện khi bật chế độ chẩn đoán).

**Lưới canh (giống lưới slug chết)** ✅ P1: `tests/test_theme_tokens.py` đếm mã hex trong CHUỖI (comment
không tính) của từng file UI so `HEX_BUDGET`; vượt ⇒ đỏ, gỡ bớt mà quên hạ ngân sách ⇒ cũng đỏ (để hex không
quay lại). Mốc trước P1: **582** · sau P1: **416**. Cùng file: config↔token, 7 file font + OFL có thật,
tương phản ≥ 4,5:1 cho 14 màu chữ trên `bg` và `surface`, `theme.py` không import Streamlit, toggle Light mode
cũ không quay lại. Đã vào whitelist `--fast`.

## 5. Bố cục & điều hướng (P2)

### 5a. `st.pills` → `st.navigation(position="top")`

Entry `vnstock_dashboard.py` giữ nguyên vai trò: dựng sidebar chung + thanh trạng thái, rồi
`st.navigation({...}).run()`. Mỗi `st.Page` nhận CALLABLE (`render_market_tab`…) ⇒ trang chạy trong cùng
`__main__`, thủ thuật alias `sys.modules["vnstock_dashboard"]` (`:3578`) không đổi. Vẫn chỉ trang đang mở
được chạy (như pills). Được thêm: URL riêng (`/thi-truong`, `/phan-tich?ma=FPT`), F5 giữ trang, Back
được, icon Material.

Gom 9 tab → 5 nhóm (menu thả xuống trên thanh trên cùng):

| Nhóm | Trang | Từ đâu |
|---|---|---|
| **Thị trường** | Tổng quan · Dòng tiền · Phái sinh NN · Hàng hoá & Tiền tệ · Vĩ mô | 4 tab cũ + sub-tab Vĩ mô của Tin tức |
| **Cổ phiếu** | Bộ lọc · Phân tích mã | Screener · Phân tích |
| **Tin & Báo cáo** | Tin theo mã · Báo cáo tuần · Báo cáo | 3 sub-tab của Tin tức |
| **Danh mục** | Danh mục · Phân bổ | Portfolio + sub-tab Phân bổ |
| **Hệ thống** | Sức khỏe | Sức khỏe + nút pipeline + chi tiết badge + chẩn đoán |

Trang mặc định (`st.Page(..., default=True)`): **Tổng quan** (§9 câu 1).

Được thêm nhờ có URL: bấm một dòng ở Bộ lọc (`st.dataframe(on_select=…)`) ⇒ `st.switch_page` sang Phân
tích mã đúng mã đó (`query_params={"ma": …}`) — hôm nay phải gõ lại mã ở sidebar.

### 5b. Thanh trạng thái — một dòng trên MỌI trang

`VN-Index 1,2xx.xx +0.85%` · `VN30 …` · **phiên** (Chưa mở / Đang khớp / ATC / Đóng cửa / Nghỉ) · **dữ liệu
phiên dd/mm** (`covered_session`) + tươi/cũ · chấm **Live** (WSS) · chấm **Hệ thống** (gộp tests + doctor +
ladder model: xanh/vàng/đỏ, bấm ⇒ `st.popover` hiện đủ 3 badge như hôm nay). Badge tests đỏ vẫn làm chấm
đỏ — giữ quy tắc "badge đỏ = KHÔNG merge/deploy". Data cũ ⇒ hiện thêm nút **Cập nhật dữ liệu** ngay trên
thanh; data tươi ⇒ ẩn.

### 5c. Sidebar gọn còn 3 phần

1. **Live Mode + Live Scan** — giữ nguyên chỗ và key (bất biến 17/08, `tests/test_live_mode_crosstab.py`).
2. Bộ điều khiển của trang đang mở (watchlist, khoảng thời gian, bộ lọc…), có tiêu đề nhỏ.
3. Cuối: giao diện sáng/tối (nếu §9 câu 3 = giữ).

### 5d. Nút pipeline + chế độ chẩn đoán → trang Hệ thống

3 nút 📥/🧩/🚀 chuyển hẳn vào Hệ thống, **giữ nguyên** logic marker khoá `_meta/pipeline_running.json` +
ô "Vẫn chạy" — chỉ dời chỗ. Công tắc **Chế độ chẩn đoán** (cờ session, mặc định tắt) ở Hệ thống: mọi
expander Debug / Stack trace / `st.json` thô chuyển qua `ui.diag_expander`. Tắt ⇒ trang người dùng chỉ còn
`st.error` một câu tiếng Việt + việc nên làm.

## 6. Từng trang — màn hình đầu đề xuất (P3)

- **Tổng quan** — hàng KPI: VN-Index · VN30 · HNX · UPCoM · thanh khoản so TB20 · NN ròng · độ rộng
  tăng/giảm (`st.metric(chart_data=…)` có sparkline) → thẻ **Brief AI** (TLDR nổi, phần còn lại gập) →
  heatmap ngành → diễn biến chỉ số → breadth → drill-down ngành.
- **Bộ lọc** — preset thành `st.segmented_control` kèm số mã → bảng chính `price_table` (RSI thanh tiến
  độ, sparkline 20 phiên, % tô màu, chọn dòng ⇒ sang Phân tích) thay iframe HTML tự viết. Chấm điểm preset,
  thống kê phiên, alerts vào khu "Chi tiết" bên dưới.
- **Phân tích mã** — đầu trang: mã + tên · giá lớn · % · TC/trần/sàn tô màu bảng điện · KL · sàn niêm
  yết · ngành → chart 4 panel (**giữ bất biến logical-range**, chỉ nhận màu từ `lwc_palette()`) → 3 cột
  thẻ Kỹ thuật / Cơ bản / Khuyến nghị → tin liên quan. Bỏ tiêu đề trùng.
- **Dòng tiền** — KPI NN ròng 1D/5D/20D → bảng ngành `price_table` → khối ngoại chi tiết → live flow.
  65 `style=` inline là nợ lớn nhất, đi trang này sau cùng trong nhóm Thị trường.
- **Danh mục** — KPI NAV · lãi/lỗ hôm nay · lãi/lỗ tổng · tỷ trọng tiền → bảng vị thế → NAV → phân bổ ngành.
- **Hàng hoá & Tiền tệ / Phái sinh NN / Vĩ mô / Báo cáo** — đã gần chuẩn (`st.metric`, `st.dataframe`,
  0 `style=`): chỉ chuẩn tiêu đề + Plotly template.
- **Hệ thống** — 3 badge chi tiết + nút pipeline + chế độ chẩn đoán + nội dung `vnstock_health` cũ.

## 7. Lộ trình

Mỗi pha = 1 PR (P3 = mỗi trang 1 PR). Mỗi PR: `run.py test --fast` xanh + ảnh chụp trước/sau. Nhãn máy theo
`docs/VIEC-DANG-LAM.md`.

| Pha | Làm gì | Ai · máy | Xong khi |
|---|---|---|---|
| **P0** Bản mẫu ✅ 30/10 | Canvas 3 artboard: Tổng quan · Phân tích mã FPT (4 panel, warmup RSI/MACD để trống như bất biến chart) · Bảng màu & chữ — token §4a, số thật SSI phiên 30/10 | Claude (cloud) · **user duyệt** ○ máy nào cũng được | User duyệt hướng (hoặc sửa) |
| | (Đầu P1) Chụp 9 trang HIỆN TẠI làm mốc so: script Playwright `scripts/ui_snapshots.py` (cloud không có kho ⇒ phải chạy trên máy thật) | Claude viết · user chạy ○ máy nào cũng được | 9 ảnh trong `ui_snapshots/before/` (gốc repo, gitignore — KHÔNG để trong kho) |
| **P1** Nền ✅ 31/10 | `theme.py` + `config.toml [theme]` (ghim `base="dark"`, nhấn xanh dương thay đỏ mặc định của Streamlit) + IBM Plex tự host `static/fonts/` (7 file, 432 KB, OFL) + nền Plotly trong suốt + `PAL` cho chart LWC + token ở `table_style`/`market_table_format`/`sparkline`/CSS chung/badge sidebar/bảng screener; `streamlit>=1.56`; bỏ toggle ☀️ Light mode + `THEMES`; lưới hex; `scripts/ui_snapshots.py` | Claude | Cloud 31/10: 9 tab 0 exception, font Plex nạp từ static, chart 4 panel vẽ đủ (62 phiên FPT, 0 lỗi JS); FULL 5.153 passed. **Sửa luôn 1 lỗi thật:** máy để chế độ SÁNG ⇒ Streamlit dựng theme sáng dưới CSS tối, tiêu đề chìm (ảnh `ui_snapshots/before-light`) |
| | Merge + **restart** dashboard (theme đọc lúc khởi động) | user ⇄ CẢ HAI | Mở app: nút/slider xanh dương, font Plex, 1D% = 0 tô vàng |
| | Kiểm bản Streamlit: `python -c "import streamlit; print(streamlit.__version__)"` ≥ 1.56 | user ⇄ CẢ HAI (venv theo máy) | Cả hai máy ≥ 1.56 |
| **P2** Khung | `st.navigation` top + 5 nhóm + URL · thanh trạng thái · sidebar gọn · nút pipeline + chẩn đoán → Hệ thống | Claude | Smoke render từng trang xanh; `test_live_mode_crosstab` xanh; test marker khoá nút ở chỗ mới |
| **P3** Từng trang | Thứ tự: Tổng quan → Bộ lọc → Phân tích mã → Danh mục → Dòng tiền → còn lại. Thay HTML inline bằng `ui.*`, chuẩn tiêu đề, màu giá VN | Claude · user soi mắt mỗi PR ○ | Allowlist hex của trang về 0; ảnh sau khớp mockup |
| **P4** Sáng/tối | `[theme.light]`+`[theme.dark]` + nút chuyển sẵn của Streamlit (§9 câu 3a; toggle cũ đã bỏ ở P1) | Claude | Hai chế độ cùng đúng trên 9 ảnh |
| **P5** Hoàn thiện | Trạng thái rỗng / đang tải / lỗi đồng bộ cả app; màn laptop (cột co, bảng cuộn ngang); `FULL` test trước PR về `main` | Claude · user soi trên 💻 LAPTOP | `run.py test` FULL xanh; user duyệt |

## 8. Rủi ro & bất biến phải giữ

- **`st.components.v1.html` bị Streamlit báo bỏ** (log 1.56: "will be removed after 2026-06-01", thay bằng
  `st.iframe`). Chart LWC + bảng screener + báo cáo lãi suất đều đi đường này; 1.56 vẫn chạy (reviewer kiểm
  wheel 1.66.1: hàm vẫn còn, chỉ báo bỏ). `requirements` ghim `>=1.56.0,<1.57` — bản đã thử — để `pip install -r`
  ở máy cũ không nhảy thẳng lên bản mới nhất. Nâng trần = thử chart Phân tích trước.

- **Chart 4 panel** (CLAUDE.md bất biến): P1 chỉ thay chuỗi màu trong CSS/JS iframe, không chạm
  logical-range hay whitespace bar warmup. Đổi màu nến ⇒ soi mắt thêm 1 lần trên máy thật.
- **Live Mode/Live Scan ở sidebar chung** — `st.navigation` vẫn chạy entry mỗi lượt, giữ được; test cũ canh.
- **Widget state khi đổi trang** — `st.navigation` dọn state widget trang cũ y như pills hôm nay ⇒ không có
  lớp bug mới, nhưng mọi cờ dùng chung giữ quy ước tách key widget ↔ key cờ.
- **Smoke test** — fake streamlit `_Ctx(MagicMock)` tự có mọi thuộc tính nên `st.badge`/`st.popover` không
  vỡ; `st.navigation` + `st.Page` cần stub ở test entry (P2).
- **Brief/Telegram** — không đổi chuỗi nào trong `vnstock_brief*`; emoji trong nội dung brief vẫn hiện.
- **Kho dùng chung** — giao diện không ghi gì mới vào `data_warehouse`; ảnh chụp P0 để ở `ui_snapshots/`
  gốc repo (gitignore), không đi Dropbox.
- **Hành vi nút pipeline** — chỉ dời chỗ; test marker khoá phải đi theo.

## 9. Đã chốt — user trả lời 30/10

| # | Câu | Chốt |
|---|---|---|
| 1 | Trang mở đầu | **Tổng quan thị trường** (thay Screener) |
| 2 | Màu giá | **Bảng điện VN**: xanh tăng · đỏ giảm · vàng tham chiếu · tím trần · xanh lơ sàn |
| 3 | Light mode | **(a)** bỏ toggle hỏng ở P1, làm thật ở P4 |
| 4 | Gom nhóm §5a | **Đồng ý** — Vĩ mô sang Thị trường, Phân bổ sang Danh mục |
| 5 | Kiểu bản mẫu | **Mockup trên cloud** là đủ để duyệt |
| 6 | Badge kỹ thuật | **Gộp** tests/doctor/model thành 1 chấm + popover; đỏ vẫn đỏ |
