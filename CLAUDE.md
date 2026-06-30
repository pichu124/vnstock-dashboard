# Project notes for Claude Code

This file holds durable reminders/context for future sessions on this repo.
Items here get auto-loaded into Claude's context at session start.

---

## 🧪 Test discipline

**Khi nào cần chạy lại tests** (121 tests, ~0.7s):
- Sau khi `git pull` về máy → đảm bảo môi trường vẫn OK
- Sau khi sửa code trong: `vnstock_regime.py`, `vnstock_brief.py`,
  `vnstock_sentiment.py`, `vnstock_news.py`, `vnstock_telegram.py`,
  `vnstock_freshness.py`, `vnstock_vn30_weights.py`,
  `vnstock_market_sentiment.py`, `vnstock_fundamental_updater.py`,
  `vnstock_macro.py`, `vnstock_news_feeds.py`
- Trước khi tạo PR merge về `main`
- Sau khi nâng cấp pandas / numpy / Python version

**Lệnh chạy**:
```powershell
# Nhanh — chỉ 121 tests cho module mới (~0.7s)
python run.py test --fast

# Đầy đủ — toàn bộ tests/ (~6s)
python run.py test
```

Kết quả được ghi vào `data_warehouse/_meta/test_status.json` và hiển
thị làm badge ở sidebar dashboard (✅ xanh nếu pass, ❌ đỏ nếu fail).

**Nếu badge sidebar hiện đỏ** → mở terminal, chạy `python run.py test --fast`,
xem output để biết test nào fail. Đừng deploy / merge khi badge đỏ.

---

## 🩺 Brief quality fixes (DONE 2026-06-09, branch `claude/serene-feynman-15y1y1`)

Một loạt fix chất lượng cho **Morning brief** (đa số dùng chung cho Close brief
vì nằm trong `build_prompt` / data blocks, không phụ thuộc template). Đừng
regress các cơ chế này:

**Data freshness / self-heal** (tất cả best-effort, có env tắt):
- `_augment_with_live_vnindex()` — gộp bar VNINDEX 1m từ `_live/bars_{today}.parquet`
  thành 1 bar daily tạm thời → brief intraday mô tả phiên HÔM NAY. Đặt
  `vnindex_tech["intraday"]=True`. (Rollup cố tình skip index — xem
  `vnstock_rollup._should_rollup_to_warehouse`, nên đây là cách duy nhất để brief
  sáng thấy data hôm nay.)
- `market_data_freshness()` so **`data_date`** (ngày DATA thật, KHÔNG phải
  `generated_at`) của `market_overview.json` với ngày phiên → header Telegram +
  block prompt cảnh báo "⚠️ độ rộng/regime: phiên cũ". File cũ thiếu `data_date`
  → fallback `_warehouse_eod_date()` (KHÔNG dùng generated_at — sẽ tưởng tươi).
  `compute_market_overview` nay ghi field `data_date`.
- `_auto_refresh_market_overview()` (env `VNSTOCK_BRIEF_AUTO_REFRESH=0` để tắt) —
  recompute market_overview khi nó tụt sau kho EOD. `_maybe_reconcile_overdue()`
  (env `VNSTOCK_BRIEF_AUTO_RECONCILE=0`) — đóng rec quá hạn trước khi tạo brief.
- **BUG NGẦM đã fix**: `_load_history` (vnstock_strategy) gọi
  `load_price_history` (@st.cache_data) → **fail ngoài Streamlit** → reconcile &
  backtest từ CLI nhận data rỗng. Nay có `_load_history_from_parquet` đọc parquet
  trực tiếp (chuẩn hoá bằng `vnstock_runner._normalize_prices`).

**Nhãn & đơn vị** (đừng để regress):
- `Giá 1T %` = đổi **1 TUẦN/5 phiên** (chg5), KHÔNG phải 1 phiên. Header movers +
  mỗi dòng + đóng góp pp đều phải ghi "(1 tuần)". KHÔNG ghi "phiên sáng"/"hôm nay"
  cho số này (không có data đổi-1-phiên cho từng mã).
- Giá CW/penny giữ số lẻ (`_fmt_price`/`_fmt_rec_price`): <1 → 3 lẻ, <10 → 2 lẻ.
- GTGD so **sáng-với-sáng** (`ctx["morning_gtgd"]`: prev/avg5/avg20). Khi
  `intraday` → ẩn "GTGD cả ngày" VÀ ẩn `session_timing` signal/detail
  (morning_share = sáng/cả-ngày là vô nghĩa giữa phiên — nguồn của lỗi "sáng
  chiếm 78% cả ngày / institutional").

**Deterministic guards** (LLM hay phớt prompt-nudge → chốt bằng code):
- `lead_sector`/`lag_sector` = ngành đóng góp +/- mạnh nhất (1 tuần); `build_prompt`
  bơm "CHỈ ngành X được làm dẫn dắt", gate ±0.05pp.
- `_bias_floor_dir(momentum, regime_score)` — momentum ≤ -50 hoặc regime ≤ -3 →
  Bias BẮT BUỘC GIẢM (và kịch bản CHÍNH phải cùng chiều); ngược lại cho TĂNG.
- Loại ngân hàng/CK/bảo hiểm (`_FINANCIAL_TICKERS`) khỏi xếp hạng D/E & Op.CF
  (đặc thù ngành, không so sánh được — tránh mis-flag "MBB Op.CF -64,972 tỷ").
- **BĐS Op.CF — ngữ cảnh, KHÔNG loại (DONE 2026-06-10)**: chủ đầu tư BĐS (Ngành
  chứa "bất động sản") GIỮ trong xếp hạng Op.CF nhưng `collect_context` tính
  `ctx["realestate_tickers"]` theo ngành → `_vn30_fund_block(realestate=…)` gắn
  "(BĐS)" vào mã trong dòng "Op.CF thấp nhất" + thêm dòng ngữ cảnh. KBC FY2025
  −17.344 tỷ là **SỐ THẬT** (dòng năm 2025 = tổng 4 quý; `_annual_operating_cf`
  đúng — KHÁC bug FPT), âm CHỦ YẾU do tích lũy quỹ đất/hàng tồn kho dự án (vốn lưu
  động; op. profit before WC = +539 tỷ → KHÔNG lỗ HĐKD). Prompt rủi ro buộc ghi
  ngữ cảnh + soi D/E/nợ vay, cấm gọi "kiệt quệ tiền mặt".
- Watchlist: chỉ chọn mã từ movers/khuyến nghị đã cung cấp, neo "Giá" thật, cấm
  "SELL ở giá" (VN không bán khống) → dùng "GIẢM TỶ TRỌNG nếu thủng…".
- **Setup CHỈ mã ⭐ (DONE 2026-06-10)**: movers quét toàn TT ở sàn 10 tỷ (phân
  tích "Biến động bất thường"), nhưng setup giao dịch chỉ được dùng mã có dấu
  **⭐** = VN30 HOẶC GTGD TB ≥ `_WATCHLIST_GTGD_MIN_TY` (=30 tỷ, tunable) — tránh
  đưa lệnh MUA vào mã mỏng (vd VIW); `enforce_watchlist_eligibility` chốt lại
  bằng code (LLM hay phớt ⭐). `_select_liquid_movers` carry "GTGD TB (tỷ)";
  `_vn30_line` gắn ⭐. Hướng setup PHẢI bám Stance/bias floor: Stance GIẢM → ưu
  tiên phòng thủ, MUA chỉ là kèo CÓ ĐIỀU KIỆN ("canh MUA nếu vượt lại…").
- Rec quá hạn bị lọc khỏi "Đề xuất giao dịch"; "Đề xuất bổ sung" cấm xin data đã
  có (dòng tiền ngành/NN ròng, GTGD, breadth, regime, VN30 cơ bản).

### 💵 GTGD cả ngày từ EOD (DONE 2026-06-11) — KHÔNG cần WSS live

`session_stats` (GTGD theo khung giờ 9h-11h30 / 9h-15h) CHỈ pipeline WSS **live**
trong phiên mới ghi — chạy brief trên data EOD-only (down hôm sau) → toàn 0.0 →
model BỊA GTGD (5.153 / 14.118 / 9.650,4). Fix: `compute_market_overview` ghi
`gtgd_by_date` = Σ (giá đóng cửa × KLGD) THEO TỪNG NGÀY (~5 phiên gần nhất; ~5
bar cuối mỗi mã) = **GTGD cả ngày THẬT từ EOD** (xấp xỉ khớp lệnh, có ngay sau
`run.py screener`); `total_gtgd_day`/`gtgd_date` = phiên HOÀN CHỈNH gần nhất qua
`_pick_gtgd_session` (bỏ phiên ĐANG DỞ — updater chạy giữa trưa kéo bar dở hôm
nay về, count thấp → chọn ngày hôm trước). Brief tra `gtgd_by_date[ngày-của-brief]`
→ `ctx["full_day_gtgd"]` (gate coverage ≥60% universe, dưới ngưỡng → "chưa đủ
dữ liệu"); Session Timing block
ưu tiên session-live, fallback EOD (gắn nhãn "ước tính từ EOD"); `enforce_gtgd_total`
pin số trong TLDR/Tổng kết về giá trị này (strip "chưa có dữ liệu" khi cả 2
nguồn đều trống). **GTGD sáng (split 9h-11h30) KHÔNG suy được từ EOD** — vẫn cần
WSS; morning brief trên EOD-only → "Chưa có GTGD phiên sáng". (Lưu ý: tổng EOD gồm
mọi sàn đã phân ngành, có thể > GTGD HOSE-only; xấp xỉ close×vol, không VWAP.)

### 🛡️ Guard hậu kiểm deterministic — chuỗi DÙNG CHUNG `apply_brief_guards(text, ctx)`

**QUAN TRỌNG (DONE 2026-06-12)**: toàn bộ chuỗi fixup nay nằm trong **một hàm
chung `apply_brief_guards(text, ctx)`** (định nghĩa ngay trước `generate_brief`);
`generate_brief` gọi nó cho MỌI agent, KHÔNG phân biệt brief_type. ⇒ **parity
morning↔close được bảo đảm BY CONSTRUCTION**: thêm 1 guard vào hàm này là áp cho
CẢ 2 brief cùng lúc. Mỗi guard tự brief_type-aware bên trong (anchor/section
detection), nên fix dùng chung trừ khi CỐ Ý gate (vd `enforce_gtgd_compare_frame`
chỉ "Tổng kết phiên" = close). Test khoá parity: `test_morning_brief_gets_all_session_guards_end_to_end`
(chạy 1 morning brief mang ĐỦ mọi bug pattern qua chuỗi → ra sạch) +
`test_apply_brief_guards_is_the_single_shared_chain`. **Đừng inline lại chuỗi vào
`generate_brief`** — sẽ phá điểm parity duy nhất.

LLM hay phớt chỉ thị prompt → chốt bằng code sau khi agent trả output (thứ tự
trong `apply_brief_guards`, áp cho mọi agent, cả morning & close):
1. `enforce_upcoming_events` — thay TOÀN BỘ body mục "Sự kiện sắp tới" bằng list
   chuẩn từ ctx (top 3 + note GDKHQ); fallback splice khi LLM chối "Không có sự kiện".
2. `enforce_risk_section` (chạy ĐẦU cho mục Rủi ro) — **canonical-hóa** phần
   fundamental: thay claim của LLM bằng block từ `_canonical_risk_lines(ctx)`
   (D/E cao nhất ≥1.5 phi-tài-chính + Op.CF âm thấp nhất, gắn (BĐS)+ngữ cảnh).
   Giữ dòng vĩ mô/kỹ thuật của model, bỏ dòng fundamental → hết loạt lỗi
   metric/số/superlative/mis-pick/mâu thuẫn. Các guard rủi ro cũ
   (`enforce_risk_numbers`, `enforce_realestate_ocf_context`) chạy SAU làm
   defensive no-op.
2b. `enforce_realestate_ocf_context` — mã BĐS trên dòng Op.CF thiếu ngữ cảnh quỹ
   đất → chèn (whole-text, áp cả 2).
3. `enforce_watchlist_hygiene` — xóa meta-disclaimer + dòng độn (anchor "watchlist
   sáng mai" → close-only).
4. `enforce_money_flow_two_sides` — thiếu vế NN mua/bán ròng mạnh nhất (≥50 tỷ) →
   chèn; anchor theo DÒNG dòng-tiền nên áp cả "Dòng tiền đáng chú ý" (close) lẫn
   "Dòng tiền ngành" inline (morning).
5. `enforce_risk_numbers` — mã trong "Rủi ro" thiếu số D/E/Op.CF → chèn (cả 2 vì
   morning nay CÓ mục Rủi ro).
6. `enforce_pivot_labels` — pin S1/S2/R1/R2 về pivot chuẩn, chỉ dải 800-2500
   (không đụng giá cổ phiếu trong setup); áp cả 2 (regex toàn text).
7. `enforce_watchlist_eligibility` — loại setup mã GTGD < `_WATCHLIST_GTGD_MIN_TY`
   & không VN30 (anchor "watchlist sáng mai" → close-only).
8. `enforce_gtgd_total` — pin GTGD cả ngày (session-live hoặc EOD `full_day_gtgd`)
   trong TLDR/Tổng kết; strip "chưa có dữ liệu" khi cả 2 nguồn trống. Keyword-anchored
   (không đụng điểm VNINDEX cùng dòng / GTGD theo ngành).
9. `enforce_no_cjk` — xóa ký tự Trung/Nhật/Hàn (vd "达到") lọt vào brief.

**Guard thêm 2026-06-12 (đều trong `apply_brief_guards`, áp cả 2 brief):**
10. `enforce_money_flow_two_sides` (mở rộng) — sửa số NN bịa gắn vào ngành cả 2
    dạng: *số-trước-tên* ("44 tỷ … Dầu khí") VÀ *số-sau-tên trong ngoặc* ("Thép &
    Kim loại (NN -1.372 tỷ)"); `_named_in_side` kiểm ngành top thật được gọi CÙNG
    MỆNH ĐỀ với từ khoá "bán/mua ròng" (không chỉ có mặt) → tránh xếp sai hạng.
    **`enforce_sector_nn_figures`** (companion, chạy NGAY SAU, WHOLE-TEXT) — sửa số
    NN ngành bịa ở BẤT KỲ ĐÂU ngoài mục dòng tiền (morning 14:11: dòng "Tránh/Bán"
    ghi "Thép & Kim loại (… NN bán ròng -1.372 tỷ)" — bịa + mâu thuẫn "Ngân hàng
    -703 mạnh nhất"). Bắt "{ngành} …(≤40 ký tự)… [NN] bán/mua ròng <số> tỷ" → pin
    về NN thật từ ctx (từ khoá "ròng" ngay trước số nên KHÔNG đụng "-0.03pp").
11. `enforce_liquidity_label` — mệnh đề "thanh khoản" mang số ÂM = NN bán ròng đội
    lốt turnover → thay bằng dòng canonical top-GTGD thật từ ctx (GTGD ≥ 0 luôn).
12. `enforce_nn_window_label` — số "NN ròng 1D" (1 phiên, từ block Tâm lý) bị gắn
    nhãn "tuần" → bỏ nhãn tuần (self-contradiction "X tỷ tuần này (1D…)") /
    relabel "(1D)"; chống nhầm khi 1 ngành có cùng magnitude.
13. `enforce_gtgd_compare_frame` — **close-only**: trong "Tổng kết phiên", số GTGD
    cả ngày bị so với baseline SÁNG (sai khung + sai chiều: 11.929 > 9.129 mà bảo
    "thấp hơn 43%") → thay bằng so-cả-ngày-vs-cả-ngày (TB5/TB20) từ
    `full_day_gtgd_cmp`. Morning so sáng-với-sáng là ĐÚNG → không đụng.
14. `enforce_no_bias_directive_leak` — "bias GIẢM **bắt buộc**": chữ "bắt buộc" là
    chỉ thị NỘI BỘ của bias-floor block (prompt cấm in) → strip, giữ hướng.
15. `enforce_no_record_superlative` — "GTGD thấp **kỷ lục**": brief chỉ có baseline
    TB5/TB20, không có cực trị lịch sử → bỏ "kỷ lục"/"nhất lịch sử", giữ "thấp".
16. `enforce_no_duplicate_momentum` — gộp "momentum N/100" lặp CÙNG GIÁ TRỊ trên 1
    dòng, giữ lần cuối (gắn tâm lý). (Lưu ý: composite "tích luỹ/phân phối mạnh"
    KHÔNG hạ theo pp — "mạnh" là composite score, trục khác với đóng góp pp index.)
17. `enforce_lead_lag` — pin dòng dẫn dắt/tụt hậu về `lead_sector`/`lag_sector`
    deterministic. Close theo prompt đúng; **MORNING brief phớt** (13:40: ghi
    "Chưa có nhóm dẫn dắt" dù BĐS +0.275pp, VÀ đặt BĐS-ngành-dẫn-dắt lên dòng
    "Tránh/Bán" với -0.03pp sai, mâu thuẫn cả TLDR). Canonical-hóa dòng mua/dẫn
    dắt (morning "Tích luỹ/Mua" / close "Dẫn dắt") + dòng tránh/tụt hậu (morning
    "Tránh/Bán" / close "Tụt hậu") khi phủ nhận / gọi sai ngành / thiếu ngành
    đúng. Dòng đúng (close) giữ nguyên; idempotent. ⇒ đây là điểm parity quan
    trọng: "Trọng tâm theo dõi" của morning giờ luôn khớp lead/lag như close.
17b. `enforce_lead_lag` (mở rộng 12/06) — pin pp của lead/lag Ở BẤT KỲ ĐÂU, không
    chỉ dòng nhãn. Morning 23:14 TLDR "giảm tỷ trọng Bất động sản (đóng góp
    -0.504pp)" — bịa (mượn số NN −504 tỷ thành −0.504pp); BĐS là lead +0.464pp →
    pin về +0.464pp. Lệch > 0.005pp mới sửa; idempotent.
20. `enforce_compare_direction` — từ so sánh phải khớp DẤU của %. Close 12/06:
    "GTGD cả ngày 18.353 tỷ … thấp hơn TB5 phiên (+43%)" — "thấp hơn" + (+43%) mâu
    thuẫn (so cả-ngày-vs-cả-ngày ĐÚNG khung nên `enforce_gtgd_compare_frame` không
    đụng). Lật từ khi clash: "thấp hơn …(+N%)" → "cao hơn"; "cao hơn …(-N%)" →
    "thấp hơn". Cặp nhất quán giữ nguyên; % phải trong ~30 ký tự (cùng mệnh đề).
    **Form B (12/06 morning)**: "8,397 tỷ … thấp hơn 11% TB sáng (7,549.1 tỷ)" —
    % KHÔNG dấu, baseline là GIÁ TRỊ trong ngoặc → so subject (giá trị tỷ đầu
    dòng) với baseline: 8,397 > 7,549 → "cao hơn". So bằng SỐ THẬT nên chắc.
19. `enforce_scenario_levels` — mức VNINDEX BỊA trong kịch bản (morning 14:28:
    "đóng cửa trên 1,801.99 (đáy phiên)" — 1,801.99 không khớp pivot/close/MA nào
    + "đáy phiên" mà CAO HƠN close = vô lý). STRICT-NHƯNG-AN-TOÀN: chỉ token
    *2-lẻ-band-index* (1,xxx.xx ∈ 800-2500) KHÔNG khớp 14 mức thật (close, MA20/50/
    200, S1/S2/R1/R2, đỉnh/đáy tuần/tháng/52w) trong ~2.7đ → pin về mức gần nhất;
    pivot/close/MA + mục tiêu tròn/xấp xỉ ("dưới 1,790") KHÔNG đụng. Nhãn đáy/đỉnh
    phiên mâu thuẫn close → bỏ. (User chọn guard chặt, chấp nhận rủi ro biên nhỏ.)
22. `enforce_gtgd_baseline_pct` — **close-only**: mỗi % phải khớp ĐÚNG baseline,
    CẢ 2 dạng. Form 1 "±N% vs/so <baseline>" (Tổng kết) — close 12/06 gán nhầm
    (+4% của TB20 thành TB5...). Form 2 "<baseline> (±N%)" (TLDR) — "cao hơn TB5
    (+43%)" trong khi Tổng kết đã pin +21% → cùng brief mâu thuẫn TB5. Pin cả 2
    chiều về `full_day_gtgd_cmp` (avg5/avg20/prev) → TLDR khớp Tổng kết. Gate
    "Tổng kết phiên" + bỏ baseline có "sáng"; baseline không có cmp (TB20 khi <15
    phiên) để nguyên (không có số để pin); idempotent.
23. `enforce_composite_rotation_hygiene` — giữ khối composite rotation nhưng vá 2
    lỗi (user chọn "giữ nhưng guard"): (a) **mâu thuẫn bucket↔nhãn** — ngành trong
    dòng "Phân phối" mang nhãn "tích luỹ" (hoặc ngược) → bỏ nhãn mâu thuẫn (23:44:
    "Phân phối cảnh báo: CNTT (tín hiệu tích luỹ mạnh)"); nhãn nhất quán giữ
    nguyên. (b) **jargon "Net BS"** (Buy/Sell tiếng Anh) — "Net BS +51.7% volume"
    / "+6M" → "mua/bán ròng ~X% KL" / "~X triệu CP" (dấu → mua/bán). **"1M/3M"
    nhập nhằng (đã truy nguồn `vnstock_market_analyzer`)**: là CỬA SỔ 1 tháng/3
    tháng (Net BS 1M, Giá 1M) → "X tháng"; còn HẬU TỐ "M" trên GIÁ TRỊ CÓ DẤU
    ("+6M") = triệu CP. Phân biệt bằng dấu (có +/- = triệu CP; không dấu = tháng);
    "volume"→"KL"; "Net BS" lẻ → "NN ròng". Idempotent.
21. `enforce_breadth_label` — brief CHỈ có "% mã trên MA200" (above_ma200_pct),
    KHÔNG có "% mã tăng giá". Close 12/06: "chỉ 17% mã cổ phiếu tăng giá" — 17%
    là số trên-MA200 (A/D 0.85 ⇒ ~46% tăng), gán nhãn "tăng giá" sai → relabel
    "trên MA200". Gate theo khớp giá trị (N ≈ above_ma200_pct ±1) nên số thật
    khác không bị đụng; idempotent.
24. `enforce_sentiment_consistency` (DONE 2026-06-16) — pin nhãn tâm lý + "momentum
    N/100" trong body về canonical `ctx["market_sentiment"]` (đúng cái header
    Telegram hiện + đã bơm vào prompt). Close 16/06: header "📉 Tiêu cực,
    momentum -33" nhưng body bịa "❄️ Sợ hãi, momentum -24" (mà -24 còn KHÔNG khớp
    ❄️ Sợ hãi vốn cần < -50). Pin mọi "momentum …/100" + mood sau cụm "Tâm lý …:";
    idempotent; no-op khi thiếu sentiment.
25. `enforce_breadth_quality` (DONE 2026-06-16) — hạ "độ rộng … tích cực" xuống
    "trái chiều" khi metric cấu trúc DUY NHẤT (% trên MA200) yếu + nền tiêu cực
    (close 16/06: "tích cực … 18% trên MA200" — A/D 1 phiên dương nhưng cấu trúc
    yếu = trái chiều). Gate `above_ma200_pct < 40` VÀ momentum < 0 nên TT rộng
    thật không bị đụng; idempotent.
26. `enforce_vnindex_change` (DONE 2026-06-16) — pin "% thay đổi VNINDEX so với
    phiên trước" về `vnindex_tech.day_change_pct` thật. Close 16/06: "tăng -24%
    so với phiên trước" (−24 là momentum lọt vào, thật +0.31%; "tăng" + số âm tự
    mâu thuẫn). CHỈ đụng cụm "tăng/giảm X% so với phiên trước/hôm qua" (không đụng
    pp ngành / đổi tuần); idempotent.
27. `enforce_buy_vs_bias_caveat` (DONE 2026-06-30) — khi `ctx["bias_floor"]["dir"]
    == "GIẢM"` mà mục "💡 Đề xuất giao dịch" VẪN có lệnh BUY/MUA (lệnh từ chiến
    lược đã backtest, qua `_recommendation_block`) → CHÈN 1 dòng cảnh báo cuối mục:
    "⚠️ Các lệnh MUA trên là tín hiệu backtest TỪNG MÃ; bối cảnh chung đang GIẢM →
    … tôn trọng cắt lỗ (SL), cân nhắc giảm tỷ trọng" (hằng số `_BUY_BIAS_CAVEAT`).
    User chọn hướng **GẮN CẢNH BÁO, KHÔNG lọc** (mirror BĐS Op.CF "ngữ cảnh, không
    loại" — lệnh có SL = rủi ro xác định, giấu đi là mất tín hiệu). CHỈ phát khi
    bias=GIẢM + có dòng buy-side (SELL-only dưới GIẢM đã nhất quán; "canh MUA NẾU
    vượt" là conditional đã bias-aware → bỏ qua). Idempotent: caveat mở đầu bằng ⚠️
    (= section emoji) nên khi re-parse nó thành ranh giới mục → check `_BUY_BIAS_CAVEAT
    in text` TRÊN TOÀN VĂN (không theo body bị cắt) để khỏi chèn trùng. Áp cả 2
    brief (mục "Đề xuất giao dịch" có ở cả morning & close).

**`max_tokens` brief = `_BRIEF_MAX_TOKENS` (2400, bump từ 1200 — 2026-06-16)**:
`generate_brief._call` truyền giá trị này. Brief nay ~11 mục (thêm 🌐 Vĩ mô + 📰
Tin, model còn echo lại 2 block đó) → 1200 token cắt cụt body (close 21:00 dừng
ngay sau "Mức kỹ thuật", mất 8 mục cuối). Nếu sau thêm mục → cân nhắc nâng tiếp.
18. `enforce_number_format` (chạy CUỐI) — chuẩn hoá số về 1 quy ước EN (phẩy ngăn
    nghìn, chấm thập phân) như data block (`{:,.2f}`)/guards/close. Morning 13:54
    trộn VN ("1.798,61", "9.129,4", "1.858,39", "-3,2%", "5.038 tỷ") với EN
    ("5,233.3", "1,789.31") do template example xưa dùng VN ("1.815,42") trong khi
    data block xuất EN → model lẫn lộn. Chỉ đổi token VN KHÔNG nhập nhằng
    (nghìn+thập-phân dấu chấm-grouping + phẩy-decimal; nghìn-dot ngay trước tỷ/tỉ;
    % phẩy-decimal). KHÔNG đụng số EN, pp 3 lẻ ("+0.275pp"), tỷ số ("0.87"), ngày
    ISO. Đã sửa luôn example template (212/283) về EN để hết tín hiệu mâu thuẫn.

**Parity morning↔close (DONE 2026-06-11)**: 2 template nay thống nhất tính năng,
trừ khác biệt CỐ Ý — GTGD sáng-với-sáng (intraday), "Watchlist sáng mai"/"Stance
ngày mai" là close-only, "Kịch bản phiên chiều" là morning-only. Đã đồng bộ:
morning thêm mục "⚠️ Rủi ro cần lưu ý" (cùng luật cơ bản/BĐS/số); guard dòng-tiền
2-vế áp cả dòng inline morning; khối RÀNG BUỘC BIAS brief_type-aware (morning→"Kịch
bản phiên chiều", close→"Stance ngày mai"); morning Trọng tâm neo block lead/lag;
luật thuần-tiếng-Việt + pin pivot áp cả 2.

### ✅ Checklist kiểm tra CLOSE brief (lần tới — sau khi down data CẢ NGÀY)

Khi chạy close brief với data EOD đầy đủ, `intraday=False` → hành vi khác sáng:
1. **Header**: KHÔNG còn "⚠️ data phiên gần nhất" VÀ KHÔNG còn "⚠️ độ rộng/regime:
   phiên cũ" (vì data_date = hôm nay sau khi down + chạy `run.py screener`). Nếu
   vẫn cảnh báo → `market_overview.json` chưa refresh với data hôm nay.
2. **GTGD**: PHẢI hiện "GTGD cả ngày" (phiên đã đóng), và `session_timing` signal
   institutional/retail hiện lại (morning_share lúc này hợp lệ). Mục "Tổng kết
   phiên" so GTGD cả-ngày-với-cả-ngày, KHÔNG dùng baseline sáng.
3. **Stance ngày mai** (TLDR) phải bám regime/sentiment (bias floor áp dụng).
4. **Dẫn dắt & Tụt hậu** = đúng `lead_sector`/`lag_sector` deterministic, ghi "(1
   tuần)". **Watchlist sáng mai**: neo giá thật, không bịa mã, BUY/SELL nhất quán,
   không "SELL ở giá".
5. **Rủi ro**: không mis-flag ngân hàng/CK vì D/E hay dòng tiền lớn.
6. **Khuyến nghị đang mở**: số ngày hợp lý, rec quá hạn đã reconcile (không zombie).
7. Mọi % giá có khung thời gian rõ; mã chỉ trong VN30.

→ Khi đánh giá close brief, soi đúng các điểm trên + đối chiếu nội bộ (Stance ↔
regime ↔ kịch bản, đóng góp pp ↔ ngành dẫn dắt). Chạy `python run.py test --fast`
sau bất kỳ sửa nào ở `vnstock_brief.py`.

---

## 🧠 Brief context blocks + lịch refresh (DONE 2026-06-08)

`collect_context()` trong `vnstock_brief.py` bơm các khối dữ liệu vào prompt.
Các khối **mới thêm** (ngoài kỹ thuật VNINDEX / regime / breadth có sẵn):

| Khối | Nguồn data | Cần chạy gì để có |
|------|-----------|-------------------|
| **Cơ bản nhóm theo dõi** (VN30 + mid-cap; D/E, ROE, Op.CF) | `data_warehouse/_meta/fundamentals.parquet` | `python vnstock_fundamental_updater.py` (1×/tuần) |
| **Tâm lý thị trường** (mood + momentum -100..+100) | breadth + NN ròng + RSI/MA + news + **vĩ mô**, qua `vnstock_market_sentiment.py` | luôn có (6 tín hiệu nội tại); tin tức (thứ 7) cần `python run.py news`; vĩ mô (thứ 8) cần `python run.py macro` |
| **Dòng tiền ngành** (NN ròng 1T + GTGD theo ngành) | `market_overview.json` (đã pre-aggregate) | có sẵn sau `python run.py screener` |
| **🌐 Vĩ mô** (lãi suất & tỷ giá + đổi) | `data_warehouse/_meta/macro_indicators.json` qua `vnstock_macro.py` | `python run.py macro` (auto: tỷ giá + LNH-Vietstock; SBV policy nhập tay) |
| **📰 Tin kinh tế/chính trị** (RSS diện rộng + sentiment + tác động) | `data_warehouse/_meta/market_news_cache.json` qua `vnstock_news_feeds.py` | `python run.py news` (gồm RSS) — fetch RSS cần mạng (web session bị chặn) |

**Lịch refresh (Task Scheduler) — DÙNG SCRIPT CÓ SẴN `scripts/setup_scheduled_tasks.ps1`**
(PowerShell **Run as Administrator**, chạy 1 lần; tự detect venv, set working dir,
StartWhenAvailable=ON — máy tắt giờ đó thì chạy bù lúc boot; xem trước: `-DryRun`;
gỡ: `-Remove`):
```powershell
cd "C:\Users\Administrator\Dropbox\Claude vnstock"
.\scripts\setup_scheduled_tasks.ps1
```
3 task được đăng ký: **VnStock Daily Pipeline** 18:00 T2-T6 (`run.py all` =
sync EOD → validate → screener → news → test → audit — trọn quy trình tối,
sau giờ đóng cửa) · **VnStock Weekly Corp Actions** CN 09:00 (Vietstock
cổ tức/chia tách → registry) · **VnStock Fundamentals** T2 08:00 (1×/tuần;
mùa BCTC giữa tháng 1/4/7/10 chạy thêm tay). Sự kiện GDKHQ KHÔNG cần task —
brief tự refresh 1×/ngày (VN30 + top-40 movers). Kiểm tra:
`Get-ScheduledTask -TaskName "VnStock *"`.

**Sự kiện DN sắp tới (DONE 2026-06-10)** — `vnstock_events.py` tổng hợp GDKHQ
cổ tức/chia tách/thưởng (tái dùng `vnstock_adjust._fetch_events` →
`Company.events()`), cache `_meta/upcoming_events.parquet`. Brief nạp qua
`load_upcoming(within_days=14, tickers=VN30∪movers)` → block "📅 Sự kiện sắp
tới" (`_upcoming_events_block`). Đây là phần "sự kiện kinh tế" KHẢ THI với data
nội bộ; **vĩ mô lãi suất & tỷ giá nay ĐÃ tích hợp** qua `vnstock_macro.py` (xem
mục riêng bên dưới); CPI/Fed/GDP vẫn chưa có (cần nguồn ngoài, vướng allowlist).
Chạy `python vnstock_events.py` (VN30) / `--tickers` / `--check`.
Auto-refresh 1×/ngày qua `_maybe_refresh_events()` trong `generate_brief`
(mtime cache ≠ hôm nay → fetch; tắt: `VNSTOCK_BRIEF_AUTO_EVENTS=0`); universe =
`_events_universe()` = **VN30 ∪ top-`_EVENTS_REFRESH_MAX_MOVERS`(=40) movers
theo GTGD** (2026-06-11 — trước đó VN30-only nên sự kiện mid-cap watchlist
không bao giờ tự có). Fundamentals KHÔNG auto — chạy tay/Task Scheduler
1×/tuần (xem lịch trên), thêm trong mùa BCTC (giữa tháng 1/4/7/10).
Chống regress (2026-06-10): `refresh_upcoming` **merge-safe** — mã fetch lỗi
(None) GIỮ sự kiện cũ trong cache, chỉ fetch THÀNH CÔNG (kể cả rỗng) mới
thay/xóa. `enforce_upcoming_events()` (gọi trong `generate_brief`) — guard
deterministic: LLM ghi "Không có sự kiện đáng chú ý" dù ctx CÓ events → splice
danh sách thật vào output (LLM hay phớt block dù data có trong prompt).

### 🌐 Vĩ mô: lãi suất & tỷ giá (DONE 2026-06-14) — `vnstock_macro.py`

Lấp khoảng trống "tin VĨ MÔ — lãi suất/tỷ giá" mà block "🔧 Đề xuất bổ sung" lâu
nay vẫn xin. Theo dõi 3 chỉ số cốt lõi, cache `_meta/macro_indicators.json`
(history theo ngày/chỉ số), brief nạp qua `load_macro(effective_date)`:
- **`usdvnd`** (tỷ giá USD/VND tham chiếu) — AUTO-fetch best-effort từ API FX
  miễn phí (`open.er-api.com` → fallback `exchangerate.host`). Mạng bị chặn /
  API lỗi → GIỮ cache cũ, KHÔNG bịa.
- **`sbv_policy_rate`** (lãi suất tái cấp vốn) — SEED 4.5%/năm as_of 2023-06-19
  (nguồn "seed"); đổi vài lần/năm → cập nhật tay khi SBV ra quyết định.
- **`interbank_on`** (lãi suất liên ngân hàng ON) — **nhập tay `--set`** (mặc
  định). Đã thử auto từ **Vietstock** VNIBOR (`getdatabynormid` normid 66):
  handshake CSRF token+cookie chạy được (token render UNQUOTED), POST 200 nhưng
  trả **`[]`** vì **TƯỜNG PHÍ bản Basic** (xác minh 2026-06-14: popup "nâng
  cấp", Network 0 request data). FiinGroup/WiFeed/CEIC đều trả phí ⇒ KHÔNG có
  API free đáng tin cho lãi suất VN. Code fetch (`fetch_interbank_on` /
  `trace_vietstock` / `extract_interbank_on`) GIỮ lại, bật bằng env
  `VNSTOCK_MACRO_VIETSTOCK=1` nếu có tài khoản Vietstock trả phí.

Chiến lược HYBRID (user chọn 2026-06-14): auto tỷ giá + nhập tay lãi suất, và
**mọi chỉ số đều ghi đè được**: `python vnstock_macro.py --set <key> <value>
[--as-of YYYY-MM-DD]`. CLI khác: `--refresh` (seed + fetch FX), `--show`,
`--diag` (thử fetch FX 1 lần — **xác minh trên máy có mạng**; sandbox bị
allowlist chặn nên FX luôn None ở đây). Pipeline: bước `macro` trong `run.py all`
(best-effort, sau `foreign-flow`).

**Brief wiring (parity morning↔close by construction)**:
- `collect_context` → `ctx["macro"]` (levels + change vs lần đọc trước) +
  `ctx["macro_news"]` (lọc news cache theo từ khoá lãi suất/tỷ giá/CPI/Fed/SBV —
  KHÔNG fetch mới). Auto-refresh 1×/ngày qua `_maybe_refresh_macro()` (tắt:
  `VNSTOCK_BRIEF_AUTO_MACRO=0`).
- `_macro_block` → mục "## 🌐 Vĩ mô" trong cả 2 template (sau "Sự kiện sắp tới").
  Số định dạng EN (như mọi data block); đổi tỷ giá ghi %, đổi lãi suất ghi
  "điểm %"; luôn kèm `as_of` để thấy độ cũ. Hàm ý: lãi suất tăng / VND mất giá =
  thắt chặt (bất lợi CP, nhóm vay nợ cao, NN dễ bán ròng).
- `enforce_macro(text, ctx)` trong `apply_brief_guards` (mirror
  `enforce_upcoming_events`) — canonical-hoá body mục vĩ mô từ ctx (LLM hay làm
  tròn/đổi số); idempotent; no-op khi không có data; splice đè dòng phủ nhận
  "chưa có dữ liệu vĩ mô". `🌐` đã thêm vào `_SECTION_EMOJIS`.
- **Tín hiệu tâm lý thứ 8**: `vnstock_macro.macro_pressure_score()` (lãi suất
  tăng / VND yếu = điểm ÂM) → `vnstock_market_sentiment` (weight 0.10, tự
  renormalize). CHỈ phát tín hiệu khi có THAY ĐỔI đáng kể (FX ≥0.3%, lãi suất
  ≥10bps) — backdrop ổn định không làm loãng composite.

**Tỷ giá USD/VND**: auto OK (verify 14/06: 26,191.9 qua `--diag`). FX None ⇒ cần
thêm host vào egress allowlist (web session). **Lãi suất**: nhập tay vì nguồn
free đều bị tường phí (xem trên) — `python vnstock_macro.py --set sbv_policy_rate
<số>` và `--set interbank_on <số>` (cập nhật khi để ý nó nhảy; brief tự cảnh báo
thay đổi + tự lọc tin lãi suất từ news cache). Nếu sau này có tài khoản Vietstock
trả phí: đặt `VNSTOCK_MACRO_VIETSTOCK=1` rồi `--refresh` để auto LNH.

### 📰 Tin kinh tế/chính trị diện rộng (DONE 2026-06-15) — `vnstock_news_feeds.py`

Bổ trợ tin THEO MÃ (`vnstock_news.py`): kéo tin VĨ MÔ/CHÍNH TRỊ ảnh hưởng thị
trường từ **bộ RSS free** (báo tài chính VN + quốc tế), lọc liên quan, dedup,
LLM chấm sentiment + tóm tắt tác động 1 dòng, cache
`_meta/market_news_cache.json`.
- **Parse RSS bằng STDLIB** (`xml.etree`) — KHÔNG thêm dependency (RSS 2.0/Atom,
  RFC822/ISO date, strip CDATA/HTML). Fetch best-effort qua `requests`.
- `_FEEDS` = danh sách feed curated (user chọn "bộ rộng" 2026-06-15) — **URL cần
  verify trên máy có mạng**: `python vnstock_news_feeds.py --diag` in số tin/feed,
  feed ❌ (URL sai/chặn) thì sửa/xoá trong `_FEEDS`. Sandbox bị allowlist chặn nên
  --diag ở đây ra 0/9.
- `_MARKET_KEYWORDS` lọc tin thị-trường (lãi suất/tỷ giá/Fed/CPI/chính sách/dầu/
  địa chính trị…); dedup tái dùng `vnstock_news.deduplicate_news`.
- **LLM**: `analyze_item` gọi `vnstock_sentiment.chat_complete` (helper MỚI,
  additive — provider ladder Groq→Cerebras→OpenRouter) 1 call ra `sentiment |
  tác động`. CHỈ chấm top-N (`_MAX_ANALYZE_DEFAULT`=8) tin mới chưa phân tích;
  cache trong JSON nên không chấm lại.

**Brief wiring (parity morning↔close by construction)**:
- `collect_context` → `ctx["market_news"]` (top 6, ≤3 ngày). `_maybe_refresh_market_news()`
  auto 1×/ngày (tắt: `VNSTOCK_BRIEF_AUTO_MARKET_NEWS=0`).
- `_market_news_block` → mục "## 📰 Tin kinh tế/chính trị" cả 2 template (sau
  "🌐 Vĩ mô"); 🟢/🔴 sentiment + dòng tác động. `📰` thêm vào `_SECTION_EMOJIS`.
- `enforce_market_news` trong `apply_brief_guards` — canonical-hoá mục từ ctx
  (chống LLM bịa tiêu đề), idempotent, splice đè dòng "không có tin"; mirror
  `enforce_macro`/`enforce_upcoming_events`.
- Pipeline: `run.py news` nay refresh LUÔN RSS feeds (nên `run.py all` đã gồm) +
  `_maybe_refresh_market_news` khi tạo brief. Cadence = "theo pipeline + brief"
  (user chọn 2026-06-15; KHÔNG poll realtime — brief chạy 2×/ngày).
- **Telegram split (DONE 2026-06-16)**: brief dài hơn (vĩ mô + tin) vượt giới hạn
  4096 ký tự/tin của Telegram → đuôi (mục 📰) bị cắt. `vnstock_telegram.send_message`
  nay tách thành NHIỀU tin ≤4096 (cắt theo dòng để tag HTML không vỡ, hậu tố
  "(k/n)") thay vì truncate. `_split_for_telegram` test trong `test_telegram.py`.

### ⚡ Updater nhanh 10× (DONE 2026-06-16) — `vnstock_updater.py`

"Cập nhật giá" cũ chạy 3+ giờ vì xử lý ~1724 mã TUẦN TỰ (1 API call/lần ~7s) +
mã hủy niêm yết (last 2018-2021) re-fetch nhiều NĂM mỗi lần cho 0 ngày mới. Fix:
- `run_update(workers=8)` — ThreadPoolExecutor song song (fetch I/O-bound, mỗi mã
  ghi thư mục riêng → an toàn). `--workers` (mặc định 8; 1 = tuần tự cũ). → ~18
  phút thay vì 3h, 0 lỗi với 8 luồng (user verify 16/06).
- `update_ticker(skip_stale_days=N)` — bỏ qua mã có bar cuối cũ hơn N ngày TRƯỚC
  khi fetch. `--skip-stale-days` (mặc định 0 = tắt).
- Nút dashboard "📥 Cập nhật giá" → `--force --workers 8 --skip-stale-days 90`;
  `run.py sync` (pipeline tối) tự hưởng 8 luồng (không skip-stale → vẫn thorough).
- API rate-limit (nhiều "error") → giảm `--workers 4`.

**Quan trọng — vnstock 4.0.4 + sponsor API gotchas** (hard-won, đừng quên):
- `vnstock_auth._StockShim` PHẢI expose `.quote/.company/.listing/.finance`.
  Thiếu `.finance` → `vnstock_fundamental_updater` chết. Pattern: ưu tiên
  `vnstock_data` (sponsor) rồi fallback `vnstock.api.*`.
- VCI ratio/statement trả **nhãn tiếng Anh** (P/E, ROE (%), Debt/Equity,
  Financial Leverage, "Net cash from/flows from operating activities"…),
  KHÔNG phải tiếng Việt. Cột năm là `report_period`.
- **Ngân hàng**: ratio table để Debt/Equity = 0 → tính D/E từ balance sheet
  (`TOTAL LIABILITIES / OWNER'S EQUITY`). D/E bank ~9-17 là bình thường.
- Ratio `iloc[0]` có thể là row TTM/interim NaN → dùng `_best_ratio_row`
  (lấy row gần nhất có P/E/ROE/D-E thật).
- **Cash flow `operating_cf` (DONE 2026-06-09 — đừng regress)**: VCI `cash_flow`
  TRỘN cả dòng NĂM ("2025") lẫn dòng QUÝ ("2025-Q1".."2026-Q1") trong cùng df.
  `_latest_row` cũ lấy quý dở dang (FPT 2026-Q1 = -2.847,8 tỷ, âm do WC đầu năm)
  → mis-flag. `_annual_operating_cf` nay: parse năm từ `report_period`, lấy **năm
  hoàn tất gần nhất** (year < năm hiện tại — loại năm dở), trong năm đó **ưu tiên
  dòng "năm thuần"** (report_period khớp đúng 1 năm) thay vì cộng 4 quý (cộng cả
  hai = gấp đôi!). FPT FY2025 đúng = 10.136 tỷ. Soi bằng `--diag <ticker>`
  (in "OCF theo kỳ gần nhất" + giá trị parse).
- `.env` PHẢI được load TRƯỚC khi agent kiểm tra `is_available` — brief gọi
  `_ensure_env_loaded()` đầu `generate_brief()`; telegram gọi `_load_env()`
  đầu `push_*_brief()`. Nếu không, chạy từ CLI fresh sẽ báo "no agent".

---

## 📌 Pending suggestions (raise when relevant)

### 1. Auto-schedule `vnstock_train.py` (NOT YET SET UP)

**Status**: User chose to run manually for now (decided 2026-04-27).

**When to bring up again**:
- User mentions running `vnstock_train.py` and forgets / runs late
- User asks about automation, scheduling, or "letting it run on its own"
- User reports inconsistent / outdated training data
- User says brief quality is plateauing

**What to suggest**:
Set up Windows Task Scheduler (or cron on Linux) to run `python vnstock_train.py --once`
on a daily cadence aligned with VN market sessions:
- 11:35 (after morning session close) — optional
- 15:05 (after full close) — primary slot

PowerShell command ready to paste:
```powershell
schtasks /Create /SC DAILY /ST 15:05 /TN "VNStock Train" `
  /TR "<repo>\.venv\Scripts\python.exe <repo>\vnstock_train.py --once"
```

**Why daily and not continuous**: VN market data refreshes 1×/day. Running
the training loop more often wastes API tokens without new information.
The system is API-based (Claude/Groq/Mistral) — there are no model weights
to fine-tune locally; "training" here means refreshing prompt few-shots,
re-running strategy generation/backtest, and reconciling recommendations.

### 2. ✅ Xác nhận OpenRouter hoạt động (DONE 2026-05-18)

**Status**: Đã xác nhận — "🔌 Test" trả về **Kết nối OK** với model `meta-llama/llama-3.3-70b-instruct:free`.

### 3. ✅ Tách nút Quét tín hiệu + Dynamic training universe (DONE 2026-04-28)

**Commit**: `8485962`

- Nút "🔍 Quét tín hiệu toàn thị trường" tách biệt khỏi training buttons
- `emit_recommendations()` lọc vol ≥ 100K cổ/ngày (30-day avg)
- `_training_universe()` dynamic: live API → warehouse filter → volume rank
  - Lite: sector-stratified top-10 VN30 + top-7 VNMID = ~17 mã
  - Full: VN30 đủ + top-20 VNMID = ~50 mã
- `_sector_stratified()`: max 3 bank slots, 1 slot/ngành khác — không bao giờ cluster ngân hàng

---

## 🔧 Future improvements — tracked TODOs

### 0. NN ròng 1D — full-market source `vnstock_foreign_flow.py` (DONE 2026-06-12, CẦN USER VERIFY)

**Bug cũ (12/06)**: brief in "NN ròng 1D −665 tỷ … phiên hôm nay" SAI cho cả 2
phiên (thực 11/06 = −504, 12/06 = −491). Hai nguyên nhân:
1. **Top-100**: `vnstock_dashboard._fetch_foreign_net_flow(limit=100)` chỉ lấy
   top-100 mã foreign buy/sell → tổng net **thổi phồng bán ròng** (thiếu đuôi
   small-cap mua ròng + mã chỉ có ở top-sell mất vế mua).
2. **Stale**: cache `nn_flow_cache.json` CHỈ được ghi khi mở tab Money Flow trên
   Streamlit; `_load_nn_net_1d` đọc thẳng JSON **bỏ qua tuổi** → brief hiện giá
   trị ĐÓNG BĂNG (−665 y hệt cho 2 phiên khác nhau).

**Fix**: module mới `vnstock_foreign_flow.py` — fetch FULL universe
(`limit=3000`) qua `TopStock.foreign_buy/sell`, tính market-total net THEO TỪNG
NGÀY, cache `_meta/foreign_net_daily.json`. `load_market_net_1d(effective_date)`
trả net của ĐÚNG phiên (hoặc None → brief BỎ signal, không bao giờ hiện số stale).
`vnstock_regime._load_nn_net_1d(effective_date)` nay ưu tiên nguồn này (bỏ hẳn
top-100 stale); `vnstock_market_sentiment.load_market_sentiment` truyền
`vnindex_tech["data_date"]` xuống. Pipeline: thêm bước `foreign-flow` vào
`run.py all` (best-effort) — `python run.py foreign-flow --days 5`.

**⚠️ CẦN USER VERIFY (tôi không có network/data ở sandbox)**: chạy
`python vnstock_foreign_flow.py --diag 2026-06-12` → in net + **số mã** trả về.
Nếu khớp ~−491 và vài trăm mã ⇒ OK. Nếu chỉ ~100 mã ⇒ API đang cap `limit`, cần
tăng `--limit` hoặc đổi nguồn (xem mục 1 bên dưới về các nguồn đã thử).

### 1. Replace calibrated GTGD estimate with exact realtime source

**Status**: Currently using Option A — `vnstock_data Quote.history(interval='1m')`
intraday cumulative volume × per-index calibrated `avg_price/share` (computed
weekly from `Trading.price_history` last 10 days). Accuracy ~95-98% during
trading; auto-corrected to exact via `reconcile_with_price_history()` when
the EOD batch posts ~24h after market close.

**Why estimate**: vnstock_data does NOT expose realtime `total_value` for
indices. We exhaustively tested (see commit history of `_test_market_sources.py`):
- ❌ SSI iboard public URLs — all 404 (need DevTools URL discovery)
- ❌ cafef.vn public URLs — all 404
- ❌ `Trading.price_history` — EOD batch only, ~24h delay
- ❌ `Trading.put_through` — block deals only (~16% of total GTGD)
- ❌ `Trading.trading_stats / order_stats / side_stats` — `NotImplementedError`
- ❌ `Quote.intraday(VNINDEX)` — `ValueError: Invalid symbol`
- ❌ `Quote.history` columns — only OHLCV, no `total_value` for indices

**To improve when ready**:
1. Reverse-engineer real iboard.ssi.com.vn URL via browser DevTools network tab
   (look for XHR with `totalValue` / `totalNmValue` field)
2. Or test `price_board(all_HOSE_stocks)` batch latency — if <5s for 500
   symbols, can aggregate `match_price × accumulated_volume` per stock
3. Or use cafef live websocket if it exists
4. UPCOM symbol for `price_history` is unknown — currently tries fallbacks
   `["UPCOM", "UPINDEX", "UPCOM-INDEX", "HNXUPCOM"]`. Find the correct one.

**Files affected**: `vnstock_session_stats.py`, `dashboard/screener_tab.py`
(UI status indicator 🟡 estimate / 🟢 exact). Schema bumped to
`SESSION_STATS_FORMAT_VERSION = 3` to invalidate old data.

---

## ⚠️ Hard-won invariants — DO NOT change without reading this

### 4-panel chart sync (Price / Volume / RSI / MACD) — vnstock_dashboard.py

**MUST use logical-range API, never time-range API.**

```
subscribeVisibleLogicalRangeChange  ✓
getVisibleLogicalRange              ✓
setVisibleLogicalRange              ✓

subscribeVisibleTimeRangeChange     ✗  DO NOT USE
getVisibleRange                     ✗  DO NOT USE
setVisibleRange                     ✗  DO NOT USE
```

**Why**: `setVisibleRange({to: lastBarTime})` tells LWC the chart is at
"live position" and triggers a right-edge snap — all 4 panels lock to the
rightmost bar whenever the user pans right. Logical range uses bar indices
(floats, 0 … N-1+rightOffset); LWC never treats these as a time boundary.

**Prerequisite**: all 4 charts must have IDENTICAL bar counts. RSI/MACD
warmup bars (first ~14 / ~33 bars with no value) MUST be emitted as LWC
whitespace `{time: t}` (no `value` key), NOT skipped. If they are skipped,
the bar-count mismatch breaks the 1:1 logical-index mapping and re-introduces
the snap. See the data serialization loop (~line 2394) in `vnstock_dashboard.py`.

**Other rules in the same sync block**:
- Never call `setVisibleLogicalRange` from inside `subscribeVisibleLogicalRangeChange`
  on the same chart — corrupts LWC pan state (drag becomes zoom).
- `_ready` gate: keep callbacks suppressed until the initial
  `setVisibleLogicalRange` fires at T=200ms (prevents RSI/MACD auto-fit
  from polluting the range before the uniform initial view is applied).

---

## 🏗️ Architecture cheat sheet

- `vnstock_brief.py` — agent abstraction + brief generation + memory wiring
  - context blocks: VNINDEX tech, regime, breadth, **market sentiment**,
    **sector money flow**, **VN30 fundamentals**, news, recommendations
  - `effective_trading_date()` → brief dùng ngày phiên gần nhất (cuối tuần /
    sáng sớm dùng data ngày T-1 thay vì báo "chưa có data")
- `vnstock_market_sentiment.py` — composite "tâm lý thị trường": breadth +
  NN ròng + RSI/MA + news → mood label + momentum (-100..+100)
- `vnstock_fundamental_updater.py` — CLI tải P/E/ROE/**D-E**/**cash flow** →
  `fundamentals.parquet`. `--diag <ticker>` để soi raw API output.
- `vnstock_sentiment.py` — chấm sentiment tin (Groq→Cerebras→OpenRouter),
  cache SQLite. `market_news_sentiment()` = aggregate toàn thị trường.
- `vnstock_memory.py` — SQLite store at `data_warehouse/_meta/brief_memory.db`
- `vnstock_strategy.py` — AST-sandboxed strategy executor + backtest engine
  - Sandbox: `InProcessExecutor` (Option A). Swap to `SubprocessExecutor`
    in `vnstock_strategy.py` when paranoid mode needed (Option B).
- `vnstock_train.py` — CLI orchestrator: `--once` / `--briefs-only` /
  `--strategy-only` / `--reconcile-only` / `--schedule`
- `dashboard/market_tab.py` — Streamlit UI: AI Brief panel + ⭐ rating +
  strategy/recommendation panel
- `vnstock_sectors.py` — **canonical custom sector groupings** (pure, dep-free)
  dùng chung bởi dashboard tab + brief pipeline (DONE 2026-06-30). Registry
  `_CUSTOM_GROUPS` (có THỨ TỰ) → `custom_sector_for(ticker)` + `CUSTOM_SECTOR_ORDER`
  + `CUSTOM_FAMILY`; `_build_lookup` chống 1 mã ở 2 họ. **Thêm họ mới = thêm 1
  dòng `(label, {tickers})`** — cả dashboard lẫn brief tự hưởng. Hiện có:
  **"Họ VIN"** {VIC, VHM, VRE, VPL} và **"Họ M"** {GEX, EIB, VIX, VGC, VSC, GEE,
  GEL} (Gelex eco). EIB là ngân hàng nhưng vào "Họ M" ở sector flow; per-ticker
  vẫn "Ngân hàng" nên `financial_tickers` vẫn loại đúng.
  - Money flow tab: `_mf_sector = custom_sector_for(tk) or _get_sector(ind)`;
    `_MF_SECTOR_ORDER = [*CUSTOM_SECTOR_ORDER, *SECTOR_ORDER]` (**pin các họ lên
    đầu, theo thứ tự registry**); icon `_MF_SECTOR_ICONS` (🅥 / Ⓜ️); áp mọi
    sub-table. `SECTOR_ORDER`/`_get_sector` chung KHÔNG đổi (training/portfolio
    giữ nguyên).
  - Brief: `compute_market_overview` (vnstock_runner) relabel CHỈ **sector
    aggregation** (`merged["ticker"].map(custom_sector_for).fillna(industry)` →
    cột `_sector_group` trước groupby) → `sectors` có row mỗi họ cho
    `_sector_flow_block` ("Dòng tiền ngành") + lead/lag + guard NN ngành;
    **per-ticker "Ngành" GIỮ thô** → `realestate_tickers`/`financial_tickers`/
    Op.CF context KHÔNG bị phá. Cần recompute market_overview (run.py screener
    hoặc brief auto-refresh) để có hiệu lực.

API keys live in `.env` (auto-loaded by `python-dotenv`):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`,
`DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`.

Dashboard tab files:
- `dashboard/market_tab.py` — Thị trường: AI Brief + training + recommendations
- `dashboard/analysis_tab.py` — Phân tích cổ phiếu (có FUTURES/INDEX fallback)
