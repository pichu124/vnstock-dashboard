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
  `vnstock_gold.py`, `vnstock_scorecard.py`, `vnstock_reflection.py`,
  `vnstock_debate.py`, `vnstock_strategy.py` (validation/decay),
  `vnstock_train.py` (reconcile)
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
    idempotent; no-op khi thiếu sentiment. **Mở rộng 14/07**: mood word bọc
    markdown ("**Sợ hãi**") không khớp pattern cũ → close 14/07 ra "📉 Tiêu
    cực **Sợ hãi**" (label đúng + đuôi mood bịa dính kèm); nay cho phép `[*_]`
    quanh word VÀ nuốt 1 mood word LẶP ngay sau → chỉ còn canonical.
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
29. **Vá 4 biến thể trượt guard (đêm 14/07, close 23:46 — test gộp
    `test_close_1407_guard_regressions`)**: (a) guard 14 nhận markdown quanh
    hướng ("bias **GIẢM** bắt buộc" → strip "bắt buộc"); (b) guard 24 thêm
    dạng KHÔNG dấu hai chấm "tâm lý sợ hãi (momentum …)" → pin mood word
    (gate ngoặc-momentum nên văn quá khứ "tâm lý hưng phấn đã biến mất"
    không đụng) + guard 16 dọn ngoặc RỖNG "()" sót lại sau dedup momentum;
    (c) `enforce_sector_nn_figures` nhận số dấu "+" VÀ gap tên→verb cấm vượt
    ranh giới mệnh đề (".<space>" / token "tỷ") — không thì pass ngành A với
    sang câu ngành B phá số vừa pin ("Họ VIN +1,471 tỷ. Ngân hàng bị bán ròng
    +1,471 tỷ" — thật -1,032); (d) guard 22 thêm **Form 3 tự-chứa**: "N% so
    <base> (A tỷ vs B tỷ)" — model tự ghi cả 2 vế thì % pin về (A/B−1)×100,
    chạy CHỈ khi ctx thiếu full_day_gtgd/cmp (ctx là nguồn chân lý khi có);
    close 23:46 "giảm 29%" thật ra −21%.
30. **Vòng review phản biện chéo close 23:58 14/07 (workflow 4 lăng kính ×
    2 skeptic/phát hiện) → 4 vá (test `test_enforce_session_direction_*` +
    `test_close_1407_2358_review_fixes`)**:
    (a) `enforce_session_direction` (guard MỚI, sau enforce_vnindex_change) —
    nhãn ĐỊNH TÍNH "phiên tăng/giảm (điểm)" phải khớp dấu day_change_pct
    (close +0.34% mà TLDR gọi "phiên giảm điểm nhẹ"); gate neo "đóng cửa"/
    "kết quả phiên" cùng dòng, bỏ qua phiên KHÁC ("sau phiên tăng…", "trước
    đó/hôm qua") + kịch bản tương lai ("nếu/kỳ vọng…", "tiếp theo").
    (b) `enforce_breadth_quality` nay 2 CHIỀU: thêm A/D ≥ 1.05 (ngày DƯƠNG —
    nhãn canonical prompt là "tích cực") mà brief gọi "độ rộng tiêu cực" →
    "trái chiều" (vẫn gate cấu trúc yếu pct<40 + momentum<0; A/D thấp thật
    giữ nguyên "tiêu cực").
    (c) `enforce_nn_frame_labels` (guard MỚI, sau enforce_net_flow_label) —
    số NN THEO NGÀNH (khung 1 tuần) nêu không nhãn → gắn "(1 tuần)" (Tổng
    kết phiên đặt "159 tỷ" 1-ngày cạnh "Ngân hàng -1,032 tỷ" 1-tuần → đọc
    thành bán riêng hôm nay gấp 6.5 lần cả thị trường); match phải khớp
    |NN 1T| đúng ngành + có "ròng" cùng mệnh đề; dòng đã có "tuần"/"1T"
    trước/sau → bỏ qua; GTGD không đụng.
    (d) `_leadlag_candidates` (helper MỚI trong collect_context) — sanity
    gate ứng viên Dẫn dắt/Tụt hậu: contrib/weight ≡ "Giá 1T %" của row;
    |%đổi tuần| > 35 vượt trần vật lý sàn = member data hỏng → loại.
    **Hậu kiểm bằng data user (đêm 14/07)**: "Họ VIN [1.6%VNI, -0.873pp]"
    hóa ra KHÔNG phải data hỏng — kho đủ 4 mã, trọng số thật ~25%, model
    bịa "1.6" (mượn GTGD 1,653 tỷ) → thêm pass pin "%VNI" của lead/lag về
    ctx sector_weights trong `enforce_lead_lag` (gate (d) giữ làm defense
    cho data hỏng thật). Phát hiện bị BÁC sau phản biện (không sửa): "57%
    GTGD phiên chiều" (echo đúng session_timing_signal bucket), "Dầu khí
    tích luỹ mạnh (+0.06pp)" (nhãn composite hợp lệ, trục khác pp).
31. **Vá close 01:10 15/07 (test `test_close_1507_0110_fixes`)** — brief đầu
    tiên sau loạt fix đêm 14/07, xác nhận các guard mới đều ăn; lộ thêm:
    (a) `enforce_macro` anchor nay 2 NẤC: ưu tiên dòng _is_section_start có
    "vĩ mô"; nhánh lỏng ("vĩ mô"+"lãi suất/tỷ giá", cho header bị reformat
    — fix 16/06) CHỈ là fallback. Trước đó nhánh lỏng match dòng VĂN XUÔI
    "Rủi ro vĩ mô: lãi suất…" trong mục Rủi ro → body canonical splice vào
    mục Rủi ro (nuốt dòng D/E) còn section 🌐 thật không được pin.
    (b) `enforce_nn_frame_labels` thêm dạng SỐ-TRƯỚC-TÊN ("NN mua ròng
    1,471 tỷ trong ngành Họ VIN" → "…ngành Họ VIN (1 tuần)").
    (c) Template "🔧 Đề xuất bổ sung": CPI/lạm phát + lãi suất Fed chuyển từ
    ví-dụ-thứ-thiếu sang danh sách ĐÃ CÓ (model chép nguyên ví dụ cũ để
    "xin CPI" dù registry có từ 08/07); ví dụ thiếu mới: giá dầu Brent/WTI.
    (d) Close 01:20 (lần chạy lại): `_MORNING_CMP_RE` (guard 13) nới 2 chỗ —
    mệnh đề so sánh nhận dạng KHÔNG có "so" ("cao hơn 35% phiên trước
    (10,294.2 tỷ) và 23% trung bình 5 phiên sáng" — 10,294.2 là GTGD SÁNG
    phiên trước đội lốt "phiên trước") + baseline "trung bình N phiên sáng"
    (chữ "sáng" đứng CUỐI). Match phải MỞ ĐẦU bằng verb-so-sánh+% hoặc
    %+"so/vs" — không thì nuốt nhầm "57% GTGD (…)" đứng trước mệnh đề.
    (e) Close 01:26 (lần chạy lại nữa): guard 22 thêm **Form 4** "±N%
    <baseline>" — % CÓ DẤU đứng NGAY TRƯỚC baseline, không connector
    ("(-21% phiên trước, +2% TB5 phiên)" — +2% lệch, TB5 thật -8%; Form 1
    cần "so/vs", Form 2 cần baseline đứng trước ngoặc → cả 2 trượt). Dấu
    BẮT BUỘC nên "thấp hơn 21% phiên trước" (verb mang chiều, magnitude
    không dấu) không bị đụng; "-35% GTGD so sáng phiên trước" là so
    sáng-với-sáng HỢP LỆ (subject = phiên sáng) — không sửa, đúng thiết kế.

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
8. **KỊCH BẢN PHẢI KHẢ THI TRONG BIÊN ĐỘ NGÀY (trục NGỮ NGHĨA GIAO DỊCH —
   user chốt 17/07 sau 2 lần bắt lỗi cùng ngày)**: mọi "mục tiêu"/"trigger"
   cho phiên kế phải nằm trong tầm với thực tế (biên độ HOSE 7%/ngày là
   trần vật lý; index thực tế còn hẹp hơn nhiều). Soi cụ thể: (a) thủng
   S1 → mục tiêu phải THẤP HƠN S1 và là mức KẾ TIẾP (không nhảy cóc qua
   MA200/đáy tháng để xuống thẳng đáy 52w cách 19%); vượt R1 → đối xứng;
   (b) S1/S2, R1/R2 đúng VAI (1 = gần giá nhất); (c) không mức nào = giá
   đóng cửa. Code đã chốt 4 tầng trong `enforce_sr_direction` (đúng phía →
   đúng vai → vai 2 kế tiếp trong tầm `_SR_MAX_MOVE_PCT`=7% → dedupe) —
   mục này để REVIEW SAU vẫn soi trục "có giao dịch được không", vì loại
   lỗi này máy khó tự thấy (cần ngữ nghĩa giao dịch, không chỉ cú pháp):
   giá vào lệnh/cắt lỗ watchlist so với giá hiện tại có với tới trong
   1-2 phiên không, kịch bản có đòi index đi quãng đường phi lý không.

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
- **Test hermetic**: mọi test gọi `mac.refresh()` PHẢI patch TOÀN BỘ fetcher
  — autouse fixture test_macro nay chặn `_fetch_nso/_fetch_fred/_pmi_from_news/
  _fetch_vbma/_fetch_hnx/_fetch_sbv/_fetch_sbv_daily/_fetch_sbv_policy` +
  `_FX_ENDPOINTS=()` (FX chặn qua endpoint, KHÔNG patch hàm — test parser cần
  hàm thật). **BÀI HỌC desktop 17/07**: sandbox chặn mạng nên fetcher lọt
  fixture vẫn "vô tình pass"; chạy suite trên máy CÓ MẠNG là fetch thật đè
  fixture (ON 4.11 thật đè 9.35 fake — 3 test fail). Thêm fetcher mới vào
  `refresh()` thì PHẢI thêm vào autouse fixture cùng lúc.

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
  **FIX leak directive (2026-07-14)**: `_macro_body_lines`/`_market_news_body_lines`
  trước đây LUÔN gắn dòng chỉ thị "→ … DÙNG bối cảnh này / TUYỆT ĐỐI KHÔNG
  bịa…" → guard splice mang nguyên chỉ thị NỘI BỘ vào brief xuất bản (lộ khi
  phần 2/2 Telegram về được sau fix sanitize). Nay 2 builder có tham số
  `directive` (mirror `_macro_reports_body_lines` P4): prompt renderer
  directive=True, guard truyền False; catch-all `_INSTR_LEAK_RE`
  (enforce_no_instruction_leak) bắt thêm dòng "→ …KHÔNG bịa/DÙNG bối cảnh/
  DÙNG các tin/DÙNG ĐÚNG số" model tự echo Ở BẤT KỲ ĐÂU — "→" nội dung thật
  ("→ Dòng tiền khối ngoại…") không đụng.
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
- **Telegram HTML sanitize (FIX 2026-07-14)**: body brief gửi với
  `parse_mode=HTML` mà KHÔNG escape → ký tự `<`/`>`/`&` lạc (model viết
  "<3", "P/E <10", tin "M&A"…) làm Telegram trả **400 can't parse entities
  và NUỐT NGUYÊN PHẦN TIN** (bug thật close 14/07: phần (2/2) không bao giờ
  tới nơi, `raise_for_status` còn vứt mất description nên không soi được).
  Fix 3 lớp trong `send_message`: (1) `_sanitize_html` — escape toàn bộ
  `& < >` rồi un-escape whitelist tag chủ đích (`_ALLOWED_TAGS`: b/i/u/s/
  code/pre); (2) vẫn 400 → tự GỬI LẠI phần đó dạng plain (strip tag) —
  nội dung luôn tới nơi; (3) lỗi API nào cũng raise kèm `description` thật
  của Telegram. Tests trong test_telegram.py.
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
- **VCI outage 21h+ (chẩn đoán thật 17/07) — PLAYBOOK 3 PROBE + fallback
  ứng viên**: updater rề rề toàn "Read timed out (30s)" từ
  `trading.vietcap.com.vn`. Chẩn đoán tách biến: (1) `curl -w` tới host →
  edge 120ms OK = mạng vô can; (2) 1 call đơn `Quote(source='VCI').history`
  → timeout = backend query VCI sập (KHÔNG phải concurrency/8 workers);
  (3) cùng call `source='kbs'` → **6 bar/2.5s** = outage riêng VCI, các
  nguồn VN khác sống. Registry quote bản hiện tại: ['fmp','kbs','msn','vci'].
  Khung 21h± là giờ batch EOD của provider — dính thì Ctrl+C updater (an
  toàn, `--skip-if-done` chạy bù), thử lại khuya/sáng sau khi probe (2)
  nhanh trở lại. KHOAN nâng vnii/vnai khi đang chẩn đoán (đổi biến giữa
  chừng). Mỗi mã thực tế đốt ~60s+ vì tenacity retry bên trong vnstock.
  **Nếu tái diễn nhiều tối → build (user nói "làm đi")**: fallback ladder
  nguồn giá VCI→KBS trong updater (KBS đã verify sống) và/hoặc fail-fast:
  tỷ lệ timeout vượt ngưỡng → dừng sớm thay vì cày 30s×1724 mã.
- **`vnstock_source_probe.py` (DONE 17/07 tối, 2 run thật) — BẢNG XẾP HẠNG
  FALLBACK đã chốt**: đo mọi nguồn registry trên rổ FPT/BSR/SHS/VGI +
  VNINDEX, chấm độ-phủ → đúng-giá-CÙNG-NGÀY → tốc độ (v2 date-aware — run
  đầu vu "lệch giá" oan cho KBS vì so close khác ngày với MSN trễ 2 phiên);
  cache 20 run `_meta/source_probe.json`, cột ok tích lũy đo độ bền.
  **Kết quả 2 run tối 17/07 (lúc VCI outage)**: 🥇 **KBS 8/8 + index,
  0.4-0.7s/call, bar đủ phiên = fallback DUY NHẤT đủ chuẩn** · 🥈 MSN 8/8
  + index ~1.8s nhưng TRỄ ~2 PHIÊN (kém tươi cho EOD — dự phòng khẩn cấp
  có caveat) · VCI 3/6 rồi 0/2 (outage nặng dần trong tối) · dnse/tcbs
  không có trong registry quote bản này · fmp cần key (US-oriented, bỏ).
  Khi build ladder VCI→KBS: nhớ so ĐƠN VỊ + hệ số điều chỉnh cổ tức giữa
  2 nguồn trước khi ghi kho (khác adjustment basis là hỏng chuỗi giá).
- **FALLBACK VCI→KBS ĐÃ BUILD (DONE 17/07 đêm, user "làm fallback đi" —
  CHỜ VERIFY lần updater kế tiếp)**: `vnstock_price_fallback.py` (thuần,
  hermetic) + wire vào `update_ticker`/`run_update`. 3 mảnh: (1)
  `CircuitBreaker` thread-safe dùng chung 8 worker — 5 mã lỗi MẠNG liên
  tiếp → MỞ mạch = đi thẳng KBS (hết cày 60-90s/mã), đang mở probe lại
  VCI mỗi 25 mã → tự đóng khi hồi (log "⚡ MỞ MẠCH"/"VCI hồi phục");
  (2) `is_outage_error` — chỉ lỗi mạng/timeout vào breaker, lỗi riêng của
  mã (Invalid symbol…) KHÔNG fallback bừa; (3) `reconcile_fallback_df` —
  chốt an toàn trước khi ghi kho: close bar overlap (last_date, updater
  vốn refetch inclusive) phải khớp warehouse; ratio ~×1000 → VND thô, chia
  1000 OHLC (volume giữ); sau chuẩn hoá lệch >8% → TỪ CHỐI (khác adjustment
  basis cổ tức — giữ kho cũ, VCI tự lành sau); không có bar overlap → từ
  chối. Kill switch `VNSTOCK_PRICE_FALLBACK=0` (hành vi y cũ). Summary in
  "⚡ Fallback KBS: N mã"; result mang source/fb_note. Refactor kèm:
  `_normalize_price_df` tách chung VCI/KBS; `_get_close_on` đọc close
  warehouse. Tests `tests/test_price_fallback.py` (11 — 6 thuần chạy
  sandbox, 5 integration skip khi thiếu vnstock, chạy đủ trên máy user).
  **VERIFY khi VCI ốm lần tới**: log phải thấy "⚡ MỞ MẠCH" rồi run vẫn về
  đích, summary có "⚡ Fallback KBS: N mã"; kho không có bar lệch giá.

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

**Verify 14/07 (phiên chiều) — thêm các mục ĐÃ XONG:** digest end-to-end
với báo cáo HedgeAcademy thật (ảnh trong docx → Claude gõ lại → add-text →
Cerebras gpt-oss-120b stance CP -2 → consensus tilt +1 → dòng 📚 trong
allocation) · close brief thật chạy trọn phần (1/2): Rủi ro/Sự kiện/Vĩ mô
canonical, 13 chỉ số + 3 gauge lần đầu lên brief; lộ + đã vá 2 guard
(enforce_breadth_label thiếu tổ hợp "số mã cổ phiếu"; enforce_vnindex_change
đè % GTGD-vs-phiên-trước vì không kiểm tra chủ ngữ).

**✅ ĐỢT VERIFY 14-15/07 HOÀN TẤT** (user chạy trọn đêm 14 → rạng sáng 15/07):
phần (2/2) + 📚 canonical (4 bản close brief liên tiếp) · doctor **14/14 ✅** ·
brief phân bổ tháng 7 tạo xong (bảng % khớp `--show`, debate 4 luận điểm,
lộ + vá luôn pass (d) pin % lớp tài sản) · reflection 3 bài học đầu (đúng
outcome, tiếng Việt sạch; 9 rec còn lại xử dần mỗi tối, trần 3 call/lượt) ·
validation 🧪 sống (family-05f9d495: p=0.986, 0% fold dương — lột mặt
"lãi trên giấy" +0.365 gross → −0.777 net; 3 ứng viên revise đều bị gate
loại ĐÚNG vì net âm) · sức khỏe live 💚 (12 rec, wr 58.3%) · sizing NAV
500tr/1%/25% đã lưu · chẩn đoán Họ VIN: data OK, "1.6%VNI" là model bịa
(đã pin). Trong đợt này vá tổng cộng ~20 lỗi guard/transport qua 6 bản
brief thật + 3 bug hệ (Telegram sanitize, benchmark gross-vs-net đóng
băng, macro-anchor hijack).

**CÒN LẠI — ⏰ NHẮC CHỦ ĐỘNG khi user quay lại / nói "test"/"verify":**
1. **Việc TRÊN DESKTOP (máy production — gotcha 2 máy 17/07)**: (a) ✅ KIỂM
   XONG tối 17/07 — cả 3 task ĐỀU bắn đúng lịch (kể cả chạy bù khi boot)
   NHƯNG `LastTaskResult = 3221225786` (0xC000013A = bị NGẮT giữa chừng —
   tắt máy/đóng console khi pipeline đang chạy) ở cả 3 → pipeline desktop
   CHƯA TỪNG chạy trọn; cùng tối phát hiện VCI outage 21h (xem playbook ⚡)
   → 2 bệnh có thể chung gốc: VCI chậm giờ đó → run kéo dài → user tắt máy.
   **CÒN THEO DÕI: tối T2 20/07 18:00** — máy bật, không đụng, kỳ vọng lần
   đầu LastTaskResult=0; user cần trả lời "hay tắt desktop lúc mấy giờ" để
   chốt giờ task. Desktop đã seed tay 17/07: test 742 pass, macro ra ON
   4.11 @07-16 sbv_daily + policy sbv_portal (KHÔNG cần --drop — entry
   manual 06-15 chỉ có trên laptop), backfill 300 ngày. Còn nợ: bù GIÁ khi
   VCI khỏe (probe 1 lệnh → bấm 🚀 Cập nhật tất cả);
   (b) ✅ XONG 17/07 — FRED key
   đã vào .env laptop, `--diag` ra us10y 4.55/fed_funds 3.63 @07-15, cả 2
   máy nay 13/13 chỉ số auto; (c) `python vnstock_preset_score.py --show`
   ~24/07 TRÊN DESKTOP (item
   6b — screener_history do pipeline desktop nuôi, laptop thiếu snapshot).
2. **Lần train kế tiếp**: panel Chiến lược phải hiện "p=… · N ứng viên"
   (hiệu chỉnh chọn-lọc Bonferroni mới 15/07 — p_adj = p × N, chỉ siết
   không nới); validation trong DB mang `p_value_adj` + `n_trials`.
3. **✅ DASHBOARD CHECK XONG 17/07 (6/6 trạm, qua ảnh user — lộ + vá luôn
   4 lỗi)**: 5 sub-tab ✓ · 📄 render bảng+SVG ✓ (vá 2: nền trắng tường
   minh — iframe nền tối làm chữ tàng hình; "dữ liệu đến 2023" — loại
   sbv_policy_rate khỏi as_of báo cáo) · 🌐 nguồn mới + chart ON/1W ~295
   mốc ngày ✓ (vá: `dense_history` đọc cache SBV daily/HNX — registry chỉ
   vài mốc) · caption 🎯 "đúng 4/7 (57%)" ✓ · 📋 preset expander + Đọc kết
   quả ✓ · conviction hết "-0.00" ✓ (vá zero âm market_regime). CÒN LẠI
   khi có rec mở mới: bảng Open recommendations phải có cột "KL gợi ý" +
   "Giá HT"/"L/L tạm" + "SL trailing" (mã mỏng "(cap TK)") + brief gắn
   "KL gợi ý ~N cp"; expander ⚖️ 4 ô (thêm "Cap thanh khoản (% ADV20)").
4. **Passive — tự đến, chỉ để ý**: scorecard allocation kỳ đầu ~đầu
   tháng 9 (đủ 2 tháng history) · decay 🔻 + log "[reconcile] … DECAYED"
   nếu chiến lược nào tụt thật · OpenRouter `qwen/qwen3-235b-a22b:free`
   chưa thử lửa (chỉ lộ khi Cerebras chết) · chiến lược mới thay
   family-05f9d495 khi có ứng viên net-dương qua được 🧪 (rule 2b thách
   thức mỗi lần train, nay kèm penalty chọn-lọc)
   · **stance track đủ ~30 điểm chấm (~3-4 tuần)** → phân tích breakdown:
   stance do bias-floor ÉP có tệ hơn stance model tự gọi không (→ chỉnh
   ngưỡng floor bằng số liệu) + agent nào đáng làm primary consensus;
   mẫu sớm (7 điểm, 29%) gợi ý brief TRỄ PHA — trung tính khi đang rơi,
   GIẢM ngay đáy hồi — chưa kết luận được, chờ đủ mẫu
   · **preset scorecard đọc lại khi thị trường ĐỔI PHA** (baseline Bear
   15/07 đã ghi ở mục 📋: mean-reversion > trend-following, edge ~5 phiên,
   sau phí gần hòa) → tách "alpha mọi thời tiết" khỏi "alpha một mùa";
   chạy `python vnstock_preset_score.py --show`.
5. **Theo dõi chất lượng (brief phân bổ tháng 8)**: mục "Phản biện band"
   của Mistral Small logic lộn xộn ("regime -4 trái ngược B4"?!) — nếu
   lặp → route brief allocation sang agent mạnh (1 call/tháng, đáng).
6. **Đợt build 15/07 CHIỀU (StockSharp + quant-trading — mẫu nến/CHOP/
   CRSI/PSAR/W-bottom/HA/GA/profit-recovery) — VERIFY CÒN NỢ:**
   a. **Close brief kế tiếp**: block "VNINDEX kỹ thuật" phải có dòng
      "CHOP(14): … (nhãn)" + (khi có mẫu) "Mẫu nến phiên gần nhất: …" +
      (khi |streak|≥2) "Heikin-Ashi: N nến …". Data block prompt-side
      nên KỲ VỌNG không cần guard mới; nếu model echo/bịa quanh 3 dòng
      này → vá guard theo quy trình đêm 14/07.
   b. **Preset scorecard sau ~1 tuần tích lũy** (5 preset mới cần
      screener_history + đủ 5/20 phiên forward):
      `python vnstock_preset_score.py --show` phải hiện thêm
      candle_bull / candle_bear / crsi_oversold / double_bottom /
      ha_trend cạnh 9 preset cũ → đọc xem MẪU NẾN nào có alpha thật
      trên HOSE (mục đích (c) của khảo sát StockSharp). double_bottom
      hiếm by design — n nhỏ/0 vài tuần đầu là bình thường.
   c. **GA sau khi có core mới** (rule 2b sẽ revise family-05f9d495 vì
      expectancy net ≤ 0): `python vnstock_genetic.py --run --medium` —
      console phải SẠCH (fix _load_history), median n_trades đủ (≥
      min_trades), so benchmark; ưng → `--run --medium --apply`. GA
      trên core cũ thưa lệnh là vô ích — đợi core mới CÓ lệnh đều.
   d. **Cột "SL trailing" khi có rec mở + trend chạy đủ xa**: giá trị
      nay = max(trailing 5%, PSAR) — trend kéo dài phải thấy mức nâng
      NHANH hơn 5% cố định (PSAR tăng tốc). Chưa có rec mở → chưa thấy.
   e. **Lần train/backtest kế**: metrics row mới phải mang
      `profit_factor` + `recovery_factor` (cả dict 0-lệnh); log task
      18:00 (train/reconcile CLI) phải HẾT spam ScriptRunContext /
      "missing runtime" (fix `_in_streamlit_session` áp mọi CLI đụng
      backtest).
   f. **Screener chạy tối 15/07**: `run.py screener` không gãy với 5
      preset mới (metrics candle/crsi/db/ha đều best-effort try/except
      — kỳ vọng OK; nếu chậm bất thường thì nghi CRSI trên ~1700 mã).
7. **Đợt build 15/07 TỐI (LLM hardening — 3 món deep-dive DojoAgents) —
   VERIFY CÒN NỢ (mọi thứ tự kích hoạt, chỉ cần để ý):**
   a. **Lần digest kế tiếp** (báo cáo mới hoặc `--redigest`): nếu model
      free trả JSON hỏng → console phải có dòng "🔁 <nấc>: cho 1 lượt tự
      sửa (lỗi: …)"; digest lưu provider đuôi "(retry)" khi lượt sửa ăn.
      Nếu thấy retry mà VẪN hỏng thường xuyên → lời phê chưa đủ trúng,
      xem describe_digest_error có nhánh nào thiếu.
   b. **Sổ LLM ledger tự tích lũy** sau lần chạy đầu có call LLM
      (run.py news / digest / brief): `python vnstock_llm_ledger.py
      --show` phải ra bảng per provider; `run.py doctor` có dòng "LLM
      call ledger" (⬜ khi chưa có call là ĐÚNG thiết kế). Khi nào nghi
      ladder rơi bậc âm thầm → mở sổ xem cột rate-limit.
   c. **Strip think-tags**: chỉ lộ tác dụng khi ladder free đổi sang
      model reasoning (deepseek-r1 style) — không cần verify chủ động;
      nếu một ngày digest/sentiment dính chữ "think"/suy nghĩ tiếng Anh
      lạ → nghi strip miss dạng thẻ mới, thêm tên thẻ vào _THINK_NAMES.
   d. **Món CHƯA LÀM chờ chốt**: net-worth curve cho portfolio_tab
      (khảo sát DojoAgents — curve = Σ qty×close(t) từ buy_date + đường
      VNINDEX cùng kỳ, zero fetch, ~50-70 dòng) — user nói "làm đi" là
      triển; PE band lịch sử vẫn để dành (cần EPS quý, scope VN30).
8. **Đợt review guard close brief 15/07 (5 fix, mục 🔬 ở dưới) — VERIFY
   CÒN NỢ trên close brief PHIÊN SAU (mọi fix tự kích hoạt qua guard chain
   / telegram):**
   a. **% thay đổi VNINDEX**: TLDR/Tổng kết phải KHỚP mục kỹ thuật — không
      còn cảnh "TLDR giảm 1.36% mà kỹ thuật +0.00%". Nếu bar VNINDEX vẫn
      phẳng (day_change 0.00 do bar EOD trễ) → brief phải ghi "gần như đi
      ngang (0.00%)" nhất quán, KHÔNG bịa %. (Muốn số ngày THẬT thì cần bar
      VNINDEX về trước giờ chạy close — vấn đề DATA, không phải guard.)
   b. **Dòng tiền NN 2 vế**: 2 ngành nối bằng "trong khi" phải giữ SỐ RIÊNG
      (không còn cùng magnitude do nhiễm chéo); dấu +/− khớp mua/bán ròng.
   c. **GTGD so TB**: câu "cao/thấp hơn TB N phiên" phải khớp chiều thật.
   d. **Mức S/R**: mọi S1/S2 < giá đóng cửa, R1/R2 > giá; KHÔNG còn "S=giá
      đóng cửa". Residual chấp nhận: S1 có thể xa (=low_52w) khi giá ở đáy
      range — role-ordering thủng-S1→S2 hơi ngược vai là ĐÃ BIẾT, không vá.
      **Nâng cấp 17/07 (close 15:33)**: dạng tệ hơn "thủng S1=X → mục tiêu
      S2=X" (2 vai CÙNG mức vì cả hai pin về low_52w) → enforce_sr_direction
      nay CẮT vế mũi-tên của vai 2 khi trùng số (áp cả R1/R2); cặp khác số
      không đụng. **Residual "ngược vai" HẾT CÒN CHẤP NHẬN (user bắt cùng
      chiều 17/07)**: "thủng S1=1,445.64 → mục tiêu S2=1,774.22" — thủng mức
      SÂU mà mục tiêu CAO HƠN là phi logic → pass XẾP LẠI VAI: S1 = hỗ trợ
      GẦN giá nhất, S2 sâu hơn (R1 gần, R2 xa); cả 2 vai đúng 1 giá trị +
      thứ tự ngược → hoán đổi số giữa 2 nhãn (mức vẫn là mức thật đã pin);
      nhiều giá trị/vai → không đoán. Chạy TRƯỚC dedupe, idempotent.
      **User bắt LẦN 2 cùng ngày — vai 2 phải TRONG TẦM**: swap xong vẫn còn
      "→ mục tiêu S2=1,445.64" cách giá ~19% (biên độ HOSE 7%/ngày là trần
      vật lý, giữa đường còn MA200/đáy tháng là mốc THẬT trong ctx) → pass
      thứ 3: vai 2 = mức known KẾ TIẾP sau vai 1 trong tầm `_SR_MAX_MOVE_PCT`
      (7%, tunable); không còn mức nào trong tầm → CẮT vế mục tiêu. CHỈ can
      thiệp khi ctx KHÔNG có canon vai 2 (support_2/resistance_2 — có canon
      thì enforce_pivot_labels là chủ). Chuỗi đủ 4 tầng: pin đúng phía →
      xếp đúng vai → vai 2 kế tiếp trong tầm → dedupe trùng mức.
   e. **Caveat BUY-vs-bias**: khi regime GIẢM (score ≤ -3 / momentum ≤ -50)
      mà "Khuyến nghị đang mở" có lệnh BUY → phải có dòng ⚠️ "_BUY_BIAS_
      CAVEAT" ngay dưới khối lệnh trên Telegram (áp cả morning & close).
   f. Nếu lộ PATTERN LỖI MỚI → chạy lại workflow review 7-cụm×verify như
      đợt này (script cached: close-brief-guard-regression-1507), vá tiếp.
9. **Đợt HNX/SBV 16-17/07 (nguồn LNH ngày + policy auto — mục 🏦/🏦② đã
   verify TRỌN trên máy user; còn lại toàn PASSIVE, tự đến chỉ để ý):**
   a. **Pipeline 18:00 tối nay**: lần đầu `run.py all` chạy bước macro với
      2 nguồn SBV mới (daily + policy = 2 request thêm mỗi refresh) — kỳ
      vọng chạy êm; nếu bước macro chậm/lỗi bất thường → nghi WAF SBV,
      xem log, cân nhắc thêm gap sleep vào fetch_page (hiện chỉ backfill
      có gap giữa các TRANG).
   b. **LNH ngày tự dày lên**: bài SBV đăng ~1 ngày sau phiên → vài ngày
      tới `run.py macro` phải thấy as_of ON nhích theo (07-16, 07-17…).
      Đứng yên nhiều ngày → `python vnstock_sbv_rates.py --diag` (schema
      đổi thì sửa parse_items; doctor `--net` có dòng "SBV daily LNH").
   c. ✅ XONG 17/07 (laptop): `doctor --net` ra "SBV daily LNH (mạng)" ✅
      (on=4.16 @07-15) + cả 10 probe mạng sống; 3 ⚠️ còn lại là cache
      laptop (xem gotcha 2 máy) — xác nhận nốt trên desktop ở item 1.
   d. **Mở dashboard**: sub-tab 🌐 Vĩ mô — chart lịch sử `interbank_on`
      giờ granularity NGÀY (300 điểm backfill) phải render mượt; nguồn
      hiển thị sbv_daily/sbv_portal đúng nhãn.
   e. **Khi SBV đổi lãi suất điều hành (vài lần/năm)**: registry phải tự
      nhích trong ngày (item 3450482 thay tại chỗ) — đây là lần verify
      THẬT đầu tiên của policy auto; nếu không nhích → soi `--policy` +
      guard as_of trong khối sbv_daily của vnstock_macro.refresh.
   f. **Chờ user "làm đi"**: nâng gauge thanh khoản band tĩnh → percentile
      lịch sử (trụ 4 VnBondLab) — data ĐÃ ĐỦ (300 ngày ON trong cache
      sbv_daily_rates); thiết kế gợi ý: percentile của spread ON−điều hành
      trên cửa sổ 250 phiên, giữ band tĩnh làm nhãn phụ.

10. **Đợt vá chiều-tối 17/07 (6 fix từ ảnh user + 2 lần bắt lỗi S/R) —
    VERIFY trên CLOSE BRIEF KẾ TIẾP (sau khi user pull trên máy chạy brief):**
    a. **Dòng Trigger/TLDR S/R** phải qua đủ 4 tầng `enforce_sr_direction`:
       đúng phía + đúng VAI (S1/R1 = gần giá nhất) + vai 2 là mức KẾ TIẾP
       trong tầm 7% (kỳ vọng với data hiện tại: "thủng S1=1,774.22 → mục
       tiêu S2=1,770.28" = MA200; không còn mức trong tầm → vế mục tiêu bị
       CẮT, chỉ còn "thủng S1=…"). KHÔNG còn dạng nào trong 3 bệnh cũ:
       S=close / S1=S2 cùng số / mục tiêu cách giá ~19%.
    b. **Mục 🌐 Vĩ mô (brief) + báo cáo tuần + sub-tab**: chỉ số đứng im
       không còn "▲ +0.00% (VND yếu đi)" — rơi vào dòng gộp "Đi ngang"
       (fmt_change nén đổi làm tròn về 0, formatter dùng chung).
    c. Ghi nhận ĐÃ verify trên close 15:33 17/07: TLDR % khớp mục kỹ thuật
       (fix vnindex_change ăn) · khối Rủi ro canonical chuẩn + ngữ cảnh
       BĐS · watchlist "GIẢM TỶ TRỌNG nếu thủng / canh MUA NẾU vượt" đúng
       luật bias · lead/lag "Họ VIN −1.369pp" contrib thật · caption 🎯
       4/7 (57%) sống trên UI.
    d. Nếu S/R vẫn lệch dạng MỚI → mở rộng test_close_1507_review theo
       quy trình cũ; trục soi thêm = mục 8 checklist CLOSE brief ("kịch
       bản phải khả thi trong biên độ ngày").

11. **Đợt tối 17/07 (VCI outage → probe nguồn + fallback VCI→KBS + nút 🚀)
    — VERIFY CÒN NỢ:**
    a. **Pipeline bù giá** (user chạy `run.py all`/nút 🚀 tối 17/07 hoặc
       sáng 18/07, lúc VCI khỏe — probe 21:58 đã xanh): sync phải hoàn tất
       ~1724 mã (skip-if-done bỏ phần đã tải 21:13), 12 bước về đích,
       doctor cuối sạch → desktop production đồng bộ hoàn chỉnh lần đầu
       với code mới. KHÔNG tắt máy giữa chừng (bệnh 0xC000013A).
    b. **✅ VERIFY XONG NGAY TRONG ĐÊM BUILD (23:01-23:20 17/07 — VCI chết
       suốt run)**: sau fix nuốt-lỗi (bd43f8a — _fetch_prices cũ `except:
       pass` làm timeout thành df rỗng, breaker không bao giờ đếm được;
       user bắt tại trận 22:51), run thật ra ĐỦ kịch bản: "⚡ MỞ MẠCH" đúng
       phút 3:13 (8 mã đầu phải cạn ~5 lượt tenacity nội bộ vnstock ×30s
       trước khi lỗi lộ — trễ ~3ph đầu run là BY DESIGN), progress 0→150
       mã/34s (KBS 0.4s/mã), summary "⚡ Fallback KBS: 1299 mã", Updated
       1396, KHÔNG mã nào bị từ chối vì "lệch %" (KBS cùng adjustment
       basis với kho — 1299 mã ghi sạch). 121 Errors = 3 loại lành tính:
       cả 2 nguồn cùng chết (ASA/BED) · KBS ValueError một số mã (KBS
       không phục vụ đủ biên) · CCI reconcile từ chối vì KBS thiếu bar
       đối chiếu (chốt an toàn chạy đúng). Tự lành khi VCI khỏe.
    c. **Probe nguồn tích lũy** (passive): `python vnstock_source_probe.py`
       chạy thêm vài run giờ KHÁC (sáng, giờ giao dịch) — cột "tích lũy"
       mới đo được độ bền; 3 run đầu (tối outage) đã có trong cache.
    d. Ghi nhận 17/07: desktop 759 pass (5 integration fallback chạy
       THẬT) · sandbox 749+7 skip · VCI outage timeline 21:13 ốm → 21:52
       chết → 21:58 hồi — khớp giả thuyết "giờ batch EOD". VCI ốm TIẾP
       đêm 18/07 23:05 → "giờ ốm buổi tối" là pattern lặp, không phải
       sự cố lẻ.
    e. **✅ 20/07: DESKTOP XANH TRỌN 15/15 doctor + 1271 full pass, 0
       fail** — sau 3 lớp vá hermetic cùng một bài học (17/07 fixture
       fast-list thiếu fetcher → 18/07 fixture file khác cũng thiếu, 6
       fail full → 20/07 singleton BREAKER rò trạng thái giữa test, 3
       fail updater): tất cả chốt về `tests/conftest.py` DÙNG CHUNG
       (chặn 8 fetcher macro + _FX_ENDPOINTS=() + reset BREAKER trước/
       sau MỖI test — file test/fetcher mới tự được bảo vệ). Quà kèm:
       full suite 254s → ~10-20s (96% thời gian cũ là ngồi chờ mạng).
       VCI khỏe lại trong ngày 20/07, kho bar 20/07 tươi "hôm nay".

### 📅 AUDIT LỊCH ĐỊNH KỲ sau ~10 đợt tích hợp (17/07 — user hỏi, CHỜ CHỐT)

Đã rà `run.py all` (12 bước) + 3 task Scheduler + nút dashboard. **Phần ỔN**:
mọi nguồn data mới đều qua bước `macro` (HNX/SBV tuần/SBV ngày/policy/FRED/
NSO/FX) + gold/allocation/scorecard/reflection/foreign-flow/doctor là bước
pipeline; screener tối nuôi preset history; events/overview tự refresh khi
tạo brief; fundamentals task T2; nút "Cập nhật giá" đúng scope (chỉ giá).

**3 LỖ HỔNG THẬT (cadence ngày/tuần đang chạy TAY) — user chưa chốt:**
1. `run.py telegram morning` + `close` — 2×/ngày KHÔNG có task nào (mọi
   brief Telegram từ trước tới nay là user chạy tay; pipeline 18:00 chỉ
   chuẩn bị data). Đề xuất: task 11:40 T2-T6 (morning) + 19:00 T2-T6
   (close, sau pipeline xong).
2. `run.py rates-weekly` — báo cáo tuần lãi suất (hướng B) chưa có lịch.
   Đề xuất: T7 09:00.
3. `vnstock_train.py --once` — vẫn tay (user chọn 27/04, pending #1);
   không train đều → reconcile/decay/stance-track chấm thưa. Đề xuất
   nhắc lại: 15:05 T2-T6.
Tùy chọn nhỏ: bước `preset-score` best-effort vào pipeline tối (cache
expander 📋 luôn tươi thay vì chờ bấm 🔄). Khi user chốt món/giờ → sửa
`scripts/setup_scheduled_tasks.ps1` (thêm entry vào $Tasks) + user chạy
lại script Run-as-Admin trên desktop.

**Checklist gốc (đã chạy gần hết — giữ làm tài liệu lệnh):**
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
    (d) **Pin % gắn TÊN LỚP trong văn xuôi (15/07 — brief phân bổ đầu tiên
    trên máy user)**: TLDR bịa "Giảm cổ phiếu xuống 10% (từ 15%), tiền gửi
    45%" — pass (d) pin mọi "<lớp>…N%" về bảng band; gate mục "Phân bổ đề
    xuất" (allocation-only) nên "cổ phiếu…%" trong brief ngày không đụng.
    Ghi nhận prose-quality (KHÔNG phải lỗi số): mục "Phản biện band B4" của
    Mistral Small nén 4 luận điểm debate thành đồng-ý/bác-bỏ logic lộn xộn
    ("regime -4 trái ngược band B4"?!) — theo dõi, nếu lặp thì nâng model
    cho brief allocation (cadence tháng, 1 call — đáng dùng agent mạnh).
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

### 🧠 Reflection + 🗣 Debate (DONE 2026-07-14 — từ khảo sát TradingAgents, user duyệt "làm đi")

Hai mảnh LLM MỀM bổ sung quanh hệ deterministic — cả hai best-effort, đi qua
cascade sức-mạnh của `vnstock_report_digest.digest_call` (đã verify), không
mảnh nào sinh số được pin vào output:

- **`vnstock_reflection.py`** — rec đóng (tp/sl/expire, có pnl — superseded/
  stale là đóng hành chính, bỏ) + kỳ scorecard khép → 1 call/outcome ra
  "2-4 câu bài học" (đúng hướng chưa + luận điểm nào đổ + 1 bài học), sanitize
  1 dòng, lưu `_meta/reflection_log.json` (cap 200, id `rec-<id>`/`alloc-<start>`
  → idempotent; LLM chết → KHÔNG đánh dấu, lượt sau thử lại). Trần
  `--max` 3 call/lượt. Bước `reflection` trong `run.py all` (SAU audit — 
  reconciler vừa đóng rec). Brief nạp qua `collect_context` 8f →
  `ctx["reflections"]` (3 bài mới nhất) → block "🧠 Bài học" trong prompt MỌI
  brief_type — block NỘI BỘ, chỉ thị cấm chép nguyên văn/tạo mục (không cần
  guard vì không splice output). Tắt: `VNSTOCK_REFLECTION=0` (module) /
  `VNSTOCK_BRIEF_REFLECTIONS=0` (brief). `recent_closed_recommendations` nay
  SELECT thêm `rationale` (để bài học soi luận điểm lúc mở).
- **`vnstock_debate.py`** — devil's advocate cho band phân bổ, THU GỌN từ
  bull/bear debate của TradingAgents (họ 10-20 call/quyết định — ngược
  free-tier): đúng **1 call/kỳ**, chỉ brief ALLOCATION (cadence tháng).
  Prompt = dữ kiện THẬT từ allocation state + consensus → 3 luận điểm chống
  band + 1 "Điều kiện đảo ngược:"; mỗi dòng sanitize; cache
  `_meta/allocation_debate.json` theo (as_of, band) — recompute cùng kỳ
  không tốn call; LLM chết → dùng cache cũ/bỏ qua. `generate_brief`
  (allocation) tự gọi trước build_prompt → ctx["allocation_debate"] → block
  "🗣 Phản biện" trong prompt + template ⚠️ buộc đối diện TỪNG luận điểm.
  Tắt: `VNSTOCK_ALLOC_DEBATE=0`. CLI: `--run [--force]` / `--show`.
- **Tests**: `tests/test_reflection.py` (11) + `tests/test_debate.py` (5) +
  3 test wiring trong test_brief — tất cả vào `--fast`.

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

**Khảo sát HKUDS/Vibe-Trading (2026-07-14): KHÔNG dùng framework — CẢ 2
MÓN ĐÃ TRIỂN KHAI cùng ngày (xem mục 🎲 Validation + 🔻 Decay bên dưới).**
Nền tảng trading agent lớn (~203K dòng Python + React; Alpha Zoo 460
factor, backtest A-share/Mỹ/HK/Ấn/crypto, 18+ loader, MCP 68 tool, broker
thật). Không dùng vì: không có HOSE/HNX (vnstock đã tự chủ VN), kéo cả
platform ngược triết lý; sandbox AST của họ mình ĐÃ tương đương
(vnstock_strategy cấm import + dunder-escape + walk AST lồng).

### 🎲 Validation backtest + 🔻 Decay lifecycle (DONE 2026-07-14 — 2 món Vibe-Trading, user "làm cả 2 món")

Cả 2 đều deterministic thuần (numpy + SQL, zero LLM/fetch/dependency),
nằm trong `vnstock_strategy.py`; tests `tests/test_strategy_validation.py`
(26, hermetic — mem/EXECUTOR monkeypatch) đã vào `--fast`.

**Món 1 — kiểm định chống-ăn-may** (chặn chiến lược LLM overfit/ăn may
thành active): `backtest()` nay gắn `metrics["validation"]` =
`validate_backtest_quality(trades)` → {p_value_sharpe, sharpe_ci,
walk_forward, passed, reasons}:
- `monte_carlo_pvalue` — **SIGN-FLIP permutation** (KHÁC bản gốc Vibe: họ
  xáo THỨ TỰ pnl rồi đo path-metrics, nhưng Sharpe per-trade mean/std là
  BẤT BIẾN thứ tự → xáo thứ tự vô nghĩa ở đây; sign-flip test đúng H0
  "pnl đối xứng quanh 0 = không có edge"). 1000 sim, seed cố định
  (deterministic), +1 hiệu chỉnh nên p không bao giờ 0. None khi < 3
  lệnh / σ=0.
- `bootstrap_sharpe_ci` — CI 90% percentile (tham khảo, KHÔNG gate — mẫu
  nhỏ CI rộng).
- `walk_forward_consistency` — chia lệnh theo start_idx thành 4 fold;
  hiệu năng dồn 1 giai đoạn → fail.
- **Gate `passed`** = p < 0.10 VÀ ≥ 50% fold dương. `_validation_ok`
  (True khi VẮNG validation — backtest cũ/quá ít lệnh, gate n_trades
  hiện hành xử) được thêm vào: `_cold_start` (chỉ ảnh hưởng nhãn status —
  cold-start vẫn luôn promote "always have one active"), `_do_revise`
  (trượt → retired, giữ bản cũ), `_do_tune` (trượt → không nhận params).
- Dashboard: panel Chiến lược hiện "🧪 Kiểm định: ĐẠT (p=…)" / cảnh báo 🎲.

**Món 2 — vòng đời decay** (backtest nói hay nhưng lệnh THẬT tụt →
tự demote): `strategy_health(sid)` so win-rate rec đóng thật
(`recommendation_performance`, bỏ superseded) với win-rate backtest gần
nhất → state: `insufficient` (live n < `_DECAY_MIN_LIVE_N`=8 / chưa có
backtest) · `healthy` · `monitoring` (gap ≥ 12đ%) · `decayed` (gap ≥
`_DECAY_WR_GAP`=25đ% HOẶC live wr ≤ 30% + avg pnl âm).
`check_strategy_decay(apply=True)` — state=decayed → `update_strategy_status
(sid,'decayed')`: get_active_family lọc status='active' nên bản decayed
tự rơi khỏi vòng tune/revise → strategy_loop kế tiếp **cold-start bản
mới** (không cần status 'disabled' riêng — 'decayed' là terminal record).
Gọi best-effort CUỐI `reconcile_recommendations` (vnstock_train) — chạy
mỗi lần reconciler đóng rec (train/brief/_maybe_reconcile_overdue/nút
dashboard). Chỉ transition decayed ghi DB; monitoring chỉ cảnh báo
(dashboard 🟡/🔻). Kill switch: `VNSTOCK_STRATEGY_DECAY=0`. Lưu ý đọc
số: win-rate live tính trên MỌI rec đóng của strategy_id đó (không cửa
sổ thời gian) — đủ dùng ở n nhỏ; nếu sau này rec tích lũy hàng trăm thì
cân nhắc cửa sổ 30-60 rec gần nhất.

**Khảo sát QuantConnect/Lean (2026-07-15): KHÔNG dùng — món trailing-stop
hint ĐÃ TRIỂN KHAI cùng ngày (xem mục 💧📈 bên dưới).** Engine C# khổng lồ
(~6,200 file, 500MB — lớn nhất
từng khảo sát) cho backtest/live execution đa sàn, đang được bảo trì
tích cực. Không dùng vì: (1) C# + live-execution platform — mình là
Python dashboard hỗ trợ quyết định, không đặt lệnh; (2) không có
data/fee model HOSE (toàn Binance/Alpaca/IB/Bybit…); (3) **Algorithm
Framework 5 tầng (Universe → Alpha → Portfolio Construction → Risk →
Execution) — hệ mình ĐÃ mirror đủ về khái niệm**: screener=universe,
strategy+brief=alpha, sizing=portfolio construction, bias-caveat/decay/
validation=risk, execution=con người; (4) Insight scoring (direction/
period/confidence chấm sau) ≡ stance track + reconciler đã có;
(5) VolumeShareSlippage ≡ món zipline vừa ghi; 169 indicators đã tự có;
Optimizer framework (grid search params) — tune hiện LLM-driven, để
dành nếu muốn tune deterministic. **ĐÁNG MƯỢN (nói "làm trailing
stop")**: `TrailingStopRiskManagementModel` (Algorithm.Framework/Risk) —
track ĐỈNH giá trị vị thế, tụt >X% (mặc định 5%) từ đỉnh → thoát. Áp
cho mình: rec đang mở có SL TĨNH; nay đã có MTM → thêm cột display-only
"SL trailing đề xuất" = max(SL gốc, đỉnh close kể từ ngày mở × (1−5%))
trong bảng Open recommendations — nâng SL theo đà lãi, khóa lợi nhuận.
KHÔNG đổi convention reconciler (vẫn chấm theo SL gốc); chỉ gợi ý hiển
thị. Bộ Risk models còn lại (MaxDrawdownPortfolio/MaxSectorExposure/
MaxUnrealizedProfit=chốt lời trần) ghi nhận để dành cùng chỗ.

**Khảo sát quantopian/zipline (2026-07-15): KHÔNG dùng — món liquidity-cap
ĐÃ TRIỂN KHAI cùng ngày (xem mục 💧📈 bên dưới).** Backtester event-driven
kinh điển của
Quantopian nhưng repo GỐC ĐÃ CHẾT (commit cuối 10/2020, Python 3.5-3.6
era, C-ext bcolz; bản sống là zipline-reloaded của CHÍNH Stefan Jansen —
trùng tác giả ML4T vừa khảo sát). Không dùng vì: abandoned + không
calendar/bundle HOSE + Pipeline API (factor engine declarative) mình đã
có tương đương là screener + kho parquet riêng; commission per-share/
per-dollar đã có flat 0.4% VN-specific. **ĐÁNG MƯỢN (nói "làm liquidity
cap")**: `VolumeShareSlippage` (finance/slippage.py) — fill bị CAP theo
% volume của bar (mặc định 2.5%) + price impact ∝ volume_share². Áp
dụng thực dụng cho mình: **"KL gợi ý" hiện cap theo %NAV nhưng KHÔNG
theo THANH KHOẢN** — NAV lớn + mã mỏng → gợi ý khối lượng vượt xa ADV
= bất khả thi (tự đẩy giá). Fix nhỏ: `suggest_position_size` cap thêm
qty ≤ ~10% ADV20 (vol20 sẵn trong kho), ghi rõ lý do cap trong output.
Để dành: price impact bậc hai cho backtest — chỉ có nghĩa khi backtest
mô phỏng SIZE lệnh (hiện per-trade %, không qty).

### 💧 Cap thanh khoản sizing + 📈 SL trailing gợi ý (DONE 2026-07-15 — 2 món zipline + Lean, user "làm cả 2")

Cả 2 deterministic thuần, display-only, zero LLM/fetch; tests bổ sung vào
`tests/test_costs_sizing.py` (18 tests) — đã trong `--fast`.

**Món 1 — cap thanh khoản** (`vnstock_strategy.suggest_position_size`,
mirror `VolumeShareSlippage` của zipline): tham số mới `adv_shares` (KLGD
TB 20 phiên) → qty ≤ `max_adv_pct` (mặc định 10%, config
`_meta/sizing_config.json` — user chỉnh trong expander ⚖️, cột 4) × ADV;
cap kích hoạt → flag `capped_adv` → bảng hiện "(cap TK)" (phân biệt với
"(cap)" = cap %NAV). ADV rác/thiếu → bỏ qua cap (không nổ); mã quá mỏng
cap dưới 1 lô → None (không gợi ý 0 cp). Dashboard: `_mtm(row)` trong
market_tab nay load `days=35` và trả thêm ADV20 (`h["volume"].tail(20)
.mean()`) → `_adv_by_ticker` → truyền vào `_sps`.

**Món 2 — SL trailing gợi ý** (`vnstock_strategy.trailing_stop_hint(sl,
closes_since_entry, trail_pct=5.0)`, mirror `TrailingStopRiskManagementModel`
của Lean): đỉnh close KỂ TỪ NGÀY MỞ REC × (1 − 5%) — nâng SL theo đà lãi
để khóa lợi nhuận. CHỈ trả giá trị khi vượt SL gốc > +0.5% (chưa có lãi
đáng kể → None, khỏi gợi ý "hạ SL"); rec SELL không áp dụng. Cột mới
"SL trailing" trong bảng Open recommendations (— khi chưa kích hoạt).
**KHÔNG đổi convention reconciler — hệ VẪN chấm theo SL gốc trong DB**
(mirror nguyên tắc display-only của KL gợi ý/MTM); closes lọc theo
`h["time"] >= created_at[:10]` nên rec mở hôm nay chỉ thấy bar hôm nay.

**Khảo sát stefan-jansen/machine-learning-for-trading (2026-07-15): KHÔNG
tích hợp trực tiếp — CẢ 2 MÓN ĐÃ TRIỂN KHAI cùng ngày (xem mục 📋 Preset
scorecard bên dưới).** Repo
GIÁO TRÌNH đi kèm sách ML4T **3rd edition** (2026): 27 chương/122 notebook
+ 9 case study end-to-end (ETF/crypto/intraday/options/FX/futures), code
lõi nằm trong 6 thư viện ml4t-* riêng. Không tích hợp vì: (1) là giáo
trình, không phải lib để import; (2) stack nặng lệch hẳn (Polars/PyTorch/
LightGBM/Optuna/Docker per chương) — ngược triết lý zero-dependency;
(3) data Mỹ (NYSE/CME calendar, SEC filings), không HOSE; (4) mảng
GenAI/multi-agent của sách — hệ này đã tự có bản VN-specific. **Điều đáng
nể: sách XÁC NHẬN hướng đi hiện tại** — vòng "retrain/pause/retire khi
edge decay" ≡ decay lifecycle vừa build; "evidence boundary" tách tuning
khỏi evaluation ≡ gate validation 🧪; chương riêng về transaction costs ≡
món phí 0.4%; walk-forward CV ≡ fold check. **2 MÓN ĐÁNG MƯỢN (đều
deterministic, zero dep):**
1. **Preset scorecard — chấm alpha của screener** (workflow đánh giá
   factor chương 6-8): 9 preset screener chạy mỗi tối và lưu
   `_meta/screener_history/*.json` từ lâu nhưng CHƯA BAO GIỜ được chấm —
   không biết oversold/momentum/breakout… preset nào THẬT SỰ có alpha
   trên HOSE. Làm: module đọc history + kho giá → forward return 5/20
   phiên của rổ hit từng preset vs baseline universe → hit-rate + excess
   return + IC per preset. Mirror triết lý reconciler/stance-track: "mọi
   tín hiệu phát ra đều phải được chấm". Trigger: user hỏi "preset nào
   đáng tin" / muốn tinh gọn danh sách preset.
2. **Hiệu chỉnh đa-thử-nghiệm cho gate 🧪** (chương 7 Factor Zoo /
   multiple testing — "selecting the best inflates estimates"): mỗi vòng
   revise/cold-start backtest N ứng viên rồi CHỌN BEST → p-value của
   winner bị lạm phát do selection bias, tích lũy qua các vòng train
   hàng ngày. Fix rẻ kiểu Bonferroni: nhân p của winner với số ứng viên
   trong vòng trước khi so ngưỡng 0.10 + log n_trials vào metrics (vài
   dòng trong _do_revise/_cold_start). Trigger: khi có ứng viên ĐẠT gate
   lần đầu — trước lúc promote đáng siết thêm nấc này.
Bỏ qua nhưng ghi nhận: Deflated Sharpe/PBO đầy đủ (cần chuỗi dài + nhiều
strategy — để dành khi tích lũy nhiều family); purged/embargo CV (fold
per-trade hiện tại đủ scale); event study quanh GDKHQ (hay, chưa đau);
TabPFN/PatchTST/RL/TimeGAN (ngược triết lý free-tier deterministic).

### 📋 Preset scorecard + 🎲 hiệu chỉnh chọn-lọc (DONE 2026-07-15 — 2 món ML4T, user "làm cả 2 món")

Cả 2 deterministic thuần, zero LLM/fetch; tests `tests/test_preset_score.py`
(7, hermetic — history/giá fake) đã vào `--fast`.

**Món 1 — `vnstock_preset_score.py`**: chấm alpha 9 preset screener —
forward return 5/20 PHIÊN của rổ hit từng preset (từ snapshot
`_meta/screener_history/*.json`, giữ ~30 ngày) so VNINDEX cùng cửa sổ →
`avg_excess` + `hit_rate` (% tín hiệu thắng index) + n per preset/horizon.
Đọc parquet trực tiếp (CLI-safe); tín hiệu chưa đủ H phiên tương lai
KHÔNG chấm non; mã thiếu giá bỏ qua. CLI `--show [--horizons 5,20]
[--days 30]` / `--refresh` (ghi cache `_meta/preset_scorecard.json`,
atomic). KHÔNG vào run.py/pipeline — công cụ phân tích user gọi tay;
lưu ý mẫu 30 ngày = XẾP HẠNG tương đối giữa preset, chưa kết luận được
tuyệt đối. UI/screener_tab để dành khi cần.
**`_stitch_units` (vá ngay lần chạy đầu 15/07)**: run đầu ra "oversold
excess +42.73%/5 phiên" — artifact của `_normalize_prices` chuẩn hóa
PER-BAR (bar > 500 chia 1000): mã penny quanh mốc 500 VND cho chuỗi
[480, 0.51, 495, 0.52] → return giả ±96,959% đầu độc mean. Return bất
biến thang đo → stitch dò bước nhảy ×≥200 (trần sàn 15%/phiên không bao
giờ chạm) và ép cả chuỗi về CÙNG thang. **TODO ngầm đáng nhớ**: artifact
này tồn tại ở MỌI chỗ tính return qua `_normalize_prices`/`_load_history`
với mã < ~500-1,000 VND (backtest/emit trên penny, chg5 screener?) —
scorecard đã tự vệ; nếu thấy số penny quái ở chỗ khác thì nghĩ ngay đến
per-bar normalization.
**Baseline đọc lần đầu (15/07, 30 ngày regime BEAR — đọc lại khi đổi
pha)**: mean-reversion thắng trend-following rõ (reversal +0.81 / oversold
+0.36 vs momentum −1.47 / strong_uptrend −2.01 / breakout −2.02 %/5p);
edge bắt-đáy chỉ sống ~5 phiên (20p toàn âm, hit 21-31% — bounce tắt rồi
rơi tiếp); top preset +0.36-0.81%/5p TRƯỚC phí 0.4% round-trip ⇒ sau phí
gần hòa vốn — nhất quán với verdict 🧪 "regime này chưa có edge đủ dày".
Caveat: 1 regime, tín hiệu lặp mã liên ngày (mẫu hiệu dụng nhỏ hơn n).
**"Đọc kết quả" vào dashboard (user thích, DONE 15/07)**:
`interpret_scorecard(card, breadth_pct, cost_pct)` — bản DETERMINISTIC
của phần diễn giải (user khen phần này): 5 nhận định suy từ chính số
liệu bằng code, KHÔNG LLM — (1) trường phái nào thắng (nhóm
`_MEANREV_PRESETS` vs `_TREND_PRESETS`, chênh ≥1đ% mới kết luận, kèm
"đặc trưng thị trường điều chỉnh/xu hướng"); (2) edge sống bao lâu (top
preset dương ở h0 nhưng âm ở h1 → "kèo ngắn"; toàn âm → "đứng ngoài
cũng là một vị thế"); (3) so phí 3 nấc (≤0.1 hòa vốn / ≤0.6 "phí ăn gần
hết edge" / còn ăn được); (4) ngữ cảnh độ rộng (breadth <40% + đa số
preset âm → "excess âm hàng loạt một phần do độ rộng"); (5) caveat mẫu.
Render ở CLI `--show` (mục "— Đọc kết quả —") + expander "📋 Chấm điểm
preset" MỚI trong tab Screener (bảng xếp hạng + nút 🔄 Tính lại +
bullets, ghi rõ "suy từ số liệu, không LLM").

**Món 2 — `vnstock_strategy.apply_selection_penalty(metrics, n_trials)`**:
Bonferroni cho winner-of-N — cả 3 vòng thi (`_cold_start`/`_do_revise`/
`_do_tune`) sau khi CHỌN BEST đều gọi với n = số ứng viên: p_adj =
min(1, p×n), ghi `n_trials` + `p_value_adj` vào validation; p_adj ≥ 0.10
→ passed=False kèm lý do "thắng cuộc thi nội bộ chưa đủ bằng chứng edge".
CHỈ SIẾT không nới (p_adj nhỏ không lật passed=False→True — walk-forward
có thể đã đánh trượt). Panel Chiến lược ưu tiên hiện p_adj + "· N ứng
viên". Áp TRƯỚC save_backtest nên row DB mang verdict đã hiệu chỉnh.

**Khảo sát HKUDS/AI-Trader (2026-07-15): KHÔNG dùng platform — CẢ 2 MÓN
ĐÃ TRIỂN KHAI cùng ngày (xem mục 🎯 Stance track bên dưới).** Cùng nhà
với Vibe-Trading nhưng là thứ khác hẳn:
NỀN TẢNG XÃ HỘI hosted cho agent (ai4trade.ai) — agent tự đăng ký bằng
cách đọc SKILL.md, publish signal, copy-trade, leaderboard/challenge/
team/points, paper trading $100K, Polymarket; service FastAPI ~21.7K
dòng + frontend để VẬN HÀNH platform đa người dùng. Không dùng vì:
(1) bản chất là DỊCH VỤ BÊN THỨ 3 — nối agent + đẩy tín hiệu/danh mục
của mình lên đó ngược triết lý tự chủ local (tín hiệu là data riêng —
KHÔNG "register" agent của hệ này lên ai4trade dù pattern SKILL.md
self-registration thú vị); (2) thị trường US/crypto/Polymarket, không
HOSE/HNX; (3) trích xuất dự đoán của họ là REGEX KEYWORD trên text tự
do (signal_quality.py) — hệ mình đã có rec CÓ CẤU TRÚC entry/TP/SL +
reconciler chấm chính xác hơn hẳn; (4) fee flat 0.1% — mình đã có 0.4%
round-trip VN-specific.

**2 món ĐÁNG MƯỢN (đều deterministic, zero LLM, data có sẵn):**
1. **Chấm điểm STANCE của brief** (mirror vòng signal_predictions →
   outcome scoring của họ): "Stance ngày mai" (TĂNG/GIẢM/TRUNG TÍNH) là
   dự đoán hướng được lưu trong MỌI close brief nhưng chưa bao giờ được
   chấm — hệ chấm REC mà chưa chấm BRIEF. Làm: tracker so stance với
   chiều VNINDEX phiên kế tiếp (brief_memory đã có stance qua consensus
   parser + kho giá có sẵn) → % đúng rolling hiện dashboard + bơm vào
   reflection ("gọi GIẢM 5 phiên gần nhất, đúng 3/5").
2. **MTM lãi/lỗ tạm tính cho rec ĐANG MỞ** (mirror live mark-to-market
   của leaderboard): bảng Open recommendations hiện chỉ có entry/TP/SL —
   không biết lệnh đang xanh hay đỏ. Thêm cột "Giá hiện tại" + "Lãi/lỗ
   tạm tính %" từ close mới nhất trong kho (display-only).
Bỏ qua nhưng ghi nhận: điểm chất lượng signal 5 trục (verifiability/
evidence/specificity/novelty/review — brief mình đã bị guard chain ép
cấu trúc chặt hơn nhiều); experiment/A-B framework + teams/points
(platform đa người dùng); yfinance fallback ladder (đã có pattern ladder
khắp nơi).

### 🎯 Stance track + 💹 MTM rec đang mở (DONE 2026-07-15 — 2 món AI-Trader, user "làm cả 2 món")

Cả 2 deterministic thuần, zero LLM/fetch; tests `tests/test_stance_track.py`
(7, hermetic — memory/giá fake) đã vào `--fast`.

**Món 1 — `vnstock_stance_track.py`**: chấm "Stance ngày mai" của MỌI close
brief đã lưu (brief_memory) vs chiều VNINDEX phiên KẾ TIẾP — hệ chấm REC
mà trước giờ chưa chấm BRIEF. Parser tái dùng `_extract_section` +
`_detect_stance` của consensus (không thể lệch nhau). Luật chấm:
bullish đúng nếu đổi > +`_FLAT_BAND` (0.1%); bearish nếu < −0.1%; neutral
đúng nếu |đổi| ≤ `_NEUTRAL_BAND` (0.3%); stance CÓ HƯỚNG mà phiên kế
|đổi| ≤ 0.1% → KHÔNG chấm (nhiễu); unknown/brief lỗi/brief mới nhất
(chưa có phiên kế) → bỏ. `stance_records/stance_summary/summary_line`;
CLI `--show [--limit N]` (mặc định 60 brief, mỗi agent 1 dòng). Dashboard:
caption "🎯 Stance ngày mai: đúng X/Y…" ngay dưới consensus banner ở panel
AI Brief (best-effort). KHÔNG bơm vào prompt (tránh mở bề mặt guard mới) —
cân nhắc sau khi đủ mẫu.

**Món 2 — `vnstock_strategy.unrealized_pnl_pct(entry, last, action)`**:
lãi/lỗ TẠM TÍNH gross, display-only. Bảng Open recommendations thêm 2 cột
"Giá HT" + "L/L tạm" (close mới nhất từ `_load_history`, best-effort —
thiếu giá → "—"); lệnh đang xanh/đỏ thấy ngay, không phải chờ reconcile.

### 🏦 HNX yield curve + SBV weekly + cross-source (DONE 2026-07-16 — 3 nguồn baocaolaisuatvatiente, user "làm cả 3")

Cả 3 deterministic thuần, best-effort, VERIFY-GATED (sandbox chặn nguồn —
`--diag` trên máy có mạng); tests `tests/test_hnx_sbv.py` (14, hermetic —
fetch fake) đã vào `--fast`. Chảy qua bước `macro` sẵn có (như VBMA/FRED,
KHÔNG cần bước run.py riêng).

**`vnstock_hnx.py`** — lợi suất TPCP HNX 8 kỳ hạn/NGÀY (thay/bổ sung VBMA
PDF tuần cho 2Y/10Y): POST `hnx.vn/ModuleReportBonds/Bond_YieldCurve/
SearchAndNextPageYieldCurveData` `pDate=dd/mm/YYYY` → `parse_yield_curve_html`
(tbody>tr>td, cột 0 kỳ hạn khớp CHÍNH XÁC "N năm", ưu tiên cột 2 par;
sanity 0.1<y<15). TLS ladder 3 nấc cho POST (`_http_post`: certifi→OS
trust→verify=False; `VNSTOCK_HNX_TLS_STRICT=1` cấm nấc cuối). `fetch_latest`
lùi ngày bỏ T7/CN. Cache `_meta/hnx_yields.json` history 260 phiên (đủ mẫu
percentile "trụ 4" VnBondLab sau này). Loaders `load_yields`/`yield_on`.
Tắt `VNSTOCK_HNX=0`. **Wiring macro**: `_fetch_hnx` ghi 2Y/10Y SAU VBMA →
GHI ĐÈ (nguồn ngày > PDF tuần, source="hnx"); tắt `VNSTOCK_MACRO_HNX=0`.
Cache giữ CẢ 8 kỳ hạn (chỉ 2Y/10Y vào registry — cap 13; 5Y/7Y/15Y/20Y
để dành cho gauge/percentile).

**`vnstock_sbv.py`** — bản tin tuần SBV: LNH ON/1W/2W/1M + **OMO ròng SỐ**
(hút=+/bơm=−, trước chỉ suy từ từ khoá tin) + **tỷ giá trung tâm**.
`parse_sbv_text` (regex thuần, testable) trên PDF → `pdf_to_text` (dùng lại
vnstock_vbma). Cache `_meta/sbv_weekly.json` merge-safe (trường None giữ giá
trị cũ). `--set-omo` nhập tay. Tắt `VNSTOCK_SBV=0`. **Wiring macro**: LNH ON
qua `resolve_interbank_on` (SBV↔VBMA, ưu tiên SBV + cờ divergence >15%);
OMO/tỷ-giá-trung-tâm lưu `cache["_meta"]["sbv"]` display-only (ngoài
registry 13).
**FETCH + PARSE — ĐÃ VERIFY THẬT & CHẠY (16/07)**: listing SBV render bài
qua JS (HTML tĩnh 73KB chỉ 1 link `/vi/trang-chu`) → KHÔNG scrape. Mirror
repo gốc: `fetch_weekly` DỰNG URL `sbv.gov.vn/vi/web/sbv_portal/w/<title-slug>
-<DD>-<DD>.<M>.<YYYY>` (ngày T2-T6 zero-pad, THÁNG KHÔNG pad — `_week_date_slug`;
`_SBV_TITLE_SLUGS[0]`="diễn-biến-thị-trường-ngoại-tệ-và-thị-trường-liên-ngân
-hàng-tuần-từ" ĐÃ verify khớp). Bài tuần N publish tuần N+1 → bắt đầu TUẦN
TRƯỚC lùi 5 tuần; 404 = nghỉ → thử tuần trước. Bài chứa PDF `/documents/…/
<uuid>` → tải + `pdf_to_text`. `_fetch_pdf_text` tách riêng, `--dump-text`
in text thô.
**PARSE (calibrate từ text THẬT tuần 06-10.7.2026)**: lãi suất LNH lấy TỪ
BẢNG cuối bản tin — `_parse_interbank_table` bắt dòng "VND <ON> <1T> <2T>
<1 tháng>…" (≥4 token số/-, phân biệt với văn xuôi "bằng VND đạt 4.428.576
tỷ"). KHÔNG parse câu tường thuật (BẪY: "kỳ hạn qua đêm giảm 0,03%/năm" là
mức THAY ĐỔI + là USD; mọi kỳ hạn chung 1 mệnh đề "xuống các mức A,B,C" nên
regex per-tenor gán SAI) → thà None (VBMA vẫn cover LNH). Bản tin FX/LNH này
KHÔNG có tỷ giá trung tâm / OMO (ở bản tin điều hành SBV KHÁC) → 2 field đó
= None là ĐÚNG; OMO regex nay yêu cầu ngữ cảnh "ròng"/"OMO"/"thị trường mở"
(không bắt nhầm số doanh số). Fixture test = text thật. **Số thật verify**:
ON 5.21 / 1T 5.57 / 2T 6.13 / 1 tháng 7.32 (%/năm, TB tuần). Cross-source:
SBV 5.21 (TB tuần) vs VBMA 4.28 (điểm) chênh 19.6% → cờ divergence bật
(2 nguồn đo khác thời điểm — cờ chỉ cảnh báo, ưu tiên SBV).

**Cross-source `resolve_interbank_on(sbv, vbma)`** → (giá trị, nguồn, cờ
lệch): cả 2 → ưu tiên SBV + cờ khi chênh >15% (mirror `_fx_crosscheck`
er-api↔VCB, mở rộng sang lãi suất). Thiếu 1 → dùng nguồn kia.

**Doctor**: `net_hnx` + `net_sbv` vào NET_CHECKS (probe fetch thật — máy
có mạng; sandbox toàn ❌ là bình thường).

**✅ ĐÃ VERIFY THẬT TRÊN MÁY USER (16/07)**: HNX --diag ra 8 kỳ hạn (1Y
3.819 … 20Y 4.658, TLS ladder → verify=False đúng); SBV --diag+refresh ra
bài tuần 06-10.7.2026, parse ĐÚNG từ bảng (ON 5.21/1T 5.57/2T 6.13/1M
7.32) sau fix calibrate; macro `--show`: 2Y/10Y source="hnx" ngày 07-16,
LNH ON source="sbv". Nguồn 1+2+3 CHẠY THẬT.

**🔎 VỤ CACHE SBV NHIỄM SỐ SAI (16-17/07, đã fix + chờ user chạy lại)**:
`--show` cache ra {ON 4.26, 1W 7.34, 2W 7.76, 1M 7.32} trong khi `--diag`
CÙNG LÚC parse đúng {5.21, 5.57, 6.13, 7.32} → fetch+parse hiện tại ĐÚNG,
cache bị ghi bẩn bởi lượt refresh trước. **Root cause**: `_SBV_TITLE_SLUGS`
từng có slug fallback thứ 2 "thông-tin-hoạt-động-ngân-hàng-trong-tuần-từ" =
BẢN TIN KHÁC (hoạt động NH — lãi suất huy động/cho vay) cũng có dòng
'VND <số> <số>…' → khi bài FX/LNH fail tạm (nghi WAF SBV vì gọi dồn dập —
cùng phiên có lần `--refresh` trả "không có data"), fetch rơi xuống bài này
và bảng huy động parse thành LNH (4.26/7.34/7.76 = số huy động). **Fix 3
lớp (17/07)**: (1) GỠ slug #2 — chỉ còn bài FX/LNH đã verify; (2) gate
header trong `_parse_interbank_table` — dòng VND chỉ nhận khi ~250 ký tự
trước có "Qua đêm" (header bảng LNH; bảng tiền gửi không có); (3)
`_REQUEST_GAP_S=2.0` giãn cách giữa các request SBV (mirror sleep_s=3 "WAF
avoidance" của repo gốc). Tests: `test_sbv_table_requires_interbank_header`
+ `test_sbv_single_slug_fx_interbank_only`. **✅ VERIFY XONG trên máy user
17/07**: `--refresh` ra {ON 5.21, 1W 5.57, 2W 6.13, 1M 7.32}; `run.py macro`
registry "LNH ON: 5.21%/năm (nguồn sbv) (+0.95đ% vs hôm trước — hôm trước
chính là 4.26 bẩn)"; gauge thanh khoản ra **CĂNG +0.71** (5.21 − 4.5). Cờ
divergence nằm trong `cache["_meta"]["sbv"]["interbank_on_diverged"]` —
`--refresh` không in ra console, xem ở sub-tab Vĩ mô/doctor. Lưu ý:
`interbank_1w` registry vẫn nguồn vbma (4.92) — SBV chỉ resolve ON, đúng
thiết kế.

**✅ QUYẾT ĐỊNH ĐÃ CHỐT (user 17/07: "muốn số liệu luôn cập nhật nhất")**:
`resolve_interbank_on(sbv, vbma, sbv_as_of, vbma_as_of)` nay chọn theo **ĐỘ
MỚI của DATA** — tuần data mới hơn thắng bất kể nguồn; cùng tuần/thiếu as_of
→ ưu tiên VBMA (ĐIỂM cuối tuần sát hiện tại hơn TRUNG BÌNH cả tuần của SBV);
cờ divergence >15% vẫn bật khi có cả 2 (SBV giữ vai trò cross-check + OMO).
Kèm 2 fix nhãn thời gian: (a) `SBVWeekly.week_end` = thứ 6 TUẦN DATA của bản
tin — `refresh` đóng dấu `as_of` = ngày DATA thật, KHÔNG phải ngày fetch
(trước đó cache ghi as_of=hôm-nay dù data là tuần trước — vi phạm nguyên tắc
data_date ≠ generated_at); (b) khối SBV trong `vnstock_macro.refresh` không
ghi đè registry khi đã có reading MỚI hơn (VBMA fail lượt này nhưng lượt
trước ghi tuần mới hơn → source label không bị lật bừa). Hệ quả với số hiện
tại: cả 2 nguồn cùng tuần 06-10.7 → ON = VBMA 4.28 → gauge thanh khoản về
"bình thường" (−0.22) thay vì CĂNG +0.71; khi SBV ra bản tin tuần mới trước
VBMA thì SBV tự thắng. Tests: `test_sbv_resolve_interbank` (recency đủ
nhánh) + `test_sbv_refresh_as_of_is_data_week_not_fetch_date` +
`test_sbv_fetch_weekly_carries_week_end`.
**Tàn dư history + `--drop` (17/07, run đầu sau fix)**: registry ra "5.21
nguồn vbma, tính đến 07-17" — CON LAI vì history `interbank_on` còn 2 entry
CODE CŨ ghi sai ngày (07-17=5.21 đóng dấu ngày fetch, 07-16=4.26 bẩn);
giá trị đọc theo NGÀY MỚI NHẤT nên vớ 07-17 cũ, còn source label do VBMA
vừa set. Registry KHÔNG tự sửa được (không biết entry nào chủ đích) → thêm
CLI cache-surgery `python vnstock_macro.py --drop <key> <YYYY-MM-DD>`
(`drop_reading`, KeyError khi key lạ, False khi ngày không có). Dọn chuẩn:
`--drop interbank_on 2026-07-17` + `--drop interbank_on 2026-07-16` →
`run.py macro` ra ON 4.28 (vbma, tính đến 07-10), gauge thanh khoản
"bình thường" −0.22. **✅ user chạy xong 17/07 — refresh lại KHÔNG tái
nhiễm** (recency + guard chống ghi đè giữ đúng). Toàn bộ chuỗi HNX/SBV/
resolve/gauge coi như ĐÓNG; đổi ưu tiên/ngưỡng sau này chỉ đụng
`resolve_interbank_on` + `_INTERBANK_DIVERGENCE_PCT`.

**⚠️ GOTCHA 2 MÁY (lộ thật 17/07 — vụ "FRED thiếu key dù đã update")**:
user có **desktop + laptop**, cả 2 đều clone C:\vnstock. `.env` và
`data_warehouse/` KHÔNG đi theo git → **mỗi máy một bản riêng**:
- **Desktop = máy PRODUCTION**: Task Scheduler (pipeline 18:00 / corp
  actions CN / fundamentals T2) đăng ký Ở ĐÓ; .env desktop có FRED_API_KEY.
- **Laptop = máy phụ**: doctor/badge trên laptop phản ánh cache CỦA LAPTOP
  — thấy "overview cũ 2 ngày"/"FRED thiếu key" trên laptop KHÔNG có nghĩa
  production hỏng. Chẩn đoán độ tươi data đêm / Get-ScheduledTaskInfo phải
  chạy TRÊN DESKTOP; verify UI/code thì máy nào cũng được (sau khi chạy
  tay run.py macro/screener tại chỗ).
- Thêm key mới vào .env → nhớ thêm CẢ 2 MÁY (key free dùng chung được).

**⚠️ GOTCHA GIT (gặp thật 16/07)**: máy user checkout nhánh KHÁC
(`claude/phase-1-kickoff-lzorv6`) nhưng CHUNG lineage với nhánh session
(`claude/stocksharp-dashboard-research-bv9tas`) — commit SHA trùng. Khi
user "git pull" không lấy được commit mới (khác tên nhánh) → chạy code cũ
(bug đã fix vẫn tái hiện). Cách sửa: `git fetch origin` +
`git merge --ff-only origin/<session-branch>` (ff sạch vì chung tổ tiên).
Dấu hiệu chẩn đoán: `python -c "import M; print(hasattr(M,'<hàm mới>'))"`
ra False = đang chạy code cũ dù đã "pull".

**Nếu nguồn chết sau này**: HNX đổi layout bảng → sửa `parse_yield_curve_html`
/cột par (`--diag`); SBV đổi tiêu đề bài → toàn 404, cập nhật `_SBV_TITLE_SLUGS`
(`--diag` in URL thử); đổi layout PDF → `--dump-text` gửi lại chỉnh
`_parse_interbank_table`. Nguồn nào chết → VBMA/FRED vẫn fallback (không gãy).

### 🏦② LNH THEO NGÀY từ portal SBV (DONE 2026-07-17, CHỜ USER VERIFY) — `vnstock_sbv_rates.py`

Trả lời câu user "muốn số liệu luôn cập nhật nhất": truy từ trang
`sbv.gov.vn/vi/lãi-suất-thị-trường-liên-ngân-hàng` (user gửi URL) bằng chuỗi
probe (`vnstock_sbv.py --probe` / `--probe-api` — GIỮ LẠI làm công cụ khảo
sát portal SBV sau này): trang Liferay render khung bảng RỖNG, data đổ bằng
**headless-delivery API công khai, không key**:
`/o/headless-delivery/v1.0/content-structures/3450260/structured-contents`
→ totalCount ~3.100 bài = **~13 NĂM LNH theo NGÀY** (7 kỳ hạn ON→9M +
doanh số). Trang "Lãi suất NHNN quy định" cùng cơ chế, structure id
**3450482** (`_STRUCT_POLICY` — schema CHƯA soi; muốn auto sbv_policy_rate
thì bảo user chạy `vnstock_sbv.py --probe-api ".../content-structures/
3450482/structured-contents?pageSize=2&sort=datePublished:desc"` rồi wire).

**2 bẫy data thật (test khoá cả 2)**: (a) `ngayApDung` = midnight VN
serialize `T17:00:00Z` hôm TRƯỚC → `_vn_date` +7h rồi lấy date, không thì
lệch 1 ngày; (b) kỳ hạn có `footNode` "(*)" = số THAM CHIẾU ngày cũ độn vào
(9M không có giao dịch) → LOẠI khỏi rates.

Mirror vnstock_hnx: cache `_meta/sbv_daily_rates.json` history 400 ngày
(percentile "trụ 4" sắp đủ mẫu — có `--backfill N` trang×100 ngày, 1 năm ≈
3 trang); loaders `load_rates`/`rate_on`; tắt `VNSTOCK_SBV_DAILY=0`. Macro:
`_fetch_sbv_daily` chạy SAU 2 nguồn tuần, ghi `interbank_on`/`interbank_1w`
source="sbv_daily" CHỈ khi as_of ≥ max history (recency 17/07 giữ nguyên —
nguồn ngày tự thắng tuần). Tắt wiring: `VNSTOCK_MACRO_SBV_DAILY=0`. Doctor:
`net_sbv_daily`. Số thật lúc khảo sát: ON 15/07 = 4.16, 14/07 = 4.18 (khớp
chiều VBMA 4.28 cuối tuần 10/07 — LNH đang hạ nhiệt).

**✅ VERIFY XONG trên máy user 17/07 — ăn ngay lượt đầu**: `--diag` ra 3
ngày × 6 kỳ hạn (15/07: on 4.16, 1w 4.74, 1m 7.17…); `run.py macro` registry
ON **4.16 (nguồn sbv_daily, tính đến 07-15)** + 1W 4.74 sbv_daily, đổi tính
đúng vs entry VBMA 07-10 (−0.12/−0.18đ%); gauge thanh khoản −0.34 "bình
thường" trên số NGÀY (trễ ~1 ngày thay vì 1-2 tuần). `--backfill 3` cũng
đã chạy (17/07): **300 ngày ON→9M trong cache** — mẫu percentile lịch sử
("trụ 4" VnBondLab) coi như ĐỦ, khi nào nâng gauge thanh khoản từ band tĩnh
sang percentile thì data có sẵn.

**Lãi suất điều hành AUTO (DONE 2026-07-17, wire từ probe-api 3450482)**:
`parse_policy_items`/`refresh_policy`/`load_policy` trong vnstock_sbv_rates —
structure 3450482 totalCount=1 (SBV thay item tại chỗ = quyết định hiện
hành). **BẪY DATA THẬT (test khoá)**: field `ngayApDung` ghi SAI THÁNG
(2023-03-18T17:00Z = 19/03 VN) trong khi title "19-06-2023" + QĐ 1123 ngày
16/06/2023 → parser ưu tiên NGÀY TRONG TITLE, fallback ngayApDung. Giá trị
"4,500%" = 4.5 (phẩy thập phân). Macro: `_fetch_sbv_policy` cùng block
sbv_daily → registry `sbv_policy_rate` source="sbv_portal" với guard as_of ≥
max(hist) — `--set` tay ngày mới hơn vẫn thắng. Tái chiết khấu (3.0) lưu
trong cache["policy"] display-only (ngoài registry 13). CLI:
`python vnstock_sbv_rates.py --policy`. **✅ VERIFY XONG trên máy user
17/07**: `--policy` ra đúng (hiệu lực 2023-06-19, QĐ 1123, 4.5/3.0); registry
có entry manual 2026-06-15 (--set tay tháng 6, ngày gõ lệnh ≠ ngày hiệu lực)
chặn guard đúng thiết kế → dọn bằng `--drop sbv_policy_rate 2026-06-15` →
`run.py macro` ra "4.50%/năm (tính đến **2023-06-19, nguồn sbv_portal**)".
Từ nay SBV đổi lãi suất điều hành là registry + 2 gauge tự cập nhật trong
pipeline tối — TOÀN BỘ 13 chỉ số registry đã AUTO (PMI còn --set mùng 1-2
nhưng có fallback RSS).

### 📄 Báo cáo tuần lãi suất — A + B (DONE 2026-07-16, user chọn "A+B", ý skill baocaolaisuatvatiente)

Skill nguồn là report-generator (fetch 5 nguồn → HTML → Vercel), nhưng
dashboard ĐÃ có sẵn TOÀN BỘ data (registry 13 + 3 gauge + HNX 8 kỳ hạn +
OMO/SBV) → báo cáo chỉ còn tầng RENDER. Lật ngược skill (nó ~80% code đi
lấy data) — mượn Ý trình bày (data-driven, 0 speculation), KHÔNG copy code.

**`vnstock_rates_report.py`** (thuần, deterministic, ZERO fetch/LLM):
- `build_report_data(as_of)` → dict từ cache: `load_macro` (bảng lãi suất/
  tỷ giá theo `_RATE_KEYS`) + 3 gauge + `vnstock_hnx.load_yields` (đường
  cong) + `vnstock_sbv.load_weekly` (OMO/tỷ giá trung tâm). Trường thiếu →
  bỏ, KHÔNG bịa.
- `_narrative` = câu SUY TỪ SỐ (nhãn gauge + đổi LNH ON ≥0.10đ% + OMO
  bơm/hút) — KHÔNG dự đoán tương lai → không cần guard/LLM.
- `render_html(data)` → HTML TỰ CHỨA (inline CSS + **đường cong lợi suất
  bằng inline SVG** polyline — zero external dep, verify test `http`
  không xuất hiện) cho tab/tải/Artifact. Lãi suất tăng = màu ĐỎ (thắt).
- `render_telegram(data)` → text gọn (không chart) cho hướng B.
- CLI `--html out.html` / `--text` / `--as-of`.

**Hướng A — tab dashboard** `dashboard/rates_report_tab.py` (sub-tab thứ 5
"📄 Báo cáo tuần" trong tab Tin tức, cạnh 🌐/📚/🧭): lazy-import st, render
HTML inline (`components.html`) + nút ⬇️ Tải HTML + nút 📤 Đẩy Telegram.
UI mỏng trên cache (mirror macro_tab).

**Hướng B — Telegram** `vnstock_telegram.push_rates_weekly()` (cadence
TUẦN, render_telegram + footer) + `run.py rates-weekly` (chạy tay/lịch
riêng — KHÔNG vào brief 2×/ngày). Cache rỗng → trả `{ok:False}` sạch.

Tests: 6 test rates_report cuối `tests/test_hnx_sbv.py` + smoke tab trong
`test_allocation_reports_tabs.py` (nay 3 tab). **VERIFY**: mở dashboard →
tab Tin tức có sub-tab "📄 Báo cáo tuần" render bảng + đường cong SVG (cần
`run.py macro` chạy trước để có cache); `python vnstock_rates_report.py
--text` in bản Telegram; `run.py rates-weekly` đẩy thật (cần TELEGRAM
token). Đường cong chỉ hiện khi HNX đã verify (--diag máy có mạng).

**Khảo sát Thanhtran-165/baocaolaisuatvatiente (2026-07-16): repo = SKILL
sinh BÁO CÁO HTML tuần + deploy Vercel (sai hình dạng Streamlit, KHÔNG
dùng framework), NHƯNG 3 NGUỒN DỮ LIỆU ĐÃ TRIỂN KHAI (mục 🏦 trên).**
Repo = "VN Rates Weekly": pipeline 7
bước fetch SBV+VBMA+VNBA (PDF) + HNX+FRED (API) → report.json → HTML +
audit gates + Playwright QA. Bản thân nó "port từ Bond Lab providers".
KHÔNG có LICENSE = all rights reserved → mượn Ý TƯỞNG + SỰ KIỆN (URL/
endpoint/tenor map/cách parse), KHÔNG copy code. Phần report/Vercel/
audit-gate/Playwright + VNBA narrative (bank PBT) = bỏ (orthogonal /
FRED+foreign-flow đã cover global).

**3 nguồn ĐÁNG MƯỢN (deterministic, lấp gap vĩ mô đã ghi ở mục Vĩ mô):**
1. **HNX yield curve POST API — MẠNH NHẤT, thay/bổ sung VBMA PDF cho lợi
   suất TPCP**: `https://hnx.vn/ModuleReportBonds/Bond_YieldCurve/
   SearchAndNextPageYieldCurveData`, POST `pDate=dd/mm/YYYY` → parse HTML
   `table tbody tr/td` → **8 kỳ hạn 1Y/2Y/3Y/5Y/7Y/10Y/15Y/20Y, granularity
   NGÀY**, chính thức (HNX = sàn niêm yết TPCP). Hiện dashboard lấy 2Y/10Y
   từ `vnstock_vbma._parse_bond_yields` (PDF tuần, mong manh, chỉ 2 kỳ
   hạn) → HNX API ROBUST hơn hẳn + nhiều tenor hơn → nuôi thẳng registry
   `govt_bond_yield_2y/10y` + 3 gauge kỳ-hạn/đường-cong/quốc-tế + mở khóa
   thêm 5Y/7Y (percentile lịch sử "trụ 4" VnBondLab dễ hơn khi có data
   ngày). **SSL bẫy đã ghi rõ**: HNX thiếu chứng chỉ TRUNG GIAN → cần
   verify=False fallback — TLS ladder 3-nấc của `vnstock_nso._http_get`
   (certifi → OS store → verify=False cho nguồn công khai) xử ĐÚNG ca này.
   Verify-gated: sandbox chặn hnx.vn → phải `--diag` trên máy có mạng
   (endpoint là ứng viên CHƯA verify, HTML table selector có thể đổi).
2. **SBV weekly PDF chính thức — nguồn thứ 2 cho LNH + OMO SỐ**: article
   `sbv.gov.vn/vi/web/sbv_portal/w/<slug>` (slug dạng "01-05.6.2026") →
   PDF nhúng `/documents/20117/0/...pdf/<uuid>` → `parse_sbv_interbank`
   bắt Overnight/1 tuần/2 tuần/1 tháng + **tỷ giá trung tâm** + **OMO ròng**
   (hút=+/bơm=−, tỷ VND). Hiện: `sbv_policy_rate` NHẬP TAY, LNH qua VBMA,
   OMO chỉ có qua từ khoá tin (`_MACRO_KEYWORDS` "bơm/hút ròng") — SBV PDF
   cho OMO thành SỐ + LNH nguồn 2 (chính thức) + tỷ giá trung tâm (hiện
   so er-api↔VCB, thêm trung tâm làm neo). Verify-gated (slug SBV hay ghi
   nhầm, PDF cần uuid).
3. **Cross-source resolution SBV↔VBMA cho LNH ON** (`resolve_cross_source`):
   2 nguồn có cả → lấy 1 nguồn + cờ divergence khi lệch > ngưỡng (mirror
   `_fx_crosscheck` er-api↔VCB đã có, mở rộng sang lãi suất). Làm cùng lúc
   nếu triển khai nguồn 1+2.
Ưu tiên nếu user chốt: **nguồn 1 (HNX) trước** — giá trị cao nhất, lấp
đúng điểm yếu "VBMA PDF mong manh" + "cần đủ mẫu ngày cho percentile" đã
ghi. Mô-đun mới `vnstock_hnx.py` (mirror vnstock_vbma/nso/fred: fetch +
parse + cache `_meta/`, doctor check cadence + net probe, tắt bằng env),
`vnstock_macro` ưu tiên HNX rồi fallback VBMA PDF cho 2Y/10Y.

**Khảo sát StockSharp/StockSharp (2026-07-15): KHÔNG dùng framework —
CẢ 3 MÓN + profit/recovery factor ĐÃ TRIỂN KHAI cùng ngày (xem mục 🕯
bên dưới).** Nền tảng trading
C#/.NET production (~1.624 file .cs, 166MB clone): connector đa sàn
(crypto/MOEX/IB — KHÔNG có HOSE/HNX), matching engine, backtest emulator,
Designer (visual strategy WPF), 188 indicators, candle patterns, risk
rules, optimizer brute-force + genetic. Không dùng vì: (1) C#/.NET +
GUI Windows — lệch hẳn stack Python/Streamlit; (2) không data VN;
(3) là platform live-execution, mình là dashboard hỗ trợ quyết định;
(4) mọi mảnh "đáng mượn" họ hàng framework này (fee/slippage/sizing/
trailing/bar-ordering/validation) ĐÃ mượn đủ từ nautilus/zipline/Lean/
ML4T — và bản của StockSharp KHÔNG tốt hơn: emulator decompose nến theo
thứ tự O→H→L→C CỐ ĐỊNH (`ProcessStoredCandles`, chỉ chính xác khi data
có HighTime/LowTime — vnstock EOD không có) → thua bản adaptive
|high−open| vs |low−open| đã có (còn thấy copy-paste bug: lowState set
HighPrice, MarketEmulator.cs:1131); (5) LGPL — mượn Ý TƯỞNG, không copy
code (như nautilus).

**3 món ĐÁNG MƯỢN (đều deterministic thuần, zero LLM/fetch, port
Python/numpy rẻ):**
1. **CandlePatternRegistry — nhận diện ~30 mẫu nến bằng BIỂU THỨC thuần**
   (`Algo/Candles/Patterns/CandlePatternRegistry.cs`): mỗi pattern = 1-5
   biểu thức trên biến O/H/L/C + dẫn xuất B (thân), LEN (H−L), TS/BS
   (râu trên/dưới), prefix p/pp/ppp = nến trước (vd Bullish Engulfing =
   `"O > C"`, `"(O < C) && (O < pC) && (C > pO)"`; đủ bộ Hammer/Morning
   Star/Three White Soldiers/Harami/Tweezer/Piercing…). Giá trị nhất vì
   dashboard hiện KHÔNG có nhận diện mẫu nến ở đâu (preset screener toàn
   ngưỡng RSI/MACD/EMA/52w/volume) — port thành module nhỏ → (a) preset
   screener mới / cột "Mẫu nến" analysis tab; (b) 1 dòng ngữ cảnh VNINDEX
   trong brief (qua data block — guard chain không đổi); (c) QUAN TRỌNG:
   `vnstock_preset_score` vừa build chấm được ngay pattern nào CÓ ALPHA
   THẬT trên HOSE (mẫu đảo chiều Hammer/Engulfing/Morning Star hợp
   baseline Bear mean-reversion 15/07). Bẫy khi port: `==` trên giá
   (Flat "O == C", Tweezer "H == pH") phải thành tolerance theo bước giá
   HOSE; nến 1 giá LEN=0 (trần/sàn VN hay gặp) phải guard chia 0.
2. **Choppiness Index** (`Algo.Indicators/ChoppinessIndex.cs`): CHOP 14
   phiên = 100·log10(ΣTR/(maxH−minL))/log10(14) — đo trend-vs-range
   thuần giá, bổ sung trục "thị trường đang choppy/sideway" cho regime +
   brief (regime hiện composite MA/RSI/breadth/NN, chưa có trục này);
   ~20 dòng numpy. Nice-to-have, làm cùng món 1 thì tiện.
3. **ConnorsRSI** (`Algo.Indicators/ConnorsRSI.cs`): CRSI = trung bình
   RSI(3) + RSI-streak(2) + percent-rank ROC(100) — chỉ báo mean-reversion
   kinh điển, ứng viên tự nhiên cho preset "oversold nâng cao" khi
   baseline 15/07 cho thấy mean-reversion là edge duy nhất đang sống
   trên HOSE; chấm lại bằng chính preset scorecard. ~30 dòng numpy.

Bỏ qua nhưng ghi nhận: bộ Statistics 50 tham số — profit_factor +
recovery factor ĐÃ LÀM cùng ngày (xem mục 🕯); GeneticOptimizer
với fitness formula + GenerationsStagnation early-stop — user đổi ý
CÙNG NGÀY "làm luôn" → ĐÃ LÀM (xem mục 🧬); Risk rules
(position-time-limit ≈ rec expiry đã có);
order book emulation L2/L3 + Diagram visual programming + Algo.Gpu +
Storages binary + Export Excel — không có data/use-case tương ứng.

### 🔬 Review phản biện chéo close brief 15/07 (DONE 2026-07-15 tối — workflow 7-cụm × verify, user "làm cho tôi đi") — 5 guard gap vá

Close brief thật phiên 15/07 (bản đầu sau đợt vá guard 14/07) → chạy
workflow đa-agent (7 agent triage 1 cụm/agent đối chiếu code guard THẬT +
vòng phản biện xác nhận từng gap bằng cách import vnstock_brief và CHẠY
guard trên đúng chuỗi text). 15 finding: 8 CONFIRMED_GAP (đều sống sót
verify, tái hiện trên code hiện tại — KHÔNG phải stale deploy), 2
DATA_ISSUE, 5 NOT_A_BUG. Gom thành **5 fix** (test
`tests/test_close_1507_review.py` 15 test, vào `--fast`):
1. **`enforce_sector_nn_figures` vượt ranh giới mệnh đề** (REGRESSION thật):
   pass ngành A nuốt số của ngành B qua connector ", trong khi" → pin nhầm
   ("bán ròng 703 tỷ … Ngân hàng" → "+1,496" = số Họ VIN). Fix: (a) thêm
   `trong\s+khi` vào negative-lookahead của gap tên→verb; (b) backstop:
   nếu ngay sau số có "trong ngành <ngành-khác>" thì bỏ qua (số của ngành
   đứng sau). Sau fix, số giữ 703 → net_flow_label bỏ được dấu "+" (trước
   đó +1,496 ≠ |703| nên net_flow trượt → dấu + sống).
2. **`enforce_vnindex_change` bỏ lọt "% không hậu tố so-với"**: bar VNINDEX
   phẳng (day_change=0.00, bar 15/07 chưa về) → model bịa "VNINDEX đóng cửa
   giảm 1.36%" mâu thuẫn mục kỹ thuật "+0.00%". Nhánh 1 cũ BẮT BUỘC "so với
   phiên trước/hôm qua" nên trượt. Fix: nhánh 2 pin "(tăng|giảm) X%" KHÔNG
   cần hậu tố, gate CHỦ NGỮ index (vnindex/chỉ số/kết quả phiên trong ~35
   ký tự trước) + loại GTGD/thanh khoản (_SUBJ_SKIP); dc≈0 → "gần như đi
   ngang (0.00%)". (day_change=0.00 gốc là DATA_ISSUE — bar EOD trễ 1-2
   phiên, doctor đã dung sai; guard chỉ ép brief NHẤT QUÁN với data.)
3. **`enforce_gtgd_baseline_pct` Form 5 (bare-direction)**: "GTGD 16,523.1
   tỷ, cao hơn trung bình 5 phiên" — mệnh đề so sánh ĐỊNH TÍNH không %, không
   guard nào đối chiếu chiều. Fix: pass bắt "(cao hơn|thấp hơn) (TB N phiên|
   phiên trước)" không %, lật từ theo dấu(F/base−1) từ full_day_gtgd_cmp;
   gate |p|>1%; close-only; idempotent; no-op khi đúng.
4. **`enforce_sr_direction` (guard MỚI, sau enforce_pivot_labels)**: hỗ trợ
   S1/S2 phải < close, kháng cự R1/R2 phải > close. Close 15/07: "S2=1,782.12"
   = ĐÚNG giá đóng cửa (support = giá hiện tại, vô nghĩa) vì support_1/2 của
   ctx = None (giá ở đáy range, không swing-low actionable) nên pivot_labels
   bỏ qua. Fix: token SAI CHIỀU trong dải chỉ số 800-2500 → pin về mức KNOWN
   đúng phía gần nhất (close/MA/tuần/tháng/52w). Không đụng giá cổ phiếu
   (ngoài dải) / token đúng chiều; idempotent. **Residual đã biết** (không
   vá — role-ordering fragile): S1=1,445.64 (=low_52w) hợp CHIỀU nhưng xa
   ~19%, giữ nguyên → "thủng S1=1445 → S2=1775" vẫn hơi ngược vai; chấp nhận
   vì S1 là mức THẬT, đã hết cái "= close" gây xấu hổ.
5. **Caveat BUY-vs-bias ở TELEGRAM** (không phải guard body): lệnh mở
   ("Khuyến nghị đang mở (5 mã)" toàn BUY) được `_open_recs_block` append
   NGOÀI apply_brief_guards → guard #27 enforce_buy_vs_bias_caveat không với
   tới. Fix: `vnstock_telegram._open_recs_block` gắn `_BUY_BIAS_CAVEAT`
   (import từ vnstock_brief) khi ≥1 lệnh BUY VÀ `_market_is_bearish()`
   (=_bias_floor_dir GIẢM: regime ≤ -3 hoặc momentum ≤ -50). Gắn cảnh báo
   KHÔNG lọc (mirror guard #27). Áp cả morning & close (đều dùng
   _open_recs_block).
**NOT_A_BUG đã bác (không sửa)**: lead/lag "Chưa có nhóm dẫn dắt" + "Họ VIN
-1.369pp" — guard SẼ sửa nếu ctx có data; brief giữ vì thật sự không ngành
nào ≥0.05pp (ngày giảm diện rộng) và -1.369pp là contrib THẬT (guard đã pin
nếu lệch). Watchlist "canh MUA NẾU vượt" conditional bias-aware = đúng.

### 🕯 Mẫu nến + CHOP + ConnorsRSI + profit/recovery factor (DONE 2026-07-15 — 3 món StockSharp + Statistics, user "làm cả 3 món + ý Statistics")

Cả 4 mảnh deterministic thuần, zero LLM/fetch; tests
`tests/test_candle_patterns.py` (21) + `tests/test_chop_crsi.py` (11) +
2 test build_prompt trong test_brief — tất cả vào `--fast`.

**Món 1 — `vnstock_candle_patterns.py`** (port CandlePatternRegistry, ~27
mẫu, mượn Ý TƯỞNG không copy code — LGPL): mỗi mẫu = hàm thuần trên 1-5
nến cuối (O/H/L/C + B/LEN/TS/BS, list [cũ→mới]). 2 bẫy khảo sát đã xử:
(a) equality giá → tolerance `_REL_TOL` 0.2% (Tweezer/On-Neck; Marubozu so
LEN−B ≤ tolerance theo THANG GIÁ `_tol(H,L)`, KHÔNG theo độ dài đem so —
thân nhỏ sẽ ép tolerance về ~0); (b) nến 1 giá trần/sàn (LEN=0) → mẫu
hình-dạng đơn bị bỏ (tránh Dragonfly+Gravestone cùng-đúng 0≤0). NGOÀI bản
gốc (StockSharp không gate): cặp SONG SINH cùng hình ngược nghĩa
(Hammer↔Hanging Man, Inverted Hammer↔Shooting Star, Dragonfly↔Gravestone)
gate bằng xu hướng 5 phiên trước mẫu (±`_TREND_MIN_PCT` 1%) — thiếu trend
rõ → bỏ CẢ HAI (không bao giờ phát bull lẫn bear cho 1 bar); guard
unit-break ×200 (bẫy per-bar normalization penny — mirror
`_stitch_units`); `spinning_top` loại khỏi output mặc định (nhiễu trung
tính). API: `detect`/`detect_df`/`pattern_labels`; hit sort mẫu NHIỀU nến
(đặc hiệu) trước; tên hiển thị tiếng Việt kèm tên Anh chuẩn trong ngoặc
(hợp luật thuần-tiếng-Việt).

**Wiring screener + scorecard**: `_calc_indicators` thêm
`candle_patterns`/`candle_bull`/`candle_bear` + `crsi` (best-effort);
**3 preset MỚI**: `candle_bull` / `candle_bear` / `crsi_oversold` (CRSI <
10) → tự vào screener_history mỗi tối → `vnstock_preset_score` chấm alpha
trên HOSE như mọi preset (đúng mục đích (c) của khảo sát);
`_MEANREV_PRESETS` += candle_bull, crsi_oversold (candle_bear là tín hiệu
bear-side — không xếp nhóm long, vẫn được chấm riêng).

**Món 2+3 — `vnstock_indicators.py`**: `choppiness_index` (CHOP 14,
100·log10(ΣTR/range)/log10(14); >61.8 choppy / <38.2 có xu hướng —
`chop_label`) + `connors_rsi` bản CỔ ĐIỂN mean(RSI(3), RSI-streak(2),
percent-rank ROC(1) trên 100 phiên) — LƯU Ý: StockSharp dùng biến thể
RSI-của-ROC, mình cố ý theo bản percent-rank kinh điển; cần 102 bar,
thiếu/giá rác → None.

**Wiring brief (parity by construction)**: `_vnindex_technicals` thêm
`chop14` + `candle_patterns` (labels, cap 3; SKIP mẫu nến khi bar cuối là
bar intraday chưa chốt — thân/râu còn đổi tới đóng phiên); block "VNINDEX
kỹ thuật" render 2 dòng mới sau RSI ("CHOP(14): … — đo độ choppy, KHÔNG
chỉ hướng" + "Mẫu nến phiên gần nhất: … (tín hiệu nến tham khảo, cần nến
xác nhận)"). Display-only/ngữ cảnh — KHÔNG vào regime score (mirror triết
lý LEVEL-gauge), data block prompt-side nên KHÔNG cần guard output mới.

**Statistics — `vnstock_strategy.profit_and_recovery(pnls)`**:
profit_factor (Σlãi/|Σlỗ|) + recovery_factor (net/|maxDD|) vào metrics
`backtest()` (cả dict 0-lệnh — downstream không KeyError). Suy biến trả
None thay vì chia 0 (không lệnh lỗ → PF None; equity không DD → RF None);
recovery dùng maxDD BASELINE-0 (mốc vốn ban đầu cũng là đỉnh — chuỗi toàn
lỗ có maxDD=|net|), KHÁC metric `max_drawdown` hiện hành (đỉnh đầu =
cum[0]) — metric cũ GIỮ NGUYÊN, đã ghi chú tại chỗ. GeneticOptimizer:
user "làm luôn" cùng ngày → mục 🧬 ngay dưới.

### 🧬 GeneticOptimizer — GA tune params deterministic (DONE 2026-07-15, món StockSharp thứ 4, user "làm luôn cả geneticOptimizer")

`vnstock_genetic.py` — bản "tune deterministic" từng để dành (Lean →
StockSharp): GA thuần numpy tối ưu params chiến lược ACTIVE, thay/bổ sung
vòng tune LLM. Zero LLM/fetch, **seed cố định** (`_SEED_DEFAULT`) — cùng
data ra cùng kết quả. Tests `tests/test_genetic.py` (14, hermetic —
backtest + mem đều monkeypatch) đã vào `--fast`.

- **3 ý mirror StockSharp** (mượn ý tưởng, không copy code — LGPL):
  Population/GenerationsMax → `--pop 8`/`--gens 5`; **GenerationsStagnation**
  → `--stagnation 2` (best không cải thiện N thế hệ → dừng sớm; họ default
  5, mình 2 vì mỗi thế hệ = N backtest thật); fitness formula → `--fitness
  expectancy|sharpe|profit_factor|recovery_factor` (bản rút gọn metric-key,
  không compile biểu thức).
- **Không gian params suy TỰ ĐỘNG** (`_param_space`): mọi param SỐ →
  khoảng [0.4×, 2.5×] giá trị hiện tại (int giữ int sàn 1; bool/str/0 giữ
  cố định — 0 không có thang). GA: elitism 2 + tournament 3 → crossover
  pick/blend per-gene → mutation gaussian 15% bề rộng; **cache dedup theo
  bộ gene** (không backtest lại params trùng).
- **Kỷ luật chống-ăn-may GIỮ NGUYÊN như tune LLM** — điểm sống còn:
  backtest NET sau phí; winner bị `apply_selection_penalty` với
  **n_trials = số bộ params UNIQUE đã chấm** (GA chấm ~20-40 ứng viên ≫
  3-4 agent LLM → penalty nặng tương ứng, cố ý); adopt cần thắng benchmark
  active RE-BACKTEST cùng config (né bẫy benchmark đóng băng 15/07) VÀ
  `_validation_ok` sau penalty; fitness -inf khi n_trades <
  `_MIN_TRADES_DEFAULT` (8).
- **Vận hành**: công cụ GỌI TAY (mirror preset_score — KHÔNG vào run.py
  all; backtest full ~8 phút × 40 đánh giá là bất khả thi). Mặc định
  `lite_config` (~10-30s/backtest → trọn gói ~10-30 phút) + **DRY-RUN**;
  `--apply` mới ghi DB (update_strategy_params agent="GeneticOptimizer" +
  2 row backtest: benchmark + best — panel Chiến lược thấy 🧪 như thường).
  `--full` dùng config đầy đủ (cảnh báo thời gian in sẵn trong help).
  `--space` in không gian gene suy ra. DB chưa init → thông báo sạch,
  không stacktrace (`_active_or_none`).
- **Verify lần đầu trên máy user (trưa 15/07) — lộ + vá ngay 2 bug:**
  (a) **`_load_history` boot nguyên dashboard ngoài Streamlit** — import
  `vnstock_dashboard` trong bare mode "chạy được" (st.cache_data dùng
  MemoryCacheStorageManager) nên KHÔNG rơi xuống nhánh parquet như thiết
  kế cũ → thực thi ~4k dòng app (st.pills nav…), spam hàng trăm warning
  ScriptRunContext vào MỌI CLI đụng backtest (train/reconcile/genetic).
  Fix hệ thống trong vnstock_strategy: `_in_streamlit_session()`
  (`streamlit.runtime.exists()`) — có runtime thật mới dùng loader
  dashboard, ngoài ra đi THẲNG `_load_history_from_parquet`. Test poison
  module chốt không-import.
  (b) **`min_trades=8` chặn sạch ứng viên trên lite config** (~25 cửa
  sổ, chiến lược chọn lọc tự nhiên < 8 lệnh): benchmark chấm min_trades=0
  có số (−1.3174) mà GA toàn "—", báo cáo không nói lý do. Fix:
  `_MIN_TRADES_LITE=4` tự áp khi lite (full giữ 8), CLI `--min-trades`
  override; report thêm chẩn đoán `n_below_min_trades` + best THÔ
  (bỏ gate, kèm n lệnh) + hint "hạ --min-trades hoặc --full" khi mọi
  ứng viên bị gate.
- **Verify vòng 2 (trưa 15/07, sau fix)**: console SẠCH ✅, chẩn đoán ăn ✅
  — và lộ tầng sâu hơn: active (family-05f9d495) ra đúng **1 lệnh trên
  ~20 cửa sổ lite** (benchmark n_trades=1, best thô = chính params gốc)
  → lite config MÙ với chiến lược thưa lệnh, không phải lỗi gate. Thêm
  **`--medium`** (`medium_config`: 10 mã, lookback 300, step 15 → ~90 cửa
  sổ, ~1-2 phút/backtest, trọn gói ~30-60 phút) + báo cáo in **median
  n_trades** của ứng viên (nhìn 1 dòng biết cỡ mẫu đủ hay chưa);
  `genetic_tune_active` nhận `config="lite|medium|full"` thay cờ lite.
- **Cách dùng đúng (đúc kết sau 2 vòng verify)**: GA hữu ích nhất trên
  core CÓ lệnh đều — active hiện tại đằng nào cũng bị rule 2b revise
  (expectancy net ≤ 0) → tune SAU KHI có core mới; median n_trades thấp
  → nâng --medium/--full thay vì hạ --min-trades. So kết quả với vòng
  tune LLM — nếu GA thắng ổn định thì cân nhắc gọi từ `_do_tune` như một
  "agent" thêm (TODO để dành, đừng tự ý nối vào pipeline tối).
**Khảo sát Alpha-Dojo/DojoAgents (2026-07-15): KHÔNG dùng framework —
1 MÓN NHỎ ĐÁNG MƯỢN (net-worth curve, CHƯA LÀM) + 1 món để dành (PE
band).** AI copilot đầu tư cá nhân full-market (A-share/US/HK): agent-loop
engine trên strands-agents (~430 file Python — token ledger, context
compression, planning/triggers, memory, multi-agent, skills) + React SPA
4 trụ (Portfolio/Markets/Sectors/Equities) + gateway chat. Không dùng vì:
(1) **tầng DATA là `dojosdk` — SDK ĐÓNG của chính họ** (K-line/PE band/
sector taxonomy A-share/US/HK, KHÔNG có HOSE/HNX) — trái tim repo là thứ
mình không xài được; module `quant/` trong repo chỉ là dataclass scaffold
RỖNG (62 dòng), logic thật nằm sau SDK + LLM loop; (2) agent-loop
"cognitive" LLM tự gọi tool nhiều vòng — ngược triết lý deterministic-first
+ free-tier (cùng lý do đã bỏ TradingAgents 10-20 call/quyết định);
(3) React SPA + FastAPI + docker — lệch hẳn stack Streamlit; (4) trùng
những gì ĐÃ CÓ: 4 trụ ≈ các tab hiện hành; sector exposure vs benchmark →
portfolio_tab đã so VN30 (bar+pie+diff) + PnL theo ngành; scheduled
research (planning/cron) ≈ Task Scheduler + Routines; memory/reflection
đã có bản VN. Apache 2.0.

**1 món ĐÁNG MƯỢN (nhỏ, deterministic, zero fetch): Net-worth curve cho
portfolio_tab** — trụ Portfolio của họ có "net worth curves" mà tab danh
mục mình chỉ có bảng vị thế + sector exposure, CHƯA có đường cong GIÁ TRỊ
DANH MỤC THEO THỜI GIAN. Data đủ sẵn: positions = {ticker, quantity,
buy_price, buy_date} + kho giá parquet → curve(t) = Σ qty×close(t) từ
buy_date (mã chưa mua chưa tính) + đường VNINDEX chuẩn hóa cùng kỳ →
thấy ngay danh mục thắng/thua index. Display-only, plotly/line_chart.

**Để dành — PE band lịch sử** (trụ Equities): band phân vị P/E 3-5 năm
per ticker → "rẻ/đắt so với chính nó". VN làm được nhưng cần EPS QUÝ lịch
sử (vnstock finance có; fundamentals.parquet hiện chỉ giữ ratio MỚI NHẤT)
→ fetch nặng ~3 call/mã: scope VN30 + watchlist thì khả thi. Trigger: user
hỏi định giá lịch sử / mùa BCTC. Bỏ qua nhưng ghi nhận:
ticker_label_aliases.jsonl (map tên↔mã cho câu hỏi NLP); portfolio_eval
harness (validate output agent theo tiêu chí tự khai — hay cho harness
LLM thuần, mình dùng guard chain); heatmap (UI candy, Streamlit không hợp).

**Nghiên cứu SÂU agent-loop DojoAgents (15/07, user yêu cầu mổ tiếp thay
vì gạt ngang) — phát hiện chính: BÊN TRONG loop "cognitive" là cả bộ
xương DETERMINISTIC.** Giải phẫu (loop.py 1.522 dòng quanh strands-agents,
max_iterations default 100): (1) **ToolCallGuardrailController** tiền/hậu
kiểm MỌI tool call bằng CODE — block "cùng tool+args fail N lần" (bắt đổi
strategy), block tool read-only trả cùng kết quả N lần, ép dùng batch API
thay vì N call đơn; (2) **TaskHarness**: validate_progress(state) →
{complete, issues, next_steps} → chưa xong thì bơm recovery prompt "còn
thiếu X" cho chạy tiếp, CAP số lượt recovery; agent tự khai success
criteria qua tool submit (không keyword-parse); (3) **chống placeholder
deliverable**: LLM hay trả "file saved at …" thay vì nội dung thật →
`is_placeholder_task_output` bắt dict chỉ-có-meta/note "saved at"/thiếu
trường bắt buộc; (4) **ContextCompressor** 2 tầng thuần code trước khi
LLM-summarize (giữ 3 đầu + 8 cuối, tool result cũ >150 chars → tóm 1 dòng,
md5-dedup "[Duplicate omitted]"); (5) **SessionTokenState ledger** đếm
token per loop/session, persist atomic JSON, quyết định khi nào nén;
(6) **StreamingThinkScrubber** strip `<think>/<reasoning>` streaming.
⇒ Bài học meta XÁC NHẬN triết lý: framework LLM-loop nặng nhất cũng phải
chốt mọi chỗ LLM không đáng tin bằng code — guard chain của mình là hậu
kiểm TEXT, guardrails của họ là tiền/hậu kiểm TOOL CALLS, cùng một tư duy.

**3 món rút ra sau deep-dive — CẢ 3 ĐÃ LÀM cùng ngày (user "làm cả 3
món luôn"; tests `tests/test_llm_hardening.py` 14 test, vào `--fast`):**
1. **Retry-1-lượt-kèm-lỗi cho digest** (mirror harness recovery):
   `digest_call` nay nhận `feedback(raw)->str` — output KHÔNG ĐẠT → cho
   ĐÚNG NẤC ĐÓ 1 lượt tự sửa kèm lời phê cụ thể (`describe_digest_error`:
   thiếu khối JSON / JSON đứt tại vị trí X / không phải object) + echo
   output hỏng (800 ký tự đầu), TRƯỚC khi rơi nấc sau. Chỉ retry 1 LẦN
   cho CẢ cascade (trần +1 call); provider gắn đuôi "(retry)" trong
   digest để soi. `feedback=None` (--diag) → hành vi cũ nguyên vẹn.
2. **`strip_think_tags` (vnstock_sentiment, dùng chung)**: xóa khối
   `<think>/<thinking>/<reasoning>/<thought>` — CẢ 3 dạng: cặp thẻ đủ,
   "</think>" MỒ CÔI (provider nuốt thẻ mở — deepseek-r1 style, phần
   TRƯỚC thẻ đóng là reasoning), thẻ mở không đóng (cạn token — bỏ đuôi).
   Áp ở `chat_complete` + `_call_provider` (sentiment) + `digest_call`
   (mọi nấc, TRƯỚC khi accept/parse — think block chứa JSON NHÁP mà không
   strip là parse_digest vớ nhầm nháp). Chỉ khớp đúng 4 tên thẻ → "P/E
   <10"/"M&A" không bị đụng.
3. **`vnstock_llm_ledger.py` — sổ call/token per provider per ngày**:
   `record()` BEST-EFFORT TUYỆT ĐỐI (không bao giờ raise — sổ chết không
   được kéo chết call LLM), ghi atomic `_meta/llm_ledger.json`, giữ 30
   ngày, hiểu cả usage OpenAI-style lẫn Anthropic-style, tự nhận diện
   rate-limit (429/quota/too many requests). Wire ở sentiment
   (`_call_provider`, `chat_complete`) + digest (Claude/GPT/free — cả 3
   đường). CLI `--show [--day]`; doctor `check_llm_ledger` (off khi chưa
   có sổ; warn khi hôm nay có call bị rate-limit — kèm tên provider chạm
   trần — hoặc quá nửa call lỗi) → trả lời "vì sao ladder rơi bậc" bằng số.
Đã có tương đương, không làm: repeated-failure-block ≈ ladder đổi provider
mỗi lần fail; placeholder-detection ≈ schema clamp digest + anti-hallucination
sentinel brief; compression (prompt brief là data block, không phải hội
thoại tích lũy); turn-intent/multi-agent/planning (không có bề mặt).

**Khảo sát je-suis-tm/quant-trading (2026-07-15): KHÔNG dùng repo —
CẢ 3 MÓN ĐÃ TRIỂN KHAI cùng ngày (xem mục 🪃 bên dưới).** Bộ sưu tập ~15
chiến lược quant GIÁO DỤC nổi tiếng (Python single-file, mỗi script =
indicator + signal + backtest thô + plot). Không dùng trực tiếp vì:
(1) là script notebook-export đời 2018-2021 (`os.chdir('d:/')`,
`fix_yahoo_finance`, loop iterrows O(n²)) — không phải library;
(2) data US/FX/commodity — nhiều chiến lược cần thứ VN KHÔNG có:
intraday (Dual Thrust, London Breakout), bán khống (Pair trading —
Engle-Granger cointegration chỉ còn nửa chân long ở VN, bỏ), options
chain (Straddle, VIX Calculator); (3) hạ tầng backtest của repo (không
phí, không validation) — hệ mình đã VƯỢT xa (phí 0.4%, sign-flip MC,
walk-forward, Bonferroni, preset scorecard); (4) trùng lặp lớn:
MACD/RSI OB-OS/Bollinger/Awesome Oscillator/Shooting Star — screener +
mẫu nến 15/07 đã có đủ. Apache 2.0 — mượn ý tưởng, không copy code.

**3 món ĐÁNG MƯỢN (đều deterministic, preset scorecard chấm miễn phí):**
1. **Parabolic SAR làm SL trailing THÍCH ỨNG** (`Parabolic SAR
   backtest.py` — fit tự nhiên nhất): `trailing_stop_hint` hiện tại là
   5% CỐ ĐỊNH từ đỉnh; PSAR tăng tốc theo trend (AF 0.02 step 0.02 cap
   0.2, họ ghi chú equity nên dùng 0.01) — mức thoát bám đà thay vì
   khoảng cách cứng. Áp: cột "SL trailing" lấy max(SL gốc, đỉnh×0.95,
   PSAR) hoặc hiện PSAR cạnh — display-only, KHÔNG đổi convention
   reconciler (mirror nguyên tắc 15/07). ~40 dòng numpy (bản họ loop
   pandas chậm; lưu ý SAR bị clamp bởi High/Low của 2 bar trước).
2. **Double bottom W neo Bollinger** (`Bollinger Bands Pattern
   Recognition backtest.py`) → preset screener "double_bottom": pattern
   recognition SỐ HỌC trên CẤU TRÚC GIÁ nhiều tuần (đáy k ≈ đáy m,
   đỉnh giữa j chạm mid-band, kích hoạt vượt upper band, cửa sổ 75
   phiên) — trục mới bổ sung mẫu nến 1-5 phiên; mean-reversion hợp
   baseline Bear 15/07. BẪY KHI PORT: alpha/beta của họ là ngưỡng TUYỆT
   ĐỐI 0.0001 (giá FX ~1.0) — scale-dependent, phải đổi sang % giá
   (bài học tolerance mẫu nến); loop O(n·75) → viết lại bằng cực trị
   cục bộ.
3. **Heikin-Ashi transform** (~20 dòng): HAc=(O+H+L+C)/4,
   HAo=(HAo₋₁+HAc₋₁)/2 — bộ lọc nhiễu trend; preset "ha_trend" (chuỗi
   nến HA cùng màu không râu ngược = trend sạch) và/hoặc 1 dòng ngữ
   cảnh VNINDEX cạnh CHOP. Nice-to-have, xếp thứ 3.

Bỏ qua nhưng ghi nhận: **Oil Money project** (hồi quy petrocurrency ~
giá dầu → trade lệch) — concept "độ nhạy hàng hóa" cho GAS/PLX/PVD/HPG
hay nhưng THIẾU nguồn giá dầu/quặng free (đúng gap đã ghi ở TODO 1c
public-apis: dầu toàn API trả phí) → để dành cùng chỗ, làm khi có
nguồn; Dual Thrust mức breakout từ EOD (open + K×range) có thể thành
display cạnh pivots — marginal; Monte Carlo GBM forecast (đã có MC
validation nghiêm hơn); Smart Farmers/Ore Money (econometrics
USDA/quặng — không data VN).

### 🪃 PSAR trailing + Double bottom W + Heikin-Ashi (DONE 2026-07-15 — 3 món quant-trading, user "làm cả 3 đi")

Cả 3 deterministic thuần trong `vnstock_indicators.py` (mượn Ý TƯỞNG,
không copy code — Apache 2.0); tests `tests/test_psar_db_ha.py` (16,
hermetic) + 1 test build_prompt trong test_brief — vào `--fast`.

**Món 1 — `parabolic_sar(high, low, close)` + `vnstock_strategy.
psar_stop_hint`**: PSAR Wilder chuẩn (AF 0.01 equity theo ghi chú repo
gốc, step 0.01 cap 0.2; SAR clamp bởi High/Low 2 bar trước; ≥5 bar; data
rác/high<low/unit-break → None). `psar_stop_hint(sl, h, l, c)` — CHỈ trả
mức khi PSAR đang uptrend VÀ > SL gốc +0.5% (cùng luật trailing 5%).
Cột "SL trailing" (market_tab `_mtm`) nay = **max(trailing 5% cố định,
PSAR)** — mức khóa lời chặt hơn thắng; vẫn display-only, reconciler chấm
SL gốc (nguyên tắc 15/07 giữ nguyên).

**Món 2 — `double_bottom_w(close, low)`** → preset screener
`double_bottom`: 2 đáy hình W neo Bollinger(20,2) viết lại bằng CỰC TRỊ
CỤC BỘ (thay loop O(n·75) gốc): 2 đáy cuối cách ≥5 bar + giá lệch ≤3%
(ngưỡng TƯƠNG ĐỐI — bẫy alpha=0.0001 tuyệt đối của repo gốc đã né) +
đáy 1 chạm/thủng lower band NHƯNG đáy 2 giữ TRÊN band (đà giảm yếu đi —
luật W-bottom kinh điển) + neckline cao hơn đáy ≥3% + close vượt
neckline trong ≤3 bar cuối (breakout cũ → không phát lại). Trả
{neckline, bottom, bars_since_bottom}; screener ghi `double_bottom` +
`db_neckline`. Mẫu HIẾM by design — n nhỏ trên scorecard là bình thường.

**Món 3 — `heikin_ashi` + `ha_trend_streak`** → preset `ha_trend` +
dòng brief: HAc=(O+H+L+C)/4, HAo đệ quy; streak = số nến HA CÙNG MÀU
liên tiếp từ bar cuối, mỗi nến KHÔNG râu ngược (tol 0.15% giá) = trend
sạch; trả ±N. Preset `ha_trend`: streak ≥ 3 (sort desc). Brief: dòng
"Heikin-Ashi: N nến xanh/đỏ sạch liên tiếp" trong block VNINDEX kỹ
thuật khi |streak| ≥ 2, cùng luật SKIP bar intraday như mẫu nến;
display-only, không guard mới (data block prompt-side).

Wiring chung: 2 preset mới tự vào screener_history → preset scorecard
chấm; `_MEANREV_PRESETS` += double_bottom, `_TREND_PRESETS` += ha_trend.
Guard unit-break ×200 nay là helper chung `_has_unit_break` trong
vnstock_indicators (PSAR/W/HA đều dùng — bẫy per-bar normalization).

**Khảo sát nautechsystems/nautilus_trader (2026-07-14): KHÔNG dùng
framework — CẢ 3 MÓN ĐÃ TRIỂN KHAI cùng ngày (xem mục 💸 Phí + ⚖️ Sizing
bên dưới).** Engine
trading production-grade lớn nhất từng khảo sát (~2.530 file Rust +
Cython/Python control plane; backtest nanosecond, matching engine L1-L3,
live execution đa sàn). Không dùng vì: (1) không có adapter HOSE/HNX
(toàn crypto CEX/DEX, IB, Betfair, databento); (2) mình KHÔNG đặt lệnh
tự động — dashboard là hệ hỗ trợ quyết định, kéo cả engine live-execution
ngược mục đích; (3) build Rust+Cython nặng, LGPL (mượn Ý TƯỞNG, không
copy code). Điều đáng nể để đối chiếu: fill/fee model của họ tách rời
matching engine, deterministic seed được (cùng triết lý seed cố định của
mình ở Monte Carlo validation).

**3 món ĐÁNG MƯỢN (đều deterministic thuần, vài chục dòng mỗi món):**
1. **CHI PHÍ GIAO DỊCH vào backtest (FeeModel)** — giá trị nhất, chỗ
   mỏng THẬT: `_simulate_trade` (vnstock_strategy) tính pnl GROSS 0 phí.
   VN thực tế: phí CTCK ~0.15%/chiều + thuế bán 0.1% → round-trip ~0.4%.
   Chiến lược edge mỏng (avg pnl +0.3%/lệnh) qua được validation 🎲 nhưng
   LỖ THẬT sau phí. Làm: hằng số `_COST_ROUNDTRIP_PCT` (~0.4, tunable)
   trừ vào pnl mỗi lệnh backtest; cân nhắc trừ luôn ở grading
   `reconcile_recommendations` (rec thật cũng chịu phí thật) để decay
   gap so táo-với-táo. LƯU Ý khi làm: expectancy/validation sẽ khó đạt
   hơn — đó là ĐÚNG, nhưng chiến lược active hiện tại có thể rớt gate
   ngay lần train sau (chấp nhận, cold-start bản mới).
2. **Adaptive high/low ordering khi bar chứa CẢ TP lẫn SL**
   (`bar_adaptive_high_low_ordering`, matching_engine/engine.rs:1712):
   họ tách bar thành 4 tick O→H→L→C, và extreme nào GẦN OPEN hơn thì xử
   TRƯỚC (|high−open| < |low−open| → high trước). Mình hiện luôn cho SL
   thắng trong cùng bar (pessimistic cứng, cả `_simulate_trade` lẫn
   `reconcile_recommendations`). Áp heuristic này → backtest + chấm rec
   thật chính xác hơn, vẫn deterministic. (Giữ SL-first làm fallback khi
   thiếu open.)
3. **Position sizing fixed-risk (risk/sizing.pyx FixedRiskSizer)**:
   qty = (NAV × risk%) / (entry − SL), trừ phí. Rec hiện chỉ có
   entry/TP/SL, KHÔNG có size → user tự đoán khối lượng. Làm: 1 dòng
   "size gợi ý (risk 1% NAV)" display-only trong rec/brief, NAV + risk%
   đặt trong config. Zero LLM, guard không cần đổi.
Bỏ qua nhưng ghi nhận: bộ 35 thống kê danh mục (crates/analysis) —
mình đã có expectancy/sharpe/win-rate/max-dd; đáng thêm nhất nếu cần là
`profit_factor` (Σlãi/|Σlỗ|) và `ulcer_index` (RMS drawdown — đo cả độ
sâu lẫn độ dài); indicators (RSI/MACD/ATR…) — đã tự có; probabilistic
FillModel (prob_slippage) — ngược triết lý deterministic, phí cố định
món 1 là đủ.

### 💸 Phí giao dịch + thứ tự TP/SL trong bar + ⚖️ Sizing fixed-risk (DONE 2026-07-14 — 3 món nautilus_trader, user "làm cả 3 món")

Cả 3 deterministic thuần, zero LLM/fetch; tests `tests/test_costs_sizing.py`
(13, hermetic) đã vào `--fast`.

**FIX benchmark đóng băng (15/07, user bắt được khi verify)**: `_do_tune`/
`_do_revise` trước đây lấy benchmark từ `mem.latest_backtest` (row DB cũ =
GROSS) trong khi mọi ứng viên mới là NET sau phí → chấp sẵn 0.4, không ứng
viên nào thắng nổi → tune/revise đóng băng + active không bao giờ có row
backtest mới (nên không có 🧪 validation). Nay cả 2 hàm RE-BACKTEST chính
active (code+params hiện tại, cùng cost-basis) làm benchmark VÀ lưu row đó
→ so net-vs-net công bằng, panel/CLI luôn thấy validation của active.
Verify thật trên máy user 15/07: family-05f9d495 lộ nguyên hình +0.365
gross → **−0.777 net, p=0.986, 0% fold dương** — đúng loại chiến lược
"lãi trên giấy, lỗ sau phí" mà Món 1 sinh ra để tóm. Kéo theo **rule 2b**
trong `_should_revise`: expectancy net ≤ 0 → REVISE NGAY (không tune chờ
hết tuần) — các agent viết lại core cạnh tranh dưới luật net; benchmark
−0.777 là bar thấp nên thay máu nhanh, ứng viên vẫn phải qua gate
validation 🧪 mới được promote.

**Món 1 — phí round-trip vào backtest** (`vnstock_strategy._cost_roundtrip_pct`):
`_simulate_trade` trừ `_COST_ROUNDTRIP_PCT_DEFAULT` = **0.4%** (phí CTCK
~0.15%/chiều + thuế bán 0.1%) vào pnl MỌI lệnh backtest (tp/sl/expire;
hold/no_data không trừ). Env `VNSTOCK_COST_ROUNDTRIP_PCT` tune (0 = về
gross), đọc TẠI CALL-TIME. ⇒ expectancy/sharpe/validation 🎲 nay đều NET —
chiến lược edge mỏng (<0.4%/lệnh) sẽ trượt gate ĐÚNG NHƯ PHẢI THẾ; chiến
lược active hiện tại có thể rớt ở lần train sau (chấp nhận → cold-start).
**PnL rec THẬT (close_recommendation) giữ GROSS** — không đổi convention DB
giữa chừng (trộn gross/net làm hỏng recommendation_performance); hệ quả:
decay gap (backtest net vs live gross) hơi bảo thủ (live nhìn đẹp hơn ~0.4đ%)
— đã cân nhắc, chấp nhận.

**Món 2 — bar chứa CẢ TP lẫn SL** (`_bar_high_first`, mirror
`bar_adaptive_high_low_ordering` của nautilus matching engine): cực trị
GẦN OPEN hơn coi là chạm TRƯỚC (|high−open| < |low−open| → high trước).
Trước đây SL LUÔN thắng trong cùng bar (pessimistic cứng). Áp CẢ HAI chỗ
chấm lệnh: `_simulate_trade` (backtest, cả buy lẫn sell symmetric) và
`vnstock_train._grade_rec` (grading rec thật — tách từ inline loop của
`reconcile_recommendations` thành helper thuần để test). Thiếu/hỏng open
→ None → fallback SL thắng (giữ nếp pessimistic cũ).

**Món 3 — KL gợi ý fixed-risk** (`suggest_position_size`, mirror
`FixedRiskSizer` của nautilus/risk/sizing): qty = (NAV × risk%) /
((entry−SL)×1000 + phí/cp), tròn XUỐNG lô 100, **cap giá trị lệnh ≤
`max_position_pct` (25%) × NAV** (SL sát entry không thể dồn cả NAV vào 1
mã), qty < 1 lô → None. Config user: `_meta/sizing_config.json`
{nav_million, risk_pct=1.0, max_position_pct=25} — ghi atomic qua
`save_sizing_config` (NAV=0 → None = TẮT). **DISPLAY-ONLY, không ghi DB,
chưa cấu hình NAV thì mọi chỗ im lặng** (mirror best-effort): (a) bảng
Open recommendations dashboard thêm cột "KL gợi ý" + expander "⚖️ Cấu
hình khối lượng gợi ý" (3 number_input + nút lưu); (b)
`_recommendation_block` (brief) gắn "· KL gợi ý ~N cp (rủi ro X% NAV)"
vào từng dòng rec — data block nên vào prompt như entry/TP/SL hiện có,
không cần guard mới. Giá theo NGHÌN đồng (như mọi giá trong hệ), NAV theo
TRIỆU đồng.

**Khảo sát TauricResearch/TradingAgents (2026-07-14): KHÔNG dùng trực
tiếp — ý tưởng reflection + debate ĐÃ TRIỂN KHAI cùng ngày (xem mục
🧠 Reflection + 🗣 Debate dưới P6).** Framework nghiên cứu
multi-agent (~16K dòng, LangGraph): 4 analyst → debate Bull/Bear → trader →
debate rủi ro 3 phe → BUY/HOLD/SELL per-ticker. Không dùng vì: (1) data
100% Mỹ (Alpha Vantage/yfinance/Reddit/Polymarket — không HOSE/HNX);
(2) ~10-20 call LLM/quyết định/mã — ngược triết lý deterministic-trước
+ free-tier của hệ này (guard pin số đã chứng minh đúng hướng ở vụ digest
14/07); (3) dependency LangGraph nặng. **ĐÁNG MƯỢN (khi muốn nâng chất
lượng học từ lịch sử)**: `reflection.py` — quyết định đã BIẾT outcome →
1 call ngắn ra "2-4 câu bài học" (đúng hướng? luận điểm nào đổ? 1 bài học)
lưu log, tái bơm vào prompt sau. Nguyên liệu mình có đủ (reconciler biết
win/loss, scorecard biết band đúng/sai, brief_memory có few-shot) — chỉ
thiếu bước rút-bài-học-thành-chữ; chi phí 1 call/rec đóng. Trigger: user
thấy brief lặp lỗi nhận định cũ / muốn brief "khôn lên" theo thời gian.
Mẹo nhỏ đáng nhớ: delimiter log bằng HTML comment `<!-- ENTRY_END -->`
(LLM prose không bao giờ sinh ra). Bull/bear debate cho brief allocation
(tháng, 2-3 call) = để dành mức thấp; rating 5-tier = đã có stance -2..+2.

**Khảo sát emilkowalski/skills (2026-07-14): BỎ QUA cho dashboard — lệch
stack, ĐỂ DÀNH nếu làm frontend web riêng.** 5 skill Claude Code dạy taste
UI/animation web (easing/duration/spring, review + audit animation — tác
giả Vercel/Linear, chất lượng cao) nhưng toàn bộ nhắm codebase React/CSS
tự viết animation. Dashboard là Streamlit: không có bề mặt animation
(grep: đúng 2 chỗ `animation:` — chấm pulse analysis_tab), khối JS duy
nhất là 4-panel chart sync (vùng hard-won invariants, không đụng). Chính
luật #1 của repo ("công cụ dùng hằng ngày tần suất cao → No animation.
Ever.") phán dashboard cá nhân không nên thêm animation. KHI NÀO DÙNG:
làm frontend React/Next riêng → `npx skills@latest add emilkowalski/skills`
(đáng nhất: review-animations + apple-design).

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
