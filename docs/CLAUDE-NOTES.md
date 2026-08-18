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
32. **Vá close 23:18 20/07 (test `test_close_2007_review.py`, user "sửa cả
    2 bug")**: (a) guard 13 thêm dạng NHÃN-TRƯỚC-%-SAU — "cao hơn TB sáng
    5 phiên (+42%) nhưng cao hơn TB cả ngày (+53%)" trượt cả
    `_MORNING_CMP_RE` (đòi mở đầu verb+% / %+so) lẫn guard 22 Form 2 (cố
    ý bỏ baseline "sáng"), lại vô lý nội tại (TB sáng > TB cả ngày là bất
    khả — sáng là tập con cả ngày). `_MORNING_LABEL_CMP_RE` bắt CHUỖI 1-3
    mệnh đề "verb + TB/trung bình … (±N%)" nối nhưng/và → thay TRỌN chuỗi
    bằng canonical TB5/TB20 khi có ≥1 baseline "sáng"; chủ ngữ GTGD SÁNG
    ("sáng" đứng TRƯỚC chuỗi trên dòng) → so sáng-với-sáng hợp lệ, không
    đụng; canonical không chứa "sáng" → idempotent. (Addendum 21/07 —
    review code-reviewer: thêm ANCHOR CHỦ NGỮ `_GTGD_SUBJECT_RE` — câu
    chứa chuỗi phải nói về GTGD/giá trị giao dịch/thanh khoản/khớp lệnh,
    soi trong phạm vi CÂU (sau ". "/"; ") — kẻo câu khối ngoại/tự doanh
    cùng bề mặt "cao hơn TB sáng … (+N%)" bị thay bằng số GTGD.) (b) **`_select_sr_levels`
    thêm TRẦN `_SR_MAX_MOVE_PCT` (7%) ngay từ NGUỒN** — user chốt "soi mức
    hỗ trợ gần và hợp lý hơn": thị trường thủng đáy 60 phiên → ứng viên
    dưới giá chỉ còn S1 sát giá + đáy 52w → "thủng S1=1,733.25 → mục tiêu
    S2=1,457.31" (−16%!) và enforce_sr_direction tầng 3 NHƯỜNG vì canon
    vai 2 hợp lệ. Nay mức cách giá >7% không được ĐÓNG VAI S/R (vẫn hiện
    trong data block dưới nhãn thật đáy 52w/tháng) → canon vai 2 rỗng →
    tầng 3 tự kéo mục tiêu LLM viết về mức known kế tiếp trong tầm (vd
    đáy tháng) / cắt vế khi không còn mức nào. Pivot tính lại mỗi brief
    (collect_context) → hiệu lực ngay brief kế tiếp, không cần recompute gì.

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
   đóng cửa. (20/07: thêm TRẦN 7% NGAY TỪ NGUỒN trong `_select_sr_levels`
   — mức cách giá >7% không còn được chào mời làm vai S/R trong prompt;
   xem guard #32b.) Code đã chốt 4 tầng trong `enforce_sr_direction` (đúng phía →
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
4 task được đăng ký (task 4 thêm 20/07 — máy đã setup trước đó phải chạy
LẠI script để có nó): **VnStock Daily Pipeline** 18:00 T2-T6 (`run.py all` =
13 bước: sync EOD → validate → screener → news → … → audit → **train** →
reflection → doctor — trọn quy trình tối, sau giờ đóng cửa) · **VnStock
Rates Weekly** T7 09:00 (`run.py rates-weekly` — báo cáo tuần lãi suất →
Telegram, zero LLM) · **VnStock Weekly Corp Actions** CN 09:00
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
   **CÒN THEO DÕI: tối T3 21/07 18:00** (dời từ 20/07: chạy lại setup
   script sau 18:00 → task bị THAY MỚI, lịch hôm đó trôi + bộ đếm reset
   sentinel 1999/267011 — lịch sử 3 lần 0xC000013A cũng mất theo; nút
   dashboard chạy tay KHÔNG hiện trong Get-ScheduledTaskInfo) — máy bật,
   không đụng, kỳ vọng lần đầu LastTaskResult=0, lần đầu chạy đủ 13 BƯỚC
   có train. Sáng T4 kiểm `Get-ScheduledTaskInfo 'VnStock Daily
   Pipeline'`; xác nhận train qua dấu vết: doctor_status.json +
   brief_memory.db LastWriteTime tối đó + panel Chiến lược "p=… · N ứng
   viên" (câu "tắt desktop lúc mấy giờ" user BỎ 20/07 — giữ giờ 18:00,
   chỉ đổi nếu tái ngắt). Desktop đã seed tay
   17/07 + bù giá xong (kho bar 20/07 tươi, VCI khỏe lại); 20/07 đăng ký
   đủ 4 task (system Python C:\Python314 — vnstock 3.5.1, KHOAN nâng khi
   hệ đang khỏe; nâng thì chạy lại test --fast ngay);
   (b) ✅ XONG 17/07 — FRED key
   đã vào .env laptop, `--diag` ra us10y 4.55/fed_funds 3.63 @07-15, cả 2
   máy nay 13/13 chỉ số auto; (c) `python vnstock_preset_score.py --show`
   ~24/07 TRÊN DESKTOP (item
   6b — screener_history do pipeline desktop nuôi, laptop thiếu snapshot);
   (d) **Rates Weekly test-fire 20/07 exit 0** — user CHƯA xác nhận
   Telegram nhận tin: nếu sáng T7 25/07 không thấy báo cáo tuần trên
   Telegram → chạy tay `python run.py rates-weekly` xem console (nghi
   cache trống / thiếu TELEGRAM token trong .env desktop).
2. **Lần train kế tiếp** (từ 20/07 train TỰ CHẠY mỗi tối trong pipeline —
   lần kế = ngay tối 20/07): panel Chiến lược phải hiện "p=… · N ứng viên"
   (hiệu chỉnh chọn-lọc Bonferroni mới 15/07 — p_adj = p × N, chỉ siết
   không nới); validation trong DB mang `p_value_adj` + `n_trials`;
   metrics row mang profit_factor/recovery_factor; log train KHÔNG spam
   ScriptRunContext (mục 6e).
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
   d. ✅ **Net-worth curve — DONE 2026-07-20** (user "làm đi" sau khảo sát
      lại DojoAgents; chi tiết + checklist verify ở mục "### 📈 Net-worth
      curve" dưới khối Khảo sát LẠI DojoAgents). PE band lịch sử vẫn để
      dành (cần EPS quý, scope VN30).
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

12. **Đợt 20-21/07 (session DojoAgents — nhánh `claude/dojoagents-dashboard-
    integration-bid9gp`: NAV curve + fix pandas 3 + fix "giá đóng băng" tab
    Danh mục + 4 đánh bóng + guard #32; suite fast 791) — VERIFY CÒN LẠI:**
    a. **Close brief kế tiếp với DATA MỚI (21/07, sau khi pull trên máy
       chạy brief)**: (i) câu GTGD "Tổng kết phiên" giữ khung chuẩn
       TB5/TB20 — KHÔNG còn "TB sáng"/"TB cả ngày" (guard #32a đã ăn trên
       bản 01:22 21/07: ra "+28% vs TB20 phiên"); (ii) MỌI mục tiêu S/R
       trong tầm ≤7% từ close (trần nguồn #32b đã ăn: S2 1,457.31 → model
       tự chọn mức tròn 1,700 = −2.5%, HỢP LỆ by design — số tròn được
       phép làm mục tiêu xấp xỉ, đã ép đúng phía/vai/tầm); lộ dạng mới →
       mở rộng `tests/test_close_2007_review.py` theo quy trình cũ.
    b. **Reconcile tối 21/07**: 5 rec BUY (GMD/DCL/BVB/ASM/APH) đều "ngày
       5/5" từ 20/07 — phải được đóng ĐỦ (không zombie); phiên sập −2.46%
       nên khả năng SL/expire hàng loạt → soi log "[reconcile]" + panel
       Chiến lược (5 outcome mới nuôi luôn decay/reflection).
    c. **NAV curve — passive, tự đến**: mỗi phiên sync thêm 1 điểm;
       vol/Sharpe/Calmar tự mở khi đủ ≥10 phiên (~đầu tháng 8); nhãn tick
       trục X hết lặp từ ~4-5 điểm (dtick 1 ngày chỉ ép khi ≤10 phiên).
       Đối chiếu nhanh khi rảnh: `python vnstock_networth.py` in cùng số
       với mục 📈 tab Danh mục.
    d. **3 điểm nhỏ close 01:22 21/07 — GHI SỔ CHƯA VÁ (nói "làm đi" kèm
       chọn món)**: (i) caveat BUY-vs-bias in 2 LẦN khi body có mục 💡
       (guard 27 chèn) VÀ telegram append khối 📋 (fix 15/07 chèn bản
       riêng) — mỗi khối lệnh 1 cảnh báo là hợp lý UX nhưng rườm; dedupe
       = `_open_recs_block` bỏ caveat khi TOÀN VĂN đã chứa
       `_BUY_BIAS_CAVEAT`; (ii) mục 📌 Danh mục: câu LÝ DO của LLM gán
       SAI HỌ — "EIB → GIẢM TỶ TRỌNG (họ VIN yếu nhất)" trong khi EIB =
       Họ M/Ngân hàng (số vốn/hiện/lỗ vẫn ĐÚNG, chỉ sai dẫn chứng); nếu
       LẶP → thêm guard check ticker↔`custom_sector_for` trong câu lý do
       mục 📌; (iii) chất lượng mapping tin CafeF máy móc — 4/6 tin
       "ngành chứng khoán hưởng lợi…", "dư nợ margin KỶ LỤC" ngay ngày
       sập −2.46% đọc thành 🟢 — hôm nay CHẠM ngưỡng TODO 1b (≥2-3 dòng
       gượng/ngày); theo dõi vài hôm, còn lặp → nâng model chấm tin theo
       3 hướng đã ghi ở TODO 1b (prompt TRUNG_LẬP / đổi model free mạnh
       hơn / route key trả phí — ≤8 tin/ngày nên chi phí nhỏ).
    e. **Header "⚠️ data phiên gần nhất" trên bản 01:22 là ĐÚNG THIẾT KẾ**
       (chạy sau nửa đêm, kho mới tới 20/07) — không phải bug, đừng vá.
    f. **Nhánh session SẴN SÀNG MERGE MAIN** — user nói "tạo PR" là mở
       (theo nếp: chạy `python run.py test --fast` trên máy user trước,
       kỳ vọng 791 passed).
13. **Đợt 21/07 (session review — nhánh `claude/session-6nhlpt`):
    code-reviewer rà 4 commit 20/07, verdict Warning (1 HIGH · 3 MEDIUM ·
    4 LOW) → user "fix toàn bộ". Suite fast nay 795.**
    a. **HIGH — neo đơn vị `resolve_current_price` trượt mốc khi giá trôi**
       (tab Danh mục): (i) quote live trước NEO THẲNG vào buy_price tại
       ngày HÔM NAY — giá trôi >2× kể từ ngày mua → residual bung
       `_ANCHOR_TOL` → factor kẹt 1.0 → "24.5 VND" cho cổ phiếu 24,500;
       nay quote neo qua close kho cùng/kề phiên (đã về đơn vị buy_price),
       không có kho mới fallback neo buy_price như cũ; (ii) cửa sổ đọc kho
       cứng 400 ngày mất close quanh ngày mua khi vị thế già hơn cửa sổ →
       neo nhầm bar đầu cửa sổ; nay span tính từ buy_date qua
       `vnstock_networth._span_days` (helper mới DÙNG CHUNG với
       `load_networth`). Test: 2 ca drift mới trong test_portfolio_prices.
    b. **Tripwire ⚠ tab Danh mục: tách hàm thuần `_unit_suspect` + nới
       ngưỡng** — ±7.5% cũ dán nhãn "gần như chắc chắn sai" cả data hợp lệ
       HNX ±10% / UPCoM ±15% / chào sàn ±40% / mua đáy đóng trần; nay
       −90% / +300% (vùng chỉ còn lệch đơn vị 1000×: −99.9% / +99,900%),
       caption đổi thành "nghi lệch đơn vị giá 1000×". `_nav_xaxis` cũng
       tách thuần → nhánh dtick ≤10 phiên có test.
    c. **Cache path giá**: `render_portfolio_tab` bọc `st.cache_data`
       (resolver TTL 60s, `load_networth` TTL 300s) — resolver đọc TOÀN BỘ
       lịch sử parquet cho TỪNG vị thế mỗi rerun Streamlit, trước không có
       cache nào; best-effort (streamlit thiếu cache_data → gọi thẳng).
    d. **Bỏ fallback mtime trong `_quote_price_date`**: quote thiếu field
       `time` (legacy/corrupt — writer WSS luôn ghi) bị BỎ thay vì lấy
       mtime file làm ngày data (Dropbox re-sync làm mới mtime → quote cũ
       đội lốt hôm nay, thắng bar kho mới).
    e. **Xoá `_warehouse_last_close`** — dead code sau fix 20/07 (hết
       caller production) nhưng vẫn giữ nguyên bug iloc[-1]-file-đầu và
       được test xanh → dễ dụ tái sử dụng; ý "giữ làm primitive" HỦY.
    f. **Brief**: guard #32a thêm anchor chủ ngữ GTGD (xem addendum #32);
       `_SR_MAX_MOVE_PCT` 7.0 (percent) → 0.07 (fraction — CÙNG đơn vị
       `_SR_MIN_DIST_PCT`/`_SR_MIN_GAP_PCT`, định nghĩa dời về cùng block
       cạnh `_select_sr_levels`) — hết `/100.0` lệch pha giữa 2 chỗ dùng.
    g. **Baseline GTGD TB5/TB20 gate theo COVERAGE (user "làm luôn" sau
       brief 16:18 ra "+0% vs TB20" trong khi bản 01:22 ra "+28%")**: map
       `gtgd_by_date` cộng dồn 22 bar cuối CỦA TỪNG MÃ → ngày rơi ngoài
       cửa sổ của mã sync trễ bị HỤT TỔNG hệ thống, baseline lệch theo
       trạng thái kho lúc chạy screener. Fix: `_gtgd_baselines` (vnstock_
       brief, tách thuần + test) loại ngày có count < 70% median(count)
       khỏi prev/avg5/avg20 (count thấp = thiếu DATA, không phải phiên
       vắng — phiên trầm vẫn có ~hầu hết mã in ≥1 lệnh); map cũ không có
       count giữ hành vi cũ. Soi trên máy thật: `python vnstock_diagnose.py
       --gtgd` (in bảng total/count per ngày + baseline trước/sau gate —
       CHẠY SAU MỖI LẦN NGHI % GTGD SAI để phân xử data vs guard). LƯU Ý:
       chưa phân xử được bản nào trong 2 bản 21/07 đúng — cần chạy audit
       trên kho thật; gate làm cả 2 lần chạy hội tụ về số đúng hơn.
    h. **Nâng model chấm tin (TODO 1b kích hoạt — 2 ngày liên tiếp ≥3 dòng
       mapping gượng: "kim cương khó mua lại → PNJ hưởng lợi", "margin kỷ
       lục = 🟢 ngày sập", "Canada bị thuế → VN gặp áp lực" NGƯỢC logic
       cạnh tranh)**: làm CẢ 2 hướng — (i) prompt `_ANALYZE_SYSTEM` thêm 4
       luật trung lập: cấm suy diễn ngược nội dung bài, tin hai-chiều
       (margin/cho vay kỷ lục) → TRUNG_LẬP, thuế lên nước KHÁC xét đúng
       logic cạnh tranh, nới "TUYỆT ĐỐI KHÔNG 'không tác động'" bằng
       "KHÔNG ÉP CHIỀU — kênh yếu → TRUNG_LẬP thận trọng"; (ii) route TRẢ
       PHÍ TRƯỚC: `vnstock_sentiment.anthropic_complete` (Messages API raw
       requests khớp pattern ClaudeAgent; KHÔNG gửi temperature — Opus
       4.7+ bỏ sampling params trả 400; model mặc định = ClaudeAgent
       claude-haiku-4-5-20251001, override `VNSTOCK_NEWS_ANALYZE_MODEL`
       vd claude-opus-4-8) → lỗi/thiếu key fallback ladder free y cũ.
       Kill-switch nếp repo: `VNSTOCK_NEWS_ANALYZE_PAID=0`. ≤8 call/ngày
       (`_MAX_ANALYZE_DEFAULT`) → chi phí ~vài trăm đồng/ngày. SAU KHI
       PULL trên máy thật: `python vnstock_news_feeds.py --reanalyze` để
       chấm lại 8 tin mới nhất bằng prompt + model mới; theo dõi 2-3 hôm,
       còn gượng → nâng `VNSTOCK_NEWS_ANALYZE_MODEL=claude-opus-4-8`.
    i. **KHUNG GTGD cả ngày thống nhất (audit --gtgd trên máy thật 21/07
       phân xử xong: "+0%" ĐÚNG trong khung EOD tự nhất quán — coverage
       count 20 phiên đều 765-873, gate 13g không đổi gì; thủ phạm THẬT là
       TRỘN KHUNG)**: brief in "GTGD 20,453.9 tỷ (+0% vs TB20)" vì SỐ do
       `enforce_gtgd_total` pin theo capture WSS 9h-15h (đủ sàn) còn % do
       `enforce_gtgd_baseline_pct`/prompt tính trên khung EOD Σ giá×KLGD
       (14,878.9/TB20 14,869.6 — subset mã đã sync); hai khung lệch hệ
       thống ~20-40% → "+28%" bản 01:22 cùng họ (22,821 WSS / ~17.8k EOD
       = 1.28). Fix: (i) baseline WSS cả ngày MỚI `_full_wss_baselines`
       (cửa sổ 9h-15h của session_stats_history, mirror TB sáng; ngày
       capture chết giữa phiên full ≤ sáng×1.05 bị loại cả today lẫn
       baseline) → `ctx["full_wss_gtgd"]`; (ii) resolver `_gtgd_close_
       frame(ctx)` → (F, cmp, frame) MỘT KHUNG duy nhất — ưu tiên
       WSS-với-WSS, WSS thiếu lịch sử + EOD đủ bộ → TRỌN khung EOD (số
       lẫn %), cấm số khung này gắn % khung kia — DÙNG CHUNG bởi
       build_prompt + enforce_gtgd_total + enforce_gtgd_compare_frame +
       enforce_gtgd_baseline_pct (parity by construction, mirror
       apply_brief_guards). Side-effect tốt: enforce_gtgd_total hết pin
       số capture nửa phiên (trước nhận full > 0 vô điều kiện). Ctx chỉ
       có EOD (test cũ/máy không WSS) → hành vi y nguyên. VERIFY close
       kế tiếp: số GTGD và % phải cùng ra từ 1 khung — WSS có lịch sử →
       "GTGD ~20,xxx tỷ" + % vs baseline WSS ~19-20k (KHÔNG còn +0% giả).
    j. **Model chấm tin mặc định → `claude-opus-4-8`** (user chốt "đổi
       model tốt hơn" 21/07 — batch Haiku vẫn còn ca borderline "PNJ hưởng
       lợi từ động thái của chính mình"; chấm tin là tác vụ nuance, 8
       call/ngày × ~3K token → ~vài chục nghìn đồng/tháng). Hạ cấp/đổi:
       `VNSTOCK_NEWS_ANALYZE_MODEL`. Model BRIEF (ClaudeAgent Haiku) GIỮ
       NGUYÊN — brief có 30+ guard deterministic chốt số, nâng model chỉ
       cải thiện văn phong, đổi = đổi giọng brief user đang quen (để user
       tự quyết, 1 dòng: `ClaudeAgent(model="claude-opus-4-8")`).

### 📅 AUDIT LỊCH ĐỊNH KỲ sau ~10 đợt tích hợp (17/07 — chốt 20/07, 2/3 DONE)

Đã rà `run.py all` + 4 task Scheduler + nút dashboard. **Phần ỔN**:
mọi nguồn data mới đều qua bước `macro` (HNX/SBV tuần/SBV ngày/policy/FRED/
NSO/FX) + gold/allocation/scorecard/reflection/foreign-flow/doctor là bước
pipeline; screener tối nuôi preset history; events/overview tự refresh khi
tạo brief; fundamentals task T2; nút "Cập nhật giá" đúng scope (chỉ giá).

**3 lỗ hổng cadence — trạng thái sau 20/07 (user "làm... tự động đi"):**
1. `run.py telegram morning` + `close` — VẪN TREO (user chưa chốt giờ,
   brief Telegram vẫn chạy tay). Đề xuất giữ nguyên: task 11:40 T2-T6
   (morning) + 19:00 T2-T6 (close, sau pipeline). Nhắc khi user than
   quên chạy brief.
2. ✅ **DONE 20/07**: task thứ 4 "**VnStock Rates Weekly**" T7 09:00
   (`run.py rates-weekly`, MaxMinutes 10, zero LLM — render từ cache
   pipeline đêm đã nuôi cả tuần) vào `setup_scheduled_tasks.ps1`.
   **User ĐÃ đăng ký trên desktop 20/07** (script chạy Run-as-Admin, đủ
   4 task). Verify: bắn thử `Start-ScheduledTask -TaskName 'VnStock
   Rates Weekly'` hoặc chờ sáng T7 đầu tiên Telegram nhận báo cáo tuần.
   **LƯU Ý PYTHON**: desktop KHÔNG có `.venv` → cả 4 task trỏ
   `C:\Python314\python.exe` (system) — dependencies phải đủ ở đó
   (desktop 20/07 full suite 1271 pass nên khả năng cao OK).
3. ✅ **DONE 20/07 — đóng pending #1 từ 27/04**: `vnstock_train --once`
   thành bước **`train`** trong `run.py all` (user chốt "cho vào run.py
   all" thay vì task 15:05 riêng) — chạy SAU audit (rec vừa đóng →
   strategy health có số mới), TRƯỚC reflection; best-effort. Nút 🧩
   Cập nhật còn lại + 🚀 Cập nhật tất cả TỰ HƯỞNG qua `_all_steps` dùng
   chung (parity by construction). Tắt: `run.py all --no-train`; chạy
   lẻ: `run.py train`. Pipeline nay **13 bước**, ước tính 35-55 phút
   (train = backtest VN30 ~5-15 phút + vài call LLM/ngày).
Tùy chọn nhỏ còn để dành: bước `preset-score` best-effort vào pipeline
tối (cache expander 📋 luôn tươi thay vì chờ bấm 🔄).

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

### 1. ✅ Auto-schedule `vnstock_train.py` (DONE 2026-07-20 — đóng sau 3 tháng treo)

**Cách chốt**: KHÔNG task 15:05 riêng — user chọn đưa thành bước `train`
trong `run.py all` (sau audit, trước reflection; `--no-train` để tắt).
Task đêm 18:00 + nút 🧩/🚀 dashboard tự chạy train mỗi ngày. Xem mục
📅 AUDIT ở trên. Lý do daily-not-continuous vẫn đúng: data VN refresh
1×/ngày, train nhiều hơn chỉ đốt token; "train" = refresh few-shots +
strategy loop (tune/revise + validation 🧪 + Bonferroni + decay) +
reconcile, không có model weights local.

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

**⚠️ GOTCHA GIT (gặp thật 16/07, tái 20/07)**: máy user checkout nhánh
KHÁC (laptop 16/07: `claude/phase-1-kickoff-lzorv6`; desktop 20/07:
`main` local) nhưng CHUNG lineage với nhánh session
(`claude/stocksharp-dashboard-research-bv9tas`) — commit SHA trùng. Khi
user "git pull" báo "Already up to date" mà KHÔNG lấy được commit mới
(khác tên nhánh) → chạy code cũ (20/07: setup script bản cũ chỉ đăng ký
3 task, thiếu Rates Weekly). Cách sửa: `git fetch origin` +
`git merge --ff-only origin/<session-branch>` (ff sạch vì chung tổ tiên).
Dấu hiệu chẩn đoán: `python -c "import M; print(hasattr(M,'<hàm mới>'))"`
ra False / output script thiếu tính năng mới = đang chạy code cũ dù đã
"pull". Desktop main local nay ĐI TRƯỚC origin/main (chứa commit session
chưa merge PR) — vô hại, nhưng đừng push main từ máy user.

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

**Khảo sát LẠI DojoAgents (2026-07-20, user hỏi "tích hợp được gì" lần 2 —
12 commit mới từ 15/07): KHÔNG đổi kết luận cũ (dojosdk vẫn ĐÓNG, `quant/`
vẫn scaffold 62 dòng, commit mới đa số là React Market Discovery UI —
treemap/timeline/sparkline, heatmap đã bác 15/07). ĐIỂM MỚI ĐÁNG GIÁ DUY
NHẤT: nâng cấp SPEC cho net-worth curve (món 7d) từ
`portfolio_performance.py` + fix 13/07 của họ "dropped NAV points inflating
vol/Sharpe/drawdown"** — 3 bài học PHẢI áp khi build:
1. **Trục ngày = LỊCH GIAO DỊCH** (bên mình: ngày bar VNINDEX trong parquet
   = lịch HOSE tự nhiên), KHÔNG phải "những ngày tình cờ có giá" — ngày bị
   drop khiến return 2-3 phiên đội lốt 1 phiên → vol/Sharpe/maxDD phồng.
2. **Forward-fill giá TỪNG MÃ** (`_forward_fill_on_or_before`): mã thiếu
   bar/ngừng giao dịch → carry close cuối, KHÔNG drop cả ngày khỏi curve;
   chỉ bỏ ngày khi mã CHƯA TỪNG có giá tính đến hôm đó.
3. **Rebase cả 2 đường về 100** tại ngày đầu chung (danh mục vs VNINDEX);
   optional block stats deterministic ~60 dòng (cumulative / vol √~250 /
   Sharpe / maxDD / Calmar) — display-only cạnh curve.
SKIP có lý do: `market_dynamics_service` events+sector impacts (data từ
dojosdk đóng; concept ≡ "→ tác động" news_feeds + upcoming_events);
`tasks/preflight` skip-ngày-nghỉ (exchange_calendars KHÔNG có lịch HOSE;
pipeline đã T2-T6 + effective_trading_date + doctor dung sai — muốn thêm
phải tự nuôi list nghỉ lễ VN, chưa đau); sector movers gates (min 5 thành
viên + min cap + lead score cap×%đổi ≡ ⭐ GTGD + gate ±0.05pp +
`_leadlag_candidates`). Bonus cho món PE band để-dành: cách của họ =
PE(t)=close(t)×shares/LN-TTM **neo theo ngày BCTC khả dụng** (anchor
schedule — point-in-time, không lookahead), band mean±1σ/2σ, shares giữ
hằng → xác nhận cần LN QUÝ lịch sử (fundamentals.parquet chưa có), scope
VN30 khi làm.

### 📈 Net-worth curve NAV danh mục (DONE 2026-07-20 — món DojoAgents, user "làm đi") — `vnstock_networth.py`

Display-only, deterministic thuần, zero LLM/fetch — chỉ đọc
`_meta/portfolio.json` + kho parquet; KHÔNG ghi DB, không đụng logic P&L
hiện có của tab. Tests `tests/test_networth.py` (14, hermetic — core thuần
nhận dict, loader end-to-end trên tmp parquet) đã vào `--fast`.
- **NAV(t) = tiền mặt ngầm định + Σ qty×close(t)** các vị thế đã mua tính
  đến t: vốn vị thế mua SAU tính như cash 0% tới buy_date (mirror
  order-replay của DojoAgents) — CỐ Ý khác sketch v0 "mã chưa mua chưa
  tính": bỏ hẳn thì mỗi lần mua thêm tạo bước nhảy "nạp tiền" đội lốt lợi
  nhuận → so VNINDEX thành outperform giả + vol/Sharpe bẩn. Mua đúng giá
  close ngày mua → curve liên tục (jump duy nhất = lệch close-vs-giá-mua
  trong phiên = P&L thật).
- **3 bài học chống-phồng-stats áp đủ** (spec 20/07): trục ngày = ngày bar
  VNINDEX trong kho (fallback = hợp ngày các mã khi kho thiếu index, đường
  index ẩn); forward-fill close từng mã (thiếu bar → carry close cuối),
  CHỈ bỏ ngày khi một mã đang giữ CHƯA TỪNG có bar tính đến hôm đó (đếm
  `skipped_days`, hiện caption); rebase cả 2 đường về 100 tại ngày đầu chung.
- **Neo đơn vị về buy_price của user** (`_anchor_factor`): kho parquet trộn
  VND thô ↔ nghìn đồng per-bar (bẫy `_normalize_prices`), `_stitch_units`
  (tái dùng từ preset_score) chỉ nhất quán NỘI BỘ từng chuỗi → cross-ticker
  vẫn lệch 1000×. Neo bằng close phiên ≤ buy_date: ratio khớp lũy thừa 1000
  trong dung sai [0.5, 2] mới rescale, ngoài dung sai giữ 1.0 (không đoán
  bừa). buy_price là nguồn chân lý đơn vị (UI nhập "Giá mua (VND)" thô).
- **Stats `compute_curve_stats`** (mirror block risk-stats DojoAgents):
  tích lũy % · vol năm hóa √250 · Sharpe (rf=0) · maxDD % · Calmar · số
  phiên — suy biến trả None thay vì chia 0. Vị thế buy_date TƯƠNG LAI →
  loại hẳn (kẻo thành cash vĩnh viễn); mã không có data giá → loại khỏi
  curve + caption "Loại mã…" (mirror triết lý missing-feed của tab).
- **UI**: mục "📈 Giá trị danh mục theo thời gian (NAV)" trong
  portfolio_tab (sau bảng vị thế, trước Phân bổ ngành) — plotly 2 đường
  (NAV #60a5fa, VNINDEX dash #94a3b8; fallback st.line_chart), caption
  stats + caveat "vốn mua sau = tiền mặt tới ngày mua", best-effort
  try/except (mirror sector exposure). CLI: `python vnstock_networth.py
  [--json] [--warehouse DIR]`.
- **VERIFY trên máy user (kho giá + vị thế thật)**: mở tab 💼 Danh mục →
  chart 2 đường + caption stats; đối chiếu: mua 1 đợt thì % tích lũy NAV ≈
  % L/L của bảng (lệch nhỏ = close kho vs live quote); mua nhiều đợt thì
  KHÔNG khớp là ĐÚNG (NAV tính cả kỳ tiền mặt chờ giải ngân);
  `python vnstock_networth.py` in cùng số với UI. **Đã smoke-verify TRONG
  SANDBOX 20/07** (streamlit headless + Playwright, kho demo 70 phiên tổng
  hợp): chart 2 đường + caption stats/caveat render đúng, số UI khớp CLI,
  mua đợt 2 giữa kỳ KHÔNG tạo bước nhảy (implied cash chạy đúng).
  **✅ VERIFY TRÊN MÁY USER 20/07 tối** (2 vị thế thật SSI/EIB mua 17/07):
  curve 2 phiên render, điểm cuối NAV = ĐÚNG tổng "GT hiện tại" của bảng;
  chênh tích lũy −6.2% (close→close) vs bảng −5.48% (từ giá mua) = đúng
  thiết kế 2 mốc neo khác nhau.
- **Đánh bóng 20/07 (3 món user chốt sau verify)**: (a) `summary_parts(res)`
  — builder caption DÙNG CHUNG UI↔CLI (parity by construction); < 10 phiên
  ẨN vol/Sharpe/Calmar ("Calmar −16.02" trên 2 điểm là nhiễu thống kê),
  giữ tích lũy/VNINDEX/maxDD + dòng nhắc "hiện khi đủ ≥10 phiên";
  (b) trục X plotly `tickformat %d/%m` + `rangebreaks` ẩn T7-CN (hết nhãn
  00:00/12:00 + đoạn thẳng xuyên cuối tuần; ngày LỄ VN vẫn gap — chấp
  nhận, chưa nuôi lịch nghỉ lễ) + **dtick 1 ngày KHI ≤ 10 phiên** (vòng
  ảnh 3 của user: auto-tick dưới ngày làm nhãn lặp "16/07·16/07·17/07…";
  chuỗi dài giữ auto — dtick cứng làm trục dày đặc); (c) xem mục 💼 —
  resolver làm tròn 6 chữ số có nghĩa.
- **Fix kèm (lộ khi smoke-verify trên pandas 3.0)**: khối Phân bổ ngành
  chết `'Styler' object has no attribute 'applymap'` — pandas ≥2.1
  deprecate, pandas 3 BỎ HẲN `Styler.applymap` → portfolio_tab nay ưu tiên
  `.map`, fallback `.applymap` (chỗ dùng DUY NHẤT cả repo). Desktop vừa
  lên stack Python 3.14 mới 20/07 — khả năng cùng bệnh, fix này chữa luôn.

### 💼 Fix "giá đóng băng" tab Danh mục (DONE 2026-07-20 — user bắt trên máy thật)

**Bug**: user mua SSI 23,000 / EIB 19,000 NGÀY 20/07, tab hiện "Giá hiện
tại" 26,650 (+15.87%) / 20,800 (+9.47%) — +15.87% cùng phiên vượt cả kịch
bản sàn→trần (~15.05%) = chắc chắn sai; diag kho ra bar 20/07 = 22.70
ĐÚNG (khớp thị trường) → lỗi ở TẦNG ĐỌC GIÁ của portfolio_tab, không phải
data. 2 lỗ hổng: (a) `_live_quote` thắng VÔ ĐIỀU KIỆN không check tuổi —
quote WSS cũ đóng băng giá (cùng họ bug nn_flow_cache); (b)
`_warehouse_last_close` lấy `iloc[-1]` của FILE ĐẦU THEO TÊN — không sort
theo thời gian (bẫy Dropbox conflicted copy đã biết từ 07/07), không
chuẩn hóa đơn vị.

**Fix — `resolve_current_price(ticker, buy_price, buy_date, warehouse)`**
(render loop dùng hàm này; `_live_quote`/`_warehouse_last_close` giữ làm
primitive):
- Nguồn có **NGÀY DATA mới hơn thắng** (quote live ↔ bar cuối kho); cùng
  ngày → live (trong phiên tươi hơn close EOD). Ngày quote từ field
  `time` trong JSON, fallback mtime file.
- Bar kho = mới nhất THEO THỜI GIAN, gộp mọi file parquet qua
  `vnstock_networth._close_series` (sort + stitch).
- Giá NEO về đơn vị buy_price (`_anchor_factor` — kho trộn VND thô ↔
  nghìn đồng per-bar; buy_price user là nguồn chân lý đơn vị).
- Bảng hiện **"MM-DD·nguồn"** cạnh giá (triết lý as_of) + tripwire ⚠ khi
  %L/L ngay trong NGÀY MUA vượt ±7.5%/phiên (chính sanity check đã tóm
  bug này) + caption cảnh báo.
- Kèm cosmetic pandas 3: bảng Phân bổ ngành format chuỗi ("56.2" thay
  "56.200000", Lãi/Lỗ có ngăn nghìn), `_color_diff` parse chuỗi.

Tests `tests/test_portfolio_prices.py` (9, hermetic — có case tái hiện
đúng bug quote-cũ-thua-kho-tươi + case conflicted copy) vào `--fast`
(suite 781). Smoke-verify sandbox: seed quote HPG giả 99,999 ngày 08/07 →
tab hiện đúng bar kho 20/07 kèm "07-20·kho". **✅ VERIFY TRÊN MÁY USER
20/07 tối**: SSI ra 22,700 (07-20·kho) đúng bar kho, EIB 17,850
(07-20·kho); tổng L/L về số thật (−5.48% — thị trường rơi, không phải
lãi ảo +12.98%); quote_*.json cũ tự thua theo ngày, không cần xóa.
EIB −10.3% từ giá mua trông vượt biên NHƯNG là 2 phiên cộng dồn (mua
trong phiên 17/07 @19,900 > close 18,980, rồi 20/07 −5.95%) — đối chiếu
chéo từ caption NAV, hợp lệ. **Rounding kèm (đánh bóng 20/07)**: resolver
làm tròn giá 6 chữ số có nghĩa — kho lưu close float32 (22.700001×1000)
làm "GT hiện tại" ra đuôi lẻ "454,000,015".

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
`DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY` (Google AI Studio, thêm 22/07 — sentiment nấc 1).

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

## 2026-07-22 — Thay ladder sentiment (điểm [1]) + ledger phủ đủ call trả phí + cột quy đổi tiền

Bối cảnh: audit model 21-22/07 phát hiện ladder 8B llama chết gần hết (Groq
deprecate `llama-3.1-8b-instant`/`llama-3.3-70b-versatile` 17/06; Cerebras đã
gỡ `llama3.1-8b`/`llama-3.3-70b`; OpenRouter hết bản `:free` của llama 3.1-8B
— ledger 21/07: 34/34 lỗi trên 2 nấc fallback). Slug mới chốt bằng **probe 2
vòng trên máy thật** (`scripts/probe_models.py` — gọi 1 call thử/slug, đừng
bao giờ thay model theo catalog trên mạng, bài học kimi-k2 14/07 lặp lại:
`qwen3-235b-a22b:free` trên OpenRouter 4/4 OK ngày 21/07, **chết sáng 22/07**).

1. **`vnstock_sentiment._PROVIDERS` mới** (điểm [1] trong sơ đồ 8 điểm dùng
   LLM): Gemini `gemini-3.5-flash-lite` → Groq `openai/gpt-oss-20b`
   (`extra: reasoning_effort=low`) → Cerebras `gemma-4-31b` → OpenRouter
   `openai/gpt-oss-20b:free`. Entry provider giờ có `max_tokens` riêng
   (reasoning model gpt-oss tiêu budget vào suy nghĩ — 10 token như cũ là cụt
   output) + `extra` merge vào body. `chat_complete` lấy `max(max_tokens
   caller, floor provider)`; `extra` CHỈ gửi khi gọi đúng model mặc định của
   provider (model override qua `model_map` có thể 400 vì param lạ).
2. **Provider Gemini mới** (OpenAI-compat
   `generativelanguage.googleapis.com/v1beta/openai/`): key `GEMINI_API_KEY`
   (.env.example đã có mục). Key user là Postpay Tier 1 → tính tiền theo
   usage (~$0.10/$0.40 per 1M, sentiment ≈ $0.1/tháng) nhưng đổi lại prompt
   KHÔNG bị dùng training + rate limit cao. Dòng 2.5-flash bị Google khóa với
   project mới → phải dùng 3.5-flash-lite (đừng "sửa lùi" về 2.5).
3. **Ledger phủ đủ call trả phí** (trước đây MÙ 3 chỗ): brief
   `ClaudeAgent`/`_OpenAICompatAgent` (nhãn provider qua class attr
   `_LEDGER`), auditor Claude/GPT, classifier `_call_claude` — tất cả ghi
   best-effort qua helper `_ledger_record` cùng mẫu vnstock_sentiment.
4. **`--show` có cột tiền**: `_PRICES_PER_MTOK` trong vnstock_llm_ledger
   (prefix-match tên model, dòng cụ thể đặt TRƯỚC dòng chung — flash-lite
   trước flash; không khớp → free $0), `_USDVND = 26,200`. Header tổng
   `≈ $x (~y đ)`, dòng nào >0 mới in `$`. Giá là ƯỚC TÍNH hiển thị — đổi giá
   sửa bảng, không ảnh hưởng ghi sổ.
5. **Kết quả probe chốt (22/07)** cho các điểm [2]-[8] sắp sửa: Groq
   `openai/gpt-oss-20b`/`openai/gpt-oss-120b`/`qwen/qwen3.6-27b` ✅ (2 llama
   cũ còn chạy nhưng sẽ bị gỡ); Cerebras catalog CHỈ còn `gpt-oss-120b` +
   `gemma-4-31b` + `zai-glm-4.7` (dep 17/08 — tránh); OpenRouter 14 model
   `:free` — đáng chú ý `nvidia/nemotron-3-super-120b-a12b:free` ✅,
   `nvidia/nemotron-3-ultra-550b-a55b:free` ✅, `google/gemma-4-31b-it:free`
   (429 upstream — chập chờn); Gemini `gemini-3.5-flash` ✅ (6.1s),
   `gemini-flash-lite-latest` ✅. Điểm [2]-[8] CHỜ user duyệt từng điểm —
   đừng tự thay.
6. Tests: `tests/test_model_ladder.py` (7 test — guard slug ladder, body
   merge, cost prefix-match, ledger brief/auditor); test_sentiment +
   test_doctor thêm `GEMINI_API_KEY` vào danh sách delenv (không xóa thì máy
   có key Gemini sẽ fail test available_provider). Fast suite 795 passed.

## 2026-07-22 (b) — Điểm [2] chấm tin: bỏ Opus, FREE-FIRST (user chốt)

User chốt sau khi xem batch 8 tin 22/07 do Gemini flash-lite chấm (route Opus
không chạy vì thiếu key — "hên": fallback ladder mới đỡ trọn, mapping kênh
chuẩn, tin phi kinh tế trả đúng "không tác động trực tiếp"): **chọn model free
tốt nhất làm CHÍNH, không dùng Opus trả phí nữa; chỉ quay lại trả phí khi
free không đáp ứng**.

- `_ANALYZE_MODELS` mới (override cho `chat_complete`, thử override trước →
  default provider sau): Gemini `gemini-3.5-flash` (CHÍNH — mạnh nhất nhóm
  free đã probe, đa ngữ tốt nhất; ~$0.2/tháng trên key Postpay) · Groq
  `qwen/qwen3.6-27b` · OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`.
  Chuỗi hiệu dụng khi rơi hết: 3.5-flash → 3.5-flash-lite → qwen3.6-27b →
  gpt-oss-20b → gemma-4-31b (Cerebras default) → nemotron-ultra →
  gpt-oss-20b:free — KHÔNG còn nấc chết nào.
- **`_paid_analyze_enabled` ĐẢO MẶC ĐỊNH**: unset/rỗng/`0` = TẮT; bật Opus
  lại = `VNSTOCK_NEWS_ANALYZE_PAID=1` (+ key). `_ANALYZE_MODEL_DEFAULT` giữ
  `claude-opus-4-8` cho lúc opt-in. Đường code trả phí GIỮ NGUYÊN — điều
  kiện "free gượng mới dùng trả phí" nằm ở 1 dòng env, không phải sửa code.
- Tests: đảo bảng parse switch (unset→False), paid-wins/fallback set env
  `=1` tường minh, thêm `test_default_free_first_skips_paid_route` +
  `test_analyze_models_slugs_22_07` (guard slug). Fast suite 795 passed.
- Theo dõi 2-3 hôm: mapping gượng kiểu "PNJ hưởng lợi từ động thái của chính
  mình" tái xuất trên 3.5-flash → bật lại Opus qua env (đừng hạ tiêu chuẩn).

## 2026-07-22 (c) — Điểm [3][4][5] digest all-free + alert "LLM ladder DOWN"

Chẩn đoán chốt: `.env` máy user TRỐNG cả ANTHROPIC_API_KEY lẫn OPENAI_API_KEY
→ nấc Claude/GPT của digest/auditor/brief bấy lâu chỉ là hình thức. User chốt
**all-free** + yêu cầu mới: "nếu tất cả free đều lỗi thì phải BÁO tôi để sửa
hoặc thêm model trả phí".

1. **Cascade digest mới** (`vnstock_report_digest` — dùng chung digest/
   reflection/debate): bậc 1 = Gemini `gemini-3.5-flash` (6000 tk) + Cerebras
   `gpt-oss-120b` (giữ, 6000) + OpenRouter `nemotron-3-ultra-550b:free`
   (4000; thay qwen-235b:free ZOMBIE — OK 21/07, 404 sáng 22/07, OK trưa
   22/07); bậc 2 = Groq `gpt-oss-120b` + `qwen3.6-27b`, Gemini flash-lite,
   OpenRouter `gpt-oss-20b:free`; `_TIER2_TOKENS` 1200→3000 (bậc 2 nay có
   reasoning model; prompt ~4K + 3K vẫn lọt TPM 8K Groq). `_PROVIDER_META`
   thêm Gemini. Nấc Claude/GPT GIỮ NGUYÊN làm opt-in (điền key là sống lại).
2. **Alert "LLM ladder DOWN"** (`vnstock_llm_ledger.alert_ladder_down`):
   gửi Telegram khi 1 tác vụ cạn TOÀN BỘ nấc — throttle 1 lần/ngày (flag
   `_meta/llm_alert.json`, CHỈ ghi khi gửi thành công → telegram hỏng thì
   lần cạn sau thử lại), kill-switch `VNSTOCK_LLM_ALERT=0`. Điểm gọi:
   `digest_call` trả (None,''), `chat_complete` trả None,
   `score_news_batch` khi ≥3 tin cần chấm mà model rỗng toàn bộ. conftest
   autouse set `VNSTOCK_LLM_ALERT=0` cho MỌI test (không tắt là suite chạy
   trên máy có token telegram sẽ nhắn user thật); test alert tự đè =1.
3. **Doctor**: `check_llm_ledger` thêm bậc "error" khi hôm nay calls>=3 mà
   ok==0 (ladder down toàn phần) — trỏ probe_models + --show.
4. Tests: digest tests cập nhật slug mới + clear thêm GEMINI_API_KEY (máy
   user có key thật, không clear là Gemini rung ăn fake resp sai kịch bản);
   dedup env-override test đổi sang slug bậc 2 thật; test mới: guard slug
   digest 2 bậc, alert gửi-1-lần/ngày, kill-switch + retry khi send fail,
   doctor error. Fast suite 795 passed.

## 2026-07-22 (d) — Điểm [7] brief: Gemini làm agent chính, ladder mạnh→yếu, bảng đổi số

User chốt: (a) auto-fallback theo THỨ TỰ SỨC MẠNH (mạnh trước, yếu dần khi
lỗi); (b) giữ agent cũ chạy song song vài hôm để kiểm định chất lượng
(2 bản brief cùng data + cùng guard chấm — cách A/B chuẩn).

1. **`GeminiAgent` mới** (registry key "gemini", default `gemini-3.5-flash`)
   — agent CHÍNH cho brief: đa ngữ tốt nhất nhóm khả dụng, TPM 1M nuốt gọn
   prompt brief ~10K token (Groq TPM 8K là biên rủi ro 413). flash SUY NGHĨ
   mặc định → `generate` tự nới `max_tokens + _THINK_HEADROOM` (3000) để
   content không bị cụt dưới _BRIEF_MAX_TOKENS. Trong `_DEFAULT_AGENT_CONFIGS`
   đứng ĐẦU với `enabled: True` — cơ chế merge của load_agent_configs tự
   thêm vào brief_agents.json cũ trên máy user, không phải bấm dashboard.
2. **`_AGENT_STRENGTH` + `_strength_sorted`**: gemini → claude → openai →
   deepseek → groq → mistral → cerebras → openrouter (openrouter :free cuối
   vì quota 50 req/ngày + churn; type lạ xếp cuối, sort ổn định giữ thứ tự
   config). generate_brief sort agents NGAY sau build_agents.
3. **Kết quả sắp TẤT ĐỊNH theo sức mạnh**: trước đây results theo thứ tự
   as_completed → bật >1 agent thì bản Telegram (_brief_snippet lấy bản đầu
   không lỗi) phụ thuộc agent nào XONG TRƯỚC. Nay bản chính luôn = agent
   mạnh nhất thành công; agent phụ chỉ là bản so sánh trong dashboard.
4. **Auto-fallback "(dự phòng)"**: mọi agent đang bật đều lỗi → thử tuần tự
   agent CÓ KEY nhưng chưa bật (mạnh→yếu), bản đầu tiên thành công gắn nhãn
   "(dự phòng)" và ĐI QUA guard/validator/memory như thường (append vào
   `available` trước khi các vòng đó chạy). Vẫn trắng tay → alert Telegram
   (throttle/kill-switch dùng chung alert_ladder_down). Nhánh _no_available
   cũng alert.
5. **Bảng đổi số `_MODEL_MIGRATIONS`** nới 1→8 dòng: Groq 70B→qwen3.6-27b,
   Groq 8b→gpt-oss-20b, Cerebras 4 slug llama→gpt-oss-120b, OpenRouter
   llama :free→nemotron-super-120b:free / gpt-oss-20b:free. Chỉ đổi Ô MODEL
   khớp đúng cặp (type, model) — enabled/thứ tự/tên/slug user tự gõ giữ
   nguyên. Default configs + default __init__ của Groq/Cerebras/OpenRouter
   agent cũng lên slug mới; Cerebras `_MODEL_FALLBACKS` (4 slug chết cả 4)
   → ["gpt-oss-120b", "gemma-4-31b"].
6. **Vá lỗ ledger**: Cerebras/OpenRouter agent OVERRIDE generate riêng nên
   đợt phủ ledger 22/07 (a) không chạm tới — nay ghi sổ cả 2 (success+fail
   từng model thử). Doctor brief_keys + caption market_tab thêm GEMINI.
7. Tests: 5 test mới (headroom Gemini + ledger, migration giữ enabled/không
   đụng slug lạ + merge Gemini, strength sort, defaults không slug chết +
   map phủ đủ, inspect-source ordering/fallback/alert). Fast 795 passed.
   Theo dõi vài hôm: so 2 bản brief trong dashboard (Gemini vs Groq qwen),
   ưng thì tắt agent phụ; ledger soi token/lỗi từng con.

## 📌 TODO & CHỜ VERIFY sau đợt thay model 22/07 (điểm [1]-[7] xong, còn [6][8])

### Việc CHƯA làm (2/8 điểm của sơ đồ model)

1. **[6] Auditor** — hiện `make_auditor("auto")` không key Anthropic/OpenAI
   → NullAuditor **phê duyệt mọi thứ** (bước phản biện screener vô hiệu từ
   lâu). Phương án đã bàn: viết `FreeAuditorAgent` đi qua cascade digest
   sẵn có (`digest_call` — Gemini flash/gpt-oss chấm JSON verdict rất hợp),
   NullAuditor chỉ còn là nấc cuối; ghi ledger như các auditor khác.
2. **[8] Classifier** — CLI thủ công, `_call_claude` RAISE khi thiếu
   ANTHROPIC_API_KEY (crash, không fallback). Phương án đã bàn: thêm đường
   Gemini flash (free ~2 ngày quota cho batch 1,700 mã, hoặc ~$0.5/lần trên
   key Postpay); giữ Claude làm opt-in khi có key.

### Chờ VERIFY trên máy thật (soi trong 2-5 ngày tới)

- **Brief (điểm [7])**: sau pull, lần chạy brief đầu tiên phải (i) tự đổi
  slug trong `brief_agents.json` (Groq → qwen/qwen3.6-27b…), (ii) tự thêm
  agent "Gemini 3.5 Flash" enabled. Bản Telegram = Gemini; dashboard có
  thêm bản Groq so sánh. So chất lượng vài hôm (văn phong, bám template,
  cờ 🚨, auto-score trong memory) → ưng thì tắt agent phụ trong ⚙️.
- **Chấm tin (điểm [2])**: `Gemini:gemini-3.5-flash` gánh 8 tin/ngày —
  soi vài hôm; ca "mapping gượng" kiểu "PNJ hưởng lợi từ chính mình" tái
  xuất → bật lại Opus: `VNSTOCK_NEWS_ANALYZE_PAID=1` (KHÔNG hạ tiêu chuẩn).
- **Sentiment (điểm [1])**: flash-lite tỉ lệ OK phải ~100%, không rate-limit.
- **Digest bậc 1 Cerebras `gpt-oss-120b` đang chập chờn** (8/11 rồi 1/1
  fail 21-22/07) — `_warn_rung` giờ in body lỗi API: soi output digest lần
  tới để bắt đúng bệnh (capacity 503? budget? param?). Lỗi bền vững → cân
  nhắc bỏ nấc, đã có Gemini/nemotron gánh.
- **Ledger + cột tiền**: từ 23/07 lần đầu hiển thị ĐỦ brief+digest+sentiment
  +analyze; tổng ngày dự kiến ~$0.02-0.05 (~500-1,300 đ). Lệnh:
  `python vnstock_llm_ledger.py --show`.
- **Alert "LLM ladder DOWN" chưa được bắn thật** — cơ chế đã test hermetic
  (throttle 1 lần/ngày, flag `_meta/llm_alert.json`, kill-switch
  `VNSTOCK_LLM_ALERT=0`) nhưng chưa có sự cố thật để xác nhận Telegram
  nhận tin. Tuỳ chọn: thêm lệnh `--test-alert` bắn thử (chưa làm).
- **OpenRouter**: cân nhắc nạp 1 lần $10 → quota :free 50 → 1,000 req/ngày
  (tiền thành credit, không mất).
- **Doctor**: `run.py doctor` phải hiện dòng sentiment provider = Gemini và
  bậc "error" nếu một ngày toàn lỗi (đã có test, chưa thấy chạy thật).

### Nhắc quy trình (đã thành nếp từ đợt này)

- MỌI slug model mới phải probe sống trước khi vào code:
  `python scripts/probe_models.py` (đừng tin catalog trên mạng — bài
  qwen-235b:free sống 21/07 chết sáng 22/07 sống trưa 22/07).
- Provider khai tử model → thêm 1 dòng `_MODEL_MIGRATIONS` (brief) và/hoặc
  đổi ladder tương ứng + cập nhật test guard slug trong
  `tests/test_model_ladder.py` (fail = có slug chết lọt lại).

## 2026-07-29 — Nếp probe/migration thành CƠ CHẾ CỨNG (không còn chỉ là ghi chú)

1. **Test quét slug chết TOÀN REPO** (`tests/test_model_ladder.py`):
   `_DEAD_SLUGS_22_07` (15 slug chết/deprecated đã xác nhận qua probe) ×
   `_all_live_slugs()` (gom slug từ MỌI điểm dùng model: sentiment,
   analyze, digest 2 bậc, brief defaults + fallback nội bộ + __init__
   registry). Slug chết lọt lại BẤT KỲ đâu → fast suite đỏ. Kèm test đích
   migration không được trỏ về slug chết (bài entry cũ dead-to-dead:
   cerebras llama-3.3-70b → llama3.3-70b). Điểm dùng model MỚI phải khai
   vào `_all_live_slugs` để được quét.
2. **`probe_models.py --slug "Provider=model"`** (lặp lại được): probe
   ad-hoc 1-2 slug ứng viên không cần sửa file, bỏ listing catalog cho
   nhanh; không có --slug → chạy trọn bộ như cũ.
3. **CLAUDE.md** thêm quy ước 5 dòng (probe trước khi vào code; khai tử →
   1 dòng _MODEL_MIGRATIONS + 1 slug vào _DEAD_SLUGS) — mọi session sau
   thấy ngay, không phải mở CLAUDE-NOTES.

## 📌 CẬP NHẬT TODO 29/07 (sau khi máy thật xác nhận 806 passed)

Trạng thái mục "TODO & CHỜ VERIFY 22/07" phía trên:

- ✅ **XONG — "Nhắc quy trình" đã thành CƠ CHẾ CỨNG** (commit 52c99e7,
  verify máy thật 29/07 full suite 806 passed): test quét slug chết toàn
  repo (`_DEAD_SLUGS_22_07` × `_all_live_slugs()` trong
  tests/test_model_ladder.py), probe ad-hoc `--slug "Provider=model"`,
  quy ước 5 dòng trong CLAUDE.md.
- ✅ Toàn bộ điểm [1][2][3][4][5][7] + ledger + cột tiền + alert đã chạy
  production trên máy user (806 passed các đợt 22/07 và 29/07).

### CÒN LẠI (giữ nguyên, chưa làm)

1. ✅ **[6] Auditor** — XONG 29/07 (e): FreeAuditorAgent qua cascade digest
   + bật LLM audit mặc định trong pipeline (xem entry 29/07 (e) phía dưới).
2. **[8] Classifier** — đường Gemini flash cho batch; hiện crash khi
   thiếu ANTHROPIC_API_KEY.
3. **Checklist verify vận hành** (mục 22/07 phía trên): brief A/B Gemini
   vs Groq qwen (soi dashboard + auto-score + ledger vài phiên), Cerebras
   `gpt-oss-120b` digest chập chờn (soi body lỗi từ _warn_rung), alert
   Telegram chưa bắn thật (tuỳ chọn thêm `--test-alert`), cân nhắc nạp
   $10 OpenRouter (quota :free 50→1,000 req/ngày), doctor hiện sentiment
   provider = Gemini.
4. **Merge về main**: tạo PR khi user chốt (điều kiện repo: full suite
   xanh — đã đạt 806 passed).

## 2026-07-29 (b) — Brief chiều vào pipeline đêm (bước 14, hết chạy tay)

User trước giờ chạy brief tay (4 task lịch KHÔNG có task nào đẩy brief —
phát hiện khi rà setup_scheduled_tasks.ps1). Nay `run.py all` có bước CUỐI
`brief` (sau doctor): gọi `vnstock_telegram.push_close_brief()` → sinh brief
chiều bằng ladder điểm [7] (Gemini chính) + đẩy Telegram.

- **Guard `_should_push_close(now, marker)`** (tách riêng để test):
  (i) `now.hour < 15` → bỏ qua — lưới đỡ cho StartWhenAvailable: máy tắt
  lúc 18:00, task chạy bù sáng hôm sau thì KHÔNG đẩy brief chiều cũ lúc 8h;
  (ii) marker `_meta/brief_push.json` ghi hôm nay đã đẩy → bỏ qua (chống
  gửi trùng khi chạy lại pipeline/run_daily.bat trong ngày). Marker CHỈ ghi
  sau khi gửi thành công.
- Lỗi gửi → exit 1 (cảnh báo pipeline, KHÔNG fail cứng — mọi-agent-chết đã
  có alert "LLM ladder DOWN" riêng). Kill-switch: `VNSTOCK_PIPELINE_BRIEF=0`
  hoặc cờ `--no-brief`. Subcommand lẻ `run.py brief` dùng CÙNG guard (chạy
  tay không lo double-send). Brief SÁNG không thuộc pipeline 18:00 — muốn
  tự động thì đặt task riêng ~11:35 gọi `run.py telegram morning`.
- ps1/bat cập nhật mô tả 13→14 bước (command task KHÔNG đổi — không cần
  đăng ký lại task). Tests: 5 test mới trong test_run_pipeline (chuỗi bước,
  parser/dispatch, guard giờ+marker, kill-switch, push+marker/lỗi).
  Fast suite 800 passed.

## 📌 TODO bổ sung 29/07 (b) — sau khi brief vào pipeline

1. **Verify phát đầu tiên của bước 14** (chiều gần nhất sau 18:00):
   Telegram nhận brief chiều tự động; `python vnstock_llm_ledger.py --show`
   có dòng `Gemini:gemini-3.5-flash` ~10K token vào (chính là brief
   pipeline) — đồng thời khép mục verify A/B điểm [7]; marker
   `data_warehouse/_meta/brief_push.json` xuất hiện với ngày hôm đó.
   Chạy lại `run_daily.bat` cùng ngày → log phải in "bỏ qua: … tránh gửi
   trùng".
2. **(Tuỳ chọn, chưa làm) Task thứ 5 "VnStock Morning Brief"** — brief SÁNG
   tự động ~11:35 T2-T6 gọi `run.py telegram morning`: thêm entry vào
   `setup_scheduled_tasks.ps1` + guard giờ/marker tương tự bước brief chiều
   (hiện `run.py telegram morning` CHƯA có guard chống trùng). Sau khi thêm
   → user chạy lại ps1 quyền Admin để đăng ký task mới.

## 2026-07-29 (c) — Gộp 3 task cuối tuần thành "VnStock Weekend Pipeline" (09:00 T7)

User chốt: Corp Actions (CN) + Fundamentals (T2 sáng) + Rates Weekly (T7)
đều 1 lần/tuần → gộp 1 task 09:00 T7; máy tắt thì StartWhenAvailable chạy
lúc mở máy SỚM NHẤT cuối tuần (tắt cả cuối tuần → bù sáng T2).

- **`run.py weekend`** mới (`cmd_weekend` + `_weekend_steps` tách riêng để
  test): rates-weekly (nhẹ, đẩy Telegram trước) → vietstock --bulk
  --register → fundamentals **--force** (nặng ~25-30ph để cuối; --force
  BẮT BUỘC — bug no-op 2026-07-10 đã có test giữ). Khác `all`: 3 bước ĐỘC
  LẬP nên lỗi bước nào ghi cảnh báo rồi VẪN chạy tiếp, trả worst exit code.
- **ps1**: 3 task definition → 1 "VnStock Weekend Pipeline" (MaxMinutes
  180, param -WeekendTime thay 3 param cũ); `$LegacyTaskNames` — script TỰ
  GỠ 3 task cũ cả ở create mode lẫn -Remove (user không phải xoá tay);
  data fundamentals lấy T7 thay vì sáng T2 = cùng số liệu (cuối tuần không
  có phiên). `scripts/run_weekend.bat` mới để chạy tay;
  run_weekly_corp_actions.bat GIỮ NGUYÊN (mục đích ad-hoc "nghe tin corp
  action mới" vẫn hợp lệ).
- ⚠️ USER PHẢI CHẠY LẠI `.\scripts\setup_scheduled_tasks.ps1` (PowerShell
  AS ADMIN) một lần để đăng ký task mới + gỡ 3 task cũ — khác bước brief
  (command không đổi), lần này danh sách task ĐỔI.
- Tests: 3 test mới (thứ tự + cờ --force/--bulk/--register; lỗi giữa chừng
  không chặn bước sau + worst rc; parser/dispatch). Fast suite 803 passed.

## 2026-07-29 (d) — Chốt trạng thái lịch chạy: máy PICHU cầm scheduler

- Máy **PICHU** (user `admin`, venv `C:\Users\admin\.venv` — KHÔNG phải
  `C:\vnstock\.venv` nên ps1 không tự dò được, phải `-PythonExe`) là máy
  DUY NHẤT đăng ký lịch: **2 task** — Daily Pipeline 18:00 T2-T6 (14 bước,
  kết bằng brief chiều Telegram) + Weekend Pipeline 09:00 T7. 3 task cuối
  tuần cũ đã được script tự gỡ (verify output 29/07). Máy nào khác chỉ
  dev/xem dashboard — KHÔNG đăng ký lịch trùng (marker chống gửi trùng
  nằm theo máy, không chia sẻ).
- Bẫy đã dính 29/07 (ghi để khỏi lặp): (i) chạy ps1 khi checkout còn ở
  main cũ → đăng ký bản cũ; (ii) PowerShell admin không active venv →
  ps1 tự dò ra system Python `C:\Python314` KHÔNG có thư viện — task sẽ
  crash import. Thuốc: `git pull`/merge trước + luôn truyền
  `-PythonExe "C:\Users\admin\.venv\Scripts\python.exe"` (hoặc tạo venv
  tại `C:\vnstock\.venv` để tự dò).
- Local main máy PICHU đã fast-forward tới 97454b1; nhắc user
  `git push origin main` để origin/main theo kịp.

## 2026-07-29 (e) — Điểm [6] Auditor: FreeAuditorAgent + bật LLM audit trong pipeline

Chốt nốt điểm [6] của sơ đồ model: trước nay máy all-free không key
Anthropic/OpenAI → `make_auditor("auto")` rơi thẳng **NullAuditor phê duyệt
mọi thứ** — lớp phản biện screener vô hiệu ÂM THẦM; tệ hơn, bước audit
trong pipeline đêm còn CHƯA TỪNG truyền `--llm` nên kể cả có key cũng câm.

1. **`FreeAuditorAgent`** (vnstock_auditor.py, name="free"): đi qua đúng
   cascade `digest_call` của điểm [3-5] (Gemini 3.5-flash → Cerebras
   gpt-oss-120b → nemotron:free → bậc 2; nấc Claude/GPT trong cascade tự
   skip khi không key) — không thêm ladder mới, hưởng sẵn ledger từng nấc,
   feedback 1 lượt tự sửa, alert "LLM ladder DOWN" khi cạn thang.
   `accept=_is_parseable` (JSON verdict lấy ra được — output cắt cụt kiểu
   Cerebras 14/07 = chấm rớt, thử nấc sau). Prompt tách tại "CONTEXT:" —
   chỉ dẫn ổn định làm system, data biến thiên làm user. Cạn thang →
   `approved=False` (run.py audit exit 1 CẢNH BÁO, không fail cứng).
   Backend verdict ghi rõ nấc chấm ("free:Gemini:gemini-3.5-flash").
2. **Factory** `make_auditor`: auto = Claude → GPT → **Free (khi có ≥1 key
   trong `_FREE_KEY_ENVS`)** → Null; thêm prefer="free". Trả phí đứng
   trước vì có key trả phí nghĩa là user CHỦ ĐỘNG bật. Load .env tách ra
   `_ensure_env_loaded()` (mirror report_digest) — vừa vá bẫy CLI fresh
   quên .env (bài digest 14/07), vừa để test monkeypatch no-op (không tách
   thì test factory trên máy thật bị .env đè key vừa delenv → sai như vụ
   conftest 17-18/07).
3. **Pipeline bật LLM audit MẶC ĐỊNH** (run.py): `_audit_llm_enabled` —
   `cmd_all` set `args.llm=True` trừ khi cờ `--no-llm-audit` hoặc env
   `VNSTOCK_AUDIT_LLM=0` (nếp kill-switch). Subcommand `audit` lẻ vẫn
   opt-in `--llm` như cũ. `--auditor` thêm choice "free" ở cả 2 parser.
   Chi phí +1 call free/ngày (payload summary ~vài trăm token) — $0.
4. **Fast list thêm `test_model_ladder.py` + `test_auditor.py`** — test
   quét slug chết toàn repo trước giờ chỉ chạy ở FULL suite, lời hứa "đỏ
   ngay ở test --fast" trong docstring là hứa suông; giờ mới đúng.
   `_all_live_slugs` khai thêm DEFAULT_MODEL của Claude/GPT auditor ([6]).
5. Tests: 9 test mới (factory free forced/auto/ưu tiên trả phí; route qua
   digest_call + tách system/user + backend ghi nấc; accept chấm rớt JSON
   cụt; cạn thang → unapproved; `_audit_llm_enabled` default/kill-switch;
   inspect-source cmd_all; parser). Fixture `_no_keys` chặn
   `_ensure_env_loaded` + xoá 6 key cho factory test hermetic. Sandbox
   fast 848 passed / full 1375 passed.
6. **Verify máy thật**: ✅ full suite **1386 passed** trên máy PICHU 29/07
   (đông hơn sandbox 1375 vì máy có vnstock/vnai nên các test skip chạy
   đủ; 3 warning chỉ là thông báo update package vnstock — vô hại).
   ✅ `run.py audit --llm` chạy 2 vòng cùng tối: vòng 1 Gemini chết key →
   cascade rơi đúng nấc `free:Cerebras:gpt-oss-120b`; vòng 2 (sau khi thay
   key, xem entry (f)) `free:Gemini:gemini-3.5-flash`. Cả 2 vòng verdict
   disapprove toàn báo động GIẢ do thiếu chú giải schema → sinh entry (f).
   CÒN THEO DÕI: phát pipeline 18:00 tới tự audit LLM (soi `run_daily.log`);
   sau chú giải schema kỳ vọng approved=True khi data sạch. Muốn tắt:
   `VNSTOCK_AUDIT_LLM=0` vào .env.

## 2026-07-29 (f) — Sự cố key Gemini (biến Windows đè .env) + chú giải schema cho auditor

**Sự cố key** (lộ khi verify điểm [6], 23:17): mọi call Gemini trả 400
"Please pass a valid API key" dù code sentiment/digest giống hệt nhau và
từng chạy OK 23/07. Truy ra: `.env` **CHƯA TỪNG có dòng GEMINI_API_KEY** —
key sống từ 22/07 nằm ở biến môi trường Windows tầng **User** (setx), và
key đó bị Google thu hồi giữa 23-29/07. Vì mọi `_ensure_env_loaded` dùng
`load_dotenv(override=False)`, **biến Windows LUÔN THẮNG `.env`** — sửa
`.env` sẽ không có tác dụng nếu quên biến cũ. Xử lý 29/07: tạo key mới
(AI Studio) → điền vào `.env` (nguồn DUY NHẤT từ nay) → xoá biến User
(`[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $null, "User")`
+ `Remove-Item Env:GEMINI_API_KEY`). Probe verify: flash-lite ✅; flash 503
"high demand" lúc 23:28 (quá tải free tier giờ cao điểm Mỹ — không phải
key, vài phút sau gọi lại được). Key cũ đã dán lên chat → coi như lộ,
không tái sử dụng. **Bài học**: chẩn key ngờ ngợ thì soi đủ 3 tầng
`$env:`, `[Environment]::GetEnvironmentVariable(...,"User"/"Machine")` và
`Get-Content .env | Select-String` — đừng tin mỗi `.env`.

**Chú giải schema cho auditor** (`run.py _audit_llm_context`): 2 vòng
verify (Cerebras rồi Gemini — 2 model độc lập nhầm CÙNG kiểu) đều
disapprove ~0.95 toàn báo động giả: (i) so reconciler.fail=0 với
anomalies.by_severity.fail=126 — 2 lớp kiểm ĐỘC LẬP, không có nghĩa vụ
khớp; (ii) tưởng payload 1 ngày nên "9.000 dòng là sai" — reconciler đếm
ticker×date trên cả cửa sổ lookback; (iii) nghi warn≈missing_in_api là
double-count — thực ra BY DESIGN (vnstock_reconciler: dòng right_only vừa
+1 missing_in_api vừa +1 warn; missing_in_rolled thì loại hẳn khỏi
ok/warn/fail — WSS chỉ phủ một phần thị trường). Fix: context truyền vào
auditor giờ là `_audit_llm_context(len(recon.dates_checked))` — text
deterministic chốt 5 điểm semantics trên + "never add up to one total";
2 test giữ (nội dung chú giải + inspect-source cmd_audit). Nếu sau này
auditor kêu oan kiểu MỚI → bổ sung dòng chú giải tương ứng (đừng hạ
ngưỡng model).

✅ **VERIFY máy thật 29/07 ~23:55** (sau git pull, 1388 passed): cùng
payload từng bị disapprove 3 vòng → `auditor=free:Gemini:gemini-3.5-flash
approved=True conf=1.00`, không issue nào. Điểm [6] khép trọn: cascade +
key mới + chú giải schema đều xác nhận sống. Còn theo dõi thụ động: phát
pipeline 18:00 tới tự chạy audit LLM (soi run_daily.log).

## 2026-07-29 (g) — `probe_models.py --ladder`: health check toàn ladder 1 lệnh

Bộ `_CANDIDATES` mặc định của probe là danh sách ỨNG VIÊN đông cứng hồi
22/07 — không phủ ladder hiện tại (Groq không được probe con nào). Thêm
`--ladder`: tự gom slug free đang dùng ở [1]-[7] từ CHÍNH code (sentiment
_PROVIDERS, news _ANALYZE_MODELS, digest 2 bậc, brief defaults+fallback —
mirror `_all_live_slugs`), mỗi slug kèm tag điểm dùng để nhìn output biết
lỗi rơi vào tính năng nào; bỏ listing catalog cho nhanh (10 slug ~15s).
Test giữ: `--ladder` phải phủ đủ slug free sống + không probe slug chết
(test_probe_ladder_covers_all_free_live_slugs — fast suite). Nếp dùng:
sau sự cố key / provider deprecation / nghi model chập chờn → chạy
`python scripts/probe_models.py --ladder` trước khi đào sâu.

## 2026-07-30 (h) — Test ghi RÁC vào ledger thật (lộ nhờ --ladder + --show sau nửa đêm)

User chạy `--show` lúc 00:45 → ngày 30/07 hiện "4 call Anthropic Haiku,
3 OK" dù máy KHÔNG có key Anthropic. Truy ra: suite test (chạy ~00:0x)
fake HTTP bằng monkeypatch requests nhưng agent/digest vẫn gọi
`vnstock_llm_ledger.record` THẬT → usage giả 10/5 token từ fixture _Resp
đổ vào `data_warehouse/_meta/llm_ledger.json`, cost quy tiền như thật.
Trước giờ không ai thấy vì rác lẫn vào ngày đầy traffic thật; chạy suite
sau nửa đêm → ngày mới tinh chỉ có rác → lộ. Tái hiện được trong sandbox
(xoá ledger, chạy full suite → file mọc lại đúng chữ ký rác).

Fix tận gốc — autouse `_ledger_to_tmp_anywhere` trong tests/conftest.py
(cùng họ bài học `_no_llm_alert_anywhere` 22/07): redirect `_META` của
ledger về tmp_path cho MỌI test; fixture `_tmp_meta` cục bộ các file test
vẫn hoạt động (setattr đè tiếp, cũng về tmp). Verify sandbox: xoá ledger
→ full suite 1378 passed → file KHÔNG mọc lại. Lưu ý số liệu cũ trên máy
user: ngày 30/07 toàn rác (xoá được bằng pop key ngày trong JSON), ngày
29/07 lẫn rác của ~3 lần chạy suite tối đó — đọc số hôm đó nhớ trừ hao;
từ 30/07 (sau pull) ledger sạch.

### Đọc ledger 29/07 (forensics sau sự cố key — lưu để khỏi tra lại)

- `flash 9 (1 OK/8 fail)` + `flash-lite 8 fail`: KHÔNG phải sentiment [1]
  gãy fallback — là [2] analyze × 8 tin lúc key chết: `chat_complete` thử
  Gemini 2 LẦN mỗi tin (override flash rồi default flash-lite — hành vi
  cố ý của model_map) rồi mới rời sang Groq qwen (6 OK) / nemotron.
  Sentiment [1] không call gì vì 8 tin đã có cache SQLite.
- `Groq:llama-3.3-70b-versatile 1 fail` — SLUG CHẾT xuất hiện 1 lần:
  nhiều khả năng phát brief sáng 29/07 chạy TRƯỚC khi máy merge code mới
  (config cũ chưa qua _MODEL_MIGRATIONS). ⚠️ THEO DÕI: từ 30/07 trở đi mà
  còn dòng llama trong ledger → migration không cắn, soi brief_agents.json.
- `Anthropic:claude-haiku 1 OK` = rác test (máy KHÔNG có key Anthropic —
  call thật không thể OK); `Mistral:mistral-small 1 OK $0.0027` = agent
  brief mistral user đang bật trong config (trả phí nhẹ), hợp lệ.
- `Cerebras gpt-oss-120b 1 OK/5 fail` = trộn real + rác; món "digest
  chập chờn" vẫn nằm watch list cũ.

## 2026-07-30 (i) — Race header/thân brief (-60 vs -51) + 2 lỗ guard momentum

Brief close ép gửi 01:21 (đường `telegram close`, không guard giờ/marker)
lộ: header "🧭 Tâm lý … momentum -60/100" nhưng thân AI ghi "-51/100".
KHÔNG phải LLM bịa — 2 lần TÍNH composite ở 2 thời điểm: list `blocks`
của push_close_brief gọi `_market_sentiment_line()` (load_market_sentiment
= TÍNH LẠI từ cache, không phải đọc file lưu) TRƯỚC `_brief_snippet()`,
trong khi generate_brief bên trong snippet mới là bước refresh
news/overview → header dùng cache CŨ, thân ghim ctx MỚI. Chạy 18:00 bình
thường 2 lần tính cách nhau vài giây nên chưa từng lộ; chỉ lộ khi brief
chạy giữa lúc dữ liệu đang được làm tươi (1h sáng).

1. **Fix race**: push_close_brief + push_morning_brief sinh
   `ai_blk = _brief_snippet(...)` TRƯỚC rồi mới dựng header — header/regime/
   vnindex line đọc sau refresh, cùng nền cache với ctx. Test inspect-source
   (test_telegram) giữ thứ tự cho CẢ 2 hàm.
2. **Nới regex ghim momentum** (enforce_sentiment_consistency): bắt thêm
   (i) markdown quanh số "momentum **-51**/100", (ii) dạng chen tính từ
   "momentum tiêu cực (-51/100)" — giữ tính từ, ghim số trong ngoặc; không
   đụng dạng "(momentum -29/100)" (ngoặc trước momentum — test giữ). Đêm
   30/07 số -51 vốn ĐÚNG (trùng ví dụ prompt chỉ là trùng hợp), nhưng gặp
   ngày LLM bịa số ở dạng chen tính từ thì guard cũ trượt.
3. Ghi nhận brief 01:21 đọc CHẤT LƯỢNG TỐT: guard nhãn "(1 tuần)", cảnh
   báo stance GIẢM chèn đủ 2 block lệnh, macro/news/events canonical, sàn
   bias momentum -51 → Stance GIẢM đều hoạt động nhìn thấy được.

## 📌 TODO TỔNG HỢP 30/07 (chốt sau đêm verify điểm [6] + sự cố key + 2 fix brief)

### Việc CODE còn lại (chờ user ra lệnh)

1. **[8] Classifier** — điểm CUỐI của sơ đồ model 8 điểm: thêm đường Gemini
   flash cho batch ~1,700 mã (hết crash khi thiếu ANTHROPIC_API_KEY); giữ
   Claude làm opt-in khi có key. Free ~2 ngày quota/lần batch hoặc ~$0.5
   trên key Postpay.
2. **`vnstock_llm_ledger.py --test-alert`** — bắn 1 tin "(TEST)" qua đúng
   đường ống alert "LLM ladder DOWN" thật (token/chat_id/format) để verify
   chủ động thay vì chờ sự cố. Đã đề xuất, user chưa gật.
3. **PR về `main`** — khi user chốt (điều kiện: full suite xanh — máy thật
   đã 1388 passed; sau 2 fix đêm 30/07 sẽ là ~1390).

### VERIFY sau phát pipeline 18:00 gần nhất (liếc là xong)

4. **2 fix brief đêm 30/07 (i)**: momentum ở header "🧭 Tâm lý" phải KHỚP
   số trong thân AI Outlook (race đã đảo thứ tự + regex ghim đã nới).
5. **LLM audit trong pipeline**: `run_daily.log` phải có dòng
   `[audit] auditor=free:...` (mặc định BẬT từ 29/07); data sạch → kỳ vọng
   approved=True. Disapprove từ giờ là tín hiệu ĐỌC THẬT, không phải oan.
6. **Slug chết llama-3.3-70b-versatile**: ledger `--show` từ 30/07 trở đi
   KHÔNG được thấy dòng này (vết 29/07 = phát brief sáng trước khi merge).
   Còn thấy → migration không cắn, soi brief_agents.json máy đó.

### QUAN SÁT vài ngày rồi quyết (công cụ chính: ledger --show, sạch rác từ 30/07)

7. **A/B brief Gemini vs Groq** (~3-5 phiên): dashboard xem cả 2 bản mỗi
   chiều (Telegram chỉ nhận bản Gemini). Chấm: bám template đủ mục / văn
   VN tự nhiên / không bịa-lặp số / token+lỗi trong ledger. Gemini thắng
   rõ → tắt agent phụ trong ⚙️; ngược lại → đổi _AGENT_STRENGTH.
8. **Cerebras gpt-oss-120b digest**: soi OK/fail theo ngày trong --show +
   body lỗi ở dòng `[digest] ⚠ Cerebras` trong run_daily.log. Fail bền
   kiểu capacity → bỏ nấc khỏi _FREE_MODELS bậc 1 (Gemini+nemotron gánh).
9. **OpenRouter nạp $10** (trần :free 50→1,000 req/ngày, tiền thành credit
   không mất): CHỈ nạp khi cột "(N rate-limit)" các dòng OpenRouter > 0
   lặp lại nhiều ngày — hiện là nấc dự phòng, 50 req/ngày dư sức.
10. **Gemini flash 503 "high demand"**: đêm VN (cao điểm Mỹ) hay nghẽn —
    cascade tự đỡ, KHÔNG phải hỏng. Chỉ hành động nếu ban ngày giờ VN
    cũng nghẽn nhiều ngày liền → cân nhắc đổi nấc chính digest/brief.

### Ghi chú số liệu

- Ledger ngày 29/07 lẫn rác test (~3 lần chạy suite tối đó) — đọc trừ hao;
  ngày 30/07 user đã pop key rác, và từ fix conftest (8b3ef5a) test không
  ghi ledger thật nữa → số từ 30/07 tin được 100%.
- Đường ép gửi brief (`run.py telegram close`) KHÔNG có guard giờ/marker —
  chạy tay lúc nào cũng gửi + tự refresh nếu data cũ (nặng ~10-15 phút).
  Đường chuẩn nếp: `run.py brief` (sau 15:00 + chống trùng).

## 2026-07-30 (k) — Migration đổi cả TÊN hiển thị agent (lộ từ dashboard A/B)

Screenshot memory 29/07 của user: 3 dòng agent vẫn mang tên
"…Llama-3.3-70B" dù model bên dưới đã được _MODEL_MIGRATIONS đổi sang
qwen/gpt-oss — migration chỉ sửa `model`, bỏ quên `name` → dashboard A/B
gây nhầm đang so model gì. Fix trong load_agent_configs: khi đổi số model,
nếu tên đang NHẮC model cũ (helper `_name_mentions_model` — token ≥4 ký tự
của model cũ xuất hiện trong tên, vd "llama") thì thay bằng tên default
mới của type đó; tên user tự đặt (không nhắc model) giữ nguyên. Test
migration mở rộng: groq "Groq Llama-3.3-70B" → "Groq Qwen3.6-27B",
cerebras tên "Cerebras" (user chọn) giữ nguyên.

Đọc screenshot 29/07 (ghi để trả lời nhanh lần sau): 5 dòng đó là phiên
SỰ CỐ (key Gemini chết + 503 + đường ép gửi 01:21) — Gemini error (503),
Groq error, bản Telegram 01:21 thực chất do Mistral Small gánh (agent
mạnh nhất còn sống theo _AGENT_STRENGTH). KHÔNG dùng phiên này làm dữ
liệu A/B; A/B tính từ phiên 18:00 ngày 30/07 trở đi.

## 2026-08-06 — Brief cụt lên Telegram: output bị cắt được tính là THÀNH CÔNG

Close 06:53 (user ép gửi `telegram close` sáng 06/08) chỉ có TLDR + nửa
mục "Tổng kết phiên" rồi đứt ngang "và chỉ" — mất 8 mục sau. Giải phẫu:
Gemini flash "suy nghĩ" ĐỘNG, ngày data phức tạp nghĩ ~5k token trong
tổng budget 2800+3000 headroom → content còn ~600 token, đứt giữa câu
nhưng HTTP 200 + `finish_reason="length"` mà agent KHÔNG ĐỌC cờ này →
trả text cụt với error=None = "thành công" → thắng bản trọn vẹn của
agent yếu hơn, cơ chế "(dự phòng)" không kích hoạt (chỉ chạy khi agent
BÁO LỖI). Đây là lần 2 dính họ bug này (comment _BRIEF_MAX_TOKENS đã ghi
lần 2400→2800 hồi 13/07 — lần đó nâng trần, lần này vá tận gốc cờ cắt).

Fix (2 lớp):
1. **Mọi agent đọc cờ cắt**: OpenAI-compat (`finish_reason=="length"`) +
   Claude (`stop_reason=="max_tokens"`) → return LỖI "output bị cắt" +
   ledger fail (soi được qua --show). Cerebras/OpenRouter (vòng candidate)
   → thử model kế tiếp (kiểu nghĩ mỗi model khác nhau). Kết quả: bản cụt
   không bao giờ thắng nữa — generate_brief tự lấy dự phòng.
2. **Gemini `_THINK_HEADROOM` 3000 → 8000** — trần, không phải chi phí;
   3000 đã chứng minh không đủ. Test giữ không cho tụt lại (<8000).

Tests: truncation Gemini/Claude → ("", "bị cắt") + ledger fail; headroom
guard. Sandbox full 1382 passed. VERIFY máy thật: pull → phát brief kế
tiếp phải đủ mục; nếu ledger thấy `finish_reason=length` lặp lại nhiều
ngày ở Gemini → cân nhắc nâng headroom nữa hoặc đổi agent chính.

## 2026-08-06 (b) — AUDIT lỗi #2 CRITICAL: ghi parquet không nguyên tử → mất cả năm lịch sử

Phát hiện trong đợt audit đa-agent toàn repo (xem mục audit cùng ngày).
`updater._write_year` + `rollup._write_year` ghi THẲNG `pq.write_table` vào
`prices.parquet`: lệnh này cắt file thật về 0 byte rồi chép lại, nên process
chết đúng lúc (Task Scheduler ExecutionTimeLimit 120' kill CỨNG, máy tắt/ngủ
giữa pipeline — thường trực vì lịch dùng StartWhenAvailable, Ctrl+C, mất
điện) để lại file CỤT. Lần sau `_read_year` gặp file hỏng lại `except:
continue` → KHÔNG phân biệt "file hỏng" với "chưa có data".

**Đường mất data (đã tái hiện được bằng test)**: rollup chỉ có bar HÔM NAY →
existing rỗng → `combined = new_rows` → ghi đè canonical thành file hợp lệ
1 DÒNG → cả năm lịch sử bốc hơi, im lặng; rồi `_get_last_date` = hôm nay nên
updater KHÔNG BAO GIỜ refetch → mất vĩnh viễn. (Đường qua updater thì tự
lành: `_get_last_date` bỏ qua file không đọc được → rơi về năm trước →
fetch_from phủ nguyên năm → refetch đủ từ API.)

**Fix — module mới `vnstock_parquet_io.py`** (gom pattern đã có sẵn ở
`wss._flush_bars` + `write_pipeline_status`, thay vì chép lần thứ ba):
1. `write_table_atomic` — ghi `.tmp` rồi `os.replace` (nguyên tử: hoặc file
   cũ nguyên vẹn, hoặc file mới nguyên vẹn). Tên tmp mang pid+thread-id và
   KHÔNG kết thúc `.parquet` nên không bị glob nhặt nhầm thành data.
2. `read_year_frames(year_dir, *, strict)` — lưới bắt file hỏng, KHÁC NHAU
   theo caller vì khả năng tự lành khác nhau:
   * updater `strict=False`: cách ly file hỏng (`.corrupt-<ts>`) + cảnh báo
     rồi ĐI TIẾP — lần ghi ngay sau là bản đầy đủ vừa refetch → tự lành.
   * rollup `strict=True`: raise `CorruptWarehouseFile` → caller bỏ qua
     ticker-year + `stats["errors"] += 1`. CỐ Ý KHÔNG đổi tên file hỏng:
     giữ làm DÂY BẪY để mọi lần rollup sau đều dừng, cho tới khi updater
     (chạy TRƯỚC rollup trong `run.py sync`) cách ly + refetch. Đổi tên ở
     đây sẽ khiến lần rollup kế tiếp thấy thư mục rỗng rồi ghi đúng file
     1 dòng ta đang muốn tránh.
   * File KHÔNG canonical (Dropbox conflicted copy) hỏng → cách ly + đi
     tiếp ở CẢ HAI chế độ (nó không phải nguồn chân lý).

Tests (`tests/test_parquet_io.py`, 10 test, vào fast list): ghi hỏng giữa
chừng thì file CŨ nguyên vẹn + tmp được dọn; tên tmp không khớp glob
`*.parquet`; non-strict cách ly / strict raise-và-giữ-bẫy / conflicted copy;
2 test TÍCH HỢP qua `rollup_bars_file` thật — refuse-overwrite khi canonical
hỏng, và đường lành vẫn merge bình thường. Đã kiểm chứng RED: `git stash`
bỏ fix ra thì test tích hợp ĐỎ đúng chỗ (file hỏng bị ghi đè). Full suite
1392 passed.

**CÒN LẠI (chưa làm)**: `vnstock_warehouse._write_parquet` dùng
`pq.write_to_dataset(existing_data_behavior="delete_matching")` — xoá
partition rồi ghi, cùng họ rủi ro, và `_read_ticker` cũng nuốt lỗi trả
rỗng. Chỉ chạy ở bulk-load thủ công (không phải đường đêm) nên xếp sau.
Tương tự: `vnstock_macro` cache + cụm `_meta/*.json` (doctor) ghi chưa
nguyên tử — xem danh sách audit.

## 2026-08-06 (c) — AUDIT lỗi #1 CRITICAL: sandbox chiến lược thoát được → siết 2 lớp

`vnstock_strategy._validate_ast` chỉ chặn import / `_FORBIDDEN_NAMES` /
attribute DUNDER, trong khi `_safe_globals` phơi NGUYÊN module pandas. Vì
pandas có `import os` bên trong, chuỗi `pd.io.common.os.system('...')` gồm
TOÀN tên thường, không import, không dunder → lọt cổng kiểm và CHẠY LỆNH
SHELL THẬT (audit đã tái hiện, ghi được file proof). Cả `EXECUTOR`
(fast_mode) lẫn `STRICT_EXECUTOR` đều dính vì `_signal_worker` dựng CÙNG
`_safe_globals`. Đây là code do LLM sinh → lưu SQLite → chạy lại mỗi
backtest, không ai đọc; nó đọc được `.env` (toàn bộ API key), xoá được
warehouse, gửi được ra mạng. Nói cách khác: guard DUY NHẤT được giao việc
nhốt output LLM là guard duy nhất không làm được việc — trái hẳn triết lý
repo. `_FORBIDDEN_MODULES` khi đó là CODE CHẾT (khai báo, không ai dùng),
và comment ở EXECUTOR còn khẳng định sai "vẫn chặn file/network/import".

**Sandbox trước đợt này KHÔNG có một test nào** — lý do lỗ hổng sống lâu.

Fix — 2 lớp, lớp 2 là lớp bịt gốc:
1. **AST gate mở rộng** (`_validate_ast`): thêm chặn `_FORBIDDEN_MODULES`
   (nay là code SỐNG), `_FORBIDDEN_ATTRS` (ghi file `to_csv/to_pickle/
   to_parquet/…`, thực thi chuỗi `query/eval`, leo cây lớp `mro`, rò dunder
   qua chuỗi `format/format_map`, `system/popen/…`, `plot/style/attrs`), và
   — mặc định — mọi attribute NGOÀI danh sách TRẮNG `_ALLOWED_ATTRS`.
   Điểm mấu chốt: danh sách ĐEN sót một tên là LỖ HỔNG, danh sách TRẮNG sót
   một tên chỉ là BẤT TIỆN. Kill-switch `VNSTOCK_STRATEGY_STRICT_ATTRS=0`
   lùi về chế độ chỉ-chặn-đen (dùng tạm, KHÔNG để lâu).
2. **Khay thay module** (`_make_safe_namespace`): pd/np/math không còn là
   module thật mà là object chỉ chứa hàm trong `_PD_SAFE`/`_NP_SAFE`/
   `_MATH_SAFE` — members giữ trong CLOSURE, `__slots__=()` nên instance
   không mang thuộc tính nào, mọi truy cập rơi vào `__getattr__` và bị kiểm.
   `pd.io` đơn giản KHÔNG TỒN TẠI. Lớp này KHÔNG có kill-switch.

Phụ trợ:
* `audit_saved_strategies()` + CLI `python vnstock_strategy.py --audit-saved`
  — chạy `_validate_ast` lên chiến lược ĐÃ LƯU trong SQLite. Lý do: backtest
  bắt exception theo TỪNG CỬA SỔ, nên chiến lược active bị siết oan sẽ chết
  ÂM THẦM (0 trade → bị coi là tồi → retire). Lệnh này lộ mặt trước khi chạy
  đêm; exit 1 + hướng dẫn nếu chính chiến lược active bị từ chối.
* `_STRATEGY_PROMPT` thêm 3 dòng luật mới (đỡ tốn lượt retry của LLM).
* Sửa 3 comment/docstring khẳng định sai về mức bảo vệ; ghi rõ đây là
  sandbox "best effort" cho máy CÁ NHÂN, không phải hàng rào chống attacker.

Tests (`tests/test_strategy_sandbox.py`, 15 test, vào fast list): mỗi kỹ
thuật thoát 1 test (module traversal ở CẢ tầng AST lẫn runtime, df.to_*,
query/eval, mro, format, tên module trần), chống regress các chốt cũ, 2 test
ĐỐI CHỨNG rằng chiến lược mẫu trong prompt + idiom quant thông dụng vẫn chạy
(danh sách trắng không được siết tới mức phá code thật), 2 test cho CLI
audit. Kiểm chứng RED: chạy trước khi vá → 8/13 ĐỎ, gồm 2 test proof-of-
escape (lệnh shell chạy thật). Full suite 1407 passed.

**Việc cần làm trên máy thật**: sau `git pull` chạy
`python vnstock_strategy.py --audit-saved`. Nếu chiến lược ACTIVE bị từ chối
vì một API hợp lệ → báo để thêm tên đó vào `_ALLOWED_ATTRS` (đừng để
kill-switch bật lâu dài).

## 2026-08-06 (d) — Red-team PHÁ ĐƯỢC vòng vá 1: string-dispatch của pandas

Sau khi vá lỗi #1, thả 7 agent đối kháng vào chính bản vá (6 mũi tấn công +
1 mũi tìm false-positive, mỗi escape qua verifier độc lập chạy lại). Kết
quả: **6 escape THẬT** — bản vá vòng 1 chưa đủ.

**Gốc rễ**: `.apply`/`.agg`/`.aggregate`/`.transform` của pandas nhận TÊN
METHOD DẠNG CHUỖI rồi tự `getattr(obj, name)(...)` lúc chạy. Tên nằm trong
string literal (`ast.Constant`) nên MỌI kiểm tra trên `ast.Attribute` — kể
cả `_FORBIDDEN_ATTRS` vốn đã có sẵn 'to_csv' — đều không nhìn thấy:

    df.agg('to_csv', 0, '/path')            # ghi file, path + nội dung tuỳ ý
    df['close'].apply('to_csv', args=(p,))  # sạch sẽ, KHÔNG cả exception

Đã chứng minh ghi được vào /tmp, thư mục repo, $HOME, và **site-packages**
(file `.pth` ở đó = code chạy mỗi lần khởi động Python = RCE bền vững). Cả
`EXECUTOR` lẫn `STRICT_EXECUTOR` đều dính. Lưu ý bài học: `df` là DataFrame
THẬT truyền vào `signal()`, KHÔNG qua khay — nên lớp 2 (khay pd/np/math)
không đỡ được đường này; an ninh thực chất dựa vào tầng AST.

Bẫy phụ đáng ghi: `df.agg('to_csv', …)` có ném exception SAU đó (to_csv trả
None rồi agg hậu xử lý) → "có exception" KHÔNG có nghĩa là an toàn, file đã
ghi xong trước khi lỗi bật ra.

**Vá vòng 2** — `_DISPATCH_ATTRS` + `_check_dispatch_call`: với nhóm
{apply, applymap, agg, aggregate, transform, map, pipe}, đối số ĐẦU BẮT BUỘC
là `lambda` viết thẳng trong code (đã qua AST soi), và không keyword nào
được là chuỗi hằng. Cố ý KHÔNG chọn hướng "cấm chuỗi trông giống tên nguy
hiểm" — chuỗi ghép động `'to_' + 'csv'`, biến chuỗi, hay tên lấy từ
`params` (params do LLM tune, cũng là input không tin được) sẽ lách ngay.
Luật áp theo TÊN METHOD nên phủ luôn mọi đối tượng trung gian: groupby /
rolling / resample / ewm / expanding. `.rolling(n).apply(lambda …)` — idiom
quant hợp lệ — vẫn chạy.

**Vá kèm: 28 FALSE POSITIVE** (mũi tương thích viết 12 chiến lược thật →
**6/12 CHẾT** vì danh sách trắng vòng 1 quá tay). Nhóm lớn:
* `df.close` (truy cập cột kiểu attribute) — thiếu là chết ngay dòng đầu.
* `_safe_builtins` thiếu `pow` và MỌI lớp exception → chiến lược bọc
  try/except (nếp quant chuẩn) chết với NameError.
* Alias đầy-đủ-tên: `subtract/multiply/divide/kurtosis/to_frame`.
* numpy còn thiếu: `argsort/average/gradient/ptp/arctan/count_nonzero/
  convolve/isclose/roll/nanpercentile/searchsorted/…`.
* **Bất nhất 2 tầng**: `power/greater/less/equal` có trong khay np nhưng bị
  AST chặn trước khi tới; ngược lại `unique/degrees/append/hypot` qua AST
  nhưng khay thiếu → chết ở runtime. Nay có test cấu trúc
  `test_ast_allowlist_and_runtime_trays_are_consistent` bắt buộc mọi tên
  trong khay phải nằm trong danh sách trắng AST.

Tests: 57 test trong `tests/test_strategy_sandbox.py` (từ 15 → 57), gồm 7
test string-dispatch, 11 biến thể né luật (params/ghép chuỗi/f-string/list/
lambda lồng/groupby/rolling/resample/ewm/expanding), 20 idiom quant đối
chứng, test cấu trúc 2 tầng. Kiểm chứng RED trước khi vá vòng 2: 30 đỏ.
Full suite 1438 passed.

**Bài học quy trình**: fix bảo mật KHÔNG được tin bản thân — vòng vá 1 trông
rất chắc (13 test xanh, 8 đường tấn công đã chặn) mà vẫn thủng ở một cơ chế
không ai nghĩ tới. Đối kháng độc lập + verifier chạy lại là bắt buộc.

## 2026-08-06 (e) — Red-team PHÁ TIẾP vòng 2: bound method là object hạng nhất

Vòng đối kháng thứ 2 (4 mũi) lại phá được: **5 escape thật**. Luật vòng 2
`_check_dispatch_call` kiểm TẠI CHỖ GỌI — chỉ chạy khi `node.func` là
`ast.Attribute` có `.attr ∈ _DISPATCH_ATTRS`. Nhưng bound method trong
Python là OBJECT HẠNG NHẤT, nên chỉ cần tách lời gọi khỏi hình dạng đó:

    w = df.agg;  w('to_csv', 0, path)      # node.func = ast.Name
    [df.agg][0]('to_csv', 0, path)          # node.func = ast.Subscript
    (lambda f: f('to_csv', 0, path))(df.agg)

Red-team ghi lại được file tuỳ ý (path + NỘI DUNG do attacker chọn, dùng
`pd.DataFrame` từ chính khay) và **.pth vào site-packages** = RCE bền vững.
Cùng đường đó chạm được cả `to_json`/`to_pickle`/`query` (đều nằm trong
`_FORBIDDEN_ATTRS`) lẫn dunder `__len__` — vì tên method là CHUỖI lúc chạy,
mọi hàng rào cú pháp đều vô nghĩa.

**Vá vòng 3 — đổi luật từ "chỗ gọi" sang "THAM CHIẾU"**: `_validate_ast` nay
đi 2 lượt. Lượt A gom các `ast.Attribute` dispatch nằm ĐÚNG vị trí callee của
lời gọi hợp lệ (đối số đầu là lambda). Lượt B: mọi `ast.Attribute` mang tên
dispatch KHÔNG nằm trong tập đó → từ chối. Tức tên `.agg/.apply/…` không bao
giờ được "cầm ra" như một giá trị. Đã tự kiểm 10 dạng gián tiếp (gán biến,
try/except, list, tuple, dict, đối số lambda, default arg, giá trị trả về,
`sorted(key=)`, DataFrame tự dựng): **0 escape, 0 file ghi được**; đối chứng
`rolling(5).apply(lambda …)` và `.agg(lambda …)` vẫn chạy.

Test 57 → 68. Full suite 1460 passed.

### ⚠️ GIỚI HẠN CÒN LẠI — đọc trước khi tin sandbox này

Ba vòng đối kháng cho thấy: **sandbox bằng phân tích cú pháp trên một đối
tượng pandas THẬT là leaky by design**. `df` truyền vào `signal()` không qua
khay, mà bề mặt pandas quá rộng (bất kỳ API nào nhận tên hàm dạng chuỗi đều
là getattr trá hình). Mỗi vòng vá bịt được lớp cú pháp mà vòng trước bỏ sót,
nhưng KHÔNG có gì bảo đảm đã hết.

Mức bảo vệ hiện tại (đúng thực tế, không nói quá):
* CHẶN được: mọi kỹ thuật đã biết qua 3 vòng đối kháng có test giữ.
* KHÔNG bảo đảm: đường thoát chưa ai nghĩ ra, nhất là khi nâng phiên bản
  pandas/numpy (API mới có thể mở lại string-dispatch ở chỗ khác).

Muốn CHẮC thì phải đổi kiến trúc, không phải siết thêm regex:
1. Truyền vào `signal()` một PROXY chỉ-đọc thay vì DataFrame thật (chặn tận
   gốc mọi method của pandas), hoặc
2. Chạy chiến lược trong tiến trình RIÊNG hạ quyền (user riêng/seccomp/
   container), coi code là thù địch thay vì cố lọc nó.
Cả hai đều là việc lớn — ghi vào TODO, chưa làm.

**Nếp mới**: nâng pandas/numpy → chạy lại `tests/test_strategy_sandbox.py`
TRƯỚC khi tin; thêm API mới vào `_ALLOWED_ATTRS` → cân nhắc nó có nhận tên
hàm dạng chuỗi không (nếu có: thêm vào `_DISPATCH_ATTRS`).

## 2026-08-06 (f) — `--audit-saved` trên máy thật: 21/29 qua, và lộ bug lưu code hỏng

Chạy `python vnstock_strategy.py --audit-saved` trên máy user sau khi siết
sandbox: **29 chiến lược, 21 qua, 8 bị từ chối — KHÔNG cái nào đang active**
(toàn `retired`/`draft`) → pipeline đêm an toàn, không cần đụng kill-switch.

Quan trọng: 8 cái đó KHÔNG phải do luật mới siết oan. Lý do từ chối toàn là
`SyntaxError` (unterminated string literal / invalid syntax) và `Import
statements are not allowed` — hai luật CÓ TỪ ĐẦU. Tức là chúng chưa bao giờ
chạy được, chỉ nằm chiếm chỗ trong kho.

**Bug lộ ra**: sao code hỏng lại vào được SQLite? Cả `_cold_start` lẫn
`_do_revise` gác bằng `if err and not code: continue`. Nhưng
`_parse_params_and_code` LUÔN trả code non-empty (không parse được thì trả
nguyên text), nên ca hay gặp nhất — LLM trả code hỏng — có `err` mà `code`
vẫn khác rỗng → **lọt qua**, được backtest (mọi cửa sổ raise → 0 trade) rồi
LƯU vào DB. Sửa: `if err: continue` ở cả 2 nhánh (có lỗi = không dùng được,
chấm hết). 2 test mới: code hỏng KHÔNG được lưu + đối chứng code hợp lệ vẫn
lưu bình thường.

Ghi chú: nhóm `SyntaxError` nhiều khả năng là output LLM bị CẮT (agent
`Groq Llama-3.3-70B` — slug đã chết, thời điểm 04→08). Fix `finish_reason=
length` hôm nay (mục 2026-08-06 đầu tiên) đã chặn đường đó từ gốc: output cụt
nay trả LỖI nên `if err: continue` sẽ bỏ luôn.

8 dòng rác kia vô hại (retired/draft, không bao giờ được promote vì 0 trade
< MIN_TRADES_TO_VALIDATE). Muốn dọn thì xoá tay theo id trong SQLite — chưa
làm, không cần thiết.

Full suite 1462 passed.

## 2026-08-06 (g) — Test sandbox XANH GIẢ trên Windows (đường dẫn thành escape)

Máy user chạy full suite: 1 đỏ —
`test_module_traversal_blocked_even_if_validator_skipped` với
`SyntaxError: (unicode error) 'unicodeescape' … truncated \UXXXXXXXX`.
Nguyên nhân: test nhúng `tmp_path` thẳng vào SOURCE Python, mà trên Windows
đường dẫn là `C:\Users\…` → `\U` bị đọc thành escape unicode hỏng.

**Cái đỏ đó chưa phải vấn đề lớn nhất.** Test đó đỏ vì nó gọi `exec()`
TRỰC TIẾP (không bọc `pytest.raises`). Các test tấn công CÒN LẠI đều bọc
`pytest.raises(Exception)` — mà SyntaxError CŨNG là Exception → chúng "xanh"
nhờ payload hỏng cú pháp chứ KHÔNG phải nhờ sandbox chặn. Tức trên Windows,
một phần bộ test bảo mật vừa viết là **XANH GIẢ**, không kiểm gì cả.

Fix 3 lớp:
1. `_pypath(p)` = `p.as_posix()` — mọi chỗ nhúng đường dẫn vào source dùng
   dấu `/` (hợp lệ trên cả Windows).
2. **Lưới chống tái diễn**: `_wrap()` nay `compile()` payload ngay khi dựng.
   Payload hỏng cú pháp → SyntaxError ném ra NGOÀI mọi `pytest.raises` →
   test đỏ ầm ĩ thay vì xanh giả. Đã tự kiểm bằng cách giả lập đường dẫn
   Windows: lưới bắt đúng.
3. Payload traversal đổi `os.system('touch …')` → `os.makedirs(…)`: `touch`
   KHÔNG tồn tại trên Windows nên test cũ ở đó vốn đã yếu (dù sandbox có
   thủng thì file cũng không được tạo → vẫn xanh). `makedirs` chạy trên cả
   2 hệ và vẫn chứng minh chạm được `os` thật.

**Bài học chung**: test bảo mật dùng `pytest.raises(Exception)` rất dễ xanh
giả — exception nào cũng làm nó xanh, kể cả lỗi của chính test. Khi viết
test kiểu "phải bị chặn", luôn kèm một khẳng định độc lập về TÁC DỤNG PHỤ
(ở đây: `assert not proof.exists()`) và bảo đảm payload hợp lệ về cú pháp.

Full suite 1462 passed (sandbox Linux). ✅ **Máy user (Windows) xác nhận
1473 passed** — xanh hết và lần này là xanh THẬT (payload hợp lệ cú pháp,
lưới `compile()` trong `_wrap` đứng chắn tái diễn).

## 2026-08-06 (h) — ĐỔI KIẾN TRÚC sandbox: khoá NĂNG LỰC thay vì lọc cú pháp

Ba vòng red-team cho một kết luận rõ: lọc cú pháp (AST) trên một đối tượng
pandas THẬT là phòng thủ rò rỉ theo bản chất. Mỗi vòng vá bịt được lớp trước,
vòng sau lộ lớp mới (`pd.io.common.os` → `df.agg('to_csv')` → `w = df.agg`).
Nay làm phần đã ghi TODO: đổi cách đánh.

**Ý tưởng**: thay vì hỏi "câu lệnh này có nguy hiểm không?", khoá thẳng NĂNG
LỰC của tiến trình chạy code — không mở được file, không gọi shell, không mở
socket. `df.to_csv(path)` chết ở ĐÚNG bước ghi file, bất kể được gọi bằng cú
pháp nào. Đo thực nghiệm trước khi làm: khoá `builtins.open` + `io.open` chặn
sạch to_csv / to_pickle / to_json / agg-dispatch / np.save / tofile.

**`vnstock_sandbox_runtime.py` (mới)**
* `lockdown()` — vô hiệu hoá 97 hàm trên 7 module: `open` (builtins + io),
  `os`/`posix`/`nt` (system, popen, remove, rename, exec*, spawn*, fork,
  open, …), `shutil`, `subprocess`, `socket`, `webbrowser`, `ctypes`, và
  method ghi của `pathlib.Path`. Vá NGAY TRÊN module object nên mọi đường
  vòng tới nó (kể cả `pd.io.common.os`) đều nhận bản đã khoá.
* `serve()` — worker nói chuyện bằng pickle có tiền tố độ dài qua
  stdin/stdout. CỐ Ý dùng subprocess chứ KHÔNG multiprocessing: `spawn`
  re-import `__main__` ở tiến trình con — chạy từ dashboard Streamlit thì
  con sẽ chạy lại cả app.
* `minimal_env()` — worker nhận env TỐI THIỂU, không kế thừa `.env` → API key
  không bao giờ vào tới tiến trình chạy code lạ.

**`IsolatedExecutor` (vnstock_strategy)** — MỘT worker phục vụ mọi lần gọi
(cache hàm signal đã compile theo code). Đo: 0.6s lần đầu (dựng), rồi
**0.9 ms/lần** — không còn đánh đổi "tốc độ đổi cách ly" như bản
`fast_mode=True` cũ. Worker chết → tự dựng lại. `EXECUTOR` VÀ
`STRICT_EXECUTOR` nay đều trỏ về đây (trước "strict" chỉ là spawn mỗi lần
gọi — CÙNG quyền, nên thực chất không cách ly gì; red-team đã chứng minh nó
dính y hệt bản fast). Kill-switch `VNSTOCK_STRATEGY_ISOLATION=0`.

**3 bẫy đã dính khi làm, ghi lại kẻo lặp**
1. Khoá `_io.open` = khoá luôn cơ chế import của CPython → `import` và
   lazy-import trong pandas chết sạch. CHỈ vá `builtins.open` + `io.open`
   (có test guard `test_io_open_deliberately_not_patched`).
2. `scrub_secrets_from_env()` chạy SAU khi khoá `os.*` thì `del os.environ[k]`
   (gọi xuống `os.unsetenv`, đã bị khoá) ném lỗi rồi bị nuốt — hàm trả số
   ĐẸP mà không xoá được gì. Nay dọn TRƯỚC, và đếm số xoá THẬT.
3. `except Exception: return False` trần trong `_spawn` nuốt mất một
   NameError của chính nó (thiếu `import sys`) rồi âm thầm tụt về in-process
   — đúng kiểu hỏng nguy hiểm nhất của một lớp bảo mật. Nay ghi lại lý do và
   in cảnh báo (một lần/executor, không phải mỗi vòng backtest).

**Tests** `tests/test_sandbox_isolation.py` (21 test, vào fast list): 12 đường
thoát chạy THẲNG bằng Python trong tiến trình đã lockdown — **không qua AST**,
đó mới là phép thử thật ("nếu mai có người lách AST lần thứ 4 thì sao?"); test
pandas/import vẫn chạy được sau khoá; env tối thiểu không mang bí mật; worker
tái dùng/tự hồi phục/kill-switch; chốt EXECUTOR mặc định là bản cách ly.
Full suite 1483 passed.

**Lớp AST vẫn giữ** làm hàng rào 1 (bắt sớm, rẻ, không tốn IPC). Nếu sau này
danh sách trắng attribute còn gây false positive, có thể NỚI nó ra — vì đã
có tầng năng lực làm backstop thật. Ghi để nhớ lựa chọn đó.

**Còn lại**: đây vẫn là phòng thủ trong-tiến-trình, không phải seccomp/
container. Muốn cứng hơn nữa phải hạ quyền ở tầng OS (user riêng /
AppContainer / container) — việc lớn hơn nhiều, chưa làm.

### Bổ sung (h1) — tự dò ra lỗ `FileIO` ngay sau khi dựng tầng năng lực

Tự thử các đường I/O cấp thấp trên chính bản vừa làm: **`io.FileIO('x','w')`
ĐỌC VÀ GHI được file mà KHÔNG đi qua `open`** → thoát sạch tầng năng lực,
và tệ hơn: đó là đường ĐỌC THẲNG `.env` (lộ API key) chứ không chỉ ghi.

Vá không đơn giản vì `_io.FileIO` / `_io.open_code` CHÍNH LÀ thứ importlib
dùng để nạp module — chặn cứng thì `import` chết sạch (đã đo: pandas không
import nổi). Giải: **cổng theo CHÍNH SÁCH** `_guarded_fileio` — chỉ cho ĐỌC
file có đuôi kiểu module (.py/.pyc/.so/.dll/.zip/.egg/.whl), cấm mọi thao
tác ghi, cấm fd dạng số, cấm mọi đuôi khác. Import vẫn chạy; `.env` thì
không đọc được.

Bẫy phụ: `open_code(path)` chỉ nhận MỘT đối số — wrapper truyền kèm `mode`
gây TypeError giết cơ chế import (đã dính, có cờ `takes_mode`).

Kiểm lại sau vá: `os.open`, `np.fromfile`, `pd.read_csv`, `np.save`,
`ndarray.tofile`, reimport/reload `os` — chặn hết, không file nào rò; import
mới + pandas/rolling/ewm/groupby vẫn chạy. 5 test mới (26 test trong file
cách ly). Full suite 1488 passed.

## 2026-08-06 (i) — VÒNG 4 red-team phá lớp setattr → thêm AUDIT HOOK (PEP 578)

Thả 4 mũi đối kháng vào tầng khoá năng lực vừa dựng, với giả định "AST đã bị
vượt". Kết quả: **5 escape thật**, và tất cả cùng MỘT bản chất —
**không thể GIẤU thứ gì khỏi code Python chạy cùng tiến trình**:

1. `del sys.modules['posix']; import posix` → CPython dựng lại module C từ
   snapshot gốc (m_copy) → `system/popen/open/write/fork/kill` phục hồi hết
   trong một dòng. `setattr` của lockdown không đụng tới cache đó.
2. `os.posix_spawn(...)` → tên exec HIỆN ĐẠI bị bỏ sót trong deny list.
3. `_io.open(...)` → chính chỗ cố ý không vá (vì sợ chết import).
4. `tokenize._builtin_open`, `bz2._builtin_open`, `tarfile.bltn_open`,
   `numpy.lib._datasource._open` → các module stdlib/numpy giữ THAM CHIẾU
   tới `open` GỐC từ lúc import; setattr sau đó không với tới.
5. `type(sys.__stdout__.buffer)` → lấy lại class `_io.FileIO` GỐC qua một
   stream đang mở, vượt sạch cổng `_guarded_fileio` (vốn chỉ đè attribute).

**Kết luận thẳng**: `setattr` lên module object là lớp phòng thủ MỀM — tốt
cho thông báo lỗi và chặn lỗi vô ý, KHÔNG phải hàng rào.

**LỚP B — audit hook (PEP 578)** khác về CHẤT: sự kiện do CPython phát ra
TỪ BÊN TRONG chính primitive ở tầng C, nên tham chiếu cũ / module vừa import
lại / class lấy qua `type()` đều đi qua nó như nhau. Và `sys.addaudithook`
CỐ Ý không có API gỡ (`sys.removeaudithook` không tồn tại — có test guard).

* `_DENY_EVENTS`: os.system/exec/posix_spawn/spawn/fork/kill/remove/rename/
  chmod/link/truncate…, subprocess.Popen, socket.*, ctypes.*, shutil.*,
  webbrowser.open, urllib.Request, mmap/fcntl, tempfile.mk*.
* Sự kiện `open`: cấm MỌI thao tác ghi; chỉ cho ĐỌC file module (.py/.pyc/
  .so…) hoặc file nằm trong prefix Python (stdlib + site-packages + zoneinfo).
  Thư mục repo KHÔNG thuộc prefix → `.env` bị chặn. Đây là điểm mấu chốt.
* CỐ Ý KHÔNG chặn `os.listdir`/`scandir`/`glob` (cơ chế import cần, mà chúng
  chỉ liệt kê TÊN — nội dung đã khoá ở `open`; chặn thì gãy import, đã dính),
  và không chặn `exec`/`compile`/`marshal.loads` (worker PHẢI exec code
  chiến lược; importlib giải mã .pyc bằng marshal — chúng không tự cấp năng
  lực nào, mọi năng lực thật đều qua sự kiện phía trên).
* Hook cài SAU CÙNG trong `lockdown()`: các `setattr` của lớp A tự chúng phát
  sự kiện audit, cài hook trước là tự chặn chính mình.

Đo lại sau vá: **16/16 đường thoát bị chặn, 0 file rò**, gồm cả 5 vector vòng
4 lẫn các vector vòng 1-3; công việc hợp lệ (import mới, pandas rolling/ewm/
groupby, `rolling.apply(lambda)`) vẫn chạy; 300 phép rolling tốn 0.03s (chi
phí ~0 — số học không phát sự kiện audit).

Tests: 39 test trong `tests/test_sandbox_isolation.py` (9 vector vòng 4 +
đọc .env + hook-không-gỡ-được + không-chặn-tay + guard listdir). Full suite
1501 passed.

**Bẫy test tự dính**: `modules.pop('posix', None) or __import__('posix')...`
— `pop` trả module (truthy) nên `or` short-circuit, payload KHÔNG hề chạy mà
test vẫn "xanh". Dùng `;` thay `or`. Cùng họ bài học "xanh giả" hôm nay.

### Mức bảo vệ hiện tại — nói cho đúng

Có 3 lớp: (1) AST gate, (2) setattr lockdown, (3) audit hook C-level. Lớp 3
là lớp thật. Với threat model THỰC TẾ của repo này — code do LLM sinh, không
có kẻ tấn công chủ đích — mức này là đủ và còn dư.

Vẫn KHÔNG phải hàng rào tuyệt đối trước attacker chủ đích: hook chạy trong
cùng tiến trình, và một khai thác ở tầng C (ctypes đã chặn, nhưng lỗi
interpreter/extension thì không) về lý thuyết vẫn qua được. Muốn tuyệt đối
thì phải cách ly ở tầng OS (container/seccomp/user riêng) — vẫn nằm TODO.

### Bổ sung (i1) — máy Windows đỏ 2 test: chính sách cấm-ghi chặn luôn `.pyc`

Máy user chạy full suite sau bản audit hook: **1510 passed, 2 failed** — cả
hai đều thuộc nhóm "công việc hợp lệ phải chạy"
(`test_import_machinery_survives_fileio_gate`, `test_audit_hook_allows_legit_work`).

Nguyên nhân: import một module CHƯA có `.pyc` khiến Python `mkdir
__pycache__` rồi ghi `.pyc` — chính sách cấm MỌI thao tác ghi nên import
chết. Sandbox Linux không lộ vì stdlib ở đó đã cache sẵn `.pyc`; máy user
có module chưa cache nên gãy. (Đã tái hiện được bằng module mới tinh:
`SandboxViolation: posix.mkdir bị khoá`.)

Thuốc: `sys.dont_write_bytecode = True` NGAY TRONG `lockdown()`, trước khi
khoá. `minimal_env()` vốn đã đặt `PYTHONDONTWRITEBYTECODE=1` nên worker
THẬT chưa từng dính — nhưng bảo đảm an toàn không được phụ thuộc biến môi
trường, ai gọi `lockdown()` cũng phải chạy được. 2 test mới giữ (import
module chưa cache + cờ dont_write_bytecode). Full suite 1503 passed.

**Bài học lặp lại lần 2 trong ngày**: sandbox Linux KHÔNG đại diện cho máy
Windows của user (lần 1: đường dẫn `C:\Users` thành escape `\U`). Việc siết
môi trường luôn phải thử ở cả hai, hoặc ít nhất dựng lại điều kiện của máy
kia (ở đây: xoá `__pycache__` rồi import).

✅ **CHỐT: máy user (Windows) 1514 passed** — toàn bộ đợt sandbox 4 vòng đối
kháng khép lại, xanh thật trên cả 2 hệ.

## 2026-08-06 (j) — Dọn nốt 6 lỗi mức HIGH của đợt audit (5 commit theo chủ đề)

Làm cùng lúc vì 6 lỗi nằm ở 6 module không đụng nhau; tách 5 commit để
revert độc lập được.

**1-2. WSS volume tích luỹ** (2 bug cùng họ với vụ 78× trên AAA)
* `_pick(...) or 0` GỘP hai ca khác hẳn: "phiên chưa khớp lệnh nào" và
  "bảng giá thiếu cột volume tick này". Ca 2 ghi đè baseline = 0 → tick KẾ
  TIẾP tính delta = accum CẢ PHIÊN. Nay giữ `None` để phân biệt; thiếu số
  liệu thì KHÔNG đụng baseline, delta = 0.
* `_handle_tick` rơi về `tick["volume"]` khi không có `_delta_volume` — mà
  3 nguồn tick khác price_board đều đặt số TÍCH LUỸ vào đó (fallback
  intraday, index, và futures với `total_session_vol`), vòng poll ~1s cộng
  lại MỖI LẦN. Nay mặc định an toàn: chỉ tick TỰ KHAI delta mới đóng góp
  volume. Sửa 1 chỗ, phủ cả 3 nguồn lẫn nguồn thêm sau này.

**3. Đơn vị giá mã penny khi rollup** — `fix_units` chỉ chạm `close > 1000`
nên giá thô 300-900 VND (rất nhiều mã UPCOM) vào kho thành 300-900 NGHÌN
VND, sai 1000×, không lưới nào bắt. `_normalize_units` so với chính LỊCH SỬ
của mã: giá một phiên không thể nhảy ≥100× (biên độ sàn ±15%) nên tỉ lệ cỡ
đó chỉ có thể là lệch đơn vị. Mã mới niêm yết (chưa có lịch sử) giữ nguyên.

**4. `enforce_vnindex_change` đọc cửa sổ từ chuỗi SAI** — nhánh 2 khớp trên
`out` (đã bị nhánh 1 đổi ĐỘ DÀI) nhưng đọc ngữ cảnh từ `text` GỐC. Dựng lại
được ca thật: nhánh 1 rút "giảm 111,222.333%" → "tăng 0.31%" (lệch 7 ký tự)
→ cửa sổ mất chữ "chỉ số" → guard bỏ qua đúng chỗ phải sửa. Chiều ngược lại
còn tệ hơn: cửa sổ lệch có thể VÔ TÌNH thấy "vnindex" ở mệnh đề GTGD rồi
guard tự tay ghi đè số GTGD.

**5. Sentiment đóng băng "neutral"** — tin không provider nào chấm được vẫn
bị ghi cache SQLite, lần sau hash đã có nên KHÔNG BAO GIỜ chấm lại dù ladder
đã hồi. Nay chỉ cache tin CÓ model (alert ladder-down vẫn chạy trước, không
đổi).

**6. Exit code — ⚠️ ĐỔI HÀNH VI PIPELINE (có ý)**
* `vnstock_updater.py` LUÔN exit 0 → cổng `if updater != 0` chỉ bắt CRASH;
  "chạy sạch" và "500/1700 mã lỗi" cùng một mã thoát. Nay 2 = không mã nào
  update được, 1 = có mã lỗi nhưng phần lớn xong, 0 = sạch. Ngưỡng theo TỈ
  LỆ (vài mã hủy niêm yết lỗi là chuyện thường). **`cmd_sync` phải cập nhật
  theo** — quên chỗ này thì 1 mã lỗi = fail cứng cả pipeline, hỏng nặng hơn
  bug gốc (có test giữ).
* `cmd_test` trả thẳng exit code pytest, mà pytest dùng 1 cho "có test
  fail" — trong `run.py all` số 1 = "cảnh báo, chạy tiếp" → pipeline đêm vẫn
  train và ĐẨY BRIEF bằng code đang đỏ, trái quy ước "badge đỏ = không
  merge/deploy". Nay test đỏ → 2 (dừng).
* `cmd_all`: `rc == 2` để lọt mọi mã khác (pytest 3/4/5, mã âm khi tiến
  trình bị signal giết, bug trả 255) → "thành công im lặng". Nay chỉ 0 và 1
  hợp lệ.

**Bẫy phát sinh khi làm — nhiễm chéo giữa test module**: 4 test mới ĐỎ khi
chạy cả suite nhưng XANH khi chạy riêng. Thủ phạm:
`tests/test_dashboard.py` đặt `sys.modules["vnstock_wss"] = MagicMock()` ở
CẤP MODULE — có hiệu lực ngay lúc pytest THU THẬP nên nhiễm mọi file, bất
kể thứ tự. Mock đó là TÀN DƯ (file này không hề import vnstock_dashboard,
chỉ test bản replica). Đã gỡ + thêm lưới
`test_no_repo_module_is_replaced_by_a_mock`. Đây là kiểu lỗi tốn thời gian
nhất để lần ra — nhớ nghi ngờ nó khi "chạy riêng thì xanh".

Tests: 18 test mới (`tests/test_audit_high_fixes.py`, vào fast list).
Full suite 1520 passed.

### Việc cần soi trên máy thật sau khi pull
* Phát `run.py sync` đầu tiên: nếu có mã lỗi sẽ thấy dòng cảnh báo tỉ lệ %
  và pipeline VẪN chạy tiếp (rc=1). Nếu thấy fail cứng rc=2 → kiểm nguồn
  data, đó là tín hiệu thật.
* Phiên WSS đầu tiên: soi `_live/bars_*.parquet` — volume index/futures
  giờ về 0 (đúng thiết kế), volume cổ phiếu vẫn có qua delta.

### Bổ sung (j1) — máy Windows đỏ 4 test: `vnstock_wss` tạo thư mục lúc IMPORT

Máy user: `1528 passed, 4 failed`, cả 4 chết ngay ở dòng `import vnstock_wss`
với `FileExistsError [WinError 183] ... data_warehouse\_live`.

Cơ chế: `vnstock_wss.py` có `LIVE_DIR.mkdir(parents=True, exist_ok=True)`
chạy ở **cấp module**. Điều bất ngờ: `exist_ok=True` VẪN ném
`FileExistsError` — pathlib chỉ nuốt lỗi khi `self.is_dir()` trả True, mà
`Path.is_dir()` nuốt MỌI OSError của `stat` (ACL chặn, reparse point hỏng,
file đang bị khoá) rồi trả False. Tức là **thư mục có thật vẫn làm import
chết**. Và vì side effect nằm ở cấp module, hỏng một lần là cả module không
dùng được — kéo theo dashboard lẫn test.

Vì sao chỉ giờ mới lộ: trước đây KHÔNG test nào import `vnstock_wss` thật
(`tests/test_wss.py` cố tình dùng bản replica — chính điều audit đã chê).
Test mới hôm nay là lần đầu import thật, và nó lộ ngay trên máy user.

Fix: bỏ mkdir ở cấp module; thêm `_ensure_live_dir()` (cố gắng hết sức,
KHÔNG BAO GIỜ ném) gọi tại các chỗ GHI (`_atomic_write_json`, `_flush_bars`).
2 test giữ: import sống được khi LIVE_DIR là FILE, và guard cấm quay lại
kiểu mkdir cấp module. Full suite 1523 passed.

**Bài học lặp lại lần 3 trong ngày**: sandbox Linux không đại diện máy
Windows (1: đường dẫn thành escape `\U`; 2: `.pyc` chưa cache; 3: `is_dir()`
False do stat lỗi). Và: side effect ở cấp module là mìn — mọi thao tác I/O
lúc import phải bọc, hoặc dời xuống chỗ dùng.

⚠️ **User nên kiểm tra thêm**: nếu `data_warehouse\_live` thật sự không phải
thư mục dùng được thì WSS sẽ không ghi được bar. Chạy:
`python -c "import pathlib; p=pathlib.Path('data_warehouse/_live'); print(p.exists(), p.is_dir(), p.stat())"`

## 2026-08-06 (k) — 🚨 PHÁT HIỆN THẬT: `data_warehouse/_live` là FILE, WSS chết câm 1 tháng

Truy tiếp cái đỏ (j1) trên máy user thì lộ ra vấn đề PRODUCTION, không phải
chuyện test:

    exists: True | is_dir: False
    st_mode=33206 (0o100666 = FILE THƯỜNG), st_size=0
    ctime = mtime = 2026-07-07 03:13:22

`data_warehouse/_live` KHÔNG phải thư mục — nó là một **file rỗng 0 byte**.
Thời điểm tạo trùng khít sự cố Dropbox 2 máy đã ghi trong journal
(entry "2026-07-07 incident: Dropbox spawned conflicted copy…").

**Hệ quả suốt một tháng**: WSS không ghi nổi `quote_*.json` lẫn
`bars_*.parquet` nào. Không có tín hiệu nào báo, vì mọi đường ghi đều nằm
trong `try/except` (cố ý — để lỗi ghi không kéo sập vòng poll). Triệu chứng
duy nhất lộ ra bên ngoài là `missing_in_rolled` cao bất thường trong
reconciler (audit 29/07 ghi 3,623) — nhìn qua rất giống "WSS chưa chạy".

Đây cũng là lý do bug (j1) chỉ nổ trên máy user: `mkdir(exist_ok=True)` gặp
vật cản là FILE thì `is_dir()` False → pathlib re-raise → import chết.

**Thuốc cho user** (file rỗng nên xoá an toàn):
    Remove-Item "data_warehouse\_live" -Force
    # thư mục tự tạo lại ở lần ghi kế tiếp (_ensure_live_dir)

**Lưới vĩnh viễn**: `vnstock_doctor.check_dir_shapes()` — soi
`data_warehouse`, `prices`, `_live`, `_meta` có ĐÚNG là thư mục không, báo
"error" kèm hướng dẫn nếu không. Rẻ (vài lần `stat`), chạy trong mọi lần
`run.py doctor`, tức mỗi đêm. 3 test giữ. Full suite 1526 passed.

**Bài học**: `try/except` quanh I/O giữ cho dịch vụ sống, nhưng nếu KHÔNG có
check độc lập soi lại kết quả thì nó biến lỗi cứng thành lỗi CÂM — ở đây là
một tháng mất dữ liệu live. Mọi lớp "best-effort nuốt lỗi" cần một doctor
check tương ứng.

## 📌 CHỜ VERIFY 07/08 (chốt sau đợt 5 việc: WSS/rollup/guard/sentiment/exit-code)

> ⚠️ **Mục này ĐÃ ĐƯỢC THAY THẾ.** Danh sách việc ĐANG DÙNG nằm ở
> **"📌 VIỆC PHẢI LÀM — chốt 08/08"** ở CUỐI FILE (đã gộp cả mục này lẫn
> các việc phát sinh sau). Giữ đây làm sử liệu.

### 🔴 CHỜ ĐIỀU KIỆN THỰC TẾ — chưa verify được bằng test suite

1. **WSS volume tích luỹ** (`vnstock_wss.py`) — cần chạy THẬT trong giờ giao
   dịch (9h15–14h30, T2–T6). **Không cần đủ phiên**, ~5 phút là đủ: chỉ cần
   feed đẩy vài chục tick để `_last_accum_vol` có mốc so sánh.

   ```powershell
   python vnstock_wss.py       # để chạy ~5 phút rồi Ctrl+C
   ```

   Rồi soi `data_warehouse\_live\`:
   - mã cổ phiếu (VCB, HPG…) → `volume > 0` ✅
   - `VNINDEX` / `VN30F1M` → `volume == 0` ✅

   Vì sao index/futures PHẢI là 0: feed **không gửi** `accumulatedvolume` cho
   nhóm này. Trước fix, `_pick()` rơi xuống fallback `"volume"` — là volume
   của TỪNG tick lẻ, không phải luỹ kế — rồi `accum_to_delta()` coi mỗi tick
   như một mốc luỹ kế mới và **cộng dồn thành số ảo**. Sau fix: `accum_raw is
   None` → `delta_volume = 0.0`, và KHÔNG ghi vào `_last_accum_vol` (tránh
   nhiễm mốc giả cho lần sau).

   Kèm theo: `BarAggregator.diagnostics()` → `suspect_count` phải là 0.
   (Đây chính là mục "WSS volume inflation bug" treo từ `PENDING_WORK.md`
   §6/§7 — nay đã có fix, chỉ còn chờ xác nhận live.)

2. **Đơn vị giá penny khi rollup** (`_normalize_units` trong `vnstock_rollup.py`)
   — chỉ kích hoạt khi gặp mã có giá lệch ≥1.000 lần giữa data cũ và data mới
   (`_UNIT_RATIO_MIN = 100.0`, `_UNIT_SCALE = 1000.0`). **Không dựng được
   tình huống thật theo ý muốn** — phụ thuộc nguồn API đổi đơn vị.

   Đã có: test unit phủ `_normalize_units`. Và nếu xảy ra thật thì rollup
   **in cảnh báo ra log** chứ không âm thầm ghi sai như trước. Việc cần làm
   chỉ là: thấy dòng cảnh báo đơn vị trong `run_daily.log` → đọc kỹ, đừng
   lướt qua.

### ✅ ĐÃ VERIFY XONG (không cần làm lại)

3. **`enforce_vnindex_change`** — `_fix2` đọc cửa sổ từ `out[...]` thay vì
   `text[...]` (trước đó đọc chuỗi CHƯA sửa nên guard hụt). Verify qua full
   suite: **1537 passed** trên máy thật.

4. **Sentiment không đóng băng "neutral"** — tin chấm hụt (`r[4]` rỗng) bị
   lọc ra TRƯỚC khi cache, in `[sentiment] N/M tin chưa chấm được`. Trước đó
   ladder chết → cả lô ghi "neutral" vào SQLite vĩnh viễn, không bao giờ
   chấm lại. Verify qua full suite.

5. **Exit code updater 3 tầng** — verify TAY trên máy thật bằng kho giả
   (recipe tái dùng được, không đụng `data_warehouse` thật):

   ```powershell
   # dựng kho giả: GOODTK có data tương lai (→ up_to_date, khỏi gọi mạng),
   # BADTK là thư mục rỗng (→ _get_last_date trả None → error)
   mkdir khothu\prices\ticker=GOODTK\year=2030 -Force
   mkdir khothu\prices\ticker=BADTK -Force
   python -c "import pandas as pd; pd.DataFrame({'time':[pd.Timestamp('2030-01-02')],'open':[1.0],'high':[1.0],'low':[1.0],'close':[1.0],'volume':[1]}).to_parquet(r'khothu\prices\ticker=GOODTK\year=2030\prices.parquet')"

   python vnstock_updater.py --warehouse khothu --force   # 1 ok + 1 err
   echo "exit code: $LASTEXITCODE"                        # → 1  (cảnh báo)

   Remove-Item -Recurse -Force khothu\prices\ticker=GOODTK
   python vnstock_updater.py --warehouse khothu --force   # 0 ok + 1 err
   echo "exit code: $LASTEXITCODE"                        # → 2  (fail cứng)

   Remove-Item -Recurse -Force khothu                     # dọn
   ```

   | `n_ok` | `n_err` | Exit | `run.py sync` làm gì |
   |---|---|---|---|
   | >0 | 0 | **0** | xanh, chạy tiếp |
   | >0 | >0 | **1** | cảnh báo, VẪN chạy rollup |
   | 0 | >0 | **2** | DỪNG — không rollup, không brief |

   Trước fix: cả 3 trường hợp đều trả `0` → 1.100 mã lỗi hết vẫn báo "xanh"
   và brief vẫn sinh trên data cũ.

### 🟡 VIỆC CODE CÒN TREO

6. ✅ **[8] Classifier — XONG 07/08** (sơ đồ model 8 điểm nay ĐỦ CẢ 8). Xem
   entry "07/08 (b)" cuối file. Chờ verify trên máy thật: xem §10 dưới.

7. **`vnstock_llm_ledger.py --test-alert`** — bắn 1 tin "(TEST)" qua đúng
   đường ống alert "LLM ladder DOWN" thật. Đã đề xuất, user chưa gật.
   (Carry-over từ TODO 30/07 §2.)

8. **Việc mức MEDIUM/LOW của đợt audit 06/08** — chưa làm:
   - ghi nguyên tử cho `vnstock_warehouse._write_parquet`, cache macro,
     `_meta/*.json` (mới chỉ `vnstock_parquet_io` dùng ở updater/rollup)
   - hiệu năng pipeline: warehouse bị quét ~14 lần/đêm
   - test replica đã trôi xa bản thật: `tests/test_dashboard.py`,
     `tests/test_wss.py`
   - tách file quá lớn: `vnstock_brief.py` (6.758 dòng),
     `dashboard/market_tab.py`

### 🟠 QUAN SÁT vài ngày rồi quyết (carry-over TODO 30/07 §7-10)

9. A/B brief Gemini vs Groq (~3-5 phiên) · Cerebras `gpt-oss-120b` digest
   chập chờn · OpenRouter nạp $10 CHỈ khi cột "(N rate-limit)" > 0 nhiều
   ngày · Gemini flash 503 đêm VN là bình thường, cascade tự đỡ.

11. **Model watch lần chạy đầu trên máy thật** (07/08 (d)) — chạy
    `python run.py models` một lần để: (i) xác nhận đọc được danh mục cả 4
    provider (dòng nào "không đọc được danh mục" = endpoint sai, báo lại),
    (ii) lưu mốc đầu tiên — **tuần đầu chưa có diff**, phải có mốc rồi tuần
    sau mới so được. Sau đó `run.py models --eval` để xem bảng điểm bộ đề
    (~200 call, **~25-30 phút** — đo thật từ dấu thời gian alert 08-09/08,
    KHÔNG phải 4 phút như ước ban đầu) và **soi lại đáp án bộ đề** trong
    `vnstock_model_eval.GOLDEN_*` — đáp án sai thì cả bảng điểm vô nghĩa.

10. **Batch classifier thật trên máy user** (mới, sau khi làm điểm [8]) —
    chạy `python vnstock_classifier.py --classify --limit 20` rồi soi:
    (i) không đòi `ANTHROPIC_API_KEY` nữa, (ii) dòng route in ra là
    "ladder free — Gemini 3.5-flash dẫn đầu", (iii) cột `model` trong
    `industry_classification.parquet` ghi `Gemini:gemini-3.5-flash`,
    (iv) tỉ lệ "trả lời không lấy được JSON" ở dòng tổng kết. Tỉ lệ đó cao
    (>10-15%) nghĩa là flash không kham nổi prompt 32 nhóm ngành → cân
    nhắc `VNSTOCK_CLASSIFY_PAID=1` cho batch đầy đủ. Ước tính quota: 1.700
    mã tiêu ~2 ngày free tier, hoặc ~$0.5 nếu chạy Claude haiku.

## 2026-08-07 (b) — Điểm [8] classifier: ladder free, Claude thành opt-in

Điểm CUỐI của sơ đồ model 8 điểm. `_call_claude` là đường DUY NHẤT và RAISE
khi thiếu `ANTHROPIC_API_KEY` → batch ~1.700 mã chết ở mã ĐẦU TIÊN; máy
all-free không chạy được classifier chút nào.

Giải y hệt điểm [6] về tinh thần (tái dùng cascade sẵn có, không chế client
mới) nhưng CỐ Ý khác một điểm: [6] dùng `digest_call` — nấc Claude tự bật khi
có key. Ở đây KHÔNG được như vậy: 1.700 mã × 1 call là tiền thật, `.env` vô
tình có key mà tự tiêu tiền là hồi quy đắt. Nên dùng `chat_complete`
(ladder FREE thuần) làm mặc định, Claude phải gõ tay mới chạy: `--paid` hoặc
`VNSTOCK_CLASSIFY_PAID=1`. Lỗi nấc trả phí giữa batch (key hết hạn, 529) rơi
tiếp xuống free thay vì chết.

Slug: KHÔNG slug mới nào vào code (luật CLAUDE.md — slug mới phải probe sống
trước). Cả 3 đều là bộ probe 22/07 đang chạy thật ở `_ANALYZE_MODELS`;
`gemini-3.5-flash` chính là ứng viên đã ghi cho điểm [8] trong
`scripts/probe_models.py`.

**Hai sửa BẮT BUỘC đi theo** (không phải scope creep — chính việc đổi sang
model yếu hơn làm 2 lỗ này từ hiếm thành thường xuyên):

1. `_parse_claude_response` → `_parse_classification`, trả `None` khi model
   HỎNG (không có JSON / JSON vỡ) thay vì bịa ra `"Khác"`. `None` ≠ `"Khác"`:
   "Khác" là câu trả lời HỢP LỆ. Gộp 2 ca lại đúng là họ bug sentiment đóng
   băng "neutral" (fix cùng tuần): rác ghi vào kho → `is_classified` chặn lần
   chấm sau → sai VĨNH VIỄN, không đường tự sửa. Nay mã trả rác không được
   ghi, để lần chạy sau chấm lại; đếm riêng và in cảnh báo cuối batch.

2. Cột `model` ghi nấc THẬT đã trả lời (`"Gemini:gemini-3.5-flash"`) thay vì
   mặc định CLI. Ghi mặc định là nói dối sổ sách — hết soi được chất lượng
   theo model về sau, đúng thứ cần nhất khi vừa hạ từ Claude xuống free.
   Cần thêm `chat_complete(..., with_model=True)` — tham số THÊM, mặc định
   False nên mọi caller sẵn có không đổi một dòng.

Test: 22 test mới `tests/test_classifier.py` (module này TRƯỚC ĐÂY KHÔNG CÓ
TEST NÀO) + 2 test `with_model`. Trong đó 1 test end-to-end chỉ fake
`requests.post`, đi qua `chat_complete` THẬT — cố ý không stub ở chỗ mình
vừa sửa, để dựng lại nguyên chuỗi của bug gốc. Thêm `test_classifier.py` vào
danh sách `--fast`. Full 1537 → 1561, fast 1010 → 1034.

**Còn chờ máy thật**: xem "CHỜ VERIFY 07/08" §10 — chạy `--classify --limit
20` soi route + cột model + tỉ lệ JSON hỏng.

## 2026-08-07 (c) — Probe ladder trên máy thật: 10/10 sống, và 1 bẫy lộ ra từ output

User chạy `python scripts/probe_models.py --ladder` lúc 23:39 sau khi làm
điểm [8]. Kết quả: **10/10 slug SỐNG**, 4/4 key có, độ trễ 0.8–4.8s. Ba nấc
của [8] đều xanh: `gemini-3.5-flash` 1.5s (chính) · `qwen/qwen3.6-27b` 0.8s ·
`nemotron-3-ultra-550b:free` 1.5s. Tag `[8] classifier` hiện đúng — xác nhận
bản vá "khai [8] vào 2 lưới" chạy được trên máy thật (container không tự
kiểm được việc này).

**Bẫy lộ ra từ chính output**: đầu output có
`✅ Authentication successful: Binh Le (golden)` + `Using vnstock_data
(vnstock_classifier.py:66)`. Tức là để đọc 3 dòng slug, `--ladder` phải
import `vnstock_classifier` — module này kéo theo SDK vnstock + xác thực
MẠNG ngay lúc import.

Nghĩa là key DATA hết hạn hoặc mạng lỗi → `--ladder` chết TRƯỚC khi probe
được model nào. Công cụ chẩn đoán LLM bị giết bởi thứ nó không chẩn đoán,
đúng lúc cần nó nhất. Cùng họ bài học với `_live` là FILE làm WSS chết câm:
một lớp phụ trợ hỏng làm chết cả đường chính.

Vá: import [8] nằm trong `try/except` riêng, hỏng thì bỏ nấc [8] nhưng IN
CẢNH BÁO kèm loại lỗi. Không nuốt im lặng — nuốt im lặng là quay lại đúng
điểm mù vừa vá xong ở entry trước. Test `test_probe_ladder_survives_broken_
vnstock_sdk` giả lập SDK nổ và chốt: các nấc khác vẫn probe, nấc [8] biến
mất khỏi tag, và cảnh báo phải in ra.

**Bài học chung** (đáng nhớ hơn ca cụ thể): khi thêm một điểm dùng model mới,
phải khai vào CẢ HAI lưới (`_all_live_slugs` của test + `_ladder_slugs` của
probe) — và nhớ rằng lưới chỉ soi thứ được KHAI BÁO. Lần này slug [8] trùng
y nguyên giá trị với `_ANALYZE_MODELS` nên nhìn thì tưởng an toàn; đó là
TRÙNG HỢP, không phải bảo vệ. Đổi model chấm tin mà quên classifier là slug
batch 1.700 mã thành điểm mù ngay. Đã có `test_classifier_slugs_are_watched_
by_both_nets` chốt việc đó độc lập.

**Ghi chú phụ**: máy user đang có bản mới của thư viện data (vnstock 4.0.4 →
4.0.5, vnai 2.4.8 → 2.5.6, vnii 0.2.4 → 0.2.5). CHƯA nâng — vnstock là nguồn
data của cả pipeline, nâng phải chạy `run.py doctor --net` + full suite ngay
sau đó, không nâng lúc sát giờ pipeline chạy.

## 2026-08-07 (d) — Module theo dõi model hàng tuần (user chốt cả 3 giai đoạn)

User đề xuất: module chạy hàng tuần, test model, soi model sắp hết hạn / bị
thay, xếp mạnh→yếu rồi áp vào các điểm dùng theo thứ tự. Bàn xong chốt lại
như dưới — 2 vế giữ nguyên, 1 vế đổi hình thức, 1 vế cố ý KHÔNG làm.

### Vế "soi model sắp hết hạn" — probe KHÔNG làm được, phải diff DANH MỤC

Model đã khai tử nhưng còn phục vụ trả `200 OK` y hệt model khỏe. Bằng chứng
ngay trong repo: `llama-3.3-70b-versatile` ("Groq deprecated 17/06, còn phục
vụ nhưng sẽ gỡ") và `zai-glm-4.7` ("Cerebras sắp dep 17/08") — hai dòng đó
đến từ ĐỌC THÔNG BÁO nhà cung cấp, không phải từ probe. Chỉ probe thì tuần
nào cũng thấy xanh cho tới đúng ngày model biến mất.

→ Thay bằng **diff danh mục**: mỗi tuần chụp danh sách model của 4 provider,
so với tuần trước. Model thường rời danh mục TRƯỚC khi ngừng phục vụ. Chạy
thử ca giả: Gemini gỡ `gemini-3.5-flash` và thêm `gemini-4.0-flash` → báo cáo
in đúng "🗑 gỡ / 🆕 mới" + escalate 🚨 vì slug bị gỡ đang được 4 điểm dùng.

**Hai bẫy đã chốt bằng test**:
* `fetch_catalog` trả `None` khi ĐỌC HỤT, không phải tập rỗng. Gộp 2 ca là
  một lần mạng lỗi thành "toàn bộ model biến mất" — báo động giả hàng loạt
  tệ hơn không báo. Diff gặp None → `status: skipped`, gone/new RỖNG.
* Chỉ báo động cho model ĐANG DÙNG. Danh mục provider đổi liên tục; báo mọi
  thay đổi thì tuần nào cũng có tin và người đọc bỏ qua hết.

### Vế "xếp mạnh→yếu" — đổi thành BỘ ĐỀ CHẤM THEO VIỆC

Không làm bảng xếp hạng chung, vì "mạnh" phụ thuộc VIỆC: model viết brief hay
chưa chắc xuất JSON 32 nhóm ngành chuẩn. 8 điểm với 8 bộ model khác nhau
KHÔNG phải lộn xộn — đó là tri thức tích luỹ ("70B free bịa chiều tác động",
"gpt-oss-120b digest chập chờn"); gộp thành một thứ hạng là vứt bỏ đúng phần
giá trị nhất.

→ `vnstock_model_eval`: 25 ca có đáp án người duyệt, phủ 3 dạng output khác
hẳn nhau — classify (JSON + đúng 1/32 nhãn), sentiment (3 nhãn từ văn bản tự
do), json (đúng schema). Chấm bằng luật xác định, KHÔNG dùng LLM chấm LLM.

### Vế "tự áp vào code" — CỐ Ý KHÔNG LÀM

Ba lý do: (1) brief bắn thẳng Telegram mỗi sáng — script tự đổi model là user
đọc bản không ai duyệt, phát hiện thì tin đã gửi; (2) tiền lệ zombie
`qwen3-235b:free` sống→404→sống trong 1 ngày, đổi config theo một lần đo là
loạn; (3) trái doctrine repo (ràng buộc quan trọng phải là guard xác định +
test). → Chỉ đề xuất, kèm ngưỡng **2 lần chạy liên tiếp** mới `ripe`. Module
KHÔNG có `apply_swaps` và có test chốt là không được có.

### Nối vào hệ thống

`run.py models [--eval]` · bước ĐẦU của `run.py weekend` (nhẹ nhất ~10 call,
và là thứ duy nhất phát hiện ladder sắp chết → chạy trước để bước nặng lỗi
vẫn kịp cảnh báo; lỗi bước này KHÔNG chặn các bước sau — có test) · badge
sidebar 🧠 đọc `_meta/model_status.json` · cảnh báo Telegram khi probe đỏ
hoặc model đang dùng bị gỡ · kill-switch `VNSTOCK_MODEL_WATCH`,
`VNSTOCK_MODEL_WATCH_EVAL`, `VNSTOCK_MODEL_WATCH_ALERT`.

Gỡ trùng lặp: `probe_one`/`_ladder_slugs`/`_PROVIDERS` nay chỉ còn MỘT bản ở
`vnstock_model_watch`; `scripts/probe_models.py` (323 → 192 dòng) là CLI mỏng
import lại. Trước đó 2 bản song song — đúng kiểu "replica trôi xa bản thật".

**Bẫy tự tạo, tự bắt**: bản đầu `_run_eval_stage` gọi `run_eval` không truyền
delay → production bắn ~250 call liên tiếp lên free tier, dính rate limit
ngay (Groq TPM 8K). `run_eval` mặc định `delay=0` cho test chạy nhanh nên
nhánh production PHẢI tự truyền — đã có test canh.

Suite 1563 → 1592 passed (+29).

## 2026-08-08 — ~~Danh mục OpenRouter BỊ PHÂN TRANG~~ → KẾT LUẬN SAI, xem entry (b) ngay dưới

> ⚠️ **Entry này chốt sai.** Giữ lại nguyên văn làm sử liệu về một lần suy
> luận hỏng. Sự thật: OpenRouter có ĐÚNG 400 model, không hề bị cắt trang.
> Đọc entry "2026-08-08 (b)" phía dưới trước khi tin bất cứ dòng nào ở đây.

Máy user chạy `run.py models` 2 lần, lần 2 in `OpenRouter không đổi (400
model)`. **400 tròn trịa** là dấu hiệu mức trần chứ không phải số thật →
nhờ user gọi thẳng endpoint. Kết quả:

```
khoa: ['data', 'links', 'total_count']
mac dinh: 400
```

`links` + `total_count` = **có phân trang**, và `?limit=2000` bị từ chối
(response không còn khoá `data`). Tức bản `fetch_catalog` đầu tiên chỉ đọc
TRANG ĐẦU → mốc OpenRouter lưu cho user là danh mục CỤT. Để nguyên thì mọi
tuần sau diff sẽ sinh "bị gỡ/mới" giả tuỳ thứ tự trang đổi.

Bài học lặp lại y hệt entry 14/07 ("thay model theo catalog trên mạng →
model_not_found"): **không đoán hình dạng API, hỏi endpoint thật**. Con số
tròn trịa là mùi, phải ngửi ra và đi kiểm chứ đừng ghi nhận rồi đi tiếp.

**Vá**: `_fetch_openai_catalog` đi hết trang theo 2 chiến lược — `links.next`
(chuẩn) rồi tham số `offset` khi `total_count` báo còn thiếu; chống lặp vô
hạn bằng tập URL+params đã thấy, trần 12 trang. Gom mãi vẫn thiếu so với
`total_count` → trả None KÈM DÒNG NÓI RÕ `chỉ đọc được N/M model`, tức coi
như không đọc được: diff một danh mục cụt là sinh báo động giả hàng tuần,
thà không biết còn hơn báo sai (cùng doctrine với "đọc hụt ≠ tập rỗng").

**Lưới cho ca ngược** (`suspect_baseline`): mốc CŨ mới là cái cụt → tuần này
đọc đủ thì thấy cả trăm model "mới". Đó là hiện tượng ĐỌC, không phải
provider ra 240 model trong một tuần; báo cáo nay nói đúng bản chất thay vì
khoe một đống 🆕 giả. Cùng họ với `suspect_partial` (mất >50% = nghi đọc
thiếu) làm 08/08 trước đó.

**Việc user phải làm SAU KHI PULL**: xoá `data_warehouse/_meta/
model_watch_history.json` (mới có 2 lần chạy, không tiếc) rồi chạy lại
`run.py models` để dựng mốc ĐỦ. Không xoá thì tuần sau vẫn ra một lần
`suspect_baseline` — có nhãn nên không hiểu nhầm, nhưng dựng lại cho sạch.

Kích thước danh mục THẬT ghi lại để đối chiếu: Cerebras 3 · Groq 15 ·
Gemini 58 · OpenRouter 400+ (chờ số đủ sau khi vá). Cerebras = 3 khớp ghi
chú 22/07 ("catalog chỉ còn 3 model") — mốc tự xác nhận đọc đúng.

Suite 1596 → 1601 passed.

## 2026-08-08 (b) — ĐÍNH CHÍNH: OpenRouter có ĐÚNG 400 model, không cắt trang

Số liệu dứt điểm từ máy user (`Invoke-RestMethod`, PowerShell thuần):

```
$r.total_count → 400
$r.links       → next : (rỗng)
$r.data.Count  → 400
```

`total_count` = 400 = `len(data)`, `links.next` NULL. Danh mục thật sự có 400
model. **Không có bug cắt trang nào cả.**

### Chuỗi suy luận hỏng — đáng ghi hơn cả kết luận

1. Thấy `OpenRouter không đổi (400 model)`. Con số tròn → nghi mức trần. ✅
   Nghi ngờ này ĐÚNG chỗ, phải giữ thói quen này.
2. Nhờ user gọi endpoint, thấy khoá `['data', 'links', 'total_count']` và
   `?limit=2000` báo KeyError `data`. → kết luận "XÁC NHẬN có phân trang".
   ❌ **Đây là bước hỏng.**

Sai ở chỗ: suy từ sự CÓ MẶT của khoá phân trang ra việc ĐANG BỊ cắt. `links`
tồn tại trong schema không có nghĩa `links.next` khác null; `total_count` tồn
tại không có nghĩa nó lớn hơn `len(data)`. Còn `?limit=2000` lỗi chỉ chứng
minh tham số đó không hợp lệ — không nói gì về việc có bị cắt hay không.

Dữ liệu cần để kết luận là GIÁ TRỊ của `total_count` và `links.next`, mà mãi
2 lượt sau mới lấy (2 lượt đó mất vào lệnh `python -c` bị PowerShell nuốt
mất dấu nháy — bài học phụ: hỏi máy Windows thì dùng `Invoke-RestMethod`,
đừng lồng nháy trong `python -c`).

**Luật rút ra**: đọc GIÁ TRỊ, đừng đọc SỰ TỒN TẠI CỦA KHOÁ. Áp cho mọi API
lạ — `has_more`, `next_page`, `total` đều là affordance, không phải bằng chứng.

### Code giữ nguyên — nhưng vì lý do khác với lúc viết

`_fetch_openai_catalog` + guard "đọc thiếu → trả None" KHÔNG bỏ đi, vì:

* Chi phí bằng 0 khi không cần: `links.next` null và `total_count == len(ids)`
  → thoát ngay sau 1 request, y hệt bản cũ. Đã verify trên máy thật.
* `links.next` CÓ trong schema nghĩa là OpenRouter phân trang khi vượt cỡ
  trang. Hôm nay 400 model vừa đủ một trang; ngày họ vượt thì code đã sẵn
  sàng, và quan trọng hơn là ta sẽ KHÔNG âm thầm lưu mốc cụt.
* Guard hoàn chỉnh-hay-không (`len(ids) < total_count` → None + in lý do) là
  thứ duy nhất biến "đọc cụt" từ lỗi CÂM thành lỗi nói được.

Tức: code đúng, nhưng commit message của `6584828` ("Co phan trang that")
chốt sai — đã merge vào main nên không sửa lịch sử, đính chính ở đây.

### Kích thước danh mục THẬT (mốc 08/08, để đối chiếu về sau)

Cerebras 3 · Groq 15 · Gemini 58 · **OpenRouter 400**. Cerebras = 3 khớp ghi
chú 22/07 → xác nhận độc lập rằng phần đọc danh mục là thật.

## 2026-08-08 (c) — Theo dõi độ trễ theo tuần (user yêu cầu)

Thêm vào `vnstock_model_watch`: mỗi lần chạy lưu giây probe của từng slug
vào lịch sử, so lần này với MEDIAN các tuần trước.

**Vì sao median chứ không phải tuần liền trước** — bài học ngay đêm 07/08:
chạy probe dồn 4 lần trong 45 phút làm free tier OpenRouter bóp băng thông,
nemotron-super 4.8s → 9.6s → 17.0s rồi TỰ HỒI về 1.8s sau khi nghỉ. So với
một lần đo là kêu oan; median chịu được cú nhảy lẻ.

**Hai điều kiện PHẢI thoả cùng lúc** mới tính là chậm bất thường:
* `now ≥ 3× median` — chậm tương đối so với CHÍNH NÓ
* `now ≥ 5s` — sàn tuyệt đối. Thiếu sàn này thì 0.8s → 2.4s cũng 3×, toàn
  nhiễu. (Ca thật: Groq 2.6s so median 0.8s = 3.25× nhưng KHÔNG kêu.)

**Chỉ nâng mức badge/bắn Telegram khi `now ≥ 15s`** — mốc này chọn theo
timeout **25s** của `chat_complete` (đường [1] sentiment, [2] chấm tin,
[8] classifier), có chừa biên vì prompt thật nặng hơn ping rất nhiều. Chậm
vừa (5-15s) chỉ hiện trong báo cáo, không đổi màu badge: cảnh báo kêu oan
vài lần là lần sau người ta bỏ qua thật.

Model CHẾT không được tính vào thống kê độ trễ (đã có cảnh báo riêng), và
cần ≥2 mẫu mới có median — nên tuần đầu tuyệt đối không kêu.

Tương thích ngược: run cũ trong lịch sử không có khoá `probe_seconds` thì bỏ
qua, không nổ (máy user đang có đúng 1 run kiểu đó).

⏳ **Khi nào có tín hiệu**: cần ≥2 lần chạy CÓ lưu giây → sớm nhất là sau 2
lần chạy T7 nữa (~2 tuần). Trước đó phần này im lặng, đúng như thiết kế.

Suite 1601 → 1608 passed.
## 2026-08-08 (d) — Bảng điểm bộ đề lần đầu chạy thật: SỐ LIỆU SAI, lỗi ở thiết kế chấm

Chạy `run.py models --eval` trên máy user. Bảng ra thứ tự trông hợp lý nhưng
có dòng tự tố cáo:

```
Gemini:gemini-3.5-flash    classify=1.00  json=0.00  sentiment=0.00
```

**Mâu thuẫn logic**: được `classify=1.00` nghĩa là model xuất JSON hợp lệ
ĐÚNG 12 lần liên tiếp. Model làm được thế không thể trượt 0/5 bài xuất JSON.
Kèm `nemotron-ultra`: `classify=0.92 → sentiment=0.38 → json=0.00`, giảm dần
ĐÚNG THỨ TỰ CHẠY. Đó là chữ ký hạn mức, không phải chất lượng.

**Lỗi ở tôi**: `_run_one_task` chấm ca lỗi (429) thành 0 điểm rồi chia cho
tổng số ca. Tức gộp **KHÔNG ĐO ĐƯỢC** với **ĐO RA KẾT QUẢ KÉM** — đúng họ bug
đã sửa 2 lần trong tuần này (sentiment đóng băng "neutral"; classifier ghi
JSON hỏng thành "Khác"). Lần này tự tay tái phạm ở module mới.

Tệ hơn: đề xuất sinh ra từ số liệu đó (`json: flash 0.00 → flash-lite 1.00`)
là đề xuất dựa trên nhiễu. May là có ngưỡng 2 tuần nên chưa ai áp.

### Bốn sửa

1. **Hụt >30% số ca → điểm là `n/a`, không phải 0** (`_MIN_COVERAGE = 0.7`).
   Điểm tính trên số ca THỰC SỰ trả lời. `propose_swaps` bỏ qua `n/a` nên
   không đẻ đề xuất từ hạn mức.
2. **Báo cáo HIỆN số ca hụt** + chú thích "n/a ≠ điểm 0". Trước đó tôi lọc
   `errors` khỏi bảng → không phân biệt được "trả lời sai" với "không trả
   lời", tức bảng không đọc được. Đây mới là lỗi gốc khiến số liệu sai lọt
   qua mắt.
3. **429 được lùi-rồi-thử-lại** (5s, 15s). 429 là "thử lại sau", không phải
   "model hỏng". Lỗi khác (404 model_not_found) KHÔNG retry — chỉ tốn giờ.
4. **Dính hạn mức 3 ca liên tiếp → bỏ nốt bài đó.** Quota cả ngày cạn mà vẫn
   retry thì 25 ca × 20s × 10 model > 1 tiếng cho task T7.

Kèm bẫy test tự tạo: retry ngủ thật làm MỘT test mất 4 phút (12 ca × 20s) —
suite từ 30s vọt lên 258s. Thêm autouse fixture vá `time.sleep` cho cả
`vnstock_model_eval` lẫn `vnstock_model_watch`.

### Số liệu nào CÒN dùng được từ lần chạy này

Dòng nào `errors = 0` thì tin được. Đáng chú ý: **`Groq:openai/gpt-oss-120b`
và `OpenRouter:nemotron-3-super` đạt 1.00/1.00/1.00**, `gemini-3.5-flash-lite`
0.92/1.00/1.00. Nhưng CHƯA kết luận vội — phải chạy lại sau khi vá để biết
dòng nào 0 điểm thật, dòng nào chỉ là hụt quota.

**Bài học chung**: bảng điểm mà không kèm ĐỘ PHỦ là bảng không đọc được. Mọi
chỉ số tổng hợp phải đi kèm "đo trên bao nhiêu mẫu", nếu không thì im lặng
biến thành số 0 và số 0 biến thành kết luận.

Suite 1608 → 1612 passed.

## 2026-08-08 (e) — Hết hạn mức bị báo là "model chết", và eval tự cướp quota production

Lần chạy `--eval` thứ hai (22:10) ra dữ liệu SẠCH cho 7 model, nhưng lộ 2 lỗi
mới — cả hai đều là **cùng một sai lầm gốc lặp lại ở chỗ khác**.

### Lỗi 1: probe chấm 429 thành "chết"

```
❌ OpenRouter nvidia/nemotron-3-super-120b-a12b:free   [7] brief
     ↳ HTTP 429: Rate limit exceeded: free-models-per-day
```

Ba model OpenRouter bị báo ❌ chết, trạng thái đỏ, và sẽ bắn Telegram "model
chết" — trong khi thông báo nói rõ là hết hạn mức NGÀY. Model vẫn sống, mai
có quota là chạy.

Đây là lần thứ TƯ trong tuần cùng một họ bug: gộp "không đo được / không dùng
được TẠM THỜI" với "hỏng thật". (1) sentiment đóng băng "neutral"; (2)
classifier ghi JSON hỏng thành "Khác"; (3) bảng điểm chấm 429 thành 0 điểm;
(4) probe chấm 429 thành chết. **Mỗi lần thêm một đường xử lý lỗi mới là một
cơ hội tái phạm** — cứ gặp nhánh lỗi thì hỏi: đây là "hỏng" hay "tạm thời
không dùng được"?

Vá: `_is_rate_limited` (một bản DÙNG CHUNG cho cả watch lẫn eval) → dòng probe
in ⏳ thay vì ❌, mức là **warn** không phải red, không vào danh sách alert
"model chết", header ghi rõ "N hết hạn mức".

### Lỗi 2: eval của ta ăn hết quota của production

OpenRouter free = **50 request/ngày**. Eval chạy 3 model × 25 ca = **75 call**
→ đốt sạch. Hôm sau probe thấy 429, và quan trọng hơn: **pipeline thật mất
nấc dự phòng OpenRouter cả ngày đó**. Công cụ giám sát làm hỏng thứ nó giám
sát.

Vá: `EVAL_BUDGET = {"OpenRouter": 25}` — chạm hạn thì model còn lại để tuần
sau, kèm `_eval_order()` xoay vòng (model chưa đo lần gần nhất lên đầu). Không
xoay thì model bị cắt sẽ KHÔNG BAO GIỜ được đo.

⚠️ Lưu ý khi quyết định nạp $10 OpenRouter (mục quan sát §11): lần rate-limit
này là do CÔNG CỤ CỦA TA đốt, không phải production bị bóp. Đừng lấy nó làm
căn cứ nạp tiền — sửa công cụ trước, quan sát lại sau.

### Số liệu THẬT đầu tiên dùng được (7 model, errors=0)

```
Cerebras:gemma-4-31b            classify=1.00 sentiment=1.00 json=1.00
Cerebras:gpt-oss-120b           classify=1.00 sentiment=1.00 json=1.00
Gemini:gemini-3.5-flash-lite    classify=1.00 sentiment=1.00 json=1.00
Groq:openai/gpt-oss-120b        classify=1.00 sentiment=1.00 json=1.00
Groq:openai/gpt-oss-20b         classify=1.00 sentiment=0.88 json=0.80
Gemini:gemini-3.5-flash         classify=0.91 sentiment=1.00 json=n/a (4 ca hụt)
Groq:qwen/qwen3.6-27b           classify=0.33 sentiment=0.50 json=0.00
```

**`Groq:qwen/qwen3.6-27b` 0.33/0.50/0.00 với errors=0** — tức trả lời được
NHƯNG SAI, không phải hạn mức. Mà slug này đang gánh [2] chấm tin, [3-6]
digest b2, [7] brief VÀ [8] classifier. Đây là phát hiện đáng giá nhất của cả
đợt, nhưng CHƯA đủ để đổi: cần lần chạy thứ hai xác nhận (ngưỡng ripe 2 tuần
tồn tại chính vì thế). Nghi vấn cần loại trừ trước: model reasoning này có thể
tiêu hết `max_tokens=400` vào phần suy nghĩ → output cụt. Nếu đúng thì lỗi
nằm ở bộ đề của ta, không phải model.

Suite 1612 → 1617 passed.

## 2026-08-09 — Bộ đề cấp 400 token: chấm oan model reasoning (qwen3.6-27b)

Lần chạy `--eval` thứ ba (22:02, sau khi quota hồi) cho dữ liệu SẠCH nhất từ
trước tới nay: 8 model đo được, 2 model OpenRouter hoãn đúng theo hạn mức, độ
trễ lần đầu có median và bắt trúng (nemotron-super 18.6s so median 3.26s).

Nhưng `Groq:qwen/qwen3.6-27b` lặp lại kết quả kém với **errors=0**:

| lần | classify | sentiment | json |
|---|---|---|---|
| 08/08 | 0.33 | 0.50 | 0.00 |
| 09/08 | 0.33 | 0.38 | 0.00 |

Nhất quán, và `errors=0` nghĩa là TRẢ LỜI ĐƯỢC nhưng sai. Slug này đang gánh
[2] chấm tin, [3-6] digest b2, [7] brief VÀ [8] classifier — nếu đúng là kém
thì đây là phát hiện đắt giá nhất của cả đợt.

### Nhưng KHÔNG kết luận, vì bộ đề của ta chật token

Hai cơ chế cộng lại, và cả hai đều là lỗi của tôi:

1. **Cấp 400 token.** Chính repo đã học bài này ở digest: `_TIER1_TOKENS` cấp
   Groq **900** · Cerebras **6000** · OpenRouter **4000**, `_TIER2_TOKENS
   = 3000` kèm chú "1200 là cụt content". qwen3.6 và gpt-oss là model
   REASONING — tiêu ngân sách vào phần suy nghĩ TRƯỚC khi trả lời.
2. **`_THINK_RE` đòi THẺ ĐÓNG.** Output bị cắt giữa lúc suy nghĩ thì không có
   `</think>` → không strip được → `_first_json` lục trong đống suy nghĩ →
   không thấy JSON → 0 điểm. json=0.00 khớp chính xác dấu hiệu này.

Vá: `_EVAL_MAX_TOKENS = 2000`; và thẻ `<think>` mở còn sót sau khi `chat_once`
đã strip mọi khối ĐÓNG ĐỦ = bằng chứng bị cắt → tính là **hụt (n/a)**, không
phải 0 điểm.

Đây là lần thứ NĂM cùng một họ bug trong hai ngày: chấm "không đo được" thành
"đo ra kết quả kém". (1) sentiment neutral · (2) classifier "Khác" · (3) bảng
điểm 429→0 · (4) probe 429→chết · (5) output cụt→0. Danh sách này nên đọc
như một checklist: **mỗi nhánh xử lý lỗi mới, hỏi ngay "đây là HỎNG hay TẠM
THỜI KHÔNG ĐO ĐƯỢC?"**

### Cố ý CHƯA làm: cảnh báo "nấc yếu đang dùng"

`propose_swaps` chỉ soi nấc DẪN của mỗi việc, nên qwen (nấc dự phòng ở 4 điểm)
không bao giờ sinh đề xuất — đó là giới hạn thật của thiết kế hiện tại. Nhưng
KHÔNG thêm cảnh báo "nấc yếu" ngay bây giờ: thêm lúc này thì nó sẽ kêu ngay
trên một số đo còn hỏng. Sửa phép đo trước, xem số sau, rồi mới quyết. Nếu
sau khi cấp 2000 token mà qwen vẫn kém thì lúc đó cảnh báo mới có nghĩa.

Suite 1617 → 1621 passed.

## 2026-08-10 — Đối chiếu 3 alert Telegram cuối tuần: task T7 CHẠY THẬT

User dán 3 tin Model watch nhận cuối tuần. Đối chiếu xong:

| Thời điểm | Nội dung | Kết luận |
|---|---|---|
| **T7 08/08 09:10** | ❌ `gpt-oss-20b:free` 429 "Provider returned error" | **Task T7 TỰ CHẠY LẦN ĐẦU** — thành công. Báo cáo lãi suất tuần gửi ngay sau, cùng 09:10 → cả chuỗi weekend chạy trót lọt |
| T7 08/08 22:26 | ❌ cả 3 model OpenRouter "free-models-per-day" | Chạy tay. **Bằng chứng đóng đinh**: eval lúc 09:00 (75 call > hạn 50/ngày) đã đốt sạch quota, tối cả 3 nấc OpenRouter chết cho tới hết ngày |
| CN 09/08 22:31 | 🐌 nemotron-super chậm 5.7× | Chạy tay. **Hành vi ĐÚNG** — lần đầu lưới độ trễ bắt được |

Hai tin đầu do code TRƯỚC bản vá `d8847c8` (429 → ❌ "chết"). Nay 429 in ⏳ và
KHÔNG vào danh sách alert.

### Điều đáng giá nhất: xác nhận blast radius của bug quota

Tin 22:26 chứng minh hậu quả thật, không phải suy đoán: từ 09:00 tới hết ngày
T7, **production mất cả 3 nấc OpenRouter** ở [1] sentiment, [2] analyze,
[3-6] digest, [7] brief. Lần này vô hại vì T7 không có phiên và rates-weekly
đã chạy xong lúc 09:10 bằng Gemini/Cerebras. Nhưng nó cho thấy công cụ giám
sát ĐÃ từng làm hỏng thứ nó giám sát — `EVAL_BUDGET` không phải phòng xa.

Sau vá: T7 tới OpenRouter chỉ tiêu 3 (probe) + 25 (eval 1 model) = **28/50**,
còn dư cho digest. Thứ tự weekend giữ nguyên (models đứng đầu) vì digest gọi
Gemini → Cerebras trước, chỉ chạm OpenRouter khi 2 nấc kia hỏng.

### Sửa số liệu tôi nói sai

Tôi bảo user `--eval` mất "~4 phút". Đo thật từ chính dấu thời gian alert:
**24 phút** (08/08: 22:02 → 22:26) và **29 phút** (09/08: 22:02 → 22:31).
~8 model × 25 ca × (1s giãn + 1-3s API) + retry. Đã sửa trong checklist.
Lưu ý: bản vá token (400 → 2000) sẽ làm output dài hơn nữa → có thể lâu hơn.


## 2026-08-10 (b) — Tự duyệt bộ đề theo uỷ quyền của user (biên bản từng ca)

User: "bạn tự chấm và duyệt cho tôi với nỗ lực tối đa nhất rồi áp vào code".
Tức đáp án KHÔNG còn là "người duyệt" theo nghĩa gốc — độ tin giờ dựa trên:
(i) biên bản dưới đây, phản biện lại được TỪNG ca; (ii) các ca đều cố ý là
kiến thức phổ thông TTCK VN, không phải judgment call tinh vi. User phủ quyết
ca nào: sửa 1 dòng GOLDEN_* + `run.py test --fast`.

### Bộ A — phân loại ngành (12 ca): 11 giữ, 1 sửa mô tả

| # | Mã | Đáp án | Kết luận |
|---|---|---|---|
| 1 | VCB | Ngân hàng | ✅ hiển nhiên |
| 2 | HPG | Thép & Kim loại | ✅ desc chỉ nói thép; thực tế thép áp đảo doanh thu |
| 3 | VNM | Thực phẩm & Đồ uống | ✅ |
| 4 | FPT | CNTT & Phần mềm | ✏️ **SỬA DESC** — desc cũ liệt kê 4 mảng không trọng số, mà list nhãn có riêng "Viễn thông" và "Giáo dục" → primary không xác định được TỪ TEXT (trái luật bộ đề). Thêm "(mảng chính, phần lớn doanh thu)". Giữ cấu trúc đa mảng vì công ty thật vốn thế |
| 5 | VHM | Bất động sản | ✅ |
| 6 | GAS | Dầu khí | ✅ quy ước VN: GAS thuộc "họ dầu khí" (mọi screener VN xếp vậy) dù ICB quốc tế đôi khi xếp utilities |
| 7 | SSI | Chứng khoán & ĐTTC | ✅ |
| 8 | BVH | Bảo hiểm | ✅ |
| 9 | POW | Điện & NLTT | ✅ **GIỮ dù POW là nhiệt điện** — nhãn là TÊN RỔ (mọi phát điện + tái tạo), không phải khẳng định POW tái tạo; "Điện" chỉ có ở đúng 1 nhãn nên xác định được |
| 10 | DHG | Y tế & Dược phẩm | ✅ |
| 11 | MWG | Bán lẻ & Thương mại | ✅ |
| 12 | VSC | Cảng & HT logistics | ✅ **GIỮ dù sát "Vận tải & Logistics"** — hai nhãn CÙNG TỒN TẠI trong production nên phân biệt cảng vs logistics tổng hợp CHÍNH LÀ kỹ năng phải đo; desc dẫn bằng "khai thác cảng biển" nên xác định được |

### Bộ B — sắc thái tin (8 ca): giữ cả 8

Quy ước chấm (ghi ra để sau khỏi cãi): chấm TÁC ĐỘNG TRỰC TIẾP lên ngành/
thị trường mà tin NÓI TỚI, không đuổi theo hiệu ứng bậc hai.

* B#2 hạ lãi suất điều hành → positive: quy ước thị trường (nới tiền tệ =
  xuôi cho cổ phiếu); "NIM ngân hàng bị ép" là bậc hai.
* B#3 giá thép giảm 5 phiên → negative: tin NÓI VỀ ngành thép (cầu yếu);
  "nhà thầu xây dựng hưởng lợi" là bậc hai.
* B#7/B#8 (lịch nghỉ lễ, lịch ĐHCĐ) → neutral: công bố hành chính thuần.
* Còn lại (#1 xuất khẩu +18%, #4 thuế chống bán phá giá, #5 chậm trả trái
  phiếu, #6 FDI +10%) một chiều rõ, không cần bàn.

### Bộ C — xuất JSON (5 ca): giữ cả 5

Chấm cơ học (parse được + đủ khoá), khoá yêu cầu khớp đề từng ca. Không có
"đáp án nội dung" để duyệt.

### Phát hiện đắt nhất: BUG SCORER, không phải đáp án

`score_sentiment` so nhãn trên CẢ chuỗi, trong khi production
(`analyze_item`) partition trên `|` và chỉ so PHẦN TRƯỚC. Dựng lại được ca
cụ thể: model trả **"Trung lập | không tích cực cũng không tiêu cực"** (cách
diễn đạt neutral rất tự nhiên) → nhãn đầu dạng space nên các khoá underscore
trượt hết, rồi "tích cực" trong ĐUÔI khớp trước → chấm positive → **0 điểm
OAN cho ca neutral**. Đã sửa mirror production + test chốt.

Hệ quả đọc số lần --eval tới: điểm sentiment một số model có thể NHÍCH LÊN
nhờ fix scorer (gpt-oss-20b đang 0.75-0.88 ≈ hụt 1-2 ca — có thể chính là
nạn nhân). Đừng đọc nhầm thành "model tự khá lên".

Giữ CÓ Ý một khác biệt với production: production default "neutral" khi
không khớp gì — đó là lớp CHE LỖI; eval tính là trượt, không mirror.

Bài học — phiên bản chấm-điểm của "lưới chỉ soi thứ được khai báo": duyệt
bộ đề mà không duyệt NGƯỜI CHẤM là duyệt nửa chừng. Scorer sai thì 25 đáp
án đúng cũng vô nghĩa.


## 2026-08-10 (c) — Verify [8] lần đầu: 8/10 đậu, 2 mã trượt LỘ bug token

User chạy `--rerun-flagged` 10 mã quen. **Đậu 3/4 checkpoint**: không đòi
`ANTHROPIC_API_KEY` ✓ · route "ladder free — Gemini 3.5-flash dẫn đầu" ✓ ·
guard không-đóng-băng chạy đúng (VCB/SSI KHÔNG bị ghi rác vào kho, "để chấm
lại") ✓ · dòng cảnh báo tổng kết in đúng thiết kế ✓.

Trượt: **2/10 "không lấy được JSON" — mà là VCB và SSI**, hai mã DỄ XẾP NHẤT
thị trường (bộ đề flash vừa đạt classify 0.91-1.00). Model không thể "không
biết" VCB là ngân hàng → nghi output bị CẮT, và tiền lệ repo xác nhận:

* c1dcb14 (06/08, brief): "output bị cắt (finish_reason=length)… nâng think
  headroom Gemini" — flash SUY NGHĨ MẶC ĐỊNH, ngày data phức tạp nghĩ ~5k
  token; brief phải cộng headroom **8000**, kèm chú "đây là TRẦN, không phải
  chi phí".
* digest `_TIER1_TOKENS` cấp Gemini **6000**.
* Classifier cấp **800** — thừa kế nguyên xi từ thời `_call_claude` (Claude
  haiku KHÔNG suy nghĩ, 800 đủ). **Đổi model dẫn đường mà quên đổi ngân sách
  token đi kèm.**

Vì sao trúng đúng VCB/SSI: prompt classifier nhét profile (≤800 ký tự) +
revenue (≤400) — ngân hàng/chứng khoán lớn nhất sàn có hồ sơ tài chính DÀY
nhất → flash nghĩ nhiều nhất → 800 token cạn trước khi JSON 4 trường kịp ra.

Vá (suite 1622 → 1624):
1. `_CLASSIFY_MAX_TOKENS = 6000` làm default `_call_llm` — suggest/spot-check
   hưởng chung (bỏ override 2000 cũ: đó là sizing CONTENT thời Claude).
2. Cảnh báo "không lấy được JSON" in thêm dòng chẩn đoán `_no_json_hint`:
   thẻ `<think>` mở → "nghi bị CẮT giữa lúc suy nghĩ"; có `{` mà không parse
   → "bị cắt giữa chừng?"; kèm đuôi 70 ký tự output. Trước đó lỗi CÂM — nhìn
   "không lấy được JSON" không phân biệt được "hết token" (sửa 1 hằng số)
   với "model dốt" (tốn $0.5 bật --paid). Đúng ca này suýt kết luận nhầm
   hướng đắt tiền.

Suýt là lần thứ SÁU họ bug "không đo được ≠ kém" — lần này ở tầng CHẨN ĐOÁN
CỦA NGƯỜI chứ không phải code (guard kho đã chạy đúng): tỉ lệ 20% "không lấy
được JSON" đọc như "flash đuối với đề 32 ngành" trong khi thật ra là ta bóp
token. Không có danh tính 2 mã trượt (VCB! SSI!) thì đã đi nhầm hướng.

**Phát hiện phụ quan trọng**: kho phân loại ĐÃ ĐẦY — 1.652 mã, chấm bằng
claude-haiku đợt 04/2026 (--query VCB: "Phân loại: 2026-04-05 | Model:
claude-haiku-4-5-20251001"). → KHÔNG cần full batch 1.700 mã nữa; route free
chỉ gánh mã niêm yết MỚI, vài call một lần. Nỗi lo quota/$0.5 cho batch đầy
gần như biến mất. Phân loại ngành 4 tháng tuổi vẫn dùng tốt (ngành hiếm đổi).

**Chốt 10/08 00:27 — sau vá 6000 token**: `--rerun-flagged VCB SSI` → **2/2
sạch, 0 errors** (4 giây); `--query VCB` → `Model: Gemini:gemini-3.5-flash`,
vẫn "Ngân hàng ~100%" — KHỚP bản Claude cũ (parity chất lượng trên ca dễ).
Điểm [8] verify TRỌN VẸN: 4/4 checkpoint.


## 2026-08-11 — Lần --eval thứ 4: hồ sơ qwen ĐÓNG (model vô tội) + 2 lưới bắt cá thật lần đầu

### qwen3.6-27b: 0.33/0.38/0.00 → 1.00/1.00/1.00

Sau vá token (400 → 2000) + fix scorer sentiment: qwen đạt TUYỆT ĐỐI cả 3
việc. Chốt: model chưa bao giờ kém — PHÉP ĐO bóp nó (reasoning model, 400
token cạn vào phần suy nghĩ). Ladder GIỮ NGUYÊN ở cả 4 điểm [2][3-6][7][8].
Mục "cảnh báo nấc yếu đang dùng" mất lý do tồn tại → BỎ (may đã hoãn — xây
trên số đo hỏng thì giờ có một cái chuông chuyên kêu oan).

Bảng điểm sạch hiện tại: 5 model đạt 1.00/1.00/1.00 (gemma-4-31b* ·
gpt-oss-120b cả Cerebras lẫn Groq · flash-lite · qwen3.6-27b) · gpt-oss-20b
1.00/0.75/0.80 (nấc phụ, đủ dùng; 0.88 → 0.75 là nhiễu mẫu 8 ca) ·
nemotron-ultra 0.75/0.88/0.80 (đo đúng lúc đang bò 127s — xem dưới).
(*gemma 1 ca hụt nhưng đủ coverage.)

### Lưới danh mục bắt cá thật: Gemini gỡ cả dòng 2.0-flash

Diff tuần đầu tiên có nội dung: Gemini **-6 model** (gemini-2.0-flash /
-flash-001 / -flash-lite / -flash-lite-001 · gemini-3-pro-preview ·
robotics-preview). KHÔNG con nào đang dùng → đúng thiết kế: ghi nhận, không
báo động. Đây chính xác là loại cảnh báo sớm user đặt hàng từ đầu ("model
nào sắp hết hạn") — nếu ladder còn ở dòng 2.0 thì tuần này đã có 🚨 TRƯỚC
khi nó chết hẳn. OpenRouter: -1 (gpt-5.3-chat, không dùng) / +4, trong đó
**nvidia/nemotron-3.5-lightning:free** — ứng viên thay nếu ultra còn bò.

### Lưới độ trễ bắt cá thật: nemotron-ultra 127.3s (161× median 0.79s)

Không phải nhiễu chạy dồn (median đã 3 mẫu, các lần trước 0.5-3.2s). Nấc dự
phòng của [2]/[3-6]/[8] đang bò; production TỰ NÉ (chat_complete timeout 25s
→ rơi nấc kế; 127s thì brief timeout 90s cũng không đỡ nổi). Chưa hành động
— nếu còn bò 1-2 tuần: probe sống nemotron-3.5-lightning:free (luật repo:
slug mới phải probe trước khi vào code) rồi bàn thay.

### Nạn nhân quota cuối cùng: Gemini flash — vá nhịp theo provider

flash: classify=1.00 nhưng 15 ca hụt (sentiment + json n/a). Nhìn lại thì CẢ
3 lần chạy flash đều là nạn nhân quota (08/08 chấm 0 oan · 09/08 json n/a ·
11/08 15 ca hụt) dù probe luôn sống — vì Gemini bóp theo PHÚT (flash ~10-15
req/phút), mà eval bắn flash-lite 25 ca rồi flash ngay trong cùng cửa sổ.
Vá: `EVAL_DELAYS = {"Gemini": 7.0}` — nhịp riêng theo provider (mirror họ
hàng với EVAL_BUDGET theo ngày). Job tuần chậm thêm ~3 phút, đổi lấy ĐO
ĐƯỢC. Suite 1624 → 1625 passed.


## 2026-08-11 (b) — Tự động hoá mục canh chừng đơn vị giá: vết máy-đọc + doctor check

User hỏi "việc canh run_daily.log làm thế nào" rồi chốt "làm cho tôi đi để
tự động nhất có thể". Thiết kế CỐ Ý không grep log: log mong manh (encoding
tiếng Việt trên Windows, không biết bat xoay vòng kiểu gì, phụ thuộc máy) —
nguồn sự thật là chính ROLLUP.

Vòng tự động khép kín, không ai phải nhớ gì:
```
_normalize_units bắn (lệch ≥100×, tự quy đổi)
  → ghi vết _meta/unit_normalizations.json   (best-effort, trần 50 event)
    → run.py doctor đọc vết                  (pipeline 18:00 chạy doctor sẵn)
      → badge sidebar 🩺 tự warn, nêu ĐÍCH DANH mã + tỉ lệ
```

Chi tiết chốt:
* Vết >7 ngày coi như đã xem → về ok (vẫn nhắc "lần cuối") — warn vĩnh viễn
  là alarm fatigue, badge kêu mãi thì người ta bỏ qua thật.
* Timestamp hỏng trong vết → coi là MỚI (thà soi thừa hơn nuốt im lặng).
* Ghi vết best-effort tuyệt đối: `_meta` hỏng (vd là FILE — bài `_live`
  06/08) thì rollup VẪN quy đổi và chạy tiếp, có test chốt.
* Message warn nêu rõ việc còn lại của NGƯỜI: soi chart mã đó xem giá liên
  tục không; nghi quy đổi OAN (chia tách tỉ lệ cực lớn?) → báo Claude.

Lưới chống chính mình: test đi qua `_normalize_units` nay sẽ ghi vết —
không redirect là suite chạy trên máy user ghi VẾT GIẢ vào kho thật, sáng
sau badge warn OAN. Thêm autouse `_rollup_meta_to_tmp_anywhere` vào
conftest (cùng họ bài học ledger 30/07: fixture chặn toàn cục, file test
mới tự động được chặn).

Suite 1625 → 1634 passed. Dòng print trong log GIỮ NGUYÊN — cho người đọc
tay khi cần; file JSON là cho máy.

## 2026-08-11 (c) — `--test-alert`: kiểm chủ động lưới an toàn cuối (user gật)

Đề xuất treo từ 30/07, user gật 11/08. `alert_ladder_down` — chuông "free
chết hết" của hệ all-free — chưa từng bắn thật, mà nó best-effort nuốt mọi
lỗi: hỏng thì chỉ biết đúng giữa sự cố, chuông câm. Các tin "Model watch"
cuối tuần đã chứng minh phần VẬN CHUYỂN (token/chat_id/format) sống; phần
còn mù là logic riêng: cổng env, cờ throttle ngày, nhúng summary_lines.

`python vnstock_llm_ledger.py --test-alert` — bắn 1 tin 🧪 (TEST) qua đúng
đường ống thật, in trạng thái từng mắt xích. Khác alert thật ĐÚNG 3 chỗ,
đều có ý:
* **KHÔNG đọc/ghi cờ throttle** — bẫy thiết kế phải né: test buổi sáng ghi
  cờ thì sự cố THẬT buổi chiều cùng ngày bị nuốt. Test chốt: chạy test-alert
  xong, alert thật NGAY SAU ĐÓ vẫn gửi được.
* **KHÔNG nuốt lỗi** — mục đích là lộ bệnh; gửi fail in rõ lý do, exit 2.
* **Gửi cả khi kill-switch tắt** (chạy tay là chủ đích) nhưng exit 1 + cảnh
  báo to "alert thật đang câm" — phát hiện env tắt nhầm chính là nửa lý do
  tồn tại của test.

Parity chốt bằng refactor: thân tin tách ra `_alert_message(context)` dùng
chung cho cả alert thật lẫn test (mirror doctrine `apply_brief_guards` —
format trôi giữa 2 đường là test hết giá trị chứng thực), có test canh.

Exit: 0 = gửi OK + gate bật · 1 = gửi OK, gate TẮT · 2 = gửi fail.
Suite 1634 → 1639 passed (5 test mới).


## 2026-08-11 (d) — Test-alert ĐẬU, và ledger nhúng trong tin tố 2 chuyện

User chạy `--test-alert` → điện thoại nhận tin 🧪 (TEST) format chuẩn →
**đường ống alert "LLM ladder DOWN" kiểm chứng đầu-cuối XONG**. Nhưng giá
trị thật của lần chạy nằm ở phần ledger NHÚNG trong tin — nó phơi ra 2 thứ:

### 1. Mistral Small — agent brief DI SẢN đang chạy thật, vô hình với mọi lưới

Dòng lạ: `Mistral:mistral-small-latest  2 call · 2 OK · $0.0039`. Truy ra:
* `MistralAgent` là agent [7] brief có từ thời tháng 5 (baseline accuracy
  22/05 từng có Mistral). Default trong code: `enabled: False` — nhưng
  config runtime máy user đang BẬT (cơ chế merge giữ lựa chọn cũ của user
  khi đổi lineup 22/07). 2 call/ngày = brief sáng + chiều.
* Lớp TRẢ PHÍ theo bảng giá ledger (0.15/0.60 $/M) — ~$0.004/ngày, nhỏ
  nhưng không phải free, và trái tinh thần chốt all-free 22/07.
* **Vô hình với mọi lưới canh**: `_BRIEF_TYPE2PROVIDER` không có "mistral"
  → --ladder không probe; model_watch._PROVIDERS không có endpoint Mistral
  → không diff danh mục; eval không đo. Chỉ dead-slug net biết slug (qua
  `_DEFAULT_AGENT_CONFIGS`). Đúng bài "lưới chỉ soi thứ được khai báo".

**Chờ user quyết**: (A) tắt agent Mistral trong ⚙️ dashboard — 10 giây,
đúng all-free; hay (B) giữ làm giọng A/B thứ ba → phải đưa Mistral vào lưới
watch (thêm provider + endpoint danh mục, một lượt code). Khuyến nghị: A,
trừ khi còn muốn so giọng nó.

### 2. Groq Qwen brief agent 0/2 hôm nay — nghi án token headroom lần thứ BA

`Groq:qwen/qwen3.6-27b  2 call · 0 OK · 2 lỗi (0 rate-limit)` — B-side của
A/B brief trượt cả 2 phát với lỗi KHÔNG phải rate-limit. Nghi án: qwen là
model REASONING, agent brief cấp max_tokens=1200 mà KHÔNG cộng think-headroom
— chỉ `GeminiAgent` có `_THINK_HEADROOM = 8000`; `_OpenAICompatAgent.generate`
mặc định không cộng. Thinking ăn hết 1200 → finish_reason=length → bị tính
là LỖI AGENT (đúng luật c1dcb14 "output bị cắt = lỗi"). Cùng họ bệnh đã vá ở
[8] classifier (800→6000) và bộ đề eval (400→2000).

**Chưa vá mù** — cần error text thật vì có 2 khả năng khác hẳn cách sửa:
finish_reason=length (→ cộng headroom, nhưng phải cân trần TPM 8K của Groq —
chính lý do Groq bị loại khỏi digest bậc 1) vs HTTP 413 TPM (→ hướng khác).
User chạy: `Select-String -Path run_daily.log -Pattern "Groq API"` dán kết
quả.

### Ghi chú đọc ledger

Probe/eval KHÔNG ghi sổ (cố ý — traffic chẩn đoán); số trong ledger là
PRODUCTION thuần. Hôm nay 114 call · 50 rate-limit nhưng ladder trụ: 55 OK
rải đều các nấc, output vẫn ra — hệ chạy đúng thiết kế trong một ngày free
tier khó ở.


## 2026-08-11 (e) — `run_daily.log` KHÔNG TỒN TẠI: pipeline chưa bao giờ ghi log

User chạy lệnh Select-String tôi đưa → `Cannot find path run_daily.log`.
Truy ra sự thật to hơn nhiều so với một cái tên file sai:

* Cả 2 task scheduler (`Daily Pipeline`, `Weekend Pipeline`) chạy
  `python run.py ... all/weekend` TRỰC TIẾP — Task Scheduler VỨT stdout.
* `scripts/run_daily.bat` (chạy tay) cũng không redirect — output ra console
  rồi mất khi đóng cửa sổ.
* → **`run_daily.log` chưa bao giờ tồn tại** dưới cấu hình hiện tại. Mọi
  tham chiếu "soi run_daily.log" trong notes (kể cả mục verify 29/07 "log
  phải có dòng LLM audit") là DI TÍCH — chưa ai từng làm được các mục đó.
* Hệ quả hay: thiết kế vết-JSON cho đơn vị giá (11/08 (b)) đúng hơn mình
  tưởng — bản grep-log nếu làm sẽ âm thầm grep một file không tồn tại.

### Hai vá để "lỗi sống sót mà không cần log"

1. **`python vnstock_memory.py --recent N`** — vòi đọc bộ nhớ brief từ
   terminal. Lỗi agent brief VẪN ĐANG được lưu vào SQLite
   (`save_brief(..., error=err)`) từ trước tới nay — chỉ là không có cách
   móc ra (python -c inline bị PowerShell nuốt nháy 2 lần rồi). Dòng ❌ in
   lỗi NGUYÊN VĂN → bằng chứng vụ Groq qwen 0/2 hôm 11/08 truy được NGAY,
   không cần chờ phiên sau.
2. **Ledger giữ `last_error`** (đuôi 160 ký tự, mỗi dòng provider:model) —
   `--show` và TIN ALERT từ nay tự mang theo "vì sao fail". Trước đó ledger
   chỉ đếm: thấy 59 lỗi mà không ai biết lỗi GÌ.

CHƯA làm (ghi lại làm tuỳ chọn): sửa ps1 cho task bọc `cmd /c ... >> log`
để có log thật — cần chạy lại script as-admin trên máy; với bộ
badge/JSON/last_error hiện tại, log thô còn ít giá trị, để user quyết sau.

Suite 1639 → 1645 passed.


## 2026-08-11 (f) — Bằng chứng Groq về: 413 CẤU TRÚC, nghi án headroom SAI

`vnstock_memory.py --recent 6` (CLI vừa ship) móc được lỗi nguyên văn từ
SQLite: **`413 Payload Too Large ... Request too large for model
qwen/qwen3.6-27b`**. Nghi án think-headroom của tôi SAI — và kỷ luật "ĐỪNG
vá mù" trả công cụ thể: vá headroom là NỚI max_tokens, tức làm request TO
THÊM — bệnh nặng thêm đúng theo hướng vá.

Đau nhất: notes 22/07 (dòng ~3302) đã tiên đoán ĐÚNG CHỖ NÀY — "prompt brief
~10K token (Groq TPM 8K là biên rủi ro 413)". Rủi ro đã ghi thành chữ, nay
thành hiện thực, và suốt 3 tuần không ai biết vì pipeline không có log
(entry 11/08 (e)). Chuỗi công cụ tuần này (ledger đếm → test-alert nhúng
ledger → memory CLI) chính là thứ biến nó từ vô hình thành 1 dòng ❌.

Kết luận:
* **Bệnh CẤU TRÚC**: prompt brief ~10K > trần 8K/request của Groq free —
  không model Groq nào ở trần đó gánh nổi, không sửa bằng token/headroom.
  A/B "Gemini vs Groq" trên giấy đã CHẾT TỪ 22/07 (ngày migrate llama→qwen).
* **A/B thực tế vẫn sống với 4 giọng** (điểm auto-score 11/08): OpenRouter
  nemotron-super **0.862** · Mistral Small **0.836** · Cerebras gpt-oss-120b
  **0.834** · Gemini flash **0.83**. Groq 0.0 (fail).
* **qwen KHÔNG mất gì ở [2][3-6][8]** — prompt các điểm đó nhỏ, bộ đề 1.00.
  Chỉ riêng ghế brief agent là ngồi nhầm chỗ.
* → Khuyến nghị: TẮT agent Groq trong ⚙️ dashboard (việc user, 10 giây).
  Không có đường cứu trên Groq free; giọng thay thế đã thừa.

Phát hiện kèm: **3 tên agent đang NÓI DỐI** — "Cerebras/OpenRouter/Groq
Llama-3.3-70B" nhưng model thật là gpt-oss-120b / nemotron-super / qwen.
Di tích trạng thái nửa-migrate (slug đã mới, tên còn cũ → fix f13a33f không
kích hoạt lại được). Cosmetic; user đổi tên trong ⚙️ khi tiện.

Bug tự ship tự bắt trong ngày: CLI `--type` bản đầu cho choices
`morning/close` — giá trị THẬT trong DB là `morning/afternoon/allocation`
("close" chỉ là tên gọi miệng). Filter không bao giờ khớp được dòng nào.
Bài học: ship filter phải soi GIÁ TRỊ THẬT của data, không đặt theo thói
quen gọi tên. Suite 1645 → 1646.


## 2026-08-11 (g) — Thi hành 2 quyết định: TẮT ghế brief Groq (trong code) + Mistral VÀO LƯỚI

User chốt: "tắt Groq giúp tôi luôn" + "giữ Mistral + vào lưới".

### Tắt Groq — cơ chế tắt-một-lần, không giành tay lái

`_BRIEF_AGENT_DISABLES` trong vnstock_brief: registry (type, model) → lý do,
họ hàng với `_MODEL_MIGRATIONS` nhưng nghĩa khác — migration đổi slug CHẾT
sang slug SỐNG; đây là ghế NGỒI NHẦM CHỖ (model sống, việc không gánh nổi:
prompt brief ~10K > trần 8K/request Groq free, 413 cấu trúc). Tắt kèm marker
`auto_disabled` + in một dòng nói to; user bật lại trong ⚙️ = chủ đích,
load sau KHÔNG tắt nữa (có test chốt cả 2 chiều).

**Đổi chủ ý có ghi chép**: test 29/07 chốt "migration giữ nguyên enabled" —
nhưng CHÍNH kịch bản đó (llama enabled → qwen giữ enabled) sinh ra 3 tuần
413 câm. Test sửa theo chủ ý mới, comment trỏ về đây.

Kèm: pass sửa TÊN NÓI DỐI (hoàn tất f13a33f cho trạng thái nửa-migrate) —
tên nhắc model ĐÃ MIGRATE ĐI của cùng type mà không nhắc model hiện tại →
thay bằng tên mặc định; "Cerebras Llama-3.3-70B" (chạy gpt-oss-120b) hết
nói dối, tên user tự đặt không đụng.

### Mistral vào lưới — provider hạng nhất

* `model_watch._PROVIDERS` += Mistral (env MISTRAL_API_KEY, endpoint chat +
  catalog /v1/models dạng openai) → probe hàng tuần + diff danh mục.
* `_BRIEF_TYPE2PROVIDER` += mistral → slug vào `_ladder_slugs` tag [7].
* `EVAL_DELAYS` += Mistral 2.0s (free tier bóp theo giây) → bộ đề chấm nó
  từ T7 tới.
* Luật "slug mới phải probe sống trước": thoả bằng bằng chứng MẠNH HƠN probe
  — đang chạy thật trong production (2 OK, score 0.836 ngày 11/08).
* Dead-slug net đã phủ sẵn (slug nằm trong _DEFAULT_AGENT_CONFIGS).

Hiệu lực trên máy user: lần load config kế tiếp (mở dashboard hoặc pipeline
18:00) tự tắt Groq + sửa tên + lưu file — 413 hằng ngày chấm dứt từ mai.
Suite 1652 passed.

## 2026-08-12 — Đóng tuỳ chọn "giấu số model": user quyết GIỮ SỐ

Mục tuỳ chọn treo từ 08/08 (giấu số lượng model ở dòng "không đổi" của báo
cáo model watch). Phân tích 12/08: trên dòng "không đổi" con số mang 0 bit
(tập trùng từng phần tử ⇒ size trùng; đọc cụt luôn rơi vào nhánh ❓ chứ
không ra "không đổi") — nhưng user chọn **GIỮ NGUYÊN** cho quen mắt. Quyết
định đóng, đừng đề xuất lại.

## 2026-08-12 — Ghi nguyên tử đợt 2: lỗ NẶNG HƠN cả ca CRITICAL đã vá 06/08

Dọn mục MEDIUM/LOW của audit 06/08 theo thứ tự ưu tiên tự đặt (③ replica →
① nguyên tử → ④ tách file → ② hiệu năng). Đây là ①.

Quét bằng MÁY (không đoán) 55 điểm ghi toàn repo → lọc dương tính giả
(st.write UI, stdout, sandbox stream) → còn các file giữ STATE. Phát hiện
ngược kỳ vọng: phần lớn module ĐÃ ghi nguyên tử sẵn (tmp + os.replace, lặp
pattern ở ~15 chỗ). Nợ thật nhỏ hơn ghi chú audit — nhưng lỗ còn lại NẶNG
hơn nhiều so với mô tả "cache macro, _meta/*.json":

### `VnStockWarehouse._write_parquet` — xoá-rồi-ghi

Dùng `pq.write_to_dataset(..., existing_data_behavior="delete_matching")`:
XOÁ partition cũ RỒI mới ghi. Chết giữa hai bước (Task Scheduler kill 120',
máy ngủ, Ctrl+C, mất điện — đúng loạt kịch bản vnstock_parquet_io đã liệt
kê) thì partition BIẾN MẤT HẲN, không phải hỏng. Tệ hơn ca CRITICAL 06/08:
file cụt còn để lại dấu vết, mất partition thì `_read_ticker` trả DataFrame
rỗng — im lặng tuyệt đối.

Vá: ghi từng file year qua `write_table_atomic`. Bẫy khi vá (test bắt):
file year KHÔNG được chứa cột ticker/year — chúng nằm trong TÊN THƯ MỤC,
`_read_ticker` đọc bằng hive partitioning nên nhét vào file là trùng tên cột
→ pyarrow lỗi → `except` nuốt → kho đọc ra RỖNG. Thêm `_YEAR_FILE_SCHEMA`
(mirror `vnstock_rollup.PRICE_SCHEMA`). Verify tay: 3 đợt ghi nối tiếp bắc
qua năm → gộp đúng, dedup bản mới thắng, và ROLLUP đọc lại được y nguyên
(hai module cùng layout).

### `_save_meta` — `open(w)` cắt file về 0

Chết giữa chừng = meta cụt → `_get_last_date` trả None cho MỌI mã → updater
tưởng kho trống.

### Bốn file state còn lại

`brief_agents.json` (LỰA CHỌN của user — mất là phải chỉnh tay lại) ·
kho phân loại 1.652 mã + company profiles (chấm lại tốn cả batch LLM) ·
model_status/history · vết quy đổi đơn vị giá. Tất cả qua helper mới
`write_json_atomic` (serialize TRƯỚC khi đụng đĩa nên payload hỏng cũng
không cắt cụt file cũ; `default=str` cố ý cho date/Path trong _meta).

### Lưới chặn tái phát

`test_state_writers_stay_atomic` — parametrize trên danh sách file "giữ
state của user/kho" (KHÔNG phải mọi file: cache dựng lại được, không đáng
siết). Quét mã nguồn, thấy điểm ghi không có os.replace/helper trong 8 dòng
quanh đó là ĐỎ. Thêm điểm ghi state mới → khai vào `_MUST_BE_ATOMIC`; lưới
chỉ soi thứ ĐƯỢC KHAI BÁO (bài học lặp lần thứ ba tuần này).

Suite 1652 → 1666 passed (14 test mới).


## 2026-08-12 (b) — Gỡ test replica ĐỢT 1: WSS sạch hẳn + 2 module tách khỏi dashboard

Mục ③ của bó MEDIUM/LOW. Dùng workflow 8 agent đối chiếu TỪNG hàm replica
với bản thật (17 hàm) trước khi động dao — kết quả là bản đồ drift + kế
hoạch tách module, không phải đoán.

### Phát hiện quan trọng nhất: 4 vùng trôi = 4 vùng TRẮNG TEST

`compute_indicators` · `cell_color` · `cell_weight` · `BarAggregator` đều
DRIFTED (replica là ảnh chụp CŨ). Nhưng đổi sang import thật thì test vẫn
XANH — vì không test nào chạm nhánh đã trôi. Tức chỗ trôi trùng khít chỗ
không được phủ. Ví dụ cụ thể: bản thật `compute_indicators` có
`.where(loss != 0, 100.0)` (vá lỗi chart auto-fit, ảnh hưởng TRỰC TIẾP tín
hiệu rsi_sig: rsi=100 → "SELL", NaN → "NEUTRAL") — replica thiếu, và không
test nào phủ nhánh loss==0.

### Đợt 1 (làm 12/08)

* **tests/test_wss.py sạch replica hoàn toàn** — import thật `is_futures`,
  `BarAggregator`, `accum_to_delta`, `MAX_SINGLE_TICK_VOLUME`. Lý do lịch
  sử ("heavy init at import") ĐÃ HẾT HẠN từ commit 6cb23d9 (07/08); đo lại
  12/08: import mất **0.4s**, không tác dụng phụ. Replica BarAggregator đã
  trôi thật: thiếu `diagnostics()`, thiếu 2 khoá chẩn đoán, chép cứng
  500_000 thay vì dùng hằng số.
* **`dashboard/volume_profile.py`** (64 dòng) — `calc_value_area`. Agent
  đối chiếu ở mức AST: replica tương đương TUYỆT ĐỐI bản thật.
* **`dashboard/money_flow_score.py`** (68 dòng) — `compute_money_flow_score`
  + `score_label` + `score_bar_html` (phải cùng file: hàm 3 gọi hàm 2).
* `vnstock_dashboard` giữ TÊN CŨ bằng alias import → mọi chỗ đang gọi
  không gãy.

### Còn lại (đợt 2) — 9 replica, rủi ro cao hơn

`_normalize_price_units` + `_normalize_live_price` (có `@st.cache_data`,
và `dashboard/analysis_tab.py:406` import ĐỘNG trong thân hàm — grep dễ sót)
· `compute_indicators` (DRIFTED, ảnh hưởng tín hiệu) · `cell_color`/
`cell_weight` (DRIFTED) · watchlist I/O (cache + `.clear()`) ·
`_build_ps_command` (chỉ tách phần dựng chuỗi; `launch_in_new_console` phải
Ở LẠI root vì dùng `Path(__file__).parent`) · `_get_sector` (về
`vnstock_sectors.py`, không tạo file mới).

Suite 1666 passed (số không đổi — đợt này ĐỔI CHẤT chứ không thêm lượng:
17 test WSS + 4 nhóm dashboard nay bảo vệ code THẬT).


## 2026-08-12 (c) — Gỡ test replica ĐỢT 2: hết replica, và 45 test cho vùng trắng

Xong mục ③. `tests/test_dashboard.py` nay **không còn một hàm chép tay nào**.

### 6 module mới (đều KHÔNG import streamlit → test import thẳng được)

| Module | Nội dung | Vì sao ở đó |
|---|---|---|
| `vnstock_price_units.py` (73) | `normalize_price_units`, `normalize_live_price` | ngưỡng >500 là **bất biến dữ liệu của cả pipeline**, không riêng UI (`vnstock_brief.py:1820` đã tự nhắc "cùng quy ước") |
| `dashboard/chart_indicators.py` (95) | `compute_indicators` | thuần pandas |
| `dashboard/table_style.py` (87) | `cell_color`, `cell_weight` | trước là **closure lồng trong hàm render** → test không với tới được |
| `dashboard/watchlist_io.py` (43) | `load/save_watchlist(path,…)` | state của user |
| `vnstock_console_launch.py` (37) | `build_ps_command` | CHỈ phần dựng chuỗi |
| `vnstock_sectors.py` (+73) | `SECTOR_GROUPS/ORDER/ICONS` + `get_sector` | gộp vào module ngành sẵn có, không đẻ file mới |

`vnstock_dashboard.py`: **3.974 → 3.715 dòng** (−259). Mọi tên cũ giữ nguyên
bằng alias import — `_normalize_price_units` (screener_tab lấy qua
`_vnd.`), `_normalize_live_price` (analysis_tab import **ĐỘNG trong thân
hàm** dòng 406), `_get_sector`/`SECTOR_*` (money_flow, portfolio,
vn30_weights), `cell_color`/`cell_weight`, `compute_indicators`.
`launch_in_new_console` Ở LẠI root (cần `Path(__file__).parent`), chỉ chuỗi
PowerShell đi ra.

### Vá kèm: watchlist cũng là ghi-thẳng

`save_watchlist` cũ `open(w)` → cắt file về 0 trước khi ghi. Chết giữa chừng
= **watchlist user tự tay dựng biến mất**, mà `load_watchlist` nuốt
JSONDecodeError trả `[]` nên mất IM LẶNG. Nay qua `write_json_atomic`, và
`dashboard/watchlist_io.py` vào lưới `_MUST_BE_ATOMIC` (mục thứ 6).

### Phần trả lại giá trị thật: `tests/test_dashboard_branches.py` (45 test)

Đợt 1 đã chỉ ra "chỗ trôi trùng khít chỗ không được phủ". Đợt 2 phủ đúng
những chỗ đó:

* **RSI khi `loss == 0`** — nhánh `.where(loss != 0, 100.0)`, chính là bản vá
  bất biến "4 panel cùng số bar". Có cả test *chứng minh công thức cũ SAI*
  (`naive.iloc[-1]` là NaN) để lần sau ai định "đơn giản hoá" thì đỏ ngay.
* **VWAP intraday** — replica không có LẤY MỘT DÒNG: có/không thêm cột theo
  daily-vs-intraday, **reset theo phiên** (phiên trước giá 20, phiên sau 30 →
  bar đầu phiên sau phải đúng 30), thứ tự band ±1σ/±2σ, số dòng không đổi.
* **`cell_color`** — nhánh `Trend`/`Ticker`/`Ngành` và hai bậc RSI mềm 40/60
  mà replica không hề có.
* **`vnstock_sectors`** — hai chiều của bảng ngành: nhóm nào map tới mà thiếu
  trong `SECTOR_ORDER` là **nhóm tàng hình** (bảng ngành lặng lẽ bỏ qua);
  ngược lại là nhóm hiện rỗng mãi mãi.

Suite **1712 passed** (+46). `test_dashboard.py` + file mới vào danh sách
`--fast`.


## 2026-08-12 (d) — Tách `vnstock_brief.py`: 6.807 → 4.045 dòng (mục ④, cụm 1)

Cắt theo ĐƯỜNG RANH GIỚI THẬT, không cắt theo số dòng. Trước khi động dao,
dựng bản đồ phụ thuộc bằng AST (free-name của từng node so với binding của
phần còn lại) — nhờ vậy biết CHÍNH XÁC hợp đồng giữa hai bên thay vì đoán.

### Hợp đồng đo được (chứ không phỏng đoán)

Cụm validator (2.548 dòng, 49 hàm) hoá ra gần như tự chứa: 26/31 hằng số nó
dùng đã nằm SẴN trong cụm. Chỉ 11 tên phải nhập từ ngoài, và chiều ngược lại
đúng 3 tên (`_re`, `apply_brief_guards`, `validate_brief_factuality`).

### 3 module, phụ thuộc MỘT CHIỀU

* **`vnstock_brief_canon.py`** (290) — hằng số + khối canon: `VN30_TICKERS`,
  `_FINANCIAL_TICKERS`, ngưỡng `_SR_MAX_MOVE_PCT`/`_WATCHLIST_GTGD_MIN_TY`,
  bước giá `_vn_tick`/`_round_tick`, và 6 hàm dựng khối
  (`_macro_body_lines`, `_market_news_body_lines`, `_macro_reports_body_lines`,
  `_allocation_table_lines`, `_portfolio_fact_line`, `_gtgd_close_frame`).
  **Vì sao module này phải tồn tại:** prompt builder dựng khối để đưa vào
  prompt, guard dựng LẠI đúng khối đó để ép output khớp. Hai bên phải dùng
  CHUNG một hàm — tách đôi là guard sẽ "sửa" brief về một chuẩn khác chuẩn đã
  đưa vào prompt, loại lỗi im lặng khó lần nhất.
* **`vnstock_brief_guards.py`** (2.646) — 44 guard + chuỗi `apply_brief_guards`.
  Chuỗi về ở CÙNG FILE với các guard nó gọi.
* **`vnstock_brief.py`** (4.045) — context → prompt → agent → gọi chuỗi.

Chiều: brief → guards → canon. Mọi tên re-export qua `vnstock_brief` (84 tên)
nên `vnstock_events`, `vnstock_train`, `vnstock_telegram`, `vnstock_diagnose`,
`vnstock_stance_track` và toàn bộ test cũ **không phải sửa một dòng nào**.

### `tests/test_brief_split.py` (27 test) — giữ cho ranh giới khỏi mờ lại

Tách file chỉ có giá trị nếu ranh giới không mờ lại. Ba kiểu mờ đã thấy thật
trong repo này, mỗi kiểu một lưới:

1. **Vòng import lén** — soi cả `import` LƯỜI trong thân hàm, không chỉ đầu file.
2. **Định nghĩa trùng** — đúng bài học mục ③: bản chép sống song song rồi trôi,
   test vẫn xanh vì nó soi bản chép. Nay tên định nghĩa ở guards/canon mà
   `vnstock_brief` cũng định nghĩa lại là ĐỎ (re-export không tính).
3. **Guard viết ra rồi bỏ quên** — họ lỗi lặp nhiều nhất repo này ("lưới chỉ
   soi thứ ĐƯỢC KHAI BÁO"). `enforce_*` không nối vào chuỗi = code chết trông
   y hệt code sống, mà test riêng của nó vẫn xanh. Lưới soi cả hai chiều: guard
   mồ côi, và chuỗi gọi tên không tồn tại.

Kèm lưới re-export quét TOÀN BỘ tên đã chuyển (không chỉ danh sách tay).

Suite **1739 passed** (+27). CLAUDE.md đã sửa bản đồ kiến trúc + quy ước
"thêm guard".

### Còn lại của mục ④

`vnstock_brief_guards.py` (2.646) và `dashboard/market_tab.py` (2.566) vẫn
trên mốc 800 dòng. Cắt tiếp được: guard chia theo chủ đề (chữ nghĩa / con số /
cấu trúc), chuỗi giữ nguyên một chỗ. Làm DẦN, mỗi lần một cụm.


## 2026-08-12 (e) — Tách `market_tab.py`: 2.567 → 1.295 (mục ④, cụm 2)

Đây là ca NẶNG HƠN brief dù ít dòng hơn: cả tab là **MỘT hàm 2.544 dòng** —
đúng thứ rule của repo cấm (hàm < 50 dòng). Brief 6.8K dòng ít ra còn chia
sẵn thành 128 hàm.

### Cắt lớn: panel AI Market Brief (1.172 dòng)

Đo bằng AST trước khi động dao (tên tự do của khối so với binding của phần
trước nó): khối chỉ cần **ĐÚNG MỘT** tên từ scope ngoài — `st`. Vậy là cắt
được nguyên khối sang `dashboard/market_brief_panel.py::render_brief_panel()`,
mọi thứ khác nó tự import trong thân. Giữ nguyên nết import LƯỜI Streamlit để
pytest vẫn import module được (có test canh).

Khối này gom: cài đặt agent · nút sinh brief · consensus · bảng điểm độ chính
xác · lịch sử brief · panel chiến lược + equity curve · khuyến nghị đã đóng ·
training · scan.

### Cắt nhỏ nhưng đáng giá hơn: thang màu + định dạng ô

`dashboard/market_table_format.py` (134) + `dashboard/sparkline.py` (65) —
6 hàm trước là closure nên **chưa từng có test**.

Phát hiện khi kéo ra: `_amp_color` bị **chép nguyên bản** thành `_dd_amp_color`
cho khối drill-down, hai bản y hệt chỉ khác biến closure — đúng họ lỗi vừa dọn
ở mục ③. Và hai bản ĐÃ lệch thật: bản bảng tổng có chốt chặn `range = 0 → 1`,
bản drill-down `max - min` trần trụi ⇒ mọi giá trị bằng nhau là **chia 0**.
Nay `scale_range()` dùng chung, hết đường lệch.

Sửa lại thành hàm nhận `(vmin, vrange)` làm THAM SỐ thay vì bắt qua closure —
nhờ vậy bảng tổng và drill-down dùng chung một hàm với hai thang khác nhau.

### Đối chiếu vi phân trước khi tin

Không tin mắt: chạy bản CŨ (chép từ git HEAD) và bản mới trên cùng lưới giá
trị, so cả **kiểu ngoại lệ** — **1.480 phép so sánh cho bảng, 24 cho
sparkline, 0 khác biệt**. Sau đó mới chốt thành 44 test
(`tests/test_market_table_format.py`), nhắm vào bất biến dễ hỏng âm thầm:
thiếu data phải ra "—" chứ không ra 0; thang phẳng không được chia 0; chữ trên
nền đậm phải đổi trắng; điểm sparkline không được vẽ ra ngoài khung.

Suite **1785 passed** (+46).

### Còn lại của mục ④ (sau cụm 2)

* `vnstock_brief_guards.py` (2.646) — chia theo chủ đề chữ nghĩa/con số/cấu trúc
* `dashboard/market_brief_panel.py` (1.194) — bản thân nó cũng nên chia panel con
* `market_tab` còn 2 closure không tách được ngay: `_live_market_fragment`
  (fragment Streamlit) và `_build_commentary` (đọc `st.session_state` + `idx_df`;
  muốn tách phải luồn 2 tham số vào — đáng làm vì đó là 220 dòng SINH CHỮ
  tiếng Việt cho user mà chưa có test)


## 2026-08-12 (f) — Mục ④ XONG: nốt 3 việc còn treo, mọi file mới đều < 800 dòng

### 1. `_build_commentary` → `dashboard/market_commentary.py` (280)

220 dòng SINH CHỮ tiếng Việt cho user, chưa từng có test. Hai thứ nó bắt qua
closure (`st.session_state`, `idx_df`) thành THAM SỐ ⇒ hết dính Streamlit.
Chia ba đúng ba mục nó vốn sinh: `index_strength_lines` · `breadth_lines` ·
`quant_lines`.

Ngưỡng nay có TÊN ở đầu file (`_TREND_STRONG_UP`, `_MA200_BROAD_UPTREND`, …):
đây là **lời khuyên gửi tới user**, không phải hằng số kỹ thuật — sửa số ở đây
là đổi lời khuyên, phải thấy rõ chứ không nằm rải trong 220 dòng.

Đối chiếu vi phân trước khi tin: bản cũ (chép từ commit faf4667) vs bản mới
trên **600 tổ hợp** (breadth × chỉ số × bảng ngành × bảng mã, kể cả
None/rỗng/thiếu cột) — **0 khác biệt**. 37 test.

**Cố ý GIỮ một wart**: thị trường xấu toàn tập thì tiêu đề "🎯 Ngành đáng quan
tâm" vẫn hiện dù không có dòng nào bên dưới (tiêu đề in trước vòng lặp). Đổi
output nhìn thấy được TRONG LÚC refactor là cách nhanh nhất làm refactor mất
tin cậy — muốn sửa thì sửa RIÊNG, có test đi kèm.

### 2. `vnstock_brief_guards.py` 2.646 → 244, chia 3 chủ đề

Phân nhóm bằng dependency analysis chứ không bằng cảm giác: 44 guard + 24 hằng
số/helper, tính xem mỗi hằng số bị NHÓM NÀO dùng. Kết quả: chỉ **4 thứ** dùng
chung (`_parse_vn_number`, `_SECTION_EMOJIS`, `_is_section_start`,
`_PIVOT_LABEL_RE`) → `_guards_common` (64). Còn lại rơi gọn vào đúng một nhóm.

| Module | Dòng | Lo phần |
|---|---|---|
| `_guards_sections` | 1.204 | brief nói **SAI CHUYỆN GÌ** (dựng lại khối canon) |
| `_guards_numbers` | 1.061 | brief nói **SAI SỐ / SAI CHIỀU** |
| `_guards_text` | 233 | brief **lộ ruột / nói nhảm** |
| `_guards_common` | 64 | tiện ích cả ba dùng |
| `vnstock_brief_guards` | 244 | **chuỗi** + validator + re-export |

Ba nhóm **không import lẫn nhau** và không import file chuỗi — có test canh cả
ba chiều. Thêm 3 lưới nữa: guard không được nấp ngoài 3 module chủ đề (nấp là
lọt khỏi lưới "guard mồ côi"), chuỗi không được gọi trùng, và số guard gọi phải
BẰNG số guard định nghĩa.

### 3. `market_brief_panel.py` 1.194 → 42, chia 5 panel

Lại đo bằng AST: 5 panel con chỉ dính nhau qua `st` + vài tên import từ
`vnstock_brief` — tức chúng **vốn đã rời nhau**, chỉ là nằm chung một hàm.
`brief_agent_settings` (125) · `brief_run_panel` (184) ·
`brief_accuracy_panel` (57) · `brief_history_panel` (196) ·
`brief_strategy_panel` (663). File gốc còn đúng việc điều phối.

Lưới kèm theo: mọi panel phải import Streamlit LƯỜI (import ở cấp module là kéo
runtime vào lúc pytest thu thập — đúng thứ khiến cả tab trước đây không test
được), phải nullary, và **panel nào cũng phải được gọi** (panel viết ra mà quên
gọi = code chết trông y như code sống).

### Kết

Suite **1856 passed** (+34 so với cụm 2, +190 so với đầu đợt). Không còn file
NÀO do đợt tách này sinh ra vượt 800 dòng. `vnstock_brief.py` (4.045) và
`vnstock_dashboard.py` (3.715) vẫn lớn nhưng đã ngoài phạm vi audit 06/08;
muốn cắt tiếp thì mục tiêu rõ ràng là `build_prompt` (591 dòng) và
`collect_context` (356) — đó là chia HÀM, việc khác loại với chia file.


## 2026-08-12 (g) — Soi `build_prompt`/`collect_context`: KHÔNG chia hàm, nhưng tìm ra lỗ thật

User hỏi "chia tiếp có lợi ích gì không". Đo trước khi trả lời — và câu trả
lời hoá ra là **KHÔNG chia, nhưng có lỗi phải vá**.

### Đo cái gì

`build_prompt`: 591 dòng, **94 `if`**, 121 biến cục bộ, lồng sâu 6.
`collect_context`: 356 dòng, 39 `if`, **15 `try/except`**.

Chia cơ học 25 khối của `build_prompt` thành 25 hàm = churn rủi ro cao (121
biến phải luồn qua chữ ký) đổi lấy một con số dòng đẹp hơn. **Không làm.**
Nhưng quét thì lộ ra thứ đáng giá hơn nhiều.

### Lỗ 1: khối prompt biến mất âm thầm → model bịa

Trong `build_prompt` có sẵn một bất biến ghi rõ bằng chữ:

> "CRITICAL anti-hallucination invariant: … a missing block leaves a vacuum
> the LLM fills from imagination."

Nhưng nó chỉ được áp cho **5 khối**, bằng tay, không có lưới. Quét AST 17 khối
prompt có điều kiện → **11 khối biến mất âm thầm**.

Không phải cả 11 đều sai, và đó chính là lý do lưới phải là DANH SÁCH KHAI BÁO
chứ không phải luật quét mù:
* khối **cảnh báo** (độ tươi dữ liệu, ràng buộc bias) chỉ hiện KHI CÓ vấn đề →
  vắng mặt là ĐÚNG;
* khối **dữ liệu** mà template lại ra lệnh "dùng đúng block ở trên" → vắng mặt
  là để lại khoảng trống, mà model vẫn buộc phải nộp mục đó.

Vá 3 khối, chọn đúng 3 vì đọc template thấy nó trỏ thẳng vào:
* **Top Gainers/Losers** — nặng nhất. Template nói "CHỈ chọn mã trong block
  Top Gainers/Losers CÓ DẤU ⭐", còn thêm "block đó BÌNH THƯỜNG có sẵn vài mã",
  trong khi vẫn đòi tối đa 3 setup. Khối vắng = model được lệnh chọn từ danh
  sách KHÔNG TỒN TẠI → bịa mã + bịa giá.
* **🎯 Dẫn dắt/Tụt hậu** — template có mục BẮT BUỘC "## 🏆 Dẫn dắt & Tụt hậu"
  trỏ thẳng vào block này.
* **Quant Market Regime** — template ràng buộc stance/hướng setup theo regime.

`tests/test_prompt_sentinels.py` (20 test) canh cả hai chiều: khối khai báo
phải cảnh báo khi rỗng, VÀ khối cảnh-báo-theo-thiết-kế phải im khi không có gì
để cảnh báo (sentinel bật nhầm còn tệ hơn không có — nó dạy model im lặng).

### Lỗ 2: 13 nguồn nuốt lỗi im lặng, breadcrumb duy nhất thì không ai đọc

`collect_context` gọi ~15 nguồn best-effort. 13 chỗ `except Exception: pass`,
và `ctx["quant_error"]` — grep toàn repo: **viết ra rồi KHÔNG AI ĐỌC**.

Tin tốt (kiểm rồi mới nói): đây KHÔNG phải họ lỗi "không đo được ≠ đo ra kết
quả xấu". `ctx` khởi tạo bằng `[]`/`{}` nên nguồn hỏng để lại RỖNG, và prompt
đọc rỗng thành "không có data" → sentinel bật. Không có ca nào biến lỗi thành
số 0 giả.

Vấn đề còn lại chỉ là MẤT DẤU: brief thiếu hẳn một mục mà không ai biết nguồn
nào chết. Vá bằng `_note_loader_error(ctx, tên, lỗi)` — ghi vào
`ctx["loader_errors"]` + một dòng WARNING vào `run_daily.log` (chỗ user THẬT
SỰ đọc). Không đổi luồng: vẫn nuốt lỗi, vẫn chạy tiếp.

`tests/test_loader_breadcrumbs.py` (12 test). Lưới có một ranh giới CÓ LÝ DO:
chỉ soi `except` ở TẦNG NGUỒN, bỏ qua handler trong hàm con lồng bên trong
(`_morn()` bọc `float(v)` hỏng ở một ngày lịch sử là chuyện thường — ghi vết ở
đó chỉ tạo báo động giả, mà báo động giả làm người ta ngừng đọc cảnh báo thật).

Suite **1888 passed** (+32).


## 2026-08-12 (h) — Render smoke test: máy tự kiểm phần UI vừa tách

Đợt tách kéo ~2.400 dòng UI ra khỏi hai hàm khổng lồ, mà suite chỉ soi được
phần THUẦN (định dạng, nhận định, sparkline). Rủi ro còn lại rất cụ thể: **cắt
khối ra mà rơi mất một biến** — thứ chỉ lộ khi mở dashboard bằng mắt.

`tests/test_tab_render_smoke.py` (9 test) gọi THẲNG `render_market_tab()` và
`render_brief_panel()` với một Streamlit giả (widget vừa là giá trị vừa là
context manager; `vnstock_dashboard` bị stub vì module thật dựng UI ngay khi
import). Ba đường: kho trống · có data đầy đủ · đã chọn ngành để drill-down
(chạm thang màu riêng của drill-down). Cộng 5 test gọi LẺ từng panel brief —
panel phải tự đứng được, không dựa vào biến panel trước tình cờ để lại.

Nói rõ giới hạn để không tưởng bở: test này KHÔNG kiểm hiển thị đúng/đẹp, và
KHÔNG chạy nhánh sau khi bấm nút (nút giả luôn trả "không bấm" — train/scan/
gọi LLM là việc thật). Nó trả lời đúng một câu: *code có chạy hết không*. Đó
lại chính là rủi ro của một đợt refactor.

Suite **1897 passed** (+9), `--fast` **1435 passed / 33.8s**. Phần còn phải
dùng mắt đã gom vào mục "🔴 VIỆC TAY" ở cuối file.


## 2026-08-13 — Vòng lặp `--fast` bị ì: đo trên MÁY THẬT mới ra thủ phạm

User chạy `--fast` trên máy mình: **143.87s**, trong khi CLAUDE.md ghi vòng
lặp này vốn ~26s. Container CI báo 30s nên KHÔNG tự thấy được — máy có kho dữ
liệu đầy đủ + mạng thật chậm hơn nhiều lần. Bài học nhỏ: **thời gian test phải
đo ở nơi có dữ liệu thật**, con số CI chỉ để so tương đối.

Thêm `python run.py test --fast --slow` (xếp hạng 20 test chậm nhất) rồi nhờ
user chạy. Bảng đó chỉ thẳng vào thủ phạm:

### Thủ phạm 1 — do chính đợt này gây ra (đã vá)

* `test_loader_breadcrumbs.py` gọi `collect_context()` THẬT **4 lần**
  (1 + 3 tham số hoá). Mỗi lần đọc parquet + JSON của ~15 nguồn. →
  fixture `scope="module"`, còn 1 lần. **143.87s → 108.63s**.
* `test_tab_render_smoke.py` ba test render ngốn **20.5s = 19% cả vòng lặp**:
  chúng stub `vnstock_dashboard` nhưng vẫn để đường quant chạy THẬT
  (`vnstock_market_analyzer` đọc quarantine/ex-div/foreign-flow, `vnstock_memory`
  mở SQLite). Nay stub thêm 3 module đọc đĩa đó. Trên CI: 2.44s → 0.42s.

### Phát hiện phụ, đáng giá hơn cả phần tốc độ

Khi stub `vnstock_memory` bằng bản trả RỖNG (cố ý, không dùng MagicMock — xem
docstring), lộ ra: Streamlit giả **sót `select_slider`** → panel Lịch sử brief
nhận MagicMock, so sánh `> 0` ném TypeError, panel rơi vào `except` rồi tự tắt
— **mà test vẫn báo PASS**.

Đây đúng cái bẫy của smoke test trên code có `try/except` rộng: panel tự tắt
thì test không soi gì cả nhưng vẫn xanh. Thêm
`test_no_panel_silently_disables_itself` — bắt mọi dòng "disabled"/"Không tìm
thấy" mà panel in ra. Đã thử gỡ `select_slider` để chứng minh lưới CÓ RĂNG:
đỏ ngay.

### Thủ phạm 2 — ❌ ĐÃ CHỐT KHÔNG SỬA (user quyết 13/08)

`tests/test_sandbox_isolation.py`: 41 test, mỗi test spawn một process
(Windows spawn đắt). Chiếm **~44s trong 108s**. Bỏ khỏi `--fast` sẽ đưa vòng
lặp về ~20s.

**User chốt: GIỮ NGUYÊN** — "không sửa code để đảm bảo an toàn code".

Ghi rõ để lần sau KHÔNG ai đề xuất lại: đây là test an ninh của sandbox AST
(`vnstock_strategy`) — chặn ghi file, chặn `subprocess`, chặn đọc `.env` khi
chạy code chiến lược. Bỏ khỏi vòng lặp nhanh nghĩa là sửa code hằng ngày
không còn kiểm hàng rào đó, và lỗ hổng sandbox thuộc loại phát hiện MUỘN thì
đã muộn. 44 giây/lần chạy là cái giá đã được cân nhắc và chấp nhận, không
phải nợ kỹ thuật bỏ quên.

Hệ quả cần biết khi đọc số: `--fast` trên máy thật ~**64s** (sau vá thủ phạm
1), không còn là "~26s" như CLAUDE.md ghi từ thời 1.034 test.

CI sau vá: full **1898 passed / 34.4s**, `--fast` **1436 / 28.7s**.


## 2026-08-13 (b) — User bắt được lỗi thật: nhóm tuỳ biến không mở được ở cấp mã

Trong lúc soi dashboard sau đợt tách, user phát hiện: bảng ngành hiện đủ
**"Họ VIN" (4 mã)** và **"Họ M" (7 mã)** với đầy đủ số liệu, nhưng bấm vào để
xem chi tiết thì ra **"Không có dữ liệu ticker cho ngành Họ M"**. Mọi ngành
chuẩn mở bình thường.

### Nguyên nhân — và nó KHÔNG do đợt tách gây ra

`vnstock_runner` gom bảng cấp NGÀNH theo nhóm tuỳ biến, nhưng **cố ý** để bảng
cấp MÃ giữ `Ngành` = ngành GỐC. Comment tại chỗ ghi rõ lý do và lý do đó ĐÚNG:
brief dựa vào ngành gốc để nhận diện bất động sản / tài chính, đổi đi là hỏng
chỗ khác.

Hệ quả không ai nối tiếp: `df[df["Ngành"] == "Họ VIN"]` **luôn rỗng**, vì không
mã nào mang nhãn đó. Điểm mấu chốt khiến lọc-theo-cột không bao giờ đủ: 4 mã họ
VIN nằm ở **hai ngành gốc khác nhau** (VIC/VHM/VRE = Bất động sản, VPL = Du
lịch & Khách sạn).

Đã đối chiếu git: dòng lọc có từ lần tách tab gốc (PR #15), tức lỗi CÓ TỪ
TRƯỚC 12/08. Nhóm tuỳ biến được thêm cho đường bảng-ngành + brief; đường
drill-down không ai nối.

### Vá — một nơi, hai chỗ dùng

`vnstock_sectors.rows_for_sector(df, label)`: nhóm tuỳ biến → lọc theo DANH
SÁCH MÃ, ngành chuẩn → lọc theo cột như cũ. Không import pandas (chỉ dùng giao
diện của df) nên module vẫn là leaf.

Hai chỗ gọi: drill-down bảng ngành (`market_tab`) và khối "⭐ Mã dẫn dắt / 💀 Mã
yếu nhất" (`market_commentary`) — chỗ thứ hai dính CÙNG lỗi mà chưa ai thấy, vì
nó chỉ lộ khi một nhóm tuỳ biến lọt vào top-3/avoid-2.

### Test (13 + 1)

`tests/test_custom_sector_drilldown.py` — soi hàm lọc, kèm lưới chặn tái phát:
chỗ nào lọc bảng mã theo nhãn ngành mà tự viết `df["Ngành"] == label` là ĐỎ.
Cộng một test render đi **đúng đường user bấm** trong
`test_tab_render_smoke.py`: chọn "Họ VIN" ở drill-down rồi bắt câu "Không có dữ
liệu ticker". Đã thử trả lại cách lọc cũ để chứng minh test có răng — đỏ ngay.

Full **1912 passed**, `--fast` **1450 / 36.2s**.


## 2026-08-13 (c) — User soi brief chiều, ra 4 lỗ. Cùng một họ.

Bốn thứ nhìn khác nhau nhưng **cùng một bệnh**: hệ thống BIẾT sự thật, chỉ là
không nói ra, hoặc nói ra thành thứ khác.

### 🔴 1. Chiến lược trượt kiểm định vẫn phát khuyến nghị mà không nói một lời

Panel Chiến lược tự báo rất rõ: **p=0.974** (Sharpe không hơn ăn may),
**expectancy −0.58**, chỉ 25% cửa sổ thời gian dương, và **0/49 lệnh đã đóng
chạm chốt lời** (14 dính cắt lỗ, 35 hết hạn — chốt lời đặt quá xa so với thời
hạn 5 phiên). Vậy mà nó vẫn giữ cờ "Active" và bơm 8 khuyến nghị vào brief.

Đọc code thì thấy `_recommendation_block` viết trong docstring là *"open
recommendations from VALIDATED strategies"* — **nhưng chưa hề kiểm**. Câu
docstring đó tồn tại từ lâu và không ai để ý là nó nói dối.

Chọn **CẢNH BÁO, không LỌC BỎ** — cùng doctrine với `_BUY_BIAS_CAVEAT` và khối
BĐS Op.CF: mỗi khuyến nghị đã tự mang cắt lỗ (rủi ro có giới hạn), thêm bối
cảnh đúng hơn là giấu tín hiệu.

Vá hai tầng, đúng quy ước CLAUDE.md: `_recommendation_block` gắn câu cảnh báo
vào PROMPT, và guard `enforce_unvalidated_strategy_caveat` bảo đảm nó sống sót
tới brief cuối — vì LLM hay lược bỏ đúng những câu bất lợi cho ý tưởng nó vừa
viết.

Điểm quan trọng: **không đọc được kiểm định thì IM**, không coi là trượt.
Chưa có chiến lược / chưa backtest / DB lỗi là KHÔNG ĐO ĐƯỢC.

### 🟡 2. Ký hiệu nội bộ rò ra brief — và rò sai

Mistral viết: `cắt lỗ 77,600 (entry < TP > SL)`. Nó nhại lại ràng buộc trong
template (`BẮT BUỘC SL < entry < TP`) — **và nhại sai chiều**. Vừa lộ ruột vừa
sai. Guard `enforce_no_instruction_leak` cũ không bắt được vì nó chỉ soi DÒNG
mở đầu bằng vài mẫu cố định, còn đây là cụm nằm GIỮA câu.

Thêm `enforce_no_constraint_notation`: chỉ xoá cụm gồm TOÀN ký hiệu nội bộ nối
bằng dấu so sánh, trong ngoặc. Câu tiếng Việt có chữ "entry" bình thường không
bị đụng.

### 🟡 3. Cùng một con số, ba nhãn khác nhau

11% trên MA200 + A/D 1.08: một agent gọi độ rộng **"TÍCH CỰC"**, ba agent gọi
**"yếu"**, còn dashboard gán 🔴 **"đa số cổ phiếu trong xu hướng giảm"**.

Có guard cho đúng ca này (`enforce_breadth_quality`) nhưng nó **đứng ngoài** vì
cổng kích hoạt đòi momentum âm, mà hôm đó momentum +16.

Thêm nấc thứ hai: dưới `_MA200_CALL_IT_WEAK = 30` thì gọi "tích cực" là sai
**bất kể momentum**. Ngưỡng 30 lấy đúng biên 🔴 của bảng nhận định, và có test
`test_threshold_matches_the_dashboard_red_band` canh hai hằng số khỏi trôi khỏi
nhau — hai màn hình không được nói hai kiểu về một con số.

### 🟡 4. "0%" khi mẫu là 2

Bảng độ chính xác hiện `0%` cho agent mới chấm được 1-2 brief → nhìn như agent
sai hết, sự thật là **chưa đủ mẫu**. Đây đúng họ lỗi đã vấp nhiều lần:
**không đo được bị trình bày thành đo ra kết quả xấu**.

`format_accuracy` phân biệt BA trạng thái: chưa chấm gì → `—`; đã chấm nhưng
`n < 5` → `— (n=2)`; đủ mẫu → `40% (n=5)`. Bảng cũng xếp agent đủ mẫu lên trước
(trước đây agent 0/1 đứng trên agent đã chấm 20 brief).

### Chốt

Lỗ 1 và lỗ 4 là **cùng một bài học ở hai chiều ngược nhau**: một cái xấu mà
im, một cái chưa biết mà kêu.

`tests/test_brief_quality_fixes.py` (34 test). Chuỗi guard: 44 → **46**.
Lưới `test_all_moved_names_are_reexported` bắt đúng 2 hằng số mới quên
re-export — nó làm đúng việc.

Full **1946 passed**, `--fast` **1484 / 34.5s**.


## 2026-08-13 (d) — 3 quyết định của user + nền cho tầng chiến lược DÀI HẠN

User chốt: **(1)** theo dõi cả ngắn/dài, **(2)** không chiến lược nào đạt kiểm
định thì KHÔNG khuyến nghị gì, **(3)** bật lưu lịch sử fundamentals hàng tháng.
Đợt này làm 3 bước nền (thứ tự đã thống nhất); tầng dài hạn THẬT chờ số đo từ
máy user.

### Quyết định (2) — THAY hành vi sáng cùng ngày

Sáng 13/08 chọn "giữ khuyến nghị + cảnh báo"; user chốt lại: **trượt là không
phát**. Giờ:

* `_recommendation_block` trượt kiểm định → thay danh sách bằng **sentinel
  "KHÔNG CÓ khuyến nghị"** (không phải im lặng — cùng bất biến chống-khoảng-
  trống: block biến mất âm thầm thì template vẫn trỏ tới "block Khuyến nghị"
  và model tự bịa). Sentinel kèm chỉ đường hợp lệ: chỉ dùng mã ⭐ movers.
* **Sổ khuyến nghị trong DB vẫn ghi/đối soát bình thường** — đó là cách chiến
  lược tự chứng minh bằng live để một ngày ĐẠT; chỉ kênh brief tới user đóng.
  Đạt kiểm định là khuyến nghị tự chảy lại, không cần bật tay.
* Guard `enforce_unvalidated_strategy_caveat` hạ xuống **hàng rào dự phòng**,
  thêm điều kiện cờ `strategy_recs_in_prompt` — thiếu cờ mà bắn là gắn nhãn
  "chiến lược chưa kiểm định" lên setup movers vốn không liên quan chiến lược.

### Exit mix + cổng "chốt lời phải với tới được"

Lý do thoát ("tp"/"sl"/"expire") đã ghi vào TỪNG lệnh từ đầu mà chưa bao giờ
được gom — win rate 45% che mất "0/49 chạm TP". Giờ:

* `exit_mix(trades)` nằm trong metrics của MỌI backtest; panel hiện
  `Exit mix: 🎯 TP x% · 🔴 SL y% · ⏳ hết hạn z%` + cảnh báo khi TP < 5%.
* `validate_backtest_quality` thêm lý do trượt: đủ ≥ 20 lệnh ĐÓNG mà TP < 5%
  → "TP nằm ngoài tầm với của horizon, R:R trên giấy không thực hiện được".
  Lý do này tự chảy vào `passed` → cổng promote (revise/tune) chặn ứng viên
  cùng bệnh, và (2) tự đóng kênh brief. **"hold" không tính là lệnh đóng**,
  dưới 20 lệnh đóng thì IM — không đo được ≠ đo ra xấu.

### `vnstock_reachability.py` — chọn horizon bằng SỐ ĐO, không đoán

Đo MFE/MAE (mức lãi tối đa/lỗ sâu nhất trong N phiên sau ngày vào) theo % và
theo **bội ATR14** — so thẳng được với `tp_atr_mult` 2.5–4.0 đang dùng. Trả
lời 3 câu: TP hiện tại với tới bao nhiêu % số lần ở từng horizon · muốn với
tới ~60% thì TP đặt đâu (p60 MFE) · tầng vị thế nên lấy horizon 20 hay 40.
Ghi `_meta/reachability.json` (nguyên tử). Test bằng dữ liệu tổng hợp canh
BẤT BIẾN của phép đo (MFE không giảm theo horizon, tỷ lệ với-tới giảm theo
mốc ATR, không mẫu → {}).

### Quyết định (3) — lịch sử fundamentals point-in-time

`_save` của `vnstock_fundamental_updater` nay ghi nguyên tử + mỗi tháng giữ
MỘT ảnh chụp `_meta/fundamentals_history/fundamentals-YYYY-MM.parquet` (bản
đầu tháng thắng; best-effort — hỏng archive không hỏng update chính; vào lưới
`_MUST_BE_ATOMIC` vì ảnh chụp mất là KHÔNG tái tạo được). Đây là chìa khoá để
6–12 tháng nữa backtest tầng đầu tư cơ bản không dính look-ahead. Snapshot
đầu tiên tự rơi vào lần update fundamentals kế tiếp trên máy user.

### Còn lại của lộ trình dài hạn (chờ 2 việc trên máy thật)

1. ✅ User chạy `python vnstock_reachability.py` → số chọn horizon + TP
   (kết quả ở entry (e) ngay dưới).
2. Kiểm cổ tức trong kho giá (gap ex-div chưa điều chỉnh) — chưa làm.
3. ✅ Tầng A "vị thế 20 phiên" ĐÃ DỰNG (entry (e)). Tầng B danh mục tháng
   vẫn để sau.

Suite **1971 passed** (+25).


## 2026-08-13 (e) — Số đo về: giả thuyết ĐÚNG, và tầng "vị thế 20 phiên" ra đời

### Số đo trên máy user (30/30 mã VN30 × 500 phiên, 3.390 mẫu/horizon)

| Horizon | p60 MFE (×ATR) | TP 2.5×ATR với tới | MAE p50 |
|---|---|---|---|
| 5d | 1.30 | **16%** | −2.3% |
| 10d | 1.95 | 30% | −3.3% |
| **20d** | **2.89** | **46%** | −4.8% |
| 40d | 4.30 | 61% | −7.5% |

Đọc ra ba điều:
* **Giả thuyết 0/49 được xác nhận**: TP 2.5×ATR (ĐÁY của dải cấu hình 2.5–4.0)
  trong 5 phiên chỉ với tới 16% số lần — R:R 1.5 "trên giấy" có tử số gần như
  không bao giờ bắn. TP đúng cỡ cho 5 phiên là ~1.3×ATR (p60).
* **20 phiên là điểm khớp**: p60 = 2.89×ATR trùng đúng dải tp_atr_mult hiện
  hành → tầng vị thế lấy **20 phiên** (40d với tới 61% nhưng vốn nằm gấp đôi,
  MAE sâu −7.5%).
* Caveat trung thực: 500 phiên gần nhất phần lớn là thị trường đi lên —
  MFE nghiêng theo regime; số này để CHỌN THAM SỐ, không phải lời hứa lợi nhuận.

### Tầng "position" — dựng xong, cấu hình từ số đo

* `vnstock_memory`: cột `tier` (migration idempotent, dữ liệu cũ = 'short'
  nên nghĩa không đổi); `get_active_family(tier=)`; **promote scope theo tier**
  — không có scope thì tạo tầng vị thế xong là tầng 5 phiên mất ghế ngay.
* `vnstock_strategy`: `TIER_CONFIGS` — position = horizon 20 / step 20 /
  lookback 730. **Bất biến step ≥ horizon** (test canh): lệnh chồng cửa sổ là
  cùng cú sóng đếm nhiều lần, p-value đẹp giả, kiểm định thành trang trí.
  `develop_and_backtest(tier=)` → cold-start/revise lưu đúng tier;
  `emit_recommendations` đặt horizon rec THEO TIER của chiến lược sinh ra nó.
* **Prompt sinh chiến lược neo vào số đo**: `_reachability_hint(horizon)` đọc
  `reachability.json` → "trong N phiên p60 = X×ATR, TP 2.5×ATR với tới Y% —
  chọn tp_atr_mult quanh X". Hết thời hướng dẫn "2.5–4.0" viết chung cho mọi
  horizon. Chưa đo → hint rỗng (không bịa neo).
* `vnstock_train --tier {short,position,both}` (mặc định short — hành vi cũ
  nguyên vẹn; nightly không tự chạy position).
* Brief: gating **theo TỪNG chiến lược** — rec mang `strategy_id`, tầng vị thế
  không bị xử theo kiểm định của tầng 5 phiên. Rec vị thế mang nhãn
  `[vị thế ~20 phiên]` (bài học "Giá 1T %": nhãn phải nói rõ khung). Ẩn một
  phần thì NÓI RA trong prompt (chống model bịa lý do thiếu).
* Panel: dòng "🕰 Tầng vị thế" + lệnh tạo khi chưa có.

Suite **1987 passed** (+16), `--fast` 1.525 / 26s CI.


## 2026-08-13 (f) — Lần chạy `--tier both` đầu tiên: một đạt, một trượt, một lỗ hổng lộ ra

### Kết quả trên máy user

* **Tầng 5 phiên** — ứng viên #33 (116 lệnh): expectancy **+0.52** (cũ −0.58!),
  TP 22% (live cũ 0%), p **0.184** (cũ 0.974). CHƯA ĐẠT (p ≥ 0.1) → hệ ĐÚNG
  khi không nhận — nhưng xu hướng cải thiện rõ rệt: neo prompt vào số đo
  reachability đang kéo tầng ngắn về phía khả thi.
* **Tầng vị thế** — #32 sau MỘT vòng tune: 67 lệnh → **19 lệnh**, expectancy
  0.197 → **2.37**, kiểm định **✅ ĐẠT (p hiệu chỉnh 0.040)**. 5 rec đã emit
  (quét 3.125 mã) → brief kế tiếp SẼ có mục khuyến nghị `[vị thế ~20 phiên]`.

### Đọc kết quả #32 một cách trung thực

Đạt theo ĐÚNG luật đã chốt — nhưng bằng chứng MỎNG: 19 lệnh, và kiểu thắng
"co 67 lệnh còn 19 để expectancy nhảy ×12" là chữ ký kinh điển của overfit
(chọn lọc entry đẹp trong mẫu). KHÔNG chặn hồi tố (#32 giữ ghế + rec vẫn phát
— luật tại thời điểm chạy là luật; mỗi rec tự mang SL; trọng tài THẬT là live
reconcile ~20 phiên tới + `strategy_health` tự demote khi decay).

### Lỗ hổng lộ ra → vá + lưới

Cổng TUNE là đường adopt DUY NHẤT thiếu sàn `n_trades ≥ MIN_TRADES_TO_VALIDATE`
(cold-start và revise đều có; tune thi đấu theo expectancy nên co mẫu là cách
rẻ nhất để thắng). Đã vá tune + genetic (genetic dùng sàn CONFIG-AWARE của
chính run — lite hạ sàn có chủ đích cho smoke test, lưới của chính đợt này
bắt được bản vá đầu sai chỗ đó). Lưới mới trong `test_strategy_tiers.py`:
mọi biểu thức gọi `_validation_ok` phải kèm sàn số lệnh NGAY TRONG điều kiện.

Lưu ý: sàn 10 KHÔNG chặn được ca 19 lệnh hôm nay — vá này là NHẤT QUÁN CỔNG,
không phải chặn hồi tố. Câu hỏi mở cho user (mục 🟠): **có nâng sàn kiểm định
lên ~30 lệnh không?** Nâng = #32 quay lại "chưa đạt" ở backtest kế tiếp, brief
đóng lại cho tới khi đủ mẫu. Không nâng = tin p=0.040 trên 19 lệnh + để live
phân xử. Claude nghiêng NÂNG nhưng đây là quyết định khẩu vị rủi ro của user.

Suite **1989 passed**.


## 2026-08-13 (g) — User chốt: NÂNG sàn bằng chứng 10 → 30 lệnh

Điểm kỹ thuật quan trọng nhất của bản vá: nâng hằng số KHÔNG đủ. `passed` lưu
trong DB được tính theo luật tại thời điểm backtest, mà tune KHÔNG lưu backtest
mới khi không có ứng viên thắng → #32 (19 lệnh, passed=True đã lưu) sẽ tiếp
tục phát rec vô thời hạn. Vì thế sàn áp ở **ĐIỂM ĐỌC** (`_validation_of_strategy`
đọc `n_trades` từ row/metrics_json, verdict "đạt" + n < 30 → hạ xuống kèm lý
do "mẫu quá mỏng") — quyết định có hiệu lực NGAY với verdict cũ.

Các chốt đi kèm:
* `MIN_TRADES_TO_VALIDATE = 30` (comment ghi rõ: hạ xuống là quyết định khẩu
  vị rủi ro của USER, đừng sửa mà không hỏi — có test pin đúng giá trị 30).
* Genetic FULL đi theo sàn chung (`_MIN_TRADES_DEFAULT = MIN_TRADES_TO_VALIDATE`);
  lite giữ sàn 4 CÓ CHỦ ĐÍCH cho smoke test.
* Sàn chỉ HẠ verdict đạt-mà-mỏng; verdict trượt giữ nguyên; validation vắng
  (backtest cũ) vẫn là unknown — sàn không biến "không biết" thành "trượt".
* Sentinel + panel nêu LÝ DO: từ giờ p có thể rất đẹp (0.040) mà vẫn đóng vì
  mẫu mỏng — chỉ in p sẽ gây hiểu lầm "p tốt mà sao trượt".
* 4 fixture test cũ dùng ứng viên n=25 (hợp sàn cũ) nâng lên 45 — ý đồ của
  chúng là cơ chế adopt, không phải giá trị sàn.

Hệ quả user thấy được: brief kế tiếp KHÔNG có rec vị thế (đóng lại đúng như
đã chốt); panel ghi "thống kê ĐẠT (p=0.040) nhưng mẫu quá mỏng (n=19 < 30)".
Đường mở lại: vòng train đêm (`--tier both`) tìm được ứng viên ≥ 30 lệnh đạt
chuẩn — hoặc dữ liệu mới tích đủ lệnh cho params hiện tại.

Suite **1996 passed**.

## 2026-08-13 (h) — Verify tay đợt chót: chart 4 panel + watchlist → mục 0 ĐÓNG

User soi tab Phân tích trên máy thật (ảnh VCB + VCI, khung 1D) rồi kéo/zoom
tay. Đạt 4/4 tiêu chí: nhãn thời gian 4 panel chung cột dọc; nến đầu/cuối
chung mép; RSI/MACD chạm đúng nến cuối (không hụt mép phải); kéo/zoom panel
giá → 3 panel dưới trôi theo đồng bộ. Bất biến logical-range sống khoẻ sau
đợt chuyển nhà `compute_indicators` → `dashboard/chart_indicators.py`.

Chi tiết đắt giá: VCB đang giữa chuỗi tăng ~53→59.7, RSI 76.64 — đúng kịch
bản "cửa sổ 14 phiên gần như không có phiên giảm" TỪNG gây RSI đứt đuôi
(công thức ngây thơ chia 0 → NaN → hụt khúc phải). Ảnh cho thấy đường vẽ
liền tới nến cuối: `test_no_nan_at_the_tail` canh đúng chỗ, nay có thêm
bằng chứng mắt thường trên ca thật.

Watchlist: user thêm rồi xoá một mã trong tab Screener, danh sách cập nhật
đúng — đường ghi nguyên tử mới (`dashboard/watchlist_io.py`) chạy êm.

Ghi nhận ngoài lề (CHƯA soi, không chặn gì): sidebar có 2 badge cảnh báo —
nguồn dữ liệu 2⚠️ (`run.py doctor` xem tên) + ladder model có mục bất thường
(nhiều khả năng là nemotron-ultra chậm đã biết từ 11/08; báo cáo T7 16/08
sẽ tự soi). User rảnh thì dán output `run.py doctor` cho Claude xem.

## 2026-08-13 (i) — WSS volume verify ĐẠT trên máy thật: món nợ 07/08 đóng

Bối cảnh: user hỏi "mục 1 cụ thể làm thế nào" → lộ ra lệnh trong checklist
(`python vnstock_wss.py` trần + Ctrl+C) KHÔNG chạy được — không tham số chỉ
in help rồi thoát — và việc soi parquet + suspect_count bằng tay quá lắt
nhắt với người không lập trình. Viết `scripts/verify_wss_live.py`: MỘT
lệnh, tự mở WSS 38 mã ~5 phút, tự chấm 3 bất biến, exit 0/1/2; logic chấm
là hàm thuần với 11 test canh (`tests/test_verify_wss_live.py`) — ca canh
kỹ nhất thuộc họ bug quen "không đo được bị đọc thành đạt": snapshot rỗng
phải ra ⚠️/1, cấm ra ✅/0.

Kết quả máy thật (phiên 13/08): ✅ 28/30 mã cổ phiếu volume > 0 (top TCB
264,700 · BID 126,000 · VHM 90,607) · ✅ index volume == 0 đủ 4 chỉ số
(VNINDEX/VN30/HNX30/HNXINDEX) · ✅ suspect_count = 0 ·
`bars_2026-08-13.parquet` 8,036 bytes. 2/30 mã volume 0 trong 5 phút = mã
ít thanh khoản, bình thường.

Chi tiết soi thêm TRƯỚC khi tick: dòng [2] không có VN30F1M — tra code xác
nhận ĐÚNG THIẾT KẾ. Phái sinh không đi đường tick→BarAggregator mà đi kênh
riêng poll `price_depth` → ghi `quote_VN30F1M.json` độc lập (docstring
`_fetch_volume_profile` + main loop bước 3); đường tick→bar chỉ chở cổ
phiếu + index, và cả hai đã được chấm. Câu "VNINDEX/VN30F1M phải volume
== 0" trong checklist cũ viết theo trí nhớ bug gốc — bề mặt rủi ro THẬT
của vụ accum→delta chính là chỗ script đã phủ.

Suite 2008 passed (11 test mới của `grade()`).

## 2026-08-13 (j) — `run_daily.log` CÓ THẬT từ hôm nay: tee tại run.py, một điểm chặn

User hỏi "soi run_daily.log làm thế nào" → truy code mới vỡ ra: sự thật
11/08 (e) VẪN CÒN NGUYÊN — file đó chưa từng tồn tại (Task Scheduler vứt
stdout), mục 0c như đang viết là bất khả thi. Tệ hơn: docstring
`_note_loader_error` (12/08) hứa "WARNING vào run_daily.log" — lời hứa
viết vào một file không tồn tại, đúng vết xe 11/08 (e) khai quật hôm
trước. Lần này vá bằng CODE, không phải bằng hướng dẫn:

* `run.py main()` → `_install_run_log()`: mở `run_daily.log` (append, cạnh
  run.py — đúng tên/chỗ mọi tham chiếu cũ trong notes), ghi header mốc giờ
  + lệnh, tee `sys.stdout`/`sys.stderr`. MỌI lần gọi run.py đều ghi
  (all / train / doctor / test…), không riêng task đêm. Quá ~5 MB tự cắt
  giữ đuôi ~1 MB.
* `_run()` đổi `subprocess.run` → `Popen(stdout=PIPE, stderr=STDOUT)`, bơm
  từng dòng qua print của cha → output TIẾN TRÌNH CON (updater, train,
  brief…) cùng chảy vào tee. Env con thêm PYTHONUNBUFFERED +
  PYTHONIOENCODING=utf-8. Đánh đổi chấp nhận: progress bar `\r` (tqdm)
  nhìn như đứng im tới khi xuống dòng.
* `strategy_loop` in `tier=` trong dòng verbose → `Select-String "tier="`
  là ra ngay bằng chứng đêm đó train tầng nào (phục vụ 0c/0f).
* Best-effort triệt để CẢ HAI phía tee (console chết dưới scheduler / file
  chết vì đĩa đầy) — hỏng đường log KHÔNG được giết pipeline. `.gitignore`
  thêm `run_daily.log`.
* Lưới `tests/test_run_log.py` (15 test): chuỗi con→PIPE→tee→file chạy
  THẬT (subprocess thật), hai phía chết không nổ, trim giữ đuôi, net AST
  canh main() còn gọi `_install_run_log` / `_run` còn đi PIPE / train còn
  in `tier=` — ai gỡ tee là test đỏ, khỏi tái diễn "log ma" lần ba.

Bằng chứng sống ngay lần chạy đầu: `python run.py test` đi qua main() mới
→ sinh `run_daily.log` đầu tiên trong đời dự án (187 KB, nguyên output
pytest của tiến trình con). Suite 2008 → **2023 passed**.

## 2026-08-13 (k) — Nút "Tạo brief phân bổ" nổ ngay lần bấm THẬT đầu tiên

User tạo brief phân bổ tháng 8 (4 giọng đều ra, số ghim chuẩn) nhưng cuối
trang hiện hộp đỏ "Không render được sub tab Phân bổ: too many values to
unpack (expected 2)". Truy: `_render_brief` mổ
`for name, (text, err) in results.items()` — mổ NGAY TRONG câu for, TRƯỚC
dòng lọc `name.startswith("_")` ngay bên dưới. `generate_brief` trả kèm
metadata `_brief_ids` (list id các brief vừa lưu) → 4 agent thành công =
list 4 phần tử = unpack (expected 2) nổ. Nghịch lý đáng nhớ: brief càng
THÀNH CÔNG nhiều giọng càng chắc chắn nổ — còn smoke test không bao giờ
thấy vì Streamlit giả "không bấm nút nào" (giới hạn đã tự ghi trong
docstring test_tab_render_smoke). `brief_run_panel` làm ĐÚNG từ đầu (lọc
trước, mổ sau) — chỉ panel phân bổ sai kiểu.

Fix: lọc "_" trước rồi mới mổ payload (mirror brief_run_panel). Test mới
`TestAllocationBriefButtonBranch` (2 test): fake button bấm THẬT key
`_al_brief` + stub generate_brief trả đúng HÌNH DẠNG thật (kèm _brief_ids
4 phần tử, _warnings dict, _no_available) — chứng minh ĐỎ trước fix
(ValueError đúng dòng 167) rồi mới xanh sau fix.

Hệ quả dễ chịu: brief KHÔNG mất — save vào memory nằm BÊN TRONG
generate_brief, chạy xong trước vòng render, nên 4 brief đã trong SQLite,
doctor ⚠️ phân bổ tự tắt, expander "Brief gần nhất" mở lại là thấy. User
chỉ cần merge để lần bấm sau không đỏ.

Suite 2023 → **2025 passed**.

## 2026-08-13 (l) — 4d: checker điều chỉnh cổ tức kho giá — code xong, chờ máy thật

Bối cảnh: tầng vị thế 20 phiên sống → giữ lệnh xuyên GDKHQ thành chuyện
thường ngày. Kho build tăng dần và tin 100% nguồn vnstock; `vnstock_adjust`
tự ghi rõ tầng back-adjust "was never wired into production". Chưa ai từng
kiểm chuỗi có nhất quán điều chỉnh qua các đợt ex-div — reachability
(13/08 (e)) cũng đã dặn MAE p90 nhiễm nghi vấn này.

`vnstock_div_check.py` — thiết kế:
* Nguồn sự kiện: cache `_meta/corp_actions/{TICKER}.parquet` của
  `vnstock_adjust` (ex_date/type/cash_amount/ratio) — KHÔNG phải
  `vnstock_events` như checklist cũ ghi (module đó chỉ giữ sự kiện
  TƯƠNG LAI, không dùng soi lịch sử được).
* Chuỗi giá: `vnstock_strategy._load_history` — đúng loader backtest dùng,
  audit đúng thứ backtest nhìn thấy.
* Mỗi sự kiện = phép thử 2 giả thuyết trên gap close(T−1) → open(ex-date):
  H_adjusted ≈ 0 vs H_raw ≈ −drop kỳ vọng (cash: VND/1000/giá nghìn đồng;
  split r>1: 1−1/r; bonus 0<r≤1: r/(1+r)) — chọn giả thuyết GẦN quan sát.
* Kỷ luật "không đo được ≠ đạt" cài 5 cửa inconclusive: cổ tức < max(1%,
  2×nhiễu ngày thường) = chìm nhiễu · gap sâu hơn kỳ vọng + 6×nhiễu = sập
  sàn trùng ngày, không đổ oan cho cổ tức · yield >40% = nghi sai đơn vị
  nguồn · đứt chuỗi >7 ngày lịch quanh ex-date · chuỗi <30 bar. Toàn
  inconclusive → exit 1, KHÔNG bao giờ ra ✅.
* Exit 0/1/2 chuẩn repo · ghi `_meta/div_check.json` (write_json_atomic) ·
  `--refresh` fetch events cho mã thiếu cache · mặc định VN30 · 750 ngày
  (khớp lookback tầng vị thế).
* `tests/test_div_check.py` — 22 test hermetic trên chuỗi tổng hợp: chuỗi
  thô bị bắt / chuỗi sạch được xác nhận / đủ 5 cửa inconclusive / grade
  không bao giờ thăng hạng khi không đo được. Vào danh sách `--fast`
  (tiện tay bỏ dòng `test_strategy_tiers` bị lặp đôi trong list).

**Kết quả máy thật (user chạy NGAY 13/08): 0 GAP THÔ.** 17 mã chấm được,
28/28 sự kiện đều khớp "đã điều chỉnh" (ACB/BID/CTG/FPT/GAS/HDB/HPG/MBB/
POW/SHB/SSB/SSI/TPB/VCB/VIB/VJC + 4 của SSI); VIC 1 chưa kết luận. Ý nghĩa
kép: nguồn vnstock trả giá điều chỉnh VÀ đường sync build-tăng-dần vẫn giữ
chuỗi nhất quán qua sự kiện (nếu không thì gap thô đã lộ tại ex-date).
Backtest tầng vị thế đứng trên nền sạch TRONG PHẠM VI ĐO ĐƯỢC.

Chưa phải toàn tập — độ phủ: 11 mã "0 sự kiện trong cửa sổ" gồm cả những
mã CHẮC CHẮN có trả cổ tức 2 năm qua (VNM nhiều đợt/năm, SAB, TCB, VPB,
MSN, MWG, PLX, STB…) → không phải họ không trả, mà CACHE EVENTS CŨ/THIẾU;
GVR thiếu hẳn cache. Vá thêm sau lần chạy đầu: cờ `-v/--verbose` in lý do
của sự kiện "chưa kết luận" (bản đầu VIC câm lặng — thấy inconclusive mà
không biết vì sao là nửa cái báo cáo). Việc còn của user ghi ở mục 4d:
bù cache rồi chạy lại `-v`.

Kịch bản ❌ (nếu lần phủ nốt lòi ra): refetch lịch sử mã dính vs dạy
backtest cộng cổ tức vào equity — chưa quyết trước, đợi số liệu thật.

Suite 2025 → **2049 passed** (24 test div_check).

## 2026-08-14 (m) — VIC -v: checker tự tố lỗi trần; ca "chưa kết luận" hoá bằng chứng mạnh nhất

User chạy `div_check -v` (laptop): 29 sự kiện sạch + VIC 1 inconclusive,
lý do lộ ra: `2025-12-13 [bonus] kỳ vọng −49.82% — quan sát −0.14% → nghi
sai đơn vị/tỷ lệ nguồn`. Đọc lại cho đúng: ratio ≈ 1 (thưởng 1:1, VIC chia
cuối 2025) → giá PHẢI giảm một nửa tại GDKHQ; quan sát −0.14% = cú halving
hoàn toàn VÔ HÌNH trong chuỗi kho = chuỗi được back-adjust hoàn hảo. Cổ
tức tiền 2% còn trốn được trong nhiễu — halving thì không: đây là bằng
chứng điều chỉnh MẠNH NHẤT cả đợt kiểm, bị chính trần của checker bịt oan.

Lỗi thiết kế: `_MAX_PLAUSIBLE_YIELD_PCT = 40` hiệu chỉnh cho cổ tức TIỀN
(yield/đợt >40% = gần chắc sai đơn vị) nhưng bị áp cho MỌI loại sự kiện —
với chia thưởng/chia tách, 50% là chuyện thường. Sửa: trần theo LOẠI chọn
tại check_ticker (cash 40 / split-bonus 90 — split 10:1 = 90%),
`classify_event` nhận `max_plausible_pct`. 5 test mới, có regression đúng
ca VIC (chuỗi phẳng + kỳ vọng 49.82 + trần 90 → adjusted_ok; chuỗi gap
−49.8 → raw_gap vẫn bị bắt; đường cash giữ nguyên trần 40).

Lặt vặt: ACB 1→2 sự kiện giữa hai lần chạy — cache/cửa sổ dịch chuyển,
cả hai lần đều adjusted, vô hại. Suite 2049 → **2054 passed**.

## 2026-08-14 (n) — Hàng chờ code: ② gắn máy đo · 4d gộp 3 nguồn · 4e giữ cổng

User gọi "làm hàng chờ đi". Ba món — hai làm, một giữ có lý do:

**② Đo hiệu năng warehouse — hết đoán, pipeline TỰ ĐO mỗi đêm.** `cmd_all`
bấm giờ từng bước: in `[run.py] ⏱ <bước>: Xs` sau mỗi bước + dòng tổng kết
`⏱ TỔNG X phút — <bước nặng nhất đứng đầu>` cuối chuỗi (in cả khi dừng
giữa chừng vì hard-fail). Số nằm sẵn trong run_daily.log — khỏi cần phiên
profiling riêng, và đo đúng điều kiện thật (đĩa/mạng máy bàn, 18:00).
Helper `_format_step_summary` thuần + 3 test (2 unit + 1 net AST canh
cmd_all còn đo).

**4d nguồn sự kiện thứ hai — hoá ra ĐÃ CÓ 3 nguồn, vùng mù nằm ở chữ
`break`.** `_fetch_events` thử vnstock_data → VCI → KBS nhưng "nguồn đầu
có GÌ ĐÓ là dừng": mã nào nguồn 1 trả vài dòng cũ là nguồn 2-3 không bao
giờ được hỏi — đúng hình vùng mù VNM/SAB/TCB/VPB…. Đổi thành GỘP cả 3
nguồn: dedupe chính xác `keep="first"` (nguồn giàu sử liệu đứng trước
thắng — dividends extractor cũng chạy trước nên bản "đến trước" giàu field
hơn) + khử TRÙNG GẦN `_drop_near_duplicates` (cùng ticker+type, ex_date
lệch ≤5 ngày = MỘT sự kiện bị hai nguồn ghi hai mốc ex/record — không khử
thì div_check chấm sự kiện MA ngay cạnh sự kiện thật; đánh đổi ghi rõ:
hai sự kiện cùng loại cách ≤5 ngày coi như không tồn tại ở corp action
VN). 5 test mới (test_adjust.py 3→8).

**4e tầng B — GIỮ CỔNG, chưa làm.** Điều kiện chốt sẵn là "tầng A chạy
ổn"; thực tế 14/08: production còn chưa merge, tầng vị thế chưa train đêm
nào trên máy bàn, chưa có chiến lược đạt kiểm định để mà xoay vòng danh
mục — xây 4e bây giờ là xây tầng trên móng chưa đông. Khi tầng A có ứng
viên ≥30 lệnh đạt chuẩn chạy ổn định → nêu ý tưởng thiết kế trước (nếp
cũ) rồi mới code.

Suite 2054 → **2062 passed**.

## 2026-08-14 (o) — Dump phân xử: EXTRACTOR MÙ, nguồn sáng trưng — vá 3 chỗ đọc VCI

User chạy `dump_dividend_shape VNM SAB GVR` → nguồn VCI có ĐẦY ĐỦ cổ tức
tiền mặt ngay trong events(): VNM 1,850đ GDKHQ 26/06 · SAB 3 đợt
2,000-3,000đ · **cả GVR** (tưởng "3 nguồn đều mù") cũng có 400đ GDKHQ
13/11/2025 — số nằm trong cột chuẩn `value_per_share` (VND/cp) +
`exright_date`. Extractor mù vì đúng 3 chỗ:
1. chỉ bắt chia tách/thưởng từ events(), BỎ QUA hẳn loại DIV tiền mặt;
2. dò cột `ex_date`/`ex_rights_date` — VCI đặt tên `exright_date`
   (vnstock_events.py biết tên đúng từ lâu, vnstock_adjust thì không);
3. đọc nhãn `event_name` — VCI dùng `event_name_vi`.
Nhóm ngân hàng thoát nạn nhờ đường vòng capital_history (cổ tức bằng cổ
phiếu → tăng vốn điều lệ) — nên vùng mù rơi CHÍNH XÁC vào nhóm trả TIỀN
MẶT. "11/30 VN30 mù" hoá ra không phải nguồn thiếu mà là mình không đọc.

Vá `_extract_events`: nhận cash qua event_code=DIV / category=DIVIDEND /
nhãn "cổ tức bằng tiền" (cash_amount = `value_per_share`); thêm
`exright_date` + `event_name_vi`/`event_title_vi` vào ứng viên cột; skip
category họp/nội bộ/khác; bonus nhận thêm nhãn "cổ tức bằng cổ phiếu" +
cột `exercise_ratio`; NaN xử lý tử tế (`_first_val`). `div_check
--refresh` ĐỔI NGHĨA: fetch lại events cho TOÀN BỘ mã đang kiểm (bản đầu
chỉ fetch mã trống cache — vô dụng cho vùng mù vì cache họ không trống,
chỉ thiếu). 4 test mới với hình dạng VCI THẬT chép từ dump + 1 test giữ
hình dạng cũ không vỡ.

**Kết quả chạy `--refresh -v` (user, ngay 14/08): ĐÚNG DỰ ĐOÁN VÀ HƠN THẾ.**
Độ phủ 18 → **28/30 mã** · 37 → **64 sự kiện đều "đã điều chỉnh" · 0 GAP
THÔ** · 19 chưa kết luận — TOÀN BỘ 19 ca đều là "cổ tức nhỏ chìm trong
nhiễu" (0.7-1.9% dưới sàn 2×nhiễu/mã — đúng thiết kế không phán bừa; để ý
hầu hết observed DƯƠNG +0.3..+1.2%, nếu chuỗi thô thì phải âm ≈ −kỳ vọng
→ thêm một lớp yên tâm không chính thức). Nhóm tiền mặt vừa mở khoá được
chấm lần đầu: SAB 4/4 · VNM 3/4 · PLX 2/2 · GAS 3/3 · VPB 2/2 — sạch hết.
Hai mã còn trắng là trắng THẬT: STB không chia cổ tức từ 2015 (tái cơ
cấu), MSN không chia tiền mặt giai đoạn này — thực tế doanh nghiệp, không
phải lỗ hổng dữ liệu.

Suite 2062 → **2066 passed**.

## 2026-08-15 (p) — Phát `all` tay đầu tiên trên máy bàn chết ở bước test: 2 bug Windows-only xếp chồng

Bối cảnh: user chạy tay cả chuỗi trên máy bàn (04:54 sáng 15/08), 8 bước
đầu ngon lành, đến bước test thì UnicodeDecodeError trong luồng đọc
subprocess rồi TypeError trong _Tee giết cả pipeline. Chẩn đoán một phát
ăn ngay NHỜ chính run_daily.log vừa xây — traceback nằm nguyên trong log.

Chuỗi nhân quả (CHỈ hiện trên Windows — container Linux mù ca này):
1. `cmd_test` capture output pytest với text=True mà KHÔNG khai encoding
   → Windows decode cp1252 → gặp byte UTF-8 tiếng Việt (0x8F — byte cuối
   chữ "ỏ") là luồng đọc CHẾT → proc.stdout = None. Anh em sinh đôi của
   bug đã vá trong `_run` 13/08 — QUÉT SÓT vì cmd_test có lệnh subprocess
   riêng.
2. `sys.stdout.write(None)` rơi vào `_Tee.write` → `return len(text)` nằm
   NGOÀI try → TypeError giết pipeline — vi phạm chính lời hứa "tee không
   bao giờ được giết pipeline" trong docstring của nó.

Vá 3 chỗ + 2 test: cmd_test thêm encoding="utf-8"/errors="replace" +
PYTHONIOENCODING (net AST canh); chỗ đọc proc.stdout đỡ None (`or ""`);
`_Tee.write` ép mọi thứ không phải str về str/"" trước khi làm gì (test
tee.write(None) == 0 không nổ). Quét cùng họ: vnstock_health.py:537 cùng
bug tiềm ẩn (suy biến êm chứ không crash) — vá luôn.

LỘC từ phát chết giữa chừng — SỐ THẬT ĐẦU TIÊN cho mục ② (8 bước đầu):
sync 870s · screener 514s · news 121s · validate 86s · foreign-flow 14s
· macro 12s · allocation 2s · gold 2s ≈ **27 phút**, sync là hog (~54%).
Đợi phát TRỌN VẸN (kèm test/train/brief) rồi mới phán theo luật ②.

Suite 2066 → **2068 passed**.

## 2026-08-15 (q) — Phát `all --no-sync` lần hai: encoding ĐÃ ỔN, lộ tiếp 1 test không hermetic

Bản vá encoding chạy chuẩn (bước test chạy trọn 67s, pipeline dừng đúng
thiết kế khi test đỏ, `⏱ TỔNG` in cả khi fail giữa chừng — screener 540s
là hog của phát no-sync). Lộ ra: **2067 passed · 1 FAILED chỉ trên máy
bàn** — `test_recommendation_block_excludes_overdue_and_keeps_precision`.

Nguyên nhân (tái hiện được 100% trong container bằng cách giả lập DB máy
bàn): test stub `open_recommendations` nhưng QUÊN stub `get_active_family`
— rec giả không mang strategy_id → `_recommendation_block` rơi về đường
"kiểm định của chiến lược ACTIVE" → đọc DB SQLite THẬT của máy chạy test.
Máy bàn có chiến lược active TRƯỢT kiểm định (p=0.764, số thật của nó) →
mọi rec fixture bị chặn ĐÚNG LUẬT → sentinel thay vì FPT → test đỏ oan.
Container/CI không có DB → unknown → không chặn → xanh. Máy bàn là máy
ĐẦU TIÊN vừa mang DB trượt kiểm định vừa chạy FULL suite (test_brief
không nằm trong --fast) — nên lỗ hermetic 13/08 mới lộ hôm nay.

Vá: 2 test (cái đỏ + đứa em `..._empty_when_all_overdue` cùng lỗ tiềm ẩn)
chốt thế giới `get_active_family → None` — ý đồ của chúng là lọc-quá-hạn
+ độ chính xác giá, không phải gating. Suite **2068 passed** (số không
đổi — sửa test, không thêm).

## 2026-08-15 (r) — Brief chiều cuối tuần: user bắt lỗi thiết kế lưới 15:00 → bất biến mới "một brief mỗi PHIÊN"

User hỏi "sao chưa thấy brief lên Telegram" → truy ra 3 tầng: (1) brief
là bước CUỐI, hai phát hôm nay đều chết ở bước test — chưa tới lượt;
(2) kể cả tới, lưới `_should_push_close` chặn <15:00 mọi ngày; (3) user
chỉ ra lưới đó SAI cho cuối tuần: "sau 15h thứ 6 đến hết chủ nhật thì
nên để chạy lúc nào cũng được". Phân tích thêm thì còn tệ hơn user nói:
với luật cũ, máy tắt tối thứ 6 (chuyện thường) → brief chiều THỨ 6 MẤT
VĨNH VIỄN — chạy bù T7/CN bị chặn <15:00, sang T2 sau 15:00 đã thành
brief phiên thứ 2. Nghĩa là cả một lớp brief cuối tuần chưa từng đến tay
user mà không ai hay (không có log thì càng không ai hay).

Thiết kế lại quanh bất biến MỚI: **một brief chiều cho mỗi PHIÊN giao
dịch** (`_close_session_date`: T2-T6 = hôm nay, T7/CN = thứ 6 vừa rồi):
* Ngày làm việc <15:00: chặn như cũ (phiên chưa đóng, đỡ run-on-boot).
* T7/CN: gửi giờ nào cũng được — dữ liệu không thể tươi hơn phiên thứ 6.
* Marker chống-trùng đổi từ NGÀY GỬI sang NGÀY PHIÊN → T7 gửi rồi CN im;
  tối T6 đã gửi thì T7 chạy bù cũng im. Marker cũ tương thích ngược 100%
  (ngày gửi các ngày làm việc ≡ ngày phiên).
* Ngày lễ giữa tuần: chưa phân biệt (không theo dõi lịch nghỉ) — ghi rõ
  trong docstring, hành vi như cũ.
3 test mới (mapping T6/T7/CN/T2 · luật cuối tuần đủ 5 nhánh · marker
phải mang ngày phiên — ghi ngày gửi là T7 xong CN bắn trùng).

**Diễn biến tiếp (user test tay NGAY 15/08): Telegram sống end-to-end** —
`telegram test` message_id=210 ✅ · `telegram close` gửi brief chiều THẬT
message_id=212 ✅. Lộ thêm lỗ nhỏ: lệnh tay `telegram close` KHÔNG ghi
marker → gửi tay xong chạy `all` là bắn TRÙNG cùng phiên. Vá: tách
`_write_close_marker` dùng chung pipeline + lệnh tay (bất biến
một-brief-mỗi-phiên không phân biệt đường gửi) + 1 test. LƯU Ý một lần:
phát gửi tay #212 xảy ra TRƯỚC bản vá nên marker chưa có trên máy bàn —
phát `all` ĐẦU TIÊN sau đó sẽ gửi thêm 1 bản trùng phiên 14/08 (vô hại,
coi như test end-to-end đường pipeline; muốn tránh thì `--no-brief`).
Từ phiên sau thì hết trùng.

Task roster máy bàn xác nhận đủ: 2/2 (Daily + Weekend) — CLAUDE.md ghi
"4 task" là số CŨ trước đợt gộp 29/07, đã sửa thành 2. Brief SÁNG chưa
từng có task tự động (thiết kế cần task riêng ~11:35 gọi `run.py telegram
morning`) — user muốn thì nói Claude thêm vào setup script.

Suite 2068 → **2072 passed**.


## 2026-08-15 (s) — Làm mục 9 + 10 (user gật "theo ý bạn"): vá guard nhãn kỳ NN + gate kiểm định cho Telegram

### Mục 9 — guard ĐÃ TỒN TẠI, trượt vì 2 dấu sao markdown

Đi tìm "viết guard mới" thì phát hiện `enforce_nn_window_label` (nhánh
"1D bị dán nhãn tuần") đã nằm sẵn trong chuỗi từ 12/08, VÀ ctx phiên #212
có đủ dữ liệu (block Tâm lý/momentum trong chính brief chứng minh
`market_sentiment` sống, signal `NN ròng 1D = -856 tỷ` chuẩn format).
Nó không bắn chỉ vì regex đòi KHOẢNG TRẮNG THUẦN giữa số và "tuần" —
brief viết "bán ròng **856 tỷ** tuần qua", cặp `**` chen giữa là thoát.
Bài học cùng họ với "guard quên nối = code chết trông y như sống": guard
NỐI RỒI mà pattern hụt một ký tự thì cũng chết y như vậy, và chỉ lộ khi
đối chiếu output THẬT (ở đây là brief Telegram thật user dán về).

Vá + mở rộng, vẫn MỘT guard (không đẻ guard trùng chủ đề):
* Mọi khe trong 2 nhánh cũ nay dung `[\s*]*`; dấu `*` bị nuốt được TRẢ
  LẠI qua hàm thay thế — cặp bold không lệch (lệch là loang đậm cả brief).
* Nhánh 3 MỚI cho vế sau của mục 9: số TUẦN của MỘT ngành bị nói như
  toàn thị trường ("Khối ngoại bán ròng 1,965 tỷ tuần qua (Họ VIN -1,965
  tỷ…)"). Magnitude khớp ĐÚNG MỘT ngành → chèn tên ngành ngay sau "ròng"
  ("bán ròng **Họ VIN** 1,965 tỷ…" — claim tự đúng phạm vi). Không phân
  xử được thì KHÔNG đụng: ≥2 ngành trùng số, trùng tổng 1D, hoặc câu đã
  nêu tên ngành trước con số (dòng canon "mạnh nhất (1 tuần): …" an toàn
  nhờ luật này). 3 test mới dùng NGUYÊN VĂN hai câu lỗi của #212.

### Mục 10 — phương án (b): Telegram ẩn, dashboard giữ nguyên

Luật ẩn của brief (`_val_of` trong `_recommendation_block`) tách ra
`split_recs_by_validation` (vnstock_brief) — MỘT nơi cho cả hai kênh,
cùng lý lẽ với điểm parity `apply_brief_guards`: ẨN ⇔ known-VÀ-trượt;
không đo được ≠ trượt (unknown vẫn hiện); rec mang `strategy_id` xử theo
kiểm định của CHÍNH nó. `_open_recs_block` (vnstock_telegram) giờ lọc
qua đó: lệnh trượt biến khỏi danh sách, thay bằng dòng đếm "· N lệnh ẩn
— chiến lược nguồn chưa đạt kiểm định (xem đầy đủ trong dashboard)";
header đếm theo lệnh HIỆN; caveat BUY-dưới-bối-cảnh-GIẢM chỉ xét lệnh
ĐANG HIỆN. Ẩn hết thì còn header + dòng đếm (block không biến mất âm
thầm). Dashboard không đổi — sổ đối soát vẫn đủ.

Lưới: 2 net parity (brief + telegram đều phải GỌI splitter — ai inline
lại là đỏ) · unit splitter (known-failed ẩn / passed + unknown hiện /
legacy không sid theo active / dedup validation) · 5 test telegram stub
Ở TẦNG SQLITE (get_active_family/latest_backtest) để chuỗi thật chạy đủ
mà vẫn hermetic — né đúng vết 15/08 (q); 3 test format cũ của
`_open_recs_block` cũng được trám stub active-family vì gate mới đã đứng
trước format.

Suite 2072 → **2082 passed** (+10).


## 2026-08-17 — Heatmap VN30 live CHƯA BAO GIỜ hiện được: cờ `live_mode` chết khi chuyển tab (mục 1 bắt đúng con mồi)

User làm mục 1: bật Live Mode ở tab Phân tích rồi sang tab Thị trường —
khối live KHÔNG hiện, không cả dòng "⏳ Chờ WSS data..." (ảnh chụp: hàng
badge dính sát tiêu đề "Diễn biến chỉ số…", sidebar không còn mục Live
Mode). Chẩn đoán ra bug thật, không phải thao tác sai:

* Nav dùng `st.pills` + render có điều kiện → mỗi lượt chạy CHỈ tab đang
  mở được render (chính comment code: "dùng pills thay tabs để tránh
  lazy-render").
* Toggle "Real-time WSS" nằm trong sidebar tab Phân tích, bind THẲNG
  `key="live_mode"` — mà Streamlit XOÁ session_state của widget không
  được render trong lượt. Bấm sang Thị trường là toggle biến khỏi cây
  render → cờ bị dọn → `market_tab` đọc `get("live_mode")` ra None →
  toàn khối live (khung chỉ số + heatmap VN30) skip IM LẶNG.
* WSS client vẫn sống (`@st.cache_resource` singleton) — chỉ LÁ CỜ chết.
  Tức khối heatmap chưa bao giờ render được qua đường điều hướng thật;
  đúng khối duy nhất smoke 12/08 không phủ được, và đúng thứ bước soi
  mắt mục 1 sinh ra để bắt.

Vá (`dashboard/analysis_tab.py`): tách key — widget giữ
`key="live_mode_toggle"`, cờ cho tab khác đọc GÁN TAY
`st.session_state["live_mode"] = live_on` (key thường, Streamlit không
dọn; quay lại tab Phân tích toggle tự khôi phục qua `value=`). Nhánh đọc
nội bộ tab Phân tích (fragment live chart) không đổi vì cùng đọc cờ tay.

Lưới mới `tests/test_live_mode_crosstab.py` (+5): 3 structural canh CẢ
HAI PHÍA hợp đồng key (widget cấm bind `live_mode` · analysis phải gán
tay · market phải còn đọc đúng key — đổi tên một phía là đỏ) + 2 render
qua harness smoke (cờ sống → markup "VN30 Heatmap" phải xuất hiện; không
cờ → vắng chủ ý). Đối chứng: regex chạy trên bản CŨ → đỏ đúng cả hai.
Cùng họ bài học 15/08 (s): lỗi chỉ lộ khi đối chiếu ĐƯỜNG ĐI THẬT của
user, smoke gọi thẳng hàm không thấy được vòng đời session_state.

Suite 2082 → **2087 passed** (+5). Còn nợ verify MẮT trong phiên sau khi
merge — mục 1 cập nhật trạng thái.

**Bổ sung cùng ngày — khối live không được vắng mặt ÂM THẦM nữa.** User
báo "vẫn không thấy gì" sau bản vá đầu (khả năng cao máy chạy code cũ —
Streamlit KHÔNG tự nạp lại module `dashboard/` đã import, sửa file phải
RESTART process, và `git pull` thì dính bẫy "Already up to date"). Nhưng
gốc rễ khó chẩn đoán là: cờ tắt thì khối biến mất không dấu vết — không
phân biệt nổi "chưa bật" / "cờ chết" / "code cũ". Vá thêm nhánh `elif
WSS_AVAILABLE`: caption "🔌 Live Mode tắt — bật Real-time WSS ở sidebar
tab Phân tích…" — cùng lý lẽ "block không biến mất âm thầm" của Telegram
15/08 (s), kiêm CHỨNG CHỈ CODE MỚI: mở tab Thị trường mà không thấy dòng
này (khi chưa bật live) = máy còn chạy bản cũ. Test render "skip" mở
rộng canh caption này (ai dọn mất là đỏ). Suite giữ 2087.

**Bổ sung lần 2 — toggle Live Mode CHUYỂN LÊN sidebar chung + đối chứng
end-to-end bằng trình duyệt thật.** Sau merge bản vá, user vẫn báo "bật
livemode rồi mà vẫn báo tắt" (caption 🔌 hiện = code mới ĐÃ chạy). Dựng
Streamlit THẬT 1.61.1 + Playwright/Chromium trong container để đo: (a)
repro tối giản pills + toggle-trong-tab-A + đọc-cờ-ở-tab-B → cơ chế vá
ĐÚNG, cờ sống qua chuyển tab; (b) vậy nghi phạm còn lại là thao tác —
repo có tới BA toggle tên na ná ("Real-time WSS" tab Phân tích ·
"🔴 Live Scan (real-time)" Screener · "Live Scan (real-time)" Dòng Tiền,
user hỏi đúng về cái thứ ba giữa lúc debug), bật nhầm Live Scan thì cờ
động cơ vẫn tắt. Sửa TẬN GỐC cả hai chuyện: chuyển toggle + dải trạng
thái WSS từ sidebar tab Phân tích LÊN SIDEBAR CHUNG của main script
(dưới Light mode) — widget render MỌI lượt nên không còn lớp bug dọn
widget-state nào, và công tắc động cơ thấy được từ mọi tab, hết nhầm
với Live Scan (vốn chỉ là CONSUMER đọc quote do động cơ ghi ra
`data_warehouse/_live/`). Tab Phân tích giờ chỉ ĐỌC cờ. Lưới structural
viết lại: cấm mọi file bind widget `key="live_mode"` · toggle
`live_mode_toggle` PHẢI ở main script và CẤM ở dashboard/*.py (ai dời
về tab là đỏ) · market_tab phải còn đọc đúng key. Đối chứng cuối: boot
DASHBOARD THẬT trong container (mồi screener_results.json tối thiểu),
Playwright đi đúng đường user — bật toggle ở sidebar → sang tab Thị
trường → hết "Live Mode tắt", khối live render "⏳ Chờ WSS data..."
(container không có tick; trên máy thật trong phiên sẽ ra heatmap).
Suite giữ **2087 passed**. Ghi chú vận hành cho máy user: sau merge phải
RESTART dashboard; toggle giờ nằm sidebar trái mọi tab.

**Bổ sung lần 3 — user chốt hướng (a): khoá Live Scan khi động cơ tắt.**
Hai toggle Live Scan (Screener `live_scan_on` · Dòng Tiền `mf_live`) giờ
gate theo động cơ: `_wss_engine_on = cờ live_mode AND WSS_AVAILABLE` —
động cơ tắt thì toggle `disabled` + KÉO VỀ OFF (khỏi đứng ON-nhưng-xám
nói dối trạng thái; bỏ `value=False` để set-state không sinh warning
default-vs-state của Streamlit) + caption "🔌 Cần bật 🔴 Live Mode ở
sidebar trái trước." Test structural mới trong
`test_live_mode_crosstab.py` canh đủ 3 vế (nhìn cờ / disabled / kéo OFF
+ caption) cho CẢ HAI file. Đối chứng app thật bằng Playwright đủ 4
chiều: Screener tắt→caption hiện, bật động cơ→caption biến, Dòng Tiền
đang bật→sạch, tắt lại→caption hiện lại. Suite 2087 → **2088 passed**.

**Bổ sung lần 4 — máy user `run.py all` FAIL CỨNG ở bước test: ca sót
của vết 15/08 (q), test không hermetic chỉ đỏ trên máy có DB thật.**
`test_open_recs_block_appends_caveat_under_bear` (test_close_1507_review)
patch open_recommendations + _market_is_bearish nhưng QUÊN trám tầng
SQLite — rec GMD không mang strategy_id → gate mục 10 rơi về kiểm định
của chiến lược ACTIVE đọc từ DB thật. Máy user: active trượt (p=0.974)
→ GMD ẩn thành "1 lệnh ẩn" → caveat mất chỗ bám → test đỏ → `all` dừng
TRƯỚC audit/train/reflection/doctor/brief (các bước data TRƯỚC đó đều
xong). CI/container không có DB → xanh — đúng lý do lưới 15/08 chỉ trám
được 3 test trong test_telegram.py mà không thấy test thứ 4 ở file khác.
Tái hiện trong container bằng stub get_active_family={id}+backtest fail
→ đỏ Y HỆT log user; vá cùng pattern "hermetic mục 10" (stub
get_active_family=None trong cả 2 with-block, kèm comment tại chỗ);
repro pass ở CẢ HAI trạng thái DB. Đã quét: các file khác đụng
_recommendation_block/splitter đều có stub, và full suite của user
(2087 pass + 1 fail) chính là bằng chứng tích hợp mạnh nhất rằng chỉ
sót đúng ca này. Suite giữ **2088 passed**.
Tiện ghi từ log user: ⏱ TỔNG 64.7' — sync 2.376s vẫn nặng (quarantine
3.836 bar đang tự rút theo retry, dự kiến teo sau 1-2 phát); mục 8 đổi
số: vnstock 4.0.6 / vnai 2.5.7 đã ra (vẫn CHƯA nâng, đúng kế hoạch).

**Bổ sung lần 5 — user merge fix, chạy `all --no-sync` TRỌN BỘ exit 0,
và 🏁 CHIẾN LƯỢC ĐẦU TIÊN ĐẠT KIỂM ĐỊNH SAU KHI NÂNG SÀN 30 LỆNH.**
Log 17/08 (12 bước, TỔNG 54.4'): 2088 test pass trên máy thật (fix
hermetic ăn) → audit approved (Gemini conf 1.00) → train 2 tầng:
* tier=short #35 RETIRED — 329 lệnh, expectancy −0.287, p=0.885 → đúng
  luật không phát rec;
* **tier=position #32 ACTIVE — 94 lệnh (≥ sàn 30), expectancy +2.47,
  exit mix TP 34/SL 35/hết hạn 31, kiểm định ✅ ĐẠT p=0.012 →
  `emit_recommendations` phát 5 rec mới** (scan 3.125 mã, vol ≥ 100K).
  Đây là sự kiện cả hàng chờ 0e/4c đợi từ 13/08: mục khuyến nghị
  [vị thế ~20 phiên] MỞ LẠI trong brief bằng con đường tự chứng minh
  (tune đêm + gate Bonferroni + sàn 30), không phải nới luật.
  Lưu ý đối soát khi rảnh: expectancy nhảy 0.197 (67 lệnh, 13/08) →
  2.47 (94 lệnh) sau 2 đêm tune — hợp lệ qua gate nhưng đáng liếc panel
  Chiến lược xem tham số revise thành gì.
* reflection 3 bài học (Gemini/Cerebras 429 → ladder tự rơi bậc, đúng
  hồ sơ); doctor 15✅·2⚠️; brief chiều #217 ĐÃ GỬI (bước brief 1.131s —
  nặng nhất pipeline, phần lớn là chờ retry 429; để mắt phát 18:00).
* Doctor ⚠️ quy đổi giá KÍCH HOẠT mục 3: soi chart WSS · WTC · XPH ·
  YBM · YEG — YEG tỷ lệ 764× lệch xa 1000 đáng ngờ nhất (nghi chia
  tách bị quy đổi oan → báo Claude kèm dòng doctor). Ledger ⚠️ hôm nay
  là tự đốt (2 phát pipeline + brief tay) — đúng luật "chỉ soi khi ngày
  KHÔNG chạy tay vẫn ⚠️".
→ Brief #217 giờ là bàn VERIFY 3-trong-1 cho 0b + mục 9 + mục 10, và
mục 10 có đủ CẢ HAI chiều: lệnh tầng ngắn (trượt) phải thành dòng "N
lệnh ẩn", lệnh #32 (đạt) phải HIỆN.

**Bổ sung lần 6 — user dán brief #217: verify 3-trong-1 ĐẠT, nhưng lộ
1 bug xuyên tầng THẬT trong guard caveat → vá + 2 test.**
Kết quả soi #217: ✅ 0b (không dòng "KHÔNG CÓ" oan — "Chưa có nhóm dẫn
dắt rõ ràng" là nhận định nội dung hợp lệ phiên đi ngang; regime/momentum
đủ số) · ✅ mục 9 (NN 1D "-588 tỷ trong phiên" khớp doctor -587.6; số
tuần đều kèm nhãn "1 tuần" + TÊN NGÀNH — không còn tự mâu thuẫn như #212)
· ✅ mục 10 CẢ HAI chiều (4 rec #32 hiện đúng "ngày 0/20", tầng ngắn gom
"6 lệnh ẩn — xem trong dashboard").
BUG lộ ra: mục Đề xuất giao dịch dán caveat "CHƯA QUA kiểm định
**(p=1.000)**" lên chính rec của #32 vừa ĐẠT p=0.012 — tự mâu thuẫn với
block Khuyến nghị đang mở ngay dưới. Nguyên nhân:
`enforce_unvalidated_strategy_caveat` đọc `ctx["strategy_validation"]`
= kiểm định của active tầng NGẮN (trượt, p_adj=1.0), trong khi cờ
`strategy_recs_in_prompt` từ 13/08 không còn ngầm định "rec = của tầng
ngắn" (hai tier + splitter 15/08: emitted chỉ còn passed/unknown). Vá:
`_recommendation_block` ghi thêm `ctx["strategy_recs_validation"]`
(kiểm định của CHÍNH recs trong prompt), guard ưu tiên key này, thiếu
key mới rơi về key cũ (giữ vai trò hàng rào cho luồng chưa cập nhật).
2 test mới (unit + end-to-end dựng đúng kịch bản #217: active #1 trượt
p=1.0, rec sid=32 đạt n=94) — đối chứng cả hai ĐỎ trên code cũ.
Suite 2088 → **2090 passed**.
Ghi nhận nhỏ: (1) ✅ đếm lệch 12-vs-10 ĐÓNG — user chụp panel Chiến
lược 17/08: đúng 10 lệnh mở, khớp Telegram 4+6 TỪNG DÒNG (6 ẩn = đúng
6 lệnh 5d tầng ngắn: ABW mới + SBG/MSB/HNM/DSE/CTF cũ; 4 hiện = đúng 4
lệnh 20d của #32). Cơ chế là BY DESIGN: `emit_recommendations` supersede
lệnh mở trùng mã trước khi mở lệnh mới (`supersede_open_recommendations`,
vnstock_strategy ~2328) — 2 lệnh cũ trùng mã bị thay, 7−2+5=10. Panel
còn khép kín chuỗi bug caveat: tầng ngắn active (family-05f9d495) hiện
đúng "KHÔNG đạt (p=1.000)" = con số bị dán nhầm vào #217. Quan sát nhỏ
không chặn: card active short mang nhãn "v1 · tuned 16/06" nhưng số
expectancy −0.29/329 lệnh khớp #35 (bản backtest đêm qua, retired) chứ
không khớp dòng #16 (−1.06/113) ở Top strategies — khả năng card lấy
backtest MỚI NHẤT của family còn nhãn là bản active gốc; không ảnh
hưởng gating, khi nào rảnh soi code panel cho rõ lineage.
(2) "bán ròng -588 tỷ" mang dấu âm thừa (bán ròng đã hàm ý âm) — thẩm
mỹ, chưa đáng thêm guard.

---

# 📌 VIỆC PHẢI LÀM — chốt 12/08/2026

> Danh sách ĐANG DÙNG — bản sạch thay bản 11/08 (mọi mục đã xong nằm trong
> entry nhật ký 10-12/08). **Mục này PHẢI luôn nằm CUỐI FILE** — thêm entry
> nhật ký mới thì chèn TRƯỚC mục này.
>
> Trạng thái: full suite **2146 passed** (`--fast` ~1.585 test — ~26-42s trên CI,
> ~64s trên máy thật; ~44s trong đó là test an ninh sandbox, user chốt GIỮ
> 13/08 — xem entry 13/08) · nhánh `claude/remaining-tasks-tests-4xoam3`
> đã merge máy bàn 15/08 · nhánh MỚI `claude/tong-hop-cong-viec-test-w8mvrc`
> (fix live_mode 17/08) đã push, CHỜ MERGE. Đồng bộ máy + push main:
> user tự làm thường xuyên — KHÔNG track làm việc (user chốt 12/08).

## 🔴 VIỆC TAY — sau đợt tách file 12/08

> ✅ **Mục 🧭 Nhận định thị trường: ĐÃ VERIFY XONG 13/08** — bỏ khỏi phần
> phải soi bên dưới. Đối chiếu 3 tầng trên máy thật: 37/37 test máy · cấu
> trúc đủ 3 mục đúng thứ tự · **9/9 con số khớp** — MA200 10.8%→"11%" (làm
> tròn có chủ ý), RSI<30 118 mã, RSI>70 117 mã, **A/D 1.08 → IM LẶNG đúng
> thiết kế** (bằng chứng mạnh nhất: ngưỡng 0.8–1.2 còn nguyên), net new highs
> −33 đúng dấu đúng nhánh, VNINDEX/VN30 đều 3/5 tăng + TB lệch 0.01pp (dưới
> sai số làm tròn 0.05pp của bảng %D). Chi tiết trong lịch sử hội thoại 13/08.

**0. ✅ ĐÓNG TRỌN 13/08 — dashboard đã soi mắt đủ 5/5 mục** (riêng heatmap
live cần giờ giao dịch → gộp mục 1).
Đợt 12/08 kéo ~2.400 dòng giao diện ra khỏi hai hàm khổng lồ; máy tự kiểm
"code có chạy hết không", phần "hiển thị có đúng không" soi mắt:
* ✅ **Tab Thị trường** — 13/08 qua ảnh: bảng ngành đủ cột + màu + sparkline;
  drill-down Ngân hàng (27 mã) VÀ Họ VIN/Họ M (sau vá) đều mở đúng.
* ✅ **Khối 🤖 AI Market Brief** — 13/08 qua ảnh: Cài đặt agent · Lịch sử ·
  Chiến lược render đủ; đã sinh brief thật (4 giọng, consensus).
* ✅ **Tab Phân tích** — 13/08 qua ảnh VCB/VCI + kéo/zoom tay: 4 panel thẳng
  hàng cùng số nến, RSI/MACD chạm nến cuối, kéo/zoom đồng bộ — chi tiết ở
  entry 13/08 (h).
* ✅ **Watchlist** — 13/08: thêm rồi xoá một mã trong Screener, danh sách
  cập nhật đúng — đường ghi nguyên tử mới chạy êm.
* ✅ **Treemap + Chart xu hướng** — 13/08 qua ảnh: cả hai vẽ đủ hình, số
  hợp lý (treemap VIC/VCB dẫn vốn hoá, màu khớp chiều 1M; chart cột sắp
  đúng thứ tự, có đủ Họ VIN/Họ M). Ghi nhận một bất đối xứng ĐÚNG THIẾT KẾ,
  đừng báo lỗi: treemap gom theo NGÀNH GỐC nên KHÔNG có ô Họ VIN/Họ M —
  bản chất treemap mỗi mã chỉ được MỘT ô, không vẽ lớp phủ được; chart cột
  đi theo bảng ngành nên CÓ hai nhóm tuỳ biến (lớp phủ §4b). Đã soi code
  `market_tab.py` xác nhận 13/08. *(Mục từng bị sót vì chỉ nằm trong
  chat — user bắt 13/08.)*
* ↪ **Live Market Heatmap VN30** (đầu tab Thị trường) — khối DUY NHẤT máy
  không phủ được dòng nào vì chỉ chạy khi WSS sống trong giờ giao dịch.
  Rủi ro thấp (code không đổi) → GỘP vào mục 1 bên dưới, làm cùng phiên.

**0g. Sáng 18/08 — user chạy 3 lệnh Select-String (checklist 0c):**
`tier=` ✅ đủ 2 dòng ở CẢ HAI phát 12 bước (15/08 + 17/08 tối) ·
`collect_context` ✅ im lặng = mọi nguồn khoẻ · `⏱` đọc được: sync
9,731s (heal đỉnh) → 2,376s (17/08) đang teo đúng dự đoán; pipeline lõi
no-sync trọn bộ 25.6' (15/08) / 54.4' (17/08, brief 1,131s vì 429 tự
đốt). **Mục ② CHƯA chấm — log KHÔNG có phát 18:00 TỰ ĐỘNG nào**: từ
23:11 17/08 về trước chỉ toàn phát tay. ⚠️ NGHI VẤN MỚI: task Daily
18:00 hôm 17/08 không để lại dấu vết trong run_daily.log — đã đưa user
lệnh `Get-ScheduledTaskInfo` để soi LastRunTime/LastTaskResult, chờ
kết quả. Phát 18:00 tối 18/08 (code đã merge đủ fix) mới là "đêm tự
động đầu tiên" đúng nghĩa → sáng 19/08 lặp lại 3 lệnh, chấm ② lúc đó.
→ **GIẢI MÃ (user dán TaskInfo ngay sau):**
* **Daily 17/08**: task ĐÃ kích hoạt — LastRunTime **19:07:07** (chạy
  bù sau khi lỡ hẹn 18:00, lúc đó phát tay 64.7' của user đang chiếm
  máy) nhưng LastTaskResult **0xC000013A = BỊ NGẮT giữa chừng** trước
  khi xong bước nào (vì thế log trắng — ⏱ chỉ in khi một bước XONG).
  Khớp hoàn cảnh: buổi tối user đang merge + chạy tay `all --no-sync`
  22:17 — hai phát giẫm nhau / cửa sổ console của task bị đóng nhầm.
  KHÔNG phải lỗi cấu hình: NextRun 18/08 18:00 đã lên nòng. BÀI HỌC
  VẬN HÀNH (nối bài 15-16/08): tránh chạy pipeline TAY vắt qua giờ
  18:00, và buổi tối thấy cửa sổ console lạ đang chạy thì đó có thể là
  task chạy bù — đừng Ctrl+C/đóng.
* **Weekend 15/08**: LastRunTime 09:00 đúng hẹn, LastTaskResult **1 =
  chạy XONG có cảnh báo** (bình thường với probe model — tuần trước
  08/08 mới là fail cứng result=2). Tức báo cáo model watch T7 ĐANG
  NẰM TRONG LOG mà mục 2 checklist vẫn CHƯA ĐỌC — việc đọc nó (bảng
  điểm 5 nhà, Mistral lần đầu, nemotron-ultra còn bò → quyết mục 5)
  vẫn mở.

**0b. Đọc brief sáng/chiều kế tiếp — có dòng "KHÔNG CÓ …" nào oan không.**
Prompt vừa thêm cảnh báo cho 3 khối (movers, dẫn dắt/tụt hậu, quant regime).
Cảnh báo chỉ được hiện khi nguồn đó THẬT SỰ thiếu data. Brief bình thường mà
lại thấy "Chưa có dữ liệu mã đủ thanh khoản" hay "chưa có regime hôm nay" →
báo Claude: nghĩa là điều kiện nhận diện đang bắt nhầm.
Từ 13/08 (d) thêm một điều ĐÚNG THIẾT KẾ, đừng báo lỗi: chiến lược hiện tại
đang trượt kiểm định (p=0.974) → brief **không còn mục khuyến nghị từ chiến
lược** nữa (user chốt "trượt là không phát"). Mục Đề xuất giao dịch chỉ còn
setup từ movers ⭐. Khuyến nghị tự quay lại khi chiến lược đạt kiểm định.

**0d. ✅ XONG 13/08 — đã đo tầm với TP.** Kết quả + diễn giải ở entry 13/08
(e). Chốt: tầng vị thế = 20 phiên; TP 2.5×ATR ở 5 phiên chỉ với tới 16%.

**0e. ✅ XONG 13/08 — tầng vị thế đã khởi tạo.** Chiến lược #32: 67 lệnh,
expectancy +0.197, exit mix **TP 44.8%** / SL 40.3% / hết hạn 14.9% — cơ chế
thoát ĐÃ CHỮA XONG (live tầng 5 phiên cũ: TP 0%, hết hạn 71%; số đo dự báo
trần ~46% ở 2.5×ATR — trúng). Kiểm định: 🎲 CHƯA ĐẠT — p thô 0.377 (hiệu
chỉnh chọn-lọc 1.0), chỉ 25% cửa sổ thời gian dương (lãi dồn cục — khớp
caveat "500 phiên gần nhất toàn thị trường lên"). Brief đúng luật KHÔNG nhận
rec của #32; nó ở lại ghế làm việc, được tune + đối soát để tự chứng minh.
*(Diễn biến tiếp: tune 13/08 co mẫu 67→19 và "đạt" p=0.040 → user chốt nâng
sàn bằng chứng lên 30 lệnh, verdict bị hạ lại tại điểm đọc — entry (f)+(g).
→ **17/08: #32 TỰ CHỨNG MINH XONG** — 94 lệnh ≥ sàn 30, p=0.012, ACTIVE,
phát 5 rec: mục khuyến nghị tầng vị thế MỞ LẠI trong brief (entry 17/08
bổ sung lần 5). Tầng ngắn vẫn đóng — #35 retired p=0.885.)*

**0f. ✅ ĐÓNG 15/08 — PRODUCTION TRAIN CẢ 2 TẦNG, bằng chứng log máy bàn.**
Phát `all --no-sync` lần 3 (15/08): log ghi ĐỦ HAI dòng
`[strategy_loop] tier=short …` và `tier=position …` — cùng 4 agent
(Mistral lead · Cerebras · Nemotron · Gemini). Chuỗi giải quyết: tưởng
sửa Task Scheduler → hoá ra sửa 1 chỗ `run.py cmd_train --tier both`
(13/08) → merge máy bàn + 3 vòng vá bug production (encoding cp1252, tee
nuốt None, test không hermetic) → chạy thông. Từ nay MỖI ĐÊM ngày làm
việc hai tầng tự tune/tìm ứng viên ≥30 lệnh đạt chuẩn — con đường duy
nhất mở lại mục khuyến nghị trong brief. `collect_context` cùng phát:
IM LẶNG = mọi nguồn dữ liệu khoẻ (đóng luôn vế nguồn của 0c).

**0c. Soi `run_daily.log` sau phát pipeline 18:00 — ⚠️ 14/08: hoá ra nãy
giờ soi NHẦM MÁY. Việc này là việc của MÁY BÀN.**
Diễn biến: grep log ra 5 header đều chạy tay 13/08 (doctor ×3 · dashboard
15:13 · refresh-metadata 16:13 — tee sống hoàn hảo từ 15:03), không có
phát `all` 18:00 → Claude kết luận "pipeline không chạy". User đính chính:
**đang làm trên LAPTOP** — mà cả `run_daily.log` lẫn Task Scheduler đều
THEO MÁY; desktop mới là máy production (notes ~2201). Laptop không có
task 18:00 là BÌNH THƯỜNG, không nói gì về pipeline thật.
Chuyện lộ ra TO HƠN: mọi merge 13-14/08 mới nằm trên laptop — nếu desktop
CHƯA merge thì production vẫn chạy code cũ: KHÔNG ghi log, và đêm nào
cũng chỉ train TẦNG NGẮN (chưa có `--tier both`), thiếu cả loạt fix khác.
**📋 GÓI MÁY BÀN — trọn bộ việc còn lại, chốt với user 14/08 (một buổi
+ một buổi sáng):**

*Buổi ngồi máy bàn:*
1. **Merge** (mở khoá mọi thứ bên dưới):
   `git fetch origin claude/remaining-tasks-tests-4xoam3` rồi
   `git merge origin/claude/remaining-tasks-tests-4xoam3`
2. ✅ ĐÃ SOI (cuối tuần 15-16/08): task SỐNG, có "chạy bù khi lỡ hẹn" —
   14/08 máy tắt lúc 18:00 → tự chạy bù 20:22 (giải thích vì sao kho vẫn
   sync đều bấy lâu). NHƯNG LastTaskResult = 0xC000013A: phát bù bị NGẮT
   GIỮA CHỪNG (tắt máy khi pipeline đang chạy). BÀI HỌC VẬN HÀNH: tối nào
   máy bàn đang chạy pipeline (~20-40 phút) thì để xong hẵng tắt. Task
   daily chỉ chạy NGÀY LÀM VIỆC (NextRun 17/08 thứ Hai). Phát chạy tay
   sáng 15/08 CHẾT ở bước test — 2 bug Windows-only, ĐÃ VÁ (entry (p)).
   CHẠY LẠI sau merge bằng:
   `python run.py all --no-sync`
   (bỏ sync+validate đã xong sáng 15/08, tiết kiệm ~16 phút; ĐỂ MÁY BẬT
   tới khi xong ~15-25 phút) rồi soi 3 lệnh dưới luôn, khỏi đợi thứ Ba.
3. (tiện tay, ~10 phút, cần mạng) thử phủ vùng mù 4d sau bản gộp 3 nguồn:
```powershell
python run.py refresh-metadata --events
python vnstock_div_check.py
```
   (cách đọc kết quả: mục 4d — mã nào vẫn 0 sự kiện = cả 3 nguồn đều mù.)

*SÁNG HÔM SAU (sau đêm 18:00 đầu tiên chạy code mới) — BA lệnh một thể,
TRÊN MÁY BÀN:*
```powershell
Select-String -Path run_daily.log -Pattern "tier="
Select-String -Path run_daily.log -Pattern "collect_context"
Select-String -Path run_daily.log -Pattern "⏱"
```
* `tier=` phải ra ĐỦ HAI dòng `[strategy_loop] tier=short …` VÀ
  `tier=position …` = train 2 tầng chạy thật (đóng luôn kiểm chứng 0f).
* `collect_context` không ra gì = mọi nguồn khoẻ. Có dòng `nguồn '<tên>'
  hỏng` lặp lại mỗi tối → báo Claude tên nguồn.
* `⏱` nhìn dòng `TỔNG X phút`: X < ~30 và không bước nào chiếm quá nửa
  → mục ② khép luôn với kết luận "không đáng tối ưu"; một bước nghẽn rõ
  → dán output cho Claude mổ đúng bước đó (luật đầy đủ: mục ②). Việc ĐO
  pipeline tự làm mỗi đêm — lệnh này chỉ là cửa sổ ĐỌC, không phải việc
  định kỳ; sau lần quyết ② nó thành công cụ chẩn đoán khi nào thấy
  pipeline ì thì lôi ra.
(Thích đọc cả file: `notepad run_daily.log`.)
*Còn heatmap VN30 cần PHIÊN GIAO DỊCH, máy nào cũng được — xem mục 1.*
✅ **Đã giải mã badge 2⚠️ (user dán doctor 13/08)** — KHÔNG có nguồn hỏng,
15 ✅: (1) **Phân bổ tài sản** = nhắc việc THÁNG — ✅ user đã tạo brief
tháng 8 ngay 13/08 (4 giọng, số ghim chuẩn; lộ + vá luôn bug render
"too many values" — entry 13/08 (k)), ⚠️ này tự tắt;
(2) **LLM ledger** 50 call/26 lỗi/6 rate-limit ngày 13/08 —
hôm đó tự mình đốt tải (sinh brief thật 4 giọng + test), chạm trần Gemini
flash + 2 gemma free đúng hồ sơ đã biết (503 đêm VN + 429 free tier, mục
6/7 đang theo dõi). Đào sâu khi cần: `python vnstock_llm_ledger.py --show`
(có cột last_error). Doctor hôm khác vẫn ⚠️ ledger dù KHÔNG test tay →
lúc đó mới đáng soi.

**1. ✅ PHẦN VOLUME XONG 13/08 — WSS volume tích luỹ ĐẠT CẢ 3 bất biến.**
Món nợ verify cuối của đợt fix 07/08 ĐÃ ĐÓNG: user chạy
`python scripts\verify_wss_live.py` trong phiên 13/08 → ✅ 28/30 mã volume
> 0 (top TCB 264,700) · ✅ index volume == 0 đủ 4 chỉ số · ✅ suspect_count
= 0. VN30F1M vắng trong bảng chấm là ĐÚNG THIẾT KẾ — phái sinh đi kênh
riêng poll `price_depth` → `quote_VN30F1M.json`, không qua đường tick→bar;
đường đó chỉ chở cổ phiếu + index và cả hai đã chấm (entry 13/08 (i)).
Cần chạy lại sau này (nghi WSS hỏng): vẫn lệnh đó, trong phiên.
* ✅ **HEATMAP ĐÓNG 18/08 — soi mắt ĐẠT qua ảnh user, trong phiên.**
  Món nợ soi mắt CUỐI CÙNG của đợt tách file 12/08 khép sổ. Hành trình:
  17/08 user soi → bắt bug thật (cờ `live_mode` bind widget bị Streamlit
  dọn khi rời tab → khối live CHƯA BAO GIỜ render qua đường điều hướng
  thật) → 3 bản vá (tách key cờ · caption chỉ đường chống-vắng-âm-thầm ·
  toggle chuyển lên sidebar CHUNG + khoá 2 nút Live Scan theo động cơ)
  + lưới test + đối chứng Playwright trên app thật → 18/08 trưa user
  bật lại trong phiên: ảnh cho thấy ĐỦ VÀ ĐÚNG — khung 4 chỉ số
  (VNINDEX 1,734.72 +0.49%…), nhãn heatmap, lưới 30 ô sắp giảm dần theo
  % (PLX +6.36% → TCB −2.20%), breadth `↑16 =2 ↓12 (30 mã)` cộng đúng,
  sidebar CONNECTED (polling) · 3091 mã subscribe. Ghi nhận: ô hàng cuối
  giãn rộng là flex-wrap đúng code; "3091 mã" > ước lượng cũ "~1.100"
  trong docs vì full-market gồm cả UPCOM/CW — con số docs là ước lượng
  lỗi thời, không phải lỗi. Cần soi lại sau này (nghi WSS): vẫn trình
  tự đó — toggle sidebar trái → tab Thị trường, trong phiên.
  ↪ **Nâng cấp cùng ngày (user đặt): bề rộng ô ≈ VỐN HOÁ tương đối.**
  Cap đọc từ `_mkt_ticker_data` (bảng ticker screener). Ba quyết định
  đều ĐO trên trình duyệt thật trước khi chốt, không đoán:
  (1) nén **sqrt** — VIC/POW cap chênh 23.9× ra bề rộng 4.5×: ô nhỏ vẫn
  đọc được chữ mà tương quan vẫn thấy ngay;
  (2) **flex-basis %** chứ KHÔNG phải flex-grow — bản grow đo được
  28/30 ô dính đúng 80px (min-width nuốt sạch chênh lệch, tỷ lệ chết);
  (3) **grow = 0** — bản grow=1 làm TCB phình 575px ở hàng cuối, bề
  rộng lúc đó NÓI DỐI vốn hoá; đổi lại lề phải hàng cuối so le.
  Mã thiếu cap đi trọng số TRUNG VỊ (không teo, không phình, không
  tooltip); chưa có bảng cap (lượt render đầu, fragment chạy TRƯỚC thân
  tab) → mọi ô bằng nhau như cũ và KHÔNG hiện nhãn "rộng ô ≈ vốn hoá"
  (nhãn mà không scale là nói dối). Hằng số `_HEATMAP_WIDTH_SPAN=300`
  (≈3 hàng) ở đầu `market_tab`. Kiểm chứng cuối: dựng HTML DO CHÍNH
  CODE SINH RA rồi đo trong Chromium — VIC 379px · VCB 299 · VHM 256 ·
  TCB 220 · PLX 107 · POW 84. +4 test (tỷ lệ sqrt & tổng % = span ·
  cấm stretch · mã thiếu cap ăn trung vị · fallback bằng nhau).
  Suite 2090 → **2094 passed**.

## ⏳ TỰ ĐẾN — chỉ cần ĐỌC khi tới

**2. ✅ ĐÓNG 18/08 — báo cáo model watch T7 15/08 đã đọc trọn** (user dán
nguyên văn; task chạy đúng 09:00, exit 1 = cảnh báo mềm, KHÔNG có gì
chết). Đối chiếu 4 câu hỏi đặt trước:
* **Đủ mặt 5 nhà ✅** — Mistral lần đầu: probe 0.8s sống, lưu mốc 55
  model, chấm bộ đề (classify 1.00 / sentiment 0.88 / json 1.00).
* **Probe ladder: 10 sống / 0 chết / 1 ⏳** — chỉ OpenRouter
  `gpt-oss-20b:free` hết quota ngày (429 free tier, tự hồi), không phải
  model chết.
* **nemotron-ultra HẾT BÒ** — probe 2.1s (11/08 từng 127.3s = 161×
  median), mục "── Chậm bất thường ──" KHÔNG xuất hiện = không model nào
  chậm bất thường. → mục 5 HẠ NHIỆT (xem cập nhật ở mục 5).
* **Bảng điểm**: 8/10 nấc đo đủ, 6 nấc điểm tuyệt đối. Ba điểm để mắt
  T7 sau (22/08): (a) `gemini-3.5-flash` vẫn n/a — 22 ca hụt dù có nhịp
  riêng (quota free tối T7); (b) **Groq `gpt-oss-20b` sentiment 0.75 mà
  vai của nó chính là [1] sentiment** — tuần sau vẫn ≤0.75 thì mở lại
  "cảnh báo nấc yếu" + cân nhắc đổi nấc [1] (gemma-4-31b cùng vai đang
  1.00); (c) nemotron-ultra được xoay vòng chấm bù.
* Danh mục: Gemini +2 (có `gemini-3.7-flash` MỚI — cả bản OpenRouter);
  OpenRouter -1/+10 (model bị gỡ không nằm trong ladder). 3.7-flash là
  ứng viên nâng cấp tương lai — LUẬT CŨ GIỮ NGUYÊN: probe sống trên máy
  thật trước khi vào code.
Brief chiều 4 giọng không còn ❌ Groq đã xác nhận từ #217.

**3. ✅ ĐÓNG 18/08 — badge "Quy đổi đơn vị giá": không có ca oan nào, và
CHÍNH BADGE mới là thứ phải sửa.** User soi 5 chart (WSS/WTC/XPH/YBM/YEG)
17-18/08; điều tra 6 hướng + đối chứng phản biện cho kết quả:
* **Không thể quy đổi oan vì CHIA TÁCH** (chứng minh cấu trúc, không cần
  dữ liệu): guard chỉ bắn khi ratio ≥ **100×**; chia tách/thưởng LÀM GIẢM
  giá nên chỉ kéo ratio XUỐNG — tức chỉ gây BỎ SÓT, không thể gây oan.
  Muốn oan phải có giá TĂNG ≥100× trong một phiên, bất khả với biên
  ±7/10/15%. Thêm một lớp chặn: `_should_rollup_to_warehouse` chỉ cho mã
  3 CHỮ CÁI qua rollup nên CW/chứng chỉ quỹ/futures/index không bao giờ
  chạm `_normalize_units` (fix_units thì KHÔNG có lớp lọc này — bất đối
  xứng có thật, chưa gây hại). Ca oan "chia tách" ghi từ 11/08 ĐÓNG.
* ⚠️ **Nhưng CÒN MỘT đường oan lý thuyết — mẫu số không có sàn dưới.**
  `ref = ref[ref > 0]` (`vnstock_rollup.py:284-285`) chỉ lọc dương, không
  đòi giá hợp lý. Nếu LỊCH SỬ kho của một mã đã hỏng theo hướng nhỏ bất
  thường (ví dụ từng bị chia 1000× hai lần → 0.006 thay vì 6.0) thì bar
  MỚI ĐÚNG đơn vị cũng cho ratio ≥100 → bị chia oan, và sai số tự nuôi
  nhau. Khác hẳn ca chia tách: cần kho hỏng SẴN mới xảy ra. CHƯA quan sát
  thấy ca thật; KHÔNG vá vội (YAGNI + đụng đường ghi kho là rủi ro), vì
  ca này ĐÃ CÓ LƯỚI PHÁT HIỆN: chuỗi kho sẽ mang vách ~1000× và
  `check_unit_continuity` bắt đúng loại đó. Muốn chặn tận gốc thì thêm
  sàn `ref.median() > 0.01` (10 VND — dưới hẳn mã penny 300-900 VND vốn
  là lý do guard này tồn tại) + test; chỉ làm khi có ca thật.
* **Con số `ratio` KHÔNG phải thước đo đúng/sai**: `ratio = trung vị close
  bar mới (VND) / trung vị close YTD của chính mã (nghìn VND)`
  (`vnstock_rollup.py:291`, mẫu số là `_read_year` = file `year=<năm bar>`).
  Tức ratio ≈ 1000 × (giá hôm đó / trung vị YTD) — chỉ tròn 1000 khi giá
  bằng đúng trung vị năm. **YEG 764.1× chỉ nói YEG đang thấp hơn trung vị
  năm ~24%** (khớp chart giảm đều 12 → 7.6), KHÔNG phải dấu vết quy đổi
  sai. Claude từng nêu 764.1× là "đáng ngờ nhất" (17/08) — SAI, rút lại.
* **Badge nói quá ở 3 chỗ → ĐÃ VÁ**: (1) in ratio kèm mã như thể đó là độ
  tin cậy → bỏ; (2) 5 mã hiện ra là `fresh[-5:]` mà rollup duyệt
  `groupby("ticker")` = ALPHABET → luôn là ĐUÔI BẢNG CHỮ CÁI (đúng
  W-W-X-Y-Y), không phải 5 ca nặng nhất → nay in tổng số mã + ghi rõ "5 mã
  cuối theo vần"; (3) "50 lần" đúng bằng trần log `_UNIT_LOG_MAX=50` nên
  là SÀN chứ không phải số thật → nay in "≥50 (log đầy)". 6 test mới.
* **Việc soi mắt thay bằng lệnh**: `scripts/check_unit_continuity.py` —
  đọc CÙNG nguồn badge đọc, in bar cuối + bắt vách >30% và PHÂN LOẠI
  (~1000× = vết sót · ~2× = nghi chia tách · khác = thiếu phiên/lỗi), so
  bar cuối với `_live/quote_*.json`. Exit 0 sạch / 1 cần soi / 2 không đọc
  được kho. 13 test. Badge nay trỏ thẳng vào lệnh này.
* ✅ **CHỐT BẰNG DỮ LIỆU THẬT 18/08 — user chạy tool trên 50 mã**: KHÔNG
  mã nào có vách ~1000× (vết quy đổi sót). Cả 5 mã badge nêu đều sạch,
  **kể cả XPH: kho 15.00 nghìn ↔ live 14,900 (lệch 0.99×)** — XPH giao
  dịch 14.0-16.5 suốt tháng 7-8, chưa từng ở vùng 10. MỤC 6 ĐÓNG HOÀN
  TOÀN: guard quy đổi chạy đúng.
* ⚠️ **BÀI HỌC ĐẮT — "soi chart bằng mắt" suýt đẻ ra kết luận sai, và
  Claude đã dính**: chart trong ảnh XPH KHÔNG phải của XPH (chuỗi
  ~9.5-10.2 đúng dải của WTC, mã user xem TRƯỚC đó). Cùng hiện tượng ở
  ảnh WTC (hiện chart WSS). Nguyên nhân: khi đổi mã, quote strip +
  volume profile render TRƯỚC nên đã là mã mới, còn chart render SAU
  (phía sau 2 lời gọi mạng VCI chặn của `_today_bar_writer`) vẫn là mã
  cũ — cửa sổ lệch pha vài giây, đủ để chụp ảnh và suy luận sai. Claude
  đã dựng nguyên một giả thuyết "3 phiên trần UPCOM" từ dữ liệu của mã
  khác. ĐỀ XUẤT CHƯA LÀM (chờ user quyết): chart hiện placeholder
  "⏳ đang tải {mã}" khi mã đang xem ≠ mã chart vừa vẽ, thay vì để
  nguyên khung cũ. Trước mắt: ĐỌC NHÃN TRONG CHART trước khi kết luận.
* **Tool tự bắt lỗi của chính nó ngay lần chạy thật đầu**: 8/50 mã bị
  gắn cờ oan vì "hai bar liền nhau" ≠ "hai phiên liền nhau" — mã kém
  thanh khoản có bar cách nhau HÀNG THÁNG (VTS: 2026-03-10 → 2026-08-07,
  150 ngày, rơi 40% = tích luỹ nhiều phiên chứ không phải vách). Đã vá:
  thêm điều kiện `gap_days ≤ 4` mới kết tội "vượt biên độ sàn"; vách
  ~1000× thì luôn nghi vấn bất kể cách bao lâu (không quãng thời gian
  nào biến giá thành sai đơn vị); vách qua quãng nghỉ in ℹ để đọc chứ
  không tính suspect. +5 test.
* ⚠️ **VVS — ca thật DUY NHẤT còn lại, đã xác nhận KỀ PHIÊN**: user chạy
  `--ticker VVS` sau bản vá gap: `2026-06-15: 112.50 → 71.21 (−36.7%)`,
  hai bar 12/06 → 15/06 (thứ Sáu → thứ Hai) nên KHÔNG phải gap artifact.
  Hệ số giá **1.580×** — bất khả với biên ±15%.
  **KHÔNG PHẢI sự kiện quyền — giả thuyết "thưởng 100:58" của Claude SAI,
  rút lại.** Bằng chứng loại trừ (user chạy `vnstock_div_check --tickers
  VVS --refresh -v` 18/08): VVS có 3 sự kiện trong 750 ngày → **2 đã điều
  chỉnh · 0 GAP THÔ · 1 chưa kết luận** (2026-03-08 [bonus] kỳ vọng
  −97.68% — chính div_check gắn cờ "nghi sai đơn vị/tỷ lệ NGUỒN"). Nếu có
  sự kiện quyền ở 15/06 mà kho chưa điều chỉnh thì div_check BẮT BUỘC
  phải báo GAP THÔ ở đúng ngày đó; nó báo 0 → **không có sự kiện nào ở
  15/06**. Hai tool bổ trợ nhau chứ không mâu thuẫn: div_check chỉ soi
  TẠI ngày sự kiện, nên vách nằm ngoài ngày sự kiện thì nó không bao giờ
  nhìn tới — đó đúng là vùng mù mà `check_unit_continuity` vừa lấp.
  **Nghi phạm còn lại (có bằng chứng cấu trúc): kho trộn HAI CƠ SỞ ĐIỀU
  CHỈNH.** Vendor rebase toàn chuỗi sau một sự kiện, mà sync incremental
  chỉ nối bar MỚI (đã rebase) lên lịch sử CŨ (chưa rebase) → chuỗi gãy
  đúng tại ngày đổi cơ sở, không trùng ngày GDKHQ nào. Khớp cả với chi
  tiết 71.21 không phải bội số bước giá 100 VND (giá >50k trên sàn niêm
  yết) — tức là số ĐÃ QUA PHÉP TÍNH, không phải giá khớp lệnh thô.
  ⚠️ **BẪY: `--force` KHÔNG refetch lịch sử** (Claude hiểu sai 18/08, user
  chạy ra "Số ngày mới: 1"). `--force` chỉ bỏ qua kiểm tra cuối tuần
  (`skip_weekends=not args.force`); `update_ticker` LUÔN fetch từ
  `_get_last_date` — **repo KHÔNG có đường nạp lại lịch sử một mã**. Phép
  thử đó vì thế vô hiệu, chưa kết luận được gì.
  → **Phép thử đúng, chỉ ĐỌC: `scripts/probe_price_basis.py`** (mới
  18/08) — fetch nguồn qua đúng `_fetch_prices` của updater (cùng chuẩn
  hoá đơn vị) rồi so tỉ lệ kho/nguồn HAI BÊN ngày vách:
  `python scripts/probe_price_basis.py --ticker VVS --break-date 2026-06-15`
  · tỉ lệ ĐỔI BẬC tại ngày vách ⇒ `warehouse_basis` (nguồn liền mạch, kho
    giữ cơ sở cũ) → chữa bằng ghi đè lịch sử;
  · tỉ lệ NHƯ NHAU hai bên ⇒ `source_error` (nguồn cũng gãy) → ghi đè vô
    ích, chữa ở nguồn/cách ly.
  Hai chẩn đoán chữa NGƯỢC NHAU nên phải phân định TRƯỚC khi sửa. Hàm
  phán `basis_report` là hàm thuần + 6 test (fetch cần mạng nên tách ra).
  ✅ **CHỐT 18/08 — `warehouse_basis`, bằng chứng không thể rõ hơn**: user
  chạy probe, tỉ lệ kho/nguồn = **1.6543× cho MỌI bar trước 15/06** (43
  bar, sai số ±0.0002) rồi **1.0000× cho MỌI bar từ 15/06**. Nguồn liền
  mạch, kho gãy ⇒ VVS có sự kiện quyền ex-date 15/06 hệ số ~1.654 (thưởng
  ~65%), nguồn rebase CẢ CHUỖI, còn sync chỉ nối bar mới lên lịch sử cũ.
  Diễn giải phụ: giá "thật" phiên 12/06 theo cơ sở mới là 112.50/1.6543 =
  68.01, nên phiên 15/06 đóng 71.21 là **+4.7% bình thường** — vách 36.7%
  hoàn toàn là ảo ảnh do trộn hai cơ sở.

  🔴 **ĐÂY LÀ LỖI HỆ THỐNG, KHÔNG PHẢI CA CÁ BIỆT** — mọi mã có sự kiện
  quyền lớn (chia tách/thưởng) đều dính cùng cơ chế, vì repo KHÔNG có
  đường nạp lại lịch sử và đường ghi CHÍNH không có lưới đối chiếu.
  Vì sao mục 4d (28/30 VN30, 64 sự kiện, 0 gap thô) không bắt được: sự
  kiện VN30 trong cửa sổ đó chủ yếu là CỔ TỨC TIỀN MẶT — hệ số điều chỉnh
  1.01-1.05, chìm dưới nhiễu (đúng 19 ca "chìm nhiễu" đã ghi). Rủi ro dồn
  vào đúng nhóm hệ số LỚN, tức nơi sai số tàn phá nhất. Kết luận 4d không
  sai trong phạm vi của nó, nhưng KHÔNG suy rộng ra được.
  → **Đã thêm `check_unit_continuity --all`** (quét toàn kho, chỉ in mã
  nghi vấn) để đo độ rộng thiệt hại; vách "kề phiên" nay ghi thẳng "nghi
  KHO LỆCH CƠ SỞ" + trỏ sang `probe_price_basis` thay vì bỏ lửng ở chữ
  "dữ liệu lỗi". CHƯA có đường CHỮA (ghi đè lịch sử) — chờ user quyết,
  vì đó là ghi vào kho.
  ⚠️ **Lần quét `--all` ĐẦU TIÊN gắn cờ 1.902/3.125 mã — LỖI CỦA CÔNG CỤ,
  không phải của kho** (user chạy 18/08). Hai nguyên nhân, đã vá cả hai:
  (1) quét cả CHỨNG QUYỀN (CFPT2528…, hàng nghìn mã), TRÁI PHIẾU
  (CTG121030, MBB125008), phái sinh HNX (41I1G4000) và cả VNINDEX — những
  thứ KHÔNG có biên độ ±15% nên nhảy 30-50%/phiên là bình thường; nay lọc
  bằng chính `vnstock_anomaly._is_stock` (bất đối xứng đã ghi nhận từ
  trước: anomaly có `stocks_only`, fix_units/tool này thì không).
  (2) quét cả 20 năm lịch sử nên nhiễu 2006-2013 nhấn chìm tín hiệu mới;
  nay `--all` mặc định cắt **365 ngày** (`--since N`, 0 = toàn bộ; soi mã
  lẻ vẫn xem toàn lịch sử). Danh sách in ra cũng cắt còn 40 mã + "(+N)".
  +3 test. **Bài học lặp lại lần thứ ba trong ngày**: mỗi lần công cụ gặp
  dữ liệu THẬT là lộ một giả định ngầm sai (bar liền nhau ≠ phiên liền
  nhau · mọi mã ≠ cổ phiếu · lịch sử dài ≠ lịch sử liên quan). Đừng tin
  con số quét lần đầu; luôn soi vài dòng mẫu trước khi kết luận diện rộng.
  → **Quét lần 2 (sau lọc): 149/1.579 mã cổ phiếu (9,4%) có vách trong 365
  ngày.** Con số này đã có nghĩa. Nhưng 149 dòng TÊN thì vẫn không dùng
  được: probe từng mã là 149 lần gọi mạng, mà phần lớn là penny không ai
  giao dịch. Nên `--all` nay in **một dòng/mã kèm ngày vách + HỆ SỐ + GTGD
  TB20, XẾP THEO THANH KHOẢN giảm dần** — câu hỏi thật không phải "mã nào
  có vách" mà "mã nào đủ thanh khoản để lọt universe chiến lược
  (`min_avg_volume=100.000`) và làm hỏng tính toán". Đọc từ trên xuống,
  gặp GTGD nhỏ là dừng. Hệ số in kèm cũng giúp nhận dạng nhanh: hệ số
  "đẹp" (1.65, 2.00) → gần chắc là rebase; hệ số lộn xộn → nguyên nhân
  khác. +1 test canh thứ tự xếp.

  🔴🔴 **BẢNG QUÉT 18/08 — THIỆT HẠI CHẠM VN30, KHÔNG CÒN LÀ CHUYỆN PENNY.**
  Nhóm đầu (GTGD/phiên): **VHM 596 tỷ · vách 03/08 148.10→74.00 hệ số
  2.001×** · **GEX 311 tỷ · 28/04 hệ số 1.480×** · **PNJ 260 tỷ · 17/04
  hệ số 1.472×** · GEE 81 tỷ (1.730×) · PVD 50 tỷ (1.632×) · PET 12.7 tỷ
  (1.439×, CÓ sự kiện quyền khớp) · F88 11.6 tỷ (2.062×) · VVS 10.6 tỷ
  (1.580×) · KSV 4.7 tỷ · TOS 2.3 tỷ · L40 1.7 tỷ. **VHM và PNJ nằm
  trong VN30** — tức trong brief, screener, chart, chiến lược. Hệ số
  2.001× của VHM là chữ ký chia tách/thưởng 100%.
  ⇒ **Kết luận 4d "kho nhất quán điều chỉnh, 0 gap thô" KHÔNG còn đứng
  cho VN30**: div_check chỉ soi TẠI ngày sự kiện có trong cache, mà cache
  thiếu đúng những sự kiện này (ca PET là ngoại lệ — có sự kiện khớp).
  Vùng mù đó chính là chỗ `check_unit_continuity` lấp.
  ⇒ Hệ quả PHẢI GIẢ ĐỊNH cho tới khi chữa: mọi chỉ báo/backtest/vốn hoá
  của VHM trước 03/08, PNJ trước 17/04, GEX trước 28/04 đều SAI HỆ SỐ.
  Chiến lược #32 (đang phát rec) chạy trên universe 3.125 mã → có thể đã
  học trên chuỗi lệch. **Chưa kết luận vội** — phải probe từng mã trước.
  ⇒ `probe_price_basis` nay nhận NHIỀU `--ticker` và TỰ TÌM ngày vách
  (dùng lại `find_jumps`, một nơi định nghĩa "vách"), nên phân định cả
  nhóm đầu bằng một lệnh. +3 test.
  ⇒ Ghi nhận phụ: 4 mã BII/HSI/LCS/VLF cùng vách **1000×** ngày
  **2026-04-14** = VẾT QUY ĐỔI SÓT THẬT (penny 300-600 VND ghi thẳng số
  thô). Lọt cả hai lưới: `fix_units` đòi close > 1000 (300 không đủ),
  `_normalize_units` chỉ áp cho bar rollup/WSS chứ không áp cho đường
  updater. GTGD ~0 nên vô hại, nhưng là bằng chứng lỗ hổng thứ ba.

  ✅ **PROBE 5 MÃ ĐẦU BẢNG — CẢ 5 ĐỀU `warehouse_basis`, tỉ lệ sạch tuyệt
  đối** (user chạy 18/08): VHM **2.0000×** · PNJ **1.4999×** · GEX 1.4498×
  · GEE 1.7593× (sau vách còn 1.0052× — dư 0.5%, nghi cổ tức tiền mặt
  nguồn có mà kho không, chưa đụng) · PVD 1.6692×. Không bar nào lệch khỏi
  hệ số ⇒ hết đường nghi ngờ: lịch sử kho giữ cơ sở cũ, nguồn liền mạch.
  Suy ra thẳng: **MA200/RSI/MACD/backtest/vốn hoá của VHM trước 03/08 sai
  gấp ĐÔI**, PNJ trước 17/04 sai 1.5×; VHM vốn hoá lớn nên còn kéo lệch cả
  tổng ngành Bất động sản trong bảng screener.

  🔧 **ĐÃ DỰNG ĐƯỜNG CHỮA: `scripts/rebase_ticker_history.py`** (CHƯA
  CHẠY trên kho thật — quyết định ghi kho là của user). Thiết kế ưu tiên
  ĐÚNG hơn TIỆN: ngày nào NGUỒN CÓ thì lấy thẳng giá nguồn (không nhân
  chia, chính xác tuyệt đối), ngày nào cũ hơn độ phủ nguồn thì nhân hệ số
  ĐO ĐƯỢC — giữ nguyên độ sâu 20 năm của kho (backtest tầng vị thế cần
  730 ngày, ghi đè cụt bằng độ phủ nguồn là mất dữ liệu). Hệ số KHỐI
  LƯỢNG đo riêng (chia tách đổi cả số cổ phiếu); không đo đủ chồng lấn thì
  để yên chứ không đoán. Bốn cửa an toàn: **mặc định CHẠY THỬ** (phải
  `--apply` mới ghi) · **từ chối** nếu probe không phán `warehouse_basis`
  · **sao lưu** nguyên thư mục mã vào `_meta/backup_rebase/<mã>_<lúc>` ·
  ghi **nguyên tử** từng file rồi **TỰ KIỂM** (đọc lại; còn vách thì báo
  đỏ + gợi ý mã bị rebase nhiều lần thì chạy lại). 7 test soi đúng phần
  an toàn: chạy thử không đụng byte nào · từ chối khi `source_error` ·
  backup giữ bản gốc · ngưỡng chồng lấn tối thiểu cho hệ số khối lượng.
  ✅ **Chạy thử VHM trên máy thật 18/08 — kịch bản TỐT NHẤT**: nguồn phủ
  từ **2011-11-10**, trùng đúng ngày đầu của kho (3.476 bar) ⇒ **3.464/3.464
  bar lấy thẳng giá nguồn, 0 bar phải nhân hệ số ước lượng**; không mất một
  ngày lịch sử nào.
  ⚠️ **Nhưng lộ vấn đề KHỐI LƯỢNG, phát hiện đúng lúc chạy thử**: hệ số
  volume nguồn/kho = **1.0000×** ⇒ nguồn CHỈ điều chỉnh GIÁ. Chia tách 1:1
  làm số cổ phiếu gấp đôi, nên nếu chữa giá (÷2) mà giữ nguyên khối lượng
  thì **GTGD lịch sử còn một nửa** — mà GTGD chính là thứ screener và
  `min_avg_volume=100.000` của `emit_recommendations` dùng để lọc thanh
  khoản. Chữa một lỗi mà đẻ lỗi khác. Đã bổ sung: đo **bậc nhảy khối lượng
  tại vách** (trung vị 20 bar sau / 20 bar trước) rồi quyết —
  `--volume auto` (mặc định): nhân khối lượng lịch sử theo hệ số giá KHI
  nguồn không điều chỉnh volume (≈1.0×) VÀ volume gãy đúng bậc đó ·
  `adjust`: luôn nhân · `source`: giữ đúng số nguồn (khi muốn kho khớp
  nguồn tuyệt đối để đối chiếu). +4 test. In rõ quyết định + lý do ra màn
  hình trước khi ghi.
  ✅✅ **VHM ĐÃ CHỮA XONG 18/08 20:37 — ca đầu tiên, trọn quy trình.**
  Bậc nhảy khối lượng đo được **1.95×** (≈ hệ số giá 2.0, lệch 2.5% là dao
  động trung vị bình thường) ⇒ `auto` nhân khối lượng ×2.0000 — bằng chứng
  thực nghiệm khớp lý thuyết chia tách 1:1. Sao lưu
  `_meta/backup_rebase/VHM_20260818-203753`, ghi nguyên tử 16 file, TỰ KIỂM
  báo "chuỗi đã liền". Sau khi chữa: giá ÷2 và khối lượng ×2 nên **GTGD
  lịch sử giữ nguyên** — đúng bản chất chia tách, không đẻ lỗi mới.
  ✅ **Soi TOÀN LỊCH SỬ VHM sau khi chữa: sạch trong mọi phạm vi có ý
  nghĩa.** Còn đúng 2 dòng, cả hai đều KHÔNG phải lỗi kho:
  * `ℹ 2018-05-17: 8.41 → 30.99, cách 308 ngày` = ngày **Vinhomes niêm
    yết**. Tức dữ liệu VHM trước mốc đó KHÔNG PHẢI Vinhomes mà là mã cũ
    từng dùng ticker VHM (ngừng giao dịch 308 ngày rồi ticker được cấp
    lại). Chữ ký TICKER TÁI SỬ DỤNG: quãng nghỉ dài + nhảy lớn. Có thể
    còn ở mã khác — ghi nhận, chưa quét.
  * `⚠ 2015-06-10 +40%` nằm trong phần lịch sử "tiền Vinhomes" đó.
  **Nguyên tắc rút ra**: sau khi rebase, kho = nguồn 100%, nên MỌI VÁCH
  CÒN LẠI ĐỀU LÀ VÁCH CỦA NGUỒN — probe sẽ ra `source_error`, công cụ
  rebase không chữa được và cũng không nên chữa. Vách 2015 nằm ngoài mọi
  lookback thực tế (backtest dài nhất repo là 730 ngày) → BỎ QUA.
  ⏭ **VIỆC KẾ TIẾP (chờ user)**: chạy thử VHM → soi số → `--apply` → chạy
  lại `--all` xem 149 rút còn bao nhiêu. Sau đó mới tính chuyện chặn TÁI
  PHÁT (lưới đối chiếu ở đường ghi CHÍNH — hiện chỉ làn fallback có).
  ⚠️ **Lỗ hổng lộ ra từ ca này: lưới đối chiếu chỉ có ở làn FALLBACK.**
  `reconcile_fallback_df` (từ chối data lệch >8% so với kho) chỉ được gọi
  trong nhánh fallback (`vnstock_updater.py:441`); **đường VCI CHÍNH ghi
  thẳng vào kho không qua đối chiếu nào**. Vendor đổi cơ sở điều chỉnh là
  đi lọt cửa chính. Vá thì phải đụng đường ghi kho (rủi ro nhất repo) và
  phải miễn trừ đúng các ngày GDKHQ hợp lệ — NÊU RA ĐỂ USER QUYẾT, không
  tự làm.
  Ảnh hưởng thực tế: VVS lọt bộ lọc `min_avg_volume=100.000` của
  `emit_recommendations` (KL ~40k-500k/phiên, giá ~100 nghìn) nên chuỗi
  lệch 58% này CÓ THỂ vào tính toán chiến lược. Mục 4d chốt "kho nhất
  quán điều chỉnh" dựa trên 28/30 mã VN30 — VVS ngoài rổ đó, nên kết luận
  cũ KHÔNG sai, nhưng độ phủ ngoài VN30 nay biết là CHƯA được kiểm.
* **Tool nay tự trả lời "VÌ SAO", không chỉ "có vách"** (nối tiếp ca VVS):
  mỗi vách nghi vấn được đối chiếu với kho sự kiện quyền có sẵn
  (`vnstock_adjust.load_events`, cache 3 nguồn từ 14/08), cửa sổ ±3 ngày
  (ngày chốt quyền vs ngày GDKHQ lệch nhau). Trùng → đổi thông điệp thành
  "TRÙNG SỰ KIỆN QUYỀN (loại, GDKHQ ngày) → kho CHƯA back-adjust" kèm
  **hệ số giá quan sát vs ratio sự kiện** để đối chiếu tay, và in nguyên
  văn mô tả. Không trùng → GIỮ NGUYÊN "dữ liệu lỗi", không bịa nguyên
  nhân. Vách qua quãng nghỉ thì không đi tra sự kiện (không phải nghi vấn
  thì đừng gán tội). +5 test. Đây là bước biến "cần soi tay" thành "đã
  biết chữa ở tầng nào".
* ~~Còn treo — XPH~~ *(giả thuyết sai, giữ lại để không ai đi lại đường
  cũ)*: live 15,600 VND vs chart ~10.2 nghìn (lệch ~1.5×).
  KHÔNG phải lỗi đơn vị: mọi hệ số trong repo là 1000× và
  `normalize_live_price` chỉ kích hoạt khi >100×/<0.01× nên không đường
  code nào đẻ ra 1.5×. Hai giả thuyết còn lại, cần dữ liệu máy thật để
  chốt: (a) kho lỡ phiên — số học ủng hộ mạnh: bar WSS lúc quy đổi ≈10.16
  nghìn, mà 10,160 × 1.15³ = 15,450 ≈ 15,600 = **3 phiên trần UPCOM**;
  (b) file `_live/quote_XPH.json` thiu — `load_live_quote` KHÔNG kiểm tra
  tuổi file và strip chỉ in HH:MM:SS (không có ngày), mã UPCOM không khớp
  lệnh thì file không được ghi đè. → user chạy
  `python scripts/check_unit_continuity.py --bars 20` trên máy thật.
* **WTC**: ảnh chụp lúc trang đang rerun (mờ), chart còn khung của mã
  trước. Soi code: không state nào giữ dữ liệu mã cũ (cache theo key
  ticker, iframe srcdoc nhúng tên mã) → là khung cũ chưa bị thay, cửa sổ
  dài vì giữa quote strip và render_chart còn 2 lời gọi mạng VCI chặn.
  Phân định dứt điểm nếu tái diễn: chờ trang hết mờ rồi đọc NHÃN TRONG
  chart — vẫn ghi mã cũ mới là stale thật.

## 🟡 CODE CÒN TREO — không gấp

**4. MEDIUM/LOW của audit 06/08** — đang dọn theo thứ tự ③→①→④→②:
* ✅ **③ test replica XONG 12/08** (entry 12/08 (b)+(c)) — `test_wss.py` và
  `test_dashboard.py` hết sạch replica; 6 module thuần tách ra; +45 test cho
  các nhánh trắng lộ ra (RSI loss=0, VWAP intraday, cell_color, bảng ngành)
* ✅ **① ghi nguyên tử XONG 12/08** (entry 12/08) — warehouse xoá-rồi-ghi +
  meta + 5 file state; có lưới `_MUST_BE_ATOMIC` chặn tái phát
* ✅ **④ tách file quá lớn XONG 12/08** (entry 12/08 (d)+(e)+(f)):
  `vnstock_brief.py` 6.807 → **4.045**, hệ guard 2.646 → **244 + 4 module chủ
  đề**; `dashboard/market_tab.py` 2.567 → **1.082**, panel brief 1.194 → **42
  + 5 panel con**; nhận định thị trường ra `market_commentary.py`.
  Không còn file nào do đợt tách sinh ra vượt 800 dòng.
  Đã soi `build_prompt`/`collect_context` (entry 12/08 (g)): KHÔNG chia hàm
  (churn cao, lợi ích chỉ là con số dòng) nhưng vá 2 lỗ thật tìm được lúc
  quét — khối prompt biến mất âm thầm, và 13 nguồn nuốt lỗi im lặng
* **② hiệu năng — ✅ MÁY ĐO GẮN XONG 14/08, chờ SỐ từ đêm máy bàn đầu tiên.**
  Nghi vấn gốc: warehouse bị quét ~14 lần/đêm. `cmd_all` nay tự bấm giờ
  từng bước → sáng sau xem:
  `Select-String -Path run_daily.log -Pattern "⏱"`.
  LUẬT QUYẾT (chốt trước cho khỏi cãi nhau với chính mình sau): TỔNG < ~30
  phút VÀ không bước nào chiếm quá nửa vô lý → **BỎ ②** đúng dự đoán
  ("18:00 không ai ngồi đợi"); một bước nghẽn rõ (audit/validate 20+ phút
  chẳng hạn) → mổ ĐÚNG bước đó, không tối ưu cả dàn.

**4d. ✅ ĐÓNG 14/08 — kho giá NHẤT QUÁN điều chỉnh cổ tức. VIC hoá ra là
bằng chứng mạnh nhất.**
Hai lần chạy máy thật (13-14/08): 29 sự kiện / 17 mã đều "đã điều chỉnh",
0 gap thô — backtest giữ lệnh dài đứng trên nền sạch. Ca VIC "chưa kết
luận" khi soi `-v` hoá ra là LỖI TRẦN của chính checker (entry 14/08 (m)):
bonus 1:1 kỳ vọng −49.8% bị trần-40%-của-cash bịt oan, trong khi quan sát
−0.14% nghĩa là cú halving VÔ HÌNH trong chuỗi = bằng chứng back-adjust
mạnh nhất cả đợt. Đã sửa trần theo LOẠI (cash 40% / split-bonus 90%) + 5
test; user merge + chạy lại NGAY 14/08: **ĐÚNG DỰ ĐOÁN — VIC ✅, chốt sổ
30 sự kiện / 18 mã sạch, 0 gap thô, 0 chưa kết luận** (exit 0).
Giới hạn ghi nhận trung thực: 12 mã không có sự kiện để chấm — 11 mã nguồn
VCI phủ mỏng (VNM/SAB/TCB/VPB/MSN/MWG/PLX/STB… — user đã refresh 16:13
13/08 TRƯỚC lần chạy đầu nên không phải cache cũ; refresh nữa vô ích) +
GVR fetch fail im lặng. Rủi ro thấp: mọi mã đi CHUNG một đường sync/kho
và mọi ca đo được đều sạch. Muốn đóng kín 100% cần NGUỒN SỰ KIỆN THỨ HAI
— ✅ ĐÃ LÀM 14/08 (entry (n)): `refresh_events` đổi first-wins → GỘP 3
nguồn + khử trùng-gần. **User chạy phủ nốt NGAY 14/08**: refresh 1.723 mã
(fail=0) → div_check 29 → **37 sự kiện, vẫn 0 gap thô** — TCB thoát vùng
mù (0→1 ✅), FPT/HPG/SHB/SSB/VIB/VJC dày thêm. Kết luận 4d càng vững.
**CHỐT SỔ HOÀN TOÀN 14/08 sau 4 vòng đo** (28→30→37→**64 sự kiện**, entry
(l)-(o)): độ phủ **28/30 mã VN30**, 64 sự kiện đủ cả tiền mặt lẫn chia
thưởng đều "đã điều chỉnh", **0 gap thô xuyên suốt**; 19 ca "chìm nhiễu"
đúng thiết kế không phán bừa; STB/MSN trắng THẬT (không chia cổ tức giai
đoạn này — thực tế doanh nghiệp). KHÔNG CÒN VIỆC GÌ Ở MỤC NÀY. Tool ở lại
làm lính gác: nghi ngờ kho lúc nào chạy
`python vnstock_div_check.py --refresh -v` lúc đó.

**4e. Tầng B — danh mục xoay vòng tháng** (entry 13/08 (d)): để sau, chỉ làm
khi tầng A chạy ổn và user muốn đầu tư backtester cấp danh mục (~3-5 buổi).
*(14/08 user gọi làm luôn cả hàng chờ — GIỮ CỔNG có lý do, entry (n):
production chưa train tầng vị thế đêm nào, chưa có chiến lược đạt kiểm
định để xoay vòng. Đủ điều kiện → nêu ý tưởng thiết kế trước rồi mới code.)*

## 🟠 QUAN SÁT RỒI QUYẾT

**4c. ✅ ĐÃ CHỐT 13/08: NÂNG sàn kiểm định 10 → 30 lệnh** (entry 13/08 (g)).
Hệ quả tức thì: #32 (19 lệnh) bị hạ verdict NGAY tại điểm đọc — brief kế tiếp
KHÔNG còn rec `[vị thế ~20 phiên]` nữa; panel hiện "🎲 mẫu mỏng (n=19)".
Mở lại khi có backtest ≥ 30 lệnh đạt chuẩn (tune/revise đêm sẽ tự tìm).
→ **✅ ĐIỀU KIỆN MỞ LẠI ĐÃ XẢY RA 17/08**: #32 đạt p=0.012 với n=94 ≥ 30,
phát 5 rec tầng vị thế (entry 17/08 bổ sung lần 5) — sàn 30 hoạt động đúng
thiết kế: chặn lúc mỏng, tự mở khi đủ bằng chứng. Việc còn lại: đọc brief
#217 soi rec hiện đúng nhãn `[vị thế ~20 phiên]`, và liếc panel Chiến lược
xem tham số tune (expectancy 0.197→2.47 sau 2 đêm — hợp lệ nhưng đáng soi).

**4b. Mã của nhóm tuỳ biến ĐẾM HAI LẦN — user chốt 13/08: TẠM GIỮ NGUYÊN.**

> ⚠️ **ĐỪNG XOÁ MỤC NÀY.** Đây là nợ ĐÃ BIẾT và CHẤP NHẬN CÓ THỜI HẠN, không
> phải việc đã xong. User chốt "tạm thời giữ nguyên, ghi lại để không quên".
> Giữ ở đây cho tới khi có quyết định cuối.

Lộ ra khi verify bản vá drill-down 13/08 (entry 12/08 (b)):

* Bảng ngành: **Ngân hàng 26 mã** — vì EIB đã được chuyển sang Họ M
* Bấm vào Ngân hàng: **"27 mã"** — vì drill-down lọc theo ngành GỐC

Lệch đúng 1 = EIB. Không riêng Ngân hàng: 11 mã của hai nhóm đều có ngành gốc,
nên Bất động sản (row 102) bấm vào sẽ ra 105, Chứng khoán lệch 1 vì VIX…

Hệ quả THẬT chứ không chỉ khó nhìn: **cộng bảng chi tiết không ra dòng tổng** —
vốn hoá/GTGD/NN ở dòng "Ngân hàng" đã trừ EIB, bảng chi tiết thì cộng cả vào.

Hai hướng đã cân:
1. **Cho khớp dòng tổng** — drill-down loại mã đã thuộc nhóm tuỳ biến (Ngân
   hàng ra đúng 26, EIB chỉ ở Họ M). Số hai chỗ luôn khớp, cộng ra đúng.
   *(Claude nghiêng hướng này: số tự mâu thuẫn thì lần sau không biết tin số nào.)*
2. ✅ **Giữ nguyên — ĐANG DÙNG.** Coi nhóm tuỳ biến là LỚP PHỦ: EIB vừa là ngân
   hàng vừa là Họ M. Nhìn ngành nào cũng đủ mã, đổi lại sống chung với 26 ≠ 27.

**Khi nào lôi ra làm lại** — một trong các dấu hiệu sau:
* thêm họ mới vào registry (càng nhiều mã bị đếm đôi, lệch càng khó bỏ qua);
* có nhu cầu CỘNG bảng chi tiết ra đúng dòng tổng (báo cáo, xuất CSV đối soát);
* thấy mình lưỡng lự "tin số nào" khi đọc hai chỗ.

Sửa thì chỉ đụng `vnstock_sectors.rows_for_sector` + test, khoảng 15 phút.
Docstring của hàm đó cũng đã ghi lưu ý này (chỗ người sửa sau vấp vào đầu tiên).

**KHÔNG ảnh hưởng**: brief, dữ liệu kho, phép tính trong pipeline — đây thuần
là chuyện hai con số hiển thị trên dashboard không khớp nhau.

**9. ✅ ĐÓNG 15/08 — nhãn KỲ số khối ngoại: vá guard có sẵn + thêm nhánh
phạm-vi-ngành** (entry 15/08 (s)). Hoá ra `enforce_nn_window_label` đã
nằm trong chuỗi từ 12/08 và ctx #212 đủ dữ liệu — trượt CHỈ vì regex
không dung cặp `**` markdown giữa số và "tuần". Vá khe `[\s*]*` (trả lại
dấu sao cho bold khỏi lệch) + nhánh 3 mới: số tuần của MỘT ngành nói như
toàn thị trường → chèn tên ngành sau "ròng"; không phân xử được (trùng
số 1D, ≥2 ngành trùng, đã nêu tên) thì không đụng. Test dùng nguyên văn
2 câu lỗi #212. ✅ **VERIFY XONG 17/08 qua brief #217**: NN 1D ghi rõ
"trong phiên" khớp doctor; mọi số tuần kèm nhãn "1 tuần" + tên ngành —
hết tự mâu thuẫn (entry 17/08 bổ sung lần 6). MỤC NÀY ĐÓNG.

**10. ✅ ĐÓNG 15/08 — user chốt phương án (b): Telegram ẨN lệnh có chiến
lược nguồn trượt kiểm định, dashboard giữ đủ** (entry 15/08 (s)). Luật ẩn
tách ra `split_recs_by_validation` dùng CHUNG brief + Telegram (ẩn ⇔
known-và-trượt; unknown vẫn hiện; rec xử theo kiểm định của CHÍNH chiến
lược nguồn). `_open_recs_block` thay lệnh ẩn bằng dòng đếm trỏ về
dashboard; caveat BUY-GIẢM chỉ xét lệnh đang hiện; 2 net parity canh ai
inline lại luật. Emit đêm vẫn mở lệnh cho accuracy tracking (không chọn
(c) — giữ dữ liệu để chiến lược tự chứng minh). ✅ **VERIFY XONG 17/08
qua brief #217, đủ CẢ HAI chiều**: tầng ngắn trượt gom "6 lệnh ẩn — xem
trong dashboard", 4 lệnh #32 (ĐẠT p=0.012) hiện đúng "ngày 0/20" (entry
17/08 bổ sung lần 5+6). MỤC NÀY ĐÓNG — còn cái đuôi đếm lệch 12 vs 10
ghi ở bổ sung lần 6, soi dashboard khi rảnh.

**5. Độ trễ OpenRouter — ✅ HẠ NHIỆT 18/08 (hết leo thang).** Báo cáo T7
15/08: nemotron-ultra probe **2.1s** (11/08 từng 127.3s = 161× median),
nemotron-super 1.4s, mục "Chậm bất thường" trống. KHÔNG cần probe ứng
viên thay nữa. Đóng hẳn khi báo cáo T7 22/08 chấm bộ đề ultra (đang xoay
vòng) mà latency vẫn thường. Nếu tái bò thì lệnh probe ứng viên vẫn đây:
```powershell
python scripts/probe_models.py --slug "OpenRouter=nvidia/nemotron-3.5-lightning:free"
```
(slug CHƯA probe thì CHƯA được vào code — luật CLAUDE.md.)

**6. OpenRouter nạp $10** — quan sát LẠI TỪ ĐẦU từ lưu lượng THẬT (đợt
rate-limit 08/08 là do eval đốt, đã vá `EVAL_BUDGET`). Nay ledger có "lỗi
cuối" nên phân biệt được 429 thật/giả dễ hơn.

**7. Chất lượng brief 4 giọng** — thay cho "A/B Gemini vs Groq" (đã chết,
ghế Groq tắt 11/08): so auto-score / Lịch sử brief vài phiên giữa Gemini ·
Cerebras · OpenRouter · Mistral (mốc 11/08: 0.830 / 0.834 / 0.862 / 0.836).
Kèm: Cerebras `gpt-oss-120b` digest chập chờn · Gemini flash 503 đêm VN là
bình thường, cascade tự đỡ.

**8. Nâng thư viện data** — vnstock 4.0.4→**4.0.6**, vnai 2.4.8→**2.5.7**,
vnii 0.2.4→0.2.5 *(số mới theo warning trong log 17/08 của user)*. CHƯA
nâng. Nâng thì `run.py doctor --net` + full suite ngay sau; KHÔNG nâng
sát giờ pipeline chạy.

## 🔧 NẾP GIT — bẫy đã vấp 2 lần

User làm việc trên `main` cục bộ, Claude push lên nhánh feature → `git pull`
báo **"Already up to date"** DÙ vừa tải commit mới về. Lấy code mới phải dùng
`git fetch origin <nhánh> && git merge origin/<nhánh>`. Nghi máy chạy code cũ
→ `git log --oneline -1` đối chiếu commit cuối Claude báo.
