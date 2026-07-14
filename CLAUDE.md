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
  `vnstock_macro.py`, `vnstock_news_feeds.py`, `vnstock_doctor.py`,
  `vnstock_allocation.py`, `vnstock_reports.py`, `vnstock_report_digest.py`,
  `vnstock_gold.py`, `vnstock_scorecard.py`
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
    **`enforce_net_flow_label`** (DONE 2026-06-30, chạy SAU 2 cái trên) — dạng
    *verb→số→tên* "bán ròng +129 tỷ … Ngân hàng" mà 2 guard trên KHÔNG bắt
    (two_sides chỉ pin magnitude, sector_nn cần tên TRƯỚC verb). Close 30/06:
    "bán ròng **+**129 tỷ … Ngân hàng" (net SELL mà dấu +). Với mỗi ngành ctx có
    tên ngay sau "(mua|bán) ròng <số> tỷ" mà magnitude khớp |NN 1T| (≥30 tỷ,
    two_sides đã pin sẵn) → set verb theo DẤU(NN) + in magnitude không dấu (verb
    mang chiều). Idempotent.
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
    **Form C (DONE 2026-06-30)**: % INLINE có DẤU rõ, KHÔNG ngoặc (close 30/06:
    "GTGD … cao hơn **-41%** so với phiên trước và 37% so với TB20"). CHỈ tác động
    khi dấu clash với từ → lật từ + BỎ dấu ("thấp hơn 41% so với phiên trước");
    gate "có dấu rõ" giữ idempotent (lần 2 số trần → bỏ qua); vế 2 không dấu để
    nguyên cho người đọc. Cần "so với"/"so" sau % để chắc là mệnh đề so sánh.
    **Mở rộng 01/07**: Form C nay bắt CẢ động từ đổi "tăng/giảm" (không chỉ cao/thấp
    hơn). Động từ MANG chiều → verb theo DẤU + LUÔN bỏ dấu: "tăng -10%"→"giảm 10%",
    "giảm -10%"→"giảm 10%", "giảm +42%"→"tăng 42%" (khác cao/thấp hơn: chỉ lật khi
    clash). Sau khi `enforce_gtgd_baseline_pct` pin "-10" vào "tăng … so với phiên
    trước" → Form C ra "giảm 10% so với phiên trước".
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
    phiên) để nguyên (không có số để pin); idempotent. **Fix over-capture 01/07**:
    khi 2 vế nối bằng "và" KHÔNG có phẩy ("tăng 0.39% so với phiên trước **và** tăng
    42% so với TB5"), group3 (baseline) của Form 1 nuốt luôn cả vế sau → "trung
    bình"+"5" khiến `_base_v` đọc NHẦM "phiên trước" thành TB5 → vế phiên trước
    không bao giờ pin (0.39% = đổi index bị mượn). Lookahead nay dừng ở "và"/"nhưng"
    → mỗi vế classify đúng (phiên trước→prev, TB5→avg5).
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
28. `enforce_stance_sentiment_caution` (DONE 2026-06-30) — **soft floor**: hard
    floor `_bias_floor_dir` chỉ ép GIẢM khi momentum ≤ -50 / regime ≤ -3; band
    nhẹ hơn (momentum ≤ `_STANCE_CAUTION_MOMENTUM` = -20, vùng "Tiêu cực") KHÔNG
    ép đổi stance mà CHÈN 1 dòng cảnh báo dưới dòng Stance/Bias khi stance nghiêng
    **TĂNG** (close 30/06: "Stance ngày mai: TĂNG" trong khi tâm lý 📉 Tiêu cực
    momentum -24 → bullish vẫn được phép nhưng gắn "ưu tiên quản trị rủi ro, chỉ
    gia tăng khi giá XÁC NHẬN, tôn trọng cắt lỗ"). Detect token ĐẦU sau "Stance
    ngày mai:"/"Bias:" (cả 2 brief); no-op khi stance GIẢM/TRUNG TÍNH hoặc momentum
    > -20; idempotent qua marker `_STANCE_CAUTION_MARK`. (Triết lý: gắn ngữ cảnh,
    không override — mirror BUY-vs-bias caveat.)

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
sync EOD → validate → screener → news → test → audit → doctor — trọn quy
trình tối, sau giờ đóng cửa) · **VnStock Weekly Corp Actions** CN 09:00
(Vietstock cổ tức/chia tách → registry) · **VnStock Fundamentals** T2 08:00
(1×/tuần, `--force --workers 4 --delay 1` — **fix 2026-07-10: trước đó task
chạy KHÔNG --force = incremental skip mã đã có → NO-OP từ sau lần đầu, số
đóng băng**; mùa BCTC giữa tháng 1/4/7/10 chạy thêm tay). Sự kiện GDKHQ KHÔNG
cần task — brief tự refresh 1×/ngày (VN30 + top-40 movers). Kiểm tra:
`Get-ScheduledTask -TaskName "VnStock *"`. **Task đăng ký THEO MÁY** — đổi
máy (vd desktop mới 10/07) phải chạy lại setup script trên máy đó; script tự
detect venv nên chạy sau khi venv + `pip install -r requirements.txt` đã có.

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

### 🌐 Vĩ mô: lãi suất & tỷ giá + CPI/IIP/PMI (DONE 2026-06-14, mở rộng 2026-07-08) — `vnstock_macro.py`

**Mở rộng 2026-07-08 (P2/P3/P5 từ khảo sát vimovietnam — CẦN USER VERIFY
`python vnstock_nso.py --diag` trên máy có mạng; sandbox chặn nso.gov.vn):**
- **`_DEFS` nay mang TOÀN BỘ metadata** (decimals / delta_unit / moves /
  pressure {mode,scale,min,sign}) → thêm chỉ số mới = thêm 1 entry, KHÔNG
  if/elif theo kind ở chỗ khác. `fmt_value`/`fmt_change` public — brief
  `_macro_line` delegate về đây (CLI ↔ brief không thể lệch nhau);
  `macro_pressure_score` generic theo metadata (sign=-1: tăng bất lợi — lãi
  suất/tỷ giá/CPI; sign=+1: tăng thuận lợi — IIP/PMI).
- **`gdp_yoy` + `trade_balance` AUTO từ NSO (A+B, DONE 2026-07-08)** — cùng bài
  đã fetch, zero request mới. GDP: regex riêng (cửa sổ chung cố tình cắt tại
  "quý"), CHỈ có trong bài quý → 4 lần/năm, giữa các quý giữ reading cũ (as_of
  hiện rõ). Cán cân thương mại: bắt buộc chữ "tháng" giữa anchor và "xuất/nhập
  siêu" → số LŨY KẾ 6 tháng không lọt; "triệu USD"/1000; nhập siêu = ÂM.
  Registry cap: 2026-07-08 dừng ở 10 → **2026-07-10 nới 10→11** cho
  `govt_bond_yield_2y` (khảo sát VnBondLab, cùng PDF VBMA) → **2026-07-11 user
  "làm tất cả" khảo sát public-apis: nới 11→13** cho `us10y` + `fed_funds`
  (FRED — mở khóa trụ 3 VnBondLab + bỏ lệnh cấm-bịa-Fed). 13 là cap hiện hành —
  thêm nữa phải bỏ bớt; credit growth vẫn để dành, chỉ làm nếu brief thiếu ngữ
  cảnh khi có tin tín dụng lớn. Directive brief: GDP đã BỎ khỏi danh sách cấm
  bịa; mệnh đề cấm Fed nay ĐỘNG — tự nới khi `fed_funds` có reading
  (`_macro_body_lines` check key, guard dùng chung nên parity giữ).
- **`cpi_yoy` + `iip_yoy` AUTO từ NSO** (`vnstock_nso.py`, mirror vnstock_vbma):
  listing `nso.gov.vn/bao-cao-tinh-hinh-kinh-te-xa-hoi-hang-thang/` → bài
  `/bai-top/{YYYY}/{MM}/bao-cao-…-thang-…` publish-tháng lớn nhất (KHÔNG dựng
  URL từ slug — NSO có bài ghi NHẦM năm trong slug) → strip HTML → regex câu
  công thức "CPI tháng X tăng/giảm N% so với tháng trước/cùng kỳ" (bẫy đã chặn:
  "so với tháng 12/2025" ≠ MoM vì thiếu "trước"; cửa sổ cắt tại "bình
  quân"/"quý" để không lấy YoY bình quân; ngành con IIP đứng sau headline —
  first-match thắng; NSO dùng PHẨY thập phân). as_of = cuối THÁNG DATA (=
  tháng publish − 1; công bố ~mùng 3). Fixtures = số thật T6/2026 (CPI −0,39
  MoM/+4,69 YoY; IIP +3,5/+12,7). Tắt: `VNSTOCK_MACRO_NSO=0`.
  **TLS ladder (diag thật 08/07)**: nso/gso.gov.vn KHÔNG gửi chứng chỉ trung
  gian → certifi fail `SSLCertVerificationError` (browser tự vá qua AIA nên
  vẫn mở được). `_http_get` leo 3 nấc: certifi → OS trust store (Windows) →
  verify=False CHỈ CHO NGUỒN NÀY (data công khai chỉ đọc + sanity range;
  `VNSTOCK_NSO_TLS_STRICT=1` để cấm nấc cuối).
- **`pmi` (P3)**: nguồn chính `--set pmi <số>` mùng 1-2 hàng tháng (URL S&P đổi
  hash mỗi tháng → không crawler); nguồn phụ `_pmi_from_news()` regex "XX,X
  điểm" trên tiêu đề RSS cache SẴN CÓ (không fetch; bỏ tiêu đề PMI nước ngoài
  `_PMI_FOREIGN`; sanity 25-75; CHỈ ghi khi tin mới hơn reading hiện có — không
  đè --set). Tắt: `VNSTOCK_MACRO_PMI_NEWS=0`. Regex neo "điểm" chứ KHÔNG đo
  khoảng cách tới chữ PMI (giữa chúng có chữ số "tháng 6/2026" → gap [^\d] trượt).
  **Nhắc quên set (2026-07-08)**: `pmi_reminder(macro, today)` — từ MÙNG 3 (mùng
  1-2 là ân hạn cho đường RSS) mà PMI tháng trước chưa vào registry (as_of <
  mùng 1 tháng nay) → dòng "⏰ PMI tháng X chưa được cập nhật … --set pmi <số>"
  chèn vào block Vĩ mô của brief (qua `_macro_body_lines` dùng chung → guard
  giữ nguyên) + CLI `--show`. Đã có số → im lặng.
- **Cross-check tỷ giá (P5)**: `_parse_fx` trong vnstock_vbma lấy trung bình
  mua/bán Vietcombank từ văn xuôi PDF (cả 2 chế độ extract; pypdf DÍNH chữ
  "ởchiều bán" đã xử) → `_fx_crosscheck` so với er-api, lệch >2% in cảnh báo +
  cờ `fx_crosscheck` trong cache (hiện ở `--show`); trong ngưỡng thì XÓA cờ.
  So er-api với VCB chứ KHÔNG với tỷ giá TRUNG TÂM (trung tâm ~25.2k vs market
  ~26.3k — lệch ~4% bẩm sinh, so nhầm là báo động giả).
- **Gauge thanh khoản dẫn xuất (DONE 2026-07-08, từ sơ đồ Hedge Academy)**:
  `liquidity_spread(macro)` = ON − lãi suất điều hành (điểm %) + dốc 10Y − ON;
  band: > +0.5 → CĂNG (dir −1), < −1.5 → DƯ THỪA (dir +1), giữa → bình thường
  (`_LIQ_TIGHT_SPREAD`/`_LIQ_FLUSH_SPREAD`). Zero fetch — dẫn xuất từ 2 chỉ số
  sẵn có; hiện ở brief (`_macro_body_lines` dùng chung → guard/parity tự giữ),
  CLI `--show`, sub-tab Vĩ mô. LEVEL-gauge thuần hiển thị, KHÔNG vào pressure
  score (score là change-based). OMO/tiền gửi KBNN trong sơ đồ = KHÔNG làm
  (không có nguồn free ổn định; tin "bơm/hút ròng" đã có trong _MACRO_KEYWORDS).
- **Gauge kỳ hạn & đường cong (DONE 2026-07-10, từ khảo sát VnBondLab/Macro
  Alert System — 2 trong 4 "trụ cột" cảnh báo của nó tính được thuần từ
  registry)**: `term_spread(macro)` = 10Y − lãi suất điều hành ("Taylor-rule
  xấp xỉ"; < 0 → ÂM dir −1 = chính sách THẮT so kỳ vọng dài hạn, < +0.5 →
  "mỏng") + dốc **10Y − 2Y** khi có 2Y (< 0 → ĐẢO NGƯỢC dir −1 = bond market
  định giá rủi ro chu kỳ, < +0.3 → "phẳng"; `_TERM_THIN_SPREAD`/`_YC_FLAT_SLOPE`).
  Nguồn 2Y: `vnstock_vbma._parse_bond_yields` (generalize từ `_parse_bond_10y`)
  nhặt cột 2N từ CÙNG dòng ngày của ma trận tenor — 10N là NEO (dòng thiếu 10N
  hợp lệ bị bỏ); thêm kỳ hạn mới = thêm 1 entry `_YIELD_TENORS` + `_RANGES` +
  `_DEFS`. Cùng triết lý liquidity_spread: zero fetch, LEVEL-gauge thuần hiển
  thị (brief qua `_macro_body_lines` dùng chung → parity/guard tự giữ, CLI
  `--show`, sub-tab Vĩ mô), KHÔNG vào pressure score. Số thật 03/07/2026: 10Y
  4.40 < điều hành 4.5 → spread −0.10 ÂM (nhất quán gauge thanh khoản CĂNG);
  dốc 2-10 +0.90 bình thường. Trụ percentile lịch sử vẫn để dành (cần ~1 năm
  mẫu VBMA weekly — cache giữ 60 readings, đủ thì nâng band tĩnh → percentile).
- **FRED: us10y + fed_funds + gauge quốc tế (DONE 2026-07-11, từ khảo sát
  public-apis — CẦN USER: đăng ký key free ~2 phút
  https://fred.stlouisfed.org/docs/api/api_key.html → `FRED_API_KEY=<key>`
  vào .env, rồi verify `python vnstock_fred.py --diag` trên máy có mạng)**:
  `vnstock_fred.py` (mirror vbma/nso) fetch DGS10 + DFF qua API JSON chính
  thức, skip value "." (ngày nghỉ), sanity range, as_of RIÊNG từng series;
  không key → None, refresh bỏ qua (best-effort, KHÔNG bịa). Tắt:
  `VNSTOCK_MACRO_FRED=0`. → `intl_spread(macro)` = VN10Y − US10Y ("trụ 3"
  VnBondLab từng bỏ vì thiếu nguồn): ÂM (dir −1) = VN kém hấp dẫn vốn ngoại
  → áp lực tỷ giá/NN bán ròng; < +0.5 → "mỏng" (`_INTL_THIN_SPREAD`).
  LEVEL-gauge thuần hiển thị như 2 gauge kia (brief `_macro_body_lines` dùng
  chung → parity/guard tự giữ, CLI `--show` dòng "→ Quốc tế", sub-tab Vĩ mô);
  KHÔNG vào pressure score. Doctor: cadence 7d cho 2 chỉ số + net check
  `net_fred` (chưa có key → ⬜ kèm link đăng ký). Trụ 4 VnBondLab duy nhất
  còn lại = percentile lịch sử (chờ đủ mẫu).
- **FX ladder nay 3 NẤC (2026-07-11)**: er-api → exchangerate.host →
  **currency-api (fawazahmed0)** — nguồn từ khảo sát public-apis (2 nấc đầu
  cũng nằm trong chính danh mục đó): free, KHÔNG rate limit, host CDN
  jsdelivr + fallback pages.dev, payload `{"usd":{"vnd":…}}` CHỮ THƯỜNG
  (parser fetch_usdvnd đã hiểu cả 2 dạng).
- **Brief nén block vĩ mô**: `_macro_body_lines` gộp mọi chỉ số KHÔNG đổi vào
  1 dòng "Đi ngang/chưa có kỳ mới: …" (8 chỉ số không nở 8 bullet); chỉ số có
  thay đổi giữ bullet riêng. Directive cập nhật (CPI/IIP/PMI nay CÓ data — chỉ
  còn cấm bịa Fed/GDP). Guard `enforce_macro` dùng chung builder → parity tự giữ.
- **Test hermetic**: mọi test gọi `mac.refresh()` PHẢI patch `_fetch_nso` +
  `_pmi_from_news` (autouse fixture trong test_macro/test_vbma; test_nso patch
  trong helper) — không thì refresh chạm mạng NSO / đọc cache repo thật.

**(Gốc 2026-06-14)** — lấp khoảng trống "tin VĨ MÔ — lãi suất/tỷ giá" mà block
"🔧 Đề xuất bổ sung" lâu nay vẫn xin. Cache `_meta/macro_indicators.json`
(history theo ngày/chỉ số), brief nạp qua `load_macro(effective_date)`:
- **`usdvnd`** (tỷ giá USD/VND tham chiếu) — AUTO-fetch best-effort từ API FX
  miễn phí (`open.er-api.com` → fallback `exchangerate.host`). Mạng bị chặn /
  API lỗi → GIỮ cache cũ, KHÔNG bịa.
- **`sbv_policy_rate`** (lãi suất tái cấp vốn) — SEED 4.5%/năm as_of 2023-06-19
  (nguồn "seed"); đổi vài lần/năm → cập nhật tay khi SBV ra quyết định.
- **`interbank_on` / `interbank_1w` / `govt_bond_yield_10y`** — **AUTO từ báo
  cáo tuần VBMA (DONE 2026-07-07, CẦN USER VERIFY `python vnstock_vbma.py
  --diag` — sandbox chặn `vbma.org.vn`)**: `vnstock_vbma.py` scrape listing →
  tải PDF tuần free → `pdftotext -layout`/`pypdf` → regex bảng theo SECTION
  (chống false-positive chữ "on" tiếng Anh) + sanity range; as_of = ngày cuối
  tuần báo cáo; tắt bằng `VNSTOCK_MACRO_VBMA=0`; parse lỗi → giữ cache cũ,
  `--set` tay vẫn là đường sống. (Nguồn phát hiện khi khảo sát skill
  vimovietnam.) Trước đó nhập tay vì đã thử auto từ **Vietstock** VNIBOR
  (`getdatabynormid` normid 66):
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
thêm host vào egress allowlist (web session). **Lãi suất**: LNH + lợi suất TPCP
nay auto qua VBMA weekly (xem trên); `sbv_policy_rate` vẫn nhập tay
(`python vnstock_macro.py --set sbv_policy_rate <số>` khi SBV ra quyết định).
Nếu có tài khoản Vietstock trả phí: `VNSTOCK_MACRO_VIETSTOCK=1` là nguồn LNH
thứ hai. RSS feeds mới 2026-07 (VnEconomy Tài chính / Báo Chính phủ KT / Báo
Đầu tư — nhóm policy/vĩ mô, từ khảo sát vimovietnam) là URL ứng viên **chưa
verify** — chạy `python vnstock_news_feeds.py --diag`, feed ❌ thì sửa/xoá.

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
  cache trong JSON nên không chấm lại. **`_ANALYZE_SYSTEM` (cập nhật 2026-06-30)**
  buộc CHIỀU `<tác động>` khớp tiêu đề — tin GIẢM/rời mốc/xuống → mô tả chiều
  GIẢM, KHÔNG ghi chiều ngược (vá lỗi "giá vàng GIẢM → PNJ hưởng lợi từ giá vàng
  CAO"). Là cải thiện PROMPT (không deterministic) → chỉ áp tin chấm MỚI; tin đã
  cache cần `python vnstock_news_feeds.py --reanalyze` để chấm lại.

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
- **Full text qua Jina Reader (DONE 2026-07-10, từ khảo sát Agent-Reach — CẦN
  USER VERIFY trên máy có mạng: `python vnstock_news_feeds.py --diag` có dòng
  Jina)**: `analyze_item` nay tự fetch THÂN BÀI qua `https://r.jina.ai/<URL>`
  (free, không cần key, URL→markdown sạch) và đưa vào prompt — trước đó LLM chỉ
  thấy title+description RSS, là gốc của loại lỗi đoán sai chiều tác động (vụ
  "giá vàng GIẢM → PNJ hưởng lợi giá CAO" 30/06). CHỈ fetch cho tin ĐƯỢC chấm
  (≤ `_MAX_ANALYZE_DEFAULT`=8/refresh) nên số request nhỏ; best-effort đúng
  nghĩa: fail/timeout/chặn mạng → chấm bằng title+summary như cũ, KHÔNG lưu
  full text vào cache (chỉ dùng tại chỗ, `_FULLTEXT_MAX_CHARS`=1800 vào prompt).
  Tắt: `VNSTOCK_NEWS_FULLTEXT=0` hoặc `--no-fulltext`; có `JINA_API_KEY` trong
  .env thì gửi kèm (nới rate-limit ~20 req/phút của bản không key), không có
  vẫn chạy. Sandbox/web session: r.jina.ai bị allowlist chặn (403 CONNECT,
  verify 10/07) → luôn '' ở đây, KHÔNG phải bug. Đây là cải thiện INPUT cho
  prompt (không deterministic) — tin đã cache giữ điểm cũ, muốn chấm lại chạy
  `python vnstock_news_feeds.py --reanalyze`.

### 🩺 Doctor — khám sức khỏe MỌI nguồn dữ liệu (DONE 2026-07-10) — `vnstock_doctor.py`

Gom các `--diag` rải rác (news_feeds/macro/vbma/nso/foreign_flow/events/
fundamentals) về MỘT lệnh, theo mô hình doctor của Agent-Reach (check THẬT +
đơn thuốc sửa cụ thể cho từng nguồn, một nguồn nổ không kéo sập báo cáo):

```powershell
python run.py doctor          # OFFLINE <1s: tuổi cache + key .env
python run.py doctor --net    # + probe mạng: RSS/FX/VBMA/NSO/foreign-flow API/Jina
```

- **2 tầng**: OFFLINE so tuổi data với `_prev_trading_day` (T2-T6 — sáng thứ 2 /
  trước pipeline 18:00 KHÔNG báo động giả); NET fetch thử từng nguồn ngoài —
  chạy trên MÁY CÓ MẠNG (sandbox bị allowlist chặn → toàn ❌ là bình thường).
  Riêng kho VNINDEX dung sai **2 phiên** (bar index qua API EOD về trễ ~1 phiên
  so với cổ phiếu — verify trên máy user 10/07: overview 07-09 tươi nhưng bar
  VNINDEX mới tới 07-08; đây là lý do tồn tại `_augment_with_live_vnindex`).
- **Trạng thái**: ok ✅ · warn ⚠️ (cũ/thiếu một phần) · off ⬜ (chưa cấu hình/chưa
  chạy — KHÔNG tính vào exit code) · error ❌. Exit 1 khi có warn/error.
- **Check đáng chú ý**: vĩ mô so as_of TỪNG chỉ số với cadence nguồn của nó
  (`_MACRO_MAX_AGE_DAYS`: FX 5d, VBMA 12d, NSO 45d, GDP 120d; sbv_policy_rate
  nhập tay → không bao giờ cũ) + nhắc PMI; foreign-flow cảnh báo `n_symbols`
  ≤120 (= API cap limit, bug top-100 cũ); LLM keys tách "sentiment provider"
  vs "brief agent key"; NET có probe Jina Reader (feature full text ở trên);
  **PDF→text cho VBMA (thêm tối 10/07 sau bẫy thật)**: desktop user venv khác
  → thiếu pypdf → VBMA chết IM LẶNG (best-effort giữ cache cũ) — check offline
  `check_pdf_tooling` bắt ngay, pypdf đã vào requirements.txt. Chuỗi
  `run_checks` bắt cả **BaseException** (pyo3 PanicException từ native package
  hỏng — thấy thật khi import pypdf trên cryptography lỗi) nhưng vẫn re-raise
  KeyboardInterrupt.
- Kết quả ghi `_meta/doctor_status.json` → **badge 🩺 sidebar** dashboard
  (dưới badge test, cùng style; xám=off, vàng=warn, đỏ=error). `run.py all`
  chạy doctor (offline) làm bước CUỐI → badge tự tươi mỗi tối theo pipeline.
- Thêm nguồn mới = viết 1 hàm `check_*`/`net_*` trả `_result(...)` rồi thêm vào
  `OFFLINE_CHECKS`/`NET_CHECKS`. Tests: `tests/test_doctor.py` (đã vào danh
  sách `--fast`); mọi check đọc dưới `_META` (tests monkeypatch được).

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
- **`vnstock_fundamental_updater` cũng có `--workers` (DONE 2026-07-10)** — cùng
  pattern (fetch trong ThreadPoolExecutor, ghi file CHỈ ở luồng chính qua batch
  save; `_fetch_one` tách riêng, không đụng file/console). Lý do: fundamentals
  ~3 call API/mã ≈ 7s → `--force` cả kho tuần tự mất ~3.5 giờ (user vướng thật
  10/07), 8 luồng còn ~25-30 phút. Mặc định 1 (tuần tự cũ). LƯU Ý kép: (a) chạy
  KHÔNG --force là incremental — chỉ fetch mã CHƯA CÓ trong parquet, mã cũ giữ
  số cũ → mùa BCTC phải `--force --workers 8`; (b) check fundamentals của
  doctor so MTIME file — lần chạy incremental cũng làm mới mtime nên badge ✅
  không có nghĩa số đã mới (TODO nhỏ: đổi check sang max updated_at/quý trong
  parquet). Test parity tuần-tự↔song-song: `tests/test_fundamental_cf.py`.
- **Rate-limit vnai = SystemExit, KHÔNG phải Exception (fix 2026-07-13,
  `vnstock_ratelimit.py`)**: "Cập nhật giá" 8 luồng CHẾT CỨNG ở 558/1724 mã khi
  chạm trần 500 req/phút Golden — mổ tận nơi `vnai/beam/quota.py:313`: hết
  lượt retry nội bộ vnai gọi `sys.exit("Rate limit exceeded ... Process
  terminated.")` → SystemExit xuyên mọi `except Exception` per-ticker, trong
  ThreadPool được `fut.result()` re-raise ở luồng chính → sập cả run (cùng họ
  bug PanicException của doctor). Fix: `call_with_rate_limit_retry(fn, ...)`
  bọc từng call fetch ở CẢ 2 updater (giá `_fetch_prices` + fundamentals cả 3
  call trong `_fetch_one`) — nhận diện message vnai, parse "Chờ X giây" (+2s,
  fallback 61s, cap 300s), ngủ rồi thử lại 3 lượt; hết lượt → RuntimeError
  (Exception thường) = 1 mã lỗi, run sống tiếp. SystemExit thật/KeyboardInterrupt
  re-raise nguyên vẹn. Tests: `tests/test_ratelimit.py` (message vnai thật làm
  fixture; test tích hợp updater giá skip khi thiếu vnstock — chạy đủ trên máy
  dev). Lưu ý vận hành: 2 tiến trình cùng chạy CHIA NHAU quota (task
  fundamentals T2 08:00 + bấm nút Cập nhật giá cùng lúc = dễ chạm trần — giờ
  chỉ chậm lại chứ không chết).

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

## 🧭 THIẾT KẾ ĐÃ DUYỆT — Báo cáo vĩ mô upload + Phân bổ tài sản (P1-P6 DONE 2026-07-13 — TOÀN BỘ ĐÃ BUILD, chờ user verify)

Ý tưởng user: upload báo cáo vĩ mô hay (CTCK/chuyên gia, cả Việt lẫn Anh) để
AI phân tích tình trạng vĩ mô VN → khuyến nghị rải ngân vào lớp tài sản nào.
Thiết kế đã qua vòng 3-góc-nhìn + critic (đối chiếu từng trích dẫn với repo);
user duyệt 2026-07-13 và chốt 5 tham số. **Lưu để RECHECK trước khi build —
nhắc khi user nói "phân bổ", "báo cáo", "allocation", "upload".**

**5 tham số user đã chốt:**
1. Báo cáo: vĩ mô đa nguồn (CTCK + chuyên gia), CẢ tiếng Việt và tiếng Anh
   → digest từ nguồn tiếng Anh phải DỊCH sang tiếng Việt (brief có luật
   thuần-tiếng-Việt + enforce_no_cjk).
2. Tần suất: 1-2 báo cáo/tháng → consensus view đa-báo-cáo giữ ĐƠN GIẢN ở v1.
3. Bảng B→% mặc định: Claude tự quyết (bảng dưới), là CONFIG user chỉnh được.
4. Brief phân bổ: CHỈ dashboard, KHÔNG đẩy Telegram (v1).
5. Lớp tài sản v1: **5 lớp — CÓ VÀNG ngay từ đầu** (user chọn, không để dành).

**Bảng B0-B4 → % mặc định (khẩu vị trung dung; convention VnBondLab: B0 =
rủi ro vĩ mô THẤP nhất = tấn công, B4 = căng thẳng = phòng thủ):**

| Band | Cổ phiếu | Trái phiếu | Tiền gửi | Vàng | USD |
|------|---------|-----------|----------|------|-----|
| B0 thuận lợi   | 70% | 10% | 10% |  5% | 5% |
| B1 tích cực    | 60% | 15% | 15% |  5% | 5% |
| B2 trung tính  | 45% | 20% | 20% | 10% | 5% |
| B3 thắt chặt   | 30% | 25% | 30% | 10% | 5% |
| B4 căng thẳng  | 15% | 25% | 40% | 12% | 8% |

**Kiến trúc (tóm tắt — chi tiết từng quyết định đã phán xử trong critic):**
- `vnstock_allocation.py` — **LÀM TRƯỚC, zero fetch/zero LLM**: score từ 3
  gauge (thanh khoản/kỳ hạn/quốc tế) + macro_pressure + regime + sentiment
  momentum + breadth → band B0-B4 + hysteresis (đổi band cần lệch ≥ ngưỡng
  2 phiên) → bảng % + lý do từng input (nguồn+as_of) → `allocation_state.json`
  + history log ĐỦ-ĐỂ-CHẤM-SAU ngay từ ngày 1. Báo cáo upload chỉ tilt ±1
  band, KHÔNG override data sống (mirror caveat 27/28).
- `vnstock_reports.py` — ingest: upload PDF (reuse `pdf_to_text` VBMA) +
  **paste URL/text qua Jina Reader** (đường sẵn có); dedup sha256 (idempotent
  Streamlit rerun); metadata BẮT BUỘC report_date+nguồn (thiếu → chỉ nằm thư
  viện, không vào phân tích); flag `no_text_layer` cho PDF scan; CLI đủ bộ.
- Digest: key Claude/GPT (1-2 call/báo cáo — TODO 1b đã ghi 70B free yếu;
  ladder free chỉ làm fallback), JSON schema {claims số+kỳ, stance/lớp
  (-2..+2), risks}, cho phép TRUNG_LẬP; **sanitize cấu trúc** (strip `##`/
  emoji-mục/CJK, số EN-format) để không phá section-parser guard chain;
  cross-check số với registry mirror `_fx_crosscheck` — **REGISTRY THẮNG**,
  lệch → cờ mismatch không vào brief; decay tuổi: giảm từ 30 ngày, weight=0
  ở 90 ngày; `--redigest`.
- Brief: block 📚 cap ~5 dòng chỉ-khi-tươi vào brief NGÀY + **brief_type=
  'allocation' RIÊNG cadence THÁNG** (không trộn — 2 thang thời gian; brief
  ngày chỉ 1 dòng ngữ cảnh band); nâng `_BRIEF_MAX_TOKENS` 2400→2800; guard
  mới `enforce_macro_reports` + `enforce_allocation_table` vào
  `apply_brief_guards` DÙNG CHUNG; band tháng lệch bias floor ngày → caveat
  horizon, KHÔNG override.
- Vàng: nguồn Goldprice.dev (Auth: No, mục để-dành 1c) — **display-only +
  proxy return, KHÔNG vào registry 13**; ghi rõ "spot quốc tế, CHƯA gồm
  premium SJC (15-20%)". Proxy return các lớp: VNINDEX / đổi-yield-10Y (proxy
  thô, dán nhãn) / policy rate / vàng spot / usdvnd.
- UI: 2 sub-tab Tin tức → "📚 Báo cáo" + "🧭 Phân bổ" (UI mỏng trên cache,
  scope như macro_tab); doctor `check_reports`+`check_allocation` (tuổi/
  mismatch/nhắc kỳ tháng mirror pmi_reminder); atomic write (tmp+rename) vì
  Streamlit upload đụng pipeline recompute.
- Scorecard hồi tố (sau ≥2 kỳ): đối soát band kỳ trước vs return thực từng
  lớp (mirror vnstock_reconciler); xếp hạng nguồn báo cáo LOG ngay, UI để
  dành khi đủ mẫu.

**3 nguyên tắc KHÔNG nhượng bộ:** (1) LLM không bao giờ sinh số %/band —
chỉ viết lời, guard pin; (2) số từ báo cáo KHÔNG vào registry 13 chỉ số
(tầng SỐ ĐO ≠ tầng QUAN ĐIỂM); (3) guard mới chỉ thêm vào
`apply_brief_guards` dùng chung + `run.py test --fast` sau mọi sửa brief.

**Phase + effort (điểm dừng nào cũng có giá trị độc lập):**
P1 allocation core ✅ → P2 ingest ✅ → P3 digest+cross-check+tilt ✅
→ P4 nối brief ✅ → P5 UI+doctor ✅ → P6 scorecard+vàng ✅ — XONG cả 6 phase
(build 1 phiên 2026-07-13, branch `claude/phase-1-kickoff-lzorv6`). Việc còn
lại: checklist VERIFY HOÃN LẠI ở trên, trên máy có data + mạng.

### ⏳ VERIFY HOÃN LẠI (user chốt 2026-07-13 "lưu việc phải test vào làm sau")

**Đã verify TRONG SANDBOX 2026-07-14 (integration end-to-end với data tổng
hợp — mọi CLI chạy thật, chuỗi nối thật):** fast suite 478 passed · allocation
tính band B3 từ 6 tín hiệu thật + hysteresis · ingest text → digest giả lập →
consensus tilt +1 → allocation ra `band_data B3 / band B4` + bảng % đổi theo ·
cross-check số sai (30,000) bị cờ mismatch với registry sống · build_prompt
allocation có bảng % + brief ngày có dòng band · guard pin band bịa B0→B4 +
thay bảng % canonical, idempotent · doctor 2 dòng mới ✅ đúng trạng thái ·
scorecard "chưa đủ kỳ" đúng thiết kế · gold hiển thị kèm nhãn premium.
**Bug bắt được khi verify + đã fix:** (1) gauge as_of hiện `2023-06-19` vì
phép min dính `sbv_policy_rate` (as_of = ngày SBV quyết định, không phải độ
cũ data) → loại policy rate khỏi min (nhất quán với doctor "không bao giờ
cũ"). (2) `vnstock_report_digest` CLI fresh không load `.env` trước khi
check key → `--diag` báo "không key nào chạy" dù .env đủ key (ĐÚNG bẫy đã
ghi ở mục gotchas — dính thật trên máy user 14/07) → `digest_call` nay gọi
`_ensure_env_loaded()` đầu tiên (mirror brief/doctor).

**Đã verify TRÊN MÁY USER 14/07:** fast suite 483 passed · allocation phiên
2026-07-13 band B4 (điểm −0.739, 6 tín hiệu, gauge as_of 2026-07-03 nhất
quán sau fix) · **gold endpoint SỐNG: 4,015.70 USD/oz** (mục cần-verify
quan trọng nhất của P6) · **digest ĐẠT trên đường FREE** (báo cáo
HedgeAcademy thật: Cerebras gpt-oss-120b @6000 token → stance CP -2 đúng
đáp án, claim fed_funds đúng số, hết bịa usdvnd=0 nhờ luật chữ-số) ·
consensus tilt +1 hiện đúng trong allocation (band data B4 → clamp B4).

**Còn lại — PHẢI chạy trên MÁY CÓ DATA + MẠNG (sandbox chặn mạng, không có
data_warehouse, không key LLM):**
1. `python vnstock_allocation.py --refresh` → in band + bảng % + lý do 7 tín
   hiệu thật (dự đoán với nền hiện tại: B2/B3). Sau đó `--show`/`--history`.
2. `python run.py all` chạy trọn — bước `allocation` mới (sau macro) không
   được làm gãy pipeline; history tự tích lũy mỗi tối.
3. `python vnstock_reports.py --add <PDF CTCK thật> --source X --report-date
   YYYY-MM-DD` → text trích được, `--list` hiện ✅; PDF scan → 🖼
   no_text_layer. `--add-url <URL báo cáo>` + `--diag` (Jina) trên máy có mạng.
4. **P3**: `python vnstock_report_digest.py --diag` (LLM ladder OK?) →
   `--refresh` trên báo cáo thật → `--show <id>` soi digest (stance hợp lý?
   claims đúng số? tiếng Việt sạch?) → `--consensus` → chạy lại
   `python vnstock_allocation.py --refresh` xem tilt xuất hiện đúng
   (`band_data` vs `band`, dòng 📚). Thử 1 báo cáo có số SAI HẲN (vd sửa tay
   text ghi "tỷ giá 30,000") → claim phải bị cờ mismatch.
5. **P4**: sau khi có allocation state + digest, chạy brief close thật →
   soi mục "📚 Báo cáo vĩ mô & phân bổ" (band đúng state? nguồn báo cáo
   thật? không bịa B0-B4/%?); brief allocation:
   `python -c "from vnstock_brief import generate_brief; r = generate_brief('allocation', force=True); print(next(iter(r.values()))[0])"`
   → bảng % phải Y HỆT `vnstock_allocation.py --show` (guard pin); nếu bias
   ngày ngược band tháng → có dòng caveat khung thời gian.
6. **P5**: mở dashboard → tab Tin tức phải có 4 sub-tab (📰/🌐/📚/🧭);
   sub-tab 📚 upload thử 1 PDF (rerun không nhân bản), nút Digest chạy;
   sub-tab 🧭 hiện band + bảng % + lý do + nút "Tạo brief phân bổ".
   `python run.py doctor` có 2 dòng mới (reports/allocation) — ⬜ khi chưa
   dùng là đúng; từ mùng 3 tháng sau chưa tạo brief phân bổ → doctor nhắc.
7. **P6**: `python vnstock_gold.py --diag` trên máy có mạng (endpoint trong
   `_ENDPOINTS` là ứng viên CHƯA VERIFY — chết thì sửa tại đó); `run.py all`
   nay có bước `gold` + scorecard tự refresh sau `allocation`;
   `python vnstock_scorecard.py --show` — trước khi có ≥2 tháng history sẽ
   ghi "chưa đủ kỳ" (đúng thiết kế), log nguồn báo cáo chạy ngay khi digest
   đủ 30 ngày tuổi.
8. `python run.py test --fast` sau khi pull (~480 tests hiện hành).

### ✅ P1 DONE (2026-07-13, branch `claude/phase-1-kickoff-lzorv6`) — `vnstock_allocation.py`

Đúng scope duyệt: **zero fetch / zero LLM**, chỉ đọc cache sẵn có. Chi tiết
implement (P2+ nối vào đây, đừng regress):
- **7 input → điểm [-1,1]** (`compute_score`, +1 = thuận lợi tài sản rủi ro):
  regime `score/5` (w .25) · sentiment `momentum/100` (w .20) · breadth
  `(pct−45)/25` (w .15) · macro_pressure nguyên trạng (w .15) · 3 gauge dùng
  `dir` −1/0/+1 (liquidity .10; term .10 — trung bình dir + slope_dir khi có;
  intl .05). Weight renormalize trên input CÓ MẶT (mirror sentiment
  composite); input hỏng/thiếu bị bỏ, không chặn input khác.
- **Band**: điểm ≥ +0.50 → B0 · ≥ +0.15 → B1 · > −0.15 → B2 · > −0.50 → B3 ·
  còn lại B4 (`_BAND_EDGES`). **Hysteresis** (`apply_hysteresis`): đổi band
  cần vượt ranh giới ≥ `_HYSTERESIS_MARGIN` (0.05) trong `_CONFIRM_SESSIONS`
  (2) NGÀY KHÁC NHAU — recompute cùng ngày không đếm 2 lần (idempotent); đề
  xuất đổi hướng giữa chừng → pending đếm lại; lần chạy ĐẦU áp band thô ngay.
- **State** `_meta/allocation_state.json` (ghi ATOMIC tmp+os.replace): band +
  điểm + `inputs[]` mỗi dòng đủ lý-do (value/score/weight/source/**as_of** —
  as_of gauge = as_of CŨ NHẤT trong các chỉ số nền) + pending + **history
  theo ngày** (cap 500, same-date replace) đủ cho scorecard P6 từ ngày 1.
  Không input nào dùng được → GIỮ state cũ nguyên vẹn, trả None, KHÔNG ghi
  đè (mirror giữ-cache-cũ của macro).
- **Config user chỉnh**: `_meta/allocation_config.json` — override
  `allocations` theo band (phải đủ 5 lớp + tổng ~100, sai → bỏ qua + cảnh
  báo) và `weights`. Mặc định = bảng B0-B4 user duyệt ở trên.
- **CLI**: `--refresh` / `--show` / `--history [N]` / `--json` / `--as-of`.
  `run.py allocation` + bước best-effort trong `run.py all` (sau `macro`) →
  history tự tích lũy mỗi tối. Loader public cho P4/P5: `load_state()`.
- **Tests**: `tests/test_allocation.py` (26 tests, hermetic — fake module
  qua sys.modules cho collect_inputs) đã vào danh sách `--fast`.
- CHƯA làm (đúng kế hoạch): doctor check + sub-tab UI (P5), block brief +
  guard (P4), vàng/scorecard (P6).

### ✅ P2 DONE (2026-07-13, cùng branch) — `vnstock_reports.py`

Tầng INGEST thuần (không LLM, không số nào vào registry 13 chỉ số):
- **3 đường vào**: `add_pdf` (tái dùng `vnstock_vbma.pdf_to_text`, GIỮ PDF
  gốc `<id>.pdf` cho `--redigest` P3) · `add_url` (Jina Reader — bản riêng
  `fetch_url_text` GIỮ xuống dòng + cap `_REPORT_MAX_CHARS`=200k, KHÔNG dùng
  bản 1.800 ký tự của news_feeds; fetch fail → KHÔNG lưu gì) · `add_text`
  (dán trực tiếp, '-' = stdin).
- **Dedup sha256** (id = 16 hex đầu): PDF theo BYTES, URL theo chuỗi URL,
  text theo text đã chuẩn hoá whitespace → Streamlit rerun/upload lại = cùng
  id, CHỈ merge metadata mới (arg không rỗng thắng), không nhân bản.
- **Gate metadata** (`in_analysis`): cần `report_date` (YYYY-MM-DD, không
  tương lai — sai định dạng → bỏ qua + cảnh báo, KHÔNG chặn ingest) +
  `source` + text ≥ `_NO_TEXT_LAYER_CHARS` (200). PDF trích ra < 200 ký tự →
  flag `no_text_layer` (🖼, PDF scan) — nằm thư viện, không vào phân tích.
  Bổ sung sau: `--set-meta <id> --report-date … --source …`.
- **Lưu trữ**: index `_meta/reports_index.json` (ghi ATOMIC tmp+os.replace) +
  text `_meta/reports/<id>.txt` + PDF gốc. Loader cho P3:
  `load_for_analysis(as_of, max_age_days=90)` — lọc đủ-metadata + tuổi ≤ 90
  ngày (age âm loại), kèm `age_days` để digest tính decay (giảm từ 30 ngày).
- **CLI**: `--add` / `--add-url` / `--add-text` / `--list` (mặc định; ✅ vào
  phân tích, 📥 thiếu metadata, 🖼 scan) / `--show` / `--set-meta` /
  `--remove` / `--diag` (thử Jina — cần mạng).
- **Tests**: `tests/test_reports.py` (19, hermetic — fake vnstock_vbma +
  requests qua sys.modules) đã vào `--fast`. KHÔNG có bước run.py (ingest là
  thao tác tay của user, không thuộc pipeline tối).

### ✅ P3 DONE (2026-07-13, cùng branch) — `vnstock_report_digest.py` + tilt trong allocation

Digest LLM + cross-check + consensus → tilt ±1 band. Chi tiết:
- **Digest** (1 call/báo cáo, `digest_report`): JSON {tom_tat, stance 5 lớp
  -2..+2 (0=TRUNG_LẬP được phép — float→int clamp, lớp thiếu/rác→0), claims
  [{key∈13-registry|"khac", value, unit, period, text}], risks}. Nguồn tiếng
  Anh → digest tiếng Việt (buộc trong prompt). Digest LƯU TRONG record của
  `reports_index.json` (`vnstock_reports.set_digest`) — xóa báo cáo là digest
  đi theo. `refresh(redigest=False)` chỉ chấm báo cáo CHƯA có digest;
  `--redigest` chấm lại tất cả (đổi prompt/extractor).
- **Provider ladder `digest_call`**: Claude (ANTHROPIC_API_KEY, model mirror
  brief `claude-haiku-4-5-20251001`) → GPT (`gpt-4o-mini`) → ladder free
  (`vnstock_sentiment.chat_complete`). **Model free nâng cấp 2026-07-14**
  (verify trên báo cáo HedgeAcademy thật: llama-3.3-70b đọc SAI stance —
  CP +0 thay vì -2, USD ngược chiều, bịa claim usdvnd=0 → cross-check chặn
  đúng): `_FREE_MODELS` nay Groq=kimi-k2-instruct / Cerebras=gpt-oss-120b /
  OpenRouter=deepseek-chat-v3:free — id là ỨNG VIÊN, sai/gỡ chỉ tốn 1 lần
  thử lỗi. **Cascade THEO BẬC SỨC MẠNH (user chốt 14/07)**: `_free_ladder`
  chạy TOÀN BỘ bậc 1 (mạnh, mọi provider) trước rồi mới rơi bậc 2 (70B) —
  KHÔNG provider-major như chat_complete (không để 70B của Groq chen trước
  gpt-oss của Cerebras); `_call_free` gọi thẳng từng (provider, model),
  provider lưu trong digest ghi rõ model ("Groq:kimi-k2…") để soi chất
  lượng về sau. Đổi model bậc 1 không sửa code: env
  `VNSTOCK_DIGEST_MODELS="Groq=...;OpenRouter=..."`.
  digest_call load .env trước khi check key (bẫy CLI fresh — fix 14/07);
  có key mà call lỗi → in cảnh báo degradation thay vì nuốt im lặng.
- **Sanitize cấu trúc** (`sanitize_text`, áp MỌI text field): strip `#`/
  emoji/CJK + ép 1 dòng — digest sẽ splice vào brief (P4) nên không được chứa
  token mà section-parser guard chain hiểu nhầm ranh giới mục. Số EN giữ
  nguyên (ép trong prompt, không convert deterministic).
- **Cross-check REGISTRY THẮNG** (`cross_check_claims`, mirror _fx_crosscheck):
  claim có key registry so với `load_macro()` hiện hành theo `_CLAIM_TOLERANCE`
  (fx rel 2%, rate/yield abs 0.5-1.0đ%, CPI 1.0, IIP 3.0, PMI 2.0…— dung sai
  RỘNG có chủ đích vì kỳ báo cáo ≠ kỳ registry, chỉ chặn số SAI HẲN). Lệch →
  cờ `mismatch` + `registry_value` trên claim + `has_mismatch` trên digest;
  claim mismatch KHÔNG vào brief (P4 lọc); **stance vẫn vào consensus** (số đo
  ≠ quan điểm — số sai bị chặn, quan điểm giữ nhưng có cờ). Số báo cáo KHÔNG
  BAO GIỜ ghi vào registry (nguyên tắc #2).
- **Consensus + tilt** (`consensus`): stance trung bình decay tuổi (w=1.0 ≤30
  ngày, tuyến tính → 0 ở 90 — đúng tham số duyệt; >90 đã bị load_for_analysis
  loại). Tilt từ stance "Cổ phiếu": ≥ +1.0 → −1 band (tấn công), ≤ −1.0 → +1
  (phòng thủ), `_TILT_THRESHOLD=1.0`. v1 không phân biệt uy tín nguồn (P6).
- **Allocation áp tilt** (`vnstock_allocation.apply_tilt` trong
  `run_allocation`): `band_data` = band từ data (P1), `band` = sau tilt (clamp
  B0-B4), `report_tilt` = {tilt, stance_cp, n_reports, sources}; history log
  thêm `band_data` + `tilt`. **Hysteresis NEO VÀO band_data** (prev_for_hyst)
  — tilt đến/đi không tạo pending giả, band data đổi vẫn cần 2 phiên như cũ.
  Đọc consensus là ĐỌC CACHE digest (zero LLM tại allocation). Kill switch:
  `VNSTOCK_ALLOCATION_TILT=0`. LƯU Ý test: autouse fixture trong
  test_allocation.py tắt tilt (hermetic trên máy có digest thật).
- **CLI**: `--refresh [--redigest] [--max N]` / `--show <id>` / `--consensus`
  / `--diag`. KHÔNG có bước run.py (digest chạy khi user ingest báo cáo mới —
  1-2 lần/tháng, không thuộc pipeline tối; cân nhắc lại ở P5 nếu cần).
- **Tests**: `tests/test_report_digest.py` (19, hermetic — digest_call/macro/
  consensus đều fake) đã vào `--fast`.

### ✅ P4 DONE (2026-07-13, cùng branch) — nối brief (vnstock_brief.py)

Mọi thay đổi giữ nguyên tắc parity morning↔close by construction:
- **ctx wiring (collect_context 8e)**: `ctx["macro_reports"]` (≤3 digest tươi
  từ `load_for_analysis(as_of)`) + `ctx["reports_consensus"]` +
  `ctx["allocation"]` (state P1 đầy đủ TRỪ history). Đọc cache thuần — zero
  LLM/fetch. Tắt: `VNSTOCK_BRIEF_REPORTS=0`.
- **Mục "📚 Báo cáo vĩ mô & phân bổ"** trong CẢ 2 template ngày (sau 📰,
  trước 📌): builder dùng chung `_macro_reports_body_lines(ctx, directive)` —
  cap ~5 dòng: 1 dòng band tháng (kèm tilt + band_data nếu có) + ≤3 báo cáo
  (ngày/nguồn/tom_tat/stance CP; digest has_mismatch → ghi chú "số không được
  trích dẫn") + 1 dòng consensus. Claims KHÔNG render → claim mismatch không
  bao giờ vào brief by construction. `directive=True` chỉ cho prompt.
- **brief_type="allocation"** (cadence THÁNG, CHỈ dashboard — KHÔNG Telegram,
  tham số duyệt #4): `_ALLOCATION_TEMPLATE` (TLDR band / 🧭 Phân bổ đề xuất /
  📊 Vì sao / 📚 Quan điểm / ⚠️ Rủi ro & khung thời gian, cap 350 từ); data
  thêm block `_allocation_state_block` (bảng % + lý do từng input kèm nguồn +
  as_of). Không time-gate (chỉ morning/afternoon bị gate). Chạy tay:
  `generate_brief('allocation', force=True)` — nút UI là việc P5. Memory lưu
  brief_type='allocation' bình thường (few-shot theo type tự tách).
- **2 guard mới trong `apply_brief_guards`** (sau enforce_market_news, áp mọi
  brief — parity by construction):
  * `enforce_macro_reports` — mirror enforce_market_news: thay body mục "📚"
    (anchor "báo cáo vĩ mô" + _is_section_start) bằng canonical bullets
    (directive=False); splice đè dòng phủ nhận; idempotent; no-op ctx trống.
  * `enforce_allocation_table` — nguyên tắc #1 (LLM không sinh số %/band):
    (a) pin token "band B<x>" + "Band phân bổ:** B<x>" lạc về band thật,
    BỎ QUA dòng canonical mang band khác hợp lệ ("band data:", "Band phân bổ
    tháng", "- Band:"); (b) brief allocation: thay body mục "🧭 Phân bổ đề
    xuất" bằng `_allocation_table_lines` canonical; (c) **caveat horizon**:
    band tháng B0/B1 + bias floor ngày GIẢM (hoặc B3/B4 + TĂNG) → chèn
    `_ALLOC_HORIZON_CAVEAT` sau dòng band — bắt đầu "- ⚠️" (dash TRƯỚC emoji
    để không thành ranh giới mục — bài học guard 27); idempotent check toàn văn.
- `_SECTION_EMOJIS` += 📚, 🧭. `_BRIEF_MAX_TOKENS` 2400→**2800** (thêm mục 📚).
- **Tests**: 8 test P4 cuối `tests/test_brief.py` (builder cap/mismatch note,
  2 guard đủ nhánh + idempotent, template selection, block cho từng
  brief_type, guard chain chứa 2 guard mới).

### ✅ P5 DONE (2026-07-13, cùng branch) — UI 2 sub-tab + doctor checks

- **Tab Tin tức nay 4 sub-tab**: 📰 Tin theo mã · 🌐 Vĩ mô · **📚 Báo cáo**
  (`dashboard/reports_tab.py`) · **🧭 Phân bổ** (`dashboard/allocation_tab.py`).
  Cả 2 tab mới **lazy-import streamlit trong render** (mirror money_flow_tab)
  → smoke test import được không cần streamlit.
- **📚 Báo cáo**: ingest (upload PDF qua tempfile → `add_pdf`; URL qua Jina;
  paste text) + form metadata (thiếu → hiện 📥, sửa bằng "Lưu meta") + bảng
  thư viện (✅/📥/🖼 + cột Digest 🧠) + nút **Digest** (chỗ DUY NHẤT tab gọi
  LLM — chỉ báo cáo đủ điều kiện chưa có digest) + xem digest từng báo cáo
  (claims kèm cờ ⚠ LỆCH registry) + dòng consensus/tilt. Streamlit rerun
  không nhân bản nhờ dedup sha256 (P2).
- **🧭 Phân bổ**: band + điểm + bảng % + tilt/pending + bảng lý do (nguồn +
  as_of) + line chart lịch sử band (B0→0…B4→4) + dòng vàng (luôn kèm nhãn
  premium SJC) + bảng scorecard + expander log nguồn (xếp hạng để dành) +
  nút "Tính lại band" (zero LLM) + nút "**Tạo brief phân bổ**"
  (`generate_brief('allocation', force=True)` — chỗ duy nhất tab gọi LLM,
  hiện brief gần nhất từ memory).
- **Doctor** (`OFFLINE_CHECKS`, sau check_events): `check_reports` (đếm đủ
  điều kiện/thiếu meta/chưa digest/claim lệch registry — warn khi có việc
  phải làm, off khi chưa dùng) + `check_allocation` (tuổi as_of so
  `_prev_trading_day` + tilt + **nhắc brief kỳ tháng** `_allocation_brief_reminder`
  mirror pmi_reminder: từ mùng 3, tháng này chưa có brief_type='allocation'
  trong memory → nhắc; hàm tách riêng để test monkeypatch).

### ✅ P6 DONE (2026-07-13, cùng branch) — scorecard hồi tố + vàng

- **`vnstock_gold.py`** — display-only + proxy return, **KHÔNG vào registry
  13** (đúng thiết kế): ladder 2 endpoint free-không-key
  (goldprice.org dbXRates → gold-api.com — ghi chú 1c nêu "Goldprice.dev"
  nhưng API cụ thể chưa xác minh, ladder này CẦN VERIFY `--diag` trên máy có
  mạng, chết thì sửa `_ENDPOINTS`); sanity range; fail → giữ cache cũ; cache
  `_meta/gold_price.json` (history cap 400); MỌI chỗ hiển thị kèm nhãn "spot
  quốc tế, CHƯA gồm premium SJC (~15-20%)". `price_on(date)` cho scorecard.
  Tắt: `VNSTOCK_GOLD=0`. Bước `gold` trong `run.py all` (sau macro).
- **`vnstock_scorecard.py`** — mirror vnstock_reconciler cho tầng phân bổ:
  * **Kỳ = tháng lịch** (`monthly_periods`): entry ĐẦU mỗi tháng trong
    history = band chốt tháng đó; kỳ khép tại entry đầu tháng sau; cần ≥2
    tháng history mới có dòng (đúng "sau ≥2 kỳ").
  * **Proxy return THÔ, dán nhãn** (`class_returns`, zero fetch): Cổ phiếu
    %Δ VNINDEX (parquet) · Trái phiếu −Δyield10Y × duration 7 · Tiền gửi
    policy rate × d/365 · Vàng %Δ spot · USD %Δ usdvnd. Thiếu data → None
    (KHÔNG độn 0), `coverage_pct` ghi tổng trọng số có data.
  * `compute_scorecard`: return danh mục theo bảng % band kỳ đó vs baseline
    B2 → `delta_vs_b2`. `returns_fn=None` resolve lúc GỌI (test patch được).
  * **`source_log`** — xếp hạng nguồn LOG NGAY (UI để dành): mỗi digest đủ
    30 ngày tuổi → {source, stance_cp, %Δ VNINDEX 30d sau report_date}.
  * Cache `_meta/allocation_scorecard.json` (atomic); `run.py allocation`
    tự refresh scorecard best-effort sau khi tính band; CLI `--refresh/--show`.
- **Tests**: `tests/test_gold.py` (7) + `tests/test_scorecard.py` (8) +
  `tests/test_allocation_reports_tabs.py` (3 smoke UI) + 4 test doctor mới —
  tất cả vào `--fast`.

---

## 📌 Pending suggestions (raise when relevant)

### 0. ✅ ĐỢT VERIFY 10-13/07 HOÀN TẤT — PR đã mở về main

Toàn bộ checklist verify xong 100% (tests/doctor/macro 13 chỉ số + 3 gauge/
Jina full-text/dashboard). PR mở 2026-07-13 theo lệnh user — nếu PR đã merge
thì XÓA mục này; nếu chưa merge, kiểm tra trạng thái PR khi user quay lại.

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

### 1c. Khảo sát public-apis (2026-07-11) — nguồn ứng viên ĐỂ DÀNH

Đã khai thác ngay: FRED (us10y/fed_funds + gauge quốc tế) + currency-api (FX
nấc 3) — xem mục Vĩ mô. Còn lại LƯU Ở ĐÂY chờ nhu cầu (user dặn giữ 2026-07-11):

**Để dành — có use-case rõ, chưa làm:**
- **Econdb** (econdb.com/api — Auth: No, macro toàn cầu, CÓ series VN):
  ứng viên nguồn **CROSS-CHECK số NSO** (CPI/GDP/IIP) — mirror đúng pattern
  `_fx_crosscheck` er-api↔VCB đang có. Việc đầu tiên khi làm: verify series
  VN của nó có tươi/khớp NSO không (`--diag` trên máy có mạng).
- **Goldprice.dev** (Auth: No, vàng/bạc/đồng spot + 30 năm lịch sử, 13 tiền
  tệ): tin vàng/PNJ xuất hiện thường xuyên mà brief chỉ có TIN không có SỐ —
  1 dòng giá vàng làm ngữ cảnh cho analyze_item/brief là use-case tự nhiên.
  Lưu ý cap registry 13 → nếu thêm thì cân nhắc display-only ngoài registry.
- Dầu (Brent/WTI): KHÔNG có API free-no-key nào trong danh mục (toàn
  paywalled: EconPulse/Sugra/Finage đều apiKey trả phí) — tin dầu vẫn đi
  đường RSS keywords như hiện tại.

**Bỏ qua nhưng ĐÁNG NHỚ (user dặn lưu — có thể đổi ý sau):**
- **News APIs** (NewsAPI/GNews/Currents/MarketAux/NewsData…): toàn `apiKey`
  + thiên nguồn Anh ngữ — RSS báo VN hiện tại PHỦ TỐT HƠN cho thị trường VN
  (12 feed, có sẵn tiếng Việt, free). Khi nào đáng xem lại: cần tin tiếng
  Anh có sentiment/ticker-tag sẵn (MarketAux) hoặc RSS VN bắt đầu chặn.
- **Stock APIs** (Alpha Vantage/Finnhub/Polygon/Twelve Data…): vnstock +
  sponsor API đã cover VN đầy đủ — các API này KHÔNG có data HOSE/HNX. Khi
  nào đáng xem lại: cần data thị trường MỸ/quốc tế làm ngữ cảnh (index
  futures, S&P500) — lúc đó Finnhub/Twelve Data free tier là ứng viên đầu.
- Repo public-apis = DANH MỤC để tra khi cần nguồn mới (2 nguồn FX cũ của
  mình cũng nằm trong đó) — không phải dependency, không cần theo dõi.

### 1d. Khảo sát Ollama (2026-07-13) — LLM LOCAL, ĐỂ DÀNH chờ có vấn đề

User chốt "note lại để đấy, sau này có vấn đề thì triển khai sau". Đã đọc
code (repo ollama/ollama): serve **`POST /v1/chat/completions` chuẩn
OpenAI-compatible** tại `localhost:11434` (xác nhận `server/routes.go`) —
CÙNG shape API mà `vnstock_sentiment._PROVIDERS` gọi Groq/Cerebras/OpenRouter
→ tích hợp = thêm 1 entry ladder, KHÔNG viết client mới. Có structured
outputs (ép JSON schema qua `format`), embeddings, Anthropic-compat, cloud
models (offload lên ollama.com — ít liên quan). Installer Windows có sẵn.

**Khi nào triển khai** (trigger): free provider (Groq/Cerebras/OpenRouter)
throttle/chết làm sentiment/tin không chấm được; HOẶC cần `--reanalyze` hàng
loạt không rate-limit; HOẶC desktop có GPU rảnh muốn tự chủ LLM local.

**Sketch tích hợp (~1-2h, zero rủi ro đường hiện tại)**:
1. Entry "Ollama (local)" CUỐI ladder `vnstock_sentiment._PROVIDERS` —
   endpoint `http://localhost:11434/v1/chat/completions`, không key; bật qua
   env `OLLAMA_MODEL` (không set = ladder bỏ qua, hành vi y cũ).
2. `_ANALYZE_MODELS["Ollama"]` = model user pull (tiếng Việt tốt: qwen3
   14B/32B tùy VRAM).
3. Doctor: check `localhost:11434/api/tags` — chạy được ở tầng OFFLINE
   (localhost không dính allowlist).

**Giới hạn ghi thẳng**: model local 8-14B thường THUA llama-3.3-70b free
trên Groq về nuance (liên quan TODO 1b — chỉ thắng nếu GPU đủ chạy 32B+);
KHÔNG dùng cho brief agent chính (2.400 token, 11 mục + guard chain — giữ
Claude/GPT). CPU-only ~5-15 tok/s: đủ cho ≤8 tin/ngày, chậm cho batch lớn.
Khác 3 khảo sát trước (lấp gap DỮ LIỆU thật), cái này lấp gap ĐỘ BỀN LLM —
hiện chưa đau nên để dành.

**Khảo sát excalidraw (2026-07-13): BỎ QUA, user chốt "không áp dụng được"**
— whiteboard vẽ tay React SPA: lệch stack (dashboard là Streamlit/Python,
nhúng cần tự viết custom component) + lệch use-case (canvas TỰ DO không neo
trục giá/thời gian — vẽ trendline trên đó lệch ngay khi pan/zoom; nhu cầu
vẽ-trên-chart nếu có thuộc về primitives của lightweight-charts đang dùng,
và khối sync 4-panel là vùng hard-won invariants phải dè chừng). Không có
gì để mượn về phương pháp. Nhu cầu phác thảo cá nhân → dùng excalidraw.com
như app rời, khỏi tích hợp.

### 1b. Chất lượng dòng "→ tác động" tin vĩ mô — giới hạn MODEL, nâng khi cần

**Status (ghi nhận 2026-07-10, verify --reanalyze với full text Jina trên máy
user)**: lỗi NGƯỢC CHIỀU (loại bug "vàng GIẢM → PNJ hưởng lợi giá CAO" 30/06)
đã HẾT nhờ full text + prompt directive. Còn lại là giới hạn chất lượng của
**model 70B free** (llama-3.3-70b qua Groq/Cerebras/OpenRouter,
`_ANALYZE_MODELS` trong `vnstock_news_feeds.py`), KHÔNG phải bug pipeline:
- Mapping kênh đôi khi MÁY MÓC vì prompt ép nêu ngành cụ thể: vd thật
  "Suntory Pepsico đưa vào hoạt động nhà máy lớn nhất châu Á → Ngành dệt may
  và thuỷ sản hưởng lợi từ đầu tư nước ngoài" (FDI đồ uống ≠ dệt may/thuỷ sản).
- Tin đa chiều (vd "Dòng dầu khí qua Hormuz khôi phục đến đâu?") chiều tác
  động khó kiểm chứng — model chọn 1 chiều thay vì TRUNG_LẬP.

**Khi nào nâng**: user thấy ≥ 2-3 dòng gượng/8 tin mỗi ngày, hoặc brief bắt
đầu trích dẫn mapping sai vào mục Rủi ro/Tin.

**Các hướng (rẻ → đắt)**:
1. Chỉnh prompt `_ANALYZE_SYSTEM`: cho phép TRUNG_LẬP khi kênh không rõ thay
   vì ép nêu ngành (đánh đổi: nhiều tin bị lọc `drop_no_impact` hơn).
2. Đổi model trong `_ANALYZE_MODELS` sang bản mạnh hơn cùng provider (Groq có
   các bản lớn hơn / OpenRouter nhiều lựa chọn free mới — kiểm tra catalog).
3. Route qua key trả phí sẵn có trong .env (ANTHROPIC/OPENAI — brief agent
   đang dùng): thêm provider vào ladder `vnstock_sentiment._PROVIDERS` hoặc
   map riêng cho analyze. Chi phí nhỏ: chỉ ≤8 tin/ngày × ~2K token.

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
- `dashboard/news_tab.py` — Tin tức, 2 sub-tab: "📰 Tin theo mã" (nội dung gốc,
  `_render_ticker_news`) + "🌐 Vĩ mô" (`dashboard/macro_tab.py`, DONE
  2026-07-08). Sub-tab Vĩ mô THUẦN HIỂN THỊ trên cache sẵn có (scope "UI mỏng"
  user chốt — KHÔNG fetcher mới, KHÔNG gọi LLM): bảng 10 chỉ số + áp lực vĩ mô
  + nhắc PMI/cờ fx_crosscheck (vnstock_macro), chart lịch sử 1 chỉ số (plotly,
  fallback st.line_chart), tin vĩ mô theo ngày (market_news_cache — retention
  nay 30 ngày: `_RETAIN_DAYS` trong vnstock_news_feeds, refresh GIỮ tin cũ
  trong cache thay vì ghi đè cụt ~4 ngày; brief không đổi hành vi vì
  load_market_news vẫn lọc within_days riêng), đọc lại mục 🎯/🌐 của brief cũ
  qua `vnstock_brief.brief_section(text, marker)` (public, cùng ranh giới mục
  với chuỗi guard) + `vnstock_memory.recent_briefs`.
