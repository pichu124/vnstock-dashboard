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

> ⚠️ **06/10 (U17): 3 ảnh chụp 08·09·10 đều GIẢ** (3 mã AAA/BBB/CCC — test
> `test_fundamental_cf` trước `4ad92f7` chụp vào kho THẬT, và vì "bản đầu
> tháng thắng" mà test chạy mỗi đêm trước bước `fundamentals` T7 ⇒ ảnh thật
> không lần nào ghi được). User xoá cả 3 trên 💻 laptop. ⇒ Lịch sử point-in-time
> **chưa có tháng thật nào**; 08 và 09 MẤT HẲN (API chỉ trả số hiện tại);
> ảnh thật đầu tiên = bước `fundamentals` T7 10/10. Mốc "6–12 tháng" ở trên
> tính lại từ 10/2026.

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

# ⚠️ HAI MÁY, HAI KHO — chốt 19/08 (bản đã sửa 2 lần, đọc kỹ)

Hai lần tôi kết luận sai về máy trong cùng một buổi; bản này là bản đúng, giữ
lại cả vết sai để không lặp.

**Sự thật:**
* **Desktop** — có 2 task lịch, là máy chạy pipeline và sinh brief. Toàn bộ
  chẩn đoán sáng 19/08 (log 1,19 MB đã bị cắt · phát `all` gần nhất **chết ở
  bước `test` 9/14, `rc=2 → stopping`** · sync 3.609s / screener 1.657s / TỔNG
  96,6 phút · `test_close_1507_review` nay đã xanh) đều đo TRÊN DESKTOP và
  **VẪN ĐÚNG**.
* **Laptop `CFA-BINHLD-LT`** — KHÔNG có task lịch, nhưng có **kho đầy đủ 3.125
  mã** + `run_daily.log` riêng. Full suite 2.168 passed / 113,7s đo ở đây.

**Hai lần nhầm, để làm bài học:**
1. Suy nhận dạng máy từ `C:\vnstock` + venv `Administrator` → sai, hai máy cài
   giống hệt nhau. Phải dùng `$env:COMPUTERNAME` + `Get-ScheduledTask`.
2. Thấy laptop không có task → vội quy TOÀN BỘ log về laptop và gỡ nhãn chẩn
   đoán đúng. Sai chiều: user chỉ vừa đổi sang laptop ở cuối buổi. **Bài học:
   khi phát hiện nhầm bối cảnh, hỏi mốc chuyển chứ đừng quy hồi tố tất cả.**

**⇄ VVS CHƯA CHỮA TRÊN MÁY NÀO (phát hiện lại 19/08).** Đầu mối để rơi: VVS
là mã KHỞI ĐẦU cuộc điều tra 18/08 (probe chốt `warehouse_basis 1.6543×`), rồi
đợt quét `--all` lôi ra VHM/PNJ/GEX/GEE/PVD và mình chữa nhóm đó — **quên chính
VVS**. Vách 2026-06-15 (mới 2 tháng, trong mọi cửa sổ backtest), GTGD ~13
tỷ/phiên nên KHÔNG thuộc diện "đuôi thanh khoản thấp bỏ qua". Dry-run 19/08 cho
ca sạch nhất: 908/908 bar lấy thẳng nguồn, 0 bar nhân hệ số, volume không gãy.
Lệnh: `python scripts/rebase_ticker_history.py --ticker VVS --apply` rồi
`check_unit_continuity --ticker VVS`. **Phải chạy trên CẢ HAI máy.**
✅ LAPTOP xong 19/08 13:04 (backup `VVS_20260819-130408`, 5 file ghi nguyên tử,
tự kiểm "chuỗi đã liền"). ⏳ **DESKTOP chưa làm** — bản chữa có hậu quả thật
nằm ở đó, vì desktop mới sinh khuyến nghị.

**RỦI RO PHÂN KỲ — ĐÃ ĐO, KHÔNG XẢY RA (ít nhất với VHM).** Lo ban đầu: đợt
chữa 18/08 chạy trên desktop, kho local không đồng bộ ⇒ laptop còn chuỗi hỏng.
Đo thật trên laptop 19/08: **VHM SẠCH** — 3.476 bar, bar cuối 2026-08-18,
KHÔNG còn vách 2026, khớp giá live 68.200 (lệch 0.99×). Chữ ký trùng KHỚP
trạng thái desktop sau khi chữa: chỉ còn 2 vết vô hại là vách 2015-06-10 và
quãng nghỉ 308 ngày tới 2018-05-17 — **cả hai nằm TRƯỚC ngày Vinhomes niêm yết
(17/05/2018), tức thuộc doanh nghiệp KHÁC từng dùng ticker VHM**, ngoài mọi
lookback thực tế (backtest dài nhất 730 ngày).
**4 mã còn lại cũng SẠCH trên laptop** (đo 19/08): PNJ 4.347 bar ·
GEX 2.700 · GEE 1.093 · PVD 4.910 — đều "không vách đứt đáng ngờ", bar cuối
18/08, khớp giá live 0.98-1.03×. ⇒ **Kho laptop = bản đầy đủ, đã chữa, cập nhật
tới 18/08 — dùng để soi số được.** Đóng hẳn nghi vấn phân kỳ cho đợt 18/08.
Còn giữ: hai kho KHÔNG tự đồng bộ, nên **lần chữa kho sau phải làm trên CẢ HAI
máy** (hoặc chép lại) — nếu không thì lần sau mới thật sự lệch.

---

# 📌 VIỆC PHẢI LÀM — chốt 18/08/2026 (bản 2, sau đợt đối soát code)

> ⚠️ ĐÂY LÀ KHO LƯU (lý do + file:line). Muốn LÀM THEO thì mở
> **`docs/VIEC-DANG-LAM.md`** — 1 trang, có lệnh sẵn, tách việc-của-user và
> việc-của-Claude. Sửa mục nào ở đây thì soát lại trang kia.
>
> Danh sách ĐANG DÙNG. **Luôn nằm CUỐI FILE** — entry nhật ký mới chèn TRƯỚC mục này.
>
> Bản này khác bản trước ở chỗ: mọi mục đã được ĐỐI SOÁT VỚI CODE THẬT (4 hướng
> quét song song + phản biện, 18/08). Nhiều nợ cũ nằm rải trong thân notes đã
> được lôi ra đây; vài mô tả cũ bị đính chính. Mục nào ghi "đối soát ✅" nghĩa là
> đã mở file kiểm lại, không phải chép sổ.
>
> Trạng thái: full suite **2.168 passed** (0 skip, 0 xfail), `--fast` 1.648.
> **ĐO TRÊN MÁY THẬT 19/08: cũng đúng 2.168 passed** (113,7s) — khớp container
> từng test một. ⇒ **HUỶ nghi ngờ "chênh 60 test do nhánh env-gated"** mà bản
> trước ghi: con số 2.088 trong log 17/08 chỉ là bộ test của NGÀY HÔM ĐÓ, ít
> hơn vì các test thêm sau đó chưa tồn tại. Không có nhánh nào bị env nuốt, và
> 6 cổng `importorskip` (mục T-a) KHÔNG kích hoạt trên máy user. Bộ test HERMETIC với mạng (chặn socket vẫn 2.148 passed) và
> KHÔNG đụng byte nào trong kho. Nhánh `claude/tong-hop-cong-viec-test-w8mvrc`
> đã push đủ, cây sạch.
>
> ⚠️ MỌI lệnh soi trạng thái CHỈ chạy được TRÊN DESKTOP `C:\vnstock` — log và kho
> đều trong `.gitignore`, task đăng ký theo máy (đã chốt vào CLAUDE.md).
>
> ĐÃ ĐÓNG 13-18/08, đừng nêu lại: heatmap VN30 live · mục 2 model watch · mục 3
> badge đơn vị · mục 5 độ trễ OpenRouter · mục 9 nhãn kỳ NN · mục 10 gate
> Telegram · 4c/0e (#32 đạt kiểm định) · 4d · 0f · **A** (chạy bù 14 bước) ·
> **B** (3 lệnh soi log + chấm mục ② = BỎ) · **C** (brief chiều 18/08 đạt 4/4) ·
> *(lưu ý đọc mục A: "14 bước, exit 0" chỉ nghĩa là 14 bước đã lần lượt ĐƯỢC GỌI,
> KHÔNG phải đều thành công — `cmd_all` coi rc==1 là cảnh báo rồi vẫn trả 0)* ·
> **I** (badge doctor — phần code xong, chỉ còn đọc khi warn).

## 🔴 LÀM NGAY — 1 lệnh trên DESKTOP, và nên làm SỚM

**1. Soi `run_daily.log` giải mã `brief 0.0s`** (mục R cũ). Đây là thứ duy nhất
đang chặn việc hiểu vì sao đêm tự động chưa lần nào tới brief.
```powershell
Select-String -Path C:\vnstock\run_daily.log -Encoding utf8 `
  -Pattern '^\[run\.py\] 20\d\d-.* all$|^\[brief\]|brief returned|^\[telegram\] close brief' `
  | Select-Object -Last 25
```
4 kết cục, mỗi cái một dòng `[brief]`: `VNSTOCK_PIPELINE_BRIEF=0` (kill-switch —
LẶP LẠI đêm sau, phải xoá khỏi `.env`) · `bỏ qua: chưa tới 15:00` (đúng thiết kế,
nhưng kéo theo việc 2) · `bỏ qua: … (marker)` · `❌ <Lỗi>` (lỗi thật).
`exit 0` KHÔNG loại được ca lỗi — `cmd_all` coi rc==1 là cảnh báo rồi vẫn trả 0
(run.py:1284-1287). Đọc THEO CỤM dưới từng header có mốc giờ; dòng `[brief]`
không mang giờ nên đọc rời là gán nhầm phát.

⏰ **SỚM chừng nào tốt chừng ấy**: bước `test` đổ TOÀN BỘ output `pytest -v` vào
`run_daily.log` (1.596 dòng mỗi `--fast`, 2.204 dòng mỗi lần full — run.py:764),
mà log quá 5 MB thì `_trim_run_log` chỉ giữ đuôi 1 MB. Log trong container đã
5,12 MB. Mỗi phát `all` nữa là bằng chứng có thể bị xén.

**2. Chỉ khi việc 1 ra "chưa tới 15:00"** — kiểm độ tươi độ rộng của brief 23:16:
```powershell
python -c "import json;d=json.load(open(r'C:\vnstock\data_warehouse\_meta\market_overview.json',encoding='utf-8'));print(d.get('generated_at'),d.get('data_date'),d.get('gtgd_date'))"
```
`generated_at` < 15:05 → A/D 0.91 + movers + dòng tiền ngành trong brief là số
GIỮA PHIÊN; chữa bằng `python run.py screener`, **đừng gửi lại brief**. Bằng
chứng dự phòng 30 ngày: `_meta/screener_history/2026-08-18.json` (copy2 giữ
nguyên mtime — vnstock_runner.py:125-137).

**3. ✅ ĐÓNG 19/08 — classifier chạy thật, ladder free hoạt động.** Nợ §10 từ
07/08. `--rerun-flagged VNM` in đúng `route: ladder free — Gemini 3.5-flash
dẫn đầu`, 1 classified / 0 errors, KHÔNG đòi `ANTHROPIC_API_KEY`. Ghi chú cho
lần sau: `--classify` thường KHÔNG xác minh được gì vì 1652/1652 mã đã phân
loại nên nó skip sạch, không gọi LLM lần nào — phải dùng `--rerun-flagged`.

## 🟠 NỢ CODE MỚI PHÁT HIỆN — đáng làm, không ai chặn

**S1. Lỗ hổng độ tươi: giờ bị cắt ngay từ nguồn** (~1 buổi, nên hỏi mốc giờ).
`vnstock_brief.py:1095` — `return gen.split(" ")[0] if gen else None` VỨT phần
giờ của `generated_at`, nên cờ stale (:1147) và auto-refresh (:1169) chỉ so được
NGÀY. Overview sinh giữa phiên trôi lọt không cảnh báo. Tệ hơn: không tự lành
trong cùng ngày vì `_warehouse_eod_date()` (:1100-1113) chỉ nhìn bar VNINDEX.
Đây là gốc của việc 2 ở trên — vá gốc thì khỏi phải soi tay mỗi lần.

**S2. `run.py telegram close` — cửa gửi không có gác nhưng vẫn ghi marker**
(~30'). run.py:962-967 gửi thẳng, KHÔNG gọi `_should_push_close`, rồi vẫn
`_write_close_marker`. Hai hậu quả: gõ 2 lần = 2 brief; gõ trước 15:00 ngày làm
việc = làm CÂM brief của task 18:00 cùng phiên. Hiện chỉ vá bằng kỷ luật ("dùng
`run.py brief`" — đường đó qua đủ 3 cửa gác).

**S3. Bộ test ghi bẩn + tự cắt `run_daily.log`** (~30'). `tests/test_run.py` gọi
`orchestrator.main([...])` 10 lần mà không patch `RUN_LOG_PATH` (run.py:1319 là
hằng số module TUYỆT ĐỐI theo `__file__`, `_install_run_log` gọi vô điều kiện ở
:1691) → **9 khối header giả** + ~101 dòng rác vào log THẬT mỗi phát full suite
(lần thứ 10 ở test_run.py:62 chết ở argparse trước khi kịp install). `--fast`
KHÔNG dính. Nguy hơn header: mỗi khối còn gọi `_trim_run_log()` trên log thật.
Cộng với S3b (bước test đổ `pytest -v` vào log) là thứ đẩy log tới ngưỡng tự
cắt. Sửa: fixture autouse trỏ `RUN_LOG_PATH` sang `tmp_path`, hoặc
`_install_run_log` tự tắt khi thấy `PYTEST_CURRENT_TEST`. Làm cái này thì lệnh
soi ở việc 1 gọn lại còn một dòng grep.
*(Đính chính hai lần: bản R6 ghi 9 → tôi sửa thành 10 → phản biện đo lại ra
ĐÚNG 9. Giữ 9.)*

**S4. Khuyến nghị bị đóng SỚM: horizon GHI bằng PHIÊN nhưng THI HÀNH bằng NGÀY
LỊCH** (~30' — nhưng đây là lỗi số liệu nặng nhất trong danh sách).
`vnstock_train.py:559` `age_days = (datetime.now() - created).days` rồi :561 so
với `horizon`, trong khi `horizon_days` lấy thẳng từ TIER_CONFIGS
(vnstock_strategy.py:77-80 & :2288-2291, short=5 / position=20) và backtest cắt
hist theo BAR (:574). **CẢ HAI tầng dính**, không riêng tầng vị thế: 20 ngày lịch
≈ 14 phiên (−30%); 5 ngày lịch ≈ 3-4 phiên (−20%…−40% tuỳ thứ trong tuần) — mà
tầng short mới là tầng đông rec. Không có chốt `len(post) >= horizon` ở bất kỳ
nhánh nào, và **đóng là VĨNH VIỄN** (grep toàn repo: không có đường reopen).
Giá exit "expire" lấy close của bar CUỐI CÙNG CÓ SẴN (~bar 14), không phải bar 20.
**4 điểm ngày-lịch khác cùng họ:** vnstock_brief.py:3752-3757 (rec biến mất khỏi
brief sau 20 ngày lịch dù DB còn mở) · :1197-1202 `_maybe_reconcile_overdue` ·
dashboard/brief_strategy_panel.py:313-321 · vnstock_train.py:500/:545
`STALE_GRACE_DAYS`. **Ảnh hưởng trực tiếp mục T3 + S8** — verdict #32 đang được
chấm trên khung ngắn hơn thiết kế ~30%.

**S5. Ghi JSON không nguyên tử — 12 điểm ở 7 file** (~30'). Repo ĐÃ có lưới
`_MUST_BE_ATOMIC` (tests/test_atomic_writes.py:145-154) nhưng chỉ khai 7 file;
chạy lại đúng thuật toán quét đó ra 12 điểm ghi thẳng NGOÀI danh sách:
vnstock_runner.py:128 (screener_results.json) · :719 (market_overview.json) ·
:494 · vnstock_session_stats.py:538 · vnstock_foreign_flow.py:132 ·
vnstock_macro.py:220 · vnstock_news.py:597 · vnstock_vn30_weights.py:61 ·
vnstock_dashboard.py:169/:502/:1913. Pipeline đã bị kill giữa chừng 2 lần.
**Mức độ thật (đã soi từng reader, đừng phóng đại):** `market_overview.json`
TỰ LÀNH (cụt → `_market_overview_data_date` trả None → auto-refresh recompute);
regime/sentiment/allocation/preset_score đều HỎNG AN TOÀN (mất khối, không ra số
sai); `run.py doctor` báo được. **Hai chỗ hở thật:** (a) dashboard đọc
`screener_results.json` KHÔNG try/except; (b) `shutil.copy2` ở
vnstock_runner.py:135 chép bản cụt sang `screener_history/` — tức đầu độc đúng
cái "bằng chứng dự phòng" mà việc 2 ở khối 🔴 đang dựa vào.
Cách sửa đúng nếp repo: đổi sang `write_json_atomic` + **thêm các file này vào
`_MUST_BE_ATOMIC`** (lưới chỉ soi thứ ĐƯỢC KHAI BÁO — đúng bài học của repo).

**S6. Doctor mù với kill-switch nguy hiểm nhất** (~30'). `vnstock_doctor.py` chỉ
đọc 6-7 cờ env của nguồn vĩ mô (:604, :620, :655, :678, :695, :711); KHÔNG soi
`VNSTOCK_PIPELINE_BRIEF` (tắt hẳn brief), `VNSTOCK_BRIEF_AUTO_*`,
`VNSTOCK_STRATEGY_ISOLATION`. Chính ẩn số của việc 1 lẽ ra phải có badge báo.

**S7. 3 file test bộ công cụ đơn vị giá nằm NGOÀI `--fast`** (vài phút).
`test_unit_continuity` / `test_price_basis_probe` / `test_rebase_history` =
48 test, không có trong fast-list (run.py:680-748) → sửa 3 script đó rồi chạy
`--fast` là chạy mà không có lưới. Thêm 3 dòng là xong.

**S8. Mục T3 đang so hai thứ khác đơn vị** (vài phút). P&L khuyến nghị thật tính
GROSS (`vnstock_train.py:503-510`), còn expectancy backtest đã trừ phí roundtrip
0,4% (`vnstock_strategy.py:907`). "Live khớp backtest" vì thế luôn thiên vị live.

**S9. Rổ VN30 hardcode ở 4 nơi, không test đồng bộ** (~30'). `vnstock_wss.py:44`,
`vnstock_brief_canon.py:46`, `vnstock_news.py:65`, + module tính trọng số
benchmark luôn ưu tiên bản hardcode. HOSE cơ cấu lại rổ là 4 nơi lệch nhau âm thầm.

**S10. `_read_ticker` nuốt lỗi trả rỗng** (~30'). Vế thứ HAI của nợ audit 06/08
(vế một đã vá): `vnstock_warehouse._write_parquet` lấy `_read_ticker` làm bản gốc
để merge, mà `_read_ticker` nuốt mọi lỗi và trả DataFrame rỗng → một file year
hỏng có thể bị ghi đè mất. Chỉ dính đường bulk-load thủ công nên không gấp, nhưng
cùng họ rủi ro với mục U1.

## 🧪 TEST — bộ test khoẻ hơn tưởng, 6 lỗ thật

Tin tốt đã kiểm: 2.148 passed, **0 skip / 0 xfail / 0 skipif** trong toàn repo;
chặn sạch socket ra ngoài vẫn 2.148 passed; chạy full suite không đụng byte nào
trong `data_warehouse/`. Bài học SQLite cũ (test_close_1507_review) đã đóng thật.

**T-a. 6 cổng `importorskip` có thể nuốt ~22 test âm thầm** (~30'), mà badge
sidebar không đọc trường `skipped` nên vẫn hiện XANH. Nặng nhất là 2 cổng
module-level: `test_updater_partial_bar.py:24` (mất cả 4 test),
`test_portfolio_prices.py:15-16` (mất cả 11 test).

**T-b. Vẫn còn 1 call mạng THẬT mỗi lần chạy test** (vài phút) — ở bước IMPORT
chứ không trong thân test: `tests/test_classifier.py:17` → `vnstock_classifier.py:70`
`from vnstock import Vnstock` → telemetry của gói vnai gọi ra Fastly.

**T-c. `USE_UNIFIED` — 4 module rẽ nhánh, 0 test chạm** (~1 buổi, cần user quyết
có đáng không). `vnstock_updater.py:49/53`, `vnstock_classifier.py:64/68/263/297`,
`vnstock_warehouse.py:105/107`. Đây đúng loại "xanh trên CI nhưng chạy CODE KHÁC
trên máy user".

**T-d. 9/16 hàm render tab không bao giờ chạy thân trong test** (~1 buổi) — tái
sử dụng được fixture `render_env` có sẵn ở `tests/test_tab_render_smoke.py`.

**T-e. `vnstock_auth.py` (224 dòng) và `vnstock_freefloat.py` (200 dòng) không có
một test nào.** auth là cửa quyết định sponsor/free mà gần như cả repo import ở
module level — dính thẳng vào mục U4 (nâng thư viện). freefloat thì hỏng ÂM THẦM
trong đường chạy đêm (`vnstock_runner.py:206-210` chỉ log 1 dòng mờ).

**T-f. `probe_price_basis` không test CLI** (~30') — 2 công cụ anh em đều có test
`main()` với exit code, riêng nó chỉ test 2 hàm thuần.

## ⏳ TỰ ĐẾN — chỉ cần ĐỌC khi tới

**U1. Báo cáo model watch T7 22/08** — 3 điểm hẹn: (a) `gemini-3.5-flash` còn n/a
không; (b) Groq `gpt-oss-20b` sentiment ≤0,75 lần 2 → cân nhắc đổi nấc [1] sang
`gemma-4-31b`; (c) chấm bù `nemotron-ultra` → đóng hẳn mục 5.
**3 cảnh báo trước để khỏi hoảng:**
* Đổi nấc [1] sẽ làm ĐỎ NGAY `test_providers_ladder_slugs_22_07`
  (tests/test_model_ladder.py:46-55 khoá cứng cả danh sách VÀ thứ tự) — đỏ có chủ ý.
* Bỏ `gemini-3.5-flash` phải sửa ít nhất 6 điểm (vnstock_brief.py:112 & :840,
  vnstock_report_digest.py:98, scripts/probe_models.py:57, vnstock_llm_ledger.py:48)
  + 1 assert cứng trong test.
* `_DEAD_SLUGS_22_07` là danh sách TAY đóng băng từ 22/07 — đã 4 tuần chưa động,
  và `zai-glm-4.7` vừa tới hạn khai tử 17/08 (hôm kia).
* Ứng viên mới `gemini-3.7-flash`: grep toàn repo = 0 kết quả (đúng luật, chưa ai
  lỡ tay nhét vào). Muốn dùng phải probe sống trước.

**U2. Không có cơ chế bắt slug MỚI chết** (~30'). Ngày khai tử chỉ nằm trong
COMMENT (`vnstock_model_watch.py:12-13`, `vnstock_brief.py:619`) — không hằng số,
không field trong `model_status.json`, không assert. Thêm `sunset_date` vào
`_DEAD_SLUGS` + 1 test canh "ngày đã qua mà slug vẫn live".

**U3. Sync time** — chuỗi đo: 9.731s → 2.376s → 4.429s (phát bị kill tối 17/08)
→ 1.205s (chạy bù 18/08). Ngưỡng: **2-3 đêm nữa phải < ~10 phút**.
**Ngưỡng CỨNG: trần task Daily là 120 phút** (`setup_scheduled_tasks.ps1:109`).
Sync 74' như 17/08 là đủ để Windows chấm dứt task TRƯỚC bước brief (bước 14/14)
— nghi phạm chính khiến đêm tự động chưa lần nào tới brief. Không teo thì nới
`MaxMinutes` hoặc tách brief ra task riêng (`run.py --no-brief` + task thứ 3 —
cờ đã có sẵn ở run.py:1234).

**U6. NSO + Jina không truy cập được TỪ LAPTOP — nhiều khả năng là MẠNG, không
phải nguồn chết** (19/08, `doctor --net` trên laptop `CFA-BINHLD-LT`).
Bảng: 25 ✅ · 2 ⚠️ · 1 ❌.
`vnstock_nso.py --diag --dump` cho thấy CẢ BA URL chết ở tầng KẾT NỐI, chưa
tải được byte nào: `www.nso.gov.vn` ConnectTimeout · `nso.gov.vn`
ConnectionReset (WinError 10054 — remote host CHỦ ĐỘNG đóng) · `www.gso.gov.vn`
ConnectTimeout. ⇒ **KHÔNG phải đổi layout, đừng đi sửa regex.**
Ghép với `r.jina.ai` cũng không tới được trong CÙNG lượt đo: hai host ngoài
độc lập cùng chết trên một máy = chữ ký của chặn mạng (laptop có tên kiểu máy
công ty), không phải hai nguồn cùng hỏng một lúc.
**Việc phân định (🖥️ DESKTOP): chạy `python run.py doctor --net` trên desktop.**
* Desktop cũng ❌ → nguồn/chính sách thật, lúc đó mới bàn sửa code.
* Desktop ✅ → chỉ là mạng laptop; production KHÔNG hỏng, và bài học là
  **không kết luận "nguồn chết" từ một máy** (cùng họ với bài học nhận dạng máy).
Hậu quả nếu desktop cũng hỏng: CPI / IIP / cán cân thương mại chạy bằng số
THÁNG 7 trong cache, số tháng 8 sẽ không về. Doctor offline không thấy vì nó
chỉ so tuổi cache.

**U4-bis (19/08, đo trên máy thật).** `vnstock_classifier` in `✅ Using
vnstock_data` ⇒ **nhánh SPONSOR đang hoạt động trên máy thật**, trong khi
container KHÔNG có `vnstock_data`/`vnii` (find_spec → None) nên toàn bộ test
2.181 chỉ chứng minh nhánh FREE. Đây chính là mục T-c (`USE_UNIFIED` — 4 module
rẽ nhánh, 0 test chạm) ở dạng cụ thể: **nâng thư viện là đụng đúng nhánh mà
lưới test không với tới**. ⇒ Nâng thì phải làm trên LAPTOP trước (không chạy
pipeline đêm nên hỏng không mất brief), rồi mới tới desktop.

# 🪙 U82. KHO ĐA TÀI SẢN — P1 CODE (09/10 tối)

User duyệt P1 sau P0/P0b (U81). Chi tiết thiết kế đã làm: `docs/THIET-KE-DA-TAI-SAN.md` §9. Tóm:
`vnstock_assets_sources` (parse thuần + fetch qua MỘT chỗ `HTTP` — conftest chặn) · `vnstock_assets`
(registry 24 chuỗi; kho `assets/<KHOÁ>/<YYYY>.parquet` ghi nguyên tử, đọc gộp bản Dropbox trùng; `merge`:
ngày ≥ hôm qua bản MỚI thắng, cũ hơn theo `Spec.sources`, lệch > `xtol_pct` ⇒ cờ `xcheck` ghi một lần;
`*_EST`: USD rộng = Fed × chỉ số tự tính lệch pha +1 ±0,30%, WTI giao ngay ±1,64% chỉ ≤3 phiên; khoá theo
máy ở thư mục tạm; `hourly` = Python + MCP theo giờ đặt; `backfill`) · `vnstock_assets_mcp` (16 tool/lượt,
đại lý ×10.000 → đồng/lượng, SBVN ⇒ trung tâm (mua+bán)/2; backfill 12 lượt nhỏ ≤2 chuỗi để mỗi phiên
`claude -p` không quá tải ngữ cảnh; `verify_sbvn` so với mbk). Nhịp: móc vào `cmd_news_alert` (tiến trình
con trần 360s vì task tin trần 15′; không đổi rc tin; dry-run/lọc nguồn không móc) + bước `assets` sau gold
+ `assets-mcp` cuối pipeline (chỉ khi MCP trước >6 giờ). Doctor `check_assets` chỉ warn. Dọn: goldprice.org
403 và exchangerate.host (hết VND) gỡ khỏi ladder; nhãn "premium SJC ~15-20%" (sai — đo 11%) thay bằng
`vnstock_gold._premium_note` đọc kho. Test 40 mới (`test_assets*.py`) + sửa test ghim thứ tự bước
(`test_run_pipeline`, `test_horizons_state`) và nguồn vàng (`test_gold`, `test_probe_assets`); conftest
`_assets_hermetic_anywhere` (kho/meta/khoá về tmp, mạng chặn, mbk rỗng, `VNSTOCK_ASSETS_HOURLY=0`).
Sandbox: `--fast` 35 đỏ = 34 đỏ sẵn (thiếu `vnstock`/`vnstock_data`) + 0 mới sau khi sửa 2 test ghim.
**Lệch §4c:** lịch sử WTI từ Yahoo (không vnstock_data); chuỗi dẫn USD rộng là currency-api (~1 lần/ngày,
~07:00 VN) — "trong ngày" chưa "trong giờ"; thử Yahoo FX sau ≥1 tuần số thật.
**Chờ 🖥️:** merge → `run.py test --fast` → `run.py assets --backfill --with-mcp` NGOÀI khung pipeline →
`run.py assets --show` + doctor, dán cho Claude (kết luận `verify_sbvn` quyết công thức trung tâm).

**🖥️ lượt đầu 10/10 ~00:xx + sửa (thiết kế §9b):** `--fast` 3.390 passed; backfill phần lớn ✅ (FRED
23.822, Yahoo, VCB 522, mbk 3.182, MCP XAU/dầu/9 sản phẩm đại lý). Bốn lỗ: (1) SJC miếng 3 khung + SBVN
3m "kết quả rỗng" = Claude Code CẮT kết quả MCP > ~25k token (đo trong phiên: đại lý ~15 token/ngày; SBVN
1m = 154 dòng) mà code gộp thành "rỗng" ⇒ SJC xin từng năm, SBVN 3 × `range=1m`+`toDate`, `empty_reason`
in text thật, `--mcp-backfill --only KHOÁ,…`. (2) **SBVN ≠ tỷ giá trung tâm**: = "tỷ giá tham khảo Cục
QLNH" (báo chí 08/10 24.407–26.869 khớp từng đồng), giữa mua/bán khớp trung tâm 3/5 phiên 05–09/10 ⇒ chuỗi
riêng `USD_SBV_REF`; `merge` nay TỪ CHỐI nguồn không khai trong `Spec.sources` (luật 1 bằng code) và bỏ
dòng cũ của nguồn đã gỡ. (3) **mbk nghi ghi LÙI 1 phiên** (mbk 08/10 = 25.629 = NHNN công bố 09/10; 08/10
là 25.634) — chưa dời ngày, `verify_central` đo lệch −1/0/+1 trên ~60 phiên ⇒ quyết sau. (4) backfill
không chạy lượt Python ⇒ đường cong trống, doctor "chưa có lượt nào", USD rộng ẩn không rõ lý do ⇒
backfill chốt bằng lượt Python + lý do ẩn chỉ đúng khâu. Test assets 40 → 48.

**🖥️ vòng 2 10/10 01:03 + sửa (thiết kế §9c):** SJC miếng 2015→nay 4.303 dòng, `USD_SBV_REF` 67, đường cong
Brent/WTI có, 21/22 chuỗi trong ngày. **mbk ghi LÙI 1 phiên — xác nhận** (62 phiên: +1 khớp 32 vs đúng ngày
8; báo chí 01→08/10 khớp từng đồng, thứ Sáu mbk = số thứ Hai NHNN) ⇒ `shift_mbk_dates` trong
`fetch_mbk_central` (sang ngày làm việc kế tiếp CÓ trong chuỗi; dòng cuối theo lịch; trùng đích dòng sau
thắng) + `central_dating()` đo SỐNG từ kho ở `--show` và doctor (warn khi lệch ≠ 0). Ước tính USD rộng
tính ra 121,23 mà không vào kho: mang ngày FILE thứ Bảy ⇒ kho bỏ cuối tuần — nay mang ngày Fed (file −
1), h đếm phiên. Cache currency-api: "latest" lúc 01:00 là file hôm qua cất dưới khoá hôm nay và không
tải lại ⇒ nay khoá theo `date` trong file + tải lại 3 ngày gần nhất. Thêm `--backfill --steps …`. Test
assets 48 → 57.

**🖥️ vòng 3 10/10 01:22:** kho ĐÚNG (22/22 trong ngày, MCP ok, USD rộng ước tính 121,23 ngày 09/10 h=5,
trung tâm 09/10 = 25.629 khớp báo chí) nhưng doctor réo "LÙI 1 phiên" — **báo động giả do THƯỚC**: giữa
SBVN = trung tâm cùng phiên 26/63, = phiên trước 43/62 (thước trễ lẫn). Bài học: thước đo có độ trễ riêng
thì đừng so từng lệch rồi lấy max — chấm GIẢ THUYẾT bằng cửa sổ đúng hình dạng thước (D−L hoặc D−L−1).
`verify_central` viết lại theo cách đó (sàn 10 phiên / 80% / cách 10 điểm, không thì "chưa rõ", doctor
im); `--backfill --steps mbk` in mbk THÔ theo thứ + 10 dòng cuối để chốt luật dòng CN. Test 57 → 58.

**🖥️ vòng 4 10/10 01:37 — P1 XONG:** "mbk ĐÚNG ngày" (lệch 0 khớp 59/61), doctor ✅ 22/22. mbk thô theo thứ
T2 535 · T3 538 · T4 537 · T5 537 · T6 502 · T7 1 · CN 532 ⇒ mbk ghi số ngày D vào ngày LỊCH D−1 (dòng CN = số
thứ Hai). Đính chính: NHNN 05/10 = 25.643, 06/10 = 25.645 (đọc theo chuỗi +12/+7/+2/−7/−4/−5) — vòng 2 đọc
nhầm thành 25.636/25.643 từ bản tóm tắt tìm kiếm trộn hai bài; test ghim số đã sửa theo bản thô thật.

# 🪙 U81. ĐA TÀI SẢN VÀNG · DẦU · USD — P0 ĐO NGUỒN (09/10)

**User 09/10:** mở rộng dashboard sang tài sản khác, trước hết vàng/dầu/USD; lên kế hoạch, duyệt rồi mới
làm ⇒ duyệt P0. Chốt cùng ngày: tab riêng · MCP "tuỳ Claude" (Claude chọn LAI: MCP Finhay/SSI làm nguồn
NGÀY, Python FRED/stooq làm lịch sử dài + dự phòng, chốt sau probe) · vàng nội cả 5 đại lý · danh sách
cổ phiếu liên kết theo thiết kế §3. Toàn bộ thiết kế: `docs/THIET-KE-DA-TAI-SAN.md`.

**Hiện trạng soi được:** vàng chỉ có spot USD/oz 1 điểm/ngày (`vnstock_gold`, nhãn cứng "premium SJC
~15–20%" ở `:39` — đo 09/10 chỉ ~9–11%); USD/VND trong registry trần 60 điểm; tỷ giá trung tâm chỉ 1
điểm/TUẦN (bản tin SBV); dầu KHÔNG có số — ghi chú khảo sát 07/2026 "dầu không có API free"
(:1767) SÓT FRED Brent `DCOILBRENTEU`/WTI `DCOILWTICO` (key đã có).

**Đo qua connector trong phiên Claude 09/10 (KHÔNG phải máy thật):** Finhay có XAU/XAG/HG/CL/BZ/NG nến
ngày tươi trong phiên nhưng sâu NGẮN (XAU có 01/2025, rỗng 01/2020; CL rỗng 01/2024; USDVND chỉ từ
03/08/2026); giá đại lý 10 sản phẩm vàng (SJC/PNJ/DOJI/BTMC/BTMH) đơn vị **nghìn đ/chỉ** (SJC bán 14.480 ⇔
144,8 tr/lượng, 01/2025 8.620 ⇔ 86,2 tr). SSI `foreign_currency_converter` bank **SBVN** = giá Sở giao
dịch NHNN: mua 24.398 · bán 26.860 ⇒ (mua+bán)/2 = 25.629 và ×1,05 = 26.910 = bán+50, ×0,95 = 24.348 =
mua−50 — khớp cả hai phía ⇒ tỷ giá TRUNG TÂM theo NGÀY suy được (cần đối chiếu bản tin SBV). VCB bán
26.090 ⇒ còn ~3,1% tới trần. Chênh SJC miếng vs XAU 4.182,09 × 25.881 × 1,20565 oz/lượng ≈ +11,0%.

**Đã làm:** `scripts/probe_assets.py` (chỉ đọc) — 4 tầng: python (FRED 3 chuỗi, 2 endpoint vàng + 4 FX
đang chạy đo TỪNG cái, stooq, Yahoo, SJC + VCB trực tiếp có dò độ sâu 1 năm/5 năm), sponsor (đi FILE
của vnstock_data/vnii/vnstock tìm module hàng hoá·vĩ mô·tỷ giá — không import cả gói — in chữ ký, gọi thử
≤16 lượt 60s/lượt trong thread daemon, bỏ hàm có chữ key/auth/limit/set/save…), local (3 cache kho), mcp
(`--mcp`: một `complete_mcp`, 36 lượt gọi — 5 chuỗi × 5 cửa sổ độ sâu + 9 sản phẩm vàng cửa sổ gần nhất +
SSI VCB/SBVN; tool tài khoản không bao giờ mở). Khối "Suy ra" (chênh SJC, dư địa tới trần, đối chiếu
trung tâm) + "Kết luận theo tài sản" (tươi nhất/sâu nhất). Lỗi mạng rút về NGUYÊN NHÂN và xoá api_key
(lỗi requests chứa nguyên URL kèm key). Test `tests/test_probe_assets.py` (25, whitelist `--fast`); dùng
`sys.modules` khi nạp script vì `@dataclass` tra module ở đó. Sandbox Claude: mọi host bị proxy chặn
403 ⇒ tầng python ra toàn ❌ đúng dự kiến.

**Kết quả máy thật (🖥️ PICHU 09/10 19:51; `--fast` 3.335 passed trước đó)** — bảng đủ ở thiết kế §4b:
FRED Brent/WTI/DTWEXBGS ✅ (trễ 3d/3d/7d, từ 1987/1986/2006) · gold-api ✅ nhưng **goldprice.org 403**
(nấc 1 `vnstock_gold` chết, nấc 2 gánh) · **exchangerate.host hết VND** (nấc 2 `usdvnd` chết) · stooq ❌
(trả HTML) · Yahoo ✅ cả 5 (DX-Y.NYB = DXY thật từ 1971; không chính thức) · sjc.com.vn + vietcombank api ✅
có ngày 5 năm trước · `vnstock_data`: `CommodityPrice` (spl) gold_vn/gold_global/oil_crude + `Macro` mbk
có "Tỷ giá trung tâm (từ 04/01/2016)", Macro asean dừng 10/09 · MCP 36/36 tool, 54s, quy đổi $0,25: Finhay
trễ 0d mọi chuỗi; BZ/CL/USDVND RỖNG ở 01/2025, **SJC miếng có từ 01/2015**; SSI SBVN ⇒ trung tâm 25.629.
**Bẫy chính:** cùng tên khác công cụ — vàng giao ngay 4.180 vs HĐTL 4.206 (+0,6%); Brent HĐTL 103 vs
giao ngay EIA (FRED) **125,44** (~+22%, khác ngày 06/10 vs 09/10 — phải so cùng ngày); WTI 91 vs 96,24 ⇒
mỗi chuỗi kho = MỘT công cụ, không nối nguồn khác công cụ. Đề xuất nguồn từng chuỗi: thiết kế §4c —
**CHỜ USER DUYỆT P1**.

**Chuẩn độ tươi (user 09/10 tối):** chỉ số quốc tế (vàng/USD/dầu) + tin liên quan phải có TRONG NGÀY ⇒
Brent/WTI giao ngay EIA (trễ 3–9d) và USD rộng Fed (trễ ≤7d) KHÔNG đạt — không có nguồn miễn phí nhanh
hơn (Dated Brent = Platts/Argus trả phí). Giải pháp (thiết kế §4d): ước tính trong ngày neo số chính
thức gần nhất × biến động chuỗi sống (HĐTL tháng gần; chỉ số tự tính từ trọng số Fed 26 tiền tệ × tỷ giá
ngày currency-api), chỉ hiện khi p90 sai số dưới ngưỡng; dầu thêm đường cong HĐTL M1…M8 (Yahoo `.NYM`)
làm thước "vật chất căng" thời gian thực. `scripts/probe_nowcast.py` (P0b, chỉ đọc) đo trên lịch sử thật;
test `tests/test_probe_nowcast.py` (14, whitelist). Bẫy khi viết: `best_shift` từng so trung vị ĐÃ làm
tròn ⇒ hoà 0,0 chọn nhầm lệch pha — nay so số thô, hoà ưu tiên lệch pha 0. Nhịp P1: nguồn Python mỗi giờ
(ghép task News Alert), MCP 3–4 lượt/ngày.

**P0b trên máy thật (🖥️ PICHU 09/10 20:20):** USD rộng tự tính 26/26 tiền tệ (trọng số Fed 2026), lệch
pha +1, p90 0,28–0,31% ở MỌI h=1…5 (nhiễu ngày, không trôi) ⇒ TẠM, hiện kèm ±0,3%; ước tính 09/10 121,23
(neo 121,38 ngày 02/10). Brent giao ngay: cùng ngày 06/10 giao ngay 125,44 vs HĐTL 100,58 = **+24,7%**,
ước tính p90 5,69% (h=3, 120 ngày) ⇒ KHÔNG HIỆN. WTI: +7,6% cùng ngày, p90 1,64% ở h=3 nhưng 3,86% ở h=5
⇒ chỉ hiện ≤3 phiên. Đường cong Yahoo `.NYM` sống đủ 6–7 kỳ hạn: Brent M1−M2 +3,29$, M1−M6 +11% ⇒
backwardation. OPEC basket 403 Cloudflare ⇒ bỏ. Bảng nguồn §4c đã chỉnh — CHỜ DUYỆT P1.

# 🏷️ U80. MỐC HIỂN THỊ CỦA LỆNH MỞ QUA GDKHQ — BRIEF 💡 + FOOTER DÙNG CÙNG HỆ SỐ VỚI PHÉP CHẤM (08/10)

**Vết (`/brief-review` brief #924, tối 08/10):** mục 💡 in "GMD BUY entry=77.6 · TP=82.2 · SL=75.1"
và footer "GMD MUA @77.6" trong khi GMD đóng **54,2** (SSI) sau thưởng 50% GDKHQ 07/10. U74 chỉ sửa
PHÉP CHẤM (`_corp_action_plan`: treo / mốc × hệ số đo tại neo) — đường HIỂN THỊ vẫn đọc mốc gốc
trong sổ. Không sai kết quả lệnh, nhưng người đọc thấy "mua 77.6" cho mã giá 54.

**Đã làm:** `vnstock_train.rec_display_levels(rec)` gọi lại ĐÚNG `_corp_action_plan`
(`record_anchor=False` — đường hiển thị không chụp neo) ⇒ `rebased`: mốc × hệ số, note "đã quy đổi
theo GDKHQ dd/mm, mốc gốc @E"; `pre_event`/`hold`: mốc gốc + "⚠️ GDKHQ dd/mm — mốc CHƯA quy đổi, giá
tham chiếu đã đổi"; thiếu id/lịch sử/lỗi ⇒ mốc gốc; tắt cùng `VNSTOCK_REC_GDKHQ_HOLD=0`. Một nguồn
`vnstock_brief._rec_levels` cho `_recommendation_block` (note sau " — " để `enforce_rec_line_format`
giữ lại; KL gợi ý tính trên mốc đã quy đổi) và `vnstock_telegram._open_recs_block` (@entry quy đổi,
TP/SL % không đổi vì cùng hệ số, note cuối dòng, `html.escape`). Sổ KHÔNG bị ghi đè. Conftest:
`_display_history` trả rỗng cho MỌI test (rec giả mang `id` không được đọc kho/neo thật). Test
`test_rec_corp_action.py` +5 (rebased/pre_event/không chụp neo/fallback/brief+footer).
Còn: dashboard (tab danh mục/sổ lệnh) vẫn in mốc gốc — chưa động.

**Đo sau merge (🖥️ 08/10 khuya, full 3.900 passed):** footer in "GMD BUY @78 … · ⚠️ GDKHQ 07/10 — mốc
CHƯA quy đổi" — KHÔNG phải @52. Vì sao: lệnh GMD tạo ~23/09, TRƯỚC khi có neo (06/10); lượt chấm 06/10
còn chạy code cũ (desktop pull sau pipeline) nên không chụp neo; từ 07/10 đã có sự kiện xen giữa ⇒ cố ý
không chụp ⇒ `hold` "chưa có neo cơ sở giá" VĨNH VIỄN, hết hạn + grace ⇒ đóng trung tính. **Ghi chú U74
"tối 08/10 lượt đầu QUY ĐỔI (≈52)" là SAI** — kỳ vọng đó giả định có neo. Hiển thị nói đúng phép chấm.
**Vá:** `vnstock_train._anchor_from_rebase_backup` — rebase luôn chép nguyên thư mục mã vào
`_meta/backup_rebase/<MÃ>_<YYYYmmdd-HHMMSS>` TRƯỚC khi ghi; bản SỚM NHẤT có dấu thời gian sau lúc tạo
lệnh = kho ngay trước lần rebase đầu tiên kể từ đó = cùng cơ sở với entry ⇒ close bar ≤ ngày tạo lệnh
là neo đúng nghĩa. `_corp_action_plan`: không có neo ⇒ thử bản sao lưu; phép chấm LƯU neo vào sổ (về sau
không cần bản sao lưu), đường hiển thị không ghi. `vnstock_strategy._read_ticker_dir` tách từ
`_load_history_from_parquet` (đọc được cả bản sao lưu, cùng chuẩn hoá đơn vị). Conftest chuyển
`_REBASE_BACKUP_ROOT` về tmp. Test +2 (chọn bản sớm nhất sau lúc tạo; lệnh không neo được quy đổi + lưu
neo, hiển thị không ghi). `test_strategy_history::…uses_dashboard_loader…` đỏ khi chạy LẺ cả trên main
(phụ thuộc thứ tự) — không phải do vá này.

# 🧾 U79. CONNECTOR MCP VÀO PIPELINE — PHA 1 CHẠY BÓNG: CP CHỜ NIÊM YẾT + CÔNG BỐ (08/10)

**Đo trước (U78 v2, 🖥️ desktop 08/10):** bộ cờ gọn `lean_ts` gọi được CẢ 3 connector, SSI $0,065
· TCBS $0,059 · Finhay $0,059/lượt, mỗi lượt 1 ToolSearch (CLI hoãn schema) — `full` cũ $0,25–0,29.

**Nguồn số:** TCBS `tcinvest-getTickerOverview` cho ĐỦ hai số trong MỘT lượt: `outstandingShare` /
`issueShare` (triệu cp) — SHB 5.343,7 / 4.594,2 khớp số HOSE (lưu hành 5,34 tỷ, niêm yết 4,59 tỷ);
SSI `company_profile.issue_share` = 4.594.200.024 xác nhận. **Bẫy:** GMD 649,3/432,9 = đúng +50%
(thưởng GDKHQ 07/10), FPT +10% — mọi đợt thưởng/cổ tức cp đều tạo lệch tới ngày niêm yết, giá đã
điều chỉnh ⇒ KHÔNG phải cung mới. ⇒ `classify_gap`: lệch < 5% `none`; ≈ Σ tỉ lệ thưởng (sổ
`vnstock_events.price_events` 120 ngày × `vnstock_corp_ratio.parse_event` kind=stock) × niêm yết
(±10%, ≥1 tr) `bonus`; lớn hơn ⇒ `bonus_plus` (phần dư); không sự kiện ⇒ `unlisted` (ca SHB).

**Đã làm:** `vnstock_claude_cli` thêm `MCP_LEAN_FLAGS`, `mcp_server_prefix`, `mcp_command`
(`--allowedTools` để CUỐI), `run_stream_json` (chuyển từ probe — dùng chung), `tool_exchanges`,
`result_event`, `complete_mcp` (thư mục tạm rỗng, sổ LLM ghi mọi kết cục, ToolSearch = phụ, tool
ngoài danh sách = `strangers`). `vnstock_mcp_enrich.py`: vũ trụ = `_meta/portfolio.json` (qty>0)
+ `_load_open_recs` (đúng tập mục Rủi ro), cắt 30; MỘT lượt `claude -p` gọi overview + activity
news (size 5) song song cho mọi mã; `parse_exchanges` đọc `tool_result` (mã trả về phải khớp
tham số); ghi `_meta/mcp_enrich.json` (nguyên tử, có `machine`, `engine.cost_usd`), kể cả
`partial`/`error` để thấy được; cùng ngày đã `ok` đủ mã ⇒ no-op; không có CLI ⇒ bỏ qua (laptop).
`run.py`: bước `mcp-enrich` CUỐI `all` (sau brief — không chạm brief), không bao giờ trả 2,
subcommand `--show|--force|--dry-run|--tickers`. Conftest chuyển `META_DIR` về tmp (U17).
Test: `test_mcp_enrich.py` 19, `test_claude_cli.py` +7, `test_run_pipeline.py` sửa thứ tự +1.

**Lượt thật đầu tiên (🖥️ 08/10 23:17, main `1fd4f38`, full 3.895 passed):** 7 mã (giữ EIB·SSI; lệnh
mở DCM·GMD·GVR·HDB·VEA) · ok · **$0,115 · 29s** (14 tool ≈ $0,008/tool — 30 mã ước ~$0,3–0,4).
GMD 649,3/432,9 ⇒ `bonus` ĐÚNG (thưởng 50% GDKHQ 07/10). EIB 1.862,7/1.868,8 và SSI 3.001,3/3.003,3:
lưu hành < niêm yết = **cổ phiếu quỹ** (lệch âm −0,3%/−0,07%) ⇒ `none`, đúng — đừng đọc thành lỗi.
Công bố bắt được: HDB 07/10 "công văn UBCKNN về hồ sơ đăng ký…" (ứng viên dòng pha 2).

**Pha 2 (sau ≥5 phiên chạy bóng, user duyệt):** brief đọc file ⇒ dòng mục ⚠️ Rủi ro cho
`unlisted`/`bonus_plus` của mã đang giữ (code dựng số, guard canh) + công bố 24h; chuyển bước
lên TRƯỚC brief khi đó (trần thời gian riêng). Chưa làm: hệ số điều chỉnh SSI cho GDKHQ, tab.

# 🔌 U78. CONNECTOR MCP SSI · TCBS · FINHAY — ĐO XEM `claude -p` CÓ GỌI ĐƯỢC KHÔNG (08/10)

**Vì sao:** 08/10 SHB giảm sàn; soi bằng 3 connector (SSI mới nối lại) ra thứ dữ liệu
vnstock không có: tổng cp lưu hành 5.344 triệu vs niêm yết 4.590 triệu (≈750 triệu cp
phát hành 2026 CHƯA niêm yết — báo chí cùng ngày nêu là áp lực cung), cổ đông lớn, công bố
HOSE, hệ số điều chỉnh. Nhưng connector gắn TÀI KHOẢN Claude, không phải API có key ⇒
pipeline Python KHÔNG gọi thẳng được (đúng điều đã ghi ở `export_bank_balance_sheets.py`).
Đường tự động duy nhất là `claude -p` — mà `vnstock_claude_cli.cli_command` CỐ Ý tắt MCP
(`--tools ""` + `--strict-mcp-config`).

**Đã làm:** `scripts/probe_mcp.py` (CHỈ ĐỌC, không ghi kho/sổ LLM). (1) `claude mcp list`;
(2) khám phá 4 bộ cờ (`pipeline` = cờ wrapper · `lean` = bỏ `--strict-mcp-config` · `lean_tools0`
= lean + `--tools ""` · `full`) bằng sự kiện `init` của `--output-format stream-json --verbose`
(có `tools` + `mcp_servers` — đã xác minh trên CLI 2.1.294 trong container) rồi GIẾT tiến
trình ngay; (3) gọi thử 1 tool chỉ-đọc/nguồn (`--allowedTools` đúng tên, cwd rỗng, biến thể
còn công cụ có sẵn thì `--disallowedTools Bash,Edit,Write,…`, `--max-turns 3` — cờ ẩn nhưng
CLI nhận), xác nhận bằng `tool_use`/`tool_result` THẬT trong stream (không tin model kể) +
`permission_denials` của sự kiện `result`. Tên server dò theo khoá (`ssi`/`tcbs`/`finhay`),
không ghim (`SSI_MCP` vs `claude_ai_SSI_MCP` tuỳ CLI). Tool tài khoản Finhay không bao giờ
mở (test canh). Test `tests/test_probe_mcp.py` 25 (tiến trình giả `python -c` in stream).

**Container:** CLI con thấy 0 server ở cả 4 biến thể (connector của phiên cloud do harness
cấp, không gắn vào CLI) ⇒ phép đo THẬT chỉ có ở 🖥️ desktop. Kết quả quyết đường A (bước tự
động qua `claude -p`, ≤30 mã/ngày: cp chờ niêm yết + công bố HOSE vào mục ⚠️ Rủi ro, hệ số
điều chỉnh SSI đối chiếu rebase) hay chỉ đường B (skill gọi tay ghi JSON vào `_meta/`).
KHÔNG dùng MCP thay vnstock lấy giá toàn sàn (1 trang SSI 200 mã ≈ 60K token).

**08/10 tối — ĐO THẬT 🖥️ desktop (full 3.861 passed):** `claude mcp list` thấy cả 3
(`claude.ai SSI MCP` / `claude.ai TCBS MCP` / `claude.ai Finhay`, √ Connected). Init:
`pipeline` 0 tool MCP (wrapper AN TOÀN) · `lean`/`lean_tools0` thấy 79/119 tool MCP của
connector KHÁC nhưng 3 server chứng khoán còn **`pending`** · `full` kịp `connected` SSI (42
tool) + TCBS (54), Finhay vẫn pending. Gọi thử (full): SSI ✅ 17s $0,291 · TCBS ✅ 14s $0,250
(số SHB khớp phiên cloud) · Finhay ⏭. Model gọi **ToolSearch** trước tool MCP (CLI hoãn schema
khi nhiều tool) — hợp lệ. **Bản đầu đọc sai 2 chỗ:** (1) `pending` lúc init = connector
claude.ai nối CHẬM, không phải không có ⇒ bỏ qua oan Finhay + các bộ cờ gọn; (2) `full` nạp
cả skill/rules ECC của máy ⇒ ~$0,25–0,29/lượt cho MỘT tool — quá đắt cho chạy đêm. **v2:**
suy tên tool từ tên server (`server_prefix`: ký tự ngoài chữ/số/_/- ⇒ `_`), thêm bộ cờ
`lean_ts` (`--tools ToolSearch` + tước settings, không strict), thử rẻ trước và dừng ở bộ
đầu tiên gọi được, `full` chỉ khi `--with-full`, ToolSearch không tính là "tool lạ". Test 31.

# 🔎 U77. SỔ NGHI NGỜ BRIEF: Op.CF ĐÃ XÁC MINH THÌ THÔI RÉO (06/10 tối, user chọn B)

**Vì sao:** doctor 06/10 (🖥️ desktop) ⚠️ "Op.CF/vốn hoá lớn bất thường ×20 (HDC, KBC, PVC,
VVS; đậm nhất VVS 1.17×) — ĐỦ mẫu". Đối chiếu BCTC 2025 qua Finhay MCP: **VVS +2.133 tỷ**
(khoản phải trả tăng 2.149 tỷ — vốn lưu động), **HDC −1.017 tỷ** (tồn kho BĐS +989 tỷ);
KBC/PVC đã soi 29/09 ⇒ cả 4 là SỐ THẬT. Nhưng `scan_ocf_scale` quét DỮ LIỆU ctx mỗi phiên
(không đọc chữ brief) ⇒ xoá sổ như 29/09 thì 6 phiên sau réo lại y hệt — báo động giả lặp.

**Đã làm (`vnstock_brief_watch.py`):** sổ RIÊNG `_meta/brief_watch_verified.json` (xoá
`brief_watch.json` để đếm lại KHÔNG mất công xác minh), khoá (mã, Op.CF) với dung sai
max(1%, 1 tỷ) — `is_verified_ocf`. `scan_ocf_scale(verified=)` bỏ qua số đã xác minh
(`observe_brief` tự nạp); `summarize` loại chúng khỏi MỌI phép đếm (cả số phiên, `enough`)
và trả `ocf_verified`. `verify_ocf` lấy Op.CF của quan sát MỚI NHẤT trong sổ (đúng con số
đang bị réo). CLI `python vnstock_brief_watch.py --verify HDC KBC PVC VVS --note "…"` (mã
không có trong sổ ⇒ báo + exit 1). Doctor: ghi chú "Op.CF đã xác minh số thật: …", lời
sửa trỏ `--verify` thay cho "xoá file". Kỳ BCTC mới đổi số ⇒ sổ réo lại để soi lại.
Test `tests/test_brief_watch.py` +8.

# 📰 U76. TIN MỖI GIỜ: THANG CHẤM 0–100, GỬI ≥75 (06/10)

**Vì sao:** user 06/10 — group News Hourly Update lượt nào cũng đầy trần 8 tin (ngưỡng
≥3/5), còn ≥4/5 thì "hơi ít". Thang 1–5 quá thô: bậc 3 gom cả "đáng biết" lẫn "đáng
báo ngay", không có chỗ đứng giữa 3 và 4.

**Đã làm (`vnstock_news_alert.py`):** prompt `SCORE_SYSTEM` chấm `muc_do` 0–100 với 6 dải
mốc (90–100 sốc hệ thống · 80–89 vĩ mô đáng kể = bậc 4 cũ · 70–79 đáng theo dõi CÓ hệ quả
rõ, 75–79 chỉ khi hệ quả cho cổ phiếu VN đã rõ · 50–69 đáng biết không cần báo · 20–49 tin
thường/một doanh nghiệp · 0–19 phi kinh tế), nói thẳng "chỉ ≥75 lên điện thoại, phân vân
chọn thấp". Luật phụ quy đổi: nguồn chính thức 80–100 · mạng xã hội ≤85 · blog ≤65 · trùng
sự kiện trong lô −15 · trùng tin đã gửi ≤40 (`SENT_DUP_CAP` 2→40). `DEFAULT_MIN_SCORE`
3→75. `normalize_min_score`: env/`--min-score` 1–5 là thang CŨ ⇒ ×20 (`.env` ghi `=4` thành
≥80, không thành "≥4/100" gửi gần hết). Ladder (Claude hỏng) điểm từ khoá 4/3/2 ⇒ 80/60/40,
"không tác động" 10 — chỉ từ khoá vĩ mô MẠNH còn vượt ngưỡng. Telegram: `🟠 82/100 ·`, chân
`N tin ≥ 75/100`, biểu tượng theo dải (🔴≥90 · 🟠≥75 · 🟡≥60). `scripts/bsky_eval.py` đếm
"đạt" theo cùng ngưỡng gửi (`HI_SCORE = DEFAULT_MIN_SCORE`), đỉnh ≥90, lạc đề <20.

**Chuyển tiếp:** bản ghi sổ `news_alert_seen.json` cũ mang điểm 1–5 — tin dư chưa gửi lúc
merge KHÔNG bao giờ ≥75 ⇒ rơi im (tự dọn sau 7 ngày); không quy đổi vì tin dư ≤6h, gửi bù
sau merge là tin cũ. `MAX_SEND` giữ 8 (trần an toàn; lượt bắt bù sáng vẫn có thể chạm).

**Đo:** vài ngày sau merge đếm tin/lượt ở log `[news-alert]` + Telegram; vẫn nhiều ⇒
`VNSTOCK_NEWS_ALERT_MIN_SCORE=80`, ít ⇒ `=70`.

**07/10 tối — ĐO THẬT: 75 quá chặt (lỗi prompt của tôi).** 591 tin chấm từ 22:00 06/10 ⇒
0 gửi; điểm CAO NHẤT 72 (việc làm Mỹ thất nghiệp 4,2% · NHNN cảnh báo lạm phát · lợi suất Mỹ
đỉnh 24 năm — đều đáng ≥80 theo chính dải của prompt). Ba câu chồng nhau ("phân vân chọn
THẤP", "75 = dừng việc đọc NGAY", "phần lớn 30–65") nén cả thang xuống. Phân bố: 70–74 ×3 ·
60–69 ×22 · 40–59 ×197 · <40 ×369 ⇒ ngưỡng 70 = 3 tin/23h, **65 = 10**, 60 = 25. User chọn
**65 qua `.env` desktop** (`VNSTOCK_NEWS_ALERT_MIN_SCORE=65`) — đặt ngưỡng theo PHÂN BỐ ĐO
ĐƯỢC, KHÔNG sửa prompt (sửa prompt là phân bố mới chưa đo, 65 hết đúng). Gửi bù tin lỡ:
`run.py news-alert --window-h 30 --max-send 15 --min-score 65` (tin đã chấm nằm sẵn trong sổ,
không chấm lại; `--window-h` cũng nới tuổi tin dư khỏi hết hạn).

**07/10 khuya — đo lại 24h (🖥️ sổ `news_alert_seen.json`, bỏ `dup_of`):** 648 tin chấm, cao nhất 78; ≥75: 2 · ≥70: 4 · ≥65: 13 · ≥62: 28 · ≥60: 31 · ≥58: 35 · ≥55: 72 · ≥50: 124. User thấy 65 ít ⇒ khuyên **60** (~30 tin/ngày): nằm giữa VÙNG PHẲNG 58–62 (28→35) nên lệch vài điểm không đổi lượng tin; 62–64 là cụm dày (13→28), dưới 58 lại vọt (55 = 72, gấp đôi). Đừng xuống dưới 58.

**Lọc trùng trước khi gửi (07/10):** bản xem trước gửi bù ra HAI bản Bloomberg "US 30-Year
Yields…" — nguồn sửa tiêu đề ("Above" → "Back Above") ⇒ hash (ngày|tiêu đề) khác ⇒ 2 bản ghi,
cùng link, cùng chưa gửi (lượt mỗi giờ có guard "ĐÃ GỬI 24h" nên ít lộ; gửi bù gom tin dư
nhiều lượt thì lọt). `mark_duplicate_pending` (chạy sau `expire_leftovers`, trước
`select_to_send`) đánh `dup_of` cho tin chờ trùng LINK (`_norm_link` bỏ scheme/www/query/#)
hoặc tiêu đề gần y hệt (`_titles_match`, cùng thước `deduplicate_news`) với tin đã gửi 24h
hoặc tin chờ điểm cao hơn; `select_to_send` bỏ tin `dup_of`. Cùng SỰ KIỆN khác bài/khác nguồn
KHÔNG gộp (việc của prompt). Test +4. Test: `tests/test_news_alert.py` (+15:
ngưỡng 75 gửi/74 không, `.env`=4 ⇒ 80, kẹp 0–100, dải biểu tượng, ghim prompt).

# 🧭 U75. MỤC ⚠️ RỦI RO THEO PHƠI NHIỄM DANH MỤC (risk_today) — KHỐI CỰC TRỊ VTZ/KBC RỜI BRIEF NGÀY (06/10)

**Vì sao:** khối "Đòn bẩy cao nhất VTZ/VJC/PET · Op.CF thấp nhất KBC/NVL" lặp y
hệt nhiều tháng (user 05/10). Đặc tả `docs/THIET-KE-MUC-RUI-RO.md` (workflow 38
agent) chỉ ra 5 lý do trong code: số BCTC năm đứng yên; phép chọn là xếp hạng
cực trị trên nhóm ổn định; không nối gì của ngày; `enforce_risk_section` chèn
vô điều kiện VÀ `_is_fundamental` xoá luôn dòng model nhắc mã danh mục (EIB,
SSI…); prompt dồn gần hết chỉ dẫn mục cho luật D/E/Op.CF.

**User trả lời (06/10):** câu 1 = **b** — bỏ khối cực trị khỏi brief ngày, in
lại CHỈ khi có kỳ BCTC mới (pha 2 — CODE XONG 06/10 tối, mục "Pha 2" cuối U75); đây
là ĐẢO ghi chú U54 ("mục Rủi ro sinh ra để nói KBC"). Câu 2 = **có** — 16 lệnh
footer tính là phơi nhiễm (tầng R + F).

**Đã làm (đúng luật R1–R17):** `ctx["risk_today"]` đọc env MỘT lần ở
collect_context (guard thuần, pack tái lập chế độ). Guard mới
`enforce_risk_today` nối NGAY SAU `enforce_reference_band_wording` (chuỗi 54 →
55). `enforce_risk_section` có nhánh mới `_risk_section_filter` (gỡ dòng code
theo TIỀN TỐ, giữ ≤1 dòng model đạt R9) — nhờ tiền tố mà chạy chuỗi hai lần ra
y hệt. Giữ nguyên tinh thần 12/06: model KHÔNG BAO GIỜ tự viết D/E, Op.CF, đòn
bẩy hay superlative — mọi dòng có số do `_risk_today_lines` dựng, prompt
("Dữ kiện rủi ro hôm nay") và guard gọi CÙNG hàm. Tầng P: tập trung ≥50% một
cụm + vốn ngoại rút (cụm theo thứ tự tài chính → BĐS → nhóm tuỳ biến → ngành
gốc; **EIB ∈ 'Họ M'** — câu chỉ gán số NN cho CHÍNH ngành đó, không bao giờ
"EIB bị bán -2,783"); biến cố từng mã (NN chính mã ≤ −50 tỷ, −7%/tuần, −3%/phiên
khi bar cuối đúng phiên); GDKHQ mã giữ. M: USD/VND +0,30%, LNH ON +1 điểm, 10Y
+0,15 (as_of ≤5 ngày; gauge chỉ có MỨC không bao giờ in), NN 1D ≤ −1.000 tỷ
khi P1 không bắn. R: GDKHQ chạm lệnh mở, giá quy đổi qua
`adjusted_price(entry×1000)/1000` (sổ lưu NGHÌN — quên ×1000 là trừ 1.500đ vào
giá 25). F: cơ bản CHỈ cho lệnh mới ≤1 ngày, phi tài chính, không đang giữ.
Trần 4 dòng, rỗng ⇒ dòng dự phòng. `enforce_risk_numbers` vòng 'missing' bỏ
qua dòng không có từ khoá cơ bản (bẫy "(Số liệu: EIB D/E=…)" cho ngân hàng).
Universe cơ bản + sự kiện mở thêm danh mục ∪ lệnh mở. brief_watch có event
`risk_section` (dấu vân thân mục) + badge doctor "mục Rủi ro trùng phiên trước
k/n" (dưới sàn mẫu ok kèm n=…). Bỏ M1/M2 (trùng 🔭 của P1b).

**Lệch đặc tả:** hàm canon tên `_fmt_footer_price` vì `vnstock_brief` đã có
`_fmt_rec_price` KHÁC hành vi (1 số lẻ tới 100, cho khối khuyến nghị prompt) —
lưới tách module bắt trùng tên. `_exposure_tickers` gồm MỌI lệnh mở (cả lệnh
ẩn) vì reconcile U74 cần lịch GDKHQ của chúng.

Test `tests/test_brief_risk_today.py` (54, whitelist `--fast`): golden 05/10
khớp NGUYÊN VĂN 2 dòng của đặc tả; chế độ cũ (thiếu khoá / False) ra y hệt 5
dòng brief cũ; idempotent cả hai chế độ; 6 biến thể đi qua toàn chuỗi nguyên
byte + không từ vựng cấm R11. Nghi vấn "reconcile chấm SL cơ học sau GDKHQ"
trong đặc tả đã VÁ ở U74 (không còn là PLAUSIBLE).

**Trạng thái:** VÀO MAIN 06/10 `bcaf013` — 💻 laptop full 3.764 passed / 224s, đã push.
Chờ 🖥️ desktop `git pull` + test FULL trước 18:00.

**Pha 2 — câu 1 = b (CODE XONG 06/10 tối, user gọi "làm việc này đi"):**
- *Updater* ghi KỲ của từng số: `de_period` = kỳ của hàng ratio mà `_best_ratio_row`
  chọn (`row_period_label`: `report_period`, hoặc `yearReport`+`lengthReport`, quý 5
  = năm); D/E lấy từ bảng cân đối (ngân hàng) ⇒ `de_period=None` (không sinh sự kiện,
  vốn bị loại khỏi bảng). `ocf_period` từ `_annual_operating_cf_period`: "2025" khi lấy
  dòng năm thuần hoặc đủ 4 quý, "2026-LK3" khi chỉ cộng được 3 quý (tháng 1 năm sau —
  trước đây con số này mang nhãn như số NĂM mà thật ra là lũy kế 3 quý). Hai cột KHÔNG vào
  `_has_new_cols` (khỏi refetch giữa tuần; lượt `--force` T7 tự điền).
- *Sổ kỳ* `_meta/fundamentals_periods.json` (`vnstock_fund_periods.fold`, CHỈ updater
  ghi, nằm CẠNH `FUND_PATH` ⇒ test chuyển FUND_PATH là sổ đi theo): lần đầu thấy mã =
  MỐC (`first_seen=None`, không phải sự kiện — nếu không, lượt đầu báo "kỳ mới" cho cả
  nghìn mã); kỳ MỚI hơn ⇒ `prev` + `first_seen`; cùng kỳ số khác ⇒ sửa số; kỳ CŨ hơn
  (nguồn trả nhầm hàng) ⇒ bỏ qua.
- *Brief*: collect_context (risk_today + `VNSTOCK_BRIEF_FUND_PERIODS`) đọc sổ ⇒
  `ctx["fund_period_news"]` (sự kiện ≤45 ngày, chưa phiên chiều nào xét hoặc xét đúng
  phiên này). Brief CHIỀU ghi `_meta/fund_period_announced.json` ⇒ mỗi kỳ mới xét ĐÚNG
  MỘT phiên chiều, chạy lại cùng phiên (A/B, --export-pack, /brief-close) ra y hệt;
  brief sáng chỉ đọc. Gọi collect_context chỉ có generate_brief + build_pack (+ train
  "morning") ⇒ không có đường xem thử nào "tiêu" sự kiện.
- *Guard*: `_risk_period_lines` (trong `enforce_risk_today`, chuỗi vẫn 55) in ≤1 dòng/chỉ
  số, tiền tố `- Kỳ BCTC mới` (vào `_RISK_LINE_PREFIXES` ⇒ idempotent), NGOÀI trần 4
  dòng, sau dòng phơi nhiễm/model. Bắn khi kỳ mới CHẠM bảng: mã trong bảng có kỳ mới,
  hoặc mã RỜI bảng vì kỳ mới (bảng "trước" dựng bằng số kỳ trước — `_risk_extremes`, luật
  DUY NHẤT dùng chung với khối cũ). Chỉ in nửa bảng có kỳ mới (D/E hoặc Op.CF), không lặp
  nửa đứng yên. Kỳ trong sổ LỆCH kỳ của số đang dùng ⇒ im. Prompt "Dữ kiện rủi ro hôm
  nay" có cùng các dòng. Chế độ cũ không đổi một byte (test).
- Test `tests/test_fund_periods.py` (43, whitelist `--fast`); conftest thêm lưới chuyển
  FUND_PATH/FUND_HISTORY_DIR/sổ kỳ về tmp cho MỌI test (họ bài học U17); sổ vào
  `_MUST_BE_ATOMIC`. Soi sổ: `python vnstock_fund_periods.py`.
- **Khi nào thấy dòng đầu tiên:** lượt `fundamentals` T7 10/10 chỉ dựng MỐC. Op.CF đổi kỳ
  sớm nhất tháng 1/2027 (lũy kế 2026); D/E tuỳ hàng ratio VCI trả (năm ⇒ quý 1–2/2027;
  có hàng quý/TTM ⇒ theo quý) — xem phân bố kỳ trong lệnh soi sau T7.

**Còn:** ngưỡng R4–R7 chỉ chỉnh khi sổ brief_watch đủ mẫu.

# ⏸ U74. LỆNH MỞ XUYÊN GDKHQ BỊ CHẤM "SL" GIẢ — TREO KHI KHO CHƯA REBASE, QUY ĐỔI THEO HỆ SỐ ĐO ĐƯỢC KHI ĐÃ REBASE (06/10)

**Bằng chứng (đọc code 06/10):** GMD BUY @78 mở 24/09, thưởng 50% GDKHQ 07/10.
`reconcile_recommendations` so entry/TP/SL (cơ sở LÚC MỞ) với bar kho, không
chỗ nào quy đổi. Sau GDKHQ: bar thô ~52 lọt kho ⇒ "sl" ngay đêm đó; hoặc cửa gác
lệch cơ sở chặn nối tới khi rebase tay ⇒ mọi bar từ ngày mở bị chia 1.5 ⇒ "sl" ở
bar đầu. Đóng là VĨNH VIỄN, và win-rate thật chảy vào kiểm định/decay chiến lược.
Thêm hai lỗ: cache sự kiện xoá sự kiện 2 ngày sau GDKHQ (không ai nhớ mã từng đổi
cơ sở), và universe sự kiện = VN30 ∪ mã thanh khoản — KHÔNG phủ mã lệnh mở (GMD
lọt vào nhờ may).

**User chốt 06/10: "A trước, B sau"** (A = đóng/treo trung tính, B = quy đổi mốc
bằng hệ số rebase). Làm cả hai trong một lượt, nhưng B KHÔNG ghi đè sổ như đề
xuất ban đầu (móc vào script rebase): nếu ghi `entry/TP/SL` lúc rebase thì
`--restore` bản sao lưu không khôi phục theo. Thay vào đó NEO cơ sở:
* `rec_basis_anchor` (bảng mới trong `brief_memory.db`): close kho tại bar ngày
  mở lệnh — chụp ngay ở `emit_recommendations` (kho chắc chắn cùng cơ sở với
  entry), hoặc lượt reconcile đầu tiên khi CHƯA có sự kiện; lần chụp đầu thắng.
* Mỗi đêm: f = close kho hôm nay tại đúng bar neo / close lúc chụp.
  |f−1| > `vnstock_basis_guard.TOL` (1,2%) ⇒ kho ĐÃ rebase ⇒ chấm với mốc × f,
  giá thoát ÷ f về cơ sở cũ (pnl đúng trên entry trong sổ) — bắt được cả rebase
  cả-chuỗi không có sự kiện nào trong sổ. Restore ⇒ f về 1 ⇒ tự quay lại treo.
* Sự kiện ĐÁNG KỂ (lệch giá tham chiếu > TOL theo `corp_ratio`; không đọc được
  tỉ lệ ⇒ đáng kể; ĐHĐCĐ bỏ qua) trong (ngày mở, hôm nay] mà f≈1 ⇒ chỉ chấm bar
  TRƯỚC GDKHQ; không chạm ⇒ TREO. Không có neo ⇒ treo không chấm gì. Hai ngày
  GDKHQ trong một cửa sổ mà kho đã rebase ⇒ treo (một f không đủ).
* Treo quá hạn + `STALE_GRACE_DAYS` ⇒ đóng `corp_action`, exit/pnl NULL (cùng họ
  "stale": `recommendation_performance` lọc `pnl_pct IS NOT NULL`, reflection chỉ
  học tp/sl/expire). Telegram "Đóng hôm nay" in "không chấm" thay vì "+0.00%".
* Sổ sự kiện đã qua `_meta/corp_actions_ledger.json`: `refresh_upcoming` ghi sự
  kiện bị cắt vì ĐÃ QUA (lấy từ cache cũ, < cutoff); sự kiện tương lai biến mất
  sau fetch thành công = bị huỷ, không ghi. `vnstock_events.price_events()` đọc
  sổ ∪ cache theo `_META` (conftest đã chuyển `_META` sang tmp cho mọi test).
* `_events_universe(extra_tickers=)` (chữ ký đúng đặc tả mục Rủi ro) +
  `_maybe_refresh_events` truyền mã lệnh mở; `_open_rec_tickers()` không mở DB
  khi sổ chưa có (sandbox — bản đầu đẻ `brief_memory.db` rỗng, đã chặn + test).
* Công tắc `VNSTOCK_REC_GDKHQ_HOLD=0` ⇒ chấm như cũ. Log reconcile in thêm
  `held_gdkhq=` và `corp_action=`.

Test `tests/test_rec_corp_action.py` (25, whitelist `--fast`): 10 ca hành vi đỏ
trên code cũ đúng lý do (sl/tp giả, không treo). Full so `main`: cùng tập fail
(thiếu `vnstock` trong container), pass +25.

**Còn hở:** máy tắt nhiều đêm ngay trước GDKHQ ⇒ bar trước GDKHQ chưa chấm kịp,
lệnh có thể bị treo rồi đóng trung tính thay vì chạm TP/SL thật (mất mẫu, không
ghi số sai). Lệnh mở trước bản vá mà lượt reconcile đầu tiên sau khi pull đã thấy
sự kiện ⇒ không có neo ⇒ treo rồi trung tính. Footer "Khuyến nghị đang mở" chưa
ghi "⏸ treo GDKHQ" (đặc tả mục Rủi ro R6 lo phần cảnh báo).

# 🔢 U73. `corp_ratio` ĐỌC SÓT HAI DẠNG TIÊU ĐỀ VCI — GMD THƯỞNG 50% IN CẢNH BÁO SUÔNG, "1,000" RA 1.0 (06/10)

**Bằng chứng (brief chiều 05/10):** `parse_event` trả None cho
`"Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%"` (GMD, GDKHQ 07/10 — đang
mở BUY @78) và `"Trả cổ tức bằng tiền mặt - Đợt 2 2025 - 1,000 VND"` (MWG) ⇒
`enforce_exdate_levels` chỉ in "giá tham chiếu tự điều chỉnh", mất con số. Gốc:
`_STOCK_WORDS` chỉ có "thuong co phieu" (VCI viết NGƯỢC); nhánh tiền không bắt
"<số> VND". Bẫy ngầm thứ ba: `_to_number` coi mọi ',' là thập phân ⇒ "1,000"
(VCI in số kiểu EN) ra **1.0** — "1,000 đồng/CP" qua nhánh cũ đã ra cổ tức 1đ.

**Vá:** "cổ phiếu thưởng" so khớp CÓ DẤU (`_BONUS_ACCENTED`, theo đặc tả R18
trong `docs/THIET-KE-MUC-RUI-RO.md`) — bỏ dấu thì "thưởng" trùng "thường" (cổ
phiếu PHỔ THÔNG: niêm yết bổ sung, hoán đổi "tỷ lệ 1:1.2" sẽ thành thưởng
120%); tiêu đề không dấu "co phieu thuong" cố ý trả None. Nhánh tiền bắt số
tiền là trọn một vế giữa dấu gạch hoặc đứng cuối tiêu đề (đứng SAU nhánh %,
loại "mệnh giá X đồng"). `_to_number` một luật cho cả hai dấu (đủ hai dấu ⇒
dấu sau là thập phân; một loại ⇒ nhóm 3 chữ số là nghìn). GMD 78,000 ⇒ ≈
52,000. Test ở `test_corp_ratio.py` + `test_brief_exdate_guard.py`. Bản đầu
(`dea48af`) thêm "co phieu thuong" vào `_STOCK_WORDS` + đổi tên trong `_norm`;
đổi sang R18 khi merge main 06/10 vì đặc tả chốt ngược lại.
Còn hở: khối "Khuyến nghị đang mở" Telegram nối NGOÀI guard nên dòng GMD @78
không mang ⚠️ GDKHQ; sổ lệnh (`vnstock_train` chấm TP/SL) không quy đổi qua
ngày GDKHQ — chưa soi, chờ user quyết.

# 🌐 U68. BÁO NƯỚC NGOÀI + PHÂN TÍCH TỪ X CHO CẢNH BÁO GIỜ — KHẢO SÁT 4 LENS + PHẢN BIỆN, BLUESKY LÀ ĐƯỜNG CHÍNH, X CHỈ KHI CÓ KEY (02/10 trưa)

**Hỏi:** "có cách nào lấy tin từ báo nước ngoài, hoặc tin phân tích quan trọng từ
X". **Cách làm:** workflow 4 lens song song (feed báo nước ngoài · X/mạng xã hội ·
nối vào code · rủi ro pháp lý) → 8 claim × 2 phản biện → tổng hợp. Bước tổng hợp
và 9/16 phản biện chết vì chạm giới hạn phiên; đọc journal rồi tự tổng hợp. WebSearch
chạy được từ sandbox, WebFetch/curl tới mọi host feed bị proxy 403 ⇒ **không URL nào
được fetch thật**, tất cả là ứng viên chờ `--diag` trên desktop.

**Ba chỗ phản biện LẬT lens đầu (đáng nhớ):**
1. **WSJ `feeds.a.dj.com` ĐÓNG BĂNG từ 01/2025** — vẫn HTTP 200, XML hợp lệ, ~20
   item nhưng tin cuối 24–27/01/2025 ⇒ job cửa sổ 3h đọc nó im lặng mãi (đúng kiểu
   lỗi "feed sống giả"). Host mới `feeds.content.dowjones.io/public/rss/<name>`
   (cùng host MarketWatch Top đang dùng). Bản đầu của tôi ghim host cũ — đã sửa.
2. **Bloomberg CÓ RSS sống**: `www.bloomberg.com/feeds/<markets|economics|politics|
   technology|industries>/news.rss` (host cũ `feeds.bloomberg.com` 301 sang), đo
   15/09/2026 20 item mới 0,01 ngày. Lens đầu nói "chết" là sai.
3. **Bing News RSS vẫn chạy** (`bing.com/news/search?q=…&format=rss`, cần UA trình
   duyệt + follow 302) — để làm fallback Google News khi cần, chưa dùng.
Chưa kiểm được: 5 feed chính thức (Fed/BLS/BEA/ECB/BoJ) là URL lâu năm nhưng không
có bằng chứng 2025–26 ⇒ `--diag`.

**Số liệu X/mạng xã hội (09–10/2026, nguồn trong journal):** X API không còn Free/
Basic/Pro cho người mới từ 06/02/2026, trả theo lượt: $0,005/post đọc, $0,01/profile,
nạp trước tối thiểu $5, trần 3M đọc/tháng; Basic $200 cũ bị ép chuyển 06/2026 ⇒
20–30 tài khoản đọc mỗi giờ với `since_id` ≈ $15/tháng ở 100 post mới/ngày, ≈ $35 ở
25 tài khoản. twitterapi.io $0,15/1.000 tweet (tối thiểu $0,00015/call) ⇒ ≈ $1–5/
tháng — vùng xám ToS X nhưng án X v. Bright Data (05/2024) bác yêu sách hợp đồng
chống scrape ⇒ rủi ro nằm ở nhà cung cấp, không ở người mua; dễ chết khi X đổi
chữ ký. xAI Grok `x_search` từ 21/09/2026 tính $5/1.000 post ĐỌC (kể cả post cha/
quote) + $10/1.000 profile + token — là bản tóm tắt, không phải tin để chấm ⇒ loại
cho job giờ. Nitter/xcancel: C&D của X 24–26/08/2026, repo archive, 09/2026 còn 1
instance sống ⇒ loại. RSSHub twitter route cần cookie tài khoản thật ⇒ loại. Reddit
RSS tắt 13/11/2026 ⇒ không xây. **Bluesky**: AppView công khai `public.api.bsky.app`
không auth, `getListFeed` một call cho cả danh sách, 3.000 req/5′/IP, đúng thiết kế
giao thức mở, nhiều chuyên gia vĩ mô đã có (Timiraos, Sahm, Furman, El-Erian,
Pettis, Blas…) nhưng Setser/Donnelly/sell-side vẫn chủ yếu trên X ⇒ Bluesky = lõi
miễn phí, X = bổ sung trả tiền khi user muốn.

**Báo VN dịch tin lớn nhanh tới đâu (lens repo-fit đo từ id URL CafeF):** FOMC
01:00 VN lên CafeF sau 25′ (30/07/2026), 63′ (18/06/2026), 43′ (20/03/2025) ⇒ feed
nước ngoài chỉ hơn về TỐC ĐỘ trong khung 20:00–06:00 (ngoài giờ gửi!) và về
PHÂN TÍCH; dữ liệu nhỏ (ISM, JOLTS) báo VN dịch chậm hoặc không ⇒ đó là chỗ BLS/
Fed feed có giá. Hệ quả: **cửa sổ bắt bù qua đêm** (lượt 07:00 nhìn lại tới lượt
22:00 hôm trước) quan trọng hơn số feed.

**Đã làm (commit `18b1956` + commit này, 71 test):**
- `effective_window_h` + `covered_until` trong marker (chỉ tiến khi có nguồn trả
  tin), trần 36h (`VNSTOCK_NEWS_ALERT_MAX_CATCHUP_H`); lô chấm nở theo cửa sổ (≤×2
  trần 30) và cap theo nguồn `cap_per_source` 6 tin/nguồn (nở ≤×3).
- `_ALERT_FEEDS` 20 nguồn riêng cho cảnh báo (không vào `_FEEDS` ⇒ brief không
  đổi): 11 RSS báo lọc `_relevant_en`, 3 chính thức không lọc (`kind=official`),
  6 Google News `when:2d` (`gnews_source` tách "– Báo" khỏi tiêu đề). Bỏ NYT/BBC/
  Guardian (trùng + nhiễu). Feed tiếng Anh trong `_FEEDS` (CNBC/MW/Yahoo) nay cũng
  qua `_relevant_en`.
- `_relevant_en` so BIÊN TỪ (regex, không bắt turmoil/corporate/software/Bond film);
  bỏ "bond" trần, giữ "bonds"/"bond market"/"bond yields".
- `collect` có tường `VNSTOCK_NEWS_ALERT_FETCH_BUDGET_S`=45s (`as_completed(timeout)`
  + `shutdown(cancel_futures)`), 12 worker; nguồn chưa về đếm 0 và in tên.
- `bsky_source` (List URL/at:// hoặc handles; ≤3 bài/người, bỏ <60 ký tự) và
  `x_source` (provider `twitterapi` advanced_search một call `from:a OR from:b`
  `-filter:retweets -filter:replies since:`; provider `official` search/recent với
  `since_id` lưu `_meta/news_alert_x_state.json`), bật bằng env
  `VNSTOCK_NEWS_ALERT_BSKY_LIST|BSKY_HANDLES|X_HANDLES|X_PROVIDER` + key
  `TWITTERAPI_IO_KEY`/`X_BEARER_TOKEN`; không env = không có gì. `_iso_dt` hiểu
  ngày kiểu Twitter. Prompt: `Loại: nguồn chính thức` ⇒ dữ liệu 4–5; `Loại: bình
  luận chuyên gia` ⇒ chấm theo giá trị phân tích, tối đa 4.
- `run.py news-alert --diag` / `vnstock_news_alert.py --diag`.

**Đo thật 02/10 tối (🖥️ desktop, `14ad320`):** `--fast` **2.862 passed / 207s**;
`news-alert --diag` **30/32 nguồn** ✅ — Bloomberg Markets 10 tin/3h, FT 5, CNBC World 5,
WSJ host mới (`feeds.content.dowjones.io`) sống, cả 6 Google News 45–100 tin, Fed
monetary mới nhất 17/09 01:00 (đúng FOMC 16/09 giờ Mỹ ⇒ quy đổi tz đúng). Xử lý ngay:
(1) ❌ investingLive/ForexLive — forexlive.com chuyển hướng investinglive.com, không
RSS ⇒ `enabled: False`, thử ứng viên bằng `--diag-url`; (2) ❌ BLS — chặn script ⇒
tắt, thay "GN US data" (`"jobs report" OR payrolls OR "consumer price index" OR "PCE
inflation" OR "retail sales"`); (3) Báo Chính phủ + Nikkei Asia ✅ mà "mới nhất —" ⇒
KHÔNG đọc được ngày ⇒ không bao giờ qua cửa sổ giờ, và Báo Chính phủ còn bị
`news_feeds.refresh` LOẠI khỏi cache brief từ 07/2026 (cutoff theo `_date_sort` rỗng —
diag 08/07 chỉ đếm tin liên quan nên không lộ). Vá: `_parse_dt_loose` (dd/mm/yyyy,
"Thứ …, dd/mm/yyyy - HH:MM", yyyy/mm/dd, offset có dấu cách) + `_norm_tz_words`
("GMT+7" — `parsedate_to_datetime` KHÔNG ném mà lặng lẽ BỎ tz, đúng nhờ may khi máy ở
VN); `parse_feed` ghi `_pub_raw` khi không đọc được ⇒ `--diag` in chuỗi gốc; feed
thật sự không có ngày ⇒ `take_undated`: lượt đầu GHI MỐC mọi tin (không chấm), từ lượt
sau tin chưa thấy = tin mới với `_published_at` = giờ thấy. Ghi chú thêm: `rss:cnbc-markets`
(id 20910258, thật ra feed Economy) mới nhất 28/09 và `rss:yahoo-finance` mới nhất 23/09
⇒ hai feed của `_FEEDS` gần như đứng — vô hại (rơi ngoài cửa sổ) nhưng là ứng viên thay
cho brief, chưa đụng.

**Lượt diag thứ hai (02/10 ~20:20, `d8ebf69`):** Nikkei xác nhận `(feed không có thẻ ngày)` ⇒ `take_undated` lo. Báo Chính phủ "mới nhất 2026-02-10" ⇒ feed viết THÁNG/NGÀY kiểu Mỹ (ASP.NET `10/2/2026 11:56 AM`), bộ đọc mới hiểu ngày/tháng ⇒ `_pick_day_month`: chọn cách hiểu gần `now` nhất, không quá 1 ngày tương lai, hoà thì ngày/tháng; đọc AM/PM. `_pub_raw` nay LUÔN giữ (≤60 ký tự) để `--diag` in chuỗi gốc khi tin mới nhất cũ hơn 7 ngày. FT Markets ✅ 25 tin lúc 20:07 rồi ❌ 0,4s lúc 20:20 ⇒ nghi chặn tạm khi gọi dồn, CHƯA tắt; `--diag` nay thăm HTTP khi nguồn ❌ (mã, content-type, chuyển hướng, 70 ký tự đầu). "GN US data" 68 tin/3h đúng ngày NFP (19:30 VN) — cap 6 tin/nguồn giữ lô.

**Lượt diag thứ ba (04/10 ~00:10, `838051d`): 31/31 ✅.** Báo Chính phủ mới nhất 03/10 18:47 (vá M/D ăn), FT trở lại 25 tin (xác nhận chặn tạm, không tắt), CNBC Markets chạy lại (03/10). Yahoo Finance `rssindex` ĐỨNG từ 23/09 (chuỗi gốc `2026-09-23T01:52:26Z`) — nằm trong `_FEEDS` của brief, không còn đóng góp tin nào; ứng viên gỡ, chưa đụng. Fed monetary bị gắn "cũ hơn 7 ngày" là báo động giả (tin cuối = FOMC 16/09) ⇒ bỏ cờ cũ cho `kind=official`.

**Dry-run đầu tiên (04/10 01:12, desktop, `f1b074e`):** 31 nguồn · 1.091 tin liên quan · 8 tin không ngày (Nikkei…) ghi mốc · 21 tin mới/3h · Claude Code chấm 21/21 trong 29s, **$0,11/call với Opus mặc định** (`VNSTOCK_CLAUDE_CLI_MODEL`) — 8 tin ≥3 (2×4/5: lợi suất Mỹ sau NFP tháng 9 nóng, GDP VN quý gần 10%). Lượt giờ có tin ≈ 16 call/ngày ⇒ ~$1,5–1,8/ngày quy đổi, ăn chung hạn mức gói Claude với phiên code ⇒ khuyên A/B `VNSTOCK_NEWS_ALERT_CLI_MODEL=claude-sonnet-5-5` (chấm tiêu đề là việc phân loại nhẹ). Định dạng: URL Google News ~250 ký tự để trần chiếm 3–4 dòng/tin trên điện thoại ⇒ tiêu đề thành `<a href>` (`send_message(allow_links=True)`, brief vẫn TẮT link — LLM không được tự chèn), giờ đăng khác ngày tin nhắn kèm `dd/mm` (lượt bắt bù 36h).

**A/B model 04/10 01:34 (dry-run, `f415818`):** `VNSTOCK_NEWS_ALERT_CLI_MODEL=claude-sonnet-5-5` ⇒ 16 tin mới chấm trong **13s · $0,04** (Opus 22′ trước: 21 tin · 29s · $0,11). 7 tin chung trong top 8: 5 trùng điểm, 2 lệch ±1 (GDP VN quý gần 10%: Opus 4 → Sonnet 3; sửa Luật Chứng khoán kỳ họp 10: 3 → 4). `tac_dong` Sonnet bớt gán mã gượng (thuế hộ kinh doanh không còn "lợi MWG, FRT"); Sonnet cho 3/5 một bài blog SchiffGold ("Fed bỏ qua việc làm yếu") — nguồn yếu. Kết luận: Sonnet đủ cho việc chấm tiêu đề, rẻ ~2,75× ⇒ khuyên đặt trong `.env` desktop; code KHÔNG đổi default (giữ một nguồn model ở `vnstock_claude_cli`). Dấu cách giữa URL trong output dán từ PowerShell là ẢO GIÁC console (dòng có emoji 2 ô bị cắt lệch khi copy) — `_safe_href` không cho khoảng trắng, có thì đã không ra `<a>`.

**Lượt gửi thật đầu tiên (04/10 01:38, Sonnet):** 15 tin mới · 11s · $0,03 · gửi 8 tin, `message_id=302`; Telegram copy ra "Tiêu đề (URL)" = text-link đã gắn. Soi 8 tin ⇒ 3 vá (`news-alert` sau `97c46b2`): (1) **prompt bị cắt câu** — khi chèn luật nguồn chính thức/mạng xã hội, ví dụ "(vd ngân hàng lớn mất thanh khoản)" rơi xuống SAU luật mạng xã hội, câu "doanh nghiệp chỉ lên 4 khi…" nối thẳng vào "NGUỒN CHÍNH THỨC" (test ghim thứ tự); (2) luật **BÀI Ý KIẾN/BLOG** tối đa 3, chỉ bình luận lại = 2 (SchiffGold "Fed sẽ bỏ qua việc làm yếu" được 3/5 cả hai model, mâu thuẫn tin "việc làm nóng" cùng lô); (3) **chống gửi lại cùng sự kiện qua các giờ** — sổ chỉ khử theo hash ngày+tiêu đề nguyên văn, `deduplicate_news` chỉ trong MỘT lô ⇒ Fed quyết định sẽ về mỗi giờ từ Reuters/CNBC/VnExpress/Google News. Nay ≤25 tiêu đề đã gửi 24h đứng đầu khối user (`### ĐÃ GỬI`, luật: cùng sự kiện ⇒ tối đa 2 trừ diễn biến mới) + guard deterministic `cap_sent_duplicates` (tiêu đề gần trùng, thước `deduplicate_news` 0,85 ⇒ trần 2, cả đường ladder). Log: `· đối chiếu N tin đã gửi 24h` / `hạ N tin trùng tiêu đề…`. Chưa đếm: bài theo sau KHÁC tiêu đề chỉ có luật prompt chặn — xem Telegram vài ngày rồi mới quyết có cần guard sự kiện không.

**`bsky_make_list.py --check` thật (04/10, desktop):** 33/33 handle ⭐ tồn tại, tên khớp (không ⚠️ giả mạo). Nhưng (a) 6 tài khoản NGỪNG đăng từ 2025 — Tracy Alloway, Mai Nguyen (5 follower/7 bài, nghi không phải người thật đang dùng), Khac Giang, Javier Blas, Ole Hansen, Ana Swanson ⇒ bỏ ⭐ (vô hại nhưng làm List công khai trông "chết"); (b) 3 tài khoản HÃNG TIN Reuters (106K bài) / Bloomberg (30K) / Nikkei Asia (26K) đăng hàng chục bài/giờ ⇒ `_social_trim` ≤3 bài/người rồi `cap_per_source` 6 bài MỚI NHẤT cho cả nguồn `bsky:analysts` ⇒ hãng tin chiếm hết suất, chuyên gia bị đẩy ra; tin của họ đã về qua RSS/Google News ⇒ đánh `⛔` (cột đầu bảng), `parse_md` bỏ qua kể cả `--all`/`--include-low`. Còn 24 ⭐. Chưa đo: số bài/giờ thật của 24 người — nếu `--diag --sources bsky` thường xuyên > 6 bài mới/giờ thì tách trần riêng cho nguồn social.

**24/7 TỪ 04/10 (user chốt):** khung 07–22h T2–T7 bỏ — đêm VN là giờ làm việc Mỹ (Fed, số liệu 8:30 ET = 19:30/20:30 VN, chuyên gia Bluesky) nên bản cũ dồn mọi thứ vào lượt 07:00. `DEFAULT_HOURS=(0,23)`, `DEFAULT_DAYS=(1,7)`; task: Weekly cả 7 ngày 00:00 + lặp 1h trong 23h01′ (`-NewsAlertDays`). Hệ quả: ~24 lượt/ngày thay 16 × 6 ngày (Sonnet ~$0,03–0,04/lượt có tin ⇒ ~$0,7–0,9/ngày quy đổi, ăn chung hạn mức gói Claude); Telegram kêu cả đêm (chưa có giờ im lặng — đề xuất `disable_notification` 23–06h nếu user muốn); máy TẮT/NGỦ thì không chạy — bật lại `StartWhenAvailable` chạy một lượt, cửa sổ bắt bù lo phần đã lỡ; badge doctor réo `>3h không lượt` cả đêm nếu máy tắt. Phải 🖥️ merge code VÀ chạy lại `setup_scheduled_tasks.ps1` — chỉ đăng ký lại task mà không merge thì code vẫn gác 07–22h T2–T7, lượt đêm in "ngoài khung giờ" rồi thoát.

**Chọn ⭐ bằng số liệu (04/10, user: "bạn tự đánh giá"):** `scripts/bsky_eval.py` thay việc đọc tay một tuần — lấy bài GỐC (bỏ repost/trả lời/bài ghim) `--days` 7 của cả bảng trừ ⛔ (86, gồm 24 ⭐), ≤15 bài ≥60 ký tự mới nhất/người, chấm theo lô 40 bằng `na.score_items_cli` (ĐÚNG prompt cảnh báo, `Loại: bình luận chuyên gia`), luật `verdict`: ≥2 bài ≥3/5 và ≥20% đạt ⇒ ⭐; >10 bài/ngày mà <15% đạt ⇒ ồn (chiếm suất 6 bài/lượt); 0 bài ≥3 trên ≥5 bài chấm hoặc ≥50% bị chấm 1 ⇒ bỏ/hạ ⭐; 0 bài gốc ⇒ im. Một tuần mẫu chưa có FOMC — phóng viên Fed ít đăng (Colby Smith, Timiraos) có thể ra "im" dù đáng giữ: phán quyết cuối do Claude đọc bảng, không áp máy móc. Test `tests/test_bsky_eval.py` (17, whitelist). **Kết quả lượt đầu 04/10 (desktop, 1.206 bài gốc, 541 chấm, 14 call ~$0,81, ~5′):** luật đề xuất 10 THÊM / 3 HẠ / 18 BỎ / 24 IM; Claude chốt +8/−8 ⭐ (bỏ qua luật ở Carl Quintanilla — 24 bài/ngày toàn chuyển tin AP, sẽ chiếm suất — và Michael Derby — 60% lạc đề; hạ thêm 5 tài khoản im >30 ngày + Wolfers; GIỮ Sahm dù mẫu 2 bài lạc đề) và ⛔ 17 khỏi List đọc thử (giữ Bonnie Glaser mẫu 2 bài). Bài học: luật `verdict` cho THÊM trước khi xét lạc đề ⇒ người 60% lạc đề vẫn lọt nếu có 3 bài trúng — chấp nhận vì Claude đọc bảng, nhưng nếu tự động hoá thì phải đảo thứ tự. `bsky_make_list.py --prune` (mới): gỡ thành viên ngoài tập đích, hỏi trước, chỉ xoá listitem thuộc repo của phiên.

**Lượt TỰ ĐỘNG đầu tiên 24/7 (04/10, desktop):** 20:00 bắt bù 20h — 171 tin mới, lô chấm trần 60 (≤18/nguồn, phần dư rơi theo cửa sổ), 33s · $0,10, đối chiếu 8 tin đã gửi, gửi 8 (`message_id=303`); 21:00 — 32 nguồn (Bluesky vào), 16 tin mới/3h, 15s · $0,03, đối chiếu 16 đã gửi, gửi 8 (`304`), `LastTaskResult 0`. Lỗ hổng lộ ra: 21:00 có 16 tin mới mà vẫn gửi đủ 8 ⇒ phần lớn là tin DƯ của lô 20:00 (đạt ≥3 nhưng hết suất) — `select_to_send` không xét tuổi nên tin 15–20h tuổi rỉ ra 8 tin/giờ suốt mấy lượt sau. Vá: `expire_leftovers` — tin dư chỉ được gửi bù khi ≤ max(cửa sổ lượt này, 6h) tuổi (`VNSTOCK_NEWS_ALERT_LEFTOVER_MAX_AGE_H`), quá thì đóng dấu `expired_at` (không đếm lại), log `bỏ N tin dư cũ hơn Xh`; lượt bắt bù vẫn gửi tin 20h tuổi LẦN ĐẦU thấy. Theo dõi tiếp: lượt thường (không backlog) gửi bao nhiêu tin/giờ — nếu đều 6–8 thì nâng `VNSTOCK_NEWS_ALERT_MIN_SCORE=4`.

**List Bluesky TẠO XONG 04/10 (🖥️ desktop):** 24/24 (lượt đầu 23 + Jason Furman lỗi `HTTP 502 UpstreamFailure` ở `createRecord` — lỗi tạm phía Bluesky; chạy lại script dùng lại List, thêm đúng 1). URL List nằm ở `.env` desktop (`VNSTOCK_NEWS_ALERT_BSKY_LIST`). `--diag --sources bsky`: ✅ thô 37 · lọc 37 · 3h 0 (sáng CN VN = tối T7 Mỹ) · 2,4s; giờ `createdAt` Z được đổi về giờ địa phương đúng (`_parse_pubdatetime` → `astimezone()`). Ba vấp khi đăng nhập, đều đã vá trong script: (1) gõ thiếu chữ cuối handle `…bsky.socia` ×3 ⇒ 401 chung chung trông như sai mật khẩu → nay `resolveHandle` TRƯỚC khi hỏi mật khẩu + gợi ý `.bsky.social`, tên trần tự thêm đuôi; (2) ô `getpass` ẩn hẳn, không biết đã dán được gì → 401 nay in độ dài + đúng/sai dạng `xxxx-xxxx-xxxx-xxxx` (không lộ giá trị) + hướng `Read-Host -AsSecureString` (hiện `*`, đếm 19); (3) gõ tay bỏ dấu `-` (16 `*`) → tự chèn lại khi bỏ `-`/khoảng trắng ra đúng 16 ký tự a-z0-9.

**Chưa kiểm / bẫy còn mở:** (a) mọi URL `_ALERT_FEEDS` + Substack/Cloudflare 403 với
TLS của `requests` — `--diag` quyết; (b) hình dạng JSON của twitterapi.io
(`tweets[].createdAt` kiểu Twitter, `author.userName`) viết theo tài liệu, chưa gọi
thật; (c) Google News từ IP VN có thể gặp consent interstitial — `--diag` sẽ ra
0 tin, khi đó đổi `hl/gl/ceid` sang `vi/VN`; (d) `covered_until` đọc marker chung
qua Dropbox nhưng chỉ desktop chạy nên nhất quán; laptop chạy tay `--force` sẽ làm
desktop bỏ bắt bù lượt sau — đừng chạy tay ở laptop ngoài `--dry-run`; (e) chưa
có khử trùng CHÉO ngôn ngữ bằng code (prompt lo) — đếm `dup` một tuần rồi quyết.

# 🔭 U72. BRIEF 3 KHUNG — KẾT QUẢ P0 TRÊN KHO THẬT + P1a CHẠY BÓNG (05/10)

**P0 (user chạy 🖥️ 05/10):** kho VNINDEX 683 phiên từ 02/01/2024 · breadth tái dựng vs ctx đã in
lệch TB 0.8 điểm % / 58 phiên (0.4 / 26 phiên giai đoạn) · floor replay khớp floor đã in 51/58 (lệch
do momentum thật có tin/vĩ mô) · brief THẬT 01/06–02/10: 58 brief, Stance đổi 23, đảo 6; nhãn header
đổi 48/87 phiên · hệ mới: ép đổi 7, đảo 0 · vùng phẳng trên kho lặp đúng Finhay (MA8–10w/30–40w
không TĂNG 08–09, MA12w/50w có) ⇒ GIỮ tham số. Script P0 in trống registry vĩ mô vì registry lồng
dưới `indicators` — đã sửa.
**Phát hiện mới — allocation:** band B4 15% → B3 30% ngày 27/08 (1,831.56) → B4 22/09 → B3 trộn ~28%
(bản 02/10 ghi 05/10 00:10). Kẹp v1 đã duyệt chỉ chặn khi trung hạn GIẢM/🚨 ⇒ chặn được cú 05/10
nhưng KHÔNG chặn 27/08 (ĐI NGANG, 🚨 tắt). Đề xuất câu 14 (B): chỉ tăng % cổ phiếu khi trung hạn
TĂNG, tạm tới P3 — **chờ user chốt trước P1b**.
**P1a (code, chạy bóng — brief KHÔNG đổi):** `vnstock_horizons_state.py` — đọc kho dùng chung với
script P0 (`read_ticker/load_vnindex/breadth_history/score_inputs`), `_meta/horizon_state.json`
{inputs, published append-only}, `fold()` gấp từ input đã lưu (close-only cho lịch sử, điểm cho
phiên có chấm), `update()` cổng ghi: as_of = bar mới nhất ≤ `session_covered_at` (trước 15:05 =
phiên trước), bản live đã có ⇒ no-op (bản backfill thì live ghi đè), `--force`; breadth live lấy
`market_overview.json` khi `data_date` khớp, không thì tái dựng; `backfill(days)` không bao giờ đè
live; `verify()` = F1 (gấp lại == published) + revision (close lưu vs parquet >0.1%); `replay_check`
thêm F2 (điểm backfill == điểm live). `run.py`: bước `horizons` sau gold/trước allocation, không bao
giờ trả 2; `run.py horizons --show|--backfill [--days]|--replay|--force`. Doctor `check_horizons`
(warn: thiếu state / cũ so bar kho / fold≠published / revision / conflicted copy; off khi
`VNSTOCK_HORIZONS_STEP=0`, main nạp `.env`). 19 test `tests/test_horizons_state.py` (whitelist
`--fast`; test kill-switch chặn `load_dotenv` để `.env` máy thật không lọt). Full sandbox: 3,568
passed, tập lỗi môi trường y hệt gốc. Kho giả chạy backfill→update→show→replay→doctor 2.4s.

# 🔭 U71. BRIEF 3 KHUNG — CHỐT + P0: LÕI `vnstock_horizons.py` + REPLAY KHO THẬT (05/10)

**User chốt:** "theo khuyến nghị hết" cả 13 câu §8 + 5 cách giảm "cái giá" §7.3 (cầu chì 8%,
bảo vệ 2 mức, KHÔNG túi lướt, vùng phẳng tham số, 🚨 sớm 15:10 lên P1b). Câu 11: brief sáng
thi thoảng mới dùng, chạy tay ⇒ chỉ ĐỌC state, không khối/logic riêng cho sáng.
**§7.3 replay (Finhay 2017-12→2026-10, `scratchpad/brief_design/mitig/mitig.py`):** cầu chì
TĂNG→ĐI NGANG khi đóng tuần ≤8% dưới đỉnh: rời TĂNG ở 2018 −20.0%→−12.8%, Q1-2026 −13.4%→−10.9%;
đổi 3.2→4.3/năm, đảo ≤4 tuần 3/28→8/38 (6% nhiễu gấp đôi; cầu chì ĐỐI XỨNG rời GIẢM sớm 42/76
đảo — loại). Túi lướt 10% khi hồi×ĐI NGANG: +0.09 điểm %/năm, 48% vòng lỗ, 2 vòng 08–09/2026 đều
lỗ. 12/12 tổ hợp MA8–10w/30–40w × ±1–3% × 1–2 tuần không TĂNG trong 08–09; MA12–13w/50–52w thì CÓ
(khung dài hơn KHÔNG an toàn hơn). Bảo vệ "cứng = ≥2 tín hiệu" làm mất 2.4% phiên so với floor cũ
⇒ cứng = floor cũ GIẢM HOẶC ≥2 tín hiệu (tập cha giữ nguyên).
**Code (chưa nối pipeline/brief — production KHÔNG đổi):**
* `vnstock_horizons.py` — lõi THUẦN: `short_step/short_series` (nhảy thẳng hồi→chỉnh, cấm
  chỉnh→hồi), `medium_series/medium_daily` (tuần ISO, tuần dở bỏ, thứ Sáu nghỉ ⇒ hiệu lực phiên
  đầu tuần sau), `trigger_levels` (2 ràng buộc + cầu chì, "chưa thể" khi >8% hoặc > đỉnh 52 tuần),
  `alert_series` (🚨 neo cố định), `protection_level` (2 mức), `stance_rule` (bảng §3.4).
  **Cầu chì đo trên đỉnh 12 ĐÓNG TUẦN, không phải đỉnh 60 phiên ngày**: replay trùng hệt, nhưng
  trung hạn chỉ nhận đóng tuần (nhiễu giữa tuần không đổi được nó — có property test).
  Đối chiếu Finhay: ngắn hạn 27.1 đổi/năm · trung hạn 3.2 / 4.3 (cầu chì) · 🚨 khớp 100% bản thiết
  kế · mức 28/08 = 1,841.56 / 1,749.84 · rời GIẢM tuần 09/10 = 1,803.15 (đều có test neo).
* `scripts/replay_horizons.py` — P0, CHỈ ĐỌC: VNINDEX (khử trùng conflicted copy), breadth/A-D
  tái dựng THEO NGÀY đúng cách runner đếm (EMA200 cửa sổ 400 ngày tính O(1) bằng
  F[hi] − (1−α)^k·(F[lo] − x[lo]); test so với cách đếm tay từng phiên), NN cache, brief đã in
  (`brief_memory.db` mode=ro, bản hợp lệ mới nhất/ngày), vùng phẳng 18 biến thể, độ sâu registry
  vĩ mô. Kho giả (VNINDEX thật + 40 mã) chạy 1.7s.
* Test: `tests/test_horizons.py` (39, whitelist `--fast`) + `tests/test_replay_horizons.py` (5,
  chỉ full). Sandbox thiếu `vnstock` ⇒ 51 lỗi môi trường, tập lỗi TRƯỚC/SAU thay đổi giống hệt.
**Tiếp:** user chạy P0 (○, ngoài khung pipeline) → dán output → chốt tham số → P1a.

# 🔭 U70. BRIEF 3 KHUNG THỜI GIAN — ĐỀ XUẤT CHỐNG LẬT (05/10, chưa code)

**Hỏi:** 27/08–09/2026 brief đổi risk-off → risk-on → risk-off quá nhanh, nhà đầu tư không
kịp xoay sở; user muốn nhìn khung dài hơn + vĩ mô, có góc nhìn ngắn/trung/dài hạn.
**Nguyên nhân gốc (đã đối chiếu tay):** `classify_regime` cộng 7 phiếu → nhãn thẳng
(≥4 Bull, ≤−4 Bear), KHÔNG trí nhớ/xác nhận, có phiếu 1 phiên (NN 1D) — `vnstock_regime.py:206-217`;
`_bias_floor_dir` ép Stance ở ±3 / momentum ±50 — `vnstock_brief.py:1327-1343`. Một nhịp hồi 2–3
phiên lật cả nhãn header lẫn Stance.
**Replay (Finhay, proxy breadth/A-D):** 15/08–30/09 nhãn 5 mức đổi 17 lần, floor ép Stance đổi 16
lần (11 ngày TĂNG / 11 GIẢM), 2 vòng Risk-off↔on; Risk-on 24/08 sau +3.6% từ đáy, Risk-off 24/09
sau −4.2% từ đỉnh — mua theo ON, bán theo OFF lỗ −0.8%. Làm mượt cùng đầu vào (N-of-M, hysteresis,
dwell) vẫn bật ON cuối 08 — phải đổi KHUNG (tuần), không chỉ làm mượt.
**Đề xuất** (workflow 23 agent, `docs/THIET-KE-BRIEF-3-KHUNG.md`): ngắn hạn (máy trạng thái trên
điểm 7 phiếu: nhịp hồi/chưa rõ/nhịp chỉnh) · trung hạn = xu hướng TUẦN (±2% MA40w + MA10w/MA40w,
xuống 1 tuần, lên 2 tuần; LÀ tiêu đề) · dài hạn (vĩ mô 5 trụ, tháng) · 🚨 rủi ro ngắn hạn tách riêng
(không lật xu hướng) · lớp bảo vệ = tập cha floor cũ (không ngày nào mất bảo vệ) · Stance TĂNG chỉ
khi trung hạn TĂNG, GIẢM không bao giờ bị cấm · kẹp band v1 không tăng ngược xu hướng · mọi mức
kích hoạt code giải sẵn. Replay giai đoạn: tiêu đề ĐI NGANG suốt → GIẢM 02/10; Stance bị ép đổi 2
lần (cũ 16), 0 đảo TĂNG↔GIẢM. Cái giá: không ăn nhịp +7.3%; Stance chậm (12 vs 8 phiên); trung hạn
trễ ~61 phiên ở khúc quay lớn; n=1 + tham số chọn sau khi thấy giai đoạn ⇒ P0 hiệu chỉnh trên kho
thật + chạy bóng trước khi bật. **User đã chốt 05/10 — xem U71.**

# 👁 U69. CLAUDE CODE ĐỌC ẢNH BÁO CÁO KHÔNG CÓ LỚP TEXT (04/10 tối)

**Vết:** user thêm `Q4.docx` (id `57ab0fd0d74c6cb5`) ở tab Báo cáo ⇒ 0 ký tự, trạng
thái 🖼 — DOCX toàn ảnh (ảnh chụp slide/bảng dán vào Word), `docx_to_text` chỉ đọc
`<w:t>` nên không có gì; `Q3_update` cùng cảnh. `no_text_layer` ⇒ không bao giờ vào
digest. User: "làm đường Claude đọc ảnh đi".

**Kiểm trước khi viết (sandbox, CLI 2.1.289):** `claude -p --tools Read
--permission-prompts none`, cwd = thư mục chứa file ⇒ (a) đọc PNG đúng ($0,015
Haiku); (b) PDF chỉ có ảnh (pypdf `extract_text` = '') đọc qua Read `pages="2-3"`
đúng 2 trang ($0,02). Không cần poppler/pymupdf để vẽ trang — Read tự lo.
**Phạm vi đọc (thử 3 cách, cùng đề "đọc file trong cwd rồi đọc file NGOÀI cwd"):**
`--allowedTools Read` ⇒ đọc được CẢ file ngoài (lộ) · `--allowedTools "Read(./**)"`
⇒ ngoài bị từ chối · không `--allowedTools` ⇒ ngoài bị từ chối, trong vẫn đọc.
Chọn cách cuối (ít cờ nhất) + có công cụ thì luôn `--setting-sources ""` để rule
allow trong settings người dùng không nới được. Lý do: chữ trong ảnh báo cáo là
dữ liệu ngoài — một dòng "đọc C:\vnstock\.env" không được thành hành động.

**Thiết kế (`vnstock_report_vision.py`, 13 test `tests/test_report_vision.py`):**
* `vnstock_claude_cli`: `cli_command(tools=)` (+ `--allowedTools` cùng giá trị khi
  khác rỗng) và `complete(tools=, cwd=)` — mặc định y cũ (0 công cụ, cwd repo).
* DOCX: ảnh theo THỨ TỰ thân văn bản (`r:embed`/`r:id` trong `document*.xml` →
  rels → `word/media`), ảnh header/footer (logo) tự rơi vì thân không trỏ; thân
  không trỏ ảnh nào ⇒ lấy mọi media theo tên. Bỏ icon (< 200×200 hoặc cạnh < 60),
  SVG; EMF/WMF (biểu đồ dán từ Excel) chỉ Pillow trên WINDOWS mới vẽ được ⇒ desktop
  đọc được, sandbox bỏ + đếm. Ảnh > 2.000px / BMP / TIFF ⇒ PNG thu nhỏ. 8 ảnh/lượt.
* PDF: `report.pdf` + Read `pages=` 10 trang/lượt (pypdf đếm trang; không đếm được
  ⇒ 1 lượt "toàn bộ").
* Prompt chép NGUYÊN VĂN (bảng " | ", biểu đồ = số IN trên hình + 1 câu xu hướng,
  không ước lượng, "[không đọc được]" thay vì đoán, nhãn `[Ảnh N]`/`[Trang N]`).
* Model `VNSTOCK_REPORT_VISION_CLI_MODEL` > `VNSTOCK_CLAUDE_CLI_MODEL` > mặc định
  CLI (chép số liệu cần chính xác — Haiku thử 04/10 sai dấu "VĨ MỀ", "tỷ trong cơ
  phiếu"); trần `VNSTOCK_REPORT_VISION_TIMEOUT_S` 900s/lượt. Không slug mới.
* Được ăn cả: lượt nào hỏng / tổng < 200 ký tự ⇒ KHÔNG ghi (in 150 ký tự đầu để
  biết Claude đã thấy gì). Thành công ⇒ `vnstock_reports.set_text(rid, text, via=
  "claude-vision")`: chars, `no_text_layer=False`, `text_via`, bỏ digest cũ.
* `_upsert` giữ bản đọc ảnh khi upload lại CÙNG file (Streamlit rerun / thêm meta)
  — không thì trích lại ra 0 ký tự đè mất.
* UI: chọn báo cáo 🖼 ở Thư viện ⇒ nút **👁 Cho Claude đọc ảnh** (reset memo "CLI
  chết" trước — bấm tay là muốn thử lại); cột "Đọc ảnh" 👁. CLI `python
  vnstock_report_vision.py <id> | --all | --dry-run`. KHÔNG tự chạy trong pipeline.

**E2E sandbox (Haiku, 2 ảnh có bảng + biểu đồ cột):** 18s · $0,02 · 548 ký tự;
số trên cột (6,9 / 7,1 / 7,4%) đọc đúng; bản ghi vào phân tích ngay.

**Chạy thật Q4.docx (04/10 khuya, 🖥️ desktop, Opus):** 26 ảnh (0 bỏ) → 4 lượt
86s/77s/91s/16s · **53.486 ký tự · $1,15** ⇒ ✅ vào phân tích; digest claude-cli
18s · $0,10 · stance CP +0. **Lỗ phát hiện ngay:** `digest_report` cắt thân báo
cáo `_PROMPT_MAX_CHARS` 12K cho MỌI nấc ⇒ digest chỉ thấy 22% đầu (bìa + mở
đầu). Vá: `digest_call(cli_user=)` — nấc claude-cli nhận bản TRỌN
(`_CLI_PROMPT_MAX_CHARS` 200K = trần ingest), API/free giữ 12K (context nhỏ),
lượt tự sửa của nấc nào dùng đúng bản của nấc đó; digest ghi `chars_seen`, log +
tab Báo cáo in "⚠ chỉ đọc X/Y ký tự" khi cắt; `--refresh --redigest --id <id>`
chấm lại đúng một báo cáo. Nguồn gõ "HedgeAcedemy" (thiếu a) — sửa bằng
`--set-meta`, digest giữ nguyên.

**Chấm lại trọn (04/10 23:53):** 26s · $0,30 · `chars_seen` 53.486 · stance CP
+0 → **−1** (Trái phiếu +1, Vàng −2, USD 0) · `us10y` 5,29% khớp registry (±0,5).
Soi `--show` ra thêm hai lỗi, vá cùng đêm: (a) `tom_tat[:400]` cắt GIỮA CHỮ
("thị trườn") và chuỗi ấy vào thẳng brief phân bổ (`vnstock_brief_canon`) ⇒
`clip_text` cắt ở ranh giới câu/từ, trần 600 (prompt xin ≤ 500), áp cả claims/
risks 160; (b) prompt không nói 5 lớp là danh mục VN — báo cáo chủ yếu bàn Mỹ/
Trung Quốc + một đoạn TT50 tích cực cho VN mà CP −1 ⇒ không rõ −1 là cổ phiếu
Mỹ hay VN. Prompt nay neo: Cổ phiếu = niêm yết VN … USD = USD/VND; quan điểm
nước ngoài chỉ thành stance khi báo cáo nói rõ tác động tới lớp VN. Digest cũ
phải `--redigest` mới ăn prompt mới.
**Chấm lại theo prompt neo VN (05/10 00:00, 2 báo cáo):** Q4 19s · $0,30 — tóm
tắt hết câu (~490 ký tự) và nêu khuyến nghị rõ ("giữ cổ phiếu 20–30%, thậm chí
~0; short vàng 4.200–4.300") ⇒ CP −1 CÓ căn cứ; Trái phiếu +1 → 0 (trước là quan
điểm UST), Vàng −2 → −1. Báo cáo 10/07 (`f30fe71407845fb6`) CP −1, w=0,05.
Consensus CP −1,00 ⇒ tilt +1. Đặc tính thiết kế cần biết: consensus là trung
bình CÓ TRỌNG SỐ nên khi chỉ còn MỘT báo cáo, decay tuổi không làm tilt nhạt đi —
Q4 giữ tilt đủ +1 tới khi tròn 90 ngày (02/01/2027) trừ khi có báo cáo mới.

**Tilt NHẠT DẦN theo tuổi (05/10, user chốt):** `consensus()` thêm `strength =
min(1, Σ trọng số tuổi)` — CHIỀU tilt vẫn do trung bình có trọng số + ngưỡng ±1,0
(lọc nhiễu, không đổi), còn MỨC áp do strength. `apply_tilt` trộn tỷ trọng từ
bảng band data tới bảng band đã tilt một đoạn = strength (`blend_allocation`: số
nguyên, tổng 100, phần dư chia theo phần lẻ lớn nhất); `band` hiệu lực = band GẦN
hơn (strength ≥ 0,5 ⇒ band đã tilt). `report_tilt{strength, label}` — label
"+1 band × 60% (B2→B3, báo cáo cũ dần)" in ở CLI, tab Phân bổ, brief canon,
debate, doctor; bảng % trong brief ghi "tỷ trọng trộn" để LLM không sửa về bảng
gốc. History ghi `allocation` + `tilt_strength`, scorecard chấm theo % THẬT đã
khuyến nghị (entry cũ về bảng band). ≥1 báo cáo tươi ⇒ đủ 1 band như cũ. Lịch
Q4 (04/10, CP −1) nếu band data B2: đủ B3 tới 03/11 · 18/11 75% · 03/12 50%
(band về B2, cổ phiếu ~37–38%) · 18/12 25% · 02/01/2027 hết. Kill-switch cũ
`VNSTOCK_ALLOCATION_TILT=0` vẫn tắt hẳn.
**Chạy thật đầu tiên (05/10 00:10, desktop):** `run.py allocation` ra "tilt +1 band
× 10% (B3→B4) từ 1 báo cáo" — KHÔNG phải Q4: as_of = phiên 02/10 (T6), Q4 ngày
04/10 có tuổi âm ⇒ `load_for_analysis` loại (point-in-time, đúng); chỉ còn báo cáo
10/07 tuổi 84 ngày ⇒ w = 0,10. Bản cũ sẽ cho báo cáo 84 ngày ấy tilt ĐỦ 1 band —
đúng lỗi user muốn sửa. Band data B3 (điểm −0,514, điểm thô đề xuất B4, hysteresis
giữ B3) ⇒ từ pipeline tối 05/10 Q4 vào: đủ +1 ⇒ band hiệu lực B4.

**⚠️ Test đỏ trên máy thật, xanh ở sandbox (05/10 ~00:30, desktop, `run.py test`
full: 3.571 passed · 2 failed).** `test_enabled_sources_filter_by_env_prefix…` +
`test_social_sources_follow_env` thấy thêm `bsky:analysts` — `.env` desktop có
`VNSTOCK_NEWS_ALERT_BSKY_LIST` (List Bluesky tạo 04/10, SAU lượt full 3.486); fixture
đặt `_ENV_LOADED=True` nhưng module KHÁC đã nạp `.env` vào `os.environ` trong cùng
phiên pytest, mà danh sách `delenv` sót nhóm Bluesky/X. Không vá thì phát 18:00
05/10 dừng ở bước test ⇒ MẤT brief (đúng kịch bản U65). Vá: fixture xoá MỌI biến
`VNSTOCK_NEWS_ALERT*` + `TWITTERAPI_IO_KEY`/`X_BEARER_TOKEN`; tái hiện bằng cách đặt
biến giống desktop rồi chạy (đỏ → xanh), full sandbox với env giống desktop khớp
mốc. **Bài học:** thêm biến `.env` mới cho một module ⇒ fixture test của module đó
phải xoá theo TIỀN TỐ, không theo danh sách.
Desktop merge `dab4511` rồi `run.py test` full: **3.573 passed · 0 failed / 179s**,
badge xanh ⇒ phát 18:00 05/10 qua được bước test.

**Badge auto-heal kêu mãi bằng sổ CŨ (05/10).** Doctor "0/1,291 bar lành qua 2 lượt"
⚠️ nhưng `⏱ CHẶNG` 01/10 + 02/10 đều `auto-heal 0s`, không dòng `scanned=` ⇒ hàng
đợi cách ly RỖNG. `auto_heal` thoát sớm khi rỗng mà KHÔNG `record_heal_run` ⇒ sổ chỉ
còn 2 lượt cũ (hồi hàng đợi 1.291 bar) và badge cộng chúng vĩnh viễn. Vá: lượt rỗng
cũng ghi (`scanned=0`, trừ dry-run); badge thấy lượt cuối `scanned=0` ⇒ ok "hàng đợi
cách ly rỗng (lượt cuối …) — sổ cũ: …"; hàng đợi đầy lại ⇒ kêu lại như cũ. (Lệnh tôi
đưa user `Select-String 'auto-heal'` bắt nhầm dòng doctor in vào log — đúng là
`'⏱ CHẶNG|\[sync\] auto-heal'`.)
Desktop merge `b57017e` + `run.py test` full: **3.576 passed · 0 failed / 156s**.

**Gộp Live Scan thành MỘT công tắc sidebar (05/10, user yêu cầu).** Trước: Screener
`live_scan_on` (quét preset 10s) + Dòng Tiền `mf_live` (Buy/Sell 15s) là 2 toggle
trong tab — nav `st.pills` chỉ vẽ tab đang mở nên rời tab là Streamlit dọn state,
quay lại thấy OFF (cùng lớp bug Live Mode 17/08). Nay: sidebar chung, ngay dưới
Real-time WSS — widget `live_scan_toggle`, cờ thường `live_scan` = toggle AND
live_mode; Live Mode tắt ⇒ kéo widget về OFF + disabled + caption "cần bật Real-time
WSS". Hai tab chỉ đọc `live_scan` (vẫn gác `live_mode`), caption chỉ đường khi tắt.
**Thử thật bằng `streamlit.testing.AppTest` (1.64, vnstock_wss giả + screener_results
tạm rồi xoá):** mở app → bật Live Mode → bật Live Scan → sang Dòng Tiền → về Screener
⇒ Live Scan GIỮ ON suốt; tắt Live Mode ⇒ Live Scan OFF + khoá; 0 exception. Test
cấu trúc + test chạy đúng khối sidebar bằng `exec` thay test 2-toggle cũ.

**Tách Telegram theo kênh (05/10, user chọn "2 group + 1 thư mục").** Telegram không
có "channel chứa group" — 3 cách dựng hỏi user: 2 group + Folder (chọn) · 1 group 2
Topic · 2 Channel. Code chung cho cả ba: `vnstock_telegram._creds(channel)` — kênh
`news` đọc `TELEGRAM_NEWS_BOT_TOKEN`/`_CHAT_ID`, biến nào thiếu lấy mặc định (không đặt
= y cũ); `send_message(channel=)`; news-alert `_default_sender` gửi `channel="news"`;
mọi chỗ khác (brief, báo cáo lãi suất, cảnh báo ladder, model watch) giữ mặc định.
`find_chats` (getUpdates, chỉ đọc) + `run.py telegram chats [--channel news]` in id
group để user KHÔNG dán token vào trình duyệt; `telegram test --channel news`. Lỗi 400
"upgraded to a supergroup" nay in id mới (`migrate_to_chat_id`). Doctor `telegram`:
warn khi có bot tin riêng mà thiếu group tin (bot tin sẽ gửi vào chat mặc định nơi nó
không là thành viên ⇒ lỗi mỗi giờ). Test xoá `TELEGRAM_*` theo TIỀN TỐ + chặn `_load_env`.
**Vết dựng thật (05/10 ~02:00):** `chats --channel news` lượt 1 rỗng, lượt 2 in group
Brief `-5561219238` ⇒ tôi kết luận "bot tin nằm nhầm group Brief" — SAI, ảnh user cho
thấy 2 bot đúng 2 group ("VnStock Hourly Update" ở News Hourly Update, "Marketview
daily" ở Brief). Thủ phạm là chính lệnh dò: thiếu `TELEGRAM_NEWS_BOT_TOKEN` (dòng bị `#`
theo gợi ý "tạm tắt" của tôi) ⇒ `_creds` LÙI về bot mặc định ⇒ in group của bot brief.
Vá: lệnh DÒ (`find_chats`, `bot_identity`) dùng `_lookup_token` KHÔNG lùi (báo thiếu
biến / bị # tắt); `chats` in `bot: @username (tên)` qua getMe trước danh sách để đối
chiếu token ↔ bot. Gửi tin vẫn lùi như cũ. **Bài học:** công cụ chẩn đoán không được
có đường lùi im lặng — nó trả lời câu hỏi KHÁC mà trông như câu trả lời đúng.
Sau vá: `chats --channel news` in `bot: @News_hourly_bot (VnStock Hourly Update)` nhưng
"chưa thấy chat nào" dù bot ĐÃ ở group — user xoá/thêm lại bot + `/start@` + Start chat
riêng ⇒ thấy `group -5480122941 News Hourly Update` + `private` (lý do lượt đầu không
thấy chưa rõ; thêm lại là cách chữa rẻ). Lượt news-alert 02:00 05/10 lỗi `400 chat not
found` — lúc ấy có token bot tin mà chưa có `TELEGRAM_NEWS_CHAT_ID` ⇒ bot tin gửi vào
group Brief nơi nó không là thành viên (đúng ca badge doctor `telegram` mới cảnh báo);
12 tin giữ lại cho lượt sau. Doctor 02:30: Telegram ✅ "bot + group riêng".
**`.env` có 2 dòng `TELEGRAM_CHAT_ID`** (group Brief `-5561219238` ở trên, chat riêng cũ
`828087238` ở dưới — user giữ dòng cũ không `#`). python-dotenv 1.2.2: dòng SAU THẮNG
(đã thử) ⇒ brief sẽ âm thầm về chat riêng cũ. Đã xoá dòng cũ; lệnh soi trùng KHÔNG in
giá trị: `Get-Content .env | ? { $_ -match '^\s*[A-Z_]+=' } | % { ($_ -split '=')[0].Trim() }
| Group-Object | ? Count -gt 1` ⇒ rỗng. **Đã làm (user yêu cầu 05/10):** badge doctor
`env_duplicates` "Khoá trùng trong .env" — warn khi khoá lặp (ghi số dòng + KHÁC giá trị
"dòng N đang thắng" / cùng giá trị "sửa dòng trên sẽ không ăn"), KHÔNG BAO GIỜ in giá
trị, kèm tên máy (.env theo máy, doctor_status đi qua Dropbox). Helper chung
`_env_file_entries`/`_env_file_values` (BOM Notepad, `export `, dòng SAU thắng như dotenv)
— `_engine_setting` + `check_kill_switches` trước lấy dòng ĐẦU ⇒ có thể báo khác pipeline,
nay khớp. 8 test `tests/test_doctor_env_duplicates.py` (whitelist --fast).

**Còn hở:** (a) biểu đồ Word GỐC (`word/charts/chartN.xml`, không phải ảnh) không
vào đường này — số nằm sẵn trong XML (`c:numCache`), làm khi gặp; (b) chưa đo trên
Q4.docx thật (bao nhiêu ảnh, EMF hay PNG) — `--dry-run` cho biết.

# 📰 U67. CẢNH BÁO TIN QUAN TRỌNG MỖI GIỜ → TELEGRAM — ĐƯỜNG A (TASK SCHEDULER + CLAUDE CLI), REGISTRY NGUỒN MỞ RỘNG (02/10 sáng)

**Hỏi:** dùng Claude Code/Cowork kéo tin kinh tế-tài chính về Telegram mỗi giờ.
**Cân ba đường:** A Task Scheduler + `run.py news-alert` (chọn) · B Routine cloud
(loại — đo lại 02/10 từ sandbox: CONNECT 403 cho `api.telegram.org`, cafef,
vnexpress, cnbc, r.jina.ai — y hệt U62; kho không lên cloud; mỗi lượt là một
phiên Claude Code thay vì một call) · C Cowork scheduled task (cần app mở trên
desktop như A, mỗi giờ là một phiên agent — không hơn A mà kém tất định).

**Kiểm kê nguồn tin trước khi làm** (user hỏi): (1) `vnstock_news_feeds._FEEDS`
**12 RSS** — VN: VnExpress Kinh doanh + Thế giới, CafeF Vĩ mô-Đầu tư + Chứng
khoán + Tài chính-NH, VnEconomy Chứng khoán + Tài chính, Tin nhanh CK (ĐTCK), Báo
Chính phủ KT; EN: MarketWatch Top, CNBC Markets, Yahoo Finance — lọc từ khoá
`_MARKET_KEYWORDS`, chấm ≤8 tin/refresh, cache `market_news_cache.json`, brief
đọc 6 tin ≤3 ngày; (2) `vnstock_news.fetch_ticker_news` — tin THEO MÃ qua thư
viện vnstock (VCI, rơi KBS, sponsor vnii/vnstock_data), universe = danh mục +
top screener, nuôi tab Tin tức + sentiment 7N của brief; (3) Finhay MCP
`list_news` chỉ có trong phiên Claude (script máy user không gọi được MCP);
(4) Vietstock scrape là SỰ KIỆN quyền, không phải tin. Báo Đầu tư bỏ 08/07
(RSS 404). Trước 02/10 KHÔNG có đường nào đẩy tin theo giờ — tin chỉ vào brief
chiều.

**Thiết kế (`vnstock_news_alert.py`, 47 test `tests/test_news_alert.py`):**
- Registry `SOURCES`: `Source(key, name, fetch, kind, lang, enabled, relevant)`;
  RSS dựng từ `_FEEDS` (một nguồn sự thật) qua `rss_source`; adapter không-RSS
  mẫu `ticker_news_source` (env `VNSTOCK_NEWS_ALERT_TICKERS`); `register_source`
  cho module khác; `enabled_sources(only)` lọc tiền tố key. `collect` fetch
  song song, một nguồn nổ = 0 tin; `normalize_item` nhận dict thô bất kỳ
  ({title, link, summary, published}) ra schema chung của news_feeds.
- `parse_feed` thêm `_published_at` (giờ đầy đủ, local) — `_date_sort` chỉ có
  ngày nên không lọc "3h qua" được; cache news cũ thêm một trường, vô hại.
- Chống trùng hai lớp: `deduplicate_news` trong lô + sổ `_meta/news_alert_seen.json`
  (`_hash` date|title của news_feeds, giữ 7 ngày). Sổ ghi cả điểm + đã gửi ⇒ tin
  dư (quá MAX_SEND) đi lượt sau KHÔNG chấm lại; tin Claude bỏ sót ghi
  `score=None` — thấy rồi, không chấm lại mãi.
- Chấm: `SCORE_SYSTEM` thang 1–5 (5 sốc hệ thống … 1 phi kinh tế) + nhãn + tác
  động ≤22 từ cùng quy tắc chiều của `_ANALYZE_SYSTEM`; MỘT call
  `vcc.complete(json_schema=SCORE_SCHEMA, tag="news-alert")`, engine
  `STEP_ENGINE_ENV["news_alert"]`; `parse_scores` kẹp 1–5, dọn `sanitize_impact`.
  Rơi về ladder: `analyze_item` từng tin với `_user_text_tmp` sẵn (không Jina),
  mức độ từ `heuristic_score` 2/3/4 theo hai bậc từ khoá, "không tác động" = 1.
  Không engine ⇒ không gửi (không đẩy tin thô), marker error.
- Gửi: `format_message` HTML chỉ b/i (whitelist telegram), link trần;
  `send_message` tự cắt 4000. Telegram lỗi ⇒ giữ `sent=False`, lượt sau gửi lại.
- Marker `news_alert_status.json` {ran_at, machine, engine, claude_error, sources,
  fetched, in_window, new, scored, picked, sent, message_id, error, error_streak}.
  Doctor `news_alert_verdict` (hàm thuần, now/active cắm được): off/ok/warn/error.
  Kill-switch `VNSTOCK_NEWS_ALERT` vào `_DANGEROUS_SWITCHES`.
- `run.py news-alert` (--dry-run/--force/--min-score/--window-h/--max-send/
  --sources/--engine/--list-sources), rc 0/1 không bao giờ 2; KHÔNG trong `all`;
  stdout chảy vào `run_daily.log` qua tee của main() (16 lượt/ngày, 3–4 dòng/lượt).
- Task 3 trong `setup_scheduled_tasks.ps1`: Weekly T2–T7 07:00 + Repetition 1h
  tới 22:00 (gán `.Repetition` từ trigger -Once — Weekly không nhận trực tiếp),
  trần 15′, `-NewsAlertStart/-NewsAlertEnd/-NoNewsAlert`. Hệ quả: "2 task =
  desktop" thành "≥2 task" ở CLAUDE.md + VIEC.

**Bẫy đã thấy trước:** (a) lượt giờ 18:00–23:00 chạy cùng phát tối trên cùng
desktop — tránh bằng cách KHÔNG ghi `market_news_cache.json`; sổ riêng.
(b) Laptop chạy script lịch ⇒ gửi đôi tới khi Dropbox sync sổ — ghi rõ chỉ
desktop. (c) Feed không tz ⇒ coi giờ địa phương; feed sai tz chỉ làm tin
vào/ra cửa sổ sớm muộn, sổ vẫn chặn trùng. (d) Sandbox không có `vnstock` ⇒
`run.py test --fast` dừng ở collection `test_classifier.py` — chạy pytest thẳng
whitelist với `--continue-on-collection-errors`: **2.748 passed · 33 failed · 1
error**, 33 fail nằm trọn 6 file (model_watch 11 · pipeline_status_gate 7 ·
bank_balance_export 5 · atomic_writes 4 · ohlc_repair 3 · model_ladder 3) và
cây sạch `git stash` cho ĐÚNG 33 fail y hệt (ModuleNotFoundError vnstock /
vnstock_data / openpyxl) ⇒ không do thay đổi này; máy thật phải chạy `--fast` đủ.

**User chốt 02/10 sáng (sau ba câu hỏi về nguồn):** (1) nguồn 1 (RSS) là bộ feed
user chọn 15/06, mở rộng 08/07 — user quên nên hỏi lại; (2) nguồn 1 ↔ nguồn 2
KHÔNG trùng bài: nguồn 2 là bài Vietstock gắn theo mã (VCI trả `news_source_link`
dạng đường dẫn vietstock.vn), nguồn 1 không có feed Vietstock; chỉ có thể trùng
SỰ KIỆN, và brief hiện không khử trùng chéo hai khối (📰 vs ngữ cảnh danh mục);
(3) **cảnh báo chỉ cần tin thị trường / vĩ mô quan trọng — nguồn 2 để TẮT**
(không đặt `VNSTOCK_NEWS_ALERT_TICKERS`). Theo đó prompt `SCORE_SYSTEM` sửa:
mục tiêu ghi rõ "TIN VĨ MÔ QUAN TRỌNG, không phải tin riêng từng doanh nghiệp";
"kết quả kinh doanh/sự kiện của mã VN30" RỜI mức 4, tin riêng một doanh nghiệp
(kể cả VN30) về mức 2, chỉ lên 4 khi đổi kỳ vọng cả ngành/thị trường; test ghim
`test_score_prompt_is_macro_first_company_news_capped` (47 test). Khử trùng chéo
nguồn 1↔2 vì thế KHÔNG làm. Lý do adapter nguồn 2 vẫn nằm trong code dù tắt:
chứng minh registry nhận nguồn không-RSS (mẫu cho Finhay/SBV/HOSE sau này),
một dòng env là bật; chi phí 1 call VCI/mã/giờ nên không bao giờ nên bật cho cả
rổ 130 mã.

**Chưa làm (cố ý):** không đưa tin cảnh báo vào brief/cache news (brief đã có
khối tin riêng); không fetch thân bài Jina (lượt giờ phải < 1′); không
Cowork/Routine. Hỏi lại khi muốn: kênh Telegram riêng cho cảnh báo (hiện dùng
chung chat_id), tóm tắt cuối ngày các tin đã gửi, nguồn API (Finhay/SBV/HOSE)
qua `register_source`.

# 🔎 U66. `/brief-review` ĐẦU TIÊN (desktop, 01/10 sáng): VALIDATOR VNINDEX BÁO GIẢ VÌ NĂM TRONG NGÀY ISO — VÁ #30, #914 CHẤM 4★

**Bằng chứng:** log lượt bù phiên 30/09 (`telegram close --engine claude
--force`, 01:46): `Brief nêu VNINDEX ≈ 2,026 (+14.6% lệch so với close thực
1,768.62) → khả năng hallucinate`. Claude Code desktop dò gói: 2,026 KHÔNG có
trong context; brief ghi 1,768.62 ở dòng 2 và 9; dòng 56 là tin canon
`- ⚪ [2026-10-01] Lãi suất và VN-Index có thực sự "ngược đường"?…` —
`_VNI_CONTEXT_RE` khớp "VN-Index", `_VNI_MAGNITUDE_RE` (`[12][.,]?\d{3}`) nuốt
"2026" của ngày ⇒ cảnh báo giả. Validator chỉ warn, brief vẫn gửi và số đúng.
Lưu ý: dòng tin là khối canon do `enforce_market_news` chèn SAU chữ model ⇒
lỗi này bắn với MỌI engine mỗi khi headline có "VN-Index" và ngày 2026 — có
thể đã réo nhiều đêm trước mà không ai đọc log.

**Vá (`49c78d6`, nhánh `fix/vnindex-validator-iso-date`, gộp về
`claude/laptop-work-ono4qt` ở `7da5a4a`):** `_ISO_DATE_RE` strip trước khi
quét ở cả hai điểm (có data / không data); re-export qua `vnstock_brief` (lưới
parity bắt thiếu); 2 ca trong `test_validate_brief_factuality_*` (headline có
ngày = sạch; cùng dòng có mức sai thật vẫn réo). Full 3.359 trước push. Desktop
`main` fast-forward, đi trước `origin/main` 62 commit — đẩy hay không là việc
của user.

**Đánh giá lượt Claude Code desktop (user hỏi):** chẩn đoán đúng, sửa tối
thiểu đúng chỗ, tự bắt lỗi re-export nhờ lưới parity, chạy full trước push,
mở nhánh riêng thay vì đụng `main`. Hai nhận định trung gian SAI rồi tự sửa
trước khi hành động: "brief bịa chỉ số" (thực ra validator giả) và "`--force`
01:46 = đẩy brief bù sáng cũ" (thực ra bản phiên 30/09 cố ý gửi vì cửa 15:05
chặn). Thiếu: không ghi docs (bù ở đây + VIEC #30), vá nằm ngoài nhánh làm
việc nên laptop không nhận theo đường quen (đã gộp), nhận xét chấm sao "số
đúng, validator lỗi" nói về validator chứ không về brief (vô hại: few-shot chỉ
dùng chữ brief). Còn hở: năm trần ("VN-Index năm 2026", "Q3/2026") vẫn lọt
validator — chờ thấy mới vá.

# 🛑 U65. PHÁT 30/09 (CHẠY BÙ 23:47) DỪNG Ở BƯỚC TEST — TEST SLUG NGOÀI WHITELIST CÒN GHIM qwen3.6-27b, MẤT BRIEF (01/10 rạng sáng)

**Bằng chứng (🖥️ desktop, 01/10 ~02:00):** `Get-ScheduledTaskInfo`: LastRunTime
30/09 23:47 (máy tắt lúc 18:00 → StartWhenAvailable chạy bù khi bật máy),
LastTaskResult 2. `run_daily.log`: 9 bước xong (sync 836s · validate 433s ·
screener 668s · news 1.007s · foreign-flow 23s · macro 13s · gold 2s ·
allocation 3s · test 134,8s) rồi `[run.py] test returned hard failure (rc=2)
→ stopping`, `⏱ TỔNG [2026-10-01 00:39] 52,0 phút (9 bước)`. Audit · train ·
reflection · doctor · brief KHÔNG chạy ⇒ `vnstock_brief_pack.py --review` sáng
01/10: marker vẫn `close=2026-09-29 · engine=claude-file · máy=CFA-BINHLD-LT`
(bản laptop 13:19), memory không có dòng 30/09 (hai dòng mới nhất #913 Claude
7.003 ký tự · #909 Nemotron 0 ký tự = brief trắng 29/09). **Phiên 30/09 mất
brief.** Cùng lúc user đang cài native Claude Code + sửa `.env` trên chính
desktop, nên nghi `.env` trước.

**Truy (tái hiện trong sandbox bằng `.env` giả giống desktop: 12 khoá dummy +
`VNSTOCK_CLAUDE_CLI_EXE` + `VNSTOCK_LLM_ENGINE=claude`):** full suite 1 failed
/ 3.358 passed — `tests/test_news_analyze_route.py::test_analyze_models_slugs_22_07`
ghim `_ANALYZE_MODELS["Groq"] == "qwen/qwen3.6-27b"` trong khi #17 (29/09
khuya) đã đổi sang `openai/gpt-oss-120b`. File KHÔNG nằm trong whitelist
`--fast` ⇒ sandbox lẫn desktop (`--fast` 2.759 xanh) đều không thấy; phát 29/09
chạy full lúc 18:00, TRƯỚC khi #17 merge 23:20 ⇒ phát 30/09 là lần full đầu
tiên sau #17. `.env` engine Claude KHÔNG liên quan: lưới `_no_claude_cli_anywhere`
(conftest) đủ, full 3.359 xanh với chính `.env` giả đó.

**Vá:** test ghim slug mới + docstring lý do; đưa
`tests/test_news_analyze_route.py` vào whitelist `--fast` (+14 test ⇒ 2.773);
full 3.359. CLAUDE.md: đổi slug/migration ⇒ chạy FULL trước khi push. Lỗi này
của tôi từ 29/09: #17 chỉ chạy `--fast`.

**Câu hỏi thiết kế (chờ user):** bước `test` (9/14) fail cứng dừng cả pipeline
⇒ 5 bước sau, kể cả brief, mất theo. "Badge đỏ = không merge/deploy" đúng cho
code, nhưng brief chiều là sản phẩm cho người đọc, không phải deploy. (a) giữ
như nay; (b) test đỏ ⇒ exit 1: badge đỏ + doctor réo, pipeline vẫn đi tới
brief. Chưa đổi gì.

# 🥇 U64. BRIEF CLAUDE ĐẦU TIÊN — TIN TELEGRAM 290 (đường B, laptop, 30/09 13:19), CHẤM + VÁ GUARD #17 (30/09 chiều)

**Bối cảnh:** user chạy trọn đường B trên 💻 laptop với gói phiên 29/09 (kho
chưa sync 30/09): `/login` → `/brief-close` (Claude Code, 2′28″, 56 dòng) →
`run.py brief --from-file … --force` (gửi trùng có ý thức, phiên 29/09 đã có
bản ladder) → tin 290, marker `engine=claude-file`. Bản ladder cùng phiên là
flash-lite dự phòng (U60).

**Chấm (toàn văn tin 290):** 4/5.
- ĐẠT: mọi nhận định neo số từ gói, format EN; TLDR có stance "Bias GIẢM"
  (parser stance bắt được) kèm mức kích hoạt VÀ mức huỷ (S1 1,766.40 /
  R1 1,789.35); mức kỹ thuật khớp header (MA20 -1.8%, MA50 +0.3%, MA200
  -1.0%); Watchlist 3 setup đều đúng THỨ TỰ và hợp bias (FRT chỉ mua nếu
  vượt 143,000 · chốt 148,000 · cắt 140,600; NLG/SSB giảm tỷ trọng NẾU thủng,
  mục tiêu dưới mức thủng, huỷ trên giá) — đúng chỗ ladder từng sai chiều
  25/09; Danh mục giữ (EIB/SSI) gắn lý do vào dữ liệu (NN bán ròng ngân hàng
  -2,536 tỷ, chứng khoán -0.147pp) và không khuyên gia tăng khi bias GIẢM;
  Rủi ro neo D/E + Op.CF, ghi chú BĐS chuẩn.
- Guard đã dọn đúng: `## 🎯 TLDR (2 dòng)` → "TLDR"; mục Sự kiện thay bằng
  danh sách chuẩn (Claude bỏ NVL 30/09 vì "trùng hôm nay" — gói cũ 1 ngày, vô
  nghĩa vì guard thay cả mục).
- LỌT (lỗi guard, không phải Claude): mục Đề xuất giao dịch in `- MSN BUY
  entry=68.7 · TP=74.6 · SL=65.6 (~1,400 cp, rủi ro 1% NAV).` và câu dẫn
  `(Strategy #69, conf 0.50–0.60)`. Claude chép gần nguyên văn dòng DATA
  (`- MSN BUY entry=… TP=… SL=… · KL gợi ý ~1,400 cp (rủi ro 1% NAV)`);
  `_REC_RAW_LINE_RE` (#17, 29/09) chỉ bắt "TK: BUY entry=E, TP=T, SL=S" (dấu
  hai chấm + dấu phẩy) ⇒ trượt. KL gợi ý là số CÓ trong gói (sizing theo
  `nav_million` user cấu hình, `_recommendation_block`) — không phải bịa.
- Nhỏ: Watchlist FRT "canh mua nếu vượt 143,000" trong khi sổ đang mở FRT
  BUY @139 (ngày 1/20) — không mâu thuẫn nhưng bản tốt hơn sẽ nhắc lệnh mở.
- Footer `🤖 Claude Code · opus-5-5` ở đường B là nhãn theo cấu hình
  (`cli_model()`), không biết model thật của phiên tương tác.

**Vá:** `enforce_rec_line_format` (guards_sections) nay bắt mọi biến thể:
dấu hai chấm tuỳ chọn, nhãn tầng `[vị thế ~N phiên]` trước/sau BUY (giữ),
ngăn cách ` , · |`, số EN không nuốt dấu phẩy, đuôi tự do → dựng lại
"TK: MUA vùng E · chốt lời T · cắt lỗ S [· KL gợi ý ~N cp (rủi ro x% NAV)]
[— lý do]"; nhãn `(Strategy #n …)` bị bỏ ở MỌI dòng (câu dẫn). Test
`test_enforce_rec_line_format_catches_claude_variant_from_telegram_290`
dùng đúng 3 dòng tin 290 + dòng data thô + dạng cũ; lưới re-export
(`test_all_moved_names_are_reexported`) đòi mọi tên module guard phải qua
`vnstock_brief_guards` → `vnstock_brief`. Fast 2.758.

**Hội đồng chấm (30/09 chiều — workflow 10 agent: 7 giám khảo độc lập →
buộc tội/bào chữa → trọng tài; cấm đọc điểm 4/5 ở trên để khỏi bị neo):**
chốt **4★** cả hai thang (bản người đọc nhận / phần quy cho Claude). Phân bố:
trung thực số liệu 4 · format 4 · đáng làm mẫu 4 · so nền ladder 4 · tính
hành động 3 · vai trader 3 · vai tuân thủ 3; buộc tội đòi 3 (tự nhận không
tìm được số/chiều nào sai), bào chữa 4 (tự nhận dải conf là chữ Claude tự
gom). **Sửa hai nhận định ở trên:** (1) `(Strategy #69, conf 0.50–0.60)`
KHÔNG phải chép — gói chỉ có từng `conf=0.5x` cuối mỗi dòng, Claude tự gom
thành dải rồi đưa lên câu dẫn ⇒ lỗi biên tập của Claude, guard trượt chỉ là
lưới phụ. (2) FRT không "nhỏ": một mã HAI bộ mốc trong một tin (watchlist
cắt 140,600 vs lệnh mở @139 SL ≈129,500) — người giữ FRT phải tự chọn stop;
FRT nằm trong 5 rec gói đưa cho Claude mà Claude không đối chiếu. Ba thiếu
sót nữa, đều ở Danh mục/Đề xuất: EIB/SSI không mốc (`_portfolio_block` không
có S/R cho mã đang giữ — đúng cách là ghi ở "Đề xuất bổ sung" thay vì "Không
cần bổ sung"); HDB (ngân hàng) chuyển tiếp MUA khi chính brief nói ngân hàng
bị bán ròng mạnh nhất — thiếu một câu nối; không ngành nào kèm %VNI dù prompt
bắt. **Vì sao 4 thắng 3:** định nghĩa 3★ đòi một LỖI khiến người đọc phải
kiểm lại số, mà mọi số/chiều kiểm được đều đúng (MA, S/R, momentum, A/D,
TP/SL MSN·HDB khớp khối lệnh mở); cửa sổ few-shot `output[:1200]` kết thúc ở
"Ngân hàng -2,536 tỷ (1 tuần)," — sạch, mọi khoản trừ nằm sau ký tự ~6.400;
chấm 3 thì memory không có mẫu Claude nào cho đêm sau. **#28 — lỗ guard thứ
hai từ tin 290:** `enforce_nn_frame_labels` trượt "ngân hàng bị NN bán ròng
mạnh nhất (-2,536 tỷ)" (chữ thường + cách số 27 ký tự > cửa sổ 18) ⇒
IGNORECASE, cửa sổ 40, trong ngoặc gắn ", 1 tuần"; test
`test_nn_frame_label_lowercase_sector_far_from_number_telegram_290`.

**Lệnh chấm (○):** `python vnstock_brief_pack.py --review` lấy id →
`python vnstock_brief_pack.py --rate <id> 4 "Không sai số hay chiều, stance
và watchlist hành động được; chỉ lộ nhãn Strategy/conf và dòng BUY entry
thô."`. **Để lên 5 (chữ của Claude, không phải pipeline):** (a) Đề xuất giao
dịch thuần Việt, không nhãn nội bộ, giữ "KL gợi ý"/"rủi ro % NAV" cho cả 3
dòng; (b) EIB/SSI nêu mức thật nếu có trong block movers, không có thì ghi
thiếu ở Đề xuất bổ sung; (c) ngành kèm %VNI; (d) FRT nhắc lệnh mở @139, nói
rõ kèo 143,000 là điểm gia tăng có điều kiện, không thay SL cũ. (b)(d) là
chuyện PROMPT — theo quy ước "đếm trước khi vá", chờ ≥3 bản Claude nữa rồi
sửa `build_prompt` một lần.

# ⏱ U63. XUẤT GÓI 12:46 30/09 MẤT 10′ — CỬA "3 MÃ LỖI LIỀN" (#21b) KHÔNG ĐỦ VÌ THƯ VIỆN TỰ THỬ LẠI (30/09 trưa)

**Bằng chứng (💻 laptop, `python run.py brief --export-pack`):** 18 dòng
`vnstock.core.utils.client - ERROR - API request failed: HTTPSConnectionPool
(host='iq.vietcap.com.vn') Read timed out (read timeout=30)` cách nhau 32–40s,
12:46:20 → 12:56:09, rồi `📦 pack phiên 2026-09-29 (30,497 ký tự prompt)`.
Gói ra phiên 29/09 là ĐÚNG (kho chưa sync bar 30/09, sync 18:00).

**Truy:** `build_pack` chạy y 4 bước refresh của `generate_brief`. Reconcile
rec đọc parquet (không VCI). Macro/news không VCI. `_maybe_refresh_events` →
`refresh_upcoming(tickers=_events_universe())` → `_fetch_vci_events(t)` =
`get_vnstock(t,"VCI").company.events()`; #21b dừng sau 3 mã lỗi LIỀN — nhưng
18 = 3 × 6: thư viện vnstock tự thử lại ~6 lần mỗi call (log là của client
thư viện, không phải của ta; sandbox không cài vnstock nên không đọc được số
retry, suy từ 18/3 và nhịp 33s). Mỗi "mã lỗi" thật ra ~3′.

**Vá:** (1) `refresh_upcoming(budget_s=120)` — có mã lỗi mà `time.monotonic()
- t_start ≥ budget` ⇒ dừng ngay (mã lỗi đầu đã vượt) ⇒ đêm VCI ốm tốn ~3′
thay vì 10′ (22/09 là 28′); env `VNSTOCK_EVENTS_REFRESH_BUDGET_S`, 0 = tắt,
cửa 3-mã-liền giữ nguyên. (2) BACKOFF: lượt trắng tay (`refreshed == 0 and
failed`) ghi `_meta/upcoming_events.backoff.json {at, until=+90′, failed}`;
`_maybe_refresh_events` (auto-refresh trong brief/pack) xét `in_backoff()`
qua `getattr` (test cũ dùng module giả không có hàm này) và bỏ qua tới hết
hạn; refresh thành công xoá marker; `vnstock_events.py --refresh` tay không
xét. Marker trong kho ⇒ Dropbox đưa sang máy kia — đúng, VCI ngã là ngã
chung. conftest redirect `vnstock_events._META` về tmp cho mọi test (không
ghi vết giả vào kho thật). Test `tests/test_events.py` +4.

**Còn để ngỏ:** số retry của thư viện có chỉnh được không (`vnstock.core.
utils.client`) — nếu có, đặt 1–2 lần là mỗi mã lỗi chỉ 30–60s; xem trên máy
thật: `python -c "import vnstock.core.utils.client as c; print([x for x in
dir(c) if 'retr' in x.lower() or 'timeout' in x.lower()])"`.

# 🧪 U62. THẨM ĐỊNH ENGINE CLAUDE (3 THIẾT KẾ × 3 GIÁM KHẢO) — A LÀ ĐƯỜNG CHÍNH, 9 LỖ HỔNG ĐÃ VÁ, BACKEND DÙNG CHUNG CHO 5 BƯỚC (30/09 trưa)

**Cách làm:** workflow 10 agent — 3 reader (đường brief, 8 điểm gọi LLM, ràng
buộc vận hành + cờ CLI) → 3 thiết kế độc lập (A CLI headless trong pipeline ·
B Routine cloud với gói đi qua git · C ClaudeAgent API qua SDK) → 3 giám khảo
(vận hành 2 máy Dropbox · chất lượng + parity · chi phí/bảo trì) → tổng hợp.
Điểm: **A 8/7/8 · C 7/8/6 · B 3/4/3.** B loại vì ba lý do KHÔNG chữa được
bằng code: cloud không gọi được `api.telegram.org` (403 chính sách mạng), kho
không lên cloud, và cửa `_should_push_close` chặn fallback sau nửa đêm ⇒ đêm
muộn mất brief mà badge vẫn xanh. C giữ làm pha tuỳ chọn khi user chịu trả
API. User sau đó chốt: **muốn cả 5 bước LLM dùng Claude, tự động hoàn toàn**
⇒ A cho brief + backend dùng chung cho 4 bước còn lại (#26).

## 1. Chín lỗ hổng giám khảo tìm ra trong bản A đầu (9aec563) — đã vá cùng trưa
1. **stdout không phải JSON được nhận làm brief** (`parse_cli_output` cũ trả
   `raw, None`): đường DUY NHẤT trong cả ba thiết kế mà chữ SAI (banner tự cập
   nhật, cảnh báo) có thể lên Telegram. Nay là LỖI ⇒ ladder.
2. **Engine chọn TRƯỚC khi ai load `.env`**: `run.py brief`/`telegram close`
   đứng một mình đọc `VNSTOCK_BRIEF_ENGINE` từ os.environ trống ⇒ bước 3 mục 8
   bản cũ âm thầm gửi ladder. `vnstock_claude_cli.engine_for` load `.env`
   (idempotent, override=False) trước khi đọc.
3. **Set trong ctx chết qua JSON**: `write_json_atomic(default=str)` biến
   `financial_tickers`/`realestate_tickers`/`mover_universe` thành chuỗi repr,
   guard so từng KÝ TỰ ở đường `--from-file`. Pack **v2**: ghi list đã sort +
   `ctx_set_keys`, `read_pack` trả set; ctx trong bộ nhớ (đường đêm) KHÔNG đụng
   — guard thấy y hệt `generate_brief`. Pack v1 bị từ chối rõ lời.
4. **Prompt một-dòng-40K trong JSON**: tool Read của skill cắt dòng dài ⇒
   Claude viết từ prompt cụt mà không ai biết. `write_pack` ghi thêm
   `_meta/brief_prompt.md` nhiều dòng; skill đọc file đó.
5. **Không có exe thì sổ không ghi** ⇒ `--show` đếm thiếu đêm rơi ladder. Nay
   `complete()` ghi sổ MỌI kết cục.
6. **Telegram lỗi sau khi Claude viết xong** ⇒ chạy lại tốn call Opus thứ hai +
   trùng dòng memory. Bản SAU guard ghi `_meta/brief_claude.md` TRƯỚC khi đẩy;
   gửi lại bằng `--from-file`. Chữ THÔ ghi `brief_claude_raw.md` để soi guard.
7. **Không ai biết vì sao rơi về ladder** (`run_daily.log` theo máy, marker chỉ
   có `engine`): marker nay `{close, engine, agent, machine, claude_error}`;
   badge doctor `brief_engine` (`brief_engine_verdict` thuần): cấu hình ladder
   → ok; claude + marker claude → ok "do <agent>"; claude + marker ladder →
   warn kèm lý do + lệnh chữa; sổ ClaudeCode 3 ngày liền toàn lỗi → error.
8. **Footer chỉ ghi engine khi là Claude**: nay `_brief_snippet` ghi
   `LAST_BRIEF_AGENT` (kèm `(fallback: model)` bóc từ dòng đầu `_(fallback:
   …)_` — dòng đó không lên Telegram nữa) ⇒ MỌI brief có `🤖 <agent>`.
   `**đậm**` → `<b>` theo dòng (qua whitelist `_sanitize_html`).
9. **Dashboard ⚙️ khoá checkbox Claude** dù có key: `ClaudeAgent` thiếu
   `_ENV_KEY` — thêm một dòng.
Thêm: timeout 900 → **600** (máy còn đăng ký trần 180′ tới khi chạy lại
script; brief từng bắt đầu ở phút 168); `--fallback-model claude-sonnet-5-5`
trong CLI (model thật đọc từ `modelUsage`, nhãn/sổ/footer theo model THẬT,
log `↘ fallback`); `DISABLE_AUTOUPDATER=1` cho tiến trình CLI (binary không
được đổi giữa đêm); `--check` (exe/version/`auth status`/probe 1 chữ bằng ĐÚNG
cờ đêm) để user go/no-go dưới tài khoản task.

## 2. Đo trên CLI 2.1.285 (sandbox, OAuth)
- Không tước context: probe "OK" tốn `cache_creation_input_tokens` **20.346**
  (system prompt Claude Code + CLAUDE.md + 28 skill + MCP), $0,164 quy đổi.
- `--system-prompt <preface> --setting-sources "" --disable-slash-commands
  --strict-mcp-config --tools ""`: **1.636** token, $0,015. Mỗi brief ≈ 13K vào
  ⇒ ~$0,06 quy đổi; thuê bao không trừ tiền.
- `--json-schema '{…}'` → JSON có thêm `structured_output` (dict) và `result`
  (chuỗi JSON), `num_turns: 2`, `stop_reason: tool_use` — parser đọc cả hai.
- `--max-turns` KHÔNG có trong `--help` (đã bỏ); `--permission-prompts none`,
  `--fallback-model`, `--effort` có.

## 3. Backend dùng chung cho 5 bước — `vnstock_claude_cli`
`complete(user, *, system, model, fallback_model, timeout_s, json_schema,
effort, exe, tag) -> (text, err, info)`; `engine_for(step)`: env riêng bước >
`VNSTOCK_LLM_ENGINE` > ladder; `cli_check()`; `outcome_line(tag, …)`.
`vnstock_brief_pack.run_claude_cli` chỉ còn là wrapper (preface làm system,
tag "brief"). Lưới slug: `_all_live_slugs` có cả model chính + fallback;
`_ladder_slugs` (model watch) KHÔNG probe được CLI (chỉ OpenAI-compat) —
tín hiệu sức khoẻ = dòng sổ `ClaudeCode` + badge doctor, chấp nhận.
Kế hoạch #26 (map code đang chạy, nối sau): nấc `("claude-cli", …)` TRƯỚC
`_call_claude` trong `report_digest.digest_call` (reflection ≤3 call/đêm,
debate/tháng, FreeAuditorAgent, digest ≤10/lượt) gated `VNSTOCK_DIGEST_ENGINE`
/`VNSTOCK_REFLECTION_ENGINE`; auditor agent CLI; sentiment + chấm tin gom LÔ
một call/đêm với `--json-schema` (từng call/tin qua CLI = spawn ×N, không hợp);
strategy loop lead agent. Mỗi nấc: lỗi ⇒ ladder như cũ, sổ `ClaudeCode`.

## 3b. #26 NỐI XONG (30/09 chiều) — bốn bước còn lại, cùng backend, lỗi ⇒ ladder
- **Cascade digest** (`vnstock_report_digest.digest_call(system, user, accept,
  feedback, *, step="digest")`): nấc `("claude-cli", _call_claude_cli)` chèn
  ĐẦU danh sách khi `engine_for(step) == "claude"`; các nấc Claude API / GPT /
  free giữ nguyên phía sau ⇒ `accept` (JSON parse được), 1 lượt tự sửa, alert
  cạn thang đều áp cho nấc mới. Trần 300s riêng (`_CLI_TIMEOUT_S`, đè bằng
  `VNSTOCK_<STEP>_CLI_TIMEOUT_S`), model đè `VNSTOCK_<STEP>_CLI_MODEL`.
  Reflection → `step="reflection"` (≤3 call/đêm, chỉ khi có lệnh đóng — KHÔNG
  cần gom lô); auditor Free → `step="audit"`; debate/digest → "digest".
- **Audit**: `make_auditor("auto")` chọn `FreeAuditorAgent` khi engine claude
  (thắng cả `ANTHROPIC_API_KEY`) vì cascade của nó đã có claude-cli đứng đầu;
  `--auditor claude|gpt|free|null` ép vẫn ép. Backend in log
  `[audit] auditor=free:claude-cli`.
- **Sentiment theo lô** (`vnstock_sentiment.score_batch_cli`): `to_score`
  chunk 50 → một call `--json-schema {results:[{i, sentiment}]}` (system =
  `_SYSTEM` đổi câu "1 từ" thành "JSON đủ mọi i"); map `i` → `item_hash` tại
  chỗ (không bắt model chép md5); nhãn qua `_SENTIMENT_MAP`; tin thiếu/lạ ⇒
  ThreadPool `score_one` ladder như cũ; cột `model = ClaudeCode:<slug>` (cache
  chỉ ghi tin có model — nếp 06/08 giữ nguyên). Cổng `cmd_news`
  (`available_provider() or cli_engine_label()`) không còn đòi key free.
- **Chấm tin RSS theo lô** (`vnstock_news_feeds.analyze_items_cli`): ≤8 tin
  một call, mỗi tin `### Tin i=<n>` + khối user chung với `analyze_item`
  (`_analyze_user_text`: tiêu đề, tóm tắt, thân bài Jina vẫn fetch TỪNG tin),
  system = `_ANALYZE_SYSTEM` + "CHẾ ĐỘ LÔ" trả `{results:[{i, nhan,
  tac_dong}]}`; `sanitize_impact` từng câu; thiếu/rỗng ⇒ `analyze_item` ladder;
  `_impact_cut` xoá khi lô chấm được.
- **Train** (`vnstock_train._inject_claude_lead`): engine claude + có CLI ⇒
  `ClaudeCodeAgent(tag="train")` đứng đầu `available` (lead revise/cold-start),
  ladder free thành pool thi đấu tune; chèn TRƯỚC cửa "không agent" nên máy
  không key free vẫn train được. Claude lỗi lúc generate ⇒ candidate bị bỏ
  như mọi agent, pool vẫn có bài — fallback tự nhiên, không cần cửa riêng.
- **`vnstock_brief.ClaudeCodeAgent`** (type `claude-code`, `_ENV_KEY=""`,
  `is_available` = có CLI, `generate` → `vcc.complete(system=_SYSTEM chung,
  tag)`): vào `AGENT_REGISTRY`, `_DEFAULT_AGENT_CONFIGS` **enabled False**,
  `_AGENT_STRENGTH` đầu (bật lên là bản chính). Dashboard ⚙️
  (`brief_agent_settings`) coi agent không key là sẵn sàng khi
  `is_available` ⇒ bật được để A/B với Gemini trên nút brief. Brief ĐÊM vẫn
  đi `vnstock_brief_pack` (không qua agent này). `load_agent_configs` merge
  type mới vào `brief_agents.json` (append cuối) — vì thế train KHÔNG dựa vào
  thứ tự config mà cắm lead theo env.
- Lưới slug: `_all_live_slugs` gom `cls().model` của registry ⇒ Opus 5.5 đã
  có; model watch `_ladder_slugs` bỏ qua type không có provider OpenAI-compat.
- Test `tests/test_claude_steps.py` (18, whitelist): nấc claude-cli đứng đầu /
  step đè / lỗi rơi nấc kế / accept + tự sửa / timeout env; reflection tag;
  auditor auto + step; lô sentiment (map i→hash, nhãn lạ, lỗi, tích hợp
  score_news_batch với DB tmp: 2 tin CLI + 1 tin ladder, engine ladder không
  gọi CLI); cổng news; lô chấm tin (parse, sanitize, refresh CLI-trước-ladder);
  inject lead; registry/strength/is_available/generate; badge dashboard.

## 3c. Thẩm định NGƯỢC #26 (agent đọc lại từng seam, 30/09 chiều) — 9 chỗ vá
Workflow thứ hai (5 reader + 1 critique) review đúng code đã nối, không review
kế hoạch. Ba lỗi chặn và cách vá:
1. **Test không hermetic**: mô phỏng đúng cấu hình desktop sau bước 4 mục 8
   (`VNSTOCK_LLM_ENGINE=claude` + `claude` trên PATH) thì 14 test whitelist
   ĐỎ và mỗi lần chạy suite spawn ~10 lượt Opus THẬT (sổ bị conftest chuyển
   về tmp nên không ai thấy). Vá tận gốc ở `tests/conftest.py` (autouse cho
   MỌI test, cùng họ lưới macro/ledger): `vcc._ENV_LOADED=True`, xoá mọi
   công tắc engine, ghim `VNSTOCK_CLAUDE_CLI_EXE` về đường dẫn không tồn tại
   (`cli_executable()` → None, không rơi về PATH), reset memo. Đã chạy lại
   `--fast` với env desktop giả: xanh.
2. **Không có memo "CLI chết"**: mỗi điểm gọi lại đợi hết timeout ⇒ đêm CLI
   treo: news ⌈N/50⌉×300s + audit + train 2×600 + reflection ≤3×300 + brief
   600 ≥ 60′ cộng thêm trên nền 101–168′ ⇒ chạm trần 240′. Nay
   `vcc._DEAD_REASON`: không exe / OSError / timeout / rc≠0 ⇒ mọi lượt sau
   trong cùng tiến trình trả lỗi NGAY (+1 dòng log, sổ vẫn ghi); lỗi API
   (`is_error`, quá tải) KHÔNG memo. `reset_dead_memo()` cho test/--check.
3. **Không trần số lô sentiment**: cache `sentiment_cache.db` mất (máy mới,
   Dropbox tắt) ⇒ ~2.600 tin = 52 lô. Nay `_CLI_MAX_CHUNKS=6` (300 tin/lượt),
   phần dư **để đêm sau** (không cache, KHÔNG đẩy sang ladder từng tin — đó là
   cơn bão call khác). Lỗi ở lô k giữ kết quả lô 1..k-1.
Sáu chỗ còn lại: (4) `allow_cli=False` cho `score_news_batch`/`refresh` —
dashboard `news_tab` không spawn CLI trong Streamlit (đứng 300s/lô), engine
chỉ ở pipeline; (5) **shim `claude.cmd`** của npm: cmd.exe đọc lại argv nên
`|<>%` và xuống dòng trong `--system-prompt`/`--json-schema` (news/audit có,
preface brief KHÔNG có ⇒ brief chạy được mà news thì không) có thể hỏng —
`cli_executable()` ưu tiên `~\.local\bin\claude.exe` (bản cài native) khi
which trả `.cmd`; `cli_check` báo `shim: true` + `warning`, và probe bằng
`PROBE_SYSTEM` CÓ đủ ký tự đặc biệt (không còn probe hiền "Trả lời ngắn");
(6) audit dùng `--json-schema` (`FreeAuditorAgent.VERDICT_SCHEMA` đi qua
`digest_call(json_schema=)`) ⇒ hết lượt tự sửa JSON; nhãn backend `claude-cli`
thay `free:claude-cli`; engine claude + không CLI ⇒ Free cascade cạn ⇒
unapproved + alert (kêu to, không duyệt suông như Null) — pin bằng test;
(7) `generate_brief` dự phòng bỏ `claude-code` khi engine brief = claude
(đường pack đã tốn 1 lượt Opus mới rơi về ladder — không spawn lần 2 với
system prompt khác); (8) `_cold_start`/`_do_revise` in `[strategy] ✗ <agent>:
<err>` thay vì bỏ candidate câm (Claude viết code rộng hơn AST whitelist thì
biết ngay); feeds không fetch Jina 2 lần khi lô lỗi (`_user_text_tmp`, dọn
trước khi ghi cache); (9) doctor `check_llm_keys` biết engine (không còn warn
"sentiment ❌" khi chấm bằng Claude); `.env.example` có đủ công tắc.
(10, user hỏi "đường B dùng thế nào" 30/09 chiều) `run.py brief --from-file
… --force` trước đó CHỈ bỏ kiểm gói-khác-phiên, KHÔNG vượt cửa marker ⇒ B
không thể thay bản ladder tối nay như đã hứa. Nay `cmd_brief` vượt cửa gác
khi `--force` (in ⚠️ như `telegram close --force`), không `--force` thì in
gợi ý; test `test_cmd_brief_from_file_force_overrides_the_marker_gate`.
Chốt với user còn treo: train hiện là "Claude lead + pool free thi đấu" (mọi
agent vẫn được gọi, Bonferroni theo số candidate) — không phải "Claude trước,
free chỉ khi lỗi"; muốn kiểu sau thì tắt agent free trong ⚙️ (pool rỗng).

## 4. Test
`tests/test_claude_cli.py` (15, whitelist): engine precedence, model/fallback/
timeout env, giấu key + autoupdater, exe env-không-rơi-PATH, cờ tước context,
json-schema/effort/repo_context, parse (cache token, model thật, non-JSON =
lỗi, structured), complete (stdin nguyên văn, system flag, fallback, sổ mọi kết
cục, timeout, rc≠0), outcome_line, cli_check. `tests/test_brief_pack.py` sửa
+ thêm (set round-trip, v1 từ chối, raw/final, review/rate, skill review).
`tests/test_run_pipeline.py` +4, `tests/test_telegram.py` +2,
`tests/test_doctor.py` +2. Fast **2.752 passed** (sandbox, 30/09 chiều; xanh cả khi mô phỏng env desktop `VNSTOCK_LLM_ENGINE=claude`).

# 🤖 U61. BRIEF CHIỀU BẰNG CLAUDE — ENGINE NGOÀI LADDER, LÕI DÙNG CHUNG BA ĐƯỜNG (30/09 sáng)

**Đề bài (user 30/09 sáng, 💻 laptop):** "chất lượng brief cũng như các tác vụ
cần AI chưa tốt — chuyển thành skill làm hàng ngày, đặc biệt là brief". Mẫu
U60 nói rõ vì sao: 6/8 brief close 16–29/09 là flash-lite qua dự phòng, 22/09
trắng; 4 lỗi mới đều là lỗi chữ/số của model yếu mà guard phải dọn sau.

## 1. Quyết định thiết kế — KHÔNG viết lại đường brief, chỉ thay AGENT
Đường brief đã 2 tháng tích luỹ: ctx (`collect_context` + 4 bước refresh) →
`build_prompt` (few-shot, lệnh mở, tin) → agent → `apply_brief_guards` (55) →
`validate_brief_factuality` → `save_brief` → brief_watch → `push_close_brief`
(header/regime/sentiment/recs) → marker `brief_push.json`. Thứ user chê là
đúng một hộp — agent. Mọi đường mới đều phải đi qua các hộp còn lại, không thì
mất parity (dashboard A/B, memory, sổ LLM, doctor badge Phát tối).

`vnstock_brief_pack.py` tách đúng HAI mặt cắt (và không hơn):
- `build_pack(brief_type)` → `{version, brief_type, session, created_at,
  machine, prompt, ctx}`; ctx ĐẦY ĐỦ (kể cả `tickers`) để guard thấy y như
  ladder; `write_pack` atomic vào `_meta/brief_pack.json` (trong kho ⇒ Dropbox
  đưa sang laptop — đường B dựa vào đó). Test canh 5 bước refresh chạy đúng
  thứ tự và `auto_refresh=True` như `generate_brief`.
- `finalize_brief(text, pack, agent_name, model)` → guard → validate → memory
  (`agent_type="claude"`, context bỏ `tickers` như ladder) → brief_watch. Bọc
  ```…``` bị cắt; rỗng sau dọn ⇒ trả rỗng, chỗ gọi rơi về ladder.
- `run_claude_cli(prompt)` → `claude -p <câu lệnh ngắn> --output-format json
  --model <slug> --tools "" --no-session-persistence`, **prompt qua STDIN** (Windows trần 32.767 ký
  tự dòng lệnh; prompt brief ~40K). Đọc `result` + `usage` (cộng cache token
  vào prompt_tokens) + `total_cost_usd`; `is_error`/rỗng/rc≠0 ⇒ lỗi kèm đuôi
  stderr; timeout 900s. Sổ LLM provider **`ClaudeCode`** (tách khỏi
  `Anthropic` = API); OK chỉ khi có chữ thật (nếp #24). Giá Opus 5.5 $4/$20,
  Sonnet 5.5 $2/$10 vào `_PRICES_PER_MTOK` — gói thuê bao không trừ tiền theo
  token, số `--show` chỉ là "tương đương API".
- `cli_env()` **GIẤU `ANTHROPIC_API_KEY`**: `_ensure_env_loaded` đổ .env vào
  os.environ và subprocess kế thừa — có key là CLI lặng lẽ chuyển sang tính
  tiền API thay vì thuê bao. `VNSTOCK_BRIEF_CLI_API_KEY=1` mới cho thấy.

`run.py`: `_brief_engine(args)` = `--engine` > `VNSTOCK_BRIEF_ENGINE` > ladder
(chữ lạ = ladder). `_send_close_brief(args)` dùng CHUNG cho `cmd_brief` (bước
14) và `telegram close` (lệnh tay) ⇒ hai cửa gửi không lệch nhau (vết 19/08).
`_close_brief_via_claude`: pack → CLI → finalize → `push_close_brief(ai_block,
engine)`; hỏng khâu nào in `[brief] ⏱ claude-cli: Ns · ❌ …` rồi `↩ rơi về
ladder agent free` — **brief luôn đi**, đêm Claude chết không mất brief, sáng
đọc log là biết. Marker thêm `engine` (claude / claude-file / ladder) — doctor
`pipeline_reach_verdict` chỉ đọc `close` nên không đổi. `--export-pack` không
qua cửa gác giờ/marker (xuất gói không phải gửi). `--from-file` từ chối gói
KHÁC phiên (gói cũ = brief kể chuyện hôm qua), `--force` để cố ý.

`vnstock_telegram.push_close_brief(ai_block=None, engine=None)`: có `ai_block`
thì KHÔNG chạy `_brief_snippet` (không gọi ladder), dọn markdown bằng
`_snippet_from_text` (tách từ `_brief_snippet` — một luật cho hai đường),
footer `Powered by VNStock Dashboard · 🤖 Claude Code · opus-5-5`. Thứ tự
snippet-trước-header giữ nguyên (test inspect-source 30/07 vẫn xanh).

Skill `.claude/skills/brief-close/SKILL.md` (frontmatter `name/description`
như skill ECC): 4 bước đọc gói → viết → ghi `_meta/brief_claude.md` → bảo user
`run.py brief --from-file`; test canh nó nêu đúng tên gói/lệnh/env.

## 2. Ba đường chạy — user chọn (mục 8 VIEC-DANG-LAM)
| | A. CLI headless trong pipeline | B. Tay bằng skill | C. API trong ladder |
|---|---|---|---|
| Hạ tầng mới | cài CLI + `/login` dưới tài khoản `admin` ở 🖥️ desktop | không | key API |
| Tiền | thuê bao đang có | thuê bao | ~$3/tháng Opus |
| Tự động | có (bước 14) | không | có |
| Lỗi ⇒ | rơi về ladder | user thấy ngay | ladder như cũ |
| Code còn phải làm | 0 | 0 | `ClaudeAgent` lên Opus 5.5 + SDK `anthropic` (skill claude-api: adaptive thinking, streaming, `get_final_message`) |
Khuyến nghị **A**; **B** dùng ngay hôm nay trên laptop khi muốn thay bản ladder
(gói đi qua Dropbox); **C** khi user không muốn CLI trên desktop. **D. Routine
cloud** (Claude Code web theo cron): cloud không thấy Dropbox ⇒ gói phải đi
qua git (nhánh data), `TELEGRAM_*` phải thành secret môi trường, và phải có
cửa chống gửi trùng với bước 14 — nhiều bộ phận hơn hẳn, chỉ làm khi A/C đều
không được.

## 3. Điều CHƯA làm và bẫy vận hành đã thấy trước
- `ClaudeAgent` (API) vẫn Haiku qua `requests` thô, `max_tokens` 2.800 — chưa
  đụng vì user chưa chọn C. Chọn C thì: SDK, `claude-opus-5-5`, thinking
  adaptive, streaming, parity cụt/rỗng với `_openai_extract`, khai slug vào
  `_all_live_slugs` (đã có sẵn Opus 5.5 qua `bp.DEFAULT_CLI_MODEL`).
- Các điểm AI khác ([1] sentiment, [2] chấm tin, [3-6] digest, reflection,
  strategy loop, brief phân bổ) — cùng lõi "gói → chữ → nhận lại", khác gói;
  làm sau khi brief đo được ~1 tuần. Sentiment/analyze là hàng trăm call nhỏ
  mỗi ngày — không hợp CLI headless từng call, hợp API Haiku/Sonnet có ngân
  sách ngày.
- Brief SÁNG vẫn không có task (V5) — engine này chỉ nối vào brief chiều.
- **Task Scheduler + CLI**: task chạy dưới `admin` với PATH của phiên đăng
  nhập KHÔNG chắc có `claude` (npm global / `%USERPROFILE%\.local\bin`) ⇒
  `shutil.which` trả None ⇒ log `❌ không tìm thấy lệnh claude` và rơi về
  ladder; chữa bằng `VNSTOCK_BRIEF_CLI_EXE=<đường dẫn đầy đủ>` trong .env.
  Token đăng nhập CLI nằm ở `%USERPROFILE%\.claude` của `admin` — đăng nhập
  ở tài khoản khác thì task không thấy.
- Gói thuê bao có thể không mở Opus ⇒ `VNSTOCK_BRIEF_CLI_MODEL=claude-sonnet-5-5`.
- **Cờ CLI đã KIỂM trên binary thật** (sandbox có Claude Code 2.1.285):
  `--help` không có `--max-turns` (bản đầu tôi định dùng — bỏ); `--tools ""`
  = "disable all tools" ⇒ đúng một lượt chữ, không đọc file, không hỏi quyền;
  `--no-session-persistence` có. Chạy thử `printf "…OK" | claude -p "…"
  --output-format json --model claude-opus-5-5 --tools ""` → rc 0, JSON
  `{type:result, subtype:success, is_error:false, result:"OK", num_turns:1,
  usage{input 2, cache_creation_input 20.346, cache_read_input 531, output 49},
  total_cost_usd 0.164, duration_ms 2.900}` ⇒ parser đọc đúng khoá. Lưu ý
  **20K token cache_creation là system prompt của Claude Code** — đường A tính
  theo giá API thì mỗi brief ≈ 32K vào ≈ $0,15–0,25 (sổ `--show` sẽ in cỡ đó);
  gói thuê bao không trừ tiền mà trừ hạn mức dùng. Đường C (API thẳng, không
  system prompt Claude Code) rẻ hơn ~3×.
- Bước brief đêm VCI ốm: `build_pack` chạy cùng 4 bước refresh ⇒ #21 (dừng
  sau 3 mã VCI lỗi liền) vẫn áp; thêm tối đa 900s CLI — trần 240′ còn dư.

## 4. Test
`tests/test_brief_pack.py` (25, vào whitelist `--fast`): env/nút vặn, gói đi
đúng đường `generate_brief`, roundtrip atomic, finalize hậu kỳ (ctx đầy đủ vào
guard, memory bỏ tickers, sống sót khi memory/validator hỏng), parse JSON CLI
(cộng cache token, is_error, rỗng, text thường), `run_claude_cli` (stdin, env
không key, cwd repo, sổ OK/fail, thiếu exe không spawn, timeout, rc≠0 lấy
stderr), dòng log, skill khớp hợp đồng. `tests/test_run_pipeline.py` +8 (engine
claude gửi bản Claude + marker engine; CLI lỗi ⇒ ladder + marker ladder; guard
dọn sạch ⇒ ladder; mặc định ladder + cờ đè env; `--export-pack` không gửi/
không marker dù cửa chặn; `--from-file` cùng phiên / khác phiên / --force;
parser; `telegram close` qua dispatch). `tests/test_telegram.py` +3. Fast
**2.689 passed / 49s** (sandbox).

# 🔎 U60. SOI BRIEF 16–29/09 — BA VÁ CŨ ĐÃ ĂN, BỐN LỖI MỚI VÁ CÙNG ĐÊM, BA NGHI CHỜ SỐ (29/09 khuya)

Mẫu: 8 close brief Telegram (16, 17, 18, 22, 23, 24, 25, 29/09) + 2 tin model
watch (T7 19/09, 26/09) + 2 báo cáo tuần lãi suất + brief phân bổ T9 (Gemini
qua lite · Nemotron Super). Không có brief sáng trong mẫu. Nguồn bản chính:
16/09 và 23→29/09 đều `_(fallback: gemini-3.5-flash-lite)_`; 17–18/09 flash
thẳng; 22/09 TRẮNG ("Chưa có brief (agent chưa chạy)", ladder DOWN).

## 1. Ba vá 16/09 (f5e512e) đã ăn từ 17/09 — đo được, không phải tin
- Header `💡 Đề xuất giao dịch (nếu có "Khuyến nghị" trong data)` chỉ còn ở
  16/09 (22:06, trước merge); 17/09 trở đi sạch.
- Watchlist 16/09 bắt đầu "2." — từ 17/09 luôn "1.".
- `điểm -0.00` ở band 16/09 — 17/09 `-0.09`, 18/09 `+0.07`.
- Vùng chết kỳ hạn (#7) chạy đúng: 17/09 `-0.08 → mỏng — sát 0 (lệch dưới
  0.10…)`, 16/09 `-0.17 → ÂM`. Sự kiện sắp tới (#9) loại đúng ngày hôm nay
  (24/09 VPB GDKHQ 24/09 không in). pp vẫn 3 chữ số ở "Dẫn dắt & Tụt hậu"
  (`+0.132pp`) — #10 chỉ thống nhất chỗ khác; ghi nhận, không sửa thêm.

## 2. Bốn lỗi mới — đều lỗi chữ/số của flash-lite, vá bằng guard + test
1. **Mốc Watchlist sai chiều / phi lý** (nặng nhất, người đọc có thể đặt lệnh
   theo): 25/09 GAS "thủng 79,300 · mục tiêu về 80,500" (mục tiêu TRÊN hỗ
   trợ), PNJ "thủng 32,650 · mục tiêu về 33,000", GEE "canh MUA NẾU vượt
   74,300 · mục tiêu 73,900" (TP dưới entry); 29/09 NLG "thủng 21,500 · mục
   tiêu về 10,300" (−52%), SSB "thủng 18,500 · mục tiêu về 10,500" (−43%) —
   số không có trong data; 23/09 GEE "mục tiêu về 69,700" = hỗ trợ; 24/09
   "mục tiêu về thấp hơn" ×3 = ô mẫu `[thấp hơn]` chép nguyên. Prompt đã bắt
   "TỰ KIỂM TRA thứ tự" — đúng nếp CLAUDE.md: LLM phớt chỉ thị ⇒ guard.
   `enforce_watchlist_levels` (sections): kèo GIẢM cần mục tiêu < hỗ trợ <
   hủy, kèo MUA cần SL < entry < TP, mục tiêu cách mốc kích hoạt ≤ 25%; vi
   phạm ⇒ BỎ setup (cùng nếp hygiene bỏ setup neo mốc VNINDEX), ô mẫu "thấp
   hơn" ⇒ cắt vế; chỉ phán khi đọc đủ số ≥ 100 ("pivot 60 phiên" không phải
   mốc). Đứng trước `enforce_watchlist_numbering` để dồn số.
2. **"(Giá 20,000 từ data)"** 24/09, 25/09, 29/09 — chữ "từ data" là ô mẫu
   prompt (`vnstock_brief.py:330`). `enforce_no_price_scaffold` (text).
3. **"Đề xuất giao dịch" bê dòng data thô** 24/09: `DRI: BUY entry=14.8,
   TP=16.1, SL=14 (Strategy #69, conf=0.50).` — 23/09 cùng model viết đúng
   mẫu. `enforce_rec_line_format` (sections) viết lại "MUA vùng · chốt lời ·
   cắt lỗ", giữ số.
4. **`10Y − lãi suất điều hành = -0.00 điểm %`** 23/09: `round(-0.001, 2)` là
   `-0.0`, nhánh nhãn coi là 0 nhưng `:+.2f` in dấu âm. `vnstock_macro` ba
   gauge + hai dốc `+ 0.0` (cùng mẹo `_score2`).
Số thanh khoản trong brief NHẤT QUÁN với ctx (guard `enforce_gtgd_baseline_pct`
bắt % khớp baseline) — lệch giữa hai brief là chuyện ctx, xem mục 4a.

## 3. Hai slug chết model watch réo hai T7 liền (#17, xong)
19/09 và 26/09 09:14 cùng một tin: Groq `qwen/qwen3.6-27b` HTTP 404 "does not
exist" (điểm dùng [2] analyze · [3-6] digest b2 · [7] brief (đã tắt 413) ·
[8] classifier), Cerebras `gemma-4-31b` 404 "archived" ([1] sentiment · [7]
fallback). Ledger 22/09 đếm gemma 10 call · 10 lỗi 404 — cầu dao chỉ chặn
401/402/403 nên 404 tốn call mỗi lần rơi thang. Thay theo thủ tục CLAUDE.md:
qwen → `openai/gpt-oss-120b` (Groq; slug ĐÃ sống trong code ở digest bậc 2 từ
probe 22/07, watch 26/09 không réo ⇒ không cần probe mới); gemma gỡ, không
thay (Cerebras 402 #3, OpenRouter phải để quota cho brief). `_MODEL_MIGRATIONS`
+2 dòng và đổi đích llama-3.3-70b (trỏ vào slug chết là vô dụng — tiền lệ
22/08), `_BRIEF_AGENT_DISABLES` đổi key (413 là trần TIER Groq free, ghế vẫn
hỏng), `_DEAD_SLUGS_22_07` +2, test ladder/sentiment/classifier sửa theo.

## 4. Ba nghi CHƯA đủ căn cứ — cần số, không vá mò
a. **GTGD cả ngày hụt vì mã lớn cách ly** (#18). 17/09 "+27% so với phiên
   trước" và 18/09 "+26%" trong khi brief hôm trước tự in 15.489 · 16.004 tỷ
   — % khớp ctx (guard bắt) ⇒ baseline `_gtgd_baselines` khác con số brief
   hôm trước in. Cổng coverage đếm SỐ MÃ (`count < 70% trung vị` ⇒ loại ngày)
   nên 45 mã cách ly gồm FPT · VPB · GAS · TCX · PVS đứng 13 ngày mà cổng
   không thấy: Σ hụt vài nghìn tỷ, brief "thấp hơn TB" một phần là thiếu
   data. **Vá 30/09 02:10 (#18):** runner giữ giá×KLGD theo TỪNG mã 22 bar →
   `heavy_missing` (mã TB ≥ 50 tỷ/phiên không có bar phiên mới nhất, còn bar
   trong 45 ngày) + `excl_missing_totals` (total từng ngày trừ đúng giá trị
   ngày đó của các mã thiếu) ⇒ brief so prev/TB5/TB20 trên CÙNG tập mã, prompt
   + guard ghi "(chưa gồm N mã lớn thiếu data)", doctor badge `gtgd_coverage`.
   Mức tuyệt đối không bù bịa — chỉ % và chú thích. Chưa có thước đo thật:
   phát kế in badge + dòng prompt là phép đo (45 mã đã chữa nên có thể ok ngay).
b. **LNH ON 6,84 → 0,48% trong 5 phiên, 1W 4,20 → 6,20** (#19): chênh ON−1W
   5,7 điểm là dị thường; gauge `liquidity_spread` phán DƯ THỪA +1,00 và bơm
   +0,10 vào điểm band (allocation 29/09 in đúng dòng đó). Sandbox không gọi
   được SBV, Finhay không có chỉ tiêu LNH ⇒ user chạy `--show` rồi `--diag`
   (01:20, fetch tươi): nguồn in y hệt cache — 28/09 ON 0,48 · 1W 6,20 · 2W
   6,18 · 1M 6,60 · 3M 6,99 · 6M 7,69; 25/09 ON 0,87 · 1W 4,73; 24/09 ON 1,10 ·
   1W 5,06 ⇒ parse ĐÚNG, số là của SBV. Không đoán vì sao SBV công bố thế
   (dồn cuối quý? doanh số ON mỏng?) — gauge chỉ cần biết ON đang không đại
   diện: `liquidity_spread` thêm `_TENOR_DIVERGENCE_PP = 1.5`, |ON − 1W| vượt
   ⇒ `dir 0` + nhãn in cả hai số "phân kỳ … không kết luận"; allocation nhận
   dir 0 ⇒ hết +0,10 vào điểm band; 1W đồng thuận hoặc thiếu 1W thì luật cũ.
   Test với đúng số 28/09 và 25/09.
c. **Thiếu brief hai thứ Hai 21/09 và 28/09; 22/09 ladder DOWN** (#20).
   **28/09 đã rõ (23:30, `⏱ TỔNG [2026-09-29 00:13] 178.2 phút … brief 0s`):**
   pipeline khởi động 21:15, sync 7.272s (VCI ốm → `⚡ Fallback KBS: 1027 mã`,
   `partial: 151` lúc 23:11), bước brief tới lúc 00:13 T3 → `_should_push_close`
   chặn "chưa tới 15:00" vì so NGÀY LỊCH — lượt tràn nửa đêm bị coi là chạy bù
   sáng. Bug cùng họ #14 (ngày lịch vs phiên phủ), vá #20a: `_close_session_date`
   = `session_covered_at`, cửa nhận `started` (giờ khởi động lượt, cmd_all gắn
   `args.pipeline_started`) — khởi động trong ngày phiên thì tràn nửa đêm vẫn
   đẩy, chạy bù sáng vẫn chặn (15/08). Không có cửa cũ thì marker đã ghi 29/09
   và brief T3 tối đó bị coi là trùng — cùng một lỗi, hai mặt.
   `run_daily.1.log` (đọc 23:55): `⏱ TỔNG` có 11→18/09 và 22→25/09, KHÔNG có
   21/09; `[brief]` nhảy msg 271 (18/09) → 275 (22/09), 272/273 = hai tin T7
   19/09, 274 = alert ladder DOWN 22/09. Sổ LLM 21/09 lại có bộ agent brief
   (Mistral 4 · super 3 · ultra 2) ⇒ 21/09 pipeline CHẠY tới brief rồi CHẾT
   giữa chừng. **Đoạn log (00:20) chốt: trần 180′.** Khởi động 20:12:20; sync
   5.940s (KBS 1.165 mã) · validate 202 · screener 1.363 · news 1.041 · test 242
   · audit 460 · train 739 · reflection 66 ⇒ 168′ khi `=== brief ===` mở lúc
   ~23:00, 25 dòng sau đã là header phát 22/09 ⇒ bị giết ~23:12. Doctor đếm 133
   call trước brief = sổ cuối ngày ⇒ bước brief chưa ghi nổi một call; các call
   Mistral/super/ultra là của `strategy_loop` (train, lead=Mistral Small — nay
   Mistral đã tắt) và auditor. Vá: cap script 180 → 240 (đăng ký lại), log
   từng agent (#21a). 28/09 xác nhận bằng dòng `[brief] bỏ qua: chưa tới 15:00
   (hiện 00:13)`. Task lịch khoẻ (LastTaskResult 0). 22/09: flash-lite 46/46
   lỗi, flash 7/13, tin Telegram cắt trước dòng OpenRouter ⇒ chưa biết nấc
   cuối chết vì gì. Sổ 22/09 (`--show --day`) bác giả thuyết quota: OpenRouter
   super 3 call · 3 OK · 0 lỗi. **Đoạn log thô bước brief 22/09 (01:00) mở ra
   gốc rễ của #21:** 21:49 → 22:17 là 52 dòng `vnstock.core.utils.client -
   ERROR … iq.vietcap.com.vn … Read timed out (read timeout=30)` = 28′ trong
   30,8′ — `_auto_refresh_events` → `refresh_upcoming` gõ VCI cho ~52 mã (VN30
   ∪ movers) đúng đêm VCI ngã, không có cửa dừng. Bước brief "phình" các đêm
   22→29/09 là VCI, KHÔNG phải Gemini; 21/09 cùng bão này góp phần đẩy qua trần.
   Vá #21b: dừng sau 3 mã lỗi liền, giữ cache, không ghi đè khi 0 mã OK. Phần
   LLM 22/09 chỉ ~2′ với đúng 1 call OK mà bản trắng (#24) — dòng log từng agent
   ở phát kế sẽ nói. Sổ 21/09 còn lộ #23: OpenRouter trả body không
   `choices`/`message` → `KeyError` thay vì in lỗi provider. **Vá 02:40 (#23 +
   #24 cùng gốc):** ba agent mổ body qua `_openai_extract` — body lỗi HTTP 200 =
   lỗi provider (transient 5xx/429 trong body → đợi 20s gọi lại), content RỖNG
   = lỗi agent ghi sổ fail + sang dự phòng; sổ chỉ ghi OK khi có chữ thật. Đọc
   code thấy bản cũ ghi sổ OK TRƯỚC khi mổ content — đúng dấu vết "+1 OK mà
   brief trắng" 22/09; log từng agent phát 30/09 sẽ xác nhận hay mở lại.

## 5. Ghi nhận khác (không vá)
- Bản Nemotron Super của brief phân bổ: thập phân kiểu VN ("-0,34", "25 917"),
  lẫn "weakening"/"dominer", đọc sai nghĩa tilt (+1 band = phòng thủ hơn).
  Bản phụ, chỉ để đo 4c: super ra ĐỦ dài (headroom 5.200 ăn) nhưng chất
  lượng dưới flash-lite.
- Báo cáo HedgeAcademy 10/07 (81 ngày) vẫn là báo cáo DUY NHẤT tạo tilt +1;
  band B4 hiện = band data B3 + tilt. Thêm báo cáo mới hay để cửa sổ tự rụng
  là quyết định của user.
- 23/09: Watchlist "FRT GIẢM TỶ TRỌNG nếu thủng 139,000" và cùng brief "Đề
  xuất: FRT MUA vùng 140" — hai nguồn (LLM pivot vs backtest) nói ngược
  nhau trên một mã; guard không bắt vì hai câu đều có điều kiện. Ghi nhận.
- Mistral đã tắt 22:50 (U59 §4) — không xuất hiện trong bản chính brief nào.
- 🖥️ desktop merge `34f614e` + `--fast` 2.640 passed / 137s lúc ~23:20, rồi
  merge `1a45a91` (cửa brief chiều) + `--fast` 2.643 passed / 327s ~23:50 —
  rồi merge `a4407b0` (log từng agent + cap script 240) + `--fast` 2.645
  passed / 102s ~00:40 — cả bốn đợt vá có hiệu lực từ phát tối 30/09; 327s
  ở lượt giữa là máy bận nhất thời (lượt sau về 102s). 00:50 chạy lại script
  Admin: `PT4H` ✅ nhưng script chọn `C:\Python314\python.exe` vì shell Admin
  chưa kích hoạt venv (script chỉ dò `.venv` trong repo rồi `python.exe` trên
  PATH) — suýt phát tối 30/09 chạy bằng Python không thư viện. 00:55 đăng ký
  lại với `-PythonExe C:\Users\admin\.venv\Scripts\python.exe` ✅. Script nay
  nhận `$env:VIRTUAL_ENV` và TỪ CHỐI Python hệ thống trừ `-AllowSystemPython`
  (`4793ce3`). Bài học: lệnh Admin nào cũng phải ghi rõ "kích hoạt venv trước".
- 01:15 merge `e3ffab4` (cửa dừng VCI trong `refresh_upcoming`), 01:40 merge
  `22e1678` (gauge thanh khoản phân kỳ) — `--fast` 2.647 rồi 2.648 passed /
  ~101s. Phát tối 30/09 là phép đo của TÁM bản vá trong một đêm: 4 guard brief,
  slug mới, cửa brief phiên phủ, log từng agent, cap 240 bằng venv, cửa dừng
  VCI, gauge thanh khoản. Đọc: `⏱ TỔNG` + `[brief] ⏱` + `[events]`.

# 🧭 U59. 29/09 SAU 13 NGÀY NGHỈ — 45 MÃ CÁCH LY MÙA QUYỀN, FPT HAI BẬC TRONG MỘT NĂM (29/09)

## 1. Sổ cách ly dồn 45 mã — 44 mã chữa bằng một lệnh, đúng thiết kế V1

Pipeline tự chạy đủ 13 ngày không ai ngó (badge Phát tối ✅ 29/09, test full
3.235 chạy trong phát). Cửa gác V1 giữ 45 mã ngoài kho suốt mùa quyền — TCX
1,2000× ĐỨNG 13 ngày kể từ 16/09, tức VN30 thiếu bar hai tuần mà brief vẫn ra
(rổ còn 29 mã, không có badge nào réo riêng chuyện VN30 thiếu mã — xem #15).
`--from-drift-ledger --whole-series` chạy thử rồi `--apply` 21:14: 44/45 ✅
(TCX/PVS 1,2× · VPB 1,2603× · GAS vách 21/09 · SZL lệch đều 1,7889× lấy nguyên
nguồn · CMP kho đứng từ 01/12/2025 · XHC hệ số đo trên 1 bar). Bẫy phụ: đầu
ra qua ống `|` trong PowerShell chết im (UnicodeEncodeError vào ống) — phải
`$env:PYTHONUTF8='1'` + `[Console]::OutputEncoding=UTF8` trước.

## 2. FPT — `--whole-series` từ chối ĐÚNG: hai đợt quyền trong 365 ngày

`--explain` 29/09: tỉ lệ trung vị 1,1151× spread 1,0139, 12 bar đuôi đều
1,1000× ✗, "81/242 bar (33%) KHÔNG cùng cơ sở" ⇒ cổng outlier ≤5% chặn. Không
phải tool hỏng: lịch quyền Finhay (`get_stock_events`) có cổ tức TIỀN 1.000đ
GDKHQ 28/05/2026 (bậc 1,0137 ≈ 1.000/72.500) và cổ phiếu THƯỞNG 10:1 GDKHQ
21/09/2026 (1,10 trọn chuỗi vì VCI back-adjust). 1,10 × 1,0138 = 1,1152 khớp
trung vị — hai bậc chồng nhau, `--whole-series` không có hệ số nào đồng đều để
mà nhân.

Chữa 22:39 bằng `--ticker FPT --break-date 2026-05-28`:
- probe tại vách 1,0138× (20 bar trước · 22 bar sau) ⇒ `warehouse_basis`;
- `last_divergent_day` thấy bar lệch nguồn cuối là 18/09 ⇒ kéo `cut` tới
  19/09 (`scripts/rebase_ticker_history.py:1124-1135`) — đợt thưởng 21/09
  được vét luôn mà không cần khai;
- nguồn phủ từ 2006-12-13 (4.931 bar) ⇒ **4.924 bar lấy thẳng nguồn · 0 nhân
  hệ số** — một lượt xử cả hai bậc, không bar nào suy từ hệ số;
- khối lượng giữ nguyên: nguồn/kho 1,0000× (VCI không chỉnh volume), sự kiện
  quanh vách là cổ tức tiền ⇒ không đổi số cổ phiếu;
- 21 file ghi nguyên tử, sao lưu `_meta/backup_rebase/FPT_20260929-223915`,
  tự kiểm "chuỗi đã liền — không còn vách trong 365 ngày · bộ dò MỨC cũng
  sạch", xoá khỏi sổ cách ly.

Tool KHÔNG nối bar mới — nó chỉ ghi đè bar ĐÃ CÓ (`mask_old = t < cut`,
~dòng 1199). Mã "đứng 11 ngày" sau rebase vẫn đứng ⇒ `python
vnstock_updater.py --tickers FPT` (không `--skip-if-done` nên không đụng marker
`pipeline_status.json`) nối 7 bar 19→29/09 trong 1s. `--explain` sau đó:
4.931 bar, đứng 0 ngày, 1,0000×/1,0000, 12/12 bar đuôi ✓, sổ cách ly không,
SẠCH. Doctor 22:39: "Lệch cơ sở — không mã nào bị cách ly" ✅.

Câu tool in "còn bậc SAU vách … (mã bị rebase nhiều lần)" là chữ chung; ở ca
này nguyên nhân là ĐỢT QUYỀN THỨ HAI sau vách. Sửa chữ ghi vào #16 cùng hai
việc đã có (`--explain` in PHÂN ĐOẠN tỉ lệ theo thời gian; `--whole-series`
nhận nhiều bậc khi nguồn phủ trọn lịch sử kho).

## 3. Bài học

1. `--whole-series` từ chối ⇒ đọc "x% bar KHÔNG cùng cơ sở" như SỐ ĐỢT QUYỀN,
   tra lịch quyền TRƯỚC khi nghi kho hỏng. Mùa quyền nào VN30 cũng có mã dính
   hai đợt trong một năm (FPT, VNM…).
2. `--break-date` = ngày GDKHQ của đợt CŨ hơn; đợt mới hơn `last_divergent_day`
   tự vét khi nguồn phủ tới bar cuối kho. Ba điều kiện trước `--apply`: probe
   không phán `aligned` · `nguồn phủ từ` ≤ bar đầu kho · `0 nhân hệ số`.
3. Sau rebase mã "đứng" N ngày vẫn đứng — chữa xong chưa có bar mới. Chạy
   updater riêng mã đó ngay, đừng đợi phát tối mai rồi tưởng rebase hỏng.

## 4. Còn treo tối 29/09

- Sổ LLM 29/09 (`--show` 22:45): 66 call · 30 OK · 36 lỗi · $0,0042. Chuyện
  chính: **Gemini flash 23 call · 3 OK · 20 lỗi 503** cả ngày, flash-lite gánh
  17 OK (5 lỗi read timeout 15s = cỡ timeout đường sentiment
  `vnstock_sentiment.py:193`; brief agent dùng 90s). Bước brief 1.743s là hệ
  quả: mỗi lượt Gemini = 503 → đợi 20s → 503 → sang lite. Badge doctor lại
  réo **Mistral 10 call · 0 OK · 10/10 429** — giọng thứ tư user giữ 11/08
  (`vnstock_model_watch.py:86`) 0 OK từ 15/09 (quota) · 16/09 (429 ×2) · 29/09
  ⇒ chết hai tuần, mỗi lượt tốn 2 call + 20s chờ (đợi rồi gọi lại, đúng thiết
  kế 15/09) và giữ badge sổ LLM ⚠️ vĩnh viễn — badge luôn vàng thì người đọc
  học cách bỏ qua, và hôm nay nó che đúng chuyện flash. Cầu dao cố ý KHÔNG
  chặn 429 (Gemini 429 sáng vẫn phải được gọi chiều) nên không vá bằng code;
  user TẮT Mistral 22:50 cùng tối (`save_agent_configs` → `_meta/brief_agents.json`,
  trong kho nên cả hai máy cùng thấy): ladder brief còn gemini · openrouter ·
  cerebras. Model watch T7 vẫn probe Mistral (`_ladder_slugs` gom từ
  `_DEFAULT_AGENT_CONFIGS`, không đọc cờ `enabled`) và phân biệt hết hạn mức
  với chết ⇒ báo cáo cuối tuần là chỗ biết lúc nào bật lại. Cerebras 402 1 call/ngày = cầu dao ăn đúng (#3 treo).
  OpenRouter super 5/5 · ultra 4/4 OK, suy nghĩ 53%/79% (4c) — bản có đủ dài
  không thì soi brief.
- Brief hai tuần 16–29/09 user sắp gửi để soi; brief bước 14 tối 29/09 1.743s
  (flash 3/23 OK, 503 cả ngày) chưa có dòng log tách theo agent.

# 🧭 U58. BADGE "PHÁT TỐI — ĐÃ TỚI KHO NÀY CHƯA" (#11) VÀ HAI LỖ HỔNG ĐƯỜNG CHẠY BÙ (16/09)

## 1. Vì sao cần badge riêng

Vụ 07/09 (U56): desktop tắt sync Dropbox, laptop sáng 08/09 vẫn VNINDEX ✅ vì
`check_warehouse` cố ý dung sai 2 phiên (EOD về trễ); chỉ hai badge tuổi data
nói bóng gió. Câu cần nói thẳng là "phát tối chưa tới BẢN KHO này", và nó có
hai cách xảy ra: pipeline không chạy HOẶC Dropbox tắt sync. Hai marker nằm
trong kho trả lời được: `pipeline_status.json[updater]` (ghi cuối bước updater)
và `brief_push.json` (bước 14/14).

## 2. Ba luật rút từ vòng phản biện (3 góc nhìn độc lập trên bản nháp)

Bản nháp đầu so `last_success_date >= phiên` và cho 90′ ân hạn. Ba góc nhìn
(mốc thời gian hai máy · nếp doctor · ca biên) cùng bắt hai lỗi cấu trúc:

1. **So PHIÊN PHỦ, không so ngày lịch.** Marker updater đóng dấu `get_today_vn()`
   = ngày CHẠY. Chạy bù 08:20 thứ 3 chỉ lấy được bar tới thứ 2 mà dấu là thứ 3
   ⇒ badge khen "phát 15/09 đã tới" ba lần liên tiếp trong khi bar 15/09 không
   có. Đúng bất biến CLAUDE.md "độ tươi so CẢ GIỜ": phiên phủ = trước 15:05 là
   phiên trước, T7/CN là thứ 6. Nay marker ghi `covered_session`; marker cũ suy
   từ `last_run_at`.
2. **Cùng đêm không bao giờ kết luận "brief chưa".** Doctor là bước 13, brief
   bước 14: kết luận "brief CHƯA — pipeline đứt" ghi vào `doctor_status.json`
   (đi qua Dropbox) là sai suốt 24 giờ ở cả hai máy — đúng loại badge nói dối
   repo đã sợ nhất. Đo marker→doctor bước 13 = 61′/69′/88′ (marker ghi trước
   rollup/fix-units/auto-heal 5–38′ + 11 bước ~45–55′), nên 90′ cũng không đủ.
   Nay: cùng ngày phiên ⇒ luôn "đang tới … xét lại từ sáng mai"; ngày khác ⇒
   cửa sổ 150′ (trần task 180′) rồi mới warn.
3. **Hạn phát tối 23:00**, không phải 21:00: 21:00 chỉ đúng cho phát khởi động
   đúng giờ (18:00 + 180′); tuần 08–14/09 toàn bật muộn 20:15–20:40, xong tới
   23:15. Sáng hôm sau verdict không đổi (phiên đã qua ngày là tới hạn).

Thêm: cờ `VNSTOCK_PIPELINE_BRIEF=0` sống trong `.env` — CODE không đồng bộ —
nên máy kia không thể biết ⇒ `cmd_brief` ghi `skipped {session, reason,
machine, at}` vào `brief_push.json` chung (không đụng `close` để cửa gửi tay
còn mở); mốc có tz quy về giờ VN (không phải giờ máy chạy test — sandbox là
UTC); đồng hồ lệch vài phút giữa hai máy không được biến "vừa ghi" thành "đứt";
`errors` rác không nổ; `doctor_status.json` + caption sidebar có `machine`.
Chuỗi sửa có nhãn máy đúng nếp (⇄ CẢ HAI kiểm Dropbox TRƯỚC · 🖥️ DESKTOP
`Get-ScheduledTaskInfo` · ○ MỘT LẦN gửi tay). Parity test: `_session_for` ↔
`run._close_session_date`, `_BRIEF_OFF` ↔ `_OFF_VALUES` (cmd_brief nay nhận
"no" là tắt, khớp badge Kill-switch).

## 3. Hai lỗ hổng đường chạy bù (StartWhenAvailable) — user nêu cùng buổi

(1) Máy tắt 18:00 T2, bật 08:20 T3: sync bù đóng dấu T3 ⇒ task 18:00 T3
`is_already_done_today` thấy "hôm nay + success" ⇒ "✓ đã chạy hôm nay", bỏ
sync; bar T3 vào kho tối T4; brief chiều T3 (cửa `_should_push_close` chỉ xét
≥15:00) dựng trên bar T2 và ghi `close: T3`. (2) Chạy bù T7: `run_update(
skip_weekends=True)` về sớm (không marker) nhưng brief T6 vẫn đẩy (luật 15/08)
⇒ brief T6 trên bar T5, bar T6 chờ tới T2 18:00.

Vá (nhỏ, có test fail-trước/pass-sau ở `test_pipeline_status_gate.py`):
`vnstock_rollup.session_covered_at(now)` + `marker_covered_session(status)` +
`is_already_done_today(job, now=None)` so phiên phủ; `updater_status_update`
ghi `covered_session`; rollup mặc định cuộn phiên phủ (chạy bù sáng cuộn bar 1m
hôm qua — trước đây nhắm `bars_<hôm nay>` không tồn tại và bar 1m hôm qua
KHÔNG BAO GIỜ được cuộn) và ghi `covered_session`; `run.py sync` thêm `--force`
cho updater T7/CN (`--force` chỉ tắt `skip_weekends`, đã đọc `main`). Mốc
15:05 mirror `vnstock_brief.SESSION_CLOSE_CUTOFF` với test parity (không import
vnstock_brief vào rollup — nặng và đảo tầng).

## 4. Phép đo

* Sáng 17/09 🖥️ desktop: badge `Phát tối` phải ✅ "phát tối 2026-09-16 đã tới
  kho này — sync … · brief chiều đã đẩy" (chạy `python run.py doctor` tay;
  badge bước 13 chụp trước brief nên ghi "đang tới" là bình thường).
* Lần chạy bù kế tiếp (máy tắt lúc 18:00): log phải in `--force` T7/CN, marker
  `covered_session` là phiên TRƯỚC khi chạy sáng, và task 18:00 cùng ngày KHÔNG
  in "✓ Updater đã phủ phiên".

## 5. Đo tối 16/09 — badge đúng cả hai nhịp, brief sống nhờ dự phòng

Doctor 21:30 (giữa phát): ✅ "đang tới kho này — sync partial 200 lỗi lúc 21:16
· brief chiều chưa (phát còn đang chạy…)". Doctor 22:10 (sau ⏱ TỔNG 22:06): ✅
"đã tới kho này … brief chiều đã đẩy". Phát khởi động 20:25 (bật muộn — đúng
lý do chọn hạn 23:00), TỔNG 101,4′: sync 3.415s · screener 776s · brief 624s.

Brief close 16/09 tới Telegram 22:06 CÓ AI Outlook, header
`_(fallback: gemini-3.5-flash-lite)_`: Gemini flash 503 ×6 trong ngày, vòng
base đợi 20s gọi lại rồi rơi xuống flash-lite (14/14 OK) — bản vá 661b193 cứu
brief ngay đêm tự động đầu tiên. Cerebras 1 call (cầu dao), Mistral 429 ×6,
OpenRouter super 1 OK/1 cụt ở trần 8.000 (4c; call cụt không mang usage nên
chưa đọc được suy nghĩ), ultra 1/1.

Soi brief thấy ba lỗi chữ, đều deterministic, vá cùng tối (50 guard):
`enforce_no_header_scaffold` thêm dạng "(nếu có …)" (header 💡 tới Telegram
nguyên chú thích template); guard mới `enforce_watchlist_numbering` dồn số sau
khi hygiene/eligibility bỏ mục (brief chỉ còn "2. **DCL**"); `_score2` trong
canon xoá "-0.00" (điểm −0.004 qua `:+.2f`).

Cùng tối: ACG·BAL·BHN rebase 3/3 (BAL = ca 3 bar lọt cửa KBS 8% sau vách
27/08 — bộ dò MỨC bắt); TCX `--explain` sạch 1,0000× TRƯỚC GDKHQ 17/09 làm
mốc; phát hiện #15 (KBS từ chối >8% không vào sổ cách ly).


# 🧭 U57. TỐI 14/09 TRÊN DESKTOP — KHO ĐÃ SYNC ĐÚNG, UPDATER LƯỠNG CỰC LÀ VCI TIMEOUT, DỪNG SỚM ĐỔ LỖI SAI CHỖ

Ba việc trong một tối, cùng một nguồn dữ liệu: `run_daily.log` + `triage` +
`rebase --from-drift-ledger` chạy thử + ledger LLM. Toàn bộ trên 🖥️ desktop
sau khi Dropbox đã bật lại (U56).

## 1. Kho đã về đúng chiều — sổ cách ly 25 mã là lệch MỚI, không phải 70 mã cũ

`triage` in 25 mã, không có VIM/HU4/SGR/PJS/ND2/CHP của bản laptop ⇒ Dropbox
đưa bản desktop lên, không đè ngược. 22/25 kho đứng 0–7 ngày = sự kiện quyền
tháng 9 (HTN 1,50 · VIB 1,0952 · DGC 1,21 · PHR 1,84). TW3 đứng 175 ngày (kiểu
GH3). Conflicted copy: 4 file `_meta` ngày **10/09** (doctor_status, llm_ledger,
market_news_cache, test_status) — sinh đúng lúc bật lại sync, đều là file ghi
lại mỗi phát ⇒ xoá, không mất gì.

**Đọc sai lúc 22:04, sửa lúc 23:52:** 8 mã `0d` tôi đoán là "gác đã thả, sổ
chưa xoá, chạy thử sẽ in `↩ kho ĐÃ SẠCH`". Chạy thử nói ngược: BMI vách
09-08, DVN mức lệch dừng 09-10, ELC 09-09, DVP 06-01 rồi lệch tiếp tới 09-07 —
2–4 bar cuối khớp nguồn, phần trước lệch 3–7%. Tức bar mới vào kho bằng đường
KHÔNG qua V1. Đường duy nhất như thế là nhánh fallback KBS (`update_ticker`:
"Bỏ qua nhánh fallback: data KBS đã có cửa gác riêng `reconcile_fallback_df`,
ngưỡng 8%") — và 14/09 đúng là đêm fallback 1.245 mã. Ngưỡng 8% rộng hơn V1
(1,2%) đúng bằng dải lệch của 8 mã này (2,3–8,4%). Chưa chứng minh từng mã,
nhưng đủ để ghi bất biến vào CLAUDE.md: **`0d` trong triage ≠ sạch.**
`rebase --whole-series` xử được ca này (nó tìm vách rồi rebase phần trước).

## 2. Updater lưỡng cực = đêm VCI timeout, KHÔNG phải rate-limit

| phát | updater | dòng tổng kết |
|---|---|---|
| 09/09 | 6.501s | `⚡ Fallback KBS: 1130 mã` · `Updated 1546 · Errors 150` |
| 10/09 | 263s | `Updated 1617 · Errors 0` |
| 11/09 | 274s | `Updated 1613 · Errors 0` |
| 14/09 | 4.860s | `⚡ Fallback KBS: 1245 mã` · `Updated 1524 · Errors 181` |

`rate-limit, chờ` trong phát 14/09: **0 dòng**. Chậm là vì mỗi mã đợi VCI
timeout (30s × retry) rồi mới rơi sang KBS. Hệ quả kép: (a) marker
`pipeline_status` updater đứng ở 11/09 vì `vnstock_updater.py:889` chỉ ghi khi
`error == 0` — 1.524 mã đã cập nhật mà doctor đọc thành "chưa chạy" ⇒ việc #12;
(b) 23:17–23:52 VCI vẫn timeout ~40 lần ⇒ rebase 25 mã dừng ở 13.
Trần task thật là **180′** (ps1 nâng 19/08), CLAUDE.md ghi 120′ là cũ — đã sửa.
Phát 14/09: 140,8′ (đệm 39′); screener 1.117s và test 302s cao bất thường,
trùng lúc user chạy triage/đọc log + Dropbox đang upload — xem lại đêm 15/09.

## 3. DỪNG SỚM đổ lỗi sai chỗ — đã vá

`main()` đếm rc=2 liên tiếp và in "hỏng ở bước GHI … tạm dừng Dropbox/AV" —
trong một lượt CHẠY THỬ không ghi gì, khi ba mã liên tiếp hỏng vì
`RetryError(ConnectionError)` và "nguồn trả rỗng". Vá: `_mark_fail(kind)` ở ba
chỗ (không fetch được nguồn / nguồn rỗng / ghi hỏng) + `_is_network_error`
đi theo chuỗi `__cause__`; dừng sớm in đúng nguyên nhân (nguồn / ghi / hỗn
hợp); TỔNG tách "KHÔNG chữa được" (từ chối đo) với "CHƯA LẤY ĐƯỢC NGUỒN (thử
lại)" và "chưa tới lượt", lời khuyên `probe_price_basis` chỉ còn cho nhóm đầu.
Lưới: `tests/test_rebase_write_failure.py` (+3 test, 281 passed bộ rebase).

## 3b. Sáng + trưa 15/09 — 24/25 mã xong, VCI khoẻ/ốm theo giờ

06:34 `--ticker BMI --explain` trả lời trong vài giây (vách thật 08/09: kho
1,0363× tới hết 07/09, 1,0000× từ 08/09 — sổ cách ly đúng, `0d` không phải
sạch). 06:41–07:31 chạy thử 25 mã: 14 OK, 5 không lấy được nguồn (IST PDN PTB
SHC SVT, mỗi mã ~6 timeout × 30s), dừng sớm in đúng "KHÔNG LẤY ĐƯỢC NGUỒN" +
tổng kết ba nhóm — bản vá mục 3 chạy đúng ngay lần đầu. 12:40 ghi 14 mã bằng
`--ticker` liệt kê: **14/14 trong 70 giây, 0 timeout**. 13:23 `--from-drift-
ledger` chạy thử 10/11 rồi ghi **10/11 trong 45 giây**. Cùng một máy, cùng
một lệnh, cùng một nguồn: 06:40 và 23:00 ốm, 12:40 và 13:20 khoẻ ⇒ VCI có
giờ đông giờ vắng; lượt sau thăm dò một mã trước rồi mới chạy lô.

Hệ số đo được: PHR 1,8426 (246 bar, spread 1,0003) · HTN 1,5000 · PTB 1,2624
(vách 11/05 + bậc sau vách tới 04/09) · DGC 1,2064 · HUB 1,1372 · SVT 1,1065 ·
VIB 1,0950 · HAD 1,0938 · IST 1,0929 · DP1 1,0852 · VLW 1,0837 · TIP 1,0738 ·
DVP 1,0690 (vách 01/06 + bậc tới 07/09) · ELC 1,0699 · DIG 1,0600 · DVN 1,0580
· DHG 1,0516 (vách 07/05 + bậc tới 11/09) · SZC 1,0541 · SHC 1,0502 · DMC
1,0435 · VAV 1,0385 (1 bar nhân hệ số) · BMI 1,0363 · PTB… · PDN 1,0233 · DNC
1,0204. Nguồn/kho khối lượng = 1,0000× ở MỌI mã ⇒ VCI back-adjust GIÁ, không
đụng khối lượng ⇒ tool giữ nguyên khối lượng là đúng theo nguồn.

**TW3 bị từ chối** `--whole-series`: "tỉ lệ LỞM CHỞM ngay ở phần LÕI: thô
1,0000× → 1,0837×". Kho đóng băng từ ~23/03 (176 ngày) nên vùng chồng lấn
kết thúc ở tháng 3; trong vùng đó tỉ lệ đổi từ 1,0000 sang 1,0837 = có vách
mà bộ dò bậc không gọi tên (nghi dưới sàn 5 bar/phía sát ngày đóng băng).
Đường đi: `--explain` đọc đuôi ⇒ `--break-date` ⇒ `--apply`. Không gộp vào lô
— đúng như triage nói, chữa mù là nhân bản số sai lên trọn lịch sử.

**13:29–13:33 — xong.** `--explain`: 38 bar chồng lấn trải 189 ngày (mã UPCoM
thưa giao dịch), 11 bar đuôi đầu 1,0834×, bar cuối 2026-03-23 khớp 1,0000×;
13,00 ÷ 1,0834 = 12,00 ⇒ 23/03 chính là phiên GDKHQ, kho đóng băng ngay sau.
Bộ dò MỨC đòi ≥2 bar sau vách (`LEVEL_BREAK_MIN_AFTER`), có đúng 1 ⇒ "cần mắt
người". `--break-date 2026-03-23` (đường VNM 19/08): hệ số 1,0837× (5 trước ·
1 sau), 2.256 bar lấy thẳng nguồn + 6 bar 18–25/10/2016 nhân hệ số (nguồn phủ
từ 26/10/2016), khối lượng giữ nguyên (bậc 48× là thanh khoản thưa, không
phải chia tách). `triage --plan` ⇒ **sổ cách ly RỖNG**. Tổng chiến dịch 15/09:
**25/25**, 0 mã từ chối còn lại.

## 4. Ledger LLM 14/09: 66 call · 29 lỗi — ladder brief có 4 bậc chết cấu trúc

Cerebras 402 ×4 (việc #3 còn treo) · Groq qwen3.6-27b **413 Payload Too
Large** (prompt brief quá cỡ — bậc này không bao giờ trả lời được brief) ·
Mistral small 429 ×3 · OpenRouter free: 8 model cụt `finish_reason=length`, 2
×429, 1 timeout 90s, nemotron-nano `KeyError 'message'`. Bậc sống: Gemini
flash 11/14, flash-lite 18/22, Groq gpt-oss-20b 4/4, nemotron-super 2/3. Brief
754s là ladder đi qua các bậc chết. ⇒ việc #13, đối chiếu model_watch T7 trước
khi cắt.

**Vá 15/09 (#13).** Đọc code mới thấy nguồn của 8 model free lạ: `OpenRouterAgent
.generate` dựng ứng viên = model chính + TOÀN BỘ danh mục `:free` (cap 12) —
nemotron-super hụt MỘT lần là gõ cửa 11 model free nhỏ với `max_tokens` 2.400,
model nhỏ cụt hết. Sửa hai tầng, cố ý KHÔNG thêm slug mới (nếp: probe sống
trên máy thật trước): (1) `provider_blocked_today` trong ledger — 401/402/403
hôm nay + chưa call nào OK ⇒ mọi điểm gọi (brief base/Cerebras/OpenRouter,
sentiment, digest) bỏ nấc đó trong ngày; 429/5xx/timeout không chặn vì chặn
Gemini cả ngày sau một cơn 429 sáng là tự bỏ agent chính; kill-switch
`VNSTOCK_LLM_BREAKER=0`. (2) OpenRouter: `_MODEL_FALLBACKS = [nemotron-ultra]`
(đã sống ở digest bậc 1), cap 3, danh mục chỉ để bỏ slug biến mất, 429 dừng
(quota theo key). Groq qwen 413 đã có `_BRIEF_AGENT_DISABLES` từ 11/08.
Không đụng cấu hình agent của user (⚙️ bật gì là chủ đích). Phép đo: ledger
đêm 15/09 — kỳ vọng < 10 lỗi, không còn chuỗi OpenRouter cụt, brief ~300–500s.

**Tối 15/09 — brief close TRẮNG, và một nửa lỗi là của bản vá #13.** Telegram
19:13: "⚠️ LLM ladder DOWN — mọi agent đều lỗi" + brief với "AI Outlook: Chưa có
brief". Ledger 15/09: 34 call · 9 lỗi (từ 66/29 — cầu dao và tỉa danh mục ĂN:
Cerebras 1 call, không còn chuỗi 8 model free cụt). Nhưng đúng lúc brief chạy:
Gemini flash 429 rồi 503 ở hai lượt cách vài giây (base agent gọi một phát,
không đợi); Mistral 429 quota; Cerebras 402/cầu dao; OpenRouter nemotron-super
cụt ×2 và **không rơi xuống ultra** dù ultra sống (digest 2/2 OK). Vì sao: bản
14/09 hỏi `/api/v1/models` để bỏ slug "đã biến mất", mà danh mục OpenRouter cắt
trang ở 400 (model_watch đã ghi 08/08) và `_fetch_free_models` chỉ đọc trang
đầu ⇒ ultra bị coi là biến mất ⇒ ứng viên chỉ còn [super]. Bài học: **đừng
dùng một danh mục cắt trang làm bằng chứng vắng mặt**; slug chết thật chỉ tốn
một call 404. Vá: bỏ hẳn hỏi danh mục; `_OpenAICompatAgent.generate` thành
vòng ứng viên với đợi-gọi-lại 20s khi 429/5xx rồi sang `_MODEL_FALLBACKS`
(Gemini flash → flash-lite, slug đã sống ở [1][2][3-6]); cụt ⇒ dự phòng ngay;
401/402/403 dừng hẳn. Lưới `_ladder_slugs`/`_all_live_slugs` gom fallback qua
`AGENT_REGISTRY` nên class nào thêm dự phòng cũng tự vào lưới. 28 test.
Kỳ vọng brief 16/09 CÓ AI Outlook; ledger chỉ có dòng flash-lite/ultra khi
nấc chính hỏng. Đêm 15/09 ngoài ra: updater `partial: 214` (VCI ốm lần 4/6
phát), TỔNG 73,2′ — task đúng 18:00 vì máy đang bật.

**Đo ngay tối 15/09 20:41** — desktop merge `661b193` (`--fast` 2.591/86s) rồi
`telegram close --force`: brief CÓ AI Outlook, 4b soi 4/4 đạt. Ledger
19:12→20:41 đọc ra từng nhánh của vòng mới: +6 call · +1 OK · +5 lỗi = Gemini
flash 503 → đợi 20s → **OK** (nguồn brief, không cần flash-lite) · Cerebras 0
call (cầu dao) · Mistral 429 ×2 (gọi lại một lần rồi thôi) · OpenRouter super
cụt → **ultra ĐƯỢC gọi** (trước vá thì không) **nhưng cũng cụt**. Ultra 2/2 OK
cho digest ngắn, 14/09 super 2/3 OK cho brief ⇒ cụt là trần 2.800 token vừa
khít brief tiếng Việt với tokenizer nemotron, không phải slug chết. Dự phòng
OpenRouter vì thế chưa gánh nổi brief — ghi VIEC-DANG-LAM 4c (ghi usage khi cụt
để biết có reasoning ăn budget không, rồi nới trần kiểu `_THINK_HEADROOM`), ưu
tiên thấp vì flash + flash-lite đang gánh.

**Vá 4c (cùng tối, user "làm 4c đi").** (1) `vnstock_llm_ledger.record`: usage
được cộng cả khi `ok=False` (trước chỉ agent OK mới đưa usage — sổ mù đúng lúc
cần), tách `reasoning_tokens` từ `completion_tokens_details` (OpenAI/OpenRouter
chuẩn hoá; Gemini OpenAI-compat cũng cộng thinking vào completion), lưu
`last_fail_usage {prompt, completion, reasoning}` của lần lỗi cuối; `--show`
in `↳ suy nghĩ: N token (x% token ra)` và `↳ lần lỗi cuối tốn: vào · ra · trong
đó suy nghĩ`. Bẫy đã né: KHÔNG nhét số vào `last_error` vì cầu dao dò
`\b40[123]\b` — một lần cụt tốn đúng 402 token là chặn provider cả ngày (có
test). Bốn vòng agent (base, Cerebras, OpenRouter, Claude) đều truyền
`usage=body["usage"]` ở nhánh cụt. (2) `OpenRouterAgent._OUTPUT_HEADROOM =
5200` cộng vào mọi call — mirror `_THINK_HEADROOM` Gemini, là trần không phải
chi phí. Cố ý CHƯA đụng tham số `reasoning` của OpenRouter: chưa có bằng chứng
nemotron nghĩ (đó chính là thứ sổ mới sẽ đo), và tham số mới phải probe sống.
8 test, `--fast` 2.599.

**Vá 15/09 (#12).** `updater_status_update` (hàm thuần): lỗi > 0 ⇒ marker
`partial` + `last_partial_date` + `errors`/`fallback`, không đụng
`last_success_date` — `is_already_done_today` vẫn đòi `success` + hôm nay nên
lượt hụt không bao giờ được coi là xong; chỉ khác là marker không câm nữa.

# 🧭 U56. HAI KHO TÁCH NHAU — KHO LAPTOP LÀ ẢNH CHỤP TRƯỚC CHIẾN DỊCH 07/09 (09/09)

Bắt đầu từ một việc vặt: xoá `brief_watch.json` rồi `run.py doctor` trên
💻 laptop. Doctor in `Lệch cơ sở — 70 mã ĐANG KHÔNG cập nhật giá`, trong khi
U53 chốt 07/09 23:15 `[triage] ✅ sổ cách ly RỖNG`.

## Số đo (toàn lệnh chỉ đọc, trên laptop)

| | |
|---|---|
| `basis_drift_pending.json` | 19.271 byte, mtime **07/09 21:07:41**; `detected_at`: 08-21 ×23 · 08-24 ×6 · 08-25 ×2 · 08-28 ×8 · 09-04 ×2 · 09-07 ×29 |
| `record_drift` | luôn stamp `date.today()` (`vnstock_updater.py:622`) ⇒ ngày là ngày phát hiện thật, không lượt sync 08/09–09/09 nào sinh ra được |
| conflicted copy | `prices/` **0**; `_meta/` chỉ 15 bản cũ tháng 5–7 (không có bản của sổ) |
| junction laptop | OK → `C:\Users\Administrator\Dropbox\vnstock_data\data_warehouse` |
| `--from-drift-ledger --whole-series` (thử) | **69/70 lệch thật**, ACE sạch. Chẩn đoán trùng U53 **từng số**: VIM 35 · HU4 24 · SGR 9 · PJS 6 · ND2 5 · CHP 4 bar nhân hệ số; DRG `lõi 1.0016, thô 1.0251, 1 bar lẻ`; GH3 1.1356×/1.033 bar |
| doctor | VNINDEX bar cuối 07/09 · market_overview 07/09 · NN ròng 07/09 |

Dòng thứ 5 là dòng quyết định: một lần chạy thử hôm nay tái tạo **nguyên
văn** bảng chẩn đoán của chiến dịch 07/09. Không có cách nào kho ĐÃ chữa lại
đẻ ra đúng bộ số đó. ⇒ **Bản kho laptop đang đọc là ảnh chụp trước chiến
dịch**, đóng băng ở lần ghi cuối 07/09 21:07 (29 dòng 09-07 = phát tối 07/09
ghi sổ; giờ 21:07 khớp một phát chạy muộn ~38′ chứ không phải 18:00).

## Hai giả thuyết đầu đều sai — lần thứ tám trong chuỗi U42→U53

Tôi đi từ "sổ sống lại qua conflicted copy" (sai: không có bản nào) sang "junction
một máy hỏng" (sai: laptop OK) trước khi lệnh chạy thử nói thẳng: không phải
sổ cũ, mà là **cả kho cũ**. Cùng bài học U53: *thêm một dòng chẩn đoán, chạy
thật, rồi mới kết luận* — và lần này chỉ số đo bar-level (VIM 35/HU4 24) mới
đủ sức phân biệt "sổ lùi bản" với "kho lùi bản".

## Hệ quả vận hành

* **KHÔNG `--apply` trên laptop.** Chữa lần hai trên bản cũ = hai bản chữa
  độc lập; sync nối lại là 69 parquet + sổ conflicted cùng lúc.
* Bản desktop (chiến dịch + phát 08/09) là bản đúng — nếu nó còn. Laptop chưa
  ghi `prices/` nên hồi phục sạch; chỉ vài file `_meta` laptop ghi hôm nay có
  thể đẻ conflicted nhỏ.
* Brief close 08/09 gửi **22:58** — không phải giờ của pipeline 18:00 (+38′).
  Nhiều khả năng là lệnh tay; máy nào gửi thì user biết.
* ~~Chưa biết client Dropbox bên nào ngừng~~ **Đã rõ (user 10/09): Dropbox ở
  desktop bị TẮT SYNC bằng tay từ tối 07/09, quên bật lại.** Laptop "Up to
  date" đã khoanh đúng bên. Hạ tầng không đọc được từ code thì HỎI (CLAUDE.md
  hệ quả #4) — lần này hỏi một câu là ra, sau ba giả thuyết sai từ timestamp.
* Lưới KHÔNG bỏ lỡ, người đọc bỏ lỡ: doctor 09/09 trên laptop đã ⚠️
  market_overview 07/09 và ⚠️ NN ròng 07/09 (VNINDEX ✅ là đúng thiết kế —
  `check_warehouse` dung sai 2 PHIÊN vì EOD về trễ; tôi suýt ghi nhầm nó là
  lỗi "đếm ngày lịch"). Hai ⚠️ đó nghĩa là "phát 08/09 chưa tới kho này" — mà
  câu đó có hai cách xảy ra (pipeline không chạy / sync tắt), badge chưa nói
  ra. Việc #11: một badge riêng cho đúng câu đó.

---

# 🧵 U55. SOI BRIEF CLOSE 08/09 — 5 LỖI, ĐỀU CÓ FILE:LINE, ĐỀU ĐÃ VÁ (09/09)

User dán brief close phiên 08/09/2026 (bản đầu sau đợt vá 07/09) và hỏi
"đánh giá". Phần lớn đúng — những thứ từng hỏng (khối tin vỡ dòng, GDKHQ
cho ĐHĐCĐ, nhãn "1 tuần", ngữ cảnh BĐS) nay đều ổn; 12 con số kiểm lại đều
khớp. Còn lại 5 lỗi thật, mỗi cái một cơ chế khác nhau.

## (1) "— tác động: Nh" — dấu vân tay loại trừ chỗ đã vá

Hai dòng tin cụt: `— tác động: Nh` và `— tác động: Tỷ giá`. **Cắt giữa từ,
không có `…`.** `sanitize_impact` (U-21/08) cắt ở BIÊN TỪ và luôn thêm `…`
⇒ không phải nó. Truy ngược: `analyze_item` gọi `chat_complete(...,
max_tokens=120)`, mà `chat_complete` **không đọc `finish_reason`** — provider
cắt ở 120 token thì chuỗi trả về là câu cụt trông y hệt câu ngắn hợp lệ,
`sanitize_impact` cho qua vì `len ≤ 160`, rồi `refresh` ghi cache và giữ mãi
(chỉ `--reanalyze` mới chấm lại). 120 token vốn đủ cho "≤22 từ"; nghi là
full-text Jina làm model viết dài hơn, hoặc rơi nấc khi Gemini rate-limit
(doctor 07/09: 25 lượt chạm trần). Không đo được từ đây — nhưng cơ chế thì
rõ nên vá ở cơ chế:

* `vnstock_sentiment.chat_complete_ex` / `anthropic_complete_ex`: trả
  `{text, model, finish_reason, truncated}`. `finish_reason ∈ {length,
  max_tokens}` (mọi wire format, không phân biệt hoa thường) ⇒ gọi lại ĐÚNG
  nấc đó **một lần** với trần ×3 (`_TRUNCATE_RETRY_X`); lần hai lỗi HTTP thì
  giữ đáp án lần đầu chứ không rơi nấc (đổi model chỉ vì một lỗi mạng ngẫu
  nhiên là sai chỗ). Bản cũ `chat_complete`/`anthropic_complete` thành
  wrapper, chữ ký y nguyên — reflection/classifier/digest không phải sửa và
  tự nhiên được hưởng retry.
* `analyze_item`: `truncated` ⇒ trả `('','')` = CHƯA CHẤM, không cache. Test
  ở tầng `refresh` canh đúng hệ quả: tin đó vẫn nằm trong hàng đợi lượt sau.
* Cache hiện tại vẫn còn hai câu cụt — việc user `--refresh --reanalyze` một
  lần (kho chung).

## (2) 4 bp thành "ÂM — rủi ro chu kỳ", và nó ăn vào band phân bổ

`10Y 4.46 − điều hành 4.50 = −0.04`. `term_spread` dùng `if spread < 0` trần
trụi ⇒ nhãn to nhất + `dir=−1`. Hai vế lấy từ HAI nguồn (VBMA/HNX vs SBV),
4 bp là nhiễu. Không chỉ là chữ: `term` có trọng số 0.10 trong
`vnstock_allocation`, `dir=−1` + `slope_dir=0` ⇒ sub-score −0.5 ⇒ **−0.05
trên tổng −0.12**; bỏ nhiễu thì −0.07 (vẫn B2 data, tilt báo cáo vẫn đẩy
B3 — band không đổi hôm đó, nhưng biên B2/B3 là −0.15 và hysteresis 0.05,
tức nhiễu 4 bp từng đứng cách một cú đổi band đúng 0.03).

Vá: `_GAUGE_NOISE_BAND = 0.10` dùng chung `term_spread` + `intl_spread`
(cùng bệnh phía âm: có `_INTL_THIN_SPREAD` cho phía dương, phía âm rơi
thẳng). Âm trong biên ⇒ "mỏng — sát 0 (lệch dưới 0.10 điểm % là nhiễu giữa
hai nguồn, chưa tính ÂM)", `dir=0`. Biên là `<= −0.10` để **−0.10 vẫn là
ÂM** — data thật 03/07 trong test cũ giữ nguyên nghĩa, không nới. Phía
dương không đụng (test `+0.05` intl "mỏng" giữ nguyên).

## (3) "🎯 TLDR (2 dòng)" — template ghi chỉ thị NGAY TRONG header

`## 🎯 TLDR (2 dòng)` và `## 🔧 Đề xuất bổ sung (1 dòng, optional)` là
header của chính template (`vnstock_brief.py` cả 3 template), model chép y
nguyên, và không guard nào dọn header. Guard mới `enforce_no_header_scaffold`
(`_guards_text`): chỉ đụng DÒNG HEADER (`##`, emoji mục theo
`_is_section_start`, hoặc nhãn đậm mà ngoặc nằm TRONG phần đậm — đuôi còn
`**`), chỉ cắt ngoặc ở CUỐI dòng chứa "N dòng/câu" hoặc "optional". Nhãn đậm
mở đầu câu nội dung ("**Kết quả phiên:** … (2 dòng)") để yên — đó là nội
dung, guard chữ nghĩa không được đoán. Nối ngay sau
`enforce_no_instruction_leak`; hằng `_HEADER_SCAFFOLD_RE` phải re-export qua
cả `vnstock_brief_guards` lẫn `vnstock_brief` (lưới
`test_all_moved_names_are_reexported` réo ngay khi thiếu — đúng việc của nó).

## (4) "Sự kiện sắp tới" của brief CHIỀU tính cả hôm nay

DIG GDKHQ 2026-09-08 nằm trong "sắp tới" của brief phiên 08/09, kèm câu
"giá tự điều chỉnh trong ngày GDKHQ". `load_upcoming` lọc `_d >= today` —
đúng cho brief SÁNG (GDKHQ hôm nay còn ở phía trước), sai cho brief CHIỀU
(phiên đóng rồi, điều chỉnh xong rồi; liệt kê là bảo người đọc đề phòng một
cú giảm đã xảy ra). Hàm đã có tham số `today`, chỗ gọi không truyền. Vá:
`_upcoming_window_start(brief_type, data_date)` — chiều ⇒ `data_date + 1`,
sáng ⇒ None. Lấy `data_date` (ngày bar cuối) chứ không phải `date.today()`
để brief chiều chạy muộn/cuối tuần vẫn đúng. Có lưới nối dây kiểu
`test_brief_split` (soi source `collect_context`) — helper đúng mà chỗ gọi
quên truyền là y như cũ.

## (5) `pp` 2 số lẻ cạnh 3 số lẻ — và vì sao chốt 3 chứ không phải 2

"+0.81pp" (header khối ngành, `:+.2f`) cạnh "−0.260pp" (block chốt lead/lag
+ guard, `:+.3f`). Hôm qua tôi ghi "quy ước repo là `{:,.2f}`" và định kéo
tất cả về 2 — **sai hướng**: ngưỡng lead/lag là 0.05pp, nằm ở số lẻ thứ 2;
in 2 số lẻ thì dòng "Chưa có nhóm dẫn dắt (đóng góp lớn nhất chỉ +0.05pp)"
tự đá nhau với luật `< 0.05`. Chốt 3 số lẻ, đổi đúng một chỗ (`:+.2f` →
`:+.3f` ở header khối ngành); guard `enforce_lead_lag` và 6 test đang pin
chuỗi 3 số lẻ giữ nguyên.

## (1b) Ledger máy thật đọc ra GỐC của (1) — và một lỗ của chính bản vá

User chạy `--refresh --reanalyze` (8 tin) rồi `vnstock_llm_ledger.py --show`:
`gemini-3.5-flash 12 call · 8 OK · 4 lỗi (3 rate-limit)`, `flash-lite 1 OK`.
Ghép được đúng từng con số: 3 tin sạch · 1 tin cắt→gọi lại OK · 1 tin flash
lỗi→lite đỡ · **3 tin cắt→gọi lại dính 429→trống**. Hai kết luận:

* **~nửa câu trả lời đầu bị cắt ở 256 token.** Gemini 3.5 Flash là model SUY
  NGHĨ — tiêu trần vào phần nghĩ trước khi viết, y hệt bệnh gpt-oss đã biết ở
  ladder sentiment (Groq kê 256 + `reasoning_effort=low`). Đây mới là gốc của
  "— tác động: Nh"; `max_tokens=120` chỉ là bề mặt. Vá: `_ANALYZE_MAX_TOKENS
  = 768` kê từ đầu (token không dùng không tính tiền; cắt-rồi-gọi-lại trả tiền
  hai lần VÀ bắn hai call sát nhau ⇒ 429). Retry ×3 vẫn đứng sau làm lưới.
  Ý còn để dành, CHƯA làm vì phải probe trên máy thật trước: gửi
  `reasoning_effort=low` cho Gemini qua endpoint OpenAI-compat (Groq đã có).
* **Gọi lại lỗi mà trả câu cụt về là sai chỗ.** Bản đầu tôi lý luận "đổi
  model chỉ vì một lỗi HTTP ngẫu nhiên là sai" — thực tế lỗi đó là 429 do
  chính mình bắn sát, và câu cụt về tay `analyze_item` thì bị từ chối ⇒ tin
  trống trong khi flash-lite/Groq còn sống, chưa hề được gọi. Nay gọi lại lỗi
  ⇒ **đi tiếp nấc kế**; câu cụt chỉ là lưới CUỐI khi cạn thang (vẫn hơn tay
  trắng cho reflection; analyze_item vẫn từ chối vì `truncated=True`).

Hai câu cụt cũ của 08/09 **không cần dọn**: `--reanalyze` chỉ chấm lại 8 tin
mới nhất mà 09/09 đã có 12 tin, nhưng chúng cũng đã rơi khỏi cửa sổ brief
(6 tin mới nhất / 3 ngày). Muốn sạch cho sub-tab Vĩ mô thì `--max-analyze 30`.

## Không phải lỗi (đã kiểm, đừng mở lại)

* **MA20 ≈ MA50 ≈ MA200 (1,784/1,784/1,786)** — user đo trên máy thật: 664
  bar, 664 ngày khác nhau, 200 phiên dao động 1,591–1,928 quanh tâm ~1,785.
  Ba đường hội tụ là hình dạng của một năm đi ngang biên rộng, không phải
  data hỏng. Cái "bất khả" tôi đặt ra chỉ đúng cho chuỗi CÓ XU HƯỚNG.
  `_load_vnindex_df` sort theo `time`, không khử trùng ngày — nhưng đo ra
  không trùng nên không đụng.
* **"Op.CF âm của mã (BĐS)"** — chuỗi cứng ở
  `vnstock_brief_guards_sections.py`, không phải placeholder hỏng; chỉ là
  chữ hơi trúc trắc.
* **PNJ 🟢 trong tin vs GIẢM TỶ TRỌNG trong watchlist**, **VIC MUA vs "phân
  phối ngầm Họ VIN"** — mạch văn LLM, không sai số. Chưa có guard nào nên
  đụng vì cần đọc ý; nếu tái diễn thì ĐẾM qua `vnstock_brief_watch` trước.
* **NSO** — CPI/IIP/cán cân đều `as_of 2026-08-31` ⇒ việc #4 (phát 4G) tự
  xong.

Test: 17 test mới; `run.py test --fast` trên sandbox phiên này: **2.561
passed / 57,5s, 0 fail**. Số máy thật (có kho) sẽ chậm hơn ~3× như thường lệ.

---

# 🧯 U54. CÔNG TẮC AUTO-HEAL LÀM NGƯỢC LỜI HỨA + SỔ Op.CF ĐẾM NHẦM NGÀNH (07/09)

Hai badge `⚠️ ĐỦ mẫu, đáng quyết` được user giao xử. Soi cả hai thì **cả hai
đều không phải chuyện mình tưởng.**

## (a) `VNSTOCK_AUTOHEAL_BUDGET_S=0` KHÔNG tắt — nó BỎ TRẦN GIỜ

Badge in nguyên văn: *"hạ trần: VNSTOCK_AUTOHEAL_BUDGET_S=120 (hoặc 0 để tắt
hẳn)"*. Code:

    _budget = float(os.environ.get("VNSTOCK_AUTOHEAL_BUDGET_S")
                    or AUTO_HEAL_BUDGET_S)
    ... time_budget_s=_budget if _budget > 0 else None

Chuỗi `"0"` là **truthy** nên `or` không rơi về mặc định ⇒ `_budget = 0.0` ⇒
`time_budget_s=None` ⇒ và trong `auto_heal`, `None` nghĩa là **KHÔNG CHẶN
GIỜ**. Làm đúng theo badge sẽ cho auto-heal chạy **không giới hạn**. Mỗi mục
hàng đợi là một lần gọi mạng, task Daily có trần cứng 120 phút — **đúng hình
dạng đã giết lượt chạy 04/09** (sync một mình 179,4 phút).

Nay `0`/`off`/`no`/`false` ⇒ TẮT thật; số dương ⇒ trần; rỗng hoặc rác ⇒ mặc
định. **Không còn đường nào xin chế độ không-trần qua biến môi trường** —
không ai cần nó, và nó là cái bẫy. Có test quét: mọi đường vào phải ra một
trần DƯƠNG hoặc ra TẮT.

### Và đề xuất "tắt đi" của tôi dựa trên tiền đề SAI

Tôi nói auto-heal *"đang tiêu ngân sách vô ích"* — chữ trong badge. Nhưng
`⏱ CHẶNG` tối 07/09 ghi **`auto-heal 0s`**. Nó không tốn gì cả. Badge chỉ đo
HIỆU SUẤT (0 lành) chứ không đo CHI PHÍ, và tôi chép lời nó thành một lý do
kinh tế mà số đo không đỡ.

⇒ Badge nay bảo **đối chiếu chi phí trước khi tắt**: xem `auto-heal <n>s`
trong `⏱ CHẶNG`. Tốn giờ thì hạ trần / tắt; tốn ~0s thì cứ để. Và nói rõ cái
mất khi tắt: hàng đợi cách ly không được thử lại **lẫn không được dọn** —
`archive_exhausted` cũng nằm trong `auto_heal`, nên tắt là hàng đợi chỉ phình.
Đường tay `python run.py heal` vẫn còn.

**Vì sao yield = 0 mà không phải lỗi:** `vnstock_ohlc_repair` (19/08) đã chữa
lớp bar tự mâu thuẫn **ngay ở đường ghi**, tức rút mất lớp chiếm phần lớn hàng
đợi. Phần còn lại là thứ refetch không bao giờ chữa được — cùng nguồn trả về
cùng bar. Yield 0 là **hệ quả của một bản vá tốt**, không phải dấu hiệu hỏng.

## (b) Op.CF/vốn hoá: số THẬT, và sổ đang đếm nhầm ngành

83 mã qua 6 phiên, đậm nhất **NAB 6.118×**. Đầu bảng: **BID · BSI · DSE · HDB
· NAB** — **năm trên sáu là ngân hàng / chứng khoán**.

Với định chế tài chính, "lưu chuyển tiền HĐKD" theo VAS gồm cả biến động
**tiền gửi, cho vay, liên ngân hàng** — dòng BẢNG CÂN ĐỐI chứ không phải dòng
tiền hoạt động theo nghĩa doanh nghiệp thường. Op.CF vài trăm nghìn tỷ ở đó là
**số thật**. Không có lệch đơn vị nào.

Và repo **đã biết điều này từ trước**: `vnstock_brief_canon._FINANCIAL_TICKERS`
ghi rõ *"a bank never gets mis-flagged as a risk purely because of its scale —
e.g. MBB Op.CF -64,972 tỷ"*, và xếp hạng rủi ro của brief ĐÃ loại nhóm đó.

⇒ Sổ đang đếm những mã **không bao giờ tới được mục Rủi ro**. Đếm bao nhiêu
phiên cũng không ra quyết định nào, mà badge thì cứ vàng — đúng kiểu làm người
dùng học cách bỏ qua badge (U42).

Bản vá không phải một ngưỡng số. `scan_ocf_scale` nay dùng **CHUNG một danh
sách** với xếp hạng: `_FINANCIAL_TICKERS` **hợp** `ctx["financial_tickers"]`
(phân loại theo NGÀNH — bắt được mã ngoài danh sách tĩnh, vd **DSE**). Hai bên
tự giữ danh sách riêng là chắc chắn lệch nhau.

**KBC (BĐS) vẫn được giữ** — Op.CF âm nặng do tích luỹ quỹ đất là tín hiệu
THẬT mà mục Rủi ro sinh ra để nói, và brief đã có guard gắn ngữ cảnh cho nó.
Vơ đũa cả nắm ở đây là giết đúng tín hiệu cần giữ.

## Bài học chung của cả hai

Cả hai badge đều **đúng khi kêu** nhưng **sai ở lời khuyên kèm theo** — một
cái khuyên một lệnh làm ngược, một cái khuyên đếm tiếp một thứ không bao giờ
kết luận được. Badge nói *"có chuyện"* thì đáng tin; badge nói *"làm thế này"*
thì vẫn phải đọc code.

13 test mới. Suite: **3.141 pass**.

# 🏁 U53. ĐÓNG CHIẾN DỊCH LỆCH CƠ SỞ: 73 → 0 (07/09)

    [triage] ✅ sổ cách ly RỖNG — không mã nào đang bị chặn cập nhật.

DRG là mã cuối: `spread lõi 1.0016, thô 1.0251, 1 bar lẻ lệch trung vị` —
đúng chữ ký U52 dự đoán. 1.627/1.627 bar lấy thẳng từ nguồn, hệ số **không
chạm bar nào**.

## Điểm đáng nhớ nhất: hệ số gần như không bao giờ được dùng

Cộng cả chiến dịch, số bar phải NHÂN hệ số đếm trên đầu ngón tay (VIM 35 ·
HU4 24 · SGR 9 · PJS 6 · ND2 5 · CHP 4 · vài mã 1 bar), còn lại **toàn bộ lấy
thẳng từ nguồn**. Nghĩa là thứ đáng sợ nhất của `--whole-series` — nhân cả
lịch sử bằng một con số đo được — thực tế gần như không xảy ra: nguồn phủ hết
dải kho, nên công cụ chỉ chép lại. Hệ số chủ yếu đóng vai **bằng chứng để
quyết**, không phải phép tính để áp.

Điều đó cũng giải thích vì sao ba lần "nới cửa" đều an toàn hơn vẻ ngoài của
chúng — và vì sao vẫn đúng khi không nới: cửa sai thì mã bị giam, mà giam một
mã đã sạch cũng là một kiểu hỏng (U47).

## Bảy vòng, và không vòng nào là vòng cuối

| # | tưởng là | hoá ra |
|---|---|---|
| U42 | công cụ chữa hỏng | hai bên đo hai ĐẠI LƯỢNG khác nhau (mức ⇄ đạo hàm) |
| U43 | cần nới cửa `_probe` | cần một cửa KHÁC, chặt hơn |
| U44 | kho sự kiện thiếu | kho sự kiện KHÔNG PHẢI cửa của bước chữa |
| U45 | 13 mã lệch đều | 13 mã có vách thật, bộ dò thiếu sàn bar |
| U47 | 3 mã chưa chữa | 1 mã ĐÃ SẠCH, chỉ sổ chưa xoá |
| U50 | GH3 là mã thưa | kho GH3 đóng băng 348 ngày, cửa sổ đo hỏi sai |
| U52 | DRG có vách | DRG có một hạt sạn, thước đo quá nhạy |

**Bảy lần liền, giả thuyết đầu tiên đều sai, và số đo đều lật.** Cái cứu từng
vòng luôn là cùng một việc: *thêm một dòng chẩn đoán, chạy thật, rồi mới sửa.*
Ba vòng cuối tôi đứng trước đúng một cám dỗ — nới ngưỡng vì nó chặn đúng một
mã — và cả ba lần thứ hỏng nằm chỗ khác.

## Còn treo (không gấp)

* **GH3 có đuổi kịp không.** Kho đóng băng 2025-09-24, **11 tháng trước khi
  cửa gác ra đời** ⇒ gác không phải nguyên nhân. Nguồn có 1.267 bar / kho
  1.033 ⇒ ~234 bar chờ nối. Phát tối mai trả lời.
* **`_corp_event_kind` vẫn chỉ đọc cache theo mã**, nên mã mới bị chặn vẫn ghi
  `event: None` vào sổ. Hoãn vì `load_events` còn phục vụ đường điều chỉnh giá.
* **`LEVEL_BREAK_MIN_AFTER` = 2 chưa bao giờ cần hạ.** Ca duy nhất tưởng cần
  (DRG) hoá ra không phải vách. Giữ nguyên, đừng hạ theo linh cảm.

Tổng: **73 mã**, ~10 giờ, 11 commit, **3.127 test**. Badge doctor `basis_drift`
hết đỏ lần đầu kể từ 19/08.

# 🪨 U52. MỘT HẠT SẠN CHE MẤT 195 BAR — VÀ VÌ SAO KHÔNG NỚI TRẦN SPREAD (07/09)

`--explain` in đuôi chuỗi DRG (U51) và câu trả lời hiện ngay:

    2026-08-18  kho 8.20  nguồn 8.04  = 1.0199×  ✗
    2026-08-19  kho 8.90  nguồn 8.72  = 1.0206×  ✗
    2026-08-21  kho 8.70  nguồn 8.53  = 1.0199×  ✗
    2026-08-27  kho 8.20  nguồn 8.23  = 0.9964×  ✓   ← MỘT MÌNH

**Không phải vách.** 11 bar sát nhau trong dải 1.0199-1.0209 (rộng 0,1%), rồi
đúng MỘT bar lệch hẳn sang hướng khác. Và bar ấy không phải "đã sang cơ sở
mới": 8.20 với 8.23 lệch **3 bước giá** — hai con số KHÁC NHAU cho cùng một
ngày, không phải quan hệ cơ sở. Kho dựng `close` từ rollup 1 phút, nguồn lấy
close chính thức; mã thưa thì hai cái đó lệch nhau là chuyện thường.

Nó lọt qua bộ dò MỨC vì 0,36% **nằm trong** ngưỡng 1,2% ⇒ bị chấm "✓ đã khớp"
⇒ `level_break_report` tưởng đó là phía cơ sở mới, chỉ thiếu đúng một bar so
với sàn 2. Suốt hai vòng trước tôi đã định hạ sàn ấy. **Hạ là sai** — không
có vách nào ở đó cả.

## `max/min` là thước nhạy nhất có thể với đúng ca này

Một hạt sạn làm spread nở từ **1.0014** lên **1.0251** và che mất toàn bộ 195
bar còn lại. Nhưng **nới trần spread là sai cách chữa**: nó nới cho cả ca có
vách thật, tức bỏ đúng thứ cửa ấy sinh ra để chặn.

Cách đúng là đổi **thước**, không đổi **trần**, và hỏi thẳng câu cần hỏi:

| luật | công thức | trần |
|---|---|---|
| **bar lẻ** | số bar lệch trung vị quá `tol`, chia cho tổng | `UNIFORM_MAX_OUTLIER_FRAC` = **5%** |
| **spread LÕI** | max/min sau khi cắt `UNIFORM_TRIM_FRAC` = 2% mỗi đuôi (chỉ khi ≥50 bar) | 1.01, y như cũ |

DRG: 1/196 bar lẻ = 0,5% ✓, spread lõi 1.0014 ✓ ⇒ **chữa được bằng
`--whole-series`**. Con số thô vẫn in ra — cắt đuôi để QUYẾT, không phải để
giấu; người đọc log vẫn phải thấy có một bar lệch.

## Hai luật che HAI hình dạng — bỏ luật nào cũng lọt một ca

Phát hiện lúc viết lưới, và nó là lý do phải giữ cả hai:

* **Chia 50/50 sát nhau** (98 bar ở 1.0204, 98 bar ở 1.0): trung vị rơi đúng
  vào GIỮA hai cụm (1.0102), nên **cả hai cụm đều nằm trong ±tol của trung
  vị** ⇒ luật bar-lẻ đếm được **0**. Chỉ spread lõi chặn được.
* **Dốc thoải** (ramp): spread lõi nở từ từ, nhưng luật bar-lẻ bắt gọn.

Có test chốt cứng cả hai chiều, kèm `UNIFORM_TRIM_FRAC < UNIFORM_MAX_OUTLIER_FRAC`
— cắt đuôi rộng hơn trần bar-lẻ thì cắt đuôi sẽ âm thầm cho qua đúng những ca
trần kia định chặn.

## Bài học

Ba vòng liền tôi đứng trước cùng một cám dỗ — **nới một ngưỡng vì nó chặn
đúng một mã** — và cả ba lần thứ hỏng đều nằm chỗ khác: cửa sổ đo sai (U50),
công cụ chẩn đoán mù (U49), thước đo sai (mục này). Ngưỡng chặn một ca đúng
thường là ngưỡng ĐÚNG đang tố cáo một phép đo sai.

7 test mới. Suite: **3.127 pass**.

# 🔬 U51. SỐ TỔNG HỢP KHÔNG TÁCH ĐƯỢC HAI CÁCH ĐỌC — PHẢI NHÌN TỪNG BAR (07/09)

GH3 chữa xong bằng cửa sổ NỚI của U50: **1.033 bar trải 1512 ngày, spread
1.0022, phủ 100% lịch sử kho**, 1.033/1.033 bar lấy thẳng từ nguồn, hệ số
không chạm bar nào. **Sổ 73 → 1.**

Hai xác nhận phụ, cả hai đều là bản vá trong ngày tự chứng minh trên máy thật:

* triage nay in `đứng lâu nhất 11 ngày · tổng ~11 bar` thay cho `0 · ~0` (U50);
* `nguồn phủ từ 2021-08-04 (1,267 bar)` trong khi kho chỉ có **1.033** ⇒ ~234
  bar của năm vừa rồi **vẫn nằm sẵn ở nguồn**, chỉ chờ được nối. Kho GH3 đóng
  băng từ 2025-09-24, tức **11 tháng TRƯỚC khi cửa gác V1 ra đời** (19/08/2026)
  — gác không phải nguyên nhân. Phát tối mai trả lời: đuổi kịp thì xong, vẫn
  dừng thì nguyên nhân nằm chỗ khác.

## DRG: cùng một bộ số, hai cách đọc đối nghịch

    CHỒNG : 196 bar trải 353 ngày · tỉ lệ 1.0204× · spread 1.0251
    vách theo MỨC : — chỉ 1 bar đã sang cơ sở mới (cần ≥2)

Ráp lại: 195 bar ở ~1.0204 và **đúng một** bar ở 0.9964 (trong ngưỡng ⇒ coi là
đã khớp); `1.0213 / 0.9964 = 1.0250`, khớp đúng spread in ra. Hai cách đọc:

| | đọc là gì | chữa thế nào |
|---|---|---|
| **A** | **vách thật** — nguồn vừa back-adjust, kho mới nối được một bar ở cơ sở mới | chữa mọi bar TRƯỚC bar đó |
| **B** | **lệch đồng đều 1.0204× kèm một bar HỎNG** | chữa TRỌN chuỗi |

**Không con số tổng hợp nào tách được hai cách đọc này** — trung vị, spread,
số bar mỗi phía đều cho ra y hệt nhau ở cả hai. Đó là giới hạn của thống kê
tóm tắt, không phải của ngưỡng nào cả. Nới ngưỡng ở đây là **đoán** một trong
hai cách đọc rồi ghi đè lịch sử theo cái đoán ấy.

Nhìn thẳng vào đuôi chuỗi thì tách được ngay: bar 0.9964 nằm ở ngày nào, một
mình hay có bạn, giá kho và giá nguồn ra sao. Nên `--explain` nay in **ĐUÔI** —
12 bar chồng lấn cuối, kèm giá hai phía, tỉ lệ từng bar và dấu ✓/✗.

**Vẫn CHƯA hạ `LEVEL_BREAK_MIN_AFTER`.** Đây là lần thứ ba trong ngày đứng
trước một ngưỡng chặn đúng một ca, và hai lần trước đều: đòi số đo → số đo lật
giả thuyết → sửa đúng thứ hỏng (không phải ngưỡng). Không có lý do gì lần này
làm khác.

## Một lỗi tốc độ lộ ra nhờ bộ test

`_tail_ratios` fetch nguồn **TRƯỚC** khi xem kho có gì — bộ test đột nhiên
chạy **34 giây** thay vì 0,7. Trên máy thật đó là một lượt gọi mạng vô ích cho
mỗi mã không có trong kho. Đảo thứ tự: 34s → **0,68s**. Có test canh.

Bài học lặp lại lần thứ hai trong ngày (lần đầu: `--explain` ở U49): *chỗ mình
định thêm một dòng chẩn đoán thường là chỗ có sẵn một lỗi chưa ai nhìn.*

6 test mới. Suite: **3.120 pass**.

# 🧊 U50. GH3 KHÔNG PHẢI MÃ THƯA — KHO NÓ ĐÓNG BĂNG GẦN MỘT NĂM (07/09)

`--explain` (U49) trả lời ngay lượt đầu, và **lật đúng giả thuyết của tôi**:

    [soi] KHO   : 1,033 bar · 2021-08-04 → 2025-09-24 · trong 365 ngày: 13 bar
    [soi] CHỒNG : 13 bar trải 16 ngày · tỉ lệ 1.1356× · spread 1.0011
    [soi]         vùng chồng lấn phủ ~1% bề dài lịch sử kho (1512 ngày)

Tôi đoán GH3 là **mã mới niêm yết**, 16 ngày ấy phủ trọn đời nó. **Sai.** Nó
niêm yết từ 2021, có 1.033 bar, và kho **dừng ở 2025-09-24** — đóng băng
**348 ngày**. 13 bar "trong 365 ngày" chỉ là cái đuôi của nó.

Ghi lại vì đây là lần thứ hai trong ngày một giả thuyết nghe rất hợp lý bị số
đo bác bỏ. Cả hai lần đều nhờ ĐÒI SỐ ĐO TRƯỚC KHI VÁ.

## Hai lỗi thật, cả hai đều báo THIẾU

**1. Cửa sổ 365 ngày đo sai với mã kho đã đứng lâu.** "Mỏng" ở đây là thuộc
tính của **cửa sổ**, không phải của mã: nới tới đầu kho thì có ~1.000 bar
chồng lấn. Nay `_uniform_probe` tự nới tới bar ĐẦU của kho khi cửa sổ mặc định
cho ra dưới `UNIFORM_MIN_BARS` bar (trần `WIDEN_MAX_DAYS` = 4500). Bằng chứng
khi ấy **mạnh hơn hẳn** — và trần spread giữ nguyên, nên nhiều lần đổi cơ sở
rải rác trong 4 năm sẽ làm spread nở và mã bị từ chối, đúng như phải thế. Nới
mà không thêm bar nào ⇒ giữ kết quả cũ, không bịa.

**2. Bảng triage báo thiệt hại bằng KHÔNG.**

    [triage] đứng lâu nhất 0 ngày · tổng ~0 bar giá đang thiếu

trong khi GH3 đứng 348 ngày. `record_drift` ghi đè `detected_at` **mỗi đêm**
khi gác còn chặn, nên trường đó luôn là "hôm nay". Nó trả lời *lần phát hiện
gần nhất là bao giờ*, KHÔNG phải *kho đứng bao lâu rồi*. Nay `summarize` nhận
`stale_days` bơm từ ngoài, và `main` bơm `stale_from_warehouse` — đo từ **bar
cuối trong kho**. `detected_at` tụt xuống làm lưới cuối.

Sai theo hướng **báo thiệt hại bằng 0** là hướng tệ nhất: người đọc kết luận
"chả mất gì" rồi xếp việc lại. Cả 70 mã tối nay đều hiện "0d" — con số ấy chưa
bao giờ đúng, chỉ là không ai đối chiếu được cho tới khi có `--explain`.

## Lưới "chỉ đọc" của triage đỏ lên — và nó đo sai đối tượng

`test_the_script_never_imports_a_writer` quét chuỗi trên TOÀN file, nên nó bắt
cả lần `record_drift` xuất hiện trong **docstring giải thích vì sao KHÔNG dùng
nó**. Cấm nhắc tên một hàm nguy hiểm là cấm luôn việc ghi lại lý do tránh nó.
Nay quét trên mã đã bỏ chú thích + chuỗi ký tự (`tokenize`), kèm một test
chứng minh lưới **vẫn cắn** lời gọi thật — nới lưới mà không chứng minh nó còn
cắn thì nó thành lưới trang trí.

## `sys.path` thiếu một đường ⇒ lại là con số 0

`stale_from_warehouse` đọc kho qua `check_unit_continuity`, module nằm **cạnh**
file triage; mà triage chỉ thêm GỐC REPO vào `sys.path`. `ImportError` bị nuốt
trong `try` ⇒ hàm lặng lẽ trả None ⇒ **lại báo 0**. Bắt được vì test dựng kho
thật rồi đối chiếu ngày, chứ không mock `load_bars`.

## DRG — chẩn đoán xong, CHƯA vá

    [soi] CHỒNG : 196 bar trải 353 ngày · tỉ lệ 1.0204× · spread 1.0251
    [soi]   vách theo MỨC : — chỉ 1 bar đã sang cơ sở mới (cần ≥2)

Ráp số: 195 bar ở ~1.0204 và **1 bar** ở 0.9964 (trong ngưỡng ⇒ coi là đã
khớp). `1.0213 / 0.9964 = 1.0250` — khớp đúng spread in ra. Tức DRG **chia
sạch**, chỉ thiếu đúng một bar so với `LEVEL_BREAK_MIN_AFTER` = 2.

Và phía đó **không bao giờ mọc thêm** — gác đang chặn. Lại đúng hình dạng vòng
tự khoá của U45, chỉ nhỏ hơn một nấc.

**Chưa hạ sàn xuống 1.** Với `n_after = 1`, `_probe` tính
`shift = r_before / r_after` nên **hệ số do đúng MỘT bar quyết định** —
0.9964 thay vì 1.0000 làm lệch 0,4%. Hạ sàn mà không sửa công thức hệ số là
đổi một lỗi lấy một lỗi. Cách đúng có lẽ là lấy thẳng `r_before` (nguồn là
mốc, không cần chia cho phía sau), nhưng đó là đụng vào công thức đã chữa 67
mã tối nay — để lượt sau, đo trước.

Suite: **3.114 pass**.

# 🔦 U49. BẢNG TRIAGE DẪN NGƯỜI TỚI ĐÚNG CÔNG CỤ MÙ (07/09)

GH3 với cửa thưa: **13 bar trải 16 ngày** — cần 180. Từ chối ĐÚNG, cửa hoạt
động như thiết kế. Nhưng bước tiếp theo mới là chỗ hỏng.

Bảng triage bảo soi tay bằng `probe_price_basis --ticker <MÃ>`. Chạy thật:

    [basis] ⬜ GH3: không tìm thấy vách nghi vấn trong 365 ngày — không có gì để phân định
    [basis] ⬜ DRG: không tìm thấy vách nghi vấn trong 365 ngày — không có gì để phân định

**Đó là công cụ chỉ chạy bộ dò BẬC** — đúng lớp bộ dò mà U42 và U45 đã chứng
minh là mù với mã bị gác chặn. Nó nói "không có gì để phân định" trong khi có
rất nhiều: tỉ lệ 1.1356×, spread 1.0011, 13 bar trải 16 ngày, độ dày kho, và
mỗi bộ dò còn lại nói một câu khác nhau.

*Dẫn người tới một công cụ mù rồi bảo "soi tay đi" là bỏ mặc, không phải giao
việc.* Và nó đội lốt một lời khuyên đầy đủ — tệ hơn im lặng.

## `--explain`, chỉ đọc

`rebase_ticker_history --ticker <MÃ> --explain` in:

* **KHO** — tổng bar, ngày đầu/cuối, bar trong 365 ngày;
* **CHỒNG** — số bar chồng lấn, tầm phủ, tỉ lệ, spread, **và phần trăm bề dài
  lịch sử kho mà vùng chồng lấn phủ được**;
* **BỘ DÒ** — bốn dòng, mỗi bộ một dòng, kể cả bộ im (*"không nói gì" và
  "không được hỏi" nhìn giống hệt nhau trong một bản in thiếu dòng*);
* **⇒** — lệnh chữa cụ thể, hoặc "CẦN MẮT NGƯỜI" kèm lý do.

Không thay `probe_price_basis`: nó là tầng ĐO, đây là tầng đọc số đo bằng ống
kính MỨC. Giữ một chiều phụ thuộc rebase → probe. Triage nay trỏ sang đây.

## Phần trăm phủ — câu hỏi tiếp theo cho GH3

16 ngày của một mã **mới niêm yết** phủ TRỌN đời nó; 16 ngày của một mã 20 năm
tuổi thì không phủ gì. **Hai con số bằng nhau, hai kết luận ngược nhau.** Nếu
vùng chồng lấn phủ ~100% lịch sử kho thì không có phần nào cũ hơn để nằm ở cơ
sở khác — bằng chứng khi ấy mạnh hơn cả 240 bar của một mã lâu năm, và cửa
đúng phải là *"phủ trọn lịch sử kho"* chứ không phải *"trải ≥180 ngày"*.

**Chưa sửa cửa** — đang chờ số đo, vì đây sẽ là lần nới thứ ba và hai lần
trước đều có số đo trước khi nới.

## Bốn test đỏ lên, và chúng đỏ vì viết sai chỗ cần canh

Bất biến *"mã chưa rõ không được vào lệnh chữa hàng loạt"* viết bằng
`if "rebase" in c`. Thêm một lệnh **chỉ đọc** cũng gọi `rebase_ticker_history`
là chúng bắt nhầm ngay — phép dò ấy đo **TÊN FILE** chứ không đo **VIỆC**. Nay
có `_write_cmds()`: lệnh ghi = gọi rebase **và không có** `--explain`. Kèm một
test ngược chiều: mã đỏ **phải** có mặt trong lệnh soi (*"không bỏ mặc mã đỏ"*)
— bất biến cũ chỉ cấm, không đòi, nên "im lặng hoàn toàn" cũng lọt.

Và một test riêng cho `--explain --apply`: gõ nhầm là chuyện sẽ xảy ra, nó
phải vẫn chỉ đọc.

10 test mới. Suite: **3.107 pass**.

# 🕸️ U48. CỬA THƯA: ĐẾM BAR LÀ PROXY, TẦM PHỦ MỚI LÀ CÂU HỎI THẬT (07/09)

Sổ cách ly xuống **2 mã** (DRG · GH3) sau khi ACE tự xoá đúng như U47 dự
liệu. Và dòng từ chối của GH3 — vừa được cho in kèm số đo ở U47 — nói ra
ngay thứ mà bản trước giấu mất:

    ✗ GH3: TỪ CHỐI --whole-series — chỉ 13 bar chồng nhau (cần ≥20)
           — quá ít để nói 'đều' (đo được 1.1356×, spread 1.0011)

**spread 1.0011.** Chặt ngang mọi mã đã chữa sạch trong ngày: AGG 1.0009 ·
BRC 1.0009 · FT1 1.0003 · IPA 1.0007 · HU4 1.0014. Bảo "quá ít để nói đều" là
**bỏ qua chính con số đang nói rất rõ**.

Bài học nhỏ nhưng đáng ghi: bản vá U47 chỉ thêm hai số vào một câu thông báo,
và chính hai số đó lộ ra một cửa đặt sai. *Thông báo từ chối phải chở theo số
đo, không chỉ chở kết luận.*

## Sàn 20 bar hỏi sai câu — với mã thưa

Câu thật sự cần hỏi không phải *"có bao nhiêu bar"* mà *"chứng cứ có phủ đủ
rộng để một lần đổi cơ sở trong cửa sổ này không lọt qua không?"* Với mã dày,
đếm bar là proxy tốt. Với mã gần như không giao dịch thì không.

Thứ đo trực tiếp hơn là **TẦM PHỦ THỜI GIAN**. Bar rải trên nửa năm ⇒ một lần
đổi cơ sở trong nửa năm ấy **chắc chắn nằm GIỮA hai bar nào đó** ⇒ tỉ lệ phải
gãy ⇒ spread phải nở. Spread **không** nở nghĩa là không có lần đổi nào. Vài
bar chụm trong hai tuần thì không nói được như vậy, đếm ra bao nhiêu cũng thế.

## Cửa thưa

    UNIFORM_SPARSE_MIN_BARS = 8
    UNIFORM_SPARSE_MIN_SPAN_DAYS = 180

Qua được khi `n ≥ 20`, **HOẶC** `n ≥ 8` **VÀ** trải `≥ 180` ngày. Đòi CẢ HAI ở
nhánh thưa: hai bar cách nhau một năm cũng "phủ rộng", mà hai điểm thì tỉ lệ
nào cũng "đều".

⚠️ **Cửa thưa chỉ nới điều kiện CHỨNG CỨ, KHÔNG nới điều kiện KẾT LUẬN.**
Trần spread 1.01 giữ nguyên cho mọi mã — lệch lởm chởm vẫn là lởm chởm dù bar
thưa hay dày. Có test canh riêng việc này, vì đây đúng là chỗ dễ nới lỏng thêm
một nấc "cho tiện".

Dòng ✅ nay nói rõ khi mã đi qua cửa thưa (`· qua CỬA THƯA: ít bar nhưng phủ
đủ rộng…`) — người đọc log cần biết bằng chứng ở đây mỏng hơn thường lệ.

## GH3 sẽ qua hay không: chưa biết, và đó là câu trả lời đúng

13 bar ấy **rải khắp năm** hay **chụm hai tuần**, log chưa nói. Cửa mới in
`span_days` nên lượt chạy tới sẽ trả lời. Rải rộng ⇒ chữa được; chụm lại ⇒ vẫn
từ chối, và từ chối đúng. Không hạ sàn theo một mẫu — hạ theo **đúng thứ mà
sàn ấy vốn định đo**.

## DRG thì khác hẳn — đừng gộp

Tỉ lệ 0.9964× → 1.0213×, spread 1.0251. Cận dưới **dưới 1**, tức có bar kho
THẤP hơn nguồn — không phải hình dạng "nguồn back-adjust, kho giữ cơ sở cũ".
`level_break_report` cũng từ chối (lẫn quá 10% bar sai phía ⇒ không chia sạch
thành hai phía). Đây là mã cần mắt người, không phải cần nới cửa.

8 test mới. Suite: **3.097 pass**.

# 🔁 U47. VÒNG TỰ KHOÁ THỨ BA: MÃ ĐÃ CHỮA NẰM LẠI TRONG SỔ CÁCH LY (07/09)

Lượt `--from-drift-ledger --whole-series --apply` sau bản vá U46: **67/70 mã
xong**, sổ **73 → 3** (còn ACE · DRG · GH3). Nhưng trong đó có một chuyện.

**ACE chữa xong lúc 21:07**, in *"✅ chuỗi đã liền — không còn vách trong 365
ngày · bộ dò MỨC cũng sạch"*. Lượt 21:20 đo lại:

    [rebase] ✗ ACE: TỪ CHỐI --whole-series — tỉ lệ 1.0000× nằm trong ngưỡng
             0.012 — kho KHÔNG lệch, không có gì để chữa

Tức **chữa đã ăn** — kho ACE sạch. Vậy mà ACE **vẫn nằm trong sổ cách ly**, và
lượt đó **từ chối** nó. Đếm lại khớp: lượt 1 xoá được AAM · AGG · BCF khỏi sổ
(73 → 70) nhưng **không xoá được ACE**.

## Hai lỗi chồng nhau

**1. `clear_drift` trả `None` và nuốt sạch ngoại lệ.**

    except Exception:
        pass

Chỗ gọi không có cách nào biết là hỏng — mà chỗ gọi cũng bọc thêm một
`try/except: pass` nữa, nên lỗi bị nuốt HAI LẦN. Dropbox đang giữ file đúng
phút ấy: BRC chết vì `WinError 5` ngay sau đó (U46). Nay hàm trả **bool**, có
retry riêng (`CLEAR_RETRIES` = 5), và vẫn KHÔNG ném — nó bị gọi từ chỗ mà một
lỗi ghi sổ không được phép làm hỏng cả lượt chạy.

**2. Ca "kho đã sạch mà sổ còn giữ mã" rơi vào nhánh TỪ CHỐI.** Và đây mới là
vòng khoá: `clear_drift` **chỉ có đúng MỘT chỗ gọi trong toàn repo** — chính
`rebase_ticker_history`. Cửa gác `record_drift` thì ghi vào sổ mỗi đêm, nhưng
**không có đường nào tự xoá ra**. Nên một mã đã sạch mà lỡ kẹt lại thì nằm đó
**vĩnh viễn**, badge doctor warn mãi.

Kết cục quen thuộc: **badge đỏ cho một mã sạch**, tức dạy người dùng bỏ qua
badge — đúng thứ cả loạt bản vá này sinh ra để chặn (xem U42).

Nay `_rebase_one` nhận ra ca ấy và **XOÁ SỔ** thay vì từ chối, không cần
`--whole-series` (xoá một bản ghi cũ là việc nhỏ; bắt user gõ cờ ghi-đè-trọn-
lịch-sử cho nó là dạy sai thói quen). Chạy lại chính lệnh cũ là tự lành.

## `aligned` — cờ máy đọc được, không phải chuỗi tiếng Việt

`uniform_offset_report` nay trả thêm `aligned`. Cả `aligned` lẫn `uniform=False`
đều nghĩa là "không chữa được bằng chế độ này", nhưng một cái là **ĐÃ SẠCH**
còn cái kia là **KHÔNG ĐỦ BẰNG CHỨNG** — hai việc phải làm ngược nhau. Phân
biệt bằng cách dò chuỗi `why` là buộc logic vào câu chữ tiếng Việt: sửa một
dấu phẩy là gãy im lặng. Có test cấm việc đó.

⚠️ **`aligned=False` gồm cả "không đo được".** Xoá khỏi sổ vì KHÔNG BIẾT là gỡ
cách ly cho một mã mình không có thông tin gì — ngược hẳn việc cửa gác sinh ra
để làm. Chỉ xoá khi có bằng chứng DƯƠNG là đã sạch.

## Vì sao KHÔNG xoá sổ ở `vnstock_updater`

Đó mới là chỗ "đúng" về cấu trúc — gác đo mỗi đêm, thấy sạch thì tự xoá. Nhưng
sync chạy 8 worker; đọc-sửa-ghi sổ trong vòng lặp 1.700 mã là tự chuốc
lost-update vào đúng thứ sinh ra để giữ. Chọn đường công cụ: **cùng một lệnh
user đã chạy** sẽ dọn luôn bản ghi cũ. Đánh đổi: sổ chỉ vơi khi user chạy lệnh
đó, chứ không tự vơi sau mỗi đêm — badge có nhắc.

## Ba mã còn lại — đều là từ chối ĐÚNG

| mã | tỉ lệ | vì sao chưa chữa |
|---|---|---|
| ACE | 1.0853 (sổ) | **đã sạch thật** — chỉ bản ghi cũ, lượt sau tự xoá |
| DRG | 1.0206 | 0.9964× → 1.0213×, không lệch đều mà cũng KHÔNG chia sạch (`level_break_report` từ chối vì lẫn quá 10% bar sai phía) — cần mắt người |
| GH3 | 1.1356 | chỉ **13 bar** chồng nhau trong 365 ngày (sàn 20). Mã gần như không giao dịch; nay dòng từ chối in kèm tỉ lệ + spread để quyết được có đáng nới sàn riêng không |

## Số đo

Lượt 2: **67/70 mã, sổ 73 → 3**, không lỗi ghi nào (user đã tạm dừng Dropbox —
U46). Bộ dò vách MỨC của U45 gánh 9 mã: C22 · DBD · EMS · ILB · MCH · PRE ·
SDV · TRS · VC3, phía cơ sở mới **2-20 bar**, tất cả dưới hoặc quanh sàn 5 của
bộ dò bậc. **MCH (VN30) đã sạch.**

12 test mới. Suite: **3.089 pass**.

# 💥 U46. DROPBOX GIỮ FILE ⇒ `os.replace` NÉM WinError 5 — VÀ MỘT MÃ GIẾT CẢ LÔ (07/09)

🖥️ Desktop 21:07, lượt `--from-drift-ledger --whole-series --apply` trên **73
mã** (sổ đã phình từ 69 sau phát 18:00). Chữa xong AAM · ACE · AGG · BCF rồi
chết:

    [rebase] 💾 sao lưu: ...\backup_rebase\BRC_20260907-210744
    PermissionError: [WinError 5] Access is denied:
      '...\ticker=BRC\year=2011\1efa...-0.18844.tmp' -> '...-0.parquet'

**Nguyên nhân là hạ tầng, không phải logic.** Kho là junction vào Dropbox.
`shutil.copytree` sao lưu vừa chạm mọi file của mã xong thì Dropbox mở CHÍNH
CHÚNG để băm/tải lên ⇒ `os.replace` đâm vào khoá tạm **ngay sau dòng "💾 sao
lưu"**. Thứ tự thời gian trong log khớp chính xác.

## BRC KHÔNG hỏng — và biết được điều đó là nhờ thứ tự file

`_read_all` duyệt `sorted(tdir.glob("year=*/*.parquet"))`, `plan` giữ đúng thứ
tự chèn ⇒ `year=2011` là file **ĐẦU TIÊN**, và nó chết ở đúng file đó ⇒ **chưa
`os.replace` nào thành công** ⇒ BRC còn nguyên, chỉ sót một `.tmp`.

Nhưng đó là **may**, không phải thiết kế. Hỏng ở file thứ 9/18 thì mã LẪN HAI
CƠ SỞ — tệ hơn cả hai đầu, và không bộ dò nào gọi tên được nó cho gọn.

## Ba lỗi, cái thứ ba nặng nhất

**1. Không retry.** `_atomic_replace` nay thử lại 5 lượt, backoff 0.4s×2ⁿ. Bit
read-only thì retry vô ích nên **gỡ ngay lần hỏng ĐẦU** thay vì ngủ đủ 5 lượt.
Hỏng hẳn thì thông báo **gọi tên Dropbox và antivirus** — "Access is denied"
trần trụi không cho user biết phải làm gì. **KHÔNG BAO GIỜ rơi về copy-đè** —
đó là phá đúng bất biến `_MUST_BE_ATOMIC` mà retry sinh ra để giữ (có test).

**2. Rác `.tmp` ở lại** trong `prices/year=*/`, làm mọi bộ đếm file/năm sau đó
đọc sai. `_sweep_tmp` chỉ dọn tmp của **tiến trình mình** — xoá của tiến trình
khác là phá một lượt chạy song song.

**3. Một mã ném ra ngoài GIẾT CẢ LÔ.** 4/73 xong, **68 mã không bao giờ được
sờ tới**, mà đó vẫn là lệnh user được bảo chạy. Nay vòng lô bắt ngoại lệ từng
mã. Kèm **dừng sớm sau 3 lượt hỏng GHI liên tiếp**: hỏng ghi liên tiếp là
chuyện của cả thư mục, cày tiếp 70 mã để hỏng 70 lần là phí một tiếng và đẻ 70
thư mục sao lưu vô ích. Từ chối (rc=1) thì **KHÔNG** dừng — đó là kết luận về
một mã, hoàn toàn khác.

## `--restore` — đường về CÓ TEST

    python scripts/rebase_ticker_history.py --ticker BRC --restore --apply

Lấy bản `backup_rebase/<MÃ>_*` mới nhất (tên có timestamp nên sắp theo tên là
sắp theo thời gian). Vì sao không bảo user `Copy-Item` tay: nó chỉ dùng đến
khi vừa có sự cố ghi, tức đúng lúc dễ gõ nhầm nhất, và gõ nhầm ở đây là chép
đè lên một mã KHÁC. **Bản sao lưu RỖNG ⇒ từ chối** — khôi phục từ thư mục rỗng
mà "thành công" là xoá sạch kho của mã, hỏng nặng hơn hẳn thứ đang chữa.

## Vận hành

Trước lượt `--apply` hàng loạt: **tạm dừng đồng bộ Dropbox** (Pause syncing).
Kho dùng chung nên dừng vài phút không mất gì, và nó cắt tận gốc cả lớp lỗi.

## Đo được thêm

Sổ cách ly **69 → 73** sau phát 18:00 — gác vẫn đang bắt mã mới mỗi đêm, đúng
như thiết kế. ACE đi qua bộ dò vách MỚI của U45 và chữa sạch: *"MỨC lệch DỪNG
tại 2026-08-27 … (3 bar sau vách, dưới sàn 5 bar/phía của bộ dò bậc nên nó
im)"* — hệ số 1.0854×, 4.092 bar, tự kiểm ba lớp xanh. **U45 chạy đúng trên
dữ liệu thật.**

20 test mới ở `tests/test_rebase_write_failure.py`. Suite: **3.078 pass**.

# 🔍 U45. VÒNG TỰ KHOÁ THỨ HAI: BỘ DÒ ĐÒI BẰNG CHỨNG MÀ CỬA GÁC KHÔNG CHO SINH (26/08)

Lượt chạy thử 69 mã bằng `--from-drift-ledger --whole-series`: **56 qua, 13
bị từ chối**. Cả 13 có chung một chữ ký trong dòng từ chối:

    ACE  tỉ lệ LỞM CHỞM: 0.9997× → 1.0857×
    C22  tỉ lệ LỞM CHỞM: 1.0000× → 1.0621×
    MCH  tỉ lệ LỞM CHỞM: 1.0000× → 1.0149×
    …

**Cận dưới 1.0000×** — một phần chuỗi ĐÃ khớp nguồn. Đó không phải lệch đồng
đều; đó là **một vách thật**, và `--whole-series` từ chối hoàn toàn đúng.
Danh sách đủ: ACE · C22 · DBD · DRG · EMS · GH3 · ILB · MCH · PRE · SDV ·
TRS · VC3 · VSN (GH3 vì lý do khác: chỉ 13 bar chồng nhau).

## Vậy sao hai bộ dò bậc cũng im?

`find_basis_step` đòi đủ bar **MỖI PHÍA**:

    BASIS_MIN_SIDE = 5
    if i < BASIS_MIN_SIDE or len(r) - i < BASIS_MIN_SIDE:
        return None

Mã bị gác chặn sau ngày GDKHQ **3 phiên** chỉ có 2-3 bar ở phía cơ sở mới ⇒
dưới sàn ⇒ `None`. Đối chiếu cột ĐỨNG trong bảng triage: 8/13 mã đứng đúng
**3d**.

Và **phía đó không bao giờ mọc thêm** — chính cửa gác đang chặn cập nhật. Tức
**vòng tự khoá THỨ HAI**, khác vòng ở U42 nhưng cùng hình dạng: *bộ dò đòi một
thứ bằng chứng mà cửa gác không cho phép sinh ra.* U42 là "gác chặn ⇒ không
bao giờ sinh ra BẬC"; đây là "gác chặn ⇒ bậc có sinh ra nhưng KHÔNG BAO GIỜ ĐỦ
DÀY".

Đáng nhớ: cùng một cơ chế khoá, hai hình dạng khác nhau, và hình thứ hai chỉ
lộ ra khi chữa xong hình thứ nhất. Đừng cho rằng vá một vòng là hết vòng.

## Bộ dò vách THỨ BA — `level_break_report`

Không đếm bar mỗi phía. Hỏi **chỗ nào tỉ lệ thôi lệch**: bar lệch cuối cùng
+ 1 ngày. Đổi lại đòi **CHIA SẠCH**:

| cửa | ngưỡng | vì sao |
|---|---|---|
| bar đã sang cơ sở mới | ≥ `LEVEL_BREAK_MIN_AFTER` = **2** | phải THẤP hơn `BASIS_MIN_SIDE` = 5, không thì nó mù đúng chỗ bộ dò cũ mù (có test canh bất đẳng thức) |
| bar "sai phía" ở phía trước | ≤ `LEVEL_BREAK_MAX_DIRTY` = **10%** | vài bar khớp do làm tròn là thường; lẫn nhiều là lệch XEN KẼ, không phải một vách |
| lệch ở MỌI bar | ⇒ trả None | đó là ca `--whole-series`; trả mốc ở đây là hai đường chữa giành nhau một mã |

Thứ tự trong `_rebase_one`: `_find_break` → `_basis_break_of` →
**`_level_break_of`** → nhánh `--whole-series`. Có phía "cơ sở mới" thì đó là
vách, và đường vách **chính xác hơn** — nó chỉ đụng phần trước mốc, không ghi
đè trọn lịch sử. Có test canh thứ tự này.

Sau khi có mốc, đường chữa cũ chạy bình thường: `_probe` → `basis_report` (hàm
này **không có sàn bar nào**, chỉ cần hai phía không rỗng) → `warehouse_basis`
⇒ hệ số = `r_before / r_after`. Tức bản vá chỉ mở khoá, không nới cửa nào.

## Không nới cửa `--whole-series`

13 mã ấy bị từ chối là ĐÚNG. Test `test_the_uniform_gate_correctly_refuses_
this_shape` chốt cứng điều đó — bản vá không được lén nới trần spread để
"chữa được nhiều hơn".

## Số đo

56/69 chữa được ngay bằng lượt đầu. 19 test mới ở
`tests/test_rebase_level_break.py`, trong đó `TestTheGapIsReal` chứng minh
khoảng mù **bằng chính `find_basis_step` thật** (cùng bộ dữ liệu: bộ cũ trả
None, bộ mới chỉ đúng ngày, và bộ cũ tỉnh lại khi nới phía mới lên 20 bar).
Suite: **3.058 pass**.

# 🧭 U44. "TRA KHÔNG RA" CÓ HAI NGUYÊN NHÂN — VÀ CHÚNG CẦN HAI LỜI KHUYÊN NGƯỢC NHAU (26/08)

Bắt được ngay sau khi chữa xong SDK bằng U43. Sổ 70 → 69, rồi `triage --plan`
in lại đúng câu nó đã in sáng nay:

    ① NẠP LẠI KHO SỰ KIỆN TRƯỚC
    python run.py vietstock --bulk --register

**User đã chạy lệnh đó rồi** (sáng 26/08: `ok=1520 empty=180 fail=23`), và tỉ
lệ khớp vẫn 2/69 = 3%. Kế hoạch đang đẩy user vào lượt chạy 1.723 mã thứ hai
cho đúng một kết quả.

## Hai lỗi, không phải một

**1. `event_store_is_blind` không phân biệt SỔ TRỐNG với SỔ ĐẦY MÀ KHÔNG
KHỚP.** Nó chỉ đo tỉ lệ khớp. Hai trạng thái ấy cần hai lời khuyên **ngược
nhau**: sổ trống thì nạp là cứu; sổ 1.520 mã mà vẫn không khớp thì nạp lại là
phí một tiếng. Nay có `registry_size()` đọc thẳng số mã/số dòng trong
`corp_actions_registry.parquet` và kế hoạch rẽ theo đó.

**2. Kho sự kiện KHÔNG phải cửa của bước chữa — mà kế hoạch bắt nó làm cửa.**
`batch_plan` dừng hẳn ở "nạp lại kho" khi mù, `return lines` ngay, không đề
xuất gì thêm. Nhưng loại sự kiện chỉ trả lời **VÌ SAO** lệch; `--whole-series`
mang bằng chứng riêng về **CÁI GÌ**: tỉ lệ kho/nguồn có ĐỀU trên toàn dải
không. Bắt bước chữa chờ một kho tra cứu mà nó không cần = giam 69 mã vô thời
hạn vì một cửa không liên quan.

Trong `_rebase_one`, `_corp_action_kind` chỉ nuôi **quyết định khối lượng** —
và ở chế độ `--whole-series` khối lượng luôn giữ nguyên. Tức kho sự kiện mù
**không ảnh hưởng gì** tới đường chữa này.

## Bất biến cũ được phát biểu lại, không bị bỏ

Lưới cũ chốt *"kho mù ⇒ KHÔNG có lệnh rebase nào"*. Chặt quá mức **và chặt sai
chỗ**. Thứ thật sự phải cấm là **liệt kê tên mã chưa rõ nguyên nhân vào một
lệnh chữa hàng loạt** — khi đó không còn cửa nào đứng giữa. Lệnh theo sổ cách
ly (`--from-drift-ledger`) không nêu tên mã nào: mỗi mã tự qua
`uniform_offset_report` và **bị từ chối riêng**. Test đã đổi theo:
`test_it_never_NAMES_an_unknown_cause_ticker_in_a_rebase_command` + một test
đòi lệnh đó phải tồn tại (*"giam mã vô thời hạn cũng là một cách hỏng"*).

## `--from-drift-ledger` — vì sao `--from-sweep` không dùng được

Vết quét `basis_sweep_check.json` cũng dựng trên `find_basis_step`, tức **cùng
bộ dò đạo hàm đang mù** (U42). Mã lệch đồng đều không bao giờ vào `suspect`,
và suspect rỗng thì rebase exit 2. Sổ cách ly thì do **cửa gác** ghi, mà gác đo
MỨC ⇒ nó là nguồn DUY NHẤT liệt kê đúng lớp mã này. Sổ rỗng ⇒ **exit 0**, không
phải lỗi: rỗng nghĩa là không còn gì để chữa.

## Rào ĐƠN VỊ, thêm cùng lúc

`UNIFORM_MAX_FACTOR = 10.0`. Lệch đơn vị (đồng ⇄ nghìn đồng) **cũng đều tăm
tắp**, nên nó qua cửa "spread" một cách hoàn hảo — không có trần thì
`--whole-series` sẽ ghi đè trọn lịch sử vì một lý do hoàn toàn khác. Sự kiện
quyền lớn nhất thực tế ~1:4 (5×), nên trần 10× nằm trên mọi ca thật mà vẫn bắt
được cỡ 1.000×. Ca đó thuộc `check_unit_continuity` / `run.py fix-units`.

## Số đo lúc đóng mục

SDK chữa xong: 3.744 bar lấy thẳng nguồn · 19 bar (10/2010, trước độ phủ nguồn)
nhân hệ số · 17 file · cả ba lớp tự kiểm xanh. Còn **69 mã**, tỉ lệ 1.015-1.232
— toàn cỡ **cổ tức**, nhỏ hơn hẳn SDK (1.4858). Suite: **3.039 pass**.

# 🔧 U43. `--whole-series`: ĐƯỜNG CHỮA CHO LỚP LỆCH ĐỒNG ĐỀU (26/08)

Đóng phần **"Còn treo"** của U42. U42 chỉ làm công cụ **từ chối trung thực**;
mục này là đường CHỮA thật. Đọc U42 trước — nó giải thích vì sao mọi bộ dò
bậc đều mù với lớp lỗi này.

## Vì sao phải là một đường RIÊNG, không phải nới cửa cũ

Đường chữa cũ dựng trên một giả định: **có một vách**, trước vách là cơ sở cũ,
sau vách là cơ sở mới, hệ số = trung vị trước / trung vị sau. Lớp lỗi này phá
đúng giả định đó — lệch đều thì **trước = sau**, nên:

* `_find_break`, `find_basis_step` → `None` (đạo hàm bằng 0 ở mọi điểm);
* `_probe` → `basis_report` → verdict **`aligned`** ⇒ cửa
  `verdict == "warehouse_basis"` không bao giờ mở, kể cả khi ép `--break-date`.

Nới cửa cũ (kiểu "aligned mà vẫn lệch thì cho qua") là bỏ luôn thứ cửa ấy sinh
ra để chặn. Nên `--whole-series` **bỏ hẳn `_probe`** — hỏi nó là hỏi sai câu —
và thay bằng một cửa KHÁC, chặt hơn.

## Cửa mới: `uniform_offset_report` — đòi ỔN ĐỊNH, không chỉ đòi CÓ LỆCH

Ghi đè trọn lịch sử là việc không lùi được, nên cửa duy nhất cho phép nó phải
trả lời hai câu TÁCH BẠCH:

| câu hỏi | công thức | ngưỡng |
|---|---|---|
| có lệch không | `\|trung vị(kho/nguồn) − 1\| > tol` | `tol` = `basis_guard.TOL` = 0.012 |
| lệch có ĐỀU không | `max(tỉ lệ) / min(tỉ lệ)` | `UNIFORM_SPREAD_MAX` = **1.01** |
| đủ bằng chứng chưa | số bar chồng nhau | `UNIFORM_MIN_BARS` = **20** |

Câu thứ hai mới là cửa thật. Lệch **đều** = nguồn back-adjust một lần, sạch,
kho chỉ việc lấy lại. Lệch **lởm chởm** = còn chuyện khác trộn vào (nhiều lần
rebase chồng nhau, bar hỏng, sai đơn vị lẻ tẻ) — nhân cả chuỗi bằng MỘT hệ số
khi đó là **bôi cái sai ra khắp lịch sử**. Trần 1.01 cố ý **chặt hơn** `TOL`
của gác (0.012): cửa ghi-đè-trọn-lịch-sử mà lỏng hơn cửa chặn hằng đêm thì có
ca gác chặn mà công cụ vẫn hồn nhiên ghi đè. Có test canh bất đẳng thức này.

## Mốc ẢO thay cho vách

Không có vách ⇒ lấy `_last_wh_bar + 1 ngày` làm mốc, tức **coi TOÀN chuỗi là
phần "trước vách"**. Đọc không được bar cuối → **từ chối**, không đoán: đoán
đại một mốc ở đây là ghi đè nhầm nửa lịch sử.

Hệ quả: phía "sau vách" rỗng ⇒ `_volume_step` = `nan`. Lấy chính `nan` đó làm
lý do giữ khối lượng thì đúng số mà **sai chuyện** (người đọc đi tìm một cái
vách không tồn tại), nên chế độ này có câu trả lời riêng: *back-adjust GIÁ
không tạo thêm cổ phiếu nào, và không có vách thì cũng không có bậc nhảy khối
lượng làm bằng chứng*. Giữ nguyên là MẶC ĐỊNH, không phải chốt chết —
`--volume adjust` vẫn ép được.

## Bước tự kiểm THỨ BA — `_residual_level`

Hai bước tự kiểm cũ đều đo **đạo hàm**: `find_jumps` (vách giá ≥30%) và
`_residual_basis_step` (đổi bậc tỉ lệ). Tức chúng **mù đúng lớp lỗi mà chế độ
này sinh ra để chữa**: chữa hụt hệ số để lại một chuỗi vẫn lệch ĐỀU, và cả hai
in xanh. *Tự kiểm mà mù đúng lớp lỗi mình sinh ra để chữa thì không phải tự
kiểm.* Nay có bước thứ ba đo MỨC, dùng lại `last_divergent_day` + `src_all`
**đã fetch** — tự kiểm không được gọi mạng lần nữa, vì nguồn đổi giữa chừng
thì đỏ/xanh không còn nói về việc mình vừa làm. Có test chứng minh bằng chính
hàm thật: cùng bộ dữ liệu, hai bước cũ im, bước mới kêu.

## Một vết bắt được ngay lúc viết lưới

Nhánh mới ĐẶT mốc ảo rồi đi tiếp, nhưng dòng `"✅ không còn vách nghi vấn"` nằm
CÙNG khối `if brk is None:` nên vẫn chạy — in "LỆCH ĐỒNG ĐỀU" xong in luôn
"✅ sạch" rồi exit 0 mà **không ghi gì**. Đúng cái bệnh báo-thành-công-sai mà
chế độ này sinh ra để chữa, tái sinh trong chính bản vá. Đã thêm `if brk is
None:` lồng vào và một test canh riêng (`test_it_never_prints_the_clean_line_
after_deciding_to_fix`).

## Cửa an toàn

* Mặc định vẫn **CHẠY THỬ**; phải `--apply` mới ghi.
* `--whole-series` + `--break-date` ⇒ **`ap.error`**, không nhận rồi âm thầm bỏ
  một cái (đó là cách chắc chắn để người dùng tưởng mình đã chạy chế độ kia).
* Sao lưu nguyên thư mục mã trước khi ghi; ghi nguyên tử tmp + `os.replace`.
* Chữa xong tự `clear_drift` để mã rời sổ cách ly — để lại là doctor kêu mãi
  và người dùng học cách bỏ qua badge.

## Lệnh (○ một lần — kho đi qua Dropbox, KHÔNG phải ⇄ cả hai)

    python scripts/rebase_ticker_history.py --ticker SDK --whole-series
    python scripts/rebase_ticker_history.py --ticker SDK --whole-series --apply

Chạy **sau 19:xx** (ngoài giờ pipeline) — đây là đường GHI KHO. Soi lại bằng
`triage_basis_drift --plan`: mã đã chữa phải rời sổ.

32 test mới ở `tests/test_rebase_whole_series.py`. Toàn bộ suite: **3.023 pass**.

# ⛔ U42. BẾ TẮC: CỬA GÁC CHẶN VĨNH VIỄN, CÔNG CỤ CHỮA IN "✅ SẠCH" — ĐÃ VÁ (26/08)

Phản biện đối kháng 4 góc nhìn: **3/4 xác nhận**, và phiếu chi tiết nhất
**dựng lại được toàn bộ ca bằng dữ liệu giả**, không phải suy diễn.

## Gốc rễ: hai bên hỏi HAI CÂU KHÁC NHAU

| ai | đo gì | công thức |
|---|---|---|
| `check_basis` — **CỬA GÁC** | **MỨC** | trung vị `wh/src`, rồi `|r − 1| > TOL` |
| `find_basis_step` — bộ dò | **ĐẠO HÀM** | `jumps = |r[1:]/r[:-1] − 1|` |
| `_find_break` — bộ dò | **ĐẠO HÀM**, chỉ chuỗi KHO | vách giá ≥30% |

Gác hỏi *"tỉ lệ có KHÁC 1 không"*; bộ dò hỏi *"tỉ lệ có ĐỔI không"*. Nguồn
back-adjust TRỌN lịch sử ⇒ lệch **ĐỒNG ĐỀU** ⇒ đạo hàm = 0 ở mọi điểm ⇒
**cả hai bộ dò trả None**, gác thì chặn.

Chạy thật trên dữ liệu dựng lại (60 bar, lệch đều 1.4857×):

    find_basis_step  -> None
    find_jumps       -> []
    basis_report     -> verdict 'aligned' (before = after = 1.4857)
    check_basis      -> {'ratio': 1.4857, 'verdict': 'basis_changed'}
    _rebase_one      -> "✅ SDK: không còn vách nghi vấn trong 365 ngày" · exit 0

## Vòng lặp TỰ NUÔI

`update_ticker` đặt `fetch_from = last_date`; khi gác phán `basis_changed` nó
`return` NGAY, **trước mọi lệnh ghi** ⇒ `last_date` đóng băng ⇒ đêm sau cửa sổ
đối chiếu vẫn nằm trọn trong phần cơ sở CŨ ⇒ tỉ lệ vẫn 1.4857 ⇒ lại cách ly.

⚠️ Docstring của gác hứa *"chỉ kêu trong ~LOOKBACK_DAYS rồi tỉ lệ về 1.0 và
guard im"* — lời hứa đó **chỉ đúng với mã được nối bar cơ sở mới TRƯỚC khi có
gác**. Mã bị chính gác chặn thì kho không bao giờ có bar cơ sở mới.

## Cửa thoát tay CŨNG bị khoá

Ép `--break-date`: `basis_report` so trung vị hai phía ngày vách; lệch đồng
đều ⇒ before = after ⇒ `same=True`, `has_break=False` ⇒ verdict **`aligned`**
⇒ `"✗ TỪ CHỐI: probe phán 'aligned'"`, exit 1. **Không đường nào chữa được.**

## Hai chỗ tôi nói QUÁ, phiếu phản biện sửa lại

* **Không phải `--from-sweep`.** Mã lệch đồng đều không bao giờ vào
  `basis_sweep_check.json:suspect` (sweep cũng dùng `find_basis_step`), và
  suspect rỗng thì rebase **exit 2**. Đường thật tới ✅ giả là:
  `triage_basis_drift --plan` → sinh `rebase_ticker_history --ticker <MÃ>` →
  nhánh tự dò → ✅ exit 0. **Tức chính script tôi viết sáng nay sinh ra lệnh
  đó.**
* **"Không có cảnh báo nào" là quá mạnh.** Badge doctor `basis_drift` giữ
  warn **vĩnh viễn** (mã chỉ rời sổ khi `clear_drift` chạy cuối nhánh
  `--apply` thành công). Cái thiếu là cảnh báo TỪ CHÍNH CÔNG CỤ CHỮA — và đó
  là hình dạng tệ nhất: badge đỏ mãi trong khi công cụ chữa in ✅, đúng kiểu
  dạy người dùng bỏ qua badge.

## Vá

`last_divergent_day` — đo MỨC từng bar — **vốn đã nằm sẵn trong chính
`rebase_ticker_history.py`, kèm test**. Nó chỉ đứng SAU hai cửa mù nên không
bao giờ được chạm tới. Cửa thoát có sẵn, bị nhốt sau cửa khoá.

Nay `_rebase_one` trước khi tuyên bố sạch phải hỏi thêm `_level_divergence`
(dùng lại `last_divergent_day`, cùng `TOL` với gác — có test canh) **và** sổ
cách ly `_in_drift_ledger`. Một trong hai lên tiếng ⇒ **từ chối, exit 1, nói
rõ vì sao cách chữa thông thường không áp dụng được**, thay vì ✅ giả.

## Một test cũ đỏ lên — và nó ĐÚNG khi đỏ

`test_clean_ticker_is_a_noop` dựng kho `10.0…11.1` trong khi `stub_source` là
`70…81` — **lệch ~7× ở MỌI bar**. Nó xanh suốt vì hồi đó "sạch" nghĩa là
"không có bậc nhảy". Đã sửa FIXTURE cho khớp nguồn, **không nới bộ dò**, và
thêm `test_a_uniformly_offset_ticker_is_NOT_called_clean` canh đúng ca này.

## Còn treo

Bản vá làm công cụ **từ chối trung thực** thay vì báo sạch giả. Nó CHƯA chữa
được lớp lỗi này — chữa đúng phải là **nạp lại trọn lịch sử mã từ nguồn**
(không có vách nào để làm mốc mà nhân). Đó là việc GHI KHO, để sau phát 18:00.

18 test mới ở `tests/test_rebase_level_guard.py` + 1 ở `test_rebase_history.py`.

# 🎯 U41. EX-DATE NẰM **SAU** CỬA SỔ ĐỐI CHIẾU — VÀ TEST CỦA TÔI CHỐT CỨNG CHIỀU SAI (26/08)

Cho fan-out đọc lại mã nguồn vì tôi đã sai ba lần trong ngày. Nó bác đúng giả
thuyết của tôi, kèm chứng minh.

## Chứng minh: ex_date > `last`

Cơ chế lỗi (ghi ngay đầu `vnstock_basis_guard`): nguồn **back-adjust MỌI bar
TRƯỚC ex_date**, bar từ ex_date trở đi giữ nguyên. Đặt ρ(d) = kho(d)/nguồn(d):

    ρ(d) = f ≠ 1   với d < ex_date
    ρ(d) = 1.0     với d ≥ ex_date

`check_basis` chỉ báo `basis_changed` khi **trung vị ρ** trên `[first, last]`
lệch khỏi 1 ⇒ **mọi bar trong khoảng phải cùng một phía của ex_date** ⇒
**ex_date > `last`**.

Chiều ngược lại cũng chặn: ex_date nằm TRƯỚC khoảng thì kho đã ở cơ sở mới,
ρ = 1, verdict `aligned`, **guard câm hẳn** — đúng như docstring của guard tự
nói: *"bắt đúng khoảnh khắc lệch sinh ra, không bắt di chứng cũ."*

Và cửa sổ đối chiếu **HẸP** — `WANT_BARS = MIN_BARS + 3 = 8`, tức ~7 phiên
ngay trước `last_date`, KHÔNG phải 30 ngày. Càng không thể chứa ex_date.

## Bug trong code tôi viết cùng ngày

`registry_event_kind` lọc `ex >= start & ex <= end` với `(start, end) =
(first, last)` — **khoảng mà ex_date chắc chắn KHÔNG nằm trong**. Nhánh tra sổ
đăng ký vì thế **trượt 100% về mặt cấu trúc**. Đó là lý do ra 1/70 dù sổ đăng
ký đã có 1.520 mã.

Nhánh kia (`event_around` → `_corp_event_kind` nới ±10 ngày quanh `last`) may
mà đúng chiều, nhưng nó tra **cache theo mã** — kho đang cũ (U40).

⇒ `event_window` nay tìm **VỀ PHÍA TRƯỚC**: `(last, detected_at + 5]`, chặn
trên bằng hôm nay. Đó đúng là khe mà kho chưa cập nhật — nơi ex_date phải nằm.

## ⚠️ Lỗi đáng ghi nhất: TEST CỦA TÔI CHỐT CỨNG CHIỀU SAI

`TestEventWindow` bản đầu có `test_it_uses_the_recorded_comparison_window`,
khẳng định `event_window` trả đúng `(first, last)`. Test **XANH**, code
**trượt 100%**. Lưới không bắt được gì vì nó được viết từ cùng một niềm tin
sai với code.

Bài học: test chỉ canh được thứ mình đã hiểu đúng. Với một cơ chế chưa nắm
chắc, phải **suy ra chiều từ mã nguồn của cơ chế** (ở đây: `check_basis` đo
trung vị ⇒ mọi bar cùng phía ⇒ ex_date ở phía nào) rồi mới viết test — chứ
viết test theo trực giác thì chỉ đóng dấu cho trực giác.

Lưới mới có `test_it_never_looks_inside_the_comparison_window` — canh đúng
chiều, và tên nói thẳng chiều nào là sai.

## Còn treo — đang phản biện riêng

`probe_price_basis --ticker SDK` (lệch 1.4857×) in ra *"không tìm thấy vách
nghi vấn trong 365 ngày"*. Cùng lúc `_rebase_one` khi không có vách sẽ in
**"✅ không còn vách nghi vấn"** và **return 0**. Nghi vấn: cửa gác và công cụ
chữa bất đồng vĩnh viễn, cả hai cùng báo thành công. Đang cho 4 góc nhìn phản
biện — chưa chốt.

**Cho tới khi chốt: KHÔNG chạy `rebase_ticker_history --from-sweep`.**

# 🧨 U40. HAI KHO SỰ KIỆN QUYỀN SONG SONG — TÔI BẢO USER NẠP NHẦM KHO (26/08)

Sau khi nạp `vietstock --bulk --register` (ok=1520/1723), chạy lại bộ soi:
**vẫn 0/70**. Và sổ đã phình **47 → 70 mã · đứng lâu nhất 17 ngày · ~713 bar
giá đang thiếu**.

## Nguyên nhân: app có HAI kho sự kiện, không nói chuyện với nhau

| kho | file | ai NẠP | ai ĐỌC |
|---|---|---|---|
| **cache theo mã** | `_meta/corp_actions/<MÃ>.parquet` | `vnstock_adjust.refresh_events` (API vnstock) | `load_events` → `vnstock_updater._corp_event_kind` → **CỬA GÁC** |
| **sổ đăng ký** | `_meta/corp_actions_registry.parquet` | `run.py vietstock --register`, `run.py registry` | `vnstock_corp_registry`, `load_recent_exdiv` (U36) |

`vietstock --bulk --register` → `fetch_and_register` → `register_bulk` → ghi
**sổ đăng ký**. Cửa gác tra **cache theo mã**. Giao nhau bằng KHÔNG.

⇒ **Tôi bảo user nạp nhầm kho**, và mất một lượt quét 1.723 mã để biết. Lượt
đó không phí hẳn — nó chính là thứ làm badge `exdiv_source` (U36) sống, vì
`load_recent_exdiv` đọc sổ đăng ký. Nhưng nó KHÔNG làm cái tôi hứa.

**Bài học đúng loại:** trước khi bảo người khác chạy một lệnh để chữa X, phải
kiểm chỗ X ĐỌC, không chỉ kiểm lệnh đó GHI cái gì. Hai cái tên đều là "corp
actions" nên nhìn lướt thì tưởng là một.

## Vá (bộ soi)

`triage_basis_drift` nay hỏi **CẢ HAI** kho: `live_event_kind` (cache theo mã)
rồi `registry_event_kind` (sổ đăng ký). Không kho nào trả lời mới là "chưa tra
được".

Tìm trong sổ đăng ký theo **KHOẢNG** — chính cửa sổ so sánh đã ghi trong sổ
cách ly (`event_window`) — chứ không phải một ngày ± N. Vách gãy nằm đâu đó
TRONG khoảng ấy; lấy một ngày rồi nới là đoán chỗ gãy. Có test canh việc
KHÔNG vơ sự kiện ngoài khoảng: gán sai nguyên nhân thì mã đó rơi thẳng vào
nhóm "chữa máy móc được".

## Còn nợ — lỗi GỐC chưa vá

`vnstock_updater._corp_event_kind` (thứ ghi nhãn `event` vào sổ cách ly lúc
phát hiện) **vẫn chỉ đọc cache theo mã**. Nên mọi lần chặn mới vẫn ghi
`event: None` dù sổ đăng ký có sự kiện. Bộ soi che được, nhưng cái nhãn trong
sổ vẫn sai.

Chưa vá vì `load_events` còn phục vụ đường ĐIỀU CHỈNH GIÁ — sửa nó là đụng
vùng rộng hơn nhiều, và tối nay là đêm đo 4 bản vá. **Đo xong rồi sửa gốc.**

11 test mới (tổng 84 ở `tests/test_triage_basis_drift.py`).

# 🔄 U39. SỔ CÁCH LY GHI ẢNH CHỤP, KHÔNG PHẢI SỰ THẬT HIỆN TẠI (26/08)

User nạp kho sự kiện: `run.py vietstock --bulk --register` →
**ok=1520 · empty=180 · fail=23** trên 1.723 mã. Kho sự kiện nay DÀY.

**Bẫy suýt làm cả việc nạp kho trông như vô ích:** trường `event` trong
`_meta/basis_drift_pending.json` là **ảnh chụp lúc PHÁT HIỆN** —
`vnstock_updater` ghi nó vào đúng lúc mã bị chặn (`vnstock_updater.py:561`).
Nạp lại kho sự kiện **KHÔNG viết ngược lại sổ**. Nên bộ soi chỉ đọc ảnh chụp
⇒ nạp kho xong chạy lại vẫn ra **y nguyên 0/47**, và người đọc kết luận việc
nạp kho vô ích — trong khi thật ra đang đọc số cũ.

⇒ `triage_basis_drift` nay **TRA LẠI** kho sự kiện tại thời điểm soi
(`live_event_kind` → `vnstock_updater._corp_event_kind`, chỉ đọc parquet),
và in ra `🔄 tra LẠI: N mã nay ra được loại sự kiện mà sổ cũ không có`. Con số
N chính là **bằng chứng việc nạp kho có tác dụng**.

Ba ràng buộc đã cài:
* **Sổ đã ghi được loại thì GIỮ NGUYÊN** — đó là số đo tại thời điểm phát
  hiện, tra lại không được đè lên.
* `event_around` lấy **cuối cửa sổ so sánh**, không có thì ngày phát hiện;
  không đọc được thì **None**, KHÔNG rơi về `today` — bịa một ngày vách rồi
  tra sự kiện quanh mốc không có thật là tự tạo dữ kiện.
* Tra lại hỏng ⇒ trả None, không ném. Bộ soi chết vì kho sự kiện hỏng thì
  mất luôn thứ duy nhất đang nói cho user biết 47 mã đang đứng giá.

`--no-relookup` để xem số cũ khi cần đối chiếu.

## Ghi chú về thời điểm — tôi đã cảnh báo RỘNG QUÁ

Tôi bảo "đừng chạy trước 19:xx" cho cả `vietstock --bulk --register`. Thật ra
lệnh đó chỉ ghi `_meta/corp_actions/` + `corp_actions_registry.parquet` —
**không đụng giá, không đụng `net_bs_cache.json`**, nên vô hại với phép đo
phát 18:00. Thứ THẬT SỰ phải đợi là `rebase_ticker_history --apply`, vì nó
ghi đè LỊCH SỬ GIÁ.

13 test mới (tổng 73 ở `tests/test_triage_basis_drift.py`).

# 🧭 U38. 0/47 TRA RA SỰ KIỆN — LỖI Ở KHO TRA CỨU, KHÔNG Ở 47 MÃ (26/08)

Chạy `triage_basis_drift --plan` trên máy thật. Con số đáng giá nhất là con
số **KHÔNG có**: nhóm "có sự kiện quyền khớp" **trống trơn — 0/47**.

    🔴 KHÔNG sự kiện, tỉ lệ lẻ · 34 mã
    🟡 tỉ lệ TRÒN, chưa khớp sự kiện · 12 mã
    ⚪ sát ngưỡng · 1 mã (MCH — VN30, đứng 5 ngày, 1,48%)
    ✅ có sự kiện · 0 mã
    đứng lâu nhất 5 ngày · tổng ~154 bar giá đang thiếu

## Đọc đúng: `event: None` = KHO KHÔNG BIẾT

Chính `vnstock_updater._corp_event_kind` đã ghi sẵn:
*"Kho sự kiện đang MỎNG (19/08: 70 mã lệch chỉ 3 mã tra ra loại)"*.
19/08: 3/70. 26/08: **0/47**. Đang tệ đi.

**Vì sao tệ dần:** 14 bước của `cmd_all` là sync · validate · screener ·
foreign-flow · macro · gold · allocation · test · audit · train · reflection ·
doctor · brief (+news). **KHÔNG có `vietstock`, không có `registry`.** Kho sự
kiện quyền chỉ được nạp BẰNG TAY ⇒ nó cũ dần theo thời gian, trong khi sự
kiện quyền vẫn diễn ra mỗi ngày. Cửa gác chặn đúng, tra tên không ra, mã nằm
lại sổ vĩnh viễn chờ người.

⇒ **Đây là lỗi cấu trúc, không phải 47 sự cố riêng lẻ.**

## Bộ soi của tôi ĐỌC SAI, và tôi đã sửa trong cùng ngày

Bản đầu (U37) xếp 34 mã vào *"🔴 chưa biết vì sao — CHỮA MÙ Ở ĐÂY LÀ NHÂN BẢN
SỐ SAI"*. Đọc như thể **các mã** đáng ngờ. Thực tế lỗi ở **kho tra cứu**, và
cách trình bày đó đẩy người dùng đi soi tay 46 mã — để rồi phát hiện gần như
tất cả đều là cổ tức. 46 lần phí công, và là cách chắc chắn nhất để bỏ cuộc
giữa chừng.

Đã thêm `event_store_is_blind`: tra ra <10% trên sổ ≥10 mã ⇒ in cảnh báo
NGAY ĐẦU rằng **đây là phát biểu về KHO SỰ KIỆN, không phải về các mã**, đổi
nhãn nhóm đỏ thành **"CHƯA TRA ĐƯỢC"**, **giấu** câu "nhân bản số sai" (đúng
khi kho tra được mà vẫn không khớp; khi kho mù thì chỉ làm sợ nhầm chỗ), và
`batch_plan` **thay 46 lệnh soi tay bằng 2 lệnh**: nạp kho → chạy lại.

Sàn `BLIND_MIN_N = 10` để không kết luận từ mẫu bé — đúng vết 13/08 (n=2 vẽ
thành "0%").

## Một ngưỡng tôi đặt sai, cũng sửa luôn

`NOISE_PCT` ban đầu là **1,5 hằng số**, trong khi cửa gác kích hoạt ở
`vnstock_basis_guard.TOL = 0.012` (1,2%). Tức tôi đẻ ra ngưỡng thứ hai phải
giữ đồng bộ bằng tay — đúng thứ `CLAUDE.md` cấm. Nay dẫn xuất:
`NOISE_PCT = TOL × 100 × 1,25`, có test canh nó bám vào `TOL`.

Hệ quả cụ thể: **MCH** (VN30) ở 1,48% nằm trong vùng "sát ngưỡng" — vẫn phải
nhìn, vì nó là mã VN30 và đã đứng 5 ngày, nhưng ở quanh mốc 1,2% thì làm tròn
giá đủ gây ra (ghi sẵn trong `vnstock_basis_guard`).

## Đề xuất cấu trúc — CHƯA làm, cần đo

Thêm bước làm mới kho sự kiện vào `cmd_all`. Nhưng nó **thêm thời gian vào
pipeline vừa mới lấy lại được đệm**, và tối nay đã là đêm đo 4 bản vá. Đo
trước, thêm sau.

60 test ở `tests/test_triage_basis_drift.py`.

# 🔬 U37. 47 MÃ ĐỨNG GIÁ — PHÂN LOẠI TRƯỚC KHI CHỮA (26/08)

`run.py doctor` trên máy thật: **47 mã ĐANG KHÔNG cập nhật giá**, ngày phát
hiện trải **21/08 → 25/08** ⇒ **đang tích tụ**, không phải một cục cũ. Cửa gác
lệch cơ sở (V1, U-basis) làm đúng việc — chặn không nối data lệch — nhưng chặn
xong thì chờ người chữa.

## Vì sao KHÔNG chạy thẳng `rebase_ticker_history --from-sweep`

Công cụ chữa hàng loạt đã có sẵn. Nhưng "47 mã" không nói được thứ quyết định
cách xử lý: **mỗi mã lệch VÌ SAO.**

* **Có sự kiện quyền khớp ngày vách** ⇒ lệch là ĐÚNG DỰ KIẾN, kho chỉ chưa
  nối lại thang giá. Chữa máy móc, hàng loạt, an toàn.
* **Không sự kiện nào** ⇒ chưa biết vì sao. Chữa mù ở đây là **nhân bản một
  con số sai lên TOÀN BỘ lịch sử của mã** — đúng thứ cửa gác sinh ra để chặn.

Gộp hai nhóm vào một lệnh là bỏ qua đúng chỗ cần người quyết.

## `scripts/triage_basis_drift.py` — CHỈ ĐỌC

Chạy được lúc nào cũng được, kể cả sát 18:00. Có lưới canh điều đó
(`test_the_script_never_imports_a_writer`: cấm `write_text` / `to_parquet` /
`subprocess` / `shutil`; **in ra** một lệnh có `--apply` thì hợp lệ — script
gợi ý, người chạy).

Bốn nhóm: `co_su_kien` ✅ · `tron_chua_ro` 🟡 · `chua_ro` 🔴 · `nhieu` ⚪.
Kèm **số ngày đứng** và **tổng bar giá đang thiếu** — đó mới là con số đọc ra
được TÁC ĐỘNG. Và cờ **mã VN30 nào đang bị cách ly**: một mã VN30 đứng giá
nặng hơn hẳn (vào chỉ số, vào brief, vào heatmap tầng nóng) mà lẫn trong 47
cái tên thì không ai nhận ra.

`--plan` in kế hoạch: chạy thử TRƯỚC `--apply`, và **nhóm 🔴 không bao giờ
lọt vào lệnh rebase** — đó là bất biến quan trọng nhất, có test riêng.

## ⚠️ Dung sai "tỉ lệ tròn" phải CHẶT — bắt được ngay khi viết test

Bản đầu để `ROUND_TOL = 0.015`, mà các mốc (1.05 / 1.10 / 1.15…) cách nhau
0,05 ⇒ **bắt nhầm gần một phần ba dải**. Cụ thể: AAM `1.0424` "khớp" `1.05`
rồi tụt từ nhóm 🔴 xuống 🟡 — đúng cái nhóm cần người nhìn. Siết còn `0.005`.
**Gợi ý bắt bừa tệ hơn không gợi ý**, vì nó xếp một mã đáng ngờ vào ô "chắc
là quyền thôi".

## Chưa làm

Chưa chạy trên kho thật — container không có kho. Con số phân nhóm thật sẽ ra
ở lượt user chạy. Và **việc CHỮA ghi kho**: kho dùng chung qua Dropbox nên
laptop chữa là desktop thấy ⇒ đừng chữa trong lúc phát 18:00-19:xx.

44 test ở `tests/test_triage_basis_drift.py`.

# 🩹 U36. BỘ CHẶN CỜ CỔ TỨC CHẠY CHAY TỪ 19/08 — MỘT LỖI IM LẶNG (26/08)

Đi tìm câu trả lời cho việc #4 ("bỏ hay giữ đường CafeF `cash-dividends`") thì
lòi ra chuyện lớn hơn: **cái nó nuôi đã chết theo nó, và không ai biết.**

## Chuỗi phụ thuộc

    dashboard/market_commentary.py:171
      → load_recent_exdiv(days_back=7)            (vnstock_market_analyzer)
        → _meta/cash_dividends/*.json             ← nguồn DUY NHẤT
          ← run.py cash-dividends                 ← cào CafeF

Ba dữ kiện cộng lại thành một lỗi im lặng:
1. `run.py cash-dividends` cào CafeF, **404 từ 19/08** (U17 mục 2).
2. Lệnh đó **KHÔNG nằm trong `cmd_all`** — chưa bao giờ tự chạy, chỉ gõ tay.
3. Cửa sổ mặc định **7 ngày**.

⇒ Từ khoảng 26/08, `load_recent_exdiv` **luôn trả `{}`**. Công dụng của nó là
**bỏ qua cờ "phân phối"** khi giá rơi chỉ vì cổ tức — nên cờ phân phối GIẢ đi
thẳng ra dashboard mỗi lần một mã GDKHQ. Và `{}` là giá trị hợp lệ nên không
chỗ nào kêu. **Code chết trông y như code sống**, đúng cái repo này sợ nhất.

## Vá

`_meta/corp_actions_registry.parquet` đã có sẵn cột `cash_amount` và được
NHIỀU nguồn nạp (vietstock, capital_history, manual), không phụ thuộc CafeF.

* `_exdiv_from_registry` — đường CHÍNH: lọc `type == "cash"`, trong cửa sổ,
  mã trùng thì lấy kỳ MỚI NHẤT.
* `_exdiv_from_cafef_cache` — đường cũ, giữ làm lưới sau.
* `load_recent_exdiv` **HỢP NHẤT hai đường**, sổ thắng khi trùng mã. Không
  loại nhau: mã chỉ có ở kho cũ vẫn được giữ — bỏ đi là mất một lần chặn cờ
  giả mà chẳng được gì.
* Sổ có sự kiện mà **thiếu số tiền** vẫn chặn cờ (amount=0). Sự kiện tồn tại
  đã là bằng chứng giá rơi vì cổ tức; bỏ dòng đó chỉ vì thiếu một con số là
  vứt luôn phần biết được.

## Badge `exdiv_source` — để lần sau nó TỰ nổi lên

Chỗ khó của badge này: **7 ngày không mã nào chia cổ tức là chuyện BÌNH
THƯỜNG.** Kêu vì rỗng là báo động giả, mà báo động giả dạy người ta bỏ qua
badge — hỏng nặng hơn cái nó cảnh báo. Nên nó chỉ warn khi **cả sổ đăng ký
cũng trống rỗng ở MỌI kỳ**, tức không phải "tuần này không có" mà là "không
có nguồn". Câu `fix` chỉ sang `run.py vietstock --bulk --register`, và nói
thẳng rằng `run.py cash-dividends` đã 404 — gợi ý một lệnh đã chết chính là
cái bẫy vừa gỡ.

## ✅ Đã XOÁ đường CafeF — cùng ngày, sau khi có bằng chứng

Badge trên máy thật (💻 laptop, 26/08) báo **`đường registry trả 1 mã trong 7
ngày`** ⇒ sổ đăng ký gánh được. Đó là điều kiện đã đặt ra, nên xoá:

* `vnstock_cash_dividends.py` (399 dòng) + `tests/test_cash_dividends.py`
* `run.py cash-dividends` (lệnh con + dispatch + subparser)
* **và cả đường ĐỌC `_exdiv_from_cafef_cache`** — chỗ này mới đáng nói.

**Vì sao xoá luôn đường đọc:** giữ một bộ đọc cho kho đã đóng băng nghe có vẻ
"an toàn", nhưng nó chứng minh được là RỖNG VĨNH VIỄN. Mọi chỗ gọi
(`market_commentary:171`, `market_tab:782`) đều dùng cửa sổ **7 ngày**; kho đó
chỉ có thể chứa sự kiện từ **19/08** trở đi; từ 19/08 lệnh ghi đã 404. Giữ lại
= nuôi thêm đúng một đoạn code chết trông như sống, tức là lặp lại chính cái
bệnh vừa chữa.

`test_run.py` nay canh **`"cash-dividends" not in names`** — lệnh đã bỏ thì
lưới phải biết nó đã bỏ.

**Badge nói thêm TỔNG SỔ.** "trả 1 mã" một mình không đọc được: 1 vì tuần này
im, hay 1 vì sổ gần rỗng? Nay in kèm `(sổ có N sự kiện tất cả các kỳ)`.

## Còn treo

Con số **1 mã / 7 ngày** vẫn mỏng. Chưa biết sổ đăng ký dày tới đâu — badge
mới sẽ nói ra ở lượt `doctor` kế tiếp. Sổ mỏng thì nạp bằng
`python run.py vietstock --bulk --register` (**GHI KHO** — đừng chạy trong
lúc phát 18:00).

30 test ở `tests/test_exdiv_source.py`.

# 🔌 U35. FINHAY MCP: CÓ GÌ, DÙNG ĐƯỢC GÌ CHO APP (26/08)

68 tool. **Ràng buộc quyết định mọi thứ bên dưới: đây là MCP connector của
Claude, KHÔNG phải thư viện Python.** Phát 18:00 chạy tự động không có Claude
trong vòng lặp ⇒ **KHÔNG nối được vào pipeline**. Giá trị của Finhay là
**ĐỐI CHỨNG trong phiên**, không phải thay nguồn.

## Đã ĐO (không phải đọc mô tả)

| tool | đo được gì | 26/08 |
|---|---|---|
| `get_macro_indicator` | **27 chỉ tiêu VN**; CPI YoY tươi tới **2026-07**, sâu tới **2021-06** (2014→2021-05 trả rỗng) | ✅ tươi, nông |
| `screen_stocks` | toàn thị trường, phân trang 50; có `foreign_net_value` + `proprietary_net_value` luỹ kế theo `window` (1D…YTD), kèm `pe`/`ma50`. `updated_at` = ngay lúc gọi | ✅ sống |
| `get_financial_statement` | **trần 5 kỳ** cứng trong schema — xem U34 | ⚠️ nông |
| `get_bank_interest_rates` | 20 ngân hàng, nhưng `effective_date: 4/5/2026` — **cũ ~4 tháng** so với 26/08 | ❌ ôi |
| `list_calendar_events` | country=Vietnam trả **0 sự kiện**; United States trả **138** ⇒ tool chạy tốt, chỉ là **không phủ VN** | ❌ với VN |

## Nhóm dịch vụ (theo mô tả tool, chưa đo hết)

giá & lịch sử (stock/index/ETF/bond/crypto/forex/hàng hoá/quỹ) · sổ lệnh ·
dòng tiền ngoại + tự doanh (có `_history`) · room ngoại · thống kê lệnh chủ
động · hồ sơ & cơ cấu sở hữu DN · BCTC + 247 trường phân tích · sàng lọc ·
**16 chỉ báo kỹ thuật khung ngày, tới 5 năm** · tin tức theo topic/mã +
toàn văn · báo cáo khuyến nghị CTCK · tài khoản cá nhân (chỉ đọc).

## Dùng vào việc gì — xếp theo giá trị THẬT

1. **Đối chứng Net BS.** `screen_stocks` trả dòng tiền ngoại/tự doanh cả thị
   trường trong một lệnh. App phải gọi `order_stats()` ~1.000 mã (vòng Net BS
   135-165s). ⇒ Sau mỗi phát 18:00, Claude soi `market_overview.json` đối
   chiếu Finhay để biết số đêm qua có đúng không. **Đây là việc đáng làm nhất.**
2. **Đối chứng chỉ báo.** `get_stock_technicals` (RSI/MACD/BBANDS/ADX/…) là
   nguồn THỨ HAI để kiểm số `vnstock_screener` tự tính và chart 4 panel.
3. **Lấp vĩ mô khi NSO hỏng.** Có CPI/GDP/IIP/bán lẻ/PMI/FDI/M2/dự trữ ngoại
   hối. ⚠️ Nếu ghi vào kho thì **BẮT BUỘC có trường `source`** — số vào kho
   mà không truy được nguồn là thứ sẽ cắn về sau.
4. Tin tức theo mã + báo cáo khuyến nghị CTCK — app chưa có, bổ sung được cho
   news tab và brief.

## ĐỪNG

* Đừng nối Finhay vào `SOURCES` / pipeline (không gọi được MCP lúc 18:00).
* Đừng thay `vnstock_sbv_rates` bằng `get_bank_interest_rates` — dữ liệu ôi.
* Đừng dùng `list_calendar_events` cho lịch VN — rỗng.
* Đừng dùng `get_financial_statement` cho quá khứ — trần 5 kỳ (U34).

# 📊 U34. BÁO CÁO TÀI CHÍNH QUÁ KHỨ: TẦM PHỦ CỦA MỌI NGUỒN (26/08) — TRA BẢNG NÀY TRƯỚC

> ## 🛑 ĐÃ TRA HẾT NGÀY 26/08 — ĐỪNG DÒ LẠI
>
> User xin bảng cân đối kế toán **theo quý, năm 2015-2016** của 26 ngân hàng.
> Đã đo **5 nguồn trên máy thật**, hết 8 lượt. **KHÔNG nguồn API nào có
> 2015-2016 đúng khung ngân hàng.** User CHỐT TẠM DỪNG 26/08.
>
> | nguồn | kỳ SỚM NHẤT | khung | dùng được cho việc gì |
> |---|---|---|---|
> | **`vci`** | **2018-Q1** (→ nay, 34 quý, 83 chỉ tiêu) | ✅ ngân hàng | **Đây là nguồn TỐT NHẤT. Xin 2018+ thì dùng ngay.** |
> | `finhay` (MCP) | quý: **2025-Q2** · năm: **2021** | ✅ ngân hàng (~75 chỉ tiêu, VND nguyên) | Trần **5 kỳ** cứng trong schema, không có tham số năm. Hiện tại thôi. |
> | `cafef` | 2015-Q1 ✅ | ❌ **DOANH NGHIỆP THƯỜNG** | **KHÔNG dùng được.** Có 2015-2016 nhưng ép số ngân hàng vào khung sai. |
> | `kbs` | — | — | ❌ trả RỖNG (gọi đúng chữ ký rồi vẫn rỗng) |
> | `tcbs` | — | — | ❌ **404**, endpoint `apipubaws` đã chết |
>
> **Muốn 2015-2016 thì chỉ còn một đường:** user xuất Excel từ Wichart/FiinPro,
> Claude viết bộ đọc. ~~PDF HOSE/HNX~~ đã bác: 26 mã × 8 quý × ~60 chỉ tiêu ≈
> **12.000 con số** chép tay = bịa số có hệ thống.
>
> **Đừng đề xuất lại:** dò TCBS · dò KBS · "thử CafeF xem sao" · nối Finhay
> vào `SOURCES` (Finhay là MCP của Claude, script chạy trên máy user không
> gọi được) · chép tay từ PDF.
>
> **Công cụ đã có, đừng viết lại:** `scripts/export_bank_balance_sheets.py`
> (`--probe-all` so mọi nguồn · `--crosscheck` đo bậc đơn vị · `--items` gọi
> tên KHUNG bảng · `--dump-cafef` chẩn đoán HTML), `bank_bs_sources.py`
> (bóc HTML bằng `html.parser`), `bank_bs_shape.py`, `bank_bs_excel.py`.
> 200+ test ở `tests/test_bank_bs_sources.py` + `test_bank_balance_export.py`.
>
> ⚠️ **File `bang_can_doi_ngan_hang_2015_2016.xlsx` sinh ngày 26/08 là FILE
> HỎNG** (khung doanh nghiệp) — bảo user xoá nếu còn. Script nay đã TỪ CHỐI
> ghi file kiểu đó.

Bên dưới là nhật ký 8 lượt, giữ lại vì mỗi lượt là một kiểu sai khác nhau —
đọc khi làm việc với nguồn HTML hay báo cáo tài chính, không phải để tra tầm
phủ (tra ở bảng trên).

| nguồn | kết quả | đo lúc nào |
|---|---|---|
| `vci`   | ✅ **2018-Q1 → 2026-Q2**, 83 chỉ tiêu | 26/08, máy user |
| `kbs`   | ❌ `TypeError: balance_sheet() got an unexpected keyword` — rồi gọi theo chữ ký thật vẫn RỖNG | 26/08, máy user |
| `tcbs`  | ❌ **404** — endpoint `apipubaws` đã chết | 26/08, máy user |
| `cafef` | ⚠️ tải được (HTTP 200, thấy đủ `Quý 1-2016 → Quý 4-2016` trong HTML) nhưng **bộ bóc KHÔNG ra bảng nào** | 26/08 lượt 2, máy user |

**Lượt 8 — Finhay MCP: ĐÚNG KHUNG, nhưng TRẦN 5 KỲ.** (user thêm connector
26/08). Đã đo, không suy:

| gọi gì | trả về |
|---|---|
| `get_financial_statement(VCB, balance-sheet, quarterly, limit=5)` | **2025-Q2 → 2026-Q2** |
| `get_financial_statement(VCB, balance-sheet, annual, limit=5)` | **2021 → 2025** |
| `get_financial_analysis(VCB, quarterly)` | 12 kỳ, **2023-Q3 → 2026-Q2** — là TỈ SỐ, không phải bảng cân đối |

`limit` có `maximum: 5` ngay trong schema và **không có tham số năm/kỳ nào**,
nên 2015-2016 không có đường nào với tới. Trần cứng, không phải chuyện xin
thêm.

**NHƯNG khung thì ĐÚNG** — đây là thứ CafeF không có: `chovaykhachhang`,
`tienguicuakhachhang`, `phathanhgiaytocogia`, `duphongruirochovaykhachhang`,
`tienguitainganhangnhanuoc` — ~75 chỉ tiêu khung tổ chức tín dụng, đơn vị
VND nguyên, và `nophaitravavonchusohuu` == `tongtaisan` (cân đối khớp).

⚠️ **Finhay là MCP connector của Claude, KHÔNG phải thư viện trên máy user.**
`scripts/export_bank_balance_sheets.py` chạy độc lập nên KHÔNG nối vào được —
đừng thêm nó vào `SOURCES`. Muốn dùng thì phải là Claude gọi rồi ghi ra file.
Với 5 kỳ thì không bõ: VCI đã phủ 2018-Q1 → nay, sâu hơn nhiều.

**Lượt 7 — KẾT: CafeF KHÔNG DÙNG ĐƯỢC cho bảng cân đối NGÂN HÀNG.**

`--items VCB --source cafef` trả lời dứt điểm:

    KHUNG BẢNG: DOANH NGHIỆP THƯỜNG
    nhãn ngân hàng thấy được: — KHÔNG CÓ
    nhãn doanh nghiệp: Hàng tồn kho, Tài sản ngắn hạn, Tài sản dài hạn,
                       Các khoản phải thu ngắn hạn, Nợ ngắn hạn
    78/119 chỉ tiêu KHÔNG có số ở kỳ nào

CafeF ép số ngân hàng vào **khung doanh nghiệp thường**. Không có `Cho vay
khách hàng`, không có `Tiền gửi của khách hàng`, không có `Phát hành giấy tờ
có giá`. Đổi lại có `IV. Hàng tồn kho 8/8` cho VCB — một ngân hàng có "hàng
tồn kho" đủ 8 quý là chuyện vô nghĩa. **Không biết được chỉ tiêu ngân hàng
nào bị nhét vào ô doanh nghiệp nào**, nên số ở đây không đọc được theo tên
dòng. Sửa bộ bóc không cứu được — lỗi ở NGUỒN.

Và `--crosscheck` lộ thêm một lỗi bóc số: ô lớn nhất của CafeF ra **~1e24** ở
6/8 quý (VCI ~1e15), **cùng chữ số đầu, lệch đúng 1e9**. Chưa truy ra nguyên
nhân — và cũng không truy nữa, vì nguồn đã bỏ. Ghi lại vì `parse_vn_number` /
bộ bóc bảng còn dùng cho nguồn HTML khác sau này.

**⇒ Hai chốt chặn thêm vào code, vì cả hai lỗi đều thuộc loại "trông đúng":**
* `template_kind` + `WRONG_TEMPLATES`: **từ chối ghi file** khi khung không
  phải khung ngân hàng. Nhưng chỉ chặn khi có **BẰNG CHỨNG** (`DOANH NGHIỆP
  THƯỜNG` / `LẪN LỘN`); `KHÔNG NHẬN RA` là *chưa biết*, chặn ở đó là đẻ ra từ
  chối oan cho mọi nguồn đặt tên khác danh mục — một test cũ đỏ ngay lúc tôi
  chặn quá tay, đó là cách bắt được.
* `insane_values` + `SANE_MAX_VND = 1e18`: nêu ra ô vượt trần tỉnh táo. Ngân
  hàng lớn nhất VN cỡ 3e15 đồng; vượt 1e18 là lỗi bóc số, không phải ngoại lệ
  kế toán. **Chỉ nêu, không tự sửa cũng không tự bỏ** — tự dọn là che mất dấu
  hiệu bộ bóc hỏng.

**⇒ Đường còn lại cho 2015-2016:** user xuất Excel từ Wichart/FiinPro, Claude
viết bộ đọc. Đó là đường duy nhất vừa có 2015-2016 vừa đúng khung tổ chức tín
dụng, và số truy được về một file nguồn.

**Lượt 6 — RA FILE, và hai việc còn treo.**

`--probe-all VCB`: `cafef ✅ 2015-Q1 → 2016-Q4 · 8 quý · 119 chỉ tiêu`. File
`bang_can_doi_ngan_hang_2015_2016.xlsx` ghi ra: **26 sheet · 119 dòng giống
nhau · 8 cột quý**, 25/26 mã đủ 8 quý (NVB 4/8).

**① `--crosscheck` ra `nan` HẾT — và đó là lỗi của phép đo, không phải của
dữ liệu.** `unit_ratios` lấy nhãn khớp ĐẦU TIÊN rồi dừng; nó trúng một dòng
TIÊU ĐỀ MỤC mà CafeF để trống ⇒ `nan` toàn bộ, không kết luận được gì, trong
khi bảng có thừa số để so. Chữa hai tầng:
* thử LẦN LƯỢT mọi cặp nhãn (kể cả VI ⇄ EN) và **bỏ qua cặp nào rỗng số**;
* không cặp nào khớp thì rơi xuống `magnitude_ratios` — tỉ số |giá trị| LỚN
  NHẤT mỗi kỳ. Trong bảng cân đối, số lớn nhất luôn là tổng tài sản, nên nó
  đo đúng thứ cần đo (BẬC ĐƠN VỊ) mà không cần khớp nhãn. Bắt buộc **in ra
  đang đo bằng cách nào** — im lặng đổi cách đo là tệ hơn không đo.

**② Khung chỉ tiêu — câu hỏi NGHĨA, chưa trả lời được.** 10 hàng đầu là
`A- TÀI SẢN NGẮN HẠN` / `I. Tiền và các khoản tương đương tiền` / `Các khoản
phải thu ngắn hạn` — khung **DOANH NGHIỆP THƯỜNG**, không phải khung tổ chức
tín dụng. Thêm `--items MÃ`: in cả 119 dòng kèm số kỳ CÓ SỐ, và `template_kind`
đếm nhãn đặc trưng (`Cho vay khách hàng`, `Tiền gửi của khách hàng`… vs
`Hàng tồn kho`, `Nợ ngắn hạn`…) để gọi tên khung. **Định dạng đúng mà nghĩa
sai là ca tệ nhất ở đây** — file mở ra trông chuẩn, 26 sheet đều nhau, mà tên
dòng lại sai khung.

**Lượt 5 — ĐÃ RA: tiêu đề và số liệu ở HAI BẢNG KHÁC NHAU.**

`--dump-cafef` in ra chữ thật, và nó bác luôn giả thuyết dấu ngăn ở lượt 4:

    ô có chứa năm 20xx: 'Quý 1- 2016' · 'Quý 2- 2016' · 'Quý 3- 2016' · 'Quý 4- 2016'
    ── bảng #123  tableContent · 119 hàng · KHÔNG có tiêu đề KỲ

Tức các ô kỳ **CÓ** trong trang, **CÓ** trong một bảng, và mẫu regex khớp
chúng — nhưng chúng **không nằm trong `tableContent`**. HTML thật:

    <td class="h_t"> Quý 1- 2016</td> … <td class="h_t_tt"> Tăng trưởng</td>

nằm ở một `<table>` riêng, còn 119 hàng số nằm ở `tableContent` **không có
tiêu đề nào**. `pick_balance_table` đòi tiêu đề và dữ liệu CÙNG một bảng nên
luôn trắng tay, dù cả hai mảnh đều nằm ngay trong HTML.

⇒ Thêm đường thứ hai: `find_header_periods` quét MỌI bảng lấy hàng tiêu đề ·
`pick_data_table` lấy bảng nhiều hàng ĐỦ RỘNG nhất (có tới cột kỳ cuối) ·
ghép hai mảnh theo CHỈ SỐ CỘT. Đường cũ (tiêu đề cùng bảng) giữ nguyên vì
vẫn đúng ở trang khác.

**⚠️ ĐƠN VỊ TRANG NÓI DỐI.** Trang ghi `Đơn vị: tỷ đồng`, mà ô số là
`7.642.463.000.000` — **ĐỒNG NGUYÊN**. Câu "Đơn vị" bắt được thuộc một khung
khác trên trang. Nên `unit_note` chỉ là GHI CHÚ THAM KHẢO, sheet phải nói rõ
thế, và thang THẬT đọc ở cột `|Giá trị| lớn nhất` + `--crosscheck`. Đây đúng
là ca mà quy đổi hộ sẽ sai một bậc nghìn mà bảng vẫn nhìn hợp lý.

**⚠️ CHƯA KIỂM: khung chỉ tiêu.** 10 hàng đầu ra `A- TÀI SẢN NGẮN HẠN`,
`I. Tiền và các khoản tương đương tiền`, `II. Các khoản đầu tư tài chính` —
đó là khung DOANH NGHIỆP THƯỜNG, không phải khung tổ chức tín dụng. Mới nhìn
10/119 hàng nên chưa kết luận được, nhưng **phải mở file ra kiểm** trước khi
dùng số: nếu CafeF ép số ngân hàng vào khung doanh nghiệp thì tên dòng không
mang nghĩa kế toán ngân hàng.

**Lượt 4 — giả thuyết dấu ngăn (SAI, nhưng bản nới vẫn giữ vì vô hại):** Sau khi vá cả ba thứ ở lượt 3,
bộ bóc VẪN không nhận ra bảng nào. Điều đó thu hẹp lại rất mạnh: **không một
ô `<td>/<th>` nào trong 124 bảng khớp mẫu kỳ**, trong khi `cafef_quarters_in`
vẫn thấy 4 kỳ trong HTML thô. Nghi phạm rõ nhất là chính cái regex:

    <td><div>Quý 4</div><div>2016</div></td>   →  gộp chữ ra "Quý 4 2016"

Mẫu cũ bắt buộc `[-/]` giữa quý và năm ⇒ khớp được chuỗi `Quý 4 - 2016` nằm
rải rác đâu đó trong trang (đủ để báo "thấy 4 kỳ") mà KHÔNG khớp ô tiêu đề
thật. Đã nới: dấu ngăn TÙY CHỌN, thêm dạng năm-trước (`2016-Q4`, `2016 Q4`),
`\b` hai đầu để khỏi ăn nhầm giữa chữ.

⚠️ Đây là GIẢ THUYẾT, chưa đo — nên `cells_with_year` được thêm vào chẩn
đoán: in NGUYÊN VĂN mọi ô có chứa `20xx`. Có ô `"Quý 4 2016"` ⇒ giả thuyết
đúng. Không ô nào chứa năm ⇒ tiêu đề nằm chỗ khác hẳn, phải đổi cách lấy.
Trả lời được bằng chữ THẬT, không phải bằng một vòng đoán nữa.

**Lượt 3 — `--dump-cafef VCB` đã chỉ ra ba khiếm khuyết, và cái đầu là BUG
CỦA TÔI:**

Trang thật: `<table>=124` `<tr>=363` `<td>=1564`, bảng lớn nhất `tableContent`
119 hàng, **đơn vị `tỷ đồng`**, mà bộ bóc ra "4 hàng đầu rỗng trơn".

1. **`_TableParser` không chịu được BẢNG LỒNG BẢNG.** Bản đầu giữ `_row` /
   `_cell` ở mức TOÀN CỤC. CafeF lồng bảng khắp nơi (124 thẻ!), nên khi một
   `<table>` con đóng `</tr>` của nó thì `_row` bị đặt về None và **mọi ô còn
   lại của hàng NGOÀI rơi mất** — trong đó có hàng tiêu đề chứa các kỳ. Chữa:
   mỗi bảng giữ hàng đang mở của RIÊNG nó, ô xếp theo ngăn xếp.
2. **Tiêu đề không nằm ở `rows[:6]`** — `tableContent` mở đầu bằng 4 hàng
   chèn rỗng. `header_row_index` giờ quét TOÀN BỘ bảng, lấy hàng đầu tiên có
   ≥2 ô là kỳ (hàng dữ liệu không chứa chuỗi kỳ nên không nhận nhầm).
3. **Cột 0 không phải tên chỉ tiêu** — đó là cột nút bấm/thụt dòng.
   `label_col_index` chọn cột nhiều CHỮ nhất bên trái cột kỳ đầu tiên.

**Và một vết trong chính phần chẩn đoán:** `dump_cafef` dò chỗ đứng của chuỗi
kỳ bằng chuỗi ghép tay `f"Quý {q}-{y}"`, trong khi trang viết `Quý 4 - 2016`
(có khoảng trắng) — regex nhận ra nhưng chuỗi ghép tay thì không, nên phần
chẩn đoán QUAN TRỌNG NHẤT im lặng bỏ qua. **Đã thấy bằng regex nào thì phải
định vị bằng đúng regex đó** (`quarter_contexts`).

**Lượt 2 (sau khi vá):** `kbs` hết `TypeError` — chữ ký đã đọc đúng — nhưng
vẫn RỖNG, nên KBS chết thật, không phải chết vì tôi gọi sai. Còn `cafef`:
`cafef_quarters_in` THẤY đủ 4 kỳ trong HTML mà `pick_balance_table` không tìm
ra bảng nào ⇒ **chuỗi kỳ nằm NGOÀI ô `<td>/<th>`**. Hai khả năng, chữa khác
hẳn nhau: tiêu đề nằm trong `<div>` (sửa bộ bóc) hay trang dựng bảng bằng JS
(phải tìm endpoint dữ liệu). `--dump-cafef` được viết lại để phân biệt: đếm
thẻ THÔ bằng regex rồi so với số bảng bộ bóc ra, in ngữ cảnh quanh chuỗi kỳ,
và liệt kê URL nghi là đường lấy dữ liệu (`/ajax/`, `.ashx`, `/api/`, `json`).
`verdict_line` suy CA HỎNG từ chính các con số đó, không từ trí nhớ.

**⇒ CafeF là nguồn DUY NHẤT có 2015-2016.** Một trang = 4 quý của MỘT năm
(`/du-lieu/bao-cao-tai-chinh/<mã>/bsheet/<năm>/4/0/0/…`), nên 2015-2016 là
**hai lượt tải**, không phải tám. `s.cafef.vn/bao-cao-tai-chinh/…` chuyển
hướng sang đường trên.

## Ba cái bẫy đã né được (viết ra vì cả ba đều ghi ra file trông như thật)

1. **`limit` mặc định = 4 kỳ.** `vci…Finance._get_financial_report` có
   `effective_limit = limit if limit is not None else 4`, mà `balance_sheet()`
   công khai KHÔNG nhận `limit`. Đi đường thường ⇒ 4 quý gần nhất, file vẫn ghi
   bình thường. Phải gọi thẳng `_get_financial_report(..., limit=N)`.
2. **`dropna=True` bỏ CHỈ TIÊU toàn 0** (`df.loc[:, (df != 0).any(axis=0)]`),
   mỗi ngân hàng bỏ một bộ khác nhau — đúng thứ phá yêu cầu "format đồng nhất".
3. **Dạng frame ngược với giả định đầu tiên của tôi**: hàng = CHỈ TIÊU, cột =
   KỲ (`item | item_en | item_id | 2018-Q1 | … | 2026-Q2`). Tôi đã đoán
   hàng=kỳ theo kiểu `yearReport`/`lengthReport` — sai. `--probe` bắt được
   trước khi ghi file.

## Điều PHẢI nhớ về máy chạy Claude: EGRESS BỊ CHẶN

Container của Claude **không ra được mọi host tài chính VN** — agent proxy trả
`403` cho `CONNECT`: `kbsec.com.vn`, `apipubaws.tcbs.com.vn`, cả
`hq.vnstocks.com` (nên `vnstock` chạy ở đây luôn ở tier `guest`). Hệ quả:

* **Mọi thứ chạm mạng chỉ kiểm được TRÊN MÁY USER.** Đừng bao giờ viết "đã
  kiểm nguồn X" nếu chỉ chạy trong container — đó là vết U26 lặp lại (trình
  bày suy luận bằng giọng của phép đo).
* Vì thế `tcbs_to_frame` viết theo hướng **không lọc theo danh mục**: trường
  lạ vẫn ra bảng với tên gốc (`_camel_to_words`). Danh mục `TCBS_VI` chỉ để
  DỊCH tên, không để chọn dòng — danh mục chép theo trí nhớ mà đem lọc thì
  trường thiếu = số biến mất im lặng.
* Và **đơn vị TCBS chưa xác nhận** (TCBS hay trả tỉ VND, VCI trả triệu VND).
  Không nhân chia gì hết: `--crosscheck` lấy dòng TỔNG TÀI SẢN ở các quý CẢ
  HAI nguồn cùng có rồi in TỈ SỐ. Tỉ số phẳng (max/min < 1,01) ⇒ chênh đúng
  một bậc đơn vị, ghép được. Tỉ số lởm chởm ⇒ **hai bảng không cùng nói về
  một chỉ tiêu**, đừng ghép.

## Ba lệnh, theo thứ tự

    python scripts\export_bank_balance_sheets.py --probe-all VCB    # nguồn nào với tới 2015?
    python scripts\export_bank_balance_sheets.py --crosscheck VCB   # đơn vị có khớp không? (năm 2018-2019)
    python scripts\export_bank_balance_sheets.py --from 2015 --to 2016 --source cafef

`--probe-all` so MỌI nguồn trên cùng một mã trong một lệnh, cộng thêm một
phép thăm dò CafeF (chỉ hỏi "trang có chứa quý mình xin không", CHƯA bóc số —
bóc số chỉ viết sau khi nhìn cấu trúc bảng thật). Exit 0 = có nguồn với tới,
exit 2 = không.

## Hai cái bẫy nữa lộ ra từ lần đo 26/08

**① Chữ ký `vnstock` KHÁC NHAU giữa các máy.** `kbs…balance_sheet` ở
container CÓ `display_mode`, ở 4.0.4 trên máy user thì KHÔNG ⇒ truyền cứng là
`TypeError` trên đúng cái máy duy nhất chạy được mạng. Chữa bằng
`_call_with_supported_kwargs` — đọc `inspect.signature` rồi mới gọi. Bài học
rộng hơn: **container và máy user không cùng một thư viện**, đừng suy chữ ký
ở đây ra chữ ký ở kia.

**② "Không tải được" ≠ "tải được mà không bóc ra bảng".** Bản đầu của
`fetch_cafef_years` nuốt cả hai thành "rỗng", rồi `--probe-all` gợi ý "hỏng ở
bước bóc bảng" ngay cả khi proxy chặn ở bước TẢI. Hai kiểu hỏng cần hai cách
chữa khác nhau ⇒ tách hẳn: tải hỏng ném `CafefFetchError` kèm mã HTTP, bóc
hỏng mới trả frame rỗng.

## Bộ bóc CafeF — viết mà CHƯA NHÌN TRANG THẬT

Vì egress bị chặn. Nên nó được viết theo hướng chịu sai:

* Nhận diện bảng theo **HÌNH DẠNG** (có ≥2 ô tiêu đề là kỳ, ≥10 dòng), không
  theo `id`/`class` — tên lớp CSS của CafeF đổi lúc nào không ai báo.
* Dùng `html.parser` của thư viện chuẩn. `lxml`/`bs4`/`html5lib` đều KHÔNG có
  trong `requirements.txt`, không được phép dựa vào.
* Không nhận ra ⇒ frame RỖNG, và `--dump-cafef` in ra cấu trúc THẬT (số bảng,
  4 hàng đầu mỗi bảng, bảng nào đang được chọn) + lưu HTML thô vào
  `_cafef_dump/`. Trật thì sửa theo cấu trúc, **đừng đoán tiếp**.
* `parse_vn_number`: `1,234,567` lẫn `1.234.567`, âm trong ngoặc `(1,234)`.
  Phân biệt dấu NGHÌN với dấu THẬP PHÂN bằng chỗ đứng — dấu cuối cùng mà theo
  sau không phải đúng 3 chữ số thì đó là dấu thập phân. Ô `-` hay trống ⇒
  **None, không phải 0**.
* Đơn vị trang ghi (`"Đơn vị: Triệu VNĐ"`) được lấy NGUYÊN VĂN vào
  `df.attrs["unit_note"]` rồi in lên sheet `0_TẦM PHỦ`. **Không quy đổi.**

## Nếu CafeF cũng trượt

1. **User xuất Excel từ Wichart/FiinPro, Claude viết bộ đọc.** Số truy được
   về một file nguồn — sạch nhất.
2. ~~PDF HOSE/HNX~~ — 26 ngân hàng × 8 quý × ~60 chỉ tiêu ≈ **12.000 con
   số** chép tay. **Không làm.** Chép tay ở quy mô đó là bịa số có hệ thống,
   mà bảng bịa thì trông y hệt bảng thật.

# 🚀 U33. NET BS: TUẦN TỰ CÓ SLEEP → SONG SONG CÓ NHỊP (26/08)

Ứng viên lớn còn lại của bước `screener` (1.318s). Vòng lấy Net Buy-Sell ở
`vnstock_runner.compute_market_overview`:

```python
for tk in _top_tickers:              # ~1.000 mã, KHÔNG hề cắt
    os_df = Trading(symbol=tk).order_stats()
    ...
    except Exception: pass
    _nb_time.sleep(0.15)
```

## Ba khiếm khuyết, không phải một

**① Sàn 150 giây chỉ để NGỦ.** 1.000 × 0,15s. Cộng round-trip mạng cũng nối
tiếp nhau ⇒ vài trăm giây nữa. Trong khi hạn mức Sponsor là **600 req/phút =
10 req/s** — đường tuần tự dùng **chưa tới 1/10 quota** mà vẫn chậm. Nhịp cũ
áp cho MỖI lượt và cộng dồn; đúng ra phải áp cho TOÀN BỘ.

**② `except Exception: pass` — mất data IM LẶNG.** Mã bị hạn mức chặn biến
mất khỏi `nb_data` không dấu vết. Không ai biết `Net BS 1T` của một ngành
thiếu mấy mã.

**③ Không có gì đo được.** Dòng log chỉ in tổng giây — không tốc độ, không số
lỗi. Nên "vòng này chậm" mãi là cảm giác.

## Vá

* **Pool worker + MỘT bộ nhịp dùng chung** (`_RatePacer`). Khoá chỉ giữ lúc
  tính mốc "lượt kế tiếp"; `sleep` nằm **ngoài** khoá nên worker không chặn
  nhau — chúng xếp hàng theo thời điểm, còn round-trip thì **chồng lên nhau**.
  Tổng tốc độ bị chặn ở `_NB_RATE_PER_SEC = 8.0` **bất kể bao nhiêu worker**
  (đo: 20 lượt @20/s qua 4 luồng = 0,95s, đúng bằng một luồng).
* 8 dưới 10 có chủ đích — chừa biên, và bước khác của phát cũng gọi mạng.
* `call_with_rate_limit_retry(retries=2)` thay cho nuốt trần: 429 nay được
  chờ rồi thử lại chứ không làm bốc hơi một mã.
* Đếm `_nb_fail` và in ra: `Net Buy-Sell: 987/1002 (128s · 7.8 req/s · 8
  luồng · 15 LỖI) → cached`. Nay chẩn đoán được.
* Kill-switch `VNSTOCK_NETBS_WORKERS=1` là quay về đúng hành vi tuần tự.

Kỳ vọng: từ ~650s (1.000 × (0,15 + rtt 0,5)) xuống **~125s** — sàn nay là HẠN
MỨC chứ không phải độ trễ nối tiếp. ~5×.

## ⚠️ CỐ Ý KHÔNG đụng TTL cache

TTL 12h < nhịp phát 24h nên cache **luôn nguội** ở đường đêm. Nhìn thì như
một chỗ đáng "tối ưu" — **không phải**. `Net BS 1T` là tổng **5 phiên**; xài
lại cache hôm qua là thiếu mất phiên hôm nay, tức một **lỗi số liệu im lặng**
trong mục Dòng Tiền của brief. Cache chỉ để cứu lượt chạy lại trong cùng buổi
tối, và nó làm đúng việc đó.

Có test canh hằng số `_NB_CACHE_TTL_H = 12` kèm lý do, để lần sau không ai
"tối ưu" nó thành số sai.

## Lưới mới
`tests/test_netbs_parallel.py` (14) — trong đó test sống chết là **tổng tốc độ
không cộng dồn theo số luồng**: vượt quota là bị nhà cung cấp chặn, mất nhiều
hơn được.
Suite: **2.615 passed** (fast 2.121).

---


# ✅ U32. ĐỐI CHỨNG fix-units TRÊN KHO THẬT — và nó lộ ra một bug CÓ SẴN (26/08)

Hai lượt `run.py fix-units --dry-run --json` trên desktop, bật/tắt phép lọc:

| | `scanned_bars` | `skipped_by_footer` | `fix_count` | `errors` |
|---|---|---|---|---|
| Lọc **BẬT** | **4.460** | **3.081** / 3.125 | 0 | — |
| Lọc **TẮT** | **5.018.868** | 0 | 0 | **1 (HFB)** |

## ✅ Tương đương đã được xác nhận trên KHO THẬT
`fix_count` bằng nhau (0 = 0) — điều duy nhất phải khớp.

## 📉 Mức lợi lớn hơn dự tính rất nhiều
**Giải nén 4.460 bar thay vì 5.018.868 — ít hơn 1.125×**, và bỏ qua
**98,6% số mã** (3.081/3.125). Chỉ 44 mã thật sự cần đọc. Con số đó nói rằng
kho gần như KHÔNG còn bar raw-VND nào — bước này đã thành một phép kiểm tra
gần như thuần footer.

## 🐛 Và lượt TẮT lộ ra một bug CÓ SẴN, không phải do bản vá

```
"errors": [{"ticker": "HFB",
            "message": "Cannot compare Timestamp with datetime.date..."}]
```

Kho có mã lưu `time` kiểu **date32** ở năm này và **timestamp** ở năm kia.
`pd.concat` hai kiểu đó ra cột `object`, rồi `sort_values("time")` ném lỗi.
`scan()` bắt lỗi và ghi vào `report.errors` — nghĩa là **mã đó im lặng không
được soi**.

Tái dựng cho thấy đây KHÔNG chỉ là ồn ào: dựng HFB với một bar `close =
9.999` (đúng loại raw-VND cần sửa), đường cũ trả **`fixes: 0`** — lỗi ĂN MẤT
một bản sửa thật.

**Vì sao trước đây không ai thấy:** với phép lọc BẬT, HFB thật (max close ≤
ngưỡng) bị bỏ qua nên không bao giờ chạm vào đoạn code hỏng. Phép lọc **che**
bug. Che một bug bỏ sót bar sai đơn vị thì vẫn là bỏ sót ⇒ phải vá gốc.

**Vá:** chuẩn hoá `time` sang datetime TRƯỚC khi sắp xếp, `errors="coerce"` +
`dropna` để hàng có dấu thời gian rác bị bỏ chứ không làm chết cả mã. Dùng
`format="mixed"` khi cột là `object` để pandas khỏi in `UserWarning "Could not
infer format"` vào log đêm.

## Bài học quy trình
Cái kill-switch `VNSTOCK_FIXUNITS_FOOTER_PRUNE` thêm vào chỉ để user **đối
chứng thay vì tin lời tôi** — và chính nó tìm ra bug. Nếu tôi chỉ nói "tôi đã
chứng minh tương đương, có 16 test" thì lượt TẮT không bao giờ chạy, và HFB
vẫn im lặng bị bỏ sót. **Đường đối chứng không phải thủ tục thừa; nó là một
phép đo riêng.**

Suite: **2.601 passed** (fast 2.107).

---


# 🚀 U31. BA BẢN VÁ 26/08 — screener quét 14 lần, fix-units đọc thừa, watchlist có mốc THẬT

Ba việc user giao cùng lúc. Bốn luồng đọc code song song trước khi sửa — và
recon **lật một kế hoạch của tôi**, đó mới là phần đáng ghi.

## ① Screener 1.318s: 14 lượt quét kho **y hệt nhau**

`run_all_presets` lặp preset ở NGOÀI, `scan()` lặp mã ở TRONG, và filter của
preset chỉ được áp **SAU** khi đã đọc parquet + tính trọn bộ chỉ báo:

```python
df  = self._load_ticker(ticker)      # 2 file parquet
ind = _calc_indicators(df)           # RSI/EMA/MACD/BB/52w + nến + CRSI + W + HA
if filter_fn: ...                    # ← preset chỉ khác NHAU ở ĐÂY
```

`_calc_indicators` là hàm THUẦN của `df`, `df` là hàm thuần của
`(ticker, lookback_days)`. Không gì phụ thuộc preset. Nên **13/14 lượt là lặp
lại nguyên xi**.

⚠️ **`PRESETS` có 14 mục, không phải 9** — CLAUDE.md ghi sai từ lâu, và con số
đó chính là HỆ SỐ NHÂN của toàn bộ chi phí bước này. Đã sửa.

Đo bằng kho tổng hợp (300 mã × 3 năm × ~250 bar): **17-19 ms/mã/lượt**, chia
gần đều I/O (8,5 ms) và pandas (8,8 ms), **đúng 2 lần mở parquet mỗi mã mỗi
lượt**. Suy ra ~1.100 mã × 2 file × 14 preset ≈ **31.000 lần mở parquet mỗi
đêm** chỉ cho bước 1.

**Vá:** `_indicators_for(ticker, min_rows)` — nhớ `(len(df), ind)` trên
instance. 14 lượt → 1. Ba điểm phải cẩn thận, đều có test canh:
* trả **bản SAO** — chỗ gọi gắn `ticker`/`industry` vào dict, sửa thẳng cache
  là preset sau nhận rác preset trước;
* `min_rows` **đổi theo preset** nên xét lại mỗi lượt, không nướng vào cache;
* mã rỗng / chỉ báo rỗng cũng phải nhớ là MISS, không thì vẫn đọc lại 14 lần.

Cache sống trên MỘT instance trong tiến trình ngắn của `vnstock_runner.py`, và
không bước nào ghi `prices/` lúc đó ⇒ không thể ôi.

*(Chưa vá, ghi lại: vòng lặp Net BS ở `vnstock_runner.py:466-493` gọi
`Trading(symbol=tk).order_stats()` **tuần tự cho MỌI mã** — biến tên
`_top_tickers` nhưng không hề cắt — với `sleep(0.15)`, tức sàn 135-165s trước
cả thời gian mạng; cache TTL 12h < nhịp 24h nên **nguội mỗi đêm**. Đây là ứng
viên co-equal, không tách được khỏi 1.318s nếu chỉ đọc code.)*

## ② fix-units 316s: lọc bằng THỐNG KÊ FOOTER, không thêm state nào

Bước này quét ~**3.125** thư mục mã (KHÔNG lọc `_is_stock` như updater chỉ
~1.600) và giải nén **cả 6 cột** trong khi chỉ dùng `time` + `close`.

Chìa khoá: `_detect_in_ticker` chỉ có thể sinh fix khi tồn tại bar
`close > RAW_VND_THRESHOLD`. Parquet ghi sẵn min/max mỗi cột trong **footer**,
và `pq.read_metadata` đọc footer mà **không giải nén data page**. Nên
`max(close) ≤ ngưỡng ⇒ bỏ qua` là phép lọc **tương đương chứng minh được**,
không phải phỏng đoán.

Bất biến sống chết: **nghi ngờ thì ĐỌC**. Thiếu cột `close`, thiếu statistics,
footer hỏng, ném lỗi ⇒ đọc như cũ. Bỏ sót một bar sai đơn vị là ghi số sai vào
kho giá — đắt hơn nhiều so với đọc thừa vài mã. Có test cho cả 5 nhánh nghi ngờ.

Thêm `skipped_by_footer` vào `FixReport` + `to_dict()`: trước đây **không gì
ghi lại** bước này tốn công vào đâu, nên con số 98s → 302s → 316s không ai
giải thích được. (Và git cũng không giải thích: commit duy nhất đụng
`vnstock_fix_units.py` trong khoảng đó chỉ đổi đường GHI, mà đường ghi không
chạy khi không có fix. Bar tăng cũng không: 3 phiên giữa 98s và 302s.)

## ③ Watchlist: mốc THẬT — và tôi suýt dùng nhầm hàm

Tôi định nối `vnstock_strategy._ticker_pivots` (chính tôi đã ghi tên nó vào
sổ). Recon cho thấy **đó là hàm sai**:
* nó trả về một **CHUỖI tiếng Việt đã format**, không phải số;
* nó `round(v, 0)` trên đơn vị **nghìn VND** — với GAS ở 83,5 thì bước làm
  tròn là **1,2%**, nhiễu còn lớn hơn khoảng cách tới mốc;
* nó **không có sàn** khoảng cách / khoảng hở / tầm với nào — R1 chỉ là đỉnh
  bar gần nhất trên giá, có thể cách 0,1%.

Bản đúng nằm ngay trong `vnstock_brief.py`: **`_select_sr_levels`** — thuần,
bất biến theo đơn vị (mọi phép so là TỈ SỐ), và đã có đủ ba sàn
`_SR_MIN_DIST_PCT` / `_SR_MIN_GAP_PCT` / `_SR_MAX_MOVE_PCT` sinh ra từ đúng
những ca nhiễu mà đường CHỈ SỐ đã dính (S1 cách close 0,03%; R1→R2 cách 0,05%;
S2 cách 16% được chào làm mục tiêu).

**Vá:** `ticker_sr_levels(highs, lows, last)` — hàm thuần, cùng cửa sổ với
đường chỉ số (60 bar **bỏ 2 bar cuối**, vì 2 bar cuối còn dính giá hiện tại
nên chưa phải đỉnh/đáy đã hình thành). I/O nằm ở `_attach_ticker_sr`, gọi từ
**`collect_context`** — KHÔNG phải `build_prompt` (test gọi nó với ctx 2 khoá,
không có kho) và KHÔNG phải tầng guard (ctx watchlist không mang OHLC nên
guard không thể tự tính). Rẻ: `_select_liquid_movers` trả tối đa 5+5 mã.

Ba dạng nhãn, đều có test:
```
⭐ [hỗ trợ 81,200 / kháng cự 87,400 — pivot 60 phiên]
⭐ [kháng cự 13,900 — pivot 60 phiên, CHƯA có mốc còn lại trong tầm]
⭐ [dải ±3% quanh giá: 41,350 – 43,950 — mốc THAM CHIẾU …]
```
Vế thiếu thì **nói là thiếu**, tuyệt đối không bịa. Template dạy model đọc kỹ
dạng nào rồi hẵng viết.

Guard `_reference_bands` nay **bỏ qua** mã đã có pivot thật: nạp dải ±3% vào
đó chỉ tạo nguy cơ ghi đè nhầm một mốc THẬT tình cờ trùng số.

## Lưới mới
`test_screener_ind_cache.py` (9) · `test_fix_units_footer_prune.py` (13) ·
`test_watchlist_real_pivots.py` (19). Cả ba vào `--fast`.
Suite: **2.594 passed** (fast 2.100).

**Chưa đo được trên máy thật.** Kỳ vọng: screener 1.318s → vài trăm giây (trừ
phần Net BS chưa đụng), fix-units 316s → nhỏ hơn hẳn. Phát kế tiếp là phép đo.

---


# 🔧 U30. DÒNG ĐO KHÔNG MANG NGÀY — phép đo phải chờ thêm một đêm (25/08)

User dán lại 4 dòng `⏱` để chốt việc #1 (đo sạch bản vá cửa sổ). Nhưng đó
đúng là **4 dòng CŨ** — chưa có phát mới. Không ai phát hiện ngay được, kể cả
Claude, vì:

```
[run.py] ⏱ TỔNG 69.0 phút (14 bước) — screener 1,318s · sync 1,145s · …
[sync]   ⏱ CHẶNG 19.1 phút — auto-heal 504s · fix-units 316s · …
```

**Không dòng nào mang ngày.** Mà `run_daily.log` thì XOAY VÒNG và giữ nhiều
đêm trong cùng một file (`_rotate_run_log`, 3 thế hệ). Nên `Select-Object
-Last 4` trả về một hỗn hợp: TỔNG của 24/08, CHẶNG của lượt chạy TAY 25/08,
CHẶNG + TỔNG của phát 25/08 — và người đọc phải tự nhớ thứ tự để biết dòng
nào là dòng nào.

Hệ quả cụ thể: một phép đo hiệu năng phải hoãn thêm một đêm **chỉ vì thiếu 16
ký tự**. Đây là họ bug "dữ liệu đúng nhưng không truy được nguồn gốc" — cùng
loại với U20 (bộ chấm live mode không in cửa sổ đo nên không chẩn đoán được
từ output dán lại).

**Vá:** `_stamp()` (hàm thuần, nhận `now` để test cắm giờ cố định) và cả hai
dòng nay in
`⏱ TỔNG [2026-08-26 18:05] 69.0 phút (14 bước) — …`.
Dấu đặt GIỮA nhãn và con số nên `grep '⏱ TỔNG'` vẫn bắt được y như cũ, và mắt
vẫn đọc số ngay sau dấu. 4 test canh: có dấu · đúng vị trí · dòng CHẶNG cũng
được đóng dấu · format số EN không đổi.

Suite: **2.553 passed** (fast 2.059).

---

# ⚠️ U29. PHÁT 25/08: 69,0′ — SỐ ĐẸP NHƯNG **KHÔNG SẠCH** (đừng ghi công vội)

```
⏱ CHẶNG 19.1 phút — auto-heal 504s · fix-units 316s · updater 308s · rollup 15s
⏱ TỔNG  69.0 phút (14 bước) — screener 1,318s · sync 1,145s · train 752s ·
         audit 286s · validate 249s · brief 206s · test 85s · news 46s · …
```

## ✅ Kết quả thô: đệm dưới trần task từ 13,7′ lên **111′**

| | TỔNG | updater |
|---|---|---|
| 24/08 (guard nới 30 ngày) | 166,3′ | 5.659s |
| 25/08 tay, guard TẮT | — | 2.224s |
| 25/08 phát (guard + `window_start`) | **69,0′** | **308s** |

Trần task `PT3H` nay chỉ dùng 38%. Rủi ro "mất brief vì chạm trần" — mục lo
lớn nhất của U27 ④ — **đã hết**.

## ⚠️ NHƯNG đây KHÔNG phải phép đo sạch của `window_start`

Số học không cho phép ghi công: cửa sổ mới ~11 ngày, cửa sổ khi **TẮT** guard
là ~1-3 ngày. Bản vá lẽ ra phải **chậm hơn** lượt tắt guard, chứ không phải
**nhanh hơn 7×** (308s vs 2.224s). Một thay đổi 30→11 ngày cho tối đa ~2,7×,
không thể ra 18×.

Nên còn biến số khác chưa nhận diện được. Nghi phạm rõ nhất: **cùng ngày đã
chạy tay `run.py sync` trước đó**, nên phát 18:00 gặp một cái kho đã ấm theo
cách nào đó. (Lưu ý: KHÔNG phải "mã đã up-to-date nên bỏ qua" —
`vnstock_updater` cố ý refetch cả khi `last_date == today` để thay bar dở
dang; chỉ bar ở TƯƠNG LAI mới cho `up_to_date`.)

**Phép đo SẠCH là phát kế tiếp trong một ngày KHÔNG chạy tay gì trước đó.**
Chưa có nó thì `window_start` vẫn là "đúng về lý, chưa đo được về lượng".

Ghi lại đây vì đúng cái bẫy repo đã dính nhiều lần: **một con số đẹp trong
điều kiện không sạch, đọc thành bằng chứng.**

## ✅ auto-heal: hàng đợi CUỐI CÙNG cũng rút

```
24/08: scanned 1956 · archived 1101 · bumped 855  → còn 1.704
25/08: scanned 1120 · archived 73   · bumped 1047 → còn 1.631
25/08: scanned 1631 · archived 853  · bumped 778  → còn 778
```

`archived` bật lên 853 vì đám bị bump các đêm trước đã chạm
`MAX_RETRIES_DEFAULT = 3`. Quét hết 1.631 mục, không còn mục tồn. Thêm ~2 đêm
là sạch hàng đợi.

**Nhưng `healed` vẫn = 0** — nay là **0 / 4.707 lượt refetch qua ba đêm**. Kết
luận không đổi: đường refetch KHÔNG chữa được thứ trong hàng đợi này, nó chỉ
đang lưu trữ dần. Badge "Hiệu suất auto-heal" (U28) sẽ nói đúng chuyện đó.

## 🔎 Kẻ ăn thời gian MỚI: `screener` 1.318s = 22′

Nay lớn hơn CẢ `sync` (1.145s). Trước đây bị `updater` che khuất. Chưa soi bao
giờ — ứng viên tiếp theo nếu cần lấy thêm thời gian, nhưng **không gấp** khi
đệm đang là 111′.

`fix-units` 316s cũng đáng soi: nó quét TOÀN KHO mỗi đêm và đã tăng đều
(98s → 302s → 316s).

---


# ✅ U28. PHÉP THỬ CHỐT: CỬA GÁC CỦA TÔI TIÊU 57 PHÚT MỖI ĐÊM (25/08)

```
VNSTOCK_BASIS_GUARD=0
[sync] ⏱ CHẶNG 52.3 phút — updater 2,224s · auto-heal 618s · fix-units 286s · rollup 7s
```

Đối chiếu phát 24/08 (guard BẬT): `updater 5,659s`.

| | updater | chênh |
|---|---|---|
| Guard BẬT (nới thẳng 30 ngày) | 5.659s | |
| Guard TẮT (cửa sổ gốc 1-3 ngày) | 2.224s | **−3.435s = −57 phút** |

**Giả thuyết U27 ③ ĐÚNG.** Cửa gác lệch cơ sở V1 của tôi tiêu **57 phút mỗi
đêm** — bằng 34% cả phát 166,3′. Không phải mạng chậm, không phải số mã tăng:
đúng cửa sổ fetch bị nới 16×.

⚠️ **Nhiễu còn lại, ghi cho trung thực:** hai lượt đo ở hai thời điểm khác
nhau (phát 18:00 vs chạy tay), mạng có thể khác. Nhưng SỐ LƯỢT gọi mạng là như
nhau (~1.600 mã, đều fetch `[last_date, today]`), chỉ độ RỘNG cửa sổ đổi — tức
đúng biến đang thử. Cỡ hiệu ứng 2,5× quá lớn để quy cho nhiễu.

**Bản vá `window_start()` (U27) chưa được đo trên máy thật.** Kỳ vọng nằm giữa
2.224s và 5.659s, lệch hẳn về phía thấp (cửa sổ ~11 ngày thay vì 30 với mã
thanh khoản cao). Đo thật ở phát kế tiếp.

## Và một con số nữa nói dứt khoát: auto-heal KHÔNG chữa được gì

```
24/08: scanned=1956 healed=0 retry_bumped=855  archived=1101
25/08: scanned=1120 healed=0 retry_bumped=1047 archived=73
```

**0 bar lành / 3.076 lượt refetch**, hai đêm liền, mỗi đêm tiêu trọn ~620s.
Đối chiếu 19/08: 35/3.844 = 0,9%. Hàng đợi còn lại gần như KHÔNG lành được —
nguồn trả về đúng bar hỏng đó.

Hàng đợi khớp sổ sách: 24/08 để lại 855+849 = 1.704; 25/08 quét 1.120, còn
584 ⇒ 1.120+584 = 1.704 ✓. Không có mục mới vào, chỉ xoay vòng. `archived`
tụt từ 1.101 xuống 73 vì đám "vắng cấu trúc" đã bị dọn hết đêm trước; phần còn
lại phải chờ đủ `MAX_RETRIES_DEFAULT = 3` lượt bump mới được lưu trữ.

**Bài học quy trình (quan trọng hơn con số):** hai đêm liền tiêu 620s để đạt
số 0, mà phải chờ user dán log về Claude mới biết. Con số đó phải TỰ nổi lên.

**Vá:** `record_heal_run()` ghi mỗi lượt vào `_meta/autoheal_runs.json` (trần
30 lượt) + badge doctor **"Hiệu suất auto-heal"**:
* `< HEAL_MIN_ATTEMPTS (200)` lượt ⇒ **ok kèm n=…**, không kêu;
* có lành ⇒ ok;
* đủ mẫu mà `healed = 0` ⇒ **warn**, kèm đúng cần gạt:
  `VNSTOCK_AUTOHEAL_BUDGET_S=120` (hoặc 0 để tắt hẳn).

CỐ Ý không tự hạ trần trong code: đó là đánh đổi của user (dừng chữa hẳn vs
tiêu 10 phút mỗi đêm), và `run.py sync` vẫn `exit 1` khi có mã lỗi nên việc
này không im lặng.

## Dự phóng thời gian phát
166,3′ − 57′ ≈ **109′** ⇒ đệm dưới trần 3 giờ đi từ 13,7′ lên ~71′. Nếu
`window_start` chỉ lấy lại được một nửa thì vẫn ~138′, đệm ~42′ — vẫn thoát
khỏi vùng nguy hiểm.

## Lưới mới
`tests/test_autoheal_yield.py` (11), đã vào `--fast`. Suite: **2.550 passed**
(fast 2.059).

---


# 🔴 U27. SỐ THẬT CỦA PHÁT 24/08 — CHẨN ĐOÁN CŨ ĐÚNG MỘT NỬA, VÀ TÔI LÀM CHẬM UPDATER

Bốn dòng số user dán về (phát 18:00 T2 24/08):

```
[sync] ⏱ auto-heal: 629.7s
[sync] auto-heal: scanned=1956 healed=0 retry_bumped=855 archived=1101
[sync] ⏳ auto-heal dừng theo trần thời gian — còn 849 mục trong hàng đợi
[sync] ⏱ CHẶNG 110.0 phút — updater 5,659s · auto-heal 630s · fix-units 302s · rollup 12s
[run.py] ⏱ TỔNG 166.3 phút (14 bước) — sync 6,602s · screener 1,393s · train 672s ·
         audit 421s · validate 364s · brief 190s · news 189s · test 95s · …
```

## ① ✅ Trần auto-heal CHẠY ĐÚNG — 2.157s → 630s

Chặn trần 600s có tác dụng: từ **35,9′ xuống 10,5′**. Dòng "dừng theo trần
thời gian" xác nhận nó bị cắt đúng chỗ. Chẩn đoán "auto-heal là kẻ ăn thời
gian" **đúng về triệu chứng**.

## ② ❌ NHƯNG healed = 0 — 630 giây gọi mạng, chữa được KHÔNG MÃ NÀO

`scanned=1956` = `archived=1101` + `retry_bumped=855`. **Không một mục nào
lành.** 1.101 mục bị dọn là loại "vắng cấu trúc" (bản vá 19/08 — dọn ngay thay
vì thử lại 3 đêm), phần đó tốt. Nhưng 855 mục được đẩy sang đêm sau, cộng 849
mục chưa kịp quét ⇒ **hàng đợi đêm mai ≈ 1.704**.

Tức auto-heal đang chạy **cối xay**: mỗi đêm tiêu trọn ngân sách 600s để đạt
số 0. Trần chỉ chặn thiệt hại, KHÔNG chữa gốc. Gốc là: đám còn lại refetch bao
nhiêu lần cũng không lành — nguồn trả về đúng bar hỏng đó.

**Việc mở:** hoặc hạ trần mạnh (120s) cho tới khi hiểu vì sao 855 mục kia
không lành, hoặc soi một mẫu trong `retry_bumped` xem chúng vướng hợp đồng nào.

## ③ ❌ `updater` 5.659s = 57% CẢ PHÁT — và nghi phạm số 1 là bản vá của tôi

Đây mới là kẻ ăn thời gian THẬT SỰ, lớn gấp 9 lần auto-heal.

Đối chiếu: 18/08 sync = 3.609s với auto-heal 2.156s + fix-units 98s + rollup
12s ⇒ updater ≈ **1.343s**. Nay **5.659s** — gấp **4,2×**.

Giữa hai mốc đó, thứ duy nhất đụng đường fetch của updater là **cửa gác lệch
cơ sở (V1, 19/08) — của tôi**:

```python
_win_from = bg.fetch_start(fetch_from)      # lùi THẲNG 30 ngày
```

`fetch_from = last_date`, nên lượt cập nhật thường chỉ cần **1-3 ngày**. Nới
thành ~32 ngày là cửa sổ fetch phình **~16×**, nhân với ~1.600 mã, mỗi đêm.

⚠️ **Chưa CHỨNG MINH được** — mới là suy luận từ hai mốc đo cách nhau 6 ngày,
và tôi không đo được trên máy thật. Nhưng nó là thay đổi duy nhất đúng chỗ,
đúng chiều, đúng cỡ.

**Vá (đúng dù nguyên nhân là gì): `window_start()` — nới THEO NHU CẦU.**
Kho nằm ở ĐĨA (miễn phí), nên đếm bar tại chỗ trước rồi mới quyết nới cửa sổ
MẠNG bao nhiêu:
* mã thanh khoản cao ⇒ ~11 ngày là đủ 8 bar chồng lấn (thay vì 30);
* mã nghỉ giao dịch dài / kho rỗng ⇒ **tự giãn tới trần 30 ngày**;
* sàn 3 ngày để không bao giờ hẹp đến mức vô nghĩa.

Sức phát hiện KHÔNG đổi: vùng chồng lấn luôn còn ≥ `MIN_BARS` bar. Chỉ bỏ phần
thừa.

**Phép thử để CHỐT nguyên nhân (một đêm, không cần code):**
```powershell
$env:VNSTOCK_BASIS_GUARD = "0"     # trả về đúng hành vi trước 19/08
python run.py sync
```
Đọc `⏱ CHẶNG`. `updater` về ~1.400s ⇒ đúng là do nới cửa sổ, và bản vá thu
hẹp sẽ ăn phần lớn khoản đó. Vẫn ~5.600s ⇒ **tôi sai**, thủ phạm nằm chỗ
khác (mạng chậm hơn? số mã tăng?) và phải đo tiếp.

## ④ 🔴 RỦI RO LỚN NHẤT: 166,3′ / trần 180′ — chỉ còn 13,7′ đệm (7,6%)

Trần task Daily là `PT3H`. Phát này **chạy hết 92,4% trần**. Task bị chấm dứt
là cắt TRƯỚC bước brief (bước 14/14) ⇒ **mất brief cả đêm**, đúng cơ chế đã
xảy ra 19/08.

Chỉ cần một đêm mạng chậm hơn 8% là mất. Đây là việc gấp hơn cả ③, và ③ chính
là cách rẻ nhất để lấy lại đệm.

Xếp hạng nguồn thời gian (166,3′):
| Bước | Thời gian | % |
|---|---|---|
| **sync** | 110,0′ | **66%** |
| — updater | 94,3′ | 57% |
| — auto-heal | 10,5′ | 6% |
| — fix-units | 5,0′ | 3% |
| screener | 23,2′ | 14% |
| train | 11,2′ | 7% |
| audit | 7,0′ | 4% |
| validate | 6,1′ | 4% |
| brief | 3,2′ | 2% |

`fix-units` cũng đáng soi: 98s (18/08) → 302s, gấp 3, và nó quét TOÀN KHO mỗi
đêm.

## Lưới mới
7 test `TestOverlapWindowIsNoWiderThanNeeded` trong `tests/test_basis_guard.py`
— canh cả hai chiều: hẹp lại cho mã thanh khoản cao, VẪN giãn tới trần cho mã
nghỉ giao dịch dài và cho kho rỗng.
Suite: **2.539 passed** (fast 2.048).

---


# 🔴 U26. TEST PHỤ THUỘC HỆ ĐIỀU HÀNH — LẦN THỨ HAI GIẾT PIPELINE (24/08)

`run.py test` trên desktop: **1 failed / 2.530 passed → exit 2 → dừng cứng**.

```
tests/test_brief_watch.py:125 test_record_never_raises_on_a_bad_path
    assert w.record("/proc/definitely/not/writable", …) is False
E   AssertionError: assert True is False
```

**Lỗi của Claude, và là lần THỨ HAI cùng một họ.** Test dựng "đường dẫn không
ghi được" bằng chuỗi POSIX `/proc/...`. Trên Windows chuỗi đó KHÔNG phải đường
dẫn hỏng — nó là `C:\proc\definitely\not\writable`, và `mkdir(parents=True)`
**thành công**. Nên `record()` ghi được thật, trả True, test đỏ. Xanh trong
container Linux, đỏ trên máy thật.

Lần thứ nhất là U18 (hai test độ tươi phụ thuộc KHO THẬT). Bài học lúc đó ghi
là "cắm dữ liệu vào fixture"; bài học lần này rộng hơn:

> **Test không được giả định gì về MÔI TRƯỜNG** — không hệ tệp, không hệ điều
> hành, không kho, không giờ trong ngày. Muốn thử nhánh hỏng thì **bắt chính
> bước hỏng ném lỗi** (monkeypatch), đừng đi tìm một đường dẫn "chắc là hỏng".

**Giá phải trả cụ thể:** `cmd_all` coi `rc not in (0,1)` là fail cứng, và
`test` là bước 9/14 ⇒ một test đỏ giết luôn train / reflection / doctor /
**brief**. Đúng cơ chế đã mất brief đêm 19/08. Lần này rơi vào lượt chạy tay
nên không mất brief — nhưng nếu user merge lúc 17:5x thì đã mất.

**Vá:** đổi sang monkeypatch `vnstock_parquet_io.write_json_atomic` cho ném
`OSError`, kiểm đúng HỢP ĐỒNG ("sổ hỏng không được kéo brief theo") mà không
đụng hệ tệp. Thêm một test nữa cho `observe_brief` ở cùng nhánh. Docstring
phải để raw-string vì trong đó có `C:\proc` — chuỗi thường đẻ SyntaxWarning.

**Đính chính (25/08):** tôi từng ghi ở đây rằng lượt test đỏ "đã TẠO THẬT"
`C:\proc\definitely\not\writable\_meta\`. Đó là **suy luận, không phải
quan sát** — tôi lập luận từ việc `record()` trả `True` (nghĩa là
`write_json_atomic` đã chạy xong, mà hàm đó có `mkdir(parents=True)`). User
kiểm trên máy thật: `Remove-Item C:\proc` → **PathNotFound, không hề tồn tại**.

Chưa giải thích được vì sao, và **không đáng đào tiếp** (không có rác, test đã
vá). Nhưng đáng ghi lại như một vết của đúng thói xấu mà cả trang này tồn tại
để chống: **trình bày một suy luận bằng giọng của một phép đo.** Lần sau: hoặc
bảo user kiểm rồi mới ghi, hoặc viết rõ "có thể đã tạo — kiểm bằng …".

**Đã quét lại toàn bộ test thêm trong đợt này** (`test_vn30_basket`,
`test_close_2108_review`, `test_weekend_2208_review`, `test_close_2408_review`,
`test_verify_wss_live`, `test_brief_watch`): không còn chỗ nào đụng đường dẫn
tuyệt đối, mạng, kho thật hay giờ trong ngày. Vài chỗ dùng `datetime.now()`
nhưng chỉ để dựng mốc "vừa mới" / "30 ngày trước" rồi khẳng định stale —
không phụ thuộc giờ chạy. Kho thật cũng đã kiểm: `_meta/` KHÔNG có
`brief_watch.json` do test sinh ra.

Suite: **2.532 passed**.

---


# 🔴 U25. CLOSE 24/08 — ⚠️ GDKHQ CHO SỰ KIỆN KHÔNG ĐỔI GIÁ (ca PNJ)

Phát 18:00 T2 24/08 chạy trọn, gửi được brief. **Lưu ý đọc: phát này chạy trên
bản `2.447`** — desktop chưa merge các đợt vá 21-22/08, nên hai lỗi đã vá rồi
vẫn xuất hiện trong bản này (khối tin cụt chữ). Chỉ mục ① dưới đây là lỗi MỚI.

## ① Lỗi mới: cảnh báo một cú giảm KHÔNG BAO GIỜ xảy ra

```
1. **PNJ** (Giá 42,650) — MUA vùng 42,650 … · ⚠️ GDKHQ 2026-08-24
   (PNJ - Tổ chức ĐHĐCĐ bất thường 2026) — giá tham chiếu tự điều chỉnh,
   mốc trên CHƯA quy đổi
```

**Tổ chức ĐHĐCĐ là chốt danh sách DỰ HỌP.** Không có gì chia ra khỏi doanh
nghiệp ⇒ HOSE **KHÔNG** điều chỉnh giá tham chiếu. Câu cảnh báo nói về một cú
giảm không tồn tại. Mục 📅 Sự kiện sắp tới cũng dán ghi chú "(Giá tự điều
chỉnh trong ngày GDKHQ…)" cho danh sách mà sự kiện đầu là ĐHĐCĐ.

**Vì sao đây KHÔNG phải lỗi nhỏ:** sai kiểu này **tệ hơn im lặng**. Nó dạy
người đọc rằng ⚠️ GDKHQ hay báo hão, nên đúng lúc có cú điều chỉnh THẬT — MSB
thưởng cổ phiếu **tỉ lệ 20%** ngày 28/08, giá sẽ rơi ~16,7% — thì họ lướt qua.
Cùng họ "alarm fatigue" mà `vnstock_doctor` đã đặt tên.

**Gốc rễ:** `_exdate_map` nhận MỌI sự kiện có `ex_date`, và nhánh dự phòng của
`enforce_exdate_levels` khẳng định "giá tham chiếu **tự điều chỉnh**" cho bất
kỳ tiêu đề nào không đọc được tỉ lệ. `vnstock_corp_ratio.parse_event` trả None
cho ĐHĐCĐ là ĐÚNG (không có tỉ lệ), nhưng "không đọc được tỉ lệ" bị đánh đồng
với "có đổi giá mà chưa quy đổi được".

**Vá:** `vnstock_corp_ratio.adjusts_price(title)` — hàm thuần, ba tầng:
1. Có phân phối (tiền/cổ phiếu) hoặc quyền mua ⇒ **CÓ** đổi giá.
2. Chỉ chốt danh sách dự họp/bỏ phiếu (`đại hội đồng cổ đông`, `lấy ý kiến
   bằng văn bản`, `tham dự đại hội`…) ⇒ **KHÔNG**.
3. Không nhận ra ⇒ **mặc định CÓ** — bỏ sót một cú điều chỉnh thật tệ hơn
   nhiều so với cảnh báo thừa.

Tầng 1 đặt TRƯỚC tầng 2 có chủ đích: "ĐHĐCĐ thông qua trả cổ tức bằng tiền"
vẫn phải cảnh báo.

Nối vào HAI chỗ: `_exdate_map` bỏ qua sự kiện không đổi giá (mã chỉ có ĐHĐCĐ
thì không còn ⚠️ nào), và footer mục Sự kiện chỉ hiện khi trong 3 dòng đang
hiện có ít nhất một sự kiện thật sự đổi giá. **Sự kiện vẫn được LIỆT KÊ** —
chỉ bỏ câu ghi chú sai.

Một test cũ (`test_unreadable_ratio_falls_back_to_the_wordy_warning`) dùng
"Đại hội cổ đông thường niên" làm ví dụ "không đọc được tỉ lệ" — nay đổi sang
"quyền mua" (đúng loại: CÓ đổi giá nhưng không suy được tỉ lệ từ tiêu đề).

## ② Đã vá từ 22/08, chỉ chờ desktop merge

* Khối tin vẫn cụt: `tác động: C` · `tác động: Căng` · `…cạnh tranh tại thị`.
  `sanitize_impact` (bản 2.462) gộp xuống dòng + cắt ở biên từ kèm `…`.
  **Phép thử sau khi merge:** nếu câu vẫn cụt Y NGUYÊN thì gốc rễ nằm ở tầng
  SINH (`analyze_item` gọi `chat_complete(max_tokens=120)` — chính LLM bị cắt
  giữa câu), không phải tầng dọn; lúc đó nới `max_tokens` mới đúng chỗ.
* Watchlist PNJ/PVS/CEO đều ±3,0% đối xứng, R:R chẵn 1,00 — đúng như U23 nói:
  hệ quả tất yếu của cấu tạo, không phải model bịa.

## ③ Đã kiểm, KHÔNG có lỗi
* Số học vĩ mô khớp cả 5 phép: ON−điều hành −1,22 · 10Y−ON +1,13 ·
  10Y−điều hành −0,09 · 10Y−2Y +0,42 · VN10Y−US10Y −0,28.
* MA khớp: 1.788,78 so MA20 1.751,52 = +2,13% · MA50 1.786,86 = +0,11% ·
  MA200 1.778,19 = +0,60%.
* GTGD 22.582,8 tỷ "+11% so phiên trước" — KHÔNG bị dán nhầm sang chỉ số
  (+1,17%), tức lỗi U22① không tái diễn ngay cả trên bản cũ.
* Guard lệch khung thời gian ĐANG chạy: brief tự nói "Band phân bổ là khung
  THÁNG, tín hiệu phiên đang lệch chiều — hai khung không phủ định nhau".

## ④ Chưa đủ căn cứ, đã vào sổ tự đếm
"Tụt hậu: **Chưa có nhóm tụt hậu rõ rệt** [đóng góp −0.044pp]" — vừa nói không
có vừa đưa số. Một lần chưa đủ để biết là mẫu câu cố định hay ngẫu nhiên.

## Lưới mới
`tests/test_close_2408_review.py` (15), đã vào `--fast`.
Suite: **2.531 passed** (fast 2.040).

---


# 🟠 U24. WEEKEND 22/08 — HỎNG TÀI KHOẢN ≠ HỎNG MODEL (và nhãn tuần/phiên)

`run.py weekend` chạy trọn, gửi được cả hai báo cáo. Soi ra hai lỗi TRÌNH BÀY
— không lỗi số, nhưng cả hai đều dẫn người đọc đi làm sai việc.

## ① Model watch: 3 dòng ❌ giống hệt nhau, đòi HAI hành động khác hẳn

```
❌ Cerebras gemma-4-31b   — HTTP 402: Payment required … Visit your billing
❌ Cerebras gpt-oss-120b  — HTTP 402: Payment required …
❌ OpenRouter openai/gpt-oss-20b:free — HTTP 404: This model is unavailable for free
🗑 OpenRouter openai/gpt-oss-20b:free biến mất khỏi danh mục
```

**HTTP 402 KHÔNG phải model chết** — đó là hỏng **TÀI KHOẢN**. Mọi model
Cerebras sẽ 402 y như vậy, nên chạy quy trình `_MODEL_MIGRATIONS` +
`_DEAD_SLUGS` cho Cerebras là **mất công vô ích**: slug mới cũng 402. Việc
đúng là chuyện hoá đơn/hạn mức, không phải chuyện code.

**HTTP 404 + biến mất khỏi danh mục MỚI là model chết** — đúng ca dùng quy
trình đó.

Báo cáo cũ trộn hai thứ vào một loại dòng ⇒ người đọc dễ đi thay slug
Cerebras rồi vẫn hỏng. **Vá:** `build_dead_alerts()` / `account_level_code()`
(hàm thuần) gộp theo PROVIDER khi mã là 401/402/403:

```
🏦 Cerebras — TÀI KHOẢN hết quyền truy cập — cần nạp tiền (HTTP 402).
   MỌI model Cerebras sẽ hỏng y như vậy, ĐỔI SLUG KHÔNG CỨU ĐƯỢC.
   Đang mất: gemma-4-31b ([1] sentiment + [7] fallback) · gpt-oss-120b (…)
❌ OpenRouter openai/gpt-oss-20b:free — [1] sentiment + [3-6] digest b2: HTTP 404 …
```

**429 CỐ Ý không gộp** — nghẽn tạm thời, gộp thành "tài khoản chết" là báo
động giả (chính vết `vnstock_model_watch` đã ghi: 4 lượt probe trong 45 phút
làm free tier throttle 0,9s → 17s rồi tự khỏi).

### Bản đồ thiệt hại thật (đọc từ code, không đoán)

| Điểm | Thang trước | Còn sống |
|---|---|---|
| [1] sentiment | Gemini → Groq → Cerebras → OpenRouter | **Gemini → Groq** (Cerebras 402, OR gỡ) |
| [3-6] digest bậc 1 | Gemini / Cerebras / OpenRouter-nemotron | **Gemini + nemotron** |
| [3-6] digest bậc 2 | Groq×2 → Gemini-lite → OpenRouter | **Groq×2 → Gemini-lite** |
| [7] brief | Gemini (CHÍNH) + Cerebras | **Gemini** |

⇒ **Không điểm nào chết**, khớp với việc brief 21/08 vẫn ra. Nhưng lưới dự
phòng mỏng đi rõ: sentiment từ 4 nấc còn 2, và Gemini nay gánh cả brief lẫn
digest bậc 1 lẫn nấc 1 sentiment. Gemini nghẽn là hụt nhiều chỗ cùng lúc.

**Đã gỡ `openai/gpt-oss-20b:free`** khỏi cả hai thang + thêm vào `_DEAD_SLUGS`
+ **sửa migration trỏ vào chính nó** (`meta-llama/llama-3.1-8b-instruct:free`
→ nó → chết: migration trỏ vào model chết thì vô dụng; nay dồn về
`nvidia/nemotron-3-super-120b-a12b:free`).

**CỐ Ý KHÔNG thêm slug mới**: quy tắc repo là slug mới phải probe SỐNG trên
máy thật trước, không chép từ catalog. Muốn có lại nấc thứ 4 thì probe rồi
hẵng thêm.

## ② Báo cáo TUẦN in con số đổi của MỘT PHIÊN, không ghi mốc

```
• Lãi suất liên ngân hàng ON: 3.01%/năm  ▼ -1.01 điểm %
📝 … qua đêm giảm 1.01 điểm % so với kỳ trước.
```

`change` của `vnstock_macro` là so với **LẦN ĐỌC LIỀN TRƯỚC** (`_pick` lấy
`dates[idx-1]`) — với lãi suất LNH đó là **phiên trước**, ở đây 2026-08-19.
Trong một bản mang tên "Báo cáo TUẦN", "kỳ trước" đọc ra là **tuần trước**, và
con số trần trụi `▼ -1.01` đọc ra là đổi trong tuần. Bản brief hằng ngày thì
ghi đúng ("so với 2026-08-19") — tức bản tuần LÀM MẤT nhãn mà bản ngày giữ.

Cùng họ bất biến với `Giá 1T %` trong CLAUDE.md: **mọi nhãn phải ghi rõ khung
thời gian**. **Vá:** đưa `prev_as_of` vào cả 3 chỗ — bullet Telegram, ô HTML,
và câu narrative (`so với 2026-08-19` thay cho `so với kỳ trước`; thiếu ngày
thì lùi về "lần đọc trước", **không bịa ra tuần**).

## Đã kiểm, KHÔNG có lỗi
Toàn bộ số học báo cáo tuần khớp: ON−điều hành −1,49 · 10Y−điều hành −0,10 ·
10Y−2Y +0,42 · VN10Y−US10Y −0,25 · HNX 2Y/5Y/10Y khớp dòng TPCP.

## Lưới mới
`tests/test_weekend_2208_review.py` (18), đã vào `--fast`.
Suite: **2.516 passed** (fast 2.025).

---


# 🔴 U23. ±3% ĐƯỢC GỌI LÀ "HỖ TRỢ/KHÁNG CỰ" — CHÍNH REPO BỊA, KHÔNG PHẢI MODEL

Soi tiếp mục ③ của U22 bằng 4 luồng đọc code song song. Kết quả **lật ngược
quy kết ban đầu của tôi**, và đó mới là phần đáng ghi.

## ① Watchlist: không phải model bịa mốc — repo bịa hộ nó, đều đặn mọi phiên

Tôi từng ghi "watchlist có mùi công thức… một phiên hai mã chưa đủ mẫu, đếm
thêm vài phiên". **Sai ở khâu quy kết**: chuyện này không cần đếm, đọc hai
dòng code là xong.

`vnstock_brief._vn30_line` gắn vào MỌI mã ⭐:

```python
_p = float(price) * 1000
line += f" ⭐ [mốc của mã: hỗ trợ ~{_round_tick(_p*0.97, _p):,} / kháng cự ~{_round_tick(_p*1.03, _p):,}]"
```

và template ra lệnh `MỐC GIÁ SETUP MỖI MÃ LẤY TỪ "[mốc của mã…]"`. Nghĩa là
**chính ctx dán nhãn "hỗ trợ/kháng cự" lên hai con số chỉ là giá ×0,97 và
×1,03**. Model chép lại trung thực ⇒ close 21/08: *"giữ vững trên hỗ trợ
81,000 và hướng tới kháng cự 86,000"* cho GAS — nghe như mốc kỹ thuật đo được,
thực chất là 83.500 ±3%. Tái dựng khớp từng đồng: 83.500 → 81.000/86.000;
39.900 → 38.700/41.100 (bước giá 100 và 50).

**R:R chẵn 1,00 là hệ quả TẤT YẾU của cấu tạo**, không phải trùng hợp — nên
"đếm thêm vài phiên" là việc vô nghĩa: phiên nào cũng sẽ ra 1,00.

Repo CÓ pivot thật (`vnstock_strategy._ticker_pivots`, 60 bar, bỏ 2 bar cuối)
nhưng chưa bao giờ nối vào đường watchlist — và ctx watchlist **không hề có**
OHLC/MA/ATR của mã (chỉ `Mã / Giá 1T % / Ngành / last / GTGD TB`), nên không
thể tính mốc thật ở tầng guard. Nối được thì phải đọc kho ở tầng dựng ctx.

**Vá (chừng nào chưa nối pivot thật): NÓI THẬT TÊN.**
* Nhãn ctx: `⭐ [dải ±3% quanh giá: 81,000 – 86,000 — mốc THAM CHIẾU tính từ
  giá, KHÔNG phải hỗ trợ/kháng cự đo được]`.
* Template cấm hẳn chữ "hỗ trợ"/"kháng cự"/"vùng cung cầu" cho các mốc này.
* **Guard `enforce_reference_band_wording`** — vì doctrine repo là model phớt
  chỉ thị nên đổi nhãn chỉ là điều kiện CẦN. Guard đổi "hỗ trợ/kháng cự N"
  → "mốc tham chiếu N" **CHỈ KHI N trùng KHỚP TUYỆT ĐỐI** một mốc ±3% mà
  chính prompt đã tính cho mã đó. Mốc thật (nếu sau này nối pivot) không
  trùng nên không bị đụng — guard không được phép làm nghèo brief thật. Cắt
  phần `⚠️ GDKHQ` trước khi soi (nó mang giá tham chiếu riêng).

**Việc mở, đã có mỏ neo:** nối `_ticker_pivots` vào tầng dựng ctx cho 1-3 mã
watchlist (đọc kho, ~60 bar/mã, rẻ) rồi mới được gọi là hỗ trợ/kháng cự; giữ
±3% làm lưới cuối và GIỮ NGUYÊN nhãn "tham chiếu" cho lưới cuối đó.

## ② Hai nghi ngờ còn lại: ĐẾM, đừng đoán ngưỡng

Ghi vào `docs/CLAUDE-NOTES.md` là **ghi vào chỗ không bao giờ nổi lên lại** —
chính file này tự nhận là "kho lưu, không phải để làm theo". Nên chuyển sang
cho MÁY đếm: `vnstock_brief_watch` + badge doctor `brief_watch`.

**(a) Op.CF quá lớn so với quy mô.** KBC −17.344 tỷ ≈ **0,826× vốn hoá**.
Đo được, nhưng ngưỡng nào là "sai" thì chưa biết: BĐS tích luỹ quỹ đất âm
nặng là chuyện THẬT, và đó chính là tín hiệu mục Rủi ro sinh ra để nói —
ngưỡng đặt bừa sẽ giết đúng tín hiệu đó. Ghi nhận từ 0,5× trở lên.
Đường số hoàn toàn xác định: `operating_cf` chia 1e9 lúc ghi parquet,
`Vốn hoá (tỷ)` chia 1e9 ở runner ⇒ cùng đơn vị tỷ VND, tỉ số không thứ nguyên.
*(Ghi chú: mục U-cũ trong file này từng khẳng định "là SỐ THẬT" — đó là khẳng
định KHÔNG có phép đo kèm, nay đã có phép đo nên để sổ quyết.)*

**(b) Câu viện dẫn dòng tiền ngoại không có trong data.** Lý do bán SSI nói
"khối ngoại bán ròng mạnh nhóm Chứng khoán", trong khi `ctx["sectors"]` cho
ngành đó **NN 1T = +340 tỷ** (MUA ròng). Guard **biết nhiều hơn model**:
prompt chỉ đưa top-3 mỗi chiều, ctx giữ trọn ~32 dòng ngành. Chỉ ghi nhận khi
tên ngành khớp CHÍNH XÁC một dòng ctx — khớp mờ là tự tạo báo động giả.
Không kiểm được chữ "liên tục": ctx chỉ có 3 ảnh chụp chồng lấn (1T/1M/3M),
không có chuỗi theo phiên.

**Kỷ luật của sổ:**
* Dưới `MIN_SAMPLES` phiên ⇒ badge **ok kèm n=…**, TUYỆT ĐỐI không warn. Vết
  13/08 của repo là trình bày "chưa đo được" thành "đo ra kết quả xấu" (n=2
  vẽ thành "0%").
* Cùng ngày + cùng máy thì GHI ĐÈ: chạy lại `run.py brief` ba lần một tối
  không được thành ba lần bằng chứng.
* Mỗi quan sát có trường `host` — kho đi qua Dropbox nên hai máy dùng chung
  file; không có trường máy thì sổ trộn hai máy mà không ai biết (đúng hệ quả
  #2 của banner Dropbox).
* Trần 400 sự kiện. Kill-switch `VNSTOCK_BRIEF_WATCH=0`.

## Lưới mới
`tests/test_brief_watch.py` (27) + 9 test dải ±3% trong
`tests/test_close_2108_review.py`. Cả hai file đều ở `--fast`.
Suite: **2.498 passed** (fast 2.007).

---


# 🔴 U22. BRIEF CLOSE 21/08 — GUARD SỐ LÀ NO-OP VÌ MỘT TRẠNG TỪ (22/08)

Phát 18:00 ngày 21/08 chạy trọn và gửi được brief. Soi bản gửi ra hai lỗi lọt
lưới, cộng ba điểm đáng ngờ chưa đủ chứng cứ để sửa.

## ① "VNINDEX đóng cửa tăng mạnh +51% so với phiên trước"

Chỉ số thật **+1.95%** — 51 là % đổi **GTGD** bị dán sang chỉ số. Chính brief
đó viết +1.95% ở **cả TLDR lẫn mục kỹ thuật** ⇒ tự mâu thuẫn trong một bản.
Đối chiếu độc lập: tin VnExpress cùng ngày "Chứng khoán tăng gần 34 điểm", mà
1.768,12 / 1,0195 = 1.734,3 ⇒ +33,8 điểm. Khớp. Vậy +1.95% đúng, +51% sai.

**`enforce_vnindex_change` ĐÃ CÓ MẶT để chặn đúng ca này** (vết 16/06 dán
momentum -24 vào; vết 15/07 bịa "giảm 1.36%" khi bar phẳng). Nó vẫn nằm trong
`apply_brief_guards`, vẫn có test — mà **không làm gì cả**:

```python
r"(?:tăng|giảm)\s*[+-]?\d[\d.,]*\s*%"      # "tăng mạnh +51%" KHÔNG khớp
```

`\s*` giữa động từ và con số không nuốt được chữ **"mạnh"**. Guard sống, test
xanh, nhưng câu model hay viết nhất thì nó không thấy. Đây là biến thể của họ
bug đã đặt tên trong repo — không phải "quên nối guard", mà **"guard nối rồi
nhưng regex hụt đúng cách viết phổ biến"**, khó thấy hơn hẳn vì mọi lưới đều
xanh.

**Vá:** thêm nhóm `_ADVERB` — danh sách ĐÓNG (`mạnh mẽ|mạnh|nhẹ|vọt|nhanh|sâu|
đáng kể|ấn tượng|khá|tốt|đột biến|kịch trần`), **cố ý KHÔNG dùng `\w+` chung
chung**: bắt bừa một từ bất kỳ là guard tự tay ghi đè số của mệnh đề khác — đúng
cái bẫy `_SUBJ_SKIP` đã dựng để tránh (vết 14/07: guard đè số GTGD bằng
day_change_pct). Có test canh cả hai chiều: sửa được câu thật, và **KHÔNG** đụng
mệnh đề GTGD trong CÙNG câu (`(tăng 51% so với phiên trước…` giữ nguyên).

## ② Khối 📰 Tin vỡ dòng

```
- ⚪ … Hormuz (VnExpress Thế giới) — tác động: An ninh tại Horm
- ⚪ … bầu cử (VnExpress Thế giới) — tác động: `
*
- 🟢 … Iran 'sụp đổ' (VnExpress Thế giới) — tác động: C
```

Thủ phạm KHÔNG phải cái trần `[:160]` (ba câu này ngắn hơn nhiều) mà là **ký
tự xuống dòng + rác markdown nằm TRONG `_impact`**. `_market_news_body_lines`
dựng khối theo TỪNG DÒNG, nên một `\n` trong impact đẩy phần còn lại thành
dòng lạc — nhìn hệt như câu bị cụt. Trần `[:160]` thì lỗi kiểu khác: nó cắt
**giữa từ** và không có dấu `…` nên người đọc không biết là còn nữa.

**Vá:** `sanitize_impact()` (hàm thuần, trong `vnstock_brief_canon`) — gộp MỌI
khoảng trắng kể cả `\n`, bỏ ký tự điều khiển markdown, rồi cắt ở **biên từ**
kèm `…`. Đặt ở **CẢ HAI đường**: đường ghi (`analyze_item`) và đường hiển thị
(`_market_news_body_lines`) — vì cache tin đã chứa sẵn giá trị bẩn, sửa mỗi
đường ghi thì bản gửi tối nay vẫn vỡ. Tiêu đề tin cũng gộp dòng (`_one_line`).

## ③ Chưa sửa — cần thêm chứng cứ

* **Watchlist có mùi công thức.** GAS 83.500 ±2.500 · PNJ 39.900 ±1.200 —
  **cả hai đúng ±3,0% đối xứng**, R:R chẵn 1,00. Câu chữ thì nói "giữ vững
  trên hỗ trợ 81.000 và hướng tới kháng cự 86.000" như thể đó là mốc THẬT.
  Nếu đúng là model dựng bằng ±3% rồi gọi tên là hỗ trợ/kháng cự thì đây là
  bịa mốc — nhưng một phiên hai mã chưa đủ mẫu. **Đếm thêm vài phiên trước
  khi viết guard.**
* **KBC Op.CF = −17.344 tỷ** — rất lớn so với quy mô KBC. Có thể thật (BĐS
  tích luỹ quỹ đất) nhưng đáng soi lại đơn vị.
* **Lý do bán SSI** nói "khối ngoại liên tục bán ròng mạnh nhóm Chứng khoán",
  trong khi mục 💰 Dòng tiền của CÙNG brief liệt kê bên bán ròng mạnh nhất là
  **Họ VIN và Ngân hàng** — không có Chứng khoán. Model viện dẫn dữ kiện không
  có trong data.

## Lưới mới
`tests/test_close_2108_review.py` (15), đã vào `--fast`.
Suite: **2.462 passed** (fast 1.971).

---


# 🔴 U21. HEATMAP LIVE: RỔ VN30 CŨ + ĐỘ TRỄ CỘNG DỒN (20/08, mắt người)

User bật Live Mode trong phiên, nhìn heatmap và báo hai chuyện — **cả hai đều
là lỗi thật, và cả hai đều KHÔNG có lưới nào bắt được**. Đây chính là giá trị
của mục W1 (mắt người): script `verify_wss_live` chấm ✅ cả 3 bất biến vài phút
trước đó mà không thấy gì, vì nó chấm *cơ chế volume*, không chấm *nội dung*.

## ① Rổ VN30 đã đổi, dashboard vẫn vẽ rổ cũ

**Gốc rễ:** danh sách 30 mã được **CHÉP CỨNG ở ba module độc lập**, không chỗ
nào tự làm mới:

| Chỗ chép | Dùng cho |
|---|---|
| `vnstock_brief_canon.VN30_TICKERS` | brief, screener, guard |
| `vnstock_wss.VN30_SYMBOLS` | subscribe WSS + heatmap live |
| `vnstock_news._VN30_FALLBACK` | lọc tin |

HOSE xét lại rổ VN30 **2 lần/năm** (hiệu lực đầu tháng 2 và đầu tháng 8) ⇒ cứ
mỗi kỳ là brief, screener và heatmap **cùng nói sai một lúc**, im lặng. Trớ
trêu: `vnstock_brief.get_vn30_live()` ĐÃ có sẵn đường lấy rổ sống
(`listing.symbols_by_group("VN30")`) từ lâu — nhưng chỉ brief dùng, và nó
không ghi cache nên không ai khác thấy.

**Đã vá — `vnstock_vn30.py`, một nguồn sự thật duy nhất:**
* Thứ tự **API sống → cache `_meta/vn30_members.json` (7 ngày) → hằng số**.
  Cache nằm trong kho ⇒ đi Dropbox ⇒ **fetch một lần phục vụ cả hai máy**.
* `validate()` từ chối rổ ngoài dải 25–35 mã. Đây là lưới quan trọng nhất:
  API trả dở dang 12 mã mà được nhận thì heatmap **teo âm thầm** — tệ hơn hẳn
  rổ cũ, vì rổ cũ ít ra còn đủ 30 ô.
* `resolve()` là **hàm thuần** (fetch/cache tiêm vào) nên test được cả 3 tầng
  ưu tiên mà không cần mạng.
* Hằng số chép cứng **giữ nguyên** — vẫn là lưới cuối khi mất mạng. Nhưng nó
  không còn là nguồn sự thật.
* Badge doctor `vn30_basket` (offline, **cấm gọi mạng**, chỉ đọc cache) +
  `net_vn30_basket` (`--net`, làm mới rồi so). Lệch thì in thẳng
  `VÀO rổ: … · RỜI rổ: …` và chỉ ba file cần sửa hằng số.
* Heatmap đi qua `vnstock_dashboard.get_vn30_symbols()` — không import thẳng
  `vnstock_wss`, vì mọi hằng số live của tab đều lấy từ đó (và test dựng module
  giả ở đúng chỗ đó).

⚠️ **Việc còn lại cho máy có mạng:** chạy `python run.py doctor --net` một lần
để nạp cache. Đường sống + heatmap tự dùng rổ mới ngay; hằng số ở 3 file thì
Claude sẽ sửa sau khi biết rổ thật (doctor sẽ in ra).

### ①b Vòng 2 — "API không trả rổ dùng được": Series ≠ DataFrame

`doctor --net` 20/08 ra `⚠️ Rổ VN30 — làm mới từ nguồn — API không trả rổ dùng
được (đang dùng fallback)`. Đọc thẳng mã nguồn gói đã cài
(`vnstock.explorer.vci.listing.Listing.symbols_by_group`) thì dòng cuối là:

```python
df = pd.DataFrame(json_data)
df.source = "VCI"
return df["symbol"]        # ← pd.Series, KHÔNG phải DataFrame
```

Cả `vnstock_vn30._fetch_live` (bản đầu, viết cùng ngày) **lẫn**
`vnstock_brief.get_vn30_live()` (có từ lâu) đều dò `df.columns`. Series không
có `.columns` ⇒ AttributeError ⇒ `except Exception: pass` ⇒ im lặng rơi về
hằng số.

**Hệ quả nặng hơn cái badge:** `get_vn30_live()` trong brief là **code chết
trông y như code sống** — nó CHƯA BAO GIỜ lấy được rổ động, từ ngày viết. Không
có badge doctor mới thì chuyện này còn ẩn tiếp qua nhiều kỳ đổi rổ nữa. Đúng họ
bug repo đã đặt tên: *"guard quên nối = code chết trông y như code sống"*.

**Vá:**
* `extract_symbols(obj)` — hàm thuần, nhận **Series** (dạng thật) · DataFrame
  có cột `ticker`/`symbol`/`code` · DataFrame 1 cột tên lạ · list/tuple/set/
  dict. Từ chối DataFrame nhiều cột không có cột mã (đoán bừa còn tệ hơn).
* `vnstock_brief.get_vn30_live()` nay **uỷ quyền** cho `vnstock_vn30` — một
  đường duy nhất, một chỗ sửa, có cache dùng chung hai máy.
* `python vnstock_vn30.py --diag` in THẬT nguồn trả gì: type, columns, số mã,
  8 mã đầu, kết quả validate, và diff so hằng số. Không có nó thì "API không
  trả rổ dùng được" là câu bí hiểm.
* Badge `net_vn30_basket` nay trỏ thẳng vào lệnh diag thay vì "soi
  _fetch_live".
* 10 test mới, trong đó test đầu tiên dựng đúng `pd.Series(name="symbol")`.

### ①c Rổ mới, kỳ tháng 8/2026 (đo được 20/08 sau khi vá Series)

```
[vn30] type=Series columns=(không có) len=30
[vn30] ✅ rổ sống 30 mã
[vn30] ⚠️ LỆCH hằng số — VÀO rổ: ['BSR', 'LPB', 'MCH', 'TCX', 'VPL']
                         · RỜI rổ: ['BCM', 'BVH', 'PLX', 'POW', 'TPB']
```

**5 mã vào / 5 mã ra** — thay 1/6 rổ. Đã cập nhật hằng số ở cả ba file, và
thêm lưới `TestTheThreeHardcodedCopiesNeverDrift` canh **ba bản chép phải
KHỚP NHAU** (trước đó không có gì canh: sửa một chỗ quên hai chỗ kia thì
brief, tin và heatmap nói ba rổ khác nhau, im lặng).

**Đuôi phải dọn theo, không chỉ ba danh sách:**
* `vnstock_sectors` — VPL (Vinpearl) ĐÃ có sẵn trong "Họ VIN", không phải sửa.
* `vnstock_brief_canon._FINANCIAL_TICKERS` — LPB ĐÃ có sẵn, không phải sửa.
* `vnstock_train._VN30_SECTOR_MAP` — thêm BSR→energy, LPB→bank, MCH→consumer,
  VPL→transport. **CỐ Ý GIỮ** BCM/BVH/PLX/POW/TPB dù đã rời rổ: mã rời VN30
  thường rơi xuống VNMID, xoá đi là mất phân ngành ở chỗ vẫn còn dùng.
* **TCX cố ý ĐỂ TRỐNG** trong bản đồ ngành — chưa xác minh được ngành, mà gán
  bừa thì lệch tầng ÂM THẦM, còn thiếu thì rơi về
  `industry_classification.parquet`, hỏng theo kiểu ồn ào hơn.

`--diag` nay đối chiếu luôn với kho: rổ đúng mà mã mới CHƯA có `ticker=<MÃ>`
trong `prices/` thì heatmap vẫn ô trống và screener vẫn bỏ sót — hỏng ở chỗ
khác hẳn, phải nói ra chứ đừng để user tự đoán.

### ①d Chốt trên máy thật (20/08)

```
[vn30] type=Series columns=(không có) len=30
[vn30] 💾 đã ghi cache → C:\vnstock\data_warehouse\_meta\vn30_members.json
[vn30] ✅ rổ sống 30 mã
[vn30] ✅ khớp hằng số chép cứng
[vn30] ✅ cả 30 mã đều có thư mục giá trong kho
```

Ba lượt diag liên tiếp mới ra được ba dòng ✅ + cache — mỗi lượt lộ một lỗi
khác nhau (Series → rổ lệch → cache không ghi). **Mục ① đóng.**

### ①e TCX = Techcom Securities (TCBS) — CÔNG TY CHỨNG KHOÁN

Tra ra (CafeF · VietstockFinance · DNSE đều khớp): **TCX = CTCP Chứng khoán
Kỹ Thương (Techcom Securities / TCBS)**, công ty con của Techcombank, niêm yết
HOSE 21/10/2025, vốn hoá ~108.000 tỷ — lớn nhất ngành chứng khoán.

Điền `TCX → "securities"` trong `_VN30_SECTOR_MAP`. **Nhưng chỗ quan trọng
hơn là chỗ suýt bỏ sót:** `vnstock_brief_canon._FINANCIAL_TICKERS`. Set đó
giữ cho ngân hàng/chứng khoán/bảo hiểm KHÔNG bị xếp hạng rủi ro cơ bản chung
với doanh nghiệp thường (D/E ngân hàng 9-17 là BÌNH THƯỜNG, Op.CF âm chục
nghìn tỷ cũng vậy — xem ca "MBB Op.CF -64.972 tỷ"). TCX không có trong đó ⇒
brief sẽ gọi tên một công ty chứng khoán như một rủi ro cơ bản, **sai mà nghe
rất thuyết phục**.

Đây là bẫy TÁI DIỄN mỗi kỳ đổi rổ, nên chốt bằng lưới chứ không bằng trí nhớ:
`test_every_financial_in_the_sector_map_is_in_the_financial_set` — mọi mã
được gán bank/securities/insurance PHẢI có trong `_FINANCIAL_TICKERS`. Kèm
`test_every_basket_member_has_a_sector` để không mã nào trong rổ còn trống
ngành nữa.

Đối chiếu 4 mã mới còn lại: LPB đã có sẵn trong `_FINANCIAL_TICKERS` ✓ · BSR
(lọc hoá dầu) · MCH (Masan Consumer) · VPL (Vinpearl) đều KHÔNG phải định chế
tài chính ✓. "Họ M" trong `vnstock_sectors` là hệ Gelex chứ không phải Masan
nên MCH không thuộc nhóm đó.

**Mục ① đóng hoàn toàn.**

## ② "Phản hồi chậm" = độ trễ CỘNG DỒN, không phải feed chậm

Ba tầng nối tiếp nhau, mỗi tầng góp trễ:

| Tầng | Trước | Sau |
|---|---|---|
| `@st.fragment(run_every=)` heatmap | **5s** | **2s** (khớp `POLL_INTERVAL`) |
| Vòng poll với `full_market=True` | quét CẢ ~1.100 mã mỗi vòng | VN30+index+futures MỖI vòng, phần còn lại mỗi 5 vòng |
| Đo được nhịp thật | **không có gì đo** | `get_status()["cycle_s"]` + caption sidebar |

Tầng 2 mới là chỗ đau: heatmap cần **30 mã**, nhưng động cơ gọi `price_board`
cho ~1.100 mã rồi ghi ~1.100 file JSON MỖI VÒNG — nên một quote VN30 chỉ tươi
lại sau trọn một vòng quét toàn thị trường. (Cũng chính là nguồn của
`[WinError 5]` ở U20: 1.100 lượt ghi/vòng vào thư mục Dropbox.)

**`split_hot_cold()` là hàm thuần**, và bất biến quan trọng nhất của nó:
**KHÔNG BAO GIỜ trả vòng quét rỗng** cho đầu vào khác rỗng — một vòng rỗng là
feed đứng hình trong khi status vẫn `connected`, đúng họ bug "im lặng trông
như bình thường". Không có mã nóng nào ⇒ quét tất cả. `subscribe_all()` (38
mã, mọi mã đều nóng) ⇒ **hành vi KHÔNG đổi**, nên `verify_wss_live` vẫn đo đúng
thứ nó vẫn đo. Kill-switch `VNSTOCK_WSS_HOT_TIER=0`.

**Giá phải trả (cố ý):** Live Scan của Screener/Dòng Tiền chậm lại ~5×. Đổi lấy
heatmap bám tick — user nhìn heatmap, không nhìn Live Scan mỗi 2 giây.

**Đừng tối ưu tiếp bằng cảm giác.** Nay đã có `cycle_s` trong badge sidebar:
đọc số thật rồi mới quyết có cần chia nhỏ `price_board` hay bỏ ghi JSON từng
mã hay không.

## Lưới mới
`tests/test_vn30_basket.py` (26) + 3 test heatmap-theo-rổ-sống trong
`tests/test_live_mode_crosstab.py`. Cả hai file đều vào `--fast`.
Suite: **2.429 passed** (fast 1.938).

---


# 🔧 U20. BỘ CHẤM LIVE MODE MÙ LỊCH PHIÊN — báo động giả chờ sẵn (20/08)

`python scripts\verify_wss_live.py --duration 120` trên máy thật:

```
⚠️ [1] Chỉ 14/30 mã có volume > 0 (mã volume 0: BCM, BID, BVH, GAS, GVR, MBB, MWG, PLX…)
✅ [2] Index/futures volume == 0 đúng thiết kế
✅ [3] suspect_count = 0
```

**Hai bất biến THẬT SỰ từng vỡ hồi 07/08 ([2] và [3]) đều ✅.** [1] không phải
bất biến của code — nó là phép đo thanh khoản, và vừa trượt ngưỡng 50% sát sao
(14 < 15).

**Danh sách mã volume 0 mới là chỗ đọc được chuyện gì đã xảy ra:** BID, MBB,
GAS, MWG thuộc nhóm thanh khoản cao nhất sàn — chúng KHÔNG THỂ đứng im 2 phút
giữa khớp lệnh liên tục. Nên cửa sổ đo gần như chắc chắn rơi ngoài khớp lệnh
liên tục: nghỉ trưa 11:30-13:00, hoặc sau 14:30 (ATC / thoả thuận).

**Gốc rễ:** `vnstock_wss._is_market_open()` chỉ so `MARKET_OPEN = 9:00` với
`MARKET_CLOSE = 15:00` (`vnstock_wss.py:243`) — KHÔNG biết nghỉ trưa. Trong giờ
nghỉ nó vẫn báo `status=connected`, bar vẫn hình thành mỗi phút (bar sinh từ
tick GIÁ, không phải từ lệnh khớp), chỉ khối lượng tích luỹ là đứng yên. Khớp
với số đo: 102 bar / 3 mốc phút / 38 mã — tức MỌI mã đều ra bar đều đặn.

**Đây là báo động giả CHỜ SẴN, không chỉ là thông báo khó hiểu:** một lượt đo
gọn trong giờ nghỉ trưa ⇒ TOÀN BỘ mã volume = 0 ⇒ nhánh `traded.empty` chấm
**❌ `_FAIL` "feed đổi schema hoặc lỗi accum→delta quay lại?"** — đổ lỗi cho
feed vì cái lỗi của lịch. Đúng họ bug quen của repo: "không đo được" bị đọc
thành "đo ra kết quả xấu".

**Đã vá 20/08** — `scripts/verify_wss_live.py`:
* Hai hàm thuần mới: `quiet_phases(t0, t1)` (tên các khung KHÔNG khớp lệnh liên
  tục mà cửa sổ đo dính: ATO · NGHỈ TRƯA · ATC · sau ATC) và
  `has_continuous_matching(t0, t1)`. Biên nửa mở — chạm đúng 11:30 không tính
  là còn khớp lệnh.
* `grade(..., window=(t0, t1))`: cửa sổ KHÔNG chạm khớp lệnh liên tục thì
  all-zero xuống `_UNSURE` kèm lý do, **không** còn `_FAIL`. Chạm khớp lệnh
  liên tục mà vẫn all-zero thì giữ nguyên ❌ cứng.
* Dòng ⚠️ [1] nay nói đúng việc phải làm: dính khung nghỉ ⇒ "chạy lại
  9:15-11:30 hoặc 13:00-14:30"; trong giờ khớp lệnh ⇒ "chạy lại lâu hơn".
* In thêm dòng `Cửa sổ đo: HH:MM:SS → HH:MM:SS` — trước đây output KHÔNG hề
  nói nó đo lúc nào, nên không chẩn đoán được từ output dán lại.
* `window` là tham số TUỲ CHỌN: gọi không truyền thì giữ nguyên hành vi cũ
  (có test canh).
* Lịch phiên KHÔNG được che lỗi thật: rò volume index vẫn ❌ cứng dù đo lúc
  nghỉ trưa (có test canh).
* 13 test mới trong `tests/test_verify_wss_live.py` (11 → 24), và file này
  **được thêm vào `--fast`** — trước đó nó không nằm trong lưới nhanh.

**✅ ĐO LẠI TRONG KHỚP LỆNH LIÊN TỤC — ĐẠT CẢ 3 (20/08):**

```
Cửa sổ đo: 09:59:51 → 10:04:51  (khớp lệnh liên tục)
✅ [1] 24/30 mã cổ phiếu volume > 0 (top: HDB 31,600, FPT 24,900, SSB 8,400)
✅ [2] Index/futures volume == 0 đúng thiết kế (HNX30, HNXINDEX, VN30, VNINDEX)
✅ [3] suspect_count = 0
```

Exit 0. **Mục 1 của checklist live mode đóng.** 6 mã còn volume 0 là bình
thường cho 5 phút với nhóm cuối VN30. Lưu ý cách đọc: lượt 09:59 KHÔNG chứng
minh được lượt 120s trước đó rơi vào khung nghỉ — lượt cũ chạy bằng bản chưa in
`Cửa sổ đo` nên không truy ngược được giờ. Nó chỉ chứng minh **feed lành trong
khớp lệnh liên tục**, và từ nay mọi lượt đo đều tự khai giờ.

Còn treo: **W1 — mắt người nhìn heatmap VN30 trong phiên** (script không thay
được).

**Còn lại chưa vá (cố ý):** `_is_market_open()` trong `vnstock_wss.py` vẫn
9:00-15:00. Nó điều khiển đường CHẠY THẬT của live mode — đổi nó là đổi hành vi
sản phẩm chứ không phải sửa công cụ chẩn đoán, và giờ nghỉ trưa vẫn cần poll
giá để giữ bảng sống. Ghi lại đây, không tự ý đụng.

**`write tick ACB: [WinError 5] Access is denied`** trong cùng lượt chạy: KHÔNG
phải lỗi mới. `_atomic_write_json` (`vnstock_wss.py:432`) đã retry 6 lần
(~310ms) rồi mới ném; lỗi xếp vào `transient_markers` và tự xoá sau vòng poll
kế — đúng như quan sát (hiện ở 30s, sạch ở 45s). Nguyên nhân gần như chắc chắn
là **Dropbox**: `data_warehouse/_live/` nằm TRONG junction, mà live mode ghi đè
~38 file `quote_*.json` mỗi ~2s suốt phiên ⇒ Dropbox mở file để sync đúng lúc
`os.replace` ⇒ WinError 5. Mất 1 tick JSON là vô hại (tick sau ghi đè 2 giây
sau). Muốn dứt điểm thì đánh dấu `_live` là ignored trong Dropbox — việc cấu
hình MÁY, không phải việc code.

---


# 🎯 U19. VIETSTOCK CHẠY ĐƯỢC — VÀ PET XÁC NHẬN TOÀN BỘ CHẨN ĐOÁN LỆCH CƠ SỞ

`run.py vietstock --ticker PET --fdate 2026-01-01` trên laptop 19/08 trả về:

```
2026-07-09  bonus   Trả cổ tức năm 2025 bằng cổ phiếu, tỷ lệ 20:1
2026-07-09  bonus   Thưởng cổ phiếu, tỷ lệ 5:2
2026-01-12  cash    Trả cổ tức năm 2024 bằng tiền, 500 đồng/CP
```

**Phép kiểm khớp đến 4 chữ số.** Hai sự kiện cùng ngày GDKHQ 09/07, tính trên
CÙNG số cổ phiếu chốt quyền (không nhân dây chuyền):
`100 → +5 (20:1) +40 (5:2) = 145` ⇒ hệ số **1.45**.
Bộ chữa kho đo độc lập từ giá: **1.4499×** (vách 2026-07-07). Lệch 0,007%.

Đây là XÁC NHẬN ĐỘC LẬP cho toàn bộ chẩn đoán lệch cơ sở của ngày 19/08: hệ số
đo từ tỉ lệ kho/nguồn trùng khít hệ số tính từ sổ sự kiện quyền của một nguồn
KHÁC HẲN. Không còn là suy luận.

**Và nó chốt luôn LUẬT GHÉP** — thứ suýt làm sai nếu tự đoán: nhiều sự kiện
cùng một ngày GDKHQ thì cộng dồn trên số cổ phiếu GỐC (1.05 + 0.40 = 1.45),
KHÔNG nhân dây chuyền (1.05 × 1.40 = 1.47 — lệch 1,4%, đủ để sai).

**Về heuristic khối lượng:** bộ chữa TỪ CHỐI nhân khối lượng PET vì bậc nhảy
volume 0.43× ngược chiều hệ số giá 1.4499×. Quyết định đó ĐÚNG về mặt thận
trọng, nhưng nay biết câu trả lời thật: **hệ số phải lấy từ SỔ SỰ KIỆN, không
lấy từ bậc nhảy volume.** Volume sau sự kiện phụ thuộc thanh khoản, không phải
số cổ phiếu — dùng nó làm bằng chứng là dùng sai đại lượng.

## Hai việc mở ra từ đây (chưa làm)

**✅ (1) ĐÃ LÀM 19/08 — phần guard.** `vnstock_corp_ratio` (hàm thuần, 31
test) đọc tỉ lệ từ tiêu đề; `enforce_exdate_levels` nay in thẳng giá tham
chiếu: `VIX (Giá 13,100) … ⚠️ GDKHQ 2026-08-20 (…) — giá tham chiếu ≈ 12,476`.
PET với HAI sự kiện cùng ngày ra 29.000 → 20.000 (gộp 20:1 + 5:2 = 1.45), đúng
luật cộng dồn.

Ranh giới an toàn giữ nguyên chỗ cũ, chỉ dịch từ "không bao giờ quy đổi" sang
"không quy đổi khi ĐỌC THIẾU": `_exdate_map` nay giữ MỌI tiêu đề của ngày gần
nhất, và `combine` trả None nếu không parse được TRỌN BỘ — thiếu một vế ra
1.05 hay 1.40 thay vì 1.45, cả hai đều trông hợp lý. Loại phát hành có giá mua
(`quyền mua`, `chào bán`) bị TỪ CHỐI thẳng vì công thức cần thêm giá phát hành.

⏳ Phần còn lại của (1): dùng tỉ lệ này trong `rebase_ticker_history` để bỏ
heuristic bậc-nhảy-volume. Chưa làm — nó là công cụ GHI KHO nên đáng một lượt
riêng, và `vnstock_adjust.load_events` có cột `ratio` với ngữ nghĩa CHƯA rõ
("10:1 split → ratio=10" — không biết là ×10 hay 10 cũ ăn 1 mới), phải xác
minh trước khi tin.

**(1-cũ) Bơm tỉ lệ quyền vào guard GDKHQ + bộ chữa.** `fetch_corp_events` ĐÃ trả
`ratio` / `cash_amount` có cấu trúc. Nhưng `vnstock_events.load_upcoming` — thứ
brief thực sự đọc — lấy từ nguồn KHÁC (VCI `company.events()`) và chỉ giữ
`ticker / ex_date / title / category`, vứt phần tỉ lệ. Vá bằng cách phân tích
tỉ lệ từ chính `title` (cùng cách diễn đạt ở cả hai nguồn), THẬN TRỌNG: chỉ
nhận mẫu chắc chắn, không khớp thì giữ nguyên hành vi hiện tại (cảnh báo không
kèm số). Khi có tỉ lệ thì:
* guard GDKHQ tự quy đổi được mốc giá thay vì chỉ nói "chưa quy đổi";
* `rebase_ticker_history` hết phải đoán khối lượng bằng bậc nhảy volume.
⚠️ Cổ tức TIỀN MẶT vẫn phải xử riêng: điều chỉnh theo SỐ TUYỆT ĐỐI
(`500 đồng/CP`), không theo % giá.

**(2) `run.py cash-dividends` HỎNG:** `HTTP 404 on
https://s.cafef.vn/lich-su-su-kien/VNM.chn` — CafeF đổi URL. Nhưng Vietstock đã
trả cả sự kiện `cash` kèm số tiền/CP, nên đường CafeF có thể THỪA. Cân nhắc bỏ
hẳn thay vì sửa URL — một nguồn ít hơn là một chỗ hỏng ít hơn.

# ✅ U18. VÁ GỐC LỖ HỔNG ĐỘ TƯƠI — so CẢ GIỜ, mốc 15:05 (user chốt 19/08)

**Lỗ hổng:** `market_data_freshness` chỉ so NGÀY (`overview_date < data_date`).
Nên "độ rộng chốt lúc 11:00" và "độ rộng chốt phiên" mang CÙNG `data_date` và
cùng được coi là TƯƠI — trong khi brief chiều mô tả cả phiên còn khối độ rộng /
VN30 movers / dòng tiền ngành / regime mới thấy nửa buổi sáng. Đây chính là thứ
phải kiểm bằng TAY suốt (mục "Bước 2" trong sổ việc).

**Vá:** thêm `SESSION_CLOSE_CUTOFF = time(15, 5)` + `_market_overview_generated_at`
đọc `generated_at` ĐẦY ĐỦ CÓ GIỜ (chấp nhận `"%Y-%m-%d %H:%M:%S"` mà
`vnstock_runner` đang ghi, bản không giây, và ISO có `T`). `market_data_freshness`
nay trả thêm `reason` + `overview_time`, với HAI kiểu cũ:
* `prev_session` — luật cũ, so ngày.
* `intraday` — cùng phiên nhưng chốt TRƯỚC 15:05.

**Hai chốt chống báo động giả** (nới quá tay thì sáng nào cũng kêu, và người
đọc học cách bỏ qua cảnh báo — hỏng còn nặng hơn):
1. Chỉ tính `intraday` khi overview được ghi ĐÚNG trong ngày phiên đó. Ghi ở
   NGÀY SAU (chạy bù sáng hôm sau từ data EOD) thì nó đã thấy trọn phiên.
2. Không có `generated_at` / parse không ra → rơi về luật ngày như cũ, KHÔNG
   biến thành "luôn stale".

**Câu cảnh báo trong prompt tách làm hai.** Mượn câu "PHIÊN TRƯỚC" cho ca giữa
phiên là nói SAI sự thật; câu mới nói rõ "chốt lúc HH:MM — GIỮA PHIÊN, chưa
thấy hết phiên" và yêu cầu brief ghi mốc giờ đó. Có test canh cả hai chiều.

**⚠️ Tôi lại vấp đúng lỗi vừa chê — lần thứ HAI trong ngày.** Hai test mới
thêm vào `tests/test_brief.py` viết file overview KHÔNG có `data_date`, nên
`_market_overview_data_date` rơi về `_warehouse_eod_date()` — hàm đọc **KHO
THẬT**. Container không có giá nên trả None → test xanh; máy user có kho nên
trả `2026-08-19` → test đỏ. Đúng họ lỗi của `test_tests_badge_states` (đỏ theo
GIỜ TRONG NGÀY) mà tôi vá ban sáng, chỉ đổi từ "phụ thuộc đồng hồ" sang "phụ
thuộc kho".

Cách né: ghi `data_date` THẲNG vào file test để không bao giờ chạm đường
fallback. Test cạnh bên né bằng `monkeypatch` `_warehouse_eod_date` — cũng
được, nhưng ghi thẳng thì không phụ thuộc tên hàm nội bộ.

**Quy tắc rút ra, áp cho mọi test sau này:** test nào chạm hàm có đường rơi về
đọc kho / đọc đồng hồ / đọc mtime repo thì phải CẮM giá trị, không được để nó
tự đi tìm. Xanh trong container ≠ xanh trên máy thật, và cái giá phải trả là
một phát pipeline chết ở bước 9.

**Một test cũ phải sửa vì nó ENCODE chính cái bug:**
`test_market_data_freshness_fresh_when_same_day` khẳng định overview 11:00
cùng ngày là "tươi". Đổi thành 18:30 (sau mốc) + thêm test riêng cho ca 11:00
phải stale.

Lưới: `tests/test_brief_freshness_intraday.py` 17 test, đã vào `--fast`.
Suite: 2.337 passed (fast 1.838).

# 🌐 U17. NSO ❌ / JINA ⚠️ — HỎNG TRÊN CẢ HAI MÁY (19/08)

`doctor --net` trên desktop `PICHU`: **28 ✅ · 1 ⚠️ · 1 ❌** — hỏng đúng hai
nguồn y như laptop. ⇒ **Loại giả thuyết "chính sách mạng laptop"**, thứ đã treo
từ sáng.

⚠️ Nhưng KHÔNG được kết luận "nguồn hỏng thật": hai máy nhiều khả năng chung
một đường ra internet nên phép thử không độc lập. Phép thử độc lập rẻ nhất:
phát 4G từ điện thoại rồi chạy lại `doctor --net`.

**Xếp mức khẩn theo HẬU QUẢ, không theo màu badge:**
* **Jina ⚠️ — không gấp.** Mất fulltext thì tin chỉ chấm bằng title+summary;
  brief 19/08 vẫn có 43 tin gắn tác động. Tắt hẳn: `VNSTOCK_NEWS_FULLTEXT=0`.
* **NSO ❌ — có HẠN.** CPI / IIP / GDP / cán cân thương mại đang dùng cache
  `as_of 2026-07-31`. Kỳ công bố tháng 8 rơi cuối tháng; không kéo được kỳ đó
  là brief bắt đầu nói số vĩ mô CŨ mà không ai biết (doctor chỉ báo nguồn
  fetch hỏng, không báo "số trong brief đã lỗi thời"). Còn ~2 tuần.

**Quan sát phụ đáng theo dõi, chưa phải việc:** badge LLM ledger ghi
`hôm nay 36 call · 12 lỗi` — tỉ lệ lỗi 33%. Bậc thang model có fallback nên
lỗi rồi rơi bậc là chuyện bình thường, nhưng 1/3 là cao. Nếu tuần tới vẫn vậy
thì đáng soi bậc nào đang chết.

**Hai badge MỚI đã sống và đang xanh** ở lượt này: "Lệch cơ sở — mã bị cách ly"
và "Nới OHLC (bar tự mâu thuẫn)". Chưa có sync nào chạy sau khi merge nên xanh
là đúng — đêm 20/08 mới là lần đầu chúng có cơ hội kêu.

# 🎯 U16. AUTO-HEAL LÀ KẺ ĂN THỜI GIAN — đã chặn trần, chưa chữa gốc

Số đo 19/08: `auto-heal 2.156,7s` = **35,9 phút = 83% bước sync và 51% cả
phát**. Nghi phạm cũ trong sổ (`fix-units` quét toàn kho) chỉ 98s = 1,6%.

**Đã làm (chặn thiệt hại):** `auto_heal(..., time_budget_s=AUTO_HEAL_BUDGET_S)`
— mặc định **600s**, env `VNSTOCK_AUTOHEAL_BUDGET_S` chỉnh được, `0` = tắt
trần. Hết giờ thì dừng TRƯỚC một lần gọi mạng mới (không cắt giữa chừng một
mục), trả `stopped_early` + `remaining`, và `run.py` in ra hàng đợi còn bao
nhiêu. Cắt được vì `auto_heal` idempotent: mục chưa xử lý còn nguyên trong
hàng đợi, đêm sau chạy tiếp. Trần này đưa worst case của `sync` từ 43 phút
xuống ~17 phút.

**ĐÃ CÓ SỐ — và nó chỉ thẳng vào chỗ phải chữa** (`run_daily.log:6908`):

```
[sync] auto-heal: scanned=3844 healed=35 retry_bumped=3809 archived=0
```

**99,1% lượt gọi mạng là vô ích.** 2.156,7s / 3.844 ≈ 0,56s mỗi mục. Và
`archived=0` nghĩa là chưa mục nào cạn lượt — tức mỗi mục trong 3.809 mục
trượt đó còn phải đốt thêm `MAX_RETRIES=3` ĐÊM × 36 phút nữa mới được dọn.

**Đã vá (chữa đúng gốc, không phải tăng tốc vòng lặp):** `refetch` vốn phân
biệt hai loại trượt mà `auto_heal` lại gộp làm một —
* `fail` + `"no row for target date"` = nguồn TRẢ LỜI được, đưa về các bar
  quanh ngày đó, nhưng THIẾU đúng ngày ấy ⇒ **vắng có cấu trúc** (mã chưa
  niêm yết, tạm ngừng, ngày không giao dịch). Đêm mai hỏi lại chắc chắn cũng
  vậy ⇒ nay **dọn NGAY**, có ghi vết vào `remediation_log.jsonl`.
* `fail` + `"API returned empty"` = không có gì trong CẢ cửa sổ 5 ngày ⇒ MƠ HỒ,
  có thể là outage ⇒ giữ nguyên đường thử-lại 3 lượt. Dọn ngay ở đây là một
  đợt outage xoá sạch hàng đợi.
* `error` (timeout/exception) = nhất thời ⇒ giữ nguyên đường thử-lại.

`archive_exhausted=False` chặn CẢ hai đường dọn. `run.py` in riêng số mục dọn
vì vắng cấu trúc.

**ĐÃ ĐẾM `remediation_log.jsonl` — và nó đổi trọng tâm.** Tổng lịch sử:

| Lý do | Số lần |
|---|---|
| `API returned empty` | **84.897** |
| `retries=3 exhausted; original reason: low > min(open, close, high)` | 19.180 |
| `no row for target date in response` | **18.070** |
| `retries=3 exhausted; … low must be <= min(open, close, high)` | 12.177 |
| `retries=3 exhausted; high < max(open, close, low)` | 2.792 |
| whitelist (`zero_vol_move` / `gap` / `ohlc`) | ~3.100 |

**1. Bản vá "vắng cấu trúc" chỉ chạm ~18% lượt trượt.** `no row for target
date` là 18.070; bucket lớn nhất `API returned empty` (84.897) thì CỐ Ý không
dọn ngay vì nó mơ hồ với outage. Vá vẫn đúng, nhưng đừng kỳ vọng `sync` co lại
ngay.

**2. NGUỒN BƠM đã lộ mặt: vi phạm hợp đồng OHLC.** Dòng `retries=3 exhausted`
ghi kèm LÝ DO GỐC lúc bị cách ly, và ~34.000 trong số đó là
`low > min(open, close, high)` / `high < max(open, close, low)` — bar có `low`
CAO HƠN giá thấp nhất trong (open, close), hoặc `high` THẤP HƠN giá cao nhất.
Bar tự mâu thuẫn.

Và đây là chỗ vòng lặp vô nghĩa: bar bị cách ly vì mâu thuẫn NỘI TẠI ⇒
`refetch` gọi lại **cùng nguồn** ⇒ nhận **cùng bar mâu thuẫn** ⇒ trượt hợp
đồng lần nữa. Chỉ lành khi nhà cung cấp tự sửa dữ liệu — đo được **35/3.844
= 0,9%**.

**✅ USER CHỌN (a) — ĐÃ LÀM 19/08: `vnstock_ohlc_repair`.**
Nới ngay ở `_write_year`, TRƯỚC khi hợp đồng phán:
`low := min(low, open, close)` · `high := max(high, open, close)`.
Lập luận vì sao không phải bịa số: giá trị mới CHÍNH LÀ `open` hoặc `close` —
mức đã KHỚP trong phiên. Bar nói "thấp nhất là X" mà có lệnh khớp dưới X thì
mâu thuẫn nằm ở X, không nằm ở lệnh đã khớp.
Trần `MAX_WIDEN_PCT = 20%`: biên độ một phiên ở VN tối đa ±15% (UPCoM), nên cần
nới hơn thế là feed HỎNG chứ không phải bar dở ⇒ KHÔNG sửa, để cách ly như cũ
(có test canh: bar cần nới 190% phải đi nguyên vẹn vào hàng đợi).
Ghi vết `_meta/ohlc_repairs.json` (cap 500 ca, `total` vẫn đếm tiếp) + badge
doctor `check_ohlc_repairs` (tự im sau 7 ngày để khỏi alarm fatigue) +
kill-switch `VNSTOCK_OHLC_REPAIR=0` đã vào danh sách cờ nguy hiểm của doctor.
Lưới: `tests/test_ohlc_repair.py` 21 test, đã vào `--fast`.

**Hai đường đã cân nhắc (giữ lại để biết vì sao chọn (a)):**
* **(a) Vá tại đường ghi** — chuẩn hoá tối thiểu `low = min(low, open, close)`,
  `high = max(high, open, close)`. Bar tự mâu thuẫn thì phép sửa nhỏ nhất và
  đúng nhất là NỚI low/high để bao được open/close. Sau đó bar qua hợp đồng,
  không vào hàng đợi, 36 phút/đêm biến mất. Đổi lại: ta ĐANG SỬA số của nhà
  cung cấp — phải ghi vết từng ca, đúng nếp `unit_normalizations.json`.
* **(b) Thôi refetch loại vi phạm hợp đồng** — rẻ, không đụng dữ liệu, nhưng
  chỉ chặn lãng phí chứ bar vẫn thiếu trong kho.

**✅ Đã loại giả thuyết "đường fetch hỏng"** (19/08 23:10):
`VnStockWarehouse._fetch_price("VNM", "2026-08-11", "2026-08-15")` trả **4 bar
đúng**. Đường fetch tốt ⇒ 84.897 lần rỗng là mã hủy niêm yết / ngày cũ THẬT,
không phải trục trặc hạ tầng. Vòng auto-heal gọi đúng nguồn, chỉ là hỏi những
câu đã biết trước câu trả lời.

**🔍 Phép thử đó lộ thêm CƠ CHẾ Dropbox**, thứ cả ngày chỉ suy được gián tiếp:
lệnh in ra `📦 Warehouse: E:\Dropbox\vnstock_data\data_warehouse` trong khi
tham số truyền vào là `root="data_warehouse"` và cwd là `C:\vnstock`. Code chỉ
làm `Path(root).resolve()`, mà `resolve()` ĐI THEO junction/symlink ⇒
`C:\vnstock\data_warehouse` là một liên kết trỏ sang `E:\Dropbox\...`.

**✅ Xác nhận bằng `Get-Item` (19/08 23:1x):** `LinkType: Junction`,
`Target: E:\Dropbox\vnstock_data\data_warehouse`. Không còn suy diễn.

Hệ quả cho mọi suy luận trước đó: **KHO đồng bộ, CODE thì không.** Repo đi
bằng git (khớp reflog: mỗi máy tự `git pull`), `run_daily.log` nằm ở GỐC REPO
nên là nhân chứng RIÊNG của từng máy — đúng như đã dùng nó để đối chiếu.
`_meta/*.json` (marker, badge) nằm trong kho nên đồng bộ — đúng như đã ghi.

**`_meta/backup_rebase/` nằm trong Dropbox — ĐÃ ĐO, KHÔNG ĐÁNG LÀM GÌ.**
Tôi có nêu lo ngại: mỗi `rebase --apply` là một `copytree` nguyên thư mục mã,
19/08 đẻ 77 thư mục, tất cả đẩy lên mây và kéo sang máy kia, không module nào
dọn. Đo ra: **10,4 MB cho cả 77 thư mục** (~135 KB/mã). Với nhịp đó thì cả năm
chữa kho cũng chỉ vài trăm MB.
⇒ **Bỏ cả hai đề xuất** (chính sách giữ N ngày · đưa ra ngoài junction). Ghi
lại đây kèm số để không ai đào lên lần nữa. Lệnh đo nếu cần kiểm lại:
`"{0:N1} MB" -f ((Get-ChildItem C:\vnstock\data_warehouse\_meta\backup_rebase -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)`

# ✅ U15. #32 CHẤM LẠI TRÊN KHO ĐÃ CHỮA — VẪN ĐẠT (19/08 21:2x)

`vnstock_train.py --strategy-only --tier both --mode tune` trên kho sạch:

```
tier=short    → strategy_id=16 status=active trades=None expectancy=None
                kiểm định: ⏳ chưa đủ lệnh để chấm
tier=position → strategy_id=32 status=active trades=39 expectancy=3.0188
                exit mix: TP 51% · SL 44% · hết hạn 5%
                kiểm định: ✅ ĐẠT (p=0.012) → rec SẼ vào brief
```

**Kết luận chính: edge của #32 KHÔNG phải sản phẩm của bậc giả.** Nó sống sót
qua việc chữa 76 mã. Cảnh báo "mọi verdict trước 19/08 là VÔ HIỆU" **gỡ bỏ**
cho #32; các verdict khác vẫn phải chạy lại mới tính.

**KHÔNG được đọc n: 94 → 39 là "58% lệnh cũ là artifact".** `--mode tune` chỉnh
lại tham số CÙNG LÚC với việc dữ liệu đổi ⇒ hai biến động một lượt, không tách
được. Lịch sử #32 vốn đã nhảy 67 → 19 → 94 → 39 qua các vòng tune, nên số lệnh
biến động theo tham số là chuyện thường. Muốn đo riêng ảnh hưởng của việc chữa
kho thì phải chạy THAM SỐ CŨ trên DỮ LIỆU MỚI — chưa làm.

**39 lệnh chỉ hơn sàn 30 đúng 9.** Mẫu mỏng; một vòng tune xấu là tụt xuống
dưới sàn và mục khuyến nghị tắt.

**p=0.012 trùng khít con số cũ — là NGẪU NHIÊN, không phải giá trị cũ còn sót.**
`monte_carlo_pvalue` seed cố định 42, `_MC_SIMS = 1000` nên p = (k+1)/1001, tức
bội của ~0.001; in 3 chữ số thì cả k=11 lẫn k=12 đều ra "0.012". Metrics là bản
tươi (trades/expectancy đều khác lần trước) nên p cũng tươi. Ghi ra đây để lần
sau không ai đọc nhầm thành "chấm lại mà không đổi gì".

**Exit mix qua cổng "TP với tới được"**: 51% lệnh đóng chạm TP, xa trên ngưỡng
`_TP_REACH_MIN_SHARE = 0.05`. Nghĩa là TP nằm trong tầm với thật của horizon 20
phiên, không phải R:R đẹp trên giấy.

**⚠️ Tầng NGẮN (#16) đang trắng** — `trades=None`, "chưa đủ lệnh để chấm". Tầng
5 phiên hiện không đóng góp khuyến nghị nào vào brief; chỉ tầng vị thế chạy.
Chưa rõ là tune không sinh ứng viên mới hay backtest không ra lệnh nào. Đáng
soi, không chặn gì.

# ✅ U14. KHO ĐÃ SẠCH LỆCH CƠ SỞ — 160/160 mã, 19/08 21:17

`probe_price_basis --sweep` trên desktop `PICHU`: **"✅ 160 mã: tỉ lệ kho/nguồn
KHÔNG đổi bậc"**. Đóng mục U10 (70/159 mã lệch) sau một ngày.

**Tổng cộng đã chữa 76 mã**: 70 mã lượt `--from-sweep` (laptop 15:43, Dropbox
đưa sang desktop) + VVS + VNM (chữa lẻ trước đó) + VTP + QNS (cần bản vá đa
bậc) + HHP + NTP (nảy ra tối 19/08).

**HHP là bằng chứng SỐNG rằng cơ chế vẫn đang chạy.** Lượt quét 17:45 soi 159
mã và HHP (GTGD20 18,2 tỷ) sạch. Lượt 21:09 nó lệch `1.0650×` vách
`2026-08-13`. Giữa hai mốc chỉ có một việc: **pipeline chạy 18:00-18:43 trên
code `65ec935`, TRƯỚC khi V1 được merge**. Tức chính `sync` tối đó nối bar cơ
sở mới lên lịch sử cơ sở cũ — đúng cơ chế vừa dựng lại vài giờ trước.
⇒ Đo được nhịp thật: **~1 mã/đêm trong mùa cổ tức**. Từ phát 20/08 (đã merge
V1) tình huống này thành "từ chối nối + vào sổ cách ly + badge doctor".

**NTP thì khác — nó không mới.** Universe nhích 159 → 160 mã (số mã dưới ngưỡng
1.564 → 1.563) vì cửa sổ GTGD20 trượt một phiên và NTP (5,4 tỷ) vượt ngưỡng lọc
5,0 tỷ. Vách `2026-06-05` vốn có từ lâu, chỉ nằm dưới bộ lọc thanh khoản.
⇒ **Ngưỡng GTGD của bộ quét là một điểm mù có thật**: mã lệch nằm ngay dưới
ngưỡng vẫn vào được backtest khi thanh khoản nhích lên. Đáng cân nhắc hạ ngưỡng
quét (chi phí: mỗi mã 1 lần gọi nguồn) hoặc quét định kỳ toàn bộ mã cổ phiếu.

**NTP cũng là mã duy nhất trong cả đợt được NHÂN khối lượng đúng lý do đầy đủ**:
bậc volume 1,20 khớp cỡ hệ số giá 1,2305 (tỉ lệ 0,97) VÀ hệ số đủ lớn để loại
trừ cổ tức tiền mặt. Cùng đợt, HCM/KLB/SSB nhân theo bằng chứng volume; HHP giữ
nguyên vì bậc 1,69 lệch cỡ hệ số 1,065.

**Hệ quả mở khoá:** nay mới được phép chạy lại backtest/kiểm định. Mọi verdict
trước 19/08 (kể cả #32 p=0.012, n=94) coi như VÔ HIỆU cho tới khi
`vnstock_train.py --strategy-only --tier both --mode tune` chạy trên kho này.

# ✅ U13. ĐÃ VÁ — watchlist nay biết ngày GDKHQ của chính mã nó nêu

Bắt được ở brief chiều 19/08 (gửi tay 20:41). Cùng một brief chứa hai khối
mâu thuẫn nhau:

* **Watchlist sáng mai** — `VIX (Giá 13,100) — GIẢM TỶ TRỌNG/TRÁNH nếu thủng
  12,700 · mục tiêu về 12,000 · hủy nếu vượt lại 13,500 — "Áp lực bán gia tăng
  trước ngày giao dịch không hưởng quyền."`
* **Sự kiện sắp tới** — `VIX: Trả Cổ tức bằng Cổ phiếu tỉ lệ 5.0% — ngày
  2026-08-20` kèm đúng câu cảnh báo `(Giá tự điều chỉnh trong ngày GDKHQ —
  không phải giảm do thị trường.)`

**Số học:** 13.100 × 100/105 = **12.476**. Giá tham chiếu mở cửa 20/08 nằm
DƯỚI ngưỡng 12.700 ⇒ tín hiệu "thủng 12.700" kích hoạt **cơ học ngay lúc mở
cửa**, không phải do bán. Mốc hủy 13.500 thành xa 8% — bất khả. Toàn bộ setup
vô hiệu, mà câu diễn giải còn quy nhân quả sai ("áp lực bán").

**Vì sao lọt:** khối canon ĐÃ có cảnh báo GDKHQ, nhưng nó nằm ở mục Sự kiện và
KHÔNG lan sang mục Watchlist. Guard hiện có canh "nói đúng chuyện" trong từng
mục, chưa có guard nào canh NHẤT QUÁN GIỮA HAI MỤC.

**Đã làm:** `enforce_exdate_levels` (guard thứ 47, ở `_guards_sections`, nối
vào `apply_brief_guards` ngay sau `enforce_watchlist_eligibility`). Gắn cảnh
báo INLINE vào đúng dòng setup: `· ⚠️ GDKHQ 2026-08-20 (<tên sự kiện>) — giá
tham chiếu tự điều chỉnh, mốc trên CHƯA quy đổi`.

Hai ngưỡng ngày lịch, cố ý khác nhau: watchlist **3 ngày** (kịch bản cho phiên
kế tiếp, 3 ngày phủ T6→T2) · đề xuất/khuyến nghị **14 ngày** (horizon 5-20
phiên). Kêu cho watchlist về quyền 10 ngày nữa là alarm fatigue.

**Cố ý KHÔNG tự quy đổi mốc giá.** Tỉ lệ quyền chỉ nằm trong CHỮ của `title`,
mà cổ tức TIỀN MẶT điều chỉnh theo MỆNH GIÁ (tỉ lệ × 10.000đ) chứ không theo %
giá — đoán sai chỗ đó còn hại hơn không đoán, và hôm nay đã có đủ bài học về
việc suy diễn từ dữ liệu mỏng. Quy đổi tự động chờ kho sự kiện có tỉ lệ dạng
SỐ. Có test canh đúng điều này (`test_guard_does_not_invent_an_adjusted_price`).

Lưới: `tests/test_brief_exdate_guard.py` 16 test, đã vào `--fast`.

**Vá kèm — độ chính xác giá hiển thị.** `_fmt_rec_price` giữ thập phân khi giá
< 10 rồi cắt sạch từ 10 trở lên, mà phần lớn cổ phiếu VN nằm dải 10-100: brief
in `SBT entry=24 TP=25 SL=23` trong khi sổ ghi TP +7,4% / SL −2,7% trên entry
≈ 23,5 (TP thật ≈ 25,2). Sai 0,5 nghìn trên mục tiêu 7,4% là hơn một phần tư
biên lợi nhuận, và lệch cả hai chiều BẤT LỢI: chốt lời sớm, cắt lỗ sát hơn ý
đồ. Nay giữ 1 chữ số thập phân cho dải 10-100 (bỏ đuôi ".0"), sai số ≤0,5%.

# ⚠️ U13b. 6 khuyến nghị đang mở đứng trên kiểm định TRƯỚC khi chữa kho

Brief 19/08 nêu SCL/SBT/PVP/MSR/HTN/GMD và 4 lệnh ẩn "chiến lược nguồn chưa
đạt kiểm định". Kho giá ĐÃ được chữa (68/70 mã) nhưng
`vnstock_train.py --strategy-only` CHƯA chạy lại — phát 19/08 chết ở bước 9
nên `train` không được gọi. Nghĩa là các chiến lược phát ra 6 lệnh này vẫn
mang verdict chấm trên dữ liệu có bậc giả. Chưa chạy lại thì mọi lệnh mới đều
thừa hưởng nguyên vẹn cảnh báo "verdict trước 19/08 là VÔ HIỆU".

# 📏 U12. ĐÃ ĐO ĐƯỢC: `sync` 43 phút — 84% là AUTO-HEAL, không phải fix-units

Phát 19/08 18:00 trên desktop `PICHU` (code `65ec935`), dòng `[sync] ⏱ CHẶNG`
lần đầu có số thật:

```
auto-heal  2,156.7s  (35.9 phút — 83,4% của sync)
updater      302.2s  ( 5.0 phút)
fix-units     98.1s  ( 1.6 phút)
rollup        27.6s  ( 0.5 phút)
[sync] ⏱ CHẶNG 43.1 phút
```

**Nghi phạm cũ SAI.** Việc #0 trong sổ ghi "nghi phạm số 1: `fix-units` quét
TOÀN KHO mỗi đêm" — đo ra `fix-units` chỉ 98 giây, tức **1,6%**. Kẻ ăn thời
gian là `auto-heal` (`vnstock_quarantine.auto_heal`), và nó gọi MẠNG theo từng
bar bị cách ly (`vnstock_quarantine.py:284,337` → `vnstock_remediate.refetch`)
— đó mới là chỗ đáng mổ. Câu hỏi tiếp theo phải hỏi: hàng đợi cách ly có bao
nhiêu bar, và có phải đêm nào cũng thử lại đúng những bar không bao giờ lành?

Tổng cả phát: **70,7 phút / 9 bước** — `sync 2.585s · screener 1.251s ·
news 134s · validate 123s · test 69s · macro 65s · foreign-flow 14s ·
allocation 2s · gold 2s`. `screener` 21 phút là chi phí số 2.

## Phát này chết ở bước 9 `test` (rc=2), KHÔNG phải chạm trần

`LastTaskResult = 2` (đúng exit code fail cứng của `run.py`), không phải
`267014 = 0x41306` (task bị chấm dứt). Trần vẫn đang là `PT2H` — **chưa nâng**
— nhưng 70,7 phút còn xa 120. Ước tính đủ 14 bước: +train 230s +audit 142s
+reflection 14s ≈ **77 phút**, vẫn dưới trần.

⇒ **Nâng trần lên PT180M nay là BẢO HIỂM, không phải bản vá.** Vẫn nên làm vì
`auto-heal` biến động mạnh, nhưng đừng coi nó là nguyên nhân mất brief.

## Nguyên nhân thật sự: một test đỏ trên máy thật

Bước `test` chạy full suite và trả rc=2 ⇒ `cmd_all` dừng cứng ⇒ train /
reflection / doctor / **brief** không bao giờ được gọi. Đây là ĐÊM THỨ HAI
chết đúng bước 9 vì cùng cơ chế.

**✅ ĐÃ XÁC NHẬN bằng log** (`run_daily.log:74584`):
```
FAILED tests/test_doctor.py::test_tests_badge_states - AssertionError: assert...
1 failed, 2235 passed, 3 warnings in 66.78s
```
2.235 + 1 = **2.236, khớp ĐÚNG số của container** ở cùng commit — máy thật và
CI đồng ý từng test một, đóng nốt nỗi lo "máy thật có test bị env chặn".

Test đó là `test_doctor::test_tests_badge_states` — nó cắm `ran_at = hôm nay 10:00` rồi
để `_code_changed_after` quét mtime file repo THẬT, nên hễ có file .py nào đổi
sau 10:00 là đỏ. User `git pull` lúc **17:37** ⇒ toàn bộ file merge mang mtime
17:37 ⇒ test đỏ ở phát 18:00. Tôi vấp đúng lỗi này trong container lúc 11:51
và đã vá ở `5ac88e4`, nhưng bản vá lên sau khi user merge nên phát tối nay
chạy code CHƯA có nó.

**Lỗi này do CHÍNH TÔI gây ra.** `_code_changed_after` thêm ở `0a3e785`
(badge "code đã đổi sau lần chạy test") biến một test sẵn có thành phụ thuộc
GIỜ TRONG NGÀY, mà tôi không nhận ra cho tới khi tự vấp lúc 11:51. Tính năng
badge vẫn đáng giữ — cái sai là để nó quét mtime repo THẬT trong test.

**Bài học vận hành:** merge lúc 17:37 rồi để phát 18:00 chạy full suite là
đúng cửa sổ nguy hiểm nhất — bước 9 biến mọi test đỏ thành "mất brief". Muốn
an toàn thì merge xong chạy `python run.py test` NGAY, đừng đợi task tự chạy.
Quy tắc: **merge → test xanh → mới để máy chạy lịch.**

# 🔴 U11. KHO HAI MÁY DÙNG CHUNG QUA DROPBOX — GHI CHÚ CŨ SAI, ĐÃ SỬA 19/08

**Kết luận cuối, sau khi hỏi user:** `C:\vnstock` VẪN được Dropbox đồng bộ
giữa desktop `PICHU` và laptop `CFA-BINHLD-LT`. Dòng trong `CLAUDE.md` nói
"đã bỏ Dropbox, hai kho ĐỘC LẬP" là **SAI**, và nó là nguyên nhân gốc của
chuỗi quy sai máy + gán nhãn sai suốt ngày 19/08.

**Đường suy luận sai của tôi, ghi lại để không lặp:** thấy 77 thư mục
`backup_rebase` có tên đóng dấu 15:43–15:48 mà `CreationTime` 17:39 → kết luận
"chép tay". Đúng dữ kiện, sai diễn giải: Dropbox **tải file xuống** thì file
nhận `CreationTime` lúc tải, còn TÊN thì do bên gửi đặt. 25.940 file khác giữ
ngày tạo cũ vì chúng không đổi nên Dropbox không tải lại — con số đó tôi từng
đọc là "phần lớn kho là bản gốc, vậy chép rất hẹp", trong khi nó chính là chữ
ký của ĐỒNG BỘ THEO DELTA. Bài học: một hạ tầng không đọc được từ code thì
đừng suy từ timestamp — HỎI.

**Hệ quả tốt:** chữa kho làm **MỘT LẦN** là đủ, máy kia tự có. Mọi nhãn
"⇄ CẢ HAI MÁY" gán cho việc chữa kho trong ngày đều thừa.

**Hệ quả phải nhớ:**
* Marker + badge cũng đi theo kho: `test_status.json` / `doctor_status.json`
  KHÔNG có trường máy ⇒ badge sidebar có thể là kết quả của MÁY KIA.
  `brief_push.json` chạy ở laptop ⇒ desktop câm brief tối đó mà vẫn `return 0`.
* **Đừng đụng kho ở máy kia trong lúc pipeline chạy.** Hai bên ghi cùng file là
  Dropbox sinh `... (conflicted copy).parquet` nằm NGAY trong `prices/`.
  ⚠️ **Tôi đã nói SAI ở đây lúc đầu ("chưa có guard nào chặn") — repo xử chuyện
  này từ lâu và xử đúng:** `vnstock_parquet_io.read_year_frames` gộp MỌI file
  (không mất phần data nằm ở bản kia), `vnstock_updater._read_year` khử trùng
  ngày giữ bản mtime mới nhất, `_write_year` dồn year-dir về đúng 1 file, và
  `vnstock_health` báo year-dir nào có >1 file (`run.py scan`, có test riêng).
  Lỗ hổng THẬT chỉ nằm ở đường ĐỌC PHÂN TÍCH: `vnstock_strategy.
  _load_history_from_parquet` (loader của backtest) nối thẳng mọi file, KHÔNG
  khử trùng ⇒ bar nằm ở cả hai file bị đếm HAI LẦN, n_trades và Sharpe sai mà
  không dấu hiệu gì. Đã vá 19/08 (`tests/test_conflicted_copy_reads.py`).
* `write_table_atomic` / `write_json_atomic` (`vnstock_parquet_io.py:76-108`)
  **không có retry**, trong khi `vnstock_wss.py:455-467` và
  `vnstock_quarantine.py:94-110` thì có. Trên Windows, Dropbox giữ handle lúc
  `os.replace` ⇒ `PermissionError` ⇒ mất đúng lần ghi đó.

**Cửa `--skip-if-done` GIỮ hành vi gốc.** Nó cố ý bỏ qua khi máy khác đã sync
hôm nay — với kho dùng chung thì đó là ĐÚNG, và đó là cấu hình thật. Tôi đã
đổi mặc định thành "đòi đúng tên máy" khi còn tin ghi chú sai, nay **trả lại
mặc định cũ**; ai tách kho riêng thì bật `VNSTOCK_INDEPENDENT_WAREHOUSE=1`.
Lưới `tests/test_pipeline_status_gate.py` canh CẢ HAI chế độ.

# 🗄️ U11b. (giữ lại) SỔ LỆNH ĐÃ KIỂM — KHÔNG MẤT

**Bằng chứng, không phải suy đoán:** 77 thư mục `_meta/backup_rebase` trên
desktop `PICHU` có TÊN đóng dấu `20260819-1543..1548` (giờ lượt `--apply`
chạy) nhưng `CreationTime` là **17:39**, trải đúng 17 giây — chữ ký của một
lượt chép hàng loạt. `shutil.copytree` lúc rebase chạy thật thì CreationTime
phải là 15:43. ⇒ Lượt chữa 70 mã chạy trên LAPTOP; kho được chép sang desktop
lúc 17:39, **21 phút trước phát 18:00**.

Việc này GIẢI câu hỏi treo ở `VIEC-DANG-LAM.md` ("vì sao desktop quét ra đúng
2 mã với đúng bộ đếm universe của laptop"). Kết luận: **một lần chép tay, KHÔNG
phải hai kho tự đồng bộ.** Dòng "hai kho KHÔNG tự đồng bộ" trong `CLAUDE.md`
vẫn đúng.

## ✅ ĐÃ KIỂM — sổ lệnh KHÔNG mất

Chép là **đè vào cây có sẵn**, không phải mirror: 4 thư mục gốc của
`data_warehouse` (`prices` / `_meta` / `companies` / `_live`) đều giữ
CreationTime tháng 4/2026, tức không bị xoá và tạo lại.

`brief_memory.db` đọc ra (19/08, mode=ro): **805 briefs · 37 strategies ·
71 backtests · 148 recommendations · 138 rec_outcomes**, `brief cuối
2026-08-18T23:16:05` — ĐÚNG bản close brief desktop gửi tay tối 18/08, và
`rec cuối 2026-08-18T23:08:51` cùng phiên đó. Laptop chưa bao giờ sinh brief
⇒ đây là sổ THẬT của desktop, không bị thay. 138 outcome cũng khớp mạch với
n=94 của verdict #32 (thêm lệnh đã đóng từ đó tới nay).

Suy ra lượt chép 17:39 chỉ đụng `prices/` + `_meta/backup_rebase` +
`basis_sweep_check.json`, không đụng DB.

**Mốc thời gian dựng lại được từ reflog + CreationTime:**
17:37:47 `git pull` (fast-forward tới `65ec935`) → ~17:39 chép kho từ laptop →
17:45 quét `--sweep` ra 2 mã → 18:00 task đêm khởi động. Merge nằm TRƯỚC
18:00 nên phát tối nay chạy MỘT bản code nhất quán, không có cảnh nửa cũ nửa
mới.

## Cái giá suýt phải trả: `brief_memory.db` là kho DUY NHẤT, KHÔNG tái tạo được

`data_warehouse/_meta/brief_memory.db` (`vnstock_memory.py:26`) giữ 5 bảng —
`briefs` / `strategies` / `backtests` / `recommendations` / `rec_outcomes` —
và **kết quả kiểm định nằm trong `backtests.metrics_json["validation"]`**
(`vnstock_strategy.py:1066`), tức verdict #32 cũng ở đây. Không module nào
backup file này (quét toàn repo: chỉ `rebase_ticker_history` backup thư mục
giá). Rec là ẢNH CHỤP QUYẾT ĐỊNH tại thời điểm phát — không suy ngược được từ
kho giá. Đóng lệnh là MỘT CHIỀU (`rec_outcomes.rec_id` UNIQUE, không có đường
mở lại — `vnstock_memory.py:106-113`, comment `vnstock_train.py:604`).

Desktop mới là máy sinh khuyến nghị; laptop chỉ chạy thử. Nếu bản chép đè DB
thì sổ lệnh thật bị thay bằng sổ thử nghiệm — **mất vĩnh viễn**.

Cùng nhóm không-tái-tạo-được, và cả 3 agent soi đầu đều bỏ sót: **file người
dùng nhập tay** trong `_meta` — `portfolio.json`, `watchlist.json`,
`price_alerts.json`, `reports_index.json` + `reports/<id>.txt|pdf`,
`sizing_config.json`, `allocation_config.json`, các whitelist. Và **bar phút
WSS** `_live/bars_*.parquet` (+ `archive/` 30 ngày) — WSS không phát lại quá
khứ, chỉ vá được bằng 1 bar tổng hợp giả (`vnstock_wss_backfill.py:100-152`).

## ✅ Đã vá NGAY: cửa `--skip-if-done` nay so cả TÊN MÁY

`is_already_done_today` (`vnstock_rollup.py`) trước chỉ so ngày + kết quả.
`pipeline_status.json` nằm TRONG kho nên đi theo bản chép ⇒ chỉ cần chép kho
là máy nhận tự bỏ qua **cả sync lẫn rollup**, in "✓ đã chạy hôm nay bởi máy
X" rồi đi tiếp — kho đứng yên nguyên đêm mà pipeline vẫn XANH.

Giả định đã chết đứng sau cửa đó: nó sinh ra thời kho nằm trên Dropbox dùng
chung, khi ấy "máy khác đã sync" ĐÚNG là "kho đã mới". Bỏ Dropbox rồi thì câu
đó thành sai. Nay khác máy ⇒ KHÔNG bỏ qua. Kho thật sự dùng chung (mount
mạng) thì bật lại hành vi cũ bằng `VNSTOCK_SHARED_WAREHOUSE=1`.
Vết cũ chưa có trường `last_machine` thì giữ hành vi cũ (không biến thành
"luôn chạy lại"). Lưới: `tests/test_pipeline_status_gate.py` 7 test.

## Bom thứ hai cùng loại, CHƯA vá: `brief_push.json`

Marker chống gửi trùng cũng nằm trong kho và cũng không có trường máy. Laptop
lỡ chạy `run.py telegram close` hôm nào là desktop câm brief hôm đó, mà
`cmd_brief` vẫn `return 0` (pipeline xanh, không ai biết).

## Hai badge đang nói dối sau lượt chép

`test_status.json` và `doctor_status.json` KHÔNG có trường máy
(`run.py:858-867`, `vnstock_doctor.py:979-983`). Badge sidebar trên desktop
hiện đang hiển thị kết quả test/doctor **của laptop**, không có cách nào phân
biệt ngoài `ran_at`.

# ✅ V1. CỬA GÁC LỆCH CƠ SỞ Ở ĐƯỜNG GHI CHÍNH — XONG 19/08

`vnstock_basis_guard.py` + wire vào `vnstock_updater.update_ticker`. 19 test
(`tests/test_basis_guard.py`, đã vào `--fast`). Suite 2.256 / fast 1.736.

**Chỗ đặt guard là điểm chính của thiết kế.** Bộ quét `--sweep` là phát hiện
SAU — mỗi mùa quyền lại phải chữa lại ngần ấy mã. `update_ticker` là chỗ DUY
NHẤT biết cùng lúc "kho trước khi ghi" và "nguồn sau khi ghi".

**Cách chạy:**
1. Nới cửa sổ fetch lùi `LOOKBACK_DAYS = 30` ngày lịch (~20 phiên). **Không
   tốn thêm lần gọi mạng nào** — cùng một call, chỉ khác tham số `start`.
2. So trung vị tỉ lệ kho/nguồn trên vùng chồng lấn, **bỏ HẲN bar `last_date`**
   — đúng bar đó có thể DỞ DANG (updater từng chạy trong phiên, VCI trả daily
   bar partial). Đó là nguồn báo động giả đáng kể duy nhất ở ngưỡng 1,2%.
3. Lệch > `TOL = 0.012` ⇒ **KHÔNG nối**, ghi mã vào
   `_meta/basis_drift_pending.json`, in cảnh báo đỏ, `status="basis_drift"`.
4. Bình thường ⇒ **cắt `new_df` lại về >= `fetch_from`** rồi merge y như cũ —
   phần nới thêm CHỈ để đối chiếu, kho không dày thêm một bar nào.

**Ba quyết định đáng ghi lại:**
* **Cách ly, KHÔNG tự ghi đè.** Sync chạy 3h sáng không ai nhìn; tự động viết
  lại 20 năm lịch sử lúc đó là đúng loại hành động không nên tự làm. Mất một
  ngày dữ liệu của một mã thì chữa xong lần sync sau tự lấy lại; một bậc giả
  im lặng thì không.
* **Ngưỡng 1,2% = `probe_price_basis.SAME_BASIS_TOL`**, có test canh hai bên
  bằng nhau. Lệch nhau là sinh ra mã guard cho qua mà bộ quét gắn cờ (hoặc
  ngược lại) — đúng cái bẫy đã vấp với 5 mã CTG/DPG/MWG/NLG/VPB. Ngưỡng 8% của
  nhánh fallback quá thô: nó lọt sạch 70 mã vừa rồi.
* **Kho sự kiện quyền chỉ để GHI KÈM, không để bật/tắt báo động.** Sổ đang
  mỏng (70 mã lệch chỉ 3 mã tra ra loại) nên tra không ra vẫn phải kêu.

**Guard KHÔNG làm 70 mã ngừng cập nhật trên máy chưa chữa** — điểm này quan
trọng, đã kiểm bằng số học: sau sự kiện quyền, mỗi đêm merge `keep="last"` đẩy
ranh giới lên một phiên, nên bar gần đây của kho về cơ sở mới trong ~1 phiên.
Qua `LOOKBACK_DAYS` là vùng chồng lấn sạch và guard im. Nó bắt đúng KHOẢNH KHẮC
lệch sinh ra, không bắt di chứng cũ.

**Xoá khỏi sổ là việc của bộ chữa, không phải của sync.** `rebase_ticker_history`
gọi `clear_drift` sau khi tự kiểm xanh. Updater chạy 8 worker; cho nó đọc-sửa-ghi
sổ 1.700 lần mỗi đêm là tự chuốc lost-update vào đúng thứ sinh ra để giữ.
Ghi sổ có `threading.Lock` + ghi nguyên tử.

**Badge doctor:** `check_basis_drift` — warn kèm tên mã + tỉ lệ + lệnh chữa.
`VNSTOCK_BASIS_GUARD` cũng đã vào danh sách kill-switch nguy hiểm của doctor,
nên tắt guard là badge kia kêu.

**Hai test cũ phải sửa theo, đều là test canh SAI THỨ:**
* `test_updater_partial_bar` canh `start == "2026-06-10"` — canh chi tiết cài
  đặt. Bất biến thật là "fetch BAO GỒM bar cuối"; cửa sổ mới là superset nên
  bar dở vẫn được lành. Đổi thành `start <= ...`.
* `test_doctor::test_tests_badge_states` đỏ/xanh theo **GIỜ TRONG NGÀY**: nó
  cắm `ran_at = hôm nay 10:00` rồi để `_code_changed_after` quét mtime file
  repo THẬT — chạy trước 10:00 thì xanh, sau 10:00 mà vừa sửa file nào là đỏ
  (vấp lúc 11:51). Nay monkeypatch `_code_changed_after`, và tách một test
  RIÊNG cho nhánh đó với repo giả + mtime dựng tay.

# 🔴🔴 U10. LỆCH CƠ SỞ LÀ CHUYỆN HỆ THỐNG — 70/159 MÃ (44%) UNIVERSE THANH KHOẢN

Quét `probe_price_basis --sweep` trên laptop 19/08 (GTGD20 ≥ 5 tỷ, cửa sổ 365
ngày): **70/159 mã lệch cơ sở**, gồm gần trọn VN30 — HPG 1.1201× · SSI 1.2511×
· TCB 1.0210× · VPB 1.0178× · MWG 1.0155× · MBB 1.2487× · ACB 1.1606× · CTG
1.0154× · NVL 1.0750× · VND 1.0289× · VJC 1.3001× … Ngày vách rải từ 03 tới
08/2026, đúng mùa ĐHCĐ/chia cổ tức. Biên độ 1.5% (cổ tức tiền mặt) tới 2.0000×
(F88, chia tách).

**HỆ QUẢ PHẢI ĐỐI MẶT — đây mới là phần quan trọng, không phải chuyện vệ sinh
dữ liệu:**
* Backtest 365-730 ngày của **44% universe** đang chạy trên chuỗi giá có bậc
  giả. Mọi cửa sổ bắc qua ngày vách đều thấy một cú rơi/nhảy KHÔNG CÓ THẬT.
* ⇒ **Kiểm định chống-ăn-may hiện tại KHÔNG đáng tin**, kể cả #32 (p=0.012,
  n=94) — nó được chấm trên dữ liệu này. Sau khi chữa kho PHẢI chạy lại
  backtest/kiểm định rồi mới bàn tiếp về tầng B hay theo dõi live.
* Screener lọc thanh khoản bằng close×volume cũng lệch theo ở phần lịch sử.
* Vì sao không ai thấy suốt bao lâu nay: `check_unit_continuity` nhìn VÁCH GIÁ
  (≥30%) nên mù; giá vẫn liền mạch, vẫn khớp giá live, mã vẫn được báo "sạch".

**Vì sao xảy ra (đã biết từ 18/08, nay rõ quy mô):** nguồn back-adjust TOÀN
chuỗi sau mỗi sự kiện quyền, còn `update_ticker` chỉ fetch từ `_get_last_date`
— KHÔNG có đường nạp lại lịch sử. Nên mỗi lần một mã trả cổ tức là kho lại lệch
thêm một bậc. Đây chính là mục **V1** (chặn tái phát): trước đây xếp "đáng làm
nhất còn lại", nay là **BẮT BUỘC** — chữa 70 mã mà không chặn thì mùa cổ tức
sau lại đúng ngần ấy.

**Công cụ đã sẵn (19/08):**
* Quét: `python scripts/probe_price_basis.py --sweep` (ghi vết
  `_meta/basis_sweep_check.json`).
* Chữa hàng loạt: `python scripts/rebase_ticker_history.py --from-sweep`
  (mặc định CHẠY THỬ; thêm `--apply` mới ghi). Mỗi mã vẫn qua đủ cửa gác:
  probe phải phán `warehouse_basis`, có sao lưu + tự kiểm riêng, và dòng TỔNG
  KHÔNG gộp "chưa chữa được" vào "xong".
* `rebase` nay tự dò được vách cỡ cổ tức (`_basis_break_of` → dùng chung
  `find_basis_step` với chế độ quét, một nơi định nghĩa).

**Chạy thử lần 2 sau khi vá (19/08 15:23): 70/70 mã chữa được**, chỉ còn 3 mã
nhân khối lượng — HCM (bậc/hệ số 1.01) · KLB (0.96) · SSB (1.04), đều có bằng
chứng khớp thật. 5 mã suýt bị nhân oan (HSG 0.71 · SSI 0.73 · VJC 0.70 ·
VTP 0.72 · TCX 0.82) nay giữ nguyên.
**Sai số CHẤP NHẬN có ý thức:** khi kho sự kiện xác nhận split/bonus mà bằng
chứng volume lại ngược (PET: bonus, hệ số 1.4499, bậc 0.43) — hoặc chia tách
rõ ràng mà bậc lệch (F88 2.0000×, bậc 3.08) — công cụ GIỮ NGUYÊN volume. Hệ
quả: GTGD lịch sử của mấy mã đó thấp hơn thực tế đúng bằng hệ số. Đây là lỗi
CÓ BIÊN, chỉ chạm bộ lọc thanh khoản, và được IN RA từng ca — đổi lại không
bịa ra khối lượng. Muốn sửa từng mã thì `--ticker <MÃ> --volume adjust`.

**Thứ tự làm (⇄ CẢ HAI MÁY, desktop trước vì nó sinh khuyến nghị):**
1. `--from-sweep` chạy thử, đọc xem mã nào bị từ chối và vì sao.
2. `--from-sweep --apply`.
3. Quét lại `--sweep` → kỳ vọng 0 mã.
4. Chạy lại backtest/kiểm định; coi mọi verdict trước 19/08 là VÔ HIỆU.
5. Làm V1 trước mùa cổ tức tới.

**CHẠY THẬT LẦN ĐẦU — LAPTOP 19/08 15:43→15:51 (`--from-sweep --apply`).**
Nhận dạng máy bằng BẰNG CHỨNG chứ không đoán: lệnh chạy được `--from-sweep`
mà không cần quét trước ⇒ vết quét có sẵn ⇒ laptop; và lượt quét lại đếm
159 + 1.564 + 1.402 = 3.125 thư mục mã, đúng con số laptop đã báo.

* Ghi: **70/70 mã**, mỗi mã một backup `_meta/backup_rebase/<MÃ>_<lúc>`.
* Quét lại ngay sau đó: **68 sạch · CÒN 2** — VTP `0.8521×` và QNS `0.9785×`,
  cả hai cùng vách `2026-03-17`. Hai mã này in `✅ chuỗi đã liền` lúc ghi.

**Hai lỗi THẬT của bộ công cụ, lộ ra đúng nhờ lượt chạy thật này:**

1. **Chữa không hội tụ với mã bị rebase NHIỀU LẦN.** Số học ép ra nguyên nhân,
   không phải phỏng đoán: vòng ghi chỉ đụng `time < brk` và lấy THẲNG giá
   nguồn, nên sau khi ghi mọi bar trước vách bằng nguồn từng đồng ⇒ tỉ lệ
   phía trước = 1.0. Quét lại vẫn ra bậc `0.8521×` tại đúng ngày cũ ⇒ phía SAU
   vách đang ở `1/0.8521 = 1.1736×`. Tức mã có **hai bậc** (hai mùa quyền), bộ
   dò chỉ chỉ vào bậc mạnh nhất, chữa tới đó là bỏ nguyên lớp GIỮA. Chạy lại
   lệnh cũ là **no-op**: bộ dò vẫn chỉ đúng ngày ấy, tool ghi lại phần đã đúng.
   → Vá: hàm thuần `last_divergent_day` — mốc chữa là **bar lệch nguồn CUỐI
   CÙNG** (bỏ bar hôm nay vì phiên chưa đóng), không phải ngày vách. Hệ số
   khối lượng vẫn chỉ áp cho phần TRƯỚC vách (bar sau vách đã đếm trên số cổ
   phiếu mới).
2. **Tự kiểm mù đúng lớp lỗi nó sinh ra để chữa.** Tự kiểm cũ chỉ gọi
   `find_jumps` (vách GIÁ ≥30%) nên in `✅` cho VTP/QNS trong khi tỉ lệ còn
   lệch 17%. → Vá: thêm `_residual_basis_step` — đọc lại kho vừa ghi, đo lại
   tỉ lệ bằng chính `find_basis_step`, còn bậc thì in ⚠️ và trả rc=1.

Lưới: `tests/test_rebase_history.py` 36 test — cầu thang 3 bậc phải liền sau
MỘT lượt, và khi ép về hành vi cũ thì phải báo ⚠️ chứ không được in ✅.
Suite: **2.236 passed** (fast 1.716).

**Việc còn lại của lượt này:** chạy lại đúng 2 mã trên LAPTOP bằng code mới
(`--ticker VTP --ticker QNS --apply`), rồi `--sweep` kỳ vọng 0. DESKTOP chưa
làm gì cả — phải `--sweep` trước vì `basis_sweep_check.json` là file local
từng máy (kho nằm trong `.gitignore`).

**U9. 🔴 LỚP LỖI MỚI: lệch cơ sở cỡ CỔ TỨC (2-5%) — bộ quét MÙ hoàn toàn.
Phát hiện tình cờ 19/08 khi test thư viện.**
`probe_price_basis --ticker VNM` (VN30, blue chip) cho:
kho/nguồn **1.0327× tới 2026-06-22**, rồi **1.0000× từ 2026-06-23**.
⇒ Toàn bộ lịch sử VNM trước 23/06 đang ở cơ sở CŨ, lệch **3,27%** — cỡ một lần
trả cổ tức tiền mặt (~1.850đ trên giá ~57.000).
**Vì sao lọt lưới:** `check_unit_continuity` chỉ bắt vách ≥30% giữa hai phiên
kề nhau (JUMP_PCT). Bậc 3,27% nằm sâu dưới ngưỡng, nên VNM được báo
"✅ không vách đứt đáng ngờ · khớp giá live 1.00×" — bar GẦN ĐÂY đúng, chỉ
LỊCH SỬ sai, mà quét liên tục không nhìn vào tỉ lệ kho/nguồn.
**Hậu quả:** backtest bắc qua 23/06 thấy VNM rơi giả 3,2%. Với tầng vị thế
(lookback 730 ngày) thì mọi cửa sổ đều bắc qua. Đây là mã VN30 — chắc chắn
nằm trong universe chiến lược.
**✅ VNM ĐÃ CHỮA trên LAPTOP 19/08 14:42** (5.089 bar lấy thẳng nguồn, khối
lượng GIỮ NGUYÊN, backup `VNM_20260819-144220`, 21 file nguyên tử; probe lại
ra **1.0 ở TỪNG BAR**). ⏳ **DESKTOP chưa chữa.**

**Còn bao nhiêu mã như vậy — nay ĐÃ CÓ công cụ trả lời:**
`python scripts/probe_price_basis.py --sweep` (19/08). Quét universe thanh
khoản (mặc định GTGD20 ≥ 5 tỷ, cửa sổ 365 ngày, mỗi mã 1 lần gọi nguồn, nghỉ
0,3s). Lõi là hàm THUẦN `find_basis_step`: bước 1 tìm điểm tỉ lệ kho/nguồn nhảy
mạnh nhất (rẻ, O(n)); bước 2 XÁC NHẬN bằng trung vị hai phía — bar lỗi đơn lẻ
làm bước 1 kêu nhưng không đổi được trung vị nên bị loại. Ngưỡng
`BASIS_STEP_TOL = 1,5%` (dưới đó là nhiễu làm tròn/bước giá).
Ra mã nào thì chữa bằng `rebase_ticker_history --ticker <MÃ> --break-date <ngày>`.
Có ghi vết `_meta/basis_sweep_check.json` (cùng hợp đồng với bộ quét kia; badge
doctor CHƯA nối — làm sau khi có kết quả thật để không dựng badge trống).
**Đã làm được phần công cụ:** `rebase_ticker_history` nay nhận `--break-date`
(trước đây chỉ tự dò ≥30% nên KHÔNG với tới lớp lỗi này).
Chữa VNM (⇄ CẢ HAI MÁY):
`python scripts/rebase_ticker_history.py --ticker VNM --break-date 2026-06-23`
Dry-run 19/08: **5.089/5.089 bar lấy thẳng từ nguồn, 0 bar nhân hệ số** (nguồn
phủ từ 2006-01-19, đúng bằng điểm đầu của kho) — phần GIÁ hoàn hảo.

**NHƯNG dry-run đó suýt làm hỏng KHỐI LƯỢNG, đã vá kịp:** heuristic `--volume
auto` định NHÂN volume 5.089 bar × 1.0327 với lý do "bậc nhảy volume ≈ hệ số
giá". Sai: 1.0327 là **cổ tức TIỀN MẶT**, không tạo thêm cổ phiếu nào — nhân
lên là bịa ra 3,27% khối lượng chưa từng khớp. Lỗ hổng của heuristic: điều
kiện "gần bằng" ở hệ số 1.03 thoả với MỌI bậc nhảy trong 0.67-1.39×, tức toàn
bộ dao động khối lượng thường ngày; 1.95× của VHM mới là tín hiệu thật.
**Đã vá:** rebase nay TRA SỰ KIỆN QUYỀN trước (`match_corp_action` →
`vnstock_adjust.load_events`): `cash` → không bao giờ nhân; `split`/`bonus` →
được phép nhân; không tra được VÀ hệ số < `VOL_SIGNAL_MIN_FACTOR` (1.15) →
giữ nguyên và nói rõ vì sao. Ép tay vẫn còn `--volume adjust`.
⇒ Dry-run sau khi vá (19/08 14:39) in đúng: `sự kiện quyền quanh vách: cash
-> KHÔNG đổi số cổ phiếu` rồi `GIỮ NGUYÊN khối lượng`. Kho sự kiện quyền
XÁC NHẬN đây là cổ tức tiền mặt — chẩn đoán 1.0327× không còn là suy luận
từ độ lớn nữa mà có bản ghi hậu thuẫn. An toàn để `--apply`.

**✅ Xác nhận 19/08 cuối ngày: CẢ HAI máy đều đang ở 4.0.4 / vnai 2.4.8.**
Warning pytest trên desktop lẫn laptop đều in `Current: 4.0.4`. Ghi chú "laptop
đã nâng xong, desktop chờ soak" là SAI — laptop nâng rồi LÙI ngay trong ngày để
chạy probe. Không có cuộc soak nào; mục này chờ BẢN VÁ của nhà cung cấp
(4.0.7+), không chờ thời gian.

**U8. ⛔ BẢN NÂNG 4.0.6 LÀM HỎNG ĐƯỜNG FETCH — LÙI LẠI, KHÔNG NÂNG DESKTOP
(19/08).** Sau khi nâng laptop, mọi lượt fetch nguồn đều nổ
`RuntimeError: RetryError[... raised UnboundLocalError]` ở nhánh SPONSOR
(`vnstock_data`). Đã loại trừ từng biến số một, không đoán:
* KHÔNG phải code repo: `_fetch_prices` (vnstock_updater.py:278) khởi tạo
  `df, last_exc = None, None` ngay đầu hàm → UnboundLocalError đến từ TRONG
  thư viện, bị tenacity bọc thành RetryError.
* KHÔNG phải ngày tương lai: cắt cửa sổ về hôm nay (`→ 2026-08-19`) vẫn nổ.
* KHÔNG phải phiên đang dở: khoảng QUÁ KHỨ HOÀN TOÀN (2026-06-01 → 2026-07-31)
  cũng nổ.
* Trước khi nâng, CÙNG đường fetch chạy tốt 3 lượt: XDH (45 bar), VVS probe,
  VVS rebase (956 bar).
⇒ **Desktop giữ nguyên vnstock 4.0.4 / vnai 2.4.8 / vnii 0.2.4.** Lùi laptop:
`python -m pip install vnstock==4.0.4 vnai==2.4.8`, rồi chạy lại
`probe_price_basis --ticker VNM --break-date 2026-07-01` để xác nhận sống lại.
**BÀI HỌC (đắt nếu bỏ qua):** đây đúng là lý do thử trên laptop trước. Nâng
thẳng desktop thì lỗi này nổ lúc 18:00 GIỮA pipeline, ở bước sync — mất cả đêm
data lẫn brief, và phải gỡ trong lúc gấp. Bộ test 2.201 KHÔNG bắt được vì nhánh
sponsor không có test nào chạm tới (mục T-c).
**NGUYÊN NHÂN GỐC — đã có traceback, không còn phải đoán:**
```
vnstock/core/utils/env.py:136  in get_hosting_service()
    return hosting_service
UnboundLocalError: cannot access local variable 'hosting_service'
                   where it is not associated with a value
```
Chuỗi gọi: `send_request` (client.py:159) → `is_colab()` (env.py:34) →
`get_hosting_service()` (env.py:136). Hàm này rõ ràng gán `hosting_service`
trong các nhánh nhận diện môi trường (Colab/Kaggle/…) mà **thiếu nhánh mặc
định cho máy thường**, nên trên PC Windows nó rơi thẳng xuống `return` với
biến chưa gán.
⇒ **`send_request` là helper HTTP DÙNG CHUNG**, nên MỌI lệnh gọi mạng của
vnstock 4.0.6 đều chết — kể cả đường `Quote` mới mà chính thư viện khuyến nghị
thay cho `Vnstock().stock()` đã deprecated. Không có đường vòng trong code
repo; `_fetch_prices` có nhánh dự phòng dùng `Quote` nhưng nhánh đó cũng đi qua
`send_request`.
⇒ Kết luận: **vnstock 4.0.6 không dùng được trên máy local.** Lùi về 4.0.4.

**Báo ngược lên tác giả (tuỳ user, nội dung đã sẵn):** "vnstock 4.0.6,
Windows/Python 3.13, không phải môi trường hosting nào. Mọi call mạng chết ở
`core/utils/env.py:136 get_hosting_service()` — `UnboundLocalError:
hosting_service`. Có vẻ thiếu nhánh gán mặc định khi không nhận ra hosting
service. 4.0.4 không bị."

**Ghi chú phụ từ cùng output:** gói sponsor cũng có bản mới
(`vnstock_data 3.2.1→3.2.8`, `vnstock_news 2.2.1→2.2.2`,
`vnstock_pipeline 2.2.5→2.3.2`, cài qua `vnstock-installer`) — CHƯA thử, và
đừng thử chung lượt với việc khác.

**U4. ✅ NÂNG THƯ VIỆN — LAPTOP XONG 19/08, desktop chờ soak.**
`vnstock 4.0.4→4.0.6 · vnai 2.4.8→2.5.7 · vnii 0.2.4→0.2.5` trên laptop
`CFA-BINHLD-LT`: cài trót lọt (vnii build từ sdist), **2.196 passed** y nguyên,
`check_unit_continuity` vẫn đọc kho đúng (50/50 mã liên tục). Đây là bằng chứng
mạnh vì laptop chạy nhánh SPONSOR (`vnstock_data`) — nhánh mà bộ test không
chạm tới.
⏳ **DESKTOP: CHƯA nâng, và CỐ Ý chưa.** Để laptop chạy vài ngày đã; nâng
desktop thì tuyệt đối không sát 18:00, và nâng xong phải `run.py doctor --net`
+ full suite ngay. Lùi lại: `pip install vnstock==4.0.4 vnai==2.4.8`.

**U4-cũ (bối cảnh)** — vnstock 4.0.4→**4.0.6**, vnai 2.4.8→**2.5.7**, vnii
0.2.4→0.2.5. **Đính chính mô tả cũ**: repo KHÔNG pin bản nào — `requirements.txt`
chỉ có `vnstock>=3.5.0`, vnai/vnii không hề được khai (dep gián tiếp). Nâng là
việc `pip` trên máy thật, không đụng file repo. Tin có ích: container NÀY đang
chạy đúng vnstock 4.0.6 + vnai 2.5.7 và 2.148 test XANH — nhưng chỉ chứng minh
được nhánh FREE (vnstock_data và vnii đều MISSING ở đây, tức nhánh sponsor chưa
ai thử). Nâng xong: `run.py doctor --net` + full suite ngay, KHÔNG sát giờ pipeline.

**U5. Quan sát dài hạn** — OpenRouter nạp $10 (ledger có cột `last_error`,
`python vnstock_llm_ledger.py --show`) · chất lượng brief 4 giọng auto-score
(mốc 11/08: 0.830 / 0.834 / 0.862 / 0.836) · badge 🩺 doctor chỉ hành động khi warn.

## 🚪 CHỜ CỔNG hoặc CHỜ USER QUYẾT

**V1. Chặn TÁI PHÁT lệch cơ sở — việc kỹ thuật đáng nhất còn lại** (~1 buổi,
CHỜ USER CHỐT THIẾT KẾ vì đụng đường ghi kho). Đối soát ✅: `reconcile_fallback_df`
có ĐÚNG 1 điểm gọi, ở nhánh fallback (`vnstock_updater.py:441` trong khối
`if use_fb and new_df is None`); đường VCI chính đi thẳng :419 → merge :463-480
với `drop_duplicates(keep="last")` = đè im lặng. **Tin tốt chưa ghi lần trước:
hạ tầng quarantine ĐÃ cắm sẵn vào đúng đường ghi của cả 2 nguồn**
(`vnstock_updater.py:170-190`), nên chỉ cần thêm phép so bar overlap — rẻ hơn
tưởng. Cần chốt: ngưỡng lệch bao nhiêu, có tra lịch sự kiện quyền không,
quarantine hay chỉ cảnh báo.

**V2. Tầng B — danh mục xoay vòng tháng** (nhiều buổi). Cổng "có chiến lược đạt"
ĐÃ MỞ (#32); cổng "tầng A chạy ổn vài đêm train tự động" **vẫn ở mốc 0** — chưa
đêm nào chạy trọn tới brief. Đối soát ✅: chưa có một dòng code nào cho tầng B
(khái niệm "tier" đang có là short/position của tầng A, đừng nhầm).

**V3. Backtest không mô phỏng ràng buộc thị trường VN** (~1 buổi, cần user chốt).
`vnstock_strategy.py:949-960` cho ĐÓNG LỆNH NGAY BAR KẾ TIẾP (T+1, thực tế VN là
T+2,5) và :963-977 vẫn tính P&L SHORT cho tín hiệu sell (VN không bán khống).
Đụng thẳng vào số liệu gating nên phải bàn trước.

**V4. Đếm hai lần nhóm tuỳ biến** (Ngân hàng 26 vs drill-down 27, lệch EIB) —
user chốt TẠM GIỮ. **Bổ sung làm ước lượng đúng hơn**: sửa xong sẽ LÀM ĐỎ một
test đang khoá chính hành vi đếm-hai-lần, nên không chỉ là "thêm 1 điều kiện lọc"
(`vnstock_sectors.py:174-175`).

**V5. Brief SÁNG không có task tự động** (~30' + user chạy lại ps1 quyền Admin).
Treo từ 20/07. Nửa tính năng quảng cáo ở đầu CLAUDE.md ("brief sáng/chiều") chưa
bao giờ tự chạy; đường gửi tay `run.py telegram morning` (run.py:959-961) KHÔNG
có cửa gác nào — không kill-switch, không check giờ, không marker (marker chỉ
mang key `"close"`, run.py:1129-1130) → gõ 2 lần là 2 brief, gõ 8h sáng vẫn gửi.
Chi tiết đáng biết: `generate_brief` CÓ cửa gác 11:30 (vnstock_brief.py:3345-3348)
nhưng `_brief_snippet` hardcode `force=True` (vnstock_telegram.py:217) nên đường
Telegram CỐ Ý vượt gác. Nút "🌅 Morning Brief" trên dashboard
(dashboard/brief_run_panel.py:18,29-31) thì có gác 11:30 nhưng chỉ render ra UI,
không đụng Telegram. Cần user chốt GIỜ bắn (đề xuất cũ 11:35-11:40 T2-T6).

**V6. Chuẩn hoá đơn vị penny trong đường phát rec** (~1 buổi, cần user chọn
hướng). Bẫy "chuẩn hoá PER-BAR" với mã quanh mốc 500 VND (return giả tới ±96,9%)
mới vá ở preset_score / networth / candle_patterns; đường `_load_history` của
backtest/emit rec CHƯA. Hai hướng: áp `_stitch_units` vào `_load_history`, hoặc
loại hẳn penny khỏi universe phát rec.

**V7. Ngày lễ GIỮA TUẦN** (~30' nếu chỉ cần danh sách cấu hình được).
`_close_session_date` (run.py:1136-1146) không biết lịch nghỉ → tối ngày lễ
pipeline vẫn bắn "brief chiều phiên hôm nay" dựng trên dữ liệu phiên trước.
1-2 ca/năm — user quyết có đáng làm không.

**V8. Kho giá chưa bao giờ kiểm nhất quán điều chỉnh cổ tức** (~1 buổi, máy thật).
`vnstock_adjust.py:31-33` ghi rõ tầng back-adjust từng viết ra nhưng CHƯA BAO GIỜ
nối vào production. Cùng họ với V1.

## 🔍 CHỜ MẮT NGƯỜI — chỉ làm được trong giờ giao dịch

**W1. Heatmap VN30 live có SỐ THẬT trong phiên** — chuỗi vá cờ `live_mode` đã
đóng về mặt code + Playwright, nhưng chưa entry nào ghi nhận đã nhìn tận mắt
trong phiên. Làm trong 9h15-14h30 T2-T6 trên desktop: bật 🔴 Live Mode ở sidebar
trái → mở tab Thị trường.

## 🩹 ĐÍNH CHÍNH SỔ (đã sửa trong bản này)

* Số test lệch ở **4 bề mặt**, đã sửa hết: CLAUDE.md (~1.436/~1.898) và
  run.py:672 (~1.034) ở commit f3f95ff; `docs/ECC-SETUP-DESKTOP.md:100` (~1.300)
  và `.claude/rules/python/testing.md:15-16` (~1.034/~1.561) ở commit sau đó.
  CHƯA có lưới canh số này — sẽ trôi lại mỗi lần thêm test (ứng viên cho S-list).
* Mục B và mục J từng ghi lệch 1 ngày cho cùng chuỗi đo sync — bản này thống nhất
  theo J (khớp mục A): 4.429s là phát bị kill **tối 17/08**.
* R6: **9** khối header rác mỗi phát full suite (không phải 10 như tôi sửa nhầm
  giữa chừng); `--fast` không dính.
* N/U4: repo không pin phiên bản nào.

## 🔧 NẾP GIT — bẫy đã vấp 2 lần

User làm việc trên `main` cục bộ, Claude push lên nhánh feature → `git pull` báo
**"Already up to date"** DÙ vừa tải commit mới về. Lấy code mới phải dùng
`git fetch origin <nhánh> && git merge origin/<nhánh>`. Nghi máy chạy code cũ →
`git log --oneline -1` đối chiếu commit cuối Claude báo.

## ⚠️ BÀI HỌC VẬN HÀNH

Đừng gõ lệnh nặng vắt qua giờ pipeline 18:00 (17/08: `0xC000013A` · 18/08:
`267014`). Làm buổi tối thì làm TRƯỚC 18:00, hoặc chờ thấy dòng `⏱ TỔNG` trong
`run_daily.log` rồi mới gõ tiếp. **Nhưng lưu ý U3**: nguyên nhân số 1 có thể
không phải bạn, mà là trần 120 phút của task.
